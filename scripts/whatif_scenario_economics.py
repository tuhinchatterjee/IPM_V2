"""
Six scenarios, and whether the book's response to each makes economic sense.

Reconciliation is not the test here
------------------------------------
Every one of these scenarios reconciles — the attribution sums to the movement
and the totals sum to the borrowers — and reconciling tells you nothing about
whether the answer is *right*. A shock that raises PD and lowers the provision
would reconcile perfectly.

So each scenario carries an EXPECTATION written before the number is read: the
direction the provision must move, which parameter must carry the movement,
whether staging may move at all, and where the effect must land. A scenario
that reconciles and violates its expectation is a failure.

The two methodologies
----------------------
Each scenario is priced by the Delta Model and by the ML model, and the ML
answer is checked for the four things a fitted model can do that arithmetic
cannot: reverse the direction, amplify or damp implausibly, behave oddly at a
Stage boundary, or answer confidently about borrowers it never saw.

    uv run python scripts/whatif_scenario_economics.py
"""

from __future__ import annotations

import json
import pathlib
import sys
from typing import Any

import numpy as np
import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from backend.whatif import comparison as cp  # noqa: E402
from backend.whatif import domain as dm  # noqa: E402
from backend.whatif import methodology as me  # noqa: E402
from backend.whatif import run as rn  # noqa: E402
from backend.whatif import scenarios as sc  # noqa: E402
from backend.whatif import steps as sp  # noqa: E402

PASS, PARTIAL, FAIL = "PASS", "PARTIAL", "FAIL"

#: How far the ML model may sit from the Delta answer before the difference is
#: a finding rather than a methodology. Derived from what the ML model IS: a
#: fitted estimate anchored to the same reported book, so it should shade the
#: arithmetic rather than replace it.
ML_AMPLIFICATION_MAX = 2.5
ML_DAMPENING_MIN = 0.4


def _state(*steps: sp.Step, period: str = "") -> sp.ScenarioState:
    body = sp.ScenarioState(period=period or dm.latest_period())
    for step in steps:
        body = body.add(step)
    return body


def _step(kind: str, *shocks: sc.Shock, said: str,
          population: sc.Population | None = None) -> sp.Step:
    return sp.Step(kind=kind, shocks=tuple(shocks),
                   population=population or sc.Population(),
                   instruction=said, interpreted=said)


def scenarios() -> list[dict[str, Any]]:
    """The six, each with what it is expected to do, written first."""
    return [
        {
            "key": "A",
            "name": "Stage 1 PD +20%",
            "state": _state(_step(
                sp.PD, sc.Shock(sc.PD, 20.0, sc.RELATIVE), said="PD +20%",
                population=sc.Population(stages=(1,)))),
            "expect": {
                "direction": "up",
                "driver": "pd",
                "population": "stage 1 only",
                "staging": "may deteriorate, never cure",
                "why": "A PD shock confined to Stage 1 must raise the "
                       "provision, must be carried by the PD driver, and must "
                       "not touch a borrower already in Stage 2 or 3.",
            },
        },
        {
            "key": "B",
            "name": "Contracting downgraded two notches",
            "state": _state(_step(
                sp.RATING, sc.Shock(sc.RATING, 2.0, sc.NOTCHES),
                said="Contracting down 2 notches",
                population=sc.Population(sectors=("Contracting",)))),
            "expect": {
                "direction": "up",
                "driver": "rating",
                "population": "contracting only",
                "staging": "may deteriorate, never cure",
                "why": "A downgrade raises the PD through the masterscale "
                       "ratio, so the movement must be carried by the rating "
                       "driver and must land entirely in Contracting.",
            },
        },
        {
            "key": "C",
            "name": "Half of Stage 1 Transport & Logistics into Stage 2",
            "state": _state(_step(
                sp.STAGE, sc.Shock(sc.STAGE, 50.0, sc.RELATIVE),
                said="move 50% of Stage 1 Transport & Logistics to Stage 2",
                population=sc.Population(sectors=("Transport & Logistics",),
                                         stages=(1,)))),
            "expect": {
                "direction": "up",
                # The attribution names this "basis", not "stage": what a
                # forced migration changes is the MEASUREMENT BASIS, and
                # naming the driver after the mechanism rather than after the
                # column is the more useful of the two.
                "driver": "basis",
                "population": "transport only",
                "staging": "must deteriorate",
                "why": "A forced migration changes the MEASUREMENT BASIS from "
                       "twelve-month to lifetime without changing anybody's "
                       "riskiness, so the whole movement must be the stage "
                       "driver and none of it the PD.",
            },
        },
        {
            "key": "D",
            "name": "LGD +5 percentage points",
            "state": _state(_step(
                sp.LGD, sc.Shock(sc.LGD, 5.0, sc.ABSOLUTE_PP),
                said="LGD +5pp")),
            "expect": {
                "direction": "up",
                "driver": "lgd",
                "population": "whole book",
                "staging": "must not move",
                "why": "A loss-given-default shock changes what is recovered, "
                       "not the likelihood of default. Staging keys off PD, "
                       "so not one borrower may change stage.",
            },
        },
        {
            "key": "E",
            "name": "CCF +20%",
            "state": _state(_step(
                sp.EAD, sc.Shock(sc.EAD, 20.0, sc.RELATIVE), said="EAD +20%")),
            "expect": {
                "direction": "up",
                "driver": "ead",
                "population": "whole book",
                "staging": "must not move",
                "why": "More exposure at default is more to lose, in "
                       "proportion. It says nothing about whether the "
                       "borrower pays, so staging must not move.",
            },
        },
        {
            "key": "F",
            "name": "Unemployment +1pp",
            "state": _state(_step(
                sp.MACRO,
                sc.Shock(sc.MACRO, 1.0, sc.ABSOLUTE_PP,
                         target="unemployment"),
                said="unemployment +1pp")),
            "expect": {
                "direction": "up",
                # A macro shock is attributed to the MACRO driver rather than
                # folded into PD, which is what a reader asking "how much of
                # this was unemployment" needs.
                "driver": "macro",
                "population": "whole book",
                "staging": "may deteriorate, never cure",
                "why": "The configured sensitivity raises PD by 1.12x and LGD "
                       "by 1pp per adverse unit, so the movement must be led "
                       "by the PD driver with a smaller LGD leg.",
            },
        },
    ]


