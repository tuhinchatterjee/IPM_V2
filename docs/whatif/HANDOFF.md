# What-If candidate — handoff

Branch `claude/advanced-cockpit-whatif-v1`, from the accepted baseline
`245c50e45786c6e0c866b281f9dd74da17d160b5`.

Implements P0–P11 of
`CreditProbe_Advanced_Cockpit_WhatIf_Master_Prompt_v1.docx`.

> **Everything measured here is measured on generated books.** The
> borrowers and customers do not exist, the economy did not happen, and
> every ECL figure comes from `reference_ecl.py`, a calculator written for
> this demonstration. Nothing in this deliverable is bank output, an
> accounting figure or observed economic history, and no model or
> sensitivity is bank-validated.

---

## 1. Read this first

**The scenario engine is reachable from a typed question, through one
authorised dispatch.** A reader asks in the Advanced Cockpit, the governed
execution path hands a typed `whatif_scenario` step to `scenario/bridge.py`,
the bridge calls the existing deterministic engine, and the result comes back
through the ordinary response path into the ordinary thread. Fourteen journeys
on each book prove it end to end against real Chromium.

**The sandbox is untouched.** A governed Python step still runs under `-I -S`
from a temporary directory with no `PYTHONPATH`, so it still imports the
standard library and nothing else: `import pandas` and
`from backend.cockpit_v4.scenario import run` both still fail with
`ModuleNotFoundError` inside it. The scenario path is not a Python escape
hatch — the operation is a closed typed shape, every field id comes from the
candidate field dictionary, every operator from a closed set, and no module
name, callable, path or Python expression is accepted from the model or the
user. The step's `code` is a restatement in words that is never parsed.

**Three protected files carry it**, each with its own authorisation and each
listed with its diff purpose in `BASELINE_AND_EXTENSION_MAP.md`:
`contracts.py` (the language must parse before the dispatch can be reached),
`execute_tool.py` (the dispatch), and one line of `routes.py` (without which
every follow-up turn in a candidate-pinned thread returned 409
`RELEASE_SUPERSEDED`, reproduced over HTTP). A fourth, `domain_resolver.py`,
corrects a defect in this work's own earlier edit.

**Both flags off restores the accepted behaviour, not merely approximates
it.** With neither book enabled nothing in the scenario package is imported by
the accepted runtime: the step language is not even accepted, the refusal is
the accepted sentence, the provider payload is byte-identical, the default
release is the accepted one, and the accepted browser suite is unchanged.

**One thing is not ready and says so.** The Retail emulator misses G4 — worst
material-group WAPE 34.36% against a predeclared 15% — so Method 2 is
unavailable on the Retail book: the answer names the gate, the method keeps its
row with empty cells rather than a zero, and no other model stands in. Delta
and User-defined work normally. Corporate passes all four gates and its
estimate is published beside Delta's.

**One thing was never run.** No provider credential is authorised here —
`service.credential_status()` reports MISSING for `COCKPIT_ANTHROPIC_API_KEY`,
the variable this product actually reads — so every journey uses a scripted
analyst and is labelled MODEL MOCK. Nothing is relabelled. The live-provider
gate is PREPARED and refuses to run without a credential rather than falling
back to the stub: `docs/whatif/LIVE_PROVIDER_UAT.md`,
`scripts/whatif/live_uat.py`, `tests/cockpit_v4/browser/whatif.live.mjs`
(L1–L8). Matrix row V01, marked BLOCKED — CREDENTIALS NOT AVAILABLE HERE.

**Three measured UI defects were fixed in this round**, each authorised
explicitly and each with its own matrix row: **U01** a money amount displayed
as a different amount (a Retail cohort read `SAR 2m → SAR 2m, change SAR 0m`);
**U02** an active run described as `Stopped: ACCEPTED` for its whole duration;
**U03** one unrenderable table taking down the thread page and the composer.
All three are display-layer fixes: no calculation, no analytical state machine
and no stored value changed. `KNOWN_LIMITATIONS.md` §16 has the before, the
fix and the measurement for each.

## 2. What the accepted application still is

Unchanged. This is the claim that matters most and it is checked three ways:

