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
           packet: Any = None, ui_state: dict[str, Any] | None = None
           ) -> RollingSummary:
    """One update, from the supported final answer."""
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


__all__ = ["RECENT_TURNS", "SUMMARY_VERSION", "RollingSummary", "load",
           "update"]
