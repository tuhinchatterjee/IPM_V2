"""
One monetary figure, written one way, wherever it appears.

The acceptance run found a KPI tile reading `15,470` sitting directly above
prose reading "SAR 15.5bn". Both are the same exposure. A reader who sees
that does not conclude the units differ — they conclude the product cannot
add up, and they are right to, because at that point four different money
conventions were live in Early Warning at once: the application-wide
formatter returning a bare number with no unit, this module's writer, an
Early-Warning formatter on the interface side, and a scattering of inline
f-strings in the report builders that rendered a portfolio total as
"SAR 117991.0 million".

There is now one writer per side. `units.money()` is the backend's — it
sits below `compose` and `escalation` because `compose` imports
`escalation`, so a writer living in the composer was unreachable from the
escalation note and grew a second convention there. `money()` in
frontend/src/lib/early-warning-format.ts is the interface's. The expected
strings below are duplicated in
frontend/src/lib/__tests__/early-warning-format.test.ts on purpose: neither
side can change its convention without failing a test on one side or the
other, which is the only thing that keeps a mirror honest.

Tables are the deliberate exception and are asserted as such. A column of
twenty-five rows each repeating "SAR" is twenty-four repetitions of the one
fact that does not change, so a table names its unit once in the header and
keeps bare numbers in the cells.
"""

from __future__ import annotations

import re

import pytest

from backend.early_warning import compose


def _without_docstrings(source: str) -> str:
    """The module's code with its docstrings and comments removed.

    A check that reads prose fires on the paragraph explaining the rule it
    enforces, which is how a check earns a `# noqa` and stops being read.

    Only DOCSTRINGS, though — a bare string statement, never a string used
    as a value. Blanking every string constant also blanks the literal
    segments of an f-string, which is where the offending money format
    actually lives, and the check silently stopped catching anything. It is
    verified against a deliberately planted offender in
    `test_the_check_catches_a_hand_formatted_figure`.
    """
    import ast

    blank: set[int] = set()
    for node in ast.walk(ast.parse(source)):
        if (isinstance(node, ast.Expr)
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)):
            blank.update(range(node.lineno, (node.end_lineno or node.lineno) + 1))
    lines = []
    for i, line in enumerate(source.splitlines(), start=1):
        if i in blank:
            lines.append("")
        else:
            # A trailing comment is prose too, and one that quotes the
            # convention would fire the same way a docstring does.
            lines.append(re.sub(r"(?<!['\"])#.*$", "", line))
    return "\n".join(lines)

#: Exactly what each figure must render as. Mirrored on the interface side.
AGREED = [
    # A credit officer says "fifteen point five billion", never "fifteen
    # thousand four hundred and seventy million".
    (15470.2, "SAR 15.5bn"),
    (117991.0, "SAR 118.0bn"),
    (2115.37, "SAR 2.1bn"),
    # A single facility stays in millions. 321.8 rounded to 322 has lost the
    # precision the reader is checking the figure for.
    (489.0, "SAR 489.0m"),
    (321.8, "SAR 321.8m"),
    (31.49, "SAR 31.5m"),
    # And a live residual balance is not rounded away to "no exposure".
    (0.04, "SAR 0.04m"),
    (0.0, "SAR 0.0m"),
]


@pytest.mark.parametrize("value,expected", AGREED,
                         ids=[e for _, e in AGREED])
def test_the_backend_writes_the_figure_the_screen_writes(value, expected):
    assert compose.money(value) == expected


def test_the_millions_become_billions_at_exactly_a_thousand():
    assert compose.money(999.9) == "SAR 999.9m"
    assert compose.money(1000.0) == "SAR 1.0bn"


def test_a_negative_amount_keeps_its_sign():
    assert compose.money(-2500.0) == "SAR -2.5bn"


def test_every_reading_writes_money_through_the_one_writer():
    """No sentence in the composer formats a riyal figure by hand.

    This is the check that actually holds the convention: the agreement
    tests above prove the writer is right, and this proves nothing bypasses
    it. An f-string that renders `SAR {x:.1f} million` is exactly how the
    four conventions accumulated in the first place.
    """
    import inspect

    from backend.early_warning import ask, escalation, facts, reports, units

    for module in (compose, reports, escalation, facts, ask, units):
        source = inspect.getsource(module)
        # Code only. A docstring is free to quote the convention it is
        # describing, and reading prose would have this check firing on the
        # sentence that explains why it exists.
        code = "\n".join(
            line for line in _without_docstrings(source).splitlines())
        # A currency literal followed by a formatted number, anywhere other
        # than inside the writer itself or a table's column heading.
        offenders = [
            line.strip()
            for line in code.splitlines()
            if re.search(r"SAR \{", line)
            and "(SAR mn)" not in line
            and "SAR m" not in line
        ]
        # `units` IS the writer, so it is the one module allowed to write a
        # currency literal. Exempting the line SHAPE instead would excuse a
        # hand-formatted figure anywhere, which is the shape the offenders
        # actually took.
        if module is units:
            continue
        assert not offenders, (
            f"{module.__name__} formats money by hand instead of using "
            f"units.money(): {offenders}")


