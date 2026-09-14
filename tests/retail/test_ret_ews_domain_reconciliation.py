"""
The same facility, read from four places, is the same facility.

Cockpit Data, Early Warning Data, the Early Warning Score domain and What-If
Analysis Data are four views of one book. A reader who opens a customer in the
Early Warning workspace, exports them into What-If Analysis and then looks them
up in Data Builder must see one exposure, one delinquency and one IFRS 9
position — not three that are nearly the same.

That is not automatic. Each domain is published separately, from its own
column contract, on its own schedule, and each one joins. A column renamed on
one side, a period rebuilt on one side and not the other, or a join that
quietly drops rows all produce a book that does not add up, and none of them
announce themselves on a screen: every page still renders, with a number that
is wrong by an amount nobody can see.

What this pins
--------------
* every domain covers exactly the facilities in the book, with nothing
  missing and nothing extra;
* the fields that appear in more than one domain carry the same value,
  facility by facility;
* the totals a reader would compare across two screens are equal;
* the Early Warning Data contract is served in full, rather than declaring
  columns the book cannot fill and dropping them silently.

Every figure here is SYNTHETIC demonstration data. Not an ANB model, not an
ANB policy, not a SAMA requirement, not independently validated.
"""

from __future__ import annotations

import random
from pathlib import Path

import pandas as pd
import pytest

from backend.retail import domains as D
from backend.retail import ews_score as S
from backend.retail import profile

pytestmark = pytest.mark.skipif(
    not profile.is_retail(), reason="the corporate profile is active")

#: Columns that live in more than one domain and must agree in all of them.
SHARED = ("gross_carrying_amount_sar", "dpd", "dpd_bucket", "ifrs9_stage",
          "customer_id", "product_code")


def _read(name: str, month: str) -> pd.DataFrame:
    root = Path(S._root(None))
    if not (root / name).exists():
        pytest.skip(f"{name} has not been published")
    frames = [pd.read_parquet(one) for one in sorted((root / name).rglob("*.parquet"))]
    if not frames:
        pytest.skip(f"{name} holds no periods")
    whole = pd.concat(frames, ignore_index=True)
    column = "reporting_month" if "reporting_month" in whole else "period"
    return whole[whole[column].astype(str) == month]


@pytest.fixture(scope="module")
def month() -> str:
    found = S.panel_months()
    if not found:
        pytest.skip("the Early Warning Score domain has not been built")
    return found[-1]


@pytest.fixture(scope="module")
def book(month: str) -> pd.DataFrame:
    return S._read_book(month)


@pytest.fixture(scope="module")
def views(month: str) -> dict[str, pd.DataFrame]:
    return {
        "early_warning": _read("retail_early_warning", month),
        "whatif": _read("retail_whatif", month),
        "ews_score": S.read(month),
    }


def test_rec_01_every_domain_covers_exactly_the_book(book, views) -> None:
    wanted = set(book["facility_id"].astype(str))
    assert wanted, "the book holds no facilities at this month"
    for name, frame in views.items():
        held = set(frame["facility_id"].astype(str))
        assert not (wanted - held), (
            f"{name} is missing {len(wanted - held)} facilities the book holds")
        assert not (held - wanted), (
            f"{name} holds {len(held - wanted)} facilities the book does not")


def test_rec_02_one_row_per_facility_in_every_domain(views) -> None:
    for name, frame in views.items():
        assert not frame["facility_id"].astype(str).duplicated().any(), name


def test_rec_03_a_sampled_facility_reads_the_same_everywhere(
        book, views) -> None:
    random.seed(7)
    sample = random.sample(sorted(set(book["facility_id"].astype(str))),
                           min(25, len(book)))
    indexed = {name: frame.set_index(frame["facility_id"].astype(str))
               for name, frame in views.items()}
    base = book.set_index(book["facility_id"].astype(str))

    problems = []
    for facility in sample:
        for column in SHARED:
            if column not in base.columns:
                continue
            seen = {"book": base.loc[facility, column]}
            for name, frame in indexed.items():
                if column in frame.columns:
                    seen[name] = frame.loc[facility, column]
            if len({str(value) for value in seen.values()}) != 1:
                problems.append((facility, column, seen))
    assert not problems, problems[:5]


def test_rec_04_the_totals_two_screens_would_compare_are_equal(
        book, views) -> None:
    wanted = round(float(book["gross_carrying_amount_sar"].sum()), 2)
    for name, frame in views.items():
        if "gross_carrying_amount_sar" not in frame.columns:
            continue
        assert round(float(frame["gross_carrying_amount_sar"].sum()), 2) \
            == wanted, name


def test_rec_05_the_early_warning_contract_is_served_in_full(
        views, month: str) -> None:
    """A declared column the book cannot fill is a promise the domain breaks.

    The builder drops such a column and records a note. Nothing on a screen
    says so, and a reader looking for a field the domain says it carries finds
    it absent. Either the book carries it or it is not declared.
    """
    frame = views["early_warning"]
    missing = [one for one in D.EARLY_WARNING.columns
               if one not in frame.columns]
    assert not missing, (
        f"Early Warning Data declares {len(missing)} columns it does not "
        f"serve: {missing[:8]}")


def test_rec_06_the_builder_reports_nothing_left_out() -> None:
    for note in D.build().notes:
        assert "left out" not in note, note


def test_rec_07_the_domains_reconcile_on_their_own_terms() -> None:
    assert D.reconcile() == []
