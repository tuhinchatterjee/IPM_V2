# Scorecard Validation Intelligence — Final Report

**Branch:** `claude/scorecard-validation-intelligence`
**Baseline:** `c17c426` (the verified Playbook HEAD)
**Final HEAD at the time of writing:** `90517f8`
**Scope:** 58 files, +19,503 / −1,582 lines, 14 commits

Sections A–AM. Every number was produced by a command run on this branch and
its output read. Where something was not verified, the section says so and
does not soften it.

---

## A. What was asked for, and what this reports against

Transform the Scorecard Validation screen into a Scorecard Validation
Intelligence Cockpit restricted to exactly three scorecard domains: the Retail
Application Scorecard, the Retail Behaviour Scorecard and the Saudi SME
Scorecard. Combine domain-restricted AI conversation, structured validation
planning, deterministic quantitative testing, qualitative validation support,
interactive charts, test-level tables, cross-test pattern recognition, model
weakness prioritisation, remediation recommendations, champion/challenger
comparison, validation evidence and lineage, CBUAE MMS/MMG-aligned report
drafting, browser-based review, and professional Word report generation.

This report states what was built, what was measured, what was found while
building it, and what remains unverified.

---

## B. The recommendation

**READY FOR USER ACCEPTANCE TESTING**, with the conditions in §AK.

The reasoning, stated so it can be disagreed with:

- Every material acceptance gate is PASS. Eight gates remain NOT VERIFIED
  (§AJ), and none of them is a claim the product makes about itself — they are
  verifications not performed in this environment.
- The engine, the conversational surface, the cockpit and the report were
  each exercised against real data and a running server, not only under test
  doubles. Three defects surfaced that way and are fixed (§AC).
- The module's most dangerous failure modes are structurally prevented rather
  than watched for: a language model cannot compute a statistic, a refusal
  cannot be rendered as a pass, and an unmeasured result cannot carry a
  number. Each is enforced by a constructor or a gate, not by a convention.

The one condition that would flip this to NOT READY is not present: no
material gate is FAIL.

---

## C. The one claim that shapes everything

> **A language model may decide which question to answer. It never decides
> what the answer is.**

Every figure that reaches a validator came from `backend/scorecard/metrics.py`
through `validation/runner.py`. The provider's entire contract is a schema
with a tool id and parameters drawn from closed sets — there is no field in it
for a number or a sentence, so there is nothing for a model to fill one into.

A validation environment whose numbers cannot be reproduced has no value, and
a paraphrase is not reproducible.

---

## D. The second claim: two-directional isolation

The Scorecard Validation surface can read the three scorecard populations and
nothing else. Every other surface can read everything else and not those
three.

The second half is the one that is easy to get half right. Those tables hold
the development population, every variable that went into the fit, and who
subsequently defaulted. A general chat surface that answers "what is the KS of
the application scorecard?" has moved a model validation out of the
environment that governs it, without anybody deciding to.

Two independent backend gates enforce it (§L). Neither is the page hiding
options.

---

## E. What was built

| Component | File | Lines |
|---|---|---:|
| Test registry — 48 tests, 11 categories | `validation/registry.py` | 736 |
| Model registry — 3 models, limits with provenance | `validation/models.py` | 575 |
| Result states — ten, with severity order | `validation/states.py` | 381 |
| Runner — five gates, 21 handlers, partition cache | `validation/runner.py` | 1,090 |
| The remaining 27 handlers | `validation/extra.py` | 1,584 |
| Findings — 7 cross-test patterns, ranking, citations | `validation/findings.py` | 889 |
| Regulatory map — 9 CBUAE requirements | `validation/regulatory.py` | 265 |
| Report studio — 4 opinions, DOCX | `validation/report.py` | ~470 |
| Agent — 9 governed tools | `validation/agent.py` | 407 |
| Conversational reader | `validation/conversation.py` | ~560 |
| API — 12 routes | `api/routers/scorecard_validation.py` | ~500 |
| Saudi SME universe | `scorecard/sme/*` | 2,031 |
| Cockpit page | `app/scorecard-validation/page.tsx` | ~470 |
| Chart dispatcher — 16 kinds onto 5 primitives | `components/.../validation-chart.tsx` | ~650 |
| Result card | `components/.../result-card.tsx` | ~300 |
| Ask | `components/.../ask.tsx` | ~330 |

