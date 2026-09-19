"""
One turn of the real Playbook conversation. Chapters 04, 05, 07 and 10.

This is what the user's message actually reaches. It assembles the turn —
history, attachments, exported analyses, the selected working artifact — hands
it to `assistant.converse` with the tools that turn can use, and records what
came back.

Why the document work is a tool rather than a branch
----------------------------------------------------
Chapter 04 forbids pre-routing every message into the authoring path, and
forbids a second Generate click. That leaves exactly one honest way to decide
whether a turn needs a file: ask the model, by giving it a tool and letting it
call one. A keyword match cannot tell "write me the report" from "what would go
in the report?", and both are ordinary things to say.

So an ordinary question costs one provider call and produces no file. A request
for a report costs that call plus the authoring call the tool makes — two calls
doing two different jobs, neither rewriting the other's output, which is the
separation chapter 08 describes. Nothing here re-interprets the assistant's
prose before the user sees it.
"""

from __future__ import annotations

import logging
from typing import Any

from backend.playbook import assistant, capabilities, provider
from backend.playbook import repository as repo

logger = logging.getLogger(__name__)

#: How many earlier messages travel with a turn. Chapter 15 asks for the
#: correct recent messages rather than the whole thread: a long Playbook would
#: otherwise resend a year of conversation on every "make this shorter".
HISTORY_TURNS = 20

#: Formats a document tool may be asked for, and what each is for. Declared
#: rather than inferred, so an unsupported request is refused by name instead
#: of producing a file nobody can open.
DOCUMENT_FORMATS = ("docx", "pdf", "pptx", "xlsx")


def _history(session, workspace_id: int) -> list[dict]:
    """The recent conversation, as the provider wants it.

    System-origin rows — "this generation was stopped", a recorded failure —
    are left out. They are true, and they belong in the thread a person reads,
    but replaying them to the model invites it to apologise for an error the
    user may never have seen.
    """
    out: list[dict] = []
    for row in repo.messages(session, workspace_id)[-HISTORY_TURNS:]:
        if row.origin == "system":
            continue
        text = (row.content or {}).get("text") or ""
        if not text.strip():
            continue
        out.append({"role": "user" if row.role == "user" else "assistant",
                    "content": text})
    return out


def _attachment_note(ledger, current) -> str:
    """What this turn has to work with, stated plainly.

    Chapter 05 is specific that "Available" must not be read as "every part was
    examined", so the coverage the ledger actually has is named here rather
    than implied.
    """
    parts: list[str] = []
    if current is not None:
        parts.append(
            f"The selected working artifact is version {current.version} of "
            f"this Playbook's document. Its current text follows, and an edit "
            f"should be made against it rather than written again from memory.")
    rendered = ledger.render() if ledger is not None else ""
    if rendered:
        parts.append(rendered)
    if ledger is not None and not ledger.complete:
        # Each omission is {"what", "why"}, and both halves matter: naming the
        # file without saying why it was skipped invites the assistant to
        # guess at its contents.
        parts.append(
            "Some attached material was not fully read: "
            + "; ".join(f"{o.get('what', '')} ({o.get('why', '')})"
                        for o in ledger.omissions)
            + ". Say so if the answer depends on it, rather than treating what "
              "is here as the whole of it.")
    return "\n\n".join(parts)


def _capability_note() -> str:
    """What the runtime can actually do today.

    Chapter 02 requires a capability to be Implemented, Available but disabled,
    or Not supported, and forbids a working-looking control with nothing behind
    it. The assistant is told the same thing, so it declines what is not there
    instead of describing it as done.
    """
    supported = ", ".join(sorted(capabilities.supported()))
    lines = [f"You can create files in these formats: {supported}."]
    if not provider.SKILL_RENDERING:
        lines.append(
            "Documents are rendered by CreditProbe's own renderer, not in a "
            "sandbox. Do not offer to run code.")
    # Read from the registry rather than restated here, so the sentence the
    # assistant is given and the row `GET /playbook/capabilities` publishes
    # cannot drift apart. Two places saying what the product cannot do is one
    # place too many.
    lines.append(
        "You cannot do the following, and must say so plainly if asked "
        "rather than implying it happened: "
        + " ".join(capabilities.NOT_SUPPORTED[name]
                   for name in sorted(capabilities.NOT_SUPPORTED)))
    return " ".join(lines)


