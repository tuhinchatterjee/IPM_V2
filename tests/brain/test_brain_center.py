"""The Brain Center end to end. §13-§26.

Two things this suite is for.

The first is the round trip: build a package here, take it back in as though
it came from somewhere else, walk it through quarantine, and prove that at no
point before activation is any of it reachable from a live answer.

The second is the refusals. Most of the value in this subsystem is in what it
declines to do, and a refusal that is never exercised is a refusal that will
be quietly removed by a later edit. So every gate gets a test that trips it.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from backend.brain import bundle, ledger, pack, quarantine
from backend.brain import status as bstatus

# ================================================== §15 the bundle builders


def _manifest(kind: str = pack.BRAIN_PACK) -> pack.Manifest:
    return pack.Manifest(
        brain_id="brain-test", brain_name="Test Brain",
        brain_version="1.0.0", package_kind=kind,
        created_by="tester", source_instance_id="inst-a",
        source_build_sha="abc123", app_version="0.3.0",
        ontology_version="2.0.0", minimum_app_version="0.3.0",
    )


def _source(**over) -> bundle.Source:
    base = bundle.collect(
        teaching_cases=[{
            "case_id": "tc-1", "status": bstatus.HUMAN_APPROVED,
            "question": "What is total ECL by stage?",
            "body": {"expected": "grouped"},
        }],
        evaluations={"approved_case_count": 1},
    )
    for key, value in over.items():
        setattr(base, key, value)
    return base


def test_collect_reads_the_live_registries_rather_than_a_fixture():
    """A bundle built from a hard-coded list would ship a Brain that has
    nothing to do with what this installation actually runs."""
    source = bundle.collect()

    assert source.ontology["ontology_version"]
    assert len(source.ontology["concepts"]) >= 20
    assert len(source.blueprints) >= 10
    assert len(source.agents) >= 10
    assert source.routing["roles"]


def test_only_approved_teaching_cases_leave_this_installation():
    """§2: generated, migrated and Claude-authored cases are not human
    reviewed, and a receiver reading a case labelled approved is entitled to
    assume a person read it here."""
    source = bundle.collect(teaching_cases=[
        {"case_id": "a", "status": bstatus.HUMAN_APPROVED},
        {"case_id": "b", "status": bstatus.SYSTEM_REFERENCE_VALIDATED},
        {"case_id": "c", "status": bstatus.AUTO_GENERATED},
        {"case_id": "d", "status": bstatus.HUMAN_REVIEWED},
    ])

    assert [c["case_id"] for c in source.teaching_cases] == ["a"]


def test_the_routing_policy_carries_roles_and_never_a_model_identifier():
    """A package naming a model would carry the sender's procurement
    decision into a receiver that may not have that model at all."""
    source = bundle.collect()
    text = json.dumps(source.routing).lower()

    for forbidden in ("claude-", "gpt-", "sonnet-2", "opus-2"):
        assert forbidden not in text, forbidden


def test_a_learning_bundle_without_a_baseline_is_refused():
    """A delta with no baseline reads to a receiver as though this is
    everything the sender knows, and that leads to the opposite decision."""
    with pytest.raises(bundle.BundleError) as caught:
        bundle.learning_bundle(_source(), _manifest(pack.LEARNING_BUNDLE))

    assert "baseline" in str(caught.value)


def test_an_empty_learning_bundle_is_refused_rather_than_shipped():
    source = _source(teaching_cases=[], learning=[])

    with pytest.raises(bundle.BundleError) as caught:
        bundle.learning_bundle(source, _manifest(pack.LEARNING_BUNDLE),
                               baseline_release_id="rel-1")

    assert "nothing portable" in str(caught.value)


# ============================================ §15 README_FOR_CLAUDE_CODE.md


def test_the_developer_bundle_carries_the_readme_section_15_asks_for():
    contents = bundle.developer_bundle(_source(), _manifest())

    assert "README_FOR_CLAUDE_CODE.md" in contents.files
    readme = contents.files["README_FOR_CLAUDE_CODE.md"]

    # §15's six required sections.
    for heading in ("## What is in it", "## Versions",
                    "## How to inspect it",
                    "## How to import it into a repository",
                    "## What must NOT be trusted without evaluation",
                    "## What stays local and confidential"):
        assert heading in readme, heading


def test_the_readme_says_what_must_not_be_trusted_in_specific_terms():
    """"Verify before use" is advice nobody acts on. The README has to name
    which asset misleads and how."""
    readme = bundle.readme_for_claude_code(_source(), _manifest())

    assert "correct there can be confidently wrong here" in readme
    assert "sender's holdout" in readme
    assert "different regulator's rules" in readme
    assert "provenance, not proof" in readme


def test_the_readme_lists_every_exclusion_so_a_reader_can_check_the_tree():
    readme = bundle.readme_for_claude_code(_source(), _manifest())

    for exclusion in bundle.DEVELOPER_EXCLUSIONS:
        assert exclusion in readme


# ================================================= §10 the export refusals


def test_an_export_carrying_a_secret_is_refused_rather_than_warned_about(
        tmp_path):
    """Every check that runs on import runs on export. An installation that
    trusted its own export is the one that ships the problem."""
    contents = bundle.brain_pack(_source(), _manifest())
    contents.add("prompts/templates.json",
                 {"key": "sk-ant-api03-" + "x" * 60})

    with pytest.raises(pack.PackError) as caught:
        pack.write(tmp_path / "leak.cpbrain", _manifest(), contents)

    assert "may not be written" in str(caught.value)


def test_an_export_carrying_holdout_content_is_refused(tmp_path):
    """A score produced against a holdout the candidate carried is
    flattering rather than wrong, and nothing downstream could tell."""
    contents = bundle.brain_pack(_source(), _manifest())
    contents.files["teaching/holdout/gold.jsonl"] = '{"q": "x"}'

    with pytest.raises(pack.PackError) as caught:
        pack.write(tmp_path / "sealed.cpbrain", _manifest(), contents)

    assert "sealed holdout" in str(caught.value)


def test_a_written_package_round_trips_and_contains_no_executable_member(
        tmp_path):
    target = pack.write(tmp_path / "ok.cpbrain", _manifest(),
                        bundle.brain_pack(_source(), _manifest()))

    with zipfile.ZipFile(target) as archive:
        names = archive.namelist()
    assert "manifest.json" in names
    assert "checksums.json" in names
    for name in names:
        assert Path(name).suffix in (".json", ".jsonl", ".md", ".csv", ""), name

    opened = pack.read(target)
    assert opened.manifest.brain_id == "brain-test"


# ==================================================== §14 ledger portability


def _entry(**over) -> ledger.Entry:
    fields = {"source": ledger.ASK, "summary": "a thing was learned",
              "object_kind": "answer", "object_id": "run-1"}
    fields.update(over)
    return ledger.Entry(**fields)


def test_a_ledger_entry_is_local_until_somebody_decides_otherwise():
    """NON_PORTABLE is the default. Most learning names a borrower or quotes
    a confidential document and is nobody else's business."""
    assert _entry().portability == ledger.NON_PORTABLE
    assert _entry().exportable is False


