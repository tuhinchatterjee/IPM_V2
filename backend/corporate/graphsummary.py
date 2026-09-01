"""The graph fields on the Borrower 360, actually computed. Phase 2.18.

Twenty fields on the Borrower 360 snapshot come from the derived graph. Until
now every one of them read ``NOT COMPUTED`` - honest, and useless. This module
runs the derivation per quarter and produces the two datasets the lineage
table has always pointed at:

``corporate_connected_groups``  one row per borrower per quarter, carrying its
                                three group identifiers, its counts and its
                                five network measures.
``corporate_graph_dq``          one row per data-quality issue per quarter,
                                which is the register the per-borrower quality
                                verdict is aggregated from.

Three sentinels, and the difference between them
------------------------------------------------
``NOT_AVAILABLE``        the measure could have been computed for this
                         borrower and was not, because the borrower is not in
                         that graph at that date. A standalone borrower has no
                         betweenness; it does not have a betweenness of zero.
``NOT_APPLICABLE``       the measure does not apply to this borrower at all -
                         a group role for a borrower in no group.
``DATA_QUALITY_BLOCKED`` the input failed a check that REJECTS, so the
                         computation did not run. The reason is in the DQ
                         register, keyed by the same borrower and quarter.

Zero is used for exactly one thing: a count that was taken and came back
empty. `director_count = 0` means the graph was searched and there are no
directors, which is a measurement. Everything else that is absent says which
kind of absent it is.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from backend.corporate import ORIGIN, graphdata
from backend.corporate import graphmath as gm
from backend.corporate import graphquality as gq
from backend.corporate import network as net
from backend.corporate.universe import (
    ELIGIBLE_CAPITAL_REFERENCE,
    GROUP_LIMIT_PCT,
    INVESTIGATION_TRIGGER_PCT,
    UNVERIFIED_REGULATORY_PARAMETER,
)

logger = logging.getLogger(__name__)

SUMMARY_VERSION = "1.0.0"

GROUPS_DATASET = "corporate_connected_groups"
DQ_DATASET = "corporate_graph_dq"

NOT_AVAILABLE = gq.NOT_AVAILABLE
NOT_APPLICABLE = gq.NOT_APPLICABLE
DATA_QUALITY_BLOCKED = gq.DATA_QUALITY_BLOCKED
AVAILABLE = "AVAILABLE"

#: Where each numeric measure's sentinel lives.
#:
#: The sentinel does NOT go in the measure column. Putting the string
#: "NOT_AVAILABLE" in `network_risk_score` alongside 3,000 floats makes the
#: whole column VARCHAR, and a measure that cannot be averaged, ranked or
#: charted is not a measure - it is a caption. So `corporate_connected_groups`
#: keeps its numbers numeric and null where absent, and a parallel status
#: column says WHICH kind of absent. The Borrower 360 snapshot, which is a
#: denormalised read for a screen rather than an analytical dataset, renders
#: the two back into one displayable value.
MEASURE_STATUS: dict[str, str] = {
    "debtrank_impact": "debtrank_status",
    "pagerank_transmits": "centrality_status",
    "pagerank_hurt": "centrality_status",
    "betweenness": "centrality_status",
    "louvain_community": "community_status",
    "network_risk_score": "network_risk_score_status",
    "ubo_count": "ownership_status",
    "group_exposure": "group_status",
    "group_utilisation_pct": "group_status",
    "graph_confidence": "confidence_status",
    # `connected_group_size` is deliberately absent. A borrower in no derived
    # group has a group of one - itself - and that is a measurement, not an
    # absence. Giving it a status column would put it under NOT_APPLICABLE
    # alongside the group figures that genuinely do not exist.
    "relationship_confidence": "confidence_status",
}

STATUS_COLUMNS: tuple[str, ...] = tuple(sorted(set(MEASURE_STATUS.values())))

#: Per-borrower graph quality verdict.
DQ_OK = "OK"
DQ_DEGRADED = "DEGRADED"
DQ_INSUFFICIENT = "INSUFFICIENT"

#: Group roles. STANDALONE is a real answer, not a missing one.
ROLE_PARENT = "PARENT"
ROLE_SUBSIDIARY = "SUBSIDIARY"
ROLE_AFFILIATE = "AFFILIATE"
ROLE_STANDALONE = "STANDALONE"

#: An effective stake at or above this joins two corporates into one
#: effective-ownership group, and makes a natural person a UBO.
OWNERSHIP_GROUP_THRESHOLD_PCT = gm.UBO_THRESHOLD_PCT

#: Published precision for the network measures.
#:
#: Rounded HERE, at the point of computation, rather than at the point of
#: display. DebtRank impacts and PageRank scores over 3,000 nodes are small
#: numbers - a typical impact is 4e-05 - so two decimals would render the
#: whole column as zero and destroy the ranking the measure exists to give.
#: Six is the precision the measure is published at, and every consumer sees
#: the same figure because none of them does its own rounding.
MEASURE_PRECISION = 6

#: Capital for DebtRank. Book equity where the borrower has published a
#: statement by the quarter end, floored so a borrower with negative equity
#: does not become infinitely fragile. Borrowers with no statement use the
#: population median rather than the floor: the floor would make them the most
#: vulnerable nodes in the network purely for not having filed.
CAPITAL_FLOOR = 5.0


@dataclass
class QuarterResult:
    """One quarter's derivation, and how long each stage took."""

    period: str
    as_of: str
    rows: list[dict[str, Any]] = field(default_factory=list)
    issues: list[dict[str, Any]] = field(default_factory=list)
    timings: dict[str, float] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)


