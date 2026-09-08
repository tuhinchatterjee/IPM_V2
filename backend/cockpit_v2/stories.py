"""
The narrative cases the demo book is built to contain. Brief §4.1.

Each story is a MECHANIC, not a script. It says what has to be true of a
borrower's generated history — cash generation falls while the rating holds, a
waiver expires, scenario weights move and nothing else does — and the generator
produces that mechanic from its parameters. The expected ANSWER is never
written down here and never reaches the runtime.

That separation is the point. `story_manifest()` is used by the integrity gates
and the evaluation suite to find the fixture borrowers and assert that the
mechanic actually landed in the data. It is deliberately NOT reachable from any
governed dataset, tool or prompt: `backend.cockpit_v2.scope` does not list it,
`generate` does not write it to Parquet, and
`tests/cockpit_v2/test_scope.py::test_the_story_manifest_is_not_reachable_from_any_tool`
holds that shut. A model that could read the manifest would be answering from
the answer key.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Story:
    """One identifiable mechanic, and the knobs the generator turns for it."""

    story_id: str
    label: str
    #: What must be observable in the generated data. Checked by the gates.
    mechanic: str
    #: Multiplicative or additive adjustments the generator applies.
    knobs: dict[str, Any] = field(default_factory=dict)


STORIES: tuple[Story, ...] = (
    Story("GROWTH_STABLE_QUALITY", "Growth with stable quality",
          "Exposure rises materially while the rating, stage and PD hold. A "
          "correct answer must not call this deterioration.",
          {"exposure_growth": 0.11, "ebitda_growth": 0.10, "rating_drift": 0.0,
           "origination_equals_current": True, "hold_utilisation": True,
           "hold_macro": True}),
    Story("CASH_DETERIORATION", "Deteriorating cash generation and rating",
          "EBITDA and cash available for debt service fall quarter on quarter, "
          "the model grade drops and PD rises with it.",
          {"exposure_growth": 0.01, "ebitda_growth": -0.085,
           "rating_drift": 0.55}),
    Story("COLLATERAL_WEAKENING", "Collateral weakening with stable PD",
          "Property valuations fall and recognised coverage drops, so LGD "
          "rises while the PD curve is unchanged. The ECL move must attribute "
          "to recovery, not to PD.",
          {"exposure_growth": 0.0, "ebitda_growth": 0.005,
           "rating_drift": 0.0, "collateral_shock": -0.22,
           "hold_macro": True, "hold_utilisation": True}),
    Story("IMPROVING_CREDIT", "Improving credit",
          "Ratios strengthen, the grade improves and ECL falls. The answer "
          "must explain improvement as readily as deterioration.",
          {"exposure_growth": 0.02, "ebitda_growth": 0.075,
           "rating_drift": -0.5}),
    Story("WEIGHTS_ONLY", "Scenario-weight-only ECL movement",
          "Every borrower parameter is unchanged; only the scenario weights "
          "move. Attribution must put the whole movement on scenario weights "
          "and nothing on PD.",
          {"exposure_growth": 0.0, "ebitda_growth": 0.0, "rating_drift": 0.0,
           "weights_only": True, "hold_macro": True,
           "hold_utilisation": True}),
    Story("OVERLAY_CHANGE", "An overlay change",
          "The modelled ECL is flat and the separately identified overlay "
          "moves. The bridge must show it on the overlay line.",
          {"exposure_growth": 0.0, "ebitda_growth": 0.0, "rating_drift": 0.0,
           "overlay_step": 0.9, "hold_macro": True,
           "hold_utilisation": True}),
    Story("BREACH_WITH_WAIVER", "Covenant breach with a valid waiver",
          "A DSCR covenant is breached and a waiver valid at the reporting "
          "date covers it. The breach stays visible in history.",
          {"exposure_growth": 0.01, "ebitda_growth": -0.06,
           "rating_drift": 0.3, "waiver": "valid"}),
    Story("EXPIRING_WAIVER", "An expiring waiver",
          "A waiver expires inside the next quarter of the snapshot's own "
          "timeline, so the review question has a real object.",
          {"exposure_growth": 0.0, "ebitda_growth": -0.04,
           "rating_drift": 0.25, "waiver": "expiring"}),
    Story("STAGE_1_TO_2", "Stage 1 to Stage 2 migration",
          "The account crosses the stated SICR rule between the two quarters "
          "and the recorded reason names the rule that fired.",
          {"exposure_growth": 0.0, "ebitda_growth": 0.0,
           "sicr_step_at_end": True, "sicr_step_notches": 4.0,
           "origination_equals_current": True,
           "hold_utilisation": True, "hold_macro": True}),
    Story("STAGE_3_RECOVERY", "Stage 3 with changing expected recoveries",
          "A credit-impaired account whose expected recovery changes between "
          "the dates, measured by the cash-shortfall method throughout.",
          {"exposure_growth": 0.0, "ebitda_growth": -0.05,
           "start_stage_3": True, "recovery_shift": -0.09}),
    Story("NEW_LENDING", "New lending",
          "A facility that exists at the closing date only. It must appear on "
          "the entry line, not as a PD movement.",
          {"exposure_growth": 0.05, "ebitda_growth": 0.02, "enters_at": 1}),
    Story("REPAYMENT", "Repayment",
          "A facility repaid between the dates. It leaves on the exit line "
          "and its departure is not credit improvement.",
          {"exposure_growth": 0.0, "ebitda_growth": 0.01, "exits_at": 1}),
    Story("WRITE_OFF", "Write-off reducing reported exposure",
          "A Stage 3 facility written off. Reported exposure and ECL both "
          "fall, and neither implies that anything was recovered.",
          {"start_stage_3": True, "write_off_at": 1}),
    Story("OFFSETTING_SEGMENTS", "Offsetting segment movements",
          "Two borrowers in different sectors move in opposite directions by "
          "similar amounts, so the net is near zero and the detail is not.",
          {"exposure_growth": 0.0, "ebitda_growth": -0.07,
           "rating_drift": 0.8}),
    Story("OFFSETTING_SEGMENTS_MIRROR", "The other side of the offset",
          "The mirror of OFFSETTING_SEGMENTS, improving by a similar amount.",
          {"exposure_growth": 0.0, "ebitda_growth": 0.07,
           "rating_drift": -0.8}),
    Story("STALE_STATEMENTS", "Stale or missing statements",
          "No statement has become available for several quarters, so ratios "
          "are marked not available rather than invented.",
          {"exposure_growth": 0.0, "ebitda_growth": 0.0,
           "suppress_statements": True}),
    Story("SHARED_COLLATERAL", "Shared collateral across facilities",
          "One property secures three facilities. Allocated recognised amounts "
          "must sum to no more than the recognised value of the asset.",
          {"exposure_growth": 0.01, "ebitda_growth": 0.01,
           "shared_collateral": 3}),
    Story("GROUP_CONCENTRATION", "Concentration in a small connected group",
          "Several borrowers in one group hold a large share of the book, so "
          "group exposure must not count one borrower three times.",
          {"exposure_growth": 0.06, "ebitda_growth": 0.01,
           "group_concentration": True}),
)

STORY_BY_ID = {s.story_id: s for s in STORIES}


def story_manifest(assignments: dict[str, str]) -> dict[str, Any]:
    """Which borrower carries which mechanic, for the gates and the evals.

    `assignments` maps borrower id to story id. Test-and-evaluation surface
    only; never serialised into a governed dataset and never placed in a prompt.
    """
    return {
        "version": "1.0.0",
        "warning": ("TEST FIXTURE MAP. Not a governed dataset. It must never "
                    "be placed in a model prompt, returned by a tool or "
                    "retrieved at runtime: it identifies the answer to cases "
                    "the evaluation suite scores."),
        "stories": [
            {"story_id": s.story_id, "label": s.label, "mechanic": s.mechanic,
             "borrowers": sorted(b for b, sid in assignments.items()
                                 if sid == s.story_id)}
            for s in STORIES],
    }


__all__ = ["STORIES", "STORY_BY_ID", "Story", "story_manifest"]
