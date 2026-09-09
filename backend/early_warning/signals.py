"""Which signals a borrower actually shows, and what happened to them. §23-§26.

Three things happen here, in order, and each is separately checkable.

**1. Evaluate.** Every governed signal in `taxonomy` is tested against the
borrower's row at a reporting period, and against its row at the period before
where the test is a movement. A signal produces one `Observation` carrying the
value, the previous value, the threshold it was tested against and the version
of that threshold — §23's governed signal object. A signal whose field this
deployment does not carry produces an UNAVAILABLE observation rather than a
silent non-firing (§7).

**2. Lifecycle.** §24 asks CreditProbe to distinguish one-period noise from
persistent deterioration from acceleration from recovery. That distinction is
not in one period's data; it is in the comparison of consecutive periods. So a
signal that fired last period and fires again is PERSISTING, one whose measure
has moved further the wrong way is WORSENING, one that has stopped firing is
CURED, and one nobody has seen before is NEW.

**3. Compose, transparently.** §25 forbids "arbitrary weighted black-box
scores" and names what to use instead: breadth of independent evidence,
severity, persistence, materiality, agreement and conflict. So a borrower's
standing is those numbers, side by side, with no coefficient over any of them.
"Four families, two of them severe, three persisting for three periods" is a
sentence a credit officer can argue with. "7.3" is not.

Why no weights at all
---------------------
A weighted score needs weights; weights need an owner, a methodology, a
version and a validation; and an unowned weight in the middle of a credit
decision is the thing this codebase spends most of its governance preventing.
§25 permits weights WITH all of that. Until somebody supplies it, counting is
the honest arithmetic — and counting families rather than signals, because
five liquidity signals firing off one utilisation number is one fact, not
five.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from backend.early_warning import taxonomy as tx

logger = logging.getLogger(__name__)

SIGNALS_VERSION = "1.0.0"

# --------------------------------------------------------------- lifecycle

NEW = "NEW"
PERSISTING = "PERSISTING"
WORSENING = "WORSENING"
IMPROVING = "IMPROVING"
CURED = "CURED"
UNAVAILABLE = "UNAVAILABLE"

LIFECYCLE: tuple[str, ...] = (NEW, PERSISTING, WORSENING, IMPROVING, CURED,
                              UNAVAILABLE)

LIFECYCLE_MEANS: dict[str, str] = {
    NEW: "Not present at the previous reporting date.",
    PERSISTING: "Present at the previous reporting date, at a similar level.",
    WORSENING: "Present before, and the measure has moved further the wrong way.",
    IMPROVING: "Still firing, but the measure has moved back towards the threshold.",
    CURED: "Fired at the previous reporting date and does not fire now.",
    UNAVAILABLE: "This deployment does not carry the field this signal reads.",
}

#: A movement smaller than this share of the threshold is not a movement — it
#: is the same position measured again. Without it, every signal on a
#: continuous measure reports WORSENING or IMPROVING every quarter and the
#: lifecycle stops carrying information.
MATERIAL_MOVE = 0.05


@dataclass
class Observation:
    """One signal, tested against one borrower at one period. §23."""

    signal: str
    family: str
    label: str
    fired: bool = False
    lifecycle: str = NEW
    severity: str = tx.CONCERN
    value: Any = None
    previous: Any = None
    movement: float | None = None
    threshold: Any = None
    threshold_version: str = tx.TAXONOMY_VERSION
    threshold_owner: str = tx.THRESHOLD_OWNER
    dataset: str = ""
    field_name: str = ""
    test: str = ""
    #: What `value`, `previous` and `threshold` are denominated in. R2 §3: a
    #: screen showing "Value 75.4" beside "Threshold 10" is asking the reader
    #: to guess, and the two numbers may not even be the same kind of thing.
    unit: str = tx.COUNT
    period: str = ""
    previous_period: str = ""
    booked_accounting: bool = False
    #: Why this signal could not be tested, when it could not be.
    unavailable: str = ""
    #: The sentence a screen shows. Composed here so the screen and the
    #: analyst's tools cannot word the same evidence differently.
    means: str = ""

    @property
    def available(self) -> bool:
        return not self.unavailable

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal": self.signal, "family": self.family,
            "family_label": tx.FAMILIES.get(self.family, self.family),
            "label": self.label, "fired": self.fired,
            "lifecycle": self.lifecycle,
            "lifecycle_means": LIFECYCLE_MEANS.get(self.lifecycle, ""),
            "severity": self.severity, "value": self.value,
            "previous": self.previous, "movement": self.movement,
            "threshold": self.threshold,
            "threshold_version": self.threshold_version,
            "threshold_owner": self.threshold_owner,
            "dataset": self.dataset, "field": self.field_name,
            "test": self.test, "unit": self.unit,
            "currency": tx.CURRENCY, "period": self.period,
            "previous_period": self.previous_period,
            "booked_accounting": self.booked_accounting,
            "unavailable": self.unavailable, "means": self.means,
            "available": self.available,
            # §11H: what the BORROWER is doing on this condition, in credit
            # language rather than in lifecycle vocabulary.
            "state": _state_of(self),
        }


def _state_of(observation: Observation) -> str:
    """Section 11H, deferred so the two modules do not import in a circle."""
    from backend.early_warning import assessment

    return assessment.state_of(observation)


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        found = float(value)
    except (TypeError, ValueError):
        return None
    return None if found != found else found


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def _ratio(row: dict[str, Any], signal: tx.Signal) -> float | None:
    """`field` over `against`, as a percentage. None if either is missing."""
    top = _number(row.get(signal.field))
    bottom = _number(row.get(signal.against))
    if top is None or bottom is None or bottom == 0:
        return None
    return 100.0 * top / bottom


def _fires_ratio(signal: tx.Signal, row: dict[str, Any],
                 previous: dict[str, Any]) -> bool | None:
    now = _ratio(row, signal)
    if now is None:
        return None
    if signal.test == tx.RATIO_ABOVE:
        # A NEGATIVE threshold means "below its absolute value" — used where
        # the worrying direction is downward (undrawn headroom) and writing a
        # second test for one signal would be worse than one sign convention
        # stated in one place.
        threshold = float(signal.threshold)
        return now <= -threshold if threshold < 0 else now >= threshold
    was = _ratio(previous, signal)
    if was is None:
        return None
    return (now - was) >= float(signal.threshold)


def _fires(signal: tx.Signal, value: Any, previous: Any) -> bool | None:
    """Whether this signal fires. None means it could not be tested."""
    if signal.test == tx.TRUE:
        return _truthy(value)
    if signal.test == tx.EQUALS:
        # A governed categorical taking a named value. Compared as text and
        # case-insensitively, because "Negative" and "NEGATIVE" are the same
        # agency outlook and a signal that missed one would be silently
        # incomplete.
        return str(value or "").strip().lower() == str(
            signal.threshold or "").strip().lower()
    now = _number(value)
    if now is None:
        return None
    if signal.test == tx.ABOVE:
        return now >= float(signal.threshold)
    if signal.test == tx.BELOW:
        return now < float(signal.threshold)
    was = _number(previous)
    if was is None:
        # A movement test needs two periods. At the earliest period in the
        # book there is no prior row, and reporting "did not fire" would be a
        # claim the data cannot support.
        return None
    if signal.test == tx.ROSE_BY:
        return (now - was) >= float(signal.threshold)
    if signal.test == tx.FELL_BY:
        return (was - now) >= float(signal.threshold)
    if signal.test == tx.CHANGED:
        return value != previous
    return None


def evaluate(row: dict[str, Any], previous: dict[str, Any] | None = None, *,
             period: str = "", previous_period: str = "",
             signals: tuple[tx.Signal, ...] = tx.SIGNALS) -> list[Observation]:
    """Every governed signal, tested against one borrower. §23.

    Returns an observation for EVERY signal, fired or not, available or not.
    A caller wanting only what fired filters; a caller wanting to know what was
    checked and could not be has the answer without asking a second question.
    """
    previous = previous or {}
    out: list[Observation] = []
    for signal in signals:
        observation = Observation(
            signal=signal.key, family=signal.family, label=signal.label,
            severity=signal.severity, threshold=signal.threshold,
            dataset=signal.dataset, field_name=signal.field,
            test=signal.test, unit=signal.unit, period=period,
            previous_period=previous_period,
            booked_accounting=signal.booked_accounting, means=signal.means)

        if signal.field not in row:
            observation.unavailable = (
                f"{signal.dataset} does not carry {signal.field} in this "
                "deployment, so this condition was not tested.")
            observation.lifecycle = UNAVAILABLE
            out.append(observation)
            continue

        observation.value = row.get(signal.field)
        observation.previous = previous.get(signal.field)
        if signal.test in (tx.RATIO_ABOVE, tx.RATIO_ROSE_BY):
            observation.value = _ratio(row, signal)
            observation.previous = _ratio(previous, signal)
            fired = _fires_ratio(signal, row, previous)
        else:
            fired = _fires(signal, observation.value, observation.previous)
        if fired is None:
            observation.unavailable = (
                "No value at this reporting date"
                if _number(observation.value) is None
                and signal.test != tx.TRUE
                else "No prior reporting date to compare with")
            observation.lifecycle = UNAVAILABLE
            out.append(observation)
            continue

        observation.fired = fired
        now, was = _number(observation.value), _number(observation.previous)
        if now is not None and was is not None:
            observation.movement = now - was
        observation.lifecycle = _lifecycle(signal, observation, previous)
        out.append(observation)
    return out


def _lifecycle(signal: tx.Signal, observation: Observation,
               previous: dict[str, Any]) -> str:
    """What happened to this signal since the last reporting date. §24."""
    if not previous:
        # Nothing to compare with. Everything firing at the earliest period in
        # the book is NEW, which is true and is why a first-period screen
        # cannot say anything about persistence.
        return NEW
    # The prior period's own firing state. A movement test needs the period
    # BEFORE that to be evaluated properly; with only two periods in hand the
    # honest approximation is to test the prior row against itself, which
    # makes a movement test read as not-firing then — so a signal that has
    # just started moving reads NEW rather than PERSISTING. That is the right
    # direction to be wrong in: it says "this is new" about something that
    # may have been building, rather than "this has been here a while" about
    # something that has not.
    fired_before = (
        _fires_ratio(signal, previous, previous)
        if signal.test in (tx.RATIO_ABOVE, tx.RATIO_ROSE_BY)
        else _fires(signal, previous.get(signal.field),
                    previous.get(signal.field)))
    if not observation.fired:
        return CURED if fired_before else NEW
    if not fired_before:
        return NEW
    move = observation.movement
    if move is None or not signal.threshold:
        return PERSISTING
    scale = abs(float(signal.threshold)) or 1.0
    if abs(move) < MATERIAL_MOVE * scale:
        return PERSISTING
    # Which direction is "worse" depends on the test, not on the sign.
    worse = (move > 0 if signal.test in (tx.ABOVE, tx.ROSE_BY, tx.RATIO_ABOVE,
                                        tx.RATIO_ROSE_BY) else move < 0)
    return WORSENING if worse else IMPROVING


# ------------------------------------------------------------- the composite


@dataclass
class Standing:
    """A borrower's early-warning position, without a score. §25."""

    borrower_id: str = ""
    period: str = ""
    #: Signals that fired, in taxonomy order.
    fired: list[Observation] = field(default_factory=list)
    #: Signals that could not be tested here, and why. §7.
    untested: list[Observation] = field(default_factory=list)
    #: Signals that fired last period and do not now.
    cured: list[Observation] = field(default_factory=list)
    #: EVERY governed signal tested against this borrower, fired or not and
    #: available or not. The borrower scorecard needs the ones that did NOT
    #: fire — a layer showing three amber rows and hiding the eleven green
    #: ones reads as an emergency whatever the borrower is doing — and
    #: recomputing them loses the lifecycle, which only exists because two
    #: periods were compared here.
    observations: list[Observation] = field(default_factory=list)
    #: The borrower's own record. R2 §25 decides what to DO about a borrower
    #: from facts the taxonomy does not model as signals — how much is drawn,
    #: what stage it is booked at, how far past due it is — so the position
    #: has to keep the row it was read from.
    record: dict[str, Any] = field(default_factory=dict)

    # ---- the six transparent measures §25 names -------------------------
    @property
    def breadth(self) -> int:
        """How many INDEPENDENT families fired.

        Families rather than signals: five liquidity conditions firing off one
        utilisation number is one fact told five ways, and counting it as five
        is exactly the inflation a weighted score would also produce.
        """
        return len({o.family for o in self.fired})

    @property
    def severity(self) -> str:
        if any(o.severity == tx.SEVERE for o in self.fired):
            return tx.SEVERE
        if any(o.severity == tx.CONCERN for o in self.fired):
            return tx.CONCERN
        return tx.WATCH

    @property
    def persistence(self) -> int:
        """How many of the fired signals were already firing."""
        return sum(1 for o in self.fired
                   if o.lifecycle in (PERSISTING, WORSENING))

    @property
    def worsening(self) -> int:
        return sum(1 for o in self.fired if o.lifecycle == WORSENING)

    @property
    def improving(self) -> int:
        return sum(1 for o in self.fired if o.lifecycle == IMPROVING)

    @property
    def agreement(self) -> list[str]:
        """Families whose evidence points the same way — deterioration."""
        return sorted({o.family for o in self.fired})

    @property
    def conflict(self) -> list[str]:
        """Evidence pointing the other way. §26 asks for it by name.

        A borrower with four deteriorating signals and two improving ones is a
        different situation from one with four and none, and a case that shows
        only the four is a case somebody will act on wrongly.
        """
        return sorted({o.family for o in self.fired
                       if o.lifecycle == IMPROVING}
                      | {o.family for o in self.cured})

    @property
    def booked_stage(self) -> list[str]:
        """Signals that are the BOOKED accounting position, not a prediction.

        §20: never describe an early-warning prediction as an accounting stage
        classification. Keeping them separable is how that stays true when
        somebody writes the case summary.
        """
        return [o.signal for o in self.fired if o.booked_accounting]

    @property
    def verdict(self) -> Any:
        """What to do about this borrower, and why. R2 §25.

        Severity says how bad the worst RULE is. This says how bad the
        BORROWER is, which is a different question and the one an officer
        working down a list is actually asking.
        """
        from backend.early_warning import priority
        return priority.decide(self, self.record)

    @property
    def priority(self) -> str:
        return str(self.verdict.priority)

    @property
    def assessment(self) -> Any:
        """How serious this borrower's position is, and why. Section 11G.

        Distinct from `severity`, which is about the worst RULE, and from
        `priority`, which is about what to DO. This is the overall Early
        Warning risk level, and it is derived from gravity and corroboration
        rather than from how many signals happen to have fired.
        """
        from backend.early_warning import assessment

        return assessment.assess(self, self.record)

    @property
    def risk_level(self) -> str:
        return str(self.assessment.level)

    def sentence(self) -> str:
        """The standing, said the way a credit officer would say it."""
        if not self.fired:
            return ("No governed early-warning signal fires for this borrower "
                    f"at {self.period}.")
        families = ", ".join(tx.FAMILIES.get(f, f).lower()
                             for f in self.agreement)
        parts = [f"{len(self.fired)} governed signal"
                 f"{'' if len(self.fired) == 1 else 's'} across "
                 f"{self.breadth} famil{'y' if self.breadth == 1 else 'ies'} "
                 f"({families})"]
        if self.severity == tx.SEVERE:
            parts.append("at least one of them severe")
        if self.persistence:
            parts.append(f"{self.persistence} already firing last period")
        if self.worsening:
            parts.append(f"{self.worsening} worse than last period")
        if self.conflict:
            parts.append(
                f"and evidence pointing the other way in "
                f"{', '.join(tx.FAMILIES.get(f, f).lower() for f in self.conflict)}")
        return "; ".join(parts) + "."

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": SIGNALS_VERSION,
            "borrower_id": self.borrower_id, "period": self.period,
            "sentence": self.sentence(),
            # §25: the transparent measures, side by side, with no coefficient
            # over any of them. There is deliberately no "score" key.
            "breadth": self.breadth, "severity": self.severity,
            "persistence": self.persistence, "worsening": self.worsening,
            "improving": self.improving,
            "agreement": self.agreement, "conflict": self.conflict,
            "booked_accounting_signals": self.booked_stage,
            # §25: severity is about the rule; priority is about the borrower.
            # Both are published, and every rule behind the priority comes
            # with the sentence that put it there.
            **self.verdict.to_dict(),
            # §11G: how serious it is, as opposed to what to do about it.
            "assessment": self.assessment.to_dict(),
            "risk_level": self.risk_level,
            "fired": [o.to_dict() for o in self.fired],
            "cured": [o.to_dict() for o in self.cured],
            "untested": [o.to_dict() for o in self.untested],
            "families": {
                key: [o.signal for o in self.fired if o.family == key]
                for key in tx.FAMILIES
            },
        }


