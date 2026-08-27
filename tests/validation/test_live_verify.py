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


# ===========================================================================
# The secret scanner, narrowed
# ===========================================================================
#
# The rule that shipped rejected any field whose name CONTAINED "token". Every
# role case carries input_tokens and output_tokens, so a Quick run that had
# made twelve successful live calls could not be filed — the scanner blocked
# the very evidence it exists to protect. These pin both halves of the fix:
# counting tokens is telemetry, holding one is a credential.


@pytest.mark.parametrize("field", [
    "input_tokens", "output_tokens", "total_tokens", "cached_input_tokens",
    "cache_creation_input_tokens", "cache_read_input_tokens",
    "prompt_tokens", "completion_tokens", "max_tokens", "token_count",
])
def test_token_usage_telemetry_is_allowed(field, tmp_path):
    report = lv.dry_run()
    report.cases.append(lv.Case(name="role:router", component="model_roles",
                                passed=True))
    payload = report.to_dict()
    payload["cases"][0][field] = 412
    assert lv._key_free(payload) == [], f"{field} must be allowed"


def test_a_real_case_with_token_counts_is_written(tmp_path):
    """The exact shape that was refused: a passing role case."""
    report = lv.dry_run()
    report.cases.append(lv.Case(
        name="role:router", component="model_roles", passed=True,
        role="router", provider="anthropic",
        configured_model="", served_model="claude-x",
        schema_valid=True, latency_ms=812,
        input_tokens=412, output_tokens=38,
        request_id="req_01ABCDEFG"))

    path = lv.write(report, tmp_path)
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["cases"][0]["input_tokens"] == 412
    assert stored["cases"][0]["output_tokens"] == 38
    assert stored["cases"][0]["request_id"] == "req_01ABCDEFG"


def test_token_telemetry_must_actually_be_a_number(tmp_path):
    """A string under input_tokens is not a count, and might be a key."""
    report = lv.dry_run()
    report.invariants = [{"input_tokens": "sk-ant-api03-leaked"}]
    with pytest.raises(RuntimeError, match="must never be recorded"):
        lv.write(report, tmp_path)


@pytest.mark.parametrize("field", [
    "api_key", "apikey", "anthropic_api_key", "x_api_key",
    "access_token", "refresh_token", "bearer_token", "id_token",
    "session_token", "auth_token", "token",
    "authorization", "authorization_header", "auth",
    "secret", "client_secret", "secret_key", "password", "passphrase",
    "credential", "credentials", "private_key", "cookie",
])
def test_every_credential_field_is_rejected(field, tmp_path):
    report = lv.dry_run()
    report.invariants = [{field: "anything at all"}]
    with pytest.raises(RuntimeError, match="must never be recorded"):
        lv.write(report, tmp_path)


@pytest.mark.parametrize("field", [
    "provider_access_token", "google_refresh_token", "vendor_api_key",
    "service_private_key", "admin_password", "db_credential",
])
def test_a_credential_suffix_is_rejected_whatever_it_is_prefixed_with(
        field, tmp_path):
    report = lv.dry_run()
    report.invariants = [{field: "x"}]
    with pytest.raises(RuntimeError, match="must never be recorded"):
        lv.write(report, tmp_path)


@pytest.mark.parametrize("field", [
    "prompt", "raw_prompt", "system_prompt", "messages", "request_body",
    "raw_request", "rows", "data_rows", "records",
    "gold", "gold_answer", "expected_answer", "answer_key",
])
def test_confidential_content_is_rejected(field, tmp_path):
    """Not a credential, and still never a thing a report may carry."""
    report = lv.dry_run()
    report.invariants = [{field: "whatever this is"}]
    with pytest.raises(RuntimeError, match="must never be recorded"):
        lv.write(report, tmp_path)


@pytest.mark.parametrize("value", [
    "sk-ant-api03-abcdefghijklmnop",
    "sk_live_abcdefghijklmnop",
    "sk-proj-abcdefghijklmnop",
    "Authorization: Bearer abcdefghijklmnopqrstuvwx",
    "Basic YWxhZGRpbjpvcGVuc2VzYW1lMTIzNDU2Nzg5",
    "x-api-key: something",
])
def test_a_credential_shaped_value_is_rejected(value, tmp_path):
    report = lv.dry_run()
    report.notes.append(f"the provider said: {value}")
    with pytest.raises(RuntimeError, match="must never be recorded"):
        lv.write(report, tmp_path)