def test_the_escalation_note_writes_money_the_same_way():
    """The note goes into Messages, where it is read beside the screen.

    It could not reach the composer's writer — `compose` imports
    `escalation`, so the dependency runs the wrong way — and grew its own
    `SAR {x:,.0f}m` instead. That is exactly why the writer now sits in
    `units`, below both.
    """
    from backend.early_warning import escalation

    note = escalation.note_for(
        {"customer_name": "Test Obligor", "customer_id": "CORP-1",
         "exposure": 15470.2, "limit": 20000.0, "ews_band": "HIGH",
         "ews_score": 72.0, "drivers": []},
        case_key="EWS-TEST-1")
    text = note if isinstance(note, str) else str(note)
    assert "SAR 15.5bn" in text, text[:300]
    assert "15,470" not in text


def test_a_report_states_its_table_unit_in_the_header():
    """Where a table keeps bare numbers, the header has to say the unit."""
    import inspect

    from backend.early_warning import reports

    source = inspect.getsource(reports)
    # Every money column in every report scope is labelled.
    assert "Exposure (SAR mn)" in source
    # And no money column is left unlabelled.
    bare = re.findall(r'"(Exposure|Limit)"', source)
    assert not bare, f"unlabelled money columns: {bare}"


@pytest.mark.parametrize("scope", ["portfolio", "segment", "all_segments"])
def test_a_generated_report_never_writes_a_raw_million_total(scope):
    """The specific defect: "SAR 117991.0 million" in a report narrative.

    A portfolio total of a hundred and eighteen billion written out in
    millions to one decimal is unreadable, and it contradicts the same
    figure written as "SAR 118.0bn" on the screen the report was generated
    from.
    """
    from backend.early_warning import reports, v2_service as svc

    if not svc.periods():
        pytest.skip("The Early Warning domain is not built.")

    identifier = "Large Corporate" if scope == "segment" else None
    report = (reports.portfolio_report() if scope == "portfolio" else
              reports.segment_report(identifier) if scope == "segment" else
              reports.all_segments_report())

    prose = " ".join(str(s.get("narrative") or "")
                     for s in report.get("sections") or [])
    # Five or more digits before the decimal in a riyal figure means the
    # value was never scaled.
    raw = re.findall(r"SAR [\d,]{6,}(?:\.\d+)?\s*(?:million|m\b)", prose)
    assert not raw, f"{scope} report states an unscaled total: {raw}"
    # And the older long-form unit is gone entirely.
    assert "million of exposure" not in prose


def test_the_check_catches_a_hand_formatted_figure():
    """The guard above has to bite, or it is measuring nothing.

    It did not, briefly: an earlier version blanked every string constant
    rather than only docstrings, which also blanked the literal parts of the
    very f-strings it was looking for. This plants one and asserts it is
    found.
    """
    planted = (
        'def _offender(x):\n'
        '    """A docstring that mentions SAR {x} and must be ignored."""\n'
        '    return f"SAR {x:,.0f} million"\n'
    )
    code = _without_docstrings(planted)
    offenders = [line.strip() for line in code.splitlines()
                 if re.search(r"SAR \{", line)]
    assert len(offenders) == 1, offenders
    assert "million" in offenders[0]

# =====================================================================
# The counts a reader is shown
# =====================================================================


def test_the_domain_description_states_the_real_classifier_count():
    """What the product SAYS the model is has to be what the model is.

    The navigation copy and the data-domain description both claimed 35
    classifiers — the number of an earlier, wrong reading of the workbook,
    and one the brief names as forbidden. The engine has 23. A description
    that contradicts the engine is worse than none: a reader who checks it
    against the methodology screen loses confidence in both.
    """
    from backend.early_warning import classifiers_v2 as clf
    from backend.services import data_domains

    found = [d for d in data_domains.DOMAINS if d.name == "Early Warning"]
    assert found, "the Early Warning domain is not registered"
    described = found[0].description
    assert f"{len(clf.CLASSIFIER_DEFINITIONS)} classifiers" in described, described
    assert "35 classifiers" not in described
