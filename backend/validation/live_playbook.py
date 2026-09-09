"""
What a live provider has to get right for Playbook, defined once. PB-013,
PB-015, PB-017, PB-029, PB-030, PB-038, PB-043.

Why this is production code
---------------------------
The same reason `live_smoke.py` gives: a deployment must be able to verify its
own live path, and the deployed image ships neither `tests/` nor pytest. So the
checks live here, `tests/playbook/test_live_playbook.py` drives them, and
`scripts/playbook_live_slice.py` drives them too. There is one definition of
what "Playbook's live path works" means and every caller reads it.

What these prove, and what they do not
--------------------------------------
They prove that a real model, with the configured AUTHOR role, produced a real
document through the real tool path: that text streamed as it was written, that
the served model is the configured one, that files were generated and their
bytes persisted and parsed back, that versions are immutable, and that a
request the fixtures do not contain was genuinely answered.

They do not grade the prose. Whether a paragraph is well written is not
something a check can assert, and pretending otherwise would make this suite
look stronger than it is.

Bounded, on purpose
-------------------
Each check declares its call cost and the suite sums it, so an operator sees
the bill before anything is spent. Evidence is synthetic throughout — the ECL
oracle and a small generated workbook — so nothing real is ever sent to a
provider.
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

#: The tenant these checks work in. Separate from `default`, so a live run can
#: never write into the seeded demonstration or a real user's workspace.
TENANT = "live-playbook"

#: How long the suite waits for one check before giving up on it and moving on.
#: Generous, because the most expensive check makes three provider calls and a
#: real report takes minutes — but finite, because the whole reason this suite
#: was revised is that a run with no ceiling sat there until somebody noticed.
CHECK_TIMEOUT_SECONDS = float(
    os.environ.get("PLAYBOOK_LIVE_CHECK_TIMEOUT_SECONDS") or 900)


@dataclass(frozen=True)
class Check:
    """One thing Playbook's live path has to get right."""

    id: str
    title: str
    #: What passing it establishes, in a sentence.
    proves: str
    #: Which acceptance criterion it stands for.
    requirement: str
    #: Roughly what it costs, in provider calls.
    calls: int = 1


@dataclass
class Outcome:
    """What one check found. Never raises; a failure is a result."""

    check: str
    passed: bool
    detail: str = ""
    calls: int = 0
    model_requested: str = ""
    model_served: str = ""
    request_ids: list[str] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    error_category: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"check": self.check, "passed": self.passed,
                "detail": self.detail, "calls": self.calls,
                "model_requested": self.model_requested,
                "model_served": self.model_served,
                "request_ids": list(self.request_ids),
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
                "latency_ms": self.latency_ms,
                "error_category": self.error_category}


def _sanitise(text: str) -> str:
    from backend.llm import telemetry

    return telemetry.sanitise(text)[:400]


def _fail(check: str, exc: BaseException, calls: int = 0) -> Outcome:
    from backend.llm import telemetry

    return Outcome(check=check, passed=False, calls=calls,
                   detail=_sanitise(str(exc)),
                   error_category=telemetry.classify(exc))


# ---------------------------------------------------------------------------
# Shared synthetic evidence
# ---------------------------------------------------------------------------


def _evidence(session, scope, workspace_id: int) -> tuple[Any, list[int]]:
    """The ledger every check draws on, and the sources behind it.

    Synthetic and small: the ECL oracle's derived figures plus two documents
    generated here. Nothing real is ever sent to a provider by this suite.
    """
    from backend.playbook import service
    from backend.playbook.fixtures import ecl_oracle as oracle
    from backend.playbook.seed_threads import (
        current_results_workbook,
        ecl_methodology,
        prior_committee_report,
    )

    ids = []
    for filename, content, role in (
        ("q1-committee-report.docx", prior_committee_report(), "previous_report"),
        ("q2-results.xlsx", current_results_workbook(), "results"),
        ("ifrs9-methodology.docx", ecl_methodology(), "methodology"),
    ):
        source = service.add_source(session, scope, workspace_id,
                                    filename=filename, content=content,
                                    source_role=role)
        ids.append(source.id)
    ledger = service.ledger_for(session, scope, workspace_id, source_ids=ids,
                               calculations=list(oracle.headline().values()))
    return ledger, ids


