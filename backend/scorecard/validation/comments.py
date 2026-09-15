"""§15: what a person says about a result, beside the result and never over it.

The rule this module exists to enforce
---------------------------------------
An analyst may disagree with a number. An analyst may not change one, and
may not relabel a check that did not run as one that passed. §15 says so,
and the way it is enforced here is structural rather than by validation:
this module writes to the comments table and has no path to a result row at
all. `ScvResult` is written once and has no update path in the service or
the API; a comment carries the author's own `severity` and `assessment`,
which a report prints BESIDE the measured state with both labelled. There is
no field a screen could read that would let a comment's severity be mistaken
for a verdict.

What a comment is attached to
------------------------------
Four things, and the key is the MODEL and the target — not the run.

    scv_category    a category card          model_id:category
    scv_result      a test-evidence card     model_id:test_id
    scv_finding     a finding                model_id:finding_id
    scv_conclusion  the overall opinion      model_id

Keyed on the model so a comment survives a refresh, a category switch, a
model switch back, a logout and a restart — §15's list. The RUN it was made
against lives in `context`, so the screen and the report can both say
whether the comment was written about what is currently on screen. That is
the other half of §15's requirement, and it is the half that is easy to get
wrong: a comment keyed on the run disappears the moment anybody re-runs,
and a comment keyed on the model with no run recorded silently becomes a
comment about the new run. Neither is acceptable, so it is keyed on the
model AND carries the run.

Editing
--------
An edit writes a NEW row that supersedes the old one, and the old row is
left exactly as written. `history()` returns the chain. A comment is
evidence; a table that permits editing one in place is a table in which
"what did the reviewer actually say before they changed it?" has no answer.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

COMMENTS_VERSION = "retail-validation-comments-1.0.0"

CATEGORY = "scv_category"
RESULT = "scv_result"
FINDING = "scv_finding"
CONCLUSION = "scv_conclusion"

TARGETS: tuple[str, ...] = (CATEGORY, RESULT, FINDING, CONCLUSION)

TARGET_MEANING: dict[str, str] = {
    CATEGORY: "a validation category",
    RESULT: "one test's evidence",
    FINDING: "a finding raised by the engine",
    CONCLUSION: "the overall validation opinion",
}

#: What each `kind` means in a report, printed beside the comment so a
#: reader never has to infer whether they are looking at a measurement, an
#: opinion or a decision. §15: these three must not read as the same thing.
KIND_MEANING: dict[str, str] = {
    "COMMENT": "A note. Neither an assessment nor a decision.",
    "ANALYST": "The validator's own assessment. Their opinion about a "
               "measured result, recorded beside it and never in place of "
               "it.",
    "REVIEWER": "A second-line response to an assessment.",
    "APPROVER": "A decision taken on the strength of the evidence. The only "
                "kind that commits the institution to anything.",
}

ASSESSMENT_MEANING: dict[str, str] = {
    "AGREED": "The author accepts the result and what the engine made of it.",
    "DISAGREED": "The author disputes the engine's reading. The measured "
                 "value is unchanged and is printed beside this.",
    "ACCEPTED_WITH_ACTION": "Accepted, with something to be done about it.",
    "NEEDS_EVIDENCE": "Not assessable on what is here. Something further is "
                      "required before an opinion can be given.",
    "NOT_ASSESSED": "Recorded without an assessment.",
}


class CommentRefused(ValueError):
    """A comment was asked for in a shape that would not be evidence."""


def _now() -> datetime:
    return datetime.now(UTC)


def key_for(target: str, model_id: str, *, category: str = "",
            test_id: str = "", finding_id: str = "") -> str:
    """The object id for one commentable thing."""
    if target == CATEGORY:
        if not category:
            raise CommentRefused("A category comment names its category.")
        return f"{model_id}:{category}"
    if target == RESULT:
        if not test_id:
            raise CommentRefused("A result comment names its test.")
        return f"{model_id}:{test_id}"
    if target == FINDING:
        if not finding_id:
            raise CommentRefused("A finding comment names its finding.")
        return f"{model_id}:{finding_id}"
    if target == CONCLUSION:
        return model_id
    raise CommentRefused(
        f"{target!r} is not something this module comments on. They are: "
        + ", ".join(TARGETS))


def context_for(model: Any, *, run: Any = None, category: str = "",
                test_id: str = "", finding_id: str = "",
                result: Any = None) -> dict[str, Any]:
    """What the comment was made against, taken from the objects themselves.

    Never from the request body, for the same reason the author is not: a
    caller that could state its own context could attach a comment to a run
    it was not written about, and the whole value of the field is that it
    cannot.
    """
    from backend.scorecard.validation import registry as test_registry

    context: dict[str, Any] = {
        "model_id": model.model_id,
        "model_version": model.version,
        "model_name": model.name,
        "comments_version": COMMENTS_VERSION,
        "registry_version": test_registry.REGISTRY_VERSION,
    }
    if category:
        context["category"] = category
        entry = test_registry.BY_CATEGORY_KEY.get(category)
        if entry is not None:
            context["category_title"] = entry.title
    if test_id:
        context["test_id"] = test_id
        test = test_registry.BY_ID.get(test_id)
        if test is not None:
            context["test_name"] = test.name
            context["test_version"] = test.version
            context.setdefault("category", test.category)
    if finding_id:
        context["finding_id"] = finding_id
    if run is not None:
        # Read off the stored run rather than off the request: the run's own
        # columns are what a report will quote, and a context assembled from
        # anything else is a context that can disagree with the evidence it
        # claims to describe.
        context.update({
            "run_key": getattr(run, "run_key", "") or "",
            "run_started_at": _stamp(getattr(run, "started_at", None)),
            "period": getattr(run, "latest_period", "") or "",
            "matured_window": getattr(run, "matured_window", "") or "",
            "reference_period": getattr(run, "reference_period", "") or "",
            "dataset": getattr(run, "dataset", "") or "",
            "dataset_as_of": getattr(run, "dataset_as_of", "") or "",
            "dataset_version": getattr(run, "dataset_version", "") or "",
            "calculation_version": getattr(run, "calculation_version", "") or "",
            "threshold_profile_version": getattr(
                run, "threshold_profile_version", "") or "",
        })
    if result is not None:
        # The state and value as they stood when the comment was written.
        # Recorded so a later reader can see whether the thing being
        # disagreed with is still what the engine says — not so that the
        # comment can change it.
        context["result_state_when_written"] = getattr(result, "state", "")
        context["result_value_when_written"] = getattr(result, "value", None)
    return {k: v for k, v in context.items() if v not in ("", None)}


def _stamp(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    return str(value)


def add(session: Any, *, target: str, model: Any, body: str,
        author_id: int | None, author_name: str = "",
        kind: str = "COMMENT", assessment: str = "", severity: str = "",
        category: str = "", test_id: str = "", finding_id: str = "",
        run: Any = None, result: Any = None,
        attachments: list[dict[str, Any]] | None = None,
        parent_id: int | None = None) -> dict[str, Any]:
    """Write one comment against one thing, with its context."""
    from backend.models.platform import Comment

    text = (body or "").strip()
    if not text:
        raise CommentRefused(
            "A comment needs something in it. An empty note attached to a "
            "validation result reads, six months later, as somebody having "
            "looked and found nothing worth saying.")
    if kind not in Comment.KINDS:
        raise CommentRefused(
            f"{kind!r} is not a kind of comment. They are: "
            + ", ".join(Comment.KINDS))
    if assessment and assessment not in Comment.ASSESSMENTS:
        raise CommentRefused(
            f"{assessment!r} is not an assessment. They are: "
            + ", ".join(Comment.ASSESSMENTS))
    if severity:
        from backend.scorecard.validation import findings as finding_engine

        if severity not in finding_engine.SEVERITIES:
            raise CommentRefused(
                f"{severity!r} is not a severity. They are: "
                + ", ".join(finding_engine.SEVERITIES))

    object_id = key_for(target, model.model_id, category=category,
                        test_id=test_id, finding_id=finding_id)
    context = context_for(model, run=run, category=category, test_id=test_id,
                          finding_id=finding_id, result=result)
    if author_name:
        context["author_name"] = author_name

    row = Comment(
        object_type=target, object_id=object_id, parent_id=parent_id,
        body=text, author_id=author_id, kind=kind, assessment=assessment,
        severity=severity, context=context,
        attachments=list(attachments or []))
    session.add(row)
    session.flush()
    return body_of(session, row)


def edit(session: Any, comment_id: int, *, body: str, author_id: int | None,
         assessment: str | None = None, severity: str | None = None,
         attachments: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Replace a comment by writing a new one that supersedes it.

    The old row keeps its text, its author and its timestamp. What changes
    is that it now points forward, so a reader following the chain sees what
    was said and what it became.
    """
    from backend.models.platform import Comment

    old = session.get(Comment, comment_id)
    if old is None:
        raise CommentRefused(f"Comment {comment_id} does not exist.")
    if old.edited_at is not None:
        raise CommentRefused(
            f"Comment {comment_id} has already been superseded. Edit the "
            "comment that replaced it, not the one it replaced — an edit "
            "chain that forks has no 'current' version.")
    text = (body or "").strip()
    if not text:
        raise CommentRefused("An edit that empties a comment is a deletion, "
                             "and this record does not delete.")

    made = Comment(
        object_type=old.object_type, object_id=old.object_id,
        parent_id=old.parent_id, body=text, author_id=author_id,
        kind=old.kind,
        assessment=old.assessment if assessment is None else assessment,
        severity=old.severity if severity is None else severity,
        context=dict(old.context or {}),
        attachments=(list(old.attachments or []) if attachments is None
                     else list(attachments)),
        resolved=old.resolved, supersedes_id=old.id)
    session.add(made)
    old.edited_at = _now()
    session.flush()
    return body_of(session, made)


