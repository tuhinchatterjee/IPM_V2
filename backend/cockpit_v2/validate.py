"""
Dataset and calculator integrity gates. Brief §8.1.

These run before the demo is published and BLOCK publication when they fail.
An invalid dataset that reaches the Cockpit produces confident wrong answers,
which is worse than no demo at all, so `scripts/build_cockpit_v2_demo.py`
refuses to write when any gate fails rather than writing with a warning.

Each check returns a machine-readable result with an id, so the evaluation
report can cite the gate rather than the assertion.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pandas as pd

from backend.cockpit_v2 import DATA_VERSION, policy
from backend.cockpit_v2 import calendar as cal
from backend.cockpit_v2 import ecl as ecl_mod
from backend.cockpit_v2 import schema as schema_mod
from backend.cockpit_v2.generate import Build

#: Numerical tolerance for reconciliation gates, in the reporting unit.
TOLERANCE = 1e-6
#: Tolerance for probability identities.
PROBABILITY_TOLERANCE = 1e-9

#: Tolerance for an identity checked against columns as PUBLISHED.
#:
#: Internal arithmetic is full double precision; the published amount columns
#: are rounded to six decimal places for display. An identity over three of
#: them — drawn + ccf x undrawn = ead — therefore carries up to about 1.5e-6 of
#: accumulated rounding, and the EAD gate failed the eight-quarter build at
#: 1.1e-6 for exactly that reason. Loosening the gate to 5e-6 is the correct
#: fix: at 500 borrowers the rounding was real and the rule was not broken.
#: Anything larger than this IS a defect and still fails.
ROUNDING_TOLERANCE = 5e-6


@dataclass
class Check:
    id: str
    description: str
    passed: bool
    detail: str = ""
    observed: Any = None

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "description": self.description,
                "passed": self.passed, "detail": self.detail,
                "observed": self.observed}


def _ok(check_id: str, description: str, observed: Any = None) -> Check:
    return Check(check_id, description, True, "", observed)


def _fail(check_id: str, description: str, detail: str,
          observed: Any = None) -> Check:
    return Check(check_id, description, False, detail, observed)


# --------------------------------------------------------------- the gates


def check_key_uniqueness(build: Build) -> list[Check]:
    out: list[Check] = []
    for label, frame in build.per_quarter.items():
        keys = schema_mod.GRAIN["cockpit_quarter"]["primary_keys"]
        duplicated = frame.duplicated(subset=keys).sum()
        out.append(_ok("key_unique", f"{label}: the primary key is unique",
                       int(len(frame)))
                   if duplicated == 0 else
                   _fail("key_unique", f"{label}: the primary key is unique",
                         f"{duplicated} duplicate row(s) on {keys}"))
    return out


def check_referential_integrity(build: Build) -> list[Check]:
    out: list[Check] = []
    history = build.frames["cockpit_credit_history"]
    facilities = set(zip(history["facility_id"], history["period"]))
    for name in ("cockpit_scenario_parameters", "cockpit_risk_curves",
                 "cockpit_collateral_allocation", "cockpit_movements"):
        frame = build.frames.get(name)
        if frame is None or frame.empty:
            continue
        if name == "cockpit_movements":
            # Exited facilities legitimately have no snapshot row this period.
            frame = frame[frame["membership"] != "exited"]
        orphans = {(f, p) for f, p in zip(frame["facility_id"], frame["period"])
                   } - facilities
        out.append(_ok("referential", f"{name} links to a real facility row",
                       len(frame))
                   if not orphans else
                   _fail("referential", f"{name} links to a real facility row",
                         f"{len(orphans)} orphan key(s), e.g. "
                         f"{sorted(orphans)[:3]}"))
    return out


def check_no_fanout(build: Build) -> list[Check]:
    """A facility with three collaterals and four covenants is one exposure."""
    out: list[Check] = []
    for label, frame in build.per_quarter.items():
        exposure = float(frame["exposure"].sum())
        facilities = int(frame["facility_id"].nunique())
        if facilities != len(frame):
            out.append(_fail(
                "no_fanout", f"{label}: one row per facility",
                f"{len(frame)} rows for {facilities} facilities"))
            continue
        allocation = build.frames.get("cockpit_collateral_allocation")
        if allocation is not None and not allocation.empty:
            rows = allocation[allocation["period"] == label]
            joined = rows.merge(frame[["facility_id", "exposure"]],
                                on="facility_id", how="inner")
            inflated = float(joined["exposure"].sum())
            if inflated <= exposure + TOLERANCE:
                out.append(_ok(
                    "no_fanout",
                    f"{label}: joining collateral detail would fan out, and "
                    f"the snapshot carries the pre-aggregated total instead",
                    {"exposure": exposure, "naive_join_total": inflated}))
            else:
                out.append(_ok(
                    "no_fanout_demonstrated",
                    f"{label}: the pre-aggregated snapshot avoids a fan-out "
                    f"that a naive join would cause",
                    {"exposure": exposure, "naive_join_total": inflated,
                     "inflation_factor": round(inflated / exposure, 3)
                     if exposure else None}))
        out.append(_ok("no_fanout_rows", f"{label}: one row per facility",
                       facilities))
    return out


def check_borrower_deduplication(build: Build) -> list[Check]:
    """Borrower financials repeat across facility rows and must not be summed."""
    out: list[Check] = []
    for label, frame in build.per_quarter.items():
        with_statement = frame[frame["statement_available"]]
        if with_statement.empty:
            continue
        naive = float(with_statement["revenue"].sum())
        deduplicated = float(
            with_statement.drop_duplicates("borrower_id")["revenue"].sum())
        multi = int((frame.groupby("borrower_id").size() > 1).sum())
        if multi == 0:
            out.append(_ok("dedup", f"{label}: no borrower has two facilities"))
            continue
        out.append(_ok(
            "dedup",
            f"{label}: summing a borrower financial across facility rows "
            f"would double count, and the semantic rules forbid it",
            {"naive_sum": round(naive, 2),
             "deduplicated_sum": round(deduplicated, 2),
             "borrowers_with_multiple_facilities": multi})
            if naive > deduplicated + TOLERANCE else
            _ok("dedup", f"{label}: borrower financials do not double count"))
    return out


def check_weights(build: Build) -> list[Check]:
    out: list[Check] = []
    for label, frame in build.per_quarter.items():
        total = (frame["scenario_weight_base"]
                 + frame["scenario_weight_upturn"]
                 + frame["scenario_weight_downturn"])
        worst = float((total - 1.0).abs().max())
        out.append(_ok("weights_sum_to_one",
                       f"{label}: scenario weights sum to one", worst)
                   if worst <= ecl_mod.WEIGHT_TOLERANCE else
                   _fail("weights_sum_to_one",
                         f"{label}: scenario weights sum to one",
                         f"worst deviation {worst}"))
    return out


def check_probability_bounds(build: Build) -> list[Check]:
    out: list[Check] = []
    for label, frame in build.per_quarter.items():
        problems: list[str] = []
        for column in [c for c in frame.columns
                       if c.startswith(("twelve_month_pd_", "lifetime_pd_",
                                        "effective_lgd_"))
                       or c in ("weighted_twelve_month_pd",
                                "weighted_lifetime_pd", "weighted_lgd")]:
            series = frame[column].astype(float)
            if series.min() < -PROBABILITY_TOLERANCE or series.max() > 1 + PROBABILITY_TOLERANCE:
                problems.append(f"{column} in [{series.min()}, {series.max()}]")
        out.append(_ok("probability_bounds",
                       f"{label}: every probability lies in [0, 1]")
                   if not problems else
                   _fail("probability_bounds",
                         f"{label}: every probability lies in [0, 1]",
                         "; ".join(problems)))
    return out


def check_curve_identities(build: Build) -> list[Check]:
    """Survival, hazard and marginal default probability must agree."""
    curves = build.frames.get("cockpit_risk_curves")
    if curves is None or curves.empty:
        return [_fail("curve_identity", "the risk curves reconcile",
                      "no curve rows were generated")]
    worst = 0.0
    for (_, _, _), group in curves.groupby(
            ["facility_id", "scenario_id", "period"], sort=False):
        group = group.sort_values("future_period")
        alive = 1.0
        for _, row in group.iterrows():
            expected = alive * float(row["conditional_hazard"])
            worst = max(worst, abs(expected
                                   - float(row["marginal_default_probability"])))
            alive *= 1.0 - float(row["conditional_hazard"])
            worst = max(worst, abs(alive - float(row["survival"])))
    return [_ok("curve_identity",
                "marginal = survival(t-1) x hazard(t), and survival compounds",
                worst)
            if worst < 1e-9 else
            _fail("curve_identity",
                  "marginal = survival(t-1) x hazard(t)",
                  f"worst discrepancy {worst}")]


def check_lifetime_is_not_annual_times_years(build: Build) -> list[Check]:
    """Lifetime PD must BE the sum of marginals, not a linear scaling.

    The obvious gate — assert the cumulative PD is below the annual PD times
    the number of years — is wrong, and writing it that way was a mistake worth
    recording: it holds only for a FLAT hazard. This demo gives each facility a
    gently rising term structure, under which a long-dated account legitimately
    exceeds the naive product. So the check is the identity itself, recomputed
    from the published curve rows, plus the separate assertion that the linear
    shortcut and the real figure are not the same number.
    """
    curves = build.frames.get("cockpit_risk_curves")
    if curves is None or curves.empty:
        return [_fail("lifetime_identity", "lifetime PD reconciles to its curve",
                      "no curve rows were generated")]

    out: list[Check] = []
    for label, frame in build.per_quarter.items():
        rows = curves[curves["period"] == label]
        if rows.empty:
            continue
        summed = (rows.groupby(["facility_id", "scenario_id"])
                  ["marginal_default_probability"].sum())
        worst = 0.0
        checked = 0
        for _, row in frame.iterrows():
            if row["stage"] == 3:
                continue
            for scenario in policy.SCENARIO_IDS:
                key = (row["facility_id"], scenario)
                if key not in summed.index:
                    continue
                worst = max(worst, abs(float(summed.loc[key])
                                       - float(row[f"lifetime_pd_{scenario}"])))
                checked += 1
        out.append(_ok("lifetime_identity",
                       f"{label}: lifetime PD equals the sum of the published "
                       f"marginal default probabilities",
                       {"scenario_curves_checked": checked,
                        "worst_discrepancy": worst})
                   if worst < 1e-9 else
                   _fail("lifetime_identity",
                         f"{label}: lifetime PD is the sum of its marginals",
                         f"worst discrepancy {worst}"))

        performing = frame[(frame["stage"] != 3)
                           & (frame["measurement_horizon_periods"] > 4)]
        if performing.empty:
            continue
        naive = (performing["twelve_month_pd_base"]
                 * performing["measurement_horizon_periods"] / 4.0)
        identical = int((naive - performing["lifetime_pd_base"]).abs()
                        .lt(1e-9).sum())
        out.append(_ok("lifetime_not_linear",
                       f"{label}: no facility's lifetime PD is its annual PD "
                       f"multiplied by its number of years",
                       int(len(performing)))
                   if identical == 0 else
                   _fail("lifetime_not_linear",
                         f"{label}: lifetime PD is not annual PD times years",
                         f"{identical} facility/-ies match the linear product "
                         f"exactly"))
    return out


def check_ecl_reconciliation(build: Build) -> list[Check]:
    out: list[Check] = []
    for label, frame in build.per_quarter.items():
        weighted = (frame["scenario_weight_base"] * frame["ecl_base"]
                    + frame["scenario_weight_upturn"] * frame["ecl_upturn"]
                    + frame["scenario_weight_downturn"] * frame["ecl_downturn"])
        worst_model = float((weighted - frame["weighted_model_ecl"]).abs().max())
        reported = frame["weighted_model_ecl"] + frame["overlay"]
        worst_reported = float((reported - frame["reported_ecl"]).abs().max())
        out.append(_ok("ecl_reconciles",
                       f"{label}: weighted model ECL is the weighted sum of "
                       f"scenario ECLs, and reported ECL adds the overlay",
                       {"model": worst_model, "reported": worst_reported})
                   if max(worst_model, worst_reported) < 1e-8 else
                   _fail("ecl_reconciles",
                         f"{label}: ECL reconciles across scenarios and overlay",
                         f"model {worst_model}, reported {worst_reported}"))
    return out


def check_weighted_parameter_product_differs(build: Build) -> list[Check]:
    """The shortcut must be visibly wrong on the real data, not just in theory."""
    out: list[Check] = []
    for label, frame in build.per_quarter.items():
        naive = (frame["weighted_twelve_month_pd"] * frame["weighted_lgd"]
                 * frame["weighted_ead"]).sum()
        actual = float(frame["weighted_model_ecl"].sum())
        out.append(_ok("weighted_product_differs",
                       f"{label}: weighted PD x weighted LGD x weighted EAD "
                       f"does not reproduce the weighted ECL",
                       {"naive_product": round(float(naive), 4),
                        "weighted_model_ecl": round(actual, 4)})
                   if abs(float(naive) - actual) > TOLERANCE else
                   _fail("weighted_product_differs",
                         f"{label}: the parameter product must differ from "
                         f"the weighted ECL",
                         "they agree, which means the demo cannot demonstrate "
                         "why the shortcut is wrong"))
    return out


def check_ead_and_exposure_differ(build: Build) -> list[Check]:
    out: list[Check] = []
    for label, frame in build.per_quarter.items():
        expected = frame["drawn_amount"] + frame["ccf"] * frame["undrawn_commitment"]
        worst = float((expected - frame["ead"]).abs().max())
        with_undrawn = frame[frame["undrawn_commitment"] > TOLERANCE]
        differ = int((with_undrawn["exposure"] - with_undrawn["ead"]
                      ).abs().gt(TOLERANCE).sum())
        if worst >= ROUNDING_TOLERANCE:
            out.append(_fail("ead_rule", f"{label}: EAD follows the CCF rule",
                             f"worst discrepancy {worst}"))
        elif len(with_undrawn) and differ == 0:
            out.append(_fail(
                "ead_rule", f"{label}: exposure and EAD are distinct",
                "every facility with an undrawn commitment has EAD equal to "
                "exposure, so the CCF is not being applied"))
        else:
            out.append(_ok("ead_rule",
                           f"{label}: EAD = drawn + CCF x undrawn to within "
                           f"published rounding, and is distinct from exposure",
                           {"facilities_with_undrawn": len(with_undrawn),
                            "where_they_differ": differ}))
    return out


def check_balance_sheet(build: Build) -> list[Check]:
    financials = build.frames.get("cockpit_borrower_financials")
    if financials is None or financials.empty:
        return [_ok("balance_sheet", "no financial statements were generated")]
    residual = (financials["total_assets"] - financials["total_liabilities"]
                - financials["total_equity"]).abs()
    worst = float(residual.max())
    return [_ok("balance_sheet",
                "assets equal liabilities plus equity on every statement",
                worst)
            if worst < 1e-6 else
            _fail("balance_sheet", "the balance sheet balances",
                  f"worst residual {worst}")]


def check_ratio_formulas(build: Build) -> list[Check]:
    """Ratios must be recomputable from the components that are published."""
    financials = build.frames.get("cockpit_borrower_financials")
    if financials is None or financials.empty:
        return [_ok("ratio_formula", "no statements to check")]
    rows = financials[financials["ratio_current_ratio"].notna()]
    if rows.empty:
        return [_ok("ratio_formula", "no current ratio was computed")]
    recomputed = rows["total_current_assets"] / rows["current_liabilities"]
    worst = float((recomputed - rows["ratio_current_ratio"]).abs().max())
    return [_ok("ratio_formula",
                "the current ratio recomputes from its published components",
                worst)
            if worst < 1e-6 else
            _fail("ratio_formula", "ratios recompute from their components",
                  f"worst discrepancy {worst}")]


def check_negative_denominators(build: Build) -> list[Check]:
    """A missing ratio must be null, never zero and never infinite."""
    financials = build.frames.get("cockpit_borrower_financials")
    if financials is None or financials.empty:
        return [_ok("null_not_zero", "no statements to check")]
    problems: list[str] = []
    for column in [c for c in financials.columns if c.startswith("ratio_")]:
        series = pd.to_numeric(financials[column], errors="coerce")
        if series.replace([math.inf, -math.inf], pd.NA).isna().sum() != series.isna().sum():
            problems.append(f"{column} carries an infinity")
    return [_ok("null_not_zero",
                "an unavailable ratio is null, not zero and not infinite")
            if not problems else
            _fail("null_not_zero", "an unavailable ratio is null",
                  "; ".join(problems))]


def check_collateral_allocation(build: Build) -> list[Check]:
    """Allocations for one asset never exceed its recognised value."""
    allocation = build.frames.get("cockpit_collateral_allocation")
    if allocation is None or allocation.empty:
        return [_ok("allocation_cap", "no collateral allocations")]
    grouped = allocation.groupby(["collateral_id", "period"]).agg(
        allocated=("allocated_recognised_amount", "sum"),
        recognised=("asset_recognised_value", "first"))
    over = grouped[grouped["allocated"] > grouped["recognised"] + 1e-6]
    shared = allocation.groupby(["collateral_id", "period"]).size()
    return [_ok("allocation_cap",
                "the allocations of one collateral asset sum to at most its "
                "recognised value, so a shared asset is counted once",
                {"assets": int(len(grouped)),
                 "shared_across_facilities": int((shared > 1).sum())})
            if over.empty else
            _fail("allocation_cap", "collateral allocations do not exceed the "
                  "recognised value",
                  f"{len(over)} asset/period pair(s) over-allocated")]


def check_staging_policy(build: Build) -> list[Check]:
    """Every stage must be explained by the stated policy, and one downgrade
    must not stage an account on its own."""
    out: list[Check] = []
    for label, frame in build.per_quarter.items():
        unexplained = frame[frame["sicr_reason"].fillna("") == ""]
        if len(unexplained):
            out.append(_fail("staging_explained",
                             f"{label}: every stage names the rule behind it",
                             f"{len(unexplained)} row(s) with no reason"))
            continue
        out.append(_ok("staging_explained",
                       f"{label}: every stage names the rule behind it"))

        one_notch = frame[(frame["rating_notches_since_origination"] == 1)
                          & (frame["days_past_due"] < policy.SICR_DPD_BACKSTOP)]
        staged = one_notch[one_notch["stage"] == 2]
        # A one-notch account may still be Stage 2 on the PD test; what must
        # not happen is that EVERY one-notch account is Stage 2, which would
        # mean the notch rule is really a one-notch rule.
        out.append(_ok("one_downgrade_is_not_stage_2",
                       f"{label}: one notch of downgrade does not stage an "
                       f"account by itself",
                       {"one_notch_accounts": int(len(one_notch)),
                        "of_which_stage_2": int(len(staged))})
                   if len(one_notch) == 0 or len(staged) < len(one_notch) else
                   _fail("one_downgrade_is_not_stage_2",
                         f"{label}: one downgrade must not imply Stage 2",
                         f"all {len(one_notch)} one-notch accounts are Stage 2"))

        stage_3 = frame[frame["stage"] == 3]
        wrong_method = stage_3[stage_3["measurement_method"] != ecl_mod.METHOD_IMPAIRED]
        out.append(_ok("stage_3_method",
                       f"{label}: Stage 3 uses the credit-impaired method",
                       int(len(stage_3)))
                   if wrong_method.empty else
                   _fail("stage_3_method",
                         f"{label}: Stage 3 uses the credit-impaired method",
                         f"{len(wrong_method)} Stage 3 row(s) measured by the "
                         f"performing formula"))
    return out


def check_temporal_availability(build: Build) -> list[Check]:
    """No snapshot may carry information that was not knowable at its date."""
    out: list[Check] = []
    for label, frame in build.per_quarter.items():
        as_at = cal.reporting_date(label)
        with_statement = frame[frame["statement_available"] == True]  # noqa: E712
        if with_statement.empty:
            out.append(_ok("no_leak", f"{label}: no statements to check"))
            continue
        later = with_statement[
            pd.to_datetime(with_statement["statement_availability_date"]).dt.date
            > as_at]
        out.append(_ok("no_leak",
                       f"{label}: every statement was available on or before "
                       f"the reporting date",
                       int(len(with_statement)))
                   if later.empty else
                   _fail("no_leak", f"{label}: no information leaks backwards",
                         f"{len(later)} row(s) carry a statement that became "
                         f"available after the reporting date"))
    return out


def check_macro_vintages(build: Build) -> list[Check]:
    macro = build.frames.get("cockpit_macro_paths")
    if macro is None or macro.empty:
        return [_fail("macro_vintage", "macro paths exist", "none generated")]
    scenarios = set(macro["scenario_id"].unique())
    expected = set(policy.SCENARIO_IDS) | {"actual"}
    return [_ok("macro_vintage",
                "macro paths carry every scenario plus the actuals, by vintage",
                {"vintages": int(macro["forecast_vintage"].nunique()),
                 "predictors": int(macro["predictor"].nunique()),
                 "rows": int(len(macro))})
            if scenarios == expected else
            _fail("macro_vintage", "macro paths carry every scenario",
                  f"found {sorted(scenarios)}, expected {sorted(expected)}")]


def check_population_changes(build: Build) -> list[Check]:
    movements = build.frames.get("cockpit_movements")
    if movements is None or movements.empty:
        return [_ok("population", "only one quarter was published")]
    manufactured = movements[(movements["membership"] == "new")
                             & movements["reported_ecl_prior"].notna()]
    return [_ok("population",
                "new and exited facilities carry a null comparator rather "
                "than a manufactured zero",
                movements["membership"].value_counts().to_dict())
            if manufactured.empty else
            _fail("population", "new facilities have no prior comparator",
                  f"{len(manufactured)} new row(s) carry a prior value")]


def check_synthetic_labelling(build: Build) -> list[Check]:
    out: list[Check] = []
    for name, frame in {**{cal.dataset_name(q): f
                           for q, f in build.per_quarter.items()},
                        **build.frames}.items():
        if frame.empty:
            continue
        if "is_synthetic" not in frame.columns:
            out.append(_fail("synthetic_label", f"{name} declares itself synthetic",
                             "no is_synthetic column"))
        elif not bool(frame["is_synthetic"].all()):
            out.append(_fail("synthetic_label", f"{name} declares itself synthetic",
                             "some rows are not marked synthetic"))
    return out or [_ok("synthetic_label",
                       "every generated row is marked synthetic")]


def check_data_version(build: Build) -> list[Check]:
    problems = [name for name, frame in build.frames.items()
                if not frame.empty and "data_version" in frame.columns
                and not (frame["data_version"] == DATA_VERSION).all()]
    return [_ok("data_version", f"every row carries data version {DATA_VERSION}")
            if not problems else
            _fail("data_version", "every row carries the current data version",
                  f"{problems} carry another version")]


def check_no_simple_measurement(build: Build) -> list[Check]:
    """The oracle's simplified fixture must not have leaked into the book."""
    out: list[Check] = []
    for label, frame in build.per_quarter.items():
        performing = frame[(frame["stage"] != 3)
                           & (frame["measurement_horizon_periods"] == 1)]
        out.append(_ok("no_toy_measurement",
                       f"{label}: no performing facility is measured over a "
                       f"single period with a unit discount factor")
                   if performing.empty else
                   _fail("no_toy_measurement",
                         f"{label}: the simplified oracle fixture is not used "
                         f"for the demo book",
                         f"{len(performing)} performing row(s) measured over "
                         f"one period"))
    return out


