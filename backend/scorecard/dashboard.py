"""
The validation dashboard, assembled. §7, §18, §22-§27, §30-§33, §40-§42, §47.

One place that reads a month, runs the deterministic engine over it, compares
every result against the approved policy and returns the payload the screen
and the report both use. The screen and the DOCX are built from the same
object on purpose: §55 asks for traceability, and two assembly paths would
eventually disagree about a number and nobody would know which was right.

Reading a month is cheap
-------------------------
§76. One month is one Parquet partition, so the read touches a single file
and the aggregation happens here rather than in the browser. Nothing sends
300,000 rows anywhere: every section returns summary rows, band tables and
curve samples.

Maturity is decided once, at the top
--------------------------------------
§7/§44. The dashboard resolves the requested month against the performance
horizon before it runs anything, and carries the answer through. Sections
that need a realised outcome are skipped with a reason rather than being run
and returning something plausible; stability sections run regardless,
because they never needed an outcome.
"""

from __future__ import annotations

import glob
import logging
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

import pandas as pd

from backend.scorecard import build as build_mod
from backend.scorecard import metrics as metrics_mod
from backend.scorecard import policy as policy_mod
from backend.scorecard import synthetic as synth
from backend.scorecard import variables as vars_mod

logger = logging.getLogger(__name__)

DASHBOARD_VERSION = "1.0.0"

APP = vars_mod.APPLICATION_SCORECARD
BEH = vars_mod.BEHAVIORAL_SCORECARD

PERIOD_FIELD: dict[str, str] = {
    APP: "application_month", BEH: "observation_month",
}


class DashboardError(Exception):
    """A dashboard that cannot be assembled as asked."""


# ------------------------------------------------------------------ loading


def _partition(scorecard_type: str, month: str) -> str:
    from backend.config import settings

    name = build_mod.dataset_name(scorecard_type, "monthly_validation")
    field_name = PERIOD_FIELD[scorecard_type]
    return str(settings.analytics_dir / name / f"{field_name}={month}")


def available_months(scorecard_type: str) -> list[str]:
    from backend.config import settings

    name = build_mod.dataset_name(scorecard_type, "monthly_validation")
    field_name = PERIOD_FIELD[scorecard_type]
    root = settings.analytics_dir / name
    found = sorted(p.name.split("=", 1)[1]
                   for p in root.glob(f"{field_name}=*") if p.is_dir())
    return found


@lru_cache(maxsize=64)
def _load_cached(scorecard_type: str, month: str) -> pd.DataFrame:
    files = glob.glob(f"{_partition(scorecard_type, month)}/*.parquet")
    if not files:
        raise DashboardError(
            f"no data for {scorecard_type} {month}. Available months: "
            + (", ".join(available_months(scorecard_type)) or "none") +
            '. Run scripts/build_retail_scorecards.py to generate this '
            'deployment universe.')
    return pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)


def load_month(scorecard_type: str, month: str) -> pd.DataFrame:
    return _load_cached(scorecard_type, month).copy()


@lru_cache(maxsize=4)
def load_development(scorecard_type: str) -> pd.DataFrame:
    from backend.config import settings

    name = build_mod.dataset_name(scorecard_type, "development_reference")
    files = glob.glob(str(settings.analytics_dir / name / "**" / "*.parquet"),
                      recursive=True)
    if not files:
        raise DashboardError(
            f"no development reference for {scorecard_type}. Stability is "
            "measured against it, so there is no baseline to compare to.")
    return pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)


# ------------------------------------------------------------------ context


@dataclass
class Context:
    """§7/§18/§44. What was asked for, and what is actually available."""

    scorecard_type: str
    model_kind: str
    month: str
    latest_data_month: str
    latest_matured_month: str
    horizon_months: int
    outcomes_available: bool
    reference: str

    @property
    def stability_only(self) -> bool:
        return not self.outcomes_available

    def to_dict(self) -> dict[str, Any]:
        return {
            "scorecard_type": self.scorecard_type,
            "model": self.model_kind,
            "validation_month": self.month,
            "latest_data_month": self.latest_data_month,
            "latest_matured_performance_month": self.latest_matured_month,
            "performance_horizon_months": self.horizon_months,
            "outcome_maturity_status": (
                "MATURED" if self.outcomes_available
                else "NOT MATURED — STABILITY ONLY"),
            "reference_population": self.reference,
            "what_this_means": (
                "Predictive metrics are computed on this month."
                if self.outcomes_available else
                "This month's performance window has not closed, so no "
                "outcome exists to compare predictions against. Stability "
                "metrics are shown because they never needed one."),
        }


