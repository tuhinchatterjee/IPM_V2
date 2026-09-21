"""Recovering an answer that was paid for, and never paying twice.

The defect this exists for
--------------------------
Question 1 of the first live UAT made a real provider call, completed, and
was destroyed by the harness that was supposed to score it. `judge()` raised
`SnapshotUnavailable` -- the independent oracle was reading
`data/retail/analytics`, which does not exist in a candidate clone -- and the
process died at the `judge()` call, which sits BEFORE the append and the
`save()`. USD 0.24853 bought an answer that was never written down.

Two properties follow, and this module holds both:

* the answer must be recoverable without asking again, because the worker
  writes `final_response` into the run record on settle and `judge()` is a
  pure function of that record and the source book. A recovery that needed a
  provider would mean paying twice for one answer;
* the recovery must not be able to spend, write to the ledger it reads, or
  quietly lose the record of what the original run cost.

The last one is subtle enough to deserve its own test. `save()` computes the
spend as a DELTA against what the ledger held when the process started, so a
re-judge of yesterday's run computes zero and erases the money by the act of
repairing it. `test_the_recovery_keeps_what_the_answer_cost` pins the fix and
the hazard together.
"""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "scripts" / "retail_cockpit" / "run_uat.py"

#: The real figure from the live run this module exists because of.
Q1_COST_USD = 0.24853


def _runner():
    spec = importlib.util.spec_from_file_location("run_uat_rejudge", RUNNER)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


uat = _runner()

#: The two tables a recovery reads, copied from `run_store.py`'s own DDL so
#: a schema change that breaks the recovery breaks this test rather than the
#: operator's evidence.
_DDL = """
CREATE TABLE runs (
  run_id TEXT PRIMARY KEY, thread_id TEXT NOT NULL, tenant_id TEXT NOT NULL,
  principal_id TEXT NOT NULL, question TEXT NOT NULL, mode TEXT NOT NULL,
  release_id TEXT NOT NULL, ui_filters TEXT NOT NULL DEFAULT '{}',
  state TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 0,
  error_code TEXT NOT NULL DEFAULT '', error_id TEXT NOT NULL DEFAULT '',
  operation TEXT NOT NULL DEFAULT '', final_response TEXT NOT NULL DEFAULT '',
  budget TEXT NOT NULL DEFAULT '{}', startup_sha TEXT NOT NULL DEFAULT '',
  route TEXT NOT NULL DEFAULT 'cockpit_v4',
  cancel_requested INTEGER NOT NULL DEFAULT 0,
  delivered_at TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL, deadline_at TEXT NOT NULL DEFAULT '');
CREATE TABLE reservations (
  reservation_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, purpose TEXT NOT NULL,
  reserved_usd REAL NOT NULL, settled_usd REAL,
  uncertain INTEGER NOT NULL DEFAULT 0, usage TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL);
"""


def _settled(db: Path, *, question: str, values: list[float],
             run_id: str = "run-q1", cost: float = Q1_COST_USD,
             state: str = "COMPLETED") -> Path:
    """A store holding one run that was answered and charged for."""
    final = {
        "disposition": "answer", "narrative": "Recovered from the store.",
        "evidence_bound": True,
        "numeric_claims": [
            {"claim_id": f"c{i}", "decimal_value": str(v), "unit": "SAR"}
            for i, v in enumerate(values)]}
    connection = sqlite3.connect(db)
    connection.executescript(_DDL)
    connection.execute(
        "INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (run_id, "th-q1", "demo-tenant", "uat", question, "standard",
         "cockpitdata-r1.2.0-c1.0.0-s20260910-p7", "{}", state, 3, "", "", "",
         json.dumps(final), json.dumps({"generations": 4}), "", "cockpit_v4",
         0, "", "2026-09-21T06:00:00+00:00", "2026-09-21T06:01:00+00:00", ""))
    connection.execute(
        "INSERT INTO reservations VALUES (?,?,?,?,?,?,?,?)",
        ("res-1", run_id, "generation", 0.30, cost, 0, "{}",
         "2026-09-21T06:00:30+00:00"))
    connection.commit()
    connection.close()
    return db


