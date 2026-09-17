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

def _challenger_version() -> str:
    """The stored challenger's version, from the registry that owns it."""
    try:
        from backend.retail.challenger_registry import CHALLENGER_VERSION

        return CHALLENGER_VERSION
    except Exception:  # noqa: BLE001 - a method list must not fail to build
        return "unavailable"


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
        # Read from the registry, not held here.
        #
        # This said 1.1.0 while the stored artifact said 2.0.0, so a single
        # challenger result carried BOTH: `version` from this table and
        # `model_version` from the card it actually scored with. A reader
        # asking which version produced a number got a different answer
        # depending on which field they read, and the wrong one was the
        # copy that no longer matched any model on disk.
        "version": _challenger_version(),
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


#: Below this a movement is rounding, not a direction. Expected credit loss
#: is in SAR over a book of six billion, so a sub-riyal difference between two
#: estimates is not a disagreement about anything.
_A_DIRECTION_SAR = 1.0


def _agreement(challenger_delta: float, delta_method_delta: Any) -> str:
    """Whether the two methods point the same way, said honestly.

    The defect: this was `(after - base) * delta_ecl > 0`, which is False
    when BOTH are zero — so a scenario whose shocks did not move anything
    reported "The two methods disagree on direction, which is a reason to
    trust the Delta method and investigate the challenger". Two methods that
    both say nothing moved agree completely, and telling a committee they
    disagree invites an investigation of a number that is not there.
    """
    if delta_method_delta is None:
        return ""
    engine = float(delta_method_delta)
    challenger = float(challenger_delta)
    still = (abs(engine) < _A_DIRECTION_SAR
             and abs(challenger) < _A_DIRECTION_SAR)
    if still:
        return ("Neither method moves expected credit loss, so there is no "
                "direction to agree or disagree about.")
    if abs(engine) < _A_DIRECTION_SAR or abs(challenger) < _A_DIRECTION_SAR:
        # `.capitalize()` would lower-case the rest and write "The delta
        # method", which is not the method's name.
        engine_moved = abs(engine) >= _A_DIRECTION_SAR
        moved = "The Delta method" if engine_moved else "The challenger"
        still_named = "the challenger" if engine_moved else "the Delta method"
        return (f"{moved} moves expected credit loss and {still_named} does "
                f"not. The Delta method is the calculation of record.")
    if challenger * engine > 0:
        return "The two methods agree on direction."
    return ("The two methods disagree on direction, which is a reason to "
            "trust the Delta method and investigate the challenger.")


def _challenger(book: Any, population: Any, shocks: dict[str, Any],
                delta_result: dict[str, Any]) -> dict[str, Any]:
    """The comparison estimate.

    Fitted on the book itself: a gradient-boosted model of expected credit
    loss on the risk parameters, trained on the unshocked population and then
    asked what it would say about the shocked one. It is a different route to
    the same question, which is the only reason to show it.
    """
    # The STORED artifact, not a fresh fit.
    #
    # This used to fit a gradient-boosted model over the whole book on every
    # single scenario run and then throw it away. Three things were wrong with
    # that, in rising order. It was the dominant cost of a run that is
    # otherwise arithmetic. There was nothing to open, so §10.2's model page
    # had no model to describe. And "the challenger said X last Tuesday" was
    # unanswerable, because the model that said it no longer existed.
    #
    # `load()` serves the artifact when it was fitted on the book that is
    # published now, and rebuilds when it was not — a challenger trained on a
    # book that has been regenerated, answering questions about the one that
    # replaced it, loads perfectly and is wrong.
    from backend.retail import challenger_registry as registry

    try:
        model, card = registry.load()
    except registry.ChallengerUnavailable as problem:
        return {"available": False, "because": str(problem),
                **METHODS[CHALLENGER]}

    import numpy as np
    import pandas as pd

    have = list(card.features)
    library = card.library
    if not len(population) or not have:
        return {"available": False,
                "because": "the selection holds no rows to score",
                **METHODS[CHALLENGER]}
    missing = [one for one in have if one not in population.columns]
    if missing:
        return {"available": False,
                "because": (f"the selection does not carry "
                            f"{', '.join(missing)}, which the stored "
                            f"challenger was fitted on"),
                **METHODS[CHALLENGER]}

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
        "model_version": card.version,
        "fitted_on": card.rows_fitted,
        "fitted_from_book": card.source_hash[:12],
        "held_back": card.rows_held_back,
        "held_back_r2": round(card.metrics.get("r2", 0.0), 4),
        "held_back_wape": round(card.metrics.get("wape", 0.0), 4),
        "features": have,
        "estimated_ecl_before_sar": round(base, 2),
        "estimated_ecl_after_sar": round(after, 2),
        "estimated_delta_sar": round(after - base, 2),
        "delta_method_delta_sar": delta_ecl,
        "agreement": _agreement(after - base, delta_ecl),
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


