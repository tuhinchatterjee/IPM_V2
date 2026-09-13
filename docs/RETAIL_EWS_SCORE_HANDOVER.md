# Retail Early Warning Score — final handover

*Synthetic Saudi retail demonstration data throughout. Nothing in this build is
ANB customer data, an ANB model, an ANB policy or a SAMA requirement, and
nothing here has been approved or independently validated by anybody. The
bureau block is a labelled synthetic proxy, not a live bureau feed.*

Branch: `claude/funny-dirac-6n8f0o`. Baseline: `f547bce`, preserved and
refactored, not restarted. The requirement-by-requirement delta against that
baseline is `docs/RETAIL_EWS_DELTA.md`; this document is what the delta became.

---

## 1. Build identity

| | |
|---|---|
| Model | Retail Early Warning Score, version `2.0.0` |
| Panel | `retail_ews_score`, version `2.0.0` |
| Rulebook carried forward | `retail-ews-rulebook-1.0.0` — its 19 risk rules survive as triggers |
| Source book | `retail_facility_month`, 546 columns, 25 months |
| Model configuration | `backend/retail/ews_model.py` — one file, no thresholds in the frontend |
| Derivation | `backend/retail/ews_score.py` |
| Serving | `backend/retail/ews_views.py`, `backend/retail/ews_chat.py` |
| Screens | `frontend/src/app/early-warning/*`, plus the Customer 360 tab |

## 2. The data

| | |
|---|---|
| Domain | `retail_ews_score`, business domain **Early Warning Score** in Data Builder |
| Months | Exactly **20**: 2025-01 … 2026-08 |
| Rows | **362,316** |
| Fields | **483** |
| Grain | One row per customer per facility per month-end |
| Reconciliation | Same customers, same facilities, same exposure as the canonical book. The domain adds no borrower and no riyal the book does not hold. |

Three fields the field contract names are **declared absent with a reason**
rather than fabricated:

- `partial_payments` — the book records missed and returned payments, not
  part-payments.
- `balance_build` — a top-up is written here as a new facility, so an
  amortising balance never grows; the largest one-month rise across twenty
  months is one per cent, which is interest accrual.
- `repeat_restructure` — the book carries a restructure date and flag, not a
  lifetime count.

## 3. The model

Four layers. Within each, sub-layers; within each sub-layer, **classifiers**
(context, always read) and **triggers** (conditions that fire). Every dynamic
trigger that fires is scored on six **action dimensions**.

| Layer | Weight | Kind | Sub-layers | Classifiers | Triggers |
|---|---|---|---|---|---|
| Behavioural Intelligence | 0.40 | dynamic | 4 | 10 | 14 |
| Affordability & Cash Flow Intelligence | 0.30 | dynamic | 5 | 7 | 9 |
| Bureau & External Credit Intelligence | 0.15 | **classifier** | 5 | 8 | 5 |
| Facility & Exposure Intelligence | 0.15 | dynamic | 5 | 11 | 6 |
| **Total** | **1.00** | | **19** | **36** | **34** (31 evaluated) |

Action dimensions and their weights: direction 0.20, magnitude 0.20,
velocity 0.10, momentum 0.15, persistence 0.25, recency 0.10.

### Central configuration

| | |
|---|---|
| Scale | 0 – 100, **higher is worse**; 0 is a customer with nothing firing |
| Warning cutoff | **20** |
| Customer bands | CRITICAL ≥ 70, HIGH ≥ 45, MEDIUM ≥ 20, LOW ≥ 0 |
| Population bands | CRITICAL ≥ 30, HIGH ≥ 22, MEDIUM ≥ 15, LOW ≥ 0 |
| Severity points | CRITICAL 85, HIGH 60, MEDIUM 35, LOW 12 |
| One trigger's cap | 90 of 100 into its sub-layer |
| Roll-up | Noisy-OR: `100 × (1 − Π(1 − wᵢsᵢ/100))`, monotone and bounded |

Six overrides floor the score regardless of the arithmetic:

| Override | Floor | Why |
|---|---|---|
| `high_trigger_floor` | 20 | A 15%-weighted layer cannot carry a lone trigger past 15, so a high-severity signal there would never reach the review line |
| `critical_trigger_floor` | 45 | The same arithmetic, one band up |
| `forbearance_arrears` | 70 | A concession was granted and the customer fell behind anyway |
| `stage_3` | 80 | Credit-impaired under the bank's own impairment policy |
| `default_entry` | 80 | The event the system exists to anticipate has happened |
| `dpd_90` | 85 | At ninety days the deterioration has already happened |

### Product configuration

