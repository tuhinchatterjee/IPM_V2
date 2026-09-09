"""
The authoring runtime. Playbook §10.

Why this is not `backend.llm`
-----------------------------
`backend/llm/base.py` states its own contract in its docstring: one method, a
schema-constrained call, and a reply that does not conform is an ERROR rather
than something to salvage. It also says, in as many words, why it does not
stream — nothing downstream can begin until the whole plan is known. That
contract is what makes every figure in CreditProbe defensible and it must not be
loosened to let Playbook write prose through it.

Playbook needs the opposite shape: long-form output, many turns, server-side
code execution, document Skills, streaming and cancellation. So it gets its own
runtime — and reuses everything about `backend.llm` that is configuration rather
than contract: the role catalogue, the no-silent-substitution rule, the
telemetry ledger, and the secret redaction those already implement.

What the model is and is not trusted with
-----------------------------------------
It writes. It structures. It argues. It drives the document tools.

It does not supply figures. Every number reaching a document comes from an
export snapshot, a located source chunk, or `backend.playbook.calc`, and
`backend.playbook.grounding` checks the draft against that ledger afterwards.
The container has no network access, is given no credential, and receives source
documents only through file ids this process created — never one supplied by a
caller, because the Files API is workspace-scoped and one user's file id would
otherwise read another user's upload.

Configured, not remembered
--------------------------
No model id is written down here. The id comes from the AUTHOR role, and the id
the provider actually served is recorded on every result so a claim about which
model wrote a report can be checked rather than believed. A configured model the
provider cannot serve is a loud configuration failure, never a quiet fall back
to a cheaper one.
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from backend.llm import roles as role_config
from backend.llm import telemetry
from backend.playbook import capabilities

logger = logging.getLogger(__name__)

#: The code-execution tool version this integration is written against. Declared
#: here rather than inline so an upgrade is one deliberate edit with one place to
#: re-test. No `anthropic-beta` header is required for any current version.
CODE_EXECUTION_TOOL = "code_execution_20260120"

#: Where the container writes what it produces. Anything outside it is ignored.
WORKDIR = "/tmp/outputs"

#: Bounds. A loop that can run for ever is not a control, and neither is a
#: prompt asking the model to be brief.
MAX_TURNS = int(os.environ.get("PLAYBOOK_MAX_TURNS") or 24)
MAX_OUTPUT_TOKENS = int(os.environ.get("PLAYBOOK_MAX_OUTPUT_TOKENS") or 16000)

#: The wall-clock ceiling on ONE authoring run, across every turn it takes.
#:
#: This is the bound that actually matters, and the one that was missing. A
#: socket timeout bounds *inactivity between reads*, not the operation: a stream
#: that produces one token every two minutes never trips a read timeout and runs
#: until somebody presses Ctrl+C. That is exactly what happened on the first
#: live run. This deadline is checked between stream events and between turns,
#: so a slow-but-alive generation is stopped like any other.
#:
#: Deliberately below `stream.IDLE_TIMEOUT_SECONDS` (900), so the worker always
#: reports the failure before the reader watching it gives up.
RUN_DEADLINE_SECONDS = float(os.environ.get("PLAYBOOK_TIMEOUT_SECONDS") or 600)

#: The four transport phases, separately. Passing a bare float here sets all
#: four to that number — which is how a 900-second CONNECT timeout got shipped.
#: Named individually so each one means what it says.
CONNECT_TIMEOUT_SECONDS = float(
    os.environ.get("PLAYBOOK_CONNECT_TIMEOUT_SECONDS") or 10)
#: Silence on an open stream. Long enough for a slow tool call to think, short
#: enough that a dead connection is noticed in minutes rather than a quarter of
#: an hour.
READ_TIMEOUT_SECONDS = float(
    os.environ.get("PLAYBOOK_READ_TIMEOUT_SECONDS") or 120)
WRITE_TIMEOUT_SECONDS = float(
    os.environ.get("PLAYBOOK_WRITE_TIMEOUT_SECONDS") or 60)
POOL_TIMEOUT_SECONDS = float(
    os.environ.get("PLAYBOOK_POOL_TIMEOUT_SECONDS") or 30)

#: Retries cover a transport hiccup and an overloaded provider. Nothing else is
#: retried: a provider that retries a refusal turns one problem into three.
MAX_ATTEMPTS = 3

#: How long an uploaded source stays in the provider's workspace. Bounded so
#: evidence does not accumulate there indefinitely; the durable copy is ours.
SOURCE_FILE_TTL_SECONDS = 24 * 3600

#: Whether the authoring call also asks the provider's document Skills to write
#: the binary files, inside the same streamed run.
#:
#: OFF by default, and the reason is measured rather than aesthetic. With it on,
#: one call authors the report AND drives server-side code execution to build
#: the DOCX and PDF. While the sandbox runs there are no text deltas, so the
#: stream goes silent for minutes and trips the read timeout — a live run failed
#: at 281 seconds exactly that way. Worse, when grounding then removes a figure
#: those files are discarded wholesale and re-rendered locally, so the wait was
#: paid for and thrown away.
#:
#: With it off the authoring call is pure text, which is what makes a read
#: timeout meaningful, and `backend/playbook/render/` produces every format
#: deterministically from the approved document. The Skills path is kept because
#: it is a real capability worth demonstrating — it is simply not on the path a
#: user waits on.
SKILL_RENDERING = (os.environ.get("PLAYBOOK_SKILL_RENDERING") or "").strip().lower() in {
    "1", "true", "yes", "on"}

#: The read timeout when document Skills ARE enabled. Longer, because silence
#: during sandbox execution is expected there rather than a symptom.
SKILL_READ_TIMEOUT_SECONDS = float(
    os.environ.get("PLAYBOOK_SKILL_READ_TIMEOUT_SECONDS") or 420)


class ProviderNotConfigured(RuntimeError):
    """No usable provider. The message is an instruction, not an apology."""


class AuthoringError(RuntimeError):
    """The authoring call failed. `category` is telemetry's classification."""

    def __init__(self, message: str, *, category: str = "") -> None:
        super().__init__(message)
        self.category = category


