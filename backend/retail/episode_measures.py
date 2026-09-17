"""Every figure the nine episodes' cards, drawers, threads and exports read.

Computed here once, for the reason `anb_demo` gives for the tenth: a card that
says a share doubled and an answer three questions later that says it rose by a
third are not a disagreement about presentation. They are two readings of the
same book, and a reader has no way to tell which one is wrong. So the card, the
drawer, the thread's six steps, the Borrower 360 list, the workbook and the
What-If baseline all come through these functions, and they cannot disagree
because there is only one of each.

The predicates live in `episodes.py`, not here. This module EVALUATES them
against the published columns at the declared date. That separation is the
point: the predicate is a written rule a reader can see in the breadcrumb and
in the exported workbook, and evaluating it is mechanical.

Three populations, and they are not the same population
-------------------------------------------------------
* **Eligible** — the denominator. Everything the case's rate is a rate OF.
* **Issue** — eligible facilities the predicate fires on at this date.
* **Pocket** — the named concentration inside the eligible population, whose
  incidence is compared against the incidence outside it.

The comparator is a fourth thing again, and which fourth thing depends on the
story. Alpha's is the same population a month earlier. The two outcome-window
stories compare a matured vintage against an earlier vintage matched at the
same age. The other seven compare the pocket against the matched eligible
population outside it at the same date. Each of those is written down beside
the figure it produces, because a comparator nobody can see is a comparator
nobody can check.

Everything read here is SYNTHETIC demonstration data.
"""

from __future__ import annotations

import glob
import logging
from functools import lru_cache
from typing import Any, Sequence

import numpy as np
import pandas as pd

from backend.retail import episodes as ep
from backend.retail import metrics_contract as mc

logger = logging.getLogger(__name__)

BOOK = "retail_facility_month"

#: How the comparator is formed, per case. Named rather than assumed.
PRIOR_MONTH = "prior_month"
OUTSIDE_POCKET = "matched_outside_pocket"
HISTORICAL = "matched_historical_cohort"

COMPARATOR_BASIS: dict[str, str] = {
    "C01": PRIOR_MONTH,
    "C02": HISTORICAL,
    "C03": OUTSIDE_POCKET,
    "C04": OUTSIDE_POCKET,
    "C05": OUTSIDE_POCKET,
    "C06": OUTSIDE_POCKET,
    "C07": OUTSIDE_POCKET,
    "C08": OUTSIDE_POCKET,
    "C09": OUTSIDE_POCKET,
    "C10": HISTORICAL,
}

COMPARATOR_LABEL: dict[str, str] = {
    PRIOR_MONTH: "the same population one month earlier",
    OUTSIDE_POCKET: ("the matched eligible population outside the named "
                     "pocket, at the same date"),
    HISTORICAL: ("an earlier cohort matched at the same months on book, "
                 "before this episode began"),
}

#: Which half of a two-vintage eligible population is under investigation.
CURRENT_COHORT = {"C02": "CURRENT_MATURE_MOB6",
                  "C10": "CURRENT_OBSERVATION_WINDOW"}
HISTORICAL_COHORT = {"C02": "HISTORICAL_MATURE_MOB6",
                     "C10": "HISTORICAL_OBSERVATION_WINDOW"}

#: Columns every case needs whatever its own rule reads.
CORE_COLUMNS: tuple[str, ...] = (
    "facility_id", "customer_id", "product_code", "product_subsegment",
    "episode_code", "episode_role", "episode_pocket_flag",
    "episode_evidence_state", "vintage_cohort",
    "dpd", "dpd_bucket", "ifrs9_stage", "gross_carrying_amount_sar",
    "ead_base_sar", "ecl_weighted_sar", "lgd_base", "pd_pit_12m_base",
    "pd_pit_lifetime_base", "behavioural_score", "behavioural_score_band",
    "application_score_band", "app_score_value", "origination_score_band",
    "credit_impaired_flag", "current_default_flag",
)

#: Columns outside the episodes' own set that their rules and drawers read.
EXTRA_COLUMNS: tuple[str, ...] = (
    "balance_buffer_months", "disposable_income_sar",
    "monthly_total_credit_obligations_sar",
    "verified_total_monthly_income_sar", "recovery_delay_months",
    "utilisation_ratio", "collateral_value_current_sar",
    "employment_status", "employer_id", "employer_sector", "region",
    "origination_channel", "origination_date", "origination_vintage",
    "balloon_payment_sar", "months_to_balloon", "balloon_band",
    "vehicle_age_months", "vehicle_new_used", "property_type",
    "housing_support_type", "restructured_flag", "restructure_date",
    "employment_tenure_months", "origination_employment_tenure_months",
    "app_predicted_pd_12m", "behavioural_predicted_pd_12m",
    "previous_month_dpd", "previous_month_stage", "sicr_flag",
)

