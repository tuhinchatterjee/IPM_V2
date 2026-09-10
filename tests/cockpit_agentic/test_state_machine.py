"""The state machine is complete, and every path through it ends.

Specification section 43. These read the transition registry rather than the
runtime, because the claim being made is about the GRAPH: that there is no
state a request can sit in with nowhere to go, no edge to a state that does
not exist, and no cycle that something finite does not close.

A registry that merely listed adjacency could not support the last of those.
Every edge here carries what it consumes, and the proof that the loops
terminate is that each back-edge spends something nothing replenishes.
"""

from __future__ import annotations

import pytest

from backend.cockpit_agentic import states as st


# ============================================== completeness of the graph

def test_every_non_terminal_state_has_an_outgoing_transition():
    """The property the whole section exists for: no request may remain
    RUNNING because its state has nowhere to go."""
    for state in st.WORKING:
        assert st.TRANSITIONS.get(state), f"{state} is a dead end"
        assert st.edges_from(state), f"{state} has no registry entry"


def test_every_terminal_state_has_no_outgoing_transition():
    for state in st.TERMINAL:
        assert st.TRANSITIONS.get(state, ()) == (), \
            f"{state} is terminal and has an exit"


def test_every_declared_edge_resolves_to_a_real_state():
    for edge in st.EDGES:
        assert edge.state in st.ALL_STATES, edge.state
        assert edge.next_state in st.ALL_STATES, edge.next_state


def test_every_state_is_reachable_from_the_start():
    seen = {st.RECEIVED}
    frontier = [st.RECEIVED]
    while frontier:
        state = frontier.pop()
        for target in st.TRANSITIONS.get(state, ()):
            if target not in seen:
                seen.add(target)
                frontier.append(target)
    unreachable = sorted(set(st.ALL_STATES) - seen)
    assert unreachable == [], f"unreachable states: {unreachable}"


def test_every_path_reaches_a_terminal_state():
    """Depth-first from every state: a terminal is always reachable.

    A state from which no terminal is reachable would be a request that can
    never finish, which is the failure mode section 42 forbids.
    """
    def reaches_terminal(state: str, seen: frozenset[str]) -> bool:
        if state in st.TERMINAL:
            return True
        if state in seen:
            return False
        return any(reaches_terminal(nxt, seen | {state})
                   for nxt in st.TRANSITIONS.get(state, ()))

    for state in st.ALL_STATES:
        assert reaches_terminal(state, frozenset()), \
            f"no terminal state is reachable from {state}"


def test_every_working_state_can_stop_on_every_hard_limit():
    """The deadline, cancellation, the budgets, the provider, the models, the
    packet size, the release and an internal failure can all happen at any
    moment. SUMMARIZING is the deliberate exception: it runs after the answer
    exists, and a guardrail reached while saving a summary must not take the
    answer away."""
    always = {st.STOPPED_TIME_LIMIT, st.CANCELLED, st.STOPPED_TOKEN_LIMIT,
              st.STOPPED_COST_LIMIT, st.STOPPED_EXECUTION_LIMIT,
              st.PROVIDER_ERROR, st.MODEL_CONFIGURATION_MISSING,
              st.MODEL_UNAVAILABLE, st.CONTEXT_TOO_LARGE, st.DATA_UNAVAILABLE,
              st.STOPPED_SECURITY, st.INTERNAL_ERROR}
    for state in st.WORKING:
        if state == st.SUMMARIZING:
            continue
        missing = always - set(st.TRANSITIONS[state])
        assert missing == set(), f"{state} cannot stop on {sorted(missing)}"


def test_a_guardrail_reached_while_summarizing_cannot_erase_the_answer():
    """Section 32. Every exit from SUMMARIZING is a delivered outcome."""
    for target in st.TRANSITIONS[st.SUMMARIZING]:
        assert target in st.TERMINAL
    assert st.STOPPED_TIME_LIMIT not in st.TRANSITIONS[st.SUMMARIZING]
    assert st.CANCELLED not in st.TRANSITIONS[st.SUMMARIZING]


# ================================================= no unbounded cycle

def _simple_cycles() -> list[list[st.Edge]]:
    """Every simple cycle among the working states, as edge lists.

    Only working states: a terminal has no exit, so no cycle can pass through
    one. Enumerated by depth-first search rather than asserted, because the
    point is to find cycles nobody thought of.
    """
    working = set(st.WORKING)
    found: list[list[st.Edge]] = []

    def walk(start: str, at: str, path: list[st.Edge],
             visited: set[str]) -> None:
        for edge in st.edges_from(at):
            if edge.next_state not in working:
                continue
            if edge.next_state == start:
                found.append(path + [edge])
                continue
            if edge.next_state in visited:
                continue
            walk(start, edge.next_state, path + [edge],
                 visited | {edge.next_state})

    for state in st.WORKING:
        walk(state, state, [], {state})
    return found


