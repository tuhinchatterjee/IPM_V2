"""
What the certification script asserts, and what its report has to say.

Two failures in the last live run were failures of the harness rather than of
the product.

**A rejected figure was reported as a bare number.** The live run said `25`
and nothing else; the discarded prose was truncated before the token appeared;
working out what 25 meant took rebuilding the packet by hand and cost a whole
round trip. Every rejected figure now travels with the clause it sat in.

**A required stage that never ran could still read as a pass.** The check
carried the detail "stage never reached" whenever `fallback_reason` was empty
— which is the normal state of a stage that worked — so passing cases printed
those words beside `pass: true`. A report nobody can read is a report nobody
checks. Presence is now its own assertion.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from backend.early_warning.conversation import reading as rd
from backend.early_warning.conversation import seam as seam_mod

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / \
    "certify_early_warning_live.py"


def load():
    spec = importlib.util.spec_from_file_location("cert_live", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cert = load()


# ------------------------------------------------- the rejected-token record

def written(**over) -> dict:
    out = {"direct": "", "interpretation": "", "points": [], "drivers": [],
           "follow_ups": [], "caveats": []}
    out.update(over)
    return out


def test_a_rejected_figure_carries_the_clause_it_sat_in():
    got = rd._rejected_context(written(interpretation=(
        "Al Rajhi Logistics 8 is the only one whose anchor also moved, at "
        "-14.0, so the other 25 of the thirty Contracting obligors did not "
        "improve at all.")), ["25"])
    assert len(got) == 1
    record = got[0]
    assert record["token"] == "25"
    assert record["field"] == "interpretation"
    assert "the other" in record["context_before"]
    assert "Contracting obligors" in record["context_after"]
    assert record["source_stage"] == seam_mod.INTERPRETATION


def test_the_record_names_the_unit_the_figure_was_attached_to():
    got = rd._rejected_context(
        written(interpretation="Roughly 25% of the exposure sits here."),
        ["25"])
    assert got[0]["unit_or_suffix"] == "%"


@pytest.mark.parametrize("prose,expected", [
    ("It carries SAR 25m of exposure.", "m"),
    ("A 25-day cure window.", ""),
    ("25 obligors moved.", "obligors"),
    ("The score fell 25 points.", "points"),
    ("A 25 basis point widening.", "basis point"),
])
def test_the_unit_is_read_from_what_follows_the_figure(prose, expected):
    got = rd._rejected_context(written(interpretation=prose), ["25"])
    if not got:
        pytest.skip("this shape does not tokenise as a bare 25")
    assert got[0]["unit_or_suffix"] == expected


def test_the_same_figure_in_two_clauses_is_reported_twice():
    """`the other 25` and `25% of the exposure` are different findings."""
    got = rd._rejected_context(written(
        interpretation="…so the other 25 did not improve.",
        points=["Roughly 25% of the exposure sits in these names."]), ["25"])
    assert [r["field"] for r in got] == ["interpretation", "points[0]"]


def test_it_reports_at_most_two_clauses_for_one_figure():
    got = rd._rejected_context(written(
        interpretation="25 and 25 and 25 again.",
        points=["25 more."]), ["25"])
    assert len(got) == 2


def test_a_figure_that_was_not_rejected_is_not_reported():
    got = rd._rejected_context(
        written(interpretation="The score is 36.2 and the change is 25."),
        ["25"])
    assert [r["token"] for r in got] == ["25"]


def test_a_month_nobody_published_is_reported_with_its_context():
    got = rd._rejected_context(
        written(direct="As at 2027-01 the score is 36.2."), ["2027-01"])
    assert got[0]["token"] == "2027-01"
    assert got[0]["unit_or_suffix"] == "period"


def test_nothing_is_reported_where_nothing_was_rejected():
    assert rd._rejected_context(written(interpretation="All fine."), []) == []


def test_the_record_reads_only_the_answer():
    """No prompt, no system text, no credential — there is nothing else here.

    Pinned as a contract rather than as a comment: the function takes the
    written answer and the list of problems, and has no other argument to
    leak from.
    """
    import inspect

    signature = inspect.signature(rd._rejected_context)
    assert list(signature.parameters) == ["written", "problems"]


def test_the_context_window_is_bounded():
    long = "x" * 500 + " 25 " + "y" * 500
    got = rd._rejected_context(written(interpretation=long), ["25"])
    assert len(got[0]["context_before"]) <= rd._WINDOW
    assert len(got[0]["context_after"]) <= rd._WINDOW


# ----------------------------------------------------- the required stages

def row(stage: str, **over) -> dict:
    out = {"stage": stage, "engine": seam_mod.MODEL, "intended_family": "opus",
           "served_family": "opus", "model": "claude-opus-5", "role": "r",
           "duration_ms": 10, "input_tokens": 100, "output_tokens": 50,
           "output_allowance": 4000, "truncated": False,
           "fallback_reason": "", "schema_errors": []}
    out.update(over)
    return out


class FakeTurn:
    def __init__(self, rows, *, owner="early_warning", executions=2):
        self._rows = rows
        self.answer = {"direct": "An answer.", "scope": "ranking"}
        self.selection = {"selected_functionality": owner}
        self.packet = {"request": {"plan": {"steps": []}}}
        self.events = []
        self.budget = {"executions_attempted": executions,
                       "executions_succeeded": executions,
                       "model_calls_charged": len(rows),
                       "model_calls_succeeded": len(rows),
                       "model_calls_failed": 0, "spent": {}}


def check_for(case, rows):
    turn = FakeTurn(rows)
    monkey = cert._stage_rows
    cert._stage_rows = lambda _t: rows  # type: ignore[assignment]
    try:
        checks, _ = cert._check(case, turn)
    finally:
        cert._stage_rows = monkey  # type: ignore[assignment]
    return checks


ANALYTICAL = {"id": "T", "category": "t", "question": "q",
              "owner": "early_warning", "analytical": True}
HANDOVER = {"id": "W", "category": "w", "question": "q",
            "owner": "early_warning", "analytical": False}


def test_a_missing_required_stage_can_never_pass():
    rows = [row(s) for s in cert.REQUIRED_MODEL_STAGES
            if s != seam_mod.PLAN]
    checks = check_for(ANALYTICAL, rows)
    about = [c for c in checks if c["what"].startswith(seam_mod.PLAN)]
    assert about, "the missing stage produced no checks at all"
    assert all(c["pass"] is False for c in about), about
    assert any(c["detail"] == "stage never reached" for c in about)


def test_no_passing_check_says_a_stage_was_never_reached():
    """The bug that made the report unreadable."""
    checks = check_for(ANALYTICAL,
                       [row(s) for s in cert.REQUIRED_MODEL_STAGES])
    offenders = [c for c in checks
                 if c["pass"] and "never reached" in str(c["detail"])]
    assert offenders == []


def test_every_required_stage_is_asserted_five_ways():
    checks = check_for(ANALYTICAL,
                       [row(s) for s in cert.REQUIRED_MODEL_STAGES])
    for stage in cert.REQUIRED_MODEL_STAGES:
        about = {c["what"] for c in checks if c["what"].startswith(stage)}
        for want in ("ran", "served by a model",
                     "served by the family it asked for",
                     "not truncated", "no fallback"):
            assert f"{stage} {want}" in about, (stage, want)


@pytest.mark.parametrize("broken,what", [
    ({"engine": seam_mod.DETERMINISTIC}, "served by a model"),
    ({"served_family": "sonnet"}, "served by the family it asked for"),
    ({"truncated": True}, "not truncated"),
    ({"fallback_reason": "the reply was empty"}, "no fallback"),
])
def test_each_stage_property_fails_on_its_own(broken, what):
    rows = [row(s, **(broken if s == seam_mod.PLAN else {}))
            for s in cert.REQUIRED_MODEL_STAGES]
    checks = check_for(ANALYTICAL, rows)
    failed = {c["what"] for c in checks if not c["pass"]}
    assert f"{seam_mod.PLAN} {what}" in failed


def test_an_unreadable_model_id_is_not_reported_as_a_wrong_family():
    rows = [row(s, served_family="unknown")
            for s in cert.REQUIRED_MODEL_STAGES]
    checks = check_for(ANALYTICAL, rows)
    assert all(c["pass"] for c in checks
               if "family it asked for" in c["what"])


def test_a_clean_analytical_case_passes_every_stage_check():
    checks = check_for(ANALYTICAL,
                       [row(s) for s in cert.REQUIRED_MODEL_STAGES])
    stage_checks = [c for c in checks
                    if any(c["what"].startswith(s)
                           for s in cert.REQUIRED_MODEL_STAGES)]
    assert stage_checks and all(c["pass"] for c in stage_checks)


# ------------------------------------------------------- the What-If path

def test_a_handover_has_its_own_shorter_required_set():
    assert set(cert.REQUIRED_HANDOVER_STAGES) < set(cert.REQUIRED_MODEL_STAGES)
    assert seam_mod.PLAN not in cert.REQUIRED_HANDOVER_STAGES
    assert seam_mod.FUNCTIONALITY in cert.REQUIRED_HANDOVER_STAGES


def test_a_handover_is_still_checked_rather_than_waved_through():
    rows = [row(s) for s in cert.REQUIRED_HANDOVER_STAGES
            if s != seam_mod.FUNCTIONALITY]
    checks = check_for(HANDOVER, rows)
    about = [c for c in checks if c["what"].startswith(seam_mod.FUNCTIONALITY)]
    assert about and all(c["pass"] is False for c in about)


def test_a_handover_does_not_require_the_analytical_stages():
    checks = check_for(HANDOVER,
                       [row(s) for s in cert.REQUIRED_HANDOVER_STAGES])
    assert not any(c["what"].startswith(seam_mod.PLAN) for c in checks)


def test_the_required_sets_are_chosen_by_the_case():
    assert cert.required_stages({"analytical": True}) \
        == cert.REQUIRED_MODEL_STAGES
    assert cert.required_stages({"analytical": False}) \
        == cert.REQUIRED_HANDOVER_STAGES


# ------------------------------------------------------------- isolation

def test_every_independent_case_runs_in_its_own_conversation():
    rows = cert.case_isolation()
    independent = [r for r in rows if r["independent"]]
    threads = [r["thread_id"] for r in independent]
    assert len(threads) == len(set(threads))
    assert all(r["inherits_context_from"] is None for r in independent)


def test_only_the_declared_follow_up_shares_a_thread():
    rows = {r["id"]: r for r in cert.case_isolation()}
    sharing = [r for r in rows.values() if not r["independent"]]
    assert [r["id"] for r in sharing] == ["LIVE-4"]
    assert rows["LIVE-4"]["thread_id"] == rows["LIVE-3"]["thread_id"]
    assert rows["LIVE-4"]["inherits_context_from"] == "LIVE-3"


def test_the_false_premise_case_is_independent():
    rows = {r["id"]: r for r in cert.case_isolation()}
    assert rows["LIVE-5"]["independent"] is True
    assert rows["LIVE-5"]["thread_id"] == "live-cert-LIVE-5"
    assert rows["LIVE-5"]["thread_id"] != rows["LIVE-3"]["thread_id"]


def test_the_thread_a_case_runs_in_comes_from_its_own_definition():
    for case in cert.CASES:
        expected = f"live-cert-{case.get('follows') or case['id']}"
        assert cert.thread_for(case) == expected


# ---------------------------------------------------- single-case running

def test_a_single_case_can_be_named_two_ways():
    parsed = cert._parser().parse_args(["--case", "LIVE-5"])
    assert parsed.only == "LIVE-5"
    assert cert._parser().parse_args(["--only", "LIVE-5"]).only == "LIVE-5"


def test_a_single_case_run_is_not_a_certification():
    """It applies the identical checks. What it cannot do is say PASSED."""
    source = SCRIPT.read_text()
    assert '"PARTIAL_RUN" if args.only else' in source
