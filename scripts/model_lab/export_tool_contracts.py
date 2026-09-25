"""
Export the frozen engine's ACTUAL tool contracts to
docs/model_comparison/TOOL_CONTRACTS.json.

The schemas are produced by calling the frozen `contracts.provider_tools`
exactly as `worker.Worker._drive` does, over each published domain book, so
the export is what a provider would really receive -- not a hand copy. The
frozen code is imported read-only; nothing is written outside the lab docs.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("COCKPIT_AGENTIC_V3_NAMESPACE", "cockpit_v4")
OUT = ROOT / "docs" / "model_comparison" / "TOOL_CONTRACTS.json"


def _digest(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True).encode()).hexdigest()


def main() -> int:
    from backend.cockpit_v4 import analytical_runtime as arun
    from backend.cockpit_v4 import contracts
    from backend.cockpit_v4 import domains as dom

    out: dict = {
        "source": "backend.cockpit_v4.contracts.provider_tools (frozen, "
                  "called as worker.Worker._drive calls it)",
        "frozen_commit": "245c50e45786c6e0c866b281f9dd74da17d160b5",
        "tool_names": list(contracts.TOOL_NAMES),
        "batchable_read_tools": sorted(getattr(contracts, "BATCHABLE", ())),
        "parser_dispositions": list(contracts.DISPOSITIONS),
        "variants": {},
    }
    for domain in (dom.CORPORATE, dom.RETAIL):
        try:
            book = arun.for_domain(domain)
        except Exception as exc:  # noqa: BLE001 - recorded, not hidden
            out["variants"][domain] = {"error": f"{type(exc).__name__}: {exc}"}
            continue
        variants = {
            "answer_tools (full_tools)": contracts.provider_tools(
                catalog=book.catalog),
            "action_tools (non-analytical first turn)": contracts.provider_tools(
                catalog=book.catalog, stage=""),
            "action_tools (analytical_action)": contracts.provider_tools(
                catalog=book.catalog, stage="analytical_action"),
        }
        out["variants"][domain] = {
            "release_id": book.release_id,
            **{name: {"sha256": _digest(tools),
                      "names": [t["name"] for t in tools],
                      "tools": tools}
               for name, tools in variants.items()},
        }
    # The schema file's own disposition enum, for the recorded mismatch.
    schema = json.loads((ROOT / "backend/cockpit_v4/contracts/"
                         "finalize_response.schema.json").read_text())
    out["schema_file_disposition_enum"] = (
        schema.get("properties", {}).get("disposition", {}).get("enum"))
    OUT.write_text(json.dumps(out, indent=1, sort_keys=False) + "\n")
    print(f"wrote {OUT.relative_to(ROOT)}")
    for d, v in out["variants"].items():
        print(d, {k: (x["names"] if isinstance(x, dict) and "names" in x
                      else x) for k, x in v.items() if k != "release_id"})
    print("schema enum:", out["schema_file_disposition_enum"])
    print("parser enum:", out["parser_dispositions"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
