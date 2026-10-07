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

import logging
import os
import json
import gradio as gr
import requests

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000")
PROCESS_TRIAGE_ENDPOINT = f"{BACKEND_URL}/api/v1/process-triage"
SESSIONS_ENDPOINT = f"{BACKEND_URL}/api/v1/sessions"
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
    """
    Converts the triage dictionary into a styled HTML clinical card dynamically.
    """
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
            
    if any(w in urgency_val for w in ["critical", "high", "severe", "red", "1", "2"]):
        triage_class = "triage-critical"
    elif any(w in urgency_val for w in ["medium", "moderate", "yellow", "3"]):
        triage_class = "triage-medium"

    rows_html = ""
    for key, value in data.items():
        formatted_key = str(key).replace("_", " ").title()
        
        if isinstance(value, list):
            formatted_value = ", ".join(str(item) for item in value)
        else:
            formatted_value = str(value)
            
        rows_html += f'<p><span class="label">{formatted_key}:</span> {formatted_value}</p>\n'
        
    html_content = f'''
    <div class="clinical-card {triage_class}">
        <div class="card-header">Patient Record ID: {data.get("Session Id", "Unknown")}</div>
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

def call_backend(audio_path: str) -> dict:
    if not audio_path or not os.path.exists(audio_path):
        raise RuntimeError("No audio was recorded. Please record your symptoms and try again.")

    filename, mimetype = _guess_mime_and_filename(audio_path)

    try:
        with open(audio_path, "rb") as f:
            response = requests.post(
                PROCESS_TRIAGE_ENDPOINT,
                files={"file": (filename, f, mimetype)},
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

def process_patient_recording(audio_path: str):
    try:
        result = call_backend(audio_path)
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

            patient_data = {
                "Session ID": str(s.get("id", "N/A"))[:8] + "...", # ID
                "Severity": s.get("severity", "Unknown"),
                "Duration": s.get("duration", "N/A"),
                "Symptoms": symptoms,
                "Possible Conditions": conditions,
                "Transcript": s.get("transcript", "")
            }
            
            dashboard_html += dict_to_html_card(patient_data)
            
        return dashboard_html
        
    except Exception as e:
        return f"<div style='color:red;'>Connection Error: {str(e)}</div>"

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
        patient_submit_btn = gr.Button("Submit", variant="primary")
        patient_output = gr.Textbox(label="Status", interactive=False)

        patient_submit_btn.click(
            fn=process_patient_recording,
            inputs=[patient_audio],
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
                    choices=["All", "Critical", "High", "Medium", "Low"],
                    value="All",
                    label="Filter by Severity",
                    interactive=True
                )
                refresh_btn = gr.Button("🔄 Refresh Dashboard", variant="primary")
                
            patient_list_html = gr.HTML(value="<div style='color: gray; margin-top: 15px;'>Click Refresh or select a filter to load patients...</div>")

            severity_radio.change(fn=fetch_patients, inputs=[severity_radio], outputs=[patient_list_html])
            refresh_btn.click(fn=fetch_patients, inputs=[severity_radio], outputs=[patient_list_html])

        pin_input.submit(
            fn=verify_pin,
            inputs=[pin_input],
            outputs=[pin_status, portal_panel],
        )

if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7861)