def stand(row: dict[str, Any], previous: dict[str, Any] | None = None, *,
          borrower_id: str = "", period: str = "",
          previous_period: str = "") -> Standing:
    """One borrower's whole early-warning position. §23, §24, §25."""
    observations = evaluate(row, previous, period=period,
                            previous_period=previous_period)
    return Standing(
        borrower_id=borrower_id or str(row.get("borrower_id") or ""),
        period=period or str(row.get("period") or ""),
        fired=[o for o in observations if o.fired and o.available],
        cured=[o for o in observations if o.lifecycle == CURED],
        untested=[o for o in observations if not o.available],
        observations=list(observations),
        record=dict(row),
    )


def rank(standings: list[Standing]) -> list[Standing]:
    """Borrowers ordered by what to do about them, deterministically.

    R2 §25. This used to lead on BREADTH — how many families of rules fired —
    which put a small facility with five stale-ish measures above a SAR 400m
    exposure in covenant breach and ninety days past due. An officer working
    down that list works down it in the wrong order.

    Priority first, then the exposure at stake, then breadth, severity,
    persistence and how many are getting worse, and finally the borrower id so
    the tenth row is the same tenth row on a second visit (§11). Every step is
    a fact somebody can check.
    """
    return sorted(
        standings,
        key=lambda s: (-priority_rank(s), -(s.verdict.exposure or 0.0),
                       -s.breadth, -tx.SEVERITY_RANK.get(s.severity, 0),
                       -s.persistence, -s.worsening, s.borrower_id))


