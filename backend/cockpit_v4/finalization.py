"""
Answer validation: check the evidence, render the numbers, rewrite nothing.

What "validated" means here, precisely
--------------------------------------
Every `numeric_claim` names an artifact, a row and a column that this run
actually produced, and the value matches what is stored there. That is
checkable and it is checked. The narrative's PROSE is not claimed to be
semantically verified -- no validator reads English and certifies that a
sentence is true. What is enforced is narrower and honest: a portfolio number
in the narrative must arrive through a `{{claim.id}}` placeholder bound to
evidence, so a figure cannot appear in the answer without an execution behind
it.

The renderer substitutes validated values at the declared unit and precision.
That is deterministic formatting of an evidence-bound value, which is
presentation. It is the ONLY transformation applied to the analyst's words.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from backend.cockpit_v4.contracts import (DATA_ANALYSIS, FinalResponse,
                                          NumericClaim, Rejection)
from backend.cockpit_v4.states import ANSWER_VALIDATION

PLACEHOLDER = re.compile(r"\{\{claim\.([A-Za-z0-9_.:-]{1,64})\}\}")

#: A bare number in narrative prose. Used to WARN, never to reject prose --
#: "20 quarters", "IFRS 9" and "12-month" are legitimate and are not
#: portfolio claims.
_BARE_NUMBER = re.compile(r"(?<![\w.{])(\d[\d,]*\.?\d*)(?![\w}])")
_ALLOWED_BARE = {"9", "12", "20", "19", "1", "2", "3", "4", "5", "10", "15",
                 "0", "40", "2021", "2022", "2023", "2024", "2025", "2026"}


@dataclass
class ValidationReport:
    ok: bool
    rendered_narrative: str = ""
    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    claim_values: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "problems": list(self.problems),
                "warnings": list(self.warnings),
                "claims_checked": len(self.claim_values)}


def _format(claim: NumericClaim) -> str:
    try:
        value = Decimal(claim.decimal_value)
    except InvalidOperation:
        return claim.decimal_value
    quantized = value.quantize(Decimal(1).scaleb(-claim.display_precision))
    text = f"{quantized:,}"
    return f"{text} {claim.unit}".strip()


@dataclass
class Finalizer:
    """Checks one final response against the evidence this run produced."""

    store: Any
    tenant_id: str
    release_id: str
    limits: Any
    #: Artifact ids this run created. Evidence outside them is not this run's.
    run_artifacts: set[str] = field(default_factory=set)

    def validate(self, final: FinalResponse, *,
                 executed: bool) -> ValidationReport:
        problems: list[str] = []
        warnings: list[str] = []
        values: dict[str, str] = {}

        for claim in final.numeric_claims:
            problem = self._check_claim(claim)
            if problem:
                problems.append(problem)
            else:
                values[claim.claim_id] = _format(claim)

        referenced = set(PLACEHOLDER.findall(final.narrative))
        declared = {c.claim_id for c in final.numeric_claims}
        for missing in sorted(referenced - declared):
            problems.append(
                f"the narrative references {{{{claim.{missing}}}}} but no "
                f"numeric_claim with that id was supplied.")
        for unused in sorted(declared - referenced):
            warnings.append(
                f"numeric claim {unused!r} was supplied but never referenced "
                f"in the narrative.")

        if final.disposition in ("answer", "partial_answer") \
                and final.intent.query_mode == DATA_ANALYSIS:
            if executed and not final.numeric_claims and not final.tables:
                # A full ANSWER that reports nothing bound to the evidence is
                # asserting a result it cannot support. A PARTIAL answer that
                # says plainly what it could not establish is the honest
                # outcome, not an invalid one -- provided it declares the
                # limitation rather than leaving the gap silent.
                if final.disposition == "answer" or not final.limitations:
                    problems.append(
                        "this data analysis response carries no numeric "
                        "claim and no table, so nothing in it is bound to "
                        "the executed evidence. Either bind the figures, or "
                        "send a partial answer that states what could not be "
                        "established.")
            stripped = PLACEHOLDER.sub("", final.narrative)
            for raw in _BARE_NUMBER.findall(stripped):
                cleaned = raw.replace(",", "").rstrip(".")
                if cleaned in _ALLOWED_BARE or len(cleaned) <= 2:
                    continue
                warnings.append(
                    f"the narrative contains the bare figure {raw!r}. A "
                    f"portfolio number should arrive through a claim "
                    f"placeholder so it is bound to evidence.")

        if not executed and final.numeric_claims:
            problems.append(
                "numeric claims were supplied but no analysis was executed in "
                "this run, so there is no artifact for them to reference.")

        for i, chart in enumerate(final.charts):
            problem = self._check_chart(chart, i)
            if problem:
                # An invalid optional chart is DROPPED with a warning. It does
                # not cost another analysis round.
                warnings.append(problem)

        if len(final.charts) > self.limits.charts:
            warnings.append(
                f"{len(final.charts)} charts were supplied and the limit is "
                f"{self.limits.charts}; the extra charts were dropped.")

        for i, table in enumerate(final.tables):
            artifact_id = str(table.get("artifact_id") or "")
            if artifact_id and artifact_id not in self.run_artifacts:
                problems.append(
                    f"tables[{i}] references artifact {artifact_id!r}, which "
                    f"this run did not produce.")

        rendered = final.narrative
        if not problems:
            rendered = PLACEHOLDER.sub(
                lambda m: values.get(m.group(1), m.group(0)), final.narrative)

        return ValidationReport(
            ok=not problems, rendered_narrative=rendered, problems=problems,
            warnings=warnings, claim_values=values)

    def _check_claim(self, claim: NumericClaim) -> str:
        ref = claim.evidence
        if ref.artifact_id not in self.run_artifacts:
            return (f"claim {claim.claim_id!r} references artifact "
                    f"{ref.artifact_id!r}, which this run did not produce.")
        record = self.store.get_artifact(ref.artifact_id,
                                         tenant_id=self.tenant_id)
        if record is None:
            return (f"claim {claim.claim_id!r} references artifact "
                    f"{ref.artifact_id!r}, which is not available to you.")
        if ref.column_id and ref.column_id not in record["columns"]:
            return (f"claim {claim.claim_id!r} names column "
                    f"{ref.column_id!r}, which is not in artifact "
                    f"{ref.artifact_id!r}. Its columns are "
                    f"{record['columns']}.")
        if not ref.column_id:
            return ""
        found = _locate(record["rows"], ref.row_key, ref.column_id)
        if found is _MISSING:
            return (f"claim {claim.claim_id!r} names row {ref.row_key!r}, "
                    f"which is not in artifact {ref.artifact_id!r}.")
        if found is None:
            return (f"claim {claim.claim_id!r} points at a NULL cell in "
                    f"{ref.artifact_id!r}. A null is not zero: report it as "
                    f"missing or name the reason.")
        try:
            stored = Decimal(str(found))
            asserted = Decimal(claim.decimal_value)
        except (InvalidOperation, ValueError):
            if str(found) != claim.decimal_value:
                return (f"claim {claim.claim_id!r} asserts "
                        f"{claim.decimal_value!r} and the artifact holds "
                        f"{found!r}.")
            return ""
        if stored != asserted:
            # A rounding difference is still a difference: the claim must
            # carry the exact stored value and declare its display precision.
            return (f"claim {claim.claim_id!r} asserts {asserted} and the "
                    f"artifact holds {stored}. Send the exact stored value "
                    f"and set display_precision for how it should read.")
        return ""

    def _check_chart(self, chart: dict[str, Any], index: int) -> str:
        artifact_id = str(chart.get("artifact_id") or "")
        if artifact_id not in self.run_artifacts:
            return (f"chart {index} references artifact {artifact_id!r}, "
                    f"which this run did not produce; the chart was dropped.")
        record = self.store.get_artifact(artifact_id, tenant_id=self.tenant_id)
        if record is None:
            return (f"chart {index} references an artifact not available to "
                    f"you; the chart was dropped.")
        columns = set(record["columns"])
        missing = [c for c in
                   [chart.get("x_column"), *(chart.get("y_columns") or [])]
                   if c and c not in columns]
        if missing:
            return (f"chart {index} names columns {missing} that are not in "
                    f"its artifact; the chart was dropped.")
        return ""

    def surviving_charts(self, final: FinalResponse) -> list[dict[str, Any]]:
        kept = [c for i, c in enumerate(final.charts)
                if not self._check_chart(c, i)]
        return kept[:self.limits.charts]

    def validate_suggestions(self, final: FinalResponse, catalog: Any
                             ) -> list[dict[str, Any]]:
        """Keep only suggestions whose fields and quarters actually exist.

        Checked from catalog metadata, never by running a sample analysis:
        a suggestion is not worth a query.
        """
        kept = []
        calendar = getattr(catalog, "calendar", None)
        quarters = set(getattr(calendar, "slots", ()) or ())
        for suggestion in final.suggested_questions:
            fields = [str(f) for f in (suggestion.get("required_fields") or [])]
            ok = True
            for field_id in fields:
                relation, _, column = str(field_id).partition(".")
                if not column:
                    ok = False
                    break
                try:
                    catalog.resolve(relation, column)
                except Exception:  # noqa: BLE001
                    ok = False
                    break
            for quarter in (suggestion.get("required_quarters") or []):
                if quarters and str(quarter) not in quarters:
                    ok = False
                    break
            if ok:
                kept.append(dict(suggestion))
        return kept


_MISSING = object()


def _locate(rows: list[dict[str, Any]], row_key: str, column: str) -> Any:
    """Find the referenced cell. `row_key` may be an index or a key=value."""
    if not rows:
        return _MISSING
    key = str(row_key or "").strip()
    if key.isdigit():
        index = int(key)
        if 0 <= index < len(rows):
            return rows[index].get(column, _MISSING)
        return _MISSING
    if "=" in key:
        name, _, wanted = key.partition("=")
        name, wanted = name.strip(), wanted.strip()
        for row in rows:
            if str(row.get(name, "")) == wanted:
                return row.get(column, _MISSING)
        return _MISSING
    for row in rows:
        if any(str(v) == key for v in row.values()):
            return row.get(column, _MISSING)
    return _MISSING


def rejection(report: ValidationReport) -> Rejection:
    return Rejection(
        ANSWER_VALIDATION,
        "The response was not published. " + " ".join(report.problems)
        + " Correct the response itself; no new analysis is available for "
          "this correction.",
        field_path="finalize_response",
        detail={"problems": report.problems})


__all__ = ["Finalizer", "PLACEHOLDER", "ValidationReport", "rejection"]
