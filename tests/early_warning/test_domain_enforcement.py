"""Early Warning answers from Early Warning data, and can be shown to.

The rule
--------
An Early Warning answer reads the published Early Warning snapshots and
nothing else -- not `corporate_borrower_360`, not `corporate_ifrs9`, not
`corporate_financials`, not the retail scorecards.

The reason is not territorial. Those datasets have ALREADY fed Early Warning:
the snapshot holds a governed copy of the rating, the stage, the utilisation
and the arrears as they stood when the score was computed. Reading them again
at answer time reads the same fact from two places that can disagree, and the
answer is then about neither the score nor the source.

Where it is enforced
--------------------
At the door -- `v2_service._load` -- because that is the single function every
Early Warning figure is read through. A rule enforced in the callers is a rule
a new caller has not heard of.

What these tests are careful about
----------------------------------
They check the door, not a list. A test that only asserted "corporate_ifrs9
is in FORBIDDEN_DOMAINS" would pass while a dataset nobody thought to name
was read freely, which is the failure an allow-list exists to make
impossible. So the positive case is asserted too: anything not on the
allow-list is refused, including names invented here.
"""

from __future__ import annotations

import pytest

from backend.early_warning import domain as dom
from backend.early_warning import v2_service as svc
from backend.early_warning.conversation import plan as plan_mod
from backend.early_warning.conversation import validate as val


# ---------------------------------------------------------- the definition


def test_the_domain_is_three_datasets_and_they_are_the_built_ones():
    assert dom.DATASETS == {
        "early_warning_borrower_month",
        "early_warning_signal_observation",
        "early_warning_external_event_synthetic",
    }


def test_every_surface_reads_the_same_definition():
    """§22: one canonical domain, not six copies that agree today."""
    from backend.early_warning import grain as grain_mod
    from backend.early_warning import registration as reg

    assert grain_mod.DOMAIN_ID == dom.DOMAIN_ID
    assert grain_mod.DOMAIN == dom.DOMAIN
    assert tuple(grain_mod.DATASETS) == tuple(sorted(dom.DATASETS))
    assert val.ALLOWED_DOMAIN == dom.DOMAIN_ID
    assert val.ALLOWED_DATASETS == dom.DATASETS
    assert reg.CATALOGUE_DOMAIN == dom.DOMAIN
    assert {reg.BORROWER_MONTH, reg.SIGNAL_OBSERVATION,
            reg.EXTERNAL_EVENT} == dom.DATASETS
    assert {svc.BORROWER_MONTH, svc.SIGNAL_OBSERVATION,
            svc.EXTERNAL_EVENT_SYNTHETIC} == dom.DATASETS


# ---------------------------------------------------------------- the door


@pytest.mark.parametrize("dataset", [
    "corporate_borrower_360",
    "corporate_ifrs9",
    "corporate_financials",
    "corporate_ratings",
    "retail_behavioral_scorecard_monthly_validation",
    "retail_application_scorecard_development_reference",
    "corporate_supply_chain",
    "corporate_exposure_network",
])
def test_the_door_refuses_a_dataset_outside_the_domain(dataset):
    with pytest.raises(dom.OutOfDomain):
        svc._load(dataset)


def test_the_door_refuses_a_dataset_nobody_thought_to_name():
    # The point of an allow-list. A deny-list would pass this test by
    # accident only until somebody built a dataset it had not heard of.
    with pytest.raises(dom.OutOfDomain):
        svc._load("a_dataset_invented_in_this_test")


def test_a_refusal_says_what_it_refused_and_what_is_allowed():
    with pytest.raises(dom.OutOfDomain) as raised:
        svc._load("corporate_ifrs9")
    message = str(raised.value)
    assert "corporate_ifrs9" in message
    assert "early_warning_borrower_month" in message


def test_a_refusal_about_an_upstream_dataset_says_why_reading_it_twice_is_wrong():
    with pytest.raises(dom.OutOfDomain) as raised:
        svc._load("corporate_borrower_360")
    assert "already holds a governed copy" in str(raised.value)


def test_the_refusal_is_an_access_error_not_a_value_error():
    # Callers must refuse the request rather than correct the name and try
    # again, so the exception type says which kind of wrong this is.
    assert issubclass(dom.OutOfDomain, PermissionError)


def test_the_three_governed_datasets_are_let_through():
    try:
        if not svc.periods():
            pytest.skip("The Early Warning domain is not built.")
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"The Early Warning domain is not readable: {e}")

    for name in sorted(dom.DATASETS):
        assert not svc._load(name).empty


# ------------------------------------------------------------ the planner


def test_a_plan_step_naming_another_domain_is_refused_and_not_repairable():
    step = plan_mod.Step(analysis="population", domain="corporate_ifrs9",
                         period="")
    plan = plan_mod.Plan(steps=[step])
    result = val.check(plan, package=_package())

    assert result.ok is False
    failure = next(f for f in result.failures if f.code == "out_of_domain")
    assert failure.repairable is False, (
        "a repair that rewrote the domain would make the refusal cosmetic")
    assert failure.offered == [dom.DOMAIN_ID]


@pytest.mark.parametrize("named", [
    "corporate_borrower_360", "corporate_financials", "retail",
    "cockpit", "what_if", "graph",
])
def test_no_other_domain_name_survives_validation(named):
    plan = plan_mod.Plan(steps=[plan_mod.Step(analysis="population",
                                              domain=named)])
    result = val.check(plan, package=_package())
    assert result.ok is False
    assert any(f.code == "out_of_domain" for f in result.failures)


# -------------------------------------------------------------- the audit


def test_a_recording_reports_the_datasets_actually_read():
    try:
        if not svc.periods():
            pytest.skip("The Early Warning domain is not built.")
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"The Early Warning domain is not readable: {e}")

    with dom.recording() as seen:
        svc.borrower_month()
    assert seen == {dom.BORROWER_MONTH}
    assert seen <= dom.DATASETS


def test_reads_outside_a_recording_cost_nothing_and_are_not_kept():
    assert dom.datasets_read() == ()
    try:
        svc.periods()
    except Exception:  # noqa: BLE001 - not built is not this test's subject
        pass
    assert dom.datasets_read() == ()


def test_two_recordings_do_not_see_each_other():
    """Two turns run at once, one thread each. Reads must not cross."""
    import threading

    results: dict[str, set[str]] = {}

    def record(name: str, dataset: str) -> None:
        with dom.recording() as seen:
            dom.note_read(dataset)
            results[name] = set(seen)

    a = threading.Thread(target=record, args=("a", dom.BORROWER_MONTH))
    b = threading.Thread(target=record, args=("b", dom.SIGNAL_OBSERVATION))
    a.start(); b.start(); a.join(); b.join()

    assert results["a"] == {dom.BORROWER_MONTH}
    assert results["b"] == {dom.SIGNAL_OBSERVATION}


def _package():
    from backend.early_warning import grain as grain_mod

    try:
        return grain_mod.build("anything")
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"The Early Warning domain is not readable: {e}")
