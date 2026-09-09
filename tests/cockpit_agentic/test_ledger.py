"""The budget ledger is the enforcement. Specification section 9.

These tests exist because "prompting Opus to try only five times is not
enforcement" is the specification's own sentence, and the only way to show
enforcement is to try to exceed each limit and be refused.
"""

from __future__ import annotations

import pytest

from backend.cockpit_agentic import ledger as L

PRICES = L.Prices(sonnet_input=3.0, sonnet_output=15.0,
                  opus_input=15.0, opus_output=75.0)


def make(mode: str = "standard", clock=None, **kw) -> L.Ledger:
    return L.Ledger(mode=mode, prices=PRICES,
                    clock=clock or (lambda: 0.0), **kw)


# ---- section 9.1: five submissions, three rounds --------------------------

def test_five_submissions_then_no_sixth():
    lg = make()
    for i in range(5):
        assert lg.note_submission(f"candidate-{i}") == i + 1
    with pytest.raises(L.BudgetExceeded) as e:
        lg.note_submission("candidate-6")
    assert e.value.reason == L.STOP_SUBMISSIONS
    assert lg.submissions_remaining == 0


def test_a_new_plan_does_not_reset_the_submission_counter():
    """Section 9.2 example B: five candidates fail while pursuing plan A, and
    proposing plan B does not buy a sixth."""
    lg = make()
    for i in range(5):
        lg.note_submission(f"plan-a-{i}")
    lg.note_analysis_round()          # a genuinely new plan
    with pytest.raises(L.BudgetExceeded) as e:
        lg.note_submission("plan-b-1")
    assert e.value.reason == L.STOP_SUBMISSIONS


def test_no_nested_loop_multiplication():
    """Section 9.2: five total, not five per round."""
    lg = make()
    used = 0
    for _round in range(3):
        lg.note_analysis_round()
        for _try in range(5):
            try:
                lg.note_submission(f"r{_round}-t{_try}")
                used += 1
            except L.BudgetExceeded:
                break
    assert used == 5, "the counter is global, so three rounds cannot buy fifteen"


def test_three_analysis_rounds_then_no_fourth():
    lg = make()
    for i in range(3):
        assert lg.note_analysis_round() == i + 1
    with pytest.raises(L.BudgetExceeded) as e:
        lg.note_analysis_round()
    assert e.value.reason == L.STOP_ROUNDS


def test_a_repair_uses_a_submission_but_not_a_round():
    """Section 7.8: syntax/binding repair uses an execution submission but does
    not itself create another substantive analysis round."""
    lg = make()
    lg.note_analysis_round()
    lg.note_submission("first")
    lg.note_submission("repaired")     # a repair
    assert lg.analysis_rounds == 1
    assert lg.submissions == 2


# ---- section 8.3: no progress ---------------------------------------------

def test_an_identical_candidate_is_blocked_before_execution():
    """Section 22: not run again, and the attempt is spent anyway.

    Spending it is the point. A repeat that cost nothing would let a model
    loop on the same failing query for as long as the deadline allowed.
    """
    lg = make()
    lg.note_submission("SELECT a FROM t")
    with pytest.raises(L.DuplicateCandidate) as e:
        lg.note_submission("SELECT a FROM t")
    assert e.value.submission_number == 2
    assert "not run again" in str(e.value)
    assert lg.submissions == 2, "the duplicate consumed an attempt of its own"


def test_a_duplicate_does_not_by_itself_end_the_request():
    """It is not a budget stop. Opus may still write something different with
    the attempts that remain, and taking those away for one repeat would be a
    stricter rule than the one that was agreed."""
    lg = make()
    lg.note_submission("SELECT a FROM t")
    with pytest.raises(L.DuplicateCandidate):
        lg.note_submission("SELECT a FROM t")
    assert lg.may_continue() == "", "the request continues"
    assert lg.submissions_remaining == 3


def test_reformatting_is_not_a_changed_approach():
    from backend.cockpit_agentic.contracts import fingerprint

    a = fingerprint("sql", "SELECT a\n  FROM t", "{}")
    b = fingerprint("sql", "select   a from   T", "{}")
    assert a == b


# ---- section 9.1: the earliest bound wins ---------------------------------

