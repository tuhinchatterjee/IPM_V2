"""Running a scenario on an Early Warning cohort, and saying what it did.

A scenario on an exported cohort has to answer two different questions at
once, and the second is the one people forget:

    What does this do to the customers I selected?
    And does that matter to the portfolio I am responsible for?

A twenty per cent PD shock on four hundred card customers can move their own
expected loss by half and the retail book by four basis points. Both numbers
are true and a reader needs both, so every result here is reported at the
selected cohort, at its classification, at its product and at total Retail —
the same scenario, the same engine, widening populations.

The methodology is stated rather than assumed. The Delta method recomputes the
IFRS 9 identity deterministically; the challenger estimator is a comparison,
not an authority, and is labelled that way wherever it appears.
"""

from __future__ import annotations

from typing import Any

from backend.retail import ews_model as M
from backend.retail import ews_score as S
from backend.retail import whatif as wif
from backend.retail import whatif_selection as sel
from backend.retail.config import load_config

DELTA = "delta"
CHALLENGER = "xgboost"

METHODS: dict[str, dict[str, str]] = {
    DELTA: {
        "key": DELTA,
        "name": "Delta method",
        "version": wif.METHODOLOGY_VERSION,
        "what": ("Deterministic recalculation of the IFRS 9 identity. Each "
                 "shock is applied to the parameter it names and expected "
                 "credit loss is recomputed facility by facility."),
        "authority": ("This is the calculation of record. Every figure can be "
                      "traced to a facility and a parameter."),
    },
    CHALLENGER: {
        "key": CHALLENGER,
        "name": "XGBoost challenger",
        "version": "retail-whatif-challenger-1.1.0",
        "what": ("A gradient-boosted scenario estimator fitted on the book's "
                 "own relationship between risk parameters and loss. It "
                 "answers the same question by a different route. The result "
                 "names the library that actually fitted it."),
        "authority": ("A challenger, not the IFRS 9 engine. It is shown for "
                      "comparison and its numbers are never the calculation "
                      "of record."),
    },
}


def methodologies() -> dict[str, Any]:
    """What a reader is choosing between, §14."""
    return {
        "methods": list(METHODS.values()),
        "default": DELTA,
        "question": ("Which methodology should this scenario be calculated "
                     "with — the Delta method, the challenger, or both?"),
        "note": ("Running both calculates the scenario twice and compares "
                 "them. Where they disagree, the Delta method is the "
                 "calculation of record."),
    }


def _aggregate(rows: Any) -> dict[str, Any]:
    """The figures a level is judged on, before or after a scenario."""
    import pandas as pd

    if not len(rows):
        return {"customers": 0, "accounts": 0, "exposure_sar": 0.0,
                "ecl_weighted_sar": 0.0}
    exposure = float(rows["gross_carrying_amount_sar"].sum())

    def weighted(column: str) -> float | None:
        if column not in rows.columns or not exposure:
            return None
        return round(float(
            (pd.to_numeric(rows[column], errors="coerce").fillna(0.0)
             * rows["gross_carrying_amount_sar"]).sum() / exposure), 6)

    return {
        "customers": int(rows["customer_id"].nunique()),
        "accounts": int(rows["facility_id"].nunique()),
        "exposure_sar": round(exposure, 2),
        "pd_pit_12m": weighted("pd_pit_12m_base"),
        "pd_ttc_12m": weighted("pd_ttc_12m"),
        "pd_pit_lifetime": weighted("pd_pit_lifetime_base"),
        "lgd": weighted("lgd_base"),
        "ccf": weighted("ccf_base"),
        "ead_sar": round(float(rows["ead_base_sar"].sum()), 2),
        "ecl_base_sar": round(float(rows["ecl_base_sar"].sum()), 2),
        "ecl_weighted_sar": round(float(rows["ecl_weighted_sar"].sum()), 2),
        "ecl_coverage_pct": round(
            float(rows["ecl_weighted_sar"].sum()) / exposure * 100, 4)
            if exposure else None,
        "stage_mix": {str(k): int(v) for k, v in
                      rows["ifrs9_stage"].value_counts().sort_index().items()},
    }


