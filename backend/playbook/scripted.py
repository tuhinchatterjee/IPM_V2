"""
A deterministic stand-in for the provider, for acceptance runs.

Why this exists
---------------
The Direct Chat specification asks for the conversation to be exercised in a
real browser (chapter 31), and separately forbids paid calls without an agreed
budget. Those two things can only both hold if the running server can be given
a scripted assistant — otherwise "verified in the browser" can only ever mean
"verified that the interface refuses to generate".

What keeps it honest
--------------------
It is off unless `PLAYBOOK_SCRIPTED_CHAT` names a readable JSON file, it logs a
warning every time it answers, and `provider.status()` reports `scripted=True`
so the capability endpoint says so out loud. A deployment cannot drift into it
by accident, and an operator looking at diagnostics cannot mistake it for a
model.

The script format
-----------------
A JSON object mapping a substring of the user's message to a reply:

    {
      "default": {"say": "I am not sure."},
      "difference between": {"say": "A development report explains…"},
      "write the report": {
        "say": "The report is ready.",
        "create": {"formats": ["docx", "pdf"],
                   "markdown": "# Report\\n\\n## 1. Scope\\n\\n…"}
      }
    }

`say` is what the assistant says. `create` makes it call `create_document`
with that instruction, and the document itself comes from `markdown` — which
is the same seam `tests/playbook/conftest.py` uses, so a browser journey and a
unit test can be written against the same fixture.
"""

from __future__ import annotations

import json
import logging
import os
import pathlib
from typing import Any

logger = logging.getLogger(__name__)

#: The file naming the scripted replies. Absent means this module does nothing.
SCRIPT_PATH = (os.environ.get("PLAYBOOK_SCRIPTED_CHAT") or "").strip()


def enabled() -> bool:
    return bool(SCRIPT_PATH) and pathlib.Path(SCRIPT_PATH).is_file()


def _script() -> dict:
    try:
        return json.loads(pathlib.Path(SCRIPT_PATH).read_text())
    except Exception:  # noqa: BLE001 — a broken script must not crash a server
        logger.exception("Playbook scripted chat could not read %s", SCRIPT_PATH)
        return {}


def _match(script: dict, messages: list[dict]) -> dict:
    """The entry for this turn, by substring of the last user message."""
    last = ""
    for message in reversed(messages):
        if message.get("role") == "user" and isinstance(message.get("content"), str):
            last = message["content"].lower()
            break
    for key, entry in script.items():
        if key != "default" and key.lower() in last:
            return entry
    return script.get("default") or {"say": "Scripted assistant: no match."}


class _Block:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class _Response:
    def __init__(self, content, stop_reason, model):
        self.content = content
        self.stop_reason = stop_reason
        self.model = model
        self._request_id = "req_scripted_acceptance"
        self.usage = type("U", (), {"input_tokens": 0, "output_tokens": 0})()


#: The entry matched for the turn in flight, so a fault named in the script
#: can be applied deeper in the stack than the conversation reaches — a format
#: that will not validate, a tool that fails, a dashboard that is down.
#: Acceptance-only state, and it exists because the alternative is a browser
#: suite that can only ever test the happy path.
_CURRENT: dict = {}


def faults() -> dict:
    return dict(_CURRENT)


def call(client: Any, *, model: str, system: str, messages: list[dict],
         tools: list[dict], container: dict, purpose: str, role: Any,
         on_delta=None, is_cancelled=None, deadline=None,
         with_tools: bool = False) -> Any:
    """Stand in for `provider._call`. Same signature, no network."""
    logger.warning(
        "Playbook is answering from a SCRIPTED assistant (%s). "
        "No model was called.", SCRIPT_PATH)
    if is_cancelled and is_cancelled():
        from backend.playbook import provider

        raise provider.Cancelled("stopped")

    entry = _match(_script(), messages)
    _CURRENT.clear()
    _CURRENT.update(entry)

    if entry.get("interrupt"):
        # Chapter 07: a turn the model did not finish. The partial text is
        # returned and labelled, never presented as an answer.
        said = entry.get("say") or "The coverage ratio moved because"
        if on_delta:
            on_delta(said)
        return _Response([_Block(type="text", text=said)], "max_tokens",
                         model or "scripted-assistant")

    used_a_tool = any(
        isinstance(m.get("content"), list)
        and any(isinstance(b, dict) and b.get("type") == "tool_result"
                for b in m["content"])
        for m in messages)

    # Which tool this entry reaches for, if any. One key per tool, so a
    # fixture reads as what the assistant decided to do.
    offered = {t.get("name") for t in (tools or [])}
    plan = next(((key, tool) for key, tool in
                 (("create", "create_document"),
                  ("revise", "revise_document"),
                  ("convert", "convert_document"))
                 if entry.get(key) and tool in offered), None)

    if plan and not used_a_tool:
        key, tool_name = plan
        spec = entry[key]
        arguments: dict[str, Any] = {
            "formats": spec.get("formats", ["docx", "pdf"])}
        if tool_name != "convert_document":
            arguments["instruction"] = spec.get("instruction", "as asked")
        if spec.get("scope"):
            arguments["scope"] = spec["scope"]

        opening = entry.get("opening") or "I will prepare that now."
        if on_delta:
            on_delta(opening)
        return _Response(
            [_Block(type="text", text=opening),
             _Block(type="tool_use", name=tool_name, id="tu_scripted",
                    input=arguments)],
            "tool_use", model or "scripted-assistant")

    said = entry.get("say") or "Done."
    if on_delta:
        # In pieces, like the real stream, so a browser journey that asserts
        # text arriving before the turn ends is testing something.
        for i in range(0, len(said), 24):
            if is_cancelled and is_cancelled():
                from backend.playbook import provider

                raise provider.Cancelled("stopped")
            on_delta(said[i:i + 24])
    return _Response([_Block(type="text", text=said)], "end_turn",
                     model or "scripted-assistant")


