"""
Long-run diagnostic time limits: an in-memory override of the frozen limit
values, applied ONLY inside an isolated diagnostic child process.

Why an override at all. The frozen `Worker.execute` builds its `Ledger` from
`envelope.for_request(...).limits`, which reads the module constants
`STANDARD_LIMITS` / `DEEP_LIMITS` / `ANALYTICAL_*_LIMITS` in
`backend.cockpit_v4.config`. No Runtime, config or environment seam changes
them, so a slow local model on a 16 GB Mac is cut off at 30 s per call and
180 s per run. The operator explicitly authorised, for this diagnostic only,
replacing those values in memory -- never on disk -- in a separate process.

Guarantees, each enforced here rather than assumed:

* only the three time fields change (`deadline_seconds`,
  `action_call_seconds`, `answer_call_seconds`); tools, prompts, validators,
  execution, step limits, reserves, counters and the Finalizer do not;
* every value is finite, positive and capped (3600 s run, 900 s call);
* `applied()` refuses to run unless this process was started as a
  diagnostic child, so it can never patch the lab server that runs the
  baseline children;
* the original objects are restored in `finally`, and the process exits.
"""

from __future__ import annotations

import math
import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from typing import Any

LABEL = "LONG-RUN HARDWARE/QUALITY DIAGNOSTIC — SLA NOT COMPARABLE"
ENV_FLAG = "MODEL_LAB_DIAGNOSTIC_CHILD"

#: The only fields that may change, and the most each may be set to.
CAPS = {"deadline_seconds": 3600.0, "action_call_seconds": 900.0,
        "answer_call_seconds": 900.0}

#: Every frozen limit family a run can start on or widen to.
FAMILIES = ("STANDARD_LIMITS", "DEEP_LIMITS", "ANALYTICAL_STANDARD_LIMITS",
            "ANALYTICAL_DEEP_LIMITS")

_armed_pid: int | None = None


class DiagnosticLimitsError(ValueError):
    pass


def validate(raw: Any) -> dict[str, float]:
    if not isinstance(raw, dict) or not raw:
        raise DiagnosticLimitsError("diagnostic_limits must be a non-empty "
                                    "object")
    out: dict[str, float] = {}
    for key, value in raw.items():
        if key not in CAPS:
            raise DiagnosticLimitsError(
                f"diagnostic_limits.{key} is not an allowed field "
                f"(allowed: {sorted(CAPS)})")
        try:
            v = float(value)
        except (TypeError, ValueError) as exc:
            raise DiagnosticLimitsError(
                f"diagnostic_limits.{key} must be a number") from exc
        if not math.isfinite(v) or v <= 0 or v > CAPS[key]:
            raise DiagnosticLimitsError(
                f"diagnostic_limits.{key}={value!r} must be finite, > 0 and "
                f"<= {CAPS[key]:.0f}")
        out[key] = v
    return out


def policy(limits_by_family: dict[str, Any]) -> dict[str, dict[str, float]]:
    """The time fields of each family, for the evidence record."""
    return {name: {k: float(getattr(lim, k)) for k in CAPS}
            for name, lim in limits_by_family.items()}


def frozen_policy() -> dict[str, dict[str, float]]:
    """The policy as the frozen module holds it in THIS process."""
    from backend.cockpit_v4 import config as config_mod
    return policy({n: getattr(config_mod, n) for n in FAMILIES})


def arm() -> None:
    """Called once by `diagnostic_child.main`, and nowhere else."""
    global _armed_pid
    if os.environ.get(ENV_FLAG) != "1":
        raise DiagnosticLimitsError(f"{ENV_FLAG}=1 is required")
    _armed_pid = os.getpid()


@contextmanager
def applied(overrides: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Replace the frozen time limits for the life of the block."""
    if _armed_pid != os.getpid() or os.environ.get(ENV_FLAG) != "1":
        raise DiagnosticLimitsError(
            "diagnostic limits may only be applied inside an isolated "
            "diagnostic child process")
    from backend.cockpit_v4 import config as config_mod

    values = validate(overrides)
    saved = {n: getattr(config_mod, n) for n in FAMILIES}
    try:
        for name, lim in saved.items():
            setattr(config_mod, name, replace(lim, **values))
        yield {"frozen_policy": policy(saved),
               "effective_policy": policy(
                   {n: getattr(config_mod, n) for n in FAMILIES}),
               "overrides": values, "pid": os.getpid()}
    finally:
        for name, lim in saved.items():
            setattr(config_mod, name, lim)
