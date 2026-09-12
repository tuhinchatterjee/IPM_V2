# Morning handover — Saudi retail CreditProbe, overnight manual UAT

Written after the night's work, against the running application in Chromium.
Every figure below was reconciled against the published Parquet by an
implementation that shares no code with the product.

---

## A. Build identity

| | |
|---|---|
| Branch | `claude/funny-dirac-6n8f0o` |
| Base of this session | `807dd6d` |
| Tree state | clean at the final commit; every change committed and pushed |
| Backend | `http://localhost:8328`, API prefix `/api/v1` |
| Frontend | `http://localhost:5328` |
| Database | PostgreSQL on 55432, database `creditprobe_retail` |
| Lake | `data/retail/analytics/retail_facility_month`, Hive-partitioned by `reporting_month` |
| Dataset | one domain (Cockpit Data), one dataset, **546 governed fields**, **447,853 rows** |
| Period coverage | **2024-08 … 2026-08**, 25 consecutive month-ends |
| Latest month | 2026-08 · 19,745 facilities · 14,251 customers |
| Latest fully matured cohort | 2025-08 (the window has closed for every account) |
| Frozen 5318 / 5308 | untouched. Nothing outside this repository's retail tree, the shared semantic layer and the UAT harness was modified; no freeze tag moved, no force-push, no merge to main |

**Oracle figures used throughout**: gross carrying amount 2,082,852,855.82;
ECL 15,952,108.84; coverage 0.7659%; stage shares 93.92 / 5.42 / 0.66%;
30+ DPD by product 3.6982 / 1.9967 / 1.8881 / 1.6209%; application Gini
0.312234; behavioural Gini 0.577979; bureau Gini 0.724987.

---

## B. Overnight defects

**Thirty-seven defects found and fixed tonight**, ON-40 … ON-76, on top of the
thirty-nine already in the register. Thirty-five of them were found by USING
the product — asking it questions a Head of Retail Risk asks, reading the
answers against the book, and driving the screens in a real browser. The other
two were found by the branch's own tooling: the frontend linter (ON-75) and
the frontend test suite (ON-76).

| Severity | Tonight | Register total |
|---|---|---|
| P0 / P1 — a wrong or misleading figure a reader would act on | 20 | 45 |
| P2 — a broken or confusing control, or a false statement about the product | 16 | 29 |
| P3 — cosmetic, wording, or a gate that reports red on correct code | 1 | 2 |
| **Total** | **37** | **76** |

Two of the thirty-seven are mine. ON-70 was a regression introduced by an
earlier fix the same night — an ordering word read as an aggregation, so
*"the worst 10 customers by ECL"* ranked each customer by their largest single
facility — and ON-75 was a blank select left by the ON-50 fix. Both are in the
register under their own numbers rather than folded into the fix that caused
them.

Each carries a reproduction, a root cause, the fix, a named regression test
and the browser journey re-run afterwards, in
`docs/RETAIL_OVERNIGHT_DEFECTS.md`.

### The ones that would have been seen in a demonstration

* **The conversation lost the conversation** (ON-40…ON-44). Four consecutive
  turns of one ordinary session each failed differently. A pronoun follow-up
  came back "Which figure should CreditProbe measure?" — and, because the
  clarification became the thread's pending question, the next three sentences
  were read as answers to it and the conversation never recovered.
* **"The average behavioural score" was the HIGHEST score in the book**
  (ON-45/46): 754.59 against the true 673.99. Underneath it, the average
  12-month PD came back 476.76 and the average debt burden ratio 11,811.08 —
  the sums of nineteen thousand probabilities and ratios.
* **302 of 546 governed fields had no definition** (ON-47), pointing the
  reader at a path inside this repository which itself repeated the sentence.
* **Stage migration could not be answered** (ON-58): "how many facilities
  migrated from Stage 1 to Stage 2" answered 1,392 — every facility in Stage 2
  — where the answer is 279.
* **A percentage bound compiled against a decimal column** (ON-61) and matched
  nothing: "debt burden ratio above 50 percent" returned an empty answer where
  6,608 customers qualify.
* **Thirty-eight API routes answered a caller with no credential** (ON-65),
  including the saved investigations and the whole governed dictionary.
* **Every certified analysis in the product was unrunnable** (ON-66) and one
  of them intercepted "How much of the book is secured?" and handed back a
  clarification.
