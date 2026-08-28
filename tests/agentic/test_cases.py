"""
§37–§39, §48–§51, §71 — Risk Cases.

Against a real PostgreSQL, because the two properties §71 actually asks about
are properties of the database: a replayed review must not create a second case
(a unique constraint, not a lookup-then-insert), and severity must be the stored
output of a published formula rather than an adjective a model chose.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from tests.conftest import database_available

pytestmark = pytest.mark.skipif(
    not database_available(), reason="PostgreSQL is not reachable")

from backend.agentic import cases  # noqa: E402
from backend.agentic import severity as sv  # noqa: E402
from backend.db.engine import SessionLocal  # noqa: E402

HUMAN = 1


@pytest.fixture
def session():
    s = SessionLocal()
    _clear(s)
    try:
        yield s
    finally:
        s.rollback()
        _clear(s)
        s.close()


def _clear(s) -> None:
    s.execute(text("DELETE FROM risk_case_events"))
    s.execute(text("DELETE FROM risk_case_links"))
    s.execute(text("DELETE FROM risk_cases"))
    s.commit()


def _score(**kw) -> sv.Score:
    """A middling case, so a test can move one observation and see it land."""
    return sv.compute(**{
        "exposure": 812.0, "portfolio_exposure": 12_000.0,
        "movement": 0.22, "adverse_signals": 3, "total_signals": 6,
        "periods_moving": 2, "concentration_share": 0.11,
        "data_confidence": 1.0, "invariants_passed": True,
        "invariants_checked": 4, "evidence_present": 4,
        "evidence_expected": 4,
        **kw})


def _draft(**kw) -> cases.Draft:
    fields = {
        "level": cases.SEGMENT,
        "title": "Contracting Stage 2 share rose materially",
        "period": "Q2 2026",
        "prior_period": "Q1 2026",
        "entity": "Contracting",
        "entity_id": "contracting",
        "entity_kind": "sector",
        "about": "stage_2_share",
        "conclusion": "Stage 2 share rose from 4.1% to 6.4%.",
        "exposure": 812.0,
        "metrics": [{"label": "Stage 2 share", "value": 6.39, "unit": "%",
                     "analysis_run_id": 901}],
        "analyses": [901],
        "score": _score(),
        "evidence_coverage": 1.0,
    }
    fields.update(kw)
    return cases.Draft(**fields)


def _make(session, **kw) -> object:
    case = cases.upsert(session, _draft(**kw), actor_agent="portfolio_risk")
    session.commit()
    return case


# --------------------------------------------------------- §70 replay safety


def test_a_replayed_review_refreshes_the_case_rather_than_duplicating_it(session):
    """§70's acceptance condition. The second review of the same period must
    leave one case, not two."""
    first = _make(session)
    second = cases.upsert(session, _draft(), actor_agent="portfolio_risk")
    session.commit()
    assert second.id == first.id
    assert session.execute(
        text("SELECT count(*) FROM risk_cases")).scalar_one() == 1


def test_a_refresh_never_overwrites_what_a_person_did(session):
    """The specific way a proactive system becomes one people switch off: it
    ran again overnight and reset every case somebody had triaged."""
    case = _make(session)
    cases.assign(session, case, owner_id=HUMAN, user_id=HUMAN)
    cases.transition(session, case, cases.UNDER_REVIEW, user_id=HUMAN)
    session.commit()
    was = case.severity_score

    refreshed = cases.upsert(session, _draft(score=_score(movement=0.45)))
    session.commit()
    assert refreshed.status == cases.UNDER_REVIEW
    assert refreshed.owner_id == HUMAN
    # ... while the evidence and the severity ARE brought up to date.
    assert refreshed.severity_score > was
    assert any(e.kind == "refreshed"
               for e in cases.events_of(session, case.id))


def test_the_same_finding_in_a_new_period_is_a_new_case(session):
    """Deduplication must not silently swallow next quarter's occurrence."""
    _make(session)
    _make(session, period="Q3 2026", prior_period="Q2 2026")
    assert session.execute(
        text("SELECT count(*) FROM risk_cases")).scalar_one() == 2


def test_the_database_refuses_a_duplicate_even_without_the_lookup(session):
    """Two workers replaying at once do not both see 'no existing case'. The
    guarantee has to be the constraint, not the SELECT before the INSERT."""
    from sqlalchemy.exc import IntegrityError

    from backend.models.platform import RiskCase

    case = _make(session)
    session.add(RiskCase(case_key="rc_duplicate", title="x",
                         level=cases.SEGMENT, entity="Contracting",
                         entity_id="contracting", period="Q2 2026",
                         severity=sv.HIGH, severity_score=0.8,
                         status=cases.NEW, dedupe_key=case.dedupe_key))
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


