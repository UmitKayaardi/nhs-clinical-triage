# Screenshot checklist (maps every screenshot to a report section)

All screenshots below were re-captured on 28 Nov 2026 with Playwright (headless Chromium, light theme, 1366 px wide,
scale 1.5) after the final evaluation and deployment. Session IDs used: `report_assets/screenshots/sessions.json`.

| Script | Captures |
|---|---|
| `python scripts/take_screenshots.py` | 01-12: local app on a fresh copy of the database (n8n not configured -> alerts `mocked`) |
| `python scripts/take_n8n_screenshots.py` | 12b-19: local n8n (local-only owner account, test mode) + local app with `N8N_WEBHOOK_URL` set |
| `python scripts/take_space_screenshots.py` | 20-22: live Hugging Face Space |
| `python scripts/build_architecture_diagram.py` | `figures/architecture.png` (300 dpi) + `figures/architecture.svg` |

## Application (local run)

| # | File | Shows | Report section |
|---|---|---|---|
| 1 | `screenshots/01_patient_kiosk.png` | Patient Kiosk tab (microphone + upload) | 4.2 UI |
| 1b | `screenshots/01b_patient_kiosk_submitted.png` | Synthetic voice clip submitted; reference ID returned (Agent 1 Whisper) | 4.1 step 1, 4.2 |
| 2 | `screenshots/02_clinician_intake_filled.png` | Clinician Intake form filled with the High demo case (data input) | 4.1 input, 4.2 |
| 3 | `screenshots/03_doctor_portal_cards.png` | Doctor Portal (PIN) with the demo cards, badges and evidence tables (source + case ID) | 4.2 UI, 4.1 output |
| 3a | `screenshots/03a_card_high.png` | High card: evidence strong (top similarity 0.71), NEWS2 6, alert mocked; evidence table with **Source** column (4 KTAS + 1 MIMIC-IV-ED) | 4.1 output, 2.2 multi-source evidence |
| 3b | `screenshots/03b_card_medium.png` | Medium card: evidence moderate, NEWS2 1, no alert | 4.1 output |
| 3c | `screenshots/03c_card_low.png` | Low card: ankle sprain, evidence moderate, NEWS2 0 | 4.1 output |
| 4 | `screenshots/04_card_weak_evidence.png` | Weak-evidence card: 0 cases found, yellow banner | 2.2 innovation (WP2), 4.1 |
| 5 | `screenshots/05_card_news2_safety_net.png` | NEWS2 safety net: Agent 3 said Low (evidence weak, top similarity 0.47), NEWS2 single-parameter score 3 (temperature 94.6 °F) raised it to High | 2.2 innovation (WP3), 4.1 Agent 4 |
| 6 | `screenshots/06_agent_trace_doctor_portal.png` | Agent Trace view: one card per agent with input, action, output, time, status | 4.1 step-by-step (Agents 1-5) |
| 6a | `screenshots/06a_agent_trace_intake.png` | Same trace under the Clinician Intake result | 4.1 |
| 7 | `screenshots/07_feedback_and_accuracy.png` | Clinician review saved -> 30-day accuracy updated (Agent 6) | 4.1 Agent 6, 4.2 |
| 8 | `screenshots/08_drift_bias_panel.png` | Drift & bias report JSON (Agent 7); same page as 7 with the panel expanded | 4.1 Agent 7 |
| 9 | `screenshots/09_evaluation_tab.png` | Evaluation tab: KTAS main results first, nurse line, MIMIC secondary check, figures | 3.3 evaluation, lecturer's metrics request |
| 10 | `screenshots/10_admin_supervisor.png` | Admin / Supervisor tab: system health (knowledge base 1,489 cases by source), alert log with channel, accuracy / drift / bias, PMS | 4.2 admin / supervisor UI |
| 11 | `screenshots/11_fastapi_docs.png` | FastAPI OpenAPI `/docs` (all endpoints) | 4.2 external interaction, 3.1 |
| 12 | `screenshots/12_console_log.png` + `.txt` | Console log of the full run: `[Agent n \| name] ... ms (status)` lines for Agents 1-7 | 4.1 processing evidence |

## n8n orchestration (Agent 5, local, Twilio test mode)

For this run only `ALERT_ON_SEVERITIES=["High","Medium"]`, so the backend also forwards the Medium case and the n8n
workflow itself decides "skipped". The Twilio node has a placeholder credential (n8n 2.x requires one to publish);
the test-mode branch never calls Twilio.

| # | File | Shows | Report section |
|---|---|---|---|
| 12b | `screenshots/12b_console_log_n8n.txt` | Console lines: `[Agent 5 \| Orchestrator & Action] n8n webhook -> mocked` (High) and `-> skipped` (Medium) | 4.1 Agent 5 |
| 13 | `screenshots/13_card_high_alert_via_n8n.png` | High card with `Alert (Agent 5): mocked via n8n` | 4.1 Agent 5 |
| 14 | `screenshots/14_card_medium_n8n_skipped.png` | Medium card with `Alert (Agent 5): skipped via n8n` | 4.1 Agent 5 |
| 15 | `screenshots/15_admin_health_n8n_reachable.png` | Admin system health with n8n reachable; alert log rows with channel `n8n` | 4.1 Agent 5, 4.2 admin |
| 16 | `screenshots/16_n8n_workflow_canvas.png` | n8n editor: workflow `NHS Triage - Agent 5 alert orchestration` (10 nodes, Published) | 4.1 Agent 5, 2.3 tools |
| 17 | `screenshots/17_n8n_executions_list.png` | n8n Executions: 2 successful runs; latest (Medium) path highlighted | 4.1 Agent 5, 4.2 external |
| 18 | `screenshots/18_n8n_execution_high_mocked.png` | High execution: Webhook -> Check secret -> Severity needs alert? (true) -> Twilio test mode? (true) -> Respond mocked | 4.1 Agent 5 |
| 19 | `screenshots/19_n8n_execution_medium_skipped.png` | Medium execution: Severity needs alert? (false) -> Respond skipped | 4.1 Agent 5 |

## Live Hugging Face Space

| # | File | Shows | Report section |
|---|---|---|---|
| 20 | `screenshots/20_space_home.png` | Space page on huggingface.co (owner / Space name visible, app running) | 4.2 deployment |
| 21 | `screenshots/21_space_demo_high_result.png` | High demo case on the Space: result card + multi-source evidence table | 4.2 deployment, 4.1 output |
| 22 | `screenshots/22_space_evaluation_tab.png` | Evaluation tab on the Space (final KTAS results) | 4.2 deployment, 3.3 |

## Figures

| File | Shows | Report section |
|---|---|---|
| `figures/architecture.png` / `.svg` | Final architecture: 7 agents (names as in the submitted workflow), multi-source knowledge base, repair loop, NEWS2 safety net, weak-evidence flag, agent trace, n8n -> Twilio + direct fallback, monitoring layer, admin endpoints | 2.1 architecture |
| `figures/*.png` (other) | Evaluation figures (copied from `evaluation/results/figures/`) | 3.3 evaluation |

## Screenshots the student must take

| # | What | How | Report section |
|---|---|---|---|
| S4 | WhatsApp alert received on the phone | Twilio WhatsApp sandbox joined, `TWILIO_TEST_MODE=false` (needs your Twilio account) | 4.1 Agent 5, 4.2 |
| S6 | Space **Settings → Variables and secrets** with secret names visible, values hidden | Space settings page (needs your Hugging Face login) | 3.1 environment |
