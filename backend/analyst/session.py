"""The investigation loop. §2, §5, §7, §8, §10.

One turn
--------
CreditProbe hands the model the question in the user's own words, the tools it
may use, and everything the tools have returned so far. The model returns ONE
governed decision document:

    {"action": "CALL_TOOL", "tool": "rank_entities", "arguments": {...},
     "why": "..."}
    {"action": "ASK",    "question": "...", "assumption": "..."}
    {"action": "ANSWER", "answer": "...", "findings": [...],
     "unavailable": [...]}
    {"action": "CANNOT", "why": "..."}

CreditProbe runs the tool, appends the result to the evidence, and asks again.
The model decides the next step from what the last one returned; that is what
makes this an investigation rather than a translation.

Why a decision document rather than a tool-calling API
------------------------------------------------------
`backend.llm` exposes one primitive: a schema-constrained call in which a reply
that does not conform is an ERROR rather than something to salvage. That
property is the reason anything downstream can be trusted, and it works
unchanged against the fake provider the tests use. Building the loop out of it
keeps one contract instead of two.

The four rules this loop enforces, whatever the model says
----------------------------------------------------------
**§7 — answer the supported portion.** A question naming seven kinds of
evidence when the catalogue carries four is answered on the four, with the
three named. The loop cannot let the model refuse a question because one
dimension is missing: CANNOT is only accepted when NOTHING was found.

**§8 — a normal question does not dead-end.** Four outcomes are permitted and
"not understood" is not among them. A model that asks a question gets one
round; a model that asks twice has stopped investigating, and the loop makes
it answer on what it has.

**§42 — grounding.** Every figure in the answer is checked against the
evidence ledger. One that is in no observation is removed, and the removal is
recorded rather than hidden.

**§50 — budget.** Turns and tool calls are bounded. A loop that can run for
ever is not a control, and neither is a prompt asking it to be brief.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from backend.analyst import safety, tools
from backend.analyst.evidence import Ledger, Observation
from backend.analyst.safety import Principal

logger = logging.getLogger(__name__)

SESSION_VERSION = "1.0.0"

CALL_TOOL = "CALL_TOOL"
ASK = "ASK"
ANSWER = "ANSWER"
CANNOT = "CANNOT"
ACTIONS = (CALL_TOOL, ASK, ANSWER, CANNOT)

#: The document the model returns each turn. One schema for every turn, because
#: a schema that changes with the state of the loop is a schema with states,
#: and a model that guesses which one it is in produces a valid document about
#: the wrong thing.
DECISION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string", "enum": list(ACTIONS),
            "description": (
                "CALL_TOOL to gather more governed evidence. ANSWER when the "
                "evidence supports an answer. ASK only when one genuine "
                "ambiguity would change which figure is correct, and only "
                "once. CANNOT only when nothing in the catalogue bears on the "
                "question at all."),
        },
        "why": {
            "type": "string",
            "description": ("One sentence: what this step is for. Shown on the "
                            "Trace. Not your reasoning — your intention."),
        },
        "tool": {"type": "string", "description": "For CALL_TOOL: the name."},
        "arguments": {
            "type": "object",
            "description": "For CALL_TOOL: its arguments.",
            "additionalProperties": True,
        },
        "question": {
            "type": "string",
            "description": ("For ASK: one short question in plain English. No "
                            "options list, no menu — the user types a reply."),
        },
        "assumption": {
            "type": "string",
            "description": ("For ASK: what you will assume if they say yes, so "
                            "the question can be answered with one word."),
        },
        "answer": {
            "type": "string",
            "description": ("For ANSWER: the analytical answer, in the words a "
                            "credit officer would use. Every figure in it must "
                            "have come from a tool result."),
        },
        "findings": {
            "type": "array", "items": {"type": "string"},
            "description": "For ANSWER: the specific things the evidence shows.",
        },
        "unavailable": {
            "type": "array", "items": {"type": "string"},
            "description": ("For ANSWER: the things the question asked for that "
                            "this deployment has no governed measure for. Name "
                            "them; never estimate them."),
        },
        "limitations": {
            "type": "array", "items": {"type": "string"},
            "description": "For ANSWER: what would change this conclusion.",
        },
    },
    "required": ["action", "why"],
    "additionalProperties": False,
}


@dataclass
class Decision:
    """One turn's governed decision, after validation."""

    action: str = CANNOT
    why: str = ""
    tool: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)
    question: str = ""
    assumption: str = ""
    answer: str = ""
    findings: list[str] = field(default_factory=list)
    unavailable: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)

    @classmethod
    def read(cls, payload: dict[str, Any]) -> Decision:
        action = str(payload.get("action") or "").upper()
        return cls(
            action=action if action in ACTIONS else CANNOT,
            why=str(payload.get("why") or ""),
            tool=str(payload.get("tool") or ""),
            arguments=dict(payload.get("arguments") or {}),
            question=str(payload.get("question") or ""),
            assumption=str(payload.get("assumption") or ""),
            answer=str(payload.get("answer") or ""),
            findings=[str(f) for f in (payload.get("findings") or [])],
            unavailable=[str(u) for u in (payload.get("unavailable") or [])],
            limitations=[str(x) for x in (payload.get("limitations") or [])],
        )

    def to_dict(self) -> dict[str, Any]:
        return {"action": self.action, "why": self.why, "tool": self.tool,
                "arguments": dict(self.arguments), "question": self.question,
                "assumption": self.assumption, "answer": self.answer,
                "findings": list(self.findings),
                "unavailable": list(self.unavailable),
                "limitations": list(self.limitations)}


