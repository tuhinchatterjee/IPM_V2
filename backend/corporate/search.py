"""Borrower and cohort search. B6.

Three shapes of answer, not one:

``single``    one borrower, found by an identifier or an exact name.
``multi``     a named list of borrowers a user assembled themselves.
``segment``   everything matching a set of attribute filters.

They are separate because what a user wants BACK differs. A single borrower
opens its 360. A hand-picked list of five wants them side by side. A segment
of four hundred wants an aggregate first and the list second - rendering four
hundred cards is not an answer to "show me contracting in Riyadh".

Matching
--------
Identifier fields match exactly; name fields match on a normalised contains.
Arabic is searched on the raw string rather than the normalised one, because
the normaliser strips Latin legal-form words and does nothing useful to an
Arabic name - running it there would be a no-op dressed up as handling.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from backend.corporate.resolution import normalise

logger = logging.getLogger(__name__)

SEARCH_VERSION = "1.0.0"

SINGLE = "single"
MULTI = "multi"
SEGMENT = "segment"
COHORT_KINDS: tuple[str, ...] = (SINGLE, MULTI, SEGMENT)

#: Fields matched by an exact, case-insensitive comparison.
IDENTIFIER_FIELDS: tuple[str, ...] = (
    "borrower_id", "customer_number",
)
#: Fields matched by a normalised substring.
NAME_FIELDS: tuple[str, ...] = (
    "legal_name", "display_name", "alias",
)
#: Searched raw. The Latin normaliser does nothing here.
ARABIC_FIELDS: tuple[str, ...] = ("arabic_name",)
#: Attribute filters, each an exact match against a value the user picked.
FACET_FIELDS: tuple[str, ...] = (
    "group_id", "segment", "sub_segment", "sector", "sub_sector", "region",
    "city", "internal_rating", "stage", "relationship_manager",
    "business_unit", "limit_status", "delinquency_bucket",
)
#: Boolean facets, filtered when set to true.
FLAG_FIELDS: tuple[str, ...] = (
    "watchlist_flag", "breach_flag", "default_flag", "collections_flag",
    "stale_data_flag", "investigation_trigger", "forbearance_flag",
)

SEARCHABLE: tuple[str, ...] = (
    *IDENTIFIER_FIELDS, *NAME_FIELDS, *ARABIC_FIELDS, *FACET_FIELDS,
    *FLAG_FIELDS,
)

#: Above this many matches a segment answer leads with the aggregate.
AGGREGATE_FIRST_ABOVE = 25
#: Never return more rows than this in one page.
PAGE_LIMIT = 200


@dataclass
class Query:
    """What was asked for."""

    text: str = ""
    borrower_ids: list[str] = field(default_factory=list)
    facets: dict[str, Any] = field(default_factory=dict)
    flags: list[str] = field(default_factory=list)
    period: str = ""
    limit: int = 50

    def kind(self) -> str:
        if len(self.borrower_ids) > 1:
            return MULTI
        if self.facets or self.flags:
            return SEGMENT
        return SINGLE


class UnknownFacetError(ValueError):
    """A filter was asked for on a field the snapshot does not carry."""


def search(snapshot: pd.DataFrame, query: Query) -> dict[str, Any]:
    """Run one search and return the matches with what they mean.

    Returns the cohort KIND alongside the rows, so the caller renders the
    right thing rather than inferring it from a row count - a segment that
    happens to match one borrower is still a segment, and offering it as "the
    borrower you were looking for" would be wrong.
    """
    for name in (*query.facets, *query.flags):
        if name not in SEARCHABLE:
            raise UnknownFacetError(
                f"'{name}' is not a searchable field. B6 searches "
                f"{', '.join(SEARCHABLE)}.")

    frame = snapshot
    if query.period:
        frame = frame[frame["period"] == query.period]
    elif "period" in frame.columns and len(frame):
        # Default to the latest quarter present. A search across sixteen
        # quarters returns each borrower sixteen times, which is never what
        # "find Al Waha" means.
        frame = frame[frame["period"] == sorted(frame["period"].unique())[-1]]

    if query.borrower_ids:
        frame = frame[frame["borrower_id"].isin(query.borrower_ids)]

    if query.text:
        frame = frame[_text_mask(frame, query.text)]

    for name, value in query.facets.items():
        wanted = value if isinstance(value, list | tuple | set) else [value]
        frame = frame[frame[name].astype(str).isin([str(v) for v in wanted])]

    for name in query.flags:
        frame = frame[frame[name].astype(str).str.lower().isin(
            ["true", "1"])]

    kind = query.kind()
    total = len(frame)
    limit = min(max(query.limit, 1), PAGE_LIMIT)
    rows = frame.head(limit)

    result: dict[str, Any] = {
        "search_version": SEARCH_VERSION,
        "cohort_kind": kind,
        "matched": total,
        "returned": len(rows),
        "truncated": total > len(rows),
        "period": (str(frame["period"].iloc[0]) if len(frame)
                   else query.period),
        "lead_with_aggregate": kind == SEGMENT and total > AGGREGATE_FIRST_ABOVE,
        "borrowers": rows[[
            c for c in ("borrower_id", "legal_name", "display_name",
                        "arabic_name", "segment", "sector", "region",
                        "internal_rating", "stage", "ifrs9_ead",
                        "watchlist_flag")
            if c in rows.columns]].to_dict("records"),
    }
    if kind == SEGMENT and total:
        result["aggregate"] = aggregate(frame)

    # A single-borrower lookup that matched several names has NOT found the
    # borrower - it has found candidates. Names in this book share stems, so
    # "Al Waha Trading" legitimately matches six companies, and returning the
    # first one as though it were the answer is how a screen ends up showing
    # somebody else's exposure under the name that was typed.
    if kind == SINGLE:
        result["ambiguous"] = total > 1
        result["resolved"] = total == 1

    # A named cohort that came back short dropped members, and which ones is
    # the useful part: a borrower absent from this quarter has exited or has
    # not arrived, and that is an answer rather than an omission.
    if kind == MULTI:
        found = set(frame["borrower_id"])
        result["requested"] = len(query.borrower_ids)
        result["not_found"] = sorted(set(query.borrower_ids) - found)
        result["not_found_note"] = (
            "Not on book in this quarter. A borrower that has exited or has "
            "not yet arrived is absent by design, not missing."
            if result["not_found"] else "")
    return result


def _text_mask(frame: pd.DataFrame, text: str) -> pd.Series:
    """Identifier equality, then EXACT name, then contains, then Arabic.

    The exact-name tier exists because without it a full legal name is
    ambiguous with its own siblings. Names in this book share stems -
    "Al Nahda Ventures Company" and "Al Nahda Ventures Company 3" - and a
    pure substring match makes typing a borrower's complete name return
    several candidates and resolve none of them. Typing the whole name is the
    least ambiguous thing a user can do, and it was the worst-served.

    An exact match SUPPRESSES the substring tier rather than adding to it.
    Ranking them together would still leave the answer among candidates,
    which is the same failure with better ordering.
    """
    wanted = str(text).strip()
    mask = pd.Series(False, index=frame.index)

    for name in IDENTIFIER_FIELDS:
        if name in frame.columns:
            mask |= frame[name].astype(str).str.casefold() == wanted.casefold()
    if mask.any():
        return mask

    normalised = normalise(wanted)
    if normalised:
        exact = pd.Series(False, index=frame.index)
        for name in NAME_FIELDS:
            if name in frame.columns:
                exact |= (frame[name].astype(str).map(normalise)
                          == normalised)
        if exact.any():
            return exact

        for name in NAME_FIELDS:
            if name in frame.columns:
                mask |= (frame[name].astype(str).map(normalise)
                         .str.contains(normalised, regex=False, na=False))

    for name in ARABIC_FIELDS:
        if name in frame.columns:
            mask |= frame[name].astype(str).str.contains(
                wanted, regex=False, na=False)
    return mask


def aggregate(frame: pd.DataFrame) -> dict[str, Any]:
    """What a segment looks like, before its members are listed.

    Sums where summing is meaningful and an EXPOSURE-WEIGHTED mean where it is
    not: an unweighted average PD over four hundred borrowers is dominated by
    the smallest ones and answers a question nobody asked.
    """
    ead = pd.to_numeric(frame.get("ifrs9_ead"), errors="coerce").fillna(0.0)
    total_ead = float(ead.sum())

    def weighted(column: str) -> float | None:
        if column not in frame.columns or total_ead <= 0:
            return None
        values = pd.to_numeric(frame[column], errors="coerce").fillna(0.0)
        return round(float((values * ead).sum() / total_ead), 4)

    stages = (frame["stage"].value_counts().sort_index().to_dict()
              if "stage" in frame.columns else {})
    return {
        "borrowers": int(frame["borrower_id"].nunique()),
        "total_ead": round(total_ead, 2),
        "total_ecl": round(float(pd.to_numeric(
            frame.get("final_ecl"), errors="coerce").fillna(0.0).sum()), 2),
        "exposure_weighted_pd_12m": weighted("pd_12m"),
        "exposure_weighted_ecl_coverage": weighted("ecl_coverage"),
        "stage_mix": {str(k): int(v) for k, v in stages.items()},
        "watchlist": int(pd.Series(
            frame.get("watchlist_flag", pd.Series(dtype=bool))
        ).astype(str).str.lower().isin(["true", "1"]).sum()),
        "weighting_note": (
            "Averages are exposure weighted. An unweighted mean across a "
            "segment is dominated by its smallest borrowers."),
    }


def catalogue() -> dict[str, Any]:
    """B6, for the screen: what can be searched and what comes back."""
    return {
        "search_version": SEARCH_VERSION,
        "cohort_kinds": list(COHORT_KINDS),
        "identifier_fields": list(IDENTIFIER_FIELDS),
        "name_fields": list(NAME_FIELDS),
        "arabic_fields": list(ARABIC_FIELDS),
        "facet_fields": list(FACET_FIELDS),
        "flag_fields": list(FLAG_FIELDS),
        "searchable_field_count": len(SEARCHABLE),
        "page_limit": PAGE_LIMIT,
        "aggregate_first_above": AGGREGATE_FIRST_ABOVE,
    }
