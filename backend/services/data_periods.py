"""A period arrives, is checked, is read by somebody, and only then is published.

The defect this closes
----------------------
Publishing a dataset rewrote every period of it. That is right when a book is
loaded in full and catastrophic when a steward sends the next quarter: the
analytics directory was deleted and rebuilt from the latest upload, so adding
Q3 2026 to a fifteen-quarter book would have left a one-quarter book behind it.
There was no way to send one period, and therefore no way to run a bank.

The shape
---------
A period release is scoped to a period and versioned within it. Publishing one
touches exactly one partition and leaves the other fourteen alone. Replacing
Q1 2025 creates version 2 of Q1 2025 and marks version 1 SUPERSEDED — both rows
stay, because an investigation run last quarter names the version it read, and
a lineage that deletes its own history cannot answer "what did we see at the
time".

The lifecycle is not decoration
-------------------------------
    UPLOADED → VALIDATING → FAILED
    UPLOADED → VALIDATING → VALIDATED → REVIEW → LOCKED → PUBLISHED

Nothing is published as a side effect of arriving. A file that fails its
contract stops at FAILED rather than being published with warnings, because a
period a reader can see is a period they will act on. A file that passes is
still not published: somebody reads what changed first, and locks it, and
publishes it, and each of those is recorded with who did it.

What "its contract" means
-------------------------
The checks are the dataset's own, not a universal list. A dataset with a
declared business key is checked for duplicates on that key; one without is
not, because inventing a key and then failing a file against it is worse than
not checking. Ranges come from the field's declared bounds. Enumerations come
from the field's declared values. Row-count anomaly is measured against the
period this one is replacing or following, because "thirty per cent fewer rows
than last quarter" is a real finding and "thirty thousand rows" is not.
"""

from __future__ import annotations

import hashlib
import logging
import re
import shutil
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.config import settings
from backend.models.platform import (
    PERIOD_FAILED,
    PERIOD_LOCKED,
    PERIOD_MODE_NEW,
    PERIOD_MODE_REPLACE,
    PERIOD_PUBLISHED,
    PERIOD_REVIEW,
    PERIOD_SUPERSEDED,
    PERIOD_UPLOADED,
    PERIOD_VALIDATED,
    DataPeriodRelease,
    DatasetDefinition,
)
from backend.services.data_builder import (
    DataBuilderError,
    detect_format,
    get_dataset,
    read_source,
)

logger = logging.getLogger(__name__)

PERIODS_VERSION = "1.0.0"

#: A row count that moves by more than this against the period it follows is
#: worth a person's attention. Not an error: books do grow and shrink, and a
#: steward who has just onboarded a portfolio should not be blocked by a rule
#: that cannot know that. It is a WARNING, which is what stops it being
#: ignored and what stops it being a gate.
ROW_COUNT_DRIFT = 0.30

#: Severities, in the order they matter.
ERROR = "error"
WARNING = "warning"
INFO = "info"


@dataclass
class Finding:
    """One check, and what it found."""

    rule: str
    severity: str
    detail: str
    count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {"rule": self.rule, "severity": self.severity,
                "detail": self.detail, "count": self.count}


@dataclass
class Report:
    """Every check that ran against one period, and whether it may publish."""

    dataset: str = ""
    period: str = ""
    rows: int = 0
    fields: int = 0
    findings: list[Finding] = field(default_factory=list)
    checked: list[str] = field(default_factory=list)

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == ERROR]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == WARNING]

    @property
    def passed(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset": self.dataset, "period": self.period,
            "rows": self.rows, "fields": self.fields,
            "passed": self.passed,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "checks_run": list(self.checked),
            "findings": [f.to_dict() for f in self.findings],
        }


# ------------------------------------------------------------- the contract


def _declared_fields(dataset: DatasetDefinition) -> list[Any]:
    return list(getattr(dataset, "field_definitions", None) or [])


def _period_field(dataset: DatasetDefinition) -> str:
    return str(getattr(dataset, "period_field", "") or "")


def _business_key(dataset: DatasetDefinition) -> list[str]:
    """The columns that identify a row, where the dataset declares them."""
    declared = getattr(dataset, "primary_keys", None) or []
    return [str(k) for k in declared if k]