def resolve(session: Any, comment_id: int, *,
            resolved: bool = True) -> dict[str, Any]:
    from backend.models.platform import Comment

    row = session.get(Comment, comment_id)
    if row is None:
        raise CommentRefused(f"Comment {comment_id} does not exist.")
    row.resolved = resolved
    session.flush()
    return body_of(session, row)


def _author(session: Any, row: Any) -> str:
    stored = (row.context or {}).get("author_name")
    if stored:
        return str(stored)
    if row.author_id is None:
        return ""
    from backend.db.models import User

    user = session.get(User, row.author_id)
    return getattr(user, "username", "") if user is not None else ""


def body_of(session: Any, row: Any) -> dict[str, Any]:
    from backend.models.platform import Comment

    context = dict(row.context or {})
    return {
        "comments_version": COMMENTS_VERSION,
        "id": row.id,
        "target": row.object_type,
        "target_meaning": TARGET_MEANING.get(row.object_type, ""),
        "object_id": row.object_id,
        "parent_id": row.parent_id,
        "body": row.body,
        "kind": row.kind,
        "kind_meaning": KIND_MEANING.get(row.kind, ""),
        "assessment": row.assessment,
        "assessment_meaning": ASSESSMENT_MEANING.get(row.assessment, ""),
        "severity": row.severity,
        # Said out loud on every comment that carries one, because a severity
        # on an opinion sitting next to a severity on a measurement is
        # exactly the pair a reader would otherwise merge.
        "severity_is_the_authors": bool(row.severity),
        "resolved": row.resolved,
        "author_id": row.author_id,
        "author": _author(session, row),
        "created_at": _stamp(row.created_at),
        "edited_at": _stamp(row.edited_at),
        "superseded": row.edited_at is not None,
        "supersedes_id": row.supersedes_id,
        "attachments": list(row.attachments or []),
        "context": context,
        "run_key": context.get("run_key", ""),
        "assessments_available": list(Comment.ASSESSMENTS),
    }


