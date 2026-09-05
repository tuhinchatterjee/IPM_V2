"""What the assistant may know, and what it must not be able to do.

The spec is explicit that testing an AI layer by checking that it returned
some text is worthless. So nothing here asserts that a brief is non-empty.
These tests assert three things instead:

  1. every claim the brief makes is traceable to something in the database,
     and is labelled FACT, INFERENCE or RECOMMENDATION accordingly;
  2. where the record does not say why something is late, the brief says the
     reason has not been recorded rather than inventing one;
  3. no registered tool can change a commitment, and the read tools cannot
     see a project the caller is not on.

The third is the load-bearing one. An agent that can be talked into marking a
task complete makes every status report in the product unreliable.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest

from backend.agentic import tools as reg
from backend.planner import agent as ai
from tests.planner.conftest import PREFIX, headers

TODAY = date(2026, 6, 15)


@pytest.fixture(scope="module")
def rich(client, cast):
    """A project with something to say about it: overdue, blocked without a
    reason, a decision outstanding and a high risk open."""
    tag = uuid.uuid4().hex[:6].upper()
    made = client.post(
        f"{PREFIX}/projects", headers=headers(cast["alice"]),
        json={"code": f"AI-{tag}", "name": "Model redevelopment",
              "status": "ACTIVE", "manager_id": cast["alice"],
              "start_date": "2026-01-05", "target_end_date": "2026-12-18"})
    assert made.status_code == 201, made.text
    pid = made.json()["project"]["id"]
    client.post(f"{PREFIX}/projects/{pid}/participants",
                headers=headers(cast["alice"]),
                json={"user_id": cast["bob"], "project_role": "CONTRIBUTOR",
                      "access": "CONTRIBUTOR"})

    yesterday = date.today() - timedelta(days=6)
    client.post(f"{PREFIX}/projects/{pid}/tasks",
                headers=headers(cast["alice"]),
                json={"code": "T-LATE", "title": "Data extract",
                      "owner_id": cast["bob"],
                      "start_date": str(yesterday - timedelta(days=20)),
                      "due_date": str(yesterday)})
    client.post(f"{PREFIX}/projects/{pid}/tasks",
                headers=headers(cast["alice"]),
                json={"code": "T-STUCK", "title": "Vendor sign-off",
                      "owner_id": cast["bob"], "blocked": True,
                      "blocker_reason": "Waiting on the vendor's legal team",
                      "due_date": str(date.today() + timedelta(days=20))})
    client.post(f"{PREFIX}/projects/{pid}/raid",
                headers=headers(cast["alice"]),
                json={"raid_type": "DECISION",
                      "title": "Which PD model version to rebuild on",
                      "severity": "HIGH"})
    client.post(f"{PREFIX}/projects/{pid}/raid",
                headers=headers(cast["alice"]),
                json={"raid_type": "RISK",
                      "title": "Key modeller leaving in September",
                      "severity": "HIGH"})
    return {"id": pid, "code": made.json()["project"]["code"]}


class TestTheRegistry:
    def test_the_planner_tools_are_registered(self):
        ids = {t.tool_id for t in reg.TOOLS}
        assert {reg.PLANNER_PORTFOLIO, reg.PLANNER_PROJECT,
                reg.PLANNER_MY_WORK, reg.PLANNER_ATTENTION,
                reg.PLANNER_CHANGES, reg.PLANNER_TASKS,
                reg.PLANNER_CHASE_LIST} <= ids

    def test_every_read_tool_carries_the_principal(self):
        """`reads_data` is what makes `invoke` pass the principal through.

        A planner read tool without it would run without a caller, which is
        an agent seeing every project in the bank.
        """
        planner = [t for t in reg.TOOLS if t.tool_id.startswith("planner_")]
        readers = [t for t in planner if not t.writes]
        assert readers
        assert all(t.reads_data for t in readers), \
            [t.tool_id for t in readers if not t.reads_data]

    def test_there_is_no_tool_that_changes_a_commitment(self):
        """The prohibition is the absence of the capability, not a check.

        A permission check can be written wrongly. A tool that does not exist
        cannot be called however the model is prompted.
        """
        forbidden = ("complete_task", "change_task_owner", "move_due_date",
                     "cancel_task", "close_risk", "set_project_health")
        ids = {t.tool_id for t in reg.TOOLS}
        assert not (set(forbidden) & ids)
        assert set(forbidden) <= set(reg.NO_TOOL_EXISTS)

    def test_the_one_writer_only_drafts(self):
        drafter = reg.require(reg.PLANNER_DRAFT_UPDATE)
        assert drafter.writes
        assert "draft" in drafter.purpose.lower()
        assert "does not send" in drafter.purpose.lower()

    def test_an_unregistered_planner_tool_is_refused(self):
        class Agent:
            agent_id = "test"
            business_name = "Test agent"

            def may_use(self, _tool):
                return True

        call = reg.check(Agent(), "planner_complete_task", {"task": 1})
        assert not call.allowed
        assert "not a registered" in call.reason


class TestGrounding:
    def test_every_statement_is_labelled(self, client, cast, rich):
        got = client.get(f"{PREFIX}/projects/{rich['id']}/brief",
                         headers=headers(cast["alice"]))
        assert got.status_code == 200, got.text
        kinds = {s["kind"] for s in got.json()["statements"]}
        assert kinds <= {ai.FACT, ai.INFERENCE, ai.RECOMMENDATION, ai.UNKNOWN}
        assert ai.FACT in kinds

    def test_facts_carry_the_codes_they_are_about(self, client, cast, rich):
        """A FACT with no evidence is an assertion.

        Every one that names a task must say which, so a reader can open it.
        """
        body = client.get(f"{PREFIX}/projects/{rich['id']}/brief",
                          headers=headers(cast["alice"])).json()
        about_tasks = [s for s in body["statements"]
                       if s["kind"] == ai.FACT
                       and ("overdue" in s["text"] or "blocked" in s["text"])]
        assert about_tasks
        assert all(s["evidence"] for s in about_tasks)

    def test_the_numbers_match_the_project(self, client, cast, rich):
        """The brief and the detail page must not disagree.

        Two screens quoting different completion percentages for the same
        project is the fastest way to lose a user's trust in both.
        """
        brief = client.get(f"{PREFIX}/projects/{rich['id']}/brief",
                           headers=headers(cast["alice"])).json()
        detail = client.get(f"{PREFIX}/projects/{rich['id']}",
                            headers=headers(cast["alice"])).json()
        percent = detail["project"]["percent_complete"]
        assert f"{percent}% complete" in " ".join(
            s["text"] for s in brief["statements"])
        assert detail["project"]["health"] in brief["headline"]

    def test_it_reports_a_recorded_blocker_verbatim(self, client, cast, rich):
        body = client.get(f"{PREFIX}/projects/{rich['id']}/brief",
                          headers=headers(cast["alice"])).json()
        text = " ".join(s["text"] for s in body["statements"])
        assert "Waiting on the vendor's legal team" in text

    def test_it_says_so_when_no_reason_was_recorded(self, client, cast, rich):
        """The honest answer to "why is it late?" is usually "nobody said"."""
        made = client.post(
            f"{PREFIX}/projects/{rich['id']}/tasks",
            headers=headers(cast["alice"]),
            json={"code": "T-SILENT", "title": "Silent blocker",
                  "owner_id": cast["bob"]})
        assert made.status_code == 201
        # Blocked with no reason cannot be set through the API — the service
        # refuses it — so this is the case where a workbook or an older row
        # produced one. Set it directly to prove the brief handles it.
        from backend.db.engine import get_session
        from backend.models.planner import PlannerTask

        with get_session() as session:
            task = session.get(PlannerTask, made.json()["id"])
            task.blocked = True
            task.blocker_reason = ""
            session.commit()

        body = client.get(f"{PREFIX}/projects/{rich['id']}/brief",
                          headers=headers(cast["alice"])).json()
        unknowns = [s for s in body["statements"] if s["kind"] == ai.UNKNOWN]
        assert unknowns, [s["kind"] for s in body["statements"]]
        assert "no reason has been recorded" in unknowns[0]["text"]
        assert any("T-SILENT" in q for q in body["open_questions"])

    def test_it_surfaces_the_outstanding_decision(self, client, cast, rich):
        body = client.get(f"{PREFIX}/projects/{rich['id']}/brief",
                          headers=headers(cast["alice"])).json()
        assert any("Which PD model version" in q
                   for q in body["open_questions"])

    def test_it_declares_how_it_is_grounded(self, client, cast, rich):
        body = client.get(f"{PREFIX}/projects/{rich['id']}/brief",
                          headers=headers(cast["alice"])).json()
        assert "guess" in body["grounding"]


class TestChases:
    def test_the_rules_choose_who_and_the_draft_only_words_it(self, client,
                                                              cast, rich):
        got = client.get(f"{PREFIX}/projects/{rich['id']}/chases",
                         headers=headers(cast["alice"]))
        assert got.status_code == 200, got.text
        body = got.json()
        assert body["sent"] is False
        assert body["drafts"], "nobody was identified as owing an update"
        first = body["drafts"][0]
        assert first["trigger"] in ("overdue_quiet", "blocked_quiet",
                                    "no_progress", "stale")
        assert first["to"]["id"] == cast["bob"]
        assert first["task_code"] in first["body"]

    def test_drafting_changes_nothing(self, client, cast, rich):
        before = client.get(f"{PREFIX}/projects/{rich['id']}/activity",
                            headers=headers(cast["alice"])).json()["count"]
        client.get(f"{PREFIX}/projects/{rich['id']}/chases",
                   headers=headers(cast["alice"]))
        after = client.get(f"{PREFIX}/projects/{rich['id']}/activity",
                           headers=headers(cast["alice"])).json()["count"]
        assert after == before


class TestTheAgentCannotSeePastThePermissions:
    def test_an_outsider_gets_nothing_from_a_brief(self, client, cast, rich):
        got = client.get(f"{PREFIX}/projects/{rich['id']}/brief",
                         headers=headers(cast["mallory"]))
        assert got.status_code == 404

    def test_an_outsider_gets_nothing_from_the_chase_list(self, client, cast,
                                                          rich):
        got = client.get(f"{PREFIX}/projects/{rich['id']}/chases",
                         headers=headers(cast["mallory"]))
        assert got.status_code == 404

    def test_the_portfolio_brief_is_scoped_to_the_caller(self, client, cast,
                                                         rich):
        mine = client.get(f"{PREFIX}/brief",
                          headers=headers(cast["alice"])).json()
        theirs = client.get(f"{PREFIX}/brief",
                            headers=headers(cast["mallory"])).json()
        assert rich["code"] in " ".join(
            s["text"] for s in mine["statements"])
        assert rich["code"] not in " ".join(
            s["text"] for s in theirs["statements"])

    def test_the_tool_handlers_refuse_an_outsider(self, client, cast, rich):
        """Called as the tool executor calls them, not through HTTP.

        The route could be right and the handler wrong; an agent reaches the
        handler.
        """
        from backend.api.permissions import Principal, Role
        from backend.db.engine import get_session
        from backend.planner import access as pacl

        with get_session() as session:
            handlers = ai.handlers(session)
            outsider = Principal(user_id=cast["mallory"], role=Role.ANALYST)
            for tool_id in (reg.PLANNER_PROJECT, reg.PLANNER_TASKS,
                            reg.PLANNER_RAID, reg.PLANNER_CHANGES,
                            reg.PLANNER_ACTIVITY, reg.PLANNER_MILESTONES,
                            reg.PLANNER_DEPENDENCIES):
                with pytest.raises(
                        (pacl.ProjectNotFound, pacl.ProjectDenied)):
                    handlers[tool_id](principal=outsider,
                                      project=rich["id"])

    def test_a_handler_accepts_a_code_as_well_as_an_id(self, client, cast,
                                                       rich):
        """People say "IFRS9-2026", not "project 41"."""
        from backend.api.permissions import Principal, Role
        from backend.db.engine import get_session

        with get_session() as session:
            handlers = ai.handlers(session)
            got = handlers[reg.PLANNER_PROJECT](
                principal=Principal(user_id=cast["alice"], role=Role.ANALYST),
                project=rich["code"])
        assert got["project"]["id"] == rich["id"]