def test_approved_but_local_stays_local_and_portable_but_unapproved_is_not_yet():
    approved_local = _entry(review_status=ledger.APPROVED,
                            portability=ledger.NON_PORTABLE)
    portable_unapproved = _entry(review_status=ledger.CAPTURED,
                                 portability=ledger.PORTABLE)

    assert approved_local.exportable is False
    assert portable_unapproved.exportable is False
    assert _entry(review_status=ledger.APPROVED,
                  portability=ledger.PORTABLE).exportable is True


def test_portable_view_refuses_rather_than_redacting_until_it_fits():
    """Stripping fields until an entry qualifies turns a governance gate
    into a formatting step."""
    with pytest.raises(ledger.LedgerError):
        ledger.portable_view(_entry())


def test_portable_view_drops_who_we_are_and_keeps_what_was_learned():
    entry = _entry(review_status=ledger.APPROVED,
                   portability=ledger.PORTABLE, tenant="bank-a",
                   user_id="u-9", reviewer="alice",
                   review_note="looked fine to me")

    view = ledger.portable_view(entry)

    assert view["summary"] == "a thing was learned"
    assert "tenant" not in view
    assert "user_id" not in view
    assert "reviewer" not in view
    assert "review_note" not in view


# ============================================== §16 quarantine, end to end


@pytest.fixture
def package(tmp_path) -> Path:
    """A real, signed package built by this installation's own exporter."""
    manifest = _manifest()
    manifest.signature = ""
    return pack.write(tmp_path / "candidate.cpbrain", manifest,
                      bundle.brain_pack(_source(), manifest),
                      signing_key=b"a-shared-verification-key",
                      signing_key_id="key-1")


def test_a_candidate_is_never_retrievable_before_activation(package):
    """The whole point of §16's first sentence."""
    candidate = quarantine.Candidate(digest="d", uploaded_by="tester")

    for stage in quarantine.PIPELINE:
        if stage == quarantine.ACTIVE:
            break
        assert candidate.retrievable is False, stage
        candidate = quarantine.advance(candidate, stage, by="tester") \
            if stage != quarantine.UPLOADED else candidate


def test_the_pipeline_refuses_a_skipped_stage(package):
    candidate = quarantine.Candidate(uploaded_by="tester")

    with pytest.raises(quarantine.QuarantineError) as caught:
        quarantine.advance(candidate, quarantine.STAGED, by="tester")

    assert "STAGED" in str(caught.value)
