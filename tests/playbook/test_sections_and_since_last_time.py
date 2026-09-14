"""Sections that hold their identity, and a comparison that refuses to mislead.

Gate 4 — a section is a thing with a life. Its identity survives a retitle,
its status survives a reload, its transitions are checked against a table and
recorded with who made them, and the ones that are governance acts refuse a
caller with no name. A section's metrics, findings, sources and reviewers are
answerable in one read, because a pane that needs five round trips is a pane
nobody keeps open.

Gate 5 — THEN is the frozen reading a version actually relied on, never
touched again. NOW is the latest GOVERNED value for the same identity in the
same context. Where the context disagrees this says *not comparable* and names
the dimension, because a missing comparison is a fact a reader can act on and
a misleading delta is not. A difference between two percentages is percentage
POINTS: calling a 0.61pp move "0.61%" is the unit slip that survives review
and reaches a committee.
"""

from __future__ import annotations

import pytest

from backend.exports import playbook_contract as contract
from backend.models.playbook import (
    PlaybookDocumentSection,
    PlaybookFinding,
    PlaybookMetricSnapshot,
    PlaybookReview,
)
from backend.playbook import document as D
from backend.playbook import repository as repo
from backend.playbook.intelligence import binding as bind
from backend.playbook.intelligence import compare
from backend.playbook.intelligence import sections as sect
from backend.playbook.intelligence import service as svc

ACTOR = "user:7"
BODY = "considered judgement " * 15


def _doc(*headings: str) -> D.Document:
    return D.parse("".join(f"## {h}\n\n{BODY}\n\n" for h in headings),
                   title="Report")


def _versioned(db, workspace, doc: D.Document, *, artifact=None, version=1):
    if artifact is None:
        artifact = repo.create_artifact(db, workspace.id, kind="report",
                                        title="Report")
        db.flush()
    repo.new_version(db, artifact, content=doc.as_dict(), source_manifest={},
                     content_hash=doc.content_hash(), validation={})
    db.flush()
    sect.sync(db, artifact.id, doc, version=version)
    return artifact


# ====================================================== Gate 4: transitions

