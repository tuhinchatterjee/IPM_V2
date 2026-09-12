"""
`execute_analysis`: validate exactly, execute exactly, repair never.

The single rule
---------------
The code that runs is byte-for-byte the code the analyst submitted. This
module parses an AST to decide whether to ALLOW it; the parse result is never
what executes. There is no path here that rewrites a filter, removes a join,
substitutes a column that looked close, drops a step to fit a bound, or
computes a business number itself. Every one of those turns a wrong analysis
into a confident one.

When something is wrong, this returns a failure packet naming the exact check
and the exact step, and the analyst writes the replacement. That is the only
repair mechanism V4 has.

Isolation is the actual security boundary, not the allowlists. The DuckDB
session is built with file access enabled, then locked before any submitted
SQL is admitted (V3's `sql.open_session` does this and V4 reuses it). Python
runs in a separate process jail or is reported UNAVAILABLE -- it is never
quietly evaluated in this process.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any

from backend.cockpit_agentic import sql as v3_sql
from backend.cockpit_v4 import derivation as deriv
from backend.cockpit_v4.contracts import ExecutionSubmission, Rejection, Step
from backend.cockpit_v4.provider import code_digest
from backend.cockpit_v4.sqlbind import (BindFailure, parameter_argument,
                                        placeholders, prove_bindable)
from backend.cockpit_v4.states import (PYTHON_UNAVAILABLE, SECURITY_DENIED,
                                       SQL_RUNTIME, SQL_VALIDATION)

#: Checks are named so a failure says WHICH one refused, not "invalid query".
CHECK_STRUCTURE = "sql_structure"
CHECK_AUTHORIZATION = "relation_authorization"
CHECK_BIND = "bind"
CHECK_GRAIN = "join_grain"
CHECK_RUNTIME = "runtime"
CHECK_SANDBOX = "sandbox"


def claim_guide(artifact_id: str, columns: list[str], row_ids: list[str],
                row_count: int) -> dict[str, Any]:
    """The evidence contract, sent with every successful result.

    This is a CONTRACT, not reasoning assistance. It exists because the
    alternative is discovery by trial and error, and a live run spent two
    rejected answers on that: told only that its claims must reference
    evidence, it referenced rows named "all sectors" and "top 4 sectors",
    which no result contains. The rules below are exactly what the validator
    enforces, stated once, before the answer is written.
    """
    last = row_ids[-1] if row_ids else "r0"
    return {
        "artifact_id": artifact_id,
        "columns": list(columns),
        "row_ids": list(row_ids),
        "row_count": row_count,
        "direct_value": (
            "A number that appears in one result cell: send 'evidence' with "
            "this artifact_id, the row_id and the column_id. Send the EXACT "
            "stored value and use display_precision for how it should read."),
        "calculated_value": (
            "A number you worked out from the result -- a total across rows, "
            "a share of a total, a difference, a growth rate: send "
            "'derivation' instead of 'evidence', naming the operation and "
            "the real rows it consumes. CreditProbe recomputes it and "
            "refuses the answer if the arithmetic does not hold."),
        "never": (
            "Do NOT invent a row to point at. There is no 'total', 'all "
            "sectors' or 'top 5' row unless one is listed in row_ids above. "
            "A total is a derivation over the real rows."),
        "operations": deriv.describe(),
        "example_total": {
            "claim_id": "total_x", "unit": "INR crore",
            "derivation": {"operation": "sum", "operands": [
                {"artifact_id": artifact_id,
                 "column_id": (columns[-1] if columns else "value"),
                 "row_ids": list(row_ids)}]}},
        "example_share": {
            "claim_id": "top_share", "unit": "percent",
            "derivation": {"operation": "percentage", "operands": [
                {"artifact_id": artifact_id,
                 "column_id": (columns[-1] if columns else "value"),
                 "row_ids": row_ids[:1] or ["r0"]},
                {"artifact_id": artifact_id,
                 "column_id": (columns[-1] if columns else "value"),
                 "row_ids": list(row_ids) or [last]}]}},
    }


@dataclass
class StepResult:
    step_id: str
    status: str
    language: str
    code_digest: str
    purpose: str
    columns: list[str] = field(default_factory=list)
    row_count: int = 0
    preview: list[dict[str, Any]] = field(default_factory=list)
    #: The published id of each preview row, aligned with `preview`. These
    #: are what a numeric claim references. They are published rather than
    #: left to be guessed because a live run, given no ids, invented row
    #: labels ("all sectors", "top 4 sectors") and had its answer refused.
    row_ids: list[str] = field(default_factory=list)
    truncated: bool = False
    artifact_id: str = ""
    warnings: list[str] = field(default_factory=list)
    error_code: str = ""
    failed_check: str = ""
    message: str = ""
    elapsed_ms: int = 0
    #: "bind" or "runtime". A query that never bound did not execute, and
    #: the trace must not say it did.
    phase: str = ""
    engine_detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        out = {"step_id": self.step_id, "status": self.status,
               "language": self.language, "purpose": self.purpose,
               "executed_code_digest": self.code_digest,
               "elapsed_ms": self.elapsed_ms}
        if self.status == "ok":
            out.update({"columns": self.columns, "row_count": self.row_count,
                        "preview": self.preview, "row_ids": self.row_ids,
                        "preview_truncated": self.truncated,
                        "artifact_id": self.artifact_id,
                        "how_to_cite_these_numbers": claim_guide(
                            self.artifact_id, self.columns, self.row_ids,
                            self.row_count)})
        else:
            out.update({"error_code": self.error_code,
                        "failed_check": self.failed_check,
                        "message": self.message,
                        "phase": self.phase or ("bind"
                                                if self.failed_check ==
                                                CHECK_BIND else "runtime"),
                        "executed": self.failed_check not in
                        (CHECK_BIND, CHECK_STRUCTURE, CHECK_AUTHORIZATION)})
        if self.warnings:
            out["warnings"] = self.warnings
        return out


@dataclass
class BatchResult:
    submission_id: str
    status: str
    steps: list[StepResult]
    validated_all: bool
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"submission_id": self.submission_id, "status": self.status,
                "validated_whole_batch_before_running": self.validated_all,
                "steps": [s.to_dict() for s in self.steps],
                **({"message": self.message} if self.message else {})}


class StepFailed(Exception):
    def __init__(self, code: str, check: str, message: str, *,
                 detail: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.check = check
        self.message = message
        #: Operator-only. The engine's own diagnostic, for the trace.
        self.detail = dict(detail or {})


_RELATION_IN_SQL = re.compile(
    r"\b(?:from|join)\s+([A-Za-z_][A-Za-z0-9_]*)", re.IGNORECASE)

#: `WITH name AS (` and `, name AS (`. A common table expression is a name the
#: query defines for itself, not a relation it reads from the release --
#: treating one as an unauthorized table would refuse perfectly legitimate
#: analyst SQL, which is a worse failure than the check is worth.
_CTE_NAME = re.compile(
    r"(?:\bwith\b|,)\s*([A-Za-z_][A-Za-z0-9_]*)\s+as\s*\(", re.IGNORECASE)


def _local_names(sql: str) -> set[str]:
    """Names the query defines itself: CTEs and derived-table aliases."""
    names = {m.lower() for m in _CTE_NAME.findall(sql)}
    # `) alias` and `) AS alias` after a derived table.
    names |= {m.lower() for m in re.findall(
        r"\)\s*(?:as\s+)?([A-Za-z_][A-Za-z0-9_]*)", sql, re.IGNORECASE)}
    return names


@dataclass
class ExecutionService:
    """Validates and runs one submission against the pinned release."""

    session: Any
    scope: Any
    catalog: Any
    store: Any
    run_id: str
    tenant_id: str
    release_id: str
    limits: Any
    python_runner: Any = None
    #: Result artifacts produced in this run, by step id, for dependencies.
    artifacts: dict[str, str] = field(default_factory=dict)

    # -- static validation of the WHOLE batch ---------------------------

    def validate_batch(self, submission: ExecutionSubmission) -> None:
        """Every step is checked before ANY step runs.

        A batch whose fourth step names a table that does not exist should
        not have run its first three: a partial execution leaves artifacts an
        analyst may reasonably think are complete.
        """
        if not submission.intent.may_execute:
            raise Rejection(
                SECURITY_DENIED,
                f"Execution is available only for a declared DATA_ANALYSIS "
                f"owned by COCKPIT with no BLOCKING ambiguity. This "
                f"submission declared {submission.intent.query_mode} / "
                f"{submission.intent.owner}"
                + (f" and left "
                   f"{list(submission.intent.blocking_ambiguities)} "
                   f"unresolved. A resolution you have already made belongs "
                   f"in resolved_assumptions or canonical_mappings, which do "
                   f"not stop execution."
                   if submission.intent.blocking_ambiguities else "."),
                field_path="intent")
        bound: list[str] = []
        deferred: list[str] = []
        for step in submission.steps:
            if step.language == "sql":
                self._validate_sql(step)
                if self._bindable_now(step):
                    self._prove_bindable(step)
                    bound.append(step.step_id)
                else:
                    deferred.append(step.step_id)
            else:
                self._validate_python(step)
        return {"bound_now": bound, "bound_at_run_time": deferred}

    @staticmethod
    def _bindable_now(step: Step) -> bool:
        """Whether this step can be bound before anything has run.

        A SQL step in V4 is self-contained: earlier step outputs are not
        registered as relations, so a query that needs one carries it as a
        CTE. A step that nonetheless declares a dependency is bound
        immediately before it runs instead, and the validation message says
        so rather than implying a proof that was not obtained.
        """
        return not (step.depends_on_step_ids or step.input_artifact_ids)

    def _prove_bindable(self, step: Step) -> None:
        """DuckDB must resolve the query, or this is not a validated query.

        Announcing "validated" and then failing the binder was the defect:
        two true statements in the wrong order. The proof costs an EXPLAIN,
        which executes nothing.
        """
        try:
            prove_bindable(step.code, self.session, parameters=step.parameters)
        except BindFailure as exc:
            raise Rejection(
                SQL_VALIDATION,
                f"step {step.step_id} did not bind: {exc.message} Nothing "
                f"was executed and nothing was repaired.",
                field_path=f"steps.{step.step_id}.code",
                detail={"failed_check": CHECK_BIND, **exc.detail()}) from exc

    def _validate_sql(self, step: Step) -> None:
        try:
            v3_sql.check_structure(step.code)
        except v3_sql.SqlRejected as exc:
            raise Rejection(
                SQL_VALIDATION,
                f"step {step.step_id}: {exc}",
                field_path=f"steps.{step.step_id}.code",
                detail={"failed_check": CHECK_STRUCTURE}) from exc
        except Exception as exc:  # noqa: BLE001 - a parse failure is a refusal
            raise Rejection(
                SQL_VALIDATION,
                f"step {step.step_id}: the SQL could not be parsed: {exc}",
                field_path=f"steps.{step.step_id}.code",
                detail={"failed_check": CHECK_STRUCTURE}) from exc

        authorized = set(self.session.relations) if self.session else set()
        named = {m.lower() for m in _RELATION_IN_SQL.findall(step.code)}
        # Names the query defines for itself, and step outputs registered as
        # views, are legitimate inputs rather than unauthorized tables.
        named -= _local_names(step.code)
        named -= {a.lower() for a in self.artifacts}
        unknown = {n for n in named
                   if n not in {r.lower() for r in authorized}}
        if unknown and authorized:
            raise Rejection(
                SQL_VALIDATION,
                f"step {step.step_id} names {sorted(unknown)}, which are not "
                f"authorized relations in this release. The authorized "
                f"relations are {sorted(authorized)}. Nothing was "
                f"substituted.",
                field_path=f"steps.{step.step_id}.code",
                detail={"failed_check": CHECK_AUTHORIZATION,
                        "authorized_relations": sorted(authorized)})

    def _validate_python(self, step: Step) -> None:
        if self.python_runner is None or not getattr(
                self.python_runner, "available", False):
            raise Rejection(
                PYTHON_UNAVAILABLE,
                f"step {step.step_id} is Python and no isolated Python "
                f"runner is available in this runtime. The step was NOT "
                f"rewritten as SQL and nothing was executed. Either submit "
                f"SQL deliberately, or report the capability as unavailable.",
                field_path=f"steps.{step.step_id}.language",
                detail={"failed_check": CHECK_SANDBOX})
        check = getattr(self.python_runner, "validate", None)
        if callable(check):
            problem = check(step.code)
            if problem:
                raise Rejection(
                    SECURITY_DENIED,
                    f"step {step.step_id}: {problem}",
                    field_path=f"steps.{step.step_id}.code",
                    detail={"failed_check": CHECK_SANDBOX})

    # -- execution -------------------------------------------------------

    def run_batch(self, submission: ExecutionSubmission, *,
                  submission_id: str, deadline_seconds: float,
                  on_step: Any = None) -> BatchResult:
        """Run the validated batch serially, stopping dependents on failure."""
        results: list[StepResult] = []
        failed: set[str] = set()

        for step in submission.steps:
            if callable(on_step):
                on_step("started", step, None)
            blocked = [d for d in step.depends_on_step_ids if d in failed]
            if blocked:
                result = StepResult(
                    step_id=step.step_id, status="not_run",
                    language=step.language, code_digest=code_digest(step.code),
                    purpose=step.purpose, error_code="DEPENDENCY_FAILED",
                    failed_check="dependency",
                    message=(f"not run: it depends on {blocked}, which "
                             f"failed. Earlier successful steps are "
                             f"preserved."))
                results.append(result)
                failed.add(step.step_id)
                if callable(on_step):
                    on_step("skipped", step, result)
                continue

            remaining = deadline_seconds - sum(
                r.elapsed_ms for r in results) / 1000.0
            budget = max(0.5, min(self.limits.step_seconds, remaining))
            started = time.monotonic()
            try:
                result = self._run_step(step, deadline_seconds=budget)
            except StepFailed as exc:
                result = StepResult(
                    step_id=step.step_id, status="failed",
                    language=step.language, code_digest=code_digest(step.code),
                    purpose=step.purpose, error_code=exc.code,
                    failed_check=exc.check, message=exc.message,
                    phase="bind" if exc.check == CHECK_BIND else "runtime",
                    engine_detail=dict(exc.detail))
                failed.add(step.step_id)
            result.elapsed_ms = int((time.monotonic() - started) * 1000)
            results.append(result)
            if callable(on_step):
                on_step("completed" if result.status == "ok" else "failed",
                        step, result)
            if result.status != "ok":
                # Stop the batch. Later steps that did not depend on this one
                # are reported not_run rather than silently omitted.
                for later in submission.steps[len(results):]:
                    results.append(StepResult(
                        step_id=later.step_id, status="not_run",
                        language=later.language,
                        code_digest=code_digest(later.code),
                        purpose=later.purpose, error_code="BATCH_STOPPED",
                        failed_check="batch",
                        message=("not run: an earlier step in this batch "
                                 "failed.")))
                break

        ok = all(r.status == "ok" for r in results)
        return BatchResult(
            submission_id=submission_id,
            status="ok" if ok else "failed", steps=results,
            validated_all=True,
            message="" if ok else (
                "One step failed. Earlier successful results are preserved "
                "as artifacts and are listed above. CreditProbe did not "
                "repair anything: the corrected code is yours to write."))

    def _run_step(self, step: Step, *, deadline_seconds: float) -> StepResult:
        if step.language == "python":
            return self._run_python(step, deadline_seconds=deadline_seconds)
        return self._run_sql(step, deadline_seconds=deadline_seconds)

    def _run_sql(self, step: Step, *, deadline_seconds: float) -> StepResult:
        digest = code_digest(step.code)
        # Bound again here, with its parameters, because a step deferred at
        # validation has not been proven yet and because the binder is cheap.
        try:
            prove_bindable(step.code, self.session, parameters=step.parameters)
        except BindFailure as exc:
            raise StepFailed(SQL_VALIDATION, CHECK_BIND, exc.message,
                             detail=exc.detail()) from exc

        warnings: list[str] = []
        try:
            risk = v3_sql.multiplication_risk(step.code, self.session)
        except v3_sql.SqlRejected as exc:
            # A demonstrable repetition trap is a refusal, not a warning. The
            # analyst is told exactly which join and why.
            raise StepFailed(SQL_VALIDATION, CHECK_GRAIN, str(exc)) from exc
        except Exception:  # noqa: BLE001
            risk = None
        if isinstance(risk, Exception):
            raise StepFailed(SQL_VALIDATION, CHECK_GRAIN, str(risk))
        if risk:
            warnings.append(str(risk))

        try:
            result = self._execute_sql(step, deadline_seconds=deadline_seconds)
        except v3_sql.SqlRejected as exc:
            raise StepFailed(SQL_RUNTIME, CHECK_RUNTIME, str(exc)) from exc
        except StepFailed:
            raise
        except Exception as exc:  # noqa: BLE001
            raise StepFailed(SQL_RUNTIME, CHECK_RUNTIME, str(exc)) from exc

        columns = [c["name"] for c in result.columns]
        artifact_id = self.store.put_artifact(
            run_id=self.run_id, tenant_id=self.tenant_id, kind="result",
            release_id=self.release_id,
            scope={"relations": list(getattr(self.session, "relations", ())),
                   "step_id": step.step_id},
            columns=columns, rows=result.rows, code_digest=digest)
        self.artifacts[step.step_id] = artifact_id

        preview_columns = columns[:self.limits.preview_columns]
        if len(columns) > self.limits.preview_columns:
            warnings.append(
                f"This preview shows {len(preview_columns)} of "
                f"{len(columns)} columns. The full result is artifact "
                f"{artifact_id}; read it rather than concluding from the "
                f"preview.")
        preview = [{k: row.get(k) for k in preview_columns}
                   for row in result.rows[:self.limits.preview_rows]]
        row_ids = [deriv.row_id_for(i) for i in range(len(preview))]
        return StepResult(
            step_id=step.step_id, status="ok", language="sql",
            code_digest=digest, purpose=step.purpose, columns=columns,
            row_count=result.row_count, preview=preview, row_ids=row_ids,
            truncated=bool(result.truncated) or len(
                columns) > self.limits.preview_columns,
            artifact_id=artifact_id,
            warnings=warnings + list(result.warnings))

    def _execute_sql(self, step: Step, *, deadline_seconds: float):
        """Run the step exactly as submitted, with its declared parameters.

        With no parameters this is V3's executor unchanged — the deadline
        watchdog, the row limits and the error classification are all its
        own, and that is the path V3's suite covers. With parameters it is
        the same connection and the same deadline, with the argument DuckDB
        needs, because a `parameters` object the engine never sees is a
        contract the application advertised and did not honour.
        """
        argument = parameter_argument(step.code, step.parameters)
        if argument is None:
            return v3_sql.execute(
                step.code, self.session, deadline_seconds=deadline_seconds,
                max_rows=self.limits.preview_rows)

        import threading

        timed_out = threading.Event()
        finished = threading.Event()

        def watchdog() -> None:
            if not finished.wait(max(0.05, deadline_seconds)):
                timed_out.set()
                try:
                    self.session.connection.interrupt()
                except Exception:  # noqa: BLE001
                    pass

        started = time.monotonic()
        threading.Thread(target=watchdog, daemon=True).start()
        try:
            frame = self.session.connection.execute(
                step.code, argument).fetch_df()
        except Exception as exc:  # noqa: BLE001
            finished.set()
            if timed_out.is_set():
                raise StepFailed(
                    SQL_RUNTIME, CHECK_RUNTIME,
                    f"the query was cancelled after {deadline_seconds:.0f} "
                    f"seconds.") from exc
            raise StepFailed(SQL_RUNTIME, CHECK_RUNTIME,
                             str(exc).strip().splitlines()[0][:400]) from exc
        finally:
            finished.set()

        total = int(len(frame))
        warnings: list[str] = []
        shown = frame.head(self.limits.preview_rows)
        truncated = total > self.limits.preview_rows
        if truncated:
            warnings.append(
                f"{total} rows were produced and the first "
                f"{self.limits.preview_rows} are shown. This is a CLIPPED "
                f"table, not a complete aggregate: do not read a total off "
                f"it.")
        return v3_sql.SqlResult(
            columns=[{"name": str(name), "type": str(dtype)}
                     for name, dtype in zip(frame.columns, frame.dtypes)],
            rows=shown.replace({float("nan"): None}).to_dict(
                orient="records"),
            row_count=total, truncated=truncated,
            elapsed_seconds=round(time.monotonic() - started, 4),
            warnings=warnings)

    def _run_python(self, step: Step, *, deadline_seconds: float) -> StepResult:
        if self.python_runner is None or not getattr(
                self.python_runner, "available", False):
            raise StepFailed(
                PYTHON_UNAVAILABLE, CHECK_SANDBOX,
                "no isolated Python runner is available in this runtime; the "
                "step was not executed and was not converted to SQL.")
        digest = code_digest(step.code)
        inputs = {sid: self.artifacts.get(sid, "")
                  for sid in step.depends_on_step_ids}
        outcome = self.python_runner.run(
            code=step.code, parameters=step.parameters, inputs=inputs,
            deadline_seconds=deadline_seconds,
            memory_mib=self.limits.python_memory_mib,
            output_bytes=self.limits.output_bytes_per_step)
        if not outcome.get("ok"):
            raise StepFailed(
                str(outcome.get("error_code") or SQL_RUNTIME),
                str(outcome.get("failed_check") or CHECK_RUNTIME),
                str(outcome.get("message") or "the Python step failed."))
        columns = list(outcome.get("columns") or [])
        rows = list(outcome.get("rows") or [])
        artifact_id = self.store.put_artifact(
            run_id=self.run_id, tenant_id=self.tenant_id, kind="result",
            release_id=self.release_id,
            scope={"step_id": step.step_id, "language": "python"},
            columns=columns, rows=rows, code_digest=digest)
        self.artifacts[step.step_id] = artifact_id
        return StepResult(
            step_id=step.step_id, status="ok", language="python",
            code_digest=digest, purpose=step.purpose, columns=columns,
            row_count=len(rows), preview=rows[:self.limits.preview_rows],
            row_ids=[deriv.row_id_for(i) for i in
                     range(min(len(rows), self.limits.preview_rows))],
            artifact_id=artifact_id,
            warnings=list(outcome.get("warnings") or []))


def no_progress_key(submission: ExecutionSubmission, *, release_id: str,
                    error_class: str = "") -> str:
    """Identity of an attempt, for the no-progress rule.

    Includes the error CLASS so a transient environment failure is not cached
    forever as an invalid query, while an identical deterministic failure
    cannot be paid for twice.
    """
    import hashlib
    parts = [release_id, error_class]
    for step in submission.steps:
        parts.append(step.language)
        parts.append(step.code)
        parts.append(repr(sorted(step.parameters.items())))
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:32]


__all__ = ["BatchResult", "CHECK_AUTHORIZATION", "CHECK_BIND", "CHECK_GRAIN",
           "CHECK_RUNTIME", "CHECK_SANDBOX", "CHECK_STRUCTURE",
           "ExecutionService", "StepFailed", "StepResult", "no_progress_key"]
