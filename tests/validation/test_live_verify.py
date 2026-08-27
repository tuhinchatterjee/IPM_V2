"""
The live verification tool, and the promises it makes about secrets.

What these can and cannot check
--------------------------------
They cannot check that a live call succeeds — there is no provider key in a
test environment, and inventing one would defeat the purpose. What they check
is everything AROUND that: that a dry run spends nothing, that a report refuses
to be written if anything key-shaped got into it, that a run which made no
calls can never report itself as verified, and that a stored verification goes
stale the moment the build or the model configuration moves.

The last one is the one worth having. A badge that survives a configuration
change is worse than no badge, because somebody will believe it.
"""

from __future__ import annotations

import json

import pytest

from backend.validation import live_verify as lv

# --------------------------------------------------------------- the dry run


def test_a_dry_run_spends_nothing():
    report = lv.dry_run()
    assert report.mode == lv.DRYRUN
    assert report.spends_credits is False
    assert report.live_calls_made == 0
    assert report.estimated_calls[lv.DRYRUN] == 0
    assert report.passed is True


def test_a_dry_run_states_what_every_other_mode_costs():
    report = lv.dry_run()
    for mode in lv.MODES:
        assert mode in report.estimated_calls
    assert all(report.estimated_calls[m] > 0
               for m in lv.MODES if m != lv.DRYRUN), (
        "a mode that spends credit must say so before it is run")


def test_a_dry_run_reports_the_build_and_the_roles():
    report = lv.dry_run()
    assert report.configuration_fingerprint
    assert set(report.role_models) == {"router", "planner", "interpretation",
                                       "critic"}
    assert set(report.role_efforts) == set(report.role_models)
    assert report.roles_summary, "the roles must be described in words"


def test_a_dry_run_never_reports_itself_as_verified():
    """Zero calls can never be a verification, whatever else passed."""
    report = lv.dry_run()
    assert report.live_verified is False


# ------------------------------------------------------------- eligibility


def test_a_build_with_no_key_is_not_eligible():
    report = lv.dry_run()
    if report.key_present:
        pytest.skip("A provider key is configured in this environment.")
    can, why = lv.eligible(report)
    assert can is False
    assert "key" in why


def test_a_stale_image_is_not_eligible():
    report = lv.Report()
    report.key_present = True
    report.build_matches_source = False
    can, why = lv.eligible(report)
    assert can is False
    assert "commit" in why


# ------------------------------------------------------------ no live claims


@pytest.mark.parametrize("mode", [lv.QUICK, lv.CRITICAL, lv.FULL_ROUTING,
                                  lv.FULL_CERTIFICATION])
def test_a_live_mode_refuses_rather_than_pretending(mode):
    """With no key, a live mode fails and says why. It does not skip quietly.

    §23 of the remediation brief: do not claim live verification, and do not
    report it as failed merely because no key exists. The distinction is
    carried by `live_verified` — false — and by the failure naming the key
    rather than naming a case.
    """
    report = lv.Report()
    lv._stamp(report)
    if report.key_present:
        pytest.skip("A provider key is configured in this environment.")

    ran = lv.RUNNERS[mode]()
    assert ran.live_verified is False
    assert ran.live_calls_made == 0
    assert ran.passed is False
    assert any("key" in f or "commit" in f for f in ran.failures), ran.failures


# ------------------------------------------------------------ the key boundary


def test_a_report_containing_a_key_is_refused(tmp_path):
    report = lv.dry_run()
    report.notes.append("the key is sk-ant-api03-abcdefghijklmnop")
    with pytest.raises(RuntimeError, match="must never be recorded"):
        lv.write(report, tmp_path)


def test_a_report_with_a_key_shaped_field_name_is_refused(tmp_path):
    report = lv.dry_run()
    report.roles = [{"role": "router", "anthropic_api_key": "anything"}]
    with pytest.raises(RuntimeError, match="must never be recorded"):
        lv.write(report, tmp_path)


@pytest.mark.parametrize("bad", ["authorization", "Bearer-Token", "SECRET_KEY",
                                 "password"])
def test_every_forbidden_field_name_is_caught(bad, tmp_path):
    report = lv.dry_run()
    report.invariants = [{bad: "x"}]
    with pytest.raises(RuntimeError, match="must never be recorded"):
        lv.write(report, tmp_path)


def test_an_ordinary_report_is_written_and_reads_back(tmp_path):
    report = lv.dry_run()
    path = lv.write(report, tmp_path)
    assert path.exists()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["verification_version"] == lv.VERIFICATION_VERSION
    assert payload["mode"] == lv.DRYRUN
    # The whole document, checked the way an auditor would: nothing anywhere
    # in it looks like a credential.
    assert "sk-ant" not in json.dumps(payload)
    assert lv._key_free(payload) == []


