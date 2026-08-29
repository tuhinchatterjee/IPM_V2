"""
The AI Intelligence Studio, over HTTP. §35-§39, §43-§46.

What this router is for
-----------------------
Every Studio tab needs the same thing: an honest answer about one governed
object — what it is, how it was validated, how it is performing, what is stale.
The tabs differ in which object they are about; the shape of the answer does
not. So the routes are thin, and the honesty lives in the services they call.

Two rules run through all of it
--------------------------------
**Nothing here calls a provider.** §37 says the Retrieval Lab needs no live
call, and that is true of the whole Studio: retrieval, packs, routing
prediction, policy, taxonomy and governance are all deterministic. A Studio
that spent credits to render a screen would be a Studio nobody opens.

**Nothing here approves anything on its own.** §35 and §38 both say it — a
case is approved by a named person with a reason, and a winning experiment
is promoted by a person, not by having won. The routes that change a status
take a reviewer and a note, and refuse without them.

Who may see it
--------------
Case authoring and review are administrator work (§2: "Ordinary users should
not see case-authoring controls"), so the write routes require MANAGE_MODELS.
The read routes an analyst may see are the ones about how the product is
performing, because that is the question an analyst is entitled to ask about
an answer they were given.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from backend.api.permissions import Principal, RequireAdmin, RequireAnalyst
from backend.orchestration import routing as rt
from backend.services import review_queue as rq
from backend.services import teaching_library as tl
from backend.teaching import classifiers as cls
from backend.teaching import disclosure as dc
from backend.teaching import failures as fl
from backend.teaching import families as fam
from backend.teaching import pack as tp
from backend.teaching import policy as pol
from backend.teaching import release as rl
from backend.teaching import retrieval as rv
from backend.teaching import schema as sc
from backend.teaching import status as st

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/intelligence", tags=["intelligence"])

MAX_QUESTION = 2000


def _unavailable(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={"error": "storage_unavailable", "message": str(exc)})


def _refused(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail={"error": "refused", "message": str(exc)})


def _not_found(what: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"error": "not_found", "message": what})


def _actor(principal: Principal) -> str:
    """Who to record. A role is not a person, so an approval made without a
    named reviewer records the role and the user id and is visible as exactly
    that — §5's "do not label it human reviewed" applied to the audit trail."""
    who = str(getattr(principal, "role", "") or "unknown")
    return f"{who}#{principal.user_id}" if principal.user_id else who


def _session():
    from backend.db.engine import SessionLocal

    return SessionLocal()


# ===========================================================================
# Overview — the tab that has to be true before any other one matters
# ===========================================================================

@router.get("/overview")
def overview(principal: Principal = RequireAnalyst) -> dict[str, Any]:
    """What the intelligence layer is, and whether it is working.

    Deliberately leads with the governance numbers rather than with a score.
    A Studio whose first screen is a percentage teaches everybody who opens it
    that the percentage is the thing to look at, and the number that actually
    decides whether the product is safe is how many cases carry a human
    approval.
    """
    session = _session()
    try:
        governance = tl.governance(session)
        library = tl.summary(session)
        queue = rq.summary(session)
    except Exception as exc:  # noqa: BLE001 - reported, not swallowed
        raise _unavailable(exc) from exc
    finally:
        session.close()

    gate = rl.gate(require_release=False)
    return {
        "library": {**library, "governance": governance},
        "release": gate.to_dict(),
        "policy": {
            "fingerprint": pol.default().fingerprint,
            "rows": [{"label": label, "value": value}
                     for label, value in pol.default().describe()],
        },
        "review_queue": queue,
        "failure_taxonomy": {
            "categories": len(fl.CATEGORIES),
            "critical": sorted(fl.CRITICAL),
        },
        "classifiers": cls.report([]),
    }


@router.get("/governance")
def governance(principal: Principal = RequireAnalyst) -> dict[str, Any]:
    """The case count, broken down every way it could mislead.

    A count of 1,828 cases means nothing on its own. This is the endpoint that
    makes it mean something, and it is a read an analyst may make: the
    provenance of the examples behind an answer is part of the answer.
    """
    session = _session()
    try:
        return tl.governance(session)
    except Exception as exc:  # noqa: BLE001
        raise _unavailable(exc) from exc
    finally:
        session.close()


# ===========================================================================
# §7 — families
# ===========================================================================