def resolve(scorecard_type: str, *, model_kind: str = "INCUMBENT",
            month: str = "", reference: str = "DEVELOPMENT") -> Context:
    """§18's default view: the latest fully matured month, not the latest."""
    months = available_months(scorecard_type)
    if not months:
        raise DashboardError(f"no months are available for {scorecard_type}")
    if model_kind not in build_mod.MODEL_KINDS:
        raise DashboardError(
            f"{model_kind!r} is not a registered model; known: "
            + ", ".join(build_mod.MODEL_KINDS))

    matured = [m for m in months if synth.matured(m)]
    chosen = month or (matured[-1] if matured else months[-1])
    if chosen not in months:
        raise DashboardError(
            f"{chosen} is not one of the available months for "
            f"{scorecard_type}")

    return Context(
        scorecard_type=scorecard_type, model_kind=model_kind, month=chosen,
        latest_data_month=months[-1],
        latest_matured_month=matured[-1] if matured else "",
        horizon_months=synth.DEFAULT_HORIZON_MONTHS,
        outcomes_available=synth.matured(chosen),
        reference=reference)


# ------------------------------------------------------------------ sections


def _suffix(model_kind: str) -> str:
    return build_mod.OUTPUT_SUFFIX[model_kind]


def _score_direction(scorecard_type: str, model_kind: str) -> str:
    equation = build_mod.load_equation(scorecard_type, model_kind)
    if equation.score_mapping is None:
        raise DashboardError(f"{model_kind} has no score mapping")
    return equation.score_mapping.score_direction


def summary_section(frame: pd.DataFrame, context: Context) -> dict[str, Any]:
    """§22's top strip."""
    suffix = _suffix(context.model_kind)
    outcome = frame["actual_default"]
    defaults = int(outcome.sum()) if outcome.notna().all() else None
    return {
        "model": f"{context.scorecard_type} {context.model_kind}",
        "population": len(frame),
        "defaults": defaults,
        "observed_default_rate": (
            None if defaults is None else round(float(outcome.mean()), 6)),
        "average_predicted_pd": round(float(frame[f"pd_{suffix}"].mean()), 6),
        "average_score": round(float(frame[f"score_{suffix}"].mean()), 2),
        "origin": synth.ORIGIN,
        **context.to_dict(),
    }


def discrimination_section(frame: pd.DataFrame, context: Context, *,
                           curves: bool = True) -> dict[str, Any]:
    """§23."""
    if context.stability_only:
        return _skipped("Discrimination", context)
    suffix = _suffix(context.model_kind)
    direction = _score_direction(context.scorecard_type, context.model_kind)
    found = metrics_mod.discrimination(
        frame, score=f"score_{suffix}", target="actual_default",
        score_direction=direction,
        label=f"{context.model_kind} {context.month}", curves=curves)
    body = found.to_dict()
    body["gains"] = metrics_mod.gains(
        frame, score=f"score_{suffix}", target="actual_default",
        score_direction=direction)
    if curves:
        body["roc_curve"] = found.roc
        body["ks_curve"] = found.ks_curve
    body["assessments"] = [
        policy_mod.assess("auc", found.auc, evidence=found.evidence).to_dict(),
        policy_mod.assess("gini", found.gini,
                          evidence=found.evidence).to_dict(),
        policy_mod.assess("ks", found.ks, evidence=found.evidence).to_dict(),
    ]
    return body


def calibration_section(frame: pd.DataFrame, context: Context
                        ) -> dict[str, Any]:
    """§24."""
    if context.stability_only:
        return _skipped("Calibration", context)
    suffix = _suffix(context.model_kind)
    found = metrics_mod.calibration(
        frame, pd_column=f"pd_{suffix}", target="actual_default",
        score=f"score_{suffix}",
        score_direction=_score_direction(context.scorecard_type,
                                         context.model_kind),
        label=f"{context.model_kind} {context.month}")
    body = found.to_dict()
    body["assessments"] = [
        policy_mod.assess("calibration_in_the_large",
                          found.calibration_in_the_large).to_dict(),
        policy_mod.assess("bucket_rmse", found.bucket_rmse).to_dict(),
        policy_mod.assess("brier_score", found.brier).to_dict(),
    ]
    return body


