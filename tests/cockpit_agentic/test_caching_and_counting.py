"""The cached prefix, and counting before spending.
Specification section 9.3, and the owner's UAT instruction.

Two properties, and they pull against each other, which is why both are here:

* The stable prefix must be byte-identical across the turns of one request, or
  caching saves nothing.
* The catalogue must be LOGICALLY present in every request regardless, because
  caching is an optimisation and section 8.1 is satisfied by the content being
  there, not by it being cheap.
"""

from __future__ import annotations

import json

import pytest

from backend.cockpit_agentic import states as st
from backend.cockpit_agentic import tokens as T
from tests.cockpit_agentic.conftest import scores
from tests.cockpit_agentic.fake_provider import FakeProvider

GOOD = ("SELECT reporting_quarter, sum(ecl_reported) AS ecl "
        "FROM cockpit_facility_quarter GROUP BY 1 ORDER BY 1 DESC LIMIT 2")
BAD = "SELECT pd_12_month FROM cockpit_facility_quarter"


def plan():
    return {"plan_id": "p1", "subquestions": ["the change in ECL"],
            "method_summary": "compare the two latest quarters"}


def steps(code, sid="s1"):
    return [{"step_id": sid, "language": "sql", "code": code}]


@pytest.fixture()
def repaired(runtime_factory, sonnet_answers):
    """A request whose first query fails and whose repair succeeds."""
    provider = FakeProvider(
        structured_script=list(sonnet_answers) + [{"current_topic": "ECL"}],
        converse_script=[
            lambda _r: {"decision": "PROCEED_COCKPIT", "scores": scores(),
                        "public_explanation": "x", "plan": plan(),
                        "steps": steps(BAD)},
            lambda _r: {"action": "submit_repaired_code", "plan": plan(),
                        "steps": steps(GOOD, "s2")},
            lambda _r: {"decision": "ANSWER",
                        "answer": {"narrative": "ECL fell.", "complete": True}},
        ])
    outcome = runtime_factory(provider).run("How much did ECL change?")
    return {"outcome": outcome, "provider": provider}


# ---- the cached prefix ----------------------------------------------------

def test_there_is_exactly_one_cache_breakpoint(repaired):
    for request in repaired["provider"].requests:
        blocks = request["system"]
        cached = [b for b in blocks if b.get("cache_control")]
        assert len(cached) == 1, (
            "a prefix match needs one breakpoint at the end of the stable "
            "span; more than one wastes them and none caches nothing")
        assert cached[0]["cache_control"] == {"type": "ephemeral"}


def test_the_breakpoint_is_not_the_last_block(repaired):
    """The untrusted-data note sits after it deliberately: it is stable too,
    but the breakpoint marks the end of the span worth caching."""
    blocks = repaired["provider"].requests[0]["system"]
    index = next(i for i, b in enumerate(blocks) if b.get("cache_control"))
    assert index == 1, "the breakpoint sits after the invariant preamble and "\
                       "the pinned domain"
    assert len(blocks) == 4, (
        "the per-turn contract and the untrusted-data note sit after it")


def test_the_prefix_is_byte_identical_across_every_turn_of_one_request(repaired):
    """The property caching depends on. One changed byte anywhere before the
    breakpoint and every later turn is a cache miss."""
    prefixes = []
    for request in repaired["provider"].requests:
        blocks = request["system"]
        breakpoint_at = next(i for i, b in enumerate(blocks)
                             if b.get("cache_control"))
        prefixes.append(json.dumps(blocks[:breakpoint_at + 1], sort_keys=True,
                                   default=str))
    assert len(prefixes) == 3, "expected a gate, a repair and a review turn"
    assert len(set(prefixes)) == 1, (
        "the cached prefix changed between turns, so every turn after the "
        "first is a cache miss")


def test_the_catalogue_is_in_the_cached_prefix(repaired):
    blocks = repaired["provider"].requests[0]["system"]
    cached = next(b for b in blocks if b.get("cache_control"))
    for name in ("pd_pit_12m", "pd_ttc_12m", "cockpit_facility_quarter",
                 "cockpit_borrower_financial_quarter"):
        assert name in cached["text"], f"{name} is not in the cached prefix"
    # The grains, the joins, the registry and the execution contract too.
    assert "grain" in cached["text"]
    assert "functionalities" in cached["text"]
    assert "execution_capabilities" in cached["text"]


def test_volatile_context_is_outside_the_prefix(repaired):
    """Anything that moves between turns must sit after the breakpoint, or it
    invalidates everything cached before it."""
    blocks = repaired["provider"].requests[-1]["system"]
    cached = json.dumps([b for b in blocks if b.get("cache_control")],
                        default=str)
    for volatile in ("submissions_remaining", "seconds_remaining",
                     "pd_12_month", "recent_exchanges",
                     "fields_with_gaps"):
        assert volatile not in cached, (
            f"{volatile!r} is inside the cached prefix and changes between "
            f"turns, so the cache can never hit")


