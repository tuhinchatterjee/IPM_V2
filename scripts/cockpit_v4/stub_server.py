#!/usr/bin/env python3
"""
Run the real V4 API with a scripted analyst, for browser testing.

Everything here is the real thing except the model: the real routes, the real
durable store, the real worker and supervisor, the real event stream, and the
real DuckDB session against the published release. Only `converse` is
scripted.

The script is chosen by the QUESTION, so one server covers every browser
scenario without the test reaching in to reconfigure it between cases:

    "Who are you?"          one call, a product-help answer
    "...fail..."            an application failure with a support reference
    "...slow..."            a stalled run, so cancel and refresh have
                            something to act on
    anything else           a real SQL analysis over the release

Usage:
    python3 scripts/cockpit_v4/stub_server.py --port 8414
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests" / "cockpit_v4"))

RELEASE = os.environ.get("COCKPIT_V4_TEST_RELEASE", "v4-uat-20q-v1")


def build_app(port: int, runtime_dir: Path, ui_port: int = 0):
    os.environ.setdefault("COCKPIT_AGENTIC_V3_NAMESPACE", "cockpit_v4")

    import oracles
    from conftest import ScriptedResult, final, intent, tool_call

    from backend.cockpit_v4 import app as v4app
    from backend.cockpit_v4 import routes
    from backend.cockpit_v4.capability import Capability, PriceCard
    from backend.cockpit_v4.config import V4Config
    from backend.cockpit_v4.service import Runtime, load_release
    from backend.cockpit_v4.supervisor import Supervisor
    from backend.cockpit_v4.worker import Worker

    cfg = V4Config(
        enabled=True, provider="anthropic", reasoning_model="stub-analyst",
        runtime_dir=runtime_dir,
        state_database=str(runtime_dir / "state" / "browser.sqlite3"),
        # The REAL UI port. The app's CORS allow-list is built from it,
        # and a guessed value silently blocks every browser request.
        release_id=RELEASE, api_port=port,
        ui_port=ui_port or port + 1,
        local_demo_auth=True, price_card_path="", memory_enabled=False,
        memory_model="", default_mode="standard", heartbeat_seconds=1.0,
        lease_heartbeat_seconds=2.0, lease_stale_seconds=10.0,
        supervisor_poll_seconds=2.0, credential_present=True, missing=())
    capability = Capability(
        provider="anthropic", model_id="stub-analyst", sdk_version="browser",
        context_tokens=200_000, max_output_tokens=8192, supports_tools=True,
        supports_token_counting=True,
        price=PriceCard(15.0, 75.0, 18.75, 1.5), source="browser stub",
        verified_at="2026-09-11T00:00:00Z", live_verified=True)

    catalog, _, summary = load_release(cfg)
    quarter = oracles.latest_quarter(RELEASE)
    ead_sql = (f"SELECT sector_name, SUM(ead_reported) AS ead_crore "
               f"FROM cockpit_facility_quarter "
               f"WHERE reporting_quarter = '{quarter}' "
               f"GROUP BY sector_name ORDER BY ead_crore DESC")

    def help_answer():
        return ScriptedResult(tool_calls=[tool_call(
            "finalize_response",
            final(intent=intent("PRODUCT_HELP", "COCKPIT",
                                understood="who this assistant is"),
                  narrative=("I am CreditProbe Cockpit. I analyse the "
                             "recorded corporate credit book and answer "
                             "questions about CreditProbe itself."),
                  coverage=[{"subquestion": "who are you",
                             "status": "answered", "evidence_refs": []}]),
            "tu-help")])

    def analysis_call():
        return ScriptedResult(tool_calls=[tool_call("execute_analysis", {
            "intent": intent("DATA_ANALYSIS", "COCKPIT",
                             understood="reported EAD by sector"),
            "objective": "Reported EAD by sector for the latest quarter",
            "subquestions": ["EAD by sector"],
            "scope": {"reporting_quarters": [quarter], "filters": {}},
            "metadata_receipt_ids": [],
            "fields_required": ["cockpit_facility_quarter.ead_reported"],
            "expected_output_grain": "sector",
            "expected_units": "INR crore",
            "steps": [{"step_id": "s1", "language": "sql", "code": ead_sql,
                       "parameters": {}, "purpose": "EAD by sector",
                       "input_artifact_ids": [], "depends_on_step_ids": []}],
            "repair_of_submission_id": ""}, "tu-exec")])

    def analysis_finish(messages):
        body = json.loads(messages[-1]["content"][0]["content"])
        step = body["steps"][0]
        cell = step["preview"][0]
        return ScriptedResult(tool_calls=[tool_call(
            "finalize_response",
            final(intent=intent("DATA_ANALYSIS", "COCKPIT",
                                understood="reported EAD by sector"),
                  narrative=("The largest reported exposure this quarter is "
                             "{{claim.top}}."),
                  coverage=[{"subquestion": "EAD by sector",
                             "status": "answered",
                             "evidence_refs": [
                                 {"artifact_id": step["artifact_id"],
                                  "row_key": f"sector_name="
                                             f"{cell['sector_name']}",
                                  "column_id": "ead_crore"}]}],
                  numeric_claims=[{
                      "claim_id": "top",
                      "decimal_value": repr(float(cell["ead_crore"])),
                      "unit": "INR crore", "display_precision": 2,
                      "evidence": {"artifact_id": step["artifact_id"],
                                   "row_key": f"sector_name="
                                              f"{cell['sector_name']}",
                                   "column_id": "ead_crore"}}],
                  tables=[{"title": "Reported EAD by sector",
                           "artifact_id": step["artifact_id"],
                           "columns": ["sector_name", "ead_crore"]}]),
            "tu-final")])

    def stall():
        """A run that keeps working, one modest action at a time.

        Deliberately NOT one long sleep. V4 observes a cancellation BETWEEN
        actions -- it does not abort an in-flight provider call, which is what
        the run deadline and the supervisor are for. A stub that blocks for
        thirty seconds inside `converse` would be testing whether we can
        interrupt a socket, which is not the mechanism, and would make a
        correct implementation look broken.
        """
        return ScriptedResult(tool_calls=[tool_call(
            "inspect_catalog",
            {"intent": intent("DATA_ANALYSIS", "COCKPIT",
                              understood="looking for the right fields"),
             "query": "exposure", "relation_ids": [], "field_ids": [],
             "detail": ["discovery"], "reporting_quarters": [],
             "sample_rows": 0, "cursor": ""},
            "tu-slow")])

    class QuestionDrivenProvider:
        """One `converse` per turn, scripted from the question under way."""

        def __init__(self) -> None:
            self.turns: dict[str, int] = {}
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
                     allow_retry=True, effort=""):
            assert allow_retry is False
            question = self._question(messages)
            key = question[:120]
            with self.lock:
                turn = self.turns.get(key, 0)
                self.turns[key] = turn + 1

            # A visible pause so the browser observes progress arriving
            # BEFORE the answer, which is the property under test.
            time.sleep(1.0)

            if "fail" in question:
                raise KeyError("a scripted application defect")
            if "slow" in question:
                return stall()
            if "who are you" in question:
                return help_answer()
            return analysis_call() if turn == 0 else analysis_finish(messages)

    provider = QuestionDrivenProvider()
    runtime = Runtime(cfg=cfg, capability=capability, provider=provider,
                      catalog=catalog, coverage=None,
                      release_summary=summary)
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8414)
    parser.add_argument("--ui-port", type=int, default=0)
    parser.add_argument("--runtime-dir",
                        default="/tmp/cockpit_v4_browser")
    args = parser.parse_args()

    import uvicorn

    runtime_dir = Path(args.runtime_dir)
    runtime_dir.mkdir(parents=True, exist_ok=True)
    app = build_app(args.port, runtime_dir, ui_port=args.ui_port)
    print(f"stub V4 API listening on http://127.0.0.1:{args.port}",
          flush=True)
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