def check(dataset: DatasetDefinition, frame: pd.DataFrame, period: str, *,
          previous: pd.DataFrame | None = None) -> Report:
    """Run the checks this dataset's contract calls for, and no others.

    Every check appends its name to `checked` whether or not it found
    anything: a report that lists only failures cannot tell a reviewer the
    difference between "the duplicate check passed" and "nobody checked for
    duplicates".
    """
    report = Report(dataset=dataset.name, period=period,
                    rows=int(len(frame)), fields=int(len(frame.columns)))
    declared = _declared_fields(dataset)

    # 1 — there is something to publish.
    report.checked.append("not empty")
    if frame.empty:
        report.findings.append(Finding(
            "not empty", ERROR, "The file has no rows.", 0))
        return report

    # 2 — every governed field the dataset declares is present.
    if declared:
        report.checked.append("declared fields present")
        missing = [f.name for f in declared if f.name not in frame.columns]
        if missing:
            report.findings.append(Finding(
                "declared fields present", ERROR,
                "The file is missing governed "
                f"{'field' if len(missing) == 1 else 'fields'}: "
                + ", ".join(sorted(missing)[:8]), len(missing)))

        report.checked.append("no undeclared fields")
        known = {f.name for f in declared}
        extra = [c for c in frame.columns if c not in known]
        if extra:
            report.findings.append(Finding(
                "no undeclared fields", WARNING,
                f"{len(extra)} column(s) are not in the data dictionary and "
                "will not be published: " + ", ".join(sorted(extra)[:8]),
                len(extra)))

    # 3 — the period column says what the upload says it is.
    period_field = _period_field(dataset)
    if period_field and period_field in frame.columns:
        report.checked.append("one period per file")
        found = {str(v) for v in frame[period_field].dropna().unique()}
        if len(found) > 1:
            report.findings.append(Finding(
                "one period per file", ERROR,
                "The file carries more than one reporting period: "
                + ", ".join(sorted(found)[:6]), len(found)))
        elif found and period and found != {period}:
            report.findings.append(Finding(
                "one period per file", ERROR,
                f"The file says {sorted(found)[0]!r} and it was uploaded as "
                f"{period!r}.", 1))
    elif period_field:
        report.checked.append("period column present")
        report.findings.append(Finding(
            "period column present", ERROR,
            f"The dataset is published by {period_field!r} and the file does "
            "not carry that column.", 1))

    # 4 — the business key identifies a row.
    key = [k for k in _business_key(dataset) if k in frame.columns]
    if key:
        report.checked.append("business key unique")
        duplicated = int(frame.duplicated(subset=key).sum())
        if duplicated:
            report.findings.append(Finding(
                "business key unique", ERROR,
                f"{duplicated:,} rows repeat a business key "
                f"({', '.join(key)}).", duplicated))

    # 5 — types, nulls, ranges and enumerations, per declared field.
    for found in declared:
        name = found.name
        if name not in frame.columns:
            continue
        series = frame[name]
        declared_type = str(getattr(found, "data_type", "") or "").lower()

        if declared_type in {"number", "float", "double", "decimal",
                             "integer", "int", "bigint"}:
            report.checked.append(f"{name} is numeric")
            coerced = pd.to_numeric(series, errors="coerce")
            broken = int(coerced.isna().sum() - series.isna().sum())
            if broken > 0:
                report.findings.append(Finding(
                    f"{name} is numeric", ERROR,
                    f"{broken:,} values in {name!r} are not numbers.", broken))

        if not bool(getattr(found, "nullable", True)):
            report.checked.append(f"{name} is populated")
            blank = int(series.isna().sum())
            if blank:
                report.findings.append(Finding(
                    f"{name} is populated", ERROR,
                    f"{blank:,} rows have no {name!r}, which the dictionary "
                    "declares as required.", blank))

        allowed = [str(v) for v in (getattr(found, "allowed_values", None)
                                    or []) if str(v)]
        if allowed:
            report.checked.append(f"{name} is a governed value")
            seen = series.dropna().astype(str)
            unknown = sorted(set(seen) - set(allowed))
            if unknown:
                report.findings.append(Finding(
                    f"{name} is a governed value", ERROR,
                    f"{name!r} holds values the dictionary does not allow: "
                    + ", ".join(unknown[:6]), len(unknown)))

    # 6 — how this period compares with the one it follows.
    if previous is not None and not previous.empty:
        report.checked.append("row count against the previous period")
        was, now = len(previous), len(frame)
        drift = abs(now - was) / max(was, 1)
        if drift > ROW_COUNT_DRIFT:
            report.findings.append(Finding(
                "row count against the previous period", WARNING,
                f"{now:,} rows against {was:,} in the period before it — "
                f"{drift * 100:.0f}% {'more' if now > was else 'fewer'}. "
                "Worth a look before this is published.", abs(now - was)))

        report.checked.append("schema against the previous period")
        gone = sorted(set(previous.columns) - set(frame.columns))
        if gone:
            report.findings.append(Finding(
                "schema against the previous period", WARNING,
                f"{len(gone)} column(s) present last period and absent now: "
                + ", ".join(gone[:8]), len(gone)))

    return report


