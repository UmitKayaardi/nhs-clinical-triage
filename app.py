"""
Gradio frontend client for the NHS Triage Assistant.

A thin HTTP client: it never runs Whisper or calls Groq itself. It sends
patient audio or typed intake data to the FastAPI backend and renders the
returned JSON.

Tabs:
- Patient Kiosk: record audio, submit, see a simple confirmation.
- Clinician Intake: typed complaint + vitals (structured endpoint), with demo cases.
- Doctor Portal (PIN): live patient cards, Agent Trace view, feedback, monitoring.
- Evaluation: offline evaluation results (evaluation/results/metrics.json + figures).
- Admin / Supervisor (PIN): alert log with channel, accuracy, drift & bias, PMS report, system health.
"""

import os

os.environ["CUDA_VISIBLE_DEVICES"] = ""

import html
import json
import logging
import tempfile
from pathlib import Path

import gradio as gr
import requests

try:  # Hugging Face ZeroGPU helper; not needed (or installed) locally.
    import spaces
except ImportError:  # pragma: no cover
    spaces = None

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent
BACKEND_URL = os.environ.get("BACKEND_URL", "http://127.0.0.1:8000")
PROCESS_TRIAGE_ENDPOINT = f"{BACKEND_URL}/api/v1/process-triage"
STRUCTURED_ENDPOINT = f"{BACKEND_URL}/api/v1/process-triage/structured"
SESSIONS_ENDPOINT = f"{BACKEND_URL}/api/v1/sessions"
FEEDBACK_ENDPOINT = f"{BACKEND_URL}/api/v1/feedback"
ACCURACY_ENDPOINT = f"{BACKEND_URL}/api/v1/admin/accuracy"
DRIFT_ENDPOINT = f"{BACKEND_URL}/api/v1/admin/drift"
PMS_REPORT_ENDPOINT = f"{BACKEND_URL}/api/v1/admin/pms-report"
ALERTS_ENDPOINT = f"{BACKEND_URL}/api/v1/alerts"
HEALTH_ENDPOINT = f"{BACKEND_URL}/api/v1/admin/system-health"
# Sent on clinician/admin calls; must match the backend's ADMIN_API_KEY when that is set.
ADMIN_HEADERS = {"X-Admin-Key": os.environ["ADMIN_API_KEY"]} if os.environ.get("ADMIN_API_KEY") else {}
REQUEST_TIMEOUT_SECONDS = 120

# Demo-only PINs (no real patient data in this system). Override with environment variables.
DOCTOR_PIN = os.environ.get("DOCTOR_PORTAL_PIN", "1234")
ADMIN_PIN = os.environ.get("ADMIN_PORTAL_PIN", DOCTOR_PIN)

METRICS_PATH = ROOT / "evaluation" / "results" / "metrics.json"
FIGURES_DIR = ROOT / "evaluation" / "results" / "figures"

custom_css = """
.clinical-card {
    background-color: #f8fafc;
    border-left: 14px solid #005eb8;
    padding: 20px 20px 20px 24px;
    border-radius: 8px;
    box-shadow: 0 4px 6px rgba(0,0,0,0.1);
    font-family: 'Arial', sans-serif;
    margin-bottom: 20px;
}
.triage-critical { border-left-color: #d32f2f; }
.triage-high { border-left-color: #d32f2f; }
.triage-medium { border-left-color: #fbc02d; }
.triage-low { border-left-color: #388e3c; }

.card-header {
    font-size: 1.4em;
    font-weight: bold;
    color: #1e293b;
    margin-bottom: 12px;
    border-bottom: 2px solid #e2e8f0;
    padding-bottom: 8px;
}
.card-body p {
    margin: 8px 0;
    color: #334155;
    font-size: 1.1em;
}
.label {
    font-weight: bold;
    color: #0f172a;
}
.badge { display:inline-block; padding:2px 10px; border-radius:12px; font-size:0.85em; font-weight:bold;
         margin-right:6px; border:1px solid transparent; }
.badge-strong { background:#e6f4ea; color:#14532d; border-color:#86c79a; }
.badge-moderate { background:#eef2ff; color:#1e3a8a; border-color:#a5b4fc; }
.badge-weak { background:#fff4ce; color:#713f12; border-color:#eda100; }
.badge-override { background:#fde8e8; color:#7f1d1d; border-color:#e34948; }
.weak-banner { background:#fff4ce; border:1px solid #eda100; color:#713f12; padding:10px 14px;
               border-radius:6px; margin:10px 0; font-weight:bold; }
.override-note { background:#fde8e8; border:1px solid #e34948; color:#7f1d1d; padding:10px 14px;
                 border-radius:6px; margin:10px 0; }
.sim-table { border-collapse: collapse; margin-top: 6px; font-size: 0.95em; }
.sim-table td, .sim-table th { border-bottom: 1px solid #e2e8f0; padding: 3px 10px; text-align:left; }
.trace-card { background:#ffffff; border:1px solid #cbd5e1; border-left:8px solid #6250d6; border-radius:8px;
              padding:12px 16px; margin:10px 0; font-family: Arial, sans-serif; color:#1e293b; }
.trace-card.status-error { border-left-color:#e34948; }
.trace-card.status-repaired { border-left-color:#eda100; }
.trace-card.status-overridden { border-left-color:#e34948; }
.trace-card.status-mocked, .trace-card.status-skipped { border-left-color:#8f8d86; }
.trace-title { font-weight:bold; font-size:1.1em; }
.trace-meta { color:#52514e; font-size:0.9em; margin:4px 0 8px 0; }
.trace-io { font-family: Consolas, monospace; font-size:0.85em; white-space:pre-wrap; background:#f1f5f9;
            padding:6px 8px; border-radius:4px; max-height:220px; overflow:auto; }
.demo-note { color:#52514e; font-size:0.9em; }
"""

