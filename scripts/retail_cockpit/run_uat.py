#!/usr/bin/env python3
"""The twelve-question live UAT, driven end to end.

    .venv/bin/python scripts/retail_cockpit/run_uat.py

Runs `docs/retail_cockpit/LIVE_UAT_PLAN.md` against a LIVE engine, through the
retail proxy -- the same path a question typed into the UI takes, so the
cumulative spend cap applies to this exactly as it applies to a reader.

**This spends real money.** Roughly $9 against a $15 cap at the candidate
card's rates. It refuses to start unless `check_live.py` says the deployment
is live-ready, and it stops at the cap.

How an answer is judged
-----------------------
Not by reading the prose. Every figure the analyst publishes is a
`numeric_claim` the engine has already bound to an executed cell, so the check
is: **does every number the answer states appear among the numbers the oracle
independently computed, within the oracle's own tolerance?**

That is a real check and it is not the same as "the answer is correct". It
catches a fabricated figure, a wrong denomination, a ratio of averages, an
un-de-duplicated customer total -- because all four produce a number the
oracle does not have. It does not catch an answer that states only true
numbers and draws a wrong conclusion from them. The report says which of the
two it is measuring, and never claims the stronger one.

What stops the run
------------------
* **Question 2 failing.** The plan: "if question 2 fails, the work goes back
  to the steering seam before anything else is spent."
* **A containment failure** -- 9 or 10 answering instead of refusing.
* **The cumulative cap.**

A numerical disagreement on 1 or 3-8 is recorded and the run continues, so one
pass buys the whole picture. It is still a failure in the report.

Everything is written after every question, and `--from N` resumes, so a stop
never costs the questions already paid for. The credential is never read into
a value here, never printed and never written to the evidence file.

What it resolves, and why it resolves it itself
-----------------------------------------------
Before it reads anything it resolves `.env.retail-candidate` the way the
launcher does, anchors every path to the repository root, and prints what it
settled on. It does not need to be started from a shell that sourced the
file, and it refuses a live run against a file that is not there.

That is a repair, not a convenience. This script used to run `check_live.py`
as a subprocess -- which resolved the file correctly and reported LIVE READY
-- and then read its own bare `os.environ` for the oracle's book, the model
name and the ledger the cumulative cap counts. In a shell that had not
sourced the file that meant the oracle read `data/retail/analytics`, a path a
candidate clone does not have, and the cap read a ledger under
`~/.creditprobe` that does not exist and so reported spending nothing.

Nothing is bought before it can be judged
-----------------------------------------
Every month the manifest names must be on disk, and every oracle the plan
names must compute, before a client is constructed. About nine seconds.
Question 1 of the first live UAT was answered, charged USD 0.24853 and then
thrown away when the oracle raised inside `judge()`; the two guards that
should have caught it could not. `--rehearse` runs offline, where every run
settles `PROVIDER_UNAVAILABLE`, so it never reaches the judgement of an
answer at all; and the test that covers the oracle path skips whenever the
candidate release is not visible to the shell running pytest, which in that
shell it was not.

An answer that was paid for is never lost
-----------------------------------------
The evidence entry is appended and written BEFORE it is judged, carrying the
engine's own response verbatim. A judging failure is recorded as
`rejudgeable` and stops the run rather than buying eight more answers it
equally cannot score. `--rejudge` then scores settled runs again out of the
engine's durable store -- read-only, constructing no client, taking each cost
from `reservations` by `run_id` -- so a fault in judging costs a re-run of
the judgement and never the money.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

EVIDENCE = ROOT / "docs" / "retail_cockpit" / "evidence" / "live_uat.json"

#: The twelve, in order, from LIVE_UAT_PLAN.md. `oracle` names a case in
#: `backend.retail_cockpit_adapter.oracle.CASES`; `check` names the special
#: judgement where a number is not what settles it.
QUESTIONS: tuple[dict[str, Any], ...] = (
    {"n": "1", "ask": "What is total exposure at default by product in the "
                      "latest month?",
     "oracle": "Q01", "settles": "the simplest possible agreement"},
    {"n": "2", "ask": "Which facilities carry the largest balances this "
                      "month?",
     "check": "denomination", "stop_on_fail": True,
     "settles": "THE MONEY RULE. Facility grain: does it choose the riyal "
                "column unprompted, or publish SAR 0 million?"},
    {"n": "3", "ask": "Show recognised ECL and coverage by product and "
                      "IFRS 9 stage for the latest month.",
     "oracle": "Q03", "settles": "ratio of sums, not an averaged ratio"},
    {"n": "4", "ask": "Where did the 1-29 day past due population move this "
                      "month?",
     "oracle": "Q05", "settles": "a movement, with the denominator stated"},
    {"n": "5", "ask": "Decompose the ECL movement since last month.",
     "oracle": "Q21", "settles": "against the panel's own attribution"},
    {"n": "6", "ask": "Which customers have the highest debt burden?",
     "oracle": "Q22", "settles": "CUSTOMER grain: is it de-duplicated?"},
    {"n": "7", "ask": "Show the twelve-month ECL trend.",
     "oracle": "Q26", "settles": "a series, not two endpoints"},
    {"n": "8", "ask": "Which behavioural score band carries the most "
                      "exposure?",
     "oracle": "Q17", "settles": "the governed band order, not alphabetical"},
    {"n": "9", "ask": "What is the Early Warning score for these customers?",
     "check": "refusal", "owner": "EWS", "stop_on_fail": True,
     "settles": "A REFUSAL. Another module's domain: it must hand off."},
    {"n": "10", "ask": "Which corporate sectors deteriorated this quarter?",
     "check": "refusal", "stop_on_fail": True,
     "settles": "A REFUSAL. Another book: it must say so."},
    {"n": "11a", "ask": "What is total ECL by product in the latest month?",
     "oracle": "Q03", "settles": "sets up the follow-up"},
    {"n": "11b", "ask": "And which product drove the increase?",
     "follow_up": True, "check": "context",
     "settles": "context retention: stays in the thread, own evidence"},
)

#: Dispositions that mean the Cockpit declined rather than answered.
DECLINED = {"referral", "unsupported"}
ANSWERED = {"answer", "partial_answer"}


# --------------------------------------------------------------- the client

class Cockpit:
    """The proxy, driven the way `check_ready.py` drives it."""

    def __init__(self, api: str, timeout: float) -> None:
        import httpx

        self.base = f"{api.rstrip('/')}/api/v1/cockpit-v4"
        self.client = httpx.Client(timeout=timeout, follow_redirects=True)

    def thread(self) -> str:
        reply = self.client.post(f"{self.base}/threads",
                                 json={"domain": "retail"})
        reply.raise_for_status()
        return str(reply.json()["thread_id"])

    def ask(self, thread_id: str, question: str, mode: str) -> Any:
        return self.client.post(
            f"{self.base}/runs",
            # Unique per question. A fixed key answers IDEMPOTENCY_CONFLICT
            # on a resumed run, which reads as a refusal when it is not one.
            headers={"Idempotency-Key": f"uat-{uuid.uuid4().hex}"},
            json={"question": question, "thread_id": thread_id, "mode": mode})

    def follow(self, run_id: str, deadline: float) -> list[str]:
        """Drain the stream until the run settles. Returns the event names."""
        seen: list[str] = []
        with self.client.stream(
                "GET", f"{self.base}/runs/{run_id}/events",
                params={"cursor": 0},
                headers={"Accept": "text/event-stream"},
                timeout=None) as stream:
            for line in stream.iter_lines():
                if time.monotonic() > deadline:
                    seen.append("(deadline)")
                    break
                if not line.startswith("event: "):
                    continue
                name = line[7:].strip()
                seen.append(name)
                if name == "run.settled":
                    break
        return seen

    def result(self, run_id: str) -> dict[str, Any]:
        reply = self.client.get(f"{self.base}/runs/{run_id}")
        reply.raise_for_status()
        return dict(reply.json())


# ------------------------------------------------------------- the judgement

def _numbers(value: Any, into: list[float]) -> None:
    """Every number reachable in an oracle row, flattened."""
    if isinstance(value, bool):
        return
    if isinstance(value, (int, float)):
        into.append(float(value))
    elif isinstance(value, dict):
        for item in value.values():
            _numbers(item, into)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _numbers(item, into)


def expected_numbers(case_id: str, snapshot: Any) -> tuple[list[float], Any]:
    from backend.retail_cockpit_adapter import oracle as oracle_mod

    expected = oracle_mod.ORACLES[case_id](snapshot)
    found: list[float] = []
    for row in expected.rows:
        _numbers(row, found)
    return found, expected


def claim_values(final: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for claim in final.get("numeric_claims") or []:
        raw = claim.get("decimal_value")
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        out.append({"claim_id": claim.get("claim_id"), "value": value,
                    "unit": claim.get("unit", "")})
    return out


def agrees(value: float, expected: list[float], tolerance: float) -> bool:
    for candidate in expected:
        if abs(value - candidate) <= max(tolerance,
                                         abs(candidate) * tolerance):
            return True
        # A riyal figure against a millions oracle, and the reverse. Both are
        # the same quantity and this book publishes both denominations.
        for scaled in (candidate * 1e6, candidate / 1e6):
            if abs(value - scaled) <= max(tolerance, abs(scaled) * tolerance):
                return True
    return False


def judge(question: dict[str, Any], final: dict[str, Any],
          snapshot: Any) -> dict[str, Any]:
    """What this question was asked to settle, and whether it did."""
    disposition = str(final.get("disposition") or "")
    claims = claim_values(final)
    narrative = str(final.get("narrative") or "")
    kind = question.get("check", "oracle")

    if kind == "refusal":
        owner = str(final.get("referral_owner") or "")
        declined = disposition in DECLINED
        named = bool(owner and owner != "NONE") or bool(
            final.get("referral_reason"))
        ok = declined and named
        return {"kind": "refusal", "passed": ok,
                "disposition": disposition, "referral_owner": owner,
                "reason": str(final.get("referral_reason") or "")[:300],
                "containment_failure": disposition in ANSWERED,
                "why": ("declined and named an owner" if ok else
                        "ANSWERED a question it should have refused"
                        if disposition in ANSWERED else
                        "declined without naming who owns it")}

    if kind == "denomination":
        # The whole point of question 2. A facility balance is ~SAR 100k, so
        # a millions answer rounds it to zero -- which is the failure this is
        # here to catch, in the analyst's own published figures.
        zero_million = any(
            c["value"] == 0 and "million" in c["unit"].lower() for c in claims)
        said_zero_million = "sar 0 million" in narrative.lower()
        riyal_scale = [c for c in claims if abs(c["value"]) >= 1_000]
        ok = bool(claims) and not zero_million and not said_zero_million \
            and bool(riyal_scale)
        return {"kind": "denomination", "passed": ok,
                "claims": claims[:12],
                "why": ("published riyal-scale figures at facility grain"
                        if ok else
                        "published SAR 0 million at facility grain" if
                        (zero_million or said_zero_million) else
                        "published no facility-scale figure at all")}

    if kind == "context":
        ok = disposition in ANSWERED and bool(final.get("evidence_bound"))
        return {"kind": "context", "passed": ok,
                "disposition": disposition,
                "evidence_bound": bool(final.get("evidence_bound")),
                "claims": claims[:12],
                "why": ("stayed in the thread and bound its own evidence"
                        if ok else "did not answer with bound evidence")}

    case_id = question["oracle"]
    expected, spec = expected_numbers(case_id, snapshot)
    unmatched = [c for c in claims
                 if not agrees(c["value"], expected, spec.tolerance)]
    ok = disposition in ANSWERED and bool(claims) and not unmatched
    return {"kind": "oracle", "case": case_id, "passed": ok,
            "disposition": disposition,
            "tolerance": spec.tolerance, "period": spec.period,
            "grain": spec.grain, "unit": spec.unit,
            "claims_total": len(claims), "claims_unmatched": len(unmatched),
            "unmatched": unmatched[:8],
            "why": ("every published figure matches the oracle" if ok else
                    "no figure was published" if not claims else
                    f"{len(unmatched)} published figure(s) match no value the "
                    f"oracle computes")}


# ----------------------------------------------------- the configuration

def _check_live() -> Any:
    """`check_live.py`, loaded by path.

    `scripts/retail_cockpit/` is not a package and is not on `sys.path` --
    only ROOT is -- so this is how the runner reaches its sibling. The module
    has no backend imports at module scope and its `main()` is guarded, so
    loading it costs nothing and does nothing.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "_check_live", ROOT / "scripts" / "retail_cockpit" / "check_live.py")
    if spec is None or spec.loader is None:  # pragma: no cover - unreachable
        raise SystemExit("check_live.py could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _anchored(value: str) -> str:
    return _check_live().anchored(value)


def resolve_environment(env_file: str) -> dict[str, str]:
    """Put the candidate's own configuration into this process, ONCE.

    The defect this exists for
    --------------------------
    `preflight()` ran `check_live.py` as a SUBPROCESS. Since the launcher fix
    that script resolves the env file correctly and reports LIVE READY -- and
    that resolved environment died with the subprocess. This process then read
    its own raw `os.environ` for the oracle's source roots, the model name and
    (through `spend.state_database`) the ledger the cumulative cap counts.

    In a shell that never sourced `.env.retail-candidate` that meant
    `data/retail/analytics`, which does not exist in a candidate clone, so the
    oracle raised `SnapshotUnavailable` AFTER a question had been paid for;
    and a ledger under `~/.creditprobe`, which does not exist either, so
    `spend.spent()` returned 0.0 and this runner's cap guarded nothing.

    The mechanics, and why they live in `check_live`, are documented on
    `check_live.apply_environment`. This must run before any `backend.`
    import.
    """
    return _check_live().apply_environment(env_file)


def describe_environment() -> str:
    """What this process resolved, printed before anything is spent."""
    from backend.retail_cockpit_host import spend

    ledger = spend.state_database()
    held = f"${spend.spent():,.4f} recorded" if ledger.exists() else "absent"
    cap = spend.cap_usd()
    lines = [
        f"  model           {os.environ.get('AI_COCKPIT_REASONING_MODEL') or '(unset)'}",
        f"  price card      {os.environ.get('COCKPIT_V4_PRICE_CARD') or '(unset)'}",
        f"  release         {os.environ.get('COCKPIT_V4_RETAIL_RELEASE_ID') or '(engine default)'}",
        f"  analytics       {os.environ.get('DATA_ANALYTICS_DIR') or '(unset)'}",
        f"  metadata        {os.environ.get('METADATA_DIR') or '(unset)'}",
        f"  state database  {ledger}  ({held})",
        f"  cumulative cap  {'(UNSET -- this runner will not stop)' if cap is None else f'${cap:,.2f}'}",
    ]
    return "\n".join(lines)


# ------------------------------------------------------------------ the gate

def oracle_cases() -> tuple[str, ...]:
    """Every distinct oracle the plan names, in the order it names them."""
    seen: list[str] = []
    for question in QUESTIONS:
        case = question.get("oracle")
        if case and case not in seen:
            seen.append(case)
    return tuple(seen)


def gate(snapshot: Any, *, api: str = "", check_engine: bool = True
         ) -> list[str]:
    """Everything that must hold BEFORE a question is paid for.

    The defect this exists for
    --------------------------
    Question 1 of the live UAT was answered, charged for, and then thrown away
    by `judge()` raising `SnapshotUnavailable` from the oracle. Nothing had
    ever checked that the book the oracle reads was on the disk it was being
    read from.

    Two guards existed and both were structurally blind to it. `--rehearse`
    runs against an offline engine where every run settles
    `PROVIDER_UNAVAILABLE`, so `state != "COMPLETED"` and the oracle branch of
    the loop is unreachable -- a rehearsal can never reach `judge()`. And
    `test_uat_runner.py`'s own book test skips whenever the candidate release
    is not visible, which in a shell that has not resolved the env file is
    always. So the check has to be here, on the machine holding the book, in
    the process about to spend the money.

    Findings, never exceptions: the caller prints all of them and refuses,
    because one run of this is worth more than one finding at a time.
    """
    findings: list[str] = []

    # 1. Every month the manifest names is actually on disk. `verify()` is
    #    the adapter's own helper and needs no change -- its only caller in
    #    the repository was `publish.py`, which is the whole bug. Covering
    #    all 25 months rather than working out which ones the oracles touch
    #    is deliberate: it is a strict superset, it costs nothing (no parquet
    #    is read), and computing the required set would mean a second
    #    implementation of q05/q21/q26's period arithmetic that could drift
    #    from the first.
    findings.extend(snapshot.verify())
    if findings:
        return findings

    # 2. The oracles themselves, computed before anything is asked. This is
    #    the exact code path that crashed, run for free, and it catches more
    #    than a missing partition: a renamed column, a contract field the
    #    projection no longer publishes, a registry key typo. Measured at
    #    ~9 seconds over the candidate book, which is not worth a flag to
    #    skip in front of the one check that would have saved the money.
    for case in oracle_cases():
        try:
            values, _ = expected_numbers(case, snapshot)
        except Exception as exc:  # noqa: BLE001 - reported, never raised
            findings.append(f"oracle {case} cannot be computed from this "
                            f"book: {type(exc).__name__}: {exc}")
            continue
        if not values:
            findings.append(f"oracle {case} produced no numbers to compare "
                            f"an answer against")

    # 3. The book the runner reads is the one the release was projected from.
    #
    #    Stated honestly, because a guard nobody understands is worse than no
    #    guard: THIS WOULD NOT HAVE CAUGHT THE FAILURE ABOVE. `metadata/retail`
    #    is committed to git and carries the same manifest as the candidate's
    #    own copy, so the hashes matched in exactly the misconfiguration that
    #    burned the money -- the manifest resolved and only the parquet did
    #    not. It is here for a different fault: a book that is PRESENT and
    #    DIFFERENT, which produces a confident false verdict rather than a
    #    crash, and which nothing else detects.
    release_id = os.environ.get("COCKPIT_V4_RETAIL_RELEASE_ID", "").strip()
    if release_id:
        findings.extend(_release_findings(release_id, snapshot))

    # 4. The engine about to be paid is reading the book the oracle will
    #    judge against. The only check here that spans the two processes;
    #    everything above compares files this process can already see. It is
    #    the unpaid GET `check_ready.py` already makes.
    if check_engine and api:
        findings.extend(_engine_findings(api, snapshot, release_id))
    return findings


def _release_findings(release_id: str, snapshot: Any) -> list[str]:
    from backend.cockpit_v4 import lake

    try:
        manifest = lake.read_manifest(release_id)
    except Exception as exc:  # noqa: BLE001
        return [f"the release {release_id!r} this runner is configured for "
                f"is not readable from {lake.root()}: {exc}. The runner and "
                f"the engine are not looking at the same lake."]
    projected = str(((manifest.get("notes") or {}).get("projected_from")
                     or {}).get("manifest_hash") or "")
    theirs = str(snapshot.manifest.get("manifest_hash") or "")
    if projected and theirs and projected != theirs:
        return [f"{release_id} was projected from a book with manifest_hash "
                f"{projected[:16]}..., and the oracle is reading one with "
                f"{theirs[:16]}.... The answers and the expected values "
                f"would come from different books."]
    return []


def _engine_findings(api: str, snapshot: Any, release_id: str) -> list[str]:
    import httpx

    from backend.cockpit_v4 import lake

    url = f"{api.rstrip('/')}/api/v1/cockpit-v4/domains"
    try:
        reply = httpx.get(url, timeout=30.0)
        reply.raise_for_status()
        books = list(reply.json().get("domains") or [])
    except Exception as exc:  # noqa: BLE001
        return [f"the engine did not answer {url}: {exc}"]

    book = next((b for b in books if str(b.get("domain_id")) == "retail"), None)
    if book is None:
        return [f"the engine publishes no retail book at {url}"]

    out: list[str] = []
    theirs = str(book.get("release_id") or "")
    if release_id and theirs != release_id:
        out.append(f"the engine is serving {theirs!r} and this runner is "
                   f"configured for {release_id!r}")
    latest = str(book.get("latest_period") or "")
    if latest and latest != snapshot.latest_period:
        out.append(f"the engine's latest period is {latest} and the oracle's "
                   f"book ends at {snapshot.latest_period}")
    if theirs:
        try:
            mine = lake.fingerprint(theirs)
        except Exception:  # noqa: BLE001 - reported by _release_findings
            mine = ""
        engine_print = str(book.get("release_fingerprint") or "")
        if mine and engine_print and mine != engine_print:
            out.append(f"the engine's {theirs} fingerprints as "
                       f"{engine_print[:16]}... and this runner's lake has "
                       f"{mine[:16]}...")
    if book.get("analysis_ready") is False:
        out.append("the engine reports the retail book is not ready for "
                   "analysis; a question would be refused after acceptance")
    return out


# ------------------------------------------------------------------- the run

def preflight(python: str) -> tuple[bool, str]:
    """`check_live.py` against the environment THIS process already resolved.

    `--env-file ""` is the point. Letting the subprocess resolve the file a
    second time would read its `${VAR:-default}` defaults over whatever the
    parent settled on, and the parent and its own preflight could disagree --
    which is the exact shape of the failure this runner is being repaired for.
    `subprocess.run` inherits `os.environ`, so the two are provably the same
    configuration. The launcher follows the same rule.
    """
    done = subprocess.run(
        [python, str(ROOT / "scripts/retail_cockpit/check_live.py"),
         "--env-file", ""],
        capture_output=True, text=True, cwd=str(ROOT))
    return done.returncode == 0, (done.stdout or "") + (done.stderr or "")


# --------------------------------------------------------------- the rejudge

def _ledger(database: Any) -> Any:
    """The engine's store, READ-ONLY.

    `mode=ro` is the same URI `spend.spent()` opens the ledger with, and it
    is not decoration: `RunStore.__init__` runs `_migrate()`, so constructing
    the engine's own class against an operator's evidence ledger would write
    DDL into it. A re-judge reads what was paid for; it must not be able to
    change it.
    """
    import sqlite3

    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True,
                                 timeout=5.0)
    connection.row_factory = sqlite3.Row
    return connection


