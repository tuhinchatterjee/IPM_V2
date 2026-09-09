"""
Opus: ownership, planning, authorship, repair and review.
Specification sections 6, 7.5, 7.8, 8 and 13.

One conversation, not four calls
--------------------------------
The gate, the plan, every repair and the review are turns of ONE conversation.
That is not an optimisation: section 8.1 requires every repair continuation to
carry the full effective context, and threading the messages is how the
catalogue, the approved ownership decision and the plan stay present without
being re-serialized into each error. The assistant's own blocks go back
verbatim, in order, because that is what the provider requires and what makes
the continuation the same conversation rather than a new one.

Section 6.2 permits the first response to carry both the functionality decision
and a candidate plan, so long as the gate is logically first and CreditProbe
approves before anything executes. It does, and it is: `runtime` checks
`decision.may_execute` and issues a server-side permission before a single
statement reaches the engine, and a referral response is required to carry no
executable plan at all.

What is not here
----------------
No method vocabulary, no template, no canned analysis. The schemas describe the
SHAPE of a plan and a submission — subquestions, fields, steps, code — and say
nothing about what the analysis should be. `AnalysisPlan.method_summary` is
free text. That is the difference between a contract and the template this
architecture removes.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from typing import Any

from backend.cockpit_agentic import UNTRUSTED_NOTE
from backend.cockpit_agentic import contracts as K
from backend.cockpit_agentic import models as models_mod
from backend.cockpit_agentic import tokens as tokens_mod
from backend.cockpit_agentic.context import CockpitContextPacket
from backend.cockpit_agentic.ledger import Ledger
from backend.cockpit_agentic.sonnet import prompt

logger = logging.getLogger(__name__)

OPUS_ROLE = "cockpit_reasoning"
OPUS_FAMILY = "opus"


class OpusUnavailable(RuntimeError):
    """No provider, or the provider cannot hold a conversation.

    Raised and reported. There is no deterministic substitute for a
    model-authored analysis, and section 17 forbids inventing one.
    """


# ------------------------------------------------------------------ schemas

_SCORE = {
    "type": "object",
    "properties": {
        "functionality_id": {"type": "string"},
        "score": {"type": "integer", "minimum": 0, "maximum": 100},
        "justification": {"type": "string"},
    },
    "required": ["functionality_id", "score", "justification"],
}

_ALTERNATIVE = {
    "type": "object",
    "properties": {
        "question": {"type": "string"},
        "required_fields": {"type": "array", "items": {"type": "string"},
                            "minItems": 1},
        "available_periods": {"type": "array", "items": {"type": "string"}},
        "limitation": {"type": "string"},
    },
    "required": ["question", "required_fields"],
}

_PLAN = {
    "type": "object",
    "properties": {
        "plan_id": {"type": "string"},
        "subquestions": {"type": "array", "items": {"type": "string"}},
        "fields_required": {"type": "array", "items": {"type": "string"}},
        "joins_required": {"type": "array", "items": {"type": "string"}},
        "steps": {"type": "array", "items": {"type": "string"}},
        "assumptions": {"type": "array", "items": {"type": "string"}},
        "missingness_handling": {"type": "string"},
        "expected_output_grain": {"type": "string"},
        "expected_units": {"type": "string"},
        # Free text on purpose. There is no method vocabulary and no enum:
        # constraining this field would be the template this architecture
        # exists to remove.
        "method_summary": {"type": "string"},
        "alternative_method": {"type": "string"},
    },
    "required": ["plan_id", "subquestions", "method_summary"],
}

_STEP = {
    "type": "object",
    "properties": {
        "step_id": {"type": "string"},
        "language": {"type": "string", "enum": ["sql"]},
        "code": {"type": "string",
                 "description": "Exactly one SELECT statement."},
        "purpose": {"type": "string"},
    },
    "required": ["step_id", "language", "code"],
}

_TABLE = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "columns": {"type": "array", "items": {"type": "string"}},
        "rows": {"type": "array", "items": {"type": "array"}},
        "units": {"type": "object", "additionalProperties": {"type": "string"}},
        "fact_ids": {"type": "array", "items": {"type": "string"}},
        "note": {"type": "string"},
    },
    "required": ["title", "columns", "rows"],
}

_CHART = {
    "type": "object",
    "properties": {
        "kind": {"type": "string",
                 "enum": ["bar", "line", "waterfall", "scatter"]},
        "title": {"type": "string"},
        "series": {"type": "array", "items": {"type": "object",
                                              "additionalProperties": True}},
        "x_label": {"type": "string"},
        "y_label": {"type": "string"},
        "unit": {"type": "string"},
        "fact_ids": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["kind", "title"],
}

_ANSWER = {
    "type": "object",
    "properties": {
        "narrative": {"type": "string"},
        "complete": {"type": "boolean"},
        "approximate": {"type": "boolean"},
        "tables": {"type": "array", "items": _TABLE},
        "charts": {"type": "array", "items": _CHART},
        "findings": {
            "type": "array", "items": {"type": "string"},
            "description": "What the analysis found, one statement each. "
                           "Every figure in these must come from an executed "
                           "result."},
        "suggested_questions": {
            "type": "array", "items": {"type": "string"}, "maxItems": 4,
            "description": "Cockpit questions the user could ask next. They "
                           "are checked against the actual field catalogue "
                           "and the available quarters, and any that names "
                           "something this domain does not have is dropped "
                           "without being repaired."},
        "limitations": {"type": "array", "items": {"type": "string"}},
        "assumptions": {"type": "array", "items": {"type": "string"}},
        "hypotheses": {
            "type": "array", "items": {"type": "string"},
            "description": "Claims the evidence supports only as "
                           "association. Never stated as cause."},
        "fact_ids": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["narrative"],
}

#: The answer-only rewrite, section 29. Deliberately carries no plan and no
#: steps: this turn cannot execute, so a schema that let it propose code would
#: be offering something the runtime will refuse.
REWRITE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"answer": _ANSWER,
                   "what_was_wrong": {"type": "string"}},
    "required": ["answer"],
}

GATE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "scores": {"type": "array", "items": _SCORE, "minItems": 6},
        "best_fit": {"type": "string"},
        "requested_actions": {"type": "array", "items": {"type": "string"}},
        "relevant_exclusions": {"type": "array", "items": {"type": "string"}},
        "decision": {"type": "string",
                     "enum": list(K.DECISIONS)},
        "query_mode": {
            "type": "string", "enum": list(K.QUERY_MODES),
            "description": (
                "What KIND of request this is, decided fresh for this turn. "
                "PRODUCT_HELP: about CreditProbe itself. THEORY_CONCEPT: what "
                "a credit or accounting term means, with no reference to this "
                "book's numbers. DATA_ANALYSIS: needs the stored portfolio -- "
                "including a question that asks for BOTH an explanation and "
                "the numbers. OTHER_FUNCTIONALITY: another module owns it. "
                "CLARIFICATION_REQUIRED: it cannot be answered without a "
                "choice only the user can make. UNSUPPORTED: nothing here "
                "owns it, including anything about current external events, "
                "which must never be answered from memory.")},
        "owner": {"type": "string", "enum": list(K.OWNERS)},
        "requires_cockpit_data": {"type": "boolean"},
        "requires_sql": {"type": "boolean"},
        "requires_python": {"type": "boolean"},
        "decision_reason": {"type": "string"},
        "ambiguity": {"type": "string"},
        "answer": _ANSWER,
        "mixed_scope": {"type": "boolean"},
        "mixed_scope_explanation": {"type": "string"},
        "public_explanation": {"type": "string"},
        "referral_destination": {"type": "string"},
        "referral_reason": {"type": "string"},
        "alternatives": {"type": "array", "items": _ALTERNATIVE,
                         "maxItems": 3},
        "clarification_question": {"type": "string"},
        "clarification_options": {"type": "array", "items": {"type": "string"}},
        "plan": _PLAN,
        "steps": {"type": "array", "items": _STEP},
    },
    "required": ["scores", "decision", "public_explanation"],
}

REPAIR_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "action": {"type": "string",
                   "enum": ["submit_repaired_code", "revise_the_analysis_plan",
                            "ask_a_targeted_clarification",
                            "explain_and_stop"]},
        "what_went_wrong": {"type": "string"},
        "plan": _PLAN,
        "steps": {"type": "array", "items": _STEP},
        "clarification_question": {"type": "string"},
        "clarification_options": {"type": "array", "items": {"type": "string"}},
        "explanation": {"type": "string"},
    },
    "required": ["action"],
}

REVIEW_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "decision": {"type": "string", "enum": list(K.REVIEW_DECISIONS)},
        "per_subquestion": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "subquestion": {"type": "string"},
                    "answered": {"type": "boolean"},
                    "evidence_fact_ids": {"type": "array",
                                          "items": {"type": "string"}},
                    "gap": {"type": "string"},
                },
                "required": ["subquestion", "answered"],
            }},
        "gap_addressed": {"type": "string"},
        "plan": _PLAN,
        "steps": {"type": "array", "items": _STEP},
        "clarification_question": {"type": "string"},
        "clarification_options": {"type": "array", "items": {"type": "string"}},
        "answer": _ANSWER,
    },
    "required": ["decision"],
}


# ----------------------------------------------------------- the conversation

class Conversation:
    """One Opus conversation for one user request.

    Holds the message list and threads the assistant's own blocks back into it
    verbatim. Nothing here interprets a block: the provider gave it, the
    provider gets it back.
    """

    def __init__(self, *, provider: Any, ledger: Ledger,
                 packet: CockpitContextPacket, model: str = "") -> None:
        if provider is None or not hasattr(provider, "converse"):
            raise OpusUnavailable(
                "This runtime has no provider that can hold a multi-turn "
                "conversation, so the Cockpit cannot plan, author or repair an "
                "analysis. This is reported rather than substituted: there is "
                "no deterministic stand-in for a model-authored analysis, and "
                "presenting one would misrepresent what the system did.")
        self.provider = provider
        self.ledger = ledger
        self.packet = packet
        self.messages: list[dict[str, Any]] = []
        self.turns: list[dict[str, Any]] = []
        self.counts: list[dict[str, Any]] = []
        #: A hook the runtime sets for a repair turn: it is handed the fully
        #: assembled request and may refuse it. Nothing else reads the outbound
        #: request, and nothing may modify it -- this is an inspection point,
        #: not an editing point.
        self.before_dispatch: Any = None
        self._pending = ""
        self.counter = tokens_mod.Counter(provider=provider, model=model)

    # -- the system prompt, and where the cache breakpoint goes ---------

    def system(self, contract: str) -> list[dict[str, Any]]:
        """System blocks, stable prefix first, with ONE cache breakpoint.

        Caching is a prefix match: any byte change anywhere before the
        breakpoint invalidates everything after it. So the blocks are ordered
        most-stable first and the breakpoint sits at the end of the last block
        that does not change within a request:

          1. the architecture instructions and the Cockpit-only restriction --
             identical for every request in this deployment;
          2. the pinned domain context: the complete compact field catalogue,
             the grains, the join definitions, the functionality registry and
             the execution contract -- identical for every turn of THIS
             request, because the release is pinned for its lifetime;
          3. <- cache breakpoint here.

        Everything that moves between turns -- the question, the Sonnet
        outputs, the filters, the thread summary, the plan, prior results, the
        failed code, the diagnostics, the remaining budgets -- lives in
        `messages`, after the breakpoint. That is what makes the repair turns
        of one request cache hits rather than four full re-reads of a
        22,000-token catalogue.

        Caching is an OPTIMISATION AND NOTHING ELSE. The catalogue is sent in
        full on every request whether it is served from cache or not; there is
        no hash, no id and no reference Opus would have to resolve. Section 8.1
        is satisfied by the content being present, not by it being cheap.
        """
        packet = self.packet.payload
        pinned = {
            "domain_id": packet["B_scope"]["domain_id"],
            "dataset_release_id": packet["B_scope"]["dataset_release_id"],
            "reporting_currency": packet["B_scope"]["reporting_currency"],
            "amount_scale": packet["B_scope"]["amount_scale"],
            "catalogue": packet["D_E_catalogue"],
            "functionalities": packet["H_functionalities"],
            "execution_capabilities": packet["I_execution"],
        }
        return [
            # 1. Invariant for every request in this deployment.
            {"type": "text", "text": prompt("shared_preamble")},
            # 2. Invariant for every TURN of this request: the release is
            #    pinned for its lifetime.
            {"type": "text",
             "text": ("THE AUTHORIZED COCKPIT DOMAIN FOR THIS REQUEST.\n"
                      "The complete field dictionary, the grains, the joins, "
                      "the functionality registry and the execution contract. "
                      "This is pinned for the lifetime of this request and is "
                      "sent in full on every turn -- it is never abridged, "
                      "hashed or replaced by a reference.\n\n"
                      + json.dumps(pinned, separators=(",", ":"),
                                   default=str)),
             # 3. The one breakpoint. Everything above is byte-identical
             #    across the turns of this request; everything below moves.
             "cache_control": {"type": "ephemeral"}},
            # 4. The contract for THIS turn -- planning, repair or review. It
            #    changes between turns, so it must sit AFTER the breakpoint:
            #    putting it first made every turn a cache miss, which is what
            #    test_the_prefix_is_byte_identical_across_every_turn caught.
            {"type": "text", "text": prompt(contract)},
            {"type": "text", "text": UNTRUSTED_NOTE},
        ]

    def opening_context(self) -> str:
        """The dynamic half of the context, as the first user message.

        Sections A, B's request-specific scope, C, F, G and J: the question in
        all three forms, the effective scope, the thread, the measured
        coverage, the sample rows and the remaining budget. All of it changes
        between requests -- and F and J change between the TURNS of a request --
        so none of it belongs in the cached prefix.
        """
        packet = self.packet.payload
        dynamic = {
            "request": packet["A_request"],
            "scope_and_filters": {
                k: v for k, v in packet["B_scope"].items()
                if k not in ("domain_id", "dataset_release_id",
                             "reporting_currency", "amount_scale")},
            "thread": packet["C_thread"],
            "measured_coverage": packet["F_coverage"],
            "sample_rows": packet["G_samples"],
            "remaining_budget": packet["J_budget"],
        }
        return ("THE REQUEST, ITS SCOPE, THE MEASURED COVERAGE AND THE "
                "REMAINING BUDGET.\n\n"
                + json.dumps(dynamic, separators=(",", ":"), default=str))

    # -- one turn ------------------------------------------------------

    def ask(self, *, contract: str, user: str, schema: dict[str, Any],
            tool_name: str, description: str, purpose: str,
            max_tokens: int = 0, finalization: bool = False
            ) -> dict[str, Any]:
        """One counted, reserved, settled turn that must answer through the tool.

        Counted first. Section 9.3 and the owner's instruction: the assembled
        request is measured against the model that will serve it, and refused
        before dispatch if it will not fit with room for the answer. A request
        that fails at the provider for size has spent latency and told the user
        nothing.
        """
        # The reasoning model id, resolved fresh and refused if absent. Every
        # analytical decision in this application is made here, so the one
        # thing that must never happen is this call reaching the provider with
        # an empty model and being served by whatever the SDK ships with.
        resolved = models_mod.resolve()
        model = models_mod.require(resolved.reasoning,
                                   role=models_mod.REASONING_ROLE)
        effort = (os.environ.get("AI_COCKPIT_REASONING_EFFORT")
                  or "").strip().lower()
        limit = max_tokens or self.ledger.limits.max_opus_output_tokens
        system_blocks = self.system(contract)

        if not self.messages:
            # The dynamic context opens the conversation, after the cached
            # prefix, so the catalogue above it stays byte-identical.
            self.messages.append({"role": "user",
                                  "content": self.opening_context()})
        pending = self.messages + [{"role": "user", "content": user}]
        tool = {"name": tool_name, "description": description,
                "input_schema": schema}

        # Section 8.1: read the request that is about to go out, not a log of
        # what was intended. A missing part of the effective context stops the
        # dispatch -- asking Opus to repair code it cannot see would produce
        # something shaped like a repair and arrived at by guessing.
        if self.before_dispatch is not None:
            self.before_dispatch(system_blocks, pending, [tool])

        counted = self.counter.fits(
            system=system_blocks, messages=pending, tools=[tool],
            cap=self.ledger.limits.max_input_tokens_per_call,
            reserve_output=limit)
        self.counts.append({"purpose": purpose, **counted.to_dict()})

        reservation = self.ledger.reserve(
            role=OPUS_ROLE, family=OPUS_FAMILY, purpose=purpose,
            input_tokens=counted.tokens, max_output_tokens=limit,
            finalization=finalization)

        self.messages = pending
        try:
            result = self.provider.converse(
                system=system_blocks, messages=self.messages, tools=[tool],
                max_tokens=limit, model=model, purpose=purpose,
                role=OPUS_ROLE, effort=effort,
                timeout=max(1.0, self.ledger.remaining_seconds))
        except Exception as e:                              # noqa: BLE001
            self.ledger.settle(reservation, output_tokens=0, error=str(e),
                               uncertain=True)
            raise

        self.ledger.settle(
            reservation, input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            cache_read_tokens=result.cache_read_tokens,
            cache_write_tokens=result.cache_write_tokens)

        # The assistant's own blocks go back verbatim, in order. A tool_use
        # block MUST be answered by a matching tool_result on the next turn,
        # which `answer_tool` does.
        if result.assistant_blocks:
            self.messages.append({"role": "assistant",
                                  "content": result.assistant_blocks})

        self.turns.append({
            "purpose": purpose, "stop_reason": result.stop_reason,
            "tool_calls": len(result.tool_calls),
            "truncated": result.truncated,
            "counted_input_tokens": counted.tokens,
            "count_method": counted.method,
            "reported_input_tokens": result.input_tokens,
            "cache_read_tokens": result.cache_read_tokens,
            "cache_write_tokens": result.cache_write_tokens})

        if result.truncated:
            # Section 9.1: a truncated output is INCOMPLETE, not a shorter
            # answer. Treating half a plan as a plan is how a confident wrong
            # analysis gets built.
            raise OpusUnavailable(
                f"The model's response was cut off at its {limit}-token output "
                f"limit, so the {purpose} is incomplete. A truncated plan is "
                f"half a plan, not a smaller one.")

        for call in result.tool_calls:
            if call["name"] == tool_name:
                self._pending = call["id"]
                return dict(call["input"])

        raise OpusUnavailable(
            f"The model answered in prose rather than through {tool_name}: "
            f"{result.text[:200] or '(nothing)'}")

    def answer_tool(self, payload: str) -> None:
        """Pair the last tool_use with its tool_result, in order.

        Required by the provider and required by section 8.1's "keep the
        assistant tool-use and corresponding tool-result blocks paired and
        ordered correctly".
        """
        pending = getattr(self, "_pending", "")
        if not pending:
            return
        self.messages.append({
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": pending,
                         "content": payload}]})
        self._pending = ""


# ------------------------------------------------------------- the three jobs

def envelope_from(raw: Any, *, kind: str = "answer"
                  ) -> K.AnswerEnvelope | None:
    """Build an answer envelope from the model's structured output.

    Shared by the gate (which answers PRODUCT_HELP and THEORY_CONCEPT in its
    own turn), the sufficiency review, and the single answer rewrite -- one
    builder, so the three cannot drift into carrying different fields.
    """
    if not isinstance(raw, dict) or not raw.get("narrative"):
        return None
    return K.AnswerEnvelope(
        kind=str(raw.get("kind") or kind),
        narrative=str(raw["narrative"]),
        complete=bool(raw.get("complete", True)),
        approximate=bool(raw.get("approximate", False)),
        tables=[K.AnswerTable(
            title=str(t.get("title") or ""),
            columns=[str(c) for c in (t.get("columns") or [])],
            rows=[list(r) for r in (t.get("rows") or [])],
            units={str(k): str(v) for k, v in (t.get("units") or {}).items()},
            fact_ids=[str(f) for f in (t.get("fact_ids") or [])],
            note=str(t.get("note") or ""))
            for t in (raw.get("tables") or [])],
        charts=[K.AnswerChart(
            kind=str(c.get("kind") or "bar"),
            title=str(c.get("title") or ""),
            series=[dict(x) for x in (c.get("series") or [])],
            x_label=str(c.get("x_label") or ""),
            y_label=str(c.get("y_label") or ""),
            unit=str(c.get("unit") or ""),
            fact_ids=[str(f) for f in (c.get("fact_ids") or [])])
            for c in (raw.get("charts") or [])],
        findings=[str(x) for x in (raw.get("findings") or [])],
        suggested_questions=[str(x) for x in
                             (raw.get("suggested_questions") or [])],
        limitations=[str(x) for x in (raw.get("limitations") or [])],
        assumptions=[str(x) for x in (raw.get("assumptions") or [])],
        hypotheses=[str(x) for x in (raw.get("hypotheses") or [])],
        fact_ids=[str(f) for f in (raw.get("fact_ids") or [])])


def gate_and_plan(conversation: Conversation, packet: CockpitContextPacket
                  ) -> tuple[K.FunctionalityDecision, K.AnalysisPlan | None,
                             K.ExecutionSubmission | None]:
    """Opus's first responsibility: who owns this, and only then, how.

    Returns the decision, and a plan and submission ONLY on the PROCEED branch.
    A referral or a clarification carries no executable plan -- section 7.5 --
    and this function drops one if the model supplies it anyway rather than
    letting it reach the validator.
    """
    request = packet.payload["A_request"]
    user = "\n\n".join([
        "Decide who owns this request, and only then how to answer it.",
        f"ORIGINAL: {request['original_question']}",
        f"BUSINESS REQUEST: {request['business_request']}",
        "SUBQUESTIONS:\n" + "\n".join(f"- {s}" for s in request["subquestions"]),
        ("UNRESOLVED AMBIGUITY (do not resolve it by guessing):\n"
         + "\n".join(f"- {a}" for a in request["unresolved_ambiguity"])
         if request["unresolved_ambiguity"] else
         "No ambiguity was flagged by the preprocessing passes."),
        ("FIRST decide the query_mode for THIS turn. Do not carry it over "
         "from the previous turn: a thread that has been discussing what "
         "lifetime PD means can turn to which borrowers' lifetime PD moved, "
         "and those are different modes."),
        ("PRODUCT_HELP and THEORY_CONCEPT answer from knowledge. Put your "
         "complete answer in `answer` in THIS response: no query runs and "
         "there is no second call. For THEORY_CONCEPT you may use general, "
         "stable credit and accounting knowledge -- but a question about how "
         "CREDITPROBE specifically does something is only answerable from the "
         "product information in this packet, and if it is not there, say it "
         "cannot be verified rather than describing what such a system "
         "usually does."),
        ("A question that asks BOTH what something means AND what this book "
         "shows is DATA_ANALYSIS, not THEORY_CONCEPT. Both halves are owed an "
         "answer."),
        ("Anything about current or recent external events -- announcements, "
         "today's rates, market news -- is UNSUPPORTED unless a configured "
         "functionality here genuinely owns it. It must never be answered "
         "from memory."),
        ("Then score every functionality in the registry. If the Cockpit is "
         "not the unique highest scorer, or the action is outside its "
         "ownership, refer or clarify and include NO executable plan. If it "
         "is, include your analysis plan and the SQL for its first step."),
    ])

    data = conversation.ask(
        contract="opus_gate_and_plan", user=user, schema=GATE_SCHEMA,
        tool_name="functionality_decision",
        description="Which functionality owns this request, and -- only if it "
                    "is the Cockpit -- the analysis plan and its SQL.",
        purpose="opus_gate_and_plan")

    scores = [K.SuitabilityScore(
        functionality_id=str(s.get("functionality_id") or ""),
        score=int(s.get("score") or 0),
        justification=str(s.get("justification") or ""))
        for s in (data.get("scores") or [])]

    alternatives = [K.AlternativeQuestion(
        question=str(a.get("question") or ""),
        required_fields=[str(f) for f in (a.get("required_fields") or [])],
        available_periods=[str(p) for p in (a.get("available_periods") or [])],
        limitation=str(a.get("limitation") or ""))
        for a in (data.get("alternatives") or [])[:3]
        if a.get("question") and a.get("required_fields")]

    destination = str(data.get("referral_destination") or "")
    route, enabled = "", False
    if destination:
        from backend.cockpit_agentic import registry

        try:
            target = registry.entry(destination)
            route, enabled = target.route, target.enabled
        except LookupError:
            route, enabled = "", False

    mode = str(data.get("query_mode") or "")
    owner = str(data.get("owner") or "")
    raw_decision = str(data.get("decision") or K.CLARIFY_FUNCTIONALITY)

    # The mode is the semantic answer and `decision` is what the server does
    # about it. Where the model gives both and they disagree, the MODE wins:
    # it is the more specific statement, and a decision to execute alongside a
    # mode that executes nothing is a contradiction the runtime must not have
    # to resolve later.
    if mode in K.NO_EXECUTION_MODES:
        raw_decision = K.ANSWER_WITHOUT_DATA
    elif mode == K.OTHER_FUNCTIONALITY:
        raw_decision = K.REDIRECT
    elif mode == K.CLARIFICATION_REQUIRED:
        raw_decision = K.CLARIFY_FUNCTIONALITY
    elif mode == K.UNSUPPORTED_MODE:
        raw_decision = K.UNSUPPORTED_REQUEST

    answer = envelope_from(
        data.get("answer"),
        kind="explanation" if mode in K.NO_EXECUTION_MODES else "answer")
    if mode in K.NO_EXECUTION_MODES and answer is None:
        # The mode promises an answer in this turn. Without one there is
        # nothing to render and no second call coming, so it becomes a
        # clarification rather than an empty success.
        mode = K.CLARIFICATION_REQUIRED
        raw_decision = K.CLARIFY_FUNCTIONALITY

    decision = K.FunctionalityDecision(
        decision=raw_decision,
        query_mode=mode, owner=owner,
        requires_cockpit_data=bool(data.get("requires_cockpit_data")),
        requires_sql=bool(data.get("requires_sql"))
        if mode not in K.NO_EXECUTION_MODES else False,
        requires_python=bool(data.get("requires_python"))
        if mode not in K.NO_EXECUTION_MODES else False,
        decision_reason=str(data.get("decision_reason") or ""),
        ambiguity=str(data.get("ambiguity") or ""),
        answer=answer,
        scores=scores, best_fit=str(data.get("best_fit") or ""),
        requested_actions=[str(a) for a in (data.get("requested_actions") or [])],
        relevant_exclusions=[str(x) for x in
                             (data.get("relevant_exclusions") or [])],
        mixed_scope=bool(data.get("mixed_scope")),
        mixed_scope_explanation=str(data.get("mixed_scope_explanation") or ""),
        referral_destination=destination,
        referral_reason=str(data.get("referral_reason") or ""),
        referral_route=route, referral_enabled=enabled,
        alternatives=alternatives,
        clarification_question=str(data.get("clarification_question") or ""),
        clarification_options=[str(o) for o in
                               (data.get("clarification_options") or [])],
        public_explanation=str(data.get("public_explanation") or ""))

    if not decision.may_execute:
        # Section 7.5, and sections 10 and 11: a referral, a clarification, a
        # product-help answer and a theory answer all contain no executable
        # analysis plan. If one arrived anyway it is discarded HERE, before
        # anything downstream could act on it.
        if data.get("steps") or data.get("plan"):
            logger.info("A non-executing decision carried an executable plan; "
                        "it was discarded at the gate.")
        return decision, None, None

    plan = _plan_from(data.get("plan"), decision)
    submission = _submission_from(data.get("steps"), plan=plan,
                                  analysis_round=1, submission_number=0)
    return decision, plan, submission


def _plan_from(raw: Any, decision: K.FunctionalityDecision
               ) -> K.AnalysisPlan | None:
    if not isinstance(raw, dict):
        return None
    return K.AnalysisPlan(
        plan_id=str(raw.get("plan_id") or f"plan-{uuid.uuid4().hex[:6]}"),
        subquestions=[str(s) for s in (raw.get("subquestions") or [])]
        or ["(unstated)"],
        fields_required=[str(f) for f in (raw.get("fields_required") or [])],
        joins_required=[str(j) for j in (raw.get("joins_required") or [])],
        steps=[str(s) for s in (raw.get("steps") or [])],
        assumptions=[str(a) for a in (raw.get("assumptions") or [])],
        missingness_handling=str(raw.get("missingness_handling") or ""),
        expected_output_grain=str(raw.get("expected_output_grain") or ""),
        expected_units=str(raw.get("expected_units") or ""),
        method_summary=str(raw.get("method_summary") or ""),
        alternative_method=str(raw.get("alternative_method") or ""))


def _submission_from(raw: Any, *, plan: K.AnalysisPlan | None,
                     analysis_round: int, submission_number: int
                     ) -> K.ExecutionSubmission | None:
    if not raw or not isinstance(raw, list):
        return None
    steps = [K.ExecutionStep(
        step_id=str(s.get("step_id") or f"step-{i + 1}"),
        language=str(s.get("language") or "sql"),
        code=str(s.get("code") or ""),
        purpose=str(s.get("purpose") or ""))
        for i, s in enumerate(raw) if str(s.get("code") or "").strip()]
    if not steps:
        return None
    return K.ExecutionSubmission(
        submission_id=f"sub-{uuid.uuid4().hex[:8]}",
        plan_id=plan.plan_id if plan else "plan-1",
        analysis_round=analysis_round, submission_number=submission_number,
        steps=steps, authored_by="opus")


def repair(conversation: Conversation, packet_failure: K.ExecutionFailurePacket,
           *, plan: K.AnalysisPlan | None, analysis_round: int
           ) -> dict[str, Any]:
    """Hand back the facts and let Opus author the next candidate.

    Everything in this function is a report. Nothing in it is a repair, and
    there is no branch that writes SQL.
    """
    import json

    conversation.answer_tool(json.dumps(packet_failure.to_dict(), default=str))

    user = "\n\n".join([
        "Your query did not run. The exact failure is in the tool result "
        "above, with the fields that DO exist, the valid filter values, the "
        "results you already have and what you have already tried.",
        "CreditProbe has not edited your SQL and will not. The next candidate "
        "comes from you.",
        f"Permitted next actions: "
        f"{', '.join(packet_failure.permitted_next_actions)}.",
        (f"Submissions remaining: "
         f"{packet_failure.budget.get('submissions_remaining')}. "
         f"Analysis rounds remaining: "
         f"{packet_failure.budget.get('analysis_rounds_remaining')}. "
         f"Seconds remaining: "
         f"{packet_failure.budget.get('seconds_remaining')}."),
        ("Do not resubmit the same query: an identical candidate is blocked "
         "before execution. Do not change the user's question to make it "
         "executable."),
    ])

    data = conversation.ask(
        contract="opus_repair", user=user, schema=REPAIR_SCHEMA,
        tool_name="repair_decision",
        description="What you make of the failure, and the next candidate if "
                    "there is one.",
        purpose="opus_repair")

    revised_plan = _plan_from(data.get("plan"), None) or plan
    submission = _submission_from(data.get("steps"), plan=revised_plan,
                                  analysis_round=analysis_round,
                                  submission_number=0)
    return {"action": str(data.get("action") or "explain_and_stop"),
            "what_went_wrong": str(data.get("what_went_wrong") or ""),
            "plan": revised_plan, "submission": submission,
            "clarification_question": str(
                data.get("clarification_question") or ""),
            "clarification_options": [
                str(o) for o in (data.get("clarification_options") or [])],
            "explanation": str(data.get("explanation") or "")}


def review(conversation: Conversation, result: K.ExecutionResultPacket, *,
           plan: K.AnalysisPlan | None, analysis_round: int
           ) -> K.AnalysisReviewDecision:
    """Sufficiency review, and the final answer when the evidence supports one."""
    import json

    conversation.answer_tool(json.dumps(result.to_dict(), default=str))

    user = "\n\n".join([
        "The results are in the tool result above. Decide whether they answer "
        "the question, subquestion by subquestion.",
        ("A zero-row result means nothing matched. It does not mean the "
         "quantity is zero. A clipped table is not a complete aggregate."),
        ("Every figure in your answer must come from a result you were given. "
         "Report anything the evidence supports only as association as a "
         "hypothesis, never as a cause."),
        (f"Analysis rounds remaining: "
         f"{result.budget.get('analysis_rounds_remaining')}. Submissions "
         f"remaining: {result.budget.get('submissions_remaining')}. If you "
         f"revise, include the changed plan and the new SQL."),
    ])

    data = conversation.ask(
        contract="opus_review_and_answer", user=user, schema=REVIEW_SCHEMA,
        tool_name="review_and_answer",
        description="Whether the evidence suffices, and the answer if it does.",
        purpose="opus_review")

    per_subquestion = [K.SubquestionEvidence(
        subquestion=str(s.get("subquestion") or ""),
        answered=bool(s.get("answered")),
        evidence_fact_ids=[str(f) for f in (s.get("evidence_fact_ids") or [])],
        gap=str(s.get("gap") or ""))
        for s in (data.get("per_subquestion") or [])]

    decision = str(data.get("decision") or K.INSUFFICIENT_DATA)
    revised_plan = _plan_from(data.get("plan"), None) or plan
    submission = _submission_from(data.get("steps"), plan=revised_plan,
                                  analysis_round=analysis_round + 1,
                                  submission_number=0)

    envelope = envelope_from(data.get("answer"))

    if decision == K.REVISE_ANALYSIS and submission is None:
        # The contract refuses a revision with no code, and refusing it here
        # with a clear reason beats letting the dataclass raise later.
        decision = K.INSUFFICIENT_DATA

    return K.AnalysisReviewDecision(
        decision=decision, per_subquestion=per_subquestion,
        revised_plan=revised_plan, revised_submission=submission,
        gap_addressed=str(data.get("gap_addressed") or ""),
        clarification_question=str(data.get("clarification_question") or ""),
        clarification_options=[str(o) for o in
                               (data.get("clarification_options") or [])],
        answer=envelope)


def rewrite_answer(conversation: Conversation, envelope: K.AnswerEnvelope,
                   instruction: str) -> K.AnswerEnvelope | None:
    """The ONE answer-only rewrite permitted by section 29.

    It cannot execute, cannot open an analysis round and cannot reset a
    counter -- and it is not given the means to: the schema carries no plan
    and no steps, and the caller discards anything else that arrives.

    CreditProbe does not edit the prose. It says what did not check out and
    hands the answer back.
    """
    user = "\n\n".join([
        instruction,
        "YOUR ANSWER, EXACTLY AS YOU WROTE IT:",
        json.dumps(envelope.to_dict(), default=str),
    ])
    data = conversation.ask(
        contract="opus_answer_rewrite", user=user, schema=REWRITE_SCHEMA,
        tool_name="rewritten_answer",
        description="The corrected answer. No code, no new analysis.",
        purpose="opus_answer_rewrite", finalization=True)
    return envelope_from(data.get("answer"), kind=envelope.kind)


__all__ = ["Conversation", "GATE_SCHEMA", "OPUS_ROLE", "OpusUnavailable",
           "REWRITE_SCHEMA", "envelope_from", "rewrite_answer",
           "REPAIR_SCHEMA", "REVIEW_SCHEMA", "gate_and_plan", "repair",
           "review"]
