""""These customers" must mean the same rows on turn three as on turn one.

REAL DATABASE · NO MODEL. The published parquet through a real DuckDB
session, and nothing here that could be mistaken for evidence about a model:
there is no provider in this module, not even a scripted one.

Section 6.1: *"use the persisted, authorized investigation cohort -- not the
top ten displayed rows, a chart sample, a paraphrase, or an unbounded new
search."*

Nothing in the accepted runtime persists a cohort, so this is net-new and the
tests are about the two things that could quietly go wrong:

  the membership is not what was frozen    -> the hash catches it
  the membership silently widens           -> C03, C04, C05

Covers C02, C03, C04 and C05 of section 16.3, and D02's "many-to-one joins
cannot multiply EAD or ECL" for the owner-widening path.
"""

from __future__ import annotations

import pathlib
from decimal import Decimal

import pytest

from backend.cockpit_v4 import analytical_runtime as arun
from backend.cockpit_v4 import domain_resolver as resolver
from backend.cockpit_v4 import domains as dom
from backend.cockpit_v4 import lake
from backend.cockpit_v4.scenario import cohort as ch
from backend.cockpit_v4.scenario.errors import ScenarioError

BOOKS = [dom.CORPORATE, dom.RETAIL]


@pytest.fixture(scope="module", autouse=True)
def _lake_present():
    if not pathlib.Path("data/cockpit_v4_lake").exists():
        pytest.skip("the published lake is not present in this worktree")
    arun.reset()
    yield
    arun.reset()


@pytest.fixture(scope="module")
def corporate():
    book = arun.for_domain(dom.CORPORATE)
    scope = resolver.scope_for(dom.CORPORATE, tenant_id=lake.DEFAULT_TENANT)
    return book.session, scope


@pytest.fixture(scope="module")
def retail():
    book = arun.for_domain(dom.RETAIL)
    scope = resolver.scope_for(dom.RETAIL, tenant_id=lake.DEFAULT_TENANT)
    return book.session, scope


def freeze(pair, **over):
    session, scope = pair
    return ch.freeze(session=session, scope=scope, **over)


# ---- the hash is the identity ------------------------------------------

def test_the_same_selection_freezes_to_the_same_hash(corporate) -> None:
    one = freeze(corporate, predicate="sector = 'Construction'")
    two = freeze(corporate, predicate="sector = 'Construction'")
    assert one.ref.membership_hash == two.ref.membership_hash
    assert one.ref.entity_count == two.ref.entity_count > 0


def test_a_different_selection_freezes_to_a_different_hash(corporate) -> None:
    one = freeze(corporate, predicate="sector = 'Construction'")
    two = freeze(corporate, predicate="sector = 'Real Estate'")
    assert one.ref.membership_hash != two.ref.membership_hash


def test_the_hash_is_over_the_set_not_the_order() -> None:
    """Two engines returning the same rows in a different order have frozen
    the same cohort."""
    assert (ch.membership_hash(["b", "a", "c"])
            == ch.membership_hash(["a", "b", "c"]))


def test_the_hash_cannot_be_collided_by_concatenation() -> None:
    """Newline-joined rather than concatenated, so ("ab","c") and ("a","bc")
    are different cohorts -- which they are."""
    assert ch.membership_hash(["ab", "c"]) != ch.membership_hash(["a", "bc"])


def test_counts_and_totals_are_not_part_of_the_identity(corporate) -> None:
    """Two different sets of the same size share a count. A hash that
    included the ECL total would also move on a mere refresh."""
    one = freeze(corporate, predicate="stage = 1")
    assert one.ref.membership_hash != ch.membership_hash(
        [str(one.ref.entity_count)])
    assert Decimal(one.ref.baseline_ecl) > 0


# ---- C02: re-resolution proves it is still the same rows ---------------

def test_c02_a_stored_cohort_re_resolves_to_itself(corporate) -> None:
    frozen = freeze(corporate, predicate="sector = 'Construction' "
                                         "AND stage = 2")
    again = ch.reresolve(session=corporate[0], scope=corporate[1],
                         stored=frozen.to_context())
    assert again.ref.membership_hash == frozen.ref.membership_hash
    assert again.ref.entity_count == frozen.ref.entity_count
    assert again.ref.baseline_ecl == frozen.ref.baseline_ecl


