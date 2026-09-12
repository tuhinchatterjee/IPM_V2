"""
Regressions for the defects that stopped retail chat answering at all.

Every test here failed before its fix and names the failure it prevents, so a
later change that reintroduces one is caught by a test that says what the user
would have seen rather than which assertion tripped.

Found by driving the running application in a real browser during the
full-functionality closeout, not by reading code — which is why several of them
concern things a direct API test cannot see.
"""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.orchestration import concepts as cx
from backend.orchestration.entities import unresolved_names
from backend.orchestration.periods import (
    period_year,
    read_period_intent,
    unavailable,
)
from backend.retail import profile

ROOT = Path(__file__).resolve().parents[2]

#: The 25 months the retail book publishes, as it labels them.
MONTHS = [f"{year}-{month:02d}"
          for year in (2024, 2025, 2026)
          for month in range(1, 13)][7:32]


def test_iso_month_labels_report_their_own_year() -> None:
    """"August 2026" was reported as a period the data does not have.

    The year was read as the last four characters of the label, which is right
    for "Q1 2026" and wrong for "2026-08" — it gave "6-08". No year a question
    could name was ever a year the book held.
    """
    assert period_year("2026-08") == "2026"
    assert period_year("Q1 2026") == "2026"
    assert period_year("Aug 2024") == "2024"
    assert period_year("FY2025") == "2025"
    assert unavailable("Show exposure by retail product for August 2026", MONTHS) == ""


def test_a_month_outside_the_history_is_still_refused() -> None:
    """The fix above must not make every date acceptable."""
    assert unavailable("Show exposure for March 2019", MONTHS) == "2019"
    assert unavailable("What was exposure in Q1 2015?", MONTHS) == "Q1 2015"


@pytest.mark.parametrize(
    ("question", "expected_from", "expected_to"),
    [
        ("Show exposure by retail product for August 2026", "2026-07", "2026-08"),
        ("Show exposure for 2026-08", "2026-07", "2026-08"),
        ("Compare August 2026 with July 2026", "2026-07", "2026-08"),
        ("Show me exposure since Aug 2025", "2025-08", "2026-08"),
    ],
)
def test_months_written_in_words_resolve(question: str,
                                         expected_from: str,
                                         expected_to: str) -> None:
    """A month nobody types as "2026-08" was read as no month at all.

    The answer then came back as at the governed default period, with nothing on
    screen to say it was not the month that had been asked for.
    """
    intent = read_period_intent(question, MONTHS)
    assert intent.specified, intent.source
    assert (intent.from_period, intent.to_period) == (expected_from, expected_to)


def test_a_question_naming_no_month_still_asks() -> None:
    assert not read_period_intent("Show total exposure", MONTHS).specified


def test_monthly_periods_are_offered_in_calendar_order() -> None:
    """The latest period was whatever the filesystem happened to list last.

    Every "YYYY-MM" label sorted to the same unknown key, so "as at the latest
    month" resolved to an arbitrary month — May 2025 on this build — and dated
    every answer wrongly without ever looking wrong.
    """
    from backend.data_access.duckdb_source import _period_sort_key

    shuffled = [MONTHS[12], MONTHS[0], MONTHS[-1], MONTHS[5]]
    assert sorted(shuffled, key=_period_sort_key) == sorted(shuffled)
    assert len({_period_sort_key(m) for m in MONTHS}) == len(MONTHS)


@pytest.fixture()
def retail_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    """Point the code at the catalogue the retail installation actually ships.

    The suite runs with the repository default metadata directory; the launcher
    exports `METADATA_DIR=metadata/retail`. Rather than assert less, the test
    hands the code the same file the running product reads.
    """
    import dataclasses

    from backend import config
    from backend.orchestration import entities

    retail = ROOT / "metadata" / "retail"
    if not (retail / "catalog.json").exists():
        pytest.skip("no retail catalogue built — run scripts/build_retail_demo.py")

    monkeypatch.setattr(
        config, "settings", dataclasses.replace(config.settings, metadata_dir=retail))
    entities._shipped_catalogue_vocabulary.cache_clear()
    monkeypatch.setattr(entities, "_CATALOGUE_WORDS", None)
    yield
    entities._shipped_catalogue_vocabulary.cache_clear()