def stability_section(frame: pd.DataFrame, context: Context, *,
                      variables: list[str] | None = None) -> dict[str, Any]:
    """§25/§26. Never gated on maturity — it never needed an outcome."""
    reference = load_development(context.scorecard_type)
    suffix = _suffix(context.model_kind)

    score_psi = metrics_mod.psi(reference, frame, score=f"score_{suffix}")
    equation = build_mod.load_equation(context.scorecard_type,
                                       context.model_kind)
    wanted = variables or equation.active_variables

    per_variable: list[dict[str, Any]] = []
    for name in wanted:
        try:
            shift = metrics_mod.csi(reference, frame, variable=name)
        except metrics_mod.MetricError as exc:
            per_variable.append({"variable": name, "index": None,
                                 "why": str(exc)})
            continue
        body = shift.to_dict()
        body["assessment"] = policy_mod.assess(
            "variable_csi", shift.index,
            label=f"CSI on {name}").to_dict()
        per_variable.append(body)

    per_variable.sort(key=lambda row: -(row.get("index") or 0.0))

    spec = build_mod.load_spec(context.scorecard_type)
    return {
        "dashboard_version": DASHBOARD_VERSION,
        "score_psi": score_psi.to_dict(),
        "score_psi_assessment": policy_mod.assess(
            "score_psi", score_psi.index).to_dict(),
        "variable_csi": per_variable,
        "special_bin_rates": spec.special_bin_rates(frame, wanted),
        "baseline": context.reference,
        "available_without_outcomes": (
            "Stability compares this month's population against the "
            "development reference. It needs no realised outcome, so it is "
            "reported even where predictive metrics cannot be."),
    }


def variables_section(frame: pd.DataFrame, context: Context, *,
                      candidates: bool = False) -> dict[str, Any]:
    """§27. Active variables by default; every candidate on request."""
    if context.stability_only:
        return _skipped("Variable diagnostics", context)
    equation = build_mod.load_equation(context.scorecard_type,
                                       context.model_kind)
    names = (vars_mod.names(context.scorecard_type, scoreable_only=True)
             if candidates else equation.active_variables)
    spec = build_mod.load_spec(context.scorecard_type)

    rows: list[dict[str, Any]] = []
    for name in names:
        if f"{name}_woe" not in frame.columns and name not in frame.columns:
            continue
        try:
            body = metrics_mod.variable_discrimination(
                frame, variable=name, target="actual_default")
        except metrics_mod.MetricError:
            continue
        binning = spec.variables.get(name)
        body["information_value"] = (binning.information_value if binning
                                     else None)
        body["woe_monotonic"] = binning.monotonic if binning else None
        body["in_active_model"] = name in equation.active_variables
        body["coefficient"] = next(
            (t.coefficient for t in equation.terms if t.variable == name),
            None)
        rows.append(body)

    rows.sort(key=lambda row: -(row.get("gini") or 0.0))
    return {
        "dashboard_version": DASHBOARD_VERSION,
        "scope": "ALL CANDIDATES" if candidates else "ACTIVE MODEL VARIABLES",
        "variables": rows,
        "active_variables": equation.active_variables,
        "candidate_count": len(vars_mod.catalogue(context.scorecard_type)),
        "candidate_is_not_active": (
            "The dataset carries "
            f"{len(vars_mod.catalogue(context.scorecard_type))} candidate "
            f"predictors; this model uses {len(equation.active_variables)}. "
            "A drift report on every candidate is not a report on the "
            "model."),
    }


def implementation_section(frame: pd.DataFrame, context: Context
                           ) -> dict[str, Any]:
    """§33. Independent reconstruction against what was stored."""
    equation = build_mod.load_equation(context.scorecard_type,
                                       context.model_kind)
    found = metrics_mod.replicate(frame, equation,
                                  label=f"{context.model_kind} "
                                        f"{context.month}")
    body = found.to_dict()
    body["assessment"] = policy_mod.assess(
        "implementation_mismatch_rate", found.mismatch_rate).to_dict()
    return body


