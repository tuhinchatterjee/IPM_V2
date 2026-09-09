"""
The C in TAC: several pieces of evidence combining into a recognised pattern.

Why a classifier is not just another threshold
----------------------------------------------
A threshold signal says "DSCR is below 1.2". A classifier says "this looks like
LIQUIDITY STRESS" — and it says it because three separate things are true at
once, none of which would carry the conclusion alone. The difference matters to
a credit officer: a single threshold is a number to check, and a pattern is a
hypothesis to investigate.

The temptation is to make everything a classifier, because a named pattern
sounds more intelligent than a comparison. That is exactly the overclaim the
brief forbids — "Do not claim a classifier exists if it is not configured" — so
there are five, each with a rule written down, and every signal that is not one
of them is honestly reported as threshold-based or action-based.

A classifier fires only on signals that were actually EVALUATED. A pattern
built partly on evidence that could not be tested is not a pattern; it is a
guess with a name, and `available` records the difference.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.early_warning import taxonomy as tx

CLASSIFIER_VERSION = "1.0.0"
CLASSIFIER_OWNER = tx.THRESHOLD_OWNER


@dataclass(frozen=True)
class Classifier:
    """A named pattern over other signals, with the rule stated."""

    key: str
    label: str
    #: What a credit officer should understand from it firing.
    means: str
    #: Signal keys that make up the pattern.
    signals: tuple[str, ...]
    #: How many of them must be firing. Never all of them by default: a
    #: pattern that needs every component is an AND of thresholds wearing a
    #: name.
    needs: int
    severity: str = tx.CONCERN
    #: The credit-risk layer this pattern belongs to, for the four-layer view.
    family: str = tx.LIQUIDITY
    #: Extra evidence that strengthens it but is not required.
    corroborating: tuple[str, ...] = field(default_factory=tuple)
    version: str = CLASSIFIER_VERSION

    def rule(self) -> str:
        names = [tx.BY_KEY[k].label for k in self.signals if k in tx.BY_KEY]
        return (f"At least {self.needs} of: " + "; ".join(names)) if names else ""

    def to_dict(self) -> dict[str, Any]:
        return {"key": self.key, "label": self.label, "means": self.means,
                "signals": list(self.signals), "needs": self.needs,
                "severity": self.severity, "family": self.family,
                "family_label": tx.FAMILIES.get(self.family, self.family),
                "corroborating": list(self.corroborating),
                "tac": tx.CLASSIFIER_BASED, "tac_letter": "C",
                "owner": CLASSIFIER_OWNER, "version": self.version,
                "rule": self.rule()}


#: The configured patterns. Five, because five are configured.
CLASSIFIERS: tuple[Classifier, ...] = (
    Classifier(
        key="liquidity_stress", label="Liquidity stress",
        means=("Cash, debt service and facility headroom are deteriorating "
               "together. Individually each is arguable; together they "
               "describe a borrower that may not be able to pay."),
        signals=("cash_thin", "liquidity_buffer_thin", "utilisation_high",
                 "near_maturity_uncovered", "committed_headroom_thin"),
        needs=3, severity=tx.SEVERE, family=tx.LIQUIDITY,
        corroborating=("in_arrears", "cash_cycle_stretched")),
    Classifier(
        key="rating_lag", label="Rating lag",
        means=("The modelled and accounting evidence has moved but the "
               "internal grade has not. The rating may be stale rather than "
               "the borrower being sound."),
        signals=("pd_rose", "ecl_rose", "sicr_flagged", "stage_2"),
        needs=2, severity=tx.CONCERN, family=tx.RATING,
        corroborating=("interest_cover_weak", "leverage_high")),
    Classifier(
        key="hidden_deterioration", label="Hidden deterioration",
        means=("Fundamentals are weakening while the borrower is still "
               "performing and still off the watchlist. This is the "
               "population an early-warning framework exists to find."),
        signals=("revenue_fell", "ebitda_margin_fell", "cash_flow_negative",
                 "interest_cover_weak", "leverage_high"),
        needs=3, severity=tx.CONCERN, family=tx.FINANCIAL,
        corroborating=("cash_thin", "covenant_headroom_tight")),
    Classifier(
        key="stage2_candidate", label="Stage 2 candidate",
        means=("Credit quality has moved far enough that a significant "
               "increase in credit risk is plausible at the next reporting "
               "date, even where no trigger has fired yet."),
        signals=("pd_rose", "rating_downgraded", "on_watchlist",
                 "covenant_breached", "in_arrears"),
        needs=2, severity=tx.CONCERN, family=tx.IFRS9,
        corroborating=("ecl_rose",)),
    Classifier(
        key="external_vulnerability", label="External vulnerability",
        means=("The borrower is exposed to conditions outside its own control "
               "— an agency view, a concentrated sector, or a position in the "
               "connected group through which trouble travels."),
        signals=("outlook_negative", "sector_concentrated",
                 "network_risk_high", "group_large", "contagion_material"),
        needs=2, severity=tx.WATCH, family=tx.EXTERNAL,
        corroborating=("rating_downgraded",)),
)

BY_KEY: dict[str, Classifier] = {c.key: c for c in CLASSIFIERS}


@dataclass(frozen=True)
class Match:
    """One classifier's verdict for one borrower."""

    classifier: Classifier
    fired: bool
    matched: tuple[str, ...]
    corroborated: tuple[str, ...]
    #: Component signals that could not be tested. A pattern resting partly on
    #: untested evidence is reported as such rather than as a clean finding.
    untested: tuple[str, ...]

    @property
    def available(self) -> bool:
        return len(self.untested) < len(self.classifier.signals)

    def why(self) -> str:
        if not self.fired:
            return ""
        names = [tx.BY_KEY[k].label for k in self.matched if k in tx.BY_KEY]
        said = f"{self.classifier.label}: {', '.join(names)}"
        if self.corroborated:
            extra = [tx.BY_KEY[k].label for k in self.corroborated
                     if k in tx.BY_KEY]
            said += f" — with {', '.join(extra)} alongside"
        if self.untested:
            said += (f" ({len(self.untested)} component"
                     f"{'s' if len(self.untested) != 1 else ''} could not be "
                     "tested)")
        # A sentence. Every other piece of evidence the assessment prints ends
        # in a full stop, and a pattern that does not reads as a fragment
        # somebody forgot to finish.
        return said + "."

    def to_dict(self) -> dict[str, Any]:
        return {**self.classifier.to_dict(), "fired": self.fired,
                "matched": list(self.matched),
                "corroborated": list(self.corroborated),
                "untested": list(self.untested),
                "available": self.available, "why": self.why()}


