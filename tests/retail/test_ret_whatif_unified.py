"""Phase 4: one What-If, whichever door it was opened through.

§8 (one thread family), §9 (units and exact targeting), §10 (model pages).
Arithmetic is checked on fixtures small enough to verify by hand; the rest is
checked against the book, where the point is that the pieces agree.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backend.retail import whatif as W
from backend.retail import whatif_cohort as C
from backend.retail import whatif_language as L
from backend.retail import whatif_selection as SEL


# ============ UNITS: a percent and a percentage point are two scenarios =====

def test_wif_01_lgd_percentage_points_is_a_supported_shock() -> None:
    """§9 names it, and says not to delete the chip to make a test pass."""
    assert "lgd_absolute_pp" in W.SUPPORTED_METHODOLOGIES
    assert "lgd_absolute_pp" in W.WATERFALL_ORDER
    assert "lgd_absolute_pp" in W.WATERFALL_LABELS


@pytest.mark.parametrize("said,expected", [
    ("Increase LGD by 5 percentage points", {"lgd_absolute_pp": 5.0}),
    ("Add 5 percentage points to LGD for Stage 2 Home Finance",
     {"lgd_absolute_pp": 5.0}),
    ("Reduce LGD by 3 percentage points", {"lgd_absolute_pp": -3.0}),
    ("Increase LGD by 5%", {"lgd_relative": 0.05}),
    ("Add 2 percentage points to PD", {"pd_absolute_pp": 2.0}),
    ("Increase PIT 12-month PD by 20%", {"pd_relative": 0.20}),
    ("Increase CCF by 10 percentage points on eligible undrawn lines",
     {"ccf_absolute_pp": 10.0}),
])
def test_wif_02_the_unit_decides_which_shock(said, expected) -> None:
    ask = L.read(said)
    assert not ask.question, f"{said!r} was refused: {ask.question}"
    for key, value in expected.items():
        assert ask.shocks.get(key) == pytest.approx(value), (said, ask.shocks)


def test_wif_03_no_unit_asks_rather_than_guesses() -> None:
    ask = L.read("Increase LGD by 5")
    assert ask.question and "percentage points" in ask.question
    assert {one["id"] for one in ask.options} == {"relative", "absolute"}
    offered = {}
    for one in ask.options:
        offered.update(one["shocks"])
    assert "lgd_relative" in offered and "lgd_absolute_pp" in offered


def test_wif_04_a_stage_number_is_not_an_amount() -> None:
    """The defect: "5 percentage points to LGD for Stage 2" read the 2."""
    ask = L.read("Add 5 percentage points to LGD for Stage 2 Home Finance")
    assert ask.shocks.get("lgd_absolute_pp") == pytest.approx(5.0)


def test_wif_05_setting_the_ccf_is_not_moving_it() -> None:
    """`ccf_absolute` SETS. Read as a set, "increase CCF by 10 percentage
    points" moved the published 0.45 to 0.10 — a reduction."""
    moved = L.read("Increase CCF by 10 percentage points")
    assert moved.shocks == {"ccf_absolute_pp": 10.0}
    put = L.read("Set CCF to 0.6")
    assert put.shocks == {"ccf_absolute": 0.6}


# ============ the engine actually moves, and says when it clipped ===========

def _book(n: int = 200) -> pd.DataFrame:
    from backend.retail import ews_score as S

    frame = S._read_book("2026-08")
    return frame[frame["product_code"] == "CREDIT_CARD"].head(n)


def _ecl(frame: pd.DataFrame, shocks: dict) -> tuple[float, dict]:
    from backend.retail.config import load_config

    scenario = W.Scenario(name="t", dataset_version="",
                          snapshot_date=str(frame["snapshot_date"].iloc[0]),
                          filters={}, shocks=shocks)
    out = W.run(frame, scenario, load_config(), decompose=False)
    return out["scenario_result"]["ecl_final_sar"], out


def test_wif_06_points_and_percent_give_different_answers(book_slice) -> None:
    points, _ = _ecl(book_slice, {"lgd_absolute_pp": 5.0})
    percent, _ = _ecl(book_slice, {"lgd_relative": 0.05})
    base, _ = _ecl(book_slice, {})
    assert points > base and percent > base
    assert points != percent, (
        "a percentage-point move and a relative move returned the same "
        "number, so one of them is not being applied")


def test_wif_07_a_bound_that_was_hit_is_reported(book_slice) -> None:
    _, out = _ecl(book_slice, {"lgd_absolute_pp": 60.0})
    assert out["bounded"].get("lgd_absolute_pp"), (
        "+60pp cannot leave every LGD inside the policy's cap")
    assert any("LGD floor or cap" in one for one in out["limitations"])


def test_wif_08_moving_the_ccf_up_does_not_reduce_ecl(book_slice) -> None:
    base, _ = _ecl(book_slice, {})
    up, _ = _ecl(book_slice, {"ccf_absolute_pp": 10.0})
    down, _ = _ecl(book_slice, {"ccf_absolute": 0.10})
    assert up > base, "more of the undrawn line in EAD must not lower ECL"
    assert down < base, "setting the factor to 0.10 from 0.45 must lower it"


