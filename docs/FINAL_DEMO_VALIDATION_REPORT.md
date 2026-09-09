# CreditProbe — final demo validation

**Integration branch** `claude/creditprobe-integration-plan-vyq22h`
**Not merged to `main`. No pull request opened.**

Everything below was run, not reasoned about. Where a figure appears it is what
a command printed; where something was not verified it says so in those words
rather than being folded into a number that looks better.

---

## 1. Source checkpoints integrated

| Branch | Commit | Merged at |
|---|---|---|
| `claude/lenses-live-intelligence-v3-jnlrep` | `c0b66d0` | M1 — carries the whole chain: playbook-committee, scorecard-validation, lenses-specialist, and the three integration-rehearsal fixes |
| `claude/what-if-analysis-rebuild` | `80e74a4` | M2 — the canonical data foundation: `backend/ifrs9/policy.py`, `backend/corporate/ratingscale.py` (19+D) |
| `claude/project-planner-copilot` | `e84bc68` | M3 |
| `claude/cockpit-agentic-v3-fhg4r0` | `275284c` | M4 |
| `claude/early-warning-rebuild-v2-3lnttn` | `7711270` | M5 |
| `claude/creditprobe-playbook-plan-ky3m05` | `713f99a` | M6 |

`origin/main` `3855f9b` is the baseline. 323 commits ahead of it.

---

## 2. The two blockers this pass was called to close

### Cockpit canonical data — CLOSED

The previous report said the Cockpit was still answering over *"its own book —
its own identifiers, INR in crore, twenty quarters"*. It no longer is.

**`corporate_ifrs9_facility`** is new: the canonical IFRS 9 book at facility
grain. `build_ifrs9` stages at obligor grain deliberately and that ruling
stands — this re-decides nothing. It is an exact decomposition, and the three
facts that make it exact were measured rather than assumed:

| | |
|---|---|
| Facility EAD already sums to obligor EAD | largest gap over the whole book **1.8e-12** |
| Stage, SICR, PD and LGD are obligor properties | carried unchanged; that IS obligor-level staging |
| ECL is linear in EAD | `ecl / (pd x lgd x ead)` constant to five decimal places within a stage |

Allocation uses the largest-remainder method. Rounding each facility
independently left 6,323 of 52,989 borrower-quarters one unit in the last place
adrift — not a modelling error, but a reconciliation that does not tie. It ties
now: **zero breaks at a tolerance of 1e-9**, asserted before publication.

**`canonical-16q-v1`** is the Cockpit's release and its default. Same relations,
same 700-column contract, same architecture — the agentic runtime, tool
registry, sandbox, prompts, ledger, audit trail and every screen are untouched.
Twelve gates run before it publishes and all twelve pass:

```
+ every borrower id is canonical (CORP-)          + reported in SAR millions
+ every facility id is canonical (CFAC-)          + every canonical borrower is present
+ no identifier from the retired book survives    + every canonical facility is present
+ exactly the 16 canonical quarters carry rows    + portfolio EAD reconciles, every quarter
+ no quarter outside the canonical window         + portfolio ECL reconciles, every quarter
+ stage takes only canonical values 1, 2 and 3    + rating ordinals sit on the 19+D masterscale
```

3,800 borrowers, 12,773 facilities, 156,397 facility-quarter rows, SAR in
millions, Q3 2022 – Q2 2026. On screen the badge reads `release
canonical-16q-v1 · quarters 20 (4 empty)`.

Twenty slots, sixteen populated. The four slots before the canonical window are
created and left **empty** rather than back-filled, using the Calendar's own
mechanism for exactly this.

**One feature is disabled rather than faked.** `cockpit_ifrs9_detail` — the
per-scenario, per-horizon term structure behind an ECL — has no canonical
source. The canonical book measures ECL as a scenario-weighted single-period
product; the Cockpit's private book measured it as a discounted term structure,
and its own integrity gate
(`check_a_single_pd_lgd_ead_product_does_not_reproduce_ecl`) exists to prove the
difference. Inventing a term structure under a canonical ECL would fabricate the
very thing that gate polices. So the manifest carries
`carries_term_structure: false`, the relation is absent, and that feature is
**post-demo**. One feature, named, not a module left on conflicting data.

`demo-20q-v1` still builds and can be pinned by name — the Cockpit's own unit
tests and evals were authored against it — and is documented as **not**
canonical Corporate.

