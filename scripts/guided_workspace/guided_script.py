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

#: A What-If question carries the active cohort by reference in `ui_filters`.
ACTIVE_COHORT = re.compile(
    r'active_cohort\W+(?:[^{}]*?)cohort_id\W+(coh-[0-9a-f]{12})')

SCENARIO_WORDS = re.compile(r"\b(increase|stress|raise|shock)\b|%")

#: The live-UAT reproduction (UAT-01), typed exactly: Construction, PD x1.20,
#: LGD x1.10, stages fixed, and NO method named.
UAT_PREVIEW = re.compile(r"pd\s*x\s*1\.20")
CONFIRM_ONLY = re.compile(r"\bconfirm the scenario\b")
METHOD_TURN = re.compile(r"run the confirmed scenario with (?:the )?"
                         r"(delta|ml emulator|a user-defined impact|delta and "
                         r"the ml emulator)")
METHODS_FOR = {"delta": ["delta"], "ml emulator": ["ml"],
               "a user-defined impact": ["user_defined"],
               "delta and the ml emulator": ["delta", "ml"]}

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


def active_cohort(messages: list[dict[str, Any]], system: Any = None) -> str:
    blob = json.dumps({"m": messages, "s": system}, default=str)
    found = ACTIVE_COHORT.search(blob.replace('\\"', '"'))
    return found.group(1) if found else ""


def shocks_from(question: str) -> list[dict[str, Any]]:
    """The two rule shapes the browser journeys ask for, typed exactly."""
    q = question.lower()
    out = []
    pd = re.search(r"pd[^0-9]*(\d+)\s*%", q)
    lgd = re.search(r"lgd[^0-9]*(\d+)\s*%", q)
    if pd:
        out.append({"field": "pd_pit_12m", "operation": "relative_pct",
                    "value": pd.group(1), "origin": f"PD +{pd.group(1)}%"})
    if lgd:
        out.append({"field": "lgd_pct", "operation": "relative_pct",
                    "value": lgd.group(1), "origin": f"LGD +{lgd.group(1)}%"})
    return out or [{"field": "pd_pit_12m", "operation": "relative_pct",
                    "value": "20", "origin": "PD +20%"}]


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
        q = question.strip().lower()
        if UAT_PREVIEW.search(q):
            return self._uat_preview(messages, question)
        if CONFIRM_ONLY.search(q):
            return self._confirm_only(messages, system, question)
        chosen = METHOD_TURN.search(q)
        if chosen:
            return self._run_with(messages, system, question,
                                  METHODS_FOR[chosen.group(1)])
        cohort_ref = active_cohort(messages, system)
        if cohort_ref and SCENARIO_WORDS.search(question) and not any(
                w in question for w in ("yes", "run it", "confirm")):
            return self._preview_on_cohort(messages, question, cohort_ref)
        if not is_guided(question):
            return self.base.converse(
                system=system, messages=messages, tools=tools,
                max_tokens=max_tokens, model=model, purpose=purpose,
                role=role, timeout=timeout, allow_retry=allow_retry,
                effort=effort, tool_choice=tool_choice,
                output_config=output_config)
        import whatif_stub_server as base_mod
        from conftest import ScriptedResult, final, intent, tool_call

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

    def _preview_on_cohort(self, messages, question: str, cohort_ref: str):
        from conftest import ScriptedResult, intent, tool_call

        turn = sum(1 for m in messages if m.get("role") == "assistant")
        time.sleep(0.3)
        # The guided stress-test suggestion ("Stress test: ...") names no
        # method, so the scripted analyst assumes none: the preview is
        # method-free and confirming leads to METHOD SELECTION (UAT-01 rule).
        method_free = question.strip().lower().startswith("stress test")
        if turn > 0:
            return _clarify(messages, question, method_free=method_free)
        parameters = {"operation": "preview_scenario",
                      "cohort": {"cohort_id": cohort_ref},
                      "shocks": shocks_from(question),
                      "clauses": [question[:400]]}
        if not method_free:
            parameters["methods"] = ["delta"]
        return ScriptedResult(tool_calls=[tool_call(
            "execute_analysis",
            {"intent": intent("DATA_ANALYSIS", "COCKPIT", understood=question),
             "objective": "preview this scenario on the active cohort",
             "subquestions": [question[:200]],
             "metadata_receipt_ids": None, "fields_required": None,
             "expected_output_grain": "one row per measure",
             "expected_units": {},
             "steps": [{"step_id": "s1", "language": "whatif_scenario",
                        "code": "Preview: the rules asked for, over the "
                                "active What-If cohort named by id.",
                        "parameters": parameters,
                        "purpose": "preview the scenario before anything runs",
                        "input_artifact_ids": None,
                        "depends_on_step_ids": None}],
             "repair_of_submission_id": None},
            "tu-wi-cohort")])


    # -- UAT-01, scripted: preview with no method, confirm, THEN choose -----

    @staticmethod
    def _step(parameters: dict[str, Any], purpose: str) -> dict[str, Any]:
        return {"step_id": "s1", "language": "whatif_scenario",
                "code": purpose, "parameters": parameters,
                "purpose": purpose, "input_artifact_ids": None,
                "depends_on_step_ids": None}

    def _submit(self, question: str, step: dict[str, Any], tag: str) -> Any:
        from conftest import ScriptedResult, intent, tool_call

        return ScriptedResult(tool_calls=[tool_call(
            "execute_analysis",
            {"intent": intent("DATA_ANALYSIS", "COCKPIT", understood=question),
             "objective": step["purpose"], "subquestions": [question[:200]],
             "metadata_receipt_ids": None, "fields_required": None,
             "expected_output_grain": "one row per measure",
             "expected_units": {}, "steps": [step],
             "repair_of_submission_id": None}, tag)])

    def _uat_preview(self, messages, question: str):
        turn = sum(1 for m in messages if m.get("role") == "assistant")
        time.sleep(0.3)
        if turn > 0:
            return _clarify(messages, question, method_free=True)
        return self._submit(question, self._step({
            "operation": "preview_scenario",
            "cohort": {"filters": [{"column": "sector", "operator": "=",
                                    "value": "Construction"}]},
            "shocks": [{"field": "pd_pit_12m", "operation": "multiply",
                        "value": "1.20", "origin": "PD x1.20"},
                       {"field": "lgd_pct", "operation": "multiply",
                        "value": "1.10", "origin": "LGD x1.10"}],
            "clauses": [question[:400]]},
            "preview the scenario; no method is assumed"), "tu-uat-preview")

    def _confirm_only(self, messages, system, question: str):
        import whatif_stub_server as base_mod
        from conftest import ScriptedResult, final, intent, tool_call

        turn = sum(1 for m in messages if m.get("role") == "assistant")
        time.sleep(0.3)
        if turn == 0:
            return self._submit(question, self._step({
                "operation": "execute_scenario",
                "confirmation_digest": base_mod._stored_digest(messages,
                                                               system),
                "reply": "yes"}, "confirm the scenario the reader approved"),
                "tu-uat-confirm")
        step = base_mod._step_of(messages)
        return ScriptedResult(tool_calls=[tool_call(
            "finalize_response",
            final(intent=intent("DATA_ANALYSIS", "COCKPIT",
                                understood=question),
                  disposition="clarification",
                  narrative=("Scenario confirmed — NOT executed. No ECL was "
                             "calculated: the scenario and the method are "
                             "separate decisions, and no method was chosen."),
                  clarification_question=("Which method should translate "
                                          "the confirmed scenario into ECL: "
                                          "Delta, the ML emulator, a "
                                          "User-defined impact, or compare "
                                          "them?"),
                  clarification_options=["Delta", "ML emulator",
                                         "User-defined", "Compare methods"],
                  tables=[{"title": "Method selection",
                           "artifact_id": str(step.get("artifact_id") or ""),
                           "columns": ["section", "item", "method", "status",
                                       "note"]}]),
            "tu-uat-method")])

    def _run_with(self, messages, system, question: str, methods: list[str]):
        import whatif_stub_server as base_mod

        turn = sum(1 for m in messages if m.get("role") == "assistant")
        time.sleep(0.3)
        if turn == 0:
            return self._submit(question, self._step({
                "operation": "execute_scenario",
                "confirmation_digest": base_mod._stored_digest(messages,
                                                               system),
                "reply": "yes", "methods": methods},
                f"run the confirmed scenario with {', '.join(methods)}"),
                "tu-uat-run")
        from conftest import ScriptedResult, final, intent, tool_call

        return ScriptedResult(tool_calls=[tool_call(
            "finalize_response",
            base_mod.answer_body(base_mod._step_of(messages),
                                 question=question, charts=True,
                                 intent_of=intent, final_of=final),
            "tu-uat-answer")])


