#!/usr/bin/env python
"""Publish the whole retail book as one bundle, or publish nothing.

    .venv/bin/python scripts/publish_retail_bundle.py

Why this exists beside build_retail_demo.py
-------------------------------------------
`build_retail_demo.py` publishes the canonical facility-month book atomically,
and that was enough while it was the only thing published. It is not any more.
The installation now serves six datasets — the book, the Early Warning panel,
the Early Warning score, and three governed views — and they were built one
after another, each idempotent and each skipping what it already had.

Which is correct while the book underneath is the same book. Regenerating it
changes every period WITHOUT changing their names, so an incremental build of
the views has nothing to do and they go on serving the previous book's figures,
reconciled against a canonical total they no longer match. Worse, a build that
fails halfway leaves a new Cockpit book published beside yesterday's Early
Warning, and every cross-domain answer is then a join across two books that
nothing in the product can see.

So: everything is built into a staging tree, validated together, and swapped in
one move. Until the swap, readers see the previous complete bundle. After it,
they see this one. There is no moment at which they see half of each.

What is validated before the swap
---------------------------------
* every dataset a complete bundle holds is present, with periods;
* the Early Warning panel and the book end at the same month;
* every episode pocket — Alpha and the nine others — exists in BOTH the
  Cockpit book and the Early Warning score at that month;
* the Early Warning join is grain-safe: joining it to the book leaves total
  ECL unchanged;
* the five governed registrations that were there before are still there.

Any failure leaves the previous bundle exactly where it was and says which
check failed. A partial publication is never dressed as a slow one.

Everything it writes is SYNTHETIC.
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

from backend.retail import bundle as bnd  # noqa: E402
from backend.retail import catalogue as cat  # noqa: E402
from backend.retail import guard  # noqa: E402
from backend.retail.config import load_config  # noqa: E402
from backend.retail.generate import PERIOD_FIELD, build  # noqa: E402

DEFAULT_ANALYTICS = ROOT / "data" / "retail" / "analytics"
DEFAULT_METADATA = ROOT / "metadata" / "retail"

log = logging.getLogger("publish_retail_bundle")


class CheckFailed(RuntimeError):
    """A validation the bundle must pass before anything is swapped."""


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _months_of(root: Path, dataset: str) -> list[str]:
    directory = root / dataset
    if not directory.exists():
        return []
    return sorted(p.name.split("=", 1)[-1] for p in directory.iterdir()
                  if p.is_dir() and p.name.startswith("reporting_month="))


def _read_month(root: Path, dataset: str, month: str,
                columns: list[str] | None = None) -> pd.DataFrame:
    parts = sorted((root / dataset / f"reporting_month={month}")
                   .glob("*.parquet"))
    if not parts:
        return pd.DataFrame()
    frames = [pd.read_parquet(p, columns=columns) for p in parts]
    return pd.concat(frames, ignore_index=True) if len(frames) > 1 else frames[0]


def validate(root: Path, *, checks: list[dict]) -> None:
    """Everything that must be true before a bundle replaces another one."""
    from backend.retail import episodes as ep

    def record(name: str, ok: bool, detail: str) -> None:
        checks.append({"check": name, "passed": bool(ok), "detail": detail})
        if not ok:
            raise CheckFailed(f"{name}: {detail}")

    # -- completeness ----------------------------------------------------
    missing = [d for d in bnd.REQUIRED if not _months_of(root, d)]
    record("every dataset present", not missing,
           f"missing {missing}" if missing else
           f"{len(bnd.REQUIRED)} datasets, all with published periods")

    book_months = _months_of(root, bnd.CANONICAL)
    as_of = book_months[-1]

    # -- the panel ends where the book ends -------------------------------
    panel_months = _months_of(root, "retail_ews_panel")
    record("Early Warning ends where the book ends",
           panel_months and panel_months[-1] == as_of,
           f"book {as_of}, panel {panel_months[-1] if panel_months else 'none'}")

    # -- every pocket exists in BOTH modules at that month -----------------
    book = _read_month(root, bnd.CANONICAL, as_of, columns=[
        "facility_id", "customer_id", "product_code", "product_subsegment",
        "episode_code", "ecl_weighted_sar"])
    score_months = _months_of(root, "retail_ews_score")
    if as_of not in score_months:
        record("Early Warning score covers the reporting month", False,
               f"score months end at {score_months[-1] if score_months else 'none'}")
    score = _read_month(root, "retail_ews_score", as_of,
                        columns=["facility_id", "customer_id", "product_code"])

    scored = set(score["facility_id"].astype(str))
    absent = []
    for case_id in ep.case_ids():
        if case_id == "C01":
            pocket = book[book["product_subsegment"] == "ALPHA"]
        else:
            pocket = book[book["episode_code"] == case_id]
        ids = set(pocket["facility_id"].astype(str))
        if not ids:
            absent.append(f"{case_id} has no facilities in the book")
            continue
        covered = len(ids & scored) / len(ids)
        if covered < 0.80:
            absent.append(f"{case_id} is {covered:.0%} covered in Early Warning")
    record("every pocket exists in both the Cockpit and Early Warning",
           not absent, "; ".join(absent) if absent else
           f"all {len(ep.case_ids())} pockets present at {as_of}")

    # -- the Early Warning join does not multiply ECL ----------------------
    panel = _read_month(root, "retail_ews_panel", as_of,
                        columns=["customer_id", "product_code"])
    duplicated = panel.duplicated(["customer_id", "product_code"]).any()
    before = round(float(pd.to_numeric(
        book["ecl_weighted_sar"], errors="coerce").sum()), 2)
    joined = book.merge(panel, on=["customer_id", "product_code"], how="left")
    after = round(float(pd.to_numeric(
        joined["ecl_weighted_sar"], errors="coerce").sum()), 2)
    record("the Early Warning join is grain-safe",
           (not duplicated) and abs(after - before) < 0.01,
           f"total ECL {before} before the join and {after} after")

    # -- identity ----------------------------------------------------------
    record("a facility-month is unique", book["facility_id"].is_unique,
           f"{len(book)} rows, {book['facility_id'].nunique()} facilities")


#: The catalogue files a publication replaces, kept aside until it succeeds.
_CATALOGUE_FILES = (cat.CATALOG_FILENAME, cat.MANIFEST_FILENAME,
                    cat.CONTRACT_FILENAME, bnd.BUNDLE_FILENAME)


def _back_up_catalogue(metadata_dir: Path, stamp: str) -> Path:
    backup = metadata_dir / f".catalogue-before-{stamp}"
    backup.mkdir(parents=True, exist_ok=True)
    for name in _CATALOGUE_FILES:
        source = metadata_dir / name
        if source.exists():
            shutil.copy2(source, backup / name)
    return backup


def _restore_catalogue(metadata_dir: Path, stamp: str) -> None:
    backup = metadata_dir / f".catalogue-before-{stamp}"
    if not backup.exists():
        return
    for name in _CATALOGUE_FILES:
        kept = backup / name
        if kept.exists():
            shutil.copy2(kept, metadata_dir / name)
    shutil.rmtree(backup, ignore_errors=True)
    log.error("Restored the previously published catalogue.")


def preserved_registrations(metadata_dir: Path) -> list[str]:
    catalog_path = metadata_dir / cat.CATALOG_FILENAME
    if not catalog_path.exists():
        return []
    raw = json.loads(catalog_path.read_text(encoding="utf-8"))
    return sorted(d.get("dataset_id") or d.get("name") or ""
                  for d in (raw.get("datasets") or []))


# ---------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--analytics-dir", type=Path, default=DEFAULT_ANALYTICS)
    ap.add_argument("--metadata-dir", type=Path, default=DEFAULT_METADATA)
    ap.add_argument("--facilities", type=int, default=None)
    ap.add_argument("--staged-from", type=Path, default=None,
                    help="use an already-built tree as the staging tree "
                         "instead of generating one")
    ap.add_argument("--keep-previous", action="store_true", default=True)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(level=logging.WARNING if args.quiet else logging.INFO,
                        format="%(message)s")

    analytics = args.analytics_dir
    metadata = args.metadata_dir
    guard.mark(analytics)
    guard.mark(metadata)
    guard.require_retail_directory(analytics, what="publish the retail bundle")
    guard.require_retail_directory(metadata, what="write the retail catalogue")

    cfg = load_config()
    if args.facilities:
        import dataclasses

        portfolio = dict(cfg.portfolio)
        portfolio["target_active_facilities_latest_month"] = int(args.facilities)
        cfg = dataclasses.replace(cfg, portfolio=portfolio)

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    staging = analytics.parent / f"{analytics.name}.staging-{stamp}"
    previous = analytics.parent / f"{analytics.name}.previous-{stamp}"

    started = time.time()
    checks: list[dict] = []
    try:
        # -- 1. the canonical book ---------------------------------------
        if args.staged_from:
            log.info("Staging from %s", args.staged_from)
            shutil.copytree(args.staged_from, staging)
            manifest = json.loads(
                (metadata / cat.MANIFEST_FILENAME).read_text())
        else:
            log.info("Building the canonical book into %s", staging.name)
            guard.mark(staging)
            manifest = build(cfg, staging, log_progress=not args.quiet)
        guard.mark(staging)

        # -- 2. everything derived from it, into the same staging tree ----
        from backend.retail import domains as retail_domains
        from backend.retail import ews_portfolio, ews_score

        log.info("Early Warning panel")
        panel = ews_portfolio.build(analytics_dir=staging)
        log.info("  %d month(s) scored, %d rows", panel.months, panel.rows)

        log.info("Early Warning score")
        scored = ews_score.build(analytics_dir=staging)
        log.info("  %s", scored.summary())

        log.info("Governed views")
        views = retail_domains.build(analytics_dir=staging, replace=True)
        log.info("  %s", views.summary())

        # -- 3. validate the whole thing before anything is swapped -------
        log.info("Validating the staged bundle")
        validate(staging, checks=checks)
        for check in checks:
            log.info("  ok  %s — %s", check["check"], check["detail"])

        book_months = _months_of(staging, bnd.CANONICAL)
        as_of = book_months[-1]
        from backend.retail import episodes as ep

        staged = bnd.describe(staging, config=cfg, as_of=as_of,
                              episode_config_version=ep.config_version())
        if not staged.complete:
            raise CheckFailed(
                f"the staged bundle is missing {staged.missing()}")
        staged.checks = checks
        staged.replaced = bnd.current_id(metadata)

        # -- 4. swap, in one move -----------------------------------------
        #
        # The catalogue is kept beside the tree it describes, so it is copied
        # aside with the tree. A swap that moved the data and left the old
        # catalogue behind would publish a book described by the previous
        # book's column list.
        log.info("Swapping in bundle %s", staged.bundle_id)
        catalogue_backup = _back_up_catalogue(metadata, stamp)
        if analytics.exists():
            analytics.rename(previous)
        staging.rename(analytics)

        sample = _read_month(analytics, bnd.CANONICAL, as_of)
        paths = cat.write_catalog(metadata, sample.columns, manifest)

        # THE FIVE REGISTRATIONS.
        #
        # `write_catalog` replaces the catalogue with the canonical book alone
        # — which is right, because it is the only thing it knows about, and
        # wrong as the last word, because four governed views and the Early
        # Warning score were registered in it and are now gone. That is not a
        # hypothetical: it is how an earlier build of this installation lost
        # three governed views, and the symptom was screens that opened empty
        # rather than an error anybody could act on.
        #
        # So registration is part of the publication, and the count is
        # checked. Below five, the previous catalogue and the previous tree
        # both go back.
        from backend.retail import domains as retail_domains

        retail_domains.register_ews_score(metadata_dir=metadata)
        retail_domains.register(metadata_dir=metadata)
        registrations = preserved_registrations(metadata)
        log.info("Catalogue datasets after the swap: %s",
                 ", ".join(registrations) or "(none)")
        if len(registrations) < 5:
            raise CheckFailed(
                f"the catalogue holds {len(registrations)} dataset "
                f"registrations after publication ({registrations}); the "
                f"installation had five. A screen reading a lost registration "
                f"opens empty rather than failing, so this is rolled back.")
        checks.append({"check": "the five registrations survive publication",
                       "passed": True,
                       "detail": f"{len(registrations)}: "
                                 f"{', '.join(registrations)}"})
        staged.checks = checks
        bundle_path = bnd.write(staged, metadata)

    except Exception as exc:  # noqa: BLE001
        log.error("")
        log.error("NOT PUBLISHED. %s", exc)
        log.error("The previously published bundle is untouched and is still "
                  "the one readers see.")
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        if previous.exists():
            if analytics.exists():
                shutil.rmtree(analytics, ignore_errors=True)
            previous.rename(analytics)
            log.error("Rolled the analytics tree back.")
        _restore_catalogue(metadata, stamp)
        return 1

    shutil.rmtree(metadata / f".catalogue-before-{stamp}", ignore_errors=True)
    if previous.exists() and not args.keep_previous:
        shutil.rmtree(previous, ignore_errors=True)

    elapsed = time.time() - started
    log.info("")
    log.info("Published bundle %s", staged.bundle_id)
    log.info("  as of             %s", staged.as_of)
    log.info("  replaced          %s", staged.replaced or "(nothing)")
    log.info("  datasets          %s", ", ".join(
        f"{k} ({v})" for k, v in sorted(staged.dataset_periods.items())))
    log.info("  checks passed     %d", len(checks))
    log.info("  previous bundle   %s", previous if previous.exists() else "(removed)")
    log.info("  bundle manifest   %s", bundle_path)
    for name, p in paths.items():
        log.info("  %-17s %s", name, p)
    log.info("  elapsed           %.1fs", elapsed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
