"""
"What needs my attention this month?", constituted from the retail book.

The failure this exists for
----------------------------
    "What needs my attention in the retail portfolio this month?"

is the first question anybody asks this product, and it was answered:

    CreditProbe has no governed data about what that asks for. It answers from
    the figures a steward has published — exposure, impairment, ratings,
    delinquency, covenants — and it holds nothing that measures this.

Two things were wrong with that. The list of what it answers from named
ratings and covenants, which are corporate objects with nothing behind them
here. And the sentence is false: the three composites that answer exactly this
question — credit concern, deterioration, affordability stress — were declared
entirely over `portfolio_facility`, so under the retail profile every signal
was missing and each composite degraded to nothing at all.

What a composite is
--------------------
Not a score and not a model. Each signal is a threshold on a published column,
written here in the open, and the answer is a COUNT of how many fired — breadth
of evidence, arithmetic a credit officer can check by eye against the columns
beside it. A weighted score would need weights, weights would need an owner,
and an unowned weight in the middle of a credit answer is the thing this
codebase spends most of its governance preventing.

What is deliberately absent
-----------------------------
A retail customer has no covenant, no debt-service coverage ratio and no
internal rating, so those three slots are not refilled with retail-sounding
substitutes. What replaces them is what a retail credit officer actually looks
at: whether the salary arrived, whether the instalment was paid, how much of
the limit is drawn, and what the bureau says about the obligations this bank
cannot see.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# ABOVE is `field >= value`, not `field > value`.
#
# Written here because getting it wrong is silent and total: `dpd ABOVE 0`
# reads as "days past due of zero or more", which every facility in the book
# satisfies, and the answer came back "6,301 of its 6,301 customers show at
# least one of 8 signals" — a hundred per cent of every sector, in a sentence
# nobody would believe and nobody could disprove without opening the table.
# Every threshold below is the INCLUSIVE one the label describes.
# ---------------------------------------------------------------------------

from typing import Any

#: The one governed book. Every signal below reads it.
BOOK = "retail_facility_month"


def composites(Composite: Any, Signal: Any, ABOVE: str, BELOW: str,
               TRUE: str) -> tuple[Any, ...]:
    """The three, built with the orchestration layer's own types.

    Built rather than imported so this module owns no copy of the shapes: a
    field added to `Composite` reaches these without a second edit.
    """
    affordability = Composite(
        key="affordability_stress",
        label="affordability stress",
        # The retail vocabulary for the same idea. A customer does not have a
        # liquidity squeeze; they run out of money before the end of the
        # month.
        pattern=(
            r"afford\w*(?:\s+\w+){0,2}?\s*(?:stress|pressur\w*|problem\w*|"
            r"trouble|strain|difficult\w*|concern\w*|risk)"
            r"|(?:stress|squeez\w*|pressur\w*|strain)\s+(?:on|in|of)\s+"
            r"(?:their\s+)?(?:afford\w*|income|budget|cash)"
            r"|(?:run\w*|going|getting)\s+(?:short|out)\s+of\s+(?:cash|money)"
            r"|short\s+of\s+(?:cash|money)"
            r"|cash\s+(?:crunch|squeez\w*|shortage|strain)"
            r"|(?:income|salary|cash)\s+(?:pressure|problem\w*|difficult\w*|"
            r"stress|shock)"
            r"|financial\s+(?:pressure|distress|strain)"
            r"|(?:cannot|can't|struggl\w+\s+to)\s+afford"),
        means=("The customers carrying the most governed evidence that the "
               "money is not there this month: a salary cycle missed, a "
               "buffer that has run out, an instalment missed, a debt burden "
               "above the affordability rule, or income that has fallen."),
        signals=(
            Signal(key="salary_missed", dimension="salary arrival",
                   label="A salary cycle missed in three months",
                   dataset=BOOK, field="salary_missed_cycle_count_3m",
                   test=ABOVE, value=1),
            Signal(key="salary_late", dimension="salary arrival",
                   label="Salary arriving six days late or more",
                   dataset=BOOK, field="salary_delay_days",
                   test=ABOVE, value=6),
            Signal(key="no_buffer", dimension="cash buffer",
                   label="Less than one month of instalment in the account",
                   dataset=BOOK, field="balance_buffer_months",
                   test=BELOW, value=1.0),
            Signal(key="stretched", dimension="affordability",
                   label="Debt burden above 55% of income",
                   dataset=BOOK, field="debt_burden_ratio",
                   test=ABOVE, value=0.55),
            Signal(key="income_fell", dimension="income",
                   label="Income down more than a tenth in three months",
                   dataset=BOOK, field="salary_change_3m_ratio",
                   test=BELOW, value=0.9),
            Signal(key="missed_payment", dimension="repayment",
                   label="A payment missed in three months",
                   dataset=BOOK, field="missed_payment_count_3m",
                   test=ABOVE, value=1),
        ),
        absent=("current-account balances outside this bank",
                "household expenditure", "undeclared obligations"),
    )

    deterioration = Composite(
        key="deterioration",
        label="deterioration",
        pattern=(
            r"\bdeteriorat\w+\b|\bweaken\w+\b|\bgetting\s+worse\b"
            r"|\bworsen\w+\b|\bgoing\s+the\s+wrong\s+way\b"
            r"|\bmoving\s+against\s+us\b|\bslipping\b"),
        means=("The customers whose position has MOVED in the wrong "
               "direction: delinquency worse than last month, a behavioural "
               "score falling, utilisation climbing, or a stage migration "
               "already recorded."),
        signals=(
            # The book carries the LEVEL this month and the level last
            # month, not the difference. A signal is a threshold on a
            # published column, so this one tests the worst-in-three-months
            # position rather than inventing a column to subtract into.
            Signal(key="recently_late", dimension="delinquency movement",
                   label="Late at some point in the last three months",
                   dataset=BOOK, field="max_dpd_3m", test=ABOVE, value=1),
            Signal(key="score_falling", dimension="behavioural score",
                   label="Behavioural score down more than twenty points",
                   dataset=BOOK, field="behavioural_score_change_3m",
                   test=BELOW, value=-20.0),
            Signal(key="utilisation_climbing", dimension="utilisation",
                   label="Utilisation up more than ten points in three months",
                   dataset=BOOK, field="utilisation_change_3m_pp",
                   test=ABOVE, value=10.0),
            Signal(key="sicr", dimension="IFRS 9 staging",
                   label="A significant increase in credit risk recorded",
                   dataset=BOOK, field="sicr_flag", test=TRUE),
            Signal(key="bureau_worse", dimension="bureau",
                   label="An adverse bureau record",
                   dataset=BOOK, field="bureau_adverse_flag", test=TRUE),
        ),
        absent=("behaviour on obligations at other banks between bureau "
                "refreshes",),
    )

    concern = Composite(
        key="credit_concern",
        label="credit concern",
        # "needs MY attention" — the possessive the corporate pattern did not
        # allow, which is how the most likely opening question in a
        # demonstration reached the "nothing to measure" refusal.
        pattern=(
            r"\b(?:real\s+)?(?:issue|problem|concern|worry|worrie)\w*\b"
            r"|\bwhich\s+(?:names?|ones?|customers?|borrowers?|clients?|"
            r"accounts?|facilit(?:y|ies))\b[^?]{0,30}\b(?:worry|worries|"
            r"concern\w*|trouble\w*|bother\w*)\b"
            r"|\b(?:requires?|requiring|needs?|needing|deserves?|deserving|"
            r"warrants?|warranted)\s+"
            r"(?:my\s+|our\s+|the\s+most\s+|most\s+|urgent\s+|"
            r"immediate\s+|closer\s+|closest\s+|your\s+){0,2}attention\b"
            r"|\bwhat\s+(?:should\s+)?(?:i|we)\s+(?:be\s+)?(?:look|worry|"
            r"focus)\w*\s+(?:at|on|about)\b"
            r"|\bworst\s+(?:names?|customers?|borrowers?|credits?|accounts?|"
            r"exposures?|offenders?|facilit(?:y|ies))\b"
            r"|\bmost\s+(?:at\s+risk|worrying|concerning|troubl\w+)\b"
            r"|\b(?:multiple|several|many|more\s+than\s+one|two\s+or\s+more|"
            r"combinations?\s+of|clusters?\s+of|overlapping|co-?occurring)\s+"
            r"(?:\w+\s+){0,2}?(?:warning\s+)?"
            r"(?:signals?|flags?|indicators?|triggers?|red\s+flags?|"
            r"early\s+warnings?)\b"),
        means=("The customers carrying the most governed evidence of credit "
               "difficulty at once: in arrears, a card drawn to its limit, a "
               "debt burden above the affordability rule, a salary that has "
               "stopped arriving, forbearance already granted, or a stage "
               "migration already recorded."),
        signals=(
            Signal(key="arrears", dimension="delinquency",
                   label="In arrears", dataset=BOOK, field="dpd",
                   test=ABOVE, value=1),
            Signal(key="seriously_late", dimension="serious delinquency",
                   label="Ninety days past due or more", dataset=BOOK,
                   field="dpd", test=ABOVE, value=90),
            Signal(key="at_the_limit", dimension="utilisation",
                   label="Drawn to 90% or more of the limit", dataset=BOOK,
                   field="utilisation_ratio", test=ABOVE, value=0.9),
            Signal(key="stretched", dimension="affordability",
                   label="Debt burden above 55% of income", dataset=BOOK,
                   field="debt_burden_ratio", test=ABOVE, value=0.55),
            Signal(key="salary_stopped", dimension="salary arrival",
                   label="A salary cycle missed in three months",
                   dataset=BOOK, field="salary_missed_cycle_count_3m",
                   test=ABOVE, value=1),
            Signal(key="forborne", dimension="forbearance",
                   label="Forbearance already granted", dataset=BOOK,
                   field="forbearance_flag", test=TRUE),
            Signal(key="impaired", dimension="credit impairment",
                   label="Classified credit-impaired", dataset=BOOK,
                   field="credit_impaired_flag", test=TRUE),
            Signal(key="stage_2_or_worse", dimension="IFRS 9 stage",
                   label="In Stage 2 or Stage 3", dataset=BOOK,
                   field="ifrs9_stage", test=ABOVE, value=2),
        ),
        absent=("obligations at other banks between bureau refreshes",
                "household expenditure", "employment the customer has not "
                "declared"),
    )

    # Order matters: `find` returns the FIRST match, and a question naming
    # affordability specifically wants that reading rather than the general
    # one. Deterioration sits between them because "which customers are
    # weakening?" asks what has GOT WORSE, a narrower claim that reads
    # movement columns rather than levels.
    return (affordability, deterioration, concern)


__all__ = ["BOOK", "composites"]
