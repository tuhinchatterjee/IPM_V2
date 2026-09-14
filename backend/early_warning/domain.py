"""The one definition of what the Early Warning domain is.

Why this is a module rather than a convention
---------------------------------------------
Six places had to agree on what Early Warning data is: the Data Builder's
registration, the planner's schema, the validator's allow-list, the executor's
data access, the field dictionary and the dashboard. They agreed by repetition
-- the same three dataset names written out six times -- which is not
agreement, it is six chances to differ. This module is the definition; the
others read it.

What it enforces
----------------
Early Warning answers from the published Early Warning snapshots and nothing
else. Not `corporate_borrower_360`, not `corporate_ifrs9`, not
`corporate_financials`, not the retail scorecards -- and the reason is not
territorial. Those datasets have ALREADY fed Early Warning: the snapshot holds
a governed copy of the rating, the stage, the utilisation and the arrears as
they stood when the score was computed. Reading them again at answer time
reads the same fact from two places that can disagree, and the answer would
then be about neither the score nor the source.

So the rule is an allow-list of three, not a deny-list of everything else. A
deny-list is a list somebody has to remember to extend, and the dataset it
does not name is the one that gets read.

The door
--------
`require()` is called by `v2_service._load`, which is the single function
through which every Early Warning figure is read. Guarding the door rather
than the callers means a future code path cannot reach outside the domain by
being new.

Audit
-----
`recording()` collects the datasets a turn actually read, so the result packet
can state which ones they were rather than asserting that the rule held. A
claim about enforcement that is not observed is a comment.
"""

from __future__ import annotations

import contextvars
from contextlib import contextmanager
from typing import Iterator

#: The canonical business name. What a reader is shown.
DOMAIN = "Early Warning"

#: The canonical identifier. What the domain lock, the planner schema, the
#: validator and the result packet all compare against.
DOMAIN_ID = "early_warning"

BORROWER_MONTH = "early_warning_borrower_month"
SIGNAL_OBSERVATION = "early_warning_signal_observation"
EXTERNAL_EVENT = "early_warning_external_event_synthetic"

#: Every dataset an Early Warning answer may read. The allow-list.
DATASETS: frozenset[str] = frozenset({
    BORROWER_MONTH, SIGNAL_OBSERVATION, EXTERNAL_EVENT})

#: Named only so a refusal can say something useful about the commonest
#: mistakes. NOT the rule -- `DATASETS` is the rule, and a dataset missing
#: from this tuple is refused exactly as firmly as one in it.
UPSTREAM_OF_EARLY_WARNING: tuple[str, ...] = (
    "corporate_borrower_360", "corporate_ifrs9", "corporate_financials",
    "corporate_ratings", "corporate_facilities", "corporate_collateral",
    "corporate_covenants", "corporate_delinquency", "corporate_limits",
    "customer_ratings", "ifrs9_staging", "collateral_register",
)


class OutOfDomain(PermissionError):
    """An Early Warning read reached for data outside the domain.

    A PermissionError rather than a ValueError: this is not a typo to be
    corrected, it is an access rule. Callers that catch it should refuse the
    request, never fall back to reading something else.
    """


def is_in_domain(dataset: str) -> bool:
    return str(dataset) in DATASETS


def require(dataset: str) -> str:
    """Return the dataset name, or refuse to let it be read.

    The refusal says what was reached for and why it is not allowed, because
    a message that only says "denied" sends the next reader looking for a
    configuration flag that does not exist.
    """
    name = str(dataset)
    if name in DATASETS:
        return name

    detail = ""
    if name in UPSTREAM_OF_EARLY_WARNING:
        detail = (f" {name} is upstream of Early Warning: the snapshot "
                  "already holds a governed copy of what it contributed, as "
                  "it stood when the score was computed. Reading it again "
                  "now would read the same fact from two places that can "
                  "disagree.")
    raise OutOfDomain(
        f"Early Warning may not read {name!r}. It answers from "
        f"{', '.join(sorted(DATASETS))} and nothing else.{detail}")


# ------------------------------------------------------------------ audit

_READS: contextvars.ContextVar[set[str] | None] = contextvars.ContextVar(
    "early_warning_datasets_read", default=None)


def note_read(dataset: str) -> None:
    """Record that a dataset was read, if anything is listening.

    Cheap and silent when nothing is recording, which is the normal case: a
    dashboard request should not pay for an audit nobody asked for.
    """
    seen = _READS.get()
    if seen is not None:
        seen.add(str(dataset))


@contextmanager
def recording() -> Iterator[set[str]]:
    """Collect the datasets read inside this block.

    Context-local, so two turns running at once each see their own reads --
    the ask lifecycle runs a turn on its own thread, and a process-wide list
    would have attributed one turn's reads to another.
    """
    seen: set[str] = set()
    token = _READS.set(seen)
    try:
        yield seen
    finally:
        _READS.reset(token)


def datasets_read() -> tuple[str, ...]:
    """What has been read so far in the current recording, in order."""
    seen = _READS.get()
    return tuple(sorted(seen)) if seen else ()


__all__ = ["BORROWER_MONTH", "DATASETS", "DOMAIN", "DOMAIN_ID",
           "EXTERNAL_EVENT", "OutOfDomain", "SIGNAL_OBSERVATION",
           "UPSTREAM_OF_EARLY_WARNING", "datasets_read", "is_in_domain",
           "note_read", "recording", "require"]
