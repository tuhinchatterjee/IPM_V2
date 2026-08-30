"""The observed relationship graph. B13, B15, B16, B17.

OBSERVED edges only - what a source system asserts. Effective ownership,
control closure, connected groups, DebtRank and every other computed quantity
is DERIVED and lives elsewhere, because the whole value of the distinction is
that a user can be shown the assertion and the inference separately and see
which one they disagree with.

What is in here
---------------
* Nodes of every type B15 names, including reified ``Guarantee`` and
  ``Facility`` nodes so a guarantee covering three facilities is one fact
  rather than three edges that have to be kept consistent.
* Edges of every observed type B13 names, each carrying ``valid_from``,
  ``valid_to``, ``recorded_at``, ``source`` and ``confidence``.
* ``ownership_pct`` and ``voting_pct`` as SEPARATE columns (B17). They differ
  on purpose: dual-class shares, shareholder agreements and golden shares all
  make voting diverge from economics, and a graph that carries one number for
  both cannot answer an ownership question and a control question differently
  - which is the single most common way a group-structure analysis goes wrong.

Structure that makes the mathematics non-trivial
------------------------------------------------
Deliberately generated, because a graph of disjoint two-node stars would let
every ownership algorithm return the right answer for the wrong reason:

* multi-level pyramids, so effective ownership needs the full chain;
* cross-holdings, so ``(I - A)`` is genuinely worth inverting;
* minority stakes that sum to less than 100%, and a few that sum to more,
  so the data-quality checks have something real to find;
* separate voting and economic percentages on the same edge;
* several natural persons holding through the same holding company, so the
  ultimate-beneficial-owner search has to branch.

Bitemporality
-------------
Every edge is stamped with when it became true (``valid_from``), when it
stopped (``valid_to``, null while current) and when the bank learned it
(``recorded_at``). B16's as-of predicate needs all three, and the third is
the one usually missing: a shareholding recorded in 2026 that was true from
2023 must NOT appear in a 2024 as-of view, or the graph gives a demonstration
foresight nobody had.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

from backend.corporate import ORIGIN
from backend.corporate.universe import (
    QUARTERS,
    SECTORS,
    _choose,
    _round,
    quarter_end,
)

logger = logging.getLogger(__name__)

GRAPH_DATA_VERSION = "1.0.0"

# ------------------------------------------------------------- node types

CORPORATE = "Corporate"
NATURAL_PERSON = "NaturalPerson"
ADDRESS = "Address"
DIRECTOR = "Director"
FACILITY = "Facility"
GUARANTEE = "Guarantee"
FINANCIAL_STATEMENT = "FinancialStatement"
SECTOR = "Sector"
FUNDING_SOURCE = "FundingSource"
CONNECTED_GROUP = "ConnectedGroup"
REGISTRY_RECORD = "RegistryRecord"
ASSESSING_INSTITUTION = "AssessingInstitution"

NODE_TYPES: tuple[str, ...] = (
    CORPORATE, NATURAL_PERSON, ADDRESS, DIRECTOR, FACILITY, GUARANTEE,
    FINANCIAL_STATEMENT, SECTOR, FUNDING_SOURCE, CONNECTED_GROUP,
    REGISTRY_RECORD, ASSESSING_INSTITUTION,
)

# ------------------------------------------------------- observed edge types

OWNS = "OWNS"
CONTROLS = "CONTROLS"
DIRECTOR_OF = "DIRECTOR_OF"
PROVIDES = "PROVIDES"
COVERS = "COVERS"
HOLDS = "HOLDS"
LENT_TO = "LENT_TO"
SUPPLIES_TO = "SUPPLIES_TO"
EXPOSED_TO = "EXPOSED_TO"
FUNDED_BY = "FUNDED_BY"
IN_SECTOR = "IN_SECTOR"
REGISTERED_AT = "REGISTERED_AT"

OBSERVED_EDGE_TYPES: tuple[str, ...] = (
    OWNS, CONTROLS, DIRECTOR_OF, PROVIDES, COVERS, HOLDS, LENT_TO,
    SUPPLIES_TO, EXPOSED_TO, FUNDED_BY, IN_SECTOR, REGISTERED_AT,
)

#: Where an assertion came from, and how much it is worth. Confidence is a
#: property of the SOURCE, not a number invented per edge: a registry filing
#: is more reliable than a relationship manager's note whatever it says, and
#: attaching the confidence to the source is what makes that auditable.
SOURCES: tuple[tuple[str, float, float], ...] = (
    # source, confidence, share of assertions
    ("Commercial Registry filing", 0.97, 0.42),
    ("Audited group structure note", 0.92, 0.19),
    ("Customer declaration (KYC)", 0.84, 0.21),
    ("Credit application form", 0.72, 0.10),
    ("Relationship manager note", 0.58, 0.08),
)

WINDOW_START = "2018-01-01"


def _source_draw(rng: np.random.Generator, size: int) -> tuple[np.ndarray,
                                                               np.ndarray]:
    weights = np.array([s[2] for s in SOURCES])
    picks = rng.choice(len(SOURCES), size=size, p=weights / weights.sum())
    names = np.array([SOURCES[i][0] for i in picks])
    confidence = np.array([SOURCES[i][1] for i in picks])
    return names, confidence


def _dates(rng: np.random.Generator, size: int, *,
           closes: float = 0.10) -> dict[str, np.ndarray]:
    """valid_from, valid_to and recorded_at for a batch of assertions.

    `recorded_at` is drawn AFTER `valid_from` with a real lag, because that
    lag is the whole reason B16's third clause exists. A registry filing is
    typically learned within weeks; a relationship manager's note about a
    shareholding that changed two years ago is learned two years late, and an
    as-of view that ignores the difference reports knowledge nobody had.
    """
    start = pd.Timestamp(WINDOW_START)
    valid_from = start + pd.to_timedelta(
        rng.integers(0, 2_800, size), unit="D")
    lag = np.clip(rng.gamma(1.7, 95.0, size), 3, 1_500).astype(int)
    recorded_at = valid_from + pd.to_timedelta(lag, unit="D")

    ends = rng.random(size) < closes
    duration = np.clip(rng.gamma(2.4, 340.0, size), 120, 2_600).astype(int)
    valid_to = np.where(
        ends, (valid_from + pd.to_timedelta(duration, unit="D")).strftime(
            "%Y-%m-%d"), "")
    return {
        "valid_from": valid_from.strftime("%Y-%m-%d").to_numpy(),
        "valid_to": valid_to,
        "recorded_at": recorded_at.strftime("%Y-%m-%d").to_numpy(),
    }


def as_of(edges: pd.DataFrame, when: str) -> pd.DataFrame:
    """B16's predicate, in one place.

        valid_from <= asOf
        AND (valid_to IS NULL OR valid_to > asOf)
        AND recorded_at <= asOf

    Written once and imported everywhere rather than re-expressed per query.
    Two of the three clauses are easy to remember and the third is easy to
    forget, and a graph filtered on two of them leaks the future silently -
    it returns MORE edges, never an error.
    """
    stamp = str(when)
    if " " in stamp and stamp.startswith("Q"):
        stamp = quarter_end(stamp)
    open_ended = edges["valid_to"].isna() | (edges["valid_to"] == "")
    return edges[
        (edges["valid_from"] <= stamp)
        & (open_ended | (edges["valid_to"] > stamp))
        & (edges["recorded_at"] <= stamp)
    ]


# ------------------------------------------------------------- the structure

#: How many group structures the universe carries. Most borrowers are
#: standalone; a graph where everything is in a group has no negative cases,
#: and "is this borrower part of a group" stops being a question.
GROUP_COUNT = 430
#: Groups with a holding company between the top and its operating members.
#: Pyramids are where effective ownership stops equalling direct ownership.
PYRAMID_SHARE = 0.38
#: Groups where one member holds a stake in another. Cross-holdings are what
#: make (I - A) worth inverting rather than a chain worth multiplying.
CROSS_HOLDING_SHARE = 0.12

PERSON_FIRST: tuple[str, ...] = (
    "Abdullah", "Mohammed", "Fahad", "Khalid", "Saud", "Turki", "Nasser",
    "Bandar", "Majed", "Sultan", "Noura", "Hessa", "Latifa", "Amal",
    "Reem", "Maha", "Sara", "Dana", "Yousef", "Ibrahim", "Omar", "Ali",
)
PERSON_FAMILY: tuple[str, ...] = (
    "Al Otaibi", "Al Dossari", "Al Harbi", "Al Qahtani", "Al Zahrani",
    "Al Ghamdi", "Al Shehri", "Al Mutairi", "Al Anzi", "Al Subaie",
    "Al Balawi", "Al Juhani", "Al Shammari", "Al Rashid", "Al Amoudi",
)

FUNDING_SOURCES: tuple[str, ...] = (
    "Domestic syndicated market", "Local bilateral banks",
    "Export credit agency", "Development fund", "Sukuk issuance",
    "International bank facility", "Shareholder loan", "Retained earnings",
)

STREET_NAMES: tuple[str, ...] = (
    "King Fahd Road", "Olaya Street", "Prince Sultan Road", "Tahlia Street",
    "King Abdulaziz Road", "Al Madinah Road", "Corniche Road",
    "Industrial Area 2", "Prince Turki Street", "Al Khobar Business Park",
)


def _person_names(rng: np.random.Generator, size: int) -> np.ndarray:
    first = rng.choice(PERSON_FIRST, size)
    family = rng.choice(PERSON_FAMILY, size)
    return np.array([f"{f} {s}" for f, s in zip(first, family, strict=True)])


def build_graph(entities: pd.DataFrame,
                rng: np.random.Generator) -> dict[str, pd.DataFrame]:
    """Nodes and observed edges for the whole universe.

    Returns the graph frames keyed by dataset name, so a caller can write them
    or assert on them without this module knowing anything about storage.
    """
    borrowers = entities["borrower_id"].to_numpy()
    n_borrowers = len(borrowers)

    nodes: list[dict[str, Any]] = []

    # ---- fixed reference nodes -------------------------------------------
    for sector in SECTORS:
        nodes.append({"node_id": f"SECT-{sector.name.replace(' ', '-')}",
                      "node_type": SECTOR, "label": sector.name,
                      "detail": "Governed sector classification"})
    for i, source in enumerate(FUNDING_SOURCES):
        nodes.append({"node_id": f"FUND-{i + 1:02d}",
                      "node_type": FUNDING_SOURCE, "label": source,
                      "detail": "Funding channel"})
    nodes.append({"node_id": "BANK-001", "node_type": ASSESSING_INSTITUTION,
                  "label": "The assessing institution",
                  "detail": "The bank whose book this is"})

    # ---- addresses --------------------------------------------------------
    #
    # Fewer addresses than borrowers, on purpose. A shared registered address
    # is weak evidence of a relationship and strong evidence of a possible
    # duplicate, and both are things the module has to be able to find.
    address_count = 900
    address_ids = np.array([f"ADDR-{i + 1:05d}" for i in range(address_count)])
    address_city = rng.choice(entities["city"].unique(), address_count)
    for node_id, street, city in zip(
            address_ids, rng.choice(STREET_NAMES, address_count),
            address_city, strict=True):
        nodes.append({"node_id": node_id, "node_type": ADDRESS,
                      "label": f"{street}, {city}",
                      "detail": "Registered address"})

    # ---- corporate nodes for every borrower ------------------------------
    for row in entities.itertuples():
        nodes.append({
            "node_id": row.borrower_id, "node_type": CORPORATE,
            "label": row.legal_name,
            "detail": f"{row.segment} - {row.sector}"})
        nodes.append({
            "node_id": f"REG-{row.borrower_id}", "node_type": REGISTRY_RECORD,
            "label": row.cr_number,
            "detail": "Commercial registration record"})

    # ---- group structures -------------------------------------------------
    order = rng.permutation(n_borrowers)
    size_draw = np.clip(2 + rng.poisson(1.6, GROUP_COUNT), 2, 9)
    cursor = 0
    groups: list[dict[str, Any]] = []
    for g in range(GROUP_COUNT):
        size = int(size_draw[g])
        if cursor + size > n_borrowers:
            break
        members = order[cursor:cursor + size]
        cursor += size
        groups.append({"index": g, "members": members})

    holding_rows: list[dict[str, Any]] = []
    person_rows: list[dict[str, Any]] = []
    ownership: list[dict[str, Any]] = []

    for group in groups:
        g = group["index"]
        members = list(group["members"])
        top_id = f"HOLD-{g + 1:04d}"
        holding_rows.append({
            "node_id": top_id, "node_type": CORPORATE,
            "label": f"{entities['display_name'].iloc[members[0]]} Holding",
            "detail": "Group holding company (not a borrower)"})

        # A pyramid inserts an intermediate holding company, so a member's
        # effective ownership by the top is a product of two percentages.
        layers: list[tuple[str, list[int]]] = []
        if rng.random() < PYRAMID_SHARE and len(members) >= 3:
            split = max(1, len(members) // 2)
            middle_id = f"HOLD-{g + 1:04d}-M"
            holding_rows.append({
                "node_id": middle_id, "node_type": CORPORATE,
                "label": (f"{entities['display_name'].iloc[members[0]]} "
                          "Investments"),
                "detail": "Intermediate holding company (not a borrower)"})
            ownership.append({
                "from": top_id, "to": middle_id,
                "ownership": float(np.clip(rng.normal(0.82, 0.14), 0.34, 1.0)),
                "voting_bias": 0.0})
            layers.append((top_id, members[:split]))
            layers.append((middle_id, members[split:]))
        else:
            layers.append((top_id, members))

        for parent, children in layers:
            for child in children:
                # Economic stake. A minority stake below 50% is common and is
                # exactly the case where ownership and control diverge.
                pct = float(np.clip(rng.beta(4.2, 1.9), 0.05, 1.0))
                # Voting rights differ from economics for about one holding in
                # five - dual-class shares, a shareholders' agreement, or a
                # golden share. Kept as a separate figure, never derived from
                # the other (B17).
                bias = 0.0
                if rng.random() < 0.20:
                    bias = float(rng.uniform(0.08, 0.35)) * rng.choice([1, -1])
                ownership.append({
                    "from": parent, "to": borrowers[child],
                    "ownership": pct, "voting_bias": bias})

        # Cross-holding: a member holds a stake in a sibling.
        if len(members) >= 3 and rng.random() < CROSS_HOLDING_SHARE:
            a, b = rng.choice(len(members), 2, replace=False)
            ownership.append({
                "from": borrowers[members[a]], "to": borrowers[members[b]],
                "ownership": float(rng.uniform(0.04, 0.19)),
                "voting_bias": 0.0})

        # Natural persons at the top of the group.
        ubo_count = int(rng.integers(1, 5))
        names = _person_names(rng, ubo_count)
        shares = rng.dirichlet(np.ones(ubo_count) * 2.4)
        # The persons hold most, but not always all, of the holding company.
        held = float(np.clip(rng.normal(0.93, 0.09), 0.42, 1.0))
        for k, (name, share) in enumerate(zip(names, shares, strict=True)):
            person_id = f"PERS-{g + 1:04d}-{k + 1}"
            person_rows.append({
                "node_id": person_id, "node_type": NATURAL_PERSON,
                "label": name, "detail": "Ultimate shareholder"})
            # A founder's shares often vote more than they own, and a passive
            # family shareholder's often vote less. Restricting the voting
            # bias to corporate holdings would leave the person layer - where
            # control of a family group is actually decided - with voting
            # identical to economics, and every control question about the top
            # of a group would silently be answered with an economic one.
            person_bias = 0.0
            if rng.random() < 0.14:
                person_bias = float(rng.uniform(0.06, 0.30)) * (
                    1 if k == 0 else -1)
            ownership.append({
                "from": person_id, "to": top_id,
                "ownership": float(share * held), "voting_bias": person_bias})

    grouped_members = {int(m) for group in groups for m in group["members"]}

    # ---- standalone borrowers get owners too ------------------------------
    for position in range(n_borrowers):
        if position in grouped_members:
            continue
        count = int(rng.integers(1, 4))
        shares = rng.dirichlet(np.ones(count) * 3.0)
        held = float(np.clip(rng.normal(0.95, 0.08), 0.45, 1.0))
        names = _person_names(rng, count)
        for k, (name, share) in enumerate(zip(names, shares, strict=True)):
            person_id = f"PERS-S{position:05d}-{k + 1}"
            person_rows.append({
                "node_id": person_id, "node_type": NATURAL_PERSON,
                "label": name, "detail": "Ultimate shareholder"})
            person_bias = 0.0
            if rng.random() < 0.14:
                person_bias = float(rng.uniform(0.06, 0.30)) * (
                    1 if k == 0 else -1)
            ownership.append({
                "from": person_id, "to": borrowers[position],
                "ownership": float(share * held), "voting_bias": person_bias})

    nodes.extend(holding_rows)
    nodes.extend(person_rows)

    # ---- ownership edges --------------------------------------------------
    own = pd.DataFrame(ownership)
    sources, confidence = _source_draw(rng, len(own))
    dates = _dates(rng, len(own), closes=0.09)
    voting = np.clip(own["ownership"].to_numpy() + own["voting_bias"].to_numpy(),
                     0.01, 1.0)
    ownership_edges = pd.DataFrame({
        "edge_id": [f"OWN-{i + 1:07d}" for i in range(len(own))],
        "edge_type": OWNS,
        "from_node": own["from"].to_numpy(),
        "to_node": own["to"].to_numpy(),
        "ownership_pct": _round(own["ownership"].to_numpy() * 100, 4),
        "voting_pct": _round(voting * 100, 4),
        "valid_from": dates["valid_from"],
        "valid_to": dates["valid_to"],
        "recorded_at": dates["recorded_at"],
        "source": sources,
        "confidence": confidence,
        "origin": ORIGIN,
    })

    return {
        "_nodes": pd.DataFrame(nodes),
        "_ownership": ownership_edges,
        "_groups": groups,
        "_grouped_members": grouped_members,
    }


# -------------------------------------------------- directors and addresses


def build_people_edges(entities: pd.DataFrame, nodes: pd.DataFrame,
                       rng: np.random.Generator) -> pd.DataFrame:
    """DIRECTOR_OF and REGISTERED_AT, plus IN_SECTOR and FUNDED_BY. B13.

    Directors are drawn from a pool SMALLER than the number of borrowers, so
    the same person sits on several boards. That overlap is the third leg of
    B7's entity-resolution precedence - "fuzzy name plus shared director" -
    and it is also how a hidden relationship between two apparently unrelated
    borrowers becomes findable at all.
    """
    borrowers = entities["borrower_id"].to_numpy()
    n = len(borrowers)
    addresses = nodes.loc[nodes["node_type"] == ADDRESS,
                          "node_id"].to_numpy()

    rows: list[pd.DataFrame] = []

    # ---- directors --------------------------------------------------------
    pool_size = 2_100
    director_ids = np.array([f"DIR-{i + 1:05d}" for i in range(pool_size)])
    seats = np.clip(3 + rng.poisson(1.4, n), 3, 9)
    total = int(seats.sum())
    holder = rng.choice(pool_size, total, p=_director_weights(rng, pool_size))
    company = np.repeat(np.arange(n), seats)
    roles = rng.choice(
        ["Chairman", "Managing Director", "Non-Executive Director",
         "Finance Director", "Board Member"], total,
        p=[0.11, 0.13, 0.42, 0.12, 0.22])
    sources, confidence = _source_draw(rng, total)
    dates = _dates(rng, total, closes=0.22)
    rows.append(pd.DataFrame({
        "edge_id": [f"DIR-E{i + 1:07d}" for i in range(total)],
        "edge_type": DIRECTOR_OF,
        "from_node": director_ids[holder],
        "to_node": borrowers[company],
        "role": roles,
        "ownership_pct": np.nan,
        "voting_pct": np.nan,
        "valid_from": dates["valid_from"],
        "valid_to": dates["valid_to"],
        "recorded_at": dates["recorded_at"],
        "source": sources,
        "confidence": confidence,
        "origin": ORIGIN,
    }))

    # ---- registered address ----------------------------------------------
    #
    # Weighted, not uniform: business parks and serviced offices hold many
    # registrations, which is what makes a shared address weak evidence
    # rather than none.
    weights = rng.dirichlet(np.ones(len(addresses)) * 0.6)
    at = rng.choice(len(addresses), n, p=weights)
    sources, confidence = _source_draw(rng, n)
    dates = _dates(rng, n, closes=0.06)
    rows.append(pd.DataFrame({
        "edge_id": [f"ADR-E{i + 1:06d}" for i in range(n)],
        "edge_type": REGISTERED_AT,
        "from_node": borrowers,
        "to_node": addresses[at],
        "role": "",
        "ownership_pct": np.nan,
        "voting_pct": np.nan,
        "valid_from": dates["valid_from"],
        "valid_to": dates["valid_to"],
        "recorded_at": dates["recorded_at"],
        "source": sources,
        "confidence": confidence,
        "origin": ORIGIN,
    }))

    # ---- sector and funding ----------------------------------------------
    sector_node = np.array([
        f"SECT-{s.replace(' ', '-')}" for s in entities["sector"]])
    dates = _dates(rng, n, closes=0.02)
    rows.append(pd.DataFrame({
        "edge_id": [f"SEC-E{i + 1:06d}" for i in range(n)],
        "edge_type": IN_SECTOR,
        "from_node": borrowers,
        "to_node": sector_node,
        "role": "",
        "ownership_pct": np.nan,
        "voting_pct": np.nan,
        "valid_from": dates["valid_from"],
        "valid_to": dates["valid_to"],
        "recorded_at": dates["recorded_at"],
        "source": "Governed sector classification",
        "confidence": 1.0,
        "origin": ORIGIN,
    }))

    funding_count = np.clip(1 + rng.poisson(0.8, n), 1, 4)
    total_funding = int(funding_count.sum())
    which = rng.integers(0, len(FUNDING_SOURCES), total_funding)
    borrower_of = np.repeat(borrowers, funding_count)
    sources, confidence = _source_draw(rng, total_funding)
    dates = _dates(rng, total_funding, closes=0.14)
    rows.append(pd.DataFrame({
        "edge_id": [f"FND-E{i + 1:06d}" for i in range(total_funding)],
        "edge_type": FUNDED_BY,
        "from_node": borrower_of,
        "to_node": np.array([f"FUND-{w + 1:02d}" for w in which]),
        "role": "",
        "ownership_pct": np.nan,
        "voting_pct": np.nan,
        "valid_from": dates["valid_from"],
        "valid_to": dates["valid_to"],
        "recorded_at": dates["recorded_at"],
        "source": sources,
        "confidence": confidence,
        "origin": ORIGIN,
    }))

    directors = pd.DataFrame({
        "node_id": director_ids,
        "node_type": DIRECTOR,
        "label": _person_names(rng, pool_size),
        "detail": "Board member",
    })
    frame = pd.concat(rows, ignore_index=True)
    frame.attrs["director_nodes"] = directors
    return frame


def _director_weights(rng: np.random.Generator, pool: int) -> np.ndarray:
    """A few people sit on many boards; most sit on one or two."""
    weights = rng.gamma(1.1, 1.0, pool)
    return weights / weights.sum()


# ------------------------------------------------------------ supply chain


def build_supply_chain(entities: pd.DataFrame,
                       rng: np.random.Generator) -> pd.DataFrame:
    """SUPPLIES_TO, with the dependence it represents. B13, B26.

    Directed and asymmetric: the share of the SUPPLIER's revenue and the share
    of the BUYER's cost are different numbers, and which of them is large
    decides who is exposed to whom. A single column called "dependence" would
    make the commonest supply-chain question - who is concentrated on whom -
    unanswerable in one of its two directions.

    Pairings follow plausible sector flows rather than being drawn at random,
    so a contracting company buys cement and a hospital does not.
    """
    borrowers = entities["borrower_id"].to_numpy()
    sector = entities["sector"].to_numpy()
    n = len(borrowers)

    flows: dict[str, tuple[str, ...]] = {
        "Contracting": ("Manufacturing", "Mining & Metals",
                        "Transport & Logistics", "Wholesale & Retail Trade"),
        "Real Estate": ("Contracting", "Utilities", "Financial Services"),
        "Manufacturing": ("Mining & Metals", "Petrochemicals",
                          "Transport & Logistics", "Utilities"),
        "Wholesale & Retail Trade": ("Manufacturing", "Agriculture & Food",
                                     "Transport & Logistics"),
        "Hospitality & Tourism": ("Agriculture & Food",
                                  "Wholesale & Retail Trade", "Utilities"),
        "Healthcare": ("Wholesale & Retail Trade", "Utilities"),
        "Petrochemicals": ("Utilities", "Transport & Logistics"),
        "Agriculture & Food": ("Utilities", "Transport & Logistics",
                               "Manufacturing"),
        "Telecommunications": ("Utilities", "Manufacturing"),
        "Education": ("Utilities", "Wholesale & Retail Trade"),
        "Mining & Metals": ("Utilities", "Transport & Logistics"),
        "Utilities": ("Manufacturing", "Mining & Metals"),
        "Transport & Logistics": ("Manufacturing", "Utilities"),
        "Financial Services": ("Telecommunications",),
        "Government-Related Entities": ("Contracting", "Utilities",
                                        "Manufacturing"),
    }
    by_sector: dict[str, np.ndarray] = {
        name: np.nonzero(sector == name)[0] for name in {s.name for s in SECTORS}}

    rows: list[dict[str, Any]] = []
    supplier_counts = np.clip(rng.poisson(1.9, n), 0, 8)
    for buyer in range(n):
        candidates = flows.get(sector[buyer], ())
        if not candidates:  # pragma: no cover - every sector has a flow
            continue
        for _ in range(int(supplier_counts[buyer])):
            pool = by_sector[str(rng.choice(candidates))]
            if pool.size == 0:  # pragma: no cover
                continue
            supplier = int(rng.choice(pool))
            if supplier == buyer:
                continue
            rows.append({
                "from_node": borrowers[supplier],
                "to_node": borrowers[buyer],
                "supplier_revenue_share_pct": float(
                    np.clip(rng.gamma(1.5, 7.0), 0.4, 78.0)),
                "buyer_cost_share_pct": float(
                    np.clip(rng.gamma(1.7, 6.0), 0.4, 71.0)),
                "relationship_years": int(rng.integers(1, 18)),
            })

    frame = pd.DataFrame(rows).drop_duplicates(
        subset=["from_node", "to_node"]).reset_index(drop=True)
    sources, confidence = _source_draw(rng, len(frame))
    dates = _dates(rng, len(frame), closes=0.26)
    frame.insert(0, "edge_id",
                 [f"SUP-{i + 1:07d}" for i in range(len(frame))])
    frame.insert(1, "edge_type", SUPPLIES_TO)
    frame["valid_from"] = dates["valid_from"]
    frame["valid_to"] = dates["valid_to"]
    frame["recorded_at"] = dates["recorded_at"]
    frame["source"] = sources
    frame["confidence"] = confidence
    frame["supplier_revenue_share_pct"] = _round(
        frame["supplier_revenue_share_pct"].to_numpy(), 2)
    frame["buyer_cost_share_pct"] = _round(
        frame["buyer_cost_share_pct"].to_numpy(), 2)
    frame["is_material_to_supplier"] = frame["supplier_revenue_share_pct"] >= 20.0
    frame["is_material_to_buyer"] = frame["buyer_cost_share_pct"] >= 20.0
    frame["caveat"] = (
        "Commercial dependence is not control and is never on its own a "
        "basis for a regulatory connected group - B21.")
    frame["origin"] = ORIGIN
    return frame


# ------------------------------------------------------------- guarantees


GUARANTEE_FORMS: tuple[tuple[str, float], ...] = (
    ("Corporate guarantee - unconditional", 0.34),
    ("Corporate guarantee - limited recourse", 0.19),
    ("Parent company guarantee", 0.22),
    ("Comfort letter (non-binding)", 0.11),
    ("Cross guarantee", 0.09),
    ("Personal guarantee", 0.05),
)


def build_guarantees(entities: pd.DataFrame, facilities: pd.DataFrame,
                     graph: dict[str, Any],
                     rng: np.random.Generator) -> tuple[pd.DataFrame,
                                                        pd.DataFrame,
                                                        pd.DataFrame]:
    """Reified Guarantee nodes, with PROVIDES and COVERS edges. B15, B25.

    A guarantee is a NODE, not an edge, because one guarantee can cover
    several facilities of several borrowers and be given by several
    guarantors jointly. Modelled as an edge, that fact has to be duplicated
    once per facility, and the duplicates drift apart the first time one of
    them is amended.

    Guarantors are drawn mostly from within the borrower's own group, which is
    what makes the guarantee graph and the ownership graph agree often enough
    to be credible - and disagree often enough that the intersection is worth
    computing.
    """
    borrowers = entities["borrower_id"].to_numpy()
    member_of: dict[int, int] = {}
    for group in graph["_groups"]:
        for member in group["members"]:
            member_of[int(member)] = group["index"]
    by_group: dict[int, list[int]] = {}
    for member, group_index in member_of.items():
        by_group.setdefault(group_index, []).append(member)

    latest = facilities[facilities["period"] == QUARTERS[-1]]
    per_borrower = latest.groupby("borrower_id")["facility_id"].apply(list)

    nodes: list[dict[str, Any]] = []
    provides: list[dict[str, Any]] = []
    covers: list[dict[str, Any]] = []

    forms = tuple((f[0], f[1]) for f in GUARANTEE_FORMS)
    counter = 0
    for position, borrower in enumerate(borrowers):
        facility_ids = per_borrower.get(borrower, [])
        if not facility_ids:
            continue
        # Roughly a third of borrowers have a guarantee behind something.
        if rng.random() > 0.32:
            continue
        counter += 1
        guarantee_id = f"GTEE-{counter:06d}"
        form = str(_choose(rng, forms, 1)[0])
        covered = list(rng.choice(
            facility_ids, size=min(len(facility_ids),
                                   int(rng.integers(1, 3))), replace=False))
        amount = float(
            latest.loc[latest["facility_id"].isin(covered),
                       "limit_amount"].sum()
            * float(np.clip(rng.normal(0.78, 0.24), 0.15, 1.0)))

        nodes.append({
            "node_id": guarantee_id, "node_type": GUARANTEE,
            "label": form,
            "detail": f"Covers {len(covered)} facility(ies)"})

        group_index = member_of.get(position)
        siblings = [m for m in by_group.get(group_index, [])
                    if m != position] if group_index is not None else []
        if siblings and rng.random() < 0.72:
            guarantors = [borrowers[int(rng.choice(siblings))]]
            if group_index is not None and rng.random() < 0.30:
                guarantors.append(f"HOLD-{group_index + 1:04d}")
        elif group_index is not None and rng.random() < 0.55:
            guarantors = [f"HOLD-{group_index + 1:04d}"]
        else:
            other = int(rng.integers(0, len(borrowers)))
            guarantors = [borrowers[other]] if other != position else []

        sources, confidence = _source_draw(rng, max(len(guarantors), 1))
        dates = _dates(rng, max(len(guarantors), 1), closes=0.12)
        for k, guarantor in enumerate(guarantors):
            provides.append({
                "edge_id": f"GPR-{counter:06d}-{k + 1}",
                "edge_type": PROVIDES,
                "from_node": guarantor,
                "to_node": guarantee_id,
                "guarantee_id": guarantee_id,
                "guaranteed_amount": round(amount / len(guarantors), 2),
                "guarantee_form": form,
                "legally_binding": form != "Comfort letter (non-binding)",
                "joint_and_several": len(guarantors) > 1,
                "valid_from": dates["valid_from"][k],
                "valid_to": dates["valid_to"][k],
                "recorded_at": dates["recorded_at"][k],
                "source": sources[k],
                "confidence": confidence[k],
                "origin": ORIGIN,
            })

        cover_dates = _dates(rng, len(covered), closes=0.08)
        for k, facility in enumerate(covered):
            covers.append({
                "edge_id": f"GCV-{counter:06d}-{k + 1}",
                "edge_type": COVERS,
                "from_node": guarantee_id,
                "to_node": str(facility),
                "guarantee_id": guarantee_id,
                "beneficiary_borrower_id": borrower,
                "valid_from": cover_dates["valid_from"][k],
                "valid_to": cover_dates["valid_to"][k],
                "recorded_at": cover_dates["recorded_at"][k],
                "source": "Credit administration record",
                "confidence": 0.95,
                "origin": ORIGIN,
            })

    return (pd.DataFrame(nodes), pd.DataFrame(provides),
            pd.DataFrame(covers))


# ---------------------------------------------------------- exposure network


def build_exposure_network(entities: pd.DataFrame, graph: dict[str, Any],
                           rng: np.random.Generator) -> pd.DataFrame:
    """Financial claims between counterparties in the book. B13, B28.

    Three observed types, kept apart because they behave differently under
    stress and a single "is exposed to" edge would blur them:

    ``LENT_TO``    an intercompany loan - a direct financial claim.
    ``HOLDS``      a receivable position - a claim contingent on trading.
    ``EXPOSED_TO`` an indirect exposure through a shared counterparty, which
                   is an assertion by the credit team rather than a
                   contractual claim, and carries a lower confidence to match.

    Most of these are within a group, because that is where intercompany
    funding actually happens; a minority cross group boundaries, which is what
    makes the exposure network add anything to the ownership graph rather than
    duplicating it.
    """
    borrowers = entities["borrower_id"].to_numpy()
    by_group: dict[int, list[int]] = {}
    for group in graph["_groups"]:
        by_group[group["index"]] = [int(m) for m in group["members"]]

    rows: list[dict[str, Any]] = []
    for members in by_group.values():
        if len(members) < 2:
            continue
        # Intercompany lending inside about half of groups.
        for _ in range(int(rng.poisson(1.1))):
            a, b = rng.choice(len(members), 2, replace=False)
            rows.append({
                "from_node": borrowers[members[int(a)]],
                "to_node": borrowers[members[int(b)]],
                "edge_type": LENT_TO,
                "amount": float(np.clip(rng.gamma(1.8, 26.0), 0.4, 900.0)),
                "instrument": str(rng.choice(
                    ["Intercompany loan", "Shareholder loan",
                     "Cash pooling position"])),
            })

    # Receivable concentrations, mostly along supply-chain lines but recorded
    # here because a receivable is a financial claim, not a trading relation.
    count = int(len(borrowers) * 0.35)
    payer = rng.integers(0, len(borrowers), count)
    payee = rng.integers(0, len(borrowers), count)
    for a, b in zip(payee, payer, strict=True):
        if a == b:
            continue
        rows.append({
            "from_node": borrowers[a],
            "to_node": borrowers[b],
            "edge_type": HOLDS,
            "amount": float(np.clip(rng.gamma(1.4, 14.0), 0.2, 420.0)),
            "instrument": "Trade receivable",
        })

    # Indirect exposure asserted by the credit team.
    indirect = int(len(borrowers) * 0.10)
    left = rng.integers(0, len(borrowers), indirect)
    right = rng.integers(0, len(borrowers), indirect)
    for a, b in zip(left, right, strict=True):
        if a == b:
            continue
        rows.append({
            "from_node": borrowers[a],
            "to_node": borrowers[b],
            "edge_type": EXPOSED_TO,
            "amount": float(np.clip(rng.gamma(1.2, 11.0), 0.1, 260.0)),
            "instrument": "Indirect exposure via shared counterparty",
        })

    frame = pd.DataFrame(rows).drop_duplicates(
        subset=["from_node", "to_node", "edge_type"]).reset_index(drop=True)
    sources, confidence = _source_draw(rng, len(frame))
    # An asserted indirect exposure is worth less than a booked loan whatever
    # the source says, so the type caps the confidence.
    confidence = np.where(frame["edge_type"] == EXPOSED_TO,
                          np.minimum(confidence, 0.55), confidence)
    dates = _dates(rng, len(frame), closes=0.18)
    frame.insert(0, "edge_id", [f"EXP-{i + 1:07d}" for i in range(len(frame))])
    frame["amount"] = _round(frame["amount"].to_numpy())
    frame["valid_from"] = dates["valid_from"]
    frame["valid_to"] = dates["valid_to"]
    frame["recorded_at"] = dates["recorded_at"]
    frame["source"] = sources
    frame["confidence"] = _round(confidence, 2)
    frame["origin"] = ORIGIN
    return frame
