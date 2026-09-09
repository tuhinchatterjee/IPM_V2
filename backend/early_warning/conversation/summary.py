"""
What the next turn needs to know, and nothing else.

Why a summary rather than the transcript
----------------------------------------
"Open the weakest one" is a complete instruction when the previous turn
listed obligors and an unanswerable one otherwise. The thread has to carry
enough for that to resolve — but carrying the whole transcript means every
turn pays for every turn before it, and the useful part is small: which
population, which month, which obligor, which node, what was established,
what was proposed, what is still open.

One update, after the answer
-----------------------------
The summary is written once, from the SUPPORTED final answer. Not from a
provisional result, not from a repair attempt, not from a plan that failed
validation. A summary that recorded an intermediate state would carry a fact
into the next turn that the current turn decided not to state.

State lives in two places on purpose
-------------------------------------
This is the analytical context. The UI state — the filters, the selection,
the URL — is navigation context and is kept separately, because rebuilding a
screen from a prose summary is guesswork and the URL already knows.

The seam
--------
Where Sonnet is configured it writes the NARRATIVE parts of this summary: what
was established, what is still open, what to drill next. The structured
state — which obligor, which period, which filters, which node, which case —
stays deterministic, because it is what the next turn resolves "it" against
and a summary that named an obligor the data does not hold would make the
following turn answer about nobody.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: How many prior turns are kept in full alongside the summary.
RECENT_TURNS = 3

#: The summary contract version, so an older thread can be read safely.
SUMMARY_VERSION = "ews-summary-1"


@dataclass
class RollingSummary:
    """The analytical thread, compact enough to carry every turn."""

    version: str = SUMMARY_VERSION
    turns: int = 0
    #: What the thread is currently about.
    scope: str = ""
    period: str = ""
    comparison_period: str = ""
    filters: dict[str, Any] = field(default_factory=dict)
    customer_id: str = ""
    customer_name: str = ""
    segment: str = ""
    sector: str = ""
    region: str = ""
    band: str = ""
    layer: str = ""
    sub_category: str = ""
    signal: str = ""
    #: Facts already established, so a follow-up does not re-derive them.
    confirmed: list[str] = field(default_factory=list)
    #: Evidence the reader has already opened.
    evidence_opened: list[str] = field(default_factory=list)
    proposed_actions: list[str] = field(default_factory=list)
    case_id: str = ""
    escalation_state: str = ""
    investigation_id: str = ""
    artifacts: list[str] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)
    next_drills: list[str] = field(default_factory=list)
    engine: str = "deterministic"
    model_call: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version, "turns": self.turns,
            "scope": self.scope, "period": self.period,
            "comparison_period": self.comparison_period,
            "filters": dict(self.filters),
            "customer_id": self.customer_id,
            "customer_name": self.customer_name,
            "segment": self.segment, "sector": self.sector,
            "region": self.region,
            "band": self.band, "layer": self.layer,
            "sub_category": self.sub_category, "signal": self.signal,
            "confirmed": list(self.confirmed),
            "evidence_opened": list(self.evidence_opened),
            "proposed_actions": list(self.proposed_actions),
            "case_id": self.case_id,
            "escalation_state": self.escalation_state,
            "investigation_id": self.investigation_id,
            "artifacts": list(self.artifacts),
            "unresolved": list(self.unresolved),
            "next_drills": list(self.next_drills),
            "engine": self.engine,
            "model_call": dict(self.model_call),
        }


def load(stored: dict[str, Any] | None) -> RollingSummary:
    """Read a stored summary, whatever version wrote it.

    An older thread predates this contract and simply has fewer fields; it
    opens with what it has rather than failing, because a saved
    investigation that cannot be reopened is a saved investigation that was
    lost.
    """
    data = dict(stored or {})
    known = {f for f in RollingSummary().to_dict()}
    return RollingSummary(**{k: v for k, v in data.items() if k in known})


def update(previous: RollingSummary | None, *, question: str,
           request: Any, answer: dict[str, Any],
           packet: Any = None, ui_state: dict[str, Any] | None = None,
           ledger: Any = None) -> RollingSummary:
    """One update, from the supported final answer.

    The structured state is written deterministically and always. Where Sonnet
    is configured it then writes the narrative parts onto that.
    """
    out = _update_deterministic(previous, question=question, request=request,
                                answer=answer, packet=packet,
                                ui_state=ui_state)
    if ledger is None:
        return out
    return _summarised_by_model(out, question=question, answer=answer,
                                ledger=ledger)


def _update_deterministic(previous: RollingSummary | None, *, question: str,
                          request: Any, answer: dict[str, Any],
                          packet: Any = None,
                          ui_state: dict[str, Any] | None = None
                          ) -> RollingSummary:
    """The structured thread state. The part the next turn resolves against."""
    out = load(previous.to_dict() if previous else None)
    out.turns = (previous.turns if previous else 0) + 1
    ui = dict(ui_state or {})

    inherited = dict(getattr(request, "inherited_context", {}) or {})
    figures = dict(getattr(packet, "figures", {}) or {})

    out.scope = str(getattr(request, "requested_scope", "") or out.scope)
    out.period = (str(getattr(packet, "period", "") or "")
                  or str(ui.get("period") or "") or out.period)
    out.comparison_period = (str(getattr(packet, "comparison_period", "") or "")
                             or out.comparison_period)
    out.filters = dict(getattr(packet, "filters", None) or ui.get("filters")
                       or out.filters)

    # The obligor the thread is about. Carried forward rather than replaced,
    # so "escalate it" two turns later still knows what "it" is.
    for key in ("customer_id", "customer_name", "layer", "sub_category",
                "signal"):
        value = (figures.get(key) or inherited.get(key) or ui.get(key))
        if value:
            setattr(out, key, str(value))

    # `band` and `segment` are the SLICE the thread is looking at, not a
    # measurement of it. The packet also carries a `band` — the portfolio's
    # own computed severity — and reading that here overwrote the reader's
    # band filter with the answer to a different question. Two things with
    # one name is exactly how a thread starts describing the wrong scope, so
    # these come from the selection only.
    for key in ("segment", "sector", "region", "band"):
        value = inherited.get(key) or ui.get(key)
        if value:
            setattr(out, key, str(value))

    direct = str(answer.get("direct") or "").strip()
    if direct:
        out.confirmed = ([direct] + [c for c in out.confirmed
                                      if c != direct])[:RECENT_TURNS]

    if str(getattr(request, "requested_analysis", "")) == "evidence" \
            and out.signal:
        if out.signal not in out.evidence_opened:
            out.evidence_opened.append(out.signal)

    actions = list(getattr(packet, "governed_actions", None) or [])
    if actions:
        out.proposed_actions = [a.get("action", "") for a in actions[:3]]

    if getattr(request, "escalation_requested", False):
        out.escalation_state = "requested"

    out.next_drills = [str(f) for f in (answer.get("follow_ups") or [])][:4]
    out.unresolved = list(getattr(request, "ambiguities", None) or [])
    del question
    return out


# ---------------------------------------------- the narrative, under Sonnet

SYSTEM = """You maintain the rolling analytical summary of one Early Warning \
conversation in CreditProbe, a credit-risk platform used by banks.

