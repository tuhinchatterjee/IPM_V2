"""Reading ordinary language into planner commands.

These test the reader directly, against a plan built the way the panels build
one. The HTTP tests next door prove the same sentences change a real draft;
these prove WHAT they were read as, which is the part that can go subtly
wrong — an owner set on the milestone instead of the task, a date read as
January because it was written 01/10.

Nothing here is tailored to a sentence. Every name in the fixtures is
resolved against the plan's own catalogue and the directory, so a rule that
only worked on the phrasing below would fail the moment the fixture was
renamed — which is the property that makes this a reader rather than a lookup
table.
"""

from __future__ import annotations

from datetime import date

import pytest

from backend.planner import draft as dr
from backend.planner import language as lang
from backend.planner import reading as rd

TODAY = date(2026, 9, 6)

PEOPLE = [
    {"user_id": 1, "name": "Rohan Mehta", "username": "rohan.mehta"},
    {"user_id": 2, "name": "Priya Raman", "username": "priya.raman"},
    {"user_id": 3, "name": "Sameer Haddad", "username": "sameer.haddad"},
    {"user_id": 4, "name": "Daniel Okafor", "username": "daniel.okafor"},
    {"user_id": 5, "name": "Ananya Rao", "username": "ananya.rao"},
    {"user_id": 6, "name": "Sameer Iqbal", "username": "sameer.iqbal"},
]


def _plan() -> dict:
    plan = dr.empty()
    plan["governance"]["start_date"] = "2026-10-01"
    plan["governance"]["target_end_date"] = "2027-06-30"
    plan["milestones"] = [
        {"code": "M01", "name": "Data Foundation"},
        {"code": "M02", "name": "Model Development"},
        {"code": "M03", "name": "Validation"},
    ]
    plan["tasks"] = [
        {"code": "M01-T01", "milestone_code": "M01", "title": "Data Extraction"},
        {"code": "M01-T02", "milestone_code": "M01",
         "title": "Data Reconciliation"},
        {"code": "M03-T01", "milestone_code": "M03",
         "title": "Validation Report"},
        {"code": "M03-T02", "milestone_code": "M03",
         "title": "Validation Sign-off"},
    ]
    return plan


def _read(message: str, *, plan: dict | None = None, focus: str = "",
          answers: dict | None = None, people=None) -> lang.Reading:
    return lang.read_with_rules(message, lang.Context(
        plan=plan if plan is not None else _plan(),
        directory=rd.Directory(people if people is not None else PEOPLE),
        today=TODAY, focus=focus, answers=answers or {}))


def _only(found: lang.Reading) -> lang.Proposal:
    assert not found.questions, [q.text for q in found.questions]
    assert not found.unread, found.unread
    assert len(found.commands) == 1, [c.to_dict() for c in found.commands]
    return found.commands[0]


# ------------------------------------------------- the ten mandated shapes


def test_add_a_milestone_by_name():
    found = _read("Add Data Foundation as the first milestone.",
                  plan=dr.empty())
    proposal = _only(found)
    assert proposal.command == "add_milestone"
    assert proposal.payload == {"name": "Data Foundation"}
    # Adding something new promises nothing, so it needs no confirmation.
    assert proposal.preview is False


def test_one_sentence_can_carry_two_facts():
    """"Rohan owns Data Foundation and Priya is the escalation owner."

    The second clause has no object; it means the thing the first clause was
    about. A reader that treated the sentence as one fact would set the owner
    of a milestone called "Data Foundation and Priya".
    """
    found = _read("Rohan owns Data Foundation and Priya is the escalation "
                  "owner.")
    assert not found.unread
    assert [c.payload for c in found.commands] == [
        {"code": "M01", "owner_id": 1},
        {"code": "M01", "escalation_id": 2},
    ]
    assert all(c.command == "update_milestone" for c in found.commands)


def test_a_pronoun_means_what_we_were_just_discussing():
    found = _read("It starts 1 October and ends 31 October.", focus="M01")
    proposal = _only(found)
    assert proposal.command == "update_milestone"
    assert proposal.payload == {"code": "M01", "start_date": "2026-10-01",
                                "target_date": "2026-10-31"}
    assert proposal.preview is True


