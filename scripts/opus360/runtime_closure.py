#!/usr/bin/env python3
"""
Which repository files does the frozen runtime ACTUALLY load?

Boots the production app in a clean interpreter (no pytest, no test conftest),
drives one real scripted analytical turn and one clarification through the
route, worker, validator, executor and finalizer, and prints every repository
module in sys.modules. `cert/protected.py` RUNTIME_CLOSURE must cover every
`backend/` file this prints; tests/opus360 checks it.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("COCKPIT_AGENTIC_V3_NAMESPACE", os.environ.get("COCKPIT_V4_NAMESPACE", "cockpit_v4"))
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1]))


def main() -> int:
    from cert import oracles as orc
    from cert import protected, scripted
    from cert.engine import CockpitHarness
    from cert.observe import Recorder

    with tempfile.TemporaryDirectory() as tmp:
        h = CockpitHarness(Path(tmp), live=False, recorder=Recorder(None))
        for question, spec, behaviour in (
                ("Show Stage 2 EAD by sector for the latest quarter.",
                 {"fn": "by_dim", "dim": "sector", "metrics": ["ead_s2"]}, "ANSWER"),
                ("What is total exposure?", {"fn": "none"}, "CLARIFY")):
            case = {"case_id": "closure", "question": question, "oracle": spec}
            ref = orc.compute(spec, "corporate")
            h.switch.set(scripted.analyst_for(case, ref, domain="corporate", behaviour=behaviour))
            h.wait(h.post(question, domain="corporate"), timeout_seconds=120)
        print(json.dumps(protected.runtime_closure(), indent=1))
        h.close()
    sys.stdout.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
