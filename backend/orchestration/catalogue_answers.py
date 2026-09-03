"""Ask CreditProbe, about CreditProbe's own data.

"What datasets do you have?" is not a question about credit. It is a question
about the catalogue, and it has to be answered from the LIVE catalogue rather
than from anything written down: a list that was true when it was typed is a
list that will be wrong the first time a data steward publishes a period, and
being confidently wrong about your own contents is worse than having none.

Three questions, and they are a thread
--------------------------------------
    "What datasets do you have?"              every dataset, by domain
    "Tell me about Corporate IFRS 9"          one dataset, in full
    "Show Q1 2025"                            that dataset, at that period

The second inherits nothing and the third inherits everything. A reader who has
just been shown a dataset and then types a period label means that dataset at
that period, and asking them which dataset they meant is the product not
listening.

What a dataset overview is
--------------------------
Three blocks, and the third is the one that earns trust:

    OVERVIEW    domain, grain, frequency, coverage, periods, fields, rows,
                origin, what it is authoritative for
    PROFILE     each field profiled the way its TYPE deserves — an identifier
                is counted and checked for duplicates, an amount is summed, a
                rate is averaged by exposure, a stage is distributed, a date is
                bounded. Averaging an account number is the single clearest
                sign that a profiler does not know what it is looking at.
    OBSERVATIONS the first twenty actual rows. Not a sample, not a summary:
                the rows, so a reader can see the data rather than a
                description of it.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

CATALOGUE_VERSION = "1.0.0"

#: How many actual rows an overview shows without being asked.
PREVIEW_ROWS = 20
#: How many it shows when asked for more. Beyond this a reader is scrolling
#: through a table they should be filtering instead.
PREVIEW_ROWS_MAX = 50

# ------------------------------------------------------------------ intents

_WHOLE_CATALOGUE = (
    r"\bwhat (?:datasets?|data(?:sets)?|tables?) (?:do|have) you\b",
    r"\bwhat (?:datasets?|data) (?:do you have|are (?:there|available))\b",
    r"\b(?:list|show me) (?:all )?(?:the |your )?datasets?\b",
    r"\bwhat data do you (?:have|hold|carry)\b",
    r"\bwhich datasets? (?:do you have|are available|exist)\b",
    r"\bwhat(?:'s| is) in the (?:data )?catalogue\b",
    r"\bshow me the (?:data )?catalogue\b",
)

_ABOUT_A_DATASET = (
    r"\btell me about\b",
    r"\bshow me the\b.{0,60}\bdataset\b",
    r"\bwhat(?:'s| is) in\b",
    r"\bdescribe\b",
    r"\bopen\b",
    r"\bprofile\b",
)

#: "Show Q1 2025" — a bare period, which means the dataset already on the
#: table at that period. Nothing else in the sentence, deliberately: a period
#: inside a longer question is that question's period, not a new subject.
_BARE_PERIOD = re.compile(
    r"^\s*(?:show|open|give me|let'?s see|and)?\s*(?:me\s+)?(?:the\s+)?"
    r"(?P<period>Q[1-4]\s+\d{4}|\d{4}[-/]\d{1,2}|FY\s*\d{4}|\d{4})\s*[.?!]?\s*$",
    re.IGNORECASE)

_MORE_ROWS = re.compile(
    r"\b(?:show|give me|see)\s+(?:me\s+)?(?:the\s+)?(?P<n>\d{1,3})\s+"
    r"(?:more\s+)?(?:rows?|records?|observations?|lines?)\b"
    r"|\b(?:more|another) (?:rows?|records?|observations?)\b"
    r"|\bshow (?:me )?more\b",
    re.IGNORECASE)


def wants_catalogue(question: str) -> bool:
    """Whether this asks what the product holds, as a whole."""
    text = " ".join((question or "").lower().split())
    return any(re.search(p, text) for p in _WHOLE_CATALOGUE)


def wants_dataset(question: str) -> bool:
    """Whether this asks about one dataset rather than about the book."""
    text = " ".join((question or "").lower().split())
    return any(re.search(p, text) for p in _ABOUT_A_DATASET)


def bare_period(question: str) -> str:
    """The period a bare "Show Q1 2025" names, or empty."""
    match = _BARE_PERIOD.match(question or "")
    return " ".join(match.group("period").split()) if match else ""


def rows_wanted(question: str) -> int:
    """How many observations a follow-up asked for, capped at the maximum."""
    match = _MORE_ROWS.search(question or "")
    if not match:
        return PREVIEW_ROWS
    asked = match.groupdict().get("n")
    if not asked:
        return PREVIEW_ROWS_MAX
    return max(1, min(int(asked), PREVIEW_ROWS_MAX))


# ------------------------------------------------------- naming a dataset


def _normal(text: str) -> str:
    """A name with the punctuation and spacing that distinguish nothing removed.

    "Corporate IFRS 9", "corporate_ifrs9" and "Corporate IFRS9" are one name
    written three ways, and a resolver that treated them as three would fail on
    the two a person actually types.
    """
    return re.sub(r"[^a-z0-9]", "", str(text or "").lower())


#: Grain words a person uses to tell two datasets in one domain apart.
#: "Facility IFRS 9" and "Corporate IFRS 9" are both IFRS 9; the grain is the
#: whole of what distinguishes them, and neither name appears in the catalogue.
_GRAIN_WORDS: dict[str, tuple[str, ...]] = {
    "facility": ("facility", "facilities", "account", "accounts", "loan",
                 "loans"),
    "customer": ("customer", "customers", "borrower", "borrowers", "obligor",
                 "obligors", "corporate", "client", "clients", "counterparty"),
    "portfolio": ("portfolio", "book"),
    "sector": ("sector", "sectors", "segment", "segments"),
}


def _grain_of(dataset: Any) -> str:
    """Which grain word this dataset's declared grain reads as."""
    said = str(getattr(dataset, "grain", "") or "").lower()
    for grain, words in _GRAIN_WORDS.items():
        if any(w in said for w in words):
            return grain
    return ""


