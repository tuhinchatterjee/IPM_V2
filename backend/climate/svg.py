"""
Hand-rolled inline-SVG charts for the downloadable summary report.

Why SVG rather than Plotly: the report is a single self-contained .html file that
has to open on a reviewer's machine with no network, print cleanly to PDF for a
regulator pack, and stay small enough to email. Inlining a charting runtime costs
several megabytes and adds a JavaScript dependency to a document whose whole point
is that it can be checked by hand.

Design rules applied throughout (see the data-viz method):
  * Form follows the data's job — magnitude to length, identity to hue, polarity
    to a diverging ramp, ordered magnitude to a single-hue sequential ramp.
  * Categorical hues are assigned in fixed slot order and never cycled.
  * Thin marks, 4px rounded data-ends anchored to the baseline, 2px surface gaps
    between adjacent fills, recessive grid and axis ink.
  * Identity is never carried by colour alone: every chart ships a legend and the
    report puts the source table directly beneath it.
Colours come from CSS custom properties defined once by the report, so light and
dark mode swap in one place.
"""

import html
import math

# Categorical slots, fixed order (validated: worst adjacent CVD dE 9.1, normal 22.9).
SERIES = ["var(--series-1)", "var(--series-2)", "var(--series-3)", "var(--series-4)"]
SEQUENTIAL = ["#cde2fb", "#b7d3f6", "#9ec5f4", "#86b6ef", "#6da7ec", "#5598e7",
              "#3987e5", "#2a78d6", "#256abf", "#1c5cab", "#184f95", "#104281", "#0d366b"]

BAR_RADIUS = 4.0
GAP = 2.0


def esc(text) -> str:
    return html.escape(str(text), quote=True)


def _fmt(value, places=2, suffix=""):
    if value is None:
        return "n/a"
    return f"{value:,.{places}f}{suffix}"


def _rounded_up_bar(x, y, w, h, r=BAR_RADIUS):
    """Vertical bar anchored to the baseline: rounded at the data end only."""
    if h <= 0:
        return ""
    r = min(r, w / 2.0, h)
    return (f"M{x:.2f},{y + h:.2f} L{x:.2f},{y + r:.2f} Q{x:.2f},{y:.2f} {x + r:.2f},{y:.2f} "
            f"L{x + w - r:.2f},{y:.2f} Q{x + w:.2f},{y:.2f} {x + w:.2f},{y + r:.2f} "
            f"L{x + w:.2f},{y + h:.2f} Z")


def _rounded_right_bar(x, y, w, h, r=BAR_RADIUS):
    """Horizontal bar growing right from the baseline: rounded at the data end."""
    if w <= 0:
        return ""
    r = min(r, h / 2.0, w)
    return (f"M{x:.2f},{y:.2f} L{x + w - r:.2f},{y:.2f} Q{x + w:.2f},{y:.2f} {x + w:.2f},{y + r:.2f} "
            f"L{x + w:.2f},{y + h - r:.2f} Q{x + w:.2f},{y + h:.2f} {x + w - r:.2f},{y + h:.2f} "
            f"L{x:.2f},{y + h:.2f} Z")


def _rounded_left_bar(x, y, w, h, r=BAR_RADIUS):
    """Horizontal bar growing left from the baseline (the negative arm of a tornado)."""
    if w <= 0:
        return ""
    r = min(r, h / 2.0, w)
    return (f"M{x + w:.2f},{y:.2f} L{x + r:.2f},{y:.2f} Q{x:.2f},{y:.2f} {x:.2f},{y + r:.2f} "
            f"L{x:.2f},{y + h - r:.2f} Q{x:.2f},{y + h:.2f} {x + r:.2f},{y + h:.2f} "
            f"L{x + w:.2f},{y + h:.2f} Z")


