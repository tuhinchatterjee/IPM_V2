"""
The conversational runtime. Chapters 04, 07, 08 and 15 of the Direct Chat
specification.

One turn of ordinary conversation, with tools the assistant may use when the
request needs them. This exists because the product had exactly one path —
every message, including "what is the difference between a development and a
validation report?", went through `service.author_document` and tried to render
a Word file and a PDF. A question that produced no document was an error.

Two rules shape everything here.

**The assistant decides whether a turn needs a file, and it decides by calling
a tool.** Not a keyword match on the user's text, which cannot tell "write me
the report" from "what would go in the report?", and not a second Generate
button, which chapter 04 forbids. A tool call is a decision the model states
explicitly and the transcript records.

**A tool that fails does not fail the turn.** The result goes back to the model
as a tool result saying what went wrong, and the model reports it to the user
in its own words. Chapter 07 is specific: an answer, a delivered file and a
failed conversion are three independent outcomes, and a turn may honestly have
all three.

Nothing in this module writes a document version, touches the dashboard or runs
a content check. It calls tools, streams text and returns what happened.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from backend.llm import roles as role_config
from backend.playbook import provider

logger = logging.getLogger(__name__)

#: How many times the assistant may call tools before the turn is cut short.
#: A conversation is not an agent loop: the tools here create or revise a
#: document, and a turn that has done that six times is not converging.
MAX_TOOL_TURNS = 6


class ToolFailed(Exception):
    """A tool could not do what it was asked.

    Raised by a tool implementation, caught here, and reported to the model as
    a tool result. It is not an error in the turn — the assistant still has an
    answer to give, and chapter 16's recovery example is exactly this case:
    "The Word draft is ready. The PDF conversion could not be completed."
    """


@dataclass
class ToolRun:
    """One tool call and what came back, for the transcript and the dashboard."""

    name: str
    request: dict = field(default_factory=dict)
    ok: bool = True
    detail: str = ""
    #: Whatever the tool produced — an artifact id, file records, a figure.
    result: dict = field(default_factory=dict)


@dataclass
class Reply:
    """What one conversational turn produced."""

    text: str = ""
    model_requested: str = ""
    model_served: str = ""
    request_ids: list[str] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    turns: int = 0
    tool_runs: list[ToolRun] = field(default_factory=list)
    provider_ms: int = 0
    stop_reason: str = ""
    #: Set when the model stopped mid-answer. Chapter 07: partial text is
    #: labelled interrupted, never presented as a finished answer.
    interrupted: bool = False
    #: The turn's own words said a document was written or was being written.
    promised_document: bool = False
    #: A document tool actually ran and succeeded.
    made_document: bool = False
    #: The turn was given one corrective second chance (see `_PROMISES`).
    nudged: bool = False

    @property
    def broke_its_promise(self) -> bool:
        """Said a document exists, produced none.

        The product rule is already written down — "a document is not created
        because you mention its filename" — and this is that rule turned into
        a fact the interface can act on, instead of a sentence the model may
        or may not honour.
        """
        return self.promised_document and not self.made_document

    @property
    def downgraded(self) -> bool:
        return bool(self.model_served
                    and self.model_requested
                    and self.model_served != self.model_requested)

    def as_dict(self) -> dict:
        return {
            "text": self.text,
            "model_served": self.model_served,
            "request_ids": list(self.request_ids),
            "turns": self.turns,
            "interrupted": self.interrupted,
            "nudged": self.nudged,
            "no_file": self.broke_its_promise,
            "tools": [
                {"name": r.name, "ok": r.ok, "detail": r.detail,
                 "result": r.result}
                for r in self.tool_runs
            ],
        }


@dataclass
class Tool:
    """One thing the assistant can do, and the function that does it.

    `run` takes the model's arguments and returns a dict, or raises
    `ToolFailed`. It is given the arguments only: everything else it needs —
    the session, the workspace, the scope — is bound by the caller when the
    tool is built. That keeps this module free of any knowledge of what a
    document is.
    """

    name: str
    description: str
    schema: dict
    run: Callable[[dict], dict]

    def declaration(self) -> dict:
        return {"name": self.name,
                "description": self.description,
                "input_schema": self.schema}


def _tool_uses(response: Any) -> list[Any]:
    """The client-tool calls in one response, in the order the model made them."""
    return [b for b in (getattr(response, "content", None) or [])
            if getattr(b, "type", "") == "tool_use"]


def _result_block(use: Any, payload: dict, *, ok: bool) -> dict:
    """One tool_result block. A failure is content, not an exception."""
    return {
        "type": "tool_result",
        "tool_use_id": getattr(use, "id", ""),
        "is_error": not ok,
        "content": json.dumps(payload, default=str)[:20_000],
    }


#: Things a turn says when it believes it has written, or is writing, a
#: document. Short and literal on purpose — this is not an attempt to read the
#: model's intent, only to notice the one claim the product already forbids
#: making falsely: "a document is not created because you mention its
#: filename".
#:
#: Note what is NOT matched here: the user's wording. This reads the
#: ASSISTANT's own sentence and compares it against what the tools actually
#: did, which is a check on an outcome rather than a guess at a request.
_PROMISES = (
    "i'll draft", "i will draft", "i'm drafting", "i am drafting",
    "drafting now", "i'll write", "i will write", "i'm writing",
    "i've drafted", "i have drafted", "i've written", "i have written",
    "i'll create", "i will create", "i'll produce", "i will produce",
    "i'll prepare", "i will prepare", "i've prepared", "i have prepared",
    "before the tool call", "i'll put that together",
    "the report will", "the document will", "here is the report",
)

#: Sent back to the model when it promised and did not call. One turn, once.
_NOT_DONE = (
    "No document tool was called, so no file exists and nothing was saved. "
    "Your last message describes a document that does not exist. If the user "
    "asked for a document, call the tool now and let it do the writing. If "
    "they did not, say so plainly and do not describe a document as written."
)


def promised_a_document(text: str) -> bool:
    """Whether this turn's own words claim a document was or is being made."""
    lowered = (text or "").lower()
    return any(phrase in lowered for phrase in _PROMISES)