def test_every_cycle_spends_something_finite():
    """The boundedness proof, and the reason there is no open-ended loop.

    A cycle is safe only if going round it costs something that cannot be
    replenished. It does NOT follow that every back-edge must charge for it:
    the repair loop charges on the way IN to validation, not on the way back
    to planning, and requiring otherwise would either double-count or push the
    cost onto the wrong edge. What must be true is that every cycle contains
    at least one consuming edge -- so that is what is asserted, over the
    cycles actually present rather than over the ones expected.
    """
    finite = {"execution_submission", "analysis_round", "answer_rewrite"}
    cycles = _simple_cycles()
    assert cycles, "the search found no cycles at all, which cannot be right"
    for cycle in cycles:
        spent = [e.consumes for e in cycle if e.consumes]
        assert spent, (
            "this cycle can be traversed for free: "
            + " -> ".join(f"{e.state}[{e.event}]" for e in cycle)
            + f" -> {cycle[-1].next_state}")
        for consumed in spent:
            assert consumed in finite, consumed


def test_the_only_loops_are_the_three_that_are_counted():
    """Named as (states, what it costs), so a fourth cannot appear without
    this failing."""
    seen = {(tuple(sorted({e.state for e in cycle}
                          | {cycle[-1].next_state})),
             tuple(sorted({e.consumes for e in cycle if e.consumes})))
            for cycle in _simple_cycles()}
    assert seen == {
        # A candidate refused by the validator goes back to Opus. The
        # submission was spent entering VALIDATING.
        ((st.PLANNING, st.VALIDATING), ("execution_submission",)),
        # A candidate that ran and failed does the same.
        ((st.EXECUTING, st.PLANNING, st.VALIDATING),
         ("execution_submission",)),
        # A sufficiency review that wants a materially different approach.
        ((st.EXECUTING, st.PLANNING, st.REVIEWING, st.VALIDATING),
         ("analysis_round", "execution_submission")),
        # The single answer rewrite.
        ((st.ANSWERING, st.ANSWER_VALIDATION), ("answer_rewrite",)),
    }, sorted(seen)


def test_the_registry_documents_every_edge():
    for edge in st.EDGES:
        assert edge.event.strip(), f"{edge.state} -> {edge.next_state}"
        assert edge.condition.strip(), f"{edge.state} -> {edge.next_state}"


# ========================================== the required terminal states

REQUIRED_TERMINALS = (
    "COMPLETED", "WAITING_FOR_USER", "REDIRECTED", "UNSUPPORTED", "PARTIAL",
    "STOPPED_EXECUTION_LIMIT", "STOPPED_ANALYSIS_LIMIT", "STOPPED_TOKEN_LIMIT",
    "STOPPED_COST_LIMIT", "STOPPED_TIME_LIMIT", "STOPPED_SECURITY",
    "MODEL_CONFIGURATION_MISSING", "MODEL_UNAVAILABLE", "DATA_UNAVAILABLE",
    "CONTEXT_TOO_LARGE", "CANCELLED", "INTERNAL_ERROR")

#: The two this implementation adds, and why each is not covered by one above.
DOCUMENTED_EXTRAS = {
    "INSUFFICIENT_DATA": "the domain is readable and simply does not hold "
                         "what was asked. Distinct from DATA_UNAVAILABLE, "
                         "which is the release being unreadable.",
    "EXECUTION_FAILED": "every attempt failed for a reason inside the "
                        "analysis. Distinct from STOPPED_EXECUTION_LIMIT, "
                        "which is running out of attempts.",
    "PROVIDER_ERROR": "the provider did not answer. Distinct from "
                      "MODEL_UNAVAILABLE, which is a model that does not "
                      "exist here, and from INTERNAL_ERROR, which is this "
                      "application's own defect.",
    "PROVIDER_CREDENTIAL_MISSING": "nobody configured the Cockpit's own "
                                   "Anthropic credential. Distinct from "
                                   "MODEL_CONFIGURATION_MISSING, which is "
                                   "nobody saying which model answers: one "
                                   "sends an operator to "
                                   "COCKPIT_ANTHROPIC_API_KEY and the other "
                                   "to the two model-role variables.",
    "STOPPED_OUTPUT_LIMIT": "The model's REPLY reached its output allowance "
                            "and stopped mid-answer, twice -- the first "
                            "response and the one permitted compact "
                            "regeneration. Distinct from CONTEXT_TOO_LARGE, "
                            "which is the PACKET not fitting the input cap: "
                            "opposite ends of the same call, and an operator "
                            "sent to the wrong one looks at something that "
                            "was never the problem. Nothing partial is "
                            "executed and no execution submission is spent.",
}