---

## F. The forty-eight tests

| Category | Tests | The question a validator is asking |
|---|---:|---|
| Data & Representativeness | 7 | Is this data complete, current, and representative of what the model was built for? |
| Conceptual Soundness & Design | 5 | Is the design defensible, documented and used as intended? |
| Discrimination | 6 | Does this model rank risk? |
| Calibration & Accuracy | 5 | Are the predicted default rates right, not just ordered right? |
| Stability | 4 | Is the model still looking at the same kind of book? |
| Robustness & Sensitivity | 3 | How much does the answer depend on choices we happened to make? |
| Variables & Binning | 5 | Which variables are doing the work, and which have stopped? |
| Model Usage, Overrides & Policy | 4 | Is the score being followed, and do the departures perform? |
| Implementation Verification | 2 | Does the system compute what the document says it computes? |
| Segmentation | 3 | Does the aggregate result conceal a segment where it fails? |
| Champion vs Challenger | 4 | Should we replace the champion — and what would we be trading? |

The category cards on screen carry that right-hand column, not the left. A
validator does not ask "run the discrimination category"; they ask whether the
model still ranks risk.

---

## G. The five refusal gates

Ordered. Each answers a question the next would otherwise answer wrongly.

| # | Gate | Refuses with | Why it sits here |
|---|---|---|---|
| 1 | Authorisation | `NOT_AUTHORISED` | A refusal for any other reason leaks the answer to a question the caller was not permitted to ask |
| 2 | Applicability | `NOT_APPLICABLE` | "This scorecard produces no PD, so it has no calibration" is stronger and more useful than "the `pd` column is missing" |
| 3 | Availability | `UNAVAILABLE` | Names the column or reference that is absent |
| 4 | Maturity | `NOT_MATURED` | An immature cohort is not a small sample; reporting it as one invites somebody to widen the window and "fix" it |
| 5 | Sufficiency | `INSUFFICIENT_SAMPLE` | Enough observations and enough events, separately |

---

## H. The tenth state

The original nine had a defect that only appeared under test: a test that
computed a value but had no configured tolerance returned `PASS`, because
`PASS` was the default. VAR-WOE on the SME scorecard reported a real
monotonicity breach as green.

`NO_LIMIT` fixes it structurally — `_verdict` no longer has a default:

```python
limit = model.limit_for(test_id)
if limit is None:
    return states.NO_LIMIT, None, ""
return limit.verdict(value), limit.value, limit.source
```

Nine tests carry **structural** limits rather than policy ones: duplicates,
implementation replication, variable sign and WoE monotonicity at zero, and
the five documentation tests at one. A structural limit is sourced
`STRUCTURAL`, distinct from the seeded `DEMO POLICY`, so a reader can tell
arithmetic from appetite.

---

## I. The population window depends on the question

The subtlest design decision in the module, and it was wrong first.

A test needing a realised outcome must run on the **matured** window. A test
measuring drift must run on the **current** window. Defaulting everything to
matured measured the drift of the book as it stood a year ago — and on this
build the difference is not academic: the same characteristic reads **0.01**
on the matured window and **0.49** on the current one.

The window is now derived from the test's own declared requirement:

```python
matured_only=test_registry.NEEDS_OUTCOME in test.requires
```

not from a flag a handler author has to remember.

---

## J. Where the numbers come from

No statistic is computed by a language model, and no statistic is computed
twice. `metrics.py` and `binning.py` are the only modules that compute one.
When the bootstrap needed to be fast, the fix was a new kernel **inside**
`metrics.py`, not a faster copy inside the runner.

