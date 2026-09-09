"""The Cockpit's two model roles fail closed.

The rest of CreditProbe resolves a model generously: role, then a nearer role,
then AI_MODEL, then the provider SDK's own default. That is right there,
because an unconfigured deployment still runs — the deterministic reader does
the reading, and refusing to start would refuse a supported mode.

The Cockpit has no deterministic reader. Every answer it gives is authored by
a model, so "which model" is not a preference, it is the claim. An answer
served by whatever the SDK happened to ship is an answer nobody can attribute,
and a commissioning run against it measures an unknown.

So these tests assert the opposite of generosity: that each route by which a
model id could arrive without an operator choosing it is closed, and that the
id which is chosen is the id that reaches the wire.

The provider here is the labelled mock. What it proves is which model id this
application puts in the request — an application property, and exactly what a
mock can prove. It says nothing about how any model behaves.
"""

from __future__ import annotations

import json

import pytest

from backend.cockpit_agentic import models as M
from backend.cockpit_agentic import states as st
from tests.cockpit_agentic.conftest import (TEST_PREPROCESS_MODEL,
                                            TEST_REASONING_MODEL, scores)
from tests.cockpit_agentic.fake_provider import FakeProvider

GOOD_SQL = ("SELECT reporting_quarter, sum(ecl_reported) AS ecl "
            "FROM cockpit_facility_quarter GROUP BY 1 ORDER BY 1 DESC LIMIT 2")

PLAN = {"plan_id": "plan-m1", "subquestions": ["the change in reported ECL"],
        "fields_required": ["ecl_reported"],
        "method_summary": "compare the two latest quarters"}

ANSWER = {"decision": "ANSWER",
          "per_subquestion": [{"subquestion": "the change in reported ECL",
                               "answered": True}],
          "answer": {"narrative": "ECL fell.", "complete": True}}


def _steps(code=GOOD_SQL, step_id="s1"):
    return [{"step_id": step_id, "language": "sql", "code": code}]


def _provider(sonnet_answers, *turns):
    return FakeProvider(structured_script=list(sonnet_answers),
                        converse_script=[(lambda _r, t=t: t) for t in turns])


# ============================================== resolution, on its own

def test_both_variables_configured_resolves_to_exactly_those_two(monkeypatch):
    monkeypatch.setenv("AI_COCKPIT_PREPROCESS_MODEL", "some-fast-model")
    monkeypatch.setenv("AI_COCKPIT_REASONING_MODEL", "some-strong-model")
    resolved = M.resolve()
    assert resolved.preprocess == "some-fast-model"
    assert resolved.reasoning == "some-strong-model"
    assert resolved.source == {M.PREPROCESS_ROLE: M.PREPROCESS_VAR,
                               M.REASONING_ROLE: M.REASONING_VAR}
    assert resolved.to_dict()["fallback_used"] is False


def test_a_missing_preprocess_model_fails_closed(monkeypatch):
    monkeypatch.delenv("AI_COCKPIT_PREPROCESS_MODEL", raising=False)
    monkeypatch.setenv("AI_COCKPIT_REASONING_MODEL", "some-strong-model")
    with pytest.raises(M.ModelConfigurationMissing) as caught:
        M.resolve()
    assert caught.value.status == "MODEL_CONFIGURATION_MISSING"
    assert "AI_COCKPIT_PREPROCESS_MODEL" in str(caught.value)
    assert caught.value.variables == ("AI_COCKPIT_PREPROCESS_MODEL",)


def test_a_missing_reasoning_model_fails_closed(monkeypatch):
    monkeypatch.setenv("AI_COCKPIT_PREPROCESS_MODEL", "some-fast-model")
    monkeypatch.delenv("AI_COCKPIT_REASONING_MODEL", raising=False)
    with pytest.raises(M.ModelConfigurationMissing) as caught:
        M.resolve()
    assert "AI_COCKPIT_REASONING_MODEL" in str(caught.value)
    assert caught.value.variables == ("AI_COCKPIT_REASONING_MODEL",)


def test_a_blank_or_whitespace_value_is_not_a_configured_value(monkeypatch):
    for blank in ("", "   ", "\t\n"):
        monkeypatch.setenv("AI_COCKPIT_PREPROCESS_MODEL", blank)
        monkeypatch.setenv("AI_COCKPIT_REASONING_MODEL", "some-strong-model")
        with pytest.raises(M.ModelConfigurationMissing):
            M.resolve()


