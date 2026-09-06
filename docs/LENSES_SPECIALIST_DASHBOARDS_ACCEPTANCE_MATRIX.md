# Lenses 2.1 — Acceptance Matrix

**Branch** `claude/lenses-specialist-dashboards-esd591` · **Base**
`origin/claude/integration-rehearsal` @ `4f79566` · **Migration head** `0041`
(unchanged)

Every row says what was actually verified and how. A row marked **Not built**
is not a row that was quietly dropped — it says what exists instead and why.

---

## A. Branch and baseline

| Check | Evidence | Result |
|---|---|---|
| Branched from a verified integrated baseline | `origin/claude/integration-rehearsal` contains main + 131 commits including Lenses 2.0, Playbook, Scorecard Validation and the rehearsal fixes | PASS |
| Not branched from the active Planner branch | `origin/claude/project-planner-copilot` untouched | PASS |
| Local and remote equal | `git rev-parse HEAD == origin/claude/lenses-specialist-dashboards-esd591` | PASS |
| Clean tree | `git status --porcelain` empty at each commit | PASS |
| Migration head unchanged | `0041`; no file added to `alembic/versions/` | PASS |
| No merge to main, no force push, no rebase, no PR | Only fast-forward pushes to the designated branch | PASS |

---

## B. Preconfigured lenses (§3–§6)

| Lens | Sections | Figures | Charts | Renders | Evidence |
|---|---:|---:|---:|---|---|
| CRO Portfolio | hand-built narrative | — | — | PASS | Preserved as-is; `CRO_LENS` records why it is not a tile grid |
| Retail Credit Risk | 8 | 23 | 7 | PASS | Journey J; `test_the_retail_lens_renders_and_its_arrears_buckets_nest` |
| Retail Analytics | 6 | 9 | 11 | PASS | Journey J; `test_the_retail_analytics_lens_renders` |
| Corporate IFRS 9 | 7 | 34 | 9 | PASS | Journey A and J; five reconciliation tests |

| Check | Evidence | Result |
|---|---|---|
| Every tile names a metric that exists | `lenses.check()` == `[]`, run by a test | PASS |
| Every chart's dimension is one the dataset offers | `check()` calls `metrics.dimension_fields` | PASS |
| Every chart type is honest over its dimension | `check()` calls `metrics.chart_types_for` | PASS |
| No tile fails or renders empty on any shipped lens | Journey J across all three | PASS |
| Stage exposures sum to total exposure | `test_the_three_stage_exposures_sum_to_the_total` | PASS |
| Stage shares account for the whole book | `test_the_stage_shares_account_for_the_whole_book` | PASS |
| Coverage is the provision over the exposure | `test_coverage_is_the_provision_over_the_exposure` | PASS |
| A chart reconciles with the tile above it | `test_a_chart_agrees_with_the_tile_it_sits_under` — exposure by sector sums to total exposure | PASS |
| Arrears buckets nest (30+ ≥ 60+ ≥ 90+) | Reconciliation and lens tests | PASS |
| No unrelated metric leaks into a specialist lens | Each lens declares its domains; behavioural scorecard statistics moved to Retail Credit Risk, next to the book they read | PASS |
| Each lens says what it cannot show, and why | `test_a_lens_says_what_it_cannot_show`; Journey J asserts the reasons are on screen | PASS |

### §4 Retail Risk coverage

| Asked for | Status |
|---|---|
| Retail exposure, accounts, average balance, utilisation | Present |
| 1+/30+/60+/90+ DPD, delinquent exposure, default rate, NPL rate | Present (count and balance for each bucket; NPL rate is an alias of default rate) |
| Roll rates | **Not built** — a movement between two consecutive months; the engine computes one period at a time. Repeat Delinquency Rate is the nearest honest measurement and is on the lens |
| Cure rates | Present as Cure Rate (3-Month Look-Back), read from the trailing window on the account's row. A month-on-month cure rate remains unsupported and says so |
| IFRS 9 staging / ECL for retail | **Not available** — no retail impairment dataset in this deployment; the lens says so |
| Gini/AUROC, KS, calibration | Present |
| PSI | **Not available** — needs a reference distribution; the scorecard validation module reports it against each model's declared reference window |
| Bad rate by score band | Present as a chart: default rate by bureau score band |
| Approval rate by score band, override rate | **Not available** — the application dataset records no accept/decline decision |
| New originations, customers | Origination volume is on Retail Analytics, which is where an origination question belongs; the behavioural dataset carries no customer id |