@router.get("/families")
def families(principal: Principal = RequireAnalyst) -> dict[str, Any]:
    """Every governed family, what it teaches, and how covered it is."""
    session = _session()
    try:
        coverage = {row["family_id"]: row for row in tl.coverage(session)}
    except Exception as exc:  # noqa: BLE001
        raise _unavailable(exc) from exc
    finally:
        session.close()

    return {"families": [{
        "id": f.id, "label": f.label, "group": f.group,
        "teaches": f.teaches, "turns": f.turns, "discourse": f.discourse,
        "outcome": f.outcome, "scope": f.scope,
        "available": f.available, "gated_on": f.gated_on,
        **{k: v for k, v in (coverage.get(f.id) or {}).items()
           if k in ("approved", "total", "gap")},
    } for f in fam.FAMILIES], "version": fam.FAMILY_VERSION}


# ===========================================================================
# §35, §36 — authoring and review
# ===========================================================================

class CaseQuery(BaseModel):
    family_id: str = ""
    review_status: str = ""
    difficulty: str = ""
    limit: int = Field(default=50, ge=1, le=500)


@router.get("/cases")
def list_cases(family_id: str = Query(default=""),
               review_status: str = Query(default=""),
               difficulty: str = Query(default=""),
               limit: int = Query(default=50, ge=1, le=500),
               principal: Principal = RequireAdmin) -> dict[str, Any]:
    """The case list the authoring tab reads.

    Administrator-only. §2: ordinary users should not see case-authoring
    controls, and a list of every teaching case is the authoring surface
    whether or not it has buttons on it.
    """
    from sqlalchemy import select

    from backend.models.platform import TeachingCase as Row

    session = _session()
    try:
        query = select(Row)
        if family_id:
            query = query.where(Row.family_id == family_id)
        if review_status:
            query = query.where(Row.review_status == review_status)
        if difficulty:
            query = query.where(Row.difficulty == difficulty)
        rows = list(session.execute(
            query.order_by(Row.case_id, Row.case_version.desc())
            .limit(int(limit))).scalars())
        return {"cases": [_case_row(r) for r in rows], "count": len(rows)}
    except Exception as exc:  # noqa: BLE001
        raise _unavailable(exc) from exc
    finally:
        session.close()


def _case_row(row: Any) -> dict[str, Any]:
    """One case, as a list row. Never the whole body: a list endpoint that
    returns every contract for five hundred cases is a list endpoint nobody
    can call twice."""
    return {
        "case_id": row.case_id, "case_version": row.case_version,
        "title": row.title, "family_id": row.family_id,
        "question": row.question, "difficulty": row.difficulty,
        "risk_level": row.risk_level, "review_status": row.review_status,
        "authoring_method": row.authoring_method,
        "data_sensitivity": row.data_sensitivity,
        "source_provenance": row.source_provenance,
        "reviewer": row.reviewer,
        "approved_at": row.approved_at.isoformat() if row.approved_at else "",
        "turn_count": row.turn_count, "cluster_id": row.cluster_id,
        "stale_axes": row.stale_axes,
        "portfolio_scope": row.portfolio_scope, "language": row.language,
        "retrievable": bool(st.retrievable(row.review_status,
                                           sensitivity=row.data_sensitivity)),
    }


@router.get("/cases/{case_id}")
def read_case(case_id: str,
              principal: Principal = RequireAdmin) -> dict[str, Any]:
    """One case in full, with its history and what a reviewer needs. §36."""
    session = _session()
    try:
        row = tl.latest(session, case_id)
        if row is None:
            raise _not_found(f"no teaching case {case_id!r}")
        case = tl.to_case(row)
        built = tp.make(case)
        return {
            "case": case.to_dict(),
            "row": _case_row(row),
            "problems": [str(p) for p in sc.validate(case)],
            "teaching_pack": built.to_dict() if built else None,
            "history": [{
                "from": e.from_status, "to": e.to_status, "actor": e.actor,
                "note": e.note, "at": e.at.isoformat() if e.at else "",
                "detail": e.detail,
            } for e in tl.history(session, case_id)],
            "duplicates": [r.case_id for r in tl.duplicates(session, case)],
        }
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise _unavailable(exc) from exc
    finally:
        session.close()


class CaseBody(BaseModel):
    case: dict[str, Any] = Field(default_factory=dict)


@router.post("/cases", status_code=status.HTTP_201_CREATED)
def save_case(body: CaseBody,
              principal: Principal = RequireAdmin) -> dict[str, Any]:
    """Create or version a case. §35.

    Never approves. A case arrives at whatever status its own validators
    allow, and §5 is explicit that a validator passing is not a review.
    """
    session = _session()
    try:
        case = sc.TeachingCase.from_dict(body.case)
        row = tl.save(session, case, actor=_actor(principal),
                      actor_id=principal.user_id)
        session.commit()
        return {"case": _case_row(row),
                "problems": [str(p) for p in sc.validate(case)]}
    except tl.LibraryError as exc:
        session.rollback()
        raise _refused(exc) from exc
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        raise _unavailable(exc) from exc
    finally:
        session.close()


