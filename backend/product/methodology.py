"""
The Early Warning methodology, read from the engine that runs it.

Why it is read rather than written
----------------------------------
A methodology document and the code that implements it drift apart, and the
document is the one people quote. So nothing here restates the taxonomy: the
four layers are a GROUPING over `backend.early_warning.taxonomy`, the signal
catalogue is that taxonomy rendered, and the frequency of a signal is read from
the periods its dataset actually publishes.

The consequence is deliberate. Add a signal to the engine and it appears in the
methodology answer. Remove one and it disappears. A reconciliation test fails
the build if a family exists in the engine and not in a layer, so the two
cannot silently diverge.

The four layers, and the eight families underneath them
-------------------------------------------------------
The remediation asks for a four-layer framework. The project's authority is
`taxonomy.FAMILIES`, which has EIGHT signal families. Those are not competing
taxonomies — the layers are credit-risk PERSPECTIVES and the families are the
governed grouping of signals — so the layers are defined here as a mapping onto
the families rather than as a replacement for them, and the mapping is written
down so a reader can check it.

    Layer 1  Borrower fundamentals         financial, leverage, liquidity
    Layer 2  Credit behaviour and structure behavioural, covenant, collateral
    Layer 3  Credit quality, IFRS 9, ratings rating, ifrs9
    Layer 4  External, sector, macro, network   — no governed family today

Layer 4 is honest rather than empty-by-oversight. The External Intelligence
DOMAIN exists and carries macro series, sector conditions and governed events,
and the Ask path reads them; but no Early Warning SIGNAL is configured against
it, so no borrower is currently promoted to a case by an external condition
alone. Claiming otherwise would be the exact failure this module exists to
prevent.

TAC
---
`tac()` reports that the repository contains no definition of TAC — no code, no
document, no configuration, nothing in the history. The remediation is explicit
that an acronym must not be invented, so the answer says what was searched and
asks for the source. That is the whole implementation, and it is the correct
one until somebody supplies the definition.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

METHODOLOGY_VERSION = "1.0.0"

# --------------------------------------------------------------- the four layers

LAYER_FUNDAMENTALS = "fundamentals"
LAYER_BEHAVIOUR = "behaviour"
LAYER_CREDIT_QUALITY = "credit_quality"
LAYER_EXTERNAL = "external"


@dataclass(frozen=True)
class Layer:
    """One credit-risk perspective, and the governed families under it."""

    key: str
    number: int
    name: str
    #: What this layer is watching, in a sentence.
    watches: str
    #: Why deterioration here matters, and how early it tends to show.
    matters: str
    #: The `taxonomy.FAMILIES` keys this layer groups.
    families: tuple[str, ...]
    #: Where the layer has no configured signals, why not.
    gap: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"key": self.key, "number": self.number, "name": self.name,
                "watches": self.watches, "matters": self.matters,
                "families": list(self.families), "gap": self.gap}


LAYERS: tuple[Layer, ...] = (
    Layer(
        key=LAYER_FUNDAMENTALS, number=1,
        name="Borrower fundamentals and financial health",
        watches="Revenue, EBITDA and margin, cash flow and working capital, "
                "leverage and net leverage, DSCR and interest coverage, and "
                "the liquidity available to meet what falls due.",
        matters="This is where deterioration starts. A borrower loses margin, "
                "then cash, then cover, and only then misses a payment — so "
                "fundamentals lead behaviour by quarters and lead the rating "
                "by longer. They are also the slowest to arrive: financial "
                "statements are reported after the period they describe, so a "
                "fundamentals signal is early in credit terms and late in "
                "calendar terms.",
        families=("financial", "leverage", "liquidity")),
    Layer(
        key=LAYER_BEHAVIOUR, number=2,
        name="Credit behaviour, facility and structural risk",
        watches="Utilisation and limit excess, delinquency and days past due, "
                "payment behaviour, rollovers and refinancing pressure, "
                "covenant headroom and breaches, collateral coverage and "
                "guarantees, watchlist status, restructuring and forbearance.",
        matters="Behaviour deteriorates before default and often before the "
                "accounts show anything, because a borrower under pressure "
                "draws its lines, pays later and asks for waivers before it "
                "reports a bad year. These are also the signals the bank "
                "observes directly rather than being told about, which makes "
                "them the most current evidence available.",
        families=("behavioural", "covenant", "collateral")),
    Layer(
        key=LAYER_CREDIT_QUALITY, number=3,
        name="Credit quality, IFRS 9 and ratings",
        watches="12-month and lifetime PD, rating migration and notches "
                "moved, IFRS 9 stage migration, SICR triggers, ECL and "
                "coverage, Stage 2 candidacy and Stage 3 default.",
        matters="This layer records the bank's own assessment, and the "
                "distinction that matters is between the BOOKED position and "
                "a prediction. A Stage 2 classification is an accounting fact "
                "about what has already been recognised; a PD that has risen "
                "without a stage change is a prediction that it has not been "
                "recognised yet. Reading the first as the second flatters the "
                "book; reading the second as the first misstates the "
                "accounts.",
        families=("rating", "ifrs9")),
    Layer(
        key=LAYER_EXTERNAL, number=4,
        name="External, sector, macro and network intelligence",
        watches="GDP, interest rates, inflation and FX, oil and commodity "
                "prices, sector conditions, external ratings and events, "
                "connected counterparties, group contagion, ownership and "
                "guarantee structures.",
        matters="External pressure transmits inward: a trade-route "
                "disruption reaches shipping utilisation and liquidity before "
                "it reaches a rating, and a stressed parent reaches a "
                "subsidiary through a guarantee rather than through its own "
                "accounts. The transmission is a hypothesis about a "
                "mechanism, not an observation about a borrower, and it has "
                "to be labelled that way.",
        families=(),
        gap="No Early Warning signal is configured against the External "
            "Intelligence domain in this installation. The domain is "
            "published and the Ask path reads it — a borrower's story shows "
            "which external conditions are live for its sector — but no "
            "borrower is promoted to a Risk Case by an external condition "
            "alone. Configuring signals here is a Data Builder and Credit "
            "Risk Analytics decision, not a code change."),
)

LAYER_BY_FAMILY: dict[str, str] = {
    family: layer.key for layer in LAYERS for family in layer.families}


# ---------------------------------------------------------------- the frequency
#
# Read from the data, never asserted. "Do not claim daily frequency if the
# available data is quarterly" is the whole rule, and the only way to keep it
# is to count the periods the dataset publishes rather than to write a word.

DAILY, WEEKLY, MONTHLY, QUARTERLY, ANNUAL = (
    "Daily", "Weekly", "Monthly", "Quarterly", "Annual")
EVENT_DRIVEN = "Event-driven"
UNKNOWN_FREQUENCY = "Not published"


def _frequency_of(dataset: str) -> str:
    """How often a dataset is published, from the periods it carries.

    Quarterly labels mean quarterly, bare years mean annual, and anything else
    is judged by how many periods there are. Where the catalogue publishes no
    periods at all the answer is "Not published" rather than a guess: an
    invented frequency on a signal catalogue is a scheduling claim somebody
    will plan around.
    """
    try:
        from backend.orchestration import context as gc

        for entry in gc.all_datasets():
            if entry.name != dataset:
                continue
            periods = [str(p).strip() for p in (entry.periods or []) if p]
            if not periods:
                return UNKNOWN_FREQUENCY
            if all(p.isdigit() and len(p) == 4 for p in periods):
                return ANNUAL
            if all(p.upper().startswith("Q") for p in periods):
                return QUARTERLY
            return MONTHLY if len(periods) > 24 else QUARTERLY
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not read the frequency of %s: %s", dataset, exc)
    return UNKNOWN_FREQUENCY


def frequencies() -> dict[str, str]:
    """Every dataset the signal catalogue reads, and how often it publishes."""
    from backend.early_warning import taxonomy as tx

    return {dataset: _frequency_of(dataset)
            for dataset in sorted({s.dataset for s in tx.SIGNALS})}


# ------------------------------------------------------------ the signal catalogue


@dataclass(frozen=True)
class CatalogueEntry:
    """One signal, with everything needed to defend and to schedule it."""

    key: str
    family: str
    family_label: str
    layer: str
    layer_name: str
    label: str
    means: str
    dataset: str
    fields: tuple[str, ...]
    grain: str
    frequency: str
    test: str
    threshold: Any
    unit: str
    direction: str
    severity: str
    booked_accounting: bool
    owner: str
    version: str
    sentence: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key, "family": self.family,
            "family_label": self.family_label, "layer": self.layer,
            "layer_name": self.layer_name, "label": self.label,
            "means": self.means, "dataset": self.dataset,
            "fields": list(self.fields), "grain": self.grain,
            "frequency": self.frequency, "test": self.test,
            "threshold": self.threshold, "unit": self.unit,
            "direction": self.direction, "severity": self.severity,
            "booked_accounting": self.booked_accounting, "owner": self.owner,
            "version": self.version, "sentence": self.sentence,
        }


#: How each governed test reads as a direction of deterioration.
_DIRECTION: dict[str, str] = {
    "above": "deteriorates as the value RISES above the threshold",
    "below": "deteriorates as the value FALLS below the threshold",
    "rose_by": "deteriorates when the value RISES by the threshold or more",
    "fell_by": "deteriorates when the value FALLS by the threshold or more",
    "true": "deteriorates when the condition becomes true",
    "changed": "deteriorates when the value changes from the prior period",
    "ratio_above": "deteriorates as the ratio RISES above the threshold",
    "ratio_rose_by": "deteriorates when the ratio RISES by the threshold or "
                     "more",
}

#: Every signal reads the borrower snapshot, which is one row per borrower per
#: reporting period. Stated rather than inferred so the answer can say it.
SIGNAL_GRAIN = "One row per borrower per reporting period"


def catalogue(family: str = "", layer_key: str = "") -> tuple[CatalogueEntry, ...]:
    """The governed signal catalogue, optionally narrowed."""
    from backend.early_warning import taxonomy as tx

    known = frequencies()
    out: list[CatalogueEntry] = []
    for signal in tx.SIGNALS:
        if family and signal.family != family:
            continue
        mapped = LAYER_BY_FAMILY.get(signal.family, "")
        if layer_key and mapped != layer_key:
            continue
        named = next((entry.name for entry in LAYERS if entry.key == mapped),
                     "Not mapped to a layer")
        out.append(CatalogueEntry(
            key=signal.key, family=signal.family,
            family_label=tx.FAMILIES.get(signal.family, signal.family),
            layer=mapped, layer_name=named,
            label=signal.label, means=signal.means, dataset=signal.dataset,
            fields=tuple(signal.columns), grain=SIGNAL_GRAIN,
            frequency=known.get(signal.dataset, UNKNOWN_FREQUENCY),
            test=signal.test, threshold=signal.threshold, unit=signal.unit,
            direction=_DIRECTION.get(signal.test, "direction not declared"),
            severity=signal.severity,
            booked_accounting=signal.booked_accounting,
            owner=tx.THRESHOLD_OWNER, version=signal.version,
            sentence=signal.sentence()))
    return tuple(out)


def layers() -> tuple[Layer, ...]:
    return LAYERS


def layer_of(family: str) -> str:
    return LAYER_BY_FAMILY.get(family, "")


def unmapped_families() -> tuple[str, ...]:
    """Governed families no layer claims.

    Empty is the only acceptable answer, and the reconciliation test says so.
    A family the engine evaluates and the methodology does not mention is a
    signal firing into an explanation that denies it exists.
    """
    from backend.early_warning import taxonomy as tx

    return tuple(sorted(set(tx.FAMILIES) - set(LAYER_BY_FAMILY)))


# -------------------------------------------------------------- warning language
#
# The engine's own words are "fired", "still firing", "condition met". Those
# describe a rule evaluating; a credit officer wants to know what the borrower
# is doing. The mapping is one-way and lives here so both the Early Warning
# screen and the methodology answer use the same words.

WARNING_STATES: tuple[tuple[str, str], ...] = (
    ("New warning",
     "The indicator crossed its warning threshold in the current observation "
     "period, having been within it in the previous one."),
    ("Persistent warning",
     "The indicator remains beyond its warning threshold in both the current "
     "and the previous observation periods."),
    ("Worsening warning",
     "The indicator was already beyond its threshold and has moved further "
     "beyond it since the previous observation period."),
    ("Improving",
     "The indicator remains beyond its threshold but has moved back toward it "
     "since the previous observation period."),
    ("Resolved",
     "The indicator was beyond its threshold in the previous observation "
     "period and is within it in the current one."),
)


# --------------------------------------------------------------------- the flow

ASSESSMENT_FLOW: tuple[str, ...] = (
    "Data signal",
    "Threshold / change detection",
    "Persistence / materiality",
    "Cross-domain evidence",
    "Severity assessment",
    "Risk Case",
    "AI investigation",
    "Credit action / review",
)

SEVERITY_MEANS: dict[str, str] = {
    "WATCH": "Worth knowing about. Recorded against the borrower and visible "
             "on its story; not on its own a reason to open a case.",
    "CONCERN": "Material. Contributes to case promotion, and a cluster of "
               "these across families is the ordinary route to a case.",
    "SEVERE": "Acute. Promotes on its own, because a single signal at this "
              "level describes a borrower that needs looking at now.",
}

PERSISTENCE_RULE = (
    "A signal is assessed against the previous observation period as well as "
    "the current one. One period beyond a threshold is a new warning; two is "
    "persistent, which is the stronger evidence — a single reading can be a "
    "reporting artefact, and two consecutive ones usually are not.")

CASE_PROMOTION = (
    "Signals do not become cases one for one; that is how a screening engine "
    "produces two thousand cases and triages nothing. Promotion depends on "
    "severity, on how many families are affected at once, and on whether the "
    "condition persisted. A case carries an owner, a status, a due date and a "
    "severity computed by formula rather than assigned by a language model, "
    "and it stays open until somebody resolves it or dismisses it with a "
    "reason.")


# ------------------------------------------------------------------------- TAC

#: Everything that was searched for a definition of TAC, so the answer can say
#: what was looked at rather than just that nothing was found.
TAC_SEARCHED: tuple[str, ...] = (
    "every Python module under backend/ and scripts/",
    "every Markdown document under docs/",
    "every TypeScript and TSX module under frontend/src/",
    "JSON, YAML and PowerShell configuration",
    "the Early Warning taxonomy, engine, severity and case modules",
    "the full commit history",
)

TAC_STATUS_MISSING = "not_defined"
TAC_STATUS_DEFINED = "defined"


@dataclass(frozen=True)
class Tac:
    """What is known about TAC, which at present is that it is not defined."""

    status: str = TAC_STATUS_MISSING
    searched: tuple[str, ...] = field(default_factory=lambda: TAC_SEARCHED)
    statement: str = (
        "CreditProbe has no definition of TAC. The term does not appear "
        "anywhere in this repository — not in the Early Warning taxonomy, "
        "engine, severity or case logic, not in any methodology document, not "
        "in configuration, and not in the commit history. Rather than guess "
        "what the acronym stands for and describe a methodology CreditProbe "
        "does not implement, this answer states that the definition is "
        "missing. Supply the source — a methodology paper, a policy document "
        "or a specification — and it can be published here as a versioned "
        "methodology alongside the four-layer framework.")
    #: What the questioner may actually be after, offered without claiming it
    #: IS TAC.
    nearest = (
        "If what is meant is how CreditProbe aggregates signals into an "
        "assessment, that is the four-layer framework, the severity model and "
        "the case-promotion rules described above, and they can be explained "
        "in full.")

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status, "searched": list(self.searched),
                "statement": self.statement, "nearest": self.nearest,
                "defined": self.status == TAC_STATUS_DEFINED}


def tac() -> Tac:
    """Whether TAC is defined anywhere authoritative. It is not."""
    return Tac()


def describe() -> dict[str, Any]:
    """The whole methodology, as data."""
    from backend.early_warning import taxonomy as tx

    entries = catalogue()
    return {
        "version": METHODOLOGY_VERSION,
        "taxonomy_version": tx.TAXONOMY_VERSION,
        "owner": tx.THRESHOLD_OWNER,
        "purpose": (
            "To identify borrowers whose credit position is deteriorating "
            "early enough to act, using governed signals with declared "
            "thresholds, and to route what matters to somebody who owns it."),
        "layers": [layer.to_dict() for layer in LAYERS],
        "signal_count": len(entries),
        "families": dict(tx.FAMILIES),
        "unmapped_families": list(unmapped_families()),
        "frequencies": frequencies(),
        "grain": SIGNAL_GRAIN,
        "severities": dict(SEVERITY_MEANS),
        "persistence": PERSISTENCE_RULE,
        "case_promotion": CASE_PROMOTION,
        "warning_states": [{"state": s, "means": m} for s, m in WARNING_STATES],
        "flow": list(ASSESSMENT_FLOW),
        "tac": tac().to_dict(),
    }


__all__ = [
    "ASSESSMENT_FLOW",
    "CASE_PROMOTION",
    "CatalogueEntry",
    "LAYERS",
    "LAYER_BEHAVIOUR",
    "LAYER_BY_FAMILY",
    "LAYER_CREDIT_QUALITY",
    "LAYER_EXTERNAL",
    "LAYER_FUNDAMENTALS",
    "Layer",
    "METHODOLOGY_VERSION",
    "PERSISTENCE_RULE",
    "SEVERITY_MEANS",
    "SIGNAL_GRAIN",
    "TAC_SEARCHED",
    "TAC_STATUS_DEFINED",
    "TAC_STATUS_MISSING",
    "Tac",
    "WARNING_STATES",
    "catalogue",
    "describe",
    "frequencies",
    "layer_of",
    "layers",
    "tac",
    "unmapped_families",
]
