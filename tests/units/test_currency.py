"""
One reporting basis, and a guard that stops the old label coming back.

Monetary figures carried `USD mn` in 242 places while the Early Warning
taxonomy declared SAR. Neither label was a conversion — nothing here has ever
multiplied an amount by an exchange rate — so correcting it changed no figure.
These tests hold the correction in place, and hold the line that matters more:
a ratio must never acquire a currency.
"""

from __future__ import annotations

import pathlib

import pytest

from backend.units import currency as cx

ROOT = pathlib.Path(__file__).resolve().parents[2]

#: Where a stray label would actually reach a reader. The currency module
#: itself names the retired labels on purpose, and the acceptance fixtures
#: record what an older run produced.
SEARCHED = ("backend", "frontend/src", "scripts")
EXEMPT = {"backend/units/currency.py"}


def _sources() -> list[pathlib.Path]:
    out: list[pathlib.Path] = []
    for area in SEARCHED:
        base = ROOT / area
        if not base.exists():
            continue
        for suffix in ("*.py", "*.ts", "*.tsx"):
            out.extend(p for p in base.rglob(suffix)
                       if "node_modules" not in p.parts
                       and "__pycache__" not in p.parts)
    return out


class TestTheReportingBasis:
    def test_there_is_one_reporting_currency(self) -> None:
        assert cx.REPORTING_CURRENCY == "SAR"
        assert cx.MONEY_UNIT == "SAR mn"

    def test_the_early_warning_taxonomy_agrees(self) -> None:
        # The two declarations that disagreed. They are now one fact.
        from backend.early_warning import taxonomy as tx

        assert tx.CURRENCY == cx.REPORTING_CURRENCY

    def test_the_generator_declares_the_same_basis(self) -> None:
        source = (ROOT / "backend/corporate/universe.py").read_text(
            encoding="utf-8")
        assert '"currency": "SAR"' in source
        assert '"unit": "millions"' in source

    def test_the_basis_states_that_nothing_was_converted(self) -> None:
        described = cx.describe()
        assert "No exchange-rate conversion" in described["conversion"]


class TestTheRetiredLabelIsGone:
    @pytest.mark.parametrize("retired", ["USD mn", "USD millions"])
    def test_no_source_file_carries_it(self, retired: str) -> None:
        offenders = []
        for path in _sources():
            relative = path.relative_to(ROOT).as_posix()
            if relative in EXEMPT:
                continue
            body = path.read_text(encoding="utf-8", errors="ignore")
            # "(USD mn)" inside a parenthesised column header is the literal
            # header of the legacy source workbook. It is a DATA KEY, not a
            # display unit, and renaming it breaks the lookup — which is the
            # difference between correcting a label and renaming a number.
            body = body.replace(f"({retired})", "")
            if retired in body:
                offenders.append(relative)
        assert not offenders, (
            f"{retired!r} is back in {offenders}. The corporate book is "
            "reported in SAR millions; use backend.units.currency.MONEY_UNIT.")

    def test_no_engine_contract_declares_another_money_unit(self) -> None:
        import backend.engine.functions  # noqa: F401  (registers the contracts)
        from backend.engine import registry

        wrong = []
        for contract in registry.get_registry().contracts():
            for field in getattr(contract, "outputs", ()):
                unit = getattr(field, "unit", None)
                if unit and cx.is_money(unit) and unit != cx.MONEY_UNIT:
                    wrong.append(f"{contract.id}.{field.name}={unit}")
        assert not wrong, f"contracts declare a foreign money unit: {wrong}"


class TestRatiosStayRatios:
    """Section 19 of the global contract, as something that can fail."""

    @pytest.mark.parametrize("unit", ["x", "%", "days", "pp", "count",
                                      "ratio", "notches", "category"])
    def test_a_non_monetary_unit_is_not_money(self, unit: str) -> None:
        assert not cx.is_money(unit)
        assert cx.normalise(unit) == unit

    @pytest.mark.parametrize("unit", ["SAR mn", "USD mn", "AED mn",
                                      "EUR millions"])
    def test_a_monetary_unit_normalises_to_the_reporting_one(
            self, unit: str) -> None:
        assert cx.is_money(unit)
        assert cx.normalise(unit) == cx.MONEY_UNIT

    def test_an_empty_unit_is_not_money(self) -> None:
        assert not cx.is_money("")
        assert not cx.is_money(None)

    def test_dscr_is_a_multiple_in_the_ontology(self) -> None:
        from backend.semantics import ontology

        source = pathlib.Path(ontology.__file__).read_text(encoding="utf-8")
        # A ratio that acquired a currency is the defect this guards.
        for line in source.splitlines():
            if "dscr" in line.lower() and "unit=" in line:
                assert '"x"' in line or "'x'" in line or "ratio" in line.lower(), (
                    f"DSCR declared with a currency unit: {line.strip()}")


class TestAMarketQuoteIsNotTheBook:
    """A price per barrel is not an amount on the balance sheet."""

    @pytest.mark.parametrize("unit", ["USD/bbl", "USD/mt", "SAR/USD"])
    def test_a_quoted_price_keeps_its_own_currency(self, unit: str) -> None:
        assert not cx.is_money(unit)
        assert cx.normalise(unit) == unit

    def test_brent_is_still_quoted_in_dollars_a_barrel(self) -> None:
        import backend.engine.functions  # noqa: F401
        from backend.engine import registry

        contract = registry.get_registry().contract("macroeconomic_context")
        brent = next(f for f in contract.outputs if f.name == "brent_usd_bbl")
        assert brent.unit == "USD/bbl", (
            "Brent is quoted in USD per barrel worldwide; converting it to the "
            "reporting currency would invent a convention nobody uses")


class TestBookingCurrencyIsADifferentFact:
    def test_the_book_carries_several_booking_currencies(self) -> None:
        assert set(cx.BOOKING_CURRENCIES) >= {"SAR", "USD"}

    def test_a_booking_currency_does_not_change_the_reporting_basis(self) -> None:
        assert cx.BASIS.currency == "SAR"
        assert "booking currency is recorded separately" in cx.BASIS.statement()

    def test_the_data_actually_carries_them(self) -> None:
        import duckdb

        pattern = str(ROOT / "data/analytics/corporate_borrower_360/**/*.parquet")
        try:
            rows = duckdb.connect().execute(
                f"select distinct currency from read_parquet('{pattern}')"
            ).fetchall()
        except Exception as exc:  # noqa: BLE001 - the lake may be absent
            pytest.skip(f"the data lake is not available: {exc}")
        found = {str(r[0]) for r in rows if r[0]}
        assert found <= set(cx.BOOKING_CURRENCIES), (
            f"the book carries booking currencies the module does not name: "
            f"{found - set(cx.BOOKING_CURRENCIES)}")


class TestWhatIfUsesTheSameBasis:
    def test_the_scenario_engine_reports_in_the_governed_currency(self) -> None:
        from backend.whatif import engine as wf

        assert wf.CURRENCY == cx.REPORTING_CURRENCY