@dataclass
class Investigation:
    """What the loop produced, and everything it did to get there."""

    question: str = ""
    outcome: str = CANNOT
    answer: str = ""
    findings: list[str] = field(default_factory=list)
    unavailable: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    #: For ASK: what the user is asked, and what a "yes" means.
    question_back: str = ""
    assumption: str = ""
    ledger: Ledger = field(default_factory=Ledger)
    #: Every decision, in order. The Trace's account of how the answer arose.
    steps: list[Decision] = field(default_factory=list)
    #: Figures the model wrote that no observation supports. §42.
    removed: list[str] = field(default_factory=list)
    turns: int = 0
    duration_ms: int = 0
    #: Present when the loop could not run at all.
    error: str = ""

    @property
    def answered(self) -> bool:
        return self.outcome == ANSWER and bool(self.answer)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": SESSION_VERSION,
            "question": self.question, "outcome": self.outcome,
            "answer": self.answer, "findings": list(self.findings),
            "unavailable": list(self.unavailable),
            "limitations": list(self.limitations),
            "question_back": self.question_back, "assumption": self.assumption,
            "removed_ungrounded": list(self.removed),
            "turns": self.turns, "duration_ms": self.duration_ms,
            "error": self.error,
            "evidence": self.ledger.to_dict(),
            "steps": [s.to_dict() for s in self.steps],
        }


# ------------------------------------------------------------- the prompt

SYSTEM = """\
You are the analyst inside CreditProbe, a governed credit-risk platform.

You investigate. You never calculate. Every figure you report must have come
back from a governed tool in this conversation; CreditProbe computes, validates
and traces all of it, and a number you produce yourself is not evidence.

How to work
-----------
Look before you plan. The catalogue tools cost nothing: find out which datasets
exist, what one row of each represents, and what its fields mean, rather than
assuming a field name. Then gather evidence, read it, and gather more if the
first result raises a question. Answer when the evidence supports an answer.

Rules that are not negotiable
-----------------------------
1. If the question names several kinds of evidence and this deployment carries
   only some, ANSWER on the ones it carries and list the others under
   `unavailable`. Never refuse a whole question because one dimension is
   missing, and never estimate a figure the catalogue cannot supply.
2. ASK at most once, and only when one genuine ambiguity would change WHICH
   figure is correct — not to narrow scope you could reasonably choose
   yourself. Phrase it as one short sentence a person can answer with a word,
   state in `assumption` what you will do if they agree, and offer no menu.
3. Apply judgement to the evidence. "The rating is unchanged while leverage,
   utilisation and covenant headroom have all deteriorated" is the analysis;
   restating the table is not.
4. Answer at the grain the question asked for. A question about borrowers is
   answered with borrowers, whatever the shape of the data underneath.
5. Never name the intelligence provider or the model. Never call this
   deployment a demonstration.
"""


