"""The demonstration. PB-025, PB-026, PB-027, PB-028.

What these assert is not that seeding runs, but that what it produces is what
§13 and §14 ask for: complete histories, real files, genuine revisions, thirty
substantial analyses, figures that reconcile across every artefact, and seeding
that can be run twice without turning the library into sixty.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from backend.models.playbook import PlaybookWorkspace
from backend.playbook import library, seed, seed_exports, store
from backend.playbook import repository as repo
from backend.playbook import seed_threads as threads
from backend.playbook.fixtures import ecl_oracle as ecl
from backend.playbook.ingest import docx_reader, pdf_reader, pptx_reader


@pytest.fixture
def seeded(db, scope):
    seed.reseed(db, scope)
    return seed.status(db, scope)


def _workspace(db, scope, title):
    return db.execute(
        select(PlaybookWorkspace).where(
            PlaybookWorkspace.tenant == scope.tenant,
            PlaybookWorkspace.title == title)).scalars().first()


class TestTheExportedAnalysisLibrary:
    def test_there_are_at_least_thirty(self, seeded):
        assert seeded["exports_total"] >= 30

    def test_at_least_six_come_from_each_module(self, seeded):
        for module, count in seeded["exports_by_module"].items():
            assert count >= 6, f"{module} has only {count}"

    def test_all_five_in_scope_modules_are_represented(self, seeded):
        assert set(seeded["exports_by_module"]) == {
            "cockpit", "early_warning", "what_if", "scorecard_validation",
            "lenses",
        }

    def test_no_two_analyses_are_the_same_paragraph_renamed(self):
        narratives = [s.narrative for s in seed_exports.catalogue()]
        assert len(set(narratives)) == len(narratives)

    def test_every_analysis_carries_substantive_content(self):
        for snapshot in seed_exports.catalogue():
            assert len(snapshot.narrative) > 200, snapshot.title
            assert snapshot.tables, snapshot.title
            assert snapshot.tables[0].rows, snapshot.title
            assert snapshot.scope, snapshot.title

    def test_every_analysis_is_labelled_as_demonstration_data(self, db, scope,
                                                              seeded):
        cards, _ = library.browse(db, scope, limit=100)
        assert cards
        assert all(c.demo_origin for c in cards)

    def test_what_if_says_what_it_is(self):
        """The deferred integration must be visible in the data, not only in a
        document nobody opens."""
        what_if = [s for s in seed_exports.catalogue()
                   if s.source_module == "what_if"]
        assert len(what_if) == 6
        for snapshot in what_if:
            assert any("adapter contract" in c for c in snapshot.caveats), \
                snapshot.title
            assert snapshot.demo_origin

    def test_a_preview_opens_and_carries_the_analysis(self, db, scope, seeded):
        cards, _ = library.browse(db, scope, limit=100)
        for card in cards:
            payload = library.preview(db, scope, card.revision_id)
            assert payload["narrative"]
            assert payload["question"]


class TestTheThreeWorkspaces:
    def test_all_three_named_workspaces_exist(self, seeded):
        assert len(seeded["workspaces_present"]) == 3
        assert seeded["ready"] is True

    def test_each_has_at_least_twelve_messages(self, db, scope, seeded):
        for title in seeded["workspaces_present"]:
            ws = _workspace(db, scope, title)
            assert len(repo.messages(db, ws.id)) >= 12, title

    def test_each_has_at_least_three_real_input_files(self, db, scope, seeded):
        for title in seeded["workspaces_present"]:
            ws = _workspace(db, scope, title)
            sources = repo.sources(db, ws.id)
            assert len(sources) >= 3, title
            for source in sources:
                assert source.status in ("parsed", "partial"), source.filename
                assert repo.chunks(db, source.id), source.filename

    def test_each_has_at_least_four_exported_analyses_attached(self, db, scope,
                                                               seeded):
        for title in seeded["workspaces_present"]:
            ws = _workspace(db, scope, title)
            attached = [a for a in repo.attachments(db, ws.id)
                        if a.kind == "export_revision"]
            assert len(attached) >= 4, title

    def test_each_has_two_versions_that_genuinely_differ(self, db, scope,
                                                         seeded):
        for title in seeded["workspaces_present"]:
            ws = _workspace(db, scope, title)
            report = next(a for a in repo.artifacts(db, ws.id)
                          if a.kind == "report")
            versions = repo.versions(db, report.id)
            assert len(versions) >= 2, title
            assert versions[0].content_hash != versions[1].content_hash, title
            assert versions[1].parent_version_id == versions[0].id
            assert versions[1].change_summary

    def test_a_change_set_shows_partial_approval(self, db, scope, seeded):
        """The demonstration must show changes being CHOSEN, not all applied."""
        ws = _workspace(db, scope, "IFRS 9 Committee Report — Q2 2026")
        change_sets = db.execute(
            select(repo.PlaybookChangeSet).where(
                repo.PlaybookChangeSet.workspace_id == ws.id)).scalars().all()
        assert change_sets
        items = repo.change_items(db, change_sets[0].id)
        assert len(items) == 5
        applied = [i for i in items if i.status == "applied"]
        rejected = [i for i in items if i.status == "rejected"]
        assert applied and rejected, "a demonstration where everything was "\
                                     "applied shows nothing about choosing"
        assert {i.stable_id for i in rejected} == {"chg-monitoring"}

    def test_the_rejected_change_is_absent_from_version_two(self, db, scope,
                                                            seeded):
        """Change 4 asked for monitoring evidence in the paper. It was held, so
        version 2 must not contain it."""
        ws = _workspace(db, scope, "IFRS 9 Committee Report — Q2 2026")
        report = next(a for a in repo.artifacts(db, ws.id) if a.kind == "report")
        v2 = repo.versions(db, report.id)[1]
        assert "chg-monitoring" not in v2.applied_change_item_ids
        text = str(v2.content)
        assert "Model Risk" not in text or "refer" not in text.lower()


class TestTheFilesAreReal:
    def test_every_stored_file_is_the_exact_bytes_recorded(self, db, scope,
                                                           seeded):
        checked = 0
        for title in seeded["workspaces_present"]:
            ws = _workspace(db, scope, title)
            for artifact in repo.artifacts(db, ws.id):
                for version in repo.versions(db, artifact.id):
                    for row in repo.files(db, version.id):
                        content = store.read(row.bytes_path)
                        assert store.sha256(content) == row.sha256
                        assert row.validated is True
                        checked += 1
        assert checked >= 12, "three workspaces should carry more files than this"

    def test_every_word_pdf_and_deck_reopens(self, db, scope, seeded):
        readers = {"docx": docx_reader, "pdf": pdf_reader, "pptx": pptx_reader}
        formats: set[str] = set()
        for title in seeded["workspaces_present"]:
            ws = _workspace(db, scope, title)
            for artifact in repo.artifacts(db, ws.id):
                for version in repo.versions(db, artifact.id):
                    for row in repo.files(db, version.id):
                        content = store.read(row.bytes_path)
                        result = readers[row.format].read(
                            content, filename=row.filename)
                        assert result.chunks, row.filename
                        formats.add(row.format)
        assert {"docx", "pdf", "pptx"} <= formats

    def test_at_least_one_workspace_produced_a_presentation(self, db, scope,
                                                            seeded):
        decks = 0
        for title in seeded["workspaces_present"]:
            ws = _workspace(db, scope, title)
            decks += sum(1 for a in repo.artifacts(db, ws.id)
                         if a.kind == "presentation")
        assert decks >= 1

    def test_a_deck_records_the_report_version_it_came_from(self, db, scope,
                                                            seeded):
        ws = _workspace(db, scope, "IFRS 9 Committee Report — Q2 2026")
        deck = next(a for a in repo.artifacts(db, ws.id)
                    if a.kind == "presentation")
        report = next(a for a in repo.artifacts(db, ws.id) if a.kind == "report")
        assert deck.derived_from_artifact_id == report.id
        assert deck.derived_from_version_id == report.current_version_id


class TestTheFiguresReconcileEverywhere:
    def test_the_ecl_figures_agree_across_analysis_report_pdf_and_deck(
            self, db, scope, seeded):
        """§14's point: one fixture, so four artefacts cannot disagree."""
        head = ecl.headline()
        current = str(head["weighted_ecl_current"].rounded)

        cards, _ = library.browse(db, scope, limit=100)
        movement = next(c for c in cards if "Quarter-on-quarter" in c.title)
        payload = library.preview(db, scope, movement.revision_id)
        assert current in payload["narrative"]

        ws = _workspace(db, scope, "IFRS 9 Committee Report — Q2 2026")
        for artifact in repo.artifacts(db, ws.id):
            version = repo.versions(db, artifact.id)[-1]
            for row in repo.files(db, version.id):
                content = store.read(row.bytes_path)
                reader = {"docx": docx_reader, "pdf": pdf_reader,
                          "pptx": pptx_reader}[row.format]
                text = " ".join(
                    [c.text for c in reader.read(content).chunks]
                    + [" ".join(str(x) for r in c.data.get("rows", [])
                                for x in r)
                       for c in reader.read(content).chunks]
                )
                assert current in text, f"{row.filename} does not state {current}"

    def test_the_scorecard_statistics_agree_between_analysis_and_report(
            self, db, scope, seeded):
        from backend.playbook.fixtures import scorecard as sc

        gini = sc.headline()["recent_gini"]
        cards, _ = library.browse(db, scope, limit=100)
        discrimination = next(c for c in cards if "Discrimination" in c.title)
        payload = library.preview(db, scope, discrimination.revision_id)
        assert gini in payload["narrative"]

        ws = _workspace(db, scope, "Behavioural Scorecard Validation Report")
        report = next(a for a in repo.artifacts(db, ws.id) if a.kind == "report")
        version = repo.versions(db, report.id)[-1]
        assert gini in str(version.content)


