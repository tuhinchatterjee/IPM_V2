"""Building the Saudi SME universe onto the Parquet lake. §6.2.

Three datasets, one binning specification, and the rule that the
specification is fitted once — on the development sample — and then only
ever applied.

Why the binning is fitted here and not per month
--------------------------------------------------
`binning.Spec.apply` is a lookup. Fitting it again on a validation month
would recompute the weight-of-evidence against that month's own outcome,
which makes every month look well-behaved by construction and makes CSI
compare a distribution to itself. The whole point of a characteristic
stability index is to ask whether the population has moved *relative to the
specification the model actually uses*, and there is only one way to keep
that question answerable: fit once, out of time, and apply everywhere.

That is also why `csi` in `metrics.py` refuses to work on raw values and
insists on the `_bin` columns. The refusal is the feature.

What gets written
-------------------
* `sme_scorecard_monthly_validation` — one row per application per cohort,
  partitioned by `cohort_month`. The scored population with its realised
  outcome where the window has closed.
* `sme_scorecard_development_reference` — the out-of-time development
  sample, the reference population every stability test compares against.
* `sme_scorecard_decisions` — the policy view: decision, override, grade,
  and the outcome of the overridden cases.

All three are restricted to the Scorecard Validation environment by
`backend/scorecard/domains.py`, and every row carries
`origin = SYNTHETIC_DEMO`.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

import pandas as pd

from backend.scorecard import binning
from backend.scorecard.sme import synthetic as synth
from backend.scorecard.sme import variables as sme_vars

logger = logging.getLogger(__name__)

BUILD_VERSION = "1.0.0"

MONTHLY = "sme_scorecard_monthly_validation"
DEVELOPMENT = "sme_scorecard_development_reference"
DECISIONS = "sme_scorecard_decisions"

DATASETS: tuple[str, ...] = (MONTHLY, DEVELOPMENT, DECISIONS)

#: The Data Builder domain these datasets are installed under.
DOMAIN = {
    "name": "Saudi SME Scorecard",
    "description": (
        "Application scorecard for Saudi small and medium enterprises: the "
        "scored population, its realised twelve-month outcome, and the "
        "credit decisions taken on it. Generated demonstration data."),
}

#: The variables the champion and the challenger actually read. Binned, and
#: therefore carrying `_bin` and `_woe` columns; the rest of the ninety are
#: carried raw for diagnostics and monitoring.
#:
#: Kept short deliberately. §11 of the retail dictionary makes the same
#: point: a dataset carries dozens of candidates and an active scorecard uses
#: five or six of them. Confusing the two makes "which variables are in the
#: model" unanswerable.
CHAMPION_VARIABLES: tuple[str, ...] = (
    "debt_to_ebitda", "dscr", "years_since_registration", "max_dpd_12m",
    "commercial_bureau_score_proxy",
)

CHALLENGER_VARIABLES: tuple[str, ...] = CHAMPION_VARIABLES + (
    "bank_credits_to_declared_sales", "payroll_regularity_score",
    "balance_volatility",
)

#: Everything binned across both models, in a stable order.
BINNED_VARIABLES: tuple[str, ...] = CHALLENGER_VARIABLES

SPEC_VERSION = "SME-BIN-1.0.0"


def _kinds() -> dict[str, str]:
    """What each binned variable is, in the binner's vocabulary."""
    return {name: sme_vars.get(name).kind for name in BINNED_VARIABLES}


_SPEC: binning.Spec | None = None


def spec() -> binning.Spec:
    """The approved binning specification, fitted once on development.

    Cached at module level rather than refitted per call. The cache is not
    an optimisation — refitting would give the same answer, because the
    development sample is deterministic — it is a statement that there is
    exactly one approved specification, and a second one appearing anywhere
    would be the defect.
    """
    global _SPEC
    if _SPEC is None:
        frame = synth.build(synth.DEVELOPMENT_MONTHS, development=True)
        _SPEC = binning.fit(
            frame, scorecard_type=sme_vars.SME_SCORECARD,
            spec_version=SPEC_VERSION, target="actual_default_12m",
            kinds=_kinds(),
            development_population=(
                f"{synth.DEVELOPMENT_MONTHS[0]}..{synth.DEVELOPMENT_MONTHS[-1]}"))
    return _SPEC


def _binned(frame: pd.DataFrame) -> pd.DataFrame:
    """Add the approved bin and WoE columns. A lookup, never a fit."""
    return spec().apply(frame, variables=list(BINNED_VARIABLES))


# ------------------------------------------------------------------- writing


def _root() -> Path:
    from backend.config import settings

    return Path(settings.analytics_dir)


def _write_partition(dataset: str, key: str, frame: pd.DataFrame,
                     partition_field: str) -> int:
    where = _root() / dataset / f"{partition_field}={key}"
    where.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(where / "part-0.parquet", index=False)
    return len(frame)


