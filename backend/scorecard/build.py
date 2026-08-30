"""
Building the retail scorecard universe on disk. §3-§14, §76, §77, §91.

Generates the two domains, fits the frozen binning on an out-of-time
development population, estimates three models per scorecard, scores every
validation month with all three, and writes the lot to the Parquet lake in
the layout the Data Access Layer already reads.

The order matters and is the point
-----------------------------------
1. Generate the **development** population (2022), which no validation month
   overlaps.
2. Fit the **binning / WoE specification** on it, and freeze it.
3. Fit the **model coefficients** on the same population, through that spec.
4. Generate each **validation month** and score it by *looking up* the frozen
   WoE and applying the fitted coefficients.

Doing it in any other order is the mistake this module is built to avoid.
Fitting bins on the validation months would make the model fit them by
construction, and every stability metric would come back flat because the
measurement moved with the data.

Which variables each model uses
--------------------------------
Chosen, not searched. §52's model-design section has to answer "why is this
variable in the model", and a stepwise search makes that unanswerable. The
incumbent uses what a 2022 development team would plausibly have picked; the
challenger swaps the enquiry count — which decays over the window — for two
factors that hold up; the recalibrated candidate is the incumbent's ordering
with the level refitted.
"""

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from backend.scorecard import binning as binning_mod
from backend.scorecard import equation as equation_mod
from backend.scorecard import fitting
from backend.scorecard import synthetic as synth
from backend.scorecard import variables as vars_mod

logger = logging.getLogger(__name__)

BUILD_VERSION = "1.0.0"

APP = vars_mod.APPLICATION_SCORECARD
BEH = vars_mod.BEHAVIORAL_SCORECARD

#: §3. The two first-class Data Builder domains.
DOMAINS: dict[str, dict[str, str]] = {
    APP: {
        "name": "Retail Application Scorecard",
        "description": (
            "Application-time retail credit scoring: the population scored at "
            "the point of decision, the approved model specification, and the "
            "twelve-month outcomes those decisions produced."),
        "owner": "Retail Model Risk",
    },
    BEH: {
        "name": "Retail Behavioral Scorecard",
        "description": (
            "Monthly behavioral scoring of the live retail book: account "
            "snapshots, the approved model specification, and the "
            "twelve-month outcomes that followed each snapshot."),
        "owner": "Retail Model Risk",
    },
}

#: §4. The governed families under each domain.
FAMILIES: dict[str, tuple[str, ...]] = {
    APP: (
        "APPLICATION SCORECARD DEVELOPMENT REFERENCE",
        "APPLICATION SCORECARD MONTHLY VALIDATION",
        "APPLICATION SCORECARD MODEL SPECIFICATION",
        "APPLICATION SCORECARD WOE / BINNING SPECIFICATION",
        "APPLICATION SCORECARD OUTCOMES",
        "APPLICATION SCORECARD OVERRIDES / DECISIONS",
        "APPLICATION SCORECARD DATA QUALITY",
    ),
    BEH: (
        "BEHAVIORAL SCORECARD DEVELOPMENT REFERENCE",
        "BEHAVIORAL SCORECARD MONTHLY VALIDATION",
        "BEHAVIORAL SCORECARD MODEL SPECIFICATION",
        "BEHAVIORAL SCORECARD WOE / BINNING SPECIFICATION",
        "BEHAVIORAL SCORECARD OUTCOMES",
        "BEHAVIORAL SCORECARD ACCOUNT SNAPSHOTS",
        "BEHAVIORAL SCORECARD DATA QUALITY",
    ),
}

#: §11/§12. The seeded model variable sets. Six each, chosen for a reason
#: that the model-design section can state.
MODEL_VARIABLES: dict[str, dict[str, tuple[str, ...]]] = {
    APP: {
        # What a 2022 development team would plausibly have selected: the
        # bureau's own view, affordability, stability of employment, and the
        # two bureau behaviours that were strongest in that window.
        "INCUMBENT": ("bureau_score", "debt_burden_ratio",
                      "employment_tenure_months", "bureau_max_dpd_12m",
                      "bureau_enquiries_6m", "credit_card_utilisation"),
        # The challenger drops the enquiry count — which decays across the
        # window — for loan-to-income and the age of the bureau file.
        "CHALLENGER": ("bureau_score", "debt_burden_ratio",
                       "employment_tenure_months", "bureau_max_dpd_12m",
                       "loan_to_income", "bureau_oldest_trade_months"),
        # Same variables as the incumbent. Only the level is refitted.
        "RECALIBRATED": ("bureau_score", "debt_burden_ratio",
                         "employment_tenure_months", "bureau_max_dpd_12m",
                         "bureau_enquiries_6m", "credit_card_utilisation"),
    },
    BEH: {
        "INCUMBENT": ("max_dpd_6m", "utilisation_pct",
                      "average_payment_ratio_3m", "bureau_score_latest",
                      "missed_payment_count_6m", "months_on_book"),
        "CHALLENGER": ("max_dpd_6m", "average_utilisation_6m",
                       "minimum_payment_ratio_6m", "bureau_score_latest",
                       "salary_credit_stability", "times_dpd_30plus_6m"),
        "RECALIBRATED": ("max_dpd_6m", "utilisation_pct",
                         "average_payment_ratio_3m", "bureau_score_latest",
                         "missed_payment_count_6m", "months_on_book"),
    },
}