class Decision(BaseModel):
    reviewer: str = ""
    note: str = ""


@router.post("/cases/{case_id}/approve")
def approve_case(case_id: str, body: Decision,
                 principal: Principal = RequireAdmin) -> dict[str, Any]:
    """A named person signs for a case. §36 requires the reason."""
    session = _session()
    try:
        row = tl.approve(session, case_id,
                         reviewer=body.reviewer or _actor(principal),
                         reviewer_id=principal.user_id, note=body.note)
        session.commit()
        return {"case": _case_row(row)}
    except tl.LibraryError as exc:
        session.rollback()
        raise _refused(exc) from exc
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        raise _unavailable(exc) from exc
    finally:
        session.close()


@router.post("/cases/{case_id}/reject")
def reject_case(case_id: str, body: Decision,
                principal: Principal = RequireAdmin) -> dict[str, Any]:
    session = _session()
    try:
        row = tl.reject(session, case_id,
                        reviewer=body.reviewer or _actor(principal),
                        reviewer_id=principal.user_id, note=body.note)
        session.commit()
        return {"case": _case_row(row)}
    except tl.LibraryError as exc:
        session.rollback()
        raise _refused(exc) from exc
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        raise _unavailable(exc) from exc
    finally:
        session.close()


@router.post("/cases/{case_id}/retire")
def retire_case(case_id: str, body: Decision,
                principal: Principal = RequireAdmin) -> dict[str, Any]:
    session = _session()
    try:
        row = tl.retire(session, case_id,
                        actor=body.reviewer or _actor(principal),
                        actor_id=principal.user_id, note=body.note)
        session.commit()
        return {"case": _case_row(row)}
    except tl.LibraryError as exc:
        session.rollback()
        raise _refused(exc) from exc
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        raise _unavailable(exc) from exc
    finally:
        session.close()


# ===========================================================================
# §37 — the Retrieval Lab
# ===========================================================================

class LabRequest(BaseModel):
    question: str = Field(default="", max_length=MAX_QUESTION)
    capability: str = ""
    concepts: list[str] = Field(default_factory=list)
    datasets: list[str] = Field(default_factory=list)
    portfolio_scope: str = fam.NO_SCOPE
    language: str = "en"
    system_validated: bool = False
    #: Ask for the pack as well as the retrieval. Off by default because the
    #: pack is the expensive half to render and most of the time the question
    #: is which cases came back.
    include_pack: bool = False


@router.post("/retrieval-lab")
def retrieval_lab(body: LabRequest,
                  principal: Principal = RequireAdmin) -> dict[str, Any]:
    """§37: paste a question, see exactly what retrieval would do with it.

    No provider call, as §37 requires. Everything shown here — the features,
    the scores, the refusals, the pack, the predicted route — is deterministic,
    so the Lab is free to use and gives the same answer twice.

    The refusals are the half people actually need. "Nothing came back" is
    unactionable; "eleven cases were refused on portfolio scope" is a fix.
    """
    from sqlalchemy import select

    from backend.models.platform import TeachingCase as Row

    need = rv.Need(
        question=body.question, capability=body.capability,
        concepts=tuple(body.concepts), datasets=tuple(body.datasets),
        portfolio_scope=body.portfolio_scope, language=body.language)

    session = _session()
    try:
        rows = list(session.execute(select(Row).limit(5000)).scalars())
        cases = [tl.to_case(r) for r in rows]
    except Exception as exc:  # noqa: BLE001
        raise _unavailable(exc) from exc
    finally:
        session.close()

    result = rv.retrieve(
        cases, need,
        permission=rv.Permission(system_validated=body.system_validated))
    decision = rt.decide(body.question)
    packs = tp.build(result.cases, budget=pol.default().token_budget) \
        if body.include_pack else []

    return {
        "need": {
            "question": body.question, "capability": body.capability,
            "concepts": list(body.concepts), "datasets": list(body.datasets),
            "portfolio_scope": body.portfolio_scope,
            "language": body.language,
        },
        "considered": len(cases),
        **result.to_dict(),
        "predicted_route": decision.record(),
        "token_budget": pol.default().token_budget,
        "teaching_pack": [p.to_dict() for p in packs] if packs else [],
        "pack_tokens": sum(p.estimated_tokens() for p in packs),
    }


