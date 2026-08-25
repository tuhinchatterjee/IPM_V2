"""
The governed joins between datasets — and the governance around them.

Why this is now load-bearing
----------------------------
Until this phase a relationship was documentation: a note that two datasets can
be joined, checked by a broken-key rule and otherwise inert. The dynamic planner
now COMPOSES joins from these rows, which turns each one into something
executable. A wrong cardinality here silently multiplies a book; a wrong
temporal rule reads a rating from the future; a relationship somebody sketched
and never checked becomes a number in a credit committee pack.

So a relationship carries governance on the row rather than in a policy
document:

    lifecycle       DRAFT → VALIDATED → ACTIVE → ARCHIVED. Only ACTIVE runs.
    version         bumped on any change to what the join DOES, and stamped
                    onto every Trace that used it, so a governance edit cannot
                    rewrite what a past analysis did.
    confidence      how sure the bank is that this join means what it says.
    join_policy     inner / left / asof — how unmatched rows are treated,
                    recorded once rather than decided at each call site.
    temporal_rule   same_period, or latest_on_or_before for an as-of join
                    across a frequency change. This is what stops an annual
                    rating being read from a year that had not happened yet.
    match rate,     measured against the real data, not asserted. A
    orphans,        relationship cannot reach ACTIVE without them.
    duplicates

There is exactly one relationship registry. The planner reads this and nothing
else, because two registries eventually disagree and the analysis silently
follows the wrong one.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models.platform import DatasetRelationship, DatasetRelationshipVersion
from backend.services import data_builder as db

logger = logging.getLogger(__name__)

FACILITY = "portfolio_facility"

# ---- lifecycle -------------------------------------------------------------

DRAFT = "draft"
VALIDATED = "validated"
ACTIVE = "active"
ARCHIVED = "archived"

LIFECYCLE = [DRAFT, VALIDATED, ACTIVE, ARCHIVED]

LIFECYCLE_LABEL = {
    DRAFT: "Draft · not usable",
    VALIDATED: "Validated · not yet approved",
    ACTIVE: "Active · the runtime may use it",
    ARCHIVED: "Archived · retained, never used",
}

#: The only state a plan may join on. Everything else is visible and inert.
RUNNABLE = frozenset({ACTIVE})

# ---- thresholds ------------------------------------------------------------
#
# Named rather than inlined because a data steward will want to argue with them,
# and an argument about a number in a config is a different conversation from an
# argument about a number buried in a comparison.

#: Below this share of left-hand rows finding a match, promotion is refused: a
#: join that loses a third of the book is not a join, it is a filter nobody
#: asked for.
MIN_MATCH_RATE = 0.80
#: A declared many_to_one or one_to_one whose right side has duplicate keys is
#: mis-declared, and the join will multiply rows. Tiny duplication is tolerated
#: because real books have a handful of bad rows; this much is a wrong model.
MAX_DUPLICATE_RATE = 0.02
#: A relationship the bank is not this sure of may be recorded, inspected and
#: proposed — never executed.
MIN_CONFIDENCE = 0.75

# ---- cardinality -----------------------------------------------------------

ONE_TO_ONE = "one_to_one"
MANY_TO_ONE = "many_to_one"
ONE_TO_MANY = "one_to_many"
MANY_TO_MANY = "many_to_many"

#: Cardinalities where the RIGHT side is unique on the join key, so the join
#: cannot multiply the left. Everything else needs aggregation or explicit
#: handling before it may be joined into an analysis.
SAFE_CARDINALITIES = frozenset({ONE_TO_ONE, MANY_TO_ONE})

# ---- temporal rules --------------------------------------------------------

SAME_PERIOD = "same_period"
LATEST_ON_OR_BEFORE = "latest_on_or_before"
NO_PERIOD = "none"

TEMPORAL_LABEL = {
    SAME_PERIOD: "Same reporting period on both sides.",
    LATEST_ON_OR_BEFORE: (
        "As-of: the latest observation dated on or before the analysis period. "
        "Never a later one, whatever exists in the data."),
    NO_PERIOD: "One side carries no period; the join is on identity alone.",
}


@dataclass(frozen=True)
class ShippedRelationship:
    """One join the demonstration book ships with."""

    from_dataset: str
    from_field: str
    to_dataset: str
    to_field: str
    cardinality: str
    kind: str
    semantic: str
    description: str = ""
    join_policy: str = "inner"
    temporal_rule: str = SAME_PERIOD
    confidence: float = 1.0
    is_preferred: bool = True


def _r(from_dataset: str, from_field: str, to_dataset: str, to_field: str,
       cardinality: str, kind: str, semantic: str, description: str = "",
       **kwargs: Any) -> ShippedRelationship:
    return ShippedRelationship(
        from_dataset=from_dataset, from_field=from_field, to_dataset=to_dataset,
        to_field=to_field, cardinality=cardinality, kind=kind,
        semantic=semantic, description=description or semantic, **kwargs)


#: The shipped joins. `many_to_one` reads left to right: many rows on the left
#: for one on the right, which is the only direction that cannot multiply the
#: left-hand book.
GOVERNED_RELATIONSHIPS: list[ShippedRelationship] = [
    # ---- everything facility-grained hangs off the facility position -------
    _r("ifrs9_staging", "account_id", FACILITY, "account_id", ONE_TO_ONE, "key",
       "The impairment assessment of this facility.",
       "One staging assessment per facility per period. The two tables describe "
       "the same facility at the same date and cannot disagree about its stage."),
    _r("facility_delinquency", "account_id", FACILITY, "account_id",
       ONE_TO_ONE, "key", "The arrears position of this facility.",
       "One arrears position per facility per period."),
    _r("payment_history", "account_id", FACILITY, "account_id", ONE_TO_ONE, "key",
       "What was due on this facility and what arrived."),
    _r("facility_limits", "account_id", FACILITY, "account_id", ONE_TO_ONE, "key",
       "The sanctioned limit behind this facility, and any excess over it."),
    _r("facility_profitability", "account_id", FACILITY, "account_id",
       ONE_TO_ONE, "key", "Revenue, cost, expected loss and capital for this "
       "facility."),
    _r("collateral_register", "account_id", FACILITY, "account_id",
       MANY_TO_ONE, "key", "The collateral securing this facility.",
       "A facility may hold several collateral items; each item secures one "
       "facility. Joining without this cardinality multiplies the book by the "
       "number of charges."),
    _r("covenant_tests", "account_id", FACILITY, "account_id", MANY_TO_ONE, "key",
       "The covenants tested against this facility.",
       "Several covenants are tested against one facility each period, so this "
       "side must be aggregated before it is joined into a facility-grained "
       "analysis."),
    _r("recoveries", "account_id", FACILITY, "account_id", ONE_TO_ONE, "key",
       "What was recovered on this facility after it defaulted.",
       "Only defaulted facilities appear. The join is inner by nature: a "
       "facility with no recovery record has not defaulted."),

    # ---- facility to customer ----------------------------------------------
    _r(FACILITY, "customer_id", "borrower_financials", "customer_id",
       MANY_TO_ONE, "key", "The borrower who holds this facility.",
       "A customer holds several facilities and files one set of financials.",
       temporal_rule=NO_PERIOD),
    _r("customer_ratings", "customer_id", "borrower_financials", "customer_id",
       MANY_TO_ONE, "key", "The borrower this rating cycle assessed.",
       temporal_rule=NO_PERIOD),
    _r("watchlist_register", "customer_id", "borrower_financials", "customer_id",
       MANY_TO_ONE, "key", "The borrower under heightened monitoring.",
       temporal_rule=NO_PERIOD),
    _r("climate_risk", "customer_id", "borrower_financials", "customer_id",
       ONE_TO_ONE, "key", "The borrower this climate assessment describes.",
       temporal_rule=NO_PERIOD),
    _r("group_structure", "customer_id", "borrower_financials", "customer_id",
       ONE_TO_ONE, "key", "The borrower's place in its obligor group.",
       temporal_rule=NO_PERIOD),
    _r("rating_transitions", "customer_id", "borrower_financials", "customer_id",
       MANY_TO_ONE, "key", "The borrower whose rating moved.",
       temporal_rule=NO_PERIOD),
    _r("credit_memo_signals", "customer_id", "borrower_financials", "customer_id",
       MANY_TO_ONE, "key", "The borrower whose credit file this note is in.",
       temporal_rule=NO_PERIOD),

    # ---- the as-of edges: annual against quarterly --------------------------
    #
    # This is the join the whole phase turns on. A rating cycle is annual and a
    # facility position is quarterly, so "the rating of this customer at Q2
    # 2026" means the latest cycle dated on or before that quarter — never a
    # later one, whatever the data contains.
    _r("customer_ratings", "customer_id", FACILITY, "customer_id",
       MANY_TO_MANY, "key",
       "The rating this customer carried at the reporting date.",
       "Annual rating cycles against a quarterly book. Joined as-of: the latest "
       "cycle dated on or before the analysis period, and never a later one. "
       "Declared many-to-many because at row level a customer has several "
       "facilities and several cycles — the as-of rule and a customer-level "
       "aggregation are what make it safe.",
       join_policy="asof", temporal_rule=LATEST_ON_OR_BEFORE),
    _r("borrower_financials", "customer_id", FACILITY, "customer_id",
       ONE_TO_MANY, "key",
       "The financials behind the borrower holding this facility.",
       "One financial record per customer against many facilities. Read at "
       "customer level; joining it onto facilities repeats it by design.",
       temporal_rule=NO_PERIOD),

    # ---- group ---------------------------------------------------------------
    _r("group_structure", "parent_customer_id", "group_structure", "customer_id",
       MANY_TO_ONE, "key", "The parent this subsidiary belongs to.",
       "A subsidiary points at its parent, which is itself a member. Large "
       "exposure limits apply at group level, so this is the edge the limit is "
       "actually tested on.", temporal_rule=NO_PERIOD),

    # ---- reporting-period links ---------------------------------------------
    _r(FACILITY, "period", "macro_saudi", "period", MANY_TO_ONE,
       "reporting_period", "The economy this quarter's book was lent into.",
       "Every facility in a quarter shares that quarter's macroeconomic "
       "reading. This is what makes 'which sectors moved with the cycle' "
       "answerable."),
    _r("risk_appetite_limits", "period", "macro_saudi", "period", MANY_TO_ONE,
       "reporting_period", "The economy the appetite position was measured in."),
    _r("pd_model_performance", "period", "macro_saudi", "period", MANY_TO_ONE,
       "reporting_period", "The cycle the predicted-against-observed gap "
       "happened in."),
    _r("scenario_definitions", "period", "macro_saudi", "period", MANY_TO_ONE,
       "reporting_period", "The actual series a scenario is shocked off."),
    _r("ifrs9_staging", "period", "macro_saudi", "period", MANY_TO_ONE,
       "reporting_period", "The economy behind this quarter's impairment."),
]


# ------------------------------------------------------------------- seeding


def _definition(record: DatasetRelationship) -> dict[str, Any]:
    """What the relationship IS, for the version history.

    Deliberately only the parts that change what the join DOES. A reworded
    description is not a new version, and treating it as one would fill the
    history with noise until nobody reads it.
    """
    return {
        "from_dataset": record.from_dataset, "from_field": record.from_field,
        "to_dataset": record.to_dataset, "to_field": record.to_field,
        "cardinality": record.cardinality, "kind": record.kind,
        "join_policy": record.join_policy, "temporal_rule": record.temporal_rule,
        "lifecycle": record.lifecycle,
    }


def bump_version(session: Session, record: DatasetRelationship, *,
                 change_note: str, user_id: int | None = None) -> int:
    """Record what the relationship was, then move it to a new version.

    Called before any change to what the join does. Without this, "why did this
    number change" has no answer that survives a governance edit.
    """
    session.add(DatasetRelationshipVersion(
        relationship_id=record.id, version=record.version,
        definition=_definition(record), change_note=change_note,
        changed_by=user_id,
    ))
    record.version += 1
    session.flush()
    return record.version


def seed(session: Session, *, only_known: bool = True,
         activate: bool = True) -> dict[str, Any]:
    """Declare the demonstration book's joins. Idempotent and additive.

    `only_known` skips a relationship naming a dataset this installation does
    not have, rather than failing: a bank running with its own datasets should
    still get the joins that apply to what it does have.

    `activate` marks the shipped joins ACTIVE. They are shipped BY the product
    rather than sketched by a steward, and they are exercised by the test suite
    on every build, which is the evidence a bank's own relationship has to earn
    through validation instead.
    """
    from backend.data_access import get_catalog

    known = set(get_catalog().names())
    created, updated, skipped = [], [], []

    for shipped in GOVERNED_RELATIONSHIPS:
        if only_known and not {shipped.from_dataset, shipped.to_dataset} <= known:
            skipped.append(f"{shipped.from_dataset} -> {shipped.to_dataset}")
            continue
        try:
            record = db.add_relationship(
                session, from_dataset=shipped.from_dataset,
                from_field=shipped.from_field, to_dataset=shipped.to_dataset,
                to_field=shipped.to_field, cardinality=shipped.cardinality,
                kind=shipped.kind, description=shipped.description,
            )
        except Exception as e:
            logger.warning("Could not declare %s -> %s: %s",
                           shipped.from_dataset, shipped.to_dataset, e)
            skipped.append(f"{shipped.from_dataset} -> {shipped.to_dataset}")
            continue

        changed = (record.cardinality != shipped.cardinality
                   or record.join_policy != shipped.join_policy
                   or record.temporal_rule != shipped.temporal_rule)
        if changed and record.id and record.version:
            bump_version(session, record,
                         change_note="Shipped definition updated by the product.")

        record.cardinality = shipped.cardinality
        record.semantic = shipped.semantic
        record.description = shipped.description
        record.join_policy = shipped.join_policy
        record.temporal_rule = shipped.temporal_rule
        record.confidence = shipped.confidence
        record.is_preferred = shipped.is_preferred
        if activate and record.lifecycle != ARCHIVED:
            record.lifecycle = ACTIVE

        (updated if changed else created).append(record.name)

    session.flush()
    return {"declared": created + updated, "changed": updated,
            "skipped": skipped, "total": len(GOVERNED_RELATIONSHIPS)}


# ---------------------------------------------------------------- validation


def _keys(series):
    """The rows that actually carry a key.

    A blank string is a missing parent, not a parent that has gone missing:
    counting it as an orphan reports a coverage failure the data does not have.
    """
    values = series.dropna()
    if values.empty:
        return values
    return values[values.astype(str).str.strip().ne("")]


def validate_relationship(session: Session, record: DatasetRelationship, *,
                          period: str | None = None) -> dict[str, Any]:
    """Measure the join against the real data, and say what it found.

    Measured rather than asserted. A steward declaring "many to one" is stating
    an intention; whether the right-hand side actually has unique keys is a
    property of the data, and the difference between the two is a silently
    multiplied book.

    Reads one period where both sides carry one, because a match rate is a
    property of a period rather than of all history, and reading fifteen
    quarters to answer it would make validation something nobody runs.
    """
    from backend.data_access import get_catalog, get_data_source
    from backend.data_access.context import AnalysisContext

    source = get_data_source()
    catalog = get_catalog()
    findings: list[str] = []

    try:
        left_def = catalog.dataset(record.from_dataset)
        right_def = catalog.dataset(record.to_dataset)
    except Exception as e:
        return {"ok": False, "findings": [f"Dataset unavailable: {e}"]}

    for definition, column in ((left_def, record.from_field),
                               (right_def, record.to_field)):
        if column not in definition.fields:
            findings.append(
                f"'{column}' is not a field of {definition.name}. The join "
                "cannot be tested, let alone run.")
    if findings:
        return {"ok": False, "findings": findings}

    def read(definition, column):
        if not definition.period_field:
            return source.fetch(definition.name,
                                context=AnalysisContext(period=None),
                                fields=[column]), None
        published = source.periods(definition.name) or []
        chosen = period if period in published else None
        if chosen is None:
            # A period-partitioned dataset read with no period named is read
            # across its whole history, which turns one row per customer into
            # fifteen and reports a duplicate rate that is an artefact of the
            # read rather than a property of the key. Fall back to the latest
            # published period instead.
            chosen = published[-1] if published else None
        return source.fetch(definition.name, context=AnalysisContext(period=chosen),
                            fields=[column], period=chosen), chosen

    try:
        left, left_period = read(left_def, record.from_field)
        right, right_period = read(right_def, record.to_field)
    except Exception as e:
        return {"ok": False, "findings": [f"Could not read the data: {e}"]}

    left_values = _keys(left[record.from_field])
    right_values = _keys(right[record.to_field])
    right_set = set(right_values.astype(str))

    left_count = int(len(left_values))
    matched = int(left_values.astype(str).isin(right_set).sum()) if left_count else 0
    match_rate = matched / left_count if left_count else 0.0

    right_count = int(len(right_values))
    distinct_right = int(right_values.nunique())
    duplicate_rate = (
        1.0 - distinct_right / right_count if right_count else 0.0)

    orphans = left_count - matched
    orphan_rate = orphans / left_count if left_count else 0.0

    if match_rate < MIN_MATCH_RATE:
        findings.append(
            f"Only {match_rate * 100:.1f}% of {record.from_dataset} rows find a "
            f"match in {record.to_dataset}. A join that loses this much of the "
            "book is a filter nobody asked for.")
    if (record.cardinality in SAFE_CARDINALITIES
            and duplicate_rate > MAX_DUPLICATE_RATE):
        findings.append(
            f"{record.to_dataset}.{record.to_field} is not unique "
            f"({duplicate_rate * 100:.1f}% duplicated), so this join would "
            f"multiply {record.from_dataset} rows — but it is declared "
            f"{record.cardinality}, which says it cannot.")
    if record.confidence < MIN_CONFIDENCE:
        findings.append(
            f"Confidence is {record.confidence:.2f}, below the "
            f"{MIN_CONFIDENCE:.2f} a relationship needs before it may run.")

    detail = {
        "period_left": left_period, "period_right": right_period,
        "left_rows": left_count, "right_rows": right_count,
        "matched_rows": matched, "orphan_rows": orphans,
        "distinct_right_keys": distinct_right,
    }
    record.match_rate = round(match_rate, 6)
    record.orphan_rate = round(orphan_rate, 6)
    record.duplicate_rate = round(duplicate_rate, 6)
    record.validated_at = datetime.now(UTC)
    record.validation = {**detail, "findings": findings}
    if not findings and record.lifecycle == DRAFT:
        record.lifecycle = VALIDATED
    session.flush()

    return {"ok": not findings, "findings": findings, **detail,
            "match_rate": record.match_rate, "orphan_rate": record.orphan_rate,
            "duplicate_rate": record.duplicate_rate,
            "lifecycle": record.lifecycle}


def promote(session: Session, relationship_id: int, *, to: str,
            user_id: int | None = None, note: str = "") -> DatasetRelationship:
    """Move a relationship along its lifecycle, or refuse and say why.

    ACTIVE is the only state the runtime will join on, so reaching it needs
    evidence: the relationship must have been validated against real data and
    have passed. Archiving is always allowed — withdrawing a join is never the
    dangerous direction.
    """
    record = session.get(DatasetRelationship, relationship_id)
    if record is None:
        raise db.DataBuilderError(f"No relationship {relationship_id}.")
    if to not in LIFECYCLE:
        raise db.DataBuilderError(f"'{to}' is not a relationship state.")

    if to == ACTIVE:
        if record.validated_at is None:
            raise db.DataBuilderError(
                "This relationship has not been validated against the data. "
                "Run validation first — a join the runtime may compose has to "
                "be measured, not asserted.")
        problems = list((record.validation or {}).get("findings") or [])
        if problems:
            raise db.DataBuilderError(
                "Validation found: " + "; ".join(problems[:3]))

    bump_version(session, record,
                 change_note=note or f"Lifecycle {record.lifecycle} → {to}",
                 user_id=user_id)
    record.lifecycle = to
    session.flush()
    return record


# ------------------------------------------------------------------- reading


def to_dict(record: DatasetRelationship) -> dict[str, Any]:
    return {
        "id": record.id,
        "name": record.name,
        "from_dataset": record.from_dataset,
        "from_field": record.from_field,
        "to_dataset": record.to_dataset,
        "to_field": record.to_field,
        "cardinality": record.cardinality,
        "kind": record.kind,
        "description": record.description,
        "semantic": record.semantic,
        "lifecycle": record.lifecycle,
        "lifecycle_label": LIFECYCLE_LABEL.get(record.lifecycle, record.lifecycle),
        "version": record.version,
        "is_preferred": record.is_preferred,
        "confidence": round(float(record.confidence or 0.0), 3),
        "join_policy": record.join_policy,
        "temporal_rule": record.temporal_rule,
        "temporal_label": TEMPORAL_LABEL.get(record.temporal_rule, ""),
        "match_rate": record.match_rate,
        "orphan_rate": record.orphan_rate,
        "duplicate_rate": record.duplicate_rate,
        "validated_at": record.validated_at.isoformat() if record.validated_at else "",
        "validation": record.validation or {},
        "is_runnable": record.lifecycle in RUNNABLE,
    }


def active_relationships(session: Session) -> list[dict[str, Any]]:
    """Every relationship the runtime is allowed to join on.

    Archived datasets are excluded here rather than at the planner, so there is
    one place where "may this be used" is decided.
    """
    from backend.services.domain_status import archived_datasets

    try:
        excluded = archived_datasets()
    except Exception:
        excluded = frozenset()

    rows = session.scalars(
        select(DatasetRelationship).where(
            DatasetRelationship.lifecycle == ACTIVE)).all()
    return [
        to_dict(r) for r in rows
        if r.confidence >= MIN_CONFIDENCE
        and r.from_dataset not in excluded and r.to_dataset not in excluded
    ]


def versions(session: Session, relationship_id: int) -> list[dict[str, Any]]:
    rows = session.scalars(
        select(DatasetRelationshipVersion)
        .where(DatasetRelationshipVersion.relationship_id == relationship_id)
        .order_by(DatasetRelationshipVersion.version.desc())).all()
    return [{"version": r.version, "definition": r.definition,
             "change_note": r.change_note, "changed_by": r.changed_by,
             "created_at": r.created_at.isoformat() if r.created_at else ""}
            for r in rows]


@dataclass
class GraphView:
    nodes: list[dict[str, Any]] = field(default_factory=list)
    edges: list[dict[str, Any]] = field(default_factory=list)


def graph(session: Session) -> dict[str, Any]:
    """Every governed dataset and every declared join, for the map.

    Nodes carry the dataset's grain and its domain, because "one row per what"
    is the question a relationship map is usually being consulted to answer, and
    an edge between two boxes whose grain nobody states is a picture rather than
    a model.
    """
    from backend.data_access import get_catalog

    catalog = get_catalog()
    edges = [to_dict(r) for r in db.list_relationships(session)]
    involved = {e["from_dataset"] for e in edges} | {e["to_dataset"] for e in edges}

    nodes = []
    for name in sorted(involved | set(catalog.names())):
        try:
            definition = catalog.dataset(name)
        except Exception:
            nodes.append({"name": name, "domain": "", "grain": "",
                          "field_count": 0, "is_synthetic": False,
                          "in_catalogue": False, "degree": 0})
            continue
        degree = sum(1 for e in edges
                     if name in (e["from_dataset"], e["to_dataset"]))
        nodes.append({
            "name": name,
            "domain": definition.domain,
            "business_name": definition.business_name,
            "grain": definition.grain,
            "period_field": definition.period_field,
            "field_count": len(definition.fields),
            "is_synthetic": definition.is_synthetic,
            "authoritative_for": list(definition.authoritative_for),
            "in_catalogue": True,
            "degree": degree,
        })

    active = [e for e in edges if e["is_runnable"]]
    return {
        "nodes": nodes, "edges": edges,
        "connected": len(involved),
        "unconnected": sorted(set(catalog.names()) - involved),
        "active_count": len(active),
        "lifecycles": [{"id": s, "label": LIFECYCLE_LABEL[s]} for s in LIFECYCLE],
        "thresholds": {"min_match_rate": MIN_MATCH_RATE,
                       "max_duplicate_rate": MAX_DUPLICATE_RATE,
                       "min_confidence": MIN_CONFIDENCE},
    }


__all__ = [
    "ACTIVE",
    "ARCHIVED",
    "DRAFT",
    "GOVERNED_RELATIONSHIPS",
    "LIFECYCLE",
    "LIFECYCLE_LABEL",
    "MANY_TO_MANY",
    "MANY_TO_ONE",
    "MIN_CONFIDENCE",
    "MIN_MATCH_RATE",
    "ONE_TO_MANY",
    "ONE_TO_ONE",
    "RUNNABLE",
    "SAFE_CARDINALITIES",
    "VALIDATED",
    "ShippedRelationship",
    "active_relationships",
    "bump_version",
    "graph",
    "promote",
    "seed",
    "to_dict",
    "validate_relationship",
    "versions",
]