@pytest.mark.usefixtures("db")
class TestStatusTransitionsAreDeterministic:

    @pytest.fixture
    def row(self, db, workspace):
        artifact = _versioned(db, workspace, _doc("1. Summary"))
        return (db.query(PlaybookDocumentSection)
                .filter(PlaybookDocumentSection.artifact_id == artifact.id)
                .one())

    def test_a_generated_section_may_go_for_review(self, db, row):
        sect.transition(db, row, to=sect.READY_FOR_REVIEW, actor=ACTOR)
        assert row.status == sect.READY_FOR_REVIEW

    def test_an_illegal_transition_is_refused_and_says_what_is_legal(self, db,
                                                                     row):
        with pytest.raises(sect.TransitionRefused) as raised:
            sect.transition(db, row, to=sect.APPROVED, actor=ACTOR)
        assert "cannot become" in str(raised.value)
        assert "ready_for_review" in str(raised.value)
        assert row.status == sect.GENERATED

    def test_an_unknown_status_is_refused(self, db, row):
        with pytest.raises(sect.TransitionRefused):
            sect.transition(db, row, to="nearly_done", actor=ACTOR)

    def test_the_route_to_approved_goes_through_review(self, db, row):
        sect.transition(db, row, to=sect.READY_FOR_REVIEW, actor=ACTOR)
        sect.transition(db, row, to=sect.APPROVED, actor=ACTOR)
        assert row.status == sect.APPROVED and row.reviewed_at is not None

    def test_approval_is_a_persons_act(self, db, row):
        """§27. A model may say a section looks finished; it may not record
        that a human agreed."""
        sect.transition(db, row, to=sect.READY_FOR_REVIEW, actor=ACTOR)
        with pytest.raises(sect.TransitionRefused) as raised:
            sect.transition(db, row, to=sect.APPROVED, actor="")
        assert "records who did it" in str(raised.value)

    def test_the_system_may_never_approve(self, db, row):
        sect.transition(db, row, to=sect.READY_FOR_REVIEW, actor=ACTOR)
        with pytest.raises(sect.TransitionRefused) as raised:
            sect.transition(db, row, to=sect.APPROVED, by_system=True)
        assert "a person's decision" in str(raised.value)

    def test_every_transition_is_recorded(self, db, row):
        sect.transition(db, row, to=sect.READY_FOR_REVIEW, actor=ACTOR,
                        reason="drafting finished")
        sect.transition(db, row, to=sect.APPROVED, actor="user:9")
        assert [h["to"] for h in row.history] == [sect.READY_FOR_REVIEW,
                                                  sect.APPROVED]
        assert row.history[0]["from"] == sect.GENERATED
        assert row.history[0]["actor"] == ACTOR
        assert row.history[0]["reason"] == "drafting finished"
        assert row.history[1]["actor"] == "user:9"
        assert all(h["at"] for h in row.history)

    def test_a_no_op_transition_writes_nothing(self, db, row):
        sect.transition(db, row, to=row.status, actor=ACTOR)
        assert row.history == []

    def test_assigning_a_reviewer_names_both_people(self, db, row):
        sect.assign_reviewer(db, row, reviewer="a.reviewer", actor=ACTOR)
        assert row.reviewer == "a.reviewer"
        assert row.status == sect.READY_FOR_REVIEW
        assert row.history[-1]["actor"] == ACTOR
        assert "a.reviewer" in row.history[-1]["reason"]

    def test_assigning_needs_an_assigner(self, db, row):
        with pytest.raises(sect.TransitionRefused):
            sect.assign_reviewer(db, row, reviewer="a.reviewer", actor="")

    def test_assigning_needs_a_named_reviewer(self, db, row):
        with pytest.raises(sect.TransitionRefused):
            sect.assign_reviewer(db, row, reviewer="   ", actor=ACTOR)


@pytest.mark.usefixtures("db")
class TestTheDocumentCanMoveASectionButOnlyDownwards:

    def test_a_changed_section_loses_its_approval_and_says_why(self, db,
                                                               workspace):
        artifact = _versioned(db, workspace, _doc("1. Summary"))
        row = (db.query(PlaybookDocumentSection)
               .filter(PlaybookDocumentSection.artifact_id == artifact.id)
               .one())
        sect.transition(db, row, to=sect.READY_FOR_REVIEW, actor=ACTOR)
        sect.transition(db, row, to=sect.APPROVED, actor=ACTOR)

        changed = D.parse("## 1. Summary\n\n" + "different " * 30,
                          title="Report")
        _versioned(db, workspace, changed, artifact=artifact, version=2)
        db.refresh(row)
        assert row.status == sect.NEEDS_REVIEW
        assert row.reviewed_at is None
        assert row.history[-1]["actor"] == "system"
        assert "changed since" in row.history[-1]["reason"]

    def test_status_survives_a_reload(self, db, workspace):
        artifact = _versioned(db, workspace, _doc("1. Summary"))
        row = (db.query(PlaybookDocumentSection)
               .filter(PlaybookDocumentSection.artifact_id == artifact.id)
               .one())
        sect.transition(db, row, to=sect.READY_FOR_REVIEW, actor=ACTOR)
        key = row.section_key
        db.expire_all()

        again = (db.query(PlaybookDocumentSection)
                 .filter(PlaybookDocumentSection.section_key == key).one())
        assert again.status == sect.READY_FOR_REVIEW
        assert again.history[-1]["actor"] == ACTOR

    def test_a_retitled_section_keeps_its_status_and_history(self, db,
                                                             workspace):
        artifact = _versioned(db, workspace, _doc("1. Executive summary"))
        row = (db.query(PlaybookDocumentSection)
               .filter(PlaybookDocumentSection.artifact_id == artifact.id)
               .one())
        sect.assign_reviewer(db, row, reviewer="a.reviewer", actor=ACTOR)
        before = row.section_key

        _versioned(db, workspace, _doc("1. Summary and key judgements"),
                   artifact=artifact, version=2)
        db.refresh(row)
        assert row.section_key == before
        assert row.reviewer == "a.reviewer"
        assert row.history


