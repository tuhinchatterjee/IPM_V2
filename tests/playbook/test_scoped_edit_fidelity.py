"""A scoped edit carries unrelated sections forward exactly. PB-017.

Written from the live failure, which reported thirteen unrelated sections as
changed while printing before/after snippets that read identically. Both halves
of that were real:

* the sections genuinely did change in canonical storage, because the merge
  base was a Markdown round-trip of the approved version rather than the
  approved version — and that round-trip drops every citation locator, `meta`
  and `subtitle`, and used to inject a section named after the document title;
* the diagnostics could not say so, because they printed `Section.text`, which
  excludes exactly the fields that had changed, and printed no hash at all.

So these tests fix the provenance of the comparison and then pin the
diagnostics that would have made the original failure readable in one line.
"""

from __future__ import annotations

import pytest

from backend.playbook import document as D
from backend.playbook import evidence as ev
from backend.playbook import grounding, merge, service
from backend.playbook import repository as repo

TITLE = "IFRS 9 Committee Report — Q2 2026"

#: Citations, a table, an ordered list, a callout and a level-2 subsection —
#: the shapes a real committee paper has and the shapes the Markdown round-trip
#: loses. The previous fixture carried no `[[locator]]` at all, which is why
#: the whole `sources` half of the comparison went untested.
BASE_MD = """# IFRS 9 Committee Report — Q2 2026

## 1. Executive summary

Weighted ECL rose to SAR 22.77 million [[fixture://oracle#weighted]].

## 2. Scenario results

| Scenario | ECL |
| --- | --- |
| Base | 19.2 |
| Downturn | 36.0 |

## 2.1 Weights

Scenario weights were unchanged [[xlsx://ECL!C2]].

## 3. Findings

1. Coverage stood at 41.3 per cent [[xlsx://ECL!D9]].
2. Stage 2 exposures were stable.

## 4. Limitations

Post-model adjustments are outside scope [[docx://para/9]].
"""


def canonical(markdown: str = BASE_MD, title: str = TITLE) -> D.Document:
    """A stored document: parsed, then through the canonical round-trip that
    persistence actually performs."""
    doc = D.parse(markdown, title=title)
    doc.subtitle = "Q2 2026"
    doc.meta = {"reporting_period": "Q2 2026", "currency": "SAR million"}
    return D.Document.from_dict(doc.as_dict())


@pytest.fixture
def ledger():
    led = ev.Ledger()
    led.add(ev.Item(locator="xlsx://ECL!B2", kind="sheet_range",
                    text="Weighted ECL 22.77; base 19.2; downturn 36.0; "
                         "coverage 41.3; stage 2",
                    origin="source", label="Results workbook"))
    return led


# ================================================== the canonical round-trip

class TestTheStoredVersionRoundTripsExactly:
    """What `Document.from_dict(as_dict(...))` guarantees, and the Markdown
    path does not. The merge base must be the first."""

    def test_the_canonical_form_is_lossless(self):
        doc = canonical()
        again = D.Document.from_dict(doc.as_dict())
        assert again.content_hash() == doc.content_hash()
        assert [merge.section_hash(s) for s in again.sections] == \
               [merge.section_hash(s) for s in doc.sections]

    def test_the_markdown_form_is_not_and_that_is_why_it_is_not_the_base(self):
        """Pinned as a fact rather than assumed. The Markdown is for the prompt
        and the thread; if it ever became lossless this test should be the
        thing that notices."""
        doc = canonical()
        back = D.parse(service._markdown_of(doc), title=TITLE)
        assert doc.sources and back.sources == []
        assert back.subtitle == "" and back.meta == {}

    def test_a_title_heading_is_not_a_section(self):
        """The phantom section. `_markdown_of` writes "# {title}" and `parse`
        was called with that same title, so the H1 fell through and became an
        empty section named after the document."""
        doc = canonical()
        back = D.parse(service._markdown_of(doc), title=TITLE)
        assert [s.heading for s in back.sections] == \
               [s.heading for s in doc.sections]

    def test_the_merge_base_is_the_stored_document_not_a_re_render(self):
        drafted = D.parse(
            BASE_MD.replace("Weighted ECL rose to SAR 22.77 million",
                            "ECL rose to SAR 22.77 million"), title=TITLE)
        result = merge.scoped_merge(canonical(), drafted,
                                    "the executive summary")
        assert merge.unchanged_outside(canonical(), result.document,
                                       "the executive summary") == []


