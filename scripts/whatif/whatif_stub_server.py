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

        Reads the tool result out of the conversation rather than restating a
        number, because the point of the journey is that the figure in the
        answer is the figure the engine computed.
        """
        rows = _rows_from(messages)
        claims, tables, chart_specs = _claims(rows, charts=charts)
        return ScriptedResult(tool_calls=[tool_call(
            "finalize_response",
            final(intent=intent("DATA_ANALYSIS", "COCKPIT",
                                understood=question),
                  narrative=_narrative(rows, claims),
                  numeric_claims=claims, tables=tables,
                  charts=chart_specs,
                  limitations=_limitations(rows),
                  evidence_refs=[]),
            "tu-answer")])

    def preview_clarification(messages: list[dict[str, Any]], *,
                              question: str) -> Any:
        """The preview, published as a clarification the reader confirms."""
        rows = _rows_from(messages)
        digest = _value(rows, "confirmation", "Digest to approve")
        return ScriptedResult(tool_calls=[tool_call(
            "finalize_response",
            final(intent=intent("DATA_ANALYSIS", "COCKPIT",
                                understood=question),
                  disposition="clarification",
                  narrative="",
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
                          "columns": ["section", "item", "detail", "value",
                                      "status"],
                          "rows": [[r.get("section", ""), r.get("item", ""),
                                    r.get("detail", ""), str(r.get("value", "")),
                                    r.get("status", "")]
                                   for r in rows],
                          "row_ids": []}]),
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
            for message in messages:
                content = message.get("content")
                if isinstance(content, str) and "USER REQUEST" in content:
                    return content.lower()
            return ""

        def converse(self, *, system, messages, tools=None, max_tokens=4096,
                     model="", purpose="", role="", timeout=0.0,
                     allow_retry=True, effort="", tool_choice=None,
                     output_config=None):
            question = self._question(messages)
            turn = sum(1 for m in messages if m.get("role") == "assistant")
            time.sleep(0.4)
            return _script(question, turn, messages)

    def _script(question: str, turn: int, messages) -> Any:
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
                digest = _stored_digest(messages)
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
            return answer_from(messages, question=asked)

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
    """The preview rows of the LAST tool result in this conversation.

    The scripted analyst quotes the engine rather than restating a number, so
    a journey that shows the wrong figure is a real defect rather than a stub
    that agreed with itself.
    """
    for message in reversed(messages):
        content = message.get("content")
        if not isinstance(content, str) or "preview" not in content:
            continue
        found = _preview_rows(content)
        if found:
            return found
    for message in reversed(messages):
        content = message.get("content")
        if isinstance(content, str):
            found = _preview_rows(content)
            if found:
                return found
    return []


def _preview_rows(content: str) -> list[dict[str, Any]]:
    """Every `preview` list in a tool-result blob, flattened."""
    out: list[dict[str, Any]] = []
    for start in range(len(content)):
        if content[start] != "{":
            continue
        try:
            parsed, _ = json.JSONDecoder().raw_decode(content[start:])
        except ValueError:
            continue
        for step in _walk(parsed):
            rows = step.get("preview")
            if isinstance(rows, list) and rows and isinstance(rows[0], dict):
                out.extend(rows)
        if out:
            return out
    return out


def _walk(node: Any):
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


def _stored_digest(messages: list[dict[str, Any]]) -> str:
    """The digest of the preview the reader is answering.

    Read from the conversation, not remembered in the stub: the whole claim
    of J02 is that the confirmation names the scenario the reader was SHOWN.
    """
    for message in reversed(messages):
        content = message.get("content")
        if not isinstance(content, str):
            continue
        for token in content.replace('"', " ").replace("'", " ").split():
            candidate = token.strip(",:;)(")
            if (len(candidate) == 64
                    and all(c in "0123456789abcdef" for c in candidate)):
                return candidate
    return "0" * 64


def _claims(rows: list[dict[str, Any]], *, charts: bool):
    """Numeric claims, a table and a chart, from whatever rows came back."""
    claims: list[dict[str, Any]] = []
    money = [r for r in rows
             if str(r.get("baseline_sar_mn") or "").strip()
             and str(r.get("scenario_sar_mn") or "").strip()]
    for row in money[:6]:
        claims.append({
            "claim_id": f"c{len(claims) + 1}",
            "label": f"{row.get('section', '')} {row.get('item', '')}",
            "value": str(row.get("scenario_sar_mn")),
            "unit": "SAR million", "row_ids": [], "operation": "as computed",
            "operands": []})
    tables = [{"title": "Scenario result",
               "columns": ["section", "item", "baseline_sar_mn",
                           "scenario_sar_mn", "change_sar_mn", "status"],
               "rows": [[r.get("section", ""), r.get("item", ""),
                         str(r.get("baseline_sar_mn", "")),
                         str(r.get("scenario_sar_mn", "")),
                         str(r.get("change_sar_mn", "")),
                         r.get("status", "")] for r in rows],
               "row_ids": []}]
    chart_specs: list[dict[str, Any]] = []
    if charts and money:
        chart_specs.append({
            "title": "Baseline against scenario, by method",
            "kind": "grouped_bar",
            "x_label": "method", "y_label": "SAR million",
            "series": [
                {"name": "baseline",
                 "points": [{"x": str(r.get("item")),
                             "y": float(r.get("baseline_sar_mn") or 0)}
                            for r in money if r.get("section") == "method"]},
                {"name": "scenario",
                 "points": [{"x": str(r.get("item")),
                             "y": float(r.get("scenario_sar_mn") or 0)}
                            for r in money if r.get("section") == "method"]},
            ]})
    return claims, tables, chart_specs


def _narrative(rows: list[dict[str, Any]], claims) -> str:
    cohort = [r for r in rows
              if r.get("section") == "cohort" and r.get("item") == "Total ECL"]
    if not cohort:
        return ("The rows this run produced are in the table below. Every "
                "figure in it came from the run and none of it is bank "
                "output: this is a generated book.")
    row = cohort[0]
    return (
        f"On the frozen cohort, baseline ECL of {row.get('baseline_sar_mn')} "
        f"SAR million becomes {row.get('scenario_sar_mn')} SAR million under "
        f"this scenario -- a change of {row.get('change_sar_mn')} SAR "
        f"million. The methods are shown side by side below, each against the "
        f"same confirmed scenario, the same frozen cohort and the same "
        f"baseline. Nothing in the source was changed: this is a simulation "
        f"over a generated book.")


def _limitations(rows: list[dict[str, Any]]) -> list[str]:
    out = ["Measured on a generated book. Not bank output, not an accounting "
           "figure, and no model or sensitivity here is bank-validated."]
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
