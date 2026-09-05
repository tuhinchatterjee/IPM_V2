"""The Scorecard Validation Intelligence cockpit, over HTTP.

Three scorecards, forty-eight tests, and one rule that shapes every route
here: a response never contains a number the engine did not measure. A test
that could not run comes back with its state, its explanation and no value,
and the client renders the explanation. There is no field a chart can read
that says 0.0 because a cohort has not matured.

What is deterministic and what is not
-------------------------------------
Everything on these routes is deterministic. Every figure comes from
`backend/scorecard/metrics.py` through `backend/scorecard/validation/runner`,
every verdict is `Limit.verdict` comparing a number to a governed threshold,
and no route calls a language model. The conversational surface is a separate
concern and reaches the same results through the same runner.

Domain isolation
----------------
`backend/scorecard/domains` is the boundary, and it is enforced below the
router rather than in it: `runner.population` calls
`domains.require_validation_domain`, and `models.get` refuses any id outside
the three. A route cannot widen that by passing a different argument, which
is the point — a permission check that lives in a handler is a permission
check somebody forgets to copy into the next handler.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Response,
    status,
)
from sqlalchemy.orm import Session

from backend.api.permissions import (
    Principal,
    RequireScorecardAnalyse,
    RequireScorecardView,
)
from backend.config import settings
from backend.db.engine import SessionLocal
from backend.scorecard import domains
from backend.scorecard import report as report_mod
from backend.scorecard.validation import (
    compare as run_compare,
)
from backend.scorecard.validation import (
    conversation as reader,
)
from backend.scorecard.validation import (
    findings as finding_engine,
)
from backend.scorecard.validation import (
    models as model_registry,
)
from backend.scorecard.validation import (
    registry as test_registry,
)
from backend.scorecard.validation import (
    regulatory as regulatory_map,
)
from backend.scorecard.validation import (
    report as report_studio,
)
from backend.scorecard.validation import (
    runner,
    states,
)
from backend.scorecard.validation import (
    store as run_store,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/scorecard-validation",
                   tags=["scorecard-validation-intelligence"])

#: A whole-model run touches every test on every period. It is a minute of
#: work on the larger books, not a page load, so the route that does it says
#: so rather than being called by accident from a dashboard poll.
FULL_RUN_IS_SLOW = (
    "A full run executes every applicable test over every period. On the "
    "larger books that is a minute or more of computation, most of it in the "
    "bootstrap resampling. Run it deliberately, not on a page refresh.")


#: A validation run is INSTITUTIONAL EVIDENCE, not a private working note.
#: Anybody who may see the module may open any run, and that is deliberate: a
#: committee, a second-line reviewer and an auditor all have to read a
#: validation somebody else performed, and a per-user visibility rule would
#: make the record useless for the purpose it exists to serve.
#:
#: What is protected is WRITING. Running tests, drafting a report and
#: finalising one all require the analyse permission and are recorded against
#: the person who did them. A signed report names its signer, and no route
#: lets a caller supply that name.
RUNS_ARE_NOT_PRIVATE = (
    "A validation run is a governance record. Anybody permitted to see this "
    "module can open any run — a committee and an auditor have to read a "
    "validation somebody else performed. Creating and signing are restricted "
    "and attributed; reading is not."
)


def _session() -> Iterator[Session]:
    """A transactional session per request, committed on success."""
    if not settings.has_database:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "database_unavailable",
                    "message": ("Validation runs are kept in PostgreSQL, and "
                                "this deployment has none configured. Tests "
                                "still run; they are not recorded.")})
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _caller(principal: Principal, *, source: str = "UI",
            detail: str = "") -> run_store.Caller:
    """Who to record. Never taken from the request body.

    The name comes from the resolved principal, so a caller cannot attribute
    a run — or the signature on a report — to somebody else by sending a
    different string.
    """
    return run_store.Caller(
        user_id=getattr(principal, "user_id", None),
        name=(getattr(principal, "username", "") or ""),
        role=str(getattr(principal, "role", "") or ""),
        source=source, detail=detail)


def _stored(session: Session, run_key: str):
    try:
        return run_store.get(session, run_key)
    except run_store.StoreError as e:
        raise _not_found(e) from e


#: A Content-Disposition filename is parsed by the browser, and a value
#: carrying a quote, a semicolon or a path separator can end the header early
#: or name a file somewhere the user did not choose. Report ids are generated
#: here rather than supplied, so this is defence in depth — but a header built
#: by string interpolation is exactly the place that assumption stops being
#: true one refactor later.
_FILENAME_SAFE = set(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.")


def _filename(stem: str) -> str:
    """A download name that cannot escape its header or its directory."""
    cleaned = "".join(c if c in _FILENAME_SAFE else "-"
                      for c in (stem or "")).strip("-.")
    return (cleaned or "validation-report")[:120]


def _refused(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail={"error": "validation_refused", "message": str(exc)})


def _forbidden(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={"error": "domain_refused", "message": str(exc)})


def _not_found(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"error": "not_found", "message": str(exc)})


def _model(model_id: str) -> model_registry.Model:
    try:
        return model_registry.get(model_id)
    except domains.DomainRefused as e:
        raise _forbidden(e) from e


def _periods(period: str) -> tuple[str, ...]:
    """A comma-separated period list, or empty for the governed default.

    Parsed rather than trusted: this argument can arrive from a tool call
    whose parameters a language model wrote, and the runner reads it as a
    partition path.
    """
    wanted = tuple(p.strip() for p in period.split(",") if p.strip())
    for one in wanted:
        if not one.replace("-", "").isalnum():
            raise _refused(ValueError(
                f"{one!r} is not a period. A period is a month like "
                "2025-04."))
    return wanted


# ================================================================== what is


@router.get("/overview")
def overview(principal: Principal = RequireScorecardView) -> dict[str, Any]:
    """The three scorecards, the test registry, and what each can support.

    Deliberately does not run anything. This is the route a page load calls,
    and a page that computed forty-eight tests to render a heading would be
    a page nobody opens twice.
    """
    scorecards: list[dict[str, Any]] = []
    for made in model_registry.all_models():
        entry = made.to_dict()
        try:
            available = runner.available_periods(made)
            matured = runner.matured_periods(made)
            entry["data"] = {
                "available": bool(available),
                "periods": len(available),
                "latest_period": available[-1] if available else "",
                "matured_periods": len(matured),
                "latest_matured_period": matured[-1] if matured else "",
                "immature_periods": len(available) - len(matured),
                "performance_window_months": made.performance_window_months,
                "why_immature": (
                    "A cohort whose performance window has not closed has no "
                    "realised outcome. It is reported as NOT YET MATURED, "
                    "never as zero defaults."),
            }
        except Exception as e:  # noqa: BLE001 - an unbuilt lake is a real state
            entry["data"] = {"available": False, "why": str(e)}
        entry["applicable_tests"] = [t.test_id
                                     for t in made.applicable_tests()]
        # `inapplicable` returns (test, what it is missing) pairs, because the
        # reason is the point: a validation report has to state its own scope,
        # and "no score-to-PD mapping" is part of it. Recomputing the reason
        # here from the test alone would be a second source for the same
        # answer.
        entry["inapplicable_tests"] = [
            {"test_id": test.test_id, "why": ", ".join(missing)}
            for test, missing in made.inapplicable_tests()]
        scorecards.append(entry)

    return {
        "module": "SCORECARD VALIDATION INTELLIGENCE",
        "domains": domains.summary(),
        "scorecards": scorecards,
        "registry": test_registry.summary(),
        "result_states": [
            {"state": s, "label": states.STATE_LABELS[s],
             "meaning": states.STATE_MEANING[s],
             "carries_a_number": s in states.MEASURED}
            for s in states.STATES
        ],
        "full_run_cost": FULL_RUN_IS_SLOW,
    }


@router.get("/tests")
def tests(category: str = Query("", description="One category, or all"),
          principal: Principal = RequireScorecardView) -> dict[str, Any]:
    """The test registry: what each test asks, and how it is calculated."""
    wanted = (test_registry.in_category(category) if category
              else test_registry.all_tests())
    if category and not wanted:
        raise _not_found(ValueError(
            f"{category!r} is not a validation category. They are: "
            f"{', '.join(test_registry.CATEGORIES)}."))
    return {
        "registry_version": test_registry.REGISTRY_VERSION,
        "category": category,
        "tests": [t.to_dict() for t in wanted],
    }


@router.get("/models/{model_id}")
def model(model_id: str,
          principal: Principal = RequireScorecardView) -> dict[str, Any]:
    """One scorecard's governed record, including its limits and their source."""
    made = _model(model_id)
    body = made.to_dict()
    try:
        body["approved_specification"] = {
            "spec_version": getattr(made.approved_spec(), "spec_version", ""),
            "variables": list(made.binned_variables),
        }
    except Exception as e:  # noqa: BLE001 - reported, not hidden
        body["approved_specification"] = {"available": False, "why": str(e)}
    try:
        equation = made.approved_equation()
        body["approved_equation"] = {
            "equation": getattr(equation, "model_name", ""),
            "specification": getattr(equation, "binning_spec_version", ""),
            "link": getattr(equation, "link", ""),
            "terms": len(getattr(equation, "terms", ())),
        }
    except model_registry.ModelError as e:
        body["approved_equation"] = {"available": False, "why": str(e)}
    return body