* **"What is our COLLATERAL coverage?" was answered "ECL Coverage is 0.77%"**
  (ON-67).
* **The backend did not stop on SIGTERM** (ON-68), and a restart signed
  everybody out (ON-69).
* **"Show me the worst 10 customers by ECL" ranked the wrong thing** (ON-70):
  each customer by their largest single FACILITY, so the true top customer by
  ECL did not appear on the list at all.
* **A 25-month trend was answered with two points** (ON-72), 2025-08 and
  2026-08, under a heading that said 25 months — and a monthly series was
  drawn as a horizontal bar ranking with the months ordered by size (ON-73).
* **No composed answer ever opened as a chart** (ON-74): the visualisation
  gate decided `chart_first` correctly and the field never reached the
  screen.
* **Two builder forms opened with a blank dataset** (ON-75), because the fix
  that stopped them naming the corporate book seeded the catalogue default
  from an effect — one render late.

---

## C. Chat quality

### Cockpit

| | |
|---|---|
| Questions executed in the browser | 24 (§5 set plus the rate/share regressions) |
| Result | **18 of 18 cases pass** |
| Defects found and fixed here | ON-40…ON-46, ON-51…ON-57, ON-61…ON-64, ON-70, ON-71, ON-72…ON-74 |

Representative five-turn thread (§23 journey A, re-run end to end):

1. *"What needs my attention in the retail portfolio this month?"* — a ranked
   list of customers with the governed concern signals behind each.
2. *"Why is that happening?"* — the drivers, from the signals already counted.
3. *"Show me the evidence."* — names the dataset, the columns and the
   calculation.
4. The thread is listed under Investigations after leaving the module.
5. Reopening carries the whole conversation, not only the title.

**Context retention** — §24 runs the same question twelve ways and checks that
context is MODIFIED rather than discarded: 13 of 13 pass. A narrowing keeps the
measure and the breakdown; a broadening drops the filter it widens out of and
keeps the one it does not; a correction replaces the measure rather than adding
it; a pronoun follow-up keeps the population AND names it on the caption.

**Clarification** — an ambiguous unit is asked about rather than guessed, and
the clarification can be answered in free text rather than by clicking a chip.
An unreadable question is answered with a question, never a crash.

**Evidence** — every answer carries a Trace; "show me the evidence" exposes the
dataset, the columns and the statement that ran.

**Chart appropriateness** — no chart for a yes/no question, a conceptual
explanation or a single fact; a chart for a 25-month trend and a product
ranking. The stage composition draws three bars now (ON-64). All seven chart
cases pass on the final build. Three defects behind them were found in the
last hour: a 25-month trend answered with two points (ON-72), a monthly
series drawn as a horizontal bar ranking with the months in order of size
(ON-73), and — under both — the fact that no composed answer had EVER opened
as a chart, because the gate decided correctly and the decision never reached
the screen (ON-74).

### Scorecard Validation

| | |
|---|---|
| Questions executed | 12 of the §6 set |
| Result | **14 of 14 cases pass** |

### What-If

| | |
|---|---|
| Questions executed | 13 of the §7 set |
| Result | **15 of 15 cases pass** |

### Other conversational surfaces

Early Warning, Customer 360, Metric Catalogue and the Playbook carry no
composer of their own; each was driven through its controls instead (§D, §G).

---

## D. Cross-module workflows

**20 of 20 pass** (`overnight_workflows`), plus the four §23 journeys
(**23 of 23**) and Customer 360 (**11 of 11**).

| Journey | Result |
|---|---|
| Thread from a Cockpit answer, three follow-ups, refresh, leave, reopen, continue, Back | pass |
| Investigation listed, reopened with its conversation | pass |
| Playbook pack opened, every block carrying a figure, Back to the Playbook | pass |
| Message addressed to a disposable UAT account, sent, opened in the recipient's own mailbox | pass |
| Saved What-If reopened from Recent Runs with its figures and an export beside it | pass |
| Early Warning alert → Customer 360 → Back to the EXACT filtered list | pass |
| Save / reopen / refresh / backend restart / sign-out / sign-in | pass (§18, 19 of 19) |

Destructive and messaging tests used disposable UAT-owned accounts throughout.
No real email or external message was sent.

---

## E. What-If

Every methodology in the retail set was exercised: a PD shock on one product,
a narrowing turn, an explanation of the impact, an unsupported unit, a product
switch, a cutoff replay, a scenario reweighting, the neutral parity case, an
unreadable scenario, the opening book, save, reopen, deep link and export.

