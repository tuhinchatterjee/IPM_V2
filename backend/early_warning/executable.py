"""
What this domain can actually DO, in one place.

The defect this module exists to end
------------------------------------
There were two registries. `grain.GROUPINGS` told a planner which fields the
book could be partitioned by; `facts.LEVEL_FIELDS` decided which ones the
execution layer would accept. They agreed on most entries and disagreed on
four, and nothing checked. A live Opus plan grouped by `dominant_subcategory`
— a real field, in the dictionary, advertised as a grouping — passed validation
and then raised `KeyError` inside the fact builder, which took the whole
conversational turn with it.

That is not a missing string. It is what two sources of truth for one
capability always eventually produce: a validator that approves what the
executor cannot run, and a crash at the seam between them.

So there is one registry, and everything reads it. `facts.LEVEL_FIELDS` is
built from it, the grain package advertises it, the validator checks against
it, and the planner is shown it. A grouping added here becomes executable,
advertised and validated in the same commit; one that cannot be executed
cannot be advertised, because there is nowhere left to advertise it from.

Being described is not being executable
---------------------------------------
The field dictionary describes 2,521 columns. Almost all of them can be read
as a measure, a filter or a sort key. Very few make sense as a *partition* of
the book: grouping three hundred obligors by `sig042_covenant_breach_event_
score` produces three hundred groups of one. So capability is recorded per
ROLE — what a field may be used AS — rather than as one flag per field.

Aliases are a governed map, not a search
----------------------------------------
Every entry below is a name a credit officer or a planner genuinely uses for
the same thing: "grade" for the internal rating, "stage" for the IFRS 9 stage.
Each maps to exactly one canonical field. There is no fuzzy matching and no
substring rule, because an alias that guesses is a way for a plan to run
against a field nobody asked for and for the answer to say nothing about it.
"""

from __future__ import annotations

import functools
from typing import Any

#: What the book can be partitioned by, and what each level is called.
#:
#: The test of membership is not "is this field in the dictionary" but "can
#: `facts.level` return a row per value of it". Everything here is either
#: stored on the borrower-month row or derived by `facts._with_derived`, and
#: `tests/early_warning/test_executable_contract.py` runs every one of them.
GROUPINGS: dict[str, str] = {
    "segment": "Corporate segment",
    "sector": "Sector",
    "region": "Region",
    "relationship_manager": "Relationship manager",
    "internal_rating": "Internal grade",
    "ifrs9_stage": "IFRS 9 stage",
    "ews_band": "Early Warning band",
    "ta_band": "T&A band",
    "classifier_band": "Classifier band",
    "dominant_layer": "Dominant layer",
    "dominant_subcategory": "Dominant sub-category",
    "utilisation_band": "Utilisation band",
}

#: Groupings that are computed at read time rather than stored. Recorded
#: because the fact builder has to add the column before it can group by it,
#: and a derived level that nobody derives is exactly the crash this module
#: exists to prevent.
DERIVED_GROUPINGS: frozenset[str] = frozenset({
    "dominant_layer", "utilisation_band"})

#: Groupings whose values are absent for part of the book. `dominant_subcategory`
#: is empty for an obligor with no fired signal — which is most of them in a
#: quiet month — and a groupby would silently drop those rows, reporting a
#: partition of the book that is not the book.
NULLABLE_GROUPINGS: frozenset[str] = frozenset({"dominant_subcategory"})

#: What an absent value becomes, so those obligors are counted rather than
#: dropped.
NO_VALUE = "none"

#: One name for one field. Every entry is a term a credit officer or a planner
#: genuinely uses; each maps to exactly one canonical field. Nothing here is
#: fuzzy, and nothing is here to make a particular model output pass.
FIELD_ALIASES: dict[str, str] = {
    # The internal grade has three names in the bank and one in the data.
    "grade": "internal_rating",
    "rating": "internal_rating",
    "internal_grade": "internal_rating",
    "risk_grade": "internal_rating",
    # IFRS 9 staging, written every way the standard is written.
    "stage": "ifrs9_stage",
    "ifrs_9_stage": "ifrs9_stage",
    "ifrs9stage": "ifrs9_stage",
    # "Band" and "severity" both mean the final Early Warning band.
    "band": "ews_band",
    "severity": "ews_band",
    "severity_band": "ews_band",
    "ews_severity": "ews_band",
    "early_warning_band": "ews_band",
    # The score, under its long name.
    "early_warning_score": "ews_score",
    "ews": "ews_score",
    # Sector and industry are the same partition of the book.
    "industry": "sector",
    # Region, under the names an operating model gives it.
    "branch": "region",
    "geography": "region",
    "governorate": "region",
    # The relationship manager, abbreviated.
    "rm": "relationship_manager",
    "account_manager": "relationship_manager",
    # The node, written as the model writes it and as the workbook writes it.
    "sub_category": "dominant_subcategory",
    "subcategory": "dominant_subcategory",
    "dominant_sub_category": "dominant_subcategory",
    "dominant_node": "dominant_subcategory",
    # The layer.
    "layer": "dominant_layer",
    "dominant_layer_code": "dominant_layer",
    # The signal that carries the position.
    "dominant_signal": "dominant_driver",
    "driver": "dominant_driver",
    # Exposure, under the name the credit book uses for it.
    "ead": "exposure",
    "drawn_exposure": "exposure",
    "outstanding": "exposure",
}