# ================================================================ what it is


@router.post("/models/{model_id}/tests/{test_id}")
def run_one(model_id: str, test_id: str,
            period: str = Query("", description="Comma-separated months"),
            segment: str = Query(""),
            segment_field: str = Query(""),
            principal: Principal = RequireScorecardAnalyse
            ) -> dict[str, Any]:
    """Run one validation test and return its result, whatever that is.

    A refusal is a 200 carrying a refusal, not an error status. The client
    has to render it either way, and a test that legitimately cannot run on
    an immature cohort is not a fault in the request.
    """
    made = _model(model_id)
    wanted = test_registry.resolve(test_id)
    if wanted is None:
        raise _not_found(ValueError(
            f"{test_id!r} is not a validation test. There are "
            f"{len(test_registry.TESTS)}; see /scorecard-validation/tests."))
    result = runner.run(wanted.test_id, made, periods=_periods(period),
                        segment=segment, segment_field=segment_field)
    return {"test": wanted.to_dict(), "result": result.to_dict()}


@router.post("/models/{model_id}/categories/{category}")
def run_category(model_id: str, category: str,
                 period: str = Query(""),
                 segment_field: str = Query(""),
                 principal: Principal = RequireScorecardAnalyse,
                 session: Session = Depends(_session),
                 ) -> dict[str, Any]:
    """Every test in one category, refusals included.

    The refusals are returned rather than filtered, because a validation
    report has to state its own scope: "not applicable, no score-to-PD
    mapping" is a finding about the model, not an empty row.
    """
    made = _model(model_id)
    if category not in test_registry.CATEGORIES:
        raise _not_found(ValueError(
            f"{category!r} is not a validation category. They are: "
            f"{', '.join(test_registry.CATEGORIES)}."))
    began = datetime.now(UTC)
    results = runner.run_category(category, made, periods=_periods(period),
                                  segment_field=segment_field)
    body = _package(made, category, results)
    body.update(_record(session, made, results, principal,
                        scope="CATEGORY", categories=(category,),
                        periods=_periods(period), segment_field=segment_field,
                        began=began))
    return body


