"""
The two-Brain merge. §21, §22.

The tests that matter here are the refusals. A merge that produces *a*
package is easy; the question is whether it produced one whose behaviour
somebody chose.
"""

from __future__ import annotations

import pytest

from backend.brain import conflicts as conflicts_mod
from backend.brain import merge, pack


def _items(**kinds):
    return {kind: dict(items) for kind, items in kinds.items()}


def _settled(kind, item_id, resolution, *, risk="medium", axis=""):
    conflict = conflicts_mod.Conflict(
        conflict_class=conflicts_mod.METHOD_FORMULA, kind=kind, risk=risk,
        local=conflicts_mod.Side("local", item_id, value="ours"),
        incoming=conflicts_mod.Side("incoming", item_id, value="theirs"))
    return conflicts_mod.resolve(
        conflict, resolution, by="reviewer@bank",
        why="the local definition matches the circular in force here",
        split_axis=axis)


def _manifest(brain_id="brain_local", name="Local"):
    return pack.Manifest(
        brain_id=brain_id, brain_name=name, brain_version="1.0.0",
        created_at="2026-01-01T00:00:00+00:00", created_by="ops@bank",
        source_instance_id="inst-1", source_build_sha="abc1234",
        app_version="0.3.0",
        ontology_version="2.0.0", supported_modules=("core", "teaching"),
        supported_languages=("en", "ar"), minimum_app_version="0.3.0")


# ------------------------------------------------------------- the refusals


def test_a_merge_refuses_while_any_conflict_is_still_open():
    open_conflict = conflicts_mod.Conflict(
        conflict_class=conflicts_mod.METHOD_FORMULA, kind="methods",
        local=conflicts_mod.Side("local", "m1", value="a"),
        incoming=conflicts_mod.Side("incoming", "m1", value="b"))
    assert open_conflict.status == "OPEN"

    with pytest.raises(merge.MergeError) as caught:
        merge.merge(_items(methods={"m1": {"value": "a"}}),
                    _items(methods={"m1": {"value": "b"}}),
                    [open_conflict], by="ops@bank")
    assert "nobody chose" in str(caught.value)


def test_a_high_risk_deferral_still_blocks_the_merge():
    """Deferring answers "which is right", not "may this activate"."""
    deferred = _settled("regulatory", "r1", conflicts_mod.DEFER, risk="high")
    assert deferred.status == "DEFERRED"

    with pytest.raises(merge.MergeError):
        merge.merge(_items(regulatory={"r1": {"value": "a"}}),
                    _items(regulatory={"r1": {"value": "b"}}),
                    [deferred], by="ops@bank")


def test_a_merge_will_not_author_the_content_it_was_told_to_write():
    """CREATE_NEW_VERSION is a decision to write something, not a merge rule.

    Synthesising the merge of two ECL definitions produces a definition
    neither institution uses, which is worse than refusing.
    """
    settled = _settled("methods", "ecl", conflicts_mod.CREATE_NEW_VERSION)
    with pytest.raises(merge.MergeError) as caught:
        merge.merge(_items(methods={"ecl": {"value": "a"}}),
                    _items(methods={"ecl": {"value": "b"}}),
                    [settled], by="ops@bank")
    message = str(caught.value)
    assert "neither institution uses" in message
    assert "No body was supplied" in message


def test_supplying_the_authored_body_lets_the_same_merge_proceed():
    settled = _settled("methods", "ecl", conflicts_mod.MERGE_MANUALLY)
    merged = merge.merge(
        _items(methods={"ecl": {"value": "a"}}),
        _items(methods={"ecl": {"value": "b"}}),
        [settled], by="ops@bank",
        authored={settled.conflict_id: {"value": "agreed wording"}})
    assert merged.items["methods"]["ecl"] == {"value": "agreed wording"}
    assert merged.authored[0].outcome == merge.AUTHORED_MANUAL_MERGE


def test_an_unsigned_merge_is_refused():
    with pytest.raises(merge.MergeError):
        merge.merge({}, {}, [], by="   ")


# ----------------------------------------------------------- what it decides


@pytest.mark.parametrize(
    "resolution,expected_outcome,expected_value",
    [
        (conflicts_mod.KEEP_LOCAL, merge.TAKEN_LOCAL, "ours"),
        (conflicts_mod.ACCEPT_INCOMING, merge.TAKEN_INCOMING, "theirs"),
        # RETIRE_LOCAL retires the local item, so incoming is what survives.
        (conflicts_mod.RETIRE_LOCAL, merge.RETIRED_LOCAL, "theirs"),
        (conflicts_mod.RETIRE_INCOMING, merge.RETIRED_INCOMING, "ours"),
    ])
def test_each_resolution_leaves_the_side_it_says_standing(
        resolution, expected_outcome, expected_value):
    settled = _settled("methods", "m1", resolution)
    merged = merge.merge(
        _items(methods={"m1": {"value": "ours"}}),
        _items(methods={"m1": {"value": "theirs"}}),
        [settled], by="ops@bank")
    decision = merged.decisions[0]
    assert decision.outcome == expected_outcome
    assert merged.items["methods"]["m1"]["value"] == expected_value


def test_a_deferred_conflict_leaves_the_item_out_rather_than_keeping_local():
    """The failure this prevents: "we could not decide, so we chose local".

    A low-risk deferral does not block the merge, so the merge has to say
    what it did with the item. Leaving it out and reporting it as dormant is
    a decision a reviewer can see; silently falling back to local is not.
    """
    settled = _settled("blueprints", "b1", conflicts_mod.DEFER, risk="low")
    merged = merge.merge(
        _items(blueprints={"b1": {"value": "ours"}}),
        _items(blueprints={"b1": {"value": "theirs"}}),
        [settled], by="ops@bank")

    assert "blueprints" not in merged.items
    assert [d.outcome for d in merged.dormant] == [merge.DORMANT]
    assert merged.dormant[0].origin == ""


