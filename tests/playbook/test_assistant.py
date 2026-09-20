"""
The conversational runtime: chapters 04, 07 and 15.

These drive the real `assistant.converse` loop — its turn handling, its tool
dispatch and its failure behaviour — against a scripted `provider._call`. The
seam is deliberately that low: patching `converse` itself would test nothing,
and patching the SDK would test the SDK.

The question every case here asks is the one chapter 07 puts first: when part
of a turn fails, does the user still get the part that worked?
"""

from __future__ import annotations

import pytest

from backend.playbook import assistant, provider

# --------------------------------------------------------------------------
# A scripted provider, one response per turn.
# --------------------------------------------------------------------------


class Block:
    """A content block. Enough of one for the loop to read."""

    def __init__(self, type_: str, **kw):
        self.type = type_
        for k, v in kw.items():
            setattr(self, k, v)


class Response:
    def __init__(self, *, content, stop_reason="end_turn",
                 model="scripted-model", request_id="req_scripted"):
        self.content = content
        self.stop_reason = stop_reason
        self.model = model
        self._request_id = request_id
        self.usage = type("U", (), {"input_tokens": 11, "output_tokens": 7})()


def text_block(text: str) -> Block:
    return Block("text", text=text)


def tool_block(name: str, args: dict, id_: str = "tu_1") -> Block:
    return Block("tool_use", name=name, input=args, id=id_)


def says(text: str, **kw) -> Response:
    return Response(content=[text_block(text)], **kw)


def calls(name: str, args: dict, *, said: str = "", id_: str = "tu_1") -> Response:
    content = ([text_block(said)] if said else []) + [tool_block(name, args, id_)]
    return Response(content=content, stop_reason="tool_use")


def _signatures_match(stand_in, real) -> None:
    """Refuse a stub the product would call differently."""
    import inspect

    wanted = set(inspect.signature(real).parameters)
    have = set(inspect.signature(stand_in).parameters)
    missing = wanted - have - {"args", "kwargs"}
    assert not missing, (
        f"the stub for {real.__name__}() is missing {sorted(missing)}; add "
        f"it, or every test using this fixture fails with a TypeError that "
        f"looks like a product defect")


@pytest.fixture
def scripted(monkeypatch):
    """Queue responses; capture what the loop sent back each turn."""
    state: dict = {"queue": [], "sent": [], "tools": [], "choices": []}

    def fake_call(client, *, model, system, messages, tools, container,
                  purpose, role, on_delta=None, is_cancelled=None,
                  deadline=None, with_tools=False, tool_choice=None,
                  on_thinking=None, max_tokens=None):
        state["sent"].append([dict(m) for m in messages])
        state["tools"] = list(tools)
        state["container"] = dict(container)
        state["with_tools"] = with_tools
        # One entry per turn, so a test can assert not only THAT a tool was
        # required but on which turn — forcing one after a tool has already
        # run would loop the assistant forever.
        state["choices"].append(tool_choice)
        if not state["queue"]:
            raise AssertionError("the loop asked for more turns than scripted")
        response = state["queue"].pop(0)
        if on_delta:
            for block in response.content:
                if block.type == "text":
                    on_delta(block.text)
        return response

    # The same drift that broke the soak harness: a stub whose signature has
    # fallen behind the real function fails deep inside the first test that
    # calls it, with a TypeError that reads like a product fault. Caught here,
    # at import of the fixture, naming the parameter.
    _signatures_match(fake_call, provider._call)

    monkeypatch.setattr(provider, "_call", fake_call)
    monkeypatch.setattr(provider, "_client", lambda: object())

    class Role:
        model = "scripted-model"
        effort = "standard"

    monkeypatch.setattr("backend.playbook.assistant.role_config.role",
                        lambda _name: Role())

    def script(*responses):
        state["queue"] = list(responses)
        return state

    script.state = state
    return script


def a_tool(name="create_document", result=None, raises=None, seen=None):
    def run(args):
        if seen is not None:
            seen.append(dict(args))
        if raises is not None:
            raise raises
        return result if result is not None else {"artifact_id": 7}

    return assistant.Tool(
        name=name, description="Create a document.",
        schema={"type": "object", "properties": {"title": {"type": "string"}}},
        run=run)


# --------------------------------------------------------------------------