def _nice_ticks(lo, hi, count=5):
    """Human-readable axis ticks spanning [lo, hi]."""
    if hi <= lo:
        hi = lo + 1.0
    raw = (hi - lo) / max(count, 1)
    magnitude = 10 ** math.floor(math.log10(raw)) if raw > 0 else 1
    step = next((m * magnitude for m in (1, 2, 2.5, 5, 10) if m * magnitude >= raw), 10 * magnitude)
    start = math.floor(lo / step) * step
    ticks, value = [], start
    while value <= hi + step * 0.5:
        ticks.append(round(value, 10))
        value += step
    return ticks


def legend(items) -> str:
    """items = [(label, colour)]. Always present for two or more series."""
    chips = "".join(
        f'<span class="lg-chip"><span class="lg-swatch" style="background:{c}"></span>{esc(label)}</span>'
        for label, c in items
    )
    return f'<div class="lg-row">{chips}</div>'


def small_multiples(panels) -> str:
    """Side-by-side panels, each with its own scale.

    This is the answer to "two measures of very different magnitude": never a
    second y-axis on one chart, which makes the ratio between them a drawing
    accident. Each panel keeps one axis and the shared category order carries the
    comparison. `panels` = [(subtitle, svg_markup)].
    """
    cells = "".join(
        f'<div class="viz-panel"><div class="viz-subtitle">{esc(sub)}</div>{markup}</div>'
        for sub, markup in panels
    )
    return f'<div class="viz-pair">{cells}</div>'


def figure(title, svg, caption="", legend_html="") -> str:
    return (f'<figure class="viz">'
            f'<figcaption class="viz-title">{esc(title)}</figcaption>'
            f'{legend_html}{svg}'
            + (f'<p class="viz-caption">{caption}</p>' if caption else "")
            + "</figure>")


# ----------------------------------------------------------------- grouped bars

def grouped_bars(categories, series, width=880, height=320, value_fmt="{:.2f}",
                 y_label="", pad_left=54, label_every=1, slot=0) -> str:
    """Vertical grouped bars. `series` = [(name, [values...])], in slot order.

    `slot` offsets the first hue, so a series keeps its identity colour when it is
    pulled out into its own panel — colour follows the entity, never its position.

    Magnitude to length, identity to hue. Direct value labels are selective — only
    on the tallest bar in each group — because a number on every mark is noise.
    """
    # Extra head room when an axis title is present, so it never collides with the
    # top gridline label or a direct value label on the tallest bar.
    pad_top, pad_bottom, pad_right = (34 if y_label else 18), 58, 14
    plot_w = width - pad_left - pad_right
    plot_h = height - pad_top - pad_bottom

    values = [v for _, vals in series for v in vals]
    hi = max(values + [0.0])
    lo = min(values + [0.0])
    ticks = _nice_ticks(lo, hi)
    t_lo, t_hi = ticks[0], ticks[-1]
    span = (t_hi - t_lo) or 1.0

    def y_of(v):
        return pad_top + plot_h - (v - t_lo) / span * plot_h

    parts = [f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" '
             f'aria-label="{esc(y_label or "grouped bar chart")}">']

    for t in ticks:
        y = y_of(t)
        parts.append(f'<line class="grid" x1="{pad_left}" y1="{y:.1f}" x2="{width - pad_right}" y2="{y:.1f}"/>')
        parts.append(f'<text class="tick" x="{pad_left - 8}" y="{y + 3.5:.1f}" text-anchor="end">'
                     f'{esc(value_fmt.format(t))}</text>')

    group_w = plot_w / max(len(categories), 1)
    n = max(len(series), 1)
    bar_w = max(3.0, (group_w * 0.72 - GAP * (n - 1)) / n)

    for gi, cat in enumerate(categories):
        gx = pad_left + gi * group_w + (group_w - (bar_w * n + GAP * (n - 1))) / 2.0
        peak = max((vals[gi] for _, vals in series), default=0.0)
        for si, (name, vals) in enumerate(series):
            v = vals[gi]
            x = gx + si * (bar_w + GAP)
            y0, y1 = y_of(max(v, t_lo if t_lo > 0 else 0.0)), y_of(0.0)
            top, h = min(y0, y1), abs(y1 - y0)
            parts.append(f'<path class="mark" d="{_rounded_up_bar(x, top, bar_w, h)}" '
                         f'fill="{SERIES[(slot + si) % len(SERIES)]}"><title>{esc(cat)} · {esc(name)}: '
                         f'{esc(value_fmt.format(v))}</title></path>')
            if v == peak and peak > 0:
                parts.append(f'<text class="mark-label" x="{x + bar_w / 2:.1f}" y="{top - 5:.1f}" '
                             f'text-anchor="middle">{esc(value_fmt.format(v))}</text>')

        if gi % label_every == 0:
            label = cat if len(cat) <= 18 else cat[:17] + "…"
            parts.append(f'<text class="axis-label" x="{pad_left + gi * group_w + group_w / 2:.1f}" '
                         f'y="{height - pad_bottom + 16}" text-anchor="end" '
                         f'transform="rotate(-32 {pad_left + gi * group_w + group_w / 2:.1f} '
                         f'{height - pad_bottom + 16})">{esc(label)}</text>')

    parts.append(f'<line class="axis" x1="{pad_left}" y1="{y_of(0.0):.1f}" '
                 f'x2="{width - pad_right}" y2="{y_of(0.0):.1f}"/>')
    if y_label:
        parts.append(f'<text class="axis-title" x="{pad_left}" y="12">{esc(y_label)}</text>')
    parts.append("</svg>")
    return "".join(parts)