The next turn will be a follow-up — "which names drive it?", "open the weakest \
one", "why did its score move?" — and it will be read against what you write \
here. Keep what a credit officer would need to make sense of that follow-up, \
and nothing else.

WHAT TO KEEP
- What has been established, in short factual lines. No adjectives.
- What is still open: a question asked and not answered, a part of the request \
the turn could not cover, an ambiguity nobody resolved.
- The next drills that follow naturally from where the conversation is.

RULES
- Only what the answer actually supports. You are not adding analysis.
- Never introduce a figure, an obligor, a period or a node that is not in the \
answer you were given.
- Short. This is carried on every subsequent turn."""

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "confirmed": {
            "type": "array", "items": {"type": "string"},
            "description": ("What this turn established, one short factual "
                            "line each. At most three."),
        },
        "unresolved": {
            "type": "array", "items": {"type": "string"},
            "description": "What is still open after this turn.",
        },
        "next_drills": {
            "type": "array", "items": {"type": "string"},
            "description": ("The questions that follow naturally from here, "
                            "each answerable by this product."),
        },
    },
    "required": ["confirmed"],
}


def _summarised_by_model(out: RollingSummary, *, question: str,
                         answer: dict[str, Any], ledger: Any
                         ) -> RollingSummary:
    import json

    from backend.early_warning.conversation import seam as seam_mod

    context = {
        "question": question,
        "answer": {k: answer.get(k) for k in
                   ("direct", "interpretation", "points", "drivers",
                    "follow_ups", "caveats", "answered", "scope", "complete")},
        "thread_state": out.to_dict(),
    }
    outcome = seam_mod.call(
        seam_mod.SUMMARY, system=SYSTEM,
        prompt=("Update the rolling summary of this thread.\n\n"
                + json.dumps(context, indent=2, default=str)),
        schema=SCHEMA, ledger=ledger)
    if not outcome.used_model:
        out.model_call = outcome.to_dict()
        return out

    data = outcome.data
    confirmed = [str(c).strip() for c in (data.get("confirmed") or [])
                 if str(c).strip()][:RECENT_TURNS]
    if confirmed:
        out.confirmed = confirmed
    drills = [str(d).strip() for d in (data.get("next_drills") or [])
              if str(d).strip()][:4]
    if drills:
        out.next_drills = drills
    # Unioned rather than replaced: an ambiguity the deterministic pass
    # recorded is still unresolved whether or not the model repeated it.
    for note in data.get("unresolved") or []:
        note = str(note).strip()
        if note and note not in out.unresolved:
            out.unresolved.append(note)
    out.engine = seam_mod.MODEL
    out.model_call = outcome.to_dict()
    return out


__all__ = ["RECENT_TURNS", "SCHEMA", "SUMMARY_VERSION", "SYSTEM",
           "RollingSummary", "load", "update"]
