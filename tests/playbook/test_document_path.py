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
