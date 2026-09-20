"""The browser never writes a number.

The numeric contract this product rests on has one sentence: CreditProbe
owns the published figure. Every value a reader sees arrives from the
server twice -- `canonical`, which the arithmetic and the ordering ran on,
and `display`, which is that same value written by the one display policy
that decides money shows no decimals and a share shows two. The frontend
picks the second and lays it out.

A frontend that rounded for itself would be a second opinion about a number
the server had already published, and the first time the two disagreed
nobody could say which was the answer.

That rule has held by convention. It now holds by test, because the chart
layer just grew axes, tick labels and a hover tooltip -- three new places
where a `toFixed(1)` would look like a reasonable thing to write and would
put a figure on screen that no policy had approved.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2] / "frontend" / "src"
CHARTS = ROOT / "components" / "cockpit-v4"

#: The files that draw a published figure. Deliberately the Cockpit V4
#: slice only: `analytics/` charts its own in-browser data and is governed
#: by a different contract.
WATCHED = ("visuals.tsx", "chart-frame.tsx", "chart-geometry.ts",
           "markdown.tsx")

#: Every way a number becomes a string in JavaScript.
FORMATTERS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("toFixed", re.compile(r"\.toFixed\s*\(")),
    ("toPrecision", re.compile(r"\.toPrecision\s*\(")),
    ("toExponential", re.compile(r"\.toExponential\s*\(")),
    ("toLocaleString", re.compile(r"\.toLocaleString\s*\(")),
    ("Intl.NumberFormat", re.compile(r"\bIntl\s*\.\s*NumberFormat\b")),
    # `Math.round(value * 100) / 100` is a rounding policy written by hand.
    ("a hand-rolled rounding", re.compile(r"Math\.round\s*\([^)]*\*\s*\d")),
)

#: Geometry is arithmetic ABOUT positions, and a coordinate is not a
#: published figure -- an SVG needs `x="12.34"`, and `toFixed` on a
#: COORDINATE is correct. A line saying so on its own line is exempt.
ALLOW = "not-a-published-figure:"


def offences(path: Path) -> list[str]:
    out: list[str] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if ALLOW in line:
            continue
        for what, pattern in FORMATTERS:
            if pattern.search(line):
                out.append(f"{path.name}:{number}  {what}: {line.strip()[:70]}")
    return out


@pytest.mark.parametrize("name", WATCHED)
def test_the_chart_layer_formats_nothing(name: str) -> None:
    path = CHARTS / name
    assert path.exists(), f"{name} has moved -- this guard now checks nothing"
    found = offences(path)
    assert not found, (
        "The browser must not write a number. Use the server's own string: "
        "`point.display[column]` for a value, `tick.display` for an axis "
        "label.\n\nIf this really is a COORDINATE rather than a published "
        f"figure, end the line with `// {ALLOW} <why>`.\n\n"
        + "\n".join(found))


def test_the_axis_ticks_are_rendered_from_display_not_value() -> None:
    """The specific mistake this exists to prevent.

    A tick arrives as `{value, display}`. `value` positions it; `display`
    is what the reader reads. Rendering `{tick.value}` would put an
    unrounded double on the axis beside a sentence citing the policy's
    rounding of the same number.
    """
    source = (CHARTS / "chart-frame.tsx").read_text(encoding="utf-8")
    assert "{tick.display}" in source
    assert not re.search(r">\s*\{\s*tick\.value\s*\}", source)


def test_the_tooltip_shows_the_servers_string() -> None:
    source = (CHARTS / "chart-frame.tsx").read_text(encoding="utf-8")
    assert "{value.display}" in source


def test_the_guard_would_catch_what_it_is_for() -> None:
    """A guard nobody has checked against the real shape is a guard that
    passes because its pattern is wrong."""
    samples = [
        "return value.toFixed(2);",
        "const shown = n.toLocaleString();",
        "new Intl.NumberFormat('en').format(x)",
        "Math.round(value * 100) / 100",
    ]
    for sample in samples:
        assert any(pattern.search(sample) for _what, pattern in FORMATTERS), sample


def test_the_guard_passes_correct_code() -> None:
    samples = [
        "{tick.display}",
        "const x = xOf(index, points.length, PLOT_BOX);",
        "Math.round(centre - next / 2)",
        "Math.max(0, Math.min(count - width, from))",
    ]
    for sample in samples:
        assert not any(pattern.search(sample)
                       for _what, pattern in FORMATTERS), sample