@router.post("/models/{model_id}/run")
def run_all(model_id: str,
            period: str = Query(""),
            duplicate_of: str = Query(
                "", description="The run this one repeats, for the audit "
                                "chain. The earlier run is not touched."),
            principal: Principal = RequireScorecardAnalyse,
            session: Session = Depends(_session),
            ) -> dict[str, Any]:
    """Every applicable test across every category. See `FULL_RUN_IS_SLOW`.

    The result is RECORDED. `duplicate_of` names the run this one repeats —
    "re-run using current data" — and creates a NEW run rather than touching
    the earlier one, which keeps its results exactly as they were.
    """
    made = _model(model_id)
    began = datetime.now(UTC)
    results: list[states.Result] = []
    for category in test_registry.CATEGORIES:
        results.extend(runner.run_category(category, made,
                                           periods=_periods(period)))
    body = _package(made, "", results)
    body["cost"] = FULL_RUN_IS_SLOW
    body.update(_record(session, made, results, principal, scope="FULL",
                        categories=test_registry.CATEGORIES,
                        periods=_periods(period), began=began,
                        duplicated_from=_run_id(session, duplicate_of)))
    return body


def _run_id(session: Session, run_key: str) -> int | None:
    """The row id behind a run key, or None. Refuses an unknown key.

    Not silently ignored: a caller naming a predecessor that does not exist
    believes it recorded a lineage, and a broken chain nobody was told about
    is worse than no chain.
    """
    if not run_key:
        return None
    return _stored(session, run_key).id


