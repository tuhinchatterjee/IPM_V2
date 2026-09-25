"""The three flag-gated core extensions, and the proof they are inert.

UNIT · NO MODEL. No database, no provider, not even a scripted one; the
published candidate release is exercised in `test_whatif_candidate_release.py`.

P0-P4 made exactly one protected-core change and this pass adds three more.
Every one of them is the same shape -- a guarded local import of the candidate
package, returning the accepted value unless that book's What-If flag is on --
and every one of them is claimed to be a no-op with the flags off. This module
is where that claim is checked rather than asserted:

| Extension | Accepted behaviour with flags off |
|---|---|
| `schema.relations()` | the same four relations per book, spec for spec |
| `schema.domain_of_relation()` | a candidate relation belongs to no domain |
| `domains.current_release()` | exactly `DEFAULT_RELEASES[domain_id]` |

The fourth extension, `context.scenario_blocks`, landed at P3 and is checked
in `test_whatif_errors.py`.

A04 of section 16.1 is the requirement: *"Feature flags off reproduce baseline
routes, tool catalog behavior and representative answers."*
"""

from __future__ import annotations

import json

import pytest

from backend.cockpit_v4 import domains as dom
from backend.cockpit_v4 import schema
from backend.cockpit_v4.scenario import candidate_schema as cs
from backend.cockpit_v4.scenario import flags as fl

BOOKS = (dom.CORPORATE, dom.RETAIL)


@pytest.fixture()
def flags_off(monkeypatch):
    for variable in fl.VARIABLES.values():
        monkeypatch.delenv(variable, raising=False)
    return monkeypatch


@pytest.fixture()
def flags_on(monkeypatch):
    for variable in fl.VARIABLES.values():
        monkeypatch.setenv(variable, "1")
    return monkeypatch


# ---- inert with the flags off -----------------------------------------

@pytest.mark.parametrize("domain_id", BOOKS)
def test_a04_relations_are_the_accepted_four_with_the_flags_off(
        flags_off, domain_id) -> None:
    assert schema.relations(domain_id) == schema.RELATIONS[domain_id]
    assert len(schema.relations(domain_id)) == 4


@pytest.mark.parametrize("domain_id", BOOKS)
def test_a04_the_accepted_specs_are_unchanged_with_the_flag_on(
        flags_off, flags_on, domain_id) -> None:
    """Not "still present": IDENTICAL, field for field, compared through the
    same `to_dict()` a release manifest is written from.

    A candidate relation that widened `corp_facility_quarter` would change
    what the accepted release means, and section 3.3 forbids exactly that.
    """
    flags_off.delenv(fl.VARIABLES[domain_id], raising=False)
    accepted = [r.to_dict() for r in schema.relations(domain_id)]
    flags_on.setenv(fl.VARIABLES[domain_id], "1")
    extended = [r.to_dict() for r in schema.relations(domain_id)]
    assert len(extended) > len(accepted)
    assert (json.dumps(extended[:len(accepted)], sort_keys=True)
            == json.dumps(accepted, sort_keys=True))


@pytest.mark.parametrize("domain_id", BOOKS)
def test_a04_the_release_is_the_accepted_one_with_the_flags_off(
        flags_off, domain_id) -> None:
    assert dom.current_release(domain_id) == dom.DEFAULT_RELEASES[domain_id]


def test_a04_a_candidate_relation_belongs_to_no_book_with_the_flags_off(
        flags_off) -> None:
    with pytest.raises(schema.UnknownRelation):
        schema.domain_of_relation("whatif_corp_ifrs9")


def test_the_flags_default_off(monkeypatch) -> None:
    for variable in fl.VARIABLES.values():
        monkeypatch.delenv(variable, raising=False)
    assert not fl.any_enabled()


# ---- and visible when they are on -------------------------------------

@pytest.mark.parametrize("domain_id", BOOKS)
def test_the_candidate_relations_appear_when_the_book_is_enabled(
        flags_on, domain_id) -> None:
    names = schema.relation_names(domain_id)
    for candidate in cs.relation_names(domain_id):
        assert candidate in names


def test_one_book_enabled_does_not_enable_the_other(monkeypatch) -> None:
    """Section 2 asks for separate flags per book, and A07 forbids Corporate
    data reaching a Retail scenario. A single shared flag would make both
    untestable."""
    monkeypatch.setenv(fl.VARIABLES[dom.CORPORATE], "1")
    monkeypatch.delenv(fl.VARIABLES[dom.RETAIL], raising=False)
    assert len(schema.relations(dom.CORPORATE)) > 4
    assert len(schema.relations(dom.RETAIL)) == 4
    assert dom.current_release(dom.RETAIL) == dom.DEFAULT_RELEASES[dom.RETAIL]


@pytest.mark.parametrize("domain_id", BOOKS)
def test_a_candidate_relation_is_owned_by_its_own_book(flags_on,
                                                       domain_id) -> None:
    """Otherwise a query naming one would be refused as belonging to no
    domain, which reads as a missing table rather than a book switched off."""
    for name in cs.relation_names(domain_id):
        assert schema.domain_of_relation(name) == domain_id


def test_neither_book_can_see_the_other_s_candidate_relations(
        flags_on) -> None:
    """A07. The prefix is not decoration; `relation()` refuses across books."""
    with pytest.raises(schema.UnknownRelation):
        schema.relation(dom.RETAIL, "whatif_corp_ifrs9")
    with pytest.raises(schema.UnknownRelation):
        schema.relation(dom.CORPORATE, "whatif_retail_profile")