def classify(fired: set[str] | frozenset[str],
             tested: set[str] | frozenset[str] | None = None,
             *, classifiers: tuple[Classifier, ...] = CLASSIFIERS
             ) -> list[Match]:
    """Every configured pattern, tested against what fired for one borrower.

    `tested` is the set of signals that could actually be evaluated. Where it
    is not supplied every component is assumed testable, which is the right
    default for a caller that already filtered.
    """
    known = set(fired)
    evaluable = set(tested) if tested is not None else None
    out: list[Match] = []
    for entry in classifiers:
        untested = tuple(
            k for k in entry.signals
            if evaluable is not None and k not in evaluable and k not in known)
        matched = tuple(k for k in entry.signals if k in known)
        corroborated = tuple(k for k in entry.corroborating if k in known)
        out.append(Match(classifier=entry, fired=len(matched) >= entry.needs,
                         matched=matched, corroborated=corroborated,
                         untested=untested))
    return out


def fired_for(fired: set[str] | frozenset[str],
              tested: set[str] | frozenset[str] | None = None) -> list[Match]:
    return [m for m in classify(fired, tested) if m.fired]


def describe() -> dict[str, Any]:
    return {
        "owner": CLASSIFIER_OWNER,
        "version": CLASSIFIER_VERSION,
        "count": len(CLASSIFIERS),
        "classifiers": [c.to_dict() for c in CLASSIFIERS],
        "statement": (
            "A classifier is a named pattern over other signals, with its rule "
            "written down. Five are configured. Every signal that is not part "
            "of one is reported as threshold-based or action-based rather than "
            "being dressed up as a pattern."),
    }


def unknown_components() -> tuple[str, ...]:
    """Component keys no configured signal provides.

    A classifier resting on a signal that does not exist is a pattern that can
    never fire, and a framework quietly missing one of its own patterns is
    worse than one that never claimed it.
    """
    out: list[str] = []
    for entry in CLASSIFIERS:
        for key in (*entry.signals, *entry.corroborating):
            if key not in tx.BY_KEY:
                out.append(f"{entry.key}:{key}")
    return tuple(sorted(set(out)))


__all__ = ["CLASSIFIERS", "CLASSIFIER_OWNER", "CLASSIFIER_VERSION", "BY_KEY",
           "Classifier", "Match", "classify", "describe", "fired_for",
           "unknown_components"]
