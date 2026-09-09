"""
Chart rendering for the committee packs.

Rendered once as PNG bytes and embedded in both the PDF and the Word file, so the
two formats cannot show different pictures. Matplotlib is driven through the
non-interactive Agg backend — there is no display on a server, and importing
pyplot without setting the backend first will try to find one.

Design follows the same rules as the rest of the tool: form follows the data's
job, one hue per series in fixed order, magnitude to length, recessive grid and
axis ink, and a direct value label on every bar so the reading never depends on
measuring against an axis.
"""

import io

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402  — must follow the backend selection

# The app's own palette, so a chart in the pack matches the screen it came from.
NAVY = "#0b2436"
TEAL = "#16b8a6"
BLUE = "#3e7bfa"
AMBER = "#f0973e"
RED = "#e5484d"
GREEN = "#1fa971"
INK = "#16232f"
MUTED = "#6c7a8c"
GRID = "#e3e8ef"

STAGE_COLORS = [GREEN, AMBER, RED]

plt.rcParams.update({
    "font.size": 9,
    "font.family": "sans-serif",
    "axes.edgecolor": GRID,
    "axes.labelcolor": MUTED,
    "xtick.color": MUTED,
    "ytick.color": MUTED,
    "text.color": INK,
    "figure.dpi": 160,
})


def _finish(fig):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return buf.getvalue()


def _bare(ax):
    """Strip the frame down to a single baseline — the chart's job is the marks."""
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.tick_params(length=0)
    ax.grid(axis="y", color=GRID, linewidth=0.7)
    ax.set_axisbelow(True)


def _hbar(labels, values, color, value_fmt, title):
    fig, ax = plt.subplots(figsize=(6.6, 0.42 * len(labels) + 0.9))
    y = range(len(labels))
    ax.barh(list(y), values, color=color, height=0.62, zorder=3)
    ax.set_yticks(list(y))
    ax.set_yticklabels(labels)
    ax.invert_yaxis()
    for side in ("top", "right", "bottom"):
        ax.spines[side].set_visible(False)
    ax.tick_params(length=0)
    ax.grid(axis="x", color=GRID, linewidth=0.7)
    ax.set_axisbelow(True)
    span = max(values) if values else 1
    for i, v in enumerate(values):
        ax.text(v + span * 0.015, i, value_fmt.format(v), va="center", fontsize=8.5,
                color=INK, fontweight="bold")
    ax.set_xlim(0, span * 1.18)
    ax.set_title(title, loc="left", fontsize=10, fontweight="bold", color=INK, pad=10)
    return _finish(fig)


def health_trend(history, title):
    fig, ax = plt.subplots(figsize=(6.6, 2.4))
    labels = [h["label"] for h in history]
    scores = [h["score"] for h in history]
    ax.plot(labels, scores, color=AMBER, linewidth=2.2, marker="o", markersize=4.5, zorder=3)
    ax.fill_between(range(len(scores)), scores, min(scores) - 4, color=AMBER, alpha=0.10, zorder=2)
    # The band edges are what make a score readable — 57 means nothing without them.
    ax.axhline(75, color=GREEN, linewidth=1, linestyle="--", alpha=0.6)
    ax.axhline(50, color=RED, linewidth=1, linestyle="--", alpha=0.6)
    ax.text(len(labels) - 0.5, 75.6, "HEALTHY", fontsize=7, color=GREEN, ha="right")
    ax.text(len(labels) - 0.5, 50.6, "AT RISK", fontsize=7, color=RED, ha="right")
    _bare(ax)
    ax.set_ylim(min(min(scores) - 6, 44), max(max(scores) + 6, 80))
    ax.tick_params(axis="x", rotation=45)
    for lbl in ax.get_xticklabels():
        lbl.set_horizontalalignment("right")
    ax.set_title(title, loc="left", fontsize=10, fontweight="bold", color=INK, pad=10)
    return _finish(fig)


