"""Reading the Borrower 360 and the graph, for a screen. Phase 3.

Everything here reads the Parquet lake and computes nothing that the
derivation has not already computed. A screen that recomputes DebtRank on
every page load is a screen that disagrees with the export beside it, and
the disagreement will be discovered by a client rather than by a test.

The one thing this module does compute is the EGO GRAPH: the neighbourhood
around one borrower, expanded server-side to a bounded depth. That is
deliberate and is the whole point of Phase 3.9 - a screen that fetches the
entire network and filters it in the browser ships 43,000 edges to show
eleven, and does it again on every click.
"""

from __future__ import annotations

import glob
import logging
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

import pandas as pd

from backend.corporate import ORIGIN, graphdata
from backend.corporate import graphsummary as gs
from backend.corporate import search as search_mod

logger = logging.getLogger(__name__)

SERVICE_VERSION = "1.0.0"

SNAPSHOT = "corporate_borrower_360"
GROUPS = gs.GROUPS_DATASET
DQ = gs.DQ_DATASET


class BorrowerNotFound(LookupError):
    """No such borrower in this period."""


class DataNotBuilt(RuntimeError):
    """The lake has not been built. Says so, rather than returning nothing."""


# ------------------------------------------------------------------ loading


@lru_cache(maxsize=32)
def _load(dataset: str) -> pd.DataFrame:
    from backend.config import settings

    files = sorted(glob.glob(
        str(settings.analytics_dir / dataset / "**" / "*.parquet"),
        recursive=True))
    if not files:
        raise DataNotBuilt(
            f"{dataset} has not been built. Run "
            "scripts/build_corporate_universe.py to generate the "
            "demonstration universe. Nothing here is client data.")
    return pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)


def load(dataset: str) -> pd.DataFrame:
    """One governed dataset from the lake, cached. Callers must not mutate."""
    return _load(dataset)


#: Re-exported so a caller does not have to know that search lives elsewhere.
SEARCHABLE: tuple[str, ...] = search_mod.SEARCHABLE
UnknownFacetError = search_mod.UnknownFacetError


def periods() -> list[str]:
    """Quarters present, oldest first."""
    frame = _load("corporate_customer_master")
    order = frame[["period", "period_end_date"]].drop_duplicates()
    return order.sort_values("period_end_date")["period"].tolist()


def latest_period() -> str:
    found = periods()
    if not found:
        raise DataNotBuilt("no periods in the corporate customer master")
    return found[-1]


def as_of_date(period: str) -> str:
    frame = _load("corporate_customer_master")
    block = frame[frame["period"] == period]
    if block.empty:
        raise BorrowerNotFound(
            f"'{period}' is not a period in this book. Available: "
            + ", ".join(periods()))
    return str(block["period_end_date"].iloc[0])


def reset_cache() -> None:
    """Drop the loaded frames. Used after a rebuild, and by tests."""
    _load.cache_clear()


# ------------------------------------------------------------------- tabs

#: The thirteen tabs, in the order they are shown, each naming the datasets
#: behind it. Declared here rather than in the frontend so that the API, the
#: export and the screen cannot drift apart: a tab the screen shows and the
#: export omits is a defect nobody notices until a client asks why.
TABS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("overview", "Overview",
     ("corporate_customer_master", "corporate_ratings", "corporate_ifrs9")),
    ("exposure", "Exposure & facilities",
     ("corporate_facilities", "corporate_limits")),
    ("ratings", "Rating & PD",
     ("corporate_ratings",)),
    ("ifrs9", "IFRS 9 & ECL",
     ("corporate_ifrs9",)),
    ("financials", "Financials",
     ("corporate_financials",)),
    ("covenants", "Covenants",
     ("corporate_covenants",)),
    ("collateral", "Collateral",
     ("corporate_collateral",)),
    ("delinquency", "Delinquency & arrears",
     ("corporate_delinquency",)),
    ("watchlist", "Watchlist & early warning",
     ("corporate_watchlist", "corporate_restructuring")),
    ("limits", "Limits & large exposures",
     ("corporate_limits", GROUPS)),
    ("group", "Group & connectedness",
     (GROUPS,)),
    ("network", "Relationship network",
     ("corporate_ownership_edges", "corporate_supply_chain",
      "corporate_exposure_network", "corporate_guarantees", GROUPS)),
    ("quality", "Data quality & lineage",
     (DQ, GROUPS, "corporate_entity_resolution")),
)

TAB_KEYS: tuple[str, ...] = tuple(key for key, _, _ in TABS)

