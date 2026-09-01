"""
Agentic validation diagnostics. §28-§32, §37, §58-§60.

The three questions a validator actually asks, turned into governed
analytical plans rather than into prompts.

"Which variable is causing the low KS?"
----------------------------------------
§28 is careful about this and the care is the point. A user asks which
variable is *causing* poor discrimination. Nothing available can answer
that: what can be measured is which active variables show the largest
*deterioration* in their own predictive power and in their contribution to
the model. So the question is restated before it is answered, the evidence
is ranked, and the wording is "associated with the largest deterioration"
unless a leave-one-out actually supports more.

The leave-one-out is what upgrades the claim. Refitting the model without a
variable and measuring what happens is a real intervention on a real model,
and where it runs the answer may say the variable *accounts for* the drop.
Where it does not run, the answer stays associational and says so.

"Accuracy deteriorated. Why?"
-------------------------------
§29's eleven steps, in order, ending on the step that matters most:
challenge whether this is discrimination, calibration, stability,
implementation or population mix. Those five have different remediations and
a diagnostic that does not separate them sends somebody to fix the wrong
thing.

Nothing here calls a model
----------------------------
Every step is deterministic. The output is an evidence table with a ranking
and an explicit statement of what the evidence does and does not support.
The LLM narrates it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from backend.scorecard import build as build_mod
from backend.scorecard import dashboard as dash
from backend.scorecard import fitting
from backend.scorecard import metrics as metrics_mod
from backend.scorecard import variables as vars_mod

logger = logging.getLogger(__name__)

DIAGNOSTICS_VERSION = "1.0.0"

#: §28's wording rule. The weaker claim is the default and the stronger one
#: has to be earned by an intervention.
ASSOCIATED = "associated with the largest deterioration"
ACCOUNTS_FOR = "accounts for the largest share of the deterioration"

#: §29's five candidate root causes. Separated because they have different
#: remediations: a population shift is fixed by re-segmenting or
#: recalibrating, a discrimination loss by redeveloping, an implementation
#: break by fixing the code.
ROOT_CAUSES: tuple[tuple[str, str], ...] = (
    ("DISCRIMINATION", "The model has lost rank-ordering power. Its ability "
                       "to separate good from bad has fallen."),
    ("CALIBRATION", "The ordering still holds but the level is wrong: "
                    "predicted PD no longer matches observed default rate."),
    ("STABILITY", "The population has moved away from the one the model was "
                  "developed on, without the model itself changing."),
    ("IMPLEMENTATION", "The scores in production cannot be reproduced from "
                       "the approved equation."),
    ("POPULATION_MIX", "The segment composition changed, so the aggregate "
                       "moved even where each segment held."),
)


class DiagnosticError(Exception):
    """A diagnostic that cannot be run as asked."""


@dataclass
class Evidence:
    """One measured fact, and how strongly it points at something."""

    subject: str
    measure: str
    current: float | None
    baseline: float | None
    change: float | None
    weight: float
    reads_as: str
    evidence_level: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject": self.subject, "measure": self.measure,
            "current": (None if self.current is None
                        else round(self.current, 6)),
            "baseline": (None if self.baseline is None
                         else round(self.baseline, 6)),
            "change": (None if self.change is None
                       else round(self.change, 6)),
            "weight": round(self.weight, 6),
            "evidence": self.evidence_level,
            "reads_as": self.reads_as,
        }


@dataclass
class Diagnosis:
    """What a diagnostic established, and what it did not."""

    question_as_asked: str
    question_as_analysed: str
    steps: list[str] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    ranked: list[dict[str, Any]] = field(default_factory=list)
    claim_strength: str = ASSOCIATED
    limitations: list[str] = field(default_factory=list)
    next_analyses: list[str] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "diagnostics_version": DIAGNOSTICS_VERSION,
            "question_as_asked": self.question_as_asked,
            "question_as_analysed": self.question_as_analysed,
            "why_restated": (
                "The question asked what is *causing* something. What can be "
                "measured is what changed alongside it. The restatement is "
                "the honest version of the question, not a narrower one."),
            "steps_run": list(self.steps),
            "evidence": [e.to_dict() for e in self.evidence],
            "ranked": list(self.ranked),
            "claim_strength": self.claim_strength,
            "limitations": list(self.limitations),
            "suggested_next_analyses": list(self.next_analyses),
            "context": dict(self.context),
        }


# ------------------------------------------------- §28/§58 the low-KS case


def low_discrimination(scorecard_type: str, *, month: str = "",
                       model_kind: str = "INCUMBENT",
                       question: str = "",
                       leave_one_out: bool = True) -> Diagnosis:
    """§28/§58. Which active variable deteriorated most, and by how much."""
    context = dash.resolve(scorecard_type, model_kind=model_kind,
                           month=month)
    if context.stability_only:
        raise metrics_mod.ImmatureCohortError(
            f"{context.month} has no realised outcome, so no discrimination "
            "can be measured on it. The latest fully matured month is "
            f"{context.latest_matured_month}.")

    current = dash.load_month(scorecard_type, context.month)
    baseline = dash.load_development(scorecard_type)
    equation = build_mod.load_equation(scorecard_type, model_kind)

    diagnosis = Diagnosis(
        question_as_asked=question or "The KS of the model is poor this "
                                      "month. Which variable is causing it?",
        question_as_analysed=(
            "Which active model variables show the largest deterioration in "
            "univariate discrimination and in their contribution to the "
            "model, between the development population and "
            f"{context.month}?"),
        context={**context.to_dict(),
                 "active_variables": equation.active_variables})

    direction = (equation.score_mapping.score_direction
                 if equation.score_mapping else "")
    suffix = build_mod.OUTPUT_SUFFIX[model_kind]
    now = metrics_mod.discrimination(
        current, score=f"score_{suffix}", target="actual_default",
        score_direction=direction)
    then = metrics_mod.discrimination(
        baseline, score=f"score_{suffix}", target="actual_default",
        score_direction=direction)
    diagnosis.steps.append(
        f"1. Model KS on {context.month}: {now.ks:.4f} against {then.ks:.4f} "
        f"on the development population ({now.ks - then.ks:+.4f}).")
    diagnosis.context["model_ks_now"] = round(now.ks, 6)
    diagnosis.context["model_ks_baseline"] = round(then.ks, 6)
    diagnosis.context["model_gini_now"] = round(now.gini, 6)
    diagnosis.context["model_gini_baseline"] = round(then.gini, 6)

    diagnosis.steps.append(
        "2. Univariate KS, AUC and Information Value for each active "
        "variable, on both populations.")
    spec = build_mod.load_spec(scorecard_type)
    for name in equation.active_variables:
        try:
            now_row = metrics_mod.variable_discrimination(
                current, variable=name, target="actual_default")
            then_row = metrics_mod.variable_discrimination(
                baseline, variable=name, target="actual_default")
        except metrics_mod.MetricError:
            continue
        if now_row["ks"] is None or then_row["ks"] is None:
            continue
        change = now_row["ks"] - then_row["ks"]
        diagnosis.evidence.append(Evidence(
            subject=name, measure="univariate KS",
            current=now_row["ks"], baseline=then_row["ks"], change=change,
            weight=max(-change, 0.0),
            evidence_level=now_row["evidence"],
            reads_as=(
                f"{name}: univariate KS {then_row['ks']:.4f} to "
                f"{now_row['ks']:.4f} ({change:+.4f}).")))

    diagnosis.steps.append(
        "3. CSI, missingness and special-bin usage for each active "
        "variable, to separate a variable that stopped working from one "
        "whose population moved.")
    for name in equation.active_variables:
        try:
            shift = metrics_mod.csi(baseline, current, variable=name)
        except metrics_mod.MetricError:
            continue
        diagnosis.evidence.append(Evidence(
            subject=name, measure="CSI", current=shift.index, baseline=0.0,
            change=shift.index, weight=shift.index * 0.5,
            reads_as=f"{name}: CSI {shift.index:.4f} against the "
                     "development population."))

    specials = spec.special_bin_rates(current, equation.active_variables)
    for name, rates in specials.items():
        total = rates.get("MISSING", 0.0) + rates.get("UNSEEN", 0.0)
        if total <= 0:
            continue
        diagnosis.evidence.append(Evidence(
            subject=name, measure="special-bin rate", current=total,
            baseline=None, change=None, weight=total * 0.4,
            reads_as=(f"{name}: {total:.1%} of rows fell in a MISSING or "
                      "UNSEEN bin.")))

    if leave_one_out:
        diagnosis.steps.append(
            "4. Leave-one-variable-out: refit the model without each "
            "variable on the development population and re-measure on this "
            "month. This is an intervention on a real model, which is what "
            "would let the answer say a variable ACCOUNTS FOR the drop "
            "rather than merely moved with it.")
        try:
            ablation = _leave_one_out(scorecard_type, equation, baseline,
                                     current, direction, now.ks)
            diagnosis.context["leave_one_out"] = ablation
            diagnosis.claim_strength = ACCOUNTS_FOR
            for name, drop in ablation.items():
                diagnosis.evidence.append(Evidence(
                    subject=name, measure="KS lost when removed",
                    current=drop, baseline=None, change=drop,
                    weight=max(drop, 0.0) * 2.0,
                    reads_as=(
                        f"{name}: removing it changes model KS by "
                        f"{-drop:+.4f}. A variable whose removal costs "
                        "nothing is contributing nothing.")))
        except (fitting.FittingError, metrics_mod.MetricError) as exc:
            diagnosis.limitations.append(
                f"The leave-one-out could not be run ({exc}), so this "
                "answer stays associational.")

    diagnosis.ranked = _rank(diagnosis.evidence)
    diagnosis.limitations.append(
        "Rank ordering here is by weight of measured evidence. Where the "
        "leave-one-out did not run, a variable that moved alongside the "
        "deterioration has not been shown to have caused it — several "
        "variables usually move together when a population does.")
    diagnosis.next_analyses = [
        "Compare the incumbent against the challenger on this month.",
        "Split performance by application channel to test whether this is a "
        "population-mix effect rather than a model effect.",
        "Look at the CSI trend by month to date the change.",
    ]
    return diagnosis


def _leave_one_out(scorecard_type: str, equation: Any,
                   development: pd.DataFrame, current: pd.DataFrame,
                   direction: str, full_ks: float) -> dict[str, float]:
    """§28/§37. Refit without each variable and see what KS is lost."""
    result: dict[str, float] = {}
    names = equation.active_variables
    if len(names) < 3:
        raise fitting.FittingError(
            "a leave-one-out needs at least three variables to leave two "
            "behind")

    for dropped in names:
        kept = [n for n in names if n != dropped]
        columns = [vars_mod.woe_name(n) for n in kept]
        refit = fitting.fit(development, columns, build_mod.TARGET)
        logit = pd.Series(refit.intercept, index=current.index,
                          dtype="float64")
        for name in kept:
            logit = logit + refit.coefficients[vars_mod.woe_name(name)] \
                * current[vars_mod.woe_name(name)].astype("float64")
        # The reduced model is scored on the logit directly. A score mapping
        # is a monotone transform, so KS is identical either way and this
        # avoids inventing a mapping the reduced model never had.
        reduced = current.assign(_reduced=-logit)
        found = metrics_mod.discrimination(
            reduced, score="_reduced", target="actual_default",
            score_direction=direction)
        result[dropped] = round(full_ks - found.ks, 6)
    return result


def _rank(evidence: list[Evidence]) -> list[dict[str, Any]]:
    """Aggregate the evidence per subject, heaviest first."""
    totals: dict[str, dict[str, Any]] = {}
    for item in evidence:
        row = totals.setdefault(item.subject, {
            "subject": item.subject, "weight": 0.0, "measures": []})
        row["weight"] += item.weight
        row["measures"].append(item.measure)
    ranked = sorted(totals.values(), key=lambda r: -r["weight"])
    for index, row in enumerate(ranked, start=1):
        row["rank"] = index
        row["weight"] = round(row["weight"], 6)
    return ranked


# ------------------------------------------- §29/§59 the accuracy case


def accuracy_deterioration(scorecard_type: str, *, month: str = "",
                           model_kind: str = "INCUMBENT",
                           question: str = "") -> Diagnosis:
    """§29's eleven steps, ending on the five-way root-cause challenge."""
    context = dash.resolve(scorecard_type, model_kind=model_kind,
                           month=month)
    diagnosis = Diagnosis(
        question_as_asked=question or "Accuracy has deteriorated. Why?",
        question_as_analysed=(
            "Is the deterioration in discrimination, in calibration, in "
            "stability, in implementation, or in population mix? Those five "
            "have different remediations."),
        context=context.to_dict())

    diagnosis.steps.append(
        f"1. Verify outcome maturity: {context.month} is "
        f"{'matured' if context.outcomes_available else 'NOT matured'}.")
    if context.stability_only:
        diagnosis.limitations.append(
            "No realised outcome exists for this month, so no accuracy "
            "figure can be computed for it at all. Everything below would "
            "be about a different month.")
        diagnosis.next_analyses = [
            f"Run this on {context.latest_matured_month}, the latest fully "
            "matured month."]
        return diagnosis

    current = dash.load_month(scorecard_type, context.month)
    baseline = dash.load_development(scorecard_type)
    equation = build_mod.load_equation(scorecard_type, model_kind)
    suffix = build_mod.OUTPUT_SUFFIX[model_kind]
    direction = (equation.score_mapping.score_direction
                 if equation.score_mapping else "")

    now_cal = metrics_mod.calibration(
        current, pd_column=f"pd_{suffix}", target="actual_default",
        score=f"score_{suffix}", score_direction=direction)
    then_cal = metrics_mod.calibration(
        baseline, pd_column=f"pd_{suffix}", target="actual_default",
        score=f"score_{suffix}", score_direction=direction)
    diagnosis.steps.append(
        f"2. Calibration now against development: observed "
        f"{now_cal.observed_rate:.2%} vs predicted "
        f"{now_cal.predicted_rate:.2%}, against {then_cal.observed_rate:.2%} "
        f"vs {then_cal.predicted_rate:.2%} at development.")

    now_dis = metrics_mod.discrimination(
        current, score=f"score_{suffix}", target="actual_default",
        score_direction=direction)
    then_dis = metrics_mod.discrimination(
        baseline, score=f"score_{suffix}", target="actual_default",
        score_direction=direction)
    diagnosis.steps.append(
        f"3. Discrimination now against development: Gini {now_dis.gini:.4f} "
        f"vs {then_dis.gini:.4f}.")

    score_psi = metrics_mod.psi(baseline, current, score=f"score_{suffix}")
    diagnosis.steps.append(f"4. Score PSI: {score_psi.index:.4f}.")

    worst_csi = 0.0
    worst_name = ""
    for name in equation.active_variables:
        try:
            shift = metrics_mod.csi(baseline, current, variable=name)
        except metrics_mod.MetricError:
            continue
        if shift.index > worst_csi:
            worst_csi, worst_name = shift.index, name
    diagnosis.steps.append(
        f"5. Worst active-variable CSI: {worst_name} at {worst_csi:.4f}."
        if worst_name else "5. No variable CSI could be computed.")

    replication = metrics_mod.replicate(current, equation)
    diagnosis.steps.append(
        f"6. Implementation: {replication.to_dict()['status']}, "
        f"{replication.mismatch_count} mismatch(es).")

    mix = _population_mix(scorecard_type, baseline, current)
    diagnosis.steps.append(
        "7. Population mix: " + (mix["reads_as"] if mix else "not available"))

    # §29's step 11, and the reason the whole diagnostic exists.
    diagnosis.steps.append(
        "8. Challenge which of the five root causes the evidence supports.")
    signals: list[tuple[str, float, str]] = []
    gini_drop = then_dis.gini - now_dis.gini
    signals.append((
        "DISCRIMINATION", max(gini_drop, 0.0) * 4.0,
        f"Gini fell {gini_drop:+.4f} from development."))
    level_gap = abs(now_cal.calibration_in_the_large)
    signals.append((
        "CALIBRATION", level_gap,
        f"Calibration in the large is {now_cal.calibration_in_the_large:+.4f}"
        f" — observed {now_cal.observed_rate:.2%} against predicted "
        f"{now_cal.predicted_rate:.2%}."))
    signals.append((
        "STABILITY", score_psi.index * 3.0 + worst_csi,
        f"Score PSI {score_psi.index:.4f}; worst variable CSI {worst_csi:.4f}"
        f" on {worst_name or 'none'}."))
    signals.append((
        "IMPLEMENTATION", 10.0 if not replication.validated else 0.0,
        replication.to_dict()["status"]))
    signals.append((
        "POPULATION_MIX", (mix or {}).get("weight", 0.0),
        (mix or {}).get("reads_as", "not available")))

    signals.sort(key=lambda row: -row[1])
    diagnosis.ranked = [
        {"rank": index, "root_cause": name, "weight": round(weight, 6),
         "because": because,
         "means": dict(ROOT_CAUSES)[name]}
        for index, (name, weight, because) in enumerate(signals, start=1)]

    for name, weight, because in signals:
        diagnosis.evidence.append(Evidence(
            subject=name, measure="root-cause signal", current=weight,
            baseline=None, change=None, weight=weight, reads_as=because))

    diagnosis.claim_strength = ASSOCIATED
    diagnosis.limitations.append(
        "These five are ranked by the strength of the evidence for each, "
        "not by a causal test. Population mix and calibration in "
        "particular move together: a population that shifted toward a "
        "riskier segment will show both, and separating them needs a "
        "segment-level calibration comparison.")
    diagnosis.next_analyses = [
        "Compare calibration by score band between this month and "
        "development.",
        "Split calibration by the segment whose mix changed most.",
        "Compare the incumbent against the recalibrated candidate, which "
        "corrects level without touching ordering.",
    ]
    return diagnosis


