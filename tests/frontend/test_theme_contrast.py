"""
Every theme's palette, checked rather than judged by eye.

IPM ships eight themes. A theme is only a set of values for the semantic tokens
in globals.css — but a set of values can be quietly illegible, and "it looked
fine on my monitor" is not a standard. So the palettes are read straight out of
the stylesheet and asserted:

  * body, secondary and muted text clear their contrast floors on that theme's
    OWN surfaces — not on white, and not on the default theme's surfaces
  * a status colour is legible both on the surface and on its own tint, because
    both appear in the product (a red figure, and a red figure inside a red pill)
  * every chart slot separates from the surface it is drawn on
  * adjacent chart slots separate from EACH OTHER perceptually, in CIELAB.
    Contrast ratio is the wrong measure for this: a good categorical palette is
    deliberately close in lightness so no series shouts over its neighbours, and
    a luminance test would fail exactly the palettes that are correct.

A failure here is a real accessibility defect in a product bankers read numbers
off all day, so it fails the build rather than warning.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

CSS = Path(__file__).resolve().parents[2] / "frontend" / "src" / "app" / "globals.css"

#: (foreground token, background token, minimum ratio, what it is)
CHECKS: list[tuple[str, str, float, str]] = [
    ("ipm-text-primary", "ipm-surface", 7.0, "body text"),
    ("ipm-text-primary", "ipm-canvas", 7.0, "body text on the canvas"),
    ("ipm-text-secondary", "ipm-surface", 4.5, "secondary text"),
    ("ipm-text-muted", "ipm-surface", 4.0, "muted text"),
    ("ipm-text-muted", "ipm-surface-sunken", 4.0, "muted text on a sunken panel"),
    ("ipm-accent", "ipm-surface", 4.0, "accent text and icons"),
    ("ipm-accent-contrast", "ipm-accent", 4.5, "a button label on the accent"),
    ("ipm-positive", "ipm-surface", 3.5, "positive"),
    ("ipm-warning", "ipm-surface", 3.5, "warning"),
    ("ipm-negative", "ipm-surface", 3.5, "negative"),
    ("ipm-info", "ipm-surface", 3.5, "info"),
    ("ipm-positive", "ipm-positive-muted", 3.5, "positive on its own tint"),
    ("ipm-warning", "ipm-warning-muted", 3.5, "warning on its own tint"),
    ("ipm-negative", "ipm-negative-muted", 3.5, "negative on its own tint"),
    ("ipm-trace-governed", "ipm-surface", 3.0, "a governed Trace node"),
    ("ipm-trace-interpretive", "ipm-surface", 3.0, "an interpretive Trace node"),
]

#: A chart series must be visible against the surface it is drawn on.
CHART_ON_SURFACE = 2.6
#: And distinguishable from the slot next to it. CIELAB, not contrast ratio.
CHART_SEPARATION = 18.0

EXPECTED_THEMES = {
    "executive-light",
    "midnight",
    "graphite",
    "warm-institutional",
    "alpine",
    "porcelain",
    "oxblood",
    "forest",
}


def _themes() -> dict[str, dict[str, str]]:
    css = CSS.read_text(encoding="utf-8")
    out: dict[str, dict[str, str]] = {}
    for match in re.finditer(r'\[data-theme="([a-z-]+)"\]\s*\{(.*?)\n\}', css, re.S):
        out[match.group(1)] = dict(
            re.findall(r"--(ipm-[a-z0-9-]+):\s*(#[0-9a-fA-F]{6})", match.group(2))
        )
    return out


def _linear(channel: float) -> float:
    return channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4


def _rgb(value: str) -> tuple[float, float, float]:
    return tuple(_linear(int(value[i : i + 2], 16) / 255) for i in (1, 3, 5))  # type: ignore[return-value]


def _luminance(value: str) -> float:
    r, g, b = _rgb(value)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    """WCAG contrast ratio between two hex colours."""
    la, lb = _luminance(a), _luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def _lab(value: str) -> tuple[float, float, float]:
    r, g, b = _rgb(value)
    x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883

    def f(t: float) -> float:
        return t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116

    fx, fy, fz = f(x), f(y), f(z)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def delta_e(a: str, b: str) -> float:
    """Perceptual distance between two colours, in CIELAB."""
    la, aa, ba = _lab(a)
    lb, ab, bb = _lab(b)
    return ((la - lb) ** 2 + (aa - ab) ** 2 + (ba - bb) ** 2) ** 0.5


THEMES = _themes()


def test_every_declared_theme_exists_in_the_stylesheet():
    assert EXPECTED_THEMES <= set(THEMES), (
        f"Missing from globals.css: {sorted(EXPECTED_THEMES - set(THEMES))}"
    )


@pytest.mark.parametrize("theme", sorted(EXPECTED_THEMES))
def test_theme_text_and_status_colours_are_legible(theme: str):
    tokens = THEMES[theme]
    failures = []
    for fg, bg, minimum, what in CHECKS:
        assert fg in tokens, f"{theme} does not define --{fg}"
        assert bg in tokens, f"{theme} does not define --{bg}"
        ratio = contrast(tokens[fg], tokens[bg])
        if ratio < minimum:
            failures.append(f"{what}: {ratio:.2f} < {minimum} ({fg} on {bg})")
    assert not failures, f"{theme}:\n  " + "\n  ".join(failures)


@pytest.mark.parametrize("theme", sorted(EXPECTED_THEMES))
def test_every_chart_slot_reads_on_its_own_surface(theme: str):
    tokens = THEMES[theme]
    failures = []
    for slot in range(1, 9):
        key = f"ipm-chart-{slot}"
        assert key in tokens, f"{theme} does not define --{key}"
        ratio = contrast(tokens[key], tokens["ipm-surface"])
        if ratio < CHART_ON_SURFACE:
            failures.append(f"slot {slot}: {ratio:.2f} < {CHART_ON_SURFACE}")
    assert not failures, f"{theme}:\n  " + "\n  ".join(failures)


@pytest.mark.parametrize("theme", sorted(EXPECTED_THEMES))
def test_adjacent_chart_slots_are_perceptually_separated(theme: str):
    tokens = THEMES[theme]
    failures = []
    for slot in range(1, 8):
        distance = delta_e(tokens[f"ipm-chart-{slot}"], tokens[f"ipm-chart-{slot + 1}"])
        if distance < CHART_SEPARATION:
            failures.append(f"slots {slot}/{slot + 1}: dE {distance:.1f} < {CHART_SEPARATION}")
    assert not failures, f"{theme}:\n  " + "\n  ".join(failures)


def test_the_theme_list_in_typescript_matches_the_stylesheet():
    """A theme in the gallery that has no palette renders as the default one."""
    ts = (CSS.parents[1] / "lib" / "themes.ts").read_text(encoding="utf-8")
    declared = set(re.findall(r'id: "([a-z-]+)"', ts))
    assert declared == EXPECTED_THEMES, (
        f"themes.ts declares {sorted(declared)}, stylesheet has {sorted(EXPECTED_THEMES)}"
    )