def test_a_moved_membership_is_caught_before_anything_is_calculated(
        corporate) -> None:
    """The failure this whole design exists to catch. A stored cohort whose
    rows have changed underneath is a scenario about a different population
    than the one that was approved."""
    frozen = freeze(corporate, predicate="sector = 'Construction'")
    tampered = dict(frozen.to_context(), membership_hash="f" * 64)
    with pytest.raises(ScenarioError, match="different population") as caught:
        ch.reresolve(session=corporate[0], scope=corporate[1],
                     stored=tampered)
    assert caught.value.code == "SOURCE_VERSION_MISMATCH"
    assert caught.value.detail["frozen_hash"] == "f" * 64
    assert caught.value.detail["now_hash"] == frozen.ref.membership_hash


def test_a_cohort_frozen_in_the_other_book_is_refused(corporate,
                                                      retail) -> None:
    """C04 and A07. A scenario cannot span both books."""
    frozen = freeze(retail, predicate="product = 'Mortgage'")
    with pytest.raises(ScenarioError, match="cannot span both") as caught:
        ch.reresolve(session=corporate[0], scope=corporate[1],
                     stored=frozen.to_context())
    assert caught.value.code == "BOOK_MISMATCH"


def test_a07_freezing_across_sessions_is_refused(corporate, retail) -> None:
    with pytest.raises(ScenarioError, match="cannot be frozen") as caught:
        ch.freeze(session=corporate[0], scope=retail[1])
    assert caught.value.code == "BOOK_MISMATCH"


# ---- C03: the facilities identified, or all their borrower's -----------

def test_c03_a_row_selection_does_not_widen_to_its_owners(corporate) -> None:
    """Section 6.1: *"Ask before expanding a facility-level finding to every
    facility of its borrower."*"""
    narrow = freeze(corporate, predicate="sector = 'Construction' "
                                         "AND stage = 2")
    wide = freeze(corporate, predicate="sector = 'Construction' AND stage = 2",
                  selection=ch.BY_OWNER)
    assert wide.ref.entity_count > narrow.ref.entity_count, (
        "this fixture only tests something if widening actually adds rows")
    assert narrow.ref.membership_hash != wide.ref.membership_hash
    assert narrow.selection == ch.BY_ROW


def test_the_widening_question_shows_what_it_would_cost(corporate) -> None:
    """Asking well means showing the numbers, not just the question."""
    narrow = freeze(corporate, predicate="sector = 'Construction' "
                                         "AND stage = 2")
    offer = ch.widened(session=corporate[0], scope=corporate[1],
                       frozen=narrow)
    assert offer["already_by_owner"] is False
    assert offer["adds"] == offer["if_widened"] - offer["selected"]
    assert offer["adds"] > 0
    # Formatted with separators, because the question is read by a person.
    assert f"{offer['selected']:,}" in offer["question"]
    assert f"{offer['if_widened']:,}" in offer["question"]
    assert f"{offer['adds']:,}" in offer["question"]
    assert len(offer["options"]) == 2


def test_widening_an_owner_cohort_is_a_no_op(corporate) -> None:
    wide = freeze(corporate, predicate="stage = 3", selection=ch.BY_OWNER)
    assert ch.widened(session=corporate[0], scope=corporate[1],
                      frozen=wide)["already_by_owner"] is True


def test_d02_widening_does_not_multiply_exposure(corporate) -> None:
    """The owner widening is a second query, not a join. A join to the owner
    table would duplicate a facility once per owner row and inflate EAD."""
    wide = freeze(corporate, predicate="sector = 'Construction' AND stage = 2",
                  selection=ch.BY_OWNER)
    session, scope = corporate
    rows = session.connection.execute(f"""
        SELECT COUNT(*), COUNT(DISTINCT facility_id)
        FROM corp_facility_quarter
        WHERE reporting_quarter = '{scope.latest_period}'
          AND borrower_id IN (SELECT borrower_id FROM corp_facility_quarter
                              WHERE reporting_quarter = '{scope.latest_period}'
                                AND sector = 'Construction' AND stage = 2)
    """).fetchone()
    assert rows[0] == rows[1] == wide.ref.entity_count, (
        "a facility appears once, however many ways it was reached")


def test_the_described_grain_says_which_it_is(corporate) -> None:
    narrow = freeze(corporate, predicate="stage = 2")
    wide = freeze(corporate, predicate="stage = 2", selection=ch.BY_OWNER)
    assert "only the facilities that matched" in narrow.describe()
    assert "every one of their facilities" in wide.describe()
    assert "fixed as at this period" in narrow.describe()


# ---- C04, C05: "all", and nothing ---------------------------------------

