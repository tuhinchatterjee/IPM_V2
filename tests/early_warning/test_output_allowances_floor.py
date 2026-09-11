"""
The floor under every stage's output allowance.

The lesson this file exists to stop relearning
----------------------------------------------
A `max_tokens` ceiling is not a budget for the document. On Opus 5 and on
Sonnet 5 adaptive thinking is ON whenever the request omits `thinking` — which
this seam does — and those tokens come out of the SAME allowance. So a stage
whose JSON is two hundred tokens can still be cut off at a thousand.

That has now happened three times, on three different stages, and each time it
was fixed one stage at a time:

    opus_sufficiency_review    truncated at 1,000   raised to 2,000
    opus_final_interpretation  truncated at 1,600   raised to 3,000
    sonnet_summary_update      truncated at   700   raised to 2,000

After the first two were fixed, `opus_functionality_selection` was still
sitting at 900 — below a level already PROVEN to truncate on the same model
family — and `sonnet_pass_1` at 700, the exact number that had just failed on
the other Sonnet stage. Nothing caught that, because nothing was looking.

So the rule is a number rather than a memory. Every stage is at or above
`MINIMUM_ALLOWANCE`, and a stage added later cannot quietly sit under it.

What this is not
----------------
Not a licence to raise every ceiling globally. The floor is a floor: a stage
still gets the allowance its own document needs, and the plan stage at 4,000
is four thousand because a six-step plan is a long document, not because
bigger is safer.
"""

from __future__ import annotations

import pytest

from backend.early_warning.conversation import seam as seam_mod

#: The largest allowance any stage has been observed to truncate at. Anything
#: at or below this is known-unsafe rather than merely untested.
OBSERVED_TRUNCATION = 1000


def test_every_stage_clears_the_floor():
    under = {key: stage.max_tokens
             for key, stage in seam_mod.STAGES.items()
             if stage.max_tokens < seam_mod.MINIMUM_ALLOWANCE}
    assert not under, (
        f"these stages are below the {seam_mod.MINIMUM_ALLOWANCE}-token "
        f"floor and will truncate on a thinking-by-default model: {under}")


def test_no_stage_sits_at_a_level_already_proven_to_fail():
    """The specific defect: a ceiling below one that demonstrably truncated."""
    unsafe = {key: stage.max_tokens
              for key, stage in seam_mod.STAGES.items()
              if stage.max_tokens <= OBSERVED_TRUNCATION}
    assert not unsafe, (
        f"{unsafe} sit at or below {OBSERVED_TRUNCATION}, which has already "
        f"cut off a well-formed reply on these models")


def test_the_floor_is_above_the_observed_truncation():
    assert seam_mod.MINIMUM_ALLOWANCE > OBSERVED_TRUNCATION


@pytest.mark.parametrize("key", [
    seam_mod.PASS_1, seam_mod.PASS_2, seam_mod.FUNCTIONALITY,
    seam_mod.SUMMARY,
])
def test_the_four_stages_that_were_under_the_floor_are_now_over_it(key):
    """Named individually, so a revert shows up as the stage it reverted."""
    assert seam_mod.STAGES[key].max_tokens >= seam_mod.MINIMUM_ALLOWANCE


def test_the_summary_stage_has_room_for_its_document_and_its_thinking():
    """The stage the live run lost.

    Losing it is quiet and expensive: the rolling summary is what lets the
    NEXT turn resolve "it", so a thread whose summary fell back keeps
    answering — and keeps answering a slightly different question than the
    one that was asked.
    """
    summary = seam_mod.STAGES[seam_mod.SUMMARY]
    assert summary.max_tokens >= 2000
    assert summary.closing is True, (
        "the summary must stay inside the closing reserve: a turn that spent "
        "its allowance on optional work and then could not write the summary "
        "has broken the next turn, not this one")


def test_the_closing_stages_are_the_two_a_turn_cannot_end_without():
    closing = {k for k, s in seam_mod.STAGES.items() if s.closing}
    assert closing == {seam_mod.INTERPRETATION, seam_mod.SUMMARY}


def test_the_plan_stage_is_still_the_largest():
    """A floor is not a levelling. The longest document still gets the most."""
    plan = seam_mod.STAGES[seam_mod.PLAN].max_tokens
    assert plan == max(s.max_tokens for s in seam_mod.STAGES.values())
    assert plan >= 4000


def test_allowances_were_not_raised_globally():
    """The earlier directive: do not blindly raise every ceiling.

    Two stages keep the allowances they were given on their own evidence, so
    a change that simply set everything to one number would fail here.
    """
    assert seam_mod.STAGES[seam_mod.REPAIR].max_tokens == 2500
    assert seam_mod.STAGES[seam_mod.INTERPRETATION].max_tokens == 3000
    assert len({s.max_tokens for s in seam_mod.STAGES.values()}) >= 4
