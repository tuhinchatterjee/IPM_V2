#!/usr/bin/env python
"""Move the demonstration book, so a Lens has something real to notice.

    python scripts/lens_demo_change.py --apply      make the change
    python scripts/lens_demo_change.py --restore    put it back
    python scripts/lens_demo_change.py --status     say which state it is in

Why this exists
---------------
§37 asks for a live-refresh journey where the data genuinely changes between
two refreshes, and §41 asks for a case where Cockpit and Early Warning
movements corroborate each other. Neither can be demonstrated against a static
book, and neither should be demonstrated by writing figures into a snapshot
table — a "what changed" panel proved against a fabricated snapshot proves
nothing about the pipeline that produces real ones.

So this moves the SOURCE DATA, in the analytics layer the engine actually
reads, and every figure downstream moves because it was recomputed.

What it changes, and why that particular change
------------------------------------------------
A cohort of facilities in the latest quarter deteriorates, coherently:

    ifrs9_stage   1 → 2        the book's own view of the risk
    severity      → High       the early-warning severity
    watchlist     → True       the name is put on watch
    trend         → Deteriorating
    covenant_headroom_pct      reduced towards and through zero

Those five move together because that is what deterioration looks like in a
real book. A demonstration that raised Stage 2 and left every early-warning
signal flat would produce a "what changed" reading that correctly reported an
unexplained movement — which is honest and is not the story §41 asks for.

Nothing here invents a figure. Exposure is not touched, no row is added or
removed, and no borrower changes identity: the same facilities are reclassified
worse. That keeps every total intact and makes the movement entirely
attributable, which is what allows the reading to be checked afterwards.

Reversible
----------
`--restore` puts the original file back from the copy `--apply` made, so the
demonstration can be run again from a clean book. `--status` says which state
the data is in, because "why is Stage 2 already elevated?" is a question that
costs a presenter ten minutes.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd  # noqa: E402

#: Both tables move, for the same facilities. A deterioration that showed up
#: in the facility position and not in the staging table would be a data-
#: quality incident, not a credit story — and a Lens carrying both would
#: correctly report an inconsistency rather than the deterioration §41 asks
#: for. `portfolio_facility` carries the early-warning signals; `ifrs9_staging`
#: carries the stage the impairment committee reads.
DATASETS = ("portfolio_facility", "ifrs9_staging")
DATASET = DATASETS[0]
#: A copy of the untouched file, made once, on the first `--apply`.
BACKUP_SUFFIX = ".before-demo-change"

#: How many facilities deteriorate. Enough that the portfolio ratios move
#: visibly; small enough that the book still looks like itself.
COHORT = 220

EXIT_OK = 0
EXIT_CANNOT_RUN = 2


def _root() -> Path:
    from backend.config import settings

    return Path(settings.analytics_dir if hasattr(settings, "analytics_dir")
                else "data/analytics")


def _latest_partition(root: Path, dataset: str = DATASET) -> Path | None:
    from backend.metrics.service import _period_order

    partitions = sorted(
        (p for p in (root / dataset).glob("period=*") if p.is_dir()),
        key=lambda p: _period_order(p.name.split("=", 1)[1]))
    return partitions[-1] if partitions else None


def _files(partition: Path) -> tuple[Path, Path]:
    data = partition / "data.parquet"
    return data, data.with_suffix(data.suffix + BACKUP_SUFFIX)


def status(root: Path) -> int:
    partition = _latest_partition(root)
    if partition is None:
        print("No analytics layer found. Build it first: "
              "python scripts/build_data_lake.py")
        return EXIT_CANNOT_RUN
    data, backup = _files(partition)
    period = partition.name.split("=", 1)[1]
    frame = pd.read_parquet(data)
    stage2 = (frame["ifrs9_stage"] == 2).sum()
    staging = _latest_partition(root, "ifrs9_staging")
    staging_changed = (staging is not None
                       and _files(staging)[1].exists())
    watch = int(frame["watchlist"].sum())
    high = int(frame["severity"].isin(["High", "Critical"]).sum())
    print(f"period:            {period}")
    print(f"state:             {'CHANGED' if backup.exists() else 'original'}")
    print(f"ifrs9_staging:     "
          f"{'CHANGED' if staging_changed else 'original'}")
    print(f"facilities:        {len(frame):,}")
    print(f"stage 2:           {stage2:,}")
    print(f"on watchlist:      {watch:,}")
    print(f"high/critical EWS: {high:,}")
    return EXIT_OK


def apply_change(root: Path) -> int:
    partition = _latest_partition(root)
    if partition is None:
        print("No analytics layer found.", file=sys.stderr)
        return EXIT_CANNOT_RUN
    data, backup = _files(partition)
    period = partition.name.split("=", 1)[1]

    if backup.exists():
        print(f"{period} already carries the demonstration change. "
              "Run --restore first if you want to reapply it.")
        return EXIT_OK

    frame = pd.read_parquet(data)
    before = _summary(frame)

    # The cohort: stage 1 facilities with the least covenant headroom, which
    # is where a deterioration would actually show up first. Deterministic —
    # sorted, not sampled — so the demonstration is the same every time.
    candidates = frame[(frame["ifrs9_stage"] == 1)
                       & (~frame["watchlist"].astype(bool))]
    if candidates.empty:
        print("Nothing in this period is eligible to deteriorate.",
              file=sys.stderr)
        return EXIT_CANNOT_RUN
    cohort = candidates.sort_values(
        ["covenant_headroom_pct", "account_id"]).head(COHORT).index

    accounts = set(frame.loc[cohort, "account_id"])

    shutil.copy2(data, backup)

    frame.loc[cohort, "ifrs9_stage"] = 2
    frame.loc[cohort, "severity"] = "High"
    frame.loc[cohort, "watchlist"] = True
    frame.loc[cohort, "trend"] = "Deteriorating"
    # Headroom through zero: a covenant breach is what a watchlist entry is
    # usually made of, and it makes the covenant metrics move with the rest.
    frame.loc[cohort, "covenant_headroom_pct"] = (
        frame.loc[cohort, "covenant_headroom_pct"] - 12.0)
    frame.to_parquet(data, index=False)

    after = _summary(frame)
    print(f"Moved {len(cohort)} facilities in {period}:")
    for key in before:
        print(f"  {key:<20} {before[key]:>10,}  ->  {after[key]:>10,}")

    staged = _move_staging(root, accounts)
    if staged:
        print(f"  {'ifrs9 stage 2':<20} {staged[0]:>10,}  ->  {staged[1]:>10,}"
              "   (ifrs9_staging)")
    print()
    print("Reopen a Lens and its CreditProbe View will report the change. "
          "Put it back with --restore.")
    return EXIT_OK


def _move_staging(root: Path, accounts: set) -> tuple[int, int] | None:
    """The same facilities, moved in the impairment staging table.

    Kept consistent with the facility position on purpose. A Lens that carries
    both a Stage 2 share and a watchlist rate is exactly the Lens §41's
    corroboration journey needs, and moving only one of the two tables would
    make the two halves of the screen disagree — which a "what changed"
    reading would correctly report as an inconsistency rather than as the
    deterioration it is meant to show.
    """
    partition = _latest_partition(root, "ifrs9_staging")
    if partition is None:
        return None
    data, backup = _files(partition)
    if backup.exists():
        return None
    frame = pd.read_parquet(data)
    if "account_id" not in frame.columns:
        return None
    rows = frame["account_id"].isin(accounts) & (frame["ifrs9_stage"] == 1)
    if not rows.any():
        return None
    before = int((frame["ifrs9_stage"] == 2).sum())
    shutil.copy2(data, backup)
    frame.loc[rows, "prior_stage"] = 1
    frame.loc[rows, "ifrs9_stage"] = 2
    frame.loc[rows, "stage_moved"] = True
    if "sicr_watchlist_trigger" in frame.columns:
        frame.loc[rows, "sicr_watchlist_trigger"] = True
    if "sicr_any_trigger" in frame.columns:
        frame.loc[rows, "sicr_any_trigger"] = True
    frame.to_parquet(data, index=False)
    return before, int((frame["ifrs9_stage"] == 2).sum())


def restore(root: Path) -> int:
    restored = []
    for dataset in DATASETS:
        partition = _latest_partition(root, dataset)
        if partition is None:
            continue
        data, backup = _files(partition)
        if not backup.exists():
            continue
        shutil.move(str(backup), str(data))
        restored.append(f"{dataset} {partition.name.split('=', 1)[1]}")
    if not restored:
        print("This period is already in its original state.")
        return EXIT_OK
    print("Restored: " + ", ".join(restored) + ".")
    return EXIT_OK


def _summary(frame: pd.DataFrame) -> dict[str, int]:
    return {
        "stage 2": int((frame["ifrs9_stage"] == 2).sum()),
        "on watchlist": int(frame["watchlist"].astype(bool).sum()),
        "high/critical EWS": int(
            frame["severity"].isin(["High", "Critical"]).sum()),
        "covenant breached": int((frame["covenant_headroom_pct"] < 0).sum()),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--apply", action="store_true",
                       help="deteriorate a cohort in the latest quarter")
    group.add_argument("--restore", action="store_true",
                       help="put the original data back")
    group.add_argument("--status", action="store_true",
                       help="say which state the data is in")
    args = parser.parse_args()

    root = _root()
    if args.status:
        return status(root)
    if args.apply:
        return apply_change(root)
    return restore(root)


if __name__ == "__main__":
    raise SystemExit(main())