| Check | Result |
|---|---|
| `v4-saudi-corporate-20q-v4` fingerprint | `e37236d0f6d4e494…` — **unchanged** |
| `v4-saudi-retail-20m-v5` fingerprint | `a1e797dcc73236b7…` — **unchanged** |
| Full V4 + frontend regression, flags OFF | **4349 passed, 4 skipped, 0 failed** |
| Accepted browser journeys, real Chromium | **76/76 passed** |
| `protected_hashes.py --check` | 17 changed, **0 removed**, 25 added — every line explained |

**The protected core is NOT byte-identical.** Seventeen files differ, each
recorded with its exact diff in `BASELINE_AND_EXTENSION_MAP.md`. Eight carry
the flag-gated extension and the authorised bridge:

| File | Extension | Authorised as |
|---|---|---|
| `context.py` | `scenario_blocks()` and `scenario_packet()` | P3, P5b |
| `schema.py` | `candidate_relations()` | P5b |
| `domains.py` | `current_release()` | P5b |
| `domain_resolver.py` | reads `current_release()` | P5b |
| `worker.py` | routes the thread context by kind; writes a confirmed scenario after settle | P5b |
| `contracts.py` | the step language must parse before the dispatch is reached | B1 |
| `execute_tool.py` | the dispatch itself | B1 |
| `routes.py` | one line: the pinned release is read through `current_release()` | B1 |

Nine are the three authorised UI fixes, which are display-layer only:

| File | Fix |
|---|---|
| `display.py` | money precision chosen once per group from the smallest non-zero magnitude (U01) |
| `finalization.py` | publishes `column_precision` / `series_precision` and agrees one precision per unit across an answer's claims (U01) |
| `axis.py` | ticks take the group's precision, so an axis agrees with its cells (U01) |
| `export.py` | CSV and Markdown read the published precision (U01) |
| `precision.py` | delegates to `display.py` rather than holding a second opinion (U01) |
| `reducer.ts` | `terminal` latches only on a genuinely terminal state; working states get truthful copy (U02) |
| `thread-view.tsx` | imports the one `TERMINAL_RUN_STATES` list instead of keeping a second (U02) |
| `visuals.tsx` | each figure is wrapped in the existing `ErrorBoundary` (U03) |
| `reducer.test.ts` | six cases pinning U02 |

Each returns the accepted value with the flags off, and each import of the
candidate package sits inside a `try/ImportError` **after** the flag check.
`test_a04_*` asserts the file list, the guard and the ordering. The
allowlist was not broadened and no hash was regenerated.

`domain_resolver.py` is deliberately not among the importers: it calls
`domains.current_release()`, which is one protected-core dependency fewer
for the same behaviour.

## 3. Verified against the unchanged accepted books

* Both accepted releases are byte-identical after every candidate build.
* With both flags off: identical relations, identical default release,
  identical payload, and the full regression green.
* Enabling one book does not enable the other.
* The accepted launchers, the accepted default source and the accepted
  interpreter are untouched.

## 4. Verified against the labelled synthetic candidate

Two new releases, `v4-whatif-corporate-20q-s1` and
`v4-whatif-retail-20m-s1`, published through the same `lake.publish` and
`invariants.check` gate.

**The macro comes first and risk is generated from it with a lag**, so a
fitted sensitivity recovers something that is really there: portfolio ECL
and lagged unemployment correlate at **0.75**, Stage 2 migration peaks at
**21.7%** in the stress and returns to near zero, and every published slope
carries the sign its factor's loading was generated with.

| | Corporate | Retail |
|---|---|---|
| Sensitivity rows | 60 (20 factors × 3 parameters) | 60 |
| `SUPPORTED_ESTIMATE` | 37 of 48 fits | 31 of 42 |
| `DIAGNOSTIC_ONLY` | 11 | 11 |
| `UNAVAILABLE` | 12 (4 absent factors × 3) | 18 (6 × 3) |
| Emulator outcome | **single model** (XGBoost) | **single model** (LightGBM) |
| G1 WAPE ≤ 10% | **1.97%** PASS | **2.33%** PASS |
| G2 bias ≤ 2% | **1.47%** PASS | **0.87%** PASS |
| G3 per-period ≤ 5% | **2.53%** PASS | **1.33%** PASS |
| G4 material group ≤ 15% | **5.06%** PASS | **38.02% FAILED** |
| Naive `ead×pd×lgd` reference | 9.12% | 5.18% |

