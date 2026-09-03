"""The critical path, calculated — and refused when it cannot be.

`control.py` already reports what is late and what is blocking what. This
module answers a different question: *given the dependency network and the
durations, which chain determines the end date, and how much slack does
everything else have?*

Three commitments shape it.

**A marker is not a calculation.** A task carries a `critical` flag somebody
ticked. That is a human judgement and it stays exactly where it is. What comes
out of here is a separate concept — CALCULATED — and the two are reported
side by side, never merged. A plan where they disagree is interesting; a
product that quietly overwrote one with the other would hide the disagreement.

**Refuse rather than guess.** A critical path computed over a network with a
missing duration is not an approximation, it is a different network. When the
inputs are not there this returns `computed=False` and the sentences that say
which task, by name. "Critical path cannot be calculated because T-104 and
T-110 have neither a start-and-due pair nor an effort estimate" is a useful
thing to read; a path drawn from three of five tasks is not.

**Dates, not working days.** CreditProbe's planner records calendar dates and
no working calendar, so the arithmetic here is in calendar days. Introducing a
five-day week without a holiday calendar would produce dates that are wrong in
a way nobody can see. That is stated in `basis` and shown on the screen.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from backend.models.planner import (
    DEP_FINISH_TO_FINISH,
    DEP_FINISH_TO_START,
    DEP_START_TO_FINISH,
    DEP_START_TO_START,
    ENTITY_MILESTONE,
    ENTITY_TASK,
)
from backend.planner import control

SCHEDULE_VERSION = "1.0.0"

#: What the arithmetic counts. Named so the screen and the API can say it.
BASIS_CALENDAR = "calendar_days"


# ============================================================== the network


@dataclass(frozen=True)
class Node:
    """One thing with a duration, whatever kind of thing it is.

    Milestones are zero-duration nodes rather than a separate concept: that is
    what a milestone *is* in a schedule, and modelling it any other way means
    two code paths for one arithmetic.
    """

    kind: str
    id: int
    code: str
    name: str
    duration: int
    #: What the person ticked. Carried through untouched, for comparison.
    marked_critical: bool = False
    complete: bool = False
    #: Where the duration came from, so a reader can see whether the number is
    #: a laid-out span or an estimate.
    duration_from: str = ""
    #: A recorded start date is a constraint, not a suggestion: a task planned
    #: to begin on 2 February cannot be scheduled into January because its
    #: predecessors happen to finish early. This is the scheduler's
    #: start-no-earlier-than, and it is set for tasks only — a milestone's
    #: target date is a target, and letting it hold the milestone open would
    #: report a date the network does not actually require.
    not_earlier_than: date | None = None
    #: What the plan says this is aimed at, for the fallback anchor and for
    #: comparison on screen. Never a constraint.
    target: date | None = None

    @property
    def key(self) -> tuple[str, int]:
        return (self.kind, self.id)


@dataclass
class Scheduled:
    """One node, placed."""

    node: Node
    early_start: date
    early_finish: date
    late_start: date
    late_finish: date

    @property
    def total_float(self) -> int:
        return (self.late_start - self.early_start).days

    @property
    def critical(self) -> bool:
        """Zero slack. Not "somebody thinks this matters"."""
        return self.total_float <= 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.node.kind, "id": self.node.id,
            "code": self.node.code, "name": self.node.name,
            "duration_days": self.node.duration,
            "duration_from": self.node.duration_from,
            "planned_start": (self.node.not_earlier_than.isoformat()
                              if self.node.not_earlier_than else None),
            "planned_finish": (self.node.target.isoformat()
                               if self.node.target else None),
            "early_start": self.early_start.isoformat(),
            "early_finish": self.early_finish.isoformat(),
            "late_start": self.late_start.isoformat(),
            "late_finish": self.late_finish.isoformat(),
            "total_float_days": self.total_float,
            "calculated_critical": self.critical,
            "marked_critical": self.node.marked_critical,
            "complete": self.node.complete,
            # The disagreement is the interesting column, so it is a field
            # rather than something a reader has to spot.
            "disagrees": self.critical != self.node.marked_critical,
        }


@dataclass
class Schedule:
    """What the engine worked out, or why it would not."""

    computed: bool = False
    basis: str = BASIS_CALENDAR
    placed: list[Scheduled] = field(default_factory=list)
    #: Codes along the critical chain, in order.
    critical_path: list[str] = field(default_factory=list)
    project_start: date | None = None
    project_finish: date | None = None
    #: Sentences. Present exactly when `computed` is False.
    cannot_because: list[str] = field(default_factory=list)
    #: Nodes the person marked critical that the arithmetic did not, and the
    #: other way round. A project manager's first question about a CPM screen.
    marked_not_calculated: list[str] = field(default_factory=list)
    calculated_not_marked: list[str] = field(default_factory=list)

    def by_code(self, code: str) -> Scheduled | None:
        for row in self.placed:
            if row.node.code == code:
                return row
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "computed": self.computed,
            "basis": self.basis,
            "version": SCHEDULE_VERSION,
            "nodes": [p.to_dict() for p in self.placed],
            "critical_path": list(self.critical_path),
            "project_start": (self.project_start.isoformat()
                              if self.project_start else None),
            "project_finish": (self.project_finish.isoformat()
                               if self.project_finish else None),
            "cannot_because": list(self.cannot_because),
            "marked_not_calculated": list(self.marked_not_calculated),
            "calculated_not_marked": list(self.calculated_not_marked),
        }


# ================================================================ durations


def _duration_of(task: Any) -> tuple[int | None, str]:
    """How long a task takes, and where the number came from.

    A laid-out span wins over an estimate: if somebody has said this runs from
    the 3rd to the 10th, that is the commitment, whatever the effort field
    says. Both ends inclusive, because a task that starts and finishes on the
    same day takes a day and not none.
    """
    if task.start_date and task.due_date:
        span = (task.due_date - task.start_date).days + 1
        if span >= 1:
            return span, "start and due dates"
    if task.effort_days:
        effort = int(task.effort_days)
        if effort >= 1:
            return effort, "effort estimate"
    return None, ""


def _network(plan: control.Plan) -> tuple[list[Node], list[Any]]:
    """Every node the dependencies touch, plus the edges between them.

    Only nodes that participate in a dependency matter to a critical path: an
    unlinked task cannot lengthen a chain, and demanding a duration for one
    would refuse to compute a perfectly computable path because somebody left
    an estimate off an unrelated piece of work.
    """
    touched: set[tuple[str, int]] = set()
    edges = [d for d in plan.dependencies]
    for edge in edges:
        touched.add((edge.predecessor_type, int(edge.predecessor_id)))
        touched.add((edge.successor_type, int(edge.successor_id)))

    nodes: list[Node] = []
    for task in plan.tasks:
        if (ENTITY_TASK, int(task.id)) not in touched:
            continue
        duration, source = _duration_of(task)
        nodes.append(Node(
            kind=ENTITY_TASK, id=int(task.id), code=task.code,
            name=task.title, duration=duration or 0,
            marked_critical=bool(task.critical),
            complete=task.status in ("COMPLETED", "CANCELLED"),
            duration_from=source,
            not_earlier_than=task.start_date,
            target=task.due_date))
    for stone in plan.milestones:
        if (ENTITY_MILESTONE, int(stone.id)) not in touched:
            continue
        nodes.append(Node(
            kind=ENTITY_MILESTONE, id=int(stone.id), code=stone.code,
            name=stone.name, duration=0,
            marked_critical=bool(stone.critical),
            complete=stone.status in ("ACHIEVED", "CANCELLED"),
            duration_from="a milestone takes no time",
            not_earlier_than=None,
            target=stone.target_date))
    return nodes, edges


# ============================================================ the two passes


def compute(plan: control.Plan, *, project_start: date | None = None
            ) -> Schedule:
    """Forward pass, backward pass, float, path. Or an honest refusal."""
    nodes, edges = _network(plan)
    out = Schedule()

    if not edges:
        out.cannot_because.append(
            "No dependencies have been recorded between the tasks on this "
            "project. A critical path is the longest chain through a network, "
            "and there is no network until something waits on something else.")
        return out

    index = {n.key: n for n in nodes}
    found = control.cycle(edges)
    if found:
        names = [index[k].code if k in index else f"{k[0].lower()} {k[1]}"
                 for k in found]
        out.cannot_because.append(
            "These depend on each other in a circle, so no order exists: "
            + " → ".join(names) + ".")
        return out

    missing = [n for n in nodes
               if n.kind == ENTITY_TASK and not n.duration_from]
    if missing:
        names = ", ".join(sorted(n.code for n in missing))
        out.cannot_because.append(
            f"{names} {'has' if len(missing) == 1 else 'have'} neither a "
            "start-and-due pair nor an effort estimate, so there is no "
            "duration to add to the chain. Give each one either, and the "
            "path will calculate.")
        return out

    anchor = project_start or _earliest(nodes)
    if anchor is None:
        out.cannot_because.append(
            "Nothing on this project has a date to start from: neither the "
            "project itself nor any task in the dependency network. A "
            "schedule needs one fixed point.")
        return out

    order = _topological(index, edges)
    if order is None:  # pragma: no cover - cycle() already caught this
        out.cannot_because.append(
            "The dependency network could not be put in order.")
        return out

    early_start, early_finish = _forward(index, edges, order, anchor)
    finish = max(early_finish.values())
    late_start, late_finish = _backward(index, edges, order, finish,
                                        early_start, early_finish)

    out.computed = True
    out.project_start = anchor
    out.project_finish = finish
    out.placed = [
        Scheduled(node=index[key], early_start=early_start[key],
                  early_finish=early_finish[key],
                  late_start=late_start[key], late_finish=late_finish[key])
        for key in order]
    out.placed.sort(key=lambda p: (p.early_start, p.node.code))
    out.critical_path = [p.node.code for p in out.placed if p.critical]
    out.marked_not_calculated = sorted(
        p.node.code for p in out.placed
        if p.node.marked_critical and not p.critical)
    out.calculated_not_marked = sorted(
        p.node.code for p in out.placed
        if p.critical and not p.node.marked_critical)
    return out


def _earliest(nodes: list[Node]) -> date | None:
    """The fixed point, when the project itself has no start date.

    The earliest thing anybody planned. A target date counts here — it is the
    only date some plans carry — even though it never constrains a node once
    the passes begin.
    """
    dates = [d for n in nodes for d in (n.not_earlier_than, n.target) if d]
    return min(dates) if dates else None


def _topological(index: dict[tuple[str, int], Node],
                 edges: list[Any]) -> list[tuple[str, int]] | None:
    """Kahn's algorithm. Iterative: a deep plan must not blow the stack."""
    incoming: dict[tuple[str, int], int] = {k: 0 for k in index}
    after: dict[tuple[str, int], list[tuple[str, int]]] = defaultdict(list)
    for edge in edges:
        pred = (edge.predecessor_type, int(edge.predecessor_id))
        succ = (edge.successor_type, int(edge.successor_id))
        if pred not in index or succ not in index:
            continue
        after[pred].append(succ)
        incoming[succ] += 1

    queue = deque(sorted(k for k, n in incoming.items() if n == 0))
    order: list[tuple[str, int]] = []
    while queue:
        key = queue.popleft()
        order.append(key)
        for nxt in after[key]:
            incoming[nxt] -= 1
            if incoming[nxt] == 0:
                queue.append(nxt)
    return order if len(order) == len(index) else None