def _capital(universe_frames: dict[str, pd.DataFrame], period: str,
             as_of_date: str, borrowers: list[str]) -> dict[str, float]:
    """Book equity as at the quarter end, on the published-by rule.

    Uses the statement the bank had by the quarter end, not the one whose
    fiscal year matches it. Joining on fiscal year would give every DebtRank
    capital figure a few months of foresight.
    """
    financials = universe_frames["corporate_financials"]
    published = financials[
        pd.to_datetime(financials["statement_published_date"])
        <= pd.Timestamp(as_of_date)]
    if published.empty:
        return dict.fromkeys(borrowers, CAPITAL_FLOOR)
    latest = published.sort_values("statement_published_date").groupby(
        "borrower_id", as_index=False).last()
    equity = dict(zip(latest["borrower_id"].astype(str),
                      pd.to_numeric(latest["book_equity"], errors="coerce"),
                      strict=True))
    known = [v for v in equity.values() if pd.notna(v) and v > 0]
    fallback = float(np.median(known)) if known else CAPITAL_FLOOR
    out: dict[str, float] = {}
    for name in borrowers:
        value = equity.get(name)
        if value is None or pd.isna(value):
            out[name] = fallback
        else:
            out[name] = max(float(value), CAPITAL_FLOOR)
    return out


def _ownership_groups(solved: gm.EffectiveOwnership,
                      corporates: set[str]) -> dict[str, str]:
    """Weak components of the effective stake at or above the threshold.

    Over EFFECTIVE stake, not direct: a parent that holds 60% of a holding
    company that holds 60% of an operating company has an effective 36% of the
    operating company and belongs in its group, and a rule over direct edges
    alone would miss exactly the structures the pyramid exists to create.
    """
    if not solved.nodes:
        return {}
    cut = OWNERSHIP_GROUP_THRESHOLD_PCT / 100.0
    rows, cols = np.nonzero(solved.matrix >= cut)
    parent: dict[str, str] = {}

    def find(name: str) -> str:
        parent.setdefault(name, name)
        while parent[name] != name:
            parent[name] = parent[parent[name]]
            name = parent[name]
        return name

    for i, j in zip(rows, cols, strict=True):
        owner, owned = solved.nodes[i], solved.nodes[j]
        if owner in solved.blocked_nodes or owned in solved.blocked_nodes:
            continue
        a, b = find(owner), find(owned)
        if a != b:
            parent[max(a, b)] = min(a, b)

    return {name: find(name) for name in parent if name in corporates}