* **Neutral parity** — a neutral scenario reproduces the published book
  exactly and says that is what it did.
* **Save / reopen / deep link** — a saved scenario survives leaving the module
  and reopens with its own pinned inputs; a deep link renders with a working
  in-app parent.
* **Unsaved export** — offered beside a saved scenario; an unsaved run is not
  claimed to persist, and the screen is headed "Saved What-Ifs" accordingly.
* **Refused rather than guessed** — an ambiguous unit, an impossible
  assumption and an unreadable scenario are each asked about, never run as a
  no-op.

---

## F. Scorecard

Eight models — four application, four behavioural, one per product — bound to
`retail_facility_month`, scoped by product, with the frozen bins and published
coefficients.

| | |
|---|---|
| Discrimination | Gini, AUC and KS on the latest FULLY MATURED cohort (2025-08), not the latest month with any outcome. Application 0.3122 / 0.6561 / 0.2465; behavioural Gini 0.5780; bureau 0.7250 |
| Calibration | predicted against observed on the same population, band by band. Average predicted 12-month PD 1.32% against an observed 2.10% |
| Drift / stability | population stability reported with its threshold labelled a convention rather than a rule, and the characteristic that moved named |
| Raw / transformed inputs | every configured model input is held raw, binned, weight-of-evidence transformed, with its missing flag and its points contribution |
| Mature-cohort logic | the maturity rule is the one the book states — `performance_window_complete_flag` and `monitoring_eligible_flag` — so the cohort is 2025-08 with 17,238 eligible rows and 370 defaults, 2.10% |
| Score reconstruction | the production score is reproduced from the approved specification and reconciles exactly, 7,701 of 7,701 rows |
| Audit response | an untestable question is refused with its reason rather than answered anyway; the auditor answer rests on computed figures and claims no approval |

---

## G. Manual browser evidence

Everything below was driven in Chromium against the launcher-served
application, with a screenshot captured for every case. Every one of these
fourteen suites was re-run against the FINAL build, after the last fix, not
only when its own defect was closed.

The evidence is `docs/evidence/retail_functionality/*.json`, one file per
suite, with the screenshots in `screens/`. The `probes/` directory beside them
holds throwaway diagnostic runs used to locate defects — two of them record a
FAIL, both of them a selector question the probe was written to answer, and
neither is a product defect or part of the count below. Its README says so.

| Suite | Result |
|---|---|
| §5 Cockpit chat | 18 / 18 |
| §6 Scorecard | 14 / 14 |
| §7 What-If | 15 / 15 |
| §8–§11 threads, Playbook, messaging | 20 / 20 |
| §13 Early Warning | 12 / 12 |
| §14 Customer 360 | 11 / 11 |
| §15 + §16 Data Builder, dictionary, lens authoring | 22 / 22 |
| §12 Metrics, Lenses and Playbook, read on screen | 11 / 11 |
| §17 navigation and Back paths | 10 pass, 1 n/a |
| §18 + §19 + §20 persistence, security, failure injection | 19 / 19 |
| §21 + §22 + §25 visual, chart discipline, timings | 19 / 19 |
| §23 cross-module journeys | 23 / 23 |
| §26 corporate zero-tolerance sweep | 29 / 29 |
| §24 language and context | 13 / 13 |
| **Total across the fourteen suites** | **236 pass, 0 fail, 1 n/a** |

The one NOT APPLICABLE is NAV-07, an unsaved-scenario-name warning, recorded
with its reason: the What-If composer holds no document-style edit, so there
is no unsaved state to warn about. It is not a failure wearing another label.

**Viewports** — every route was opened at **1440×900** and **1512×982** and
MEASURED rather than eyeballed: `scrollWidth` against `clientWidth` on the
document, the same on every element for clipped text, and the bounding box of
every button for controls pushed off the side. No screen scrolls sideways, no
text is clipped by its own box, no control is off the screen, and no screen is
still loading after it has settled, at either size. The composer is reachable
and its Send is live at both.

**Visual defects fixed** — the Data Builder domain screen counted its one
dataset twice, offered the corporate book as the example of a governed join,
and said "nothing published from this domain yet" beside a published dataset
(ON-48, ON-49, ON-50).