def test_c04_an_empty_predicate_is_the_whole_book_at_one_period(
        corporate) -> None:
    """Section 6.1: *"'All' means all authorized eligible records in the
    active book and declared period, never both books."*"""
    whole = freeze(corporate)
    session, scope = corporate
    expected = session.connection.execute(
        f"SELECT COUNT(*) FROM corp_facility_quarter "
        f"WHERE reporting_quarter = '{scope.latest_period}'").fetchone()[0]
    assert whole.ref.entity_count == expected
    assert whole.period == scope.latest_period


def test_all_is_one_period_not_every_period(corporate) -> None:
    """Section 3.1: never sum ECL stock balances across periods and call that
    one period's portfolio ECL."""
    whole = freeze(corporate)
    session = corporate[0]
    every_row = session.connection.execute(
        "SELECT COUNT(*) FROM corp_facility_quarter").fetchone()[0]
    assert whole.ref.entity_count < every_row / 10


def test_c05_an_empty_selection_does_not_widen(corporate) -> None:
    """The dangerous failure: a filter that matches nothing quietly becoming
    the whole book."""
    with pytest.raises(ScenarioError, match="no cohort to stress") as caught:
        freeze(corporate, predicate="sector = 'Interplanetary Mining'")
    assert caught.value.code == "COHORT_UNRESOLVED"
    assert "not the whole book" in str(caught.value)


def test_an_unknown_selection_kind_is_refused(corporate) -> None:
    with pytest.raises(ScenarioError, match="not a selection"):
        freeze(corporate, selection="everything_adjacent")


# ---- both books --------------------------------------------------------

@pytest.mark.parametrize("domain_id", BOOKS)
def test_each_book_freezes_at_its_own_grain(domain_id, corporate,
                                            retail) -> None:
    pair = corporate if domain_id == dom.CORPORATE else retail
    frozen = freeze(pair, predicate="stage = 2")
    assert frozen.ref.grain == ch.GRAIN[domain_id]["noun"]
    assert frozen.domain_id == domain_id
    assert frozen.ref.entity_count > 0
    assert Decimal(frozen.ref.baseline_ead) > 0


@pytest.mark.parametrize("domain_id", BOOKS)
def test_the_release_and_fingerprint_are_recorded(domain_id, corporate,
                                                  retail) -> None:
    """So a scenario carries which bytes it was built against."""
    pair = corporate if domain_id == dom.CORPORATE else retail
    frozen = freeze(pair, predicate="stage = 1")
    assert frozen.release_id.startswith("v4-saudi-")
    assert len(frozen.release_fingerprint) == 64


def test_retail_freezes_on_accounts_not_customers(retail) -> None:
    frozen = freeze(retail, predicate="product = 'Credit Card'")
    assert frozen.ref.grain == "account"
    assert frozen.owner_count < frozen.ref.entity_count, (
        "customers hold more than one account, so the two counts differ")


# ---- what gets persisted -----------------------------------------------

def test_the_stored_context_is_small(corporate) -> None:
    """The reason membership is a predicate plus a hash rather than a list.
    A 21,918-facility cohort would be a very large thread context read on
    every turn."""
    whole = freeze(corporate)
    assert whole.ref.entity_count > 20_000
    assert len(ch.to_json(whole)) < 1_000


def test_the_stored_context_round_trips(corporate) -> None:
    import json

    frozen = freeze(corporate, predicate="stage = 3",
                    described_as="the defaulted book")
    body = json.loads(ch.to_json(frozen))
    assert body["described_as"] == "the defaulted book"
    assert body["predicate"] == "stage = 3"
    assert body["membership_hash"] == frozen.ref.membership_hash
    again = ch.reresolve(session=corporate[0], scope=corporate[1],
                         stored=body)
    assert again.ref.membership_hash == frozen.ref.membership_hash


def test_the_store_key_is_namespaced_and_per_thread() -> None:
    """Section 6.2: switching books preserves distinct context rather than
    reusing the other book's pending approval."""
    assert ch.store_key("t-1").startswith("whatif.")
    assert ch.store_key("t-1") != ch.store_key("t-2")


def test_membership_is_fixed_by_default(corporate) -> None:
    """Section 6.1: *"use fixed pre-scenario membership by default"* -- a
    segment that re-evaluates after a rating change is a different thing and
    has to be asked for."""
    assert freeze(corporate, predicate="stage = 2").ref.fixed is True
    moving = freeze(corporate, predicate="stage = 2", fixed=False)
    assert moving.ref.fixed is False
    assert "RE-EVALUATES" in moving.describe()