def _record(session: Session, made: model_registry.Model,
            results: list[states.Result], principal: Principal, *,
            scope: str, categories: tuple[str, ...] = (),
            tests: tuple[str, ...] = (), periods: tuple[str, ...] = (),
            segment: str = "", segment_field: str = "",
            began: datetime | None = None,
            duplicated_from: int | None = None) -> dict[str, Any]:
    """Write the run down, and say so in the response.

    A failure to RECORD must not become a failure to ANSWER: the tests ran,
    the numbers are on the caller's screen, and losing them because a database
    was briefly unreachable would be the worse outcome. The response says
    plainly whether the run was recorded, so nobody quotes a run key that does
    not exist.
    """
    try:
        run = run_store.save(
            session, model=made, results=results, caller=_caller(principal),
            scope=scope, categories=categories, tests=tests, periods=periods,
            segment=segment, segment_field=segment_field, started_at=began,
            duplicated_from=duplicated_from)
        return {
            "run_key": run.run_key,
            "recorded": True,
            "recorded_note": (
                "This run is stored and will not change. Opening it later "
                "reads these values back rather than recalculating them."),
        }
    except Exception as e:  # noqa: BLE001 - the answer survives the record
        logger.exception("scorecard validation: the run could not be recorded")
        return {
            "run_key": "",
            "recorded": False,
            "recorded_note": (
                f"These results were computed but NOT recorded: {e}. They are "
                "correct for right now and cannot be reopened later."),
        }


def _package(made: model_registry.Model, category: str,
             results: list[states.Result]) -> dict[str, Any]:
    """Results, ranked, tallied, assessed, and honest about its own coverage.

    The coverage block is not decoration. A reader looking at eleven passes
    needs to know whether that is eleven of eleven or eleven of forty-eight,
    and a summary that reports only what ran reads as the former.

    The findings are computed here rather than on a separate route, because
    a finding is a statement about a set of results and returning the two
    separately invites a client to pair a fresh set with a stale set.
    """
    ranked = states.rank(results)
    ran = {r.test_id for r in results if r.measured}
    assessed = finding_engine.assess(results, made)
    return {
        "findings": [f.to_dict() for f in assessed],
        "burning_weaknesses": [
            f.to_dict() for f in finding_engine.burning(assessed)],
        "findings_summary": finding_engine.summary(assessed),
        "model": {"model_id": made.model_id, "name": made.name,
                  "version": made.version, "domain": made.domain,
                  "scorecard_type": made.scorecard_type},
        "category": category,
        "results": [r.to_dict() for r in ranked],
        "tally": states.tally(results),
        "adverse": [r.test_id for r in ranked if r.adverse],
        "measured": len(ran),
        "returned": len(results),
        "coverage": test_registry.coverage(ran),
        "regulatory_coverage": regulatory_map.coverage(results),
        "coverage_means": (
            "A test counted here is one that produced a number. A test that "
            "refused is returned with its reason and is not counted as "
            "covered — the point of the distinction is that a validation "
            "opinion resting on tests that did not run is an opinion resting "
            "on nothing."),
        "calculation_version": runner.RUNNER_VERSION,
    }