### §5 Retail Analytics coverage

| Asked for | Status |
|---|---|
| Portfolio mix by product, channel, segment | Present as three charts |
| Mix by geography | **Not available** — no geography field on either retail dataset |
| Mix by vintage | Present (vintage delinquency chart) |
| Mix by risk band, balance band | Present via the bureau score band chart; no balance band field exists |
| Applications, average ticket, requested amount | Present |
| Approvals, declines, approval rate, booking rate | **Not available** — no decision field |
| Score distribution, origination risk mix | Present as bad rate by score band and by segment |
| Utilisation, payment behaviour, delinquency | Present |
| Vintage bad rate, delinquency by vintage | Present |
| Cohort curves, default emergence, score migration | **Not built** — each needs a period-over-period series per cohort, which the single-period metric engine does not carry |

### §6 Corporate IFRS 9 coverage

| Asked for | Status |
|---|---|
| Stage 1/2/3 exposure, total exposure | Present |
| Stage 1/2/3 ECL, total ECL, coverage | Present, plus per-stage coverage |
| PD, LGD, EAD | Exposure-weighted PD and LGD present; EAD is the exposure measure itself. PD drift since origination added |
| Stage 1→2, 2→1, 2→3, new defaults, cures | **All five present, new in this branch**, as amounts, plus three rates over the correct base |
| Scenarios: base / upside / downside ECL, weights, sensitivity | **Not available** — the staging dataset carries one already-weighted ECL rather than one per scenario. Scenario definitions exist separately; they cannot be joined to an ECL that was never split |
| Overlay amount, overlay % of ECL, movement | Amount and share present; movement is part of the bridge below |
| ECL movement bridge (opening → closing) | **Not built** — a two-period decomposition with an attribution rule. The stage migration band covers the one leg the staging dataset can answer alone |

---

## C. Every metric explains itself (§7)

| Field §7 asks for | Where it comes from | Result |
|---|---|---|
| Name, business definition, formula, unit | `MetricDefinition.panel()` | PASS |
| Numerator, denominator, component terms | `formula.to_dict()` — the tree, term by term | PASS |
| Data domain, dataset, grain, source fields | `panel()` with the catalogue | PASS |
| Filters, period rule, transformation, exclusions | Declared per metric | PASS |
| Calculation version, verification status, origin | `version`, `status_label`, `origin_label` | PASS |
| Data as-of / last calculated | `period_used` on every tile; `calculation.period` | PASS |
| What it is NOT | `not_this`, written for every metric where a reader would reasonably assume otherwise | PASS |
| Chart: measures, dimension, aggregation, type, period, filters | `_render_chart` lineage block, including the SQL and run id | PASS |
| The panel travels with the tile, not fetched on open | `_render_metric` embeds it | PASS |
| Verified on screen, not only in the payload | Journey B: 13 checks; Journey J: "a tile explains itself on screen" for all three lenses | PASS |

---

## D. Creating a lens (§8–§12)

| Check | Evidence | Result |
|---|---|---|
| The flow opens by asking what to call it | Journey L | PASS |
| Naming it opens a short definition panel, not a metric list | Journey L | PASS |
| The panel asks purpose, audience, portfolio, domains, period, comparison, visibility — and not twenty questions | Journey L asserts all seven fields | PASS |
| Suggested values, user-controlled | `POST /lenses/suggest`; every value lands in an editable field | PASS |
| Suggestions are deterministic, not model-generated | `service.suggest` uses the same search as the typeahead; asserted by test | PASS |
| A name echoing a shipped lens is told it already exists | `suggest` returns `shipped`; the screen says so | PASS |
| The catalogue is never dumped into a dropdown | Journey L asserts it; `search("")` returns nothing by design | PASS |
| Typeahead: `del` suggests, `delinq 30` narrows | Journey L asserts the second list is no longer; `test_delinq_30_returns_only_thirty_day_metrics` | PASS |
| Ranking: canonical name, aliases, prefix, token, fuzzy | Five tiers, tested per tier | PASS |
| Ranking uses selected domain and portfolio | **New in this branch** — `DOMAIN_BOOST`, six tests | PASS |
| A suggestion shows definition, formula and unit before it is added | Journey L asserts the formula is on screen | PASS |
| Available periods and permitted chart types in the suggestion row | **Not built** — periods would turn a keystroke into eight lake reads; chart types depend on a dimension no chart has chosen. Both are on the metric's own panel, one click away | Stated |
| Governed data domains shown, not table names | `GET /lenses/vocabulary` | PASS |
| Only periods that exist are offered | `GET /lenses/{id}/periods`; Journey K asserts the picker matches the API exactly | PASS |
| Single period / multiple periods / rolling windows | Single period selection built. Multi-period selection is the chart's `compare` and the over-time dimension; an explicit range/rolling picker is **not built** | Partial |

