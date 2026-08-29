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

from backend.ai_studio import capabilities as cap
from backend.ai_studio import permissions as pm
from backend.ai_studio import report as rp
from backend.ai_studio import tabs as tb
from backend.api.permissions import Principal, RequireAdmin, RequireAnalyst
from backend.api.routers.assurance import viewer_for
from backend.assurance import comparison as acmp
from backend.assurance import reviews as arv
from backend.assurance import store as ast
from backend.assurance import trends as atr
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
        # §201. The six broad dimensions replace the flat top-level component
        # wall. They sit BELOW the governance numbers rather than above them
        # for the reason in this function's docstring: a screen that opens
        # with a score teaches everybody that the score is the thing to read.
        "dimensions": atr.overview(),
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


# ---------------------------------------------------------------------------
# Part C — the Studio's fifteen tabs
# ---------------------------------------------------------------------------
#
# Added rather than replacing the routes above: those answer questions about
# one object each and the Studio is built on them. These answer "what does
# this TAB show", which is a different question and one the front end needs
# before it can render anything.


@router.get("/studio/tabs")
def studio_tabs(principal: Principal = RequireAnalyst) -> dict[str, Any]:
    """§102's fifteen tabs, and which of them this caller may open.

    Returned for every signed-in caller, including one who may open none: a
    front end that cannot ask what exists cannot explain to a reader why they
    are seeing an empty page.
    """
    return tb.index(principal.role.value)


@router.get("/studio/readiness")
def studio_readiness(principal: Principal = RequireAnalyst) -> dict[str, Any]:
    """§104's honest client-demo status, with its reasons.

    Assembled from what other parts of the product established, never from a
    judgement made here. A readiness that this route could compute on its own
    would be a readiness that agrees with itself.
    """
    gate = rl.gate(require_release=False)
    unavailable = _unavailable_roles()

    signals = cap.Signals(
        release_state=gate.state,
        provider_state=_provider_state(),
        unavailable_roles=unavailable,
        stale_axes=list(getattr(gate, "moved", ()) or ()),
        unmeasured_capabilities=list(cap.CAPABILITIES))
    return {**cap.readiness(signals).to_dict(),
            "signals": {"release_state": gate.state,
                        "unavailable_roles": unavailable}}


def _unavailable_roles() -> list[str]:
    """Active model roles the provider cannot serve. §29's preflight.

    Spends nothing: the preflight reads configuration and whatever the
    provider can say about itself without a call, which is the whole reason
    the Studio can render this without costing anything.
    """
    from backend.llm import roles as rl_roles

    try:
        import backend.llm as llm

        report = rl_roles.preflight(llm.get_provider())
    except Exception:  # pragma: no cover - no provider configured
        return []
    return [row["name"] for row in report.get("roles", [])
            if row.get("active") and row.get("state") == rl_roles.UNAVAILABLE]


def _provider_state() -> str:
    """OFFLINE / CONFIGURED / CONNECTED / DEGRADED, from the provider itself.

    CONNECTED means a real response came back, not that a key is present —
    the distinction the whole provider-observability work exists for, and the
    one §104's readiness depends on.
    """
    try:
        import backend.llm as llm

        return str(getattr(llm.provider_status(), "state", "OFFLINE"))
    except Exception:  # pragma: no cover - provider unavailable
        return "OFFLINE"


@router.get("/studio/capabilities")
def studio_capabilities(principal: Principal = RequireAnalyst
                        ) -> dict[str, Any]:
    """§103's eighteen capability rows.

    Every one appears, including the ones nothing has measured — as
    NOT_EVALUATED rather than omitted, because a capability missing from a
    health table reads as one that does not exist.
    """
    return cap.health([])


@router.get("/studio/knowledge")
def studio_knowledge(principal: Principal = RequireAnalyst) -> dict[str, Any]:
    """§105. Read-only summaries that deep-link to the real editors."""
    return tb.knowledge()