def test_a_malformed_value_is_refused_and_shown_back(monkeypatch):
    """An operator who typed a trailing comment or left a shell variable
    unexpanded needs to see what they actually set. These are model ids, not
    secrets, and nothing else from the environment is echoed."""
    for bad in ("claude-opus-5 # the good one", "$AI_MODEL",
                '"claude-opus-5"', "claude opus 5", "a"):
        monkeypatch.setenv("AI_COCKPIT_PREPROCESS_MODEL", "some-fast-model")
        monkeypatch.setenv("AI_COCKPIT_REASONING_MODEL", bad)
        with pytest.raises(M.ModelConfigurationMissing) as caught:
            M.resolve()
        assert repr(bad) in str(caught.value)


# ============================================ the routes that must be closed

def test_ai_model_cannot_substitute(monkeypatch):
    """The shared default serves seven other roles and must not serve these."""
    monkeypatch.delenv("AI_COCKPIT_PREPROCESS_MODEL", raising=False)
    monkeypatch.delenv("AI_COCKPIT_REASONING_MODEL", raising=False)
    monkeypatch.setenv("AI_MODEL", "a-shared-model-nobody-chose-for-cockpit")
    with pytest.raises(M.ModelConfigurationMissing) as caught:
        M.resolve()
    assert "a-shared-model-nobody-chose-for-cockpit" not in str(caught.value)
    assert "no fallback to AI_MODEL" in str(caught.value)


def test_another_role_cannot_substitute(monkeypatch):
    """Before this change the preprocess role borrowed the router's id and the
    reasoning role the complex planner's, and reported that it had."""
    monkeypatch.delenv("AI_COCKPIT_PREPROCESS_MODEL", raising=False)
    monkeypatch.delenv("AI_COCKPIT_REASONING_MODEL", raising=False)
    monkeypatch.setenv("AI_ROUTER_MODEL", "a-router-model")
    monkeypatch.setenv("AI_COMPLEX_PLANNER_MODEL", "a-planner-model")
    with pytest.raises(M.ModelConfigurationMissing):
        M.resolve()

    from backend.llm import roles
    assert roles.role(roles.COCKPIT_PREPROCESS).model == ""
    assert roles.role(roles.COCKPIT_REASONING).model == ""
    # And not reported as INHERITED either, because nothing was inherited.
    assert roles.role(roles.COCKPIT_REASONING).inherited is False


def test_the_sdk_default_cannot_substitute(monkeypatch):
    """`AnthropicProvider.converse` substitutes its own pinned default for an
    empty model. Correct for the legacy paths; forbidden here. `require` is
    the gate that stops an empty id ever reaching it."""
    from backend.llm.anthropic_provider import AnthropicProvider

    assert AnthropicProvider.model, "the SDK default exists and is the risk"
    for role in (M.PREPROCESS_ROLE, M.REASONING_ROLE):
        with pytest.raises(M.ModelConfigurationMissing) as caught:
            M.require("", role=role)
        assert "substituted its own default" in str(caught.value)
        assert AnthropicProvider.model not in str(caught.value)


def test_the_shared_resolver_reports_the_cockpit_roles_as_strict(monkeypatch):
    """Settings must show what the runtime will do. A page that displayed an
    inherited model for a role that refuses to use one would be the same lie
    in a different place."""
    from backend.llm import roles

    monkeypatch.delenv("AI_COCKPIT_PREPROCESS_MODEL", raising=False)
    monkeypatch.delenv("AI_COCKPIT_REASONING_MODEL", raising=False)

    assert roles.STRICT_ROLES == {roles.COCKPIT_PREPROCESS,
                                  roles.COCKPIT_REASONING}
    problems = roles.verify(object())
    assert any("AI_COCKPIT_PREPROCESS_MODEL is not set" in p for p in problems)
    assert any("AI_COCKPIT_REASONING_MODEL is not set" in p for p in problems)

    # Exactly two roles are strict. Every other one still resolves generously,
    # which is the behaviour the rest of the product depends on.
    monkeypatch.setenv("AI_PLANNER_MODEL", "a-planner-model")
    assert roles.COMPLEX_PLANNER not in roles.STRICT_ROLES
    borrowed = roles.role(roles.COMPLEX_PLANNER)
    assert borrowed.model == "a-planner-model" and borrowed.inherited is True


# ================================================ the ids that reach the wire

