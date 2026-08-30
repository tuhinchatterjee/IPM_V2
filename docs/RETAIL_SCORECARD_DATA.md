# Retail Scorecard Data

The synthetic universe: what is generated, how, and what it must never be
called.

---

## 1. Origin

Every row, every dataset version and every catalogue entry carries
`origin = SYNTHETIC_DEMO`.

It describes **no real customer, no real applicant and no real bank's book**,
and it is **not client data**. Nothing generated here may be presented as an
institution's own portfolio performance. A test asserts the marker on every
dataset, and the validation report carries the statement on its cover rather
than in a footnote.

---

## 2. Periods

| | |
|---|---|
| Development sample | 2022-01 to 2022-12 (out of time) |
| Validation months | 2023-01 to 2025-07 (31 months) |
| Performance horizon | 12 months |
| Outcomes observable to | 2026-01 |
| Matured months | 25 (2023-01 to 2025-01) |
| Open performance window | 6 (2025-02 to 2025-07) |

The development sample is **out of time** with respect to every validation
month. Fitting the binning on months that are also being validated is the same
mistake as recomputing Weight of Evidence on the validation month, one step
earlier — and a critical check asserts the two sets do not overlap.

The six open months are the point rather than an accident. See
`RETAIL_SCORECARD_VALIDATION.md` §2.

---

## 3. Volumes

| | |
|---|---|
| Application rows per month | 12,000–15,000 |
| Behavioral accounts per month | 19,000 |
| Development population | 108,000 rows, 6,103 bads |
| Total scored rows | ~589,000 |

The behavioural side is a **panel**: the same accounts recur month to month,
so an account's history is coherent rather than redrawn.

---

## 4. Domains and families

Two governed domains, seven families each, registered in the Data Builder
catalogue.

**Retail Application Scorecard** — application-time scoring: the population
scored at the point of decision, the approved specification, and the
twelve-month outcomes those decisions produced.

**Retail Behavioral Scorecard** — monthly scoring of the live book: account
snapshots, the approved specification, and the twelve-month outcomes that
followed each snapshot.

Families (each domain):

1. Development reference
2. Monthly validation
3. Model specification
4. WoE / binning specification
5. Outcomes
6. Overrides / decisions *(application)* · Account snapshots *(behavioural)*
7. Data quality

One relationship between the two domains is declared **FORBIDDEN**: joining
an application cohort to a behavioural snapshot produces a population that is
neither, and the catalogue says so rather than leaving it to judgement.

---

## 5. Variables

| | Application | Behavioral |
|---|---|---|
| In the dictionary | 29 | 33 |
| In the incumbent model | 6 | 6 |
| Not scoreable | 2 | 0 |

**Application incumbent:** `bureau_score`, `debt_burden_ratio`,
`employment_tenure_months`, `bureau_max_dpd_12m`, `bureau_enquiries_6m`,
`credit_card_utilisation`.

**Behavioral incumbent:** `max_dpd_6m`, `utilisation_pct`,
`average_payment_ratio_3m`, `bureau_score_latest`, `missed_payment_count_6m`,
`months_on_book`.

`applicant_age` and `marital_status` are in the dictionary for **fairness
monitoring only** and are marked not scoreable. An equation referencing one is
refused by `equation.validate()` — the tag is a control, not a comment.

---

## 6. The default definition

Reproduced in full in every report, because it is what every outcome figure
counts.

| Element | Value |
|---|---|
| Trigger | 90 days past due, or a write-off or default flag, whichever is earlier |
| DPD threshold | 90 days |
| Performance window | 12 months |
| Write-off | Treated as a default |
| Distressed restructure | A default event at the restructure date |
| Cure | Below 90 DPD for three consecutive months; not counted as a default for the cohort it cured in |
| Grain | Application: one outcome per application. Behavioral: one outcome per account per snapshot month |

---

## 7. Planted phenomena

The universe carries eleven named phenomena so the validation screens have
something real to find rather than noise: a bureau-score population shift, a
missing-data supply change on declared income, a segment whose default rate
diverges, a challenger that overtakes the incumbent partway through, and
others. Each is declared in `synthetic.MANIFEST` with what it should make
visible.

The manifest is **for tests and evaluations only**. It is not shown to live
planners before execution — a planner told in advance what it is meant to find
is not being evaluated on finding it.

---

## 8. Regenerating

```
.venv/bin/python scripts/build_retail_scorecards.py            # lake only
.venv/bin/python scripts/build_retail_scorecards.py --register # and registry
```

Deterministic: the same seed reproduces the same universe. `--register` needs
a database; the build itself does not, because generating the lake on a
machine with no PostgreSQL is a normal thing to do.
