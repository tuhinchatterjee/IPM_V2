"""Retail Method 2 is NOT READY, and the product says so where a reader looks.

UNIT. NO MODEL is fitted, loaded or predicted from here: what is read is the
COMMITTED gate verdicts in `artifacts/whatif/retail/blend.json`, which the
training run wrote and which nothing in a chat turn may edit. No provider, no
database, no browser.

This module exists because "Retail Method 2 failed its gate" is a claim about
the PRODUCT SURFACE, not only about a metric in a model card. The gate is
recorded elsewhere; what is asserted here is the chain from that record to the
sentence a reader sees:

* the committed verdict really is a FAILURE, at the value and against the
  threshold that were predeclared -- 34.36% against 15% -- and the threshold
  is not moved, the group is not excluded, and materiality is not redefined;
* `infer.Loaded` reads that verdict rather than a summary of it, so
  `passed_every_gate` is False and `failures()` names G4 with both numbers;
* `bridge._ml_inputs` -- the product's own code, not this test's prose --
  turns it into the reason text, and returns NO anchored prediction, so there
  is nothing for a caller to mistake for an estimate;
* the composed comparison shows three rows: Delta COMPLETE, Emulator
  NOT READY with the reason, and Your assumption COMPLETE;
* the Emulator's cells are EMPTY -- `scenario` and `change` are `None`, not
  `"0"` -- and its baseline is the same baseline the other two started from,
  so nothing silently fell back to Delta and Corporate's model did not stand
  in.
"""

from __future__ import annotations

import json
import pathlib
from decimal import Decimal

import pytest

from backend.cockpit_v4.scenario import bridge as br
from backend.cockpit_v4.scenario import run as rn
from backend.cockpit_v4.scenario import spec as sp
from backend.cockpit_v4.scenario.ml import infer
from tests.cockpit_v4.test_whatif_run import plan_for, rows, spec_for

ROOT = pathlib.Path(__file__).resolve().parents[2]
BLEND = ROOT / "artifacts" / "whatif" / "retail" / "blend.json"

#: The predeclared G4 threshold, as `ML_ACCEPTANCE_TARGETS_V2.md` states it.
#: Written here as a literal on purpose: if the gate in code is ever loosened
#: to make this suite pass, this line is what fails.
G4_THRESHOLD = 0.15


@pytest.fixture(scope="module")
def committed() -> dict:
    assert BLEND.exists(), (
        f"{BLEND} is not published. The Retail emulator's verdict is part of "
        f"the candidate's evidence, not something re-derived at test time.")
    return json.loads(BLEND.read_text(encoding="utf-8"))


def _loaded(gates: dict) -> infer.Loaded:
    """A `Loaded` carrying the REAL gates and no models.

    `infer.load` unpickles the component boosters, which needs the candidate
    environment's libraries. The gate verdicts need none of that, and the
    verdicts are the whole question here, so the object is built directly
    from the committed manifest.
    """
    return infer.Loaded(
        domain_id="retail", model_version="whatif-ecl-emulator-2.0.0",
        release_id="v4-whatif-retail-20m-s1", features=(), categorical=(),
        weights={}, headline="", models={}, gates=gates)


# ==========================================================================
# The verdict on disk
# ==========================================================================

def test_the_committed_retail_verdict_is_a_failure_at_the_declared_gate(
        committed) -> None:
    g4 = (committed.get("gates") or {})["G4"]
    assert g4["passed"] is False
    assert g4["threshold"] == pytest.approx(G4_THRESHOLD), (
        "G4's threshold moved. It was declared before the model was fitted "
        "and before the test split was read; moving it is the one thing "
        "this gate exists to prevent.")
    assert g4["measured"] == pytest.approx(0.343562, abs=1e-6)
    assert round(g4["measured"] * 100, 2) == 34.36
    assert g4["measured"] > g4["threshold"]
    assert "material-group" in g4["what"]


def test_the_other_three_retail_gates_passed_so_the_failure_is_specific(
        committed) -> None:
    """G4 alone failed. The row is NOT READY for a stated reason, which is a
    different claim from "the model is broken"."""
    gates = committed["gates"]
    assert [name for name, g in sorted(gates.items()) if not g["passed"]] \
        == ["G4"]


def test_the_loaded_model_reports_the_failure_rather_than_a_summary(
        committed) -> None:
    loaded = _loaded(committed["gates"])
    assert loaded.passed_every_gate is False
    failures = loaded.failures()
    assert len(failures) == 1
    assert "G4" in failures[0]
    assert "0.3436" in failures[0] and "0.1500" in failures[0], (
        f"both numbers must travel with the failure, so a reader is not "
        f"asked to take the verdict on trust: {failures[0]!r}")


# ==========================================================================
# The product's own reason text
# ==========================================================================

