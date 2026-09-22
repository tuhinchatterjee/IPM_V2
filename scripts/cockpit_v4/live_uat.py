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

A third mode, which spends nothing and calls no provider:

    --rejudge PATH
                  Regrade an ALREADY SETTLED ledger. Reads `final_response`,
                  recovers every governed number from the stored artifacts,
                  runs the independent oracles, grades the chart and
                  clarification expectations and reports the dispositions and
                  the multi-turn behaviour. Every provider door is sealed for
                  the duration, so a path that would have called the model
                  raises instead of spending. The ledger is not written to and
                  the original run ids and spend are preserved.

Usage:
    python3 scripts/cockpit_v4/live_uat.py --dry-run
    python3 scripts/cockpit_v4/live_uat.py --live --cap 25.00 --stop-at 20.00
    python3 scripts/cockpit_v4/live_uat.py --rejudge /path/to/live.sqlite3
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

def published_answer(record: Any) -> dict[str, Any]:
    """The published answer, read from the field the store actually has.

    H-LIVE-01. This used to be `getattr(record, "response", None) or {}`.
    There is no `RunRecord.response`: the dataclass declares
    `final_response` (`run_store.py:327`), the schema column is
    `final_response` (`:71`), `get_run` populates `final_response`
    (`:675`) and the worker settles `outcome.response` INTO
    `final_response` (`:717`). `response` is the name of the field on
    `Outcome`, which is the worker's in-memory result and is not what a
    settled run is read back from.

    So the old expression could only ever evaluate to `{}` -- silently,
    because `getattr` was given a default. The first live UAT recorded a
    blank narrative, a blank disposition, no claims, no charts and no
    clarification for all twenty-eight paid runs while `runs.final_response`
    in the same SQLite file held every one of them.

    No default and no second candidate field: a record that cannot produce
    an answer is a record this returns `{}` for, and the caller's own
    fields then say the run was not settled.
    """
    answer = getattr(record, "final_response", None)
    return dict(answer) if isinstance(answer, dict) else {}


def capture(store, run_id: str, tenant_id: str) -> dict[str, Any]:
    """Everything the approved criteria ask for, from the product's own
    record. Nothing here is recomputed or paraphrased."""
    record = store.get_run(run_id)
    events = [{"type": e.event_type, "at": getattr(e, "created_at", ""),
               "body": getattr(e, "body", None)}
              for e in store.events_since(run_id)]
    submissions = store.submissions_for_run(run_id)
    spend = store.spend(run_id)
    answer = published_answer(record)
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
        # The LIGHTWEIGHT summary is deliberate: a table's rows are already
        # in the ledger, in the artifact the table names, at full precision.
        # Copying them here would double the evidence file and would make
        # the harness the second place a number lives.
        "tables": [{"title": t.get("title"), "artifact_id": t.get("artifact_id"),
                    "rows": len(t.get("rows") or ()),
                    "columns": list(t.get("columns") or ()),
                    "column_units": dict(t.get("column_units") or {})}
                   for t in (answer.get("tables") or ())],
        "charts": [{"kind": c.get("kind"), "title": c.get("title"),
                    "why_this_chart": c.get("why_this_chart", ""),
                    "artifact_id": c.get("artifact_id", ""),
                    "series_units": dict(c.get("series_units") or {}),
                    "points": len(c.get("points") or ())} for c in charts],
        "chart_count": len(charts),
        # WHAT THE GRADER NEEDS AND THE OLD CAPTURE DROPPED.
        #
        # `intent` carries the query mode the run settled on, which is the
        # whole of H-LIVE-03; `validation` carries the finalizer's own
        # warnings, which is how H-LIVE-06's unbound policy number was
        # visible in the first pass and not in the evidence file; and the
        # policy receipt says which governed clauses this turn was given.
        "intent": dict(answer.get("intent") or {}),
        "executed": bool(answer.get("executed")),
        "evidence_bound": bool(answer.get("evidence_bound")),
        "result_only": bool(answer.get("result_only")),
        "result_only_reason": answer.get("result_only_reason", ""),
        "validation": dict(answer.get("validation") or {}),
        "policy_context": dict(answer.get("policy_context") or {}),
        "policy_citations": list(answer.get("policy_citations") or ()),
        "referral_owner": answer.get("referral_owner", ""),
        "referral_reason": answer.get("referral_reason", ""),
        "submissions": submissions,
        "events": events,
        "spend": spend,
    }


