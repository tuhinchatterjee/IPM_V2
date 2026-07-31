"""
Model versions and immutable calculation runs.

Two design principles, both taken straight from the workbook's ethos:

  * Versioned inputs with a parent pointer, so a v5.1 -> v6 diff is queryable
    rather than a matter of memory.
  * Immutable runs carrying a FULL input snapshot. A run never references live
    inputs, so a figure quoted to a regulator can always be reproduced exactly,
    even after the inputs have moved on. Results are recomputed from the snapshot
    on read rather than stored, which keeps the store small and guarantees the
    stored inputs really do reproduce the stored headline.

Persistence is a JSON file per version and per run under `<upload_dir>/climate`.
That deliberately avoids a schema migration: the payloads are documents, not
relations, and the module has to work on a laptop with no Postgres running.
"""

import json
import logging
import threading
from datetime import UTC, datetime
from pathlib import Path

from backend.climate import checks, defaults, engine
from backend.config import settings

logger = logging.getLogger(__name__)

STATUS_DRAFT = "draft"
STATUS_FINAL = "final"
STATUS_ARCHIVED = "archived"

_lock = threading.RLock()
_seeded = False


def _root() -> Path:
    path = Path(settings.upload_dir) / "climate"
    (path / "versions").mkdir(parents=True, exist_ok=True)
    (path / "runs").mkdir(parents=True, exist_ok=True)
    return path


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _read(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.exception("climate store: unreadable document %s", path)
        return None


def _write(path: Path, payload: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=False), encoding="utf-8")
    tmp.replace(path)


def _next_id(folder: Path) -> int:
    ids = [int(p.stem) for p in folder.glob("*.json") if p.stem.isdigit()]
    return (max(ids) + 1) if ids else 1


# ------------------------------------------------------------------- seeding

def ensure_seeded() -> None:
    """Create the bundled v5.1 Oman baseline the first time the module is used."""
    global _seeded
    with _lock:
        if _seeded:
            return
        folder = _root() / "versions"
        if not any(folder.glob("*.json")):
            create_version(
                defaults.default_model(),
                name=f"{defaults.MODEL_NAME} {defaults.MODEL_VERSION_LABEL}",
                country="Oman", created_by="bundled", status=STATUS_FINAL,
                note="Bundled baseline — reproduces the Oman Climate Stressed PD v5.1 workbook "
                     "to full double precision.",
            )
        _seeded = True


# ------------------------------------------------------------ model versions

def create_version(model: dict, name: str, country: str = "", created_by: str = "",
                   parent_id: int | None = None, status: str = STATUS_DRAFT,
                   note: str = "") -> dict:
    with _lock:
        folder = _root() / "versions"
        vid = _next_id(folder)
        record = {
            "id": vid, "name": name, "country": country or model.get("country", ""),
            "status": status, "parent_version_id": parent_id, "created_by": created_by,
            "created_at": _now(), "updated_at": _now(), "note": note,
            "engine_version": engine.ENGINE_VERSION, "model": model,
        }
        _write(folder / f"{vid}.json", record)
        logger.info("climate: created model version %s (%s)", vid, name)
        return record


def clone_version(version_id: int, name: str, created_by: str = "", note: str = "") -> dict:
    src = get_version(version_id)
    if src is None:
        raise KeyError(f"model version {version_id} not found")
    return create_version(src["model"], name=name, country=src["country"], created_by=created_by,
                          parent_id=version_id, status=STATUS_DRAFT,
                          note=note or f"Cloned from version {version_id} ({src['name']}).")


def get_version(version_id: int) -> dict | None:
    ensure_seeded()
    rec = _read(_root() / "versions" / f"{int(version_id)}.json")
    if rec and rec.get("model"):
        defaults.normalise_model(rec["model"])
    return rec


def list_versions() -> list[dict]:
    """Version metadata, newest first. The model payload is stripped — callers that
    need the inputs ask for the version by id."""
    ensure_seeded()
    out = []
    for path in (_root() / "versions").glob("*.json"):
        rec = _read(path)
        if rec:
            out.append({k: v for k, v in rec.items() if k != "model"})
    out.sort(key=lambda r: r["id"], reverse=True)
    return out


def update_version(version_id: int, model: dict, note: str = "") -> dict:
    """Overwrite the inputs of a DRAFT version. Final versions are immutable: the
    caller must clone first, which is what keeps the audit trail honest."""
    with _lock:
        rec = get_version(version_id)
        if rec is None:
            raise KeyError(f"model version {version_id} not found")
        if rec["status"] == STATUS_FINAL:
            raise ValueError("a final version cannot be edited — clone it first")
        rec["model"] = model
        rec["updated_at"] = _now()
        if note:
            rec["note"] = note
        _write(_root() / "versions" / f"{version_id}.json", rec)
        return rec