# ----------------------------------------------------------------- stacked bars

def stacked_bars(categories, series, width=880, height=320, value_fmt="{:.3f}",
                 y_label="") -> str:
    """Vertical stacked bars with a 2px surface gap between segments, so adjacent
    fills never touch and the stack stays readable at small sizes."""
    pad_left, pad_top, pad_bottom, pad_right = 58, (34 if y_label else 18), 58, 14
    plot_w = width - pad_left - pad_right
    plot_h = height - pad_top - pad_bottom

    totals = [sum(vals[i] for _, vals in series) for i in range(len(categories))]
    ticks = _nice_ticks(0.0, max(totals + [0.0]))
    t_hi = ticks[-1] or 1.0

    parts = [f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" '
             f'aria-label="{esc(y_label or "stacked bar chart")}">']
    for t in ticks:
        y = pad_top + plot_h - t / t_hi * plot_h
        parts.append(f'<line class="grid" x1="{pad_left}" y1="{y:.1f}" x2="{width - pad_right}" y2="{y:.1f}"/>')
        parts.append(f'<text class="tick" x="{pad_left - 8}" y="{y + 3.5:.1f}" text-anchor="end">'
                     f'{esc(value_fmt.format(t))}</text>')

    slot_w = plot_w / max(len(categories), 1)
    bar_w = min(46.0, slot_w * 0.6)

    for gi, cat in enumerate(categories):
        x = pad_left + gi * slot_w + (slot_w - bar_w) / 2.0
        cursor = 0.0
        for si, (name, vals) in enumerate(series):
            v = vals[gi]
            if v <= 0:
                continue
            h = v / t_hi * plot_h
            y = pad_top + plot_h - (cursor + v) / t_hi * plot_h
            seg_h = max(0.0, h - (GAP if si < len(series) - 1 else 0.0))
            path = (_rounded_up_bar(x, y, bar_w, seg_h) if si == len(series) - 1
                    else f"M{x:.2f},{y:.2f} h{bar_w:.2f} v{seg_h:.2f} h{-bar_w:.2f} Z")
            parts.append(f'<path class="mark" d="{path}" fill="{SERIES[si % len(SERIES)]}">'
                         f'<title>{esc(cat)} · {esc(name)}: {esc(value_fmt.format(v))}</title></path>')
            cursor += v
        parts.append(f'<text class="mark-label" x="{x + bar_w / 2:.1f}" '
                     f'y="{pad_top + plot_h - cursor / t_hi * plot_h - 6:.1f}" text-anchor="middle">'
                     f'{esc(value_fmt.format(cursor))}</text>')
        label = cat if len(cat) <= 18 else cat[:17] + "…"
        cx = pad_left + gi * slot_w + slot_w / 2
        parts.append(f'<text class="axis-label" x="{cx:.1f}" y="{height - pad_bottom + 16}" '
                     f'text-anchor="end" transform="rotate(-32 {cx:.1f} {height - pad_bottom + 16})">'
                     f'{esc(label)}</text>')

    parts.append(f'<line class="axis" x1="{pad_left}" y1="{pad_top + plot_h}" '
                 f'x2="{width - pad_right}" y2="{pad_top + plot_h}"/>')
    if y_label:
        parts.append(f'<text class="axis-title" x="{pad_left}" y="12">{esc(y_label)}</text>')
    parts.append("</svg>")
    return "".join(parts)


