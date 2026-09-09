"""The two data domains a Lens is allowed to read, and nothing else.

§1 of the Lenses V3 brief is an architecture rule rather than a preference: a
Lens may read the **Cockpit** domain and the **Early Warning** domain, and it
may not read the Scorecard domain, the Project Planner, the Playbook, What-If,
or anything else, unless that data has been formally registered here as part of
one of the two.

Why the boundary is enforced on (dataset, field) and not on dataset alone
------------------------------------------------------------------------
In this deployment Cockpit and Early Warning share a physical table. The
facility position carries `exposure`, `ifrs9_stage` and `ecl_coverage_pct` —
which are the book, and therefore Cockpit — beside `severity`, `watchlist`,
`trend`, `ai_risk_score`, `downgrade_prob_pct` and `covenant_headroom_pct`,
which are forward-looking signals, and therefore Early Warning. A boundary
declared at table granularity would have to call that whole table one domain
and would then be lying about half of it, which matters the moment a Lens says
"this figure is an EWS figure" and a reader decides how much weight to give it.

So `portfolio_facility` is registered in BOTH domains, and which one a
particular *term* reads is decided by the field it names. Everything else in
the catalogue is registered whole, because everything else is whole.

What is deliberately refused, by name
--------------------------------------
`pd_model_performance` is scorecard model performance — Gini, KS, PSI, the
things the Scorecard Validation module exists to compute. `scenario_definitions`
is the stress and scenario library, which is What-If's. Both are governed, both
are readable by the products that own them, and neither is a Lens's to read.
A Lens asking for either gets :func:`refusal`'s sentence rather than a chart.

Registering something new
-------------------------
A dataset joins a Lens domain by being named in :data:`COCKPIT_DATASETS` or
:data:`EWS_DATASETS` with a stated reason — not by being reachable through a
join from something that is already in, and not by inheriting a Data Builder
domain label, which is deployment state a steward may edit. `check_datasets` is
the only gate, every path that could widen the boundary calls it (metric
resolution, formula validation, code generation, chart generation, join
resolution, refresh analysis), and `tests/metrics/test_lens_domains.py` asserts
that the registry and the live catalogue still agree — so a dataset added to a
deployment fails a test rather than silently landing inside or outside.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

BOUNDARY_VERSION = "3.0.0"

COCKPIT = "cockpit"
EWS = "ews"
LENS_DOMAINS: tuple[str, ...] = (COCKPIT, EWS)

LABELS: dict[str, str] = {
    COCKPIT: "Cockpit",
    EWS: "Early Warning",
}

#: What each domain is, in the words a Lens's own explanation uses.
PURPOSE: dict[str, str] = {
    COCKPIT: ("The book as it stands: exposure, limits, staging, impairment, "
              "arrears, collateral, ratings, recoveries and returns."),
    EWS: ("What is coming: watchlist, covenants, credit-file signals, "
          "external intelligence and the forward-looking risk scores over "
          "them."),
}


# ---------------------------------------------------------------------------
# The registry
# ---------------------------------------------------------------------------

#: Datasets registered inside the Cockpit domain: the book as it stands.
#:
#: Registered BY NAME rather than by Data Builder domain, because a domain
#: label is deployment state — it is edited in Data Builder, it is republished
#: with a dataset, and it changed under this feature during development, which
#: silently moved `watchlist_register` from Early Warning into Cockpit. A
#: governed dataset NAME is what a formula actually references and is what
#: `alembic`-era data cannot rename out from under a boundary check.
COCKPIT_DATASETS: frozenset[str] = frozenset({
    # The facility position and everything measured on it. Also serves Early
    # Warning through its signal fields — see EWS_FIELDS.
    "portfolio_facility",
    # Impairment and staging.
    "ifrs9_staging", "corporate_ifrs9", "corporate_macro", "macro_saudi",
    # Arrears, payments and recovery — a measured state of the book.
    "facility_delinquency", "corporate_delinquency", "payment_history",
    "recoveries", "corporate_restructuring",
    # Limits, collateral and returns.
    "facility_limits", "corporate_limits", "facility_profitability",
    "corporate_profitability", "collateral_register", "corporate_collateral",
    "collateral_insurance", "collateral_document_expiry",
    "risk_appetite_limits", "undrawn_availability", "committed_facilities",
    # Borrowers, ratings and structure.
    "borrower_financials", "corporate_financials", "customer_ratings",
    "corporate_ratings", "rating_transitions", "group_structure",
    "corporate_customer_master", "corporate_borrower_360",
    "corporate_facilities", "corporate_connected_groups",
    "corporate_ownership_edges", "corporate_guarantees",
    "corporate_exposure_network", "corporate_supply_chain",
    "corporate_graph_nodes",
    # Impairment at facility grain. A governed derivative of `corporate_ifrs9`
    # by summation, not a second book, so it sits where the obligor grain
    # already sits.
    "corporate_ifrs9_facility",
    # Liquidity and cash flow — the borrower's capacity to pay, measured.
    "borrower_cash_flow", "capital_expenditure", "cash_balance_history",
    "debt_maturity_schedule", "debt_service_schedule", "inventory_position",
    "liquidity_buffer", "payables_position", "receivables_ageing",
    "refinancing_profile", "short_term_debt", "working_capital_position",
    # The retail book at account and application grain. Formally registered
    # inside Cockpit: this is the retail portfolio's POSITION — balance,
    # limit, utilisation, days past due — not scorecard model performance,
    # which is `pd_model_performance` and is refused below.
    "retail_behavioral_scorecard_monthly_validation",
    "retail_application_scorecard_monthly_validation",
})

#: Datasets registered inside the Early Warning domain: what is coming.
#:
#: The test each of these passes is that its REASON FOR EXISTING is to warn.
#: A returned payment and a limit excess are exception registers — nobody
#: records them to measure the book, they are recorded because something is
#: wrong. Arrears, by contrast, are a measured state and sit in Cockpit.
EWS_DATASETS: frozenset[str] = frozenset({
    # The facility position's signal fields. See EWS_FIELDS.
    "portfolio_facility",
    # Watchlist.
    "watchlist_register", "corporate_watchlist",
    # Covenants.
    "covenant_tests", "covenant_waivers", "covenant_resets",
    "corporate_covenants",
    # The credit file, as structured signals.
    "credit_memo_signals",
    # Exception registers.
    "limit_excesses", "payment_rejections", "returned_payments",
    # External intelligence.
    "borrower_external_event_link", "borrower_macro_sensitivity",
    "commodity_events", "external_rating_history", "external_rating_outlook",
    "geopolitical_events", "macro_events", "sector_events",
    "sector_sensitivity", "shipping_events",
    # Forward-looking hazard.
    "climate_risk",
    # The Early Warning book itself: the score, the observations behind it and
    # the external intelligence attached to a borrower. Every one of these
    # exists to warn, which is the test this set applies.
    "early_warning_borrower_month", "early_warning_signal_observation",
    "early_warning_external_event_synthetic",
})

#: Data Builder domains, as a FALLBACK for a dataset this file does not name.
#:
#: A deployment that adds a dataset to an existing domain gets a sensible
#: answer without a code change; a deployment that adds a domain gets a
#: refusal that says so, which is the safe direction. Both taxonomies this
#: product has shipped are covered, because a catalogue republish swaps
#: between them.
CATALOGUE_DOMAINS: dict[str, str] = {
    "Core Portfolio / Facility": COCKPIT,
    "IFRS 9 Impairment": COCKPIT,
    "IFRS 9 / ECL": COCKPIT,
    "Arrears and Collections": COCKPIT,
    "Collateral": COCKPIT,
    "Corporate Ratings": COCKPIT,
    "Limits and Approvals": COCKPIT,
    "Recovery and Cure": COCKPIT,
    "Return and Profitability": COCKPIT,
    "Risk Appetite": COCKPIT,
    "Group Structure": COCKPIT,
    "Macroeconomic": COCKPIT,
    "Liquidity and Cash Flow": COCKPIT,
    "Watchlist": EWS,
    "Covenants": EWS,
    "Credit File and Commentary": EWS,
    "External Intelligence": EWS,
    "Climate and ESG": EWS,
}

#: Datasets registered by name, assembled from the two sets above. A dataset
#: in both serves both, and which domain a TERM reads is then decided by the
#: field it names.
DATASET_DOMAINS: dict[str, tuple[str, ...]] = {
    name: tuple(d for d, members in ((COCKPIT, COCKPIT_DATASETS),
                                     (EWS, EWS_DATASETS))
                if name in members)
    for name in (COCKPIT_DATASETS | EWS_DATASETS)
}

#: Datasets a Lens may not read, and the sentence a reader is given. Named
#: explicitly rather than left to fall through the registry, because "there is
#: no rule for this" and "this belongs to another product" are different
#: answers and only the second is useful.
REFUSED: dict[str, str] = {
    "pd_model_performance": (
        "Model performance belongs to the Scorecard domain, which a Lens may "
        "not read. Gini, KS and PSI are Scorecard Validation's to publish."),
    "retail_behavioral_scorecard_development_reference": (
        "A scorecard's development window belongs to the Scorecard domain. A "
        "Lens reads the retail book, not the sample a model was fitted on."),
    "retail_application_scorecard_development_reference": (
        "A scorecard's development window belongs to the Scorecard domain. A "
        "Lens reads the retail book, not the sample a model was fitted on."),
    "sme_scorecard_monthly_validation": (
        "The SME scorecard's validation book belongs to the Scorecard domain, "
        "which a Lens may not read. A Lens reports the credit book; how a "
        "model performed on it is Scorecard Validation's to publish."),
    "sme_scorecard_development_reference": (
        "A scorecard's development window belongs to the Scorecard domain. A "
        "Lens reads the SME book, not the sample a model was fitted on."),
    "sme_scorecard_decisions": (
        "Application decisions and their overrides belong to the Scorecard "
        "domain. A Lens reads exposure and its trend, not who was approved "
        "and who overruled the score."),
    "scenario_definitions": (
        "The stress and scenario library belongs to What-If, which a Lens may "
        "not read. A Lens reports the book as it is and as it is trending, "
        "not as it would be under a scenario."),
    "corporate_entity_resolution": (
        "Entity resolution is CreditProbe's own plumbing — which source "
        "record became which borrower. It is not a credit-risk measurement "
        "and a Lens has no reading of it."),
    "corporate_graph_dq": (
        "The graph data-quality register is CreditProbe's own plumbing. Data "
        "Builder reports on it; a Lens does not."),
}

#: Fields on a dataset registered to both domains that belong to Early Warning
#: rather than to the Cockpit. Everything else on such a dataset is Cockpit.
#:
#: Each of these is a forward-looking assessment ABOUT a facility rather than a
#: measurement OF it, which is exactly the line between the two domains.
EWS_FIELDS: dict[str, frozenset[str]] = {
    "portfolio_facility": frozenset({
        "watchlist", "severity", "trend", "ai_risk_score",
        "downgrade_prob_pct", "covenant_headroom_pct", "dscr",
        "news_sentiment", "reason_code", "recommended_action",
        "trigger_type", "appetite_breach",
    }),
}

#: Which domain a metric-library domain name reports itself as. Used to filter
#: the governed catalogue before it is shown to a model, so a metric outside the
#: boundary is never even offered.
LIBRARY_DOMAINS: dict[str, str] = {
    "Corporate Portfolio": COCKPIT,
    "Corporate IFRS 9": COCKPIT,
    "Corporate Concentration": COCKPIT,
    "Retail Credit Risk": COCKPIT,
    "Retail Analytics": COCKPIT,
    "Corporate Early Warning": EWS,
}


class DomainRefused(ValueError):
    """A Lens asked for data outside the Cockpit and Early Warning domains."""


# ---------------------------------------------------------------------------
# Reading the registry
# ---------------------------------------------------------------------------


def _catalogue_domain(dataset: str) -> str:
    """The Data Builder domain a dataset declares, or empty if unknown here."""
    try:
        from backend.data_access.catalog import get_catalog

        return get_catalog().dataset(dataset).domain
    except Exception:  # noqa: BLE001 - an unknown dataset is not a crash
        return ""


def domains_of(dataset: str) -> tuple[str, ...]:
    """Which Lens domains a dataset serves. Empty means it serves neither.

    Empty is the refusal: a dataset nothing here registers is outside the
    boundary whether it is governed, ungoverned, new or misspelt, and the
    caller does not have to distinguish those cases to refuse it safely.
    """
    if not dataset:
        return ()
    if dataset in REFUSED:
        return ()
    named = DATASET_DOMAINS.get(dataset)
    if named:
        return named
    mapped = CATALOGUE_DOMAINS.get(_catalogue_domain(dataset))
    return (mapped,) if mapped else ()


def domain_of_field(dataset: str, field: str) -> str:
    """Which Lens domain one field belongs to, on a dataset in both.

    On a dataset registered to a single domain this is that domain, whatever
    the field is called. On the shared facility position it is Early Warning
    for the signal fields and Cockpit for everything else.
    """
    serves = domains_of(dataset)
    if not serves:
        return ""
    if len(serves) == 1:
        return serves[0]
    if field and field in EWS_FIELDS.get(dataset, frozenset()):
        return EWS
    return COCKPIT


def permitted(dataset: str) -> bool:
    return bool(domains_of(dataset))


def refusal(dataset: str) -> str:
    """Why this dataset is not a Lens's to read, in one sentence."""
    stated = REFUSED.get(dataset)
    if stated:
        return f"'{dataset}' is not available to a Lens. {stated}"
    catalogue_domain = _catalogue_domain(dataset)
    if catalogue_domain:
        return (
            f"'{dataset}' is in the '{catalogue_domain}' domain, which is not "
            f"registered inside Cockpit or Early Warning. A Lens reads those "
            f"two domains only. Register the domain in "
            f"backend/metrics/lens_domains.py if it belongs to one of them.")
    return (
        f"'{dataset}' is not a governed dataset a Lens may read. A Lens reads "
        f"the Cockpit and Early Warning domains only.")