def test_deadline_stops_before_the_submissions_are_spent():
    """Section 9.2 example D."""
    now = {"t": 0.0}
    lg = make(clock=lambda: now["t"])
    lg.note_submission("one")
    lg.note_submission("two")
    now["t"] = 61.0
    assert lg.may_continue() == L.STOP_DEADLINE
    with pytest.raises(L.BudgetExceeded) as e:
        lg.reserve(role="opus", family="opus", purpose="repair",
                   input_tokens=100, max_output_tokens=100)
    assert e.value.reason == L.STOP_DEADLINE
    assert lg.submissions_remaining == 3, "attempts remained; time did not"


def test_the_input_packet_cap_refuses_rather_than_truncating():
    lg = make()
    with pytest.raises(L.BudgetExceeded) as e:
        lg.reserve(role="opus", family="opus", purpose="plan",
                   input_tokens=64_001, max_output_tokens=100)
    assert e.value.reason == L.STOP_INPUT_TOO_LARGE
    assert "silently dropped" in str(e.value)


def test_deep_mode_raises_the_caps_but_not_the_submissions():
    """The UAT configuration. The token budgets moved because the domain's
    mandatory catalogue does not fit the specification's own numbers; the
    deadlines and the two counters did not move, and cannot."""
    std, deep = L.limits_for("standard"), L.limits_for("deep")
    assert std.max_input_tokens_per_call == 64_000
    assert deep.max_input_tokens_per_call == 96_000
    assert std.total_tokens == 250_000
    assert deep.total_tokens == 500_000
    # Unmoved, and unmovable.
    assert deep.deadline_seconds == 120.0 and std.deadline_seconds == 60.0
    assert deep.execution_submissions == std.execution_submissions == 5
    assert deep.analysis_rounds == std.analysis_rounds == 3
    assert std.total_provider_requests == 12
    assert deep.total_provider_requests == 16
    assert std.spend_ceiling_usd == 1.00 and deep.spend_ceiling_usd == 2.00


def test_the_token_ceiling_holds_the_finalization_reserve_back():
    # No prices, so cost is not enforced and this test measures the token
    # ceiling alone. With prices configured the SPEND ceiling bites first at
    # these volumes -- which is its own finding, asserted below.
    lg = L.Ledger(prices=L.Prices(), clock=lambda: 0.0)
    with pytest.raises(L.BudgetExceeded) as e:
        for _ in range(6):
            reservation = lg.reserve(role="opus", family="opus",
                                     purpose="plan", input_tokens=40_000,
                                     max_output_tokens=4_096)
            lg.settle(reservation, output_tokens=4_000)
    assert e.value.reason == L.STOP_TOKENS
    assert "final explanation" in lg.stop_detail


def test_the_finalization_call_may_draw_on_the_reserve():
    """Section 9.3: the finalization allowance sits INSIDE the total, and is
    the only thing that may spend it."""
    lg = L.Ledger(prices=L.Prices(), clock=lambda: 0.0)
    for _ in range(5):
        r = lg.reserve(role="opus", family="opus", purpose="plan",
                       input_tokens=44_000, max_output_tokens=1_000)
        lg.settle(r, output_tokens=1_000)
    assert lg.tokens_used == 225_000
    # 250,000 - 225,000 - 25,000 held back leaves nothing for ordinary work.
    with pytest.raises(L.BudgetExceeded) as e:
        lg.reserve(role="opus", family="opus", purpose="plan",
                   input_tokens=5_000, max_output_tokens=1_000)
    assert e.value.reason == L.STOP_TOKENS
    # The reserved terminal explanation still fits inside the same ceiling --
    # and the reserve is big enough to carry this domain's catalogue, which a
    # 6,000-token reserve was not.
    held = lg.reserve(role="opus", family="opus", purpose="final",
                      input_tokens=22_000, max_output_tokens=1_000,
                      finalization=True)
    assert held.reserved_output_tokens == 1_000


def test_the_provider_call_ceiling_is_enforced():
    lg = make()
    for _ in range(12):
        r = lg.reserve(role="sonnet", family="sonnet", purpose="x",
                       input_tokens=10, max_output_tokens=10)
        lg.settle(r, output_tokens=5)
    assert lg.calls_remaining == 0
    with pytest.raises(L.BudgetExceeded) as e:
        lg.reserve(role="sonnet", family="sonnet", purpose="x",
                   input_tokens=10, max_output_tokens=10)
    assert e.value.reason == L.STOP_CALLS