@pytest.mark.usefixtures("db")
class TestASectionIsAnswerableInOneRead:

    def test_metrics_findings_reviews_and_history_come_back_together(
            self, db, workspace):
        artifact = _versioned(db, workspace, _doc("1. Summary"))
        row = (db.query(PlaybookDocumentSection)
               .filter(PlaybookDocumentSection.artifact_id == artifact.id)
               .one())
        key = row.section_key

        proposals = bind.from_export(
            [contract.Metric(metric_id="scorecard.gini", label="Gini",
                             display_value="0.415")], module="validation")
        proposals[0].section_key = key
        bind.apply(db, workspace.id, proposals, artifact_id=artifact.id)
        db.add(PlaybookFinding(workspace_id=workspace.id, section_key=key,
                               reference="F-01", title="Gini fell",
                               severity="high", blocking=True))
        db.add(PlaybookReview(workspace_id=workspace.id, section_key=key,
                              reviewer="a.reviewer", role="model risk"))
        db.flush()
        sect.transition(db, row, to=sect.READY_FOR_REVIEW, actor=ACTOR)

        detail = sect.detail(db, artifact.id, key, workspace.id)
        assert detail["heading"] == "1. Summary"
        assert detail["status"] == sect.READY_FOR_REVIEW
        assert detail["metrics"][0]["metric_id"] == "scorecard.gini"
        assert detail["metrics"][0]["governed"] is True
        assert detail["findings"][0]["reference"] == "F-01"
        assert detail["reviews"][0]["reviewer"] == "a.reviewer"
        assert detail["history"][-1]["to"] == sect.READY_FOR_REVIEW
        assert sect.APPROVED in detail["may_become"]

    def test_an_unknown_section_comes_back_empty_rather_than_guessing(
            self, db, workspace):
        artifact = _versioned(db, workspace, _doc("1. Summary"))
        assert sect.detail(db, artifact.id, "nope-9", workspace.id) == {}


# ====================================================== Gate 5: THEN and NOW

