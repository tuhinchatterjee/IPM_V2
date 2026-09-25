"""
Deterministic demonstration fixtures. NOT MODELS.

Each fixture answers `converse` with scripted Anthropic-shape tool calls, the
same result shape the frozen adapter returns, and the frozen engine does the
rest for real: validation, DuckDB execution, repair feedback, finalization,
storage. They exist so the lab's disclosure, evaluation and export can be
proven end to end on a machine with no model, and so the evaluator can be
shown to catch KNOWN injected errors (wrong cohort, invented cause, refused
submission, protocol failure).

The fixtures answer ONE task family: Stage 2 exposure (EAD) by sector for the
latest quarter of the corporate book. The SQL resolves "latest" itself, so no
expected value is baked in anywhere -- the numbers come from the release.
Nothing here is ever shown under a model's name.
"""

from __future__ import annotations

import json
from typing import Any

STAGE2_SQL = """
SELECT sector,
       SUM(ead_sar_mn) AS stage2_ead_sar_mn
FROM corp_facility_quarter
WHERE stage = 2
  AND reporting_quarter = (SELECT MAX(reporting_quarter)
                           FROM corp_facility_quarter)
GROUP BY sector
ORDER BY stage2_ead_sar_mn DESC
""".strip()

#: A different, equally valid strategy: CTE + join for the latest quarter,
#: ordered by sector name. Must pass the same independent checks (Q02).
ALTERNATE_SQL = """
WITH latest AS (
  SELECT MAX(reporting_quarter) AS q FROM corp_facility_quarter
)
SELECT f.sector,
       SUM(f.ead_sar_mn) AS stage2_ead_sar_mn
FROM corp_facility_quarter AS f
JOIN latest ON f.reporting_quarter = latest.q
WHERE f.stage = 2
GROUP BY f.sector
ORDER BY f.sector
""".strip()

#: Whole-book: every stage. Syntactically valid, plausible, wrong population.
WHOLE_BOOK_SQL = STAGE2_SQL.replace("WHERE stage = 2\n  AND ", "WHERE ")

#: Names a column the release does not have; the frozen validator refuses it.
BROKEN_SQL = STAGE2_SQL.replace("SUM(ead_sar_mn)", "SUM(stage2_exposure)")


class FixtureResult:
    """Shaped exactly like the frozen adapter's ConverseResult."""

    def __init__(self, *, tool_calls=None, text: str = "",
                 stop_reason: str = "tool_use", model: str = "",
                 input_tokens: int = 0, output_tokens: int = 0) -> None:
        self.tool_calls = list(tool_calls or [])
        self.text = text
        self.stop_reason = stop_reason
        self.assistant_blocks = (
            [{"type": "tool_use", "id": c["id"], "name": c["name"],
              "input": c["input"]} for c in self.tool_calls]
            or ([{"type": "text", "text": text}] if text else []))
        self.model = model
        self.request_id = ""
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.cache_read_tokens = 0
        self.cache_write_tokens = 0


def _execute(sql: str, *, call_id: str, purpose: str) -> dict[str, Any]:
    return {"id": call_id, "name": "execute_analysis", "input": {
        "objective": purpose,
        "subquestions": ["Stage 2 exposure by sector, latest quarter"],
        "scope": {"reporting_periods": [], "filters": {}},
        "metadata_receipt_ids": [],
        "fields_required": ["corp_facility_quarter.ead_sar_mn",
                            "corp_facility_quarter.stage",
                            "corp_facility_quarter.sector"],
        "expected_output_grain": "sector",
        "expected_units": {"stage2_ead_sar_mn": "SAR million"},
        "steps": [{"step_id": "s1", "language": "sql", "code": sql,
                   "parameters": {}, "purpose": purpose,
                   "input_artifact_ids": [], "depends_on_step_ids": []}],
        "repair_of_submission_id": ""}}