# ---- independent numerical reconciliation -------------------------------
#
# H-LIVE-02. What was here compared
#
#     {c.get("claim_id", ""): c.get("canonical", c.get("published")) ...}
#
# against the oracle and then said, in a note, that a human would do the
# join. Neither key exists. `NumericClaim.to_dict` (`contracts.py:940`)
# publishes `claim_id`, `unit`, `evidence`, `display_precision` and
# optionally `decimal_value` and `derivation`; `orchestration` adds
# `display_value` (`:1638`). There is no `canonical` and no `published`, so
# every value in that dict was `None` and the first pass cannot be described
# as independently reconciled.
#
# The three things this now does instead:
#
# 1. THE VALUE COMES FROM THE ARTIFACT, never from text. A direct claim is
#    resolved through the product's own `identity` derivation, which is the
#    same row-key resolution the finalizer used; a derived claim is
#    recomputed with `derivation.compute`, which is the same arithmetic the
#    finalizer checked it with. `display_value` is a rounded string for a
#    reader and is never the comparand.
#
# 2. THE JOIN IS DECLARED IN THE MATRIX, BEFORE THE RUN. `journey.key` names
#    the artifact column holding the oracle's key and `journey.value` names
#    the column holding the figure; both come from the question bank's
#    `Case` and neither is chosen after seeing an answer. Claim ids are the
#    analyst's own and are never assumed to mean anything.
#
# 3. A KEY THE ANSWER NEVER PUBLISHED IS REPORTED MISSING. Silence is the
#    failure mode this is for.


def claim_columns(claim: dict[str, Any]) -> list[str]:
    """Every artifact column this claim reads.

    A DIRECT claim reads the one cell its evidence names. A DERIVED claim
    reads the columns of its operands and has no evidence column of its own,
    which is why a rule written only against `evidence.column_id` compares
    nothing for a total across rows.
    """
    body = claim.get("derivation") or {}
    if body:
        return [str(o.get("column_id") or "")
                for o in (body.get("operands") or [])
                if isinstance(o, dict) and o.get("column_id")]
    column = str((claim.get("evidence") or {}).get("column_id") or "")
    return [column] if column else []


def _claim_artifact_ids(claim: dict[str, Any]) -> list[str]:
    out = [str((claim.get("evidence") or {}).get("artifact_id") or "")]
    for operand in ((claim.get("derivation") or {}).get("operands") or []):
        if isinstance(operand, dict):
            out.append(str(operand.get("artifact_id") or ""))
    return [x for x in out if x]


def evidence_artifacts(store, taken: dict[str, Any],
                       tenant_id: str) -> dict[str, dict[str, Any]]:
    """Every artifact the published answer points at, read from the ledger.

    Tenant-checked by the store, so this cannot reach another tenant's
    evidence, and it reads rows rather than re-running anything.
    """
    ids: list[str] = list(store.artifact_ids_for_run(
        str(taken.get("run_id") or ""), tenant_id=tenant_id))
    for claim in taken.get("numeric_claims") or []:
        ids += _claim_artifact_ids(claim)
    for table in taken.get("tables") or []:
        ids.append(str(table.get("artifact_id") or ""))
    for chart in taken.get("charts") or []:
        ids.append(str(chart.get("artifact_id") or ""))
    out: dict[str, dict[str, Any]] = {}
    for artifact_id in dict.fromkeys(x for x in ids if x):
        record = store.get_artifact(artifact_id, tenant_id=tenant_id)
        if record is not None:
            out[artifact_id] = record
    return out


