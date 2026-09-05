"""What the results mean together, and the ways that can go wrong.

The findings engine is where a validation product earns its keep and where
it most easily lies. Three failure modes, each with tests below: inventing a
finding the evidence does not support, dropping a breach because no rule
matched it, and reporting one problem as three so the reader counts three.
"""

from __future__ import annotations

import pytest

from backend.scorecard.validation import (
    findings,
    models,
    registry,
    runner,
    states,
)

CHAMPION = "sme_champion"


@pytest.fixture(scope="module")
def champion() -> models.Model:
    return models.get(CHAMPION)


@pytest.fixture(scope="module")
def results(champion: models.Model) -> list[states.Result]:
    out: list[states.Result] = []
    for category in registry.CATEGORIES:
        out.extend(runner.run_category(category, champion))
    return out


@pytest.fixture(scope="module")
def assessed(results: list[states.Result],
             champion: models.Model) -> list[findings.Finding]:
    return findings.assess(results, champion)


def _result(test_id: str, state: str, **kw) -> states.Result:
    """A result built by hand, for the patterns that need a shape."""
    if state in states.MEASURED:
        return states.Result(test_id=test_id, state=state, **kw)
    kw.setdefault("detail", "built for a test")
    return states.Result(test_id=test_id, state=state, **kw)


# ------------------------------------------------------ nothing is invented


def test_a_finding_must_cite_a_result() -> None:
    with pytest.raises(ValueError, match="opinion"):
        findings.Finding(
            finding_id="F-X", title="x", severity=findings.HIGH,
            category=registry.DISCRIMINATION, what="x", why_it_matters="x",
            remediation="x", verify_by="x", evidence=())


def test_a_finding_must_say_what_would_show_it_fixed() -> None:
    with pytest.raises(ValueError, match="complaint"):
        findings.Finding(
            finding_id="F-X", title="x", severity=findings.HIGH,
            category=registry.DISCRIMINATION, what="x", why_it_matters="x",
            remediation="x", verify_by="", evidence=("DISC-AUC",))


def test_a_clean_run_produces_no_findings(champion: models.Model) -> None:
    """The engine must be capable of saying nothing is wrong."""
    clean = [
        states.measured(t.test_id, states.PASS, 1.0, limit=0.5,
                        limit_source="TEST", detail="fine",
                        observations=10_000, events=500)
        for t in registry.TESTS]
    assert findings.assess(clean, champion) == []


def test_every_finding_cites_a_test_that_ran(
        assessed: list[findings.Finding],
        results: list[states.Result]) -> None:
    ran = {r.test_id for r in results}
    for made in assessed:
        assert set(made.evidence) <= ran, (
            f"{made.finding_id} cites {set(made.evidence) - ran}, which did "
            "not run")


def test_every_finding_carries_a_remediation_and_a_verification(
        assessed: list[findings.Finding]) -> None:
    for made in assessed:
        assert made.remediation.strip()
        assert made.verify_by.strip()
        assert made.why_it_matters.strip()


# --------------------------------------------------------- nothing is lost


def test_every_breach_reaches_a_finding(
        assessed: list[findings.Finding],
        results: list[states.Result]) -> None:
    """A FAIL that no pattern matched must still be reported."""
    breached = {r.test_id for r in results if r.state == states.FAIL}
    cited = {t for made in assessed for t in made.evidence}
    assert breached <= cited, (
        f"{breached - cited} breached and reached no finding")


def test_a_pattern_that_does_not_match_leaves_its_singles_standing(
        champion: models.Model) -> None:
    """The ordering that makes 'nothing is lost' true.

    Singles are built first, patterns second, and only the singles a
    matching pattern names are dropped. A pattern that failed its condition
    must not take its evidence with it.
    """
    only = [states.measured(
        "SEG-CALIBRATION", states.FAIL, 2.0, limit=0.0, limit_source="TEST",
        detail="two segments outside", observations=10_000, events=500,
        table=[{"segment": "MICRO"}])]
    made = findings.assess(only, champion)
    # CAL-OE is absent, so the aggregate-conceals pattern cannot match.
    assert [f.finding_id for f in made] == ["F-SEG-CALIBRATION"]


# ------------------------------------------------- nothing is counted twice