---

## E. Custom metrics and verification (§11, §14–§16)

Carried forward from Lenses 2.0 and re-verified on this HEAD; not rebuilt.

| Check | Evidence | Result |
|---|---|---|
| Builder: name, description, scope, unit, format, metric type | Journey G | PASS |
| Metric kinds (direct, count, distinct, sum, average, weighted, ratio, percentage, rate, change, growth, difference, function) | `formula.KINDS` | PASS |
| Numerator and denominator as separate multi-term sections | `Side` with a combining operation; Journey G | PASS |
| Every term exposes dataset, field, filter, aggregation | `Term.to_dict()` | PASS |
| No `eval`, no model-authored SQL | The formula is a tree; it compiles to the existing IR and is validated against the catalogue | PASS |
| Verification runs against real stored data and shows every step | Journey G asserts the saved metric computes the number it previewed | PASS |
| A disagreement is recorded and confers nothing | Journey E | PASS |
| A user metric is labelled as user-built and draft until verified | Journey G | PASS |
| Nested derived terms, weighting inside the builder | **Not built** | Stated |
| Natural-language transformation → editable deterministic plan (§13) | **Not built** — the safe IR exists and is used; the translation step is not | Stated |
| "I expect a different result" → CreditProbe identifies likely differences (§16) | **Not built** — the disagreement is recorded; it is not explained | Stated |

---

## F. Charts and layout (§17–§18)

| Check | Evidence | Result |
|---|---|---|
| Metric, dimension, grouping, period, filters, sort, aggregation, comparison, type, title, preview, save | Journey I, end to end | PASS |
| Only chart types the renderer can draw are offered | `bar` and `line`; a line over an unordered dimension is refused with the reason | PASS |
| The nine other types in §17 are not offered | Deliberate — offering one the renderer cannot draw is the defect this branch removed | Stated |
| Every bar reproduces from the parquet independently | Journey I | PASS |
| Add, remove, reorder, resize through the existing grid | Journey H | PASS |
| A rearrangement is a version and can be put back | Journey H | PASS |
| Bands survive a change that removes a tile | `test_sections_survive_a_change_that_removes_a_tile` | PASS |
| A metric shown twice keeps both bands | **Fixed in this branch** — identity queue in `resection` | PASS |

---

## G. AI Lens Copilot (§19)

| Check | Evidence | Result |
|---|---|---|
| "Add 30+ DPD Exposure Rate" adds the governed metric | Journey C and `POST /lenses/{id}/ask` | PASS |
| A request the deployment cannot satisfy is refused with the reason | Journey D | PASS |
| Formulas are never invented; only catalogue definitions are used | `propose` resolves against the catalogue only | PASS |
| "How is this calculated?" / "show me the numerator" | The info panel carries the tree, term by term, with values | PASS |
| Conversational remove and reorder | `ask` + `resection` | PASS |
| "Build me a Retail Collections Lens" as a one-shot build | **Removed deliberately** — replaced by `/lenses/new`, which asks the same matcher one thing at a time and shows what it understood before storing | Stated |

---

## H. Permissions (§20)

