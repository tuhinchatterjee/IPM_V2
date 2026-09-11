# Early Warning V2 — conversational architecture completion

Branch `claude/early-warning-rebuild-v2-3lnttn`. Not merged to main.

Two things were incomplete. The stages were named after models that never ran,
and the analytical universe was 73 fields when the model has far more than 73
things to say. Both are now done, and this says exactly what was measured.

---

## 1. The model stages run models

### Where a stage may reach a model

`backend/early_warning/conversation/seam.py` is the one place, and it reuses
CreditProbe's existing provider infrastructure — `backend.llm.get_provider` for
the client, `backend.llm.roles` for which model serves which job. No key is read
there, no model id is named there, and no second provider stack exists.

| Stage | Family | Configured under | Env variable |
|---|---|---|---|
| `sonnet_pass_1` | Sonnet | `translation` | `AI_TRANSLATION_MODEL` → falls back to `AI_ROUTER_MODEL` |
| `sonnet_pass_2` | Sonnet | `router` | `AI_ROUTER_MODEL` |
| `opus_functionality_selection` | Opus | `complex_planner` | `AI_COMPLEX_PLANNER_MODEL` |
| `opus_analysis_plan` | Opus | `complex_planner` | `AI_COMPLEX_PLANNER_MODEL` |
| `opus_sufficiency_review` | Opus | `critic` | `AI_CRITIC_MODEL` |
| `opus_final_interpretation` | Opus | `analyst` | `AI_ANALYST_MODEL` |
| `sonnet_summary_update` | Sonnet | `router` | `AI_ROUTER_MODEL` |

One new line of configuration behaviour: `translation` now falls back to
`router` before falling back to `AI_MODEL`, so a deployment that configured a
Sonnet router and left the translation variable blank gets that model rather
than the shared default. `TRANSLATION` was previously declared and unused, so
nothing else changes.

`GET /early-warning/v2/models` resolves the table against the live
configuration and reports what each role actually holds.

### What each stage is held to

- **Its own structured packet in.** Never the data. The planner gets the grain
  package; the interpretation gets the result packet; nothing gets rows it did
  not ask a validated executor for.
- **Schema-validated output.** The provider makes the schema a tool contract;
  the seam validates the reply against the same schema again on the way back
  with `jsonschema`. A non-conforming reply is a fallback, not something to
  salvage.
- **The SAME ledger.** Seven stages, one budget. No per-stage allowance.
- **Real metadata.** Provider, model, role, effort, latency, input and output
  tokens and request id, taken off the call that happened.
- **Fallback that says why.** No provider, no budget left, a provider error, a
  malformed reply — each produces the deterministic result with the reason
  recorded and `engine` reading `deterministic`.

A call that was made and then failed is still **spent**. A ledger counting only
successes would make a provider that fails expensively look free.

### What a model is not allowed to do

The deterministic implementations are the floor the model is merged onto and
the safety layer that decides what it may change. **A model may tighten a
control and never loosen one.**

| It may | It may not |
|---|---|
| route a question OUT of Early Warning | route one INTO it against the gate |
| name a part of the request as uncovered | declare an uncovered part answered |
| improve the phrasing of the request | resolve an obligor, name an unpublished period, or invent a grouping field |
| write the reading | write a figure the result packet does not carry |
| propose one further bounded analysis | skip the validator, in either direction |

A plan naming another dataset is refused by the same validator that refuses a
deterministic one — the schema permits the value precisely so the refusal is
demonstrated rather than assumed — and the turn falls back to the deterministic
plan, which is then validated in its turn.

Prose carrying a figure the packet does not hold is **discarded**, not
annotated. `tests/early_warning/test_model_seam.py` plants one and asserts the
answer does not contain it.

### Test results — `tests/early_warning/test_model_seam.py`

**26 passed.** The six the brief required, and what else the seam needs:

| Requirement | Cases |
|---|---|
| live-provider path increments `model_calls` | `test_a_configured_provider_is_actually_called`, `test_every_stage_that_can_reach_a_model_does`, `test_each_call_records_what_actually_served_it` |
| correct model family per stage | `test_each_stage_is_served_by_the_family_the_architecture_names`, `test_the_ledger_counts_the_families_separately`, `test_the_routing_table_reports_the_configuration_it_resolves`, `test_an_undifferentiated_deployment_says_so_rather_than_claiming_routing` |
| deterministic fallback when provider unavailable | `test_with_no_provider_every_stage_falls_back_and_says_why`, `test_a_provider_error_costs_the_stage_and_not_the_turn`, `test_a_reply_that_does_not_conform_is_discarded`, `test_a_failed_stage_still_spends_the_call_it_made` |
| no stage may falsely claim `engine=model` | `test_no_stage_claims_a_model_without_a_call_behind_it` (four configurations), `test_a_stage_that_fell_back_never_appears_in_the_recorded_calls` |
| one global budget across all stages | `test_one_ledger_carries_every_stage`, `test_a_spent_budget_stops_the_calls_and_not_the_answer`, `test_deep_mode_raises_the_ceiling_and_nothing_else` |
| repair and sufficiency loops do not reset budgets | `test_a_refused_plan_does_not_give_the_calls_back`, `test_a_sufficiency_revision_spends_from_the_same_ledger` |

Plus the controls under a model: `test_a_model_may_not_open_the_gate`,
`test_a_model_plan_naming_another_dataset_is_refused_by_the_validator`,
`test_prose_carrying_a_figure_the_packet_does_not_hold_is_discarded`,
`test_the_model_never_resolves_an_obligor`,
`test_the_deterministic_answer_is_the_floor_not_a_stub`.

The provider is injected at `backend.llm.get_provider` — the same entry point
every stage reaches — so a passing test exercises the seam's own path rather
than one built for it. `tests/early_warning/stub_provider.py` is a real
`LLMProvider`: it returns `LLMResult` objects and answers each stage's schema
from that stage's own packet.

---

## 2. The analytical universe