def stage_mix(data, title):
    labels = [d[0] for d in data]
    values = [d[1] for d in data]
    total = sum(values) or 1
    fig, ax = plt.subplots(figsize=(4.6, 2.9))
    wedges, _ = ax.pie(values, colors=STAGE_COLORS, startangle=90, counterclock=False,
                       wedgeprops=dict(width=0.42, edgecolor="white", linewidth=2))
    ax.legend(wedges, [f"{lbl} — {v / total * 100:.1f}%" for lbl, v in zip(labels, values, strict=True)],
              loc="center left", bbox_to_anchor=(1.0, 0.5), frameon=False, fontsize=8.5)
    ax.text(0, 0.06, f"{values[0] / total * 100:.0f}%", ha="center", fontsize=17,
            fontweight="bold", color=INK)
    ax.text(0, -0.22, "performing", ha="center", fontsize=8, color=MUTED)
    ax.set_title(title, loc="left", fontsize=10, fontweight="bold", color=INK, pad=10)
    return _finish(fig)


def ecl_trend(data, title):
    labels = [d[0] for d in data]
    values = [d[1] for d in data]
    fig, ax = plt.subplots(figsize=(6.6, 2.4))
    ax.plot(labels, values, color=RED, linewidth=2.2, marker="o", markersize=4.5, zorder=3)
    ax.fill_between(range(len(values)), values, 0, color=RED, alpha=0.08, zorder=2)
    _bare(ax)
    ax.set_ylim(0, max(values) * 1.25)
    for i, v in enumerate(values):
        ax.text(i, v + max(values) * 0.05, f"{v:,.0f}", ha="center", fontsize=8,
                color=INK, fontweight="bold")
    ax.tick_params(axis="x", rotation=45)
    for lbl in ax.get_xticklabels():
        lbl.set_horizontalalignment("right")
    ax.set_ylabel("US$m")
    ax.set_title(title, loc="left", fontsize=10, fontweight="bold", color=INK, pad=10)
    return _finish(fig)


def sector_exposure(data, title):
    return _hbar([d[0] for d in data], [d[1] / 1000 for d in data], TEAL, "${:,.1f}bn", title)


def stress_ecl(data, title):
    return _hbar([d[0] for d in data], [d[1] for d in data], RED, "${:,.0f}m", title)


def climate_multiples(data, title):
    """PD multiples against an unstressed baseline. 1.00x is where the chart is
    read from, so the axis starts just below it and the baseline is drawn — on a
    zero-based axis every bar looks alike and the spread is invisible."""
    labels = [d[0] for d in data]
    values = [d[1] for d in data]
    fig, ax = plt.subplots(figsize=(6.6, 0.42 * len(labels) + 0.9))
    y = range(len(labels))
    lo, hi = min(values + [1.0]), max(values)
    left = max(0.0, lo - (hi - lo) * 0.25 - 0.05)
    ax.barh(list(y), [v - left for v in values], left=left, color=BLUE, height=0.62, zorder=3)
    ax.axvline(1.0, color=NAVY, linewidth=1.2, linestyle="--", zorder=4)
    ax.set_yticks(list(y))
    ax.set_yticklabels(labels)
    ax.invert_yaxis()
    for side in ("top", "right", "bottom"):
        ax.spines[side].set_visible(False)
    ax.tick_params(length=0)
    ax.grid(axis="x", color=GRID, linewidth=0.7)
    ax.set_axisbelow(True)
    span = hi - left
    for i, v in enumerate(values):
        ax.text(v + span * 0.02, i, f"{v:.2f}x", va="center", fontsize=8.5,
                color=INK, fontweight="bold")
    ax.set_xlim(left, hi + span * 0.18)
    ax.text(1.0, -0.85, "baseline", fontsize=7.5, color=NAVY, ha="center")
    ax.set_title(title, loc="left", fontsize=10, fontweight="bold", color=INK, pad=14)
    return _finish(fig)