def governed_value(claim: dict[str, Any],
                   artifacts: dict[str, dict[str, Any]]) -> tuple[Any, str]:
    """The canonical number behind one published claim, or why there is none.

    Both kinds go through `backend.cockpit_v4.derivation`, which is the
    module the finalizer validated the claim with. A direct claim becomes a
    one-operand `identity`, whose row-key resolution accepts `r3`, a bare
    index and `column=value` exactly as the finalizer's did.
    """
    from backend.cockpit_v4 import derivation as deriv

    body = claim.get("derivation")
    if not body:
        ref = claim.get("evidence") or {}
        artifact_id = str(ref.get("artifact_id") or "")
        column_id = str(ref.get("column_id") or "")
        if not artifact_id or not column_id:
            return None, "the claim names no artifact cell"
        body = {"operation": "identity",
                "operands": [{"artifact_id": artifact_id,
                              "column_id": column_id,
                              "row_ids": [str(ref.get("row_key") or "")]}]}
    try:
        return deriv.compute(deriv.parse(body), artifacts), ""
    except Exception as exc:  # noqa: BLE001 - the reason is the evidence
        return None, str(exc)


def _keyed_rows(record: dict[str, Any], key_column: str,
                value_column: str) -> dict[str, Any]:
    """`{key: value}` from one stored artifact, at full precision."""
    if key_column not in record["columns"] \
            or value_column not in record["columns"]:
        return {}
    return {str(row.get(key_column)): row.get(value_column)
            for row in record["rows"]}


def _oracle_key_of(ref: dict[str, Any], journey: Journey,
                   artifacts: dict[str, dict[str, Any]]) -> str:
    """WHICH oracle entry a claim is about, read off its own evidence.

    The claim id is the analyst's word for its own number and is never
    assumed to mean anything. What is trustworthy is the cell the claim
    names: resolve its row against the stored artifact with the product's
    OWN resolver, then read the key column the matrix declared. A claim
    bound to r7 of the sector result is about whatever sector is in r7.
    """
    from backend.cockpit_v4 import derivation as deriv

    record = artifacts.get(str(ref.get("artifact_id") or ""))
    if record is None or not journey.key \
            or journey.key not in record["columns"]:
        return ""
    index = deriv.row_index_for(str(ref.get("row_key") or ""),
                                record["rows"])
    if index < 0:
        return ""
    return str(record["rows"][index].get(journey.key))


def _close(left: Any, right: Any, tolerance: float) -> bool:
    from decimal import Decimal, InvalidOperation

    try:
        a, b = Decimal(str(left)), Decimal(str(right))
    except (InvalidOperation, ValueError, TypeError):
        return str(left) == str(right)
    if b == 0:
        return abs(a) <= Decimal(str(tolerance))
    return abs(a - b) / abs(b) <= Decimal(str(tolerance))