_OPS = {
    "==": lambda s, v: s == v,
    "!=": lambda s, v: s != v,
    ">=": lambda s, v: pd.to_numeric(s, errors="coerce") >= v,
    "<=": lambda s, v: pd.to_numeric(s, errors="coerce") <= v,
    ">": lambda s, v: pd.to_numeric(s, errors="coerce") > v,
    "<": lambda s, v: pd.to_numeric(s, errors="coerce") < v,
    "in": lambda s, v: s.isin(list(v)),
}


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def _analytics_dir() -> str:
    from backend.config import settings

    return str(settings.analytics_dir)


@lru_cache(maxsize=1)
def months() -> tuple[str, ...]:
    return tuple(sorted(
        path.rsplit("=", 1)[-1]
        for path in glob.glob(f"{_analytics_dir()}/{BOOK}/reporting_month=*")))


def latest_month() -> str:
    found = months()
    return found[-1] if found else ""


def resolve(month: str = "") -> str:
    """A published month, or "" if the one asked for is not one.

    Never falls back to the latest month. Answering a different question under
    the heading of the question asked is the failure this module is arranged
    to avoid.
    """
    found = months()
    if not found:
        return ""
    at = str(month or "").strip()
    return found[-1] if not at else (at if at in found else "")


def previous_month(month: str = "") -> str:
    found = months()
    at = month or latest_month()
    if at in found:
        index = found.index(at)
        return found[index - 1] if index > 0 else ""
    return ""


@lru_cache(maxsize=24)
def _read(month: str, columns: tuple[str, ...]) -> pd.DataFrame:
    paths = sorted(glob.glob(
        f"{_analytics_dir()}/{BOOK}/reporting_month={month}/*.parquet"))
    if not paths:
        return pd.DataFrame(columns=list(columns))
    try:
        return pd.read_parquet(paths[0], columns=list(columns))
    except (KeyError, ValueError) as exc:
        # A column the episodes add, read against a book built before they
        # existed. Said plainly rather than returning a frame that silently
        # lacks the thing the rule is written against.
        raise MissingEpisodeColumns(
            f"{month} does not carry the episode columns this reads "
            f"({exc}). The book was built before the episodes existed; "
            f"rebuild it with scripts/build_retail_demo.py.") from exc


class MissingEpisodeColumns(RuntimeError):
    """The book predates the episodes. Never masked as an empty population."""


def frame(month: str = "", columns: Sequence[str] = ()) -> pd.DataFrame:
    """One month, projected to what the episodes actually read.

    The episodes' own columns are always included. They are forty-seven of the
    book's near-six-hundred, they are the columns every rule, drawer panel and
    exported sheet is written against, and a caller that had to list them
    would list them differently in each of the six places that read them —
    which is how a drawer and a workbook end up describing the same cohort
    with different fields.
    """
    at = resolve(month)
    if not at:
        return pd.DataFrame()
    from backend.retail.episode_overlay import COLUMNS as EPISODE_COLUMNS

    want = tuple(dict.fromkeys(
        [*CORE_COLUMNS, *EPISODE_COLUMNS, *EXTRA_COLUMNS, *columns]))
    return _read(at, want)


def available() -> bool:
    if not months():
        return False
    try:
        return not frame().empty
    except MissingEpisodeColumns:
        return False


def reset_cache() -> None:
    months.cache_clear()
    _read.cache_clear()


# ---------------------------------------------------------------------------
# The three populations
# ---------------------------------------------------------------------------


def predicate_columns(case_id: str) -> tuple[str, ...]:
    return tuple(c["field"] for c in ep.predicate(case_id)["clauses"])


def eligible_mask(data: pd.DataFrame, case_id: str) -> np.ndarray:
    """The denominator: everything the case's rate is a rate of."""
    if data.empty:
        return np.zeros(0, dtype=bool)
    if case_id == "C01":
        mask = (data["product_subsegment"] == "ALPHA").to_numpy().copy()
    else:
        mask = (data["episode_code"] == case_id).to_numpy().copy()
    current = CURRENT_COHORT.get(case_id)
    if current:
        mask &= (data["vintage_cohort"] == current).to_numpy()
    return mask


def historical_mask(data: pd.DataFrame, case_id: str) -> np.ndarray:
    """The matched earlier cohort, for the two outcome-window stories."""
    label = HISTORICAL_COHORT.get(case_id)
    if not label or data.empty:
        return np.zeros(len(data), dtype=bool)
    return ((data["episode_code"] == case_id)
            & (data["vintage_cohort"] == label)).to_numpy()