# ------------------------------------------------------------- the lifecycle


#: What a reporting period label is allowed to be.
#:
#: A period reaches the filesystem twice — the staging directory and the
#: published partition — and it arrives from an upload form. Before this,
#: `period=../../../../tmp/x` wrote a partition outside the data lake
#: entirely: the staging path stripped "/" but the partition path did not,
#: and neither stripped a dot segment. Sanitising the two paths separately is
#: how that kind of hole reopens, so the label is checked once, at the door,
#: and everything downstream can treat it as a name.
#:
#: Positive rather than a blocklist: letters, digits, spaces and a few
#: separators that real period labels use — "Q3 2026", "2026-09", "FY2026",
#: "Sep 2026". Nothing that is a path, a dot segment, or a control character.
PERIOD_LABEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.\-]{0,63}$")


def check_period_label(period: str) -> str:
    """The label, cleaned, or a refusal saying why it is not one."""
    label = " ".join(str(period or "").split())
    if not PERIOD_LABEL.match(label) or ".." in label:
        raise DataBuilderError(
            f"{period!r} is not a reporting period label. A period is written "
            "the way the dataset publishes it — Q3 2026, 2026-09, FY2026 — "
            "using letters, digits, spaces, dots, hyphens and underscores.")
    return label


def _staging_dir(dataset_name: str, period: str) -> Path:
    safe = check_period_label(period).replace(" ", "_")
    return Path(settings.raw_dir) / "staged" / dataset_name / safe


def _released(session: Session, dataset: DatasetDefinition,
              period: str) -> list[DataPeriodRelease]:
    return list(session.execute(
        select(DataPeriodRelease)
        .where(DataPeriodRelease.dataset_id == dataset.id,
               DataPeriodRelease.period == period)
        .order_by(DataPeriodRelease.version.desc())
    ).scalars())


def current_release(session: Session, dataset_name: str,
                    period: str) -> DataPeriodRelease | None:
    """The published release of one period, where there is one."""
    dataset = get_dataset(session, dataset_name)
    for release in _released(session, dataset, period):
        if release.state == PERIOD_PUBLISHED:
            return release
    return None


def history(session: Session, dataset_name: str,
            period: str = "") -> list[DataPeriodRelease]:
    """Every release of a dataset, or of one of its periods, newest first."""
    dataset = get_dataset(session, dataset_name)
    stmt = select(DataPeriodRelease).where(
        DataPeriodRelease.dataset_id == dataset.id)
    if period:
        stmt = stmt.where(DataPeriodRelease.period == period)
    return list(session.execute(
        stmt.order_by(DataPeriodRelease.uploaded_at.desc(),
                      DataPeriodRelease.version.desc())).scalars())


def _published_periods(dataset: DatasetDefinition) -> list[str]:
    """The periods the analytics layer actually holds for this dataset."""
    root = Path(settings.analytics_dir) / dataset.name
    field_name = _period_field(dataset)
    if not root.exists() or not field_name:
        return []
    prefix = f"{field_name}="
    return sorted(p.name[len(prefix):] for p in root.iterdir()
                  if p.is_dir() and p.name.startswith(prefix))


def _read_published(dataset: DatasetDefinition,
                    period: str) -> pd.DataFrame | None:
    field_name = _period_field(dataset)
    if not field_name:
        return None
    part = (Path(settings.analytics_dir) / dataset.name
            / f"{field_name}={period}" / "data.parquet")
    if not part.exists():
        return None
    try:
        return pd.read_parquet(part)
    except Exception as e:  # noqa: BLE001 - a comparison is not worth an upload
        logger.warning("Could not read the published %s at %s: %s",
                       dataset.name, period, e)
        return None


def _previous_period(dataset: DatasetDefinition, period: str) -> str:
    """The published period immediately before this one, chronologically."""
    from backend.metadata import frequency as fq

    published = [p for p in _published_periods(dataset) if p != period]
    earlier = [p for p in published
               if fq.sort_key(p) < fq.sort_key(period)]
    return max(earlier, key=fq.sort_key) if earlier else ""