def converse(
    *,
    system: str,
    messages: list[dict],
    tools: list[Tool] | None = None,
    purpose: str = "playbook_chat",
    require_tool: bool = False,
    on_delta: Callable[[str], None] | None = None,
    on_thinking: Callable[[str], None] | None = None,
    on_tool: Callable[[str, str], None] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> Reply:
    """Run one conversational turn to completion.

    Streams answer text through `on_delta` and nothing else — not reasoning,
    not tool arguments, not the code a sandbox is about to run. `on_tool`
    receives (name, stage) so the interface can show an honest work state such
    as "Creating Word" rather than a timer pretending to be progress.

    Raises only for a turn that genuinely could not happen: no configured
    model, a provider error, cancellation. A tool that fails is reported to the
    model and the turn continues.

    `require_tool`
    --------------
    The caller declared that this turn is document work — the user clicked
    "Draft the report from these sources", or a caller that knows its own
    intent said so. The first turn is then sent with `tool_choice: any`, so the
    assistant must reach for one of the tools it has rather than describing the
    document it would write.

    This is not keyword routing, and it does not take the decision away from
    the assistant: `any` leaves the choice between `create_document`,
    `revise_document` and `convert_document` entirely open. What it removes is
    the fourth option — announcing the work and doing none of it — which is
    what a real model did on the first live run, twice, leaving a thread that
    read like success and a workspace with no file in it.

    Only the FIRST turn is constrained. Once a tool has run, the assistant
    needs to be free to report what happened in prose.
    """
    tools = list(tools or [])
    by_name = {t.name: t for t in tools}

    role = role_config.role(role_config.AUTHOR)
    model = role.model or ""
    if not model:
        raise provider.ProviderNotConfigured(
            "AUTHOR_MODEL_NOT_CONFIGURED: no assistant model is configured. "
            "Set AI_AUTHOR_MODEL (or AI_ANALYST_MODEL, or AI_MODEL, which it "
            "inherits from in that order). Existing workspaces, sources and "
            "generated files stay readable without one."
        )

    client = provider._client()
    started = time.monotonic()
    reply = Reply(model_requested=model)
    convo = list(messages)
    declared = [t.declaration() for t in tools]
    used_a_tool = False

    for turn in range(1, MAX_TOOL_TURNS + 1):
        if is_cancelled and is_cancelled():
            raise provider.Cancelled("This message was stopped.")
        provider._check_clock(started, f"starting turn {turn}")

        # First turn only, and only when the caller declared document work.
        # After a tool has run the assistant must be free to answer in prose;
        # forcing a tool on every turn would loop it forever.
        choice = ({"type": "any"}
                  if require_tool and declared and turn == 1 and not used_a_tool
                  else None)
        response = provider._call(
            client, model=model, system=system, messages=convo,
            tools=declared, container={}, purpose=purpose, role=role,
            on_delta=on_delta, on_thinking=on_thinking,
            is_cancelled=is_cancelled, deadline=started,
            with_tools=bool(declared), tool_choice=choice)
        reply.turns = turn

        rid = getattr(response, "_request_id", "") or ""
        if rid:
            reply.request_ids.append(rid)
        usage = getattr(response, "usage", None)
        if usage:
            reply.input_tokens += getattr(usage, "input_tokens", 0) or 0
            reply.output_tokens += getattr(usage, "output_tokens", 0) or 0
        served = getattr(response, "model", "") or ""
        if served:
            reply.model_served = served

        stop = provider.stop_reason_of(response)
        reply.stop_reason = stop
        text = provider._text(response)
        if text:
            # Each turn's text is appended, not replaced: an assistant that
            # says "I will create that now", calls a tool and then reports the
            # result has said two things, and the user needs both.
            reply.text = f"{reply.text}\n\n{text}".strip() if reply.text else text

        if stop == "refusal":
            raise provider.AuthoringError(
                "The assistant declined this request.", category="refusal")

        uses = _tool_uses(response)
        if stop != "tool_use" or not uses:
            if stop == "max_tokens":
                reply.interrupted = True
                break
            # The turn is over as far as the model is concerned. Before
            # accepting that, check the one thing the product forbids: a
            # message that describes a document nobody made. One correction,
            # once, and only when a tool was available to call and none has
            # run. A false positive costs exactly one bounded call; the
            # alternative is what happened live — an answer that reads like
            # success beside an empty Files panel.
            if (declared and not used_a_tool and not reply.nudged
                    and promised_a_document(text)):
                reply.nudged = True
                convo.append({"role": "assistant",
                              "content": response.content})
                convo.append({"role": "user", "content": _NOT_DONE})
                continue
            break

        used_a_tool = True
        convo.append({"role": "assistant", "content": response.content})
        results = []
        for use in uses:
            name = getattr(use, "name", "")
            args = getattr(use, "input", None) or {}
            tool = by_name.get(name)
            if tool is None:
                # The model asked for something that is not on offer. Told
                # plainly rather than silently dropped, so it can choose
                # differently instead of waiting for a result that never comes.
                results.append(_result_block(
                    use, {"error": f"No tool named {name!r} is available."},
                    ok=False))
                reply.tool_runs.append(
                    ToolRun(name=name, request=dict(args), ok=False,
                            detail="not available"))
                continue

            if on_tool:
                on_tool(name, "running")
            try:
                produced = tool.run(dict(args))
                run = ToolRun(name=name, request=dict(args), ok=True,
                              result=produced or {})
                results.append(_result_block(use, produced or {}, ok=True))
            except (provider.Cancelled, provider.AuthoringTimeout,
                    provider.ProviderNotConfigured):
                # A failure of the RUNTIME, not of this tool. Reporting it to
                # the model as a tool result would spend another provider call
                # to explain a deadline already exceeded, a stop the user
                # asked for, or a credential that does not exist. The broad
                # `except` below would otherwise contain all three, which is
                # how a hard timeout quietly became a chat message saying the
                # document could not be made.
                raise
            except ToolFailed as exc:
                run = ToolRun(name=name, request=dict(args), ok=False,
                              detail=str(exc))
                results.append(_result_block(use, {"error": str(exc)},
                                             ok=False))
            except Exception as exc:  # noqa: BLE001 - reported, never swallowed
                # An unexpected failure inside a tool is still just a failed
                # tool. The turn keeps the answer; the logs keep the traceback.
                logger.exception("Playbook tool %s failed", name)
                run = ToolRun(name=name, request=dict(args), ok=False,
                              detail=f"{type(exc).__name__}: {exc}")
                results.append(_result_block(
                    use, {"error": "The tool failed. "
                                   "The conversation is unaffected."}, ok=False))
            reply.tool_runs.append(run)
            if on_tool:
                on_tool(name, "done" if run.ok else "failed")

        convo.append({"role": "user", "content": results})
    else:
        # Out of turns with tools still being called. The work done so far is
        # kept — chapter 07 forbids discarding completed sections and
        # artifacts because a later step did not converge.
        reply.interrupted = True
        reply.text = (reply.text or "").strip()

    reply.promised_document = promised_a_document(reply.text)
    reply.made_document = any(r.ok for r in reply.tool_runs)
    if reply.broke_its_promise:
        logger.warning(
            "Playbook turn described a document and called no tool "
            "(nudged=%s, stop=%s).", reply.nudged, reply.stop_reason)

    reply.provider_ms = int((time.monotonic() - started) * 1000)
    if reply.downgraded:
        logger.warning("Playbook chat requested %s and was served %s.",
                       reply.model_requested, reply.model_served)
    return reply