MODEL_KINDS: tuple[str, ...] = ("INCUMBENT", "CHALLENGER", "RECALIBRATED")

#: §14's output naming.
OUTPUT_SUFFIX: dict[str, str] = {
    "INCUMBENT": "incumbent",
    "CHALLENGER": "challenger",
    "RECALIBRATED": "recalibrated",
}

#: §13's score mapping. Points to double the odds, and a declared direction.
SCORE_MAPPING = {
    "base_score": 600.0, "pdo": 20.0, "base_odds": 50.0,
    "score_direction": equation_mod.HIGHER_SCORE_IS_BETTER,
    "min_score": 300.0, "max_score": 900.0,
}

TARGET = "actual_default"

#: §39. The default definition, reported prominently rather than buried.
DEFAULT_DEFINITION: dict[str, Any] = {
    "horizon_months": synth.DEFAULT_HORIZON_MONTHS,
    "trigger": "90 days past due, or a write-off or default flag, "
               "whichever is earlier",
    "dpd_threshold_days": 90,
    "write_off_treated_as_default": True,
    "restructure_treatment": (
        "A distressed restructure is treated as a default event at the "
        "restructure date."),
    "cure_logic": (
        "An account that returns below 90 days past due and stays there for "
        "three consecutive months is cured, and is not counted as a default "
        "for the cohort it cured in."),
    "aggregation": (
        "Application scorecard: one outcome per application. Behavioral "
        "scorecard: one outcome per account per snapshot month."),
    "origin": synth.ORIGIN,
}


def _lake_root() -> Path:
    from backend.config import settings

    return settings.analytics_dir


def dataset_name(scorecard_type: str, kind: str) -> str:
    prefix = ("retail_application_scorecard" if scorecard_type == APP
              else "retail_behavioral_scorecard")
    return f"{prefix}_{kind}"


def spec_root() -> Path:
    return _lake_root().parent / "scorecard"


# ------------------------------------------------------------------ writing


def _write_partitioned(frame: pd.DataFrame, directory: Path,
                       period_field: str) -> int:
    if directory.exists():
        shutil.rmtree(directory)
    directory.mkdir(parents=True, exist_ok=True)
    written = 0
    for period, chunk in frame.groupby(period_field, observed=True):
        part = directory / f"{period_field}={period}"
        part.mkdir(parents=True, exist_ok=True)
        chunk.to_parquet(part / "data.parquet", index=False)
        written += 1
    return written


def _write_json(payload: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str),
                    encoding="utf-8")


# ------------------------------------------------------------------ scoring


def _kinds_for(scorecard_type: str, names: tuple[str, ...]) -> dict[str, str]:
    return {name: vars_mod.get(scorecard_type, name).kind for name in names}


def _model_columns(scorecard_type: str) -> list[str]:
    """The union of every model's variables — what needs a WoE column."""
    union: list[str] = []
    for names in MODEL_VARIABLES[scorecard_type].values():
        for name in names:
            if name not in union:
                union.append(name)
    return union


def score_frame(frame: pd.DataFrame, equations: dict[str, equation_mod.Equation],
                spec: binning_mod.Spec) -> pd.DataFrame:
    """Apply the frozen WoE and every model's equation. §14's outputs."""
    columns = sorted({t.variable for eq in equations.values()
                      for t in eq.terms})
    scored = spec.apply(frame, variables=columns)

    for kind, eq in equations.items():
        suffix = OUTPUT_SUFFIX[kind]
        logit = pd.Series(eq.intercept, index=scored.index, dtype="float64")
        for term in eq.terms:
            logit = logit + term.coefficient * scored[term.column()].astype(
                "float64")
        scored[f"logit_{suffix}"] = logit.astype("float32")
        pd_values = 1.0 / (1.0 + (-logit).apply(_safe_exp))
        scored[f"pd_{suffix}"] = pd_values.astype("float32")
        if eq.score_mapping is not None:
            scored[f"score_{suffix}"] = logit.apply(
                eq.score_mapping.score).astype("float32")
    return scored


def _safe_exp(x: float) -> float:
    import math

    if x > 700:
        return float("inf")
    if x < -700:
        return 0.0
    return math.exp(x)


