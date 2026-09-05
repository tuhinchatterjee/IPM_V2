# Scorecard Validation Intelligence — Architecture

**Module:** Scorecard Validation Intelligence Cockpit
**Scope:** Retail Application Scorecard, Retail Behaviour Scorecard, Saudi SME Scorecard — and nothing else
**Branch:** `claude/scorecard-validation-intelligence`
**Status of this document:** current

---

## 1. What this module is, stated as a boundary

A model validation is not a dashboard with more charts on it. It is an
**independent** exercise, and independence is a property of what the
validator can and cannot reach, not a label on a page header.

So the architecture is organised around one claim that every layer has to
keep:

> The Scorecard Validation surface can read the three scorecard populations
> and nothing else. Every other surface can read everything else and not
> those three.

That is a two-directional restriction, and the second direction is the one
that is easy to get half right. Blocking the validator from the corporate
book is obvious. Blocking the general Cockpit from the record-level
scorecard populations is less obvious and matters more: those tables hold
the development population, every variable that went into the fit, and who
subsequently defaulted. A general chat surface that will answer "what is the
KS of the application scorecard?" has moved a model validation out of the
environment that governs it, without anybody deciding to.

`backend/scorecard/domains.py` is where that claim lives, and §4 is how it
is enforced.

---

## 2. Layers

```
                    ┌──────────────────────────────────────────┐
   conversation     │  validation/agent.py                     │
                    │  9 governed tools · invoke() · Clarify   │
                    └───────────────┬──────────────────────────┘
                                    │  tool call, never SQL
                    ┌───────────────▼──────────────────────────┐
   orchestration    │  validation/runner.py + extra.py         │
                    │  48 handlers · 5 refusal gates · run()   │
                    └───────┬───────────────────┬──────────────┘
                            │                   │
        ┌───────────────────▼───┐   ┌───────────▼──────────────┐
   defn │ validation/registry.py│   │ validation/models.py     │
        │ 48 Test definitions   │   │ 3 Models · Limit + source│
        └───────────────────────┘   └──────────────────────────┘
                            │
                    ┌───────▼──────────────────────────────────┐
   calculation      │  scorecard/metrics.py · binning.py       │
                    │  THE ONLY PLACE A STATISTIC IS COMPUTED  │
                    └───────┬──────────────────────────────────┘
                            │
                    ┌───────▼──────────────────────────────────┐
   data             │  parquet partitions · domains.py gate    │
                    └──────────────────────────────────────────┘

   reading up from results:
        validation/findings.py   → 7 cross-test patterns, ranked
        validation/regulatory.py → 9 CBUAE requirements, evidenced or not
        validation/report.py     → Report object → DOCX
```

The direction of every arrow is enforced by an import, not by convention.
`registry.py` imports nothing from `runner.py`; `metrics.py` imports nothing
from the validation package at all. That is what stops the registry
gradually becoming a second calculation engine — the failure mode that
produces two AUCs in one product that disagree in the fourth decimal and
nobody can say which is right.

### 2.1 File inventory

| File | Lines | Responsibility |
|---|---:|---|
| `validation/registry.py` | 736 | What each of the 48 tests *is*: category, requirement, limit source, CBUAE reference, chart |
| `validation/models.py` | 575 | The three models, their columns, their limits and where each limit came from |
| `validation/states.py` | 381 | Ten result states and their severity order |
| `validation/runner.py` | 1,090 | The five gates, population selection, partition cache, 21 handlers |
| `validation/extra.py` | 1,584 | The remaining 27 handlers |
| `validation/findings.py` | 889 | Cross-test patterns, severity, ranking, CBUAE citation derivation |
| `validation/regulatory.py` | 265 | Nine requirements, evidence coverage, the disclaimer |
| `validation/report.py` | 450 | Report assembly and DOCX rendering |
| `validation/agent.py` | 407 | Nine tools, domain refusal, clarification |
| `api/routers/scorecard_validation.py` | 440 | Eleven routes |
| `scorecard/sme/*` | 2,031 | The Saudi SME synthetic universe, catalogue and variables |

Tests: 1,602 lines across six files in `tests/scorecard/`, plus the bootstrap
tests appended to `tests/scorecard/test_metrics.py`.

---

## 3. The five refusal gates

Every test passes through the same ordered sequence before any arithmetic
happens. The order is not arbitrary — each gate answers a question that the
next one would otherwise answer wrongly.

| # | Gate | Refuses with | The question it settles |
|---|---|---|---|
| 1 | Authorisation | `NOT_AUTHORISED` | May this caller read this domain at all? |
| 2 | Applicability | `NOT_APPLICABLE` | Does this model even have the thing this test measures? |
| 3 | Availability | `UNAVAILABLE` | Is the column or reference actually present? |
| 4 | Maturity | `NOT_MATURED` | Has the outcome window closed on this cohort? |
| 5 | Sufficiency | `INSUFFICIENT_SAMPLE` | Are there enough observations and events to mean anything? |