---

## K. The bootstrap, and why it is exact rather than close

`ROB-BOOTSTRAP` on the retail application scorecard took **96 seconds**: 500
resamples × a full Mann-Whitney AUC over ~100k rows.

The Mann-Whitney AUC depends on the data only through the count of goods and
bads at each distinct score. A bootstrap resample of the rows is therefore
*exactly* a multinomial draw over that count table:

```python
below = np.concatenate([[0.0], np.cumsum(good)[:-1]])
return float((bad * (below + good / 2.0)).sum() / (goods * bads))
```

96 s → **3.9 s**. A re-expression, not an approximation, and the test asserts
exact equality against the row-level path rather than closeness.
`DISTINCT_SCORE_LIMIT = 50_000` falls back when a score column is continuous
enough that the count table stops compressing.

---

## L. The domain boundary, enforced twice

**Gate 1 — Discovery.** `orchestration/context.py` drops the restricted
datasets from the general Cockpit's universe, so they cannot be searched,
autocompleted, suggested, or picked up by a planner scanning for a table with
"score" in its name.

**Gate 2 — Execution.** `runtime/validation.py::validate` checks the dataset
of every SCAN in every plan before it compiles. A dataset id arriving by any
other route — typed, replayed, guessed, or injected through a document — is a
SCAN, and all four stop there.

The check sits in `validate` rather than in the `_scan` handler for two
reasons: every SCAN is visible at that point without threading a permissions
argument through sixteen handlers, and a refusal raised before any catalogue
lookup cannot be turned into an existence oracle.

`tests/corporate/test_scope_separation.py` pins it by naming the exclusions
rather than subtracting an unexamined difference.

**What is deliberately not restricted:** the governed aggregate metrics the
Retail Risk Lens and the Playbook packs publish. Those are approved outputs —
a Gini for a named month, reviewed and released. Blocking them would break two
shipped surfaces to defend a boundary they never crossed.

---

## M. The Saudi SME universe

36 monthly cohorts, 54,038 rows, 16 matured against a twelve-month window. 90
variables in six families; 26 of them proxies for external authorities.

Every one of those proxies is named as a proxy in
`docs/SAUDI_SME_SCORECARD_DATA_DICTIONARY.md`, which is generated from the
live catalogue by `scripts/generate_sme_data_dictionary.py` so it cannot
drift. Its §1 states without hedging that CreditProbe is connected to SIMAH,
ZATCA, FATOORA, GOSI, Qiwa, Mudad, Monsha'at and the Ministry of Commerce —
**none of them**.

---

## N. Determinism, and the defect that hid in it

The universe seeded from `abs(hash(key))` produced a **different universe in
every process**. Python randomises string hashing per interpreter, so two
processes computing the same AUC disagreed and neither was wrong.

```python
digest = hashlib.blake2b(key, digest_size=8).digest()
seed = (MASTER_SEED + int.from_bytes(digest, "big")) % 2**32
```

The bootstrap carries a fixed seed (`20240101`), time is frozen or controlled
in every time-dependent test, and cohorts are anchored to an explicit
reference date. The suite gives identical results before and after midnight —
an assertion that the newest calendar month is matured passes at 23:59 and
fails at 00:01, and a validation environment whose answers change at midnight
is not one anybody can rely on.

---

## O. The findings engine

Seven patterns, each naming the tests it reads:

| Pattern | Reads |
|---|---|
| Production does not match the specification | IMPL-REPLICATE |
| Portfolio calibration conceals a segment | CAL-OE + SEG-CALIBRATION |
| The cut-off is being overridden at its boundary | USE-OVERRIDE-OUTCOME + USE-MATRIX |
| Drift that is a definition change | STAB-CSI + VAR-IV |
| Passing on the strength of the other characteristics | DISC-AUC + VAR-IV |
| Most of the book has no outcome yet | DATA-MATURITY |
| A challenger advantage inside the champion's own interval | CC-DISCRIMINATION + ROB-BOOTSTRAP |

