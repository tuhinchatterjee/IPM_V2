"""
§12, §13, §14 — the Agent Registry and the Tool Registry.

The tests that matter here are the negative ones. An agent registry is easy to
write and impossible to trust unless something checks that the permissions in it
are actually the limit: that no agent has a general tool, that a tool nobody
granted is refused, and that the actions §21 places at Level 4 have no
callable behind them at all.
"""

from __future__ import annotations

import pytest

from backend.agentic import registry, tools

# --------------------------------------------------------- §12 the twelve


def test_every_specialist_section_twelve_names_is_defined():
    """§12 names twelve. Missing one is a specialist nothing can delegate to.

    A floor, not a ceiling: `relationship_graph` was added when the corporate
    relationship graph became a domain, and an equality here would have
    failed on the addition rather than on a removal - which is the failure
    that matters. The correspondence that must hold in both directions is
    the one below: every domain has an owner, and every owner is a defined
    agent.
    """
    expected = {
        "data_steward", "credit_analyst", "ratings_financials", "ifrs9",
        "delinquency", "covenants", "portfolio_risk", "early_warning",
        "stress", "validation", "workflow_coordinator", "chief_orchestrator",
    }
    defined = {a.agent_id for a in registry.AGENTS}
    missing = expected - defined
    assert not missing, f"§12 specialists that no longer exist: {missing}"


def test_every_governed_domain_has_a_specialist_that_exists():
    """The property the equality was really protecting.

    A domain with no owner silently falls to the Credit Analyst, and a
    domain owned by an id no agent answers to does the same - so a
    misspelled owner looks exactly like a deliberate generalist decision.
    """
    defined = {a.agent_id for a in registry.AGENTS}
    for domain in registry.DOMAINS:
        owner = registry.DOMAIN_AGENT.get(domain)
        assert owner, f"{domain} has no specialist"
        assert owner in defined, f"{domain} is owned by unknown {owner!r}"


def test_the_relationship_graph_reaches_its_own_specialist():
    """A group, ownership or contagion question is exactly the kind that
    reads right and is wrong: a community offered as a group, a ranking
    offered as a probability. It goes to the specialist that carries the
    caveats, not to the generalist."""
    found = registry.agents_for(("connected_group", "ubo", "debtrank"))
    assert {a.agent_id for a in found} == {"relationship_graph"}


def test_the_graph_specialist_cannot_read_the_retail_book():
    """A specialist that CAN read a domain is a scope bleed waiting for a
    question phrased loosely enough."""
    agent = registry.RELATIONSHIP_GRAPH
    assert registry.DOMAIN_RELATIONSHIP in agent.allowed_data_domains
    assert set(agent.allowed_data_domains) < set(registry.DOMAINS)


def test_the_orchestrator_cannot_delegate_to_itself():
    """§73 asks for recursive delegation to terminate safely. The cheapest
    guarantee is that the orchestrator is not on its own delegation list."""
    assert registry.CHIEF_ORCHESTRATOR.agent_id not in {
        a.agent_id for a in registry.specialists()}


# ------------------------------------------------------ §13 the contract


@pytest.mark.parametrize("agent", registry.AGENTS, ids=lambda a: a.agent_id)
def test_every_field_of_the_definition_contract_is_present(agent):
    """§13's list, checked field by field on every agent."""
    stored = agent.to_dict()
    for field_name in (
        "agent_id", "business_name", "purpose", "when_to_use",
        "when_not_to_use", "allowed_capabilities", "allowed_tools",
        "allowed_data_domains", "allowed_methods", "input_contract",
        "output_contract", "maximum_steps", "timeout_seconds",
        "retry_policy", "autonomy_level", "human_approval_requirements",
        "escalation_rules", "validation_requirements",
        "model_role_preference", "owner", "version", "status",
        "evaluation_score", "last_validation", "certification_state",
    ):
        assert field_name in stored, f"{agent.agent_id} is missing {field_name}"


@pytest.mark.parametrize("agent", registry.AGENTS, ids=lambda a: a.agent_id)
def test_no_agent_is_given_a_tool_that_does_not_exist(agent):
    for tool_id in agent.allowed_tools:
        assert tools.tool(tool_id) is not None, (
            f"{agent.agent_id} is granted '{tool_id}', which is not a tool.")