### What-If → Playbook — CLOSED

`fromWhatIfResult` builds the payload from `WhatIfRunResult`, the shape the
thread actually holds. The button sits in the action bar that appears once a
result exists.

A What-If result is a **comparison**, and that governs the payload: every amount
goes out as a labelled pair (baseline, scenario, change), the narrative says
which is which in words, the scenario definition travels with it, and the
limitation that it is conditional is first in the list and not removable. The
attribution bridge is carried whole, residual included.

Proven over HTTP: `POST /playbook/exports` → **201**, the item appears in the
library, `what_if` joins `implemented_modules`, and opening the revision shows
source module, revision, reporting period, content hash, scope, tables, the
limitation and the link back. Proven in the browser: the library lists it.

---

## 3. Module status

| Module | Status | Evidence |
|---|---|---|
| **Cockpit** | Working, canonical | Renders with SAR mn figures over Q2 2026; catalogue answers `canonical-16q-v1`, SAR millions, 16 quarters; a question either answers or refuses honestly |
| **Early Warning V2** | Working | Portfolio score 8.36 over 300 borrowers; 5 segments drill down; methodology published; Word report downloads and opens |
| **What-If** | Working | 19-grade masterscale in exact order; 13 scenarios, 12 carrying a shock; one-notch downgrade moves ECL **49,563 → 67,604** and the stated movement reconciles exactly; Delta executes in 0.7s |
| **Lenses** | Working | 9 lenses installed; a lens opens with its definition |
| **Playbook** | Working, both halves | 3 seeded workspaces; export library with all five modules; committee half answers; one route tree, zero path collisions |
| **Project Planner** | Working | Seeded delivery plan opens with its workstreams and tasks |
| **Scorecard Validation** | Working | All three scorecards offered; 48 governed tests published |
| **Borrower 360** | Working | A canonical borrower is found by id |
| **Data Builder** | Working | 84 governed datasets registered, including the three Early Warning ones and `corporate_ifrs9_facility` |
| **Investigations** | Renders, navigable | Opens, renders content, controls live, survives refresh |
| **Analysis Studio** | Renders, navigable | Same |
| **Messages / Workflow** | Renders | Reachable from the shell; counts answer |

---

## 3a. Browser acceptance — PASS

`scripts/acceptance/demo_integration_journeys.py`, real Chromium, real sign-in,
real cookie session.

```
PASS   16 journeys, 80 checks, 80 passed, 0 failed, in 255s
       13 screenshots, in docs/demo_screenshots/
```

The previous report recorded browser acceptance as NOT VERIFIED because the
wide sweep failed on itself — *"Execution context was destroyed, most likely
because of a navigation"* — evaluating script against a page that had navigated
away, which is what this build's three client-side redirects do. Every rule that
failure taught is enforced in the new suite: `settle()` waits for the URL to
stop moving before anything is read; a redirect is asserted by where it lands
rather than survived; locators are roles and ids, never classes; refresh is a
step; and the browser is resolved to the one the image actually has, rather than
downloading a second to satisfy a version number.

Covered: sign-in and session-survives-refresh · Cockpit · Early Warning ·
What-If · Lenses · Playbook · Project Planner · Scorecard Validation ·
Borrower 360 · Data Builder · Investigations · Analysis Studio · the
exported-analysis library with the What-If item in it · all three retired routes
redirecting · browser Back · a cold deep link.

### Control audit — 0 dead

| | |
|---|---|
| Controls wired | **412** |
| Dead controls | **0** |
| Skipped (destructive by name, or not clickable) | 212 |

Links are judged by whether their href resolves to a route this application
serves; buttons are pressed, and one is dead when pressing it changes nothing a
user could see — no navigation, no dialog, no change in rendered text. The
shell's own navigation is audited once rather than eleven times, because
auditing it eleven times is eleven copies of one fact.

Per screen: `/` 30 · `/early-warning` 4 · `/what-if` 10 · `/lenses` 14 ·
`/playbook` 10 · `/projects` 4 · `/scorecard-validation` 5 · `/borrower-360` 2 ·
`/data-builder` 26 · `/investigations` 2 · `/studio` 305.

### Functional depth — PASS