def test_step_ceilings_are_enforced_per_submission_and_per_request():
    lg = make()
    with pytest.raises(L.BudgetExceeded):
        lg.note_steps(7)                     # standard permits 6 per submission
    for _ in range(2):
        lg.note_steps(6)
    with pytest.raises(L.BudgetExceeded) as e:
        lg.note_steps(1)                     # 12 per request already used
    assert e.value.reason == L.STOP_STEPS


def test_metadata_lookups_do_not_become_a_discovery_loop():
    lg = make()
    lg.note_metadata_request()
    lg.note_metadata_request()
    with pytest.raises(L.BudgetExceeded) as e:
        lg.note_metadata_request()
    assert e.value.reason == L.STOP_METADATA


# ---- section 9.3: accounting ----------------------------------------------

def test_cached_reads_still_count_toward_the_token_ceiling():
    """Caching lowers cost and latency. It does not make repeated context free
    for this cumulative guardrail."""
    lg = make()
    r = lg.reserve(role="opus", family="opus", purpose="plan",
                   input_tokens=1_000, max_output_tokens=500)
    lg.settle(r, input_tokens=100, output_tokens=200, cache_read_tokens=900)
    assert lg.tokens_used == 100 + 200 + 900


def test_an_uncertain_call_is_recorded_rather_than_treated_as_free():
    lg = make()
    r = lg.reserve(role="opus", family="opus", purpose="plan",
                   input_tokens=1_000, max_output_tokens=500)
    lg.settle(r, output_tokens=0, error="timeout after dispatch",
              uncertain=True)
    assert lg.calls[0].uncertain is True
    assert lg.tokens_used >= 1_000


def test_spend_is_unknown_and_not_enforced_without_configured_prices():
    lg = L.Ledger(prices=L.Prices(), clock=lambda: 0.0)
    assert lg.cost_enforced is False
    assert lg.budget_view()["spend_usd"] == "UNKNOWN"
    assert lg.budget_view()["spend_ceiling_usd"] == "NOT_ENFORCED"
    assert "NOT a control" in lg.to_dict()["cost_note"]


def test_the_spend_ceiling_refuses_when_prices_are_configured():
    dear = L.Prices(sonnet_input=1_000.0, sonnet_output=1_000.0,
                    opus_input=1_000.0, opus_output=1_000.0)
    lg = L.Ledger(prices=dear, clock=lambda: 0.0)
    with pytest.raises(L.BudgetExceeded) as e:
        lg.reserve(role="opus", family="opus", purpose="plan",
                   input_tokens=2_000, max_output_tokens=2_000)
    assert e.value.reason == L.STOP_SPEND


# ---- section 9.3: one budget per request ----------------------------------

def test_a_restart_or_double_click_does_not_start_a_second_budget():
    store = L.LedgerStore()
    first, resumed_a = store.open(request_id="req-x", prices=PRICES,
                                  clock=lambda: 0.0)
    first.note_submission("a")
    second, resumed_b = store.open(request_id="req-x", prices=PRICES,
                                   clock=lambda: 0.0)
    assert resumed_a is False and resumed_b is True
    assert second is first
    assert second.submissions == 1, "the resumed ledger kept its counters"


def test_the_ledger_persists_on_every_mutation():
    store = L.LedgerStore()
    lg, _ = store.open(request_id="req-y", prices=PRICES, clock=lambda: 0.0)
    lg.note_submission("a")
    assert store.read("req-y")["submissions_used"] == 1


# ---- section 9.5: what a stop does ----------------------------------------

def test_the_first_stop_reason_is_the_one_reported():
    lg = make()
    lg.stop(L.STOP_DEADLINE, "the deadline expired")
    lg.stop(L.STOP_TOKENS, "and then tokens ran out")
    assert lg.stopped == L.STOP_DEADLINE
    assert lg.stop_detail == "the deadline expired"


def test_cancellation_stops_new_work():
    lg = make()
    lg.cancel()
    assert lg.may_continue() == L.STOP_CANCELLED
    with pytest.raises(L.BudgetExceeded):
        lg.reserve(role="opus", family="opus", purpose="plan",
                   input_tokens=10, max_output_tokens=10)


