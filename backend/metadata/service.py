"""What data exists, read once and answered the same way everywhere.

Where each fact comes from
--------------------------
`DOMAINS`    the business headings in `backend.services.data_domains`. That
             file is the authority for what a domain IS, and it stays the
             authority here: the count a person sees on the Data Builder
             screen is the count the analyst quotes, including headings with
             nothing installed under them. "No documents loaded" and
             "documents not supported" are different answers and a reader is
             entitled to tell them apart.
`datasets`   the governed catalogue. Names, grain, keys, purpose, fields and
             what each is authoritative for are declared there.
`periods`    the published lake. A dataset declares a period FIELD; only the
             lake knows which periods were actually published.
`row_count`  the published lake, for the same reason. A draft dataset reports
             nothing rather than an estimate.

Nothing here reads a row of credit data. It reads how many there are.

Caching
-------
The catalogue changes when a steward publishes, not when a user asks, so the
whole picture is built once behind a lock and dropped by `invalidate()`. Row
counts are the expensive part — forty-six `SELECT count(*)` against the lake —
and they are what makes the difference between a metadata answer that returns
in milliseconds and one that re-reads the lake on every turn.
"""

from __future__ import annotations

import logging
import math
import re
import threading
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

METADATA_VERSION = "1.0.0"

#: A dataset no business heading claims. Named rather than hidden: an unplaced
#: dataset is a governed dataset a person cannot find on the screen.
UNPLACED = "Unmapped"


# ------------------------------------------------------------------- records


@dataclass(frozen=True)
class Field:
    """One governed field, as every surface describes it."""

    name: str
    business_name: str
    definition: str
    data_type: str
    unit: str = ""
    nullable: bool = True
    allowed_values: tuple[str, ...] = ()
    #: What this field is FOR, which is what a person asking "what can I group
    #: by" wants and is not the same question as what type it is.
    kind: str = "attribute"  # measure | dimension | key | period | attribute

    def to_dict(self) -> dict[str, Any]:
        return {"field": self.name, "label": self.business_name,
                "description": self.definition, "type": self.data_type,
                "unit": self.unit, "kind": self.kind,
                "nullable": self.nullable,
                "allowed_values": list(self.allowed_values)}


@dataclass(frozen=True)
class Dataset:
    """One governed dataset."""

    name: str
    business_name: str
    domain: str
    catalogue_domain: str
    purpose: str
    grain: str
    primary_keys: tuple[str, ...]
    period_field: str
    periods: tuple[str, ...]
    row_count: int
    fields: tuple[Field, ...]
    authoritative_for: tuple[str, ...] = ()
    family: str = ""
    origin: str = ""
    is_synthetic: bool = False
    portfolio_scope: str = ""
    readable: bool = True

    @property
    def field_count(self) -> int:
        return len(self.fields)

    @property
    def period_count(self) -> int:
        return len(self.periods)

    @property
    def latest_period(self) -> str:
        return self.periods[-1] if self.periods else ""

    @property
    def measures(self) -> tuple[Field, ...]:
        return tuple(f for f in self.fields if f.kind == "measure")

    @property
    def dimensions(self) -> tuple[Field, ...]:
        return tuple(f for f in self.fields if f.kind == "dimension")

    def field(self, name: str) -> Field | None:
        wanted = (name or "").strip().lower()
        for found in self.fields:
            if found.name.lower() == wanted:
                return found
        for found in self.fields:
            if found.business_name.lower() == wanted:
                return found
        return None

    def to_dict(self, *, with_fields: bool = False) -> dict[str, Any]:
        payload = {
            "dataset": self.name, "business_name": self.business_name,
            "domain": self.domain, "purpose": self.purpose,
            "grain": self.grain, "primary_keys": list(self.primary_keys),
            "period_field": self.period_field, "periods": list(self.periods),
            "period_count": self.period_count, "row_count": self.row_count,
            "field_count": self.field_count,
            "authoritative_for": list(self.authoritative_for),
            "origin": self.origin, "is_synthetic": self.is_synthetic,
            "readable": self.readable,
        }
        if with_fields:
            payload["fields"] = [f.to_dict() for f in self.fields]
        return payload


@dataclass(frozen=True)
class Domain:
    """One business heading, with what is installed under it."""

    name: str
    description: str
    owner: str
    datasets: tuple[str, ...] = ()
    row_count: int = 0
    field_count: int = 0
    periods: tuple[str, ...] = ()

    @property
    def dataset_count(self) -> int:
        return len(self.datasets)

    @property
    def installed(self) -> bool:
        return bool(self.datasets)

    def to_dict(self) -> dict[str, Any]:
        return {"domain": self.name, "description": self.description,
                "owner": self.owner, "datasets": list(self.datasets),
                "dataset_count": self.dataset_count,
                "row_count": self.row_count, "field_count": self.field_count,
                "periods": list(self.periods),
                "period_count": len(self.periods),
                "installed": self.installed}


