"""
Final architecture diagram (print-friendly, white background) ->
report_assets/figures/architecture.png (300 dpi) and architecture.svg.

Agent names follow the submitted workflow (Umit_Kayaardi_3231603_Workflow.pdf).

  python scripts/build_architecture_diagram.py
"""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "report_assets" / "figures"

INK = "#1f2933"
MUTED = "#52606d"
AGENT_FILL = "#e8f0fb"
AGENT_EDGE = "#2f5d9e"
DATA_FILL = "#eef6ee"
DATA_EDGE = "#3f7d46"
EXT_FILL = "#f6f1e7"
EXT_EDGE = "#8a6d3b"
MON_FILL = "#f3eefa"
MON_EDGE = "#6b4fa0"
UI_FILL = "#f4f5f7"
UI_EDGE = "#7b8794"
FLAG_FILL = "#fff6d6"
FLAG_EDGE = "#b7791f"
REPAIR = "#b42318"


def box(ax, x0, y0, x1, y1, title, body="", fill=AGENT_FILL, edge=AGENT_EDGE, title_size=9.5, body_size=7.8,
        lw=1.4, dashed=False):
    ax.add_patch(FancyBboxPatch((x0, y0), x1 - x0, y1 - y0, boxstyle="round,pad=0.25,rounding_size=0.8",
                                fc=fill, ec=edge, lw=lw, ls="--" if dashed else "-"))
    cx = (x0 + x1) / 2
    if body:
        ax.text(cx, y1 - 0.9, title, ha="center", va="top", fontsize=title_size, fontweight="bold", color=INK,
                linespacing=1.15)
        n_title = title.count("\n") + 1
        ax.text(cx, y1 - 1.1 - 1.6 * n_title, body, ha="center", va="top", fontsize=body_size, color=MUTED,
                linespacing=1.3)
    else:
        ax.text(cx, (y0 + y1) / 2, title, ha="center", va="center", fontsize=title_size, fontweight="bold",
                color=INK, linespacing=1.2)


def arrow(ax, p0, p1, label="", color=INK, dashed=False, rad=0.0, lw=1.3, label_xy=None, label_size=7.3):
    ax.add_patch(FancyArrowPatch(p0, p1, arrowstyle="-|>", mutation_scale=11, lw=lw, color=color,
                                 ls=(0, (4, 3)) if dashed else "-", connectionstyle=f"arc3,rad={rad}",
                                 shrinkA=2, shrinkB=2))
    if label:
        lx, ly = label_xy if label_xy else ((p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2 + 0.9)
        ax.text(lx, ly, label, ha="center", va="center", fontsize=label_size, color=color,
                bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="none", alpha=0.95))


