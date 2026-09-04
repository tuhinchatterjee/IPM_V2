"""What changed since the previous committee.

The question a chair asks first, and the one a pack is worst at answering.
Comparing two packs by looking at them is a person reading forty numbers twice;
comparing them here is reading two sets of snapshots, which is what the
snapshots exist for.

Compared against the STORED figures, never recalculated
--------------------------------------------------------
The previous pack's numbers are the ones the committee was given, not the ones
its metrics return today. If a formula was revised in between, the comparison
says so — a movement that is really a definition change is the most misleading
line a pack can carry, and it is invisible unless somebody checks the formula
hash. This module checks it.

Four kinds of difference, kept apart
-------------------------------------
    MOVED       the same metric, same formula, a different number
    REDEFINED   the same metric, a DIFFERENT formula — so the movement is
                partly or wholly a change in what is being measured
    ADDED       a metric this pack carries that the previous one did not
    REMOVED     a metric the previous pack carried that this one does not

The last two matter more than they look. A pack that quietly stopped showing
the overlay balance is a pack whose reader does not know they stopped seeing
it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select

from backend.models.playbook import (
    SOURCE_UI,
    PlaybookBlock,
    PlaybookPack,
    PlaybookSection,
    PlaybookSnapshot,
)
from backend.playbook import access
from backend.playbook import snapshots as snap

logger = logging.getLogger(__name__)

MOVED = "MOVED"
REDEFINED = "REDEFINED"
ADDED = "ADDED"
REMOVED = "REMOVED"
UNCHANGED = "UNCHANGED"
NOW_UNAVAILABLE = "NOW_UNAVAILABLE"
NOW_AVAILABLE = "NOW_AVAILABLE"

#: Relative movement below this is reported as UNCHANGED. A pack that lists
#: forty metrics as "changed" because the fifteenth decimal place moved is a
#: comparison nobody reads.
NOISE = 1e-9


@dataclass
class Difference:
    """One metric, then and now."""

    metric_id: str
    name: str
    kind: str
    now_value: float | None = None
    now_display: str = "—"
    then_value: float | None = None
    then_display: str = "—"
    change: float | None = None
    change_display: str = ""
    direction: str = ""
    better: bool | None = None
    now_period: str = ""
    then_period: str = ""
    #: Set on REDEFINED. Names what a reader has to know before comparing.
    caveat: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric_id": self.metric_id, "name": self.name, "kind": self.kind,
            "now_value": self.now_value, "now_display": self.now_display,
            "then_value": self.then_value, "then_display": self.then_display,
            "change": self.change, "change_display": self.change_display,
            "direction": self.direction, "better": self.better,
            "now_period": self.now_period, "then_period": self.then_period,
            "caveat": self.caveat,
        }


@dataclass
class Comparison:
    """This pack against the previous one, and what a reader should notice."""

    pack_id: int
    pack_code: str
    previous_pack_id: int | None = None
    previous_pack_code: str = ""
    previous_meeting: str = ""
    differences: list[Difference] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def material(self) -> list[Difference]:
        """Everything a reader should look at, worst movement first."""
        wanted = [d for d in self.differences
                  if d.kind not in (UNCHANGED,)]
        return sorted(
            wanted,
            key=lambda d: (
                # Redefinitions first: they change what every other line means.
                0 if d.kind == REDEFINED else 1,
                0 if d.better is False else 1,
                -abs(d.change or 0.0)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "pack_id": self.pack_id, "pack_code": self.pack_code,
            "previous_pack_id": self.previous_pack_id,
            "previous_pack_code": self.previous_pack_code,
            "previous_meeting": self.previous_meeting,
            "differences": [d.to_dict() for d in self.differences],
            "material": [d.to_dict() for d in self.material],
            "notes": list(self.notes),
            "summary": self.summary,
        }

    @property
    def summary(self) -> str:
        if self.previous_pack_id is None:
            return ("This is the first pack this committee has approved, so "
                    "there is nothing to compare it against.")
        redefined = [d for d in self.differences if d.kind == REDEFINED]
        added = [d for d in self.differences if d.kind == ADDED]
        removed = [d for d in self.differences if d.kind == REMOVED]
        moved = [d for d in self.differences if d.kind == MOVED]
        bits = []
        if moved:
            worse = len([d for d in moved if d.better is False])
            bits.append(f"{len(moved)} figure{'s' if len(moved) != 1 else ''} "
                        f"moved" + (f", {worse} for the worse" if worse else ""))
        if redefined:
            bits.append(f"{len(redefined)} was measured differently last time")
        if added:
            bits.append(f"{len(added)} is new")
        if removed:
            bits.append(f"{len(removed)} is no longer shown")
        if not bits:
            return (f"Nothing material changed against {self.previous_pack_code}.")
        return (f"Against {self.previous_pack_code}: " + ", ".join(bits) + ".")


def against_previous(session: Any, pack_id: int, principal: Any, *,
                     source: str = SOURCE_UI) -> dict[str, Any]:
    """This pack against the previous approved one of the same committee."""
    pack, _ = access.readable_pack(session, pack_id, principal, source)
    previous = _previous(session, pack)
    return against(session, pack, previous).to_dict()


def against(session: Any, pack: Any, previous: Any) -> Comparison:
    """Two packs, compared from their stored figures.

    Neither pack is recalculated. That is the point: the previous pack's
    numbers are what the committee was given, and re-deriving them today would
    compare this pack against a history that never happened.
    """
    out = Comparison(pack_id=int(pack.id), pack_code=str(pack.code))
    now = _figures(session, pack)

    if previous is None:
        out.notes.append(
            "No previous approved pack was found for this committee.")
        for metric_id, figure in now.items():
            out.differences.append(Difference(
                metric_id=metric_id, name=figure.metric_name or metric_id,
                kind=ADDED, now_value=figure.value,
                now_display=figure.display_value,
                now_period=figure.period))
        return out

    out.previous_pack_id = int(previous.id)
    out.previous_pack_code = str(previous.code)
    out.previous_meeting = (previous.meeting_at.date().isoformat()
                            if previous.meeting_at else "")
    then = _figures(session, previous, at_version=previous.approved_version)

    for metric_id in sorted(set(now) | set(then)):
        here, there = now.get(metric_id), then.get(metric_id)
        if here is None:
            out.differences.append(Difference(
                metric_id=metric_id,
                name=there.metric_name or metric_id, kind=REMOVED,
                then_value=there.value, then_display=there.display_value,
                then_period=there.period,
                caveat=("This pack does not show it. A reader who saw it last "
                        "time has not been told it is gone.")))
            continue
        if there is None:
            out.differences.append(Difference(
                metric_id=metric_id, name=here.metric_name or metric_id,
                kind=ADDED, now_value=here.value,
                now_display=here.display_value, now_period=here.period))
            continue
        out.differences.append(_between(here, there))
    return out


def _between(here: snap.Figure, there: snap.Figure) -> Difference:
    """One metric in two packs.

    The formula-hash check comes first. A movement across a definition change
    is not a movement in the book, and reporting it as one is the most
    confidently wrong line a comparison can produce.
    """
    made = Difference(
        metric_id=here.metric_id, name=here.metric_name or here.metric_id,
        kind=UNCHANGED,
        now_value=here.value, now_display=here.display_value,
        then_value=there.value, then_display=there.display_value,
        now_period=here.period, then_period=there.period)

    if (here.formula_hash and there.formula_hash
            and here.formula_hash != there.formula_hash):
        made.kind = REDEFINED
        made.caveat = (
            f"{made.name} is not calculated the same way in the two packs "
            f"(version {there.metric_version or 'unknown'} then, "
            f"{here.metric_version or 'unknown'} now). Any difference between "
            "the two figures is partly or wholly a change in what is being "
            "measured, so they should not be read as a movement.")
        if here.value is not None and there.value is not None:
            made.change = here.value - there.value
            made.change_display = snap.display(made.change, here.unit,
                                               here.decimals)
        return made

    if here.value is None and there.value is not None:
        made.kind = NOW_UNAVAILABLE
        made.caveat = here.unavailable_reason
        return made
    if here.value is not None and there.value is None:
        made.kind = NOW_AVAILABLE
        when = there.period or "the previous pack"
        made.caveat = f"It had no value in {when}: {there.unavailable_reason}"
        return made
    if here.value is None and there.value is None:
        made.caveat = here.unavailable_reason
        return made

    change = float(here.value) - float(there.value)
    scale = max(1.0, abs(float(there.value)))
    if abs(change) / scale <= NOISE:
        return made

    made.kind = MOVED
    made.change = change
    made.change_display = snap.display(change, here.unit, here.decimals)
    made.direction = "up" if change > 0 else "down"
    if here.higher_is_better is not None:
        made.better = (made.direction == "up") == bool(here.higher_is_better)
    if here.period and there.period and here.period == there.period:
        made.caveat = (
            f"Both packs report {here.period}, so this is a restatement "
            "rather than a movement between periods.")
    return made


def _figures(session: Any, pack: Any,
             at_version: int | None = None) -> dict[str, snap.Figure]:
    """The figures a pack is SHOWING, by metric.

    Read through the blocks rather than by querying snapshots directly,
    because a pack holds a snapshot row for every version it has ever been
    generated at, and the ones it shows are the ones its blocks point at.
    """
    blocks = session.execute(
        select(PlaybookBlock).where(
            PlaybookBlock.pack_id == pack.id,
            PlaybookBlock.snapshot_id.isnot(None))).scalars().all()
    ids = [int(b.snapshot_id) for b in blocks]
    if not ids:
        return {}
    rows = session.execute(
        select(PlaybookSnapshot)
        .where(PlaybookSnapshot.id.in_(ids))).scalars().all()
    out: dict[str, snap.Figure] = {}
    for row in rows:
        if at_version is not None and int(row.pack_version) > int(at_version):
            # A superseded pack that was edited after approval would otherwise
            # be compared at its draft figures rather than its approved ones.
            continue
        out.setdefault(str(row.metric_id), snap.from_row(row))
    return out


def _previous(session: Any, pack: Any) -> Any:
    """The pack this one compares against.

    The stored link first, because it survives a backfill. Falling back to
    "the most recent approved pack before this meeting" only where the link
    was never set.
    """
    if pack.previous_pack_id is not None:
        return session.get(PlaybookPack, int(pack.previous_pack_id))
    query = select(PlaybookPack).where(
        PlaybookPack.committee_id == pack.committee_id,
        PlaybookPack.id != pack.id,
        PlaybookPack.status.in_(("APPROVED", "PUBLISHED", "SUPERSEDED")))
    if pack.meeting_at is not None:
        query = query.where(PlaybookPack.meeting_at < pack.meeting_at)
    return session.execute(query.order_by(
        PlaybookPack.meeting_at.desc().nullslast(),
        PlaybookPack.id.desc()).limit(1)).scalar_one_or_none()


def sections_of(session: Any, pack: Any) -> dict[str, str]:
    """Section titles by template key, for comparing two packs' shapes.

    A pack that dropped a required section between meetings is a governance
    change, and it is only detectable by key: titles get reworded.
    """
    rows = session.execute(
        select(PlaybookSection).where(
            PlaybookSection.pack_id == pack.id)).scalars().all()
    return {str(s.template_key or f"#{s.position}"): str(s.title)
            for s in rows}


def shape_changes(session: Any, pack: Any, previous: Any) -> list[str]:
    """Sections added or dropped between two packs, in plain sentences."""
    if previous is None:
        return []
    now, then = sections_of(session, pack), sections_of(session, previous)
    out = []
    for key in sorted(set(then) - set(now)):
        out.append(f"“{then[key]}” was in {previous.code} and is not in this "
                   "pack.")
    for key in sorted(set(now) - set(then)):
        out.append(f"“{now[key]}” is new since {previous.code}.")
    return out


__all__ = [
    "ADDED", "Comparison", "Difference", "MOVED", "NOISE", "NOW_AVAILABLE",
    "NOW_UNAVAILABLE", "REDEFINED", "REMOVED", "UNCHANGED", "against",
    "against_previous", "sections_of", "shape_changes",
]