def check_datasets(datasets: Iterable[str]) -> list[str]:
    """Every refusal, all at once, for a set of datasets.

    All at once for the same reason `formula.problems()` is: somebody fixing a
    cross-domain definition one refusal at a time gives up.
    """
    return [refusal(d) for d in dict.fromkeys(datasets) if d and not permitted(d)]


def require(datasets: Iterable[str]) -> None:
    """Raise unless every dataset is inside the boundary."""
    found = check_datasets(datasets)
    if found:
        raise DomainRefused(" ".join(found))


def permitted_datasets() -> list[str]:
    """Every governed dataset a Lens may read, sorted."""
    try:
        from backend.data_access.catalog import get_catalog

        names = get_catalog().names()
    except Exception:  # noqa: BLE001 - no catalogue is not a crash here
        names = sorted(DATASET_DOMAINS)
    return [n for n in names if permitted(n)]


def datasets_in(domain: str) -> list[str]:
    return [n for n in permitted_datasets() if domain in domains_of(n)]


# ---------------------------------------------------------------------------
# Formulas and metrics
# ---------------------------------------------------------------------------


def formula_domains(formula: Any) -> tuple[str, ...]:
    """The Lens domains a formula's terms actually read, in a stable order.

    Field-aware, so a ratio whose numerator filters on `severity` and whose
    denominator sums `exposure` correctly reports both domains — which is what
    makes the cross-domain lineage on the preview true rather than decorative.
    """
    found: list[str] = []
    for term in getattr(formula, "terms", ()) or ():
        dataset = getattr(term, "dataset", "")
        fields = [getattr(term, "field", ""), getattr(term, "weight_field", "")]
        fields += [getattr(c, "field", "") for c in (getattr(term, "where", ()) or ())]
        for name in [f for f in fields if f] or [""]:
            domain = domain_of_field(dataset, name)
            if domain and domain not in found:
                found.append(domain)
    return tuple(d for d in LENS_DOMAINS if d in found)


