"""
What the orchestrator is allowed to plan against.

The orchestrator — a language model, or the offline semantic planner — must not
plan from memory. It plans from the bank's governed metadata: the datasets that
exist, what one row of each represents, which periods are published, what the
fields mean, which joins a steward has declared, and which Analysis Studio
methods are available.

Three rules shape this module.

**Metadata only, never data.** Nothing here reads a row. The orchestrator learns
that `portfolio_facility` carries `ead` in USD mn at facility grain; it never
learns what any facility's EAD is. That is what keeps the model unable to state
a figure even if it wanted to.

**Retrieved, not dumped.** Twenty-six datasets with forty fields each, plus the
method library, is tens of thousands of tokens on every question — slow, costly,
and worse at the job, because the relevant five lines are buried. So the
question selects candidates first and only those are described in full.

**Cached.** The catalogue changes when a steward publishes, not when a user
asks. The summary is built once and invalidated on reload.
"""

from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

#: How many datasets and methods reach the orchestrator for one question.
#: Enough that a question spanning three sources still sees a fourth it might
#: have needed; few enough that the prompt stays readable.
MAX_DATASETS = 8
MAX_METHODS = 6
MAX_FIELDS_PER_DATASET = 26

#: Words that match everything and therefore rank nothing.
_STOP = frozenset("""
a an and are as at be by can did do does for from had has have how in into is it
its latest me my of on or over show tell that the their there these this to
what when where which who why will with you your me give list all any
available information records much many
""".split())

# The last line is the vocabulary of ASKING rather than of subjects. It stops
# there deliberately: "history", "data" and "period" look generic and are load
# bearing, because several datasets are named for them — dropping "history" from
# the terms sent "what data do you have about borrower ratings?" to the
# borrower financials reference table instead of to eight years of rating
# history.


def _terms(text: str) -> set[str]:
    """The words worth matching on, stemmed just enough to survive plurals."""
    words = re.findall(r"[a-z0-9_]+", (text or "").lower())
    out: set[str] = set()
    for word in words:
        if word in _STOP or len(word) < 2:
            continue
        out.add(word)
        if word.endswith("s") and len(word) > 3:
            out.add(word[:-1])
        if word.endswith("ies") and len(word) > 4:
            out.add(word[:-3] + "y")
    return out


# ---------------------------------------------------------------- the summary


@dataclass(frozen=True)
class DatasetSummary:
    """One governed dataset, as the orchestrator sees it."""

    name: str
    business_name: str
    domain: str
    family: str
    purpose: str
    grain: str
    primary_keys: tuple[str, ...]
    period_field: str
    periods: tuple[str, ...]
    origin: str
    is_synthetic: bool
    authoritative_for: tuple[str, ...]
    version: str
    fields: tuple[dict[str, Any], ...]
    #: Everything a question could plausibly match against, lower-cased.
    haystack: str = ""
    #: Which book this dataset describes. B44.
    portfolio_scope: str = "CREDIT_BOOK"

    @property
    def period_count(self) -> int:
        return len(self.periods)

    @property
    def latest_period(self) -> str:
        return self.periods[-1] if self.periods else ""

    def to_dict(self, *, full: bool = True) -> dict[str, Any]:
        brief = {
            "name": self.name, "business_name": self.business_name,
            "domain": self.domain, "grain": self.grain,
            "purpose": self.purpose,
            "authoritative_for": list(self.authoritative_for),
            "origin": self.origin, "is_synthetic": self.is_synthetic,
            "portfolio_scope": self.portfolio_scope,
        }
        if not full:
            return brief
        return {
            **brief,
            "family": self.family,
            "primary_keys": list(self.primary_keys),
            "period_field": self.period_field,
            "periods": list(self.periods),
            "period_count": len(self.periods),
            "latest_period": self.latest_period,
            "version": self.version,
            "field_count": len(self.fields),
            "fields": [dict(f) for f in self.fields[:MAX_FIELDS_PER_DATASET]],
        }


