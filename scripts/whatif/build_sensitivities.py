#!/usr/bin/env python3
"""Write the sensitivity cards, and prove they describe what was published.

    python3 scripts/whatif/build_sensitivities.py

Section 7.1 puts the fit in candidate preparation and the retrieval in the
chat turn: *"Precompute available sensitivities during candidate preparation
and an explicit versioned data/model refresh, not on every chat request...
Training work is never an unannounced side effect of asking a question."*

`scripts/whatif/seed_candidate.py` is where the fit happens, because it has to
be: `sensitivity.build.attach` reads the frames that are about to become
parquet, in the same process, so there is no window in which the published
artifact could describe different numbers than the book it lives inside.

This script is the other half. It refits from a rebuilt book and then
**compares row by row with what is published**, which is what makes
`SENSITIVITY_CARD_CORPORATE.md` and `SENSITIVITY_CARD_RETAIL.md` evidence
rather than description. A card that disagreed with the release would be a
card about a fit nobody can query.

It publishes nothing. If a row differs, it says which one and exits non-zero;
the fix is to re-run the seeder, never to edit the card.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("COCKPIT_V4_WHATIF_CORPORATE", "1")
os.environ.setdefault("COCKPIT_V4_WHATIF_RETAIL", "1")

from backend.cockpit_v4 import analytical_runtime as arun  # noqa: E402
from backend.cockpit_v4 import domain_resolver as resolver  # noqa: E402
from backend.cockpit_v4 import domains as dom  # noqa: E402
from backend.cockpit_v4 import lake  # noqa: E402
from backend.cockpit_v4.scenario import candidate_schema as cs  # noqa: E402
from backend.cockpit_v4.scenario.generate import corporate, retail  # noqa: E402
from backend.cockpit_v4.scenario.sensitivity import build as sens  # noqa: E402

BUILDERS = {dom.CORPORATE: corporate.build, dom.RETAIL: retail.build}
CARDS = {dom.CORPORATE: "SENSITIVITY_CARD_CORPORATE.md",
         dom.RETAIL: "SENSITIVITY_CARD_RETAIL.md"}

#: Columns compared against the published release. The governance stamp and
#: the prose are compared too -- a limitation sentence that drifted would
#: leave a reader with a different explanation than the one in the card.
COMPARED = ("parameter", "factor_id", "lag", "coefficient",
            "native_derivative", "reference_parameter_value",
            "reference_factor_value", "standardised_response", "std_error",
            "ci_low", "ci_high", "sign_stability", "training_periods",
            "validation_periods", "train_start", "train_end", "effective_df",
            "collinearity", "readiness", "limitation", "support_low",
            "support_high", "method", "source_release_id",
            "source_fingerprint")


def published_rows(domain_id: str) -> list[dict[str, object]]:
    """The artifact as the Cockpit would read it: through the real runtime."""
    relation = sens.SHAPES[domain_id].artifact_relation
    scope = resolver.scope_for(domain_id, tenant_id=lake.DEFAULT_TENANT)
    if relation not in scope.relations:
        raise SystemExit(
            f"{relation} is not in the opened release {scope.release_id}. "
            f"Run scripts/whatif/seed_candidate.py first.")
    connection = arun.for_domain(domain_id).session.connection
    columns = [d[0] for d in connection.execute(
        f"SELECT * FROM {relation} LIMIT 0").description]
    rows = connection.execute(f"SELECT * FROM {relation}").fetchall()
    return [dict(zip(columns, row, strict=True)) for row in rows]


def differences(fitted: list[dict[str, object]],
                stored: list[dict[str, object]]) -> list[str]:
    """Every disagreement, named. Not a count and not the first one."""
    def key(row: dict[str, object]) -> tuple[str, str, int]:
        return (str(row["parameter"]), str(row["factor_id"]),
                int(row["lag"]))

    mine = {key(r): r for r in fitted}
    theirs = {key(r): r for r in stored}
    out: list[str] = []
    for missing in sorted(set(mine) - set(theirs)):
        out.append(f"{missing}: fitted here, absent from the release")
    for extra in sorted(set(theirs) - set(mine)):
        out.append(f"{extra}: in the release, not produced by this fit")
    for shared in sorted(set(mine) & set(theirs)):
        for column in COMPARED:
            here, there = mine[shared][column], theirs[shared][column]
            if isinstance(here, float) and isinstance(there, float):
                if abs(here - there) <= 1e-12:
                    continue
            elif here == there or str(here) == str(there):
                continue
            out.append(f"{shared}.{column}: fitted {here!r}, "
                       f"published {there!r}")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--domain", choices=["corporate", "retail", "all"],
                        default="all")
    parser.add_argument("--out", default="docs/whatif",
                        help="where the cards are written.")
    parser.add_argument("--evidence",
                        default="docs/whatif/evidence/sensitivities.json")
    args = parser.parse_args()

    domains = ([dom.CORPORATE, dom.RETAIL] if args.domain == "all"
               else [dom.parse(args.domain)])
    record: dict[str, object] = {
        "origin": cs.ORIGIN,
        "note": ("Fitted on generated data against a generated macro panel. "
                 "Not a bank-validated sensitivity and not observed economic "
                 "history."),
        "books": {},
    }
    failed = False

    for domain_id in domains:
        release_id = cs.RELEASES[domain_id]
        if not lake.exists(release_id):
            print(f"{release_id} is not published; run "
                  f"scripts/whatif/seed_candidate.py")
            return 2
        print(f"\nrefitting {release_id} ...")
        build = BUILDERS[domain_id](release_id=release_id)
        fitted = sens.fit_release(
            build.frames, domain_id=domain_id, release_id=release_id,
            periods=build.periods, tenant_id=lake.DEFAULT_TENANT)

        stored = published_rows(domain_id)
        gaps = differences([dict(r) for r in fitted.rows], stored)
        status = "matches" if not gaps else f"{len(gaps)} DISAGREEMENT(S)"
        print(f"  {len(fitted.rows)} rows, {fitted.by_status()}")
        print(f"  against the published release: {status}")
        for gap in gaps[:20]:
            print(f"    - {gap}")
        failed = failed or bool(gaps)

        fingerprint = lake.fingerprint(release_id)
        target = Path(args.out) / CARDS[domain_id]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(sens.card(fitted, fingerprint=fingerprint),
                          encoding="utf-8")
        print(f"  card written to {target}")

        record["books"][release_id] = {
            "domain_id": domain_id,
            "release_fingerprint": fingerprint,
            "sensitivity_input_digest": fitted.digest,
            "rows": len(fitted.rows),
            "readiness": fitted.by_status(),
            "cohort_exposures": fitted.book.cohort_size,
            "excluded_ever_defaulted": fitted.book.excluded_defaulted,
            "excluded_not_in_every_period": fitted.book.excluded_partial,
            "matches_published_release": not gaps,
            "disagreements": gaps,
            "card": str(target),
        }

    target = Path(args.evidence)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(record, indent=2, sort_keys=True),
                      encoding="utf-8")
    print(f"\nevidence written to {target}")
    if failed:
        print("\nA card would have described a fit the release does not "
              "carry. Re-run scripts/whatif/seed_candidate.py; do not edit "
              "the card.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