A `Finding` refuses to construct without evidence and without a verification
route. An assertion a reader cannot check is one they must take on trust,
which is the opposite of what an independent validation is for.

---

## P. Severity, and the rule that fixed it

State → distance from limit → materiality → evidence. Then **nothing changes
it**.

Getting that order wrong produced two real mis-reports during the build:

- Materiality promoted an `UNAVAILABLE` to HIGH — a *missing* result presented
  as a serious one. Fixed: materiality only ever raises a FAIL or WARNING.
- Materiality then ran *after* the thin-evidence cap and undid it, restoring a
  CRITICAL resting on 40 defaults. Fixed by moving the evidence cap last,
  under one rule: **nothing may raise a severity after it has spoken.**

---

## Q. The citations that were invented

The findings originally cited MMS 10.5, 10.6, 10.8, 10.9, 10.10 and MMG 2.13,
2.14. **None of those appears in any registry entry.** They were plausible and
they were made up.

`_cite()` now derives every reference from the CBUAE references carried by the
tests the finding cites as evidence, and a test fails the build if a citation
does not resolve. A regulatory reference the product cannot trace back to a
specific test result is not a citation; it is decoration a reader will treat
as authority.

---

## R. The word this module must never say

`regulatory.py` has four statuses: EVIDENCED, PARTIALLY EVIDENCED, NOT
EVIDENCED, NOT APPLICABLE.

There is deliberately no COMPLIANT. This module can say what evidence exists
and which requirement it speaks to. It cannot say a supervisor would accept
it, and a status vocabulary containing the word would be read as saying so
whatever the disclaimer beside it said.

Nine requirements: MMS 4.9, 9.4, 10.3, 10.4; MMG 2.8, 2.9, 2.10, 2.11, 3.9.

---

## S. The report

Four opinions, and the fourth is not a courtesy: `MINIMUM_MEASURED_SHARE =
0.5`. If fewer than half the applicable tests reached a measured state, the
report says INSUFFICIENT EVIDENCE and declines to opine. A validation opinion
resting on twelve of forty-eight results is a different kind of statement and
needs a different word.

**Windows are derived, never assumed.** The report id once read
`SCV-sme_champion-2023-01..2024-04..2025-12-…` because two different windows
were concatenated. `_windows(model)` now returns them separately and the cover
states both — a reader who does not know which window a Gini came from cannot
use it.

**It says DRAFT.** It did not, until a generated file was opened and read
during this build (§AC).

---

## T. The agent

Nine tools, reusing `backend.agentic.tools.Tool` rather than a parallel type:

`scv_list_models` · `scv_list_tests` · `scv_explain_test` · `scv_periods` ·
`scv_run_test` · `scv_run_category` · `scv_findings` ·
`scv_regulatory_coverage` · `scv_draft_report`

`invoke()` is the only entry. `_check()` rejects unknown parameters rather
than ignoring them — an ignored parameter is a caller who believes it did
something. `NO_TOOL_FOR` is published rather than hidden: arbitrary SQL or
Python, raw rows, changing a limit or a model, issuing an opinion, any dataset
outside the three.

---

## U. The conversational reader

`conversation.read()` resolves a question to one governed tool call with no
provider at all. Three things at once:

1. **The offline behaviour.** A bank network that refuses egress is a
   supported deployment, not a degraded one.
2. **The guardrail.** `_accept()` checks a provider's choice against the same
   registry: an unknown tool, test id, category or scorecard is refused and
   the deterministic reading is used instead.
3. **Something a test can pin.** A fixed question maps to a fixed tool call,
   in every process, with no network.

The deterministic reader is asked **first**. A configured provider cannot
change what a clear question means — otherwise the same question resolves
differently on two deployments, and a module whose answers depend on whether
an API key is present is not one anybody can rely on.

