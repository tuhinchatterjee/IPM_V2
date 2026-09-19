"""
Which path makes a document, and whether it can ever break a conversation.
Chapter 08 and chapter 02.
"""

from __future__ import annotations

import pytest

from backend.playbook import documents, provider


class TestTheChoiceIsHonest:

    def test_a_conversion_never_uses_the_provider(self, monkeypatch):
        """Even with the Skill path fully available."""
        monkeypatch.setattr(provider, "SKILL_RENDERING", True)
        monkeypatch.setattr(provider, "status",
                            lambda: provider.Status(True, "", "anthropic", "m"))

        choice = documents.choose(converting=True)
        assert choice.path == documents.LOCAL
        assert "no provider call" in choice.reason
        assert choice.skill_available is True, (
            "available, and deliberately not used — that is the point")

    def test_the_skill_path_needs_both_the_flag_and_a_provider(
            self, monkeypatch):
        monkeypatch.setattr(provider, "SKILL_RENDERING", True)
        monkeypatch.setattr(
            provider, "status",
            lambda: provider.Status(False, "no key", "anthropic", ""))
        assert documents.skill_available() is False, (
            "a flag on its own is a preference, not a capability")

        monkeypatch.setattr(provider, "SKILL_RENDERING", False)
        monkeypatch.setattr(provider, "status",
                            lambda: provider.Status(True, "", "anthropic", "m"))
        assert documents.skill_available() is False

    def test_it_falls_back_cleanly_and_says_why(self, monkeypatch):
        monkeypatch.setattr(provider, "SKILL_RENDERING", False)
        choice = documents.choose()
        assert choice.path == documents.LOCAL
        assert "not enabled on this deployment" in choice.reason

    def test_the_audit_uses_chapter_02s_three_states(self, monkeypatch):
        monkeypatch.setattr(provider, "SKILL_RENDERING", False)
        report = documents.report()
        assert report["paths"][documents.SKILL]["state"] == (
            "available_but_disabled")
        assert report["paths"][documents.LOCAL]["state"] == "implemented"
        assert "PLAYBOOK_SKILL_RENDERING" in report["paths"][documents.SKILL][
            "enable"]

        monkeypatch.setattr(provider, "SKILL_RENDERING", True)
        monkeypatch.setattr(provider, "status",
                            lambda: provider.Status(True, "", "anthropic", "m"))
        assert documents.report()["paths"][documents.SKILL]["state"] == (
            "implemented")


@pytest.mark.usefixtures("db")
class TestAnUnavailableToolNeverBreaksTheConversation:

    def test_a_question_is_answered_with_no_document_path_at_all(
            self, db, scope, workspace, scripted_author, monkeypatch):
        """Chapter 08's last line, as a test.

        The module that chooses a document path is made to raise. An ordinary
        question must not notice.
        """
        from backend.playbook import chat

        def explode(**_kw):
            raise AssertionError("an ordinary question chose a document path")

        monkeypatch.setattr(documents, "choose", explode)
        scripted_author("", makes_document=False,
                        chat_text="A development report explains how it was built.")

        turn = chat.turn(db, scope, workspace.id, text="What is the difference?")
        assert "development report explains" in turn["text"]
        assert turn["produced"] == []

    def test_the_path_that_made_each_artifact_is_recorded(
            self, db, scope, workspace, scripted_author):
        from backend.playbook import evidence as ev
        from backend.playbook import repository as repo
        from backend.playbook import service

        scripted_author("# R\n\n## 1. Summary\n\n" + "Considered prose. " * 20)
        outcome = service.author_document(
            db, scope, workspace.id, instruction="Write it.",
            ledger=ev.Ledger(), title="R", formats=["docx"])

        assert outcome.document_path["path"] == documents.LOCAL
        assert outcome.document_path["reason"]
        [file] = repo.files(db, outcome.version_id)
        assert file.renderer == documents.LOCAL, (
            "the answer travels with the artifact, not only with the run")


class TestWhatThisDeploymentCannotDo:
    """Chapter 02's third state, and DC-13. A capability that does not exist
    must be reported as absent — not omitted, and above all not simulated."""

    def test_research_is_declared_absent_rather_than_left_unmentioned(self):
        from backend.playbook import capabilities

        report = capabilities.describe()["unsupported"]
        assert report["research"]["state"] == "not_supported"
        assert "no web search" in report["research"]["detail"].lower()

    def test_the_assistant_is_told_the_same_thing_the_audit_publishes(self):
        """One registry, two readers, so they cannot drift apart.

        Before this, the runtime instruction listed what was missing in a
        sentence of its own and the capability endpoint said nothing at all.
        The matrix claimed the audit reported research as absent; it did not.
        """
        from backend.playbook import capabilities, chat

        note = chat._capability_note()
        for name, detail in capabilities.NOT_SUPPORTED.items():
            assert detail in note, f"{name} is published but not told"

    def test_code_execution_is_not_in_two_places_at_once(self):
        """It has two runtime states, and `documents.report()` owns them.

        Listing it as flatly unsupported as well would make the audit
        contradict itself the moment the Skill path is enabled.
        """
        from backend.playbook import capabilities

        assert "code_execution" not in capabilities.NOT_SUPPORTED
        assert set(documents.report()["paths"]) == {documents.SKILL,
                                                    documents.LOCAL}

    def test_a_capability_leaves_the_list_by_being_built(self, monkeypatch):
        """The inverse, so the test is not merely describing today's dict."""
        from backend.playbook import capabilities, chat

        monkeypatch.setitem(capabilities.NOT_SUPPORTED, "telepathy",
                            "Playbook cannot read minds.")
        assert "telepathy" in capabilities.describe()["unsupported"]
        assert "cannot read minds" in chat._capability_note()