def test_every_required_terminal_state_exists():
    for name in REQUIRED_TERMINALS:
        assert name in st.TERMINAL, f"{name} is not a terminal state"


def test_every_extra_terminal_state_is_documented():
    """Section 42 permits additional terminal states and requires them to be
    documented. A state nobody explained is one nobody can act on."""
    extras = set(st.TERMINAL) - set(REQUIRED_TERMINALS)
    assert extras == set(DOCUMENTED_EXTRAS), sorted(extras)
    for reason in DOCUMENTED_EXTRAS.values():
        assert len(reason) > 40


def test_one_terminal_state_per_guardrail():
    """"The request stopped" is not actionable. Which guardrail is."""
    assert st.STOPPED_BY_GUARDRAIL == {
        st.STOPPED_EXECUTION_LIMIT, st.STOPPED_ANALYSIS_LIMIT,
        st.STOPPED_TOKEN_LIMIT, st.STOPPED_COST_LIMIT,
        st.STOPPED_TIME_LIMIT, st.STOPPED_SECURITY,
        # The OUTPUT allowance is a guardrail too, and it is not the input
        # cap: CONTEXT_TOO_LARGE sends an operator to the packet, which is
        # not what overran when a planning REPLY did.
        st.STOPPED_OUTPUT_LIMIT}


# ============================== the specific proofs section 43 asks for

def test_the_gate_cannot_be_bypassed():
    """Nothing reaches PLANNING, VALIDATING or EXECUTING without passing
    FUNCTIONALITY_ASSESSMENT first."""
    for state in (st.RECEIVED, st.NORMALIZING_1, st.NORMALIZING_2,
                  st.BUILDING_CONTEXT):
        for forbidden in (st.PLANNING, st.VALIDATING, st.EXECUTING):
            assert forbidden not in st.TRANSITIONS[state], \
                f"{state} can reach {forbidden} without the gate"


def test_product_help_and_theory_have_no_edge_to_execution():
    """Sections 10 and 11, structurally: the gate's no-execution exit goes to
    ANSWER_VALIDATION, and from there the only way on is to a delivered
    answer. There is no path from it to VALIDATING or EXECUTING."""
    no_execution = [e for e in st.edges_from(st.FUNCTIONALITY_ASSESSMENT)
                    if e.next_state == st.ANSWER_VALIDATION]
    assert no_execution, "the gate has no zero-execution answer exit"
    assert all("PRODUCT_HELP" in e.condition or "THEORY" in e.condition
               for e in no_execution)
    reachable = set(st.TRANSITIONS[st.ANSWER_VALIDATION])
    reachable |= set(st.TRANSITIONS[st.ANSWERING])
    assert st.VALIDATING not in reachable
    assert st.EXECUTING not in reachable


def test_a_validation_failure_returns_to_planning_never_to_execution():
    """Section 7.6A: only Opus authors the next candidate."""
    failures = [e for e in st.edges_from(st.VALIDATING)
                if "failed" in e.event or "duplicate" in e.event]
    assert failures
    for edge in failures:
        assert edge.next_state != st.EXECUTING
    assert st.PLANNING in st.TRANSITIONS[st.VALIDATING]


def test_the_answer_rewrite_is_one_and_the_second_failure_ends_it():
    """Section 29. The loop exists, it is counted, and its exit is named."""
    rewrites = [e for e in st.edges_from(st.ANSWER_VALIDATION)
                if e.next_state == st.ANSWERING]
    assert len(rewrites) == 1
    assert rewrites[0].consumes == "answer_rewrite"
    assert "ONE" in rewrites[0].side_effect
    second = [e for e in st.edges_from(st.ANSWER_VALIDATION)
              if "again" in e.event]
    assert second and second[0].next_state == st.PARTIAL


def test_the_rewrite_cannot_execute_or_open_a_round():
    edge = next(e for e in st.edges_from(st.ANSWER_VALIDATION)
                if e.consumes == "answer_rewrite")
    assert "cannot execute" in edge.side_effect
    assert "cannot open a round" in edge.side_effect
    assert "cannot reset a counter" in edge.side_effect