def data_quality_section(frame: pd.DataFrame, context: Context
                         ) -> dict[str, Any]:
    """§38."""
    equation = build_mod.load_equation(context.scorecard_type,
                                       context.model_kind)
    keys = (["application_month", "application_id"]
            if context.scorecard_type == APP
            else ["observation_month", "account_id"])
    suffix = _suffix(context.model_kind)

    missing = {
        name: round(float(frame[name].isna().mean()), 6)
        for name in equation.active_variables if name in frame.columns
    }
    outcome = frame["actual_default"]
    return {
        "dashboard_version": DASHBOARD_VERSION,
        "rows": len(frame),
        "unique_keys": int(frame[keys].drop_duplicates().shape[0]),
        "duplicate_keys": len(frame) - int(
            frame[keys].drop_duplicates().shape[0]),
        "defaults": int(outcome.sum()) if outcome.notna().all() else None,
        "outcome_missing": int(outcome.isna().sum()),
        "matured": bool(frame["matured_flag"].all()),
        "missingness_by_active_variable": missing,
        "missingness_assessments": [
            policy_mod.assess("missing_rate", rate,
                              label=f"Missingness on {name}").to_dict()
            for name, rate in sorted(missing.items(), key=lambda x: -x[1])[:5]
        ],
        "score_range": {
            "min": round(float(frame[f"score_{suffix}"].min()), 2),
            "max": round(float(frame[f"score_{suffix}"].max()), 2),
        },
        "pd_within_zero_and_one": bool(
            (frame[f"pd_{suffix}"] >= 0).all()
            and (frame[f"pd_{suffix}"] <= 1).all()),
        "sample_sufficiency": [
            policy_mod.assess("minimum_observations", len(frame)).to_dict(),
            policy_mod.assess(
                "minimum_defaults",
                int(outcome.sum()) if outcome.notna().all() else None
            ).to_dict(),
        ],
        "origin": synth.ORIGIN,
    }


def segment_section(frame: pd.DataFrame, context: Context, *,
                    by: str) -> dict[str, Any]:
    """§40. Performance by segment, with sample sufficiency per segment."""
    if context.stability_only:
        return _skipped(f"Segment performance by {by}", context)
    if by not in frame.columns:
        raise DashboardError(
            f"{by} is not a column of this dataset, so performance cannot "
            "be split by it")
    suffix = _suffix(context.model_kind)
    direction = _score_direction(context.scorecard_type, context.model_kind)

    rows: list[dict[str, Any]] = []
    for value, chunk in frame.groupby(by, observed=True):
        events = int(chunk["actual_default"].sum())
        row: dict[str, Any] = {
            "segment": str(value),
            "observations": len(chunk),
            "events": events,
            "observed_default_rate": round(
                float(chunk["actual_default"].mean()), 6),
            "average_predicted_pd": round(
                float(chunk[f"pd_{suffix}"].mean()), 6),
            "evidence": metrics_mod.evidence_for(events, len(chunk)),
        }
        try:
            found = metrics_mod.discrimination(
                chunk, score=f"score_{suffix}", target="actual_default",
                score_direction=direction)
            row["gini"] = round(found.gini, 6)
            row["ks"] = round(found.ks, 6)
        except metrics_mod.MetricError as exc:
            row["gini"] = None
            row["why_no_gini"] = str(exc)
        rows.append(row)

    rows.sort(key=lambda r: -r["observations"])
    return {
        "dashboard_version": DASHBOARD_VERSION,
        "split_by": by,
        "segments": rows,
        "sample_sufficiency": (
            "A segment below the approved minimum carries its evidence "
            "label. §40: ranking segments on thirty accounts each ranks the "
            "noise."),
    }