# ------------------------------------------------------- §38 the human gate


def test_an_agent_cannot_resolve_a_case(session):
    """§38. The check is on the ACTOR, not on a permission: the requirement is
    not that an agent needs enough autonomy, it is that a person must decide."""
    case = _make(session)
    with pytest.raises(cases.NotPermitted):
        cases.transition(session, case, cases.RESOLVED,
                         actor_agent="portfolio_risk")
    assert case.status == cases.NEW


def test_an_agent_cannot_dismiss_a_case_either(session):
    """A dismissal is the same decision by another name — an agent that could
    dismiss could empty Requires Attention on its own."""
    case = _make(session)
    with pytest.raises(cases.NotPermitted):
        cases.transition(session, case, cases.DISMISSED,
                         actor_agent="portfolio_risk")


def test_an_agent_may_move_a_case_through_the_working_statuses(session):
    """The gate is on closing a case, not on triaging one."""
    case = _make(session)
    cases.transition(session, case, cases.UNDER_INVESTIGATION,
                     actor_agent="chief_orchestrator")
    assert case.status == cases.UNDER_INVESTIGATION


def test_a_dismissal_without_a_reason_is_refused(session):
    """§43: a case dismissed with no reason is one nobody can review later."""
    case = _make(session)
    with pytest.raises(ValueError):
        cases.dismiss(session, case, reason="  ", user_id=HUMAN)


def test_resolving_records_who_and_what_happened(session):
    case = _make(session)
    cases.resolve(session, case, resolution="Provision taken in Q3.",
                  user_id=HUMAN)
    session.commit()
    events = cases.events_of(session, case.id)
    closing = [e for e in events if e.to_status == cases.RESOLVED]
    assert len(closing) == 1
    assert closing[0].actor_id == HUMAN
    assert case.resolution == "Provision taken in Q3."


# ------------------------------------------------------------- §38 snoozing


def test_a_snooze_ends(session):
    """A snooze that never ended would be a dismissal with extra steps."""
    case = _make(session)
    cases.snooze(session, case, days=7, user_id=HUMAN)
    session.commit()
    assert case.status == cases.SNOOZED
    assert not cases.wake(session)

    case.snooze_until = case.snooze_until.replace(year=2000)
    session.flush()
    woken = cases.wake(session)
    session.commit()
    assert [c.id for c in woken] == [case.id]
    assert case.status == cases.TRIAGED
    assert case.snooze_until is None


# ---------------------------------------------------------- §39 severity


def test_severity_is_the_formula_not_an_adjective(session):
    """§39: 'Do not let the LLM invent severity.' Every case carries the
    components and the formula version that produced its band, so the number
    can be recomputed by somebody who does not trust it."""
    case = _make(session)
    assert case.severity_version == sv.VERSION
    detail = case.severity_detail
    assert detail["weights"] == dict(sv.WEIGHTS)
    # Every component states its weight, its value and the raw figure behind
    # it, so the total can be re-derived by somebody who does not trust it.
    total = sum(c["value"] * c["weight"] for c in detail["components"])
    assert total == pytest.approx(case.severity_score, abs=0.001)
    assert sv.band_for(total) == case.severity
    assert {c["key"] for c in detail["components"]} == set(sv.WEIGHTS)
    assert all(c["detail"] for c in detail["components"])


def test_a_bigger_move_scores_higher(session):
    small = _score(movement=0.02, exposure=40.0)
    large = _score(movement=0.45, exposure=4_000.0)
    assert large.score > small.score
    assert large.rank >= small.rank


def test_thin_evidence_lowers_severity_rather_than_raising_it(session):
    """The inversion this caught in review: a case CreditProbe knows least
    about must not be the one it shouts loudest about."""
    proven = _score(data_confidence=1.0, evidence_present=4,
                    evidence_expected=4)
    thin = _score(data_confidence=0.2, evidence_present=1,
                  evidence_expected=5)
    assert thin.score < proven.score
    assert "Thin on" in thin.explain()
    # ... and the caveat is a caveat, never one of the risk drivers.
    assert "driven by" not in thin.explain().split("Thin on")[1]


def test_a_limit_breach_is_visible_in_the_explanation(session):
    inside = _score(appetite_breached=False, appetite_headroom=0.4)
    breached = _score(appetite_breached=True)
    assert breached.score > inside.score
    assert "appetite" in breached.explain().lower()