@dataclass(frozen=True)
class MethodSummary:
    """One Analysis Studio method, as the orchestrator sees it."""

    id: str
    name: str
    category: str
    definition: str
    aliases: tuple[str, ...]
    when_to_use: str
    when_not_to_use: str
    required_grain: str
    required_domains: tuple[str, ...]
    required_concepts: tuple[str, ...]
    required_history: str
    lifecycle: str
    is_certified: bool
    is_runnable: bool
    version: str
    haystack: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "name": self.name, "category": self.category,
            "definition": self.definition, "aliases": list(self.aliases),
            "when_to_use": self.when_to_use,
            "when_not_to_use": self.when_not_to_use,
            "required_grain": self.required_grain,
            "required_domains": list(self.required_domains),
            "required_concepts": list(self.required_concepts),
            "required_history": self.required_history,
            "certified": self.is_certified, "runnable": self.is_runnable,
            "version": self.version,
        }


@dataclass(frozen=True)
class RelationshipSummary:
    """One governed join, as the orchestrator sees it."""

    relationship_id: int
    from_dataset: str
    from_field: str
    to_dataset: str
    to_field: str
    cardinality: str
    join_policy: str
    temporal_rule: str
    semantic: str
    version: int
    match_rate: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "relationship_id": self.relationship_id,
            "from": f"{self.from_dataset}.{self.from_field}",
            "to": f"{self.to_dataset}.{self.to_field}",
            "cardinality": self.cardinality,
            "join_policy": self.join_policy,
            "temporal_rule": self.temporal_rule,
            "means": self.semantic,
            "version": self.version,
            "match_rate": self.match_rate,
        }

    def describe(self) -> str:
        rule = {"latest_on_or_before": ", joined as-of the reporting date",
                "same_period": ""}.get(self.temporal_rule, "")
        return (f"{self.from_dataset}.{self.from_field} → "
                f"{self.to_dataset}.{self.to_field} "
                f"({self.cardinality.replace('_', ' ')}{rule})")


@dataclass
class GovernedContext:
    """Everything the orchestrator may plan against, retrieved for one question."""

    datasets: list[DatasetSummary] = field(default_factory=list)
    methods: list[MethodSummary] = field(default_factory=list)
    relationships: list[RelationshipSummary] = field(default_factory=list)
    concepts: list[dict[str, Any]] = field(default_factory=list)
    periods: list[str] = field(default_factory=list)
    dimensions: dict[str, list[str]] = field(default_factory=dict)
    domains: list[str] = field(default_factory=list)
    #: Datasets that exist but did not make the cut, by name only. The
    #: orchestrator can ask for one it needs rather than assuming it is absent.
    other_datasets: list[str] = field(default_factory=list)

    @property
    def latest_period(self) -> str:
        return self.periods[-1] if self.periods else ""

    def dataset(self, name: str) -> DatasetSummary | None:
        return next((d for d in self.datasets if d.name == name), None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "datasets": [d.to_dict() for d in self.datasets],
            "methods": [m.to_dict() for m in self.methods],
            "relationships": [r.to_dict() for r in self.relationships],
            "concepts": self.concepts,
            "periods": self.periods,
            "latest_period": self.latest_period,
            "dimensions": self.dimensions,
            "domains": self.domains,
            "other_datasets": self.other_datasets,
        }


# ------------------------------------------------------------------- building


_lock = threading.Lock()
_cache: dict[str, Any] = {}


def invalidate() -> None:
    """Forget the cached summary. Called when the catalogue is republished."""
    with _lock:
        _cache.clear()