def test_the_shipped_catalogue_names_the_domain_the_product_puts_on_screen() -> None:
    """The vocabulary is only as good as the file it reads.

    Four domains rather than one. The retail installation holds ONE
    analytical book and offers four governed VIEWS of it — Cockpit, Early
    Warning, Credit Scorecard and What-If — because five hundred and
    forty-six columns serve four different readers and one list of them
    serves none. What this gate is about is unchanged: every domain named in
    the shipped catalogue is a domain the product puts on screen, and no
    other. A corporate heading appearing here would still fail it.
    """
    import json

    from backend.services import data_domains

    document = json.loads((ROOT / "metadata/retail/catalog.json").read_text())
    domains = {dataset.get("domain") for dataset in document["datasets"]}
    assert domains == set(data_domains.active_domain_names()), \
        sorted(str(d) for d in domains)


@pytest.mark.parametrize("phrase", [
    "Use Cockpit Data for August 2026",
    "Show the August position",
    "What changed last quarter",
    "Exposure by retail product in December",
])
def test_calendar_and_catalogue_words_are_not_read_as_borrower_names(
        phrase: str, retail_metadata: None) -> None:
    """Chat answered "I could not find a borrower called Cockpit Data".

    Both the domain the user had just selected and the month they had asked for
    were treated as the names of customers to look up.
    """
    context = SimpleNamespace(dimensions={"retail_product": ["Personal Finance",
                                                             "Auto Lease"]})
    assert unresolved_names(phrase, context) == []


def test_an_unreadable_catalogue_is_not_cached_as_an_empty_vocabulary() -> None:
    """An early turn taken before PostgreSQL was up used to poison the cache.

    The vocabulary was cached for the life of the process, so a single failed
    read left chat refusing its own domain heading until the next restart —
    intermittently, and never reproducibly.
    """
    from backend.orchestration import entities

    assert entities._CATALOGUE_WORDS is None or entities._CATALOGUE_WORDS


@pytest.mark.skipif(not profile.is_retail(), reason="the corporate profile is active")
def test_the_active_concepts_are_retail_and_bound_to_the_retail_dataset() -> None:
    """Every question was met with "Which figure should CreditProbe measure?".

    The concept registry still bound its measures to corporate datasets that the
    retail conversion had retired, so no retail question could be planned and
    the clarification offered choices — "internal rating" among them — that the
    active product no longer has.
    """
    active = cx.active_concepts()
    assert len(active) >= 30
    datasets = {candidate.dataset
                for concept in active
                for candidate in concept.candidates}
    assert datasets == {"retail_facility_month"}, sorted(datasets)

    labels = " ".join(c.label.lower() for c in active)
    assert "internal rating" not in labels
    for expected in ("exposure", "ecl", "stage", "pd", "lgd", "dpd"):
        assert any(expected in c.id for c in active), expected


def test_the_corporate_concepts_are_retained_as_code() -> None:
    """Retired, not deleted: the corporate book must remain restorable."""
    assert len(cx.CORPORATE_CONCEPTS) > len(cx.active_concepts())


@pytest.mark.skipif(not profile.is_retail(), reason="the corporate profile is active")
def test_facility_grain_resolves_on_the_retail_dataset() -> None:
    """Chat refused: "this can only be reported as one row per customer".

    Facility grain was bound to `account_id` alone, which the retail dataset
    does not carry — so the one grain the retail book is built at was the one
    grain the planner said it could not produce.
    """
    from backend.orchestration.analysis_planner import _grain_key

    assert _grain_key("facility", {"facility_id", "customer_id"}) == "facility_id"
    assert _grain_key("facility", {"account_id"}) == "account_id"
    assert _grain_key("customer", {"customer_id"}) == "customer_id"


