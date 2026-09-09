"""
Every one of the 123 signals, as columns a person can name.

Why this exists
---------------
The scoring model is normalised, and it has to be: a signal observation is a
row, and an obligor-month has as many of them as fired. That is the right shape
for an audit trail and the wrong one for a question. "Which obligors have a
covenant breach this month, and what was the reading behind it?" should not
require a reader — or a planner writing bounded analysis against this domain —
to know that the answer lives in a second dataset keyed on a signal key they
have not been shown.

So the signal inventory is projected onto the customer-month grain: one column
per business field per signal, named after the signal, with the inventory
number in front so the name is unique and stable however the workbook renames
things.

The absent ones are the point
-----------------------------
All 123 inventory rows get columns, not only the ones the build populates. A
field dictionary that listed only the signals with data would tell a planner
that the other eighty-five do not exist, when what is true is that they exist
and this deployment has no feed for them yet. The measured coverage in the
dictionary says which is which — counted from the published rows rather than
declared — and that is a far more useful thing to know than a shorter list.

The eighteen that are not scored
---------------------------------
Ten merged, five dropped, two replaced and one moved. They carry status,
status detail and lineage and nothing else, because there is no score to
explain: a column for the accelerator bands of a dropped signal would be a
column that is empty for a reason nobody could recover.
"""

from __future__ import annotations

import functools
import re
from dataclasses import dataclass
from typing import Any

from backend.early_warning import catalog as cat

#: The per-signal columns every SCORED signal carries. Suffix, dtype, the
#: business label, and what the field means — the dictionary is generated from
#: this table, so a column and its definition cannot drift apart.
SCORED_MEASURES: tuple[tuple[str, str, str, str], ...] = (
    ("status", "string", "scoring status",
     "Whether this inventory row is scored, merged, dropped, replaced or "
     "moved in the current methodology."),
    ("fired", "boolean", "trigger fired",
     "Whether this signal fired for this obligor in this month. False means "
     "the signal was in scope and did not fire; a signal with no feed is "
     "false in every month and its coverage says so."),
    ("observed_value", "number", "observed value",
     "The raw reading the trigger saw — the balance, the utilisation, the "
     "rating, the event severity — before any normalisation."),
    ("baseline_value", "number", "baseline compared against",
     "What the reading was measured against: the obligor's own trailing "
     "baseline, or the previous period's value for a transition signal."),
    ("normalised_value", "number", "normalised value",
     "The transformed figure the severity band was taken from, usually an "
     "adverse percentage change against the baseline."),
    ("observed_unit", "string", "unit of the reading",
     "What the observed and normalised values are expressed in."),
    ("trigger_severity_band", "number", "trigger severity band",
     "The 1-5 severity band the normalised reading fell into."),
    ("trigger_score", "number", "trigger severity score",
     "The score the severity band carries, before any accelerator."),
    ("magnitude_band", "number", "magnitude band",
     "Accelerator dimension: how large the movement was, 1-5."),
    ("velocity_band", "number", "velocity band",
     "Accelerator dimension: how fast the movement happened, 1-5."),
    ("persistence_band", "number", "persistence band",
     "Accelerator dimension: how long the condition has been live, 1-5."),
    ("repetition_band", "number", "repetition band",
     "Accelerator dimension: how often this signal has recurred, 1-5."),
    ("corroboration_band", "number", "corroboration band",
     "Accelerator dimension: whether other feeds corroborate the reading, "
     "1-5, where 1 is corroborated and a high band is a lone source."),
    ("accelerator_multiplier", "number", "accelerator multiplier",
     "The combined multiplier the five dimensions and the decay produced."),
    ("decay_class", "string", "decay class",
     "Which decay curve this signal's sub-category uses."),
    ("decay_factor", "number", "decay factor applied",
     "The decay actually applied. A live condition holds at 1.0 however old "
     "it is; the clock only starts once it cures."),
    ("score", "number", "signal score",
     "The signal's final contribution, severity times accelerator times "
     "decay, before chain deduplication and the sub-category roll-up."),
    ("reason_code", "string", "reason code",
     "The canonical reason this signal carries, as node and severity band."),
    ("reason", "string", "reason",
     "The published reason text for this node at the severity it fired."),
    ("source_system", "string", "source system",
     "The upstream system the reading came from, for verification."),
    ("evidence_age_days", "number", "evidence age (days)",
     "How old the reading is, in days, at this month end."),
    ("freshness", "string", "evidence freshness",
     "Fresh, ageing or stale, from the evidence age against the signal's "
     "own update frequency."),
)

#: What the eighteen non-scored inventory rows carry.
INVENTORY_MEASURES: tuple[tuple[str, str, str, str], ...] = (
    ("status", "string", "scoring status",
     "Whether this inventory row is scored, merged, dropped, replaced or "
     "moved in the current methodology."),
    ("status_detail", "string", "status detail",
     "What happened to this row — which signal it merged into, what "
     "replaced it, or why it was dropped."),
    ("source_system", "string", "source system",
     "The upstream system this signal would read, kept so the inventory "
     "remains traceable after the row stopped being scored."),
)

