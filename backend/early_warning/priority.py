"""What to do about this borrower, and why. R2 §25.

Severity was the maximum severity of any rule that fired, which is a fact
about the RULE BOOK rather than about the borrower. Two names with one severe
signal each came out identical when one of them was a SAR 400m exposure in
covenant breach and ninety days past due and the other was a SAR 3m facility
whose statements were stale. An officer working down that list works down it
in the wrong order.

So the priority is decided by what a credit committee would actually weigh:

* **materiality** — how much money is at stake;
* **the accounting position** — an impaired exposure is not a watch item;
* **arrears** — an unpaid instalment is not an early warning, it is a fact;
* **the covenant** — a breach is a contractual right the bank now holds;
* **collateral** — a shortfall is the recovery assumption failing;
* **breadth** — several independent families saying the same thing;
* **severity** — how bad the worst individual condition is;
* **trajectory** — whether it is getting worse or coming back.

Transparent, not weighted
-------------------------
There is deliberately no score. Each rule below is a named condition that
either holds or does not, and every one that holds produces a SENTENCE the
screen can print. A reader who disagrees with the priority can see exactly
which rule put it there and argue with that rule. A weighted score offers
them nothing to argue with, which is why nobody ever argues with one — and
why nobody ever trusts one either.

None of these thresholds is a regulatory requirement. They are seeded
materialities owned by the same function that owns the signal thresholds.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.early_warning import taxonomy as tx

PRIORITY_VERSION = "1.0.0"

# ------------------------------------------------------------ the four levels
#
# Four, and they are instructions rather than adjectives. "High" tells an
# officer how to feel; "Act now" tells them what to do.

ACT_NOW = "ACT_NOW"
REVIEW = "REVIEW"
MONITOR = "MONITOR"
ROUTINE = "ROUTINE"

PRIORITIES: tuple[str, ...] = (ACT_NOW, REVIEW, MONITOR, ROUTINE)
PRIORITY_RANK: dict[str, int] = {ACT_NOW: 4, REVIEW: 3, MONITOR: 2, ROUTINE: 1}

PRIORITY_LABEL: dict[str, str] = {
    ACT_NOW: "Act now",
    REVIEW: "Bring forward the review",
    MONITOR: "Monitor",
    ROUTINE: "Routine",
}

PRIORITY_MEANS: dict[str, str] = {
    ACT_NOW: ("Something has already happened that the bank can act on, on an "
              "exposure large enough to matter."),
    REVIEW: ("Enough independent evidence to bring the next credit review "
             "forward rather than wait for it."),
    MONITOR: ("Evidence worth carrying into the next review, not worth "
              "interrupting it."),
    ROUTINE: "Nothing governed fires for this borrower at this date.",
}

# --------------------------------------------------------------- the numbers

#: Exposure at or above which a condition is material enough to act on, in the
#: millions the book is kept in. A covenant breach on a SAR 3m facility is a
#: letter; on a SAR 400m facility it is a meeting. Set where roughly a third of
#: this book sits: a floor most of the book clears is not a floor.
MATERIAL_EXPOSURE = 250.0

#: A collateral shortfall this large a share of the exposure is the recovery
#: assumption failing. Below it, it is a valuation to refresh: a gap of SAR 9m
#: behind SAR 400m of exposure does not need anybody today, and a policy that
#: says it does produces a list nobody can work.
MATERIAL_SHORTFALL_SHARE = 0.10

#: Arrears that are a fact rather than a warning.
DEFAULT_DPD = 90
#: Arrears that are a warning.
ARREARS_DPD = 30

#: Families firing together before breadth alone is worth a review. Five, not
#: three: with forty-three conditions across eight families the median
#: borrower already carries four, so three families is the middle of the book
#: rather than a signal about one name.
BROAD_FAMILIES = 5

OWNER = tx.THRESHOLD_OWNER


@dataclass
class Reason:
    """One rule that held, and how to say it."""

    rule: str
    level: str
    says: str

    def to_dict(self) -> dict[str, Any]:
        return {"rule": self.rule, "level": self.level, "says": self.says}


@dataclass
class Verdict:
    """The priority, and every rule behind it."""

    priority: str = ROUTINE
    reasons: list[Reason] = field(default_factory=list)
    exposure: float | None = None
    material: bool = False
    version: str = PRIORITY_VERSION

    @property
    def label(self) -> str:
        return PRIORITY_LABEL.get(self.priority, self.priority)

    @property
    def means(self) -> str:
        return PRIORITY_MEANS.get(self.priority, "")

    def because(self) -> list[str]:
        """The sentences that put it at this level, worst rule first.

        Never empty. A caller that prints only this must still have something
        to print for a borrower nothing fires on.
        """
        top = [r.says for r in self.reasons if r.level == self.priority]
        return top or [r.says for r in self.reasons] or [self.means]

    def to_dict(self) -> dict[str, Any]:
        return {
            "priority": self.priority, "priority_label": self.label,
            "priority_means": self.means,
            "priority_because": self.because(),
            "priority_reasons": [r.to_dict() for r in self.reasons],
            "priority_owner": OWNER, "priority_version": self.version,
            "exposure": self.exposure, "material": self.material,
        }


def _amount(row: dict[str, Any], name: str) -> float | None:
    value = row.get(name)
    if value is None or isinstance(value, bool):
        return None
    try:
        found = float(value)
    except (TypeError, ValueError):
        return None
    return None if found != found else found


def _money(millions: float | None) -> str:
    """The way a credit officer writes it down. R2 §3."""
    if millions is None:
        return "an exposure this deployment does not carry"
    if abs(millions) >= 1000:
        return f"{tx.CURRENCY} {millions / 1000:,.1f}bn"
    return f"{tx.CURRENCY} {millions:,.1f}m"


def decide(standing: Any, row: dict[str, Any] | None = None) -> Verdict:
    """What to do about this borrower. R2 §25.

    `standing` is a `signals.Standing`; `row` the borrower's own record, which
    carries the facts the taxonomy does not model as signals — how much is
    drawn, what stage it is booked at, how far past due it is.
    """
    row = row or {}
    exposure = _amount(row, "drawn_exposure")
    material = exposure is not None and exposure >= MATERIAL_EXPOSURE
    verdict = Verdict(exposure=exposure, material=material)
    size = _money(exposure)

    fired = {o.signal for o in getattr(standing, "fired", [])}
    families = int(getattr(standing, "breadth", 0) or 0)
    severity = str(getattr(standing, "severity", "") or "")
    worsening = int(getattr(standing, "worsening", 0) or 0)
    improving = int(getattr(standing, "improving", 0) or 0)

    dpd = _amount(row, "current_dpd") or 0.0
    stage = _amount(row, "stage") or 0.0
    breached = bool(row.get("breach_flag")) or bool(
        (_amount(row, "covenants_breached") or 0) > 0)
    gap = _amount(row, "collateral_shortfall") or 0.0
    shortfall = gap > 0.0
    share = gap / exposure if exposure else 0.0
    #: Whether recovery is actually in question. More than half this book
    #: carries some collateral shortfall, because much corporate lending is
    #: unsecured by design — so a shortfall on a performing, well-rated name
    #: is a policy choice rather than a problem, and a priority that treats
    #: the two the same produces a list nobody can work.
    #: The severe evidence has to be INDEPENDENT of the collateral, or the
    #: rule unlocks itself: a large shortfall raises a severe collateral
    #: signal, which would then be the distress that justifies acting on the
    #: shortfall. A borrower is deteriorating for reasons other than its
    #: security, or it is a well-secured-on-paper borrower with a valuation
    #: problem.
    severe_elsewhere = any(o.severity == tx.SEVERE and o.family != tx.COLLATERAL
                           for o in getattr(standing, "fired", []))
    distressed = stage >= 2 or dpd >= ARREARS_DPD or severe_elsewhere

    def note(rule: str, level: str, says: str) -> None:
        verdict.reasons.append(Reason(rule, level, says))

    # ---- act now -------------------------------------------------------
    if stage >= 3:
        note("booked_impaired", ACT_NOW,
             f"Booked at IFRS 9 stage 3. This is the accounting position at "
             f"the reporting date, not a forecast. Exposure {size}.")
    if dpd >= DEFAULT_DPD:
        note("in_default", ACT_NOW,
             f"{int(dpd)} days past due on {size}. Past ninety days this is a "
             f"fact about payment rather than a warning about it.")
    if breached and material:
        note("covenant_breached_material", ACT_NOW,
             f"A covenant is breached on {size}. The bank holds a contractual "
             f"right it can choose to use.")
    if shortfall and material and share >= MATERIAL_SHORTFALL_SHARE and distressed:
        note("collateral_shortfall_material", ACT_NOW,
             f"Security is short of the exposure by {_money(gap)} — "
             f"{share * 100:.0f}% of {size} — on a borrower already showing "
             f"distress. Lending unsecured to a sound name is a policy "
             f"choice; doing it to a deteriorating one is the recovery "
             f"assumption behind the provision failing.")

    # ---- bring the review forward ---------------------------------------
    # The two EVIDENCE-ONLY rules are gated on materiality, for the same
    # reason the act-now rules are: evidence alone, on an exposure the bank
    # would not convene a meeting about, is something to carry into the next
    # review rather than something to move the review for. The rules below
    # them turn on FACTS — arrears, a breach, a booked stage — and those hold
    # whatever the facility is worth.
    if severity == tx.SEVERE and families >= 3 and material:
        note("severe_and_broad", REVIEW,
             f"A severe condition, with corroborating evidence in "
             f"{families} independent families, on {size}. Severe evidence is "
             f"a reason to look again; it is not, on its own, something the "
             f"bank can act on.")
    elif severity == tx.SEVERE and material:
        note("severe", REVIEW,
             f"At least one condition is severe on its own terms, on {size}.")
    if families >= BROAD_FAMILIES and material:
        note("broad", REVIEW,
             f"{families} independent families of evidence point the same "
             f"way. One number read several ways would not do that.")
    if ARREARS_DPD <= dpd < DEFAULT_DPD:
        note("in_arrears", REVIEW,
             f"{int(dpd)} days past due on {size}.")
    if breached and not material:
        note("covenant_breached", REVIEW,
             f"A covenant is breached. The exposure of {size} is below the "
             f"materiality this policy acts on, so it is a review item.")
    if (shortfall and share >= MATERIAL_SHORTFALL_SHARE
            and not (material and distressed)):
        note("collateral_shortfall", REVIEW,
             f"Security is short of the exposure by {_money(gap)} against "
             f"{size}. A valuation to refresh rather than a call to make.")
    if stage >= 2 and worsening:
        note("stage_two_worsening", REVIEW,
             f"Booked at IFRS 9 stage 2, and {worsening} condition"
             f"{'' if worsening == 1 else 's'} moved further the wrong way "
             f"this quarter.")

    # ---- monitor --------------------------------------------------------
    if fired:
        note("something_fires", MONITOR,
             f"{len(fired)} governed condition"
             f"{'' if len(fired) == 1 else 's'} fire on {size}.")
    if improving and not any(r.level == ACT_NOW for r in verdict.reasons):
        note("improving", MONITOR,
             f"{improving} condition{'' if improving == 1 else 's'} moved back "
             f"towards the threshold. Evidence pointing the other way is part "
             f"of the picture, not an argument against looking.")

    for level in (ACT_NOW, REVIEW, MONITOR):
        if any(r.level == level for r in verdict.reasons):
            verdict.priority = level
            break
    return verdict


__all__ = ["ACT_NOW", "ARREARS_DPD", "BROAD_FAMILIES", "DEFAULT_DPD",
           "MATERIAL_EXPOSURE", "MATERIAL_SHORTFALL_SHARE", "MONITOR",
           "OWNER", "PRIORITIES",
           "PRIORITY_LABEL", "PRIORITY_MEANS", "PRIORITY_RANK",
           "PRIORITY_VERSION", "REVIEW", "ROUTINE", "Reason", "Verdict",
           "decide"]