def reconcile(journey: Journey, taken: dict[str, Any], *,
              store: Any = None, tenant_id: str = "") -> dict[str, Any]:
    """Compare the governed evidence with the independent pandas oracle.

    Offline by construction: it reads a settled ledger and recomputes the
    truth with pandas. Nothing here constructs a provider, and it works the
    same on a run settled ten minutes ago and one settled last week.
    """
    if journey.oracle is None:
        return {"has_oracle": False, "checked": False,
                "why": "graded on behaviour, not on a figure"}
    mapping = {"key_column": journey.key, "value_column": journey.value,
               "tolerance": journey.tolerance,
               "declared": "in the approved matrix, before the run"}
    if store is None:
        return {"has_oracle": True, "checked": False, "mapping": mapping,
                "why": "no ledger was supplied to read the governed values"}
    if not journey.value:
        return {"has_oracle": True, "checked": False, "mapping": mapping,
                "why": "the matrix declares no value column for this journey"}
    try:
        expected = journey.oracle()
    except Exception as exc:  # noqa: BLE001 - an oracle that cannot run is news
        return {"has_oracle": True, "checked": False, "mapping": mapping,
                "why": f"oracle failed: {exc}"}

    artifacts = evidence_artifacts(store, taken, tenant_id)
    scalar = not isinstance(expected, dict)
    truth = {"": expected} if scalar else {str(k): v
                                           for k, v in expected.items()}

    # -- the rows the answer published, from the artifacts themselves ----
    rows: dict[str, Any] = {}
    for record in artifacts.values():
        if scalar:
            continue
        rows.update(_keyed_rows(record, journey.key, journey.value))
    row_matches = {k: _close(v, truth[k], journey.tolerance)
                   for k, v in rows.items() if k in truth}
    missing_keys = sorted(set(truth) - set(rows)) if not scalar else []

    # -- the claims the answer wrote, recomputed from that evidence ------
    claims: list[dict[str, Any]] = []
    for claim in taken.get("numeric_claims") or []:
        value, why = governed_value(claim, artifacts)
        ref = claim.get("evidence") or {}
        column = str(ref.get("column_id") or "")
        row_key = str(ref.get("row_key") or "")
        entry: dict[str, Any] = {
            "claim_id": str(claim.get("claim_id") or ""),
            "unit": str(claim.get("unit") or ""),
            "kind": "derived" if claim.get("derivation") else "direct",
            "column_id": column, "row_key": row_key,
            "canonical": None if value is None else str(value),
            # Captured so a reader can SEE that the comparison did not use
            # it. A rounded string is what a person reads, never a comparand.
            "display_value": claim.get("display_value", ""),
            "unresolved": why,
        }
        # WHICH oracle entry this claim is about, decided from the evidence
        # binding and the matrix's declared columns -- not from the claim id,
        # which is the analyst's own word for its own number.
        # ON THE DECLARED MEASURE, decided from the columns the claim
        # actually reads. Every column must be `journey.value`: a sum over
        # the measure is the measure, and a ratio of ECL to EAD reads two
        # columns and is a different number from the one under test.
        columns = claim_columns(claim)
        entry["columns_read"] = columns
        on_the_measure = bool(columns) and all(c == journey.value
                                               for c in columns)
        oracle_key = ("" if scalar or entry["kind"] == "derived"
                      else _oracle_key_of(ref, journey, artifacts))
        comparable = (value is not None and on_the_measure
                      and (scalar or oracle_key in truth))
        if comparable:
            entry["oracle_key"] = oracle_key
            entry["expected"] = str(truth[oracle_key])
            entry["ok"] = _close(value, truth[oracle_key], journey.tolerance)
        else:
            entry["ok"] = None
            entry["why"] = why or (
                f"this claim reads {columns or ['nothing']}, and the matrix "
                f"declares the figure under test is in {journey.value!r}"
                if not on_the_measure else
                "no oracle entry is bound to this claim's evidence row")
        claims.append(entry)

    graded = [c for c in claims if c.get("ok") is not None]
    return {
        "has_oracle": True, "checked": True, "mapping": mapping,
        "expected": truth if scalar else {k: str(v) for k, v in truth.items()},
        "published_rows": {k: str(v) for k, v in rows.items()},
        "rows_matched": sorted(k for k, ok in row_matches.items() if ok),
        "rows_mismatched": sorted(k for k, ok in row_matches.items()
                                  if not ok),
        "rows_missing_from_the_answer": missing_keys,
        "claims": claims,
        "claims_compared": len(graded),
        "claims_not_compared": [c["claim_id"] for c in claims
                                if c.get("ok") is None],
        "ok": (bool(row_matches) or bool(graded))
              and not any(not ok for ok in row_matches.values())
              and all(c["ok"] for c in graded),
    }


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


# ---- offline rejudge of a settled first pass ----------------------------

#: Everything a provider could be built from. Rejudge replaces each one with
#: a raise, so a path that WOULD have called the model fails loudly instead
#: of quietly spending. This is not a promise in a comment; it is the
#: mechanism, and `test_live_uat_rejudge.py` asserts each name is sealed.
PROVIDER_DOORS = (
    ("backend.cockpit_v4.service", "resolve_provider"),
    ("backend.cockpit_v4.service", "credential"),
    ("backend.cockpit_v4.capability", "verify_live"),
    ("backend.llm.anthropic_provider", "AnthropicProvider"),
)