# ------------------------------------------------------------------- build


@dataclass
class BuildResult:
    scorecard_type: str
    counts: synth.Counts
    spec_version: str
    models: dict[str, dict[str, Any]]
    datasets: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "build_version": BUILD_VERSION,
            "scorecard_type": self.scorecard_type,
            "counts": self.counts.to_dict(),
            "binning_spec_version": self.spec_version,
            "models": self.models,
            "datasets": dict(self.datasets),
        }


#: §74. How many recent matured months a recalibration is fitted on. The
#: recalibrated candidate exists because the incumbent's *level* has drifted
#: since development, so it has to be refitted on experience that contains
#: the drift. Refitting it on the development population — the sample the
#: incumbent was already fitted on — returns a slope of 1.0 and an intercept
#: of 0 by construction, producing a "candidate" identical to the incumbent.
RECALIBRATION_WINDOW_MONTHS = 6


def _build_equations(scorecard_type: str, development: pd.DataFrame,
                     spec: binning_mod.Spec,
                     recalibration: pd.DataFrame | None = None) -> tuple[
                         dict[str, equation_mod.Equation], dict[str, Any]]:
    """Fit the three models.

    Incumbent and challenger on the development population; the recalibrated
    candidate on recent matured experience, because that is the only place
    the drift it exists to correct can be observed.
    """
    prepared = spec.apply(development,
                          variables=_model_columns(scorecard_type))
    equations: dict[str, equation_mod.Equation] = {}
    diagnostics: dict[str, Any] = {}

    for kind in ("INCUMBENT", "CHALLENGER"):
        names = MODEL_VARIABLES[scorecard_type][kind]
        columns = [vars_mod.woe_name(n) for n in names]
        result = fitting.fit(prepared, columns, TARGET)
        equations[kind] = equation_mod.Equation(
            model_name=f"{scorecard_type}_{kind}",
            scorecard_type=scorecard_type,
            intercept=result.intercept,
            terms=[equation_mod.Term(variable=n,
                                     coefficient=result.coefficients[
                                         vars_mod.woe_name(n)])
                   for n in names],
            binning_spec_version=spec.spec_version,
            score_mapping=equation_mod.ScoreMapping.from_dict(SCORE_MAPPING),
            output_prefix=OUTPUT_SUFFIX[kind])
        diagnostics[kind] = result.to_dict()

    # §74: the recalibrated candidate refits level, not ordering. Fitting a
    # one-variable logistic on the incumbent's own logit is exactly that —
    # a monotone transformation, so every rank statistic is unchanged by
    # construction and the level is free to move.
    incumbent = equations["INCUMBENT"]
    basis = prepared if recalibration is None else spec.apply(
        recalibration, variables=_model_columns(scorecard_type))
    logit = pd.Series(incumbent.intercept, index=basis.index,
                      dtype="float64")
    for term in incumbent.terms:
        logit = logit + term.coefficient * basis[term.column()].astype(
            "float64")
    recal_frame = basis.assign(_incumbent_logit=logit)
    recal = fitting.recalibrate(recal_frame, "_incumbent_logit", TARGET)
    slope = recal.coefficients["_incumbent_logit"]
    equations["RECALIBRATED"] = equation_mod.Equation(
        model_name=f"{scorecard_type}_RECALIBRATED",
        scorecard_type=scorecard_type,
        intercept=recal.intercept + slope * incumbent.intercept,
        terms=[equation_mod.Term(variable=t.variable,
                                 coefficient=t.coefficient * slope)
               for t in incumbent.terms],
        binning_spec_version=spec.spec_version,
        score_mapping=equation_mod.ScoreMapping.from_dict(SCORE_MAPPING),
        output_prefix=OUTPUT_SUFFIX["RECALIBRATED"])
    diagnostics["RECALIBRATED"] = {
        **recal.to_dict(),
        "recalibrated_from": incumbent.model_name,
        "recalibration_basis": (
            "development population" if recalibration is None else
            f"the most recent {RECALIBRATION_WINDOW_MONTHS} matured "
            f"validation months ({len(recalibration):,} rows)"),
        "slope_on_incumbent_logit": round(slope, 8),
        "what_it_can_and_cannot_change": (
            "A monotone transformation of the incumbent's logit. It moves "
            "the level of predicted risk and cannot move the ordering, so "
            "AUC, Gini and KS are unchanged by construction."),
    }
    return equations, diagnostics