def test_a_list_of_tasks_under_a_named_milestone():
    found = _read("Under Data Foundation add Data Extraction, Data "
                  "Reconciliation and Data Quality Review.", plan={
                      **dr.empty(),
                      "milestones": [{"code": "M01", "name": "Data Foundation"}],
                      "tasks": [], "links": []})
    assert not found.questions and not found.unread
    assert [c.payload["title"] for c in found.commands] == [
        "Data Extraction", "Data Reconciliation", "Data Quality Review"]
    assert all(c.payload["milestone_code"] == "M01" for c in found.commands)


def test_an_owner_and_a_date_in_one_clause():
    proposal = _only(_read("Sameer Haddad owns Data Extraction until "
                           "10 October."))
    assert proposal.command == "update_task"
    assert proposal.payload == {"code": "M01-T01", "owner_id": 3,
                                "due_date": "2026-10-10"}


def test_link_a_to_b_makes_a_wait_for_b():
    proposal = _only(_read("Link Data Reconciliation to Data Extraction."))
    assert proposal.command == "add_link"
    assert proposal.payload == {"predecessor": "M01-T01",
                                "successor": "M01-T02"}
    # The reading is stated back, because "link A to B" has two readings and
    # only the person knows which they meant.
    assert "Data Reconciliation will wait for Data Extraction" \
        in proposal.sentence
    assert proposal.preview is True


def test_a_dependency_said_the_long_way_round():
    proposal = _only(_read("Validation can only start after Model "
                           "Development is finished."))
    assert proposal.payload == {"predecessor": "M02", "successor": "M03"}


def test_a_code_is_an_identifier_not_a_guess():
    proposal = _only(_read("Move M03-T02 to Daniel."))
    assert proposal.command == "update_task"
    assert proposal.payload == {"code": "M03-T02", "owner_id": 4}


def test_the_monitoring_mode():
    proposal = _only(_read("Change this project's monitoring to Critical."))
    assert proposal.command == "set_agentic"
    assert proposal.payload == {"mode": "CRITICAL"}


def test_escalation_reaches_every_task_it_named_and_sets_the_threshold():
    """"Escalate Validation tasks to Ananya after two days overdue."

    Two facts: who hears, and when. And "Validation tasks" is a plural — a
    reader that resolved it to the single best match would silently do a
    third of what was asked.
    """
    found = _read("Escalate Validation tasks to Ananya after two days "
                  "overdue.")
    assert not found.questions and not found.unread
    escalations = [c for c in found.commands if "escalation_id" in c.payload]
    assert {c.payload["code"] for c in escalations} == {"M03-T01", "M03-T02"}
    assert all(c.payload["escalation_id"] == 5 for c in escalations)

    policy = [c for c in found.commands if c.command == "set_agentic"]
    assert len(policy) == 1
    assert policy[0].payload["mode"] == "CUSTOM"
    assert policy[0].payload["policy"]["escalate_after_days"] == 2


# ------------------------------------------------------ a messy paragraph


def test_a_paragraph_of_mixed_facts_about_things_that_do_not_exist_yet():
    """The hard case: everything referred to is created by the same message.

    "Reporting" has no code when "Priya owns it" is read, and "Draft Report"
    has no code when "Committee Review can only start after Draft Report" is
    read. The reader hands out placeholders and the executor fills them in
    from what the earlier commands actually created.
    """
    found = _read(
        "We need a Reporting milestone, Priya owns it, it starts "
        "15 November and ends 20 December, and under it add Draft Report, "
        "Committee Review and Final Sign-off. Sameer Haddad owns Draft "
        "Report until 30 November. Committee Review can only start after "
        "Draft Report is finished.", plan=dr.empty())
    assert not found.questions
    assert not found.unread, found.unread

    commands = [(c.command, c.payload) for c in found.commands]
    assert commands[0] == ("add_milestone", {"name": "Reporting"})
    milestone = found.commands[0].creates
    assert milestone.startswith(lang.PENDING)

    assert ("update_milestone", {"code": milestone, "owner_id": 2}) in commands
    assert ("update_milestone", {"code": milestone,
                                 "start_date": "2026-11-15",
                                 "target_date": "2026-12-20"}) in commands
    titles = [p["title"] for c, p in commands if c == "add_task"]
    assert titles == ["Draft Report", "Committee Review", "Final Sign-off"]

    # The ownership and the dependency both point at placeholders, not names.
    owned = [p for c, p in commands
             if c == "update_task" and p.get("owner_id") == 3]
    assert len(owned) == 1 and owned[0]["due_date"] == "2026-11-30"
    links = [p for c, p in commands if c == "add_link"]
    assert len(links) == 1
    assert links[0]["predecessor"].startswith(lang.PENDING)
    assert links[0]["successor"].startswith(lang.PENDING)
    assert links[0]["predecessor"] != links[0]["successor"]


