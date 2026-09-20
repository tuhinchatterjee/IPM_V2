"""What this deployment has spent, and whether it may spend more.

The gap this exists for
-----------------------
`docs/retail_cockpit/LIVE_UAT_PLAN.md` promises a *"hard cumulative cap, USD
15.00"*. Nothing in the engine enforces one. `budgets.py`'s
`spend_ceiling_usd` is a **per-run** ceiling -- 1.50 in standard mode -- and
there is no cumulative counter anywhere in `backend/cockpit_v4/**`. Twelve
runs at the per-run ceiling is 18.00, and nothing stops the thirteenth. A cap
that exists only in a document is not a cap.

Where the number comes from
---------------------------
The engine's own ledger, which already records every reservation:

    reservations(reservation_id, run_id, purpose,
                 reserved_usd, settled_usd, uncertain, usage, created_at)

so cumulative spend is

    SUM(COALESCE(settled_usd, reserved_usd))

and the `COALESCE` is the point: an in-flight reservation counts at what it
RESERVED until it settles for less. A cap that only counted settled rows
would let a burst of concurrent runs through on the strength of spending that
had not been recorded yet.

What this is not
----------------
Not a replacement for the engine's per-run ceiling, which is untouched and
still the thing that bounds one question. Not a billing record either -- the
provider's own invoice is. It reads the ledger and never writes to it, never
opens the database for writing, and holds no long-lived connection.

Unset, it does nothing
----------------------
`RETAIL_COCKPIT_SPEND_CAP_USD` unset means no cap, and `allowed()` says yes
without reading anything. So the offline path, and any deployment that has
not opted in, behave exactly as they did before this module existed.
"""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path

#: The cap, in USD, for everything this runtime has spent. Unset or empty
#: means no cap. Zero is a real value and means "spend nothing".
CAP_VAR = "RETAIL_COCKPIT_SPEND_CAP_USD"


class SpendCapInvalid(ValueError):
    """The cap is configured but unreadable. Refuses rather than guesses."""


@dataclass(frozen=True)
class Verdict:
    """Whether a new run may start, and the numbers behind the answer."""

    allowed: bool
    spent_usd: float
    cap_usd: float | None
    #: True when no cap is configured, so `spent_usd` was never read.
    uncapped: bool = False

    @property
    def remaining_usd(self) -> float:
        if self.cap_usd is None:
            return float("inf")
        return max(0.0, self.cap_usd - self.spent_usd)

    def to_dict(self) -> dict[str, object]:
        body: dict[str, object] = {"spend_cap_usd": self.cap_usd,
                                   "spent_usd": round(self.spent_usd, 6)}
        if self.cap_usd is not None:
            body["remaining_usd"] = round(self.remaining_usd, 6)
        return body


def cap_usd() -> float | None:
    """The configured cap, or None when there is none."""
    raw = os.environ.get(CAP_VAR, "").strip()
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError as exc:
        raise SpendCapInvalid(
            f"{CAP_VAR}={raw!r} is not a number. A cap that cannot be read "
            f"is not a cap, so nothing is assumed.") from exc
    if value < 0:
        raise SpendCapInvalid(f"{CAP_VAR}={raw!r} is negative.")
    return value


def state_database() -> Path:
    """The engine's state store, from the engine's own configuration."""
    from backend.cockpit_v4 import config as config_mod

    configured = os.environ.get("COCKPIT_V4_STATE_DATABASE", "").strip()
    if configured:
        return Path(configured).expanduser()
    return config_mod.default_runtime_dir() / "state" / "cockpit_v4.sqlite3"


def spent(database: Path | str | None = None) -> float:
    """Everything reserved or settled so far, in USD.

    A store that does not exist yet has spent nothing -- that is the state
    before the first run, not a failure. A store that exists but cannot be
    read IS a failure, and is raised rather than reported as zero: reporting
    zero would open the cap.
    """
    path = Path(database) if database else state_database()
    if not path.exists():
        return 0.0
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True,
                                 timeout=5.0)
    try:
        row = connection.execute(
            "SELECT COALESCE(SUM(COALESCE(settled_usd, reserved_usd)), 0.0) "
            "FROM reservations").fetchone()
    except sqlite3.OperationalError:
        # No ledger table yet: the engine has not written one. Same as a
        # store that is not there.
        return 0.0
    finally:
        connection.close()
    return float(row[0] or 0.0)


def allowed(database: Path | str | None = None) -> Verdict:
    """May a new run start?

    Refuses at the cap as well as above it: reaching exactly the cap means
    the budget is gone, and the next run would cross it.
    """
    cap = cap_usd()
    if cap is None:
        return Verdict(allowed=True, spent_usd=0.0, cap_usd=None,
                       uncapped=True)
    so_far = spent(database)
    return Verdict(allowed=so_far < cap, spent_usd=so_far, cap_usd=cap)


def refusal(verdict: Verdict) -> dict[str, object]:
    """The body a refused run answers with, in the shape the UI renders."""
    return {
        "error_code": "SPEND_CAP_REACHED",
        "message": (
            f"This deployment's cumulative spend cap of "
            f"USD {verdict.cap_usd:,.2f} has been reached "
            f"(USD {verdict.spent_usd:,.2f} recorded). No further question "
            f"will be sent to the provider. Raise {CAP_VAR} deliberately, or "
            f"unset it, to continue."),
        "capability": "spend_cap",
        **verdict.to_dict(),
    }


__all__ = ["CAP_VAR", "SpendCapInvalid", "Verdict", "allowed", "cap_usd",
           "refusal", "spent", "state_database"]
