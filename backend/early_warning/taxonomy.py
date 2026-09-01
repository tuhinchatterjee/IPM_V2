"""What CreditProbe watches for, and where each one lives. §20, §23, §25.

Not a score
-----------
`model.py` fits a probability and `factors.py` feeds it. This is the other
half, and §19 is explicit that Early Warning "is NOT one opaque score": a
credit officer asked to act on a number cannot argue with it, cannot explain
it to a committee, and cannot tell whether it moved because the borrower did
or because the model was refitted.

So this is a TAXONOMY. Each signal is a named condition, on a named governed
field, against a named threshold, in a named family. It fires or it does not,
and a borrower's page reads "utilisation rose 14 points and covenant headroom
fell below 10%" rather than "risk score 7.3".

The eight families are §20's, in its order
-------------------------------------------
    financial      revenue, margin, cash flow, working capital, net worth
    leverage       debt, interest burden, coverage, refinancing pressure
    liquidity      cash, buffers, utilisation, rollovers, payment stress
    behavioural    days past due, arrears, excesses, forbearance, restructure
    covenant       breach, near-breach, headroom movement, waivers
    collateral     coverage, valuation staleness, shortfall, false comfort
    rating         internal and external migration, staleness, divergence
    ifrs9          stage, SICR triggers, PD movement, ECL movement

Concentration and connected-counterparty signals (§20's last two groups) are
portfolio- and group-grain rather than borrower-grain, and live with the group
analytics that already compute them; putting them here would make a
per-borrower signal table that is sometimes about a group.

Every signal declares what it CANNOT do
----------------------------------------
A signal names its dataset and its field. If this deployment does not carry
them, the signal reports UNAVAILABLE and says which field is missing — it does
not quietly not fire. §7: an absent measure is a stated absence, and a
borrower silently missing from a watchlist because a column was never loaded
is the worst failure this module can have.

Thresholds are declared, owned and versioned
---------------------------------------------
Every number below is in one place, carries an owner, and moves the policy
version in `runkey` when it changes (§11) — so an answer computed under the
old threshold is not served from the cache under the new one. None of them is
a regulatory requirement, and none claims to be.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

TAXONOMY_VERSION = "1.0.0"

#: Who owns these numbers. A threshold with no owner cannot be challenged and
#: cannot be changed, which are the same problem.
THRESHOLD_OWNER = "Credit Risk Analytics"

# --------------------------------------------------------------- the families

FINANCIAL = "financial"
LEVERAGE = "leverage"
LIQUIDITY = "liquidity"
BEHAVIOURAL = "behavioural"
COVENANT = "covenant"
COLLATERAL = "collateral"
RATING = "rating"
IFRS9 = "ifrs9"
#: Layer 4. Configured against fields the borrower snapshot already publishes,
#: so an external signal reads from the same governed row as every other one.
EXTERNAL = "external"
NETWORK = "network"

FAMILIES: dict[str, str] = {
    FINANCIAL: "Financial performance",
    LEVERAGE: "Leverage and debt service",
    LIQUIDITY: "Liquidity",
    BEHAVIOURAL: "Facility behaviour",
    COVENANT: "Covenants",
    COLLATERAL: "Collateral",
    RATING: "Ratings and watchlist",
    IFRS9: "IFRS 9 and SICR",
    EXTERNAL: "External and macro",
    NETWORK: "Group and network",
}

FAMILY_MEANS: dict[str, str] = {
    FINANCIAL: ("What the borrower earns and what it keeps. The slowest to "
                "move and the last to be argued with."),
    LEVERAGE: ("What it owes and whether it can service it. Leverage rising "
               "while coverage falls is one story told twice."),
    LIQUIDITY: ("Whether it can pay this month. The earliest family to move "
                "and the one a borrower can least easily present otherwise."),
    BEHAVIOURAL: ("What the facility is actually doing — paid, drawn, rolled, "
                  "excess. Observed rather than reported."),
    COVENANT: ("The promises in the agreement, and how much room is left "
               "inside them."),
    COLLATERAL: ("What secures the exposure, and whether the value it is "
                 "carried at is still a value."),
    RATING: ("Where the bank has already said this borrower sits, and which "
             "way that has been moving."),
    IFRS9: ("The BOOKED accounting stage and the evidence behind it. A "
            "prediction that a borrower may move stage is not a stage."),
    EXTERNAL: ("What somebody outside the bank has said about this borrower, "
               "and the macro conditions its sector is trading in."),
    NETWORK: ("Who else the exposure reaches. A borrower is not only itself: "
              "a group, a guarantor and a set of connected counterparties "
              "carry risk into it and out of it."),
}

# ---------------------------------------------------------------- the tests

ABOVE = "above"          # value >= threshold
BELOW = "below"          # value < threshold
ROSE_BY = "rose_by"      # value - previous >= threshold
FELL_BY = "fell_by"      # previous - value >= threshold
TRUE = "true"            # a boolean is set
CHANGED = "changed"      # value differs from the previous period
EQUALS = "equals"        # a governed categorical takes a named value

#: field / against, as a percentage. Utilisation is drawn over limit and the
#: snapshot carries the two amounts rather than the ratio; computing it here
#: rather than adding a column keeps one definition of "utilisation" instead
#: of two that can drift apart.
RATIO_ABOVE = "ratio_above"
RATIO_ROSE_BY = "ratio_rose_by"

TESTS: frozenset[str] = frozenset({ABOVE, BELOW, ROSE_BY, FELL_BY, TRUE,
                                   CHANGED, EQUALS, RATIO_ABOVE,
                                   RATIO_ROSE_BY})

# --------------------------------------------------------------------- TAC
#
# How a warning was DETECTED, as opposed to what it is about. The four layers
# say which part of the credit picture a signal watches; TAC says what kind of
# evidence made it fire, and the two are independent — a liquidity concern can
# be found by a threshold or by a credit event, and a reader needs to know
# which because the two carry different weight.
#
#   T  THRESHOLD-BASED   a measurable indicator crossed a governed warning
#                        level: DSCR, utilisation, days past due, PD movement,
#                        covenant headroom, collateral coverage.
#
#   A  ACTION-BASED      a meaningful credit event happened: a rating
#                        downgrade, a stage migration, a watchlist addition, a
#                        covenant breach, forbearance, a restructuring, an
#                        agency outlook change. Somebody DID something.
#
#   C  CLASSIFIER-BASED  several pieces of evidence combined into a recognised
#                        risk pattern. A classifier is not a threshold on a
#                        derived number; it is a named pattern with a stated
#                        rule over other signals.
#
# Nothing is declared a classifier unless a classifier is actually configured
# for it. `CLASSIFIERS` below is that configuration, and it is deliberately
# short.

THRESHOLD_BASED = "THRESHOLD"
ACTION_BASED = "ACTION"
CLASSIFIER_BASED = "CLASSIFIER"
TAC_TYPES: tuple[str, ...] = (THRESHOLD_BASED, ACTION_BASED, CLASSIFIER_BASED)

TAC_MEANS: dict[str, str] = {
    THRESHOLD_BASED: ("A measurable indicator crossed a governed warning "
                      "level."),
    ACTION_BASED: ("A meaningful credit event happened — somebody downgraded, "
                   "migrated, listed, breached or restructured."),
    CLASSIFIER_BASED: ("Several pieces of evidence combined into a recognised "
                       "risk pattern."),
}

TAC_LETTER: dict[str, str] = {THRESHOLD_BASED: "T", ACTION_BASED: "A",
                              CLASSIFIER_BASED: "C"}


def _tac_for(test: str, field: str, booked: bool) -> str:
    """Which detection mechanism a signal uses, from what it actually tests.

    Derived rather than hand-assigned, so a signal cannot be given a letter
    that disagrees with its own test. A boolean flag or a categorical change
    records that something HAPPENED; a comparison against a number records
    that a level was CROSSED.
    """
    if test in (TRUE, CHANGED, EQUALS):
        return ACTION_BASED
    if booked:
        # A booked stage migration is an event even though it is read as a
        # number.
        return ACTION_BASED
    if "flag" in field or "breach" in field or "moved" in field:
        return ACTION_BASED
    return THRESHOLD_BASED


# --------------------------------------------------------------- the severity
#
# Three levels, not five. A scale finer than a person can apply consistently
# is a scale nobody applies consistently, and the difference between "medium"
# and "medium-high" has never once changed what somebody did next.

WATCH = "WATCH"
CONCERN = "CONCERN"
SEVERE = "SEVERE"
SEVERITIES: tuple[str, ...] = (WATCH, CONCERN, SEVERE)
SEVERITY_RANK: dict[str, int] = {WATCH: 1, CONCERN: 2, SEVERE: 3}


# ------------------------------------------------------------------ the units
#
# R2 §3. The acceptance run found the borrower detail showing "Value 75.4" and
# "Threshold 10" — bare numbers a credit officer cannot read. 75.4 what? The
# unit is not decoration: without it the reader cannot tell a percentage from a
# multiple from a sum of money, and a screen that makes them guess is a screen
# they will stop trusting.
#
# Derived rather than hand-typed on forty-three signals, because a table
# maintained by hand drifts from the fields it describes. The derivation is the
# mechanism; `tests/early_warning/test_signal_units.py` is the explicit table
# that holds it honest.

MONEY = "money"          #: SAR millions, the unit the whole book is kept in
PERCENT = "percent"      #: already a percentage
RATIO = "ratio"          #: a multiple — 1.25x
DAYS = "days"
NOTCHES = "notches"      #: rating grades moved
STAGE = "stage"          #: the IFRS 9 stage, 1, 2 or 3
FLAG = "flag"            #: a boolean condition
COUNT = "count"          #: a plain number of things
SCORE = "score"          #: a model output on its own scale, with no natural unit
SHARE = "share"          #: a fraction of one, NOT a percentage already times 100
ENTITIES = "entities"    #: a number of named counterparties
CATEGORY = "category"    #: a label from a controlled vocabulary

#: The currency the book is denominated in. One place, so a screen and an
#: export cannot disagree about it.
CURRENCY = "SAR"

#: Fields that are a multiple rather than a percentage. A covenant written as
#: "minimum DSCR 1.25x" is not a covenant written as "minimum DSCR 125%", and
#: showing one as the other misstates the test.
_MULTIPLES: frozenset[str] = frozenset({
    "debt_to_equity", "interest_coverage", "dscr", "net_leverage",
    "current_ratio", "leverage", "gearing"})

#: Percentages that do not announce themselves with a `_pct` suffix.
_PERCENTAGES: frozenset[str] = frozenset({
    "revenue_growth", "ebitda_margin", "ecl_coverage", "pd_12m",
    "pd_lifetime", "lgd"})

#: Amounts of money that do not announce themselves either. Matched on the
#: underscore-separated WORDS of a column name rather than as substrings:
#: "debt" is inside "debtrank_impact", which is a modelled transmission share
#: and not an amount of money, and labelling it SAR would put a currency in
#: front of 0.0003 on a screen.
_MONEY_WORDS: frozenset[str] = frozenset({
    "cash", "flow", "exposure", "revenue", "ebitda", "capex", "debt",
    "collateral", "limit", "amount", "buffer", "shortfall", "commitment",
    "maturing", "equity", "worth", "balance"})

#: Model outputs on their own scale. A score is not a percentage and not an
#: amount; saying so is the whole point of publishing a unit.
_SCORES: frozenset[str] = frozenset({
    "network_risk_score", "risk_score", "connectedness_score"})

#: Fractions of one. Distinct from PERCENT because these have NOT been
#: multiplied by a hundred, and a screen that treats them as percentages
#: misstates them by two orders of magnitude.
_SHARES: frozenset[str] = frozenset({
    "debtrank_impact", "contagion_share"})

#: Numbers of named counterparties.
_ENTITY_COUNTS: frozenset[str] = frozenset({
    "connected_group_size", "exposure_network_links", "group_size"})

#: Labels from a controlled vocabulary. Not numbers at all, and a signal that
#: reads one must not be rendered with a decimal place.
_CATEGORIES: frozenset[str] = frozenset({
    "rating_outlook", "external_rating", "internal_rating", "rating_grade",
    "sector", "group_role"})


def unit_for(field: str, test: str) -> str:
    """What the value of this signal IS. R2 §3."""
    name = (field or "").strip().lower()
    if test in {RATIO_ABOVE, RATIO_ROSE_BY}:
        # The value is the ratio the test computes, in percent, whatever the
        # underlying field happens to be denominated in.
        return PERCENT
    if test == TRUE:
        return FLAG
    if name == "stage":
        return STAGE
    if name in _CATEGORIES:
        return CATEGORY
    if "notch" in name:
        return NOTCHES
    if name in _MULTIPLES:
        return RATIO
    if name in _SCORES or name.endswith("_score"):
        return SCORE
    if name in _SHARES:
        return SHARE
    if name in _ENTITY_COUNTS:
        return ENTITIES
    if name.endswith("_share"):
        # A share is a share whether it is written as a fraction or scaled.
        # Where the catalogue does not say, the safe reading is the one that
        # cannot be out by a hundred.
        return RATIO
    if name.endswith("_pct") or name in _PERCENTAGES:
        return PERCENT
    if name.endswith("_days") or name.endswith("_dpd") or "dpd" in name:
        return DAYS
    if _MONEY_WORDS & set(name.split("_")):
        return MONEY
    return COUNT


@dataclass(frozen=True)
class Signal:
    """One governed condition, and everything needed to defend it. §23."""

    key: str
    family: str
    label: str
    #: What it means for a borrower to be in this state, in one sentence a
    #: credit officer would recognise.
    means: str
    dataset: str
    field: str
    test: str
    threshold: Any = None
    #: For ROSE_BY / FELL_BY / CHANGED: the field carrying the prior value,
    #: when the dataset carries one. Empty means "compare with the same field
    #: at the previous period", which the evaluator does by joining periods.
    against: str = ""
    severity: str = CONCERN
    #: True where this is IFRS 9's BOOKED position rather than a prediction.
    #: §20 is emphatic: never describe an early-warning prediction as an
    #: accounting stage classification, and the only way to keep that straight
    #: is to mark which is which in the data.
    booked_accounting: bool = False
    version: str = TAXONOMY_VERSION

    @property
    def unit(self) -> str:
        """What the value is denominated in. R2 §3."""
        return unit_for(self.field, self.test)

    @property
    def tac(self) -> str:
        """How this signal is detected: threshold, action or classifier."""
        return _tac_for(self.test, self.field, self.booked_accounting)

    @property
    def tac_letter(self) -> str:
        return TAC_LETTER[self.tac]

    @property
    def columns(self) -> tuple[str, ...]:
        return (self.field, self.against) if self.against else (self.field,)

    def sentence(self) -> str:
        """The threshold, said as a person would say it."""
        if self.test == TRUE:
            return self.label
        if self.test == ABOVE:
            return f"{self.label} ({self.field} at or above {self.threshold})"
        if self.test == BELOW:
            return f"{self.label} ({self.field} below {self.threshold})"
        if self.test == ROSE_BY:
            return f"{self.label} ({self.field} up {self.threshold} or more)"
        if self.test == RATIO_ABOVE:
            return (f"{self.label} ({self.field} over {self.against} at or "
                    f"above {self.threshold}%)")
        if self.test == RATIO_ROSE_BY:
            return (f"{self.label} ({self.field} over {self.against} up "
                    f"{self.threshold} points or more)")
        if self.test == FELL_BY:
            return f"{self.label} ({self.field} down {self.threshold} or more)"
        return f"{self.label} ({self.field} changed)"

    def to_dict(self) -> dict[str, Any]:
        return {"key": self.key, "family": self.family,
                "family_label": FAMILIES.get(self.family, self.family),
                "label": self.label, "means": self.means,
                "dataset": self.dataset, "field": self.field,
                "test": self.test, "threshold": self.threshold,
                "unit": self.unit, "currency": CURRENCY,
                "against": self.against, "severity": self.severity,
                "booked_accounting": self.booked_accounting,
                "tac": self.tac, "tac_letter": self.tac_letter,
                "tac_means": TAC_MEANS[self.tac],
                "owner": THRESHOLD_OWNER, "version": self.version,
                "sentence": self.sentence()}


def _s(key, family, label, means, dataset, field, test, threshold=None, *,
       against="", severity=CONCERN, booked=False) -> Signal:
    return Signal(key=key, family=family, label=label, means=means,
                  dataset=dataset, field=field, test=test,
                  threshold=threshold, against=against, severity=severity,
                  booked_accounting=booked)


#: The governed signals, bound to fields the catalogue actually publishes.
#:
#: §20 lists more conditions than this — receivable stretch, inventory build,
#: returned payments, insurance expiry, multiple-notch rating movement. Each of
#: those needs a column this book does not carry, and a signal declared over a
#: field that does not exist is a signal that never fires and a watchlist that
#: is quietly incomplete. `unavailable()` names them instead.
SIGNALS: tuple[Signal, ...] = (
    # ---- financial performance
    _s("revenue_fell", FINANCIAL, "Revenue fell",
       "Turnover is below where it was a year ago.",
       "corporate_borrower_360", "revenue_growth", BELOW, 0.0),
    _s("ebitda_margin_fell", FINANCIAL, "EBITDA margin fell",
       "The borrower is keeping less of what it earns than it was.",
       "corporate_borrower_360", "ebitda_margin", FELL_BY, 2.0),
    _s("cash_flow_negative", FINANCIAL, "Operating cash flow negative",
       "The business consumed cash in the period rather than generating it.",
       "corporate_borrower_360", "cash_flow_from_operations", BELOW, 0.0,
       severity=SEVERE),
    _s("free_cash_flow_negative", FINANCIAL, "Free cash flow negative",
       "After investment, the borrower did not fund itself.",
       "corporate_borrower_360", "free_cash_flow", BELOW, 0.0),
    _s("cash_thin", LIQUIDITY, "Cash below a twentieth of drawn exposure",
       "The borrower holds very little cash against what it has drawn. A "
       "seeded materiality, not a regulatory requirement.",
       "corporate_borrower_360", "cash", RATIO_ABOVE, -5.0,
       against="drawn_exposure"),

    # ---- leverage and debt service
    _s("leverage_rose", LEVERAGE, "Leverage rose",
       "Net debt to EBITDA is half a turn or more above the prior period.",
       "corporate_borrower_360", "debt_to_equity", ROSE_BY, 0.25),
    _s("leverage_high", LEVERAGE, "Debt above four times equity",
       "The balance sheet carries four times more debt than book equity.",
       "corporate_borrower_360", "debt_to_equity", ABOVE, 4.0,
       severity=SEVERE),
    _s("interest_cover_weak", LEVERAGE, "Interest cover below 2x",
       "EBITDA covers the interest bill less than twice over.",
       "corporate_borrower_360", "interest_coverage", BELOW, 2.0),
    _s("interest_cover_fell", LEVERAGE, "Interest cover fell",
       "The room between earnings and the interest bill has narrowed.",
       "corporate_borrower_360", "interest_coverage", FELL_BY, 0.5),

    _s("receivable_days_stretched", FINANCIAL,
       "Collecting in more than 90 days",
       "The borrower is waiting more than three months for its money. A "
       "stretching collection cycle is the earliest liquidity signal a "
       "lender can see, because it moves before revenue does.",
       "corporate_borrower_360", "receivable_days", ABOVE, 90.0),
    _s("receivable_days_rose", FINANCIAL, "Collection period lengthened",
       "Receivable days are fifteen or more above the prior period.",
       "corporate_borrower_360", "receivable_days", ROSE_BY, 15.0),
    _s("cash_cycle_stretched", FINANCIAL, "Cash conversion cycle above 120 days",
       "Money spent on stock and supply takes more than four months to come "
       "back as cash, so the same trade ties up more of the facility.",
       "corporate_borrower_360", "cash_conversion_cycle_days", ABOVE, 120.0),
    _s("capex_starved", FINANCIAL,
       "Investing less than 2% of revenue",
       "Capital expenditure is thin against turnover. Capex is what a "
       "borrower cuts first when cash is short, which is what makes a low "
       "line a warning rather than a sign of discipline. A seeded "
       "materiality, not a regulatory requirement.",
       "corporate_borrower_360", "capex", RATIO_ABOVE, -2.0,
       against="revenue", severity=WATCH),

    # ---- liquidity
    _s("liquidity_buffer_thin", LIQUIDITY,
       "Cash and committed headroom below a tenth of drawn exposure",
       "What the borrower can actually reach — cash plus the headroom it is "
       "contractually entitled to draw — is thin against what it has already "
       "borrowed. A seeded materiality, not a regulatory requirement.",
       "corporate_borrower_360", "cash", RATIO_ABOVE, -10.0,
       against="drawn_exposure", severity=SEVERE),
    _s("committed_headroom_thin", LIQUIDITY,
       "Little COMMITTED headroom left",
       "The undrawn amount the bank is contractually obliged to lend is "
       "under a tenth of the limit. Uncommitted headroom is exactly what "
       "disappears when a borrower needs it, so this is the number that "
       "matters rather than the undrawn total.",
       "corporate_borrower_360", "undrawn_committed", RATIO_ABOVE, -10.0,
       against="total_limit"),
    _s("short_term_debt_heavy", LIQUIDITY,
       "More than half of debt falls due within a year",
       "Lenders have stopped lending long. This is the difference between a "
       "leverage problem and a liquidity one.",
       "corporate_borrower_360", "short_term_debt", RATIO_ABOVE, 50.0,
       against="debt"),
    _s("maturity_wall", LIQUIDITY,
       "More than a fifth of drawn exposure matures within twelve months",
       "A refinancing requirement is coming and the cash is not obviously "
       "there to meet it.",
       "corporate_borrower_360", "maturing_within_12m", RATIO_ABOVE, 20.0,
       against="drawn_exposure"),
    _s("near_maturity_uncovered", LIQUIDITY,
       "Debt due within three months exceeds cash",
       "What falls due this quarter is larger than the cash balance, so the "
       "borrower must generate, refinance or draw to meet it.",
       "corporate_borrower_360", "maturing_0_3m", RATIO_ABOVE, 100.0,
       against="cash", severity=SEVERE),
    _s("utilisation_high", LIQUIDITY, "Drawn to 90% or more of its limit",
       "There is little room left on the facilities the borrower has.",
       "corporate_borrower_360", "drawn_exposure", RATIO_ABOVE, 90.0,
       against="total_limit"),
    _s("utilisation_rose", LIQUIDITY, "Utilisation rose sharply",
       "Drawing has increased by five points of its limit or more since the "
       "prior period.",
       "corporate_borrower_360", "drawn_exposure", RATIO_ROSE_BY, 5.0,
       against="total_limit"),
    _s("undrawn_thin", LIQUIDITY, "Little committed headroom left",
       "The undrawn commitment is under a tenth of the limit, so there is "
       "little the borrower can draw on if it needs to.",
       "corporate_borrower_360", "undrawn_commitment", RATIO_ABOVE, -10.0,
       against="total_limit"),
    _s("large_exposure", LIQUIDITY, "Large single-name exposure",
       "Exposure to this borrower is above a twentieth of the eligible "
       "capital reference. UNVERIFIED REGULATORY PARAMETER: a seeded "
       "materiality, not a verified large-exposure requirement.",
       "corporate_borrower_360", "single_name_utilisation_pct", ABOVE, 5.0,
       severity=WATCH),

    # ---- facility behaviour
    _s("in_arrears", BEHAVIOURAL, "In arrears",
       "A payment is past due.",
       "corporate_borrower_360", "current_dpd", ABOVE, 1),
    _s("arrears_30", BEHAVIOURAL, "Thirty days past due",
       "A payment has been outstanding for a month or more.",
       "corporate_borrower_360", "current_dpd", ABOVE, 30,
       severity=SEVERE),
    _s("repeated_delinquency", BEHAVIOURAL, "Late more than once this year",
       "The worst arrears in the last twelve months exceeded a month.",
       "corporate_borrower_360", "max_dpd_12m", ABOVE, 30),
    _s("restructured", BEHAVIOURAL, "Concession granted",
       "The bank has granted a concession it would not grant a healthy "
       "borrower.",
       "corporate_borrower_360", "forbearance_flag", TRUE, severity=SEVERE),

    # ---- covenants
    _s("covenant_breached", COVENANT, "Covenant breached",
       "At least one financial covenant is in breach.",
       "corporate_borrower_360", "breach_flag", TRUE, severity=SEVERE),
    _s("covenant_headroom_tight", COVENANT, "Covenant headroom below 10%",
       "The nearest covenant has less than a tenth of its room left.",
       "corporate_borrower_360", "minimum_headroom_pct", BELOW, 10.0),
    _s("covenant_headroom_fell", COVENANT, "Covenant headroom fell",
       "Average headroom has narrowed by five points or more.",
       "corporate_borrower_360", "average_headroom_pct", FELL_BY, 5.0),
    _s("statements_stale", COVENANT, "Tested on old statements",
       "The most recent financials are more than six months old, so the "
       "headroom shown may already be historical.",
       "corporate_borrower_360", "financial_statement_age_days", ABOVE, 365),

    # ---- collateral
    _s("collateral_thin", COLLATERAL, "Collateral coverage below 50%",
       "Post-haircut collateral covers less than half the exposure.",
       "corporate_borrower_360", "collateral_coverage_pct", BELOW, 50.0),
    _s("collateral_fell", COLLATERAL, "Collateral coverage fell",
       "Coverage has dropped by ten points or more.",
       "corporate_borrower_360", "collateral_coverage_pct", FELL_BY, 10.0),
    _s("collateral_shortfall", COLLATERAL, "Material collateral shortfall",
       "A quarter or more of the drawn exposure is not reached by collateral. "
       "Measured against the borrower's own exposure rather than as a fixed "
       "amount: ten million uncovered is a rounding error on a large "
       "facility and the whole facility on a small one, and a threshold that "
       "cannot tell those apart fires on two fifths of the book. The "
       "proportion is a seeded default, not a regulatory requirement.",
       "corporate_borrower_360", "collateral_shortfall", RATIO_ABOVE, 25.0,
       against="drawn_exposure", severity=SEVERE),
    _s("valuation_stale", COLLATERAL, "Valuation more than two years old",
       "The collateral is carried at a value nobody has revisited in over two "
       "years. A stale value is not a value.",
       "corporate_borrower_360", "valuation_age_days", ABOVE, 730),

    # ---- ratings and watchlist
    _s("rating_downgraded", RATING, "Internal rating downgraded",
       "The bank's own rating has moved down since the prior period.",
       "corporate_borrower_360", "rating_change_notches", BELOW, 0.0),
    _s("rating_multi_notch", RATING, "Downgraded two notches or more",
       "A single-notch move is routine; two is a change of view.",
       "corporate_borrower_360", "rating_change_notches", BELOW, -1.0,
       severity=SEVERE),
    _s("rating_stale", RATING, "Rating overridden",
       "The rating in force is a manual override rather than the model's.",
       "corporate_borrower_360", "rating_override_flag", TRUE,
       severity=WATCH),
    _s("on_watchlist", RATING, "On the watchlist",
       "Somebody has already raised this borrower.",
       "corporate_borrower_360", "watchlist_flag", TRUE),

    # ---- IFRS 9. Booked, not predicted.
    _s("stage_2", IFRS9, "Booked at stage 2 or worse",
       "The accounting position TODAY, not a prediction that it will move.",
       "corporate_borrower_360", "stage", ABOVE, 2, booked=True),
    _s("stage_3", IFRS9, "Booked at stage 3",
       "Credit-impaired in the accounts. Booked, not predicted.",
       "corporate_borrower_360", "stage", ABOVE, 3, booked=True,
       severity=SEVERE),
    _s("pd_rose", IFRS9, "12-month PD rose",
       "The modelled probability of default is a point or more above the "
       "prior period.",
       "corporate_borrower_360", "pd_12m", ROSE_BY, 1.0),
    _s("ecl_rose", IFRS9, "ECL coverage rose",
       "The provision against this borrower has increased as a share of "
       "exposure.",
       "corporate_borrower_360", "ecl_coverage", ROSE_BY, 0.5),
    _s("sicr_flagged", IFRS9, "SICR trigger set",
       "A significant-increase-in-credit-risk trigger fired at the last "
       "reporting date.",
       "corporate_borrower_360", "sicr_flag", TRUE, booked=True),

    # ---- external and macro (layer 4)
    #
    # These read fields the borrower snapshot already publishes, so an external
    # signal comes off the same governed row as every other one. The layer was
    # previously empty and SAID so; it is no longer empty, and what fills it is
    # small and real rather than large and invented.
    _s("outlook_negative", EXTERNAL, "External outlook is negative",
       "A rating agency has this borrower on a negative outlook. Somebody "
       "outside the bank expects its credit quality to deteriorate.",
       "corporate_borrower_360", "rating_outlook", EQUALS, "Negative"),
    _s("external_rating_lost", EXTERNAL, "External rating withdrawn or absent",
       "The borrower carries no external rating this period where it "
       "previously did. A withdrawn rating removes an independent view.",
       "corporate_borrower_360", "external_rating", CHANGED),
    _s("sector_concentrated", EXTERNAL, "Large share of a concentrated sector",
       "The borrower is a material part of a sector the bank is already "
       "heavily exposed to, so a sector shock reaches the book through it.",
       "corporate_borrower_360", "sector_concentration_share", ABOVE, 1.25,
       severity=WATCH),

    # ---- group and network (layer 4)
    _s("network_risk_high", NETWORK, "High network risk score",
       "The connected-exposure graph places this borrower where trouble "
       "would travel: it both carries and transmits risk across the group.",
       "corporate_borrower_360", "network_risk_score", ABOVE, 21.0),
    _s("group_large", NETWORK, "Large connected group",
       "The borrower sits inside an unusually large connected group, so its "
       "exposure is not the exposure the bank is actually running.",
       "corporate_borrower_360", "connected_group_size", ABOVE, 13.0,
       severity=WATCH),
    _s("contagion_material", NETWORK, "Material contagion impact",
       "Modelled loss transmission from this borrower into the rest of the "
       "group is above the level the threshold owner treats as material.",
       "corporate_borrower_360", "debtrank_impact", ABOVE, 0.0003),
)

BY_KEY: dict[str, Signal] = {s.key: s for s in SIGNALS}


def in_family(family: str) -> list[Signal]:
    return [s for s in SIGNALS if s.family == family]


#: Conditions §20 names that this book carries no field for. Stated rather
#: than silently absent: a watchlist missing a whole family because a column
#: was never loaded is worse than one that says which family it is missing.
#: What this deployment cannot watch for, and why. §7.
#:
#: This list used to have eight entries and every one of them was liquidity or
#: external context. They were true, and they were the wrong answer: liquidity
#: is where a corporate credit actually fails, so the data was built rather
#: than the box redrawn. See docs/LIQUIDITY_AND_EXTERNAL_DATA.md.
#:
#: The mechanism stays. A deployment that does not install those domains
#: reports the gap again, and `unavailable()` is still what an answer consults
#: when a question reaches past what the book holds. An empty list here is a
#: statement about THIS deployment, not a claim that nothing is ever missing.
UNAVAILABLE: tuple[tuple[str, str], ...] = (
    (COVENANT, "the covenant a waiver was granted against — the waiver file "
               "records that one was granted and on what terms, not which of "
               "the borrower's tests it released"),
)


def unavailable(family: str = "") -> list[dict[str, str]]:
    """What this deployment cannot watch for, and why. §7."""
    return [{"family": f, "family_label": FAMILIES.get(f, f), "means": why}
            for f, why in UNAVAILABLE if not family or f == family]


def describe() -> dict[str, Any]:
    """The whole taxonomy, for the screen and for the analyst's tools."""
    return {
        "version": TAXONOMY_VERSION,
        "owner": THRESHOLD_OWNER,
        "families": [
            {"id": key, "label": label, "means": FAMILY_MEANS.get(key, ""),
             "signals": [s.to_dict() for s in in_family(key)],
             "unavailable": unavailable(key)}
            for key, label in FAMILIES.items()
        ],
        # The same signals again, flat. Families are how a screen groups them
        # and a flat list is how anything searches them; deriving one from the
        # other at every call site is how two callers end up disagreeing about
        # how many signals there are.
        "signals": [s.to_dict() for s in SIGNALS],
        "unavailable": unavailable(),
        "signal_count": len(SIGNALS),
        "severities": list(SEVERITIES),
    }


__all__ = [
    "ABOVE", "BEHAVIOURAL", "BELOW", "BY_KEY", "CATEGORY", "CHANGED",
    "COLLATERAL", "ENTITIES", "SCORE", "SHARE",
    "RATIO_ABOVE", "RATIO_ROSE_BY",
    "CONCERN", "COVENANT", "FAMILIES", "FAMILY_MEANS", "FELL_BY", "FINANCIAL",
    "ACTION_BASED", "CLASSIFIER_BASED", "EQUALS", "EXTERNAL", "IFRS9",
    "LEVERAGE", "LIQUIDITY", "NETWORK", "RATING", "ROSE_BY", "SEVERE",
    "TAC_LETTER", "TAC_MEANS", "TAC_TYPES", "THRESHOLD_BASED",
    "SEVERITIES", "SEVERITY_RANK", "SIGNALS", "TAXONOMY_VERSION", "TESTS",
    "THRESHOLD_OWNER", "TRUE", "UNAVAILABLE", "WATCH", "Signal", "describe",
    "in_family", "unavailable",
]
