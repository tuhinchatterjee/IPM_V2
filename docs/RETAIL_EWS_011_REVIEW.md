# RET-EWS-011 — affordability deterioration, reviewed and changed

Section 6 of the closeout asked for a semantics review of this rule and its
alert usability, with before-and-after counts over a scoped population. Here it
is, measured at 2026-08 over the published book: 14,251 customers, 19,745
facilities.

## What the rule said, and why it was unusable

    debt_burden_ratio - origination_debt_burden_ratio >= 0.15
    AND debt_burden_ratio >= 0.65                                  (v1.0.0)

It fired on **3,377 customers — 23.7% of the book — at HIGH severity.**

The rule was not broken. Every alert it raised was true: a customer whose debt
burden is 15 points above where it stood when their first facility was written,
and above 65% today, really is in that position. It is simply not a
**deterioration**. 4,347 customers in this book hold more than one facility, and
taking a second one raises the burden against origination by construction. The
rule was describing the book's ordinary lifecycle and calling it a warning.

A HIGH-severity alert on a quarter of the portfolio is not a warning list. It is
a list nobody opens.

## What it says now

    debt_burden_ratio - previous_month_debt_burden_ratio >= 0.05
    AND debt_burden_ratio >= 0.65                                  (v1.1.0)

It fires on **386 customers — 2.7% of the book.**

Origination has not been thrown away: it stays on the alert as context, so the
reader still sees where the burden started. What changed is the question the
rule asks — *has this customer's affordability got worse?* rather than *has this
customer borrowed since origination?*

## The counts, at 2026-08

Against **origination**, at every threshold pair worth considering:

| Rise required | Current DBR floor | Customers | Share of book |
|---|---|---|---|
| 0.15 | 0.65 | 3,377 | 23.7% |
| 0.15 | 0.75 | 2,558 | 17.9% |
| 0.15 | 0.80 | 2,178 | 15.3% |
| 0.20 | 0.65 | 3,219 | 22.6% |
| 0.25 | 0.65 | 3,020 | 21.2% |
| 0.30 | 0.65 | 2,801 | 19.7% |
| 0.30 | 0.80 | 1,946 | 13.7% |

Tightening the threshold does not rescue it: even a 30-point rise on an 80%
burden still names one customer in seven, because the comparison itself is
wrong.

Against the **prior month**:

| Rise required | Current DBR floor | Customers | Share of book |
|---|---|---|---|
| 0.02 | 0.65 | 409 | 2.9% |
| **0.05** | **0.65** | **386** | **2.7%** ← shipped |
| 0.10 | 0.65 | 312 | 2.2% |

The comparator changes the answer by an order of magnitude; the threshold
barely moves it. That is what tells you the comparator was the defect.

## How the comparator is produced

The published book carries a prior-month value for delinquency
(`previous_month_dpd`) and for the behavioural score
(`behavioural_score_previous_month`), and none for the debt burden. Rather than
rebuild twenty-five partitions to add one column — which would change every
figure already verified in this closeout — the comparator is attached where both
months are already readable:

    backend/retail/ews.with_prior_month(frame, previous)

and the rule reads it like any other field. It is declared in
`ews.DERIVED_FEATURES`, which is the one list allowed to name an input that is
not a column of the book, and the acceptance gate checks that
`with_prior_month` actually produces every name in it — so declaring a derived
input is not a way to smuggle a field nobody computes past the gate.

**A month with nothing before it raises no alert from this rule.** The first
published month has no deterioration to measure, and inventing one would be
exactly the defect this change removes. That is asserted, not assumed.

## What was not done

The better long-term fix is to publish the prior-month burden in the book
itself, alongside the two comparators already there. That is a generator change
and a lake rebuild, and it is recorded as remaining work rather than performed
here.

Total alert volume at 2026-08 moves from 5,566 to 5,952 — the affordability
rule's own 3,377 leave and 386 arrive; the difference is the other rules, which
are unchanged, now being visible in a list that is no longer dominated by one.