def limit_utilisation(data, title):
    """Utilisation against a cap: the 100% line is the point of the chart, so it is
    drawn explicitly and bars past it take the breach colour."""
    labels = [d[0] for d in data]
    values = [d[1] for d in data]
    colors = [RED if v >= 100 else (AMBER if v >= 90 else GREEN) for v in values]
    fig, ax = plt.subplots(figsize=(6.6, 0.42 * len(labels) + 0.9))
    y = range(len(labels))
    ax.barh(list(y), values, color=colors, height=0.62, zorder=3)
    ax.axvline(100, color=NAVY, linewidth=1.2, linestyle="--", zorder=4)
    ax.set_yticks(list(y))
    ax.set_yticklabels(labels)
    ax.invert_yaxis()
    for side in ("top", "right", "bottom"):
        ax.spines[side].set_visible(False)
    ax.tick_params(length=0)
    ax.grid(axis="x", color=GRID, linewidth=0.7)
    ax.set_axisbelow(True)
    span = max(values + [100])
    for i, v in enumerate(values):
        ax.text(v + span * 0.015, i, f"{v:.0f}%", va="center", fontsize=8.5,
                color=INK, fontweight="bold")
    ax.set_xlim(0, span * 1.16)
    ax.text(100, -0.85, "cap", fontsize=7.5, color=NAVY, ha="center")
    ax.set_title(title, loc="left", fontsize=10, fontweight="bold", color=INK, pad=14)
    return _finish(fig)


def pack_bar(data, title):
    """One committee-pack figure broken down by a dimension.

    Generic on purpose. Every other renderer here draws one named report
    shape; a Playbook chart block is configured by a person choosing a metric
    and a dimension, so its shape is not knowable in advance. Takes
    `[{"label": ..., "value": ...}]`, which is what
    `backend.metrics.execution.breakdown` returns.
    """
    rows = [d for d in data if d.get("value") is not None][:20]
    if not rows:
        return None
    return _hbar([str(d.get("label") or "") for d in rows],
                 [float(d["value"]) for d in rows], TEAL, "{:,.2f}", title)


def pack_line(data, title):
    """One committee-pack figure over time."""
    rows = [d for d in data if d.get("value") is not None]
    if len(rows) < 2:
        return None
    fig, ax = plt.subplots(figsize=(6.6, 2.4))
    labels = [str(d.get("label") or "") for d in rows]
    values = [float(d["value"]) for d in rows]
    ax.plot(labels, values, color=TEAL, linewidth=2.2, marker="o",
            markersize=4.5, zorder=3)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.grid(axis="y", color=GRID, linewidth=0.7)
    ax.set_axisbelow(True)
    if len(labels) > 8:
        # A quarterly series over five years is forty labels on a 6.6 inch
        # axis. Thinning them is the difference between a chart and a smear.
        step = max(1, len(labels) // 8)
        ax.set_xticks(range(0, len(labels), step))
        ax.set_xticklabels(labels[::step], rotation=0)
    ax.set_title(title, loc="left", fontsize=10, fontweight="bold", color=INK,
                 pad=10)
    return _finish(fig)


_RENDERERS = {
    "pack_bar": pack_bar,
    "pack_line": pack_line,
    "health_trend": health_trend,
    "stage_mix": stage_mix,
    "ecl_trend": ecl_trend,
    "sector_exposure": sector_exposure,
    "stress_ecl": stress_ecl,
    "climate_multiples": climate_multiples,
    "limit_utilisation": limit_utilisation,
}


def render(spec, context=None):
    """PNG bytes for one chart spec, or None if it cannot be drawn.

    A chart is an illustration; failing to draw one must never stop a committee
    pack from being produced, so every failure degrades to no chart."""
    if not spec:
        return None
    kind = spec.get("kind")
    renderer = _RENDERERS.get(kind)
    if renderer is None:
        return None
    try:
        if kind == "health_trend":
            history = (context or {}).get("health_history") or []
            if len(history) < 2:
                return None
            return renderer(history, spec.get("title", ""))
        data = spec.get("data") or []
        if not data:
            return None
        return renderer(data, spec.get("title", ""))
    except Exception:  # noqa: BLE001
        return None