def test_gini_and_auc_are_one_finding_not_two(
        assessed: list[findings.Finding]) -> None:
    """They are the same number: Gini is 2·AUC − 1."""
    ids = {f.finding_id for f in assessed}
    assert not ("F-DISC-AUC" in ids and "F-DISC-GINI" in ids)


def test_a_pattern_supersedes_the_singles_it_is_built_from(
        assessed: list[findings.Finding]) -> None:
    ids = {f.finding_id for f in assessed}
    for made in assessed:
        for gone in made.supersedes:
            assert gone not in ids, (
                f"{made.finding_id} supersedes {gone} and both are reported")


# ------------------------------------------------------- severity is earned


def test_severity_comes_from_the_distance_outside_the_limit(
        champion: models.Model) -> None:
    near = states.measured("CAL-OE", states.FAIL, 1.26, limit=1.25,
                           limit_source="TEST", detail="just outside",
                           observations=10_000, events=500)
    far = states.measured("CAL-OE", states.FAIL, 2.50, limit=1.25,
                          limit_source="TEST", detail="far outside",
                          observations=10_000, events=500)
    assert (findings.SEVERITY_RANK[findings._severity(far, champion)]
            < findings.SEVERITY_RANK[findings._severity(near, champion)])


def test_a_thin_sample_cannot_produce_a_critical(
        champion: models.Model) -> None:
    """A breach on forty defaults is a reason to look again, not to act."""
    thin = states.measured("CAL-OE", states.FAIL, 3.0, limit=1.25,
                           limit_source="TEST", detail="far outside",
                           observations=600, events=40)
    assert findings._severity(thin, champion) != findings.CRITICAL


def test_a_missing_column_is_not_promoted_by_materiality(
        champion: models.Model) -> None:
    """A field that is not supplied is the same absence at any tier.

    Materiality raises a breach by one step. Applying it to an UNAVAILABLE
    put a missing version column above findings about whether the model
    works, which is the wrong end of the list.
    """
    absent = states.unavailable("IMPL-VERSION", what="a model version")
    assert findings._severity(absent, champion) == findings.MEDIUM


# ------------------------------------------ the patterns say something new


def test_the_aggregate_conceals_the_segment(
        assessed: list[findings.Finding]) -> None:
    made = _by_id(assessed, "F-PATTERN-AGGREGATE-CONCEALS-SEGMENT")
    assert made is not None, (
        "the portfolio O/E is inside its limit and a segment is outside it; "
        "that combination is the finding")
    assert set(made.evidence) == {"CAL-OE", "SEG-CALIBRATION"}
    assert "average of segments wrong in opposite directions" in made.what


def test_the_pattern_does_not_fire_when_the_portfolio_also_fails(
        champion: models.Model) -> None:
    """Then the portfolio number is not concealing anything."""
    both = [
        states.measured("CAL-OE", states.FAIL, 1.9, limit=1.25,
                        limit_source="TEST", detail="portfolio outside",
                        observations=10_000, events=500),
        states.measured("SEG-CALIBRATION", states.FAIL, 2.0, limit=0.0,
                        limit_source="TEST", detail="segments outside",
                        observations=10_000, events=500,
                        table=[{"segment": "MICRO"}]),
    ]
    made = findings.assess(both, champion)
    assert _by_id(made, "F-PATTERN-AGGREGATE-CONCEALS-SEGMENT") is None


def test_drift_plus_lost_information_reads_as_a_definition_change(
        assessed: list[findings.Finding]) -> None:
    made = _by_id(assessed, "F-PATTERN-DEFINITION-CHANGE")
    assert made is not None
    assert made.severity == findings.CRITICAL
    assert "definition" in made.remediation.lower()
    assert made.values["variable"]


def test_the_decay_patterns_ignore_variables_that_never_predicted(
        assessed: list[findings.Finding],
        champion: models.Model) -> None:
    """Otherwise they name whichever characteristic is noisiest this month.

    Both IV-reading patterns apply the same floor the runner does. Without
    it, `balance_volatility` — 0.016 at approval, below the floor — was named
    as the model's weakening characteristic ahead of the bureau proxy, which
    is the one that actually decayed.
    """
    spec = champion.approved_spec()
    for made in assessed:
        name = made.values.get("variable")
        if not name or "information_value_retained" not in made.values:
            continue
        approved = spec.variables.get(str(name))
        assert approved is not None
        assert approved.information_value >= runner.IV_FLOOR, (
            f"{made.finding_id} rests on the decay of {name}, which carried "
            f"{approved.information_value:.4f} at approval — below the floor "
            "where a retention ratio means anything")