def check_stories_landed(build: Build) -> list[Check]:
    """Each assigned story's mechanic must actually be observable."""
    if len(build.published) < 2:
        return [_ok("stories", "a story check needs two published quarters")]
    from backend.cockpit_v2 import attribution as attr

    opening, closing = build.published[-2], build.published[-1]
    by_story = {sid: bid for bid, sid in build.assignments.items()}
    out: list[Check] = []

    def factors(borrower: str) -> dict[str, float]:
        o = [m for k, m in build.measurements[opening].items()
             if k.startswith(borrower + "-")]
        c = [m for k, m in build.measurements[closing].items()
             if k.startswith(borrower + "-")]
        if not o or not c:
            return {}
        found = attr.decompose_ecl_factors(o, c)
        return ({f.factor: f.contribution for f in found.factors}
                | {s.line: s.amount for s in found.structural})

    expectations: dict[str, tuple[str, str]] = {
        "STORY_WEIGHTS_ONLY": (attr.FACTOR_WEIGHTS,
                         "the weights are the largest factor"),
        "STORY_COLLATERAL_WEAKENING": (attr.FACTOR_LGD,
                                 "recovery is the largest factor"),
        "STORY_CASH_DETERIORATION": (attr.FACTOR_PD,
                               "the PD curves are the largest factor"),
        "STORY_OVERLAY_CHANGE": (attr.LINE_OVERLAY,
                           "the overlay is the largest line"),
    }
    for story_id, (expected, description) in expectations.items():
        borrower = by_story.get(story_id)
        if borrower is None:
            out.append(_ok("story", f"{story_id} is not in this population"))
            continue
        found = factors(borrower)
        if not found:
            out.append(_ok("story", f"{story_id}: no facility at both dates"))
            continue
        largest = max(found, key=lambda k: abs(found[k]))
        out.append(_ok("story", f"{story_id}: {description}",
                       {"largest": largest,
                        "contribution": round(found[largest], 8)})
                   if largest == expected else
                   _fail("story", f"{story_id}: {description}",
                         f"the largest was {largest} "
                         f"({found[largest]:.8f}), not {expected}"))

    stage_borrower = by_story.get("STORY_STAGE_1_TO_2")
    if stage_borrower:
        o = build.per_quarter[opening]
        c = build.per_quarter[closing]
        before = o[o["borrower_id"] == stage_borrower]["stage"]
        after = c[c["borrower_id"] == stage_borrower]["stage"]
        out.append(_ok("story",
                       "STAGE_1_TO_2: the account migrates from Stage 1 to 2",
                       {"opening": before.tolist(), "closing": after.tolist()})
                   if (not before.empty and not after.empty
                       and before.iloc[0] == 1 and after.iloc[0] == 2) else
                   _fail("story", "STAGE_1_TO_2 migrates from Stage 1 to 2",
                         f"stages went {before.tolist()} -> {after.tolist()}"))
    return out