@pytest.mark.usefixtures("db")
class TestThenIsFrozenAndNeverRewritten:

    def _bound(self, db, workspace, artifact, **kwargs):
        proposals = bind.from_export([contract.Metric(
            metric_id=kwargs.pop("metric_id", "application.cohort_bad_rate"),
            label=kwargs.pop("label", "Application cohort bad rate"),
            value=kwargs.pop("value", "5.86"),
            display_value=kwargs.pop("display_value", "5.86%"),
            unit=kwargs.pop("unit", "percent"), **kwargs)], module="cockpit")
        return bind.apply(db, workspace.id, proposals,
                          artifact_id=artifact.id)[0]

    def test_a_snapshot_records_what_the_version_relied_on(self, db,
                                                           workspace):
        artifact = _versioned(db, workspace, _doc("1. Summary"))
        self._bound(db, workspace, artifact, reporting_period="Q1 2026")
        [snapshot] = compare.freeze_current(db, workspace.id)
        assert snapshot.value == "5.86"
        assert snapshot.reporting_period == "Q1 2026"
        assert snapshot.version == 1

    def test_new_data_never_rewrites_the_snapshot(self, db, workspace):
        """The whole point. A snapshot that moves when today's data moves
        cannot answer "what did the committee see"."""
        artifact = _versioned(db, workspace, _doc("1. Summary"))
        binding = self._bound(db, workspace, artifact,
                              reporting_period="Q1 2026")
        compare.freeze_current(db, workspace.id)

        binding.value_in_document = "6.47"
        binding.raw_value = "6.47"
        binding.display_value = "6.47%"
        binding.reporting_period = "Q2 2026"
        db.flush()
        compare.freeze_current(db, workspace.id)

        # Scoped to this artifact. Counting the whole table only worked
        # while nothing in the product ever wrote a snapshot; the seeded
        # demonstration shares this database and now does.
        snapshots = (db.query(PlaybookMetricSnapshot)
                     .filter(PlaybookMetricSnapshot.artifact_id == artifact.id)
                     .all())
        assert len(snapshots) == 1
        assert snapshots[0].value == "5.86"

    def test_freezing_twice_writes_one_row(self, db, workspace):
        artifact = _versioned(db, workspace, _doc("1. Summary"))
        self._bound(db, workspace, artifact)
        compare.freeze_current(db, workspace.id)
        compare.freeze_current(db, workspace.id)
        assert (db.query(PlaybookMetricSnapshot)
                .filter(PlaybookMetricSnapshot.artifact_id == artifact.id)
                .count()) == 1

    def test_a_suggestion_is_never_frozen(self, db, workspace):
        """A suggestion is not something the document relied on — nobody
        confirmed it was that metric."""
        artifact = _versioned(db, workspace, _doc("1. Summary"))
        bind.apply(db, workspace.id, bind.from_labels(
            [("Gini", "0.415", "0.4152", "B2")], locator="xlsx://P!A1"),
            artifact_id=artifact.id)
        assert compare.freeze_current(db, workspace.id) == []

    def test_the_context_travels_with_the_snapshot(self, db, workspace):
        artifact = _versioned(db, workspace, _doc("1. Summary"))
        self._bound(db, workspace, artifact, population="retail",
                    segment="new", scenario="base", currency="SAR")
        [snapshot] = compare.freeze_current(db, workspace.id)
        assert (snapshot.population, snapshot.segment, snapshot.scenario,
                snapshot.currency) == ("retail", "new", "base", "SAR")


