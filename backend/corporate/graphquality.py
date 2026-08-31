"""Data quality for the corporate graph. Phase 2.17.

Fourteen checks over the observed graph, each returning PASS, FLAG or
REJECT, and one rule that gives the module its purpose:

    **REJECT blocks the derived computation that depends on it.**

That is the whole point. A quality report that is written, stored and then
ignored by the engine is decoration; the value is in the engine refusing to
publish an effective-ownership percentage computed from a shareholder
register that claims 188% of a company. The alternative - compute anyway,
print a warning somewhere - produces a number that looks exactly like a
correct one and will be read as correct.

PASS / FLAG / REJECT
--------------------
``PASS``    the check found nothing.
``FLAG``    the check found something a reviewer should see, but the
            underlying mathematics is still defined. Derived computation
            proceeds and carries the flag.
``REJECT``  the input violates an assumption the mathematics needs.
            Dependent derived computation does not run and the affected
            fields report DATA_QUALITY_BLOCKED rather than a number.

Scope
-----
Each check names the derived computations it blocks, so a REJECT on the
shareholder register stops effective ownership and UBO without stopping
DebtRank, which does not read the register. A quality gate that fails the
whole Borrower 360 because one unrelated check failed teaches people to
turn it off.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from backend.corporate import graphdata

logger = logging.getLogger(__name__)

QUALITY_VERSION = "1.0.0"

PASS = "PASS"
FLAG = "FLAG"
REJECT = "REJECT"
STATUSES: tuple[str, ...] = (PASS, FLAG, REJECT)

#: How far a REJECT reaches.
#:
#: ``GLOBAL``  the input is broken in a way that invalidates the computation
#:             for everyone - a dangling edge, knowledge from the future.
#: ``ENTITY``  the input is broken for a named set of entities only. Four
#:             impossible shareholder registers out of 4,179 must stop the
#:             effective-ownership figure for those four and the components
#:             they contaminate, and must NOT stop it for the other 4,175.
#:             A gate that blanks the whole book over four rows is a gate
#:             that gets switched off.
SCOPE_GLOBAL = "GLOBAL"
SCOPE_ENTITY = "ENTITY"

#: The derived computations a check can block. Named constants rather than
#: free strings so a typo in a check definition fails loudly at import
#: instead of silently blocking nothing.
EFFECTIVE_OWNERSHIP = "EFFECTIVE_OWNERSHIP"
UBO = "UBO"
CONTROL_CLOSURE = "CONTROL_CLOSURE"
CONNECTED_GROUPS = "CONNECTED_GROUPS"
OWNERSHIP_CHAINS = "OWNERSHIP_CHAINS"
DEBTRANK = "DEBTRANK"
CENTRALITY = "CENTRALITY"
COMMUNITIES = "COMMUNITIES"
SIMILARITY = "SIMILARITY"
NETWORK_RISK_SCORE = "NETWORK_RISK_SCORE"

COMPUTATIONS: tuple[str, ...] = (
    EFFECTIVE_OWNERSHIP, UBO, CONTROL_CLOSURE, CONNECTED_GROUPS,
    OWNERSHIP_CHAINS, DEBTRANK, CENTRALITY, COMMUNITIES, SIMILARITY,
    NETWORK_RISK_SCORE,
)

#: What depends on what. NRS depends on DebtRank and centrality, so a REJECT
#: reaching either of those must reach the score too - a composite that
#: survives the failure of its own inputs is worse than no composite.
DEPENDS_ON: dict[str, tuple[str, ...]] = {
    NETWORK_RISK_SCORE: (DEBTRANK, CENTRALITY),
    UBO: (EFFECTIVE_OWNERSHIP,),
    CONNECTED_GROUPS: (CONTROL_CLOSURE,),
}

#: Tolerances. Published because a threshold nobody can see is a threshold
#: nobody can challenge.
REGISTER_FLAG_PCT = 100.5
REGISTER_REJECT_PCT = 110.0
ORPHAN_FLAG_SHARE = 0.02
ORPHAN_REJECT_SHARE = 0.10
STALE_EVIDENCE_DAYS = 1_095
STALE_FLAG_SHARE = 0.35
LOW_CONFIDENCE_FLOOR = 0.60
LOW_CONFIDENCE_FLAG_SHARE = 0.25
SELF_LOOP_REJECT = 1
NEGATIVE_REJECT = 1
DUPLICATE_FLAG_SHARE = 0.01
FUTURE_DATED_REJECT = 1


@dataclass(frozen=True)
class CheckResult:
    """One check, its verdict, and what it stops."""

    check_id: str
    name: str
    status: str
    observed: str
    threshold: str
    blocks: tuple[str, ...]
    examples: tuple[str, ...] = ()
    scope: str = SCOPE_GLOBAL
    affected: frozenset[str] = frozenset()

    def to_dict(self) -> dict[str, Any]:
        return {
            "check_id": self.check_id,
            "check": self.name,
            "status": self.status,
            "observed": self.observed,
            "threshold": self.threshold,
            "blocks": list(self.blocks) if self.status == REJECT else [],
            "would_block": list(self.blocks),
            "scope": self.scope,
            "affected_entities": len(self.affected),
            "examples": list(self.examples[:5]),
            "quality_version": QUALITY_VERSION,
        }


@dataclass
class QualityReport:
    """Every check for one as-of date, and the resulting block set."""

    as_of: str
    results: list[CheckResult] = field(default_factory=list)

    @property
    def status(self) -> str:
        if any(r.status == REJECT for r in self.results):
            return REJECT
        if any(r.status == FLAG for r in self.results):
            return FLAG
        return PASS

    def blocked(self, entity: str | None = None) -> set[str]:
        """The computations that must not run, closed over dependencies.

        With no `entity` this answers for a POPULATION-LEVEL computation and
        counts only global rejects. Pass a borrower to add the rejects scoped
        to it.
        """
        direct = {
            computation
            for result in self.results if result.status == REJECT
            and (result.scope == SCOPE_GLOBAL
                 or (entity is not None and entity in result.affected))
            for computation in result.blocks
        }
        # Close over DEPENDS_ON. Iterate to a fixed point rather than once:
        # a two-step chain (register REJECT -> effective ownership -> UBO)
        # would otherwise leave the far end computing on blocked input.
        changed = True
        while changed:
            changed = False
            for consumer, inputs in DEPENDS_ON.items():
                if consumer in direct:
                    continue
                if any(name in direct for name in inputs):
                    direct.add(consumer)
                    changed = True
        return direct

    def is_blocked(self, computation: str, entity: str | None = None) -> bool:
        return computation in self.blocked(entity)

    def reasons(self, computation: str,
                entity: str | None = None) -> list[str]:
        return sorted(
            f"{r.check_id} {r.name}: {r.observed}"
            for r in self.results
            if r.status == REJECT and computation in r.blocks
            and (r.scope == SCOPE_GLOBAL
                 or (entity is not None and entity in r.affected)))

    def affected_by(self, computation: str) -> set[str]:
        """Entities whose `computation` is blocked by an entity-scoped reject."""
        found: set[str] = set()
        for result in self.results:
            if (result.status == REJECT and result.scope == SCOPE_ENTITY
                    and computation in result.blocks):
                found |= set(result.affected)
        return found

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of,
            "overall_status": self.status,
            "checks_run": len(self.results),
            "passed": sum(1 for r in self.results if r.status == PASS),
            "flagged": sum(1 for r in self.results if r.status == FLAG),
            "rejected": sum(1 for r in self.results if r.status == REJECT),
            "blocked_computations": sorted(self.blocked()),
            "entity_scoped_blocks": {
                computation: len(self.affected_by(computation))
                for computation in COMPUTATIONS
                if self.affected_by(computation)},
            "checks": [r.to_dict() for r in self.results],
            "quality_version": QUALITY_VERSION,
        }


# ------------------------------------------------------------- the checks
#
# Each check takes the as-of graph frames and returns one CheckResult. They
# are written as separate functions rather than one long routine so that a
# check can be tested against a graph built to fail exactly it.


def _share(count: int, total: int) -> float:
    return count / total if total else 0.0


def _pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def _union_find(edges: list[tuple[str, str]],
                members: list[str]) -> dict[str, str]:
    """Weakly connected components over `members`, as node -> root."""
    parent = {name: name for name in members}

    def find(name: str) -> str:
        root = name
        while parent[root] != root:
            root = parent[root]
        while parent[name] != root:
            parent[name], name = root, parent[name]
        return root

    for left, right in edges:
        if left in parent and right in parent:
            a, b = find(left), find(right)
            if a != b:
                parent[max(a, b)] = min(a, b)
    return {name: find(name) for name in members}


def _ownership_contamination(own: pd.DataFrame,
                             offenders: set[str]) -> frozenset[str]:
    """Every node in a weakly connected component holding an offender.

    Effective ownership is solved per component, so one impossible register
    makes every stake in ITS component unreliable - and only that component.
    Reporting just the offending company would understate the damage;
    reporting the whole book would overstate it.
    """
    if not offenders:
        return frozenset()
    nodes = sorted(set(own["from_node"].astype(str))
                   | set(own["to_node"].astype(str)))
    roots = _union_find(
        list(zip(own["from_node"].astype(str), own["to_node"].astype(str),
                 strict=True)),
        nodes)
    bad_roots = {roots[name] for name in offenders if name in roots}
    return frozenset(name for name, root in roots.items()
                     if root in bad_roots)


def check_register_totals(frames: dict[str, pd.DataFrame]) -> CheckResult:
    """GQ-01. A shareholder register cannot claim more than 100% of a company.

    This is the check the effective-ownership solve cannot do for itself: the
    spectral radius bounds convergence, not the column sums, so an impossible
    register returns a perfectly well-conditioned wrong answer.
    """
    own = frames["ownership"]
    own = own[own["edge_type"] == graphdata.OWNS]
    if own.empty:
        return CheckResult("GQ-01", "Shareholder register totals", PASS,
                           "no ownership edges as at date",
                           f"<= {REGISTER_FLAG_PCT}%",
                           (EFFECTIVE_OWNERSHIP, OWNERSHIP_CHAINS))
    totals = own.groupby("to_node")["ownership_pct"].sum()
    over_flag = totals[totals > REGISTER_FLAG_PCT]
    over_reject = totals[totals > REGISTER_REJECT_PCT]
    if len(over_reject):
        status = REJECT
    elif len(over_flag):
        status = FLAG
    else:
        status = PASS
    worst = totals.max() if len(totals) else 0.0
    affected = _ownership_contamination(
        own, {str(k) for k in over_reject.index}) if len(over_reject) else \
        frozenset()
    return CheckResult(
        "GQ-01", "Shareholder register totals", status,
        f"{len(over_flag)} of {len(totals)} registers above "
        f"{REGISTER_FLAG_PCT}%, worst {worst:.2f}%; "
        f"{len(affected)} entities in contaminated components",
        f"FLAG > {REGISTER_FLAG_PCT}%, REJECT > {REGISTER_REJECT_PCT}%",
        (EFFECTIVE_OWNERSHIP, OWNERSHIP_CHAINS),
        tuple(str(k) for k in over_flag.sort_values(ascending=False).index[:5]),
        scope=SCOPE_ENTITY, affected=affected)


def check_negative_ownership(frames: dict[str, pd.DataFrame]) -> CheckResult:
    """GQ-02. Negative or above-100% single stakes are not data, they are errors."""
    own = frames["ownership"]
    own = own[own["edge_type"] == graphdata.OWNS]
    bad = own[(own["ownership_pct"] < 0) | (own["ownership_pct"] > 100.0)]
    status = REJECT if len(bad) >= NEGATIVE_REJECT else PASS
    affected = _ownership_contamination(
        own, set(bad["to_node"].astype(str)) | set(bad["from_node"].astype(str))
    ) if len(bad) else frozenset()
    return CheckResult(
        "GQ-02", "Single stake within [0, 100]", status,
        f"{len(bad)} of {len(own)} stakes outside range; "
        f"{len(affected)} entities in contaminated components",
        "REJECT on any", (EFFECTIVE_OWNERSHIP, UBO, OWNERSHIP_CHAINS),
        tuple(str(e) for e in bad["edge_id"].head(5)),
        scope=SCOPE_ENTITY, affected=affected)


def check_self_ownership(frames: dict[str, pd.DataFrame]) -> CheckResult:
    """GQ-03. A company owning itself makes (I - A) singular."""
    own = frames["ownership"]
    loops = own[own["from_node"] == own["to_node"]]
    status = REJECT if len(loops) >= SELF_LOOP_REJECT else PASS
    return CheckResult(
        "GQ-03", "No self-ownership edge", status,
        f"{len(loops)} self-referencing ownership edges",
        "REJECT on any", (EFFECTIVE_OWNERSHIP, CONTROL_CLOSURE),
        tuple(str(e) for e in loops["edge_id"].head(5)))


def check_dangling_endpoints(frames: dict[str, pd.DataFrame]) -> CheckResult:
    """GQ-04. Every edge endpoint must be a declared node.

    An edge to a node that does not exist is the classic silent join failure:
    it disappears from a node-first traversal and survives an edge-first one,
    so the same graph gives two different answers depending on the query.
    """
    nodes = set(frames["nodes"]["node_id"].astype(str))
    dangling: list[str] = []
    total = 0
    for key in ("ownership", "supply", "exposure", "guarantees"):
        frame = frames.get(key)
        if frame is None or frame.empty:
            continue
        total += len(frame)
        missing = frame[~frame["from_node"].astype(str).isin(nodes)
                        | ~frame["to_node"].astype(str).isin(nodes)]
        dangling.extend(str(e) for e in missing["edge_id"].head(5))
        dangling = dangling[:5]
        if len(missing):
            return CheckResult(
                "GQ-04", "Edge endpoints resolve to nodes", REJECT,
                f"{len(missing)} edges in {key} reference unknown nodes",
                "REJECT on any", tuple(COMPUTATIONS), tuple(dangling))
    return CheckResult(
        "GQ-04", "Edge endpoints resolve to nodes", PASS,
        f"0 of {total} edges reference unknown nodes",
        "REJECT on any", tuple(COMPUTATIONS))


def check_orphan_borrowers(frames: dict[str, pd.DataFrame]) -> CheckResult:
    """GQ-05. Borrowers with no graph edge at all.

    A FLAG, not a REJECT: a genuinely standalone borrower is a real thing.
    But a sudden jump in the orphan share means an upstream join broke, and
    the network measures for those borrowers become structurally zero rather
    than unknown - which reads as "no network risk" instead of "no data".
    """
    borrowers = set(frames["borrowers"])
    connected: set[str] = set()
    for key in ("ownership", "supply", "exposure", "guarantees"):
        frame = frames.get(key)
        if frame is None or frame.empty:
            continue
        connected |= set(frame["from_node"].astype(str))
        connected |= set(frame["to_node"].astype(str))
    orphans = sorted(borrowers - connected)
    share = _share(len(orphans), len(borrowers))
    if share > ORPHAN_REJECT_SHARE:
        status = REJECT
    elif share > ORPHAN_FLAG_SHARE:
        status = FLAG
    else:
        status = PASS
    return CheckResult(
        "GQ-05", "Borrowers present in the graph", status,
        f"{len(orphans)} of {len(borrowers)} borrowers have no edge "
        f"({_pct(share)})",
        f"FLAG > {_pct(ORPHAN_FLAG_SHARE)}, REJECT > {_pct(ORPHAN_REJECT_SHARE)}",
        (CENTRALITY, COMMUNITIES, NETWORK_RISK_SCORE),
        tuple(orphans[:5]))


def check_temporal_validity(frames: dict[str, pd.DataFrame]) -> CheckResult:
    """GQ-06. valid_to must not precede valid_from."""
    bad: list[str] = []
    total = 0
    for key in ("ownership", "supply", "exposure", "guarantees"):
        frame = frames.get(key)
        if frame is None or frame.empty or "valid_to" not in frame:
            continue
        total += len(frame)
        closed = frame[frame["valid_to"].astype(str) != ""]
        if closed.empty:
            continue
        inverted = closed[pd.to_datetime(closed["valid_to"])
                          < pd.to_datetime(closed["valid_from"])]
        bad.extend(str(e) for e in inverted["edge_id"].head(5))
    status = REJECT if bad else PASS
    return CheckResult(
        "GQ-06", "Validity interval ordering", status,
        f"{len(bad)} of {total} edges close before they open",
        "REJECT on any", tuple(COMPUTATIONS), tuple(bad[:5]))


def check_future_knowledge(frames: dict[str, pd.DataFrame],
                           as_of_date: str) -> CheckResult:
    """GQ-07. Nothing recorded after the as-of date may be in the view.

    This checks the as-of filter itself rather than the data. If it ever
    fails, an answer has been produced from knowledge nobody had on the date
    it claims to describe, which is the single most damaging thing a
    bitemporal system can do quietly.
    """
    late: list[str] = []
    total = 0
    stamp = pd.Timestamp(as_of_date)
    for key in ("ownership", "supply", "exposure", "guarantees"):
        frame = frames.get(key)
        if frame is None or frame.empty or "recorded_at" not in frame:
            continue
        total += len(frame)
        after = frame[pd.to_datetime(frame["recorded_at"]) > stamp]
        late.extend(str(e) for e in after["edge_id"].head(5))
    status = REJECT if len(late) >= FUTURE_DATED_REJECT else PASS
    return CheckResult(
        "GQ-07", "No knowledge from after the as-of date", status,
        f"{len(late)} of {total} edges recorded after {as_of_date}",
        "REJECT on any", tuple(COMPUTATIONS), tuple(late[:5]))


def check_duplicate_edges(frames: dict[str, pd.DataFrame]) -> CheckResult:
    """GQ-08. The same assertion twice double-counts the stake behind it."""
    own = frames["ownership"]
    if own.empty:
        return CheckResult("GQ-08", "No duplicate assertions", PASS,
                           "no edges as at date", "FLAG > 1%",
                           (EFFECTIVE_OWNERSHIP,))
    keys = own[["edge_type", "from_node", "to_node"]].astype(str)
    duplicated = int(keys.duplicated().sum())
    share = _share(duplicated, len(own))
    status = FLAG if share > DUPLICATE_FLAG_SHARE else PASS
    return CheckResult(
        "GQ-08", "No duplicate assertions", status,
        f"{duplicated} of {len(own)} ownership edges duplicate an existing "
        f"(type, from, to) ({_pct(share)})",
        f"FLAG > {_pct(DUPLICATE_FLAG_SHARE)}", (EFFECTIVE_OWNERSHIP,))


def check_missing_confidence(frames: dict[str, pd.DataFrame]) -> CheckResult:
    """GQ-09. An assertion with no confidence cannot be weighed."""
    missing = 0
    total = 0
    for key in ("ownership", "supply", "exposure", "guarantees"):
        frame = frames.get(key)
        if frame is None or frame.empty or "confidence" not in frame:
            continue
        total += len(frame)
        values = pd.to_numeric(frame["confidence"], errors="coerce")
        missing += int(values.isna().sum() + (values < 0).sum()
                       + (values > 1).sum())
    status = REJECT if missing else PASS
    return CheckResult(
        "GQ-09", "Confidence present and in [0, 1]", status,
        f"{missing} of {total} edges without a usable confidence",
        "REJECT on any", (EFFECTIVE_OWNERSHIP, UBO, CONTROL_CLOSURE))


def check_low_confidence_share(frames: dict[str, pd.DataFrame]) -> CheckResult:
    """GQ-10. How much of the graph rests on weak evidence.

    A FLAG: weak evidence is still evidence, and a book with many relationship
    manager notes is a real book. It becomes a reviewer's problem, not the
    engine's.
    """
    weak = 0
    total = 0
    for key in ("ownership", "supply", "exposure", "guarantees"):
        frame = frames.get(key)
        if frame is None or frame.empty or "confidence" not in frame:
            continue
        values = pd.to_numeric(frame["confidence"], errors="coerce").fillna(0)
        total += len(values)
        weak += int((values < LOW_CONFIDENCE_FLOOR).sum())
    share = _share(weak, total)
    status = FLAG if share > LOW_CONFIDENCE_FLAG_SHARE else PASS
    return CheckResult(
        "GQ-10", "Share of low-confidence evidence", status,
        f"{weak} of {total} edges below {LOW_CONFIDENCE_FLOOR} ({_pct(share)})",
        f"FLAG > {_pct(LOW_CONFIDENCE_FLAG_SHARE)}",
        (EFFECTIVE_OWNERSHIP, UBO))


def check_stale_evidence(frames: dict[str, pd.DataFrame],
                         as_of_date: str) -> CheckResult:
    """GQ-11. Evidence last recorded a long time before the as-of date."""
    stale = 0
    total = 0
    cutoff = pd.Timestamp(as_of_date) - pd.Timedelta(days=STALE_EVIDENCE_DAYS)
    for key in ("ownership", "supply", "exposure", "guarantees"):
        frame = frames.get(key)
        if frame is None or frame.empty or "recorded_at" not in frame:
            continue
        recorded = pd.to_datetime(frame["recorded_at"], errors="coerce")
        total += len(recorded)
        stale += int((recorded < cutoff).sum())
    share = _share(stale, total)
    status = FLAG if share > STALE_FLAG_SHARE else PASS
    return CheckResult(
        "GQ-11", "Evidence recency", status,
        f"{stale} of {total} edges last recorded more than "
        f"{STALE_EVIDENCE_DAYS} days before {as_of_date} ({_pct(share)})",
        f"FLAG > {_pct(STALE_FLAG_SHARE)}", (EFFECTIVE_OWNERSHIP, UBO))


def check_exposure_sign(frames: dict[str, pd.DataFrame]) -> CheckResult:
    """GQ-12. Negative exposure inverts the direction of a DebtRank shock."""
    exposure = frames.get("exposure")
    if exposure is None or exposure.empty or "amount" not in exposure:
        return CheckResult("GQ-12", "Exposure amounts non-negative", PASS,
                           "no exposure edges as at date", "REJECT on any",
                           (DEBTRANK, NETWORK_RISK_SCORE))
    amounts = pd.to_numeric(exposure["amount"], errors="coerce")
    bad = int((amounts < 0).sum() + amounts.isna().sum())
    status = REJECT if bad else PASS
    return CheckResult(
        "GQ-12", "Exposure amounts non-negative", status,
        f"{bad} of {len(amounts)} exposure amounts negative or missing",
        "REJECT on any", (DEBTRANK, NETWORK_RISK_SCORE))


def check_guarantee_coverage(frames: dict[str, pd.DataFrame]) -> CheckResult:
    """GQ-13. A guarantee must name both a guarantor and a beneficiary."""
    guarantees = frames.get("guarantees")
    if guarantees is None or guarantees.empty:
        return CheckResult("GQ-13", "Guarantees fully specified", PASS,
                           "no guarantee edges as at date", "REJECT on any",
                           (DEBTRANK, CONNECTED_GROUPS))
    blank = guarantees[(guarantees["from_node"].astype(str).str.len() == 0)
                       | (guarantees["to_node"].astype(str).str.len() == 0)]
    status = REJECT if len(blank) else PASS
    return CheckResult(
        "GQ-13", "Guarantees fully specified", status,
        f"{len(blank)} of {len(guarantees)} guarantee edges missing an endpoint",
        "REJECT on any", (DEBTRANK, CONNECTED_GROUPS),
        tuple(str(e) for e in blank["edge_id"].head(5)))


def check_component_concentration(frames: dict[str, pd.DataFrame]) -> CheckResult:
    """GQ-14. One component swallowing the population.

    A FLAG on the analytics rather than the data: when a single weakly
    connected component holds most of the book, betweenness and community
    detection stop discriminating - everything is central, everything is one
    community - and the resulting ranking says nothing.
    """
    edges: list[tuple[str, str]] = []
    for key in ("ownership", "supply", "exposure", "guarantees"):
        frame = frames.get(key)
        if frame is None or frame.empty:
            continue
        edges.extend(zip(frame["from_node"].astype(str),
                         frame["to_node"].astype(str), strict=True))
    borrowers = sorted(frames["borrowers"])
    if not borrowers:
        return CheckResult("GQ-14", "No single dominant component", PASS,
                           "no borrowers", "FLAG > 60% of population",
                           (CENTRALITY, COMMUNITIES))

    roots = _union_find(edges, borrowers)
    sizes: dict[str, int] = {}
    for root in roots.values():
        sizes[root] = sizes.get(root, 0) + 1
    largest = max(sizes.values()) if sizes else 0
    share = _share(largest, len(borrowers))
    status = FLAG if share > 0.60 else PASS
    return CheckResult(
        "GQ-14", "No single dominant component", status,
        f"largest weakly connected component holds {largest} of "
        f"{len(borrowers)} borrowers ({_pct(share)})",
        "FLAG > 60.00% of population", (CENTRALITY, COMMUNITIES))


def check_isolated_group_members(frames: dict[str, pd.DataFrame]) -> CheckResult:
    """GQ-15. A declared group whose members share no edge with each other.

    Either the group is wrong or the edges behind it are missing. Both are
    reviewer findings; neither invalidates the mathematics, so this flags.
    """
    master = frames.get("master")
    if master is None or master.empty or "group_id" not in master:
        return CheckResult("GQ-15", "Declared groups have internal edges",
                           PASS, "no declared groups as at date",
                           "FLAG on any", (CONNECTED_GROUPS,))
    declared = master[master["group_id"].astype(str).str.len() > 0]
    if declared.empty:
        return CheckResult("GQ-15", "Declared groups have internal edges",
                           PASS, "no declared groups as at date",
                           "FLAG on any", (CONNECTED_GROUPS,))
    pairs: set[tuple[str, str]] = set()
    for key in ("ownership", "supply", "exposure", "guarantees"):
        frame = frames.get(key)
        if frame is None or frame.empty:
            continue
        pairs |= set(zip(frame["from_node"].astype(str),
                         frame["to_node"].astype(str), strict=True))
    lonely: list[str] = []
    for group_id, block in declared.groupby("group_id"):
        members = set(block["borrower_id"].astype(str))
        if len(members) < 2:
            continue
        if not any(a in members and b in members for a, b in pairs):
            lonely.append(str(group_id))
    status = FLAG if lonely else PASS
    return CheckResult(
        "GQ-15", "Declared groups have internal edges", status,
        f"{len(lonely)} declared groups have no edge between any two members",
        "FLAG on any", (CONNECTED_GROUPS,), tuple(sorted(lonely)[:5]))


CHECKS: tuple[Callable[..., CheckResult], ...] = (
    check_register_totals,
    check_negative_ownership,
    check_self_ownership,
    check_dangling_endpoints,
    check_orphan_borrowers,
    check_temporal_validity,
    check_duplicate_edges,
    check_missing_confidence,
    check_low_confidence_share,
    check_exposure_sign,
    check_guarantee_coverage,
    check_component_concentration,
    check_isolated_group_members,
)

#: Checks that need the as-of date as well as the frames.
DATED_CHECKS: tuple[Callable[..., CheckResult], ...] = (
    check_future_knowledge,
    check_stale_evidence,
)


def as_of_frames(universe_frames: dict[str, pd.DataFrame],
                 as_of_date: str) -> dict[str, Any]:
    """The graph frames filtered to one date, in the shape the checks want."""
    nodes = universe_frames["corporate_graph_nodes"]
    master = universe_frames.get("corporate_customer_master")
    borrowers: set[str] = set()
    if master is not None and not master.empty:
        borrowers = set(master["borrower_id"].astype(str))
    return {
        "nodes": nodes,
        "borrowers": borrowers,
        "master": master,
        "ownership": graphdata.as_of(
            universe_frames["corporate_ownership_edges"], as_of_date),
        "supply": graphdata.as_of(
            universe_frames["corporate_supply_chain"], as_of_date),
        "exposure": graphdata.as_of(
            universe_frames["corporate_exposure_network"], as_of_date),
        "guarantees": graphdata.as_of(
            universe_frames["corporate_guarantees"], as_of_date),
    }


def run(universe_frames: dict[str, pd.DataFrame],
        as_of_date: str) -> QualityReport:
    """Every check, for one as-of date. Phase 2.17.

    A check that raises is reported as a REJECT naming its own failure rather
    than being allowed to propagate. A quality gate that crashes has told the
    caller nothing, and the caller will be tempted to skip it.
    """
    frames = as_of_frames(universe_frames, as_of_date)
    report = QualityReport(as_of=as_of_date)
    for check in CHECKS:
        try:
            report.results.append(check(frames))
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("graph quality check failed: %s", check.__name__)
            report.results.append(CheckResult(
                check_id=check.__name__, name=check.__name__, status=REJECT,
                observed=f"check raised {type(exc).__name__}: {exc}",
                threshold="check must complete", blocks=tuple(COMPUTATIONS)))
    for check in DATED_CHECKS:
        try:
            report.results.append(check(frames, as_of_date))
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("graph quality check failed: %s", check.__name__)
            report.results.append(CheckResult(
                check_id=check.__name__, name=check.__name__, status=REJECT,
                observed=f"check raised {type(exc).__name__}: {exc}",
                threshold="check must complete", blocks=tuple(COMPUTATIONS)))
    report.results.sort(key=lambda r: r.check_id)
    return report


DATA_QUALITY_BLOCKED = "DATA_QUALITY_BLOCKED"
NOT_AVAILABLE = "NOT_AVAILABLE"
NOT_APPLICABLE = "NOT_APPLICABLE"


def blocked_value(report: QualityReport, computation: str,
                  entity: str | None = None) -> dict[str, Any]:
    """What a Borrower 360 field says instead of a number when blocked."""
    return {
        "status": DATA_QUALITY_BLOCKED,
        "value": None,
        "computation": computation,
        "entity": entity,
        "reasons": report.reasons(computation, entity),
        "as_of": report.as_of,
        "quality_version": QUALITY_VERSION,
    }