def test_the_configured_preprocess_id_serves_both_preprocessing_passes(
        runtime_factory, sonnet_answers):
    """Sonnet pass 1 and pass 2, read off the recorded requests."""
    provider = _provider(
        sonnet_answers,
        {"decision": "PROCEED_COCKPIT", "scores": scores(),
         "public_explanation": "x", "plan": PLAN, "steps": _steps()},
        ANSWER)
    runtime_factory(provider).run("How much did ECL change?")

    preprocessing = [r for r in provider.structured_requests
                     if r.get("purpose", "").startswith("sonnet")]
    assert len(preprocessing) >= 2, provider.structured_requests
    for request in preprocessing:
        assert request["model"] == TEST_PREPROCESS_MODEL
        assert request["model"] != TEST_REASONING_MODEL


def test_the_configured_reasoning_id_serves_every_analytical_stage(
        runtime_factory, sonnet_answers):
    """Functionality selection, planning, repair, sufficiency review and the
    final interpretation. Every one, read off the recorded requests."""
    failing = "SELECT pd_12_month FROM cockpit_facility_quarter"
    provider = _provider(
        sonnet_answers,
        {"decision": "PROCEED_COCKPIT", "scores": scores(),
         "public_explanation": "x", "plan": PLAN, "steps": _steps(failing)},
        {"action": "submit_repaired_code", "plan": PLAN,
         "what_went_wrong": "no such column", "steps": _steps(GOOD_SQL, "s2")},
        ANSWER)
    outcome = runtime_factory(provider).run("How much did ECL change?")

    assert outcome.status == st.COMPLETED
    purposes = provider.purposes()
    assert purposes == ["opus_gate_and_plan", "opus_repair", "opus_review"]
    for request in provider.requests:
        assert request["model"] == TEST_REASONING_MODEL, request["purpose"]
        assert request["model"] != TEST_PREPROCESS_MODEL


def test_no_request_anywhere_in_a_run_goes_out_without_a_model(
        runtime_factory, sonnet_answers):
    provider = _provider(
        sonnet_answers,
        {"decision": "PROCEED_COCKPIT", "scores": scores(),
         "public_explanation": "x", "plan": PLAN, "steps": _steps()},
        ANSWER)
    runtime_factory(provider).run("How much did ECL change?")
    for request in provider.requests + provider.structured_requests:
        assert (request.get("model") or "").strip(), request.get("purpose")


# ================================================= the stop, end to end

def test_an_unconfigured_cockpit_stops_and_never_answers(
        runtime_factory, sonnet_answers, monkeypatch):
    """No deterministic answering fallback. The request ends with a status an
    operator can act on and nothing is substituted for the analysis."""
    monkeypatch.delenv("AI_COCKPIT_REASONING_MODEL", raising=False)
    provider = _provider(sonnet_answers)
    outcome = runtime_factory(provider).run("How much did ECL change?")

    assert outcome.status == st.MODEL_CONFIGURATION_MISSING
    assert outcome.envelope.kind == "stop"
    assert outcome.envelope.complete is False
    assert "AI_COCKPIT_REASONING_MODEL" in outcome.envelope.narrative
    assert "AI_COCKPIT_REASONING_MODEL" in outcome.envelope.what_would_help
    # Nothing was asked of the provider, and nothing was answered without it.
    assert provider.requests == []
    assert provider.structured_requests == []
    assert outcome.results == []


def test_the_stop_names_both_variables_when_both_are_missing(
        runtime_factory, sonnet_answers, monkeypatch):
    monkeypatch.delenv("AI_COCKPIT_PREPROCESS_MODEL", raising=False)
    monkeypatch.delenv("AI_COCKPIT_REASONING_MODEL", raising=False)
    outcome = runtime_factory(_provider(sonnet_answers)).run("anything")
    assert outcome.status == st.MODEL_CONFIGURATION_MISSING
    for variable in ("AI_COCKPIT_PREPROCESS_MODEL",
                     "AI_COCKPIT_REASONING_MODEL"):
        assert variable in outcome.envelope.what_would_help


def test_a_model_the_provider_refuses_stops_with_model_unavailable():
    """Configured and wrong is a different problem from not configured, and
    an operator needs to be told which."""
    class Refusing:
        configured = True
        name = "anthropic"

        def count_tokens(self, **_kw):
            raise RuntimeError("model: not_found_error")

    resolved = M.CockpitModels(preprocess="a-fast-model",
                              reasoning="a-model-that-does-not-exist")
    with pytest.raises(M.ModelUnavailable) as caught:
        M.verify_live(Refusing(), resolved)
    assert caught.value.status == "MODEL_UNAVAILABLE"
    assert "a-model-that-does-not-exist" in str(caught.value)
    assert "rather than falling back" in str(caught.value)