def test_a_challenger_inside_the_noise_is_an_observation_not_a_finding(
        assessed: list[findings.Finding]) -> None:
    made = _by_id(assessed, "F-PATTERN-CHALLENGER-INSIDE-THE-NOISE")
    assert made is not None
    assert made.severity == findings.OBSERVATION
    assert made.values["difference"] <= made.values[
        "champion_interval_half_width"]


def test_a_failed_replication_outranks_everything(
        champion: models.Model) -> None:
    """If the book was scored by something else, nothing else describes it."""
    broken = [
        states.measured("IMPL-REPLICATE", states.FAIL, 0.4, limit=0.0,
                        limit_source="STRUCTURAL",
                        detail="two in five rows do not reproduce",
                        observations=10_000),
        states.measured("DISC-AUC", states.FAIL, 0.5, limit=0.65,
                        limit_source="TEST", detail="weak",
                        observations=10_000, events=500),
    ]
    made = findings.assess(broken, champion)
    assert made[0].finding_id == "F-PATTERN-NOT-WHAT-WAS-APPROVED"
    assert made[0].severity == findings.CRITICAL


# ------------------------------------------------------------- the shortlist


def test_the_burning_list_is_short_and_not_padded(
        assessed: list[findings.Finding]) -> None:
    burning = findings.burning(assessed)
    assert len(burning) <= 5
    assert all(f.severity in (findings.CRITICAL, findings.HIGH,
                              findings.MEDIUM) for f in burning), (
        "a shortlist padded with observations is a shortlist of nothing")


def test_the_burning_list_leads_with_the_most_severe(
        assessed: list[findings.Finding]) -> None:
    burning = findings.burning(assessed)
    ranks = [f.rank for f in burning]
    assert ranks == sorted(ranks)


def test_a_pattern_outranks_a_single_test_at_the_same_severity() -> None:
    """A reader who stops after three rows should read the complete ones."""
    pattern = findings.Finding(
        finding_id="F-PATTERN-Z", title="z", severity=findings.HIGH,
        category=registry.CALIBRATION, what="z", why_it_matters="z",
        remediation="z", verify_by="z", evidence=("CAL-OE",),
        pattern="z")
    single = findings.Finding(
        finding_id="F-A", title="a", severity=findings.HIGH,
        category=registry.CALIBRATION, what="a", why_it_matters="a",
        remediation="a", verify_by="a", evidence=("CAL-OE",))
    assert findings.rank([single, pattern])[0] is pattern


def test_every_finding_serialises(
        assessed: list[findings.Finding]) -> None:
    import json

    for made in assessed:
        payload = made.to_dict()
        json.dumps(payload, default=str)
        assert payload["severity_meaning"]


def test_the_summary_counts_every_severity(
        assessed: list[findings.Finding]) -> None:
    summary = findings.summary(assessed)
    assert set(summary["by_severity"]) == set(findings.SEVERITIES)
    assert sum(summary["by_severity"].values()) == len(assessed)


def _by_id(made: list[findings.Finding],
           finding_id: str) -> findings.Finding | None:
    for one in made:
        if one.finding_id == finding_id:
            return one
    return None


# ------------------------------------------------- the references resolve


def test_every_reference_a_finding_cites_exists(
        assessed: list[findings.Finding]) -> None:
    """A citation that leads nowhere is worse than no citation.

    The references are derived from the test registry rather than written on
    each finding, so a finding cannot quote an article number the catalogue
    has never heard of. Before that, the patterns carried hand-written
    references — MMS 10.5, 10.6, 10.8 among them — that appeared in no
    registry entry and no requirement, so following one led nowhere.
    """
    from backend.scorecard.validation import regulatory

    for made in assessed:
        for reference in made.cbuae:
            assert reference in regulatory.BY_REFERENCE, (
                f"{made.finding_id} cites {reference}, which is not in the "
                "requirement catalogue")


def test_a_finding_cites_what_its_evidence_cites(
        assessed: list[findings.Finding]) -> None:
    for made in assessed:
        expected: set[str] = set()
        for test_id in made.evidence:
            expected |= set(registry.BY_ID[test_id].cbuae)
        assert set(made.cbuae) == expected