def _control_groups(closure: gm.ControlClosure, corporates: set[str],
                    borrowers: set[str]) -> tuple[dict[str, str],
                                                  dict[str, str]]:
    """Control bloc per entity, and the role the borrower plays in it.

    The bloc is named by its head: the entity that reaches every other member
    and is itself reached by none. That head is often a natural person, which
    is correct - a family group is a control group.

    The ROLE, though, is about the corporate structure, and the first version
    got it wrong. Reading "controlled by someone" as SUBSIDIARY made 3,020 of
    3,253 borrowers subsidiaries, because in this book almost every company
    has a majority shareholder. A company wholly owned by its founder is not
    a subsidiary of anything; it is a standalone company with an owner. So the
    four roles are decided over the CORPORATE members of the bloc only:

    ``PARENT``      controls at least one other corporate in the bloc;
    ``SUBSIDIARY``  another corporate in the bloc controls it;
    ``AFFILIATE``   shares the bloc with other corporates, but no control
                    relation between them either way - common control by a
                    person, or a mutual-control bloc with no single top;
    ``STANDALONE``  the only corporate in its bloc.

    `corporates` is every legal entity of corporate type, INCLUDING the
    holding companies that are not themselves borrowers. Restricting it to
    borrowers made 1,284 borrowers AFFILIATE that are in fact subsidiaries of
    an intermediate holding company - the holding company was invisible, so
    two borrowers under it looked like siblings under a person rather than
    subsidiaries of a company. `borrowers` is what the result is keyed by.
    """
    group_of: dict[str, str] = {}
    role_of: dict[str, str] = {}
    if not closure.nodes:
        return group_of, role_of

    reach = closure.effective
    index = {name: i for i, name in enumerate(closure.nodes)}

    for top in np.nonzero(reach.any(axis=1))[0]:
        if reach[:, top].any():
            # Controlled by someone else, so not the head of its own bloc.
            continue
        head = closure.nodes[top]
        for member in [head, *[closure.nodes[j]
                               for j in np.nonzero(reach[top])[0]]]:
            group_of.setdefault(member, head)

    # Mutual-control blocs have no uncontrolled head. Name them by their
    # lowest member so the id is stable between runs.
    blocs: dict[int, list[str]] = {}
    for name, component in closure.component_of.items():
        blocs.setdefault(component, []).append(name)
    for members in blocs.values():
        if len(members) > 1:
            head = min(members)
            for member in members:
                group_of.setdefault(member, head)

    members_of: dict[str, list[str]] = {}
    for member, head in group_of.items():
        members_of.setdefault(head, []).append(member)

    for member, head in group_of.items():
        if member not in borrowers:
            continue
        siblings = [n for n in members_of[head]
                    if n in corporates and n != member]
        if not siblings:
            role_of[member] = ROLE_STANDALONE
            continue
        row = reach[index[member]]
        controls_a_sibling = any(row[index[n]] for n in siblings)
        controlled_by_a_sibling = any(reach[index[n], index[member]]
                                      for n in siblings)
        if controls_a_sibling and not controlled_by_a_sibling:
            role_of[member] = ROLE_PARENT
        elif controlled_by_a_sibling:
            role_of[member] = ROLE_SUBSIDIARY
        else:
            role_of[member] = ROLE_AFFILIATE

    return ({k: v for k, v in group_of.items() if k in borrowers}, role_of)


def _edge_counts(frames: dict[str, Any], borrowers: list[str]
                 ) -> dict[str, dict[str, int]]:
    """The five counts, taken once over the as-of frames.

    Counted rather than defaulted. A borrower with no directors gets 0, which
    is a measurement; a borrower absent from the graph entirely still gets 0
    here, and the distinction is carried by `graph_dq_status` instead - the
    counts are over observed edges, and the absence of an edge IS the answer.
    """
    empty = dict.fromkeys(borrowers, 0)
    counts = {name: dict(empty) for name in
              ("director_count", "supplier_count", "customer_count",
               "guarantee_links", "exposure_network_links")}

    own = frames["ownership"]
    if not own.empty:
        directors = own[own["edge_type"] == graphdata.DIRECTOR_OF]
        for name, total in directors["to_node"].astype(str).value_counts(
                ).items():
            if name in counts["director_count"]:
                counts["director_count"][name] = int(total)

    supply = frames["supply"]
    if not supply.empty:
        for name, total in supply["to_node"].astype(str).value_counts().items():
            if name in counts["supplier_count"]:
                counts["supplier_count"][name] = int(total)
        for name, total in supply["from_node"].astype(str).value_counts(
                ).items():
            if name in counts["customer_count"]:
                counts["customer_count"][name] = int(total)

    for key, frame in (("guarantee_links", frames["guarantees"]),
                       ("exposure_network_links", frames["exposure"])):
        if frame.empty:
            continue
        touching = pd.concat([frame["from_node"], frame["to_node"]]).astype(str)
        for name, total in touching.value_counts().items():
            if name in counts[key]:
                counts[key][name] = int(total)

    return counts


