# Screenshot checklist (maps every screenshot to a report section)

Automated screenshots: `python scripts/take_screenshots.py` (Playwright, headless Chromium, app on a fresh copy of the
database, light theme, 1366 px wide, scale 1.5). Session IDs used: `report_assets/screenshots/sessions.json`.

| # | File | Shows | Report section |
|---|---|---|---|
| 1 | `screenshots/01_patient_kiosk.png` | Patient Kiosk tab (microphone + upload) | 4.2 UI |
| 1b | `screenshots/01b_patient_kiosk_submitted.png` | Synthetic voice clip submitted; reference ID returned (Agent 1 Whisper) | 4.1 step 1, 4.2 |
| 2 | `screenshots/02_clinician_intake_filled.png` | Clinician Intake form filled with the High demo case (data input) | 4.1 input, 4.2 |
| 3 | `screenshots/03_doctor_portal_cards.png` | Doctor Portal (PIN) with High / Medium / Low cards, badges, similarity tables | 4.2 UI, 4.1 output |
| 3a | `screenshots/03a_card_high.png` | High card (strong evidence, NEWS2 6, alert mocked) | 4.1 output |
| 3b | `screenshots/03b_card_medium.png` | Medium card | 4.1 output |
| 3c | `screenshots/03c_card_low.png` | Low card (weak evidence banner; MIMIC demo KB has 2 Low stays) | 4.1 output |
| 4 | `screenshots/04_card_weak_evidence.png` | Weak-evidence card (0 cases found, yellow banner) | 2.2 innovation (WP2), 4.1 |
| 5 | `screenshots/05_card_news2_safety_net.png` | NEWS2 safety net override: Agent 3 said Medium, NEWS2 temperature score 3 raised to High | 2.2 innovation (WP3), 4.1 Agent 4 |
| 6 | `screenshots/06_agent_trace_doctor_portal.png` | Agent Trace view: one card per agent with input, action, output, time, status | 4.1 step-by-step (Agents 1-5) |
| 6a | `screenshots/06a_agent_trace_intake.png` | Same trace shown under the Clinician Intake result | 4.1 |
| 7 | `screenshots/07_feedback_and_accuracy.png` | Clinician review saved -> 30-day accuracy updated (Agent 6) | 4.1 Agent 6, 4.2 |
| 8 | `screenshots/08_drift_bias_panel.png` | Drift & bias report JSON (Agent 7) (same page as 7, panel expanded) | 4.1 Agent 7 |
| 9 | `screenshots/09_evaluation_tab.png` | Evaluation tab: split tables, metric tables, figures | 3.3, lecturer's metrics request |
| 10 | `screenshots/10_admin_supervisor.png` | Admin / Supervisor tab: system health, alert log with channel, accuracy/drift/bias, PMS | 4.2 admin/supervisor UI |
| 11 | `screenshots/11_fastapi_docs.png` | FastAPI OpenAPI `/docs` (all endpoints) | 4.2 external interaction, 3.1 |
| 12 | `screenshots/12_console_log.png` + `.txt` | Console log of full runs: `[Agent n \| name] ... ms (status)` lines | 4.1 processing evidence |

Figures for section 3.3 are in `report_assets/figures/` (copied from `evaluation/results/figures/`).

## Screenshots the student must take

| # | What | How | Report section |
|---|---|---|---|
| S1 | n8n canvas showing the workflow `NHS Triage - Agent 5 alert orchestration` | n8n editor after import (see `n8n/README.md`) | 4.1 Agent 5, 2.3 tools |
| S2 | n8n **Executions** list + one successful execution (green path to `Respond mocked` or `Respond sent`) | run a High demo case with `python scripts/run_local_demo.py --n8n-url http://localhost:5678/webhook/triage-alert` | 4.1 Agent 5, 4.2 external |
| S3 | Card showing `Alert (Agent 5): mocked via n8n` (or `sent via n8n`) | same run, Clinician Intake tab | 4.1 Agent 5 |
| S4 | WhatsApp alert received on the phone | Twilio sandbox joined, `TWILIO_TEST_MODE=false` | 4.1 Agent 5, 4.2 |
| S5 | Hugging Face Space running (Space URL visible) + one demo case result | https://huggingface.co/spaces/UmitKayaardi/nhs-clinical-triage | 4.2 deployment |
| S6 | Space **Settings → Variables and secrets** page with secret names visible, values hidden | Space settings | 3.1 environment |