def set_status(version_id: int, status: str) -> dict:
    """Promote or archive a version. Promotion to final is blocked while any
    quality check is failing."""
    with _lock:
        rec = get_version(version_id)
        if rec is None:
            raise KeyError(f"model version {version_id} not found")
        if status == STATUS_FINAL:
            result = engine.calculate(rec["model"])
            summary = checks.summarise(checks.run_checks(result, rec["model"]))
            if not summary["can_finalise"]:
                failing = ", ".join(str(c["id"]) for c in summary["failures"])
                raise ValueError(f"cannot finalise: quality check(s) {failing} are failing")
        rec["status"] = status
        rec["updated_at"] = _now()
        _write(_root() / "versions" / f"{version_id}.json", rec)
        return rec


def delete_version(version_id: int) -> bool:
    with _lock:
        path = _root() / "versions" / f"{int(version_id)}.json"
        if not path.exists():
            return False
        path.unlink()
        return True


# --------------------------------------------------------------------- runs

def calculate_run(version_id: int, created_by: str = "", note: str = "") -> dict:
    """Calculate a version and persist an immutable run with a full input snapshot."""
    rec = get_version(version_id)
    if rec is None:
        raise KeyError(f"model version {version_id} not found")

    model = rec["model"]
    result = engine.calculate(model)
    check_rows = checks.run_checks(result, model)
    summary = checks.summarise(check_rows)

    with _lock:
        folder = _root() / "runs"
        rid = _next_id(folder)
        record = {
            "id": rid, "model_version_id": version_id, "model_version_name": rec["name"],
            "created_at": _now(), "created_by": created_by, "note": note,
            "engine_version": engine.ENGINE_VERSION,
            "snapshot": model,
            "headline": _headline(result, summary),
            "checks": check_rows,
            "check_summary": {k: v for k, v in summary.items()
                              if k not in ("failures", "unexpected")},
        }
        _write(folder / f"{rid}.json", record)
        logger.info("climate: stored run %s for version %s", rid, version_id)
    return {**record, "result": result}


def _headline(result: dict, summary: dict) -> dict:
    grade = result["reference_grade"]
    rows = [r for r in result["grid"] if r["grade"] == grade]
    worst = max(rows, key=lambda r: r["multiple"]) if rows else None
    return {
        "horizon_year": result["horizon_year"], "theta": result["theta"], "k": result["k"],
        "reference_grade": grade,
        "cells": len(result["grid"]),
        "max_multiple": worst["multiple"] if worst else 0.0,
        "worst_sector": worst["sector"] if worst else "",
        "worst_scenario": worst["scenario"] if worst else "",
        "max_cost_ratio": result["max_cost_ratio"],
        "checks_passed": summary["passed"], "checks_total": summary["total"],
        "failure_count": summary["failure_count"],
        "can_finalise": summary["can_finalise"],
        "structural_pair_ok": summary["structural_pair_ok"],
    }


def get_run(run_id: int, with_result: bool = True) -> dict | None:
    """Load a run. The result is recomputed from the stored snapshot, so what you
    see is provably what those inputs produce."""
    rec = _read(_root() / "runs" / f"{int(run_id)}.json")
    if rec is None:
        return None
    if rec.get("snapshot"):
        defaults.normalise_model(rec["snapshot"])
    if with_result:
        rec = {**rec, "result": engine.calculate(rec["snapshot"])}
    return rec


def list_runs(version_id: int | None = None, limit: int = 50) -> list[dict]:
    out = []
    for path in (_root() / "runs").glob("*.json"):
        rec = _read(path)
        if rec is None:
            continue
        if version_id is not None and rec["model_version_id"] != int(version_id):
            continue
        out.append({k: v for k, v in rec.items() if k not in ("snapshot", "checks")})
    out.sort(key=lambda r: r["id"], reverse=True)
    return out[:limit]


def delete_run(run_id: int) -> bool:
    with _lock:
        path = _root() / "runs" / f"{int(run_id)}.json"
        if not path.exists():
            return False
        path.unlink()
        return True


# ------------------------------------------------------------- convenience

def default_version_id() -> int:
    """The version the UI opens on: the most recent final one, else the newest."""
    versions = list_versions()
    if not versions:
        ensure_seeded()
        versions = list_versions()
    final = [v for v in versions if v["status"] == STATUS_FINAL]
    return (final[0] if final else versions[0])["id"]


def latest_result(version_id: int | None = None) -> tuple[dict, dict, list[dict]]:
    """(model, result, checks) for a version — the read path the UI uses on every
    page load. Calculation is ~40 cells of arithmetic plus a 280-cell grid, so it
    is cheaper than a round trip to a cache."""
    vid = version_id or default_version_id()
    rec = get_version(vid)
    if rec is None:
        model = defaults.default_model()
    else:
        model = rec["model"]
    result = engine.calculate(model)
    return model, result, checks.run_checks(result, model)