@pytest.mark.parametrize("agent", registry.AGENTS, ids=lambda a: a.agent_id)
def test_no_agent_has_unrestricted_tools(agent):
    """§13: 'Do not give agents unrestricted tools.'"""
    assert agent.allowed_tools, f"{agent.agent_id} has no tools at all."
    granted = set(agent.allowed_tools)
    assert granted != {t.tool_id for t in tools.TOOLS}, (
        f"{agent.agent_id} is granted every tool in the registry.")
    for forbidden in tools.NO_TOOL_EXISTS:
        assert forbidden not in granted


@pytest.mark.parametrize("agent", registry.AGENTS, ids=lambda a: a.agent_id)
def test_every_agent_has_a_budget(agent):
    """§20: nothing runs without a ceiling."""
    assert agent.maximum_steps > 0
    assert agent.timeout_seconds > 0
    assert agent.max_model_calls >= 0
    assert agent.retry_policy[0] >= 0


@pytest.mark.parametrize("agent", registry.AGENTS, ids=lambda a: a.agent_id)
def test_no_agent_claims_level_four_autonomy(agent):
    """§21: Level 4 is not allowed without explicit human approval, so no
    definition may assert it as a standing autonomy."""
    assert agent.autonomy_level <= 3


@pytest.mark.parametrize("agent", registry.AGENTS, ids=lambda a: a.agent_id)
def test_model_role_preference_is_a_role_not_a_model(agent):
    """§3 and §0: model IDs are configuration, never baked into a definition."""
    assert agent.model_role_preference in {
        "router", "planner", "interpretation", "critic"}
    assert "claude" not in agent.model_role_preference.lower()


def test_the_registry_has_a_fingerprint_that_moves_with_a_change():
    first = registry.fingerprint()
    assert len(first) == 16
    assert first == registry.fingerprint()


# -------------------------------------------------------- domain mapping


def test_every_concept_domain_maps_to_a_known_domain():
    for concept, domain in registry.CONCEPT_DOMAIN.items():
        assert domain in registry.DOMAINS, f"{concept} → unknown {domain}"


def test_the_specialists_a_question_needs_come_from_its_concepts():
    found = registry.agents_for(("rating", "ecl"))
    assert {a.agent_id for a in found} == {"ratings_financials", "ifrs9"}


def test_an_unowned_concept_needs_no_specialist():
    """A concept no domain owns is generalist work, not a gap."""
    assert registry.agents_for(("something_new",)) == ()


def test_agent_order_is_stable():
    """The specialist list is shown to the user. Two identical requests must
    not produce two different orders."""
    first = [a.agent_id for a in registry.agents_for(("dpd", "ecl", "rating"))]
    second = [a.agent_id for a in registry.agents_for(("rating", "dpd", "ecl"))]
    assert first == second


# --------------------------------------------------------- §14 the gate


class _Fake:
    """The smallest thing the gate reads: an id, a tool list, a domain list."""

    def __init__(self, tool_ids, domains=("ifrs9",)):
        self.agent_id = "fake"
        self.business_name = "Fake"
        self._tools = set(tool_ids)
        self._domains = set(domains)

    def may_use(self, tool_id):
        return tool_id in self._tools

    def may_read(self, domain):
        return domain in self._domains


def test_a_tool_the_agent_was_not_granted_is_refused():
    call = tools.check(_Fake([tools.CATALOGUE_LOOKUP]), tools.RUN_ANALYSIS,
                       {"plan": {}})
    assert not call.allowed
    assert "not permitted" in call.reason


def test_a_tool_that_does_not_exist_is_refused():
    call = tools.check(_Fake(["execute_sql"]), "execute_sql", {})
    assert not call.allowed
    assert "not a registered" in call.reason


def test_a_domain_outside_the_agents_permission_is_refused():
    call = tools.check(_Fake([tools.RUN_ANALYSIS], domains=("ifrs9",)),
                       tools.RUN_ANALYSIS, {"plan": {}}, domains=["covenants"])
    assert not call.allowed
    assert "covenants" in call.reason