| Product | Behavioural | Affordability | Bureau | Facility |
|---|---|---|---|---|
| Credit Card | 0.45 | 0.22 | 0.13 | 0.20 |
| Personal Finance | 0.40 | 0.35 | 0.15 | 0.10 |
| Auto Finance | 0.36 | 0.28 | 0.14 | 0.22 |
| Home Finance | 0.30 | 0.36 | 0.14 | 0.20 |

Twelve sub-products, each with its derivation written down in the model
metadata rather than in frontend code: Silver / Privilege / Platinum / Ultra
Card; New / Buyout / Top-up Personal Finance; New / Used Auto Finance; First
Home / Refinance / Second Property.

### The bureau, honestly

The book stamps a bureau date on every month-end, which would let a monthly
bureau trend be drawn that no bank actually receives. It is not drawn. Instead
a governed pull schedule is applied — at origination, on a per-customer cadence
of 6 / 9 / 12 / 18 months, and on a delinquency pull at 30 days past due — and
between pulls the last observed values are **carried forward unchanged** with
their date and age. At 2026-08, 2,783 of 19,745 facilities carry a new
observation; recency runs 0 to 17 months, median 3. Bureau triggers are gated
on a new observation: no observation, no bureau trigger. The customer screen
shows last observed score, band, observation date, recency and whether this
month is a new pull, and says in words why there is no monthly line.

## 4. The book at 2026-08

| | |
|---|---|
| Customers | 14,251 |
| Facilities | 19,745 |
| Exposure | SAR 2,082.9 mn |
| Under warning | 3,377 customers, SAR 506.1 mn (24.3% of exposure) |
| High or Critical | 1,908 |
| Already bad | 391 |
| Forward risk, still performing | 1,517 |
| Portfolio score | 17.51, MEDIUM |
| Default-entry rate | 0.24% (47 of 19,589 eligible) |

| Product | Score | Band | Customers | Warned | Bad | Forward risk | Exposure |
|---|---|---|---|---|---|---|---|
| Credit Card | 17.13 | MEDIUM | 5,853 | 1,343 | 175 | 335 | SAR 58.1 mn |
| Personal Finance | 16.05 | MEDIUM | 6,781 | 1,416 | 143 | 851 | SAR 463.2 mn |
| Auto Finance | 15.55 | MEDIUM | 3,117 | 745 | 55 | 318 | SAR 231.2 mn |
| Home Finance | 14.00 | LOW | 2,067 | 389 | 31 | 248 | SAR 1,330.4 mn |

Credit Card sub-products: Silver 17.60, Privilege 16.77, Platinum 16.46,
Ultra 16.04. Facilities and exposure partition the product exactly; customer
counts do not, because 135 customers hold cards in two tiers, and the screen
says so rather than showing a total that fails to add up.

## 5. The screens

One left-hand item, **Early Warning Score**, opening a workspace with five
levels — total retail, product, sub-product, customer list, customer — all
URL-addressed, with Back retaining the level and its filters. The chat sits at
the top of every level. Signals is a view inside the workspace, not the
landing screen.

Screenshots are in `docs/evidence/retail_ews_score/cases/`:

| Deliverable | File |
|---|---|
| Retail Early Warning landing | `EW-01-landing.png` |
| Credit Card product | `EW-11-product.png` |
| Credit Card sub-product | `EW-16-sub-product.png` |
| Customer list, three mini charts per card | `EW-20-customers.png` |
| Customer 360 Early Warning section | `EW-34-customer-360.png` |
| View Model, main tree | `EW-41-model.png` |
| Behavioural layer expanded | `EW-44-behavioural-layer.png` |
| Bureau layer expanded, classifier and recency treatment | `EW-48-bureau.png`, with the written treatment at `EW-48-bureau-treatment.png` |
| Early Warning Score domain in Data Builder | `EW-51-data-builder.png` |
| Signals / rules view | `EW-33-signals-view.png`, and where a rule lands: `EW-33-signals-filter.png` |
| The chat, and a refused cross-domain question | `EW-18-chat.png`, `EW-60-out-of-scope.png` |
| The customer's own Early Warning page | `EW-34-customer.png` |

## 6. The chat

`POST /retail/ews/ask` reads the Early Warning Score domain and the model
configuration, and nothing else. It has no catalogue, no planner and no
second data source — a structural check on its imports is part of the suite
(EW-58), not a promise. A question belonging to another module is refused by
name: expected credit loss, stress scenarios, scorecard diagnostics, capital,
and corporate vocabulary each come back with a scope notice naming the module
that owns it (EW-60).

Known-good questions: which product is deteriorating fastest; which sub-product
is worst; how many customers are under warning; show the currently bad
customers; show forward risk but still performing; what is driving Credit Card;
the top five signals for Privilege Card; how many customers are at DPD 0; what
exposure is under warning; what is the default-entry rate; and anything about a
named customer id, answered from that customer.