#: Tabs that show the relationship graph rather than the credit book. The
#: permission split follows this list.
GRAPH_TABS: frozenset[str] = frozenset({"group", "network"})


# ------------------------------------------------- the six group concepts

#: Six group concepts, kept apart on purpose. Phase 3.11.
#:
#: They are not synonyms and they do not agree. A borrower can be in a
#: control group of three, an effective-ownership group of five, a connected
#: counterparty group of twenty-two and a network community of four hundred,
#: and every one of those numbers is correct for the question it answers.
#: Collapsing them into one "group" column - which is what almost every
#: system does - produces a number that is wrong for every question.
GROUP_CONCEPTS: tuple[dict[str, str], ...] = (
    {
        "key": "effective_ownership_group",
        "label": "Effective ownership group",
        "column": "effective_ownership_group_id",
        "question": "Whose economics move with this borrower's?",
        "basis": "Integrated ownership at or above 25%, solved as "
                 "A(I - A)^-1 per component.",
        "is_not": "NOT control. 51% of 51% is 26% of the economics and "
                  "100% of the control, and this column is the 26%.",
    },
    {
        "key": "control_group",
        "label": "Control group",
        "column": "control_group_id",
        "question": "Who can direct this borrower's decisions?",
        "basis": "Binary control closure over VOTING rights: majority, an "
                 "explicit assertion, or a dominant minority holder.",
        "is_not": "NOT proportional ownership, and NOT a regulatory "
                  "determination of connectedness.",
    },
    {
        "key": "connected_counterparty_group",
        "label": "Connected counterparty group",
        "column": "connected_group_id",
        "question": "Which borrowers should be assessed as one obligor?",
        "basis": "Control components, then validated economic "
                 "interdependence merged in. Never weak components over "
                 "raw shareholdings.",
        "is_not": "NOT a determination. These are CANDIDATES for assessment "
                  "under the institution's own approved criteria - graph "
                  "connectivity is not regulatory connectedness.",
    },
    {
        "key": "exposure_limit_group",
        "label": "Exposure limit group",
        "column": "connected_group_id",
        "question": "What is measured against the group limit?",
        "basis": "The connected counterparty group's total EAD over the "
                 "eligible capital reference.",
        "is_not": "NOT a breach finding. The threshold is an UNVERIFIED "
                  "REGULATORY PARAMETER carried from the framework "
                  "document, not confirmed as currently binding.",
    },
    {
        "key": "network_community",
        "label": "Network community",
        "column": "louvain_community",
        "question": "Which borrowers cluster together in the exposure "
                    "network?",
        "basis": "Modularity optimisation over the exposure graph.",
        "is_not": "NOT a group in any legal, economic or regulatory sense. "
                  "It is a description of the network's shape and carries "
                  "no claim about the borrowers in it.",
    },
    {
        "key": "similarity_cluster",
        "label": "Hidden relationship candidates",
        "column": "",
        "question": "Who shares enough evidence with this borrower to be "
                    "worth a second look?",
        "basis": "Jaccard similarity over shared directors, registered "
                 "addresses and funding channels.",
        "is_not": "NOT a relationship. It establishes no control, no "
                  "beneficial ownership and no group membership - it is a "
                  "suggestion for investigation and nothing more.",
    },
)

GROUP_CONCEPT_KEYS: tuple[str, ...] = tuple(
    concept["key"] for concept in GROUP_CONCEPTS)


# --------------------------------------------------------------- the ego graph

#: How far out the neighbourhood may be expanded. Beyond three hops a
#: "neighbourhood" in a graph whose largest component holds 95% of the book
#: is the whole book, and returning it is not a subgraph query - it is a
#: table scan wearing a graph's clothes.
MAX_DEPTH = 3
DEFAULT_DEPTH = 1

#: The cap on what one request returns. Reached rather than exceeded: the
#: response says it was truncated and by how much, because a silently
#: truncated graph is one a user reads as complete.
MAX_NODES = 400
MAX_EDGES = 1_200

EDGE_SOURCES: dict[str, str] = {
    "ownership": "corporate_ownership_edges",
    "supply": "corporate_supply_chain",
    "exposure": "corporate_exposure_network",
    "guarantee": "corporate_guarantees",
}