# --------------------------------------------------------------------- heat map

def heatmap(row_labels, col_labels, values, width=880, cell_h=30, value_fmt="{:.2f}x",
            low_label="", high_label="") -> str:
    """Sequential single-hue heat map: continuous magnitude, light to dark.

    The value is printed in every cell and the ink flips to white on the darker
    steps, so the reading never depends on discriminating two blues.
    """
    label_w = 250
    pad_top, pad_right, pad_bottom = 26, 14, 26
    grid_w = width - label_w - pad_right
    cell_w = grid_w / max(len(col_labels), 1)
    height = pad_top + cell_h * len(row_labels) + pad_bottom

    flat = [v for row in values for v in row if v is not None]
    lo, hi = (min(flat), max(flat)) if flat else (0.0, 1.0)
    span = (hi - lo) or 1.0

    parts = [f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" '
             f'aria-label="heat map of {esc(len(row_labels))} rows by {esc(len(col_labels))} columns">']

    for ci, col in enumerate(col_labels):
        x = label_w + ci * cell_w + cell_w / 2
        parts.append(f'<text class="tick" x="{x:.1f}" y="{pad_top - 9}" text-anchor="middle">'
                     f'{esc(col)}</text>')

    for ri, row in enumerate(row_labels):
        y = pad_top + ri * cell_h
        label = row if len(row) <= 38 else row[:37] + "…"
        parts.append(f'<text class="axis-label" x="{label_w - 12}" y="{y + cell_h / 2 + 3.5:.1f}" '
                     f'text-anchor="end">{esc(label)}</text>')
        for ci in range(len(col_labels)):
            v = values[ri][ci]
            step = 0 if v is None else int(round((v - lo) / span * (len(SEQUENTIAL) - 1)))
            fill = SEQUENTIAL[max(0, min(step, len(SEQUENTIAL) - 1))]
            x = label_w + ci * cell_w
            ink = "#ffffff" if step >= 7 else "#0b0b0b"
            parts.append(f'<rect class="cell" x="{x + GAP / 2:.1f}" y="{y + GAP / 2:.1f}" '
                         f'width="{cell_w - GAP:.1f}" height="{cell_h - GAP:.1f}" rx="3" fill="{fill}">'
                         f'<title>{esc(row)} · {esc(col_labels[ci])}: '
                         f'{esc(value_fmt.format(v) if v is not None else "n/a")}</title></rect>')
            parts.append(f'<text class="cell-label" x="{x + cell_w / 2:.1f}" '
                         f'y="{y + cell_h / 2 + 3.5:.1f}" text-anchor="middle" fill="{ink}">'
                         f'{esc(value_fmt.format(v) if v is not None else "n/a")}</text>')

    if low_label or high_label:
        parts.append(f'<text class="tick" x="{label_w}" y="{height - 8}">{esc(low_label)}</text>')
        parts.append(f'<text class="tick" x="{width - pad_right}" y="{height - 8}" text-anchor="end">'
                     f'{esc(high_label)}</text>')
    parts.append("</svg>")
    return "".join(parts)


# ------------------------------------------------------------------ line chart