def test_the_permitted_report_contract_all_writes(tmp_path):
    """Everything section 4 says a report MAY contain, in one document."""
    report = lv.dry_run()
    report.cases.append(lv.Case(
        name="B_complex_dynamic_calculation", component="analytical_planning",
        passed=True, role="planner", provider="anthropic",
        configured_model="a-model", served_model="a-model",
        schema_valid=True, latency_ms=1240,
        input_tokens=980, output_tokens=145,
        request_id="req_01XYZ", error_category=""))
    report.invariants = [{"ok": True, "checked": ["headroom < 15%"],
                          "failed": []}]
    assert lv._key_free(report.to_dict()) == []
    written = json.loads(lv.write(report, tmp_path).read_text(encoding="utf-8"))
    for permitted in ("git_sha", "source_sha", "git_branch", "provider",
                      "role_models", "role_efforts",
                      "configuration_fingerprint", "cases", "invariants"):
        assert permitted in written


def test_the_refusal_names_the_field_and_the_reason(tmp_path):
    report = lv.dry_run()
    report.invariants = [{"access_token": "x"}]
    with pytest.raises(RuntimeError) as raised:
        lv.write(report, tmp_path)
    said = str(raised.value)
    assert "access_token" in said
    assert "credential field" in said


# ===========================================================================
# Status, storage and exit codes
# ===========================================================================


class _FakeResult:
    """What a provider returns, without a provider."""

    def __init__(self, role: str) -> None:
        self.data = {"ok": True, "role": role}
        self.model = "claude-fake-1"
        self.duration_ms = 91
        self.input_tokens = 412
        self.output_tokens = 38
        self.attempts = 1
        self.request_id = f"req_{role}"


class _FakeProvider:
    """Answers every role, conformingly, and calls nothing."""

    #: The health endpoint reads these, so a stand-in has to carry them.
    name = "anthropic"
    model = "claude-fake-1"

    def __init__(self) -> None:
        self.calls = 0

    @property
    def configured(self) -> bool:
        return True

    def status(self):
        from backend.llm.base import ProviderStatus

        return ProviderStatus(provider=self.name, model=self.model,
                              configured=True, state="connected",
                              detail="a stand-in, for tests")

    def structured(self, **kwargs):
        self.calls += 1
        return _FakeResult(str(kwargs.get("role") or ""))


@pytest.fixture
def offline_quick(monkeypatch):
    """A Quick run that makes no network call and spends nothing.

    Section 8 of the brief: no live Anthropic call may be made from this
    environment. The provider, the eligibility gate and the live smoke suite
    are all replaced, so what is exercised is this module's own logic.
    """
    import backend.llm as llm
    from backend.validation import live_smoke

    provider = _FakeProvider()
    monkeypatch.setattr(llm, "get_provider", lambda *a, **k: provider)
    monkeypatch.setattr(lv, "_provider_status",
                        lambda: {"configured": True, "state": "connected"})

    # The eight smoke checks, stood in for at the seam Quick actually uses.
    # This fixture used to patch `_run_pytest`, because Quick used to shell out
    # to pytest — which the production image does not ship, and which is why a
    # healthy provider once reported FAILED.
    def _suite(stop_early: bool = False) -> live_smoke.Suite:
        return live_smoke.Suite(outcomes=[
            live_smoke.Outcome(
                check=check.id, passed=True, detail="held",
                calls=check.calls, model="claude-fake-1", latency_ms=210,
                input_tokens=400, output_tokens=30)
            for check in live_smoke.CHECKS
        ])

    monkeypatch.setattr(live_smoke, "run_all", _suite)
    return provider


def test_a_mocked_quick_run_passes_and_stores(offline_quick, tmp_path):
    report = lv.quick()
    assert report.passed is True, report.failures
    assert report.live_verified is True
    assert report.live_calls_made == 12, "4 role pings plus 8 smoke checks"
    assert offline_quick.calls == 4

    path = lv.store_result(report, tmp_path)
    assert path is not None
    assert report.status == lv.STATUS_LIVE_VERIFIED
    assert report.storage_error == ""
    assert lv.EXIT_FOR[report.status] == lv.EXIT_OK


