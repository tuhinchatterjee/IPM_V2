"""The nine business domains a data office actually thinks in, and what is
installed in each.

Why this file exists
--------------------
The governed catalogue names a domain per dataset, and it names it at the
grain the GENERATOR cared about: `CORPORATE COVENANTS`, `CORPORATE DPD /
DELINQUENCY`, `Arrears and Collections`, `Watchlist`. Thirty-nine of them for
forty-six datasets. That is a useful engineering taxonomy and a hopeless
business one — a Data Builder screen listing thirty-nine domains, most with a
single dataset in them, tells a credit officer nothing about what the bank
has.

The Data Builder screen was written against these business domains. Nothing
mapped the catalogue's thirty-nine onto those business headings, so the
screen compared
two vocabularies that had never been introduced: "Domains defined: 0 of 9"
beside "Governed fields: 344". Both numbers were true. Read together they were
nonsense, and the presenter was left looking at cards saying "Not
created" describing data that was installed and working.

So the mapping lives here, in the backend, as one authority. The screen reads
it, the bootstrap applies it, and a dataset that arrives without a home is
REPORTED rather than quietly dropped into a bucket.

What this does NOT do
---------------------
It does not change `portfolio_scope`. Grouping `corporate_facilities` and
`portfolio_facility` under one business domain is a statement about what a
person would go looking for; it is not a statement that they are the same
book. The corporate book stays `BORROWER_360`, the credit book stays
`CREDIT_BOOK`, and every read still goes through the scope the catalogue
declares. A business domain is a heading. A portfolio scope is a boundary.

That distinction is the whole reason the two are separate fields, and
`test_a_business_domain_does_not_merge_two_books` fails if a future edit lets
a domain imply a scope.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

DOMAIN_MAP_VERSION = "1.0.0"

#: A dataset the map does not place. Named rather than hidden: an unplaced
#: dataset is a governed dataset a person cannot find on the screen, which is
#: the defect this module exists to fix, reappearing quietly.
UNPLACED = "Unmapped"


@dataclass(frozen=True)
class BusinessDomain:
    """One heading on the Data Builder screen."""

    name: str
    description: str
    owner: str
    #: Catalogue domain names that belong here, matched case-insensitively.
    catalogue_domains: tuple[str, ...] = ()
    #: Individual dataset names that belong here regardless of their catalogue
    #: domain. Used where one catalogue domain splits across two business ones.
    datasets: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description,
                "owner": self.owner}


# ----------------------------------------------------------------- the nine

DOMAINS: tuple[BusinessDomain, ...] = (
    BusinessDomain(
        name="Core Portfolio / Facility",
        description=(
            "Facilities, limits, exposure and utilisation, and the collateral, "
            "covenants, arrears and payment behaviour attached to them — for "
            "both the credit book and the corporate Borrower 360 book."),
        owner="Credit Risk Analytics",
        catalogue_domains=(
            "Core Portfolio / Facility",
            "Limits and Approvals",
            "Collateral",
            "Covenants",
            "Arrears and Collections",
            "Recovery and Cure",
            "Return and Profitability",
            "Risk Appetite",
            "Group Structure",
            "CORPORATE FACILITIES / EXPOSURE",
            "CORPORATE LIMITS / LARGE EXPOSURES",
            "CORPORATE COLLATERAL",
            "CORPORATE COVENANTS",
            "CORPORATE DPD / DELINQUENCY",
            "CORPORATE GUARANTEES",
            "CORPORATE RESTRUCTURING / FORBEARANCE",
            "CORPORATE PROFITABILITY / RAROC",
            "CORPORATE CUSTOMER MASTER",
            "CORPORATE BORROWER 360",
            "CORPORATE CONNECTED COUNTERPARTY GRAPH",
            "CORPORATE EXPOSURE NETWORK",
            "CORPORATE OWNERSHIP & CONTROL GRAPH",
            "CORPORATE SUPPLY CHAIN GRAPH",
        ),
    ),
    BusinessDomain(
        name="Liquidity and Cash Flow",
        description=(
            "Cash, operating and free cash flow, working capital and its "
            "ageing, the debt maturity ladder, committed and undrawn "
            "headroom, debt service falling due and what has to be "
            "refinanced. Where a corporate credit actually fails: not "
            "because a ratio drifted, but because a payment fell due and "
            "the cash was not there."),
        owner="Treasury and Credit Risk",
        catalogue_domains=("Liquidity and Cash Flow",),
    ),
    BusinessDomain(
        name="External Intelligence",
        description=(
            "What is happening outside the bank, governed: external ratings "
            "and outlooks, sector, macroeconomic, geopolitical, commodity "
            "and shipping events, which borrowers each one reaches and "
            "through which channel. Every row says whether it is a recorded "
            "fact or an analytical reading."),
        owner="Credit Research",
        catalogue_domains=("External Intelligence",),
    ),
    BusinessDomain(
        name="IFRS 9 / ECL",
        description=(
            "Staging, SICR, PD, LGD, EAD and expected credit loss, with the "
            "forward-looking scenarios and macroeconomic series the "
            "measurement depends on."),
        owner="Group Finance",
        catalogue_domains=(
            "IFRS 9 Impairment",
            "Stress and Scenario",
            "Macroeconomic",
            "Climate and ESG",
            "CORPORATE IFRS 9",
        ),
        # The corporate macro series is filed under CORPORATE BORROWER 360 in
        # the catalogue because that is the build that produced it. It is a
        # macroeconomic series, and a reader looking for one will look here
        # beside `macro_saudi`, not under facilities.
        datasets=("corporate_macro",),
    ),
    BusinessDomain(
        name="Corporate Ratings",
        description=(
            "Internal grades, rating history and transitions, obligor "
            "financial statements, and the qualitative watchlist and credit "
            "file commentary that sit beside them."),
        owner="Credit Risk Analytics",
        catalogue_domains=(
            "Corporate Ratings",
            "Watchlist",
            "Credit File and Commentary",
            "CORPORATE RATINGS",
            "CORPORATE FINANCIALS",
            "CORPORATE WATCHLIST / QUALITATIVE SIGNALS",
        ),
    ),
    BusinessDomain(
        name="Retail / SME Scorecards",
        description=(
            "Application, behavioural and Saudi SME scorecard populations, "
            "their frozen development reference, model outputs, recorded "
            "credit decisions and monthly validation outcomes."),
        owner="Retail Risk",
        catalogue_domains=(
            "Retail Application Scorecard",
            "Retail Behavioral Scorecard",
            "Saudi SME Scorecard",
        ),
        # Named individually as well as by catalogue domain. Placement by
        # catalogue domain reads a field that `install_business_domains`
        # overwrites, so a dataset that was once filed as UNPLACED can never
        # be re-homed by it — the information needed to place it is gone.
        # Naming the dataset makes placement independent of what was stored.
        datasets=(
            "sme_scorecard_monthly_validation",
            "sme_scorecard_development_reference",
            "sme_scorecard_decisions",
        ),
    ),
    BusinessDomain(
        name="Documents",
        description=(
            "Credit papers, committee packs and signed facility documentation "
            "onboarded through the Data Inbox."),
        owner="Credit Administration",
    ),
    BusinessDomain(
        name="Policies / Knowledge",
        description=(
            "Credit policy, regulatory circulars and the governed knowledge "
            "the Regulatory Intelligence module reads."),
        owner="Credit Policy",
    ),
    BusinessDomain(
        name="CreditProbe Operational Metadata",
        description=(
            "How the platform knows what it knows: entity resolution across "
            "source systems, graph data-quality findings, and model "
            "performance monitoring."),
        owner="Model Risk",
        catalogue_domains=(
            "Model Performance",
            "CORPORATE ENTITY RESOLUTION",
            "CORPORATE GRAPH DATA QUALITY",
        ),
    ),
)

NAMES: tuple[str, ...] = tuple(d.name for d in DOMAINS)

#: Built once. A catalogue domain naming two business domains is a mistake in
#: this file rather than a runtime condition, so it is caught at import.
_BY_CATALOGUE: dict[str, str] = {}
_BY_DATASET: dict[str, str] = {}
for _domain in DOMAINS:
    for _catalogue in _domain.catalogue_domains:
        _key = _catalogue.strip().lower()
        # The catalogue spells one business idea two ways — "Corporate
        # Ratings" for the credit book and "CORPORATE RATINGS" for the
        # corporate one. Matching case-insensitively collapses those, which is
        # wanted. What is NOT wanted is one catalogue domain claimed by two
        # different headings: that is a decision nobody made, resolved by
        # whichever line happened to come second.
        if _BY_CATALOGUE.get(_key, _domain.name) != _domain.name:  # pragma: no cover
            raise ValueError(
                f"catalogue domain {_catalogue!r} is claimed by both "
                f"{_BY_CATALOGUE[_key]!r} and {_domain.name!r}")
        _BY_CATALOGUE[_key] = _domain.name
    for _dataset in _domain.datasets:
        _BY_DATASET[_dataset.strip().lower()] = _domain.name
    # A heading is its own catalogue domain. The catalogue was renamed to
    # these headings after this map was written, and the map went on
    # looking only for the generator's older spellings — so `ifrs9_staging`,
    # sitting in a catalogue domain literally called "IFRS 9 / ECL", came back
    # UNPLACED. Twelve datasets fell out of the map that way, and a dataset
    # that no heading claims is a dataset a person cannot find on the screen.
    _BY_CATALOGUE.setdefault(_domain.name.strip().lower(), _domain.name)


def business_domain(*, dataset: str = "", catalogue_domain: str = "") -> str:
    """Which of the nine headings this dataset belongs under.

    Returns `UNPLACED` when nothing claims it — deliberately, so the caller
    can report the gap. A default of "Core Portfolio / Facility" would put a
    retail dataset in the corporate book on the strength of a typo.
    """
    named = _BY_DATASET.get((dataset or "").strip().lower())
    if named:
        return named
    return _BY_CATALOGUE.get((catalogue_domain or "").strip().lower(), UNPLACED)


def get(name: str) -> BusinessDomain | None:
    for domain in DOMAINS:
        if domain.name == name:
            return domain
    return None


def placement(entries: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Group catalogue entries under their business domain.

    `entries` are catalogue records: anything with `name` and `domain`.
    Every domain appears in the result, including the empty ones — a heading
    with nothing under it is a true statement about the deployment, and
    hiding it would leave a reader unable to tell "no documents installed"
    from "documents not supported".
    """
    grouped: dict[str, list[str]] = {name: [] for name in NAMES}
    grouped[UNPLACED] = []
    for entry in entries:
        name = str(entry.get("name") or "")
        if not name:
            continue
        where = business_domain(dataset=name,
                                catalogue_domain=str(entry.get("domain") or ""))
        grouped.setdefault(where, []).append(name)
    for names in grouped.values():
        names.sort()
    return grouped


__all__ = [
    "DOMAINS", "DOMAIN_MAP_VERSION", "NAMES", "UNPLACED", "BusinessDomain",
    "business_domain", "get", "placement",
]