Authorisation is first because a refusal for any other reason leaks the
answer to a question the caller was not permitted to ask. Applicability
precedes availability because "this scorecard produces no PD, so it has no
calibration" is a stronger and more useful statement than "the `pd` column is
missing". Maturity precedes sufficiency because an immature cohort is not a
small sample — it is a sample whose outcome has not happened yet, and
reporting it as a thin one invites somebody to widen the window and "fix" it.

### 3.1 The tenth state: `NO_LIMIT`

The original nine states had a defect that only appeared under test. A test
that computed a value but had no configured tolerance returned `PASS`,
because `PASS` was the default. VAR-WOE on the SME scorecard reported a real
monotonicity breach as green.

`NO_LIMIT` fixes it structurally: `_verdict` no longer has a default.

```python
limit = model.limit_for(test_id)
if limit is None:
    return states.NO_LIMIT, None, ""
return limit.verdict(value), limit.value, limit.source
```

Four tests have no defensible non-zero tolerance and so carry **structural**
limits rather than policy ones — `DATA-DUPLICATES`, `IMPL-REPLICATE`,
`VAR-SIGN`, `VAR-WOE` at zero, and the five `CONC-*` documentation tests at
one. A structural limit is sourced `STRUCTURAL`, distinct from the seeded
ones sourced `DEMO POLICY`, so a reader can tell "this is arithmetic" from
"this is a threshold somebody chose".

---

## 4. The domain boundary, enforced twice

Two independent backend gates. Defeating one is not enough.

**Gate 1 — Discovery.** `orchestration/context.py` builds the general
Cockpit's dataset universe and drops the restricted datasets. They cannot be
searched, autocompleted, suggested, matched to a subject, or picked up by a
planner scanning for a table with "score" in its name.

**Gate 2 — Execution.** `runtime/validation.py::validate` checks the dataset
of every SCAN in every plan, whatever produced it, before the plan compiles.
A dataset ID arriving by any other route — typed by a user, replayed from a
saved query, guessed by a model, or injected through the text of a document
the model was asked to summarise — arrives as a SCAN, and all four stop
there, before a single row is read.

The check sits in `validate` rather than in the `_scan` handler for two
reasons. Every SCAN is visible at that point without threading a permissions
argument through sixteen operation handlers that have no use for it; and a
refusal raised before any catalogue lookup cannot be turned into an oracle —
the message is identical whether the dataset exists or not.

Gate 2 is the security control. Gate 1 is a courtesy: it stops the model
proposing something that would then be refused, which is a better
conversation, but removing it would be a usability regression, not a hole.

`tests/corporate/test_scope_separation.py` pins the invariant by naming the
exclusions rather than subtracting an unexamined difference:

```python
known = {d.name for d in governed_context.all_datasets()}
published = {d.name for d in catalogue_of().all()}
restricted = set(domains.DATASET_DOMAIN)
assert known == published - restricted
```

An unnamed gap there would let the next accidental omission pass as a policy.

### 4.1 What is deliberately *not* restricted

The governed **aggregate** scorecard metrics that the Retail Risk Lens and
the Playbook committee packs already publish. Those are approved outputs — a
Gini for a named month, computed by the same kernel, reviewed and released.
They are not conversational access to the record-level population. Blocking
them would break two shipped surfaces to defend a boundary they never
crossed. The restriction is on **datasets**, not on published metrics.

---

## 5. Where the numbers come from

**No statistic is computed by a language model, and no statistic is computed
twice.**

`backend/scorecard/metrics.py` and `backend/scorecard/binning.py` are the
only modules that compute a validation statistic. The validation package
calls them; it does not reimplement them. When the bootstrap needed to be
fast, the fix was a new kernel *inside* `metrics.py`, not a faster copy of
the AUC inside `runner.py`.

### 5.1 The bootstrap, and why it is exact

`ROB-BOOTSTRAP` on the retail application scorecard took 96 seconds:
500 resamples × a full Mann-Whitney AUC over ~100k rows.

The observation that fixes it: the Mann-Whitney AUC depends on the data only
through the **count of goods and bads at each distinct score**. A bootstrap
resample of the rows is therefore *exactly* a multinomial draw over that
count table. So:

```python
def auc_from_counts(good: np.ndarray, bad: np.ndarray) -> float | None:
    goods, bads = float(good.sum()), float(bad.sum())
    if goods == 0 or bads == 0:
        return None
    below = np.concatenate([[0.0], np.cumsum(good)[:-1]])
    return float((bad * (below + good / 2.0)).sum() / (goods * bads))
```

