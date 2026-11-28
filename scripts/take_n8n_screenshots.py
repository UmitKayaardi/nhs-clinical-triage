"""
n8n screenshots for Agent 5 (local only, test mode -- no WhatsApp message is ever sent).

1. Creates a throwaway n8n home in .local/n8n-shots (git-ignored); the local-only owner account is set up
   through the n8n UI (random password, written to .local/n8n-shots/owner_local_only.json, never printed).
2. Imports n8n/triage_alert_workflow.json plus a placeholder Twilio credential (the test-mode branch
   never calls Twilio; n8n 2.x will not publish a Twilio node without a credential) and publishes it.
3. Starts n8n and the app (fresh DB copy) with N8N_WEBHOOK_URL / N8N_WEBHOOK_SECRET set.
   For this run only ALERT_ON_SEVERITIES=["High","Medium"], so the backend forwards the Medium case
   as well and the n8n workflow itself takes the "skipped" branch.
4. Runs the High and Medium demo cases, captures the cards, Admin system health (n8n reachable),
   the n8n workflow canvas, the executions list and both execution views.
5. Stops the app and n8n.

  python scripts/take_n8n_screenshots.py                 # full run (fresh n8n home, app, editor)
  python scripts/take_n8n_screenshots.py --editor-only   # editor screenshots from the previous run's executions

Needs Node.js (npx) and Playwright. Two demo triages cost two Groq calls.
"""

import json
import os
import secrets
import shutil
import subprocess
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "report_assets" / "screenshots"
N8N_DIR = ROOT / ".local" / "n8n-shots"
N8N = "http://localhost:5678"
WEBHOOK = f"{N8N}/webhook/triage-alert"
APP = "http://127.0.0.1:7860/?__theme=light"
N8N_PKG = os.environ.get("N8N_PACKAGE", "n8n@2.48.7")
NPX = "npx.cmd" if os.name == "nt" else "npx"
WF_ID = "TriageAlertWf001"
CRED = {"id": "twplaceholder0001", "name": "Twilio (placeholder, test mode only)", "type": "twilioApi",
        "data": {"authType": "authToken", "accountSid": "ACtest", "authToken": "test"}}
PIN = os.environ.get("DOCTOR_PORTAL_PIN", "1234")