def main() -> None:
    fig, ax = plt.subplots(figsize=(16.5, 11))
    ax.set_xlim(0, 106.5)
    ax.set_ylim(0, 69)
    ax.axis("off")
    fig.patch.set_facecolor("white")

    ax.text(52, 68.6, "NHS Clinical Triage Assistant: 7-agent architecture", ha="center", va="top", fontsize=15,
            fontweight="bold", color=INK)
    ax.text(52, 66.3, "FastAPI backend + Gradio UI (Hugging Face Space)  ·  decision support only: every "
            "recommendation is reviewed by a clinician", ha="center", va="top", fontsize=9, color=MUTED)

    # --- Agent trace band ---------------------------------------------------------------------------
    box(ax, 17.5, 60.2, 99.9, 63.6, "Agent trace: every step records input, action, output, duration and status  "
        "→  console log, Doctor Portal trace view, GET /api/v1/sessions/{id}/trace", fill="#fafbfc",
        edge=UI_EDGE, title_size=8.6, lw=1.0, dashed=True)

    # --- Inputs ---------------------------------------------------------------------------------------
    box(ax, 1.0, 45.0, 14.0, 52.0, "Patient Kiosk", "voice recording\n(microphone or file)", fill=UI_FILL,
        edge=UI_EDGE)
    box(ax, 1.0, 35.0, 14.0, 42.0, "Clinician Intake", "typed complaint, vitals,\npain, ACVPU, arrival",
        fill=UI_FILL, edge=UI_EDGE)

    # --- Main pipeline (Agents 1-5) -------------------------------------------------------------------
    xs = [(17.5, 30.3), (34.9, 47.7), (52.3, 65.1), (69.7, 82.5), (87.1, 99.9)]
    y0, y1 = 34.0, 53.0
    texts = [
        ("Agent 1\nData Intake &\nTranscription Agent",
         "Whisper base.en (CPU)\nspeech → text;\nrejects silent audio;\nstructured intake\nskips transcription"),
        ("Agent 2\nEvidence Retrieval\nAgent",
         "TF-IDF + clinical synonyms\n+ vitals similarity;\ntop 5 cases, each with\nits source label;\n"
         "evidence strength:\nstrong / moderate / weak"),
        ("Agent 3\nClinical Reasoning\nAgent",
         "Groq openai/gpt-oss-20b\ntemperature 0, prompt v2\n(ESI / KTAS definitions)\n→ severity, reasoning,\n"
         "required actions"),
        ("Agent 4\nMedical Guardrail\nAgent",
         "(a) Pydantic schema check\n(b) NEWS2 safety net\n(raise only):\nscore ≥ 7 or a single\n"
         "parameter = 3 → High;\nscore 5-6 → Medium"),
        ("Agent 5\nOrchestrator &\nAction Agent",
         "alert for High severity;\nn8n webhook first,\ndirect Twilio fallback;\nchannel logged:\n"
         "n8n / twilio_direct /\nmocked"),
    ]
    for (a, b), (title, body) in zip(xs, texts):
        box(ax, a, y0, b, y1, title, body)

    arrow(ax, (14.0, 48.5), (17.5, 46.0))
    arrow(ax, (14.0, 38.5), (17.5, 41.0))
    for i, lab in enumerate(["transcript\n+ vitals", "evidence\nblock", "draft\nJSON", "final\nseverity"]):
        xa, xb = xs[i][1], xs[i + 1][0]
        yy = 44.5 if i != 2 else 46.0
        arrow(ax, (xa, yy), (xb, yy), lab, label_xy=((xa + xb) / 2, yy - 3.2), label_size=7.0)

    # Guardrail -> reasoning repair loop (arc above Agents 3-4)
    arrow(ax, (76.1, 53.0), (58.7, 53.0), color=REPAIR, rad=0.35, lw=1.6)
    ax.text(67.4, 57.6, "repair loop: invalid output → validation error sent back to Agent 3 "
            "(max 2 repairs, then HTTP 502)", ha="center", va="center", fontsize=7.4, color=REPAIR,
            bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="none"))

    # Weak-evidence flag (WP2)
    box(ax, 41.5, 26.0, 65.1, 31.4, "Weak-evidence flag",
        "top-1 similarity < 0.50 → told to the LLM;\nyellow banner on the result card", fill=FLAG_FILL,
        edge=FLAG_EDGE, title_size=8.4, body_size=7.3)
    arrow(ax, (44.5, 34.0), (44.5, 31.4), color=FLAG_EDGE)
    arrow(ax, (60.0, 31.4), (60.0, 34.0), color=FLAG_EDGE)

    # --- Multi-source knowledge base ------------------------------------------------------------------
    box(ax, 17.5, 13.8, 47.7, 24.2, "Multi-source knowledge base (Agent 2)",
        "about 1,500 records from two datasets\n(three emergency departments: one in the USA, two in South Korea)\n"
        "MIMIC-IV-ED Demo: 222 ED stays, 6 tables (USA)\nKTAS: 1,267 ED records (South Korea)\n"
        "each retrieved case labelled 'MIMIC-IV-ED' or 'KTAS'", fill=DATA_FILL, edge=DATA_EDGE, body_size=7.3)
    arrow(ax, (37.5, 24.2), (37.5, 34.0), color=DATA_EDGE, label="similar\ncases", label_xy=(37.5, 29.2))

    # --- Persistence ----------------------------------------------------------------------------------
    box(ax, 52.3, 14.8, 82.5, 22.6, "SQLite database (Git LFS)",
        "triage_sessions: result, evidence, NEWS2,\noverride, agent trace\nalert_log (channel) · "
        "triage_session_feedback · drift_metrics", fill=DATA_FILL, edge=DATA_EDGE, body_size=7.3)
    arrow(ax, (76.1, 34.0), (76.1, 22.6), color=DATA_EDGE, label="save session\n+ trace", label_xy=(76.1, 28.6))

    # --- n8n / Twilio ---------------------------------------------------------------------------------
    box(ax, 87.1, 20.5, 99.9, 29.5, "n8n workflow",
        "webhook → secret check\n→ severity → test mode\n→ Twilio node", fill=EXT_FILL, edge=EXT_EDGE)
    box(ax, 87.1, 7.5, 99.9, 15.5, "Twilio WhatsApp",
        "on-call clinician;\ntest mode → mocked", fill=EXT_FILL, edge=EXT_EDGE)
    arrow(ax, (93.5, 34.0), (93.5, 29.5), color=EXT_EDGE, label="POST event", label_xy=(93.5, 31.8))
    arrow(ax, (93.5, 20.5), (93.5, 15.5), color=EXT_EDGE)
    arrow(ax, (100.1, 37.0), (100.1, 12.0), color=EXT_EDGE, dashed=True, rad=-0.3)
    ax.text(105.4, 24.5, "fallback: direct Twilio if n8n unavailable", ha="center", va="center", fontsize=7.0,
            color=EXT_EDGE, rotation=90)

    # --- Monitoring layer -----------------------------------------------------------------------------
    ax.add_patch(FancyBboxPatch((17.0, 0.6), 66.0, 11.8, boxstyle="round,pad=0.2,rounding_size=0.8", fc="none",
                                ec=MON_EDGE, lw=1.0, ls=(0, (2, 2))))
    ax.text(18.0, 12.3, "Monitoring layer", ha="left", va="top", fontsize=8.6, fontweight="bold", color=MON_EDGE)
    box(ax, 17.5, 1.2, 30.3, 9.8, "Doctor Portal (PIN)",
        "cards, evidence tables,\ntrace view, clinician\nreview (correct / incorrect)", fill=UI_FILL, edge=UI_EDGE,
        title_size=8.6, body_size=7.2)
    box(ax, 34.9, 1.2, 47.7, 9.8, "Agent 6\nPost-Deployment\nMonitor Agent",
        "accuracy, hallucination rate,\nflagged queue, PMS report", fill=MON_FILL, edge=MON_EDGE,
        title_size=8.4, body_size=7.0)
    box(ax, 52.3, 1.2, 65.1, 9.8, "Agent 7\nDrift Detection &\nBias Monitor Agent",
        "drift: JS, KS\nbias: chi², Cramér's V", fill=MON_FILL, edge=MON_EDGE, title_size=8.4, body_size=7.0)
    box(ax, 69.7, 1.2, 82.5, 9.8, "Admin endpoints\n(API key)",
        "/admin/accuracy · /admin/flagged\n/admin/pms-report · /admin/drift\n/admin/system-health · /alerts\n"
        "→ Admin / Supervisor tab", fill=UI_FILL, edge=UI_EDGE, title_size=8.4, body_size=6.6)
    arrow(ax, (30.3, 4.0), (34.9, 4.0), color=MON_EDGE, label="feedback", label_xy=(32.6, 2.4), label_size=6.4)
    arrow(ax, (47.7, 5.0), (52.3, 5.0), color=MON_EDGE)
    arrow(ax, (65.1, 5.0), (69.7, 5.0), color=MON_EDGE)
    arrow(ax, (54.5, 14.8), (27.0, 9.8), color=DATA_EDGE, rad=0.05, label="sessions", label_xy=(41.0, 12.9),
          label_size=6.8)
    arrow(ax, (62.0, 14.8), (60.0, 9.8), color=DATA_EDGE)
    ax.text(62.6, 12.2, "session logs", fontsize=6.8, color=DATA_EDGE, ha="left", va="center")

    # --- Legend ---------------------------------------------------------------------------------------
    lx, ly = 1.0, 30.0
    ax.text(lx, ly, "Legend", fontsize=8.6, fontweight="bold", color=INK, va="top")
    items = [(AGENT_FILL, AGENT_EDGE, "agent (1-5: clinical pipeline)"), (MON_FILL, MON_EDGE, "monitoring agent (6-7)"),
             (DATA_FILL, DATA_EDGE, "data store"), (EXT_FILL, EXT_EDGE, "external service"),
             (FLAG_FILL, FLAG_EDGE, "safety flag"), (UI_FILL, UI_EDGE, "user interface / API")]
    for i, (fc, ec, txt) in enumerate(items):
        yy = ly - 2.6 - i * 2.3
        ax.add_patch(FancyBboxPatch((lx, yy - 0.7), 2.2, 1.4, boxstyle="round,pad=0.1", fc=fc, ec=ec, lw=1.0))
        ax.text(lx + 3.0, yy, txt, fontsize=7.6, color=INK, va="center")
    yy = ly - 2.6 - len(items) * 2.3
    for style, color, txt in (("-", INK, "data flow"), ((0, (4, 3)), INK, "fallback path"),
                              ("-", REPAIR, "repair loop")):
        ax.annotate("", xy=(lx + 2.4, yy), xytext=(lx, yy), arrowprops=dict(arrowstyle="-|>", color=color, lw=1.3,
                                                                            ls=style))
        ax.text(lx + 3.0, yy, txt, fontsize=7.6, color=INK, va="center")
        yy -= 2.3

    OUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT / "architecture.png", dpi=300, facecolor="white", bbox_inches="tight", pad_inches=0.15)
    fig.savefig(OUT / "architecture.svg", facecolor="white", bbox_inches="tight", pad_inches=0.15)
    plt.close(fig)
    print("wrote", OUT / "architecture.png", "and architecture.svg")


if __name__ == "__main__":
    main()