def resolve(question: str, catalogue: Any = None) -> Any:
    """The dataset a sentence names, or None.

    Three ways, in order of how certain each is:

      1. the technical id or the business name, however it is punctuated;
      2. a domain phrase plus a grain word — "the facility IFRS 9 dataset" —
         which is how a person distinguishes two datasets in one domain that
         the catalogue has given near-identical names;
      3. a domain phrase alone, but only when that domain holds exactly one
         dataset, because otherwise it names the domain and not a dataset.
    """
    from backend.metadata import service as ms

    everything = list(getattr(catalogue, "datasets", None) or ms.datasets())
    if not everything:
        return None
    asked = _normal(question)
    if not asked:
        return None

    # 1 — a name, however it is spelled. Longest first so "corporate ifrs9"
    #     is not answered by a dataset called "corporate".
    named = sorted(
        everything,
        key=lambda d: max(len(_normal(d.name)), len(_normal(d.business_name))),
        reverse=True)
    for found in named:
        for candidate in (found.name, found.business_name):
            token = _normal(candidate)
            if len(token) >= 6 and token in asked:
                return found

    # 2 — a domain and a grain.
    words = set(re.findall(r"[a-z0-9]+", (question or "").lower()))
    wanted_grain = next(
        (grain for grain, forms in _GRAIN_WORDS.items()
         if words & set(forms)), "")
    by_domain: dict[str, list[Any]] = {}
    for found in everything:
        by_domain.setdefault(str(found.domain), []).append(found)
    for domain, members in by_domain.items():
        if _normal(domain) and _normal(domain) in asked:
            if wanted_grain:
                matched = [m for m in members if _grain_of(m) == wanted_grain]
                if len(matched) == 1:
                    return matched[0]
            if len(members) == 1:
                return members[0]

    # 2b — a domain named the way a person names it. A catalogue domain is
    #      often a compound label — "IFRS 9 / ECL", "Core Portfolio /
    #      Facility" — and nobody types the whole thing. Each side of the
    #      slash is a name the domain answers to, so "the Facility IFRS 9
    #      dataset" finds the IFRS 9 domain by its first half and then the
    #      facility-grained dataset inside it.
    for domain, members in by_domain.items():
        for alias in _domain_aliases(domain):
            token = _normal(alias)
            if len(token) < 3 or token not in asked:
                continue
            if wanted_grain:
                matched = [m for m in members if _grain_of(m) == wanted_grain]
                if len(matched) == 1:
                    return matched[0]
            if len(members) == 1:
                return members[0]
    return None