def test_a_quick_run_records_the_model_that_actually_served(offline_quick):
    report = lv.quick()
    roles = [c for c in report.cases if c.component == "model_roles"]
    assert len(roles) == 4
    for case in roles:
        assert case.served_model == "claude-fake-1"
        assert case.schema_valid is True
        assert case.input_tokens == 412
        assert case.request_id


def test_a_storage_refusal_is_not_live_verified(offline_quick, tmp_path):
    """Section 5: calls passing is not the same as being verified.

    The behaviour this replaces printed REPORT NOT WRITTEN to stderr and then
    announced "live verified yes" three lines later. Both halves were true and
    only the second one governs what the product may show.
    """
    report = lv.quick()
    assert report.status == lv.STATUS_LIVE_VERIFIED

    # Something a scanner must refuse, arriving after the calls succeeded.
    report.invariants = [{"access_token": "leaked"}]
    path = lv.store_result(report, tmp_path)

    assert path is None
    assert report.status == lv.STATUS_PASSED_NOT_STORED
    assert report.storage_error
    assert lv.EXIT_FOR[report.status] == lv.EXIT_PASSED_NOT_STORED
    assert lv.EXIT_FOR[report.status] != lv.EXIT_OK

    # And the live calls DID pass. Both facts are kept, separately.
    assert report.passed is True
    assert report.live_verified is True

    # Nothing was stored, so nothing can be shown.
    assert lv.badge(tmp_path)["live_verified"] is False


def test_an_unwritable_directory_is_also_not_live_verified(
        offline_quick, tmp_path, monkeypatch):
    report = lv.quick()

    def _refuse(*a, **k):
        raise OSError("read-only file system")

    monkeypatch.setattr(lv, "write", _refuse)
    assert lv.store_result(report, tmp_path) is None
    assert report.status == lv.STATUS_PASSED_NOT_STORED
    assert "read-only" in report.storage_error


def test_a_failing_run_is_failed_not_unstored(offline_quick, tmp_path,
                                              monkeypatch):
    from backend.validation import live_smoke

    def _broken(stop_early: bool = False) -> live_smoke.Suite:
        return live_smoke.Suite(outcomes=[
            live_smoke.Outcome(check=c.id, passed=False, detail="did not hold")
            for c in live_smoke.CHECKS])

    monkeypatch.setattr(live_smoke, "run_all", _broken)
    report = lv.quick()
    lv.store_result(report, tmp_path)

    assert report.status == lv.STATUS_FAILED
    assert lv.EXIT_FOR[report.status] == lv.EXIT_FAILED


def test_an_ineligible_run_says_so(tmp_path):
    report = lv.Report()
    lv._stamp(report)
    if report.key_present:
        pytest.skip("A provider key is configured in this environment.")
    ran = lv.quick()
    assert ran.status == lv.STATUS_NOT_ELIGIBLE
    assert lv.EXIT_FOR[ran.status] == lv.EXIT_NOT_ELIGIBLE


def test_a_dry_run_is_its_own_status_and_exits_zero():
    report = lv.dry_run()
    assert report.status == lv.STATUS_DRY_RUN
    assert lv.EXIT_FOR[report.status] == lv.EXIT_OK


def test_a_dry_run_makes_no_provider_call(monkeypatch):
    """Section 8, as a property rather than a promise."""
    import backend.llm as llm

    def _forbidden(*a, **k):
        raise AssertionError("a dry run must never reach the provider")

    monkeypatch.setattr(llm, "get_provider", _forbidden)
    report = lv.dry_run()
    assert report.live_calls_made == 0
    assert report.spends_credits is False


def test_every_status_has_an_exit_code_and_an_explanation():
    for status in (lv.STATUS_DRY_RUN, lv.STATUS_LIVE_VERIFIED,
                   lv.STATUS_PASSED_NOT_STORED, lv.STATUS_FAILED,
                   lv.STATUS_NOT_ELIGIBLE):
        assert status in lv.EXIT_FOR
        assert lv.STATUS_DETAIL.get(status), f"{status} is not explained"
    assert lv.EXIT_FOR[lv.STATUS_LIVE_VERIFIED] == 0
    assert len({lv.EXIT_FOR[s] for s in
                (lv.STATUS_FAILED, lv.STATUS_PASSED_NOT_STORED,
                 lv.STATUS_NOT_ELIGIBLE)}) == 3, (
        "the three failure modes must be distinguishable by exit code")