@dataclass(frozen=True)
class Relationship:
    """A declared join between two governed datasets."""

    left: str
    left_field: str
    right: str
    right_field: str
    kind: str = ""
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"from_dataset": self.left, "from_field": self.left_field,
                "to_dataset": self.right, "to_field": self.right_field,
                "kind": self.kind, "description": self.description}


@dataclass(frozen=True)
class Catalogue:
    """Everything CreditProbe knows about its own data, at one instant."""

    domains: tuple[Domain, ...] = ()
    datasets: tuple[Dataset, ...] = ()
    relationships: tuple[Relationship, ...] = ()
    version: str = METADATA_VERSION
    by_name: dict[str, Dataset] = field(default_factory=dict)

    def counts(self) -> dict[str, int]:
        return {
            "domains": len(self.domains),
            "domains_installed": sum(1 for d in self.domains if d.installed),
            "datasets": len(self.datasets),
            "fields": sum(d.field_count for d in self.datasets),
            "rows": sum(d.row_count for d in self.datasets),
            "relationships": len(self.relationships),
        }


# --------------------------------------------------------------- the reading

_LOCK = threading.Lock()
_CACHE: Catalogue | None = None
_INDEX: dict[str, dict[str, set[str]]] | None = None


def invalidate() -> None:
    """Forget the catalogue. Called when a steward publishes."""
    global _CACHE, _INDEX
    with _LOCK:
        _CACHE = None
        _INDEX = None


def catalogue() -> Catalogue:
    """The whole picture, built once."""
    global _CACHE
    with _LOCK:
        if _CACHE is None:
            _CACHE = _build()
        return _CACHE


# Field kinds. A "measure" is something you can sum or average; a "dimension"
# is something you can group by. Deciding this once here is what lets every
# surface answer "what can I group this by" the same way — the analyst tool
# used to derive it from the pandas dtype of a sample, which called an integer
# customer id a measure.
_KEYISH = re.compile(r"(^|_)(id|code|key|number|no)$|^customer_|^account_", re.I)
_NUMERIC = frozenset({"number", "integer", "float", "decimal"})


def _kind(name: str, data_type: str, *, period_field: str,
          keys: tuple[str, ...]) -> str:
    if name == period_field:
        return "period"
    if name in keys or _KEYISH.search(name):
        return "key"
    if (data_type or "").lower() in _NUMERIC:
        return "measure"
    return "dimension"


def _fields_of(definition: Any, *, period_field: str,
               keys: tuple[str, ...]) -> tuple[Field, ...]:
    out: list[Field] = []
    for name, declared in (getattr(definition, "fields", {}) or {}).items():
        data_type = str(getattr(declared, "data_type", "") or "")
        out.append(Field(
            name=str(name),
            business_name=str(getattr(declared, "business_name", "") or ""),
            definition=str(getattr(declared, "definition", "") or ""),
            data_type=data_type,
            unit=str(getattr(declared, "unit", "") or ""),
            nullable=bool(getattr(declared, "nullable", True)),
            allowed_values=tuple(getattr(declared, "allowed_values", None) or ()),
            kind=_kind(str(name), data_type, period_field=period_field,
                       keys=keys),
        ))
    return tuple(sorted(out, key=lambda f: f.name))


def _ordered(periods: set[str]) -> tuple[str, ...]:
    """Periods in time order. "Q1 2026" sorts before "Q4 2025" alphabetically."""

    def key(period: str) -> tuple[int, int, str]:
        text = str(period)
        quarter = re.search(r"Q([1-4])[\s-]*(\d{4})", text, re.I)
        if quarter:
            return int(quarter.group(2)), int(quarter.group(1)), text
        year_first = re.search(r"(\d{4})[\s-]*Q([1-4])", text, re.I)
        if year_first:
            return int(year_first.group(1)), int(year_first.group(2)), text
        year = re.search(r"(\d{4})", text)
        month = re.search(r"\d{4}-(\d{2})", text)
        return (int(year.group(1)) if year else 0,
                int(month.group(1)) if month else 0, text)

    return tuple(sorted(periods, key=key))