def _domain_aliases(domain: str) -> list[str]:
    """The names one catalogue domain answers to.

    The whole label and each side of its separators. "IFRS 9 / ECL" is called
    "IFRS 9" by everybody and "ECL" by half of them, and it is called by its
    full punctuated name by nobody.
    """
    label = str(domain or "").strip()
    if not label:
        return []
    parts = [p.strip() for p in re.split(r"[/|,]", label) if p.strip()]
    return [label, *parts] if len(parts) > 1 else [label]


__all__ = ["CATALOGUE_VERSION", "PREVIEW_ROWS", "PREVIEW_ROWS_MAX",
           "wants_catalogue", "wants_dataset", "bare_period", "rows_wanted",
           "resolve", "named_but_unknown", "unknown_dataset_result"]


# ------------------------------------------------------------- the listing


#: What a reader deciding whether to ask about a dataset needs to know, in the
#: order they need it. Frequency sits beside the period count because "34" and
#: "34 quarters" answer different questions, and only the second one tells
#: somebody whether a year-on-year comparison is available.
CATALOGUE_COLUMNS: list[dict[str, Any]] = [
    {"name": "domain", "label": "Data domain", "semantic": "text"},
    {"name": "business_name", "label": "Dataset", "semantic": "text"},
    {"name": "dataset", "label": "Technical id", "semantic": "text"},
    {"name": "grain", "label": "One row per", "semantic": "text"},
    {"name": "frequency", "label": "Frequency", "semantic": "text"},
    {"name": "periods", "label": "Periods", "semantic": "count",
     "decimals": 0, "align": "right"},
    {"name": "from", "label": "From", "semantic": "period"},
    {"name": "to", "label": "Latest", "semantic": "period"},
    {"name": "fields", "label": "Fields", "semantic": "count",
     "decimals": 0, "align": "right"},
    {"name": "rows", "label": "Rows", "semantic": "count",
     "decimals": 0, "align": "right"},
    {"name": "state", "label": "State", "semantic": "text"},
]


def catalogue_rows(catalogue: Any = None) -> list[dict[str, Any]]:
    """Every readable dataset, ordered by domain then by name.

    Ordered by domain because that is how it is asked for and how it is read:
    a reader wants to know what the bank holds about impairment, not which
    dataset happens to sort first alphabetically across seventy-seven of them.
    """
    from backend.metadata import service as ms

    everything = list(getattr(catalogue, "datasets", None) or ms.datasets())
    rows = []
    for found in everything:
        if not getattr(found, "readable", True):
            continue
        rows.append({
            "domain": found.domain,
            "business_name": found.business_name,
            "dataset": found.name,
            "grain": str(found.grain or "").rstrip(".") or "—",
            "frequency": found.frequency or "reference",
            "periods": found.period_count,
            "from": found.first_period or "—",
            "to": found.latest_period or "—",
            "fields": found.field_count,
            "rows": int(found.row_count or 0),
            "state": "Synthetic data" if found.is_synthetic else "Client data",
        })
    rows.sort(key=lambda r: (str(r["domain"]), str(r["business_name"])))
    return rows


def catalogue_answer(rows: list[dict[str, Any]]) -> str:
    """The sentence over the listing, said the way the book is actually shaped."""
    if not rows:
        return ("The governed catalogue holds nothing yet. A data steward "
                "publishes a dataset in Data Builder and it appears here.")
    domains = sorted({str(r["domain"]) for r in rows})
    total_rows = sum(int(r["rows"] or 0) for r in rows)
    fields = sum(int(r["fields"] or 0) for r in rows)
    dated = [r for r in rows if r["periods"]]
    said = (f"{len(rows)} governed datasets across {len(domains)} data "
            f"{'domain' if len(domains) == 1 else 'domains'}, holding "
            f"{total_rows:,} rows and {fields:,} fields.")
    if dated:
        from backend.metadata import frequency as fq

        # Chronologically, not lexically. "Q4 2025" sorts after "Q2 2026" as
        # text, so the string maximum reported a period that had already
        # passed as the most recent one published.
        latest = fq.latest_of([str(r["to"]) for r in dated])
        kinds = sorted({str(r["frequency"]) for r in dated})
        shape = (f"{kinds[0]}" if len(kinds) == 1
                 else " and ".join([", ".join(kinds[:-1]), kinds[-1]]))
        said += (f" {len(dated)} of them publish on a period; they are "
                 f"{shape}, and the most recent published period is "
                 f"{latest}.")
    undated = len(rows) - len(dated)
    if undated:
        said += (f" The remaining {undated} are reference data with no "
                 "period of their own.")
    return said