class _Documents:
    """The document tools for one turn, bound to its workspace.

    Each returns a plain dict the model can read, and raises `ToolFailed` when
    it cannot do what was asked. Neither outcome ends the turn: chapter 07
    requires that a failed conversion still leaves the answer and any other
    format standing.
    """

    def __init__(self, session, scope, ws, *, artifact_id=None,
                 base_version_id=None, ledger=None, on_milestone=None,
                 is_cancelled=None):
        self.session = session
        self.scope = scope
        self.ws = ws
        self.artifact_id = artifact_id
        self.base_version_id = base_version_id
        self.ledger = ledger
        self.on_milestone = on_milestone
        self.is_cancelled = is_cancelled
        #: Every version this turn wrote, in order, for the projection that
        #: runs after the commit. A turn may write more than one.
        self.projections: list[dict] = []
        self.produced: list[dict] = []

    # -- helpers ---------------------------------------------------------

    def _formats(self, asked: Any) -> list[str]:
        wanted = [str(f).lower().strip() for f in (asked or []) if str(f).strip()]
        if not wanted:
            raise assistant.ToolFailed(
                "Name at least one format to produce, from "
                + ", ".join(DOCUMENT_FORMATS) + ".")
        unknown = [f for f in wanted if f not in DOCUMENT_FORMATS]
        if unknown:
            raise assistant.ToolFailed(
                f"{', '.join(unknown)} is not a format this workspace can "
                f"produce. Supported: {', '.join(DOCUMENT_FORMATS)}.")
        return wanted

    def _record(self, outcome) -> dict:
        """Turn an authoring outcome into something the model can act on."""
        from backend.playbook import service

        self.artifact_id = outcome.artifact_id
        if outcome.pending_projection:
            self.projections.append(dict(outcome.pending_projection))

        delivered = [f for f, o in outcome.formats.items() if o.delivered]
        failed = {f: "; ".join(o.issues) for f, o in outcome.formats.items()
                  if not o.delivered}
        result = {
            "artifact_id": outcome.artifact_id,
            "version": outcome.version,
            "version_id": outcome.version_id,
            "delivered": delivered,
            "failed": failed,
            # Content findings, carried so the assistant can mention them
            # rather than presenting a draft as checked. They never block.
            "review_notes": list(outcome.notes),
            # Chapter 03: a written document is a DRAFT. Handing the assistant
            # the count rather than the findings keeps it from restating a
            # finding as though it had checked it.
            "review_state": "draft",
            "review_items": len(outcome.review_items),
        }
        self.produced.append(dict(result))
        del service
        return result

    def _author(self, *, instruction: str, formats: list[str], task_kind: str,
                task_scope: str = "", artifact_id=None, base_version_id=None):
        from backend.playbook import evidence as ev
        from backend.playbook import service

        try:
            return service.author_document(
                self.session, self.scope, self.ws.id,
                instruction=instruction,
                ledger=self.ledger if self.ledger is not None else ev.Ledger(),
                title=self.ws.title,
                formats=formats,
                artifact_id=artifact_id,
                base_version_id=base_version_id,
                task_kind=task_kind,
                task_scope=task_scope,
                on_milestone=self.on_milestone,
                # Deliberately not streamed into the chat. The answer the user
                # reads is the assistant's own prose; streaming the document
                # here as well would put the whole report in the message
                # column beside the file card that already holds it.
                on_delta=None,
                is_cancelled=self.is_cancelled)
        except provider.Cancelled:
            # A stop is the user's decision, not a tool failure. It ends the
            # turn rather than being reported to the model as a result.
            raise
        except (provider.AuthoringTimeout, provider.ProviderNotConfigured):
            # A failure of the RUNTIME, not of this document. Reporting it to
            # the model as a tool result would spend another provider call
            # explaining a deadline that has already been exceeded, or one
            # that cannot be made at all — so it ends the turn, and the user
            # retries deliberately. Chapter 17: a deadline has to be a bound.
            raise
        except provider.AuthoringError as exc:
            # A failure of THIS DOCUMENT — nothing usable came back, the scope
            # named no section, the formats could not be produced. The turn
            # keeps its answer and the assistant explains what happened.
            raise assistant.ToolFailed(str(exc)) from exc

    # -- the tools themselves --------------------------------------------

    def create(self, args: dict) -> dict:
        instruction = str(args.get("instruction") or "").strip()
        if not instruction:
            raise assistant.ToolFailed(
                "Say what the document should contain.")
        outcome = self._author(
            instruction=instruction,
            formats=self._formats(args.get("formats")),
            task_kind="create")
        return self._record(outcome)

    def revise(self, args: dict) -> dict:
        if not self.artifact_id:
            raise assistant.ToolFailed(
                "There is no document in this Playbook to revise yet.")
        instruction = str(args.get("instruction") or "").strip()
        if not instruction:
            raise assistant.ToolFailed("Say what should change.")
        outcome = self._author(
            instruction=instruction,
            formats=self._formats(args.get("formats")),
            task_kind="edit",
            task_scope=str(args.get("scope") or "").strip(),
            artifact_id=self.artifact_id,
            base_version_id=self.base_version_id)
        return self._record(outcome)

    def convert(self, args: dict) -> dict:
        """Produce another format from the version that already exists.

        Chapter 17 and journey 16: retrying a failed PDF reuses the saved
        content rather than authoring the report again. No provider call is
        made here at all — the document is already written, and re-authoring it
        would spend money to produce a different report under the same name.
        """
        from backend.playbook import document as D
        from backend.playbook import service

        if not self.artifact_id:
            raise assistant.ToolFailed("There is no document to convert yet.")
        formats = self._formats(args.get("formats"))

        current = service._current_document(self.session, self.artifact_id)
        if current is None:
            raise assistant.ToolFailed(
                "This document has no saved version to convert.")

        produced = service._usable({}, current.canonical, formats)
        stored = service.attach_formats(
            self.session, self.scope, self.ws.id, self.artifact_id, produced)
        if not stored["delivered"]:
            raise assistant.ToolFailed(
                "The conversion did not produce a usable file. "
                + "; ".join(stored["failed"].values()))
        del D
        return {"artifact_id": self.artifact_id, **stored}

    def tools(self) -> list[assistant.Tool]:
        formats_schema = {
            "type": "array",
            "items": {"type": "string", "enum": list(DOCUMENT_FORMATS)},
            "description": "The file formats to produce.",
        }
        return [
            assistant.Tool(
                name="create_document",
                description=(
                    "Write a new document for this Playbook and produce it as "
                    "real files the user can download. Use this when the user "
                    "asks for a report, paper, note, deck or workbook. Do not "
                    "use it to answer a question."),
                schema={
                    "type": "object",
                    "properties": {
                        "instruction": {
                            "type": "string",
                            "description": (
                                "What the document should contain, in your own "
                                "words, including audience, scope and depth."),
                        },
                        "formats": formats_schema,
                    },
                    "required": ["instruction", "formats"],
                },
                run=self.create),
            assistant.Tool(
                name="revise_document",
                description=(
                    "Revise the Playbook's current document and save a new "
                    "version. Give `scope` when only one section or slide may "
                    "change; everything else is carried forward unchanged."),
                schema={
                    "type": "object",
                    "properties": {
                        "instruction": {"type": "string",
                                        "description": "What should change."},
                        "scope": {
                            "type": "string",
                            "description": (
                                "The heading of the only section that may "
                                "change. Omit for a whole-document revision."),
                        },
                        "formats": formats_schema,
                    },
                    "required": ["instruction", "formats"],
                },
                run=self.revise),
            assistant.Tool(
                name="convert_document",
                description=(
                    "Produce another file format from the document version "
                    "that already exists — for example a PDF after the Word "
                    "file is written, or a retry of a conversion that failed. "
                    "This does not rewrite the document."),
                schema={
                    "type": "object",
                    "properties": {"formats": formats_schema},
                    "required": ["formats"],
                },
                run=self.convert),
        ]