def _weakest_confidence(frames: dict[str, Any],
                        borrowers: list[str]) -> dict[str, float]:
    """The weakest evidence touching each borrower. Phase 2.16.

    The confidence of a borrower's place in the graph is the confidence of the
    worst assertion that put it there. Averaging would let one relationship
    manager's note hide behind five registry filings, which is the opposite of
    what a reviewer needs to see.
    """
    weakest: dict[str, float] = {}
    for key in ("ownership", "supply", "exposure", "guarantees"):
        frame = frames.get(key)
        if frame is None or frame.empty or "confidence" not in frame:
            continue
        # The WEAKEST is different: a missing confidence is the weakest
        # possible evidence, so filling it with zero is the honest reading
        # here and the conservative one. Named, so the asymmetry with the
        # mean above is deliberate rather than an oversight.
        values = pd.to_numeric(frame["confidence"], errors="coerce").fillna(0.0)
        for side in ("from_node", "to_node"):
            grouped = pd.DataFrame({
                "node": frame[side].astype(str).to_numpy(),
                "confidence": values.to_numpy()}).groupby("node")[
                    "confidence"].min()
            for name, value in grouped.items():
                current = weakest.get(str(name))
                if current is None or value < current:
                    weakest[str(name)] = float(value)
    return {name: weakest[name] for name in borrowers if name in weakest}


def _mean_confidence(frames: dict[str, Any],
                     borrowers: list[str]) -> dict[str, float]:
    """The average confidence of the edges touching each borrower.

    Kept SEPARATE from the weakest. They answer different questions and the
    product deliberately shows both: the mean says how well evidenced the
    borrower is overall, the weakest says what the conclusion actually rests
    on. Showing only the mean is how one relationship manager's note ends up
    hidden behind five registry filings.
    """
    totals: dict[str, float] = {}
    counts: dict[str, int] = {}
    for key in ("ownership", "supply", "exposure", "guarantees"):
        frame = frames.get(key)
        if frame is None or frame.empty or "confidence" not in frame:
            continue
        # NOT filled with zero. A missing confidence counted as zero drags
        # the MEAN down and reads as weak evidence rather than as absent
        # evidence - two different statements, and only one of them is about
        # the borrower. GQ-09 REJECTS a missing confidence outright, so this
        # cannot arise in a passing build; the code should not depend on that
        # being true for it to be correct.
        values = pd.to_numeric(frame["confidence"], errors="coerce")
        for side in ("from_node", "to_node"):
            block = pd.DataFrame({
                "node": frame[side].astype(str).to_numpy(),
                "confidence": values.to_numpy()}).dropna(
                    subset=["confidence"]).groupby("node")[
                    "confidence"].agg(["sum", "count"])
            for name, row in block.iterrows():
                totals[str(name)] = totals.get(str(name), 0.0) + float(row["sum"])
                counts[str(name)] = counts.get(str(name), 0) + int(row["count"])
    return {name: totals[name] / counts[name]
            for name in borrowers if counts.get(name)}


def _group_exposure(universe_frames: dict[str, pd.DataFrame], period: str,
                    group_of: dict[str, str]) -> tuple[dict[str, float],
                                                       dict[str, str]]:
    """Total EAD per connected group, and a readable name for it.

    The group's exposure is the sum of its members' EAD, which is the number
    the group limit is measured against - and the reason `group_utilisation`
    could not be computed before the graph existed. The group's NAME is its
    largest member by EAD, because that is the name the group is known by in
    every credit committee.
    """
    limits = universe_frames["corporate_limits"]
    block = limits[limits["period"] == period]
    ead = dict(zip(block["borrower_id"].astype(str),
                   pd.to_numeric(block["ifrs9_ead"], errors="coerce").fillna(0.0),
                   strict=True))
    master = universe_frames["corporate_customer_master"]
    names_block = master[master["period"] == period]
    legal = dict(zip(names_block["borrower_id"].astype(str),
                     names_block["legal_name"].astype(str), strict=True))

    totals: dict[str, float] = {}
    biggest: dict[str, tuple[float, str]] = {}
    for borrower, group in group_of.items():
        amount = float(ead.get(borrower, 0.0))
        totals[group] = totals.get(group, 0.0) + amount
        current = biggest.get(group)
        # Ties break on the borrower id so the name is stable between runs.
        if current is None or (amount, borrower) > (current[0], current[1]):
            biggest[group] = (amount, borrower)
    labels = {group: f"{legal.get(who, who)} Group"
              for group, (_, who) in biggest.items()}
    return totals, labels


