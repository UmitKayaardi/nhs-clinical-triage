"""
Cached, budgeted LLM completion for the offline evaluation.

- Every call is cached in evaluation/cache/llm_cache.jsonl, keyed by a
  SHA-256 of (model, messages, settings). Re-runs never call the API twice
  for the same input, so all numbers are reproducible from the committed cache.
- --max-llm-calls caps real API calls per run (cache hits are free).
- Groq free tier: 8,000 tokens/minute is respected by a sliding-window
  throttle; per-minute 429s are retried after a pause. A per-day limit
  (tokens or requests per day) raises BudgetExhausted so the run can stop
  cleanly and be resumed later with the same command.
"""

import hashlib
import json
import re
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from app.services import llm_service
from evaluation.common import CACHE_DIR

CACHE_PATH = CACHE_DIR / "llm_cache.jsonl"
TPM_LIMIT = 8000
EST_TOKENS_PER_CALL = 1700


class BudgetExhausted(Exception):
    """The run's --max-llm-calls budget or the provider's daily quota is used up."""


def cache_key(messages: List[Dict[str, str]], params: Dict) -> str:
    payload = json.dumps({"messages": messages, "params": params}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class CachedCompletion:
    def __init__(self, max_calls: int = 150, path: Path = CACHE_PATH, offline: bool = False,
                 tpm_limit: int = TPM_LIMIT):
        self.path = path
        self.max_calls = max_calls
        self.offline = offline            # True: never call the API (cache-only reproduction)
        self.tpm_limit = tpm_limit
        self.api_calls = 0
        self.hits = 0
        self.misses_offline = 0
        self.tokens_used = 0
        self._window: deque = deque()     # (timestamp, tokens)
        self._lock = threading.Lock()
        self._cache: Dict[str, Dict] = {}
        if path.exists():
            with path.open(encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        rec = json.loads(line)
                        self._cache[rec["key"]] = rec

    def __len__(self) -> int:
        return len(self._cache)

    def has(self, messages, params) -> bool:
        return cache_key(messages, params) in self._cache

    def _throttle(self) -> None:
        while True:
            now = time.time()
            while self._window and now - self._window[0][0] > 60:
                self._window.popleft()
            used = sum(t for _, t in self._window)
            if used + EST_TOKENS_PER_CALL <= self.tpm_limit:
                return
            time.sleep(max(1.0, 60 - (now - self._window[0][0]) + 0.5))

    def __call__(self, messages: List[Dict[str, str]], params: Dict) -> Tuple[str, Dict]:
        key = cache_key(messages, params)
        rec = self._cache.get(key)
        if rec is not None:
            self.hits += 1
            return rec["response"], {"latency_ms": rec.get("latency_ms"), "usage": rec.get("usage"), "cached": True}
        if self.offline:
            self.misses_offline += 1
            raise BudgetExhausted("cache miss in offline mode")
        if self.api_calls >= self.max_calls:
            raise BudgetExhausted(f"--max-llm-calls budget of {self.max_calls} reached")

        for attempt in range(6):
            self._throttle()
            try:
                content, meta = llm_service.groq_completion(messages, params)
                break
            except llm_service.LLMGenerationError as exc:
                cause = exc.__cause__
                text = str(cause or exc)
                status = getattr(cause, "status_code", None)
                if status == 429 or "rate limit" in text.lower():
                    if re.search(r"per day|\bTPD\b|\bRPD\b", text, re.IGNORECASE):
                        raise BudgetExhausted(f"provider daily limit reached: {text[:200]}")
                    wait = _retry_after(text) or 20.0
                    time.sleep(wait + 1.0)
                    continue
                if attempt < 2 and (status is None or status >= 500):
                    time.sleep(5.0)
                    continue
                raise
        else:
            raise BudgetExhausted("repeated per-minute rate limiting")

        self.api_calls += 1
        tokens = ((meta.get("usage") or {}).get("total_tokens")) or EST_TOKENS_PER_CALL
        self.tokens_used += tokens
        self._window.append((time.time(), tokens))
        rec = {
            "key": key,
            "created_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "model": params.get("model"),
            "params": params,
            "messages": messages,
            "response": content,
            "usage": meta.get("usage"),
            "latency_ms": meta.get("latency_ms"),
        }
        with self._lock:
            self._cache[key] = rec
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return content, {"latency_ms": meta.get("latency_ms"), "usage": meta.get("usage"), "cached": False}

    def stats(self) -> Dict:
        return {"cache_entries": len(self._cache), "cache_hits": self.hits, "api_calls": self.api_calls,
                "tokens_used_this_run": self.tokens_used, "budget": self.max_calls, "offline": self.offline}


def _retry_after(text: str) -> Optional[float]:
    m = re.search(r"try again in (?:(\d+)m)?([\d.]+)s", text)
    if not m:
        return None
    return (int(m.group(1)) * 60 if m.group(1) else 0) + float(m.group(2))
