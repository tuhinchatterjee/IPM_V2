# Revision 3 — status, on evidence

Branch `claude/funny-dirac-6n8f0o`. This is the Revision 3 result only. It does
not repeat the Revision 2 report; where a claim is unchanged from Revision 2 it
is named and pointed at, not restated.

Every figure below was produced by running the thing it describes.

## 1. What was asked, and what happened

| # | Priority | Outcome |
|---|---|---|
| 1 | Fix Customer 360 through the actual UI and complete the EWS → customer → facility/history → Back journey | **DONE.** C360-01…C360-10 pass in a browser. CP-10 is no longer BLOCKED |
| 2 | Verify the new retail What-If has not reduced or replaced required functionality | **DONE, with seven reductions named rather than waived.** Six defects found and fixed; all twelve advertised methodologies now reachable. `docs/WHATIF_RETAIL_FIDELITY_MAP.md` |
| 3 | Complete the retail-only content sweep | **DONE for everything reachable.** Five more corporate surfaces found and retired, including two the navigation itself offered. One OPEN item named: RFD-37 |
| 4 | Independently explain the SAR 0.52 residual without forcing it to zero or weakening tolerance | **DONE, and the previous explanation was wrong.** The residual is now exactly zero because the rebuild does the build's arithmetic; the tolerance is unchanged |
| 5 | Preserve deterministic chat testing as PASS; provider-backed AI NOT RUN | **HELD.** No provider was configured, requested or simulated |
| 6 | macOS execution NOT RUN until run on the actual Mac | **HELD.** This ran on Linux in a container. A read-only probe is prepared for the Mac; it has not been run there |

## 2. The status table §8 asks for

| Area | Status | Evidence |
|---|---|---|
| Customer 360 and its return journeys | **PASS** | `customer360.json` — 11 cases incl. Back to the same filtered list; `test_ret_customer_360.py` (13) |
| Cockpit deterministic browser conversations | **PASS** (carried forward, re-run) | `cockpit_chat.json` (19), `cockpit_journeys.json` (17) |
| What-If deterministic browser conversations | **PASS** | `whatif_chat.json` (14), `whatif_journeys.json` (12), `whatif_fidelity.json` (23) |
| Provider-backed Cockpit path | **NOT RUN** | no authorised provider credential exists; see §7 |
| Provider-backed What-If path | **NOT RUN** | as above |
| Scorecard / auditor evidence | **PASS** (carried forward) | `test_ret_026_033_scorecard.py`; scorecard evidence panel exercised in C360-05 |
| Required visible operations and return paths | **PASS**, reconciled by operation class | `coverage.json` — 13 operation classes, 0 uncovered, 33 routes opened |
| Retail content and EWS closeout | **PASS** | `retail_only.json` (29), `test_ret_retail_only_surfaces.py` (37), `docs/RETAIL_EWS_011_REVIEW.md` |
| Numeric reconciliation | **PASS** | `test_ret_whatif_reconciliation.py` (29) and §4 below |
| Authentication, role and ownership boundaries | **PASS** | `test_ret_ownership_boundaries.py` (18) |
| Local WHATIF_5318 source verification | **NOT RUN — external prerequisite** | probe prepared: `scripts/retail_uat/local_probe.py`; see §6 |
| Actual Mac setup and launch | **NOT RUN — external prerequisite** | see §7 |
| Metrics, Lenses and Playbook tiles | **OPEN — internal** | RFD-37: the metric library reads datasets this build does not contain |

Statuses mean what they say. **NOT RUN** is used only where the prerequisite is
outside this environment; **OPEN** only where the defect is ours.

## 3. What-If fidelity — the answer to priority 2

The screen lists twelve methodologies under "What this engine implements". That
list is generated from the engine's own contract, so it was always complete and
proved nothing: the composer is the only way in, and **one of the twelve could
not be reached by typing a sentence at all**. "Replay an application cutoff of
620 on personal finance" matched no shock pattern, was read as a scenario with
no shocks, and came back as the published book — a baseline, under the reader's
own question, indistinguishable on the page from an answer.

All twelve are now exercised through the route the launcher serves, one browser
case each (WF-04…WF-15), and each case asserts the answer was NOT the untouched
book.

Six defects were found this way and all six are fixed: RFD-38 to RFD-44 in
`docs/RETAIL_FUNCTIONAL_DEFECTS.md`.

