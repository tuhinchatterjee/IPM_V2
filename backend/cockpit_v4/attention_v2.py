"""
What deserves attention in a book, decided the same way every time.

Deterministic, and zero model calls
-----------------------------------
This runs when a landing page loads. A page that costs a generation to
render is a page nobody can leave open, and a ranking that changes between
two loads of the same data is a ranking nobody can act on. So every number
here comes out of SQL over the pinned release and the ordering is a pure
function of those numbers.

Why it is domain-aware rather than domain-agnostic
--------------------------------------------------
A corporate book is watched by SECTOR: a sector's Stage 2 migration, its ECL
movement, its rating drift, its covenant headroom. A retail book is watched
by PRODUCT, SCORE BAND, DELINQUENCY BUCKET and VINTAGE, because the
individual account only matters once one of those moves. Pretending the two
are the same shape -- "segments" with "metrics" -- would produce a retail
page that talks about sectors it does not have.

So each domain declares its own families. The RANKING is shared, because
"material and moving" means the same thing in both books; what is ranked is
not.

Materiality and movement, together
----------------------------------
A segment that doubled its ECL on two accounts is noise. A segment holding a
fifth of the book that moved two per cent is not. The score multiplies a
normalised movement by the segment's share of the book, so neither alone
gets to the top, and a segment too small to matter is dropped before scoring
rather than ranked and buried.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

from backend.cockpit_v4 import display as disp
from backend.cockpit_v4 import domains as dom

TOP_N = 5

#: A segment holding less than this share of the book is not a finding about
#: the book. It is still visible in a query; it is not worth a card.
MIN_SHARE = 0.01

#: Below this, a movement is indistinguishable from rounding.
MIN_MOVEMENT = 0.005

#: How many cards one lens may take. A book that moves moves every slice of
#: a dimension with it, and five cards from one dimension is one finding
#: with five headlines.
MAX_PER_DIMENSION = 2


class AttentionUnavailable(RuntimeError):
    """The feed could not be computed. Said plainly, never faked as empty."""


@dataclass(frozen=True)
class Family:
    """One way of watching a book: what to group by, and what to measure."""

    key: str
    label: str
    dimension: str
    dimension_label: str
    relation: str
    measure: str
    measure_label: str
    kind: str
    unit: str
    #: SQL fragment producing the measure, grouped by `dimension`.
    expression: str
    #: A weight the whole family carries: a Stage 2 migration is a louder
    #: signal than a utilisation drift even at the same magnitude.
    weight: float = 1.0
    direction: str = "up"
    #: How big this segment IS, for materiality. Exposure at default in
    #: almost every case -- but a relation that does not carry EAD needs its
    #: own answer rather than a crash or a silent zero.
    size_expression: str = "SUM(ead_sar_mn)"


def _corporate_families() -> tuple[Family, ...]:
    rel = "corp_facility_month"
    return (
        Family("sector_stage2", "Stage 2 exposure", "sector", "Sector", rel,
               "stage2_share", "Stage 2 share of EAD", "share", "percent",
               "SUM(CASE WHEN stage >= 2 THEN ead_sar_mn ELSE 0 END) "
               "/ NULLIF(SUM(ead_sar_mn), 0)", weight=1.30),
        Family("sector_ecl", "ECL", "sector", "Sector", rel,
               "ecl", "Recognised ECL", "amount", "SAR million",
               "SUM(ecl_sar_mn)", weight=1.20),
        Family("sector_coverage", "ECL coverage", "sector", "Sector", rel,
               "ecl_coverage", "ECL as a share of EAD", "share", "percent",
               "SUM(ecl_sar_mn) / NULLIF(SUM(ead_sar_mn), 0)", weight=1.05),
        Family("sector_pastdue", "Past due", "sector", "Sector", rel,
               "past_due_share", "Past-due share of EAD", "share", "percent",
               "SUM(CASE WHEN dpd_days > 0 THEN ead_sar_mn ELSE 0 END) "
               "/ NULLIF(SUM(ead_sar_mn), 0)", weight=1.10),
        Family("type_stage2", "Stage 2 exposure", "facility_type",
               "Facility type", rel,
               "stage2_share", "Stage 2 share of EAD", "share", "percent",
               "SUM(CASE WHEN stage >= 2 THEN ead_sar_mn ELSE 0 END) "
               "/ NULLIF(SUM(ead_sar_mn), 0)", weight=0.95),
        Family("region_ecl", "ECL", "region", "Region", rel,
               "ecl", "Recognised ECL", "amount", "SAR million",
               "SUM(ecl_sar_mn)", weight=0.90),
        Family("sector_ltv", "Collateral cover", "collateral_type",
               "Collateral type", "corp_collateral_month",
               "ltv", "EAD as a share of collateral value", "share",
               "percent",
               "SUM(ltv_pct) / NULLIF(COUNT(*) * 100.0, 0)", weight=1.00,
               size_expression="SUM(allocated_value_sar_mn)"),
    )


def _retail_families() -> tuple[Family, ...]:
    rel = "retail_account_month"
    return (
        Family("product_stage2", "Stage 2 exposure", "product", "Product",
               rel, "stage2_share", "Stage 2 share of EAD", "share",
               "percent",
               "SUM(CASE WHEN stage >= 2 THEN ead_sar_mn ELSE 0 END) "
               "/ NULLIF(SUM(ead_sar_mn), 0)", weight=1.30),
        Family("product_ecl", "ECL", "product", "Product", rel,
               "ecl", "Recognised ECL", "amount", "SAR million",
               "SUM(ecl_sar_mn)", weight=1.20),
        Family("product_delinquency", "Delinquency", "product", "Product",
               rel, "dpd_share", "Share of EAD past due", "share", "percent",
               "SUM(CASE WHEN dpd_days > 0 THEN ead_sar_mn ELSE 0 END) "
               "/ NULLIF(SUM(ead_sar_mn), 0)", weight=1.15),
        Family("band_stage2", "Stage 2 exposure", "score_band",
               "Behaviour score band", rel,
               "stage2_share", "Stage 2 share of EAD", "share", "percent",
               "SUM(CASE WHEN stage >= 2 THEN ead_sar_mn ELSE 0 END) "
               "/ NULLIF(SUM(ead_sar_mn), 0)", weight=1.10),
        Family("vintage_stage2", "Stage 2 exposure", "vintage_year",
               "Origination vintage", rel,
               "stage2_share", "Stage 2 share of EAD", "share", "percent",
               "SUM(CASE WHEN stage >= 2 THEN ead_sar_mn ELSE 0 END) "
               "/ NULLIF(SUM(ead_sar_mn), 0)", weight=1.00),
        Family("segment_ecl", "ECL", "customer_segment", "Customer segment",
               rel, "ecl", "Recognised ECL", "amount", "SAR million",
               "SUM(ecl_sar_mn)", weight=0.95),
    )


FAMILIES: dict[str, tuple[Family, ...]] = {
    dom.CORPORATE: _corporate_families(),
    dom.RETAIL: _retail_families(),
}

SECTION_LABELS: dict[str, str] = {
    dom.CORPORATE: "Segments requiring attention",
    dom.RETAIL: "Retail portfolio requiring attention",
}
HIGHLIGHT_LABELS: dict[str, str] = {
    dom.CORPORATE: "Latest-month ECL highlights",
    dom.RETAIL: "Latest-month retail ECL highlights",
}


@dataclass
class Candidate:
    family: Family
    segment: str
    now: float
    before: float
    ead_now: float
    ead_before: float
    share: float
    score: float = 0.0
    extras: dict[str, Any] = field(default_factory=dict)

    @property
    def movement(self) -> float:
        return self.now - self.before

    @property
    def relative(self) -> float:
        if self.before in (0, None):
            return 1.0 if self.now else 0.0
        return (self.now - self.before) / abs(self.before)


def _query(session, sql: str) -> list[dict[str, Any]]:
    cursor = session.connection.execute(sql)
    columns = [d[0] for d in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def _measure(session, family: Family, month: str) -> dict[str, dict[str, float]]:
    rows = _query(session, f"""
        SELECT CAST({family.dimension} AS VARCHAR) AS segment,
               {family.expression} AS value,
               {family.size_expression} AS ead
        FROM {family.relation}
        WHERE reporting_month = '{month}'
        GROUP BY 1
    """)
    return {str(r["segment"]): {"value": float(r["value"] or 0.0),
                                "ead": float(r["ead"] or 0.0)}
            for r in rows}


def _candidates(session, family: Family, *, month: str,
                comparison: str) -> list[Candidate]:
    now = _measure(session, family, month)
    before = _measure(session, family, comparison)
    total = sum(v["ead"] for v in now.values()) or 1.0

    out: list[Candidate] = []
    for segment, current in now.items():
        prior = before.get(segment)
        if prior is None:
            continue  # a segment that did not exist last month is not a move
        share = current["ead"] / total
        if share < MIN_SHARE:
            continue
        candidate = Candidate(
            family=family, segment=segment,
            now=current["value"], before=prior["value"],
            ead_now=current["ead"], ead_before=prior["ead"], share=share)
        movement = candidate.movement
        if family.kind == "amount":
            scale = max(abs(candidate.before), 1e-6)
            normalised = movement / scale
        else:
            normalised = movement
        if candidate.now <= candidate.before or abs(normalised) < MIN_MOVEMENT:
            continue
        # Material AND moving. Neither alone reaches the top.
        candidate.score = abs(normalised) * share * family.weight
        out.append(candidate)
    return out


def _spread(ordered: list[Candidate], *, limit: int) -> list[Candidate]:
    """Round-robin across dimensions, then backfill by score."""
    by_dimension: dict[str, list[Candidate]] = {}
    for candidate in ordered:
        by_dimension.setdefault(candidate.family.dimension,
                                []).append(candidate)

    # Dimensions take their turn strongest-first. Alphabetical order was the
    # first version and it decided, by nothing but the letter C, that a
    # collateral card outranked the strongest sector finding in the book.
    order = sorted(by_dimension,
                   key=lambda d: (-by_dimension[d][0].score, d))

    taken: list[Candidate] = []
    seen: set[int] = set()
    for rounds in range(MAX_PER_DIMENSION):
        for dimension in order:
            queue = by_dimension[dimension]
            if len(queue) > rounds and len(taken) < limit:
                taken.append(queue[rounds])
                seen.add(id(queue[rounds]))
    for candidate in ordered:
        if len(taken) >= limit:
            break
        if id(candidate) not in seen:
            taken.append(candidate)
            seen.add(id(candidate))
    return sorted(taken, key=lambda c: (-c.score, c.family.key, c.segment))


def _item_id(domain_id: str, family: str, segment: str, month: str) -> str:
    seed = f"{domain_id}|{family}|{segment}|{month}"
    return "att-" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]


def _shown(value: float, family: Family, currency: str, scale: str) -> str:
    if family.kind == "amount":
        return disp.format_value(_dec(value), f"{currency} {scale}")
    return disp.format_value(_dec(value * 100), "percent")


def _dec(value: float):
    from decimal import Decimal

    return Decimal(str(value))


def _item(candidate: Candidate, *, scope: dom.DomainScope,
          month: str, comparison: str) -> dict[str, Any]:
    family = candidate.family
    shown_now = _shown(candidate.now, family, scope.currency,
                       scope.amount_scale)
    shown_before = _shown(candidate.before, family, scope.currency,
                          scope.amount_scale)
    if family.kind == "amount":
        movement_text = (f"{disp.format_value(_dec(candidate.relative * 100), 'percent')}"
                         f" higher than {comparison}")
    else:
        movement_text = (
            f"{disp.format_value(_dec(candidate.movement * 100), 'percentage points')}"
            f" higher than {comparison}")
    return {
        "item_id": _item_id(scope.domain_id, family.key, candidate.segment,
                            month),
        "domain_id": scope.domain_id,
        "release_id": scope.release_id,
        "release_fingerprint": scope.release_fingerprint,
        "section": "attention",
        "family": family.key,
        # The family's label as written, not lower-cased: "ECL" is an
        # initialism and "ecl rose to" is how a card announces it was
        # assembled by string concatenation.
        "headline": (f"{candidate.segment}: {family.label} rose to "
                     f"{shown_now}"),
        "segment": candidate.segment,
        "segment_dimension": family.dimension,
        "segment_dimension_label": family.dimension_label,
        "metric": family.measure,
        "metric_label": family.measure_label,
        "reporting_quarter": month,
        "reporting_month": month,
        "comparison_quarter": comparison,
        "comparison_month": comparison,
        "comparison_basis": "previous month",
        "what_changed": (f"{family.measure_label} was {shown_before} in "
                         f"{comparison} and is {shown_now} in {month}."),
        "why_it_appeared": (
            f"It moved {movement_text} on a segment holding "
            f"{disp.format_value(_dec(candidate.share * 100), 'percent')} of "
            f"the book's exposure at default."),
        "movement": {
            "from": candidate.before, "to": candidate.now,
            "from_display": shown_before, "to_display": shown_now,
            "unit": family.unit,
        },
        "key_numbers": [
            {"label": f"{family.measure_label}, {month}",
             "display": shown_now},
            {"label": f"{family.measure_label}, {comparison}",
             "display": shown_before},
            {"label": f"Exposure at default, {month}",
             "display": disp.format_value(
                 _dec(candidate.ead_now),
                 f"{scope.currency} {scope.amount_scale}")},
            {"label": "Share of book",
             "display": disp.format_value(_dec(candidate.share * 100),
                                          "percent")},
        ],
        "evidence": {"relation": family.relation,
                     "dimension": family.dimension,
                     "measure": family.measure},
        "evidence_url": "",
        "drilldown": {"suggested_questions": _questions(candidate, scope,
                                                        month)},
        "severity": ("high" if candidate.score > 0.02
                     else "medium" if candidate.score > 0.005 else "low"),
        "score": round(candidate.score, 6),
    }


def _questions(candidate: Candidate, scope: dom.DomainScope,
               month: str) -> list[dict[str, Any]]:
    """What to ask next about THIS finding. Deterministic; no model call."""
    family = candidate.family
    segment = candidate.segment
    if scope.domain_id == dom.CORPORATE:
        return [
            {"question": f"Show the borrowers behind {segment} in {month}.",
             "required_fields": [], "required_quarters": [month],
             "kind": "drilldown"},
            {"question": f"Which {segment} facilities moved to Stage 2?",
             "required_fields": [], "required_quarters": [month],
             "kind": "drilldown"},
            {"question": f"How has {segment} ECL changed over the latest "
                         f"year?", "required_fields": [],
             "required_quarters": [], "kind": "trend"},
        ]
    return [
        {"question": f"Show the accounts behind {segment} in {month}.",
         "required_fields": [], "required_quarters": [month],
         "kind": "drilldown"},
        {"question": f"Which behaviour score bands drove {segment}?",
         "required_fields": [], "required_quarters": [month],
         "kind": "drilldown"},
        {"question": f"Is delinquency or utilisation driving {segment}?",
         "required_fields": [], "required_quarters": [month],
         "kind": "diagnostic"},
    ]


def _highlights(session, *, scope: dom.DomainScope, month: str,
                comparison: str) -> list[dict[str, Any]]:
    """The latest month's ECL, said four ways a reader actually asks for."""
    domain_id = scope.domain_id
    relation = ("corp_facility_month" if domain_id == dom.CORPORATE
                else "retail_account_month")
    dimension = "sector" if domain_id == dom.CORPORATE else "product"
    money = f"{scope.currency} {scope.amount_scale}"

    rows = _query(session, f"""
        SELECT CAST({dimension} AS VARCHAR) AS segment,
               SUM(ecl_sar_mn) AS ecl,
               SUM(ead_sar_mn) AS ead
        FROM {relation} WHERE reporting_month = '{month}'
        GROUP BY 1 ORDER BY 2 DESC
    """)
    prior = {r["segment"]: float(r["ecl"] or 0.0) for r in _query(session, f"""
        SELECT CAST({dimension} AS VARCHAR) AS segment,
               SUM(ecl_sar_mn) AS ecl
        FROM {relation} WHERE reporting_month = '{comparison}'
        GROUP BY 1
    """)}
    if not rows:
        return []

    total = sum(float(r["ecl"] or 0.0) for r in rows)
    total_ead = sum(float(r["ead"] or 0.0) for r in rows)
    largest = rows[0]
    moved = max(rows, key=lambda r: float(r["ecl"] or 0.0)
                - prior.get(r["segment"], 0.0))
    stage2 = _query(session, f"""
        SELECT SUM(CASE WHEN stage >= 2 THEN ead_sar_mn ELSE 0 END) AS s2,
               SUM(ead_sar_mn) AS ead
        FROM {relation} WHERE reporting_month = '{month}'
    """)[0]

    def card(key: str, headline: str, one_line: str, shown: str) -> dict:
        return {"item_id": _item_id(scope.domain_id, f"ecl-{key}", "", month),
                "domain_id": scope.domain_id,
                "release_id": scope.release_id,
                "release_fingerprint": scope.release_fingerprint,
                "section": "ecl_highlight", "headline": headline,
                "one_line": one_line, "display": shown,
                "reporting_quarter": month, "reporting_month": month,
                "comparison_quarter": comparison}

    increase = float(moved["ecl"] or 0.0) - prior.get(moved["segment"], 0.0)
    return [
        card("total", f"{scope.short_label} recognised ECL is "
                      f"{disp.format_value(_dec(total), money)}",
             f"Across the book in {month}, on exposure of "
             f"{disp.format_value(_dec(total_ead), money)}.",
             disp.format_value(_dec(total), money)),
        card("largest", f"{largest['segment']} carries the most ECL",
             f"{disp.format_value(_dec(float(largest['ecl'])), money)} of "
             f"the {disp.format_value(_dec(total), money)} recognised.",
             disp.format_value(_dec(float(largest["ecl"])), money)),
        card("increase", f"{moved['segment']} added the most ECL",
             f"Up {disp.format_value(_dec(increase), money)} against "
             f"{comparison}.",
             disp.format_value(_dec(increase), money)),
        # Named for its book. Both dashboards carried a card headlined
        # "Stage 2 and 3 exposure" and a reader with two tabs open could not
        # tell which portfolio they were looking at.
        card("stage2", f"{scope.short_label} Stage 2 and 3 exposure",
             f"{disp.format_value(_dec(float(stage2['s2'])), money)} of "
             f"{disp.format_value(_dec(float(stage2['ead'])), money)} sits "
             f"in Stage 2 or 3.",
             disp.format_value(
                 _dec(float(stage2["s2"]) / max(float(stage2["ead"]), 1e-9)
                      * 100), "percent")),
    ]