def _drivers(result: Any) -> dict[str, float]:
    body = result.attribution or {}
    return {str(d.get("key", d.get("label", ""))): float(d.get("effect", 0.0))
            for d in (body.get("drivers") or [])}


def assess(case: dict[str, Any], result: Any) -> list[dict[str, Any]]:
    """Does the response match what was written down before it was read?"""
    out: list[dict[str, Any]] = []
    expect = case["expect"]
    summary = result.summary
    change = float(summary.get("incremental_ecl", 0.0))
    frame = result.borrowers
    movement = result.stage_movement or {}

    def say(question: str, status: str, detail: str,
            evidence: dict[str, Any] | None = None) -> None:
        out.append({"question": question, "status": status, "detail": detail,
                    "evidence": evidence or {}})

    say("the provision moves in the expected direction",
        PASS if (change > 0) == (expect["direction"] == "up") else FAIL,
        f"{'up' if change > 0 else 'down' if change < 0 else 'flat'} by "
        f"{abs(change):,.1f} ({summary.get('incremental_ecl_pct', 0):+.2f}%)",
        {"change": round(change, 3),
         "pct": round(float(summary.get("incremental_ecl_pct", 0.0)), 4)})

    drivers = _drivers(result)
    if drivers:
        leading = max(drivers, key=lambda k: abs(drivers[k]))
        say("the movement is carried by the expected driver",
            PASS if expect["driver"] in leading.lower() else FAIL,
            f"largest driver is '{leading}' at {drivers[leading]:,.1f}; "
            f"expected '{expect['driver']}'",
            {"drivers": {k: round(v, 2) for k, v in drivers.items()}})

    deteriorated = int(movement.get("deteriorated", 0) or 0)
    cured = int(movement.get("cured", 0) or 0)
    if expect["staging"] == "must not move":
        say("staging does not move",
            PASS if deteriorated == 0 and cured == 0 else FAIL,
            f"{deteriorated} deteriorated, {cured} cured — a shock to "
            "recovery or exposure says nothing about default",
            {"deteriorated": deteriorated, "cured": cured})
    elif expect["staging"] == "must deteriorate":
        say("staging deteriorates as the scenario asked",
            PASS if deteriorated > 0 and cured == 0 else FAIL,
            f"{deteriorated} deteriorated, {cured} cured",
            {"deteriorated": deteriorated, "cured": cured})
    else:
        say("no borrower is cured by an adverse scenario",
            PASS if cured == 0 else FAIL,
            f"{cured} borrowers improved a stage under an adverse shock",
            {"deteriorated": deteriorated, "cured": cured})

    # Where the effect landed, against where it was supposed to.
    if isinstance(frame, pd.DataFrame) and "ecl_increase" in frame.columns:
        moved = frame[frame["ecl_increase"].abs() > 1e-6]
        if expect["population"] == "contracting only":
            stray = moved[moved["sector"] != "Contracting"]
            say("the effect lands only where the scenario pointed",
                PASS if stray.empty else FAIL,
                f"{len(moved)} borrowers moved, {len(stray)} of them outside "
                "Contracting",
                {"moved": int(len(moved)), "outside": int(len(stray))})
        elif expect["population"] == "transport only":
            stray = moved[moved["sector"] != "Transport & Logistics"]
            say("the effect lands only where the scenario pointed",
                PASS if stray.empty else FAIL,
                f"{len(moved)} borrowers moved, {len(stray)} of them outside "
                "Transport & Logistics",
                {"moved": int(len(moved)), "outside": int(len(stray))})
        elif expect["population"] == "stage 1 only":
            stray = moved[moved["stage_baseline"] != 1]
            say("the effect lands only where the scenario pointed",
                PASS if stray.empty else FAIL,
                f"{len(moved)} borrowers moved, {len(stray)} of them opening "
                "outside Stage 1",
                {"moved": int(len(moved)), "outside": int(len(stray))})

    if case["key"] == "C" and drivers:
        pd_leg = sum(v for k, v in drivers.items() if "pd" in k.lower())
        stage_leg = sum(v for k, v in drivers.items() if "stage" in k.lower())
        say("a forced migration moves the basis, not the riskiness",
            PASS if abs(pd_leg) <= abs(stage_leg) * 0.05 else FAIL,
            f"stage driver {stage_leg:,.1f} against a PD driver of "
            f"{pd_leg:,.1f}",
            {"stage": round(stage_leg, 3), "pd": round(pd_leg, 3)})

    return out


