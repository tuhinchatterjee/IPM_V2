#!/usr/bin/env python3
"""Run the candidate Cockpit engine.

    .venv/bin/python scripts/retail_cockpit/run_engine.py --port 8414

The real engine, on the real published projection, with the retail identity
bridge installed. `--offline` swaps in a provider that raises if it is ever
asked to reach the network, which is how the transport, the event stream and
the state machine are exercised without a paid call: a run is accepted, the
real worker picks it up, real frames are emitted and the run settles as a
real failure. Nothing about answer quality is claimed by it.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class OfflineProvider:
    """A provider that cannot call anything. Present so a run can be driven.

    `--think SECONDS` makes it spend that long before failing, which is how
    the stream is shown to be UNBUFFERED: a proxy that held frames until the
    response completed would deliver `model.requested` and `run.failed` in
    the same instant, and the live panel exists to make that impossible.
    """

    def __init__(self, think: float = 0.0) -> None:
        self.think = float(think)

    def count_tokens(self, **_: object) -> int:
        return 1

    def converse(self, **_: object):
        if self.think:
            import time

            time.sleep(self.think)
        raise RuntimeError(
            "This runtime has no provider credential. The run was accepted, "
            "driven and settled by the real worker; only the model call is "
            "absent.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8414)
    parser.add_argument("--offline", action="store_true",
                        help="drive runs with a provider that cannot call out")
    parser.add_argument("--think", type=float, default=0.0,
                        help="seconds the offline provider spends before it "
                             "fails, so frame timing can be measured")
    args = parser.parse_args()

    import uvicorn

    from backend.retail_cockpit_host.engine_app import build_app

    app = build_app(provider=(OfflineProvider(args.think)
                              if args.offline else None),
                    verify_model=not args.offline)
    print(f"candidate Cockpit engine on http://127.0.0.1:{args.port}",
          flush=True)
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