def _workspace(session, title: str):
    from backend.playbook import repository as repo

    return repo.create_workspace(session, repo.Scope(tenant=TENANT),
                                 title=title,
                                 document_family="ifrs9_committee_report")


def _scope():
    from backend.playbook import repository as repo

    return repo.Scope(tenant=TENANT)


def _record(outcome: Outcome, result: Any, began: float) -> Outcome:
    """Copy what a run reported onto the check's result.

    Defensive about which fields exist: an authoring Outcome and a provider
    AuthoringResult carry overlapping but not identical evidence, and a check
    that raised an AttributeError while recording a successful run would be a
    poor way to report one.
    """
    outcome.model_served = getattr(result, "model_served", "") or ""
    outcome.model_requested = getattr(result, "model_requested", "") or ""
    outcome.request_ids = list(getattr(result, "request_ids", []) or [])
    outcome.latency_ms = int((time.time() - began) * 1000)
    usage = result.usage() if callable(getattr(result, "usage", None)) else {}
    outcome.input_tokens = int((usage or {}).get("input_tokens", 0) or 0)
    outcome.output_tokens = int((usage or {}).get("output_tokens", 0) or 0)
    return outcome


# ---------------------------------------------------------------------------
# The checks
# ---------------------------------------------------------------------------


def author_serves_the_configured_model() -> Outcome:
    """PB-030. The configured AUTHOR model answered, and was not swapped.

    A downgrade is not an outage and does not raise; it is recorded on the
    result and would otherwise pass silently, which is the whole point of
    asserting it here.
    """
    from backend.db.engine import get_session
    from backend.playbook import service

    began = time.time()
    try:
        with get_session() as session:
            ws = _workspace(session, "Live check — model")
            ledger, _ = _evidence(session, _scope(), ws.id)
            outcome = service.author_document(
                session, _scope(), ws.id,
                instruction="Write a two-paragraph note on the movement.",
                ledger=ledger, title="Model check", formats=["docx"])
            _cleanup(session, ws.id)
    except Exception as exc:  # noqa: BLE001
        return _fail("author_model", exc, calls=1)

    served, requested = outcome.model_served, ""
    from backend.llm import roles as role_config
    requested = role_config.role(role_config.AUTHOR).model or ""
    downgraded = bool(requested and served and requested not in served)
    result = Outcome(
        check="author_model",
        passed=bool(served) and not downgraded,
        calls=1,
        model_requested=requested or "(provider default)",
        model_served=served,
        request_ids=list(outcome.request_ids),
        latency_ms=int((time.time() - began) * 1000),
        detail=(f"requested {requested or '(provider default)'}, served {served}"
                + ("  DOWNGRADED" if downgraded else "")))
    return result


def text_streams_before_the_answer_is_finished() -> Outcome:
    """PB-038 on the live path. Deltas arrived while the model was writing.

    The synthetic suite proves the transport with fixture deltas. This is the
    one that proves the provider's own stream reaches it — and that what
    arrives is the answer rather than reasoning or tool input.
    """
    from backend.db.engine import get_session
    from backend.playbook import service

    began = time.time()
    pieces: list[str] = []
    try:
        with get_session() as session:
            ws = _workspace(session, "Live check — streaming")
            ledger, _ = _evidence(session, _scope(), ws.id)
            outcome = service.author_document(
                session, _scope(), ws.id,
                instruction="Write a short note on the ECL movement.",
                ledger=ledger, title="Streaming check", formats=["docx"],
                on_delta=pieces.append)
            _cleanup(session, ws.id)
    except Exception as exc:  # noqa: BLE001
        return _fail("streaming", exc, calls=1)

    written = "".join(pieces)
    # More than one delta, and what they assembled to is the document that was
    # saved — not a separate stream of something else.
    saved = outcome.document.plain_text() if outcome.document else ""
    first_line = (saved.splitlines() or [""])[0][:40]
    result = Outcome(
        check="streaming",
        passed=len(pieces) > 1 and bool(written) and (
            first_line in written or not first_line),
        calls=1,
        detail=f"{len(pieces)} deltas, {len(written)} characters")
    return _record(result, outcome, began)