#: How each shock reads in a sentence. A shock with no entry here falls
#: through to its identifier, which is how "lgd_absolute_pp = 5.0" reached a
#: reader — the identifier IS the fallback, so every supported shock needs a
#: line and a test checks that they all have one.
_SAYS: dict[str, Any] = {
    "pd_relative": lambda v: f"a {float(v):+.0%} relative move in PD",
    "pd_absolute_pp": lambda v: f"{float(v):+g} percentage points on PD",
    "lgd_relative": lambda v: f"a {float(v):+.0%} relative move in LGD",
    "lgd_absolute_pp": lambda v: (
        f"{float(v):+g} percentage points on loss given default"),
    "collateral_value_pct": lambda v: (
        f"a {float(v):+.0%} move in collateral value"),
    "recovery_delay_months": lambda v: (
        f"{float(v):+g} months of recovery delay"),
    "utilisation_pp": lambda v: (
        f"{float(v):+g} percentage points of card utilisation"),
    "ccf_absolute": lambda v: f"a credit conversion factor set to {float(v):g}",
    "ccf_absolute_pp": lambda v: (
        f"{float(v):+g} percentage points on the credit conversion factor"),
    "income_pct": lambda v: f"a {float(v):+.0%} move in verified income",
    "expense_pct": lambda v: f"a {float(v):+.0%} move in household expenses",
    "behavioural_score_points": lambda v: (
        f"{float(v):+g} behavioural score points"),
    "scenario_weights": lambda v: "reweighted macroeconomic scenarios",
    "staging_mode": lambda v: (
        "stages re-evaluated by the policy" if "reeval" in str(v)
        else "stages held as published"),
    "cutoff_replay": lambda v: f"the application cutoff replayed at {v}",
    "dpd_migration": lambda v: _migration_says(v, "delinquency bucket"),
    "score_band_migration": lambda v: _migration_says(v, "score band"),
    "stage_migration": lambda v: _migration_says(v, "IFRS 9 stage"),
}


def _migration_says(value: Any, what: str) -> str:
    """A migration, in the reader's words rather than as a dictionary."""
    if not isinstance(value, dict):
        return f"a {what} migration"
    share = value.get("share")
    basis = value.get("basis") or "exposure"
    source, target = value.get("from"), value.get("to")
    part = (f"{float(share) * 100:g}% of {basis}" if share is not None
            else "part")
    if source and target:
        return f"{part} moved from {what} {source} to {target}"
    return f"{part} moved between {what}s"


def _describe(shocks: dict[str, Any]) -> str:
    said = []
    for name, value in (shocks or {}).items():
        says = _SAYS.get(name)
        said.append(says(value) if says else f"{name} = {value}")
    return " and ".join(said) if said else "the scenario"


def follow_ups(selection: sel.Selection, levels: list[dict[str, Any]]
               ) -> list[str]:
    """What to test next, given what this scenario just showed, §19."""
    out = []
    if selection.forward_risk:
        out.append("Stress only the forward-risk customers in this selection.")
    if selection.current_bad:
        out.append("Stress only the customers who are already bad.")
    out.append("Add 10 percentage points to LGD.")
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

    inside = panel[wif.facility_mask(panel, held)]
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
        rows = book[wif.facility_mask(book, level["facility_ids"])]
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
        touched = rows[wif.facility_mask(rows, stressed)]
        untouched_ecl = (float(rows["ecl_weighted_sar"].sum())
                         - float(touched["ecl_weighted_sar"].sum()))
        # The movement itself, computed ONCE from the shocked population and
        # not from the difference of two rounded level totals.
        #
        # Deriving it from `after - before` at each level rounded both sides
        # at that level's magnitude — SAR 7.7m for a sub-product, SAR 6.4bn
        # for total Retail — and the same movement came out as 451,024.35 at
        # one level and 451,024.36 at another. The workbook's own sheet says
        # the absolute movement is identical at every level, which is true of
        # the arithmetic and was not true of the number printed beside it.
        moved_ecl = round(float(shocked.get("ecl_weighted_sar") or 0.0)
                          - float(touched["ecl_weighted_sar"].sum()), 2)
        moved_base = round(float(shocked.get("ecl_base_sar") or 0.0)
                           - float(touched["ecl_base_sar"].sum()), 2)
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

        delta = _delta(before, after)
        # The level-independent movement wins over the subtraction of two
        # rounded totals, and the percentage is recomputed from it so the two
        # columns still agree with each other.
        delta["ecl_weighted_sar"] = moved_ecl
        delta["ecl_base_sar"] = moved_base
        if before.get("ecl_weighted_sar"):
            delta["ecl_weighted_sar_pct"] = round(
                moved_ecl / float(before["ecl_weighted_sar"]) * 100, 4)
        if before.get("ecl_base_sar"):
            delta["ecl_base_sar_pct"] = round(
                moved_base / float(before["ecl_base_sar"]) * 100, 4)
        levels.append({
            "level": level["level"],
            "label": level["label"],
            "before": before,
            "after": after,
            "delta": delta,
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
        # The propagation, carried up from the engine so the result, the
        # screen and the workbook all read one record of it.
        "mechanism": (cohort.get("engine") or {}).get("mechanism"),
        "score_migration": (cohort.get("engine") or {}).get("score_migration"),
        "stage_movement": (cohort.get("engine") or {}).get("stage_movement"),
        "bounded": (cohort.get("engine") or {}).get("bounded"),
        "scenario": (cohort.get("engine") or {}).get("scenario"),
        "limitations": (cohort.get("engine") or {}).get("limitations") or [],
        "assumptions": (cohort.get("engine") or {}).get("assumptions") or [],
        "follow_ups": follow_ups(selection, levels),
        "disclaimer": M.DISCLAIMER,
    }

    if which in (CHALLENGER, "both"):
        touched = book[wif.facility_mask(book, stressed)]
        out["challenger"] = _challenger(
            book, touched, dict(shocks), cohort.get("engine") or {})
    out["interpretation"] = _interpretation(
        selection, levels, dict(shocks),
        DELTA if which == "both" else which)
    return out


__all__ = ["CHALLENGER", "DELTA", "METHODS", "follow_ups", "methodologies",
           "run"]