def kill_tree(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
    else:
        proc.terminate()
    try:
        proc.wait(timeout=20)
    except subprocess.TimeoutExpired:
        proc.kill()


def wait_until(check, what: str, timeout: int = 240) -> None:
    start = time.time()
    while time.time() - start < timeout:
        try:
            if check():
                return
        except requests.RequestException:
            pass
        time.sleep(2)
    raise RuntimeError(f"{what} not ready after {timeout} s")


def n8n_sign_in(page, owner) -> None:
    """Owner setup on first load (local-only account), otherwise sign in -- both through the n8n UI."""
    wait_until(lambda: requests.get(f"{N8N}/rest/settings", timeout=3).ok, "n8n editor API")
    for attempt in range(3):
        page.goto(f"{N8N}/")
        try:
            page.wait_for_function("() => document.querySelector('input') || location.pathname.includes('/home')"
                                   " || location.pathname.includes('/workflow')", timeout=60000)
            break
        except Exception:
            print(f"n8n editor not ready (attempt {attempt + 1}), reloading", flush=True)
    print("n8n page:", page.url.replace(N8N, ""), flush=True)
    if "/setup" in page.url:
        for field in ("email", "firstName", "lastName", "password"):
            page.locator(f"input[name='{field}']").fill(owner[field])
        page.get_by_role("button", name="Next").click()
    elif "/signin" in page.url:
        page.locator("input[name='emailOrLdapLoginId'], input[type='email']").first.fill(owner["email"])
        page.locator("input[type='password']").first.fill(owner["password"])
        page.get_by_role("button", name="Sign in").click()
    page.wait_for_url(lambda u: "/setup" not in u and "/signin" not in u, timeout=60000)
    page.wait_for_timeout(3000)
    print("n8n owner session ready", flush=True)


def editor_shots(ctx, page, owner, shot) -> None:
    page.set_viewport_size({"width": 1600, "height": 900})
    n8n_sign_in(page, owner)
    page.goto(f"{N8N}/workflow/{WF_ID}")
    page.locator(".vue-flow").first.wait_for(timeout=90000)
    page.wait_for_timeout(3000)
    ignore = page.get_by_text("Ignore for all workflows")
    if ignore.count() and ignore.first.is_visible():
        ignore.first.click()              # dismiss the production checklist pop-up ...
        page.wait_for_timeout(800)
        confirm = page.get_by_role("button", name="Ignore for all workflows")
        if confirm.count():
            confirm.first.click()         # ... and confirm the dialog
            page.wait_for_timeout(1000)
    page.keyboard.press("Shift+1")   # zoom to fit
    page.wait_for_timeout(1000)
    shot("16_n8n_workflow_canvas", full=False)

    # Executions: navigate inside the editor (a full page reload would need a new sign-in).
    page.locator("[data-test-id='radio-button-executions']").first.click(force=True)
    page.wait_for_timeout(5000)
    test_ids = page.evaluate("() => [...new Set([...document.querySelectorAll('[data-test-id]')]"
                             ".map(e => e.getAttribute('data-test-id')).filter(x => /execution/i.test(x)))]")
    print("execution test ids:", test_ids, flush=True)
    items = page.locator("[data-test-id='execution-item'], [data-test-id='execution-list-item'], a[href*='/executions/']")
    n = items.count()
    print("n8n executions listed:", n, flush=True)
    shot("17_n8n_executions_list", full=False)
    # Newest first: [0] = Medium (skipped), [1] = High (mocked).
    for idx, name in ((min(1, n - 1), "18_n8n_execution_high_mocked"), (0, "19_n8n_execution_medium_skipped")):
        if n == 0:
            break
        items.nth(idx).click()
        page.wait_for_timeout(6000)
        shot(name, full=False)


def main() -> int:
    import argparse

    from playwright.sync_api import sync_playwright

    p = argparse.ArgumentParser()
    p.add_argument("--editor-only", action="store_true",
                   help="reuse .local/n8n-shots (workflow + executions of a previous run); editor screenshots only")
    args = p.parse_args()

    if args.editor_only:
        owner = json.loads((N8N_DIR / "owner_local_only.json").read_text(encoding="utf-8"))
    else:
        if N8N_DIR.exists():
            shutil.rmtree(N8N_DIR)
        N8N_DIR.mkdir(parents=True)
        owner = {"email": "owner@n8n.local", "firstName": "Local", "lastName": "Owner",
                 "password": secrets.token_urlsafe(12) + "Aa1"}
        (N8N_DIR / "owner_local_only.json").write_text(json.dumps(owner, indent=2), encoding="utf-8")
    log = open(N8N_DIR / ("run_editor.log" if args.editor_only else "run.log"), "w", encoding="utf-8")
    webhook_secret = secrets.token_urlsafe(32)
    env_n8n = {**os.environ, "N8N_USER_FOLDER": str(N8N_DIR), "N8N_BLOCK_ENV_ACCESS_IN_NODE": "false",
               "TRIAGE_WEBHOOK_SECRET": webhook_secret, "TWILIO_WHATSAPP_FROM": "+14155238886",
               "DOCTOR_WHATSAPP_NUMBER": "+440000000000", "N8N_DIAGNOSTICS_ENABLED": "false",
               "N8N_PERSONALIZATION_ENABLED": "false", "N8N_VERSION_NOTIFICATIONS_ENABLED": "false",
               "N8N_SECURE_COOKIE": "false", "N8N_PORT": "5678"}

    if not args.editor_only:
        # Import the repository workflow (credential reference added in a temporary copy only) and publish it.
        wf = json.loads((ROOT / "n8n" / "triage_alert_workflow.json").read_text(encoding="utf-8"))
        wf["id"] = WF_ID
        for node in wf["nodes"]:
            if node["type"] == "n8n-nodes-base.twilio":
                node["credentials"] = {"twilioApi": {"id": CRED["id"], "name": CRED["name"]}}
        (N8N_DIR / "import_workflow.json").write_text(json.dumps(wf), encoding="utf-8")
        (N8N_DIR / "import_credentials.json").write_text(json.dumps([CRED]), encoding="utf-8")
        for cli in (["import:credentials", f"--input={N8N_DIR / 'import_credentials.json'}"],
                    ["import:workflow", f"--input={N8N_DIR / 'import_workflow.json'}"],
                    ["publish:workflow", f"--id={WF_ID}"]):
            subprocess.run([NPX, "--yes", N8N_PKG, *cli], cwd=ROOT, env=env_n8n, stdout=log,
                           stderr=subprocess.STDOUT, check=True)
        print("n8n workflow imported and published", flush=True)

    n8n = subprocess.Popen([NPX, "--yes", N8N_PKG, "start"], cwd=ROOT, env=env_n8n, stdout=log,
                           stderr=subprocess.STDOUT)
    app = None
    results = {}
    try:
        wait_until(lambda: requests.get(f"{N8N}/healthz", timeout=3).status_code == 200, "n8n")
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            ctx = browser.new_context(viewport={"width": 1366, "height": 900}, device_scale_factor=1.5)
            page = ctx.new_page()

            def shot(name, full=True):
                page.wait_for_timeout(1000)
                page.screenshot(path=str(OUT / f"{name}.png"), full_page=full)
                print("saved", name, flush=True)

            if not args.editor_only:
                n8n_sign_in(page, owner)
                wait_until(lambda: "POST" in requests.get(WEBHOOK, timeout=3).text, "n8n webhook registration")
                print("n8n webhook live", flush=True)
                env_app = {**os.environ, "PYTHONIOENCODING": "utf-8", "TRIAGE_WEBHOOK_SECRET": webhook_secret,
                           "ALERT_ON_SEVERITIES": '["High","Medium"]', "TWILIO_TEST_MODE": "true"}
                app_log = open(N8N_DIR / "app.log", "w", encoding="utf-8")
                app = subprocess.Popen([sys.executable, "-u", str(ROOT / "scripts" / "run_local_demo.py"),
                                        "--n8n-url", WEBHOOK], cwd=ROOT, env=env_app, stdout=app_log,
                                       stderr=subprocess.STDOUT)
                wait_until(lambda: requests.get("http://127.0.0.1:8000/health", timeout=3).status_code == 200,
                           "backend")
                wait_until(lambda: requests.get("http://127.0.0.1:7860/", timeout=3).status_code == 200, "Gradio")

                page.set_viewport_size({"width": 1366, "height": 900})
                page.goto(APP)
                page.get_by_role("tab", name="Clinician Intake").click()
                for demo, name in (("High", "13_card_high_alert_via_n8n"), ("Medium", "14_card_medium_n8n_skipped")):
                    page.get_by_role("button", name=f"Demo: {demo}", exact=True).click()
                    page.wait_for_timeout(1500)
                    prev = page.evaluate(
                        "() => (document.querySelector('.clinical-card .card-header') || {}).innerText || ''")
                    page.get_by_role("button", name="Run triage").click()
                    page.wait_for_function(
                        "(prev) => { const h = document.querySelector('.clinical-card .card-header');"
                        " return h && h.innerText !== prev; }", arg=prev, timeout=120000)
                    page.wait_for_timeout(1500)
                    results[demo] = page.locator(".clinical-card .card-header").first.inner_text().split(":")[-1].strip()
                    shot(name)

                page.get_by_role("tab", name="Admin / Supervisor").click()
                page.get_by_label("Enter supervisor PIN").fill(PIN)
                page.get_by_label("Enter supervisor PIN").press("Enter")
                page.get_by_role("button", name="🩺 System health").click()
                page.get_by_text("Groq LLM").first.wait_for(timeout=30000)
                page.get_by_role("button", name="🔔 Load alert log").click()
                page.wait_for_timeout(3000)
                shot("15_admin_health_n8n_reachable")

            editor_shots(ctx, page, owner, shot)
            browser.close()
    finally:
        if app is not None:
            kill_tree(app)
        kill_tree(n8n)
        log.close()

    if not args.editor_only:
        app_lines = (N8N_DIR / "app.log").read_text(encoding="utf-8", errors="replace").splitlines()
        agent5 = [ln for ln in app_lines if "agent_trace" in ln and any(f"Agent {n}" in ln for n in (2, 3, 4, 5))]
        (OUT / "12b_console_log_n8n.txt").write_text("\n".join(agent5) + "\n", encoding="utf-8")
        sessions = OUT / "sessions.json"
        merged = json.loads(sessions.read_text(encoding="utf-8")) if sessions.exists() else {}
        merged.update({f"n8n {k}": v for k, v in results.items()})
        sessions.write_text(json.dumps(merged, indent=2), encoding="utf-8")
    print("n8n stopped; screenshots in", OUT, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