class TestAnOrdinaryQuestion:
    """DC-01. The whole point of this module."""

    def test_a_question_is_answered_without_any_tool(self, scripted):
        scripted(says("A development report explains how a model was built."))
        reply = assistant.converse(
            system="s", messages=[{"role": "user", "content": "what is it?"}])

        assert reply.text.startswith("A development report")
        assert reply.turns == 1
        assert reply.tool_runs == []
        assert reply.interrupted is False

    def test_no_tools_are_declared_when_none_are_offered(self, scripted):
        state = scripted(says("hello"))
        assistant.converse(system="s", messages=[{"role": "user", "content": "hi"}])

        assert state["tools"] == []
        assert state["with_tools"] is False, (
            "an empty tool list is still a request to consider tools")
        assert state["container"] == {}, "a chat turn starts no sandbox"

    def test_the_answer_streams(self, scripted):
        scripted(says("streamed in pieces"))
        seen: list[str] = []
        assistant.converse(system="s", on_delta=seen.append,
                           messages=[{"role": "user", "content": "q"}])
        assert "".join(seen) == "streamed in pieces"

    def test_usage_and_identity_are_recorded(self, scripted):
        scripted(says("hi", model="scripted-model"))
        reply = assistant.converse(system="s",
                                   messages=[{"role": "user", "content": "q"}])
        assert reply.model_served == "scripted-model"
        assert reply.request_ids == ["req_scripted"]
        assert reply.input_tokens == 11 and reply.output_tokens == 7
        assert reply.downgraded is False

    def test_a_served_model_that_differs_is_reported(self, scripted):
        scripted(says("hi", model="something-else"))
        reply = assistant.converse(system="s",
                                   messages=[{"role": "user", "content": "q"}])
        assert reply.downgraded is True


class TestTheAssistantDecidesToMakeAFile:
    """Chapter 04: the decision is a tool call, not a keyword match."""

    def test_a_tool_call_runs_the_tool_and_the_turn_continues(self, scripted):
        seen: list[dict] = []
        scripted(calls("create_document", {"title": "Auto Loan"}, said="Making it."),
                 says("The Word draft is ready."))
        reply = assistant.converse(
            system="s", messages=[{"role": "user", "content": "write it"}],
            tools=[a_tool(seen=seen)])

        assert seen == [{"title": "Auto Loan"}], "the tool got the model's arguments"
        assert reply.turns == 2
        assert [r.name for r in reply.tool_runs] == ["create_document"]
        assert reply.tool_runs[0].ok is True
        assert reply.tool_runs[0].result == {"artifact_id": 7}

    def test_both_halves_of_what_the_assistant_said_survive(self, scripted):
        scripted(calls("create_document", {}, said="Making it."),
                 says("The Word draft is ready."))
        reply = assistant.converse(
            system="s", messages=[{"role": "user", "content": "write it"}],
            tools=[a_tool()])

        assert "Making it." in reply.text
        assert "The Word draft is ready." in reply.text, (
            "text from each turn is appended; replacing it loses half the answer")

    def test_the_tool_result_is_sent_back_to_the_model(self, scripted):
        state = scripted(calls("create_document", {}), says("done"))
        assistant.converse(system="s",
                           messages=[{"role": "user", "content": "write it"}],
                           tools=[a_tool()])

        second = state["sent"][1]
        assert second[-1]["role"] == "user"
        block = second[-1]["content"][0]
        assert block["type"] == "tool_result"
        assert block["tool_use_id"] == "tu_1"
        assert block["is_error"] is False
        assert "artifact_id" in block["content"]

    def test_tool_stages_are_reported_for_an_honest_work_state(self, scripted):
        scripted(calls("create_document", {}), says("done"))
        stages: list[tuple[str, str]] = []
        assistant.converse(
            system="s", messages=[{"role": "user", "content": "write it"}],
            tools=[a_tool()], on_tool=lambda n, s: stages.append((n, s)))
        assert stages == [("create_document", "running"),
                          ("create_document", "done")]


