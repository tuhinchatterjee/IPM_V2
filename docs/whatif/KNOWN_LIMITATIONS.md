# Known limitations

Everything this candidate does not do, in one place, with the reason. A
limitation stated here is one a reader can plan around; a limitation
discovered later is one that cost somebody a day.

> Every figure this candidate produces is measured on **generated books**.
> Nothing here is bank output, an accounting figure or observed economic
> history, and no model or sensitivity is bank-validated.

---

## 1. The scenario engine cannot be driven from a chat turn

**The largest limitation, and the one that stopped work.**

The engine is built, governed and tested: cohort freezing, rule
compilation, previews, confirmation hashes, Delta, user assumptions,
sensitivities, mappings, both emulators, the three-method run, the ledger,
attribution and the charts. 785 tests pass over it.

None of it is reachable from a typed question. A governed Python step runs
under `-I -S` from a temporary directory with no `PYTHONPATH`, so it can
import the standard library and nothing else — `import pandas` and
`from backend.cockpit_v4.scenario import run` both fail with
`ModuleNotFoundError`, measured directly against `pyrunner._spawn`. Closing
this needs a protected-core change that the current brief does not
authorise.

`PROTECTED_CORE_INCOMPATIBILITY.md` §7 has the evidence, the two options and
the approval needed. **Option A** — one branch in `execute_tool.py`
dispatching a `whatif_scenario` step to `scenario/run.py` — is the smaller
change and the one this implementation would propose.

**What still works today:** anything published as a **relation**. A
methodology question, a sensitivity, a rating map, a score band, a model
card metric and the MEV registry are all ordinary `SELECT`s against the
candidate release, and that is deliberate — it is why P5, P6 and P7 publish
their artifacts as data rather than as objects.

## 2. The Retail emulator missed a predeclared gate

G4, worst material-group WAPE: **38.02% against a 15% threshold**, on
`score_band = A` — 652 test observations carrying **0.15% of the test
period's ECL**.

The threshold has not been moved, the group has not been excluded and the
model has not been retuned. Method 2 on the Retail book returns its number
**with the failed gate named beside it**. `P7_FINDINGS.md` §2 records what
would be legitimate to do about it in a future model version and what would
not.

Corporate passed all four gates.

## 3. Neither emulator is a blend

Three components were offered per book and the weight fit put everything on
one: XGBoost on Corporate, LightGBM on Retail. Both model cards say
"SINGLE-MODEL RESULT" in those words. The additive component scored 32%
(Corporate) and 182% (Retail) fold WAPE against 3–10% for the boosters — an
additive spline basis cannot represent a product of variables, which is what
this target is.

## 4. There is no tornado chart

`BarChart` computes `max = Math.max(high, 0)` and `width = abs(value) / max`,
so −400 and +400 draw the same rectangle on the same side
(`visuals.tsx:245-253`, server SVG identically at `export.py:594-601`). A
signed driver ranking through it would show every driver pointing one way.

`results.tornado_substitute()` returns a waterfall whose caption says the
requested form is unavailable and why, plus a signed table that keeps both
the ordering and the direction. It is not called a tornado.

## 5. There is no XLSX export, and no offline workbook was built

cockpit-v4 exports Markdown, CSV, SVG and a governance ZIP
(`routes.py:767, 853, 938, 983`). `openpyxl` is used only by the legacy
`backend/exports/`, which keys on integer run ids. §14.3's workbook is
**not built** — neither the route (a protected-core change) nor the offline
script.

## 6. Export reconciliation is not exercised

The existing CSV/Markdown/SVG/ZIP routes are unchanged and have **not** been
driven against a scenario result, because §1 means there is no scenario
result to drive them against. Formula-injection blocking is likewise not
re-tested for scenario content.

## 7. Two frozen ledgers cannot be compared

A compare-two-runs function is **not built**. Each ledger, run and summary
reconciles individually; a difference between two of them is not
implemented and is not claimed.

## 8. No browser journey was run against the candidate

J01–J14 are **BLOCKED — NOT RUN**, for the reason in §1 rather than for want
of tooling: `npm --prefix frontend install` succeeded and the **accepted**
browser suite runs **76/76 green** against real Chromium in this container.
The harness works; the path does not exist.

E20 (timeout, cancellation, repeated Run under a scenario turn) is blocked
for the same reason.

## 9. No live provider call was made

Every provider-facing test uses `ScriptedProvider` or the stub server and is
labelled MODEL MOCK. No credential is authorised here, so no journey
exercises a real model. Nothing in this deliverable claims a live
validation.

## 10. The Mac launcher was prepared, not installed

`scripts/whatif/START_ADVANCED_COCKPIT_WHATIF_CANDIDATE.command` exists with
its installation steps in its own header. `/Users/tuhinchatterjee/Desktop/
CreditProbe_Launchers` is not reachable from this Linux container, so the
file has **not been copied there, not made executable there, and not run**.
The accepted launchers are untouched.

## 11. Twenty periods is twenty periods

Every sensitivity in this deliverable is fitted on **20 distinct
macroeconomic observations**, 11 of them training. §7.3's own words: these
are *"conservative product defaults to make insufficiency visible, not
universal statistical or regulatory adequacy standards."* `SUPPORTED_ESTIMATE`
means "this book supports publishing this slope" and nothing more.

11 of 48 Corporate fits and 11 of 42 Retail fits are `DIAGNOSTIC_ONLY`, and a
diagnostic row is refused for automatic translation.

## 12. The degrees-of-freedom reading is a choice

§7.3 caps effective fitted degrees of freedom at
`max(1, floor((training − 5) / 5))`, which on 11–13 training periods is
**one**. A single-regressor ridge counting its intercept scores about 1.9 and
would fail — as would an intercept-only model at exactly 1.0. The ceiling is
therefore read as governing **predictor** complexity.

Under the stricter reading **every row of both artifacts would be
`DIAGNOSTIC_ONLY`**, the slopes and intervals would be identical, and no
macro scenario could translate automatically. Recorded in both
`SENSITIVITY_CARD_*.md`.

## 13. The stored artifacts cannot carry their own release's fingerprint

A sensitivity artifact and a model-metric table live **inside** the release
they describe, and a release fingerprint is taken over bytes that include
them. `source_fingerprint` is therefore a SHA-256 over the exact
period-level series the fit consumed, republished in the manifest notes as
`sensitivity_input_digest`; `trained_against_fingerprint` in
`artifacts/whatif/<book>/model_metric.json` is the fingerprint the model was
**fitted** on, which is the release before the metrics were added to it.

Staleness detection works on those digests plus `source_release_id`. It is
not the whole-release fingerprint and the documents say so.

## 14. SQL step artifacts store 100 rows

`execute_tool.py:767-769` stores `frame.head(preview_rows)`. Record-level
detail beyond 100 rows must come from a Python step — which §1 limits to the
standard library — or be declared capped with the full population count.

## 15. A cohort's cohort is not re-derivable from the thread body alone

`thread.py` stores the cohort id, its membership hash, its counts and its
baselines. It does **not** store the membership itself. Reopening a scenario
against the same release reuses the id; reopening it against a different one
drops the binding entirely and does not rebind.