def _all_datasets() -> list[DatasetSummary]:
    from backend.data_access import get_catalog, get_data_source

    catalog = get_catalog()
    source = get_data_source()
    try:
        from backend.services.domain_status import archived_datasets

        archived = archived_datasets()
    except Exception:
        archived = frozenset()

    out: list[DatasetSummary] = []
    for name in sorted(catalog.names()):
        if name in archived:
            continue
        try:
            spec = catalog.dataset(name)
        except Exception:
            continue
        try:
            periods = tuple(source.periods(name) or ())
        except Exception:
            periods = ()

        fields = tuple(
            {"name": f.name, "business_name": f.business_name,
             "definition": f.definition, "type": f.data_type, "unit": f.unit,
             "allowed_values": (list(f.allowed_values)[:12]
                                if f.allowed_values else None)}
            for f in sorted(spec.fields.values(), key=lambda f: f.name)
        )
        haystack = " ".join([
            name, spec.business_name or "", spec.domain or "",
            spec.purpose or "", spec.grain or "",
            " ".join(spec.authoritative_for or ()),
            " ".join(f["name"] for f in fields),
            " ".join(f["business_name"] or "" for f in fields),
        ]).lower()

        out.append(DatasetSummary(
            name=name, business_name=spec.business_name or name,
            domain=spec.domain or "", family=spec.family,
            purpose=spec.purpose or "", grain=spec.grain or "",
            primary_keys=tuple(spec.primary_keys or ()),
            period_field=spec.period_field or "", periods=periods,
            origin=str(spec.origin), is_synthetic=bool(spec.is_synthetic),
            authoritative_for=tuple(spec.authoritative_for or ()),
            version=spec.version, fields=fields, haystack=haystack,
            portfolio_scope=getattr(spec, "portfolio_scope", "CREDIT_BOOK"),
        ))
    return out


def _all_methods() -> list[MethodSummary]:
    try:
        from backend.studio.registry import get_registry

        methods = get_registry().all()
    except Exception as e:
        logger.debug("No Studio registry available: %s", e)
        return []

    out: list[MethodSummary] = []
    for method in methods:
        concepts = tuple(
            str(c.get("concept") or c.get("label") or "")
            for c in (getattr(method, "required_concepts", None) or [])
        )
        haystack = " ".join([
            method.id, method.name, method.category or "",
            method.definition or "", method.purpose or "",
            " ".join(method.aliases or ()), method.when_to_use or "",
            " ".join(method.required_domains or ()),
            " ".join(method.required_fields or ()),
        ]).lower()
        out.append(MethodSummary(
            id=method.id, name=method.name, category=method.category or "",
            definition=method.definition or "",
            aliases=tuple(method.aliases or ()),
            when_to_use=method.when_to_use or "",
            when_not_to_use=method.when_not_to_use or "",
            required_grain=method.required_grain or "",
            required_domains=tuple(method.required_domains or ()),
            required_concepts=concepts,
            required_history=method.required_history or "",
            lifecycle=str(method.lifecycle),
            is_certified=bool(method.is_certified),
            is_runnable=bool(method.is_runnable),
            version=method.version, haystack=haystack,
        ))
    return out


def _all_relationships() -> list[RelationshipSummary]:
    from backend.config import settings

    if not settings.has_database:
        return []
    try:
        from backend.db.engine import get_session
        from backend.services.relationships import active_relationships

        with get_session() as session:
            rows = active_relationships(session)
    except Exception as e:
        logger.warning("Could not read the relationship graph: %s", e)
        return []

    return [
        RelationshipSummary(
            relationship_id=int(r.get("id") or 0),
            from_dataset=str(r["from_dataset"]), from_field=str(r["from_field"]),
            to_dataset=str(r["to_dataset"]), to_field=str(r["to_field"]),
            cardinality=str(r.get("cardinality") or ""),
            join_policy=str(r.get("join_policy") or "inner"),
            temporal_rule=str(r.get("temporal_rule") or "same_period"),
            semantic=str(r.get("semantic") or r.get("description") or ""),
            version=int(r.get("version") or 1),
            match_rate=r.get("match_rate"),
        )
        for r in rows
    ]


def _catalogue() -> dict[str, Any]:
    """The whole governed picture, cached."""
    with _lock:
        if _cache:
            return _cache
    built = {
        "datasets": _all_datasets(),
        "methods": _all_methods(),
        "relationships": _all_relationships(),
    }
    with _lock:
        _cache.update(built)
    return built


def all_datasets() -> list[DatasetSummary]:
    return list(_catalogue()["datasets"])


def all_methods() -> list[MethodSummary]:
    return list(_catalogue()["methods"])


def relationship_rows() -> list[dict[str, Any]]:
    """The governed relationship rows a planner may join on.

    Read through the service layer so there is one definition of "usable" —
    ACTIVE, confident enough, and not in an archived domain. Degrades to an
    empty list rather than failing: with no relationships declared, a
    multi-dataset question is refused for want of a join, which is the honest
    outcome and not an outage.
    """
    from backend.config import settings

    if not settings.has_database:
        return []
    try:
        from backend.db.engine import get_session
        from backend.services.relationships import active_relationships

        with get_session() as session:
            return active_relationships(session)
    except Exception as e:  # noqa: BLE001
        logger.warning("Could not read the relationship graph: %s", e)
        return []