Refusals happen before a provider is consulted. A refusal that depends on a
model declining is a request that usually gets turned down.

A vague question is **clarified**, not refused: "how is the SME scorecard
doing?" is about the right thing, too generally, and the answer is the eleven
questions a validation asks.

---

## V. The cockpit

Chat at the top, three scorecards, a model-health strip whose second figure is
how many periods carry an outcome, the findings that would change a decision,
eleven category cards, and a results workspace.

**What is deliberately absent:** no overall score, no traffic light for the
model as a whole, no percentage complete. A single number for "is this
scorecard sound" is what a committee would quote and what no validator would
sign, and putting it on the screen would make every honest refusal beneath it
decorative. A test asserts that `overallScore`, `healthScore`,
`validationScore` and `percentComplete` appear nowhere in the page.

---

## W. The charts

Sixteen payload kinds mapped onto the five primitives already in
`components/analytics/charts.tsx`. Nothing new draws anything. A second chart
engine means two tooltip conventions, two palettes, and a fortnight later a
Gini in the colour that means "negative" everywhere else in the product.

What the mapping preserves is that a validation chart is almost never a
picture of the headline number: the headline of DISC-AUC is 0.6547 and the
chart is the ROC curve it was integrated from; the headline of STAB-CSI is the
worst variable's index and the chart is every variable ranked, because "which
one, and did the others move with it" is the finding.

A chart is drawn only for a measured result — the same flag that gates the
figure.

---

## X. Verified numbers

Saudi SME champion, matured window 2023-01..2024-04, 24,119 rows carrying
1,398 defaults. Re-run on the final HEAD.

| Test | Value | State |
|---|---|---|
| DISC-AUC | 0.6547 | WARNING |
| DISC-GINI | 0.3094 | WARNING |
| DISC-KS | 0.2241 | PASS |
| CAL-OE | 1.134 (observed 5.796% against predicted 5.111%) | PASS |
| ROB-BOOTSTRAP | 95% CI [0.6408, 0.6695], width 0.0287, seed 20240101 | NO APPROVED LIMIT |
| STAB-CSI | `bank_credits_to_declared_sales` 1.0799 on 2025-12; 2 of 8 outside | FAIL |
| VAR-IV | `commercial_bureau_score_proxy` retains 0.71 (0.0948 now, 0.1333 at approval) | NO APPROVED LIMIT |
| USE-OVERRIDE-OUTCOME | 6.29% against 3.37% — 1.86× | FAIL |
| SEG-DISCRIMINATION | 3 of 3 segments outside limit, worst MICRO | FAIL |
| DATA-MATURITY | 16 of 36 periods | PASS |

Two are worth pausing on. **ROB-BOOTSTRAP** reports that the interval
straddles the 0.65 limit — so the WARNING on DISC-AUC is inside the noise of
its own measurement, which is a different statement from "it failed". And
**VAR-IV** is NO APPROVED LIMIT rather than a pass: a characteristic has lost
29% of the information value it was approved with, and nothing governed says
how much loss is acceptable.

---

## Y. Every built weakness was found

The SME universe was generated with specific weaknesses. Each was found by a
test that did not know where to look:

| Built in | Found by |
|---|---|
| Micro-enterprise PD understatement | SEG-CALIBRATION |
| Micro-enterprise discrimination | SEG-DISCRIMINATION |
| Banked-sales definition drift | STAB-CSI |
| Commercial bureau proxy decay | VAR-IV |
| Upward-override abuse | USE-OVERRIDE-OUTCOME |
| Marginal discrimination overall | DISC-AUC |
| Immature cohorts | DATA-MATURITY |
| Bin monotonicity break | VAR-WOE |

---

## Z. Performance

| Operation | Before | After | How |
|---|---:|---:|---|
| ROB-BOOTSTRAP (retail) | 96 s | 3.9 s | Count-table AUC kernel (§K) |
| A full 48-test run | ~80 s of I/O | ~7 s | mtime-keyed `lru_cache` over parquet partitions |

