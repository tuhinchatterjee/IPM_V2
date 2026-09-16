#!/usr/bin/env python3
"""
What the answer turn has to write, and what it has to read first.

Records the measurement Stage 2 was sized from. No provider call, no
database: it builds the objects and counts them with the run's OWN estimator
(`Analyst.count_input`, `len(json)/2.2`), so the numbers here are the same
arithmetic the run does about itself.

    python3 scripts/cockpit_v4/answer_size_evidence.py

Writes docs/cockpit_v4/evidence/answer_size.json.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests" / "cockpit_v4"))
os.environ.setdefault("COCKPIT_AGENTIC_V3_NAMESPACE", "cockpit_v4")

#: `provider.py::count_input`, the conservative local estimate the run uses
#: when the provider's own counter is unavailable.
CHARS_PER_TOKEN = 2.2


def size(obj) -> int:
    return len(json.dumps(obj, ensure_ascii=False, default=str))


def tokens(obj) -> int:
    return int(size(obj) / CHARS_PER_TOKEN) + 1


def main() -> int:
    import answer_object as ao

    from backend.cockpit_v4 import config as config_mod

    limits = config_mod.ANALYTICAL_STANDARD_LIMITS
    answer = ao.four_step_answer()
    batch = ao.four_step_tool_result()
    step = batch["steps"][0]

    report = {
        "what": "a four-step, 100-row analysis answered properly",
        "estimator": "len(json)/2.2 -- provider.count_input",
        "answer_object": {
            "bytes": size(answer), "tokens": tokens(answer),
            "narrative_bytes": size(answer["narrative"]),
            "numeric_claims": len(answer["numeric_claims"]),
            "numeric_claims_bytes": size(answer["numeric_claims"]),
            "numeric_claims_share": round(
                size(answer["numeric_claims"]) / size(answer), 3)},
        "allowance": {
            "before_stage_2": 4_096,
            "base": limits.reserved_output_tokens,
            "ceiling_on_a_truncated_re_ask": limits.answer_output_ceiling,
            "fits_before_stage_2": tokens(answer) <= 4_096,
            "fits_now": tokens(answer) <= limits.reserved_output_tokens},
        "tool_result_after_the_shrink": {
            "four_step_bytes": size(batch),
            "four_step_tokens": tokens(batch),
            "one_step_bytes": size(step),
            "preview_bytes": size(step["preview"]),
            "row_ids_bytes": size(step["row_ids"]),
            "claim_guide_bytes": size(step["how_to_cite_these_numbers"])},
        "tool_result_before_the_shrink": {
            # Measured on the shipped code before this round: the same rows
            # again as `preview_formatted`, and a claim guide restating
            # ~2.8 KB of constant rules plus the whole row-id list three
            # more times, once per step.
            "four_step_bytes": 115_790, "one_step_bytes": 27_503,
            "preview_formatted_bytes": 11_437, "claim_guide_bytes": 5_453},
    }
    before = report["tool_result_before_the_shrink"]["four_step_bytes"]
    after = report["tool_result_after_the_shrink"]["four_step_bytes"]
    report["tool_result_saved"] = {
        "bytes": before - after,
        "share": round((before - after) / before, 3),
        "tokens": int((before - after) / CHARS_PER_TOKEN)}

    out = ROOT / "docs" / "cockpit_v4" / "evidence" / "answer_size.json"
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    a = report["answer_object"]
    print(f"\nanswer object     {a['bytes']:>9,} B  ~{a['tokens']:>6,} tok")
    print(f"  numeric_claims  {a['numeric_claims_bytes']:>9,} B  "
          f"({a['numeric_claims_share']:.0%} of it, "
          f"{a['numeric_claims']} claims)")
    print(f"\nallowance before  {4_096:>9,} tok   "
          f"fits: {report['allowance']['fits_before_stage_2']}")
    print(f"allowance now     {limits.reserved_output_tokens:>9,} tok   "
          f"fits: {report['allowance']['fits_now']}")
    print(f"ceiling on re-ask {limits.answer_output_ceiling:>9,} tok")
    print(f"\ntool_result       {before:>9,} B -> {after:,} B  "
          f"({report['tool_result_saved']['share']:.0%} off, "
          f"~{report['tool_result_saved']['tokens']:,} input tokens)")
    print(f"\nwritten to {out.relative_to(ROOT)}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