96 s → 3.9 s. This is a **re-expression**, not an approximation, and a test
asserts exact equality against the row-level path rather than closeness.
`DISTINCT_SCORE_LIMIT = 50_000` falls back to the row-level path if a score
column is continuous enough that the count table stops being a compression.

### 5.2 The partition cache

Running all 48 tests re-read the same parquet partitions 288 times — 80
seconds of pure I/O. The cache is keyed on `mtime_ns` so a rebuilt partition
invalidates it, and hands out a copy so a handler cannot mutate a shared
frame:

```python
@lru_cache(maxsize=256)
def _read_partition(where: str, mtime_ns: int,
                    columns: tuple[str, ...]) -> pd.DataFrame:
    return pd.read_parquet(where, columns=list(columns) or None)

def _partition(where, mtime_ns, columns) -> pd.DataFrame:
    return _read_partition(where, mtime_ns, columns).copy()
```

80 s → 7 s.

### 5.3 The population window depends on the question

This is the subtlest design decision in the module, and it was wrong first.

A test that needs a realised outcome — discrimination, calibration — must run
on the **matured** window, because rows whose outcome window has not closed
have no outcome. A test that measures **drift** must run on the **current**
window, because the question is what the book looks like now.

Defaulting everything to the matured window measured the drift of the book as
it stood a year ago. On this build the difference is not academic: the same
characteristic reads **0.01** on the matured window and **0.49** on the
current one.

```python
pool = population(
    model, periods=periods, segment=segment,
    segment_field=segment_field,
    matured_only=test_registry.NEEDS_OUTCOME in test.requires)
```

The window is therefore derived from the test's own declared requirement,
not from a flag a handler author has to remember.

---

## 6. The findings engine

`findings.py` reads the 48 results and produces what the results do not say
individually. Seven patterns:

| Pattern | Reads | What it means |
|---|---|---|
| `not_what_was_approved` | IMPL-REPLICATE | Production does not match the specification |
| `aggregate_conceals_segment` | CAL-OE, SEG-CALIBRATION | Portfolio calibration inside limit, a segment outside it |
| `cut_off_not_believed` | USE-OVERRIDE-OUTCOME, USE-MATRIX | The cut-off is being overridden at its boundary |
| `definition_change` | STAB-CSI, VAR-IV | Drift that is a definition change, not a population shift |
| `borrowed_power` | DISC-AUC, VAR-IV | Passing on the strength of the other characteristics |
| `short_matured_window` | DATA-MATURITY | Most of the book has no outcome yet |
| `challenger_inside_the_noise` | CC-DISCRIMINATION, ROB-BOOTSTRAP | A challenger advantage inside the champion's own interval |

### 6.1 Severity ordering, and the rule that fixed it

Severity is computed as: **state → distance from limit → materiality →
evidence**, and then nothing changes it.

Getting that order wrong produced two real mis-reports:

* Materiality promoted an `UNAVAILABLE` to HIGH — a *missing* result
  presented as a serious one. Fixed: materiality only ever raises a `FAIL`
  or `WARNING`.
* Materiality then ran *after* the thin-evidence cap and undid it, restoring
  a CRITICAL finding resting on 40 defaults. Fixed by moving the evidence
  cap last, under one rule: **nothing may raise a severity after it has
  spoken.**

A `Finding` refuses to construct without evidence and without a verification
route (`__post_init__`), so a pattern cannot emit an assertion the reader
cannot check.

### 6.2 Citations are derived, never written

The findings originally cited MMS 10.5, 10.6, 10.8, 10.9, 10.10 and MMG
2.13, 2.14. **None of those appear in any registry entry.** They were
plausible and invented.

`_cite()` now derives every reference from the CBUAE references carried by
the tests the finding cites as evidence, and a test fails the build if a
citation does not resolve to a registry entry. A regulatory reference the
product cannot trace back to a specific test result is not a citation; it is
decoration that a reader will treat as authority.

---

## 7. The regulatory layer, and the word it must never say

`regulatory.py` maps nine CBUAE MMS/MMG requirements to the tests that
evidence them. Its four statuses are:

`EVIDENCED` · `PARTIALLY EVIDENCED` · `NOT EVIDENCED` · `NOT APPLICABLE`

There is deliberately no `COMPLIANT`. This module can say what evidence
exists and which requirement it speaks to. It cannot say that a supervisor
would accept it, and a status vocabulary that includes "compliant" will be
read as saying so regardless of any disclaimer beside it. `DISCLAIMER` states
this in the report itself.

The nine requirements: MMS 4.9, 9.4, 10.3, 10.4; MMG 2.8, 2.9, 2.10, 2.11,
3.9. Full text-to-test mapping is in
`docs/CBUAE_SCORECARD_VALIDATION_REPORT_MAPPING.md`.

---

## 8. The report