The cache is keyed on `mtime_ns` so a rebuilt partition invalidates it, and
hands out a copy so a handler cannot mutate a shared frame.

---

## AA. Tests added

| Suite | Count |
|---|---:|
| `test_validation_runner.py` | 19 |
| `test_validation_extra.py` | 28 |
| `test_validation_findings.py` | 25 |
| `test_validation_regulatory.py` | 12 |
| `test_validation_report.py` | 21 |
| `test_validation_agent.py` | 21 |
| `test_validation_conversation.py` | 51 |
| `test_scorecard_validation_ask.py` (API) | 36 |
| Bootstrap tests in `test_metrics.py` | 9 |
| Frontend structural tests | 20 |
| **Total new, directly on this module** | **242** |

`tests/scorecard` as a whole: **613 passed, 1 skipped** in 336 s.

---

## AB. The ten regression failures, and their one root cause

A full suite run reported 10 failed / 12,492 passed across six unrelated
places, none of which mentioned the SME scorecard. All ten came from three
datasets registered in the catalogue and in the domain restriction without a
business domain:

1. Three datasets landed in `Unmapped` — a dataset a person cannot find on the
   Data Builder screen, which is the defect `data_domains` exists to prevent.
2. `install_business_domains` could never re-home them: it reads the catalogue
   domain and then overwrites it, so once a dataset was filed as UNPLACED the
   information needed to place it was gone. Placement is now independent of
   what was stored.
3. `_field("facility_id", "Facility", …)` hijacked "Tell me about
   portfolio_facility" — the metadata assistant matches on business name and
   the shorter one won. Qualified to "SME facility".
4. The three datasets had no brain measures. Seventeen measures and seven
   dimensions registered.
5. Forty-three display-decimal violations in the validation package — AUC
   0.6547 against a 0.65 limit reads as 0.65 at two decimals, which is a
   breach rendered as a pass. Allowlisted with the same reasoning that already
   exempts `metrics.py`.
6. Two scope-separation tests asserted the old behaviour, where the Cockpit
   could reach a scorecard dataset. Rewritten to assert the isolation
   invariant.

---

## AC. Three defects a running browser found that no unit test did

Everything was green before these. The engine was right in each case; what was
wrong sat between it and a person.

**`/overview` returned a 500 on the live server.** The router unpacked
`inapplicable_tests()` as bare tests when it yields (test, missing) pairs. A
screen wired to a route nobody has called is a screen that fails the first
time somebody opens it. `TestEveryRouteActuallyServes` now hits all eleven.

**The generated report never said "draft".** The screen said it, the button
said it, the agent said it. The file did not, and the file is what survives
the meeting. Fixed on the cover and in the document-control table. The
acceptance matrix had recorded this gate PASS on the strength of the button;
that claim was wrong and the correction stands beside it.

**The ROC axis read 0.000044, 0.062321, 0.118833.** Two hundred points as
categories, six decimals of spurious precision. The curve is downsampled to 51
points for drawing and the axis rounded to two — the statistic still
integrates every point.

---

## AC-2. An adversarial read of this module's own code

Two defects found by reading the code against its own claims rather than by a
failing test.

**A refusal rendered the word "true".** `refuse_out_of_domain` returns
`refused: True` — a flag — while `conversation.answer` returned
`refused: "<the thing>"` — a sentence. The client rendered the field directly,
so a validator asking for raw rows would have been shown `true`. Both paths
now use the flag, the subject has its own `what` field, and the client
composes the sentence. The browser journey had passed because it matched a
different part of the refusal.

**A refusal never said where the answer lives.** The client read
`where_it_lives`; the backend sends `where_instead`. The sentence never
rendered, and the structural test asserting it asserted the wrong key — so it
passed on a string that appeared only in the source. Both corrected, and the
test now names why.