def stage(session: Session, dataset_name: str, *, content: bytes,
          filename: str, period: str, mode: str = PERIOD_MODE_NEW,
          uploaded_by: int | None = None,
          sheet_name: str | None = None) -> DataPeriodRelease:
    """A file arrives for one period. It is read, staged and validated.

    It is NOT published. The release comes back VALIDATED or FAILED, and a
    person moves it from there.
    """
    dataset = get_dataset(session, dataset_name)
    if not str(period or "").strip():
        raise DataBuilderError(
            "A period upload has to say which period it is. "
            f"{dataset.business_name or dataset.name} publishes by "
            f"{_period_field(dataset) or 'no period column'}.")
    period = check_period_label(period)

    if mode not in (PERIOD_MODE_NEW, PERIOD_MODE_REPLACE):
        raise DataBuilderError(
            f"{mode!r} is not an upload mode. It is either "
            f"{PERIOD_MODE_NEW} or {PERIOD_MODE_REPLACE}.")

    already = period in _published_periods(dataset)
    if mode == PERIOD_MODE_NEW and already:
        raise DataBuilderError(
            f"{dataset.business_name or dataset.name} already publishes "
            f"{period}. Upload it as a replacement if that is what you mean — "
            "a period sent twice as new would double the quarter.")
    if mode == PERIOD_MODE_REPLACE and not already:
        raise DataBuilderError(
            f"{dataset.business_name or dataset.name} does not publish "
            f"{period} yet, so there is nothing to replace. Upload it as a "
            "new period.")

    file_format = detect_format(filename)
    try:
        frame = read_source(content, file_format, sheet_name=sheet_name)
    except Exception as e:  # noqa: BLE001 - refuse with the reason
        raise DataBuilderError(f"{filename} could not be read: {e}") from e

    version = 1 + max((r.version for r in _released(session, dataset, period)),
                      default=0)
    staged_dir = _staging_dir(dataset.name, period)
    staged_dir.mkdir(parents=True, exist_ok=True)
    staged_path = staged_dir / f"v{version}.parquet"
    frame.to_parquet(staged_path, index=False)

    release = DataPeriodRelease(
        dataset_id=dataset.id, period=period, version=version, mode=mode,
        state=PERIOD_UPLOADED, row_count=int(len(frame)),
        field_count=int(len(frame.columns)),
        staged_path=str(staged_path), source_filename=filename,
        source_sha256=hashlib.sha256(content).hexdigest(),
        uploaded_by=uploaded_by,
        note=f"{filename} received for {period}.")
    session.add(release)
    session.flush()

    previous = _read_published(dataset, _previous_period(dataset, period))
    if mode == PERIOD_MODE_REPLACE:
        # A correction is measured against the version it corrects, not against
        # the quarter before: a restatement that halves one sector is a drift
        # of 50% from last quarter and a drift of 50% from what it replaces,
        # and only the second of those is the one a reviewer needs to see.
        #
        # `or` cannot be used to choose between two frames — pandas refuses to
        # say whether a DataFrame is true — so the empty case is explicit.
        standing = _read_published(dataset, period)
        if standing is not None and not standing.empty:
            previous = standing
    report = check(dataset, frame, period, previous=previous)
    release.validation = report.to_dict()
    release.state = PERIOD_VALIDATED if report.passed else PERIOD_FAILED
    release.note = (
        f"{len(report.checked)} checks ran; "
        f"{len(report.errors)} blocking, {len(report.warnings)} to look at.")
    session.flush()
    logger.info("Staged %s %s v%d as %s", dataset.name, period, version,
                release.state)
    return release


def send_to_review(session: Session, release_id: int, *,
                   note: str = "") -> DataPeriodRelease:
    """A validated period goes to somebody to read before it is locked."""
    release = _require(session, release_id)
    if release.state != PERIOD_VALIDATED:
        raise DataBuilderError(
            f"Only a validated period can go to review. This one is "
            f"{release.state}.")
    release.state = PERIOD_REVIEW
    release.note = note or "Waiting to be read."
    session.flush()
    return release


def lock(session: Session, release_id: int, *, reviewed_by: int | None = None,
         note: str = "") -> DataPeriodRelease:
    """Somebody has read it. It may now be published and not changed."""
    release = _require(session, release_id)
    if release.state != PERIOD_REVIEW:
        raise DataBuilderError(
            f"Only a period in review can be locked. This one is "
            f"{release.state}.")
    release.state = PERIOD_LOCKED
    release.reviewed_by = reviewed_by
    release.reviewed_at = datetime.now(UTC)
    release.note = note or "Read and locked."
    session.flush()
    return release


