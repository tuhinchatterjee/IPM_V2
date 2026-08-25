"""
What the method library may and may not claim.

The library is 300+ credit-risk methods. The number is easy; the honesty is the
hard part. A definition somebody wrote down is not an implementation, and an
implementation nobody tested is not a certified method. These tests exist to
stop the library drifting into advertising a tick it has not earned, because
that is the one failure a bank would never forgive.
"""

from __future__ import annotations

import pytest

from backend.studio.library import all_definitions
from backend.studio.model import Category, Lifecycle, MethodDefinition
from backend.studio.registry import Registry

LIBRARY = all_definitions()


@pytest.fixture(scope="module")
def registry() -> Registry:
    return Registry().load()


# ------------------------------------------------------------------ coverage


def test_library_is_large_enough_to_be_a_library():
    assert len(LIBRARY) >= 300, (
        f"The library holds {len(LIBRARY)} methods; the product claims 300+."
    )


def test_every_id_is_unique():
    ids = [m.id for m in LIBRARY]
    assert len(ids) == len(set(ids))


def test_every_method_has_a_definition_and_a_category():
    for method in LIBRARY:
        assert method.definition.strip(), f"{method.id} has no definition"
        assert method.category in set(Category), f"{method.id}: {method.category}"


def test_categories_are_all_populated(registry: Registry):
    # An empty category is a navigation dead end. `categories()` filters them
    # out, so the assertion is that the ones we ship are actually used.
    used = {c["category"] for c in registry.categories()}
    assert len(used) >= 12


# ------------------------------------------------------- certification honesty


def test_certified_count_is_in_the_declared_range(registry: Registry):
    certified = registry.stats()["certified"]
    assert 40 <= certified <= 60, (
        f"{certified} methods claim certification. The product says 40-60; "
        "anything outside that is either a regression or an inflated claim."
    )


def test_no_method_is_certified_without_an_implementation(registry: Registry):
    for method in registry.all():
        if method.is_certified:
            assert method.plan or method.engine_analysis, (
                f"{method.id} carries the certified tick with nothing to run."
            )


def test_certified_methods_could_survive_their_own_gate(registry: Registry):
    """Every upheld claim passes `can_certify`, or is backed by a certified
    engine analysis that carries its own contract and tests."""
    for method in registry.all():
        if not method.is_certified:
            continue
        ok, missing = method.can_certify()
        assert ok or method.engine_analysis, (
            f"{method.id} claims certification but is missing: {missing}"
        )


def test_a_certification_claim_with_no_evidence_is_downgraded():
    """The registry, not the author, decides what is certified."""
    registry = Registry()
    registry.register(MethodDefinition(
        id="fabricated_claim", name="Fabricated Claim",
        category=Category.PORTFOLIO_QUALITY, definition="Nothing.",
        lifecycle=Lifecycle.CERTIFIED,
    ))
    method = registry.get("fabricated_claim")
    assert not method.is_certified
    assert method.lifecycle == Lifecycle.PRECONFIGURED
    assert "no implementation" in registry.audit().downgraded["fabricated_claim"]


def test_a_claim_backed_by_an_unrun_test_is_downgraded():
    from backend.studio.model import TestCase

    registry = Registry()
    registry.register(MethodDefinition(
        id="untested_claim", name="Untested Claim",
        category=Category.PORTFOLIO_QUALITY, definition="Something.",
        lifecycle=Lifecycle.CERTIFIED,
        plan={"operations": []},
        test_cases=[TestCase(id="t1", name="A case", purpose="p")],  # passed=None
    ))
    assert not registry.get("untested_claim").is_certified
    assert "run and passed" in registry.audit().downgraded["untested_claim"]


def test_a_claim_pointing_at_a_missing_engine_analysis_is_downgraded():
    registry = Registry()
    registry.register(MethodDefinition(
        id="ghost_engine", name="Ghost Engine",
        category=Category.PORTFOLIO_QUALITY, definition="Something.",
        lifecycle=Lifecycle.CERTIFIED,
        engine_analysis="an_analysis_that_does_not_exist",
    ))
    assert not registry.get("ghost_engine").is_certified
    assert "not runnable" in registry.audit().downgraded["ghost_engine"]


