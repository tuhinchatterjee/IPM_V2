"""One governed, idempotent demonstration bootstrap.

    from backend import bootstrap

    result = bootstrap.run()          # do whatever is missing, then verify
    report = bootstrap.readiness()    # verify without changing anything

Before this package, demonstration setup lived in five scripts, a Docker
entrypoint that ran three of them, a README that named three more, and a
button on a screen. A fresh Mac ran `docker compose up --build`, got the
Saudi portfolio and nothing else, and the API reported itself healthy.

`plan` holds the sequence and does the work. `readiness` holds the checks and
never repairs anything. Keeping them apart is what makes "is this deployment
ready?" answerable without also changing the answer.
"""

from __future__ import annotations

from typing import Any

from backend.bootstrap import readiness as _readiness
from backend.bootstrap.plan import BOOTSTRAP_VERSION, Result, run, steps
from backend.bootstrap.readiness import PERIOD, PRIOR_PERIOD, Report


def readiness(session: Any | None = None) -> Report:
    """What is and is not in place. Reports; never repairs."""
    return _readiness.report(session)


def ready(session: Any | None = None) -> bool:
    return _readiness.ready(session)


__all__ = ["BOOTSTRAP_VERSION", "PERIOD", "PRIOR_PERIOD", "Report", "Result",
           "ready", "readiness", "run", "steps"]