def _prompt(question: str, catalogue: str, ledger: Ledger, *,
            turns_left: int, asked_already: bool, context: str) -> str:
    parts = [f"THE QUESTION\n{question}\n"]
    if context:
        parts.append(f"EARLIER IN THIS INVESTIGATION\n{context}\n")
    parts.append(f"GOVERNED TOOLS\n{catalogue}\n")
    if ledger.observations:
        parts.append("EVIDENCE SO FAR")
        for index, observation in enumerate(ledger.observations, start=1):
            parts.append(_render(index, observation))
    else:
        parts.append("EVIDENCE SO FAR\nNothing yet. Start by looking.")
    parts.append(
        f"\nYou have {turns_left} turn(s) left."
        + (" You have already asked the user one question; do not ask another."
           if asked_already else ""))
    if turns_left <= 1:
        parts.append(
            "This is your last turn. ANSWER on the evidence above, naming "
            "anything the question asked for that is not in it.")
    return "\n".join(parts)


def _render(index: int, observation: Observation) -> str:
    head = f"[{index}] {observation.tool}({_args(observation.arguments)})"
    if observation.refused:
        return f"{head}\n    REFUSED: {observation.refused}"
    lines = [f"{head}  -> {observation.total_rows} row(s)"]
    if observation.purpose:
        lines.append(f"    {observation.purpose}")
    for row in observation.rows[:safety.MAX_ROWS_TO_MODEL]:
        lines.append("    " + json.dumps(row, default=str)[:600])
    if observation.total_rows > len(observation.rows):
        lines.append(f"    ... {observation.total_rows - len(observation.rows)}"
                     " more row(s) not shown")
    return "\n".join(lines)


def _args(arguments: dict[str, Any]) -> str:
    return ", ".join(f"{k}={v!r}" for k, v in arguments.items()
                     if v not in (None, "", [], {}))


def _catalogue(principal: Principal) -> str:
    lines = []
    for described in tools.describe_all(principal):
        arguments = ", ".join(
            f"{name} ({what})" for name, what in described["arguments"].items())
        required = (f"  [required: {', '.join(described['required'])}]"
                    if described["required"] else "")
        lines.append(f"- {described['name']}: {described['purpose']}\n"
                     f"    arguments: {arguments or 'none'}{required}")
    return "\n".join(lines)


# --------------------------------------------------------------- the loop


def investigate(question: str, principal: Principal, *,
                provider: Any = None, context: str = "",
                max_turns: int = safety.MAX_TURNS,
                max_tool_calls: int = safety.MAX_TOOL_CALLS) -> Investigation:
    """Run one governed investigation. §2.

    `provider` is anything with `backend.llm`'s `structured()`. Left out, the
    configured one is used; the tests pass a fake, and the loop cannot tell the
    difference, which is the point of the contract being one method.
    """
    started = time.perf_counter()
    found = Investigation(question=question)
    if provider is None:
        try:
            from backend.llm import get_provider

            provider = get_provider()
        except Exception as e:  # noqa: BLE001
            logger.warning("No provider for the analyst: %s", e)
            found.error = "no_provider"
            return found
    if not getattr(provider, "configured", False):
        found.error = "no_provider"
        return found

    catalogue = _catalogue(principal)
    asked_already = bool(context)
    calls = 0

    for turn in range(1, max_turns + 1):
        found.turns = turn
        prompt = _prompt(question, catalogue, found.ledger,
                         turns_left=max_turns - turn + 1,
                         asked_already=asked_already, context=context)
        try:
            result = provider.structured(
                system=SYSTEM, prompt=prompt, schema=DECISION_SCHEMA,
                tool_name="decide",
                tool_description="Your next step in this investigation.",
                max_tokens=3000, purpose="investigation", role="analyst")
        except Exception as e:  # noqa: BLE001 - a provider failure ends the loop
            logger.warning("The analyst's provider failed on turn %s: %s",
                           turn, e)
            found.error = "provider_failed"
            break

        decision = Decision.read(result.data or {})
        found.steps.append(decision)

        if decision.action == CALL_TOOL:
            if calls >= max_tool_calls:
                # Out of budget rather than out of ideas. Say so on the next
                # turn rather than silently answering on a partial gather.
                found.ledger.add(Observation(
                    tool=decision.tool, arguments=decision.arguments,
                    refused=("The evidence budget for this question is spent. "
                             "Answer on what you already have.")))
                continue
            observation = tools.call(principal, decision.tool,
                                     decision.arguments)
            observation.purpose = decision.why or observation.purpose
            found.ledger.add(observation)
            if not tools.BY_NAME.get(decision.tool, None) or \
                    not getattr(tools.BY_NAME.get(decision.tool), "discovery",
                                False):
                calls += 1
            continue

        if decision.action == ASK and not asked_already:
            found.outcome = ASK
            found.question_back = decision.question
            found.assumption = decision.assumption
            break

        if decision.action == ASK:
            # It has asked once already. §8: a question twice is not a
            # clarification, it is a refusal wearing one.
            continue

        if decision.action == ANSWER:
            found.outcome = ANSWER
            found.answer = decision.answer
            found.findings = decision.findings
            found.unavailable = decision.unavailable
            found.limitations = decision.limitations
            break

        if decision.action == CANNOT:
            # §7/§8. CANNOT is only honest when nothing was found. With
            # evidence in the ledger it is the model giving up on a question it
            # has partly answered, and the loop makes it finish.
            if found.ledger.observations and any(
                    o.ok and o.rows for o in found.ledger.observations):
                found.ledger.add(Observation(
                    tool="", refused=(
                        "You have governed evidence above. Answer on the part "
                        "it supports and name what is missing; do not refuse "
                        "the whole question.")))
                continue
            found.outcome = CANNOT
            found.answer = decision.why
            break

    else:
        # Out of turns with no answer. Not an error: everything gathered is
        # real, and the honest outcome is the partial one.
        found.outcome = ANSWER if found.ledger.observations else CANNOT
        found.answer = _fallback(found)

    _ground(found)
    found.duration_ms = int((time.perf_counter() - started) * 1000)
    return found


