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

FAMILIES: dict[str, str] = {
    FINANCIAL: "Financial performance",
    LEVERAGE: "Leverage and debt service",
    LIQUIDITY: "Liquidity",
    BEHAVIOURAL: "Facility behaviour",
    COVENANT: "Covenants",
    COLLATERAL: "Collateral",
    RATING: "Ratings and watchlist",
    IFRS9: "IFRS 9 and SICR",
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
}

# ---------------------------------------------------------------- the tests

ABOVE = "above"          # value >= threshold
BELOW = "below"          # value < threshold
ROSE_BY = "rose_by"      # value - previous >= threshold
FELL_BY = "fell_by"      # previous - value >= threshold
TRUE = "true"            # a boolean is set
CHANGED = "changed"      # value differs from the previous period

#: field / against, as a percentage. Utilisation is drawn over limit and the
#: snapshot carries the two amounts rather than the ratio; computing it here
#: rather than adding a column keeps one definition of "utilisation" instead
#: of two that can drift apart.
RATIO_ABOVE = "ratio_above"
RATIO_ROSE_BY = "ratio_rose_by"

TESTS: frozenset[str] = frozenset({ABOVE, BELOW, ROSE_BY, FELL_BY, TRUE,
                                   CHANGED, RATIO_ABOVE, RATIO_ROSE_BY})

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
                "against": self.against, "severity": self.severity,
                "booked_accounting": self.booked_accounting,
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

    # ---- liquidity
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
       "More than ten million of exposure that the collateral does not reach. "
       "The materiality is a seeded default, not a regulatory requirement.",
       "corporate_borrower_360", "collateral_shortfall", ABOVE, 10.0,
       severity=SEVERE),
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
)

BY_KEY: dict[str, Signal] = {s.key: s for s in SIGNALS}


def in_family(family: str) -> list[Signal]:
    return [s for s in SIGNALS if s.family == family]


#: Conditions §20 names that this book carries no field for. Stated rather
#: than silently absent: a watchlist missing a whole family because a column
#: was never loaded is worse than one that says which family it is missing.
UNAVAILABLE: tuple[tuple[str, str], ...] = (
    (FINANCIAL, "receivable days and inventory days — no working-capital "
                "ageing is published"),
    (FINANCIAL, "free cash flow — operating cash flow is published, capital "
                "expenditure is not"),
    (LEVERAGE, "the maturity schedule — refinancing pressure and maturity "
               "concentration need dated debt, and debt is published as a "
               "balance"),
    (LIQUIDITY, "cash and undrawn committed lines as a liquidity buffer — "
                "cash is published, committed availability is not"),
    (BEHAVIOURAL, "returned payments and limit excesses — the payment file "
                  "carries due and paid, not rejections"),
    (COVENANT, "waivers and resets — the covenant file records a breach flag "
               "and headroom, not the negotiation after one"),
    (COLLATERAL, "insurance and document expiry"),
    (RATING, "external ratings and outlooks — the book carries the bank's own "
             "rating only"),
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
        "signal_count": len(SIGNALS),
        "severities": list(SEVERITIES),
    }


__all__ = [
    "ABOVE", "BEHAVIOURAL", "BELOW", "BY_KEY", "CHANGED", "COLLATERAL",
    "RATIO_ABOVE", "RATIO_ROSE_BY",
    "CONCERN", "COVENANT", "FAMILIES", "FAMILY_MEANS", "FELL_BY", "FINANCIAL",
    "IFRS9", "LEVERAGE", "LIQUIDITY", "RATING", "ROSE_BY", "SEVERE",
    "SEVERITIES", "SEVERITY_RANK", "SIGNALS", "TAXONOMY_VERSION", "TESTS",
    "THRESHOLD_OWNER", "TRUE", "UNAVAILABLE", "WATCH", "Signal", "describe",
    "in_family", "unavailable",
]