# ------------------------------------------------------------- the profile


#: What a field IS, for profiling. Not its storage type: `pd_12m_pct` and
#: `ead` are both floats and profiling them the same way is how a catalogue
#: reports the average of an account number.
IDENTIFIER = "identifier"
AMOUNT = "amount"
RATE = "rate"
RATIO = "ratio"
ORDINAL_CLASS = "ordinal_class"
CATEGORY = "category"
BOOLEAN = "boolean"
DATE = "date"
DURATION = "duration"
TEXT = "text"

#: Name shapes that say what a field is when the catalogue's own metadata does
#: not. Ordered: the first match wins, so `ecl_coverage_pct` is a rate before
#: it is an amount.
_BY_NAME: tuple[tuple[str, str], ...] = (
    (r"(?:^|_)(?:id|key)$|_id$|_key$|^account|^customer_id|^borrower_id"
     r"|_number$|_ref$", IDENTIFIER),
    (r"stage|grade|band|bucket|tier|notch", ORDINAL_CLASS),
    (r"_flag$|^is_|^has_|_indicator$", BOOLEAN),
    (r"date$|_at$|^as_of", DATE),
    (r"dpd|days_past_due|_days$|days_", DURATION),
    (r"_pct$|_rate$|^pd_|_pd$|lgd|coverage|utilisation|utilization|margin"
     r"|_share$|yield", RATE),
    (r"ratio$|dscr|leverage|_x$|coverage_times", RATIO),
    (r"sector|segment|region|country|industry|type$|status$|category"
     r"|currency|name$|reason$|_by$", CATEGORY),
    (r"ead|ecl|exposure|balance|amount|limit|outstanding|revenue|ebitda"
     r"|income|cost|assets|liabilit|debt|cash|capital|provision", AMOUNT),
)

_NUMERIC_TYPES = ("float", "double", "decimal", "int", "bigint", "number",
                  "numeric", "real")


def profile_kind(field: Any) -> str:
    """What one field is, for the purpose of describing it.

    The catalogue's own `kind` decides first where it is decisive — a declared
    key is an identifier and a declared period is a date — and the name shape
    decides the rest. A profiler that went by storage type alone would average
    an account number, which is the single clearest sign that it does not know
    what it is looking at.
    """
    name = str(getattr(field, "name", "") or "").lower()
    declared = str(getattr(field, "kind", "") or "").lower()
    data_type = str(getattr(field, "data_type", "") or "").lower()

    if declared == "key":
        return IDENTIFIER
    if declared == "period":
        return DATE
    if "bool" in data_type:
        return BOOLEAN
    for pattern, kind in _BY_NAME:
        if re.search(pattern, name):
            return kind
    if declared == "dimension":
        return CATEGORY
    if any(t in data_type for t in _NUMERIC_TYPES):
        return AMOUNT
    if "date" in data_type or "time" in data_type:
        return DATE
    return TEXT


#: How each kind is described, and what it must NEVER be described with. The
#: second half is the point: an average stage is a number no reporting standard
#: recognises, and a summed PD is a type error with a unit printed after it.
PROFILE_RULES: dict[str, dict[str, str]] = {
    IDENTIFIER: {
        "shows": "rows, distinct values, duplicates, missing",
        "never": "an average — an identifier has no magnitude"},
    AMOUNT: {
        "shows": "total, mean, median, smallest and largest",
        "never": "nothing; an amount is additive"},
    RATE: {
        "shows": "exposure-weighted average, median, 25th and 75th percentile",
        "never": "a total — summing a rate across a portfolio is a type error"},
    RATIO: {
        "shows": "median, 25th and 75th percentile, smallest and largest",
        "never": "a total, and a mean only with its median beside it"},
    ORDINAL_CLASS: {
        "shows": "the distribution across classes, by count and by exposure",
        "never": "an average class — no reporting standard recognises stage 1.7"},
    CATEGORY: {
        "shows": "how many categories, and the largest few by share",
        "never": "any arithmetic at all"},
    BOOLEAN: {
        "shows": "how many yes, how many no, how many missing",
        "never": "a mean, which reads as a rate and is not one"},
    DATE: {
        "shows": "earliest, latest, and how many are missing",
        "never": "a sum"},
    DURATION: {
        "shows": "the distribution across bands, and the median",
        "never": "a mean alone — a long tail moves it and describes nobody"},
    TEXT: {
        "shows": "how many distinct values, and how many are missing",
        "never": "any arithmetic at all"},
}