#: The eleven network views. Each is a named subset of edge families and a
#: statement of what it is FOR - a view whose purpose nobody can state is a
#: view nobody knows how to read.
NETWORK_VIEWS: tuple[dict[str, Any], ...] = (
    {"key": "ownership", "label": "Ownership structure",
     "families": ("ownership",), "edge_types": (graphdata.OWNS,),
     "purpose": "Who holds what, directly, as filed."},
    {"key": "control", "label": "Control structure",
     "families": ("ownership",),
     "edge_types": (graphdata.OWNS, graphdata.CONTROLS),
     "purpose": "Who can direct whom, over voting rights."},
    {"key": "ubo", "label": "Ultimate beneficial owners",
     "families": ("ownership",), "edge_types": (graphdata.OWNS,),
     "purpose": "The natural persons behind the borrower.",
     "requires_ubo_permission": True},
    {"key": "directors", "label": "Directors and boards",
     "families": ("ownership",), "edge_types": (graphdata.DIRECTOR_OF,),
     "purpose": "Shared board membership.",
     "requires_ubo_permission": True},
    {"key": "addresses", "label": "Shared addresses",
     "families": ("ownership",), "edge_types": (graphdata.REGISTERED_AT,),
     "purpose": "Registered at the same place as whom.",
     "requires_ubo_permission": True},
    {"key": "group", "label": "Connected counterparty group",
     "families": ("ownership", "guarantee"),
     "edge_types": (graphdata.OWNS, graphdata.PROVIDES, graphdata.COVERS),
     "purpose": "The members of the candidate obligor group and why."},
    {"key": "supply", "label": "Supply chain",
     "families": ("supply",), "edge_types": (graphdata.SUPPLIES_TO,),
     "purpose": "Who supplies whom. Never forms a regulatory group."},
    {"key": "guarantees", "label": "Guarantee network",
     "families": ("guarantee",),
     "edge_types": (graphdata.PROVIDES, graphdata.COVERS),
     "purpose": "Who stands behind whose obligations."},
    {"key": "exposure", "label": "Exposure network",
     "families": ("exposure",),
     "edge_types": (graphdata.EXPOSED_TO, graphdata.LENT_TO,
                    graphdata.HOLDS),
     "purpose": "Financial claims between counterparties."},
    {"key": "contagion", "label": "Contagion paths",
     "families": ("exposure", "guarantee"),
     "edge_types": (graphdata.EXPOSED_TO, graphdata.LENT_TO,
                    graphdata.HOLDS, graphdata.PROVIDES, graphdata.COVERS),
     "purpose": "The paths a shock would travel. DebtRank runs over this."},
    {"key": "full", "label": "Everything",
     "families": tuple(EDGE_SOURCES), "edge_types": (),
     "purpose": "Every observed relationship at once. Slow and usually "
                "unreadable; kept because sometimes the question really is "
                "'what else is there'."},
)

NETWORK_VIEW_KEYS: tuple[str, ...] = tuple(
    view["key"] for view in NETWORK_VIEWS)

VIEW_BY_KEY: dict[str, dict[str, Any]] = {
    view["key"]: view for view in NETWORK_VIEWS}


@dataclass
class EgoGraph:
    """A bounded neighbourhood, and an honest account of what was left out."""

    centre: str
    period: str
    as_of: str
    view: str
    depth: int
    nodes: list[dict[str, Any]] = field(default_factory=list)
    edges: list[dict[str, Any]] = field(default_factory=list)
    truncated: bool = False
    reached_depth: int = 0
    omitted_nodes: int = 0
    omitted_edges: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "centre": self.centre,
            "period": self.period,
            "as_of": self.as_of,
            "view": self.view,
            "view_label": VIEW_BY_KEY[self.view]["label"],
            "view_purpose": VIEW_BY_KEY[self.view]["purpose"],
            "requested_depth": self.depth,
            "reached_depth": self.reached_depth,
            "node_count": len(self.nodes),
            "edge_count": len(self.edges),
            "truncated": self.truncated,
            "omitted_nodes": self.omitted_nodes,
            "omitted_edges": self.omitted_edges,
            "truncation_note": (
                f"The neighbourhood was larger than this request returns. "
                f"{self.omitted_nodes} node(s) and {self.omitted_edges} "
                f"edge(s) beyond the caps of {MAX_NODES} and {MAX_EDGES} "
                f"were not returned. Narrow the view or reduce the depth."
                if self.truncated else ""),
            "nodes": self.nodes,
            "edges": self.edges,
            "origin": ORIGIN,
            "service_version": SERVICE_VERSION,
        }