class ProviderForbidden(RuntimeError):
    """A rejudge reached a path that would have constructed the provider."""


def seal_the_provider() -> list[tuple[Any, str, Any]]:
    """Make every provider door raise. Returns what to restore."""
    import importlib

    restore: list[tuple[Any, str, Any]] = []
    for module_name, attribute in PROVIDER_DOORS:
        try:
            module = importlib.import_module(module_name)
        except Exception:  # noqa: BLE001 - an adapter this build lacks
            continue
        if not hasattr(module, attribute):
            continue
        original = getattr(module, attribute)

        def refuse(*_args: Any, _door: str = f"{module_name}.{attribute}",
                   **_kwargs: Any) -> Any:
            raise ProviderForbidden(
                f"{_door} was reached during an offline rejudge. A rejudge "
                f"reads a settled ledger and spends nothing; it must never "
                f"construct the provider.")

        setattr(module, attribute, refuse)
        restore.append((module, attribute, original))
    return restore


def _ledger_runs(store) -> list[tuple[str, str]]:
    """`(thread_id, run_id)` for every run in a settled ledger, in order.

    Read with SQL because `RunStore` has no "every run" accessor -- it is a
    live store and nothing in the product ever wants one. `open_store`
    already counts this table the same way.
    """
    rows = store._connect().execute(
        "SELECT thread_id, run_id FROM runs ORDER BY created_at, rowid"
    ).fetchall()
    return [(str(r["thread_id"]), str(r["run_id"])) for r in rows]


def journeys_for(question: str) -> list[Journey]:
    """Every approved journey whose script contains this exact question.

    EXACT, never fuzzy: a rejudge that guessed which journey a turn belonged
    to could grade it against the wrong expectation, which is the one thing
    a regrade must not do.

    More than one is normal and is not a defect. L01 and L17 ask the same
    question on purpose -- L17 is the negative control for an unnecessary
    clarification -- so the text alone cannot say which thread is which.
    """
    return [j for j in matrix() if question in j.turns]


def resolve_journeys(threads: list[list[dict[str, Any]]],
                     queue: list[str]) -> list[tuple[Journey | None,
                                                     list[str]]]:
    """Which journey each recorded thread is, and what was ambiguous.

    With a QUEUE -- the frozen, approved execution order -- thread `i` is
    `queue[i]`, and the recorded question must be one of that journey's own
    turns or the mapping is refused. Position is the only thing that can
    separate two journeys that ask the same question, and the order the
    queue ran in is a fact the operator holds, not something to infer.

    Without one, a question matching exactly one journey resolves and a
    question matching several resolves to NOTHING and says which ones it
    could have been. Silence would be a graded verdict against a guess.
    """
    out: list[tuple[Journey | None, list[str]]] = []
    index = {j.jid: j for j in matrix()}
    for position, turns in enumerate(threads):
        question = str(turns[0].get("question") or "")
        if position < len(queue):
            wanted = index.get(queue[position])
            if wanted is None:
                out.append((None, [f"unknown journey id {queue[position]!r}"]))
                continue
            if question not in wanted.turns:
                out.append((None, [
                    f"the approved queue puts {wanted.jid} at position "
                    f"{position + 1} and this thread opens with "
                    f"{question!r}, which is not one of its turns"]))
                continue
            out.append((wanted, []))
            continue
        candidates = journeys_for(question)
        if len(candidates) == 1:
            out.append((candidates[0], []))
        elif candidates:
            out.append((None, [j.jid for j in candidates]))
        else:
            out.append((None, []))
    return out