def comparison_section(frame: pd.DataFrame, context: Context
                       ) -> dict[str, Any]:
    """§36. Every registered model on an identical population and period."""
    if context.stability_only:
        return _skipped("Model comparison", context)
    direction = _score_direction(context.scorecard_type, "INCUMBENT")
    rows: list[dict[str, Any]] = []
    for kind in build_mod.MODEL_KINDS:
        suffix = _suffix(kind)
        found = metrics_mod.discrimination(
            frame, score=f"score_{suffix}", target="actual_default",
            score_direction=direction, label=kind)
        calibrated = metrics_mod.calibration(
            frame, pd_column=f"pd_{suffix}", target="actual_default",
            score=f"score_{suffix}", score_direction=direction, label=kind)
        rows.append({
            "model": kind,
            "auc": round(found.auc, 6),
            "gini": round(found.gini, 6),
            "ks": round(found.ks, 6),
            "brier_score": round(calibrated.brier, 8),
            "log_loss": round(calibrated.log_loss, 8),
            "bucket_rmse": round(calibrated.bucket_rmse, 8),
            "mape": calibrated.mape,
            "mape_status": calibrated.mape_status,
            "average_predicted_pd": round(calibrated.predicted_rate, 6),
            "observed_default_rate": round(calibrated.observed_rate, 6),
            "auc_ci_low": found.to_dict()["auc_ci_low"],
            "auc_ci_high": found.to_dict()["auc_ci_high"],
            "evidence": found.evidence,
        })
    best_rank = max(rows, key=lambda r: r["gini"])
    best_level = min(rows, key=lambda r: abs(
        r["observed_default_rate"] - r["average_predicted_pd"]))
    return {
        "dashboard_version": DASHBOARD_VERSION,
        "population": len(frame),
        "period": context.month,
        "models": rows,
        "best_rank_ordering": best_rank["model"],
        "best_calibrated": best_level["model"],
        "identical_population": (
            "Every model above was scored on the same rows over the same "
            "period. A comparison across different populations measures the "
            "populations."),
        "overlapping_intervals": (
            "Where the AUC confidence intervals overlap, the difference "
            "between two models has not been shown on this sample."),
    }


def _skipped(what: str, context: Context) -> dict[str, Any]:
    return {
        "dashboard_version": DASHBOARD_VERSION,
        "available": False,
        "section": what,
        "why": (
            f"{what} compares predicted against actual, and {context.month}'s "
            f"performance window closes "
            f"{synth.add_months(context.month, context.horizon_months)}. "
            "There is no realised outcome to compare against. The latest "
            f"fully matured month is {context.latest_matured_month}."),
        "latest_matured_month": context.latest_matured_month,
    }


# --------------------------------------------------------------- assembly


@dataclass
class Dashboard:
    """§47's composed dashboard, and the opinion derived from it."""

    context: Context
    sections: dict[str, Any] = field(default_factory=dict)
    assessments: list[policy_mod.Assessment] = field(default_factory=list)
    opinion: policy_mod.Opinion | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "dashboard_version": DASHBOARD_VERSION,
            "context": self.context.to_dict(),
            **self.sections,
            "performance_limits": [a.to_dict() for a in self.assessments],
            "validation_opinion": (self.opinion.to_dict() if self.opinion
                                   else None),
            "origin": synth.ORIGIN,
            "not_client_data": (
                'This dashboard is computed over synthetic data. It describes '
                "no real customer and no real bank's book."),
        }


#: §47's section order. The dashboard is composed in this order and the
#: report follows it, so a reader moving between the two is not re-orienting.
SECTION_ORDER: tuple[str, ...] = (
    "summary", "data_quality", "discrimination", "calibration", "stability",
    "variables", "implementation", "segments", "findings", "comparison",
)


def build_dashboard(scorecard_type: str, *, model_kind: str = "INCUMBENT",
                    month: str = "", segment_by: str = "",
                    curves: bool = True) -> Dashboard:
    """Assemble everything for one model, one month."""
    context = resolve(scorecard_type, model_kind=model_kind, month=month)
    frame = load_month(scorecard_type, context.month)

    sections: dict[str, Any] = {
        "summary": summary_section(frame, context),
        "data_quality": data_quality_section(frame, context),
        "discrimination": discrimination_section(frame, context,
                                                 curves=curves),
        "calibration": calibration_section(frame, context),
        "stability": stability_section(frame, context),
        "variables": variables_section(frame, context),
        "implementation": implementation_section(frame, context),
        "comparison": comparison_section(frame, context),
    }
    if segment_by:
        sections["segments"] = segment_section(frame, context, by=segment_by)

    assessments = _collect_assessments(sections, frame, context)
    findings = _findings_from(assessments, context)
    sections["findings"] = {
        "findings": [f.to_dict() for f in findings],
        "counts": {severity: sum(1 for f in findings
                                 if f.severity == severity)
                   for severity in policy_mod.SEVERITIES},
    }

    sample_sufficient = all(
        a.status != policy_mod.BREACH for a in assessments
        if a.metric in ("minimum_defaults", "minimum_observations"))
    opinion = policy_mod.opine(assessments, findings,
                              sample_sufficient=sample_sufficient)

    return Dashboard(context=context, sections=sections,
                     assessments=assessments, opinion=opinion)