def _edges_into(index: dict[tuple[str, int], Node],
                edges: list[Any]) -> dict[tuple[str, int], list[Any]]:
    into: dict[tuple[str, int], list[Any]] = defaultdict(list)
    for edge in edges:
        pred = (edge.predecessor_type, int(edge.predecessor_id))
        succ = (edge.successor_type, int(edge.successor_id))
        if pred in index and succ in index:
            into[succ].append(edge)
    return into


def _edges_out(index: dict[tuple[str, int], Node],
               edges: list[Any]) -> dict[tuple[str, int], list[Any]]:
    out: dict[tuple[str, int], list[Any]] = defaultdict(list)
    for edge in edges:
        pred = (edge.predecessor_type, int(edge.predecessor_id))
        succ = (edge.successor_type, int(edge.successor_id))
        if pred in index and succ in index:
            out[pred].append(edge)
    return out


def _forward(index: dict[tuple[str, int], Node], edges: list[Any],
             order: list[tuple[str, int]], anchor: date
             ) -> tuple[dict[tuple[str, int], date], dict[tuple[str, int], date]]:
    """Earliest start and finish, in topological order.

    The four dependency kinds are the whole of the arithmetic:

      FS  the successor starts the day after the predecessor finishes;
      SS  they may start together;
      FF  they may finish together;
      SF  the successor finishes after the predecessor starts.

    `lag` shifts each by a number of days, positive or negative.
    """
    into = _edges_into(index, edges)
    early_start: dict[tuple[str, int], date] = {}
    early_finish: dict[tuple[str, int], date] = {}

    for key in order:
        node = index[key]
        starts = [node.not_earlier_than or anchor]
        finishes: list[date] = []
        for edge in into[key]:
            pred = (edge.predecessor_type, int(edge.predecessor_id))
            lag = int(edge.lag_days or 0)
            kind = edge.dependency_type
            if kind == DEP_FINISH_TO_START:
                starts.append(early_finish[pred] + timedelta(days=1 + lag))
            elif kind == DEP_START_TO_START:
                starts.append(early_start[pred] + timedelta(days=lag))
            elif kind == DEP_FINISH_TO_FINISH:
                finishes.append(early_finish[pred] + timedelta(days=lag))
            elif kind == DEP_START_TO_FINISH:
                finishes.append(early_start[pred] + timedelta(days=lag))

        start = max(starts)
        length = max(node.duration - 1, 0)
        if finishes:
            # A finish constraint can push the whole node later; it can never
            # pull it earlier than its own predecessors allow.
            forced = max(finishes)
            start = max(start, forced - timedelta(days=length))
        early_start[key] = start
        early_finish[key] = start + timedelta(days=length)
    return early_start, early_finish