def priority_rank(standing: Standing) -> int:
    from backend.early_warning import priority
    return priority.PRIORITY_RANK.get(standing.priority, 0)


__all__ = ["CURED", "IMPROVING", "LIFECYCLE", "LIFECYCLE_MEANS",
           "MATERIAL_MOVE", "NEW", "Observation", "PERSISTING",
           "SIGNALS_VERSION", "Standing", "UNAVAILABLE", "WORSENING",
           "dashboard", "evaluate", "rank", "stand"]


# ------------------------------------------------------- over the whole book


def _period_key(period: str) -> tuple[int, int]:
    """A reporting-period label, as something that sorts chronologically."""
    import re

    found = re.match(r"\s*Q([1-4])\s+(\d{4})", str(period))
    if found:
        return (int(found.group(2)), int(found.group(1)))
    found = re.match(r"\s*(\d{4})[-/]?Q?([1-4])?", str(period))
    if found:
        return (int(found.group(1)), int(found.group(2) or 0))
    return (0, 0)


def portfolio(period: str = "", *, limit: int = 100,
              source: Any = None) -> dict[str, Any]:
    """Every borrower's standing at one period, ranked. §28.

    Reads the Borrower 360 snapshot at `period` and the period before it,
    because a lifecycle is a statement about two periods and cannot be made
    from one.

    Bounded by `limit` rows RETURNED, never by rows evaluated: a screen
    showing the twenty worst names must have looked at all of them, or the
    twenty are the twenty it happened to load.

    Memoised per period. Standing up three thousand borrowers against
    thirty-four conditions takes a little over two seconds, and a screen that
    pays that on every load is a screen people stop opening - so the ranked
    result is held and sliced. The cache is keyed on the period and inherits
    the lifetime of `corporate._load`, which is itself memoised for the life
    of the process; `reset()` clears both, and the bootstrap calls it after
    regenerating the lake. Nothing here caches a figure the snapshot could
    have changed underneath.
    """
    del source
    return _slice(_book(period), limit)


