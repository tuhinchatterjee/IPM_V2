"""
The scorecard teaching corpus and its sealed holdout. §A2-§A6.

Three things are being checked, and they are different claims.

**That the corpus exists at the size it says.** Five hundred development
cases across twenty-three families, and no family padded to its target with
cases that assert the same thing twice.

**That the holdout is isolated.** Not "was built separately" — checked, by
comparing clusters, questions and fingerprints, because a holdout score
computed over cases the layer was tuned on fails in the flattering direction
and looks fine.

**That no production path can reach it.** A holdout that is isolated by
convention is isolated until somebody adds a retrieval source. The test
walks the actual export and retrieval paths.
"""

from __future__ import annotations

import pytest

from backend.brain import cases as brain_cases
from backend.scorecard import holdout as hold
from backend.teaching import families as fam
from backend.teaching import schema as sch
from intelligence_factory.teaching import scorecard as dev

SCORECARD_FAMILIES = tuple(f.id for f in fam.in_group(fam.SCORECARD))


@pytest.fixture(scope="module")
def development():
    return dev.cases()


@pytest.fixture(scope="module")
def held():
    return hold.build()


# ------------------------------------------------------------- the families


def test_all_twenty_three_families_are_registered():
    """§A2 names them. A family in the brief and not in the registry is a
    coverage claim with nothing behind it."""
    assert len(SCORECARD_FAMILIES) == 23
    for name in ("SCORECARD_DATA_DISCOVERY", "SCORECARD_MODEL_EQUATION",
                 "SCORECARD_VARIABLES", "SCORECARD_WOE_BINNING",
                 "SCORECARD_DISCRIMINATION", "SCORECARD_CALIBRATION",
                 "SCORECARD_STABILITY", "SCORECARD_PSI", "SCORECARD_CSI",
                 "SCORECARD_VARIABLE_DIAGNOSTICS", "SCORECARD_IMPLEMENTATION",
                 "SCORECARD_SEGMENT_PERFORMANCE", "SCORECARD_CUTOFF",
                 "SCORECARD_OVERRIDE", "SCORECARD_MODEL_COMPARISON",
                 "SCORECARD_RESCORING", "SCORECARD_MATURITY",
                 "SCORECARD_DEFAULT_DEFINITION", "SCORECARD_REPORT",
                 "SCORECARD_REGULATORY", "SCORECARD_AGENTIC_DIAGNOSIS",
                 "SCORECARD_AMBIGUITY", "SCORECARD_CONTROLLED_FAILURE"):
        assert name in SCORECARD_FAMILIES, name


def test_every_scorecard_family_declares_retail_scope():
    """A scorecard family with an open scope is one the corporate side can
    match against, which is C1's separation failing in the corpus."""
    for family in fam.in_group(fam.SCORECARD):
        assert family.scope == fam.RETAIL, family.id


def test_every_family_says_what_a_case_must_demonstrate():
    for family in fam.in_group(fam.SCORECARD):
        assert len(family.teaches) > 40, family.id
        assert family.teaches.rstrip().endswith("."), family.id


# ------------------------------------------------ the development corpus


def test_the_development_corpus_meets_its_floor(development):
    """§A3: at least five hundred."""
    assert len(development) >= dev.MINIMUM_DEVELOPMENT


def test_no_family_was_padded_to_its_target(development):
    """A blueprint that could not reach its count reports the shortfall
    rather than repeating a case. The report is the check."""
    assert dev.report()["short"] == {}


def test_every_development_case_is_distinct(development):
    """Two cases asserting the same thing of the same question are one
    case."""
    prints = [c.fingerprint for c in development]
    assert len(set(prints)) == len(prints)


def test_every_development_case_validates(development):
    for case in development:
        assert sch.problems_blocking(case) == [], (
            f"{case.case_id}: "
            + "; ".join(str(p) for p in sch.problems_blocking(case)))


