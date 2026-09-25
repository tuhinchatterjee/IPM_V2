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

**The scenario engine is built and cannot be driven from a chat turn.**

785 tests pass over cohort freezing, rule compilation, previews,
confirmation hashes, Delta, user assumptions, sensitivities, mappings, two
emulators, the three-method run, the ledger, attribution and the charts.
Every piece is governed and reconciled.

None of it is reachable from a typed question, because a governed Python
step runs under `-I -S` from a temp directory with no `PYTHONPATH` and can
therefore import the standard library and nothing else. `import pandas` and
`from backend.cockpit_v4.scenario import run` both fail with
`ModuleNotFoundError` — measured, not inferred.

Closing it needs a protected-core change the current brief does not
authorise. `PROTECTED_CORE_INCOMPATIBILITY.md` §7 has the evidence, the two
options and the approval needed; **Option A**, one branch in
`execute_tool.py`, is the smaller change and the one this implementation
would propose.

**What works today without that change:** anything published as a relation.
Sensitivities, rating maps, score bands, the MEV registry and the model
cards are all ordinary `SELECT`s against the candidate release. That is why
they were published as data.

## 2. What the accepted application still is

Unchanged. This is the claim that matters most and it is checked three ways:

| Check | Result |
|---|---|
| `v4-saudi-corporate-20q-v4` fingerprint | `e37236d0f6d4e494…` — **unchanged** |
| `v4-saudi-retail-20m-v5` fingerprint | `a1e797dcc73236b7…` — **unchanged** |
| Full V4 regression, flags OFF | **4189 passed, 4 skipped** |
| Accepted browser journeys, real Chromium | **76/76 passed** |
| `protected_hashes.py --check` | 5 changed, **0 removed**, 25 added — every line explained |

**The protected core is NOT byte-identical.** Five files differ, each an
authorised flag-gated extension, each recorded with its exact diff in
`BASELINE_AND_EXTENSION_MAP.md`:

| File | Extension |
|---|---|
| `context.py` | `scenario_blocks()` and `scenario_packet()` |
| `schema.py` | `candidate_relations()` |
| `domains.py` | `current_release()` |
| `domain_resolver.py` | reads `current_release()` |
| `worker.py` | routes the thread context by kind; writes a confirmed scenario after settle |

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

### The Mac launcher: prepared, not installed

`scripts/whatif/START_ADVANCED_COCKPIT_WHATIF_CANDIDATE.command` exists with
its installation steps in its own header.
`/Users/tuhinchatterjee/Desktop/CreditProbe_Launchers` is not reachable from
this Linux container, so it has **not been copied there, not made executable
there, and not run**. The accepted launchers are unchanged; do not replace
them with this one.

## 10. Verification

```bash
cd /home/user/whatif_wt
COCKPIT_AGENTIC_V3_NAMESPACE=cockpit_v4 python -m pytest -o addopts="" -q \
    tests/cockpit_v4 tests/frontend        # 4189 passed, 4 skipped
python -m pytest -o addopts="" -q tests/cockpit_agentic
/root/.local/bin/ruff check backend/cockpit_v4 tests/cockpit_v4 scripts/whatif
python3 scripts/whatif/protected_hashes.py --check
python3 scripts/whatif/build_matrix.py
python3 scripts/whatif/build_sensitivities.py     # cards vs published release
python3 scripts/cockpit_v4/browser_evidence.py    # 76/76
```

## 11. Documents

| | |
|---|---|
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

## 12. The remaining ask

One decision, and it is the user's:

> **Authorise Option A in `PROTECTED_CORE_INCOMPATIBILITY.md` §7** — a
> single branch in `execute_tool.py` dispatching a `whatif_scenario` step to
> `scenario/run.py` — or say that the scenario engine should remain a
> library that is exercised by tests and scripts rather than by a reader.

Without it, P8's run, P9's results and P10's journeys stay what they are
today: correct, tested, reconciled, and unreachable from the product.