def compute(*, session, scope: dom.DomainScope) -> dict[str, Any]:
    """The whole feed for one book. No model call, and no cross-domain read."""
    if session.domain_id != scope.domain_id:
        raise AttentionUnavailable(
            f"A {dom.LABELS[scope.domain_id]} feed was asked for from a "
            f"{dom.LABELS[session.domain_id]} session. Nothing was computed.")
    month, comparison = scope.latest_period, scope.previous_period
    if not month or not comparison:
        raise AttentionUnavailable(
            f"Release {scope.release_id!r} does not have two months to "
            f"compare.")

    candidates: list[Candidate] = []
    for family in FAMILIES[scope.domain_id]:
        candidates.extend(_candidates(session, family, month=month,
                                      comparison=comparison))
    # One card per segment: the same sector arriving from three families is
    # one finding said three ways, and a page of it is a page of one story.
    best: dict[str, Candidate] = {}
    for candidate in candidates:
        key = f"{candidate.family.dimension}|{candidate.segment}"
        if key not in best or candidate.score > best[key].score:
            best[key] = candidate
    ordered = sorted(best.values(),
                     key=lambda c: (-c.score, c.family.key, c.segment))

    # Then spread across DIMENSIONS before filling up from any one of them.
    #
    # When a whole book moves, every slice of one lens moves with it, and the
    # page filled up with four customer segments that had all risen by
    # roughly the same amount -- true, and four ways of reading one fact.
    # A flat cap fixed that and broke the other case: the corporate book has
    # two lenses worth showing, so capping at two per dimension left it with
    # two cards on a book that had plainly changed.
    #
    # So: take the best from each dimension in turn, and once every dimension
    # has had its offer, fill the rest by score. Diversity where the book
    # offers it, depth where it does not.
    ranked = _spread(ordered, limit=TOP_N)

    return {
        "domain_id": scope.domain_id,
        "domain_label": scope.label,
        "release_id": scope.release_id,
        "release_fingerprint": scope.release_fingerprint,
        "reporting_quarter": month, "reporting_month": month,
        "comparison_quarter": comparison, "comparison_month": comparison,
        "reporting_currency": scope.currency,
        "amount_scale": scope.amount_scale,
        "attention_label": SECTION_LABELS[scope.domain_id],
        "highlights_label": HIGHLIGHT_LABELS[scope.domain_id],
        "segments_requiring_attention": [
            _item(c, scope=scope, month=month, comparison=comparison)
            for c in ranked[:TOP_N]],
        "ecl_highlights": _highlights(session, scope=scope, month=month,
                                      comparison=comparison),
        "model_calls": 0,
        "method_summary": {
            "candidates_considered": len(candidates),
            "families": [f.key for f in FAMILIES[scope.domain_id]],
            "minimum_share": MIN_SHARE,
            "minimum_movement": MIN_MOVEMENT,
            "max_per_dimension": MAX_PER_DIMENSION,
            "ranking": ("normalised movement x share of book x family "
                        "weight; one card per segment, at most "
                        f"{MAX_PER_DIMENSION} per dimension"),
        },
    }


_CACHE: dict[tuple, dict[str, Any]] = {}


def cached(*, session, scope: dom.DomainScope, tenant_id: str,
           refresh: bool = False) -> dict[str, Any]:
    """Keyed by tenant, domain, release AND fingerprint. §55."""
    key = scope.cache_key("attention", tenant_id)
    if not refresh and key in _CACHE:
        return {**_CACHE[key], "cached": True}
    feed = compute(session=session, scope=scope)
    _CACHE[key] = feed
    return {**feed, "cached": False}


def clear_cache() -> None:
    _CACHE.clear()


def find_item(feed: dict[str, Any], item_id: str) -> dict[str, Any] | None:
    for item in feed.get("segments_requiring_attention", []):
        if item.get("item_id") == item_id:
            return item
    return None


__all__ = ["AttentionUnavailable", "Candidate", "FAMILIES",
           "HIGHLIGHT_LABELS", "MIN_MOVEMENT", "MIN_SHARE", "SECTION_LABELS",
           "MAX_PER_DIMENSION", "TOP_N", "cached", "clear_cache", "compute", "find_item"]
