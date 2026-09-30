"""The scripted analyst's guided-investigation turns. MODEL MOCK.

Wraps the What-If round's scripted provider (`whatif_stub_server`) without
editing it: a question that reads like an investigation step -- the wording
the Requires Attention next-best questions produce, or a banker's own
"which / show / what changed" -- is answered here with an ordinary SQL step
over the book the THREAD reads (Corporate or Retail, detected from the packet
the runtime built, never from the question). Everything else, scenarios
included, goes to the base provider unchanged.

The answer is built by the base `plain_body`, so each figure is an
`EvidenceRef` into the stored artifact the engine produced, exactly as on the
What-If journeys.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any

#: The investigation SQL each book answers with: one row per segment at the
#: latest period. A mock's query, labelled as one in every answer.
PLAN: dict[str, dict[str, str]] = {
    "corporate": {"relation": "corp_facility_quarter", "dimension": "sector",
                  "period": "reporting_quarter"},
    "retail": {"relation": "retail_account_month", "dimension": "product",
               "period": "reporting_month"},
}

GUIDED = re.compile(
    r"^(which|show|what changed|check whether|how does|compare pd|why|"
    r"what is driving|list the|where is)\b")


def is_guided(question: str) -> bool:
    q = question.strip().lower()
    return bool(GUIDED.match(q)) and "stress test" not in q


def domain_of(messages: list[dict[str, Any]], system: Any = None) -> str:
    """The book the thread reads, from the packet the runtime assembled."""
    blob = json.dumps({"m": messages, "s": system}, default=str)
    if "retail_account_month" in blob or '\\"domain\\": \\"retail\\"' in blob \
            or '"domain": "retail"' in blob:
        return "retail"
    return "corporate"


def investigation_sql(domain: str) -> str:
    p = PLAN[domain]
    return (f"SELECT {p['dimension']} AS dimension,\n"
            f"       COUNT(*) AS exposures,\n"
            f"       SUM(ead_sar_mn) AS ead_sar_mn,\n"
            f"       SUM(ecl_sar_mn) AS ecl_sar_mn\n"
            f"FROM {p['relation']}\n"
            f"WHERE {p['period']} = (SELECT MAX({p['period']}) "
            f"FROM {p['relation']})\n"
            f"GROUP BY 1\n"
            f"ORDER BY ecl_sar_mn DESC")


class GuidedProvider:
    """Delegates to `base` for everything but a guided investigation turn."""

    def __init__(self, base: Any) -> None:
        self.base = base

    def count_tokens(self, **kwargs) -> int:
        return self.base.count_tokens(**kwargs)

    def converse(self, *, system, messages, tools=None, max_tokens=4096,
                 model="", purpose="", role="", timeout=0.0,
                 allow_retry=True, effort="", tool_choice=None,
                 output_config=None):
        question = self.base._question(messages)
        if not is_guided(question):
            return self.base.converse(
                system=system, messages=messages, tools=tools,
                max_tokens=max_tokens, model=model, purpose=purpose,
                role=role, timeout=timeout, allow_retry=allow_retry,
                effort=effort, tool_choice=tool_choice,
                output_config=output_config)
        from conftest import ScriptedResult, final, intent, tool_call

        import whatif_stub_server as base_mod

        turn = sum(1 for m in messages if m.get("role") == "assistant")
        time.sleep(0.3)
        if turn == 0:
            domain = domain_of(messages, system)
            return ScriptedResult(tool_calls=[tool_call(
                "execute_analysis",
                {"intent": intent("DATA_ANALYSIS", "COCKPIT",
                                  understood=question),
                 "objective": "the segments behind the issue",
                 "subquestions": [question[:200]],
                 "metadata_receipt_ids": None, "fields_required": None,
                 "expected_output_grain": "one row per segment",
                 "expected_units": {},
                 "steps": [{"step_id": "s1", "language": "sql",
                            "code": investigation_sql(domain),
                            "parameters": None,
                            "purpose": "the segments at the latest period",
                            "input_artifact_ids": None,
                            "depends_on_step_ids": None}],
                 "repair_of_submission_id": None},
                "tu-guided")])
        return ScriptedResult(tool_calls=[tool_call(
            "finalize_response",
            base_mod.plain_body(base_mod._step_of(messages), question=question,
                                dimension="dimension", intent_of=intent,
                                final_of=final),
            "tu-guided-answer")])


def install(app: Any) -> GuidedProvider:
    """Swap the running runtime's provider for the guided wrapper.

    The worker reads `runtime.provider` per run (and binds the exchange
    recorder around it there), so replacing the attribute is enough.
    """
    runtime = app.state.cockpit_v4["runtime"]
    wrapped = GuidedProvider(runtime.provider)
    runtime.provider = wrapped
    return wrapped