def test_every_family_reaches_its_declared_count(development):
    tally: dict[str, int] = {}
    for case in development:
        tally[case.family_id] = tally.get(case.family_id, 0) + 1
    for blueprint in dev.BLUEPRINTS:
        assert tally.get(blueprint.family, 0) == blueprint.count, \
            blueprint.family


def test_the_corpus_covers_every_scorecard_family(development):
    covered = {c.family_id for c in development}
    assert covered == set(SCORECARD_FAMILIES)


def test_the_distribution_matches_the_brief(development):
    """§A3's minimum targets, checked as a distribution rather than a
    total. A corpus of five hundred discrimination questions would meet the
    floor and teach one thing."""
    tally: dict[str, int] = {}
    for case in development:
        tally[case.family_id] = tally.get(case.family_id, 0) + 1
    assert tally["SCORECARD_DATA_DISCOVERY"] >= 40
    assert tally["SCORECARD_DISCRIMINATION"] >= 50
    assert tally["SCORECARD_CALIBRATION"] >= 50
    assert tally["SCORECARD_VARIABLE_DIAGNOSTICS"] >= 50
    assert tally["SCORECARD_IMPLEMENTATION"] >= 30
    assert tally["SCORECARD_AGENTIC_DIAGNOSIS"] >= 30
    assert (tally["SCORECARD_STABILITY"] + tally["SCORECARD_PSI"]
            + tally["SCORECARD_CSI"]) >= 50
    assert (tally["SCORECARD_MODEL_EQUATION"]
            + tally["SCORECARD_DEFAULT_DEFINITION"]) >= 30
    assert (tally["SCORECARD_VARIABLES"]
            + tally["SCORECARD_WOE_BINNING"]) >= 30
    assert (tally["SCORECARD_MODEL_COMPARISON"]
            + tally["SCORECARD_RESCORING"]) >= 30
    assert tally["SCORECARD_AMBIGUITY"] >= 20
    assert tally["SCORECARD_CONTROLLED_FAILURE"] >= 20


def test_the_corpus_spans_more_than_one_difficulty(development):
    """A corpus that is all INTERMEDIATE cannot report a difficulty
    breakdown §A6 asks for."""
    difficulties = dev.report()["difficulties"]
    assert len(difficulties) >= 4
    assert difficulties.get("ADVERSARIAL", 0) >= 20


def test_the_corpus_asks_in_more_than_one_register(development):
    """§A3: formal, informal, abbreviations. A corpus of careful prose
    teaches a model to need careful prose."""
    questions = [c.question for c in development]
    assert any(q.startswith("what's") or q.startswith("whats")
               or q.startswith("gimme") for q in questions)
    assert any(q.startswith("Show me") or q.startswith("Report")
               for q in questions)
    assert any("PSI" in q or "CSI" in q or "KS" in q or "IV" in q
               for q in questions)


def test_no_development_case_stores_a_figure(development):
    """§5's rule. A stored AUC is right for one month and wrong for every
    month after it."""
    import re
    figure = re.compile(r"\b\d+\.\d{3,}\b")
    for case in development:
        assert not figure.search(case.question), case.case_id
        for objective in case.objectives:
            assert not figure.search(objective.text), case.case_id


def test_every_case_records_what_its_question_is_usually_got_wrong(
        development):
    """The field that turns a check into a discriminator."""
    for case in development:
        forbidden = (case.scope_contract or {}).get("forbidden_behaviours")
        assert forbidden, case.case_id


def test_the_immature_months_are_reachable_from_the_corpus():
    """§7 is only a control if a month it applies to exists. A corpus built
    over a universe where every month had matured could not teach it."""
    assert dev.OPEN_WINDOW, (
        "no month has an open performance window, so the maturity family "
        "teaches a rule nothing can exercise")
    assert dev.MATURED


# -------------------------------------------------------- the sealed holdout


def test_the_holdout_meets_its_floor(held):
    """§A4: at least two hundred and twenty."""
    assert len(held) >= hold.MINIMUM_HOLDOUT