PROFILE_COLUMNS: list[dict[str, Any]] = [
    {"name": "field", "label": "Field", "semantic": "text"},
    {"name": "label", "label": "Means", "semantic": "text"},
    {"name": "kind", "label": "Kind", "semantic": "text"},
    {"name": "profile", "label": "Profile", "semantic": "text"},
    {"name": "missing", "label": "Missing", "semantic": "count",
     "decimals": 0, "align": "right"},
]


def _read(dataset: Any, period: str = "") -> Any:
    """The dataset's rows at one period, through the governed read path."""
    from backend.data_access import get_data_source
    from backend.data_access.context import AnalysisContext

    source = get_data_source()
    label = period or dataset.latest_period
    context = AnalysisContext(period=label) if label else AnalysisContext(
        period="")
    return source.fetch(dataset.name, fields=[f.name for f in dataset.fields],
                        context=context)


def _fmt(value: Any, decimals: int = 2) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if number == int(number) and abs(number) < 1e15:
        return f"{int(number):,}"
    return f"{number:,.{decimals}f}"


def _describe(kind: str, name: str, frame: Any, weight: Any) -> str:
    """One field, profiled the way its kind deserves."""
    import pandas as pd

    series = frame[name]
    present = series.dropna()
    if present.empty:
        return "No values at this period."

    if kind == IDENTIFIER:
        distinct = int(present.nunique())
        duplicates = int(len(present) - distinct)
        said = f"{len(present):,} values, {distinct:,} distinct"
        return said + (f", {duplicates:,} repeated." if duplicates
                       else ", every one unique.")

    if kind == BOOLEAN:
        truthy = present.astype(str).str.lower().isin(
            {"true", "1", "y", "yes", "t"})
        return (f"{int(truthy.sum()):,} yes, "
                f"{int((~truthy).sum()):,} no.")

    if kind == DATE:
        text = present.astype(str)
        return f"{text.min()} to {text.max()}."

    if kind in (CATEGORY, TEXT):
        counts = present.astype(str).value_counts()
        top = counts.head(3)
        share = ", ".join(f"{k} {v / len(present) * 100:.0f}%"
                          for k, v in top.items())
        return f"{len(counts):,} distinct. Largest: {share}."

    numbers = pd.to_numeric(series, errors="coerce").dropna()
    if numbers.empty:
        return f"{present.nunique():,} distinct values, none numeric."

    if kind == ORDINAL_CLASS:
        counts = numbers.astype(int).value_counts().sort_index()
        parts = []
        for value, count in counts.items():
            share = count / len(numbers) * 100
            parts.append(f"{value}: {count:,} ({share:.0f}%)")
        return "; ".join(parts) + ". No average — a class has no midpoint."

    if kind == DURATION:
        bands = ((0, 0, "current"), (1, 30, "1-30"), (31, 60, "31-60"),
                 (61, 90, "61-90"), (91, 10 ** 9, "90+"))
        parts = [f"{label}: {int(((numbers >= low) & (numbers <= high)).sum()):,}"
                 for low, high, label in bands]
        return "; ".join(parts) + f". Median {_fmt(numbers.median())}."

    if kind in (RATE, RATIO):
        said = (f"median {_fmt(numbers.median())}, "
                f"p25 {_fmt(numbers.quantile(0.25))}, "
                f"p75 {_fmt(numbers.quantile(0.75))}")
        if kind == RATE and weight is not None and float(weight.sum()) > 0:
            aligned = weight.reindex(numbers.index).fillna(0.0)
            total = float(aligned.sum())
            if total > 0:
                weighted = float((numbers * aligned).sum() / total)
                said = (f"exposure-weighted average {_fmt(weighted)}, " + said)
        return said + "."

    return (f"total {_fmt(numbers.sum())}, mean {_fmt(numbers.mean())}, "
            f"median {_fmt(numbers.median())}, "
            f"range {_fmt(numbers.min())} to {_fmt(numbers.max())}.")


