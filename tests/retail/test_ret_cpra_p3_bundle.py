"""P3 gates: one version of the book, or none.

The failure these guard is not a crash. Six datasets were built one after
another, each idempotent and each skipping what it already had — correct while
the book underneath is the same book, and silently wrong the moment it is not,
because regenerating it changes every period WITHOUT changing their names. The
views then go on serving the previous book's figures, reconciled against a
canonical total they no longer match, and a build that fails halfway publishes
a new Cockpit book beside yesterday's Early Warning.

Nothing about that produces an error. It produces answers.

So these gates check the three things that make a publication safe to fail:
the bundle is complete or it is not published, every pocket is in both modules
at the same date, and a join across two builds is refused rather than averaged.

Everything read here is SYNTHETIC.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.retail import bundle as bnd
from backend.retail import episode_measures as em
from backend.retail import episodes as ep

METADATA = Path("metadata/retail")


@pytest.fixture(scope="module")
def published():
    found = bnd.read(METADATA)
    if found is None:
        pytest.skip(
            "No bundle manifest is published. Run "
            "`scripts/publish_retail_bundle.py` — the incremental build "
            "leaves no record of which version the datasets came from.")
    return found


def test_the_published_bundle_is_complete(published):
    assert published.complete, (
        f"The published bundle is missing {published.missing()}. An "
        f"incomplete bundle is never swapped in, so a manifest that names one "
        f"means the swap happened anyway.")
    assert published.bundle_id.startswith("RB-")
    assert published.as_of
    assert published.seed


def test_every_dataset_carries_a_content_hash(published):
    for dataset in bnd.REQUIRED:
        assert published.dataset_hashes.get(dataset), dataset
        assert published.dataset_periods.get(dataset, 0) > 0, dataset


def test_the_published_hashes_still_match_what_is_on_disk(published):
    """A bundle manifest that describes a tree nobody has changed since.

    If this fails, somebody rebuilt one dataset in place — which is exactly
    the state the bundle exists to make visible rather than survivable.
    """
    from backend.config import settings

    root = Path(settings.analytics_dir)
    for dataset, expected in published.dataset_hashes.items():
        actual, _ = bnd.dataset_hash(root, dataset)
        assert actual == expected, (
            f"{dataset} on disk does not match the published bundle "
            f"{published.bundle_id}. One dataset has been rebuilt "
            f"underneath the others.")


def test_the_validation_that_gated_the_swap_is_recorded(published):
    names = {c["check"] for c in published.checks}
    assert {"every dataset present",
            "every pocket exists in both the Cockpit and Early Warning",
            "the Early Warning join is grain-safe",
            "a facility-month is unique",
            "the five registrations survive publication"} <= names, (
        f"The bundle records only {sorted(names)}. A publication that did not "
        f"record what it checked cannot be audited later.")
    assert all(c["passed"] for c in published.checks)


def test_the_five_registrations_survived_publication():
    """The specific way an earlier build of this installation broke.

    `write_catalog` replaces the catalogue with the canonical book alone,
    which is right for what it knows about and wrong as the last word: four
    governed views and the Early Warning score were registered in it. A screen
    reading a lost registration opens EMPTY rather than failing, so nothing
    tells anybody it happened.
    """
    catalog = json.loads((METADATA / "catalog.json").read_text())
    names = {d.get("dataset_id") or d.get("name")
             for d in catalog.get("datasets") or []}
    assert {"retail_facility_month", "retail_ews_score",
            "retail_early_warning", "retail_credit_scorecard",
            "retail_whatif"} <= names, (
        f"The catalogue holds {sorted(names)}.")


def test_every_pocket_is_in_both_modules_at_the_same_date():
    import pandas as pd
    from backend.config import settings

    root = Path(settings.analytics_dir)
    as_of = em.latest_month()
    book = em.frame(as_of)
    score_dir = root / "retail_ews_score" / f"reporting_month={as_of}"
    parts = sorted(score_dir.glob("*.parquet"))
    if not parts:
        pytest.fail(
            f"The Early Warning score has no {as_of}. The Cockpit is a month "
            f"ahead of it, and every cross-module answer is a join across two "
            f"dates.")
    scored = set(pd.concat(
        [pd.read_parquet(p, columns=["facility_id"]) for p in parts],
        ignore_index=True)["facility_id"].astype(str))

    for case_id in ep.case_ids():
        eligible = em.eligible_mask(book, case_id)
        ids = set(book.loc[eligible, "facility_id"].astype(str))
        assert ids, case_id
        covered = len(ids & scored) / len(ids)
        assert covered >= 0.80, (
            f"{case_id}'s pocket is {covered:.0%} present in Early Warning. "
            f"A pocket the Cockpit can raise and Early Warning cannot show is "
            f"a pocket nobody can act on.")


def test_a_join_across_two_builds_is_refused():
    assert bnd.require_same("RB-A", "RB-A") == "RB-A"
    with pytest.raises(bnd.StaleBundle):
        bnd.require_same("RB-A", "RB-B")
    with pytest.raises(bnd.StaleBundle):
        # Unknown provenance is a mismatch, not a wildcard.
        bnd.require_same("RB-A", "")


def test_a_failed_publication_leaves_the_previous_bundle_readable(tmp_path):
    """Proved by running the publisher against a tree it must reject.

    The staging tree here holds only the canonical book, so the completeness
    check fails before any swap. What matters is the state afterwards: the
    previously published tree still there, still complete, still described by
    its own catalogue.
    """
    import shutil
    import subprocess
    import sys
    from backend.config import settings

    live = Path(settings.analytics_dir)
    if not (live / "retail_facility_month").exists():
        pytest.skip("Nothing is published to protect.")

    analytics = tmp_path / "analytics"
    metadata = tmp_path / "meta"
    analytics.mkdir(parents=True)
    metadata.mkdir(parents=True)
    # A complete-looking previous bundle: one directory per required dataset.
    for dataset in bnd.REQUIRED:
        (analytics / dataset / "reporting_month=2026-08").mkdir(parents=True)
        (analytics / dataset / "reporting_month=2026-08" / "data.parquet"
         ).write_bytes(b"previous")
    (metadata / "catalog.json").write_text('{"datasets": [{"name": "keep"}]}')
    for marker in (analytics, metadata):
        (marker / ".retail-installation").write_text("test fixture")

    # The staging tree: the book alone, so the completeness check refuses it.
    staged = tmp_path / "staged"
    (staged / "retail_facility_month" / "reporting_month=2026-08").mkdir(
        parents=True)
    shutil.copy(
        live / "retail_facility_month" / "reporting_month=2026-08"
        / "data.parquet",
        staged / "retail_facility_month" / "reporting_month=2026-08"
        / "data.parquet")

    result = subprocess.run(
        [sys.executable, "scripts/publish_retail_bundle.py",
         "--analytics-dir", str(analytics), "--metadata-dir", str(metadata),
         "--staged-from", str(staged), "--quiet"],
        capture_output=True, text=True,
        env={**__import__("os").environ, "PYTHONPATH": str(Path.cwd())})

    assert result.returncode == 1, (
        f"An incomplete bundle was published.\n{result.stdout}\n{result.stderr}")
    assert "NOT PUBLISHED" in (result.stdout + result.stderr)
    for dataset in bnd.REQUIRED:
        kept = (analytics / dataset / "reporting_month=2026-08"
                / "data.parquet")
        assert kept.exists(), f"{dataset} was lost by a failed publication"
    assert json.loads((metadata / "catalog.json").read_text())["datasets"] \
        == [{"name": "keep"}], "the previous catalogue was overwritten"