@router.get("/studio/blueprints")
def studio_blueprints(principal: Principal = RequireAnalyst
                      ) -> dict[str, Any]:
    """§107. Every blueprint, with what may be omitted and why."""
    return tb.blueprints()


@router.get("/studio/judgment")
def studio_judgment(principal: Principal = RequireAnalyst) -> dict[str, Any]:
    """§108. The six judgment policies, with their actual rules on screen."""
    return tb.judgment()


@router.get("/studio/visual-grammar")
def studio_visual_grammar(principal: Principal = RequireAnalyst
                          ) -> dict[str, Any]:
    """§109. Roles, mapping, suitability weights and the critic's checks."""
    return tb.visual_grammar()


class ShapeLabRequest(BaseModel):
    """§109's Result Shape Lab. A SHAPE, never portfolio data."""

    shape: str = Field(..., description="One of the fifteen result shapes")
    roles: dict[str, str] = Field(default_factory=dict)
    categories: int = 0
    longest_label: int = 0
    periods: int = 0
    measures: int = 0
    cardinality: int = 0
    missing_pct: float = 0.0
    needs_zero_baseline: bool = False
    zero_baseline_available: bool = True
    wants_records: bool = False
    precision_required: int = 0
    narrow_device: bool = False


@router.post("/studio/shape-lab")
def studio_shape_lab(body: ShapeLabRequest,
                     principal: Principal = RequireAnalyst) -> dict[str, Any]:
    """§109's lab, with every candidate's score and rejection kept.

    Takes a sanitised schema, not rows: "no live portfolio data required" is
    the instruction, and a lab that accepted rows would be a lab somebody
    pasted a client extract into.
    """
    payload = body.model_dump()
    shape = payload.pop("shape")
    roles = payload.pop("roles")
    return tb.result_shape_lab(shape, roles, **payload)


@router.get("/studio/permissions")
def studio_permissions(principal: Principal = RequireAdmin) -> dict[str, Any]:
    """§119's grant table. Administrator-only: it is the Settings tab."""
    return {**pm.matrix(), "yours": pm.granted(principal.role.value)}


@router.get("/studio/holdout")
def studio_holdout(principal: Principal = RequireAdmin) -> dict[str, Any]:
    """§120. Sealed-holdout METADATA, and nothing else, ever.

    The factory already keeps holdout content behind an import boundary the
    backend cannot cross. This is the second wall: a screenshot of a holdout
    question in a demo has leaked it whatever the import graph says.
    """
    path = rl.latest()
    manifest = {}
    if path:
        _, _, _ = rl.load(path)
        manifest = _holdout_manifest(path)
    try:
        return pm.holdout_view(manifest)
    except pm.HoldoutLeak as leak:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "holdout_leak", "message": str(leak)}) from leak


def _holdout_manifest(path: Any) -> dict[str, Any]:
    import json
    from pathlib import Path

    candidate = Path(path) / "holdout_manifest.json"
    if not candidate.exists():
        return {}
    try:
        return json.loads(candidate.read_text("utf-8"))
    except Exception:  # pragma: no cover - unreadable release file
        return {}


@router.get("/studio/teaching-cases")
def studio_teaching_cases(principal: Principal = RequireAdmin
                          ) -> dict[str, Any]:
    """§106. The library, with the governance sentence leading.

    Administrator-only, because a list of what production retrieves is most
    of the way to knowing how to get a chosen answer out of it.
    """
    session = _session()
    try:
        return tb.teaching_cases(tl.summary(session), tl.governance(session),
                                 tl.coverage(session))
    finally:
        session.close()


@router.get("/studio/routing-tab")
def studio_routing_tab(principal: Principal = RequireAnalyst
                       ) -> dict[str, Any]:
    """§110. Roles, thresholds, and the four "why" answers."""
    return tb.routing(_preflight())


def _preflight() -> dict[str, Any]:
    from backend.llm import roles as rl_roles

    try:
        import backend.llm as llm

        return rl_roles.preflight(llm.get_provider())
    except Exception:  # pragma: no cover - no provider configured
        return {"roles": [], "note": "No provider is configured."}


