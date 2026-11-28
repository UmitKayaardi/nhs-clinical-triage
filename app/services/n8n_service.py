"""
Agent 5 -- Orchestrator & Action Agent, n8n channel (WP5).

The submitted workflow routes alerts through an n8n workflow engine. When
N8N_WEBHOOK_URL is set, Agent 5 POSTs a JSON event to the n8n webhook
(`n8n/triage_alert_workflow.json`), which checks the shared secret, decides
whether to alert, and sends the WhatsApp message with its own Twilio node
(or returns "mocked" in test mode). If n8n is not configured or cannot be
reached, the caller falls back to the direct Twilio path.

Request:  POST {N8N_WEBHOOK_URL}
          header X-Webhook-Secret: {N8N_WEBHOOK_SECRET}
          {session_id, severity, chief_complaint, reasoning, news2_score,
           low_evidence, created_at, message, test_mode}
Response: {status: "sent" | "mocked" | "skipped" | "failed", channel: "n8n", message_sid}
Timeout N8N_TIMEOUT_SECONDS (5 s), N8N_MAX_RETRIES retries (2) on network errors and 5xx.
"""

import logging
import time
from typing import Callable, Dict, Optional

import requests

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)


class N8nUnavailable(Exception):
    """n8n is not configured, unreachable, or returned an error."""


class N8nOrchestrator:
    def __init__(self, settings: Optional[Settings] = None, post: Callable = requests.post,
                 sleep: Callable[[float], None] = time.sleep):
        self.settings = settings or get_settings()
        self._post = post
        self._sleep = sleep

    @property
    def configured(self) -> bool:
        return bool(self.settings.N8N_WEBHOOK_URL)

    def health(self) -> Dict:
        """Reachability check for the Admin tab (GET on the n8n base URL)."""
        if not self.configured:
            return {"configured": False, "reachable": False}
        base = self.settings.N8N_WEBHOOK_URL.split("/webhook")[0]
        try:
            r = requests.get(f"{base}/healthz", timeout=2)
            return {"configured": True, "reachable": r.status_code == 200}
        except requests.RequestException:
            return {"configured": True, "reachable": False}

    def send(self, event: Dict) -> Dict:
        if not self.configured:
            raise N8nUnavailable("N8N_WEBHOOK_URL not set")
        headers = {"Content-Type": "application/json"}
        if self.settings.N8N_WEBHOOK_SECRET:
            headers["X-Webhook-Secret"] = self.settings.N8N_WEBHOOK_SECRET
        attempts = self.settings.N8N_MAX_RETRIES + 1
        last_error: Optional[str] = None
        for attempt in range(1, attempts + 1):
            try:
                r = self._post(self.settings.N8N_WEBHOOK_URL, json=event, headers=headers,
                               timeout=self.settings.N8N_TIMEOUT_SECONDS)
                if r.status_code >= 500:
                    last_error = f"HTTP {r.status_code}"
                elif r.status_code >= 400:
                    raise N8nUnavailable(f"n8n rejected the event: HTTP {r.status_code}")
                else:
                    try:
                        body = r.json()
                    except ValueError:
                        body = {}
                    if isinstance(body, list):  # n8n may wrap the response item in a list
                        body = body[0] if body else {}
                    return {"status": body.get("status", "sent"), "channel": "n8n",
                            "message_sid": body.get("message_sid")}
            except requests.RequestException as exc:
                last_error = f"{type(exc).__name__}"
            logger.warning("n8n attempt %d/%d failed: %s", attempt, attempts, last_error)
            if attempt < attempts:
                self._sleep(0.5 * attempt)
        raise N8nUnavailable(f"n8n unreachable after {attempts} attempts: {last_error}")