def _population_mix(scorecard_type: str, baseline: pd.DataFrame,
                    current: pd.DataFrame) -> dict[str, Any] | None:
    """§29's step 4. Which segment composition moved most."""
    candidates = ("application_channel", "customer_segment", "product_type",
                  "product", "vintage")
    best: dict[str, Any] | None = None
    for column in candidates:
        if column not in baseline.columns or column not in current.columns:
            continue
        shift = metrics_mod._shift(baseline[column], current[column],
                                   kind="MIX", variable=column)
        if best is None or shift.index > best["index"]:
            top = shift.bins[0] if shift.bins else {}
            best = {
                "variable": column,
                "index": round(shift.index, 6),
                "weight": shift.index * 2.0,
                "largest_move": top,
                "reads_as": (
                    f"{column} composition moved by {shift.index:.4f}; the "
                    f"largest single move is {top.get('bin', '?')} from "
                    f"{top.get('reference_share', 0):.1%} to "
                    f"{top.get('current_share', 0):.1%}."),
            }
    return best


# --------------------------------------------- §30/§31/§60 trends


def odr_trend(scorecard_type: str, *, months: int = 20,
              model_kind: str = "INCUMBENT") -> dict[str, Any]:
    """§30/§60. Observed default rate against average predicted PD."""
    available = [m for m in dash.available_months(scorecard_type)
                 if metrics_mod is not None]
    from backend.scorecard import synthetic as synth

    matured = [m for m in available if synth.matured(m)][-months:]
    suffix = build_mod.OUTPUT_SUFFIX[model_kind]

    rows: list[dict[str, Any]] = []
    for month in matured:
        frame = dash.load_month(scorecard_type, month)
        outcome = frame["actual_default"]
        events = int(outcome.sum())
        rows.append({
            "month": month,
            "observations": len(frame),
            "defaults": events,
            "observed_default_rate": round(float(outcome.mean()), 6),
            "average_predicted_pd": round(
                float(frame[f"pd_{suffix}"].mean()), 6),
            "evidence": metrics_mod.evidence_for(events, len(frame)),
        })
    return {
        "diagnostics_version": DIAGNOSTICS_VERSION,
        "scorecard_type": scorecard_type,
        "model": model_kind,
        "months": rows,
        "months_requested": months,
        "months_returned": len(rows),
        "only_matured": (
            "Only fully matured months appear. A month whose performance "
            "window has not closed has no observed default rate, and "
            "plotting a partial one as though it were complete is how a "
            "trend chart shows a fictitious improvement at its right edge."),
    }