### 2,521 fields, not 73

| Group | Fields |
|---|---|
| Customer | 8 |
| Core credit inputs | 7 |
| **Signal inventory — all 123** | **2,364** |
| Sub-categories — 22 nodes × score, band, worst signal, reason | 88 |
| Layer and dimension outputs, plus T&A and Classifier | 11 |
| Matrix, the five notches, overrides | 10 |
| Final Early Warning and dominance | 11 |
| Movement, including direction of travel | 8 |
| Workflow — governed escalation route and action | 14 |
| **Total** | **2,521** |

The dictionary and the wide view are an exact contract in both directions at
2,521 each way, asserted by
`tests/early_warning/test_signal_universe.py::test_the_dictionary_and_the_view_are_an_exact_contract`.

### All 123 signals, at customer-month grain

Confirmed: `test_every_signal_is_exposed_at_customer_month_grain` iterates the
inventory and asserts every column of every row is present.

Each of the **105 scored** signals carries 22 columns:

`status`, `fired`, `observed_value`, `baseline_value`, `normalised_value`,
`observed_unit`, `trigger_severity_band`, `trigger_score`, `magnitude_band`,
`velocity_band`, `persistence_band`, `repetition_band`, `corroboration_band`,
`accelerator_multiplier`, `decay_class`, `decay_factor`, `score`,
`reason_code`, `reason`, `source_system`, `evidence_age_days`, `freshness`.

Each of the **18** that are merged (10), dropped (5), replaced (2) or moved (1)
carries `status`, `status_detail` and `source_system`. They get nothing else on
purpose: a column for the accelerator bands of a dropped signal would be empty
for a reason nobody could recover from the data.

Columns are named `sig{num:03d}_{slug}_{measure}` — for example
`sig042_covenant_breach_event_score`. The inventory number keeps the name
unique and stable when the workbook rewords a signal.

### The reading behind a signal is now persisted

`scripts/build_early_warning_v2.py` was computing the raw value each trigger
saw and throwing it away. It now writes `observed_value`, `baseline_value`,
`normalised_value`, `observed_metric`, `observed_unit`, `reason_code` and
`reason` onto every signal observation, so "why is this signal at 80?" is
answered from the row rather than re-derived against a window that may since
have moved.

Scoring is untouched: the same 6,000 borrower-month rows and 4,767 signal
observations as before the change.

### Coverage is measured, not declared

| | |
|---|---|
| Fields | 2,521 |
| Fully populated | 1,049 |
| Partially populated | 293 |
| Empty | 1,179 |
| Inventory rows with a feed in this build | 49 of 123 |
| Signals that fired in the latest published month | 22 |

All 123 are exposed, not only the 49 this deployment feeds. A dictionary
listing only the fed ones would tell a planner the other seventy-four do not
exist, when what is true is that they exist and there is no feed yet. An unfed
signal's columns are **empty rather than zero** — a column of noughts would
report that every obligor scores zero on a signal nobody can see, which reads
as evidence of safety.

### Period coverage

Twenty contiguous published months, **2024-11 through 2026-06**, 300 obligors,
6,000 rows, one row per customer per month. The build still computes 32 months
and publishes the last 20, so the earliest published month is scored with a
full twelve-month trailing baseline.

### Sub-categories, roll-up and workflow

Each of the 22 nodes now carries its **band**, the **worst signal** behind it
for that obligor-month, and the **published reason text** for that node at that
band, alongside its score.

The roll-up carries T&A and Classifier scores and bands, all six
layer/dimension outputs, the anchor, the **matrix cell**, all five notches, the
net notch, the notch points, the override flags, types and **reasons**, the
final score and band, the dominant layer, sub-category and signal, the
**direction of travel**, and **`movement_is_notch_driven`** — true where the
score and the anchor moved in opposite directions, which is what stops a score
that fell while its anchor rose being read as a recovery. Eleven obligors in
the latest month are notch-driven.

The workflow group carries the escalation rung, owner role, notified roles,
exposure tier and both SLAs from the deterministic matrix, and the recommended
action, owner, timeframe, evidence-to-close, reversibility and cost ranks from
the governed action library.

### Discoverability at this size

A dictionary of 2,521 entries cannot go in a prompt whole, so the planner is
given the 157 fields that are not one signal's own column in full, the **signal
inventory** — 123 rows carrying each signal's column prefix — and the list of
measure suffixes. It composes the column it needs from a naming convention
rather than reading two thousand names looking for one.

Relevance selection was rebuilt against the expanded view and matches on the
signal's own name:

| Question | Top fields |
|---|---|
| "Which names have a covenant breach and why?" | `sig042_covenant_breach_event_fired`, `sig041_covenant_headroom_fired`, `sig042_covenant_breach_event_score`, `dominant_subcategory`, `l2_ta` … |
| "Show the obligors whose utilisation increase fired." | `sig008_utilisation_increase_fired`, `sig008_utilisation_increase_score`, `sig009_sustained_high_utilisation_fired`, `utilisation_pct` … |

Sample rows show only the signals that actually fired for that obligor —
roughly 180 columns rather than 2,521, because two thousand nulls teach a
planner nothing and cost the whole context window.

`GET /early-warning/v2/grain?group=<name>` narrows the dictionary to one group
and always reports the sizes of all of them.

The projection and the measured profile are cached per month. Building 2,521
columns per call turned a grain package into 13.8 seconds of arithmetic; it is
now 3.7 seconds cold and 0.13 seconds warm, and a full turn is 0.87 seconds.

### Test results — `tests/early_warning/test_signal_universe.py`

**22 passed**, covering the inventory count, the per-signal column sets for
both scored and retired rows, the exact dictionary contract, measured coverage
distinguishing fed from unfed signals, the sub-category detail, the complete
roll-up, the governed outputs reconciling to the escalation matrix, the
relevance ranking, and the bounded sample.