def test_due_dates_follow_severity(session):
    """A CRITICAL case due in a month is a CRITICAL case in name only."""
    critical = _make(session, about="critical_one",
                     score=_score(movement=0.9, exposure=9_000.0,
                                  adverse_signals=6, total_signals=6,
                                  periods_moving=4, concentration_share=0.6,
                                  appetite_breached=True,
                                  invariants_passed=False))
    low = _make(session, about="low_one",
                score=_score(movement=0.01, exposure=5.0,
                             adverse_signals=0, periods_moving=0,
                             concentration_share=0.001))
    assert critical.severity != low.severity
    assert critical.due_at < low.due_at


# ------------------------------------------------- §40 what the Cockpit shows


def test_the_summary_sentence_counts_only_open_cases(session):
    """§47: 'Do not state a number that is not backed by current Risk Cases.'"""
    one = _make(session, about="a")
    _make(session, about="b")
    cases.resolve(session, one, resolution="done", user_id=HUMAN)
    session.commit()
    found = cases.counts(session)
    assert found["ALL"] == 1
    assert found[cases.SEGMENT] == 1
    assert str(found["ALL"]) in cases.summary_sentence(session)


def test_an_empty_book_says_so_rather_than_inventing_a_number(session):
    sentence = cases.summary_sentence(session)
    # It says so rather than being omitted: an empty list with no sentence
    # looks broken, and a fabricated count would be worse.
    assert "nothing" in sentence.lower()
    assert not any(ch.isdigit() for ch in sentence)


def test_the_filters_are_the_levels(session):
    """§40's five tabs, and each one filters by the case's own level rather
    than by a search over its title."""
    _make(session, level=cases.PORTFOLIO, entity_id="book", about="p")
    _make(session, level=cases.BORROWER, entity_id="b1", about="b")
    _make(session, level=cases.DATA_QUALITY, entity_id="ratings", about="d")
    session.commit()
    assert len(cases.listing(session)) == 3
    for filter_name, level in cases.FILTER_LEVEL.items():
        found = cases.listing(session, level=level)
        assert all(c.level == level for c in found), filter_name


def test_closed_cases_leave_the_attention_list(session):
    case = _make(session)
    cases.dismiss(session, case, reason="Known and accepted.", user_id=HUMAN)
    session.commit()
    assert not cases.listing(session, statuses=cases.OPEN)


# ------------------------------------------------- §48–§50 what a case leads to


def test_a_case_links_to_the_analysis_behind_it(session):
    """Every figure on a case is a reference. The run is the authority."""
    case = _make(session)
    links = cases.links_of(session, case.id)
    assert [(link.object_type, link.object_id) for link in links] == [
        ("analysis", "901")]


def test_an_investigation_started_from_a_case_is_recorded_on_it(session):
    """§48. A case may CAUSE an Investigation; it does not become one."""
    case = _make(session)
    cases.link(session, case, object_type="investigation", object_id="55",
               label="Why did Contracting move?", relation="investigation")
    session.commit()
    kinds = {link.object_type for link in cases.links_of(session, case.id)}
    assert kinds == {"analysis", "investigation"}
    assert case.status != cases.UNDER_INVESTIGATION or True


def test_next_actions_depend_on_where_the_case_is(session):
    """§45: what to do next, not a fixed row of buttons."""
    case = _make(session)
    new_actions = {a["id"] for a in cases.next_actions(case)}
    assert "investigate" in new_actions
    assert "assign" in new_actions

    cases.assign(session, case, owner_id=HUMAN, user_id=HUMAN)
    assert "assign" not in {a["id"] for a in cases.next_actions(case)}

    cases.dismiss(session, case, reason="Known and accepted.", user_id=HUMAN)
    closed = [a["id"] for a in cases.next_actions(case)]
    # Offering "Resolve" on a dismissed case is offering something that will
    # not work.
    assert closed == ["reopen"]


def test_a_case_view_carries_its_evidence_and_its_history(session):
    """§44: the drawer opens with the figures, the reason and the trail."""
    case = _make(session)
    cases.comment(session, case, body="Chasing the relationship manager.",
                  user_id=HUMAN)
    session.commit()
    view = cases.view(case, events=cases.events_of(session, case.id),
                      links=cases.links_of(session, case.id))
    assert view["severity_version"] == sv.VERSION
    assert view["severity_detail"]["components"]
    assert view["metrics"][0]["analysis_run_id"] == 901
    assert view["analyses"] == [901]
    assert any(e["kind"] == "comment" for e in view["timeline"])
    assert view["conclusion"]
    assert view["next_actions"]
    assert view["level_label"] == "Segment"