def build(scorecard_type: str, *, months: tuple[str, ...] | None = None,
          write: bool = True) -> BuildResult:
    """Generate, fit, score and persist one scorecard's universe."""
    months = months or (synth.APPLICATION_MONTHS if scorecard_type == APP
                        else synth.BEHAVIORAL_MONTHS)

    logger.info("scorecard build: generating %s development population",
                scorecard_type)
    if scorecard_type == APP:
        development = synth.application_development()
    else:
        development = synth.behavioral_development()

    columns = _model_columns(scorecard_type)
    spec = binning_mod.fit(
        development, scorecard_type=scorecard_type,
        spec_version=f"{scorecard_type.lower()}-woe-1.0.0",
        target=TARGET, kinds=_kinds_for(scorecard_type, tuple(columns)),
        development_population=(
            f"{synth.DEVELOPMENT_MONTHS[0]} to "
            f"{synth.DEVELOPMENT_MONTHS[-1]} ({len(development):,} rows)"))

    panel = synth.behavioral_panel() if scorecard_type == BEH else None

    # The recalibration window: the most recent matured months, generated
    # before scoring so the candidate exists when the months are written.
    matured_months = [m for m in months if synth.matured(m)]
    window = matured_months[-RECALIBRATION_WINDOW_MONTHS:]
    recalibration = pd.concat(
        [(synth.application_month(m, offset=months.index(m))
          if scorecard_type == APP
          else synth.behavioral_month(m, offset=months.index(m), panel=panel))
         for m in window],
        ignore_index=True) if window else None

    equations, diagnostics = _build_equations(scorecard_type, development,
                                              spec, recalibration)

    counts = synth.Counts(scorecard_type=scorecard_type, months=list(months))
    root = _lake_root() / dataset_name(scorecard_type, "monthly_validation")
    if write and root.exists():
        shutil.rmtree(root)
    if write:
        root.mkdir(parents=True, exist_ok=True)

    period_field = ("application_month" if scorecard_type == APP
                    else "observation_month")

    for offset, month in enumerate(months):
        raw = (synth.application_month(month, offset=offset)
               if scorecard_type == APP
               else synth.behavioral_month(month, offset=offset, panel=panel))
        scored = score_frame(raw, equations, spec)
        counts.rows_by_month[month] = len(scored)
        outcome = scored[TARGET]
        counts.defaults_by_month[month] = (
            int(outcome.sum()) if outcome.notna().all() else 0)
        if bool(scored["matured_flag"].iloc[0]):
            counts.matured_months.append(month)
        if write:
            part = root / f"{period_field}={month}"
            part.mkdir(parents=True, exist_ok=True)
            scored.to_parquet(part / "data.parquet", index=False)
        logger.info("scorecard build: %s %s -> %d rows", scorecard_type,
                    month, len(scored))

    datasets: dict[str, str] = {
        "monthly_validation": str(root),
    }

    if write:
        development_scored = score_frame(development, equations, spec)
        dev_root = _lake_root() / dataset_name(scorecard_type,
                                               "development_reference")
        dev_field = ("application_month" if scorecard_type == APP
                     else "observation_month")
        _write_partitioned(development_scored, dev_root, dev_field)
        datasets["development_reference"] = str(dev_root)

        _write_json(spec.to_dict(),
                    spec_root() / f"{scorecard_type.lower()}_binning.json")
        _write_json(
            {
                "scorecard_type": scorecard_type,
                "default_definition": DEFAULT_DEFINITION,
                "score_mapping": SCORE_MAPPING,
                "models": {
                    kind: {
                        "equation": eq.to_dict(),
                        "fit": diagnostics[kind],
                        "active_variables": list(
                            MODEL_VARIABLES[scorecard_type][kind]),
                    }
                    for kind, eq in equations.items()
                },
            },
            spec_root() / f"{scorecard_type.lower()}_models.json")

    return BuildResult(
        scorecard_type=scorecard_type, counts=counts,
        spec_version=spec.spec_version,
        models={kind: eq.to_dict() for kind, eq in equations.items()},
        datasets=datasets)


def load_spec(scorecard_type: str) -> binning_mod.Spec:
    path = spec_root() / f"{scorecard_type.lower()}_binning.json"
    if not path.exists():
        raise FileNotFoundError(
            f"no binning specification at {path}. Run "
            "scripts/build_retail_scorecards.py first — scoring without an "
            "approved specification would mean inventing the mapping.")
    return binning_mod.Spec.from_dict(json.loads(path.read_text("utf-8")))


def load_models(scorecard_type: str) -> dict[str, Any]:
    path = spec_root() / f"{scorecard_type.lower()}_models.json"
    if not path.exists():
        raise FileNotFoundError(f"no model specification at {path}")
    return json.loads(path.read_text("utf-8"))


def load_equation(scorecard_type: str, kind: str) -> equation_mod.Equation:
    models = load_models(scorecard_type)
    if kind not in models["models"]:
        raise KeyError(
            f"{kind} is not a seeded model of the {scorecard_type} "
            f"scorecard; known: {', '.join(models['models'])}")
    return equation_mod.Equation.from_dict(
        models["models"][kind]["equation"])
