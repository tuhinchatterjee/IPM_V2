"""
Domain intelligence. §30-§33.

Four domains - IFRS 9, covenants, collateral, external intelligence - each of
which already has a dataset. What none of them had was a *reading*: somebody
looking at the rows and saying what they mean, with every sentence bound to a
figure a reader can go and check.

This package supplies that, and it supplies it the same way in all four,
because the alternative is four modules that each invented their own idea of
what an explanation is and four screens that word the same evidence
differently.

The shape
---------
A ``Reading`` is a domain, a borrower, a period, a list of ``Finding``s, and a
list of what could not be read. Every finding names the dataset and field it
came from and the rule it was tested against. A reading composes its own
sentence from its findings, so the summary and the evidence beneath it cannot
disagree - the same discipline `early_warning.signals` follows, for the same
reason.

Three rules hold across all four readers.

**No score.** There is no ``Reading.score`` and no rule producing one. Each
domain reports what it found; ranking, where a screen needs it, is by counts.

**Absence is reported, never inferred.** A borrower with no covenant rows is
"no covenant is recorded for this borrower", not "no covenant pressure". The
two look identical on a screen that only shows findings, and only one of them
is reassuring.

**The booked position is never a prediction.** IFRS 9 stage is what the book
says today. Saying a borrower "will move to stage 2" from a stage-2 row is the
single most consequential wording error available in this product, so the
accounting facts are flagged as booked and carry that word into every sentence
built from them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: Bumped when a reader's rules change, so a reading can be interpreted
#: against the rules that produced it.
INTELLIGENCE_VERSION = "1.0.0"

#: Who owns the thresholds these readers test against. The same team that owns
#: the early-warning taxonomy: two owners for one book is how two screens end
#: up disagreeing about what "tight" means.
OWNER = "Credit Risk Analytics"

IFRS9 = "IFRS9"
COVENANT = "COVENANT"
COLLATERAL = "COLLATERAL"
EXTERNAL = "EXTERNAL"

DOMAINS: dict[str, str] = {
    IFRS9: "IFRS 9 position",
    COVENANT: "Covenant compliance",
    COLLATERAL: "Collateral and security",
    EXTERNAL: "External intelligence",
}

# --------------------------------------------------------------- severity
#
# The same three levels as the early-warning taxonomy, deliberately. A product
# with one severity scale in one module and another next door teaches nobody
# anything except that its scales are decorative.

WATCH = "WATCH"
CONCERN = "CONCERN"
SEVERE = "SEVERE"
SEVERITIES: tuple[str, ...] = (WATCH, CONCERN, SEVERE)
SEVERITY_RANK: dict[str, int] = {WATCH: 1, CONCERN: 2, SEVERE: 3}


@dataclass
class Finding:
    """One thing a reader found, and everything needed to check it."""

    key: str
    label: str
    #: What it means, in a sentence somebody would say out loud.
    means: str
    severity: str = CONCERN
    value: Any = None
    previous: Any = None
    threshold: Any = None
    #: The rule that was applied, named rather than implied.
    test: str = ""
    dataset: str = ""
    field_name: str = ""
    period: str = ""
    #: True when this is the BOOKED accounting position rather than a view
    #: about the future. §20.
    booked_accounting: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key, "label": self.label, "means": self.means,
            "severity": self.severity, "value": self.value,
            "previous": self.previous, "threshold": self.threshold,
            "test": self.test, "dataset": self.dataset,
            "field": self.field_name, "period": self.period,
            "booked_accounting": self.booked_accounting,
            "owner": OWNER, "version": INTELLIGENCE_VERSION,
        }


@dataclass
class Missing:
    """Something a reader could not read, and why. §7."""

    what: str
    why: str

    def to_dict(self) -> dict[str, str]:
        return {"what": self.what, "why": self.why}


@dataclass
class Reading:
    """What one domain says about one borrower at one period."""

    domain: str
    borrower_id: str = ""
    period: str = ""
    findings: list[Finding] = field(default_factory=list)
    missing: list[Missing] = field(default_factory=list)
    #: Figures the reader looked at whether or not anything was found. A
    #: reading that shows only what went wrong is a reading nobody can put in
    #: context.
    measured: dict[str, Any] = field(default_factory=dict)

    @property
    def severity(self) -> str:
        if any(f.severity == SEVERE for f in self.findings):
            return SEVERE
        if any(f.severity == CONCERN for f in self.findings):
            return CONCERN
        return WATCH

    @property
    def booked(self) -> list[Finding]:
        return [f for f in self.findings if f.booked_accounting]

    def sentence(self) -> str:
        """Composed from the findings, never written separately.

        A summary written alongside the evidence rather than out of it is a
        summary that can drift from it, and by the time anybody notices, the
        number in the sentence is the one people quote.
        """
        label = DOMAINS.get(self.domain, self.domain)
        if not self.findings and self.missing:
            return (f"{label}: nothing could be read for this borrower at "
                    f"{self.period}. " + " ".join(m.why for m in self.missing))
        if not self.findings:
            return (f"{label}: nothing this reader tests for is present at "
                    f"{self.period}.")
        parts = [f.label for f in self.findings]
        head = (f"{label}: {len(self.findings)} finding"
                f"{'' if len(self.findings) == 1 else 's'} - "
                f"{and_list(parts)}")
        if self.missing:
            head += (f". {len(self.missing)} thing"
                     f"{'' if len(self.missing) == 1 else 's'} could not be "
                     "read")
        return head + "."

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": INTELLIGENCE_VERSION,
            "owner": OWNER,
            "domain": self.domain,
            "domain_label": DOMAINS.get(self.domain, self.domain),
            "borrower_id": self.borrower_id,
            "period": self.period,
            "sentence": self.sentence(),
            "severity": self.severity,
            # Deliberately no score key, in any of the four domains.
            "findings": [f.to_dict() for f in self.findings],
            "booked_accounting": [f.key for f in self.booked],
            "missing": [m.to_dict() for m in self.missing],
            "measured": dict(self.measured),
        }


def and_list(items: list[str]) -> str:
    kept = [i for i in items if i]
    if not kept:
        return ""
    if len(kept) == 1:
        return kept[0]
    return ", ".join(kept[:-1]) + " and " + kept[-1]


def number(value: Any) -> float | None:
    """A figure as a number, or nothing. Never a zero standing in for a gap."""
    if value is None:
        return None
    try:
        found = float(value)
    except (TypeError, ValueError):
        return None
    return None if found != found else found  # NaN is absence, not zero


def truthy(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "y", "1"}
    return bool(value) if value is not None else False


__all__ = ["COLLATERAL", "CONCERN", "COVENANT", "DOMAINS", "EXTERNAL",
           "Finding", "IFRS9", "INTELLIGENCE_VERSION", "Missing", "OWNER",
           "Reading", "SEVERE", "SEVERITIES", "SEVERITY_RANK", "WATCH",
           "and_list", "number", "truthy"]
