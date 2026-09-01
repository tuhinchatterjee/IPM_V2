"""
The credit story, section by section. R2 §5.

The instruction the module answers is "do not merely list 17 conditions", and
the way to hold that is to assert the SHAPE of what comes out — every section
present, in order, each with the question it answers — and then to assert that
the hard cases read correctly: a borrower whose signals disagree, a family
tested in full and clean, an external event that reaches a sector but not the
borrower, and a section whose data is simply absent.

The last of those is the one worth most. "There is nothing here" and "this was
not checked" are the two answers that must never look alike, and a story is
exactly the shape of screen where a reader will otherwise read silence as
safety.
"""

from __future__ import annotations

from typing import Any

import pytest

from backend.early_warning import signals as sg
from backend.early_warning import story as st
from backend.early_warning import taxonomy as tx


def observation(**over: Any) -> sg.Observation:
    base: dict[str, Any] = {
        "signal": "x", "family": tx.LIQUIDITY, "label": "A condition",
        "fired": True, "lifecycle": sg.NEW, "severity": tx.CONCERN,
        "means": "Something happened.",
    }
    base.update(over)
    return sg.Observation(**base)


class Fake:
    """A standing built by hand.

    The real one comes out of a snapshot join, and building a borrower whose
    signals disagree in a chosen way is not something the generator can be
    asked for. Every attribute the story reads is here and nothing else is,
    so a story that reached for something undeclared would fail loudly.
    """

    def __init__(self, fired: list[sg.Observation] | None = None,
                 cured: list[sg.Observation] | None = None,
                 untested: list[sg.Observation] | None = None,
                 conflict: list[str] | None = None,
                 sentence: str = "A sentence about this borrower.") -> None:
        self.borrower_id = "TEST-1"
        self.period = "Q2 2026"
        self.fired = fired or []
        self.cured = cured or []
        self.untested = untested or []
        self.conflict = conflict or []
        self.sentence = sentence
        self.verdict = None


def build(**kwargs: Any) -> dict[str, Any]:
    return st.build(Fake(**kwargs), external=False, group=False).to_dict()


def section(story: dict[str, Any], key: str) -> dict[str, Any]:
    return next(s for s in story["sections"] if s["key"] == key)


class TestTheShapeOfTheStory:
    def test_it_is_a_sequence_of_questions_not_a_list_of_conditions(
            self) -> None:
        story = build(fired=[observation()])
        keys = [s["key"] for s in story["sections"]]
        assert keys == [st.WHY_HERE, st.TOP_RISK, st.NEW, st.WORSENING,
                        st.PERSISTENT, st.CURED, st.MITIGATING,
                        st.INVESTIGATE]

    def test_every_section_carries_the_question_it_answers(self) -> None:
        for found in build(fired=[observation()])["sections"]:
            assert found["question"].endswith("?"), found["key"]

    def test_the_external_and_group_sections_are_added_when_asked_for(
            self) -> None:
        whole = st.build(Fake(), external=True, group=True).to_dict()
        keys = [s["key"] for s in whole["sections"]]
        assert st.EXTERNAL in keys
        assert st.GROUP in keys
        # And they sit before the argument-and-action sections, because
        # context is read before a conclusion is argued with.
        assert keys.index(st.EXTERNAL) < keys.index(st.MITIGATING)
        assert keys.index(st.GROUP) < keys.index(st.INVESTIGATE)

    def test_all_eight_families_appear_in_credit_file_order(self) -> None:
        story = build()
        assert [f["family"] for f in story["families"]] == list(
            st.FAMILY_ORDER)

    def test_a_quiet_family_still_appears(self) -> None:
        # A family shown only when it has something to say is a family whose
        # silence the reader cannot interpret.
        story = build(fired=[observation(family=tx.LIQUIDITY)])
        collateral = next(f for f in story["families"]
                          if f["family"] == tx.COLLATERAL)
        assert collateral["quiet"] is True
        assert "every test ran and none was met" in collateral["reading"]


class TestTheRiskThatMattersMost:
    def test_the_severe_one_leads_not_the_first_one(self) -> None:
        story = build(fired=[
            observation(signal="a", severity=tx.WATCH,
                        means="A small thing."),
            observation(signal="b", severity=tx.SEVERE, family=tx.COVENANT,
                        means="A covenant is breached."),
        ])
        top = section(story, st.TOP_RISK)
        assert "covenant is breached" in top["body"][0]

    def test_it_names_the_family_the_position_is_weakest_in(self) -> None:
        story = build(fired=[observation(severity=tx.SEVERE,
                                         family=tx.COVENANT)])
        assert "covenants" in section(story, st.TOP_RISK)["body"][1].lower()

    def test_a_borrower_with_nothing_firing_has_no_top_risk(self) -> None:
        assert section(build(), st.TOP_RISK)["empty"] is True