# ===========================================================================
# §38, §39 — experiments and evaluation
# ===========================================================================

@router.get("/policy")
def policy(principal: Principal = RequireAnalyst) -> dict[str, Any]:
    """The routing policy in force, and what a sweep would try. §31."""
    active = pol.default()
    return {
        "active": active.to_dict(),
        "fingerprint": active.fingerprint,
        "rows": [{"label": label, "value": value}
                 for label, value in active.describe()],
        "grid": {k: list(v) for k, v in pol.GRID.items()},
        "candidates": len(pol.candidates()),
    }


@router.get("/failures")
def failure_taxonomy(principal: Principal = RequireAnalyst) -> dict[str, Any]:
    """§34's taxonomy, for the UI to render and the queue to file against."""
    return {
        "version": fl.TAXONOMY_VERSION,
        "stages": list(fl.STAGES),
        "categories": [{
            "id": c.id, "stage": c.stage, "label": c.label,
            "looks_like": c.looks_like, "defect": c.defect,
            "critical": fl.is_critical(c.id),
        } for c in fl.CATEGORIES],
    }


@router.get("/routing")
def routing(principal: Principal = RequireAnalyst) -> dict[str, Any]:
    """§22-§28: the model roles, the routes, and what happens when the complex
    one cannot be served. Never a key, and never a model id this code chose."""
    from backend.llm import roles

    return {
        "roles": roles.describe(),
        "routes": [{"id": route, "label": rt.LABELS.get(route, route),
                    "role": rt.ROLE_OF.get(route, "")}
                   for route in rt.ROUTES],
        "unavailable_policy": rt.unavailable_policy(),
        "policies": list(rt.POLICIES),
        "cascade_limits": {
            "routine_plans": rt.MAX_ROUTINE_PLANS,
            "complex_replans": rt.MAX_COMPLEX_REPLANS,
            "critic_passes": rt.MAX_CRITIC_PASSES,
            "interpretation_repairs": rt.MAX_INTERPRETATION_REPAIRS,
        },
        "stages": list(rt.STAGES),
    }


@router.get("/classifiers")
def classifiers(principal: Principal = RequireAnalyst) -> dict[str, Any]:
    """§32: which narrow-model experiments have been run, and which have not.

    The unmeasured list is the useful half. A report showing only the
    experiments somebody ran cannot show which of the seven nobody has looked
    at.
    """
    return cls.report([])


# ===========================================================================
# §33 — the review queue
# ===========================================================================

@router.get("/review-queue")
def review_queue(limit: int = Query(default=50, ge=1, le=200),
                 principal: Principal = RequireAdmin) -> dict[str, Any]:
    """§33's queue, including the items approved and not yet released.

    That last list is the one that stops a queue looking clear when it is not:
    an approved correction that has not shipped has not fixed anything.
    """
    session = _session()
    try:
        return {
            "summary": rq.summary(session),
            "awaiting_release": [{
                "id": item.id, "question": item.question,
                "failure_category": item.failure_category,
                "teaching_case_id": item.teaching_case_id,
                "adjudicated_at": (item.adjudicated_at.isoformat()
                                   if item.adjudicated_at else ""),
            } for item in rq.awaiting_release(session, limit=limit)],
        }
    except Exception as exc:  # noqa: BLE001
        raise _unavailable(exc) from exc
    finally:
        session.close()


# ===========================================================================
# §43, §44 — releases
# ===========================================================================

@router.get("/releases")
def releases(principal: Principal = RequireAnalyst) -> dict[str, Any]:
    """The Teaching Releases on disk, and which one production would use."""
    path = rl.latest()
    manifest, cases, missing = (rl.load(path) if path else
                                (rl.Manifest(), [], list(rl.FILES)))
    return {
        "gate": rl.gate(require_release=False).to_dict(),
        "latest": {
            "release_id": manifest.release_id,
            "path": str(path) if path else "",
            "manifest": manifest.to_dict(),
            "cases": len(cases),
            "missing_files": missing,
        } if path else None,
        "states": list(rl.STATES),
        "files": list(rl.FILES),
    }


@router.get("/disclosure-sections")
def disclosure_sections(principal: Principal = RequireAnalyst
                        ) -> dict[str, Any]:
    """§45's seven Trace sections, named for the UI to render in order."""
    return {"sections": list(dc.SECTIONS), "version": dc.DISCLOSURE_VERSION}


__all__ = ["router"]
