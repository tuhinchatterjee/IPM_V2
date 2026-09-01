"""
The Data Inbox — files arrive, and something has to decide.

The shape of the problem
------------------------
Onboarding is a one-off; arrival is forever. A bank's facility extract lands
every month from the same system into the same folder, and nobody sits down to
onboard it. What the product owes them is not another upload wizard — it is an
answer to "is this file the same as the last one, and if it is not, does anybody
know".

So every arrival is recorded here whether it was published or held, with the
drift report and the decision attached. A file that was published automatically
has a row saying why, exactly like one that was stopped.

The policy
----------
Auto-publish is a real feature and a real risk, so the rule is narrow and the
reason is always recorded:

    publish automatically      matched to a dataset, the schema is unchanged,
                               and nothing blocking or material drifted
    hold for a person          anything blocking or material, a first load, or
                               a match nobody is confident about
    hold, unmatched            nothing in the catalogue looks like this file

There is deliberately no "publish anyway because it is late" path. A held file
is published by a person, and that person is recorded.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models.platform import DatasetDefinition, InboxItem
from backend.services import data_builder as db
from backend.services.drift import DriftReport, compare

logger = logging.getLogger(__name__)

# ---- statuses --------------------------------------------------------------

RECEIVED = "received"
HELD = "held"
PUBLISHED = "published"
REJECTED = "rejected"
UNMATCHED = "unmatched"

STATUSES = [RECEIVED, UNMATCHED, HELD, PUBLISHED, REJECTED]

STATUS_LABEL = {
    RECEIVED: "Received",
    UNMATCHED: "Nothing matched",
    HELD: "Held for review",
    PUBLISHED: "Published",
    REJECTED: "Rejected",
}

# ---- decisions -------------------------------------------------------------

AUTO_PUBLISH = "auto_publish"
HOLD = "hold"
REJECT = "reject"

#: How sure the match has to be before a file is published without anybody
#: looking. Below it the file is matched but held, because publishing into the
#: wrong dataset is worse than a day's delay.
MATCH_CONFIDENCE_TO_AUTO_PUBLISH = 0.8


@dataclass(frozen=True)
class Match:
    """Which governed dataset this file looks like, and how sure that is."""

    dataset: str
    confidence: float
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {"dataset": self.dataset, "confidence": round(self.confidence, 3),
                "reason": self.reason}


def match_dataset(session: Session, filename: str,
                  profile: dict[str, Any]) -> Match:
    """Which dataset a file belongs to, decided on its COLUMNS.

    The filename is a hint and nothing more: `extract_final_v3.csv` is what a
    monthly extract is actually called. What identifies a facility file is that
    it carries the columns a facility file carries, so the match is scored on
    column overlap against each dataset's accepted mappings, and the filename
    only breaks ties.
    """
    columns = {db.slugify(str(c.get("name"))) for c in (profile.get("columns") or [])}
    if not columns:
        return Match("", 0.0, "The file has no readable columns.")

    lowered = str(filename).lower()
    best = Match("", 0.0, "Nothing in the catalogue carries these columns.")

    for dataset in session.scalars(select(DatasetDefinition)).all():
        mapped = {
            db.slugify(m.governed_field or m.source_column)
            for m in db.get_mappings(session, dataset)
            if m.governed_field
        }
        known = mapped or {db.slugify(f.name) for f in dataset.fields}
        if not known:
            continue

        overlap = len(columns & known)
        if not overlap:
            continue
        # Scored against the KNOWN fields, not the file's: a file carrying every
        # field plus five extras still matches, and a file carrying five of forty
        # does not.
        score = overlap / len(known)
        if db.slugify(dataset.name) in db.slugify(lowered):
            score = min(1.0, score + 0.1)

        if score > best.confidence:
            best = Match(
                dataset.name, score,
                f"{overlap} of {len(known)} governed fields of "
                f"'{dataset.name}' are in this file.")

    return best


def apply_policy(match: Match, drift: DriftReport) -> tuple[str, str, str]:
    """(status, decision, reason). Nothing here writes anything.

    Kept as a pure function so the rule can be read, argued with and tested
    without a database — which is the difference between a policy and a
    behaviour somebody discovers.
    """
    if not match.dataset:
        return UNMATCHED, HOLD, (
            "Nothing in the catalogue carries these columns, so there is no "
            "dataset to publish it into.")

    if match.confidence < MATCH_CONFIDENCE_TO_AUTO_PUBLISH:
        return HELD, HOLD, (
            f"This looks like '{match.dataset}' but only {match.confidence * 100:.0f}% "
            "of its governed fields are present. Publishing into the wrong "
            "dataset is worse than a day's delay.")

    if drift.first_load:
        return HELD, HOLD, (
            "This is the first file for this dataset, so there is nothing to "
            "compare it against. A first load is reviewed by a person.")

    if drift.blocking:
        return HELD, HOLD, (
            f"{len(drift.blocking)} blocking change(s): "
            + "; ".join(f.detail for f in drift.blocking[:3]))

    if drift.material:
        return HELD, HOLD, (
            f"{len(drift.material)} material change(s) somebody should see: "
            + "; ".join(f.detail for f in drift.material[:3]))

    noted = len(drift.findings)
    return PUBLISHED, AUTO_PUBLISH, (
        "The schema is unchanged and nothing material drifted"
        + (f", though {noted} change(s) were noted" if noted else "")
        + ".")


# ------------------------------------------------------------------ arrivals


def receive(session: Session, *, content: bytes, filename: str,
            sheet_name: str | None = None, user_id: int | None = None,
            publish: bool = True) -> InboxItem:
    """Take one arriving file as far as the policy allows.

    Profiles it, matches it, compares it against the last accepted profile, and
    either publishes it or holds it — recording the reason either way. Set
    `publish=False` to run the whole assessment without acting on it, which is
    what the "what would happen" view uses.
    """
    if not content:
        raise db.DataBuilderError("The file is empty.")

    file_format = db.detect_format(filename)
    frame = db.read_source(content, file_format, sheet_name)
    profile = db.profile_dataframe(frame)

    item = InboxItem(
        filename=filename, file_format=file_format,
        file_sha256=hashlib.sha256(content).hexdigest(),
        size_bytes=len(content), profile=profile, status=RECEIVED,
    )
    session.add(item)

    match = match_dataset(session, filename, profile)
    item.dataset = match.dataset
    item.match_confidence = match.confidence
    item.match_reason = match.reason

    report = _drift_against_last(session, match.dataset, profile)
    item.drift = report.to_dict()

    status, decision, reason = apply_policy(match, report)
    item.decision = decision
    item.decision_reason = reason

    if decision == AUTO_PUBLISH and publish:
        try:
            upload = db.upload_file(
                session, dataset_name=match.dataset, content=content,
                filename=filename, sheet_name=sheet_name, uploaded_by=user_id)
            item.upload_id = upload.id
            db.publish_dataset(session, match.dataset, published_by=user_id)
            item.status = PUBLISHED
            item.resolved_at = datetime.now(UTC)
        except Exception as e:
            # A policy that says publish and a publish that fails is a held
            # file, not a silent success. The reason is replaced with what
            # actually stopped it.
            logger.warning("Auto-publish of %s failed: %s", filename, e)
            item.status = HELD
            item.decision = HOLD
            item.decision_reason = (
                f"The policy allowed this to publish automatically, but "
                f"publishing failed: {e}")
    else:
        item.status = status if decision != AUTO_PUBLISH else HELD

    session.flush()
    logger.info("Inbox: %s -> %s (%s)", filename, item.status, item.decision)
    return item


def _drift_against_last(session: Session, dataset_name: str,
                        profile: dict[str, Any]) -> DriftReport:
    """Compare against the profile of the last file this dataset published."""
    if not dataset_name:
        return DriftReport(dataset="", first_load=True,
                           current_row_count=int(profile.get("row_count") or 0))
    try:
        dataset = db.get_dataset(session, dataset_name)
    except Exception:
        return DriftReport(dataset=dataset_name, first_load=True,
                           current_row_count=int(profile.get("row_count") or 0))

    previous = db.latest_upload(session, dataset)
    return compare(previous.profile if previous else None, profile,
                   dataset=dataset_name)


# ----------------------------------------------------------------- resolving


def resolve(session: Session, item_id: int, *, action: str, user_id: int | None = None,
            note: str = "", dataset: str = "") -> InboxItem:
    """A person decides what happens to a held file.

    `publish` and `reject` are the two outcomes. Publishing a held file is a
    deliberate act by a named person and is recorded as one — the drift the
    policy stopped it for stays on the row afterwards, so "who published this
    despite the warning" has an answer.
    """
    item = session.get(InboxItem, item_id)
    if item is None:
        raise db.DataBuilderError(f"No inbox item {item_id}.")
    if item.status == PUBLISHED:
        raise db.DataBuilderError("That file has already been published.")

    if action == "reject":
        item.status = REJECTED
        item.resolution_note = note or "Rejected without publishing."
    elif action == "publish":
        target = dataset or item.dataset
        if not target:
            raise db.DataBuilderError(
                "Say which dataset this file belongs to. Nothing in the "
                "catalogue matched it.")
        if not note.strip():
            raise db.DataBuilderError(
                "Publishing a held file needs a reason. The drift that stopped "
                "it is recorded, and so is the decision to publish anyway.")
        db.publish_dataset(session, target, published_by=user_id)
        item.dataset = target
        item.status = PUBLISHED
        item.resolution_note = note
    else:
        raise db.DataBuilderError(f"'{action}' is not something to do with a file.")

    item.resolved_by = user_id
    item.resolved_at = datetime.now(UTC)
    session.flush()
    return item


def listing(session: Session, *, status: str = "", limit: int = 100
            ) -> list[dict[str, Any]]:
    query = select(InboxItem).order_by(InboxItem.received_at.desc(), InboxItem.id.desc())
    if status:
        query = query.where(InboxItem.status == status)
    return [to_dict(i) for i in session.scalars(query.limit(limit)).all()]


def to_dict(item: InboxItem, *, full: bool = False) -> dict[str, Any]:
    body = {
        "id": item.id,
        "filename": item.filename,
        "file_format": item.file_format,
        "size_bytes": item.size_bytes,
        "dataset": item.dataset,
        "match_confidence": round(float(item.match_confidence or 0.0), 3),
        "match_reason": item.match_reason,
        "status": item.status,
        "status_label": STATUS_LABEL.get(item.status, item.status),
        "decision": item.decision,
        "decision_reason": item.decision_reason,
        "drift": item.drift or {},
        "row_count": int((item.profile or {}).get("row_count") or 0),
        "column_count": int((item.profile or {}).get("column_count") or 0),
        "received_at": item.received_at.isoformat() if item.received_at else "",
        "resolved_at": item.resolved_at.isoformat() if item.resolved_at else "",
        "resolved_by": item.resolved_by,
        "resolution_note": item.resolution_note,
    }
    if full:
        body["profile"] = item.profile or {}
    return body


def counts(session: Session) -> dict[str, int]:
    from sqlalchemy import func

    rows = session.execute(
        select(InboxItem.status, func.count()).group_by(InboxItem.status)).all()
    out = {status: 0 for status in STATUSES}
    for status, count in rows:
        out[str(status)] = int(count)
    out["total"] = sum(int(c) for _, c in rows)
    out["needs_attention"] = out.get(HELD, 0) + out.get(UNMATCHED, 0)
    return out


__all__ = [
    "AUTO_PUBLISH",
    "HELD",
    "HOLD",
    "MATCH_CONFIDENCE_TO_AUTO_PUBLISH",
    "PUBLISHED",
    "REJECT",
    "REJECTED",
    "STATUSES",
    "STATUS_LABEL",
    "UNMATCHED",
    "Match",
    "apply_policy",
    "counts",
    "listing",
    "match_dataset",
    "receive",
    "resolve",
    "to_dict",
]
