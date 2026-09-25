"""Generators for the labelled synthetic candidate releases.

Separate from `backend/cockpit_v4/generate/`, which produces the two ACCEPTED
books and is a protected file. Nothing here writes to those, and
`test_whatif_candidate_release.py` re-checks both accepted fingerprints after
every candidate build.

What makes these books different from the accepted ones, and why it matters:

**The macro comes first.** The twenty-factor panel is generated before any
risk parameter, and PD and LGD are then generated FROM it through a declared
structural relationship with lags and segment heterogeneity. That order is the
whole point. Appending random macro columns to unchanged PD values and then
fitting a sensitivity to them would produce coefficients, a fitted R-squared
and a heatmap, and every one of those numbers would be an artefact of noise.
Section 7 would be a decoration. Here there is something real to recover, and
`test_whatif_sensitivity.py` checks that the estimator recovers it.

**ECL is measured, not multiplied.** `reference_ecl.py` takes the per-scenario
term structure and discounts it; the accepted books' `ead x pd x lgd` is what
made them unusable as an ML target (section 11.1).

**Everything is labelled.** `origin` is SYNTHETIC_DEMO on every row of every
candidate relation, the release ids say `whatif`, and no document produced from
them may call these bank outputs or the macro paths observed history.

Determinism is the accepted generators' contract, kept: a seeded `random` for
the book's shape, `stable()` for anything that must be a pure function of
(entity, period), `totals.exact_total` for every float sum, and two builds of
the same release id produce byte-identical parquet.
"""

from __future__ import annotations

import hashlib

from backend.cockpit_v4.generate import month_range, quarter_range

#: Distinct from the accepted books' seeds (20260803 / 20260802) so that a
#: candidate borrower is not the accepted book's borrower under a new name.
CORPORATE_SEED = 20260925
RETAIL_SEED = 20260926

#: Smaller than the accepted books on purpose. The candidate exists to carry a
#: macro panel, a term structure and a trainable target, not to restate the
#: accepted population: 3,000 facilities over 20 quarters is 60,000
#: facility-quarters, which is a real panel for a chronological split and
#: still publishes a term structure in tens of megabytes rather than hundreds.
CORPORATE_BORROWERS = 1_200
CORPORATE_FACILITIES_PER_BORROWER = (2, 3)
RETAIL_CUSTOMERS = 4_500
RETAIL_ACCOUNTS_PER_CUSTOMER = (1, 2)


def stable(text: str, modulus: int) -> int:
    """A repeatable integer from a string.

    The same device the accepted generators use, and for the same reason:
    `hash()` is randomised per process, so a build on Monday and a build on
    Tuesday would produce different parquet bytes from identical inputs and
    the fingerprint would certify nothing.
    """
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % modulus


def unit_interval(text: str) -> float:
    """A repeatable float in [0, 1) from a string.

    Eight hex digits is about seven significant decimal digits -- far finer
    than anything published here needs, and coarse enough to be exactly
    representable, so it cannot introduce a rounding tie of its own.
    """
    return stable(text, 10_000_000) / 10_000_000.0


def signed(text: str) -> float:
    """A repeatable float in [-1, 1) from a string."""
    return unit_interval(text) * 2.0 - 1.0


__all__ = ["CORPORATE_BORROWERS", "CORPORATE_FACILITIES_PER_BORROWER",
           "CORPORATE_SEED", "RETAIL_ACCOUNTS_PER_CUSTOMER",
           "RETAIL_CUSTOMERS", "RETAIL_SEED", "month_range", "quarter_range",
           "signed", "stable", "unit_interval"]
