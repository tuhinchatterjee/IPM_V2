"""The Early Warning landing page, in business terms. R2 §10.

The screen opened on signal counts — "412 utilisation_high, 389 leverage_rose"
— which tells a credit officer how the rule book is behaving and nothing about
the book. What they arrive wanting to know is how many names need them today,
how much money is behind those names, and what changed since last quarter.

So the landing carries BUSINESS RISK measures, each with a sentence saying
what it is; the signal counts move to diagnostics, where the person tuning the
taxonomy can find them.

Every measure states its own availability
-----------------------------------------
A KPI that cannot be computed reports UNAVAILABLE with the reason, never zero.
"No borrowers are in covenant breach" and "this deployment does not carry the
covenant flag" are different answers, and only one of them is reassuring (§7).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.early_warning import priority as pr
from backend.early_warning import signals as sg
from backend.early_warning import taxonomy as tx

DASHBOARD_VERSION = "1.0.0"

COUNT = "count"
MONEY = tx.MONEY


@dataclass
class Measure:
    """One number on the landing page, and what it means."""

    key: str
    label: str
    means: str
    value: float | None = None
    unit: str = COUNT
    #: Why it could not be computed. Empty when it could.
    unavailable: str = ""
    #: The borrowers behind it, so the number is a door rather than a fact.
    borrowers: list[str] = field(default_factory=list)

    @property
    def available(self) -> bool:
        return not self.unavailable

    def to_dict(self) -> dict[str, Any]:
        return {"key": self.key, "label": self.label, "means": self.means,
                "value": self.value, "unit": self.unit,
                "currency": tx.CURRENCY if self.unit == MONEY else "",
                "available": self.available, "unavailable": self.unavailable,
                "borrowers": self.borrowers[:50],
                "borrower_count": len(self.borrowers)}


def _exposure(standing: sg.Standing) -> float:
    return float(standing.verdict.exposure or 0.0)


def _flag(record: dict[str, Any], name: str) -> bool:
    value = record.get(name)
    if isinstance(value, bool):
        return value
    try:
        return float(value) > 0
    except (TypeError, ValueError):
        return False


def _carries(standings: list[sg.Standing], column: str) -> bool:
    """Whether the book carries this column at all."""
    return any(column in s.record for s in standings)


def measures(standings: list[sg.Standing]) -> list[Measure]:
    """The ten business-risk measures §10 asks for, in reading order."""
    out: list[Measure] = []

    def named(where) -> list[str]:
        return sorted(s.borrower_id for s in standings if where(s))

    acting = named(lambda s: s.priority == pr.ACT_NOW)
    reviewing = named(lambda s: s.priority == pr.REVIEW)
    attention = set(acting) | set(reviewing)

    out.append(Measure(
        "act_now", "Borrowers to act on",
        "Something has already happened that the bank can act on, on an "
        "exposure large enough to matter.",
        float(len(acting)), COUNT, borrowers=acting))

    # NEW: nothing was firing for this borrower at the previous reporting date.
    arrived = named(lambda s: s.fired and s.persistence == 0
                    and s.priority in (pr.ACT_NOW, pr.REVIEW))
    out.append(Measure(
        "newly_at_risk", "New this quarter",
        "Borrowers that need attention now and had nothing firing at the "
        "previous reporting date. A name that arrives is a different problem "
        "from one that has been there all year.",
        float(len(arrived)), COUNT, borrowers=arrived))

    if _carries(standings, "drawn_exposure"):
        at_stake = sum(_exposure(s) for s in standings
                       if s.borrower_id in attention)
        out.append(Measure(
            "exposure_at_stake", "Exposure requiring attention",
            "Drawn exposure across every borrower to act on or bring forward "
            "for review.",
            round(at_stake, 1), MONEY, borrowers=sorted(attention)))
    else:
        out.append(Measure(
            "exposure_at_stake", "Exposure requiring attention",
            "Drawn exposure across the borrowers needing attention.",
            unavailable="This book does not carry drawn exposure, so the "
                        "amount at stake cannot be totalled."))

    # §20: an early-warning prediction is NEVER an accounting stage. This
    # counts borrowers whose evidence would support a stage 2 discussion and
    # whose booked stage is still 1 — and says so in those words.
    if _carries(standings, "stage"):
        candidates = named(
            lambda s: (s.record.get("stage") in (1, 1.0, "1"))
            and s.breadth >= pr.BROAD_FAMILIES)
        out.append(Measure(
            "stage_two_candidates", "Booked at stage 1, evidence says look",
            "Booked at IFRS 9 stage 1 with evidence in three or more "
            "independent families. This is a prompt to review the staging "
            "judgement, NOT a stage classification.",
            float(len(candidates)), COUNT, borrowers=candidates))
    else:
        out.append(Measure(
            "stage_two_candidates", "Booked at stage 1, evidence says look",
            "Borrowers whose evidence would support a staging discussion.",
            unavailable="This book does not carry the IFRS 9 stage."))

    for key, label, means, column in (
        ("covenant_breaches", "Covenant breaches",
         "Borrowers in breach of at least one covenant at the reporting date.",
         "breach_flag"),
        ("collateral_shortfall", "Collateral shortfall",
         "Borrowers whose security does not cover the exposure.",
         "collateral_shortfall"),
    ):
        if _carries(standings, column):
            hit = named(lambda s, c=column: _flag(s.record, c))
            out.append(Measure(key, label, means, float(len(hit)), COUNT,
                               borrowers=hit))
        else:
            out.append(Measure(key, label, means,
                               unavailable=f"This book does not carry "
                                           f"{column.replace('_', ' ')}."))

    liquid = named(lambda s: any(o.family == tx.LIQUIDITY for o in s.fired))
    out.append(Measure(
        "liquidity_stress", "Liquidity stress",
        "Borrowers with at least one liquidity condition firing — cash, "
        "committed headroom, short-term maturities.",
        float(len(liquid)), COUNT, borrowers=liquid))

    lagging = named(lambda s: any(o.signal in ("rating_stale", "rating_downgraded",
                                               "rating_multi_notch")
                                  for o in s.fired))
    out.append(Measure(
        "rating_movement", "Rating moved or overdue",
        "Borrowers downgraded, downgraded more than one notch, or carrying a "
        "rating override the bank has not revisited.",
        float(len(lagging)), COUNT, borrowers=lagging))

    return out


def hotspots(standings: list[sg.Standing], *, limit: int = 8) -> list[dict[str, Any]]:
    """Where the attention is concentrated. R2 §10.

    By sector, because that is the cut a credit committee acts on. Counts and
    exposure side by side: a sector with many small problems and one with a
    single large one are different situations and a count alone hides that.
    """
    by_sector: dict[str, dict[str, Any]] = {}
    for standing in standings:
        sector = str(standing.record.get("sector") or "Unattributed")
        row = by_sector.setdefault(sector, {
            "sector": sector, "borrowers": 0, "act_now": 0, "review": 0,
            "exposure": 0.0})
        row["borrowers"] += 1
        if standing.priority == pr.ACT_NOW:
            row["act_now"] += 1
            row["exposure"] += _exposure(standing)
        elif standing.priority == pr.REVIEW:
            row["review"] += 1
            row["exposure"] += _exposure(standing)
    rows = [r | {"exposure": round(r["exposure"], 1)}
            for r in by_sector.values() if r["act_now"] or r["review"]]
    rows.sort(key=lambda r: (-r["act_now"], -r["exposure"], r["sector"]))
    return rows[:limit]


def changes(standings: list[sg.Standing], *, limit: int = 10) -> list[dict[str, Any]]:
    """What actually moved since the last reporting date. R2 §10.

    A borrower that has been in breach for a year is not news. One that
    arrived this quarter, or whose evidence got worse, is.
    """
    moved = [s for s in standings
             if s.priority in (pr.ACT_NOW, pr.REVIEW)
             and (s.worsening or s.persistence == 0)]
    moved.sort(key=lambda s: (-pr.PRIORITY_RANK.get(s.priority, 0),
                              -_exposure(s), -s.worsening, s.borrower_id))
    out = []
    for standing in moved[:limit]:
        arrived = standing.persistence == 0
        out.append({
            "borrower_id": standing.borrower_id,
            "borrower_name": str(standing.record.get("borrower_name") or ""),
            "sector": str(standing.record.get("sector") or ""),
            "priority": standing.priority,
            "priority_label": standing.verdict.label,
            "exposure": standing.verdict.exposure,
            "what_changed": (
                "Nothing was firing at the previous reporting date."
                if arrived else
                f"{standing.worsening} condition"
                f"{'' if standing.worsening == 1 else 's'} moved further the "
                f"wrong way this quarter."),
            "because": standing.verdict.because()[:2],
        })
    return out


def diagnostics(standings: list[sg.Standing], *, limit: int = 20) -> list[dict[str, Any]]:
    """How the RULE BOOK is behaving. R2 §10 moved this off the landing page.

    Still published, because the person tuning a threshold needs it — just not
    where a credit officer arrives looking for names.
    """
    counted: dict[str, int] = {}
    for standing in standings:
        for observation in standing.fired:
            counted[observation.signal] = counted.get(observation.signal, 0) + 1
    labels = {s.key: s.label for s in tx.SIGNALS}
    rows = [{"signal": key, "label": labels.get(key, key), "borrowers": n,
             "share_of_book_pct": round(100.0 * n / max(1, len(standings)), 1)}
            for key, n in counted.items()]
    rows.sort(key=lambda r: (-r["borrowers"], r["signal"]))
    return rows[:limit]


def risk_levels(standings: list[sg.Standing]) -> dict[str, Any]:
    """The book split by overall Early Warning risk. Section 11B and 11G.

    Assessed once per borrower here rather than by each caller, because the
    assessment reads the whole standing and a screen that recomputes it per
    card recomputes it three thousand times.
    """
    from backend.early_warning import assessment as ea

    found = [(s, ea.assess(s, s.record)) for s in standings]
    by_level: dict[str, list[tuple[sg.Standing, Any]]] = {
        level: [] for level in ea.LEVELS}
    for standing, verdict in found:
        by_level[verdict.level].append((standing, verdict))

    return {
        "owner": ea.ASSESSMENT_OWNER,
        "version": ea.ASSESSMENT_VERSION,
        "rule": ea.describe()["rule"],
        "levels": [
            {"level": level,
             "means": ea.LEVEL_MEANS[level],
             "borrowers": len(by_level[level]),
             "share": (round(100.0 * len(by_level[level]) / len(found), 1)
                       if found else 0.0),
             "exposure": round(sum(_exposure(s) for s, _ in by_level[level]), 1),
             # The names, so the count is a door rather than a fact.
             "names": [s.borrower_id for s, _ in by_level[level][:50]]}
            for level in ea.LEVELS],
        "statement": (
            "Risk level is decided by gravity AND corroboration, never by how "
            "many signals fired. A borrower with six stale-valuation "
            "observations is not in more trouble than one in covenant breach."),
    }


def build(standings: list[sg.Standing], *, period: str = "",
          previous_period: str = "", evaluated: int = 0) -> dict[str, Any]:
    """The whole landing page, from one pass over the standings."""
    return {
        "version": DASHBOARD_VERSION,
        "period": period,
        "previous_period": previous_period,
        "evaluated": evaluated or len(standings),
        "currency": tx.CURRENCY,
        "measures": [m.to_dict() for m in measures(standings)],
        "hotspots": hotspots(standings),
        "changes": changes(standings),
        "diagnostics": diagnostics(standings),
        "risk_levels": risk_levels(standings),
        "priority_policy": {
            "owner": pr.OWNER, "version": pr.PRIORITY_VERSION,
            "levels": [{"priority": level,
                        "label": pr.PRIORITY_LABEL[level],
                        "means": pr.PRIORITY_MEANS[level]}
                       for level in pr.PRIORITIES],
            "material_exposure": pr.MATERIAL_EXPOSURE,
        },
    }


__all__ = ["DASHBOARD_VERSION", "Measure", "build", "changes", "diagnostics",
           "hotspots", "measures", "risk_levels"]