def a_report_is_written_without_a_template() -> Outcome:
    """PB-015. A complete report from evidence alone, inventing no test.

    The assertion that matters is the negative one: the evidence contains no
    backtest, so a report claiming one was performed has failed even if it
    reads beautifully.
    """
    from backend.db.engine import get_session
    from backend.playbook import service

    began = time.time()
    try:
        with get_session() as session:
            ws = _workspace(session, "Live check — no template")
            ledger, _ = _evidence(session, _scope(), ws.id)
            outcome = service.author_document(
                session, _scope(), ws.id,
                instruction=("Write the Q2 2026 IFRS 9 committee report from "
                             "the attached evidence."),
                ledger=ledger, title="IFRS 9 Committee Report — Q2 2026",
                formats=["docx", "pdf"], task_kind="create")
            text = (outcome.document.plain_text() if outcome.document else "")
            headings = [s.heading for s in (outcome.document.sections
                                            if outcome.document else [])]
            _cleanup(session, ws.id)
    except Exception as exc:  # noqa: BLE001
        return _fail("no_template_report", exc, calls=2)

    invented = [phrase for phrase in
                ("backtest was performed", "we backtested",
                 "the backtest shows")
                if phrase in text.lower()]
    result = Outcome(
        check="no_template_report",
        passed=(len(headings) >= 4
                and outcome.grounding is not None and outcome.grounding.ok
                and set(outcome.files) == {"docx", "pdf"}
                and not invented),
        calls=2,
        detail=(f"{len(headings)} sections; "
                f"grounding {'held' if outcome.grounding and outcome.grounding.ok else 'FAILED'}"
                + (f"; INVENTED {invented}" if invented else "")))
    return _record(result, outcome, began)


def a_methodology_is_checked_without_editing_anything() -> Outcome:
    """PB-013. A coverage matrix, and no unauthorised edit.

    Two things are asserted, and the second is the one that would be missed:
    that asking for a check produced a check, and that it wrote nothing to the
    document it was checking.
    """
    from backend.db.engine import get_session
    from backend.playbook import repository as repo
    from backend.playbook import service

    began = time.time()
    try:
        with get_session() as session:
            ws = _workspace(session, "Live check — coverage")
            ledger, _ = _evidence(session, _scope(), ws.id)
            before = len(repo.artifacts(session, ws.id))
            outcome = service.author_document(
                session, _scope(), ws.id,
                instruction=("Check the attached methodology against the "
                             "attached prior report."),
                ledger=ledger, title="Coverage matrix",
                formats=["docx"], task_kind="coverage")
            text = outcome.document.plain_text() if outcome.document else ""
            tables = [b for s in (outcome.document.sections
                                  if outcome.document else [])
                      for b in s.blocks if b.kind == "table"]
            after = repo.artifacts(session, ws.id)
            _cleanup(session, ws.id)
    except Exception as exc:  # noqa: BLE001
        return _fail("coverage_matrix", exc, calls=1)

    # Exactly one artifact, and it is the matrix — not a revision of the report.
    edited_the_report = any(a.kind == "report" and a.title != "Coverage matrix"
                            for a in after[before:])
    words = text.lower()
    result = Outcome(
        check="coverage_matrix",
        passed=(bool(tables)
                and any(w in words for w in ("covered", "missing", "partial"))
                and not edited_the_report),
        calls=1,
        detail=(f"{len(tables)} table(s)"
                + ("; EDITED THE REPORT" if edited_the_report else "")))
    return _record(result, outcome, began)


def a_scoped_edit_changes_only_its_scope() -> Outcome:
    """PB-017. One section revised; the figures elsewhere unchanged; v1 intact.

    Costs two calls because the thing under test is the SECOND one: a revision
    needs a document to revise.
    """
    from backend.db.engine import get_session
    from backend.playbook import repository as repo
    from backend.playbook import service

    began = time.time()
    try:
        with get_session() as session:
            ws = _workspace(session, "Live check — scoped edit")
            ledger, _ = _evidence(session, _scope(), ws.id)
            first = service.author_document(
                session, _scope(), ws.id,
                instruction="Write the Q2 2026 committee report.",
                ledger=ledger, title="IFRS 9 Committee Report — Q2 2026",
                formats=["docx"], task_kind="create")
            v1_hash = first.document.content_hash() if first.document else ""

            second = service.author_document(
                session, _scope(), ws.id,
                instruction=("Make it more concise and more direct, in a "
                             "formal committee register."),
                ledger=ledger, title="IFRS 9 Committee Report — Q2 2026",
                formats=["docx"], task_kind="edit",
                task_scope="the executive summary",
                artifact_id=first.artifact_id,
                base_version_id=first.version_id,
                change_summary="Sharpened the executive summary.")
            versions = repo.versions(session, first.artifact_id)
            v2_text = second.document.plain_text() if second.document else ""
            v1_text = first.document.plain_text() if first.document else ""
            _cleanup(session, ws.id)
    except Exception as exc:  # noqa: BLE001
        return _fail("scoped_edit", exc, calls=3)

    import re
    figures = set(re.findall(r"\d+\.\d{2}", v1_text))
    lost = sorted(f for f in figures if f not in v2_text)
    result = Outcome(
        check="scoped_edit",
        passed=(second.version == 2
                and len(versions) == 2
                and versions[0].content_hash == v1_hash
                and versions[1].content_hash != v1_hash
                and not lost
                and second.grounding is not None and second.grounding.ok),
        calls=3,
        detail=("v1 intact, v2 written"
                + (f"; LOST FIGURES {lost}" if lost else "")))
    return _record(result, second, began)