def _rows(session: Any, *, object_type: str = "",
          object_ids: list[str] | None = None,
          run_key: str = "") -> list[Any]:
    from sqlalchemy import select

    from backend.models.platform import Comment

    query = select(Comment).where(Comment.object_type.in_(TARGETS))
    if object_type:
        query = query.where(Comment.object_type == object_type)
    if object_ids:
        query = query.where(Comment.object_id.in_(object_ids))
    if run_key:
        query = query.where(Comment.context["run_key"].astext == run_key)
    return list(session.execute(query.order_by(Comment.created_at))
                .scalars().all())


def listing(session: Any, *, model_id: str, run_key: str = "",
            category: str = "", test_id: str = "",
            include_superseded: bool = False) -> list[dict[str, Any]]:
    """Every live comment on this model, newest last, with its run marked.

    `run_key` does NOT filter. It marks: each comment comes back with
    `made_against_this_run` saying whether it was written about the run
    currently on screen. §15 forbids a comment silently attaching itself to
    a later run, and hiding the earlier ones would be the same mistake in
    the other direction — the reader would never learn that somebody had
    already looked at this test and said something about it.
    """
    rows = _rows(session)
    out: list[dict[str, Any]] = []
    for row in rows:
        if not row.object_id.startswith(f"{model_id}:") \
                and row.object_id != model_id:
            continue
        if not include_superseded and row.edited_at is not None:
            continue
        context = row.context or {}
        if category and context.get("category") != category \
                and row.object_type == CATEGORY:
            continue
        if test_id and context.get("test_id") != test_id \
                and row.object_type == RESULT:
            continue
        made = body_of(session, row)
        made["made_against_this_run"] = (
            bool(run_key) and made["run_key"] == run_key)
        made["run_note"] = _run_note(made, run_key)
        out.append(made)
    return out