def test_the_audit_accounts_for_every_claim(registry: Registry):
    audit = registry.audit()
    claimed = sum(1 for m in LIBRARY if m.lifecycle == Lifecycle.CERTIFIED)
    assert len(audit.upheld) + len(audit.downgraded) == claimed


def test_certified_methods_say_what_they_do_not_tell_you(registry: Registry):
    for method in registry.all():
        if method.is_certified and not method.engine_analysis:
            assert method.limitations.strip(), (
                f"{method.id} is certified with no statement of limitations."
            )


# ----------------------------------------------------------------- resolution


def test_aliases_route_to_one_method(registry: Registry):
    stats = registry.stats()
    assert stats["aliases"] >= stats["total"], (
        "Every method should at least be reachable by its own id and name."
    )


def test_find_refuses_to_guess(registry: Registry):
    # A near-miss must not resolve. A confident number answering a different
    # question is worse than no answer.
    assert registry.find("defalt rate") is None
    assert registry.find("") is None
    assert registry.find("show me everything about credit") is None


def test_find_resolves_an_exact_alias(registry: Registry):
    method = registry.find("NPL ratio")
    assert method is not None
    assert "npl" in method.search_text()


def test_get_raises_rather_than_returning_none(registry: Registry):
    from backend.studio.registry import MethodNotFound

    with pytest.raises(MethodNotFound):
        registry.get("no_such_method_at_all")


def test_search_can_be_narrowed(registry: Registry):
    certified = registry.search(certified_only=True)
    assert certified and all(m.is_certified for m in certified)
    runnable = registry.search(runnable_only=True)
    assert len(runnable) >= len(certified)


def test_search_puts_evidence_first(registry: Registry):
    results = registry.search(category=Category.PORTFOLIO_QUALITY)
    if results and any(m.is_certified for m in results):
        assert results[0].is_certified


# ------------------------------------------------------------------ mechanics


def test_two_methods_computing_the_same_thing_share_a_fingerprint():
    a = MethodDefinition(id="a", name="A", category=Category.PORTFOLIO_QUALITY,
                         plan={"operations": [{"id": "x"}]},
                         required_fields=["ead", "account_id"])
    b = MethodDefinition(id="b", name="B differently named",
                         category=Category.CONCENTRATION,
                         plan={"operations": [{"id": "x"}]},
                         required_fields=["account_id", "ead"])
    assert a.fingerprint() == b.fingerprint()


def test_bumping_a_certified_method_keeps_the_signed_off_version():
    method = MethodDefinition(
        id="m", name="M", category=Category.PORTFOLIO_QUALITY,
        lifecycle=Lifecycle.CERTIFIED, version="2.0.0",
        certified_at="2026-01-01", certified_by="Model Validation",
        plan={"operations": []},
    )
    method.bump(change_note="Threshold changed to 90 days.", by="analyst")
    assert method.version == "2.1.0"
    assert method.lifecycle == Lifecycle.DRAFT
    assert not method.certified_at, "Editing must not carry the tick forward."
    assert method.versions[0].version == "2.0.0"
    assert method.versions[0].lifecycle == Lifecycle.CERTIFIED
    assert method.versions[0].certified_by == "Model Validation"


def test_can_certify_reports_every_gap_not_the_first():
    ok, missing = MethodDefinition(id="m", name="M",
                                   category=Category.PORTFOLIO_QUALITY).can_certify()
    assert not ok
    assert len(missing) >= 4


def test_round_trip_through_a_dict_is_lossless():
    original = LIBRARY[0]
    restored = MethodDefinition.from_dict(original.to_dict())
    assert restored.id == original.id
    assert restored.category == original.category
    assert restored.aliases == original.aliases