Two of them are the ones that matter most:
`test_a_fired_signal_matches_its_own_observation` checks the projected score,
trigger score, decay factor and reason code against the normalised observation
for every signal that fired — the wide view is a projection and must never be a
second computation — and `test_a_signal_with_no_feed_is_absent_rather_than_zero`
asserts the empty-not-zero rule.

---

## 3. What did not change

| | |
|---|---|
| Signals | 123 inventory, **105 scored**, 18 dropped / merged / replaced / moved |
| Classifiers | 23 |
| Sub-category nodes | 22 |
| Layer/dimension outputs | 6 |
| Notches | 5, at 8 points, capped ±2 |
| Published months | 20 contiguous, 2024-11 to 2026-06 |
| Obligors | 300, 6,000 customer-month rows |
| Methodology version | `ews-v2.1.0` |
| **Rawabi regression** | **anchor 72, notches −1/−1/0/0/0, final EWS 56 MEDIUM** ✓ |

The functionality routing gate, the six domain-lock controls, thread
continuity, the governed action library, the deterministic escalation matrix,
Messages, Investigations, the DOCX reports and the AI quality rubric all
continue to work unchanged.

---

## 4. End-to-end proof

`scripts/prove_early_warning_conversation.py` runs one owned question and one
question Early Warning does not own, and prints the stage trace, the model that
served each stage, the single ledger and what ran.

### Provider status in this container

**No vendor API key is configured here.** `ANTHROPIC_API_KEY` is unset, so
`get_provider()` returns the `NullProvider` and `provider_configured` is
`false`. No vendor call was made and none is reported. `api.anthropic.com` is
reachable from this container (it answers 401 without a key), so the only thing
missing is the credential.

Two traces below: the offline configuration this container actually has, and
the same run against the test double with the four models configured. The
second is labelled a stub in its own output — nothing here is presented as a
vendor call that did not happen.

### Trace A — no provider configured (this container)

```
  model calls       : 0 of 8
    sonnet          : 0
    opus            : 0

      0ms  request_started
      2ms  sonnet_pass_1                   engine=deterministic  [no AI provider is configured]
    392ms  sonnet_pass_2                   engine=deterministic  [no AI provider is configured]
   4056ms  ews_context_built
   4060ms  opus_functionality_selection    engine=deterministic  [no AI provider is configured]
   4065ms  opus_analysis_plan              engine=deterministic  [no AI provider is configured]
   4070ms  validation
   4740ms  execution
   4741ms  result_packet
   4742ms  opus_sufficiency_review         engine=deterministic  [no AI provider is configured]
   4742ms  opus_final_interpretation       engine=deterministic  [no AI provider is configured]
   4743ms  sonnet_summary_update           engine=deterministic  [no AI provider is configured]
   4743ms  thread_persisted
```

The answer is still produced, in full, from the deterministic path. That is the
supported offline configuration, not a degraded one.

### Trace B — a provider configured, four models routed

Run with `AI_ROUTER_MODEL=claude-sonnet-5`,
`AI_COMPLEX_PLANNER_MODEL=claude-opus-5`, `AI_CRITIC_MODEL=claude-opus-5`,
`AI_ANALYST_MODEL=claude-opus-5` against the stub provider.

```
STAGE ROUTING
  sonnet_pass_1                  sonnet  role=translation      model=claude-sonnet-5  served=sonnet
  sonnet_pass_2                  sonnet  role=router           model=claude-sonnet-5  served=sonnet
  opus_functionality_selection   opus    role=complex_planner  model=claude-opus-5    served=opus
  opus_analysis_plan             opus    role=complex_planner  model=claude-opus-5    served=opus
  opus_sufficiency_review        opus    role=critic           model=claude-opus-5    served=opus
  opus_final_interpretation      opus    role=analyst          model=claude-opus-5    served=opus
  sonnet_summary_update          sonnet  role=router           model=claude-sonnet-5  served=sonnet

"Why has Contracting deteriorated over six months, and is it concentrated in a
 handful of names?"

      0ms  request_started
     67ms  sonnet_pass_1                   engine=model  [claude-sonnet-5 role=translation]
    340ms  sonnet_pass_2                   engine=model  [claude-sonnet-5 role=router]
   4106ms  ews_context_built
   4111ms  opus_functionality_selection    engine=model  [claude-opus-5 role=complex_planner]
   4117ms  opus_analysis_plan              engine=model  [claude-opus-5 role=complex_planner]
   4123ms  validation
   4819ms  execution
   4819ms  result_packet
   4820ms  opus_sufficiency_review         engine=model  [claude-opus-5 role=critic]
   4823ms  opus_final_interpretation       engine=model  [claude-opus-5 role=analyst]
   4824ms  sonnet_summary_update           engine=model  [claude-sonnet-5 role=router]
   4824ms  thread_persisted

ONE LEDGER
  model calls       : 7 of 8      sonnet: 3      opus: 4
  executions        : 4     repairs: 0     revisions: 0
  recorded calls    : 7

DOMAIN
  domains planned   : ['early_warning']
  steps executed    : ['population', 'movement', 'concentration', 'diagnosis']
  figures           : 15 from the result packet

ANSWER
  Contracting is at 33.2 (low), 30 obligors and SAR 6.5bn, 11 at high or above.
  The weakness is concentrated rather than broad-based: 11 of 30 obligors sit
  at high or above and carry 81.3% of the high-risk exposure...
```

The stage order is exactly the one the architecture specifies. Model calls are
seven, not zero. Three are Sonnet and four are Opus, matching the routing
table. All seven spend from one ledger — recorded calls equals the ledger's
count. Every planned step named `early_warning`; every figure in the answer
came from the result packet.

### The What-If redirect

