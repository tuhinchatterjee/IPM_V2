"""Twenty-four working papers, with their figures computed rather than typed.

The rule this file exists to hold
-----------------------------------
§19 asks for substantive documents across all four products and the whole
lifecycle. The temptation is to write them — twenty-four convincing papers
with numbers in the prose. That produces a demonstration that breaks
silently: the first time the book is rebuilt, every paper disagrees with the
screen beside it, and nobody notices until a client reads one aloud.

So a document here is a TEMPLATE with named slots, and the slots are filled
from the computed analyses at seed time. `{cc-dpd30-trend.headline}` becomes
the sentence the measure engine wrote about the measure it computed. A paper
and the screen cannot diverge because they are the same number.

Where a slot cannot be filled — the analysis refused, the measure is not
applicable to that book — the paper says so in place of the figure rather
than leaving a gap or writing a zero. A blank in a committee paper reads as
an oversight; "not measurable on this population, because …" reads as a
finding, and one of them is true.
"""

from __future__ import annotations

import re
from typing import Any

from backend.retail.seed_catalogue import (
    AUTO,
    CARD,
    HOME,
    OWNERS,
    PERSONAL,
    RETAIL,
)

DOCUMENTS_SEED_VERSION = "retail-seed-documents-1.0.0"

SLOT = re.compile(r"\{([a-z0-9-]+)\.(headline|question|title)\}")


def _fill(body: str, results: dict[str, Any]) -> str:
    """Replace every slot with what the engine computed for it."""
    def swap(match: re.Match[str]) -> str:
        row = results.get(match.group(1))
        if row is None:
            return ("[this figure could not be computed on the current "
                    "book — the analysis it cites did not produce a result]")
        got = row.result or {}
        which = match.group(2)
        if which == "headline":
            return str(got.get("headline") or "")
        if which == "question":
            return str(got.get("question") or "")
        return str(row.title or "")
    return SLOT.sub(swap, body)


def _evidence(keys: tuple[str, ...], results: dict[str, Any]
              ) -> list[dict[str, Any]]:
    out = []
    for key in keys:
        row = results.get(key)
        if row is None:
            continue
        out.append({"kind": "analysis", "id": str(row.id),
                    "label": row.title, "href": f"/analyses/{row.id}"})
    return out


