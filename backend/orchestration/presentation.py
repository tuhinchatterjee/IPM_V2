"""
What each column in a result IS, so it can be read without decoding it.

Two failures this fixes
-----------------------
**73391.774000000012.** A float printed at full precision in a table a credit
officer is reading. It is the right number and it looks like a bug, which is
worse than being slightly wrong in a way that looks deliberate.

**A column called `facility_delinquency_days_past_due` showing 0, under an
answer that says days past due rose.** Both true: the column is the OPENING
value and the change is in a column further right. But a reader sees a claim
and a zero beside it, and the only honest conclusions available are that the
product is wrong or that they have misunderstood it. The column is now called
"Days past due at Q2 2025", and the change sits next to it.

Where the rules come from
-------------------------
The semantic ontology, not the column name. A concept knows its unit, whether
it is ordinal, and whether it is a ratio; those decide the decimals and the
suffix. Name-based guessing is a fallback for the columns a plan derives —
shares, counts, changes — whose naming CreditProbe controls.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# Semantic types a renderer branches on.
IDENTITY = "identity"
TEXT = "text"
MONEY = "money"
PERCENT = "percent"
RATIO = "ratio"
COUNT = "count"
ORDINAL = "ordinal"
DAYS = "days"
PERIOD = "period"

#: Above this, a money figure is read in whole units. Two decimals on a
#: hundred-million balance is noise pretending to be precision.
WHOLE_UNITS_ABOVE = 1000.0


@dataclass
class Column:
    """One column, as something to render rather than a name and a type."""

    name: str
    label: str
    semantic: str = TEXT
    unit: str = ""
    currency: str = ""
    #: The scale the figures are already in — "mn" for a book kept in millions.
    scale: str = ""
    decimals: int = 2
    align: str = "left"
    #: True for the column that names the thing each row is about.
    is_identity: bool = False
    #: Why this column exists, where it is not obvious: an opening value, a
    #: denominator, a derived change.
    role: str = ""
    origin: str = ""
    #: Where this column belongs in the answer, lowest first. See `RANK_*`.
    rank: int = 40
    #: True where the column is lineage or plumbing rather than an answer.
    #: Not removed — a hidden column is one a reader can turn on, and a
    #: deleted one is a question they cannot ask.
    hidden: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "label": self.label,
                "semantic": self.semantic, "unit": self.unit,
                "currency": self.currency, "scale": self.scale,
                "decimals": self.decimals, "align": self.align,
                "is_identity": self.is_identity, "role": self.role,
                "origin": self.origin, "rank": self.rank,
                "hidden": self.hidden}


# ---------------------------------------------------------------------------
# Naming
# ---------------------------------------------------------------------------

_IDENTITY_COLUMNS = ("customer_id", "account_id", "borrower_id",
                     "borrower_name", "customer_name")

_KNOWN_LABELS = {
    "customer_id": "Customer",
    "account_id": "Facility",
    "borrower_id": "Borrower",
    "borrower_name": "Borrower",
    "sector": "Sector",
    "region": "Region",
    "segment": "Segment",
    "period": "Period",
    "ifrs9_stage": "IFRS 9 stage",
    "internal_grade": "Internal grade",
    "change_pp": "Change (pp)",
    "opening_share_pct": "Share at opening",
    "closing_share_pct": "Share at closing",
    "opening_qualified": "Qualifying at opening",
    "closing_qualified": "Qualifying at closing",
    "opening_total": "Total at opening",
    "closing_total": "Total at closing",
}

# ---------------------------------------------------------------------------
# Where a column belongs in the answer
# ---------------------------------------------------------------------------
#
# A result's column order comes out of the compiler, which orders by how the
# query was built. That is the wrong order for reading. "For each rating grade,
# show average ECL coverage, average leverage and average DSCR" put the grade
# fourth, because the grade was the last thing the plan grouped by — and a
# table whose first column is not what the rows are about is a table nobody can
# scan.
#
# The presentation schema is therefore separate from the computational one. The
# question decides: what the rows are ABOUT comes first, then what was ASKED
# for, then what it is being compared with, then what was derived from those,
# then context, and lineage last and hidden.

RANK_SUBJECT = 0      # what each row is about: the grouping or the entity
RANK_PERIOD = 5       # the period, where the rows are a time series
RANK_PRIMARY = 10     # the measure the question asked for
RANK_COMPARISON = 20  # a second measure, or the same one at another date
RANK_DERIVED = 30     # changes, shares, ranks computed from the above
RANK_CONTEXT = 40     # attributes that qualify a row without answering it
RANK_LINEAGE = 90     # plumbing: as-of stamps, denominators, carried keys

_CHANGE = re.compile(r"^(?P<base>.+?)_change(?P<pct>_pct)?$")
_CLOSING = re.compile(r"^closing_(?P<base>.+)$")
_SHARE = re.compile(r"^(?P<base>.+?)_share_pct$")
_POPULATION = re.compile(r"^(?P<base>.+?)_population$")
_COUNT = re.compile(r"^(?P<base>.+?)_count$")


def _humanise(name: str) -> str:
    cleaned = str(name or "").replace("_", " ").strip()
    return cleaned[:1].upper() + cleaned[1:] if cleaned else ""


#: Dataset prefixes stripped before a column is named, set for the duration of
#: one contract build. A joined column arrives as `customer_ratings_internal_grade`
#: because that is what keeps it unique across two sources; "Customer ratings
#: internal grade" is not what anybody calls it, and the prefix is noise in
#: every row of every table.
_PREFIXES: list[str] = []


def _unprefixed(name: str) -> str:
    lowered = str(name or "").lower()
    for prefix in _PREFIXES:
        if lowered.startswith(prefix) and len(lowered) > len(prefix):
            return lowered[len(prefix):]
    return lowered


def contract(runtime: Any, build: Any = None) -> list[dict[str, Any]]:
    """A display contract for every column the result carries."""
    try:
        return [c.to_dict() for c in _columns(runtime, build)]
    except Exception as e:  # noqa: BLE001 - a rendering hint must not lose an answer
        logger.warning("Could not build the presentation contract: %s", e)
        return []


def _columns(runtime: Any, build: Any) -> list[Column]:
    opening = str(getattr(build, "opening", "") or "")
    closing = str(getattr(build, "closing", "") or "")
    by_field = _concepts(build)
    two_period = bool(opening and closing)

    _PREFIXES[:] = sorted(
        (f"{str(d).lower()}_" for d in (getattr(build, "datasets", None) or [])),
        key=len, reverse=True)
    try:
        out: list[Column] = []
        for entry in (getattr(runtime, "columns", []) or []):
            name = str(entry.get("name") if isinstance(entry, dict)
                       else getattr(entry, "name", entry))
            origin = str(entry.get("origin", "") if isinstance(entry, dict) else "")
            out.append(_column(name, origin, by_field, opening, closing,
                               two_period))
        _place(out, build)
        return out
    finally:
        _PREFIXES.clear()


def _place(columns: list[Column], build: Any) -> None:
    """Rank each column by what the QUESTION made it, not by how it was built.

    Three things the compiler's order gets wrong, in the order they annoy a
    reader:

    **The subject is not first.** A result grouped by rating grade puts the
    grade wherever the GROUP happened to emit it. What the rows are about
    belongs in column one, always.

    **The measure that was asked for is not distinguished** from the two that
    were asked for alongside it. The first concept the question named is the
    one the answer is about.

    **Plumbing looks like an answer.** A borrower name carried through an
    aggregate so a filter could be applied is not a column in a sector-level
    table; it is one value out of thousands, and showing it invites a reader to
    conclude the sector total belongs to that borrower.
    """
    dimension = str(getattr(build, "dimension", "") or "").lower()
    grain = str(getattr(build, "grain", "") or "").lower()
    matches = list(getattr(build, "matches", None) or [])
    measures = [str(getattr(m, "field", "")).lower() for m in matches]
    primary = measures[0] if measures else ""
    aggregated = bool(dimension) and dimension not in _IDENTITY_COLUMNS

    for column in columns:
        lowered = column.name.lower()

        if dimension and lowered == dimension:
            column.rank = RANK_SUBJECT
            column.is_identity = True
            continue

        if lowered in _IDENTITY_COLUMNS:
            # An identity column in a result grouped by something else is a
            # carried value, not a subject. Kept, so a reader can turn it on and
            # see what it is; hidden, so nobody reads it as the answer.
            if aggregated:
                column.rank = RANK_LINEAGE
                column.hidden = True
                column.is_identity = False
                column.role = column.role or ("carried through the aggregate so "
                                              "a filter could be applied")
            elif grain and not lowered.startswith(grain[:4]) and any(
                    c.is_identity and c.name.lower() != lowered
                    for c in columns):
                column.rank = RANK_SUBJECT + 1
            continue

        if column.rank != RANK_CONTEXT:
            # Already placed by its shape — a change, a share, a closing value.
            continue

        if primary and lowered == primary:
            column.rank = RANK_PRIMARY
        elif lowered in measures:
            column.rank = RANK_COMPARISON
        elif column.semantic in (MONEY, PERCENT, RATIO, COUNT, DAYS, ORDINAL):
            column.rank = RANK_COMPARISON + 1


def _column(name: str, origin: str, by_field: dict[str, Any],
            opening: str, closing: str, two_period: bool) -> Column:
    lowered = name.lower()

    if lowered in _IDENTITY_COLUMNS:
        return Column(name=name, label=_KNOWN_LABELS.get(lowered, _humanise(name)),
                      semantic=IDENTITY, is_identity=True, origin=origin,
                      decimals=0, rank=RANK_SUBJECT)

    if lowered in ("period", "_asof_period") or lowered.endswith("_period"):
        return Column(name=name, label=_KNOWN_LABELS.get(lowered, _humanise(name)),
                      semantic=PERIOD, origin=origin, decimals=0,
                      rank=RANK_LINEAGE if lowered.startswith("_") else RANK_PERIOD,
                      hidden=lowered.startswith("_"))

    change = _CHANGE.match(lowered)
    if change:
        base = change.group("base")
        measure = _label_of(base, by_field)
        if change.group("pct"):
            return Column(name=name, label=f"Change in {measure} (%)",
                          semantic=PERCENT, unit="%", decimals=2,
                          align="right", role="the change, as a percentage",
                          origin=origin, rank=RANK_DERIVED)
        return Column(name=name, label=f"Change in {measure}",
                      **_numeric(base, by_field),
                      role="closing minus opening", origin=origin,
                      rank=RANK_DERIVED)

    closing_match = _CLOSING.match(lowered)
    if closing_match:
        base = closing_match.group("base")
        measure = _label_of(base, by_field)
        return Column(name=name,
                      label=(f"{measure} at {closing}" if closing
                             else f"{measure} (closing)"),
                      **_numeric(base, by_field),
                      role="the closing position", origin=origin,
                      rank=RANK_COMPARISON)

    share = _SHARE.match(lowered)
    if share:
        return Column(name=name,
                      label=f"{_label_of(share.group('base'), by_field)} share",
                      semantic=PERCENT, unit="%", decimals=2, align="right",
                      role="this row as a percentage of the population",
                      origin=origin, rank=RANK_DERIVED)

    population = _POPULATION.match(lowered)
    if population:
        base = population.group("base")
        return Column(name=name,
                      label=f"{_label_of(base, by_field)} — population total",
                      **_numeric(base, by_field),
                      role="the denominator the share is taken over",
                      origin=origin, rank=RANK_LINEAGE, hidden=True)

    counted = _COUNT.match(lowered)
    if counted:
        return Column(name=name,
                      label=f"{_humanise(counted.group('base'))}s",
                      semantic=COUNT, decimals=0, align="right",
                      role="a distinct count", origin=origin,
                      rank=RANK_PRIMARY)

    if lowered in _KNOWN_LABELS:
        column = Column(name=name, label=_KNOWN_LABELS[lowered], origin=origin,
                        **_numeric(lowered, by_field))
        if lowered in ("change_pp",):
            column.semantic, column.unit, column.decimals = PERCENT, "pp", 2
        return column

    # A bare measure in a two-period plan is the OPENING value. Labelling it
    # with the measure alone is what put a zero beside a claim that the figure
    # had risen, and left a reader with no honest conclusion available.
    label = _label_of(_unprefixed(lowered), by_field)
    if two_period and _is_measure(lowered, by_field):
        return Column(name=name, label=f"{label} at {opening}",
                      **_numeric(lowered, by_field),
                      role="the opening position", origin=origin,
                      rank=RANK_COMPARISON)

    return Column(name=name, label=label, origin=origin,
                  **_numeric(lowered, by_field))


# ---------------------------------------------------------------------------
# Semantics from the ontology
# ---------------------------------------------------------------------------


def _concepts(build: Any) -> dict[str, Any]:
    """Every measure the plan reads, keyed by the column it lands in."""
    out: dict[str, Any] = {}
    for match in (getattr(build, "matches", None) or []):
        try:
            out[str(match.field).lower()] = match.concept
        except Exception:  # noqa: BLE001
            continue
    return out


def _concept_for(base: str, by_field: dict[str, Any]) -> Any:
    if base in by_field:
        return by_field[base]
    # A joined column is prefixed with its dataset — `ifrs9_staging_total_ecl`.
    for field_name, concept in by_field.items():
        if base.endswith(f"_{field_name}") or base == field_name:
            return concept
    return None


def _label_of(base: str, by_field: dict[str, Any]) -> str:
    concept = _concept_for(base, by_field)
    if concept is not None:
        label = str(getattr(concept, "label", "") or "")
        if label:
            return label[:1].upper() + label[1:]
    unprefixed = _unprefixed(base)
    return (_KNOWN_LABELS.get(unprefixed)
            or _humanise(unprefixed))


def _is_measure(base: str, by_field: dict[str, Any]) -> bool:
    return _concept_for(base, by_field) is not None


def _numeric(base: str, by_field: dict[str, Any]) -> dict[str, Any]:
    """Unit, decimals and alignment for a numeric column, from its concept."""
    from backend.semantics import ontology

    concept = _concept_for(base, by_field)
    if concept is None:
        return {"semantic": TEXT, "align": "left", "decimals": 2}

    contract_of = ontology.contract(getattr(concept, "id", ""))
    unit = str(getattr(concept, "unit", "") or
               (contract_of.unit if contract_of else ""))

    if getattr(concept, "is_ordinal", False):
        return {"semantic": ORDINAL, "unit": "", "decimals": 0,
                "align": "right"}
    if unit == "days":
        return {"semantic": DAYS, "unit": "days", "decimals": 0,
                "align": "right"}
    if unit in ("%", "pp"):
        return {"semantic": PERCENT, "unit": unit, "decimals": 2,
                "align": "right"}
    if unit == "x":
        return {"semantic": RATIO, "unit": "x", "decimals": 2, "align": "right"}
    if "mn" in unit or "USD" in unit or "SAR" in unit:
        currency = "USD" if "USD" in unit else ("SAR" if "SAR" in unit else "")
        # One decimal is the hint, not the rule: money precision depends on
        # the magnitude of the individual figure, which a column contract
        # cannot know. `figures` decides per value; this is what a renderer
        # falls back to when it has nothing else.
        return {"semantic": MONEY, "unit": unit, "currency": currency,
                "scale": "mn" if "mn" in unit else "", "decimals": 1,
                "align": "right"}
    return {"semantic": TEXT, "unit": unit, "decimals": 2, "align": "left"}


# ---------------------------------------------------------------------------
# Rendering, for anything that needs a string rather than a contract
# ---------------------------------------------------------------------------


def render(value: Any, column: dict[str, Any] | Column,
           *, threshold: float | None = None, side: str = "") -> str:
    """One value, formatted the way its column says it should be.

    A thin adapter now. Every rule about decimals, separators, suffixes and
    thresholds lives in `figures`, so a number in a sentence, the same number
    in the table and the same number in a tooltip cannot disagree.
    """
    from backend.orchestration import figures

    spec = figures.Spec.from_column(column)
    if threshold is not None:
        spec = figures.Spec(semantic=spec.semantic, unit=spec.unit,
                            currency=spec.currency, scale=spec.scale,
                            decimals=spec.decimals, threshold=threshold,
                            side=side)
    return figures.text(value, spec)


def in_sentence(label: str) -> str:
    """A column label as it reads mid-sentence.

    Three rules, each of which fixed something a reader would have noticed.
    An acronym keeps its capitals — "ECL coverage", never "ecl coverage". A
    label carrying a period keeps the period's — "expected credit loss at Q2
    2025", never "at q2 2025". And an ordinary word is lowered, because a
    capitalised noun in the middle of a sentence reads as a proper name.
    """
    text = str(label or "").strip()
    if not text:
        return text

    def lower_word(word: str) -> str:
        if word.isupper() or any(c.isdigit() for c in word):
            return word
        return word.lower()

    words = text.split()
    first = words[0]
    if first.isupper() or any(c.isdigit() for c in first):
        head = first
    else:
        head = first[:1].lower() + first[1:]
    return " ".join([head, *(lower_word(w) if w[:1].isupper() and not w.isupper()
                             else w for w in words[1:])])


def schema(runtime: Any, build: Any = None) -> list[dict[str, Any]]:
    """The columns in reading order, with lineage marked rather than removed.

    What the table renders from. `contract` still returns them in the order the
    runtime produced, because the rows are keyed by name and nothing downstream
    should have to care; this is the order a person reads them in.
    """
    try:
        ordered = sorted(_columns(runtime, build),
                         key=lambda c: (c.rank, c.hidden))
        return [c.to_dict() for c in ordered]
    except Exception as e:  # noqa: BLE001 - an ordering hint must not lose an answer
        logger.warning("Could not order the presentation schema: %s", e)
        return contract(runtime, build)


__all__ = ["COUNT", "DAYS", "IDENTITY", "MONEY", "ORDINAL", "PERCENT",
           "PERIOD", "RANK_COMPARISON", "RANK_CONTEXT", "RANK_DERIVED",
           "RANK_LINEAGE", "RANK_PERIOD", "RANK_PRIMARY", "RANK_SUBJECT",
           "RATIO", "TEXT", "WHOLE_UNITS_ABOVE", "Column", "contract",
           "in_sentence", "render", "schema"]