```
"What happens to ECL if oil falls 30%?"

      0ms  request_started
      0ms  sonnet_pass_1                   engine=model  [claude-sonnet-5]
     45ms  sonnet_pass_2                   engine=model  [claude-sonnet-5]
    215ms  ews_context_built
    215ms  opus_functionality_selection    engine=model  [claude-opus-5]
    216ms  redirect_answer_created
    216ms  sonnet_summary_update           engine=model  [claude-sonnet-5]
    216ms  thread_persisted

  selected          : what_if
  analytical stages : none — nothing was run
  model calls       : 4 of 8      sonnet: 3      opus: 1
  executions        : 0

  "That is a question for What-If Analysis, not for Early Warning."
  Alternatives offered, each checked against the live field dictionary first:
    Which obligors currently carry external-intelligence warning signals?
    Which sectors have the highest external-intelligence score?
    Which obligors' Early Warning score has risen most over twelve months?
    Which obligors in the affected sectors are at High or Very High?
    Show exposure by sector for obligors at High or Very High.
```

Opus selected What-If. No plan was created, no SQL or Python ran, nothing was
executed. The redirect names the owner, says why in terms of what the products
are FOR, and offers five questions this domain can actually answer.

### Reproducing it against a real provider

From the repository root, with the virtualenv the backend uses:

```bash
AI_PROVIDER=anthropic \
ANTHROPIC_API_KEY="sk-ant-..." \
AI_ROUTER_MODEL=claude-sonnet-5 \
AI_COMPLEX_PLANNER_MODEL=claude-opus-5 \
AI_CRITIC_MODEL=claude-opus-5 \
AI_ANALYST_MODEL=claude-opus-5 \
.venv/bin/python scripts/prove_early_warning_conversation.py
```

`AI_TRANSLATION_MODEL` is optional — pass one falls back to the router's model.
Add `--mode deep` for the wider ceilings, or `--json` to print the whole turn.

---

## 5. Regression results

Backend, `tests/early_warning/` + `tests/evals/test_early_warning_brain.py` +
`tests/api/`, with PostgreSQL running:

```
30 failed, 2439 passed, 66 skipped, 8 errors in 223.42s
```

| | |
|---|---|
| Passed | **2,439** |
| Non-passing identifiers | **38** (30 failed + 8 errors) |
| — Forward Risk Signal (Early Warning) | 5 — 2 failed, 3 errors, all pre-existing |
| — credit-book API fixtures | 33 — 28 failed, 5 errors, all pre-existing |
| Introduced by this work | **0** |

The five Early Warning failures are identical to the set captured in the
previous sweep before any of this work
(`test_forward_risk_signal.py`: `test_only_eligible_facilities_are_in_the_panel`,
`test_the_panel_pairs_this_quarters_factors_with_next_quarters_outcome`, and
three errors in the out-of-time backtest). The 33 API failures are the same
credit-book fixtures documented in the previous handoff and are untouched by
Early Warning.

Suites that matter here, run individually:

| Suite | Result |
|---|---|
| `test_rawabi_regression.py` | 1 passed — **56 MEDIUM** |
| `test_model_seam.py` | 26 passed |
| `test_opus_plan_contract.py` | 31 passed |
| `test_closing_reserve.py` | 17 passed |
| `test_executable_contract.py` | 41 passed |
| `test_output_allowances.py` | 23 passed |
| `test_grounding.py` | 32 passed |
| `test_execution_budget.py` | 20 passed |
| `test_signal_universe.py` | 22 passed |
| `test_conversation_routing.py` | 76 passed, 1 skipped |
| `test_conversation_pipeline.py` | 21 passed |
| `test_conversation_thread.py` | 13 passed |
| `test_data_domain.py` | 28 passed |

Routing: 32 ownership cases across all five functionalities, plus five
cross-domain requests refused by name, plus the injection case. Every case
where Early Warning loses also asserts that **no analytical stage was reached**.

Frontend: **405 of 405** passing across 41 suites. `tsc --noEmit` clean, lint
clean, `next build` clean.

### The whole backend suite, before and after the execution-budget fix

The container was rebuilt between sweeps and lost its analytical lake, so both
sides of this comparison were re-run on the same regenerated data — the numbers
are not comparable with the narrower sweep above, and the identifiers are what
matters.

```
before the execution-budget fix   22 failed, 10,282 passed, 25 skipped, 0 errors
after  the execution-budget fix   22 failed, 10,302 passed, 25 skipped, 0 errors
after  the progress experience    22 failed, 10,368 passed, 25 skipped, 0 errors
```

The failing identifiers are **identical, line for line** across all three — 22
each time, none of them in `tests/early_warning/`. The additional passes are
`test_execution_budget.py` (20), `test_turn_progress.py` (53) and
`test_ews_progress_api.py` (13).

Frontend after the progress work: **429 of 429** passing, `tsc --noEmit` clean,
`eslint src` clean, `next build` clean.

---

## 6. Live-proof remediation

The first real `claude-sonnet-5` / `claude-opus-5` run exposed two defects. The
What-If journey was correct and is unchanged. Both defects are fixed.

### Defect 1 — the Opus plan was discarded

`opus_analysis_plan` made a real call, got a plan back, and threw it away with
`the reply did not conform to the schema`.

The plan was fine. The JSON schema required `domain` and `rationale` on every
step and `output_grain` at the top. `domain` has exactly one legal value and
the prompt says so; `rationale` is for the audit trail; `output_grain` has a
sensible default. A model that saw no reason to repeat a constant on every step
had not written a bad plan — and requiring it cost the whole stage.

**The governed contract is untouched.** `Step`, `Plan` and
`conversation/validate.py` are unchanged, and they are what decides whether a
plan may run. What changed:

- The schema requires only what the document cannot exist without: `steps` at
  the top, `analysis` per step. Everything else keeps its description and its
  enum, and stays optional.
- Two normalising passes run **before** validation. `_coerce` is generic and
  schema-driven — it only ever moves a value into the type the schema already
  declares (`"25"` → `25`, one measure → a list of one, an explicit null for an
  optional field dropped). `planner.tidy` maps vocabulary into the enum the
  schema already contains (`trend` → `movement`, `top_n` → `ranking`,
  `portfolio` → `population_month`) and clamps `limit` to the 500-row bound.
  **Neither may add a value**, so a reply missing something required is still
  missing it and still falls back.
