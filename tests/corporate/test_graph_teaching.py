"""
The relationship-graph teaching corpus and its sealed holdout. B45-B49.

Two things are being tested and they are not the same thing.

The DEVELOPMENT corpus has to be big enough, distinct enough and honest
enough: every family reaches its target from real specification space rather
than from padding, every case declares corporate scope, and not one case
carries a figure that could go stale when the graph is rebuilt next quarter.

The HOLDOUT has to be *unusable* as teaching material. That is a stronger
property than being large, and it is the one that fails silently: a holdout
that overlaps the development set still produces a score, and the score is
flattering. So the isolation checks here compare fingerprints, clusters and
question text, and they are the reason the holdout is worth having at all.
"""

from __future__ import annotations

import re

import pytest

from backend.corporate import graphsummary as gs
from backend.corporate import holdout as ho
from backend.teaching import families as fam
from backend.teaching import schema as sc
from intelligence_factory.teaching import corporate_graph as cg

DEVELOPMENT = cg.cases()
HELD = ho.build()

GRAPH_FAMILIES = tuple(f.id for f in fam.FAMILIES if f.group == fam.GRAPH)


class TestFamilies:
    def test_every_graph_family_is_declared(self):
        declared = set(fam.IDS)
        for blueprint in cg.BLUEPRINTS:
            assert blueprint.family in declared, blueprint.family

    def test_every_declared_graph_family_has_cases(self):
        """A family declared and never populated is a coverage report with a
        hole in it that reads as a zero rather than as a gap."""
        built = {case.family_id for case in DEVELOPMENT}
        missing = [f for f in GRAPH_FAMILIES if f not in built]
        assert not missing, f"declared but empty: {missing}"

    def test_every_graph_family_is_corporate_scoped(self):
        for family_id in GRAPH_FAMILIES:
            assert fam.BY_ID[family_id].scope == fam.CORPORATE, family_id

    def test_the_family_version_moved(self):
        """A case validated against an older family list is STALE, not
        wrong, and the version is what tells the two apart."""
        assert fam.FAMILY_VERSION >= "1.2.0"


class TestDevelopmentCorpus:
    def test_the_corpus_meets_its_floor(self):
        assert len(DEVELOPMENT) >= cg.MINIMUM_DEVELOPMENT

    def test_no_family_came_up_short(self):
        """A shortfall is reported rather than padded, so this test failing
        means a family needs more SHAPES - not a higher count."""
        assert cg.report()["short"] == {}

    def test_every_case_validates(self):
        problems = {case.case_id: sc.validate(case) for case in DEVELOPMENT}
        broken = {k: [str(p) for p in v] for k, v in problems.items() if v}
        assert not broken, f"{len(broken)} invalid cases: {list(broken)[:5]}"

    def test_every_case_is_corporate_scoped(self):
        """A case that left the scope open is a case the retail side could
        match against, which is the scope bleed the separation tests exist
        to catch."""
        for case in DEVELOPMENT:
            assert case.portfolio_scope == fam.CORPORATE, case.case_id

    def test_every_case_is_distinct(self):
        fingerprints = [case.fingerprint for case in DEVELOPMENT]
        assert len(fingerprints) == len(set(fingerprints))

    def test_every_case_id_is_unique(self):
        ids = [case.case_id for case in DEVELOPMENT]
        assert len(ids) == len(set(ids))

    def test_every_case_records_what_it_forbids(self):
        """A case with no forbidden behaviour cannot tell a right answer
        from a convincing substitute, which is the entire difficulty of
        this subject area."""
        for case in DEVELOPMENT:
            forbidden = case.scope_contract.get("forbidden_behaviours", [])
            assert forbidden, case.case_id

    def test_the_build_is_deterministic(self):
        again = cg.cases()
        assert [c.case_id for c in again] == [c.case_id for c in DEVELOPMENT]
        assert [c.fingerprint for c in again] == [
            c.fingerprint for c in DEVELOPMENT]


class TestNoStoredFigures:
    """No case carries an answer. Not one.

    An impact, a score, a group size or a utilisation stored as teaching
    truth is correct for one quarter and wrong for every quarter after it,
    and the graph is rebuilt quarterly.
    """

    #: The only percentages a graph case may name: governed parameters, read
    #: from the module so a policy change moves the corpus with it.
    PARAMETERS = {f"{value:g}" for value in (
        gs.OWNERSHIP_GROUP_THRESHOLD_PCT, gs.GROUP_LIMIT_PCT,
        gs.INVESTIGATION_TRIGGER_PCT)}

    def _numbers(self, case) -> list[str]:
        text = " ".join([
            case.question,
            " ".join(o.text for o in case.objectives),
            " ".join(turn.expected_answer_behavior
                     for turn in case.conversation_turns),
        ])
        return re.findall(r"\d+(?:\.\d+)?", text)

    def test_no_case_names_a_figure_that_is_not_a_governed_parameter(self):
        offenders: dict[str, list[str]] = {}
        for case in DEVELOPMENT:
            stray = [n for n in self._numbers(case)
                     if n not in self.PARAMETERS and not self._structural(n)]
            if stray:
                offenders[case.case_id] = stray
        assert not offenders, (
            f"{len(offenders)} cases name a figure: "
            f"{dict(list(offenders.items())[:5])}")

    @staticmethod
    def _structural(number: str) -> bool:
        """Numbers that describe the graph's shape rather than its values.

        A quarter ("2026"), a count of components ("three"), a degree of
        separation. These do not go stale when the data moves, which is the
        property the rule is actually about.
        """
        return number.isdigit() and (len(number) == 4 or int(number) <= 12)

    def test_no_case_carries_a_stored_reference_value(self):
        for case in DEVELOPMENT:
            for key in ("result_contract", "analytical_plan_contract"):
                payload = getattr(case, key, {}) or {}
                for name, value in payload.items():
                    assert not isinstance(value, float), (
                        f"{case.case_id}.{key}.{name} stores a figure")