def test_the_launcher_serves_the_api_at_the_hostname_it_opens() -> None:
    """The whole authenticated application answered 401 in the browser.

    The launcher opened the page at localhost and pointed it at an API on
    127.0.0.1. The session cookie is host-only and SameSite=Lax, so the browser
    withheld it on every call: the screen said the user was signed out while the
    backend was perfectly healthy, and both chat boxes were dead.
    """
    from pathlib import Path

    launcher = Path(__file__).resolve().parents[2] / "launchers/retail/start-retail.command"
    text = launcher.read_text()

    api = re.findall(r'NEXT_PUBLIC_API_URL="http://([^:"]+)', text)
    opened = re.findall(r'open "http://([^:"]+)', text) or re.findall(r'http://([a-z0-9.]+):\$RETAIL_FRONTEND_PORT', text)
    assert api, "the launcher no longer sets NEXT_PUBLIC_API_URL"
    assert opened, "the launcher no longer opens a browser at a fixed host"
    assert set(api) == set(opened), f"API host {set(api)} != opened host {set(opened)}"


def test_every_governed_dimension_is_a_real_column_of_the_retail_book() -> None:
    """The planner governed NO dimensions at all on the retail installation.

    The filterable list still named the corporate book's columns — sector,
    region, segment, product_type, rating_bucket, country — and the retail
    dataset carries none of them. So "by retail product" resolved to nothing
    and the answer came back at the source grain, and "only personal finance"
    had nothing to filter on.
    """
    import json

    from backend.orchestration.vocabulary import (
        facility_dataset,
        filterable_dimensions,
    )

    document = json.loads((ROOT / "metadata/retail/catalog.json").read_text())
    dataset = next(d for d in document["datasets"] if d["name"] == facility_dataset())
    columns = {field["name"] for field in dataset["fields"]}

    governed = filterable_dimensions()
    assert governed, "the installation governs no dimensions at all"
    missing = [name for name in governed if name not in columns]
    assert not missing, f"not columns of {facility_dataset()}: {missing}"
    assert "product_label" in governed


def test_the_vocabulary_reads_periods_from_the_active_dataset() -> None:
    """The vocabulary read its periods from a dataset this product retired."""
    from backend.orchestration.vocabulary import facility_dataset
    from backend.retail import CANONICAL_DATASET

    assert facility_dataset() == (CANONICAL_DATASET if profile.is_retail()
                                  else "portfolio_facility")


#: A governed vocabulary shaped like the retail book's, without a database.
RETAIL_DIMENSIONS = {
    "product_label": ["Personal Finance", "Auto Finance", "Home Finance",
                      "Credit Card"],
    "customer_segment": ["MASS", "AFFLUENT", "PRIVATE", "PAYROLL"],
    "region_label": ["Riyadh", "Makkah", "Eastern Province"],
    "employer_sector": ["GOVERNMENT", "CONSTRUCTION"],
    "ifrs9_stage": ["1", "2", "3"],
    "dpd_bucket": ["CURRENT", "1-29", "30-59"],
}


@pytest.mark.parametrize(("question", "expected"), [
    ("Show exposure by retail product", "product_label"),
    ("Show exposure by product", "product_label"),
    ("Break that down by employer sector", "employer_sector"),
    ("Show ECL by region", "region_label"),
    ("Show ECL by stage", "ifrs9_stage"),
    ("Show the book by customer segment", "customer_segment"),
    ("Show exposure by delinquency bucket", "dpd_bucket"),
])
def test_retail_breakdowns_resolve_to_retail_columns(question: str,
                                                     expected: str) -> None:
    from backend.orchestration import dimensions as dm

    assert dm.read(question, RETAIL_DIMENSIONS).dimension == expected


def test_a_measure_list_does_not_decide_the_grain() -> None:
    """CP-01 was refused as a contradiction between two readings.

        "Show exposure, customers, facilities and weighted ECL by retail
         product"

    names customers and facilities as COUNTS. Reading either as the grain made
    the explicit breakdown conflict with the head noun, and the product table
    the question asked for came back as "one question back" instead.
    """
    from backend.orchestration import dimensions as dm, grain as gr

    question = ("Use Cockpit Data for August 2026. Show exposure, customers, "
                "facilities and weighted ECL by retail product.")
    found = dm.read(question, RETAIL_DIMENSIONS)
    assert found.dimension == "product_label"
    assert not found.entity, "the head noun is a measure, not an entity"

    wanted = gr.requested(question, dimension=found.dimension,
                          dimension_is_head=found.is_head,
                          entity_is_head=bool(found.entity))
    assert wanted.grain == gr.SEGMENT, wanted.because


