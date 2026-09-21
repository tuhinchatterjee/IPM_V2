#!/usr/bin/env python3
"""
Round H live UAT: drive the approved matrix against a real analyst.

The MODEL is the thing under test here. Everything else -- the store, the
worker, the catalogue, the DuckDB session, the validator, the executor, the
finalizer, the governance record -- is the product's own, unchanged.

Nothing in this file tells the analyst what SQL to write. The bank's SQL and
its pandas oracle are used ONLY to check the answer afterwards. A harness
that handed the query over would be measuring itself.

Two modes:

    --dry-run     ScriptedProvider. Costs nothing. Proves the harness:
                  capture, reconciliation, the cumulative cap, the stop
                  conditions and the evidence file.
    --live        The real provider. Refuses to start unless every
                  pre-flight check is green.

Usage:
    python3 scripts/cockpit_v4/live_uat.py --dry-run
    python3 scripts/cockpit_v4/live_uat.py --live --cap 25.00 --stop-at 20.00
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "tests" / "cockpit_v4"))

APPROVED_MODEL = "claude-opus-5"
APPROVED_RELEASES = {"corporate": "v4-saudi-corporate-20q-v4",
                     "retail": "v4-saudi-retail-20m-v5"}
APPROVED_CARD = "config/cockpit_v4/price_card.claude-opus-5.json"


# ---- stop conditions ----------------------------------------------------

class Stop(RuntimeError):
    """A stop condition fired. The remaining queue is abandoned."""

    def __init__(self, condition: str, detail: str) -> None:
        super().__init__(f"{condition}: {detail}")
        self.condition = condition
        self.detail = detail


@dataclass
class Guard:
    """The cumulative cap, which the PRODUCT does not enforce.

    `spend_ceiling_usd` is per run. `store.spend()` is keyed by run_id and
    there is no tenant or session ledger, so nothing in the product stops
    the twentieth run because the first nineteen were expensive. This does,
    and it is named a harness control rather than described as a product
    guarantee.
    """

    cap_usd: float
    stop_at_usd: float
    per_run_ceiling_usd: float
    committed_usd: float = 0.0
    runs: int = 0
    max_runs: int = 0
    stopped: str = ""

    def before_run(self, label: str) -> None:
        if self.stopped:
            raise Stop("already_stopped", self.stopped)
        if self.max_runs and self.runs >= self.max_runs:
            raise Stop("run_count", f"{self.runs} runs is the approved maximum")
        if self.committed_usd >= self.stop_at_usd:
            raise Stop("stop_at",
                       f"${self.committed_usd:.4f} committed reaches the "
                       f"${self.stop_at_usd:.2f} stop-at threshold")
        # A run may commit up to its own product ceiling. Starting one that
        # COULD cross the hard cap is refused before it is started, not
        # after it has spent.
        if self.committed_usd + self.per_run_ceiling_usd > self.cap_usd:
            raise Stop("hard_cap",
                       f"${self.committed_usd:.4f} committed plus a possible "
                       f"${self.per_run_ceiling_usd:.2f} would exceed the "
                       f"${self.cap_usd:.2f} hard cap")

    def after_run(self, spent_usd: float) -> None:
        self.committed_usd += spent_usd
        self.runs += 1
        if self.committed_usd > self.cap_usd:
            # Belt. Should be unreachable given before_run.
            self.stopped = (f"hard cap breached: ${self.committed_usd:.4f} "
                            f"> ${self.cap_usd:.2f}")
            raise Stop("hard_cap_breached", self.stopped)


def check_served_model(served: str, expected: str) -> None:
    if served and served != expected:
        raise Stop("wrong_model",
                   f"the provider served {served!r}, not {expected!r}")


# ---- the approved matrix ------------------------------------------------

@dataclass
class Journey:
    """One approved journey. `turns` is 1 for a single-turn journey."""

    jid: str
    domain_id: str
    turns: list[str]
    coverage: str
    #: Recompute the truth with pandas. None for a journey graded on
    #: behaviour rather than on a figure.
    oracle: Callable[[], Any] | None = None
    #: What the bank's own SQL is, for the dry run's scripted analyst and
    #: for the reconciliation report. Never shown to a live analyst.
    sql: str = ""
    fields: tuple[str, ...] = ()
    grain: str = ""
    units: str = ""
    key: str = ""
    value: str = ""
    tolerance: float = 0.01
    expect_chart: str = ""          # "", "yes", "no"
    expect_clarification: str = ""  # "", "yes", "no"
    notes: str = ""


_CASES: dict[str, Any] = {}


def _case_index() -> dict[str, Any]:
    """The bank, imported as a PACKAGE module.

    `question_bank` does `from . import domain_oracles`, so importing it as
    a top-level module fails. It has to come in as `cockpit_v4.question_bank`
    with `tests/` on the path -- which is also how pytest loads it, so the
    harness and the suite read the same cases.
    """
    global _CASES
    if not _CASES:
        import importlib
        qb = importlib.import_module("cockpit_v4.question_bank")
        _CASES = {c.case_id: c for c in qb.all_cases()}
    return _CASES


def _from_case(jid: str, case_id: str, coverage: str, *,
               expect_chart: str = "", notes: str = "") -> Journey:
    case = _case_index()[case_id]
    return Journey(
        jid=jid, domain_id=case.domain_id, turns=[case.question],
        coverage=coverage, oracle=case.oracle, sql=case.sql,
        fields=tuple(case.fields), grain=case.grain, units=case.units,
        key=case.key, value=case.value, tolerance=case.tolerance,
        expect_chart=expect_chart, notes=notes or case.notes)


def single_turn() -> list[Journey]:
    """The eighteen approved single-turn journeys."""
    out = [
        _from_case("L01", "C01", "simple Corporate", expect_chart="yes"),
        _from_case("L02", "R01", "simple Retail", expect_chart="yes"),
        _from_case("L03", "C16", "trend"),
        _from_case("L04", "R05", "delinquency", expect_chart="yes"),
        _from_case("L05", "C10", "concentration", expect_chart="yes"),
        _from_case("L06", "C11", "rating movement"),
        _from_case("L07", "R10", "score movement"),
        _from_case("L08", "C35", "migration / staging"),
        _from_case("L09", "C13", "multi-relation"),
        _from_case("L10", "R34", "multi-relation, two-key grain"),
        _from_case("L11", "C05", "ratio and denominator"),
        _from_case("L12", "R15", "portfolio aggregation, single scalar",
                   expect_chart="no",
                   notes="A single coverage ratio. A chart of one number is "
                         "decoration: the Round H restraint rule says say it "
                         "and send no chart."),
    ]
    corp = _case_index()["C01"].domain_id
    out += [
        Journey("L13", corp,
                ["Which sectors contributed most to the change in total ECL "
                 "from the previous quarter?"],
                "ECL decomposition", expect_chart="yes",
                notes="A contribution bridge. Graded on method (a decomposition "
                      "that reconciles to the total move) and form."),
        Journey("L14", corp,
                ["Which sectors deteriorated on at least two of these measures "
                 "over the latest quarter: ECL, Stage 2 share, and ECL "
                 "coverage of exposure?"],
                "complex diagnosis",
                notes="Multi-measure, multi-period. Graded on whether the "
                      "analyst states its own deterioration rule."),
        Journey("L15", corp,
                ["wat is the toatl expsoure at defalt by secter this qtr"],
                "poor English / typo-heavy",
                oracle=_case_index()["C01"].oracle,
                sql=_case_index()["C01"].sql,
                fields=tuple(_case_index()["C01"].fields),
                key=_case_index()["C01"].key,
                value=_case_index()["C01"].value,
                expect_clarification="no",
                notes="Must reach L01's answer. Typos are not an ambiguity, "
                      "and the trace must show entity/value resolution, not a "
                      "fabricated spelling-correction stage."),
        Journey("L16", corp,
                ["Which sectors are above the single-name limit?"],
                "true clarification", expect_clarification="yes",
                notes="The bare word 'exposure' behind 'single-name limit' is "
                      "the documented blocking ambiguity: ead_reported, "
                      "gross_carrying_amount or drawn_balance. CP-1.1 should "
                      "also be retrieved by name after the Round H fix."),
        Journey("L17", corp, [_case_index()["C01"].question],
                "unnecessary-clarification negative control",
                oracle=_case_index()["C01"].oracle,
                sql=_case_index()["C01"].sql,
                fields=tuple(_case_index()["C01"].fields),
                key=_case_index()["C01"].key,
                value=_case_index()["C01"].value,
                expect_clarification="no", expect_chart="yes",
                notes="Every term resolves. Asking here is the failure."),
        Journey("L18", corp,
                ["For each borrower, what is the average utilisation of their "
                 "facilities this quarter, and how many facilities does each "
                 "have?"],
                "grain refusal + analyst-authored repair",
                notes="Borrower grain from a facility-grain relation. The "
                      "product must refuse an ungoverned collapse and the "
                      "ANALYST must author the corrected submission. "
                      "CreditProbe must not rewrite the SQL."),
    ]
    return out


def chains() -> list[Journey]:
    """The five approved multi-turn chains."""
    import importlib
    oracle = importlib.import_module("cockpit_v4.domain_oracles")
    from backend.cockpit_v4 import domains as dom

    corp_latest = oracle.latest_period(dom.CORPORATE)
    out = [
        Journey("M01", dom.CORPORATE,
                ["What is total exposure at default?",
                 "And for the Construction sector?",
                 "How much of that is project finance?",
                 "How much of that is impaired?"],
                "multi-turn narrowing",
                notes="Each turn must inherit the filters of the one before."),
        Journey("M02", dom.CORPORATE,
                ["What is total exposure at default?",
                 "And for the Manufacturing sector?",
                 "How much of that is project finance?",
                 "How much of that is impaired?",
                 "How did that compare a quarter ago?"],
                "period-changing follow-up",
                notes="The last turn changes the PERIOD and nothing else. "
                      f"Latest corporate period is {corp_latest}."),
        Journey("M03", dom.RETAIL,
                ["What is total exposure at default?",
                 "And for Credit Card?",
                 "And within the Payroll segment?",
                 "How much of that is past due?",
                 "And what is the ECL on it?"],
                "multi-turn narrowing, Retail"),
        Journey("M04", dom.RETAIL,
                ["What is total exposure at default?",
                 "And for Personal Finance?",
                 "And within the Affluent segment?",
                 "How much of that is past due?",
                 "How did that compare a month ago?"],
                "period-changing follow-up, Retail"),
        Journey("M05", dom.CORPORATE,
                ["Which sectors are above the single-name limit?",
                 "Exposure at default",
                 "Just the top five by that measure",
                 "And how much of that is Stage 2?"],
                "narrowing across a clarification",
                expect_clarification="yes",
                notes="Turn 2 ANSWERS turn 1's clarification. The Round H "
                      "history projection must carry `you_asked` so the "
                      "analyst does not have to guess what three words mean."),
    ]
    return out


def matrix() -> list[Journey]:
    return single_turn() + chains()


# ---- capture ------------------------------------------------------------

def capture(store, run_id: str, tenant_id: str) -> dict[str, Any]:
    """Everything the approved criteria ask for, from the product's own
    record. Nothing here is recomputed or paraphrased."""
    record = store.get_run(run_id)
    events = [{"type": e.event_type, "at": getattr(e, "created_at", ""),
               "body": getattr(e, "body", None)}
              for e in store.events_since(run_id)]
    submissions = store.submissions_for_run(run_id)
    spend = store.spend(run_id)
    answer = getattr(record, "response", None) or {}
    charts = list(answer.get("charts") or ())
    return {
        "run_id": run_id,
        "state": str(getattr(record, "state", "")),
        "error_code": str(getattr(record, "error_code", "") or ""),
        "question": getattr(record, "question", ""),
        "domain_id": getattr(record, "domain_id", ""),
        "release_id": getattr(record, "release_id", ""),
        "release_fingerprint": getattr(record, "release_fingerprint", ""),
        "disposition": answer.get("disposition", ""),
        "narrative": answer.get("narrative", ""),
        "canonical_mappings": answer.get("canonical_mappings"),
        "resolved_assumptions": answer.get("resolved_assumptions"),
        "blocking_ambiguities": answer.get("blocking_ambiguities"),
        "clarification_question": answer.get("clarification_question", ""),
        "clarification_options": answer.get("clarification_options") or [],
        "coverage": answer.get("coverage") or [],
        "limitations": answer.get("limitations") or [],
        "suggested_questions": answer.get("suggested_questions") or [],
        "numeric_claims": answer.get("numeric_claims") or [],
        "tables": [{"title": t.get("title"), "artifact_id": t.get("artifact_id"),
                    "rows": len(t.get("rows") or ())}
                   for t in (answer.get("tables") or ())],
        "charts": [{"kind": c.get("kind"), "title": c.get("title"),
                    "why_this_chart": c.get("why_this_chart", ""),
                    "points": len(c.get("points") or ())} for c in charts],
        "chart_count": len(charts),
        "submissions": submissions,
        "events": events,
        "spend": spend,
    }


def reconcile(journey: Journey, taken: dict[str, Any]) -> dict[str, Any]:
    """Compare the published figures with the independent pandas oracle."""
    if journey.oracle is None:
        return {"checked": False,
                "why": "graded on behaviour, not on a figure"}
    try:
        expected = journey.oracle()
    except Exception as exc:  # noqa: BLE001 - an oracle that cannot run is news
        return {"checked": False, "why": f"oracle failed: {exc}"}
    published = {c.get("claim_id", ""): c.get("canonical", c.get("published"))
                 for c in taken.get("numeric_claims") or []}
    return {"checked": True, "expected": expected, "published": published,
            "tolerance": journey.tolerance,
            "note": "compared by hand in the report: the analyst chooses its "
                    "own claim ids, so an automatic join would assume the "
                    "mapping this is meant to check"}


# ---- where the ledger lives ---------------------------------------------

#: The paid ledger and the scripted one are DIFFERENT FILES.
#:
#: They used to be one. The dry run settles real reservations -- scripted
#: token counts priced at the real card -- so it leaves a ledger with
#: committed spend in it, and the live pre-flight then has to decide whether
#: that spend is real. There is nothing in the store to decide it WITH: the
#: schema records no provider or model anywhere. `runs`, `reservations` and
#: `events` have no such column, and the whole event stream contains zero
#: occurrences of "model". `startup_sha` is "live-uat" in both modes.
#:
#: So the only sound answer to "is this spend real?" is never to have mixed
#: the two. Two paths, chosen by the mode, and no deletion is needed for the
#: live one at all.
STATE_DIR = Path("/tmp/cockpit_v4_live_uat")
DRY_RUN_DB = STATE_DIR / "dry_run.sqlite3"
LIVE_DB = STATE_DIR / "live.sqlite3"


def state_db_for(*, live: bool, override: str = "") -> Path:
    if override:
        return Path(override).expanduser()
    return LIVE_DB if live else DRY_RUN_DB


def open_store(db: Path, *, live: bool):
    """The store for this mode, opened under the rule its mode deserves.

    A scripted ledger is disposable and is recreated each run: nothing live
    can ever have written to it, because live never opens this path.

    A live ledger is NEVER deleted here. If one already holds anything, the
    run refuses to start and says where it is. Moving a paid record aside is
    an operator's decision, and a harness that made it silently would be the
    one thing a spend control must never do.
    """
    from backend.cockpit_v4.run_store import RunStore

    db.parent.mkdir(parents=True, exist_ok=True)
    if not live:
        if db.exists():
            db.unlink()
        return RunStore(db)

    store = RunStore(db)
    conn = store._connect()
    runs = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
    reservations = conn.execute(
        "SELECT COUNT(*) FROM reservations").fetchone()[0]
    if runs or reservations:
        raise Stop(
            "live_ledger_not_empty",
            f"{db} already holds {runs} run(s) and {reservations} "
            f"reservation(s). A live UAT starts from an empty ledger. Move "
            f"that file aside yourself and re-run; nothing has been deleted.")
    return store


# ---- the runner ---------------------------------------------------------

def build_runtime(live: bool, capability, provider, *, state_db: Path):
    from backend.cockpit_v4 import analytical_runtime as arun
    from backend.cockpit_v4 import config as config_mod
    from backend.cockpit_v4 import domains as dom
    from backend.cockpit_v4.service import Runtime

    book = arun.for_domain(dom.CORPORATE)
    cfg = config_mod.V4Config(
        enabled=True, provider="anthropic",
        reasoning_model=capability.model_id,
        runtime_dir=STATE_DIR,
        state_database=str(state_db),
        release_id=book.release_id, api_port=8414, ui_port=5414,
        local_demo_auth=True, price_card_path=APPROVED_CARD,
        memory_enabled=False, memory_model="", default_mode="standard",
        heartbeat_seconds=5.0, lease_heartbeat_seconds=2.0,
        lease_stale_seconds=10.0, supervisor_poll_seconds=2.0,
        credential_present=live, missing=())
    return Runtime(cfg=cfg, capability=capability, provider=provider,
                   catalog=book.catalog, coverage=None,
                   release_summary=book.release_summary())


def run_turn(store, runtime, *, thread_id: str, domain_id: str,
             question: str, tenant_id: str) -> tuple[Any, str]:
    from backend.cockpit_v4 import domain_resolver as resolver
    from backend.cockpit_v4.worker import Worker

    scope = resolver.scope_for(domain_id)
    if scope.release_id != APPROVED_RELEASES[domain_id]:
        raise Stop("source_release_mismatch",
                   f"{domain_id} resolved to {scope.release_id}, not "
                   f"{APPROVED_RELEASES[domain_id]}")
    record, _created = store.accept_run(
        thread_id=thread_id, tenant_id=tenant_id, principal_id="u1",
        question=question, mode="standard", release_id=scope.release_id,
        domain_id=domain_id, release_fingerprint=scope.release_fingerprint,
        ui_filters={}, idempotency_key="", body_digest="",
        startup_sha="live-uat", deadline_at="")
    started = time.monotonic()
    outcome = Worker(store=store, runtime=runtime).execute(record)
    latency_ms = int((time.monotonic() - started) * 1000)
    return outcome, record.run_id, latency_ms


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--cap", type=float, default=25.0)
    parser.add_argument("--stop-at", type=float, default=20.0)
    parser.add_argument("--max-runs", type=int, default=0)
    parser.add_argument("--only", default="")
    parser.add_argument("--out", default="")
    parser.add_argument("--state-db", default="",
                        help="override the ledger path for this mode")
    args = parser.parse_args()

    if args.live == args.dry_run:
        print("choose exactly one of --live and --dry-run")
        return 2

    from backend.cockpit_v4 import capability as cap_mod
    from backend.cockpit_v4 import config as config_mod
    from backend.cockpit_v4 import lake
    from backend.cockpit_v4.run_store import RunStore

    tenant_id = lake.DEFAULT_TENANT

    if args.live:
        capability = cap_mod.load_price_card(
            APPROVED_CARD, model_id=APPROVED_MODEL, provider="anthropic")
        from backend.cockpit_v4.service import resolve_provider
        cfg = config_mod.load()
        if cfg.missing:
            print(f"NOT READY: {', '.join(cfg.missing)}")
            return 1
        provider = resolve_provider(cfg)
        capability = cap_mod.verify_live(capability, provider)
        print(f"model verified live: {capability.model_id}")
    else:
        from conftest import ScriptedProvider  # noqa: F401
        capability = cap_mod.load_price_card(
            APPROVED_CARD, model_id=APPROVED_MODEL, provider="anthropic")
        provider = None  # set per turn below

    db = state_db_for(live=bool(args.live), override=args.state_db)
    runtime = build_runtime(args.live, capability, provider, state_db=db)
    try:
        store = open_store(db, live=bool(args.live))
    except Stop as stop:
        print(f"STOP [{stop.condition}] {stop.detail}")
        return 1
    print(f"ledger: {db}")

    guard = Guard(cap_usd=args.cap, stop_at_usd=args.stop_at,
                  per_run_ceiling_usd=config_mod.ANALYTICAL_STANDARD_LIMITS
                  .spend_ceiling_usd, max_runs=args.max_runs)

    # --only IS AN ORDER, NOT JUST A FILTER.
    #
    # A comprehension over `matrix()` keeps the DEFINITION order however the
    # ids were listed, so an approved queue that runs the load-bearing
    # journeys first would silently execute in the order this file happens
    # to declare them. The run order is a spend decision -- it decides what
    # is already proven when a cap stops the queue -- so the caller's order
    # is the one that runs.
    #
    # An id that is not in the matrix stops the run rather than being
    # skipped: a typo in an approved queue must not quietly shorten it.
    if args.only:
        index = {j.jid: j for j in matrix()}
        asked = [x.strip() for x in args.only.split(",") if x.strip()]
        unknown = [x for x in asked if x not in index]
        if unknown:
            print(f"unknown journey id(s): {', '.join(unknown)}")
            return 2
        wanted = [index[x] for x in asked]
    else:
        wanted = matrix()
    results: list[dict[str, Any]] = []
    stopped: dict[str, Any] | None = None

    for journey in wanted:
        thread_id = store.create_thread(
            tenant_id=tenant_id, principal_id="u1",
            domain_id=journey.domain_id,
            release_id=APPROVED_RELEASES[journey.domain_id])
        turns: list[dict[str, Any]] = []
        try:
            for index, question in enumerate(journey.turns, 1):
                guard.before_run(f"{journey.jid}.{index}")
                if args.dry_run:
                    runtime.provider = _scripted_for(journey, question)
                outcome, run_id, latency_ms = run_turn(
                    store, runtime, thread_id=thread_id,
                    domain_id=journey.domain_id, question=question,
                    tenant_id=tenant_id)
                taken = capture(store, run_id, tenant_id)
                served = _served_model(taken)
                if args.live:
                    check_served_model(served, APPROVED_MODEL)
                spent = float(taken["spend"].get("committed_usd") or 0.0)
                guard.after_run(spent)
                taken.update(turn=index, question=question,
                             latency_ms=latency_ms, served_model=served,
                             cumulative_usd=round(guard.committed_usd, 6))
                turns.append(taken)
                print(f"  {journey.jid}.{index} {taken['state']:<12} "
                      f"${spent:.4f}  cum ${guard.committed_usd:.4f}  "
                      f"{latency_ms}ms")
        except Stop as stop:
            stopped = {"journey": journey.jid, "condition": stop.condition,
                       "detail": stop.detail}
            print(f"STOP [{stop.condition}] {stop.detail}")
            results.append({"journey": journey.jid,
                            "coverage": journey.coverage,
                            "domain_id": journey.domain_id,
                            "notes": journey.notes, "turns": turns,
                            "stopped": stopped})
            break
        except Exception as exc:  # noqa: BLE001 - a harness fault is evidence
            stopped = {"journey": journey.jid, "condition": "harness_error",
                       "detail": f"{exc}\n{traceback.format_exc()[-1200:]}"}
            print(f"HARNESS ERROR in {journey.jid}: {exc}")
            results.append({"journey": journey.jid, "turns": turns,
                            "stopped": stopped})
            break
        results.append({
            "journey": journey.jid, "coverage": journey.coverage,
            "domain_id": journey.domain_id, "notes": journey.notes,
            "expect_chart": journey.expect_chart,
            "expect_clarification": journey.expect_clarification,
            "turns": turns,
            "oracle": reconcile(journey, turns[-1]) if turns else {},
        })

    summary = {
        "label": ("REAL PROVIDER · REAL DATABASE · REAL WORKER"
                  if args.live else
                  "MODEL MOCK · REAL DATABASE · REAL WORKER · HARNESS DRY RUN"),
        "live": bool(args.live),
        "model": capability.model_id,
        "price_card": APPROVED_CARD,
        "price_card_source": capability.source,
        "price_card_verified_at": capability.verified_at,
        "releases": APPROVED_RELEASES,
        "cap_usd": args.cap, "stop_at_usd": args.stop_at,
        "per_run_ceiling_usd": guard.per_run_ceiling_usd,
        "runs": guard.runs,
        "cumulative_usd": round(guard.committed_usd, 6),
        "stopped": stopped,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "journeys": results,
    }
    out = Path(args.out) if args.out else (
        ROOT / "docs" / "cockpit_v4" / "evidence" /
        ("live_uat.json" if args.live else "live_uat_dry_run.json"))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2, default=str) + "\n",
                   encoding="utf-8")
    print(f"\n{guard.runs} runs, ${guard.committed_usd:.4f} committed")
    print(f"evidence written to {out}")
    return 1 if stopped else 0


def _served_model(taken: dict[str, Any]) -> str:
    for event in reversed(taken.get("events") or []):
        body = event.get("body") or {}
        if isinstance(body, dict) and body.get("model"):
            return str(body["model"])
    return ""


def _scripted_for(journey: Journey, question: str):
    """The dry run's stand-in analyst.

    It submits the BANK's SQL, which is exactly what a live analyst must NOT
    be given. That is the point of the dry run: it exercises the harness --
    capture, reconciliation, the ledger, the cap -- on a path where the
    answer is already known, so a failure here is the harness's and not the
    model's.
    """
    from conftest import ScriptedProvider, ScriptedResult, final, intent, tool_call
    from test_domain_execution import execute_call

    if not journey.sql:
        return ScriptedProvider([ScriptedResult(tool_calls=[tool_call(
            "finalize_response",
            final(intent=intent("PRODUCT_HELP", "COCKPIT"),
                  disposition="answer",
                  narrative="No bank SQL for this journey; the dry run "
                            "exercises the harness only."))])])

    def answer(messages):
        body = json.loads(messages[-1]["content"][0]["content"])
        step = body["steps"][0]
        return ScriptedResult(tool_calls=[tool_call(
            "finalize_response",
            final(intent=intent("DATA_ANALYSIS", "COCKPIT"),
                  disposition="answer",
                  narrative="The figure is {{claim.figure}}.",
                  numeric_claims=[{
                      "claim_id": "figure", "unit": journey.units or "SAR million",
                      "evidence": {"artifact_id": step["artifact_id"],
                                   "row_key": "0",
                                   "column_id": journey.value or "ead_sar_mn"}}]))])

    import importlib
    oracle = importlib.import_module("cockpit_v4.domain_oracles")
    period = oracle.latest_period(journey.domain_id)
    return ScriptedProvider([
        ScriptedResult(tool_calls=[execute_call(
            journey.sql, purpose=question,
            grain=journey.grain or "portfolio",
            units=journey.units or "SAR million",
            subquestions=[question], fields=list(journey.fields),
            month=period)]),
        answer])


if __name__ == "__main__":
    raise SystemExit(main())