# ========================================================= through the service

@pytest.mark.usefixtures("db")
class TestTheLiveShape:
    """Create, then revise one section, through `author_document` itself."""

    def _create(self, db, scope, workspace, ledger, scripted_author):
        scripted_author(BASE_MD)
        return service.author_document(
            db, scope, workspace.id, instruction="Write the report.",
            ledger=ledger, title=TITLE, formats=["docx"], task_kind="create")

    def test_no_unrelated_section_changes_in_canonical_storage(
            self, db, scope, workspace, ledger, scripted_author):
        first = self._create(db, scope, workspace, ledger, scripted_author)

        # The model returns a whole document, paraphrasing sections it was not
        # asked to touch — which is what a real one does.
        scripted_author(BASE_MD
                        .replace("Weighted ECL rose to", "ECL climbed to")
                        .replace("Post-model adjustments are outside scope",
                                 "PMAs are out of scope"))
        second = service.author_document(
            db, scope, workspace.id, instruction="Sharpen it.",
            ledger=ledger, title=TITLE, formats=["docx"], task_kind="edit",
            task_scope="the executive summary",
            artifact_id=first.artifact_id, base_version_id=first.version_id)

        versions = repo.versions(db, first.artifact_id)
        stored_v1 = D.Document.from_dict(versions[0].content)
        stored_v2 = D.Document.from_dict(versions[1].content)
        assert merge.unchanged_outside(stored_v1, stored_v2,
                                       "the executive summary") == []
        assert second.rejected_sections == ["4. Limitations"]

    def test_the_requested_section_does_change(
            self, db, scope, workspace, ledger, scripted_author):
        first = self._create(db, scope, workspace, ledger, scripted_author)
        scripted_author(BASE_MD.replace("Weighted ECL rose to",
                                        "ECL climbed to"))
        second = service.author_document(
            db, scope, workspace.id, instruction="Sharpen it.",
            ledger=ledger, title=TITLE, formats=["docx"], task_kind="edit",
            task_scope="the executive summary",
            artifact_id=first.artifact_id, base_version_id=first.version_id)
        target = second.document.section("the executive summary")
        assert "ECL climbed to" in target.text

    def test_citations_survive_the_revision(
            self, db, scope, workspace, ledger, scripted_author):
        """The field the live failure actually lost, and the one a text diff
        cannot show."""
        first = self._create(db, scope, workspace, ledger, scripted_author)
        scripted_author(BASE_MD.replace("Weighted ECL rose to",
                                        "ECL climbed to"))
        second = service.author_document(
            db, scope, workspace.id, instruction="Sharpen it.",
            ledger=ledger, title=TITLE, formats=["docx"], task_kind="edit",
            task_scope="the executive summary",
            artifact_id=first.artifact_id, base_version_id=first.version_id)
        assert "docx://para/9" in second.document.sources
        assert "xlsx://ECL!C2" in second.document.sources

    def test_the_header_block_is_carried_forward_from_the_approved_version(
            self):
        """`subtitle` and `meta` are the two fields a Markdown base dropped
        entirely. Asserted on the merge, where the approved version is the one
        that actually has them."""
        base = canonical()
        drafted = D.parse(BASE_MD, title=TITLE)   # a model reply has neither
        merged = merge.scoped_merge(base, drafted, "the executive summary")
        assert merged.document.subtitle == "Q2 2026"
        assert merged.document.meta["reporting_period"] == "Q2 2026"


# ============================================================== grounding

