"""
Regenerates the data-driven files in report_assets/ (facts only, no prose):

  environment.md     versions, hardware, model settings
  json_examples/     one sanitised input/output example per agent (from the newest traced session in
                     .local/demo.db), Groq request/response (from the LLM cache), n8n and Twilio payloads
  REPORT_FACTS.md    bullet facts and numbers from evaluation/results/metrics.json

Usage: python scripts/build_report_assets.py
"""

import importlib.metadata as md
import json
import platform
import sqlite3
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.config import get_settings  # noqa: E402
from app.services.twilio_service import TwilioService  # noqa: E402

ASSETS = ROOT / "report_assets"
EX = ASSETS / "json_examples"
PACKAGES = ["fastapi", "uvicorn", "pydantic", "pydantic-settings", "SQLAlchemy", "alembic", "openai-whisper", "torch",
            "groq", "twilio", "requests", "pandas", "numpy", "scipy", "scikit-learn", "matplotlib", "openpyxl",
            "gradio", "pytest", "httpx", "imageio-ffmpeg", "playwright"]


def _ver(pkg):
    try:
        return md.version(pkg)
    except md.PackageNotFoundError:
        return "not installed"


def _cmd(args):
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=20).stdout.strip()
    except Exception:
        return "n/a"


def environment():
    s = get_settings()
    cpu = _cmd(["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_Processor).Name"]) or platform.processor()
    ram = _cmd(["powershell", "-NoProfile", "-Command",
                "[math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory/1GB,1)"])
    gpu = _cmd(["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_VideoController).Name -join '; '"])
    n8n = "2.48.7 (npx n8n@2.48.7)"
    lines = [
        "# Development and simulation environment (facts only)", "",
        f"Generated {date.today().isoformat()} by `python scripts/build_report_assets.py`.", "",
        "## Platform", "",
        "| Item | Value |", "|---|---|",
        f"| OS | {platform.system()} {platform.release()} ({platform.version()}) |",
        f"| Python | {platform.python_version()} |",
        f"| CPU | {cpu} |", f"| RAM | {ram} GB |", f"| GPU | {gpu} (not used: Whisper and torch run on CPU) |",
        f"| Node.js | {_cmd(['node', '-v'])} |", f"| n8n | {n8n} |",
        "| Deployment | Hugging Face Space, Gradio SDK 5.9.1, hardware ZeroGPU (`zero-a10g`); Dockerfile: python:3.11-slim |",
        "", "## Python packages (installed versions)", "", "| Package | Version |", "|---|---|"]
    lines += [f"| {p} | {_ver(p)} |" for p in PACKAGES]
    lines += ["", "## Models and agent parameters", "", "| Parameter | Value | Setting |", "|---|---|---|",
              f"| Agent 1 speech model | Whisper `{s.WHISPER_MODEL_NAME}`, CPU, fp16=False | `WHISPER_MODEL_NAME` |",
              f"| Agent 3 LLM | `{s.GROQ_MODEL_NAME}` via Groq API | `GROQ_MODEL_NAME` |",
              f"| Temperature | {s.LLM_TEMPERATURE} | `LLM_TEMPERATURE` |",
              f"| Max output tokens | {s.LLM_MAX_TOKENS} | `LLM_MAX_TOKENS` |",
              f"| Reasoning effort | {s.LLM_REASONING_EFFORT} | `LLM_REASONING_EFFORT` |",
              "| Output format | JSON mode (`response_format={\"type\":\"json_object\"}`) | — |",
              f"| Prompt version | {s.LLM_PROMPT_VERSION} | `LLM_PROMPT_VERSION` |",
              f"| Guardrail repair attempts | {s.LLM_MAX_REPAIR_ATTEMPTS} | `LLM_MAX_REPAIR_ATTEMPTS` |",
              f"| Retrieved cases (k) | {s.MAX_SIMILAR_CASES} | `MAX_SIMILAR_CASES` |",
              f"| Retrieval weights complaint/diagnosis/vitals/medication | {s.RETRIEVAL_WEIGHT_COMPLAINT}/"
              f"{s.RETRIEVAL_WEIGHT_DIAGNOSIS}/{s.RETRIEVAL_WEIGHT_VITALS}/{s.RETRIEVAL_WEIGHT_MEDICATION} | `RETRIEVAL_WEIGHT_*` |",
              f"| Weak-evidence threshold (top-1 similarity) | {s.LOW_EVIDENCE_THRESHOLD} | `LOW_EVIDENCE_THRESHOLD` |",
              f"| Evidence label-agreement minimum (strong) | {s.EVIDENCE_MIN_AGREEMENT} | `EVIDENCE_MIN_AGREEMENT` |",
              f"| NEWS2 safety net | {s.NEWS2_SAFETY_NET_ENABLED} | `NEWS2_SAFETY_NET_ENABLED` |",
              f"| Alert severities | {s.ALERT_ON_SEVERITIES} | `ALERT_ON_SEVERITIES` |",
              f"| n8n timeout / retries | {s.N8N_TIMEOUT_SECONDS} s / {s.N8N_MAX_RETRIES} | `N8N_TIMEOUT_SECONDS`, `N8N_MAX_RETRIES` |",
              f"| Twilio retries / backoff | {s.TWILIO_MAX_RETRIES} / {s.TWILIO_RETRY_BACKOFF_SECONDS} s exponential | `TWILIO_MAX_RETRIES` |",
              f"| Monitoring window | {s.MONITORING_WINDOW_DAYS} days | `MONITORING_WINDOW_DAYS` |",
              f"| Accuracy alert threshold | {s.ACCURACY_ALERT_THRESHOLD} | `ACCURACY_ALERT_THRESHOLD` |",
              f"| Drift score threshold | {s.DRIFT_SCORE_THRESHOLD} | `DRIFT_SCORE_THRESHOLD` |",
              f"| Bias p-value threshold | {s.BIAS_P_VALUE_THRESHOLD} | `BIAS_P_VALUE_THRESHOLD` |",
              "| Evaluation seed | 42 | `evaluation/common.py` |",
              "", "## Input formats", "", "| Agent | Expected input |", "|---|---|",
              "| 1 | audio file .wav/.mp3/.m4a/.ogg/.webm/.flac (multipart `file`) |",
              "| 1 (structured) | JSON `StructuredIntakeRequest` (`json_examples/structured_request.json`) |",
              "| 2 | complaint text + optional vitals dict (F, /min, %, mmHg) |",
              "| 3 | chat messages (system prompt with evidence, user message with statement + structured data) |",
              "| 4 | raw model text; vitals + ACVPU for NEWS2 |",
              "| 5 | severity, complaint, reasoning, NEWS2, session id -> n8n JSON event |",
              "| 6 | JSON `{session_id, feedback, notes, reviewed_by}` |",
              "| 7 | session rows in a 30-day window |", ""]
    (ASSETS / "environment.md").write_text("\n".join(lines), encoding="utf-8")


