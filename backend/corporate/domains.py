"""The nineteen governed corporate domains. B3.

A domain here is what Data Builder shows as a domain: a named, owned grouping
of datasets with a stated purpose. B3 lists nineteen by name, and the point of
listing them separately rather than as one "corporate data" blob is authority.
IFRS 9 staging is owned by Impairment, the ownership graph by Group Risk, and
the Borrower 360 snapshot by neither - it copies from both and is authoritative
over nothing. Keeping that visible in the metadata is what stops the snapshot
quietly becoming the source of truth for a number it merely cached (B2).

Each entry also declares its GRAIN. Grain is the property most often
misunderstood about a table, and the one that makes a wrong answer look right:
`corporate_covenants` is one row per covenant test, so counting its rows counts
tests and not borrowers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

DOMAINS_VERSION = "1.0.0"

#: Domains whose datasets describe the relationship structure rather than the
#: borrower. Separated because B44 requires credit and network evidence to stay
#: distinguishable everywhere they are shown.
GRAPH_KIND = "GRAPH"
CREDIT_KIND = "CREDIT"
QUALITY_KIND = "QUALITY"


@dataclass(frozen=True)
class Domain:
    """One governed domain and the datasets it owns."""

    key: str
    name: str
    owner: str
    purpose: str
    kind: str = CREDIT_KIND
    datasets: tuple[str, ...] = ()
    #: What this domain is the last word on. A field the Borrower 360 snapshot
    #: also carries is still THIS domain's number; the snapshot is a copy.
    authoritative_for: tuple[str, ...] = ()
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key, "name": self.name, "owner": self.owner,
            "purpose": self.purpose, "kind": self.kind,
            "datasets": list(self.datasets),
            "authoritative_for": list(self.authoritative_for),
            "notes": self.notes,
        }


DOMAINS: tuple[Domain, ...] = (
    Domain(
        key="customer_master",
        name="CORPORATE CUSTOMER MASTER",
        owner="Client Data Management",
        purpose=("Who the borrower is: legal identity, aliases, group "
                 "membership, segment, sector, geography and relationship "
                 "ownership, as at each quarter."),
        datasets=("corporate_customer_master",),
        authoritative_for=("corporate_identity",),
        notes=("Names, aliases and the Arabic name are the inputs entity "
               "resolution works on, so they live here rather than being "
               "derived anywhere else."),
    ),
    Domain(
        key="ratings",
        name="CORPORATE RATINGS",
        owner="Credit Risk - Rating Unit",
        purpose=("The internal grade on the master scale, the model that "
                 "produced it, any override, and the movement against the "
                 "previous assessment."),
        datasets=("corporate_ratings",),
        authoritative_for=("corporate_internal_rating",),
    ),
    Domain(
        key="facilities",
        name="CORPORATE FACILITIES / EXPOSURE",
        owner="Credit Administration",
        purpose=("Every facility granted to a corporate borrower: limit, "
                 "drawn and undrawn, funded and unfunded, product, currency "
                 "and security status, at each quarter end."),
        datasets=("corporate_facilities",),
        authoritative_for=("corporate_exposure",),
        notes="One row per facility per quarter, not one per borrower.",
    ),
    Domain(
        key="ifrs9",
        name="CORPORATE IFRS 9",
        owner="Impairment",
        purpose=("The staging decision and the expected credit loss behind "
                 "it: PD, LGD, EAD, twelve-month and lifetime ECL, scenario "
                 "weighting and any management overlay."),
        datasets=("corporate_ifrs9",),
        authoritative_for=("corporate_staging", "corporate_ecl"),
        notes=("The Borrower 360 snapshot copies stage and final_ecl. It is "
               "never authoritative over them - B2."),
    ),
    Domain(
        key="delinquency",
        name="CORPORATE DPD / DELINQUENCY",
        owner="Collections",
        purpose=("Days past due, the arrears bucket, the amount overdue, "
                 "missed payments and whether collections have been engaged."),
        datasets=("corporate_delinquency",),
        authoritative_for=("corporate_dpd",),
    ),
    Domain(
        key="financials",
        name="CORPORATE FINANCIALS",
        owner="Credit Analysis",
        purpose=("Spread financial statements and the credit ratios derived "
                 "from them, with the statement date and its age so a stale "
                 "ratio can be recognised as stale."),
        datasets=("corporate_financials",),
        authoritative_for=("corporate_financials",),
    ),
    Domain(
        key="covenants",
        name="CORPORATE COVENANTS",
        owner="Credit Administration",
        purpose=("Every covenant tested, the threshold, the observed value, "
                 "the headroom and whether it breached."),
        datasets=("corporate_covenants",),
        authoritative_for=("corporate_covenants",),
        notes="One row per covenant test per quarter.",
    ),
    Domain(
        key="collateral",
        name="CORPORATE COLLATERAL",
        owner="Credit Administration",
        purpose=("Security held: type, market and eligible value, the "
                 "valuation date and how old it is, and the coverage it "
                 "provides against the secured exposure."),
        datasets=("corporate_collateral",),
        authoritative_for=("corporate_collateral",),
        notes="One row per collateral item per quarter.",
    ),
    Domain(
        key="guarantees",
        name="CORPORATE GUARANTEES",
        owner="Credit Administration",
        purpose=("Guarantees given and received between counterparties: the "
                 "guarantor, the beneficiary, the covered amount and the "
                 "legal form."),
        kind=GRAPH_KIND,
        datasets=("corporate_guarantees",),
        authoritative_for=("corporate_guarantees",),
        notes=("Both a credit fact and a graph edge. Recorded once, here, "
               "and read by the guarantee graph rather than copied into it."),
    ),
    Domain(
        key="limits",
        name="CORPORATE LIMITS / LARGE EXPOSURES",
        owner="Portfolio Risk",
        purpose=("Single-name and group utilisation against the eligible "
                 "capital reference, and the large-exposure status that "
                 "follows from it."),
        datasets=("corporate_limits",),
        authoritative_for=("corporate_large_exposure",),
        notes=("The capital reference and thresholds here are demonstration "
               "parameters, not verified regulatory limits - B55."),
    ),
    Domain(
        key="watchlist",
        name="CORPORATE WATCHLIST / QUALITATIVE SIGNALS",
        owner="Credit Risk - Watchlist Committee",
        purpose=("Qualitative concerns recorded against a borrower: the "
                 "signal, its severity, who raised it and when, and the "
                 "watchlist grade that resulted."),
        datasets=("corporate_watchlist",),
        authoritative_for=("corporate_watchlist",),
    ),
    Domain(
        key="restructuring",
        name="CORPORATE RESTRUCTURING / FORBEARANCE",
        owner="Special Assets",
        purpose=("Concessions granted for credit reasons: the type, the "
                 "date, the probation period and whether the exposure is "
                 "still classified as forborne."),
        datasets=("corporate_restructuring",),
        authoritative_for=("corporate_forbearance",),
    ),
    Domain(
        key="profitability",
        name="CORPORATE PROFITABILITY / RAROC",
        owner="Business Finance",
        purpose=("Revenue, cost of risk, capital consumed and the "
                 "risk-adjusted return on it, per borrower per quarter."),
        datasets=("corporate_profitability",),
        authoritative_for=("corporate_raroc",),
    ),
    Domain(
        key="ownership",
        name="CORPORATE OWNERSHIP & CONTROL GRAPH",
        owner="Group Risk",
        purpose=("Observed shareholding and voting relationships between "
                 "legal entities and persons, each with the source it was "
                 "asserted by and the period it is valid for."),
        kind=GRAPH_KIND,
        datasets=("corporate_ownership_edges", "corporate_graph_nodes"),
        authoritative_for=("corporate_ownership",),
        notes=("Observed edges only. Effective ownership, control closure "
               "and connected groups are DERIVED and live in their own "
               "datasets so the derivation stays inspectable - B14."),
    ),
    Domain(
        key="supply_chain",
        name="CORPORATE SUPPLY CHAIN GRAPH",
        owner="Sector Research",
        purpose=("Declared supplier and customer relationships, the share of "
                 "each party's revenue or cost they represent, and how that "
                 "was evidenced."),
        kind=GRAPH_KIND,
        datasets=("corporate_supply_chain",),
        authoritative_for=("corporate_supply_chain",),
        notes=("Commercial dependence is not control and is never used to "
               "form a regulatory group - B21."),
    ),
    Domain(
        key="exposure_network",
        name="CORPORATE EXPOSURE NETWORK",
        owner="Portfolio Risk",
        purpose=("Financial claims between counterparties in the book: "
                 "intercompany lending, receivables concentration and the "
                 "guarantee-backed exposure that links two names."),
        kind=GRAPH_KIND,
        datasets=("corporate_exposure_network",),
        authoritative_for=("corporate_exposure_network",),
    ),
    Domain(
        key="connected",
        name="CORPORATE CONNECTED COUNTERPARTY GRAPH",
        owner="Group Risk",
        purpose=("The derived connected-counterparty groups: which borrowers "
                 "were grouped, on which basis, and the evidence chain that "
                 "put each one there."),
        kind=GRAPH_KIND,
        datasets=("corporate_connected_groups",),
        authoritative_for=("corporate_connected_group",),
        notes=("Derived, not observed. Graph connectivity is not regulatory "
               "connectedness - B54."),
    ),
    Domain(
        key="entity_resolution",
        name="CORPORATE ENTITY RESOLUTION",
        owner="Client Data Management",
        purpose=("Which source records were judged to be the same legal "
                 "entity, by which rule, with what confidence, and whether a "
                 "human has reviewed it."),
        kind=QUALITY_KIND,
        datasets=("corporate_entity_resolution",),
        authoritative_for=("corporate_canonical_entity",),
        notes=("Source records are never destructively merged - B7. The "
               "mapping is additive and reversible."),
    ),
    Domain(
        key="graph_dq",
        name="CORPORATE GRAPH DATA QUALITY",
        owner="Group Risk",
        purpose=("What is wrong with the graph and how much of the answer "
                 "depends on it: missing ownership, percentages that do not "
                 "sum, cycles, stale assertions and unresolved duplicates."),
        kind=QUALITY_KIND,
        datasets=("corporate_graph_dq",),
        authoritative_for=("corporate_graph_quality",),
    ),
)

BY_KEY: dict[str, Domain] = {d.key: d for d in DOMAINS}
BY_NAME: dict[str, Domain] = {d.name: d for d in DOMAINS}

#: Which domain owns each dataset. Read the other way round from DOMAINS so a
#: dataset can never be claimed by two owners without this raising at import.
DATASET_DOMAIN: dict[str, str] = {}
for _domain in DOMAINS:
    for _dataset in _domain.datasets:
        if _dataset in DATASET_DOMAIN:  # pragma: no cover - guarded at import
            raise RuntimeError(
                f"{_dataset} is claimed by both {DATASET_DOMAIN[_dataset]} "
                f"and {_domain.name}; a dataset has exactly one owning domain")
        DATASET_DOMAIN[_dataset] = _domain.name


def graph_domains() -> tuple[Domain, ...]:
    return tuple(d for d in DOMAINS if d.kind == GRAPH_KIND)


def credit_domains() -> tuple[Domain, ...]:
    return tuple(d for d in DOMAINS if d.kind == CREDIT_KIND)


def authority_for(purpose: str) -> Domain:
    """Which domain is the last word on this governed purpose."""
    for domain in DOMAINS:
        if purpose in domain.authoritative_for:
            return domain
    known = sorted(p for d in DOMAINS for p in d.authoritative_for)
    raise KeyError(
        f"no corporate domain is authoritative for '{purpose}'. "
        f"Known: {', '.join(known)}")


def catalogue() -> dict[str, Any]:
    """B3, for a report or a screen."""
    return {
        "domains_version": DOMAINS_VERSION,
        "count": len(DOMAINS),
        "domains": [d.to_dict() for d in DOMAINS],
        "by_kind": {
            "CREDIT": [d.name for d in credit_domains()],
            "GRAPH": [d.name for d in graph_domains()],
            "QUALITY": [d.name for d in DOMAINS if d.kind == QUALITY_KIND],
        },
        "datasets": dict(sorted(DATASET_DOMAIN.items())),
    }
