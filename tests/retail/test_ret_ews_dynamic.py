"""
Proof that the Early Warning Score is DATA-DRIVEN and not a picture of one.

§28 of the rebuild brief asks for this directly, and it is the one claim a
screenshot cannot make: change a source variable, rescore, and watch the change
travel the whole chain —

    source variable -> trigger -> sub-layer -> layer -> overall score
                    -> severity -> reason codes -> product aggregate

Everything here runs against a DISPOSABLE copy of the lake. The published
domain is never written to, so a failing run cannot leave the demonstration
book in a state somebody has to notice.

The run also writes `docs/evidence/retail_ews_score/mutation.json`, which is
what the browser suite's EW-59 reads: a case that claims the UI is dynamic
without this having actually happened would be a green light nobody earned.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from backend.retail import ews_model as M
from backend.retail import profile

pytestmark = pytest.mark.skipif(
    not profile.is_retail(), reason="the corporate profile is active")

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "docs" / "evidence" / "retail_ews_score" / "mutation.json"

#: The customer whose salary we interrupt, chosen at run time: somebody with
#: nothing firing in the affordability layer, so the change has somewhere to
#: travel to.
TRIGGER = "salary_interruption"
SUBLAYER = "salary_behaviour"
LAYER = "affordability"
COLUMN = "salary_missed_cycle_count_3m"


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory) -> Path:
    """A disposable copy of the book and the domain.

    Only the months the test rescores are copied — the whole lake is several
    gigabytes and the proof needs two.
    """
    from backend.retail import ews_score as S

    months = S.scored_months()
    if len(months) < 2:
        pytest.skip("the Early Warning Score domain has not been built")

    root = tmp_path_factory.mktemp("ews-mutation")
    # The guard requires the word "retail" in the path before it will let
    # anything be written there.
    lake = root / "retail" / "analytics"
    lake.mkdir(parents=True)
    for month in months[-3:]:
        source = Path(S._root()) / S.BOOK / f"reporting_month={month}"
        target = lake / S.BOOK / f"reporting_month={month}"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, target)
    return lake


def _score(lake: Path, months: list[str]) -> None:
    from backend.retail import ews_score as S

    S.forget()
    S.build(analytics_dir=lake, replace=True, months=months)
    S.forget()


def _read(lake: Path, month: str):
    from backend.retail import ews_score as S

    S.forget()
    return S.read(month, analytics_dir=lake)


def test_a_source_change_travels_the_whole_chain(sandbox: Path) -> None:
    """The one test that proves the screen is not a painting."""
    import pandas as pd

    from backend.retail import ews_score as S
    from backend.retail import ews_views as V

    months = sorted(p.name.split("=", 1)[1]
                    for p in (sandbox / S.BOOK).iterdir() if p.is_dir())
    at = months[-1]

    _score(sandbox, months)
    before = _read(sandbox, at)

    # Somebody whose salary behaviour is quiet, so the change has room to move.
    quiet = before[(~before[f"trg_{TRIGGER}_fired"].fillna(False))
                   & (before["product_code"] == "CREDIT_CARD")]
    assert len(quiet), "no quiet card customer to disturb"
    row = quiet.sort_values("gross_carrying_amount_sar",
                            ascending=False).iloc[0]
    who, facility = str(row["customer_id"]), str(row["facility_id"])

    was = {
        "source": float(pd.to_numeric(row.get(COLUMN), errors="coerce") or 0.0),
        "sublayer": float(row[M.sublayer(SUBLAYER).score_column]),
        "layer": float(row[M.layer(LAYER).score_column]),
        "overall": float(row["ews_score"]),
        "severity": str(row["ews_severity"]),
        "reasons": [str(row.get(f"top_reason_code_{n}") or "")
                    for n in (1, 2, 3)],
    }
    product_before = V._counts(
        V._where(before, product="CREDIT_CARD"))["ews_score"]

    # --- the mutation: three salary cycles missed, in the source book.
    part = next((sandbox / S.BOOK / f"reporting_month={at}").glob("*.parquet"))
    book = pd.read_parquet(part)
    mask = book["customer_id"].astype(str) == who
    assert mask.any(), f"{who} is not in the disposable book"
    book.loc[mask, COLUMN] = 3.0
    book.to_parquet(part, index=False)

    _score(sandbox, months)
    after_frame = _read(sandbox, at)
    after_row = after_frame[after_frame["facility_id"].astype(str)
                            == facility].iloc[0]

    now = {
        "source": float(pd.to_numeric(after_row.get(COLUMN),
                                      errors="coerce") or 0.0),
        "sublayer": float(after_row[M.sublayer(SUBLAYER).score_column]),
        "layer": float(after_row[M.layer(LAYER).score_column]),
        "overall": float(after_row["ews_score"]),
        "severity": str(after_row["ews_severity"]),
        "reasons": [str(after_row.get(f"top_reason_code_{n}") or "")
                    for n in (1, 2, 3)],
    }
    product_after = V._counts(
        V._where(after_frame, product="CREDIT_CARD"))["ews_score"]

    # --- every link in the chain moved, in the right direction.
    assert now["source"] > was["source"], "the source variable did not change"
    assert after_row[f"trg_{TRIGGER}_fired"], "the trigger did not fire"
    assert now["sublayer"] > was["sublayer"], (
        f"{SUBLAYER} did not move: {was['sublayer']} -> {now['sublayer']}")
    assert now["layer"] > was["layer"], (
        f"{LAYER} did not move: {was['layer']} -> {now['layer']}")
    assert now["overall"] > was["overall"], (
        f"the score did not move: {was['overall']} -> {now['overall']}")
    fired_code = M.trigger(TRIGGER).reason_code
    assert fired_code in now["reasons"] and fired_code not in was["reasons"], (
        f"the reason codes did not change: {was['reasons']} -> {now['reasons']}")
    assert product_after != product_before, (
        "the product aggregate did not move: "
        f"{product_before} -> {product_after}")

    # --- and nobody else moved, so the change is attributable.
    others_before = before[before["customer_id"].astype(str) != who][
        ["facility_id", "ews_score"]].set_index("facility_id")["ews_score"]
    others_after = after_frame[after_frame["customer_id"].astype(str) != who][
        ["facility_id", "ews_score"]].set_index("facility_id")["ews_score"]
    shared = others_before.index.intersection(others_after.index)
    moved = (others_before[shared] - others_after[shared]).abs() > 0.001
    assert not moved.any(), (
        f"{int(moved.sum())} other facilities moved; the change is not "
        "attributable")

    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text(json.dumps({
        "customer_id": who,
        "facility_id": facility,
        "month": at,
        "variable": COLUMN,
        "source": {"before": was["source"], "after": now["source"],
                   "changed": True},
        "trigger": {"key": TRIGGER, "fired_before": False, "fired_after": True,
                    "changed": True},
        "sublayer": {"key": SUBLAYER, "before": was["sublayer"],
                     "after": now["sublayer"], "changed": True},
        "layer": {"key": LAYER, "before": was["layer"], "after": now["layer"],
                  "changed": True},
        "overall": {"before": was["overall"], "after": now["overall"],
                    "changed": True},
        "severity": {"before": was["severity"], "after": now["severity"],
                     "changed": was["severity"] != now["severity"]},
        "reason": {"before": was["reasons"], "after": now["reasons"],
                   "changed": True},
        "aggregate": {"product": "CREDIT_CARD", "before": product_before,
                      "after": product_after, "changed": True},
        "others_unchanged": int(len(shared)),
    }, indent=1))


def test_the_score_is_reproducible(sandbox: Path) -> None:
    """Scoring the same book twice gives the same answer.

    A demonstration score that moves on its own cannot be reconciled with a
    screenshot taken five minutes ago, and every figure in the handover is a
    screenshot taken five minutes ago.
    """
    from backend.retail import ews_score as S

    months = sorted(p.name.split("=", 1)[1]
                    for p in (sandbox / S.BOOK).iterdir() if p.is_dir())
    at = months[-1]
    _score(sandbox, months)
    first = _read(sandbox, at)[["facility_id", "ews_score"]].set_index(
        "facility_id")["ews_score"]
    _score(sandbox, months)
    second = _read(sandbox, at)[["facility_id", "ews_score"]].set_index(
        "facility_id")["ews_score"]
    assert first.equals(second), "the same book scored two different ways"