@dataclass
class Overview:
    """One dataset, described: what it is, what is in it, and its actual rows."""

    dataset: str = ""
    business_name: str = ""
    domain: str = ""
    period: str = ""
    summary: str = ""
    profile: list[dict[str, Any]] = field(default_factory=list)
    observations: list[dict[str, Any]] = field(default_factory=list)
    observation_columns: list[dict[str, Any]] = field(default_factory=list)
    shown: int = 0
    total_rows: int = 0
    refusal: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset": self.dataset, "business_name": self.business_name,
            "domain": self.domain, "period": self.period,
            "summary": self.summary, "profile": list(self.profile),
            "observations": list(self.observations),
            "observation_columns": list(self.observation_columns),
            "shown": self.shown, "total_rows": self.total_rows,
            "refusal": self.refusal,
        }


def overview(dataset: Any, *, period: str = "",
             limit: int = PREVIEW_ROWS) -> Overview:
    """A dataset overview, a semantic profile, and its first real rows.

    The rows are the point. A profile is a description and a description is
    something a reader has to take on trust; twenty actual observations are
    the data itself, and a reader can tell in five seconds whether it is what
    they expected.
    """
    out = Overview(dataset=dataset.name, business_name=dataset.business_name,
                   domain=dataset.domain, total_rows=int(dataset.row_count or 0))
    label = period or dataset.latest_period
    if period and dataset.periods and period not in dataset.periods:
        out.refusal = (
            f"{dataset.business_name} does not publish {period}. It publishes "
            f"{dataset.coverage.rstrip('.')}.")
        return out
    out.period = label

    try:
        frame = _read(dataset, label)
    except Exception as e:  # noqa: BLE001 - refuse with the reason
        logger.warning("Could not read %s at %s: %s", dataset.name, label, e)
        out.refusal = f"{dataset.business_name} could not be read: {e}"
        return out

    out.summary = _overview_sentence(dataset, label, len(frame))
    if frame.empty:
        out.refusal = (f"{dataset.business_name} has no rows at "
                       f"{label or 'any period'}.")
        return out

    import pandas as pd

    weight = None
    for candidate in ("ead", "exposure", "balance", "outstanding"):
        if candidate in frame.columns:
            weight = pd.to_numeric(frame[candidate], errors="coerce").fillna(0.0)
            break

    for found in dataset.fields:
        if found.name not in frame.columns:
            continue
        kind = profile_kind(found)
        try:
            said = _describe(kind, found.name, frame, weight)
        except Exception as e:  # noqa: BLE001 - one field must not lose the rest
            logger.debug("Could not profile %s.%s: %s",
                         dataset.name, found.name, e)
            said = "Could not be profiled."
        out.profile.append({
            "field": found.name,
            "label": found.business_name or found.name,
            "kind": kind.replace("_", " "),
            "profile": said,
            "missing": int(frame[found.name].isna().sum()),
        })

    shown = frame.head(max(1, min(limit, PREVIEW_ROWS_MAX)))
    out.shown = int(len(shown))
    out.observations = shown.astype(object).where(
        shown.notna(), None).to_dict("records")
    out.observation_columns = [
        {"name": f.name, "label": f.business_name or f.name,
         "semantic": "text" if profile_kind(f) in (IDENTIFIER, CATEGORY, TEXT,
                                                   BOOLEAN, DATE)
         else "number"}
        for f in dataset.fields if f.name in frame.columns]
    return out


def _overview_sentence(dataset: Any, period: str, rows: int) -> str:
    """What this dataset is, in the words a data steward would use."""
    grain = str(dataset.grain or "").rstrip(".")
    said = (f"{dataset.business_name} sits in {dataset.domain}. "
            f"{grain or 'One row per record'}, "
            f"{dataset.field_count} governed fields, "
            f"{int(dataset.row_count or 0):,} rows in total.")
    if dataset.periods:
        said += f" {dataset.coverage}"
        if period:
            said += (f" This is {period}, which holds {rows:,} "
                     f"{'row' if rows == 1 else 'rows'}.")
    else:
        said += " It carries no period of its own — it is reference data."
    if dataset.authoritative_for:
        said += (" It is the authoritative source for "
                 + ", ".join(dataset.authoritative_for) + ".")
    return said


# ------------------------------------------------------------ the answers


#: The words a sentence wraps a dataset name in. Stripped to leave the name.
_NAME_FRAME = re.compile(
    r"^\s*(?:please\s+)?(?:can you\s+)?"
    r"(?:tell me about|show me|describe|profile|open|what(?:'s| is) in)\s+"
    r"(?:the\s+)?(?P<name>.+?)"
    r"(?:\s+(?:dataset|data\s*set|table|book))?\s*[.?!]*\s*$",
    re.IGNORECASE)