def _view_edges(view_key: str, as_of: str) -> pd.DataFrame:
    view = VIEW_BY_KEY[view_key]
    blocks: list[pd.DataFrame] = []
    for family in view["families"]:
        frame = graphdata.as_of(_load(EDGE_SOURCES[family]), as_of)
        if view["edge_types"]:
            frame = frame[frame["edge_type"].isin(view["edge_types"])]
        if frame.empty:
            continue
        keep = [c for c in ("edge_id", "edge_type", "from_node", "to_node",
                            "ownership_pct", "voting_pct", "amount",
                            "instrument", "role", "share_of_supplier_revenue",
                            "share_of_buyer_cogs", "source", "confidence",
                            "valid_from", "valid_to")
                if c in frame.columns]
        block = frame[keep].copy()
        block["family"] = family
        blocks.append(block)
    if not blocks:
        return pd.DataFrame(columns=["edge_id", "edge_type", "from_node",
                                     "to_node", "family"])
    return pd.concat(blocks, ignore_index=True)


def ego_graph(borrower_id: str, period: str, *, view: str = "ownership",
              depth: int = DEFAULT_DEPTH) -> EgoGraph:
    """The neighbourhood around one borrower, expanded server-side. Phase 3.9.

    Breadth-first from the centre, following edges in BOTH directions. A
    directed expansion would answer a different question: following only
    outgoing ownership finds what the borrower owns and misses its parent,
    which is the single fact a group structure exists to show.
    """
    if view not in VIEW_BY_KEY:
        raise ValueError(
            f"'{view}' is not a network view. Available: "
            + ", ".join(NETWORK_VIEW_KEYS))
    depth = max(0, min(int(depth), MAX_DEPTH))
    stamp = as_of_date(period)
    edges = _view_edges(view, stamp)

    result = EgoGraph(centre=borrower_id, period=period, as_of=stamp,
                      view=view, depth=depth)
    if edges.empty:
        result.nodes = [_node_payload(borrower_id)]
        return result

    by_node: dict[str, list[int]] = {}
    for position, (source, target) in enumerate(
            zip(edges["from_node"].astype(str),
                edges["to_node"].astype(str), strict=True)):
        by_node.setdefault(source, []).append(position)
        by_node.setdefault(target, []).append(position)

    seen_nodes: set[str] = {borrower_id}
    seen_edges: set[int] = set()
    frontier = [borrower_id]
    # Counted exactly, as the traversal drops them. Deriving the omitted
    # count from the size of the whole index would report the rest of the
    # BOOK rather than the rest of this neighbourhood, which reads as a much
    # bigger truncation than actually happened.
    dropped_edges: set[int] = set()
    dropped_nodes: set[str] = set()

    for step in range(1, depth + 1):
        following: list[str] = []
        for node in frontier:
            for position in by_node.get(node, ()):
                if position in seen_edges:
                    continue
                if len(seen_edges) >= MAX_EDGES:
                    result.truncated = True
                    dropped_edges.add(position)
                    continue
                seen_edges.add(position)
                for end in (str(edges["from_node"].iloc[position]),
                            str(edges["to_node"].iloc[position])):
                    if end in seen_nodes:
                        continue
                    if len(seen_nodes) >= MAX_NODES:
                        result.truncated = True
                        dropped_nodes.add(end)
                        continue
                    seen_nodes.add(end)
                    following.append(end)
        result.reached_depth = step
        if not following:
            break
        frontier = following

    result.omitted_edges = len(dropped_edges - seen_edges)
    result.omitted_nodes = len(dropped_nodes - seen_nodes)

    chosen = edges.iloc[sorted(seen_edges)]
    result.edges = [
        {k: (None if pd.isna(v) else v) for k, v in row.items()}
        for row in chosen.to_dict(orient="records")]
    result.nodes = [_node_payload(name) for name in sorted(seen_nodes)]
    return result


@lru_cache(maxsize=1)
def _node_index() -> dict[str, dict[str, Any]]:
    frame = _load("corporate_graph_nodes")
    return {str(row.node_id): {"node_id": str(row.node_id),
                               "node_type": str(row.node_type),
                               "label": str(row.label),
                               "detail": str(row.detail)}
            for row in frame.itertuples()}


def _node_payload(node_id: str) -> dict[str, Any]:
    known = _node_index().get(node_id)
    if known:
        return dict(known)
    # A node that appears on an edge but not in the node table. GQ-04 REJECTS
    # this, so it should never happen - but returning it as an unlabelled
    # node beats dropping it and showing an edge that goes nowhere.
    return {"node_id": node_id, "node_type": "UNKNOWN", "label": node_id,
            "detail": "This node appears on an edge but is not in the node "
                      "table. It is a data-quality defect, not a borrower."}


# ------------------------------------------------------------ the snapshot