class TestAFailedToolDoesNotFailTheTurn:
    """Chapter 07 and chapter 16's recovery example."""

    def test_a_declared_failure_is_reported_and_the_answer_survives(self, scripted):
        scripted(calls("create_document", {}),
                 says("The Word draft is ready. The PDF could not be made."))
        reply = assistant.converse(
            system="s", messages=[{"role": "user", "content": "write it"}],
            tools=[a_tool(raises=assistant.ToolFailed("PDF conversion failed"))])

        assert reply.tool_runs[0].ok is False
        assert reply.tool_runs[0].detail == "PDF conversion failed"
        assert "The Word draft is ready." in reply.text, (
            "the turn keeps its answer; a failed tool is one of three outcomes")

    def test_the_model_is_told_what_went_wrong(self, scripted):
        state = scripted(calls("create_document", {}), says("done"))
        assistant.converse(
            system="s", messages=[{"role": "user", "content": "q"}],
            tools=[a_tool(raises=assistant.ToolFailed("PDF conversion failed"))])

        block = state["sent"][1][-1]["content"][0]
        assert block["is_error"] is True
        assert "PDF conversion failed" in block["content"]

    def test_an_unexpected_failure_is_contained_and_not_leaked(self, scripted):
        state = scripted(calls("create_document", {}), says("I could not do that."))
        reply = assistant.converse(
            system="s", messages=[{"role": "user", "content": "q"}],
            tools=[a_tool(raises=RuntimeError("psycopg2: relation does not exist"))])

        assert reply.tool_runs[0].ok is False
        assert "RuntimeError" in reply.tool_runs[0].detail, (
            "the internal detail is kept for diagnostics")
        block = state["sent"][1][-1]["content"][0]
        assert "psycopg2" not in block["content"], (
            "an internal message is not handed to the model as content")
        assert "I could not do that." in reply.text

    def test_a_tool_the_model_invented_is_answered_rather_than_crashed(self, scripted):
        state = scripted(calls("delete_everything", {}), says("I cannot do that."))
        reply = assistant.converse(
            system="s", messages=[{"role": "user", "content": "q"}],
            tools=[a_tool()])

        assert reply.tool_runs[0].name == "delete_everything"
        assert reply.tool_runs[0].ok is False
        block = state["sent"][1][-1]["content"][0]
        assert block["is_error"] is True
        assert "No tool named" in block["content"]

    def test_several_tool_calls_in_one_turn_all_run(self, scripted):
        first = Response(
            content=[tool_block("create_document", {"n": 1}, "tu_1"),
                     tool_block("create_document", {"n": 2}, "tu_2")],
            stop_reason="tool_use")
        seen: list[dict] = []
        scripted(first, says("both done"))
        reply = assistant.converse(
            system="s", messages=[{"role": "user", "content": "q"}],
            tools=[a_tool(seen=seen)])

        assert seen == [{"n": 1}, {"n": 2}]
        assert len(reply.tool_runs) == 2


class TestTheEdges:

    def test_a_truncated_answer_is_marked_interrupted(self, scripted):
        scripted(says("half a sen", stop_reason="max_tokens"))
        reply = assistant.converse(system="s",
                                   messages=[{"role": "user", "content": "q"}])
        assert reply.interrupted is True
        assert reply.text == "half a sen", "the partial text is kept, and labelled"

    def test_a_refusal_is_raised_rather_than_shown_as_an_answer(self, scripted):
        scripted(Response(content=[], stop_reason="refusal"))
        with pytest.raises(provider.AuthoringError) as caught:
            assistant.converse(system="s",
                               messages=[{"role": "user", "content": "q"}])
        assert caught.value.category == "refusal"

    def test_running_out_of_tool_turns_keeps_the_work_so_far(self, scripted):
        scripted(*[calls("create_document", {}, said=f"step {i}")
                   for i in range(assistant.MAX_TOOL_TURNS)])
        reply = assistant.converse(
            system="s", messages=[{"role": "user", "content": "q"}],
            tools=[a_tool()])

        assert reply.interrupted is True
        assert reply.turns == assistant.MAX_TOOL_TURNS
        assert "step 0" in reply.text, (
            "a loop that does not converge still delivers what it did")
        assert len(reply.tool_runs) == assistant.MAX_TOOL_TURNS

    def test_a_stop_before_the_call_raises_rather_than_spending_a_turn(self, scripted):
        state = scripted(says("never reached"))
        with pytest.raises(provider.Cancelled):
            assistant.converse(system="s",
                               messages=[{"role": "user", "content": "q"}],
                               is_cancelled=lambda: True)
        assert state["sent"] == [], "no provider call was made"

    def test_no_configured_model_is_a_configuration_state(self, scripted, monkeypatch):
        scripted(says("never reached"))

        class Blank:
            model = ""
            effort = "standard"

        monkeypatch.setattr("backend.playbook.assistant.role_config.role",
                            lambda _n: Blank())
        with pytest.raises(provider.ProviderNotConfigured) as caught:
            assistant.converse(system="s",
                               messages=[{"role": "user", "content": "q"}])
        assert "AI_AUTHOR_MODEL" in str(caught.value)
        assert "stay readable" in str(caught.value), (
            "a missing key is not a broken product")

    def test_the_reply_serialises_for_the_transcript(self, scripted):
        scripted(calls("create_document", {}), says("done"))
        reply = assistant.converse(
            system="s", messages=[{"role": "user", "content": "q"}],
            tools=[a_tool()])
        payload = reply.as_dict()

        assert payload["tools"] == [
            {"name": "create_document", "ok": True, "detail": "",
             "result": {"artifact_id": 7}}]
        assert payload["interrupted"] is False
        assert payload["request_ids"] == ["req_scripted", "req_scripted"]