def named_but_unknown(question: str) -> str:
    """A dataset this sentence names that the catalogue does not hold.

    Empty for everything else — including a sentence that names one it does
    hold, and a sentence that names none at all.
    """
    if not wants_dataset(question) or resolve(question) is not None:
        return ""
    match = _NAME_FRAME.match(" ".join((question or "").split()))
    if not match:
        return ""
    name = " ".join(match.group("name").split())
    if len(name) < 3 or bare_period(name):
        return ""
    # A reference is not a name.
    #
    # "Open the latest dataset" points at something the conversation has just
    # listed; it does not name a dataset the catalogue is missing. Treating it
    # as one turned a NAVIGATE into "there is no dataset called latest", which
    # is both wrong and unhelpful. A phrase made ONLY of referring words is a
    # reference; one that also carries a real word is a name.
    words = [word.strip(".,'\"") for word in name.lower().split()]
    if all(word in _NOT_A_NAME for word in words if word):
        return ""
    return name


#: Words that point at something rather than naming it: pronouns, ordinals,
#: determiners, and the generic nouns a reader uses for "the thing we are
#: looking at".
_NOT_A_NAME = frozenset({
    "a", "an", "the", "it", "this", "that", "them", "those", "these",
    "latest", "last", "newest", "first", "next", "previous", "prior",
    "earliest", "oldest", "recent", "current", "same", "other", "another",
    "one", "ones", "each", "every", "all", "any", "some", "more",
    "data", "dataset", "datasets", "catalogue", "table", "tables", "book",
    "rows", "row", "records", "everything", "anything", "something",
})


def unknown_dataset_result(question: str, reading: Any, name: str) -> Any:
    """Say the name is not one we hold, and offer the nearest that are.

    Falling through used to answer this with the whole catalogue: a reader who
    asked about one dataset by a name the bank uses internally was told how
    many datasets exist in total, which answers a question nobody asked and
    hides the fact that the name was not recognised.
    """
    from backend.metadata import service as ms
    from backend.orchestration.handlers import HandlerResult, _graph

    near = list(ms.search(name, limit=5))
    rows = [{"dataset": d.business_name, "governed_name": d.name,
             "domain": d.catalogue_domain or d.domain, "grain": d.grain,
             "periods": d.period_count, "rows": d.row_count} for d in near]
    if rows:
        answer = (f"There is no governed dataset called **{name}**. "
                  f"The {'closest is' if len(rows) == 1 else 'closest are'} "
                  + ", ".join(f"**{r['dataset']}**" for r in rows) + ".")
    else:
        answer = (f"There is no governed dataset called **{name}**, and "
                  "nothing in the catalogue is close to that name. Ask what "
                  "datasets are available to see the whole list.")
    return HandlerResult(
        answer=answer,
        title=f"No dataset called {name}",
        rows=rows,
        columns=[
            {"name": "dataset", "label": "Dataset", "semantic": "text"},
            {"name": "governed_name", "label": "Technical id",
             "semantic": "text"},
            {"name": "domain", "label": "Data domain", "semantic": "text"},
            {"name": "grain", "label": "One row per", "semantic": "text"},
            {"name": "periods", "label": "Periods", "semantic": "count",
             "decimals": 0, "align": "right"},
            {"name": "rows", "label": "Rows", "semantic": "count",
             "decimals": 0, "align": "right"},
        ],
        values={"matches": len(rows)},
        detail={"asked_for": name,
                "rule": ("A name the catalogue does not hold is said to be "
                         "unknown. It is never answered with a different "
                         "dataset, and never with the catalogue as a whole.")},
        graph=_graph(question, reading, consulted="Data Builder catalogue",
                     detail={"asked_for": name, "matches": len(rows)}),
        follow_ups=([f"Tell me about {rows[0]['dataset']}."] if rows else [])
        + ["What datasets do you have?"],
    )