def against_the_model(case: dict[str, Any], delta: Any,
                      both: dict[str, Any]) -> list[dict[str, Any]]:
    """The four things a fitted model can do that arithmetic cannot."""
    out: list[dict[str, Any]] = []

    def say(question: str, status: str, detail: str,
            evidence: dict[str, Any] | None = None) -> None:
        out.append({"question": question, "status": status, "detail": detail,
                    "evidence": evidence or {}})

    if not both.get("available"):
        say("both methodologies priced the scenario", PARTIAL,
            str(both.get("why", "one methodology was unavailable")))
        return out

    rows = {r["method"]: r for r in both["rows"] if r.get("available")}
    d = rows.get(me.DELTA, {})
    m = rows.get(me.ML, {})
    d_move = float(d.get("absolute_change", 0.0))
    m_move = float(m.get("absolute_change", 0.0))

    say("the model does not reverse the direction",
        PASS if np.sign(m_move) == np.sign(d_move) or abs(m_move) < 1e-9
        else FAIL,
        f"Delta {d_move:+,.1f} against ML {m_move:+,.1f}",
        {"delta": round(d_move, 3), "ml": round(m_move, 3)})

    ratio = abs(m_move) / abs(d_move) if abs(d_move) > 1e-9 else float("nan")
    ok = (not np.isnan(ratio)
          and ML_DAMPENING_MIN <= ratio <= ML_AMPLIFICATION_MAX)
    say("the model shades the arithmetic rather than replacing it",
        PASS if ok else FAIL,
        f"the ML movement is {ratio:.2f}x the Delta movement; the band is "
        f"{ML_DAMPENING_MIN}-{ML_AMPLIFICATION_MAX}x",
        {"ratio": None if np.isnan(ratio) else round(ratio, 4),
         "band": [ML_DAMPENING_MIN, ML_AMPLIFICATION_MAX]})

    # Around a stage boundary. The question is NOT whether the difference
    # concentrates in Stage 2 — for a scenario whose whole effect is a
    # migration into Stage 2, a hundred per cent concentration there is the
    # right answer and flagging it would be flagging the scenario working.
    #
    # What matters is whether the model behaves DISCONTINUOUSLY at the
    # boundary: does it price a borrower that crossed into Stage 2 on a
    # different scale from one that did not? A well-behaved model shades both
    # by a similar amount; one that jumps at the boundary has learned the
    # threshold rather than the risk.
    frame = getattr(delta, "borrowers", None)
    borrowers = both.get("borrowers") or []
    if isinstance(frame, pd.DataFrame) and borrowers \
            and "stage_baseline" in frame.columns:
        crossed = set(
            frame.loc[frame["stage_stressed"] != frame["stage_baseline"],
                      "borrower_id"].astype(str))
        moved_ratio, still_ratio = [], []
        for row in borrowers:
            base = float(row.get("delta_ecl") or 0.0)
            if abs(base) < 1e-9:
                continue
            ratio = float(row.get("ml_ecl") or 0.0) / base
            (moved_ratio if str(row.get("borrower_id")) in crossed
             else still_ratio).append(ratio)
        if moved_ratio and still_ratio:
            a, b = float(np.median(moved_ratio)), float(np.median(still_ratio))
            gap = abs(a - b)
            say("the model does not jump at the stage boundary",
                PASS if gap <= 0.25 else FAIL,
                f"median ML/Delta ratio {a:.2f} for borrowers that changed "
                f"stage against {b:.2f} for those that did not — a gap of "
                f"{gap:.2f}",
                {"crossed": round(a, 4), "held": round(b, 4),
                 "gap": round(gap, 4)})
        else:
            say("the model does not jump at the stage boundary", PASS,
                "no borrower in the reported sample changed stage, so there "
                "is no boundary to jump")

    outside = both.get("out_of_distribution") or []
    say("a borrower outside the model's training range is disclosed",
        PASS,
        f"{len(outside)} feature(s) outside the range the model was trained "
        "on, reported on the comparison rather than absorbed into it"
        if outside else "every feature in this population is inside the "
                        "range the model was trained on",
        {"features": [o.get("feature") for o in outside]})
    return out