## 5. What FAILED, and stays failed

**Retail G4: 38.02% against a 15% threshold**, on `score_band = A` — 652
test observations carrying **0.15%** of the test period's ECL.

The threshold was not moved. The group was not excluded. The model was not
retuned. `ML_ACCEPTANCE_TARGETS.md` was committed before either model was
fitted and has not been edited. Method 2 on the Retail book returns its
number **with the failed gate named beside it**, and
`REQUIREMENT_TEST_MATRIX.md` marks M16 **PARTIAL**.

`P7_FINDINGS.md` §2 sets out what a future model version could legitimately
do about it and what would be dishonest.

## 6. Neither emulator is a blend

Three components per book; the weight fit put all of it on one. Both cards
say "SINGLE-MODEL RESULT … This is a `<component>` model, not a blend, and
is reported as one." The wording is generated from the weights, so it
cannot drift from what was fitted.

## 7. Not supported, not validated, not run

`KNOWN_LIMITATIONS.md` is the full list. The headlines:

* **Not supported:** end-to-end scenario execution from a chat turn (§1); a
  tornado chart (the bar renderer cannot draw a signed extent); an XLSX
  export route; the §14.3 offline workbook; comparing two frozen ledgers.
* **Not validated:** agreement with any bank's ECL engine — there is none
  here to compare against, and both model cards say so explicitly. No
  sensitivity is bank-validated; twenty periods is twenty periods.
* **Not run:** browser journeys J01–J14 and E20 against the candidate
  (**BLOCKED — NOT RUN**, for §1's reason, not for want of tooling — the
  accepted suite runs 76/76 green in this container); export reconciliation
  against a scenario result; any live provider call.

## 8. Acceptance

**136 acceptance IDs.** 115 COVERED, 3 PARTIAL, 17 BLOCKED, 1 NOT BUILT.

`REQUIREMENT_TEST_MATRIX.md` has one row per ID with the tests that prove
it. It is generated by `scripts/whatif/build_matrix.py`, which **exits
non-zero if it names a test that is not in the suite** — a guard that caught
29 wrong names the first time it ran, and one requirement (candidate build
determinism) with no test at all, which was then written.

**A pytest count is not a completion claim.** 785 passing tests say nothing
about whether S14 is met; only a named test against a named requirement
does.

## 9. Running it

```bash
# once — the candidate's own environment, layered on the accepted one
python3 -m venv --system-site-packages .venv-whatif
.venv-whatif/bin/pip install --ignore-installed -r requirements-whatif.txt

# once — build the data (about ten minutes in total)
.venv-whatif/bin/python scripts/whatif/seed_candidate.py --domain all
.venv-whatif/bin/python scripts/whatif/train_emulator.py --domain all
.venv-whatif/bin/python scripts/whatif/seed_candidate.py --domain all --overwrite
python3 scripts/whatif/build_sensitivities.py
python3 scripts/whatif/build_matrix.py

# start it, beside the accepted Cockpit
.venv-whatif/bin/python scripts/whatif/start_candidate.py
.venv-whatif/bin/python scripts/whatif/start_candidate.py --stop
```

The second `seed_candidate` run is not a mistake: the model metrics are
produced by training and published on the next seed, so the release carries
them.

The candidate takes **different ports** (from 8424 and 5424, and an occupied
port is stepped over rather than taken), a **different interpreter**, and a
**different state database**. The flags are set in the child's environment
only — not a `.env`, not an export — so an accepted process started
afterwards has them off. `--stop` stops only the pids this script recorded.

Started with the accepted interpreter it **refuses**, naming the libraries
it cannot import, rather than coming up with Method 2 silently unavailable.

### The Mac launchers: prepared, not installed

Two candidate launchers exist, both with their installation steps in their own
headers:

* `scripts/whatif/START_ADVANCED_COCKPIT_WHATIF_CANDIDATE.command` — the
  earlier one, which starts the candidate directly.