def test_verification_uses_the_exact_configured_ids():
    seen = []

    class Counting:
        configured = True
        name = "anthropic"

        def count_tokens(self, *, model="", **_kw):
            seen.append(model)
            return 7

    verified = M.verify_live(
        Counting(), M.CockpitModels(preprocess="fast-id", reasoning="strong-id"))
    assert seen == ["fast-id", "strong-id"]
    assert verified.verified is True
    assert verified.verification["method"] == "provider_count_tokens"


def test_a_provider_that_cannot_count_leaves_the_ids_unverified():
    """Not a pass and not a failure. Reported as what it is."""
    class Silent:
        configured = True
        name = "anthropic"

    result = M.verify_live(Silent(),
                           M.CockpitModels(preprocess="a", reasoning="b"))
    assert result.verified is False
    assert "could not be checked" in result.verification["why"]


# ==================================================== metadata, and the key

def test_every_run_records_the_exact_ids_that_served_it(
        runtime_factory, sonnet_answers):
    provider = _provider(
        sonnet_answers,
        {"decision": "PROCEED_COCKPIT", "scores": scores(),
         "public_explanation": "x", "plan": PLAN, "steps": _steps()},
        ANSWER)
    body = runtime_factory(provider).run("How much did ECL change?").to_dict()

    recorded = body["models"]
    assert recorded["preprocess_model"] == TEST_PREPROCESS_MODEL
    assert recorded["reasoning_model"] == TEST_REASONING_MODEL
    assert recorded["fallback_used"] is False
    assert recorded["source"] == {M.PREPROCESS_ROLE: M.PREPROCESS_VAR,
                                  M.REASONING_ROLE: M.REASONING_VAR}


def test_the_diagnostics_report_the_model_configuration_state(monkeypatch):
    monkeypatch.setenv("AI_COCKPIT_PREPROCESS_MODEL", "fast-id")
    monkeypatch.setenv("AI_COCKPIT_REASONING_MODEL", "strong-id")
    good = M.status()
    assert good["configured"] is True and good["status"] == "OK"
    assert good["preprocess_model"] == "fast-id"

    monkeypatch.delenv("AI_COCKPIT_REASONING_MODEL", raising=False)
    bad = M.status()
    assert bad["configured"] is False
    assert bad["status"] == "MODEL_CONFIGURATION_MISSING"
    assert bad["variables_to_set"] == ["AI_COCKPIT_REASONING_MODEL"]