- An analysis this product does not have under any name is left exactly as it
  arrived, so the refusal names it: `'monte_carlo' is not one of ['population',
  …]`.
- A `domain` that is not this one is also left alone, so the **validator**
  refuses it by name. That path is asserted, not assumed.
- The plan stage's token allowance went from 2,000 to 4,000. Eight steps with
  filters, measures and rationales was landing on the boundary, and a tool call
  truncated at the boundary arrives as a partial document.
- A truncated tool call is now reported as truncation rather than as a
  malformed reply, and is not retried — it would be cut off again in exactly
  the same place. `backend/llm/anthropic_provider.py::_refuse_if_truncated`.
- A failed stage now records what came back: the schema errors AND the
  top-level keys the model returned.

`tests/early_warning/test_opus_plan_contract.py`: **31 passed.** Half are plans
a real model plausibly returns that must be accepted — the live shape, the same
plan without `domain`, without `rationale`, without `output_grain`, with
`"limit": "25"`, with a single measure instead of a list, with `filters` as a
list of field/value pairs, with a limit above the bound. Half are replies that
must still fall back — no steps, steps that are not a list, an empty document,
an analysis this product cannot run, a foreign domain, a provider error.

### Defect 2 — the answer lost the budget to the analysis

The trace ended:

```
opus_final_interpretation   deterministic
sonnet_summary_update       deterministic
this turn's model-call budget is spent (6 of 8)
```

Six of eight is not spent. Two calls remained and two stages needed one each.
What had run out was the **sixty-second clock** — and the message named the
wrong resource, so the obvious reading of the trace was wrong in a way nothing
on the trace could correct.

Three changes, none of them "more budget":

**A closing reserve.** Two model calls are held back for the final
interpretation and the rolling summary, and optional work may not touch them.
The ceiling is unchanged, every stage still spends from the same counters, and
a repair or revision costs exactly what it cost before — the reserve is an
ordering rule inside the one ledger, not a second allowance beside it. Standard
mode's arithmetic is why the ceiling is eight: five calls to the first
sufficiency review, six with the one permitted revision, eight with the closing
stages. A second revision would eat the reserve and is **declined** — the turn
returns the supported partial answer, says which part is missing, and still
writes it properly.

**Two clocks.** The soft deadline stops optional work; the hard deadline stops
everything; only the closing stages may run between them. Standard is now
120s soft / 240s hard, Deep 240s / 480s — bounded, and set against real Opus
latency rather than against the sub-second deterministic path the original 60s
was chosen for.

**Every refusal names its resource.** `Ledger.why_not()` returns the reason
rather than a bare `False`, and distinguishes the counter, the reserve and each
clock.

### The `6 charged / 5 recorded` discrepancy

Legitimate, and now explicit. A call that was made and then failed is real
spending: it is charged. It is not a stage a model served. Reporting only the
second made the first look like an error.

The ledger now records `model_calls_charged`, `model_calls_succeeded`,
`model_calls_failed` and `calls` — every attempt in order with its stage,
family, provider, model, role, duration, tokens, elapsed time and, where it
failed, why. `charged = succeeded + failed` holds by construction. The API
returns `model_attempts` alongside `model_calls`, and the proof script prints
both.

```
ONE LEDGER
  model calls       : 7 charged of 8  (2 reserved for the closing stages)
    succeeded       : 7
    failed          : 0
    sonnet / opus   : 3 / 4
  optional left     : 0
  elapsed           : 4.7s of 120s soft, 240s hard
  stages served     : 7

EVERY ATTEMPT (charged, in order)
     0.07s  ok    sonnet_pass_1                  sonnet  …/claude-sonnet-5   7ms
     0.36s  ok    sonnet_pass_2                  sonnet  …/claude-sonnet-5   7ms
     4.09s  ok    opus_functionality_selection   opus    …/claude-opus-5     7ms
     4.10s  ok    opus_analysis_plan             opus    …/claude-opus-5     7ms
     …
```

`tests/early_warning/test_closing_reserve.py`: **17 passed**, including the
exact misdiagnosis (the clock must not be reported as the call count), the
closing stages running past the soft deadline, the hard deadline still stopping
them, the revision being declined rather than the answer, the reserve not being
extra budget, and the ledger reconciling.

### Defect 3 — an unsupported grouping escaped validation

The second live run reached the real Opus planner and then crashed:

```
pipeline._analyse → execute.run(step) → facts.level(step.group_by, step.period)
KeyError: 'dominant_subcategory'
```

**What `dominant_subcategory` is.** A real field. It is on the borrower-month
row, in the wide view, in the dictionary, and it was advertised by the grain
package as one of the eleven groupings a planner might use. Opus did not invent
it, and it is a legitimate partition of the book — it is exactly what "which
sub-category is driving the high-risk population?" needs. So of the three
outcomes the brief names, this is the third: a legitimate derived grouping that
should be supported, and now is.

**What actually broke.** There were two registries. `grain.GROUPINGS` told the
planner what it could group by; `facts.LEVEL_FIELDS` decided what execution
would accept. They agreed on most entries and disagreed on four, and nothing
checked. That is not a missing string — it is what two sources of truth for one
capability always eventually produce.

`backend/early_warning/executable.py` is now the only one. `facts.LEVEL_FIELDS`
is built from it, the grain package advertises it, the validator checks against
it, and the planner is shown it. All **twelve** groupings execute, and a test
runs every one of them rather than checking that a name is in a list.

| | |
|---|---|
| Groupings, all executable | segment, sector, region, relationship manager, internal grade, IFRS 9 stage, Early Warning band, T&A band, Classifier band, dominant layer, **dominant sub-category**, utilisation band |
| Newly executable | `dominant_subcategory`, `ta_band`, `classifier_band` |
| Newly advertised | `utilisation_band` (it was executable and unadvertised) |