class TestWhatChanged:
    def test_new_worsening_persistent_and_cured_are_kept_apart(self) -> None:
        story = build(
            fired=[observation(signal="n", lifecycle=sg.NEW),
                   observation(signal="w", lifecycle=sg.WORSENING),
                   observation(signal="p", lifecycle=sg.PERSISTING)],
            cured=[observation(signal="c", fired=False, lifecycle=sg.CURED)])
        assert len(section(story, st.NEW)["evidence"]) == 1
        assert len(section(story, st.WORSENING)["evidence"]) == 1
        assert len(section(story, st.PERSISTENT)["evidence"]) == 1
        assert len(section(story, st.CURED)["evidence"]) == 1

    def test_an_improving_signal_is_persistent_not_cured(self) -> None:
        # It has not gone away. Filing it under "cured" would be the one place
        # this screen could tell a comfortable untruth.
        story = build(fired=[observation(lifecycle=sg.IMPROVING)])
        assert len(section(story, st.PERSISTENT)["evidence"]) == 1
        assert section(story, st.CURED)["empty"] is True


class TestWhatArguesTheOtherWay:
    def test_a_conflict_is_stated_in_sentences_not_as_a_list_of_keys(
            self) -> None:
        # The bug this pins: `conflict` is a list of family keys, and printing
        # it raw put a Python repr on the screen where a reading belongs.
        story = build(fired=[observation()],
                      conflict=[tx.COVENANT, tx.COLLATERAL])
        said = " ".join(section(story, st.MITIGATING)["body"])
        assert "[" not in said and "'" not in said
        assert "covenants" in said and "collateral" in said

    def test_a_family_tested_in_full_and_clean_counts_as_evidence(self) -> None:
        story = build(fired=[observation(family=tx.LIQUIDITY)])
        said = " ".join(section(story, st.MITIGATING)["body"])
        assert "Tested in full and clean" in said
        assert "covenants" in said

    def test_an_improving_signal_argues_the_other_way(self) -> None:
        story = build(fired=[observation(lifecycle=sg.IMPROVING,
                                         label="Utilisation")])
        said = " ".join(section(story, st.MITIGATING)["body"])
        assert "right direction" in said

    def test_it_says_so_plainly_when_nothing_argues_the_other_way(
            self) -> None:
        story = build(fired=[observation(family=f) for f in st.FAMILY_ORDER])
        said = section(story, st.MITIGATING)["body"]
        assert said, "the section is silent, which reads as reassurance"
        assert "Nothing in the governed evidence" in said[0]


class TestWhatToGoAndLookAt:
    def test_the_recommendation_follows_what_actually_fired(self) -> None:
        covenant = " ".join(section(
            build(fired=[observation(family=tx.COVENANT)]),
            st.INVESTIGATE)["body"])
        collateral = " ".join(section(
            build(fired=[observation(family=tx.COLLATERAL)]),
            st.INVESTIGATE)["body"])
        assert "covenant schedule" in covenant
        assert "covenant schedule" not in collateral
        assert "valuation" in collateral

    def test_it_starts_with_the_severe_families(self) -> None:
        story = build(fired=[
            observation(signal="a", family=tx.LIQUIDITY, severity=tx.WATCH),
            observation(signal="b", family=tx.COVENANT, severity=tx.SEVERE)])
        assert section(story, st.INVESTIGATE)["body"][0].startswith(
            "Start with covenants")

    def test_untested_signals_become_a_question_about_the_data(self) -> None:
        story = build(untested=[observation(
            fired=False, unavailable="the field is not carried")])
        said = " ".join(section(story, st.INVESTIGATE)["body"])
        assert "could not be run" in said

    def test_a_clean_borrower_is_told_the_routine_review_is_enough(
            self) -> None:
        assert "routine review" in section(build(), st.INVESTIGATE)["body"][0]


