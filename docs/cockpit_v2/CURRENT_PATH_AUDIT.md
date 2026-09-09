# Cockpit Intelligence V2 — audit of the actual answer path

Brief §2. Every claim in the original Phase 0–3 plan (Appendix B of
`IMPLEMENTATION_BRIEF.md`) was re-checked against the code at base commit
`3855f9b6f6b231beb6f2193c8a1e219d01596421`. Nothing below is carried over from
the old plan on trust.

## 1. The real call chain

```
frontend/src/app/page.tsx  (CockpitPage → Cockpit)
  └─ frontend/src/components/ask/composer.tsx      user types the question
       └─ POST /api/v1/ask                         backend/api/routers/ask.py:261 ask()
            ├─ backend/analyst/classify.py:read()  question class A/B/C
            ├─ backend/analyst/cost.py:measuring() cost meter
            └─ _ask()                              ask.py:285
                 ├─ backend/orchestration/executor.py:898 run_investigation()
                 │    └─ :912 answer_investigation()
                 │         ├─ orchestrator.answer()      reads the question
                 │         ├─ assembly.from_analysis()   builds the Investigation
                 │         ├─ :1013 _apply_interpretation()   ← the visible prose
                 │         └─ _check_grounding()
                 └─ :318 _analyst_view()
                      └─ backend/analyst/route.py:80 answer()
                           ├─ answers.recall(run key)        §11 cache
                           ├─ CLASS_A → _from_catalogue()    no model call
                           ├─ session.investigate()          the analyst loop
                           └─ fallback → deterministic
  response body:  { narrative:{…}, result:{…}, graph:{…}, analyst:{…}, cost:{…} }
       └─ frontend/src/components/ask/answer.tsx renders it
```

The response carries **two** narratives. `body["narrative"]` is the
deterministic one and is what the screen shows. `body["analyst"]` is the
analyst's own payload and its `answer` / `findings` are never read by the
frontend.

Both streaming and non-streaming were looked for: `POST /ask` is a single
non-streaming JSON response. There is no SSE/websocket answer path to test, so
the "test streaming too" instruction in §2.1 has nothing to apply to here, and
that is recorded rather than reported as done.

## 2. Original plan's claims, classified

