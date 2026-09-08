"""
Thread continuity in the restricted domain. Specification section 12.

A recent exchange is one COMPLETE question and its final answer, referral or
clarification — not one message. At question twenty the default context is
question twenty, the stored rolling summary, and complete pairs seventeen
through nineteen.

Three defaults, and what moves between them
-------------------------------------------
Three pairs by default, normally at most five when the question needs them, an
absolute maximum of eight, and all of it under the mode's history token cap.
`select` applies both bounds and reports which one bit, because "we sent three
pairs" and "we sent three pairs because eight would not fit" are different
facts about an answer.

An explicitly referenced older exchange can displace a less relevant recent one
INSIDE the same cap — it does not raise it.

The boundary applies to memory too
----------------------------------
Section 6.4: thread history, summaries and caches obey the domain boundary. A
result created by another module, or by an earlier and broader Cockpit, does
not become authorized by appearing in an old answer. So every stored exchange
carries its domain and release, and `select` drops the ones that do not match
rather than trusting that they were fine when they were written.

A referral is remembered as a referral. Summarising it as though the analysis
had been performed would let the NEXT question be answered against a memory of
work that never happened.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.cockpit_agentic import DOMAIN
from backend.cockpit_agentic.contracts import Exchange, ThreadSummary
from backend.cockpit_agentic.context import estimate_tokens
from backend.cockpit_agentic.ledger import Limits

DEFAULT_PAIRS = 3
EXPANDED_PAIRS = 5
HARD_CAP_PAIRS = 8


@dataclass
class Selection:
    """The bounded history for one request, and why it is that size."""

    exchanges: list[dict[str, Any]] = field(default_factory=list)
    requested_pairs: int = DEFAULT_PAIRS
    delivered_pairs: int = 0
    limited_by: str = ""            # "" | "pairs" | "tokens" | "availability"
    dropped_out_of_domain: int = 0
    estimated_tokens: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "delivered_pairs": self.delivered_pairs,
            "requested_pairs": self.requested_pairs,
            "limited_by": self.limited_by,
            "dropped_out_of_domain": self.dropped_out_of_domain,
            "estimated_tokens": self.estimated_tokens,
            "note": ("A recent exchange is one complete question and its final "
                     "answer, referral or clarification. The full thread stays "
                     "in authorized storage for audit and is not resent."),
        }


def authorized(exchange: Exchange, *, dataset_release_id: str) -> bool:
    """Whether a stored exchange may be reused as context.

    Refuses anything from another domain or another release. Section 12: reject
    inaccessible, expired or cross-domain prior artifacts even if a summary
    mentions them.
    """
    if exchange.domain_id != DOMAIN:
        return False
    if exchange.dataset_release_id and \
            exchange.dataset_release_id != dataset_release_id:
        return False
    return True


def render(exchange: Exchange) -> dict[str, Any]:
    """One exchange as the context packet carries it.

    The KIND travels with it. A referral rendered without its kind reads, to
    the next turn, exactly like an answer.
    """
    prefix = {
        "referral": "[This question was REFERRED to another part of "
                    "CreditProbe and was not answered here.]",
        "clarification": "[A clarification was asked; this question is still "
                         "open.]",
        "stop": "[This question stopped without an answer.]",
    }.get(exchange.kind, "")
    return {
        "exchange_id": exchange.exchange_id,
        "kind": exchange.kind,
        "question": exchange.question,
        "answer": (f"{prefix} {exchange.answer}".strip() if prefix
                   else exchange.answer),
        "fact_ids": list(exchange.fact_ids),
    }


def select(history: list[Exchange], *, limits: Limits,
           dataset_release_id: str, pairs: int = DEFAULT_PAIRS,
           referenced_ids: list[str] | None = None) -> Selection:
    """The bounded recent history, newest last.

    `pairs` is what the caller wants; the hard cap and the token cap are what
    it gets. `referenced_ids` names older exchanges the user explicitly pointed
    at, which may displace a less relevant recent pair WITHIN the same cap.
    """
    wanted = max(1, min(int(pairs), HARD_CAP_PAIRS))
    usable = [e for e in history
              if authorized(e, dataset_release_id=dataset_release_id)]
    dropped = len(history) - len(usable)

    chosen: list[Exchange] = []
    referenced = [e for e in usable if e.exchange_id in set(referenced_ids or ())]
    for exchange in referenced[-wanted:]:
        chosen.append(exchange)
    for exchange in reversed(usable):
        if len(chosen) >= wanted:
            break
        if exchange in chosen:
            continue
        chosen.append(exchange)
    # Back into conversation order.
    chosen = [e for e in usable if e in chosen]

    limited_by = ""
    if len(usable) > wanted:
        limited_by = "pairs"
    elif len(chosen) < wanted:
        limited_by = "availability"

    rendered = [render(e) for e in chosen]
    tokens = estimate_tokens(rendered)
    while rendered and tokens > limits.recent_history_tokens:
        rendered.pop(0)
        tokens = estimate_tokens(rendered)
        limited_by = "tokens"

    return Selection(exchanges=rendered, requested_pairs=wanted,
                     delivered_pairs=len(rendered), limited_by=limited_by,
                     dropped_out_of_domain=dropped, estimated_tokens=tokens)


@dataclass
class ThreadState:
    """One Cockpit thread: its rolling summary and its complete exchanges.

    In-memory here. The persistence seam is deliberate: `backend/services/
    threads.py` already stores messages durably, and this layer is about
    SELECTION and boundary, not storage.
    """

    thread_id: str
    dataset_release_id: str
    summary: ThreadSummary | None = None
    exchanges: list[Exchange] = field(default_factory=list)

    def record(self, exchange: Exchange) -> None:
        self.exchanges.append(exchange)

    def context_for(self, *, limits: Limits, pairs: int = DEFAULT_PAIRS,
                    referenced_ids: list[str] | None = None
                    ) -> tuple[dict[str, Any], Selection]:
        selection = select(self.exchanges, limits=limits,
                           dataset_release_id=self.dataset_release_id,
                           pairs=pairs, referenced_ids=referenced_ids)
        summary = self.summary.to_dict() if self.summary else {}
        if self.summary and self.summary.unsummarized_exchange_ids:
            summary["note"] = (
                "One or more exchanges after this summary were not "
                "summarised; they are included verbatim in the recent "
                "exchanges below.")
        return summary, selection

    def apply_summary(self, summary: ThreadSummary) -> ThreadSummary:
        """Store a newer summary, refusing a stale one.

        Section 7.9: serialize active work per thread or use version checks so
        a stale summary cannot overwrite a newer one.
        """
        if self.summary and summary.version <= self.summary.version:
            return self.summary
        summary.thread_id = self.thread_id
        self.summary = summary
        return summary


__all__ = ["DEFAULT_PAIRS", "EXPANDED_PAIRS", "HARD_CAP_PAIRS", "Selection",
           "ThreadState", "authorized", "render", "select"]