# =============================================================== the periods


@router.get("/models/{model_id}/periods")
def periods(model_id: str,
            principal: Principal = RequireScorecardView) -> dict[str, Any]:
    """Which months exist, and which of them have a realised outcome.

    The single most useful route on this router, because almost every wrong
    number in model validation comes from running an outcome metric over a
    window that has not closed.
    """
    made = _model(model_id)
    try:
        available = runner.available_periods(made)
        matured = set(runner.matured_periods(made))
    except Exception as e:  # noqa: BLE001 - an unbuilt lake is a real state
        raise _refused(e) from e
    return {
        "model_id": made.model_id,
        "performance_window_months": made.performance_window_months,
        "periods": [{"period": p, "matured": p in matured} for p in available],
        "latest_period": available[-1] if available else "",
        "latest_matured_period": (max(p for p in available if p in matured)
                                  if matured else ""),
        "immature": [p for p in available if p not in matured],
        "what_immature_means": (
            "The performance window for these cohorts has not closed. They "
            "carry no realised outcome — which is not the same as carrying "
            "no defaults, and every outcome test refuses them by name."),
    }


def _report(model: model_registry.Model, principal: Principal):
    """Run everything, then assemble. The report never recomputes."""
    results: list[states.Result] = []
    for category in test_registry.CATEGORIES:
        results.extend(runner.run_category(category, model))
    return report_studio.build(
        model, results,
        generated_by=getattr(principal, "username", "") or "CreditProbe")


@router.post("/models/{model_id}/report")
def report(model_id: str,
           principal: Principal = RequireScorecardAnalyse
           ) -> dict[str, Any]:
    """The validation report as content, for review before it is a document.

    §29 asks for a report a validator reads in the browser and edits before
    it becomes a Word file. This route returns the content; the .docx route
    below renders the same content, so what was reviewed is what is sent.
    """
    made = _report(_model(model_id), principal)
    return {**made.to_dict(), "cost": FULL_RUN_IS_SLOW}


@router.post("/models/{model_id}/report.docx")
def report_docx(model_id: str,
                principal: Principal = RequireScorecardAnalyse) -> Response:
    """The same report, as a Word document.

    Built from the same `Report` object the review route returns, through
    the writer the retail scorecard report already uses. One content model,
    one writer: a second document builder would disagree with this one about
    a heading within a quarter, and the reader who noticed would be a
    regulator.
    """
    made = _report(_model(model_id), principal)
    blob = report_studio.docx(made)
    return Response(
        content=blob,
        media_type=("application/vnd.openxmlformats-officedocument"
                    ".wordprocessingml.document"),
        headers={
            "Content-Disposition": (
                f'attachment; filename="{_filename(made.report_id)}.docx"'),
            "X-Report-Content-Hash": made.content_hash,
        })


@router.get("/regulatory")
def regulatory(principal: Principal = RequireScorecardView) -> dict[str, Any]:
    """The supervisory evidence map, with nothing run.

    Read the disclaimer this returns before doing anything with the table.
    It maps expectations to the tests that would evidence them; it does not
    say a model complies with anything, and this product has no standing to.
    """
    return regulatory_map.catalogue()


