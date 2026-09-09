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
30 failed, 2343 passed, 66 skipped, 8 errors in 369.51s
```

| | |
|---|---|
| Passed | **2,343** |
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

### What was NOT changed

The What-If journey, the functionality gate, the domain locks, the 20-month
domain, the 2,521-field universe, the 123/105/18 reconciliation, the scoring
engine, Rawabi at 56 MEDIUM, the action and escalation workflow, Messages,
Investigations, the reports and the thread semantics.

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