def issue_mask(data: pd.DataFrame, case_id: str,
               *, outcome_only: bool = False) -> np.ndarray:
    """The predicate, evaluated over the published columns at this date.

    `outcome_only` drops the scope clause, which is how a matched historical
    cohort is measured: it is a different vintage, so it fails the scope
    clause by definition, and evaluating the whole rule over it would return
    nobody and make every rate ratio infinite.
    """
    if data.empty:
        return np.zeros(0, dtype=bool)
    mask = np.ones(len(data), dtype=bool)
    clauses = (ep.outcome_clauses(case_id) if outcome_only
               else ep.predicate(case_id)["clauses"])
    for clause in clauses:
        field = clause["field"]
        if field not in data.columns:
            raise MissingEpisodeColumns(
                f"{case_id}'s rule reads {field!r}, which this book does not "
                f"carry. A population cannot be reported as empty when the "
                f"column the rule is written against is absent.")
        mask &= _OPS[clause["op"]](
            data[field], clause["value"]).fillna(False).to_numpy()
    return mask


def pocket_mask(data: pd.DataFrame, case_id: str,
                eligible: np.ndarray | None = None) -> np.ndarray:
    """The named concentration inside the eligible population."""
    if data.empty:
        return np.zeros(0, dtype=bool)
    within = eligible_mask(data, case_id) if eligible is None else eligible
    if case_id == "C01":
        # Alpha's pocket is the expansion's own lower origination bands, which
        # the card book has carried since the accepted build.
        bands = ["580-589", "590-599", "600-619"]
        return within & data["origination_score_band"].isin(bands).to_numpy()
    return within & data["episode_pocket_flag"].fillna(False).to_numpy()


def evidence_mask(data: pd.DataFrame, state: str) -> np.ndarray:
    """Alerts that have survived to a given level of verification.

    The levels nest: corroborated evidence is also verified evidence, so an S3
    cohort is a subset of an S1 cohort rather than a differently-drawn one.
    """
    if data.empty:
        return np.zeros(0, dtype=bool)
    order = {ep.EV_TIMING: 0, ep.EV_VERIFIED: 1, ep.EV_CORROBORATED: 2}
    want = order.get(state)
    if want is None:
        raise ValueError(f"{state!r} is not an evidence state")
    have = data["episode_evidence_state"].map(order)
    return (have >= want).fillna(False).to_numpy()


# ---------------------------------------------------------------------------
# The measures
# ---------------------------------------------------------------------------


def _rate(part: int, whole: int) -> float | None:
    return round(part / whole, 6) if whole else None


def _totals(data: pd.DataFrame, mask: np.ndarray) -> dict[str, Any]:
    rows = data.loc[mask]
    if rows.empty:
        return {"customers": 0, "facilities": 0, "gca_sar": 0.0,
                "ead_sar": 0.0, "ecl_sar": 0.0}
    return {
        "customers": int(rows["customer_id"].nunique()),
        "facilities": int(rows["facility_id"].nunique()),
        "gca_sar": round(float(pd.to_numeric(
            rows["gross_carrying_amount_sar"], errors="coerce").sum()), 2),
        "ead_sar": round(float(pd.to_numeric(
            rows["ead_base_sar"], errors="coerce").sum()), 2),
        "ecl_sar": round(float(pd.to_numeric(
            rows["ecl_weighted_sar"], errors="coerce").sum()), 2),
    }


def _weighted(rows: pd.DataFrame, column: str,
              weight: str = "ead_base_sar") -> float | None:
    """EAD-weighted, per the metric dictionary's preference for PD and LGD.

    An unweighted average over a cohort whose exposures differ by two orders
    of magnitude describes a portfolio nobody holds.
    """
    if rows.empty or column not in rows.columns:
        return None
    values = pd.to_numeric(rows[column], errors="coerce")
    weights = pd.to_numeric(rows.get(weight), errors="coerce")
    ok = values.notna() & weights.notna() & (weights > 0)
    if not ok.any():
        return None
    return round(float((values[ok] * weights[ok]).sum() / weights[ok].sum()), 6)