@pytest.fixture()
def real_book(published_release, monkeypatch):
    """The candidate's own book, opened the way the runner opens it."""
    import os

    from backend.retail_cockpit_adapter.source import open_snapshot

    analytics = os.environ.get("DATA_ANALYTICS_DIR")
    metadata = os.environ.get("METADATA_DIR")
    if not analytics or not metadata:
        pytest.skip("DATA_ANALYTICS_DIR/METADATA_DIR are not configured; "
                    "resolve .env.retail-candidate to run this")
    return open_snapshot(analytics, metadata)


def _q1_oracle_values(snapshot) -> list[float]:
    values, _ = uat.expected_numbers("Q01", snapshot)
    return values[:4]


def _run(monkeypatch, argv: list[str]) -> int:
    monkeypatch.setattr(sys, "argv", ["run_uat.py", *argv])
    return uat.main()


# ------------------------------------------------- it cannot spend, at all

def test_the_recovery_builds_no_client_and_asks_nothing(
        tmp_path, real_book, monkeypatch) -> None:
    """The property that matters is *no money*, not merely *no crash*.

    `Cockpit` is the only thing in the runner that can reach the engine, and
    the only thing that can start a run. If it is never constructed, nothing
    could have been asked and nothing could have been charged -- which is a
    stronger statement than counting requests.
    """
    def _explode(*_: object, **__: object):  # pragma: no cover - must not run
        raise AssertionError("a recovery constructed a client")

    monkeypatch.setattr(uat, "Cockpit", _explode)
    database = _settled(tmp_path / "uat.sqlite3",
                        question=uat.QUESTIONS[0]["ask"],
                        values=_q1_oracle_values(real_book))
    out = tmp_path / "live_uat.json"

    code = _run(monkeypatch, ["--rejudge", "--rejudge-db", str(database),
                              "--out", str(out), "--env-file", ""])

    assert code == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    first = report["questions"][0]
    assert first["run_id"] == "run-q1"
    assert first["judgement"]["kind"] == "oracle"
    assert first["passed"] is True


def test_the_recovery_does_not_write_to_the_ledger_it_reads(
        tmp_path, real_book, monkeypatch) -> None:
    """`mode=ro`, and not by accident.

    `RunStore.__init__` runs `_migrate()`, so building the engine's own store
    class against an operator's evidence ledger would execute DDL against it.
    A recovery reads what was paid for and must not be able to change it.
    """
    database = _settled(tmp_path / "uat.sqlite3",
                        question=uat.QUESTIONS[0]["ask"],
                        values=_q1_oracle_values(real_book))
    before = database.stat().st_mtime_ns

    _run(monkeypatch, ["--rejudge", "--rejudge-db", str(database),
                       "--out", str(tmp_path / "out.json"), "--env-file", ""])

    assert database.stat().st_mtime_ns == before
    # And the connection itself refuses a write.
    connection = uat._ledger(database)
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        connection.execute("UPDATE runs SET state='TAMPERED'")
    connection.close()


def test_the_recovery_refuses_to_combine_with_a_paying_mode(
        monkeypatch) -> None:
    for extra in ("--i-accept-the-cost", "--rehearse"):
        assert _run(monkeypatch, ["--rejudge", extra]) == 2


# --------------------------------------------------------------- the money