def turn(session, scope, workspace_id: int, *,
         text: str,
         source_ids: list[int] | None = None,
         export_revision_ids: list[int] | None = None,
         artifact_id: int | None = None,
         base_version_id: int | None = None,
         context_kind: str = "",
         context_target: str = "",
         calculations: list | None = None,
         on_milestone=None,
         on_delta=None,
         on_tool=None,
         is_cancelled=None) -> dict:
    """Run one conversational turn against the real workspace.

    Returns what happened, for the caller to persist: the answer, what the
    tools did, and what the status projection still owes.
    """
    from backend.playbook import service

    ws = repo.get_workspace(session, scope, workspace_id)

    # The selected working artifact: the one named, or the workspace's current
    # report. Chapter 10 wants "this document" to resolve to something real
    # before the assistant is asked to change it.
    artifact = None
    if artifact_id:
        artifact = artifact_id
    else:
        from backend.playbook.intelligence import service as intel

        current = intel._current_artifact(session, ws.id)
        artifact = current.id if current is not None else None

    chat_context = service.resolve_context(session, ws.id, kind=context_kind,
                                           target=context_target)
    ledger = service.ledger_for(
        session, scope, ws.id, source_ids=source_ids,
        export_revision_ids=export_revision_ids, calculations=calculations,
        artifact_id=artifact, chat_context=chat_context)
    current_doc = service._current_document(session, artifact)

    documents = _Documents(
        session, scope, ws, artifact_id=artifact,
        base_version_id=base_version_id, ledger=ledger,
        on_milestone=on_milestone, is_cancelled=is_cancelled)

    active = ""
    if current_doc is not None:
        active = f"version {current_doc.version} of this Playbook's document"
    system = service.prompts.assistant(
        workspace_title=ws.title, active=active,
        capabilities=_capability_note())

    messages = _history(session, ws.id)
    note = _attachment_note(ledger, current_doc)
    body = f"{note}\n\n{text}" if note else text
    if current_doc is not None:
        body = (f"{note}\n\n--- the document as it stands ---\n"
                f"{current_doc.markdown}\n--- end of document ---\n\n{text}")
    messages.append({"role": "user", "content": body})

    if on_milestone:
        on_milestone("reviewing_sources", "")

    reply = assistant.converse(
        system=system, messages=messages, tools=documents.tools(),
        on_delta=on_delta, on_tool=on_tool, is_cancelled=is_cancelled)

    return {
        "text": reply.text,
        "reply": reply,
        "interrupted": reply.interrupted,
        "artifact_id": documents.artifact_id,
        "produced": list(documents.produced),
        "projections": list(documents.projections),
        "evidence_complete": ledger.complete,
        "evidence_gaps": list(ledger.omissions),
    }
