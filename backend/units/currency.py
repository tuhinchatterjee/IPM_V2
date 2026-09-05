"""
What currency the numbers are in, and why the answer was "it depends".

The finding
-----------
Monetary figures were labelled `USD mn` in two hundred and forty-two places
while the Early Warning taxonomy declared `CURRENCY = "SAR"`. Both labels sat
over the same numbers.

Neither was a conversion. Nothing in this system has ever multiplied an amount
by an exchange rate. Tracing it back to the generator settles it:

    backend/corporate/universe.py, borrower financials:
        "currency": "SAR",
        "unit": "millions",

The corporate book is generated and reported in SAR millions. The `USD mn`
label was inherited from the source workbook of a much earlier retail dataset
and was never revisited. So this is a LABELLING defect, not a conversion one,
and correcting it changes no figure — which is the only reason it can be
corrected at all. Relabelling numbers that HAD been converted would be the
opposite of a fix.

Booking currency is a different fact
------------------------------------
A facility also carries a `currency` field: the currency the facility is
BOOKED in. 78% of this book is SAR, 17% USD, and the rest EUR and AED. That
field is a property of the facility, not of the reporting basis, and the two
were being conflated. A borrower whose largest facility is booked in USD still
has its exposure REPORTED in SAR millions like everything else.

Both facts are now named separately, and a test asserts no engine contract
declares a monetary unit other than the reporting one.
"""

from __future__ import annotations

from dataclasses import dataclass

#: The reporting currency of the corporate credit book. Every monetary figure
#: CreditProbe reports for this installation is expressed in it.
REPORTING_CURRENCY = "SAR"

#: And the scale those figures are expressed at.
REPORTING_SCALE = "millions"

#: The unit string that goes on a monetary output field, an axis label or a
#: column header. One constant, so a rename is one edit rather than 242.
MONEY_UNIT = f"{REPORTING_CURRENCY} mn"

#: The label a reader sees where the scale is already obvious from context.
CURRENCY_LABEL = REPORTING_CURRENCY

#: Booking currencies that appear on facilities. A facility's booking currency
#: is a fact about the facility; it does not change the reporting basis.
BOOKING_CURRENCIES: tuple[str, ...] = ("SAR", "USD", "EUR", "AED")

#: Prices quoted in their own market currency, which is a different fact from
#: the book's reporting basis. Brent is quoted in USD per barrel everywhere in
#: the world; expressing it in SAR would be inventing a convention nobody uses.
#: The global contract allows exactly this — "unless a source dataset
#: legitimately carries another currency and that distinction is explicit" —
#: and the distinction is explicit here.
MARKET_QUOTED_UNITS: tuple[str, ...] = ("USD/bbl", "USD/mt", "USD/oz",
                                        "USD/tonne", "SAR/USD", "USD/EUR")

#: Units that are NOT money and must never be given a currency. A ratio that
#: acquires a currency is the defect this list exists to prevent: DSCR is a
#: multiple, leverage is a multiple, PD is a percentage, and a Stage is a
#: category.
NON_MONETARY_UNITS: tuple[str, ...] = ("x", "%", "days", "notches", "count",
                                       "ratio", "pp", "bps", "category")

#: The labels that were wrong, and are searched for by the reconciliation test
#: so the defect cannot return quietly.
RETIRED_MONEY_UNITS: tuple[str, ...] = ("USD mn", "USD m", "USDmn", "$mn",
                                        "AED mn", "USD millions")


@dataclass(frozen=True)
class Basis:
    """The reporting basis, as something an answer can quote."""

    currency: str = REPORTING_CURRENCY
    scale: str = REPORTING_SCALE
    unit: str = MONEY_UNIT

    def statement(self) -> str:
        return (f"Every monetary figure is reported in {self.currency} "
                f"{self.scale}. A facility's own booking currency is recorded "
                "separately and does not change the reporting basis.")


BASIS = Basis()


def is_money(unit: str | None) -> bool:
    """Whether a unit string denotes an amount of money."""
    said = str(unit or "").strip()
    if not said:
        return False
    if said.lower() in {u.lower() for u in NON_MONETARY_UNITS}:
        return False
    if said in MARKET_QUOTED_UNITS or "/" in said:
        # A price PER something is a market quote, not an amount on the book.
        return False
    return any(code.lower() in said.lower()
               for code in ("sar", "usd", "eur", "aed", "mn", "million"))


def normalise(unit: str | None) -> str:
    """The reporting unit for anything monetary; everything else unchanged.

    A ratio stays a ratio. This is the function that must NEVER be applied
    blindly to every unit in a result — the whole point of section 19 of the
    global contract is that DSCR is a multiple and does not become SAR because
    a formatter was feeling helpful.
    """
    said = str(unit or "").strip()
    if not is_money(said):
        return said
    return MONEY_UNIT


def describe() -> dict[str, object]:
    return {
        "reporting_currency": REPORTING_CURRENCY,
        "reporting_scale": REPORTING_SCALE,
        "money_unit": MONEY_UNIT,
        "booking_currencies": list(BOOKING_CURRENCIES),
        "statement": BASIS.statement(),
        "conversion": ("No exchange-rate conversion is applied anywhere in "
                       "this installation. The book is generated and reported "
                       "on one basis, and the booking currency is a facility "
                       "attribute."),
    }


__all__ = ["BASIS", "BOOKING_CURRENCIES", "Basis", "CURRENCY_LABEL",
           "MARKET_QUOTED_UNITS",
           "MONEY_UNIT", "NON_MONETARY_UNITS", "REPORTING_CURRENCY",
           "REPORTING_SCALE", "RETIRED_MONEY_UNITS", "describe", "is_money",
           "normalise"]
