# Retail conversion: assumptions and limitations

> **Synthetic Saudi retail demonstration data — not ANB customer data or
> approved models.** Nothing below is validated, approved or audited.

---

## 1. Synthetic assumptions, and what they are not

| Area | Assumption | What it is NOT |
|---|---|---|
| Portfolio size | ~20,000 active facilities in August 2026 | Not an estimate of ANB's retail book |
| Product mix | 34% cards, 38% personal finance, 17% auto, 11% home | Not an observed Saudi or ANB mix |
| Income distribution | Lognormal by employment status, floored at SAR 3,500 | Not observed Saudi income data |
| Geography | Thirteen provinces, weighted toward Riyadh, Makkah and the Eastern Province | A plausible shape, not a branch network or a market share |
| 12-month default rate | ~3.3% on eligible matured cohorts | A demo calibration choice, not a market or ANB default rate |
| Scenario weights | base 0.60, upturn 0.20, downturn 0.20 | Not an IFRS 9 requirement and not ANB's weighting |
| Scenario multipliers | hazard 0.72 / 1.00 / 1.55 | Demo assumptions, not an estimated Saudi macro relationship |
| Staging thresholds | 30-DPD Stage 2, 90-DPD default, 3-month cure probation | Conservative illustrative choices, not a statement of IFRS 9 or SAMA requirements |
| Application cutoffs | 560 to 600 by product, 4% documented exception rate | Not ANB's cutoffs and not its delegation matrix |
| Scorecard coefficients and bins | Written down in full in the model registry | Not fitted to real data and not any real institution's scorecard |
| Score scale | 300–900, base 600 at 30:1 odds, 40 points to double the odds | A demonstration scale, not a bureau's range |
| Bureau data | "Synthetic bureau proxy", scale `SYNTH_BUREAU_PROXY_300_900` | **Not SIMAH.** No SIMAH score, range, report layout, schema or feed is replicated or claimed |
| Employers | Fifteen groups, every name beginning "Synthetic" | No real employer is named or implicated |
| Housing support | A synthetic programme flag | Names no real Saudi programme and states none of its rules |

## 2. Modelling choices worth knowing

- **Lifetime horizon cap.** Lifetime curves are evaluated to 120 months. A
  300-month home finance contract is not truncated silently: `ecl_horizon_months`
  records what each row actually used. The discounted tail beyond ten years is
  immaterial at these profit rates.
- **Behavioural score grain.** Facility level, recorded in `score_subject_grain`.
  A customer-level behavioural score is a valid alternative design; this one was
  chosen because the inputs (utilisation, DPD, payment ratio) are facility facts,
  and replicating one customer-level score across facilities with different
  behaviour would have been the less honest option.
- **Revolving expected life.** 30 months, configurable. A credit card is not
  assumed to have a fixed 12-month contractual life.
- **Warm-up.** Twelve months are simulated before the first published month so
  that a 3- or 6-month rolling feature at August 2024 is computed from real
  history. Warm-up months are never published, and a facility originated inside
  the window does not inherit history it did not have —
  `behaviour_history_months_available` says how much it actually has.
- **Product mix calibration.** The application mix is measured and inverted from
  each product's contractual survival and booking rate, because applications are
  not the book. This is a deterministic pre-pass with its own seed.

## 3. What this data cannot answer

- **Anything about declined applicants.** The canonical table holds BOOKED
  facilities. A lower cutoff cannot be evaluated at all, and no row is
  manufactured to make the chart work.
- **The next twelve months from August 2026.** The last published month has zero
  observed follow-up. A next-12-month Gini for it does not exist, and the product
  says so rather than inventing one.
- **Causality.** The employer-group and channel patterns are descriptive. A
  concentration of stress among one synthetic employer's customers is not
  evidence that the employer caused it.
- **Job loss.** Missed salary credits are evidence of income interruption.
  `job_loss_reported_flag` is a separate, rarer, explicitly-sourced field, and
  the two are never conflated in a generated explanation.

## 4. Regulatory and reference position

- The [SAMA Responsible Lending Principles for Individual Customers][R1] informed
  which affordability concepts exist (verified income, credit obligations,
  disposable income, documented creditworthiness). **No threshold in this
  installation is presented as a SAMA rule.** The Arabic governing text and its
  circulars are what actual compliance work would need.
- [IFRS 9][R2] and its [forward-looking information material][R3] informed the
  staging, horizon, revolving-life and scenario conventions. A demonstration
  engine is not a substitute for the standard or for a bank's own methodology.
- Orientation and the Gini/AUC relationship follow the
  [scikit-learn ROC-AUC documentation][R4]; the position that Brier loss is not a
  pure calibration measure follows the
  [probability calibration documentation][R5].
- [ANB's personal-banking site][R7] was used only as context for which product
  categories a Saudi retail bank offers. It is not evidence of ANB's portfolio
  distributions, scorecard inputs or policies.

[R1]: https://rulebook.sama.gov.sa/en/responsible-lending-principles-individual-customers-0
[R2]: https://www.ifrs.org/issued-standards/list-of-standards/ifrs-9-financial-instruments/
[R3]: https://www.ifrs.org/news-and-events/news/2016/07/25-webcast-on-ifrs-9/
[R4]: https://scikit-learn.org/stable/modules/generated/sklearn.metrics.roc_auc_score.html
[R5]: https://scikit-learn.org/stable/modules/calibration.html
[R7]: https://anb.com.sa/web/anb
