"""
What must be true of the projection before anybody is allowed to ask it
anything.

Why these run before publication
--------------------------------
A projection defect is worse than a generator defect, because it is invisible
from both sides: the retail book is right, the engine is right, and the
answer is wrong in between. Asked "which product has the highest ECL" the
analyst would answer correctly FROM a mis-projected column and the answer
would look fine.

So the gates run against every month before a single byte is published, and a
finding refuses the release. Each returns a sentence a person can act on.

Why they are written here rather than imported
----------------------------------------------
`backend/cockpit_v4/invariants.py` is the engine's own gate and it is
excellent, but it iterates the engine's STATIC schema and imports the
synthetic generator's product taxonomy -- so against this projection it would
report every column this book adds as unknown and every product it publishes
as unconfigured. It is the template for what follows and is not modified.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.retail_cockpit_adapter import semantic_map as sm

#: Columns whose sign is meaningful. Everything else denominated in money is
#: expected to be non-negative, and a negative one is a finding rather than a
#: figure.
SIGNED_MONEY: frozenset[str] = frozenset({
    # "Overlay applied on top of the modelled result. Kept separate and
    # visible." -- it may release as well as add.
    "ecl_overlay_sar_mn",
    # "Verified income less household expenses less all credit obligations."
    # A customer whose obligations exceed their income has a negative one,
    # and that is the finding a reader wants rather than a bound to clip.
    "disposable_income_sar_mn",
})

#: Percentage columns that compare two quantities rather than expressing one
#: as a share of a whole. A loan-to-value above 100 is a real loan, and
#: bounding it would be a misreading rather than a check.
COMPARISON_PERCENTS: frozenset[str] = frozenset({
    "ltv_pct", "ltv_origination_pct", "utilisation_pct",
    # "What was paid over what was due" -- a card customer who settles the
    # balance pays many times the minimum due, so this has no ceiling of a
    # hundred and capping it would misread what it measures.
    "payment_ratio_1m_pct", "payment_ratio_3m_pct",
})


@dataclass(frozen=True)
class Finding:
    check: str
    relation: str
    problem: str

    def __str__(self) -> str:
        return f"{self.relation}: {self.check} -- {self.problem}"


def _bounded(frame, relation, column, low, high, findings, check) -> None:
    if column not in frame.columns:
        return
    series = frame[column].dropna()
    if series.empty:
        return
    try:
        series = series.astype("float64")
    except (TypeError, ValueError):
        return
    below, above = series[series < low], series[series > high]
    if len(below):
        findings.append(Finding(check, relation,
                                f"{column} has {len(below)} value(s) below "
                                f"{low}, lowest {below.min()}"))
    if len(above):
        findings.append(Finding(check, relation,
                                f"{column} has {len(above)} value(s) above "
                                f"{high}, highest {above.max()}"))


def check_month(projected, month, *, tenant_id: str, release_id: str,
                domain_id: str, currency: str,
                governed: dict[str, Any] | None = None) -> list[Finding]:
    """Every invariant, over one projected month."""
    import pandas as pd

    governed = governed or {}
    findings: list[Finding] = []
    frames = projected.frames

    for relation, frame in frames.items():
        spec = sm.RELATION_SPEC[relation]
        if frame.empty and relation not in (sm.COLLATERAL, sm.ORIGINATION):
            findings.append(Finding("rows present", relation,
                                    f"{month.reporting_month} is empty"))
            continue

        keys = list(spec["key_columns"])
        missing = [k for k in keys if k not in frame.columns]
        if missing:
            findings.append(Finding("grain columns", relation,
                                    f"missing key column(s) {missing}"))
            continue
        duplicated = int(frame.duplicated(subset=keys).sum())
        if duplicated:
            findings.append(Finding("unique grain", relation,
                                    f"{duplicated} duplicate row(s) for "
                                    f"{keys}"))

        # A relation whose grain is not monthly -- the origination one --
        # has no reporting month to check, and checking it against this
        # month would be asserting that a facility was written in the month
        # it is being read in.
        stray = (sorted(set(frame["reporting_month"].dropna())
                        - {month.reporting_month})
                 if "reporting_month" in frame.columns else [])
        if stray:
            findings.append(Finding("period", relation,
                                    f"rows carrying {stray[:3]} in the "
                                    f"{month.reporting_month} projection"))

        for column, expected in (("tenant_id", tenant_id),
                                 ("dataset_release_id", release_id),
                                 ("domain_id", domain_id),
                                 ("reporting_currency", currency)):
            wrong = sorted(set(frame[column].dropna()) - {expected})
            if wrong:
                findings.append(Finding("governance", relation,
                                        f"{column} carries {wrong[:3]}, not "
                                        f"{expected!r}"))

        for column in frame.columns:
            if column.endswith("_sar_mn") and column not in SIGNED_MONEY:
                _bounded(frame, relation, column, 0.0, 1e7, findings,
                         "amounts non-negative")
            elif column.startswith(("pd_", "prob_")):
                _bounded(frame, relation, column, 0.0, 1.0, findings,
                         "probability bounds")
            elif column.endswith("_days"):
                _bounded(frame, relation, column, 0, 3650, findings,
                         "days non-negative")
            elif (column.endswith("_pct")
                  and column not in COMPARISON_PERCENTS):
                _bounded(frame, relation, column, 0.0, 100.0, findings,
                         "percentage bounds")

        if "stage" in frame.columns:
            bad = sorted(set(pd.to_numeric(frame["stage"],
                                           errors="coerce").dropna())
                         - {1, 2, 3})
            if bad:
                findings.append(Finding("IFRS 9 stage", relation,
                                        f"stage values {bad} are not 1, 2 "
                                        f"or 3"))
        bands = governed.get("score_bands")
        if bands and "score_band" in frame.columns:
            bad = sorted(set(frame["score_band"].dropna()) - set(bands))
            if bad:
                findings.append(Finding("score band", relation,
                                        f"bands {bad} are not this book's "
                                        f"{sorted(bands)}"))
        products = governed.get("products")
        if products and "product" in frame.columns:
            bad = sorted(set(frame["product"].dropna()) - set(products))
            if bad:
                findings.append(Finding("product taxonomy", relation,
                                        f"products {bad} are not governed "
                                        f"values of this book"))

    findings.extend(_cross_relation(frames, month))
    return findings


def _cross_relation(frames: dict[str, Any], month) -> list[Finding]:
    """The checks that are about two relations agreeing with each other."""
    import pandas as pd

    findings: list[Finding] = []
    accounts = frames[sm.ACCOUNT]
    customers = frames[sm.CUSTOMER]
    collateral = frames[sm.COLLATERAL]

    # The roll-up IS the facilities, added up. This is the check that stops a
    # customer total being counted once per facility, which is the defect
    # this book's own catalogue warns about.
    for rolled_column, source_column in (("total_ead_sar_mn", "ead_sar_mn"),
                                         ("total_ecl_sar_mn", "ecl_sar_mn")):
        rolled = accounts.groupby("customer_id")[source_column].sum().round(9)
        declared = customers.set_index("customer_id")[rolled_column].round(9)
        joined = declared.to_frame("declared").join(
            rolled.to_frame("rolled"), how="outer")
        mismatched = int(((joined["declared"].fillna(-1)
                           - joined["rolled"].fillna(-2)).abs()
                          > 1e-7).sum())
        if mismatched:
            findings.append(Finding(
                "customer roll-up", sm.CUSTOMER,
                f"{mismatched} customer(s) in {month.reporting_month} "
                f"declare a {rolled_column} that is not the sum of their "
                f"facilities"))

    declared_count = customers.set_index("customer_id")["facilities_held"]
    actual = accounts.groupby("customer_id").size()
    if int((declared_count.sort_index().values
            != actual.sort_index().values).sum()):
        findings.append(Finding("facilities held", sm.CUSTOMER,
                                "facilities_held does not equal the rows "
                                "that customer holds"))

    # Collateral is secured lending only, and every row of it names a
    # facility that exists this month.
    if not collateral.empty:
        known = set(accounts["account_id"])
        orphans = int((~collateral["account_id"].isin(known)).sum())
        if orphans:
            findings.append(Finding("referential integrity", sm.COLLATERAL,
                                    f"{orphans} row(s) name a facility with "
                                    f"no row this month"))
        secured = set(accounts.loc[accounts["secured_flag"] == 1,
                                   "account_id"])
        unsecured = int((~collateral["account_id"].isin(secured)).sum())
        if unsecured:
            findings.append(Finding("collateral scope", sm.COLLATERAL,
                                    f"{unsecured} row(s) secure an unsecured "
                                    f"facility"))

    # The fine arrears split reconciles to the published bucket, exactly.
    if {"delinquency_bucket", "delinquency_bucket_fine",
            "dpd_days"} <= set(accounts.columns):
        coarse_of_fine = {
            "Current": "CURRENT", "1-9": "1-29", "10-19": "1-29",
            "20-29": "1-29", "30-59": "30-59", "60-89": "60-89",
            "90-179": "90-179", "180+": "180+"}
        mapped = accounts["delinquency_bucket_fine"].map(coarse_of_fine)
        published = accounts["delinquency_bucket"].astype("string")
        disagree = int((mapped.fillna("") != published.fillna("")).sum())
        if disagree:
            sample = accounts.loc[
                mapped.fillna("") != published.fillna(""),
                ["dpd_days", "delinquency_bucket",
                 "delinquency_bucket_fine"]].head(3).to_dict("records")
            findings.append(Finding(
                "arrears reconciliation", sm.ACCOUNT,
                f"{disagree} row(s) whose derived fine bucket does not roll "
                f"up to the published bucket, e.g. {sample}"))

    # The behavioural relation is one row per facility-month, the same
    # population as the account relation. One row each way is what the
    # engine's join graph states.
    if len(frames[sm.BEHAVIOUR]) != len(accounts):
        findings.append(Finding(
            "behaviour grain", sm.BEHAVIOUR,
            f"{len(frames[sm.BEHAVIOUR])} rows against "
            f"{len(accounts)} facility rows in {month.reporting_month}"))

    return findings


class GatesFailed(RuntimeError):
    """A projection that failed its own gates. Never published."""

    def __init__(self, findings: list[Finding]) -> None:
        self.findings = findings
        super().__init__("; ".join(str(f) for f in findings[:8]))


__all__ = ["COMPARISON_PERCENTS", "Finding", "GatesFailed", "SIGNED_MONEY",
           "check_month"]
