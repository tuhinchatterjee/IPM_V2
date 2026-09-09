"""Playbook against a real provider. PB-013, PB-015, PB-017, PB-029, PB-030,
PB-038, PB-043.

Thin on purpose. The checks are defined in `backend/validation/live_playbook.py`
— production code — for the reason `tests/llm/test_live_smoke.py` gives: a
deployment must be able to verify its own live path, and the deployed image
ships neither `tests/` nor pytest. One definition, three callers, no drift.

These SKIP where no credential is configured, and a skip is never reported as a
pass. The structural tests below run everywhere, because a live suite that
quietly stopped covering a requirement would otherwise be discovered only by
somebody reading it.
"""

from __future__ import annotations

import pytest

from backend.validation import live_playbook


class TestTheSuiteCoversWhatItClaims:
    """Runs with no provider. Guards the suite itself."""

    def test_every_blocked_requirement_has_a_check(self):
        covered = {r.strip()
                   for c in live_playbook.CHECKS
                   for r in c.requirement.split(",")}
        for requirement in ("PB-013", "PB-015", "PB-017", "PB-029", "PB-030",
                            "PB-043"):
            assert requirement in covered, f"{requirement} has no live check"

    def test_streaming_is_verified_live_and_not_only_with_fixtures(self):
        assert any("PB-038" in c.requirement for c in live_playbook.CHECKS)

    def test_every_check_has_a_runner(self):
        assert ({c.id for c in live_playbook.CHECKS}
                == set(live_playbook.RUNNERS))

    def test_every_check_says_what_passing_it_establishes(self):
        for check in live_playbook.CHECKS:
            assert check.proves and check.proves[0].islower(), check.id
            assert check.requirement

    def test_the_cost_is_declared_before_anything_is_spent(self):
        assert live_playbook.ESTIMATED_CALLS == sum(
            c.calls for c in live_playbook.CHECKS)
        # Bounded: this is a verification suite, not a benchmark.
        assert live_playbook.ESTIMATED_CALLS <= 20

    def test_it_refuses_to_run_without_a_credential_rather_than_passing(self):
        ok, reason = live_playbook.available()
        import os
        if os.environ.get("ANTHROPIC_API_KEY"):
            assert ok, reason
        else:
            assert not ok
            assert "ANTHROPIC_API_KEY" in reason
            assert "sk-ant" not in reason

    def test_an_unknown_check_is_a_failure_not_an_exception(self):
        outcome = live_playbook.run("not-a-check")
        assert outcome.passed is False
        assert "no such check" in outcome.detail

    def test_one_check_can_be_re_run_without_paying_for_the_rest(self):
        """After the first live run, three checks failed and re-testing them
        cost all twelve provider calls."""
        suite = live_playbook.run_some(["not-a-check"])
        assert len(suite.outcomes) == 1
        assert suite.passed is False

    def test_an_unknown_id_in_a_re_run_fails_rather_than_running_nothing(self):
        """A typo that quietly ran nothing would read as success."""
        assert live_playbook.run_some(["typo"]).outcomes[0].passed is False

    def test_every_check_is_bounded(self):
        """The first live run hung until Ctrl+C. The provider deadline is the
        real fix; this is the backstop that keeps the suite reportable."""
        assert live_playbook.CHECK_TIMEOUT_SECONDS > 0
        from backend.playbook import provider
        assert (live_playbook.CHECK_TIMEOUT_SECONDS
                >= provider.RUN_DEADLINE_SECONDS), (
            "a check must not be abandoned before the provider call inside it "
            "has had its own chance to time out and report properly")

    def test_a_check_that_wedges_is_reported_and_the_run_continues(self,
                                                                   monkeypatch):
        import time as _time

        monkeypatch.setattr(live_playbook, "CHECK_TIMEOUT_SECONDS", 0.2)
        monkeypatch.setitem(live_playbook.RUNNERS, "author_model",
                            lambda: _time.sleep(30))
        outcome = live_playbook.run("author_model")
        assert outcome.passed is False
        assert outcome.error_category == "timeout"
        assert "not counted as a pass" in outcome.detail

    def test_progress_is_reported_before_and_after_each_check(self,
                                                              monkeypatch):
        """So a run that costs minutes shows what it is doing while it does
        it, rather than nothing until the end."""
        seen = []
        monkeypatch.setitem(
            live_playbook.RUNNERS, "author_model",
            lambda: live_playbook.Outcome(check="author_model", passed=True))
        live_playbook.run("author_model",
                          on_progress=lambda stage, cid: seen.append((stage, cid)))
        assert seen == [("start", "author_model"), ("end", "author_model")]

    def test_the_suite_works_in_its_own_tenant(self):
        """A live run must not be able to write into the demonstration or
        into a real user's workspace."""
        assert live_playbook.TENANT != "default"


_ok, _reason = live_playbook.available()

pytestmark_live = pytest.mark.live


@pytest.mark.live
@pytest.mark.skipif(not _ok, reason=_reason or "no live provider configured")
@pytest.mark.parametrize("check", [c.id for c in live_playbook.CHECKS])
def test_the_live_check_passes(check):
    """One test per check, so a failure names the requirement that failed."""
    outcome = live_playbook.run(check)
    assert outcome.passed, (
        f"{check}: {outcome.detail}"
        + (f" [{outcome.error_category}]" if outcome.error_category else ""))
