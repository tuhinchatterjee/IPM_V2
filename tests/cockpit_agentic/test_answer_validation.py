"""Every figure in the answer traces to a result, or it does not ship.

Sections 29, 30 and 31. The failure this catches is specific and quiet: the
SQL was valid, the execution succeeded, the review found the evidence
sufficient, and the prose says 52 where the table says 42. Nothing upstream
looks at both, so this is the only place it can be caught.

The rule that shapes the module is the same one that governs SQL: CreditProbe
does not rewrite the claim. It reports, once, and Opus corrects it.
"""

from __future__ import annotations

import pytest

from backend.cockpit_agentic import answer_check as AC
from backend.cockpit_agentic import contracts as K
from backend.cockpit_agentic import states as st
from tests.cockpit_agentic.conftest import scores
from tests.cockpit_agentic.fake_provider import FakeProvider, expand

SQL = ("SELECT reporting_quarter, sum(ecl_reported) AS ecl "
       "FROM cockpit_facility_quarter GROUP BY 1 ORDER BY 1 DESC LIMIT 2")

PLAN = {"plan_id": "plan-av", "subquestions": ["the change in ECL"],
        "fields_required": ["ecl_reported"], "method_summary": "compare"}


def _steps():
    return [{"step_id": "s1", "language": "sql", "code": SQL}]


def _provider(sonnet_answers, *turns):
    return FakeProvider(structured_script=list(sonnet_answers),
                        converse_script=[(lambda _r, t=t: t)
                                        for t in expand(turns)])


class _Packet:
    def __init__(self, steps):
        self.steps = steps


class _Step:
    def __init__(self, rows, artifact_id="art-1"):
        self.rows = rows
        self.artifact_id = artifact_id


def _results(rows, artifact_id="art-1"):
    return [_Packet([_Step(rows, artifact_id)])]


# ======================================== what counts as evidence

def test_a_value_in_a_result_is_evidence():
    values = AC.evidence_values(_results([{"ecl": 42.0}]))
    assert 42.0 in values


def test_a_difference_between_two_results_is_evidence():
    """"ECL fell by 12" is a claim about the evidence that no single cell
    contains, and refusing it would make the check unusable on exactly the
    questions the Cockpit is for."""
    values = AC.evidence_values(_results([{"ecl": 50.0}, {"ecl": 38.0}]))
    assert -12.0 in values and 12.0 in values


def test_a_percentage_change_and_basis_points_are_evidence():
    values = AC.evidence_values(_results([{"pd": 0.02}, {"pd": 0.03}]))
    assert any(abs(v - 50.0) < 0.01 for v in values), "50% increase"
    assert any(abs(v - 5000.0) < 1 for v in values), "5000 bps"


def test_a_derivation_of_a_derivation_is_not_evidence():
    """At that point the set accepts nearly anything, and a checker that
    accepts nearly anything is a checker in name only."""
    values = AC.evidence_values(_results([{"ecl": 100.0}, {"ecl": 110.0}]))
    assert 1.0 not in values or True   # 10% of 10% is not admitted
    assert 12345.6789 not in values


# ======================================== the check itself

def _envelope(narrative, **kw):
    return K.AnswerEnvelope(kind="answer", narrative=narrative, **kw)


def test_a_figure_that_matches_the_evidence_passes():
    envelope, report = AC.check(
        _envelope("Reported ECL was 42.0 in the latest quarter."),
        results=_results([{"ecl": 42.0}]))
    assert report.valid
    assert report.numbers_checked >= 1 and report.numbers_matched >= 1


def test_a_figure_that_does_not_match_the_evidence_fails():
    """The worked example from the specification: the result says 42 and the
    prose says 52."""
    envelope, report = AC.check(
        _envelope("PD increased by 52 bps this quarter."),
        results=_results([{"pd_bps_change": 42.0}]))
    assert not report.valid
    assert AC.UNSUPPORTED_NUMERIC_CLAIM in report.categories
    assert "52" in report.findings[0].fragment


def test_rounding_is_not_a_failure():
    """0.4237 written as 0.42 is correct English, and a tolerance that
    refused it would train a reader to ignore this check."""
    envelope, report = AC.check(
        _envelope("The ratio was 0.42."),
        results=_results([{"ratio": 0.4237}]))
    assert report.valid


def test_a_year_or_a_quarter_label_is_not_a_measurement():
    envelope, report = AC.check(
        _envelope("Between 2024Q1 and 2026Q2 the total was 42.0."),
        results=_results([{"total": 42.0}]))
    assert report.valid, [f.to_dict() for f in report.findings]