def grade(journey: Journey | None, turns: list[dict[str, Any]]
          ) -> dict[str, Any]:
    """The behavioural verdicts the criteria ask for, from the record alone.

    Every field here is read off a settled run. Nothing is inferred from
    prose and nothing is recomputed by a model.
    """
    last = turns[-1] if turns else {}
    charts = int(last.get("chart_count") or 0)
    disposition = str(last.get("disposition") or "")
    asked = bool(last.get("clarification_question"))
    out: dict[str, Any] = {
        "turns": len(turns),
        "states": [t.get("state", "") for t in turns],
        "dispositions": [t.get("disposition", "") for t in turns],
        "query_modes": [(t.get("intent") or {}).get("query_mode", "")
                        for t in turns],
        "executed": [bool(t.get("executed")) for t in turns],
        "chart_counts": [int(t.get("chart_count") or 0) for t in turns],
        "clarification_asked": [bool(t.get("clarification_question"))
                                for t in turns],
        # OBSERVABLE POLICY PROVENANCE. Empty means the answer carried none,
        # which is the finding rather than the absence of one.
        "policy_context": [t.get("policy_context") or {} for t in turns],
        "policy_citations": [t.get("policy_citations") or [] for t in turns],
        "validation_warnings": [(t.get("validation") or {}).get("warnings")
                                or [] for t in turns],
        # MULTI-TURN BEHAVIOUR, from the record: did each turn after the
        # first actually execute against the book, and did the thread hold?
        "every_turn_executed": all(bool(t.get("executed")) for t in turns),
        "thread_ids": sorted({str(t.get("thread_id", "")) for t in turns}),
    }
    if journey is None:
        out["expectations"] = {"checked": False,
                              "why": "this question is not in the matrix"}
        return out
    expectations: dict[str, Any] = {"checked": True}
    if journey.expect_chart:
        expectations["chart"] = {
            "expected": journey.expect_chart,
            "charts_in_the_final_turn": charts,
            "met": (charts > 0 if journey.expect_chart == "yes"
                    else charts == 0)}
    if journey.expect_clarification:
        expectations["clarification"] = {
            "expected": journey.expect_clarification,
            "asked": asked,
            "met": (asked if journey.expect_clarification == "yes"
                    else not asked)}
    expectations["disposition_of_the_final_turn"] = disposition
    out["expectations"] = expectations
    return out