class SimulateRequest(BaseModel):
    """A sanitised question for the route simulator. Never sent anywhere."""

    question: str = Field(..., min_length=1, max_length=2000)


@router.post("/studio/route-simulator")
def studio_route_simulator(body: SimulateRequest,
                           principal: Principal = RequireAdmin
                           ) -> dict[str, Any]:
    """§110's simulator. Predicts the route; makes no call.

    An administrator who can try twenty phrasings for nothing will, and one
    who spends a call per try will try none — which is how a routing policy
    goes unexamined.
    """
    return tb.route_simulator(body.question)


@router.get("/studio/prompts")
def studio_prompts(principal: Principal = RequireAdmin) -> dict[str, Any]:
    """§111. The pack policy and the caching contract, never prompt text
    that might carry a hard-coded client example."""
    return tb.prompts()


@router.get("/studio/evaluations")
def studio_evaluations(principal: Principal = RequireAdmin
                       ) -> dict[str, Any]:
    """§112's seven suites, and the rules under which any of them may be
    quoted."""
    return tb.evaluations()


@router.get("/studio/releases-tab")
def studio_releases_tab(principal: Principal = RequireAnalyst
                        ) -> dict[str, Any]:
    """§115. What is frozen, approved, and stale underneath it."""
    path = rl.latest()
    manifest, _, missing = (rl.load(path) if path else
                            (rl.Manifest(), [], list(rl.FILES)))
    return tb.releases(rl.gate(require_release=False).to_dict(),
                       manifest.to_dict(), list(rl.FILES), missing)


@router.get("/investigation-reviews")
def investigation_reviews(view: str = Query(default=arv.RECENT),
                          limit: int = Query(default=100, ge=1, le=500),
                          since: str = Query(default=""),
                          until: str = Query(default=""),
                          user_id: int | None = Query(default=None),
                          project_id: str = Query(default=""),
                          portfolio_scope: str = Query(default=""),
                          language: str = Query(default=""),
                          officer_level: int | None = Query(default=None),
                          model_route: str = Query(default=""),
                          teaching_release_id: str = Query(default=""),
                          overall_status: str = Query(default=""),
                          dimension: str = Query(default=""),
                          feedback: str = Query(default=""),
                          case_family: str = Query(default=""),
                          principal: Principal = RequireAnalyst
                          ) -> dict[str, Any]:
    """§186 and §187. Recent Investigations, and how CreditProbe performed.

    Open to an analyst rather than administrator-only, unlike the rest of the
    Studio: §207 already limits WHICH Investigations each caller sees, and
    an analyst who ran an Investigation is entitled to review it. What an
    analyst does not get is other people's — which the access policy, not
    this decorator, decides.
    """
    viewer = viewer_for(principal)
    filters = arv.Filters.from_query({
        "since": since, "until": until, "user_id": user_id,
        "project_id": project_id, "portfolio_scope": portfolio_scope,
        "language": language, "officer_level": officer_level,
        "model_route": model_route,
        "teaching_release_id": teaching_release_id,
        "overall_status": overall_status, "dimension": dimension,
        "feedback": feedback, "case_family": case_family})
    records = ast.recent(limit=max(limit, 200))
    listing = arv.build(viewer, view=view, filters=filters, limit=limit,
                        records=records)
    payload = listing.to_dict()
    payload["counts"] = arv.counts(viewer, records=records)
    return payload


@router.get("/studio/investigation-reviews")
def studio_investigation_reviews(principal: Principal = RequireAnalyst
                                 ) -> dict[str, Any]:
    """§186's tab shell: the views, their counts, and the six dimensions
    across everything this reviewer may see."""
    viewer = viewer_for(principal)
    records = ast.recent(limit=500)
    visible = arv.build(viewer, view=arv.RECENT, limit=500, records=records)
    return tb.investigation_reviews(
        arv.counts(viewer, records=records),
        visible.total_visible,
        atr.tiles([r for r in records
                   if r.assurance_record_id in
                   {row["assurance_record_id"] for row in visible.rows}]))