def _clear(dataset: str) -> None:
    where = _root() / dataset
    if where.exists():
        shutil.rmtree(where)


def build(*, months: tuple[str, ...] = synth.COHORT_MONTHS,
          rebuild: bool = True) -> dict[str, Any]:
    """Write the three datasets. Deterministic for a given month list.

    `rebuild` removes what is there first. A partial write over an existing
    build would leave partitions from two different generator versions side
    by side, which is the kind of state that produces a metric nobody can
    reproduce.
    """
    if rebuild:
        for dataset in DATASETS:
            _clear(dataset)

    written = {d: 0 for d in DATASETS}

    # The development reference, first: everything else is validated
    # against it, and a build that failed here should fail before it has
    # written a validation month that has nothing to compare to.
    for month in synth.DEVELOPMENT_MONTHS:
        frame = _binned(synth.cohort(month, development=True))
        written[DEVELOPMENT] += _write_partition(
            DEVELOPMENT, month, frame, "cohort_month")

    for month in months:
        frame = _binned(synth.cohort(month))
        written[MONTHLY] += _write_partition(
            MONTHLY, month, frame, "cohort_month")
        written[DECISIONS] += _write_partition(
            DECISIONS, month, _decisions(frame), "cohort_month")

    logger.info("[sme] built %s", {k: f"{v:,}" for k, v in written.items()})
    return {
        "build_version": BUILD_VERSION,
        "synthetic_version": synth.SYNTHETIC_VERSION,
        "spec_version": SPEC_VERSION,
        "origin": synth.ORIGIN,
        "rows": written,
        "cohorts": len(months),
        "matured_cohorts": len(synth.matured_months(months)),
        "development_months": len(synth.DEVELOPMENT_MONTHS),
        "binned_variables": list(BINNED_VARIABLES),
        "root": str(_root()),
    }


#: The columns the decisions dataset carries. A narrow view on purpose: §17
#: asks about usage, overrides and policy, and a decision file that repeats
#: every predictor invites somebody to answer a model question from it.
DECISION_COLUMNS: tuple[str, ...] = (
    "sme_obligor_id", "application_id", "facility_id", "cohort_month",
    "snapshot_month", "score_date", "performance_window_end",
    "performance_horizon_months", "is_matured", "origin",
    "enterprise_size_class_proxy", "economic_sector", "region",
    "champion_score", "champion_pd_12m", "final_risk_grade",
    "approval_decision", "override_flag", "override_direction",
    "actual_default_12m",
)


def _decisions(frame: pd.DataFrame) -> pd.DataFrame:
    made = frame[list(DECISION_COLUMNS)].copy()
    #: §17 needs a reason on an override, and a reason that is always the
    #: same teaches nothing. Derived from where the override sits rather
    #: than drawn independently, so the reason and the score agree.
    made["override_reason_code"] = _reason_codes(made)
    return made


def _reason_codes(frame: pd.DataFrame) -> list[str]:
    out: list[str] = []
    for flag, direction, score in zip(frame["override_flag"],
                                      frame["override_direction"],
                                      frame["champion_score"], strict=True):
        if not int(flag):
            out.append("")
        elif direction == "UPWARD":
            out.append("REL_RELATIONSHIP_HISTORY" if score >= 580
                       else "REL_SECURITY_OFFERED")
        else:
            out.append("SECTOR_CONCENTRATION")
    return out


def summary() -> dict[str, Any]:
    """What exists, for a report or a data dictionary."""
    return {
        "build_version": BUILD_VERSION,
        "domain": DOMAIN["name"],
        "datasets": list(DATASETS),
        "cohorts": len(synth.COHORT_MONTHS),
        "matured_cohorts": len(synth.matured_months()),
        "data_end_month": synth.DATA_END_MONTH,
        "performance_horizon_months": synth.DEFAULT_HORIZON_MONTHS,
        "variables_declared": len(sme_vars.SME),
        "variables_binned": len(BINNED_VARIABLES),
        "champion_variables": list(CHAMPION_VARIABLES),
        "challenger_variables": list(CHALLENGER_VARIABLES),
        "spec_version": SPEC_VERSION,
        "origin": synth.ORIGIN,
        "not_client_data": (
            "Every row is generated. It is marked synthetic in the catalogue "
            "and every row carries origin = SYNTHETIC_DEMO. It describes no "
            "real business and no real bank's book."),
    }


__all__ = [
    "BINNED_VARIABLES", "BUILD_VERSION", "CHALLENGER_VARIABLES",
    "CHAMPION_VARIABLES", "DATASETS", "DECISIONS", "DEVELOPMENT", "DOMAIN",
    "MONTHLY", "SPEC_VERSION", "build", "spec", "summary",
]
