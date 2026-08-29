#!/usr/bin/env python
"""Report or export the training corpus. §3, §4, §8.

    python scripts/brain_corpus.py --check
    python scripts/brain_corpus.py --report
    python scripts/brain_corpus.py --export docs/brain_corpus.json

--check builds everything and proves the contracts hold: the family floors,
no duplicate cases, variants inside their parents' clusters, and a holdout
that is disjoint from everything the layer may learn from. It makes no
network call and consumes no API credit.

The export deliberately omits the sealed holdout. §20 is explicit that a
Brain Pack may not carry sealed gold answers, and the easiest way for one to
end up in a pack is for a convenience export to have written it to disk
first.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.brain import corpus, holdout, variants  # noqa: E402
from backend.brain.cases import (  # noqa: E402
    FAMILIES,
    MINIMUM_CANONICAL,
    MINIMUM_HOLDOUT,
)


def _build() -> tuple[list, list, list]:
    canonical = corpus.build()
    generated = variants.build(canonical)
    sealed = holdout.build()
    holdout.assert_isolated([*canonical, *generated], sealed)
    return canonical, generated, sealed


def _report(canonical: list, generated: list, sealed: list) -> None:
    print(f"canonical {len(canonical)} (floor {MINIMUM_CANONICAL})   "
          f"variants {len(generated)}   "
          f"holdout {len(sealed)} (floor {MINIMUM_HOLDOUT})")
    print()
    print(f"{'family':<20}{'canonical':>10}{'floor':>7}"
          f"{'variants':>10}{'holdout':>9}{'clusters':>10}")
    for family, floor in FAMILIES.items():
        canon = [c for c in canonical if c.case_family == family]
        var = [c for c in generated if c.case_family == family]
        held = [c for c in sealed if c.case_family == family]
        clusters = len({c.cluster for c in canon})
        flag = "" if len(canon) >= floor else "  UNDER FLOOR"
        print(f"{family:<20}{len(canon):>10}{floor:>7}{len(var):>10}"
              f"{len(held):>9}{clusters:>10}{flag}")
    print()
    print("every holdout cluster is disjoint from every training cluster, "
          "and no holdout question appears in training")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="build everything and prove the contracts hold")
    parser.add_argument("--report", action="store_true",
                        help="print the per-family breakdown")
    parser.add_argument("--export", metavar="PATH",
                        help="write canonical cases and variants as JSON; "
                             "the sealed holdout is never written")
    args = parser.parse_args()
    if not (args.check or args.report or args.export):
        args.report = True

    canonical, generated, sealed = _build()

    if args.check:
        print(f"OK  {len(canonical)} canonical, {len(generated)} variants, "
              f"{len(sealed)} sealed holdout, isolated")
    if args.report:
        _report(canonical, generated, sealed)
    if args.export:
        path = Path(args.export)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "corpus_version": corpus.CORPUS_VERSION,
            "variant_schema_version": variants.VARIANT_SCHEMA_VERSION,
            "canonical": [c.to_dict() for c in canonical],
            "variants": [c.to_dict() for c in generated],
            "holdout_count": len(sealed),
            "holdout_cases": "withheld: sealed holdout is never exported",
        }, indent=2), encoding="utf-8")
        print(f"wrote {path} ({len(canonical)} canonical, "
              f"{len(generated)} variants; holdout withheld)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
