"""The seed script, run for real, and the cycle it is supposed to produce.

Slow and deliberate. Everything else in this suite tests one function; this
runs the whole seed against the real lake and then asks whether what came out
is something a person could actually be shown — which is the only question
that matters about a demonstration seed and the one a unit test cannot ask.

It runs `build()` directly rather than the command line, because the command
line is argument parsing over the same function and a subprocess would hide
the traceback when something fails.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import select

from tests.conftest import database_available

pytestmark = pytest.mark.skipif(
    not database_available(), reason="PostgreSQL not reachable")


@pytest.fixture(scope="module")
def built():
    """The three committees, built once and torn down afterwards.

    `--reset` semantics: whatever was there before this module ran is removed
    and rebuilt, and removed again at the end. The seed is idempotent, so a
    developer who had it seeded gets it back by running the script.
    """
    import scripts.seed_playbook_committees as seed
    from backend.db.engine import get_session
    from backend.playbook import demo

    report = seed.build(reset=True)
    if report.error:
        pytest.skip(f"the seed could not run here: {report.error}")
    if not report.built:
        pytest.skip("the seed built nothing: "
                    + "; ".join(report.notes))

    with get_session() as session:
        committees = {
            str(c.code): {
                "id": int(c.id), "name": str(c.name),
                "anchor": c.demo_anchor_date,
                "default_template_id": c.default_template_id,
            }
            for c in demo.seeded(session)}
    yield {"report": report, "committees": committees}

    with get_session() as session:
        for row in demo.seeded(session):
            session.delete(row)
        session.commit()


def _packs(committee_id: int):
    from backend.db.engine import get_session
    from backend.models.playbook import PlaybookPack

    with get_session() as session:
        return [
            {"id": int(p.id), "code": str(p.code), "status": str(p.status),
             "period": str(p.period),
             "comparison_period": str(p.comparison_period),
             "readiness_percent": int(p.readiness_percent),
             "readiness_state": str(p.readiness_state),
             "meeting_at": p.meeting_at, "demo_origin": str(p.demo_origin)}
            for p in session.execute(
                select(PlaybookPack)
                .where(PlaybookPack.committee_id == committee_id)
                .order_by(PlaybookPack.meeting_at)).scalars()]


# =============================================================== it is there


def test_all_three_committees_are_built(built):
    assert set(built["committees"]) == {c.code for c in _specs()}


def _specs():
    from backend.playbook import demo

    return demo.COMMITTEES


def test_each_has_a_previous_pack_and_a_current_one(built):
    """The point of the seed. One pack is a form; two is a cycle."""
    for code, committee in built["committees"].items():
        packs = _packs(committee["id"])
        assert len(packs) == 2, code
        assert packs[0]["meeting_at"] < packs[1]["meeting_at"], code


def test_each_committee_has_a_template_it_lays_packs_out_from(built):
    for code, committee in built["committees"].items():
        assert committee["default_template_id"] is not None, code


def test_every_pack_is_marked_as_seeded(built):
    """The marker is how the re-anchor knows what it may touch."""
    from backend.playbook import demo

    for committee in built["committees"].values():
        for pack in _packs(committee["id"]):
            assert pack["demo_origin"] == demo.PLAYBOOK_DEMO


def test_every_committee_carries_the_day_its_dates_are_relative_to(built):
    for code, committee in built["committees"].items():
        assert committee["anchor"] is not None, code


# ========================================================== it is calculated


def test_every_figure_on_every_pack_was_measured_against_the_real_lake(built):
    """Not one number is typed in.

    A snapshot carries the formula hash and the dataset version it was
    produced from, so a figure that had been written by hand would have
    neither — which is the check, rather than trusting the seed's own word.
    """
    from backend.db.engine import get_session
    from backend.models.playbook import PlaybookSnapshot

    with get_session() as session:
        for committee in built["committees"].values():
            for pack in _packs(committee["id"]):
                figures = list(session.execute(
                    select(PlaybookSnapshot)
                    .where(PlaybookSnapshot.pack_id == pack["id"])).scalars())
                assert figures, pack["code"]
                for figure in figures:
                    assert figure.formula_hash, (pack["code"],
                                                 figure.metric_id)
                    assert figure.run_id, (pack["code"], figure.metric_id)


def test_a_seeded_pack_reads_a_period_the_data_actually_has(built):
    """The failure this cost an hour to find.

    A period derived from `date.today()` asks the lake for a month it does not
    hold, and every figure comes back PERIOD_MISSING — the availability
    machinery working correctly and a demonstration of nothing. The periods
    come from the data, so the figures resolve.
    """
    from backend.db.engine import get_session
    from backend.models.playbook import PlaybookSnapshot

    with get_session() as session:
        for committee in built["committees"].values():
            for pack in _packs(committee["id"]):
                figures = list(session.execute(
                    select(PlaybookSnapshot)
                    .where(PlaybookSnapshot.pack_id == pack["id"])).scalars())
                missing = [f.metric_id for f in figures
                           if f.availability == "PERIOD_MISSING"]
                assert not missing, (pack["code"], pack["period"], missing)


def test_every_pack_compares_against_a_different_period(built):
    """"Since last time" needs a last time."""
    for committee in built["committees"].values():
        for pack in _packs(committee["id"]):
            assert pack["comparison_period"], pack["code"]
            assert pack["comparison_period"] != pack["period"], pack["code"]


def test_the_findings_are_whatever_the_thresholds_produced(built):
    """Not a list somebody wrote to look interesting.

    Every finding carries the rule key that raised it and the numbers it fired
    on, which a hand-written one would not.
    """
    from backend.db.engine import get_session
    from backend.models.playbook import PlaybookFinding

    with get_session() as session:
        raised = 0
        for committee in built["committees"].values():
            for pack in _packs(committee["id"]):
                for finding in session.execute(
                        select(PlaybookFinding).where(
                            PlaybookFinding.pack_id == pack["id"])).scalars():
                    raised += 1
                    assert finding.rule_key, finding.title
                    assert finding.factual_basis, finding.title
                    assert finding.fingerprint, finding.title
        assert raised, ("the declared thresholds produced nothing at all, "
                        "which means the demonstration has no finding to open")


# ============================================================== it is a cycle


def test_the_committees_are_not_all_at_the_same_point(built):
    """Three copies of one state demonstrates one screen.

    The argument is the lifecycle, so the three of them together have to show
    more than one part of it.
    """
    states = set()
    for committee in built["committees"].values():
        for pack in _packs(committee["id"]):
            states.add(pack["status"])
    assert len(states) >= 2, states


def test_at_least_one_pack_is_signed_off_and_read_only(built):
    """The end of the lifecycle, which is where the governance argument is.

    An approved pack cannot be edited — the only way to change it is an
    amendment that supersedes it — and a demonstration with nothing in that
    state cannot make the point.
    """
    signed = [pack for committee in built["committees"].values()
              for pack in _packs(committee["id"])
              if pack["status"] in ("APPROVED", "PUBLISHED")]
    assert signed, "no seeded pack reached approval"


def test_at_least_one_pack_is_still_open_with_something_outstanding(built):
    """And the beginning, which is where the work is.

    A demonstration where everything is finished has nothing for anybody to
    do, and the chase list has nothing true to say.
    """
    from backend.db.engine import get_session
    from backend.models.playbook import PlaybookFinding

    with get_session() as session:
        open_findings = 0
        for committee in built["committees"].values():
            for pack in _packs(committee["id"]):
                if pack["status"] in ("APPROVED", "PUBLISHED"):
                    continue
                open_findings += len(list(session.execute(
                    select(PlaybookFinding).where(
                        PlaybookFinding.pack_id == pack["id"],
                        PlaybookFinding.status == "OPEN")).scalars()))
        assert open_findings, (
            "every seeded finding is answered, so there is nothing for a "
            "reader to open and answer")


def test_a_signed_off_pack_answered_its_own_findings(built):
    """Readiness will not let a pack reach approval with a serious finding
    nobody has answered, and that gate is the product working. A seeded
    APPROVED pack that had unanswered findings would mean the gate was
    bypassed."""
    from backend.db.engine import get_session
    from backend.models.playbook import PlaybookFinding
    from backend.playbook import findings as find

    with get_session() as session:
        for committee in built["committees"].values():
            for pack in _packs(committee["id"]):
                if pack["status"] not in ("APPROVED", "PUBLISHED"):
                    continue
                for finding in session.execute(
                        select(PlaybookFinding).where(
                            PlaybookFinding.pack_id == pack["id"])).scalars():
                    assert str(finding.status) in find.ANSWERED, (
                        pack["code"], finding.title, finding.status)


def test_the_cycle_reaches_decisions_and_actions(built):
    """DECISIONS → ACTIONS is the half of the lifecycle that follows the
    meeting, and a pack with neither stops at the interesting part."""
    from backend.db.engine import get_session
    from backend.models.playbook import PlaybookAction, PlaybookDecision

    with get_session() as session:
        decisions = actions = 0
        for committee in built["committees"].values():
            for pack in _packs(committee["id"]):
                decisions += len(list(session.execute(
                    select(PlaybookDecision).where(
                        PlaybookDecision.pack_id == pack["id"])).scalars()))
                actions += len(list(session.execute(
                    select(PlaybookAction).where(
                        PlaybookAction.pack_id == pack["id"])).scalars()))
        assert decisions, "no committee is being asked to decide anything"
        assert actions, "nothing follows from what was decided"


def test_a_decided_decision_has_a_name_and_a_date_against_it(built):
    from backend.db.engine import get_session
    from backend.models.playbook import PlaybookDecision

    with get_session() as session:
        decided = list(session.execute(
            select(PlaybookDecision).where(
                PlaybookDecision.status == "APPROVED")).scalars())
        assert decided, "nothing was decided on any seeded pack"
        for decision in decided:
            assert decision.decided_by is not None, decision.reference
            assert decision.decided_at is not None, decision.reference
            assert str(decision.decision_text).strip(), decision.reference


# =============================================================== it is safe


def test_running_it_again_changes_nothing(built):
    """Idempotent, which is what makes it safe in a start-up script."""
    import scripts.seed_playbook_committees as seed

    again = seed.build()
    assert again.built == [], again.built
    assert sorted(again.present) == sorted(built["committees"]), again.present


def test_the_reset_refuses_where_it_might_be_real(monkeypatch):
    """--reset removes committees and the packs on them.

    Two ways to be sure this is not production, and neither can be acquired
    by forgetting to set something.
    """
    import backend.config as config
    import scripts.seed_playbook_committees as seed
    from backend.demo import mode

    # `settings` is a frozen dataclass — deliberately, so nothing mutates the
    # deployment's configuration at runtime. Stood in for rather than edited,
    # which is also closer to what actually differs in production.
    monkeypatch.setattr(mode, "enabled", lambda: False)
    monkeypatch.setattr(
        config, "settings",
        SimpleNamespace(**{**vars(config.settings), "env": "production"}),
        raising=False)

    allowed, why = seed._may_reset()
    assert allowed is False
    assert "refuses to run anywhere that might be real" in why

    report = seed.build(reset=True)
    assert report.error
    assert report.built == []
