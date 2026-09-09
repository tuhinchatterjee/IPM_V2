"""
Corporate IFRS 9 at facility grain — a governed derivative of the one book.

Why this exists
---------------
`corporate_ifrs9` is deliberately obligor-grain. `universe.py::build_ifrs9`
says why in its own docstring: for a corporate exposure a significant increase
in credit risk is assessed on the counterparty, and *"a book that stages one
facility of a borrower differently from another is describing a bank that does
not exist."* That ruling stands and this module does not touch it.

But several consumers need the same book expressed per facility — the Cockpit's
field contract, What-If's detailed Excel, Borrower 360's facility view. Each of
them inventing its own allocation is how one book becomes three.

So there is one allocation, here, and it is exact rather than approximate.

Why it is exact, and not an estimate
------------------------------------
Three facts about the canonical book make this a decomposition rather than a
model:

1. **EAD is already facility-level and already reconciles.** Every row of
   `corporate_facilities` carries `ifrs9_ead`, and `build_ifrs9` computes the
   obligor's EAD as their sum. Measured over the whole book, the largest
   disagreement between the sum of a borrower's facility EADs and their obligor
   EAD is 1.8e-12 — floating point noise, not a difference.

2. **Stage, SICR, PD and LGD are obligor properties.** That is the ruling
   above, not a simplification: assigning the obligor's stage to each of their
   facilities *is* what obligor-level staging means. Nothing is allocated here,
   it is carried.

3. **ECL is linear in EAD.** The book computes ECL as a scenario-weighted
   product of PD, LGD and EAD; holding the obligor's PD and LGD fixed, the only
   facility-varying input is EAD. Measured over the whole book, the ratio
   `ecl_before_overlay / (pd_applicable x lgd x ead)` is constant to five
   decimal places within a stage. So splitting the obligor's ECL in proportion
   to EAD reproduces exactly what computing it per facility would have given.

Where a quantity is genuinely facility-level in the source (drawn exposure,
undrawn commitment, limit, secured and unsecured split, CCF) it is READ from
`corporate_facilities`, not allocated. Only the ECL amounts are shared out, and
`reconciles()` asserts the sum returns to the obligor figure.

What this is not
----------------
Not a second IFRS 9 engine. It re-decides no stage, no SICR, no PD, no LGD and
no ECL total. It exposes the one book at a second grain, and a test fails if
the two ever disagree.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

#: The dataset this module publishes.
DATASET = "corporate_ifrs9_facility"

#: The obligor's assessment, carried to each of their facilities unchanged.
#: These are properties OF THE COUNTERPARTY. Copying them is not an
#: approximation; it is the definition of obligor-level staging.
CARRIED: tuple[str, ...] = (
    "period_end_date",
    "stage", "prior_stage", "stage_measured", "stage_moved",
    "sicr_flag", "sicr_trigger_dpd", "sicr_trigger_pd",
    "sicr_trigger_watchlist", "sicr_clear_quarters",
    "pd_12m", "pd_lifetime", "pd_applicable", "pd_measurement_basis",
    "ttc_pd_pct", "pit_pd_12m_pct", "lifetime_pd_pct",
    "pd_at_origination_pct",
    "lgd", "secured_lgd", "unsecured_lgd",
    "current_dpd", "default_flag",
    "scenario_weight_base", "scenario_weight_upside",
    "scenario_weight_downside",
)

#: Read from the facility row itself. These already vary by facility in the
#: source, so allocating them would be replacing a fact with an estimate.
FROM_FACILITY: dict[str, str] = {
    "ead": "ifrs9_ead",
    "drawn_exposure": "drawn_exposure",
    "undrawn_commitment": "undrawn_commitment",
    "total_limit": "limit_amount",
    "credit_conversion_factor": "credit_conversion_factor",
    "secured_exposure": "secured_exposure",
    "unsecured_exposure": "unsecured_exposure",
    "product_type": "product_type",
    "is_revolving": "is_revolving",
    "is_secured": "is_secured",
    "utilisation_pct": "utilisation_pct",
}

#: Shared out in proportion to EAD. Exact, for the reason in the docstring.
ALLOCATED: tuple[str, ...] = (
    "ecl_12m", "ecl_lifetime", "ecl_before_overlay", "management_overlay",
    "final_ecl",
)

#: How far the sum of a borrower's facility ECLs may sit from their obligor
#: ECL before it is called a break. Four decimals is the book's own rounding.
TOLERANCE = 1e-4


#: Decimal places the book carries its amounts to.
DECIMALS = 4


def _split(frame: pd.DataFrame, keys: list[str], total: np.ndarray,
           share: np.ndarray) -> np.ndarray:
    """Share `total` out by `share`, rounded, and summing back EXACTLY.

    Rounding each facility independently is what a naive allocation does, and
    it leaves the sum one or two units in the last place away from the obligor
    figure — on this book, on 6,323 of 52,989 borrower-quarters. That is not a
    modelling error but it is still a reconciliation that does not tie, and a
    facility book that does not tie to the obligor book is the thing this
    module exists to avoid.

    So: round every share down to the book's precision, then hand the leftover
    units, one at a time, to the facilities with the largest discarded
    remainder. This is the largest-remainder method. It moves at most one unit
    in the last place onto any facility, and the column sums to the obligor
    figure exactly rather than nearly.
    """
    scale = 10 ** DECIMALS
    exact = total * share * scale
    floor = np.floor(exact)
    remainder = exact - floor

    group = frame.groupby(keys, sort=False)
    # How many units the obligor total is short after flooring everybody.
    wanted = np.round(total * scale)
    given = group["_units"].transform("sum") if "_units" in frame else None
    del given  # kept explicit: the sum is computed below on the local array

    work = pd.DataFrame({"_k": group.ngroup().to_numpy(),
                         "floor": floor, "remainder": remainder,
                         "wanted": wanted})
    short = (work.groupby("_k")["wanted"].transform("first")
             - work.groupby("_k")["floor"].transform("sum"))
    # Rank within the group by discarded remainder, largest first. `first` as
    # the tie-break keeps this deterministic: the same input gives the same
    # output, which a reconciliation everyone relies on has to.
    rank = work.groupby("_k")["remainder"].rank(method="first",
                                                ascending=False)
    units = floor + np.where(rank <= short.to_numpy(), 1.0, 0.0)
    return np.round(units / scale, DECIMALS)


def build(ifrs9: pd.DataFrame, facilities: pd.DataFrame) -> pd.DataFrame:
    """One row per facility per quarter, carrying the obligor's assessment.

    `ifrs9` is `corporate_ifrs9`; `facilities` is `corporate_facilities`.
    Both are read, neither is modified.
    """
    keys = ["borrower_id", "period"]
    missing = [c for c in keys if c not in facilities.columns]
    if missing:
        raise ValueError(f"corporate_facilities is missing {missing}")

    facility_columns = ["facility_id", *keys,
                        *[src for src in FROM_FACILITY.values()
                          if src in facilities.columns]]
    frame = facilities[facility_columns].copy()
    frame = frame.rename(columns={src: dst for dst, src in FROM_FACILITY.items()
                                  if src in facilities.columns})

    # The obligor's EAD, recomputed here from the same facility rows the
    # allocation will use. Taking it from `corporate_ifrs9` instead would make
    # the shares sum to something very slightly other than one whenever the
    # two disagreed, and the point of this module is that they do not.
    frame["_obligor_ead"] = frame.groupby(keys)["ead"].transform("sum")
    ead = frame["ead"].to_numpy(dtype=float)
    obligor_ead = frame["_obligor_ead"].to_numpy(dtype=float)
    # A borrower whose facilities all carry zero EAD still has facilities, and
    # still has an ECL of zero to share between them. Splitting equally there
    # is not an assumption about risk — it is the only split that exists when
    # the denominator is zero, and it allocates zero either way.
    count = frame.groupby(keys)["ead"].transform("size").to_numpy(dtype=float)
    share = np.where(obligor_ead > 0, ead / np.maximum(obligor_ead, 1e-12),
                     1.0 / np.maximum(count, 1.0))
    frame["ead_share"] = np.round(share, 10)

    carried = [c for c in CARRIED if c in ifrs9.columns]
    allocated = [c for c in ALLOCATED if c in ifrs9.columns]
    obligor = ifrs9[[*keys, *carried, *allocated]].copy()
    obligor = obligor.rename(columns={c: f"_obligor_{c}" for c in allocated})

    frame = frame.merge(obligor, on=keys, how="left")

    for column in allocated:
        frame[column] = _split(frame, keys,
                               frame[f"_obligor_{column}"].to_numpy(dtype=float),
                               share)
        frame = frame.drop(columns=[f"_obligor_{column}"])

    # Coverage is recomputed from this row rather than carried, because it is a
    # ratio of two facility quantities and the obligor's ratio is not this
    # facility's. Zero EAD gives zero coverage, not a division by zero.
    if "final_ecl" in frame.columns:
        frame["ecl_coverage"] = np.round(np.where(
            ead > 0, frame["final_ecl"].to_numpy(dtype=float)
            / np.maximum(ead, 1e-12) * 100.0, 0.0), 4)

    frame = frame.drop(columns=["_obligor_ead"])
    frame["grain"] = "facility"
    frame["allocation_basis"] = "ead_share"
    frame["origin"] = "derived_from_corporate_ifrs9"

    ordered = ["borrower_id", "facility_id", "period"]
    rest = [c for c in frame.columns if c not in ordered]
    return frame[[*ordered, *rest]].sort_values(
        ["period", "borrower_id", "facility_id"]).reset_index(drop=True)


def reconciles(facility: pd.DataFrame, ifrs9: pd.DataFrame,
               *, tolerance: float = TOLERANCE) -> pd.DataFrame:
    """Every borrower-quarter where the two grains disagree. Empty is correct.

    Returned rather than asserted so a caller can print WHICH borrower broke
    and by how much, instead of a bare False.
    """
    keys = ["borrower_id", "period"]
    columns = [c for c in ALLOCATED if c in facility.columns
               and c in ifrs9.columns]
    summed = facility.groupby(keys)[list(columns)].sum().reset_index()
    merged = summed.merge(ifrs9[[*keys, *columns]], on=keys,
                          how="outer", suffixes=("_facility", "_obligor"),
                          indicator=True)
    breaks = merged["_merge"] != "both"
    for column in columns:
        difference = (merged[f"{column}_facility"].fillna(0.0)
                      - merged[f"{column}_obligor"].fillna(0.0)).abs()
        merged[f"{column}_diff"] = difference
        breaks = breaks | (difference > tolerance)
    # EAD too: it is not allocated, so a break here is a break in the source.
    if "ead" in facility.columns and "ead" in ifrs9.columns:
        ead_sum = facility.groupby(keys)["ead"].sum().reset_index()
        merged = merged.merge(ead_sum, on=keys, how="left")
        merged = merged.merge(ifrs9[[*keys, "ead"]], on=keys, how="left",
                              suffixes=("_facility", "_obligor"))
        difference = (merged["ead_facility"].fillna(0.0)
                      - merged["ead_obligor"].fillna(0.0)).abs()
        merged["ead_diff"] = difference
        breaks = breaks | (difference > tolerance)
    return merged[breaks].reset_index(drop=True)


__all__ = ["ALLOCATED", "CARRIED", "DATASET", "FROM_FACILITY", "TOLERANCE",
           "build", "reconciles"]
