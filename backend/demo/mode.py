"""Demo Mode. §4 of the client-demo release-candidate brief.

    "clear DEMO / SYNTHETIC DATA label; fixed demo data release/version; no
     accidental client-data expectation; stable seeded users/projects/cases;
     deterministic sample entities; repeatable reset; background schedules
     disabled unless explicitly started; no automatic external communication;
     no automatic publication/certification/approval; all destructive actions
     require explicit confirmation."

One switch, read once, and every consequence derived from it rather than
scattered as separate flags somebody can set inconsistently. A deployment that
is in Demo Mode with schedules running is not in Demo Mode; making the
consequences properties of the one setting is what stops that combination
existing.

What Demo Mode is NOT
---------------------
It is not Demo Safe Mode (`backend/release/demo_safe.py`), which governs
whether an ANSWER may be shown. Demo Mode governs whether this DEPLOYMENT is a
demonstration. They are independent: a pilot on real client data wants Demo
Safe Mode on and Demo Mode off, and running the second against real data would
label a client's own portfolio as synthetic.

It is also not a licence to fake anything. Nothing here changes a figure, an
answer, a plan, an assurance verdict or a score. Everything it touches is
labelling, background activity and confirmation.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from backend.release import product_copy

DEMO_MODE_VERSION = "1.0.0"

#: The switch. Read from the environment rather than from the database,
#: because a demonstration host is configured before it has a database.
ENV = "CREDITPROBE_DEMO_MODE"

#: What the user is told, verbatim, wherever data appears. Short enough for a
#: header chip and unambiguous enough that nobody can later say they thought
#: the figures were their own.
#:
#: It used to read "DEMO - SYNTHETIC DATA". The second half is the part that
#: matters and the first half was the part that made the product sound like a
#: rehearsal, so the first half is gone (§13). Dropping the disclosure
#: altogether was never an option: presenting a generated portfolio as a
#: bank's own book is the one thing worse than saying "demo".
LABEL = product_copy.SYNTHETIC_LABEL

LABEL_DETAIL = product_copy.SYNTHETIC_DETAIL

#: The data release this deployment is pinned to. A deployment whose data can
#: change under it is not repeatable, and "it worked yesterday" is the least
#: useful sentence in a release war room.
#:
#: The identifier itself is a version string, not product copy — it is shown
#: as a release name and nobody reads it as a claim about the product.
DATA_RELEASE = "creditprobe-synthetic-2026Q2"

#: The truthful values of `_TRUTHS` below, given the switch. Stated as data so
#: a test can assert the whole policy in one comparison rather than probing
#: nine functions and hoping it caught them all.
_TRUTHS: dict[str, tuple[bool, str]] = {
    "synthetic_label": (
        True, "Every screen states that the data is synthetic."),
    "fixed_data_release": (
        True, "This deployment is pinned to one named data release."),
    "background_schedules": (
        False, "Agent schedules do not fire on their own. Somebody starts a "
               "run deliberately, or nothing runs."),
    "external_communication": (
        False, "Nothing is emailed, posted or sent outside this host."),
    "automatic_publication": (
        False, "Nothing is published globally, certified or approved without "
               "a person doing it."),
    "destructive_confirmation": (
        True, "Deleting or resetting anything asks first."),
}

#: The keys above, in the order they are reported.
GUARANTEES: tuple[str, ...] = tuple(_TRUTHS)

GUARANTEE_MEANS: dict[str, str] = {k: why for k, (_, why) in _TRUTHS.items()}


def enabled() -> bool:
    """Whether this deployment is running as a demonstration.

    Fail-closed in the direction that matters: an unset variable means NOT a
    demonstration, so a production deployment cannot acquire a synthetic-data
    label by forgetting to set something.
    """
    return os.environ.get(ENV, "").strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Posture:
    """What Demo Mode is currently guaranteeing, and what it is not.

    Returned whole rather than queried one flag at a time, so the API, the
    header chip and `demo-check.ps1` all read the same object and cannot
    disagree about whether schedules are suppressed.
    """

    on: bool = False
    label: str = ""
    detail: str = ""
    data_release: str = ""
    guarantees: dict[str, bool] = field(default_factory=dict)
    version: str = DEMO_MODE_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "demo_mode": self.on,
            "label": self.label,
            "detail": self.detail,
            "data_release": self.data_release,
            "guarantees": dict(self.guarantees),
            "guarantee_means": dict(GUARANTEE_MEANS),
            "version": self.version,
        }

    def sentence(self) -> str:
        if not self.on:
            return (f"{product_copy.SYNTHETIC_MODE_LABEL} is OFF. Data is not "
                    "labelled synthetic, schedules run normally, and nothing "
                    "is suppressed.")
        return (f"{product_copy.SYNTHETIC_MODE_LABEL} is ON, pinned to "
                f"{self.data_release}. {self.detail}")


def posture() -> Posture:
    """The whole policy, derived from the one switch."""
    on = enabled()
    return Posture(
        on=on,
        label=LABEL if on else "",
        detail=LABEL_DETAIL if on else "",
        data_release=DATA_RELEASE if on else "",
        # Off, every guarantee is simply absent — not "False", which would
        # read as a promise that external communication is happening.
        guarantees={k: want for k, (want, _) in _TRUTHS.items()} if on else {},
    )


def schedules_may_fire() -> bool:
    """§4: background schedules are disabled unless explicitly started.

    The agent worker asks this before claiming a due schedule. A presenter can
    still run a review from the screen — what is suppressed is a schedule
    firing during the demonstration and competing for the same database.
    """
    return not enabled()


def may_communicate_externally() -> bool:
    """§4: no automatic external communication."""
    return not enabled()


def may_publish_automatically() -> bool:
    """§4: no automatic publication, certification or approval.

    Note the word: AUTOMATICALLY. A person clicking Publish still publishes;
    what this refuses is a code path that publishes on their behalf.
    """
    return not enabled()


def requires_confirmation() -> bool:
    """§4: all destructive actions require explicit confirmation."""
    return enabled()