def test_nothing_about_the_model_configuration_can_carry_the_credential(
        monkeypatch):
    """The ids are configuration and are reported. The key is a secret and is
    not, and this module must not become the place it leaks."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-do-not-print-me")
    monkeypatch.setenv("AI_COCKPIT_PREPROCESS_MODEL", "fast-id")
    monkeypatch.setenv("AI_COCKPIT_REASONING_MODEL", "strong-id")

    for blob in (json.dumps(M.status()),
                 json.dumps(M.resolve().to_dict())):
        assert "sk-ant" not in blob
        assert "do-not-print-me" not in blob
        assert "ANTHROPIC_API_KEY" not in blob

    monkeypatch.delenv("AI_COCKPIT_REASONING_MODEL", raising=False)
    assert "sk-ant" not in json.dumps(M.status())

    source = (M.__file__ and open(M.__file__).read()) or ""
    assert "ANTHROPIC_API_KEY" in source, "the docstring should name it"
    assert "os.environ.get(\"ANTHROPIC_API_KEY\")" not in source
    assert "settings.anthropic_api_key" not in source


def test_a_model_the_provider_refuses_stops_the_whole_request(
        runtime_factory, sonnet_answers):
    """End to end, and distinct from a provider outage. "The provider did not
    answer" and "the model you named does not exist here" have different
    remedies, so they are different statuses."""
    M.reset()

    class Refusing(FakeProvider):
        @property
        def configured(self):
            return True

        def count_tokens(self, **_kw):
            raise RuntimeError("404 model: not_found_error")

    provider = Refusing(structured_script=list(sonnet_answers),
                        converse_script=[])
    outcome = runtime_factory(provider).run("How much did ECL change?")

    assert outcome.status == st.MODEL_UNAVAILABLE
    assert TEST_REASONING_MODEL in outcome.envelope.narrative
    assert "rather than falling back" in outcome.envelope.narrative
    assert provider.requests == [] and provider.structured_requests == []
    M.reset()


def test_the_availability_check_costs_one_call_per_process_not_per_request(
        runtime_factory, sonnet_answers):
    """A correct configuration must not pay a token-count call on every
    question to re-establish that it is still correct."""
    M.reset()
    checks: list[str] = []

    class Counting(FakeProvider):
        @property
        def configured(self):
            return True

        def count_tokens(self, *, model="", system=None, **_kw):
            # The availability probe is unmistakable: a two-token payload.
            # Everything else through this method is the ordinary
            # count-before-you-send that guards the input cap.
            if system == "ok":
                checks.append(model)
            return 11

    for _ in range(3):
        provider = Counting(
            structured_script=list(sonnet_answers),
            converse_script=[
                lambda _r: {"decision": "PROCEED_COCKPIT", "scores": scores(),
                            "public_explanation": "x", "plan": PLAN,
                            "steps": _steps()},
                lambda _r: ANSWER])
        runtime_factory(provider).run("How much did ECL change?")

    # Two ids, checked once between them across three requests -- not once
    # per request, and not once per id per request.
    assert checks == [TEST_PREPROCESS_MODEL, TEST_REASONING_MODEL], checks
    M.reset()


def test_no_cockpit_module_can_put_the_credential_anywhere_a_reader_sees_it():
    """Requirement 8, read off the source of the whole package.

    Two modules legitimately touch `settings.anthropic_api_key`: `service`
    builds the provider with it and reports whether one is configured as a
    boolean. Neither renders it. Nothing else in the package may reach for it
    at all, and no module may log it.
    """
    import ast
    from pathlib import Path

    from backend.cockpit_agentic import models as models_module

    package = Path(models_module.__file__).parent
    may_construct_the_provider = {"service.py"}

    for path in sorted(package.rglob("*.py")):
        source = path.read_text()
        tree = ast.parse(source)

        # Reaching for the key at all, outside the one module that must.
        reaches = [node for node in ast.walk(tree)
                   if isinstance(node, ast.Attribute)
                   and node.attr == "anthropic_api_key"]
        env_reads = "ANTHROPIC_API_KEY" in source and "os.environ" in source
        if path.name not in may_construct_the_provider:
            assert not reaches, f"{path.name} reads the credential"
            assert not (env_reads and "get(\"ANTHROPIC_API_KEY\")" in source), \
                f"{path.name} reads the credential from the environment"

        # And nobody logs or formats it, including the module that holds it.
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            rendered = ast.dump(node)
            if "anthropic_api_key" not in rendered:
                continue
            function = node.func
            name = (function.attr if isinstance(function, ast.Attribute)
                    else getattr(function, "id", ""))
            assert name in ("bool", "AnthropicProvider"), (
                f"{path.name} passes the credential to {name}()")


def test_the_diagnostics_payload_never_carries_the_credential(monkeypatch):
    """Not the source this time: the actual JSON the browser is sent."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-never-render-this")
    monkeypatch.setenv("AI_COCKPIT_PREPROCESS_MODEL", "fast-id")
    monkeypatch.setenv("AI_COCKPIT_REASONING_MODEL", "strong-id")

    from backend.cockpit_agentic import service

    body = json.dumps(service.diagnostics(), default=str)
    assert "sk-ant" not in body
    assert "never-render-this" not in body
    # The ids ARE reported, because an operator has to be able to see which
    # models answered without reading a log.
    assert "fast-id" in body and "strong-id" in body


def test_the_preflight_reports_the_strict_roles_without_refusing_to_start(
        monkeypatch):
    """Two things that must both be true.

    An unset Cockpit role must be VISIBLE in the preflight — an administrator
    should not have to run a question to discover it. And it must not fail the
    preflight, because the Cockpit is off by default, the rest of the product
    runs without it, and a server that will not boot is one nobody can reach
    the settings page on to fix.
    """
    from backend.llm import roles

    class _Provider:
        name = "anthropic"
        supported_models = ("a-model",)

    monkeypatch.delenv("AI_COCKPIT_PREPROCESS_MODEL", raising=False)
    monkeypatch.delenv("AI_COCKPIT_REASONING_MODEL", raising=False)

    report = roles.preflight(_Provider())
    assert report["ok"], report["problems"]

    rows = {r["role"]: r for r in report["roles"]}
    for name in roles.STRICT_ROLES:
        assert rows[name]["state"] == roles.REQUIRED_UNSET
        assert "does not inherit" in rows[name]["note"]
        assert "MODEL_CONFIGURATION_MISSING" in rows[name]["note"]
    # And an ordinary unset role still says the provider's default serves it,
    # because for that role it does.
    assert rows[roles.ROUTER]["state"] == roles.UNCONFIGURED