def _fallback(found: Investigation) -> str:
    """What to say when the loop ran out of turns mid-investigation."""
    if not found.ledger.observations:
        return ""
    datasets = ", ".join(found.ledger.datasets) or "the governed catalogue"
    return (f"This investigation reached its step limit after "
            f"{found.ledger.calls} governed queries over {datasets}. What it "
            "found is below; it is not a complete answer, and narrowing the "
            "question will finish it.")


def _ground(found: Investigation) -> None:
    """Remove figures no observation supports. §42.

    Removed rather than flagged. A sentence carrying a number nobody can check
    is not improved by a footnote saying so — it is read as a fact by everyone
    who skims, and skimming is what a credit committee does.
    """
    if not found.answer and not found.findings:
        return
    missing = found.ledger.ungrounded(found.answer)
    for finding in found.findings:
        missing.extend(found.ledger.ungrounded(finding))
    if not missing:
        return
    found.removed = sorted(set(missing))
    found.findings = [f for f in found.findings
                      if not found.ledger.ungrounded(f)]
    if found.ledger.ungrounded(found.answer):
        found.limitations.append(
            "One or more figures in the drafted answer could not be traced to "
            "a governed result and were removed. What remains is what the "
            "evidence supports.")
        found.answer = _strip(found.answer, found.removed)

    if not found.answer and found.ledger.observations:
        # Grounding removed the whole narrative. The evidence is still real
        # and the outcome is still an answer — saying nothing, or falling
        # through to another path as though the investigation had not
        # happened, would hide that a drafted answer was rejected. The reader
        # is told exactly that, and the table underneath is unaffected.
        found.answer = (
            f"CreditProbe ran {found.ledger.calls} governed "
            f"{'query' if found.ledger.calls == 1 else 'queries'} over "
            f"{', '.join(found.ledger.datasets) or 'the governed catalogue'}. "
            "The written reading of them could not be traced back to those "
            "results and was not shown. The figures below are the evidence "
            "itself.")


def _strip(text: str, numbers: list[str]) -> str:
    """Drop the sentences carrying an unsupported figure, keep the rest."""
    kept = []
    for sentence in text.replace("\n", " ").split(". "):
        if any(number in sentence for number in numbers):
            continue
        kept.append(sentence.strip())
    return ". ".join(s for s in kept if s).strip()


__all__ = ["ACTIONS", "ANSWER", "ASK", "CALL_TOOL", "CANNOT",
           "DECISION_SCHEMA", "Decision", "Investigation", "SESSION_VERSION",
           "SYSTEM", "investigate"]