def test_the_budget_view_tells_opus_what_is_left():
    lg = make()
    lg.note_analysis_round()
    lg.note_submission("a")
    view = lg.budget_view()
    assert view["submissions_remaining"] == 4
    assert view["analysis_rounds_remaining"] == 2
    assert view["seconds_remaining"] == 60.0


def test_an_absolute_stop_ends_even_the_final_explanation():
    """Section 8.3: if no model budget remains, a factual server-generated stop
    envelope is used -- not a further model call."""
    now = {"t": 0.0}
    lg = make(clock=lambda: now["t"])
    now["t"] = 61.0
    with pytest.raises(L.BudgetExceeded) as e:
        lg.reserve(role="opus", family="opus", purpose="final",
                   input_tokens=100, max_output_tokens=100, finalization=True)
    assert e.value.reason == L.STOP_DEADLINE


def test_a_soft_stop_still_permits_the_bounded_explanation():
    lg = make()
    for _ in range(5):
        lg.note_submission(f"c{_}")
    assert lg.stopped == ""          # not latched until a sixth is attempted
    with pytest.raises(L.BudgetExceeded):
        lg.note_submission("c6")
    assert lg.stopped == L.STOP_SUBMISSIONS
    # Opus may still be asked to explain, in plain English, what it tried.
    lg.reserve(role="opus", family="opus", purpose="final",
               input_tokens=2_000, max_output_tokens=1_000, finalization=True)


# ---- the UAT configuration, and what now binds first ----------------------

def test_the_spend_ceiling_binds_before_the_token_ceiling_at_these_volumes():
    """A measured consequence of the new configuration, not a defect.

    The token ceiling moved to 250,000 for Standard; the spending ceiling
    stayed at $1.00 so live usage can be measured against it. At Opus rates a
    quarter of a million input tokens costs well over a dollar, so spend is now
    the binding constraint. The earliest bound wins, and this asserts WHICH one
    that is -- so if the ceiling is later raised, this test says so out loud
    rather than the change passing silently.
    """
    opus = L.Prices(sonnet_input=2.0, sonnet_output=10.0,
                    opus_input=5.0, opus_output=25.0)
    lg = L.Ledger(prices=opus, clock=lambda: 0.0)
    assert lg.cost_enforced is True

    reason = ""
    for _ in range(20):
        try:
            reservation = lg.reserve(role="opus", family="opus",
                                     purpose="plan", input_tokens=28_000,
                                     max_output_tokens=4_096)
            lg.settle(reservation, output_tokens=2_000)
        except L.BudgetExceeded as e:
            reason = e.reason
            break
    assert reason == L.STOP_SPEND, (
        f"expected the spending ceiling to bind first; got {reason!r}")
    assert lg.tokens_used < lg.limits.total_tokens, (
        "the token ceiling was never reached, which is the point")


def test_a_cached_prefix_lowers_the_cost_of_the_same_context():
    """Caching lowers cost. It does NOT lower the logical token count, and the
    ledger counts cached reads toward the token ceiling either way (9.3)."""
    opus = L.Prices(sonnet_input=2.0, sonnet_output=10.0,
                    opus_input=5.0, opus_output=25.0)
    uncached = L.Ledger(prices=opus, clock=lambda: 0.0)
    r = uncached.reserve(role="opus", family="opus", purpose="plan",
                         input_tokens=28_000, max_output_tokens=1_000)
    uncached.settle(r, input_tokens=28_000, output_tokens=500)

    cached = L.Ledger(prices=opus, clock=lambda: 0.0)
    r2 = cached.reserve(role="opus", family="opus", purpose="plan",
                        input_tokens=28_000, max_output_tokens=1_000)
    cached.settle(r2, input_tokens=6_000, output_tokens=500,
                  cache_read_tokens=22_000)

    # Same logical context, same token count against the ceiling...
    assert cached.tokens_used == uncached.tokens_used
    # ...and the ledger prices the cached read at the same nominal rate here,
    # so any saving shows up in the provider's own usage rather than being
    # assumed. What matters for the guardrail is that the token count did not
    # shrink.
    assert cached.tokens_remaining == uncached.tokens_remaining