# ==========================================================================
# A turn that promises a document and produces none.
#
# This is the class of failure that reached a user. A real model, asked to
# draft a report, answered:
#
#     "I'll draft the full committee report now. Before the tool call, two
#      things shape how I've written it…"
#
# and called nothing. The turn was recorded as a complete, successful answer,
# the Files panel said "Nothing generated yet", and the user pressed Send
# three more times.
#
# Nothing in the suite could catch it, because the scripted fixture decides
# whether a tool is called: it proves the plumbing works WHEN the tool is
# called, never that a model reaches for it. These tests script the refusal
# instead.
# ==========================================================================


class TestADeclaredDocumentTaskMustProduceOne:

    def test_the_first_turn_requires_a_tool_when_the_caller_declared_one(
            self, scripted):
        state = scripted(calls("create_document", {"instruction": "Write it."}),
                         says("Both files are ready."))
        assistant.converse(system="s", messages=[{"role": "user",
                                                  "content": "Draft it."}],
                           tools=[a_tool()], require_tool=True)

        assert state["choices"][0] == {"type": "any"}, (
            "the user clicked a control that says what it does; the model "
            "must reach for a tool rather than describe the document")

    def test_the_choice_is_open_between_the_tools_on_offer(self, scripted):
        """`any`, never a named tool.

        Which document operation this is — create, revise, convert — is still
        the assistant's decision. Naming one here would be the routing
        chapter 04 forbids.
        """
        state = scripted(calls("create_document", {"instruction": "Write it."}),
                         says("Done."))
        assistant.converse(system="s", messages=[{"role": "user", "content": "x"}],
                           tools=[a_tool()], require_tool=True)
        assert state["choices"][0] == {"type": "any"}
        assert "name" not in state["choices"][0]

    def test_later_turns_are_free(self, scripted):
        """Forcing a tool on every turn would loop the assistant for ever."""
        state = scripted(calls("create_document", {"instruction": "Write it."}),
                         says("Both files are ready."))
        assistant.converse(system="s", messages=[{"role": "user", "content": "x"}],
                           tools=[a_tool()], require_tool=True)
        assert state["choices"][1] is None

    def test_nothing_is_forced_when_no_task_was_declared(self, scripted):
        """An ordinary question must never be turned into a document."""
        state = scripted(says("A development report explains how it was built."))
        reply = assistant.converse(
            system="s", messages=[{"role": "user", "content": "What is the "
                                                              "difference?"}],
            tools=[a_tool()])
        assert state["choices"] == [None]
        assert reply.tool_runs == []

    def test_nothing_is_forced_when_there_are_no_tools(self, scripted):
        """`tool_choice` without `tools` is a request the provider rejects."""
        scripted(says("Fine."))
        assistant.converse(system="s", messages=[{"role": "user", "content": "x"}],
                           tools=[], require_tool=True)