def _save(name, data):
    EX.mkdir(parents=True, exist_ok=True)
    (EX / name).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def json_examples():
    demo_db = ROOT / ".local" / "demo.db"
    steps = []
    if demo_db.exists():
        con = sqlite3.connect(f"file:{demo_db.as_posix()}?mode=ro", uri=True)
        row = con.execute("SELECT agent_trace FROM triage_sessions WHERE agent_trace IS NOT NULL "
                          "AND intake_mode='structured' ORDER BY created_at DESC LIMIT 1").fetchone()
        con.close()
        steps = json.loads(row[0]) if row else []
    names = {1: "agent1_intake", 2: "agent2_retrieval", 3: "agent3_reasoning", 4: "agent4_guardrail",
             5: "agent5_orchestrator", 6: "agent6_monitor", 7: "agent7_drift_bias", 0: "persistence"}
    seen = {}
    for s in steps:
        key = names.get(s["agent_no"], f"agent{s['agent_no']}")
        if s["agent_no"] == 4:
            key += "_news2" if "NEWS2" in s["agent_name"] else "_schema"
        if key in seen:
            continue
        seen[key] = True
        _save(f"{key}.json", {"agent": f"{s['agent_no']} {s['agent_name']}", "input": s["input"], "output": s["output"],
                              "status": s["status"], "duration_ms": s["duration_ms"], "messages_to": s["messages_to"]})

    _save("structured_request.json", {
        "chief_complaint": "Crushing central chest pain spreading to my left arm, sweating and feeling sick for 40 minutes",
        "vitals": {"temperature": 98.2, "heart_rate": 112, "resp_rate": 22, "o2sat": 94, "sbp": 104, "dbp": 68,
                   "pain": 9, "consciousness": "alert"},
        "age": 62, "gender": "M", "arrival_mode": "ambulance", "injury": False})

    cache = ROOT / "evaluation" / "cache" / "llm_cache.jsonl"
    if cache.exists():
        for line in cache.read_text(encoding="utf-8").splitlines():
            rec = json.loads(line)
            if "Triage levels (decide in this order)" in rec["messages"][0]["content"]:
                req = {"url": "https://api.groq.com/openai/v1/chat/completions",
                       "headers": {"Authorization": "Bearer <GROQ_API_KEY>", "Content-Type": "application/json"},
                       "body": {**{k: v for k, v in rec["params"].items() if k != "reasoning_effort"},
                                "reasoning_effort": rec["params"].get("reasoning_effort"),
                                "messages": rec["messages"]}}
                _save("groq_request.json", req)
                _save("groq_response.json", {"choices": [{"index": 0, "message": {"role": "assistant",
                                                                                   "content": rec["response"]},
                                                          "finish_reason": "stop"}],
                                             "usage": rec["usage"], "model": rec["model"],
                                             "note": "content parsed by Agent 4 into TriageResult",
                                             "parsed_content": json.loads(rec["response"])})
                break

    message = TwilioService.format_message("High", "Crushing central chest pain spreading to my left arm", "<session_id>",
                                           None, "Cardiac-sounding chest pain with tachycardia and diaphoresis.")
    _save("n8n_webhook_request.json", {
        "method": "POST", "url": "http://localhost:5678/webhook/triage-alert",
        "headers": {"Content-Type": "application/json", "X-Webhook-Secret": "<N8N_WEBHOOK_SECRET>"},
        "body": {"session_id": "<session_id>", "severity": "High",
                 "chief_complaint": "Crushing central chest pain spreading to my left arm",
                 "reasoning": "Cardiac-sounding chest pain with tachycardia and diaphoresis.", "news2_score": 6,
                 "low_evidence": False, "created_at": "2026-11-21T00:57:41", "message": message, "test_mode": True}})
    _save("n8n_webhook_response.json", {
        "test_mode_true": {"status": "mocked", "channel": "n8n", "message_sid": None, "session_id": "<session_id>"},
        "test_mode_false": {"status": "sent", "channel": "n8n", "message_sid": "SMxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"},
        "severity_not_high": {"status": "skipped", "channel": "n8n", "message_sid": None,
                              "reason": "severity Medium does not alert"},
        "wrong_secret_http_401": {"status": "unauthorized", "channel": "n8n"}})
    _save("twilio_message.json", {
        "api": "POST https://api.twilio.com/2010-04-01/Accounts/<ACCOUNT_SID>/Messages.json (twilio SDK messages.create)",
        "auth": "HTTP Basic <ACCOUNT_SID>:<AUTH_TOKEN>",
        "params": {"from_": "whatsapp:<TWILIO_WHATSAPP_NUMBER>", "to": "whatsapp:<ON_CALL_NUMBER>", "body": message},
        "response_fields_used": {"sid": "SM...", "status": "queued"}})
    _save("feedback_request_response.json", {
        "request": {"method": "POST", "path": "/api/v1/feedback", "headers": {"X-Admin-Key": "<ADMIN_API_KEY>"},
                    "body": {"session_id": "<session_id>", "feedback": "correct", "notes": None, "reviewed_by": "Dr A"}},
        "response_201": {"id": 1, "session_id": "<session_id>", "feedback": "correct", "flagged_for_review": False,
                         "timestamp": "2026-11-21T01:10:00"}})