def test_the_recovery_keeps_what_the_answer_cost(
        tmp_path, real_book, monkeypatch) -> None:
    """USD 0.24853 is derived from the ledger, and survives being written.

    Two halves, and the second is the one that would have gone wrong. The
    cost comes from `reservations` by `run_id`, because the original entry
    was never saved and there is nothing to carry forward. And `save()` must
    not recompute the totals as a delta against a ledger that has not moved
    since -- which is what it does on every other call site, correctly, and
    what would silently report a paid UAT as free.
    """
    database = _settled(tmp_path / "uat.sqlite3",
                        question=uat.QUESTIONS[0]["ask"],
                        values=_q1_oracle_values(real_book))
    out = tmp_path / "live_uat.json"

    _run(monkeypatch, ["--rejudge", "--rejudge-db", str(database),
                       "--out", str(out), "--env-file", ""])

    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["questions"][0]["cost_usd"] == Q1_COST_USD
    assert report["spend_this_run_usd"] == Q1_COST_USD
    assert "ledger" in report["spend_source"]
    assert report["paid_provider_calls"] is True, (
        "the answers were paid for when they were given; a re-judge does not "
        "make the evidence free")

    # The hazard, pinned: the delta `save()` normally computes is zero here,
    # because the money was spent before this process started.
    from backend.retail_cockpit_host import spend

    assert round(spend.spent(database), 6) == Q1_COST_USD
    delta = round(spend.spent(database) - spend.spent(database), 6)
    assert delta == 0.0, ("if the recovery recomputed the spend as a delta "
                          "it would record this run as free")


# --------------------------------------------------------- it never guesses

def test_it_will_not_score_a_run_that_did_not_answer(
        tmp_path, real_book, monkeypatch) -> None:
    """A FAILED run has no answer, and is not quietly skipped either."""
    database = _settled(tmp_path / "uat.sqlite3",
                        question=uat.QUESTIONS[0]["ask"], values=[1.0],
                        state="FAILED")
    out = tmp_path / "live_uat.json"

    _run(monkeypatch, ["--rejudge", "--rejudge-db", str(database),
                       "--out", str(out), "--env-file", ""])

    first = json.loads(out.read_text(encoding="utf-8"))["questions"][0]
    assert first["passed"] is False
    assert first["judgement"]["kind"] == "run"
    assert first["run_id"] == "run-q1"
    # It IS recorded, because it was really asked and really cost money.
    # That is the distinction a question never asked does not have.
    assert first["cost_usd"] == Q1_COST_USD


def test_it_matches_the_question_exactly_and_says_how(
        tmp_path, real_book, monkeypatch) -> None:
    """Exact equality, because a candidate ledger holds near-miss wordings.

    A candidate's store accumulates every run it has ever driven, including
    earlier rehearsals of differently-worded versions of the same question.
    A `LIKE` here would score the wrong answer with complete confidence, so
    the selection is exact and the entry records which run it chose.
    """
    database = _settled(tmp_path / "uat.sqlite3",
                        question=uat.QUESTIONS[0]["ask"],
                        values=_q1_oracle_values(real_book))
    connection = sqlite3.connect(database)
    connection.execute(
        "INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("run-decoy", "th-decoy", "demo-tenant", "uat",
         uat.QUESTIONS[0]["ask"] + " in 2026-08?", "standard", "rel", "{}",
         "COMPLETED", 3, "", "", "", json.dumps({"disposition": "answer"}),
         "{}", "", "cockpit_v4", 0, "", "2026-09-21T07:00:00+00:00",
         "2026-09-21T07:00:00+00:00", ""))
    connection.commit()
    connection.close()
    out = tmp_path / "live_uat.json"

    _run(monkeypatch, ["--rejudge", "--rejudge-db", str(database),
                       "--out", str(out), "--env-file", ""])

    first = json.loads(out.read_text(encoding="utf-8"))["questions"][0]
    assert first["run_id"] == "run-q1", "the decoy wording was scored"
    assert "1 settled candidate" in first["judged_by"]