def line_chart(x_labels, series, width=880, height=300, value_fmt="{:,.0f}", y_label="") -> str:
    """Change over an ordered axis. 2px strokes, >=8px markers, direct end labels
    so the legend is a convenience rather than the only route to identity."""
    pad_left, pad_top, pad_bottom, pad_right = 62, (34 if y_label else 18), 40, 118
    plot_w = width - pad_left - pad_right
    plot_h = height - pad_top - pad_bottom

    flat = [v for _, vals in series for v in vals]
    ticks = _nice_ticks(min(flat + [0.0]), max(flat + [0.0]))
    t_lo, t_hi = ticks[0], ticks[-1]
    span = (t_hi - t_lo) or 1.0

    def px(i):
        return pad_left + (i / max(len(x_labels) - 1, 1)) * plot_w

    def py(v):
        return pad_top + plot_h - (v - t_lo) / span * plot_h

    parts = [f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" '
             f'aria-label="{esc(y_label or "line chart")}">']
    for t in ticks:
        y = py(t)
        parts.append(f'<line class="grid" x1="{pad_left}" y1="{y:.1f}" x2="{width - pad_right}" y2="{y:.1f}"/>')
        parts.append(f'<text class="tick" x="{pad_left - 8}" y="{y + 3.5:.1f}" text-anchor="end">'
                     f'{esc(value_fmt.format(t))}</text>')
    for i, label in enumerate(x_labels):
        parts.append(f'<text class="axis-label" x="{px(i):.1f}" y="{height - pad_bottom + 18}" '
                     f'text-anchor="middle">{esc(label)}</text>')

    for si, (name, vals) in enumerate(series):
        colour = SERIES[si % len(SERIES)]
        pts = " ".join(f"{px(i):.1f},{py(v):.1f}" for i, v in enumerate(vals))
        parts.append(f'<polyline class="line" points="{pts}" stroke="{colour}"/>')
        for i, v in enumerate(vals):
            parts.append(f'<circle class="dot" cx="{px(i):.1f}" cy="{py(v):.1f}" r="4.5" '
                         f'fill="{colour}"><title>{esc(name)} · {esc(x_labels[i])}: '
                         f'{esc(value_fmt.format(v))}</title></circle>')

    # Direct end labels, de-collided: where series converge the raw y positions
    # overlap, so nudge them apart top-down while keeping the drawing order.
    ends = sorted(((py(vals[-1]), si, name) for si, (name, vals) in enumerate(series)),
                  key=lambda e: e[0])
    placed, last_y = [], None
    for y, si, name in ends:
        y = y if last_y is None else max(y, last_y + 13.0)
        placed.append((y, si, name))
        last_y = y
    for y, si, name in placed:
        parts.append(f'<text class="series-label" x="{px(len(x_labels) - 1) + 10:.1f}" '
                     f'y="{y + 4:.1f}" fill="{SERIES[si % len(SERIES)]}">{esc(name)}</text>')

    parts.append(f'<line class="axis" x1="{pad_left}" y1="{py(max(t_lo, 0.0)):.1f}" '
                 f'x2="{width - pad_right}" y2="{py(max(t_lo, 0.0)):.1f}"/>')
    if y_label:
        parts.append(f'<text class="axis-title" x="{pad_left}" y="12">{esc(y_label)}</text>')
    parts.append("</svg>")
    return "".join(parts)


# --------------------------------------------------------------------- tornado

