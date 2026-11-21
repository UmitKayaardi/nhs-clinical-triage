"""
Evaluation figures: 300 dpi PNG, colour-blind-safe categorical palette
(validated reference palette, light mode), titled and labelled, one axis
per chart, values printed so the figures read in black-and-white print.
"""

from typing import Dict, List

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from evaluation.common import FIGURES_DIR, LABELS  # noqa: E402

SLOTS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
NEUTRAL = "#8f8d86"
TEXT = "#0b0b0b"
TEXT2 = "#52514e"
GRID = "#e4e3df"
HIGHLIGHT = {"S4": SLOTS[0], "H": SLOTS[6]}

plt.rcParams.update({
    "font.size": 9, "axes.titlesize": 10, "axes.titleweight": "bold", "axes.labelcolor": TEXT2,
    "axes.edgecolor": "#b9b8b2", "xtick.color": TEXT2, "ytick.color": TEXT2, "axes.spines.top": False,
    "axes.spines.right": False, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6,
    "axes.axisbelow": True, "figure.dpi": 100, "savefig.dpi": 300, "savefig.bbox": "tight",
    "legend.frameon": False,
})


def _save(fig, name: str, out: List[str]) -> None:
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIGURES_DIR / name, facecolor="white")
    plt.close(fig)
    out.append(f"evaluation/results/figures/{name}")


def _systems_for(ds: Dict, dataset: str) -> Dict[str, Dict]:
    """Ordered {display name: metrics} for the test comparison (LLM systems on their own case set)."""
    systems = {k: v for k, v in ds["test"].items()}
    for job, entry in ds.get("llm_systems", {}).items():
        kb = job.split("kb=")[-1]
        for s in ("S3", "S4", "S4-noNEWS2", "S4-promptv1"):
            if s in entry:
                label = s if s == "S3" else f"{s} [KB {kb}]"
                if not entry["complete"]:
                    label += f" ({entry['n_done']}/{entry['n_target']})"
                systems[label] = entry[s]
    return systems


def confusion_grid(dataset: str, ds: Dict, out: List[str]) -> None:
    panels = [("S1", ds["test"].get("S1")), ("S2b", ds["test"].get("S2b"))]
    for job, entry in ds.get("llm_systems", {}).items():
        kb = job.split("kb=")[-1]
        if "S3" in entry:
            panels.append(("S3 (no evidence)", entry["S3"]))
        if "S4" in entry:
            panels.append((f"S4 [KB {kb}]", entry["S4"]))
    if "H" in ds["test"]:
        panels.append(("H nurse (full test)", ds["test"]["H"]))
    panels = [p for p in panels if p[1]]
    n = len(panels)
    cols = min(3, n)
    rows = int(np.ceil(n / cols))
    fig, axes = plt.subplots(rows, cols, figsize=(3.2 * cols, 3.0 * rows), squeeze=False)
    for ax, (title, m) in zip(axes.flat, panels):
        cm = np.array(m["confusion_matrix"])
        norm = np.array(m["confusion_matrix_normalised"])
        ax.imshow(norm, cmap="Blues", vmin=0, vmax=1)
        ax.grid(False)
        for i in range(3):
            for j in range(3):
                ax.text(j, i, f"{cm[i, j]}\n{100 * norm[i, j]:.0f}%", ha="center", va="center", fontsize=8,
                        color="white" if norm[i, j] > 0.55 else TEXT)
        ax.set_xticks(range(3), LABELS)
        ax.set_yticks(range(3), LABELS)
        ax.set_xlabel("Predicted")
        ax.set_ylabel("True")
        ax.set_title(f"{title}\n(n={m['n']}, acc {100 * m['accuracy']:.0f}%)", fontsize=9)
    for ax in list(axes.flat)[n:]:
        ax.axis("off")
    fig.suptitle(f"{dataset.upper()} test -- confusion matrices (counts and row %)", fontweight="bold", y=1.02)
    fig.tight_layout()
    _save(fig, f"confusion_matrices_{dataset}.png", out)


