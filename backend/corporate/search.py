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

#: Fields a cohort may be ordered by, and what each one means on screen. §18.
#:
#: A closed list, for two reasons. A caller cannot ask the snapshot to order
#: by a column it happens to carry but nobody governs — `betweenness` is real,
#: is numeric, and ranking a credit book by it would be nonsense on a screen.
#: And each entry says which DIRECTION is the worrying one, so "highest PD
#: first" does not have to be spelled by every caller and cannot be spelled
#: backwards by one.
ORDERABLE: dict[str, str] = {
    "pd_12m": "12-month probability of default",
    "pd_lifetime": "Lifetime probability of default",
    "final_ecl": "Expected credit loss",
    "ecl_coverage": "ECL coverage",
    "ifrs9_ead": "Exposure at default",
    "stage": "IFRS 9 stage",
    "current_dpd": "Days past due",
    "max_dpd_12m": "Worst days past due in 12 months",
    "arrears_amount": "Arrears",
    "single_name_utilisation_pct": "Single-name limit utilisation",
    "group_utilisation_pct": "Group limit utilisation",
    "average_headroom_pct": "Average covenant headroom",
    "minimum_headroom_pct": "Minimum covenant headroom",
    "collateral_coverage_pct": "Collateral coverage",
    "collateral_shortfall": "Collateral shortfall",
    "covenants_breached": "Covenants breached",
    "connected_group_size": "Connected group size",
}

#: Where a LOW value is the worrying one, so a preset asking for "the worst"
#: sorts ascending without every caller having to know which way round it is.
LOWER_IS_WORSE: frozenset[str] = frozenset({
    "average_headroom_pct", "minimum_headroom_pct", "collateral_coverage_pct",
})

#: What a cohort is ordered by when nobody says. §18: a Borrower 360 landing
#: page that opens on an arbitrary slice of the book is a search box with rows
#: under it, and the first thing a credit officer wants is the riskiest names.
DEFAULT_ORDER = "pd_12m"

#: Every ordering ends here. Two borrowers on the same PD must not come back
#: in whichever order the frame happened to hold them, or the same page shows
#: a different tenth name on a second visit. §11.
TIE_BREAK = "borrower_id"

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
    #: Empty means DEFAULT_ORDER for a cohort, and no reordering for a name
    #: lookup — which is already ranked by how well each row matched.
    order_by: str = ""
    #: None means "whichever direction is the worrying one for this field".
    descending: bool | None = None

    def kind(self) -> str:
        if len(self.borrower_ids) > 1:
            return MULTI
        if self.facets or self.flags:
            return SEGMENT
        return SINGLE


class UnknownFacetError(ValueError):
    """A filter was asked for on a field the snapshot does not carry."""


class UnknownOrderError(ValueError):
    """A cohort was asked to be ordered by something ungoverned."""


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
    frame, ordered_by, ordered_desc = _order(frame, query, kind)
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
        "ordered_by": ordered_by,
        "ordered_descending": ordered_desc,
        "order_label": ORDERABLE.get(ordered_by, ""),
        "borrowers": rows[[
            c for c in COHORT_COLUMNS if c in rows.columns]].to_dict("records"),
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


#: What a cohort row carries, in reading order. §18 asks for the borrower,
#: its identity, where it sits, how it is rated, what it owes, what it is
#: provisioned at, how drawn it is, and whether anybody has flagged it — which
#: is what a credit officer scans a list of names for.
COHORT_COLUMNS: tuple[str, ...] = (
    "borrower_id", "legal_name", "display_name", "arabic_name",
    "segment", "sector", "region", "internal_rating", "stage",
    "pd_12m", "ifrs9_ead", "final_ecl", "ecl_coverage",
    "single_name_utilisation_pct", "current_dpd", "arrears_amount",
    "average_headroom_pct", "collateral_coverage_pct",
    "connected_group_id", "group_name",
    "watchlist_flag", "breach_flag", "default_flag",
)


def _order(frame: pd.DataFrame, query: Query,
           kind: str) -> tuple[pd.DataFrame, str, bool]:
    """Put a cohort in a governed, repeatable order. §18, §11.

    A NAME LOOKUP is left alone: it is already ordered by how well each row
    matched, and re-sorting it by exposure would bury the borrower somebody
    typed the name of. Everything else is a cohort, INCLUDING the empty query
    — which is the whole book, and is exactly what the Borrower 360 landing
    page asks for. `Query.kind()` calls that SINGLE because it names no facet;
    the test here is whether TEXT was typed, which is the thing that makes an
    order meaningful in the first place.
    """
    del kind
    wanted = str(query.order_by or "").strip()
    if wanted and wanted not in ORDERABLE:
        raise UnknownOrderError(
            f"'{wanted}' is not a field a cohort can be ordered by. "
            f"Governed orderings: {', '.join(sorted(ORDERABLE))}.")
    if query.text and not wanted:
        return frame, "", False

    column = wanted or DEFAULT_ORDER
    if column not in frame.columns:
        return frame, "", False
    descending = (query.descending if query.descending is not None
                  else column not in LOWER_IS_WORSE)

    keys = [column]
    ascending = [not descending]
    if TIE_BREAK in frame.columns and TIE_BREAK != column:
        keys.append(TIE_BREAK)
        ascending.append(True)
    # `na_position="last"` on purpose: a borrower with no PD is not the
    # riskiest borrower in the book, and putting nulls first is exactly how a
    # ranking screen opens on the rows that carry the least information.
    return (frame.sort_values(keys, ascending=ascending, kind="mergesort",
                              na_position="last"),
            column, descending)


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