## 7. Validation

| Suite | Result |
|---|---|
| `scripts/retail_uat/ews_score_uat.py` — EW-01 … EW-60, real browser | **60 of 60 passed** (`docs/evidence/retail_ews_score/ew_score_uat.txt`, `ew_score_uat.json`) |
| `tests/retail/test_ret_ews_score.py` — 61 model, arithmetic, domain, bureau, view and chat regressions | 61 passed |
| `tests/retail/test_ret_ews_dynamic.py` — source-variable mutation proof | 2 passed |
| `tests/retail/test_ret_ews_wiring.py` — routes, runtime catalogue, readiness, restart script | 15 passed |
| `scripts/retail_uat/fresh_install_check.py` — isolated database, migrations, accounts, bootstrap, application | 12 of 12 |
| `tests/retail` — the whole retail suite | 1,407 collected, **1,402 passed, 5 failed**, 0 skipped. All five failures are in `test_ret_adversarial_cockpit.py` and pre-date this work (`docs/evidence/retail_ews_score/retail_suite.txt`) |
| `npm test` — frontend units | 577 passed |
| `npm run typecheck` | clean |
| `npm run lint` | clean except two pre-existing errors in What-If, untouched by this pass |

### The screen is not a painting

`tests/retail/test_ret_ews_dynamic.py` copies the lake to a disposable
directory, changes one source variable on one customer, rescores, and asserts
the change travels the whole chain: source → trigger → sub-layer → layer →
overall score → severity → reason codes → product aggregate, with every other
facility in the book unmoved so the change is attributable. It writes
`docs/evidence/retail_ews_score/mutation.json`, which the browser suite reads
(EW-59) so that no run can claim the UI is dynamic without that having
happened.

## 7a. Page load, measured in the browser

Time from navigation to the screen being readable, best of three, Chromium
1194 at 1512×982 through `scripts/retail_uat/driver.py`
(`docs/evidence/retail_ews_score/page_load.json`).

| Screen | Before | After |
|---|---|---|
| Early Warning landing | `/retail/ews/portfolio` alone took **12.8 s**, and the browser never reached network idle inside 30 s | **1.46 s** |
| Product (Credit Card) | `/retail/ews/product/CREDIT_CARD` alone took 10.0 s | **1.47 s** |
| Sub-product (Privilege Card) | — | **1.03 s** |
| Customer list | — | **4.06 s** |
| Customer detail | — | **3.55 s** |
| View Model | — | **4.07 s** |

The API is no longer the cost anywhere: portfolio and product answer in 0.01 s,
the customer list in 0.36 s, a customer in 0.27 s and the model in 0.36 s. What
remains on the last three screens is client-side rendering under the Next
**development** server — unminified, double-rendered under React strict mode,
with hot-reload instrumentation attached. A production build is not part of
this pass and these figures should not be read as production numbers.

## 8. Defects found and fixed in this pass

Found by reproducing on the running application, root-caused, fixed, and each
one now held by a named regression test.

1. **A serious signal read LOW.** A weighted mean put one HIGH trigger at 10 of
   100. Rescaled by the heaviest weight.
2. **Ceiling pile-up.** The rescale overshot and 126 customers sat pinned at
   exactly 100 with no ordering between them. Replaced with a noisy-OR roll-up.
3. **One trigger reached 100.** A lone early-life payment failure carried a
   customer to the top of the scale. Severity points lowered to 85/60/35/12 and
   any one trigger capped at 90 into its sub-layer.
4. **Column collision.** The behavioural *layer* score overwrote the book's
   behavioural *scorecard* score, so customer cards showed 91.89 where the
   scorecard says 526.35. Layer and sub-layer columns are now prefixed.
5. **List and detail disagreed.** The list read layer scores off the
   worst-overall facility; the customer page took the worst per layer.
   RC-0025457 read bureau 0.0 in one and 42.4 in the other. Both now take the
   worst per layer.
6. **Every product read CRITICAL.** The population score averaged only warned
   customers, so all four products came out between 49 and 65. It is now
   exposure-weighted across everyone, and the population bands are set to that
   scale.
7. **Already-bad undercounted by one.** The cohort flag was read from the
   worst-scoring facility; a customer can be thirty days down on another one.
   Aggregated with `any` across the customer's facilities.
8. **A key used twice.** `external_obligations` named both a bureau classifier
   and an affordability trigger, so their columns collided. The classifier is
   renamed, and `M.check()` now refuses this class of collision outright.
9. **A 15%-weighted layer could not raise a warning.** A new external
   delinquency — a high-severity bureau trigger — scored 13 against a cutoff of
   20 and could never appear on a warning list, because 0.15 × 100 is 15. Two
   severity floors were added. Nine facilities in the book were affected.