def _bar_with_ci(dataset: str, systems: Dict[str, Dict], key: str, ci_key: str, title: str, xlabel: str,
                 name: str, out: List[str], pct: bool) -> None:
    labels = list(systems)
    vals = [systems[s][key] for s in labels]
    lows, highs = [], []
    for s in labels:
        ci = (systems[s].get("ci95") or {}).get(ci_key)
        lows.append(vals[labels.index(s)] - ci["low"] if ci else 0)
        highs.append(ci["high"] - vals[labels.index(s)] if ci else 0)
    colors = [HIGHLIGHT["S4"] if s.startswith("S4 ") else HIGHLIGHT["H"] if s == "H" else NEUTRAL for s in labels]
    fig, ax = plt.subplots(figsize=(6.4, 0.42 * len(labels) + 1.2))
    y = np.arange(len(labels))
    ax.barh(y, vals, color=colors, height=0.62, xerr=[lows, highs], error_kw={"ecolor": TEXT2, "lw": 1, "capsize": 3})
    for yi, v in zip(y, vals):
        ax.text(v + 0.01, yi + 0.28, f"{100 * v:.1f}%" if pct else f"{v:.2f}", va="center", fontsize=8, color=TEXT)
    ax.set_yticks(y, labels)
    ax.invert_yaxis()
    ax.set_xlim(0, 1.05)
    ax.set_xlabel(xlabel)
    ax.grid(axis="y", visible=False)
    ax.set_title(title)
    fig.text(0.01, -0.02, "Error bars: 95% bootstrap CI (1,000 resamples). Blue = full system, violet = nurse, "
             "grey = baselines/ablations.", fontsize=7, color=TEXT2)
    _save(fig, name, out)


def nurse_vs_system(ds: Dict, out: List[str]) -> None:
    if "llm_subset" not in ds:
        return
    series = {"H nurse": ds["llm_subset"]["systems"]["H"]}
    for job, entry in ds.get("llm_systems", {}).items():
        if "S4" in entry:
            series[f"S4 KB {job.split('kb=')[-1]}"] = entry["S4"]
    if len(series) < 2:
        return
    metrics = [("accuracy", "Accuracy"), ("f1_macro", "Macro-F1"), ("high_recall", "High recall"),
               ("under_triage_rate", "Under-triage"), ("over_triage_rate", "Over-triage")]
    colors = [SLOTS[6], SLOTS[0], SLOTS[2]]
    fig, ax = plt.subplots(figsize=(7.2, 3.4))
    x = np.arange(len(metrics))
    w = 0.8 / len(series)
    for i, (name, m) in enumerate(series.items()):
        vals = [m[k] for k, _ in metrics]
        bars = ax.bar(x + (i - (len(series) - 1) / 2) * w, vals, w * 0.92, color=colors[i % 3], label=f"{name} (n={m['n']})")
        for b, v in zip(bars, vals):
            ax.text(b.get_x() + b.get_width() / 2, v + 0.01, f"{100 * v:.0f}", ha="center", fontsize=7, color=TEXT)
    ax.set_xticks(x, [m[1] for m in metrics])
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("Rate (labels in %)")
    ax.grid(axis="x", visible=False)
    ax.legend(loc="upper right", fontsize=8)
    ax.set_title("KTAS: triage nurse vs full system on the same LLM test sample (truth = KTAS_expert)")
    _save(fig, "nurse_vs_system_ktas.png", out)


