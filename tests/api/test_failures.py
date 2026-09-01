"""
P0.10 — every failure is categorised, and none of them leaks.

The defect: one anonymous 500 for every cause. "Something went wrong on the
server" was returned for a missing dataset, an unreachable provider, a
permission refusal and a stopped database — four different things to do, one
sentence.
"""

from __future__ import annotations

import pytest

from backend.api import failures as f


class NotAuthorised(PermissionError):
    pass


class CannotPlan(Exception):
    pass


class DataAccessError(Exception):
    pass


class OperationalError(Exception):
    pass


class Exhausted(RuntimeError):
    pass


class APIConnectionError(Exception):
    pass


class ContractError(Exception):
    pass


class WhoKnows(Exception):
    pass


@pytest.mark.parametrize("exc, expected", [
    (NotAuthorised("no"), f.PERMISSION),
    (CannotPlan("no"), f.PLANNING),
    (DataAccessError("no"), f.DATA),
    (OperationalError("no"), f.PERSISTENCE),
    (Exhausted("no"), f.BUDGET),
    (APIConnectionError("no"), f.PROVIDER),
    (ContractError("no"), f.VALIDATION),
    (PermissionError("no"), f.PERMISSION),
    (FileNotFoundError("no"), f.DATA),
    (TimeoutError("no"), f.EXECUTION),
])
def test_each_cause_gets_its_own_category(exc, expected):
    assert f.classify(exc) == expected


def test_an_unrecognised_failure_says_so_rather_than_guessing():
    """UNKNOWN is a real answer. Forcing every exception into a named category
    would make the categories meaningless."""
    assert f.classify(WhoKnows("no")) == f.UNKNOWN


def test_a_wrapped_persistence_failure_is_still_persistence():
    """SQLAlchemy wraps the driver's error. Classifying only the outermost
    exception reported a stopped database as an unknown server fault — which is
    exactly what happened when Postgres was stopped during Phase 0."""
    try:
        try:
            raise OperationalError("connection refused")
        except OperationalError as inner:
            raise RuntimeError("could not answer") from inner
    except RuntimeError as outer:
        assert f.classify(outer) == f.PERSISTENCE


def test_the_status_matches_the_cause():
    """A missing dataset is not a server fault, and a 500 on one sends an
    operator to look in the wrong place."""
    assert f.STATUS[f.DATA] == 404
    assert f.STATUS[f.PERMISSION] == 403
    assert f.STATUS[f.BUDGET] == 429
    assert f.STATUS[f.PERSISTENCE] == 503
    assert f.STATUS[f.PROVIDER] == 503
    assert f.STATUS[f.UNKNOWN] == 500


def test_every_category_has_a_message_a_person_can_act_on():
    for category in f.CATEGORIES:
        message = f.MESSAGE[category]
        assert len(message) > 20, category
        assert message[0].isupper() or message.startswith("You"), category


def test_no_message_leaks_anything():
    """The check is on the shipped messages, not on the idea of them."""
    for category in f.CATEGORIES:
        assert not f.leaks(f.MESSAGE[category]), category


@pytest.mark.parametrize("text", [
    "connect to postgresql://ipm:hunter2@db:5432/ipm",
    "ANTHROPIC_API_KEY was rejected",
    "sk-ant-api03-AAAAAAAAAAAAAAAA",
    "Authorization: Bearer abcdefghijklmnop",
    "password=hunter2",
])
def test_the_leak_check_catches_what_it_is_for(text):
    assert f.leaks(text)


def test_a_failure_carries_a_correlation_id_and_no_exception_text():
    """The id is how an engineer finds the log. The exception's own message is
    not shown, because it carries paths and identifiers."""
    failure = f.of(DataAccessError("/srv/data/secret/portfolio.parquet missing"),
                   "abc123")
    shown = failure.to_dict()
    assert shown["detail"]["correlation_id"] == "abc123"
    assert "parquet" not in shown["message"]
    assert "/srv" not in shown["message"]
    assert shown["category"] == f.DATA
    # The TYPE is kept, because "what keeps failing" is a question about kinds.
    assert failure.kind == "DataAccessError"