def test_uncontested_items_from_both_sides_carry_through():
    merged = merge.merge(
        _items(cases={"c1": {"value": "a"}, "shared": {"value": "s"}}),
        _items(cases={"c2": {"value": "b"}, "shared": {"value": "s"}}),
        [], by="ops@bank")
    assert set(merged.items["cases"]) == {"c1", "c2", "shared"}
    origins = {d.item_id: d.origin for d in merged.decisions}
    assert origins == {"c1": "local", "c2": "incoming", "shared": "both"}


def test_a_scope_split_keeps_both_and_records_the_axis():
    settled = _settled("regulatory", "r1", conflicts_mod.SCOPE_SPLIT,
                       axis="jurisdiction")
    merged = merge.merge(
        _items(regulatory={"r1": {"value": "ours"}}),
        _items(regulatory={"r1": {"value": "theirs"}}),
        [settled], by="ops@bank")
    item = merged.items["regulatory"]["r1"]
    assert item["scoped"] is True
    assert item["split_axis"] == "jurisdiction"
    assert {b["origin"] for b in item["branches"]} == {"local", "incoming"}


def test_every_decision_names_who_made_it_and_why():
    settled = _settled("methods", "m1", conflicts_mod.KEEP_LOCAL)
    merged = merge.merge(
        _items(methods={"m1": {"value": "ours"}}),
        _items(methods={"m1": {"value": "theirs"}}),
        [settled], by="ops@bank")
    decision = merged.decisions[0]
    assert decision.decided_by == "reviewer@bank"
    assert "circular in force" in decision.reason
    assert decision.conflict_id == settled.conflict_id


# ------------------------------------------------------------- the manifest


def test_the_merged_manifest_names_both_parents_and_carries_no_scores():
    """The one that would hide a regression.

    Inheriting the better parent's numbers would make the merged Brain look
    evaluated when it has never been run.
    """
    local = _manifest("brain_local", "Local")
    incoming = _manifest("brain_riyadh", "Riyadh")
    local.evaluation_metrics = {"validation": 0.88}
    incoming.evaluation_metrics = {"validation": 0.91}

    merged = merge.merge(_items(cases={"c1": {"value": "a"}}),
                         _items(cases={"c2": {"value": "b"}}),
                         [], by="ops@bank")
    manifest = merge.manifest_for(
        merged, brain_name="Merged", brain_version="1.0.0",
        local_manifest=local, incoming_manifest=incoming,
        created_by="ops@bank")

    assert manifest.parent_brain_ids == ("brain_local", "brain_riyadh")
    assert manifest.evaluation_metrics == {}
    assert any("has not been evaluated" in limitation
               for limitation in manifest.known_limitations)
    assert manifest.merge_history[-1]["local_brain_id"] == "brain_local"


def test_the_merged_manifest_takes_the_intersection_of_supported_modules():
    """A merged Brain supports what both parents support, not either."""
    local, incoming = _manifest(), _manifest("brain_r", "Riyadh")
    local.supported_modules = ("core", "teaching", "retail")
    incoming.supported_modules = ("core", "teaching", "corporate")
    merged = merge.merge({}, {}, [], by="ops@bank")
    manifest = merge.manifest_for(
        merged, brain_name="M", brain_version="1.0.0",
        local_manifest=local, incoming_manifest=incoming, created_by="o@b")
    assert manifest.supported_modules == ("core", "teaching")


# ------------------------------------------------------------- the package


def test_the_package_carries_the_decision_record_with_it():
    merged = merge.merge(_items(cases={"c1": {"value": "a"}}),
                         _items(cases={"c2": {"value": "b"}}),
                         [], by="ops@bank")
    manifest = merge.manifest_for(
        merged, brain_name="M", brain_version="1.0.0",
        local_manifest=_manifest(), incoming_manifest=_manifest("brain_r"),
        created_by="ops@bank")
    contents = merge.package(merged, manifest)

    assert "provenance/decisions.jsonl" in contents.files
    assert "provenance/merge.json" in contents.files
    assert "teaching/cases.jsonl" in contents.files
    assert '"evaluated": false' in contents.files["evaluations/summary.json"]
    assert ('"inherited_from_parents": false'
            in contents.files["evaluations/summary.json"])


def test_a_merged_kind_with_nowhere_to_go_is_refused_not_dropped():
    """Silently losing a whole category of learning looks like success."""
    merged = merge.merge(_items(unheard_of={"x": {"value": 1}}), {}, [],
                         by="ops@bank")
    manifest = merge.manifest_for(
        merged, brain_name="M", brain_version="1.0.0",
        local_manifest=_manifest(), incoming_manifest=_manifest("brain_r"),
        created_by="ops@bank")
    with pytest.raises(merge.MergeError) as caught:
        merge.package(merged, manifest)
    assert "silently lose" in str(caught.value)


def test_every_package_path_is_inside_the_governed_directory_layout():
    """A merged package must not invent a top-level folder."""
    tops = {path.split("/")[0] for path in merge.KIND_PATHS.values()}
    assert tops <= set(pack.DIRECTORIES)


def test_the_merge_record_says_the_brain_has_never_been_evaluated():
    merged = merge.merge(_items(cases={"c1": {"value": "a"}}), {}, [],
                         by="ops@bank")
    body = merged.to_dict()
    assert "never been evaluated" in body["note"]
    assert body["items_total"] == 1