def _build() -> Catalogue:
    from backend.data_access.catalog import get_catalog
    from backend.services import data_domains as bd

    catalog = get_catalog()
    lake = _lake()
    readable = _readable(lake)
    archived = _archived()

    found: list[Dataset] = []
    for name in sorted(catalog.names()):
        if name in archived:
            continue
        definition = catalog.dataset(name)
        if definition is None:  # pragma: no cover - names() is the source
            continue
        catalogue_domain = str(getattr(definition, "domain", "") or "")
        keys = tuple(getattr(definition, "primary_keys", ()) or ())
        period_field = str(getattr(definition, "period_field", "") or "")
        is_readable = name in readable
        found.append(Dataset(
            name=name,
            business_name=str(getattr(definition, "business_name", "") or name),
            domain=bd.business_domain(dataset=name,
                                      catalogue_domain=catalogue_domain),
            catalogue_domain=catalogue_domain,
            purpose=str(getattr(definition, "purpose", "") or ""),
            grain=str(getattr(definition, "grain", "") or ""),
            primary_keys=keys,
            period_field=period_field,
            periods=_periods_of(lake, name) if is_readable else (),
            row_count=_rows_of(lake, name) if is_readable else 0,
            fields=_fields_of(definition, period_field=period_field, keys=keys),
            authoritative_for=tuple(
                getattr(definition, "authoritative_for", ()) or ()),
            family=str(getattr(definition, "dataset_family", "") or ""),
            origin=str(getattr(definition, "origin", "") or ""),
            is_synthetic=bool(getattr(definition, "is_synthetic", False)),
            portfolio_scope=str(getattr(definition, "portfolio_scope", "") or ""),
            readable=is_readable,
        ))

    by_name = {d.name: d for d in found}
    headings: list[Domain] = []
    for heading in bd.DOMAINS:
        under = tuple(d.name for d in found if d.domain == heading.name)
        periods: set[str] = set()
        for name in under:
            periods.update(by_name[name].periods)
        headings.append(Domain(
            name=heading.name, description=heading.description,
            owner=heading.owner, datasets=under,
            row_count=sum(by_name[n].row_count for n in under),
            field_count=sum(by_name[n].field_count for n in under),
            periods=_ordered(periods)))

    # A dataset no heading claims gets a heading of its own rather than
    # disappearing. It is a gap in the map, and the map is a file someone can
    # fix; a silently dropped dataset is not.
    orphans = tuple(d.name for d in found if d.domain == UNPLACED)
    if orphans:
        logger.warning("%d governed datasets are not placed under a business "
                       "domain: %s", len(orphans), ", ".join(orphans))
        headings.append(Domain(
            name=UNPLACED,
            description=("Governed datasets that no business domain claims. "
                         "A gap in the domain map, not a category."),
            owner="Data Governance", datasets=orphans,
            row_count=sum(by_name[n].row_count for n in orphans),
            field_count=sum(by_name[n].field_count for n in orphans),
            periods=_ordered({p for n in orphans for p in by_name[n].periods})))

    return Catalogue(domains=tuple(headings), datasets=tuple(found),
                     relationships=_relationships(by_name), by_name=by_name)


def _lake() -> Any:
    try:
        from backend.data_access.duckdb_source import DuckDBSource

        return DuckDBSource()
    except Exception:  # noqa: BLE001 - metadata must survive an unreadable lake
        logger.warning("The published lake could not be opened; row counts "
                       "and periods will read as unavailable.", exc_info=True)
        return None


def _readable(lake: Any) -> frozenset[str]:
    if lake is None:
        return frozenset()
    try:
        return frozenset(lake.datasets())
    except Exception:  # noqa: BLE001
        logger.warning("The published lake would not list its datasets.")
        return frozenset()


def _archived() -> frozenset[str]:
    try:
        from backend.services.domain_status import archived_datasets

        return frozenset(archived_datasets())
    except Exception:  # noqa: BLE001 - no database is a valid deployment here
        return frozenset()


def _periods_of(lake: Any, name: str) -> tuple[str, ...]:
    if lake is None:
        return ()
    try:
        return _ordered(set(lake.periods(name)))
    except Exception:  # noqa: BLE001
        return ()


def _rows_of(lake: Any, name: str) -> int:
    if lake is None:
        return 0
    try:
        return int(lake.row_count(name))
    except Exception:  # noqa: BLE001
        return 0