A third, in the reader: **a keyword beat a named test.** "What is the worst
CSI?" resolved to the findings engine because it contains the word "worst" —
an answer about eight tests to a question about one, with nothing on the way
telling the reader it had happened. A question that names a test is now about
that test, whatever else it contains.

---

## AD. Browser journeys

Thirteen journeys, 37 checks, all passing against the running stack in
headless Chromium. Script at
`scripts/browser/scorecard-validation-journeys.mjs` so the run repeats.

| Journey | What it asserts |
|---|---|
| A | The cockpit renders; the three scorecards are named; the restriction is stated on screen |
| B | Periods, matured periods, immature periods, and an explanation rather than a number |
| C | Nothing reported as passing before a run; no overall score anywhere |
| D | The category cards carry the validator's question |
| E | Results appear with their coverage and the sentence explaining what it counts |
| F | 0.6547 against its 0.65 limit, with the limit's source |
| G | PASS, WARNING and NO APPROVED LIMIT distinguishable; a measurement with no limit is not called a pass |
| H | The evidence panel opens; a chart is drawn; no axis tick carries spurious precision |
| I | A question is answered, says which tool ran, and states no figure came from a language model |
| J | An out-of-domain question is refused, and the scope is stated |
| K | An injected instruction is refused |
| L | Switching scorecard clears the previous model's numbers |
| M | The retail monitoring surface still loads |

Plus: no unhandled console errors originating from this module.

---

## AE. Security

| Vector | Result |
|---|---|
| Cockpit discovering a scorecard dataset | Refused at gate 1 |
| Any plan scanning one | Refused at gate 2, before catalogue lookup |
| Model-authored SQL or Python | No such tool exists |
| Raw rows | No such tool exists |
| Changing a limit conversationally | No such tool exists |
| An unknown tool from a provider | `_accept` refuses it |
| An unknown test id, category or scorecard from a provider | `_accept` refuses each |
| An instruction inside a question | Resolves to no tool; the question is never interpolated anywhere that reaches data |
| A pasted document as a question | 422 at 2,000 characters |
| A `model_id` from a client | Validated through `models.get`, dropped if outside the three |
| A period argument becoming a path | `_periods` rejects anything not alphanumeric-with-hyphens |
| A VIEWER running tests by asking | 403 — the route carries ANALYSE |

---

## AF. What the module refuses to say

- It does not claim CBUAE compliance or regulatory approval (§R).
- It does not claim a live connection to SIMAH, ZATCA, FATOORA, GOSI, Qiwa,
  Mudad, Monsha'at, the Ministry of Commerce, a bureau or a core system (§M).
- It does not issue a validation opinion. The report is a draft (§S).
- It does not report an unavailable figure as zero, or an immature cohort as
  zero defaults.
- It does not give the model an overall score (§V).

---

## AG. Documents produced

| Document | What it is for |
|---|---|
| `SCORECARD_VALIDATION_INTELLIGENCE_REPORT.md` | This |
| `SCORECARD_VALIDATION_ACCEPTANCE_MATRIX.md` | Every gate, PASS or NOT VERIFIED by name |
| `SCORECARD_VALIDATION_ARCHITECTURE.md` | How it is built and what enforces each boundary |
| `SCORECARD_VALIDATION_USER_GUIDE.md` | How a validator uses the screen |
| `SCORECARD_VALIDATION_DEMO_RUNBOOK.md` | Twelve-minute demonstration, with the numbers to expect |
| `SAUDI_SME_SCORECARD_DATA_DICTIONARY.md` | Generated from the catalogue; names every proxy |
| `CBUAE_SCORECARD_VALIDATION_REPORT_MAPPING.md` | Requirement-to-test mapping |

---

## AH. Quality gates

