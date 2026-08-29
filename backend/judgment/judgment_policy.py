"""
When the harder model is worth its cost, and what it may see. §91.

    "Use deterministic engines first.
     Do not send raw portfolios to Opus.
     Do not hard-code model IDs."

Three instructions, three different failures.

**Deterministic engines first.** Every situation on §91's list has a governed
engine underneath it — drivers, breadth, persistence, materiality, the fifteen
contradiction diagnostics. The complex-planner role is for SYNTHESIS over what
those engines produced, never for producing it. A model asked to work out
whether a movement is broad will answer, plausibly, from nothing, and the
answer will be indistinguishable from the one the engine computes.

**No raw portfolios.** Cost is the least of it. A model handed ten thousand
rows will find a pattern in them, and the pattern will not have been computed
by anything — the same failure §79 guards the interpretation pack against,
arriving through a different door. So what escalates is a bounded package of
FACTS and OBSERVATIONS, and this module refuses to build one that is not.

**No hard-coded model IDs.** The role is named; the model behind it is
configuration. A module that named a provider model would decide, in code,
something the deployment is supposed to decide, and would be wrong the week
after the next model ships.

Why escalation is a list rather than a threshold
-------------------------------------------------
§25's cascade already escalates on measured complexity. This is different:
ten SITUATIONS where the harder model is warranted regardless of how simple
the arithmetic looked, because what is hard about them is the judgement rather
than the analysis. A contradiction with two surviving explanations is not
complex to compute and is exactly where a fluent wrong answer does the most
damage.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.llm import roles as rl

JUDGMENT_POLICY_VERSION = "1.0.0"

# ------------------------------------------------------ §91's ten situations
BLUEPRINT_SELECTION = "broad_investigation_blueprint_selection"
HYPOTHESIS_REVIEW = "hypothesis_tree_review"
ECL_SYNTHESIS = "ecl_decomposition_synthesis"
CONTRADICTION_SYNTHESIS = "contradictory_signal_synthesis"
CRITICAL_MATERIALITY = "critical_materiality_interpretation"
CONFLICTING_AGENTS = "conflicting_agent_conclusions"
DEMO_SAFE = "client_demo_safe_high_risk_answer"
RUBRIC_REPAIR = "interpretation_rubric_repair"
CHALLENGE_PASS = "challenge_pass"
MULTI_EXPLANATION = "unresolved_multi_explanation_case"

SITUATIONS: tuple[str, ...] = (
    BLUEPRINT_SELECTION, HYPOTHESIS_REVIEW, ECL_SYNTHESIS,
    CONTRADICTION_SYNTHESIS, CRITICAL_MATERIALITY, CONFLICTING_AGENTS,
    DEMO_SAFE, RUBRIC_REPAIR, CHALLENGE_PASS, MULTI_EXPLANATION,
)

#: Why each one warrants the harder model, in the words somebody would use to
#: argue that it does not. A policy whose entries are only labels gets
#: extended by whoever wants their feature to be important.
BECAUSE: dict[str, str] = {
    BLUEPRINT_SELECTION: "Choosing what a competent analyst would look at "
                         "decides everything downstream, and a wrong "
                         "blueprint produces a complete, coherent "
                         "investigation of the wrong question.",
    HYPOTHESIS_REVIEW: "Deciding which explanations are worth testing is the "
                       "judgement; testing them is mechanical.",
    ECL_SYNTHESIS: "The decomposition is computed. Saying which of the "
                   "reconciling components is the story is not.",
    CONTRADICTION_SYNTHESIS: "The fifteen diagnostics are deterministic. "
                             "Reading what they collectively mean is where a "
                             "plausible invented story gets written.",
    CRITICAL_MATERIALITY: "At the top band the answer changes what somebody "
                          "does, so the interpretation carries the most "
                          "consequence it ever does.",
    CONFLICTING_AGENTS: "Two specialists reaching different conclusions is "
                        "precisely the case no deterministic rule resolves.",
    DEMO_SAFE: "A high-risk answer shown to a client cannot be repaired "
               "afterwards.",
    RUBRIC_REPAIR: "The rubric already found the defect; repairing it without "
                   "introducing a second one is the hard part.",
    CHALLENGE_PASS: "The challenge pass exists to find what the analysis "
                    "assumed, and a model that shares the assumption will not "
                    "find it.",
    MULTI_EXPLANATION: "Several surviving explanations is exactly where the "
                       "temptation to pick one is strongest.",
}

#: The deterministic engine that must have run FIRST for each situation.
#: §91's first line, made checkable: escalating before the engine ran means
#: asking a model to produce what an engine computes.
REQUIRES_FIRST: dict[str, tuple[str, ...]] = {
    BLUEPRINT_SELECTION: ("blueprint_scoring",),
    HYPOTHESIS_REVIEW: ("hypothesis_tree",),
    ECL_SYNTHESIS: ("driver_decomposition", "reconciliation"),
    CONTRADICTION_SYNTHESIS: ("contradiction_diagnostics",),
    CRITICAL_MATERIALITY: ("materiality_assessment",),
    CONFLICTING_AGENTS: (),
    DEMO_SAFE: ("presentability_rubric",),
    RUBRIC_REPAIR: ("presentability_rubric",),
    CHALLENGE_PASS: ("hypothesis_tree",),
    MULTI_EXPLANATION: ("contradiction_diagnostics",),
}

#: The role that handles each. Named roles, never model ids: §91's third line,
#: and the reason `roles.py` exists at all.
ROLE_FOR: dict[str, str] = {
    BLUEPRINT_SELECTION: rl.COMPLEX_PLANNER,
    HYPOTHESIS_REVIEW: rl.COMPLEX_PLANNER,
    ECL_SYNTHESIS: rl.COMPLEX_PLANNER,
    CONTRADICTION_SYNTHESIS: rl.COMPLEX_PLANNER,
    CRITICAL_MATERIALITY: rl.COMPLEX_PLANNER,
    CONFLICTING_AGENTS: rl.COMPLEX_PLANNER,
    DEMO_SAFE: rl.CRITIC,
    RUBRIC_REPAIR: rl.CRITIC,
    CHALLENGE_PASS: rl.CRITIC,
    MULTI_EXPLANATION: rl.COMPLEX_PLANNER,
}


class EngineFirst(Exception):
    """Escalation attempted before the deterministic engine ran.

    Raised rather than allowed, because the permissive version of this is a
    model producing a breadth verdict, a materiality band or a contribution —
    all of which it will do, fluently, and none of which anybody can check
    against the engine that did not run.
    """


class RawData(Exception):
    """A package carrying rows rather than facts.

    Cost is the least of it. A model handed ten thousand rows finds a pattern
    in them and the pattern was computed by nothing.
    """


#: How many facts and observations may go up. Above this the package is not
#: a summary of an investigation, it is the investigation.
MAX_FACTS = 60
MAX_OBSERVATIONS = 40


@dataclass
class Escalation:
    """One decision to use the harder role, and what it is allowed to see."""

    situation: str = ""
    role: str = ""
    #: Which deterministic engines produced the material below.
    engines_run: list[str] = field(default_factory=list)
    fact_ids: list[str] = field(default_factory=list)
    observation_ids: list[str] = field(default_factory=list)
    #: Structured summaries only — an engine's verdict, never its inputs.
    summaries: list[dict[str, Any]] = field(default_factory=list)
    why: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"version": JUDGMENT_POLICY_VERSION,
                "situation": self.situation, "role": self.role,
                "engines_run": list(self.engines_run),
                "fact_ids": list(self.fact_ids),
                "observation_ids": list(self.observation_ids),
                "summaries": [dict(s) for s in self.summaries],
                "why": self.why,
                # Named so a Trace reader can see that no model id was
                # decided here. The deployment configures the role.
                "model_chosen_here": False}


def applies(situation: str) -> bool:
    """Whether §91 names this situation. Unknown situations do not escalate.

    Fails closed in the cost direction rather than the quality one, because
    the alternative — any string escalating — makes the policy a list of
    examples rather than a policy.
    """
    return situation in SITUATIONS


def escalate(situation: str, *, engines_run: list[str],
             fact_ids: list[str] | None = None,
             observation_ids: list[str] | None = None,
             summaries: list[dict[str, Any]] | None = None,
             rows: list[Any] | None = None) -> Escalation:
    """Build the package that goes to the harder role. §91's three rules.

    Refuses rather than trims when the rules are broken: a package silently
    stripped of its rows would let a caller go on sending them, and a
    situation silently downgraded to the ordinary planner would produce an
    answer nobody knew had been decided by the cheaper model.
    """
    if not applies(situation):
        raise KeyError(f"{situation!r} is not one of §91's situations")

    required = REQUIRES_FIRST[situation]
    missing = [engine for engine in required if engine not in engines_run]
    if missing:
        raise EngineFirst(
            f"{situation} may not escalate before {', '.join(missing)} has "
            "run; §91 says deterministic engines first")

    if rows:
        raise RawData(
            f"{len(rows)} result rows were offered to the {ROLE_FOR[situation]} "
            "role; §91 permits facts and observations, not portfolios")

    facts = list(fact_ids or [])
    observations = list(observation_ids or [])
    if len(facts) > MAX_FACTS or len(observations) > MAX_OBSERVATIONS:
        raise RawData(
            f"{len(facts)} facts and {len(observations)} observations is not a "
            "summary of an investigation, it is the investigation")

    return Escalation(
        situation=situation, role=ROLE_FOR[situation],
        engines_run=list(engines_run), fact_ids=facts,
        observation_ids=observations, summaries=list(summaries or []),
        why=BECAUSE[situation])


def policy() -> dict[str, Any]:
    """The whole policy, for the Studio and for a model-risk reviewer.

    Every situation with its role, its reason and the engine that has to run
    first — so somebody can disagree with an entry rather than with the
    behaviour it produces.
    """
    return {
        "version": JUDGMENT_POLICY_VERSION,
        "situations": [
            {"id": situation, "role": ROLE_FOR[situation],
             "because": BECAUSE[situation],
             "requires_first": list(REQUIRES_FIRST[situation])}
            for situation in SITUATIONS],
        "max_facts": MAX_FACTS,
        "max_observations": MAX_OBSERVATIONS,
        "roles_named_not_models": True,
    }


__all__ = ["BECAUSE", "BLUEPRINT_SELECTION", "CHALLENGE_PASS",
           "CONFLICTING_AGENTS", "CONTRADICTION_SYNTHESIS",
           "CRITICAL_MATERIALITY", "DEMO_SAFE", "ECL_SYNTHESIS",
           "EngineFirst", "Escalation", "HYPOTHESIS_REVIEW",
           "JUDGMENT_POLICY_VERSION", "MAX_FACTS", "MAX_OBSERVATIONS",
           "MULTI_EXPLANATION", "RUBRIC_REPAIR", "REQUIRES_FIRST",
           "ROLE_FOR", "RawData", "SITUATIONS", "applies", "escalate",
           "policy"]