def dashboard(period: str = "") -> dict[str, Any]:
    """The Early Warning landing page, in business terms. R2 §10.

    Built from the SAME standings the ranked list is built from, so a KPI and
    the list behind it cannot disagree about how many borrowers there are.
    """
    from backend.early_warning import dashboard as db

    book = _book(period)
    return db.build(book.get("_ranked") or [],
                    period=str(book.get("period") or ""),
                    previous_period=str(book.get("previous_period") or ""),
                    evaluated=int(book.get("evaluated") or 0))


def reset() -> None:
    """Forget the memoised book. Called after the lake is regenerated."""
    from backend.corporate import service as corporate
    from backend.early_warning import cases as ews_cases

    _book.cache_clear()
    ews_cases._standings.cache_clear()
    corporate._load.cache_clear()


def _slice(book: dict[str, Any], limit: int) -> dict[str, Any]:
    ranked: list[Standing] = book.get("_ranked") or []
    out = {k: v for k, v in book.items() if not k.startswith("_")}
    out["returned"] = min(limit, len(ranked))
    out["borrowers"] = [s.to_dict() for s in ranked[:limit]]
    return out


@lru_cache(maxsize=8)
def _book(period: str = "") -> dict[str, Any]:
    """Every borrower stood up at one period, ranked, without the slicing."""
    import pandas as pd

    from backend.corporate import service as corporate

    snapshot: pd.DataFrame = corporate._load(corporate.SNAPSHOT)
    # Sorted by (year, quarter), never as strings. "Q4 2025" sorts after
    # "Q2 2026" alphabetically, so a string sort put the latest period a year
    # and two quarters in the past and compared it with the wrong prior one —
    # which makes every lifecycle verdict in the result about the wrong pair
    # of dates.
    periods = sorted((str(p) for p in snapshot["period"].unique()),
                     key=_period_key)
    if not periods:
        return {"version": SIGNALS_VERSION, "period": "", "evaluated": 0,
                "note": "This book carries no periods.", "_ranked": []}
    chosen = period or periods[-1]
    if chosen not in periods:
        return {"version": SIGNALS_VERSION, "period": chosen, "evaluated": 0,
                "note": f"{chosen} is not a period this book holds.",
                "_ranked": []}
    index = periods.index(chosen)
    prior = periods[index - 1] if index else ""

    current = snapshot[snapshot["period"] == chosen]
    previous = (snapshot[snapshot["period"] == prior].set_index("borrower_id")
                if prior else None)

    standings: list[Standing] = []
    for record in current.to_dict("records"):
        borrower = str(record.get("borrower_id") or "")
        before: dict[str, Any] = {}
        if previous is not None and borrower in previous.index:
            before = previous.loc[borrower].to_dict()
        standings.append(stand(record, before, borrower_id=borrower,
                               period=chosen, previous_period=prior))

    ranked = rank([s for s in standings if s.fired])
    return {
        "version": SIGNALS_VERSION,
        "taxonomy_version": tx.TAXONOMY_VERSION,
        "period": chosen,
        "previous_period": prior,
        "evaluated": len(standings),
        "with_signals": len(ranked),
        "headline": headline(standings),
        # How many conditions each borrower was tested against, published
        # rather than left for a screen to hard-code. A caption that says
        # "34 governed conditions" and a taxonomy that carries thirty-five
        # is a small lie that nobody notices until somebody counts.
        "signal_count": len(tx.SIGNALS),
        "unavailable": tx.unavailable(),
        "origin": corporate.ORIGIN,
        # Private, and stripped by `_slice`: the ranked standings themselves,
        # held so a second request for the same period pays nothing.
        "_ranked": ranked,
    }


