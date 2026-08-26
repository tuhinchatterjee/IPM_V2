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

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "label": self.label,
                "semantic": self.semantic, "unit": self.unit,
                "currency": self.currency, "scale": self.scale,
                "decimals": self.decimals, "align": self.align,
                "is_identity": self.is_identity, "role": self.role,
                "origin": self.origin}


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

_CHANGE = re.compile(r"^(?P<base>.+?)_change(?P<pct>_pct)?$")
_CLOSING = re.compile(r"^closing_(?P<base>.+)$")
_SHARE = re.compile(r"^(?P<base>.+?)_share_pct$")
_POPULATION = re.compile(r"^(?P<base>.+?)_population$")
_COUNT = re.compile(r"^(?P<base>.+?)_count$")


def _humanise(name: str) -> str:
    cleaned = str(name or "").replace("_", " ").strip()
    return cleaned[:1].upper() + cleaned[1:] if cleaned else ""


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

    out: list[Column] = []
    for entry in (getattr(runtime, "columns", []) or []):
        name = str(entry.get("name") if isinstance(entry, dict)
                   else getattr(entry, "name", entry))
        origin = str(entry.get("origin", "") if isinstance(entry, dict) else "")
        out.append(_column(name, origin, by_field, opening, closing, two_period))
    return out


def _column(name: str, origin: str, by_field: dict[str, Any],
            opening: str, closing: str, two_period: bool) -> Column:
    lowered = name.lower()

    if lowered in _IDENTITY_COLUMNS:
        return Column(name=name, label=_KNOWN_LABELS.get(lowered, _humanise(name)),
                      semantic=IDENTITY, is_identity=True, origin=origin,
                      decimals=0)

    if lowered in ("period", "_asof_period") or lowered.endswith("_period"):
        return Column(name=name, label=_KNOWN_LABELS.get(lowered, _humanise(name)),
                      semantic=PERIOD, origin=origin, decimals=0)

    change = _CHANGE.match(lowered)
    if change:
        base = change.group("base")
        measure = _label_of(base, by_field)
        if change.group("pct"):
            return Column(name=name, label=f"Change in {measure} (%)",
                          semantic=PERCENT, unit="%", decimals=1,
                          align="right", role="the change, as a percentage",
                          origin=origin)
        return Column(name=name, label=f"Change in {measure}",
                      **_numeric(base, by_field),
                      role="closing minus opening", origin=origin)

    closing_match = _CLOSING.match(lowered)
    if closing_match:
        base = closing_match.group("base")
        measure = _label_of(base, by_field)
        return Column(name=name,
                      label=(f"{measure} at {closing}" if closing
                             else f"{measure} (closing)"),
                      **_numeric(base, by_field),
                      role="the closing position", origin=origin)

    share = _SHARE.match(lowered)
    if share:
        return Column(name=name,
                      label=f"{_label_of(share.group('base'), by_field)} share",
                      semantic=PERCENT, unit="%", decimals=1, align="right",
                      role="this row as a percentage of the population",
                      origin=origin)

    population = _POPULATION.match(lowered)
    if population:
        base = population.group("base")
        return Column(name=name,
                      label=f"{_label_of(base, by_field)} — population total",
                      **_numeric(base, by_field),
                      role="the denominator the share is taken over",
                      origin=origin)

    counted = _COUNT.match(lowered)
    if counted:
        return Column(name=name,
                      label=f"{_humanise(counted.group('base'))}s",
                      semantic=COUNT, decimals=0, align="right",
                      role="a distinct count", origin=origin)

    if lowered in _KNOWN_LABELS:
        column = Column(name=name, label=_KNOWN_LABELS[lowered], origin=origin,
                        **_numeric(lowered, by_field))
        if lowered in ("change_pp",):
            column.semantic, column.unit, column.decimals = PERCENT, "pp", 2
        return column

    # A bare measure in a two-period plan is the OPENING value. Labelling it
    # with the measure alone is what put a zero beside a claim that the figure
    # had risen, and left a reader with no honest conclusion available.
    label = _label_of(lowered, by_field)
    if two_period and _is_measure(lowered, by_field):
        return Column(name=name, label=f"{label} at {opening}",
                      **_numeric(lowered, by_field),
                      role="the opening position", origin=origin)

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
    return _humanise(base)


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
        return {"semantic": PERCENT, "unit": unit, "decimals": 1,
                "align": "right"}
    if unit == "x":
        return {"semantic": RATIO, "unit": "x", "decimals": 2, "align": "right"}
    if "mn" in unit or "USD" in unit or "SAR" in unit:
        currency = "USD" if "USD" in unit else ("SAR" if "SAR" in unit else "")
        return {"semantic": MONEY, "unit": unit, "currency": currency,
                "scale": "mn" if "mn" in unit else "", "decimals": 0,
                "align": "right"}
    return {"semantic": TEXT, "unit": unit, "decimals": 2, "align": "left"}


# ---------------------------------------------------------------------------
# Rendering, for anything that needs a string rather than a contract
# ---------------------------------------------------------------------------


def render(value: Any, column: dict[str, Any] | Column) -> str:
    """One value, formatted the way its column says it should be.

    Used by the deterministic narrative and by anything that has to produce a
    figure as text. The browser renders from the same contract, so a number in
    a sentence and the same number in the table agree.
    """
    spec = column.to_dict() if isinstance(column, Column) else dict(column or {})
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if not isinstance(value, (int, float)):
        return str(value)

    number = float(value)
    decimals = int(spec.get("decimals", 2))
    if spec.get("semantic") == MONEY and abs(number) < WHOLE_UNITS_ABOVE:
        decimals = max(decimals, 2)

    text = f"{number:,.{decimals}f}"
    unit = str(spec.get("unit") or "")
    if unit == "%":
        return f"{text}%"
    if unit:
        return f"{text} {unit}"
    return text


__all__ = ["COUNT", "DAYS", "IDENTITY", "MONEY", "ORDINAL", "PERCENT",
           "PERIOD", "RATIO", "TEXT", "WHOLE_UNITS_ABOVE", "Column",
           "contract", "render"]