def _collect_assessments(sections: dict[str, Any], frame: pd.DataFrame,
                         context: Context) -> list[policy_mod.Assessment]:
    """Every limit comparison on the dashboard, in one list.

    Rebuilt from the numbers rather than collected from the section dicts,
    so the limits table and the sections cannot drift into disagreeing.
    """
    found: list[policy_mod.Assessment] = []
    discrimination = sections.get("discrimination", {})
    if discrimination.get("available") is not False:
        found.append(policy_mod.assess("auc", discrimination.get("auc")))
        found.append(policy_mod.assess("gini", discrimination.get("gini")))
        found.append(policy_mod.assess("ks", discrimination.get("ks")))

    calibration = sections.get("calibration", {})
    if calibration.get("available") is not False:
        found.append(policy_mod.assess(
            "calibration_in_the_large",
            calibration.get("calibration_in_the_large")))
        found.append(policy_mod.assess("bucket_rmse",
                                       calibration.get("bucket_rmse")))
        found.append(policy_mod.assess("brier_score",
                                       calibration.get("brier_score")))

    stability = sections.get("stability", {})
    found.append(policy_mod.assess(
        "score_psi", (stability.get("score_psi") or {}).get("index")))
    worst = max((row for row in stability.get("variable_csi", [])
                 if row.get("index") is not None),
                key=lambda row: row["index"], default=None)
    if worst is not None:
        found.append(policy_mod.assess(
            "variable_csi", worst["index"],
            label=f"Worst variable CSI ({worst['variable']})"))

    implementation = sections.get("implementation", {})
    found.append(policy_mod.assess("implementation_mismatch_rate",
                                   implementation.get("mismatch_rate")))

    quality = sections.get("data_quality", {})
    found.append(policy_mod.assess("minimum_observations",
                                   quality.get("rows")))
    found.append(policy_mod.assess("minimum_defaults",
                                   quality.get("defaults")))
    missing = quality.get("missingness_by_active_variable") or {}
    if missing:
        name = max(missing, key=lambda k: missing[k])
        found.append(policy_mod.assess(
            "missing_rate", missing[name],
            label=f"Worst missingness ({name})"))

    del frame, context
    return found


def _findings_from(assessments: list[policy_mod.Assessment],
                   context: Context) -> list[policy_mod.Finding]:
    """§48. Raise a finding for every breach and every watch."""
    category_for = {
        "auc": "DISCRIMINATION", "gini": "DISCRIMINATION",
        "ks": "DISCRIMINATION",
        "calibration_in_the_large": "CALIBRATION",
        "bucket_rmse": "CALIBRATION", "brier_score": "CALIBRATION",
        "score_psi": "STABILITY", "variable_csi": "STABILITY",
        "implementation_mismatch_rate": "IMPLEMENTATION",
        "minimum_observations": "DATA_QUALITY",
        "minimum_defaults": "DATA_QUALITY",
        "missing_rate": "DATA_QUALITY",
    }
    findings: list[policy_mod.Finding] = []
    for index, assessment in enumerate(assessments):
        if assessment.status not in (policy_mod.BREACH, policy_mod.WATCH):
            continue
        category = category_for.get(assessment.metric, "MONITORING")
        findings.append(policy_mod.finding_from(
            assessment,
            finding_id=(f"F-{context.scorecard_type[:3]}-"
                        f"{context.month.replace('-', '')}-{index + 1:03d}"),
            model_id=f"{context.scorecard_type}_{context.model_kind}",
            model_version="1.0.0", period=context.month, category=category,
            title=f"{assessment.label} outside approved limit",
            description=assessment.to_dict()["why"],
            impact=("The metric is outside the limit approved for it, so "
                    "the model's performance on this dimension is not "
                    "within what the institution accepts."),
            recommendation=(
                "Investigate the driver before the next monitoring cycle "
                "and record whether it is a population change, a model "
                "problem or an implementation problem."),
            raised_by="CreditProbe governed policy"))
    return findings
