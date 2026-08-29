"""
The teaching case library: storing cases, and moving them through review.

§4-§6. The schema in `backend/teaching/schema.py` says what a case is and the
status module says what it is allowed to be; this is where those two meet a
database, and where the two decisions with consequences are made:

**A new version, never an overwrite.** `save` writes version *n+1* rather than
editing version *n*. An approved case whose content can change underneath its
approval is an approval that means nothing, and retrieval that happened last
week has to stay explicable this week.

**Nothing reaches APPROVED without a person.** `approve` requires a named
reviewer and a note. A validator passing puts a case in AUTO_VALIDATED, which
is a different word on purpose (§5: do not label LLM-generated cases human
reviewed).

Every transition writes an event. A review workflow with no audit trail cannot
answer the only question ever asked of it afterwards — who approved this, when,
and what did they say.

Retrieval reads one query
-------------------------
`retrievable` is the only way a case reaches a live prompt, and it is
deliberately the narrowest thing in the module: the latest version, APPROVED
(or SYSTEM_VALIDATED where a caller has governed that on), not stale, not
client data. Anything wanting to widen it has to widen it here, in one place,
in front of a reviewer.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.models.platform import TeachingCase as Row
from backend.models.platform import TeachingCaseEvent as Event
from backend.teaching import families as fam
from backend.teaching import schema as sc
from backend.teaching import status as st

logger = logging.getLogger(__name__)


class LibraryError(RuntimeError):
    """A refusal the caller has to see. Never raised for a validation problem —
    an invalid case is stored as a DRAFT with its problems recorded, because a
    case somebody is halfway through writing is not an error."""


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value or "")


def _at(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


# --------------------------------------------------------------- reading
def to_case(row: Row) -> sc.TeachingCase:
    """The stored row, back as the governed object.

    The body is authoritative for content and the columns are authoritative
    for governance: a status change writes a column, and reconstructing the
    case from the body alone would hand back the status the case had when it
    was written rather than the one it has now.
    """
    case = sc.TeachingCase.from_dict(row.body or {})
    case.case_id = row.case_id
    case.case_version = row.case_version
    case.review_status = row.review_status
    case.reviewer = row.reviewer or ""
    case.approved_at = _iso(row.approved_at)
    case.last_validated_at = _iso(row.last_validated_at)
    case.fingerprint = row.fingerprint or case.fingerprint
    case.cluster_id = row.cluster_id or case.cluster_id
    return case


def latest(session: Session, case_id: str) -> Row | None:
    """The newest version of a case, whatever status it is in."""
    return session.execute(
        select(Row).where(Row.case_id == str(case_id or ""))
        .order_by(Row.case_version.desc()).limit(1)
    ).scalars().first()


def version(session: Session, case_id: str, case_version: int) -> Row | None:
    return session.execute(
        select(Row).where(Row.case_id == str(case_id or ""),
                          Row.case_version == int(case_version))
    ).scalars().first()


def history(session: Session, case_id: str) -> list[Event]:
    return list(session.execute(
        select(Event).where(Event.case_id == str(case_id or ""))
        .order_by(Event.at.asc(), Event.id.asc())).scalars())


# ---------------------------------------------------------------- writing
def _event(session: Session, *, case_id: str, case_version: int,
           from_status: str, to_status: str, actor: str,
           actor_id: int | None = None, note: str = "",
           detail: Mapping[str, Any] | None = None) -> Event:
    row = Event(case_id=case_id, case_version=case_version,
                from_status=from_status, to_status=to_status,
                actor=actor or "", actor_id=actor_id, note=note or "",
                detail=dict(detail or {}), at=_now())
    session.add(row)
    return row


def _write(row: Row, case: sc.TeachingCase) -> None:
    """Copy the case onto the row. One place, so a new field cannot be stored
    on some paths and not others."""
    row.title = case.title[:240]
    row.family_id = case.family_id
    row.subfamily = case.subfamily[:64]
    row.description = case.description
    row.language = case.language[:8]
    row.locale = case.locale[:16]
    row.portfolio_scope = case.portfolio_scope
    row.industry_or_product_scope = case.industry_or_product_scope[:96]
    row.difficulty = case.difficulty
    row.risk_level = case.risk_level
    row.question = case.question or (case.conversation_turns[0].user_message
                                     if case.conversation_turns else "")
    row.turn_count = case.turn_count()
    row.expected_capability = case.expected_capability[:48]
    row.expected_conversation_action = case.expected_conversation_action[:48]
    row.expected_outcome = case.expected_outcome
    row.expected_officer_level = int(case.expected_officer_level or 0)
    row.expected_model_route = case.expected_model_route[:24]
    row.expected_effort = case.expected_effort[:16]
    row.grain = case.grain[:48]
    row.concepts = list(case.concepts)
    row.required_datasets = list(case.required_datasets)
    row.operations = list(case.operations)
    row.tags = list(case.tags)
    row.body = case.to_dict()
    row.authoring_method = case.authoring_method
    row.data_sensitivity = case.data_sensitivity
    row.source_provenance = case.source_provenance
    row.ontology_version = case.ontology_version[:24]
    row.method_version = case.method_version[:24]
    row.relationship_version = case.relationship_version[:24]
    row.dataset_contract_version = case.dataset_contract_version[:24]
    row.planner_schema_version = case.planner_schema_version[:24]
    row.prompt_schema_version = case.prompt_schema_version[:24]
    row.model_family = case.model_family[:48]
    row.prompt_compatibility = case.prompt_compatibility[:48]
    row.family_version = case.family_version[:24]
    row.fingerprint = case.fingerprint
    row.cluster_id = case.cluster_id[:64]
    row.cost_budget = float(case.cost_budget or 0.0)
    row.latency_budget = float(case.latency_budget or 0.0)
    row.notes = case.notes


def save(session: Session, case: sc.TeachingCase, *, actor: str = "",
         actor_id: int | None = None) -> Row:
    """Store a case as a new version, in the status its validators allow.

    Never APPROVED — approval is `approve`, and it needs a person. A case that
    fails validation is stored as a DRAFT with the problems on its event, so
    the author can see what to fix rather than losing the work to an
    exception.
    """
    if not (case.case_id or "").strip():
        raise LibraryError("a case needs a case_id")

    case.fingerprint = sc.fingerprint(case)
    problems = sc.validate(case)
    resolved = sc.resolve_status(case)

    previous = latest(session, case.case_id)
    next_version = (previous.case_version + 1) if previous else 1
    case.case_version = next_version

    row = Row(case_id=case.case_id, case_version=next_version,
              review_status=resolved, created_by=actor_id,
              last_validated_at=_now() if not problems else None)
    _write(row, case)
    session.add(row)
    session.flush()

    _event(session, case_id=case.case_id, case_version=next_version,
           from_status=previous.review_status if previous else "",
           to_status=resolved, actor=actor or "system", actor_id=actor_id,
           note="authored" if next_version == 1 else "new version",
           detail={"problems": [str(p) for p in problems],
                   "fatal": sum(1 for p in problems if p.fatal)})
    return row


def _transition(session: Session, row: Row, target: str, *, actor: str,
                actor_id: int | None, note: str,
                detail: Mapping[str, Any] | None = None) -> Row:
    allowed = st.may_transition(row.review_status, target)
    if not allowed:
        raise LibraryError(allowed.reason)
    was = row.review_status
    row.review_status = target
    session.flush()
    _event(session, case_id=row.case_id, case_version=row.case_version,
           from_status=was, to_status=target, actor=actor, actor_id=actor_id,
           note=note, detail=detail)
    return row


def approve(session: Session, case_id: str, *, reviewer: str,
            note: str, reviewer_id: int | None = None,
            reviewer_is_human: bool = True,
            case_version: int | None = None) -> Row:
    """A named person signs for a case. §5's one rule, enforced.

    The note is required. An approval with no reasoning is a click, and every
    case retrieved on the strength of it inherits the click.
    """
    row = (version(session, case_id, case_version) if case_version
           else latest(session, case_id))
    if row is None:
        raise LibraryError(f"no case {case_id!r}")
    if not (note or "").strip():
        raise LibraryError("an approval needs a reason")

    permitted = st.may_approve(authoring_method=row.authoring_method,
                               reviewer=reviewer,
                               reviewer_is_human=reviewer_is_human)
    if not permitted:
        raise LibraryError(permitted.reason)
    if row.data_sensitivity == st.CLIENT:
        raise LibraryError("a case carrying client data cannot be approved "
                           "as a teaching case (§47)")
    family = fam.get(row.family_id)
    if family is not None and not family.available:
        raise LibraryError(f"{family.id} waits on {family.gated_on}; cases in "
                           "it cannot be approved yet")

    row.reviewer = reviewer[:120]
    row.reviewed_by = reviewer_id
    row.approved_at = _now()
    return _transition(session, row, st.APPROVED, actor=reviewer,
                       actor_id=reviewer_id, note=note)


def reject(session: Session, case_id: str, *, reviewer: str, note: str,
           reviewer_id: int | None = None) -> Row:
    row = latest(session, case_id)
    if row is None:
        raise LibraryError(f"no case {case_id!r}")
    if not (note or "").strip():
        raise LibraryError("a rejection needs a reason")
    row.reviewer = reviewer[:120]
    row.reviewed_by = reviewer_id
    return _transition(session, row, st.REJECTED, actor=reviewer,
                       actor_id=reviewer_id, note=note)


def retire(session: Session, case_id: str, *, actor: str, note: str = "",
           actor_id: int | None = None) -> Row:
    row = latest(session, case_id)
    if row is None:
        raise LibraryError(f"no case {case_id!r}")
    return _transition(session, row, st.RETIRED, actor=actor,
                       actor_id=actor_id, note=note)


def send_to_review(session: Session, case_id: str, *, actor: str,
                   note: str = "", actor_id: int | None = None) -> Row:
    row = latest(session, case_id)
    if row is None:
        raise LibraryError(f"no case {case_id!r}")
    return _transition(session, row, st.SME_REVIEW_REQUIRED, actor=actor,
                       actor_id=actor_id, note=note)


def system_validate(session: Session, case_id: str, *, source: str,
                    provenance: str, deterministic_validation_passed: bool,
                    actor: str = "system", note: str = "",
                    model_generated_gold: bool = False,
                    from_holdout: bool = False) -> Row:
    """§6's controlled status, with §6's five requirements checked first."""
    row = latest(session, case_id)
    if row is None:
        raise LibraryError(f"no case {case_id!r}")
    permitted = st.may_system_validate(
        source=source, provenance=provenance,
        deterministic_validation_passed=deterministic_validation_passed,
        sensitivity=row.data_sensitivity,
        model_generated_gold=model_generated_gold, from_holdout=from_holdout)
    if not permitted:
        raise LibraryError(permitted.reason)

    row.system_source = str(source).upper()[:32]
    row.source_provenance = provenance
    row.last_validated_at = _now()
    return _transition(session, row, st.SYSTEM_VALIDATED, actor=actor,
                       actor_id=None,
                       note=note or f"derived from {row.system_source}",
                       detail={"source": row.system_source,
                               "provenance": provenance})


# -------------------------------------------------------------- staleness
def sweep_stale(session: Session, current: Mapping[str, str], *,
                actor: str = "system") -> list[Row]:
    """Mark every retrievable case whose world has moved underneath it.

    Runs over APPROVED and SYSTEM_VALIDATED cases only. A DRAFT is going to be
    revalidated anyway, and marking it stale would bury the cases where
    staleness actually costs something — the ones production retrieval is
    drawing from right now.
    """
    rows = list(session.execute(
        select(Row).where(Row.review_status.in_(sorted(st.RETRIEVABLE)))
    ).scalars())

    moved: list[Row] = []
    for row in rows:
        axes = st.stale_because(to_case(row).recorded_versions(), current)
        if not axes:
            continue
        row.stale_axes = ", ".join(axes)[:240]
        _transition(session, row, st.STALE, actor=actor, actor_id=None,
                    note=f"stale on {row.stale_axes}",
                    detail={"axes": list(axes), "current": dict(current)})
        moved.append(row)
    return moved


def revalidate(session: Session, case_id: str, *, current: Mapping[str, str],
               actor: str = "system") -> Row:
    """A stale case re-checked against today's versions.

    It goes back to AUTO_VALIDATED, never straight back to APPROVED: the case
    was approved against a world that has since changed, and a person decides
    whether the approval survives that.
    """
    row = latest(session, case_id)
    if row is None:
        raise LibraryError(f"no case {case_id!r}")

    case = to_case(row)
    for axis, value in dict(current).items():
        attribute = {st.ONTOLOGY: "ontology_version",
                     st.METHOD: "method_version",
                     st.RELATIONSHIP: "relationship_version",
                     st.DATASET_CONTRACT: "dataset_contract_version",
                     st.PLANNER_SCHEMA: "planner_schema_version",
                     st.PROMPT_SCHEMA: "prompt_schema_version",
                     st.MODEL_FAMILY: "model_family"}.get(axis)
        if attribute:
            setattr(case, attribute, str(value or ""))

    problems = sc.validate(case)
    target = st.SME_REVIEW_REQUIRED if problems else st.AUTO_VALIDATED
    case.fingerprint = sc.fingerprint(case)
    _write(row, case)
    row.stale_axes = ""
    row.last_validated_at = _now()
    return _transition(session, row, target, actor=actor, actor_id=None,
                       note="revalidated",
                       detail={"problems": [str(p) for p in problems]})


# -------------------------------------------------------------- retrieval
def retrievable(session: Session, *, family_id: str = "",
                language: str = "", portfolio_scope: str = "",
                system_validated_enabled: bool = False,
                limit: int = 200) -> list[Row]:
    """The only query that puts a case in front of the live model.

    Latest version only. A superseded version that was approved before an edit
    is history, not curriculum.
    """
    statuses = [st.APPROVED]
    if system_validated_enabled:
        statuses.append(st.SYSTEM_VALIDATED)

    newest = (select(Row.case_id,
                     func.max(Row.case_version).label("case_version"))
              .group_by(Row.case_id).subquery())

    query = (select(Row)
             .join(newest, (Row.case_id == newest.c.case_id)
                   & (Row.case_version == newest.c.case_version))
             .where(Row.review_status.in_(statuses),
                    Row.data_sensitivity != st.CLIENT))
    if family_id:
        query = query.where(Row.family_id == family_id)
    if language:
        query = query.where(Row.language == language)
    if portfolio_scope:
        query = query.where(Row.portfolio_scope == portfolio_scope)

    return list(session.execute(
        query.order_by(Row.family_id, Row.case_id).limit(int(limit))
    ).scalars())


def duplicates(session: Session, case: sc.TeachingCase) -> list[Row]:
    """Cases already in the library teaching the same thing. §15."""
    return list(session.execute(
        select(Row).where(Row.fingerprint == sc.fingerprint(case),
                          Row.case_id != case.case_id,
                          Row.review_status != st.RETIRED)
    ).scalars())


# --------------------------------------------------------------- reporting
def coverage(session: Session) -> list[dict[str, Any]]:
    """How the library stands, family by family. §13 asks for quality by
    family rather than a total, because a total hides the empty families
    behind the crowded ones."""
    counts = dict(session.execute(
        select(Row.family_id, func.count())
        .where(Row.review_status == st.APPROVED).group_by(Row.family_id)
    ).all())
    totals = dict(session.execute(
        select(Row.family_id, func.count()).group_by(Row.family_id).where(
            Row.review_status != st.RETIRED)
    ).all())

    out: list[dict[str, Any]] = []
    for family in fam.FAMILIES:
        out.append({
            "family_id": family.id,
            "label": family.label,
            "group": family.group,
            "approved": int(counts.get(family.id, 0)),
            "total": int(totals.get(family.id, 0)),
            "available": family.available,
            "gated_on": family.gated_on,
            "gap": family.available and not counts.get(family.id),
        })
    return out


def summary(session: Session) -> dict[str, Any]:
    """One line per status, plus what §13 counts by."""
    by_status = dict(session.execute(
        select(Row.review_status, func.count()).group_by(Row.review_status)
    ).all())
    demanding = session.execute(
        select(func.count()).select_from(Row)
        .where(Row.difficulty.in_(sorted(sc.DEMANDING)),
               Row.review_status != st.RETIRED)).scalar() or 0
    multi_turn = session.execute(
        select(func.count()).select_from(Row)
        .where(Row.turn_count > 1, Row.review_status != st.RETIRED)
    ).scalar() or 0

    gaps = [c["family_id"] for c in coverage(session) if c["gap"]]
    return {
        "by_status": {k: int(v) for k, v in by_status.items()},
        "total": int(sum(by_status.values())),
        "approved": int(by_status.get(st.APPROVED, 0)),
        "expert_or_adversarial": int(demanding),
        "multi_turn": int(multi_turn),
        "families_covered": len(fam.AVAILABLE) - len(gaps),
        "families_available": len(fam.AVAILABLE),
        "gaps": gaps,
    }


def governance(session: Session) -> dict[str, Any]:
    """The library, reported honestly. Every cut the phase brief asks for.

    Why this is its own function and not a slice of `summary`
    ---------------------------------------------------------
    A count of 1,828 cases means nothing on its own, and the ways it can
    mislead are specific: a library that is 100% AUTO_VALIDATED reads as a
    library of 1,828 usable cases and is a library of none, because retrieval
    serves APPROVED only. A library whose cases were written by rules and
    blueprints reads as reviewed work unless the authoring method is on the
    same screen as the count.

    So every count here is broken down by the thing that could be hiding
    behind it, and `human_reviewed` is computed from actual approval records
    rather than from status — a case can only be counted as human reviewed
    when a person's name and a timestamp are on it.
    """
    rows = list(session.execute(select(Row)).scalars())
    newest: dict[str, Row] = {}
    for row in rows:
        held = newest.get(row.case_id)
        if held is None or row.case_version > held.case_version:
            newest[row.case_id] = row
    current = list(newest.values())

    def _count(attribute: str) -> dict[str, int]:
        out: dict[str, int] = {}
        for row in current:
            key = str(getattr(row, attribute, "") or "—")
            out[key] = out.get(key, 0) + 1
        return dict(sorted(out.items()))

    by_status = {name: 0 for name in st.STATUSES}
    for row in current:
        by_status[row.review_status] = by_status.get(row.review_status, 0) + 1

    #: A case counted as human reviewed must have a person and a time on it.
    #: §5 forbids labelling LLM-generated cases human reviewed, and the way
    #: that happens is not a deliberate lie — it is a status being read as an
    #: approval.
    human = [r for r in current
             if r.review_status == st.APPROVED and (r.reviewer or "").strip()
             and r.approved_at is not None]
    claimed = [r for r in current if r.review_status == st.APPROVED]

    provenance: dict[str, int] = {}
    for row in current:
        source = (row.source_provenance or "").split(":")[0] or "unrecorded"
        provenance[source] = provenance.get(source, 0) + 1

    retrievable_now = [r for r in current if bool(
        st.retrievable(r.review_status, sensitivity=r.data_sensitivity))]

    return {
        "cases": len(current),
        "versions": len(rows),
        "by_status": by_status,
        "by_authoring_method": _count("authoring_method"),
        "by_provenance": dict(sorted(provenance.items())),
        "by_family": _count("family_id"),
        "by_difficulty": _count("difficulty"),
        "by_scope": _count("portfolio_scope"),
        "by_language": _count("language"),
        "by_sensitivity": _count("data_sensitivity"),
        "human_reviewed": len(human),
        "approved_without_a_reviewer": len(claimed) - len(human),
        "retrievable_now": len(retrievable_now),
        "hand_written": sum(1 for r in current
                            if r.authoring_method == st.HUMAN),
        "generated": sum(1 for r in current
                         if r.authoring_method in st.GENERATED),
        "machine_authored": sum(
            1 for r in current
            if r.authoring_method in st.MACHINE_AUTHORED),
        "derived_from_contracts": sum(
            1 for r in current if r.authoring_method == st.DERIVED),
        "sentence": _governance_sentence(current, human, retrievable_now),
    }


def _governance_sentence(current: list[Row], human: list[Row],
                         retrievable_now: list[Row]) -> str:
    """The one line that has to be true.

    Written to be readable out loud in a governance meeting, and written so
    that the uncomfortable version of it is the one that appears when the
    uncomfortable version is true.
    """
    total = len(current)
    if not total:
        return "The teaching library is empty."
    written = sum(1 for r in current if r.authoring_method == st.HUMAN)
    blueprint = sum(1 for r in current if r.authoring_method == st.BLUEPRINT)
    migrated = sum(1 for r in current if r.authoring_method == st.MIGRATED)
    derived = sum(1 for r in current if r.authoring_method == st.DERIVED)
    return (
        f"{total} teaching cases. {len(human)} carry a named human approval "
        f"and {len(retrievable_now)} are retrievable by production. "
        f"{written} were written by hand, {blueprint} instantiated from "
        f"reviewed blueprints, {migrated} migrated from existing corpora and "
        f"{derived} derived from certified method contracts. No case is "
        "described as human reviewed without an approval record.")


def specifications(rows: Sequence[Row]) -> list[dict[str, Any]]:
    """Stored rows as plain dictionaries, for the factory to read.

    The same shape as the review queue's `specifications`, and for the same
    reason: the factory must be able to read the library without the backend
    being able to import the factory. Plain data crosses the line; imports do
    not.
    """
    return [to_case(row).to_dict() for row in rows]


__all__ = ["LibraryError", "approve", "coverage", "duplicates",
           "governance", "history",
           "latest", "reject", "retire", "retrievable", "revalidate", "save",
           "send_to_review", "specifications", "summary", "sweep_stale",
           "system_validate", "to_case", "version"]