def test_the_release_override_falls_back_when_nothing_is_published(
        flags_on, monkeypatch) -> None:
    """A flag on with no candidate release is an operator mid-setup, not a
    reason to refuse a book that is sitting there."""
    monkeypatch.setattr("backend.cockpit_v4.lake.exists", lambda _r: False)
    for domain_id in BOOKS:
        assert (dom.current_release(domain_id)
                == dom.DEFAULT_RELEASES[domain_id])


def test_the_candidate_release_ids_are_their_own(flags_on) -> None:
    """Separately versioned, per section 3.3: a source change has to be
    visible, and two books sharing an id is the substitution the release
    fingerprint exists to stop."""
    for domain_id in BOOKS:
        candidate = cs.release_id(domain_id)
        assert candidate and candidate != dom.DEFAULT_RELEASES[domain_id]
        assert "whatif" in candidate
        assert cs.is_candidate(candidate)
        assert not cs.is_candidate(dom.DEFAULT_RELEASES[domain_id])


# ---- the candidate specs are well formed ------------------------------

@pytest.mark.parametrize("domain_id", BOOKS)
def test_every_candidate_relation_is_self_consistent(domain_id) -> None:
    for spec in cs.relations(domain_id):
        assert spec.name.startswith("whatif_"), spec.name
        assert len(set(spec.columns)) == len(spec.columns), spec.name
        assert spec.period_column in spec.columns, spec.name
        for key in spec.key_columns:
            assert key in spec.columns, (spec.name, key)
        assert spec.description and spec.grain, spec.name


@pytest.mark.parametrize("domain_id", BOOKS)
def test_every_candidate_relation_carries_the_governance_columns(
        domain_id) -> None:
    """They are the isolation: the session filters on them when it
    materialises a table, so a query cannot reach another tenant or release
    by forgetting a WHERE."""
    for spec in cs.relations(domain_id):
        for column in ("tenant_id", "dataset_release_id", "domain_id",
                       "reporting_currency"):
            assert column in spec.columns, (spec.name, column)


@pytest.mark.parametrize("domain_id", BOOKS)
def test_every_candidate_row_says_it_is_synthetic(domain_id) -> None:
    """`origin` is in the DATA, not only in the manifest, so a figure copied
    out of a result carries its own provenance. Section 11.1 is the reason:
    a generated target described as bank output is the failure that matters
    most here."""
    for spec in cs.relations(domain_id):
        assert "origin" in spec.columns, spec.name
        assert "SYNTHETIC_DEMO" in spec.field("origin").description


@pytest.mark.parametrize("domain_id", BOOKS)
def test_every_candidate_unit_is_one_the_catalogue_knows(domain_id) -> None:
    """`test_field_units.py` asserts the two unit sets cover the accepted
    catalogue. An inventively spelled unit here would publish figures with
    the wrong display policy, and `Field.additive` would silently call it
    non-additive."""
    known = schema.ADDITIVE_UNITS | schema.NOT_ADDITIVE_UNITS
    for spec in cs.relations(domain_id):
        for field in spec.fields:
            assert field.unit in known, (spec.name, field.name, field.unit)


def test_the_two_books_declare_no_relation_in_common() -> None:
    corporate = set(cs.relation_names(dom.CORPORATE))
    retail = set(cs.relation_names(dom.RETAIL))
    assert not corporate & retail


def test_the_scenario_weights_are_an_expectation() -> None:
    assert len(cs.SCENARIOS) == 3
    assert sum(w for _i, _n, w in cs.SCENARIOS) == pytest.approx(1.0)
    assert {i for i, _n, _w in cs.SCENARIOS} == {"baseline", "downside",
                                                 "upside"}


# ---- determinism -------------------------------------------------------

def test_the_generator_is_deterministic_across_processes() -> None:
    """A09, in part. Two builds of one release must agree.

    `generate.stable` is SHA-256 based rather than `hash()`, which Python
    randomises per process, so a value derived from it is the same in every
    interpreter. This asserts the property on the primitive and on the two
    generated structures that every downstream number is built from.

    It does NOT rebuild both releases and diff the parquet: that is 90
    seconds and belongs in
    `python3 scripts/whatif/seed_candidate.py --domain all --overwrite`,
    which prints the fingerprint for comparison. The matrix records A09 as
    PARTIAL for exactly that reason.
    """
    import random
    import subprocess
    import sys

    from backend.cockpit_v4 import domains as dom
    from backend.cockpit_v4.scenario import generate as gen
    from backend.cockpit_v4.scenario.generate import corporate
    from backend.cockpit_v4.scenario.generate import macro as mv

    quarters = corporate.quarter_range()
    first = mv.panel(dom.CORPORATE, quarters)
    second = mv.panel(dom.CORPORATE, quarters)
    assert first == second
    assert len(first) > 900

    borrowers = corporate.obligors(random.Random(corporate.CORPORATE_SEED))
    again = corporate.obligors(random.Random(corporate.CORPORATE_SEED))
    assert borrowers == again

    facilities = corporate.facilities_of(
        borrowers, random.Random(corporate.CORPORATE_SEED))
    assert facilities == corporate.facilities_of(
        again, random.Random(corporate.CORPORATE_SEED))

    # And across PROCESSES, which is the half `hash()` would fail: a fresh
    # interpreter has a different hash seed.
    probe = subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.path.insert(0, '.');"
         "from backend.cockpit_v4.scenario import generate as g;"
         "print(g.stable('MEV03|2026Q2', 100000))"],
        capture_output=True, text=True, check=True)
    assert int(probe.stdout.strip()) == gen.stable("MEV03|2026Q2", 100000)