# ------------------------------------------------------------- asking back


def test_two_people_with_one_first_name_is_a_question():
    found = _read("Sameer owns Data Extraction.")
    assert not found.commands
    assert len(found.questions) == 1
    question = found.questions[0]
    assert "which" in question.text.lower()
    assert {o["label"] for o in question.options} == {"Sameer Haddad",
                                                     "Sameer Iqbal"}


def test_the_answer_is_applied_by_re_reading_the_same_sentence():
    """A clarification changes how the sentence is read, not what is run.

    The client sends the answer alongside the original words; it never sends
    a command. So the disambiguation cannot become a second way into the
    planner.
    """
    found = _read("Sameer owns Data Extraction.", answers={"sameer": "3"})
    proposal = _only(found)
    assert proposal.payload == {"code": "M01-T01", "owner_id": 3}


def test_a_name_nobody_has_is_said_back_rather_than_invented():
    found = _read("Escalate Validation Report to Fergus.")
    assert not found.commands
    assert found.questions
    assert "Fergus" in found.questions[0].text
    assert found.questions[0].options == []


def test_something_that_is_not_in_the_plan_is_a_question():
    found = _read("Move Data Cleansing to Daniel.")
    assert not found.commands
    assert found.questions
    assert "Data Cleansing" in found.questions[0].text


def test_a_sentence_it_cannot_read_is_reported_not_guessed():
    found = _read("Please tidy this up a bit and make it nicer.")
    assert not found.commands
    assert found.unread


# ------------------------------------------------------ dates and numbers


@pytest.mark.parametrize("said,expected", [
    ("1 October", date(2026, 10, 1)),
    ("1st October 2026", date(2026, 10, 1)),
    ("October 1", date(2026, 10, 1)),
    ("2026-10-01", date(2026, 10, 1)),
    ("01/10/2026", date(2026, 10, 1)),
    ("tomorrow", date(2026, 9, 7)),
    ("in two weeks", date(2026, 9, 20)),
    ("next Friday", date(2026, 9, 11)),
])
def test_dates_however_they_are_written(said, expected):
    found = rd.find_date(said, today=TODAY)
    assert found is not None and found.value == expected


def test_a_slashed_date_is_read_day_first():
    """01/10 is the first of October.

    Reading it the American way would move a deadline nine months without
    anybody noticing, which is the kind of defect that only shows up in a
    steering meeting.
    """
    found = rd.find_date("01/10/2026", today=TODAY)
    assert found and found.value == date(2026, 10, 1)


def test_a_bare_date_lands_inside_the_project_window():
    """"1 March" on a plan running to June 2027 means March 2027."""
    plan = _plan()
    plan["governance"]["start_date"] = "2026-10-01"
    plan["governance"]["target_end_date"] = "2027-06-30"
    proposal = _only(_read("Validation Report is due 1 March.", plan=plan))
    assert proposal.payload["due_date"] == "2027-03-01"


@pytest.mark.parametrize("said,expected", [
    ("two", 2), ("2", 2), ("2nd", 2), ("ten", 10), ("third", 3),
])
def test_numbers_in_words(said, expected):
    assert rd.number(said) == expected


# ------------------------------------------------------------- what is safe


