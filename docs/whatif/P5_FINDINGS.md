# P5 — what the sensitivity work found

Section 7 of `CreditProbe_Advanced_Cockpit_WhatIf_Master_Prompt_v1`. Three
findings are recorded here because each changed the code, and two of them
changed published numbers.

> Everything in this document is about a fit on **generated data**. Nothing
> here is a bank-validated sensitivity and the macro panel is not observed
> economic history.

---

## 1. The ridge penalty was graded in the factor's unit, not in evidence

**Found by** a diagnostic on noiseless data — `y = 0.8x + c` exactly — where
the fitted slope should be the shrunk truth and the resampled interval should
be degenerate. Neither held.

`ridge()` computed `β = Sxy / (Sxx + λ)` with `λ = 0.05` absolute. The twenty
factors are in their own native units: oil sits at 82 dollars a barrel, GDP
growth at 3.2 percent, and their first differences are two orders of magnitude
apart. A fixed 0.05 is negligible against one factor's sum of squares and
material against another's, so the estimator was shrinking factors **by their
unit**. That is the specific error the whole quantity algebra exists to
prevent, sitting inside the estimator that publishes the unit-explicit slope.

**Fixed** by making the penalty relative: `β = Sxy / (Sxx × (1 + λ))`, which
shrinks every factor by the same `1 / 1.05`. The unit-independence is asserted
directly — the same series measured in units a thousand times larger returns
the same slope after conversion, and the same effective degrees of freedom.

A side effect worth stating: `effective_df` is now the constant
`1 / (1 + λ) = 0.9524` for every single-factor fit. That is the honest
statement — one regressor is one regressor — and it removes a number that
previously varied for a reason that had nothing to do with the factor.

## 2. Published intervals excluded their own point estimates

**Found by** the same diagnostic, and visible in the first Corporate card:
MEV03's slope was `+0.2987` with a 95% interval of `−0.0555 to +0.1987`. An
interval that does not contain the estimate it describes is not an interval.

Same root cause. A resample of repeated contiguous blocks spans less of the
training range than the full window does, so its sum of squares is smaller and
an absolute penalty shrank it harder. Every interval came back attenuated,
systematically, in the direction that made the slopes look less certain than
the estimator believed them to be.

**Fixed** by the relative penalty. Every published row's point estimate now
lies inside its own interval, and
`test_the_resampled_interval_contains_its_own_point_estimate` fails if that
stops being true.

**The readiness verdicts did not change.** 37 `SUPPORTED_ESTIMATE` and 11
`DIAGNOSTIC_ONLY` on Corporate before the fix and after it. The correction was
not a route to more publishable rows, and it is recorded here rather than
silently absorbed for exactly that reason.

## 3. The interval was published in a different unit from the slope

`std_error`, `ci_low` and `ci_high` carried the model-space coefficient's
resampled quantiles while `native_derivative` beside them was in percentage
points per native unit. Two quantities in one row, which is section 5.1's own
failure mode.

**Fixed** by scaling the resampled slopes by `q(1−q) × 100` before taking the
quantiles — a positive constant, so the quantiles carry over directly and the
sign share is unchanged. The schema's field descriptions now say the unit.

---

## The degrees-of-freedom reading, restated

Section 7.3 caps *"effective fitted degrees of freedom"* at
`max(1, floor((training_periods − 5) / 5))`, which on thirteen training
periods is **one**.

A single-regressor ridge's standard trace is the slope term **plus one for the
intercept**, about 1.9. Under that reading the policy forbids fitting any
macro factor at all on a twenty-period book — and forbids the intercept-only
model too, at exactly 1.0. A ceiling written as "how much complexity does this
history support" cannot mean that, so **the budget is read as governing
predictor complexity and the intercept is not charged against it**.

Under the stricter reading every row of both artifacts would be
`DIAGNOSTIC_ONLY`, the published slopes and their intervals would be
character-for-character identical, and the only difference would be that no
macro scenario could translate automatically. That is recorded in both
`SENSITIVITY_CARD_*.md` files where a reader will find it, and it is the kind
of choice that should be visible rather than defaulted.

---

## What the artifacts actually say

| | Corporate | Retail |
|---|---|---|
| Factors carried | 16 of 20 | 14 of 20 |
| Fitted rows | 48 (16 × 3 parameters) | 42 (14 × 3) |
| `SUPPORTED_ESTIMATE` | 37 | 31 |
| `DIAGNOSTIC_ONLY` | 11 | 11 |
| `UNAVAILABLE` | 12 (4 factors × 3) | 18 (6 × 3) |
| Fixed cohort | 2,897 facilities | 6,019 accounts |
| Excluded, ever defaulted | 99 | 683 |
| Excluded, not in every period | 0 | 0 |
| Distinct macro observations | **20** | **20** |

Sixty rows per book, always: a factor the book does not carry gets an
`UNAVAILABLE` row with a reason, so "is there a sensitivity to oil in the
Retail book?" has an answer rather than a silence.

### The signs are the ones the generator put in

Every factor carries a `loading` saying which way it moves when conditions
worsen. A factor with a positive loading must come back with a positive PD
slope and one with a negative loading with a negative slope, and
`test_the_published_slopes_have_the_signs_the_book_was_built_with` asserts it
on every supported row in both books. That is the check that distinguishes
recovering a relationship from fitting noise, and it is only possible because
the book was generated macro-first.

### What is not established

* That any of these relationships holds in a real economy. The book is
  generated and the panel is generated.
* That sixteen marginal slopes are sixteen separable effects. They are not:
  variance inflation runs 1.37–2.79 against the other retained factors, the
  factors load on one shared cycle by construction, and `aggregate()` attaches
  that warning to every multi-factor sum it produces.
* That twelve to thirteen training periods make any of this bank-validated.
  Section 7.3's thresholds are, in its own words, *"conservative product
  defaults to make insufficiency visible, not universal statistical or
  regulatory adequacy standards."*

---

## Where the fit runs, and where it does not

`scripts/whatif/seed_candidate.py` fits during candidate preparation, in the
same process that publishes, so the artifact cannot describe different numbers
than the book it lives inside. `scripts/whatif/build_sensitivities.py` refits
and **compares row by row with the published release** before writing the
cards, so a card is evidence rather than description; it publishes nothing and
exits non-zero on a disagreement.

Nothing a chat turn reaches imports `estimate.py`, `panel.py` or `build.py`.
`test_nothing_a_chat_turn_reaches_imports_the_estimator` walks every module
under `backend/cockpit_v4` and fails if one appears. A methodology question is
a `SELECT` against a published relation.

## The fingerprint an artifact cannot carry

An artifact stored inside the release it describes cannot carry that release's
own fingerprint: the fingerprint is taken over the published bytes and the
artifact is some of those bytes. `source_fingerprint` is instead a SHA-256
over the exact period-level series the fit consumed — the cohort size, every
parameter aggregate and every factor value, in a canonical order. The release
publishes the same digest in its manifest notes as
`sensitivity_input_digest`, so the staleness check (S16) is a string
comparison against a manifest rather than a rescan of the book, and
`source_release_id` catches the cruder case of an artifact from another
release entirely.
