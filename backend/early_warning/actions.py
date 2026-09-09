"""
The action library: what to do about a driver, who owns it, by when, and
what closes it.

Why a library rather than advice
-------------------------------
"Monitor closely" is the failure this module exists to prevent. It is not an
action: nobody owns it, nothing is due, and no evidence can close it, so a
month later the file looks exactly as it did and the alert is still open.
Every recommendation here therefore carries four things — the action itself,
an owner drawn from the escalation ladder, a timeframe, and the specific
evidence that closes it. A case cannot be closed until that evidence is
attached, which is what makes the alert a control rather than a report.

Keyed to the driver, not the score
----------------------------------
Recommendations are keyed to the 22 sub-category nodes, because the driver
is what determines the response. A covenant breach and a supplier failure
can produce the same score and need entirely different actions; keying on
severity would give them the same advice and be useless for both.

Prioritising when only one thing can be done
--------------------------------------------
Asked to pick one, the honest answer is not "the highest-scoring node". It
is the action that preserves the most optionality for the least cost: a
reservation of rights costs nothing, is quick, and keeps every other action
available afterwards, while an independent business review is slow,
expensive and forecloses nothing. So each entry carries a reversibility rank
(how much it preserves the bank's position) and a cost rank (what it costs
to take), and `single_highest_value` ranks by those rather than by score.
That is the reasoning the framework asks for: justify by reversibility and
cost, not by severity.

Owners resolve against the ladder
---------------------------------
`owner_role` is one of the escalation ladder's own rungs (L0-L5) or a
specialist route (S1-S5) from `escalation.py`, never a free-text job title,
so an action and an escalation name the same person by the same rule.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.early_warning import escalation as esc

#: Immediate, expressed as a timeframe of zero days.
IMMEDIATE = 0


@dataclass(frozen=True)
class Action:
    """One governed recommendation.

    `reversibility_rank` and `cost_rank` are both 1-5, low is better: rank 1
    reversibility means the action preserves the bank's position and closes
    nothing off; rank 1 cost means it is essentially free to take.
    """

    sub_category: str
    action: str
    owner_role: str  # an escalation ladder level ("L3") or specialist route ("S5")
    timeframe_days: int
    evidence_to_close: str
    reversibility_rank: int
    cost_rank: int

    @property
    def owner_title(self) -> str:
        """The human name of the owner, read from the escalation ladder."""
        for rung in esc.LADDER:
            if rung["level"] == self.owner_role:
                return str(rung["role"])
        for route in esc.SPECIALIST_ROUTES:
            if route["code"] == self.owner_role:
                return str(route["name"])
        return self.owner_role

    @property
    def timeframe(self) -> str:
        if self.timeframe_days == IMMEDIATE:
            return "immediate"
        if self.timeframe_days == 1:
            return "1 day"
        return f"{self.timeframe_days} days"

    def to_dict(self) -> dict:
        return {
            "sub_category": self.sub_category,
            "action": self.action,
            "owner_role": self.owner_role,
            "owner": self.owner_title,
            "timeframe_days": self.timeframe_days,
            "timeframe": self.timeframe,
            "evidence_to_close": self.evidence_to_close,
            "reversibility_rank": self.reversibility_rank,
            "cost_rank": self.cost_rank,
        }


#: One recommendation per scoring node. The four the framework publishes
#: verbatim (L1.3, L2.5, L2.T2, L4.2) are transcribed; the rest follow the
#: same construction — the action a credit officer would actually take
#: against that driver, owned at the rung that can decide it alone.
ACTION_LIBRARY: dict[str, Action] = {
    # ---- Layer 1, internal behavioural -------------------------------------
    "L1.1": Action(
        "L1.1", "Obtain a 13-week cash flow forecast and confirm where "
        "operating inflows have moved", "L1", 10,
        "Cash flow forecast and a written explanation of the diverted inflows",
        reversibility_rank=1, cost_rank=1),
    "L1.2": Action(
        "L1.2", "Freeze the unutilised portion of the limit pending review",
        "L2", IMMEDIATE,
        "System limit-block confirmation",
        reversibility_rank=2, cost_rank=1),
    "L1.3": Action(
        "L1.3", "Agree a cure plan and reinstate the payment mandates", "L1", 10,
        "Cleared arrears and mandate confirmation",
        reversibility_rank=1, cost_rank=2),
    "L1.4": Action(
        "L1.4", "Relationship review: confirm whether collections have moved "
        "to another bank and on what terms", "L1", 15,
        "Written relationship review noting the accounts and volumes involved",
        reversibility_rank=1, cost_rank=1),

    # ---- Layer 2, credit and financial fundamentals (classifier side) ------
    "L2.1": Action(
        "L2.1", "Confirm the staging decision and the arrears position, and "
        "put the obligor on the watchlist at the frequency the band requires",
        "L2", 5,
        "Watchlist entry with the agreed monitoring frequency",
        reversibility_rank=1, cost_rank=1),
    "L2.2": Action(
        "L2.2", "Re-test leverage and coverage against the current forecast "
        "and reset the covenant package if headroom has gone", "L3", 30,
        "Re-tested covenant schedule and the revised facility terms",
        reversibility_rank=3, cost_rank=3),
    "L2.3": Action(
        "L2.3", "Obtain a working capital plan showing how the cycle will be "
        "funded to the next test date", "L1", 15,
        "Working capital plan with committed funding lines identified",
        reversibility_rank=1, cost_rank=2),
    "L2.4": Action(
        "L2.4", "Commission an independent business review at the obligor's "
        "cost", "L3", 60,
        "Independent business review report and management response",
        reversibility_rank=4, cost_rank=5),
    "L2.5": Action(
        "L2.5", "Commission a fresh valuation and require a collateral top-up",
        "S5", 30,
        "Valuation report and registered security",
        reversibility_rank=2, cost_rank=3),
    "L2.6": Action(
        "L2.6", "Review the group exposure against appetite and reduce the "
        "single-name concentration where it exceeds it", "L3", 30,
        "Approved exposure reduction plan against the group limit",
        reversibility_rank=3, cost_rank=3),
    "L2.7": Action(
        "L2.7", "Require audited financial statements and a management "
        "response to the qualification before the next review", "L1", 30,
        "Audited statements and the written management response",
        reversibility_rank=1, cost_rank=2),

    # ---- Layer 2, trigger side ---------------------------------------------
    "L2.T1": Action(
        "L2.T1", "Bring forward the credit review and re-test the rating "
        "against the migration that has already happened", "L2", 20,
        "Completed accelerated review with the rating decision recorded",
        reversibility_rank=1, cost_rank=2),
    "L2.T2": Action(
        "L2.T2", "Reserve rights on the breach in writing rather than "
        "granting a waiver", "L3", 15,
        "Reservation-of-rights letter and confirmation at the next covenant test",
        reversibility_rank=1, cost_rank=1),

    # ---- Layer 3, external intelligence ------------------------------------
    "L3.1": Action(
        "L3.1", "Verify the disclosure at source and establish whether the "
        "obligor's licence or registration status has changed", "L0", 5,
        "Copy of the official filing and a confirmed registration status",
        reversibility_rank=1, cost_rank=1),
    "L3.2": Action(
        "L3.2", "Refer to Legal to establish the standing of the proceedings "
        "and any cross-default consequence", "S4", 10,
        "Legal opinion on standing and cross-default exposure",
        reversibility_rank=2, cost_rank=3),
    "L3.3": Action(
        "L3.3", "Reconcile the market signal against the internal rating and "
        "flag the divergence for the next review", "L2", 15,
        "Written reconciliation of the market signal to the internal grade",
        reversibility_rank=1, cost_rank=1),
    "L3.4": Action(
        "L3.4", "Verify the reported event with management and quantify its "
        "impact on repayment capacity", "L1", 10,
        "Written management response with a quantified impact",
        reversibility_rank=1, cost_rank=1),
    "L3.5": Action(
        "L3.5", "Reassess the obligor's forecast against the sector or "
        "commodity move and test it at the stressed assumption", "L2", 30,
        "Revised forecast tested at the stressed sector assumption",
        reversibility_rank=1, cost_rank=2),

    # ---- Layer 4, network ---------------------------------------------------
    "L4.1": Action(
        "L4.1", "Verify the supplier's distress and establish whether an "
        "alternative source exists at what cost and lead time", "L1", 20,
        "Confirmed alternative supply arrangement or a costed substitution plan",
        reversibility_rank=1, cost_rank=2),
    "L4.2": Action(
        "L4.2", "Verify the receivable ageing against the distressed customer "
        "and require credit insurance on the exposure", "L2", 30,
        "Aged receivables listing and insurance confirmation",
        reversibility_rank=2, cost_rank=3),
    "L4.3": Action(
        "L4.3", "Reconfirm the guarantee and obtain current guarantor "
        "accounts, checking whether any cross-default clause is live", "L2", 20,
        "Reconfirmed guarantee and current guarantor financial statements",
        reversibility_rank=1, cost_rank=2),
    "L4.4": Action(
        "L4.4", "Verify the concentration edges and their confidence before "
        "relying on them, then set a dependency limit", "L0", 15,
        "Verified counterparty edges with a recorded confidence and an agreed "
        "dependency limit",
        reversibility_rank=1, cost_rank=2),
}


def for_subcategory(code: str) -> Action | None:
    """The governed action for one driver, or None if the code is unknown."""
    return ACTION_LIBRARY.get(code)


def for_drivers(codes: list[str]) -> list[Action]:
    """The actions for a borrower's drivers, in the order the drivers were
    given — worst first, since that is how the caller ranks them."""
    out: list[Action] = []
    seen: set[str] = set()
    for code in codes:
        found = ACTION_LIBRARY.get(code)
        if found is not None and found.sub_category not in seen:
            seen.add(found.sub_category)
            out.append(found)
    return out


def single_highest_value(actions: list[Action]) -> Action | None:
    """The one to take if only one can be taken.

    Ranked by reversibility first and cost second — never by the score of the
    node it came from. The action that preserves the bank's position and
    costs nothing keeps every other action available afterwards; the
    expensive, slow one does not become unavailable by waiting.
    """
    if not actions:
        return None
    return sorted(actions, key=lambda a: (a.reversibility_rank, a.cost_rank,
                                          a.timeframe_days))[0]


def coverage() -> dict[str, int]:
    """How much of the scoring model the library can answer for."""
    return {"nodes": len(ACTION_LIBRARY)}


__all__ = ["IMMEDIATE", "Action", "ACTION_LIBRARY", "for_subcategory",
           "for_drivers", "single_highest_value", "coverage"]