**Timings** (§25, recorded rather than judged against an invented SLA): a cold
Customer 360 route 93s on first compile and under 3s afterwards; every chat
answer between 5 and 8 seconds; nothing took minutes.

---

## H. Final test counts

Automated, and AFTER the manual result rather than in place of it.

| Suite | Result |
|---|---|
| `tests/retail` | **1008 passed, 0 failed** (673s), on the final commit with a clean tree |
| `tests/orchestration` | unchanged against its pre-session baseline, checked by diffing the failure lists |
| `tests/api` | unchanged against its pre-session baseline, same method |
| `tests/metrics` | unchanged against its pre-session baseline, same method |
| frontend `npm test` | **577 passed, 0 failed**, 48 suites |
| frontend `npm run typecheck` | clean |
| frontend `npm run lint` | 6 errors, all `react-hooks/set-state-in-effect` and all present at this session's base; tonight's work added two and removed them again (ON-75) |

The backend suites above are reported as *unchanged against baseline* rather
than as a pass because they are the CORPORATE book's suites and they fail on
a retail installation for that reason — see section I. The method was the same
every time: stash the change, run the suite, capture the sorted list of
`FAILED`/`ERROR` lines, restore, run again, diff the two lists. An identical
list means the change introduced nothing. A count alone would not have shown
that, because one new failure and one fixed one net to zero.

New regression suites written tonight, all reconciling against the Parquet
rather than against the code that produced the answer:

| File | Gates |
|---|---|
| `test_ret_overnight_followups.py` | 43 |
| `test_ret_overnight_dictionary.py` | 31 |
| `test_ret_overnight_counts_and_signs.py` | 19 |
| `test_ret_overnight_migration.py` | 19 |
| `test_ret_overnight_scale_and_series.py` | 25 |
| `test_ret_overnight_access_and_methods.py` | 26 |
| **New tonight** | **163** |

Written earlier on this branch and re-run tonight:
`test_ret_overnight_metric_route.py` 77, `test_ret_overnight_filters.py` 39,
`test_ret_overnight_concern.py` 33, `test_ret_overnight_scorecard.py` 33,
`test_ret_overnight_early_warning.py` 20.

---

## I. Honest blockers

### Internal — none broken, two things named rather than buried

Every defect found tonight was fixed, regression-tested and re-run in the
browser. Nothing is recorded as N/A, BLOCKED or "demo limitation" to avoid
fixing it. Two facts belong here anyway, because neither is a pass:

* **One screen behind tonight's last fix was not driven in the browser.**
  ON-75 changed two forms. `/engine-builder/new` was opened in Chromium and
  its Required dataset reads `retail_facility_month`. The twin control is the
  Add Dataset wizard's **step 6**, and reaching step 6 means creating a
  dataset, uploading a file and saving a dictionary — and this installation
  has no route that deletes a dataset, only archive. Driving it would have
  left a scratch dataset on the Data Builder screen for the demonstration, so
  it was not driven. The change is the same three lines as the screen that
  was driven, and it is covered by
  `frontend/src/lib/__tests__/builder-defaults.test.ts`. That is weaker
  evidence than the rest of this handover and is recorded as weaker.
* **Six `react-hooks/set-state-in-effect` errors remain in the frontend
  linter**, in Customer 360, Early Warning Signals and the retail What-If
  composer. They are unchanged from this session's base — tonight took the
  count from eight back to six rather than leaving my two behind. All three
  screens pass their browser suites in full (Customer 360 11/11, Early
  Warning 12/12, What-If 15/15), so this is a latent pattern rather than an
  observed failure. It was not refactored at the end of a long night: these
  are the asynchronous screens, and an unforced rewrite of state handling on
  three proven journeys is the wrong trade at this hour. It is the first
  thing to take on next.

### Not run, and why

* **Provider-backed chat — NOT RUN.** No authorised model-provider credential
  is available in this environment, and none was requested. Everything above
  was answered by the deterministic governed semantic reader, which is the
  whole path when no provider is configured. The screen says so: "No AI
  provider is configured. CreditProbe reads questions with its deterministic
  governed semantic reader and computes every figure in the governed runtime."
  Nothing here claims AI was tested.
* **Mac launch — NOT RUN.** This work was done on Linux. No Mac acceptance is
  claimed. The launcher scripts were changed tonight (ON-68) and are
  shell-syntax-checked, not Mac-executed.
