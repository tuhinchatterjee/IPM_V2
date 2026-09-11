"""
Canonical Cockpit semantics: what a term means when it has one meaning.

The defect this exists for
--------------------------
A live run recorded these, honestly, as ambiguities:

    "Exposure read as reported EAD (ead_reported), not gross carrying amount."
    "Period not specified: using the latest populated quarter 2026Q2 against
     2026Q1."
    "ECL read as booked ECL (ecl_reported)."

Every one is a correct resolution, written down for the reader. None of them
is a question. But `Intent.may_execute` required an EMPTY ambiguities list, so
recording a resolution blocked the analysis that the resolution made possible.
Careful behaviour was penalised, and the only way to run was to say nothing.

So the three things get three names:

  * a BLOCKING AMBIGUITY is a term with two defensible readings that would
    produce materially different numbers. It stops execution and is worth one
    targeted question.
  * a RESOLVED ASSUMPTION is a choice that has been made and is being
    declared. It belongs in the trace and in the answer's own words. It does
    not stop anything.
  * a CANONICAL MAPPING is a term this domain already defines. It is not even
    a choice.

What is here, and what is not
-----------------------------
Only mappings the catalogue supports. Nothing in this module invents a meaning,
and every entry names the field it resolves to so a reader can check it against
`inspect_catalog`. Where the catalogue genuinely offers two readings -- the
bare word "exposure" is the real case -- there is no canonical mapping and the
term is listed as one that needs a question.
"""

from __future__ import annotations

import re
from typing import Any

#: term -> (relation, field, what it means, why this and not the other)
#: Every field here exists in `cockpit_facility_quarter` in the pinned
#: release. A term whose field is absent from a release is dropped from the
#: mapping rather than offered and then failing to bind.
_MEASURES: tuple[tuple[str, str, str, str, str], ...] = (
    ("exposure at default", "cockpit_facility_quarter", "ead_reported",
     "Reported exposure at default.",
     "EAD has one recorded meaning in this domain. `ead_pit` and `ead_ttc` "
     "are model parameters, not the reported figure."),
    ("ead", "cockpit_facility_quarter", "ead_reported",
     "Reported exposure at default.",
     "The same field. `ead_pit` and `ead_ttc` are parameters."),
    ("ecl", "cockpit_facility_quarter", "ecl_reported",
     "Booked expected credit loss as reported.",
     "`ecl_modelled` is the model's output before overlay and "
     "`ecl_overlay` is the adjustment; the booked figure is what the book "
     "carries."),
    ("expected credit loss", "cockpit_facility_quarter", "ecl_reported",
     "Booked expected credit loss as reported.",
     "As for ECL."),
    ("12-month ecl", "cockpit_facility_quarter", "ecl_12m_reported",
     "Reported 12-month ECL.", "Named explicitly by the question."),
    ("lifetime ecl", "cockpit_facility_quarter", "ecl_lifetime_reported",
     "Reported lifetime ECL.", "Named explicitly by the question."),
    ("ecl coverage", "cockpit_facility_quarter", "ecl_coverage_ratio",
     "Reported ECL coverage ratio.",
     "The recorded ratio. Computing ECL/EAD instead is a different figure "
     "and must be described as one."),
    ("gross carrying amount", "cockpit_facility_quarter",
     "gross_carrying_amount", "Gross carrying amount as recorded.",
     "A balance-sheet measure, distinct from EAD."),
    ("drawn balance", "cockpit_facility_quarter", "drawn_balance",
     "Drawn balance.", "Distinct from both EAD and gross carrying amount."),
    ("stage", "cockpit_facility_quarter", "ifrs9_stage",
     "IFRS 9 stage, recorded as 1, 2 or 3.",
     "The recorded stage. `sicr_flag` is the trigger, not the stage."),
    ("stage 1", "cockpit_facility_quarter", "ifrs9_stage",
     "ifrs9_stage = 1.", "Performing, 12-month ECL."),
    ("stage 2", "cockpit_facility_quarter", "ifrs9_stage",
     "ifrs9_stage = 2.",
     "Significant increase in credit risk, lifetime ECL."),
    ("stage 3", "cockpit_facility_quarter", "ifrs9_stage",
     "ifrs9_stage = 3.", "Credit-impaired, lifetime ECL."),
    ("pd", "cockpit_facility_quarter", "pd_pit_12m",
     "Point-in-time 12-month probability of default.",
     "The point-in-time 12-month PD is the reporting default. "
     "`pd_pit_lifetime`, `pd_ttc_12m` and the at-origination variants are "
     "different measures and must be named."),
    ("lgd", "cockpit_facility_quarter", "lgd_pit",
     "Point-in-time loss given default.",
     "`lgd_ttc` and `lgd_downturn` are different measures and must be "
     "named."),
    ("sector", "cockpit_facility_quarter", "sector_name",
     "Recorded sector name. `sector_code` is the same dimension by code.",
     "The only segment dimension in this release. There is no subsegment."),
    ("segment", "cockpit_facility_quarter", "sector_name",
     "Sector, the only segment dimension this release records.",
     "No subsegment level exists; do not imply one."),
    ("borrower", "cockpit_facility_quarter", "borrower_id",
     "Borrower, identified by borrower_id with borrower_name for display.",
     "One borrower may hold several facilities: a facility-grain sum "
     "repeats nothing, but a borrower-grain measure needs an explicit "
     "aggregation."),
    ("customer", "cockpit_facility_quarter", "borrower_id",
     "The same as borrower in this domain.", "One recorded counterparty."),
    ("facility", "cockpit_facility_quarter", "facility_id",
     "Facility, the grain of cockpit_facility_quarter.",
     "One row per facility per reporting quarter."),
    ("days past due", "cockpit_facility_quarter", "days_past_due",
     "Days past due at the reporting date.", "Recorded, not derived."),
    ("collateral coverage", "cockpit_facility_quarter",
     "collateral_coverage_ratio", "Recorded collateral coverage ratio.",
     "Allocated net collateral value over the coverage denominator, as "
     "recorded."),
    ("rating", "cockpit_rating_ratio_quarter", "risk_rating",
     "Internal risk rating, with rating_rank as its ordinal.",
     "Borrower grain. A lower rank is a stronger grade."),
)