@pytest.mark.usefixtures("db")
class TestNowAndTheChange:

    def _setup(self, db, workspace, *, then: dict, now: dict | None = None):
        artifact = _versioned(db, workspace, _doc("1. Summary"))
        proposals = bind.from_export([contract.Metric(**then)],
                                     module="cockpit")
        binding = bind.apply(db, workspace.id, proposals,
                             artifact_id=artifact.id)[0]
        compare.freeze_current(db, workspace.id)
        if now is not None:
            for key, value in now.items():
                setattr(binding, {"value": "raw_value",
                                  "display_value": "display_value"}.get(
                                      key, key), value)
            if "value" in now:
                binding.value_in_document = now["value"]
            db.flush()
        return artifact, binding

    def test_a_percentage_moves_in_percentage_points(self, db, workspace):
        """§6D's own example: 5.86% to 6.47% is +0.61pp, not +0.61%."""
        self._setup(db, workspace,
                    then={"metric_id": "application.cohort_bad_rate",
                          "label": "Application cohort bad rate",
                          "value": "5.86", "display_value": "5.86%",
                          "unit": "percent", "reporting_period": "Q1 2026"},
                    now={"value": "6.47", "display_value": "6.47%",
                         "reporting_period": "Q2 2026"})
        [row] = compare.since_last_time(db, workspace.id)["rows"]
        assert row["then"]["display"] == "5.86%"
        assert row["now"]["display"] == "6.47%"
        assert row["change"] == "+0.61pp"
        assert row["change_unit"] == "pp"
        assert row["direction"] == compare.WORSE

    def test_a_falling_bad_metric_is_an_improvement(self, db, workspace):
        self._setup(db, workspace,
                    then={"metric_id": "retail.default_rate",
                          "label": "Retail default rate", "value": "7.46",
                          "display_value": "7.46%", "unit": "percent"},
                    now={"value": "6.88", "display_value": "6.88%"})
        [row] = compare.since_last_time(db, workspace.id)["rows"]
        assert row["change"] == "-0.58pp"
        assert row["direction"] == compare.IMPROVED

    def test_a_rising_statistic_is_an_improvement(self, db, workspace):
        self._setup(db, workspace,
                    then={"metric_id": "scorecard.gini", "label": "Gini",
                          "value": "0.391", "display_value": "0.391",
                          "unit": "statistic"},
                    now={"value": "0.415", "display_value": "0.415"})
        [row] = compare.since_last_time(db, workspace.id)["rows"]
        assert row["change"] == "+0.024"
        assert row["change_unit"] == ""
        assert row["direction"] == compare.IMPROVED

    def test_basis_points_move_in_basis_points(self, db, workspace):
        self._setup(db, workspace,
                    then={"metric_id": "spread", "label": "Spread",
                          "value": "120", "display_value": "120bps",
                          "unit": "basis_point"},
                    now={"value": "145", "display_value": "145bps"})
        [row] = compare.since_last_time(db, workspace.id)["rows"]
        assert row["change"] == "+25bps"

    def test_a_metric_with_no_stated_polarity_is_not_judged(self, db,
                                                            workspace):
        """Reporting the movement is honest. Calling it an improvement when
        nobody has said which way is good would not be."""
        self._setup(db, workspace,
                    then={"metric_id": "bespoke.overlay", "label": "Overlay",
                          "value": "1.20", "display_value": "1.20",
                          "unit": "ratio"},
                    now={"value": "1.40", "display_value": "1.40"})
        [row] = compare.since_last_time(db, workspace.id)["rows"]
        assert row["direction"] == compare.MOVED

    def test_an_unchanged_metric_says_so(self, db, workspace):
        self._setup(db, workspace,
                    then={"metric_id": "scorecard.gini", "label": "Gini",
                          "value": "0.415", "display_value": "0.415",
                          "unit": "statistic"})
        [row] = compare.since_last_time(db, workspace.id)["rows"]
        assert row["direction"] == compare.UNCHANGED

    def test_every_delta_keeps_its_lineage(self, db, workspace):
        self._setup(db, workspace,
                    then={"metric_id": "scorecard.gini", "label": "Gini",
                          "value": "0.391", "display_value": "0.391",
                          "unit": "statistic", "locator": "export://9#t.perf"},
                    now={"value": "0.415", "display_value": "0.415"})
        [row] = compare.since_last_time(db, workspace.id)["rows"]
        assert row["lineage"]["then"]["version"] == 1
        assert row["lineage"]["then"]["locator"] == "export://9#t.perf"
        assert row["lineage"]["now"]["source_module"] == "cockpit"
        assert row["lineage"]["now"]["binding_method"] == bind.FROM_EXPORT