def score_trend(scorecard_type: str, *, months: int = 12,
                model_kind: str = "INCUMBENT") -> dict[str, Any]:
    """§31. Has the score pattern changed? PSI trend and distribution."""
    available = dash.available_months(scorecard_type)[-months:]
    baseline = dash.load_development(scorecard_type)
    suffix = build_mod.OUTPUT_SUFFIX[model_kind]

    rows: list[dict[str, Any]] = []
    for month in available:
        frame = dash.load_month(scorecard_type, month)
        shift = metrics_mod.psi(baseline, frame, score=f"score_{suffix}")
        scores = frame[f"score_{suffix}"].astype(float)
        rows.append({
            "month": month,
            "score_psi": round(shift.index, 6),
            "mean_score": round(float(scores.mean()), 2),
            "median_score": round(float(scores.median()), 2),
            "p10": round(float(scores.quantile(0.10)), 2),
            "p90": round(float(scores.quantile(0.90)), 2),
            "observations": len(frame),
        })
    return {
        "diagnostics_version": DIAGNOSTICS_VERSION,
        "scorecard_type": scorecard_type,
        "model": model_kind,
        "baseline": "DEVELOPMENT REFERENCE",
        "months": rows,
        "available_without_outcomes": (
            "Score stability needs no realised outcome, so this covers "
            "every month including the immature ones."),
    }