def all_relationships() -> list[RelationshipSummary]:
    return list(_catalogue()["relationships"])


# ----------------------------------------------------------------- retrieval


def _score(haystack: str, terms: set[str]) -> int:
    """How many distinct question terms this candidate carries.

    Counting distinct terms rather than occurrences on purpose: a dataset whose
    purpose repeats the word "exposure" six times is not six times more relevant
    than one that carries both "exposure" and "sector".
    """
    return sum(1 for term in terms if term in haystack)


def _identifier(dataset: Any) -> set[str]:
    """The words of a dataset's technical name.

    The business name is deliberately excluded here: "Facility Limits and
    Utilisation" carries a word nobody types, so requiring the question to
    contain all of it would mean no question ever names a dataset in full.
    """
    import re

    return {w for w in re.findall(r"[a-z]+", str(dataset.name).lower())
            if len(w) > 3}


def _names(dataset: Any) -> set[str]:
    """The words of a dataset's own name — its strongest identifier."""
    import re

    return {w for w in re.findall(
        r"[a-z]+", f"{dataset.name} {dataset.business_name}".lower())
        if len(w) > 3}


#: Words that mean the Borrower 360 book and nothing else. Deliberately narrow:
#: "corporate" is a segment of the credit book as well as the name of this
#: module, and "customer" and "exposure" belong to both, so neither can select.
#: Every term here names a thing only the relationship graph carries.
BORROWER_360_TERMS: frozenset[str] = frozenset({
    "borrower360", "ubo", "ubos", "beneficial", "shareholding",
    "shareholder", "shareholders", "ownership", "owns", "parent",
    "subsidiary", "subsidiaries", "affiliate", "affiliates",
    "conglomerate", "holdco", "pyramid", "crossholding",
    "control", "controls", "controlling", "voting",
    "connected", "connectedness", "counterparty", "counterparties",
    "group", "groups", "grouping",
    "graph", "network", "centrality", "pagerank", "betweenness",
    "louvain", "community", "debtrank", "contagion", "propagation",
    "supplier", "suppliers", "supply", "buyer", "buyers",
    "guarantor", "guarantors", "guarantee", "guarantees",
    "director", "directors", "board",
    "resolution", "duplicate", "duplicates", "canonical",
    "relationship", "relationships", "structure", "structures",
})


def _scope_for(question: str, terms: set[str],
               concepts: list[str]) -> str:
    """Which book a question is about. B44.

    The credit book unless the question names something only the Borrower 360
    module has. Defaulting the other way would silently re-point every
    existing question at a different portfolio.
    """
    from backend.data_access.catalog import (
        BORROWER_360_SCOPE,
        CREDIT_BOOK_SCOPE,
    )

    words = terms | _terms(" ".join(concepts))
    if words & BORROWER_360_TERMS:
        return BORROWER_360_SCOPE
    lowered = str(question or "").lower()
    if "borrower 360" in lowered or "360" in words:
        return BORROWER_360_SCOPE
    return CREDIT_BOOK_SCOPE