def test_the_products_own_code_turns_the_failed_gate_into_the_reason(
        committed, monkeypatch) -> None:
    """`_ml_inputs` is the single place the engine decides whether Method 2
    has an answer. The reason a reader sees is built HERE, not in a test."""
    loaded = _loaded(committed["gates"])
    monkeypatch.setattr(infer, "load", lambda *a, **k: loaded)
    spec = spec_for(methods=(sp.DELTA, sp.ML))
    got, anchored, reason = br._ml_inputs(
        spec, rows=rows(), domain_id="retail",
        release_id="v4-whatif-retail-20m-s1", plan=plan_for(spec))

    assert got is loaded
    assert anchored is None, (
        "a model that missed a predeclared gate must not hand back an "
        "anchored prediction at all; there is then nothing to mistake for "
        "an estimate")
    assert "did not pass its predeclared validation gates" in reason
    assert "G4" in reason and "0.3436" in reason
    assert "model-development evidence" in reason


def test_the_reason_never_offers_another_model_or_a_zero(
        committed, monkeypatch) -> None:
    monkeypatch.setattr(infer, "load", lambda *a, **k: _loaded(
        committed["gates"]))
    spec = spec_for(methods=(sp.DELTA, sp.ML))
    _, _, reason = br._ml_inputs(
        spec, rows=rows(), domain_id="retail",
        release_id="v4-whatif-retail-20m-s1", plan=plan_for(spec))
    lowered = reason.lower()
    assert "corporate" not in lowered, (
        "Corporate's validated emulator must never be offered as Retail's")
    assert "zero" not in lowered
    assert "instead we use" not in lowered and "falls back" not in lowered


# ==========================================================================
# What the comparison shows
# ==========================================================================

@pytest.fixture()
def compared(committed, monkeypatch) -> dict:
    monkeypatch.setattr(infer, "load", lambda *a, **k: _loaded(
        committed["gates"]))
    spec = spec_for(methods=(sp.DELTA, sp.ML, sp.USER_DEFINED),
                    user_assumption={"form": "relative", "value": "10",
                                     "stated_as": "10% higher"})
    book = rows()
    _, _, reason = br._ml_inputs(
        spec, rows=book, domain_id="retail",
        release_id="v4-whatif-retail-20m-s1", plan=plan_for(spec))
    outcome = rn.execute(spec, book, key="facility_id",
                         ecl_column="ecl_sar_mn", plan=plan_for(spec),
                         ml_unavailable=reason)
    return outcome.compare()


def test_all_three_methods_keep_their_row(compared) -> None:
    """Section 2's rule: the method is not removed post hoc. A reader who
    asked to compare every method sees every method."""
    methods = [row["method"] for row in compared["own_population"]]
    assert methods == [sp.DELTA, sp.ML, sp.USER_DEFINED]


def test_the_comparison_reads_complete_not_ready_complete(compared) -> None:
    verdicts = {row["method"]: row["verdict"]
                for row in compared["own_population"]}
    assert verdicts == {sp.DELTA: "COMPLETE", sp.ML: "NOT READY",
                        sp.USER_DEFINED: "COMPLETE"}


def test_the_reader_facing_verdict_is_a_translation_not_a_second_opinion(
        compared) -> None:
    """The analytical status is what the code branches on and it does not
    move; the verdict beside it is copy derived from it."""
    for row in compared["own_population"]:
        assert row["verdict"] == rn.VERDICTS[row["status"]]
    statuses = {row["method"]: row["status"]
                for row in compared["own_population"]}
    assert statuses[sp.ML] == rn.UNAVAILABLE


def test_the_emulators_cells_are_empty_and_not_zero(compared) -> None:
    ml_row = next(r for r in compared["own_population"]
                  if r["method"] == sp.ML)
    assert ml_row["scenario"] is None
    assert ml_row["change"] is None
    assert ml_row["scenario"] != "0" and ml_row["change"] != "0"
    assert ml_row["rows_covered"] == 0


def test_the_validation_reason_is_reachable_from_the_published_row(
        compared) -> None:
    """The reason is IN the row a reader is looking at -- not in a log, not
    in a model card they would have to be told about."""
    ml_row = next(r for r in compared["own_population"]
                  if r["method"] == sp.ML)
    assert "G4" in ml_row["reason"]
    assert "0.3436" in ml_row["reason"]
    assert "validation gates" in ml_row["reason"]


def test_the_status_line_names_the_gate_beside_the_not_ready_verdict(
        compared) -> None:
    line = compared["status_line"]
    assert "Emulator NOT READY" in line
    assert "G4" in line and "0.3436" in line
    assert "Delta (proportional) COMPLETE" in line
    assert "Your assumption COMPLETE" in line


def test_nothing_fell_back_to_delta(compared) -> None:
    """The two methods that DID run are not the same answer twice, and the
    emulator's absence did not become Delta's number wearing its label."""
    ran = [r for r in compared["own_population"] if r["scenario"] is not None]
    assert len(ran) == 2
    assert {r["method"] for r in ran} == {sp.DELTA, sp.USER_DEFINED}
    assert compared["baselines_identical"] is True
    delta = next(r for r in ran if r["method"] == sp.DELTA)
    assert Decimal(delta["baseline"]) > 0


def test_the_comparison_still_refuses_to_compose_the_methods(
        compared) -> None:
    assert "not multiplied by the Delta factor" in compared["never_composed"]
