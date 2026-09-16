"""
Answer validation: check the evidence, render the numbers, rewrite nothing.

What "validated" means here, precisely
--------------------------------------
Every `numeric_claim` is checked against the evidence this run produced, in
one of two ways.

A DIRECT claim names an artifact, a row and a column, and its value must
match what is stored there.

A DERIVED claim names an operation and the cells it consumes, and the value
is RECOMPUTED here from the stored artifact. This is the stricter of the two:
a direct claim is compared against a cell, a derived claim has its whole
arithmetic redone. It exists because a total across twelve sectors, or the
share carried by the largest four, is a real number with no row of its own --
and a validator that only accepted pointers to physical cells left the
analyst no move except inventing a row called "all sectors", which is exactly
what a live run did before being refused twice. The narrative's PROSE is not claimed to be
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

from backend.cockpit_v4 import derivation as deriv
from backend.cockpit_v4 import precision as prec
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

#: Language that asserts an order. Matched against the narrative to decide
#: whether a published chart is making a ranking claim.
_SUPERLATIVE = re.compile(
    r"\b(top|largest|biggest|highest|greatest|smallest|lowest|"
    r"rank(?:ed|ing)?|leading|worst|best|most)\b")


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


def _cell(value: Any, unit: str, disp: Any) -> Any:
    """One published cell, as a reader sees it.

    A null and a non-numeric value pass through unchanged. A number whose
    unit was resolved is written in that unit. A number whose unit nobody
    could name is still written for a person -- no unit asserted, but not
    sixteen digits either, because machine precision reaching a reader is a
    defect whether or not we know what the number measures.
    """
    if value is None:
        return value
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return value
    if unit:
        return disp.format_value(number, unit)
    return disp.format_unitless(number)


def _format(claim: NumericClaim) -> str:
    """Last resort: a claim that never reached the canonical registry.

    Reached only when a claim was neither settled nor rejected, which the
    validator does not allow. It renders whatever the analyst sent rather
    than raising, because an answer that is already being refused should not
    also crash while being described.
    """
    if not claim.decimal_value:
        return ""
    try:
        value = Decimal(claim.decimal_value)
    except InvalidOperation:
        return claim.decimal_value
    return prec.format_value(value, claim.unit, claim.precision())


#: What a chart can say. Below the floor there is nothing to compare; above
#: the ceiling there is nothing a reader can take in, and the honest form of
#: a ninety-row result is a table.
MIN_CHART_POINTS = 2
MAX_CHART_POINTS = 25


@dataclass
class Finalizer:
    """Checks one final response against the evidence this run produced."""

    store: Any
    tenant_id: str
    release_id: str
    limits: Any
    #: Artifact ids this run created. Evidence outside them is not this run's.
    run_artifacts: set[str] = field(default_factory=set)
    #: claim_id -> the canonical value and the display form it was checked
    #: against. Rendering reads THIS, not the analyst's string, so the
    #: published figure is CreditProbe's rounding of CreditProbe's
    #: arithmetic rather than whatever the model happened to type.
    canonical: dict[str, Any] = field(default_factory=dict)
    #: claim_id -> the stored text of a non-numeric cell (a sector name, a
    #: rating grade). Rounding a category is meaningless, so these never
    #: reach the precision policy and are published exactly as stored.
    text: dict[str, str] = field(default_factory=dict)
    #: The claims this run validated. Read when rendering a table, so a
    #: column's unit is one the answer has already been held to rather than
    #: one the renderer chose for it.
    _claims: tuple = ()
    #: The run's release header. Evidence is checked against it: an artifact
    #: from a DIFFERENT build of the same release id is not this run's
    #: evidence, and an id alone cannot tell them apart.
    header: Any = None

    def validate(self, final: FinalResponse, *,
                 executed: bool) -> ValidationReport:
        problems: list[str] = []
        warnings: list[str] = []
        values: dict[str, str] = {}
        self._claims = tuple(final.numeric_claims)

        for claim in final.numeric_claims:
            problem = self._check_claim(claim)
            if problem:
                problems.append(problem)
            else:
                values[claim.claim_id] = self._render(claim)

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
            problems.extend(self._check_table(table, i))

        problems.extend(self._check_ordering(final))

        rendered = final.narrative
        if not problems:
            rendered = PLACEHOLDER.sub(
                lambda m: values.get(m.group(1), m.group(0)), final.narrative)

        return ValidationReport(
            ok=not problems, rendered_narrative=rendered, problems=problems,
            warnings=warnings, claim_values=values)

    def _render(self, claim: NumericClaim) -> str:
        """The published text of a claim, from the canonical value."""
        if claim.claim_id in self.text:
            return self.text[claim.claim_id]
        verdict = self.canonical.get(claim.claim_id)
        if verdict is None:
            return _format(claim)
        return prec.format_value(verdict.canonical, claim.unit,
                                 verdict.precision)

    def release_problem(self, artifact_id: str) -> str:
        """Is this artifact from the same release, and the same bytes?

        A release id is a name. Two builds of one id have the same name and
        different numbers, and an artifact stored before a rebuild satisfies
        "same release_id" against the rebuild perfectly. The fingerprint is
        what the two cannot share.
        """
        if self.header is None:
            return ""
        record = self.store.get_artifact(artifact_id,
                                         tenant_id=self.tenant_id)
        if record is None:
            return ""
        if str(record.get("release_id") or "") != self.header.release_id:
            return (f"artifact {artifact_id!r} was computed from release "
                    f"{record.get('release_id')!r} and this run is answering "
                    f"from {self.header.release_id!r}. A figure from one "
                    f"release is not evidence for another.")
        stored = str((record.get("scope") or {}).get(
            "release_fingerprint") or "")
        if stored and stored != self.header.release_fingerprint:
            return (f"artifact {artifact_id!r} carries release "
                    f"{self.header.release_id!r} but was computed from a "
                    f"different build of it. Same name, different numbers.")
        return ""

    def _artifacts(self, ids) -> dict[str, Any]:
        """The stored artifacts for a derivation, tenant-checked."""
        out: dict[str, Any] = {}
        for artifact_id in ids:
            if artifact_id not in self.run_artifacts:
                continue
            record = self.store.get_artifact(artifact_id,
                                             tenant_id=self.tenant_id)
            if record is not None:
                out[artifact_id] = record
        return out

    def _settle(self, claim: NumericClaim, computed, *, label: str) -> str:
        """Record the canonical value, checking any figure the analyst sent.

        Two paths, and the difference is the whole point of this round.

        The analyst sent NOTHING: there is no figure to disagree with. The
        value CreditProbe computed is the value, and the display policy says
        how it is written. A correct analysis cannot be refused here.

        The analyst sent a figure: it is a cross-check and it is checked as
        strictly as before. Wrong arithmetic still fails.
        """
        precision = claim.precision()
        if not claim.asserts_a_value:
            canonical = prec.plain(computed)
            self.canonical[claim.claim_id] = prec.Verdict(
                True, canonical=canonical,
                display=prec.plain(prec.quantize(canonical, precision)),
                precision=precision)
            return ""
        verdict = prec.check(claim.decimal_value, computed, unit=claim.unit,
                             declared_precision=precision, label=label)
        if not verdict.ok:
            return verdict.problem
        self.canonical[claim.claim_id] = verdict
        return ""

    def _check_derived(self, claim: NumericClaim) -> str:
        """Recompute the claim. Its arithmetic is redone, not taken on trust."""
        label = f"claim {claim.claim_id!r}"
        try:
            derivation = deriv.parse(claim.derivation)
        except deriv.DerivationError as exc:
            return f"{label}: {exc}"

        for artifact_id in derivation.artifact_ids:
            if artifact_id not in self.run_artifacts:
                return (f"{label} references artifact {artifact_id!r}, which "
                        f"this run did not produce.")
            if self.store.get_artifact(artifact_id,
                                       tenant_id=self.tenant_id) is None:
                return (f"{label} references artifact {artifact_id!r}, which "
                        f"is not available to you.")
            wrong_release = self.release_problem(artifact_id)
            if wrong_release:
                return f"{label}: {wrong_release}"

        unit_wrong = deriv.unit_problem(derivation, claim.unit)
        if unit_wrong:
            return f"{label}: {unit_wrong}"

        try:
            computed = deriv.compute(derivation,
                                     self._artifacts(derivation.artifact_ids),
                                     label=label)
        except deriv.DerivationError as exc:
            return f"{exc}"

        problem = self._settle(claim, computed, label=label)
        if problem:
            return f"{problem} (derivation: {derivation.operation})"
        return ""

    def _check_claim(self, claim: NumericClaim) -> str:
        if claim.is_derived:
            return self._check_derived(claim)
        ref = claim.evidence
        if ref.artifact_id not in self.run_artifacts:
            return (f"claim {claim.claim_id!r} references artifact "
                    f"{ref.artifact_id!r}, which this run did not produce.")
        record = self.store.get_artifact(ref.artifact_id,
                                         tenant_id=self.tenant_id)
        if record is None:
            return (f"claim {claim.claim_id!r} references artifact "
                    f"{ref.artifact_id!r}, which is not available to you.")
        wrong_release = self.release_problem(ref.artifact_id)
        if wrong_release:
            return f"claim {claim.claim_id!r}: {wrong_release}"
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
        except (InvalidOperation, ValueError):
            # A non-numeric cell -- a sector name, a rating grade. Compared
            # as text, because rounding a category is meaningless.
            if claim.asserts_a_value and str(found) != claim.decimal_value:
                return (f"claim {claim.claim_id!r} asserts "
                        f"{claim.decimal_value!r} and the artifact holds "
                        f"{found!r}.")
            self.text[claim.claim_id] = str(found)
            return ""
        return self._settle(claim, stored,
                            label=f"claim {claim.claim_id!r}")

    # -- rendering ------------------------------------------------------

    def _units_for(self, artifact_id: str, columns: list[str],
                   catalog: Any) -> dict[str, str]:
        """What unit each published column is in. Asked, never assumed.

        Two sources, in order, and no third:

          1. A NUMERIC CLAIM already bound to this artifact and column. The
             analyst declared that unit, the validator checked it against
             the arithmetic, and it is therefore a unit this answer has
             already been held to.
          2. The CATALOGUE, when the column name is a field it knows.

        A column neither source can name is published as a plain number.
        That is the honest outcome: a column called `total` could be an
        amount, a count of them or a ratio, and printing a currency beside
        it because the query produced floats is how a reader is shown a
        denomination nobody computed.
        """
        out: dict[str, str] = {}
        for claim in self._claims:
            ref = claim.evidence
            if ref.artifact_id == artifact_id and ref.column_id:
                out.setdefault(str(ref.column_id), claim.unit)
            for operand in ((claim.derivation or {}).get("operands") or []):
                if not isinstance(operand, dict):
                    continue
                if str(operand.get("artifact_id") or "") != artifact_id:
                    continue
                column = str(operand.get("column_id") or "")
                if column:
                    out.setdefault(column, claim.unit)
        if catalog is not None:
            from backend.cockpit_v4 import display as disp

            relations = []
            record = self.store.get_artifact(artifact_id,
                                             tenant_id=self.tenant_id)
            if record is not None:
                relations = list((record.get("scope") or {}).get(
                    "relations", ()))
            for column in columns:
                if column in out:
                    continue
                for relation in relations:
                    unit = disp.unit_for_field(catalog, relation, column)
                    if unit:
                        out[column] = unit
                        break
        return out

    #: What a reader is told when the numbers arrive without their write-up.
    #:
    #: Written HERE, by the server, and never by the model -- the model is
    #: precisely the thing that failed. It says what happened in the order a
    #: reader needs it: the analysis ran, the rows are real, the explanation
    #: is what is missing.
    RESULT_ONLY_NARRATIVE = (
        "**The analysis ran and its result is below.** CreditProbe could "
        "not write the accompanying explanation, so what follows is the "
        "query's own output with no commentary on it.\n\n"
        "Every figure here was computed and stored by CreditProbe and is "
        "shown exactly as it was recorded. Nothing in this response was "
        "written by the analyst.")

    def result_only_response(self, *, reason: str, purposes: Any = None,
                             catalog: Any = None,
                             intent: Any = None) -> dict[str, Any]:
        """The computed result, published without a written answer.

        The defect this exists for
        --------------------------
        A live run executed its query, stored three result artifacts, and
        then could not write the answer about them. The reader was shown
        "This request stopped. Reason: ANSWER_FORMAT_EXHAUSTED" and nothing
        else -- no rows, no export, and on a refresh no record that the
        exchange had happened at all.

        The rows were never lost. They were in the artifact store the whole
        time, individually serveable, with their ids known to the
        orchestrator. What they did not have was an ADDRESS: the only
        channel a result can reach a reader through is the written answer
        object, and failing to produce that object is exactly what had
        happened.

        So this builds the object from the stored artifacts instead, with a
        server-written caveat in place of the narrative and NO numeric
        claims -- a claim is a thing the analyst asserted and had checked,
        and there is no analyst here to assert one. Every number comes from
        `render_tables`, which reads the artifact and formats it under the
        one display policy, so nothing published this way has passed
        through a model.

        Returns `{}` when there is nothing to publish, which is the correct
        answer for a run that never executed anything.
        """
        artifacts = sorted(self.run_artifacts)
        if not artifacts:
            return {}
        titles = dict(purposes or {})

        tables: list[dict[str, Any]] = []
        for artifact_id in artifacts:
            record = self.store.get_artifact(artifact_id,
                                             tenant_id=self.tenant_id)
            if record is None or not record.get("columns"):
                continue
            step_id = str((record.get("scope") or {}).get("step_id") or "")
            tables.append({
                "artifact_id": artifact_id,
                "title": (titles.get(step_id) or titles.get(artifact_id)
                          or "Result"),
                "columns": list(record["columns"])})
        if not tables:
            return {}

        # Rendered by the SAME code path a published answer uses, so a
        # reader sees one table format whatever produced it.
        shell = FinalResponse(
            intent=intent, disposition="partial_answer",
            narrative=self.RESULT_ONLY_NARRATIVE, coverage=(),
            numeric_claims=(), evidence_refs=(), tables=tuple(tables),
            charts=(), limitations=(), suggested_questions=(),
            clarification_question="", clarification_options=(),
            referral_owner="", referral_reason="")
        rendered = self.render_tables(shell, catalog)

        body: dict[str, Any] = {
            "intent": intent.to_dict() if intent is not None else {},
            "disposition": "partial_answer",
            "narrative": self.RESULT_ONLY_NARRATIVE,
            "coverage": [], "numeric_claims": [], "evidence_refs": [],
            "tables": rendered, "charts": [],
            "limitations": [
                "The written answer could not be produced, so these rows "
                "are published without an explanation of them.",
                reason],
            "suggested_questions": [],
            "clarification_question": "", "clarification_options": [],
            "referral_owner": "", "referral_reason": "",
            "evidence_bound": False,
            "executed": True,
            # The flag the reader's caveat banner hangs on, and the one
            # thing that distinguishes this from an answer somebody wrote.
            "result_only": True,
            "result_only_reason": reason,
        }
        if self.header is not None:
            body["release"] = self.header.to_dict()
        return body

    def render_tables(self, final: FinalResponse,
                      catalog: Any = None) -> list[dict[str, Any]]:
        """The rows a reader sees, built here from the stored artifact.

        The analyst chose the table: which result, which columns, what to
        call it. Every VALUE in it comes from the artifact CreditProbe
        executed and stored, formatted by the one display policy. No number
        in a published table has passed through the model.

        Ordering is the artifact's own, which the query produced at full
        precision. Sorting formatted strings would put SAR 9,000 million
        above SAR 40,599 million.
        """
        from backend.cockpit_v4 import display as disp

        out: list[dict[str, Any]] = []
        for table in final.tables:
            artifact_id = str(table.get("artifact_id") or "")
            record = (self.store.get_artifact(artifact_id,
                                              tenant_id=self.tenant_id)
                      if artifact_id in self.run_artifacts else None)
            body = dict(table)
            if record is None:
                out.append(body)
                continue
            columns = [str(c) for c in (table.get("columns")
                                        or record["columns"])]
            units = self._units_for(artifact_id, columns, catalog)
            rows = []
            for index, row in enumerate(record["rows"]):
                rows.append({
                    "row_id": deriv.row_id_for(index),
                    "canonical": {c: row.get(c) for c in columns},
                    "display": {c: _cell(row.get(c), units.get(c, ""), disp)
                                for c in columns},
                })
            body.update({"columns": columns, "column_units": units,
                         "rows": rows, "row_count": len(rows),
                         "rendered_by": "creditprobe"})
            out.append(body)
        return out

    def render_charts(self, charts: list[dict[str, Any]],
                      catalog: Any = None) -> list[dict[str, Any]]:
        """The same contract for a chart: the server supplies every point.

        The analyst decided a chart is useful and which series to show. The
        values are the artifact's, at full precision for ordering and scale,
        with the reader's form carried beside each point for axis labels and
        tooltips.
        """
        from backend.cockpit_v4 import display as disp

        out: list[dict[str, Any]] = []
        for chart in charts:
            artifact_id = str(chart.get("artifact_id") or "")
            record = (self.store.get_artifact(artifact_id,
                                              tenant_id=self.tenant_id)
                      if artifact_id in self.run_artifacts else None)
            body = dict(chart)
            if record is None:
                out.append(body)
                continue
            label = str(chart.get("x_column") or "")
            series = [str(c) for c in (chart.get("y_columns") or []) if c]
            units = self._units_for(artifact_id,
                                    [c for c in [label, *series] if c],
                                    catalog)
            # The unit the analyst DECLARED on the chart is authoritative for
            # its own axis: a chart is allowed to plot a measure no claim
            # happens to cite. The catalogue still fills in what it can.
            declared = str(chart.get("unit") or "")
            points = []
            for index, row in enumerate(record["rows"]):
                values = {c: row.get(c) for c in series}
                points.append({
                    "row_id": deriv.row_id_for(index),
                    "label": row.get(label) if label else None,
                    "values": values,
                    "display": {
                        c: _cell(values[c], units.get(c, declared), disp)
                        for c in series},
                })
            body.update({"points": points,
                         "series_units": {c: units.get(c, declared)
                                          for c in series},
                         "rendered_by": "creditprobe"})
            out.append(body)
        return out

    def _check_table(self, table: dict[str, Any], index: int) -> list[str]:
        """A published table must project columns the artifact really has.

        A table carries no values of its own: it names an artifact and the
        columns to show, and the reader is served the stored rows. That is
        why a table cannot misreport a number -- but it CAN name a column
        that does not exist, which renders as an empty column and reads as
        missing data rather than as a mistake in the answer.
        """
        problems: list[str] = []
        artifact_id = str(table.get("artifact_id") or "")
        if not artifact_id:
            return problems
        if artifact_id not in self.run_artifacts:
            return [f"tables[{index}] references artifact {artifact_id!r}, "
                    f"which this run did not produce."]
        record = self.store.get_artifact(artifact_id,
                                         tenant_id=self.tenant_id)
        if record is None:
            return [f"tables[{index}] references artifact {artifact_id!r}, "
                    f"which is not available to you."]
        available = set(record["columns"])
        missing = [c for c in (table.get("columns") or [])
                   if str(c) not in available]
        if missing:
            problems.append(
                f"tables[{index}] names columns {missing}, which are not in "
                f"artifact {artifact_id!r}. Its columns are "
                f"{record['columns']}.")
        return problems

    def _check_ordering(self, final: FinalResponse) -> list[str]:
        """A ranking claimed in words must be a ranking in the evidence.

        Checked only where the answer both CLAIMS an order ("the largest",
        "top five") and publishes a chart, because a chart of ranked bars is
        the reader's ranking. The test is monotonicity on the charted
        measure, in either direction -- an ascending chart under "the
        smallest" is as correct as a descending one under "the largest". It
        catches the specific error of a query that forgot its ORDER BY under
        an answer that says "the biggest", which no other check would see.
        """
        if not final.charts:
            return []
        words = final.narrative.lower()
        if not _SUPERLATIVE.search(words):
            return []
        problems: list[str] = []
        for index, chart in enumerate(final.charts):
            artifact_id = str(chart.get("artifact_id") or "")
            if artifact_id not in self.run_artifacts:
                continue
            record = self.store.get_artifact(artifact_id,
                                             tenant_id=self.tenant_id)
            if record is None:
                continue
            for column in (chart.get("y_columns") or [])[:1]:
                values = []
                for row in record["rows"]:
                    cell = row.get(column)
                    if cell is None:
                        values = []
                        break
                    try:
                        values.append(Decimal(str(cell)))
                    except InvalidOperation:
                        values = []
                        break
                if len(values) < 3:
                    continue
                descending = all(a >= b for a, b in zip(values, values[1:]))
                ascending = all(a <= b for a, b in zip(values, values[1:]))
                if not (descending or ascending):
                    problems.append(
                        f"the answer claims a ranking and charts "
                        f"{column!r}, but artifact {artifact_id!r} is not "
                        f"ordered by it. Order the query by the measure you "
                        f"are ranking, or drop the ranking language.")
        return problems

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
        return self._chart_shape_problem(chart, index, record)

    def _chart_shape_problem(self, chart: dict[str, Any], index: int,
                             record: dict[str, Any]) -> str:
        """Is this result the shape a chart can actually say something about?

        §26: the analyst decides whether a picture helps; CreditProbe checks
        the decision against the result it would be drawn from. Two things
        make a chart useless whatever was intended, and both are countable.

        ONE POINT is not a comparison. A single scalar drawn as one bar tells
        a reader nothing they did not read in the sentence above it.

        TOO MANY POINTS is not a comparison either. Twelve sectors ranked by
        exposure is a chart; ninety borrowers with their covenant status is a
        list, and drawing it produces a wall of bars nobody reads and a
        label column nobody can align. This is the live case in §29 -- a
        "show me the customers behind this" answer arrived with a bar per
        borrower, which is a worse way to read the same table.

        Note what this does NOT do: infer intent from the question, or from
        the column names, or from the grain. A top-ten borrower ranking is
        ten points and passes, because ten points IS a readable comparison
        whatever the rows are called.
        """
        label = str(chart.get("x_column") or "")
        rows = record["rows"]
        points = (len({str(row.get(label)) for row in rows}) if label
                  else len(rows))
        if points < MIN_CHART_POINTS:
            return (f"chart {index} would have {points} point(s); a chart "
                    f"needs at least {MIN_CHART_POINTS} to compare anything. "
                    f"The table says it better and the chart was dropped.")
        if points > MAX_CHART_POINTS:
            return (f"chart {index} would have {points} points, past the "
                    f"{MAX_CHART_POINTS} a reader can take in. A result this "
                    f"long is a table -- rank it and show the top rows if a "
                    f"picture is wanted. The chart was dropped.")
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


def _close(asserted: Decimal, computed: Decimal) -> bool:
    """Exact, or within the last place of a rounded display value.

    Not a licence to be approximately right. A derived figure is compared at
    a relative 1e-9, which absorbs a decimal string the analyst rounded and
    nothing wider -- a dropped row moves these by whole millions.
    """
    if asserted == computed:
        return True
    if computed == 0:
        return abs(asserted) <= deriv.DEFAULT_TOLERANCE
    return abs(asserted - computed) / abs(computed) <= deriv.DEFAULT_TOLERANCE


_MISSING = object()


def _locate(rows: list[dict[str, Any]], row_key: str, column: str) -> Any:
    """Find the referenced cell.

    `row_key` may be a published row id ("r0"), a bare index, a
    `column=value` key, or a value that appears in exactly that row. The
    vocabulary is deliberately the SAME one the derivation resolver accepts:
    the result packet publishes "r0", and a direct claim citing "r0" being
    refused while a derivation citing "r0" was accepted would be a trap of
    our own making.
    """
    if not rows:
        return _MISSING
    index = deriv._index_of(row_key, rows)
    if index < 0:
        return _MISSING
    return rows[index].get(column, _MISSING)


def correction_packet(final: FinalResponse, report: ValidationReport, *,
                      store: Any, tenant_id: str,
                      run_artifacts: set[str]) -> dict[str, Any]:
    """Everything needed to fix the BINDING, and nothing that reruns anything.

    The live EAD run failed validation twice over row names, and each
    rejection sent back prose. Prose is enough to know something is wrong and
    not enough to fix it: the analyst was never told what the row ids
    actually were. This packet answers that directly -- here is the artifact
    you may cite, here are its columns, here are its row ids, here is how a
    calculated number must be expressed -- so the repair is a rewrite of the
    evidence binding rather than another guess.
    """
    artifacts = []
    for artifact_id in sorted(run_artifacts):
        record = store.get_artifact(artifact_id, tenant_id=tenant_id)
        if record is None:
            continue
        rows = record["rows"]
        artifacts.append({
            "artifact_id": artifact_id,
            "columns": record["columns"],
            "row_count": len(rows),
            "row_ids": [deriv.row_id_for(i) for i in range(len(rows))],
            "rows": [{"row_id": deriv.row_id_for(i), **row}
                     for i, row in enumerate(rows)],
        })
    return {
        "what_to_do": (
            "Send finalize_response again with the SAME analysis and "
            "corrected evidence. The query already ran and its result is "
            "below; do not run it again, do not read the catalogue again, "
            "and do not ask the user anything."),
        "problems": list(report.problems),
        "rejected_claims": [
            {"claim_id": c.claim_id, "claimed_value": c.decimal_value,
             "unit": c.unit,
             "kind": "derived" if c.is_derived else "direct"}
            for c in final.numeric_claims],
        "authorized_artifacts": artifacts,
        "direct_value": (
            "A number that appears in one result cell: send 'evidence' with "
            "artifact_id, row_id and column_id."),
        "row_scope": (
            "Each operand says WHICH cells one way and not both: "
            "rows='all' for every row of that result -- a total, or the "
            "denominator of a share -- or row_ids naming the ones you mean. "
            "rows='all' is refused on a result that was clipped at the "
            "preview cap."),
        "calculated_value": (
            "A number calculated from the result -- a total, a share, a "
            "difference, a growth rate: send 'derivation' instead of "
            "'evidence'. Do NOT invent a row such as 'all sectors' or 'top "
            "4 sectors'; name the real row ids and let the operation add "
            "them up."),
        "operations": deriv.describe(),
    }


def rejection(report: ValidationReport) -> Rejection:
    return Rejection(
        ANSWER_VALIDATION,
        "The response was not published. " + " ".join(report.problems)
        + " Correct the response itself; no new analysis is available for "
          "this correction.",
        field_path="finalize_response",
        detail={"problems": report.problems})


__all__ = ["Finalizer", "MAX_CHART_POINTS", "MIN_CHART_POINTS",
           "PLACEHOLDER", "ValidationReport",
           "correction_packet", "rejection"]