#: Terms with more than one defensible reading in this catalogue. These are
#: the ones worth a question, and the only ones.
AMBIGUOUS_TERMS: dict[str, tuple[str, ...]] = {
    "exposure": ("ead_reported", "gross_carrying_amount", "drawn_balance"),
}

_PERIOD_PHRASES = {
    "latest quarter": "latest_quarter",
    "latest reporting quarter": "latest_quarter",
    "most recent quarter": "latest_quarter",
    "this quarter": "latest_quarter",
    "current quarter": "latest_quarter",
    "previous quarter": "prior_quarter",
    "prior quarter": "prior_quarter",
    "last quarter": "prior_quarter",
    "quarter on quarter": "quarter_on_quarter",
    "quarter-on-quarter": "quarter_on_quarter",
    "over the latest quarter": "quarter_on_quarter",
    "latest-quarter change": "quarter_on_quarter",
    "latest year": "year_on_year",
    "over the latest year": "year_on_year",
    "last year": "year_on_year",
    "year on year": "year_on_year",
    "year-on-year": "year_on_year",
    "past year": "year_on_year",
}


def measures(catalog: Any = None) -> list[dict[str, str]]:
    """The canonical measure mappings this release can actually honour."""
    out: list[dict[str, str]] = []
    for term, relation, field, meaning, note in _MEASURES:
        if catalog is not None:
            try:
                if field not in set(catalog.columns(relation)):
                    continue
            except Exception:  # noqa: BLE001
                continue
        out.append({"term": term, "relation": relation, "field": field,
                    "means": meaning, "note": note})
    return out


def populated_quarters(catalog: Any) -> list[str]:
    calendar = getattr(catalog, "calendar", None)
    return [str(q) for q in (getattr(calendar, "populated", ()) or ())]


def periods(catalog: Any) -> dict[str, Any]:
    """Deterministic period resolution for this release's own calendar.

    "Latest quarter" is the latest POPULATED quarter, not the latest slot the
    calendar defines: a quarter with no rows is not a reporting period, and
    silently comparing against one produces a movement that is entirely an
    artefact of coverage.
    """
    quarters = populated_quarters(catalog)
    if not quarters:
        return {"populated_quarters": [], "resolution": {}}
    latest = quarters[-1]
    prior = quarters[-2] if len(quarters) >= 2 else ""
    year_ago = quarters[-5] if len(quarters) >= 5 else ""
    return {
        "populated_quarters": quarters,
        "latest_quarter": latest,
        "prior_quarter": prior,
        "same_quarter_last_year": year_ago,
        "resolution": {
            "latest quarter": latest,
            "previous quarter": prior,
            "quarter on quarter": (f"{latest} vs {prior}" if prior else ""),
            "latest year (for a quarterly comparison)":
                (f"{latest} vs {year_ago}" if year_ago else ""),
        },
        "rule": (
            "'Latest quarter' is the latest POPULATED reporting quarter. A "
            "latest-quarter CHANGE is that quarter against the previous "
            "populated one. 'Over the latest year', for a quarterly measure, "
            "is that quarter against the same quarter one year earlier. These "
            "are resolutions, not assumptions to ask about."),
    }


def period_phrases(question: str) -> list[str]:
    """Which period phrases the question actually used. Deterministic."""
    text = re.sub(r"\s+", " ", (question or "").lower())
    found = []
    for phrase, kind in _PERIOD_PHRASES.items():
        if phrase in text and kind not in found:
            found.append(kind)
    return found


def ambiguous_terms_in(question: str) -> list[dict[str, Any]]:
    """Terms that genuinely need a question, if the user used one of them.

    "Exposure at default" contains the word "exposure" and is NOT ambiguous,
    so the longer canonical term is checked first and wins.
    """
    text = re.sub(r"\s+", " ", (question or "").lower())
    canonical = [term for term, *_ in _MEASURES if term in text]
    out = []
    for term, options in AMBIGUOUS_TERMS.items():
        if not re.search(rf"\b{re.escape(term)}\b", text):
            continue
        if any(term in longer and longer != term for longer in canonical):
            continue
        out.append({"term": term, "candidate_fields": list(options)})
    return out


def block(catalog: Any) -> dict[str, Any]:
    """The semantics block carried in the starting context."""
    return {
        "canonical_measures": measures(catalog),
        "periods": periods(catalog),
        "terms_needing_a_question": {
            term: {"candidate_fields": list(options),
                   "why": ("The catalogue records all three and they are "
                           "materially different figures. 'Exposure at "
                           "default' is NOT this case: it is EAD.")}
            for term, options in AMBIGUOUS_TERMS.items()},
        "how_to_use": (
            "These are resolutions, not assumptions to ask about. Declare "
            "them in canonical_mappings or resolved_assumptions and proceed. "
            "Reserve blocking_ambiguities for a term with two defensible "
            "readings that would produce materially different numbers."),
    }


__all__ = ["AMBIGUOUS_TERMS", "ambiguous_terms_in", "block", "measures",
           "period_phrases", "periods", "populated_quarters"]