def publish(session: Session, release_id: int, *,
            published_by: int | None = None) -> DataPeriodRelease:
    """Write ONE period's partition, supersede the release it replaces.

    Every other period of the dataset is untouched. That is the whole point:
    the previous publication path deleted the analytics directory and rebuilt
    it from the latest upload, so sending one quarter would have left a
    one-quarter book behind it.
    """
    release = _require(session, release_id)
    if release.state != PERIOD_LOCKED:
        raise DataBuilderError(
            "A period is published from LOCKED, so that somebody has read it "
            f"first. This one is {release.state}.")

    dataset = session.get(DatasetDefinition, release.dataset_id)
    if dataset is None:
        raise DataBuilderError("The dataset behind this release is gone.")

    frame = pd.read_parquet(release.staged_path)
    field_name = _period_field(dataset)
    if not field_name:
        raise DataBuilderError(
            f"{dataset.name} publishes no period column, so it cannot take a "
            "period release.")

    # Checked again here rather than trusted from the row. A release is
    # staged and published by two separate calls, and a label that was legal
    # when it was staged is the only thing standing between an upload form and
    # a write outside the data lake.
    part = (Path(settings.analytics_dir) / dataset.name
            / f"{field_name}={check_period_label(release.period)}")
    lake = Path(settings.analytics_dir).resolve()
    if not str(part.resolve()).startswith(str(lake)):  # pragma: no cover
        raise DataBuilderError(
            f"{release.period!r} does not name a partition inside the "
            "governed data lake.")
    part.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(part / "data.parquet", index=False)

    for earlier in _released(session, dataset, release.period):
        if earlier.id != release.id and earlier.state == PERIOD_PUBLISHED:
            earlier.state = PERIOD_SUPERSEDED
            earlier.superseded_by_id = release.id
            earlier.note = (f"Superseded by v{release.version} on "
                            f"{datetime.now(UTC):%Y-%m-%d}.")

    release.state = PERIOD_PUBLISHED
    release.published_by = published_by
    release.published_at = datetime.now(UTC)
    release.published_path = str(part)
    release.note = (f"{release.row_count:,} rows published for "
                    f"{release.period}.")
    session.flush()
    logger.info("Published %s %s v%d (%d rows)", dataset.name, release.period,
                release.version, release.row_count)
    return release


def discard(session: Session, release_id: int, *,
            note: str = "") -> DataPeriodRelease:
    """Throw a staged period away. Published ones are never discarded."""
    release = _require(session, release_id)
    if release.state == PERIOD_PUBLISHED:
        raise DataBuilderError(
            "A published period is not discarded. Replace it, which keeps "
            "both and marks the old one superseded.")
    staged = Path(release.staged_path) if release.staged_path else None
    if staged is not None and staged.exists():
        shutil.rmtree(staged.parent, ignore_errors=True)
    release.state = PERIOD_FAILED
    release.note = note or "Discarded before publication."
    session.flush()
    return release


def _require(session: Session, release_id: int) -> DataPeriodRelease:
    release = session.get(DataPeriodRelease, int(release_id))
    if release is None:
        raise DataBuilderError(f"No period release {release_id}.")
    return release


def describe(release: DataPeriodRelease) -> dict[str, Any]:
    """One release, as the API and the screen read it."""
    return {
        "id": release.id, "period": release.period,
        "version": release.version, "mode": release.mode,
        "state": release.state, "rows": release.row_count,
        "fields": release.field_count,
        "source_filename": release.source_filename,
        "source_sha256": release.source_sha256,
        "validation": dict(release.validation or {}),
        "note": release.note,
        "uploaded_at": (release.uploaded_at.isoformat()
                        if release.uploaded_at else None),
        "reviewed_at": (release.reviewed_at.isoformat()
                        if release.reviewed_at else None),
        "published_at": (release.published_at.isoformat()
                         if release.published_at else None),
        "superseded_by": release.superseded_by_id,
    }


__all__ = ["PERIODS_VERSION", "ROW_COUNT_DRIFT", "PERIOD_LABEL",
           "check_period_label", "ERROR", "WARNING", "INFO",
           "Finding", "Report", "check", "stage", "send_to_review", "lock",
           "publish", "discard", "history", "current_release", "describe"]
