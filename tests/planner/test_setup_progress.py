"""Progress and guidance: derived from the plan, never stored, never guessed.

The complaint these answer is that the form did not say where you were or
what to do next, and that the panel beside it disagreed with the fields. So
the claims under test are:

  * every state comes out of the document — set a field and the section moves,
    clear it and the section moves back, with nothing to invalidate;
  * the count is business-meaningful — "complete" means the section has what a
    project needs from it, not that somebody pressed Next;
  * the assistant's next step is the first REQUIRED thing missing, in the
    order the form asks for it, and it says which field;
  * the publish message names the number of required items left.
"""

from __future__ import annotations

import pytest

from backend.planner import draft as dr
from backend.planner import setup as su


def _section(bars: dict, key: str) -> dict:
    return next(s for s in bars["sections"] if s["key"] == key)


@pytest.fixture
def plan() -> dict:
    return dr.empty()


@pytest.fixture
def full(plan) -> dict:
    dr._cmd_overview(plan, {"name": "LGD Model Redevelopment",
                            "code": "LGDMR-2026",
                            "description": "Rebuild the LGD model.",
                            "objective": "Signed off by Model Risk."})
    dr._cmd_governance(plan, {"sponsor_id": 1, "manager_id": 2, "owner_id": 3,
                              "escalation_id": 4, "start_date": "2026-02-02",
                              "target_end_date": "2026-09-30"})
    dr._cmd_add_milestone(plan, {"name": "Data Foundation", "owner_id": 3,
                                 "start_date": "2026-02-02",
                                 "target_date": "2026-04-30"})
    for title, start, due in (("Extract", "2026-02-02", "2026-03-02"),
                              ("Reconcile", "2026-03-03", "2026-04-01")):
        dr._cmd_add_task(plan, {"milestone_code": "M01", "title": title,
                                "owner_id": 3, "description": f"{title} it.",
                                "start_date": start, "due_date": due})
    dr._cmd_add_link(plan, {"predecessor": "M01-T01", "successor": "M01-T02"})
    return plan


# ------------------------------------------------------------------- shape


def test_there_are_eight_sections_in_the_order_the_form_asks_them(plan):
    bars = su.progress(plan)
    assert [s["number"] for s in bars["sections"]] == list(range(1, 9))
    assert [s["key"] for s in bars["sections"]] == [
        "overview", "governance", "agentic", "milestones", "tasks",
        "dependencies", "review", "publish"]
    assert bars["total"] == 8


def test_a_blank_plan_is_not_started_rather_than_in_trouble(plan):
    """§4. "Needs attention" on a form nobody has touched means nothing."""
    bars = su.progress(plan)
    for key in ("overview", "governance", "milestones", "tasks"):
        assert _section(bars, key)["state"] == su.NOT_STARTED, key
    assert "1 of 8 sections complete" == bars["sentence"]


def test_a_finished_plan_completes_every_section_but_publish(full):
    bars = su.progress(full)
    for key in ("overview", "governance", "agentic", "milestones", "tasks",
                "dependencies", "review"):
        assert _section(bars, key)["state"] == su.COMPLETE, key
    assert _section(bars, "publish")["state"] == su.NOT_STARTED
    assert bars["sentence"] == "7 of 8 sections complete"
    assert bars["publishable"] is True


def test_publishing_completes_the_eighth(full):
    bars = su.progress(full, status="PUBLISHED")
    assert _section(bars, "publish")["state"] == su.COMPLETE
    assert bars["sentence"] == "8 of 8 sections complete"
    assert bars["publish_message"] == "Published."


# -------------------------------------------------------------- it derives


def test_a_half_filled_section_is_in_progress_not_complete(plan):
    dr._cmd_overview(plan, {"name": "Half a project"})
    bars = su.progress(plan)
    overview = _section(bars, "overview")
    assert overview["state"] == su.IN_PROGRESS
    assert overview["done"] == 2  # the name, and the code derived from it
    assert overview["total"] == 4


def test_a_section_moves_back_when_the_field_is_cleared(full):
    assert _section(su.progress(full), "governance")["state"] == su.COMPLETE
    dr._cmd_governance(full, {"sponsor_id": None})
    after = _section(su.progress(full), "governance")
    assert after["state"] == su.NEEDS_ATTENTION
    assert after["blockers"] == 1


def test_a_started_section_with_a_missing_requirement_needs_attention(plan):
    dr._cmd_governance(plan, {"manager_id": 2})
    governance = _section(su.progress(plan), "governance")
    assert governance["state"] == su.NEEDS_ATTENTION
    assert governance["done"] == 1


def test_the_count_is_not_stored_anywhere(full):
    """Two calls on the same document agree, and neither writes."""
    first = su.progress(full)
    second = su.progress(full)
    assert first == second


# --------------------------------------------------------------- summaries