* `scripts/whatif/START_ADVANCEDCOCKPIT_WHATIF_UAT.command` — the UAT
  launcher. It runs `scripts/whatif/uat_preflight.py` as a GATE and starts
  nothing if the preflight fails: it checks the expected candidate revision
  and prints both hashes on a mismatch, the candidate interpreter and its
  pinned libraries, both releases published at their expected fingerprints,
  both emulator artifact sets and their gate verdicts (printing Retail's
  FAILED G4 without refusing, because that is the product's real state), and
  the credential as PRESENT or MISSING — the key itself is never read or
  printed. It then shows the Corporate and Retail candidate release state and
  hands over to `start_candidate.py`, whose `pick_port` steps past an occupied
  port and never kills its holder.

`/Users/tuhinchatterjee/Desktop/CreditProbe_Launchers` is not reachable from
this Linux container, so neither has been **copied there, made executable
there, or run**. The accepted launchers under `scripts/cockpit_v4/` are
unchanged — `git status` on that directory is empty — and the accepted
presentation launcher is not overwritten by either of these.

## 10. Verification

```bash
cd /home/user/whatif_wt
COCKPIT_AGENTIC_V3_NAMESPACE=cockpit_v4 python -m pytest -o addopts="" -q \
    tests/cockpit_v4 tests/frontend        # 4349 passed, 4 skipped
python -m pytest -o addopts="" -q tests/cockpit_agentic       # 564 passed
cd frontend && npm test && npx tsc --noEmit && cd ..          # 593 passed
/root/.local/bin/ruff check backend/cockpit_v4 tests/cockpit_v4 scripts/whatif
python3 scripts/whatif/protected_hashes.py --check    # 17 changed, 0 removed
python3 scripts/whatif/build_matrix.py
python3 scripts/whatif/build_sensitivities.py     # cards vs published release
python3 scripts/cockpit_v4/browser_evidence.py    # 76/76, the ACCEPTED suite
python3 scripts/whatif/browser_evidence.py --domain all   # J01-J15, 30/30
.venv-whatif/bin/python scripts/whatif/build_explanations.py --domain all
.venv-whatif/bin/python scripts/whatif/verify_artifacts.py --domain all
.venv-whatif/bin/python scripts/whatif/uat_preflight.py   # the UAT gate
.venv-whatif/bin/python scripts/whatif/live_uat.py        # refuses: no credential
```

The last one refits both emulators from scratch into a temporary directory and
compares every component hash, blend weight, gate verdict and measured value,
seed, library version and period split against what is published. It takes
about eight minutes and touches nothing published. A difference is reported, not
regenerated away.

## 11. Documents

| | |
|---|---|
| `FINAL_STATUS.md` | **the deliverable table**: requirement, status, evidence, commit, known limitation |
| `BASELINE_AND_EXTENSION_MAP.md` | every protected-file difference, with its diff and reason |
| `PROTECTED_CORE_INCOMPATIBILITY.md` | what could not be built without a core change; **§7 is the execution boundary** |
| `DATA_READINESS.md` | what each book has and does not have |
| `CANDIDATE_RELEASE.md` | the synthetic releases: provenance, formulas, determinism |
| `SENSITIVITY_CARD_CORPORATE.md` / `_RETAIL.md` | what was fitted, on what, and what it is not |
| `ML_ACCEPTANCE_TARGETS.md` | the gates, **committed before any model was fitted** |
| `MODEL_CARD_CORPORATE.md` / `_RETAIL.md` | provenance, splits, weights, metrics, subgroups, hashes |
| `P4`–`P7_FINDINGS.md` | what each phase found, including the defects it corrected |
| `REQUIREMENT_TEST_MATRIX.md` + `ACCEPTANCE_CASES.json` | one row per acceptance ID |
| `KNOWN_LIMITATIONS.md` | everything this candidate does not do |
| `PERFORMANCE_AND_BUDGETS.md` | measured build times, sizes and budgets |
| `LIVE_PROVIDER_UAT.md` | the live-provider gate: the eight conversations, what each must produce, the exact Mac commands, and why it is BLOCKED here |

## 12. The remaining ask

One decision, and it is the user's:

> **Authorise Option A in `PROTECTED_CORE_INCOMPATIBILITY.md` §7** — a
> single branch in `execute_tool.py` dispatching a `whatif_scenario` step to
> `scenario/run.py` — or say that the scenario engine should remain a
> library that is exercised by tests and scripts rather than by a reader.

Without it, P8's run, P9's results and P10's journeys stay what they are
today: correct, tested, reconciled, and unreachable from the product.