class TestAPromiseWithNoToolCall:

    def test_a_promise_with_no_tool_call_is_corrected_once(self, scripted):
        state = scripted(
            says("I'll draft the full committee report now. Before the tool "
                 "call, two things shape how I've written it."),
            calls("create_document", {"instruction": "Write it."}),
            says("Both files are ready."))
        reply = assistant.converse(
            system="s", messages=[{"role": "user", "content": "Draft it."}],
            tools=[a_tool()])

        assert reply.nudged is True
        assert [r.name for r in reply.tool_runs] == ["create_document"]
        assert reply.made_document is True
        assert reply.broke_its_promise is False
        # The correction went back as a user turn the model can act on, and
        # says plainly what is not true rather than only "try again".
        last_sent = state["sent"][1][-1]
        assert "no file exists" in last_sent["content"]

    def test_it_is_corrected_once_and_not_twice(self, scripted):
        """A model that will not call is not made to by repetition. One
        bounded extra call; the turn then ends and says what happened."""
        scripted(says("I'll draft that now."),
                 says("I have written the report."))
        reply = assistant.converse(
            system="s", messages=[{"role": "user", "content": "Draft it."}],
            tools=[a_tool()])

        assert reply.nudged is True
        assert reply.turns == 2, "one correction, not a loop"
        assert reply.broke_its_promise is True

    def test_a_broken_promise_is_recorded_for_the_interface(self, scripted):
        scripted(says("I'll draft that now."), says("I've drafted it."))
        reply = assistant.converse(
            system="s", messages=[{"role": "user", "content": "Draft it."}],
            tools=[a_tool()])

        assert reply.as_dict()["no_file"] is True, (
            "an answer that reads like success beside an empty Files panel is "
            "the failure that started this")
        assert reply.as_dict()["nudged"] is True

    def test_an_ordinary_answer_is_never_corrected(self, scripted):
        """The detector reads the ASSISTANT's claim, never the user's words.

        "Draft the report" from the user is a request; only the assistant
        saying it has drafted one is a claim that can be false.
        """
        state = scripted(says("A development report explains how the scorecard "
                              "was built; a validation report challenges it."))
        reply = assistant.converse(
            system="s",
            messages=[{"role": "user", "content": "Draft the report for me?"}],
            tools=[a_tool()])

        assert reply.nudged is False
        assert reply.broke_its_promise is False
        assert len(state["sent"]) == 1, "no second call was spent"

    def test_a_promise_kept_is_not_a_broken_one(self, scripted):
        scripted(calls("create_document", {"instruction": "Write it."},
                       said="I'll draft that now."),
                 says("Both files are ready."))
        reply = assistant.converse(
            system="s", messages=[{"role": "user", "content": "Draft it."}],
            tools=[a_tool()])

        assert reply.promised_document is True
        assert reply.made_document is True
        assert reply.broke_its_promise is False

    def test_a_failed_tool_is_not_a_kept_promise(self, scripted):
        """The tool ran and could not do it. The user has no file, and the
        turn must not imply otherwise."""
        scripted(calls("create_document", {"instruction": "Write it."},
                       said="I'll draft that now."),
                 says("The Word file could not be produced."))
        reply = assistant.converse(
            system="s", messages=[{"role": "user", "content": "Draft it."}],
            tools=[a_tool(raises=assistant.ToolFailed("no renderer"))])

        assert reply.made_document is False
        assert reply.broke_its_promise is True

    def test_a_truncated_promise_is_not_corrected(self, scripted):
        """A turn cut off at max_tokens is interrupted, not disobedient.
        Spending another call on it would pay twice for the same stall."""
        scripted(says("I'll draft that now.", stop_reason="max_tokens"))
        reply = assistant.converse(
            system="s", messages=[{"role": "user", "content": "Draft it."}],
            tools=[a_tool()])

        assert reply.interrupted is True
        assert reply.nudged is False

    @pytest.mark.parametrize("said,expected", [
        ("I'll draft the full committee report now.", True),
        ("Before the tool call, two things shape how I've written it.", True),
        ("I have what I need. Drafting now — the report will carry every "
         "supplied figure exactly.", True),
        ("I've prepared the paper.", True),
        ("A development report explains how the scorecard was built.", False),
        ("What would you like the report to cover?", False),
        ("I cannot draft that without the methodology.", False),
    ])
    def test_the_detector_reads_claims_and_not_topics(self, said, expected):
        """The two live replies are in here verbatim, and both must match."""
        assert assistant.promised_a_document(said) is expected