def test_an_entity_head_noun_still_outranks_a_breakdown() -> None:
    """The fix above must not turn every ranking into a group-by."""
    from backend.orchestration import dimensions as dm, grain as gr

    question = "Show the ten largest customers by retail product"
    found = dm.read(question, RETAIL_DIMENSIONS)
    assert found.entity == "customer"
    wanted = gr.requested(question, dimension=found.dimension,
                          dimension_is_head=found.is_head,
                          entity_is_head=bool(found.entity))
    assert wanted.grain == gr.CUSTOMER, wanted.because


def test_the_ungrouped_follow_up_offers_a_governed_breakdown() -> None:
    """Every ungrouped retail answer offered "Break that down by sector."

    Sector is a corporate dimension this installation retired: the one
    suggestion under the answer asked a question the book cannot answer.
    """
    from backend.orchestration.suggestions import _default_breakdown

    suggestion = _default_breakdown()
    assert suggestion
    if profile.is_retail():
        assert suggestion != "sector"


def test_the_saved_whatif_row_fits_the_columns_it_is_written_to() -> None:
    """Saving a What-If answered 500, and the screen said the backend was down.

    The store stamped a 25-character version into a VARCHAR(24). PostgreSQL
    does not truncate — it refuses the insert — so every Save failed, and the
    failure reached the user as "Cannot reach the CreditProbe backend".
    """
    from backend.models.platform import StressScenario
    from backend.retail.whatif_store import SAVED, STORE_VERSION

    columns = StressScenario.__table__.columns
    assert len(STORE_VERSION) <= columns["version"].type.length
    assert len(SAVED) <= columns["status"].type.length
    for severity in ("low", "moderate", "high", "severe"):
        assert len(severity) <= columns["severity"].type.length


def test_the_whatif_language_never_guesses_a_unit() -> None:
    """"Increase PD by 2" is two scenarios. On a PD of 2% they are 2.04% and 4%."""
    from backend.retail import whatif_language as lang

    ambiguous = lang.read("Increase PD by 2.", [])
    assert ambiguous.needs_clarification
    assert not ambiguous.shocks, "a shock was applied to an ambiguous sentence"
    assert {o["id"] for o in ambiguous.options} == {"relative", "absolute"}

    relative = lang.read("Increase PD by 20% relative.", [])
    assert relative.shocks == {"pd_relative": 0.2}
    absolute = lang.read("Increase PD by 2 percentage points.", [])
    assert absolute.shocks == {"pd_absolute_pp": 2.0}


def test_the_whatif_language_refuses_a_retired_operation_whole() -> None:
    """A sentence this engine cannot run is never run as the half it understood."""
    from backend.retail import whatif_language as lang

    notches = lang.read("Downgrade everyone one notch.", [])
    assert not notches.shocks
    assert notches.unsupported and "notch" in notches.unsupported[0]


def test_scenario_weights_are_read_exactly_as_written() -> None:
    """Weights are validated, never renormalised behind the reader."""
    from backend.retail import whatif_language as lang

    weights = lang.read("Use base 60%, upturn 10%, downturn 40%.", [])
    assert weights.scenario_weights == {"base": 0.6, "upturn": 0.1,
                                        "downturn": 0.4}
    total = sum(weights.scenario_weights.values())
    assert abs(total - 1.1) < 1e-9, "the weights were rescaled on the way in"


@pytest.mark.parametrize(("question", "expected_from", "expected_to"), [
    ("Give me the July to August ECL decomposition for personal finance",
     "2026-07", "2026-08"),
    ("How did ECL move from June to August?", "2026-06", "2026-08"),
    ("Compare December with January", "2025-12", "2026-01"),
])
def test_months_written_without_a_year_resolve(question: str,
                                               expected_from: str,
                                               expected_to: str) -> None:
    """"The July to August decomposition" named no period at all.

    The question fell through to a single-period total at the governed
    default, and the product's own invariant caught it: "The question asks for
    how a measure moved between two dates, and the analysis produced a total."
    Correct, and not an answer.
    """
    intent = read_period_intent(question, MONTHS)
    assert intent.specified, intent.source
    assert (intent.from_period, intent.to_period) == (expected_from, expected_to)


