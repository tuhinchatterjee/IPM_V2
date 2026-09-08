"""The Early Warning escalation matrix: the ladder, the specialist routes,
and severity/materiality routing — versioned separately from the scoring
methodology (implementation plan Section 12).

Recommended default, per the plan's evaluation of the spec's L5/L6 question:
a single L5 "Credit / Board Risk Committee" rather than splitting into L5/L6.
The platform has no existing Board-level workflow concept — WorkflowItem/
WorkflowRecipient are role/team-resolved, not committee-tiered — so a split
would need new governance plumbing nothing else in the platform needs today.
Revisit only if a real Board-governance workflow requirement emerges
elsewhere in the platform.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.early_warning import units

DEFAULT_VERSION = "1.0.0"

LADDER: tuple[dict[str, str], ...] = (
    {"level": "L0", "role": "Credit Monitoring Analyst",
     "owns": "Triage, evidence, entity and edge verification",
     "can_decide_alone": "Close a documented false positive"},
    {"level": "L1", "role": "Relationship Manager",
     "owns": "Client contact and information requests",
     "can_decide_alone": "Meeting, financials, cash flow forecast"},
    {"level": "L2", "role": "Credit Risk Manager",
     "owns": "Watchlist and the monitoring plan",
     "can_decide_alone": "Watchlist entry, freeze unutilised limits"},
    {"level": "L3", "role": "Head of Credit Risk",
     "owns": "Risk-mitigating action on material exposures",
     "can_decide_alone": "Limit cut, covenant reset, security top-up"},
    {"level": "L4", "role": "Chief Risk Officer",
     "owns": "Portfolio-level decisions",
     "can_decide_alone": "Sector and counterparty concentration action"},
    {"level": "L5", "role": "Credit / Board Risk Committee",
     "owns": "Mandate and restructuring",
     "can_decide_alone": "Restructure, forbear, remedial, write-off"},
)

SPECIALIST_ROUTES: tuple[dict[str, str], ...] = (
    {"code": "S1", "name": "Compliance / Financial Crime", "handles": "Sanctions, fraud"},
    {"code": "S2", "name": "Special Assets / Remedial", "handles": "Stage 3, restructuring"},
    {"code": "S3", "name": "Impairment Committee", "handles": "Staging and ECL"},
    {"code": "S4", "name": "Legal", "handles": "Litigation, cross-default"},
    {"code": "S5", "name": "Collateral / Valuation", "handles": "Valuation, security, perfection"},
)

#: Exposure tiers, in SAR millions. Severity decides urgency; this decides altitude.
EXPOSURE_TIERS: tuple[str, ...] = ("<50m", "50-150m", "150-400m", ">400m")

#: routing_matrix[severity][exposure_tier] -> {escalated_to, notified, ack_sla, decision_sla}
ROUTING_MATRIX: dict[str, dict[str, dict[str, Any]]] = {
    "VERY_HIGH": {
        "<50m": {"escalated_to": ["L2", "S3"], "notified": [], "ack_sla_days": 0, "decision_sla_days": 5},
        "50-150m": {"escalated_to": ["L3", "S3"], "notified": [], "ack_sla_days": 0, "decision_sla_days": 5},
        "150-400m": {"escalated_to": ["L3"], "notified": ["L4"], "ack_sla_days": 0, "decision_sla_days": 5},
        ">400m": {"escalated_to": ["L4", "L5"], "notified": [], "ack_sla_days": 0, "decision_sla_days": 5},
    },
    "HIGH": {
        "<50m": {"escalated_to": ["L1"], "notified": [], "ack_sla_days": 1, "decision_sla_days": 10},
        "50-150m": {"escalated_to": ["L2"], "notified": [], "ack_sla_days": 1, "decision_sla_days": 10},
        "150-400m": {"escalated_to": ["L2"], "notified": ["L3"], "ack_sla_days": 1, "decision_sla_days": 10},
        ">400m": {"escalated_to": ["L3"], "notified": [], "ack_sla_days": 1, "decision_sla_days": 10},
    },
    "MEDIUM": {
        "<50m": {"escalated_to": ["L0"], "notified": [], "ack_sla_days": 3, "decision_sla_days": 20},
        "50-150m": {"escalated_to": ["L1"], "notified": [], "ack_sla_days": 3, "decision_sla_days": 20},
        "150-400m": {"escalated_to": ["L1"], "notified": ["L2"], "ack_sla_days": 3, "decision_sla_days": 20},
        ">400m": {"escalated_to": ["L2"], "notified": [], "ack_sla_days": 3, "decision_sla_days": 20},
    },
    "LOW": {
        "<50m": {"escalated_to": ["L0"], "notified": [], "ack_sla_days": 5, "decision_sla_days": None},
        "50-150m": {"escalated_to": ["L0"], "notified": [], "ack_sla_days": 5, "decision_sla_days": None},
        "150-400m": {"escalated_to": ["L0"], "notified": [], "ack_sla_days": 5, "decision_sla_days": None},
        ">400m": {"escalated_to": ["L1"], "notified": [], "ack_sla_days": 5, "decision_sla_days": None},
    },
    "VERY_LOW": {
        tier: {"escalated_to": [], "notified": [], "ack_sla_days": None, "decision_sla_days": None}
        for tier in EXPOSURE_TIERS
    },
}


def exposure_tier(exposure_sar_mn: float) -> str:
    if exposure_sar_mn < 50:
        return "<50m"
    if exposure_sar_mn < 150:
        return "50-150m"
    if exposure_sar_mn < 400:
        return "150-400m"
    return ">400m"


def route_for(ews_band: str, exposure_sar_mn: float) -> dict[str, Any]:
    """Severity decides urgency, materiality decides altitude (spec Section AE)."""
    tier = exposure_tier(exposure_sar_mn)
    routing = ROUTING_MATRIX.get(ews_band, ROUTING_MATRIX["VERY_LOW"])[tier]
    return {"severity": ews_band, "exposure_tier": tier, **routing}


def default_bundle() -> dict[str, Any]:
    return {
        "ladder": list(LADDER),
        "specialist_routes": list(SPECIALIST_ROUTES),
        "exposure_tiers": list(EXPOSURE_TIERS),
        "routing_matrix": ROUTING_MATRIX,
    }


def role_of(level: str) -> str:
    """The title behind a rung or a specialist code."""
    for rung in LADDER:
        if rung["level"] == level:
            return str(rung["role"])
    for route in SPECIALIST_ROUTES:
        if route["code"] == level:
            return str(route["name"])
    return level


def sla_due(days: int | None, *, from_when: Any = None) -> Any:
    """The date an acknowledgement or a decision is due.

    The matrix has always carried these; nothing ever stamped them, so no
    early warning escalation could appear in the "due soon" list and an SLA
    breach rate could not be measured. A control whose clock never starts is
    a report.
    """
    from datetime import datetime, timedelta, timezone

    if days is None:
        return None
    start = from_when or datetime.now(timezone.utc)
    return start + timedelta(days=int(days))


def route_with_actions(ews_band: str, exposure_sar_mn: float,
                        driver_codes: list[str] | None = None) -> dict[str, Any]:
    """The routing decision, with what the recipient is being asked to do.

    An alert that arrives without a recommendation makes the recipient start
    from the score, which is the least useful part of it. So the route
    carries the actions keyed to the drivers, the owner of each, and the
    evidence that closes them.
    """
    from backend.early_warning import actions as act

    route = route_for(ews_band, exposure_sar_mn)
    recommended = act.for_drivers(list(driver_codes or []))
    first = act.single_highest_value(recommended)
    return {
        **route,
        "escalated_to_roles": [role_of(l) for l in route.get("escalated_to") or []],
        "notified_roles": [role_of(l) for l in route.get("notified") or []],
        "ack_due": sla_due(route.get("ack_sla_days")),
        "decision_due": sla_due(route.get("decision_sla_days")),
        "actions": [a.to_dict() for a in recommended],
        "priority_action": first.to_dict() if first else None,
    }


def note_for(figures: dict[str, Any], *, case_key: str = "",
             requested_decision: str = "") -> str:
    """The escalation note, drafted from the facts rather than from prose.

    Written in the order a decision-maker reads: position, driver with its
    score and whether it is cured, corroboration, recommendation with owner
    and date, and the evidence that closes it. Everything in it is a figure
    the pack already carried — an escalation note is the last place to
    introduce a number nobody can trace.
    """
    from backend.early_warning import actions as act

    name = figures.get("customer_name", "the obligor")
    cid = figures.get("customer_id", "")
    exposure = figures.get("exposure", 0.0)
    limit = figures.get("limit") or 0.0
    drivers = figures.get("drivers") or []
    band = figures.get("ews_band", "")
    route = route_for(band, float(exposure))

    lines: list[str] = []
    head = f"{name}, {cid}, exposure {units.money(exposure)}"
    if limit:
        head += f" of a {units.money(limit)} limit"
    head += (f", {figures.get('dpd', 0)} days past due, "
             f"Stage {figures.get('ifrs9_stage', 1)}.")
    lines.append(head)

    lines.append(
        f"EWS {figures.get('ews_score', 0):.0f} ({band.replace('_', ' ').lower()}), "
        f"anchor {figures.get('anchor_score', 0):.0f} from T&A "
        f"{figures.get('live_versus_structural', {}).get('ta_band', '').replace('_', ' ').lower()} "
        f"by classifier "
        f"{figures.get('live_versus_structural', {}).get('classifier_band', '').replace('_', ' ').lower()}, "
        f"{figures.get('net_notches', 0):+d} net notches.")

    if drivers:
        worst = drivers[0]
        line = (f"Driver: {worst['code']} {worst['name'].lower()} at "
                f"{worst['score']:.0f}, {worst['reason'].lower()}.")
        others = [d for d in drivers[1:3] if d["score"] >= 50]
        if others:
            line += (" Corroborated by " + ", ".join(
                f"{d['code']} {d['name'].lower()} at {d['score']:.0f}"
                for d in others) + ".")
        lines.append(line)

    recommended = act.for_drivers([d["code"] for d in drivers])
    first = act.single_highest_value(recommended)
    if first is not None:
        lines.append(
            f"Recommendation: {first.action.lower()}. "
            f"{first.owner_title}, {first.timeframe}. "
            f"Evidence to close: {first.evidence_to_close.lower()}.")

    to = [role_of(l) for l in route.get("escalated_to") or []]
    if to:
        decide = route.get("decision_sla_days")
        ask = (requested_decision or
               "what risk-mitigating action is proportionate to the exposure")
        lines.append(
            f"Decision requested from {' and '.join(to)}: {ask}"
            + (f", within {decide} working days." if decide else "."))
    if case_key:
        lines.append(f"Case {case_key}.")
    return " ".join(lines)