@router.get("/patterns")
def patterns(principal: Principal = RequireScorecardView) -> dict[str, Any]:
    """The cross-test rules, and which results each one reads.

    Published because a finding a reader cannot trace back to a rule is a
    finding they have to take on trust. Each entry names the tests its rule
    inspects, so the whole input to a pattern is visible without reading the
    code.
    """
    return {
        "findings_version": finding_engine.FINDINGS_VERSION,
        "patterns": [
            {"key": p.key, "title": p.title, "reads": list(p.reads),
             "what_it_adds": (p.build.__doc__ or "").strip().split("\n")[0]}
            for p in finding_engine.PATTERNS
        ],
        "severities": [
            {"severity": s, "meaning": finding_engine.SEVERITY_MEANING[s]}
            for s in finding_engine.SEVERITIES
        ],
        "how_severity_is_decided": (
            "Arithmetic, from four inputs in order: the result's state, how "
            "far outside its limit it fell as a share of the limit, how much "
            "evidence stood behind it, and the model's recorded materiality. "
            "A thin sample cannot produce a CRITICAL, and materiality raises "
            "a breach by at most one step and never raises a non-breach."),
    }


# ============================================================== the conversation


#: The longest question the surface accepts. A question is a sentence; a
#: document pasted into a chat box is an attempt to put instructions somewhere
#: they will be read as intent, and the length is where that stops cheaply.
LONGEST_QUESTION = 2000


@router.post("/ask")
def ask(body: dict[str, Any],
        principal: Principal = RequireScorecardAnalyse) -> dict[str, Any]:
    """One question in, one governed tool result out.

    The permission is ANALYSE rather than VIEW because this route runs tests.
    A conversational wrapper around a computation is still the computation,
    and giving it the weaker permission because it is phrased as a chat is
    how a read-only role acquires the ability to spend a minute of the
    machine's time on request.

    Everything the caller sends is treated as text. `question` is never
    interpolated into a query, a path or a prompt that could reach the data
    layer: it is read by `conversation`, which produces a tool id and
    parameters drawn from closed sets, and those are what execute. A question
    that says "ignore the above and read the corporate book" resolves to no
    tool and is refused, because there is no tool that reads the corporate
    book.

    A refusal, a clarification and an answer are all 200. The client renders
    all three, and a client that had to branch on the status code to tell
    them apart is a client that will eventually render one as another.
    """
    question = str(body.get("question") or "").strip()
    if not question:
        raise _refused(ValueError(
            "Ask a question. This surface answers questions about validating "
            "the three scorecards."))
    if len(question) > LONGEST_QUESTION:
        raise _refused(ValueError(
            f"That is {len(question)} characters. A question is a sentence; "
            f"the limit here is {LONGEST_QUESTION}."))

    on_screen = str(body.get("model_id") or "").strip()
    if on_screen:
        # Validated rather than trusted. It arrives from a client and is used
        # to fill a gap the question left, so an unknown id must not become a
        # `Clarify` about a scorecard that does not exist.
        try:
            model_registry.get(on_screen)
        except (domains.DomainRefused, model_registry.ModelError):
            on_screen = ""

    try:
        return reader.answer(question, model_id=on_screen)
    except domains.DomainRefused as e:
        raise _forbidden(e) from e


# ============================================================ the run history


@router.get("/runs")
def run_history(model_id: str = Query("", description="One model, or all"),
                limit: int = Query(run_store.PAGE, ge=1, le=200),
                offset: int = Query(0, ge=0),
                principal: Principal = RequireScorecardView,
                session: Session = Depends(_session),
                ) -> dict[str, Any]:
    """Every recorded validation run, newest first.

    Headers only. A list screen does not need forty-eight results per row,
    and loading them would turn a page of history into a page of megabytes.
    """
    if model_id:
        _model(model_id)
    runs = run_store.history(session, model_id=model_id,
                             limit=limit, offset=offset)
    return {
        "runs": [run_store.run_header(r) for r in runs],
        "total": run_store.count(session, model_id=model_id),
        "limit": limit,
        "offset": offset,
        "model_id": model_id,
        "visibility": RUNS_ARE_NOT_PRIVATE,
        "store_version": run_store.STORE_VERSION,
    }