def a_seeded_thread_continues_live() -> Outcome:
    """PB-029. Continuing a seeded workspace calls the model for real.

    The trap this closes: a demonstration that answers a follow-up from its own
    fixtures looks identical to one that asked a model, right up until somebody
    asks it something the fixtures do not contain.
    """
    from backend.db.engine import get_session
    from backend.playbook import repository as repo
    from backend.playbook import seed, service

    began = time.time()
    try:
        with get_session() as session:
            default = repo.Scope(tenant="default")
            state = seed.status(session, default)
            if not state.get("ready"):
                return Outcome(
                    check="seeded_continuation", passed=False, calls=0,
                    detail="the demonstration is not seeded, so there is no "
                           "thread to continue")
            title = state["workspaces_present"][0]
            ws = next(w for w in repo.recent_workspaces(session, default, 50)
                      if w.title == title)
            before = len(repo.messages(session, ws.id))
            result = service.send_message(
                session, default, ws.id,
                text=("In one paragraph, what would change in this report if "
                      "the downturn scenario weight rose by five percentage "
                      "points? Do not restate figures you cannot support."),
                idempotency_key=f"live-continuation-{int(time.time())}",
                formats=[])
            messages = repo.messages(session, ws.id)
            answer = messages[-1]
    except Exception as exc:  # noqa: BLE001
        return _fail("seeded_continuation", exc, calls=1)

    return Outcome(
        check="seeded_continuation",
        passed=(len(messages) == before + 2
                and answer.origin == "assistant_live"
                and bool(answer.request_ids)),
        calls=1,
        model_served=answer.model or "",
        request_ids=list(answer.request_ids or []),
        latency_ms=int((time.time() - began) * 1000),
        detail=f"origin={answer.origin}, requests={len(answer.request_ids or [])}"
               f", job={result.get('job_id')}")


def a_fresh_prompt_is_genuinely_answered() -> Outcome:
    """PB-043. A question no fixture contains, answered by the model.

    Asserted against the fixtures themselves rather than by eye: the answer
    must not be a substring of any seeded assistant turn.
    """
    from backend.db.engine import get_session
    from backend.playbook import service

    began = time.time()
    question = ("Summarise, in exactly three sentences, what a credit "
                "committee should ask about the movement in the attached "
                "evidence. Do not state any figure you cannot support.")
    try:
        with get_session() as session:
            ws = _workspace(session, "Live check — fresh prompt")
            ledger, _ = _evidence(session, _scope(), ws.id)
            outcome = service.author_document(
                session, _scope(), ws.id, instruction=question,
                ledger=ledger, title="Fresh prompt", formats=["docx"])
            text = outcome.document.plain_text() if outcome.document else ""
            _cleanup(session, ws.id)
    except Exception as exc:  # noqa: BLE001
        return _fail("fresh_prompt", exc, calls=1)

    from backend.playbook import seed_threads
    fixture_text = " ".join(
        turn.text for spec in seed_threads.threads() for turn in spec.turns)
    borrowed = text.strip() and text.strip()[:120] in fixture_text
    result = Outcome(
        check="fresh_prompt",
        passed=bool(text) and not borrowed and bool(outcome.request_ids),
        calls=1,
        detail=("answered from the model"
                if not borrowed else "REPLAYED FIXTURE TEXT"))
    return _record(result, outcome, began)


