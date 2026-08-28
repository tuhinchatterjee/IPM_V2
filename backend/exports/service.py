"""
Producing one workbook, end to end.

The single place that knows the order of operations for an export: decide
whether it may happen, read the persisted run, build the file, audit what was
served. The endpoint below this is thin on purpose — it turns an `ExportError`
into a status code and a JSON body and does nothing else — so the same sequence
is exercised by the tests without a web server, and there is one implementation
of "what happens when somebody downloads an analysis" rather than two.

Synchronous, and why
--------------------
§37 offers a job API for potentially large packs: POST a job, poll its status,
fetch the file. This implementation generates synchronously and guards size
instead, which is a deliberate deviation recorded in the report:

* the ceiling is enforced before any reading happens — a population above
  `MAX_INLINE_POPULATION_ROWS` is never loaded, so the expensive case is
  refused rather than survived;
* generation is bounded by `GENERATION_TIMEOUT_SECONDS`, and a pack that
  exceeds it fails with an explanation rather than holding a worker;
* the browser calls this with `fetch`, shows "Preparing workbook…" while it
  waits and saves the blob when it arrives, so the interface never freezes —
  which is the user-visible requirement §37 actually states.

A job queue with no worker infrastructure behind it would be a status endpoint
that lies. When this product grows a task runner, `generate()` is the function
that runs inside the job, unchanged.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from backend.api.permissions import Principal
from backend.exports import audit, authorize, calculation, gather, results
from backend.exports import plan as planning
from backend.exports import population as populations
from backend.exports import profile as profiling
from backend.exports.contract import (
    CALCULATION_PACK,
    GENERATION_TIMEOUT_SECONDS,
    RESULTS,
    ExportError,
    NotExportable,
    TooLarge,
    Workbook,
)

logger = logging.getLogger(__name__)


class Denied(ExportError):
    """The caller may not have this export."""

    def __init__(self, message: str):
        super().__init__("forbidden", message, status=403)


class TookTooLong(ExportError):
    def __init__(self, message: str):
        super().__init__("export_timeout", message, status=504)


@dataclass
class Served:
    """A workbook, and the audit row that records serving it."""

    workbook: Workbook
    record_id: int | None
    duration_ms: int


def export(run_id: int, *, kind: str, principal: Principal,
           version: int | None = None, user_name: str = "") -> Served:
    """Authorise, generate and audit one export.

    Raises `ExportError` subclasses for every refusal, which the route turns
    into a status code and a message. Nothing here returns a bare 500: a run
    that does not exist, a result that was never persisted, a permission that is
    not held and a workbook that is too large are four different answers and the
    user is told which one they got.
    """
    started = time.monotonic()
    decision = authorize.decide(principal, kind=kind, run_id=run_id)
    if not decision.allowed:
        audit.record(audit.Entry(
            kind=kind, object_id=str(run_id), run_id=run_id,
            user_id=principal.user_id, role=principal.role.value,
            status=audit.DENIED, authorization=decision.basis,
            reason=decision.reason,
        ))
        raise Denied(decision.reason)

    try:
        pack = gather.pack_for(run_id, version=version,
                               user_id=principal.user_id, user_name=user_name)
    except ExportError as e:
        audit.record(audit.Entry(
            kind=kind, object_id=str(run_id), run_id=run_id,
            trace_version=version, user_id=principal.user_id,
            role=principal.role.value, status=audit.FAILED,
            authorization=decision.basis, reason=e.message,
        ))
        raise

    try:
        workbook = generate(pack, kind=kind, decision=decision, started=started)
    except ExportError as e:
        audit.record(audit.Entry(
            kind=kind, object_id=str(run_id), run_id=run_id,
            trace_version=pack.version, user_id=principal.user_id,
            role=principal.role.value, status=audit.FAILED,
            authorization=decision.basis, reason=e.message,
            datasets=[s.dataset for s in pack.sources],
        ))
        raise
    except Exception as e:  # noqa: BLE001 - a generation bug is still an answer
        logger.exception("Workbook generation failed for run %s", run_id)
        audit.record(audit.Entry(
            kind=kind, object_id=str(run_id), run_id=run_id,
            trace_version=pack.version, user_id=principal.user_id,
            role=principal.role.value, status=audit.FAILED,
            authorization=decision.basis, reason=str(e),
            datasets=[s.dataset for s in pack.sources],
        ))
        raise ExportError(
            "export_failed",
            "The workbook could not be generated. The analysis itself is "
            "unaffected — it is on screen and on its Trace. This failure has "
            "been recorded for the CreditProbe team.",
            status=500,
        ) from e

    duration = int((time.monotonic() - started) * 1000)
    record_id = audit.record(audit.Entry(
        kind=kind,
        object_id=str(run_id),
        run_id=run_id,
        trace_version=pack.version,
        user_id=principal.user_id,
        role=principal.role.value,
        status=audit.ALLOWED,
        authorization=decision.basis,
        filename=workbook.filename,
        content_hash=audit.content_hash(workbook.content),
        size_bytes=workbook.size,
        row_count=len(pack.rows),
        duration_ms=duration,
        datasets=[s.dataset for s in pack.sources],
        redactions=list(workbook.manifest.get("redactions") or []),
        detail=dict(workbook.manifest),
    ))
    return Served(workbook=workbook, record_id=record_id, duration_ms=duration)


def generate(pack: gather.Pack, *, kind: str,
             decision: authorize.Decision,
             started: float | None = None) -> Workbook:
    """Build the workbook itself. No authorisation, no audit — just the file.

    Separated so a test can build a workbook from a pack without a principal,
    and so a future job runner has one function to call.
    """
    if kind == RESULTS:
        return results.build(pack)
    if kind != CALCULATION_PACK:
        raise NotExportable(f"'{kind}' is not an export this product produces.")

    view = planning.read(pack.ir, kernel_steps=pack.query.get("kernel_steps"))
    profiles = profiling.profiles_for(pack, view)
    _check_clock(started, "profiling the source datasets")

    extract = None
    redactions: list[str] = []
    if decision.row_level:
        extract = populations.extract_for(pack, view)
        if extract.omitted:
            redactions.append(f"Population extract: {extract.omitted}")
    else:
        redactions.append(
            "The row-level population is not included: your role carries access "
            "to the calculation and its lineage, not to the underlying rows."
        )
    _check_clock(started, "reading the analytical population")

    workbook = calculation.build(pack, profiles=profiles, extract=extract,
                                 redactions=redactions + decision.redactions)
    _check_clock(started, "writing the workbook")
    return workbook


def _check_clock(started: float | None, doing: str) -> None:
    if started is None:
        return
    if time.monotonic() - started > GENERATION_TIMEOUT_SECONDS:
        raise TookTooLong(
            f"This workbook took longer than {GENERATION_TIMEOUT_SECONDS} "
            f"seconds while {doing}, so it was stopped rather than left "
            "running. The results workbook is smaller and should succeed; if "
            "the full pack is needed for this analysis, ask for a governed "
            "extract instead."
        )


def too_large(rows: int, ceiling: int) -> TooLarge:
    return TooLarge(
        f"This result is {rows:,} rows, above the {ceiling:,}-row ceiling for a "
        "workbook. Nothing was truncated to fit: ask for a governed extract of "
        "this run instead."
    )