class TestHoldout:
    def test_the_holdout_meets_its_floor(self):
        assert len(HELD) >= ho.MINIMUM_HOLDOUT

    def test_every_holdout_case_is_sealed(self):
        for case in HELD:
            assert ho.sealed(case), case.case_id
            assert case.cluster.startswith(ho.SEAL), case.case_id

    def test_the_holdout_is_isolated_from_development(self):
        """The check that makes the holdout worth having. It raises."""
        ho.isolated(DEVELOPMENT, HELD)

    def test_a_leaked_case_is_caught_rather_than_scored(self):
        """Prove `isolated` can fail. A separation check that has never
        rejected anything is a separation check nobody has tested."""
        leaked = list(HELD[:1])
        pretend_development = [type("Row", (), {
            "cluster_id": leaked[0].cluster,
            "question": leaked[0].question})()]
        with pytest.raises(Exception) as raised:
            ho.isolated(pretend_development, leaked)
        assert "not isolated" in str(raised.value)

    def test_the_holdout_shapes_are_not_the_development_shapes(self):
        """Fingerprint disjointness is the floor, not the ceiling.

        A holdout built by paraphrasing measures paraphrase robustness and
        calls it generalisation. The clusters carry the shape name, so a
        shape reused on both sides shows up here.
        """
        dev_clusters = {c.cluster_id for c in DEVELOPMENT}
        for case in HELD:
            assert case.cluster not in dev_clusters, case.case_id

    def test_every_holdout_case_records_what_it_forbids(self):
        for case in HELD:
            assert case.forbidden, case.case_id

    def test_the_holdout_carries_no_gold(self):
        """A reference is a routine and its arguments, never a value.

        A stored figure is an answer somebody could leak, and it goes stale
        the quarter after it was written.
        """
        for case in HELD:
            assert case.reference.kind, case.case_id
            assert case.reference.means, case.case_id
            for name, value in case.reference.args.items():
                assert not isinstance(value, (int, float)), (
                    f"{case.case_id}.reference.{name} stores a figure")

    def test_the_report_leaks_nothing(self):
        """Safe to render on a screen: counts and cluster prefixes, no
        question text and no reference values."""
        rendered = str(ho.report())
        for case in HELD[:40]:
            assert case.question not in rendered

    def test_most_of_the_holdout_is_adversarial(self):
        """The development corpus teaches each rule; the holdout checks
        whether the rule survives a question that wants it broken. A holdout
        of comfortable questions measures nothing the development set has
        not already measured."""
        abstains = sum(1 for c in HELD if c.expected_abstention)
        assert abstains > len(HELD) // 2

    def test_every_holdout_case_is_corporate_scoped(self):
        for case in HELD:
            assert case.portfolio_scope == "corporate", case.case_id

    def test_the_holdout_build_is_deterministic(self):
        again = ho.build()
        assert [c.case_id for c in again] == [c.case_id for c in HELD]

    def test_no_holdout_question_reaches_the_teaching_library(self):
        """The path a sealed question could actually take.

        A Brain Pack refuses a file under `holdout/`, which stops the
        obvious leak. The leak it cannot see is a holdout question that got
        into the LIBRARY and was packaged as an ordinary teaching case. The
        library is what the seeder offers, so that is what this checks.
        """
        from scripts.seed_teaching_library import corpus

        offered = {case.question.strip().lower() for case in corpus()}
        leaked = [c.case_id for c in HELD
                  if c.question.strip().lower() in offered]
        assert not leaked, f"sealed questions in the library: {leaked[:5]}"

    def test_the_holdout_is_not_in_the_seeder_corpus_by_id_either(self):
        from scripts.seed_teaching_library import corpus

        offered = {case.case_id for case in corpus()}
        assert not [c.case_id for c in HELD if c.case_id in offered]

    def test_the_holdout_covers_the_substitutions_that_matter(self):
        """Each of these is a way a graph answer looks right and is not.
        A holdout missing one is silent about the failure most likely to
        reach a credit committee."""
        clusters = " ".join(c.cluster for c in HELD)
        for shape in ("community_as_group", "similarity_as_control",
                      "path_as_connectedness", "nrs_as_probability",
                      "debtrank_as_ecl", "centrality_reversed",
                      "utilisation_as_law", "zero_instead"):
            assert shape in clusters, shape
