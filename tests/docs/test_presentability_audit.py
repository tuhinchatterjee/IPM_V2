"""The client-presentability audit's own contract. §5.

The audit runs real questions through the real orchestrator, so it is slow
and it is the thing that would quietly stop being run. These tests keep its
REASONING honest without re-running it: that the probe set still covers every
answer type §5 names, that the shape rules do not let one shape's obligations
be applied to another, and that a criterion nobody could establish is reported
as unmeasured rather than as a pass.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import presentability_audit as pa  # noqa: E402

REPORT = ROOT / "docs" / "CLIENT_PRESENTABILITY_AUDIT.md"
DATA = ROOT / "docs" / "client_presentability.json"


@pytest.fixture(scope="module")
def recorded():
    if not DATA.exists():
        pytest.skip("run `python scripts/presentability_audit.py --write`")
    return json.loads(DATA.read_text(encoding="utf-8"))


def test_the_probe_set_covers_every_answer_type_the_brief_names():
    kinds = {probe.kind for probe in pa.PROBES}
    assert {"metadata", "analysis", "investigation", "compound",
            "clarification", "unsupported"} <= kinds


def test_the_probe_set_includes_the_known_complex_questions():
    """§5: "Include the known complex questions and broad investigations."."""
    questions = " ".join(p.question.lower() for p in pa.PROBES)
    assert "investigate contracting" in questions
    assert "covenant headroom below 15%" in questions
    assert "four quarters ago" in questions


def test_every_probe_that_should_be_refused_says_why():
    for probe in pa.PROBES:
        if probe.expect != "answer":
            assert probe.note, (
                f"{probe.key} expects a refusal and does not say why, so "
                "nobody can tell a correct refusal from a defect")


def test_a_criterion_that_cannot_be_established_is_not_a_pass(recorded):
    for row in recorded:
        for criterion, verdict in row["checks"].items():
            assert verdict in (pa.PASS, pa.FAIL, pa.NOT_APPLICABLE,
                               pa.NOT_MEASURED), (criterion, verdict)


def test_the_recorded_run_is_clean(recorded):
    failures = [(r["key"], r["checks"]) for r in recorded
                if r["verdict"] == pa.FAIL]
    assert failures == [], failures


def test_every_answer_type_was_probed(recorded):
    assert len(recorded) == len(pa.PROBES)
    assert {r["key"] for r in recorded} == {p.key for p in pa.PROBES}


def test_a_metadata_answer_is_not_asked_for_a_scope(recorded):
    """The shape rules exist because applying one shape's obligations to
    another reports correct behaviour as a defect. That is not a
    hypothetical - it is what the first version of this audit did."""
    for row in recorded:
        if row["detail"].get("shape") == "metadata":
            assert row["checks"]["correct_population_and_scope"] == \
                pa.NOT_APPLICABLE


def test_an_unsupported_answer_is_not_asked_for_follow_ups(recorded):
    """Offering an adjacent question after a refusal invites the reader to
    accept an answer to a different question."""
    for row in recorded:
        if row["key"] == "unsupported":
            assert row["checks"]["contextual_next_questions"] == \
                pa.NOT_APPLICABLE


def test_a_metadata_answer_names_a_governed_dataset(recorded):
    for row in recorded:
        if row["detail"].get("shape") == "metadata":
            assert row["checks"]["correct_data_and_relationships"] == pa.PASS
            assert "names" in row["detail"]["correct_data_and_relationships"]


def test_no_answer_carried_a_causal_claim(recorded):
    for row in recorded:
        assert row["checks"]["no_unsupported_causal_claim"] == pa.PASS, (
            row["key"], row["detail"].get("no_unsupported_causal_claim"))


def test_no_answer_carried_decimal_debris(recorded):
    for row in recorded:
        assert row["checks"]["max_two_decimals"] == pa.PASS, (
            row["key"], row["detail"].get("max_two_decimals"))


def test_the_report_exists_and_states_what_it_cannot_measure():
    assert REPORT.exists()
    body = REPORT.read_text(encoding="utf-8")
    assert "NOT MEASURED" in body
    assert "blind spots" in body
