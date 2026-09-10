"""
Versioned synthetic retail credit policy: staging, default, cure, affordability.

Every threshold in this file is a **synthetic demo policy**. None of it is an
ANB rule, and none of it is a statement of what SAMA or IFRS 9 require. The
30-DPD Stage 2 trigger and the 90-DPD default backstop are conservative
illustrative choices that a Saudi retail bank would recognise; they are written
down here, with a version, so that every stage decision in the book can be
traced to the rule that made it rather than to a number somebody typed into a
generator.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from backend.retail.taxonomy import CREDIT_CARD, HOME_LOAN, PERSONAL_LOAN, AUTO_LOAN

STAGING_POLICY_VERSION = "retail-staging-1.0.0"
DEFAULT_DEFINITION_ID = "retail-default-90dpd-or-utp-1.0.0"
AFFORDABILITY_POLICY_VERSION = "retail-affordability-1.0.0"
SOURCE_LABEL = "Synthetic demo policy"


@dataclass(frozen=True)
class StagingPolicy:
    """When a facility moves stage, and why.

    Written as a policy object rather than as `if dpd > 30` inside the generator
    so that the reason recorded on the row and the rule that fired are the same
    object, and so What-If can re-evaluate staging under a changed threshold
    without a second, drifting copy of the rule.
    """

    version: str = STAGING_POLICY_VERSION
    source_label: str = SOURCE_LABEL

    # --- quantitative SICR -------------------------------------------------
    #: Lifetime-PD *ratio* against the origination curve's remaining-life PD.
    #: A ratio compares like horizons; dividing a 12-month PD by an origination
    #: lifetime PD would compare two different questions.
    sicr_pd_ratio_threshold: float = 2.0
    #: Absolute remaining-life PD increase that triggers SICR on its own.
    sicr_pd_absolute_threshold: float = 0.05

    # --- DPD backstops -----------------------------------------------------
    stage2_dpd_backstop: int = 30
    stage3_dpd_backstop: int = 90

    # --- qualitative -------------------------------------------------------
    #: Forbearance granted is qualitative SICR evidence on its own, so Stage 2
    #: is reachable with zero arrears.
    forbearance_is_sicr: bool = True
    #: Two or more missed payments in six months, even if currently up to date.
    missed_payments_6m_sicr_threshold: int = 2
    #: Behavioural-score deterioration is SICR *evidence*, combined with a
    #: watch condition — never an automatic staging rule on its own.
    behavioural_drop_sicr_threshold: float = 80.0

    # --- default / credit impairment --------------------------------------
    #: Unlikeliness to pay can make a facility Stage 3 before 90 DPD.
    utp_is_default: bool = True

    # --- cure --------------------------------------------------------------
    cure_probation_months: int = 3
    cure_requires_zero_dpd: bool = True

    def stage2_reasons(
        self,
        *,
        dpd: int,
        pd_ratio: float | None,
        pd_absolute_change: float | None,
        forbearance_flag: bool,
        missed_payments_6m: int,
        behavioural_score_drop: float | None,
        watch_flag: bool,
    ) -> list[str]:
        """Every Stage 2 reason that holds, not just the first one found."""
        reasons: list[str] = []
        if dpd >= self.stage2_dpd_backstop:
            reasons.append(f"DPD backstop: {dpd} days past due at or above {self.stage2_dpd_backstop}")
        if pd_ratio is not None and pd_ratio >= self.sicr_pd_ratio_threshold:
            reasons.append(
                f"Quantitative SICR: remaining-life PD is {pd_ratio:.2f}x its origination "
                f"remaining-life reference (threshold {self.sicr_pd_ratio_threshold:.2f}x)"
            )
        if pd_absolute_change is not None and pd_absolute_change >= self.sicr_pd_absolute_threshold:
            reasons.append(
                f"Quantitative SICR: remaining-life PD up {pd_absolute_change:.4f} in absolute "
                f"terms (threshold {self.sicr_pd_absolute_threshold:.4f})"
            )
        if forbearance_flag and self.forbearance_is_sicr:
            reasons.append("Qualitative SICR: forbearance granted")
        if missed_payments_6m >= self.missed_payments_6m_sicr_threshold:
            reasons.append(
                f"Qualitative SICR: {missed_payments_6m} missed payments in six months "
                f"(threshold {self.missed_payments_6m_sicr_threshold})"
            )
        if (
            behavioural_score_drop is not None
            and behavioural_score_drop >= self.behavioural_drop_sicr_threshold
            and watch_flag
        ):
            reasons.append(
                f"Qualitative SICR: behavioural score down {behavioural_score_drop:.0f} points "
                "with a watch condition also present"
            )
        return reasons


@dataclass(frozen=True)
class AffordabilityPolicy:
    """Income, obligations and what the demo bank will lend against them.

    Obligation scope is stated explicitly because the commonest affordability
    bug in a retail book is counting the facility being assessed twice.
    """

    version: str = AFFORDABILITY_POLICY_VERSION
    source_label: str = SOURCE_LABEL

    #: `monthly_total_credit_obligations_sar` INCLUDES this facility's own
    #: instalment. Anything adding it again is double counting.
    obligation_scope_definition: str = (
        "monthly_total_credit_obligations_sar = own-bank obligations (including this "
        "facility's scheduled instalment) + verified external obligations. The "
        "facility's own instalment is included exactly once."
    )

    #: DBR = total monthly credit obligations / verified total monthly income.
    max_debt_burden_ratio: dict[str, float] = field(default_factory=lambda: {
        "GOVERNMENT": 0.55, "GOVERNMENT_RELATED": 0.55, "PRIVATE_SECTOR": 0.50,
        "SELF_EMPLOYED": 0.45, "RETIRED": 0.30,
    })
    min_disposable_income_sar: float = 2_000.0
    min_income_sar: dict[str, float] = field(default_factory=lambda: {
        CREDIT_CARD: 4_000.0, PERSONAL_LOAN: 4_000.0,
        AUTO_LOAN: 5_000.0, HOME_LOAN: 8_000.0,
    })
    max_tenor_months: dict[str, int] = field(default_factory=lambda: {
        PERSONAL_LOAN: 60, AUTO_LOAN: 60, HOME_LOAN: 300,
    })
    max_ltv_origination: dict[str, float] = field(default_factory=lambda: {
        AUTO_LOAN: 0.85, HOME_LOAN: 0.90,
    })

    def dbr_cap(self, employment_status: str) -> float:
        return self.max_debt_burden_ratio.get(employment_status, 0.50)


@dataclass(frozen=True)
class ScoreCutoffPolicy:
    """Application-score cutoffs used at origination, by product and version.

    Kept versioned because a retrospective cutoff experiment (§13.4) has to say
    which cutoff was actually in force when an account was booked.
    """

    version: str = "retail-cutoff-1.0.0"
    source_label: str = SOURCE_LABEL
    cutoff: dict[str, float] = field(default_factory=lambda: {
        CREDIT_CARD: 560.0, PERSONAL_LOAN: 580.0, AUTO_LOAN: 570.0, HOME_LOAN: 600.0,
    })
    #: Share of applications allowed through below cutoff on a documented
    #: exception. A demo setting, not an ANB delegation matrix.
    exception_rate: float = 0.04

    def cutoff_for(self, product_code: str) -> float:
        return self.cutoff[product_code]


@dataclass(frozen=True)
class RecoveryPolicy:
    """LGD and recovery assumptions by product. Synthetic demo parameters."""

    version: str = "retail-recovery-1.0.0"
    source_label: str = SOURCE_LABEL
    #: Unsecured LGD after expected collections, discounted to default date.
    unsecured_lgd: dict[str, float] = field(default_factory=lambda: {
        CREDIT_CARD: 0.78, PERSONAL_LOAN: 0.68,
    })
    #: Secured products derive LGD from collateral, sale cost and delay.
    expected_sale_cost_ratio: dict[str, float] = field(default_factory=lambda: {
        AUTO_LOAN: 0.12, HOME_LOAN: 0.09,
    })
    recovery_delay_months: dict[str, int] = field(default_factory=lambda: {
        AUTO_LOAN: 9, HOME_LOAN: 24,
    })
    #: Floor and cap so a collateral shock cannot produce a negative or >1 LGD.
    lgd_floor: float = 0.03
    lgd_cap: float = 0.95
    #: What LGD embeds, said once so recoveries are not discounted twice.
    lgd_definition: str = (
        "LGD is the loss on the exposure at default, net of expected recoveries "
        "already discounted from their receipt date back to the DEFAULT date. ECL "
        "then discounts only from the default month back to the reporting date."
    )


STAGING_POLICY = StagingPolicy()
AFFORDABILITY_POLICY = AffordabilityPolicy()
CUTOFF_POLICY = ScoreCutoffPolicy()
RECOVERY_POLICY = RecoveryPolicy()


def policy_manifest() -> dict[str, object]:
    """Everything a reader needs to check a decision against the rule that made it."""
    return {
        "staging": {
            "version": STAGING_POLICY.version,
            "source_label": STAGING_POLICY.source_label,
            "stage2_dpd_backstop": STAGING_POLICY.stage2_dpd_backstop,
            "stage3_dpd_backstop": STAGING_POLICY.stage3_dpd_backstop,
            "sicr_pd_ratio_threshold": STAGING_POLICY.sicr_pd_ratio_threshold,
            "sicr_pd_absolute_threshold": STAGING_POLICY.sicr_pd_absolute_threshold,
            "cure_probation_months": STAGING_POLICY.cure_probation_months,
            "default_definition_id": DEFAULT_DEFINITION_ID,
        },
        "affordability": {
            "version": AFFORDABILITY_POLICY.version,
            "source_label": AFFORDABILITY_POLICY.source_label,
            "obligation_scope_definition": AFFORDABILITY_POLICY.obligation_scope_definition,
            "max_debt_burden_ratio": dict(AFFORDABILITY_POLICY.max_debt_burden_ratio),
            "min_disposable_income_sar": AFFORDABILITY_POLICY.min_disposable_income_sar,
        },
        "cutoff": {
            "version": CUTOFF_POLICY.version,
            "source_label": CUTOFF_POLICY.source_label,
            "cutoff": dict(CUTOFF_POLICY.cutoff),
        },
        "recovery": {
            "version": RECOVERY_POLICY.version,
            "source_label": RECOVERY_POLICY.source_label,
            "lgd_definition": RECOVERY_POLICY.lgd_definition,
            "unsecured_lgd": dict(RECOVERY_POLICY.unsecured_lgd),
            "recovery_delay_months": dict(RECOVERY_POLICY.recovery_delay_months),
        },
        "disclaimer": (
            "Every threshold above is a synthetic demonstration policy. It is not "
            "ANB policy, not a SAMA requirement and not a statement of IFRS 9."
        ),
    }