* **Exact WHATIF_5318 provenance — NOT RUN and still open.** No rebase was
  performed to force a provenance story.

### Pre-existing, not caused by tonight's work

`tests/orchestration`, `tests/api` and `tests/metrics` carry failures on a
retail installation because they assert the CORPORATE book's vocabulary —
"Real Estate", "the ratings data", `portfolio_facility`. Their counts are
identical before and after every change tonight, verified by diffing the
failure lists at each step. They are an environment fact of running a
corporate test suite against a retail installation, not a regression.

---

## J. Presentation-readiness verdict

## LOCAL UAT CANDIDATE — INTERNAL GAPS REMAIN

That is the honest label, and the reason is not that something is broken on
screen tonight. It is that the evidence does not yet support the stronger one.

### What the stronger label would have required, and what is missing

`PRESENTATION CANDIDATE — INTERNAL UAT PASS` claims that a session of hard
use would not turn up a material defect. Three facts say otherwise.

**The discovery curve had not flattened.** Thirty-five defects were found
tonight, twenty of them the kind a reader would act on — a wrong number, a
wrong population, a ranking that ranked the wrong thing. They did not taper.
ON-72 — *"Show the 25-month weighted ECL trend for credit cards"*, a question
from the demonstration script itself, answered with two points — was found in
the last hour of the night, from a question nobody had happened to ask until
then. ON-70, the worst-ten-customers ranking that ranked each customer by
their largest single facility, was found the same way. A curve still rising
at the end of a long night means the next session of hard use finds more. It
would be a claim about untested ground to say otherwise.

**The product's headline path was not exercised.** Every answer in this
handover came from the deterministic governed semantic reader, because no
authorised model-provider credential exists in this environment and none was
requested overnight. That reader is a real path and it is the path the
product falls back to, but the conversational quality of a provider-backed
session is untested here. Section C is an honest account of the reader, not
of the product with a model behind it.

**The shared semantic layer is not green on this installation.** Its suites
assert the corporate book, and they fail here for that reason — verified
unchanged, failure list by failure list, before and after every change
tonight. That is an environment fact rather than a regression, and it is
also a missing safety net: the layer those files belong to is carrying
retail changes tonight without its own suite able to confirm them. The
retail suites cover what was changed; the corporate ones cannot.

### What the weaker label would have required, and why it does not apply

`NOT READY` would mean a material internal workflow is broken now. None is.
Every defect found tonight was reproduced, fixed, regression-tested, and the
exact browser journey re-run and looked at again. At the close of the night
every browser suite passes on the current build:

cockpit 18/18, language 13/13, metrics 11/11, scorecard 14/14, what-if
15/15, workflows 20/20, early warning 12/12, journeys 23/23, data and lenses
22/22, retail-only 29/29, Customer 360 11/11, resilience 19/19, visual
19/19, navigation 10/10 with one case not applicable.

The single NOT APPLICABLE is NAV-07, an unsaved-scenario-name warning. It is
recorded with its reason — the What-If composer holds no document-style edit,
so there is no unsaved state to warn about — and not as a way of retiring a
failure. Nothing else in this handover is marked N/A, BLOCKED or "demo
limitation".

Every quantitative claim was reconciled against an independent pandas read of
the Parquet rather than against the code that produced the answer: GCA
2,082,852,855.82, ECL 15,952,108.84, coverage 0.7659%, stage shares
93.92/5.42/0.66%, the three Ginis, the migration matrix, the latest matured
cohort.

### What this means for tomorrow

The build can be driven in front of an internal audience by someone who knows
it, on the journeys section G records, and it will hold. What it has not
earned is the claim that an unrehearsed question from the floor lands safely,
because tonight's own unrehearsed questions kept finding defects until the
end.

The three shortest routes to the stronger label, in order of what they buy:

1. A second adversarial session on the Cockpit specifically, asking questions
   nobody has asked yet — the twenty P1s tonight came almost entirely from
   that surface, and it is the surface a demonstration lives on. The six
   remaining linter errors in section I are the same session's work: they sit
   on three screens the browser suites pass, so they are a rewrite to do with
   a clear head and the suites to check it against, not at the end of a night.
2. A provider credential, so section C can be written about the product as it
   ships rather than about its fallback.
3. A Mac run of the launcher. The launcher scripts changed tonight (ON-68)
   and have been shell-syntax-checked only; no Mac acceptance is claimed.
