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

#: Where reports are written. Mounted from the host in docker-compose, so a
#: report produced inside the container lands beside the repository.
REPORT_DIR = Path(os.environ.get("IPM_LOG_DIR", "logs"))

#: Roughly what each mode costs, in provider calls. Stated before anything
#: runs. Approximate by design — a thread that clarifies makes fewer calls than
#: one that answers — and the DIRECTION is what matters: nobody should discover
#: the size of a run after paying for it.
ESTIMATED_CALLS: dict[str, int] = {
    DRYRUN: 0,
    QUICK: 12,
    CRITICAL: 30,
    FULL_ROUTING: 14,
    FULL_CERTIFICATION: 120,
}


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
    #: conformed. This is the field the product reads before it may display
    #: LIVE VERIFIED, and it is deliberately impossible to set from a run that
    #: made no calls.
    live_verified: bool = False

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

    report.cases.extend(_run_pytest(
        "tests/llm/test_live_smoke.py", ["-m", "live"], "live_smoke", report))
    report.failures.extend(c.name for c in report.cases if not c.passed)
    report.passed = not report.failures
    report.live_verified = report.passed and report.live_calls_made > 0
    return _finish(report)


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
        return _finish(report)

    report.cases.extend(_run_pytest(
        "tests/evals/test_ask_evaluation.py", [], "intent_recognition",
        report, env={"RUN_LIVE_LLM_EVALS": "1"}))
    report.failures = [c.name for c in report.cases if not c.passed]
    report.passed = not report.failures
    report.live_verified = report.passed and report.live_calls_made > 0
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
_FORBIDDEN = ("api_key", "apikey", "authorization", "anthropic_api_key",
              "secret", "token", "password", "bearer")


def _key_free(payload: dict[str, Any]) -> list[str]:
    """Anything in the report that must not be written. Empty is the pass."""
    found: list[str] = []

    def walk(value: Any, path: str) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                lowered = str(key).lower()
                if any(bad in lowered for bad in _FORBIDDEN):
                    found.append(f"{path}.{key}")
                walk(item, f"{path}.{key}")
        elif isinstance(value, list):
            for index, item in enumerate(value):
                walk(item, f"{path}[{index}]")
        elif isinstance(value, str):
            # An Anthropic key is `sk-ant-` followed by a long opaque string.
            # Matching the prefix rather than the length: a truncated key is
            # still a key, and a report is not the place to be clever.
            if "sk-ant" in value or "sk_live" in value:
                found.append(path)

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
    return {
        "live_verified": bool(found) and not stale,
        "stale": was_verified and stale,
        "reason": why,
        "verified_at": str(found.get("finished_at") or ""),
        "mode": str(found.get("mode") or ""),
        "calls": int(found.get("live_calls_made") or 0),
        "components": list(found.get("components") or []),
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
    try:
        path = write(report, directory)
    except Exception as e:  # noqa: BLE001 - refusing to write is a result
        print(f"REPORT NOT WRITTEN: {e}", file=sys.stderr)
        path = None

    if args.json:
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    else:
        _print_summary(report, path)
    return 0 if report.passed else 1


def _print_summary(report: Report, path: Path | None) -> None:
    print(f"CreditProbe live verification — {report.mode}")
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
        print(f"  eligible          {'yes' if can else 'no' + (f' — {why}' if why else '')}")
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
    print(f"  live verified     {'yes' if report.live_verified else 'no'}")
    if path:
        print(f"  report            {path}")


if __name__ == "__main__":  # pragma: no cover - the entry point
    raise SystemExit(main())