class TestGroundingStaysInsideTheScope:

    def _document(self) -> D.Document:
        return canonical(
            "# R\n\n## 1. Executive summary\n\nCoverage is 41.3 per cent.\n\n"
            "## 2. Untouched\n\nStage 3 exposures were SAR 128.4 million.\n",
            title="R")

    def _narrow_ledger(self) -> ev.Ledger:
        led = ev.Ledger()
        led.add(ev.Item(locator="xlsx://A1", kind="sheet_range",
                        text="coverage 41.3", origin="source", label="Sheet"))
        return led

    def test_a_figure_in_a_carried_forward_section_is_not_removed(self):
        doc = self._document()
        result = grounding.check(doc, self._narrow_ledger(),
                                 scope={"1. Executive summary"})
        assert result.ok is True
        assert "128.4" in doc.section("2. Untouched").text
        assert result.attested == ["2. Untouched"]

    def test_without_a_scope_every_section_is_still_checked(self):
        """The create path, unchanged. The narrowing is a property of a scoped
        edit, not of grounding."""
        doc = self._document()
        result = grounding.check(doc, self._narrow_ledger())
        assert result.ok is False
        assert "128.4" not in doc.section("2. Untouched").text

    def test_an_invented_figure_inside_the_scope_is_still_removed(self):
        doc = canonical(
            "# R\n\n## 1. Executive summary\n\nCoverage is 99.9 per cent.\n\n"
            "## 2. Untouched\n\nNothing numeric.\n", title="R")
        result = grounding.check(doc, self._narrow_ledger(),
                                 scope={"1. Executive summary"})
        assert result.ok is False
        assert "99.9" not in doc.section("1. Executive summary").text

    def test_a_re_rounded_figure_inside_the_scope_is_still_caught(self):
        doc = canonical(
            "# R\n\n## 1. Executive summary\n\nCoverage is 41.4 per cent.\n",
            title="R")
        result = grounding.check(doc, self._narrow_ledger(),
                                 scope={"1. Executive summary"})
        assert result.ok is False


# ============================================================== diagnostics

class TestTheDiagnosticsALiveFailureNeeded:

    def test_a_sources_only_change_prints_the_field_not_two_equal_strings(self):
        before = canonical()
        after = canonical()
        after.sections[-1].blocks[0].sources = []
        entry = next(e for e in merge.diff_sections(before, after)
                     if e["section"] == "4. Limitations")
        assert entry["before"] == entry["after"]      # the original confusion
        assert entry["field"] == "blocks[0].sources"  # and the way out of it
        assert entry["before_hash"] != entry["after_hash"]

    def test_every_entry_carries_both_canonical_hashes(self):
        before = canonical()
        after = canonical()
        after.sections[-1].blocks[0].text = "Rewritten."
        entry = next(e for e in merge.diff_sections(before, after)
                     if e["section"] == "4. Limitations")
        assert len(entry["before_hash"]) == 64
        assert entry["before_hash"] != entry["after_hash"]

    def test_the_first_differing_character_is_named(self):
        diff = merge.first_difference("Coverage is 41.3 per cent.",
                                      "Coverage is 41.4 per cent.")
        assert diff["offset"] == 15
        assert diff["before"].startswith("3") and diff["after"].startswith("4")

    def test_a_whitespace_difference_is_reported_as_a_codepoint(self):
        """The case that printed as two identical-looking strings."""
        diff = merge.first_difference("a b", "a b")
        assert diff["before_codepoint"] == "U+0020"
        assert diff["after_codepoint"] == "U+00A0"

    def test_identical_strings_have_no_first_difference(self):
        assert merge.first_difference("same", "same") is None

    def test_canonical_drift_and_render_normalisation_are_told_apart(self):
        doc = canonical()
        same = merge.section_hash(doc.sections[0])
        drifted = merge.section_hash(canonical().sections[1])
        assert merge.classify(same, same, "a b", "a  b") == \
            merge.RENDER_NORMALISED
        assert merge.classify(same, drifted, "a", "a") == merge.CANONICAL_DRIFT
        assert merge.classify(same, same, "a", "a") == ""

    def test_classification_never_calls_differing_content_equivalent(self):
        """No semantic tolerance. Different canonical content is drift even
        when the rendered text matches."""
        a, b = "hash-a", "hash-b"
        assert merge.classify(a, b, "identical", "identical") == \
            merge.CANONICAL_DRIFT
