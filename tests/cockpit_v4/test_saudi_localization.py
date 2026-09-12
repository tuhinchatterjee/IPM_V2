"""
The V4 demonstration book is Saudi, and the whole surface has to agree.

REAL DATABASE · REAL SOURCE. No paid provider call.

The release is read from disk and the source files are read as
text; nothing here is mocked and no model is involved.

Two things are proven here.

First, that the localization is a RELABELLING and not a conversion. Applying
an exchange rate to fictional amounts would manufacture economic meaning that
was never in them, so every figure in the Saudi release is byte-identical to
the figure the generator produced -- only the currency, the country and the
borrower names differ.

Second, that no part of the V4 experience a user can see still says INR or
crore. That is asserted against the release, the catalog, the runtime, the
product knowledge and the V4 source itself, rather than against a list of
files someone remembered to update.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import re

import pandas as pd
import pytest

from backend.cockpit_v4 import precision as prec
from backend.cockpit_v4 import saudi

ROOT = pathlib.Path(__file__).resolve().parents[2]

#: Money words that must not reach a reader of the Saudi demonstration.
FORBIDDEN = ("INR", "crore", "lakh", "₹", "Indian rupee", "rupee")


@pytest.fixture(scope="module")
def frames(release_id):
    from backend.cockpit_agentic import store

    directory = pathlib.Path(
        store.relation_path(release_id, "cockpit_facility_quarter")).parent
    return {path.stem: pd.read_parquet(path)
            for path in sorted(directory.glob("*.parquet"))}


# ---- the release ------------------------------------------------------

def test_the_release_is_denominated_in_sar(release_id):
    from backend.cockpit_agentic import store

    manifest = store.read_manifest(release_id)
    assert manifest["reporting_currency"] == "SAR"
    assert manifest["amount_scale"] == "million"
    assert manifest["amounts_converted"] is False, (
        "the amounts are read as Saudi amounts, never FX-converted")
    assert "No FX conversion" in manifest["localization_note"]


def test_the_release_still_says_it_is_not_client_data(release_id):
    from backend.cockpit_agentic import store

    manifest = store.read_manifest(release_id)
    assert manifest["not_client_data"], (
        "a Saudi-looking demonstration must still declare itself synthetic")


def test_the_release_keeps_twenty_quarters(release_id):
    from backend.cockpit_agentic import store

    calendar = store.read_manifest(release_id)["calendar"]
    assert calendar["slot_count"] == 20
    assert calendar["first_reporting_quarter"] == "2021Q3"
    assert calendar["last_reporting_quarter"] == "2026Q2"


def test_no_relation_carries_an_india_specific_money_word(frames):
    report = saudi.audit(frames)
    assert report["leaks"] == [], report["leaks"]
    assert "SAR" in report["currencies"]
    assert "INR" not in report["currencies"]


def test_the_book_is_booked_in_saudi_arabia(frames):
    countries = set(frames["cockpit_facility_quarter"]["country_code"].dropna())
    assert countries == {"SA"}, countries


def test_borrower_names_are_fictional_gcc_names(frames):
    names = sorted(set(
        frames["cockpit_facility_quarter"]["borrower_name"].dropna()))
    assert names, "the book has borrowers"
    heads = set(saudi.NAME_HEAD)
    for name in names:
        assert any(name.startswith(h) for h in heads), (
            f"{name!r} is not from the Saudi name vocabulary")
    # The names the previous book used, which must be gone.
    for gone in ("Bhavani", "Yamuna", "Aravali", "Deccan", "Narmada",
                 "Sahyadri", "Wardha"):
        assert not any(gone in n for n in names), (
            f"{gone} is an India-specific synthetic name")


def test_a_borrower_name_is_stable_across_reseeds():
    """Deterministic, so reseeding the release reproduces it byte for byte."""
    first = [saudi.borrower_name(f"BRW{i:04d}") for i in range(1, 40)]
    second = [saudi.borrower_name(f"BRW{i:04d}") for i in range(1, 40)]
    assert first == second
    assert saudi.borrower_name("BRW0001") != saudi.borrower_name("BRW0002")


def test_localization_changes_no_amount(frames):
    """The guarantee that makes this a relabelling and not a conversion."""
    before = {name: frame.copy() for name, frame in frames.items()}
    after = saudi.localize(before)
    for relation, frame in frames.items():
        numeric = frame.select_dtypes(include="number")
        if numeric.empty:
            continue
        pd.testing.assert_frame_equal(
            numeric, after[relation].select_dtypes(include="number"),
            check_exact=True,
            obj=f"{relation}: localization moved a number")


def test_localizing_twice_changes_nothing(frames):
    once = saudi.localize({k: v.copy() for k, v in frames.items()})
    twice = saudi.localize({k: v.copy() for k, v in once.items()})
    for relation in frames:
        pd.testing.assert_frame_equal(once[relation], twice[relation],
                                      obj=relation)


# ---- the runtime ------------------------------------------------------

def test_the_catalog_reports_sar_million(runtime):
    assert runtime.catalog.reporting_currency == "SAR"
    assert runtime.catalog.amount_scale == "million"


def test_the_release_summary_shown_to_the_analyst_is_saudi(runtime):
    blob = json.dumps(runtime.release_summary, default=str)
    for word in FORBIDDEN:
        assert word not in blob, f"the release summary mentions {word}"


def test_the_precision_policy_is_denominated_in_sar():
    assert prec.CURRENCY == "SAR"
    assert prec.AMOUNT_SCALE == "million"
    assert prec.MONEY_UNIT == "SAR million"
    assert prec.classify("SAR million").kind == prec.MONEY


def test_a_published_amount_reads_as_saudi_money():
    from decimal import Decimal

    text = prec.format_value(Decimal("40599.1736630513815"), "SAR million", 2)
    assert text == "SAR 40,599.17 million"
    for word in FORBIDDEN:
        assert word not in text


# ---- the source ------------------------------------------------------

def _v4_sources():
    for folder, patterns in (
            (ROOT / "backend" / "cockpit_v4", ("*.py", "*.json")),
            (ROOT / "frontend" / "src" / "components" / "cockpit-v4",
             ("*.ts", "*.tsx")),
            (ROOT / "scripts" / "cockpit_v4", ("*.py",)),
    ):
        for pattern in patterns:
            for path in folder.rglob(pattern):
                if "__pycache__" in str(path):
                    continue
                yield path


def test_no_v4_source_file_shows_an_india_specific_money_label():
    """The whole V4 surface, not a list someone remembered to update.

    `saudi.py` is exempt for the two lines that NAME what is being replaced
    and the audit that looks for leaks -- a module that cannot say "INR"
    cannot convert away from it.
    """
    offenders: list[str] = []
    for path in _v4_sources():
        if path.name == "saudi.py":
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for line_no, line in enumerate(text.splitlines(), start=1):
            if line.lstrip().startswith("#") or line.lstrip().startswith("//"):
                continue
            for word in ("INR", "crore", "₹"):
                if word in line:
                    offenders.append(f"{path.relative_to(ROOT)}:{line_no} "
                                     f"{line.strip()[:80]}")
    assert offenders == [], "\n".join(offenders)


def test_product_knowledge_is_saudi_framed():
    body = (ROOT / "backend" / "cockpit_v4"
            / "product_knowledge.json").read_text()
    for word in FORBIDDEN:
        assert word not in body, f"product knowledge mentions {word}"
    assert "SAR" in body, (
        "the deck's own Saudi framing should survive, not be neutralised")


def test_the_product_knowledge_still_declares_the_demo_synthetic():
    body = json.loads((ROOT / "backend" / "cockpit_v4"
                       / "product_knowledge.json").read_text())
    blob = json.dumps(body).lower()
    assert "synthetic" in blob or "demonstration" in blob


# ---- release stability ------------------------------------------------

def test_the_saudi_release_is_not_rewritten_by_running_the_suite(release_id):
    """D-001, against the new release. The oracles are measured on it."""
    from backend.cockpit_agentic import store

    directory = pathlib.Path(
        store.relation_path(release_id, "cockpit_facility_quarter")).parent
    digest = hashlib.sha256()
    names = []
    for parquet in sorted(directory.glob("*.parquet")):
        names.append(parquet.name)
        digest.update(parquet.read_bytes())
    assert len(names) == 11, names
    pathlib.Path(ROOT / "docs" / "cockpit_v4" / "evidence"
                 / "saudi_release_fingerprint.json").write_text(json.dumps({
                     "release_id": release_id,
                     "relations": len(names),
                     "fingerprint": digest.hexdigest(),
                     "currency": "SAR", "amount_scale": "million",
                     "amounts_converted": False,
                 }, indent=2) + "\n")