def test_the_written_report_is_named_for_the_commit(tmp_path):
    report = lv.dry_run()
    path = lv.write(report, tmp_path)
    assert report.git_sha[:12] in path.name
    assert path.name.startswith("live_ai_verification_")


# ---------------------------------------------------------------- staleness


def _verified(report: lv.Report) -> dict:
    payload = report.to_dict()
    payload["live_verified"] = True
    payload["live_calls_made"] = 12
    return payload


def test_a_verification_for_this_build_is_not_stale():
    current = lv.Report()
    lv._stamp(current)
    stale, why = lv.is_stale(_verified(current))
    assert stale is False, why


def test_a_verification_from_another_commit_is_stale():
    current = lv.Report()
    lv._stamp(current)
    payload = _verified(current)
    payload["git_sha"] = "0" * 40
    stale, why = lv.is_stale(payload)
    assert stale is True
    assert "commit" in why


def test_a_changed_model_configuration_makes_it_stale():
    current = lv.Report()
    lv._stamp(current)
    payload = _verified(current)
    payload["configuration_fingerprint"] = "deadbeefdeadbeef"
    stale, why = lv.is_stale(payload)
    assert stale is True
    assert "model configuration" in why


def test_a_verification_that_made_no_calls_is_stale():
    current = lv.Report()
    lv._stamp(current)
    payload = current.to_dict()
    payload["live_verified"] = False
    stale, why = lv.is_stale(payload)
    assert stale is True
    assert "live provider calls" in why


def test_an_older_report_format_is_stale():
    current = lv.Report()
    lv._stamp(current)
    payload = _verified(current)
    payload["verification_version"] = "0.1"
    stale, why = lv.is_stale(payload)
    assert stale is True


def test_no_stored_verification_is_stale():
    stale, why = lv.is_stale({})
    assert stale is True
    assert "no stored verification" in why


# ------------------------------------------------------------------ the badge


def test_the_badge_is_false_with_nothing_stored(tmp_path):
    found = lv.badge(tmp_path)
    assert found["live_verified"] is False
    assert found["caveat"], "the badge always carries its own limitation"
    assert "not a measure of accuracy" in found["caveat"]


def test_the_badge_reads_a_stored_verification(tmp_path):
    current = lv.Report()
    lv._stamp(current)
    current.mode = lv.QUICK
    current.live_verified = True
    current.live_calls_made = 12
    current.components = ["model_roles", "live_smoke"]
    current.passed = True
    lv.write(current, tmp_path)

    found = lv.badge(tmp_path)
    assert found["live_verified"] is True
    assert found["stale"] is False
    assert found["calls"] == 12
    assert found["mode"] == lv.QUICK


def test_the_badge_goes_stale_when_the_configuration_moves(tmp_path):
    current = lv.Report()
    lv._stamp(current)
    current.mode = lv.QUICK
    current.live_verified = True
    current.live_calls_made = 12
    current.configuration_fingerprint = "not-the-current-one"
    lv.write(current, tmp_path)

    found = lv.badge(tmp_path)
    assert found["live_verified"] is False
    assert found["stale"] is True


def test_a_dry_run_on_disk_does_not_make_the_badge_stale(tmp_path):
    """The commonest report on disk is the one that costs nothing.

    A dry run is a survey of what WOULD be verified. Filing it as a
    verification made the badge read STALE on a build that had simply never
    been verified — and "stale" implies a verification once existed.
    """
    lv.write(lv.dry_run(), tmp_path)

    found = lv.badge(tmp_path)
    assert found["live_verified"] is False
    assert found["stale"] is False, (
        "a build that was never verified is NOT VERIFIED, not STALE")
    assert "no stored verification" in found["reason"]


# ------------------------------------------------------------- the threads


def test_every_declared_expectation_is_implemented():
    """A thread cannot ask for a check that does not exist.

    A verification that silently skipped an expectation it did not recognise
    would get weaker every time somebody extended it.
    """
    from backend.validation import threads

    for thread in lv.THREADS:
        for name in thread.expects:
            assert name in threads.EXPECTATIONS, (
                f"{thread.name} expects {name!r}, which nothing implements")


def test_the_threads_cover_the_brief():
    names = {t.name for t in lv.THREADS}
    assert names == {
        "A_metadata_memory", "B_complex_dynamic_calculation",
        "C_entity_set_memory", "D_previous_result_reuse",
        "E_material_ambiguity", "F_business_invariant_gate",
        "G_unsupported_data",
    }


def test_the_threads_drive_the_api_not_the_orchestrator():
    """§5: through the same path the browser uses.

    Checked structurally. The last time conversation memory was verified
    against an internal function it worked in every check and failed for every
    user, because the browser's route through the service layer was the thing
    that was broken.
    """
    import inspect

    from backend.validation import threads

    source = inspect.getsource(threads.ask)
    assert "/api/v1/investigations" in source
    assert "/messages" in source
    assert "orchestrator" not in source