def _p(x):
    return "n/a" if x is None else f"{100 * x:.1f}%"


def _f(x):
    return "n/a" if x is None else f"{x:.3f}"


def _ci(m, key, pct=True):
    c = (m.get("ci95") or {}).get(key)
    if not c:
        return ""
    return f" (95% CI {_p(c['low'])}-{_p(c['high'])})" if pct else f" (95% CI {_f(c['low'])}-{_f(c['high'])})"


def _sys_line(label, m):
    return (f"- {label}: n={m['n']}; accuracy {_p(m['accuracy'])}{_ci(m, 'accuracy')}; balanced accuracy "
            f"{_p(m['balanced_accuracy'])}; macro-F1 {_f(m['f1_macro'])}{_ci(m, 'f1_macro', False)}; weighted F1 "
            f"{_f(m['f1_weighted'])}; linear kappa {_f(m['kappa_linear'])}; High recall {_p(m['high_recall'])}; "
            f"under-triage {_p(m['under_triage_rate'])}{_ci(m, 'under_triage_rate')}; over-triage "
            f"{_p(m['over_triage_rate'])}" + (f"; ROC-AUC {_f(m['roc_auc_macro_ovr'])}" if m.get("roc_auc_macro_ovr") else ""))


def report_facts():
    path = ROOT / "evaluation" / "results" / "metrics.json"
    if not path.exists():
        return
    m = json.loads(path.read_text(encoding="utf-8"))
    s = get_settings()
    L = ["# REPORT FACTS (bullet facts and numbers only -- not report text)", "",
         f"- Source: `evaluation/results/metrics.json` generated {m['generated_at']}; seed {m['seed']}",
         f"- All LLM runs complete: {m['llm']['all_llm_runs_complete']}", "",
         "## Datasets",
         "- MIMIC-IV-ED Demo v2.2: 64 patients, 222 ED stays, 207 stays with ESI acuity (56 patients); 15 unlabelled excluded",
         "- MIMIC 3-class labels (ESI 1-2 High, 3 Medium, 4-5 Low): High 115, Medium 90, Low 2",
         "- MIMIC knowledge base tables: edstays, triage, diagnosis (545 rows), vitalsign (1,038), medrecon (2,764), pyxis (1,082)",
         "- MIMIC temperature unit: deg F; 1 triage temperature recorded in deg C (36.5) converted; 1 DBP of 879 set missing",
         "- KTAS: Moon et al. (2019) PLoS ONE 14(9) e0216972; 1,267 adult ED visits; 2 Korean EDs (local 688, regional 579); Oct 2016 - Sep 2017; CC BY 4.0",
         "- KTAS ground truth = KTAS_expert: High 246, Medium 487, Low 534; nurse baseline KTAS_RN: High 232, Medium 447, Low 588",
         "- KTAS inputs excluded (leak answer / post-triage): KTAS_RN, KTAS_expert, Error_group, mistriage, Diagnosis in ED, Disposition, Length of stay_min, KTAS duration_min",
         "- KTAS cleaning: 19 distinct Korean complaints (21 rows) translated; 'F/C, C/S' expanded (2 rows); Greek alpha folded (1 row); 0 rows dropped",
         "- KTAS vitals: Korean '측불' (unmeasurable) -> missing (SBP 25, DBP 29, HR 20, RR 22, BT 18, SpO2 9); SpO2 not recorded at the local ED (688 rows); BT deg C -> deg F", "",
         "## Knowledge base (Agent 2, multi-source; change decided 2026-11-22 before any result of the affected KTAS jobs)",
         "- Sources: two datasets -- MIMIC-IV-ED Demo (Beth Israel Deaconess Medical Center ED, Boston, USA; ESI) and KTAS (two Korean EDs, local + regional; KTAS_expert)",
         "- Live system (Space) knowledge base: all 222 MIMIC-IV-ED stays + all 1,267 KTAS records = 1,489 cases: about 1,500 records from two datasets (three emergency departments: one in the USA, two in South Korea)",
         "- Evaluation knowledge base for the KTAS main run: all 222 MIMIC-IV-ED stays + KTAS training split only (886) = 1,108 cases; KTAS validation (190) and test (191) records are never in it (runner.kb_frame raises KnowledgeBaseLeak; unit test)",
         "- MIMIC held-out evaluation unchanged: knowledge base = 114 protocol-v2 training stays; not re-run",
         "- Each retrieved case carries its source label ('MIMIC-IV-ED' or 'KTAS'): API field evidence_cases[].source / case_ref, Agent 2 trace output, Clinician Intake and Doctor Portal evidence tables",
         "- LLM evidence text: each case prefixed 'Source: <label>' when the knowledge base has more than one source; single-source evidence text unchanged (cached MIMIC calls stay valid)",
         "- KTAS knowledge-base file: data/external/ktas/ktas_kb.csv (scripts/build_ktas_kb.py; same preprocessing as the evaluation; fields complaint, KTAS_expert severity, ED diagnosis, disposition, vitals; KTAS_RN not included)",
         "- Frozen configuration unchanged (sha256 unchanged); knowledge-base change recorded in evaluation/frozen_config.json (knowledge_base block + history entry dated 2026-11-22)", ""]
    L += ["## Splits"]
    for ds_name, ds in m["datasets"].items():
        for split, sm in ds["split_summary"].items():
            c = sm["class_counts"]
            L.append(f"- {ds_name.upper()} {split}: {sm['n_cases']} cases, {sm['n_groups']} "
                     f"{'patients' if ds_name == 'mimic' else 'rows'} ({100 * sm['share']:.0f}%); Low {c['Low']}, Medium {c['Medium']}, High {c['High']}")
    L += ["- MIMIC protocol v2 splits: train 114 stays / 21 patients (knowledge base + ML training), development 62 stays / 26 patients (= development-phase validation + test splits), held-out test 31 stays / 9 patients",
          "- MIMIC held-out test drawn only from development-phase training patients (previously knowledge-base only); patient-grouped; stratified on High/Medium; max 9 stays per test patient; seed 42; file evaluation/splits/mimic_split_v2.json",
          "- No patient in two of train / development / test",
          "- Development-phase split (kept for the development results): patient-grouped stratified 70/15/15, 145/31/31 stays, file evaluation/splits/mimic_split.json",
          "- KTAS split method: stratified 70/15/15 on the 3-class expert label",
          "- KTAS main LLM evaluation: full test split, 191 cases (Low 81, Medium 73, High 37): S4 with KB = MIMIC-IV-ED + KTAS train, S3 on the same 191 cases",
          f"- KTAS secondary S4 (KB = MIMIC-IV-ED only): stratified sample of {m['datasets']['ktas'].get('llm_subset', {}).get('n', 'n/a')} test cases (40 Low, 40 Medium, all 37 High) first, then the other 74 test cases, so all three KTAS LLM jobs (S4 multi-source KB, S3, S4 MIMIC-only KB) cover the same 191 cases",
          "- MIMIC held-out test knowledge base: the 114 training stays only (leakage control; unit test proves no test stay is retrieved)",
          "- LLM-free systems S0-S2: trained on the 114 training stays, tuned on the 62-stay development set, 5-fold patient-grouped CV on train + development (176 stays)",
          "- KTAS knowledge bases: main KB = MIMIC-IV-ED (222) + KTAS train (886); secondary KB = MIMIC-IV-ED only (222); the planned KB=KTAS-train-only LLM job was replaced by the multi-source job (S1 retrieval-only still reported for KB=KTAS-train and the multi-source KB)", ""]
    L += ["## Hyperparameters chosen on the tuning set (MIMIC: development set; KTAS: validation split)"]
    for ds_name, ds in m["datasets"].items():
        L.append(f"- {ds_name.upper()} S1: k={ds['s1_config']['k']}, weights {ds['s1_config']['weights']}")
        L.append(f"- {ds_name.upper()} S2a LR: {ds['tuning']['S2a']['best']['params']} (class_weight balanced)")
        L.append(f"- {ds_name.upper()} S2b RF: {ds['tuning']['S2b']['best']['params']} (class_weight balanced)")
        L.append(f"- {ds_name.upper()} best non-LLM system by tuning-set macro-F1 (MIMIC: development set; KTAS: validation split): {ds['best_non_llm_by_validation']}")
    t = m["datasets"]["mimic"]["low_evidence_threshold"]
    L += [f"- LOW_EVIDENCE_THRESHOLD = {t['config_value']} (top-1 similarity); rule: {t['rule']}; selected on non-test data only, OOF retrieval votes over protocol-v2 train + development (n={t['n_development']}): "
          f"flag rate {t['chosen_row']['flag_rate']}, accuracy flagged {t['chosen_row']['acc_flagged']} vs unflagged {t['chosen_row']['acc_unflagged']}",
          f"- LLM: {m['llm']['model']}, temperature {m['llm']['temperature']}, max_tokens {m['llm']['max_tokens']}, reasoning_effort {m['llm']['reasoning_effort']}, max repairs {m['llm']['max_repair_attempts']}, prompt {s.LLM_PROMPT_VERSION}", ""]
    for ds_name, ds in m["datasets"].items():
        L += [f"## Results -- {ds_name.upper()} " + ("held-out test (frozen configuration, evaluated once)" if ds_name == "mimic"
                                                     else "test split, 191 cases (MAIN evaluation, frozen configuration)")]
        for name, met in ds["test"].items():
            L.append(_sys_line(f"{name} ({m['systems'][name]})", met))
        if ds.get("s1_multi_source"):
            L.append(_sys_line(f"S1-mk ({m['systems'].get('S1-mk', 'S1 multi-source KB')})", ds["s1_multi_source"]))
            share = ds["s1_multi_source"].get("neighbour_source_share_top5") or {}
            L.append("- Multi-source KB, top-5 neighbours of the 191 KTAS test queries by source: "
                     + ", ".join(f"{k} {_p(v)}" for k, v in share.items()))
        if ds.get("nurse_all_records"):
            L.append(_sys_line("H triage nurse (KTAS_RN) on ALL KTAS records", ds["nurse_all_records"]))
        for job, entry in ds.get("llm_systems", {}).items():
            for sname in ("S3", "S4", "S4-noNEWS2", "S4-promptv1"):
                if sname in entry:
                    tag = "" if entry["complete"] else f" [INCOMPLETE {entry['n_done']}/{entry['n_target']}]"
                    L.append(_sys_line(f"{sname} KB={job.split('kb=')[-1]}{tag}", entry[sname]))
        if "llm_subset" in ds:
            L.append(f"- Same {ds['llm_subset']['n']}-case KTAS sample (used by the secondary S4 job, KB = MIMIC-IV-ED only):")
            for name, met in ds["llm_subset"]["systems"].items():
                L.append("  " + _sys_line(f"{name} ({m['systems'][name]})", met))
        for job, entry in ds.get("llm_development", {}).items():
            for sname in ("S4", "S4-promptv1"):
                if sname in entry:
                    L.append(_sys_line(f"DEVELOPMENT SET (not held-out) {sname} {job}", entry[sname]))
        cv = ds["cross_validation"]
        L.append(f"- 5-fold CV ({cv['method']}): " + "; ".join(
            f"{k} macro-F1 {v['f1_macro']['mean']:.3f} ± {v['f1_macro']['std']:.3f}, accuracy {v['accuracy']['mean']:.3f} ± {v['accuracy']['std']:.3f}"
            for k, v in cv["systems"].items()))
        for kb, r in ds["retrieval_quality"].items():
            L.append(f"- Retrieval quality KB={kb}: P@1 {_f(r['precision_at_1'])}, P@3 {_f(r['precision_at_3'])}, P@5 {_f(r['precision_at_5'])}, "
                     f"mean top-1 similarity {_f(r['mean_top1_similarity'])}, no-evidence rate {_p(r['no_evidence_rate'])}")
        for k, v in ds.get("mcnemar", {}).items():
            L.append(f"- McNemar {k}: {v['a_correct_b_wrong']} vs {v['a_wrong_b_correct']} discordant, exact p = {v['p_value_exact']:.4f}")
        for k, v in ds.get("llm_systems", {}).items():
            a = v.get("agent_performance")
            if a:
                lat = a["latency_ms"]
                L.append(f"- Agent performance {k}: first-pass guardrail validity {_p(a['guardrail_first_pass_valid_rate'])}, repair rate {_p(a['repair_rate'])}, "
                         f"failed {a['failed_after_repairs']}, NEWS2 overrides {a['news2_override_count']}, weak-evidence flags {_p(a['low_evidence_flag_rate'])}, "
                         f"median latency Agent 2 {lat['agent2_retrieval'].get('median', 0):.1f} ms / Agent 3 {lat['agent3_llm'].get('median', 0):.0f} ms "
                         f"(p95 {lat['agent3_llm'].get('p95', 0):.0f}) / Agent 4 {lat['agent4_guardrail_news2'].get('median', 0):.2f} ms, "
                         f"tokens per case {a['mean_tokens_per_case'] or 0:.0f}")
            if v.get("evidence_source_share"):
                L.append(f"- Evidence sources {k} (all retrieved cases): "
                         + ", ".join(f"{src} {_p(x)}" for src, x in v["evidence_source_share"].items()))
        for k, v in ds.get("low_evidence_analysis", {}).items():
            fw, nf = v["flagged_weak"], v["not_flagged"]
            L.append(f"- Weak-evidence flag {k}: flagged n={fw['n']} accuracy {_p(fw.get('accuracy'))} under-triage {_p(fw.get('under_triage_rate'))}; "
                     f"not flagged n={nf['n']} accuracy {_p(nf.get('accuracy'))} under-triage {_p(nf.get('under_triage_rate'))}")
        for system, groups in ds.get("subgroups", {}).items():
            for gname, gres in groups.items():
                L.append(f"- Subgroup {system} by {gname}: " + "; ".join(
                    f"{g} n={v['n']} acc {_p(v['accuracy'])} under {_p(v['under_triage_rate'])}" for g, v in gres.items()))
        L.append("")
    fz = m.get("protocol", {}).get("frozen_config", {})
    L += ["## Development process (facts)",
          "- Step 1 (development set): prompt v1 = previous release prompt ('assign Low if mild and no red flags; NEVER default to Medium or High'); on the 31 development stays of the development-phase test half: 18/31 predicted Low, under-triage 64.5%",
          "- Step 2 (development set): prompt v2 written from the ESI/KTAS level definitions (high-risk complaints High even with normal vitals; danger-zone vitals; resource-based Medium/Low; uncertain -> more urgent)",
          "- Step 3 (development set): v2 checked on the development set (62 stays) -- results in the 'Development set' table",
          "- Step 4: configuration frozen on 2026-11-21 and re-frozen on 2026-11-22 after the non-test threshold re-selection (prompt v2, weights, k=5, LOW_EVIDENCE_THRESHOLD 0.50, repair attempts 2, NEWS2 on, model settings); sha256 " + str(fz.get("sha256", ""))[:16] + "...; stored in evaluation/frozen_config.json; held-out jobs refuse to run if the live configuration differs",
          "- Step 5: frozen system evaluated once on the new held-out MIMIC test split (S4, S3, S4-promptv1, S4-noNEWS2 from the same calls) and on KTAS (external, prompt v2 for every KTAS job)",
          "- LOW_EVIDENCE_THRESHOLD re-selected on 2026-11-22, before any held-out LLM run, with the same rule (largest accuracy drop unflagged - flagged, 10-40% flagged, candidates 0.300-0.700 step 0.025) on non-test data only: 5-fold patient-grouped out-of-fold retrieval votes (Agent 2) over the 114 training + 62 development stays (176); no held-out test stay involved; result 0.50 (flag rate 33.5%, accuracy flagged 61.0% vs unflagged 62.4%) = same value as the first selection, kept",
          "- Configuration re-frozen on 2026-11-22 after the threshold re-selection; config hash unchanged",
          "- Step 6 (2026-11-22, decided before any result of the affected KTAS jobs): multi-source knowledge base (MIMIC-IV-ED + KTAS) as in Feature 2 'Multi-Source Evidence-Grounded Reasoning' of the submitted workflow; KTAS becomes the main evaluation (full 191-case test split; S4 KB = all MIMIC + KTAS train; S3 on the same cases); KB=KTAS-train-only job replaced; KB=MIMIC-only job kept (117-case sample); MIMIC held-out (31 stays) kept as a secondary check, not re-run; all other frozen settings unchanged",
          "- Step 7 (2026-11-22, student decision): the KB=MIMIC-only KTAS job is extended from the 117-case sample to all 191 test cases (74 more calls), so S4 multi-source KB, S3 and S4 MIMIC-only KB are compared on the same 191 cases",
          "", "## Live system facts",
          "- Example local run (High demo case): Agent 2 632 ms, Agent 3 1,224 ms (1,637 tokens), Agent 4 0.1 ms, Agent 5 12 ms (mocked)",
          "- Whisper base.en first transcription incl. model load: 19.3 s on CPU (demo clip, 9 s of speech)",
          f"- Weak-evidence banner text: 'Weak historical evidence — treat this recommendation with caution.'",
          "- NEWS2 assumption: room air (supplemental oxygen not captured); SpO2 scale 1",
          "", "## Limitations (facts)",
          "- MIMIC-IV-ED Demo is small: 207 labelled stays; held-out test split 31 stays from 9 patients; MIMIC Low class has 2 stays in total (1 in held-out test, 1 in development, 0 in training)",
          "- KTAS (Korea) and ESI (MIMIC, USA) are different 5-level scales; both mapped to the same 3 tiers",
          "- Secondary KB=MIMIC-only run for KTAS is a cross-site, cross-scale transfer; in the main multi-source KB most KTAS test neighbours come from KTAS train",
          "- Groq free tier: 1,000 requests/day, 8,000 tokens/minute; LLM evaluation run over several days with a response cache",
          "- The Hugging Face Space cannot reach a locally running n8n; Space uses direct Twilio / mocked alerts",
          "- Decision support only: every recommendation is reviewed by a clinician",
          "- Retrieval synonym map sends 'blood' -> 'bleed' (e.g. 'blood pressure tablets' matched a GI-bleed case at 0.53)",
          ""]
    (ASSETS / "REPORT_FACTS.md").write_text("\n".join(L), encoding="utf-8")


if __name__ == "__main__":
    ASSETS.mkdir(exist_ok=True)
    environment()
    json_examples()
    report_facts()
    print("report_assets updated:", sorted(p.name for p in ASSETS.iterdir()))