_esc = html.escape


def _evidence_badge(strength) -> str:
    if not strength:
        return ""
    return f'<span class="badge badge-{_esc(strength)}">Evidence: {_esc(strength)}</span>'


def _weak_banner(low_evidence) -> str:
    if not low_evidence:
        return ""
    return ('<div class="weak-banner">⚠️ Weak historical evidence — treat this recommendation with caution.</div>')


def _news2_html(news2_score, safety_override, override_reason, llm_severity=None) -> str:
    parts = []
    if news2_score is not None:
        parts.append(f'<span class="badge badge-moderate">NEWS2: {int(news2_score)}</span>')
    if safety_override:
        parts.append('<span class="badge badge-override">Safety net override</span>')
        parts.append(f'<div class="override-note">🛡️ Agent 4 NEWS2 safety net raised the severity'
                     f'{f" (Agent 3 said {_esc(str(llm_severity))})" if llm_severity else ""}: '
                     f'{_esc(override_reason or "")}</div>')
    return " ".join(parts)


def _similarity_table(ids, scores) -> str:
    if not ids:
        return "<p><span class='label'>Historical evidence:</span> none found</p>"
    def source_and_id(ref):
        ref = str(ref)
        return ("KTAS", ref.split("-", 1)[1]) if ref.startswith("KTAS-") else ("MIMIC-IV-ED", ref)

    rows = "".join(f"<tr><td>{i}</td><td>{source_and_id(sid)[0]}</td><td>{_esc(source_and_id(sid)[1])}</td>"
                   f"<td>{(scores[i - 1] if i - 1 < len(scores) else 0):.2f}</td></tr>"
                   for i, sid in enumerate(ids, 1))
    return ("<p><span class='label'>Historical evidence (Agent 2):</span></p><table class='sim-table'>"
            "<tr><th>#</th><th>Source</th><th>Case ID</th><th>Similarity</th></tr>" + rows + "</table>")


def dict_to_html_card(data: dict, extra_html: str = "") -> str:
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except Exception:
            pass

    if not data or not isinstance(data, dict):
        return "<p style='color: red;'>No valid clinical data returned.</p>"

    triage_class = "triage-low"
    urgency_val = ""

    for k, v in data.items():
        if any(word in k.lower() for word in ["urgency", "severity", "triage", "level"]):
            urgency_val = str(v).lower()
            break

    if any(w in urgency_val for w in ["high", "severe", "red"]):
        triage_class = "triage-high"
    elif any(w in urgency_val for w in ["medium", "moderate", "yellow"]):
        triage_class = "triage-medium"

    session_id = data.get("Session Id", data.get("Session ID", "Unknown"))

    rows_html = ""
    for key, value in data.items():
        if key.lower() in ["session id", "session_id"]:
            continue

        formatted_key = str(key).replace("_", " ").title()

        if isinstance(value, list):
            formatted_value = ", ".join(_esc(str(item)) for item in value)
        else:
            formatted_value = _esc(str(value))

        rows_html += f'<p><span class="label">{formatted_key}:</span> {formatted_value}</p>\n'

    return f'''
    <div class="clinical-card {triage_class}">
        <div class="card-header">Patient Record ID: {_esc(str(session_id))}</div>
        <div class="card-body">
            {extra_html}
            {rows_html}
        </div>
    </div>
    '''


def _guess_mime_and_filename(audio_path: str) -> tuple:
    ext = os.path.splitext(audio_path)[1].lower() or ".wav"
    mime_map = {
        ".wav": "audio/wav",
        ".mp3": "audio/mpeg",
        ".m4a": "audio/mp4",
        ".ogg": "audio/ogg",
        ".webm": "audio/webm",
        ".flac": "audio/flac",
    }
    filename = f"patient_recording{ext}"
    mimetype = mime_map.get(ext, "application/octet-stream")
    return filename, mimetype


_GENDER_CODES = {"Male": "M", "Female": "F"}