def rejudge(ledger: Path, *, out: Path, first_pass: Path | None,
            tenant_id: str, queue: list[str] | None = None) -> int:
    """Regrade an ALREADY SETTLED live ledger. Zero provider calls.

    It reads `final_response` (H-LIVE-01), recovers the governed numbers
    from the stored artifacts (H-LIVE-02), runs every independent oracle,
    grades the chart and clarification expectations, and reports the
    dispositions, the multi-turn behaviour and whatever policy provenance
    the answers carry. Run ids and spend are the ledger's own and nothing
    here writes to it.
    """
    from backend.cockpit_v4.run_store import RunStore

    queue = list(queue or ())
    if not ledger.exists():
        print(f"no such ledger: {ledger}")
        return 2
    restore = seal_the_provider()
    try:
        store = RunStore(ledger)
        rows = _ledger_runs(store)
        if not rows:
            print(f"{ledger} holds no runs")
            return 2
        by_thread: dict[str, list[dict[str, Any]]] = {}
        order: list[str] = []
        committed = 0.0
        for thread_id, run_id in rows:
            taken = capture(store, run_id, tenant_id)
            taken["thread_id"] = thread_id
            committed += float(taken["spend"].get("committed_usd") or 0.0)
            if thread_id not in by_thread:
                by_thread[thread_id] = []
                order.append(thread_id)
            taken["turn"] = len(by_thread[thread_id]) + 1
            by_thread[thread_id].append(taken)

        journeys: list[dict[str, Any]] = []
        resolved = resolve_journeys([by_thread[t] for t in order], queue)
        for thread_id, (journey, ambiguous) in zip(order, resolved):
            turns = by_thread[thread_id]
            journeys.append({
                "ambiguous": ambiguous,
                "journey": journey.jid if journey else "",
                "coverage": journey.coverage if journey else "",
                "domain_id": str(turns[0].get("domain_id") or ""),
                "notes": journey.notes if journey else "",
                "expect_chart": journey.expect_chart if journey else "",
                "expect_clarification": (journey.expect_clarification
                                         if journey else ""),
                "thread_id": thread_id,
                "turns": turns,
                "grade": grade(journey, turns),
                "oracle": (reconcile(journey, turns[-1], store=store,
                                     tenant_id=tenant_id)
                           if journey is not None else
                           {"has_oracle": False, "checked": False,
                            "why": "question not in the matrix"}),
            })

        with_oracle = [j for j in journeys if j["oracle"].get("has_oracle")]
        summary = {
            "label": ("RECONSTRUCTED FROM SETTLED FIRST-PASS RUNS · "
                      "NO PROVIDER CALL"),
            "reconstructed": True,
            "live": False,
            "provider_calls": 0,
            "provider_doors_sealed": [f"{m}.{a}" for m, a in PROVIDER_DOORS],
            "source_ledger": str(ledger),
            "source_first_pass_json": str(first_pass) if first_pass else "",
            # The order the operator states the paid runs executed in. Empty
            # means the mapping was done on question text alone, and any
            # thread whose question belongs to two journeys is reported
            # ambiguous rather than graded against a guess.
            "queue": queue,
            "runs": len(rows),
            "threads": len(order),
            # THE LEDGER'S OWN SPEND, summed and not re-priced. A rejudge
            # cannot change what a paid run cost.
            "cumulative_usd": round(committed, 6),
            "journeys_with_an_independent_oracle": [
                j["journey"] for j in with_oracle],
            "journeys_graded_on_behaviour_only": [
                j["journey"] for j in journeys
                if not j["oracle"].get("has_oracle")],
            "reconciled_ok": [j["journey"] for j in with_oracle
                              if j["oracle"].get("ok") is True],
            "reconciled_not_ok": [j["journey"] for j in with_oracle
                                  if j["oracle"].get("checked")
                                  and j["oracle"].get("ok") is not True],
            "rejudged_at": datetime.now(timezone.utc).isoformat(),
            "journeys": journeys,
        }
        if first_pass is not None and first_pass.exists():
            import hashlib

            summary["source_first_pass_sha256"] = hashlib.sha256(
                first_pass.read_bytes()).hexdigest()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(summary, indent=2, default=str) + "\n",
                       encoding="utf-8")
        print(f"rejudged {len(rows)} settled run(s) across {len(order)} "
              f"thread(s); ${committed:.6f} was already committed")
        print("NO PROVIDER CALL WAS MADE")
        print(f"written to {out}")
        return 0
    finally:
        for module, attribute, original in restore:
            setattr(module, attribute, original)


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
    parser.add_argument("--rejudge", default="",
                        help="regrade an ALREADY SETTLED ledger offline; "
                             "makes no provider call and writes nothing to it")
    parser.add_argument("--first-pass", default="",
                        help="the preserved first-pass evidence JSON, "
                             "hashed into the rejudge for provenance")
    parser.add_argument("--queue", default="",
                        help="the order the recorded threads were executed "
                             "in, so two journeys that ask the same question "
                             "can be told apart by position")
    args = parser.parse_args()

    if args.rejudge:
        if args.live or args.dry_run:
            print("--rejudge is offline; do not pass --live or --dry-run")
            return 2
        from backend.cockpit_v4 import lake as lake_mod

        out = Path(args.out) if args.out else (
            ROOT / "docs" / "cockpit_v4" / "evidence" /
            "live_uat_first_pass_rejudge.json")
        return rejudge(
            Path(args.rejudge).expanduser(), out=out,
            first_pass=(Path(args.first_pass).expanduser()
                        if args.first_pass else None),
            tenant_id=lake_mod.DEFAULT_TENANT,
            queue=[x.strip() for x in args.queue.split(",") if x.strip()])

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
            "oracle": (reconcile(journey, turns[-1], store=store,
                                 tenant_id=tenant_id) if turns else {}),
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
