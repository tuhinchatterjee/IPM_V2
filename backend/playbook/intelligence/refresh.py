"""Check for updates, and propose — never rewrite. §16, §23, §24.

The rule this module exists to hold
-----------------------------------
**Never silently rewrite the document because data arrived.** New data is a
reason to tell somebody, not a licence to edit a governed pack. So everything
here is a read that produces a PROPOSAL: what has moved, which sections rest
on it, which findings were raised against a figure that has since changed, and
which decisions were framed on a position that may no longer hold. Applying
any of it is a separate, explicit act by a person.

What counts as an update
------------------------
Only governed facts. A suggested metric link that nobody has confirmed does
not make a section stale, does not satisfy a required metric, and does not
appear here as a reason to refresh anything — it appears as *"9 suggested
links waiting for review"*, which is a different sentence with a different
remedy.

Freshness is `new_data_available` or `stale`; `unknown` is deliberately
excluded, because not knowing whether something moved is not evidence that it
did.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from backend.models.playbook import (
    PlaybookDecision,
    PlaybookFinding,
    PlaybookMetricBinding,
)
from backend.playbook import reparse
from backend.playbook.intelligence import binding as bind
from backend.playbook.intelligence import compare
from backend.playbook.intelligence import governance as gov
from backend.playbook.intelligence import sections as sect
from backend.playbook.intelligence import service as svc


@dataclass
class Proposal:
    """What a refresh WOULD do. Nothing here has been done."""

    metrics_with_newer_values: list[dict] = field(default_factory=list)
    sections_affected: list[dict] = field(default_factory=list)
    findings_to_reconsider: list[dict] = field(default_factory=list)
    decisions_to_revisit: list[dict] = field(default_factory=list)
    sources_needing_reread: list[dict] = field(default_factory=list)
    suggestions_awaiting_review: list[dict] = field(default_factory=list)

    @property
    def anything(self) -> bool:
        return bool(self.metrics_with_newer_values or self.sections_affected
                    or self.findings_to_reconsider
                    or self.decisions_to_revisit
                    or self.sources_needing_reread
                    or self.suggestions_awaiting_review)

    def lines(self) -> list[str]:
        """The review summary, one sentence per kind, counts first."""
        out = []
        for count, singular, plural in (
            (len(self.metrics_with_newer_values),
             "metric has a newer value", "metrics have newer values"),
            (len(self.sections_affected),
             "section is affected", "sections are affected"),
            (len(self.findings_to_reconsider),
             "finding may need reconsidering",
             "findings may need reconsidering"),
            (len(self.decisions_to_revisit),
             "decision may need updated wording",
             "decisions may need updated wording"),
            (len(self.sources_needing_reread),
             "source needs re-reading", "sources need re-reading"),
            (len(self.suggestions_awaiting_review),
             "suggested metric link is waiting for review",
             "suggested metric links are waiting for review"),
        ):
            if count:
                out.append(f"{count} {singular if count == 1 else plural}")
        return out

    def as_dict(self) -> dict:
        return {
            "anything": self.anything,
            "summary": self.lines(),
            "message": ("Nothing has changed since this document was written."
                        if not self.anything else "; ".join(self.lines())),
            "metrics": list(self.metrics_with_newer_values),
            "sections": list(self.sections_affected),
            "findings": list(self.findings_to_reconsider),
            "decisions": list(self.decisions_to_revisit),
            "sources": list(self.sources_needing_reread),
            "suggestions": list(self.suggestions_awaiting_review),
        }


def check(session, workspace_id: int) -> Proposal:
    """Look, and say what a person might want to do. Change nothing."""
    proposal = Proposal()

    bindings = (session.query(PlaybookMetricBinding)
                .filter(PlaybookMetricBinding.workspace_id == workspace_id)
                .all())
    governed = [b for b in bindings if bind.is_governed(b)]

    # --- metrics that have moved -----------------------------------------
    #
    # Two independent signals, and both are governed facts rather than
    # guesses: the binding says its reading is superseded, or the frozen
    # snapshot the document relied on differs from what the binding says now.
    moved: dict[int, dict] = {}
    for row in governed:
        if row.freshness in bind.NEEDS_ATTENTION:
            moved[row.id] = {
                "binding_id": row.id, "metric_id": row.metric_id,
                "label": row.label or row.metric_id,
                "value": row.display_value, "freshness": row.freshness,
                "section_key": row.section_key,
                "source_locator": row.source_locator,
                "reason": "the source reports a newer reading",
            }

    table = compare.since_last_time(session, workspace_id)
    by_metric = {b.metric_id: b for b in governed}
    for comparison in table.get("rows", []):
        if not comparison.get("comparable"):
            continue
        if comparison.get("direction") in ("", "unchanged"):
            continue
        row = by_metric.get(comparison["metric_id"])
        if row is None:
            continue
        moved.setdefault(row.id, {
            "binding_id": row.id, "metric_id": row.metric_id,
            "label": row.label or row.metric_id,
            "value": row.display_value, "freshness": row.freshness,
            "section_key": row.section_key,
            "source_locator": row.source_locator,
        })
        moved[row.id].update({
            "then": comparison["then"]["display"],
            "now": comparison["now"]["display"],
            "change": comparison.get("change", ""),
            "change_unit": comparison.get("change_unit", ""),
            "direction": comparison.get("direction", ""),
            "reason": ("the document relied on a different value: "
                       f"{comparison['then']['display']} → "
                       f"{comparison['now']['display']}"),
        })
    proposal.metrics_with_newer_values = sorted(
        moved.values(), key=lambda m: m["label"])

    # --- the sections that rest on them ----------------------------------
    artifact = svc._current_artifact(session, workspace_id)
    headings = {}
    if artifact is not None:
        headings = {r.section_key: r for r in sect.rows_for(session,
                                                            artifact.id)}
    affected: dict[str, dict] = {}
    for metric in proposal.metrics_with_newer_values:
        key = metric.get("section_key") or ""
        if not key or key not in headings:
            continue
        entry = affected.setdefault(key, {
            "section_key": key, "heading": headings[key].heading,
            "status": headings[key].status, "metrics": []})
        entry["metrics"].append(metric["label"])
    proposal.sections_affected = sorted(affected.values(),
                                        key=lambda s: s["heading"])

    # --- findings raised against a figure that has since moved ------------
    changed_ids = {m["metric_id"] for m in proposal.metrics_with_newer_values}
    for finding in (session.query(PlaybookFinding)
                    .filter(PlaybookFinding.workspace_id == workspace_id)
                    .all()):
        if finding.metric_id and finding.metric_id in changed_ids:
            proposal.findings_to_reconsider.append({
                "finding_id": finding.id,
                "reference": finding.reference,
                "title": finding.title,
                "severity": finding.severity,
                "status": finding.status,
                "metric_id": finding.metric_id,
                "recorded_value": finding.current_value,
                "reason": ("this finding was raised against a value that has "
                           "since changed"),
            })

    # --- decisions framed on a position that may have moved ---------------
    related_findings = {f["finding_id"] for f in
                        proposal.findings_to_reconsider}
    for decision in (session.query(PlaybookDecision)
                     .filter(PlaybookDecision.workspace_id == workspace_id)
                     .all()):
        if decision.status in (gov.DECIDED, gov.WITHDRAWN):
            continue
        linked = set(decision.related_finding_ids or []) & related_findings
        if not (linked or (changed_ids and decision.status
                           == gov.READY_FOR_DECISION and related_findings)):
            continue
        proposal.decisions_to_revisit.append({
            "decision_id": decision.id,
            "reference": decision.reference,
            "question": decision.question,
            "status": decision.status,
            "reason": ("the evidence behind this decision has moved since it "
                       "was framed"),
        })

    # --- sources and suggestions -----------------------------------------
    proposal.sources_needing_reread = [
        s.as_dict() for s in reparse.stale(session, workspace_id)]
    proposal.suggestions_awaiting_review = [
        {"binding_id": b.id, "label": b.label or b.metric_id,
         "metric_id": b.metric_id, "value": b.display_value,
         "confidence": b.confidence, "source_locator": b.source_locator}
        for b in bindings
        if b.binding_method == bind.SUGGESTED and not b.confirmed_by_user]

    return proposal


# --------------------------------------------------------------------------
# A new upload, against what this document already tracks. §24
# --------------------------------------------------------------------------


def proposals_from_source(session, workspace_id: int,
                          source_id: int) -> dict:
    """Which tracked metrics a newly uploaded file appears to update.

    Appears to. Every row here is a SUGGESTION and says so: a column header
    resembling a metric this document tracks is not evidence that it is that
    metric, and confirming it is a person's act. Until then the uploaded value
    is visible and is not a governed current value.
    """
    from backend.models.playbook import PlaybookSource
    from backend.playbook import repository as repo

    source = session.get(PlaybookSource, source_id)
    if source is None or source.workspace_id != workspace_id:
        raise repo.NotFound(f"No source {source_id} in this document.")

    tracked = {b.metric_id: b for b in
               (session.query(PlaybookMetricBinding)
                .filter(PlaybookMetricBinding.workspace_id == workspace_id)
                .all())
               if b.metric_id and bind.is_governed(b)}

    rows = []
    for chunk in repo.chunks(session, source.id):
        for label, shown, raw, cell in _readings(chunk):
            guess = bind.suggest_from_label(label)
            if guess is None:
                continue
            metric_id, _unit, confidence = guess
            current = tracked.get(metric_id)
            if current is None:
                continue
            rows.append({
                "metric_id": metric_id,
                "document_metric": current.label or metric_id,
                "current_document_value": current.display_value,
                "uploaded_label": label,
                "uploaded_value": shown,
                "uploaded_raw_value": raw,
                "source": source.filename,
                "source_locator": bind.cell_locator(chunk.locator, cell),
                "confidence": confidence,
                # Never "confirmed". A resemblance is not an identity.
                "match_status": bind.SUGGESTED,
                "binding_id": current.id,
                "changes_value": (str(shown).strip()
                                  != str(current.display_value).strip()),
            })

    return {
        "source_id": source.id,
        "filename": source.filename,
        "detected": len(rows),
        "message": _upload_message(len(rows)),
        "rows": rows,
    }


def _upload_message(count: int) -> str:
    if not count:
        return ("Nothing in this file appears to update a metric this "
                "document tracks.")
    return (f"{count} value{'s' if count != 1 else ''} in this file "
            f"appear{'' if count != 1 else 's'} to update metrics already "
            "tracked by this document.")


def _readings(chunk) -> list[tuple[str, str, str, str]]:
    """`(label, shown, raw, cell)` per row of a sheet chunk.

    A label in the first column and a value in the second is the shape a
    monitoring workbook actually has. Anything else yields nothing rather than
    a guess about which column meant what.
    """
    data = chunk.data or {}
    rows = data.get("rows") or []
    raw_rows = data.get("raw_rows") or rows
    cells = data.get("cells") or []
    out = []
    for index, row in enumerate(rows):
        if not isinstance(row, list) or len(row) < 2:
            continue
        label = str(row[0] or "").strip()
        shown = str(row[1] or "").strip()
        if not label or not shown:
            continue
        raw_row = raw_rows[index] if index < len(raw_rows) else row
        raw = str(raw_row[1] if len(raw_row) > 1 else shown or "").strip()
        cell_row = cells[index] if index < len(cells) else []
        cell = str(cell_row[1]) if len(cell_row) > 1 else ""
        out.append((label, shown, raw, cell))
    return out


def apply_uploaded(session, workspace_id: int, source_id: int, *,
                   binding_ids: list[int], actor: str) -> dict:
    """Take the uploaded readings a person has confirmed, and only those.

    This is the act that makes an uploaded number a governed current value,
    and it is a person's: the uploaded column resembled a tracked metric, and
    a resemblance is not an identity. `require_person` refuses anything else.

    Each confirmed reading replaces the binding's current value and records
    where it came from. The frozen snapshots are untouched — THEN is what the
    document relied on and is never rewritten, which is what makes the next
    Since Last Time comparison mean something.
    """
    who = gov.require_person(actor, "Updating a metric from an uploaded file")
    proposed = {row["binding_id"]: row
                for row in proposals_from_source(session, workspace_id,
                                                 source_id)["rows"]}
    wanted = [i for i in binding_ids if i in proposed]

    updated = []
    for binding_id in wanted:
        row = session.get(PlaybookMetricBinding, binding_id)
        if row is None or row.workspace_id != workspace_id:
            continue
        reading = proposed[binding_id]
        row.value_in_document = reading["uploaded_raw_value"] \
            or reading["uploaded_value"]
        row.raw_value = reading["uploaded_raw_value"]
        row.display_value = reading["uploaded_value"]
        row.source_locator = reading["source_locator"]
        row.source_id = source_id
        row.confirmed_by_user = True
        row.confirmed_by = who
        row.confirmed_at = datetime.now(UTC)
        # It is current because somebody just said so, from a file they
        # uploaded. Leaving it stale here would ask them again immediately.
        row.freshness = bind.CURRENT
        updated.append({"binding_id": row.id, "metric_id": row.metric_id,
                        "label": row.label, "value": row.display_value,
                        "source_locator": row.source_locator})
    session.flush()

    ignored = [i for i in proposed if i not in set(wanted)]
    return {
        "updated": updated,
        "ignored": ignored,
        "message": _applied_message(len(updated), len(ignored)),
    }


def _applied_message(updated: int, ignored: int) -> str:
    if not updated:
        return "Nothing was changed."
    parts = [f"{updated} metric{'s' if updated != 1 else ''} updated"]
    if ignored:
        parts.append(f"{ignored} left as {'it was' if ignored == 1 else 'they were'}")
    return "; ".join(parts) + "."