def derive(universe_frames: dict[str, pd.DataFrame], period: str,
           as_of_date: str, borrowers: list[str]) -> QuarterResult:
    """Every graph field for one quarter. Phase 2.18.

    Runs the quality gate FIRST and honours it. A computation whose input was
    rejected does not run and its fields say DATA_QUALITY_BLOCKED - which is
    the only reason the gate is worth having.
    """
    out = QuarterResult(period=period, as_of=as_of_date)
    clock = time.perf_counter

    start = clock()
    report = gq.run(universe_frames, as_of_date)
    out.timings["quality"] = clock() - start
    frames = gq.as_of_frames(universe_frames, as_of_date)

    for result in report.results:
        out.issues.append({
            "issue_id": f"DQ-{period.replace(' ', '')}-{result.check_id}",
            "period": period,
            "as_of": as_of_date,
            "check_id": result.check_id,
            "check": result.name,
            "status": result.status,
            "observed": result.observed,
            "threshold": result.threshold,
            "scope": result.scope,
            "affected_entities": len(result.affected),
            "blocks": ", ".join(result.blocks) if result.status == gq.REJECT
            else "",
            "quality_version": gq.QUALITY_VERSION,
            "origin": ORIGIN,
        })

    corporates = set(borrowers)

    # ---- ownership, control, groups --------------------------------------
    start = clock()
    ownership_graph = gm.build_ownership_graph(
        universe_frames["corporate_ownership_edges"], as_of_date)
    out.timings["ownership_graph"] = clock() - start

    start = clock()
    solved = gm.effective_ownership(ownership_graph)
    out.timings["effective_ownership"] = clock() - start

    start = clock()
    closure = gm.control_closure(ownership_graph)
    out.timings["control_closure"] = clock() - start

    start = clock()
    interdependence = gm.interdependence_predicates(
        universe_frames["corporate_supply_chain"],
        universe_frames["corporate_guarantees"],
        universe_frames["corporate_exposure_network"], as_of_date)
    groups = gm.connected_groups(closure, interdependence,
                                 population=len(borrowers))
    out.timings["connected_groups"] = clock() - start

    node_types = universe_frames["corporate_graph_nodes"]
    corporate_nodes = set(
        node_types.loc[node_types["node_type"] == graphdata.CORPORATE,
                       "node_id"].astype(str))
    ownership_group = _ownership_groups(solved, corporates)
    control_group, control_role = _control_groups(
        closure, corporate_nodes, corporates)

    ubo_count: dict[str, int] = {}
    people = set(
        node_types.loc[node_types["node_type"] == graphdata.NATURAL_PERSON,
                       "node_id"].astype(str))
    if solved.nodes:
        cut = OWNERSHIP_GROUP_THRESHOLD_PCT / 100.0
        rows, cols = np.nonzero(solved.matrix >= cut)
        for i, j in zip(rows, cols, strict=True):
            if solved.nodes[i] in people:
                owned = solved.nodes[j]
                ubo_count[owned] = ubo_count.get(owned, 0) + 1

    # ---- network analytics -----------------------------------------------
    start = clock()
    exposure = net.exposure_graph(
        universe_frames["corporate_exposure_network"],
        universe_frames["corporate_guarantees"], as_of_date)
    capital = _capital(universe_frames, period, as_of_date,
                       list(exposure.nodes))
    out.timings["exposure_graph"] = clock() - start

    network_blocked = report.is_blocked(gq.DEBTRANK)
    centrality_blocked = report.is_blocked(gq.CENTRALITY)

    impact: dict[str, float] = {}
    forward: dict[str, float] = {}
    reverse: dict[str, float] = {}
    between: dict[str, float] = {}
    community: dict[str, int] = {}
    score: net.NetworkRiskScore | None = None

    if not network_blocked and exposure.size:
        start = clock()
        impact = net.debtrank_all(exposure, capital)
        out.timings["debtrank"] = clock() - start
    if not centrality_blocked and exposure.size:
        start = clock()
        forward = net.pagerank(exposure)
        reverse = net.pagerank(exposure, reverse=True)
        between = net.betweenness(exposure)
        community = net.louvain(exposure)
        out.timings["centrality"] = clock() - start
    if (not network_blocked and not centrality_blocked
            and not report.is_blocked(gq.NETWORK_RISK_SCORE) and exposure.size):
        start = clock()
        score = net.network_risk_score(
            exposure, capital,
            population=[n for n in exposure.nodes if n in corporates],
            debtrank_impact=impact)
        out.timings["network_risk_score"] = clock() - start

    counts = _edge_counts(frames, borrowers)
    confidence = _weakest_confidence(frames, borrowers)
    mean_confidence = _mean_confidence(frames, borrowers)
    group_exposure, group_labels = _group_exposure(
        universe_frames, period, groups.group_of)
    in_exposure = set(exposure.nodes)

    entity_issues: dict[str, int] = {}
    for result in report.results:
        if result.status == gq.PASS or result.scope != gq.SCOPE_ENTITY:
            continue
        for name in result.affected:
            entity_issues[name] = entity_issues.get(name, 0) + 1

    def measure(store: dict[str, Any], name: str, blocked: bool,
                computation: str, *, precision: int = MEASURE_PRECISION
                ) -> tuple[float, str]:
        """The number and its status, never one standing in for the other."""
        if blocked or report.is_blocked(computation, name):
            return float("nan"), DATA_QUALITY_BLOCKED
        if name not in in_exposure:
            return float("nan"), NOT_AVAILABLE
        value = store.get(name)
        if value is None:
            return float("nan"), NOT_AVAILABLE
        return round(float(value), precision), AVAILABLE


    def worst(*statuses: str) -> str:
        """The status a group of measures shares, most severe first."""
        for candidate in (DATA_QUALITY_BLOCKED, NOT_AVAILABLE,
                          NOT_APPLICABLE):
            if candidate in statuses:
                return candidate
        return AVAILABLE

    for borrower in borrowers:
        blocked_ownership = (solved.is_blocked(borrower)
                             or report.is_blocked(gq.EFFECTIVE_OWNERSHIP,
                                                  borrower))
        group_id = groups.group_of.get(borrower)
        weakest = confidence.get(borrower)
        mean = mean_confidence.get(borrower)

        impact_value, impact_status = measure(
            impact, borrower, network_blocked, gq.DEBTRANK)
        forward_value, forward_status = measure(
            forward, borrower, centrality_blocked, gq.CENTRALITY)
        reverse_value, _ = measure(
            reverse, borrower, centrality_blocked, gq.CENTRALITY)
        between_value, between_status = measure(
            between, borrower, centrality_blocked, gq.CENTRALITY)
        community_value, community_status = measure(
            community, borrower, centrality_blocked, gq.COMMUNITIES,
            precision=0)

        if score is None:
            score_value, score_status = float("nan"), DATA_QUALITY_BLOCKED
        elif borrower in score.scores:
            score_value = round(score.scores[borrower], 2)
            score_status = AVAILABLE
        else:
            score_value, score_status = float("nan"), NOT_AVAILABLE

        exposure_total = (group_exposure.get(group_id, 0.0) if group_id
                          else None)

        row: dict[str, Any] = {
            "borrower_id": borrower,
            "period": period,
            "as_of": as_of_date,

            # ---- identifiers. A sentinel is idiomatic here: these are
            # dimensions, and "NOT_APPLICABLE" is a legitimate category.
            "effective_ownership_group_id": (
                DATA_QUALITY_BLOCKED if blocked_ownership
                else ownership_group.get(borrower, NOT_APPLICABLE)),
            "control_group_id": control_group.get(borrower, NOT_APPLICABLE),
            "connected_group_id": group_id or NOT_APPLICABLE,
            "group_name": (group_labels.get(group_id, NOT_APPLICABLE)
                           if group_id else NOT_APPLICABLE),
            "group_role": (control_role.get(borrower)
                           or (ROLE_AFFILIATE if group_id
                               else ROLE_STANDALONE)),

            # ---- counts. Zero here IS a measurement: the graph was searched
            # and there is nothing there.
            "director_count": counts["director_count"][borrower],
            "supplier_count": counts["supplier_count"][borrower],
            "customer_count": counts["customer_count"][borrower],
            "guarantee_links": counts["guarantee_links"][borrower],
            "exposure_network_links":
                counts["exposure_network_links"][borrower],
            "dq_issue_count": entity_issues.get(borrower, 0),

            # ---- numeric measures, numeric. Null where absent; the reason
            # is in the matching status column.
            "ubo_count": (float("nan") if blocked_ownership
                          else float(ubo_count.get(borrower, 0))),
            "connected_group_size": (float(groups.size_of(borrower))
                                     if group_id else 1.0),
            "group_exposure": (round(exposure_total, 2)
                               if exposure_total is not None
                               else float("nan")),
            "group_utilisation_pct": (
                round(exposure_total / ELIGIBLE_CAPITAL_REFERENCE * 100, 4)
                if exposure_total is not None else float("nan")),
            "debtrank_impact": impact_value,
            "pagerank_transmits": forward_value,
            "pagerank_hurt": reverse_value,
            "betweenness": between_value,
            "louvain_community": community_value,
            "network_risk_score": score_value,
            "graph_confidence": (round(weakest, 4) if weakest is not None
                                 else float("nan")),
            "relationship_confidence": (round(mean, 4) if mean is not None
                                        else float("nan")),

            # ---- which kind of absent, per block of measures
            "ownership_status": (DATA_QUALITY_BLOCKED if blocked_ownership
                                 else AVAILABLE),
            "group_status": AVAILABLE if group_id else NOT_APPLICABLE,
            "debtrank_status": impact_status,
            "centrality_status": worst(forward_status, between_status),
            "community_status": community_status,
            "network_risk_score_status": score_status,
            "confidence_status": (
                AVAILABLE if (weakest is not None and mean is not None)
                else NOT_AVAILABLE),

            # ---- verdicts and governance
            "group_limit_pct": GROUP_LIMIT_PCT,
            "group_utilisation_status": _group_limit_status(exposure_total),
            "graph_dq_status": _borrower_dq_status(
                report, borrower, weakest, borrower in in_exposure),
            "snapshot_validation_status": _validation_status(
                report, borrower, entity_issues.get(borrower, 0), weakest),
            "network_risk_score_label": net.NRS_LABEL,
            "parameter_caveat": UNVERIFIED_REGULATORY_PARAMETER,
            "method_version": net.NETWORK_VERSION,
            "policy_version": net.POLICY_VERSION,
            "summary_version": SUMMARY_VERSION,
            "origin": ORIGIN,
        }
        out.rows.append(row)

    out.provenance = {
        "as_of": as_of_date,
        "period": period,
        "quality": report.to_dict(),
        "effective_ownership": solved.provenance(),
        "control_closure": closure.provenance(),
        "connected_groups": groups.provenance(),
        "network": {
            "nodes": exposure.size,
            "debtrank_computed": bool(impact),
            "centrality_computed": bool(forward),
            "network_risk_score_computed": score is not None,
            "label": net.NRS_LABEL,
            "debtrank_caveat": net.DEBTRANK_CAVEAT,
        },
        "timings_seconds": {k: round(v, 3) for k, v in out.timings.items()},
        "summary_version": SUMMARY_VERSION,
    }
    return out


