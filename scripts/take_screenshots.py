"""
Automated report screenshots (WP9) with Playwright (headless Chromium).

Starts the app on a FRESH copy of the database (scripts/run_local_demo.py, never the committed DB),
captures its console log, runs the demo cases and saves full-page PNGs to report_assets/screenshots/.
Each demo triage costs one Groq call (about 7 in total).

  python scripts/take_screenshots.py [--n8n-url http://localhost:5678/webhook/triage-alert]

Needs: pip install playwright && python -m playwright install chromium
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "report_assets" / "screenshots"
LOG = OUT / "12_console_log.txt"
URL = "http://127.0.0.1:7860/?__theme=light"
PIN = os.environ.get("DOCTOR_PORTAL_PIN", "1234")


def wait_for(url: str, timeout: int = 240) -> None:
    start = time.time()
    while time.time() - start < timeout:
        try:
            if requests.get(url, timeout=3).status_code == 200:
                return
        except requests.RequestException:
            pass
        time.sleep(2)
    raise RuntimeError(f"{url} did not come up in {timeout} s")


def render_log_png(text: str, path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    lines = text.splitlines()[-40:]
    fig = plt.figure(figsize=(13, 0.22 * len(lines) + 0.6))
    fig.patch.set_facecolor("#0f172a")
    fig.text(0.01, 0.99, "\n".join(lines), va="top", ha="left", family="monospace", fontsize=8, color="#e2e8f0")
    fig.savefig(path, dpi=200, facecolor=fig.get_facecolor())
    plt.close(fig)


def _previous_high_sid() -> str:
    prev = OUT / "sessions.json"
    return json.loads(prev.read_text(encoding="utf-8")).get("High", "") if prev.exists() else ""


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--n8n-url", default=None)
    p.add_argument("--keep-db", action="store_true", help="reuse .local/demo.db (keeps earlier demo sessions)")
    p.add_argument("--demos", default="High,Medium,Low,Weak evidence,NEWS2 safety net",
                   help="comma-separated demo cases to run in Clinician Intake")
    p.add_argument("--skip-kiosk", action="store_true")
    args = p.parse_args()
    wanted = [d.strip() for d in args.demos.split(",") if d.strip()]
    OUT.mkdir(parents=True, exist_ok=True)
    from playwright.sync_api import sync_playwright

    cmd = [sys.executable, "-u", str(ROOT / "scripts" / "run_local_demo.py")]
    if args.n8n_url:
        cmd += ["--n8n-url", args.n8n_url]
    if args.keep_db:
        cmd += ["--keep"]
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    log_file = open(ROOT / ".local" / "screenshot_run.log", "w", encoding="utf-8")
    server = subprocess.Popen(cmd, cwd=ROOT, stdout=log_file, stderr=subprocess.STDOUT, env=env)
    results = {}
    try:
        wait_for("http://127.0.0.1:8000/health")
        wait_for("http://127.0.0.1:7860/")
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 1366, "height": 900}, device_scale_factor=1.5)
            page.goto(URL)
            page.get_by_role("tab", name="Patient Kiosk").wait_for()

            def shot(name):
                page.wait_for_timeout(800)
                page.screenshot(path=str(OUT / f"{name}.png"), full_page=True)
                print("saved", name, flush=True)

            # 1 Patient Kiosk: upload the synthetic demo clip and submit (Agent 1 Whisper).
            shot("01_patient_kiosk")
            try:
                if args.skip_kiosk:
                    raise RuntimeError("skipped by --skip-kiosk")
                upload_btn = page.locator("button[aria-label*='pload']").first
                if upload_btn.count():
                    upload_btn.click()
                    page.wait_for_timeout(800)
                with page.expect_file_chooser(timeout=10000) as chooser:
                    page.get_by_text("Drop Audio Here").first.click()
                chooser.value.set_files(str(ROOT / "demo" / "demo_patient_chest_pain.wav"))
                page.wait_for_timeout(5000)
                page.get_by_role("button", name="Submit").click()
                page.wait_for_function("() => [...document.querySelectorAll('textarea')].some(t => t.value.includes('Reference ID'))",
                                       timeout=120000)
                shot("01b_patient_kiosk_submitted")
            except Exception as exc:  # keep going; the kiosk shot without upload is already saved
                print('kiosk upload step failed:', type(exc).__name__, str(exc)[:200], flush=True)
                (OUT / 'kiosk_dom.html').write_text(page.content(), encoding='utf-8')

            # 2-5 Clinician Intake demo cases.
            page.get_by_role("tab", name="Clinician Intake").click()
            demos = [("High", "03a_card_high"), ("Medium", "03b_card_medium"), ("Low", "03c_card_low"),
                     ("Weak evidence", "04_card_weak_evidence"), ("NEWS2 safety net", "05_card_news2_safety_net")]
            for i, (demo, name) in enumerate([d for d in demos if d[0] in wanted]):
                page.get_by_role("button", name=f"Demo: {demo}", exact=True).click()
                page.wait_for_timeout(700)
                if demo == "High":
                    shot("02_clinician_intake_filled")
                before = page.locator(".clinical-card").count()
                page.get_by_role("button", name="Run triage").click()
                page.wait_for_function(
                    "(n) => document.querySelectorAll('.clinical-card').length >= 1 && "
                    "!document.querySelector('.clinical-card .card-header').innerText.includes(window.__lastSid || '#')",
                    arg=before, timeout=120000)
                page.wait_for_timeout(1500)
                sid = page.locator(".clinical-card .card-header").first.inner_text().split(":")[-1].strip()
                page.evaluate(f"window.__lastSid = '{sid}'")
                results[demo] = sid
                if demo == "High":
                    page.get_by_text("Agent Trace for this request").click()
                    page.wait_for_timeout(800)
                    shot("06a_agent_trace_intake")
                    page.get_by_text("Agent Trace for this request").click()
                shot(name)

            # 3 / 6 / 7 / 8 Doctor Portal.
            page.get_by_role("tab", name="Doctor Portal").click()
            page.get_by_label("Enter PIN").fill(PIN)
            page.get_by_label("Enter PIN").press("Enter")
            page.get_by_role("button", name="🔄 Refresh Dashboard").click()
            page.locator(".clinical-card:visible").first.wait_for(timeout=30000)
            page.wait_for_timeout(1500)
            shot("03_doctor_portal_cards")

            page.get_by_text("Agent Trace (step-by-step evidence per session)").click()
            page.wait_for_timeout(600)
            trace_dd = page.get_by_label("Session (refresh the dashboard to populate)")
            trace_dd.click()
            high_sid = results.get("High") or _previous_high_sid()
            results.setdefault("High", high_sid)
            page.get_by_role("option").filter(has_text=high_sid[:8]).first.click()
            page.get_by_role("button", name="Show trace").click()
            page.locator(".trace-card:visible").first.wait_for(timeout=30000)
            shot("06_agent_trace_doctor_portal")
            page.get_by_text("Agent Trace (step-by-step evidence per session)").click()

            page.get_by_text("Review a triage decision (Agent 6)").click()
            page.get_by_label("Session ID (copy from a card above)").fill(results.get("High", ""))
            page.get_by_label("Correct", exact=True).check()
            page.get_by_label("Reviewed by").fill("Dr Demo")
            page.get_by_role("button", name="Save review").click()
            page.get_by_text("Feedback saved").wait_for(timeout=20000)
            page.get_by_text("Monitoring: accuracy, drift and bias (Agents 6 & 7)").click()
            page.get_by_role("button", name="Run monitoring check").click()
            page.get_by_text("30-day accuracy").first.wait_for(timeout=30000)
            shot("07_feedback_and_accuracy")
            shot("08_drift_bias_panel")

            # 9 Evaluation tab.
            page.get_by_role("tab", name="Evaluation").click()
            page.wait_for_timeout(2500)
            shot("09_evaluation_tab")

            # 10 Admin / Supervisor tab.
            page.get_by_role("tab", name="Admin / Supervisor").click()
            page.get_by_label("Enter supervisor PIN").fill(PIN)
            page.get_by_label("Enter supervisor PIN").press("Enter")
            page.get_by_role("button", name="🩺 System health").click()
            page.get_by_text("Groq LLM").first.wait_for(timeout=30000)
            page.get_by_role("button", name="🔔 Load alert log").click()
            page.get_by_role("button", name="📈 Accuracy, drift & bias").click()
            page.wait_for_timeout(4000)
            shot("10_admin_supervisor")

            # 11 FastAPI docs.
            page.goto("http://127.0.0.1:8000/docs")
            page.get_by_text("process-triage").first.wait_for(timeout=30000)
            shot("11_fastapi_docs")
            browser.close()
    finally:
        server.terminate()
        try:
            server.wait(timeout=20)
        except subprocess.TimeoutExpired:
            server.kill()
        log_file.close()

    raw = (ROOT / ".local" / "screenshot_run.log").read_text(encoding="utf-8", errors="replace")
    lines = [ln for ln in raw.splitlines() if "agent_trace" in ln or "Built evidence index" in ln]
    LOG.write_text("\n".join(lines) + "\n", encoding="utf-8")
    render_log_png("\n".join(lines), OUT / "12_console_log.png")
    merged = json.loads((OUT / "sessions.json").read_text(encoding="utf-8")) if (OUT / "sessions.json").exists() else {}
    merged.update({k: v for k, v in results.items() if v})
    (OUT / "sessions.json").write_text(json.dumps(merged, indent=2), encoding="utf-8")
    print("screenshots in", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