@pytest.mark.usefixtures("db")
class TestItRefusesToMislead:

    def _frozen(self, db, workspace, **metric):
        artifact = _versioned(db, workspace, _doc("1. Summary"))
        binding = bind.apply(db, workspace.id, bind.from_export(
            [contract.Metric(**metric)], module="cockpit"),
            artifact_id=artifact.id)[0]
        compare.freeze_current(db, workspace.id)
        return binding

    @pytest.mark.parametrize("dimension,value", [
        ("population", "corporate"), ("segment", "used"),
        ("scenario", "downturn"), ("currency", "USD"), ("unit", "count")])
    def test_a_changed_context_is_not_comparable_and_names_the_dimension(
            self, db, workspace, dimension, value):
        binding = self._frozen(
            db, workspace, metric_id="retail.default_rate", label="DR",
            value="7.46", display_value="7.46%", unit="percent",
            population="retail", segment="new", scenario="base",
            currency="SAR")
        setattr(binding, dimension, value)
        binding.raw_value = "6.88"
        db.flush()

        [row] = compare.since_last_time(db, workspace.id)["rows"]
        assert row["comparable"] is False
        assert dimension in row["reason"]
        assert row["change"] == ""

    def test_a_suggestion_is_never_a_now(self, db, workspace):
        """The product rule at the comparison layer."""
        artifact = _versioned(db, workspace, _doc("1. Summary"))
        binding = bind.apply(db, workspace.id, bind.from_export(
            [contract.Metric(metric_id="scorecard.gini", label="Gini",
                             value="0.391", display_value="0.391",
                             unit="statistic")], module="validation"),
            artifact_id=artifact.id)[0]
        compare.freeze_current(db, workspace.id)

        # The link is downgraded to a suggestion; the value moves.
        binding.binding_method = bind.SUGGESTED
        binding.confirmed_by_user = False
        binding.raw_value = "0.415"
        db.flush()

        [row] = compare.since_last_time(db, workspace.id)["rows"]
        assert row["comparable"] is False
        assert "no current governed value" in row["reason"]
        assert row["now"]["value"] == ""

    def test_a_non_numeric_value_is_not_subtracted(self, db, workspace):
        binding = self._frozen(db, workspace, metric_id="x", label="X",
                               value="not available", display_value="n/a")
        binding.raw_value = "12"
        db.flush()
        [row] = compare.since_last_time(db, workspace.id)["rows"]
        assert row["comparable"] is False
        assert "not numeric" in row["reason"]

    def test_labels_alone_never_link_two_readings(self, db, workspace):
        """Two metrics sharing a label and differing in identity stay apart.
        The corporate reading must never become the retail NOW, however
        identical the words are — this is the mistake the whole binding model
        exists to stop."""
        artifact = _versioned(db, workspace, _doc("1. Summary"))
        retail = bind.apply(db, workspace.id, bind.from_export([
            contract.Metric(metric_id="retail.default_rate",
                            label="Default rate", value="7.46",
                            display_value="7.46%", unit="percent")],
            module="cockpit"), artifact_id=artifact.id)[0]
        compare.freeze_current(db, workspace.id)

        # A corporate series arrives under the identical label, and the
        # retail series is no longer governed.
        bind.apply(db, workspace.id, bind.from_export([
            contract.Metric(metric_id="corporate.default_rate",
                            label="Default rate", value="2.10",
                            display_value="2.10%", unit="percent")],
            module="cockpit"), artifact_id=artifact.id)
        retail.binding_method = bind.SUGGESTED
        retail.confirmed_by_user = False
        db.flush()

        [row] = compare.since_last_time(db, workspace.id)["rows"]
        assert row["metric_id"] == "retail.default_rate"
        assert row["comparable"] is False
        assert "no current governed value" in row["reason"]
        # And emphatically not the corporate figure.
        assert row["now"]["display"] != "2.10%"

    def test_nothing_frozen_yet_says_so_rather_than_showing_an_empty_table(
            self, db, workspace):
        _versioned(db, workspace, _doc("1. Summary"))
        result = compare.since_last_time(db, workspace.id)
        assert result["available"] is False
        assert "frozen" in result["reason"]


@pytest.mark.usefixtures("db")
class TestItReachesTheDashboard:

    def test_since_last_time_is_part_of_the_payload(self, db, workspace):
        artifact = _versioned(db, workspace, _doc("1. Summary"))
        binding = bind.apply(db, workspace.id, bind.from_export(
            [contract.Metric(metric_id="scorecard.gini", label="Gini",
                             value="0.391", display_value="0.391",
                             unit="statistic")], module="validation"),
            artifact_id=artifact.id)[0]
        compare.freeze_current(db, workspace.id)
        binding.raw_value = "0.415"
        binding.display_value = "0.415"
        db.flush()

        state = svc.dashboard(db, workspace.id).as_dict()
        assert state["since_last_time"]["available"] is True
        assert state["since_last_time"]["rows"][0]["change"] == "+0.024"
        assert state["since_last_time"]["improved"] == 1