def _relationships(by_name: dict[str, Dataset]) -> tuple[Relationship, ...]:
    from backend.orchestration import context as ctx

    out: list[Relationship] = []
    seen: set[tuple[str, str, str, str]] = set()
    for row in ctx.relationship_rows():
        left = str(row.get("from_dataset") or "")
        right = str(row.get("to_dataset") or "")
        if left not in by_name or right not in by_name:
            continue
        key = (left, str(row.get("from_field") or ""),
               right, str(row.get("to_field") or ""))
        if key in seen:
            continue
        seen.add(key)
        out.append(Relationship(
            left=left, left_field=key[1], right=right, right_field=key[3],
            kind=str(row.get("relationship_type") or row.get("kind") or ""),
            description=str(row.get("description") or "")))
    return tuple(sorted(out, key=lambda r: (r.left, r.right, r.left_field)))


# ----------------------------------------------------------------- accessors


def domains() -> tuple[Domain, ...]:
    return catalogue().domains


def domain(name: str) -> Domain | None:
    """One heading, matched the way a person would name it.

    Exact first, then case-insensitive, then a containment match in either
    direction, so "IFRS 9" finds "IFRS 9 / ECL" and "ratings" finds
    "Corporate Ratings" without either being spelled in full.
    """
    wanted = " ".join((name or "").strip().lower().split())
    if not wanted:
        return None
    found = catalogue().domains
    for heading in found:
        if heading.name.lower() == wanted:
            return heading
    contains = [h for h in found
                if wanted in h.name.lower() or h.name.lower() in wanted]
    if len(contains) == 1:
        return contains[0]
    if contains:
        # "corporate" matches two headings. Prefer the one whose name starts
        # with what was asked over one that merely contains it.
        starts = [h for h in contains if h.name.lower().startswith(wanted)]
        return starts[0] if len(starts) == 1 else contains[0]
    # Last resort: the word appears in the heading's own vocabulary.
    words = {w for w in re.findall(r"[a-z0-9]+", wanted) if len(w) > 2}
    scored = [(len(words & set(re.findall(r"[a-z0-9]+", h.name.lower()))), h)
              for h in found]
    best = max(scored, key=lambda pair: pair[0])
    return best[1] if best[0] else None


def datasets(domain_name: str = "") -> tuple[Dataset, ...]:
    found = catalogue().datasets
    if not domain_name:
        return found
    heading = domain(domain_name)
    if heading is None:
        return ()
    return tuple(d for d in found if d.name in heading.datasets)


def dataset(name: str) -> Dataset | None:
    wanted = (name or "").strip().lower()
    if not wanted:
        return None
    every = catalogue()
    direct = every.by_name.get(wanted)
    if direct is not None:
        return direct
    for found in every.datasets:
        if found.name.lower() == wanted or found.business_name.lower() == wanted:
            return found
    return None


def fields(dataset_name: str) -> tuple[Field, ...]:
    found = dataset(dataset_name)
    return found.fields if found else ()


def periods(dataset_name: str = "") -> tuple[str, ...]:
    if dataset_name:
        found = dataset(dataset_name)
        return found.periods if found else ()
    every: set[str] = set()
    for found in catalogue().datasets:
        every.update(found.periods)
    return _ordered(every)


def relationships(dataset_name: str = "") -> tuple[Relationship, ...]:
    found = catalogue().relationships
    if not dataset_name:
        return found
    wanted = (dataset_name or "").strip().lower()
    return tuple(r for r in found
                 if r.left.lower() == wanted or r.right.lower() == wanted)


def counts() -> dict[str, int]:
    return catalogue().counts()


# ------------------------------------------------------------------ matching

_STOP = frozenset("""
a an and are as at be by can do does for from had has have how in into is it
its me my of on or over show tell that the their there these this to what
when where which who why will with you your give list all any available
information records much many data dataset datasets domain domains field
fields about need would use using assess risk risks
""".split())

# "risk" earns its place in that list the way "data" does. This is a
# credit-RISK platform: the word is in the name of half the subject matter and
# discriminates nothing, and leaving it in sent "what data do you have about
# borrower liquidity risk?" to a climate dataset whose only qualification was
# having the word in its title. A term for a specific kind of risk — credit,
# climate, liquidity, concentration — still carries, because that is the word
# doing the work.


def _terms(text: str) -> set[str]:
    out: set[str] = set()
    for word in re.findall(r"[a-z0-9_]+", (text or "").lower()):
        if word in _STOP or len(word) < 3:
            continue
        out.add(word)
        if word.endswith("ies") and len(word) > 4:
            out.add(word[:-3] + "y")
        elif word.endswith("s") and len(word) > 3:
            out.add(word[:-1])
    return out


def _haystack(found: Dataset) -> str:
    parts = [found.name.replace("_", " "), found.business_name, found.domain,
             found.purpose, found.grain, " ".join(found.authoritative_for)]
    parts.extend(f.name.replace("_", " ") for f in found.fields)
    parts.extend(f.business_name for f in found.fields)
    return " ".join(parts).lower()


