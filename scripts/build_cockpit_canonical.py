#!/usr/bin/env python
"""Build and publish the Cockpit's CANONICAL release.

    COCKPIT_AGENTIC_V3=true .venv/bin/python scripts/build_cockpit_canonical.py

The Cockpit's relations, its column contract and its whole architecture,
populated from the canonical corporate book: CORP- and CFAC- identities, every
canonical borrower and facility, SAR in millions, the canonical sixteen
quarters, and Stage, SICR, PD, LGD, EAD and reported ECL read from
`corporate_ifrs9_facility` rather than assigned here.

Prerequisites, in order:

    scripts/generate_saudi_universe.py            (catalogue first)
    scripts/build_corporate_universe.py
    scripts/build_corporate_ifrs9_facility.py

Refuses to publish a release whose identities are not canonical, whose calendar
reaches outside the canonical window, or whose exposure does not reconcile to
the canonical book.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


from backend.cockpit_agentic import canonical as C  # noqa: E402
from backend.cockpit_agentic import fields as F  # noqa: E402
from backend.cockpit_agentic import store  # noqa: E402


def _gates(release, source: C.Source) -> list[tuple[bool, str, str]]:
    """The checks that decide whether this release may be published.

    Each is a claim the demo makes on screen, asserted here rather than
    assumed: if one fails the release is not written, because a Cockpit
    answering over half-canonical data is worse than one that will not start.
    """
    facility = release.frames[F.FACILITY_QUARTER]
    out: list[tuple[bool, str, str]] = []

    borrowers = facility["borrower_id"].astype(str)
    facilities = facility["facility_id"].astype(str)
    out.append((
        bool(borrowers.str.startswith("CORP-").all()),
        "every borrower id is canonical (CORP-)",
        f"{(~borrowers.str.startswith('CORP-')).sum()} are not"))
    out.append((
        bool(facilities.str.startswith("CFAC-").all()),
        "every facility id is canonical (CFAC-)",
        f"{(~facilities.str.startswith('CFAC-')).sum()} are not"))
    out.append((
        not borrowers.str.startswith(("BRW", "FAC", "GRP0")).any(),
        "no identifier from the retired private book survives",
        "one or more BRW/FAC/GRP0 identifiers are present"))

    quarters = set(facility["reporting_quarter"].unique())
    expected = set(release.calendar.populated)
    out.append((quarters == expected,
                f"exactly the {len(expected)} canonical quarters carry rows",
                f"extra {sorted(quarters - expected)}, "
                f"missing {sorted(expected - quarters)}"))
    out.append((
        not any(q.startswith(("2021", "2027", "2028", "2029", "2030"))
                for q in quarters),
        "no quarter outside the canonical window",
        f"{sorted(q for q in quarters if q[:4] not in {str(y) for y in range(2022, 2027)})}"))

    currencies = set(facility["reporting_currency"].unique())
    scales = set(facility["amount_scale"].unique())
    out.append((currencies == {C.CURRENCY} and scales == {C.AMOUNT_SCALE},
                f"reported in {C.CURRENCY} {C.AMOUNT_SCALE}",
                f"currencies {currencies}, scales {scales}"))

    # Population: every canonical borrower and facility, not a cohort.
    out.append((
        facility["borrower_id"].nunique()
        == source.ifrs9["borrower_id"].nunique(),
        "every canonical borrower is present",
        f"{facility['borrower_id'].nunique()} of "
        f"{source.ifrs9['borrower_id'].nunique()}"))
    out.append((
        facility["facility_id"].nunique()
        == source.facilities["facility_id"].nunique(),
        "every canonical facility is present",
        f"{facility['facility_id'].nunique()} of "
        f"{source.facilities['facility_id'].nunique()}"))

    # And the numbers themselves reconcile to the canonical book.
    got = (facility.groupby("reporting_quarter")[["ead_reported", "ecl_reported"]]
           .sum().round(2))
    want = source.ifrs9.copy()
    want["reporting_quarter"] = want["period"].map(C._slot)
    want = (want.groupby("reporting_quarter")[["ead", "final_ecl"]]
            .sum().round(2))
    joined = got.join(want, how="outer")
    ead_gap = float((joined["ead_reported"] - joined["ead"]).abs().max())
    ecl_gap = float((joined["ecl_reported"] - joined["final_ecl"]).abs().max())
    out.append((ead_gap <= 0.05,
                "portfolio EAD reconciles to the canonical book every quarter",
                f"largest quarterly gap {ead_gap:,.4f}"))
    out.append((ecl_gap <= 0.05,
                "portfolio ECL reconciles to the canonical book every quarter",
                f"largest quarterly gap {ecl_gap:,.4f}"))

    # Stage, read not assigned: the mix must be the canonical mix.
    got_stage = facility.groupby("ifrs9_stage")["facility_id"].size()
    stage_ok = set(got_stage.index) <= {1, 2, 3}
    out.append((stage_ok, "stage takes only canonical values 1, 2 and 3",
                f"found {sorted(got_stage.index)}"))

    ratings = release.frames[F.RATING_RATIO]
    ranks = ratings["rating_rank"].dropna().astype(int)
    out.append((int(ranks.max()) <= 20 and int(ranks.min()) >= 1,
                "rating ordinals sit on the canonical 19+D masterscale",
                f"observed {int(ranks.min())}..{int(ranks.max())}"))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", default=C.RELEASE_ID)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--check", action="store_true",
                        help="build and gate; publish nothing")
    args = parser.parse_args(argv)

    print(f"> Building {args.release} from the canonical corporate book")
    source = C.load()
    release = C.build(dataset_release_id=args.release)

    for name, frame in release.frames.items():
        print(f"  {name:<38s} {len(frame):>9,} rows  {frame.shape[1]:>3} cols")
    missing = [r for r in F.RELATIONS if r not in release.frames]
    for name in missing:
        print(f"  {name:<38s} NOT PUBLISHED — {C.ANNOTATIONS.get(name, '')[:60]}…")

    failures = 0
    print("> Gates")
    for passed, claim, detail in _gates(release, source):
        print(f"  {'+' if passed else 'X'} {claim}" + ("" if passed
                                                       else f" — {detail}"))
        failures += 0 if passed else 1
    if failures:
        print(f"! {failures} gate(s) failed. Nothing published.")
        return 1

    if args.check:
        print("> --check: nothing written")
        return 0

    manifest = store.write(release, overwrite=True)
    print(f"> published to {store.release_dir(args.release)}")
    print(f"  {sum(r['rows'] for r in manifest['relations'].values()):,} rows, "
          f"{sum(r['bytes'] for r in manifest['relations'].values()) / 1e6:.1f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