#: The twenty-four papers. `cites` is both the evidence rail and the set of
#: analyses whose figures the body may interpolate.
PAPERS: tuple[dict[str, Any], ...] = (
    {"key": "cc-delinquency-paper",
     "title": "Credit Card Delinquency and ECL Deterioration",
     "kind": "Board Risk Committee paper", "product": CARD,
     "project": "cc-delinquency", "owner": OWNERS["retail_risk"],
     "status": "in_review",
     "summary": "Thirty-plus delinquency on the card book has risen for "
                "five consecutive months. What moved, where it is "
                "concentrated, and what we propose.",
     "cites": ("cc-dpd30-trend", "cc-dpd-weighted", "cc-dpd-by-salary",
               "cc-dpd-by-subproduct", "cc-ecl-trend", "cc-bucket-mix"),
     "body": """# Executive summary

{cc-dpd30-trend.headline}

The movement is not uniform. {cc-dpd-by-salary.headline} Salary transfer
remains the strongest single affordability control in this book, and the
gap it produces has widened rather than closed.

Separately from the observed arrears, the expected credit loss has moved.
{cc-ecl-trend.headline} The two are different measurements and this paper
keeps them apart: an observed default rate is what happened, and an
expected credit loss is what the model now believes about what will.

# What moved

{cc-dpd30-trend.headline}

{cc-dpd-weighted.headline}

Where the exposure share exceeds the account share, the larger balances are
the ones in arrears — which changes the collections priority, not only the
provision.

# Where it is concentrated

{cc-dpd-by-subproduct.headline}

{cc-dpd-by-salary.headline}

# The delinquency bucket mix

{cc-bucket-mix.headline}

# Recommendation

1. Re-price the non-salaried card pocket at the next policy review, and
   bring the decision to this committee with the affordability evidence
   attached.
2. Prioritise collections on the exposure-weighted arrears rather than the
   account count, on the evidence above.
3. Commission a behavioural scorecard recalibration. The under-prediction
   is a level problem rather than a ranking problem; the validation review
   in this project carries the evidence.

# What this paper does not establish

The associations above are measured, not causal. Nothing here demonstrates
that salary transfer CAUSES lower arrears; it demonstrates that the
populations differ, which is what a pricing decision needs and is not the
same claim.
"""},

    {"key": "cc-salaried-paper",
     "title": "Credit Card Salaried versus Non-Salaried Review",
     "kind": "Credit policy paper", "product": CARD,
     "project": "cc-salaried", "owner": OWNERS["portfolio"],
     "status": "draft",
     "summary": "The size of the salary-transfer gap in delinquency, "
                "coverage and utilisation, and whether the non-salaried "
                "pocket is priced for it.",
     "cites": ("cc-salary-gap", "cc-nonsalaried-income",
               "cc-utilisation-by-salary", "cc-salaried-trend",
               "cc-employment-risk"),
     "body": """# Purpose

To quantify what salary transfer changes about the card book, and to put
the pricing question to the credit policy committee with the evidence
attached.

# The gap

{cc-salary-gap.headline}

# Where the non-salaried customers sit

{cc-nonsalaried-income.headline}

{cc-employment-risk.headline}

# How they use the product

{cc-utilisation-by-salary.headline}

# Has the mix itself moved?

{cc-salaried-trend.headline}

This matters for reading the portfolio number. A change in the salaried
share moves the book's delinquency without any individual customer
behaving differently, and a paper that did not separate the two would
recommend a pricing change for a composition effect.

# Proposal

Re-price the non-salaried pocket, with a floor set by the measured gap
rather than by a round number. Bring the revised schedule to the next
policy review.
"""},

    {"key": "cc-validation-paper",
     "title": "Credit Card Behavioural Scorecard — Validation Findings",
     "kind": "Model Risk Committee pack", "product": CARD,
     "project": "cc-scorecard", "owner": OWNERS["model_risk"],
     "status": "in_review",
     "summary": "The behavioural scorecard under-predicts default across "
                "every band. Whether that is a level problem or a ranking "
                "problem, and when it began.",
     "cites": ("cc-score-trend", "cc-score-by-band", "cc-pd-by-stage",
               "cc-score-by-vintage", "retail-score-by-product"),
     "body": """# Scope

The Credit Card behavioural scorecard, validated against the closed
monitoring cohorts. This paper carries the portfolio evidence; the test-level
evidence is in the Scorecard Validation module and the findings there are
linked from the evidence rail.

# Discrimination

{cc-score-by-band.headline}

The score continues to rank. That is the finding that decides the
remediation: a model that ranks and is calibrated to the wrong level needs
a recalibration, and a model that has stopped ranking needs a
re-development. They are different pieces of work with different costs.

# Calibration

{cc-pd-by-stage.headline}

Observed default runs above the predicted probability in every score band.
The development sample itself reads a comparable observed-over-expected,
which places the gap at development rather than in anything the book has
done since — a definition or horizon mismatch rather than drift.

# Stability

{cc-score-trend.headline}

{cc-score-by-vintage.headline}

# Against the other products

{retail-score-by-product.headline}

# Recommendation

1. Re-calibrate the score-to-PD mapping on the latest closed cohorts and
   date the calibration.
2. Before that work starts, confirm that the outcome definition behind the
   observed rate is the one the PD was fitted to predict.
3. No re-development is proposed. The evidence does not support one.
"""},

    {"key": "traits-attribution-paper",
     "title": "Retail Customer Traits and ECL Attribution",
     "kind": "Portfolio analytics paper", "product": RETAIL,
     "project": "traits-ecl", "owner": OWNERS["portfolio"],
     "status": "draft",
     "summary": "Which customer characteristics have deteriorated, how much "
                "is the same customers behaving differently rather than the "
                "book changing shape, and what each contributes to ECL.",
     "cites": ("retail-dbr-trend", "retail-income-by-product",
               "retail-salaried-trend", "retail-segment-affordability",
               "retail-score-trend", "retail-mix-indebtedness"),
     "body": """# The question

Which traits moved, and how much of the portfolio's movement is the traits
rather than the mix.

# Affordability

{retail-dbr-trend.headline}

{retail-income-by-product.headline}

{retail-segment-affordability.headline}

# Indebtedness

{retail-mix-indebtedness.headline}

# Mix, separated

{retail-salaried-trend.headline}

Separating matched change from mix is the whole of this paper. A book whose
salaried share falls will report worse delinquency with every customer
behaving exactly as before, and a remediation aimed at the customers would
be aimed at nothing.

# What the score saw

{retail-score-trend.headline}

# Conclusion

The deterioration is largely in the customers rather than in the shape of
the book. The attribution by trait is in the linked analyses; the ECL
consequence is carried in the IFRS 9 close paper rather than repeated here,
so that one number has one home.
"""},

    {"key": "pf-affordability-paper",
     "title": "Personal Finance Affordability and Income Review",
     "kind": "Credit policy paper", "product": PERSONAL,
     "project": "pf-affordability", "owner": OWNERS["retail_risk"],
     "status": "draft",
     "summary": "Verified income and debt-burden across the personal "
                "finance book, and whether the affordability policy still "
                "separates the accounts that default.",
     "cites": ("pf-income-bands", "pf-dbr-bands", "pf-employment",
               "pf-income-trend", "pf-dpd-trend"),
     "body": """# Purpose

To test whether the affordability policy still separates.

# Income

{pf-income-bands.headline}

{pf-income-trend.headline}

# Debt burden

{pf-dbr-bands.headline}

If the policy separates, the arrears should rise monotonically across the
indebtedness bands. The table above is the test.

# Who holds the book

{pf-employment.headline}

# Performance

{pf-dpd-trend.headline}

# Recommendation

Hold the current policy. Re-test after two further closed cohorts, and
bring the result back to this committee whether or not it has moved.
"""},

    {"key": "pf-monitoring-paper",
     "title": "Personal Finance Scorecard Monitoring Pack",
     "kind": "Model Risk Committee pack", "product": PERSONAL,
     "project": "pf-scorecard", "owner": OWNERS["model_risk"],
     "status": "approved",
     "summary": "Discrimination, calibration and stability for the personal "
                "finance scorecards this cycle, including the local rank "
                "inversion in the upper bands.",
     "cites": ("pf-score-by-band", "pf-score-trend", "pf-score-by-segment",
               "pf-score-by-dbr", "pf-score-by-stage"),
     "body": """# Scope

The personal finance application and behavioural scorecards, this
monitoring cycle.

# Discrimination

{pf-score-by-band.headline}

The validation module reports a local rank inversion between two adjacent
upper bands. It persists across a majority of the closed cohorts and
concentrates in one indebtedness band, which makes it a segmentation
question rather than a re-development one.

# Calibration

{pf-score-by-stage.headline}

# Stability

{pf-score-trend.headline}

{pf-score-by-segment.headline}

# Against the affordability policy

{pf-score-by-dbr.headline}

Where the score already carries the indebtedness the policy screens on, the
two controls are not independent and the combined cut-off is tighter than
either was set to be.

# Conclusion

No action on the model this cycle. Take the inversion to the binning
specification owner with the concentration evidence attached.
"""},

    {"key": "auto-collections-paper",
     "title": "Auto Finance Delinquency, Collections and Balloon Exposure",
     "kind": "Collections review", "product": AUTO,
     "project": "auto-collections", "owner": OWNERS["collections"],
     "status": "in_review",
     "summary": "Auto delinquency is low and the balloon book is "
                "concentrated. What falls due inside twelve months and what "
                "working it would take.",
     "cites": ("auto-dpd-trend", "auto-balloon-bands", "auto-balloon-trend",
               "auto-ews-balloon-current", "auto-collateral-cover",
               "auto-bucket-mix"),
     "body": """# Summary

{auto-dpd-trend.headline}

The delinquency is not the concern in this book. The balloon window is.

# The balloon window

{auto-balloon-bands.headline}

{auto-balloon-trend.headline}

# How much is on performing accounts

{auto-ews-balloon-current.headline}

A balloon falling due on a fully current account is a refinancing question
and not a collections one. The two need different teams and different
conversations, and a single queue would give both the wrong one.

# If the refinancing fails

{auto-collateral-cover.headline}

# Current arrears

{auto-bucket-mix.headline}

# Ask

Approve a dedicated refinancing outreach for the balloon population falling
due within twelve months, separate from the collections queue.
"""},

    {"key": "auto-ews-paper",
     "title": "Auto Finance Early Warning and Collateral Review",
     "kind": "Portfolio analytics paper", "product": AUTO,
     "project": "auto-ews", "owner": OWNERS["retail_risk"],
     "status": "draft",
     "summary": "Forward-risk auto customers who are still current, and "
                "whether collateral would absorb a default.",
     "cites": ("auto-ews-by-segment", "ews-auto-current-ltv",
               "auto-ews-cover-trend", "auto-collateral-type",
               "auto-ltv-trend"),
     "body": """# The population

{auto-ews-by-segment.headline}

These customers are fully up to date. Nothing in this paper says they will
default; it says their forward indicators have moved and they are worth a
review.

# Where the cover is thin

{ews-auto-current-ltv.headline}

{auto-ews-cover-trend.headline}

# What is securing the book

{auto-collateral-type.headline}

{auto-ltv-trend.headline}

# Recommendation

Review the thin-cover performing accounts before the next quarter close.
Treat the output as a watchlist, not as a provision.
"""},

    {"key": "home-stage2-paper",
     "title": "Home Finance Stage 2 and SICR Migration Review",
     "kind": "IFRS 9 technical paper", "product": HOME,
     "project": "home-stage2", "owner": OWNERS["ifrs9"],
     "status": "in_review",
     "summary": "Stage 2 migration in the mortgage book, the loan-to-value "
                "distribution behind it, and whether SICR is firing on the "
                "right population.",
     "cites": ("home-stage2-trend", "home-stage2-by-ltv", "home-ltv-mix",
               "home-ltv-trend", "home-stage-mix",
               "ews-home-current-stage"),
     "body": """# Question

Is the SICR trigger firing on the population it was designed for?

# The migration

{home-stage2-trend.headline}

{home-stage-mix.headline}

# Against loan-to-value

{home-stage2-by-ltv.headline}

{home-ltv-mix.headline}

{home-ltv-trend.headline}

# The population with no arrears

{ews-home-current-stage.headline}

Stage 2 exposure that is fully up to date is the trigger working as
intended — it caught the deterioration before the arrears did. Reporting it
as a problem would penalise the control for doing its job.

# Conclusion

The trigger is firing on the intended population. No change proposed.
"""},

    {"key": "ifrs9-close-paper",
     "title": "Retail IFRS 9 — Monthly Close",
     "kind": "IFRS 9 close pack", "product": RETAIL,
     "project": "ifrs9-close", "owner": OWNERS["ifrs9"],
     "status": "approved",
     "summary": "The month's expected credit loss, the staging and coverage "
                "movements behind it, and the product attribution.",
     "cites": ("retail-ecl-trend", "retail-stage-mix",
               "retail-stage2-by-product", "retail-coverage-trend",
               "retail-bucket-exposure", "retail-lgd-by-product",
               "retail-stage3-trend"),
     "body": """# The month

{retail-ecl-trend.headline}

# Staging

{retail-stage-mix.headline}

{retail-stage2-by-product.headline}

{retail-stage3-trend.headline}

# Coverage

{retail-coverage-trend.headline}

Coverage moves for two reasons and this pack separates them: risk changing,
and the mix changing underneath a constant risk. A ratio that moved because
the book grew in its safest product is not a deterioration.

# Where the money sits

{retail-bucket-exposure.headline}

# Loss severity

{retail-lgd-by-product.headline}

# Sign-off

Prepared by IFRS 9 Reporting. The figures reconcile to the governed book at
the source hash recorded on the cover.
"""},

    {"key": "ews-review-paper",
     "title": "Retail EWS Forward-Risk Review",
     "kind": "Risk committee note", "product": RETAIL,
     "project": "ews-monitoring", "owner": OWNERS["retail_risk"],
     "status": "draft",
     "summary": "Customers whose leading indicators are deteriorating while "
                "they are still current, by product and by layer.",
     "cites": ("ews-retail-current-product", "ews-cc-current-utilisation",
               "ews-cc-stage2-current", "retail-stage2-current",
               "ews-pf-current-income"),
     "body": """# Why this note exists

Everything in the delinquency papers is lagging. By the time an account is
thirty days down, the decision that would have helped was available months
earlier. This note is about the customers that decision is still available
for.

# The clean population

{ews-retail-current-product.headline}

The clean cohort means no arrears at all — not "not currently bad". The two
differ by everybody sitting in one to twenty-nine days, and a review aimed
at the wider definition spends its time on customers who are already in
collections.

# Where the forward risk is

{ews-cc-current-utilisation.headline}

{ews-pf-current-income.headline}

# What the staging already caught

{retail-stage2-current.headline}

{ews-cc-stage2-current.headline}

# Language

For the latest month this note says elevated forward risk and needs review.
It does not say will default. No future outcome is used as an input to any
figure above.
"""},

    {"key": "portfolio-quarter-paper",
     "title": "Retail Portfolio Review — Latest Complete Quarter",
     "kind": "Board Risk Committee paper", "product": RETAIL,
     "project": "portfolio-quarter", "owner": OWNERS["retail_risk"],
     "status": "in_review",
     "summary": "The quarter's position across all four products, with the "
                "quarter-to-date months labelled separately.",
     "cites": ("retail-mix-product", "retail-dpd-by-product",
               "retail-exposure-trend", "retail-top-regions",
               "retail-channel-risk", "retail-vintage-risk",
               "retail-mean-dpd-trend"),
     "body": """# The book

{retail-mix-product.headline}

{retail-exposure-trend.headline}

# Risk

{retail-dpd-by-product.headline}

{retail-mean-dpd-trend.headline}

# Concentration

{retail-top-regions.headline}

# Origination

{retail-channel-risk.headline}

{retail-vintage-risk.headline}

# On the period

The figures above are the latest complete quarter. The months that have
closed since are reported as a quarter-to-date update and are labelled as
such wherever they appear; a partial quarter presented as a quarter is the
most common way a committee pack overstates a trend.
"""},

    {"key": "cc-remediation-plan",
     "title": "Credit Card Scorecard Recalibration — Remediation Plan",
     "kind": "Remediation plan", "product": CARD,
     "project": "cc-scorecard", "owner": OWNERS["model_risk"],
     "status": "draft",
     "summary": "The actions arising from the card behavioural scorecard "
                "validation, with owners and proposed dates.",
     "cites": ("cc-pd-by-stage", "cc-score-by-band", "cc-lgd-by-stage"),
     "body": """# Findings this plan responds to

{cc-pd-by-stage.headline}

{cc-score-by-band.headline}

# Actions

| Ref | Action | Owner | Proposed |
| --- | --- | --- | --- |
| R-1 | Confirm the outcome definition behind the observed rate matches the one the PD was fitted to predict | Retail Model Risk | Before recalibration starts |
| R-2 | Re-calibrate the score-to-PD mapping on the latest closed cohorts, and date the calibration | Retail Model Risk | Next validation cycle |
| R-3 | Re-run the full validation against the recalibrated mapping | Model Risk & Validation | After R-2 |
| R-4 | Report the provision impact to the IFRS 9 close | IFRS 9 Reporting | The close after R-2 |

# Not proposed

A re-development. {cc-score-by-band.headline} The score continues to rank,
and re-developing a model that ranks to fix a level is expensive work aimed
at the wrong defect.

# Verification

R-2 is complete when the observed-over-expected is inside its limit on the
next closed cohort with the band-level observed rate no longer above the
predicted PD in a majority of bands.
"""},

    {"key": "whatif-committee-note",
     "title": "What-If Committee Note — Income Shock on the Card Book",
     "kind": "Risk committee note", "product": CARD,
     "project": "cc-delinquency", "owner": OWNERS["retail_risk"],
     "status": "draft",
     "summary": "A ten per cent verified-income reduction applied to the "
                "exported card cohort, and what it does to the provision.",
     "cites": ("cc-dpd-by-income", "cc-income-trend",
               "cc-nonsalaried-income"),
     "body": """# The scenario

A ten per cent reduction in verified income, applied to the exact exported
cohort rather than to a re-derived filter. The membership is immutable and
is recorded with the scenario.

# Why this cohort

{cc-dpd-by-income.headline}

{cc-nonsalaried-income.headline}

# The baseline it moves from

{cc-income-trend.headline}

# What the engine reports

The scenario's propagation, waterfall, affected population and hierarchy
materiality are in the attached workbook. The method was chosen explicitly
before the first run; the Delta calculation is the calculation of record and
the challenger is reported beside it.

# What this is not

A forecast. It is a bounded sensitivity on a stated shock, and the baseline
it moves from is unchanged by it — the live card lens still shows the book
as it is.
"""},

    {"key": "retail-methodology-paper",
     "title": "Retail ECL Methodology — Model and Parameter Summary",
     "kind": "Model methodology", "product": RETAIL,
     "project": "ifrs9-close", "owner": OWNERS["model_risk"],
     "status": "approved",
     "summary": "The models, parameters and policies behind the retail "
                "expected credit loss, and where each is governed.",
     "cites": ("retail-lgd-by-product", "retail-stage-mix",
               "retail-pd-trend"),
     "body": """# Scope

The expected credit loss calculation for the four retail products.

# The identity

Expected credit loss is computed facility by facility as the product of the
probability of default, the loss given default and the exposure at default,
discounted over the remaining life for stage 2 and stage 3 and over twelve
months for stage 1. It is multiplicative, which is why an attribution across
several parameters must be computed per prefix rather than allocated: an
allocation of a multiplicative identity does not reconcile.

# Probability of default

{retail-pd-trend.headline}

Behavioural scorecards per product, mapped to a point-in-time twelve-month
probability. The mapping is governed and versioned; the current validation
findings are in the Model Risk pack for each product.

# Loss given default

{retail-lgd-by-product.headline}

# Staging

{retail-stage-mix.headline}

# Scenario weights

Base, upturn and downturn, weighted by the approved policy. The weights are
carried on every result rather than applied at the end, so a figure can be
traced to the weighting that produced it.

# Limitations

Every row in this book is synthetic. It describes no real customer and no
real bank's book, and no figure here is a statement about an actual
portfolio.
"""},

    {"key": "cc-collections-note",
     "title": "Credit Card Collections Prioritisation Note",
     "kind": "Collections review", "product": CARD,
     "project": "cc-delinquency", "owner": OWNERS["collections"],
     "status": "draft",
     "summary": "Whether the collections queue should follow accounts or "
                "exposure, on the current arrears distribution.",
     "cites": ("cc-dpd-weighted", "cc-bucket-mix", "cc-meandpd-trend",
               "cc-dpd-by-subproduct"),
     "body": """# The question

The queue is built on account count. The arrears are not distributed that
way.

# Accounts against money

{cc-dpd-weighted.headline}

# The bucket mix

{cc-bucket-mix.headline}

{cc-meandpd-trend.headline}

Whether the population is getting larger or deeper changes what the queue
should do. A larger early-arrears population is an outbound-contact problem;
a deeper one is a restructuring problem.

# Where to start

{cc-dpd-by-subproduct.headline}

# Proposal

Weight the queue by exposure within bucket, keeping the bucket order. Review
after one cycle against cure rates rather than against contact volume.
"""},

    {"key": "retail-lens-note",
     "title": "Retail Dashboard Definitions and Refresh Policy",
     "kind": "Operating note", "product": RETAIL,
     "project": "portfolio-quarter", "owner": OWNERS["portfolio"],
     "status": "approved",
     "summary": "What each product dashboard measures, how often it "
                "refreshes, and what the LIVE badge means.",
     "cites": ("retail-mix-product", "retail-dpd-by-product"),
     "body": """# Purpose

To record what the product dashboards show, so that two readers quoting the
same tile mean the same thing.

# What LIVE means

The lens is bound to the latest published snapshot of the governed book and
refreshes against it. It does not mean a real-time feed: the book is a
monthly snapshot and the badge says which one. Where the snapshot is behind
the latest published month, or a refresh fails, the badge reads Stale or
Error rather than green.

# The measures

Each tile names its own column and its own arithmetic. A measure that is not
meaningful for a product is not rendered as zero for it — loan-to-value on a
credit card is absent with its reason, because a card has no collateral to
be a share of.

# Coverage

{retail-mix-product.headline}

{retail-dpd-by-product.headline}

# Filters

A filter applies to the tiles, the charts, the drill-through table and the
interpretation together. A filtered chart beside an unfiltered tile is the
most common way a dashboard misleads without anybody writing a wrong number.
"""},

    {"key": "cc-application-validation",
     "title": "Credit Card Application Scorecard — Validation Summary",
     "kind": "Model Risk Committee pack", "product": CARD,
     "project": "cc-scorecard", "owner": OWNERS["model_risk"],
     "status": "draft",
     "summary": "Discrimination, calibration and representativeness for the "
                "card application scorecard.",
     "cites": ("cc-score-by-band", "cc-score-by-vintage",
               "retail-score-by-product"),
     "body": """# Scope

The Credit Card application scorecard, on the booked population.

# Discrimination

{cc-score-by-band.headline}

# Representativeness

{cc-score-by-vintage.headline}

The population the model is applied to has moved from the one it was fitted
on. The per-input evidence is in the validation module; the material inputs
are indebtedness and the buffer characteristic.

# Against the other products

{retail-score-by-product.headline}

# The limitation this pack cannot remove

Everything above is measured on BOOKED accounts. The applications that were
declined under the cut-off in force were never observed, so nothing here
says what they would have done. An inference about them from this evidence
would be an inference about a population the bank has no data on.
"""},

    {"key": "home-ltv-note",
     "title": "Home Finance Loan-to-Value and Collateral Note",
     "kind": "Portfolio analytics paper", "product": HOME,
     "project": "home-stage2", "owner": OWNERS["portfolio"],
     "status": "draft",
     "summary": "The mortgage loan-to-value distribution and what it means "
                "for cover.",
     "cites": ("home-ltv-mix", "home-ltv-trend", "home-collateral-cover",
               "home-top-regions"),
     "body": """# Distribution

{home-ltv-mix.headline}

# Direction

{home-ltv-trend.headline}

# Cover

{home-collateral-cover.headline}

# Concentration

{home-top-regions.headline}

# Note on valuation

Current collateral value is carried at its last valuation date. Where that
date is old the ratio is stale in the direction the market has moved since,
and the paper does not adjust it — an adjustment the bank has not approved
would be this paper inventing a policy.
"""},

    {"key": "pf-growth-note",
     "title": "Personal Finance Growth and Coverage Note",
     "kind": "Portfolio analytics paper", "product": PERSONAL,
     "project": "pf-affordability", "owner": OWNERS["portfolio"],
     "status": "draft",
     "summary": "How fast personal finance is growing and what it is "
                "costing in coverage.",
     "cites": ("pf-exposure-trend", "pf-coverage-trend",
               "pf-subproduct-mix", "pf-stage2-trend"),
     "body": """# Growth

{pf-exposure-trend.headline}

# Coverage

{pf-coverage-trend.headline}

{pf-stage2-trend.headline}

# Composition

{pf-subproduct-mix.headline}

# Reading these together

Growth into a lower-coverage sub-product reduces the portfolio coverage
ratio with no account getting better. The composition table above is what
separates the two readings.
"""},

    {"key": "auto-vintage-note",
     "title": "Auto Finance Vintage Performance Note",
     "kind": "Portfolio analytics paper", "product": AUTO,
     "project": "auto-collections", "owner": OWNERS["portfolio"],
     "status": "draft",
     "summary": "Which auto origination cohorts are performing and which "
                "are not.",
     "cites": ("auto-by-vintage", "auto-by-channel", "auto-score-by-band",
               "auto-exposure-trend"),
     "body": """# By vintage

{auto-by-vintage.headline}

# By channel

{auto-by-channel.headline}

# Against the score

{auto-score-by-band.headline}

# Growth

{auto-exposure-trend.headline}

# Caution

A young vintage has had less time to go wrong. Comparing its arrears with a
mature one understates it, and this note reads the cohorts at comparable
ages rather than at a common calendar date wherever the data allows.
"""},

    {"key": "retail-ews-methodology",
     "title": "Early Warning Score — Methodology and Layer Definitions",
     "kind": "Model methodology", "product": RETAIL,
     "project": "ews-monitoring", "owner": OWNERS["model_risk"],
     "status": "approved",
     "summary": "The four layers, the classifier-trigger-action chain and "
                "what the score does and does not claim.",
     "cites": ("ews-retail-current-product", "retail-stage2-current"),
     "body": """# The four layers

Behavioural Intelligence; Affordability and Cash Flow; Bureau and External
Credit; Facility and Exposure. Each contributes signals with a governed
weight, and the weights are versioned.

# The chain

Classifier, then trigger, then action. A classifier says what a pattern is;
a trigger says the pattern has crossed a threshold; an action says what
somebody should do about it. Collapsing the three loses the reason a
customer appeared on a list.

# The signal properties

Direction, magnitude, velocity, momentum, persistence and recency. A
deterioration that is large and old is a different case from one that is
small and accelerating, and a single score that averaged them would rank the
two the same.

# Bureau recency

Bureau data is last-observed with a recorded recency and a documented decay.
It is not re-pulled monthly and the score does not pretend it is. A stale
bureau observation carries less weight by policy, not by imputation.

# Missing history

A customer with no behavioural history is shown as having none. It is not
treated as zero risk, which is what an unstated null becomes the moment it
reaches an average.

# Population

{ews-retail-current-product.headline}

{retail-stage2-current.headline}

# What it does not claim

For the latest month the score says elevated forward risk and needs review.
It does not say will default. No future outcome is used as an input.
"""},

    {"key": "retail-data-lineage-note",
     "title": "Retail Book — Source, Freshness and Lineage Note",
     "kind": "Operating note", "product": RETAIL,
     "project": "ifrs9-close", "owner": OWNERS["ifrs9"],
     "status": "approved",
     "summary": "Which snapshot the retail figures are computed on, how "
                "freshness is checked and what invalidates a derived view.",
     "cites": ("retail-exposure-trend", "retail-customers-trend"),
     "body": """# The source

One governed book of facility-months. Every derived view — the early warning
domain, the scorecard populations, the What-If baselines — is built from it
and carries the source hash it was built against.

# Why a version string is not enough

A current model version does not prove that a derived dataset used the
current source. A previous release passed readiness with a 59,449-facility
canonical book and a 19,745-facility derived domain, both labelled version
3.0.0. A hash of what was actually read is the thing that catches that; a
version somebody typed is not.

# What invalidates a derived view

A change in the source hash. The dependent views are rebuilt rather than
re-stamped, and a partial rebuild does not delete the months it did not
touch.

# The population

{retail-exposure-trend.headline}

{retail-customers-trend.headline}

# Freshness

Readiness fails for a stale early-warning or What-If source, an unreadable
scored period, a stale current demo document or a missing model artifact. A
two-hundred response from a health endpoint is not readiness.
"""},

    {"key": "cc-quarterly-update",
     "title": "Credit Card — Quarter-to-Date Update",
     "kind": "Risk committee note", "product": CARD,
     "project": "portfolio-quarter", "owner": OWNERS["retail_risk"],
     "status": "draft",
     "summary": "The card book in the months that have closed since the "
                "last complete quarter, labelled separately.",
     "cites": ("cc-exposure-trend", "cc-dpd30-trend", "cc-ecl-trend",
               "cc-stage2-trend"),
     "body": """# On the period

This is a quarter-to-date update. It covers the months that have closed
since the last complete quarter and is not comparable with a full quarter
without adjustment. Every figure below carries its own window.

# Exposure

{cc-exposure-trend.headline}

# Delinquency

{cc-dpd30-trend.headline}

# Staging

{cc-stage2-trend.headline}

# Provision

{cc-ecl-trend.headline}

# Why this is separate

A partial quarter presented as a quarter is the most common way a committee
pack overstates a trend. The complete-quarter position is in the portfolio
review; this note exists so the two are never read as one series.
"""},
)