`report.build(model, results, *, generated_by, generated_at)` assembles a
`Report` out of the evidence; `report.docx(report)` renders it.

Four opinions: `USE_AS_IS`, `USE_WITH_CONDITIONS`,
`DO_NOT_USE_UNTIL_REMEDIATED`, `INSUFFICIENT_EVIDENCE`.

The fourth is not a courtesy option. `MINIMUM_MEASURED_SHARE = 0.5` — if
fewer than half the applicable tests reached a measured state, the report
says so and declines to opine. A validation opinion resting on twelve of
forty-eight results is not a cautious opinion; it is a different kind of
statement, and it needs a different word.

**Windows are derived, never assumed.** The report ID once read
`SCV-sme_champion-2023-01..2024-04..2025-12-…` because two different windows
were concatenated. `_windows(model)` now returns the matured window and the
latest data period separately, and the cover states both — because a reader
who does not know which window a Gini came from cannot use it.

---

## 9. The agent

Nine tools, reusing `backend.agentic.tools.Tool` rather than defining a
parallel tool type:

`scv_list_models` · `scv_list_tests` · `scv_explain_test` · `scv_periods` ·
`scv_run_test` · `scv_run_category` · `scv_findings` ·
`scv_regulatory_coverage` · `scv_draft_report`

Constraints, each of which is a refusal the agent cannot talk its way past:

* `invoke()` is the **only** entry point. There is no path from the agent to
  a database, a SQL string, or a Python expression.
* `_check()` rejects unknown parameters rather than ignoring them, so a
  hallucinated argument is an error and not a silently different query.
* `refuse_out_of_domain()` — a question about anything other than the three
  scorecards is refused, not answered approximately.
* `NO_TOOL_FOR` is published rather than hidden: the agent states what it
  cannot do.
* `Clarify` is raised when a required argument is missing, and
  `_which_scorecard()` takes priority over the generic message — "which
  scorecard?" is more useful than "PERIODS needs model_id".

The agent draft report says the word **draft**. It did not, once, and a draft
that does not announce itself as one is the exact artefact that ends up in a
committee pack.

---

## 10. Determinism

The SME synthetic universe seeded from `abs(hash(key))` produced a
**different universe in every process**. Python randomises string hashing per
interpreter; the seed was stable within one run and different in the next, so
two processes computing the same AUC disagreed and neither was wrong.

```python
def _rng(*parts: Any) -> np.random.Generator:
    key = "|".join(str(p) for p in parts).encode("utf-8")
    digest = hashlib.blake2b(key, digest_size=8).digest()
    seed = (MASTER_SEED + int.from_bytes(digest, "big")) % 2**32
    return np.random.default_rng(seed)
```

The bootstrap is seeded (`BOOTSTRAP_SEED = 20240101`) so an interval is
reproducible and a reviewer re-running it gets the same bounds.

Time is frozen or controlled in every time-dependent test, and cohorts are
anchored to an explicit reference date. The suite gives identical results
before and after midnight — an assertion that the newest calendar month is
matured passes at 23:59 and fails at 00:01, and a validation environment
whose answers change at midnight is not one anybody can rely on.

---

## 11. Verified numbers on the deterministic SME universe

Matured window 2023-01..2024-04 · 24,119 rows · 1,398 defaults.

| Test | Value |
|---|---|
| DISC-AUC | 0.6547 |
| DISC-GINI | 0.3094 |
| DISC-KS | 0.2241 |
| CAL-OE | 1.134 |
| ROB-BOOTSTRAP | 95% CI [0.6408, 0.6695] |
| STAB-CSI (worst) | `bank_credits_to_declared_sales` 1.0799 on 2025-12 |
| VAR-IV (retained) | `commercial_bureau_score_proxy` 0.71 |
| USE-OVERRIDE-OUTCOME | 6.29% vs 3.37% (1.86×) |
| SEG-DISCRIMINATION | 3 of 3 outside limit, worst MICRO |
| DATA-MATURITY | 16 of 36 periods |

These are reproducible: same numbers, any process, any hour.

---

## 12. What this architecture does not do

Stated so nobody has to discover it from a gap:

* It does not claim CBUAE compliance or regulatory approval. It reports
  evidence against named requirements. See §7.
* It does not connect to SIMAH, ZATCA, the Ministry of Commerce, GOSI, Qiwa,
  Mudad, Monsha'at, a credit bureau, or a core banking system. The SME
  universe carries **proxies** for those sources, named as proxies in
  `docs/SAUDI_SME_SCORECARD_DATA_DICTIONARY.md`, and a proxy presented as a
  live feed is the single most damaging misstatement this module could make.
* It does not let a model author or execute SQL or Python. See §9.
* It does not compute a statistic outside `metrics.py` / `binning.py`. See §5.
