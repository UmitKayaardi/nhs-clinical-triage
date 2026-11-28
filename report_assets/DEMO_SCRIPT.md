# Demo script: 15-minute in-person presentation (bullet points only)

Space: https://huggingface.co/spaces/UmitKayaardi/nhs-clinical-triage · direct app: https://umitkayaardi-nhs-clinical-triage.hf.space
Doctor Portal / Admin PIN: `1234` (demo-only) · numbers: `evaluation/results/metrics.json` (generated 28 Nov 2026)

## Before the session (30-10 minutes before)

- Open the Space 10+ minutes early: a sleeping Space needs a few minutes to start, and the first triage builds the
  1,489-case index (first request can take about a minute). Run one warm-up case (Demo: Low) and discard it.
- Do not run an LLM evaluation batch on presentation day: each demo triage uses 1 Groq call from the same free-tier quota.
- Open these tabs in the browser: Space app, `report_assets/figures/architecture.png`, n8n screenshots
  `report_assets/screenshots/16_n8n_workflow_canvas.png` and `18_n8n_execution_high_mocked.png`.
- Laptop fallback ready (see "Fallback plan"): `.env` with `GROQ_API_KEY`, `python scripts/run_local_demo.py` tested once.
- Optional voice demo: `demo/demo_patient_chest_pain.wav` on the desktop (synthetic voice, invented text).
- Phone hotspot available in case the venue Wi-Fi blocks Groq or Hugging Face.

## Timeline (15 min)

| Time | Screen | What to click / show | Say (headline facts) |
|---|---|---|---|
| 0:00-1:30 | `architecture.png` | Point along Agents 1 → 5, the repair loop, NEWS2, weak-evidence flag, n8n → Twilio + fallback, Agents 6-7, admin endpoints | 7 agents; decision support only; multi-source knowledge base: about 1,500 records from two datasets (three EDs: one USA, two South Korea) |
| 1:30-2:00 | Space home | Show the header and tabs | FastAPI backend + Gradio UI on Hugging Face; no real patient data |
| 2:00-4:00 | Clinician Intake → **Demo: High** → **Run triage** | Badges (evidence strong, top similarity ~0.71, NEWS2 6) · Severity High · Reasoning · Required actions · Alert (Agent 5) mocked · evidence table **Source** column (KTAS + MIMIC-IV-ED) · open **Agent Trace for this request** | Agent 2 found similar chest-pain cases in both sources; Agent 4 validated on attempt 1; Agent 5 alert is mocked (Twilio test mode) |
| 4:00-5:00 | **Demo: Medium** → Run triage | Severity Medium, evidence moderate, NEWS2 1 · no alert | Only High triggers an alert |
| 5:00-5:45 | **Demo: Low** → Run triage | Severity Low, NEWS2 0 | Resource-based Low (ankle sprain, walking) |
| 5:45-7:00 | **Demo: Weak evidence** → Run triage | 0 cases found, yellow **weak historical evidence** banner, "weak" badge | WP2: top-1 similarity < 0.50 → flag; the LLM is told the evidence is weak |
| 7:00-8:30 | **Demo: NEWS2 safety net** → Run triage | Override note: Agent 3 said Low (on 28 Nov; earlier runs Medium), NEWS2 3 (temperature 94.6 °F scores 3) → raised to High; weak-evidence banner too; alert mocked | WP3: NEWS2 can only raise severity, never lower it |
| 8:30-10:00 | Doctor Portal → PIN `1234` → **Refresh Dashboard** | Cards with badges and evidence (source + case ID) · filter High · **Agent Trace** accordion → pick the High session → **Show trace** · **Review a triage decision** → paste the High session ID → Correct → Save | Agent 6 records the clinician verdict; trace = input, output, duration, status per agent |
| 10:00-11:00 | Doctor Portal → **Monitoring** → Run monitoring check; Admin / Supervisor → PIN → **System health**, **Load alert log** | 30-day accuracy, drift & bias JSON · Groq reachable, n8n "not configured" on the Space (direct Twilio path), alert log with channel | Agent 7: JS / KS drift, chi² / Cramér's V bias; admin endpoints behind an API key |
| 11:00-13:30 | **Evaluation** tab | KTAS main table, then nurse line, then MIMIC secondary table; figure gallery (nurse vs LLM systems) | See "Headline numbers" below |
| 13:30-14:15 | n8n screenshots | Canvas (10 nodes) → High execution (mocked branch) → Medium execution (skipped branch) | n8n runs locally; the Space cannot reach a local n8n, so it uses the direct Twilio fallback |
| 14:15-15:00 | Summary | — | Limitations (small MIMIC demo, cross-scale labels, LLM below nurse); next steps |

## Headline numbers (from metrics.json)

- KTAS main evaluation, 191 test cases, frozen configuration, 0 failed cases:
  - S4 full system (MIMIC-IV-ED + KTAS-train knowledge base): accuracy 60.2% (95% CI 53.4-67.0%), macro-F1 0.603, High recall 81.1%, under-triage 15.2%
  - S3 LLM only: 60.7%; S4 with MIMIC-only knowledge base: 61.8%
  - Triage nurse (KTAS_RN): 88.0% on the same 191 cases; 88.6% on all 1,267 records
  - Random forest 70.7%, logistic regression 69.1%, retrieval-only vote 65.4%
  - McNemar: S4 vs nurse p < 0.001; S4 vs random forest p = 0.015; S4 vs S3 p = 1.00; multi-source vs MIMIC-only knowledge base p = 0.73
  - Weak-evidence flag (multi-source KB): flagged 18 cases, accuracy 38.9% vs 62.4% unflagged
  - NEWS2 overrides: 3 (all raised to a wrong higher level; S4 without NEWS2 61.8%)
  - Guardrail: 100% valid on the first attempt; median latency Agent 2 14 ms, Agent 3 565 ms, Agent 4 0.09 ms; ~1,524 tokens per case
- MIMIC held-out (secondary, 31 stays, 9 patients): S4 48.4%, S3 61.3%; prompt v2 under-triage 16.1% vs prompt v1 74.2%
- Evidence sources for KTAS queries: 89.5% KTAS, 10.5% MIMIC-IV-ED

## Optional (only if time allows)

- Patient Kiosk: upload `demo/demo_patient_chest_pain.wav` → Submit → reference ID (Agent 1 Whisper; first transcription ~20 s on CPU).
- FastAPI docs: `http://127.0.0.1:8000/docs` in the local run (not exposed on the Space).

## Fallback plan

| Problem | Action |
|---|---|
| Space asleep / slow | Wait on the "Building / Starting" page (2-4 min); meanwhile present `architecture.png` and the Evaluation figures |
| Space error or Hugging Face down | Local run: `python scripts/run_local_demo.py` → open http://127.0.0.1:7860 (same UI, copy of the database) |
| Venue Wi-Fi down | Phone hotspot → local run. Groq needs internet: without any internet, show the saved screenshots instead (`report_assets/screenshots/02`-`10`), and the Evaluation tab of the local run (works offline, reads `metrics.json`) |
| Groq quota / rate limit (HTTP 429 or 502 in the card) | Switch to screenshots `03a`-`05`; explain the daily free-tier limit |
| Demo case returns a different severity | Expected: temperature 0 is near-deterministic but not guaranteed; show the reasoning and the trace instead |
| n8n question | Show `16_n8n_workflow_canvas.png`, `17_n8n_executions_list.png`, `18_`/`19_` execution views; `n8n/README.md` for the setup |