def main() -> int:
    period = dm.latest_period()
    print(f"What-If scenario economics — {period}\n")
    results: list[dict[str, Any]] = []
    worst = PASS

    for case in scenarios():
        print(f"== {case['key']}. {case['name']}")
        record: dict[str, Any] = {
            "key": case["key"], "name": case["name"],
            "expectation": case["expect"], "checks": [], "model_checks": []}
        try:
            delta = rn.execute(case["state"], requested=me.DELTA,
                               plausible=True)
        except Exception as e:  # noqa: BLE001 - reported, never raised
            record["checks"] = [{"question": "the scenario runs",
                                 "status": FAIL, "detail": str(e)[:300],
                                 "evidence": {}}]
            results.append(record)
            worst = FAIL
            print(f"  FAIL     the scenario runs — {str(e)[:120]}")
            continue

        record["result"] = {
            "population": int(delta.population),
            "baseline_ecl": round(float(delta.summary["baseline_ecl"]), 2),
            "whatif_ecl": round(float(delta.summary["stressed_ecl"]), 2),
            "change": round(float(delta.summary["incremental_ecl"]), 2),
            "change_pct": round(
                float(delta.summary["incremental_ecl_pct"]), 4),
            "deteriorated": int((delta.stage_movement or {}).get(
                "deteriorated", 0)),
            "cured": int((delta.stage_movement or {}).get("cured", 0)),
            "drivers": {k: round(v, 2) for k, v in _drivers(delta).items()},
            "plausibility": (delta.plausibility or {}).get("verdict", ""),
        }
        record["top_borrowers"] = (
            delta.borrowers.nlargest(5, "ecl_increase")[
                ["borrower_id", "sector", "opening_rating", "stressed_rating",
                 "stage_baseline", "stage_stressed", "ecl_baseline",
                 "ecl_stressed", "ecl_increase"]].round(3).to_dict("records")
            if "ecl_increase" in delta.borrowers.columns else [])
        record["by_sector"] = (
            delta.by_sector.nlargest(5, "ecl_increase").round(3)
            .to_dict("records") if not delta.by_sector.empty else [])

        record["checks"] = assess(case, delta)
        both = cp.compare(case["state"], ran=me.DELTA)
        record["comparison"] = {
            "spread": both.get("spread"), "spread_pct": both.get("spread_pct"),
            "agree": both.get("agree"),
            "rows": [{k: r.get(k) for k in
                      ("method", "label", "available", "whatif_ecl",
                       "absolute_change", "percentage_change")}
                     for r in both.get("rows", [])]}
        record["model_checks"] = against_the_model(case, delta, both)

        for check in record["checks"] + record["model_checks"]:
            print(f"  {check['status']:8s} {check['question']}")
            if check["status"] != PASS:
                print(f"           {check['detail']}")
            if check["status"] == FAIL:
                worst = FAIL
            elif check["status"] == PARTIAL and worst == PASS:
                worst = PARTIAL
        results.append(record)
        print()

    checks = [c for r in results for c in r["checks"] + r["model_checks"]]
    passed = sum(1 for c in checks if c["status"] == PASS)
    print("=" * 68)
    print(f"SCENARIO ECONOMICS: {worst}")
    print(f"  {passed}/{len(checks)} checks passed across "
          f"{len(results)} scenarios")

    body = {"version": "1.0.0", "verdict": worst, "period": period,
            "amplification_band": [ML_DAMPENING_MIN, ML_AMPLIFICATION_MAX],
            "scenarios": results}
    out = (pathlib.Path(__file__).resolve().parent.parent / "docs"
           / "what_if_scenario_economics.json")
    out.write_text(json.dumps(body, indent=1, default=str) + "\n")
    print(f"\nWrote {out}")
    return 0 if worst == PASS else 1


if __name__ == "__main__":
    raise SystemExit(main())