def settled_run(connection: Any, question: dict[str, Any],
                run_id: str = "") -> tuple[dict[str, Any] | None, str]:
    """The run that answered this question, and how it was chosen.

    Selecting on the exact question text is load-bearing, and so is
    `state='COMPLETED'`: a candidate's state store accumulates every run it
    has ever driven, including near-miss wordings of the same question from
    earlier rehearsals, so a `LIKE` here would score the wrong answer with
    complete confidence. Where a run id is already recorded, it wins -- it is
    unambiguous even across two UAT passes over one ledger.
    """
    if run_id:
        row = connection.execute(
            "SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            return None, f"no run {run_id} in this store"
        return dict(row), f"run_id {run_id}, as recorded in the evidence"

    rows = connection.execute(
        "SELECT * FROM runs WHERE question=? AND state='COMPLETED'"
        " AND final_response <> '' ORDER BY created_at DESC",
        (question["ask"],)).fetchall()
    if not rows:
        return None, "no settled answer to this question in this store"
    how = (f"matched on the question text ({len(rows)} settled "
           f"candidate{'s' if len(rows) != 1 else ''}, newest taken)")
    return dict(rows[0]), how


def run_cost_usd(connection: Any, run_id: str) -> float:
    """What this one run cost, from the engine's own reservations.

    The same `COALESCE` the cumulative cap uses: an unsettled reservation
    counts at what it reserved until it settles for less, so this can never
    under-report what a run has already committed.
    """
    row = connection.execute(
        "SELECT COALESCE(SUM(COALESCE(settled_usd, reserved_usd)), 0.0) "
        "FROM reservations WHERE run_id=?", (run_id,)).fetchone()
    return float(row[0] or 0.0)


def rejudge(args: Any, report: dict[str, Any], snapshot: Any,
            save: Any) -> int:
    """Judge again what has already been answered and paid for.

    Why this exists
    ---------------
    Question 1 of the first live UAT was answered, charged USD 0.24853, and
    then lost: `judge()` raised before the evidence was written, and the
    process died with the only copy of the entry in memory. The answer itself
    survived, because the worker writes `final_response` into the run record
    on settle -- so the money did not have to be spent again, only read.

    It constructs no client, calls no engine and cannot reach a provider: an
    answer is a column in a SQLite row, and `judge()` is a pure function of
    that row and the source book.
    """
    from backend.retail_cockpit_host import spend

    database = args.rejudge_db or spend.state_database()
    if not Path(database).exists():
        print(f"  REFUSING: there is no state database at {database}. "
              f"Point --rejudge-db at the ledger the UAT ran against.")
        return 1
    print(f"  reading {database}\n")

    recorded = {str(e.get("n")): e for e in report["questions"]}
    connection = _ledger(database)
    judged = 0
    # `--from N` means the same here as it does live: this question onward.
    # Everything before it stays exactly as the evidence already has it.
    reached = not args.start
    try:
        for question in QUESTIONS:
            number = str(question["n"])
            if not reached:
                if number != args.start:
                    continue
                reached = True
            previous = recorded.get(number) or {}
            row, how = settled_run(connection, question,
                                   str(previous.get("run_id") or ""))
            if row is None:
                print(f"[{number}] not judged: {how}")
                if number not in recorded:
                    recorded[number] = {
                        "n": number, "ask": question["ask"],
                        "settles": question["settles"], "passed": False,
                        "judged_from": "nothing", "judgement": {
                            "kind": "unjudged", "passed": False, "why": how}}
                continue

            final = json.loads(row["final_response"] or "{}")
            cost = run_cost_usd(connection, row["run_id"])
            entry = dict(previous)
            entry.update({
                "n": number, "ask": question["ask"],
                "settles": question["settles"],
                "thread_id": row["thread_id"], "run_id": row["run_id"],
                "state": row["state"], "error_code": row["error_code"] or "",
                "disposition": final.get("disposition", ""),
                "narrative": str(final.get("narrative") or "")[:1200],
                "final_response": final,
                "budget": json.loads(row["budget"] or "{}"),
                "settled_at": row["created_at"],
                "cost_usd": round(cost, 6),
                "cost_source": ("the engine's reservations ledger, "
                                "by run_id"),
                "judged_from": "ledger", "judged_by": how,
            })
            if str(row["state"]) != "COMPLETED" or not final:
                entry["judgement"] = {
                    "kind": "run", "passed": False,
                    "why": f"the run settled {row['state']} without an "
                           f"answer: {row['error_code'] or 'no code'}"}
            else:
                entry["judgement"] = judge(question, final, snapshot)
            entry["passed"] = bool(entry["judgement"]["passed"])
            recorded[number] = entry
            judged += 1
            mark = "ok  " if entry["passed"] else "FAIL"
            print(f"[{number}] {question['ask']}")
            print(f"      {how}")
            print(f"      {mark} {entry['judgement']['why']}  "
                  f"(${entry['cost_usd']:.5f})")
    finally:
        connection.close()

    # Order by the plan, then anything the plan no longer names, so a merge
    # can neither duplicate an entry nor drop one it did not re-judge.
    plan_order = [str(q["n"]) for q in QUESTIONS]
    report["questions"] = (
        [recorded[n] for n in plan_order if n in recorded]
        + [e for n, e in recorded.items() if n not in plan_order])

    paid = [e for e in report["questions"] if e.get("cost_usd")]
    # The ledger that was actually read, not the one this shell would have
    # defaulted to: with --rejudge-db they can differ, and a total taken
    # from a different store than the per-run costs would be a fiction.
    report["spend_before_usd"] = round(spend.spent(database), 6)
    report["spend_after_usd"] = round(spend.spent(database), 6)
    report["spend_this_run_usd"] = round(
        sum(float(e.get("cost_usd") or 0.0) for e in paid), 6)
    report["spend_source"] = ("the engine's reservations ledger, per run_id. "
                              "These runs were paid for when they were "
                              "answered, not by this re-judge, which spends "
                              "nothing.")
    report["rejudged_at"] = _now()
    report["rejudged_from"] = str(database)
    passed = [e for e in report["questions"] if e.get("passed")]
    report["stopped_because"] = ""
    report["verdict"] = (
        f"RE-JUDGED: {len(passed)} of {len(report['questions'])} recorded "
        f"questions pass ({len(QUESTIONS)} in the plan). No question was "
        f"asked and nothing was spent.")
    save(recompute=False)

    print(f"\n  re-judged {judged} question(s) without a provider call")
    print(f"  ${report['spend_this_run_usd']:.5f} was paid for these answers "
          f"when they were given")
    print(f"  {report['verdict']}")
    print(f"  evidence: {args.out}")
    return 0


def _now() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat(timespec="seconds")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default="http://127.0.0.1:8329")
    parser.add_argument("--mode", default="standard")
    parser.add_argument("--from", dest="start", default="",
                        help="resume at this question number, e.g. 7")
    parser.add_argument("--timeout", type=float, default=300.0,
                        help="seconds allowed for one question")
    parser.add_argument("--out", type=Path, default=EVIDENCE)
    parser.add_argument("--analytics-dir", type=Path, default=None)
    parser.add_argument("--metadata-dir", type=Path, default=None)
    parser.add_argument(
        "--i-accept-the-cost", action="store_true",
        help="required for a live run. This spends real money.")
    parser.add_argument(
        "--rehearse", action="store_true",
        help="drive all twelve against an OFFLINE engine. Proves the "
             "plumbing -- threads, submission, the stream, the result, the "
             "oracles, the cap, the evidence file -- and answers nothing. "
             "Costs nothing and refuses to run against a live engine.")
    parser.add_argument(
        "--env-file", default=str(ROOT / ".env.retail-candidate"),
        help="the candidate configuration to resolve before reading "
             "anything, exactly as the launcher does. Pass an empty string "
             "to use this shell as it stands.")
    parser.add_argument(
        "--rejudge", action="store_true",
        help="re-judge questions that have ALREADY been answered and paid "
             "for, reading the engine's durable store read-only. Asks "
             "nothing, constructs no client, and cannot spend.")
    parser.add_argument(
        "--rejudge-db", type=Path, default=None,
        help="the state database to recover settled runs from. Defaults to "
             "the one this configuration points the engine at.")
    args = parser.parse_args()

    # BEFORE ANY `backend.` IMPORT. `backend/config.py` freezes `settings` at
    # module scope and `lake.root()` is derived from it, so resolving later
    # would leave this process reading a different lake than the engine
    # serves from -- and `config._resolve_dir` would have created a handful
    # of empty directories in the worktree on the way past.
    resolved = resolve_environment(args.env_file)
    if args.env_file and not resolved:
        message = (f"{args.env_file} does not exist, so this process is "
                   f"reading your shell as it stands. That is how a live "
                   f"UAT came to judge a paid answer against a book that "
                   f"was never there.")
        if args.rehearse or not args.env_file:
            print(f"  WARNING: {message}\n")
        else:
            print(f"  REFUSING TO START: {message}")
            print("  Create it from .env.retail-candidate.example, or pass "
                  "--env-file '' if you really mean this shell.")
            return 1
    if not args.env_file:
        print("  --env-file '' : reading this shell as it stands, not the "
              "candidate configuration.\n")

    if args.rejudge and (args.rehearse or args.i_accept_the_cost):
        print("--rejudge re-reads answers that were already paid for. It "
              "cannot be combined with --rehearse or --i-accept-the-cost.")
        return 2

    rehearsal = bool(args.rehearse)
    if args.rejudge:
        print("  RE-JUDGE. Reading answers already settled and paid for, "
              "read-only.\n  No question is asked, no client is built and "
              "nothing can be spent.\n")
    elif rehearsal:
        # The guard that keeps this honest: rehearsal is only meaningful
        # against an engine that CANNOT call out, and only safe there.
        if not os.environ.get("RETAIL_COCKPIT_OFFLINE", "").strip():
            print("--rehearse needs RETAIL_COCKPIT_OFFLINE set, so it cannot "
                  "be pointed at an engine that would spend money.")
            return 2
        print("  REHEARSAL. The engine is offline, so every question will "
              "settle as a provider failure.\n  This proves the runner, not "
              "the Cockpit's answers, and costs nothing.\n")
    elif not args.i_accept_the_cost:
        print("This runs twelve real analyses and spends real money.\n"
              "Re-run with --i-accept-the-cost once you mean it, or "
              "--rehearse to prove the runner for free.")
        return 2

    from backend.retail_cockpit_adapter.source import open_snapshot
    from backend.retail_cockpit_host import spend

    print(describe_environment())
    print()

    if args.i_accept_the_cost:
        ok, detail = preflight(sys.executable)
        print(detail.rstrip())
        if not ok:
            print("\n  REFUSING TO START: check_live.py is not satisfied.")
            return 1

    analytics = args.analytics_dir or Path(
        _anchored(os.environ.get("DATA_ANALYTICS_DIR")
                  or str(ROOT / "data" / "retail" / "analytics")))
    metadata = args.metadata_dir or Path(
        _anchored(os.environ.get("METADATA_DIR")
                  or str(ROOT / "metadata" / "retail")))
    try:
        snapshot = open_snapshot(analytics, metadata)
    except Exception as exc:  # noqa: BLE001
        print(f"  REFUSING TO START: the source book could not be opened "
              f"from {analytics}: {exc}")
        return 1

    # Before the client is built, so a failure here cannot be followed by a
    # question. `Cockpit.__init__` imports httpx; this runs above it.
    print("  checking the book and the oracles before anything is asked...")
    findings = gate(snapshot, api=args.api, check_engine=not args.rejudge)
    if findings:
        for finding in findings:
            print(f"    - {finding}")
        print("\n  REFUSING TO START: the answers could not be judged, so "
              "buying them would waste them.")
        return 1
    print(f"    {len(snapshot.months)} months resolve; "
          f"{len(oracle_cases())} oracles compute.\n")

    started_spend = spend.spent()
    cockpit = None if args.rejudge else Cockpit(args.api,
                                                timeout=args.timeout)

    if args.rejudge:
        evidence_class = ("live provider run, re-judged from the engine's "
                          "durable store")
    elif rehearsal:
        evidence_class = "offline rehearsal -- the runner, not the answers"
    else:
        evidence_class = "live provider run"

    report: dict[str, Any] = {
        "evidence_class": evidence_class,
        "paid_provider_calls": not rehearsal,
        "what_is_measured": (
            "Whether every figure the analyst publishes as a numeric_claim "
            "appears among the values an independent oracle computes from "
            "the source book, at the oracle's own tolerance; whether a "
            "facility-grain money question answers in riyals; whether two "
            "out-of-scope questions are declined and say who owns them; and "
            "whether a follow-up stays in its thread with its own evidence."),
        "what_is_not_measured": (
            "Whether an answer that states only true numbers draws the right "
            "conclusion from them. A human reads the narratives for that."),
        "model": os.environ.get("AI_COCKPIT_REASONING_MODEL", ""),
        "mode": args.mode,
        "spend_before_usd": round(started_spend, 6),
        "questions": [],
    }
    if args.out.exists():
        try:
            previous = json.loads(args.out.read_text(encoding="utf-8"))
            if args.start or args.rejudge:
                report["questions"] = previous.get("questions", [])
        except (OSError, json.JSONDecodeError):
            pass

    def save(recompute: bool = True) -> None:
        """Write the evidence.

        `recompute` exists for the re-judge, and it guards a real hazard: the
        spend figures are a DELTA against what the ledger held when this
        process started, so re-judging a run paid for yesterday would compute
        a delta of zero and erase the record of the money by the very act of
        repairing it. The re-judge sets the two figures from the per-run
        ledger instead and writes with `recompute=False`.
        """
        if recompute:
            report["spend_after_usd"] = round(spend.spent(), 6)
            report["spend_this_run_usd"] = round(
                report["spend_after_usd"] - started_spend, 6)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2, default=str),
                            encoding="utf-8")

    if args.rejudge:
        return rejudge(args, report, snapshot, save)

    started = not args.start
    thread_id = ""
    stopped = ""

    for question in QUESTIONS:
        if not started:
            if question["n"] != args.start:
                continue
            started = True

        verdict = spend.allowed()
        if not verdict.allowed:
            stopped = (f"the cumulative cap of ${verdict.cap_usd:,.2f} was "
                       f"reached (${verdict.spent_usd:,.2f} recorded)")
            break

        if not question.get("follow_up") or not thread_id:
            thread_id = cockpit.thread()

        print(f"\n[{question['n']}] {question['ask']}")
        print(f"      settles: {question['settles']}")
        before = spend.spent()
        accepted = cockpit.ask(thread_id, question["ask"], args.mode)
        if accepted.status_code != 202:
            entry = {"n": question["n"], "ask": question["ask"],
                     "accepted": accepted.status_code,
                     "error": accepted.text[:400], "passed": False}
            report["questions"].append(entry)
            save()
            stopped = (f"question {question['n']} was not accepted "
                       f"({accepted.status_code})")
            break

        run_id = str(accepted.json()["run_id"])
        frames = cockpit.follow(run_id, deadline=time.monotonic()
                                + args.timeout)
        record = cockpit.result(run_id)
        final = dict(record.get("final_response") or {})
        state = str(record.get("state") or "")

        entry: dict[str, Any] = {
            "n": question["n"], "ask": question["ask"],
            "settles": question["settles"],
            "thread_id": thread_id, "run_id": run_id, "state": state,
            "error_code": record.get("error_code") or "",
            "disposition": final.get("disposition", ""),
            "narrative": str(final.get("narrative") or "")[:1200],
            # THE ENGINE'S OWN PAYLOAD, VERBATIM. The summary fields above
            # truncate the narrative and carry no claims at all, so an entry
            # written from them could be read but never re-judged. This is
            # the answer that was paid for; it is evidence, and it is what
            # lets `--rejudge` work from the file rather than the ledger.
            "final_response": final,
            "frames": frames,
            "budget": record.get("budget") or {},
            "cost_usd": round(spend.spent() - before, 6),
            "passed": False,
            "judgement": {
                "kind": "pending", "passed": False,
                "why": "recorded before judging; the judgement had not run"},
        }

        # APPENDED AND WRITTEN BEFORE IT IS JUDGED. Question 1 of the first
        # live UAT was answered, charged for, and lost because `judge()`
        # raised between building this dict and saving it. The money buys the
        # answer; the judgement is an opinion about it, and an opinion that
        # fails must not be able to destroy the thing it was about.
        report["questions"].append(entry)
        save()

        if state != "COMPLETED" or not final:
            entry["judgement"] = {
                "kind": "run", "passed": False,
                "why": f"the run settled {state or 'unknown'} without an "
                       f"answer: {record.get('error_code') or 'no code'}"}
        else:
            try:
                entry["judgement"] = judge(question, final, snapshot)
            except Exception as exc:  # noqa: BLE001
                entry["judgement"] = {
                    "kind": "judge_error", "passed": False,
                    "rejudgeable": True,
                    "why": f"the answer was recorded; judging it raised "
                           f"{type(exc).__name__}: {exc}"}
                entry["passed"] = False
                save()
                # And it STOPS. A fault in judging is systematic, so carrying
                # on would buy eight more answers it equally cannot score.
                stopped = (f"the judgement of question {question['n']} raised "
                           f"{type(exc).__name__}. The answer is recorded and "
                           f"can be re-judged with --rejudge once the cause "
                           f"is fixed; nothing further was bought.")
                print(f"      LOST? no -- recorded. {entry['judgement']['why']}")
                break
        entry["passed"] = bool(entry["judgement"]["passed"])
        save()

        # The ledger this runner counts against must be the one the engine
        # writes to. Nothing before a real settlement can prove that, so it
        # is proven at the first one -- after $0.25 rather than after $9.
        if (not rehearsal and state == "COMPLETED"
                and entry["cost_usd"] == 0.0
                and spend.cap_usd() is not None):
            stopped = (f"question {question['n']} settled COMPLETED and this "
                       f"runner's ledger did not move, so the cumulative cap "
                       f"is not measuring this engine's spend. Check "
                       f"COCKPIT_V4_STATE_DATABASE and "
                       f"COCKPIT_V4_RUNTIME_DIR.")
            save()
            print(f"      STOP  {stopped}")
            break

        mark = "ok  " if entry["passed"] else "FAIL"
        print(f"      {mark} {entry['judgement']['why']}  "
              f"(${entry['cost_usd']:.4f})")

        if not entry["passed"] and question.get("stop_on_fail") \
                and not rehearsal:
            if entry["judgement"].get("containment_failure"):
                stopped = (f"CONTAINMENT FAILURE on question "
                           f"{question['n']}: it answered a question it must "
                           f"refuse")
            else:
                stopped = (f"question {question['n']} failed, and the plan "
                           f"stops the run there rather than spending on the "
                           f"rest")
            break

    report["stopped_because"] = stopped
    passed = [q for q in report["questions"] if q.get("passed")]
    if rehearsal:
        # A rehearsal cannot pass or fail the UAT: nothing was answered. What
        # it reports is whether the RUNNER drove all twelve.
        drove = len(report["questions"])
        report["verdict"] = (
            f"REHEARSAL: the runner drove {drove} of {len(QUESTIONS)} "
            f"questions. No answer was produced and none was possible.")
    else:
        report["verdict"] = (
            "UAT PASSED" if not stopped and len(passed) == len(QUESTIONS)
            else "UAT FAILED")
    save()

    print(f"\n  {len(passed)} of {len(report['questions'])} questions passed "
          f"({len(QUESTIONS)} in the plan)")
    print(f"  spent ${report['spend_this_run_usd']:.4f} this run, "
          f"${report['spend_after_usd']:.4f} recorded in total")
    if stopped:
        print(f"  STOPPED: {stopped}")
    print(f"  {report['verdict']}")
    print(f"  evidence: {args.out}")
    for entry in report["questions"]:
        if not entry.get("passed"):
            print(f"    - [{entry['n']}] "
                  f"{entry.get('judgement', {}).get('why', 'failed')}")
    if rehearsal:
        return 0 if len(report["questions"]) == len(QUESTIONS) else 1
    return 0 if report["verdict"] == "UAT PASSED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
