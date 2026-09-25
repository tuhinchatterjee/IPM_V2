#!/usr/bin/env python3
"""Train the ECL emulators, once, and report what they measured.

    .venv-whatif/bin/python scripts/whatif/train_emulator.py --domain all

**Runs in the candidate virtual environment**, built from
`requirements-whatif.txt`. The accepted environment has none of these
libraries and is meant not to: running this with the accepted interpreter
exits with the missing libraries named rather than importing anything.

`docs/whatif/ML_ACCEPTANCE_TARGETS.md` was committed before this script was
first run and is not edited afterwards. Every gate is reported as measured;
a failure stays a failure, appears in the model card marked FAILED, is
published in `whatif_*_model_metric` with its measured value, and makes
Method 2 report its limitation to the reader.

The test periods are read ONCE, at the end, after every configuration,
every preprocessing statistic and every blend weight is settled.

Everything here is fitted on a **generated** book against a target produced
by `reference_ecl.py`. Passing establishes that an emulator can learn that
calculator. It is not bank-engine validation and no output may say it is.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("COCKPIT_V4_WHATIF_CORPORATE", "1")
os.environ.setdefault("COCKPIT_V4_WHATIF_RETAIL", "1")

from backend.cockpit_v4 import analytical_runtime as arun  # noqa: E402
from backend.cockpit_v4 import domains as dom  # noqa: E402
from backend.cockpit_v4 import lake  # noqa: E402
from backend.cockpit_v4.scenario import candidate_schema as cs  # noqa: E402
from backend.cockpit_v4.scenario import ml  # noqa: E402
from backend.cockpit_v4.scenario.ml import blend as bl  # noqa: E402
from backend.cockpit_v4.scenario.ml import card as cd  # noqa: E402
from backend.cockpit_v4.scenario.ml import components as cp  # noqa: E402
from backend.cockpit_v4.scenario.ml import features as ft  # noqa: E402
from backend.cockpit_v4.scenario.ml import split as sp  # noqa: E402
from backend.cockpit_v4.scenario.ml import train as tr  # noqa: E402

#: The one query per book that assembles the training frame. Written out so
#: a reader can run it and get the same rows, and so the joins are visible
#: rather than hidden in a builder.
SOURCE: dict[str, str] = {
    dom.CORPORATE: """
        SELECT f.*, b.rating_current, b.rating_notches_moved,
               b.rating_migration, b.rating_outlook, b.pd_ttc_12m,
               b.leverage_x, b.dscr_x, b.interest_cover_x, b.current_ratio_x,
               b.ebitda_margin_pct, b.return_on_assets_pct,
               b.cash_conversion_pct, b.qualitative_score, b.watchlist_flag,
               b.restructured_flag, b.quarters_on_watchlist,
               i.ecl_rate, i.effective_interest_rate,
               i.remaining_maturity_months, i.lifetime_horizon_months,
               i.ccf_pit, i.ccf_eligible_flag, i.undrawn_eligible_sar_mn
        FROM corp_facility_quarter f
        JOIN corp_borrower_quarter b
          USING (borrower_id, reporting_quarter)
        JOIN whatif_corp_ifrs9 i USING (facility_id, reporting_quarter)
    """,
    dom.RETAIL: """
        SELECT a.*, h.utilisation_change_pp, h.payment_ratio_pct,
               h.missed_payments_12m, h.delinquency_streak_months,
               h.balance_growth_pct, h.cash_advance_ratio_pct,
               h.overlimit_flag, h.inflow_change_pct, h.bureau_inquiries_6m,
               h.repayment_behaviour_score,
               p.employer_sector, p.employer_sector_group,
               p.application_score,
               i.ecl_rate, i.effective_interest_rate,
               i.remaining_maturity_months, i.lifetime_horizon_months
        FROM retail_account_month a
        JOIN retail_behaviour_month h
          ON h.account_id = a.account_id
         AND h.reporting_month = a.reporting_month
        JOIN whatif_retail_profile p
          ON p.customer_id = a.customer_id
         AND p.reporting_month = a.reporting_month
        JOIN whatif_retail_ifrs9 i
          ON i.account_id = a.account_id
         AND i.reporting_month = a.reporting_month
    """,
}

ARTIFACTS = ROOT / "artifacts" / "whatif"


def load(domain_id: str):
    import pandas as pd  # noqa: F401  (duckdb returns a DataFrame)

    connection = arun.for_domain(domain_id).session.connection
    return connection.execute(SOURCE[domain_id]).fetchdf()


def run(domain_id: str, *, out_dir: Path) -> tr.Result:
    import numpy as np

    key, period_column = ft.KEYS[domain_id]
    release_id = cs.RELEASES[domain_id]
    frame = load(domain_id)
    print(f"  {len(frame):,} rows, {frame[period_column].nunique()} periods")

    embargo, rule = sp.label_embargo(
        frame.to_dict("records")[:1], period_column=period_column)
    assignment = sp.assign(sorted(frame[period_column].unique()),
                           embargo=embargo, rule=rule)
    leaks = sp.leakage(assignment)
    if leaks:
        raise SystemExit(f"the split leaks: {leaks}")
    print(f"  {assignment.describe()}")

    ft.check_target(ft.TARGET)
    features, names = tr.matrix(frame, domain_id)
    target = frame[ft.TARGET].astype("float64")
    denominator = frame[ft.DENOMINATOR].astype("float64")
    periods = frame[period_column].astype(str)
    print(f"  {len(names)} features, target {ft.TARGET}")

    development = periods.isin(
        assignment.train + assignment.validate).to_numpy()
    test = periods.isin(assignment.test).to_numpy()

    fitted: dict[str, cp.Fitted] = {}
    out_of_fold: dict[str, dict[int, float]] = {}
    versions = cp.available()

    for component in ml.COMPONENTS:
        started = time.time()
        config, trials, oof = tr.tune(
            component, features, target, denominator, periods, assignment)
        # The final refit sees every development period and has nothing left
        # to stop early against, so it runs for the round count the folds
        # justified. Giving it the 600-round cap instead would let a booster
        # memorise data it can no longer be checked on.
        chosen = max((t.rounds for t in trials
                      if t.config == config), default=0)
        model = cp.build(component, config, seed=ml.SEEDS[component],
                         rounds=chosen)
        model.fit(features[development], target[development])
        fitted[component] = cp.Fitted(
            component=component, config=config, model=model,
            rounds=chosen, trials=trials,
            seed=ml.SEEDS[component],
            library_version=versions.get(component, ""))
        out_of_fold[component] = oof
        print(f"  {component:16s} best {min(t.mean_error for t in trials):.5f}"
              f" WAPE over {len(trials)} configs in {time.time()-started:.0f}s")

    # Every component saw the same folds, so their out-of-fold row sets
    # agree; the intersection is taken anyway rather than assumed, because
    # weights fitted on rows one component did not predict would be weights
    # fitted on a population that does not exist.
    shared = sorted(set.intersection(
        *(set(oof) for oof in out_of_fold.values())))
    if not shared:
        raise SystemExit("no row was predicted out of fold by every "
                         "component; there is nothing to fit weights on.")
    oof_actual = [float(target.iloc[i]) * float(denominator.iloc[i])
                  for i in shared]
    oof_currency = {
        c: [out_of_fold[c][i] * float(denominator.iloc[i]) for i in shared]
        for c in ml.COMPONENTS}
    blended = bl.fit(oof_currency, oof_actual)
    print(f"  {blended.headline}")

    # ---- the test split, read once ------------------------------------
    predictions = {
        c: np.asarray(fitted[c].model.predict(features[test]), dtype=float)
        for c in ml.COMPONENTS}
    test_denominator = denominator[test].to_numpy()
    test_actual = (target[test].to_numpy() * test_denominator).tolist()
    test_predicted = blended.predict(
        {c: (predictions[c] * test_denominator).tolist()
         for c in ml.COMPONENTS})

    test_frame = frame[test]
    test_periods = periods[test].to_numpy()
    per_period = []
    for one in assignment.test:
        mask = test_periods == one
        if mask.any():
            per_period.append(abs(tr.bias(
                [a for a, m in zip(test_actual, mask, strict=True) if m],
                [p for p, m in zip(test_predicted, mask, strict=True) if m])))

    subgroups = tr.subgroup_table(test_frame, test_actual, test_predicted,
                                  domain_id)
    material = [g["wape"] for g in subgroups if g["material"]]
    naive = (frame.loc[test, "ead_sar_mn"] * frame.loc[test, "pd_pit_12m"]
             * frame.loc[test, "lgd_pct"] / 100.0).tolist()

    result = tr.Result(
        domain_id=domain_id, release_id=release_id,
        model_version=ml.MODEL_VERSION, assignment=assignment,
        blended=blended, components=fitted,
        metrics={
            "test_wape": tr.wape(test_actual, test_predicted),
            "test_bias": tr.bias(test_actual, test_predicted),
            "worst_period_bias": max(per_period, default=0.0),
            "worst_material_group_wape": max(material, default=0.0),
        },
        reference={
            "wape": tr.wape(test_actual, naive),
            "bias": tr.bias(test_actual, naive),
        },
        subgroups=subgroups,
        counts={
            "rows": len(frame), "development_rows": int(development.sum()),
            "test_rows": int(test.sum()), "features": len(names),
            "entities": int(frame[key].nunique()),
            "train_periods": len(assignment.train),
            "validate_periods": len(assignment.validate),
            "test_periods": len(assignment.test),
            "embargoed_periods": len(assignment.embargoed),
            "out_of_fold_rows": len(shared),
        },
        libraries=versions)
    tr.judge(result)

    print(f"  test WAPE {result.metrics['test_wape']:.4f} "
          f"bias {result.metrics['test_bias']:+.4f} "
          f"| reference WAPE {result.reference['wape']:.4f}")
    for name, gate in sorted(result.gates.items()):
        mark = "PASS" if gate["passed"] else "FAIL"
        print(f"    {name} {mark}  {gate['what']}: "
              f"{gate['measured']:.4f} vs {gate['threshold']:.4f}")

    out_dir.mkdir(parents=True, exist_ok=True)
    cd.freeze(result, names, out_dir / domain_id)

    # The model card as DATA, for `whatif_*_model_metric`. Written to disk
    # rather than published here: publishing is `seed_candidate.py`'s job
    # and it picks these up on its next run.
    #
    # The metric rows live INSIDE the release they describe, so that
    # release's own fingerprint cannot be one of them -- the fingerprint is
    # taken over bytes that include them. `trained_against_fingerprint` is
    # the fingerprint the model was FITTED on, recorded as exactly that.
    shape = {dom.CORPORATE: ("reporting_quarter", "whatif_corp_model_metric"),
             dom.RETAIL: ("reporting_month", "whatif_retail_model_metric")}
    period_column, relation = shape[domain_id]
    stamp = {"tenant_id": lake.DEFAULT_TENANT,
             "dataset_release_id": release_id, "domain_id": domain_id,
             "reporting_currency": "SAR", "origin": cs.ORIGIN}
    metrics = tr.metric_rows(result, stamp=stamp, period_column=period_column,
                             period=assignment.test[-1])
    (out_dir / domain_id / "model_metric.json").write_text(
        json.dumps({"relation": relation, "period_column": period_column,
                    "trained_against_fingerprint": lake.fingerprint(
                        release_id),
                    "rows": metrics}, indent=2, sort_keys=True, default=str),
        encoding="utf-8")
    print(f"  {len(metrics)} model-metric rows for {relation}")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--domain", choices=["corporate", "retail", "all"],
                        default="all")
    parser.add_argument("--artifacts", default=str(ARTIFACTS))
    parser.add_argument("--docs", default="docs/whatif")
    parser.add_argument("--evidence",
                        default="docs/whatif/evidence/emulators.json")
    args = parser.parse_args()

    absent = cp.missing()
    if absent:
        print("These component libraries are not importable here: "
              f"{', '.join(absent)}.\n"
              "This script runs in the CANDIDATE environment:\n"
              "    python3 -m venv .venv-whatif\n"
              "    .venv-whatif/bin/pip install -r requirements-whatif.txt\n"
              "    .venv-whatif/bin/python scripts/whatif/train_emulator.py\n"
              "The accepted environment does not have them and is not meant "
              "to.")
        return 2

    domains = ([dom.CORPORATE, dom.RETAIL] if args.domain == "all"
               else [dom.parse(args.domain)])
    record: dict[str, object] = {
        "origin": cs.ORIGIN,
        "model_version": ml.MODEL_VERSION,
        "note": ("Trained on generated books against a target produced by "
                 "reference_ecl.py. Not bank-engine validation, and no "
                 "agreement with any bank's ECL engine is established."),
        "libraries": cp.available(),
        "books": {},
    }
    failed = False

    for domain_id in domains:
        release_id = cs.RELEASES[domain_id]
        if not lake.exists(release_id):
            print(f"{release_id} is not published; run "
                  f"scripts/whatif/seed_candidate.py")
            return 2
        print(f"\ntraining {domain_id} on {release_id} ...")
        started = time.time()
        result = run(domain_id, out_dir=Path(args.artifacts))
        failed = failed or not result.passed

        card_path = Path(args.docs) / (
            f"MODEL_CARD_{domain_id.upper()}.md")
        card_path.parent.mkdir(parents=True, exist_ok=True)
        card_path.write_text(cd.markdown(result), encoding="utf-8")
        print(f"  card written to {card_path}")

        record["books"][release_id] = {
            "domain_id": domain_id,
            "release_fingerprint": lake.fingerprint(release_id),
            "blend": result.blended.by_name,
            "blend_headline": result.blended.headline,
            "metrics": {k: round(v, 8)
                        for k, v in result.metrics.items()},
            "reference_model": {k: round(v, 8)
                                for k, v in result.reference.items()},
            "gates": result.gates,
            "counts": result.counts,
            "passed": result.passed,
            "failures": result.failures(),
            "seconds": round(time.time() - started, 1),
        }

    target = Path(args.evidence)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(record, indent=2, sort_keys=True,
                                 default=str), encoding="utf-8")
    print(f"\nevidence written to {target}")
    if failed:
        print("\nAt least one predeclared gate FAILED. That is the reported "
              "outcome: the card says so, the metric rows carry the measured "
              "value, and Method 2 reports its limitation. "
              "ML_ACCEPTANCE_TARGETS.md is not edited.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