def retrieve(question: str, *, concepts: list[str] | None = None,
             datasets: list[str] | None = None,
             max_datasets: int = MAX_DATASETS,
             max_methods: int = MAX_METHODS) -> GovernedContext:
    """The governed context for one question.

    `datasets` names sources the caller already knows are needed — a concept
    resolution, or a second planning pass that discovered it needs one more.
    Those are always included whatever they score.
    """
    from backend.orchestration.vocabulary import get_vocabulary

    terms = _terms(question) | _terms(" ".join(concepts or []))
    every = _catalogue()
    required = set(datasets or [])

    # B44. Which BOOK the question is about, decided before anything else.
    wanted_scope = _scope_for(question, terms, concepts or [])

    # A dataset the question names by name is always retrieved. Ranking on the
    # haystack alone dropped `collateral_register` out of the top eight for
    # "how many quarters of collateral history do you have?", because a dozen
    # other datasets mention collateral in a field somewhere.
    #
    # Restricted to the question's own book. `corporate_customer_master`
    # carries the word "customer" in its TECHNICAL NAME, so without this it is
    # force-retrieved for every question about customers - including the ones
    # that mean the credit book - and it displaces the dataset that actually
    # answers them. A name the CALLER supplied is different and stays
    # absolute: a concept resolution already knows which dataset it needs.
    required |= {d.name for d in every["datasets"]
                 if _names(d) & terms and d.portfolio_scope == wanted_scope}

    # A dataset the question names IN FULL leads. "What fields are in the
    # facility limits data?" names `facility_limits` completely, while
    # `portfolio_facility` shares one word and scores higher on the haystack
    # because the facility book mentions limits in a dozen fields.
    named_in_full = {d.name for d in every["datasets"]
                     if _identifier(d) and _identifier(d) <= terms}

    # The scope decided above orders the ranking.
    #
    # Two portfolios share one catalogue and almost all of their vocabulary:
    # both have customers, exposure at default, an IFRS 9 stage, a covenant.
    # Ranking on word overlap alone let the Borrower 360 datasets outscore the
    # credit book on its own questions - twenty new datasets pushed
    # `portfolio_facility` out of the top eight for "the ten largest customers
    # by exposure at default", and the answer became a clarification.
    #
    # So a question reaches the Borrower 360 book only when it names something
    # ONLY that book has. Everything else stays on the credit book, which is
    # what the product has always been about and what an unqualified question
    # means.
    ranked = sorted(
        every["datasets"],
        key=lambda d: (d.name not in named_in_full, d.name not in required,
                       d.portfolio_scope != wanted_scope,
                       -_score(d.haystack, terms),
                       # An authoritative source outranks one that merely
                       # mentions the word, so "exposure" reaches the facility
                       # book rather than a reference table that cites it.
                       -len(d.authoritative_for), d.name),
    )
    chosen = [d for d in ranked
              if d.name in required or _score(d.haystack, terms) > 0][:max_datasets]
    if not chosen:
        # Nothing matched: give the orchestrator the authoritative spine rather
        # than nothing, so it can still say what exists.
        chosen = [d for d in ranked if d.authoritative_for][:max_datasets]

    names = {d.name for d in chosen}
    methods = sorted(
        every["methods"],
        key=lambda m: (-_score(m.haystack, terms), not m.is_certified, m.name),
    )
    methods = [m for m in methods if _score(m.haystack, terms) > 0][:max_methods]

    # Every relationship connecting two chosen datasets, plus any that reaches
    # a chosen one — the orchestrator needs to know what it could join to.
    relationships = [
        r for r in every["relationships"]
        if r.from_dataset in names or r.to_dataset in names
    ]

    vocab = get_vocabulary()
    return GovernedContext(
        datasets=chosen, methods=methods, relationships=relationships,
        concepts=_concept_catalogue(),
        periods=list(vocab.periods), dimensions=dict(vocab.dimensions),
        domains=sorted({d.domain for d in every["datasets"] if d.domain}),
        other_datasets=[d.name for d in every["datasets"] if d.name not in names],
    )


def _concept_catalogue() -> list[dict[str, Any]]:
    """The governed credit concepts, with where each resolves.

    Included on every call rather than retrieved: there are eighteen of them,
    they are the vocabulary the whole conversation happens in, and an
    orchestrator that cannot see "exposure at default" is one that will invent a
    column name for it.
    """
    from backend.orchestration import concepts as cx

    out: list[dict[str, Any]] = []
    for concept in cx.CONCEPTS:
        out.append({
            "id": concept.id,
            "label": concept.label,
            "unit": concept.unit,
            "is_ordinal": concept.is_ordinal,
            "is_categorical": concept.is_categorical,
            "higher_is_worse": concept.higher_is_worse,
            "carried_by": [f"{c.dataset}.{c.field}" for c in concept.candidates],
        })
    return out


__all__ = [
    "MAX_DATASETS",
    "MAX_METHODS",
    "DatasetSummary",
    "GovernedContext",
    "MethodSummary",
    "RelationshipSummary",
    "all_datasets",
    "all_methods",
    "all_relationships",
    "relationship_rows",
    "invalidate",
    "retrieve",
]