| Check | Evidence | Result |
|---|---|---|
| The general Cockpit still cannot read a restricted scorecard dataset | `test_the_general_cockpit_still_cannot_read_what_a_lens_reads` | PASS |
| The batched path is scoped exactly like the single path | `test_the_batched_path_is_scoped_exactly_like_the_single_one` | PASS |
| `GOVERNED_METRIC` is still the only extra scope | `test_governed_metric_is_still_the_only_extra_scope` | PASS |
| An unauthorised dataset is absent from autocomplete | `test_the_typeahead_never_suggests_one` | PASS |
| A direct metric id cannot bypass the filter | `test_asking_for_it_by_id_does_not_get_round_that` | PASS |
| The refusal does not reveal whether the metric exists | `test_the_refusal_does_not_say_whether_the_metric_exists` | PASS |
| A batch does not compute a metric the asker may not read | `test_a_batch_does_not_compute_a_metric_the_asker_may_not_read` | PASS |
| A lens tile over a dataset that has gone reports the absence | `test_a_lens_tile_over_a_missing_dataset_says_so_rather_than_guessing` | PASS |
| Every shipped lens reads only datasets this deployment has | `test_every_shipped_lens_reads_only_datasets_this_deployment_has` | PASS |
| Scorecard validation domain isolation unchanged | `tests/scorecard/test_domain_isolation.py` passes unmodified | PASS |
| Per-user dataset permission revocation | **No such model in this deployment.** `readable` exists at the service level and only the Playbook supplies it; access is by role gate and domain scope. Stated in the report rather than implied | Stated |

---

## I. Performance (§21)

| Check | Before | After | Evidence |
|---|---:|---:|---|
| Corporate IFRS 9: scans of the staging dataset | 34 | **1** | `test_a_lens_worth_of_metrics_costs_one_read` |
| Corporate IFRS 9: 43 panels rendered | 1.83s | **0.54s** | Measured on this HEAD |
| Retail Credit Risk: 30 panels | 2.03s | 1.23s | Measured |
| Retail Analytics: 20 panels | 1.28s | 0.97s | Measured |
| Two datasets cost two reads, not one and not many | — | 2 | `test_metrics_on_two_datasets_are_two_reads_not_one_and_not_many` |
| Period resolved once per source, not per tile | — | — | `test_every_tile_on_a_lens_lands_on_the_same_period` |
| An aggregate wanted by nine metrics is written once | — | — | `test_an_aggregate_wanted_twice_is_written_once` |
| Batched figures equal individually-run ones | — | 34 of 34 | `test_values_and_value_agree_metric_for_metric` |
| No cache outlives the render | The memo is per-render; nothing is stored | By construction; documented in `render` | PASS |

---

## J. Browser acceptance (§22)

Real Chromium, real backend on `:8000`, real frontend on `:3000`, real
PostgreSQL, `REQUIRE_LOGIN=true`, signed in as `priya.raman`.

**164 checks passed, 0 failed.**

| Journey | What it proves | Result |
|---|---|---|
| A | A shipped lens shows real figures that reconcile with each other | PASS |
| B | A tile explains itself: formula, terms, fields, period, governance | PASS |
| C | Finding a metric by typing what you call it | PASS |
| D | A request the deployment cannot satisfy is refused with the reason | PASS |
| E | Checking a figure against your own number, including disagreement | PASS |
| F | What the lens deliberately does not show, on screen | PASS |
| G | Building a metric and getting the right number for it | PASS |
| H | Arranging a lens by hand as a version like any other | PASS |
| I | Building a chart end to end, including why types are refused | PASS |
| J | Every shipped lens read as a client would read it | PASS |
| **K** | **Changing the period; figures still reconcile after they move** | PASS |
| **L** | **Creating a lens by being asked; typeahead narrows** | PASS |

Journey mapping to the brief: A/B/J cover Journey A (Retail Risk) and C
(Corporate IFRS 9); K covers Journey B (change period, coherent updates); L
covers Journey D (create lens); G covers Journey E (custom metric); I covers
Journey F (custom chart); H covers Journey G (layout).

---

## K. Static checks

| Check | Result |
|---|---|
| `ruff check backend tests scripts` | All checks passed |
| `npm run typecheck` (`tsc --noEmit`) | clean |
| `npm run lint` (eslint) | clean |
| `npm run build` (next build) | Compiled successfully |
| Migrations | none added; head `0041` |

---

## Verdict

**READY FOR INTEGRATION REHEARSAL.**

Not merged. No pull request. No force push, no rebase, no merge to main.