def cv_boxplot(dataset: str, ds: Dict, out: List[str]) -> None:
    cv = ds["cross_validation"]["systems"]
    names = list(cv)
    data = [cv[n]["f1_macro"]["folds"] for n in names]
    fig, ax = plt.subplots(figsize=(5.2, 3.2))
    ax.boxplot(data, widths=0.5, patch_artist=True, boxprops={"facecolor": "#dbe8f8", "edgecolor": SLOTS[0]},
               medianprops={"color": SLOTS[0], "lw": 2}, whiskerprops={"color": TEXT2}, capprops={"color": TEXT2})
    for i, d in enumerate(data, 1):
        ax.scatter(np.full(len(d), i) + np.linspace(-0.08, 0.08, len(d)), d, s=14, color=TEXT2, zorder=3)
        ax.text(i, max(d) + 0.03, f"{np.mean(d):.2f} ± {np.std(d, ddof=1):.2f}", ha="center", fontsize=7, color=TEXT)
    ax.set_xticks(range(1, len(names) + 1), names)
    ax.set_ylabel("Macro-F1 per fold")
    ax.set_ylim(0, 1)
    ax.grid(axis="x", visible=False)
    ax.set_title(f"{dataset.upper()}: 5-fold cross-validation (train + validation)")
    _save(fig, f"cv_boxplot_{dataset}.png", out)


def per_class_f1(dataset: str, systems: Dict[str, Dict], out: List[str]) -> None:
    names = [s for s in systems if not s.startswith("S0")]
    fig, ax = plt.subplots(figsize=(7.2, 3.2))
    x = np.arange(len(names))
    w = 0.26
    for i, label in enumerate(LABELS):
        vals = [systems[s]["per_class"][label]["f1"] for s in names]
        support = systems[names[0]]["per_class"][label]["support"]
        ax.bar(x + (i - 1) * w, vals, w * 0.92, color=SLOTS[[2, 3, 7][i]], label=f"{label} (test support {support})")
    ax.set_xticks(x, names, rotation=25, ha="right")
    ax.set_ylim(0, 1)
    ax.set_ylabel("F1")
    ax.grid(axis="x", visible=False)
    ax.legend(fontsize=7, ncols=3, loc="upper center", bbox_to_anchor=(0.5, 1.13))
    ax.set_title(f"{dataset.upper()}: per-class F1 on the test split", pad=26)
    _save(fig, f"per_class_f1_{dataset}.png", out)


def latency(metrics: Dict, out: List[str]) -> None:
    rows = []
    for dataset, ds in metrics["datasets"].items():
        for job, entry in ds.get("llm_systems", {}).items():
            if "S4" in entry and "agent_performance" in entry:
                rows.append((f"{dataset.upper()} KB {job.split('kb=')[-1]}", entry["agent_performance"]["latency_ms"]))
    if not rows:
        return
    agents = [("agent2_retrieval", "Agent 2 Retrieval"), ("agent3_llm", "Agent 3 LLM (Groq)"),
              ("agent4_guardrail_news2", "Agent 4 Guardrail + NEWS2")]
    fig, ax = plt.subplots(figsize=(7.0, 3.2))
    x = np.arange(len(agents))
    w = 0.8 / len(rows)
    for i, (name, lat) in enumerate(rows):
        med = [max(lat[a].get("median", 0), 0.01) for a, _ in agents]
        p95 = [max(lat[a].get("p95", 0), 0.01) for a, _ in agents]
        pos = x + (i - (len(rows) - 1) / 2) * w
        ax.bar(pos, med, w * 0.9, color=SLOTS[i], label=name)
        ax.scatter(pos, p95, marker="_", s=120, color=TEXT, zorder=3)
        for px, v in zip(pos, med):
            ax.text(px, v * 1.15, f"{v:.0f}" if v >= 10 else f"{v:.2f}", ha="center", fontsize=7, color=TEXT)
    ax.set_yscale("log")
    ax.set_xticks(x, [a[1] for a in agents])
    ax.set_ylabel("Milliseconds (log scale)")
    ax.grid(axis="x", visible=False)
    ax.legend(fontsize=7)
    ax.set_title("Latency per agent: median (bars) and p95 (black ticks)")
    _save(fig, "latency_per_agent.png", out)