| # | Original claim | Verdict | Evidence at base commit |
|---|---|---|---|
| P1.1 | `_ask` runs the deterministic pipeline **and** the analyst loop separately | **CONFIRMED** | `ask.py:291` `run_investigation(...)`, then `ask.py:310` `body["analyst"] = _analyst_view(...)`. Both run on every request; neither is conditioned on the other. |
| P1.2 | The analyst's `answer` and `findings` are never rendered | **CONFIRMED** | `answer.tsx:1081-1084` reads only `run.analyst?.interpretation`, `.alternatives`, `.confirm_or_refute`, `.external_context`. `analyst.answer` and `analyst.findings` appear nowhere in `frontend/src/`. They exist in the payload — `session.py:262-278`. |
| P1.3 | Visible prose comes from `orchestration/interpretation.py` | **CONFIRMED** | `answer.tsx:987-996` renders `narrative.direct_answer \|\| narrative.summary` and `narrative.interpretation_points`; those are written by `executor.py:1013 _apply_interpretation()`. |
| P1.4 | `narrative.prose_source` should record which path wrote the sentence | **NOT PRESENT** | The string `prose_source` does not occur anywhere in the repository. |
| P1.5 | The interpretation call is paid for and then discarded | **CONFIRMED, with a correction** | It is not discarded — it is the one that *wins*. The analyst's is the discarded output. Both are produced. The waste is real; the direction stated in the old plan is backwards. |
| P2.1 | A `_CAUSAL` regex discards causal sentences | **CONFIRMED** | `orchestration/evidence.py:168` compiles `\bbecause\b\|\bdue to\b\|\bcaused by\b\|\bdriven by\b\|\bas a result of\b`; `evidence.py:378-381` appends every matching sentence to `grounding.causal_claims`, and `grounding.ok` is false when that list is non-empty. |
| P2.2 | `decompose_movement` does not exist | **CONFIRMED** | No occurrence in the repository. |
| P2.3 | `decompose_ratio` does not exist | **CONFIRMED** | No occurrence. |
| P2.4 | `metric_history` does not exist | **CONFIRMED** | No occurrence. |
| P2.5 | `list_certified_analyses` does not exist; the model must guess analysis IDs | **CONFIRMED** | `tools.py:1424-1592` registry: discovery tools cover domains, datasets, dictionary, measures, dimensions, periods, relationships, metric/threshold/model/policy definitions — none enumerates certified analyses. `run_governed_analysis` takes an `analysis` id with no way to list valid ones. |
| P2.6 | `rubric.py` has a `NON_CAUSAL` safety criterion | **CONFIRMED** | `rubric.py:42` `NON_CAUSAL = "non_causal"`; `rubric.py:52` includes it in `SAFETY`; `rubric.py:177` scores it. There is no `CAUSE_IS_EVIDENCED` and no `ATTRIBUTION_QUANTIFIED`. |
| P3.1 | `MAX_PLANNING_TURNS = 4`, flat for every question | **CONFIRMED** | `analyst/safety.py:76` `MAX_PLANNING_TURNS = 4`; `:77` `MAX_TURNS = MAX_PLANNING_TURNS + 1`; `:66` `MAX_TOOL_CALLS = 12`. Neither is a function of the question class, although `classify.py` already computes A/B/C. |
| P3.2 | Discovery burns turns; a catalogue digest belongs in the cached stable blocks | **PARTLY ALREADY FIXED** | `analyst/session.py` does cache stable prompt blocks, and `route.py:121-138` short-circuits class-A questions to the catalogue with no model call at all. The *digest of dataset names/grain/periods* is still not in the stable block, so a class-B/C question still spends turns on `list_datasets` / `describe_dataset`. |
| P3.3 | `tests/evals/golden_answers.json` should exist | **NOT PRESENT** | `tests/evals/` exists but holds no golden-answer case file. |
| P0 | Roles all resolve to one model unless `AI_*_MODEL` vars are set | **NOT VERIFIABLE HERE** | `backend/llm/roles.py` exists and `describe()` is present, but with no provider credential the resolution cannot be exercised. See §4. |

### Claims that are different in the current implementation

* The old plan describes a single `_ask` with the analyst bolted on. The current
  code has an explicit **router** — `backend/analyst/route.py` — that the plan
  does not mention: run-key reproduction cache (`answers.recall`), a class-A
  catalogue path with no model call, then the analyst, then the deterministic
  fallback. This is a working component. Brief §2.1 says not to reimplement a
  working component because the old review did not mention it, so it is kept and
  extended, not replaced.
* `backend/analyst/tools.py` already carries 28 governed tools with capability
  checks and a permission-filtered `describe_all`. The four new tools are added
  to that registry rather than to a new parallel one.
* The old plan's Phase 0 `.env` block names seven role models. Brief §0 forbids
  copying those IDs into configuration without provider verification, and §4
  below records why none of them was written anywhere.

## 3. Where the visible answer actually comes from — measured

Captured live against the isolated backend at `127.0.0.1:8100`, base behaviour,
flag off. Full payloads: `docs/cockpit_v2/evidence/baseline_answers.json`.

For every one of the twelve baseline questions the response carried
`analyst.path == "deterministic"` and
`analyst.why == "no intelligence provider is configured, so the governed
semantic reader answered"`. So in *this* environment the analyst never runs and
the deterministic reader is the whole path. The Phase 1 defect is real in the
code, but it cannot be the cause of the answer quality observed here — with no
provider there is no analyst output to lose. That distinction matters and is
carried into the evaluation report: **improving the visible-prose precedence
alone would change nothing in an offline deployment.**

## 4. Model verification — LIVE_PROVIDER_UNVERIFIED

* `settings.anthropic_api_key` resolves to `""`; `ANTHROPIC_API_KEY` is unset
  and there is no `.env` in the base checkout.
* `GET https://api.anthropic.com/v1/models` → **HTTP 401**,
  `authentication_error: x-api-key header is required`. The network path works;
  the credential does not exist.