**Nothing was silently dropped, and nothing is waived.** The old-to-current
mapping is `docs/WHATIF_RETAIL_FIDELITY_MAP.md`. Its §7 lists **seven
reductions from the corporate baseline that this pass did not close** — no
recent-runs list, no export of an unsaved run, no visible scenario-step editor,
no opening profile of the book, no stage-movement charts, no facility-level
drill-down, no deep-linkable saved scenario. None is claimed N/A. The capability
behind the step editor is not lost — a follow-up narrows the scenario on the
table and a replacement replaces rather than compounds, both proved in the
browser (WF-16…WF-18) — what is missing is the structural view of it.

Where a corporate capability is genuinely inapplicable it is justified
individually: rating movement and sector stress have no rating master scale and
no corporate sector taxonomy here; the Delta-versus-ML choice has no retail
model trained on this book, so the single methodology version is named on every
result rather than one being mislabelled as the other.

## 4. The SAR 0.52 residual — the answer to priority 4

**The population.** SAR 8,994,011.868 is the PERSONAL_LOAN population at
2026-08: 7,761 facilities. SAR 15,952,108.836 is the whole book at the same
month. These were never a discrepancy — they are two populations, and the
reconciliation now asserts both.

**The baseline measure.** `ecl_final_sar`, the carried loss allowance:
probability-weighted ECL plus management overlay. The overlay is 0.00, so final
equals weighted; the base-scenario ECL is a different quantity and is not the
baseline.

**Where the 0.002 grid comes from, derived rather than asserted.** The build
publishes each SCENARIO ECL rounded to the halala — that is the figure a reader
quotes — and then carries the weighted allowance as the exact weighted
combination of those published values. The weights are 0.6 / 0.2 / 0.2. A
weighted sum of multiples of 0.01 with those weights can only land on multiples
of gcd(0.6, 0.2, 0.2) × 0.01 = **0.002**. All 7,761 published rows sit exactly
on that grid; none is off it by more than 1×10⁻⁹.

**The cause was not what was reported.** "Continuous recalculation" was wrong:
the rebuild rounded the weighted and final allowance a second time to the
halala, which the build never does. Snapping a 0.002-grid value to the nearest
0.01 displaces it by at most 0.004 — and 0.004 is exactly the largest row
residual that was observed. The mechanism predicted the evidence rather than
being fitted to it.

**The net was not the error.** The row displacements summed to **|SAR 17.86|**
and cancelled down to **SAR −0.52** across 3,088 positive and 3,346 negative
rows, with 1,327 exact. A tolerance justified by the aggregate would have been
set thirty-four times too loose, and a real per-row defect of the same shape
would have passed it. This is the check §5 asked for, and it is why smallness
was never evidence for the explanation.

**The resolution.** The rebuild now performs the build's arithmetic. Every
per-scenario ECL already reproduced row for row — zero difference on all 7,761
rows — so removing the two spurious roundings leaves the neutral residual
**exactly zero**. Not forced: the same operations produce the same number.

**Verified across scope, not at one point.** 200 neutral runs — all 25 months ×
(whole book + 4 products + 3 stages) — every one at residual 0.0. Also exactly
zero for credit-impaired, stage 3, secured, forbearance and the 375 facilities
with one month or less of remaining life.

**The tolerance is unchanged and was not weakened.**
`PARITY_PER_FACILITY_SAR = 0.01` and `PARITY_RELATIVE_TOTAL = 1e-6` remain as a
guard so a future regression is reported rather than absorbed. A test asserts
they have not moved, and another reproduces the old SAR 0.52 by putting the
rounding back — the diagnosis, proved rather than argued.

**Exports.** The export writes the stored figures with no rounding, scaling or
formatting between the run and the file, and names the run id, dataset version,
snapshot date, reporting month, methodology, staging mode, population filters
and every shock. The screen rounds for display; the reconciliation file does
not. Asserted by test.

## 5. Retail-only content — the answer to priority 3

Five more corporate surfaces were reachable, and two of them the product itself
offered:

* The **CRO Portfolio Lens** was a card on the Lenses index — one click from a
  navigation item — rendering "the wholesale book", sector concentration and
  largest-obligor share.
* **Agent Operations** published Ratings & Financials, Covenant & Collateral and
  the Relationship Graph as ACTIVE teams. Every retained retail team also
  advertised a grant over those domains, so eight cards named them too. A
  seeded schedule woke one of them — and that name reached the screen from the
  **database**, so editing the seed alone would not have removed it.
* The **document library** shipped a Real Estate Sector Review.
* The **bootstrap** would, on any fresh deployment, install a Corporate IFRS 9
  lens, a Corporate Credit Committee, an IFRS 9 committee whose every tile names
  a `corporate.ifrs9.*` metric, a corporate model-redevelopment delivery plan
  and a shipping-review conversation. The bootstrap is where a retired surface
  comes back: nobody types its URL, the installer creates it.

