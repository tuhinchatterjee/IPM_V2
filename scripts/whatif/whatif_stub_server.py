#!/usr/bin/env python3
"""The real V4 stack against the CANDIDATE book, with a scripted analyst.

Everything here is the real thing except the model: the real routes, the real
durable store, the real worker and supervisor, the real event stream, the real
DuckDB session against the published candidate release, and the real scenario
engine reached through the real `execute_analysis` tool. Only `converse` is
scripted.

**MODEL MOCK, and labelled as one everywhere it is reported.** No provider
credential is authorised in this environment -- `ANTHROPIC_API_KEY`,
`OPENAI_API_KEY`, `AZURE_OPENAI_API_KEY` and `COCKPIT_LLM_API_KEY` are all
unset -- so the analyst's tool calls are written here rather than generated. A
journey driven by a live model is a separate, unrun claim and is reported
BLOCKED, not folded into these results.

What that leaves proved, and it is the thing that was blocked: a scenario
question typed into the Advanced Cockpit reaches `scenario/run.py` through the
governed execution path, and its result comes back through the ordinary
response path into the ordinary thread. Every hop between the composer and the
engine is the product's own.

## Why its own file rather than a flag on the accepted stub

The accepted `scripts/cockpit_v4/stub_server.py` builds its provider inside
`build_app`, keyed on questions the accepted suite asks, against the accepted
release. Threading a second release, two feature flags and a different script
through it would put the What-If journeys inside the file the accepted 76
journeys depend on -- and those journeys are the evidence that the accepted
application is unchanged. They do not share a process.

Usage:
    python3 scripts/whatif/whatif_stub_server.py --port 8424 --domain corporate
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from decimal import Decimal
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests" / "cockpit_v4"))

# SET BEFORE ANY BACKEND IMPORT, not inside `build_app`.
#
# `v3_store.read_manifest` resolves its namespace when the module is first
# imported, and `build_app` imports `conftest`, which imports the backend. A
# `setdefault` inside the function therefore ran too late: the release was
# looked up in the default namespace, was not found there, and the server
# refused to start saying the candidate was not published -- which it was.
os.environ.setdefault("COCKPIT_AGENTIC_V3_NAMESPACE", "cockpit_v4")

#: The candidate releases, by book. NOT what `cfg.release_id` is set to --
#: see `PREFLIGHT_RELEASE` -- but what the analytical path must actually open,
#: which is what the journeys assert.
CANDIDATE = {"corporate": "v4-whatif-corporate-20q-s1",
             "retail": "v4-whatif-retail-20m-s1"}

#: WHAT `cfg.release_id` PINS, AND WHY IT IS NOT THE CANDIDATE.
#:
#: `service.load_release` validates the pinned release through
#: `cockpit_agentic.store`, which reads `data/cockpit_v4/` -- the V3-namespace
#: releases. The candidate books are published to the LAKE,
#: `data/cockpit_v4_lake/`, by `lake.publish`, and are not V3-namespace
#: releases at all. Pinning one here makes the server refuse to start saying
#: the candidate is not published, which is true of the namespace it looked in
#: and false of the release.
#:
#: The accepted stub pins this same release for the same reason, and it is not
#: a substitution: `cfg.release_id` supplies the preflight and the release
#: header, while every analytical turn resolves its own book through
#: `domain_resolver.scope_for` -> `domains.current_release`, which returns the
#: CANDIDATE when that book's flag is on. The journeys assert the release the
#: turn actually opened, not the one the config pinned, so a regression that
#: made the runtime open the accepted book would fail them.
PREFLIGHT_RELEASE = "v4-saudi-20q-v1"

FLAG = {"corporate": "COCKPIT_V4_WHATIF_CORPORATE",
        "retail": "COCKPIT_V4_WHATIF_RETAIL"}

#: The cohort each book's journey investigates, and the rule it then applies.
#: A NON-TRIVIAL cohort in both cases -- a filtered sector or product, not the
#: whole book -- because "those customers" only means something when it means
#: fewer rows than everything.
JOURNEY: dict[str, dict[str, Any]] = {
    "corporate": {
        "filters": [{"column": "sector", "operator": "=",
                     "value": "Construction"}],
        "described": "construction facilities",
        "field": "pd_pit_12m",
        "dimension": "sector",
        "relation": "corp_facility_quarter",
        "key": "facility_id",
        "owner": "borrower_id",
        "period_column": "reporting_quarter",
    },
    "retail": {
        "filters": [{"column": "product", "operator": "=",
                     "value": "Personal Finance"}],
        "described": "personal finance accounts",
        "field": "pd_pit_12m",
        "dimension": "product",
        "relation": "retail_account_month",
        "key": "account_id",
        "owner": "customer_id",
        "period_column": "reporting_month",
    },
}


def build_app(port: int, runtime_dir: Path, *, domain_id: str,
              ui_port: int = 0):
    os.environ[FLAG[domain_id]] = "1"

    from conftest import ScriptedResult, final, intent, tool_call

    from backend.cockpit_v4 import app as v4app
    from backend.cockpit_v4 import routes
    from backend.cockpit_v4.capability import Capability, PriceCard
    from backend.cockpit_v4.config import V4Config
    from backend.cockpit_v4.service import Runtime, load_release
    from backend.cockpit_v4.supervisor import Supervisor
    from backend.cockpit_v4.worker import Worker

    plan = JOURNEY[domain_id]

    cfg = V4Config(
        enabled=True, provider="anthropic", reasoning_model="stub-analyst",
        runtime_dir=runtime_dir,
        state_database=str(runtime_dir / "state" / "whatif.sqlite3"),
        release_id=PREFLIGHT_RELEASE, api_port=port,
        ui_port=ui_port or port + 1,
        local_demo_auth=True, price_card_path="", memory_enabled=False,
        memory_model="", default_mode="standard", heartbeat_seconds=1.0,
        lease_heartbeat_seconds=2.0, lease_stale_seconds=10.0,
        supervisor_poll_seconds=2.0, credential_present=True, missing=())
    capability = Capability(
        provider="anthropic", model_id="stub-analyst", sdk_version="whatif",
        context_tokens=200_000, max_output_tokens=128_000,
        supports_tools=True, supports_token_counting=True,
        price=PriceCard(5.0, 25.0, 6.25, 0.5), source="what-if stub",
        verified_at="2026-09-26T00:00:00Z", live_verified=True)
    catalog, _, summary = load_release(cfg)

    # ---- the scripted turns ------------------------------------------

    def investigation_step() -> dict[str, Any]:
        """An ordinary SQL step. J01 starts with a real investigation, so the
        cohort a scenario later names is one the reader actually saw."""
        where = " AND ".join(
            f"{f['column']} = '{f['value']}'" for f in plan["filters"])
        return {
            "step_id": "s1", "language": "sql",
            "code": (f"SELECT {plan['dimension']} AS dimension,\n"
                     f"       COUNT(*) AS exposures,\n"
                     f"       SUM(ead_sar_mn) AS ead_sar_mn,\n"
                     f"       SUM(ecl_sar_mn) AS ecl_sar_mn\n"
                     f"FROM {plan['relation']}\n"
                     f"WHERE {where}\n"
                     f"GROUP BY 1\n"
                     f"ORDER BY ecl_sar_mn DESC"),
            "parameters": None, "purpose": "the cohort as it stands",
            "input_artifact_ids": None, "depends_on_step_ids": None}

    def scenario_step(parameters: dict[str, Any], *, purpose: str,
                      restatement: str) -> dict[str, Any]:
        """A `whatif_scenario` step.

        `code` is a restatement in words. It is stored for the trace and is
        never parsed or executed on this path -- the operation is the typed
        `parameters` object and nothing else.
        """
        return {"step_id": "s1", "language": "whatif_scenario",
                "code": restatement, "parameters": parameters,
                "purpose": purpose, "input_artifact_ids": None,
                "depends_on_step_ids": None}

    def submission(steps: list[dict[str, Any]], *, objective: str,
                   understood: str) -> dict[str, Any]:
        return {
            "intent": intent("DATA_ANALYSIS", "COCKPIT",
                             understood=understood),
            "objective": objective,
            "subquestions": [objective],
            "metadata_receipt_ids": None, "fields_required": None,
            "expected_output_grain": "one row per measure",
            "expected_units": {}, "steps": steps,
            "repair_of_submission_id": None}

    def preview_parameters(*, methods: list[str],
                           assumption: dict[str, Any] | None = None,
                           value: str = "20") -> dict[str, Any]:
        out: dict[str, Any] = {
            "operation": "preview_scenario",
            "cohort": {"filters": plan["filters"], "selection": "row"},
            "shocks": [{"field": plan["field"], "operation": "relative_pct",
                        "value": value,
                        "origin": f"increase PD by {value}%"}],
            "methods": methods,
            "clauses": [f"For those customers, increase PD by {value}%."]}
        if assumption is not None:
            out["user_assumption"] = assumption
        return out

    def answer_from(messages: list[dict[str, Any]], *, question: str,
                    charts: bool = True) -> Any:
        """A final response built from the rows the run actually produced.

        Reads the step out of the conversation rather than restating a
        number, because the point of the journey is that the figure in the
        answer is the figure the engine computed -- named by an
        `EvidenceRef` into the stored artifact, and resolved into the prose
        by CreditProbe rather than spelled out here.
        """
        return ScriptedResult(tool_calls=[tool_call(
            "finalize_response",
            answer_body(_step_of(messages), question=question, charts=charts,
                        intent_of=intent, final_of=final),
            "tu-answer")])

    def preview_clarification(messages: list[dict[str, Any]], *,
                              question: str) -> Any:
        """The preview, published as a clarification the reader confirms."""
        step = _step_of(messages)
        rows = _rows_from(messages)
        digest = _value(rows, "confirmation", "Digest to approve")
        # THE TABLE IS NAMED, NOT CARRIED.
        #
        # This turn used to inline its own `rows` as arrays of strings. The
        # server renders a published table from the STORED ARTIFACT
        # (`finalization.render_tables`) and passes an unrecognised one
        # straight through, so those raw arrays reached the browser without
        # the `display` map every cell is read from -- and the thread page
        # died in its error boundary with "Cannot read properties of
        # undefined (reading 'section')", taking the composer with it. An
        # analyst names the artifact and the columns; CreditProbe owns every
        # value and its formatting.
        artifact = str(step.get("artifact_id") or "")
        return ScriptedResult(tool_calls=[tool_call(
            "finalize_response",
            final(intent=intent("DATA_ANALYSIS", "COCKPIT",
                                understood=question),
                  disposition="clarification",
                  # A clarification still needs a narrative: the contract
                  # requires one and a run whose narrative was empty burned
                  # every provider attempt being told so, seven times, before
                  # ending as CALL_LIMIT. The preview's own summary IS the
                  # narrative -- there is nothing else this turn is saying.
                  narrative=(
                      f"Nothing has been calculated. This is what would "
                      f"happen, over the cohort frozen as "
                      f"{_value(rows, 'cohort', 'Cohort id')}: "
                      f"{_value(rows, 'cohort', 'Exposures selected')} "
                      f"exposures carrying a baseline ECL of "
                      f"{_value(rows, 'cohort', 'Baseline ECL')} SAR "
                      f"million. The rules, the methods and the policies "
                      f"below are exactly what a yes would approve. No "
                      f"source row, no reported ECL and no accounting "
                      f"record would change: this is a simulation over a "
                      f"generated book."),
                  clarification_question=(
                      f"This would apply the rules below to the "
                      f"{_value(rows, 'cohort', 'Exposures selected')} "
                      f"exposures frozen as "
                      f"{_value(rows, 'cohort', 'Cohort id')}, measured "
                      f"against a baseline ECL of "
                      f"{_value(rows, 'cohort', 'Baseline ECL')} SAR "
                      f"million. Nothing is calculated until you confirm. "
                      f"Approve this scenario ({digest[:12]})?"),
                  clarification_options=["Yes, run it",
                                        "No, change something"],
                  tables=[{"title": "Scenario preview",
                          "artifact_id": artifact,
                          "columns": ["section", "item", "detail", "value",
                                      "unit", "status"]}]),
            "tu-preview")])

    class ScenarioProvider:
        """One `converse` per turn, scripted from the question under way."""

        def __init__(self) -> None:
            self.lock = threading.RLock()

        def count_tokens(self, *, system=None, messages=None, tools=None,
                        model="") -> int:
            return int(len(json.dumps({"s": system, "m": messages,
                                       "t": tools}, default=str)) / 3.5) + 1

        @staticmethod
        def _question(messages) -> str:
            """THE READER'S OWN WORDS, not the packet that carries them.

            `context.build` writes `USER REQUEST (original wording,
            unmodified):` and then the question, as the FIRST part of a block
            that goes on to hold the catalogue, the policy, the scenario
            semantics and the recent turns. Returning the whole block
            lowercased -- which is what this did -- meant every keyword test
            matched something: "which", "show me", "compare", "model" and
            "sensitivity" all appear in a packet about a credit book. Every
            scenario question was routed to the investigation branch and ran
            a SELECT instead of a scenario step.

            So the question is cut out of the block: the text after the
            marker's own line, up to the blank line that closes that part.
            """
            marker = "USER REQUEST"
            for message in messages:
                content = message.get("content")
                if not isinstance(content, str) or marker not in content:
                    continue
                after = content.split(marker, 1)[1]
                if "\n" in after:
                    after = after.split("\n", 1)[1]
                return after.split("\n\n", 1)[0].strip().lower()
            return ""

        def converse(self, *, system, messages, tools=None, max_tokens=4096,
                     model="", purpose="", role="", timeout=0.0,
                     allow_retry=True, effort="", tool_choice=None,
                     output_config=None):
            question = self._question(messages)
            turn = sum(1 for m in messages if m.get("role") == "assistant")
            time.sleep(0.4)
            return _script(question, turn, messages, system)

    def _script(question: str, turn: int, messages, system=None) -> Any:
        """Which scripted turn this is. Keyed on the reader's own words."""
        asked = question

        # -- J03: a methodology question. An ordinary SELECT over a
        # published relation, which is why P5 published sensitivities as
        # data: no scenario, no engine, no refit.
        if "sensitivity" in asked or "how much would" in asked:
            if turn == 0:
                book = "corp" if domain_id == "corporate" else "retail"
                return ScriptedResult(tool_calls=[tool_call(
                    "execute_analysis",
                    submission([{
                        "step_id": "s1", "language": "sql",
                        "code": (f"SELECT factor_id, parameter, "
                                 f"native_slope, readiness\n"
                                 f"FROM whatif_{book}_sensitivity\n"
                                 f"WHERE readiness = 'SUPPORTED_ESTIMATE'\n"
                                 f"ORDER BY ABS(native_slope) DESC\n"
                                 f"LIMIT 10"),
                        "parameters": None,
                        "purpose": "the published sensitivities",
                        "input_artifact_ids": None,
                        "depends_on_step_ids": None}],
                        objective="published macro sensitivities",
                        understood=asked),
                    "tu-sens")])
            return ScriptedResult(tool_calls=[tool_call(
                "finalize_response",
                plain_body(_step_of(messages), question=asked,
                           dimension="factor_id", intent_of=intent,
                           final_of=final),
                "tu-sens-answer")])

        # -- J13: a run that keeps working, one modest action at a time.
        #
        # Deliberately NOT one long sleep. V4 observes a cancellation BETWEEN
        # actions; it does not abort an in-flight provider call, which is what
        # the deadline and the supervisor are for. A stub that blocked inside
        # `converse` would be testing whether a socket can be interrupted --
        # not the mechanism -- and would make a correct implementation look
        # broken.
        if "keep working" in asked or "slowly" in asked:
            return ScriptedResult(tool_calls=[tool_call(
                "inspect_catalog",
                {"intent": intent("DATA_ANALYSIS", "COCKPIT",
                                  understood="looking for the right fields"),
                 "query": "exposure", "relation_ids": [], "field_ids": [],
                 "detail": ["discovery"], "reporting_periods": [],
                 "sample_rows": 0, "cursor": ""},
                "tu-slow")])

        # -- J11: a category the book does not have. The reader's own words
        # reach the typed contract unchanged, and `selector` refuses the
        # column value against the release's declared categories. The refusal
        # is the product's, not the script's.
        if "interstellar" in asked:
            if turn == 0:
                return ScriptedResult(tool_calls=[tool_call(
                    "execute_analysis",
                    submission([scenario_step(
                        {"operation": "preview_scenario",
                         "cohort": {"filters": [
                             {"column": plan["filters"][0]["column"],
                              "operator": "=",
                              "value": "Interstellar Freight"}]},
                         "shocks": [{"field": plan["field"],
                                     "operation": "relative_pct",
                                     "value": "20",
                                     "origin": asked[:200]}],
                         "methods": ["delta"]},
                        purpose="preview a scenario over a named category",
                        restatement="Preview: a category the reader named.")],
                        objective="preview this scenario", understood=asked),
                    "tu-unseen")])
            return answer_from(messages, question=asked, charts=False)

        # -- J12: a probability outside its own range. `units` and the field
        # dictionary own the bound; the script does not pre-clip it, because
        # a stub that corrected the request would be testing itself.
        if "250" in asked:
            if turn == 0:
                return ScriptedResult(tool_calls=[tool_call(
                    "execute_analysis",
                    submission([scenario_step(
                        {"operation": "preview_scenario",
                         "cohort": {"filters": plan["filters"]},
                         "shocks": [{"field": plan["field"],
                                     "operation": "set_to", "value": "250",
                                     "origin": asked[:200]}],
                         "methods": ["delta"]},
                        purpose="preview a scenario with a stated bound",
                        restatement="Preview: set the parameter as asked.")],
                        objective="preview this scenario", understood=asked),
                    "tu-range")])
            return answer_from(messages, question=asked, charts=False)

        # -- J01/J02 and the rest: a scenario.
        confirming = any(
            word in asked for word in ("yes", "run it", "confirm", "go ahead"))
        methods = ["delta"]
        assumption: dict[str, Any] | None = None
        if "compare" in asked or "all three" in asked or "every method" in asked:
            methods = ["delta", "ml", "user_defined"]
            assumption = {"form": "relative", "value": "15",
                          "stated_as": "assume ECL rises 15%"}
        elif "emulator" in asked or "model" in asked or " ml" in asked:
            methods = ["delta", "ml"]

        if confirming:
            if turn == 0:
                digest = _stored_digest(messages, system)
                return ScriptedResult(tool_calls=[tool_call(
                    "execute_analysis",
                    submission([scenario_step(
                        {"operation": "execute_scenario",
                         "confirmation_digest": digest,
                         "reply": "yes"},
                        purpose="run the confirmed scenario",
                        restatement="Run the scenario the reader approved.")],
                        objective="the confirmed scenario",
                        understood=asked),
                    "tu-run")])
            return answer_from(messages, question=asked)

        if "investigate" in asked or "which" in asked or "show me" in asked:
            if turn == 0:
                return ScriptedResult(tool_calls=[tool_call(
                    "execute_analysis",
                    submission([investigation_step()],
                               objective="the cohort as it stands",
                               understood=asked),
                    "tu-invest")])
            return ScriptedResult(tool_calls=[tool_call(
                "finalize_response",
                plain_body(_step_of(messages), question=asked,
                           dimension="dimension", intent_of=intent,
                           final_of=final),
                "tu-invest-answer")])

        if turn == 0:
            value = "40" if "40" in asked else "20"
            return ScriptedResult(tool_calls=[tool_call(
                "execute_analysis",
                submission([scenario_step(
                    preview_parameters(methods=methods, assumption=assumption,
                                       value=value),
                    purpose="preview the scenario before anything runs",
                    restatement=(f"Preview: increase {plan['field']} by "
                                 f"{value}% over {plan['described']}."))],
                    objective="preview this scenario",
                    understood=asked),
                "tu-preview-run")])
        return preview_clarification(messages, question=asked)

    provider = ScenarioProvider()
    runtime = Runtime(cfg=cfg, capability=capability, provider=provider,
                      catalog=catalog, coverage=None, release_summary=summary)
    app = v4app.create_app(cfg, provider=provider, verify_model=False,
                           start_workers=False)
    state = app.state.cockpit_v4
    state["runtime"] = runtime
    routes.install(store=state["store"], runtime=runtime,
                   principal_resolver=v4app._demo_resolver(cfg, runtime),
                   startup_sha=state["startup_sha"])
    worker = Worker(store=state["store"], runtime=runtime)
    supervisor = Supervisor(store=state["store"], lease_stale_seconds=10.0)
    threading.Thread(target=worker.serve_forever, daemon=True).start()
    threading.Thread(target=supervisor.serve_forever, daemon=True).start()
    return app