def tornado(rows, width=880, row_h=34, value_fmt="{:.3f}x", base=None) -> str:
    """One-way sensitivity ranges around a base case.

    Polarity, so a diverging pair around a neutral baseline: blue for the arm that
    lowers the result, red for the arm that raises it. Rows arrive sorted by span,
    which is what makes it a tornado rather than a bar chart.
    """
    label_w, pad_right, pad_top, pad_bottom = 210, 150, 26, 24
    plot_w = width - label_w - pad_right
    height = pad_top + row_h * len(rows) + pad_bottom

    lows = [r["low"] for r in rows] + ([base] if base is not None else [])
    highs = [r["high"] for r in rows] + ([base] if base is not None else [])
    lo, hi = min(lows), max(highs)
    pad = (hi - lo) * 0.12 or 0.05
    lo, hi = lo - pad, hi + pad
    span = (hi - lo) or 1.0

    def x_of(v):
        return label_w + (v - lo) / span * plot_w

    parts = [f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" '
             f'aria-label="one-way sensitivity tornado">']
    for t in _nice_ticks(lo, hi, 4):
        if lo <= t <= hi:
            parts.append(f'<line class="grid" x1="{x_of(t):.1f}" y1="{pad_top - 6}" '
                         f'x2="{x_of(t):.1f}" y2="{height - pad_bottom}"/>')
            parts.append(f'<text class="tick" x="{x_of(t):.1f}" y="{height - 8}" text-anchor="middle">'
                         f'{esc(value_fmt.format(t))}</text>')

    if base is not None:
        parts.append(f'<line class="baseline-rule" x1="{x_of(base):.1f}" y1="{pad_top - 8}" '
                     f'x2="{x_of(base):.1f}" y2="{height - pad_bottom}"/>')

    for i, r in enumerate(rows):
        y = pad_top + i * row_h + 5
        h = row_h - 14
        centre = base if base is not None else (r["low"] + r["high"]) / 2.0
        parts.append(f'<text class="axis-label" x="{label_w - 12}" y="{y + h / 2 + 3.5:.1f}" '
                     f'text-anchor="end">{esc(r["label"])}</text>')

        left_w = max(0.0, x_of(centre) - x_of(min(r["low"], centre))) - GAP / 2
        if left_w > 0:
            parts.append(f'<path class="mark" d="{_rounded_left_bar(x_of(min(r["low"], centre)), y, left_w, h)}" '
                         f'fill="var(--diverge-low)"><title>{esc(r["label"])} at '
                         f'{esc(r.get("low_label", ""))}: {esc(value_fmt.format(r["low"]))}</title></path>')
        right_w = max(0.0, x_of(max(r["high"], centre)) - x_of(centre)) - GAP / 2
        if right_w > 0:
            parts.append(f'<path class="mark" d="{_rounded_right_bar(x_of(centre) + GAP / 2, y, right_w, h)}" '
                         f'fill="var(--diverge-high)"><title>{esc(r["label"])} at '
                         f'{esc(r.get("high_label", ""))}: {esc(value_fmt.format(r["high"]))}</title></path>')

        parts.append(f'<text class="mark-label" x="{width - pad_right + 10}" y="{y + h / 2 + 3.5:.1f}">'
                     f'{esc(value_fmt.format(r["low"]))} – {esc(value_fmt.format(r["high"]))}</text>')

    parts.append("</svg>")
    return "".join(parts)


# ------------------------------------------------------------------- waterfall