#: Evidence older than this, in days, is stale. Between the two it is ageing.
FRESH_DAYS = 45
AGEING_DAYS = 120


@dataclass(frozen=True)
class SignalField:
    """One inventory row, and the columns it contributes."""

    num: int
    prefix: str
    code: str
    layer: str
    name: str
    sub_category_name: str
    status: str
    status_detail: str
    source_system: str
    what_is_measured: str
    update_frequency: str
    tac_role: str
    trigger_key: str
    classifier_key: str

    @property
    def scored(self) -> bool:
        return self.status == cat.SCORED

    @property
    def measures(self) -> tuple[tuple[str, str, str, str], ...]:
        return SCORED_MEASURES if self.scored else INVENTORY_MEASURES

    def column(self, suffix: str) -> str:
        return f"{self.prefix}_{suffix}"

    @property
    def columns(self) -> tuple[str, ...]:
        return tuple(self.column(suffix) for suffix, *_ in self.measures)


def _slug(text: str) -> str:
    """A signal's name as the readable half of a column name."""
    cleaned = re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")
    if len(cleaned) <= 46:
        return cleaned
    # Cut at a word boundary rather than mid-word: `..._concentrat` reads as
    # a typo and a planner will retype it as the word it looks like.
    parts = cleaned.split("_")
    out: list[str] = []
    for part in parts:
        if len("_".join(out + [part])) > 46:
            break
        out.append(part)
    return "_".join(out) or cleaned[:46]


@functools.lru_cache(maxsize=1)
def fields() -> tuple[SignalField, ...]:
    """Every inventory row, in workbook order.

    The prefix carries the inventory number, so two signals whose names
    shorten to the same slug still get different columns, and a column keeps
    its name when the workbook rewords a signal.
    """
    out: list[SignalField] = []
    for resolved in cat.resolve_all():
        row = resolved.row
        out.append(SignalField(
            num=row.num,
            prefix=f"sig{row.num:03d}_{_slug(row.name)}",
            code=row.code,
            layer=row.layer,
            name=row.name,
            sub_category_name=row.sub_category,
            status=row.status,
            status_detail=row.status_detail,
            source_system=row.source_system,
            what_is_measured=row.what_is_measured,
            update_frequency=row.update_frequency,
            tac_role=row.tac_role,
            trigger_key=resolved.linked_trigger_key or "",
            classifier_key=resolved.linked_classifier_key or "",
        ))
    return tuple(out)


@functools.lru_cache(maxsize=1)
def by_trigger_key() -> dict[str, tuple[SignalField, ...]]:
    """Which inventory rows a fired trigger key populates.

    A tuple rather than one row: the workbook has signals that share a
    trigger, and quietly picking the first would leave the others looking
    like they never fire.
    """
    out: dict[str, list[SignalField]] = {}
    for entry in fields():
        if entry.trigger_key:
            out.setdefault(entry.trigger_key, []).append(entry)
    return {key: tuple(rows) for key, rows in out.items()}


@functools.lru_cache(maxsize=1)
def scored_fields() -> tuple[SignalField, ...]:
    return tuple(f for f in fields() if f.scored)


@functools.lru_cache(maxsize=1)
def columns() -> tuple[str, ...]:
    """Every signal column the wide view exposes, in inventory order."""
    return tuple(column for entry in fields() for column in entry.columns)


def freshness(age_days: float | None) -> str:
    """Fresh, ageing or stale — said in words rather than left as a number.

    A reader deciding whether to act on a signal is asking whether the
    reading is current, and "217" only answers that for somebody who already
    knows the update frequency.
    """
    if age_days is None:
        return ""
    try:
        days = float(age_days)
    except (TypeError, ValueError):
        return ""
    if days <= FRESH_DAYS:
        return "fresh"
    if days <= AGEING_DAYS:
        return "ageing"
    return "stale"


def describe() -> dict[str, Any]:
    """What the inventory projection covers, for the handoff and the tests."""
    scored = scored_fields()
    return {
        "inventory_rows": len(fields()),
        "scored": len(scored),
        "not_scored": len(fields()) - len(scored),
        "columns": len(columns()),
        "columns_per_scored_signal": len(SCORED_MEASURES),
        "columns_per_inventory_signal": len(INVENTORY_MEASURES),
        "status_counts": cat.status_counts(),
    }


__all__ = ["AGEING_DAYS", "FRESH_DAYS", "INVENTORY_MEASURES",
           "SCORED_MEASURES", "SignalField", "by_trigger_key", "columns",
           "describe", "fields", "freshness", "scored_fields"]
