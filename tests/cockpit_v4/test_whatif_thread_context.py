"""A confirmed scenario the conversation carries, and what a book change does.

UNIT plus a REAL DATABASE half for `remember()`, which writes through the
real `RunStore`. No model, no provider call.

Section 19 wants execution through registered deterministic methods with a
confirmation bound to what will run, which needs the confirmed scenario to
survive between the turn that approved it and the turn that asks about it.
`thread_context` is the one server-written place for that — `routes.py:1342`
is its only existing caller and nothing in a request or a model response can
reach it.

The rule this module is mostly about:

> A source or release change must be VISIBLE and must invalidate the previous
> scenario confirmation and cohort binding.

Every one of the five invalidations section 6.2 names arrives here as a
release that no longer matches, and none of them involves anybody acting in
bad faith: a source refresh does it on its own.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from backend.cockpit_v4 import context as ctx
from backend.cockpit_v4.scenario import spec as sp
from backend.cockpit_v4.scenario import thread as th
from tests.cockpit_v4.test_whatif_spec import confirmed, draft, source

RELEASE = "v4-whatif-corporate-20q-s1"
PRINT = "01fffad050c248f3" + "0" * 48
OTHER_PRINT = "af8a85c3fc6bad50" + "0" * 48


def stored(spec: sp.ScenarioSpec | None = None, **over) -> dict:
    spec = spec or confirmed(
        source=source(release_id=RELEASE, release_fingerprint=PRINT),
        name="Construction stress", original_clauses=("raise PD by 20%",))
    body = th.body(spec, domain_id="corporate", release_id=RELEASE,
                   release_fingerprint=PRINT, reporting_period="2026Q2",
                   run_id="run-1", headline="Construction stress")
    body.update(over)
    return body


def seed(**over) -> dict:
    return {"kind": th.KIND, "created_at": "2026-09-25", "body": stored(**over)}


class _Scope(SimpleNamespace):
    pass


def scope(release_id: str = RELEASE, fingerprint: str = PRINT) -> _Scope:
    return _Scope(release_id=release_id, release_fingerprint=fingerprint)


# ---- the body round trip -----------------------------------------------

def test_a_confirmed_scenario_survives_the_round_trip() -> None:
    body = stored()
    read = th.read({"kind": th.KIND, "body": body})
    assert read is not None
    assert read["scenario_id"] == "sc-1"
    assert read["confirmed_digest"] == body["digest_now"]
    assert read["release_id"] == RELEASE


def test_the_confirmation_digest_is_stored_as_it_was_not_recomputed() -> None:
    """Recomputing it here would make every stored scenario confirmed."""
    unconfirmed = draft(state=sp.PREVIEW_READY)
    body = th.body(unconfirmed, domain_id="corporate", release_id=RELEASE,
                   release_fingerprint=PRINT, reporting_period="2026Q2")
    assert body["confirmed_digest"] == ""
    assert body["digest_now"] == unconfirmed.digest()
    status, _ = th.state_of(body, release_id=RELEASE,
                            release_fingerprint=PRINT)
    # Whatever else it is, it is NOT executable: that is what this test is
    # for. Which not-executable state it is, is the next two tests'.
    assert status != th.ACTIVE


def test_a_previewed_scenario_is_awaiting_approval_not_invalidated() -> None:
    """The two say opposite things and only one of them is true here.

    A preview writes the scenario to the thread so the confirming turn can
    find the exact rules the reader was shown. It carries no confirmation,
    which `state_of` first read as INVALIDATED -- telling the analyst the
    book had moved, about a scenario one "yes" from running. Nothing had
    moved; the reader had simply not answered yet.
    """
    body = th.body(draft(state=sp.PREVIEW_READY), domain_id="corporate",
                   release_id=RELEASE, release_fingerprint=PRINT,
                   reporting_period="2026Q2")
    status, why = th.state_of(body, release_id=RELEASE,
                              release_fingerprint=PRINT)
    assert status == th.AWAITING_CONFIRMATION
    assert "not yet approved" in why
    resolved = th.facts(body, release_id=RELEASE, release_fingerprint=PRINT)
    # The cohort survives, because it was frozen against the release in use
    # and still names those rows. The approval does not, because there is
    # none, and the digest a "yes" would approve is named instead.
    assert isinstance(resolved["cohort"], dict)
    assert "nothing may be executed" in resolved["confirmed_digest"]
    assert resolved["digest_to_confirm"] == body["digest_now"]
    shown = th.parts({"kind": th.KIND, "body": body}, release_id=RELEASE,
                     release_fingerprint=PRINT)
    assert shown and shown[0].startswith(th.PREVIEW_HEADER)
    assert "Do NOT execute it yet" in shown[0]


def test_an_unconfirmed_scenario_that_was_never_previewed_is_invalid() -> None:
    """A DRAFT with no approval is not awaiting one; nobody was shown it."""
    body = th.body(draft(state=sp.DRAFT), domain_id="corporate",
                   release_id=RELEASE, release_fingerprint=PRINT,
                   reporting_period="2026Q2")
    status, why = th.state_of(body, release_id=RELEASE,
                              release_fingerprint=PRINT)
    assert status == th.INVALIDATED
    assert "nothing here that a reader approved" in why


def test_an_attention_card_is_not_a_scenario() -> None:
    """The other kind in the same row is left entirely alone."""
    assert th.read({"kind": "attention_item",
                    "body": {"metric": "ecl_sar_mn"}}) is None
    assert th.parts({"kind": "attention_item", "body": {}},
                    release_id=RELEASE) == []


def test_a_body_from_an_unknown_version_is_dropped_not_guessed_at() -> None:
    assert th.read(seed(body_version=99)) is None
    assert th.read(seed(scenario_id="")) is None
    assert th.read({"kind": th.KIND, "body": "not a dict"}) is None
    assert th.read(None) is None


# ---- a release change invalidates ---------------------------------------

def test_the_same_release_leaves_the_scenario_active() -> None:
    status, why = th.state_of(stored(), release_id=RELEASE,
                              release_fingerprint=PRINT)
    assert status == th.ACTIVE
    assert why == ""


def test_a_different_release_id_invalidates_and_says_so() -> None:
    status, why = th.state_of(stored(), release_id="v4-saudi-corporate-20q-v4",
                              release_fingerprint=PRINT)
    assert status == th.INVALIDATED
    assert RELEASE in why
    assert "v4-saudi-corporate-20q-v4" in why
    assert "different baselines" in why


def test_the_same_id_republished_is_caught_by_the_fingerprint() -> None:
    """Two builds under one id is what a fingerprint exists to detect."""
    status, why = th.state_of(stored(), release_id=RELEASE,
                              release_fingerprint=OTHER_PRINT)
    assert status == th.INVALIDATED
    assert "was republished" in why
    assert PRINT[:12] in why and OTHER_PRINT[:12] in why


def test_an_invalidated_scenario_loses_its_cohort_binding() -> None:
    """The cohort was identifiers in the old book. It is not rebound."""
    live = th.facts(stored(), release_id=RELEASE, release_fingerprint=PRINT)
    assert isinstance(live["cohort"], dict)
    assert live["cohort"]["cohort_id"] == "coh-1"
    assert live["cohort"]["entity_count"] == 412
    assert live["cohort"]["baseline_ecl"] == "640.25"
    assert live["cohort"]["membership_hash"] == "a" * 64
    assert live["confirmed_digest"]

    dead = th.facts(stored(), release_id="v4-saudi-corporate-20q-v4")
    assert isinstance(dead["cohort"], str)
    assert "not rebound" in dead["cohort"]
    assert "Dropped" in dead["confirmed_digest"]
    assert dead["why_it_is_no_longer_valid"]


def test_an_invalidated_scenario_keeps_what_the_reader_wrote() -> None:
    """Losing the binding is not losing the conversation."""
    dead = th.facts(stored(), release_id="v4-saudi-corporate-20q-v4")
    assert dead["the_reader_wrote"] == ["raise PD by 20%"]
    assert dead["name"] == "Construction stress"
    assert dead["rules"]
    assert dead["methods"] == ["delta"]


def test_the_release_change_is_visible_in_both_directions() -> None:
    """Which book it was confirmed against, and which is in use now."""
    dead = th.facts(stored(), release_id="v4-saudi-corporate-20q-v4")
    assert dead["release_id_it_was_confirmed_against"] == RELEASE
    assert dead["release_id_in_use"] == "v4-saudi-corporate-20q-v4"


# ---- what the analyst is shown ------------------------------------------

def test_an_active_scenario_is_handed_over_as_a_record_not_an_instruction():
    rendered = th.parts(seed(), release_id=RELEASE,
                        release_fingerprint=PRINT)
    assert len(rendered) == 1
    text = rendered[0]
    assert text.startswith(th.HEADER)
    assert "not an instruction" in text
    assert "needs its own preview and its own confirmation" in text
    body = json.loads(text[len(th.HEADER) + 1:])
    assert body["status"] == th.ACTIVE
    assert "No source row" in body["this_is_a_simulation"]


def test_an_invalidated_scenario_is_handed_over_with_a_refusal() -> None:
    rendered = th.parts(seed(), release_id="v4-saudi-corporate-20q-v4")
    text = rendered[0]
    assert text.startswith(th.INVALID_HEADER)
    assert "Do NOT execute it" in text
    assert "do NOT rebind its cohort" in text
    assert "offer to rebuild the scenario against the book in use" in text


def test_the_warnings_shown_before_approval_travel_with_it() -> None:
    """A confirmation given without seeing a warning is not a confirmation."""
    spec = confirmed(
        source=source(release_id=RELEASE, release_fingerprint=PRINT),
        warnings=("PD would exceed 100% for 14 facilities; capped.",))
    body = th.facts(stored(spec), release_id=RELEASE,
                    release_fingerprint=PRINT)
    assert body["warnings_shown_before_approval"] == [
        "PD would exceed 100% for 14 facilities; capped."]


# ---- the protected-core branch ------------------------------------------

def test_context_renders_nothing_for_a_thread_with_no_standing_context():
    assert ctx.scenario_packet(None, scope=scope()) == []
    assert ctx.scenario_packet({}, scope=scope()) == []


def test_context_renders_nothing_for_an_attention_card() -> None:
    """The accepted seeded-thread path is untouched by this branch."""
    assert ctx.scenario_packet(
        {"kind": "attention_item", "body": {"metric": "ecl_sar_mn"}},
        scope=scope()) == []


def test_context_renders_the_scenario_against_the_release_in_scope() -> None:
    rendered = ctx.scenario_packet(seed(), scope=scope())
    assert len(rendered) == 1
    assert rendered[0].startswith(th.HEADER)

    moved = ctx.scenario_packet(
        seed(), scope=scope(release_id="v4-saudi-corporate-20q-v4"))
    assert moved[0].startswith(th.INVALID_HEADER)


def test_a_scope_without_a_release_does_not_invent_an_invalidation() -> None:
    """A book that cannot say which release it is is not a book that moved."""
    rendered = ctx.scenario_packet(seed(), scope=SimpleNamespace())
    assert rendered[0].startswith(th.HEADER)


# ---- remember(), through the real store ---------------------------------

@pytest.fixture()
def store(tmp_path):
    from backend.cockpit_v4.run_store import RunStore

    return RunStore(str(tmp_path / "runs.sqlite3"))


def record_for(thread_id="th-1", tenant_id="t-1", run_id="run-1",
               domain_id="corporate") -> SimpleNamespace:
    return SimpleNamespace(thread_id=thread_id, tenant_id=tenant_id,
                           run_id=run_id, domain_id=domain_id)


def put_spec_artifact(store, *, run_id="run-1", tenant_id="t-1",
                      body=None) -> str:
    return store.put_artifact(
        run_id=run_id, tenant_id=tenant_id, kind=th.ARTIFACT_KIND,
        release_id=RELEASE, scope={}, columns=["scenario_id"],
        rows=[body or stored()])


def test_remember_does_nothing_when_the_book_has_whatif_off(store) -> None:
    """The default for every book, and the whole point of the guard."""
    put_spec_artifact(store)
    assert th.remember(store, record=record_for()) is False
    assert store.thread_context("th-1", tenant_id="t-1") is None


def test_remember_stores_the_scenario_the_run_published(store, monkeypatch):
    monkeypatch.setenv("COCKPIT_V4_WHATIF_CORPORATE", "1")
    put_spec_artifact(store)
    assert th.remember(store, record=record_for()) is True
    seeded = store.thread_context("th-1", tenant_id="t-1")
    assert seeded is not None
    assert seeded["kind"] == th.KIND
    assert th.read(seeded)["scenario_id"] == "sc-1"


def test_remember_ignores_every_other_artifact_the_run_stored(store,
                                                              monkeypatch):
    monkeypatch.setenv("COCKPIT_V4_WHATIF_CORPORATE", "1")
    store.put_artifact(run_id="run-1", tenant_id="t-1", kind="sql_result",
                       release_id=RELEASE, scope={}, columns=["ecl"],
                       rows=[{"ecl": 1.0}])
    assert th.remember(store, record=record_for()) is False
    assert store.thread_context("th-1", tenant_id="t-1") is None


def test_remember_will_not_store_a_body_it_cannot_read(store, monkeypatch):
    """A malformed artifact leaves the thread carrying nothing."""
    monkeypatch.setenv("COCKPIT_V4_WHATIF_CORPORATE", "1")
    put_spec_artifact(store, body={"body_version": 99})
    assert th.remember(store, record=record_for()) is False
    assert store.thread_context("th-1", tenant_id="t-1") is None


def test_remember_is_tenant_scoped(store, monkeypatch) -> None:
    monkeypatch.setenv("COCKPIT_V4_WHATIF_CORPORATE", "1")
    put_spec_artifact(store, tenant_id="t-1")
    assert th.remember(store, record=record_for(tenant_id="t-2")) is False


def test_the_latest_scenario_artifact_wins(store, monkeypatch) -> None:
    """A run that revised its scenario carries the one it ended on."""
    monkeypatch.setenv("COCKPIT_V4_WHATIF_CORPORATE", "1")
    put_spec_artifact(store)
    put_spec_artifact(store, body=stored(scenario_id="sc-2", version=2))
    assert th.remember(store, record=record_for()) is True
    seeded = store.thread_context("th-1", tenant_id="t-1")
    assert th.read(seeded)["scenario_id"] == "sc-2"


def test_the_latest_wins_even_when_the_ids_tie_on_the_clock(
        store, monkeypatch) -> None:
    """The defect this test exists for was a coin flip, not a crash.

    `artifact_ids_for_run` orders by `created_at, artifact_id`, and
    `artifact_id` is a uuid. Two spec artifacts written inside one clock tick
    were therefore ordered by a random string, and `remember` -- which walked
    the list backwards and took the first match -- carried whichever
    scenario the tie happened to favour. It picked the right one most of the
    time, which is how it survived.

    Ranking by `version` is what makes it deterministic, so this drives the
    tie directly: the higher version has to win from EITHER position in the
    list.
    """
    monkeypatch.setenv("COCKPIT_V4_WHATIF_CORPORATE", "1")
    first = put_spec_artifact(store, body=stored(scenario_id="sc-2",
                                                version=2))
    second = put_spec_artifact(store, body=stored(scenario_id="sc-1",
                                                 version=1))
    for order in ([first, second], [second, first]):
        assert th.remember(store, record=record_for(),
                           artifact_ids=order) is True
        seeded = store.thread_context("th-1", tenant_id="t-1")
        assert th.read(seeded)["scenario_id"] == "sc-2", (
            f"with the ids in {order} order the revision lost to the "
            f"scenario it replaced.")


def test_one_book_enabled_does_not_carry_the_other_books_scenarios(
        store, monkeypatch) -> None:
    monkeypatch.setenv("COCKPIT_V4_WHATIF_CORPORATE", "1")
    put_spec_artifact(store)
    assert th.remember(store, record=record_for(domain_id="retail")) is False