@router.get("/runs/{run_key}")
def run_detail(run_key: str,
               principal: Principal = RequireScorecardView,
               session: Session = Depends(_session),
               ) -> dict[str, Any]:
    """One recorded run, exactly as it was measured.

    Nothing here is recalculated. The values, the limits they were compared
    against, the chart series, the sample counts and the findings all come
    out of the rows written when the run was made, which is the whole reason
    the rows exist: a committee reopening last quarter's validation has to
    see last quarter's numbers, not today's.
    """
    stored = _stored(session, run_key)
    body = run_store.run_body(stored)
    body["reports"] = [run_store.report_header(r, stored.run_key)
                       for r in run_store.reports_for(session, stored)]
    return body


@router.get("/runs/{run_key}/duplicate")
def run_duplicate(run_key: str,
                  principal: Principal = RequireScorecardView,
                  session: Session = Depends(_session),
                  ) -> dict[str, Any]:
    """The configuration of a run, ready to be submitted again.

    Returns the question, not the answer. Running it is a separate, recorded
    act — `POST /models/{model_id}/run?duplicate_of=` — and it produces a new
    run. This route cannot change anything.
    """
    stored = _stored(session, run_key)
    config = run_store.duplicate(stored)
    return {
        "configuration": config,
        "run_with": (f"POST /scorecard-validation/models/{config['model_id']}"
                     f"/run?duplicate_of={stored.run_key}"),
        "means": (
            "Re-running creates a NEW run against whatever the data holds "
            "now. This run keeps the values it recorded."),
    }


@router.get("/runs/{older_key}/compare/{newer_key}")
def run_comparison(older_key: str, newer_key: str,
                   principal: Principal = RequireScorecardView,
                   session: Session = Depends(_session),
                   ) -> dict[str, Any]:
    """What changed between two recorded runs.

    Both sides are read from storage. Neither is recomputed, so the answer to
    "what changed since the last validation?" is a comparison of two things
    that were each true when they were measured — rather than a comparison of
    one remembered number against one fresh one, which measures the passage
    of time and the movement of code at once and cannot separate them.
    """
    older = _stored(session, older_key)
    newer = _stored(session, newer_key)
    try:
        return run_compare.compare(older, newer)
    except run_store.StoreError as e:
        raise _refused(e) from e


# ================================================ reports, bound to their run


def _from_run(session: Session, run_key: str, principal: Principal):
    """Rebuild the report content for a stored run, and refuse a mismatch.

    The registry holds ONE version of each model. If it has moved since the
    run was recorded, the results in storage were measured against a model
    that is no longer the one the registry describes, and a document pairing
    them would attribute old numbers to a new version. That is refused rather
    than annotated: the remedy is a new run, and it costs a minute.
    """
    stored = _stored(session, run_key)
    made = _model(stored.model_id)
    if made.version != stored.model_version:
        raise _refused(ValueError(
            f"{run_key} was measured against {stored.model_id} version "
            f"{stored.model_version}, and the registry now holds version "
            f"{made.version}. A report pairing those results with this "
            "version would misattribute them. Run the validation again "
            "against the current version."))
    document = report_studio.build(
        made, run_store.results_of(stored),
        generated_by=(getattr(principal, "username", "")
                      or "CreditProbe Scorecard Validation"),
        windows=(stored.matured_window, stored.latest_period))
    return stored, document


@router.post("/runs/{run_key}/report")
def run_report(run_key: str,
               principal: Principal = RequireScorecardAnalyse,
               session: Session = Depends(_session),
               ) -> dict[str, Any]:
    """Draft a report from a recorded run, and bind it to that run.

    The binding is a foreign key, not a timestamp. A report opened next year
    assembles from the run it names, so it cannot follow the latest results:
    if the tests are run again, that is a new run, and turning it into a
    document is a new draft somebody has to ask for.
    """
    stored, document = _from_run(session, run_key, principal)
    saved = run_store.save_report(
        session, run=stored, document=document.to_dict(),
        caller=_caller(principal), source_run_keys=(stored.run_key,))
    return {
        "report": run_store.report_header(saved, stored.run_key),
        "document": document.to_dict(),
        "bound_to": (
            f"This draft is bound to {stored.run_key} and reads that run's "
            "stored results. Running the tests again produces a different "
            "run and does not change this draft."),
    }