**Being described is not being executable.** The dictionary describes 2,521
columns; twelve are partitions of the book. Grouping by
`sig042_covenant_breach_event_score` gives three hundred groups of one, and so
does `customer_name`. Capability is now recorded per **role**, and the validator
checks `group_by`, every measure, every filter field and the sort field against
the rule for that role — plus the subject each analysis needs, so a borrower
step with no obligor is refused rather than failing in the executor.

**No rows are lost.** `dominant_subcategory` is empty for any obligor with no
fired signal — most of them in a quiet month — and a `groupby` drops null rows
silently. It is filled with `none`, and a test asserts every grouping accounts
for all 300 obligors.

**One governed alias map**, exact and curated: `grade` → `internal_rating`,
`stage` → `ifrs9_stage`, `sub_category` → `dominant_subcategory`, `ead` →
`exposure`. Role-aware, because "group by utilisation" means the band and "show
utilisation" means the percentage. **No fuzzy matching** — the substring rule
that used to sit in the planner matched `band` to whichever of `ews_band` and
`classifier_band` sorted first. An unknown name now comes through unchanged, so
the refusal names what the planner wrote.

**The repair packet** carries what the brief specifies —
`requested_grouping`, `status: unsupported`, `allowed_groupings`,
`relevant_available_fields` — and goes back to Opus as a new
`opus_plan_repair` stage under the `critic` role, spending from the same
ledger. Once: a second failed correction is repaired deterministically, which
terminates.

**Nothing raw escapes.** Every failure leaves the executor as an
`ExecutionError` with a code and what the domain offers instead; the turn has an
outer boundary that turns anything unexpected into a stated limitation with the
thread persisted. `facts.level` raises a named `UnsupportedLevel` (still a
`KeyError` subclass, so nothing that caught one stops catching it) whose message
lists the twelve.

`tests/early_warning/test_executable_contract.py`: **41 passed** — the exact
live question through every stage, the crashing grouping validating and running,
the one-registry invariant, every grouping executed and reconciled to 300
obligors, role-separated validation, the alias map, the repair packet shape, and
seven adversarial plans (a nonexistent grouping, an aliased real field, a
nonexistent measure, a valid field that is the wrong type for grouping, a
measure used as a partition, a source-domain field not materialised here, and an
aliased measure) each normalised or repaired before execution.

### Defect 4 — the answer was cut off by CreditProbe's own output caps

The third live run reached every stage on real models and then wrote its
answer deterministically anyway:

```
opus_sufficiency_review     claude-opus-5   cut off at the 1000-token limit
opus_final_interpretation   claude-opus-5   cut off at the 1600-token limit
```

Both replies were well formed. Both were thrown away.

**Why the caps were wrong.** They were sized for the document. On Opus 5
adaptive thinking is on by default and its tokens come out of the **same**
`max_tokens` allowance, so a two-hundred-token sufficiency verdict can be cut
off at a thousand. A ceiling has to cover the document *and* the reasoning that
produces it.

Two halves, and the first matters more than the second.

**The documents are compact.** `uncovered` was free text, so a model wrote a
sentence about each missing part; it is now an enum over the eight analysis
labels, because which parts are missing is a choice from a closed set. The
lists on both schemas are bounded (`maxItems`), and both prompts now say
plainly not to restate the request or repeat figures back.

The input packets stopped duplicating the evidence. The sufficiency stage was
receiving every figure the packet held and the coverage map's whole dictionary
— including the proposed next step and the model-call metadata, neither of
which it reads; it now gets the *names* of the figures produced, because the
question is which parts were measured rather than what they measured.
The interpretation stage was receiving `figures` **and** `fact_packs` — the
packs are where the figures come from, so every number arrived twice and the
rows a third time. The packs are gone; the rows are capped at ten.

**Then the two ceilings, and only those two.**

| Stage | Was | Now |
|---|---|---|
| `opus_sufficiency_review` | 1,000 | **2,000** |
| `opus_final_interpretation` | 1,600 | **3,000** |
| every other stage | — | unchanged |

Both stages truncated at their previous caps, which bounds the true size from
below and says nothing about it from above — so these are the smallest values
that are *safe* on the evidence available, at the top of the range the brief
gave. The documents are meanwhile smaller than they were when they did not fit.

**One thing the new bounds caught in testing.** A `maxItems` of 3 rejected a
four-item list outright, which is the same papercut as refusing a plan for
writing `"25"` instead of `25`. The generic coercion now **trims a list to its
bound** rather than discarding the reply. Prose length stayed guidance in the
prompt rather than a hard `maxLength`: a cap on a paragraph cannot be enforced
by trimming without cutting mid-word, and discarding a good reading for being
forty characters long is the failure this whole fix is about.

**Truncation detection is unchanged and still explicit.** A tool call cut off
at the limit raises a named "cut off at the N-token limit" error, is never
reported as malformed JSON, and is never retried — it would be cut off again in
exactly the same place. It costs one charged call, and the closing reserve
still carries the answer.

`tests/early_warning/test_output_allowances.py`: **23 passed** — the two
allowances asserted at both ends, no other stage raised, a full verdict and a
full grounded reading both accepted, the packets proved not to duplicate the
evidence, list-trimming, truncation still detected and not retried, one
truncation costing one call with both closing stages still on a model, the
budget architecture untouched, and both live acceptance targets.

### Defect 5 — a successful Opus reading was discarded by the grounding guard

The fourth live run made seven Anthropic calls, all successful, and still wrote
its answer deterministically:

```
Discarding an Early Warning reading:
figures ['-06,', '1,049', '1,218', '2,521'] are not in the result packet.
```

The guard was **right to reject the prose** and wrong about two of the four.

**Where the numbers came from.** `1,049` and `2,521` are the field dictionary's
coverage summary — 2,521 fields described, 1,049 fully populated — which the
interpretation packet was carrying as `coverage`, and `1,218` is arithmetic on
them. Those are statistics about the SCHEMA, not about the book. A credit
paragraph quoting them says nothing true about any obligor, so discarding the
reading was correct; the defect is that the writer could see them at all.

