"""Any dashboard object can become a chat context. §15.

What this is
------------
The dashboard is not a separate dead screen. Clicking a metric, a finding, a
section, a decision or a Since Last Time row hands the chat composer a
question already written, the §8 task framing that question belongs to, and
an explicit list of what it refers to.

Three things travel, and they are different on purpose:

* **the prompt** — what the user sees in the composer and may rewrite before
  sending. It is a starting point, never a hidden instruction;
* **the task and scope** — the existing framing machinery. "Update this
  section" resolves to `task="edit"`, `scope=<heading>`, which is the scoped
  merge that already refuses to touch anything else;
* **the references** — `{kind, id, label, value, locator}` per object. These
  are the facts as the dashboard holds them, so the authoring path can put
  them in front of the model as evidence instead of asking it to remember
  what the user was looking at.

The one rule
------------
A reference carries only what is governed. A metric binding that is merely
suggested is handed over as a suggestion, labelled as one, and is NOT
presented to the model as an established reading — the same rule that governs
THEN/NOW links, for the same reason: a guess that travels far enough from
where it was made stops looking like a guess.

Nothing here writes anything and nothing here calls a provider. Building a
context is a read. The user still presses send.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from backend.models.playbook import (
    PlaybookDecision,
    PlaybookDocumentSection,
    PlaybookFinding,
    PlaybookMetricBinding,
)
from backend.playbook.intelligence import binding as bind
from backend.playbook.intelligence import compare
from backend.playbook.intelligence import governance as gov
from backend.playbook.intelligence import service as svc


class UnknownContext(ValueError):
    """A context kind or a target that does not exist here."""


# --------------------------------------------------------------------------
# What a context is
# --------------------------------------------------------------------------

#: The actions §15 names, with the label each one carries on the dashboard.
ASK_ABOUT_METRIC = "ask_about_metric"
DRAFT_FINDING_ANSWER = "draft_finding_answer"
UPDATE_SECTION = "update_section"
EXPLAIN_MOVEMENTS = "explain_movements"
DRAFT_RECOMMENDATION = "draft_recommendation"
REFRESH_AFFECTED = "refresh_affected_sections"

ACTION_LABELS = {
    ASK_ABOUT_METRIC: "Ask CreditProbe about this",
    DRAFT_FINDING_ANSWER: "Draft an answer",
    UPDATE_SECTION: "Update this section",
    EXPLAIN_MOVEMENTS: "Explain these movements",
    DRAFT_RECOMMENDATION: "Draft the committee recommendation",
    REFRESH_AFFECTED: "Refresh affected sections",
}

ACTIONS = tuple(ACTION_LABELS)


@dataclass
class Reference:
    """One thing the chat turn is about, as the dashboard holds it."""

    kind: str
    id: str
    label: str
    value: str = ""
    locator: str = ""
    #: False for anything the user has not confirmed. Carried so nothing
    #: downstream has to re-derive it, and so a suggestion cannot be quietly
    #: read as a reading.
    governed: bool = True
    detail: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {"kind": self.kind, "id": self.id, "label": self.label,
                "value": self.value, "locator": self.locator,
                "governed": self.governed, "detail": dict(self.detail)}


@dataclass
class ChatContext:
    """What the composer is handed when a dashboard object is clicked."""

    action: str
    label: str
    prompt: str
    task: str = ""
    scope: str = ""
    references: list[Reference] = field(default_factory=list)
    #: Governed facts, each with the address it came from, for the authoring
    #: prompt. Separate from `prompt` because the user may rewrite the
    #: question and must not thereby rewrite the evidence.
    evidence: list[dict] = field(default_factory=list)
    #: Said plainly when something in the context is not governed, so the
    #: user sees it before sending rather than in the output.
    caveats: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "action": self.action, "label": self.label, "prompt": self.prompt,
            "task": self.task, "scope": self.scope,
            "references": [r.as_dict() for r in self.references],
            "evidence": [dict(e) for e in self.evidence],
            "caveats": list(self.caveats),
        }


# --------------------------------------------------------------------------
# Building one
# --------------------------------------------------------------------------


def _fact(text: str, locator: str = "", *, kind: str = "metric",
          ref: str = "") -> dict:
    """One governed fact, with the address it came from.

    A fact with no locator of its own is addressed to the dashboard object it
    came from, so nothing enters the evidence ledger without an address a
    reader can follow back.
    """
    if locator:
        return {"text": text, "locator": locator}
    return {"text": text,
            "locator": f"dashboard://{kind}/{ref}" if ref
                       else f"dashboard://{kind}"}


def _metric(session, workspace_id: int, binding_id: int) -> ChatContext:
    row = session.get(PlaybookMetricBinding, binding_id)
    if row is None or row.workspace_id != workspace_id:
        raise UnknownContext(f"No metric {binding_id} in this document.")

    governed = bind.is_governed(row)
    label = row.label or row.canonical_name or row.metric_id or "this metric"
    shown = row.display_value or row.value_in_document or row.raw_value

    reference = Reference(
        kind="metric", id=str(row.id), label=label, value=shown,
        locator=row.source_locator, governed=governed,
        detail={"metric_id": row.metric_id, "unit": row.unit,
                "reporting_period": row.reporting_period,
                "population": row.population, "segment": row.segment,
                "section_key": row.section_key,
                "method": row.binding_method,
                "method_label": bind.METHOD_LABELS.get(row.binding_method,
                                                       row.binding_method)})

    evidence, caveats = [], []
    if governed:
        stated = f"{label} is {shown}" if shown else label
        if row.unit:
            stated += f" ({row.unit})"
        if row.reporting_period:
            stated += f", {row.reporting_period}"
        evidence.append(_fact(stated, row.source_locator))
    else:
        caveats.append(
            f"{label} is a suggested link that nobody has confirmed. It is "
            "not being treated as a governed reading of "
            f"{row.metric_id or 'a catalogue metric'}.")

    question = (f"Explain {label}" + (f", currently {shown}" if shown else "")
                + ". What does it mean for this document, and what drove it?")
    return ChatContext(action=ASK_ABOUT_METRIC,
                       label=ACTION_LABELS[ASK_ABOUT_METRIC],
                       prompt=question, references=[reference],
                       evidence=evidence, caveats=caveats)


def _finding(session, workspace_id: int, finding_id: int) -> ChatContext:
    row = session.get(PlaybookFinding, finding_id)
    if row is None or row.workspace_id != workspace_id:
        raise UnknownContext(f"No finding {finding_id} in this document.")

    reference = Reference(
        kind="finding", id=str(row.id), label=row.title,
        value=row.severity, locator=row.source_locator,
        detail={"reference": row.reference, "status": row.status,
                "origin": row.raised_by,
                "origin_label": gov.ORIGIN_LABELS.get(row.raised_by,
                                                      row.raised_by),
                "blocking": row.blocking, "owner": row.owner,
                "section_key": row.section_key, "delta": row.delta})

    evidence = []
    if row.rationale:
        evidence.append(_fact(row.rationale, row.source_locator))
    if row.previous_value and row.current_value:
        evidence.append(_fact(
            f"{row.metric_id or row.title}: was {row.previous_value}, now "
            f"{row.current_value}" + (f" ({row.delta})" if row.delta else ""),
            row.source_locator))
    if row.threshold:
        evidence.append(_fact(f"Threshold: {row.threshold}",
                              row.source_locator))

    caveats = [
        "A drafted answer is a draft. It does not answer, accept or close "
        "this finding — a person does that, on the record."
    ]
    if row.answer:
        caveats.append("This finding already carries an answer; sending this "
                       "replaces the draft.")

    return ChatContext(
        action=DRAFT_FINDING_ANSWER,
        label=ACTION_LABELS[DRAFT_FINDING_ANSWER],
        prompt=(f"Draft an answer to the finding “{row.title}” for "
                "the committee, using only the evidence this document holds."),
        references=[reference], evidence=evidence, caveats=caveats)


def _section(session, workspace_id: int, section_key: str) -> ChatContext:
    artifact = svc._current_artifact(session, workspace_id)
    row = None
    if artifact is not None:
        row = (session.query(PlaybookDocumentSection)
               .filter(PlaybookDocumentSection.artifact_id == artifact.id,
                       PlaybookDocumentSection.section_key == section_key)
               .one_or_none())
    if row is None:
        raise UnknownContext(f"No section {section_key!r} in this document.")

    bindings = (session.query(PlaybookMetricBinding)
                .filter(PlaybookMetricBinding.workspace_id == workspace_id,
                        PlaybookMetricBinding.section_key == section_key)
                .all())
    governed = [b for b in bindings if bind.is_governed(b)]
    suggested = [b for b in bindings if not bind.is_governed(b)]

    references = [Reference(
        kind="section", id=section_key, label=row.heading,
        detail={"status": row.status, "ordinal": row.ordinal,
                "word_count": row.word_count,
                "last_changed_version": row.last_changed_version,
                "reviewer": row.reviewer})]
    references += [
        Reference(kind="metric", id=str(b.id),
                  label=b.label or b.metric_id, value=b.display_value,
                  locator=b.source_locator, governed=True)
        for b in governed]

    evidence = [_fact(f"{b.label or b.metric_id} is {b.display_value}",
                      b.source_locator)
                for b in governed if b.display_value]

    caveats = []
    if suggested:
        caveats.append(
            f"{len(suggested)} metric link(s) in this section are suggested "
            "and unconfirmed. They are not being supplied as evidence.")
    if row.reviewed_at is not None:
        caveats.append("This section has been reviewed. Changing it reopens "
                       "that review.")

    return ChatContext(
        action=UPDATE_SECTION, label=ACTION_LABELS[UPDATE_SECTION],
        prompt=f"Update “{row.heading}”. ",
        # The existing scoped-edit machinery, unchanged: everything outside
        # this heading must come back byte-identical.
        task="edit", scope=row.heading,
        references=references, evidence=evidence, caveats=caveats)


def _movements(session, workspace_id: int) -> ChatContext:
    table = compare.since_last_time(session, workspace_id)
    if not table.get("available"):
        raise UnknownContext(
            table.get("reason") or "There is nothing to compare yet.")

    moved = [r for r in table["rows"] if r.get("direction") != "unchanged"]
    references = [
        Reference(kind="metric_movement", id=r["metric_id"], label=r["label"],
                  value=f"{r['then']} → {r['now']}",
                  locator=r.get("source_locator", ""),
                  detail={"change": r.get("change", ""),
                          "direction": r.get("direction", ""),
                          "assessment": r.get("assessment", ""),
                          "section_key": r.get("section_key", "")})
        for r in moved]
    evidence = [_fact(
        f"{r['label']}: {r['then']} at version {r['then_version']}, now "
        f"{r['now']}" + (f", {r['change']}" if r.get("change") else ""),
        r.get("source_locator", ""), kind="metric_movement", ref=r["metric_id"])
        for r in moved]

    return ChatContext(
        action=EXPLAIN_MOVEMENTS, label=ACTION_LABELS[EXPLAIN_MOVEMENTS],
        prompt=("Explain the movements since the last version of this "
                "document, and what they mean for its conclusions."),
        references=references, evidence=evidence,
        caveats=([] if moved else
                 ["Nothing has moved since the last version."]))


def _decision(session, workspace_id: int, decision_id: int) -> ChatContext:
    row = session.get(PlaybookDecision, decision_id)
    if row is None or row.workspace_id != workspace_id:
        raise UnknownContext(f"No decision {decision_id} in this document.")

    reference = Reference(
        kind="decision", id=str(row.id), label=row.question,
        value=row.status,
        detail={"reference": row.reference, "status": row.status,
                "options": list(row.options or []),
                "current_position": row.current_position,
                "proposed_position": row.proposed_position,
                "reporting_period": row.reporting_period})

    evidence = []
    if row.current_position:
        evidence.append(_fact(f"Current position: {row.current_position}",
                              kind="decision", ref=str(row.id)))
    if row.proposed_position:
        evidence.append(_fact(f"Proposed position: {row.proposed_position}",
                              kind="decision", ref=str(row.id)))

    caveats = ["A drafted recommendation is a recommendation. Recording what "
               "the committee decided is a person's act and is not part of "
               "this."]
    if row.status == gov.DECIDED:
        caveats.append("This decision has already been recorded. Drafting "
                       "does not change it.")

    return ChatContext(
        action=DRAFT_RECOMMENDATION,
        label=ACTION_LABELS[DRAFT_RECOMMENDATION],
        prompt=(f"Draft the committee recommendation for: {row.question}"),
        references=[reference], evidence=evidence, caveats=caveats)


def _stale(session, workspace_id: int) -> ChatContext:
    """Sections whose governed metrics have newer readings.

    Which sections, named from the bindings — never "everything", which is
    how a governed refresh turns into an ungoverned rewrite.
    """
    bindings = (session.query(PlaybookMetricBinding)
                .filter(PlaybookMetricBinding.workspace_id == workspace_id)
                .all())
    stale = [b for b in bindings
             if bind.is_governed(b) and b.freshness in bind.NEEDS_ATTENTION]
    if not stale:
        raise UnknownContext("No governed metric has a newer reading.")

    headings = _headings(session, workspace_id)
    sections = sorted({b.section_key for b in stale if b.section_key})

    references = [
        Reference(kind="metric", id=str(b.id), label=b.label or b.metric_id,
                  value=b.display_value, locator=b.source_locator,
                  detail={"freshness": b.freshness,
                          "section_key": b.section_key})
        for b in stale]
    evidence = [_fact(f"{b.label or b.metric_id} is marked {b.freshness}",
                      b.source_locator)
                for b in stale]

    named = ", ".join(f"“{headings.get(k, k)}”" for k in sections)
    return ChatContext(
        action=REFRESH_AFFECTED, label=ACTION_LABELS[REFRESH_AFFECTED],
        prompt=("Refresh the sections affected by the newer readings"
                + (f": {named}." if named else ".")),
        references=references, evidence=evidence,
        caveats=["Nothing is rewritten by this. It produces proposed changes "
                 "for review."])


def _headings(session, workspace_id: int) -> dict[str, str]:
    from backend.playbook.intelligence import sections as sect

    artifact = svc._current_artifact(session, workspace_id)
    if artifact is None:
        return {}
    return {r.section_key: r.heading
            for r in sect.rows_for(session, artifact.id)}


#: Each entry says whether the context needs a target and how to build it.
BUILDERS = {
    "metric": (True, lambda s, w, t: _metric(s, w, int(t))),
    "finding": (True, lambda s, w, t: _finding(s, w, int(t))),
    "section": (True, lambda s, w, t: _section(s, w, t)),
    "decision": (True, lambda s, w, t: _decision(s, w, int(t))),
    "since_last_time": (False, lambda s, w, t: _movements(s, w)),
    "stale_metrics": (False, lambda s, w, t: _stale(s, w)),
}

KINDS = tuple(BUILDERS)


def build(session, workspace_id: int, *, kind: str,
          target: str = "") -> ChatContext:
    """Turn a dashboard object into a chat context. A read, always."""
    if kind not in BUILDERS:
        raise UnknownContext(
            f"{kind!r} is not a dashboard context. Expected one of: "
            + ", ".join(KINDS))
    needs_target, builder = BUILDERS[kind]
    if needs_target and not str(target or "").strip():
        raise UnknownContext(f"A {kind} context needs a {kind} to point at.")
    try:
        return builder(session, workspace_id, target)
    except ValueError as exc:
        if isinstance(exc, UnknownContext):
            raise
        raise UnknownContext(f"{target!r} is not a {kind} id.") from exc


# --------------------------------------------------------------------------
# Travelling with the message
# --------------------------------------------------------------------------

#: Where references live on a message. `content` is already the structured
#: field, and a reference is part of what the turn said rather than metadata
#: about it — so it is stored there rather than in a column of its own.
CONTENT_KEY = "context"


def attach(content: dict, ctx: ChatContext | None) -> dict:
    """Put a context's references on a message's content."""
    if ctx is None:
        return content
    return {**content, CONTENT_KEY: {
        "action": ctx.action,
        "references": [r.as_dict() for r in ctx.references],
    }}


def references_of(message) -> list[dict]:
    """Read back what a turn referred to. Empty for a turn that referred to
    nothing, which is most of them."""
    stored = (message.content or {}).get(CONTENT_KEY) or {}
    return list(stored.get("references") or [])


def as_items(ctx: ChatContext | None) -> list:
    """The governed facts as evidence items, for the authoring ledger.

    Never the caveats and never the prompt: a caveat is written for the
    person, and the prompt is theirs to rewrite. Only what `build` already
    established as governed reaches here — an unconfirmed suggestion produced
    a caveat, not a fact, so it cannot become a citable figure by travelling
    through the composer.
    """
    from backend.playbook import evidence as ev

    if ctx is None:
        return []
    return [ev.Item(locator=fact["locator"], kind="context",
                    text=fact["text"], origin="dashboard",
                    label=ctx.label)
            for fact in ctx.evidence]