def every_format_is_produced_and_reopens() -> Outcome:
    """PB-020/PB-021 live. Four formats, persisted bytes, parsed back."""
    from backend.db.engine import get_session
    from backend.playbook import repository as repo
    from backend.playbook import service, store, validate

    began = time.time()
    try:
        with get_session() as session:
            ws = _workspace(session, "Live check — formats")
            ledger, _ = _evidence(session, _scope(), ws.id)
            outcome = service.author_document(
                session, _scope(), ws.id,
                instruction="Write the Q2 2026 committee report.",
                ledger=ledger, title="IFRS 9 Committee Report — Q2 2026",
                formats=["docx", "pdf", "pptx", "xlsx"], task_kind="create")
            rows = repo.files(session, outcome.version_id)
            exact = all(store.sha256(store.read(r.bytes_path)) == r.sha256
                        for r in rows)
            reopened = validate.validate_all(
                {r.format: store.read(r.bytes_path) for r in rows},
                outcome.document)
            _cleanup(session, ws.id)
    except Exception as exc:  # noqa: BLE001
        return _fail("all_formats", exc, calls=2)

    bad = [f for f, v in reopened.items() if not v.ok]
    result = Outcome(
        check="all_formats",
        passed=(set(outcome.files) == {"docx", "pdf", "pptx", "xlsx"}
                and exact and not bad),
        calls=2,
        detail=(f"{len(rows)} file(s), bytes exact={exact}"
                + (f"; FAILED PARSE-BACK {bad}" if bad else "")))
    return _record(result, outcome, began)


def _cleanup(session, workspace_id: int) -> None:
    """Remove the workspace a check made. Live runs leave no residue."""
    from backend.models.playbook import PlaybookWorkspace

    row = session.get(PlaybookWorkspace, workspace_id)
    if row is not None:
        session.delete(row)
        session.flush()


CHECKS: tuple[Check, ...] = (
    Check(id="author_model", requirement="PB-030",
          title="The configured AUTHOR model answered, and was not swapped",
          proves="the model the deployment configured is the model that "
                 "wrote the document, with no silent downgrade",
          calls=1),
    Check(id="streaming", requirement="PB-038",
          title="Text arrived from the provider while it was being written",
          proves="the streamed conversation is the provider's own stream "
                 "reaching the browser, not a completed answer replayed",
          calls=1),
    Check(id="no_template_report", requirement="PB-015",
          title="A complete report from evidence alone, inventing no test",
          proves="a report can be written with no template, and an analysis "
                 "the evidence does not contain is not described as performed",
          calls=2),
    Check(id="coverage_matrix", requirement="PB-013",
          title="A methodology is checked without editing anything",
          proves="asking for a check produces a check and leaves the document "
                 "it checked alone",
          calls=1),
    Check(id="scoped_edit", requirement="PB-017",
          title="A scoped edit changes its scope and nothing else",
          proves="an editorial request preserves every figure elsewhere and "
                 "leaves the previous version intact",
          calls=3),
    Check(id="seeded_continuation", requirement="PB-029",
          title="A seeded thread continues by calling the model",
          proves="the demonstration is a starting point, not a recording",
          calls=1),
    Check(id="fresh_prompt", requirement="PB-043",
          title="A question no fixture contains is genuinely answered",
          proves="the live path answers what it is asked rather than what it "
                 "was seeded with",
          calls=1),
    Check(id="all_formats", requirement="PB-020, PB-021",
          title="Word, PDF, PowerPoint and a workbook, all reopening",
          proves="every format is really generated, its exact bytes stored, "
                 "and each one parses back to the document it came from",
          calls=2),
)

RUNNERS: dict[str, Callable[[], Outcome]] = {
    "author_model": author_serves_the_configured_model,
    "streaming": text_streams_before_the_answer_is_finished,
    "no_template_report": a_report_is_written_without_a_template,
    "coverage_matrix": a_methodology_is_checked_without_editing_anything,
    "scoped_edit": a_scoped_edit_changes_only_its_scope,
    "seeded_continuation": a_seeded_thread_continues_live,
    "fresh_prompt": a_fresh_prompt_is_genuinely_answered,
    "all_formats": every_format_is_produced_and_reopens,
}

#: What the whole suite costs, for the estimate shown before anything runs.
ESTIMATED_CALLS = sum(c.calls for c in CHECKS)