`scripts/acceptance/demo_functionality.py`. **54 checks, 54 passed.** A route
returning 200 proves a page exists; these ask whether the thing works.

| | |
|---|---|
| What-If, one-notch corporate downgrade | ECL **49,563 → 67,604**, stated movement reconciles to the two figures exactly, over 3,241 borrowers, in 0.7s |
| Masterscale | 19 grades in the exact order AAA … C |
| Early Warning | portfolio score 8.36, 300 borrowers, 5 segments, methodology published |
| Cockpit | `canonical-16q-v1`, SAR millions, 16 populated quarters; a question answers or refuses honestly |
| Playbook | 3 workspaces, 31 exports across 5 modules; a What-If export opens with its provenance, its conditional limitation and its link back |
| Download | Early Warning portfolio report, 130,444 bytes, opens as a real Word document |
| Health | every deterministic component ok; `ai_provider` states its own configuration rather than faking it |

### Auth and session — PASS

Sign in · move between four modules · a long analytical call · the session
survives it · export a workbook · reopen a saved object · sign out · sign back
in. No false "backend did not answer" at any point, and after sign-out the
product says it is signed out rather than rendering an empty screen that reads
as "nothing to show".

**One observation, recorded rather than asserted away.** Signed out, all seven
portfolio-data endpoints refuse with 401 — Playbook, Planner, Scorecard
Validation, Cockpit, Borrower 360, Early Warning, What-If. Two endpoints remain
readable without a session: `/lenses` and `/data-builder/datasets`. Both are
metadata — lens names and descriptions, and the governed dataset catalogue with
its field names — and neither carries a borrower, a facility or a figure. That
is a design decision rather than a defect, and it is written here so it is a
known property rather than a discovery. A check demanding 401 everywhere would
have failed on the decision instead of on a defect.

### Cross-module canonical identity — 16 tests, all passing

`tests/proof/test_cross_module_canonical_identity.py` samples borrowers across
all three IFRS 9 stages plus the largest exposure — not the top of a sorted
list — and proves Cockpit, Early Warning, What-If and Borrower 360 describe the
same rows: same borrower ids, same facility ids, and agreement on stage, SICR,
default flag, DPD, PD, LGD, EAD and ECL, with the facility book summing back to
the obligor book.

---

## 4. Defects found and fixed during this validation

Each of these was found by running something, not by reading code.

| # | What | How it was found |
|---|---|---|
| 1 | **Blank screen.** Every `/_next/static/*` 404ed and the body was zero characters. Two stale servers — a `next-server` from an earlier `next start` holding port 3000 and serving a previous build's asset map, and a `uvicorn` from before the Cockpit repoint holding 8000 and reporting the old release. **Both answered 200 to a health check the whole time**, which is exactly why route health is not evidence | the new browser suite, on its first run |
| 2 | **Three Early Warning datasets existed on disk and nowhere else.** The build writes Parquet and never touches `metadata/catalog.json`; Data Builder listed 80 governed datasets and none of them Early Warning's. The readiness check asked "do the files exist?" rather than "can the product see them?" | the functionality suite |
| 3 | **`corporate_ifrs9_facility` unregistered** — the same fault, in work from earlier this same pass | the functionality suite |
| 4 | **The stale `/stress` route**, still pinned by `tests/cockpit_agentic/test_ownership_mechanism.py` — on the Cockpit session's own defect list. The registry was right; the test was asserting a product that had moved on | the Cockpit test suite after the repoint |
| 5 | **A false provenance sentence on every Cockpit screen.** The module constant describes the Cockpit's own generated demonstration; printed over the shared corporate book it was simply untrue | reading the screenshot the browser suite took |
| 6 | **`AUTHOR`, `cockpit_preprocess` and `cockpit_reasoning` had no cost routing class** — each would have had its spend land wherever the default happened to be, which is the quiet reclassification the map exists to prevent | `tests/llm/test_cost.py` |
| 7 | **Six high-precision display sites** unaccounted for. Examined one at a time and allowlisted with the argument for each: two are lookup keys never rendered, one is a failure message for a release that is never published, two are multipliers and a ratio where the third decimal is the finding | `scripts/check_decimals.py` |

**Three faults in my own checks**, recorded because each produced a confident
wrong answer before it was caught:

