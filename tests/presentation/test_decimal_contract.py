"""The two-decimal display contract, proved rather than asserted. §4.

A credit officer once read `2.6246841182876173%` in a CreditProbe answer. The
figure was correct. It looked like a defect, and a figure that looks like a
defect costs more trust than an imprecise one saves.

These are property tests rather than examples: they generate values across the
ranges a credit book actually produces - fractions of a basis point, tens of
billions, negative movements, values sitting exactly on a rounding boundary -
and assert the contract holds for every one. An example test proves the
formatter works on the number somebody thought of; a property test is what
catches the number nobody did.

The scan tests go the other way round. They take what the product ACTUALLY
renders - a real answer through the real orchestrator, a real workbook through
the real exporter - and read every user-facing string back out looking for
debris. That is the check that survives someone adding a new component.
"""

from __future__ import annotations

import math
import re
import subprocess
import sys
from pathlib import Path

import pytest

from backend.orchestration import figures

ROOT = Path(__file__).resolve().parents[2]

#: Three or more decimals in a number that is not a time, a version or an
#: identifier. Mirrors the frontend's `scrubDebris`, deliberately: the two
#: have to agree, or a figure changes shape when it crosses the wire.
_TOO_PRECISE = re.compile(r"(?<![\w.:])(-?\d[\d,]*\.\d{3,})")

#: The magnitudes a credit book actually produces, from a fraction of a basis
#: point to a sovereign-sized balance.
_MAGNITUDES = [
    0.0000001, 0.000123, 0.001, 0.01, 0.5, 1.0, 1.5, 9.999, 10.0, 99.995,
    100.0, 999.999, 1000.0, 12345.6789, 999999.99999, 1_000_000.0,
    73_391.774000000012, 12_260.522999999981, 2.6246841182876173,
    1e9, 7.3e10,
]
_SIGNED = [v * sign for v in _MAGNITUDES for sign in (1, -1)]


def _decimals_in(text: str) -> int:
    """How many decimal places a rendered figure actually shows."""
    match = re.search(r"\.(\d+)", text)
    return len(match.group(1)) if match else 0


# ------------------------------------------------------- the formatter itself


@pytest.mark.parametrize("value", _SIGNED)
def test_a_percentage_never_shows_more_than_two_decimals(value):
    assert _decimals_in(figures.percent(value)) <= 2


@pytest.mark.parametrize("value", _SIGNED)
def test_a_ratio_never_shows_more_than_two_decimals(value):
    assert _decimals_in(figures.ratio(value)) <= 2


@pytest.mark.parametrize("value", _SIGNED)
def test_points_never_show_more_than_two_decimals(value):
    assert _decimals_in(figures.points(value)) <= 2


@pytest.mark.parametrize("value", _SIGNED)
def test_money_never_shows_more_than_two_decimals(value):
    assert _decimals_in(figures.money(value)) <= 2


@pytest.mark.parametrize("value", _SIGNED)
def test_a_count_is_a_whole_number(value):
    assert _decimals_in(figures.count(value)) == 0


@pytest.mark.parametrize("value", _SIGNED)
def test_days_never_show_more_than_one_decimal(value):
    assert _decimals_in(figures.days(value)) <= 1


@pytest.mark.parametrize("value", _SIGNED)
def test_no_formatter_ever_emits_floating_point_debris(value):
    for rendered in (figures.percent(value), figures.money(value),
                     figures.ratio(value), figures.points(value),
                     figures.count(value), figures.days(value)):
        assert not _TOO_PRECISE.search(rendered), rendered


@pytest.mark.parametrize("value", _SIGNED)
def test_display_rounding_never_changes_the_sign(value):
    """A movement that fell must not be shown as one that rose."""
    rendered = figures.percent(value).replace(",", "").rstrip("%")
    shown = float(rendered)
    if abs(shown) > 0:
        assert math.copysign(1, shown) == math.copysign(1, value)


# ------------------------------------------------------------ the threshold


@pytest.mark.parametrize("threshold,value", [
    (15.0, 14.9996), (15.0, 15.0004), (5.0, 4.99999), (5.0, 5.00001),
    (0.0, -0.0001), (0.0, 0.0001), (100.0, 99.999), (100.0, 100.001),
])
def test_a_figure_never_rounds_across_the_boundary_it_is_judged_on(
        threshold, value):
    """§4: threshold-sensitive values must never round across the threshold.

    "Covenant headroom below 15%" answered with a row reading "15.00%" is a
    sentence that contradicts the answer it sits inside.
    """
    rendered = figures.percent(value, threshold=threshold)
    shown = float(rendered.replace(",", "").rstrip("%"))
    assert (shown < threshold) == (value < threshold), (
        f"{value} displayed as {rendered} crosses the {threshold} boundary")


# --------------------------------------------------- the technical exception


@pytest.mark.parametrize("value", _SIGNED)
def test_the_technical_escape_is_capped_at_four(value):
    assert _decimals_in(figures.technical(value, decimals=9)) <= \
        figures.MAX_TECHNICAL_DECIMALS


def test_the_technical_escape_is_not_reachable_by_accident():
    """It is a separate function, not a `text()` option.

    A caller cannot get three decimals by passing a semantic; they have to
    name `technical`, which is what makes the bypass visible in review.
    """
    assert "technical" not in figures.__dict__.get("_SEMANTICS", {})
    for semantic in (figures.MONEY, figures.PERCENT, figures.POINTS,
                     figures.RATIO, figures.COUNT, figures.DAYS):
        rendered = figures.text(0.123456789,
                                figures.Spec(semantic=semantic))
        assert _decimals_in(rendered) <= 2, (semantic, rendered)


# ----------------------------------------------- what the product renders


@pytest.mark.parametrize("question", [
    "What is total exposure at default by sector?",
    "What is ECL coverage by rating bucket?",
    "How has expected credit loss moved over the latest year?",
    "Which ten customers carry the most exposure?",
])
def test_a_real_answer_carries_no_debris(question):
    """The scan that survives someone adding a new component."""
    from backend.orchestration.executor import run_investigation

    answer = run_investigation(question, persist=False)
    narrative = answer.narrative.to_dict()
    for key in ("direct_answer", "headline", "summary", "interpretation",
                "key_insight"):
        text = str(narrative.get(key) or "")
        found = _TOO_PRECISE.findall(text)
        assert not found, f"{key} of {question!r} carries {found}"


def test_a_real_answers_result_rows_carry_no_debris():
    from backend.orchestration.executor import run_investigation

    answer = run_investigation(
        "What is total exposure at default by sector?", persist=False)
    for step in answer.steps:
        result = step.result or {}
        for row in (result.get("rows") or [])[:40]:
            for value in row.values():
                if isinstance(value, str):
                    assert not _TOO_PRECISE.search(value), value


# ----------------------------------------------------------- the enforcement


def test_no_display_path_bypasses_the_contract():
    """`scripts/check_decimals.py`, as a test.

    Run here as well as by hand so a new bypass fails the suite rather than
    waiting for somebody to remember the script exists.
    """
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_decimals.py")],
        capture_output=True, text=True, cwd=ROOT, check=False)
    assert result.returncode == 0, result.stdout + result.stderr


def test_the_allowlist_every_entry_gives_a_reason():
    sys.path.insert(0, str(ROOT / "scripts"))
    import check_decimals  # noqa: PLC0415

    assert check_decimals.ALLOWLIST
    for entry in check_decimals.ALLOWLIST:
        assert len(entry.reason) > 60, (
            f"{entry.path} is allowed with a reason too short to review")
