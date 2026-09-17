"""Effective-dated clauses, and the refusal to call a draft a bank policy.

The defect this exists for
--------------------------
A recommendation that reads as compliant when it is not is the most expensive
sentence this product could produce. "Place these accounts on second-level
approval, per clause 2.1" is indistinguishable, to a reader, from the same
sentence quoting a clause the bank has actually approved.

No approved bank policy was supplied with this work. So every clause here
carries `DEMO_DRAFT - NOT BANK APPROVED`, every surface that renders one shows
that status beside it, and `claims_compliance()` returns False for all of them
— not as a caveat to be trimmed later, but as the thing the answer is built
from.

The hierarchy, and what this module can and cannot do
-----------------------------------------------------
Applicable law and regulation, then bank-approved effective policy, then
delegated authority and the customer contract, then a proposed action. This
module holds the third and fourth. It does not hold the first — public SAMA
guidance is context for a mechanism, not a substitute for the bank's own
thresholds — and the second is empty until somebody supplies it.

That is why the affordability rules are not a number here. The applicable
limit depends on income band, salary or pension status, obligation category
and housing-support eligibility, so a single hardcoded 45%, 55% or 65% applied
to everybody would be wrong for most of them and wrong in a way that looks
authoritative.

Nothing here executes anything
------------------------------
`actions_for` returns proposals. There is no apply, no write to a limit, no
change to a balance. A scenario trial is labelled a trial, and an unmodelled
effect is labelled unavailable rather than filled with a percentage.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from backend.retail import episodes as ep

logger = logging.getLogger(__name__)

VERSION = "retail-episode-policy-1.0.0"

DRAFT = "DEMO_DRAFT - NOT BANK APPROVED"
APPROVED = "BANK_APPROVED"

#: Every action requires a person. Stated per action rather than once at the
#: top, because an action list read halfway down is read without the preamble.
APPROVAL = ("Human approval required; applicability, contractual and "
            "customer-consent checks before anything is done")


class NotApproved(RuntimeError):
    """A compliance claim was made against a draft clause. Always refused."""


def clauses_for(case_id: str) -> list[dict[str, Any]]:
    """This story's clauses, as the configuration holds them."""
    episode = ep.by_id(case_id)
    if episode is None:
        return []
    return [{
        "policy_id": episode.policy_id,
        "version": episode.policy_version,
        "clause": action["clause"],
        "status": action["status"],
        "effective_from": action["effective_from"],
        "effective_to": "",
        "product_scope": episode.product,
        "text": action["action"],
        "owner": action["owner"],
        "timing": action["timing"],
        "safeguard": action["safeguard"],
        "research_context": list(action.get("research") or []),
    } for action in episode.policy_actions]


def in_force(clause: dict[str, Any], as_of: str) -> bool:
    """Whether a clause was in force at a date.

    An expired or not-yet-effective clause is not a smaller version of an
    applicable one: an action proposed against it is unsupported, and the
    caller is told so rather than shown the action with a footnote.
    """
    at = str(as_of or "")[:10]
    if not at:
        return False
    try:
        when = date.fromisoformat(at if len(at) == 10 else f"{at}-01")
    except ValueError:
        return False
    start = str(clause.get("effective_from") or "")[:10]
    end = str(clause.get("effective_to") or "")[:10]
    if start:
        try:
            if when < date.fromisoformat(start):
                return False
        except ValueError:
            return False
    if end:
        try:
            if when > date.fromisoformat(end):
                return False
        except ValueError:
            return False
    return True


def claims_compliance(clause: dict[str, Any]) -> bool:
    """Whether an action against this clause may be described as compliant.

    False for every clause this installation holds, and the function exists so
    that the surfaces asking the question get an answer rather than deciding
    for themselves.
    """
    return str(clause.get("status") or "") == APPROVED


def actions_for(case_id: str, *, as_of: str = "") -> list[dict[str, Any]]:
    """The sequenced proposals for one story, checked against their dates."""
    out: list[dict[str, Any]] = []
    for index, clause in enumerate(clauses_for(case_id), start=1):
        applicable = in_force(clause, as_of)
        out.append({
            "sequence": index,
            "action": clause["text"],
            "owner": clause["owner"],
            "timing": clause["timing"],
            "safeguard": clause["safeguard"],
            "policy_id": clause["policy_id"],
            "version": clause["version"],
            "clause": clause["clause"],
            "status": clause["status"],
            "effective_from": clause["effective_from"],
            "applicable_at": as_of,
            "applicable": applicable,
            "unsupported_because": (
                "" if applicable else
                f"clause {clause['clause']} was not in force at {as_of}, so "
                f"an action proposed against it is unsupported"),
            "approval": APPROVAL,
            "claims_compliance": claims_compliance(clause),
            "executed": False,
            "research_context": clause["research_context"],
        })
    return out


