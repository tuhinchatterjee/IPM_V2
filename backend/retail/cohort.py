"""The cohort object every handoff carries, and the rules it is read under.

The defect this exists for
--------------------------
"Export these customers to Borrower 360" used to mean "navigate there with a
filter and hope". Four modules each knew how to select *Alpha Card, 20-29 DPD,
August* and they agreed right up until the book moved underneath them — a
rebuild, a corrected row, a new month — at which point they resolved to
different sets and nothing in the product could see it. The reader was shown
one population in the drawer, a slightly different one in Borrower 360, and a
third in the workbook they sent to a committee.

Putting the identifiers in the link is the obvious fix and is worse: eleven
thousand customer identifiers do not fit in a URL, and the ones that do end up
in browser history, proxy logs and referrer headers.

So the identifiers are written once and the link carries an opaque id.

What a snapshot promises
------------------------
* **These exact customers and facilities**, as a stored list, not a predicate.
* **Measured on this bundle**, with the dataset hashes it read. Joining a
  snapshot to figures from another bundle is refused, not rounded away.
* **Under these metric definitions**, cited by id from
  `backend/retail/metrics_contract.py`.
* **Up to this step.** `visited_steps` is the cap: an export taken at S1 may
  not contain the pocket S4 would have found or the actions S5 would have
  proposed, because the reader has not seen them.
* **For this purpose, by this person.** Authorisation is rechecked at read,
  share, reopen and export — four moments, because access can be withdrawn
  between any two of them. Knowing an id is not permission.

Immutability is the contract, not an optimisation. There is no update path
here at all. Narrowing writes a child; refreshing against a newer book writes a
new version; switching from flagged facilities to all of a customer's
facilities writes a new snapshot with its own counts. That is what makes a
figure somebody saved in August still the figure they saved in August.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from backend.models.platform import CohortSnapshot
from backend.retail import metrics_contract as mc

logger = logging.getLogger(__name__)

#: Bumped when the hash input or the field meanings change.
VERSION = "retail-cohort-snapshot-1.0.0"

ALL_MATCHED = "all_matched"
SELECTED_SUBSET = "selected_subset"
SELECTION_MODES = (ALL_MATCHED, SELECTED_SUBSET)

FLAGGED_ONLY = "flagged_only"
ALL_FACILITIES = "all_authorised_facilities"
FACILITY_MODES = (FLAGGED_ONLY, ALL_FACILITIES)

#: The six steps of a story. An export is capped at the furthest one visited.
STEPS = ("S0", "S1", "S2", "S3", "S4", "S5")


class NotPermitted(PermissionError):
    """The reader may not have this cohort. Said plainly, never as an empty list.

    An empty result and a refusal look identical to a reader and mean opposite
    things: one says the pocket is clean, the other says they were not allowed
    to see it. They are never collapsed into each other here.
    """


class BundleMismatch(RuntimeError):
    """A snapshot from one build of the book, joined to another.

    Raised rather than reconciled. The two sets of figures are not two
    measurements of the same thing that happen to differ; they are measurements
    of different books, and averaging them produces a number that was never
    true.
    """


# ---------------------------------------------------------------------------
# The predicate
# ---------------------------------------------------------------------------
#
# Stored as a small tree rather than a SQL string: it has to be rendered as a
# breadcrumb, compared between a root and a current scope, and shown in an
# export, and none of those survive a dialect-specific fragment. It is evidence
# of HOW the set was chosen. It is never re-executed to rebuild the set —
# re-execution is the bug this whole module exists to remove.


@dataclass(frozen=True)
class Predicate:
    """One clause of a scope, in a form a reader can be shown."""

    field: str
    op: str
    value: Any
    label: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"field": self.field, "op": self.op, "value": self.value,
                "label": self.label or f"{self.field} {self.op} {self.value}"}


def predicate_ast(*clauses: Predicate, combine: str = "and",
                  describes: str = "") -> dict[str, Any]:
    """The stored form of a scope."""
    if combine not in ("and", "or"):
        raise ValueError("a scope combines its clauses with 'and' or 'or'")
    return {
        "combine": combine,
        "describes": describes,
        "clauses": [c.to_dict() for c in clauses],
    }


def describe(ast: dict[str, Any]) -> str:
    """The breadcrumb text. Empty scope reads as 'everything eligible'."""
    clauses = (ast or {}).get("clauses") or []
    if not clauses:
        return (ast or {}).get("describes") or "everything eligible"
    joiner = f" {(ast.get('combine') or 'and')} "
    return joiner.join(c.get("label") or
                       f"{c.get('field')} {c.get('op')} {c.get('value')}"
                       for c in clauses)


# ---------------------------------------------------------------------------
# Identity and integrity
# ---------------------------------------------------------------------------


def new_id(case_id: str = "", step_id: str = "", as_of: str = "") -> str:
    """An opaque, readable id. Readable because a support conversation about a
    snapshot should not require a database to work out which story it came from;
    opaque because nothing in it is a customer identifier."""
    stem = "-".join(p for p in (case_id, step_id, as_of.replace("-", ""))
                    if p) or "CPRA"
    return f"CPRA-{stem}-{uuid.uuid4().hex[:8].upper()}" if stem == "CPRA" \
        else f"CPRA-{stem}-{uuid.uuid4().hex[:8].upper()}"


def content_hash(*, customer_ids: list[str], facility_ids: list[str],
                 as_of: str, bundle_id: str,
                 root_predicate: dict[str, Any],
                 predicate: dict[str, Any],
                 selection_mode: str, facility_mode: str) -> str:
    """A stable fingerprint of the cohort.

    Sorted identifiers, because the order a query happened to return them in is
    not part of what the cohort is. Both predicates and both modes, because
    *these eleven customers chosen from all matched* and *these eleven
    customers who were all that matched* are different claims about the same
    eleven people.
    """
    payload = {
        "v": VERSION,
        "customers": sorted({str(c) for c in customer_ids}),
        "facilities": sorted({str(f) for f in facility_ids}),
        "as_of": as_of,
        "bundle": bundle_id,
        "root": root_predicate or {},
        "predicate": predicate or {},
        "selection_mode": selection_mode,
        "facility_mode": facility_mode,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                     default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Creating
# ---------------------------------------------------------------------------


@dataclass
class Draft:
    """A cohort about to be frozen."""

    case_id: str = ""
    occurrence_id: str = ""
    thread_id: str = ""
    step_id: str = ""
    source_as_of: str = ""
    source_bundle_id: str = ""
    dataset_hashes: dict[str, str] = field(default_factory=dict)
    versions: dict[str, str] = field(default_factory=dict)
    metric_definition_ids: list[str] = field(default_factory=list)
    root_predicate: dict[str, Any] = field(default_factory=dict)
    predicate: dict[str, Any] = field(default_factory=dict)
    customer_ids: list[str] = field(default_factory=list)
    facility_ids: list[str] = field(default_factory=list)
    selection_mode: str = ALL_MATCHED
    facility_mode: str = FLAGGED_ONLY
    restricted_count: int = 0
    parent_snapshot_id: str = ""
    visited_steps: list[str] = field(default_factory=list)
    owner_user_id: int | None = None
    team_id: int | None = None
    purpose: str = ""
    permitted_fields: list[str] = field(default_factory=list)
    evidence_refs: list[dict[str, Any]] = field(default_factory=list)
    retain_until: datetime | None = None
    totals: dict[str, Any] = field(default_factory=dict)


def create(session: Any, draft: Draft) -> CohortSnapshot:
    """Freeze a cohort. Validates first, because a snapshot cannot be corrected.

    The validations are the ones that produce a wrong answer silently rather
    than an error: an undeclared metric (a figure nobody can look up), an
    unknown selection or facility mode (a count that means two things), a step
    outside S0-S5, and an empty as-of (a cohort that cannot be reconciled
    against any month).
    """
    if draft.selection_mode not in SELECTION_MODES:
        raise ValueError(
            f"selection_mode must be one of {SELECTION_MODES}; "
            f"{draft.selection_mode!r} would leave a reader unable to tell a "
            f"ticked subset from everything that matched.")
    if draft.facility_mode not in FACILITY_MODES:
        raise ValueError(
            f"facility_mode must be one of {FACILITY_MODES}; "
            f"{draft.facility_mode!r} would leave the financial baseline "
            f"ambiguous between flagged facilities and all of them.")
    if draft.step_id and draft.step_id not in STEPS:
        raise ValueError(f"step_id must be one of {STEPS}, not {draft.step_id!r}")
    for bad in [m for m in draft.metric_definition_ids if m not in mc.BY_ID]:
        raise KeyError(
            f"{bad!r} is not a defined retail metric. A cohort may not cite a "
            f"measure that has no published definition.")
    if not draft.source_as_of:
        raise ValueError(
            "a cohort must record the date it was measured at, or nothing "
            "downstream can prove it did not drift")

    customers = _unique(draft.customer_ids)
    facilities = _unique(draft.facility_ids)

    digest = content_hash(
        customer_ids=customers, facility_ids=facilities,
        as_of=draft.source_as_of, bundle_id=draft.source_bundle_id,
        root_predicate=draft.root_predicate, predicate=draft.predicate,
        selection_mode=draft.selection_mode, facility_mode=draft.facility_mode)

    row = CohortSnapshot(
        snapshot_id=new_id(draft.case_id, draft.step_id, draft.source_as_of),
        case_id=draft.case_id,
        occurrence_id=draft.occurrence_id,
        thread_id=draft.thread_id,
        step_id=draft.step_id,
        source_as_of=draft.source_as_of,
        source_bundle_id=draft.source_bundle_id,
        dataset_hashes=dict(draft.dataset_hashes),
        versions=dict(draft.versions),
        metric_definition_ids=list(draft.metric_definition_ids),
        root_predicate=dict(draft.root_predicate),
        predicate=dict(draft.predicate),
        customer_ids=customers,
        facility_ids=facilities,
        customer_count=len(customers),
        facility_count=len(facilities),
        selection_mode=draft.selection_mode,
        facility_mode=draft.facility_mode,
        restricted_count=int(draft.restricted_count),
        content_hash=digest,
        parent_snapshot_id=draft.parent_snapshot_id,
        visited_steps=_ordered_steps(draft.visited_steps, draft.step_id),
        owner_user_id=draft.owner_user_id,
        team_id=draft.team_id,
        purpose=draft.purpose,
        permitted_fields=list(draft.permitted_fields),
        evidence_refs=list(draft.evidence_refs),
        retain_until=draft.retain_until,
        totals=dict(draft.totals),
    )
    session.add(row)
    session.flush()
    logger.info("cohort snapshot %s: %d customers, %d facilities at %s",
                row.snapshot_id, row.customer_count, row.facility_count,
                row.source_as_of)
    return row


def narrow(session: Any, parent: CohortSnapshot, *, step_id: str,
           customer_ids: list[str], facility_ids: list[str],
           predicate: dict[str, Any],
           totals: dict[str, Any] | None = None,
           metric_definition_ids: list[str] | None = None,
           owner_user_id: int | None = None) -> CohortSnapshot:
    """A child cohort, checked to be a subset of its parent.

    The check is the point. A step that claims to narrow but introduces a
    customer the previous step never contained has not narrowed — it has
    re-queried, and the reader following a breadcrumb would be looking at a
    population they were never shown.
    """
    escaped = set(map(str, customer_ids)) - set(map(str, parent.customer_ids))
    if escaped:
        raise ValueError(
            f"{len(escaped)} customer(s) in this step were not in the step it "
            f"claims to narrow ({parent.snapshot_id}). A narrowing step may "
            f"only remove; introducing a customer means the cohort was "
            f"re-queried rather than narrowed.")
    return create(session, Draft(
        case_id=parent.case_id,
        occurrence_id=parent.occurrence_id,
        thread_id=parent.thread_id,
        step_id=step_id,
        source_as_of=parent.source_as_of,
        source_bundle_id=parent.source_bundle_id,
        dataset_hashes=dict(parent.dataset_hashes),
        versions=dict(parent.versions),
        metric_definition_ids=list(
            metric_definition_ids
            if metric_definition_ids is not None
            else parent.metric_definition_ids),
        root_predicate=dict(parent.root_predicate or parent.predicate),
        predicate=predicate,
        customer_ids=list(customer_ids),
        facility_ids=list(facility_ids),
        selection_mode=parent.selection_mode,
        facility_mode=parent.facility_mode,
        parent_snapshot_id=parent.snapshot_id,
        visited_steps=list(parent.visited_steps) + [step_id],
        owner_user_id=owner_user_id if owner_user_id is not None
        else parent.owner_user_id,
        team_id=parent.team_id,
        purpose=parent.purpose,
        permitted_fields=list(parent.permitted_fields),
        evidence_refs=list(parent.evidence_refs),
        totals=dict(totals or {}),
    ))


def select_subset(session: Any, parent: CohortSnapshot, *,
                  customer_ids: list[str], facility_ids: list[str],
                  facility_mode: str = "",
                  owner_user_id: int | None = None,
                  totals: dict[str, Any] | None = None) -> CohortSnapshot:
    """What the reader actually ticked, as its own cohort.

    Also the route for switching between flagged facilities and all of a
    selected customer's facilities: both change the financial baseline, so both
    produce a new snapshot with recomputed counts rather than a flag on the old
    one.
    """
    escaped = set(map(str, customer_ids)) - set(map(str, parent.customer_ids))
    if escaped:
        raise ValueError(
            f"{len(escaped)} selected customer(s) are not in "
            f"{parent.snapshot_id}. A selection is a subset of what was shown.")
    mode = facility_mode or parent.facility_mode
    if mode not in FACILITY_MODES:
        raise ValueError(f"facility_mode must be one of {FACILITY_MODES}")
    return create(session, Draft(
        case_id=parent.case_id,
        occurrence_id=parent.occurrence_id,
        thread_id=parent.thread_id,
        step_id=parent.step_id,
        source_as_of=parent.source_as_of,
        source_bundle_id=parent.source_bundle_id,
        dataset_hashes=dict(parent.dataset_hashes),
        versions=dict(parent.versions),
        metric_definition_ids=list(parent.metric_definition_ids),
        root_predicate=dict(parent.root_predicate or parent.predicate),
        predicate=dict(parent.predicate),
        customer_ids=list(customer_ids),
        facility_ids=list(facility_ids),
        selection_mode=SELECTED_SUBSET,
        facility_mode=mode,
        parent_snapshot_id=parent.snapshot_id,
        visited_steps=list(parent.visited_steps),
        owner_user_id=owner_user_id if owner_user_id is not None
        else parent.owner_user_id,
        team_id=parent.team_id,
        purpose=parent.purpose,
        permitted_fields=list(parent.permitted_fields),
        evidence_refs=list(parent.evidence_refs),
        totals=dict(totals or {}),
    ))


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def load(session: Any, snapshot_id: str) -> CohortSnapshot | None:
    return session.execute(
        select(CohortSnapshot)
        .where(CohortSnapshot.snapshot_id == snapshot_id)
    ).scalar_one_or_none()


def read(session: Any, snapshot_id: str, *, user_id: int | None,
         role: str = "", team_id: int | None = None,
         action: str = "read") -> CohortSnapshot:
    """Load a cohort and recheck who is asking.

    `action` is recorded rather than decorative: read, share, reopen and export
    are four separate authorisations of the same object, and a product that
    checks once at creation has checked at the one moment when nothing could
    have changed yet.
    """
    row = load(session, snapshot_id)
    if row is None:
        raise NotPermitted(
            f"No cohort {snapshot_id!r} is readable here. It may not exist, or "
            f"it may not be yours — the two are deliberately indistinguishable "
            f"from outside, because saying which would confirm that somebody "
            f"else's cohort exists.")
    if not permitted(row, user_id=user_id, role=role, team_id=team_id):
        logger.warning("cohort %s refused to user %s for %s",
                       snapshot_id, user_id, action)
        raise NotPermitted(
            f"No cohort {snapshot_id!r} is readable here. It may not exist, or "
            f"it may not be yours.")
    return row


def permitted(row: CohortSnapshot, *, user_id: int | None,
              role: str = "", team_id: int | None = None) -> bool:
    """Whether this reader may have this cohort.

    Deliberately narrow. An administrator may read anything; the owner may read
    their own; a team member may read a cohort scoped to their team. Everything
    else is refused, including a cohort with no owner at all — an unowned
    customer list is a bug, not a public one.
    """
    if (role or "").upper() in ("ADMIN", "OWNER"):
        return True
    if row.owner_user_id is None:
        return False
    if user_id is not None and row.owner_user_id == user_id:
        return True
    return bool(row.team_id and team_id and row.team_id == team_id)


def require_bundle(row: CohortSnapshot, bundle_id: str) -> None:
    """Refuse to join a cohort to a different build of the book."""
    if row.source_bundle_id and bundle_id and row.source_bundle_id != bundle_id:
        raise BundleMismatch(
            f"Cohort {row.snapshot_id} was measured on bundle "
            f"{row.source_bundle_id} and the current book is {bundle_id}. "
            f"These are different measurements, not a discrepancy to "
            f"reconcile. Refresh the investigation to create a new version "
            f"against the current bundle, which leaves the saved one intact.")


def allows_step(row: CohortSnapshot, step_id: str) -> bool:
    """Whether a step's conclusions may appear in this cohort's export.

    The cap that stops an S1 workbook from containing S5's policy actions. A
    reader who exported at S1 has not seen the pocket or the plan, and a file
    that shows them conclusions they never reached is a file that attributes
    reasoning to them.
    """
    return step_id in (row.visited_steps or [])


def view(row: CohortSnapshot, *, include_ids: bool = False) -> dict[str, Any]:
    """The cohort as a surface shows it.

    Identifiers are off by default. A banner needs counts, a date and a
    provenance line; it does not need eleven thousand customer numbers, and a
    payload that carries them by habit is a payload that leaks them by habit.
    """
    out: dict[str, Any] = {
        "snapshot_id": row.snapshot_id,
        "case_id": row.case_id,
        "occurrence_id": row.occurrence_id,
        "thread_id": row.thread_id,
        "step_id": row.step_id,
        "source_as_of": row.source_as_of,
        "source_bundle_id": row.source_bundle_id,
        "dataset_hashes": dict(row.dataset_hashes or {}),
        "versions": dict(row.versions or {}),
        "metric_definitions": [mc.definition(m)
                               for m in (row.metric_definition_ids or [])
                               if m in mc.BY_ID],
        "root_scope": describe(row.root_predicate or {}),
        "scope": describe(row.predicate or {}),
        "root_predicate": dict(row.root_predicate or {}),
        "predicate": dict(row.predicate or {}),
        "customer_count": row.customer_count,
        "facility_count": row.facility_count,
        "selection_mode": row.selection_mode,
        "facility_mode": row.facility_mode,
        "restricted_count": row.restricted_count,
        "content_hash": row.content_hash,
        "parent_snapshot_id": row.parent_snapshot_id,
        "visited_steps": list(row.visited_steps or []),
        "purpose": row.purpose,
        "totals": dict(row.totals or {}),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "contract_version": VERSION,
    }
    if include_ids:
        out["customer_ids"] = list(row.customer_ids or [])
        out["facility_ids"] = list(row.facility_ids or [])
    return out


def reconcile(row: CohortSnapshot, *, customer_ids: list[str],
              facility_ids: list[str],
              totals: dict[str, float] | None = None,
              tolerance: float = 0.01) -> dict[str, Any]:
    """Prove that what a downstream module is about to show is the same cohort.

    Used as a gate before What-If simulates and before an export is written.
    It returns the differences rather than a bare boolean, because "these do
    not match" is not actionable and "three customers are missing and the ECL
    is short by 412 SAR" is.
    """
    want_c = {str(c) for c in (row.customer_ids or [])}
    want_f = {str(f) for f in (row.facility_ids or [])}
    got_c = {str(c) for c in customer_ids}
    got_f = {str(f) for f in facility_ids}

    differences: list[dict[str, Any]] = []
    for label, want, got in (("customers", want_c, got_c),
                             ("facilities", want_f, got_f)):
        missing, extra = sorted(want - got), sorted(got - want)
        if missing or extra:
            differences.append({
                "what": label,
                "missing": len(missing), "extra": len(extra),
                "missing_sample": missing[:10], "extra_sample": extra[:10],
            })

    for key, expected in (row.totals or {}).items():
        if totals is None or key not in totals:
            continue
        try:
            gap = abs(float(totals[key]) - float(expected))
        except (TypeError, ValueError):
            continue
        if gap > tolerance:
            differences.append({"what": key, "expected": float(expected),
                                "got": float(totals[key]),
                                "difference": round(gap, 6)})

    return {
        "snapshot_id": row.snapshot_id,
        "reconciled": not differences,
        "differences": differences,
        "expected_customers": len(want_c),
        "expected_facilities": len(want_f),
        "tolerance": tolerance,
    }


# ---------------------------------------------------------------------------


def _unique(values: Any) -> list[str]:
    """Distinct, order-preserving, string. A cohort of a customer twice is a
    cohort that double-counts its ECL."""
    return list(dict.fromkeys(str(v) for v in (values or []) if str(v)))


def _ordered_steps(visited: Any, step_id: str) -> list[str]:
    seen = list(dict.fromkeys(list(visited or []) + ([step_id] if step_id else [])))
    return [s for s in STEPS if s in seen]


def now() -> datetime:
    return datetime.now(UTC)