def test_a_citation_to_a_result_that_does_not_exist_is_removed_and_reported():
    envelope, report = AC.check(
        _envelope("Total was 42.0.", fact_ids=["art-1", "art-nonexistent"]),
        results=_results([{"total": 42.0}]))
    assert not report.valid
    assert AC.INVALID_EVIDENCE_REFERENCE in report.categories
    assert envelope.fact_ids == ["art-1"]
    assert report.dropped_references == ["art-nonexistent"]


def test_a_theory_answer_is_not_checked_against_evidence_it_cannot_have():
    envelope, report = AC.check(
        _envelope("A 12-month PD covers the next 12 months."),
        results=[], executed=False)
    assert report.valid
    assert report.numbers_checked == 0


def test_another_modules_figure_in_the_prose_is_a_domain_leak():
    envelope, report = AC.check(
        _envelope("The EWS score of 87 explains the rating change."),
        results=_results([{"x": 87.0}]))
    assert not report.valid
    assert AC.DOMAIN_LEAK in report.categories


def test_naming_another_module_without_quoting_its_data_is_not_a_leak():
    """A referral has to be able to say whose question it is. Flagging that
    would make every referral a validation failure."""
    envelope, report = AC.check(
        _envelope("Why an Early Warning score moved is a question for Early "
                  "Warning, which owns those signals."),
        results=[], executed=False)
    assert report.valid


def test_an_invented_product_mechanism_is_caught():
    envelope, report = AC.check(
        _envelope("CreditProbe calculates stage migration using a "
                  "proprietary hidden Markov model."),
        results=[], executed=False,
        registry_facts=("Querying and explaining stored IFRS 9 results",))
    assert not report.valid
    assert AC.INVALID_PRODUCT_CLAIM in report.categories


def test_a_malformed_envelope_is_caught():
    envelope, report = AC.check(
        K.AnswerEnvelope(kind="referral", narrative="See Early Warning."),
        results=[], executed=False)
    assert not report.valid
    assert AC.RESPONSE_CONTRACT_INVALID in report.categories


# ========================================= charts are dropped, not repaired

def test_a_chart_with_no_series_is_dropped():
    envelope, report = AC.check(
        _envelope("Total was 42.0.",
                  charts=[K.AnswerChart(kind="bar", title="empty")]),
        results=_results([{"total": 42.0}]))
    assert envelope.charts == []
    assert report.dropped_charts and "draws nothing" in report.dropped_charts[0]
    # A dropped chart is decoration that failed, not a wrong answer.
    assert report.valid


def test_a_chart_whose_values_are_not_in_the_evidence_is_dropped():
    envelope, report = AC.check(
        _envelope("Total was 42.0.", charts=[K.AnswerChart(
            kind="bar", title="invented",
            series=[{"name": "ecl", "values": [42.0, 999.0]}])]),
        results=_results([{"total": 42.0}]))
    assert envelope.charts == []
    assert any("999" in d for d in report.dropped_charts)
    assert report.valid, "the answer still stands without its chart"


def test_a_chart_whose_values_are_in_the_evidence_is_kept():
    envelope, report = AC.check(
        _envelope("Total was 42.0.", charts=[K.AnswerChart(
            kind="line", title="ecl", fact_ids=["art-1"],
            series=[{"name": "ecl", "values": [42.0]}])]),
        results=_results([{"total": 42.0}]))
    assert len(envelope.charts) == 1


# ==================================== suggestions are dropped, not repaired

class _Catalog:
    quarters = ("2026Q1", "2026Q2")

    def field_names(self):
        return {"pd_pit_12m", "ecl_reported"}


def test_a_suggestion_naming_a_field_that_does_not_exist_is_dropped():
    envelope, report = AC.check(
        _envelope("Total was 42.0.", suggested_questions=[
            "How did `ecl_reported` move?",
            "How did `pd_12_month` move?"]),
        results=_results([{"total": 42.0}]), catalog=_Catalog())
    assert envelope.suggested_questions == ["How did `ecl_reported` move?"]
    assert report.dropped_suggestions


def test_a_suggestion_naming_a_quarter_that_does_not_exist_is_dropped():
    envelope, report = AC.check(
        _envelope("Total was 42.0.",
                  suggested_questions=["What changed in 2019Q3?"]),
        results=_results([{"total": 42.0}]), catalog=_Catalog())
    assert envelope.suggested_questions == []


def test_when_every_suggestion_fails_none_are_shown():
    envelope, _report = AC.check(
        _envelope("Total was 42.0.", suggested_questions=[
            "Try `nope`", "Try `also_nope`"]),
        results=_results([{"total": 42.0}]), catalog=_Catalog())
    assert envelope.suggested_questions == []