def waterfall(steps, width=880, height=330, value_fmt="{:+.4f}") -> str:
    """Cumulative contribution chart for the probit decomposition.

    `steps` = [(label, delta, kind)] where kind is 'start', 'delta' or 'total'.
    Increases and decreases take the diverging pair; the anchoring bars take the
    neutral. Polarity is the data's job here, so hue carries the sign and the
    signed value label carries it again in text.

    Feed it the shift components, not the probit level they sit on: a baseline
    probit near -2 is two orders of magnitude larger than the shifts, and putting
    both on one scale flattens the very thing the chart exists to show.
    """
    pad_left, pad_top, pad_bottom, pad_right = 62, 26, 76, 14
    plot_w = width - pad_left - pad_right
    plot_h = height - pad_top - pad_bottom

    cumulative, running = [], 0.0
    for label, delta, kind in steps:
        if kind in ("start", "total"):
            base, top = 0.0, (delta if kind == "start" else running)
            if kind == "start":
                running = delta
        else:
            base, top = running, running + delta
            running = top
        cumulative.append((label, base, top, kind, delta))

    values = [v for _, b, t, _, _ in cumulative for v in (b, t)]
    ticks = _nice_ticks(min(values + [0.0]), max(values + [0.0]))
    t_lo, t_hi = ticks[0], ticks[-1]
    span = (t_hi - t_lo) or 1.0

    def y_of(v):
        return pad_top + plot_h - (v - t_lo) / span * plot_h

    parts = [f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" '
             f'aria-label="probit shift waterfall">']
    for t in ticks:
        parts.append(f'<line class="grid" x1="{pad_left}" y1="{y_of(t):.1f}" '
                     f'x2="{width - pad_right}" y2="{y_of(t):.1f}"/>')
        parts.append(f'<text class="tick" x="{pad_left - 8}" y="{y_of(t) + 3.5:.1f}" text-anchor="end">'
                     f'{esc(f"{t:.3f}")}</text>')

    slot_w = plot_w / max(len(cumulative), 1)
    bar_w = min(64.0, slot_w * 0.62)

    prev_top_x = prev_top_y = None
    for i, (label, base, top, kind, delta) in enumerate(cumulative):
        x = pad_left + i * slot_w + (slot_w - bar_w) / 2.0
        y0, y1 = y_of(base), y_of(top)
        y, h = min(y0, y1), max(abs(y1 - y0), 1.5)
        fill = ("var(--neutral-mark)" if kind in ("start", "total")
                else ("var(--diverge-high)" if delta >= 0 else "var(--diverge-low)"))
        parts.append(f'<path class="mark" d="{_rounded_up_bar(x, y, bar_w, h)}" fill="{fill}">'
                     f'<title>{esc(label)}: {esc(value_fmt.format(delta))}</title></path>')
        parts.append(f'<text class="mark-label" x="{x + bar_w / 2:.1f}" y="{y - 6:.1f}" '
                     f'text-anchor="middle">'
                     f'{esc(f"{top:.4f}" if kind in ("start", "total") else value_fmt.format(delta))}</text>')

        # No connector into a total bar: it restarts from the baseline, so a line
        # from the previous running total would read as a drop that never happened.
        if prev_top_x is not None and kind != "total":
            parts.append(f'<line class="connector" x1="{prev_top_x:.1f}" y1="{prev_top_y:.1f}" '
                         f'x2="{x:.1f}" y2="{y_of(base):.1f}"/>')
        prev_top_x, prev_top_y = x + bar_w, y_of(top)

        cx = x + bar_w / 2
        short = label if len(label) <= 22 else label[:21] + "…"
        parts.append(f'<text class="axis-label" x="{cx:.1f}" y="{height - pad_bottom + 16}" '
                     f'text-anchor="end" transform="rotate(-30 {cx:.1f} {height - pad_bottom + 16})">'
                     f'{esc(short)}</text>')

    parts.append(f'<line class="axis" x1="{pad_left}" y1="{y_of(0.0):.1f}" '
                 f'x2="{width - pad_right}" y2="{y_of(0.0):.1f}"/>')
    parts.append("</svg>")
    return "".join(parts)


# ----------------------------------------------------------------- stat tiles

def stat_tile(label, value, sub="", tone="") -> str:
    """A single headline number. Not a chart — when the data's job is one figure,
    a tile beats plotting it."""
    tone_cls = f" tone-{tone}" if tone else ""
    return (f'<div class="tile{tone_cls}"><div class="tile-label">{esc(label)}</div>'
            f'<div class="tile-value">{esc(value)}</div>'
            + (f'<div class="tile-sub">{esc(sub)}</div>' if sub else "") + "</div>")


def table(headers, rows, numeric_from=1, caption="") -> str:
    """The table view every chart in the report is paired with — the relief route
    for the two low-contrast categorical hues, and the audit route for everything."""
    head = "".join(f'<th{" class=num" if i >= numeric_from else ""}>{esc(h)}</th>'
                   for i, h in enumerate(headers))
    body = "".join(
        "<tr>" + "".join(f'<td{" class=num" if i >= numeric_from else ""}>{esc(c)}</td>'
                         for i, c in enumerate(row)) + "</tr>"
        for row in rows
    )
    cap = f"<caption>{esc(caption)}</caption>" if caption else ""
    return f'<table class="data">{cap}<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>'