def borrower_row(borrower_id: str, period: str) -> pd.Series:
    frame = _load(SNAPSHOT)
    block = frame[(frame["borrower_id"] == borrower_id)
                  & (frame["period"] == period)]
    if block.empty:
        raise BorrowerNotFound(
            f"'{borrower_id}' has no Borrower 360 row for {period}. It may "
            "exist in another quarter: a borrower that had not yet been "
            "onboarded, or one whose relationship had ended, is absent from "
            "that quarter by design rather than missing from the data.")
    return block.iloc[0]


def group_view(borrower_id: str, period: str) -> dict[str, Any]:
    """The six group concepts for one borrower, side by side. Phase 3.11."""
    frame = _load(GROUPS)
    block = frame[(frame["borrower_id"] == borrower_id)
                  & (frame["period"] == period)]
    if block.empty:
        return {
            "borrower_id": borrower_id,
            "period": period,
            "status": gs.NOT_AVAILABLE,
            "reason": "The derived graph has not been computed for this "
                      "quarter.",
            "concepts": [dict(concept, value=gs.NOT_AVAILABLE)
                         for concept in GROUP_CONCEPTS],
        }
    row = block.iloc[0]
    concepts: list[dict[str, Any]] = []
    for concept in GROUP_CONCEPTS:
        column = concept["column"]
        if not column:
            value = "See the hidden-relationship candidates for this borrower"
        elif column in block.columns:
            raw = row[column]
            value = gs.NOT_AVAILABLE if pd.isna(raw) else raw
            if isinstance(value, float) and not pd.isna(value):
                value = str(int(value))
        else:
            value = gs.NOT_AVAILABLE
        entry = dict(concept)
        entry["value"] = value
        if concept["key"] == "connected_counterparty_group":
            entry["size"] = int(row["connected_group_size"])
            entry["name"] = str(row["group_name"])
            entry["role"] = str(row["group_role"])
        if concept["key"] == "exposure_limit_group":
            entry["utilisation_pct"] = (
                None if pd.isna(row["group_utilisation_pct"])
                else float(row["group_utilisation_pct"]))
            entry["limit_pct"] = float(row["group_limit_pct"])
            entry["status"] = str(row["group_utilisation_status"])
            entry["parameter_caveat"] = str(row["parameter_caveat"])
        concepts.append(entry)

    return {
        "borrower_id": borrower_id,
        "period": period,
        "as_of": str(row["as_of"]),
        "status": "AVAILABLE",
        "concepts": concepts,
        "graph_dq_status": str(row["graph_dq_status"]),
        "note": ("These six answer different questions and do not agree by "
                 "design. Collapsing them into one 'group' produces a number "
                 "that is wrong for every one of them."),
        "origin": ORIGIN,
    }


# ---------------------------------------------------------------- searching


def find(term: str, period: str | None = None, *,
         limit: int = 25) -> dict[str, Any]:
    """Search on the twelve declared attributes. Phase 3.2.

    Delegates to `search`, which returns `resolved`, `ambiguous` and
    `not_found` separately. An ambiguous term is never silently resolved to
    its best match: two borrowers with similar names is the case where
    picking one quietly is worst.
    """
    chosen = period or latest_period()
    # Searched over the SNAPSHOT, not the customer master. Nine of the twelve
    # searchable attributes - rating, stage, limit status, delinquency
    # bucket, the flags - live on the snapshot and nowhere else, and a search
    # over the master would silently support three of them and reject the
    # rest as unknown facets.
    frame = _load(SNAPSHOT)
    payload = dict(search_mod.search(
        frame, search_mod.Query(text=term, period=chosen, limit=limit)))
    payload["period"] = chosen
    payload["origin"] = ORIGIN
    return payload


def filter_cohort(period: str | None = None, *,
                  facets: dict[str, Any] | None = None,
                  flags: list[str] | None = None,
                  borrower_ids: list[str] | None = None,
                  limit: int = 50) -> dict[str, Any]:
    """A faceted search. Phase 3.2, 3.3.

    Kept separate from `find` because they answer different questions and
    return different shapes: `find` resolves a name, this one describes a
    cohort. A caller that gets a segment back from a name lookup has been
    told something it did not ask.
    """
    chosen = period or latest_period()
    payload = dict(search_mod.search(
        _load(SNAPSHOT),
        search_mod.Query(borrower_ids=list(borrower_ids or []),
                         facets=dict(facets or {}), flags=list(flags or []),
                         period=chosen, limit=limit)))
    payload["period"] = chosen
    payload["origin"] = ORIGIN
    return payload