def _group_limit_status(exposure: float | None) -> str:
    """The group's position against the group limit.

    The threshold itself is an UNVERIFIED REGULATORY PARAMETER carried from
    the framework document, not a rule this system has confirmed is currently
    binding, and every row says so.
    """
    if exposure is None:
        return NOT_APPLICABLE
    pct = exposure / ELIGIBLE_CAPITAL_REFERENCE * 100
    if pct >= GROUP_LIMIT_PCT:
        return "BREACH"
    if pct >= INVESTIGATION_TRIGGER_PCT:
        return "INVESTIGATE"
    return "WITHIN LIMIT"


def _validation_status(report: gq.QualityReport, borrower: str, issues: int,
                       weakest: float | None) -> str:
    """PASSED, PASSED WITH ISSUES or FAILED, for THIS borrower's row."""
    if report.blocked(borrower):
        return "FAILED"
    if issues or weakest is None or weakest < gq.LOW_CONFIDENCE_FLOOR:
        return "PASSED WITH ISSUES"
    return "PASSED"


def _borrower_dq_status(report: gq.QualityReport, borrower: str,
                        weakest: float | None, in_graph: bool) -> str:
    """OK, DEGRADED or INSUFFICIENT for one borrower.

    INSUFFICIENT means something about THIS borrower was rejected, or it has
    no graph evidence at all. DEGRADED means THIS borrower's own evidence is
    weak.

    Portfolio-wide flags deliberately do not reach this field. The first
    version let them, and every one of the 3,253 borrowers came back DEGRADED
    because two portfolio checks were flagged - a status that reads the same
    for every row tells a reviewer nothing and trains them to ignore the
    column. Those flags belong in the DQ register, where they are about the
    portfolio, which is what they are about.
    """
    if report.blocked(borrower):
        return DQ_INSUFFICIENT
    if not in_graph and weakest is None:
        return DQ_INSUFFICIENT
    if weakest is None or weakest < gq.LOW_CONFIDENCE_FLOOR:
        return DQ_DEGRADED
    return DQ_OK