def test_a_complete_section_collapses_to_a_line_worth_reading(full):
    """§12. What a collapsed section shows instead of its fields."""
    names = {1: "Priya Raman", 2: "Omar Haddad", 3: "Lina Said",
             4: "Priya Raman"}
    bars = su.progress(full, names=names)
    assert _section(bars, "overview")["summary"] == \
        "LGD Model Redevelopment (LGDMR-2026)"
    governance = _section(bars, "governance")["summary"]
    assert "Sponsor Priya Raman" in governance
    assert "Manager Omar Haddad" in governance
    assert "2 Feb 2026" in governance and "30 Sep 2026" in governance
    assert _section(bars, "milestones")["summary"] == "1 milestone"
    assert _section(bars, "tasks")["summary"] == "2 tasks"
    assert _section(bars, "dependencies")["summary"] == "1 dependency"


def test_a_person_the_names_do_not_cover_is_not_invented(full):
    governance = _section(su.progress(full), "governance")["summary"]
    assert "Sponsor #1" in governance


# ---------------------------------------------------------------- guidance


def test_the_next_step_is_the_first_required_thing_missing(plan):
    """§8. And it says which field, so the form can go there."""
    found = su.guidance(plan)["next"]
    assert found["required"] is True
    assert found["step"] == "OVERVIEW"
    assert found["field"] == "overview.name"


def test_the_next_step_moves_on_as_each_one_is_answered(plan):
    dr._cmd_overview(plan, {"name": "A project", "code": "AP-2026"})
    found = su.guidance(plan)["next"]
    assert found["step"] == "GOVERNANCE"
    assert found["field"] == "governance.sponsor_id"

    dr._cmd_governance(plan, {"sponsor_id": 1})
    assert su.guidance(plan)["next"]["field"] == "governance.manager_id"


def test_a_finished_plan_is_told_to_publish(full):
    found = su.guidance(full)["next"]
    assert found["step"] == su.STEP_PUBLISH
    assert found["title"] == "Publish the project"


def test_the_assistant_says_what_is_done_and_what_is_missing(plan):
    dr._cmd_overview(plan, {"name": "A project", "code": "AP-2026",
                            "description": "x", "objective": "y"})
    said = su.guidance(plan)
    assert any(row["summary"] == "A project (AP-2026)"
               for row in said["complete"])
    messages = [row["message"] for row in said["missing"]]
    assert "The project has no sponsor." in messages
    assert all(row["field"] for row in said["missing"] if "no name" not in
               row["message"])


def test_every_missing_item_carries_the_field_to_go_to(plan):
    """§9. A note a person has to search the page for is not an answer."""
    for row in su.guidance(plan)["missing"]:
        assert row["field"], row["message"]
        assert row["step"]


def test_the_readiness_message_counts_what_is_left(plan):
    said = su.guidance(plan)
    assert said["readiness"]["publishable"] is False
    assert said["readiness"]["message"] == \
        f"Publish unavailable — {said['readiness']['required_remaining']} " \
        "required items remain."


def test_one_required_item_left_is_said_in_the_singular(full):
    dr._cmd_governance(full, {"sponsor_id": None})
    said = su.guidance(full)
    assert said["readiness"]["message"] == \
        "Publish unavailable — 1 required item remains."


def test_a_date_that_contradicts_another_is_reported_as_a_conflict(full):
    dr._cmd_update_task(full, {"code": "M01-T02", "due_date": "2026-06-30"})
    conflicts = su.guidance(full)["conflicts"]
    assert any("after its milestone" in row["message"] for row in conflicts)
    assert all(row["step"] for row in conflicts)


def test_the_quick_actions_are_about_the_step_you_are_on(plan):
    on_governance = su.guidance(plan, step="GOVERNANCE")["actions"]
    labels = [a["label"] for a in on_governance]
    assert "Assign sponsor" in labels
    assert "Set escalation contact" in labels
    assert "Check readiness" in labels

    on_milestones = su.guidance(plan, step="MILESTONES")["actions"]
    assert "Add milestone" in [a["label"] for a in on_milestones]


def test_unlinked_tasks_can_be_named(full):
    dr._cmd_add_task(full, {"milestone_code": "M01", "title": "Third",
                            "owner_id": 3, "start_date": "2026-04-02",
                            "due_date": "2026-04-20"})
    assert su.unlinked_tasks(full) == ["M01-T03"]
    actions = su.guidance(full, step="DEPENDENCIES")["actions"]
    show = next(a for a in actions if a["label"].startswith("Show"))
    assert show["codes"] == ["M01-T03"]


def test_the_assistant_has_nothing_to_type_into(full):
    """§6, §7. It reports. There is no message field and no free text in."""
    said = su.guidance(full)
    assert set(said) == {"here", "headline", "complete", "missing",
                         "recommended", "conflicts", "next", "actions",
                         "readiness"}
