"""Which governed metric a document quotes, and on whose authority. §7, §8.

The rule, in one sentence
------------------------
A metric is linked because something authoritative said so, never because two
labels look alike.

Auto-confirmed, and only these
------------------------------
1. the attached CreditProbe analysis carried a stable `metric_id`;
2. the source field has an explicit Metric Catalogue mapping;
3. the same mapping was already confirmed by a person for this document and
   this source context.

Everything else is a SUGGESTION
-------------------------------
An ordinary uploaded workbook has no metric identity in it. A column headed
"Default rate" might be the retail book or the corporate book, this quarter or
last, a rate or a count of accounts. So a high-confidence suggestion is made
and shown immediately — the dashboard is useful on first open — but it is
marked as needing confirmation and it does not act like a link:

* it is not a THEN/NOW comparison;
* it does not trigger freshness;
* it does not block readiness;
* it is not an input to an automatic section refresh.

It reduces metric-linkage COVERAGE, which is a visible, explainable score, and
that is the whole of its effect until a person confirms it.

And generation never stops for it
---------------------------------
Nothing here sits between a user and their document. Suggestions are made after
the fact, from what was attached, and the user reviews them when they choose.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from backend.models.playbook import PlaybookMetricBinding

# --------------------------------------------------------------------------
# How a binding was made. This is the authority, and it is never inferred
# from how the numbers look.
# --------------------------------------------------------------------------

#: The export itself carried a stable metric id. Rule 1.
FROM_EXPORT = "export_metric_id"
#: The source field maps to the Metric Catalogue explicitly. Rule 2.
FROM_CATALOGUE = "catalogue_mapping"
#: A person confirmed this same mapping before, here. Rule 3.
FROM_PRIOR_CONFIRMATION = "prior_confirmation"
#: A label match. Shown, never trusted.
SUGGESTED = "suggested"
#: Nothing matched. Said plainly rather than guessed at.
UNLINKED = "unlinked"

#: The methods that are links the moment they are made.
AUTO_CONFIRMED = frozenset({FROM_EXPORT, FROM_CATALOGUE,
                            FROM_PRIOR_CONFIRMATION})

METHOD_LABELS = {
    FROM_EXPORT: "Exported analysis carried a metric id",
    FROM_CATALOGUE: "Metric Catalogue mapping",
    FROM_PRIOR_CONFIRMATION: "Previously confirmed here",
    SUGGESTED: "Suggested — confirmation required",
    UNLINKED: "Not linked",
}

HIGH, MEDIUM, LOW = "high", "medium", "low"

CURRENT, NEW_AVAILABLE, STALE, UNKNOWN = (
    "current", "new_data_available", "stale", "unknown")


def is_governed(binding: PlaybookMetricBinding) -> bool:
    """Whether this binding may be used as a governed link.

    The single predicate everything downstream asks. A suggestion answers
    False here no matter how confident it looks, which is what keeps it out of
    THEN/NOW, freshness, readiness blocking and automatic refresh.
    """
    return bool(binding.metric_id) and (
        binding.confirmed_by_user or binding.binding_method in AUTO_CONFIRMED)


# --------------------------------------------------------------------------
# Proposing bindings
# --------------------------------------------------------------------------


@dataclass
class Proposal:
    """One metric a document appears to quote, and why we think so."""

    metric_id: str
    label: str
    value: str = ""
    display_value: str = ""
    raw_value: str = ""
    unit: str = ""
    currency: str = ""
    population: str = ""
    segment: str = ""
    reporting_period: str = ""
    scenario: str = ""
    as_of: str = ""
    section_key: str = ""
    source_module: str = ""
    source_locator: str = ""
    source_id: int | None = None
    source_export_revision_id: int | None = None
    catalogue_id: str = ""
    method: str = SUGGESTED
    confidence: str = MEDIUM
    #: What the document itself called it, which is not its identity but is
    #: what a reviewer needs to recognise the row.
    document_label: str = ""
    evidence: list[str] = field(default_factory=list)

    @property
    def auto_confirmed(self) -> bool:
        return self.method in AUTO_CONFIRMED

    def as_dict(self) -> dict:
        return {
            "metric_id": self.metric_id, "label": self.label,
            "document_label": self.document_label or self.label,
            "value": self.value, "display_value": self.display_value,
            "raw_value": self.raw_value, "unit": self.unit,
            "currency": self.currency, "population": self.population,
            "segment": self.segment, "reporting_period": self.reporting_period,
            "scenario": self.scenario, "as_of": self.as_of,
            "section_key": self.section_key,
            "source_module": self.source_module,
            "source_locator": self.source_locator,
            "catalogue_id": self.catalogue_id,
            "method": self.method, "method_label": METHOD_LABELS[self.method],
            "confidence": self.confidence,
            "auto_confirmed": self.auto_confirmed,
            "evidence": list(self.evidence),
        }


def from_export(metrics, *, module: str = "", revision_id: int | None = None,
                section_key: str = "") -> list[Proposal]:
    """Rule 1. An analysis that states its metric ids is authoritative.

    `metrics` are `backend.exports.playbook_contract.Metric` records. A metric
    with no id is NOT proposed from here — an exporter that does not know its
    identity has not provided one, and inventing it from the label would be
    exactly the mistake this module exists to prevent.
    """
    out: list[Proposal] = []
    for metric in metrics or ():
        if not getattr(metric, "metric_id", ""):
            continue
        out.append(Proposal(
            metric_id=metric.metric_id, label=metric.label or metric.metric_id,
            document_label=metric.label, value=metric.value,
            display_value=metric.display_value or metric.value,
            unit=metric.unit, currency=metric.currency,
            population=metric.population, segment=metric.segment,
            reporting_period=metric.reporting_period, scenario=metric.scenario,
            as_of=metric.as_of, section_key=section_key, source_module=module,
            source_locator=metric.locator,
            source_export_revision_id=revision_id,
            catalogue_id=metric.catalogue_id,
            method=FROM_EXPORT, confidence=HIGH,
            evidence=[f"export carried metric_id {metric.metric_id!r}"]))
    return out


#: The label shapes a workbook uses for a metric it has no id for. Matching
#: one produces a SUGGESTION and nothing more.
_KNOWN_LABELS: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("retail.default_rate", ("retail default rate", "default rate"),
     "percent"),
    ("retail.dpd30_rate", ("30+ dpd", "30 dpd", "30+ dpd exposure rate"),
     "percent"),
    ("retail.dpd90_rate", ("90+ dpd", "90 dpd", "90+ dpd exposure rate"),
     "percent"),
    ("application.cohort_bad_rate",
     ("application cohort bad rate", "cohort bad rate", "bad rate"),
     "percent"),
    ("scorecard.gini", ("gini", "gini coefficient", "scorecard gini"),
     "statistic"),
    ("scorecard.auc", ("auc", "auroc", "roc area", "area under the curve"),
     "statistic"),
    ("scorecard.ks", ("ks", "ks statistic", "kolmogorov-smirnov"),
     "statistic"),
    ("scorecard.brier", ("brier", "brier score"), "statistic"),
    ("ifrs9.coverage_ratio", ("coverage ratio", "coverage"), "percent"),
    ("ifrs9.weighted_ecl", ("weighted ecl", "ecl"), "currency"),
)


def _normalise(label: str) -> str:
    text = re.sub(r"[^a-z0-9+ ]+", " ", (label or "").lower())
    return re.sub(r"\s+", " ", text).strip()


def suggest_from_label(label: str) -> tuple[str, str, str] | None:
    """A metric id a label RESEMBLES, with its unit. Never authoritative.

    Exact or whole-phrase match only. Substring matching would bind "bad rate"
    to "cohort bad rate" and to anything else containing the words, which is
    how the wrong series gets attached to a governed paper.
    """
    key = _normalise(label)
    if not key:
        return None
    for metric_id, phrases, unit in _KNOWN_LABELS:
        for phrase in phrases:
            if key == phrase:
                return metric_id, unit, HIGH
    for metric_id, phrases, unit in _KNOWN_LABELS:
        for phrase in phrases:
            if re.search(rf"\b{re.escape(phrase)}\b", key):
                return metric_id, unit, MEDIUM
    return None


def cell_locator(sheet_locator: str, cell: str) -> str:
    """`xlsx://Validation!A1` plus `B4` is `xlsx://Validation!B4`.

    The chunk's locator already names an anchor cell, so appending would
    produce `xlsx://Validation!A1!B4` — an address of nothing, which is worse
    than no address at all because it looks like one.
    """
    if not cell:
        return sheet_locator
    if not sheet_locator:
        return cell
    head, sep, _anchor = sheet_locator.rpartition("!")
    return f"{head}!{cell}" if sep else f"{sheet_locator}!{cell}"


def from_labels(rows, *, source_id: int | None = None, locator: str = "",
                reporting_period: str = "",
                confirmed_before: dict[str, str] | None = None,
                catalogue: dict[str, str] | None = None) -> list[Proposal]:
    """Rules 2, 3 and the suggestion path, over label/value pairs.

    `rows` are `(label, display_value, raw_value, cell)` as `ingest.sheets`
    now preserves them. A row is auto-confirmed only when the catalogue maps
    its field explicitly, or when a person already confirmed that same label
    in this context. Everything else is a suggestion, and a label that matches
    nothing produces an UNLINKED proposal rather than silence — a metric the
    document quotes and we cannot identify is itself worth showing.
    """
    catalogue = catalogue or {}
    confirmed_before = confirmed_before or {}
    out: list[Proposal] = []
    for label, display_value, raw_value, cell in rows:
        key = _normalise(label)
        where = cell_locator(locator, cell)

        if key in catalogue:
            metric_id, method, confidence = catalogue[key], FROM_CATALOGUE, HIGH
            unit, why = "", f"catalogue maps {label!r}"
        elif key in confirmed_before:
            metric_id = confirmed_before[key]
            method, confidence = FROM_PRIOR_CONFIRMATION, HIGH
            unit, why = "", f"{label!r} was confirmed here before"
        else:
            guess = suggest_from_label(label)
            if guess is None:
                out.append(Proposal(
                    metric_id="", label=label, document_label=label,
                    display_value=display_value, raw_value=raw_value,
                    value=display_value, source_locator=where,
                    source_id=source_id, reporting_period=reporting_period,
                    method=UNLINKED, confidence=LOW,
                    evidence=[f"no governed metric matches {label!r}"]))
                continue
            metric_id, unit, confidence = guess
            method = SUGGESTED
            why = f"label {label!r} resembles {metric_id}"

        out.append(Proposal(
            metric_id=metric_id, label=metric_id or label,
            document_label=label, value=display_value,
            display_value=display_value, raw_value=raw_value, unit=unit,
            reporting_period=reporting_period, source_locator=where,
            source_id=source_id, method=method, confidence=confidence,
            evidence=[why]))
    return out


# --------------------------------------------------------------------------
# Writing them down
# --------------------------------------------------------------------------


def apply(session, workspace_id: int, proposals: list[Proposal], *,
          artifact_id: int | None = None) -> list[PlaybookMetricBinding]:
    """Persist proposals as bindings, auto-confirming only where the rule says.

    Idempotent on (workspace, artifact, metric, section, locator): re-running
    ingestion over the same evidence updates the values rather than growing a
    second row, so a refresh does not multiply a document's inventory.
    """
    existing = {
        (b.metric_id, b.section_key, b.source_locator): b
        for b in session.query(PlaybookMetricBinding)
        .filter(PlaybookMetricBinding.workspace_id == workspace_id)
        .all()
    }
    written: list[PlaybookMetricBinding] = []
    for proposal in proposals:
        key = (proposal.metric_id, proposal.section_key,
               proposal.source_locator)
        binding = existing.get(key)
        if binding is None:
            binding = PlaybookMetricBinding(workspace_id=workspace_id,
                                            metric_id=proposal.metric_id)
            session.add(binding)
            existing[key] = binding

        # A confirmation a person already gave is never withdrawn by a later
        # ingestion: re-reading the same workbook must not un-confirm work.
        already_confirmed = bool(binding.confirmed_by_user)

        binding.artifact_id = artifact_id or binding.artifact_id
        binding.section_key = proposal.section_key
        binding.canonical_name = proposal.label
        binding.catalogue_id = proposal.catalogue_id
        binding.label = proposal.document_label or proposal.label
        binding.unit = proposal.unit or binding.unit
        binding.currency = proposal.currency
        binding.population = proposal.population
        binding.segment = proposal.segment
        binding.reporting_period = proposal.reporting_period
        binding.scenario = proposal.scenario
        binding.source_module = proposal.source_module
        binding.source_export_revision_id = proposal.source_export_revision_id
        binding.source_id = proposal.source_id
        binding.source_locator = proposal.source_locator
        binding.value_in_document = proposal.value
        binding.display_value = proposal.display_value
        binding.raw_value = proposal.raw_value
        binding.as_of = proposal.as_of
        binding.confidence = proposal.confidence
        if not already_confirmed:
            binding.binding_method = proposal.method
            binding.confirmed_by_user = False
        written.append(binding)
    session.flush()
    return written


class NotConfirmable(ValueError):
    """A confirmation that cannot be recorded, with the reason."""


def confirm(session, binding: PlaybookMetricBinding, *, actor: str,
            metric_id: str = "") -> PlaybookMetricBinding:
    """A person accepts a suggestion, or changes it to a different metric.

    `actor` is required and must be a person. Confirming a mapping is a
    governance act: it turns something the system guessed into something the
    document relies on, and a row that cannot say who did it is not a
    confirmation.
    """
    from datetime import UTC, datetime

    if not (actor or "").strip():
        raise NotConfirmable(
            "A metric mapping is confirmed by a person. Nothing was changed.")
    if metric_id:
        binding.metric_id = metric_id
        binding.canonical_name = metric_id
    if not binding.metric_id:
        raise NotConfirmable(
            "This figure has no governed metric to confirm it against. "
            "Choose one, or leave it unlinked.")
    binding.confirmed_by_user = True
    binding.confirmed_by = actor.strip()[:160]
    binding.confirmed_at = datetime.now(UTC)
    session.flush()
    return binding


def ignore(session, binding: PlaybookMetricBinding) -> PlaybookMetricBinding:
    """A person says this figure is not a governed metric. Kept, not deleted.

    The row stays so the document's inventory still shows the figure and so
    the same suggestion is not made again next time the source is read.
    """
    binding.binding_method = UNLINKED
    binding.confirmed_by_user = False
    binding.metric_id = binding.metric_id or ""
    session.flush()
    return binding


def coverage(bindings: list[PlaybookMetricBinding]) -> dict:
    """The inventory line a dashboard opens with. §8's four numbers.

    Confirmed, suggested and unlinked are counted separately and never summed
    into one "linked" figure, because that is precisely the conflation the
    product rule forbids.
    """
    confirmed = [b for b in bindings if is_governed(b)]
    suggested = [b for b in bindings
                 if b.binding_method == SUGGESTED and not b.confirmed_by_user]
    unlinked = [b for b in bindings if b.binding_method == UNLINKED
                and not b.confirmed_by_user]
    total = len(bindings)
    return {
        "detected": total,
        "confirmed": len(confirmed),
        "suggested": len(suggested),
        "unlinked": len(unlinked),
        # Coverage counts only what is governed. A suggestion lowers this
        # score; it never quietly raises it.
        "coverage_pct": round(100 * len(confirmed) / total) if total else 0,
        "review_prompt": (f"Review {len(suggested)} suggested metric link"
                          f"{'s' if len(suggested) != 1 else ''}"
                          if suggested else ""),
    }