#: What a story's What-If trial actually varies, and what it may not touch.
#: Written per story because the parameters are not interchangeable: a balloon
#: needs a payment schedule, a recovery needs costs and timing, and a limit
#: change on a drawn card cannot repay the drawing.
_SCENARIOS: dict[str, dict[str, Any]] = {
    "C01": {
        "family": "new_book_limit",
        "label": "New-origination limit trial by original score band",
        "trials": [{"band": "600-619", "from_sar": 20_000, "to_sar": 17_000},
                   {"band": "590-599", "from_sar": 15_000, "to_sar": 12_000},
                   {"band": "580-589", "from_sar": 10_000, "to_sar": 7_500}],
        "affects": "future originations only",
        "must_not": ("An existing card's drawn balance is unchanged by a limit "
                     "cut. Only the lawful remaining undrawn headroom and its "
                     "credit conversion factor can move."),
        "not_modelled": ["probability of cure", "revenue"],
    },
    "C02": {
        "family": "new_book_underwriting",
        "label": "Second-level approval on the evidenced exception route",
        "affects": "future approvals on one exception route only",
        "must_not": ("Today's rules are not applied retrospectively to "
                     "decisions already taken."),
        "not_modelled": ["approval-rate effect", "volume effect"],
    },
    "C03": {
        "family": "payment_accommodation",
        "label": "Documented, consented payment accommodation",
        "affects": "existing arrangements, with consent",
        "must_not": ("A longer duration can INCREASE expected loss. The "
                     "modification and its accounting are shown, not netted "
                     "away."),
        "not_modelled": ["payroll restoration date"],
    },
    "C04": {
        "family": "new_book_underwriting",
        "label": "No further discretionary top-up, refreshed affordability",
        "affects": "future top-ups to the corroborated cohort",
        "must_not": ("Consolidation is not elimination. Existing commitments "
                     "remain."),
        "not_modelled": ["reborrowing elsewhere"],
    },
    "C05": {
        "family": "contract_structure",
        "label": "Maximum balloon 40% to 30% on new leases",
        "affects": "future leases only",
        "must_not": ("A smaller final payment raises the ordinary instalment. "
                     "The affordability recheck is part of the trial, not a "
                     "consequence of it."),
        "not_modelled": ["residual value realisation"],
    },
    "C06": {
        "family": "recovery",
        "label": "Validated recovery values and timing, PD held constant",
        "affects": "loss given default on the evidenced pocket",
        "must_not": ("Probability of default is HELD. Moving it would be "
                     "manufacturing the borrower deterioration this story "
                     "found is not there."),
        "not_modelled": ["vendor performance improvement"],
    },
    "C07": {
        "family": "disbursement",
        "label": "Actual draw timing and permitted accommodation",
        "affects": "committed-but-undrawn exposure and its timing",
        "must_not": ("Committed-but-undrawn exposure and the contractual "
                     "obligation to fund it are preserved."),
        "not_modelled": ["completion date"],
    },
    "C08": {
        "family": "operational_correction",
        "label": "Support restored against support delayed",
        "affects": "verified eligible cases only",
        "must_not": ("An operating correction is not a modelled credit-risk "
                     "change. Probability of default does not become zero "
                     "because a posting was fixed."),
        "not_modelled": ["programme funding schedule"],
    },
    "C09": {
        "family": "reschedule",
        "label": "Permitted instalment or tenor rebuild on documented pension",
        "affects": "existing contracts, with consent",
        "must_not": ("No automatic cure is assumed, and the duration effect "
                     "on expected loss is shown."),
        "not_modelled": ["other household income"],
    },
    "C10": {
        "family": "stage_correction",
        "label": "Policy-compliant staging and sustainable arrangements",
        "affects": "the allowance on the reviewed arrangements",
        "must_not": ("A correction can RAISE the allowance. The adverse "
                     "direction is shown rather than avoided."),
        "not_modelled": ["probability of sustained cure"],
    },
}


def scenarios_for(case_id: str, as_of: str,
                  scope: dict[str, Any] | None = None) -> dict[str, Any]:
    """The What-If trial this story supports, and what it explicitly does not.

    An unmodelled effect is named rather than approximated. The specification
    is blunt about why: without an approved exposure budget, a 15% or 20%
    reduction is a TRIAL, and presenting one as an optimum reverse-engineers a
    percentage into something that reads like a bank rule.
    """
    found = dict(_SCENARIOS.get(case_id) or {})
    if not found:
        return {"available": False,
                "because": f"no scenario family is defined for {case_id}"}
    return {
        "available": True,
        "case_id": case_id,
        "as_of": as_of,
        "scope": {k: (scope or {}).get(k) for k in
                  ("customer_count", "facility_count", "totals")},
        **found,
        "basis": (
            "Explicit scenario trials, not optimised recommendations. No "
            "approved exposure or loss budget was supplied, so nothing here "
            "was solved for."),
        "approval": APPROVAL,
        "status": DRAFT,
    }