def variable_drift(scorecard_type: str, *, month: str = "",
                   model_kind: str = "INCUMBENT",
                   candidates: bool = False) -> dict[str, Any]:
    """§32. CSI for the active variables, or for every candidate."""
    context = dash.resolve(scorecard_type, model_kind=model_kind,
                           month=month)
    current = dash.load_month(scorecard_type, context.month)
    baseline = dash.load_development(scorecard_type)
    equation = build_mod.load_equation(scorecard_type, model_kind)

    names = (vars_mod.names(scorecard_type, scoreable_only=True)
             if candidates else equation.active_variables)
    rows: list[dict[str, Any]] = []
    for name in names:
        try:
            shift = metrics_mod.csi(baseline, current, variable=name)
        except metrics_mod.MetricError as exc:
            rows.append({"variable": name, "csi": None, "why": str(exc),
                         "in_active_model": name in
                         equation.active_variables})
            continue
        rows.append({
            "variable": name,
            "csi": round(shift.index, 6),
            "in_active_model": name in equation.active_variables,
            "largest_move": shift.bins[0] if shift.bins else None,
        })
    rows.sort(key=lambda row: -(row.get("csi") or -1))
    return {
        "diagnostics_version": DIAGNOSTICS_VERSION,
        "scope": "ALL CANDIDATES" if candidates else "ACTIVE MODEL VARIABLES",
        "month": context.month,
        "variables": rows,
        "measurable": sum(1 for row in rows if row.get("csi") is not None),
        "why_some_are_absent": (
            "A CSI is computed over a variable's approved bins. A candidate "
            "that was never binned has none, so it has no CSI — which is a "
            "fact about the specification, not a missing number."),
    }