def call_backend(audio_path: str, patient_form: dict = None) -> dict:
    if not audio_path or not os.path.exists(audio_path):
        raise RuntimeError("No audio was recorded. Please record your symptoms and try again.")

    filename, mimetype = _guess_mime_and_filename(audio_path)
    form = {k: v for k, v in (patient_form or {}).items() if v not in (None, "")}

    try:
        with open(audio_path, "rb") as f:
            response = requests.post(
                PROCESS_TRIAGE_ENDPOINT,
                files={"file": (filename, f, mimetype)},
                data=form,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
    except requests.exceptions.ConnectionError as exc:
        logger.exception("Could not reach backend")
        raise RuntimeError(
            f"Could not reach the triage backend at {BACKEND_URL}. Is it running?"
        ) from exc
    except requests.exceptions.Timeout as exc:
        raise RuntimeError("The backend took too long to respond. Please try again.") from exc

    if response.status_code != 200:
        try:
            detail = response.json().get("detail", response.text)
        except ValueError:
            detail = response.text
        raise RuntimeError(f"Backend error ({response.status_code}): {detail}")

    return response.json()


def process_patient_recording(audio_path: str, patient_id: str = "", age=None, gender: str = "", ethnicity: str = ""):
    patient_form = {
        "patient_id": (patient_id or "").strip(),
        "age": int(age) if age not in (None, "") else None,
        "gender": _GENDER_CODES.get(gender or ""),
        "ethnicity": ethnicity if ethnicity and ethnicity != "Prefer not to say" else None,
    }
    try:
        result = call_backend(audio_path, patient_form)
    except RuntimeError as exc:
        return f"⚠️ {exc}"

    return (
        "✅ Thank you. Your symptoms have been recorded and sent to the triage team.\n"
        f"Reference ID: {result.get('session_id', 'N/A')}\n"
        "Please take a seat -- a clinician will call you shortly."
    )


# ---------------------------------------------------------------- Clinician Intake (structured)
_AVPU = {"Alert": "alert", "New confusion": "confusion", "Responds to voice": "verbal",
         "Responds to pain": "pain", "Unresponsive": "unresponsive"}

DEMO_CASES = {
    # Invented examples for the live demonstration -- not real patient records.
    "High": dict(complaint="Crushing central chest pain spreading to my left arm, sweating and feeling sick for 40 minutes",
                 age=62, sex="Male", temp=98.2, hr=112, rr=22, spo2=94, sbp=104, dbp=68, pain=9, avpu="Alert",
                 arrival="ambulance", injury=False),
    "Medium": dict(complaint="Pain in the right lower abdomen since this morning, vomited twice, mild fever",
                   age=29, sex="Female", temp=100.4, hr=98, rr=18, spo2=98, sbp=122, dbp=78, pain=6, avpu="Alert",
                   arrival="walk in", injury=False),
    "Low": dict(complaint="Twisted my left ankle playing football yesterday, I can walk on it but it is swollen",
                age=24, sex="Male", temp=98.4, hr=76, rr=14, spo2=99, sbp=128, dbp=80, pain=3, avpu="Alert",
                arrival="walk in", injury=True),
    "Weak evidence": dict(complaint="Itchy bumps on my arms after gardening", age=45, sex="Female", temp=98.6,
                          hr=78, rr=14, spo2=99, sbp=124, dbp=76, pain=1, avpu="Alert", arrival="walk in",
                          injury=False),
    "NEWS2 safety net": dict(complaint="Cold and shivery after waiting outside for a long time, otherwise I feel fine",
                             age=79, sex="Male", temp=94.6, hr=72, rr=14, spo2=97, sbp=132, dbp=78, pain=0,
                             avpu="Alert", arrival="walk in", injury=False),
}
_DEMO_FIELDS = ["complaint", "age", "sex", "temp", "hr", "rr", "spo2", "sbp", "dbp", "pain", "avpu", "arrival", "injury"]


def load_demo(name: str):
    case = DEMO_CASES[name]
    return [case[f] for f in _DEMO_FIELDS] + [f"Loaded demo case: **{name}** (invented example)."]


def _num(v):
    return None if v in (None, "") else float(v)


def _alert_text(alert: dict) -> str:
    if not alert:
        return "no alert (severity not in alert list)"
    if alert.get("channel") == "mocked":
        return "mocked: Twilio test mode, no WhatsApp message sent (n8n not configured)"
    return f"{alert.get('status')} via {alert.get('channel')}"


def render_result(body: dict) -> str:
    tr = body.get("triage_result", {})
    cases = body.get("evidence_cases") or []
    extra = (_evidence_badge(body.get("evidence_strength"))
             + (f'<span class="badge badge-moderate">Top similarity {body.get("top_similarity", 0):.2f}</span>'
                if body.get("top_similarity") is not None else "")
             + _news2_html(body.get("news2_score"), body.get("safety_override"), body.get("override_reason"),
                           body.get("llm_severity"))
             + _weak_banner(body.get("low_evidence")))
    alert = body.get("alert") or {}
    data = {
        "Session ID": body.get("session_id"),
        "Severity": tr.get("Severity"),
        "Confidence": tr.get("Confidence") or "—",
        "Symptoms": tr.get("Symptoms", []),
        "Duration": tr.get("Duration", ""),
        "Possible Conditions": tr.get("Possible_Conditions", []),
        "Reasoning": tr.get("Reasoning", ""),
        "Required Actions": tr.get("Required_Actions", []),
        "Guardrail attempts": body.get("guardrail_attempts"),
        "Alert (Agent 5)": _alert_text(alert),
    }
    sim = "".join(f"<tr><td>{i}</td><td>{_esc(c.get('source') or 'MIMIC-IV-ED')}</td>"
                  f"<td>{_esc(c['chief_complaint'])}</td><td>{_esc(c['severity'])}</td>"
                  f"<td>{c['similarity_score']:.2f}</td></tr>" for i, c in enumerate(cases, 1))
    sim_html = ("<p><span class='label'>Historical evidence (Agent 2, multi-source knowledge base):</span></p>"
                "<table class='sim-table'>"
                "<tr><th>#</th><th>Source</th><th>Chief complaint</th><th>Recorded severity</th><th>Similarity</th></tr>"
                + sim + "</table>") if cases else "<p><span class='label'>Historical evidence:</span> none found</p>"
    return dict_to_html_card(data, extra) + sim_html


def submit_structured(complaint, age, sex, temp, hr, rr, spo2, sbp, dbp, pain, avpu, arrival, injury):
    if not complaint or len(complaint.strip()) < 3:
        return "<p style='color:red'>Enter the presenting complaint.</p>", {}, "", ""
    vitals = {"temperature": _num(temp), "heart_rate": _num(hr), "resp_rate": _num(rr), "o2sat": _num(spo2),
              "sbp": _num(sbp), "dbp": _num(dbp), "pain": _num(pain), "consciousness": _AVPU.get(avpu)}
    payload = {
        "chief_complaint": complaint.strip(),
        "vitals": {k: v for k, v in vitals.items() if v is not None},
        "age": int(age) if age not in (None, "") else None,
        "gender": _GENDER_CODES.get(sex or ""),
        "arrival_mode": arrival or None,
        "injury": bool(injury),
    }
    try:
        r = requests.post(STRUCTURED_ENDPOINT, json=payload, timeout=REQUEST_TIMEOUT_SECONDS)
    except requests.exceptions.RequestException as exc:
        return f"<p style='color:red'>Could not reach backend: {_esc(str(exc))}</p>", {}, "", ""
    if r.status_code != 200:
        return f"<p style='color:red'>Backend error ({r.status_code}): {_esc(r.text[:500])}</p>", {}, "", ""
    body = r.json()
    return render_result(body), body, render_trace(body.get("trace") or []), body.get("session_id", "")


# ---------------------------------------------------------------- Agent trace
def render_trace(steps) -> str:
    if not steps:
        return "<p>No trace recorded for this session.</p>"
    cards = []
    for s in steps:
        label = f"Agent {s['agent_no']}" if s.get("agent_no") else "Persistence"
        cards.append(f"""
        <div class="trace-card status-{_esc(str(s.get('status', 'ok')))}">
          <div class="trace-title">{label} · {_esc(str(s.get('agent_name', '')))}{(' — ' + _esc(str(s['stage']))) if s.get('stage') else ''}</div>
          <div class="trace-meta">{_esc(str(s.get('started_at', '')))} · {s.get('duration_ms', 0)} ms ·
            status <b>{_esc(str(s.get('status')))}</b> · sends to: {_esc(', '.join(s.get('messages_to') or []) or '—')}</div>
          <div><b>What it did:</b> {_esc(str(s.get('summary') or ''))}</div>
          <div style="margin-top:6px"><b>Input</b></div>
          <div class="trace-io">{_esc(json.dumps(s.get('input'), indent=1, ensure_ascii=False))}</div>
          <div style="margin-top:6px"><b>Output</b></div>
          <div class="trace-io">{_esc(json.dumps(s.get('output'), indent=1, ensure_ascii=False))}</div>
        </div>""")
    return "".join(cards)


def load_trace(session_id: str):
    session_id = (session_id or "").strip()
    if not session_id:
        return "<p>Enter or pick a Session ID.</p>", {}
    try:
        r = requests.get(f"{SESSIONS_ENDPOINT}/{session_id}/trace", timeout=15)
    except requests.exceptions.RequestException as exc:
        return f"<p style='color:red'>Could not reach backend: {_esc(str(exc))}</p>", {}
    if r.status_code != 200:
        return f"<p style='color:red'>Backend error ({r.status_code}): {_esc(r.text[:300])}</p>", {}
    body = r.json()
    header = (f"<p><b>Session</b> {_esc(body['session_id'])} · {_esc(body.get('intake_mode') or '')} intake · "
              f"final severity <b>{_esc(str(body.get('severity')))}</b> · {body['count']} steps</p>")
    return header + render_trace(body["steps"]), body


def verify_pin(pin: str):
    is_authorized = pin == DOCTOR_PIN
    status_message = "✅ Access granted." if is_authorized else "❌ Incorrect PIN."
    return (
        status_message,
        gr.update(visible=is_authorized),
    )


def verify_admin_pin(pin: str):
    ok = pin == ADMIN_PIN
    return ("✅ Supervisor access granted." if ok else "❌ Incorrect PIN."), gr.update(visible=ok)


def _gpu(fn):
    return spaces.GPU(fn) if spaces is not None else fn


@_gpu
def fetch_patients(severity_filter: str):
    """Fetches patient sessions from the backend and renders them as HTML cards."""
    params = {}
    if severity_filter != "All":
        params["severity"] = severity_filter

    try:
        response = requests.get(SESSIONS_ENDPOINT, params=params, timeout=10)
        if response.status_code != 200:
            return f"<div style='color:red;'>API Error: {response.status_code}</div>", gr.update()

        sessions = response.json().get("data", [])

        if not sessions:
            return ("<div style='text-align:center; padding: 20px;'><h3 style='color: gray;'>No patients found for "
                    "this filter.</h3></div>", gr.update(choices=[]))

        dashboard_html = ""
        for s in sessions:
            try:
                symptoms = json.loads(s.get("symptoms", "[]"))
            except Exception:
                symptoms = []

            try:
                conditions = json.loads(s.get("possible_conditions", "[]"))
            except Exception:
                conditions = []

            review = s.get("latest_feedback")
            patient_data = {
                "Session ID": str(s.get("id", "N/A")),
                "Severity": s.get("severity", "Unknown"),
                "Received": (s.get("created_at") or "")[:16].replace("T", " "),
                "Duration": s.get("duration", "N/A"),
                "Symptoms": symptoms,
                "Possible Conditions": conditions,
                "Reasoning": s.get("reasoning") or "—",
                "Required Actions": s.get("required_actions") or [],
                "Transcript": s.get("transcript", ""),
                "Clinician Review": {"correct": "✅ Correct", "incorrect": "⚠️ Incorrect (flagged)"}.get(review, "Not reviewed"),
            }
            extra = (_evidence_badge(s.get("evidence_strength"))
                     + _news2_html(s.get("news2_score"), s.get("safety_override"), s.get("override_reason"),
                                   s.get("llm_severity"))
                     + _weak_banner(s.get("low_evidence"))
                     + _similarity_table(s.get("evidence_stay_ids") or [], s.get("evidence_scores") or [])
                     + ("<p class='demo-note'>🔎 Agent trace available: open the <b>Agent Trace</b> panel below and "
                        "pick this Session ID.</p>" if s.get("has_trace") else ""))
            dashboard_html += dict_to_html_card(patient_data, extra)

        choices = [f"{s['id']} | {s.get('severity')} | {(s.get('chief_complaint') or '')[:50]}" for s in sessions]
        return dashboard_html, gr.update(choices=choices, value=choices[0] if choices else None)

    except Exception as e:
        return f"<div style='color:red;'>Connection Error: {_esc(str(e))}</div>", gr.update()


def submit_feedback(session_id: str, verdict: str, notes: str, reviewer: str) -> str:
    session_id = (session_id or "").strip()
    if not session_id or verdict not in ("Correct", "Incorrect"):
        return "⚠️ Enter a Session ID and choose Correct or Incorrect."
    payload = {"session_id": session_id, "feedback": verdict.lower(), "notes": notes or None,
               "reviewed_by": reviewer or None}
    try:
        r = requests.post(FEEDBACK_ENDPOINT, json=payload, headers=ADMIN_HEADERS, timeout=10)
    except requests.exceptions.RequestException as exc:
        return f"⚠️ Could not reach backend: {exc}"
    if r.status_code != 201:
        return f"⚠️ Backend error ({r.status_code}): {r.text}"
    flagged = r.json().get("flagged_for_review")
    return "✅ Feedback saved." + (" Session flagged for hallucination review." if flagged else "")


def _pct(value) -> str:
    return "—" if value is None else f"{value:.0%}"


def load_monitoring():
    """Agent 6 + 7 summary for the Doctor Portal."""
    try:
        acc = requests.get(ACCURACY_ENDPOINT, headers=ADMIN_HEADERS, timeout=15)
        drift = requests.get(DRIFT_ENDPOINT, headers=ADMIN_HEADERS, timeout=30)
    except requests.exceptions.RequestException as exc:
        return f"⚠️ Could not reach backend: {exc}", {}
    if acc.status_code != 200 or drift.status_code != 200:
        return f"⚠️ Backend error ({acc.status_code}/{drift.status_code})", {}
    a, d = acc.json(), drift.json()
    score = d.get("drift_score")
    summary = (
        f"**30-day accuracy:** {_pct(a.get('accuracy_30d'))}  ·  "
        f"**Hallucination rate:** {_pct(a.get('hallucination_rate'))}  ·  "
        f"**Reviewed:** {a.get('reviewed_sessions', 0)} / {a.get('total_sessions', 0)} sessions\n\n"
        f"**Drift score:** {'—' if score is None else f'{score:.2f}'}  ·  "
        f"**Retraining needed:** {'Yes' if d.get('retraining_needed') else 'No'}  ·  "
        f"**Data drift:** {'Yes' if d.get('data_drift_detected') else 'No'}  ·  "
        f"**Bias flagged:** {'Yes' if d.get('bias_detected') else 'No'}"
    )
    return summary, d


def download_pms_report(month: str):
    month = (month or "").strip()
    try:
        r = requests.get(PMS_REPORT_ENDPOINT, params={"month": month} if month else None,
                         headers=ADMIN_HEADERS, timeout=30)
    except requests.exceptions.RequestException:
        return None
    if r.status_code != 200:
        return None
    path = os.path.join(tempfile.gettempdir(), f"pms_report_{month or 'current'}.csv")
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(r.text)
    return path


# ---------------------------------------------------------------- Admin / Supervisor
def load_alert_log():
    try:
        r = requests.get(ALERTS_ENDPOINT, params={"limit": 200}, headers=ADMIN_HEADERS, timeout=15)
    except requests.exceptions.RequestException as exc:
        return [[f"Could not reach backend: {exc}", "", "", "", "", "", ""]]
    if r.status_code != 200:
        return [[f"Backend error {r.status_code}", "", "", "", "", "", ""]]
    rows = []
    for a in r.json().get("data", []):
        rows.append([a["timestamp"][:19].replace("T", " "), a["alert_type"], a["severity"], a.get("status") or "",
                     a.get("channel") or "—", (a.get("session_id") or "")[:8], a["message"].splitlines()[0][:80]])
    return rows or [["(no alerts yet)", "", "", "", "", "", ""]]


def load_health():
    try:
        r = requests.get(HEALTH_ENDPOINT, headers=ADMIN_HEADERS, timeout=20)
    except requests.exceptions.RequestException as exc:
        return f"⚠️ Could not reach backend: {exc}", {}
    if r.status_code != 200:
        return f"⚠️ Backend error ({r.status_code})", {}
    h = r.json()
    g, n = h["groq"], h["n8n"]
    rows = h["database"]["rows"]
    latency = f" ({g['latency_ms']} ms)" if g.get("latency_ms") else ""
    md = (f"**Groq LLM** ({g['model']}): {'🟢 reachable' if g.get('reachable') else '🔴 unreachable'}{latency}  ·  "
          f"**n8n**: {'🟢 reachable' if n.get('reachable') else ('🔴 configured but unreachable' if n.get('configured') else '⚪ not configured (direct Twilio fallback)')}  ·  "
          f"**Twilio**: {h['twilio']['mode']}\n\n"
          f"**Database** ({h['database']['backend']}): " + ", ".join(f"{k} {v}" for k, v in rows.items()) + "\n\n"
          f"**Models**: Whisper `{h['models']['agent1_whisper']}` · LLM `{h['models']['agent3_llm']}` "
          f"(temperature {h['models']['llm_temperature']}, reasoning effort {h['models']['llm_reasoning_effort']}, "
          f"prompt {h['models']['llm_prompt_version']}) · low-evidence threshold {h['models']['low_evidence_threshold']} · "
          f"NEWS2 safety net {'on' if h['models']['news2_safety_net'] else 'off'}\n\n"
          f"**Versions**: " + ", ".join(f"{k} {v}" for k, v in h["versions"].items()) + f", gradio {gr.__version__}")
    kb = h.get("knowledge_base")
    if isinstance(kb, dict) and kb.get("sources"):
        md += (f"\n\n**Knowledge base (Agent 2, multi-source)**: {kb['total']} cases -- "
               + ", ".join(f"{k} {v}" for k, v in kb["sources"].items()))
    return md, h


def load_supervisor_monitoring():
    summary, drift = load_monitoring()
    return summary, drift


# ---------------------------------------------------------------- Evaluation tab
def _fmt(x, pct=False):
    if x is None:
        return "–"
    return f"{100 * x:.1f}%" if pct else f"{x:.3f}"


_EVAL_HEADER = ("| System | n | Accuracy | Balanced acc. | Macro-F1 | Kappa | High recall | Under-triage | Over-triage |\n"
                "|---|---|---|---|---|---|---|---|---|")
_KB_LABELS = {"mimic+ktas-train": "multi-source KB: MIMIC-IV-ED + KTAS train", "mimic-all": "KB: MIMIC-IV-ED only",
              "mimic-train": "KB: MIMIC training stays", "none": "no evidence"}


def _eval_row(label, r):
    return (f"| {label} | {r['n']} | {_fmt(r['accuracy'], True)} | {_fmt(r['balanced_accuracy'], True)} | "
            f"{_fmt(r['f1_macro'])} | {_fmt(r['kappa_linear'])} | {_fmt(r['high_recall'], True)} | "
            f"{_fmt(r['under_triage_rate'], True)} | {_fmt(r['over_triage_rate'], True)} |")


def _llm_rows(ds) -> list:
    rows = []
    for job, entry in ds.get("llm_systems", {}).items():
        kb = _KB_LABELS.get(job.split("kb=")[-1], job.split("kb=")[-1])
        for sname in ("S4", "S3", "S4-noNEWS2", "S4-promptv1"):
            if sname in entry:
                tag = "" if entry["complete"] else f" *(in progress {entry['n_done']}/{entry['n_target']})*"
                label = f"**{sname}**" if sname == "S4" and "multi-source" in kb else sname
                rows.append(_eval_row(f"{label} ({kb}){tag}", entry[sname]))
    return rows


def evaluation_markdown() -> str:
    if not METRICS_PATH.exists():
        return "No evaluation results found. Run `python scripts/evaluate.py --all`."
    m = json.loads(METRICS_PATH.read_text(encoding="utf-8"))
    names = m["systems"]
    out = [f"Generated {m['generated_at']} · seed {m['seed']} · LLM {m['llm']['model']} (temperature "
           f"{m['llm']['temperature']}, reasoning effort {m['llm']['reasoning_effort']}) · all LLM runs complete: "
           f"**{m['llm']['all_llm_runs_complete']}**", ""]
    datasets = m["datasets"]

    # --- Main evaluation: KTAS ---
    k = datasets.get("ktas")
    if k:
        out += ["## Main evaluation — KTAS test split (Moon et al., 2019; truth = KTAS_expert)", "",
                "191 test cases never used for development, frozen configuration. S4 retrieves from the multi-source "
                "knowledge base (all MIMIC-IV-ED stays + the KTAS training split only; KTAS validation/test records "
                "are never in it).", "", _EVAL_HEADER]
        out += _llm_rows(k)
        if "H" in k["test"]:
            out.append(_eval_row(f"H {names.get('H', '')}", k["test"]["H"]))
        for sname, r in k["test"].items():
            if sname != "H":
                out.append(_eval_row(f"{sname} {names.get(sname, '')}", r))
        if k.get("s1_multi_source"):
            out.append(_eval_row(f"S1-mk {names.get('S1-mk', '')}", k["s1_multi_source"]))
        if k.get("nurse_all_records"):
            r = k["nurse_all_records"]
            out += ["", f"Triage nurse on all {r['n']} KTAS records: accuracy {_fmt(r['accuracy'], True)}, macro-F1 "
                        f"{_fmt(r['f1_macro'])}, under-triage {_fmt(r['under_triage_rate'], True)}."]
        secondary = k.get("llm_systems", {}).get("ktas:S4:kb=mimic-all", {})
        if "llm_subset" in k and not secondary.get("extended_to_full_test"):
            out += ["", f"Same {k['llm_subset']['n']}-case stratified sample used by the secondary S4 run so far "
                        "(KB: MIMIC-IV-ED only):", "", _EVAL_HEADER]
            for sname, r in k["llm_subset"]["systems"].items():
                out.append(_eval_row(f"{sname} {names.get(sname, '')}", r))
        out += ["", "| Split | Cases | Low | Medium | High |", "|---|---|---|---|---|"]
        for split, s in k["split_summary"].items():
            c = s["class_counts"]
            out.append(f"| {split} | {s['n_cases']} | {c['Low']} | {c['Medium']} | {c['High']} |")
        cv = k["cross_validation"]
        out += ["", f"5-fold cross-validation ({cv['method']}): " + "; ".join(
            f"{n} macro-F1 {v['f1_macro']['mean']:.3f} ± {v['f1_macro']['std']:.3f}" for n, v in cv["systems"].items()), ""]

    # --- Secondary check: MIMIC held-out ---
    mi = datasets.get("mimic")
    if mi:
        out += ["## Secondary check — MIMIC-IV-ED Demo held-out test (31 stays, 9 patients; ESI labels)", "",
                "Small held-out split evaluated once with the frozen configuration; knowledge base = the 114 "
                "training stays.", "", _EVAL_HEADER]
        out += _llm_rows(mi)
        for sname, r in mi["test"].items():
            out.append(_eval_row(f"{sname} {names.get(sname, '')}", r))
        out += ["", "| Split | Cases | Patients | Low | Medium | High |", "|---|---|---|---|---|---|"]
        for split, s in mi["split_summary"].items():
            c = s["class_counts"]
            out.append(f"| {split} | {s['n_cases']} | {s['n_groups']} | {c['Low']} | {c['Medium']} | {c['High']} |")
        cv = mi["cross_validation"]
        out += ["", f"5-fold cross-validation ({cv['method']}): " + "; ".join(
            f"{n} macro-F1 {v['f1_macro']['mean']:.3f} ± {v['f1_macro']['std']:.3f}" for n, v in cv["systems"].items()), ""]
    return "\n".join(out)


def evaluation_figures():
    order = ["nurse_vs_system_ktas.png", "confusion_matrices_ktas.png", "model_comparison_f1_ktas.png",
             "under_triage_ktas.png", "confusion_matrices_mimic.png", "model_comparison_f1_mimic.png",
             "under_triage_mimic.png", "cv_boxplot_mimic.png", "cv_boxplot_ktas.png", "latency_per_agent.png",
             "low_evidence_accuracy.png", "subgroups_ktas.png", "per_class_f1_ktas.png"]
    return [(str(FIGURES_DIR / f), f.replace(".png", "").replace("_", " ")) for f in order if (FIGURES_DIR / f).exists()]


# --- UI layout ---
with gr.Blocks(title="NHS Triage Assistant", theme=gr.themes.Soft(primary_hue="slate", neutral_hue="gray"), css=custom_css) as demo:
    gr.Markdown("# NHS Triage Assistant")
    gr.Markdown(
        f"Connected to backend: `{BACKEND_URL}`  \n"
        "This client only records audio / intake data and displays results -- all transcription, "
        "database search, and AI analysis happen on the backend. **Decision support only; demo system with no real "
        "patient data.**"
    )

    with gr.Tab("Patient Kiosk"):
        gr.Markdown("### Please describe your symptoms")
        patient_audio = gr.Audio(sources=["microphone", "upload"], type="filepath", label="Record your symptoms")
        with gr.Accordion("Optional details (used only for audit and fairness monitoring)", open=False):
            with gr.Row():
                patient_id_in = gr.Textbox(label="Patient / NHS number", max_lines=1)
                age_in = gr.Number(label="Age", precision=0, minimum=0, maximum=120)
                gender_in = gr.Dropdown(["", "Male", "Female"], value="", label="Sex")
                ethnicity_in = gr.Dropdown(
                    ["", "WHITE", "BLACK", "ASIAN", "HISPANIC", "OTHER", "Prefer not to say"],
                    value="", label="Ethnicity",
                )
        patient_submit_btn = gr.Button("Submit", variant="primary")
        patient_output = gr.Textbox(label="Status", interactive=False)

        patient_submit_btn.click(
            fn=process_patient_recording,
            inputs=[patient_audio, patient_id_in, age_in, gender_in, ethnicity_in],
            outputs=[patient_output],
        )

    with gr.Tab("Clinician Intake"):
        gr.Markdown("### Typed complaint and vital signs (structured intake → Agents 2–5)")
        with gr.Row():
            demo_buttons = [gr.Button(f"Demo: {name}", size="sm") for name in DEMO_CASES]
        demo_status = gr.Markdown("<span class='demo-note'>Demo buttons fill the form with invented examples.</span>")
        ci_complaint = gr.Textbox(label="Presenting complaint (patient's words)", lines=2)
        with gr.Row():
            ci_age = gr.Number(label="Age", precision=0, minimum=0, maximum=120)
            ci_sex = gr.Dropdown(["", "Male", "Female"], value="", label="Sex")
            ci_avpu = gr.Dropdown(list(_AVPU), value="Alert", label="Consciousness (ACVPU)")
            ci_arrival = gr.Dropdown(["", "walk in", "ambulance", "private car", "helicopter", "other"], value="",
                                     label="Arrival mode", allow_custom_value=True)
            ci_injury = gr.Checkbox(label="Injury-related", value=False)
        with gr.Row():
            ci_temp = gr.Number(label="Temperature (°F)")
            ci_hr = gr.Number(label="Heart rate (/min)")
            ci_rr = gr.Number(label="Respiratory rate (/min)")
            ci_spo2 = gr.Number(label="SpO2 (%)")
            ci_sbp = gr.Number(label="Systolic BP")
            ci_dbp = gr.Number(label="Diastolic BP")
            ci_pain = gr.Number(label="Pain (0-10)", minimum=0, maximum=10)
        ci_submit = gr.Button("Run triage", variant="primary")
        ci_card = gr.HTML()
        with gr.Accordion("Agent Trace for this request (step by step)", open=False):
            ci_trace = gr.HTML()
        with gr.Accordion("Raw API response (JSON)", open=False):
            ci_json = gr.JSON()
        ci_session = gr.Textbox(label="Session ID", interactive=False, max_lines=1)

        form_fields = [ci_complaint, ci_age, ci_sex, ci_temp, ci_hr, ci_rr, ci_spo2, ci_sbp, ci_dbp, ci_pain,
                       ci_avpu, ci_arrival, ci_injury]
        for btn, name in zip(demo_buttons, DEMO_CASES):
            btn.click(fn=lambda n=name: load_demo(n), inputs=[], outputs=form_fields + [demo_status])
        ci_submit.click(fn=submit_structured, inputs=form_fields, outputs=[ci_card, ci_json, ci_trace, ci_session])

    with gr.Tab("Doctor Portal"):
        gr.Markdown("### Clinician access only")
        pin_input = gr.Textbox(label="Enter PIN", type="password")
        pin_status = gr.Textbox(label="Status", interactive=False)

        with gr.Group(visible=False) as portal_panel:
            gr.Markdown("### 🏥 Live Patient Triage Dashboard")

            with gr.Row():
                severity_radio = gr.Radio(
                    choices=["All", "High", "Medium", "Low"],
                    value="All",
                    label="Filter by Severity",
                    interactive=True
                )
                refresh_btn = gr.Button("🔄 Refresh Dashboard", variant="primary")

            patient_list_html = gr.HTML(value="<div style='color: gray; margin-top: 15px;'>Click Refresh or select a filter to load patients...</div>")

            with gr.Accordion("🔎 Agent Trace (step-by-step evidence per session)", open=False):
                with gr.Row():
                    trace_pick = gr.Dropdown(choices=[], label="Session (refresh the dashboard to populate)",
                                             interactive=True, allow_custom_value=True)
                    trace_btn = gr.Button("Show trace")
                trace_html = gr.HTML()
                with gr.Accordion("Raw trace JSON", open=False):
                    trace_json = gr.JSON()
                trace_btn.click(fn=lambda v: load_trace((v or "").split(" | ")[0]), inputs=[trace_pick],
                                outputs=[trace_html, trace_json])

            severity_radio.change(fn=fetch_patients, inputs=[severity_radio], outputs=[patient_list_html, trace_pick])
            refresh_btn.click(fn=fetch_patients, inputs=[severity_radio], outputs=[patient_list_html, trace_pick])

            with gr.Accordion("📝 Review a triage decision (Agent 6)", open=False):
                with gr.Row():
                    fb_session = gr.Textbox(label="Session ID (copy from a card above)", max_lines=1)
                    fb_verdict = gr.Radio(["Correct", "Incorrect"], label="Was the AI triage level correct?")
                with gr.Row():
                    fb_notes = gr.Textbox(label="Notes (what was wrong?)", lines=2)
                    fb_reviewer = gr.Textbox(label="Reviewed by", max_lines=1)
                fb_btn = gr.Button("Save review", variant="primary")
                fb_status = gr.Markdown()
                fb_btn.click(fn=submit_feedback, inputs=[fb_session, fb_verdict, fb_notes, fb_reviewer],
                             outputs=[fb_status])

            with gr.Accordion("📈 Monitoring: accuracy, drift and bias (Agents 6 & 7)", open=False):
                mon_btn = gr.Button("Run monitoring check")
                mon_summary = gr.Markdown()
                mon_details = gr.JSON(label="Full drift & bias report")
                mon_btn.click(fn=load_monitoring, inputs=[], outputs=[mon_summary, mon_details])
                with gr.Row():
                    pms_month = gr.Textbox(label="PMS report month (YYYY-MM, blank = current)", max_lines=1)
                    pms_btn = gr.Button("Download monthly PMS report")
                pms_file = gr.File(label="PMS report (CSV)")
                pms_btn.click(fn=download_pms_report, inputs=[pms_month], outputs=[pms_file])

        pin_input.submit(
            fn=verify_pin,
            inputs=[pin_input],
            outputs=[pin_status, portal_panel],
        )

    with gr.Tab("Evaluation"):
        gr.Markdown("### Offline evaluation (WP1) — reproducible with `python scripts/evaluate.py --all`")
        gr.Markdown("**Knowledge base (Agent 2):** about 1,500 records from two datasets (three emergency "
                    "departments: one in the USA, two in South Korea) — 222 MIMIC-IV-ED Demo stays and 1,267 KTAS "
                    "records; every retrieved case shows "
                    "its source. **Main evaluation: KTAS** test split (191 cases), frozen configuration; the "
                    "evaluation knowledge base holds all MIMIC-IV-ED stays + the KTAS training split only. "
                    "**Secondary check:** MIMIC held-out test (31 stays, 9 patients), prompt developed on a separate "
                    "development set (62 stays).  \n"
                    "Systems: S0 majority · S1 retrieval-only (Agent 2) · S1-mk retrieval-only with the multi-source "
                    "KB · S2a logistic regression · S2b random forest · S3 LLM without evidence · **S4 full system** "
                    "(Agents 2+3+4) · S4-noNEWS2 ablation · S4-promptv1 prompt ablation · H triage nurse (KTAS_RN).")
        eval_md = gr.Markdown(evaluation_markdown())
        eval_gallery = gr.Gallery(value=evaluation_figures(), label="Figures", columns=2, height="auto",
                                  object_fit="contain")
        eval_refresh = gr.Button("Reload results")
        eval_refresh.click(fn=lambda: (evaluation_markdown(), evaluation_figures()), inputs=[],
                           outputs=[eval_md, eval_gallery])

    with gr.Tab("Admin / Supervisor"):
        gr.Markdown("### Supervisor access (demo PIN)")
        admin_pin = gr.Textbox(label="Enter supervisor PIN", type="password")
        admin_status = gr.Textbox(label="Status", interactive=False)
        with gr.Group(visible=False) as admin_panel:
            with gr.Row():
                health_btn = gr.Button("🩺 System health", variant="primary")
                alerts_btn = gr.Button("🔔 Load alert log")
                sup_mon_btn = gr.Button("📈 Accuracy, drift & bias")
            health_md = gr.Markdown()
            with gr.Accordion("Health JSON", open=False):
                health_json = gr.JSON()
            alerts_table = gr.Dataframe(headers=["Time (UTC)", "Type", "Severity", "Status", "Channel", "Session",
                                                 "Message"], interactive=False, wrap=True)
            sup_summary = gr.Markdown()
            sup_details = gr.JSON(label="Agent 7 drift & bias report")
            with gr.Row():
                sup_month = gr.Textbox(label="PMS report month (YYYY-MM, blank = current)", max_lines=1)
                sup_pms_btn = gr.Button("Download monthly PMS report")
            sup_pms_file = gr.File(label="PMS report (CSV)")
            health_btn.click(fn=load_health, inputs=[], outputs=[health_md, health_json])
            alerts_btn.click(fn=load_alert_log, inputs=[], outputs=[alerts_table])
            sup_mon_btn.click(fn=load_supervisor_monitoring, inputs=[], outputs=[sup_summary, sup_details])
            sup_pms_btn.click(fn=download_pms_report, inputs=[sup_month], outputs=[sup_pms_file])
        admin_pin.submit(fn=verify_admin_pin, inputs=[admin_pin], outputs=[admin_status, admin_panel])

import threading  # noqa: E402

import uvicorn  # noqa: E402

from app.main import app as fastapi_app  # noqa: E402


def run_backend():

    uvicorn.run(fastapi_app, host="127.0.0.1", port=8000)


threading.Thread(target=run_backend, daemon=True).start()

if __name__ == "__main__":
    demo.launch(allowed_paths=[str(FIGURES_DIR)])
