"""The Data Builder has to see the domain the chat is answering from.

The defect
----------
Data Builder showed Early Warning as **Empty** — no datasets, no rows, no
periods — on a deployment holding three hundred obligors, twenty published
months and six thousand borrower-month rows, while the chat answered
questions from exactly that data. Neither surface was wrong. The chat reads
the published parquet; Data Builder reads the governed catalogue; and the
build wrote the parquet and registered nothing. One domain, two truths.

What these tests hold
---------------------
That the build's registration step exists and is idempotent, that it
describes the datasets the lake actually has, that the field list comes from
the governed dictionary rather than a hand-kept copy, that it never
un-publishes another domain, and — the whole point — that nothing here
hard-codes how much data there is. Row counts and periods are read from the
lake on every request. A test that asserted "6,000 rows" against a constant
in the source would pass on an empty environment, which is the failure mode
this module was written to remove.
"""

from __future__ import annotations

import json

import pytest

from backend.early_warning import dictionary as dic
from backend.early_warning import registration as reg


@pytest.fixture()
def catalog(tmp_path):
    """A catalogue holding one unrelated domain's dataset."""
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps({
        "version": 1,
        "datasets": [{
            "name": "corporate_borrower_360",
            "domain": "Core Portfolio / Facility",
            "business_name": "Borrower 360",
            "fields": [{"name": "customer_id"}],
        }],
    }))
    return path


# --------------------------------------------------- what gets registered


def test_the_three_datasets_the_build_writes_are_the_three_it_registers():
    names = {d["name"] for d in reg.dataset_definitions()}
    assert names == {reg.BORROWER_MONTH, reg.SIGNAL_OBSERVATION,
                     reg.EXTERNAL_EVENT}


def test_every_dataset_is_filed_under_the_early_warning_heading():
    # The business-domain map claims this exact catalogue heading. A dataset
    # registered under any other string lands in "unplaced", and the card
    # stays empty for a second reason that reads like the first.
    for definition in reg.dataset_definitions():
        assert definition["domain"] == reg.CATALOGUE_DOMAIN


def test_the_heading_is_one_the_business_domain_map_actually_claims():
    from backend.services import data_domains as bd

    placed = bd.business_domain(dataset=reg.BORROWER_MONTH,
                                catalogue_domain=reg.CATALOGUE_DOMAIN)
    assert placed != bd.UNPLACED
    assert placed == "Early Warning"


def test_every_dataset_declares_its_grain_keys_and_period_field():
    for definition in reg.dataset_definitions():
        assert definition["grain"], definition["name"]
        assert definition["primary_keys"], definition["name"]
        assert definition["period_field"] == "snapshot_month"


def test_every_dataset_is_marked_synthetic_because_it_is():
    # A demonstration book that does not say so is the one governance
    # failure a credit officer cannot recover from on their own.
    for definition in reg.dataset_definitions():
        assert definition["is_synthetic"] is True


# ------------------------------------------------- one source for a field


def test_the_borrower_month_fields_come_from_the_governed_dictionary():
    borrower_month = next(d for d in reg.dataset_definitions()
                          if d["name"] == reg.BORROWER_MONTH)
    registered = [f["name"] for f in borrower_month["fields"]]
    assert registered == [entry.name for entry in dic.fields()]


def test_the_field_count_is_not_a_number_written_down_anywhere():
    # Whatever the dictionary holds is what the catalogue publishes. If a
    # signal is added to the inventory tomorrow, the Data Builder's count
    # moves with it and nobody has to remember to edit a constant.
    import inspect

    source = inspect.getsource(reg)
    assert "2527" not in source
    assert "2521" not in source
    assert "6000" not in source
    assert "6,000" not in source


def test_a_field_carries_enough_for_a_reader_to_know_what_it_means():
    borrower_month = next(d for d in reg.dataset_definitions()
                          if d["name"] == reg.BORROWER_MONTH)
    for field in borrower_month["fields"][:50]:
        assert field["business_name"]
        assert field["data_type"]
        assert field["source_column"] == field["name"]


# --------------------------------------------------------- publishing it


def test_publishing_adds_the_domain_and_keeps_the_rest_of_the_bank(catalog):
    result = reg.publish(catalog, sync_database=False)

    payload = json.loads(catalog.read_text())
    names = [d["name"] for d in payload["datasets"]]
    assert "corporate_borrower_360" in names, (
        "publishing Early Warning must not un-publish another domain")
    assert reg.BORROWER_MONTH in names
    assert sorted(result["registered"]) == sorted(
        [reg.BORROWER_MONTH, reg.EXTERNAL_EVENT, reg.SIGNAL_OBSERVATION])


def test_publishing_twice_leaves_the_catalogue_identical(catalog):
    reg.publish(catalog, sync_database=False)
    once = catalog.read_text()
    second = reg.publish(catalog, sync_database=False)
    assert catalog.read_text() == once
    # The second run knows it replaced rather than added, which is what
    # makes it safe to run on every build.
    assert sorted(second["replaced"]) == sorted(second["registered"])


def test_publishing_into_a_missing_catalogue_creates_one(tmp_path):
    path = tmp_path / "nested" / "catalog.json"
    reg.publish(path, sync_database=False)
    assert path.exists()
    assert reg.registered(path) is True


def test_an_unreadable_catalogue_is_rebuilt_rather_than_crashing_the_build(
        tmp_path):
    path = tmp_path / "catalog.json"
    path.write_text("{ this is not json")
    reg.publish(path, sync_database=False)
    assert reg.registered(path) is True


