"""From a sentence somebody typed to a metric on a Lens. §10–§13.

    read → generate → validate → APPROVE → preview → LOCK

The two words in capitals are the ones this module exists for. Everything
before them is CreditProbe working; those two are a person deciding, and the
whole design question is how to make that decision real rather than a button
somebody clicks past.

Nothing is stored before the lock
----------------------------------
The artefact travels in the request body through every step, exactly as the
existing metric builder's draft does. That is not a convenience: it means
there is no half-built metric in the catalogue for a lens to find, and it means
§11's rule — code that came back from a browser is not trusted for having been
there — is enforced by construction, because the ONLY thing the server has is
what the browser sent, and it revalidates all of it on every call.

Approval is bound to what was approved
---------------------------------------
`approve` records a checksum over the code, the program and the declared
shape. `preview` and `lock` recompute it and refuse if it has moved. Without
that, a browser could show one definition, collect the approval, and send a
different one to be locked — and every screen afterwards would say the metric
had been approved, which it would not have been.

Preview runs the real thing
----------------------------
§12 asks for the actual calculation lineage: the current period, the current
value, the previous period, the previous value, the arithmetic between them,
and the population behind each. `preview` runs the governed program against
authorised data and returns exactly that — the numerator and denominator as
separate figures with their own periods and row counts, because "41.8 / 39.6
= +5.56%" is the sentence somebody checks and a single percentage is not.

What editing the code does
---------------------------
§11. An edited artefact goes back through the whole validator, its §6 facts
are recomputed from the program rather than trusted, and `divergence` says in
words what the edit changed about the metric's meaning — a dataset added, a
filter dropped, a denominator removed. Approval is cleared by any edit, which
is what stops "approved" from being a state a metric keeps while its
definition changes underneath it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from backend.metrics import codegen, codeguard
from backend.metrics import lens_domains as domains
from backend.metrics.metric_code import (
    AUTHOR_USER,
    STAGE_APPROVED,
    STAGE_LOCKED,
    STAGE_PREVIEWED,
    MetricCode,
)

logger = logging.getLogger(__name__)

FLOW_VERSION = "3.0.0"


class ApprovalRequired(ValueError):
    """Something asked to run or lock code nobody has approved."""


class ApprovalStale(ValueError):
    """The code changed after it was approved."""


# ---------------------------------------------------------------------------
# Reading and generating
# ---------------------------------------------------------------------------


def read(said: str, *, budget: Any = None, model: str = "",
         effort: str = "") -> dict[str, Any]:
    """§4, §5, §34. What the person typed, located and flagged, not rewritten."""
    from backend.metrics import formula_intake

    intake = formula_intake.read(said, model=model, effort=effort,
                                 budget=budget)
    return intake.to_dict()


def draft(said: str, *, period: str = "", lens: dict[str, Any] | None = None,
          user_id: int | None = None, readable: Any = None,
          keep_formula: str = "", budget: Any = None, model: str = "",
          effort: str = "") -> dict[str, Any]:
    """§6–§9. Read the formula, write the code, validate it, repair it.

    `keep_formula` is §5's answer: where the person was shown an
    unconventional formula and chose the conventional one, THEIR CHOICE
    arrives here as the formula to compute. It replaces the typed formula only
    because they said so, and the artefact records both.
    """
    from backend.metrics import formula_intake

    intake = formula_intake.read(said, model=model, effort=effort,
                                 budget=budget)
    chosen_note = ""
    if keep_formula and keep_formula != intake.formula_text:
        if intake.unconventional and keep_formula == intake.unconventional.conventional:
            chosen_note = (
                f"You entered '{intake.formula_text}' and chose the "
                f"conventional form instead. CreditProbe is computing "
                f"'{keep_formula}'.")
        else:
            chosen_note = (
                f"You edited the formula from '{intake.formula_text}' to "
                f"'{keep_formula}'. CreditProbe is computing what you edited "
                "it to.")
        # Re-read the chosen formula so the numerator, denominator and period
        # offsets come from IT rather than from the one it replaced. Reusing
        # the old sides would compute the old formula under the new label,
        # which is the failure §5 is about wearing a different hat.
        intake = formula_intake.read(keep_formula, model=model, effort=effort,
                                     budget=budget)
        intake.notes.append(chosen_note)

    code, verdict = codegen.generate(
        intake, period=period, lens=lens, user_id=user_id, readable=readable,
        budget=budget, model=model, effort=effort)
    return {
        "intake": intake.to_dict(),
        "code": code.to_dict(),
        "validation": verdict.to_dict(),
        "ready": verdict.ok,
        "chosen_note": chosen_note,
    }


def revise(code: MetricCode, *, period: str = "", readable: Any = None,
           edited_by_user: bool = False,
           previous: MetricCode | None = None) -> dict[str, Any]:
    """§11. Revalidate an artefact that came back from a browser.

    Nothing is trusted: not the datasets it claims to read, not the fields it
    lists, not the fact that it was validated before. The §6 facts are
    recomputed from the program and the whole validator runs again.
    """
    if edited_by_user:
        code.author = AUTHOR_USER
    code, verdict = codegen.revalidate(code, period=period, readable=readable)
    payload = {
        "code": code.to_dict(),
        "validation": verdict.to_dict(),
        "ready": verdict.ok,
    }
    if previous is not None:
        payload["divergence"] = divergence(previous, code)
    return payload


def divergence(before: MetricCode, after: MetricCode) -> dict[str, Any]:
    """§11. What an edit changed about what the metric MEANS, in sentences.

    Not a diff of the text. A reformatted query means the same thing and
    should say nothing; a query that no longer reads Stage 3 means something
    different and must say so before anybody proceeds.
    """
    changes: list[str] = []
    was, now = set(before.datasets), set(after.datasets)
    if was != now:
        added, gone = sorted(now - was), sorted(was - now)
        if added:
            changes.append(f"It now reads {', '.join(added)}, which it did not.")
        if gone:
            changes.append(
                f"It no longer reads {', '.join(gone)}, which it did.")

    was_fields, now_fields = set(before.fields), set(after.fields)
    if was_fields != now_fields:
        added, gone = sorted(now_fields - was_fields), sorted(was_fields - now_fields)
        if added:
            changes.append(f"It now uses the field(s) {', '.join(added)}.")
        if gone:
            changes.append(f"It no longer uses the field(s) {', '.join(gone)}.")

    was_filters, now_filters = set(before.filters), set(after.filters)
    if was_filters != now_filters:
        added, gone = sorted(now_filters - was_filters), sorted(was_filters - now_filters)
        if added:
            changes.append(f"A filter was added: {'; '.join(added)}.")
        if gone:
            changes.append(
                f"A filter was removed: {'; '.join(gone)}. The metric now "
                "covers a wider population than the formula describes.")

    if codeguard._has_denominator(before) != codeguard._has_denominator(after):
        changes.append(
            "The denominator was removed, so this is now an amount rather "
            "than a share."
            if codeguard._has_denominator(before)
            else "A denominator was added, so this is now a share rather than "
                 "an amount.")

    if before.unit != after.unit:
        changes.append(f"The unit changed from {before.unit} to {after.unit}.")

    matches_formula = not changes
    return {
        "changed": bool(changes),
        "changes": changes,
        "matches_original_formula": matches_formula,
        "original_formula": before.user_formula,
        "note": (
            "" if matches_formula else
            f"This no longer matches the formula you wrote — "
            f"'{before.user_formula}'. Confirm before continuing."),
        "confirmation_required": bool(changes),
    }


# ---------------------------------------------------------------------------
# Approval
# ---------------------------------------------------------------------------


def approve(code: MetricCode, *, note: str = "", period: str = "",
            readable: Any = None) -> dict[str, Any]:
    """§10. The person has read the code and accepts it.

    Revalidated first, and refused if it does not pass. An approval recorded
    over code CreditProbe would not run is an approval of nothing.
    """
    code, verdict = codegen.revalidate(code, period=period, readable=readable)
    if not verdict.ok:
        return {"code": code.to_dict(), "validation": verdict.to_dict(),
                "approved": False,
                "why": "CreditProbe will not run this code, so there is "
                       "nothing to approve. The reasons are listed above."}
    code.stage = STAGE_APPROVED
    code.approval_note = (note or "").strip()[:2000]
    return {"code": code.to_dict(), "validation": verdict.to_dict(),
            "approved": True, "checksum": code.checksum()}


def _require_approved(code: MetricCode, approved_checksum: str) -> None:
    if code.stage not in (STAGE_APPROVED, STAGE_PREVIEWED, STAGE_LOCKED):
        raise ApprovalRequired(
            "This code has not been approved. CreditProbe runs generated code "
            "only after somebody has read it and said so.")
    if approved_checksum and approved_checksum != code.checksum():
        raise ApprovalStale(
            "The code changed after it was approved, so the approval no "
            "longer covers it. Read the current definition and approve it "
            "again.")


# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------


@dataclass
class Preview:
    """§12. The exact calculation, with everything that produced it."""

    value: float | None = None
    formatted: str = ""
    unit: str = "number"
    period: str = ""
    final: str = ""
    numerator: dict[str, Any] = field(default_factory=dict)
    denominator: dict[str, Any] = field(default_factory=dict)
    terms: list[dict[str, Any]] = field(default_factory=list)
    rows_considered: int = 0
    datasets: list[str] = field(default_factory=list)
    domains: list[str] = field(default_factory=list)
    filters: list[str] = field(default_factory=list)
    group_by: str = ""
    join_logic: str = ""
    data_version: str = ""
    code_version: str = ""
    run_id: str = ""
    sql: str = ""
    compiled_sql: str = ""
    warnings: list[str] = field(default_factory=list)
    unavailable: str = ""

    @property
    def available(self) -> bool:
        return self.value is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": self.value, "formatted": self.formatted,
            "unit": self.unit, "period": self.period, "final": self.final,
            "numerator": dict(self.numerator),
            "denominator": dict(self.denominator),
            "terms": list(self.terms),
            "rows_considered": self.rows_considered,
            "datasets": list(self.datasets), "domains": list(self.domains),
            "filters": list(self.filters), "group_by": self.group_by,
            "join_logic": self.join_logic,
            "data_version": self.data_version,
            "code_version": self.code_version, "run_id": self.run_id,
            "sql": self.sql, "compiled_sql": self.compiled_sql,
            "warnings": list(self.warnings), "unavailable": self.unavailable,
            "available": self.available,
        }


def _format(value: float | None, unit: str, decimals: int) -> str:
    if value is None:
        return "—"
    if unit == "percent":
        return f"{value:,.{decimals}f}%"
    if unit == "currency":
        return f"{value:,.{decimals}f}"
    if unit == "count":
        return f"{value:,.0f}"
    return f"{value:,.{decimals}f}"


def preview(code: MetricCode, *, period: str = "", user_id: int | None = None,
            readable: Any = None, approved_checksum: str = "") -> dict[str, Any]:
    """§12. Run the approved program against real authorised data.

    The governed program runs, not the SQL. §7: the model's code is read and
    approved; CreditProbe executes the plan it was reconciled against.
    """
    _require_approved(code, approved_checksum)
    code, verdict = codegen.revalidate(code, period=period, readable=readable)
    if not verdict.ok:
        return {"code": code.to_dict(), "validation": verdict.to_dict(),
                "preview": Preview(
                    unavailable="CreditProbe re-checked this code before "
                                "running it and will not run it. The reasons "
                                "are listed above.").to_dict()}

    result = _run(code, period=period, user_id=user_id, readable=readable)
    code.stage = STAGE_PREVIEWED
    return {"code": code.to_dict(), "validation": verdict.to_dict(),
            "preview": result.to_dict(), "checksum": code.checksum()}


def _run(code: MetricCode, *, period: str, user_id: int | None,
         readable: Any) -> Preview:
    from backend.metrics import composite as composite_mod
    from backend.metrics import execution
    from backend.metrics import service as metrics

    out = Preview(unit=code.unit, period=period,
                  datasets=list(code.datasets), domains=list(code.domains),
                  filters=list(code.filters), join_logic=code.join_logic,
                  sql=code.sql, compiled_sql=code.compiled_sql,
                  code_version=code.checksum())

    if not period:
        try:
            period = _default_period(code)
            out.period = period
        except Exception as e:  # noqa: BLE001 - reported, not raised
            out.unavailable = str(e)
            return out

    def resolver(metric_id: str) -> Any:
        return metrics.resolve(metric_id, user_id=user_id, readable=readable)

    try:
        if code.composite is not None:
            calculation = composite_mod.run(
                code.composite, period=period, scope=code.scope_tuple(),
                user_id=user_id, resolver=resolver)
            out.value = calculation.value
            out.final = calculation.final_expression
            out.warnings = list(calculation.warnings)
            out.unavailable = calculation.unavailable
            if calculation.numerator:
                out.numerator = calculation.numerator.to_dict()
                out.run_id = calculation.numerator.run_id
                out.rows_considered = calculation.numerator.rows
            if calculation.denominator:
                out.denominator = calculation.denominator.to_dict()
            out.terms = [t for side in (out.numerator, out.denominator)
                         for t in ((side.get("detail") or {}).get("numerator")
                                   or {}).get("terms", [])]
        elif code.formula is not None:
            calculation = execution.run(
                code.formula, period=period, scope=code.scope_tuple(),
                question=code.name or "metric preview")
            out.value = calculation.value
            out.final = calculation.final_expression
            out.rows_considered = calculation.rows_considered
            out.run_id = calculation.run_id
            out.warnings = list(calculation.warnings)
            out.unavailable = calculation.unavailable
            out.compiled_sql = calculation.sql or out.compiled_sql
            if calculation.numerator:
                out.numerator = calculation.numerator.to_dict()
                out.terms = list(out.numerator.get("terms") or [])
            if calculation.denominator:
                out.denominator = calculation.denominator.to_dict()
                out.terms += list(out.denominator.get("terms") or [])
        else:
            out.unavailable = "There is no program to run."
    except Exception as e:  # noqa: BLE001 - a preview reports rather than 500s
        logger.warning("metric preview failed: %s", e)
        out.unavailable = str(e)

    out.formatted = _format(out.value, code.unit, code.decimals)
    out.data_version = _data_version(code.datasets)
    return out


def _default_period(code: MetricCode) -> str:
    from backend.data_access import get_data_source

    for dataset in code.datasets:
        periods = get_data_source().periods(dataset)
        if periods:
            return periods[-1]
    raise ValueError(
        "CreditProbe could not work out which period to preview this metric "
        "for, because none of the datasets it reads has any.")


def _data_version(datasets: list[str]) -> str:
    from backend.data_access.catalog import get_catalog

    parts: list[str] = []
    for dataset in datasets:
        try:
            parts.append(f"{dataset}@{get_catalog().dataset(dataset).version}")
        except Exception:  # noqa: BLE001
            parts.append(f"{dataset}@unknown")
    return ", ".join(parts)


# ---------------------------------------------------------------------------
# Lock
# ---------------------------------------------------------------------------


def lock(code: MetricCode, *, period: str = "", user_id: int | None = None,
         readable: Any = None, owner: str = "", shared: bool = True,
         approved_checksum: str = "", require_preview: bool = True
         ) -> dict[str, Any]:
    """§13. Persist the metric, with everything that was approved.

    Refuses without a preview by default. §9's own rule: "a metric nobody has
    seen a number for is a metric nobody has checked." The flag exists for the
    test suite and for a caller that has previewed through another route, not
    as a way past the rule.
    """
    from backend.metrics import service as metrics
    from backend.metrics.formula import Formula

    _require_approved(code, approved_checksum)
    if require_preview and code.stage != STAGE_PREVIEWED:
        raise ApprovalRequired(
            "This metric has not been previewed. A metric nobody has seen a "
            "number for is a metric nobody has checked.")

    code, verdict = codegen.revalidate(code, period=period, readable=readable)
    if not verdict.ok:
        return {"locked": False, "code": code.to_dict(),
                "validation": verdict.to_dict(),
                "why": "CreditProbe re-checked this code before storing it "
                       "and will not store it."}

    code.stage = STAGE_LOCKED
    presentation = {
        "formula_text": code.interpreted_formula,
        "numerator_text": (code.composite.numerator.label
                           if code.composite and code.composite.numerator
                           else ""),
        "denominator_text": (code.composite.denominator.label
                             if code.composite and code.composite.denominator
                             else ""),
        "period_rule": "as_selected",
        "transformation": " ".join(code.plain_english),
        "decimals": code.decimals,
        "visuals": ["kpi"],
        "not_this": "",
        "aliases": [],
    }
    metric = metrics.create(
        name=code.name,
        formula=code.formula or Formula(),
        definition=code.why or code.interpreted_formula,
        unit=code.unit,
        domain=", ".join(domains.LABELS.get(d, d) for d in code.domains),
        portfolio="",
        presentation=presentation,
        user_id=user_id, owner=owner, shared=shared,
        code=code.to_dict())
    # A metric that has been previewed against real data calculates. Saying so
    # is not the same as saying it is VERIFIED — that still needs somebody to
    # compare it with their own number, which is what the verification
    # workspace is for and what `service.verify` records.
    try:
        metrics.set_status(metric.metric_id, "CALCULATION_READY",
                           user_id=user_id)
    except Exception:  # noqa: BLE001 - the metric is stored either way
        logger.warning("could not set status on %s", metric.metric_id,
                       exc_info=True)
    return {"locked": True, "metric_id": metric.metric_id,
            "metric": metric.panel(), "code": code.to_dict(),
            "validation": verdict.to_dict()}


__all__ = [
    "FLOW_VERSION", "ApprovalRequired", "ApprovalStale", "Preview",
    "approve", "divergence", "draft", "lock", "preview", "read", "revise",
]