10. **The landing screen took thirteen seconds.** The portfolio view recounted
    every customer across seven months and four products on every request, and
    sorted a 483-column frame to do it. The worst facility is now taken by
    index rather than by sorting, the per-customer frame is built once per
    count instead of twice, series and whole answers are held against the
    immutable panel, and the API warms the landing figures on a daemon thread
    at startup. Cold 13 s → 0.01 s warm, with the same figures.
11. **The chat lost its answer.** Applying a filter pushed a URL that remounted
    the route and discarded the answer the reader had just asked for. No-op
    pushes are skipped, the filter no longer carries the month, and the
    conversation is held outside the component.
12. **Cosmetic, found by looking at the screen.** Customer 360 carried a back
    link to the retired "Early Warning Signals" route, and the embedded Early
    Warning section offered to open Customer 360 while already inside it.

## 8a. The fresh-install wiring defect, and what closed it

Reported from a Mac running this branch: the bootstrap said ready, the twenty
partitions were on disk, `metadata/retail/catalog.json` held the domain, Data
Builder was synced — and `/openapi.json` carried no `/retail/ews/*` route at
all, the runtime `data_catalog` held one dataset instead of five, and the
screen read "The Early Warning Score domain could not be read."

**Root cause 1 — the restart script could not stop anything on a Mac.**
`scripts/retail_uat/restart_backend.sh` decided whether a backend was running
by testing `/proc/$PID`. macOS has no `/proc`, so the test was always false:
the old server was never stopped, the new one could not bind the port and
exited, and the health check that followed was answered by the old server. The
script printed "backend ready" naming a pid that no longer existed, and the
machine went on serving whatever code it had booted with — which predated the
Early Warning Score. It now uses `kill -0` and `ps`, stops anything of ours
holding the port, refuses to start when the port stays busy, and reports ready
only if the process IT started is the one alive. Its pid file is per port.

**Root cause 2 — the governed catalogue was read once per process, forever.**
`get_catalog()` was `lru_cache(maxsize=1)`. The bootstrap registers the domain
by writing the catalogue file, and on a fresh install it runs while a backend
is already up, so the running server kept serving a catalogue from before the
domain existed. The cache is now keyed on that file's identity and size, so a
catalogue written by another process is picked up; `reload_catalog()` still
exists for datasets published through Data Builder, which change no file.

**Root cause 3 — readiness never asked the application anything.** Every check
was about files. `backend/retail/readiness.py` now builds the production app
through its own factory, requires all ten Early Warning routes in its OpenAPI
document, signs in and calls the endpoints, checks the twenty months and the
model, panel and rulebook versions, checks the RUNTIME catalogue rather than
the file — and, when something is listening on `API_PORT`, asks that server
the same questions, which is what catches a stale process.

Why the existing acceptance missed all three: every test drove the API over
HTTP after `restart_backend.sh`, and on Linux that script works, so the server
was always current and the catalogue always fresh. Nothing compared the code
on disk with the code being served. A fourth trap sat underneath: an
application's paths cannot be enumerated by walking `app.routes` in this
FastAPI — an included router is one wrapper object with no path of its own, so
such a check reports that an app serving 619 paths serves none. The checks
read the OpenAPI document instead, which is what a person inspects.

Closed by `tests/retail/test_ret_ews_wiring.py` (15 gates, including one that
stands a healthy server with no Early Warning routes in front of readiness and
requires a refusal) and by `scripts/retail_uat/fresh_install_check.py`, which
walks an isolated database, the migrations, the accounts, the bootstrap and
the application end to end: 12 of 12
(`docs/evidence/retail_ews_score/fresh_install_check.txt`).

### On a Mac

```
cd /path/to/IPM_V2
git fetch origin && git checkout claude/funny-dirac-6n8f0o && git pull
set -a && source .env.retail && set +a
.venv/bin/python scripts/bootstrap_retail_installation.py
bash scripts/retail_uat/restart_backend.sh
.venv/bin/python scripts/bootstrap_retail_installation.py --check
```

The bootstrap first, then the restart, then the check — and the check now
fails rather than passing if the server in front of it is serving older code.

## 9. Limitations

- Every figure is synthetic demonstration data. The bureau block is a proxy
  built to a governed pull schedule, not a bureau feed.
- The thresholds are demonstration thresholds, chosen so the four products and
  twelve sub-products separate on this book. They are bank-configurable and are
  not calibrated against observed default outcomes.
- The score is not a probability of default and is not mapped to one.
- Three declared fields are never evaluated, for the reasons in §2. They are
  visible as absent in View Model rather than silently missing.
- Two lint errors remain in the What-If module. They pre-date this pass, are
  outside the Early Warning scope, and were left alone deliberately.
