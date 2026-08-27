"""
Proving that THIS build, on THIS machine, actually talks to the live model.

Why this exists
---------------
Every quality gate in the repository runs without a provider key, which is
right: the deterministic governed reader must work on its own, and it is what
CI can check. But it means a green suite proves nothing whatever about the live
path — and a product that reports "AI POWERED" on the strength of a test that
never called a model is making a claim it has not earned.

The key never leaves the user's machine. So the verification has to run there,
against the running containers, and produce a record that can be brought back:
what was asked, which model actually answered, whether the response conformed,
and the exact commit it was all measured on.

What is deliberately NOT here
------------------------------
The key. Not read into a variable that is returned, not logged, not written to
the report, not passed as a build argument. This module asks the provider
whether it is *configured* and takes yes or no for an answer.

Costs
-----
Every mode states its call count before it runs, and `--mode dryrun` spends
nothing at all. A verification tool that quietly burns credit is one people
stop running.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: Bumped when the shape of the report changes, so an old report is recognised
#: as old rather than mis-read.
VERIFICATION_VERSION = "1.0"

DRYRUN = "dryrun"
QUICK = "quick"
CRITICAL = "critical"
FULL_ROUTING = "fullrouting"
FULL_CERTIFICATION = "fullcertification"

MODES: tuple[str, ...] = (DRYRUN, QUICK, CRITICAL, FULL_ROUTING,
                          FULL_CERTIFICATION)

#: What a run amounted to. Four outcomes, and no fifth.
#:
#: The distinction that matters is between the middle two. A run whose live
#: calls all passed but whose report could not be stored is NOT a verification:
#: nothing is bound to the commit or to the model configuration, the product
#: cannot show durable verification, and nobody can audit it later. Reporting
#: that as success — which is what "live verified yes" beside "REPORT NOT
#: WRITTEN" did — tells the operator the opposite of the truth.
STATUS_DRY_RUN = "DRY_RUN"
STATUS_LIVE_VERIFIED = "LIVE_VERIFIED"
STATUS_PASSED_NOT_STORED = "PASSED_NOT_STORED"
STATUS_FAILED = "FAILED"
STATUS_NOT_ELIGIBLE = "NOT_ELIGIBLE"

#: The exit-code contract, shared verbatim with scripts/verify-live-ai.ps1.
EXIT_OK = 0
EXIT_FAILED = 1
EXIT_PASSED_NOT_STORED = 2
EXIT_NOT_ELIGIBLE = 3

EXIT_FOR: dict[str, int] = {
    STATUS_DRY_RUN: EXIT_OK,
    STATUS_LIVE_VERIFIED: EXIT_OK,
    STATUS_FAILED: EXIT_FAILED,
    STATUS_PASSED_NOT_STORED: EXIT_PASSED_NOT_STORED,
    STATUS_NOT_ELIGIBLE: EXIT_NOT_ELIGIBLE,
}

#: Where reports are written. Mounted from the host in docker-compose, so a
#: report produced inside the container lands beside the repository.
REPORT_DIR = Path(os.environ.get("IPM_LOG_DIR", "logs"))

#: Roughly what each mode costs, in provider calls. Stated before anything
#: runs. Approximate by design — a thread that clarifies makes fewer calls than
#: one that answers — and the DIRECTION is what matters: nobody should discover
#: the size of a run after paying for it.
def _quick_estimate() -> int:
    """Four role pings plus whatever the smoke catalogue says it costs.

    Derived rather than written down, so adding a check cannot leave the
    estimate quietly wrong.
    """
    from backend.llm import roles as role_config
    from backend.validation import live_smoke

    return len(role_config.ROLES) + live_smoke.ESTIMATED_CALLS


ESTIMATED_CALLS: dict[str, int] = {
    DRYRUN: 0,
    QUICK: 12,   # replaced below by the derived figure
    CRITICAL: 30,
    FULL_ROUTING: 14,
    FULL_CERTIFICATION: 120,
}

# Derived from the catalogue rather than left as the literal above, which is
# kept only so the dict reads completely at a glance.
try:
    ESTIMATED_CALLS[QUICK] = _quick_estimate()
except Exception:  # noqa: BLE001 - an estimate must not break the import
    pass


# ---------------------------------------------------------------------------
# The record
# ---------------------------------------------------------------------------


@dataclass
class Case:
    """One thing that was checked, and what came back."""

    name: str
    component: str
    passed: bool
    detail: str = ""
    role: str = ""
    provider: str = ""
    #: The model that was ASKED for, and the model that actually answered.
    #: Both, because a provider that silently substitutes one for another is
    #: the failure this whole exercise exists to catch.
    configured_model: str = ""
    served_model: str = ""
    schema_valid: bool | None = None
    latency_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    request_id: str = ""
    #: A sanitised category, never a raw provider message.
    error_category: str = ""
    #: Provider calls this case actually made. Summed into the run's total, so
    #: "how many calls did this cost" is answered from the cases rather than
    #: from a counter somebody has to remember to increment.
    calls: int = 0


@dataclass
class Report:
    """The whole verification, in the shape that is written to disk."""

    verification_version: str = VERIFICATION_VERSION
    mode: str = DRYRUN
    started_at: str = ""
    finished_at: str = ""
    duration_ms: int = 0

    #: What was verified. A report that cannot be tied to a commit and a model
    #: configuration is a report about nothing in particular.
    git_sha: str = ""
    git_branch: str = ""
    git_dirty: bool = False
    source_sha: str = ""
    image_sha: str = ""
    build_matches_source: bool = False

    provider: str = ""
    provider_state: str = ""
    key_present: bool = False
    roles: list[dict[str, Any]] = field(default_factory=list)
    role_models: dict[str, str] = field(default_factory=dict)
    role_efforts: dict[str, str] = field(default_factory=dict)
    roles_differentiated: bool = False
    roles_summary: str = ""
    #: One string that changes whenever the model configuration does. Part of
    #: what makes a stored verification go stale.
    configuration_fingerprint: str = ""

    estimated_calls: dict[str, int] = field(default_factory=dict)
    spends_credits: bool = False

    live_calls_made: int = 0
    cases: list[Case] = field(default_factory=list)
    components: list[str] = field(default_factory=list)
    invariants: list[dict[str, Any]] = field(default_factory=list)

    passed: bool = False
    failures: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    #: True only when real provider calls actually happened AND all of them
    #: conformed. Necessary for LIVE VERIFIED and, on its own, not sufficient:
    #: a result nobody could store cannot be bound to this build.
    live_verified: bool = False

    #: The outcome as one word. See the STATUS_* constants.
    #:
    #: Empty until a runner settles it. Defaulting it to DRY_RUN read as a
    #: sensible starting value and was not one: `_finish` deliberately leaves
    #: DRY_RUN alone, so a Quick run that passed every case kept the default
    #: and reported itself as a dry run.
    status: str = ""
    #: Where the report was filed, when it could be.
    stored_path: str = ""
    #: Why it could not be, when it could not.
    storage_error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "cases": [asdict(c) for c in self.cases]}


# ---------------------------------------------------------------------------
# What is being verified
# ---------------------------------------------------------------------------


def _stamp(report: Report) -> None:
    """The build and the model configuration, onto the report."""
    from backend.build_info import build_info
    from backend.llm import roles as role_config

    build = build_info()
    report.git_sha = build.sha
    report.git_branch = build.source_branch
    report.git_dirty = build.source_dirty
    report.source_sha = build.source_sha
    report.image_sha = build.image_sha
    report.build_matches_source = not build.stale

    described = role_config.describe()
    report.provider = str(described.get("provider") or "")
    report.roles = list(described.get("roles") or [])
    report.roles_differentiated = bool(described.get("differentiated"))
    report.roles_summary = str(described.get("summary") or "")
    # The serialised role calls the field "role"; older payloads called it
    # "name". Both are read, because a report whose model map is keyed on the
    # string "None" is a report nobody can compare against the next one.
    report.role_models = {_role_name(r): str(r.get("model") or "")
                          for r in report.roles}
    report.role_efforts = {_role_name(r): str(r.get("effort") or "")
                           for r in report.roles}
    report.configuration_fingerprint = _configuration_fingerprint(report)

    status = _provider_status()
    report.key_present = bool(status.get("configured"))
    report.provider_state = str(status.get("state") or "")


def _role_name(role: dict[str, Any]) -> str:
    return str(role.get("role") or role.get("name") or "")


def _configuration_fingerprint(report: Report) -> str:
    """One string that changes whenever anything verified would change.

    The commit, the provider, and every role's model and effort. A stored
    verification whose fingerprint no longer matches is STALE — which is the
    rule that stops a green badge from a fortnight ago describing a build
    somebody has since re-pointed at a different model.
    """
    import hashlib

    payload = json.dumps(
        {"sha": report.git_sha, "provider": report.provider,
         "models": report.role_models, "efforts": report.role_efforts},
        sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _provider_status() -> dict[str, Any]:
    """Whether a provider is configured. Never what it is configured WITH."""
    try:
        from backend.llm import get_provider

        return get_provider().status().to_dict()
    except Exception as e:  # noqa: BLE001 - absence is a finding
        logger.info("The provider could not be described: %s", e)
        return {"configured": False, "state": "offline"}


def _category(error: BaseException) -> str:
    from backend.llm import telemetry

    try:
        return telemetry.classify(error)
    except Exception:  # noqa: BLE001
        return "unknown"


# ---------------------------------------------------------------------------
# Dry run — zero credits
# ---------------------------------------------------------------------------


def dry_run() -> Report:
    """Everything that can be reported without calling anything."""
    report = Report(mode=DRYRUN, started_at=_now())
    _stamp(report)
    report.estimated_calls = dict(ESTIMATED_CALLS)
    report.spends_credits = False

    report.notes.append(
        "This mode spends nothing. -Quick, -Critical, -FullRouting and "
        "-FullCertification all make real provider calls and consume credit.")
    if not report.key_present:
        report.notes.append(
            "No provider key is configured for this container, so no live "
            "mode can run here. The key is read at RUN TIME from your .env "
            "through docker-compose; it is never a build argument and never "
            "enters an image layer.")
    if not report.build_matches_source:
        report.notes.append(
            "The running image was built from a different commit than the "
            "code checked out beside it. A live verification against this "
            "build would not describe the code you are reading — rebuild "
            "with `docker compose up --build` first.")
    if not report.roles_differentiated:
        report.notes.append(report.roles_summary)

    report.passed = True
    report.live_verified = False
    report.status = STATUS_DRY_RUN
    return _finish(report)


def eligible(report: Report) -> tuple[bool, str]:
    """Whether this build may be live-verified at all."""
    if not report.key_present:
        return False, "no provider key is configured for the running backend"
    if not report.build_matches_source:
        return False, ("the running image was built from a different commit "
                       "than the checked-out source")
    return True, ""


# ---------------------------------------------------------------------------
# Quick — one tiny call per configured role
# ---------------------------------------------------------------------------


#: The smallest possible structured request. Two fields, both required, both
#: trivially checkable — the point is whether a conforming document comes back
#: from the model that was asked, not whether the model is clever.
_PING_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "ok": {"type": "boolean",
               "description": "Always true."},
        "role": {"type": "string",
                 "description": "Echo the role name you were given."},
    },
    "required": ["ok", "role"],
}


def quick() -> Report:
    """One tiny schema-constrained call per role, then the live smoke suite."""
    report = Report(mode=QUICK, started_at=_now())
    _stamp(report)
    report.estimated_calls = {QUICK: ESTIMATED_CALLS[QUICK]}
    report.spends_credits = True
    report.components = ["provider", "model_roles", "structured_output",
                         "live_smoke"]

    can, why = eligible(report)
    if not can:
        report.failures.append(why)
        report.passed = False
        report.status = STATUS_NOT_ELIGIBLE
        return _finish(report)

    from backend.llm import get_provider
    from backend.llm import roles as role_config

    provider = get_provider()
    for role in role_config.all_roles():
        case = _ping(provider, role, report)
        report.cases.append(case)
        if not case.passed:
            # Stop at the first broken role. Continuing would spend credit
            # proving the same configuration problem three more times.
            report.failures.append(
                f"the {role.name} role could not be served: "
                f"{case.error_category or case.detail}")
            report.passed = False
            return _finish(report)

    # The eight live smoke checks, run IN PROCESS.
    #
    # This used to shell out to `pytest tests/llm/test_live_smoke.py`, inside
    # the production backend container, which ships neither tests/ nor pytest.
    # The subprocess died in 45ms before reaching an assertion and the verifier
    # recorded that as the model failing — a healthy provider reported FAILED.
    # A production verification tool may only depend on what production ships.
    report.cases.extend(_smoke_cases())

    report.failures.extend(c.name for c in report.cases if not c.passed)
    report.passed = not report.failures
    # Counted from the cases, so the total and the per-case numbers can never
    # disagree about what this run cost.
    report.live_calls_made = sum(c.calls for c in report.cases)
    report.live_verified = report.passed and report.live_calls_made > 0
    return _finish(report)


def _smoke_cases() -> list[Case]:
    """Every production-safe smoke check, as its own reported case.

    One case per check rather than one opaque result for the suite. When a
    single check fails, the report has to say WHICH — "live_smoke: failed" sent
    somebody looking at the model when the harness was the thing that was
    broken.
    """
    from backend.validation import live_smoke

    out: list[Case] = []
    for outcome in live_smoke.run_all().outcomes:
        out.append(Case(
            name=f"smoke:{outcome.check}",
            component="live_smoke",
            passed=outcome.passed,
            detail=outcome.detail,
            role=outcome.role,
            served_model=outcome.model,
            latency_ms=outcome.latency_ms,
            input_tokens=outcome.input_tokens,
            output_tokens=outcome.output_tokens,
            error_category=outcome.error_category,
            calls=outcome.calls,
        ))
    return out


def _ping(provider: Any, role: Any, report: Report) -> Case:
    """One role, one tiny call, everything about it that is safe to record."""
    started = time.perf_counter()
    try:
        result = provider.structured(
            system=("You are verifying connectivity for CreditProbe. Answer "
                    "with the tool and nothing else."),
            prompt=(f"Set ok to true and role to {role.name!r}."),
            schema=_PING_SCHEMA,
            tool_name="verify",
            tool_description="Confirm the role is reachable.",
            max_tokens=64,
            purpose="validation",
            model=role.model,
            role=role.name,
            effort=role.effort,
        )
    except Exception as e:  # noqa: BLE001 - a failure is the finding
        return Case(
            name=f"role:{role.name}", component="model_roles", passed=False,
            role=role.name, provider=report.provider,
            configured_model=role.model,
            latency_ms=int((time.perf_counter() - started) * 1000),
            error_category=_category(e),
            detail="the provider did not return a conforming response")

    report.live_calls_made += 1
    data = result.data or {}
    made = 1
    conforms = (data.get("ok") is True
                and str(data.get("role") or "").strip().lower()
                == role.name.lower())
    served = str(result.model or "")
    substituted = bool(role.model) and served and served != role.model
    return Case(
        name=f"role:{role.name}",
        component="model_roles",
        passed=conforms and not substituted,
        role=role.name,
        provider=report.provider,
        configured_model=role.model,
        served_model=served,
        schema_valid=conforms,
        latency_ms=result.duration_ms,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        request_id=result.request_id,
        calls=made,
        detail=("a different model answered than the one configured for this "
                "role" if substituted else
                "" if conforms else "the response did not conform"),
    )


# ---------------------------------------------------------------------------
# Critical — the threads, through the API the browser uses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Thread:
    """One conversation, and what must be true at the end of it."""

    name: str
    questions: tuple[str, ...]
    component: str
    #: What is checked on the final turn. Named rather than inlined so a
    #: failure says which property did not hold.
    expects: tuple[str, ...] = ()


#: §5 of the remediation brief, verbatim in intent.
#:
#: These run through `POST /investigations` and `.../messages` — the endpoints
#: the browser calls — rather than through `read_request()`. The last time
#: conversation memory was verified against an internal function it worked in
#: every check and failed for every user.
THREADS: tuple[Thread, ...] = (
    Thread(
        name="A_metadata_memory",
        component="conversation_memory",
        questions=(
            "What data do you have about borrower ratings?",
            "What fields are available in that data?",
            "Which of those fields are financial ratios?",
        ),
        expects=("succeeded", "dataset_focus_retained", "field_set_retained",
                 "narrowed"),
    ),
    Thread(
        name="B_complex_dynamic_calculation",
        component="analytical_planning",
        questions=(
            "For each sector, calculate Stage 2 EAD as a percentage of total "
            "sector EAD, compare it with four quarters ago, and rank sectors "
            "by the largest increase.",
        ),
        expects=("succeeded", "two_periods", "grouped", "ranked_descending",
                 "invariants_passed", "interpretation_grounded"),
    ),
    Thread(
        name="C_entity_set_memory",
        component="conversation_memory",
        questions=(
            "Show me the five largest Real Estate customers by EAD.",
            "Which of these are Stage 2 or Stage 3?",
            "Add their latest internal rating.",
        ),
        expects=("succeeded", "population_retained", "no_expansion"),
    ),
    Thread(
        name="D_previous_result_reuse",
        component="previous_result_reuse",
        questions=(
            "For each rating grade, show average ECL coverage, average "
            "leverage and average DSCR in the latest period.",
            "Does this trend make sense?",
        ),
        expects=("succeeded", "reused_result", "no_rescan",
                 "association_not_causation", "sample_size_stated"),
    ),
    Thread(
        name="E_material_ambiguity",
        component="ambiguity_gate",
        questions=("Show me exposure.",),
        expects=("asks_or_states_choice",),
    ),
    Thread(
        name="F_business_invariant_gate",
        component="business_invariants",
        questions=(
            "Which large Real Estate customers have worsening DPD, increasing "
            "ECL, a rating downgrade and covenant headroom below 15%?",
        ),
        expects=("succeeded_or_empty", "every_row_satisfies_threshold",
                 "prose_satisfies_threshold", "invariants_ran"),
    ),
    Thread(
        name="G_unsupported_data",
        component="coverage",
        questions=("Which borrowers had their CEO resign in the last three "
                   "months?",),
        expects=("unsupported", "no_unrelated_analysis", "no_method_menu"),
    ),
)


def critical() -> Report:
    """Every thread in §5, end to end, through the investigation API."""
    report = Report(mode=CRITICAL, started_at=_now())
    _stamp(report)
    report.estimated_calls = {CRITICAL: ESTIMATED_CALLS[CRITICAL]}
    report.spends_credits = True
    report.components = sorted({t.component for t in THREADS})

    can, why = eligible(report)
    if not can:
        report.failures.append(why)
        report.passed = False
        report.status = STATUS_NOT_ELIGIBLE
        return _finish(report)

    from backend.validation import threads as thread_runner

    for thread in THREADS:
        started = time.perf_counter()
        try:
            outcome = thread_runner.run_thread(thread.questions, thread.expects)
        except Exception as e:  # noqa: BLE001 - a thread failing is a finding
            report.cases.append(Case(
                name=thread.name, component=thread.component, passed=False,
                latency_ms=int((time.perf_counter() - started) * 1000),
                error_category=_category(e),
                detail="the thread raised before it could be checked"))
            continue

        report.live_calls_made += int(outcome.get("calls") or 0)
        report.invariants.extend(outcome.get("invariants") or [])
        unmet = list(outcome.get("unmet") or [])
        report.cases.append(Case(
            name=thread.name,
            component=thread.component,
            passed=not unmet,
            latency_ms=int((time.perf_counter() - started) * 1000),
            served_model=str(outcome.get("model") or ""),
            provider=report.provider,
            detail=("" if not unmet
                    else "did not hold: " + ", ".join(unmet)),
        ))

    report.failures = [c.name for c in report.cases if not c.passed]
    report.passed = not report.failures
    report.live_verified = report.passed and report.live_calls_made > 0
    return _finish(report)


# ---------------------------------------------------------------------------
# Full routing, and full certification
# ---------------------------------------------------------------------------


def full_routing() -> Report:
    """The live intent-recognition suite, in full."""
    report = Report(mode=FULL_ROUTING, started_at=_now())
    _stamp(report)
    report.estimated_calls = {FULL_ROUTING: ESTIMATED_CALLS[FULL_ROUTING]}
    report.spends_credits = True
    report.components = ["intent_recognition", "capability_routing"]

    can, why = eligible(report)
    if not can:
        report.failures.append(why)
        report.passed = False
        report.status = STATUS_NOT_ELIGIBLE
        return _finish(report)

    report.cases.extend(_run_pytest(
        "tests/evals/test_ask_evaluation.py", [], "intent_recognition",
        report, env={"RUN_LIVE_LLM_EVALS": "1"}))
    report.failures = [c.name for c in report.cases if not c.passed]
    report.passed = not report.failures
    report.live_verified = report.passed and report.live_calls_made > 0

    # A harness that is not present proves nothing about the provider, so it
    # is reported as this build being unable to run the mode rather than as
    # the model having failed.
    if any(c.error_category == "harness_unavailable" for c in report.cases):
        report.status = STATUS_NOT_ELIGIBLE
        report.notes.append(
            "This mode needs the pytest suite, which production images do not "
            "ship. Run it from a development checkout, or use -Quick, which "
            "is production-safe.")
    return _finish(report)


def full_certification() -> Report:
    """The full shipped benchmark library, scored.

    NOT the sealed certification, and the difference matters enough to be
    stated here rather than only in the report. The sealed holdout lives
    outside the application and the product is forbidden to import it — a
    product that can reach its own exam has no exam — so certification against
    it is a build-time command run from the repository, never a mode of a tool
    that runs inside the container.

    What this does run is the shipped benchmark library, in full, against the
    live model: the widest live exercise available from inside a running
    installation, and honestly labelled as that.
    """
    report = Report(mode=FULL_CERTIFICATION, started_at=_now())
    _stamp(report)
    report.estimated_calls = {FULL_CERTIFICATION:
                              ESTIMATED_CALLS[FULL_CERTIFICATION]}
    report.spends_credits = True
    report.components = ["benchmark_library"]
    report.notes.append(
        "This is the shipped benchmark library, not the sealed certification. "
        "The sealed holdout is deliberately not present inside the "
        "application, so it cannot be run from here; certification against it "
        "is a build-time command run from the repository.")

    can, why = eligible(report)
    if not can:
        report.failures.append(why)
        report.passed = False
        report.status = STATUS_NOT_ELIGIBLE
        return _finish(report)

    try:
        from backend.validation import runner

        result = runner.run(user_id=None)
    except Exception as e:  # noqa: BLE001
        report.cases.append(Case(
            name="benchmark_library", component="benchmark_library",
            passed=False, error_category=_category(e),
            detail="the benchmark run could not complete"))
        report.failures.append("benchmark_library")
        report.passed = False
        return _finish(report)

    payload = result.to_dict()
    report.live_calls_made += int(payload.get("model_calls") or 0)
    report.cases.append(Case(
        name="benchmark_library", component="benchmark_library",
        passed=bool(payload.get("passed")),
        detail=str(payload.get("summary") or ""),
    ))
    report.failures = [c.name for c in report.cases if not c.passed]
    report.passed = not report.failures
    report.live_verified = report.passed and report.live_calls_made > 0
    return _finish(report)


# ---------------------------------------------------------------------------
# Running a pytest file and reading its result back
# ---------------------------------------------------------------------------


def _run_pytest(target: str, extra: list[str], component: str,
                report: Report, env: dict[str, str] | None = None
                ) -> list[Case]:
    """Run one test file and turn its outcome into cases.

    Shelling out rather than importing pytest here: the live suites are
    ordinary tests, they are what a developer runs, and a verification that
    exercised a DIFFERENT code path from the suite would be verifying itself.
    """
    import subprocess

    started = time.perf_counter()

    # Preflight, because the alternative is what already happened once: the
    # subprocess died in 45ms without reaching an assertion, and the verifier
    # recorded the MODEL as having failed. A missing harness is a different
    # fact from a failing provider, and the two must never be reported with
    # the same word.
    missing = _harness_missing(target)
    if missing:
        return [Case(name=target, component=component, passed=False,
                     latency_ms=int((time.perf_counter() - started) * 1000),
                     error_category="harness_unavailable",
                     detail=missing)]

    command = [sys.executable, "-m", "pytest", target, "-q", "--no-header",
               "-p", "no:randomly", *extra]
    try:
        completed = subprocess.run(
            command, capture_output=True, text=True, timeout=1800,
            env={**os.environ, **(env or {})}, check=False)
    except Exception as e:  # noqa: BLE001
        return [Case(name=target, component=component, passed=False,
                     latency_ms=int((time.perf_counter() - started) * 1000),
                     error_category=_category(e),
                     detail="the suite could not be started")]

    tail = (completed.stdout or "").strip().splitlines()
    summary = tail[-1] if tail else ""
    passed = completed.returncode == 0
    # Every test in a live suite made at least one provider call. Counting the
    # tests rather than the calls understates it, which is the safe direction:
    # the field exists to prove calls HAPPENED, not to bill anybody.
    report.live_calls_made += _passed_count(summary)
    return [Case(
        name=target, component=component, passed=passed,
        latency_ms=int((time.perf_counter() - started) * 1000),
        detail=_sanitise(summary),
    )]


def _harness_missing(target: str) -> str:
    """Why this suite cannot run here, or an empty string.

    Two ways, and the production image has both: pytest is not installed, and
    `tests/` is not shipped. Neither is an accident — a deployed image has no
    business carrying its own test suite, still less the sealed holdout beside
    it — so a mode that needs them is unavailable in production rather than
    broken.
    """
    import importlib.util
    from pathlib import Path as _Path

    if importlib.util.find_spec("pytest") is None:
        return ("pytest is not installed in this image, so this mode cannot "
                "run here. Production images do not ship a test runner. Run "
                "this mode from a development checkout.")
    if not _Path(target).exists():
        return (f"{target} is not present in this image, so this mode cannot "
                "run here. Production images do not ship tests/. Run this "
                "mode from a development checkout.")
    return ""


def _passed_count(summary: str) -> int:
    import re

    found = re.search(r"(\d+) passed", summary or "")
    return int(found.group(1)) if found else 0


def _sanitise(text: str) -> str:
    """A provider message with anything key-shaped removed.

    Belt and braces. The provider layer already sanitises, and this is the
    last thing between an error and a file the user may attach to an email.
    """
    from backend.llm import telemetry

    try:
        return telemetry.sanitise(text)[:300]
    except Exception:  # noqa: BLE001
        return ""


# ---------------------------------------------------------------------------
# Writing it down
# ---------------------------------------------------------------------------


def _now() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()


def _finish(report: Report) -> Report:
    """Stamp the duration, and settle the status the run has earned so far.

    "So far" because storage has not been attempted yet: `main` upgrades a
    passing run to LIVE_VERIFIED only once the report is actually on disk, and
    downgrades it to PASSED_NOT_STORED when it is not.
    """
    if report.status not in (STATUS_NOT_ELIGIBLE, STATUS_DRY_RUN):
        report.status = (STATUS_LIVE_VERIFIED if report.live_verified
                         else STATUS_FAILED)
    report.finished_at = _now()
    try:
        from datetime import datetime

        started = datetime.fromisoformat(report.started_at)
        finished = datetime.fromisoformat(report.finished_at)
        report.duration_ms = int((finished - started).total_seconds() * 1000)
    except Exception:  # noqa: BLE001
        report.duration_ms = 0
    return report


#: Keys that must never appear in a written report, whatever produced them.
#: Checked rather than trusted: this file is the last thing between a live run
#: and a JSON document a user may attach to an email.
#: Field names that carry a CREDENTIAL. Matched on the whole normalised key,
#: not as a substring of it.
#:
#: The substring rule this replaces refused a Quick run that had passed: every
#: role case carries `input_tokens` and `output_tokens`, "token" was on the
#: list, and so a verification that had made twelve successful live calls could
#: not be filed. A scanner that blocks the evidence it exists to protect is a
#: scanner people turn off.
CREDENTIAL_FIELDS: frozenset[str] = frozenset({
    "api_key", "apikey", "anthropic_api_key", "openai_api_key",
    "x_api_key", "auth", "authorization", "authorization_header",
    "auth_header", "auth_token", "access_token", "refresh_token",
    "bearer_token", "id_token", "session_token", "csrf_token",
    "token",           # bare, it is a credential; the counts below are named
    "secret", "secrets", "client_secret", "secret_key", "signing_key",
    "password", "passwd", "pwd", "passphrase",
    "credential", "credentials", "private_key", "cookie", "set_cookie",
})

#: Numerical telemetry that merely COUNTS tokens. Explicitly permitted, and
#: required to be a number: a string under `input_tokens` is not a count.
TOKEN_TELEMETRY: frozenset[str] = frozenset({
    "input_tokens", "output_tokens", "total_tokens",
    "cached_input_tokens", "cache_creation_input_tokens",
    "cache_read_input_tokens", "prompt_tokens", "completion_tokens",
    "max_tokens", "token_count", "tokens", "tokens_used",
})

#: Content that is not a credential and still must never be filed: the raw
#: material of a request, the client's own rows, or a benchmark's answers.
#: These are the §4 prohibitions that a key scanner alone would not catch.
CONFIDENTIAL_FIELDS: frozenset[str] = frozenset({
    "prompt", "raw_prompt", "system", "system_prompt", "messages",
    "request_body", "raw_request", "body", "payload_body",
    "rows", "raw_rows", "data_rows", "records", "sample_rows",
    "gold", "gold_answer", "gold_answers", "expected_answer", "answer_key",
})

#: Suffixes that make a field a credential whatever it is prefixed with, so
#: `provider_access_token` is caught without listing every provider.
CREDENTIAL_SUFFIXES: tuple[str, ...] = (
    "_api_key", "_access_token", "_refresh_token", "_bearer_token",
    "_id_token", "_session_token", "_auth_token", "_secret", "_password",
    "_credential", "_private_key", "_passphrase",
)

#: Values that are a credential on sight.
CREDENTIAL_VALUES: tuple[tuple[str, str], ...] = (
    (r"sk-ant[-\w]", "an Anthropic API key"),
    (r"sk_live[-\w]", "a live secret key"),
    (r"sk-proj[-\w]", "a project API key"),
    (r"(?i)\bBearer\s+[A-Za-z0-9._\-]{16,}", "a bearer credential"),
    (r"(?i)\bBasic\s+[A-Za-z0-9+/]{16,}={0,2}", "a basic-auth credential"),
    (r"(?i)\bx-api-key\s*[:=]", "an API-key header"),
)


def _normalised(key: str) -> str:
    """A field name in the one form the rules are written against."""
    out = []
    for ch in str(key).lower():
        out.append(ch if ch.isalnum() else "_")
    return "_".join(part for part in "".join(out).split("_") if part)


def _field_problem(key: str, value: Any) -> str:
    """Why this field may not be written, or an empty string.

    Order matters. Token telemetry is checked FIRST, because it is the case
    that was wrongly refused and because `input_tokens` would otherwise be
    caught by the bare `token` rule the moment anybody re-broadened it.
    """
    name = _normalised(key)

    if name in TOKEN_TELEMETRY:
        if value is None or isinstance(value, bool):
            return ""
        if isinstance(value, (int, float)):
            return ""
        return (f"{key!r} is token-usage telemetry and must be a number; "
                "this one holds a string")

    if name in CREDENTIAL_FIELDS:
        return f"{key!r} is a credential field"
    if name in CONFIDENTIAL_FIELDS:
        return (f"{key!r} carries raw request or client content, which a "
                "verification report may not record")
    for suffix in CREDENTIAL_SUFFIXES:
        if name.endswith(suffix.strip("_")) and name != suffix.strip("_"):
            return f"{key!r} ends in a credential suffix"
        if ("_" + name).endswith(suffix):
            return f"{key!r} ends in a credential suffix"
    return ""


def _value_problem(value: str) -> str:
    """Why this value may not be written, or an empty string."""
    import re as _re

    for pattern, what in CREDENTIAL_VALUES:
        if _re.search(pattern, value):
            return f"the value looks like {what}"
    return ""


def _key_free(payload: dict[str, Any]) -> list[str]:
    """Everything in the report that must not be written. Empty is the pass.

    Returns the PATH and the reason together, so a refusal tells whoever ran
    the verification which field to look at rather than making them guess.
    """
    found: list[str] = []

    def walk(value: Any, path: str) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                where = f"{path}.{key}"
                problem = _field_problem(key, item)
                if problem:
                    found.append(f"{where} ({problem})")
                walk(item, where)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                walk(item, f"{path}[{index}]")
        elif isinstance(value, str):
            problem = _value_problem(value)
            if problem:
                found.append(f"{path} ({problem})")

    walk(payload, "report")
    return found


def write(report: Report, directory: Path | None = None) -> Path:
    """Write the report, refusing if anything key-shaped is in it."""
    payload = report.to_dict()
    leaks = _key_free(payload)
    if leaks:
        raise RuntimeError(
            "The verification report was not written because it contains "
            "fields that must never be recorded: " + ", ".join(leaks))

    target = Path(directory or REPORT_DIR)
    target.mkdir(parents=True, exist_ok=True)
    short = (report.git_sha or "unknown")[:12]
    path = target / f"live_ai_verification_{short}.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Staleness
# ---------------------------------------------------------------------------


def is_stale(report: dict[str, Any]) -> tuple[bool, str]:
    """Whether a stored verification still describes what is running.

    Anything that could change the answer makes it stale: a different commit,
    a different provider, a different model for any role, a different effort.
    The rule is deliberately blunt — a badge that survives a configuration
    change is worse than no badge, because somebody will believe it.
    """
    current = Report()
    _stamp(current)

    if not report:
        return True, "there is no stored verification for this build"
    if str(report.get("verification_version")) != VERIFICATION_VERSION:
        return True, "the stored verification is in an older format"
    if str(report.get("git_sha") or "") != current.git_sha:
        return True, ("the stored verification was made on a different "
                      "commit than the one running")
    if str(report.get("configuration_fingerprint") or "") \
            != current.configuration_fingerprint:
        return True, ("the model configuration has changed since the stored "
                      "verification was made")
    if not report.get("live_verified"):
        return True, "the stored verification did not make live provider calls"
    return False, ""


def stored(directory: Path | None = None) -> dict[str, Any]:
    """The verification for the build that is running, if there is one.

    A dry run is deliberately not one. It is a survey of what WOULD be
    verified and it costs nothing, so it is the report most likely to be
    sitting on disk — and treating it as a verification made the badge read
    STALE on a build that had simply never been verified at all.
    """
    current = Report()
    _stamp(current)
    short = (current.git_sha or "unknown")[:12]
    path = Path(directory or REPORT_DIR) / f"live_ai_verification_{short}.json"
    if not path.exists():
        return {}
    try:
        found = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001 - an unreadable report is no report
        logger.warning("The stored verification could not be read: %s", e)
        return {}
    return {} if str(found.get("mode") or "") == DRYRUN else found


def badge(directory: Path | None = None) -> dict[str, Any]:
    """What the product may display about live verification.

    `live_verified` is true only when a stored report passed, actually made
    provider calls, was made on this commit, and matches the model
    configuration that is running now.
    """
    found = stored(directory)
    stale, why = is_stale(found)
    # STALE means "was verified, and something has since moved". A build that
    # has never been verified is NOT VERIFIED, and calling it stale would
    # imply a verification once existed.
    was_verified = bool(found) and bool(found.get("live_verified"))
    current = Report()
    _stamp(current)
    return {
        "live_verified": bool(found) and not stale,
        "stale": was_verified and stale,
        "reason": why,
        "status": str(found.get("status") or ""),
        "verified_at": str(found.get("finished_at") or ""),
        "mode": str(found.get("mode") or ""),
        "calls": int(found.get("live_calls_made") or 0),
        "components": list(found.get("components") or []),
        # What the stored verification was made against, and what is running
        # now. Both, so a reader can see WHY it is stale rather than being
        # told that it is.
        "verified_sha": str(found.get("git_sha") or ""),
        "verified_short_sha": str(found.get("git_sha") or "")[:12],
        "verified_fingerprint":
            str(found.get("configuration_fingerprint") or ""),
        "running_sha": current.git_sha,
        "running_short_sha": current.git_sha[:12],
        "running_fingerprint": current.configuration_fingerprint,
        "role_models": dict(found.get("role_models") or {}),
        "role_efforts": dict(found.get("role_efforts") or {}),
        # Said on every surface that shows the badge. A live verification
        # proves the path works on the cases it exercised; it is not a
        # statistical claim about accuracy, and a product that lets one be read
        # as the other has mis-sold itself.
        "caveat": ("This confirms the live model path ran and conformed on "
                   "the cases listed. It is not a measure of accuracy."),
    }


# ---------------------------------------------------------------------------
# The command line
# ---------------------------------------------------------------------------


RUNNERS = {
    DRYRUN: dry_run,
    QUICK: quick,
    CRITICAL: critical,
    FULL_ROUTING: full_routing,
    FULL_CERTIFICATION: full_certification,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="live_verify",
        description="Verify that this build talks to the live model.")
    parser.add_argument("--mode", choices=MODES, default=DRYRUN,
                        help="Which verification to run. Default: dryrun, "
                             "which spends nothing.")
    parser.add_argument("--json", action="store_true",
                        help="Print the whole report as JSON.")
    parser.add_argument("--out", default="",
                        help="Directory for the report. Default: logs/")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.WARNING)
    report = RUNNERS[args.mode]()

    directory = Path(args.out) if args.out else None
    path = store_result(report, directory)

    if args.json:
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    else:
        _print_summary(report, path)
    return EXIT_FOR.get(report.status, EXIT_FAILED)


def store_result(report: Report, directory: Path | None = None) -> Path | None:
    """File the report, and settle what the run is actually worth.

    A run whose calls passed and whose report could not be stored is downgraded
    here, not glossed over. The previous behaviour printed the refusal to
    stderr and then announced "live verified yes" three lines later, which is
    the one thing an operator cannot be told: the calls did work, and nothing
    about them was kept, so the product will show nothing and nobody can audit
    it. Both halves are true and only the second one governs what happens next.
    """
    if report.status == STATUS_FAILED or report.status == STATUS_NOT_ELIGIBLE:
        # Still filed where it can be: a failed verification is evidence too.
        # But its status does not change, and a refusal to write one is not
        # worth escalating over.
        try:
            return write(report, directory)
        except Exception as e:  # noqa: BLE001
            report.storage_error = str(e)
            return None

    try:
        path = write(report, directory)
    except Exception as e:  # noqa: BLE001 - refusing to write IS the result
        report.storage_error = str(e)
        if report.status == STATUS_LIVE_VERIFIED:
            report.status = STATUS_PASSED_NOT_STORED
        print(f"REPORT NOT WRITTEN: {e}", file=sys.stderr)
        return None

    report.stored_path = str(path)
    return path


#: What each status means, in the words the operator needs. Printed rather
#: than left to be inferred from an exit code nobody reads.
STATUS_DETAIL: dict[str, str] = {
    STATUS_DRY_RUN:
        "Nothing was spent and nothing was verified.",
    STATUS_LIVE_VERIFIED:
        "The live calls passed AND the report was stored against this commit. "
        "The AI panel will show LIVE VERIFIED.",
    STATUS_PASSED_NOT_STORED:
        "The live calls PASSED, but the report could not be stored. Nothing "
        "is bound to this commit or model configuration, the AI panel will "
        "NOT show LIVE VERIFIED, and the result cannot be audited later.",
    STATUS_FAILED:
        "At least one case did not pass.",
    STATUS_NOT_ELIGIBLE:
        "This build cannot be live verified: see the reason above.",
}


def _print_summary(report: Report, path: Path | None) -> None:
    print(f"CreditProbe live verification - {report.mode}")
    print(f"  commit            {report.git_sha[:12] or 'unknown'}"
          f"{' (dirty)' if report.git_dirty else ''}")
    print(f"  branch            {report.git_branch or 'unknown'}")
    print(f"  build matches     {'yes' if report.build_matches_source else 'NO'}")
    print(f"  provider          {report.provider or 'none'} "
          f"({report.provider_state or 'unknown'})")
    print(f"  key present       {'yes' if report.key_present else 'no'}")
    print(f"  roles             {report.roles_summary}")
    for name, model in sorted(report.role_models.items()):
        effort = report.role_efforts.get(name) or "default"
        print(f"    {name:<16}{model or '(provider default)'}  effort={effort}")
    if report.mode == DRYRUN:
        print("  estimated calls")
        for mode, calls in report.estimated_calls.items():
            spend = "spends credit" if calls else "free"
            print(f"    {mode:<20}{calls:>4}   {spend}")
        can, why = eligible(report)
        print(f"  eligible          "
              f"{'yes' if can else 'no' + (f' - {why}' if why else '')}")
    else:
        print(f"  live calls        {report.live_calls_made}")
        for case in report.cases:
            mark = "PASS" if case.passed else "FAIL"
            served = f"  served={case.served_model}" if case.served_model else ""
            print(f"    {mark}  {case.name}{served}"
                  f"{'  ' + case.detail if case.detail else ''}")
    for note in report.notes:
        print(f"  note: {note}")
    for failure in report.failures:
        print(f"  FAILED: {failure}")

    # Three separate facts, never collapsed into one. The middle one is the
    # whole point of this block: calls can pass and still leave nothing behind.
    print(f"  live calls passed {'yes' if report.live_verified else 'no'}")
    print(f"  report stored     {'yes' if path else 'NO'}")
    if report.storage_error:
        print(f"    reason          {report.storage_error}")
    print(f"  STATUS            {report.status}")
    print(f"    {STATUS_DETAIL.get(report.status, '')}")
    if path:
        print(f"  report            {path}")
    print(f"  exit code         {EXIT_FOR.get(report.status, EXIT_FAILED)}")


if __name__ == "__main__":  # pragma: no cover - the entry point
    raise SystemExit(main())