* the credential check grepped for `ANTHROPIC_API_KEY` and reported the defect
  present. That string is in the module because it heads a `FORBIDDEN_FALLBACKS`
  list whose purpose is to prove it inert. It now sets every forbidden variable
  and asks the Cockpit what it sees;
* the Alembic check parsed migration files with a regex and reported six heads
  where Alembic reports one. It now asks Alembic;
* the What-If check ran the first scenario in the catalogue, which is `base` —
  the reported position, whose entire point is that nothing moves. It proved the
  engine returns the same number twice. It now runs a scenario that carries a
  shock and asserts the two ECLs differ.

---

## 5. Known issues carried forward

`scripts/acceptance/defect_carry_forward.py` re-asks 28 known defects from every
feature session of THIS build, because a branch merging cleanly does not mean
its fixes survived: a merge takes the side it is told to take, and a fix on the
losing side is gone without a conflict.

**27 VERIFIED · 1 DEFERRED · 0 PRESENT**

Verified include: the Cockpit's credential isolation (asked behaviourally, with
every forbidden fallback set) and its provider `repr`; referral routes;
`STRICT_ROLES`; the clarification caveat's position ahead of the Cockpit
short-circuit; `scope` and `domain_lock` both surviving the same hard merge;
canonical `CORP-` identity in Early Warning with zero orphans; the 19+D
masterscale at ordinals 1–20; Stage 3 applicable PD at 100% on all 1,470 rows;
the 16-quarter period set; XGBoost importing; the Lens domain guard; both
Playbooks mounting without collision across 670 paths; the empty-Playbook
false-ready bootstrap; one Alembic head; the display contract.

**The one deferred item, named rather than buried:** the SME model registry row.
`registry.seed()` loops over `(APPLICATION, BEHAVIORAL)` while `models.py`
points at `registry_key="SME"`. It is on the feature branch's own defect list
and is post-demo work under the scope control.

---

## 6. Also deferred, post-demo

| Item | Why |
|---|---|
| Cockpit forward projection (`quarter_offset > 0`) | No canonical source. Not fabricated; the macro window publishes actuals only |
| `cockpit_ifrs9_detail` term structure | The two ECL models genuinely disagree — see §2 |
| Cockpit V2's 12-grade scale | V3 already matches canonical; V2 is a separate, older surface |
| SME statement kernel and recalibration | Explicitly out of scope for this pass |
| 84 `ruff` findings | Inherited, unchanged through this pass, none new. `B904` chaining, `B905` zip-strict, `F841`, `E741` — judgement calls on other branches' code |
| Eight orchestration/planner failures | Inherited. M6's diff touches zero files under `backend/orchestration`, `backend/engine`, `backend/runtime` or any non-Playbook router, so nothing in it can reach the analytical planner they exercise |

---

## 7. Migrations

```
alembic heads     ->  0049 (head)          exactly one
0031 -> head      ->  clean, no manual step
head -> 0031      ->  104 tables / 1,648 columns
0031 -> head      ->  162 tables / 2,577 columns, identical to before
```

Round trip verified by comparing `information_schema` before and after, not by
re-reading the migrations.

---

## 8. Local startup

See `docs/DEMO_STARTUP.md` for the full runbook. In short:

```bash
cp .env.example .env        # set DATABASE_URL, COCKPIT_AGENTIC_V3=true,
                            # NEXT_PUBLIC_API_URL=http://127.0.0.1:8000
createdb creditprobe
.venv/bin/alembic upgrade head
.venv/bin/python scripts/build_corporate_ifrs9_facility.py
COCKPIT_AGENTIC_V3=true .venv/bin/python scripts/build_cockpit_canonical.py
.venv/bin/python scripts/bootstrap_demo.py

# two terminals
COCKPIT_AGENTIC_V3=true .venv/bin/python -m uvicorn backend.api.main:app \
    --host 127.0.0.1 --port 8000
cd frontend && npm run dev
```

Open **http://127.0.0.1:3000**.

**Before you start, kill anything already on 3000 or 8000.** A stale server
answers 200 to a health check while serving a previous build — that is defect 1
above, and it is the single easiest way to demonstrate the wrong thing.

### Demo sign-in

Password for every account: **`creditprobe-demo`**

| Username | Role |
|---|---|
| `alex.rahman` | Administrator |
| `sara.qahtani` | Data steward |
| `omar.nasser` | Analyst |
| `layla.haddad` | Viewer |
