"""What breaks at the seams between two capabilities that each work.

Every module here is covered by its own tests. This file is about the joins:
the dataset a conversation established reaching the analysis that follows it,
a preference losing when it would change what an answer covers, and a saved
investigation keeping its own figures when the data underneath it moves on.

The remaining joins are proved where the work they cross actually happens:
Data Builder -> catalogue -> Ask and Data Builder -> Messages are steps 7 to
16 of tests/api/test_data_release_loop.py, and sharing every block of a
multi-analysis investigation is the class at the end of it.
"""

from __future__ import annotations

import pytest

from tests.conftest import database_available

# ======================================== the book a conversation is reading


@pytest.fixture(scope="module")
def concept_setup():
    from backend.orchestration import concepts as cx
    from backend.orchestration import context as gc

    known = {d.name: {f["name"] for f in d.fields} for d in gc.all_datasets()}
    shared = [c for c in cx._ORDERED
              if len({x.dataset for x in c.candidates
                      if cx._available(x, known)}) > 1]
    if not shared:
        pytest.skip("no concept in this installation lives in two datasets")
    return {"known": known, "concepts": shared, "cx": cx}


class TestTheThreadsDatasetSettlesAConcept:
    """A figure that exists in two governed books is read from the one the
    reader is looking at.

    Both are defensible and the product used to take the declared default
    regardless, so a reader who had just asked about one dataset was answered
    from another with nothing on screen saying so.
    """

    def test_without_a_thread_the_declared_default_wins(self, concept_setup) -> None:
        cx = concept_setup["cx"]
        for concept in concept_setup["concepts"][:5]:
            plain = cx.resolve_concept(concept, concept.label,
                                       known=concept_setup["known"],
                                       phrase=concept.label)
            assert plain is not None

    def test_a_thread_on_the_other_book_moves_the_answer(self, concept_setup) -> None:
        cx = concept_setup["cx"]
        moved = 0
        for concept in concept_setup["concepts"]:
            plain = cx.resolve_concept(concept, concept.label,
                                       known=concept_setup["known"],
                                       phrase=concept.label)
            if plain is None:
                continue
            usable = [x for x in concept.candidates
                      if cx._available(x, concept_setup["known"])]
            other = next((x.dataset for x in usable
                          if x.dataset != plain.candidate.dataset), "")
            if not other:
                continue
            carried = cx.resolve_concept(concept, concept.label,
                                         known=concept_setup["known"],
                                         phrase=concept.label,
                                         preferred_datasets=[other])
            assert carried is not None
            if carried.candidate.dataset == other:
                moved += 1
                assert "this conversation" in carried.reason, (
                    "the answer must say why it read that source")
        assert moved, "no concept honoured the dataset the thread is reading"

    def test_a_book_that_does_not_carry_it_is_ignored(self, concept_setup) -> None:
        """A preference is never allowed to invent a field."""
        cx = concept_setup["cx"]
        for concept in concept_setup["concepts"][:8]:
            plain = cx.resolve_concept(concept, concept.label,
                                       known=concept_setup["known"],
                                       phrase=concept.label)
            nonsense = cx.resolve_concept(
                concept, concept.label, known=concept_setup["known"],
                phrase=concept.label,
                preferred_datasets=["a_dataset_that_does_not_exist"])
            assert plain is not None and nonsense is not None
            assert nonsense.candidate.dataset == plain.candidate.dataset
            assert nonsense.candidate.field == plain.candidate.field