def test_only_registered_commands_can_be_proposed():
    """The reader's whole output surface is the draft's command list."""
    plan = _plan()
    for message in ["Delete the project.", "Publish this plan now.",
                    "Give everyone owner access.",
                    "Run the IFRS 9 staging analysis."]:
        found = _read(message, plan=plan)
        for proposal in found.commands:
            assert proposal.command in dr.COMMANDS


def test_a_removal_says_what_it_takes_with_it():
    proposal = _only(_read("Remove Data Foundation."))
    assert proposal.command == "remove_milestone"
    assert proposal.preview is True
    assert "2 tasks" in proposal.sentence


def test_additions_apply_and_commitments_wait():
    """§4 as a property rather than as a list of examples."""
    plan = _plan()
    adds = _read("Under Validation add Independent Review.", plan=plan)
    assert all(not c.preview for c in adds.commands)

    for message in ["Move M03-T02 to Daniel.",
                    "Validation Report is due 1 March.",
                    "Link Validation Sign-off to Validation Report.",
                    "Change monitoring to Light.",
                    "Remove Validation Report."]:
        found = _read(message, plan=plan)
        assert found.commands, message
        assert all(c.preview for c in found.commands), message


# ------------------------------------------------------- the provider path
#
# There is no live AI provider in this environment, so LIVE AI stays NOT
# VERIFIED. What IS verified here is the whole contract around it: the schema
# the model must answer in, that the model's answer is resolved and validated
# rather than trusted, and that an offline deployment falls back rather than
# inventing. A fake provider exercises the same `structured()` call the real
# Anthropic provider implements.


class _FakeProvider:
    """A provider that returns a fixed document, recording how it was asked."""

    name = "fake"
    model = "fake-1"

    def __init__(self, document):
        self.document = document
        self.calls: list[dict] = []

    @property
    def configured(self) -> bool:
        return True

    def structured(self, **kwargs):
        from backend.llm.base import LLMResult

        self.calls.append(kwargs)
        return LLMResult(data=self.document, model=self.model)


def _ctx(plan=None, people=None):
    return lang.Context(plan=plan if plan is not None else _plan(),
                        directory=rd.Directory(people or PEOPLE),
                        today=TODAY)


def test_the_model_is_asked_only_about_what_the_rules_could_not_read():
    """A live provider makes the Copilot understand more phrasings.

    It never makes it understand a sentence differently: the rules run first,
    and only the leftovers are sent.
    """
    provider = _FakeProvider({"commands": []})
    found = lang.read("Move M03-T02 to Daniel.", _ctx(), provider=provider)
    assert found.source == "rules"
    assert provider.calls == []

    provider = _FakeProvider({"commands": [
        {"command": "update_task", "task": "Validation Report",
         "owner": "Daniel"}]})
    found = lang.read("Could you get Daniel to pick up the validation write-up "
                      "at some point", _ctx(), provider=provider)
    assert provider.calls, "the leftover should have reached the model"
    assert found.commands[0].payload == {"code": "M03-T01", "owner_id": 4}
    assert found.commands[0].source == "model"


def test_the_model_is_told_the_plan_and_the_people_but_asked_for_words():
    provider = _FakeProvider({"commands": []})
    lang.read("please sort out the reporting", _ctx(), provider=provider)
    call = provider.calls[0]
    assert "M01-T01" in call["prompt"] and "Data Extraction" in call["prompt"]
    assert "Sameer Haddad" in call["prompt"]
    # The schema offers no id fields at all, so the model has nothing to put
    # a user id into even if it wanted to.
    fields = lang.MODEL_SCHEMA["properties"]["commands"]["items"]["properties"]
    assert not [key for key in fields if key.endswith("_id")]
    assert set(fields["command"]["enum"]) == set(dr.COMMANDS)


def test_a_command_the_model_invents_is_dropped():
    found = lang.resolve_model(
        {"commands": [{"command": "grant_admin", "owner": "Daniel"},
                      {"command": "delete_project"}]}, _ctx())
    assert found.commands == []
    assert len(found.unread) == 2