def _delta(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in ("ecl_weighted_sar", "ecl_base_sar", "pd_pit_12m", "lgd",
                "ead_sar", "ccf", "exposure_sar"):
        one, two = before.get(key), after.get(key)
        if one is None or two is None:
            out[key] = None
            continue
        out[key] = round(float(two) - float(one), 6)
        if key.endswith("_sar") and float(one):
            out[f"{key}_pct"] = round((float(two) - float(one))
                                      / float(one) * 100, 4)
    return out


def _levels(selection: sel.Selection) -> list[dict[str, Any]]:
    """The widening populations a result is reported at, §16."""
    from backend.retail import ews_views as V

    scored = S.read(selection.source_month)
    out = [{
        "level": "selection",
        "label": f"Selected cohort — {selection.source_label}",
        "facility_ids": set(selection.selected_facility_ids),
    }]
    if selection.source_sub_product:
        # The sub-product across BOTH classifications. Narrowing it to the
        # classification as well would make this level identical to the
        # selection whenever a reader drilled Salaried -> Platinum, and a
        # hierarchy that repeats itself tells them nothing.
        rows = V._where(scored, product=selection.source_product,
                        sub_product=selection.source_sub_product)
        out.append({
            "level": "sub_product",
            "label": M.SUB_PRODUCT_LABELS.get(selection.source_sub_product,
                                              selection.source_sub_product),
            "facility_ids": set(rows["facility_id"].astype(str)),
        })
    if selection.source_classification:
        rows = V._where(scored, product=selection.source_product,
                        classification=selection.source_classification)
        out.append({
            "level": "classification",
            "label": M.CLASSIFICATION_LABELS.get(
                selection.source_classification,
                selection.source_classification),
            "facility_ids": set(rows["facility_id"].astype(str)),
        })
    if selection.source_product:
        rows = V._where(scored, product=selection.source_product)
        out.append({
            "level": "product",
            "label": (str(rows["product_label"].iloc[0]) if len(rows)
                      else selection.source_product),
            "facility_ids": set(rows["facility_id"].astype(str)),
        })
    out.append({
        "level": "retail",
        "label": "Total Retail",
        "facility_ids": set(scored["facility_id"].astype(str)),
    })
    # A customer-level export has no sub-product row of its own unless the
    # customer's facilities carry one; deduplicate by level rather than guess.
    seen, unique = set(), []
    for one in out:
        if one["level"] in seen:
            continue
        seen.add(one["level"])
        unique.append(one)
    return unique


def _challenger(book: Any, population: Any, shocks: dict[str, Any],
                delta_result: dict[str, Any]) -> dict[str, Any]:
    """The comparison estimate.

    Fitted on the book itself: a gradient-boosted model of expected credit
    loss on the risk parameters, trained on the unshocked population and then
    asked what it would say about the shocked one. It is a different route to
    the same question, which is the only reason to show it.
    """
    # XGBoost where the installation has it, scikit-learn's gradient boosting
    # where it does not. Which one actually ran is reported on the result: the
    # method was keyed "xgboost" while it fitted a scikit-learn estimator, and
    # a reader comparing two methodologies has to be able to see which model
    # produced the number in front of them.
    estimator, library = None, ""
    try:
        from xgboost import XGBRegressor

        estimator = XGBRegressor(
            n_estimators=120, max_depth=6, learning_rate=0.1,
            tree_method="hist", random_state=20260914, n_jobs=2)
        library = f"XGBoost {__import__('xgboost').__version__}"
    except ImportError:
        try:
            from sklearn.ensemble import HistGradientBoostingRegressor

            estimator = HistGradientBoostingRegressor(
                max_iter=120, max_depth=6, learning_rate=0.1,
                random_state=20260914)
            library = ("scikit-learn HistGradientBoostingRegressor — XGBoost "
                       "is not installed here")
        except ImportError:
            return {"available": False,
                    "because": ("the challenger estimator needs XGBoost or "
                                "scikit-learn, and this installation has "
                                "neither"),
                    **METHODS[CHALLENGER]}

    import numpy as np
    import pandas as pd

    features = ["pd_pit_12m_base", "pd_pit_lifetime_base", "lgd_base",
                "ead_base_sar", "ccf_base", "gross_carrying_amount_sar",
                "ifrs9_stage", "dpd"]
    have = [one for one in features if one in book.columns]
    if len(have) < 5 or not len(population):
        return {"available": False,
                "because": "the book does not carry enough parameters to fit",
                **METHODS[CHALLENGER]}

    train = book[have + ["ecl_weighted_sar"]].dropna()
    if len(train) < 500:
        return {"available": False,
                "because": "too few complete rows to fit a challenger",
                **METHODS[CHALLENGER]}

    model = estimator
    model.fit(train[have].to_numpy(dtype=float),
              train["ecl_weighted_sar"].to_numpy(dtype=float))

    # The shocked parameters, as the Delta method computed them, fed back in.
    shocked = population.copy()
    for column, factor in (("pd_pit_12m_base", shocks.get("pd_relative")),
                           ("pd_pit_lifetime_base", shocks.get("pd_relative")),
                           ("lgd_base", shocks.get("lgd_relative"))):
        if factor is not None and column in shocked.columns:
            shocked[column] = pd.to_numeric(
                shocked[column], errors="coerce") * (1 + float(factor))
    if shocks.get("pd_absolute_pp") is not None:
        for column in ("pd_pit_12m_base", "pd_pit_lifetime_base"):
            if column in shocked.columns:
                shocked[column] = pd.to_numeric(
                    shocked[column], errors="coerce") + float(
                        shocks["pd_absolute_pp"]) / 100.0

    base = float(model.predict(
        population[have].fillna(0.0).to_numpy(dtype=float)).sum())
    after = float(model.predict(
        shocked[have].fillna(0.0).to_numpy(dtype=float)).sum())
    # The engine names its own delta `ecl_final_sar`; that is the figure to
    # compare a challenger against, not the aggregate key used elsewhere.
    engine_delta = delta_result.get("delta") or {}
    delta_ecl = engine_delta.get("ecl_final_sar")
    if delta_ecl is None:
        delta_ecl = engine_delta.get("ecl_weighted_sar")
    return {
        "available": True,
        **METHODS[CHALLENGER],
        "estimator": library,
        "fitted_on": int(len(train)),
        "features": have,
        "estimated_ecl_before_sar": round(base, 2),
        "estimated_ecl_after_sar": round(after, 2),
        "estimated_delta_sar": round(after - base, 2),
        "delta_method_delta_sar": delta_ecl,
        "agreement": (
            "The two methods agree on direction."
            if delta_ecl is not None and (after - base) * float(delta_ecl) > 0
            else "The two methods disagree on direction, which is a reason to "
                 "trust the Delta method and investigate the challenger."
            if delta_ecl is not None else ""),
        "note": ("An estimate from a model fitted on this book, shown for "
                 "comparison. The Delta method is the calculation of record."),
    }


def _interpretation(selection: sel.Selection, levels: list[dict[str, Any]],
                    shocks: dict[str, Any], method: str) -> str:
    """What the scenario did, in the terms a committee asks about, §18."""
    by = {one["level"]: one for one in levels}
    cohort = by.get("selection") or {}
    delta = cohort.get("delta") or {}
    moved = delta.get("ecl_weighted_sar")
    moved_pct = delta.get("ecl_weighted_sar_pct")
    before = (cohort.get("before") or {}).get("ecl_weighted_sar") or 0.0
    retail = by.get("retail") or {}
    retail_delta = (retail.get("delta") or {}).get("ecl_weighted_sar") or 0.0
    retail_before = (retail.get("before") or {}).get("ecl_weighted_sar") or 0.0
    retail_exposure = (retail.get("before") or {}).get("exposure_sar") or 0.0

    said = [
        f"Applying {_describe(shocks)} to {selection.source_label} "
        f"({selection.selected_customer_count:,} customers, "
        f"{selection.selected_account_count:,} accounts, SAR "
        f"{selection.selected_exposure_sar:,.0f}) moves the cohort's weighted "
        f"expected credit loss from SAR {before:,.0f} to SAR "
        f"{(cohort.get('after') or {}).get('ecl_weighted_sar', 0):,.0f}"
        + (f", a change of SAR {moved:,.0f} ({moved_pct:+.1f}%)."
           if moved is not None and moved_pct is not None else ".")]

    drivers = []
    for name, label in (("pd_pit_12m", "point-in-time PD"),
                        ("lgd", "loss given default"),
                        ("ead_sar", "exposure at default")):
        value = delta.get(name)
        if value:
            drivers.append(label)
    if drivers:
        said.append(f"The move comes through {', '.join(drivers)}.")

    if retail_before:
        said.append(
            f"At total Retail the same scenario adds SAR {retail_delta:,.0f} "
            f"to expected credit loss, {retail_delta / retail_before * 100:+.2f}% "
            f"of the book's provision and "
            f"{retail_delta / retail_exposure * 10000:+.1f} basis points of "
            f"coverage on SAR {retail_exposure:,.0f} of exposure."
            if retail_exposure else "")
    share = (selection.materiality.get("retail") or {}).get("exposure_pct")
    if share is not None and retail_delta:
        contribution = (float(moved or 0.0) / retail_delta * 100
                        if retail_delta else 0.0)
        said.append(
            f"The selected cohort is {share:.1f}% of Retail exposure and "
            f"accounts for {contribution:.1f}% of the portfolio-wide increase, "
            + ("so the impact is concentrated in the customers selected."
               if contribution > share * 1.5 else
               "roughly in line with its size."))

    said.append(
        f"Calculated with the {METHODS.get(method, METHODS[DELTA])['name']}. "
        + METHODS.get(method, METHODS[DELTA])["authority"])
    said.append(
        "The scenario holds everything else at its published value: it is a "
        "parameter sensitivity on one month's book, not a forecast, and it "
        "assumes the selected cohort behaves as the shock describes.")
    return " ".join(one for one in said if one)


def _describe(shocks: dict[str, Any]) -> str:
    said = []
    for name, value in (shocks or {}).items():
        if name == "pd_relative":
            said.append(f"a {float(value):+.0%} relative move in PD")
        elif name == "pd_absolute_pp":
            said.append(f"{float(value):+g} percentage points on PD")
        elif name == "lgd_relative":
            said.append(f"a {float(value):+.0%} move in LGD")
        elif name == "collateral_value_pct":
            said.append(f"a {float(value):+.0%} move in collateral value")
        elif name == "utilisation_pp":
            said.append(f"{float(value):+g} percentage points of utilisation")
        elif name == "ccf_absolute":
            said.append(f"a credit conversion factor of {float(value):g}")
        elif name == "income_pct":
            said.append(f"a {float(value):+.0%} move in income")
        elif name == "behavioural_score_points":
            said.append(f"{float(value):+g} behavioural score points")
        else:
            said.append(f"{name} = {value}")
    return " and ".join(said) if said else "the scenario"


def follow_ups(selection: sel.Selection, levels: list[dict[str, Any]]
               ) -> list[str]:
    """What to test next, given what this scenario just showed, §19."""
    out = []
    if selection.forward_risk:
        out.append("Stress only the forward-risk customers in this selection.")
    if selection.current_bad:
        out.append("Stress only the customers who are already bad.")
    # Phrased so the parser reads it. "Add a 10% increase in loss given
    # default" puts the number before the subject, which the reader's
    # subject-then-number rule does not match — a follow-up the thread offered
    # and then refused.
    out.append("Increase LGD by 10%.")
    out.append("Combine the DPD migration with a 10% collateral haircut.")
    if not selection.source_classification:
        out.append("Compare Salaried against Non-Salaried.")
    out.append("Run the challenger and compare it with the Delta method.")
    out.append("Save this scenario and share it.")
    return out[:7]


def narrow(selection: sel.Selection,
           within: dict[str, Any]) -> tuple[list[str], str]:
    """The facilities inside a selection that also match `within`.

    "Stress only the forward-risk customers in this selection" narrows what
    was exported; it does not replace it. A sentence read as a fresh filter
    would quietly widen the scenario to every forward-risk customer in the
    book, report a number four times the size, and be wrong in the direction
    nobody checks.

    Returns the facilities and a sentence saying what the narrowing did, so
    the thread can show the reader the population it actually ran on.
    """
    from backend.retail import ews_score as scored

    held = list(selection.selected_facility_ids)
    if not within:
        return held, ""
    try:
        panel = scored.read(selection.source_month)
    except Exception:  # noqa: BLE001 - the domain may not be built
        return held, ""
    if panel is None or not len(panel):
        return held, ""

    inside = panel[panel["facility_id"].astype(str).isin(set(held))]
    for column, value in within.items():
        if column not in inside.columns:
            continue
        values = value if isinstance(value, (list, tuple, set)) else [value]
        if column.endswith("_flag"):
            inside = inside[inside[column].fillna(False).astype(bool)
                            == bool(list(values)[0])]
        else:
            inside = inside[inside[column].astype(str).isin(
                [str(one) for one in values])]

    kept = [str(one) for one in inside["facility_id"].astype(str)]
    if len(kept) == len(held):
        return held, ""
    said = ", ".join(f"{k.replace('_', ' ')} "
                     + (", ".join(str(one) for one in v)
                        if isinstance(v, (list, tuple)) else str(v))
                     for k, v in within.items())
    return kept, (
        f"Narrowed to {said}: {len(kept):,} of the selection's "
        f"{len(held):,} facilities.")


def read(said: str, selection: sel.Selection) -> dict[str, Any]:
    """Read a typed sentence against one selection, with the governed parser.

    The thread used to carry its own reader in the browser — a short list of
    patterns that knew about five shocks. It could not be right for long: the
    parser that the rest of What-If runs on lives in
    `backend.retail.whatif_language`, understands the whole retail cohort
    vocabulary, and is the thing that gets improved. Two readers meant the
    thread understood less than the composer on the next screen did, and no
    amount of keeping them in step would have survived the next shock.
    """
    from backend.retail import ews_score as scored
    from backend.retail import whatif_language as language

    ask = language.read(said, months=scored.panel_months())
    if ask.needs_clarification:
        return {"understood": False, "question": ask.question,
                "options": ask.options, "read_as": ask.read_as}
    if not ask.shocks and not ask.scenario_weights:
        return {
            "understood": False,
            "question": (
                f'This thread could not read a governed change out of "{said}". '
                "Name a parameter and a size — \u201cincrease PIT 12-month PD "
                "by 20%\u201d — or a migration — \u201cmove 15% of Stage 1 "
                "exposure to Stage 2\u201d."),
            "options": [],
            "read_as": ask.read_as,
            "unsupported": ask.unsupported,
        }

    # Anything the sentence says about WHO narrows the selection. What it says
    # about the month and the product it was already exported for is dropped:
    # the selection decides those.
    within = {k: v for k, v in ask.filters.items()
              if k not in ("product_code", "facility_id", "customer_id")}
    return {
        "understood": True,
        "shocks": dict(ask.shocks),
        "staging_mode": ask.staging_mode,
        "scenario_weights": ask.scenario_weights,
        "within": within,
        "read_as": list(ask.read_as),
        "unsupported": list(ask.unsupported),
    }


def run(selection_id: str, *, shocks: dict[str, Any],
        name: str = "", method: str = DELTA,
        staging_mode: str = wif.FROZEN_STAGE,
        within: dict[str, Any] | None = None,
        scenario_weights: dict[str, float] | None = None) -> dict[str, Any]:
    """One scenario, on one selection, reported at every level above it."""
    selection = sel.get(selection_id)
    if selection is None:
        return {"available": False,
                "because": f"{selection_id} is not a known selection."}

    # A sentence may narrow the selection. It never widens it: the population
    # a scenario runs on is the one that was exported, or a part of it.
    stressed, narrowing = narrow(selection, within or {})
    if not stressed:
        return {"available": False,
                "because": ("Nothing in this selection matches that "
                            "narrowing, so there is nothing to stress.")}

    book = S._read_book(selection.source_month)
    config = load_config()
    which = str(method or DELTA).lower()
    if which not in METHODS and which != "both":
        return {"available": False,
                "because": f"{method!r} is not a methodology this offers."}

    levels = []
    for level in _levels(selection):
        rows = book[book["facility_id"].astype(str).isin(level["facility_ids"])]
        if not len(rows):
            continue
        # The scenario is applied ONLY to the selected facilities, at every
        # level: the wider populations show what that does to them, not what
        # shocking the whole product would do.
        scenario = wif.Scenario(
            name=name or f"{selection.source_label} scenario",
            dataset_version=str(book.get("dataset_version",
                                         [""])[0]) if "dataset_version" in book
                            else "",
            snapshot_date=str(rows["snapshot_date"].iloc[0]),
            filters={"facility_id": list(stressed)},
            shocks=dict(shocks), staging_mode=staging_mode,
            scenario_weights=scenario_weights)
        # Decompose only at the selection level. The wider levels differ from
        # it by the population that is NOT shocked, so a step-by-step reading
        # of them would be the same steps against a larger denominator — the
        # same decomposition, told less clearly, four more times.
        result = wif.run(rows, scenario, config,
                         decompose=level["level"] == "selection")

        before = _aggregate(rows)
        shocked = result.get("scenario_result") or {}
        # The engine reports the shocked population; everything outside it is
        # unchanged, so the level's after-figure is the level's before-figure
        # with the shocked part swapped in.
        touched = rows[rows["facility_id"].astype(str).isin(
            set(stressed))]
        untouched_ecl = (float(rows["ecl_weighted_sar"].sum())
                         - float(touched["ecl_weighted_sar"].sum()))
        after = dict(before)
        after["ecl_weighted_sar"] = round(
            untouched_ecl + float(shocked.get("ecl_weighted_sar") or 0.0), 2)
        after["ecl_base_sar"] = round(
            float(rows["ecl_base_sar"].sum())
            - float(touched["ecl_base_sar"].sum())
            + float(shocked.get("ecl_base_sar") or 0.0), 2)
        if before["exposure_sar"]:
            after["ecl_coverage_pct"] = round(
                after["ecl_weighted_sar"] / before["exposure_sar"] * 100, 4)
        if level["level"] == "selection":
            for key in ("pd_pit_12m", "lgd", "ead_sar", "ccf"):
                moved = (result.get("scenario_result") or {}).get(key)
                if moved is not None:
                    after[key] = moved

        levels.append({
            "level": level["level"],
            "label": level["label"],
            "before": before,
            "after": after,
            "delta": _delta(before, after),
            "engine": result if level["level"] == "selection" else None,
        })

    if not levels:
        return {"available": False,
                "because": "the selection matches nothing in this month's book"}

    cohort = next(one for one in levels if one["level"] == "selection")
    out: dict[str, Any] = {
        "available": True,
        "selection_id": selection.selection_id,
        "selection": {k: v for k, v in selection.to_dict().items()
                      if k not in ("selected_customer_ids",
                                   "selected_facility_ids")},
        "month": selection.source_month,
        "methodology": METHODS.get(which, METHODS[DELTA]) if which != "both"
                       else {"key": "both", "name": "Delta and challenger",
                             "what": "Both methods, compared.",
                             "authority": METHODS[DELTA]["authority"]},
        "shocks": dict(shocks),
        "shocks_described": _describe(shocks),
        "levels": levels,
        "stressed_facilities": len(stressed),
        "narrowing": narrowing,
        # The cohort as it stood, carried on the result rather than left on the
        # page that opened the thread. A result downloaded into a workbook, or
        # reopened from a saved thread, has to be able to say what it ran on.
        "baseline": sel.baseline(selection),
        "waterfall": (cohort.get("engine") or {}).get("waterfall"),
        "scenario": (cohort.get("engine") or {}).get("scenario"),
        "limitations": (cohort.get("engine") or {}).get("limitations") or [],
        "assumptions": (cohort.get("engine") or {}).get("assumptions") or [],
        "follow_ups": follow_ups(selection, levels),
        "disclaimer": M.DISCLAIMER,
    }

    if which in (CHALLENGER, "both"):
        touched = book[book["facility_id"].astype(str).isin(
            set(stressed))]
        out["challenger"] = _challenger(
            book, touched, dict(shocks), cohort.get("engine") or {})
    out["interpretation"] = _interpretation(
        selection, levels, dict(shocks),
        DELTA if which == "both" else which)
    return out


__all__ = ["CHALLENGER", "DELTA", "METHODS", "follow_ups", "methodologies",
           "run"]