def catalogue_result(question: str, reading: Any, context: Any = None) -> Any:
    """"What datasets do you have?" — the live catalogue, by domain."""
    from backend.orchestration.handlers import HandlerResult, _graph

    rows = catalogue_rows(context)
    domains = sorted({str(r["domain"]) for r in rows})
    return HandlerResult(
        answer=catalogue_answer(rows),
        title="Every governed dataset, by data domain",
        rows=rows,
        columns=list(CATALOGUE_COLUMNS),
        values={"datasets": len(rows), "domains": len(domains),
                "rows": sum(int(r["rows"] or 0) for r in rows)},
        detail={"domains": domains,
                "rule": ("Read from the live catalogue at the moment the "
                         "question was asked. Publish a period in Data "
                         "Builder and the next answer says so.")},
        graph=_graph(question, reading, consulted="Data Builder catalogue",
                     detail={"datasets": len(rows), "domains": domains}),
        follow_ups=([f"Tell me about {rows[0]['business_name']}."] if rows
                    else []) + [
            "Which domains hold the most data?",
            "What periods are published?",
        ],
    )


def overview_result(question: str, reading: Any, dataset: Any, *,
                    period: str = "", limit: int = PREVIEW_ROWS) -> Any:
    """One dataset: what it is, what is in it, and its first real rows."""
    from backend.orchestration.handlers import HandlerResult, _graph

    found = overview(dataset, period=period, limit=limit)
    if found.refusal and not found.profile:
        return HandlerResult(
            answer=found.refusal,
            graph=_graph(question, reading, consulted="Data Builder catalogue",
                         detail={"dataset": dataset.name, "period": period}))

    tables = []
    if found.observations:
        tables.append({
            "title": f"First {found.shown} rows"
                     + (f" at {found.period}" if found.period else ""),
            "because": ("The data itself rather than a description of it. A "
                        "profile is something a reader has to take on trust; "
                        "the rows are not."),
            "rows": found.observations,
            "columns": found.observation_columns,
        })

    return HandlerResult(
        answer=found.summary,
        title=f"What is in {found.business_name}, field by field",
        rows=found.profile,
        columns=list(PROFILE_COLUMNS),
        values={"fields": len(found.profile), "rows_shown": found.shown,
                "rows_total": found.total_rows},
        detail={"dataset": found.dataset, "domain": found.domain,
                "period": found.period,
                "rule": ("Every field is profiled the way its own kind "
                         "deserves. An identifier is counted and checked for "
                         "duplicates, never averaged; a class is distributed, "
                         "never averaged; a rate is weighted by exposure, "
                         "never summed.")},
        tables=tables,
        graph=_graph(question, reading, consulted="the governed lake",
                     detail={"dataset": found.dataset,
                             "period": found.period,
                             "fields": len(found.profile),
                             "rows_shown": found.shown}),
        execution="metadata",
        execution_label="Governed catalogue and published rows",
        follow_ups=[
            f"Show me 50 rows of {found.business_name}.",
            (f"Show {dataset.periods[-2]}."
             if len(dataset.periods) > 1 else "What periods are published?"),
            f"What fields are in {found.dataset}?",
        ],
    )


_PERIOD_ANYWHERE = re.compile(
    r"\b(Q[1-4]\s+\d{4}|\d{4}[-/]\d{1,2}|FY\s*\d{4})\b", re.IGNORECASE)

#: A sentence that is only a dataset name — "Corporate IFRS 9", "ifrs9_staging"
#: — with at most a courtesy word around it. Longer sentences that happen to
#: contain a dataset name are questions ABOUT the data, not requests to open it.
_ONLY_A_NAME = re.compile(
    r"^\s*(?:the\s+)?[A-Za-z0-9 _/&.-]{3,60}\s*(?:dataset|data|table)?\s*[.?!]?\s*$")

_ASKS_FOR_ROWS = re.compile(
    r"\b(?:rows?|records?|observations?|lines?|more)\b", re.IGNORECASE)


def period_in(question: str) -> str:
    """A period label named anywhere in the sentence, or empty."""
    match = _PERIOD_ANYWHERE.search(question or "")
    return " ".join(match.group(1).split()) if match else ""


def names_only_a_dataset(question: str) -> bool:
    """Whether the sentence is a dataset name and nothing else."""
    text = " ".join((question or "").strip().split())
    if not _ONLY_A_NAME.match(text):
        return False
    # A question is never just a name, whatever it looks like.
    return not re.search(r"\b(?:what|which|how|why|who|when|show me the top)\b",
                         text, re.IGNORECASE)


def asks_for_rows(question: str) -> bool:
    """Whether a follow-up is asking for more of the same rows."""
    return bool(_ASKS_FOR_ROWS.search(question or ""))