def test_the_catalogue_is_still_logically_present_in_every_request(repaired):
    """Caching is an optimisation. Section 8.1 is satisfied by the content
    being THERE, not by it being cheap -- there is no hash and no reference
    Opus would have to resolve."""
    for request in repaired["provider"].requests:
        blob = json.dumps(request, default=str)
        assert "pd_pit_12m" in blob and "pd_ttc_12m" in blob
        assert "point-in-time probability of default" in blob.lower()


def test_the_dynamic_context_opens_the_conversation(repaired):
    """The question, scope, thread, coverage, samples and budget go in the
    first user message -- after the prefix, so the prefix stays stable."""
    first = repaired["provider"].requests[0]["messages"][0]
    assert first["role"] == "user"
    assert "THE REQUEST, ITS SCOPE" in first["content"]
    for section in ("measured_coverage", "remaining_budget", "thread"):
        assert section in first["content"]


# ---- counting before spending ---------------------------------------------

def test_every_request_is_counted_before_it_is_sent(repaired):
    counts = repaired["outcome"].tokens["counts"]
    assert len(counts) == len(repaired["provider"].requests)
    for count in counts:
        assert count["tokens"] > 0
        assert count["method"] in (T.MEASURED, T.ESTIMATED)


def test_without_a_credential_the_count_is_an_estimate_and_says_so(repaired):
    for count in repaired["outcome"].tokens["counts"]:
        assert count["method"] == T.ESTIMATED
        assert count["measured"] is False
        assert count["error"]
    report = repaired["outcome"].tokens["counter"]
    assert report["provider_counting_available"] is False


def test_a_request_that_will_not_fit_is_refused_before_dispatch(
        runtime_factory, sonnet_answers, monkeypatch):
    """Not sent, not truncated, not discovered from a provider 400."""
    from backend.cockpit_agentic import opus as opus_mod

    provider = FakeProvider(
        structured_script=list(sonnet_answers),
        converse_script=[lambda _r: {}])

    original = opus_mod.tokens_mod.Counter.fits

    def refuse(self, *, system, messages, tools, cap, reserve_output):
        raise T.TooLargeToSend(
            f"The assembled request is 999,999 tokens against a {cap:,}-token "
            f"per-call limit. It was not sent.",
            counted=T.Count(tokens=999_999, method=T.ESTIMATED), cap=cap)

    monkeypatch.setattr(opus_mod.tokens_mod.Counter, "fits", refuse)
    outcome = runtime_factory(provider).run("How much did ECL change?")
    monkeypatch.setattr(opus_mod.tokens_mod.Counter, "fits", original)

    assert outcome.status == st.CONTEXT_TOO_LARGE
    assert "was not sent" in outcome.envelope.narrative
    assert provider.requests == [], "an oversized request was dispatched"


def test_the_output_allowance_is_part_of_fitting():
    """A request that fits only if the answer is truncated has not fitted."""
    counter = T.Counter()
    with pytest.raises(T.TooLargeToSend) as e:
        counter.fits(system="x" * (3400 * 63), messages=[], tools=None,
                     cap=64_000, reserve_output=4_096)
    assert "has not fitted" in str(e.value)


def test_counting_is_cached_so_the_preflight_cannot_loop():
    counter = T.Counter()
    first = counter.count(system="abc", messages=[], tools=None)
    second = counter.count(system="abc", messages=[], tools=None)
    assert second.cached is True and second.tokens == first.tokens


def test_the_counting_budget_is_bounded_and_reported():
    class Chatty:
        configured = True

        def count_tokens(self, **_kwargs):
            return 10

    counter = T.Counter(provider=Chatty(), model="test-model")
    for i in range(T.MAX_COUNT_CALLS + 4):
        counter.count(system=f"unique-{i}", messages=[], tools=None)
    assert counter.calls == T.MAX_COUNT_CALLS
    assert counter.fallbacks == 4
    report = counter.report()
    assert report["count_call_budget"] == T.MAX_COUNT_CALLS
    assert "not inference" in report["note"]


def test_a_provider_count_is_used_when_one_is_available():
    class Counting:
        configured = True
        seen: list[str] = []

        def count_tokens(self, *, system, messages, tools=None, model=""):
            self.seen.append(model)
            return 4_321

    provider = Counting()
    counter = T.Counter(provider=provider, model="configured-model-id")
    result = counter.count(system="x", messages=[], tools=None)
    assert result.tokens == 4_321
    assert result.method == T.MEASURED and result.measured is True
    assert provider.seen == ["configured-model-id"], (
        "the count must be taken against the model that will serve the "
        "request; tokenizers differ between model families")


def test_a_failed_provider_count_falls_back_and_records_that_it_did():
    class Broken:
        configured = True

        def count_tokens(self, **_kwargs):
            raise RuntimeError("the counting endpoint is unreachable")

    counter = T.Counter(provider=Broken(), model="m")
    result = counter.count(system="x" * 3400, messages=[], tools=None)
    assert result.method == T.ESTIMATED
    assert result.measured is False
    assert "unreachable" in result.error
    assert counter.fallbacks == 1