`-06,` was never a figure. It was `2026-06,` read by a numeral scanner whose
pattern took the hyphen for a minus sign and swallowed the trailing comma — so
a reading that quoted its own period correctly was thrown out for citing minus
six.

**The rule underneath.** The guard checks prose against what the writer was
allowed to SEE, which makes the packet the control. The packet now carries
evidence and nothing else, and the allowance is **derived from the citable
sections of that packet** — so the two agree by construction rather than by a
whitelist somebody has to remember to update.

| The writer sees | The writer does not see |
|---|---|
| the question and the normalised request | field-inventory counts |
| the scope, the filters, the periods | dictionary coverage and missingness |
| the executed figures and up to ten rows | the grain package's statistics |
| the provenance and the runtime's caveats | anything held for planning only |
| the governed actions and the escalation route | |
| the sufficiency verdict, and the deterministic reading as the baseline | |

Planning keeps all of it — `packet.coverage`, the grain package and the API's
`result_packet` are untouched, and a test asserts that. This is about the last
stage only.

**Nothing was whitelisted.** `1,049`, `1,218` and `2,521` are not analytical
figures, are no longer visible to the writer, and a test proves they would
still be rejected in prose if they ever reappeared.

**The parser.** A `YYYY-MM` period is matched and set aside as one token before
any numeral scanning; a figure can no longer begin after a hyphen that follows
a digit, nor end on a separator. `2026-06` is a month, `1,049` is one figure and
`-3.2` is still a negative one. A period is a permitted non-analytical
reference — and checked: a month nobody published is refused like any other
invented figure.

**Structured grounding, added.** A reading may return `fact_refs`, naming the
result fields its figures came from. A ref that resolves to nothing is recorded
on the trace and is not fatal — a mistyped field name on a reading whose every
figure IS in the packet is a bookkeeping slip, not an invented number — and
naming a field does not make a number true: an invented figure with a ref
attached is still discarded. The numeric check remains the one that rejects.

**No second model call.** One interpretation call, grounded or not; a repair
pass would spend an Opus call out of the closing reserve. The ledger is
unchanged at 7 charged.

`tests/early_warning/test_grounding.py`: **32 passed** — the packet-is-evidence
invariant (no section reaches the writer that is not citable), every numeral the
writer can see being one it may cite, the coverage summary gone from the packet
and still present for planning, the parser on periods and separators, an
unpublished month refused, invented figures still rejected, the schema
statistics still rejected, `fact_refs` resolving and not rescuing, and both
acceptance targets.

### Defect 6 — the execution budget was consumed before execution

The fifth live run reached `validation` with every model stage served by a real
model and an Opus plan of six analyses — population, movement, diagnosis,
grouping, concentration, ranking. Standard allows six executions. The turn then
emitted:

```
stopped_honestly   this turn's executions budget is spent (6 of 6)
model calls : 5 charged
executions  : 6
```

No `execution` stage. No `result_packet`. No answer. Six executions charged and
nothing to show for them — a ledger describing a turn that did not happen.

**Where the counter moves.** Exactly one place, and it always did: immediately
before `execute.run` is called, in the pipeline. There is no pre-charge during
validation, no reservation function writing to the same field, no second
accountant between validator and executor, and no `>=`/`>` off-by-one — the
ceiling comparison was and is correct. A test now pins that: `.execution()`
appears in one file in `backend/`.

**What was actually wrong.** Two things, neither of them the ceiling.

*The exhaustion escaped the loop.* `ledger.execution()` was called unguarded at
the top of each iteration; `_spend` raises `Exhausted`; the handler that caught
it returned `stopped_honestly` — discarding six completed analyses in order to
report that the next one was one too many. A ceiling is meant to stop the step
it cannot afford, not the turn. The loop now asks `why_not("executions")`
**before** charging and before the executor: the step it cannot afford is
declined, named on a new `execution_declined` event, and the turn carries on to
its packet, its review and its answer with what ran. The sufficiency review
names the part it could not cover, as it does for any other uncovered analysis.

*The retry ran inline.* The per-step correction added with the executable
registry re-ran a corrected step immediately, spending the execution a LATER
planned step was going to need. One failing step could therefore starve a step
that would have succeeded, and a six-step plan under a six-execution ceiling
could stop at five. Corrections are now deferred: every planned step reaches the
executor once before any correction reaches it twice, and a correction runs only
on what is left.

**The invariant.** `executions` counts governed analytical executions
**attempted** — one increment per call to the executor, charged as the call is
made, never for a step that was merely planned, validated or queued. A valid
six-step plan under a six-execution ceiling runs exactly six; the seventh is
refused before it runs. Zero executed steps cannot report six.

Charged on attempt rather than on success, for the reason model calls are: an
execution that ran and failed cost what one that ran and worked cost. So
`executions_succeeded` and `executions_failed` are recorded beside it rather
than inferred from it, and every attempt is settled onto a `steps` list naming
the analysis, the outcome, the rows and whether it was a correction. The
`execution` event carries the same four numbers, so **the trace and the ledger
reconstruct the same turn** and a test compares them from both ends.

**The ceiling was not raised.** Standard is still six executions, Deep still
fourteen. The fix is sequencing.

| Case | Ceiling | Planned | Executed | Refused |
|---|---|---|---|---|
| Five steps | 6 | 5 | 5 | — |
| Six steps | 6 | 6 | 6 | — |
| Seven steps | 6 | 7 | 6 | the seventh, before it ran |
| Validation only | 6 | 6 | 0 | — |
| What-If redirect | 6 | 0 | 0 | — |

A revision still spends the same counter on the same ledger, and now settles
onto it too, so a revision's execution is visible beside the plan's rather than
folded into an untraceable total. A repair still buys no fresh allowance.