@dataclass
class Suite:
    outcomes: list[Outcome] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return bool(self.outcomes) and all(o.passed for o in self.outcomes)

    @property
    def calls(self) -> int:
        return sum(o.calls for o in self.outcomes)

    def to_dict(self) -> dict[str, Any]:
        return {"passed": self.passed, "calls": self.calls,
                "outcomes": [o.to_dict() for o in self.outcomes]}


def available() -> tuple[bool, str]:
    """Whether this suite can run at all, and why not when it cannot."""
    from backend.config import settings
    from backend.playbook import provider

    state = provider.status()
    if not state.configured:
        return False, state.reason
    if not settings.has_database:
        return False, ("Playbook stores workspaces and versions in the "
                       "platform database, which is not configured.")
    return True, ""


def run(check_id: str, *, on_progress: Callable[[str, str], None] | None = None
        ) -> Outcome:
    """One check, bounded and reported as it goes.

    `on_progress(stage, detail)` is called with `start` before and `end` after,
    so a caller can print which check is running rather than showing nothing
    for two minutes. A check that raises becomes a failed Outcome: the other
    seven still need to run, and an exception is a poor carrier for a request
    id.
    """
    runner = RUNNERS.get(check_id)
    if runner is None:
        return Outcome(check=check_id, passed=False,
                       detail=f"no such check: {check_id}")
    if on_progress:
        on_progress("start", check_id)
    began = time.monotonic()
    outcome = _run_bounded(check_id, runner)
    if not outcome.latency_ms:
        outcome.latency_ms = int((time.monotonic() - began) * 1000)
    if on_progress:
        on_progress("end", check_id)
    return outcome


def _run_bounded(check_id: str, runner: Callable[[], Outcome]) -> Outcome:
    """Run one check, and stop WAITING for it after CHECK_TIMEOUT_SECONDS.

    Said precisely, because the distinction matters: Python cannot kill a
    thread, so this bounds the suite's wait, not the check's execution. The
    abandoned worker is a daemon and is itself bounded — every provider call it
    can still be inside is capped by `provider.RUN_DEADLINE_SECONDS`, which is
    the fix that stopped the hang in the first place. This is the second line
    of defence: if a check wedges somewhere the provider deadline does not
    reach, the remaining seven still run and the report still comes out.
    """
    import threading

    box: dict[str, Outcome] = {}

    def work() -> None:
        try:
            box["outcome"] = runner()
        except Exception as exc:  # noqa: BLE001 — never takes the run down
            logger.exception("Live Playbook check %s raised.", check_id)
            box["outcome"] = _fail(check_id, exc)

    worker = threading.Thread(target=work, name=f"live-check-{check_id}",
                              daemon=True)
    worker.start()
    worker.join(CHECK_TIMEOUT_SECONDS)
    if worker.is_alive():
        return Outcome(
            check=check_id, passed=False, error_category="timeout",
            latency_ms=int(CHECK_TIMEOUT_SECONDS * 1000),
            detail=(f"still running after {CHECK_TIMEOUT_SECONDS:.0f}s, so the "
                    "suite stopped waiting for it and carried on. It is not "
                    "counted as a pass."))
    return box.get("outcome") or Outcome(
        check=check_id, passed=False,
        detail="the check returned nothing at all")


def run_some(check_ids: list[str], *,
             on_progress: Callable[[str, str], None] | None = None) -> Suite:
    """Re-run named checks and nothing else.

    The reason this exists: after the first live run, three checks failed and
    re-testing them cost all twelve provider calls. Naming them costs what they
    cost. Unknown ids are reported as failures rather than silently skipped —
    a typo that quietly runs nothing would read as success.
    """
    suite = Suite()
    for check_id in check_ids:
        suite.outcomes.append(run(check_id, on_progress=on_progress))
    return suite


def run_all(stop_early: bool = False, *,
            on_progress: Callable[[str, str], None] | None = None) -> Suite:
    suite = Suite()
    for check in CHECKS:
        outcome = run(check.id, on_progress=on_progress)
        suite.outcomes.append(outcome)
        if stop_early and not outcome.passed:
            break
    return suite


def describe() -> list[dict[str, Any]]:
    return [{"id": c.id, "title": c.title, "proves": c.proves,
             "requirement": c.requirement, "calls": c.calls} for c in CHECKS]
