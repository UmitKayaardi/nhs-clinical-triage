"""
Offline evaluation CLI (CN7050 WP1). Fixed seed 42 everywhere.

  python scripts/evaluate.py --all                 # everything; LLM calls limited by --max-llm-calls
  python scripts/evaluate.py --all --offline       # reproduce all numbers from the committed cache, no API calls
  python scripts/evaluate.py --llm-only            # only fill the LLM cache (resumable)
  python scripts/evaluate.py --no-llm              # LLM-free systems only

Options: --max-llm-calls N (default 150 real API calls per run), --ktas-llm-sample N (per class, default 40).
When the Groq daily quota or the per-run budget is reached the run stops cleanly, writes everything
it can, and prints the command to resume (cached calls are never repeated).
"""

import argparse
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from evaluation.llm_cache import CachedCompletion  # noqa: E402
from evaluation.runner import LLM_JOBS, load_all, quiet, run_llm_jobs  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description="CN7050 offline evaluation")
    p.add_argument("--all", action="store_true", help="run every stage")
    p.add_argument("--llm-only", action="store_true", help="only run the LLM systems (fills the cache)")
    p.add_argument("--no-llm", action="store_true", help="skip LLM systems")
    p.add_argument("--offline", action="store_true", help="never call the API; cache only")
    p.add_argument("--max-llm-calls", type=int, default=150)
    p.add_argument("--ktas-llm-sample", type=int, default=40, help="KTAS LLM sample size per class")
    p.add_argument("--jobs", default="", help="comma-separated LLM job names to run (default: all, in order)")
    args = p.parse_args()
    if not (args.all or args.llm_only or args.no_llm):
        p.error("choose --all, --llm-only or --no-llm")

    quiet()
    start = time.time()
    bundle = load_all()
    completion = CachedCompletion(max_calls=args.max_llm_calls, offline=args.offline)
    print(f"Cache: {len(completion)} entries. Budget this run: {args.max_llm_calls} API calls"
          + (" (offline)" if args.offline else ""), flush=True)

    llm_results, llm_complete = {}, True
    if not args.no_llm:
        wanted = [j.strip() for j in args.jobs.split(",") if j.strip()]
        jobs = [j for j in LLM_JOBS if not wanted or j.name in wanted]
        llm_results, llm_complete = run_llm_jobs(bundle, completion, args.ktas_llm_sample, jobs)

    if args.all or args.no_llm:
        from evaluation.report import build_everything  # heavy imports only when needed
        build_everything(bundle, llm_results, completion.stats(), llm_complete, args)

    print(f"LLM stats: {completion.stats()}")
    if not args.no_llm and not llm_complete:
        done = sum(r["n_done"] for r in llm_results.values())
        total = sum(r["n_target"] for r in llm_results.values())
        print(f"\nLLM runs incomplete: {done}/{total} cases have results ({total - done} remaining, "
              f"each needs >= 1 API call).")
        print("Resume after the quota resets (Groq free tier: daily limits) with:")
        print(f"  python scripts/evaluate.py {'--all' if args.all else '--llm-only'} "
              f"--max-llm-calls {args.max_llm_calls} --ktas-llm-sample {args.ktas_llm_sample}")
    print(f"Finished in {time.time() - start:.0f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