class AuthoringTimeout(AuthoringError):
    """The run exceeded its wall-clock deadline and was stopped.

    A subclass rather than a bare category so a caller can catch it precisely.
    It is never retried automatically: a timed-out generation has already spent
    its tokens, and trying again on the product's own initiative spends them a
    second time without anybody asking. The user has a retry button.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message, category="timeout")


class Cancelled(RuntimeError):
    """The user stopped this generation."""


@dataclass
class GeneratedFile:
    """A file the container produced, before it has been persisted."""

    file_id: str
    filename: str
    content: bytes

    @property
    def format(self) -> str:
        return self.filename.rsplit(".", 1)[-1].lower() if "." in self.filename else ""


@dataclass
class AuthoringResult:
    """What one authoring run produced, and what it cost.

    `model_served` is what the provider says answered, which is not necessarily
    what was configured. Keeping both is the whole of PB-030: a downgrade that
    nobody records is a downgrade that nobody notices.
    """

    text: str = ""
    files: list[GeneratedFile] = field(default_factory=list)
    model_requested: str = ""
    model_served: str = ""
    request_ids: list[str] = field(default_factory=list)
    container_id: str = ""
    turns: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    milestones: list[dict] = field(default_factory=list)
    stop_reason: str = ""
    #: Wall clock inside the provider — every attempt of every turn, summed.
    #: Named for what it measures rather than "latency", because the authoring
    #: run around it and the check around that are different spans.
    provider_ms: int = 0
    #: How many times the model asked to use a tool. Zero when the document
    #: tools are off, which is the default and the whole point of the split.
    tool_calls: int = 0

    @property
    def downgraded(self) -> bool:
        """True when the provider served something other than what was asked
        for. Never suppressed — surfaced, so a report carries an honest note."""
        if not self.model_requested or not self.model_served:
            return False
        return not self.model_served.startswith(self.model_requested.split("-latest")[0])

    def usage(self) -> dict:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "turns": self.turns,
            "model_requested": self.model_requested,
            "model_served": self.model_served,
            "downgraded": self.downgraded,
        }


@dataclass(frozen=True)
class Status:
    """Whether authoring can run at all, said plainly and without a key."""

    configured: bool
    reason: str = ""
    provider: str = ""
    model: str = ""
    inherited: bool = True

    def as_dict(self) -> dict:
        return {
            "configured": self.configured,
            "reason": self.reason,
            "provider": self.provider,
            "model": self.model,
            "model_inherited": self.inherited,
        }


def status() -> Status:
    """What an administrator needs to know, with nothing secret in it."""
    from backend.config import settings

    provider = (settings.ai_provider or "").strip().lower()
    author = role_config.role(role_config.AUTHOR)

    if provider in ("", "none", "offline"):
        return Status(
            False,
            "AI_PROVIDER is set to offline, so Playbook will not call a model. "
            "Seeded workspaces and their files remain browseable.",
            provider, author.model, author.inherited,
        )
    if provider != "anthropic":
        return Status(
            False,
            f"Playbook's authoring runtime supports the Anthropic provider; "
            f"AI_PROVIDER is {provider!r}.",
            provider, author.model, author.inherited,
        )
    if not (settings.anthropic_api_key or "").strip():
        return Status(
            False,
            "ANTHROPIC_API_KEY is not set. Set it in the deployment's "
            "environment to enable Playbook generation. Existing workspaces, "
            "sources and files stay readable without it.",
            provider, author.model, author.inherited,
        )
    if not (author.model or "").strip():
        # A key with no model is not a working configuration. The Messages API
        # has no server-side default, so this used to report CONFIGURED and
        # then fail inside the SDK on the first call. Reported here instead,
        # where an administrator can act on it.
        return Status(
            False,
            "AUTHOR_MODEL_NOT_CONFIGURED: no authoring model is configured. "
            "Set AI_AUTHOR_MODEL, or AI_ANALYST_MODEL or AI_MODEL for it to "
            "inherit from. Existing workspaces, sources and files stay "
            "readable without one.",
            provider, author.model, author.inherited,
        )
    return Status(True, "", provider, author.model, author.inherited)


def _client() -> Any:
    from backend.config import settings

    state = status()
    if not state.configured:
        raise ProviderNotConfigured(state.reason)
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover - declared dependency
        raise ProviderNotConfigured("The anthropic SDK is not installed.") from exc
    import httpx

    return anthropic.Anthropic(
        api_key=settings.anthropic_api_key,
        # Four phases, separately. A bare float sets all four to the same
        # number, which is how this shipped with a 900-second connect timeout:
        # httpx collapses `timeout=900.0` to `Timeout(timeout=900.0)`.
        timeout=httpx.Timeout(
            connect=CONNECT_TIMEOUT_SECONDS,
            read=READ_TIMEOUT_SECONDS,
            write=WRITE_TIMEOUT_SECONDS,
            pool=POOL_TIMEOUT_SECONDS,
        ),
        max_retries=0,  # retries are handled here, where they can be recorded
    )


#: Where `_stream_once` leaves the request id for the attempt it is running, so
#: that a FAILURE can report it too. Read from the response alone, a failed
#: attempt has no response and the ledger logged `request_id=-` for every one of
#: them — which is most of what a request id is for.


def _check_clock(started: float | None, doing: str) -> None:
    """Stop a run that has outlived its deadline, naming what it was doing.

    Follows `backend/exports/service.py`'s `_check_clock`: the phase is in the
    message because "it timed out" sends somebody looking in the wrong place,
    and "it timed out while building the files" does not.
    """
    # `not started` rather than `started is None`. 0.0 is falsy but not None,
    # and a 0.0 origin would make this measure `time.monotonic()` itself —
    # container uptime — so any process older than the deadline would be
    # declared timed out on its first event, and the number reported as a
    # provider latency would be the age of the process. That is exactly the
    # shape of the 1636923 ms recorded against a 281-second attempt.
    if not started or started <= 0:
        return
    elapsed = time.monotonic() - started
    if elapsed > RUN_DEADLINE_SECONDS:
        raise AuthoringTimeout(
            f"This generation passed its {RUN_DEADLINE_SECONDS:.0f}-second "
            f"limit while {doing} ({elapsed:.0f}s elapsed), so it was stopped. "
            "Nothing was saved and the previous version is unchanged."
        )


def upload_source(filename: str, content: bytes, mime: str) -> str:
    """Put one source document in the provider's workspace, and return its id.

    Server-side only. The returned id is stored against our own source row and
    never accepted back from a client: the Files API is scoped to the workspace,
    not to an end user, so honouring a caller-supplied id would let one user
    read another's document.
    """
    client = _client()
    uploaded = client.beta.files.upload(
        file=(filename, content, mime),
        extra_body={"expires_in_seconds": SOURCE_FILE_TTL_SECONDS},
    )
    return uploaded.id


def stop_reason_of(response: Any) -> str:
    return getattr(response, "stop_reason", "") or ""


def _skills(formats: list[str]) -> list[dict]:
    wanted, seen = [], set()
    for fmt in formats:
        cap = capabilities.require(fmt)
        skill_id = capabilities.SKILL_ID[cap.format]
        if skill_id not in seen:
            seen.add(skill_id)
            wanted.append({"type": "anthropic", "skill_id": skill_id,
                           "version": "latest"})
    return wanted


def _file_ids(response: Any) -> list[str]:
    """Ids of the files the container produced during this turn.

    They arrive inside `bash_code_execution_tool_result` blocks. The shape is
    walked defensively: a provider that adds a field must not break authoring,
    and a block we do not recognise is skipped rather than guessed at.
    """
    found: list[str] = []
    for block in getattr(response, "content", []) or []:
        if getattr(block, "type", "") != "bash_code_execution_tool_result":
            continue
        content = getattr(block, "content", None)
        inner = getattr(content, "content", None) or []
        for item in inner:
            fid = getattr(item, "file_id", None)
            if fid:
                found.append(fid)
    return found


def _text(response: Any) -> str:
    return "\n".join(
        getattr(b, "text", "") for b in (getattr(response, "content", []) or [])
        if getattr(b, "type", "") == "text"
    ).strip()


def download(client: Any, file_id: str) -> GeneratedFile:
    """Fetch a generated file's bytes into this process.

    Called before a job may complete. A file card pointing at a container that
    has since expired is not a deliverable, so the bytes come here first and go
    to durable storage immediately afterwards.
    """
    meta = client.beta.files.retrieve_metadata(file_id)
    payload = client.beta.files.download(file_id)
    content = payload.read() if hasattr(payload, "read") else bytes(payload)
    return GeneratedFile(file_id=file_id,
                         filename=getattr(meta, "filename", "") or file_id,
                         content=content)


def author(
    *,
    system: str,
    messages: list[dict],
    formats: list[str],
    purpose: str = "playbook_authoring",
    container_id: str = "",
    on_milestone: Callable[[str, str], None] | None = None,
    on_delta: Callable[[str], None] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
    document_tools: bool | None = None,
) -> AuthoringResult:
    """Run one authoring turn to completion, including its tool-use loop.

    Returns when the model stops, or raises. The loop is bounded by MAX_TURNS,
    checks for cancellation between turns, and downloads every produced file
    before returning so that nothing depends on a container that will expire.

    `on_delta` receives the answer text as it arrives, and NOTHING else. The
    provider's stream also carries reasoning blocks, tool inputs and the code
    the sandbox is about to run; those are not forwarded — only `text_delta` on
    a `text` block is. Cancellation is checked between deltas as well as
    between turns, so stopping does not wait for a long reply to finish.

    The whole run is bounded by `RUN_DEADLINE_SECONDS` of wall-clock, checked
    between stream events and between turns.
    """
    role = role_config.role(role_config.AUTHOR)
    model = role.model or ""
    if not model:
        # Checked BEFORE the client is built, so no call is ever made without
        # one. The Messages API has no server-side default model — omitting the
        # field is an error, not a fallback — so the comment that used to sit
        # here, claiming "the provider's own default", was simply wrong, and the
        # SDK raised `missing 1 required keyword-only argument: 'model'` at the
        # worst possible moment instead.
        raise ProviderNotConfigured(
            "AUTHOR_MODEL_NOT_CONFIGURED: no authoring model is configured. "
            "Set AI_AUTHOR_MODEL (or AI_ANALYST_MODEL, or AI_MODEL, which it "
            "inherits from in that order). Existing workspaces, sources and "
            "generated files stay readable without one."
        )

    client = _client()
    started = time.monotonic()

    # Document tools are off unless a deployment asks for them. See
    # SKILL_RENDERING: with them on, this one call both writes the report and
    # builds the files, and the silence while the sandbox works is what trips
    # the read timeout.
    with_tools = SKILL_RENDERING if document_tools is None else document_tools
    tools: list[dict] = []
    container: dict[str, Any] = {}
    if with_tools:
        tools = [{"type": CODE_EXECUTION_TOOL, "name": "code_execution"}]
        container = {"skills": _skills(formats)}
        if container_id:
            container["id"] = container_id

    result = AuthoringResult(model_requested=model)
    convo = list(messages)

    def milestone(state: str, detail: str = "") -> None:
        # Monotonic, not wall clock: a machine that adjusts its time mid-run
        # must not produce a milestone that happened before the one before it.
        entry = {"state": state, "detail": detail,
                 "at": round(time.monotonic() - started, 3)}
        result.milestones.append(entry)
        if on_milestone:
            on_milestone(state, detail)

    milestone("reviewing_sources")

    for turn in range(1, MAX_TURNS + 1):
        if is_cancelled and is_cancelled():
            raise Cancelled("This generation was stopped.")
        _check_clock(started, f"starting turn {turn}")

        response = _call(client, model=model, system=system, messages=convo,
                         tools=tools, container=container, purpose=purpose,
                         role=role, on_delta=on_delta,
                         is_cancelled=is_cancelled, deadline=started,
                         with_tools=with_tools)
        result.turns = turn

        rid = getattr(response, "_request_id", "") or ""
        if rid:
            result.request_ids.append(rid)
        usage = getattr(response, "usage", None)
        if usage:
            result.input_tokens += getattr(usage, "input_tokens", 0) or 0
            result.output_tokens += getattr(usage, "output_tokens", 0) or 0
        served = getattr(response, "model", "") or ""
        if served:
            result.model_served = served
        cont = getattr(response, "container", None)
        if cont is not None and getattr(cont, "id", ""):
            result.container_id = cont.id
            container["id"] = cont.id

        if stop_reason_of(response) == "tool_use":
            result.tool_calls += 1
        for fid in _file_ids(response):
            if fid not in {f.file_id for f in result.files}:
                milestone("rendering", fid)
                result.files.append(download(client, fid))

        stop = getattr(response, "stop_reason", "") or ""
        result.stop_reason = stop
        text = _text(response)
        if text:
            result.text = text

        if stop == "pause_turn":
            # A long-running skill asked for more time. Continue the same turn
            # with the same container rather than starting again.
            convo.append({"role": "assistant", "content": response.content})
            milestone("drafting", "continuing a paused turn")
            continue
        if stop == "tool_use":
            convo.append({"role": "assistant", "content": response.content})
            # Code execution is served by the provider, so there is no local
            # tool result to append; asking it to carry on is enough.
            convo.append({"role": "user",
                          "content": "Continue. When every requested file has "
                                     "been written, summarise what you produced."})
            milestone("drafting", f"turn {turn}")
            continue
        if stop == "refusal":
            raise AuthoringError(
                "The model declined this request. Nothing was generated.",
                category="refusal")
        break
    else:
        raise AuthoringError(
            f"Authoring did not finish within {MAX_TURNS} turns. Nothing was "
            "marked complete.", category="budget")

    result.provider_ms = int((time.monotonic() - started) * 1000)
    milestone("validating")
    if result.downgraded:
        logger.warning(
            "Playbook authoring requested %s and was served %s.",
            result.model_requested, result.model_served)
    return result


def _call(client: Any, *, model: str, system: str, messages: list[dict],
          tools: list[dict], container: dict, purpose: str, role: Any,
          on_delta: Callable[[str], None] | None = None,
          is_cancelled: Callable[[], bool] | None = None,
          deadline: float | None = None,
          with_tools: bool = False) -> Any:
    """One provider call, with bounded retries and honest telemetry.

    Streamed, always. The completed message is still what the caller gets back —
    stop reason, container, usage, file ids and all — so nothing downstream
    changes; streaming adds the text arriving as it is written rather than
    replacing the result with a pile of fragments.

    A stream is never retried after the first delta has been forwarded. Retrying
    then would replay text the user has already read, and a second copy of half
    an answer is worse than the failure.
    """

    last: Exception | None = None
    emitted = False
    for attempt in range(1, MAX_ATTEMPTS + 1):
        # Monotonic, like every other duration on this path. An epoch clock
        # that steps backwards mid-call produces a negative latency, and one
        # that steps forwards produces a fictional outage.
        began = time.monotonic()
        seen: dict = {"request_id": ""}
        try:
            kwargs: dict[str, Any] = {
                "max_tokens": MAX_OUTPUT_TOKENS,
                "messages": messages,
                "system": system,
            }
            # Omitted entirely rather than sent empty: an empty tools list is
            # still a request to consider tools, and a container with no skills
            # is a sandbox nobody asked to start.
            if with_tools and tools:
                kwargs["tools"] = tools
            if with_tools and container:
                kwargs["container"] = container
            if model:
                kwargs["model"] = model
            response, streamed = _stream_once(
                client, kwargs, on_delta=on_delta, is_cancelled=is_cancelled,
                deadline=deadline, with_tools=with_tools, seen=seen)
            if streamed:
                emitted = True
            telemetry.record_success(
                provider="anthropic",
                model=getattr(response, "model", "") or model,
                purpose=purpose, role=role_config.AUTHOR, effort=role.effort,
                latency_ms=int((time.monotonic() - began) * 1000),
                request_id=getattr(response, "_request_id", "") or "",
                attempts=attempt,
                input_tokens=getattr(getattr(response, "usage", None),
                                     "input_tokens", 0) or 0,
                output_tokens=getattr(getattr(response, "usage", None),
                                      "output_tokens", 0) or 0,
            )
            return response
        except Cancelled:
            # A stop is not a provider failure. It must not be classified,
            # retried, or reported as an outage.
            raise
        except AuthoringTimeout as exc:
            # Recorded before it is re-raised. Left unrecorded, the product's
            # own deadline breach — the likeliest timeout on this path — was
            # invisible to the ledger, so the only `timeout` rows anybody could
            # see came from elsewhere and were read as this.
            telemetry.record_failure(
                provider="anthropic", model=model, purpose=purpose,
                role=role_config.AUTHOR, effort=role.effort,
                latency_ms=int((time.monotonic() - began) * 1000),
                error=exc, category="timeout", attempts=attempt,
                request_id=seen["request_id"],
            )
            # Retrying would spend the deadline it has already exceeded, and
            # spend tokens again for a generation nobody is still waiting for.
            raise
        except Exception as exc:  # noqa: BLE001 — classified, then re-raised
            category = telemetry.classify(exc)
            telemetry.record_failure(
                provider="anthropic", model=model, purpose=purpose,
                role=role_config.AUTHOR, effort=role.effort,
                latency_ms=int((time.monotonic() - began) * 1000),
                error=exc, category=category, attempts=attempt,
                # Without this the ledger logged `request_id=-` for every
                # failure, so a failed attempt could not be taken to the
                # provider's own logs. anthropic_provider.py already does it.
                request_id=seen["request_id"],
            )
            last = exc
            # `timeout` is deliberately NOT here. A socket timeout means the
            # request was accepted and is being worked on somewhere; retrying
            # buys a second billable generation of the same turn on the chance
            # the first was merely slow. `connection` stays, because it fires
            # before any tokens are spent. The user has a retry button for the
            # rest — the product does not spend money on its own initiative.
            retryable = category in {"rate_limit", "overloaded", "server",
                                     "connection"}
            if emitted:
                # Text has already reached the user. Starting again would show
                # them a second beginning of the same answer.
                retryable = False
            if not retryable or attempt == MAX_ATTEMPTS:
                raise AuthoringError(
                    _message_for(category, exc), category=category
                ) from exc
            time.sleep(min(2 ** attempt, 8))
    raise AuthoringError(str(last) if last else "authoring failed")  # pragma: no cover


def _stream_once(client: Any, kwargs: dict, *,
                 on_delta: Callable[[str], None] | None,
                 is_cancelled: Callable[[], bool] | None,
                 deadline: float | None = None,
                 with_tools: bool = False,
                 seen: dict | None = None) -> tuple[Any, bool]:
    """One streamed call. Returns the finished message and whether text flowed.

    The filter is the security boundary of this module, and it is deliberately
    narrow: a delta is forwarded only when the event is a `content_block_delta`
    AND the delta is a `text_delta`. Reasoning (`thinking_delta`), its signature,
    and tool inputs (`input_json_delta` — which carries the code the sandbox is
    about to run) all fail that test and never leave this function.
    """
    forwarded = False
    if with_tools:
        # Silence is expected while the sandbox builds a file, so the per-read
        # ceiling is raised for this call only rather than globally.
        kwargs = {**kwargs, "timeout": SKILL_READ_TIMEOUT_SECONDS}
    with client.beta.messages.stream(**kwargs) as stream:
        # Captured as soon as the connection exists, before anything can go
        # wrong, so a failure mid-stream still knows which request it was.
        if seen is not None and stream.request_id:
            seen["request_id"] = stream.request_id
        for event in stream:
            # Checked per event, because this is the only place that can catch
            # a stream which is alive but going nowhere. A read timeout never
            # fires on one: every chunk resets it.
            _check_clock(deadline, "waiting for the model to finish writing")
            if is_cancelled and is_cancelled():
                # Close the connection rather than reading a reply nobody
                # wants. `stream` is a context manager, so this releases it.
                raise Cancelled("This generation was stopped.")
            if getattr(event, "type", "") != "content_block_delta":
                continue
            delta = getattr(event, "delta", None)
            if getattr(delta, "type", "") != "text_delta":
                continue
            text = getattr(delta, "text", "") or ""
            if text and on_delta:
                on_delta(text)
                forwarded = True
        message = stream.get_final_message()
        rid = stream.request_id or ""
    if rid and not getattr(message, "_request_id", ""):
        try:
            object.__setattr__(message, "_request_id", rid)
        except Exception:  # noqa: BLE001 — a model that refuses the attribute
            pass            # simply reports no request id, which is honest.
    return message, forwarded


def _message_for(category: str, exc: Exception) -> str:
    """A sentence an operator can act on, with nothing secret in it."""
    return {
        "auth": "The configured Anthropic credential was rejected. Playbook "
                "generation is unavailable until it is corrected.",
        "credit": "The Anthropic account has no available credit, so nothing "
                  "was generated.",
        "model_not_found": "The configured authoring model is not one this "
                           "account can serve. Playbook will not quietly use a "
                           "different model; correct AI_AUTHOR_MODEL.",
        "rate_limit": "The provider rate-limited this request after several "
                      "attempts. Nothing was generated; try again shortly.",
        "timeout": "The provider did not respond in time. Nothing was "
                   "generated and the previous version is unchanged.",
        "connection": "Playbook could not reach the provider. Nothing was "
                      "generated and the previous version is unchanged; check "
                      "network access from this deployment and try again.",
    }.get(category, telemetry.sanitise(str(exc)) or "The authoring call failed.")