def _backward(index: dict[tuple[str, int], Node], edges: list[Any],
              order: list[tuple[str, int]], finish: date,
              early_start: dict[tuple[str, int], date],
              early_finish: dict[tuple[str, int], date]
              ) -> tuple[dict[tuple[str, int], date], dict[tuple[str, int], date]]:
    """Latest start and finish, walking the order backwards."""
    out_edges = _edges_out(index, edges)
    late_finish: dict[tuple[str, int], date] = {}
    late_start: dict[tuple[str, int], date] = {}

    for key in reversed(order):
        node = index[key]
        limits = [finish]
        for edge in out_edges[key]:
            succ = (edge.successor_type, int(edge.successor_id))
            lag = int(edge.lag_days or 0)
            kind = edge.dependency_type
            if kind == DEP_FINISH_TO_START:
                limits.append(late_start[succ] - timedelta(days=1 + lag))
            elif kind == DEP_START_TO_START:
                limits.append(late_start[succ] - timedelta(days=lag)
                              + timedelta(days=max(node.duration - 1, 0)))
            elif kind == DEP_FINISH_TO_FINISH:
                limits.append(late_finish[succ] - timedelta(days=lag))
            elif kind == DEP_START_TO_FINISH:
                # succ.finish >= pred.start + lag, so pred may start no later
                # than succ's late finish minus the lag.
                limits.append(late_finish[succ] - timedelta(days=lag)
                              + timedelta(days=max(node.duration - 1, 0)))
        late_finish[key] = min(limits)
        late_start[key] = late_finish[key] - timedelta(
            days=max(node.duration - 1, 0))
    _ = early_start, early_finish
    return late_start, late_finish