#: Aliases that mean something different when the field is a PARTITION.
#:
#: "Group by utilisation" cannot mean the percentage — that is three hundred
#: groups of one. It means the band, and the band is a real field. The same
#: word as a MEASURE means the percentage, which is why this is separate from
#: the map above rather than merged into it.
GROUPING_ALIASES: dict[str, str] = {
    "utilisation": "utilisation_band",
    "utilisation_pct": "utilisation_band",
    "usage": "utilisation_band",
    # The severity band as a reader NAMES it, where `FIELD_ALIASES` below
    # does not already have the spelling. "Distribution by risk band" is the
    # first question anybody asks of this product, and "risk band" resolved to
    # nothing — so the grouping was dropped and the question was answered at
    # population level, without the five band counts it asked for.
    #
    # Only the spellings the field map does not already carry: "band",
    # "severity" and "severity_band" are there, and repeating them here would
    # put one capability in two registries, which is the thing this module
    # exists to stop.
    "risk_band": "ews_band",
    "ews_score_band": "ews_band",
    "credit_band": "ews_band",
}

#: The roles a field can be used in. Named because the answer differs by
#: role: `exposure` is a fine measure and a meaningless partition.
GROUP_BY = "group_by"
MEASURE = "measure"
FILTER = "filter"
ORDER_BY = "order_by"
ROLES: tuple[str, ...] = (GROUP_BY, MEASURE, FILTER, ORDER_BY)


@functools.lru_cache(maxsize=1)
def readable() -> frozenset[str]:
    """Every field the executor can read off a row.

    The wide view, which the dictionary describes exactly. A measure, a
    filter or a sort key must be one of these.
    """
    from backend.early_warning import dictionary as dic

    return dic.names()


def groupable() -> frozenset[str]:
    return frozenset(GROUPINGS)


def normalise(name: str, *, role: str = MEASURE) -> str:
    """The canonical field a name refers to, or the name unchanged.

    Exact lookups only. A name this map does not know comes back untouched,
    so the validator refuses it by the name the planner actually wrote —
    which is the name that has to appear in the repair packet for the repair
    to mean anything.
    """
    text = (name or "").strip().lower().replace(" ", "_").replace("-", "_")
    if not text:
        return ""
    if role == GROUP_BY:
        if text in GROUPINGS:
            return text
        aliased = GROUPING_ALIASES.get(text)
        if aliased:
            return aliased
    aliased = FIELD_ALIASES.get(text)
    if aliased:
        return aliased
    return text


def supports(name: str, *, role: str) -> bool:
    """Whether a canonical field can be used in this role."""
    if role == GROUP_BY:
        return name in GROUPINGS
    return name in readable()


def alternatives(name: str, *, role: str, limit: int = 8) -> list[str]:
    """What could have been meant, for the repair packet.

    For a grouping this is the whole list, because there are twelve of them
    and a planner given all twelve does not have to guess. For a measure it
    is the nearest names by shared words, because there are two and a half
    thousand and the whole list is not an answer.
    """
    if role == GROUP_BY:
        return sorted(GROUPINGS)
    return _nearest(name, readable(), limit)


def _nearest(name: str, known: frozenset[str], limit: int) -> list[str]:
    """The closest real field names, scored on shared words.

    Words rather than letters: scored on letters, `ews_rating` suggested
    `relationship_manager`, which shares eleven of them and nothing else.
    """
    words = set((name or "").lower().split("_"))
    if not words:
        return []
    scored: list[tuple[int, str]] = []
    for candidate in known:
        parts = candidate.split("_")
        shared = len(words & set(parts))
        if not shared:
            continue
        # A shared trailing word — `_score`, `_band` — usually means the same
        # KIND of field, which is what a planner reaching for a name it half
        # remembers actually wants.
        bonus = 1 if parts[-1:] == list(words)[-1:] else 0
        scored.append((shared * 2 + bonus, candidate))
    scored.sort(key=lambda s: (-s[0], s[1]))
    return [name for _, name in scored[:limit]]


def describe() -> dict[str, Any]:
    """The capability surface, for the grain package and the tests."""
    return {
        "groupings": dict(GROUPINGS),
        "derived_groupings": sorted(DERIVED_GROUPINGS),
        "nullable_groupings": sorted(NULLABLE_GROUPINGS),
        "readable_fields": len(readable()),
        "field_aliases": dict(FIELD_ALIASES),
        "grouping_aliases": dict(GROUPING_ALIASES),
        "note": ("One registry. A grouping listed here is executable by "
                 "`facts.level`, advertised by the grain package and enforced "
                 "by the validator, because all three read this."),
    }


__all__ = ["DERIVED_GROUPINGS", "FIELD_ALIASES", "FILTER", "GROUPINGS",
           "GROUPING_ALIASES", "GROUP_BY", "MEASURE", "NO_VALUE",
           "NULLABLE_GROUPINGS", "ORDER_BY", "ROLES", "alternatives",
           "describe", "groupable", "normalise", "readable", "supports"]