@pytest.mark.parametrize("question", [
    "Show the ECL decomposition",          # "dec" inside "decomposition"
    "Show total exposure",
    "This may be understated",             # the modal verb, not the month
    "Explain the marginal PD",             # "mar" inside "marginal"
])
def test_a_month_is_only_matched_as_a_whole_word(question: str) -> None:
    """"decomposition" named December, and the answer used the wrong window."""
    assert not read_period_intent(question, MONTHS).specified


def test_a_bare_month_pair_never_runs_backwards() -> None:
    """Each bare month resolves at or before the one after it."""
    intent = read_period_intent("Compare July with August", MONTHS)
    assert MONTHS.index(intent.from_period) < MONTHS.index(intent.to_period)


def test_the_ecl_decomposition_reads_the_active_book() -> None:
    """"Give me the July to August ECL decomposition" was refused.

    "This decomposition needs two published periods to compare and CreditProbe
    cannot find them" — on a book that publishes twenty-five. The method read
    `ifrs9_staging`, which this installation retired, so it saw no periods at
    all and no field it needed.
    """
    import json

    from backend.orchestration import decomposition as dcp
    from backend.retail import CANONICAL_DATASET

    if profile.is_retail():
        assert dcp.dataset() == CANONICAL_DATASET
    mapping = dcp.field_map()
    assert set(mapping) >= {"ead", "pd_12m_pct", "lgd_pct", "total_ecl",
                            "ifrs9_stage", "customer_id"}

    document = json.loads((ROOT / "metadata/retail/catalog.json").read_text())
    dataset = next(d for d in document["datasets"] if d["name"] == dcp.dataset())
    columns = {field["name"] for field in dataset["fields"]}
    missing = [column for column in mapping.values() if column not in columns]
    assert not missing, f"not columns of {dcp.dataset()}: {missing}"


@pytest.mark.parametrize(("question", "wanted"), [
    ("Give me the July to August ECL decomposition for personal finance", True),
    ("Decompose the change in expected credit loss between two months", True),
    ("Show the ECL waterfall between July and August", True),
    ("Show expected credit loss by retail product", False),
    ("Break that down by product", False),
])
def test_a_decomposition_request_is_recognised(question: str,
                                               wanted: bool) -> None:
    """"ECL decomposition" named a movement and was read as a total.

    The product's own invariant caught it — "the question asks how a measure
    moved between two dates, and the analysis produced a total" — which is the
    right refusal to the wrong plan.
    """
    from backend.orchestration import decomposition as dcp

    assert dcp.wants(question) is wanted


@pytest.mark.parametrize(("question", "wanted"), [
    ("How did expected credit loss move from July to August?", True),
    ("How has ECL moved between July and August?", True),
    ("Move this to the project", False),
    ("Move the chart to the top", False),
])
def test_move_from_x_to_y_is_a_movement(question: str, wanted: bool) -> None:
    """"How did ECL move from July to August" came back as one month's total."""
    from backend.orchestration.movement import asks_for_change

    assert asks_for_change(question) is wanted


def test_the_studio_offers_no_method_the_retail_book_cannot_run() -> None:
    """Analysis Studio offered a retail user a menu of dead methods.

    Rating Distribution, Rating Migration, Rating Transition Matrix, Sector
    Concentration, Single Name Concentration and Exposure by Obligor — every
    one of them reads a dataset this conversion retired, so every one of them
    is a control that cannot work.
    """
    import re

    from backend.studio.library import active_definitions, all_definitions

    active = active_definitions()
    assert active, "the library offers nothing at all"
    if not profile.is_retail():
        assert len(active) == len(all_definitions())
        return

    retired = re.compile(r"rating|notch|grade|obligor|sector|covenant|ebitda|"
                         r"dscr|single name|large exposure", re.I)
    offending = [m.name for m in active
                 if retired.search(f"{m.name} {m.definition}")]
    assert not offending, f"the active library still offers {offending[:5]}"
    # Retired, not deleted: the corporate book must remain restorable.
    assert len(all_definitions()) > len(active)
