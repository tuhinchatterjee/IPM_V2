"""Ordinary language, turned into the planner commands that already exist.

The Copilot's promise is that somebody can say "under Data Foundation add
Data Extraction, Data Reconciliation and Data Quality Review" and the plan
changes. This module is where that happens, and the shape of it matters more
than any individual sentence it can read.

Nothing here writes anything. It produces PROPOSALS — `(command, payload)`
pairs drawn from `draft.COMMANDS` and nothing else — which the caller applies
through `draft.apply`, which is the same function the structured panels call.
So every rule the panels obey, the conversation obeys: the permission check,
the cycle check, the date validation, the optimistic concurrency, the audit
row marked AI_CHAT. A sentence cannot reach a mutation that has no screen,
because a sentence cannot reach anything except this list.

Two readers, one contract
-------------------------
**The rule reader** handles the shapes people actually use — ownership,
dates, lists of tasks under a milestone, dependencies, escalation, the
monitoring mode. It is deterministic, it costs nothing, and it works on a
bank network with no egress. It reads against the plan's OWN vocabulary: the
milestones and tasks that exist, and the colleagues who can be named. It has
no knowledge of any particular sentence, and adding a test sentence to it
would be adding a rule that fires on anything shaped like it.

**The model** is asked only about what the rules could not read, and only
when a provider is actually configured. It answers in the same structured
shape — and, crucially, it answers with the WORDS the person used, never with
an id or a code. Resolution from "Sameer" to a user id happens here,
afterwards, against the directory that person can see. A model that returned
`owner_id: 41` would be a model deciding who is on a project.

What is asked rather than guessed
---------------------------------
Two tasks called "Data Review" and one phrase that fits both is a question
with two buttons, not a coin toss. A name nobody in the directory has is said
back, not invented. This is the difference between an assistant somebody can
leave running and one they have to check.

What gets confirmed
-------------------
A change that moves a commitment — a date, an owner, a dependency, the
monitoring policy, a removal — is previewed before it happens. Adding
something new is not: nothing was promised about a milestone that did not
exist thirty seconds ago.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from backend.planner import draft as dr
from backend.planner import policy as pol
from backend.planner import reading as rd

logger = logging.getLogger(__name__)

LANGUAGE_VERSION = "1.0.0"

#: A payload value of `$new:2` means "the code created by proposal 2".
#: Needed because "Add Data Foundation as the first milestone. It starts on
#: 1 October." refers to something that does not have a code yet when the
#: sentence is read. The executor substitutes it after each apply returns.
PENDING = "$new:"


# ------------------------------------------------------------------ shapes


@dataclass
class Proposal:
    """One change, resolved, and what it will do said in words."""

    command: str
    payload: dict[str, Any] = field(default_factory=dict)
    sentence: str = ""
    #: True where the change moves something somebody may have committed to.
    preview: bool = False
    source: str = "rules"
    #: The `$new:` handle this proposal will fill once it has run, when it
    #: creates something later proposals refer to. Carried on the proposal
    #: rather than derived from its position, because the milestone that
    #: three tasks hang off is rarely the first command in the message.
    creates: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"command": self.command, "payload": self.payload,
                "sentence": self.sentence, "preview": self.preview,
                "source": self.source, "creates": self.creates}


@dataclass
class Question:
    """A short clarification, with the answers as buttons."""

    text: str
    field: str
    options: list[dict[str, str]] = field(default_factory=list)
    fragment: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"text": self.text, "field": self.field,
                "options": self.options, "fragment": self.fragment}


@dataclass
class Reading:
    """Everything one message turned into."""

    commands: list[Proposal] = field(default_factory=list)
    questions: list[Question] = field(default_factory=list)
    unread: list[str] = field(default_factory=list)
    source: str = "rules"
    focus: str = ""
    said: str = ""

    @property
    def understood(self) -> bool:
        return bool(self.commands or self.questions)

    def to_dict(self) -> dict[str, Any]:
        return {
            "commands": [c.to_dict() for c in self.commands],
            "questions": [q.to_dict() for q in self.questions],
            "unread": list(self.unread),
            "source": self.source,
            "focus": self.focus,
            "said": self.said,
            "understood": self.understood,
        }


@dataclass
class Context:
    """What the reader is allowed to know: this plan, and these people."""

    plan: dict[str, Any]
    directory: rd.Directory
    today: date
    #: The last thing talked about, so "it starts on the first" has a subject.
    focus: str = ""
    #: What the person picked when asked "which one did you mean?", keyed by
    #: the words they originally used. A clarification is answered by
    #: re-reading the SAME sentence with the answer to hand, rather than by
    #: the client sending back a command — so the disambiguation is a fact
    #: about the sentence, not a second way to reach a mutation.
    answers: dict[str, str] = field(default_factory=dict)

    @property
    def lexicon(self) -> rd.Lexicon:
        rows: list[dict[str, Any]] = []
        for row in dr.catalogue(self.plan):
            rows.append({"code": str(row.get("code") or ""),
                         "name": str(row.get("name") or ""),
                         "kind": str(row.get("kind") or ""),
                         "milestone": str(row.get("milestone") or "")})
        return rd.Lexicon(rows)

    @property
    def window(self) -> tuple[date | None, date | None]:
        governance = self.plan.get("governance") or {}
        return (_date(governance.get("start_date")),
                _date(governance.get("target_end_date")))


def _date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


# --------------------------------------------------------------- resolving


def _answered(ctx: Context, said: Any) -> str:
    """What the person chose last time we asked about these words."""
    return ctx.answers.get(rd.normalise(said), "")


def _person(ctx: Context, said: str) -> rd.Resolution:
    """A person from however much of their name somebody used.

    Tried longest-first, because a capture like "Priya Raman is" has to lose
    the "is" before it finds Priya.
    """
    chosen = _answered(ctx, said)
    if chosen.isdigit():
        return rd.Resolution(rd.RESOLVED, match=rd.Match(
            chosen, ctx.directory.name_of(chosen), 1.0,
            {"user_id": int(chosen)}))
    words = str(said or "").strip().split()
    for size in range(min(len(words), 3), 0, -1):
        found = ctx.directory.find(" ".join(words[:size]))
        if found.state != rd.UNKNOWN:
            return found
    return rd.Resolution(rd.UNKNOWN, asked="person")


def _item(ctx: Context, said: str, *, kind: str = "") -> rd.Resolution:
    """One milestone or task, by name or by code."""
    chosen = _answered(ctx, said)
    if chosen:
        return ctx.lexicon.find(chosen, kind=kind)
    text = re.sub(r"^(the|this|that)\s+", "", str(said or "").strip(),
                  flags=re.IGNORECASE)
    text = re.sub(r"\s+(task|milestone|stage|step)$", "", text,
                  flags=re.IGNORECASE)
    return ctx.lexicon.find(text, kind=kind)


def _ask(field: str, fragment: str, found: rd.Resolution) -> Question:
    if found.state == rd.AMBIGUOUS:
        return Question(
            text=f"Which one do you mean by “{fragment.strip()}”?",
            field=field, fragment=fragment,
            options=[{"label": c.label, "value": c.key}
                     for c in found.candidates])
    return Question(
        text=f"I could not find “{fragment.strip()}” in this plan.",
        field=field, fragment=fragment, options=[])


def _label(ctx: Context, code: str) -> str:
    row = dr.item(ctx.plan, code)
    if row is None:
        return code
    return str(row.get("name") or row.get("title") or code)


# ------------------------------------------------------------- the rules


@dataclass
class Hit:
    """What one rule made of one span of the sentence."""

    start: int
    end: int
    commands: list[Proposal] = field(default_factory=list)
    questions: list[Question] = field(default_factory=list)
    focus: str = ""


#: A person's name, as somebody types one. Lazy, so "Ananya after two days"
#: yields Ananya and leaves the rest of the sentence to be read.
_NAME = r"[A-Za-z][\w'’.\-]*(?:\s+[A-Za-z][\w'’.\-]*){0,2}?"
#: Anything that could name a milestone or a task.
_THING = r"[^,.;]+?"
#: Where a clause stops. A phrase runs to a comma, a full stop, or an "and"
#: that starts another statement — which is what makes "Rohan owns Data
#: Foundation and Priya is the escalation owner" two facts rather than one
#: fact about a milestone called "Data Foundation and Priya".
_END = r"(?=\s*[,.;]|\s+and\b|\s*$)"

#: Words that point at whatever was just being discussed.
_PRONOUNS = {"it", "this", "that", "them", "those", "these", "there"}


def _split_list(text: str) -> list[str]:
    """"A, B and C" → three things. "A and B" → two."""
    body = re.sub(r"\s+and\s+", ",", str(text or ""), flags=re.IGNORECASE)
    return [part.strip(" .;") for part in body.split(",") if part.strip(" .;")]


def _remember(state: dict, name: str, kind: str) -> str:
    """Give something this message is about to create a handle to be named by.

    Needed because "add a Reporting milestone … and under it add Draft
    Report … Sameer owns Draft Report until 30 November" refers three times
    to things that do not have codes yet. The handle is substituted for the
    real code after the command that creates it has run.
    """
    handle = f"{PENDING}{state['next_pending']}"
    state["next_pending"] += 1
    state["pending"][handle] = name
    state["pending_kind"][handle] = kind
    return handle


def _pending_match(state: dict, said: Any, *, kind: str = "") -> str:
    wanted = rd.normalise(said)
    if not wanted:
        return ""
    for handle, name in state["pending"].items():
        if kind and state["pending_kind"].get(handle) != kind:
            continue
        if rd.normalise(name) == wanted or wanted in rd.normalise(name):
            return handle
    return ""


def _rule_add_tasks_under(text: str, ctx: Context, state: dict) -> Hit | None:
    """"Under Data Foundation add A, B and C" — and the other way round."""
    match = re.search(
        rf"\bunder\s+(?P<parent>{_THING})\s*,?\s*\badd\b\s+(?P<list>.+)",
        text, re.IGNORECASE) or re.search(
        rf"\badd\b\s+(?P<list>.+?)\s+\bunder\s+(?P<parent>{_THING})\s*$",
        text, re.IGNORECASE)
    if not match:
        return None
    parent = _resolve_parent(ctx, state, match["parent"])
    if isinstance(parent, Question):
        return Hit(match.start(), match.end(), questions=[parent])
    if not parent:
        return None
    hit = Hit(match.start(), match.end())
    for title in _split_list(match["list"]):
        clean = _clean_name(title)
        if not clean:
            continue
        hit.commands.append(Proposal(
            "add_task", {"milestone_code": parent, "title": clean},
            f"Add “{clean}” under {_pending_label(ctx, state, parent)}.",
            creates=_remember(state, clean, "TASK")))
    if not hit.commands:
        return None
    hit.focus = parent
    return hit


def _pending_label(ctx: Context, state: dict, code: str) -> str:
    if code.startswith(PENDING):
        return state["pending"].get(code, "the new item")
    return _label(ctx, code)


def _resolve_parent(ctx: Context, state: dict, said: Any) -> str | Question:
    """A milestone that either exists or is about to, in this same message."""
    if rd.normalise(said) in _PRONOUNS:
        return state.get("focus_milestone") or state.get("focus") or ""
    handle = _pending_match(state, said, kind="MILESTONE")
    if handle:
        return handle
    found = _item(ctx, said, kind="MILESTONE")
    if found.ok and found.match:
        return found.match.key
    return _ask("milestone", str(said), found)


def _rule_add_milestones(text: str, ctx: Context, state: dict) -> Hit | None:
    """"Add Data Foundation, Model Build and Validation as the milestones."

    The list form, which is how somebody names the stages of a programme the
    first time: one sentence, three or five or eight names. The singular rule
    below reads "add X as the first milestone" — the sentence somebody says
    second. Reading only that one made the first sentence of every new
    project unreadable, which is a poor place to start.

    No focus is set. "It" after a list of three names does not refer to
    anything in particular, and guessing the last one would be a plausible
    wrong answer rather than a question.
    """
    del ctx
    match = (
        re.search(r"\badd\s+(?P<list>.+?)\s+as\s+(?:the\s+)?milestones?\b",
                  text, re.IGNORECASE)
        or re.search(r"\b(?:the\s+)?milestones?\s+(?:are|will be)\s+"
                     r"(?P<list>.+)", text, re.IGNORECASE)
        or re.search(r"\badd\s+(?:the\s+)?milestones?\s+(?P<list>.+)",
                     text, re.IGNORECASE))
    if not match:
        return None
    names = [_clean_name(said) for said in _split_list(match["list"])]
    names = [n for n in names if n and rd.normalise(n) not in _PRONOUNS]
    if len(names) < 2:
        # One name is the singular rule's job, and only it knows the
        # ordinals ("as the first milestone").
        return None
    hit = Hit(match.start(), match.end())
    for name in names:
        hit.commands.append(Proposal(
            "add_milestone", {"name": name},
            f"Add a milestone called \u201c{name}\u201d.",
            creates=_remember(state, name, "MILESTONE")))
    return hit


def _rule_add_milestone(text: str, ctx: Context, state: dict) -> Hit | None:
    """"Add Data Foundation as the first milestone", and its neighbours."""
    match = (
        re.search(rf"\badd\s+(?P<name>{_THING})\s+as\s+(?:the\s+)?"
                  r"(?:first|second|third|next|last|a|an|the)?\s*milestone",
                  text, re.IGNORECASE)
        or re.search(r"\badd\s+(?:a\s+|the\s+)?milestone\s+"
                     rf"(?:called|named|for|:)?\s*(?P<name>{_THING}){_END}",
                     text, re.IGNORECASE)
        or re.search(rf"\b(?:we need|create|add|there is)\s+(?:a\s+|an\s+)?"
                     rf"(?P<name>{_THING})\s+milestone", text, re.IGNORECASE))
    if not match:
        return None
    name = _clean_name(match["name"])
    if not name or rd.normalise(name) in _PRONOUNS:
        return None
    handle = _remember(state, name, "MILESTONE")
    return Hit(match.start(), match.end(),
               commands=[Proposal("add_milestone", {"name": name},
                                  f"Add a milestone called “{name}”.",
                                  creates=handle)],
               focus=handle)


def _rule_add_task(text: str, ctx: Context, state: dict) -> Hit | None:
    match = re.search(
        r"\badd\s+(?:a\s+)?task\s+(?:called|named|:)?\s*"
        rf"(?P<name>{_THING}){_END}", text, re.IGNORECASE)
    if not match:
        return None
    parent = state.get("focus_milestone") or _only_milestone(ctx)
    title = _clean_name(match["name"])
    if not title:
        return None
    if not parent:
        return Hit(match.start(), match.end(), questions=[Question(
            text="Which milestone does that task belong under?",
            field="milestone", fragment=title,
            options=[{"label": f"{row['code']} — {row['name']}",
                      "value": str(row["code"])}
                     for row in ctx.lexicon.all("MILESTONE")])])
    return Hit(match.start(), match.end(), commands=[Proposal(
        "add_task", {"milestone_code": parent, "title": title},
        f"Add “{title}” under {_pending_label(ctx, state, parent)}.",
        creates=_remember(state, title, "TASK"))], focus=parent)


def _only_milestone(ctx: Context) -> str:
    """The obvious parent when there is exactly one milestone to be under."""
    rows = ctx.lexicon.all("MILESTONE")
    return str(rows[0]["code"]) if len(rows) == 1 else ""


def _clean_name(said: Any) -> str:
    body = re.sub(r"^\s*(?:a|an|the)\s+", "", str(said or "").strip(),
                  flags=re.IGNORECASE)
    return body.strip(" .,;:\"'“”")


def _rule_link_after(text: str, ctx: Context, state: dict) -> Hit | None:
    """"Validation can only start after Model Development is finished." """
    match = (
        re.search(rf"(?P<succ>{_THING})\s+can(?:'?t|not)?\s+(?:only\s+)?"
                  rf"(?:start|begin)\s+(?:until|after|once)\s+(?P<pred>{_THING})"
                  r"\s+(?:is|has been|are)\s+(?:finished|complete[d]?|done)",
                  text, re.IGNORECASE)
        or re.search(rf"(?P<succ>{_THING})\s+can(?:'?t|not)?\s+(?:only\s+)?"
                     rf"(?:start|begin)\s+(?:until|after|once)\s+"
                     rf"(?P<pred>{_THING}){_END}", text, re.IGNORECASE)
        or re.search(rf"(?P<succ>{_THING})\s+(?:starts?|begins?)\s+"
                     rf"(?:only\s+)?after\s+(?P<pred>{_THING}){_END}",
                     text, re.IGNORECASE)
        or re.search(rf"(?P<pred>{_THING})\s+(?:must|has to|needs to)\s+"
                     r"(?:finish|be finished|be done|complete)\s+before\s+"
                     rf"(?P<succ>{_THING}){_END}", text, re.IGNORECASE))
    if not match:
        return None
    return _link(ctx, state, match, match["pred"], match["succ"])


def _rule_link_to(text: str, ctx: Context, state: dict) -> Hit | None:
    """"Link Data Reconciliation to Data Extraction."

    Read as "make the first wait for the second", which is what a person
    building a plan in order means. It is stated back before it is made, so
    the reading is visible rather than assumed.
    """
    match = re.search(
        rf"\blink\s+(?P<a>{_THING})\s+to\s+(?P<b>{_THING}){_END}",
        text, re.IGNORECASE)
    if not match:
        return None
    if re.search(r"previous\s+task", match["b"], re.IGNORECASE):
        found = _lookup(ctx, state, match["a"])
        if isinstance(found, Question):
            return Hit(match.start(), match.end(), questions=[found])
        if not found:
            return None
        before = dr.previous_task(ctx.plan, found)
        if not before:
            return Hit(match.start(), match.end(), questions=[Question(
                text=f"{_label(ctx, found)} is the first task under its "
                     "milestone, so there is no previous one.",
                field="task", fragment=match["a"])])
        return _made_link(ctx, before, found, match.start(), match.end())
    return _link(ctx, state, match, match["b"], match["a"])


def _lookup(ctx: Context, state: dict, said: Any) -> str | Question | None:
    """A code for something named, whether it exists yet or not."""
    if rd.normalise(said) in _PRONOUNS:
        return state.get("focus") or None
    handle = _pending_match(state, said)
    if handle:
        return handle
    found = _item(ctx, said)
    if found.ok and found.match:
        return found.match.key
    return _ask("item", str(said), found)


def _link(ctx: Context, state: dict, match: re.Match[str],
          pred_said: str, succ_said: str) -> Hit:
    questions: list[Question] = []
    before = _lookup(ctx, state, pred_said)
    after = _lookup(ctx, state, succ_said)
    for got in (before, after):
        if isinstance(got, Question):
            questions.append(got)
    if questions:
        return Hit(match.start(), match.end(), questions=questions)
    if not before or not after:
        return Hit(match.start(), match.end())
    assert isinstance(before, str) and isinstance(after, str)
    return _made_link(ctx, before, after, match.start(), match.end(),
                      state=state)


def _made_link(ctx: Context, before: str, after: str, start: int, end: int,
               state: dict | None = None) -> Hit:
    names = state["pending"] if state else {}
    left = names.get(before) or _label(ctx, before)
    right = names.get(after) or _label(ctx, after)
    return Hit(start, end, commands=[Proposal(
        "add_link", {"predecessor": before, "successor": after},
        f"{right} will wait for {left}.", preview=True)], focus=after)


def _rule_escalate_after(text: str, ctx: Context, state: dict) -> Hit | None:
    """"Escalate Validation tasks to Ananya after two days overdue."

    Two facts in one sentence: who hears about it, and when. The first is a
    property of the items; the second is the project's monitoring policy.
    Applying only the half that fits one command would be the kind of quiet
    partial obedience that makes an assistant untrustworthy.
    """
    match = re.search(
        rf"\bescalate\s+(?P<what>{_THING})\s+to\s+(?P<who>{_NAME})"
        r"(?:\s+(?:after|once)\s+(?P<count>[\w]+)\s+days?"
        r"(?:\s+(?:overdue|late|past due))?)?",
        text, re.IGNORECASE)
    if not match:
        return None
    person = _person(ctx, match["who"])
    if not person.ok or not person.match:
        return Hit(match.start(), match.end(),
                   questions=[_ask("escalation", match["who"], person)])
    user_id = person.match.payload["user_id"]

    rows = ctx.lexicon.matching(match["what"], kind=_kind_said(match["what"]))
    if not rows:
        found = _item(ctx, match["what"])
        if not found.ok or not found.match:
            return Hit(match.start(), match.end(),
                       questions=[_ask("item", match["what"], found)])
        rows = [dict(found.match.payload)]

    hit = Hit(match.start(), match.end())
    for row in rows:
        command = ("update_milestone" if row.get("kind") == "MILESTONE"
                   else "update_task")
        hit.commands.append(Proposal(
            command, {"code": row["code"], "escalation_id": user_id},
            f"{row['code']} — {row.get('name', '')} escalates to "
            f"{person.match.label}.", preview=True))
    days = rd.number(match["count"]) if match["count"] else None
    if days is not None:
        hit.commands.append(_custom_policy(
            ctx, {"escalate_after_days": days},
            f"The agent will escalate {days} day"
            f"{'' if days == 1 else 's'} after a date passes."))
    hit.focus = str(rows[0]["code"])
    return hit


def _kind_said(said: Any) -> str:
    """"Validation tasks" names tasks; "the Validation milestone" names one.

    Without this, "escalate Validation tasks to Ananya" resolves to the
    milestone called Validation and quietly does a third of what was asked.
    """
    text = rd.normalise(said)
    if re.search(r"\btasks?$", text):
        return "TASK"
    if re.search(r"\bmilestones?$", text):
        return "MILESTONE"
    return ""


def _custom_policy(ctx: Context, changes: dict[str, Any],
                   sentence: str) -> Proposal:
    """A threshold change, expressed as the project's own custom policy.

    Built on top of whatever the project already has rather than from the
    Standard preset, so "escalate after two days" does not silently reset a
    Critical project's other thresholds to standard ones.
    """
    agentic = (ctx.plan.get("agentic") or {})
    document = dict(agentic.get("policy") or {})
    if not document:
        current = pol.resolve(str(agentic.get("mode") or ""), None)
        document = dict(pol.describe(current).get("policy") or {})
    document.update(changes)
    return Proposal("set_agentic", {"mode": pol.MODE_CUSTOM,
                                    "policy": document},
                    sentence, preview=True)


def _rule_escalation_owner(text: str, ctx: Context, state: dict) -> Hit | None:
    """"Priya is the escalation owner" — for whatever we were just discussing."""
    match = re.search(
        rf"(?P<who>{_NAME})\s+(?:is|will be)\s+(?:the\s+)?escalation\s+"
        rf"(?:owner|contact|point)(?:\s+for\s+(?P<what>{_THING}))?{_END}",
        text, re.IGNORECASE)
    if not match:
        return None
    person = _person(ctx, match["who"])
    if not person.ok or not person.match:
        return Hit(match.start(), match.end(),
                   questions=[_ask("escalation", match["who"], person)])
    user_id = person.match.payload["user_id"]
    target = _target(ctx, state, match["what"])
    if isinstance(target, Question):
        return Hit(match.start(), match.end(), questions=[target])
    if not target:
        return Hit(match.start(), match.end(), commands=[Proposal(
            "set_governance", {"escalation_id": user_id},
            f"{person.match.label} is the project's escalation contact.",
            preview=True)])
    return Hit(match.start(), match.end(), commands=[_set_on(
        ctx, state, target, {"escalation_id": user_id},
        f"{_pending_label(ctx, state, target)} escalates to "
        f"{person.match.label}.")], focus=target)


def _target(ctx: Context, state: dict, said: Any) -> str | Question | None:
    """What a clause is about: what it named, or what we were just discussing."""
    text = str(said or "").strip()
    if text and rd.normalise(text) not in _PRONOUNS:
        handle = _pending_match(state, text)
        if handle:
            return handle
        found = _item(ctx, text)
        if found.ok and found.match:
            return found.match.key
        return _ask("item", text, found)
    return state.get("focus") or None


def _set_on(ctx: Context, state: dict, code: str, fields: dict[str, Any],
            sentence: str) -> Proposal:
    """Update whichever kind of thing this code names."""
    if code.startswith(PENDING):
        kind = state["pending_kind"].get(code, "MILESTONE")
    else:
        kind = dr.kind_of(ctx.plan, code)
    command = "update_milestone" if kind == "MILESTONE" else "update_task"
    return Proposal(command, {"code": code, **fields}, sentence, preview=True)


def _rule_owns(text: str, ctx: Context, state: dict) -> Hit | None:
    """"Sameer owns Data Extraction until 10 October." """
    match = (
        re.search(rf"(?P<who>{_NAME})\s+(?:owns|will own)\s+(?P<what>{_THING})"
                  r"\s+(?:until|by|due(?: on)?)\s+(?P<date>[^,.;]+?)"
                  rf"{_END}", text, re.IGNORECASE)
        or re.search(rf"(?P<who>{_NAME})\s+(?:owns|will own)\s+"
                     rf"(?P<what>{_THING})(?P<date>){_END}", text,
                     re.IGNORECASE)
        or re.search(rf"(?P<what>{_THING})\s+is\s+owned\s+by\s+"
                     rf"(?P<who>{_NAME})(?P<date>){_END}", text,
                     re.IGNORECASE))
    if not match:
        return None
    person = _person(ctx, match["who"])
    if not person.ok:
        # Two colleagues called Sameer is a question. A word that is nobody's
        # name means this was never a sentence about a person at all —
        # "Discovery owns nothing" — so another rule gets a turn.
        return (Hit(match.start(), match.end(),
                    questions=[_ask("owner", match["who"], person)])
                if person.state == rd.AMBIGUOUS else None)
    assert person.match
    target = _target(ctx, state, match["what"])
    if isinstance(target, Question):
        return Hit(match.start(), match.end(), questions=[target])
    if not target:
        return None
    fields: dict[str, Any] = {"owner_id": person.match.payload["user_id"]}
    words = (f"{_pending_label(ctx, state, target)} is owned by "
             f"{person.match.label}")
    when = rd.find_date(match["date"] or "", today=ctx.today,
                        window=ctx.window)
    if when:
        fields[_end_field(ctx, state, target)] = when.value.isoformat()
        words += f", due {when.value}"
    return Hit(match.start(), match.end(),
               commands=[_set_on(ctx, state, target, fields, words + ".")],
               focus=target)


def _end_field(ctx: Context, state: dict, code: str) -> str:
    if code.startswith(PENDING):
        kind = state["pending_kind"].get(code, "MILESTONE")
    else:
        kind = dr.kind_of(ctx.plan, code)
    return "target_date" if kind == "MILESTONE" else "due_date"


def _rule_move_to(text: str, ctx: Context, state: dict) -> Hit | None:
    """"Move M03-T02 to Daniel." """
    match = re.search(
        rf"\b(?:move|assign|reassign|give|hand)\s+(?P<what>{_THING})\s+"
        rf"(?:to|over to)\s+(?P<who>{_NAME}){_END}", text, re.IGNORECASE)
    if not match:
        return None
    person = _person(ctx, match["who"])
    if not person.ok:
        return (Hit(match.start(), match.end(),
                    questions=[_ask("owner", match["who"], person)])
                if person.state == rd.AMBIGUOUS else None)
    assert person.match
    target = _target(ctx, state, match["what"])
    if isinstance(target, Question):
        return Hit(match.start(), match.end(), questions=[target])
    if not target:
        return None
    return Hit(match.start(), match.end(), commands=[_set_on(
        ctx, state, target, {"owner_id": person.match.payload["user_id"]},
        f"{_pending_label(ctx, state, target)} moves to "
        f"{person.match.label}.")], focus=target)


_ROLES = {"sponsor": "sponsor_id", "manager": "manager_id",
          "project manager": "manager_id", "owner": "owner_id",
          "project owner": "owner_id"}


def _rule_governance_role(text: str, ctx: Context, state: dict) -> Hit | None:
    match = re.search(
        rf"(?P<who>{_NAME})\s+(?:is|will be)\s+(?:the\s+)?"
        r"(?P<role>project owner|project manager|sponsor|manager|owner)"
        rf"(?:\s+of\s+(?:this\s+)?project)?{_END}", text, re.IGNORECASE)
    if not match:
        return None
    person = _person(ctx, match["who"])
    if not person.ok:
        return (Hit(match.start(), match.end(),
                    questions=[_ask(match["role"].lower(), match["who"],
                                    person)])
                if person.state == rd.AMBIGUOUS else None)
    assert person.match
    field_name = _ROLES[match["role"].lower()]
    return Hit(match.start(), match.end(), commands=[Proposal(
        "set_governance", {field_name: person.match.payload["user_id"]},
        f"{person.match.label} is the project's "
        f"{match['role'].lower()}.", preview=True)])


_START_WORDS = r"(?:starts?|starting|begins?|beginning|runs from)"
_END_WORDS = r"(?:ends?|ending|finishes?|finishing|completes?|runs to)"


def _rule_period(text: str, ctx: Context, state: dict) -> Hit | None:
    """"It starts 1 October and ends 31 October." """
    match = re.search(
        rf"\b{_START_WORDS}\s+(?:on\s+|from\s+)?(?P<start>[^,.;]+?)"
        rf"(?:\s+and\s+{_END_WORDS}\s+(?:on\s+|by\s+)?(?P<end>[^,.;]+?))?"
        rf"{_END}", text, re.IGNORECASE)
    if not match:
        return None
    start = rd.find_date(match["start"], today=ctx.today, window=ctx.window)
    if not start:
        return None
    target = _target(ctx, state, _subject_before(text, match.start()))
    if isinstance(target, Question):
        target = state.get("focus") or None
    end = rd.find_date(match["end"] or "", today=ctx.today,
                       window=ctx.window) if match["end"] else None
    words = f"starts on {start.value}"
    if end:
        words += f" and ends on {end.value}"
    if not target:
        return Hit(match.start(), match.end(), commands=[Proposal(
            "set_governance",
            {"start_date": start.value.isoformat(),
             **({"target_end_date": end.value.isoformat()} if end else {})},
            f"The project {words}.", preview=True)])
    fields: dict[str, Any] = {"start_date": start.value.isoformat()}
    if end:
        fields[_end_field(ctx, state, target)] = end.value.isoformat()
    return Hit(match.start(), match.end(), commands=[_set_on(
        ctx, state, target, fields,
        f"{_pending_label(ctx, state, target)} {words}.")], focus=target)


def _subject_before(text: str, at: int) -> str:
    """What the clause before the verb was about, if it named anything.

    "Data Foundation starts 1 October" names its subject; "it starts
    1 October" does not, and falls through to whatever is in focus.
    """
    head = text[:at].strip()
    head = head[max(head.rfind(","), head.rfind(";")) + 1:].strip()
    head = re.sub(r"^(?:and|then|also|so)\b\s*", "", head, flags=re.IGNORECASE)
    return head if 0 < len(head.split()) <= 6 else ""


def _rule_due(text: str, ctx: Context, state: dict) -> Hit | None:
    """"Data Extraction is due 10 October." """
    match = re.search(
        rf"(?P<what>{_THING})\s+is\s+due\s+(?:on\s+|by\s+)?"
        rf"(?P<date>[^,.;]+?){_END}", text, re.IGNORECASE)
    if not match:
        return None
    when = rd.find_date(match["date"], today=ctx.today, window=ctx.window)
    if not when:
        return None
    target = _target(ctx, state, match["what"])
    if isinstance(target, Question):
        return Hit(match.start(), match.end(), questions=[target])
    if not target:
        return None
    return Hit(match.start(), match.end(), commands=[_set_on(
        ctx, state, target,
        {_end_field(ctx, state, target): when.value.isoformat()},
        f"{_pending_label(ctx, state, target)} is due {when.value}.")],
        focus=target)


def _rule_monitoring(text: str, ctx: Context, state: dict) -> Hit | None:
    """"Change this project's monitoring to Critical." """
    match = re.search(
        r"\b(?:set|change|switch|make|put)?\s*[^.;]{0,40}?"
        r"\b(?:monitoring|agentic(?:\s+ai)?|chasing|the agent)\b[^.;]{0,30}?"
        r"\bto\s+(?P<mode>light|standard|critical|custom)\b",
        text, re.IGNORECASE
    ) or re.search(
        r"\b(?:set|change|switch|make)\b[^.;]{0,40}?\bto\s+"
        r"(?P<mode>light|standard|critical)\s+monitoring\b", text,
        re.IGNORECASE)
    if not match:
        return None
    mode = match["mode"].upper()
    return Hit(match.start(), match.end(), commands=[Proposal(
        "set_agentic", {"mode": mode},
        f"The agent will monitor this project on {mode.title()}.",
        preview=True)])


def _rule_name_project(text: str, ctx: Context, state: dict) -> Hit | None:
    match = re.search(
        r"\b(?:call it|call the project|name it|the project is called"
        r"|it(?:'s| is) called)\s+(?:the\s+)?(?P<name>[^,.;]+?)"
        rf"{_END}", text, re.IGNORECASE)
    if not match:
        return None
    name = _clean_name(match["name"])
    if not name:
        return None
    return Hit(match.start(), match.end(), commands=[Proposal(
        "set_overview", {"name": name}, f"The project is called “{name}”.")])


def _rule_remove(text: str, ctx: Context, state: dict) -> Hit | None:
    match = re.search(
        rf"\b(?:remove|delete|drop|take out)\s+(?P<what>{_THING}){_END}",
        text, re.IGNORECASE)
    if not match:
        return None
    found = _item(ctx, match["what"])
    if not found.ok or not found.match:
        return Hit(match.start(), match.end(),
                   questions=[_ask("item", match["what"], found)])
    code = found.match.key
    kind = dr.kind_of(ctx.plan, code)
    command = "remove_milestone" if kind == "MILESTONE" else "remove_task"
    under = len(dr.tasks_of(ctx.plan, code)) if kind == "MILESTONE" else 0
    sentence = f"Remove {found.match.label}."
    if under:
        sentence += (f" That takes {under} task"
                     f"{'' if under == 1 else 's'} with it.")
    return Hit(match.start(), match.end(), commands=[Proposal(
        command, {"code": code}, sentence, preview=True)])


#: Order breaks ties between rules that match at the SAME point in a
#: sentence. Which rule fires first is decided by where it matches, not by
#: where it sits in this list, so a sentence is read left to right the way it
#: is written.
RULES = (
    _rule_add_tasks_under,
    _rule_add_milestones,
    _rule_add_milestone,
    _rule_add_task,
    _rule_escalate_after,
    _rule_escalation_owner,
    _rule_link_after,
    _rule_link_to,
    _rule_monitoring,
    _rule_name_project,
    _rule_governance_role,
    _rule_owns,
    _rule_move_to,
    _rule_remove,
    _rule_period,
    _rule_due,
)


# ------------------------------------------------------------- the reader


_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+|;\s*")


def read_with_rules(message: str, ctx: Context) -> Reading:
    """Everything the deterministic reader can make of this message."""
    found = Reading(source="rules", said=str(message or ""), focus=ctx.focus)
    state: dict[str, Any] = {
        "pending": {}, "pending_kind": {}, "next_pending": 0,
        "focus": ctx.focus, "focus_milestone": "",
    }
    if ctx.focus and dr.kind_of(ctx.plan, ctx.focus) == "MILESTONE":
        state["focus_milestone"] = ctx.focus

    for sentence in _SENTENCE.split(str(message or "")):
        body = sentence.strip()
        if not body:
            continue
        _read_sentence(body, ctx, state, found)

    found.focus = state["focus"] or ctx.focus
    return found


def _read_sentence(sentence: str, ctx: Context, state: dict,
                   found: Reading) -> None:
    """Consume a sentence rule by rule until nothing else fits.

    Each hit is blanked out rather than removed, so the offsets of everything
    still unread stay valid and "Rohan owns Data Foundation and Priya is the
    escalation owner" reads as two facts instead of one.
    """
    remaining = sentence
    for _ in range(8):  # a sentence with nine facts in it is not a sentence
        hit = _first_hit(remaining, ctx, state)
        if hit is None:
            break
        found.commands.extend(hit.commands)
        found.questions.extend(hit.questions)
        if hit.focus:
            state["focus"] = hit.focus
            kind = ("MILESTONE" if hit.focus.startswith(PENDING)
                    else dr.kind_of(ctx.plan, hit.focus))
            if hit.focus.startswith(PENDING):
                state["pending_kind"][hit.focus] = "MILESTONE"
            if kind == "MILESTONE":
                state["focus_milestone"] = hit.focus
        remaining = (remaining[:hit.start] + " " * (hit.end - hit.start)
                     + remaining[hit.end:])
    leftover = re.sub(r"\s+", " ", remaining).strip(" .,;")
    if leftover and _substantive(leftover):
        found.unread.append(leftover)


#: Words left behind by a rule that consumed the fact around them. A trailing
#: "and", "it" or "then" is punctuation, not something we failed to read, and
#: reporting it as unread would send a needless call to the model.
_GLUE = {"and", "then", "also", "so", "it", "this", "that", "the", "a", "an",
         "to", "for", "of", "with", "please", "there", "they", "we", "i",
         "plus", "but", "which"}


def _substantive(text: str) -> bool:
    words = [w for w in rd.normalise(text).split() if w not in _GLUE]
    return any(len(word) >= 3 for word in words)


def _first_hit(text: str, ctx: Context, state: dict) -> Hit | None:
    """The earliest thing this sentence says that we can read.

    Earliest rather than highest-priority, because a sentence is read left to
    right: "We need a Reporting milestone … and under it add three tasks"
    must create the milestone before it hangs anything off it, and the
    "under" rule matches further along the same sentence. Priority only
    breaks ties between rules matching at the same point.

    A rule may set up state (a pending handle) and then be discarded when an
    earlier rule wins, so rules are evaluated against a scratch copy and the
    winner is re-run against the real one.
    """
    if not re.search(r"[A-Za-z]", text):
        return None
    best: tuple[int, int, Any] | None = None
    for order, rule in enumerate(RULES):
        scratch = _scratch(state)
        try:
            hit = rule(text, ctx, scratch)
        except Exception:  # noqa: BLE001 - one bad rule must not eat the turn
            logger.exception("planner language rule failed: %s",
                             getattr(rule, "__name__", rule))
            continue
        if hit is None or not (hit.commands or hit.questions):
            continue
        if best is None or (hit.start, order) < (best[0], best[1]):
            best = (hit.start, order, rule)
    if best is None:
        return None
    return best[2](text, ctx, state)


def _scratch(state: dict) -> dict:
    """A throwaway copy, so a rule that loses does not leave handles behind."""
    return {**state, "pending": dict(state["pending"]),
            "pending_kind": dict(state["pending_kind"])}


# --------------------------------------------------------------- the model


#: What the model is allowed to say. Field values are the WORDS the person
#: used — never an id and never a code the model made up. Everything here is
#: resolved afterwards against the plan and the directory.
MODEL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "commands": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "command": {"type": "string",
                                "enum": list(dr.COMMANDS)},
                    "milestone": {"type": "string"},
                    "task": {"type": "string"},
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "owner": {"type": "string"},
                    "escalation": {"type": "string"},
                    "sponsor": {"type": "string"},
                    "manager": {"type": "string"},
                    "start_date": {"type": "string"},
                    "end_date": {"type": "string"},
                    "critical_date": {"type": "string"},
                    "predecessor": {"type": "string"},
                    "successor": {"type": "string"},
                    "mode": {"type": "string"},
                    "escalate_after_days": {"type": "integer"},
                    "priority": {"type": "string"},
                },
                "required": ["command"],
                "additionalProperties": False,
            },
        },
        "unread": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["commands"],
}

_SYSTEM = (
    "You are the reading half of a project planning assistant. You convert "
    "what somebody says about a DELIVERY PLAN into structured commands.\n\n"
    "Rules you must follow.\n"
    "1. Use only the listed commands. If what they said is not one of them, "
    "put the phrase in `unread`.\n"
    "2. Refer to people and to milestones and tasks by THE WORDS THE PERSON "
    "USED. Never invent an id, and never invent a code the plan does not "
    "already contain.\n"
    "3. Dates may be given as the person wrote them.\n"
    "4. Do not answer questions about credit risk, IFRS 9, scorecards, "
    "portfolios or any other part of the bank. You handle delivery only.\n"
    "5. If a sentence says two things — who owns something and when it is "
    "due — emit both.\n"
    "6. Never guess which of two similarly named things was meant. Leave the "
    "words as they were said; the resolver will ask."
)


def read_with_model(message: str, ctx: Context, *,
                    provider: Any = None) -> Reading | None:
    """Ask the configured model, then resolve what it says ourselves.

    Returns None when no provider is configured or the call fails: the rule
    reader's answer stands, and the Copilot says what it could not read
    rather than inventing a command.
    """
    from backend.llm import LLMError, get_provider

    provider = provider or get_provider()
    if not getattr(provider, "configured", False):
        return None

    catalogue = "\n".join(
        f"  {row['code']} ({row['kind'].lower()}): {row['name']}"
        for row in ctx.lexicon.rows) or "  (the plan is empty)"
    people = ", ".join(str(p.get("name") or p.get("username"))
                       for p in ctx.directory.people[:60]) or "(nobody yet)"
    prompt = (
        f"Today is {ctx.today.isoformat()}.\n\n"
        f"The plan currently contains:\n{catalogue}\n\n"
        f"People who can be named: {people}\n\n"
        f"The person said:\n{message}"
    )
    try:
        result = provider.structured(
            system=_SYSTEM, prompt=prompt, schema=MODEL_SCHEMA,
            tool_name="planner_commands",
            tool_description="The changes this message asks for.",
            purpose="reading", role="router", max_tokens=1500)
    except LLMError as exc:
        logger.info("planner language model call failed: %s", exc)
        return None
    except Exception:  # noqa: BLE001 - a provider fault is not a product fault
        logger.exception("planner language model call raised")
        return None
    return resolve_model(result.data or {}, ctx)


def resolve_model(document: dict[str, Any], ctx: Context) -> Reading:
    """Turn what the model said into resolved, validated proposals.

    Every reference goes through the same resolvers the rule reader uses, and
    a command the registry does not contain is dropped rather than attempted.
    This is the boundary: the model chooses WHAT, the plan and the directory
    decide WHICH.
    """
    found = Reading(source="model", focus=ctx.focus)
    state: dict[str, Any] = {"pending": {}, "pending_kind": {},
                             "next_pending": 0, "focus": ctx.focus}

    for entry in document.get("commands") or []:
        command = str(entry.get("command") or "")
        if command not in dr.COMMANDS:
            found.unread.append(f"“{command}” is not something I can do.")
            continue
        built = _from_model(command, dict(entry), ctx, state, found)
        if built:
            found.commands.append(built)
    for phrase in document.get("unread") or []:
        if str(phrase).strip():
            found.unread.append(str(phrase).strip())
    found.focus = state["focus"] or ctx.focus
    return found


def _from_model(command: str, entry: dict[str, Any], ctx: Context,
                state: dict, found: Reading) -> Proposal | None:
    """One model entry, with every name resolved or asked about."""

    def person(key: str) -> int | None:
        said = str(entry.get(key) or "").strip()
        if not said:
            return None
        got = _person(ctx, said)
        if not got.ok or not got.match:
            found.questions.append(_ask(key, said, got))
            return None
        return int(got.match.payload["user_id"])

    def when(key: str) -> str:
        said = str(entry.get(key) or "").strip()
        if not said:
            return ""
        got = rd.find_date(said, today=ctx.today, window=ctx.window)
        return got.value.isoformat() if got else ""

    def item(key: str, *, kind: str = "") -> str:
        said = str(entry.get(key) or "").strip()
        if not said:
            return ""
        for code, name in state["pending"].items():
            if rd.normalise(name) == rd.normalise(said):
                return code
        got = _item(ctx, said, kind=kind)
        if not got.ok or not got.match:
            found.questions.append(_ask(key, said, got))
            return ""
        return got.match.key

    if command == "add_milestone":
        name = _clean_name(entry.get("name") or entry.get("milestone"))
        if not name:
            return None
        index = state["next_pending"]
        state["next_pending"] += 1
        code = f"{PENDING}{index}"
        state["pending"][code] = name
        state["pending_kind"][code] = "MILESTONE"
        state["focus"] = code
        payload: dict[str, Any] = {"name": name}
        _carry(payload, {"owner_id": person("owner"),
                         "escalation_id": person("escalation"),
                         "start_date": when("start_date"),
                         "target_date": when("end_date")})
        return Proposal("add_milestone", payload,
                        f"Add a milestone called “{name}”.", source="model",
                        creates=code)

    if command == "add_task":
        title = _clean_name(entry.get("name") or entry.get("task"))
        parent = item("milestone", kind="MILESTONE") or state.get("focus", "")
        if not title or not parent:
            return None
        payload = {"title": title, "milestone_code": parent}
        _carry(payload, {"owner_id": person("owner"),
                         "escalation_id": person("escalation"),
                         "start_date": when("start_date"),
                         "due_date": when("end_date"),
                         "description": entry.get("description")})
        return Proposal("add_task", payload,
                        f"Add “{title}” under "
                        f"{_pending_label(ctx, state, parent)}.",
                        source="model")

    if command in {"update_milestone", "update_task"}:
        code = (item("milestone", kind="MILESTONE")
                if command == "update_milestone" else item("task"))
        code = code or state.get("focus", "")
        if not code:
            return None
        end_key = "target_date" if command == "update_milestone" else "due_date"
        payload = {"code": code}
        _carry(payload, {"owner_id": person("owner"),
                         "escalation_id": person("escalation"),
                         "start_date": when("start_date"),
                         end_key: when("end_date"),
                         "critical_date": when("critical_date")})
        if len(payload) == 1:
            return None
        state["focus"] = code
        return Proposal(command, payload,
                        f"Change {_pending_label(ctx, state, code)}.",
                        preview=True, source="model")

    if command == "add_link":
        before, after = item("predecessor"), item("successor")
        if not before or not after:
            return None
        return Proposal("add_link", {"predecessor": before,
                                     "successor": after},
                        f"{_label(ctx, after)} will wait for "
                        f"{_label(ctx, before)}.", preview=True,
                        source="model")

    if command == "set_agentic":
        mode = str(entry.get("mode") or "").upper()
        days = entry.get("escalate_after_days")
        if days is not None:
            return _custom_policy(ctx, {"escalate_after_days": int(days)},
                                  f"The agent will escalate {int(days)} days "
                                  "after a date passes.")
        if mode not in pol.MODES:
            return None
        return Proposal("set_agentic", {"mode": mode},
                        f"The agent will monitor this project on "
                        f"{mode.title()}.", preview=True, source="model")

    if command == "set_governance":
        payload = {}
        _carry(payload, {"sponsor_id": person("sponsor"),
                         "manager_id": person("manager"),
                         "owner_id": person("owner"),
                         "escalation_id": person("escalation"),
                         "start_date": when("start_date"),
                         "target_end_date": when("end_date")})
        if not payload:
            return None
        return Proposal("set_governance", payload,
                        "Set the project's governance.", preview=True,
                        source="model")

    if command == "set_overview":
        name = _clean_name(entry.get("name"))
        if not name:
            return None
        return Proposal("set_overview", {"name": name},
                        f"The project is called “{name}”.", source="model")

    if command in {"remove_milestone", "remove_task"}:
        code = item("milestone" if command == "remove_milestone" else "task")
        if not code:
            return None
        return Proposal(command, {"code": code},
                        f"Remove {_label(ctx, code)}.", preview=True,
                        source="model")
    return None


def _carry(payload: dict[str, Any], fields: dict[str, Any]) -> None:
    for key, value in fields.items():
        if value not in (None, ""):
            payload[key] = value


# ------------------------------------------------------------------- read


def read(message: str, ctx: Context, *, provider: Any = None) -> Reading:
    """Read a message with the rules, and ask the model about the rest.

    The rules go first because they are exact, free and available offline.
    The model is asked only about leftovers, so a live provider makes the
    Copilot understand MORE phrasings and never makes it understand a
    sentence differently.
    """
    found = read_with_rules(message, ctx)
    if not found.unread:
        return found

    leftovers = " ".join(found.unread)
    helped = read_with_model(leftovers, ctx, provider=provider)
    if helped is None or not helped.commands:
        return found

    merged = Reading(
        commands=[*found.commands, *helped.commands],
        questions=[*found.questions, *helped.questions],
        unread=list(helped.unread),
        source="rules+model" if found.commands else "model",
        focus=helped.focus or found.focus, said=found.said)
    return merged


# ------------------------------------------------------------------ apply


def apply_all(session: Any, principal: Any, key: str,
              proposals: list[Proposal], *, source: str = "") -> dict[str, Any]:
    """Run resolved proposals through the ordinary draft writer, in order.

    `$new:` references are substituted from what the earlier commands
    actually created, so "add a milestone, then put three tasks under it"
    works in one message without the reader having to invent a code.

    Nothing here validates anything. `draft.apply` does — that is the point:
    a proposal is a request, and the same layer that refuses a bad form
    refuses a bad sentence.
    """
    from backend.models.planner import SOURCE_AI_CHAT

    made: dict[str, str] = {}
    outcomes: list[dict[str, Any]] = []
    for proposal in proposals:
        payload = {k: _substitute(v, made) for k, v in proposal.payload.items()}
        unfilled = [v for v in payload.values()
                    if isinstance(v, str) and v.startswith(PENDING)]
        if unfilled:
            raise dr.DraftError(
                "I lost track of something I was about to create. Say that "
                "again and I will start from what is in the plan now.")
        outcome = dr.apply(session, principal, key, proposal.command, payload,
                           source=source or SOURCE_AI_CHAT)
        code = str(outcome.get("code") or "")
        if proposal.creates and code:
            made[proposal.creates] = code
        outcomes.append({"command": proposal.command,
                         "sentence": proposal.sentence,
                         "code": code, "outcome": outcome})
    return {"applied": outcomes, "created": made}


def _substitute(value: Any, made: dict[str, str]) -> Any:
    if isinstance(value, str) and value.startswith(PENDING):
        return made.get(value, value)
    return value


__all__ = [
    "Context", "LANGUAGE_VERSION", "MODEL_SCHEMA", "PENDING", "Proposal",
    "Question", "RULES", "Reading", "apply_all", "read", "read_with_model",
    "read_with_rules", "resolve_model",
]