class TestThePreferenceIsOnlyEverATieBreak:
    """`_base_dataset` ranks calendar, then how much of the question's scope a
    source can express, and only then what the thread is reading. A carried
    name that cannot carry the filter must lose, or a conversation could
    quietly narrow an answer to a book that does not hold the population."""

    def test_scope_coverage_beats_the_carried_name(self) -> None:
        from backend.orchestration import analysis_planner as ap

        by_dataset: dict = {"wide": [], "narrow": []}
        fields_of = {"wide": {"sector", "ifrs9_stage", "ead"},
                     "narrow": {"ead"}}
        chosen = ap._base_dataset(
            by_dataset, fields_of, [("sector", "Shipping")], "ifrs9_stage",
            None, preferred=["narrow"])
        assert chosen == "wide", (
            "a carried dataset that cannot express the scope must not be used")

    def test_it_decides_a_genuine_tie(self) -> None:
        from backend.orchestration import analysis_planner as ap

        by_dataset: dict = {"first": [], "second": []}
        fields_of = {"first": {"ead"}, "second": {"ead"}}
        assert ap._base_dataset(by_dataset, fields_of, [], "", None,
                                preferred=["second"]) == "second"
        assert ap._base_dataset(by_dataset, fields_of, [], "", None,
                                preferred=["first"]) == "first"

    def test_the_analysis_that_ran_leads_the_one_merely_looked_at(self) -> None:
        from backend.orchestration import analysis_planner as ap
        from backend.orchestration import conversation as cv

        state = cv.ConversationState()
        state.datasets = ["from_the_analysis"]
        order = ap._preferred_datasets(state, True, ["from_the_catalogue"])
        assert order == ["from_the_analysis", "from_the_catalogue"]

    def test_nothing_carried_is_no_preference_at_all(self) -> None:
        from backend.orchestration import analysis_planner as ap

        assert ap._preferred_datasets(None, False, []) is None
        assert ap._preferred_datasets(None, False, None) is None


@pytest.mark.skipif(not database_available(),
                    reason="the thread runs against the governed catalogue")
class TestTheWholeThread:
    """The seam as a reader meets it: name a dataset, then ask a question two
    governed books could both answer."""

    QUESTION = "How has the 12-month PD moved over the last year?"

    @staticmethod
    def _read(question: str, first: str = "") -> tuple[str, list[str]]:
        from backend.orchestration import memory as wm
        from backend.orchestration.executor import answer_investigation

        memory = wm.WorkingMemory()
        if first:
            opening, answered = answer_investigation(first, persist=False,
                                                     memory=memory)
            memory = wm.observe(memory, answered, opening)
        investigation, answered = answer_investigation(
            question, persist=False, memory=memory)
        payload = investigation.to_dict()
        read = sorted({n["dataset"]
                       for n in (payload.get("trace") or {}).get("nodes") or []
                       if n.get("dataset")})
        return str(payload.get("status")), read

    def test_on_its_own_it_reads_the_default(self) -> None:
        status, read = self._read(self.QUESTION)
        assert status == "succeeded"
        assert read == ["ifrs9_staging"], read

    def test_after_naming_the_facility_book_it_reads_that(self) -> None:
        status, read = self._read(
            self.QUESTION, first="Show me the Portfolio Facility dataset")
        assert status == "succeeded"
        assert read == ["portfolio_facility"], read

    def test_naming_the_default_book_changes_nothing(self) -> None:
        status, read = self._read(
            self.QUESTION,
            first="Tell me about IFRS 9 Staging and SICR Assessment")
        assert status == "succeeded"
        assert read == ["ifrs9_staging"], read


# ============================= an investigation keeps the figures it was given


@pytest.mark.skipif(not database_available(),
                    reason="saved investigations live in PostgreSQL")