def test_registered_reports_false_before_and_true_after(tmp_path):
    path = tmp_path / "catalog.json"
    assert reg.registered(path) is False
    reg.publish(path, sync_database=False)
    assert reg.registered(path) is True


# ------------------------------------------------ what the screen reads

def test_the_domain_reads_as_populated_from_the_lake_not_from_this_module():
    """The end-to-end claim, through the one metadata reader every surface uses.

    Deliberately asserts shape rather than size: that the heading holds the
    registered datasets, and that whatever rows and periods it reports came
    from the lake. On an environment with no data built, it skips — because
    then "empty" is the honest answer and there is no defect to catch.
    """
    from backend import metadata as md
    from backend.early_warning import v2_service as svc

    try:
        if not svc.periods():
            pytest.skip("The Early Warning domain is not built.")
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"The Early Warning domain is not readable: {e}")

    if not reg.registered():
        pytest.skip("Run scripts/register_early_warning_domain.py first.")

    md.invalidate()
    domain = md.domain(reg.CATALOGUE_DOMAIN)
    assert domain is not None
    assert reg.BORROWER_MONTH in domain.datasets

    borrower_month = md.dataset(reg.BORROWER_MONTH)
    assert borrower_month is not None
    assert borrower_month.readable, (
        "registered but not readable means the catalogue names a dataset the "
        "lake does not have")
    # The numbers are the data's, not this module's.
    assert borrower_month.row_count == sum(
        len(svc.borrower_month(p)) for p in svc.periods())
    assert list(borrower_month.periods) == list(svc.periods())
    assert borrower_month.field_count == len(dic.fields())


def test_the_build_registers_as_part_of_building():
    """§18: the fix must survive a rebuild.

    A one-off row in somebody's database disappears with the environment. The
    build script itself has to publish, or the defect comes back the next
    time the data is rebuilt.
    """
    from pathlib import Path

    source = Path("scripts/build_early_warning_v2.py").read_text()
    assert "registration" in source
    assert "publish()" in source


# ------------------------------------ registering a domain without breaking one


def test_the_early_warning_datasets_declare_their_own_book():
    """A derived copy must not compete with what it was derived from.

    The snapshots carry two and a half thousand fields covering every signal,
    classifier, trigger, node, layer and notch, so they mention almost every
    word a credit question can contain. Registered into the general catalogue
    at the credit book's own scope, they outscored the dataset that actually
    answers one: "what is the observed default rate by score band?" -- a
    retail scorecard question -- led with `early_warning_borrower_month`.

    Scoping them apart is the same mechanism the corporate book already uses,
    and it hides nothing: the datasets stay governed, visible in Data Builder
    and read by the Early Warning product through its own path.
    """
    from backend.data_access.catalog import EARLY_WARNING_SCOPE

    for definition in reg.dataset_definitions():
        assert definition["portfolio_scope"] == EARLY_WARNING_SCOPE, (
            definition["name"])


def test_a_retail_question_still_leads_with_a_retail_dataset():
    """The regression itself, held where the registration is."""
    from backend.orchestration import context as ctx

    if not reg.registered():
        pytest.skip("Run scripts/register_early_warning_domain.py first.")

    found = ctx.retrieve("What is the observed default rate by score band?")
    assert found.datasets
    lead = found.datasets[0].name
    assert lead.startswith("retail_"), (
        f"a retail question led with {lead}")


def test_a_credit_book_question_does_not_lead_with_early_warning():
    from backend.orchestration import context as ctx

    if not reg.registered():
        pytest.skip("Run scripts/register_early_warning_domain.py first.")

    for question in ("the ten largest customers by exposure at default",
                     "how much collateral do we hold?",
                     "what is the IFRS 9 stage 3 exposure?"):
        found = ctx.retrieve(question)
        if not found.datasets:
            continue
        assert not found.datasets[0].name.startswith("early_warning"), (
            f"{question!r} led with {found.datasets[0].name}")


def test_the_registered_domain_can_carry_a_question_of_its_own():
    """The other half: a governed dataset with no measure is one the
    Teaching Factory silently skips, and a domain nobody can ask a question
    about is a domain that does not exist."""
    from backend.brain import vocabulary as vocab

    assert vocab.measures_for(reg.BORROWER_MONTH)
    assert vocab.dimensions_for(reg.BORROWER_MONTH)
    assert vocab.measures_for(reg.SIGNAL_OBSERVATION)
    # The external feed is an event log: a type, a severity, a source and a
    # date, and nothing to sum. Exempted by name rather than by inference,
    # because "no measure" and "somebody forgot" look identical from outside.
    assert reg.EXTERNAL_EVENT in vocab.EVENT_DATASETS
    assert vocab.dimensions_for(reg.EXTERNAL_EVENT)


def test_every_registered_field_type_is_one_the_catalogue_knows():
    """The Early Warning dictionary has a richer type vocabulary than the
    catalogue -- it distinguishes a closed `category` from free `string` --
    and publishing the richer one put a type into the catalogue that no
    catalogue reader could interpret."""
    allowed = {"string", "number", "integer", "boolean", "date"}
    for definition in reg.dataset_definitions():
        for field in definition["fields"]:
            assert field["data_type"] in allowed, (
                f"{definition['name']}.{field['name']}: {field['data_type']}")