def build(universe: Any, *, periods: list[str] | None = None,
          ) -> dict[str, pd.DataFrame]:
    """Both graph datasets, for every quarter. Phase 2.18.

    `periods` restricts the derivation, which is what tests use: a full
    sixteen-quarter derivation is about four minutes, and a suite that pays
    that on every run is a suite people stop running.
    """
    frames = universe.frames
    master = frames["corporate_customer_master"]
    wanted = periods if periods is not None else list(universe.quarters)

    rows: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    provenance: list[dict[str, Any]] = []

    for period in wanted:
        block = master[master["period"] == period]
        if block.empty:
            continue
        as_of_date = str(block["period_end_date"].iloc[0])
        borrowers = sorted(block["borrower_id"].astype(str).unique())
        result = derive(frames, period, as_of_date, borrowers)
        rows.extend(result.rows)
        issues.extend(result.issues)
        provenance.append(result.provenance)
        logger.info("graph summary %s: %d borrowers, %.1fs", period,
                    len(result.rows), sum(result.timings.values()))

    groups_frame = pd.DataFrame(rows)
    dq_frame = pd.DataFrame(issues)
    groups_frame.attrs["provenance"] = provenance
    dq_frame.attrs["provenance"] = provenance
    return {GROUPS_DATASET: groups_frame, DQ_DATASET: dq_frame}


