"""
What the Corporate IFRS 9 book looks like before anybody changes anything.

Why the product shows this first
--------------------------------
A scenario answer is a comparison, and a comparison is worthless to somebody
who does not know what they are comparing against. So every guided What-If
journey opens by describing the book: the rating profile before a downgrade,
the PD distribution before a PD shock, the sector table before a sector stress.

That is not decoration. "Increase Stage 1 PD by 20%" is a different instruction
depending on whether Stage 1 PD averages 0.4% or 4%, and a person who has just
seen the distribution asks a better second question.

Two arithmetic rules this module keeps
--------------------------------------
**Coverage is summed over summed, never an average of ratios.** A borrower with
SAR 5m of exposure and one with SAR 5bn do not each contribute half of the
book's coverage. Every ratio here is built from its own numerator and
denominator.

**A rate is exposure-weighted unless it says otherwise.** A simple mean PD
answers "what is the average borrower like"; an exposure-weighted mean answers
"what is the book exposed to". Both are reported where both are meaningful,
each under its own name, because quietly picking one is how a screen ends up
disagreeing with the ECL underneath it.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from backend.corporate import ratingscale
from backend.corporate.ratingscale import ALL_STATES, DEFAULT_GRADE, PERFORMING
from backend.whatif import domain as dm

#: The nineteen PERFORMING grades, strongest first, exactly as the governed
#: scale declares them: AAA through C. This is the order every rating table,
#: chart axis and migration matrix uses, and nothing derives it by sorting.
GRADES: tuple[str, ...] = PERFORMING
#: The nineteen grades followed by the default state. A rating profile of the
#: whole book shows all twenty, because a borrower in default is still on the
#: book and dropping it would make the profile's Total disagree with every
#: other screen.
STATES: tuple[str, ...] = ALL_STATES
#: The label a totals row carries.
TOTAL = "Total"

STAGES: tuple[int, ...] = (1, 2, 3)


def _num(frame: pd.DataFrame, column: str) -> pd.Series:
    """One column as a number, with absence treated as zero rather than a crash."""
    if column not in frame.columns:
        return pd.Series(np.zeros(len(frame)), index=frame.index)
    return pd.to_numeric(frame[column], errors="coerce").fillna(0.0)


def _share(part: float, whole: float) -> float:
    return float(part / whole * 100.0) if whole else 0.0


def _weighted(values: pd.Series, weights: pd.Series) -> float:
    total = float(weights.sum())
    if total <= 0:
        return float(values.mean()) if len(values) else 0.0
    return float((values * weights).sum() / total)


def stage_appropriate_pd(frame: pd.DataFrame) -> pd.Series:
    """The PD each borrower is actually measured on.

    Stage 1 on the twelve-month PD, Stage 2 on the lifetime PD, Stage 3 on
    100%. Averaging the two PD columns together produces a number that
    describes no borrower in the book, which is why this exists rather than a
    caller picking a column — and the choice is made by the governed function
    in `ratingscale` rather than repeated here, so a screen and the ECL
    underneath it cannot disagree about what a Stage 3 borrower is measured on.
    """
    return pd.Series(
        ratingscale.applicable_pd(_num(frame, "stage").to_numpy(),
                                  _num(frame, "pd_12m").to_numpy(),
                                  _num(frame, "pd_lifetime").to_numpy()),
        index=frame.index)


def distribution(values: pd.Series, weights: pd.Series | None = None) -> dict[str, Any]:
    """The shape of one measure: the five numbers a risk person asks for."""
    clean = pd.to_numeric(values, errors="coerce").dropna()
    if clean.empty:
        return {"count": 0, "mean": None, "median": None, "min": None,
                "max": None, "p10": None, "p25": None, "p75": None,
                "p90": None, "exposure_weighted_mean": None}
    body = {
        "count": int(len(clean)),
        "mean": round(float(clean.mean()), 4),
        "median": round(float(clean.median()), 4),
        "min": round(float(clean.min()), 4),
        "max": round(float(clean.max()), 4),
        "p10": round(float(clean.quantile(0.10)), 4),
        "p25": round(float(clean.quantile(0.25)), 4),
        "p75": round(float(clean.quantile(0.75)), 4),
        "p90": round(float(clean.quantile(0.90)), 4),
        "exposure_weighted_mean": None,
    }
    if weights is not None:
        aligned = pd.to_numeric(weights, errors="coerce").fillna(0.0).reindex(clean.index)
        body["exposure_weighted_mean"] = round(_weighted(clean, aligned), 4)
    return body


def _enrich(frame: pd.DataFrame, period: str, source: Any = None) -> pd.DataFrame:
    """The book with CCF and collateral brought up from their own grains."""
    work = frame.copy()
    try:
        ccf = dm.facility_ccf(period, source)
        if not ccf.empty:
            work = work.merge(ccf[["borrower_id", "ccf", "facility_count"]],
                              on="borrower_id", how="left", suffixes=("", "_fac"))
    except Exception:  # pragma: no cover - facilities absent
        pass
    if "ccf" not in work.columns:
        work["ccf"] = np.nan
    try:
        col = dm.collateral_by_borrower(period, source)
        if not col.empty:
            work = work.merge(col[["borrower_id", "implied_haircut_pct"]],
                              on="borrower_id", how="left")
    except Exception:  # pragma: no cover - collateral absent
        pass
    if "implied_haircut_pct" not in work.columns:
        work["implied_haircut_pct"] = np.nan
    return work


def _row(label: str, part: pd.DataFrame, whole: pd.DataFrame) -> dict[str, Any]:
    """One line of a profile table, whatever it is grouped by."""
    ead = _num(part, "ead")
    ecl = _num(part, "final_ecl")
    all_ead = _num(whole, "ead")
    all_ecl = _num(whole, "final_ecl")
    exposure = float(ead.sum())
    provision = float(ecl.sum())
    applicable = stage_appropriate_pd(part)
    ccf = pd.to_numeric(part.get("ccf"), errors="coerce") if "ccf" in part.columns \
        else pd.Series(dtype=float)
    return {
        "label": label,
        "count": int(len(part)),
        "count_pct": _share(len(part), len(whole)),
        "exposure": exposure,
        "exposure_pct": _share(exposure, float(all_ead.sum())),
        "ecl": provision,
        "ecl_pct": _share(provision, float(all_ecl.sum())),
        "ecl_coverage_pct": _share(provision, exposure),
        "avg_pd_12m": round(float(_num(part, "pd_12m").mean()), 4) if len(part) else 0.0,
        "avg_pd_lifetime": round(float(_num(part, "pd_lifetime").mean()), 4) if len(part) else 0.0,
        "avg_pd_applicable": round(float(applicable.mean()), 4) if len(part) else 0.0,
        "weighted_pd_applicable": round(_weighted(applicable, ead), 4) if len(part) else 0.0,
        "avg_lgd": round(float(_num(part, "lgd").mean()), 4) if len(part) else 0.0,
        "weighted_lgd": round(_weighted(_num(part, "lgd"), ead), 4) if len(part) else 0.0,
        "avg_stage": round(float(_num(part, "stage").mean()), 4) if len(part) else 0.0,
        "avg_ccf": round(float(ccf.mean()), 4) if len(ccf.dropna()) else None,
    }


# ------------------------------------------------------------ rating profile


def rating_profile(period: str = "", *, source: Any = None) -> dict[str, Any]:
    """The current rating profile: nineteen grades, then default, then Total.

    Every grade appears even when the book holds none of it. A rating table
    that silently omits AAA because nothing is rated AAA reads as though the
    scale stops at AA, and the next question — "downgrade everything one
    notch" — needs the whole scale to be visible to make sense.

    The nineteen performing grades come first, in governed order, and `D`
    follows as a clearly marked state rather than a twentieth grade: it is not
    reachable by a downgrade, and its row exists so the Total ties to the book.
    """
    frame, settled = dm.book(period, source=source)
    work = _enrich(frame, settled, source)
    said = work["internal_rating"].astype(str).str.strip().str.upper() \
        if "internal_rating" in work.columns else pd.Series([""] * len(work))
    work = work.assign(_grade=said)

    rows = []
    for state in STATES:
        row = _row(state, work[work["_grade"] == state], work)
        row["performing"] = state != DEFAULT_GRADE
        row["ordinal"] = STATES.index(state) + 1
        rows.append(row)
    total = _row(TOTAL, work, work)
    total["count_pct"] = 100.0 if len(work) else 0.0
    total["exposure_pct"] = 100.0 if len(work) else 0.0
    total["ecl_pct"] = 100.0 if len(work) else 0.0

    unknown = work[~work["_grade"].isin(STATES)]
    return {
        "period": settled,
        "currency": dm.CURRENCY,
        "grain": dm.GRAIN,
        "grades": list(GRADES),
        "states": list(STATES),
        "performing_grades": list(GRADES),
        "default_grade": DEFAULT_GRADE,
        "rows": rows,
        "total": total,
        "borrowers": int(len(work)),
        "ungraded": int(len(unknown)),
        "note": (f"{len(unknown)} borrower(s) carry a rating outside the "
                 "governed scale and are excluded from the grade rows but "
                 "included in the Total.") if len(unknown) else "",
    }


# ---------------------------------------------------------- stage profile


def stage_profile(period: str = "", *, source: Any = None) -> dict[str, Any]:
    """Stages 1, 2 and 3 with the measures the standard actually distinguishes."""
    frame, settled = dm.book(period, source=source)
    work = _enrich(frame, settled, source)
    stage = _num(work, "stage").astype(int)
    work = work.assign(_stage=stage)

    rows = []
    for number in STAGES:
        part = work[work["_stage"] == number]
        row = _row(f"Stage {number}", part, work)
        row["stage"] = number
        row["measured_on"] = ("12-month PD" if number == 1
                              else "Lifetime PD" if number == 2
                              else "100% - the default has already happened")
        rows.append(row)
    total = _row(TOTAL, work, work)
    total["stage"] = None
    total["count_pct"] = 100.0 if len(work) else 0.0
    total["exposure_pct"] = 100.0 if len(work) else 0.0
    total["ecl_pct"] = 100.0 if len(work) else 0.0
    return {"period": settled, "currency": dm.CURRENCY, "grain": dm.GRAIN,
            "rows": rows, "total": total, "borrowers": int(len(work))}


# --------------------------------------------------------- sector profile


def sector_profile(period: str = "", *, source: Any = None) -> dict[str, Any]:
    """Every sector the book actually holds, largest exposure first.

    No rating distribution here by default: a sector table with nineteen extra
    columns per row is unreadable, and the sector question is about
    concentration and coverage, not about grades.
    """
    frame, settled = dm.book(period, source=source)
    work = _enrich(frame, settled, source)
    if "sector" not in work.columns:
        raise dm.DomainError(dm.field_refusal("sector"))
    rows = []
    for name, part in work.groupby(work["sector"].astype(str)):
        row = _row(str(name), part, work)
        row["sector"] = str(name)
        row["median_pd_applicable"] = round(
            float(stage_appropriate_pd(part).median()), 4)
        row["collateral_value"] = float(_num(part, "collateral_market_value").sum())
        row["collateral_coverage_pct"] = _share(
            float(_num(part, "collateral_market_value").sum()),
            float(_num(part, "ead").sum()))
        haircut = pd.to_numeric(part.get("implied_haircut_pct"), errors="coerce")
        row["avg_haircut_pct"] = round(float(haircut.mean()), 4) \
            if haircut is not None and len(haircut.dropna()) else None
        rows.append(row)
    rows.sort(key=lambda r: r["exposure"], reverse=True)
    total = _row(TOTAL, work, work)
    total["count_pct"] = total["exposure_pct"] = total["ecl_pct"] = \
        100.0 if len(work) else 0.0
    return {"period": settled, "currency": dm.CURRENCY, "grain": dm.GRAIN,
            "rows": rows, "total": total, "sectors": [r["sector"] for r in rows]}


# ------------------------------------------------------ parameter profiles


def _by(work: pd.DataFrame, column: str, values: pd.Series) -> list[dict[str, Any]]:
    """One measure summarised across a dimension, exposure-weighted."""
    if column not in work.columns:
        return []
    ead = _num(work, "ead")
    out = []
    for name, part in work.groupby(work[column].astype(str)):
        chunk = values.reindex(part.index)
        out.append({"label": str(name), "count": int(len(part)),
                    "exposure": float(ead.reindex(part.index).sum()),
                    "mean": round(float(chunk.mean()), 4) if len(chunk) else 0.0,
                    "median": round(float(chunk.median()), 4) if len(chunk) else 0.0,
                    "weighted_mean": round(
                        _weighted(chunk, ead.reindex(part.index)), 4)})
    out.sort(key=lambda r: r["exposure"], reverse=True)
    return out


def _top_names(work: pd.DataFrame, values: pd.Series, limit: int = 10) -> list[dict[str, Any]]:
    """The borrowers carrying the highest value of a measure."""
    if work.empty:
        return []
    ranked = work.assign(_v=values).nlargest(limit, "_v")
    return [{"borrower_id": str(r.get("borrower_id", "")),
             "name": str(r.get("display_name") or r.get("legal_name") or ""),
             "sector": str(r.get("sector", "")),
             "rating": str(r.get("internal_rating", "")),
             "stage": int(r.get("stage") or 0),
             "value": round(float(r["_v"]), 4),
             "exposure": float(r.get("ead") or 0.0),
             "ecl": float(r.get("final_ecl") or 0.0)}
            for _, r in ranked.iterrows()]


def pd_profile(period: str = "", *, source: Any = None) -> dict[str, Any]:
    """PD, described the way each Stage is actually measured.

    Stage 1 is reported on the twelve-month PD and Stage 2 on the lifetime PD,
    in separate blocks that are never combined. Stage 3 is reported with the
    governed treatment stated rather than a distribution implied: a defaulted
    borrower's forward PD is not the thing driving its provision.
    """
    frame, settled = dm.book(period, source=source)
    work = _enrich(frame, settled, source)
    stage = _num(work, "stage").astype(int)
    ead = _num(work, "ead")

    blocks: dict[str, Any] = {}
    for number, column, label in ((1, "pd_12m", "12-month PD"),
                                  (2, "pd_lifetime", "Lifetime PD")):
        part = work[stage == number]
        values = _num(part, column)
        blocks[f"stage_{number}"] = {
            "stage": number,
            "measured_on": label,
            "column": column,
            "borrowers": int(len(part)),
            "exposure": float(_num(part, "ead").sum()),
            "ecl": float(_num(part, "final_ecl").sum()),
            "distribution": distribution(values, _num(part, "ead")),
            "by_rating": _by(part, "internal_rating", values),
            "by_sector": _by(part, "sector", values),
            "by_segment": _by(part, "segment", values),
            "highest": _top_names(part, values),
        }
    third = work[stage == 3]
    blocks["stage_3"] = {
        "stage": 3,
        "measured_on": "Lifetime PD",
        "borrowers": int(len(third)),
        "exposure": float(_num(third, "ead").sum()),
        "ecl": float(_num(third, "final_ecl").sum()),
        "treatment": (
            "Stage 3 is credit-impaired. The provision is measured on the "
            "lifetime PD, and the Stage is a fact about the borrower — a "
            "recorded default or 90+ days past due — rather than a level of "
            "PD. A What-If scenario does not cure a Stage 3 borrower and does "
            "not create one."),
        "distribution": distribution(_num(third, "pd_lifetime"), _num(third, "ead")),
    }
    return {"period": settled, "currency": dm.CURRENCY, "parameter": "PD",
            "grain": dm.GRAIN, "blocks": blocks,
            "book_exposure": float(ead.sum()),
            "book_ecl": float(_num(work, "final_ecl").sum())}


def lgd_profile(period: str = "", *, source: Any = None) -> dict[str, Any]:
    """LGD, with the secured and unsecured halves separated.

    A single average LGD hides the only thing that makes LGD move under a
    scenario: how much of the exposure is actually covered. So the secured and
    unsecured populations are reported apart, and the collateral behind them is
    reported by type with its haircut.
    """
    frame, settled = dm.book(period, source=source)
    work = _enrich(frame, settled, source)
    values = _num(work, "lgd")
    ead = _num(work, "ead")
    secured = _num(work, "secured_exposure")
    covered = work[secured > 0]
    bare = work[secured <= 0]

    types: list[dict[str, Any]] = []
    try:
        items = dm.collateral_detail(settled, source)
        if not items.empty and "collateral_type" in items.columns:
            for name, part in items.groupby(items["collateral_type"].astype(str)):
                gross = float(pd.to_numeric(
                    part["collateral_market_value"], errors="coerce").fillna(0).sum())
                net = float(pd.to_numeric(
                    part["collateral_eligible_value"], errors="coerce").fillna(0).sum())
                haircut = pd.to_numeric(part.get("regulatory_haircut_pct"),
                                        errors="coerce")
                types.append({
                    "collateral_type": str(name),
                    "items": int(len(part)),
                    "gross_value": gross,
                    "haircut_pct": round(float(haircut.mean()), 4)
                    if haircut is not None and len(haircut.dropna()) else
                    round(_share(gross - net, gross), 4),
                    "post_haircut_value": net,
                    "borrowers": int(part["borrower_id"].nunique())})
            types.sort(key=lambda r: r["gross_value"], reverse=True)
    except Exception:  # pragma: no cover - collateral absent
        types = []

    return {
        "period": settled, "currency": dm.CURRENCY, "parameter": "LGD",
        "grain": dm.GRAIN,
        "distribution": distribution(values, ead),
        "by_stage": _by(work.assign(_s=_num(work, "stage").astype(int).astype(str)),
                        "_s", values),
        "by_sector": _by(work, "sector", values),
        "by_segment": _by(work, "segment", values),
        "secured": {"borrowers": int(len(covered)),
                    "exposure": float(_num(covered, "ead").sum()),
                    "ecl": float(_num(covered, "final_ecl").sum()),
                    "distribution": distribution(_num(covered, "lgd"),
                                                 _num(covered, "ead"))},
        "unsecured": {"borrowers": int(len(bare)),
                      "exposure": float(_num(bare, "ead").sum()),
                      "ecl": float(_num(bare, "final_ecl").sum()),
                      "distribution": distribution(_num(bare, "lgd"),
                                                   _num(bare, "ead"))},
        "collateral_types": types,
        "collateral_value": float(_num(work, "collateral_market_value").sum()),
        "collateral_coverage_pct": _share(
            float(_num(work, "collateral_market_value").sum()), float(ead.sum())),
        "book_exposure": float(ead.sum()),
        "book_ecl": float(_num(work, "final_ecl").sum()),
    }


def ccf_profile(period: str = "", *, source: Any = None) -> dict[str, Any]:
    """CCF and the exposure it converts, at facility grain and rolled up.

    CCF is the one parameter here that is not a borrower attribute: a borrower
    with a revolver and a term loan has two of them. The facility view is the
    honest one, and the borrower view is undrawn-weighted so it reproduces the
    borrower's own EAD rather than averaging a large facility with a small one.
    """
    frame, settled = dm.book(period, source=source)
    work = _enrich(frame, settled, source)
    facilities = dm.read(dm.FACILITIES, settled, source)

    by_product: list[dict[str, Any]] = []
    if not facilities.empty and "product_type" in facilities.columns:
        ccf_col = pd.to_numeric(facilities.get("credit_conversion_factor"),
                                errors="coerce")
        undrawn = pd.to_numeric(facilities.get("undrawn_commitment"),
                                errors="coerce").fillna(0.0)
        for name, part in facilities.groupby(facilities["product_type"].astype(str)):
            chunk = ccf_col.reindex(part.index)
            weight = undrawn.reindex(part.index)
            by_product.append({
                "label": str(name), "facilities": int(len(part)),
                "undrawn": float(weight.sum()),
                "ead": float(pd.to_numeric(part.get("ifrs9_ead"),
                                           errors="coerce").fillna(0).sum()),
                "mean": round(float(chunk.mean()), 4) if len(chunk.dropna()) else 0.0,
                "median": round(float(chunk.median()), 4) if len(chunk.dropna()) else 0.0,
                "weighted_mean": round(_weighted(chunk.fillna(0.0), weight), 4)})
        by_product.sort(key=lambda r: r["undrawn"], reverse=True)

    borrower_ccf = pd.to_numeric(work.get("ccf"), errors="coerce")
    return {
        "period": settled, "currency": dm.CURRENCY, "parameter": "CCF",
        "grain": "Facility for the distribution; borrower, undrawn-weighted, for the roll-up.",
        "facility_count": int(len(facilities)),
        "distribution": distribution(
            pd.to_numeric(facilities.get("credit_conversion_factor"), errors="coerce")
            if not facilities.empty else pd.Series(dtype=float),
            pd.to_numeric(facilities.get("undrawn_commitment"), errors="coerce")
            if not facilities.empty else None),
        "borrower_distribution": distribution(borrower_ccf, _num(work, "ead")),
        "by_product": by_product,
        "by_sector": _by(work, "sector", borrower_ccf.fillna(0.0)),
        "drawn_exposure": float(_num(work, "drawn_exposure").sum()),
        "undrawn_commitment": float(_num(work, "undrawn_commitment").sum()),
        "ead": float(_num(work, "ead").sum()),
        "book_ecl": float(_num(work, "final_ecl").sum()),
        "note": ("EAD = drawn + CCF x undrawn. A change in CCF moves EAD, and "
                 "ECL moves with EAD — not by the same percentage as the CCF."),
    }


# -------------------------------------------------------------- borrowers


def top_stage_2(period: str = "", *, limit: int = 10,
                source: Any = None) -> dict[str, Any]:
    """The Stage 2 borrowers carrying the most ECL, at true obligor grain."""
    frame, settled = dm.book(period, source=source)
    work = _enrich(frame, settled, source)
    staged = work[_num(work, "stage").astype(int) == 2]
    ranked = staged.nlargest(int(limit), "final_ecl") if not staged.empty else staged
    rows = [{
        "borrower_id": str(r.get("borrower_id", "")),
        "name": str(r.get("display_name") or r.get("legal_name") or ""),
        "sector": str(r.get("sector", "")),
        "segment": str(r.get("segment", "")),
        "rating": str(r.get("internal_rating", "")),
        "stage": int(r.get("stage") or 0),
        "exposure": float(r.get("ead") or 0.0),
        "pd_12m": float(r.get("pd_12m") or 0.0),
        "pd_lifetime": float(r.get("pd_lifetime") or 0.0),
        "lgd": float(r.get("lgd") or 0.0),
        "ccf": None if pd.isna(r.get("ccf")) else round(float(r.get("ccf")), 4),
        "collateral_value": float(r.get("collateral_market_value") or 0.0),
        "collateral_coverage_pct": float(r.get("collateral_coverage_pct") or 0.0),
        "ecl": float(r.get("final_ecl") or 0.0),
    } for _, r in ranked.iterrows()]
    return {"period": settled, "currency": dm.CURRENCY, "grain": dm.GRAIN,
            "rows": rows, "stage_2_borrowers": int(len(staged)),
            "stage_2_ecl": float(_num(staged, "final_ecl").sum())}


def borrower_history(borrower_id: str, *, quarters: int = 8,
                     source: Any = None) -> dict[str, Any]:
    """One borrower's own path, most recent last.

    Roughly two years by default. A borrower that did not exist in an early
    quarter simply has no row for it — the history is what the book recorded,
    never back-filled.
    """
    said = str(borrower_id or "").strip().upper()
    if not said:
        raise dm.DomainError("No borrower was named.")
    available = dm.periods(source)
    wanted = available[-int(quarters):] if quarters else available
    rows: list[dict[str, Any]] = []
    for period in wanted:
        frame, settled = dm.book(period, source=source)
        found = frame[frame["borrower_id"].astype(str).str.upper() == said]
        if found.empty:
            continue
        r = found.iloc[0]
        rows.append({
            "period": settled,
            "rating": str(r.get("internal_rating", "")),
            "rating_numeric": int(r.get("internal_rating_numeric") or 0),
            "stage": int(r.get("stage") or 0),
            "exposure": float(r.get("ead") or 0.0),
            "pd_12m": float(r.get("pd_12m") or 0.0),
            "pd_lifetime": float(r.get("pd_lifetime") or 0.0),
            "lgd": float(r.get("lgd") or 0.0),
            "ecl": float(r.get("final_ecl") or 0.0),
            "ecl_coverage_pct": float(r.get("ecl_coverage") or 0.0),
            "collateral_value": float(r.get("collateral_market_value") or 0.0),
            "current_dpd": int(r.get("current_dpd") or 0),
            "sector": str(r.get("sector", "")),
            "name": str(r.get("display_name") or r.get("legal_name") or ""),
        })
    if not rows:
        raise dm.DomainError(
            f"Corporate IFRS 9 has no borrower '{borrower_id}' in the "
            f"{len(wanted)} most recent quarters.")
    return {"borrower_id": said, "name": rows[-1]["name"],
            "sector": rows[-1]["sector"], "currency": dm.CURRENCY,
            "quarters": len(rows), "rows": rows}


__all__ = [
    "GRADES", "STAGES", "TOTAL", "borrower_history", "ccf_profile",
    "distribution", "lgd_profile", "pd_profile", "rating_profile",
    "sector_profile", "stage_appropriate_pd", "stage_profile", "top_stage_2",
]