def author(*, system: str, messages: list[dict], formats: list[str], **kw) -> Any:
    """Stand in for `provider.author`, for the document a tool asks for."""
    from backend.playbook import provider

    # The document comes from the entry that is in flight, so a revision
    # returns the revised text rather than the text of whichever entry
    # happened to be first in the file.
    current = _CURRENT or _match(
        _script(), [{"role": "user", "content": kw.get("instruction", "")}])
    markdown = ""
    for key in ("revise", "create"):
        candidate = (current.get(key) or {}).get("markdown")
        if candidate:
            markdown = candidate
            break
    if _CURRENT.get("tool_error"):
        # A document that could not be written. The conversation survives it
        # and the assistant explains — chapter 07's three outcomes.
        raise provider.AuthoringError(str(_CURRENT["tool_error"]),
                                      category="empty_output")
    logger.warning("Playbook is AUTHORING from a scripted document.")
    return provider.AuthoringResult(
        text=markdown or "# Report\n\n## 1. Scope\n\nScripted content.\n",
        files=[], model_requested=kw.get("model", "scripted-assistant"),
        model_served="scripted-assistant",
        request_ids=["req_scripted_acceptance"], turns=1)


def install() -> bool:
    """Replace the provider's call sites. Returns whether it did."""
    if not enabled():
        return False
    from backend.playbook import provider

    # A scripted server is a configured server: it will answer. The runtime
    # checks for a model before it does anything, and leaving that unset made
    # every scripted turn fail with AUTHOR_MODEL_NOT_CONFIGURED — technically
    # true and useless. The name is deliberately not a real model id, so
    # anything that records what served a turn records the truth.
    os.environ.setdefault("AI_AUTHOR_MODEL", "scripted-assistant")

    provider._call = call            # type: ignore[assignment]
    provider._client = lambda: object()  # type: ignore[assignment]
    provider.author = author         # type: ignore[assignment]

    _install_faults()
    logger.warning(
        "Playbook SCRIPTED CHAT is active from %s. Every answer and document "
        "on this server is fixture content, not a model's.", SCRIPT_PATH)
    return True


def _install_faults() -> None:
    """Let the script break one format, or the dashboard, on purpose.

    Both failures have to be reachable from a browser or the journeys that
    matter most — a PDF that fails while Word survives, a status projection
    that is down while files still download — can only ever be asserted in a
    unit test. Each wraps the real function and defers to it unless the
    matched script entry asked for the failure.
    """
    from backend.playbook import service, validate
    from backend.playbook.intelligence import adopt

    real_validate = validate.validate

    def validate_with_faults(content: bytes, fmt: str, doc: Any) -> Any:
        broken = {f.lower() for f in (_CURRENT.get("fail_formats") or [])}
        if fmt.lower() in broken:
            result = validate.Validation(format=fmt)
            result.fail(
                f"the generated file could not be reopened: scripted fault "
                f"for {fmt}", integrity=True)
            return result
        return real_validate(content, fmt, doc)

    validate.validate = validate_with_faults          # type: ignore[assignment]
    service.validate.validate = validate_with_faults  # type: ignore[assignment]

    real_adopt = adopt.adopt

    def adopt_with_faults(*args: Any, **kw: Any) -> Any:
        if _CURRENT.get("break_dashboard"):
            raise RuntimeError("scripted fault: the status indexer is down")
        return real_adopt(*args, **kw)

    adopt.adopt = adopt_with_faults                   # type: ignore[assignment]
