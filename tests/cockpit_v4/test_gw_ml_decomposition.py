"""DECOMP02 / DECOMP03 / M042 on a real Method 2 (ML emulator) result.

Runs only where the ML runtime is installed (the candidate interpreter,
`.venv-whatif`); on the accepted interpreter, which by design carries no ML
library, it skips -- the regression runs it on the candidate interpreter.

Proves, on Corporate (where every emulator gate passes):
* the booked baseline and the emulator's own raw baseline are both
  published and differ, and the calibration gap is exactly their
  difference (DECOMP02);
* the ML scenario effect starts from the booked baseline and the gap is not
  inside it: the method's change equals its scenario minus the BOOKED
  baseline, and the decomposition names the gap N/A with its reason rather
  than folding it into a component (DECOMP03);
* metric M042 reads that published gap, per ML result (M042).

EVIDENCE LABEL: REAL DATABASE (governed candidate books, real emulator
artifacts); NO MODEL (no language model).
"""

# ruff: noqa: F811

from __future__ import annotations

from decimal import Decimal

import pytest

pytest.importorskip("lightgbm")
pytest.importorskip("xgboost")

from backend.workspace import access, metrics, service  # noqa: E402
from tests.cockpit_v4.test_gw_runs import (  # noqa: E402,F401 (fixtures)
    WHO,
    client,
    full_run,
    results,
    svc,
    uat_scenario,
    who,
)


def _ml_result(client, svc):
    obj, cohort = uat_scenario(svc)
    run, result = full_run(client, obj["object_id"], methods=("delta", "ml"),
                           cohort_id=cohort["object_id"])
    assert result is not None, run
    stored = svc.store.get(result["object_id"], tenant_id="demo-tenant")
    ml = stored["body"]["results"]["ml"]
    if not ml["ran"]:
        pytest.skip(f"Method 2 did not run here: {ml['reason']}")
    return stored


def test_decomp02_booked_and_model_baselines_are_both_published(client, svc):
    stored = _ml_result(client, svc)
    b = stored["body"]
    ml, delta = b["results"]["ml"], b["results"]["delta"]
    # Both methods report against the SAME booked baseline of the cohort.
    assert Decimal(ml["baseline"]) == Decimal(delta["baseline"])
    gap = Decimal(ml["calibration_gap"])
    assert gap != 0, "the emulator's raw baseline differs from booked ECL"
    facts = ml.get("facts") or {}
    if "raw_model_baseline" in facts:
        assert gap == Decimal(str(facts["raw_model_baseline"])) - \
            Decimal(str(facts["observed_modelled_ecl"]))


def test_decomp03_the_gap_is_not_inside_the_scenario_effect(client, svc):
    stored = _ml_result(client, svc)
    b = stored["body"]
    ml = b["results"]["ml"]
    d = b["decomposition"]["ml"]
    sel = d["scopes"]["selected"]
    # The ML change is scenario minus the BOOKED baseline: no gap in it.
    assert Decimal(ml["change"]) == Decimal(ml["scenario"]) - \
        Decimal(ml["baseline"])
    comps = {c["id"]: c for c in sel["components"]}
    gap = comps["calibration_gap"]
    assert gap.get("value") in (None, "", "0") or gap.get("not_applicable")
    reason = (sel.get("not_applicable") or {}).get("calibration_gap") or \
        gap.get("reason", "")
    assert "baseline gap is removed before the scenario effect" in reason
    # The whole ML move is one unattributed method effect equal to the
    # change; adding the gap anywhere would break this identity.
    effect = Decimal(comps["unattributed_method_effect"]["value"])
    assert effect == Decimal(ml["change"])
    assert Decimal(sel["opening"]) + effect == Decimal(sel["closing"])


def test_m042_reads_the_published_gap_per_ml_result(client, svc):
    stored = _ml_result(client, svc)
    book = access.book(WHO, "corporate")
    token = metrics.VIEWER.set(service.principal(WHO))
    try:
        got = metrics.evaluate(book, "M042")
    finally:
        metrics.VIEWER.reset(token)
    mine = [g for g in got["groups"] if g["object_id"] == stored["object_id"]]
    assert len(mine) == 1
    assert mine[0]["method"] == "ml"
    assert Decimal(str(mine[0]["value"])) == Decimal(
        stored["body"]["results"]["ml"]["calibration_gap"])
    assert got["value"] == mine[0]["value"]
    assert results(svc), "the ML result is persisted"