# ========================================================= downstream impact


@dataclass
class Slip:
    """What moves if one thing is late, and by how much."""

    code: str
    days: int
    moved: list[dict[str, Any]] = field(default_factory=list)
    finish_moves_by: int = 0
    project_finish_before: date | None = None
    project_finish_after: date | None = None
    absorbed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code, "days": self.days, "moved": self.moved,
            "finish_moves_by": self.finish_moves_by,
            "absorbed": self.absorbed,
            "project_finish_before": (self.project_finish_before.isoformat()
                                      if self.project_finish_before else None),
            "project_finish_after": (self.project_finish_after.isoformat()
                                     if self.project_finish_after else None),
        }


def slip(plan: control.Plan, code: str, days: int, *,
         project_start: date | None = None) -> Slip | None:
    """"If this slips by two days, what gets affected?"

    Answered by recomputing rather than by reasoning about float, because
    float is only correct until something else moves too. The plan is copied,
    the one task is lengthened, and the two schedules are compared: what comes
    back is measured, not inferred.

    Returns None when the schedule could not be computed in the first place —
    the caller then has `compute().cannot_because` to explain why, and must
    not present a slip analysis built on nothing.
    """
    base = compute(plan, project_start=project_start)
    if not base.computed or base.by_code(code) is None:
        return None

    stretched = _stretch(plan, code, days)
    after = compute(stretched, project_start=project_start)
    if not after.computed:  # pragma: no cover - lengthening cannot break it
        return None

    moved: list[dict[str, Any]] = []
    for row in after.placed:
        was = base.by_code(row.node.code)
        if was is None:
            continue
        shift = (row.early_finish - was.early_finish).days
        if shift and row.node.code != code:
            moved.append({
                "code": row.node.code, "name": row.node.name,
                "kind": row.node.kind, "days": shift,
                "was": was.early_finish.isoformat(),
                "now": row.early_finish.isoformat(),
                "float_before": was.total_float})
    moved.sort(key=lambda m: (-m["days"], m["code"]))

    finish_shift = ((after.project_finish - base.project_finish).days
                    if base.project_finish and after.project_finish else 0)
    return Slip(
        code=code, days=days, moved=moved, finish_moves_by=finish_shift,
        project_finish_before=base.project_finish,
        project_finish_after=after.project_finish,
        absorbed=finish_shift == 0)


def _stretch(plan: control.Plan, code: str, days: int) -> control.Plan:
    """A copy of the plan with one task's due date pushed out.

    A copy, because the caller's plan is the live one and a what-if that
    edited it would be a what-if that happened.
    """
    import copy

    clone = copy.deepcopy(plan)
    for task in clone.tasks:
        if task.code != code:
            continue
        if task.due_date:
            task.due_date = task.due_date + timedelta(days=days)
        elif task.effort_days:
            task.effort_days = int(task.effort_days) + days
    return clone


__all__ = [
    "SCHEDULE_VERSION", "BASIS_CALENDAR",
    "Node", "Scheduled", "Schedule", "compute",
    "Slip", "slip",
]