def apply_group_limits(universe_frames: dict[str, pd.DataFrame],
                       groups_frame: pd.DataFrame) -> pd.DataFrame:
    """Fill `corporate_limits`' group columns from the derived groups.

    `build_limits` has always written `group_utilisation_pct = NaN` and
    `group_utilisation_status = "NOT YET COMPUTED"`, because the group is a
    derived answer and the derivation did not exist. It does now, so the
    honest sentinel becomes a number - for the quarters the derivation
    actually ran. Quarters it did not run for keep the sentinel rather than
    inheriting another quarter's group, which would be a silent forward-fill
    of a structural fact across a period boundary.
    """
    limits = universe_frames["corporate_limits"].copy()
    if groups_frame.empty:
        return limits

    keyed = groups_frame.set_index(["borrower_id", "period"])
    index = pd.MultiIndex.from_arrays(
        [limits["borrower_id"].astype(str), limits["period"].astype(str)])

    for column in ("group_utilisation_pct", "group_utilisation_status"):
        mapped = pd.Series(index.map(keyed[column]), index=limits.index)
        if column == "group_utilisation_pct":
            numeric = pd.to_numeric(mapped, errors="coerce")
            limits[column] = numeric.where(numeric.notna(),
                                           limits[column])
        else:
            limits[column] = mapped.where(mapped.notna(), limits[column])
    return limits
