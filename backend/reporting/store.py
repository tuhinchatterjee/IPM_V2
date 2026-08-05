"""
The archive of generated committee packs.

Every pack that is generated is written to disk and indexed, so the Archive
screen lists real artefacts rather than a table of what was notionally produced.
Re-serving an archived pack returns the exact bytes that were issued — a board
pack cannot be allowed to change after it has been tabled, so the file is stored
rather than regenerated on demand.

Layout under `<upload_dir>/reports`:

  index/<id>.json   metadata — type, quarter, format, size, headline figures
  files/<id>.<ext>  the issued document itself

Metadata and payload are separate files so the index can be listed without
reading megabytes of PDF off disk.
"""

import json
import logging
import threading
from datetime import UTC, datetime
from pathlib import Path

import backend.cockpit_data as cd
from backend import data_loader as dl
from backend.config import settings
from backend.reporting import content as rc
from backend.reporting import writers

logger = logging.getLogger(__name__)

_lock = threading.RLock()

# The archive is not a growth area — packs are quarterly. This cap simply stops a
# stuck loop from filling the disk.
MAX_PACKS = 200


def _root() -> Path:
    path = Path(settings.upload_dir) / "reports"
    (path / "index").mkdir(parents=True, exist_ok=True)
    (path / "files").mkdir(parents=True, exist_ok=True)
    return path


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _read(path: Path):
    # A missing entry is an ordinary answer to "does this pack exist" — only a
    # file that is present but unreadable is worth a traceback.
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.exception("report store: unreadable index entry %s", path)
        return None


def _write(path: Path, payload: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(path)


def _next_id(folder: Path) -> int:
    ids = [int(p.stem) for p in folder.glob("*.json") if p.stem.isdigit()]
    return (max(ids) + 1) if ids else 1


def _headline(report: dict) -> dict:
    """The few figures the Archive row shows, lifted from the assembled report so
    the list never has to rebuild a pack to describe it."""
    return {
        "section_count": len(report.get("sections", [])),
        "finding_count": len(report.get("findings", [])),
        "action_count": len(report.get("actions", [])),
        "remediation_count": len(report.get("remediation", [])),
        "high_severity_count": report.get("high_severity_count", 0),
    }


# ------------------------------------------------------------------- writing

def chart_context(quarter: str | None = None) -> dict:
    """The one series the chart renderers cannot derive from the quarter alone.

    Built here rather than at the call site so a caller cannot forget it and
    quietly ship a pack with the health trend missing.
    """
    return {"health_history": cd.compute_index_history(quarter or dl.DEFAULT_QUARTER)}


def generate(report_type: str = "smc", quarter: str | None = None, fmt: str = "pdf",
             prepared_by: str = "", context: dict | None = None, archive: bool = True) -> dict:
    """Build, render and (by default) archive one pack.

    Returns the archive record with the document bytes attached under `data`, so
    a caller that only wants to hand the file straight to the browser does not
    have to read it back off disk.
    """
    quarter = quarter or dl.DEFAULT_QUARTER
    report = rc.build_report(report_type, quarter, prepared_by=prepared_by)
    if context is None:
        context = chart_context(quarter)
    data, filename, mime = writers.write(report, fmt, context)

    record = {
        "id": 0,
        "type": report["type"],
        "type_label": report["short_title"],
        "title": report["title"],
        "quarter": quarter,
        "format": fmt,
        "format_label": writers.FORMATS.get(fmt, writers.FORMATS["pdf"])["label"],
        "filename": filename,
        "mime": mime,
        "size_bytes": len(data),
        "prepared_by": prepared_by,
        "generated_at": _now(),
        "headline": _headline(report),
    }
    if archive:
        record = _persist(record, data)
    return {**record, "data": data}


def _persist(record: dict, data: bytes) -> dict:
    with _lock:
        root = _root()
        pid = _next_id(root / "index")
        record = {**record, "id": pid}
        ext = writers.FORMATS.get(record["format"], writers.FORMATS["pdf"])["extension"]
        (root / "files" / f"{pid}.{ext}").write_bytes(data)
        _write(root / "index" / f"{pid}.json", record)
        logger.info("reports: archived pack %s (%s %s %s, %d bytes)",
                    pid, record["type"], record["quarter"], record["format"], len(data))
        _prune()
    return record


def _prune() -> None:
    """Drop the oldest packs once the cap is passed."""
    packs = list_packs(limit=0)
    for stale in packs[MAX_PACKS:]:
        delete(stale["id"])


# ------------------------------------------------------------------- reading

def list_packs(report_type: str | None = None, quarter: str | None = None,
               limit: int = 50) -> list[dict]:
    """Archived packs, newest first. `limit=0` returns everything."""
    out = []
    for path in (_root() / "index").glob("*.json"):
        rec = _read(path)
        if rec is None:
            continue
        if report_type and rec["type"] != report_type:
            continue
        if quarter and rec["quarter"] != quarter:
            continue
        out.append(rec)
    out.sort(key=lambda r: r["id"], reverse=True)
    return out if limit == 0 else out[:limit]


def get(pack_id: int) -> dict | None:
    return _read(_root() / "index" / f"{int(pack_id)}.json")


def load(pack_id: int) -> tuple[bytes, str, str] | None:
    """(bytes, filename, mime) for an archived pack — the exact document that was
    issued, not a fresh render of it."""
    rec = get(pack_id)
    if rec is None:
        return None
    ext = writers.FORMATS.get(rec["format"], writers.FORMATS["pdf"])["extension"]
    path = _root() / "files" / f"{int(pack_id)}.{ext}"
    if not path.exists():
        logger.warning("reports: index entry %s has no payload at %s", pack_id, path)
        return None
    return path.read_bytes(), rec["filename"], rec["mime"]


def delete(pack_id: int) -> bool:
    with _lock:
        root = _root()
        index = root / "index" / f"{int(pack_id)}.json"
        rec = _read(index) if index.exists() else None
        if rec is None:
            return False
        ext = writers.FORMATS.get(rec["format"], writers.FORMATS["pdf"])["extension"]
        (root / "files" / f"{int(pack_id)}.{ext}").unlink(missing_ok=True)
        index.unlink(missing_ok=True)
        return True


# --------------------------------------------------------------------- stats

def summary() -> dict:
    """Counts for the Archive header."""
    packs = list_packs(limit=0)
    return {
        "total": len(packs),
        "by_type": {rt: sum(1 for p in packs if p["type"] == rt) for rt in rc.REPORT_TYPES},
        "by_format": {f: sum(1 for p in packs if p["format"] == f) for f in writers.FORMATS},
        "total_bytes": sum(p["size_bytes"] for p in packs),
        "latest": packs[0] if packs else None,
    }