def test_a_clarification_closes_the_request():
    """Section 15: the reply is a new request in the same thread, so this one
    must be terminal rather than parked."""
    assert st.WAITING_FOR_USER in st.TERMINAL
    assert st.TRANSITIONS[st.WAITING_FOR_USER] == ()


def test_cancellation_is_terminal_and_reachable_from_every_working_state():
    assert st.CANCELLED in st.TERMINAL
    for state in st.WORKING:
        if state == st.SUMMARIZING:
            continue
        assert st.CANCELLED in st.TRANSITIONS[state]


def test_a_model_or_provider_failure_has_no_fallback_edge():
    """There is no edge from any of these back into working states. A
    fallback would show up here as an exit."""
    for state in (st.MODEL_CONFIGURATION_MISSING, st.MODEL_UNAVAILABLE,
                  st.PROVIDER_ERROR):
        assert st.TRANSITIONS[state] == ()


def test_a_data_release_failure_has_no_fallback_edge():
    """Section 38: no silent switch to the latest release."""
    assert st.DATA_UNAVAILABLE in st.TERMINAL
    assert st.TRANSITIONS[st.DATA_UNAVAILABLE] == ()


def test_a_security_stop_is_terminal():
    """Section 24: forbidden behaviour ends the request. There is no edge by
    which it could continue and try something else."""
    assert st.STOPPED_SECURITY in st.TERMINAL
    assert st.TRANSITIONS[st.STOPPED_SECURITY] == ()
    reachable_from = {e.state for e in st.EDGES
                      if e.next_state == st.STOPPED_SECURITY}
    assert {st.VALIDATING, st.EXECUTING, st.RECEIVED} <= reachable_from


def test_an_internal_error_is_terminal_and_has_no_fallback():
    assert st.INTERNAL_ERROR in st.TERMINAL
    assert st.TRANSITIONS[st.INTERNAL_ERROR] == ()
    edge = next(e for e in st.EDGES if e.next_state == st.INTERNAL_ERROR)
    assert "no secrets" in edge.side_effect
    assert "no stack trace" in edge.side_effect
    assert "no fallback" in edge.side_effect


# ================================================ the machine enforces it

def test_the_machine_refuses_an_edge_the_registry_does_not_declare():
    machine = st.Machine()
    with pytest.raises(st.IllegalTransition):
        machine.advance(st.EXECUTING)


def test_a_settled_request_is_not_reopened():
    machine = st.Machine()
    machine.advance(st.CANCELLED)
    for target in st.ALL_STATES:
        with pytest.raises(st.IllegalTransition):
            machine.advance(target)


def test_the_adjacency_view_is_derived_and_cannot_drift():
    """`TRANSITIONS` is built from `EDGES`. A hand-maintained second copy is
    exactly how a state machine and its documentation come apart."""
    for state, targets in st.TRANSITIONS.items():
        declared = {e.next_state for e in st.edges_from(state)}
        assert set(targets) == declared, state


def test_the_registry_renders_for_the_documentation():
    rows = st.registry()
    assert len(rows) == len(st.EDGES)
    for row in rows:
        assert set(row) == {"state", "event", "condition", "next_state",
                            "side_effect", "consumes", "terminal"}


# ============================================ the document cannot drift

def test_the_architecture_document_carries_every_transition():
    """`docs/cockpit_v3/FINAL_AGENTIC_ARCHITECTURE.md` documents the state
    machine. A document that has fallen behind the registry is worse than no
    document, because it is read as though it were true -- so every edge and
    every terminal state must appear in it, and adding one without documenting
    it fails here.
    """
    from pathlib import Path

    doc = (Path(__file__).resolve().parents[2] / "docs" / "cockpit_v3"
           / "FINAL_AGENTIC_ARCHITECTURE.md")
    assert doc.exists()
    text = doc.read_text()

    for state in st.ALL_STATES:
        assert f"`{state}`" in text, f"{state} is not documented"

    always = {e.event for e in st._always("X")}
    for edge in st.EDGES:
        if edge.event in always:
            continue      # written once in its own table
        assert edge.event in text, f"undocumented event: {edge.event}"
    for edge in st._always("X"):
        assert edge.event in text, f"undocumented event: {edge.event}"


def test_the_document_states_the_three_counted_loops():
    from pathlib import Path

    text = (Path(__file__).resolve().parents[2] / "docs" / "cockpit_v3"
            / "FINAL_AGENTIC_ARCHITECTURE.md").read_text()
    for consumed in ("an execution submission", "an analysis round",
                     "the answer rewrite"):
        assert consumed in text