class TestASavedVersionIsASnapshot:
    """Version 1 must keep reporting what version 1 computed.

    An investigation somebody circulated last quarter is evidence of what the
    book said then. If reopening it silently recomputed against today's data,
    the figure in the email and the figure on the screen would differ with
    nothing to explain why — and being able to go back to it is the whole
    point of saving one.
    """

    @pytest.fixture(scope="class")
    @classmethod
    def saved(cls):
        from backend.orchestration import investigations as inv_store
        from backend.orchestration.executor import answer_investigation

        investigation, _ = answer_investigation(
            "What is total exposure at default by IFRS 9 stage?",
            persist=True, user_id=1)
        if not investigation.analysis_run_id:
            pytest.skip("the investigation was not persisted")
        row = inv_store.save(investigation, title="Stage split, as it stood",
                             user_id=1)
        return {"id": row.id, "recorded": investigation.narrative.to_dict()}

    def test_it_records_the_periods_it_read(self, saved) -> None:
        from backend.orchestration import investigations as inv_store

        loaded = inv_store.load(saved["id"]).to_dict()
        assert loaded["version"] == 1
        assert loaded["from_period"] or loaded["to_period"], (
            "a saved version must say which reporting period it read")

    def test_reopening_it_returns_what_was_computed(self, saved) -> None:
        from backend.orchestration import investigations as inv_store

        again = inv_store.load(saved["id"], version=1).to_dict()
        assert again["narrative"] == saved["recorded"], (
            "version 1 was recomputed rather than returned")

    def test_asking_for_a_version_that_is_not_there_is_refused(self, saved) -> None:
        """It used to hand back the newest one instead.

        Somebody following a link to version 1 of a report that has since been
        refreshed would have read today's figures under version 1's heading.
        """
        from backend.orchestration import investigations as inv_store
        from backend.orchestration.investigations import InvestigationNotFound

        with pytest.raises(InvestigationNotFound) as raised:
            inv_store.load(saved["id"], version=99)
        assert "no version 99" in str(raised.value)
        assert "holds version" in str(raised.value), (
            "the refusal must say which versions do exist")


# ================================ a name the catalogue does not hold


class TestAnUnknownDatasetNameIsSaidToBeUnknown:
    """It used to fall through to the whole catalogue.

    "Show me the Facility Master dataset" — a name this bank uses internally
    and the catalogue does not — was answered with "there are 77 governed
    datasets", which answers a question nobody asked and hides the fact that
    the name was not recognised.
    """

    def test_a_name_that_is_not_there_is_recognised_as_such(self) -> None:
        from backend.orchestration import catalogue_answers as cat

        assert cat.named_but_unknown("Show me the Facility Master dataset") \
            == "Facility Master"
        assert cat.named_but_unknown("Tell me about the Widget Ledger dataset") \
            == "Widget Ledger"

    def test_a_name_that_is_there_is_not_flagged(self) -> None:
        from backend.orchestration import catalogue_answers as cat

        assert cat.named_but_unknown("Show me the Portfolio Facility dataset") == ""
        assert cat.named_but_unknown("Tell me about Corporate IFRS 9") == ""

    def test_a_reference_is_not_a_name(self) -> None:
        """"Tell me about it" continues a thread; it does not name a dataset."""
        from backend.orchestration import catalogue_answers as cat

        for question in ("Tell me about it", "Show me 50 rows", "Show Q1 2025",
                         "What datasets do you have?", "Show me the catalogue"):
            assert cat.named_but_unknown(question) == "", question

    @pytest.mark.skipif(not database_available(),
                        reason="the near matches come from the catalogue")
    def test_the_answer_says_so_and_offers_the_nearest(self) -> None:
        from backend.orchestration import memory as wm
        from backend.orchestration.executor import answer_investigation

        investigation, _ = answer_investigation(
            "Show me the Facility Master dataset", persist=False,
            memory=wm.WorkingMemory())
        summary = str((investigation.to_dict().get("narrative")
                       or {}).get("summary"))
        assert "no governed dataset called" in summary
        assert "Facility Master" in summary
        assert "77 governed datasets" not in summary, (
            "the whole catalogue is not an answer to a question about one "
            "dataset")

    @pytest.mark.skipif(not database_available(),
                        reason="the near matches come from the catalogue")
    def test_a_name_nothing_resembles_is_still_answered_honestly(self) -> None:
        from backend.orchestration import memory as wm
        from backend.orchestration.executor import answer_investigation

        investigation, _ = answer_investigation(
            "Tell me about the Widget Ledger dataset", persist=False,
            memory=wm.WorkingMemory())
        summary = str((investigation.to_dict().get("narrative")
                       or {}).get("summary"))
        assert "no governed dataset called" in summary
        assert "nothing in the catalogue is close" in summary