class TestSeedingTwiceIsSafe:
    def test_a_second_run_creates_nothing(self, db, scope, seeded):
        again = seed.reseed(db, scope)
        assert again["exports"] == 0
        assert again["exports_already_present"] == 30
        assert all(w["created"] is False for w in again["workspaces"])

    def test_the_library_does_not_double(self, db, scope, seeded):
        seed.reseed(db, scope)
        assert seed.status(db, scope)["exports_total"] == 30

    def test_an_edited_workspace_is_not_overwritten(self, db, scope, seeded):
        ws = _workspace(db, scope, "IFRS 9 Committee Report — Q2 2026")
        repo.add_message(db, ws.id, role="user",
                         content={"text": "A demonstrator's own question."},
                         origin="user")
        before = len(repo.messages(db, ws.id))

        seed.reseed(db, scope)
        after = repo.messages(db, ws.id)
        assert len(after) == before
        assert any("demonstrator's own" in str(m.content) for m in after)


class TestNothingIsAttributedToAModelThatDidNotWriteIt:
    def test_every_seeded_assistant_turn_is_marked_as_a_fixture(self, db, scope,
                                                                seeded):
        for title in seeded["workspaces_present"]:
            ws = _workspace(db, scope, title)
            for message in repo.messages(db, ws.id):
                if message.role == "assistant":
                    assert message.origin == "seed_fixture", title
                    assert message.model == "", "a fixture has no model"
                    assert message.request_ids == []

    def test_every_workspace_is_flagged_as_a_demonstration(self, db, scope,
                                                           seeded):
        for title in seeded["workspaces_present"]:
            ws = _workspace(db, scope, title)
            assert ws.demo_origin is True
            assert ws.seed_version == seed.SEED_VERSION

    def test_the_specs_and_the_catalogue_agree_on_what_is_attached(self):
        titles = {s.title for s in seed_exports.catalogue()}
        for spec in threads.threads():
            for wanted in spec.export_titles:
                assert wanted in titles, wanted