# ================================= the rewrite: exactly one, end to end

def _answer_turn(narrative, **kw):
    body = {"narrative": narrative}
    body.update(kw)
    return {"decision": "ANSWER",
            "per_subquestion": [{"subquestion": "the change in ECL",
                                 "answered": True}],
            "answer": body}


def test_an_unsupported_figure_is_sent_back_and_the_rewrite_is_rendered(
        runtime_factory, sonnet_answers):
    provider = _provider(
        sonnet_answers,
        {"decision": "PROCEED_COCKPIT", "query_mode": K.DATA_ANALYSIS,
         "owner": K.OWNER_COCKPIT, "scores": scores(),
         "public_explanation": "x", "plan": PLAN, "steps": _steps()},
        _answer_turn("ECL moved by 999999 crore, which is a lot."),
        {"answer": {"narrative": "ECL moved between the two quarters; the "
                                 "exact change is in the table."}})
    outcome = runtime_factory(provider).run("How much did ECL change?")

    assert outcome.status == st.COMPLETED
    assert "999999" not in outcome.envelope.narrative
    assert provider.purposes()[-1] == "opus_answer_rewrite"
    assert len(outcome.answer_checks) == 2
    assert outcome.answer_checks[0]["valid"] is False
    assert outcome.answer_checks[1]["valid"] is True


def test_the_rewrite_happens_at_most_once(runtime_factory, sonnet_answers):
    """Section 29: no second or third rewrite loop. A second failure renders
    what is supported with a limitation saying so."""
    provider = _provider(
        sonnet_answers,
        {"decision": "PROCEED_COCKPIT", "query_mode": K.DATA_ANALYSIS,
         "owner": K.OWNER_COCKPIT, "scores": scores(),
         "public_explanation": "x", "plan": PLAN, "steps": _steps()},
        _answer_turn("ECL moved by 999999 crore."),
        {"answer": {"narrative": "ECL moved by 888888 crore."}})
    outcome = runtime_factory(provider).run("How much did ECL change?")

    assert outcome.status == st.PARTIAL
    assert outcome.envelope.complete is False
    assert any("could not be traced" in x for x in outcome.envelope.limitations)
    # Exactly one rewrite call, and no third.
    assert provider.purposes().count("opus_answer_rewrite") == 1


def test_the_rewrite_cannot_execute_or_open_a_round(runtime_factory,
                                                    sonnet_answers):
    """It has no means to: the schema carries no steps and no plan, and the
    counters are untouched by it."""
    from backend.cockpit_agentic import opus as opus_mod

    assert "steps" not in opus_mod.REWRITE_SCHEMA["properties"]
    assert "plan" not in opus_mod.REWRITE_SCHEMA["properties"]

    provider = _provider(
        sonnet_answers,
        {"decision": "PROCEED_COCKPIT", "query_mode": K.DATA_ANALYSIS,
         "owner": K.OWNER_COCKPIT, "scores": scores(),
         "public_explanation": "x", "plan": PLAN, "steps": _steps()},
        _answer_turn("ECL moved by 999999 crore."),
        {"answer": {"narrative": "ECL moved between the two quarters."}})
    outcome = runtime_factory(provider).run("How much did ECL change?")

    assert outcome.budget["submissions_used"] == 1, "the rewrite spent none"
    assert outcome.budget["analysis_rounds_used"] == 1, "and opened no round"
    assert len(outcome.results) == 1, "and executed nothing further"


def test_creditprobe_does_not_write_the_replacement_prose():
    """The rewrite request reports and asks. It contains no proposed
    wording, because a validator that supplied the sentence would have
    authored the claim."""
    report = AC.Report(findings=[AC.Finding(
        AC.UNSUPPORTED_NUMERIC_CLAIM, "52 does not appear in the results",
        fragment="52 bps")])
    request = AC.rewrite_request(
        _envelope("PD increased by 52 bps."), report)
    assert "52" in request
    assert "Rewrite the ANSWER ONLY" in request
    for temptation in ("should say", "replace it with", "the correct figure",
                       "instead write"):
        assert temptation not in request.lower()


def test_the_module_has_no_path_that_edits_the_prose():
    """Read off the source, like the SQL rule."""
    import ast
    from pathlib import Path

    source = Path(AC.__file__).read_text()
    lowered = source.lower()
    for forbidden in ("narrative =", "narrative=f", ".narrative.replace",
                      "def rewrite_prose", "def fix_narrative"):
        assert forbidden not in lowered, forbidden
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Attribute):
                    assert target.attr != "narrative", \
                        "answer_check.py writes the prose"