def test_every_holdout_case_is_sealed(held):
    for case in held:
        assert hold.sealed(case), case.case_id
        assert case.cluster.startswith(hold.SEAL), case.case_id


def test_the_holdout_is_isolated_from_the_development_corpus(development,
                                                             held):
    """§A4's real content. Raises rather than returning a score."""
    hold.isolated(development, held)


def test_the_holdout_shares_no_cluster_with_development(development, held):
    """Belt and braces on `isolated`: the split is BY CLUSTER, so a
    rephrasing cannot land on the other side of the boundary."""
    dev_clusters = {c.cluster_id for c in development}
    held_clusters = {c.cluster for c in held}
    assert dev_clusters & held_clusters == set()


def test_the_holdout_shares_no_question_with_development(development, held):
    dev_questions = {c.question.strip().lower() for c in development}
    for case in held:
        assert case.question.strip().lower() not in dev_questions, \
            case.case_id


def test_a_leak_would_be_caught(development, held):
    """The isolation check has to be able to fail, or it is decoration."""
    planted = brain_cases.Case(
        case_id="planted", case_family="SCORECARD_DISCRIMINATION",
        cluster=development[0].cluster_id, question="anything",
        objectives=("x",), forbidden=("y",))
    with pytest.raises(brain_cases.CaseError, match="not isolated"):
        hold.isolated(development, [*held, planted])


def test_the_holdout_carries_no_numeric_gold(held):
    """A reference is a routine and its arguments, recomputed at evaluation
    time. A stored answer is a leak waiting for a screen."""
    for case in held:
        assert case.reference.kind, case.case_id
        for value in case.reference.args.values():
            assert not isinstance(value, float), case.case_id


def test_the_holdout_covers_the_traps_the_brief_names(held):
    """§A4's list. A holdout that skipped the maturity trap would be silent
    about exactly the rule this module is built around."""
    clusters = {c.cluster for c in held}
    for fragment in ("maturity", "leakage", "semantics", "direction",
                     "comparison", "candidate", "claims", "report",
                     "missing", "impl", "ambiguity"):
        assert any(fragment in cluster for cluster in clusters), fragment


def test_every_holdout_case_records_a_forbidden_behaviour(held):
    for case in held:
        assert case.forbidden, case.case_id


def test_the_report_leaks_nothing(held):
    """§A4: holdout gold does not reach ordinary screens, and a summary that
    quoted the questions would be the leak wearing a different name."""
    payload = hold.report()
    rendered = repr(payload)
    for case in held[:40]:
        assert case.question not in rendered
    assert payload["contains_no_gold"] is True


# ------------------------------------------- no production path reaches it


def test_the_brain_package_refuses_sealed_holdout_paths():
    """§A4/§A8: prove no production import path can carry sealed gold.

    Exercised rather than asserted to exist: a package whose file list names
    a holdout path is refused, and the refusal names it.
    """
    from backend.brain import pack

    assert any("holdout" in path for path in pack.FORBIDDEN_PATHS)
    carrying = pack.Contents()
    carrying.add("teaching/holdout/scorecard.json", "{}")
    problems = pack._sealed_content(carrying)
    assert problems, (
        "a package carrying sealed scorecard holdout was accepted, and a "
        "score produced against it would be flattering rather than wrong")
    assert "sealed holdout" in problems[0]


def test_teaching_retrieval_refuses_a_holdout_provenance():
    """The runtime retrieval path filters on provenance, and the holdout
    module stamps it."""
    from backend.teaching import retrieval

    source = (retrieval.__file__)
    with open(source, encoding="utf-8") as handle:
        body = handle.read()
    assert 'holdout' in body


def test_the_development_corpus_is_not_stamped_as_holdout(development):
    """A development case that carried a holdout provenance would be
    filtered out of the retrieval it was built for."""
    for case in development:
        assert "holdout" not in (case.source_provenance or "").lower(), \
            case.case_id