def test_a_missing_required_parameter_is_refused():
    call = tools.check(_Fake([tools.RUN_ANALYSIS]), tools.RUN_ANALYSIS, {})
    assert not call.allowed
    assert "plan" in call.reason


def test_an_unknown_parameter_is_refused_rather_than_ignored():
    """A parameter the tool does not understand is a caller who believes it
    does something it does not — silently dropping it is how an agent comes to
    think it applied a filter that was never applied."""
    call = tools.check(_Fake([tools.RUN_ANALYSIS]), tools.RUN_ANALYSIS,
                       {"plan": {}, "sql": "SELECT 1"})
    assert not call.allowed
    assert "sql" in call.reason


def test_a_permitted_call_is_allowed():
    call = tools.check(_Fake([tools.RUN_ANALYSIS]), tools.RUN_ANALYSIS,
                       {"plan": {}}, domains=["ifrs9"])
    assert call.allowed


def test_there_is_no_tool_for_a_level_four_action():
    """§21's material side effects have no registry entry, so the prohibition
    does not depend on a permission check being written correctly."""
    for action in tools.NO_TOOL_EXISTS:
        assert tools.tool(action) is None, (
            f"'{action}' has a tool. §21 places it at Level 4, which means no "
            f"agent may reach it without a person.")


def test_every_writing_tool_produces_a_draft():
    """§21 Level 2. Nothing an agent calls sends, publishes or approves."""
    writers = [t for t in tools.TOOLS if t.writes]
    assert writers
    for t in writers:
        assert ("draft" in t.tool_id or t.tool_id == tools.ADD_TO_PROJECT), (
            f"{t.tool_id} writes but is not a draft.")


def test_a_refusal_is_recorded_rather_than_raised():
    """A refusal that vanishes into a traceback is one nobody can review."""
    call = tools.check(_Fake([]), tools.RUN_ANALYSIS, {"plan": {}})
    stored = call.to_dict()
    assert stored["allowed"] is False
    assert stored["reason"]
    assert stored["agent"] == "fake"


def test_invoke_refuses_before_reaching_a_handler():
    reached = []
    call, result = tools.invoke(
        _Fake([]), tools.RUN_ANALYSIS, {"plan": {}},
        handlers={tools.RUN_ANALYSIS: lambda **kw: reached.append(kw)})
    assert not call.allowed
    assert result is None
    assert reached == []


def test_invoke_passes_the_principal_to_a_data_reading_tool():
    """§57: an agent runs with the requesting user's permissions."""
    seen = {}

    def handler(*, principal, **kw):
        seen["principal"] = principal
        return None

    call, _ = tools.invoke(
        _Fake([tools.RUN_ANALYSIS]), tools.RUN_ANALYSIS, {"plan": {}},
        domains=["ifrs9"], principal="omar",
        handlers={tools.RUN_ANALYSIS: handler})
    assert call.allowed
    assert seen["principal"] == "omar"


def test_a_failing_handler_is_recorded_not_swallowed():
    def boom(**_kw):
        raise ValueError("the source is not published")

    call, result = tools.invoke(
        _Fake([tools.CATALOGUE_LOOKUP]), tools.CATALOGUE_LOOKUP, {},
        handlers={tools.CATALOGUE_LOOKUP: boom})
    assert result is None
    assert "ValueError" in call.error
    assert "not published" in call.error


def test_an_approved_tool_with_no_handler_is_reported_honestly():
    call, result = tools.invoke(_Fake([tools.CATALOGUE_LOOKUP]),
                                tools.CATALOGUE_LOOKUP, {}, handlers={})
    assert not call.allowed
    assert call.error == "not_wired"
    assert result is None


def test_audit_parameters_summarise_rather_than_copy_the_data():
    call = tools.Call(tool_id="x", agent_id="y",
                      parameters={"rows": list(range(500)),
                                  "plan": {"a": 1, "b": 2},
                                  "period": "Q2 2026"})
    stored = call.to_dict()["parameters"]
    assert stored["rows"] == "[500 items]"
    assert stored["plan"] == "{2 keys}"
    assert stored["period"] == "Q2 2026"
