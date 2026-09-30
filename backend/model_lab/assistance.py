"""
ASSISTED_V1: a deterministic, lab-only assistance packet for small models.

The packet carries ONLY metadata CreditProbe already knows deterministically:
the question as asked, the analytical intent, the grain, the relevant
relations and fields with their catalogue definitions and units, the
reporting calendar, the catalogue's own join keys and warnings, the filters
the wording implies, an output contract, generic tool-contract reminders and
evidence discipline. It never carries an expected value, an oracle result,
an Opus output, solution SQL or a cause.

Delivery seam: `AssistedProvider` wraps the lab's provider for an ASSISTED_V1
child and appends the packet as ONE extra system text block to each request
it forwards. The frozen engine is not modified: its prompts, history,
validators, executor and Finalizer are the same objects, and the copy it
holds is never mutated. FROZEN_BASELINE children are never wrapped.

Known limitation, disclosed in every packet record: the frozen engine counts
input tokens before the call, so the packet's tokens are not in that count.
The packet is kept small, and its size is recorded.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from backend.model_lab import benchmark_questions as bq

PACKET_VERSION = "assisted-v1.0"
LANE_BASELINE = "FROZEN_BASELINE"
LANE_ASSISTED = "ASSISTED_V1"
LANES = (LANE_BASELINE, LANE_ASSISTED)
HEADER = "CREDITPROBE ASSISTANCE PACKET (ASSISTED_V1)"


def _catalog():
    from backend.cockpit_v4 import analytical_runtime as arun
    return arun.for_domain(bq.DOMAIN).catalog


def _unit(unit: str, currency: str, scale: str) -> str:
    return {"rcy": f"{currency} {scale}", "probability_0_1":
            "probability (0 to 1)", "percent": "percent", "times": "times",
            "notches": "rating notches", "days": "days",
            "count": "count / flag"}.get(unit, unit or "text")


def build_packet(qid: str, catalog: Any = None) -> dict[str, Any]:
    """The exact packet for one question. Pure function of the question
    registry and the frozen catalogue: same inputs, same bytes."""
    q = bq.get(qid)
    cat = catalog or _catalog()
    specs = {r.name: r for r in cat.specs}
    slots = list(cat.calendar.slots)
    latest, previous = slots[-1], slots[-2]
    tables, fields = [], []
    for rel in q.relations:
        r = specs[rel]
        tables.append({"relation": rel, "grain": r.grain,
                       "period_column": r.period_column,
                       "key_columns": list(r.key_columns),
                       "description": r.description})
        by_name = {f.name: f for f in r.fields}
        for name in q.fields.get(rel, ()):
            f = by_name[name]
            fields.append({"field": f"{rel}.{name}",
                           "label": f.business_label, "type": f.dtype,
                           "unit": _unit(f.unit, cat.reporting_currency,
                                         cat.amount_scale),
                           "definition": f.description})
    joins = []
    for left, right in q.joins:
        if left == right:
            r = specs[left]
            joins.append({"left": left, "right": f"{left} (another quarter)",
                          "keys": [k for k in r.key_columns
                                   if k != r.period_column],
                          "note": "pair the same entity across two "
                                  "reporting quarters; each side keeps its "
                                  "own reporting_quarter filter"})
            continue
        j = next(x for x in (cat.joins() if callable(cat.joins) else cat.joins)
                 if {x["left"], x["right"]} == {left, right})
        joins.append({"left": j["left"], "right": j["right"],
                      "keys": list(j["on"]), "cardinality": j["cardinality"],
                      "warning": j.get("warning", "")})
    period_words = {"latest": f"latest quarter = {latest}",
                    "previous": f"preceding quarter = {previous}"}
    packet = {
        "packet_version": PACKET_VERSION,
        "question_id": q.qid,
        "1_user_question": q.text,
        "2_domain": bq.DOMAIN,
        "3_analytical_intent": list(q.intent),
        "4_primary_data_grain": q.grain,
        "5_relevant_tables": tables,
        "6_relevant_fields": fields,
        "7_metric_definitions": [
            {"metric": m} for m in q.metrics] + [
            {"field": f["field"], "definition": f["definition"]}
            for f in fields if f["unit"].startswith(cat.reporting_currency)],
        "8_units": {"amounts": f"{cat.reporting_currency} "
                               f"{cat.amount_scale}",
                    "stage": "IFRS 9 stage 1, 2 or 3"},
        "9_time_semantics": {
            "period_field": "reporting_quarter (YYYYQn)",
            "calendar": f"{slots[0]} .. {latest}, quarterly",
            "periods_needed": [period_words.get(p, p) for p in q.periods],
            "rule": "filter every relation to its own reporting_quarter; "
                    "never mix quarters inside one aggregate"},
        "10_valid_join_keys": joins or [{"note": "single relation: no join "
                                                 "needed"}],
        "11_mandatory_filters": list(q.filters),
        "12_output_contract": {
            "dimensions": list(q.dimensions), "metrics": list(q.metrics),
            "ranking_or_top_n": q.ranking or None,
            "reconciliation": q.reconciliation or None,
            "chart": q.chart or None,
            "notes": list(q.notes)},
        "13_tool_contract_help": [
            "execute_analysis.steps is an ARRAY of step objects: "
            "{step_id, language: 'sql', code: '<your query>', parameters: {}, "
            "purpose, input_artifact_ids: [], depends_on_step_ids: []}.",
            "finalize_response.numeric_claims is an ARRAY; each claim needs "
            "claim_id, unit and evidence {artifact_id, row_key, column_id} "
            "pointing at a cell of an executed result.",
            "finalize_response.tables and .charts reference an executed "
            "artifact_id and its column names.",
            "Join on EVERY listed key, including reporting_quarter; a join "
            "on the id alone multiplies rows across quarters.",
            "Aggregate the many-side before joining a one-side, or de-"
            "duplicate, so no amount is counted twice."],
        "14_evidence_discipline": [
            "State facts only from executed results; cite them as claims.",
            "Keep facts and interpretation separate; label interpretation.",
            "A cause needs evidence in the data; otherwise say it is not "
            "established.",
            "Unknown stays unknown; do not estimate missing values."],
        "not_included": "no expected values, no oracle results, no other "
                        "model's output, no solution query, no causes",
    }
    return packet


def render(packet: dict[str, Any]) -> str:
    return (f"{HEADER}\n"
            "Deterministic metadata supplied by CreditProbe for this "
            "question. It contains no answer.\n"
            + json.dumps(packet, indent=1, ensure_ascii=False,
                         sort_keys=True))


def packet_record(packet: dict[str, Any]) -> dict[str, Any]:
    text = render(packet)
    data = text.encode()
    return {"packet": packet, "rendered_text": text,
            "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
            "estimated_tokens": int(len(text) / 2.2) + 1,
            "delivery": "one extra system text block appended to every "
                        "provider request of this child (lab provider "
                        "seam); the frozen engine is unchanged",
            "token_accounting_note": "the frozen engine's pre-call input "
                                     "count does not include the packet"}


class AssistedProvider:
    """Appends the packet to each request; forwards everything else."""

    def __init__(self, inner: Any, packet: dict[str, Any]) -> None:
        self._inner = inner
        self.assistance_record = packet_record(packet)
        self._block = {"type": "text",
                       "text": self.assistance_record["rendered_text"]}
        self.injections = 0

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def converse(self, **kwargs: Any) -> Any:
        system = kwargs.get("system")
        if isinstance(system, list):
            new = list(system) + [dict(self._block)]
        else:
            new = [{"type": "text", "text": str(system or "")},
                   dict(self._block)]
        self.injections += 1
        return self._inner.converse(**{**kwargs, "system": new})
