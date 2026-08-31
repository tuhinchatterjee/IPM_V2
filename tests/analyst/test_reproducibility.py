"""The same question returns the same answer. §11.

This is a product contract, not a hope about temperature. Foundation models are
not deterministic, and a credit committee reading two different answers to the
same question on two days will not accept "the sampler was different". So the
determinism belongs to CreditProbe, and it rests on two things it controls:

  * the computation is already deterministic — every tool sorts by an explicit
    key with an explicit tie-break, so two runs of one plan return the same
    rows in the same order; and
  * the narrative is cached against a run key, AFTER validation, so an
    identical question returns the answer already validated rather than a new
    composition of the same evidence.

The counter-tests matter as much as the tests. A cache that returned the same
answer when the DATA had changed, or across two principals with different
visible books, would satisfy "the same answer twice" and would be a defect —
the first a stale figure presented as current, the second a permission leak.
"""

from __future__ import annotations

import pytest

from backend.analyst import answers, route, runkey, session, tools
from backend.analyst.safety import Principal
from tests.analyst.conftest import ScriptedProvider


@pytest.fixture(autouse=True)
def _empty_store():
    answers.store().clear()
    yield
    answers.store().clear()


def script(text="Contracting carries the largest exposure."):
    return [
        {"action": "CALL_TOOL", "why": "rank the sectors",
         "tool": "rank_entities",
         "arguments": {"dataset": "portfolio_facility", "entity": "sector",
                       "measure": "ead", "top": 5}},
        {"action": "ANSWER", "why": "the ranking answers it", "answer": text},
    ]


# ------------------------------------------------------------- the key


class TestTheRunKey:

    def test_the_same_question_said_differently_is_the_same_question(self):
        analyst = Principal(1, "ANALYST")
        one = runkey.build("Which borrowers are on the watchlist?", analyst)
        two = runkey.build("  which  borrowers are on the WATCHLIST  ",
                           analyst)
        assert one.key == two.key

    def test_a_different_question_is_a_different_key(self):
        analyst = Principal(1, "ANALYST")
        one = runkey.build("Which borrowers are on the watchlist?", analyst)
        two = runkey.build("Which facilities are on the watchlist?", analyst)
        assert one.key != two.key

    def test_two_permission_scopes_never_share_a_key(self):
        """A permission leak dressed as a cache hit is still a permission leak.

        The scope is part of the IDENTITY rather than a filter over a shared
        entry, so this holds whatever the storage does.
        """
        wide = Principal(1, "ANALYST")
        narrow = Principal(2, "ANALYST",
                           datasets=frozenset({"portfolio_facility"}))
        assert runkey.build("q", wide).key != runkey.build("q", narrow).key

    def test_two_users_with_the_same_permissions_do_share_one(self):
        """The counter-test. Keying on the user id would mean the product
        recomputed every answer for every person, and "the same answer" would
        then be a claim about one person's session rather than the product."""
        first = Principal(11, "ANALYST")
        second = Principal(22, "ANALYST")
        assert runkey.build("q", first).key == runkey.build("q", second).key

    def test_a_resolved_clarification_changes_the_key(self):
        """§5. "Yes, the 12-month PD" and "no, the movement" are different
        answers to the same words, and neither may be served from the other's
        entry."""
        analyst = Principal(1, "ANALYST")
        base = runkey.build("Which borrowers deteriorate?", analyst)
        one = runkey.build("Which borrowers deteriorate?", analyst,
                           clarification="use the 12-month PD")
        two = runkey.build("Which borrowers deteriorate?", analyst,
                           clarification="use the movement since last quarter")
        assert len({base.key, one.key, two.key}) == 3

    def test_the_conversation_so_far_changes_the_key(self):
        analyst = Principal(1, "ANALYST")
        alone = runkey.build("Which of those are Stage 2?", analyst)
        after = runkey.build("Which of those are Stage 2?", analyst, turns=[
            {"question": "Show the 20 largest exposures",
             "answer": "Here they are."}])
        assert alone.key != after.key

    @pytest.mark.parametrize("part", [
        "data_version", "catalogue_version", "policy_version",
        "prompt_version", "tools_version", "release_version",
    ])
    def test_every_governed_version_is_in_the_key(self, part):
        """Anything that could legitimately change the answer must be IN the
        key, so that when it moves a new answer is ALLOWED rather than
        suppressed by a stale entry."""
        analyst = Principal(1, "ANALYST")
        base = runkey.build("q", analyst)
        moved = type(base)(**{**base.to_dict_fields(), part: "moved"}) \
            if hasattr(base, "to_dict_fields") else None
        if moved is None:
            import dataclasses

            moved = dataclasses.replace(base, **{part: "moved"})
        assert base.key != moved.key

    def test_the_versions_are_read_rather_than_hard_coded(self):
        """A version that never changes is not a version."""
        assert runkey.data_version() not in ("", "unavailable")
        assert runkey.catalogue_version() not in ("", "unavailable")
        assert runkey.tools_version() not in ("", "unavailable")


# --------------------------------------------------------- the computation