def check_factor_bridge_reconciles(build: Build) -> list[Check]:
    if len(build.published) < 2:
        return [_ok("bridge", "a bridge needs two published quarters")]
    from backend.cockpit_v2 import attribution as attr

    out: list[Check] = []
    for i in range(1, len(build.published)):
        opening, closing = build.published[i - 1], build.published[i]
        found = attr.decompose_ecl_factors(
            list(build.measurements[opening].values()),
            list(build.measurements[closing].values()),
            opening_date=cal.iso(opening), closing_date=cal.iso(closing))
        out.append(_ok("bridge",
                       f"{opening} to {closing}: the factor bridge reconciles",
                       {"residual": found.residual,
                        "net_change": round(found.net_change, 6)})
                   if found.reconciled else
                   _fail("bridge",
                         f"{opening} to {closing}: the factor bridge reconciles",
                         f"residual {found.residual}"))
    return out


CHECKS: tuple[Callable[[Build], list[Check]], ...] = (
    check_key_uniqueness,
    check_referential_integrity,
    check_no_fanout,
    check_borrower_deduplication,
    check_weights,
    check_probability_bounds,
    check_curve_identities,
    check_lifetime_is_not_annual_times_years,
    check_ecl_reconciliation,
    check_weighted_parameter_product_differs,
    check_ead_and_exposure_differ,
    check_balance_sheet,
    check_ratio_formulas,
    check_negative_denominators,
    check_collateral_allocation,
    check_staging_policy,
    check_temporal_availability,
    check_macro_vintages,
    check_population_changes,
    check_synthetic_labelling,
    check_data_version,
    check_no_simple_measurement,
    check_stories_landed,
    check_factor_bridge_reconciles,
)


def validate(build: Build) -> dict[str, Any]:
    """Run every gate. A failure blocks publication."""
    results: list[Check] = []
    for gate in CHECKS:
        try:
            results.extend(gate(build))
        except Exception as e:  # noqa: BLE001 - a broken gate is a failure
            results.append(_fail(gate.__name__, gate.__name__,
                                 f"the gate itself raised: {e!r}"))
    passed = sum(1 for r in results if r.passed)
    return {
        "data_version": DATA_VERSION,
        "published_quarters": list(build.published),
        "checks": [r.to_dict() for r in results],
        "total": len(results), "passed": passed,
        "failed": len(results) - passed,
        "tolerance": TOLERANCE,
        "note": ("These are dataset and calculator integrity gates. They "
                 "check internal consistency and stated policy, not "
                 "calibration, validation or accounting compliance."),
    }


__all__ = ["CHECKS", "Check", "PROBABILITY_TOLERANCE", "ROUNDING_TOLERANCE",
           "TOLERANCE", "validate"]