def test_it_merges_and_never_drops_what_it_did_not_judge(
        tmp_path, real_book, monkeypatch) -> None:
    """An entry the recovery has nothing to say about survives untouched."""
    database = _settled(tmp_path / "uat.sqlite3",
                        question=uat.QUESTIONS[0]["ask"],
                        values=_q1_oracle_values(real_book))
    out = tmp_path / "live_uat.json"
    kept = {"n": "2", "ask": "already recorded", "passed": True,
            "cost_usd": 0.5, "judgement": {"kind": "denomination",
                                           "passed": True, "why": "kept"}}
    out.write_text(json.dumps({"questions": [kept]}), encoding="utf-8")

    _run(monkeypatch, ["--rejudge", "--rejudge-db", str(database),
                       "--out", str(out), "--env-file", ""])

    entries = {e["n"]: e for e in
               json.loads(out.read_text(encoding="utf-8"))["questions"]}
    assert entries["2"] == kept, "an entry it did not re-judge was altered"
    assert entries["1"]["passed"] is True
    assert [e["n"] for e in
            json.loads(out.read_text(encoding="utf-8"))["questions"]][:2] == \
        ["1", "2"], "the plan's order was not preserved"


# ------------------------------------------- one question, one entry, always

def test_a_recovery_invents_no_entry_for_a_question_never_asked(
        tmp_path, real_book, monkeypatch) -> None:
    """A question with no run has no result, and must not be given one.

    The first draft recorded an `unjudged` row for every question the ledger
    had nothing for. That row is not a preserved record -- nothing was ever
    recorded to preserve -- it is a fabricated failure, and it was counted
    against the pass rate and collided with the real answer when the UAT was
    continued.
    """
    database = _settled(tmp_path / "uat.sqlite3",
                        question=uat.QUESTIONS[0]["ask"],
                        values=_q1_oracle_values(real_book))
    out = tmp_path / "live_uat.json"

    _run(monkeypatch, ["--rejudge", "--rejudge-db", str(database),
                       "--out", str(out), "--env-file", ""])

    report = json.loads(out.read_text(encoding="utf-8"))
    assert [e["n"] for e in report["questions"]] == ["1"], (
        "the recovery invented entries for questions that were never asked")


def test_continuing_a_uat_replaces_a_question_rather_than_repeating_it(
) -> None:
    """The 13-entries-for-12-questions defect, at its mechanism.

    `--rejudge` followed by `run_uat.py --from 2` wrote the re-judge's row
    for question 2 AND the live run's row for question 2, one saying "no
    settled answer" and the other carrying the answer that had just been paid
    for. Both paths appended; neither replaced.
    """
    report = {"questions": [
        {"n": "1", "passed": True},
        {"n": "2", "passed": False,
         "judgement": {"kind": "unjudged", "why": "no settled answer"}},
        {"n": "3", "passed": False}]}

    uat.record_entry(report, {
        "n": "2", "ask": uat.QUESTIONS[1]["ask"], "passed": False,
        "cost_usd": 0.26710,
        "judgement": {"kind": "denomination", "passed": False,
                      "why": "published SAR 0 million at facility grain"}})

    numbers = [e["n"] for e in report["questions"]]
    assert numbers == ["1", "2", "3"], f"a question was repeated: {numbers}"
    second = next(e for e in report["questions"] if e["n"] == "2")
    assert second["judgement"]["kind"] == "denomination", (
        "the later result did not supersede the placeholder")
    assert second["cost_usd"] == 0.26710


def test_an_entry_the_plan_no_longer_names_is_kept_at_the_end() -> None:
    """Merging orders by the plan and drops nothing it did not write."""
    report = {"questions": [{"n": "99", "passed": True, "ask": "retired"}]}
    uat.record_entry(report, {"n": "1", "passed": True})
    assert [e["n"] for e in report["questions"]] == ["1", "99"]


def test_the_tally_counts_the_plan_and_not_the_rows() -> None:
    """"0 of 13 questions passed (12 in the plan)" was the symptom.

    The denominator was the number of rows, so a duplicated row inflated it
    past the plan. It is now the number of PLAN questions that have a result.
    """
    report = {"questions": [
        {"n": "1", "passed": True},
        {"n": "2", "passed": False},
        {"n": "99", "passed": True, "ask": "not in the plan"}]}

    passed, recorded = uat.plan_tally(report)

    assert (passed, recorded) == (1, 2), (
        "the tally counted a row the plan does not name")
    assert recorded <= len(uat.QUESTIONS)
