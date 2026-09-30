"""
The governed Cohort: one population, one identity, in every module.

Frozen through the What-If engine's own `scenario.cohort.freeze` -- so a cohort
saved from the grid, from an issue card, from Early Warning or from a Lens
selection has exactly the membership hash the scenario engine will re-resolve
and verify before it calculates anything. The predicate is composed from typed
filters over the governed grid view (`grid.py`), with literals written by the
scenario selector's own allowlist (`predicates.literal`).

Identity has two parts, kept apart on purpose:

* `predicate_hash` -- the QUESTION (filters, selection mode, period, book);
* `membership_hash` -- the ANSWER (SHA-256 of the sorted exposure ids).

Reopening a cohort re-runs the question and compares the answer. Refreshing a
cohort "to latest data" writes a NEW VERSION at the latest period and never
alters the historical population (CO-02).
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from backend.cockpit_v4.scenario import cohort as ch
from backend.workspace import grid, predicates
from backend.workspace.access import Book
from backend.workspace.objects import ObjectService, Principal

#: A cohort may carry its explicit member ids (an immutable snapshot) up to
#: this size; above it the predicate plus membership hash is the reference.
SNAPSHOT_MAX = 5000

SOURCES = ("grid_selection", "issue", "early_warning", "lens_selection",
           "chart_selection", "investigation", "scenario_library", "manual",
           "message")


def _predicate(v: grid.View, checked: list[dict[str, Any]]) -> str:
    """SQL over the exposure relation selecting the grid rows that match."""
    if not checked:
        return ""
    inner = predicates.literal(checked)
    return (f"{v.key} IN (SELECT {v.key} FROM ({v.sql}) gwv WHERE {inner})")


def resolve(book: Book, *, filters: Any, selection: str = ch.BY_ROW,
            period: str = "") -> tuple[grid.View, list[dict[str, Any]],
                                        ch.Frozen]:
    v = grid.view(book, period)
    checked = predicates.normalise(filters, columns=v.keys)
    if selection not in ch.SELECTIONS:
        raise HTTPException(422, {"error_code": "INVALID_SELECTION",
                                  "message": "selection is 'row' (the "
                                             "exposures that match) or "
                                             "'owner' (everything their "
                                             "owners hold)."})
    try:
        frozen = ch.freeze(session=book.session, scope=book.scope,
                           predicate=_predicate(v, checked), period=v.period,
                           selection=selection,
                           described_as=predicates.describe(checked))
    except Exception as exc:  # scenario errors carry a message and a code
        message = str(getattr(exc, "message", "") or exc)
        raise HTTPException(422, {"error_code": getattr(
            exc, "code", "COHORT_UNRESOLVED"), "message": message}) from exc
    return v, checked, frozen


def _member_ids(book: Book, v: grid.View, frozen: ch.Frozen) -> list[str]:
    g = ch.GRAIN[book.domain_id]
    where = f"{g['period']} = '{frozen.period}'"
    if frozen.predicate:
        where += f" AND ({frozen.predicate})"
    if frozen.selection == ch.BY_OWNER:
        where = (f"{g['period']} = '{frozen.period}' AND {g['owner']} IN "
                 f"(SELECT {g['owner']} FROM {g['relation']} WHERE {where})")
    rows = book.rows(f"SELECT {g['key']} AS k FROM {g['relation']} WHERE "
                     f"{where} ORDER BY 1")
    return [str(r["k"]) for r in rows]


def body_for(book: Book, *, name: str, v: grid.View,
             checked: list[dict[str, Any]], frozen: ch.Frozen,
             source: dict[str, Any], snapshot: bool,
             description: str = "") -> dict[str, Any]:
    spec = grid.SPEC[book.domain_id]
    ids = _member_ids(book, v, frozen)
    if frozen.selection == ch.BY_ROW:
        stats_filters = checked
    else:
        stats_filters = [{"column": v.key, "op": "in", "values": ids[:500]}] \
            if len(ids) <= 500 else checked
    stats = grid.summary(book, v=v, **_bound(stats_filters))
    return {
        "name": name,
        "description": description or frozen.describe(),
        "domain_id": book.domain_id, "release_id": book.release_id,
        "fingerprint": book.fingerprint, "period": v.period,
        "relation": spec["relation"], "grain": spec["noun"],
        "owner_grain": spec["owner_plural"],
        "selection": frozen.selection, "filters": checked,
        "filter_description": predicates.describe(checked),
        "membership_hash": frozen.ref.membership_hash,
        "engine_cohort_id": frozen.ref.cohort_id,
        "predicate_hash": predicates.predicate_hash(
            checked, selection=frozen.selection, period=v.period,
            domain_id=book.domain_id),
        "counts": {"entities": frozen.ref.entity_count,
                   "owners": frozen.owner_count},
        "ead": float(frozen.ref.baseline_ead),
        "ecl": float(frozen.ref.baseline_ecl),
        "stage_mix": stats["stage_mix"], "band_mix": stats["band_mix"],
        "band_dimension": stats["band_dimension"],
        "source": source,
        "snapshot": bool(snapshot and len(ids) <= SNAPSHOT_MAX),
        "member_ids": ids if (snapshot and len(ids) <= SNAPSHOT_MAX) else [],
        "member_ids_preview": ids[:25],
    }


def _bound(filters: list[dict[str, Any]]) -> dict[str, Any]:
    sql, params = predicates.bound(filters)
    return {"where": f"WHERE {sql}" if sql else "", "params": params}


def freeze(book: Book, svc: ObjectService, who: Principal, *, name: str,
           filters: Any, selection: str = ch.BY_ROW,
           source: dict[str, Any] | None = None, snapshot: bool = False,
           description: str = "", tags: list[str] | None = None,
           permissions: dict[str, Any] | None = None,
           seeded: bool = False, owner_id: str = "") -> dict[str, Any]:
    source = dict(source or {"kind": "manual"})
    if source.get("kind") not in SOURCES:
        raise HTTPException(422, {"error_code": "INVALID_SOURCE",
                                  "message": f"source.kind must be one of "
                                             f"{SOURCES}."})
    v, checked, frozen = resolve(book, filters=filters, selection=selection)
    body = body_for(book, name=name, v=v, checked=checked, frozen=frozen,
                    source=source, snapshot=snapshot, description=description)
    return svc.create(
        "cohort", who, body, title=name, domain_id=book.domain_id,
        release_id=book.release_id, fingerprint=book.fingerprint,
        period=v.period, status="ACTIVE", tags=tags or [],
        permissions=permissions, seeded=seeded, owner_id=owner_id,
        lineage={"origin": "frozen", "source": source})


def verify(book: Book, cohort: dict[str, Any]) -> dict[str, Any]:
    """Re-resolve the saved question; say whether the answer is the same rows."""
    body = cohort["body"]
    if body["domain_id"] != book.domain_id:
        return {"status": "WRONG_BOOK", "identical": False,
                "message": "This cohort belongs to the other book."}
    if (body["release_id"] != book.release_id
            or body["fingerprint"] != book.fingerprint):
        return {"status": "RELEASE_MOVED", "identical": False,
                "message": (f"The cohort was frozen on {body['release_id']} "
                            f"and the book now serves {book.release_id}. Its "
                            f"historical membership is kept; refresh it to "
                            f"make a new version on the current data."),
                "saved": {"release_id": body["release_id"],
                          "membership_hash": body["membership_hash"]}}
    if body["period"] not in book.periods:
        return {"status": "PERIOD_UNAVAILABLE", "identical": False,
                "message": f"{body['period']} is not a period of this release."}
    _v, _checked, frozen = resolve(book, filters=body["filters"],
                                   selection=body["selection"],
                                   period=body["period"])
    identical = frozen.ref.membership_hash == body["membership_hash"]
    return {"status": "IDENTICAL" if identical else "MEMBERSHIP_CHANGED",
            "identical": identical,
            "saved_hash": body["membership_hash"],
            "resolved_hash": frozen.ref.membership_hash,
            "entities": frozen.ref.entity_count}


def refresh(book: Book, svc: ObjectService, who: Principal,
            cohort: dict[str, Any]) -> dict[str, Any]:
    """The same question at the latest data: a NEW VERSION, never a mutation."""
    body = cohort["body"]
    v, checked, frozen = resolve(book, filters=body["filters"],
                                 selection=body["selection"])
    new_body = body_for(book, name=body["name"], v=v, checked=checked,
                        frozen=frozen, source=body["source"],
                        snapshot=body.get("snapshot", False),
                        description=body.get("description", ""))
    return svc.revise(cohort["object_id"], who, body=new_body,
                      reason=f"refreshed to {v.period} on {book.release_id}",
                      release_id=book.release_id, fingerprint=book.fingerprint,
                      period=v.period, status="ACTIVE")


def as_scenario_filters(cohort: dict[str, Any]) -> dict[str, Any]:
    """What the engine needs to re-freeze exactly this population."""
    body = cohort["body"]
    return {"filters": body["filters"], "selection": body["selection"],
            "period": body["period"], "membership_hash": body["membership_hash"],
            "cohort_object_id": cohort["object_id"],
            "cohort_version": cohort["version"]}


__all__ = ["SNAPSHOT_MAX", "SOURCES", "as_scenario_filters", "freeze",
           "refresh", "resolve", "verify"]