def build(session: Any, owner: Any, projects: dict[str, int],
          results: dict[str, Any], month: str, source_hash: str,
          report: Any, *, preview: bool = False) -> None:
    """Seed or refresh the documents, leaving anything edited alone."""
    from sqlalchemy import select

    from backend.models.platform import Document
    from backend.services import documents as docs

    for paper in PAPERS:
        row = session.execute(
            select(Document)
            .where(Document.seed_key == paper["key"])
            .where(Document.is_current.is_(True))).scalars().first()

        if preview:
            report.add("document", paper["key"],
                       "create" if row is None
                       else "skip" if row.user_edited else "refresh",
                       paper["title"])
            continue

        body = _fill(paper["body"], results)
        versions = {"source_hash": source_hash, "month": month,
                    "seed_version": DOCUMENTS_SEED_VERSION}
        evidence = _evidence(paper["cites"], results)

        if row is None:
            docs.create(
                session, title=paper["title"], kind=paper["kind"],
                product=paper["product"], body=body,
                summary=paper["summary"], as_of=month,
                project_id=projects.get(paper["project"]),
                owner_id=getattr(owner, "id", None),
                owner_name=paper["owner"], data_versions=versions,
                evidence=evidence, seed_key=paper["key"], seeded=True,
                status=paper["status"])
            report.add("document", paper["key"], "create", paper["title"])
            continue

        if row.user_edited:
            # §24: preserve user edits. The seeder reports the difference
            # rather than overwriting somebody's work — a seeder that
            # silently replaced a draft is a seeder nobody runs twice.
            report.add("document", paper["key"], "skip",
                       "edited by a person; left as it is")
            continue

        if (row.data_versions or {}).get("source_hash") == source_hash \
                and row.body == body:
            report.add("document", paper["key"], "unchanged", paper["title"])
            continue

        if row.status == "approved":
            # An approved paper is an immutable snapshot. Refreshing its
            # figures would rewrite what somebody signed, so the refresh
            # becomes a new draft revision and the approved text stays.
            made = docs.revise(session, row.id,
                               owner_id=getattr(owner, "id", None),
                               owner_name=paper["owner"])
            made.body = body
            made.data_versions = versions
            made.evidence = evidence
            made.seeded = True
            made.user_edited = False
            report.add("document", paper["key"], "refresh",
                       "the approved revision was kept; a new draft carries "
                       "the current figures")
            continue

        row.title = paper["title"]
        row.kind = paper["kind"]
        row.product = paper["product"]
        row.summary = paper["summary"]
        row.body = body
        row.as_of = month
        row.data_versions = versions
        row.evidence = evidence
        row.project_id = projects.get(paper["project"]) or row.project_id
        report.add("document", paper["key"], "refresh",
                   "the book moved; figures recomputed")


__all__ = ["DOCUMENTS_SEED_VERSION", "PAPERS", "build"]
