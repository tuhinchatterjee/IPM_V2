"""
The governed joins between the demonstration domains.

Why these are shipped rather than drawn
---------------------------------------
A relationship is not decoration. It is what lets the runtime carry a customer's
sector onto its facilities, what makes "collateral coverage by sector" a
question rather than a project, and what a broken-key check tests against. A
twenty-domain book whose relationships a steward has to draw by hand is a
twenty-domain book nobody joins.

So the demonstration book ships with its joins declared, and they are declared
as facts about the data rather than as convenience: `covenant_tests.account_id`
is many-to-one against `portfolio_facility.account_id` because a facility has
several covenants and a covenant belongs to one facility. Getting a cardinality
wrong is how a join silently multiplies a book.

Seeding is idempotent and additive. It never removes a relationship a steward
declared, because a bank's own join is not this module's to withdraw.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from backend.services import data_builder as db

logger = logging.getLogger(__name__)

FACILITY = "portfolio_facility"

#: (from_dataset, from_field, to_dataset, to_field, cardinality, kind, why)
#:
#: `many_to_one` reads left to right: many rows on the left for one on the
#: right. A reporting-period link is a different kind from an identifier link
#: because it is checked differently — the periods have to align, rather than
#: the values having to exist.
GOVERNED_RELATIONSHIPS: list[tuple[str, str, str, str, str, str, str]] = [
    # ---- everything facility-grained hangs off the facility position -------
    ("ifrs9_staging", "account_id", FACILITY, "account_id",
     "one_to_one", "key",
     "One staging assessment per facility per period. The two tables describe "
     "the same facility at the same date and cannot disagree about its stage."),
    ("facility_delinquency", "account_id", FACILITY, "account_id",
     "one_to_one", "key",
     "One arrears position per facility per period."),
    ("payment_history", "account_id", FACILITY, "account_id",
     "one_to_one", "key",
     "What was due and what arrived, for the same facility and period."),
    ("facility_limits", "account_id", FACILITY, "account_id",
     "one_to_one", "key",
     "The sanctioned limit behind the facility, and any excess over it."),
    ("facility_profitability", "account_id", FACILITY, "account_id",
     "one_to_one", "key",
     "Revenue, cost, expected loss and capital for the same facility."),
    ("collateral_register", "account_id", FACILITY, "account_id",
     "many_to_one", "key",
     "A facility may hold several collateral items; each item secures one "
     "facility. Joining without this cardinality multiplies the book by the "
     "number of charges."),
    ("covenant_tests", "account_id", FACILITY, "account_id",
     "many_to_one", "key",
     "Several covenants are tested against one facility each period."),
    ("recoveries", "account_id", FACILITY, "account_id",
     "one_to_one", "key",
     "Only defaulted facilities appear. The join is inner by nature: a "
     "facility with no recovery record has not defaulted."),

    # ---- customer-grained ---------------------------------------------------
    ("portfolio_facility", "customer_id", "borrower_financials", "customer_id",
     "many_to_one", "key",
     "A customer holds several facilities and files one set of financials."),
    ("customer_ratings", "customer_id", "borrower_financials", "customer_id",
     "many_to_one", "key",
     "One rating cycle a year per customer, against one financial record."),
    ("watchlist_register", "customer_id", "borrower_financials", "customer_id",
     "many_to_one", "key",
     "A watchlisted customer appears once per period it is on the list."),
    ("climate_risk", "customer_id", "borrower_financials", "customer_id",
     "one_to_one", "key",
     "One climate assessment per customer."),
    ("group_structure", "customer_id", "borrower_financials", "customer_id",
     "one_to_one", "key",
     "A customer belongs to one group."),
    ("rating_transitions", "customer_id", "borrower_financials", "customer_id",
     "many_to_one", "key",
     "One transition row per customer per pair of consecutive rating years."),
    ("credit_memo_signals", "customer_id", "borrower_financials", "customer_id",
     "many_to_one", "key",
     "A customer's credit file carries many notes."),

    # ---- group ---------------------------------------------------------------
    ("group_structure", "parent_customer_id", "group_structure", "customer_id",
     "many_to_one", "key",
     "A subsidiary points at its parent, which is itself a member. Large "
     "exposure limits apply at group level, so this is the edge the limit "
     "is actually tested on."),

    # ---- reporting-period links ---------------------------------------------
    ("portfolio_facility", "period", "macro_saudi", "period",
     "many_to_one", "reporting_period",
     "Every facility in a quarter shares that quarter's macroeconomic reading. "
     "This is what makes 'which sectors moved with the cycle' answerable."),
    ("risk_appetite_limits", "period", "macro_saudi", "period",
     "many_to_one", "reporting_period",
     "Appetite is measured at a reporting date."),
    ("pd_model_performance", "period", "macro_saudi", "period",
     "many_to_one", "reporting_period",
     "Predicted against observed, read against the cycle it happened in."),
    ("scenario_definitions", "period", "macro_saudi", "period",
     "many_to_one", "reporting_period",
     "A scenario is a shocked path off the actual series, quarter by quarter."),
]


def seed(session: Session, *, only_known: bool = True) -> dict[str, Any]:
    """Declare the demonstration book's joins. Idempotent and additive.

    `only_known` skips a relationship naming a dataset this installation does
    not have, rather than failing: a bank running with its own datasets should
    still get the joins that apply to what it does have.
    """
    from backend.data_access import get_catalog

    known = set(get_catalog().names())
    created, skipped = [], []

    for from_ds, from_f, to_ds, to_f, cardinality, kind, why in GOVERNED_RELATIONSHIPS:
        if only_known and not {from_ds, to_ds} <= known:
            skipped.append(f"{from_ds} -> {to_ds}")
            continue
        try:
            record = db.add_relationship(
                session, from_dataset=from_ds, from_field=from_f,
                to_dataset=to_ds, to_field=to_f, cardinality=cardinality,
                kind=kind, description=why,
            )
            created.append(record.name)
        except Exception as e:
            logger.warning("Could not declare %s -> %s: %s", from_ds, to_ds, e)
            skipped.append(f"{from_ds} -> {to_ds}")

    return {"declared": created, "skipped": skipped,
            "total": len(GOVERNED_RELATIONSHIPS)}


def graph(session: Session) -> dict[str, Any]:
    """Every declared join, as nodes and edges — the relationship map.

    Nodes carry the dataset's grain, because "one row per what" is the question
    a relationship map is usually being consulted to answer, and an edge between
    two boxes whose grain nobody states is a picture rather than a model.
    """
    from backend.data_access import get_catalog

    catalog = get_catalog()
    edges = []
    involved: set[str] = set()

    for record in db.list_relationships(session):
        involved.update({record.from_dataset, record.to_dataset})
        edges.append({
            "id": record.id,
            "name": record.name,
            "from_dataset": record.from_dataset,
            "from_field": record.from_field,
            "to_dataset": record.to_dataset,
            "to_field": record.to_field,
            "cardinality": record.cardinality,
            "kind": record.kind,
            "description": record.description,
        })

    nodes = []
    for name in sorted(involved | set(catalog.names())):
        try:
            definition = catalog.dataset(name)
        except Exception:
            nodes.append({"name": name, "domain": "", "grain": "",
                          "field_count": 0, "is_synthetic": False,
                          "in_catalogue": False})
            continue
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
        })

    return {"nodes": nodes, "edges": edges,
            "connected": len(involved), "unconnected":
            sorted(set(catalog.names()) - involved)}


__all__ = ["GOVERNED_RELATIONSHIPS", "graph", "seed"]