def concentration(month: str = "", case_id: str = "") -> dict[str, Any]:
    """Share of the book, share of the cases, and both incidences.

    Everything S4 quotes, with its sample sizes, because a rate ratio with no
    denominators beside it is the figure a reader cannot challenge.
    """
    data = frame(month)
    at = resolve(month)
    if data.empty:
        return {"available": False, "because": "no published book"}
    eligible = eligible_mask(data, case_id)
    issue = issue_mask(data, case_id) & eligible
    pocket = pocket_mask(data, case_id, eligible)
    outside = eligible & ~pocket

    n_eligible, n_issue = int(eligible.sum()), int(issue.sum())
    n_pocket, n_pocket_issue = int(pocket.sum()), int((pocket & issue).sum())
    n_outside = int(outside.sum())
    n_outside_issue = int((outside & issue).sum())
    inside = _rate(n_pocket_issue, n_pocket)
    beyond = _rate(n_outside_issue, n_outside)

    return {
        "available": True,
        "case_id": case_id,
        "as_of": at,
        "pocket_label": (ep.by_id(case_id).pocket_label
                         if ep.by_id(case_id) else ""),
        "eligible": n_eligible,
        "issue": n_issue,
        "pocket": {"eligible": n_pocket, "issue": n_pocket_issue,
                   "incidence": inside,
                   "share_of_eligible": _rate(n_pocket, n_eligible),
                   "share_of_cases": _rate(n_pocket_issue, n_issue)},
        "outside": {"eligible": n_outside, "issue": n_outside_issue,
                    "incidence": beyond},
        "rate_ratio": (round(inside / beyond, 2)
                       if inside is not None and beyond else None),
        "definition": mc.definition("concentration"),
    }


def comparator(month: str = "", case_id: str = "") -> dict[str, Any]:
    """The rate this case's rate is compared against, and what it is.

    Three different things behind one word, so the word is never used without
    saying which. The basis is returned beside the figure and is rendered in
    the drawer, because "versus 6 in the comparator" with no statement of what
    the comparator is cannot be checked by anybody.
    """
    at = resolve(month)
    if not at:
        return {"available": False, "because": "no published book"}
    basis = COMPARATOR_BASIS.get(case_id, OUTSIDE_POCKET)
    data = frame(at)

    if basis == PRIOR_MONTH:
        before = previous_month(at)
        if not before:
            return {"available": False, "basis": basis,
                    "because": "there is no earlier published month"}
        earlier = frame(before)
        eligible = eligible_mask(earlier, case_id)
        issue = issue_mask(earlier, case_id) & eligible
        return {"available": True, "basis": basis, "as_of": before,
                "label": COMPARATOR_LABEL[basis],
                "eligible": int(eligible.sum()), "issue": int(issue.sum()),
                "rate": _rate(int(issue.sum()), int(eligible.sum()))}

    if basis == HISTORICAL:
        historical = historical_mask(data, case_id)
        issue = issue_mask(data, case_id, outcome_only=True)
        # The historical cohort is measured on the SAME rule at the same date;
        # what differs is that it reached this age before the episode began.
        return {"available": bool(historical.any()), "basis": basis,
                "as_of": at, "label": COMPARATOR_LABEL[basis],
                "eligible": int(historical.sum()),
                "issue": int((historical & issue).sum()),
                "rate": _rate(int((historical & issue).sum()),
                              int(historical.sum())),
                "because": ("" if historical.any() else
                            "no matched historical cohort is published")}

    eligible = eligible_mask(data, case_id)
    pocket = pocket_mask(data, case_id, eligible)
    outside = eligible & ~pocket
    issue = issue_mask(data, case_id)
    return {"available": bool(outside.any()), "basis": basis, "as_of": at,
            "label": COMPARATOR_LABEL[basis],
            "eligible": int(outside.sum()),
            "issue": int((outside & issue).sum()),
            "rate": _rate(int((outside & issue).sum()), int(outside.sum())),
            "because": ("" if outside.any() else
                        "every eligible facility is inside the named pocket")}


def headline(month: str = "", case_id: str = "") -> dict[str, Any]:
    """The card's own figures: affected, eligible, comparator, exposure.

    The same numbers the drawer opens with and the thread carries into S0.
    """
    at = resolve(month)
    episode = ep.by_id(case_id)
    if not at or episode is None:
        return {"available": False, "because": "no published book"}
    data = frame(at)
    eligible = eligible_mask(data, case_id)
    issue = issue_mask(data, case_id) & eligible
    against = comparator(at, case_id)
    totals = _totals(data, issue)
    rate = _rate(int(issue.sum()), int(eligible.sum()))
    against_rate = against.get("rate")

    return {
        "available": True,
        "case_id": case_id,
        "title": episode.title,
        "card_measure": episode.card_measure,
        "severity": episode.severity,
        "product": episode.product,
        "product_family": episode.product_family,
        "pocket_label": episode.pocket_label,
        "as_of": at,
        "affected": int(issue.sum()),
        "eligible": int(eligible.sum()),
        "rate": rate,
        "comparator": against,
        "multiple": (round(rate / against_rate, 2)
                     if rate and against_rate else None),
        "points": (round((rate - against_rate) * 100, 2)
                   if rate is not None and against_rate is not None else None),
        "exposure_sar": totals["gca_sar"],
        "totals": totals,
        "grain": episode.grain,
        "headline_metric": mc.definition(episode.headline_metric),
        "disclosure": ep.disclosure(),
    }