def _index() -> dict[str, dict[str, set[str]]]:
    """Where every word appears, and in how many datasets.

    Built once with the catalogue. The document frequency is the point: in a
    credit-risk platform the word "risk" appears in nearly every dataset and
    therefore separates nothing, while "liquidity" appears in a handful and
    separates a great deal. Weighting by rarity is why "what data do you have
    about borrower liquidity risk?" stopped answering with a climate dataset —
    that answer came from matching "risk" in a purpose line and having no way
    to know the word was worthless.
    """
    global _INDEX
    if _INDEX is not None:
        return _INDEX
    built: dict[str, dict[str, set[str]]] = {}
    frequency: dict[str, int] = {}
    for found in catalogue().datasets:
        name_words = set(re.findall(r"[a-z0-9]+", found.name.lower()))
        label_words = set(re.findall(
            r"[a-z0-9]+",
            f"{found.business_name} {found.domain} "
            f"{' '.join(found.authoritative_for)}".lower()))
        field_words: set[str] = set()
        for declared in found.fields:
            field_words.update(re.findall(
                r"[a-z0-9]+",
                f"{declared.name} {declared.business_name}".lower()))
        prose = set(re.findall(
            r"[a-z0-9]+", f"{found.purpose} {found.grain}".lower()))
        built[found.name] = {"name": name_words, "label": label_words,
                             "field": field_words, "prose": prose}
        for word in name_words | label_words | field_words | prose:
            frequency[word] = frequency.get(word, 0) + 1
    built["__frequency__"] = frequency  # type: ignore[assignment]
    _INDEX = built
    return built


#: Where a term lands, and what that placement is worth before rarity.
_WEIGHTS = (("name", 10), ("label", 6), ("field", 3), ("prose", 1))


def search(subject: str, *, limit: int = 8) -> tuple[Dataset, ...]:
    """The governed datasets bearing on a subject, best first.

    Scored on two things: WHERE a term matches — a word in a dataset's name is
    stronger evidence than the same word buried in the definition of one of
    its forty fields — and how DISCRIMINATING that term is across the
    catalogue, so a word every dataset uses cannot carry an answer on its own.
    """
    terms = _terms(subject)
    if not terms:
        return ()
    index = _index()
    frequency: dict[str, int] = index["__frequency__"]  # type: ignore[assignment]
    total = max(1, len(catalogue().datasets))

    scored: list[tuple[float, str, Dataset]] = []
    for found in catalogue().datasets:
        where = index.get(found.name)
        if not where:
            continue
        score = 0.0
        matched = 0
        for term in terms:
            seen = frequency.get(term, 0)
            if not seen:
                continue
            rarity = math.log(total / seen) + 0.1
            for slot, weight in _WEIGHTS:
                if term in where[slot]:
                    score += weight * rarity
                    matched += 1
                    break
        if score > 0:
            # How much of the QUESTION this dataset accounts for, rather than
            # how hard one word of it hit.
            score *= (matched / len(terms)) ** 0.5
            scored.append((score, found.name, found))
    scored.sort(key=lambda row: (-row[0], row[1]))
    if not scored:
        return ()
    # Only what is genuinely close. One incidental word in a purpose line is
    # not a reason to name a dataset as an answer.
    best = scored[0][0]
    floor = max(1.0, best / 3.0)
    return tuple(found for score, _, found in scored[:limit] if score >= floor)


def coverage(subject: str, *, limit: int = 8) -> tuple[tuple[Dataset, ...],
                                                     tuple[str, ...]]:
    """What bears on a subject, and which words of it nothing bears on.

    The second half is the point. A question naming three things where the
    catalogue holds two is not answered by listing the two: "we have no
    liquidity data" is the fact the reader needs, and it is the fact a
    relevance ranking silently discards.
    """
    terms = _terms(subject)
    if not terms:
        return (), ()
    frequency: dict[str, int] = _index()["__frequency__"]  # type: ignore[assignment]
    missing = tuple(sorted(t for t in terms if not frequency.get(t)))
    return search(subject, limit=limit), missing


__all__ = [
    "METADATA_VERSION",
    "UNPLACED",
    "Catalogue",
    "Dataset",
    "Domain",
    "Field",
    "Relationship",
    "catalogue",
    "counts",
    "coverage",
    "dataset",
    "datasets",
    "domain",
    "domains",
    "fields",
    "invalidate",
    "periods",
    "relationships",
    "search",
]