* `GET /api/v1/ask/mode` reports `{"mode":"offline","configured":false,
  "live":false,"label":"GOVERNED LOCAL READER"}` — the product reports its own
  state honestly.
* `GET /api/v1/ask/posture` reports `{"primary":"deterministic",
  "analyst_available":false,"max_turns":5,"max_tool_calls":12,"tools":28}`.

No model ID was written into any configuration file. No smoke invocation could
be made. No model/effort/tool configuration is claimed to be verified. Any
statement in this branch about analyst-authored prose is therefore an
implementation-and-unit-test claim, never a live-provider claim.

## 5. Reproducible before state

Twelve questions spanning ECL movement and composition, scenarios, ratings and
fundamentals, covenants, collateral, definitions, macro dependencies and a
deliberately unavailable comparison quarter. Each recorded with HTTP status,
elapsed time, `narrative.direct_answer`, `interpretation`,
`interpretation_points`, `findings`, `caveats`, `scope`, the analyst path and
the analyst's stated reason.

Representative results — these are the actual strings returned:

| Question | What came back |
|---|---|
| *Give me an ECL decomposition and explain the impact of PD.* | "Over which horizon? Twelve-month and lifetime PD are different measures, and IFRS 9 uses each in different stages." — a clarification. No decomposition, no PD attribution. |
| *Show base, upturn, downturn and weighted ECL. Explain why the weighted result is where it is.* | "The 10 largest facilities by expected credit loss at Q2 2026." — a different question answered confidently. No scenario appears in the answer. |
| *Break the current ECL down by stage and sector.* | "CreditProbe cannot join ifrs9_staging to portfolio_facility: no active relationship connects them." |
| *Why did Construction's ECL rise this quarter?* | "CreditProbe could not find Construction in the published data." |
| *The total provision barely changed. What deteriorated and what improved underneath it?* | A single total movement — ECL 6,000 → 5,313 USD mn, Q2 2025 vs Q2 2026 — with no decomposition of what moved underneath it, plus a caveat that "improved underneath it" could not be applied. |

Median elapsed time across the twelve: **140 ms**; none reached a model,
because none could.

This is the state the rest of the branch is measured against.

## 6. Defect-to-test map (initial)

| ID | Defect | Test that will hold it |
|---|---|---|
| D1 | Analyst answer never becomes the visible prose | `tests/cockpit_v2/test_prose_source.py::test_analyst_answer_becomes_the_direct_answer` |
| D2 | No record of which path wrote the sentence | `…::test_prose_source_is_reported` |
| D3 | Interpretation call runs even when the analyst answered | `…::test_interpretation_is_not_called_when_the_analyst_answered` |
| D4 | Causal sentences suppressed by regex rather than evidenced | `tests/cockpit_v2/test_evidence_causal.py` |
| D5 | No movement decomposition | `tests/cockpit_v2/test_tools_movement.py` |
| D6 | No ratio decomposition | `tests/cockpit_v2/test_tools_ratio.py` |
| D7 | No metric history / z-score | `tests/cockpit_v2/test_tools_history.py` |
| D8 | No certified-analysis registry for the model | `tests/cockpit_v2/test_tools_registry.py` |
| D9 | **No ECL factor attribution at all** | `tests/cockpit_v2/test_ecl_oracle.py`, `tests/cockpit_v2/test_factor_attribution.py` |
| D10 | Flat investigation budget regardless of question class | `tests/cockpit_v2/test_budgets.py` |
| D11 | ECL/PD question returns a clarification instead of an answer | `tests/cockpit_v2/test_cockpit_answer.py` |
| D12 | Scenario question answered with a top-10 table | `tests/cockpit_v2/test_cockpit_answer.py::test_scenario_question_is_not_answered_with_a_ranking` |
| D13 | Stage × sector composition refused for want of a declared join | `tests/cockpit_v2/test_dataset_integrity.py::test_the_quarterly_package_needs_no_join_to_answer_stage_by_sector` |
| D14 | Cockpit can read unrelated domains | `tests/cockpit_v2/test_scope.py` |
