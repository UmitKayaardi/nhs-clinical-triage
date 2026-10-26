"""
Gradio frontend client for the NHS Triage Assistant.

Unlike the original PoC, this client does NOT run Whisper or call Groq
locally. It is a thin HTTP client: it records/accepts patient audio,
sends it to the FastAPI backend's POST /api/v1/process-triage endpoint
as multipart/form-data, and renders the returned JSON.

Two tabs:
- Patient Kiosk: record audio, submit, see a simple confirmation.
- Doctor Portal: PIN-protected live dashboard, fetches and filters 
  patient sessions from the database automatically.
"""

import os
os.environ["CUDA_VISIBLE_DEVICES"] = ""

import spaces
import logging
import os
import json
import tempfile
import gradio as gr
import requests

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BACKEND_URL = os.environ.get("BACKEND_URL", "http://127.0.0.1:8000")
PROCESS_TRIAGE_ENDPOINT = f"{BACKEND_URL}/api/v1/process-triage"
SESSIONS_ENDPOINT = f"{BACKEND_URL}/api/v1/sessions"
FEEDBACK_ENDPOINT = f"{BACKEND_URL}/api/v1/feedback"
ACCURACY_ENDPOINT = f"{BACKEND_URL}/api/v1/admin/accuracy"
DRIFT_ENDPOINT = f"{BACKEND_URL}/api/v1/admin/drift"
PMS_REPORT_ENDPOINT = f"{BACKEND_URL}/api/v1/admin/pms-report"
# Sent on clinician/admin calls; must match the backend's ADMIN_API_KEY when that is set.
ADMIN_HEADERS = {"X-Admin-Key": os.environ["ADMIN_API_KEY"]} if os.environ.get("ADMIN_API_KEY") else {}
REQUEST_TIMEOUT_SECONDS = 120  

DOCTOR_PIN = os.environ.get("DOCTOR_PORTAL_PIN", "1234")

# Custom CSS for the NHS-style clinical card
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
"""

def dict_to_html_card(data: dict) -> str:
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
            formatted_value = ", ".join(str(item) for item in value)
        else:
            formatted_value = str(value)
            
        rows_html += f'<p><span class="label">{formatted_key}:</span> {formatted_value}</p>\n'
        
    html_content = f'''
    <div class="clinical-card {triage_class}">
        <div class="card-header">Patient Record ID: {session_id}</div>
        <div class="card-body">
            {rows_html}
        </div>
    </div>
    '''
    return html_content

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

def verify_pin(pin: str):
    is_authorized = pin == DOCTOR_PIN
    status_message = "✅ Access granted." if is_authorized else "❌ Incorrect PIN."
    return (
        status_message,
        gr.update(visible=is_authorized),  
    )

@spaces.GPU
def fetch_patients(severity_filter: str) -> str:
    """Fetches patient sessions from the backend and renders them as HTML cards."""
    params = {}
    if severity_filter != "All":
        params["severity"] = severity_filter
        
    try:
        response = requests.get(SESSIONS_ENDPOINT, params=params, timeout=10)
        if response.status_code != 200:
            return f"<div style='color:red;'>API Error: {response.status_code}</div>"
            
        sessions = response.json().get("data", [])
        
        if not sessions:
            return "<div style='text-align:center; padding: 20px;'><h3 style='color: gray;'>No patients found for this filter.</h3></div>"
            
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
            
            dashboard_html += dict_to_html_card(patient_data)
            
        return dashboard_html
        
    except Exception as e:
        return f"<div style='color:red;'>Connection Error: {str(e)}</div>"

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


# --- UI layout ---
with gr.Blocks(title="NHS Triage Assistant", theme=gr.themes.Soft(primary_hue="slate", neutral_hue="gray"), css=custom_css) as demo:
    gr.Markdown("# NHS Triage Assistant")
    gr.Markdown(
        f"Connected to backend: `{BACKEND_URL}`  \n"
        "This client only records audio and displays results -- all transcription, "
        "database search, and AI analysis happen on the backend."
    )

    with gr.Tab("Patient Kiosk"):
        gr.Markdown("### Please describe your symptoms")
        patient_audio = gr.Audio(sources=["microphone"], type="filepath", label="Record your symptoms")
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

            severity_radio.change(fn=fetch_patients, inputs=[severity_radio], outputs=[patient_list_html])
            refresh_btn.click(fn=fetch_patients, inputs=[severity_radio], outputs=[patient_list_html])

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

import threading
import uvicorn

from app.main import app as fastapi_app

def run_backend():

    uvicorn.run(fastapi_app, host="127.0.0.1", port=8000)

threading.Thread(target=run_backend, daemon=True).start()

if __name__ == "__main__":
    demo.launch()