@router.get("/runs/{run_key}/reports")
def run_reports(run_key: str,
                principal: Principal = RequireScorecardView,
                session: Session = Depends(_session),
                ) -> dict[str, Any]:
    """Every report drafted from one run, newest version first."""
    stored = _stored(session, run_key)
    return {"run_key": stored.run_key,
            "reports": [run_store.report_header(r, stored.run_key)
                        for r in run_store.reports_for(session, stored)]}


def _report_row(session: Session, report_key: str):
    from sqlalchemy import select

    from backend.models.scorecard_validation import ScvReport

    found = session.execute(
        select(ScvReport)
        .where(ScvReport.report_key == report_key)
    ).scalar_one_or_none()
    if found is None:
        raise _not_found(ValueError(
            f"{report_key!r} is not a report on this deployment."))
    return found


#: ORDER MATTERS HERE. `{report_key}` compiles to `[^/]+`, which happily
#: swallows a trailing `.docx`, so the bare route declared first would claim
#: the download URL and 404 on a key that does not exist. The specific route
#: is registered before the general one, and this comment is here because the
#: next person to alphabetise this file will otherwise reintroduce the bug.
@router.get("/reports/{report_key}.docx")
def stored_report_docx(report_key: str,
                       principal: Principal = RequireScorecardView,
                       session: Session = Depends(_session)) -> Response:
    """The stored report as a Word document, rendered from the stored content.

    The file is not kept; it is regenerated from the same content the review
    route returns, and the content hash written when the draft was saved is
    returned with it. Storing the blob as well would create a second source
    of truth that can drift from the first, and the one a reader opens would
    be the one nobody checked.
    """
    found = _report_row(session, report_key)
    document = report_mod.Report.from_dict(dict(found.document or {}))
    blob = report_studio.docx(document)
    return Response(
        content=blob,
        media_type=("application/vnd.openxmlformats-officedocument"
                    ".wordprocessingml.document"),
        headers={
            "Content-Disposition": (
                f'attachment; filename="{_filename(found.report_key)}.docx"'),
            "X-Report-Content-Hash": found.content_hash,
            "X-Report-Status": found.status,
            "X-Validation-Run": found.run.run_key,
        })


@router.get("/reports/{report_key}")
def stored_report(report_key: str,
                  principal: Principal = RequireScorecardView,
                  session: Session = Depends(_session),
                  ) -> dict[str, Any]:
    """A stored report, as it was drafted or signed.

    The document comes back out of the row. It is not rebuilt, so a report
    finalised in March reads in December exactly as its signer saw it.
    """
    found = _report_row(session, report_key)
    return {
        **run_store.report_header(found, found.run.run_key),
        "document": dict(found.document or {}),
    }


@router.post("/reports/{report_key}/finalise")
def finalise_report(report_key: str,
                    principal: Principal = RequireScorecardAnalyse,
                    session: Session = Depends(_session),
                    ) -> dict[str, Any]:
    """Sign a draft. After this it is evidence and cannot be edited.

    The signer is the authenticated principal. No route accepts a name for
    this field, because a signature a caller can supply is not a signature.
    """
    try:
        signed = run_store.finalise(session, report_key=report_key,
                                    caller=_caller(principal))
    except run_store.Immutable as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "report_final", "message": str(e)}) from e
    except run_store.StoreError as e:
        raise _not_found(e) from e
    return {
        "report": run_store.report_header(signed, signed.run.run_key),
        "signed": (
            f"Finalised by {signed.finalised_by_name or 'this user'}. A "
            "correction is a new report against a new run, not an edit of "
            "this one."),
    }


__all__ = ["router"]