def _run_note(made: dict[str, Any], run_key: str) -> str:
    if not made["run_key"]:
        return ("Written without a recorded run, so it cannot be tied to a "
                "particular set of numbers.")
    if not run_key:
        return f"Written against run {made['run_key']}."
    if made["made_against_this_run"]:
        return "Written against the run on screen."
    return (f"Written against run {made['run_key']}, which is not the run on "
            "screen. The numbers it refers to are that run's.")


def for_run(session: Any, run_key: str, *,
            model_id: str = "") -> list[dict[str, Any]]:
    """Every comment made against one recorded run. What the report prints."""
    rows = _rows(session, run_key=run_key)
    out = []
    for row in rows:
        if row.edited_at is not None:
            continue
        if model_id and not (row.object_id.startswith(f"{model_id}:")
                             or row.object_id == model_id):
            continue
        made = body_of(session, row)
        made["made_against_this_run"] = True
        made["run_note"] = "Written against this run."
        out.append(made)
    return out


def history(session: Any, comment_id: int) -> list[dict[str, Any]]:
    """The whole edit chain, oldest first."""
    from sqlalchemy import select

    from backend.models.platform import Comment

    row = session.get(Comment, comment_id)
    if row is None:
        raise CommentRefused(f"Comment {comment_id} does not exist.")
    # Back to the original.
    chain = [row]
    while chain[0].supersedes_id:
        earlier = session.get(Comment, chain[0].supersedes_id)
        if earlier is None:
            break
        chain.insert(0, earlier)
    # Forward to the current one.
    while True:
        later = session.execute(
            select(Comment).where(Comment.supersedes_id == chain[-1].id)
        ).scalars().first()
        if later is None:
            break
        chain.append(later)
    return [body_of(session, one) for one in chain]


def summary(comments: list[dict[str, Any]]) -> dict[str, Any]:
    """What the drawer's heading says, and what the report's section says."""
    open_now = [c for c in comments if not c["resolved"]]
    by_kind: dict[str, int] = {}
    for one in comments:
        by_kind[one["kind"]] = by_kind.get(one["kind"], 0) + 1
    disagreements = [c for c in comments if c["assessment"] == "DISAGREED"]
    return {
        "comments": len(comments),
        "open": len(open_now),
        "resolved": len(comments) - len(open_now),
        "by_kind": by_kind,
        "disagreements": len(disagreements),
        "from_another_run": sum(
            1 for c in comments if not c.get("made_against_this_run", True)),
        "separation": (
            "System-calculated findings, analyst commentary and approver "
            "decisions are recorded as different kinds and are never merged. "
            "A comment carries the author's own severity where they gave "
            "one; it sits beside the measured state and does not replace it."),
    }
