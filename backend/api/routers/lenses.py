"""
Lenses over HTTP.

A caller may define a lens, ask for a change to one, render it, and read its
revision history. A caller may not supply a figure or name an analysis the
Engine Registry does not have — the service refuses both, and says why.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from backend.api.permissions import Principal, RequireAnalyst, RequireDataSteward
from backend.services import lenses as ln

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/lenses", tags=["lenses"])

MAX_TEXT = 2000


def _unavailable(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={"error": "storage_unavailable", "message": str(exc)},
    )


def _not_found(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"error": "not_found", "message": str(exc)},
    )


def _refused(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail={"error": "invalid_lens", "message": str(exc)},
    )


class TileIn(BaseModel):
    """One tile as the person arranging the lens is holding it.

    One shape for both kinds, because a lens holds an ordered list of things
    to draw and a caller should not have to send two shapes to fill it. A tile
    naming neither an analysis nor a metric is refused by `validate`, which
    says which of the two is missing.

    A layout is submitted whole rather than as a list of moves: an ordering is
    not a set of independent edits, and applying five of six reorderings
    leaves a lens nobody asked for.
    """

    kind: str = Field(default="", max_length=16)
    analysis_id: str = Field(default="", max_length=120)
    metric_id: str = Field(default="", max_length=160)
    title: str = Field(default="", max_length=200)
    visual: str = Field(default="auto", max_length=16)
    params: dict = Field(default_factory=dict)
    filters: dict = Field(default_factory=dict)
    period: str = Field(default="", max_length=32)
    note: str = Field(default="", max_length=MAX_TEXT)


class SectionIn(BaseModel):
    """A band, and the tiles in it by position in the submitted order.

    `subtitle`, not `note`: that is the key every stored lens and the renderer
    already use, and a second name for one field is how a band's line of prose
    goes missing between the editor and the screen.
    """

    title: str = Field(default="", max_length=200)
    subtitle: str = Field(default="", max_length=MAX_TEXT)
    panels: list[int] = Field(default_factory=list)


class LayoutIn(BaseModel):
    tiles: list[TileIn] = Field(default_factory=list)
    sections: list[SectionIn] | None = None
    change_summary: str = Field(default="", max_length=500)


class LensIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=MAX_TEXT)
    audience: str = Field(default="", max_length=120)
    # `TileIn`, not a panel shape requiring an analysis id: a lens made
    # through this route could otherwise hold no metric tiles at all,
    # which is most of what a lens is for now. A tile naming neither an
    # analysis nor a metric is still refused — by `validate`, which says
    # which of the two is missing rather than "field required".
    panels: list[TileIn] = Field(default_factory=list)
    project_id: int | None = None


class AskIn(BaseModel):
    """A request in words. Applied only if `apply` is set."""

    request: str = Field(min_length=1, max_length=500)
    apply: bool = True


class StatusIn(BaseModel):
    status: str = Field(max_length=24)


@router.get("", summary="Lenses")
def list_lenses(status_filter: str | None = Query(default=None, alias="status")) -> dict:
    return {
        "lenses": ln.listing(status=status_filter),
        "visuals": list(ln.VISUALS),
        "statuses": list(ln.STATUSES),
        "max_panels": ln.MAX_PANELS,
    }


@router.post("", status_code=201, summary="Create a lens")
def create_lens(payload: LensIn, principal: Principal = RequireAnalyst) -> dict:
    try:
        return ln.create(
            name=payload.name,
            panels=[ln.Panel.from_dict(p.model_dump()) for p in payload.panels],
            description=payload.description, audience=payload.audience,
            project_id=payload.project_id, user_id=principal.user_id,
        ).to_dict()
    except ln.InvalidLens as e:
        raise _refused(e) from e
    except ln.StorageUnavailable as e:
        raise _unavailable(e) from e


@router.post("/build", status_code=201, summary="Build a lens by describing it")
def build_lens(payload: AskIn, principal: Principal = RequireAnalyst) -> dict:
    """Turn a description into a lens.

    The description is matched against the Engine Registry's own metadata, so it
    can only ever resolve to analyses that exist. Anything it asks for that the
    registry has nothing for comes back as a refusal with the reason.
    """
    try:
        proposal = ln.propose(payload.request, user_id=principal.user_id)
    except ln.InvalidLens as e:
        raise _refused(e) from e
    if not proposal.panels:
        return {"lens": None, "proposal": proposal.to_dict()}
    if not payload.apply:
        return {"lens": None, "proposal": proposal.to_dict()}
    try:
        lens = ln.create(
            name=payload.request[:200], panels=proposal.panels,
            description=proposal.change_summary, origin="ai",
            request=payload.request, user_id=principal.user_id,
        )
    except ln.InvalidLens as e:
        raise _refused(e) from e
    except ln.StorageUnavailable as e:
        raise _unavailable(e) from e
    return {"lens": lens.to_dict(), "proposal": proposal.to_dict()}


@router.get("/{lens_id}", summary="One lens and its revisions")
def get_lens(lens_id: int) -> dict:
    try:
        return ln.get(lens_id).to_dict()
    except ln.LensNotFound as e:
        raise _not_found(e) from e
    except ln.StorageUnavailable as e:
        raise _unavailable(e) from e


@router.get("/{lens_id}/render", summary="Run every panel now")
def render_lens(lens_id: int, period: str | None = None) -> dict:
    """A lens is what the book says today, not what it said when it was built."""
    try:
        return ln.render(lens_id, period=period)
    except ln.LensNotFound as e:
        raise _not_found(e) from e
    except ln.StorageUnavailable as e:
        raise _unavailable(e) from e


@router.post("/{lens_id}/ask", summary="Change a lens by asking")
def ask_lens(lens_id: int, payload: AskIn,
             principal: Principal = RequireAnalyst) -> dict:
    """"Add the sector breakdown", "drop the stress panel".

    Every applied change is a new revision with a sentence saying what changed,
    and the previous one is kept so it can be put back.
    """
    try:
        before = ln.get(lens_id)
        current = [ln.Panel.from_dict(p) for p in before.panels]
        proposal = ln.propose(payload.request, existing=current,
                              user_id=principal.user_id)
    except ln.LensNotFound as e:
        raise _not_found(e) from e
    except ln.InvalidLens as e:
        raise _refused(e) from e
    except ln.StorageUnavailable as e:
        raise _unavailable(e) from e

    if not payload.apply or not proposal.change_summary:
        return {"lens": ln.get(lens_id).to_dict(), "proposal": proposal.to_dict()}

    try:
        lens = ln.revise(
            lens_id, proposal.panels, request=payload.request,
            change_summary=proposal.change_summary, user_id=principal.user_id,
            # A revision must not scramble a lens's bands. Sections hold
            # indices, so they are remapped by panel identity rather than
            # carried across verbatim, and the notes travel with them.
            sections=ln.resection(current, before.sections, proposal.panels),
            notes=before.notes,
        )
    except ln.InvalidLens as e:
        raise _refused(e) from e
    return {"lens": lens.to_dict(), "proposal": proposal.to_dict()}


@router.post("/{lens_id}/restore/{version}", summary="Put back an earlier version")
def restore_lens(lens_id: int, version: int,
                 principal: Principal = RequireAnalyst) -> dict:
    try:
        return ln.restore(lens_id, version, user_id=principal.user_id).to_dict()
    except ln.LensNotFound as e:
        raise _not_found(e) from e
    except ln.InvalidLens as e:
        raise _refused(e) from e
    except ln.StorageUnavailable as e:
        raise _unavailable(e) from e


@router.post("/{lens_id}/status", summary="Publish or archive a lens")
def set_lens_status(lens_id: int, payload: StatusIn,
                    principal: Principal = RequireAnalyst) -> dict:
    try:
        return ln.set_status(lens_id, payload.status).to_dict()
    except ln.LensNotFound as e:
        raise _not_found(e) from e
    except ln.InvalidLens as e:
        raise _refused(e) from e
    except ln.StorageUnavailable as e:
        raise _unavailable(e) from e


@router.delete("/{lens_id}", status_code=204, summary="Delete a lens")
def delete_lens(lens_id: int, principal: Principal = RequireDataSteward) -> None:
    try:
        ln.delete(lens_id)
    except ln.LensNotFound as e:
        raise _not_found(e) from e
    except ln.StorageUnavailable as e:
        raise _unavailable(e) from e


__all__ = ["router"]


@router.put("/{lens_id}/layout", summary="Rearrange a lens by hand")
def set_layout(lens_id: int, payload: LayoutIn,
               principal: Principal = RequireAnalyst) -> dict:
    """Reorder tiles, band them, retitle them, change how one is drawn.

    The same validation and the same versioning as the conversational path,
    deliberately: a tile moved by hand is refused for the same reasons a tile
    added by asking is, and a rearrangement that turns out to have been wrong
    can be put back. There is no route into a lens that skips `validate`.

    Sections address tiles by position in the list submitted with them, so an
    ordering and its bands arrive together and cannot disagree.
    """
    try:
        before = ln.get(lens_id)
    except ln.LensNotFound as e:
        raise _not_found(e) from e
    except ln.StorageUnavailable as e:
        raise _unavailable(e) from e

    panels = [ln.Panel.from_dict(tile.model_dump()) for tile in payload.tiles]
    sections = _sections_for(payload.sections, len(panels))

    try:
        lens = ln.revise(
            lens_id, panels,
            request="rearranged by hand",
            change_summary=payload.change_summary or _describe(before, panels),
            user_id=principal.user_id,
            sections=sections, notes=before.notes)
    except ln.InvalidLens as e:
        raise _refused(e) from e
    except ln.StorageUnavailable as e:
        raise _unavailable(e) from e
    return lens.to_dict()


def _sections_for(sections: list[SectionIn] | None,
                  tiles: int) -> list[dict] | None:
    """Bands as stored, refusing any that points at a tile that is not there.

    A section holding an index past the end of the list renders as a band with
    a missing tile — or, worse, quietly picks up whichever tile later occupies
    that position. Both are silent, so the index is checked here.
    """
    if sections is None:
        return None
    out: list[dict] = []
    for section in sections:
        for index in section.panels:
            if not 0 <= index < tiles:
                raise _refused(ln.InvalidLens(
                    f"Section '{section.title or 'untitled'}' points at tile "
                    f"{index}, and the layout has {tiles}."))
        out.append({"title": section.title, "subtitle": section.subtitle,
                    "panels": list(section.panels)})
    return out


def _describe(before: ln.LensView, panels: list[ln.Panel]) -> str:
    """What changed, in a sentence, when the caller did not say.

    Every revision carries one. A history of "rearranged by hand" nine times
    tells somebody nothing about which of the nine to restore.
    """
    was = [(p.get("kind"), p.get("metric_id") or p.get("analysis_id"))
           for p in before.panels]
    now = [(p.kind, p.metric_id or p.analysis_id) for p in panels]
    if was == now:
        return "Retitled or redrawn without changing which tiles are shown."
    added = [n[1] for n in now if n not in was]
    removed = [w[1] for w in was if w not in now]
    parts = []
    if added:
        parts.append(f"added {', '.join(added)}")
    if removed:
        parts.append(f"removed {', '.join(removed)}")
    if not parts:
        return "Reordered the tiles."
    return f"Rearranged the lens: {'; '.join(parts)}."