`tests/early_warning/test_execution_budget.py`: **20 passed** — the single
charging site, charge-on-attempt, `charged = succeeded + failed`, the five/six/
seven-step cases, the refusal naming its resource, the declined analysis absent
from the packet rather than empty in it, validation costing nothing, a turn that
never reached the executor reporting zero, a refused plan costing nothing to
refuse, a failed step charged but not counted as a success, a correction not
starving a later planned step, revision and repair accounting on one ledger, the
live Contracting question reaching every closing stage, seven model stages
served by a model at 7 charged / 7 succeeded / 0 failed, and the ceilings
unchanged.

### The agentic chat experience — watching a turn happen

Not a defect. The reasoning was right and invisible: an Early Warning turn takes
fifteen to sixty seconds against a real provider, and the screen showed a grey
skeleton for all of it. A grey rectangle is indistinguishable from a hang.

**Nothing in the reasoning architecture changed.** Two Sonnet passes, the
context build, the Opus ownership gate, the Opus plan, governed validation and
execution, the Opus sufficiency review, the Opus interpretation, the Sonnet
summary — same stages, same families, same budgets, same ceilings, same
grounding, same repair semantics. The panel observes that pipeline.

**What the reader now sees.** Each stage as it begins and as it finishes, with
its own measured duration; the governed analyses filling in one by one
underneath "Running Early Warning analysis"; a live clock; then one collapsed
line that reopens into the full history, with a Details table.

```
✓ Understanding your question                          2.0s
✓ Resolving scope and intent                           2.1s
✓ Loading Early Warning evidence                       4.1s
✓ Checking the right CreditProbe functionality         2.0s
✓ Planning the investigation                           0.0s
✓ Validating the analysis                              0.0s
✓ Running Early Warning analysis                       4.6s
    ✓ Establishing the Contracting portfolio position
    ✓ Checking movement over the selected period
    ⓘ Testing concentration in high-risk obligors
    ⓘ Diagnosing the main drivers
ⓘ Additional drill-down deferred
✓ Checking evidence and completeness                   2.0s
✓ Preparing risk interpretation                        2.0s
ⓘ Using governed Early Warning reader
✓ Updating conversation context
✓ Analysis complete

✓ Analysed in 18.7s · 2 analyses · governed Early Warning reader ·
  evidence checked · some limitations remain · additional drill-down deferred
```

**Two rules govern it.** Nothing is invented — every visible step comes from a
real pipeline event, and `progress.build` is a pure function of the event list
rather than a state machine with a clock. And nothing is model engineering: no
stage name, family, provider, token count, schema error or budget counter
reaches the reader. A test reads every sentence the panel can say, looking for
exactly those words.

**Two instrumentation events were added**, and they decide nothing, gate
nothing and spend nothing. `stage_started` names the user-facing step a stage is
about to work on — without it the panel is blank for the first seconds of every
turn, because every other event fires when a stage FINISHES. `execution_step`
reports each governed analysis as it lands, because `execution` is emitted after
the whole loop and would be one line that sits still for twenty seconds.

Guessing the next stage from the one that just finished was considered and
rejected. It is a prediction, and where the pipeline branches the guess puts a
step on screen that never runs.

**Reuse.** The Cockpit's `Pulse`, `usePrefersReducedMotion`, polling cadence,
pure-contract-plus-component split and live-region discipline are shared, in
`components/agentic/steps.ts` and `components/agentic/step-progress.tsx`.
Early Warning supplies only the endpoint and the turn key. What was deliberately
NOT copied is `pending.tsx`, which advances its stage on a timer — fabricated
progress, which this brief forbids.

**A latent bug found on the way.** `--color-pulse` was declared in a plain
`:root` rather than in the `@theme` block, so Tailwind never generated
`bg-pulse` or `text-pulse` and every mark asking for the activity colour was
painted transparent. The Cockpit's working indicator had the same problem. The
token now sits in `@theme`, and both products' marks paint the theme's positive
tone.

| What | Where |
|---|---|
| Governed labels, event→step mapping, the document | `backend/early_warning/conversation/progress.py` |
| The in-flight registry | `backend/early_warning/conversation/live.py` |
| `POST /ask/progress`, `GET /ask/vocabulary` | `backend/api/routers/early_warning_v2.py` |
| Shared contract | `frontend/src/components/agentic/steps.ts` |
| Shared panel | `frontend/src/components/agentic/step-progress.tsx` |
| Early Warning's polling hook | `frontend/src/components/early-warning/ews-progress.tsx` |

`tests/early_warning/test_turn_progress.py`: **53 passed**.
`tests/api/test_ews_progress_api.py`: **13 passed**, including a turn polled
from a second thread while it runs, which is the only way to prove the panel
fills in rather than arriving complete.
`frontend/src/components/agentic/__tests__/steps.test.ts`: 24 behavioural cases
inside the suite's **429 passed**.

### What was NOT changed

The What-If journey, the functionality gate, the domain locks, the 20-month
domain, the 2,521-field universe, the 123/105/18 reconciliation, the scoring
engine, Rawabi at 56 MEDIUM, the Sonnet/Opus assignments, the eight-call model
budget, the two-call closing reserve, the execution ceilings, the stage output
allowances, the numeric grounding guard, the action and escalation workflow,
Messages, Investigations, the reports and the thread semantics.

The conversational architecture is unchanged by the progress work: the same
stages in the same order, served by the same model families, spending the same
budgets. No model call was added, and no label is generated by a model.

---

## 7. What a reviewer should look at first

1. `backend/early_warning/conversation/seam.py` — the single model boundary and
   the fallback contract.
2. `backend/early_warning/conversation/select.py` — the asymmetric rule that a
   model may close the gate and never open it.
3. `backend/early_warning/conversation/reading.py` — the figure grounding, and
   what happens to prose that fails it.
4. `backend/early_warning/signal_fields.py` — the 123-row projection, generated
   from the workbook's own catalogue so a column and its definition cannot
   drift apart.
5. `tests/early_warning/test_model_seam.py` — the invariant that no stage can
   claim a model without a call behind it.