class TestTheComputationIsAlreadyDeterministic:

    def test_the_same_ranking_three_times_is_identical(self):
        analyst = Principal(1, "ANALYST")
        runs = [tools.call(analyst, "rank_entities", {
            "dataset": "portfolio_facility", "entity": "sector",
            "measure": "ead", "top": 15}) for _ in range(3)]
        assert len({r.hash() for r in runs}) == 1
        assert runs[0].rows == runs[1].rows == runs[2].rows

    def test_ties_are_broken_by_an_explicit_key(self):
        """Utilisation is capped, so many facilities share the top value. The
        order must not depend on how the engine felt like scanning."""
        analyst = Principal(1, "ANALYST")
        first = tools.call(analyst, "query_dataset", {
            "dataset": "portfolio_facility",
            "columns": ["account_id", "utilisation_pct"],
            "order_by": "utilisation_pct", "limit": 30})
        second = tools.call(analyst, "query_dataset", {
            "dataset": "portfolio_facility",
            "columns": ["account_id", "utilisation_pct"],
            "order_by": "utilisation_pct", "limit": 30})
        assert first.rows == second.rows


# ------------------------------------------------------------ the contract


class TestTheSameQuestionReturnsTheSameAnswer:

    def test_the_second_ask_returns_the_validated_first_answer(self):
        analyst = Principal(1, "ANALYST")
        first = route.answer("Which sectors carry the most exposure?", analyst,
                             provider=ScriptedProvider(script()))
        assert first["path"] == route.ANALYST
        assert first["reproduced"] is False

        # A provider with an EMPTY script: if the loop ran again this raises.
        second = route.answer("Which sectors carry the most exposure?",
                              analyst, provider=ScriptedProvider([]))

        assert second["reproduced"] is True
        assert second["path"] == route.REPRODUCED
        assert second["answer"] == first["answer"]
        assert second["evidence"]["hash"] == first["evidence"]["hash"]

    def test_it_holds_when_the_model_would_have_said_something_else(self):
        """The whole point. A second run with a DIFFERENT scripted answer must
        still return the first, because the run key has not moved."""
        analyst = Principal(1, "ANALYST")
        first = route.answer("Which sectors?", analyst,
                             provider=ScriptedProvider(script("First wording.")))
        second = route.answer(
            "Which sectors?", analyst,
            provider=ScriptedProvider(script("Completely different wording.")))
        assert second["answer"] == first["answer"] == "First wording."

    def test_asking_ten_times_returns_one_answer(self):
        analyst = Principal(1, "ANALYST")
        route.answer("Which sectors?", analyst,
                     provider=ScriptedProvider(script()))
        seen = {route.answer("Which sectors?", analyst,
                             provider=ScriptedProvider([]))["answer"]
                for _ in range(10)}
        assert len(seen) == 1

    def test_a_different_scope_does_not_read_the_first_answer(self):
        """The counter-test that matters most: not a cache miss, a refusal to
        hand one principal's result to another."""
        wide = Principal(1, "ANALYST")
        narrow = Principal(2, "ANALYST",
                           datasets=frozenset({"portfolio_facility"}))
        route.answer("Which sectors?", wide,
                     provider=ScriptedProvider(script("Wide answer.")))
        other = route.answer("Which sectors?", narrow,
                             provider=ScriptedProvider(script("Narrow answer.")))
        assert other["answer"] == "Narrow answer."
        assert other["reproduced"] is False

    def test_a_clarification_is_never_cached(self):
        """It would make the product ask the same question for ever."""
        analyst = Principal(1, "ANALYST")
        asked = route.answer(
            "Which borrowers deteriorate?", analyst,
            provider=ScriptedProvider([
                {"action": "ASK", "why": "two measures fit",
                 "question": "12-month PD or the movement?",
                 "assumption": "the 12-month PD"}]))
        assert asked["outcome"] == session.ASK
        assert len(answers.store()) == 0

    def test_the_stored_answer_is_only_stored_after_grounding(self):
        """§11: cache AFTER validation. Caching a draft turns one bad answer
        into a permanently reproducible one."""
        analyst = Principal(1, "ANALYST")
        found = route.answer(
            "How large is Contracting?", analyst,
            provider=ScriptedProvider(script("Contracting is 987654321.")))
        assert "987654321" in " ".join(found["removed_ungrounded"])
        stored = answers.store().get(found["run_key"]["key"])
        assert stored is not None
        assert "987654321" not in stored.payload["answer"]

    def test_the_entry_carries_the_hashes_that_make_it_checkable(self):
        analyst = Principal(1, "ANALYST")
        found = route.answer("Which sectors?", analyst,
                             provider=ScriptedProvider(script()))
        stored = answers.store().get(found["run_key"]["key"])
        assert stored.evidence_hash
        assert stored.answer_hash
        assert stored.run_key["data_version"]


class TestTheStore:

    def test_it_is_bounded(self):
        from backend.analyst.answers import Store, StoredAnswer

        store = Store(limit=3)
        for index in range(10):
            store.put(StoredAnswer(key=str(index), question=str(index)))
        assert len(store) == 3
        assert store.get("0") is None
        assert store.get("9") is not None

    def test_the_oldest_is_evicted_first(self):
        from backend.analyst.answers import Store, StoredAnswer

        store = Store(limit=2)
        store.put(StoredAnswer(key="a", question="a"))
        store.put(StoredAnswer(key="b", question="b"))
        store.get("a")                       # a is now the most recent
        store.put(StoredAnswer(key="c", question="c"))
        assert store.get("b") is None
        assert store.get("a") is not None