All are retired as served content and retained as code — a corporate profile
still serves all thirteen agents, all three lenses, all three committees and
every corporate screen. The delivery plan was rewritten as a retail programme
that keeps every Planner feature it demonstrated: an overdue task, a blocked
task, an open decision, a closed decision, five milestones, eighteen
dependencies and a fortnight of updates.

**Proved by opening the screens.** `retail_only.json`: 29 cases, every one of
the 22 navigable routes opened and read, plus the CRO route and one document
workspace. Zero corporate phrases on any of them.

## 6. Coverage, reconciled by operation rather than by DOM node

§4 asked for the crawl to be reconciled with the 127-row matrix, and was
explicit that one row per DOM node is the wrong shape.
`scripts/retail_uat/coverage.py` reads the evidence the suites actually wrote
and maps thirteen required operation classes — open, ask, run, filter, drill,
save, reopen, compare, export, delete, return, refuse, recover — to the cases
that executed them.

**163 browser cases across 10 suites, 0 failed. 13 of 13 operation classes
covered, 0 uncovered. 33 routes opened.** Written to `coverage.json` so the
reconciliation can be checked rather than taken on trust.

What this does not claim: every control on every module was individually
pressed. Modules outside the retail demonstration path are opened and read, and
their write controls are covered by the equivalence class that exercises the
same operation elsewhere. Where a module has no calculable content at all, that
is RFD-37, and it is stated as OPEN rather than counted as covered.

## 7. What is NOT RUN, and exactly what would close it

**An authorised AI provider.** This installation reports "No AI provider is
configured". Every answer in every suite was read by the deterministic governed
semantic reader and every figure computed in the governed runtime. That is an
honest test of the production fallback and **it is not a live-provider pass**.
No key was requested, printed, committed or placed in evidence, and none was
simulated. To close it: configure an authorised credential on the machine that
will present, then re-run `cockpit_chat.py` and `whatif_chat.py` and record the
provider and model identifier, the invocation correlation id, the resolved
scope and the run id — enough to distinguish a real invocation from a silent
fallback.

**A launch on the user's Mac.** This ran on Linux in a container. Reproducing
the launcher's environment variables here does **not** prove a double-click
launch, and no claim in this document depends on one.
`launchers/retail/start-retail.command` was read, not executed on macOS.

**The WHATIF_5318 source checkpoint.** Still unresolved, and not dropped. The
token appears in no file at any branch or tag of this repository; the recovery
tag `recovered-sep8-whatif` (`0558f267`) is the only ref named for a What-If
installation, and it is an ancestor of this branch. Five things could not be
established from a container: the launcher file itself, `git rev-parse HEAD`
inside that worktree, whether it is dirty, whether the frontend it serves is a
live dev server or a stale bundle, and the paths it writes to.

`scripts/retail_uat/local_probe.py` answers all five and nothing else. It is
read-only by construction: it never runs, sources or opens a launcher; it
records variable NAMES from environment files and never a value; it changes no
Git state; it contacts no database; it signals no process; and it reads nothing
outside the directory it is given. On the Mac:

```
python3 scripts/retail_uat/local_probe.py /path/to/WHATIF_5318
```

It writes `whatif5318_probe.json` beside itself and prints a summary first.

## 8. Frozen builds and Git state

Nothing in this pass touched the frozen 5318 or 5308 installations: no file
outside this worktree was written, the retail backend runs on its own port, its
own database and its own lake, no freeze tag was created or moved, no branch
was rebased or reset, and nothing was merged.

## 9. Candidate freeze — proposed, not taken

This branch is proposed as a **candidate for local UAT**, on the following
reading, which is the only one the evidence supports:

* Every release gate that can be met in this environment is met, with browser
  evidence and a screenshot per case.
* Nothing is blocked by a defect in this product. One internal item is OPEN and
  named (RFD-37).
* It is **not presentation-accepted**, because the provider-backed path and the
  Mac launch are NOT RUN.
* It is **not proven to originate from the user's exact local build**, because
  the WHATIF_5318 source checkpoint is unresolved.

No freeze tag has been created or moved, and nothing has been merged. The next
verified local action is to run the read-only probe in §7 on the Mac that holds
WHATIF_5318, and send back the summary it prints.

## 10. What this is not

Not SAMA compliant, not ANB approved, not auditor certified, and not an
independent model validation. The data is synthetic, the scorecards are not any
real institution's models, and every threshold is a demonstration setting. No
claim here depends on a test that was not run, and every test that was not run
is named above.