# ---- reading the run's own rows back -----------------------------------

def _rows_from(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The preview rows of the last scenario tool result in this conversation.

    The scripted analyst QUOTES the engine rather than restating a number, so
    a journey that shows the wrong figure is a real defect rather than a stub
    agreeing with itself.

    Two layers, and the first version only unwrapped one. A tool-result
    message's `content` is a JSON ARRAY of blocks, and each block's own
    `content` is a JSON STRING holding the tool's result. Scanning the outer
    text for `{` found the block wrapper, whose payload was still an
    unparsed string, so the rows were never reached and every preview
    rendered with empty values.
    """
    for message in reversed(messages):
        found = _tool_result_rows(message.get("content"))
        if found:
            return found
    return []


def _tool_result_rows(content: Any) -> list[dict[str, Any]]:
    """Every `preview` list inside one message, both layers unwrapped."""
    blocks = content
    if isinstance(blocks, str):
        try:
            blocks = json.loads(blocks)
        except ValueError:
            return []
    if not isinstance(blocks, list):
        return []
    out: list[dict[str, Any]] = []
    for block in blocks:
        if not isinstance(block, dict) or block.get("type") != "tool_result":
            continue
        payload = block.get("content")
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except ValueError:
                continue
        for node in _walk(payload):
            rows = node.get("preview")
            if isinstance(rows, list) and rows and isinstance(rows[0], dict):
                out.extend(rows)
    return out


def _walk(node: Any):
    """Every dict inside a nested structure, the node itself included."""
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value)


def _value(rows: list[dict[str, Any]], section: str, item: str) -> str:
    for row in rows:
        if row.get("section") == section and row.get("item") == item:
            return str(row.get("value", "") or row.get("scope", ""))
    return ""


def _stored_digest(messages: list[dict[str, Any]], system: Any = None) -> str:
    """The digest of the preview the reader is answering.

    Read from the CONTEXT THE PRODUCT HANDED THE ANALYST, which is the whole
    point of J02: `thread.remember` wrote the confirmed-scenario body after
    the preview turn settled, `context.scenario_packet` rendered it into this
    turn's packet, and `digest_to_confirm` is the field that says which
    scenario a yes approves.

    So this looks for that field by name rather than scanning for any
    64-character hex string. A scan was the first version and it was worse in
    both directions: it would have matched a membership hash or a release
    fingerprint just as happily, and when the packet carried no digest at all
    it fell back to zeros -- which reached the engine as a confirmation of
    something, and was refused as stale rather than as absent.
    """
    for blob in _texts(messages, system):
        found = _field_in(blob, "digest_to_confirm")
        if found:
            return found
    for blob in _texts(messages, system):
        found = _field_in(blob, "confirmed_digest")
        if found and len(found) == 64:
            return found
    return ""


def _texts(messages: list[dict[str, Any]], system: Any = None):
    """Every string this turn was handed, newest first."""
    for message in reversed(messages):
        content = message.get("content")
        if isinstance(content, str):
            yield content
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and isinstance(
                        block.get("text"), str):
                    yield block["text"]
    if isinstance(system, str):
        yield system
    elif isinstance(system, list):
        for block in system:
            if isinstance(block, dict) and isinstance(block.get("text"), str):
                yield block["text"]


def _field_in(blob: str, field: str) -> str:
    """One JSON field's value out of a block of text, or `""`.

    The packet's scenario block is `HEADER + "\n" + json.dumps(facts)`, so
    the facts are findable but the block as a whole is not valid JSON. Rather
    than guess at the header's length, every `{` is tried until one decodes
    to an object carrying the field.
    """
    marker = f'"{field}"'
    if marker not in blob:
        return ""
    decoder = json.JSONDecoder()
    for start in (i for i, c in enumerate(blob) if c == "{"):
        try:
            parsed, _ = decoder.raw_decode(blob[start:])
        except ValueError:
            continue
        for node in _walk(parsed):
            value = node.get(field)
            if isinstance(value, str) and value:
                return value
    return ""


def _step_of(messages: list[dict[str, Any]]) -> dict[str, Any]:
    """The last tool-result STEP in this conversation, whole.

    The step, not only its rows: `artifact_id` is what an `EvidenceRef` has
    to name, and a claim without one is refused --
    *"numeric_claims[0] carries neither 'evidence' nor 'derivation'"*.
    """
    for message in reversed(messages):
        blocks = message.get("content")
        if isinstance(blocks, str):
            try:
                blocks = json.loads(blocks)
            except ValueError:
                continue
        if not isinstance(blocks, list):
            continue
        for block in blocks:
            if (not isinstance(block, dict)
                    or block.get("type") != "tool_result"):
                continue
            payload = block.get("content")
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except ValueError:
                    continue
            for node in _walk(payload):
                steps = node.get("steps")
                if not isinstance(steps, list):
                    continue
                for step in steps:
                    if (isinstance(step, dict) and step.get("artifact_id")
                            and isinstance(step.get("preview"), list)
                            and step["preview"]):
                        return step
    return {}


#: The measures the answer quotes, in the order a reader meets them, with the
#: claim id each gets. Named rather than "the first six numeric rows": a
#: narrative that quotes whichever rows happened to come first is a narrative
#: nobody can review.
#: Each quoted figure as (claim id, the row's `measure`, the column, the unit).
#:
#: The PERCENTAGE change is quoted as well as the absolute one, and not for
#: symmetry: the display policy fixes a riyal amount at whole numbers
#: (`display.PERMITTED[MONETARY_AMOUNT] == (0,)`), and the Retail book's
#: monthly cohort carries about SAR 1.7 million of ECL, so a real 20% rise
#: rounds in prose to "SAR 2 million becomes SAR 2 million". The percentage is
#: a percentage class, carries two decimals, and states the movement exactly.
QUOTED: tuple[tuple[str, str, str, str], ...] = (
    ("baseline", "cohort:Total ECL", "baseline_sar_mn", "SAR million"),
    ("scenario", "cohort:Total ECL", "scenario_sar_mn", "SAR million"),
    ("change", "cohort:Total ECL", "change_sar_mn", "SAR million"),
    ("change_pct", "cohort:Total ECL", "change_pct", "percent"),
    ("book_before", "book:Total ECL", "baseline_sar_mn", "SAR million"),
    ("book_after", "book:Total ECL", "scenario_sar_mn", "SAR million"),
)


def plain_body(step: dict[str, Any], *, question: str, dimension: str,
               intent_of, final_of) -> dict[str, Any]:
    """The investigation turn's answer: an ordinary SQL result, cited.

    Separate from `answer_body` because a scenario result and a SELECT are
    different shapes. The first version used one builder for both, keyed on
    the scenario table's `measure` column -- which a plain query does not
    have, so every claim came back without evidence and the investigation
    turn published as PARTIAL with ANSWER_VALIDATION. A builder that cannot
    find its rows should not produce a claim about them.
    """
    rows = list(step.get("preview") or [])
    artifact = str(step.get("artifact_id") or "")
    if not rows or dimension not in rows[0]:
        return final_of(
            intent=intent_of("DATA_ANALYSIS", "COCKPIT",
                             understood=question),
            narrative=("The rows this query produced are in the table "
                       "below. Measured on a generated book: not bank "
                       "output and not an accounting figure."),
            tables=[{"title": "Result", "artifact_id": artifact,
                     "columns": list(rows[0]) if rows else []}],
            limitations=[_SYNTHETIC])
    top = rows[0]
    return final_of(
        intent=intent_of("DATA_ANALYSIS", "COCKPIT", understood=question),
        narrative=("The cohort in view carries {{claim.ecl}} of reported "
                   "ECL across {{claim.count}} exposures. Measured on a "
                   "generated book: no figure here is bank output, an "
                   "accounting figure or bank-validated."),
        numeric_claims=[
            {"claim_id": "ecl", "unit": "SAR million",
             "evidence": {"artifact_id": artifact,
                          "row_key": f"{dimension}={top[dimension]}",
                          "column_id": "ecl_sar_mn"}},
            {"claim_id": "count", "unit": "count",
             "evidence": {"artifact_id": artifact,
                          "row_key": f"{dimension}={top[dimension]}",
                          "column_id": "exposures"}}],
        coverage=[{"subquestion": question[:120] or "the cohort",
                   "status": "answered",
                   "evidence_refs": [
                       {"artifact_id": artifact,
                        "row_key": f"{dimension}={top[dimension]}",
                        "column_id": "ecl_sar_mn"}]}],
        tables=[{"title": "The cohort as it stands",
                 "artifact_id": artifact,
                 "columns": [dimension, "exposures", "ead_sar_mn",
                             "ecl_sar_mn"]}],
        charts=[{"kind": "bar", "title": "Reported ECL",
                 "artifact_id": artifact, "x_column": dimension,
                 "y_columns": ["ecl_sar_mn"], "unit": "SAR million"}],
        limitations=[_SYNTHETIC])


#: One sentence, on every answer this stub writes.
_SYNTHETIC = (
    "Measured on a generated book. Not bank output, not an accounting "
    "figure, and no model or sensitivity here is bank-validated.")


def answer_body(step: dict[str, Any], *, question: str, charts: bool,
                intent_of, final_of) -> dict[str, Any]:
    """A `finalize_response` body built from the step the engine produced.

    Every number is a CLAIM with an `evidence` reference into the stored
    artifact, and the narrative carries `{{claim.<id>}}` placeholders rather
    than digits -- the server owns the numeric string, so a figure that did
    not come out of the artifact cannot appear in the prose.
    """
    rows = {str(r.get("measure", "")): r for r in step.get("preview") or []}
    artifact = str(step.get("artifact_id") or "")
    claims: list[dict[str, Any]] = []
    for claim_id, measure, column, unit in QUOTED:
        row = rows.get(measure)
        if not row or not str(row.get(column) or "").strip():
            continue
        claims.append({
            "claim_id": claim_id,
            "unit": unit,
            "evidence": {"artifact_id": artifact,
                         "row_key": f"measure={measure}",
                         "column_id": column}})
    methods = [r for r in (step.get("preview") or [])
               if r.get("section") == "method"]
    for index, row in enumerate(methods, start=1):
        if not str(row.get("scenario_sar_mn") or "").strip():
            # An unavailable method has no number to quote, and inventing a
            # zero here is the substitution section 12 forbids.
            continue
        claims.append({
            "claim_id": f"method{index}",
            "unit": "SAR million",
            "evidence": {"artifact_id": artifact,
                         "row_key": f"measure={row['measure']}",
                         "column_id": "scenario_sar_mn"}})
    have = {c["claim_id"] for c in claims}
    cohort = rows.get("cohort:Total ECL") or {}
    narrative = _narrative(have, methods,
                           cohort_change=str(cohort.get("change_sar_mn") or ""))
    # `note` IS SHOWN, NOT HIDDEN.
    #
    # It carries the sentences that stop a number being misread -- "exactly
    # zero, not approximately", the gate a method failed, which engine and
    # which model wrote this result. Leaving it out of the declared columns put
    # all of that in the artifact where only an auditor could reach it, and the
    # export inherited the same omission.
    tables = [{"title": "Scenario result",
               "artifact_id": artifact,
               "columns": ["section", "item", "baseline_sar_mn",
                           "scenario_sar_mn", "change_sar_mn", "change_pct",
                           "status", "note"]}]
    chart_specs: list[dict[str, Any]] = []
    if charts and methods:
        chart_specs = [
            {"kind": "grouped_bar",
             "title": "Baseline against scenario, by method",
             "artifact_id": artifact, "x_column": "item",
             "y_columns": ["baseline_sar_mn", "scenario_sar_mn"],
             "unit": "SAR million"},
            {"kind": "waterfall",
             "title": "What moved the ECL",
             "artifact_id": artifact, "x_column": "item",
             "y_columns": ["change_sar_mn"], "unit": "SAR million"},
        ]
    return final_of(
        intent=intent_of("DATA_ANALYSIS", "COCKPIT", understood=question),
        narrative=narrative,
        numeric_claims=claims,
        coverage=[{"subquestion": question[:120] or "the scenario",
                   "status": "answered",
                   "evidence_refs": [c["evidence"] for c in claims[:1]]}]
        if claims else [],
        tables=tables, charts=chart_specs,
        limitations=_limitations(step.get("preview") or []))


def _rounds_to_nothing(raw: str) -> bool:
    """Would the display policy write this riyal amount as zero?

    `display.PERMITTED[MONETARY_AMOUNT]` is `(0,)`, so anything under half a
    million is written "SAR 0 million". True here is not an error; it is the
    cue to say out loud that the absolute figure is rounded and the percentage
    is not.
    """
    text = str(raw or "").strip()
    if not text:
        return False
    try:
        value = Decimal(text)
    except (ArithmeticError, ValueError):
        return False
    return value != 0 and abs(value) < Decimal("0.5")


def _narrative(have: set[str], methods: list[dict[str, Any]], *,
               cohort_change: str = "") -> str:
    """Prose with placeholders, never digits.

    A narrative that spelled a number out would be the analyst formatting
    currency, which is the one thing section 7 of the accepted brief took
    away from it. `{{claim.x}}` is resolved by CreditProbe from the evidence.
    """
    if "baseline" not in have:
        return ("The rows this run produced are in the table below. Every "
                "figure in it came from the run. Measured on a generated "
                "book: not bank output and not an accounting figure.")
    lines = ["On the frozen cohort, baseline ECL of {{claim.baseline}} "
             "becomes {{claim.scenario}} under this scenario, a change of "
             "{{claim.change}}"
             + (" ({{claim.change_pct}})." if "change_pct" in have else ".")]
    # WHEN THE RIYAL FIGURE ROUNDS TO NOTHING, SAY SO.
    #
    # A riyal amount is written to whole numbers, and the Retail book's monthly
    # cohort is small enough that a real 20% PD rise reads "SAR 2 million
    # becomes SAR 2 million, a change of SAR 0 million". Every digit there is
    # the display policy doing its job, and together they say the opposite of
    # what happened. The percentage above is exact; this sentence tells the
    # reader why the two look inconsistent and where the full precision is.
    if _rounds_to_nothing(cohort_change) and "change_pct" in have:
        lines.append(
            "At this book's scale a riyal amount is written to whole "
            "millions, so the absolute change above rounds to zero even "
            "though the scenario moved the cohort's ECL by the percentage "
            "stated: the unrounded baseline, scenario and change are in the "
            "table below, and nothing here was rounded before it was "
            "computed.")
    if "book_before" in have and "book_after" in have:
        lines.append("Across the whole book that is {{claim.book_before}} "
                     "becoming {{claim.book_after}}: every exposure outside "
                     "the cohort is unchanged, and its change is exactly "
                     "zero rather than approximately zero.")
    # EVERY METHOD NAMED, WITH ITS OWN STATUS AND ITS OWN FIGURE.
    #
    # "method1 / method2 / method3" told a reader nothing: which of them was
    # the model, and which was the reader's own assumption, was legible only
    # in a table row they had to expand to reach. A composed line names each
    # method, gives its figure through its own claim, and says outright when
    # one is not ready -- which is also the side-by-side statement the brief
    # asks for, with no average and no substituted number.
    status_parts: list[str] = []
    for index, row in enumerate(methods, start=1):
        label = str(row.get("item") or f"method {index}")
        if str(row.get("scenario_sar_mn") or "").strip():
            status_parts.append(f"{label} COMPLETE at {{{{claim.method{index}}}}}")
        else:
            reason = str(row.get("note") or row.get("status") or "").strip()
            status_parts.append(
                f"{label} NOT READY{f' — {reason}' if reason else ''}")
    if status_parts:
        lines.append(
            "Each method ran against the same confirmed scenario, the same "
            "frozen cohort, the same release and the same baseline, and they "
            "are shown side by side rather than averaged: "
            + "; ".join(status_parts) + ".")
    held = [m for m in methods
            if not str(m.get("scenario_sar_mn") or "").strip()]
    for row in held:
        lines.append(
            f"{row.get('item')} produced no estimate and its cells are "
            f"empty rather than zero: {row.get('note')}")
    lines.append("Nothing in the source changed. This is a simulation over "
                 "a generated book, and no figure here is bank output, an "
                 "accounting figure or bank-validated.")
    return " ".join(lines)


def _limitations(rows: list[dict[str, Any]]) -> list[str]:
    out = [_SYNTHETIC]
    for row in rows:
        if (row.get("section") == "method"
                and "UNAVAILABLE" in str(row.get("status", ""))):
            out.append(f"{row.get('item')} did not run: {row.get('note')}")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8424)
    parser.add_argument("--ui-port", type=int, default=0)
    parser.add_argument("--domain", default="corporate",
                       choices=sorted(CANDIDATE))
    parser.add_argument("--runtime-dir", default="")
    args = parser.parse_args()

    import uvicorn

    runtime_dir = Path(args.runtime_dir
                       or f"/tmp/cockpit_v4_whatif_{args.port}")
    runtime_dir.mkdir(parents=True, exist_ok=True)
    app = build_app(args.port, runtime_dir, domain_id=args.domain,
                    ui_port=args.ui_port)
    print(f"what-if stub V4 API listening on http://127.0.0.1:{args.port} "
          f"({args.domain}, {CANDIDATE[args.domain]})", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
