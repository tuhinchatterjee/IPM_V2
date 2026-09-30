# Protected extension map — Guided Risk Workspace round

Every difference `scripts/guided_workspace/protected_baseline.py --check`
reports against the H2 checkpoint `feb80f58` is listed here with the exact
incompatibility, the smallest change made, the authorising section of the v3.1
master specification, and the named test that pins it. A difference not listed
here is a defect. No hash was regenerated to hide a change; the H2 manifest was
captured once at P0 and is never rewritten.

The accepted-baseline tool (`scripts/whatif/protected_hashes.py`, against
`245c50e`) keeps reporting its own counts; see `BASELINE_PROVENANCE.md` §4 for
why its data rows differ in this container.

| # | Protected file | Phase | Incompatibility (why no unprotected seam exists) | Smallest change made | Authorisation | Flags-off behaviour | Named test(s) |
|---|---|---|---|---|---|---|---|
| 1 | `backend/cockpit_v4/worker.py` | P1 | The analyst's provider object is handed to `Analyst(...)` inside `Worker._drive`; the run id, thread id and tenant the recorder must stamp on each call exist only there. `backend/llm/*` (unprotected) sees the request but not which run it belongs to. | One argument: `provider=llm_exchange.bind(self.runtime.provider, runtime=self.runtime, run=record)` plus a local import. | §43 P1, §47 ("a common passive LLM Exchange Recorder used by AdvancedCockpit, What-If, Lenses and AI Model Lab") | `bind` returns **the same provider object** when `COCKPIT_V4_LLM_EXCHANGE_TRACE` is off. | `test_bind_returns_the_same_provider_object_when_the_flag_is_off`, `test_a_run_sends_byte_identical_requests_with_the_recorder_on`, `test_the_recorder_adds_no_model_call`, `test_the_recorder_forwards_the_identical_argument_objects` |
| 2 | `backend/cockpit_v4/app.py` | P1 (G1 shell) | `create_app` is the only place routers are mounted on the V4 app; the frontend's V4 runtime guard only lets `/api/v1/cockpit-v4/…` calls through, so the workspace API must live on this app. No router registry exists (`BASELINE_AND_EXTENSION_MAP.md` §2). | Six lines after `app.include_router(routes.compat_router)`: import the workspace flag; if on, include `backend.workspace.api.router`. | §39 ARCH-03 ("explicitly authorized generic UX shell additions"), §43 P1/P2 | Router not included; every workspace path is 404. | `test_the_workspace_router_is_absent_when_its_flag_is_off` |
| 3 | `frontend/src/app/cockpit/trace/[runId]/page.tsx` | P1 | "Trace > LLM Exchange" must be reachable from the run's trace; the governance record page is that trace. | One `Link` under the run id, to `/trace/llm-exchange/[runId]` (an unprotected route). | §43 P1 ("Add Trace > LLM Exchange") | Link present; page shows "recorder off / no calls recorded" honestly when the flag was off during the run. | Browser `GW-P1-01` |

Unprotected seams used instead of protected ones (recorded so a reviewer can
see what was deliberately *not* touched):

* `backend/llm/anthropic_provider.py` — two passive `exchange.adapter_stage(...)`
  calls (the provider-native request body and the raw SDK message). Not a
  protected file; covered by `tests/llm` (17 passed, 8 skipped — identical to H2)
  and `test_the_anthropic_adapter_request_and_raw_response_are_recorded`.
* `backend/llm/exchange.py`, `backend/llm/openai_compatible.py`, `backend/workspace/*` — new modules.