# ===========================================================================
# What /api/v1/ai/status shows
# ===========================================================================


def _stored_quick(tmp_path, provider) -> dict:
    report = lv.quick()
    lv.store_result(report, tmp_path)
    return report.to_dict()


def test_the_badge_reports_the_commit_and_configuration_it_was_made_on(
        offline_quick, tmp_path):
    _stored_quick(tmp_path, offline_quick)
    found = lv.badge(tmp_path)

    current = lv.Report()
    lv._stamp(current)

    assert found["live_verified"] is True
    assert found["stale"] is False
    assert found["status"] == lv.STATUS_LIVE_VERIFIED
    assert found["verified_sha"] == current.git_sha
    assert found["verified_fingerprint"] == current.configuration_fingerprint
    assert found["running_sha"] == current.git_sha
    assert found["mode"] == lv.QUICK
    assert found["verified_at"], "the report timestamp must be shown"
    assert found["calls"] == 12
    assert set(found["role_models"]) == {"router", "planner",
                                         "interpretation", "critic"}


@pytest.mark.parametrize("field,value,expected", [
    ("git_sha", "0" * 40, "commit"),
    ("configuration_fingerprint", "deadbeefdeadbeef", "model configuration"),
])
def test_a_moved_build_or_configuration_goes_stale(
        offline_quick, tmp_path, field, value, expected):
    payload = _stored_quick(tmp_path, offline_quick)
    payload[field] = value
    path = tmp_path / f"live_ai_verification_{payload['git_sha'][:12]}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    if field == "git_sha":
        # Filed under a different commit. The badge looks for THIS build's
        # file, so the correctly-named one has to go before the question can
        # be asked at all.
        current = lv.Report()
        lv._stamp(current)
        (tmp_path / f"live_ai_verification_{current.git_sha[:12]}.json").unlink()
        assert lv.badge(tmp_path)["live_verified"] is False
        return

    found = lv.badge(tmp_path)
    assert found["live_verified"] is False
    assert found["stale"] is True
    assert expected in found["reason"]


def test_a_changed_role_model_makes_the_fingerprint_move(monkeypatch):
    """Section 6: model or effort moving is what STALE has to catch."""
    before = lv.Report()
    lv._stamp(before)

    monkeypatch.setenv("AI_PLANNER_MODEL", "some-other-model")
    after = lv.Report()
    lv._stamp(after)

    assert after.configuration_fingerprint != before.configuration_fingerprint
    assert lv.is_stale({**before.to_dict(), "live_verified": True})[0] is True


def test_a_changed_role_effort_makes_the_fingerprint_move(monkeypatch):
    before = lv.Report()
    lv._stamp(before)

    monkeypatch.setenv("AI_PLANNER_EFFORT", "high")
    after = lv.Report()
    lv._stamp(after)

    assert after.configuration_fingerprint != before.configuration_fingerprint


def test_the_api_serves_the_stored_verification(offline_quick, tmp_path,
                                                monkeypatch):
    """The whole round trip, through the endpoint the header chip calls."""
    from fastapi.testclient import TestClient

    from backend.api.main import app

    _stored_quick(tmp_path, offline_quick)
    monkeypatch.setattr(lv, "REPORT_DIR", tmp_path)

    response = TestClient(app).get("/api/v1/ai/status")
    assert response.status_code == 200
    shown = response.json()["live_verification"]

    current = lv.Report()
    lv._stamp(current)
    assert shown["live_verified"] is True
    assert shown["stale"] is False
    assert shown["status"] == lv.STATUS_LIVE_VERIFIED
    assert shown["verified_sha"] == current.git_sha
    assert shown["verified_fingerprint"] == current.configuration_fingerprint
    assert shown["mode"] == lv.QUICK
    assert shown["verified_at"]
    assert "not a measure of accuracy" in shown["caveat"]
    assert json.dumps(shown).count("sk-ant") == 0


def test_the_api_shows_nothing_when_nothing_was_stored(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from backend.api.main import app

    monkeypatch.setattr(lv, "REPORT_DIR", tmp_path)
    shown = TestClient(app).get("/api/v1/ai/status").json()["live_verification"]
    assert shown["live_verified"] is False
    assert shown["stale"] is False
    assert shown["command"].endswith("-Quick")