def check_formula(formula: Any) -> list[str]:
    """Every boundary refusal a formula earns."""
    return check_datasets(getattr(formula, "datasets", ()) or ())


def metric_domains(metric: Any) -> tuple[str, ...]:
    """The Lens domains a governed or user-built metric reads.

    Read from the formula where there is one, because that is the truth, and
    from the library domain otherwise, because an `Unsupported` entry has no
    formula and still has to be placed.
    """
    formula = getattr(metric, "formula", None)
    if formula is not None and getattr(formula, "terms", ()):
        found = formula_domains(formula)
        if found:
            return found
    mapped = LIBRARY_DOMAINS.get(getattr(metric, "domain", ""))
    return (mapped,) if mapped else ()


def primary_domain(metric: Any) -> str:
    """Which domain's STORY a metric belongs to, as opposed to which domains
    its fields touch.

    The two are different and both are needed. "Watchlist Exposure" measures
    a Cockpit field (`exposure`) filtered by an Early Warning one
    (`watchlist`), so its LINEAGE is both — which is what the preview and the
    boundary check want. But it is an Early Warning metric: the watchlist is
    the point of it, and the exposure is how it is sized.

    Reporting the lineage where the story is wanted made §41's corroboration
    vacuous: every such metric appeared in both the Cockpit changes and the
    Early Warning changes, so "the two domains moved together" was true by
    construction and said nothing. The primary domain is the governed library
    CATEGORY — a curated statement of what a metric is for — falling back to
    the lineage where the category says nothing.
    """
    # A metric whose every FILTER is an Early Warning field is an Early
    # Warning metric, whatever category it was filed under. The filter is what
    # makes it one: "exposure WHERE watchlist" is not a portfolio metric that
    # happens to mention the watchlist, it is a watchlist metric sized in
    # exposure.
    #
    # Three shipped metrics are in exactly that position — the watchlist rate
    # and the two risk-appetite breach metrics, all filed under a portfolio
    # category. Left alone, the watchlist AMOUNT reported as Early Warning and
    # the watchlist RATE as Cockpit, which is the same movement counted under
    # two different stories on one screen.
    filters = [c.field for t in getattr(metric.formula, "terms", ()) or ()
               for c in (getattr(t, "where", ()) or ()) if c.field]
    if filters:
        signal = EWS_FIELDS.get("portfolio_facility", frozenset())
        if all(f in signal for f in filters):
            return EWS

    mapped = LIBRARY_DOMAINS.get(getattr(metric, "domain", ""))
    if mapped:
        return mapped
    found = metric_domains(metric)
    return found[0] if found else ""


def metric_permitted(metric: Any) -> bool:
    return bool(metric_domains(metric))


def within_boundary(metrics: Iterable[Any]) -> list[Any]:
    """Only the metrics a Lens may show. Used before any model sees a catalogue."""
    return [m for m in metrics if metric_permitted(m)]


__all__ = [
    "BOUNDARY_VERSION", "COCKPIT", "EWS", "LENS_DOMAINS", "LABELS", "PURPOSE",
    "CATALOGUE_DOMAINS", "DATASET_DOMAINS", "REFUSED", "EWS_FIELDS",
    "LIBRARY_DOMAINS", "DomainRefused",
    "domains_of", "domain_of_field", "permitted", "refusal", "check_datasets",
    "require", "permitted_datasets", "datasets_in",
    "formula_domains", "check_formula", "metric_domains", "metric_permitted",
    "primary_domain",
    "within_boundary",
]