def test_a_person_the_model_names_is_resolved_here_not_trusted():
    """The model says "Sameer"; the directory decides which one.

    Two colleagues share that first name, so the answer is a question — the
    same question the rule reader would have asked.
    """
    found = lang.resolve_model(
        {"commands": [{"command": "update_task", "task": "Data Extraction",
                       "owner": "Sameer"}]}, _ctx())
    assert found.commands == []
    assert found.questions
    assert {o["label"] for o in found.questions[0].options} == {
        "Sameer Haddad", "Sameer Iqbal"}


def test_an_item_the_model_names_must_exist_in_the_plan():
    found = lang.resolve_model(
        {"commands": [{"command": "update_task", "task": "Nonexistent Task",
                       "owner": "Daniel Okafor"}]}, _ctx())
    assert found.commands == []
    assert "Nonexistent Task" in found.questions[0].text


def test_a_date_the_model_repeats_is_parsed_here():
    found = lang.resolve_model(
        {"commands": [{"command": "update_task", "task": "M01-T01",
                       "end_date": "the 10th of October"}]}, _ctx())
    assert found.commands[0].payload["due_date"] == "2026-10-10"


def test_a_model_change_still_needs_confirming():
    found = lang.resolve_model(
        {"commands": [{"command": "update_task", "task": "M01-T01",
                       "owner": "Daniel Okafor"}]}, _ctx())
    assert found.commands[0].preview is True


def test_with_no_provider_the_rules_answer_alone():
    """An offline deployment reads what it can and says what it cannot.

    It does not degrade into guessing, and it does not report an outage: the
    rule reader is the product's floor, not its failure mode.
    """
    class Offline:
        name, model = "none", ""
        configured = False

        def structured(self, **_kwargs):  # pragma: no cover - never called
            raise AssertionError("an offline provider must not be called")

    found = lang.read("Move M03-T02 to Daniel. Then do something clever.",
                      _ctx(), provider=Offline())
    assert found.source == "rules"
    assert found.commands[0].payload == {"code": "M03-T02", "owner_id": 4}
    assert found.unread


def test_a_provider_that_fails_leaves_the_rules_reading_standing():
    class Broken:
        name, model = "broken", "x"
        configured = True

        def structured(self, **_kwargs):
            from backend.llm.base import LLMError

            raise LLMError("the provider is unreachable")

    found = lang.read("Move M03-T02 to Daniel. Then do something clever.",
                      _ctx(), provider=Broken())
    assert found.commands[0].payload == {"code": "M03-T02", "owner_id": 4}
    assert found.source == "rules"


# ------------------------------------------ naming the stages in one breath


def test_three_milestones_from_one_sentence():
    """How somebody names the stages of a programme the first time.

    The singular rule reads "add X as the first milestone" — the sentence
    said second. Reading only that one made the FIRST sentence of every new
    project unreadable.
    """
    read = _read("Add Data Foundation, Model Build and Independent "
                 "Validation as the milestones.", plan=dr.empty())

    assert not read.questions, read.questions
    assert not read.unread, read.unread
    assert [c.command for c in read.commands] == ["add_milestone"] * 3
    assert [c.payload["name"] for c in read.commands] == [
        "Data Foundation", "Model Build", "Independent Validation"]
    assert len({c.creates for c in read.commands}) == 3, \
        "each new milestone needs its own handle for later commands to name"


def test_the_milestones_are_form_reads_too():
    read = _read("The milestones are Discovery, Build and Handover.",
                 plan=dr.empty())
    assert [c.payload["name"] for c in read.commands] == [
        "Discovery", "Build", "Handover"]


def test_a_single_milestone_still_goes_through_the_ordinal_rule():
    """So that "as the first milestone" keeps working, ordinal and all."""
    read = _read("Add Data Foundation as the first milestone.",
                 plan=dr.empty())
    assert [c.command for c in read.commands] == ["add_milestone"]
    assert read.commands[0].payload["name"] == "Data Foundation"


def test_a_list_of_milestones_sets_no_focus():
    """"It" after three names refers to nothing, and guessing would be worse."""
    read = _read("Add One, Two and Three as the milestones.",
                 plan=dr.empty())
    assert not read.focus, read.focus