def _last_result(messages: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The newest tool_result block, parsed; None if there is none."""
    for message in reversed(messages):
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if isinstance(part, dict) and part.get("type") == "tool_result":
                body = part.get("content")
                if isinstance(body, list):
                    body = "".join(b.get("text", "") for b in body
                                   if isinstance(b, dict))
                try:
                    parsed = json.loads(body) if isinstance(body, str) else {}
                except ValueError:
                    parsed = {"_text": body}
                parsed["_is_error"] = bool(part.get("is_error"))
                return parsed
        return None
    return None


def _executed_artifact(messages) -> tuple[str, list[dict[str, Any]]] | None:
    res = _last_result(messages)
    if not res or res.get("_is_error"):
        return None
    steps = res.get("steps") or []
    if not steps or not steps[0].get("artifact_id"):
        return None
    return steps[0]["artifact_id"], list(steps[0].get("preview") or [])


def _finalize(artifact: str, rows: list[dict[str, Any]], *,
              narrative_extra: str = "", call_id: str) -> dict[str, Any]:
    col = "stage2_ead_sar_mn"
    top = (max(rows, key=lambda r: r.get(col) or 0)["sector"] if rows
           else "")
    return {"id": call_id, "name": "finalize_response", "input": {
        "disposition": "answer",
        "narrative": (f"In the latest quarter, {top} carries the largest "
                      f"Stage 2 exposure at {{{{claim.top}}}}."
                      + narrative_extra),
        "coverage": [{"subquestion": "Stage 2 exposure by sector, latest "
                                     "quarter", "status": "answered",
                      "evidence_refs": [{"artifact_id": artifact,
                                         "row_key": f"sector={top}",
                                         "column_id": col}]}],
        "numeric_claims": [{"claim_id": "top", "unit": "SAR million",
                            "evidence": {"artifact_id": artifact,
                                         "row_key": f"sector={top}",
                                         "column_id": col}}],
        "evidence_refs": [], "tables": [{"title": "Stage 2 EAD by sector",
                                         "artifact_id": artifact,
                                         "columns": ["sector", col]}],
        "charts": [], "limitations": [], "suggested_questions": [],
        "clarification_question": "", "clarification_options": [],
        "referral_owner": "", "referral_reason": ""}}


def _asked_already(messages) -> bool:
    first = messages[0].get("content") if messages else ""
    text = first if isinstance(first, str) else json.dumps(first)
    return "you_asked" in text or "the_question_still_standing" in text


class FixtureProvider:
    """One behaviour per profile; stateless apart from the call counter."""

    def __init__(self, behaviour: str, model: str) -> None:
        self.behaviour = behaviour
        self.model = model
        self.calls = 0
        self.submitted = 0
        self.artifact: tuple[str, list[dict[str, Any]]] | None = None
        self.corrected = False

    def converse(self, *, system, messages, tools=None, max_tokens=4096,
                 model="", purpose="", role="", timeout=0.0,
                 allow_retry=False, tool_choice=None, output_config=None,
                 **_: Any) -> FixtureResult:
        self.calls += 1
        n = self.calls
        size = len(json.dumps({"s": system, "m": messages, "t": tools},
                              default=str))
        usage = {"input_tokens": size // 4, "output_tokens": 120}
        b = self.behaviour
        executed = _executed_artifact(messages)
        if executed:
            self.artifact = executed
        last = _last_result(messages) or {}
        refused_answer = (last.get("status") == "rejected"
                          and last.get("error_code") == "ANSWER_VALIDATION")

        if b == "no_tool":
            return FixtureResult(text="Stage 2 exposure rose, mainly in "
                                      "real estate.", stop_reason="end_turn",
                                 model=self.model, **usage)
        if b == "clarify" and not _asked_already(messages) and not executed:
            return FixtureResult(tool_calls=[{
                "id": f"fx-{n}", "name": "finalize_response", "input": {
                    "disposition": "clarification",
                    "narrative": "Before I run this: which exposure measure "
                                 "do you mean?",
                    "clarification_question": "Which exposure measure do "
                                              "you mean: EAD or drawn "
                                              "balance?",
                    "clarification_options": ["EAD", "Drawn balance"],
                    "blocking_ambiguities": ["exposure measure"]}}],
                model=self.model, **usage)
        forced = (tool_choice or {}).get("name") if isinstance(
            tool_choice, dict) else None
        if forced == "inspect_catalog" and b != "no_tool":
            # Honour a forced metadata turn, as a compliant model would.
            return FixtureResult(tool_calls=[{
                "id": f"fx-{n}", "name": "inspect_catalog",
                "input": {"relation_ids": ["corp_facility_quarter"],
                          "field_ids": ["ead_sar_mn", "stage", "sector",
                                        "reporting_quarter"]}}],
                model=self.model, **usage)
        if refused_answer and self.artifact:
            # The frozen Finalizer refused the answer: correct it, as a
            # compliant model would, by removing the refused sentence.
            self.corrected = True
            artifact, rows = self.artifact
            return FixtureResult(tool_calls=[_finalize(
                artifact, rows, call_id=f"fx-{n}")], model=self.model,
                **usage)
        if executed:
            artifact, rows = executed
            extra = ""
            if b == "invented_cause":
                # Unsupported causal attribution: nothing in the evidence
                # speaks to contract awards. Worded without "policy" so the
                # frozen policy-citation check does not catch it first.
                extra = (" The increase was driven by a slowdown in new "
                         "construction contract awards this year.")
            return FixtureResult(tool_calls=[_finalize(
                artifact, rows, narrative_extra=extra, call_id=f"fx-{n}")],
                model=self.model, **usage)
        self.submitted += 1
        if b == "repair" and self.submitted == 1:
            sql = BROKEN_SQL
        elif b == "wrong_scope":
            sql = WHOLE_BOOK_SQL
        elif b == "alternate_plan":
            sql = ALTERNATE_SQL
        else:
            sql = STAGE2_SQL
        return FixtureResult(tool_calls=[_execute(
            sql, call_id=f"fx-{n}",
            purpose="Stage 2 exposure by sector for the latest quarter")],
            model=self.model, **usage)