def low_evidence(metrics: Dict, out: List[str]) -> None:
    rows = []
    for dataset, ds in metrics["datasets"].items():
        for job, v in ds.get("low_evidence_analysis", {}).items():
            rows.append((f"{dataset.upper()} KB {job.split('kb=')[-1]}", v))
    if not rows:
        return
    fig, ax = plt.subplots(figsize=(6.4, 3.2))
    x = np.arange(len(rows))
    w = 0.38
    for i, (key, label, color) in enumerate((("flagged_weak", "Weak evidence (flagged)", SLOTS[3]),
                                             ("not_flagged", "Not flagged", SLOTS[0]))):
        vals = [r[1][key].get("accuracy") or 0 for r in rows]
        ns = [r[1][key]["n"] for r in rows]
        bars = ax.bar(x + (i - 0.5) * w, vals, w * 0.92, color=color, label=label)
        for b, v, n in zip(bars, vals, ns):
            ax.text(b.get_x() + b.get_width() / 2, v + 0.01, f"{100 * v:.0f}%\nn={n}", ha="center", fontsize=7, color=TEXT)
    ax.set_xticks(x, [r[0] for r in rows])
    ax.set_ylim(0, 1.15)
    ax.set_ylabel("S4 accuracy")
    ax.grid(axis="x", visible=False)
    ax.legend(fontsize=8, loc="upper right")
    ax.set_title("Full system accuracy: weak-evidence flagged vs not flagged")
    _save(fig, "low_evidence_accuracy.png", out)


def subgroups(dataset: str, ds: Dict, out: List[str]) -> None:
    sg = ds.get("subgroups") or {}
    systems = list(sg)
    if not systems:
        return
    bars = []
    for system in systems:
        for gname, groups in sg[system].items():
            for g, v in groups.items():
                if g != "unknown":
                    bars.append((system, f"{gname.replace('_', ' ')}: {g}", v))
    group_labels = list(dict.fromkeys(b[1] for b in bars))
    fig, ax = plt.subplots(figsize=(7.2, 3.3))
    x = np.arange(len(group_labels))
    w = 0.8 / len(systems)
    for i, system in enumerate(systems):
        vals = [next((b[2]["accuracy"] for b in bars if b[0] == system and b[1] == gl), np.nan) for gl in group_labels]
        ns = [next((b[2]["n"] for b in bars if b[0] == system and b[1] == gl), 0) for gl in group_labels]
        pos = x + (i - (len(systems) - 1) / 2) * w
        ax.bar(pos, vals, w * 0.9, color=SLOTS[[0, 6, 2, 1][i % 4]] if system != "S2b" else NEUTRAL, label=system)
        for px, v, n in zip(pos, vals, ns):
            if not np.isnan(v):
                ax.text(px, v + 0.01, f"{100 * v:.0f}", ha="center", fontsize=6.5, color=TEXT)
    ax.set_xticks(x, [f"{gl}" for gl in group_labels], rotation=15)
    ax.set_ylim(0, 1.1)
    ax.set_ylabel("Accuracy (labels in %)")
    ax.grid(axis="x", visible=False)
    ax.legend(fontsize=7, ncols=len(systems), loc="upper center", bbox_to_anchor=(0.5, 1.14))
    ax.set_title(f"{dataset.upper()}: accuracy by subgroup (LLM case set)", pad=24)
    _save(fig, f"subgroups_{dataset}.png", out)


def make_all(metrics: Dict, job_results: Dict) -> List[str]:
    out: List[str] = []
    for dataset, ds in metrics["datasets"].items():
        systems = _systems_for(ds, dataset)
        confusion_grid(dataset, ds, out)
        _bar_with_ci(dataset, systems, "f1_macro", "f1_macro", f"{dataset.upper()}: macro-F1 by system (test)",
                     "Macro-F1", f"model_comparison_f1_{dataset}.png", out, pct=False)
        _bar_with_ci(dataset, systems, "under_triage_rate", "under_triage_rate",
                     f"{dataset.upper()}: under-triage rate by system (test, lower is safer)",
                     "Under-triage rate", f"under_triage_{dataset}.png", out, pct=True)
        cv_boxplot(dataset, ds, out)
        per_class_f1(dataset, systems, out)
        subgroups(dataset, ds, out)
        if dataset == "ktas":
            nurse_vs_system(ds, out)
    latency(metrics, out)
    low_evidence(metrics, out)
    return out