def _clarify(messages, question: str, method_free: bool = False) -> Any:
    """The preview, published as a clarification the reader confirms."""
    import whatif_stub_server as base_mod
    from conftest import ScriptedResult, final, intent, tool_call

    step = base_mod._step_of(messages)
    rows = base_mod._rows_from(messages)
    digest = base_mod._value(rows, "confirmation", "Digest to approve")
    cohort = base_mod._value(rows, "cohort", "Cohort id")
    n = base_mod._value(rows, "cohort", "Exposures selected")
    return ScriptedResult(tool_calls=[tool_call(
        "finalize_response",
        final(intent=intent("DATA_ANALYSIS", "COCKPIT", understood=question),
              disposition="clarification",
              narrative=(f"Nothing has been calculated. The rules below would "
                         f"apply to the {n} exposures of the "
                         f"{'cohort' if method_free else 'active What-If cohort'}"
                         f", frozen as {cohort}."
                         + (" Confirming does NOT run it: you then choose "
                            "the method." if method_free else "")),
              clarification_question=(f"Apply these rules to the {n} "
                                      f"exposures of the active cohort "
                                      f"({cohort})? Approve this scenario "
                                      f"({digest[:12]})?"),
              clarification_options=(["Yes, confirm the scenario",
                                      "No, change something"]
                                     if method_free else
                                     ["Yes, run it", "No, change something"]),
              tables=[{"title": "Scenario preview",
                       "artifact_id": str(step.get("artifact_id") or ""),
                       "columns": ["section", "item", "detail", "value",
                                   "unit", "status"]}]),
        "tu-wi-preview")])


def install(app: Any) -> GuidedProvider:
    """Swap the running runtime's provider for the guided wrapper.

    The worker reads `runtime.provider` per run (and binds the exchange
    recorder around it there), so replacing the attribute is enough.
    """
    runtime = app.state.cockpit_v4["runtime"]
    wrapped = GuidedProvider(runtime.provider)
    runtime.provider = wrapped
    return wrapped
