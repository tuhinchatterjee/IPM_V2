"""What the emulator may look at, and what it must never see.

Section 11.1 names the failure directly: a model trained with the ECL, or
with anything the ECL was computed from in one step, scores near-perfectly
and has learned an identity rather than a relationship. The defence is not a
careful feature list -- those drift -- it is a **banned-name check that runs
on the actual columns handed to the fit** and fails the build.

## The three bans

**The target and its relatives.** Every ECL column, the coverage rate, the
declared rate, the expected shortfall and the whole term structure.

**Anything computed from the target.** `ecl_coverage_pct` is `ecl / ead`;
`ecl_rate` is the target itself. Both are excluded by name AND by the
suffix rules below, so a column added to the release later is caught without
this file being edited.

**The post-hoc columns.** `write_off_sar_mn` and `recovery_sar_mn` describe
what happened after the loss was recognised. They are not available at the
moment the ECL is set, and a model using them is predicting the past.

## What is deliberately KEPT

`pd_pit_12m`, `pd_lifetime` and `lgd_pct` stay in. They are inputs to the
calculator, not outputs of it, and excluding them would be excluding the
credit risk the model is supposed to learn from -- leaving an emulator that
predicts ECL from sector and region alone. The naive `ead x pd x lgd`
reference model in `ML_ACCEPTANCE_TARGETS.md` exists precisely so that the
blend has to beat what those three alone can do, rather than being
congratulated for using them.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from backend.cockpit_v4 import domains as dom

#: The label. The declared rate on the declared denominator, per §11.1, NOT
#: ECL as a share of total exposure -- a share target rewards a model that
#: gets the portfolio mix right while getting every facility wrong.
TARGET = "ecl_rate"

#: The denominator the target is declared against, kept as a feature so the
#: prediction can be converted back to currency.
DENOMINATOR = "ead_sar_mn"

#: Names no feature matrix may contain, whatever a caller passes.
BANNED: frozenset[str] = frozenset({
    "ecl_rate", "ecl_sar_mn", "ecl_12m_sar_mn", "ecl_lifetime_sar_mn",
    "ecl_modelled_sar_mn", "ecl_overlay_sar_mn", "ecl_coverage_pct",
    "total_ecl_sar_mn", "expected_shortfall_sar_mn", "ecl_denominator",
    "overlay_reason",
    # Post-hoc: what happened after the loss was recognised.
    "write_off_sar_mn", "recovery_sar_mn",
})

#: Substrings that make a column suspect however it is spelled, so a column
#: added to the release later is caught without editing `BANNED`.
BANNED_SUBSTRINGS: tuple[str, ...] = ("ecl_", "_ecl", "shortfall",
                                      "write_off", "recovery")

#: Governance and identity columns: not features, not leakage, just not
#: predictive of anything and excluded to keep the matrix readable.
STRUCTURAL: frozenset[str] = frozenset({
    "tenant_id", "dataset_release_id", "domain_id", "reporting_currency",
    "origin", "borrower_name", "ifrs9_model_version",
    "application_score_version", "behaviour_score_version",
    "application_scored_at",
})

#: The key and period columns. Carried beside the matrix for the split and
#: for the per-row audit, and never fed to the fit.
KEYS: dict[str, tuple[str, str]] = {
    dom.CORPORATE: ("facility_id", "reporting_quarter"),
    dom.RETAIL: ("account_id", "reporting_month"),
}

#: The features each book offers, by relation. Listed explicitly rather than
#: taken as "everything left over", because a new column in the release
#: should be a decision rather than an automatic input.
CORPORATE: dict[str, tuple[str, ...]] = {
    "corp_facility_quarter": (
        "product_type", "facility_class", "sector", "sub_sector", "region",
        "relationship_tier", "limit_sar_mn", "drawn_sar_mn",
        "undrawn_sar_mn", "utilisation_pct", "ead_sar_mn", "stage",
        "sicr_flag", "dpd_days", "pd_pit_12m", "pd_lifetime", "lgd_pct",
        "cure_flag", "past_due_flag", "quarters_in_stage"),
    "corp_borrower_quarter": (
        "rating_current", "rating_notches_moved", "rating_migration",
        "rating_outlook", "pd_ttc_12m", "leverage_x", "dscr_x",
        "interest_cover_x", "current_ratio_x", "ebitda_margin_pct",
        "return_on_assets_pct", "cash_conversion_pct", "qualitative_score",
        "watchlist_flag", "restructured_flag", "quarters_on_watchlist"),
    "whatif_corp_ifrs9": (
        "effective_interest_rate", "remaining_maturity_months",
        "lifetime_horizon_months", "ccf_pit", "ccf_eligible_flag",
        "undrawn_eligible_sar_mn"),
}

RETAIL: dict[str, tuple[str, ...]] = {
    "retail_account_month": (
        "product", "sub_product", "secured_flag", "origination_channel",
        "vintage_year", "months_on_book", "customer_segment",
        "employment_type", "region", "limit_sar_mn", "balance_sar_mn",
        "ead_sar_mn", "utilisation_pct", "stage", "sicr_flag", "dpd_days",
        "delinquency_bucket", "pd_pit_12m", "pd_lifetime", "lgd_pct",
        "cure_flag", "behaviour_score", "score_band"),
    "retail_behaviour_month": (
        "utilisation_change_pp", "payment_ratio_pct", "missed_payments_12m",
        "delinquency_streak_months", "balance_growth_pct",
        "cash_advance_ratio_pct", "overlimit_flag", "inflow_change_pct",
        "bureau_inquiries_6m", "repayment_behaviour_score"),
    "whatif_retail_profile": (
        "employer_sector", "employer_sector_group", "application_score"),
    "whatif_retail_ifrs9": (
        "effective_interest_rate", "remaining_maturity_months",
        "lifetime_horizon_months"),
}

BY_DOMAIN: dict[str, dict[str, tuple[str, ...]]] = {
    dom.CORPORATE: CORPORATE, dom.RETAIL: RETAIL}

#: Columns a tree has to be told are categories rather than numbers.
CATEGORICAL: frozenset[str] = frozenset({
    "product_type", "facility_class", "sector", "sub_sector", "region",
    "relationship_tier", "rating_current", "rating_migration",
    "rating_outlook", "product", "sub_product", "origination_channel",
    "customer_segment", "employment_type", "delinquency_bucket",
    "score_band", "employer_sector", "employer_sector_group",
})


def names(domain_id: str) -> tuple[str, ...]:
    """Every feature this book offers, in a stable order."""
    out: list[str] = []
    for relation in sorted(BY_DOMAIN[dom.parse(domain_id)]):
        out.extend(BY_DOMAIN[dom.parse(domain_id)][relation])
    return tuple(out)


def suspicious(columns: Iterable[str]) -> list[str]:
    """Every column that must not be in a feature matrix, and why.

    By name AND by substring, so a column added to the release later is
    caught by the rule rather than by somebody remembering to edit a list.
    """
    bad: list[str] = []
    for column in columns:
        lower = str(column).lower()
        if lower in BANNED:
            bad.append(f"{column}: named in BANNED")
            continue
        for fragment in BANNED_SUBSTRINGS:
            if fragment in lower:
                bad.append(f"{column}: contains {fragment!r}")
                break
    return bad


def require_clean(columns: Sequence[str], *, where: str = "X") -> None:
    """M02. Raise rather than train on a matrix that can see the answer.

    An assertion rather than a filter on purpose. Silently dropping a leaked
    column would let a training script that assembled the wrong matrix
    produce a plausible model, and the mistake would surface as an
    implausibly good score that somebody would then have to disbelieve.
    """
    bad = suspicious(columns)
    if bad:
        raise AssertionError(
            f"{where} contains {len(bad)} column(s) derived from the target. "
            f"A model trained on these learns an identity, not a "
            f"relationship:\n  " + "\n  ".join(bad))


def check_target(target: str) -> None:
    if target != TARGET:
        raise AssertionError(
            f"the target is {TARGET!r}, the declared rate on the declared "
            f"denominator. {target!r} is something else, and section 11.1 is "
            f"specifically about training on a target that was manufactured "
            f"rather than published.")


__all__ = ["BANNED", "BANNED_SUBSTRINGS", "BY_DOMAIN", "CATEGORICAL",
           "CORPORATE", "DENOMINATOR", "KEYS", "RETAIL", "STRUCTURAL",
           "TARGET", "check_target", "names", "require_clean", "suspicious"]