class TestSayingWhenSomethingIsNotAvailable:
    def test_an_absent_dataset_is_stated_rather_than_shown_empty(self,
                                                                 monkeypatch:
                                                                 Any) -> None:
        monkeypatch.setattr(st, "_headlines", dict)
        found = st._external(Fake(), sector="Shipping")
        assert found.unavailable, \
            "an unbuilt domain looks identical to a quiet one"
        assert not found.body

    def test_no_event_for_this_sector_is_stated_rather_than_unavailable(
            self, monkeypatch: Any) -> None:
        # The distinction: the domain IS built and has nothing for this
        # sector, which is a finding rather than a gap.
        monkeypatch.setattr(st, "_headlines", lambda: {
            "E1": {"event_id": "E1", "headline": "Something elsewhere",
                   "sectors_affected": "Utilities",
                   "first_period": "Q1 2026", "last_period": "Q2 2026"}})
        found = st._external(Fake(), sector="Shipping")
        assert not found.unavailable
        assert "No governed external event" in found.body[0]

    def test_a_missing_graph_is_stated_rather_than_shown_as_no_group(
            self, monkeypatch: Any) -> None:
        import backend.corporate.service as corporate

        def boom(*_: Any, **__: Any) -> Any:
            raise RuntimeError("the graph is not built")

        monkeypatch.setattr(corporate, "relationship_network", boom)
        found = st._group(Fake())
        assert found.unavailable
        assert "not available" in found.unavailable


class TestExternalEvidenceIsNotDressedUp:
    @staticmethod
    def _events() -> dict[str, Any]:
        return {"EV-1": {
            "event_id": "EV-1",
            "headline": "SYNTHETIC DEMONSTRATION SCENARIO: something",
            "sectors_affected": "Shipping, Transport & Logistics",
            "first_period": "Q1 2026", "last_period": "Q2 2026",
            "evidence_type": "ANALYTICAL_HYPOTHESIS",
            "scenario_status": "SYNTHETIC DEMONSTRATION SCENARIO"}}

    def test_a_sector_link_says_it_is_a_sector_link(self,
                                                   monkeypatch: Any) -> None:
        monkeypatch.setattr(st, "_headlines", self._events)
        monkeypatch.setattr(
            "backend.intelligence.reader.load", lambda _name: None)
        found = st._external(Fake(), sector="Shipping")
        assert "not attached to this borrower individually" in found.body[0]

    def test_a_hypothesis_is_labelled_as_one(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(st, "_headlines", self._events)
        monkeypatch.setattr(
            "backend.intelligence.reader.load", lambda _name: None)
        found = st._external(Fake(), sector="Shipping")
        assert "analytical hypothesis, not an observed fact" in found.body[0]

    def test_an_event_outside_its_window_does_not_reach_this_quarter(
            self, monkeypatch: Any) -> None:
        stale = {"EV-1": dict(self._events()["EV-1"],
                              first_period="Q1 2024", last_period="Q4 2024")}
        monkeypatch.setattr(st, "_headlines", lambda: stale)
        monkeypatch.setattr(
            "backend.intelligence.reader.load", lambda _name: None)
        found = st._external(Fake(), sector="Shipping")
        assert "No governed external event" in found.body[0]

    def test_an_event_naming_no_sector_reaches_everything(self,
                                                          monkeypatch: Any
                                                          ) -> None:
        # A macro event is economy-wide. Treating an empty sector list as
        # "reaches nothing" would silently drop every one of them.
        macro = {"EV-1": dict(self._events()["EV-1"], sectors_affected="")}
        monkeypatch.setattr(st, "_headlines", lambda: macro)
        monkeypatch.setattr(
            "backend.intelligence.reader.load", lambda _name: None)
        found = st._external(Fake(), sector="Anything At All")
        assert found.evidence


class TestAgainstTheRealBook:
    @pytest.fixture(scope="class")
    @classmethod
    def standing(cls) -> Any:
        try:
            book = sg._book("")
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"the corporate lake is not built: {exc}")
        ranked = book.get("_ranked") or []
        if not ranked:
            pytest.skip("no borrower stands up in this build")
        return ranked[0]

    def test_the_worst_borrower_gets_a_whole_story(self, standing: Any
                                                   ) -> None:
        built = st.build(standing,
                         sector=str(standing.record.get("sector") or "")
                         ).to_dict()
        assert len(built["sections"]) == 10
        assert len(built["families"]) == 8

    def test_no_section_prints_a_python_repr(self, standing: Any) -> None:
        built = st.build(standing, external=False, group=False).to_dict()
        for found in built["sections"]:
            for line in found["body"]:
                assert "[" not in line and "{" not in line, \
                    f"{found['key']} shows a repr: {line[:80]}"

    def test_every_family_reading_is_a_sentence(self, standing: Any) -> None:
        built = st.build(standing, external=False, group=False).to_dict()
        for family in built["families"]:
            assert family["reading"].endswith("."), family["family"]