| Gate | Result |
|---|---|
| `ruff check backend/ tests/ scripts/` | Clean |
| `npx tsc --noEmit` | Clean |
| `npx eslint` on the new surfaces | Clean |
| `scripts/check_decimals.py` | 92 allowed with a reason, 0 not |
| Frontend `npm test` | 540 passed, 0 failed |
| `tests/scorecard` | 613 passed, 1 skipped |
| `tests/api/test_scorecard_validation_ask.py` | 36 passed |
| Browser journeys | 37 passed, 0 failed |
| Full backend suite | §AI |

---

## AI. The final regression

<!-- FINAL_REGRESSION -->

---

## AJ. What was not verified

Eight gates, each stating what is missing rather than what is probably fine.

| Gate | Why |
|---|---|
| SCV-CALC-11 | No independent second implementation exists to reconcile against. `bootstrap_auc` is reconciled against the row-level path by exact equality, which is a re-expression check |
| SCV-AI-13 | No provider key is configured here. The deterministic path is fully covered; the model-selection path is covered only by `_accept` unit tests against synthetic documents |
| SCV-SEC-07 | The vectors in §AE are covered by tests; no systematic adversarial sweep was run |
| SCV-QUALITY-05 | Docker stack not run on this build |
| SCV-VIZ-05 (partial) | Charts were inspected by screenshot; no human has reviewed every chart kind by eye |
| SCV-REPORT-08 (partial) | The DOCX was opened and read with `python-docx`; nobody has opened it in Word |
| Second-engineer adversarial review | Not performed as a separate exercise. An adversarial read of this module's own code during the build found two defects, recorded in §AC-2 |

---

## AJ-2. What was not built

One item of scope was not built, and it is a decision rather than a gap in
verification.

**Validation runs are not persisted.** Each run is computed on request and
returned; nothing is written to a database. A run is therefore reproducible
from its inputs — the model, the period and the calculation version, all of
which travel with every result — rather than retrievable from a store.

That is defensible for a deterministic engine: the same inputs give the same
numbers in any process at any hour (§N), so "re-run it" and "look it up" give
the same answer. It is not sufficient for a production model-risk function,
which needs to open the run a committee saw rather than a run that agrees with
it. A migration and a run store are the natural next piece of work, and this
report does not claim they exist.

---

## AK. Conditions on the recommendation

READY FOR USER ACCEPTANCE TESTING, provided the acceptance team knows:

1. **Every figure is synthetic.** No row describes a real business, applicant,
   facility or default, and 26 of the 90 SME variables are proxies for
   authorities the product is not connected to.
2. **A full run takes a minute.** That is bootstrap resampling, not a hang.
3. **The AI path is deterministic here.** With no provider configured, the
   reader resolves questions on its own. Behaviour with a live provider is
   guarded by `_accept` but has not been exercised against a real one.
4. **Validation runs are not persisted.** Each is computed on request; see
   §AJ-2.
5. **The report is a draft.** It says so on its cover and in its document
   control. Nobody should sign it without reading it.

---

## AL. What would change the recommendation to NOT READY

Stated in advance so the bar is not moved later:

- Any material gate turning FAIL.
- A figure appearing on screen that the engine did not compute.
- A refusal rendered in a way a reader could mistake for a pass.
- The word "compliant" appearing in any status vocabulary.
- A claim of a live connection to any named external authority.
- A validation opinion issued by the product rather than drafted for a person.

None of these is present at `90517f8`.

---

## AM. Branch discipline

| Constraint | Held |
|---|---|
| `claude/vigilant-darwin-eohyi1` untouched | Yes — not checked out, not merged, not rebased |
| `claude/playbook-committee-intelligence` untouched | Yes — same |
| All commits on `claude/scorecard-validation-intelligence` | Yes — 14 commits, no other branch touched |
| No force-push, no history rewrite | Yes — every push fast-forward |
| Nothing merged to `main` | Yes — no merge command issued |
| No pull request opened | Yes — none requested |
| No environment-specific trust material committed | Yes — no CA certificate, no `.env`, no absolute path in a committed file |