@pytest.fixture(scope="module")
def book_slice():
    return _book()


# ================== every shock reads as a sentence =========================

def test_wif_09_no_shock_falls_through_to_its_identifier() -> None:
    """The defect: the reader was shown "lgd_absolute_pp = 5.0".

    The identifier IS the fallback in `_describe`, so a shock without a line
    leaks it into the user journey — which §2.1 lists as a defect to remove.
    """
    missing = [one for one in W.SUPPORTED_METHODOLOGIES if one not in C._SAYS]
    assert not missing, f"no business wording for {missing}"


def test_wif_10_a_migration_reads_as_a_sentence() -> None:
    said = C._describe({"dpd_migration": {"from": "30-59", "to": "90-179",
                                          "share": 0.2, "basis": "exposure"}})
    assert said == "20% of exposure moved from delinquency bucket 30-59 to 90-179"
    assert "_" not in said


# ============== SELECTION: a guided cohort is a real selection ==============

GUIDED = [
    ("whole Retail", {}),
    ("DPD bucket", {"dpd_bucket": "30-59"}),
    ("behavioural band", {"behavioural_band": "C"}),
    ("stage", {"stage": "2"}),
    ("product and classification",
     {"product": "CREDIT_CARD", "classification": "NON_SALARIED"}),
    ("sub-product", {"product": "CREDIT_CARD", "sub_product": "CC_PLATINUM"}),
    ("forward risk", {"cohort": "forward_risk"}),
]


@pytest.mark.parametrize("label,filters", GUIDED,
                         ids=[one[0] for one in GUIDED])
def test_sel_01_every_guided_card_selects_a_real_cohort(label, filters) -> None:
    made = SEL.create(month="2026-08", level="cohort", route="/what-if",
                      source_module=SEL.SOURCE_GUIDED, label=label, **filters)
    assert made.selected_account_count > 0, label
    assert made.selected_customer_count > 0, label
    assert made.selected_exposure_sar > 0, label
    assert made.source_module == SEL.SOURCE_GUIDED
    # Membership is recorded, not re-queried later.
    assert len(made.selected_facility_ids) == made.selected_account_count


def test_sel_02_a_standalone_cohort_is_the_whole_book() -> None:
    from backend.retail import ews_score as S

    made = SEL.create(month="2026-08", level="cohort", route="/what-if",
                      source_module=SEL.SOURCE_STANDALONE, label="Retail")
    frame = S.read("2026-08")
    assert made.selected_account_count == int(frame["facility_id"].nunique())
    assert made.selected_customer_count == int(frame["customer_id"].nunique())


def test_sel_03_an_empty_cohort_refuses_rather_than_returns_zero() -> None:
    with pytest.raises(ValueError, match="empty selection"):
        SEL.create(month="2026-08", product="CREDIT_CARD",
                   sub_product="HL_VILLA", source_module=SEL.SOURCE_GUIDED)


# ==================== THREADS: the conversation survives ====================

def test_thr_01_a_thread_persists_its_turns(thread) -> None:
    from backend.retail import whatif_thread as T

    T.append(thread, {"kind": T.SAID, "text": "Increase LGD by 5 pp"}, owner=1)
    T.append(thread, {"kind": T.RESULT, "method": "delta"}, owner=1)
    # Read back through a fresh call — nothing in memory carries over.
    got = T.get(thread, owner=1)
    assert [one["kind"] for one in got.turns] == [T.SAID, T.RESULT]
    assert got.turns[0]["n"] == 1 and got.turns[1]["n"] == 2


def test_thr_02_a_thread_belongs_to_its_owner(thread) -> None:
    from backend.retail import whatif_thread as T

    assert T.get(thread, owner=1) is not None
    assert T.get(thread, owner=999) is None


def test_thr_03_undo_removes_the_last_exchange(thread) -> None:
    from backend.retail import whatif_thread as T

    T.append(thread, {"kind": T.SAID, "text": "one"}, owner=1)
    T.append(thread, {"kind": T.RESULT, "method": "delta"}, owner=1)
    T.append(thread, {"kind": T.SAID, "text": "two"}, owner=1)
    T.append(thread, {"kind": T.RESULT, "method": "delta"}, owner=1)
    after = T.remove_last_result(thread, owner=1)
    assert [one.get("text") for one in after.turns
            if one["kind"] == T.SAID] == ["one"]


def test_thr_04_the_method_is_remembered(thread) -> None:
    from backend.retail import whatif_thread as T

    T.set_method(thread, method="xgboost", staging_mode="reevaluate_stage",
                 owner=1)
    got = T.get(thread, owner=1)
    assert got.method == "xgboost"
    assert got.staging_mode == "reevaluate_stage"


@pytest.fixture
def thread():
    from backend.retail import whatif_thread as T

    made = T.create(title="test", selection_id="EWSEL-TEST", month="2026-08",
                    opened_from=T.FROM_STANDALONE, owner=1)
    return made.thread_id
