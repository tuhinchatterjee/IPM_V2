"""
The Cockpit V2 answer. Brief §7.3, §7.4.

Every requested output is answered, in the order it was asked. A subquestion
that cannot be answered is reported as unanswered rather than dropped, because
silently answering half a question is the specific failure the base build had:
"Give me an ECL decomposition and explain the impact of PD" came back as a
clarification about horizons.

Answer standard, from §7.4
--------------------------
Lead with substance, not a preface. Give the amounts, the movement, the top
contributors and the interpretation. Explain improvement as readily as
deterioration — a book that grew is not thereby a book that got worse. Then one
compact table or chart that earns its place: a waterfall for a reconciled
bridge, nothing at all for a definition.

Where the prose comes from
--------------------------
`prose_source` records it on every answer: `analyst` when a grounded model
wrote it, `deterministic_v2` when this module composed it from the governed
observations, `interpretation` or `deterministic` for the base paths. The base
product had no such field and a reader could not tell which path wrote the
sentence they were reading.

This module composes from OBSERVATIONS, never from stored narrative. There is
no lookup of a written answer anywhere in it: change a PD input, regenerate,
and the sentences change because the numbers they are built from changed.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Sequence

import pandas as pd

from backend.cockpit_v2 import (ANSWER_VERSION, DATA_VERSION, MODEL_VERSION,
                                POLICY_VERSION)
from backend.cockpit_v2 import attribution as attr
from backend.cockpit_v2 import calendar as cal
from backend.cockpit_v2 import ecl as ecl_mod
from backend.cockpit_v2 import evidence as ev
from backend.cockpit_v2 import policy
from backend.cockpit_v2 import reader
from backend.cockpit_v2 import schema as schema_mod
from backend.cockpit_v2 import scope as scope_mod
from backend.cockpit_v2 import understand as understand_mod
from backend.cockpit_v2.generate import AMOUNT_UNIT, REPORTING_CURRENCY

logger = logging.getLogger(__name__)

PROSE_ANALYST = "analyst"
PROSE_DETERMINISTIC_V2 = "deterministic_v2"
PROSE_INTERPRETATION = "interpretation"
PROSE_DETERMINISTIC = "deterministic"

SYNTHETIC_BANNER = (
    "Synthetic demonstration data. No figure here describes a real borrower.")


def money(value: float | None, *, unit: str = AMOUNT_UNIT,
          places: int = 2) -> str:
    if value is None:
        return "not available"
    return f"{value:,.{places}f} {unit}"


def pct(value: float | None, places: int | None = None) -> str:
    """A percentage, with enough precision that it is still the same number.

    One decimal place turned a coverage of 0.4598% into "0.5%", which is a
    different figure from the one in the evidence and was rejected by the claim
    validator — correctly. Small percentages therefore get two decimals.
    """
    if value is None:
        return "not available"
    if places is None:
        places = 2 if abs(value) < 10 else 1
    return f"{value:.{places}f}%"


def prob(value: float | None, places: int = 2) -> str:
    if value is None:
        return "not available"
    return f"{value * 100:.{places}f}%"


@dataclass
class Section:
    """One requested output, answered."""

    output: str
    heading: str
    paragraphs: list[str] = field(default_factory=list)
    findings: list[str] = field(default_factory=list)
    table: dict[str, Any] | None = None
    chart: dict[str, Any] | None = None
    limitations: list[str] = field(default_factory=list)
    answered: bool = True
    unanswered_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"output": self.output, "heading": self.heading,
                "paragraphs": list(self.paragraphs),
                "findings": list(self.findings), "table": self.table,
                "chart": self.chart, "limitations": list(self.limitations),
                "answered": self.answered,
                "unanswered_reason": self.unanswered_reason}


@dataclass
class Answer:
    """The whole Cockpit V2 response."""

    question: str
    request: understand_mod.Request
    sections: list[Section] = field(default_factory=list)
    ledger: ev.Ledger = field(default_factory=ev.Ledger)
    contracts: list[ev.ContractResult] = field(default_factory=list)
    scope_note: str = ""
    prose_source: str = PROSE_DETERMINISTIC_V2
    fallback_reason: str = ""
    clarification: dict[str, Any] | None = None
    validation: ev.Validation | None = None
    trace: dict[str, Any] = field(default_factory=dict)
    recommendations: list[dict[str, Any]] = field(default_factory=list)

    @property
    def direct_answer(self) -> str:
        for section in self.sections:
            if section.answered and section.paragraphs:
                return section.paragraphs[0]
        return ""

    @property
    def narrative(self) -> str:
        out: list[str] = []
        for section in self.sections:
            out.extend(section.paragraphs)
        return "\n\n".join(out)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": ANSWER_VERSION,
            "question": self.question,
            "understood": self.request.to_dict(),
            "prose_source": self.prose_source,
            "fallback_reason": self.fallback_reason,
            "direct_answer": self.direct_answer,
            "narrative": self.narrative,
            "sections": [s.to_dict() for s in self.sections],
            "findings": [f for s in self.sections for f in s.findings],
            "limitations": [l for s in self.sections for l in s.limitations],
            "unanswered": [{"output": s.output, "reason": s.unanswered_reason}
                           for s in self.sections if not s.answered],
            "tables": [s.table for s in self.sections if s.table],
            "charts": [s.chart for s in self.sections if s.chart],
            "clarification": self.clarification,
            "recommendations": list(self.recommendations),
            "evidence": self.ledger.to_dict(),
            "coverage": ev.coverage_report(self.ledger, self.contracts),
            "validation": (self.validation.to_dict() if self.validation
                           else None),
            "scope": self.scope_note,
            "trace": self.trace,
            "synthetic": SYNTHETIC_BANNER,
        }


# ------------------------------------------------------------------ helpers


def _policy_observation(ledger: ev.Ledger, principal: Any,
                        quarter: str) -> None:
    """The governed constants and population counts the prose may quote.

    Policy thresholds — three notches, thirty days past due, ninety days to
    default, the staleness windows — and the size of the population in scope
    are FACTS with a source, and an answer that states them is not making an
    unsupported claim. Before this observation existed the claim validator
    rejected forty evaluation cases for quoting the SICR notch threshold, which
    is exactly the kind of correct sentence a grounding check must not delete.
    """
    try:
        snap = reader.snapshot(quarter, principal)
        population = {
            "facilities_in_scope": float(len(snap)),
            "borrowers_in_scope": float(snap["borrower_id"].nunique()),
            "groups_in_scope": float(snap["group_id"].nunique()),
            "sectors_in_scope": float(snap["sector"].nunique()),
        }
    except Exception:  # noqa: BLE001 - the policy block still stands
        population = {}

    ledger.add(ev.Observation(
        observation_id="obs-policy-1", tool="get_policy_definition",
        scope="the governed demonstration policy set", unit="policy units",
        reporting_date=cal.iso(quarter), policy_version=POLICY_VERSION,
        model_version=MODEL_VERSION, data_version=DATA_VERSION,
        figures={
            "sicr_notch_threshold": float(policy.SICR_NOTCH_THRESHOLD),
            "sicr_relative_pd_increase": float(policy.SICR_RELATIVE_PD_INCREASE),
            "sicr_absolute_pd_floor_pct": policy.SICR_ABSOLUTE_PD_FLOOR * 100.0,
            "sicr_dpd_backstop": float(policy.SICR_DPD_BACKSTOP),
            "default_dpd": float(policy.DEFAULT_DPD),
            "covenant_cure_days": float(policy.COVENANT_CURE_DAYS),
            "stale_valuation_days": float(policy.STALE_VALUATION_DAYS),
            "stale_statement_days": float(policy.STALE_STATEMENT_DAYS),
            "stale_rating_days": float(policy.STALE_RATING_DAYS),
            "macro_predictor_count": float(len(policy.MACRO_PREDICTORS)),
            "scenario_count": float(len(policy.SCENARIOS)),
            "impaired_recovery_lag_years": policy.IMPAIRED_RECOVERY_LAG_YEARS,
            **{f"scenario_weight_{k}": v
               for k, v in policy.SCENARIO_WEIGHT.items()},
            **population},
        rows=[{"policy": "SICR notch threshold",
               "value": policy.SICR_NOTCH_THRESHOLD, "unit": "notches"},
              {"policy": "Past-due backstop",
               "value": policy.SICR_DPD_BACKSTOP, "unit": "days"},
              {"policy": "Default definition",
               "value": policy.DEFAULT_DPD, "unit": "days"}],
        rows_total=3,
        limitations=[policy.SYNTHETIC_ASSUMPTION]))


def _apply_filters(frame: pd.DataFrame, filters: dict[str, Any]) -> pd.DataFrame:
    out = frame
    for key in ("sector", "segment", "geography", "product", "stage",
                "borrower_id", "group_id"):
        if key in filters and key in out.columns:
            out = out[out[key] == filters[key]]
    if filters.get("exclude_new") and "is_new_this_period" in out.columns:
        out = out[~out["is_new_this_period"].astype(bool)]
    return out


def _scope_text(request: understand_mod.Request, closing: str,
                rows: int, opening: str = "") -> str:
    parts = [f"{rows:,} facilities"]
    if request.filters:
        described = ", ".join(
            f"{k.replace('_', ' ')} = {v}" for k, v in request.filters.items()
            if k not in ("exclude_new", "continuing_only"))
        if described:
            parts.append(described)
        if request.filters.get("exclude_new"):
            parts.append("new facilities excluded")
    window = (f"{cal.display(opening)} to {cal.display(closing)}"
              if opening else f"as at {cal.display(closing)}")
    return f"{window} — {', '.join(parts)}. Amounts in {AMOUNT_UNIT}."


def _waterfall(found: attr.FactorDecomposition) -> dict[str, Any]:
    """A waterfall spec for a reconciled bridge. The one chart that earns it."""
    steps = [{"label": f"Opening ({found.opening_date})",
              "value": found.opening_ecl, "kind": "total"}]
    for factor in found.factors:
        if abs(factor.contribution) > 1e-9:
            steps.append({"label": factor.label,
                          "value": factor.contribution, "kind": "delta"})
    for line in found.structural:
        if abs(line.amount) > 1e-9:
            steps.append({"label": line.label, "value": line.amount,
                          "kind": "delta"})
    steps.append({"label": f"Closing ({found.closing_date})",
                  "value": found.closing_ecl, "kind": "total"})
    return {"type": "waterfall", "title": "Reported ECL bridge",
            "unit": found.unit, "steps": steps,
            "reconciled": found.reconciled, "residual": found.residual}


def _factor_table(found: attr.FactorDecomposition) -> dict[str, Any]:
    rows = [{"Component": f.label, "Contribution": round(f.contribution, 4),
             "Share of net change": (None if f.share_of_net_change is None
                                     else round(f.share_of_net_change, 2)),
             "Kind": "Parameter factor"}
            for f in found.factors]
    rows.extend({"Component": s.label, "Contribution": round(s.amount, 4),
                 "Share of net change": (
                     None if not found.shares_available or found.net_change == 0
                     else round(s.amount / found.net_change * 100.0, 2)),
                 "Kind": "Structural"}
                for s in found.structural)
    rows.sort(key=lambda r: abs(r["Contribution"]), reverse=True)
    return {"title": f"ECL bridge, {found.opening_date} to {found.closing_date}",
            "columns": ["Component", "Contribution", "Share of net change",
                        "Kind"],
            "rows": rows, "unit": found.unit,
            "footer": (f"Opening {found.opening_ecl:,.2f} + components "
                       f"{found.net_change:,.2f} = closing "
                       f"{found.closing_ecl:,.2f} {found.unit}. "
                       f"Residual {found.residual:.2e}.")}


# ---------------------------------------------------- the factor decomposition


def _decomposition_section(request: understand_mod.Request, principal: Any,
                           ledger: ev.Ledger, present: set[str],
                           ) -> tuple[Section, attr.FactorDecomposition | None,
                                      dict[str, Any]]:
    periods = reader.resolve_period_pair(
        to_period=request.to_period, from_period=request.from_period,
        principal=principal)
    if not periods["available"]:
        section = Section(
            understand_mod.ECL_FACTOR_DECOMPOSITION,
            "ECL movement", answered=False,
            unanswered_reason=periods["reason"])
        section.paragraphs.append(periods["reason"])
        return section, None, periods

    opening, closing = periods["opening"], periods["closing"]

    # The rebuilt measurements must reproduce the published ECL, or the bridge
    # would reconcile numbers the dataset does not contain.
    verification = reader.verify_reconstruction(closing, principal)
    opening_snap = _apply_filters(reader.snapshot(opening, principal),
                                  request.filters)
    closing_snap = _apply_filters(reader.snapshot(closing, principal),
                                  request.filters)
    wanted = sorted(set(opening_snap["facility_id"])
                    | set(closing_snap["facility_id"]))
    if request.filters.get("continuing_only"):
        wanted = sorted(set(opening_snap["facility_id"])
                        & set(closing_snap["facility_id"]))

    opening_m = reader.measurements_for(opening, principal, wanted)
    closing_m = reader.measurements_for(closing, principal, wanted)

    found = attr.decompose_ecl_factors(
        list(opening_m.values()), list(closing_m.values()),
        opening_date=cal.iso(opening), closing_date=cal.iso(closing),
        currency=REPORTING_CURRENCY, unit=AMOUNT_UNIT,
        top_facilities=max(request.top_n or 0, 10))

    scope_text = _scope_text(request, closing, len(closing_snap), opening)
    observation = ledger.add(ev.Observation(
        observation_id="obs-ecl-factors-1",
        tool="decompose_ecl_factors", scope=scope_text, unit=AMOUNT_UNIT,
        reporting_date=cal.iso(closing), comparison_date=cal.iso(opening),
        method=found.method, method_version=found.method_version,
        model_version=MODEL_VERSION, data_version=DATA_VERSION,
        policy_version=POLICY_VERSION, filters=dict(request.filters),
        coverage={"continuing": found.continuing_accounts,
                  "entered": found.entered_accounts,
                  "exited": found.exited_accounts,
                  "reconstruction_matches_published": verification["matches"],
                  "worst_reconstruction_gap": verification["worst_discrepancy"]},
        figures={"opening_ecl": found.opening_ecl,
                 "closing_ecl": found.closing_ecl,
                 "net_change": found.net_change,
                 "residual": found.residual,
                 "continuing_accounts": float(found.continuing_accounts),
                 "entered_accounts": float(found.entered_accounts),
                 "exited_accounts": float(found.exited_accounts),
                 **{f.factor: f.contribution for f in found.factors},
                 **{f"{f.factor}_share": f.share_of_net_change
                    for f in found.factors
                    if f.share_of_net_change is not None},
                 **{s.line: s.amount for s in found.structural}},
        entities=[str(r["facility_id"]) for r in found.by_facility]
                 + [str(r["borrower_id"]) for r in found.by_facility],
        rows=found.by_facility, rows_total=found.continuing_accounts,
        truncated=len(found.by_facility) < found.continuing_accounts,
        reconciled=found.reconciled, limitations=list(found.limitations),
        drill_down={"dataset": "cockpit_credit_history",
                    "facility_ids": [r["facility_id"]
                                     for r in found.by_facility]}))
    present.update({"opening_scope", "closing_scope", "measurement_basis",
                    "factor_method", "reconciliation", "pd_contribution",
                    "top_entities"})

    direction = "rose" if found.net_change > 0 else (
        "fell" if found.net_change < 0 else "was effectively unchanged")
    ranked = sorted(found.factors, key=lambda f: abs(f.contribution),
                    reverse=True)
    largest = ranked[0] if ranked else None
    increasing = [f for f in ranked if f.contribution > 0]
    decreasing = [f for f in ranked if f.contribution < 0]

    section = Section(understand_mod.ECL_FACTOR_DECOMPOSITION,
                      "ECL decomposition")
    section.paragraphs.append(
        f"Reported ECL {direction} from {money(found.opening_ecl)} at "
        f"{cal.display(opening)} to {money(found.closing_ecl)} at "
        f"{cal.display(closing)}, a movement of {money(found.net_change)}. "
        f"Decomposing that movement across the parameter groups of the "
        f"governed calculator, the largest single component is "
        f"{largest.label.lower()} at {money(largest.contribution)}"
        + (f", which this method allocates "
           f"{pct(largest.share_of_net_change)} of the net change"
           if largest and largest.share_of_net_change is not None else "")
        + f". The bridge reconciles: opening plus every component below equals "
          f"closing, with a residual of {found.residual:.2e} {AMOUNT_UNIT}.")

    if increasing and decreasing:
        section.paragraphs.append(
            "The net figure hides movement in both directions. Increasing the "
            "allowance: "
            + "; ".join(f"{f.label.lower()} {money(f.contribution)}"
                        for f in increasing[:3])
            + ". Reducing it: "
            + "; ".join(f"{f.label.lower()} {money(f.contribution)}"
                        for f in decreasing[:3])
            + ". Both are real and reporting only the net would conceal the "
              "improvement as well as the deterioration.")

    entry = next(s for s in found.structural if s.line == attr.LINE_ENTRY)
    exit_line = next(s for s in found.structural if s.line == attr.LINE_EXIT)
    overlay = next(s for s in found.structural if s.line == attr.LINE_OVERLAY)
    section.paragraphs.append(
        f"Outside the continuing book, {entry.accounts} facility/-ies entered "
        f"carrying {money(entry.amount)} of new allowance and "
        f"{exit_line.accounts} left, removing {money(abs(exit_line.amount))}. "
        f"An account leaving the book is a repayment, a write-off or a sale; "
        f"none of them means a loss was recovered. The separately identified "
        f"overlay moved {money(overlay.amount)} and is never folded into a "
        f"parameter.")

    section.findings = [
        f"{f.label}: {money(f.contribution)}"
        + (f" ({pct(f.share_of_net_change)} of the net change)"
           if f.share_of_net_change is not None else "")
        for f in ranked]
    section.table = _factor_table(found)
    if request.wants_chart is not False:
        section.chart = _waterfall(found)
    section.limitations = list(found.limitations)
    section.limitations.append(
        "These are contributions under the stated attribution method and "
        "model version. They quantify how the movement is allocated between "
        "parameter groups; they are not evidence of a real-world cause.")
    if not verification["matches"]:
        section.limitations.append(
            f"The measurements rebuilt from the published curves differ from "
            f"the published ECL by up to "
            f"{verification['worst_discrepancy']:.2e} {AMOUNT_UNIT}, so this "
            f"bridge should not be relied on until the dataset is rebuilt.")
    return section, found, periods


def _pd_section(request: understand_mod.Request, found: attr.FactorDecomposition,
                principal: Any, ledger: ev.Ledger, present: set[str],
                periods: dict[str, Any]) -> Section:
    section = Section(understand_mod.PD_IMPACT, "The impact of PD")
    pd_factor = found.factor(attr.FACTOR_PD)
    if pd_factor is None:
        section.answered = False
        section.unanswered_reason = ("the PD factor group was not evaluated in "
                                     "this decomposition")
        return section

    others = [f for f in found.factors if f.factor != attr.FACTOR_PD]
    bigger = [f for f in others if abs(f.contribution) > abs(pd_factor.contribution)]

    section.paragraphs.append(
        f"Under this decomposition the PD curves contributed "
        f"{money(pd_factor.contribution)} of the {money(found.net_change)} "
        f"movement"
        + (f", or {pct(pd_factor.share_of_net_change)} of it"
           if pd_factor.share_of_net_change is not None else "")
        + ". That figure is the exact Shapley allocation to the PD factor "
          "group: the opening and closing hazard curves are evaluated through "
          "the same governed ECL calculator in every combination with the "
          "other factor groups, and the allocation is averaged symmetrically "
          "across them, so no ordering was chosen and no interaction was left "
          "in an unexplained remainder.")

    if bigger:
        section.paragraphs.append(
            "PD is not the largest component here. "
            + "; ".join(f"{f.label.lower()} contributed "
                        f"{money(f.contribution)}" for f in bigger[:3])
            + ". Reporting the PD effect without saying what outweighed it "
              "would leave the wrong impression of what moved the allowance.")
    else:
        section.paragraphs.append(
            "PD is the largest single component of this movement. The "
            "remaining groups contributed "
            + "; ".join(f"{f.label.lower()} {money(f.contribution)}"
                        for f in others[:4]) + ".")

    # Which accounts carry the PD effect, from the per-facility allocation.
    carriers = sorted(
        (r for r in found.by_facility if not r.get("method_change")),
        key=lambda r: abs(r["factors"].get(attr.FACTOR_PD, 0.0)), reverse=True)
    top = carriers[:max(request.top_n or 5, 3)]
    if top:
        section.paragraphs.append(
            "The PD contribution is concentrated: "
            + "; ".join(
                f"{r['borrower_id']} facility {r['facility_id']} "
                f"{money(r['factors'].get(attr.FACTOR_PD, 0.0))}"
                for r in top)
            + ".")
        section.table = {
            "title": "PD contribution by facility",
            "columns": ["Borrower", "Facility", "PD contribution",
                        "Total movement"],
            "rows": [{"Borrower": r["borrower_id"],
                      "Facility": r["facility_id"],
                      "PD contribution": round(
                          r["factors"].get(attr.FACTOR_PD, 0.0), 4),
                      "Total movement": round(r["net_change"], 4)}
                     for r in top],
            "unit": AMOUNT_UNIT,
            "footer": (f"{len(carriers)} continuing facilities were "
                       f"decomposed; the {len(top)} largest PD contributions "
                       f"are shown.")}

    ledger.add(ev.Observation(
        observation_id="obs-pd-carriers-1",
        tool="decompose_ecl_factors", scope="PD factor group, by facility",
        unit=AMOUNT_UNIT, reporting_date=found.closing_date,
        comparison_date=found.opening_date, method=found.method,
        method_version=found.method_version, model_version=MODEL_VERSION,
        data_version=DATA_VERSION,
        figures={"pd_contribution": pd_factor.contribution},
        entities=[str(r["facility_id"]) for r in top]
                 + [str(r["borrower_id"]) for r in top],
        rows=[{"facility_id": r["facility_id"],
               "borrower_id": r["borrower_id"],
               "pd_contribution": r["factors"].get(attr.FACTOR_PD, 0.0)}
              for r in top],
        rows_total=len(carriers), truncated=len(top) < len(carriers),
        reconciled=found.reconciled))
    present.add("pd_contribution")

    section.findings = [
        f"PD contribution {money(pd_factor.contribution)}",
        f"Method: exact Shapley allocation across "
        f"{len(found.factors)} non-overlapping factor groups, evaluated "
        f"through the governed ECL calculator",
        f"Reconciliation residual {found.residual:.2e} {AMOUNT_UNIT}",
    ]
    section.limitations.append(
        "A PD attribution says how much of the movement this method allocates "
        "to the PD curves. It does not say why the PD curves moved, and it is "
        "a historical attribution rather than a forward sensitivity.")
    return section


# ------------------------------------------------------------ other outputs


def _composition_section(request: understand_mod.Request, principal: Any,
                         ledger: ev.Ledger, present: set[str]) -> Section:
    quarter = (request.to_period and cal.parse(request.to_period).label) \
        or reader.latest_quarter(principal)
    snap = _apply_filters(reader.snapshot(quarter, principal), request.filters)
    dimensions = [d for d in ("stage", "sector", request.dimension)
                  if d and d in snap.columns]
    dimensions = list(dict.fromkeys(dimensions))[:2] or ["sector"]

    section = Section(understand_mod.COMPOSITION,
                      "Current ECL composition")
    total = float(snap["reported_ecl"].sum())
    exposure = float(snap["exposure"].sum())
    section.paragraphs.append(
        f"As at {cal.display(quarter)} the reported allowance is "
        f"{money(total)} over {money(exposure)} of exposure across "
        f"{len(snap):,} facilities, a coverage of "
        f"{pct(total / exposure * 100 if exposure else 0)}. This is the "
        f"position at that date, not a movement: nothing below compares it "
        f"with another quarter.")

    rows: list[dict[str, Any]] = []
    for dimension in dimensions:
        grouped = snap.groupby(dimension).agg(
            ecl=("reported_ecl", "sum"), exposure=("exposure", "sum"),
            facilities=("facility_id", "count")).reset_index()
        grouped = grouped.sort_values("ecl", ascending=False)
        for _, row in grouped.iterrows():
            rows.append({
                "Dimension": dimension.replace("_", " ").title(),
                "Member": str(row[dimension]),
                "Reported ECL": round(float(row["ecl"]), 4),
                "Exposure": round(float(row["exposure"]), 2),
                "Coverage %": round(float(row["ecl"]) / float(row["exposure"])
                                    * 100.0, 3) if row["exposure"] else None,
                "Facilities": int(row["facilities"])})
        top = grouped.iloc[0]
        section.findings.append(
            f"Largest by {dimension}: {top[dimension]} at "
            f"{money(float(top['ecl']))} "
            f"({pct(float(top['ecl']) / total * 100 if total else 0)} of the "
            f"allowance)")

    section.table = {"title": f"Reported ECL at {cal.display(quarter)}",
                     "columns": ["Dimension", "Member", "Reported ECL",
                                 "Exposure", "Coverage %", "Facilities"],
                     "rows": rows, "unit": AMOUNT_UNIT,
                     "footer": (f"Coverage is reported ECL over exposure for "
                                f"each member. It is a ratio of components, "
                                f"not the average of facility coverages.")}
    if request.wants_chart:
        section.chart = {"type": "bar", "title": "Reported ECL by sector",
                         "unit": AMOUNT_UNIT,
                         "series": [{"label": r["Member"],
                                     "value": r["Reported ECL"]}
                                    for r in rows
                                    if r["Dimension"] == "Sector"]}

    ledger.add(ev.Observation(
        observation_id="obs-composition-1", tool="aggregate_snapshot",
        scope=_scope_text(request, quarter, len(snap)), unit=AMOUNT_UNIT,
        reporting_date=cal.iso(quarter), data_version=DATA_VERSION,
        filters=dict(request.filters),
        figures={"reported_ecl": total, "exposure": exposure,
                 "coverage_pct": (total / exposure * 100) if exposure else 0.0,
                 "facilities": float(len(snap)),
                 **{f"member_ecl_{r['Member']}": r["Reported ECL"]
                    for r in rows},
                 **{f"member_share_{r['Member']}":
                    (r["Reported ECL"] / total * 100.0) if total else 0.0
                    for r in rows}},
        entities=sorted({str(r["Member"]) for r in rows}),
        rows=rows, rows_total=len(rows),
        coverage={"facilities": len(snap),
                  "dimensions": dimensions}))
    present.update({"reporting_date", "population", "measure_definition"})
    return section


def _scenario_section(request: understand_mod.Request, principal: Any,
                      ledger: ev.Ledger, present: set[str]) -> Section:
    quarter = (request.to_period and cal.parse(request.to_period).label) \
        or reader.latest_quarter(principal)
    snap = _apply_filters(reader.snapshot(quarter, principal), request.filters)

    section = Section(understand_mod.SCENARIO_COMPARISON,
                      "Scenario comparison")
    totals = {s: float(snap[f"ecl_{s}"].sum()) for s in policy.SCENARIO_IDS}
    weights = {s: float(snap[f"scenario_weight_{s}"].iloc[0]) if len(snap) else 0.0
               for s in policy.SCENARIO_IDS}
    weighted = float(snap["weighted_model_ecl"].sum())
    overlay = float(snap["overlay"].sum())
    reported = float(snap["reported_ecl"].sum())

    contributions = {s: weights[s] * totals[s] for s in policy.SCENARIO_IDS}
    dominant = max(contributions, key=lambda s: contributions[s])

    section.paragraphs.append(
        f"At {cal.display(quarter)} the three scenarios produce "
        + ", ".join(f"{s} {money(totals[s])}" for s in policy.SCENARIO_IDS)
        + f". Weighting them at "
        + ", ".join(f"{s} {weights[s]:.0%}" for s in policy.SCENARIO_IDS)
        + f" gives a modelled ECL of {money(weighted)}, and adding the "
          f"separately identified overlay of {money(overlay)} gives the "
          f"reported allowance of {money(reported)}.")
    section.paragraphs.append(
        f"The weighted result sits where it does because {dominant} carries "
        f"the largest weighted contribution at "
        f"{money(contributions[dominant])}"
        + (f" — the downturn scenario is only "
           f"{weights['downturn']:.0%} likely but its loss is "
           f"{totals['downturn'] / totals['base']:.2f} times the base case, so "
           f"it pulls the weighted figure well above the base scenario"
           if totals.get("base") and totals["downturn"] > totals["base"]
           else "") + ".")

    naive = float((snap["weighted_twelve_month_pd"] * snap["weighted_lgd"]
                   * snap["weighted_ead"]).sum())
    section.paragraphs.append(
        f"A weighted-parameter shortcut does not reproduce this. The "
        f"exposure-level product of weighted PD, weighted LGD and weighted "
        f"EAD comes to {money(naive)} against a modelled "
        f"{money(weighted)}: the expectation of a product is not the product "
        f"of expectations, and the gap of {money(weighted - naive)} is the "
        f"covariance between the parameters across scenarios.")

    section.table = {
        "title": f"Scenario ECL at {cal.display(quarter)}",
        "columns": ["Scenario", "Weight", "Scenario ECL",
                    "Weighted contribution"],
        "rows": [{"Scenario": s.title(), "Weight": weights[s],
                  "Scenario ECL": round(totals[s], 4),
                  "Weighted contribution": round(contributions[s], 4)}
                 for s in policy.SCENARIO_IDS]
        + [{"Scenario": "Weighted model ECL", "Weight": 1.0,
            "Scenario ECL": None, "Weighted contribution": round(weighted, 4)},
           {"Scenario": "Overlay", "Weight": None, "Scenario ECL": None,
            "Weighted contribution": round(overlay, 4)},
           {"Scenario": "Reported ECL", "Weight": None, "Scenario ECL": None,
            "Weighted contribution": round(reported, 4)}],
        "unit": AMOUNT_UNIT,
        "footer": "Weights sum to one. Reported ECL is the weighted model "
                  "result plus the separately identified overlay."}
    section.findings = [
        f"{s.title()} ECL {money(totals[s])} at weight {weights[s]:.0%}"
        for s in policy.SCENARIO_IDS] + [
        f"Weighted model ECL {money(weighted)}",
        f"Weighted PD x weighted LGD x weighted EAD gives {money(naive)}, "
        f"which is not the weighted ECL"]

    ledger.add(ev.Observation(
        observation_id="obs-scenarios-1", tool="scenario_comparison",
        scope=_scope_text(request, quarter, len(snap)), unit=AMOUNT_UNIT,
        reporting_date=cal.iso(quarter), model_version=MODEL_VERSION,
        data_version=DATA_VERSION, filters=dict(request.filters),
        figures={**{f"ecl_{s}": totals[s] for s in policy.SCENARIO_IDS},
                 **{f"weight_{s}": weights[s] for s in policy.SCENARIO_IDS},
                 **{f"contribution_{s}": contributions[s]
                    for s in policy.SCENARIO_IDS},
                 "weighted_model_ecl": weighted, "overlay": overlay,
                 "reported_ecl": reported, "naive_parameter_product": naive,
                 "gap": weighted - naive,
                 "downturn_multiple": (totals["downturn"] / totals["base"]
                                       if totals.get("base") else 0.0),
                 **{f"weight_pct_{s}": weights[s] * 100.0
                    for s in policy.SCENARIO_IDS}},
        rows=section.table["rows"], rows_total=len(section.table["rows"])))
    present.update({"scenario_ecls", "weights", "weighted_result",
                    "parameter_product_check"})
    return section


def _scope_section(request: understand_mod.Request, principal: Any,
                   ledger: ev.Ledger, present: set[str]) -> Section:
    """The question asked the Cockpit to read outside its domain. Brief §3.4."""
    digest = scope_mod.describe(principal)
    datasets = digest["scope"]["datasets"]
    section = Section(understand_mod.SCOPE_STATEMENT, "Read scope")
    section.paragraphs.append(
        f"The Cockpit reads its own certified demonstration domain and "
        f"nothing else. That is enforced in the backend, as the intersection "
        f"of this capability scope and your own dataset permissions, so a "
        f"request cannot widen it — not by naming another domain, not by a "
        f"flag in the request, and not by an instruction in a data field. "
        f"The {len(datasets)} dataset(s) readable here are "
        f"{', '.join(datasets[:6])}"
        f"{' and others in the same domain' if len(datasets) > 6 else ''}. "
        f"Anything held in Early Warning, Scorecards, Planner, Lenses, "
        f"Playbook or What-if stays in those features, which have their own "
        f"access policies that this branch does not change.")
    section.findings.append(
        f"Cockpit read scope: {len(datasets)} dataset(s) in {digest['domain']}")
    section.limitations.append(scope_mod.UNTRUSTED_NOTE)
    ledger.add(ev.Observation(
        observation_id="obs-scope-1", tool="describe_scope",
        scope=digest["domain"], unit="", reporting_date="",
        data_version=DATA_VERSION,
        figures={"datasets_in_scope": float(len(datasets))},
        entities=list(datasets),
        rows=[{"dataset": name} for name in datasets],
        rows_total=len(datasets)))
    return section


def _definition_section(request: understand_mod.Request,
                        ledger: ev.Ledger, present: set[str]) -> Section:
    label, text = understand_mod.definition(request.term)
    section = Section(understand_mod.DEFINITION, "Definition")
    if not text:
        section.answered = False
        section.unanswered_reason = (
            f"{request.term or 'that term'} is not in the Cockpit's governed "
            f"glossary. Known terms: "
            f"{', '.join(understand_mod.known_terms())}.")
        section.paragraphs.append(section.unanswered_reason)
        return section
    section.paragraphs.append(f"{label}. {text}")
    section.findings.append(f"{label} is defined in the Cockpit glossary")
    present.add("term")
    ledger.add(ev.Observation(
        observation_id="obs-definition-1", tool="get_definition",
        scope="glossary", unit="", reporting_date="",
        data_version=DATA_VERSION,
        entities=[label], rows=[{"term": label, "definition": text}],
        rows_total=1))
    # No chart, no investigation. Brief A10.46.
    return section


def _macro_section(request: understand_mod.Request, ledger: ev.Ledger,
                   present: set[str]) -> Section:
    sector = request.filters.get("sector", "")
    section = Section(understand_mod.MACRO_DEPENDENCY, "Macro dependencies")
    pd_links = policy.active_sensitivities(sector, "pd")
    lgd_links = policy.active_sensitivities(sector, "lgd")

    if sector:
        if not pd_links and not lgd_links:
            section.answered = False
            section.unanswered_reason = (
                f"No macroeconomic predictor is declared in the demo model for "
                f"{sector}.")
            section.paragraphs.append(section.unanswered_reason)
            return section
        used = {s.predictor for s in pd_links}
        unused = [p for p in policy.MACRO_PREDICTOR_IDS if p not in used]
        section.paragraphs.append(
            f"Of the ten macroeconomic predictors this demo carries, "
            f"{len(used)} enter the PD model for {sector}: "
            + "; ".join(f"{s.predictor.replace('_', ' ')} with coefficient "
                        f"{s.coefficient:+.2f} at a {s.lag_quarters}-quarter "
                        f"lag" for s in pd_links)
            + f". The remaining {len(unused)} — "
            + ", ".join(p.replace('_', ' ') for p in unused)
            + " — are carried in the dataset but have no declared "
              "sensitivity for this sector, so they do not affect its PD.")
        if lgd_links:
            section.paragraphs.append(
                f"Separately, "
                + "; ".join(f"{s.predictor.replace('_', ' ')} enters LGD with "
                            f"coefficient {s.coefficient:+.2f}"
                            for s in lgd_links)
                + ". That is a recovery dependency, not a default one: it "
                  "moves what the security is worth rather than how likely "
                  "the borrower is to fail, and the two must not be added "
                  "together as though they were separate effects on the same "
                  "quantity.")
    else:
        section.paragraphs.append(
            f"The demo carries {len(policy.MACRO_PREDICTORS)} macroeconomic "
            f"predictors and {len(policy.active_sensitivities())} declared "
            f"sensitivities across "
            f"{len({s.sector for s in policy.active_sensitivities()})} sectors. "
            f"This is a proposed demonstration set, not a statistically "
            f"validated selection, and not every predictor enters every model.")

    rows = [{"Sector": s.sector, "Predictor": s.predictor.replace("_", " "),
             "Target": s.target.upper(), "Coefficient": s.coefficient,
             "Lag (quarters)": s.lag_quarters, "Note": s.note}
            for s in (pd_links + lgd_links if sector
                      else policy.active_sensitivities())]
    section.table = {"title": "Declared macro sensitivities",
                     "columns": ["Sector", "Predictor", "Target",
                                 "Coefficient", "Lag (quarters)", "Note"],
                     "rows": rows, "unit": "log-odds per standard deviation",
                     "footer": (
                         "Coefficients act on the standardised, lagged "
                         "predictor in a bounded logistic transform of the "
                         "rating-linked PD. Every one is a synthetic "
                         "demonstration assumption.")}
    section.findings = [
        f"{len({s.predictor for s in pd_links})} predictors enter the PD model"
        + (f" for {sector}" if sector else ""),
        f"{len(lgd_links)} predictor(s) enter LGD rather than PD"]
    section.limitations.append(
        "A macro predictor's effect is already fully counted inside the PD "
        "contribution of a factor decomposition. It is a nested explanation "
        "of that factor, never an additional top-level contribution to be "
        "added alongside it.")

    ledger.add(ev.Observation(
        observation_id="obs-macro-1", tool="get_macro_dependencies",
        scope=sector or "all sectors", unit="log-odds per standard deviation",
        reporting_date="", model_version=policy.MACRO_MODEL_ID,
        policy_version=POLICY_VERSION, data_version=DATA_VERSION,
        figures={**{f"coefficient_{s.sector}_{s.predictor}_{s.target}":
                    s.coefficient for s in (pd_links + lgd_links)},
                 "predictors_total": float(len(policy.MACRO_PREDICTORS)),
                 "predictors_in_pd_model": float(
                     len({s.predictor for s in pd_links})),
                 "predictors_in_lgd_model": float(len(lgd_links)),
                 "predictors_not_in_model": float(
                     len(policy.MACRO_PREDICTOR_IDS)
                     - len({s.predictor for s in pd_links})),
                 "sensitivities_total": float(
                     len(policy.active_sensitivities())),
                 "sectors_with_sensitivities": float(
                     len({s.sector for s in policy.active_sensitivities()}))},
        entities=[s.predictor for s in (pd_links + lgd_links)],
        rows=rows, rows_total=len(rows)))
    present.update({"declared_sensitivities", "model_version"})
    return section


def _covenant_section(request: understand_mod.Request, principal: Any,
                      ledger: ev.Ledger, present: set[str]) -> Section:
    quarter = (request.to_period and cal.parse(request.to_period).label) \
        or reader.latest_quarter(principal)
    tests = reader.detail("cockpit_covenant_tests", quarter, principal)
    snap = _apply_filters(reader.snapshot(quarter, principal), request.filters)
    if request.filters:
        tests = tests[tests["borrower_id"].isin(set(snap["borrower_id"]))]

    section = Section(understand_mod.COVENANT_REVIEW, "Covenants")
    breached = tests[tests["breached"] == True]  # noqa: E712
    near = tests[(tests["near_breach"] == True) & (tests["breached"] != True)]  # noqa: E712
    untested = tests[tests["tested"] != True]  # noqa: E712
    covered = breached[breached["waiver_status"] == "VALID"]
    expiring = breached[breached["waiver_status"] == "EXPIRING"]
    uncovered = breached[breached["waiver_status"] == "NONE"]

    section.paragraphs.append(
        f"At {cal.display(quarter)} {len(breached)} covenant test(s) are "
        f"breached across {int(breached['borrower_id'].nunique())} "
        f"borrower(s), out of {len(tests)} tests on the book. "
        f"{len(covered)} are covered by a waiver valid beyond the reporting "
        f"date, {len(expiring)} by a waiver expiring within the next quarter, "
        f"and {len(uncovered)} are uncovered. A further {len(near)} test(s) "
        f"are inside their tolerance without having breached, and "
        f"{len(untested)} could not be tested because the observed value was "
        f"not available.")

    rows = []
    for _, row in breached.sort_values("headroom").head(20).iterrows():
        rows.append({
            "Borrower": row["borrower_id"],
            "Covenant": row["covenant_id"],
            "Test": row["contractual_formula"],
            "Operator": row["operator"],
            "Threshold": (None if pd.isna(row["threshold"])
                          else round(float(row["threshold"]), 3)),
            "Observed": (None if pd.isna(row["observed_value"])
                         else round(float(row["observed_value"]), 3)),
            "Headroom": (None if pd.isna(row["headroom"])
                         else round(float(row["headroom"]), 3)),
            "Waiver": row["waiver_status"],
            "Waiver valid to": row["waiver_valid_to"],
            "Materiality": row["materiality"]})
    if rows:
        worst = rows[0]
        section.paragraphs.append(
            f"The largest shortfall is {worst['Borrower']} on "
            f"{worst['Covenant']}: the test requires "
            f"{worst['Operator']} {worst['Threshold']} and the observed value "
            f"is {worst['Observed']}, a headroom of {worst['Headroom']} in the "
            f"metric's own units. Its waiver status is "
            f"{worst['Waiver'].lower()}.")
    section.table = {"title": f"Breached covenants at {cal.display(quarter)}",
                     "columns": ["Borrower", "Covenant", "Test", "Operator",
                                 "Threshold", "Observed", "Headroom", "Waiver",
                                 "Waiver valid to", "Materiality"],
                     "rows": rows, "unit": "metric units",
                     "footer": (f"{len(breached)} breached test(s); the "
                                f"{len(rows)} with the least headroom are "
                                f"shown. Headroom is in each metric's own "
                                f"units, not a common scale.")}
    section.findings = [
        f"{len(breached)} breached, {len(covered)} with a valid waiver, "
        f"{len(expiring)} with a waiver expiring within a quarter, "
        f"{len(uncovered)} uncovered",
        f"{len(near)} test(s) within tolerance but not breached",
        f"{len(untested)} test(s) could not be run for want of an observed "
        f"value"]
    if len(untested):
        section.limitations.append(
            f"{len(untested)} test(s) had no observed value at this date, "
            f"usually because no financial statement has become available. "
            f"They are reported as untested, not as passing.")
    section.limitations.append(
        "A waived breach remains a breach in the history. Waivers change what "
        "action is required, not whether the test was failed.")

    ledger.add(ev.Observation(
        observation_id="obs-covenants-1", tool="covenant_review",
        scope=_scope_text(request, quarter, len(snap)), unit="metric units",
        reporting_date=cal.iso(quarter), policy_version=POLICY_VERSION,
        data_version=DATA_VERSION, filters=dict(request.filters),
        figures={"breached": float(len(breached)),
                 "breached_borrowers": float(breached["borrower_id"].nunique()),
                 "with_valid_waiver": float(len(covered)),
                 "expiring_waiver": float(len(expiring)),
                 "uncovered": float(len(uncovered)),
                 "near_breach": float(len(near)),
                 "untested": float(len(untested)),
                 "tests": float(len(tests))},
        entities=sorted(set(breached["borrower_id"].astype(str))),
        rows=rows, rows_total=len(breached), truncated=len(rows) < len(breached),
        drill_down={"dataset": "cockpit_covenant_tests", "period": quarter}))
    present.update({"thresholds", "observed_values", "test_dates",
                    "waiver_validity"})
    return section


def _collateral_section(request: understand_mod.Request, principal: Any,
                        ledger: ev.Ledger, present: set[str]) -> Section:
    quarter = (request.to_period and cal.parse(request.to_period).label) \
        or reader.latest_quarter(principal)
    snap = _apply_filters(reader.snapshot(quarter, principal), request.filters)
    allocation = reader.detail("cockpit_collateral_allocation", quarter,
                               principal)
    assets = reader.detail("cockpit_collateral_assets", quarter, principal)

    section = Section(understand_mod.COLLATERAL_REVIEW, "Collateral")
    exposure = float(snap["exposure"].sum())
    secured = float(snap["secured_amount"].sum())
    unsecured = float(snap["unsecured_amount"].sum())
    stale = int(snap["collateral_stale_valuations"].sum())
    shared = allocation.groupby("collateral_id").size()
    shared_assets = int((shared > 1).sum())

    section.paragraphs.append(
        f"At {cal.display(quarter)} recognised security covers "
        f"{money(secured)} of {money(exposure)} of exposure, leaving "
        f"{money(unsecured)} unsecured — "
        f"{pct(unsecured / exposure * 100 if exposure else 0)} of the book. "
        f"Recognised value is the valuation after the policy haircut and "
        f"after allocation across the facilities that share an asset, so a "
        f"property securing three facilities is counted once and not three "
        f"times.")
    over = allocation.iloc[0:0]
    if shared_assets:
        totals = allocation.groupby("collateral_id").agg(
            allocated=("allocated_recognised_amount", "sum"),
            recognised=("asset_recognised_value", "first"))
        over = totals[totals["allocated"] > totals["recognised"] + 1e-6]
        section.paragraphs.append(
            f"{shared_assets} asset(s) secure more than one facility. Summing "
            f"the allocations of each shared asset and comparing with its "
            f"recognised value shows {len(over)} over-allocation(s), so the "
            f"cross-collateralisation reconciles.")
    if stale:
        section.paragraphs.append(
            f"{stale} facility/-ies rely on a valuation older than the "
            f"{policy.STALE_VALUATION_DAYS}-day policy threshold. A falling "
            f"recognised value on a stale valuation is an information problem "
            f"rather than evidence that the asset has lost value, and the two "
            f"should not be reported as the same finding.")

    rows = [{"Facility": r["facility_id"], "Borrower": r["borrower_id"],
             "Exposure": round(float(r["exposure"]), 2),
             "Recognised collateral": round(
                 float(r["collateral_recognised_allocated"]), 2),
             "Coverage": round(float(r["collateral_coverage_ratio"]), 4),
             "Unsecured": round(float(r["unsecured_amount"]), 2),
             "Weighted LGD": round(float(r["weighted_lgd"]), 4),
             "Oldest valuation (days)": int(
                 r["collateral_oldest_valuation_days"])}
            for _, r in snap.sort_values("unsecured_amount",
                                         ascending=False).head(20).iterrows()]
    section.table = {"title": f"Collateral coverage at {cal.display(quarter)}",
                     "columns": ["Facility", "Borrower", "Exposure",
                                 "Recognised collateral", "Coverage",
                                 "Unsecured", "Weighted LGD",
                                 "Oldest valuation (days)"],
                     "rows": rows, "unit": AMOUNT_UNIT,
                     "footer": (f"{len(snap)} facilities; the {len(rows)} with "
                                f"the largest unsecured amount are shown.")}
    section.findings = [
        f"Recognised security {money(secured)} against {money(exposure)} of "
        f"exposure",
        f"{money(unsecured)} unsecured",
        f"{shared_assets} asset(s) shared across facilities, allocations "
        f"reconciled",
        f"{stale} facility/-ies on a stale valuation"]
    section.limitations.append(
        "Legal status is recorded as a status. A recognised value is what the "
        "policy permits to be counted; it is not a prediction that the "
        "security will be realised at that amount.")

    ledger.add(ev.Observation(
        observation_id="obs-collateral-1", tool="collateral_review",
        scope=_scope_text(request, quarter, len(snap)), unit=AMOUNT_UNIT,
        reporting_date=cal.iso(quarter), policy_version=POLICY_VERSION,
        data_version=DATA_VERSION, filters=dict(request.filters),
        figures={"exposure": exposure, "secured": secured,
                 "unsecured": unsecured, "facilities": float(len(snap)),
                 "allocation_over_allocations": float(len(over))
                 if shared_assets else 0.0,
                 "unsecured_pct": (unsecured / exposure * 100) if exposure else 0.0,
                 "shared_assets": float(shared_assets),
                 "stale_valuations": float(stale),
                 "assets": float(len(assets))},
        entities=sorted(set(snap["facility_id"].astype(str))
                        | set(snap["borrower_id"].astype(str))),
        rows=rows, rows_total=len(snap), truncated=len(rows) < len(snap),
        drill_down={"dataset": "cockpit_collateral_allocation",
                    "period": quarter}))
    present.update({"recognised_value", "allocation", "coverage",
                    "valuation_age", "lgd_effect"})
    return section


def _rating_section(request: understand_mod.Request, principal: Any,
                    ledger: ev.Ledger, present: set[str]) -> Section:
    periods = reader.resolve_period_pair(
        to_period=request.to_period, from_period=request.from_period,
        principal=principal)
    quarter = periods.get("closing") or reader.latest_quarter(principal)
    snap = _apply_filters(reader.snapshot(quarter, principal), request.filters)

    section = Section(understand_mod.RATING_REVIEW,
                      "Ratings and financial fundamentals")
    movements = pd.DataFrame()
    if periods.get("available"):
        movements = reader.detail("cockpit_movements", quarter, principal)
        movements = movements[movements["facility_id"].isin(
            set(snap["facility_id"]))]

    downgrades = (movements[movements["rating_notch_change"] > 0]
                  if "rating_notch_change" in movements.columns
                  else pd.DataFrame())
    upgrades = (movements[movements["rating_notch_change"] < 0]
                if "rating_notch_change" in movements.columns
                else pd.DataFrame())

    if not downgrades.empty:
        merged = downgrades.merge(
            snap[["facility_id", "exposure", "rating_approved_grade",
                  "ratio_dscr", "ratio_net_debt_to_ebitda",
                  "ratio_interest_coverage", "borrower_name"]],
            on="facility_id", how="left").sort_values("exposure",
                                                      ascending=False)
        top = merged.head(max(request.top_n or 5, 5))
        section.paragraphs.append(
            f"{len(downgrades)} facility/-ies were downgraded between "
            f"{periods['opening_label']} and {periods['closing_label']}, "
            f"carrying {money(float(merged['exposure'].sum()))} of exposure, "
            f"against {len(upgrades)} upgraded. Ranked by exposure the "
            f"downgrades that matter most are "
            + "; ".join(
                f"{r['borrower_id']} ({money(float(r['exposure']))}, "
                f"{int(r['rating_notch_change'])} notch(es) to "
                f"{r['rating_approved_grade']})"
                for _, r in top.iterrows()) + ".")
        # Deduplicated to BORROWER grain before ranking. A borrower financial
        # repeats across that borrower's facility rows, so ranking the rows
        # listed the same name twice — which is the exact fan-out the semantic
        # rules forbid, showing up in the prose rather than in a sum.
        weak = (snap[snap["ratio_dscr"].notna()]
                .drop_duplicates("borrower_id")
                .nsmallest(5, "ratio_dscr"))
        if not weak.empty:
            section.paragraphs.append(
                "On the financial inputs behind those grades, the weakest "
                "debt service coverage on the book is "
                + "; ".join(f"{r['borrower_id']} at "
                            f"{float(r['ratio_dscr']):.2f}x"
                            for _, r in weak.iterrows())
                + ". DSCR here is cash available for debt service over "
                  "scheduled principal plus cash interest, annualised from "
                  "the latest available statement, and it is ranked per "
                  "borrower rather than per facility so a borrower with two "
                  "facilities is named once.")
            ledger.add(ev.Observation(
                observation_id="obs-weakest-dscr-1", tool="rating_review",
                scope="weakest debt service coverage, per borrower",
                unit="times", reporting_date=cal.iso(quarter),
                data_version=DATA_VERSION,
                figures={f"dscr_{r['borrower_id']}": float(r["ratio_dscr"])
                         for _, r in weak.iterrows()},
                entities=sorted(set(weak["borrower_id"].astype(str))),
                rows=[{"borrower_id": r["borrower_id"],
                       "dscr": round(float(r["ratio_dscr"]), 4),
                       "exposure": round(float(r["exposure"]), 4)}
                      for _, r in weak.iterrows()],
                rows_total=int(snap["borrower_id"].nunique()),
                truncated=True))
    else:
        section.paragraphs.append(
            f"No rating downgrade is recorded in this scope"
            + (f" between {periods['opening_label']} and "
               f"{periods['closing_label']}" if periods.get("available") else "")
            + f". {len(snap)} facilities carry a grade at "
              f"{cal.display(quarter)}.")

    rows = [{"Borrower": r["borrower_id"],
             "Grade": r["rating_approved_grade"],
             "Model grade": r["rating_model_grade"],
             "Override": bool(r["rating_override"]),
             "Notches since origination": int(
                 r["rating_notches_since_origination"]),
             "Exposure": round(float(r["exposure"]), 2),
             "DSCR": (None if pd.isna(r["ratio_dscr"])
                      else round(float(r["ratio_dscr"]), 3)),
             "Net debt / EBITDA": (
                 None if pd.isna(r["ratio_net_debt_to_ebitda"])
                 else round(float(r["ratio_net_debt_to_ebitda"]), 3)),
             "Statement age (days)": (None if pd.isna(r["statement_age_days"])
                                      else int(r["statement_age_days"])),
             "Stale statement": bool(r["statement_is_stale"])}
            for _, r in snap.sort_values("exposure",
                                         ascending=False).head(20).iterrows()]
    section.table = {"title": f"Ratings at {cal.display(quarter)}",
                     "columns": ["Borrower", "Grade", "Model grade",
                                 "Override", "Notches since origination",
                                 "Exposure", "DSCR", "Net debt / EBITDA",
                                 "Statement age (days)", "Stale statement"],
                     "rows": rows, "unit": AMOUNT_UNIT,
                     "footer": (
                         "Grade is a label on the demo master scale and is "
                         "never averaged; notch movements are arithmetic on "
                         "the ordinal rank. A null ratio means the "
                         "denominator was zero or negative, or no statement "
                         "was available — not a ratio of nought.")}
    overrides = int(snap["rating_override"].sum())
    stale_statements = int(snap["statement_is_stale"].sum())
    missing = int((~snap["statement_available"].astype(bool)).sum())
    section.findings = [
        f"{len(downgrades)} downgrade(s), {len(upgrades)} upgrade(s)",
        f"{overrides} approved grade(s) differ from the model grade",
        f"{stale_statements} borrower(s) on a statement older than the "
        f"{policy.STALE_STATEMENT_DAYS}-day threshold",
        f"{missing} facility/-ies have no available statement at all"]
    if missing:
        section.limitations.append(
            f"{missing} facility/-ies have no statement available at this "
            f"date, so their ratios are not available and their grade uses "
            f"the stated policy fallback rather than the model.")

    if not downgrades.empty:
        merged_rows = downgrades.merge(
            snap[["facility_id", "exposure", "rating_approved_grade",
                  "borrower_id"]], on="facility_id", how="left",
            suffixes=("", "_snap"))
        ledger.add(ev.Observation(
            observation_id="obs-rating-movements-1", tool="rating_review",
            scope="rating movements between the two periods", unit=AMOUNT_UNIT,
            reporting_date=cal.iso(quarter),
            comparison_date=(cal.iso(periods["opening"])
                             if periods.get("available") else ""),
            data_version=DATA_VERSION,
            figures={f"downgrade_exposure_{r['facility_id']}":
                     float(r["exposure"]) for _, r in merged_rows.iterrows()
                     if pd.notna(r["exposure"])},
            entities=sorted(set(merged_rows["borrower_id"].astype(str))
                            | set(merged_rows["facility_id"].astype(str))),
            rows=[{"facility_id": r["facility_id"],
                   "borrower_id": r["borrower_id"],
                   "exposure": (None if pd.isna(r["exposure"])
                                else round(float(r["exposure"]), 4)),
                   "notch_change": int(r["rating_notch_change"]),
                   "grade": r["rating_approved_grade"]}
                  for _, r in merged_rows.iterrows()],
            rows_total=len(merged_rows)))

    ledger.add(ev.Observation(
        observation_id="obs-ratings-1", tool="rating_review",
        scope=_scope_text(request, quarter, len(snap)), unit=AMOUNT_UNIT,
        reporting_date=cal.iso(quarter), policy_version=POLICY_VERSION,
        model_version=policy.RATING_MODEL_VERSION, data_version=DATA_VERSION,
        filters=dict(request.filters),
        figures={"downgrades": float(len(downgrades)),
                 "upgrades": float(len(upgrades)),
                 "downgraded_exposure": (
                     float(downgrades.merge(
                         snap[["facility_id", "exposure"]], on="facility_id",
                         how="left")["exposure"].sum())
                     if not downgrades.empty else 0.0),
                 "overrides": float(overrides),
                 "stale_statements": float(stale_statements),
                 "missing_statements": float(missing),
                 "exposure": float(snap["exposure"].sum())},
        entities=sorted(set(snap["borrower_id"].astype(str))),
        rows=rows, rows_total=len(snap), truncated=len(rows) < len(snap),
        drill_down={"dataset": "cockpit_borrower_financials",
                    "period": quarter}))
    present.update({"grades", "exposure", "model_inputs", "ratio_detail",
                    "override"})
    return section


def _stage_section(request: understand_mod.Request, principal: Any,
                   ledger: ev.Ledger, present: set[str]) -> Section:
    periods = reader.resolve_period_pair(
        to_period=request.to_period, from_period=request.from_period,
        principal=principal)
    quarter = periods.get("closing") or reader.latest_quarter(principal)
    snap = _apply_filters(reader.snapshot(quarter, principal), request.filters)

    section = Section(understand_mod.STAGE_REVIEW, "Staging")
    counts = snap["stage"].value_counts().to_dict()
    section.paragraphs.append(
        f"At {cal.display(quarter)} the book stands at "
        + ", ".join(f"{int(counts.get(s, 0))} facilities in Stage {s}"
                    for s in (1, 2, 3))
        + f". Staging follows the stated demo SICR policy: Stage 2 requires "
          f"{policy.SICR_NOTCH_THRESHOLD} or more notches of downgrade since "
          f"origination, a lifetime PD at least "
          f"{policy.SICR_RELATIVE_PD_INCREASE:.0f} times its origination level "
          f"above a {policy.SICR_ABSOLUTE_PD_FLOOR:.0%} floor, or "
          f"{policy.SICR_DPD_BACKSTOP} days past due as a backstop. One "
          f"downgrade on its own does not stage an account.")

    transitions = pd.DataFrame()
    if periods.get("available"):
        movements = reader.detail("cockpit_movements", quarter, principal)
        movements = movements[movements["facility_id"].isin(
            set(snap["facility_id"]))]
        transitions = movements[movements["stage_transition"].notna()
                                & (movements["stage_now"]
                                   != movements["stage_prior"])]
    if not transitions.empty:
        merged = transitions.merge(
            snap[["facility_id", "exposure", "sicr_reason", "stage_trigger",
                  "days_past_due", "rating_notches_since_origination"]],
            on="facility_id", how="left")
        section.paragraphs.append(
            f"{len(transitions)} facility/-ies changed stage since "
            f"{periods['opening_label']}: "
            + "; ".join(f"{r['facility_id']} {r['stage_transition']} "
                        f"({r['stage_trigger']})"
                        for _, r in merged.head(8).iterrows())
            + ". Each carries the rule that fired, so a migration can be "
              "checked against the policy rather than taken on trust.")
        rows = [{"Facility": r["facility_id"], "Borrower": r["borrower_id"],
                 "Transition": r["stage_transition"],
                 "Trigger": r["stage_trigger"],
                 "Reason": r["sicr_reason"],
                 "Days past due": int(r["days_past_due"]),
                 "Notches since origination": int(
                     r["rating_notches_since_origination"]),
                 "Exposure": round(float(r["exposure"]), 2)}
                for _, r in merged.iterrows()]
    else:
        rows = [{"Facility": r["facility_id"], "Borrower": r["borrower_id"],
                 "Transition": "unchanged", "Trigger": r["stage_trigger"],
                 "Reason": r["sicr_reason"],
                 "Days past due": int(r["days_past_due"]),
                 "Notches since origination": int(
                     r["rating_notches_since_origination"]),
                 "Exposure": round(float(r["exposure"]), 2)}
                for _, r in snap[snap["stage"] > 1].head(20).iterrows()]

    one_notch = snap[(snap["rating_notches_since_origination"] == 1)
                     & (snap["days_past_due"] < policy.SICR_DPD_BACKSTOP)]
    if len(one_notch):
        staged = int((one_notch["stage"] == 2).sum())
        section.paragraphs.append(
            f"Checking the rule against the actual book: {len(one_notch)} "
            f"facility/-ies are exactly one notch below origination and inside "
            f"the past-due backstop, and {staged} of them are in Stage 2. A "
            f"single downgrade therefore does not imply Stage 2 here, which "
            f"is what the configured policy says.")

    section.table = {"title": f"Staging at {cal.display(quarter)}",
                     "columns": ["Facility", "Borrower", "Transition",
                                 "Trigger", "Reason", "Days past due",
                                 "Notches since origination", "Exposure"],
                     "rows": rows, "unit": AMOUNT_UNIT,
                     "footer": (f"Stage 3 is measured by the credit-impaired "
                                f"cash-shortfall method, not by the "
                                f"performing formula. NPL and Stage 3 "
                                f"coincide here as a stated demo policy.")}
    section.findings = [f"Stage {s}: {int(counts.get(s, 0))} facilities"
                        for s in (1, 2, 3)]
    section.findings.append(f"{len(transitions)} stage change(s) in the period")

    ledger.add(ev.Observation(
        observation_id="obs-staging-1", tool="stage_review",
        scope=_scope_text(request, quarter, len(snap)), unit="count",
        reporting_date=cal.iso(quarter), policy_version=POLICY_VERSION,
        data_version=DATA_VERSION, filters=dict(request.filters),
        figures={f"stage_{s}": float(counts.get(s, 0)) for s in (1, 2, 3)}
                | {"transitions": float(len(transitions)),
                   "one_notch_accounts": float(len(one_notch)),
                   "one_notch_in_stage_2": float(
                       (one_notch["stage"] == 2).sum()) if len(one_notch) else 0.0,
                   "facilities": float(len(snap))},
        entities=sorted(set(snap["facility_id"].astype(str))),
        rows=rows, rows_total=len(snap), truncated=len(rows) < len(snap)))
    present.update({"population", "reporting_date"})
    return section


def _concentration_section(request: understand_mod.Request, principal: Any,
                           ledger: ev.Ledger, present: set[str]) -> Section:
    quarter = (request.to_period and cal.parse(request.to_period).label) \
        or reader.latest_quarter(principal)
    snap = _apply_filters(reader.snapshot(quarter, principal), request.filters)

    section = Section(understand_mod.CONCENTRATION, "Concentration")
    total = float(snap["exposure"].sum())
    by_group = snap.groupby(["group_id", "group_name"]).agg(
        exposure=("exposure", "sum"), ecl=("reported_ecl", "sum"),
        borrowers=("borrower_id", "nunique"),
        facilities=("facility_id", "count")).reset_index()
    by_group = by_group.sort_values("exposure", ascending=False)
    top_group = by_group.iloc[0] if len(by_group) else None
    top5 = float(by_group.head(5)["exposure"].sum())

    section.paragraphs.append(
        f"At {cal.display(quarter)} the book is {money(total)} across "
        f"{int(snap['borrower_id'].nunique())} borrowers in "
        f"{len(by_group)} connected groups. The largest group is "
        f"{top_group['group_name']} at {money(float(top_group['exposure']))}, "
        f"{pct(float(top_group['exposure']) / total * 100 if total else 0)} of "
        f"the book across {int(top_group['borrowers'])} borrower(s) and "
        f"{int(top_group['facilities'])} facilities. The top five groups hold "
        f"{pct(top5 / total * 100 if total else 0)}. Group exposure is the sum "
        f"of facility rows once — a borrower with three facilities is one "
        f"borrower and is not counted three times."
        if top_group is not None else
        f"No exposure is in scope at {cal.display(quarter)}.")

    by_sector = snap.groupby("sector").agg(
        exposure=("exposure", "sum"), ecl=("reported_ecl", "sum"),
        facilities=("facility_id", "count")).reset_index()
    by_sector = by_sector.sort_values("exposure", ascending=False)
    section.paragraphs.append(
        "By sector the concentration is "
        + "; ".join(f"{r['sector']} {pct(float(r['exposure']) / total * 100)}"
                    for _, r in by_sector.head(4).iterrows())
        + ". Concentration is a share of exposure, and a large share is not "
          "by itself a quality problem: the coverage column shows whether the "
          "concentrated exposure is also the more heavily provisioned.")

    rows = [{"Group": r["group_name"], "Group ID": r["group_id"],
             "Exposure": round(float(r["exposure"]), 2),
             "Share %": round(float(r["exposure"]) / total * 100, 3)
             if total else None,
             "Reported ECL": round(float(r["ecl"]), 4),
             "Coverage %": round(float(r["ecl"]) / float(r["exposure"]) * 100,
                                 3) if r["exposure"] else None,
             "Borrowers": int(r["borrowers"]),
             "Facilities": int(r["facilities"])}
            for _, r in by_group.head(15).iterrows()]
    section.table = {"title": f"Connected groups at {cal.display(quarter)}",
                     "columns": ["Group", "Group ID", "Exposure", "Share %",
                                 "Reported ECL", "Coverage %", "Borrowers",
                                 "Facilities"],
                     "rows": rows, "unit": AMOUNT_UNIT,
                     "footer": (f"{len(by_group)} groups; the {len(rows)} "
                                f"largest by exposure are shown. Shares are "
                                f"of {money(total)} total exposure.")}
    section.findings = [
        f"Largest group {top_group['group_name']} at "
        f"{pct(float(top_group['exposure']) / total * 100)} of exposure"
        if top_group is not None else "No exposure in scope",
        f"Top five groups hold {pct(top5 / total * 100 if total else 0)}"]

    ledger.add(ev.Observation(
        observation_id="obs-concentration-1", tool="concentration",
        scope=_scope_text(request, quarter, len(snap)), unit=AMOUNT_UNIT,
        reporting_date=cal.iso(quarter), data_version=DATA_VERSION,
        filters=dict(request.filters),
        figures={"total_exposure": total, "top_five_share":
                 (top5 / total * 100) if total else 0.0,
                 "largest_group_share_pct": (
                     float(top_group["exposure"]) / total * 100.0
                     if top_group is not None and total else 0.0),
                 "borrowers": float(snap["borrower_id"].nunique()),
                 "facilities": float(len(snap)),
                 **{f"sector_share_{r['sector']}":
                    float(r["exposure"]) / total * 100.0 if total else 0.0
                    for _, r in by_sector.iterrows()},
                 "largest_group_exposure": float(top_group["exposure"])
                 if top_group is not None else 0.0,
                 "groups": float(len(by_group))},
        entities=sorted(set(by_group["group_id"].astype(str))),
        rows=rows, rows_total=len(by_group),
        truncated=len(rows) < len(by_group),
        coverage={"denominator": "total exposure in scope",
                  "borrowers": int(snap["borrower_id"].nunique())}))
    present.update({"population", "reporting_date"})
    return section


def _history_section(request: understand_mod.Request, principal: Any,
                     ledger: ev.Ledger, present: set[str]) -> Section:
    quarters = reader.published_quarters(principal)
    frame = _apply_filters(reader.history(principal), request.filters)
    measure = request.measure or "reported_ecl"

    points = []
    for quarter in quarters:
        rows = frame[frame["period"] == quarter]
        points.append((cal.display(quarter),
                       float(rows[measure].sum()) if len(rows) else None))
    found = attr.metric_history(points, measure_name=measure,
                               unit=AMOUNT_UNIT)

    section = Section(understand_mod.METRIC_HISTORY, "History")
    described = schema_mod.MEASURE_BY_NAME.get(measure, {}).get("label", measure)
    section.paragraphs.append(
        f"{described} over the {found['observations']} published quarter(s): "
        + "; ".join(f"{p['period']} {money(p['value'])}"
                    for p in found["points"] if p["value"] is not None)
        + (f". The latest reading of {money(found['latest'])} is "
           f"{money(found['change'])} against the prior quarter."
           if found["change"] is not None else "."))
    if found["z_score"] is not None:
        section.paragraphs.append(
            f"Against the {found['comparator_periods']} preceding "
            f"observations the latest value sits {found['z_score']:.2f} "
            f"standard deviations from their mean of "
            f"{money(found['mean'])}. That is a descriptive comparison over a "
            f"very short series, not a finding of statistical abnormality.")
    section.table = {"title": f"{described} by quarter",
                     "columns": ["Period", "Value"],
                     "rows": [{"Period": p["period"], "Value": p["value"]}
                              for p in found["points"]],
                     "unit": AMOUNT_UNIT,
                     "footer": found["z_score_basis"] or
                     "Too few observations for a z-score."}
    if request.wants_chart is not False and found["observations"] > 2:
        section.chart = {"type": "line", "title": f"{described} by quarter",
                         "unit": AMOUNT_UNIT,
                         "series": [{"label": p["period"], "value": p["value"]}
                                    for p in found["points"]]}
    section.limitations = list(found["limitations"])
    section.findings = [f"Latest {money(found['latest'])}",
                        f"{found['observations']} observation(s) available"]

    ledger.add(ev.Observation(
        observation_id="obs-history-1", tool="metric_history",
        scope=_scope_text(request, quarters[-1], len(frame)), unit=AMOUNT_UNIT,
        reporting_date=cal.iso(quarters[-1]), data_version=DATA_VERSION,
        method="latest against preceding observations only",
        filters=dict(request.filters),
        figures={"latest": found["latest"] or 0.0,
                 "prior": found["prior"] or 0.0,
                 "change": found["change"] or 0.0,
                 "mean": found["mean"] or 0.0,
                 "std_dev": found["std_dev"] or 0.0,
                 "z_score": found["z_score"] or 0.0,
                 "comparator_periods": float(found["comparator_periods"]),
                 "observations": float(found["observations"])},
        rows=[{"period": p["period"], "value": p["value"]}
              for p in found["points"]],
        rows_total=len(found["points"]), limitations=list(found["limitations"])))
    present.update({"reporting_date", "population"})
    return section


def _data_quality_section(request: understand_mod.Request, principal: Any,
                          ledger: ev.Ledger, present: set[str]) -> Section:
    quarter = (request.to_period and cal.parse(request.to_period).label) \
        or reader.latest_quarter(principal)
    snap = _apply_filters(reader.snapshot(quarter, principal), request.filters)

    missing_statement = int((~snap["statement_available"].astype(bool)).sum())
    stale_statement = int(snap["statement_is_stale"].sum())
    stale_rating = int(snap["rating_is_stale"].sum())
    stale_valuation = int(snap["collateral_stale_valuations"].sum())
    untested = int(snap["covenants_untested"].sum())
    no_ratio = int(snap["ratio_dscr"].isna().sum())

    section = Section(understand_mod.DATA_QUALITY, "Data gaps")
    section.paragraphs.append(
        f"At {cal.display(quarter)}, of {len(snap):,} facilities: "
        f"{missing_statement} have no financial statement available at all; "
        f"{stale_statement} rely on a statement older than the "
        f"{policy.STALE_STATEMENT_DAYS}-day threshold; {stale_rating} carry a "
        f"rating older than {policy.STALE_RATING_DAYS} days; "
        f"{stale_valuation} rely on a collateral valuation older than "
        f"{policy.STALE_VALUATION_DAYS} days; {untested} covenant test(s) "
        f"could not be run; and {no_ratio} have no computable DSCR. Each of "
        f"these is reported as unavailable rather than as a zero.")
    section.table = {"title": f"Data gaps at {cal.display(quarter)}",
                     "columns": ["Gap", "Facilities affected"],
                     "rows": [
                         {"Gap": "No financial statement available",
                          "Facilities affected": missing_statement},
                         {"Gap": f"Statement older than "
                                 f"{policy.STALE_STATEMENT_DAYS} days",
                          "Facilities affected": stale_statement},
                         {"Gap": f"Rating older than "
                                 f"{policy.STALE_RATING_DAYS} days",
                          "Facilities affected": stale_rating},
                         {"Gap": f"Collateral valuation older than "
                                 f"{policy.STALE_VALUATION_DAYS} days",
                          "Facilities affected": stale_valuation},
                         {"Gap": "Covenant test could not be run",
                          "Facilities affected": untested},
                         {"Gap": "No computable DSCR",
                          "Facilities affected": no_ratio}],
                     "unit": "count",
                     "footer": "A missing input is null, never zero."}
    section.findings = [f"{missing_statement} facility/-ies with no statement",
                        f"{stale_statement} on a stale statement",
                        f"{untested} covenant test(s) not run"]
    ledger.add(ev.Observation(
        observation_id="obs-data-quality-1", tool="data_quality",
        scope=_scope_text(request, quarter, len(snap)), unit="count",
        reporting_date=cal.iso(quarter), data_version=DATA_VERSION,
        filters=dict(request.filters),
        figures={"facilities": float(len(snap)),
                 "missing_statement": float(missing_statement),
                 "stale_statement": float(stale_statement),
                 "stale_rating": float(stale_rating),
                 "stale_valuation": float(stale_valuation),
                 "untested_covenants": float(untested),
                 "no_dscr": float(no_ratio)},
        rows=section.table["rows"], rows_total=6))
    present.update({"reporting_date", "population"})
    return section


def _movement_section(request: understand_mod.Request, principal: Any,
                      ledger: ev.Ledger, present: set[str]) -> Section:
    periods = reader.resolve_period_pair(
        to_period=request.to_period, from_period=request.from_period,
        principal=principal)
    section = Section(understand_mod.MOVEMENT_BY_DIMENSION, "Movement")
    if not periods["available"]:
        section.answered = False
        section.unanswered_reason = periods["reason"]
        section.paragraphs.append(periods["reason"])
        return section

    dimension = request.dimension or "sector"
    measure = request.measure or "reported_ecl"
    opening = _apply_filters(reader.snapshot(periods["opening"], principal),
                             request.filters)
    closing = _apply_filters(reader.snapshot(periods["closing"], principal),
                             request.filters)
    found = attr.decompose_movement(
        opening.groupby(dimension)[measure].sum().to_dict(),
        closing.groupby(dimension)[measure].sum().to_dict(),
        measure_name=measure, unit=AMOUNT_UNIT,
        opening_date=cal.iso(periods["opening"]),
        closing_date=cal.iso(periods["closing"]),
        top=request.top_n or 0)

    described = schema_mod.MEASURE_BY_NAME.get(measure, {}).get("label", measure)
    if found["shares_available"]:
        top = found["rows"][0]
        section.paragraphs.append(
            f"{described} moved {money(found['net_change'])} between "
            f"{periods['opening_label']} and {periods['closing_label']}, from "
            f"{money(found['opening_total'])} to "
            f"{money(found['closing_total'])}. By {dimension} the largest "
            f"movement is {top['member']} at {money(top['change'])}, which is "
            f"{pct(top['share_of_net_change'])} of the net change. Increases "
            f"total {money(found['positive_contributions'])} and decreases "
            f"{money(found['negative_contributions'])}.")
    else:
        section.paragraphs.append(
            f"{described} is effectively unchanged between "
            f"{periods['opening_label']} and {periods['closing_label']} — "
            f"{money(found['opening_total'])} against "
            f"{money(found['closing_total'])}. No contribution share is "
            f"reported, because dividing into a net change of nearly nothing "
            f"produces meaningless percentages. Underneath it, increases "
            f"total {money(found['positive_contributions'])} and decreases "
            f"{money(found['negative_contributions'])}, so the flat headline "
            f"conceals movement in both directions.")

    section.table = {
        "title": f"{described} movement by {dimension}",
        "columns": ["Member", "Opening", "Closing", "Change",
                    "Share of net change %", "Membership"],
        "rows": [{"Member": r["member"], "Opening": round(r["opening"], 4),
                  "Closing": round(r["closing"], 4),
                  "Change": round(r["change"], 4),
                  "Share of net change %": (
                      None if r["share_of_net_change"] is None
                      else round(r["share_of_net_change"], 2)),
                  "Membership": r["membership"]}
                 for r in found["rows"]],
        "unit": AMOUNT_UNIT,
        "footer": (f"Shares may exceed 100% where other members offset them; "
                   f"they are not clipped. Amounts stay in {AMOUNT_UNIT}: a "
                   f"currency movement has no basis-point form.")}
    section.findings = [
        f"{r['member']}: {money(r['change'])}" for r in found["rows"][:5]]
    section.limitations = list(found["limitations"])

    ledger.add(ev.Observation(
        observation_id="obs-movement-1", tool="decompose_movement",
        scope=_scope_text(request, periods["closing"], len(closing),
                          periods["opening"]),
        unit=AMOUNT_UNIT, reporting_date=cal.iso(periods["closing"]),
        comparison_date=cal.iso(periods["opening"]),
        method=found["method"], data_version=DATA_VERSION,
        filters=dict(request.filters),
        figures={"opening_total": found["opening_total"],
                 "closing_total": found["closing_total"],
                 "net_change": found["net_change"],
                 "positive": found["positive_contributions"],
                 "negative": found["negative_contributions"]},
        entities=[str(r["member"]) for r in found["rows"]],
        rows=found["rows"], rows_total=found["rows_total"],
        truncated=found["truncated"], reconciled=found["reconciled"]))
    present.update({"opening_scope", "closing_scope", "population"})
    return section


def _ratio_section(request: understand_mod.Request, principal: Any,
                   ledger: ev.Ledger, present: set[str]) -> Section:
    periods = reader.resolve_period_pair(
        to_period=request.to_period, from_period=request.from_period,
        principal=principal)
    section = Section(understand_mod.RATIO_MOVEMENT, "Ratio movement")
    if not periods["available"]:
        section.answered = False
        section.unanswered_reason = periods["reason"]
        section.paragraphs.append(periods["reason"])
        return section

    opening = _apply_filters(reader.snapshot(periods["opening"], principal),
                             request.filters)
    closing = _apply_filters(reader.snapshot(periods["closing"], principal),
                             request.filters)
    lower = request.utterance.lower()
    if "npl" in lower or "non-performing" in lower:
        name = "NPL ratio"
        n0 = float(opening[opening["is_npl"] == True]["exposure"].sum())  # noqa: E712
        n1 = float(closing[closing["is_npl"] == True]["exposure"].sum())  # noqa: E712
    else:
        name = "ECL coverage"
        n0 = float(opening["reported_ecl"].sum())
        n1 = float(closing["reported_ecl"].sum())
    d0 = float(opening["exposure"].sum())
    d1 = float(closing["exposure"].sum())

    found = attr.decompose_ratio(
        numerator_opening=n0, numerator_closing=n1,
        denominator_opening=d0, denominator_closing=d1, ratio_name=name,
        opening_date=cal.iso(periods["opening"]),
        closing_date=cal.iso(periods["closing"]))

    if not found["available"]:
        section.answered = False
        section.unanswered_reason = found["reason"]
        section.paragraphs.append(found["reason"])
        return section

    numerator_bigger = abs(found["numerator_effect"]) >= abs(
        found["denominator_effect"])
    section.paragraphs.append(
        f"{name} moved from {found['opening_ratio'] * 100:.3f}% to "
        f"{found['closing_ratio'] * 100:.3f}%, a change of "
        f"{found['change_scaled']:+.2f} basis points. Splitting that exactly "
        f"into a numerator and a denominator effect: the numerator "
        f"contributed {found['numerator_effect_scaled']:+.2f} bp and the "
        f"denominator {found['denominator_effect_scaled']:+.2f} bp. "
        f"{'The numerator did the work' if numerator_bigger else 'The denominator did the work'}"
        f" — the ratio moved mainly because "
        f"{'the numerator changed' if numerator_bigger else 'the book itself changed size'}"
        f", which is a different fact from the other reading and the two "
        f"should not be confused.")
    section.paragraphs.append(
        f"In levels: the numerator went from {money(n0)} to {money(n1)} and "
        f"the denominator from {money(d0)} to {money(d1)}. The two effects sum "
        f"to the whole change, so there is no separate mix term to add — one "
        f"would make the parts sum to more than the whole.")
    section.table = {
        "title": f"{name} decomposition",
        "columns": ["Component", "Opening", "Closing", "Effect (bp)"],
        "rows": [
            {"Component": "Numerator", "Opening": round(n0, 4),
             "Closing": round(n1, 4),
             "Effect (bp)": round(found["numerator_effect_scaled"], 2)},
            {"Component": "Denominator", "Opening": round(d0, 4),
             "Closing": round(d1, 4),
             "Effect (bp)": round(found["denominator_effect_scaled"], 2)},
            {"Component": "Total", "Opening": round(found["opening_ratio"], 6),
             "Closing": round(found["closing_ratio"], 6),
             "Effect (bp)": round(found["change_scaled"], 2)}],
        "unit": "basis points",
        "footer": found["method_note"]}
    section.findings = [
        f"Numerator effect {found['numerator_effect_scaled']:+.1f} bp",
        f"Denominator effect {found['denominator_effect_scaled']:+.1f} bp"]

    ledger.add(ev.Observation(
        observation_id="obs-ratio-1", tool="decompose_ratio",
        scope=_scope_text(request, periods["closing"], len(closing),
                          periods["opening"]),
        unit="basis points", reporting_date=cal.iso(periods["closing"]),
        comparison_date=cal.iso(periods["opening"]), method=found["method"],
        data_version=DATA_VERSION, filters=dict(request.filters),
        figures={"opening_ratio": found["opening_ratio"],
                 "closing_ratio": found["closing_ratio"],
                 "opening_ratio_pct": found["opening_ratio"] * 100.0,
                 "closing_ratio_pct": found["closing_ratio"] * 100.0,
                 "change_bp": found["change_scaled"],
                 "numerator_effect_bp": found["numerator_effect_scaled"],
                 "denominator_effect_bp": found["denominator_effect_scaled"],
                 "numerator_opening": n0, "numerator_closing": n1,
                 "denominator_opening": d0, "denominator_closing": d1},
        rows=section.table["rows"], rows_total=3,
        reconciled=found["reconciled"]))
    present.update({"opening_scope", "closing_scope"})
    return section


def _parameter_product_section(request: understand_mod.Request, principal: Any,
                               ledger: ev.Ledger, present: set[str]) -> Section:
    quarter = (request.to_period and cal.parse(request.to_period).label) \
        or reader.latest_quarter(principal)
    snap = _apply_filters(reader.snapshot(quarter, principal), request.filters)
    section = Section(understand_mod.PARAMETER_PRODUCT_CHECK,
                      "Weighted parameters versus weighted ECL")
    naive = float((snap["weighted_twelve_month_pd"] * snap["weighted_lgd"]
                   * snap["weighted_ead"]).sum())
    modelled = float(snap["weighted_model_ecl"].sum())
    section.paragraphs.append(
        f"No. On this data at {cal.display(quarter)} the product of the "
        f"weighted parameters comes to {money(naive)} while the weighted "
        f"model ECL is {money(modelled)} — a difference of "
        f"{money(modelled - naive)}, or "
        f"{pct(abs(modelled - naive) / modelled * 100 if modelled else 0)} of "
        f"the modelled figure. The reason is that the expectation of a "
        f"product is not the product of expectations: PD, LGD and EAD move "
        f"together across scenarios, and the downturn scenario pairs its high "
        f"PD with its high LGD. Weighting each parameter separately throws "
        f"that covariance away. Weighted parameter summaries remain useful "
        f"descriptive measures; they are not a route back to the weighted ECL.")
    section.table = {
        "title": "Weighted parameters against the weighted result",
        "columns": ["Quantity", "Value"],
        "rows": [
            {"Quantity": "Exposure-weighted 12-month PD",
             "Value": round(float(
                 (snap["weighted_twelve_month_pd"] * snap["weighted_ead"]).sum()
                 / snap["weighted_ead"].sum()) if snap["weighted_ead"].sum()
                 else 0.0, 6)},
            {"Quantity": "Exposure-weighted LGD",
             "Value": round(float(
                 (snap["weighted_lgd"] * snap["weighted_ead"]).sum()
                 / snap["weighted_ead"].sum()) if snap["weighted_ead"].sum()
                 else 0.0, 6)},
            {"Quantity": "Sum of PD x LGD x EAD per facility",
             "Value": round(naive, 4)},
            {"Quantity": "Weighted model ECL (governed calculator)",
             "Value": round(modelled, 4)},
            {"Quantity": "Difference", "Value": round(modelled - naive, 4)}],
        "unit": AMOUNT_UNIT,
        "footer": "The shortcut understates or overstates according to the "
                  "covariance between the parameters; it is never equal."}
    section.findings = [
        f"Parameter product {money(naive)}",
        f"Weighted model ECL {money(modelled)}",
        f"Difference {money(modelled - naive)}"]
    ledger.add(ev.Observation(
        observation_id="obs-parameter-product-1",
        tool="parameter_product_check",
        scope=_scope_text(request, quarter, len(snap)), unit=AMOUNT_UNIT,
        reporting_date=cal.iso(quarter), model_version=MODEL_VERSION,
        data_version=DATA_VERSION,
        figures={"naive_parameter_product": naive,
                 "weighted_model_ecl": modelled,
                 "difference": modelled - naive,
                 "difference_pct": (abs(modelled - naive) / modelled * 100.0
                                    if modelled else 0.0)},
        rows=section.table["rows"], rows_total=5))
    present.add("parameter_product_check")
    return section


# ------------------------------------------------------------------- the run


_SIMPLE = {
    understand_mod.COMPOSITION: _composition_section,
    understand_mod.SCENARIO_COMPARISON: _scenario_section,
    understand_mod.COVENANT_REVIEW: _covenant_section,
    understand_mod.COLLATERAL_REVIEW: _collateral_section,
    understand_mod.RATING_REVIEW: _rating_section,
    understand_mod.STAGE_REVIEW: _stage_section,
    understand_mod.CONCENTRATION: _concentration_section,
    understand_mod.METRIC_HISTORY: _history_section,
    understand_mod.DATA_QUALITY: _data_quality_section,
    understand_mod.MOVEMENT_BY_DIMENSION: _movement_section,
    understand_mod.RATIO_MOVEMENT: _ratio_section,
    understand_mod.PARAMETER_PRODUCT_CHECK: _parameter_product_section,
}


def _recommendations(answer: Answer) -> list[dict[str, Any]]:
    """Suggested demo review actions, tied to what the evidence showed.

    Labelled as SUGGESTED and as DEMO. Nothing here has been assigned,
    notified, escalated or blocked, and the payload says so, because writing
    "escalated to the credit committee" in a chat window does not escalate
    anything.
    """
    out: list[dict[str, Any]] = []
    covenants = answer.ledger.by_tool("covenant_review")
    if covenants:
        uncovered = covenants[0].figures.get("uncovered", 0.0)
        if uncovered:
            out.append({
                "action": f"Review the {int(uncovered)} breached covenant "
                          f"test(s) with no waiver in force",
                "because": "they are breached and uncovered at the reporting "
                           "date",
                "suggested_owner": "Relationship Manager",
                "priority": "high",
                "monitoring_evidence": "cockpit_covenant_tests: waiver_status, "
                                       "headroom, next_test_due",
                "escalation_if": "no cure plan by the next test date"})
    factors = answer.ledger.by_tool("decompose_ecl_factors")
    if factors:
        pd_contribution = factors[0].figures.get(attr.FACTOR_PD)
        lgd_contribution = factors[0].figures.get(attr.FACTOR_LGD)
        if pd_contribution and pd_contribution > 0:
            out.append({
                "action": "Review the rating inputs on the facilities carrying "
                          "the largest PD contribution",
                "because": f"the PD factor group contributed "
                           f"{money(pd_contribution)} to the movement under "
                           f"this decomposition",
                "suggested_owner": "Credit Risk Analytics",
                "priority": "medium",
                "monitoring_evidence": "cockpit_scenario_parameters: "
                                       "twelve_month_pd by scenario; "
                                       "cockpit_borrower_financials: ratios",
                "escalation_if": "the same facilities contribute again next "
                                 "quarter"})
        if lgd_contribution and lgd_contribution > 0:
            out.append({
                "action": "Refresh the collateral valuations behind the "
                          "recovery movement",
                "because": f"the recovery and LGD group contributed "
                           f"{money(lgd_contribution)}",
                "suggested_owner": "Collateral Management",
                "priority": "medium",
                "monitoring_evidence": "cockpit_collateral_assets: "
                                       "valuation_age_days, recognised_value",
                "escalation_if": "coverage falls further on a valuation older "
                                 "than the policy threshold"})
    for item in out:
        item["status"] = "SUGGESTED — not assigned, not notified, not escalated"
        item["policy"] = ("No review policy is configured in this "
                          "demonstration, so these are suggested demo review "
                          "actions rather than bank-mandated deadlines.")
    return out


def compose(question: str, principal: Any = None, *,
            previous: understand_mod.Request | None = None,
            clarification: str = "") -> Answer:
    """Answer one Cockpit question from the governed demo data."""
    request = understand_mod.read(
        f"{question} {clarification}".strip() if clarification else question,
        previous=previous)
    answer = Answer(question=question, request=request)
    answer.scope_note = scope_mod.describe(principal)["domain"]
    present: set[str] = set()
    capabilities: list[str] = []
    try:
        _policy_observation(
            answer.ledger, principal,
            (request.to_period and cal.parse(request.to_period).label)
            or reader.latest_quarter(principal))
    except Exception:  # noqa: BLE001 - an answer without it still validates
        logger.debug("Cockpit V2 could not add the policy observation")

    if request.ambiguities and not request.outputs:
        answer.clarification = request.ambiguities[0]
        section = Section("clarification", "Which reading did you want?",
                          answered=False,
                          unanswered_reason="the question does not resolve to "
                                            "a movement or a composition")
        section.paragraphs.append(
            answer.clarification["question"]
            + " You can also type what you want in your own words.")
        answer.sections.append(section)
        answer.trace = _trace(answer, request, principal)
        return answer

    found: attr.FactorDecomposition | None = None
    periods: dict[str, Any] = {}

    for output in request.outputs:
        try:
            if output == understand_mod.ECL_FACTOR_DECOMPOSITION:
                section, found, periods = _decomposition_section(
                    request, principal, answer.ledger, present)
                capabilities.append("ecl_factor_decomposition")
            elif output == understand_mod.PD_IMPACT:
                if found is None:
                    section, found, periods = _decomposition_section(
                        request, principal, answer.ledger, present)
                    answer.sections.append(section)
                    capabilities.append("ecl_factor_decomposition")
                if found is None:
                    continue
                section = _pd_section(request, found, principal,
                                      answer.ledger, present, periods)
                capabilities.append("pd_impact")
            elif output == understand_mod.SCOPE_STATEMENT:
                section = _scope_section(request, principal, answer.ledger,
                                         present)
            elif output == understand_mod.DEFINITION:
                section = _definition_section(request, answer.ledger, present)
                capabilities.append("definition")
            elif output == understand_mod.MACRO_DEPENDENCY:
                section = _macro_section(request, answer.ledger, present)
                capabilities.append("macro_dependency")
            elif output in _SIMPLE:
                section = _SIMPLE[output](request, principal, answer.ledger,
                                          present)
                capabilities.append(output)
            else:
                continue
            answer.sections.append(section)
        except (reader.NotPublished, scope_mod.OutOfScope) as e:
            answer.sections.append(Section(
                output, output.replace("_", " ").title(), answered=False,
                unanswered_reason=str(e), paragraphs=[str(e)]))
        except Exception as e:  # noqa: BLE001 - one output failing is not all
            logger.exception("Cockpit V2 could not build %s", output)
            answer.sections.append(Section(
                output, output.replace("_", " ").title(), answered=False,
                unanswered_reason=(
                    f"this part of the question could not be answered: {e}"),
                paragraphs=[f"This part of the question could not be "
                            f"answered: {e}"]))

    for assertion in request.loaded_assertions:
        answer.sections.append(Section(
            "assertion_check", "About the premise of the question",
            paragraphs=[assertion["note"]],
            findings=[f"Premise not adopted: {assertion['assertion']}"]))

    answer.contracts = [ev.check_contract(c, present)
                        for c in dict.fromkeys(capabilities)]
    answer.validation = ev.validate(answer.narrative, answer.ledger)
    if request.wants_recommendations:
        answer.recommendations = _recommendations(answer)

    if answer.validation and not answer.validation.ok:
        # Brief §7.2: remove or correct the unsupported claim, keeping the
        # validated content, and say what happened rather than silently
        # serving prose that failed its own check.
        answer.fallback_reason = (
            f"{len(answer.validation.issues)} claim(s) did not validate "
            f"against the evidence and were removed.")
        for section in answer.sections:
            section.paragraphs = [
                p for p in section.paragraphs
                if not any(i.sentence[:60] in p
                           for i in answer.validation.issues)]
        answer.sections.append(Section(
            "validation", "Claims withheld",
            paragraphs=[
                "Some sentences did not validate against the evidence behind "
                "them and were removed rather than shown: "
                + "; ".join(f"{i.problem} ({i.detail})"
                            for i in answer.validation.issues[:4]) + "."],
            limitations=["This answer was regenerated with the unsupported "
                         "claims removed."]))

    answer.trace = _trace(answer, request, principal)
    return answer


def _trace(answer: Answer, request: understand_mod.Request,
           principal: Any) -> dict[str, Any]:
    from backend.cockpit_v2 import persist

    manifest = persist.read_manifest()
    return {
        "answer_version": ANSWER_VERSION,
        "prose_source": answer.prose_source,
        "data_version": DATA_VERSION, "model_version": MODEL_VERSION,
        "policy_version": POLICY_VERSION,
        "attribution_version": attr.ATTRIBUTION_VERSION,
        "requested_outputs": list(request.outputs),
        "subquestions": list(request.subquestions),
        "filters": dict(request.filters),
        "tools_called": sorted({o.tool for o in answer.ledger.observations}),
        "observations": len(answer.ledger.observations),
        "published_quarters": reader.published_quarters(principal),
        "dataset_checksums": manifest.get("quarter_checksums", {}),
        "scope": scope_mod.describe(principal)["scope"],
        "policy": {
            "sicr_notch_threshold": policy.SICR_NOTCH_THRESHOLD,
            "sicr_relative_pd_increase": policy.SICR_RELATIVE_PD_INCREASE,
            "default_dpd": policy.DEFAULT_DPD,
            "scenario_weights": dict(policy.SCENARIO_WEIGHT),
            "policy_id_rating": policy.RATING_MODEL_ID,
            "policy_id_sicr": policy.SICR_POLICY_ID,
            "policy_id_recovery": policy.RECOVERY_POLICY_ID,
        },
        "measurement": {
            "grid": f"{ecl_mod.PERIODS_PER_YEAR} periods per year",
            "twelve_month_window": ecl_mod.TWELVE_MONTH_PERIODS,
            "max_lifetime_periods": ecl_mod.MAX_LIFETIME_PERIODS,
            "performing_method": ecl_mod.METHOD_PERFORMING,
            "impaired_method": ecl_mod.METHOD_IMPAIRED,
        },
        "synthetic": SYNTHETIC_BANNER,
    }


__all__ = ["Answer", "PROSE_ANALYST", "PROSE_DETERMINISTIC",
           "PROSE_DETERMINISTIC_V2", "PROSE_INTERPRETATION", "SYNTHETIC_BANNER",
           "Section", "compose", "money", "pct", "prob"]