@router.get("/dimension-trends")
def dimension_trends(cohort: str = Query(default="release"),
                     limit: int = Query(default=500, ge=1, le=1000),
                     principal: Principal = RequireAnalyst
                     ) -> dict[str, Any]:
    """§202. One cohort at a time, each bucket carrying its own sample size.

    A bucket below the sample floor reports no score rather than a score
    with a footnote: a number with a caveat next to it gets read as a
    number.
    """
    viewer = viewer_for(principal)
    records = ast.recent(limit=limit)
    visible = [r for r in records
               if r.assurance_record_id in
               {row["assurance_record_id"]
                for row in arv.build(viewer, limit=limit,
                                     records=records).rows}]
    return atr.trend(visible, cohort)


@router.get("/dimension-contribution/{record_id}")
def dimension_contribution(record_id: str,
                           principal: Principal = RequireAnalyst
                           ) -> dict[str, Any]:
    """§203. How each dimension affected one record's overall status.

    Roles and sentences rather than six percentages: where a gate decided
    the outcome the weights never ran, and printing them would describe an
    arithmetic that did not happen.
    """
    from backend.assurance import access as aac

    viewer = viewer_for(principal)
    row = ast.get(record_id)
    if row is None or not aac.may_read(viewer, aac.Subject(
            assurance_record_id=row.assurance_record_id,
            investigation_id=row.investigation_id,
            project_id=row.project_id, owner_user_id=row.user_id,
            tenant_id=row.tenant_id)).allowed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "not_found",
                    "message": "No assurance record is available at that "
                               "address."})
    payload = atr.contribution(row)
    payload["comparison_verdicts"] = [
        {"id": v, "means": acmp.VERDICT_MEANS[v]} for v in acmp.VERDICTS]
    return payload


@router.get("/studio/live-health")
def studio_live_health(principal: Principal = RequireAdmin
                       ) -> dict[str, Any]:
    """§116. Provider state and the exact safe local commands.

    Never a key and never an authorization header. The commands are given in
    full because an administrator who cannot copy one will invent a variant,
    and the invented variant is the one that logs a key.
    """
    return tb.live_health({"state": _provider_state()}, _preflight())


@router.get("/studio/failures")
def studio_failures(principal: Principal = RequireAdmin) -> dict[str, Any]:
    """§114. The active-learning queue. No automatic production learning."""
    session = _session()
    try:
        items = rq.listing(session) if hasattr(rq, "listing") else []
    finally:
        session.close()
    return tb.failures(items)


@router.get("/studio/report")
def studio_report(principal: Principal = RequireAdmin) -> dict[str, Any]:
    """§121's Intelligence Performance report, as data.

    Every one of the thirteen sheets appears, empty ones saying so. A report
    whose contents depend on what was available produces two documents with
    the same title and different meanings.
    """
    try:
        return rp.build()
    except rp.WouldLeak as leak:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "would_leak", "message": str(leak)}) from leak


@router.get("/studio/audit-actions")
def studio_audit_actions(principal: Principal = RequireAdmin
                         ) -> dict[str, Any]:
    """§123. What is audited, and what every entry must carry."""
    return {"actions": list(rp.AUDITED), "fields": list(rp.AUDIT_FIELDS),
            "events": [{"id": e, "says": rp.SAYS[e],
                        "notify": rp.NOTIFY[e]} for e in rp.EVENTS]}


@router.get("/studio/badge")
def studio_badge(principal: Principal = RequireAnalyst) -> dict[str, Any]:
    """§119: all an ordinary Analyst sees of the Studio.

    A compact assurance badge for the Trace. Not a score and not a case count:
    an analyst who could read which cases production retrieves would be most
    of the way to knowing how to phrase a question to get a chosen answer.
    """
    gate = rl.gate(require_release=False)
    ready = cap.readiness(cap.Signals(
        release_state=gate.state,
        unmeasured_capabilities=list(cap.CAPABILITIES)))
    return pm.badge(gate.release_id, gate.state, ready.state)


__all__ = ["router"]