def headline(standings: list[Standing]) -> dict[str, Any]:
    """What a head of credit reads first. §28.

    Counts of SITUATIONS, not of raw signals. "New signals: 4,812" tells
    nobody anything; "borrowers with a new signal: 214" is a queue.
    """
    with_new = sum(1 for s in standings
                   if any(o.lifecycle == NEW for o in s.fired))
    worsening = sum(1 for s in standings if s.worsening)
    persisting = sum(1 for s in standings if s.persistence)
    cured = sum(1 for s in standings if s.cured and not s.fired)
    severe = sum(1 for s in standings
                 if s.fired and s.severity == tx.SEVERE)
    multi = sum(1 for s in standings if s.breadth >= 3)
    booked_two = sum(1 for s in standings if "stage_2" in s.booked_stage)
    covenant = sum(1 for s in standings
                   if any(o.family == tx.COVENANT for o in s.fired))
    collateral = sum(1 for s in standings
                     if any(o.family == tx.COLLATERAL for o in s.fired))
    return {
        "borrowers": len(standings),
        "with_a_new_signal": with_new,
        "worsening": worsening,
        "persisting": persisting,
        "cured": cured,
        "severe": severe,
        "multi_family": multi,
        "booked_stage_2_or_worse": booked_two,
        "covenant_pressure": covenant,
        "collateral_pressure": collateral,
        "means": {
            "with_a_new_signal":
                "Borrowers showing at least one condition that was not "
                "present at the previous reporting date.",
            "multi_family":
                "Borrowers whose evidence spans three or more independent "
                "families. §25: breadth of independent evidence, not a score.",
            "booked_stage_2_or_worse":
                "The BOOKED IFRS 9 position, not a prediction that a borrower "
                "will migrate.",
        },
    }
