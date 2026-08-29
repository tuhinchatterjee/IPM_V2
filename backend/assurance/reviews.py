"""
Recent Investigation Reviews. §186, §187, §199, §203.

The tab, and what it is for
----------------------------
    §186: "This tab shows recent authorized Investigations and how
           CreditProbe performed."

The word doing the work is AUTHORIZED. This module produces rows and views;
every one of them is filtered through `access.may_read` before it reaches a
caller, and the filtering removes rows rather than replacing them with a
refusal — a row that says "you may not see this" has already disclosed that
the Investigation exists.

Views are queries, not tabs
-----------------------------
§186's eight views are eight predicates over the same rows. Writing them as
predicates rather than as eight endpoints means LOW ASSURANCE and FAILED
cannot drift into two different definitions of what a failure is, which is
the way this kind of screen usually goes wrong.

Why a table rather than cards
-------------------------------
    §187: "Use a table/list, not a giant card wall."

Because the point of the screen is comparison. A reviewer arrives asking
which of the last two hundred Investigations needs attention, and that is a
scanning task: forty rows of the same nine columns answers it, and forty
cards of nine differently-placed facts does not.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from backend.assurance import access as ac
from backend.assurance import dimensions as dm
from backend.assurance import record as rc
from backend.assurance import store as st

REVIEWS_VERSION = "1.0.0"

# ------------------------------------------------------------------ views

RECENT = "RECENT"
MINE = "MY_INVESTIGATIONS"
PROJECT = "PROJECT_INVESTIGATIONS"
LOW_ASSURANCE = "LOW_ASSURANCE"
NEEDS_REVIEW = "NEEDS_REVIEW"
FAILED = "FAILED"
WITH_FEEDBACK = "WITH_USER_FEEDBACK"
FIXED_OR_RERUN = "FIXED_RERUN"

VIEWS: tuple[str, ...] = (RECENT, MINE, PROJECT, LOW_ASSURANCE, NEEDS_REVIEW,
                          FAILED, WITH_FEEDBACK, FIXED_OR_RERUN)

VIEW_LABELS: dict[str, str] = {
    RECENT: "Recent",
    MINE: "My Investigations",
    PROJECT: "Project Investigations",
    LOW_ASSURANCE: "Low assurance",
    NEEDS_REVIEW: "Needs review",
    FAILED: "Failed",
    WITH_FEEDBACK: "With user feedback",
    FIXED_OR_RERUN: "Fixed / rerun",
}

VIEW_MEANS: dict[str, str] = {
    RECENT: "Everything the viewer may see, newest first.",
    MINE: "Investigations this person ran themselves.",
    PROJECT: "Investigations belonging to a Project the viewer is in.",
    LOW_ASSURANCE: ("Records that were scored and scored poorly, plus records "
                    "the gates refused to score at all. Both are 'we cannot "
                    "vouch for this', and separating them would let the "
                    "unscored ones hide."),
    NEEDS_REVIEW: "A mandatory check did not run, so a person has to look.",
    FAILED: "A critical check failed. The answer should not be relied on.",
    WITH_FEEDBACK: ("Somebody pressed Good or Bad. Raw feedback changes no "
                    "score; it changes where a reviewer looks."),
    FIXED_OR_RERUN: ("Turns that were re-run after a change, and the originals "
                     "they replaced. Both are kept."),
}

#: §186's threshold for LOW ASSURANCE. Records the gates refused to score are
#: included regardless: "no number" is not better than a low number.
LOW_ASSURANCE_BELOW = 70.0


# ---------------------------------------------------------------- filters

#: §186's filter list. Each is (field on the row, human label). Declared so
#: the API, the UI and the tests agree on the set rather than each carrying
#: their own copy.
FILTERS: tuple[tuple[str, str], ...] = (
    ("since", "Date from"),
    ("until", "Date to"),
    ("user_id", "User"),
    ("team", "Team"),
    ("project_id", "Project"),
    ("portfolio_scope", "Portfolio scope"),
    ("language", "Language"),
    ("officer_level", "Officer level"),
    ("model_route", "Model route"),
    ("teaching_release_id", "Teaching Release"),
    ("overall_status", "Status"),
    ("dimension", "Dimension"),
    ("feedback", "Feedback"),
    ("case_family", "Case family"),
)

FILTER_FIELDS: tuple[str, ...] = tuple(name for name, _ in FILTERS)


@dataclass(frozen=True)
class Filters:
    """§186's filters, as a value. Every field optional; absent means "do
    not filter on this", never "match empty"."""

    since: str = ""
    until: str = ""
    user_id: int | None = None
    team: str = ""
    project_id: str = ""
    portfolio_scope: str = ""
    language: str = ""
    officer_level: int | None = None
    model_route: str = ""
    teaching_release_id: str = ""
    overall_status: str = ""
    #: A dimension name. Selects records where THAT dimension failed or
    #: warned — "show me everything where the computation was the problem".
    dimension: str = ""
    #: "GOOD", "BAD", "ANY" or "".
    feedback: str = ""
    case_family: str = ""

    @classmethod
    def from_query(cls, raw: dict[str, Any]) -> Filters:
        """Build from query parameters, ignoring anything unrecognised.

        Unrecognised rather than rejected: a stale bookmark with a filter
        that no longer exists should show a list, not an error.
        """
        clean: dict[str, Any] = {}
        for name in FILTER_FIELDS:
            value = raw.get(name)
            if value in (None, ""):
                continue
            if name in ("user_id", "officer_level"):
                try:
                    clean[name] = int(value)
                except (TypeError, ValueError):
                    continue
            else:
                clean[name] = str(value)
        return cls(**clean)

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in FILTER_FIELDS}


def _dimension_troubled(row: st.StoredRecord, dimension: str) -> bool:
    stored = row.dimension_results.get(dimension)
    if not isinstance(stored, dict):
        return False
    return bool(stored.get("failures") or stored.get("warnings"))


def matches(row: st.StoredRecord, filters: Filters) -> bool:
    """Deterministic, and every unset filter passes everything."""
    if filters.since and row.created_at and row.created_at < filters.since:
        return False
    if filters.until and row.created_at and row.created_at > filters.until:
        return False
    if filters.user_id is not None and row.user_id != filters.user_id:
        return False
    if filters.project_id and row.project_id != filters.project_id:
        return False
    if (filters.portfolio_scope
            and row.portfolio_scope != filters.portfolio_scope):
        return False
    if filters.language and row.language != filters.language:
        return False
    if (filters.officer_level is not None
            and row.officer_level != filters.officer_level):
        return False
    if filters.model_route and row.model_route != filters.model_route:
        return False
    if (filters.teaching_release_id
            and row.teaching_release_id != filters.teaching_release_id):
        return False
    if filters.overall_status and row.overall_status != filters.overall_status:
        return False
    if filters.case_family and row.case_family != filters.case_family:
        return False
    if filters.dimension and not _dimension_troubled(row, filters.dimension):
        return False
    if filters.feedback:
        wanted = filters.feedback.upper()
        if wanted == "GOOD" and not row.good_feedback_count:
            return False
        if wanted == "BAD" and not row.bad_feedback_count:
            return False
        if wanted == "ANY" and not (row.good_feedback_count
                                    or row.bad_feedback_count):
            return False
    return True


# ------------------------------------------------------------------ views


def _low_assurance(row: st.StoredRecord) -> bool:
    if row.overall_status in (rc.FAILED, rc.NEEDS_REVIEW, rc.UNVERIFIED):
        return True
    score = row.operational_assurance
    return score is not None and score < LOW_ASSURANCE_BELOW


VIEW_PREDICATES: dict[str, Callable[[st.StoredRecord, ac.Viewer], bool]] = {
    RECENT: lambda row, viewer: True,
    MINE: lambda row, viewer: (viewer.user_id is not None
                               and row.user_id == viewer.user_id),
    PROJECT: lambda row, viewer: bool(row.project_id),
    LOW_ASSURANCE: lambda row, viewer: _low_assurance(row),
    NEEDS_REVIEW: lambda row, viewer: row.overall_status == rc.NEEDS_REVIEW,
    FAILED: lambda row, viewer: row.overall_status == rc.FAILED,
    WITH_FEEDBACK: lambda row, viewer: bool(row.good_feedback_count
                                            or row.bad_feedback_count),
    FIXED_OR_RERUN: lambda row, viewer: bool(row.rerun_of or row.superseded_by),
}


def _subject(row: st.StoredRecord) -> ac.Subject:
    return ac.Subject(assurance_record_id=row.assurance_record_id,
                      investigation_id=row.investigation_id,
                      project_id=row.project_id,
                      owner_user_id=row.user_id,
                      tenant_id=row.tenant_id)


# ------------------------------------------------------------------- rows


def compact_dimensions(row: st.StoredRecord) -> list[dict[str, Any]]:
    """§187's "six compact dimension indicators".

    One letter-sized cell per dimension, in a fixed order so a reader's eye
    learns the positions. A dimension nothing measured shows as unmeasured
    rather than as a pass, which is the whole of §183 compressed into a
    single character of screen.
    """
    cells: list[dict[str, Any]] = []
    for name in dm.DIMENSIONS:
        stored = row.dimension_results.get(name)
        if not isinstance(stored, dict) or not stored.get("measured", False):
            cells.append({"dimension": name, "short": dm.SHORT[name],
                          "state": "UNMEASURED", "score": None})
            continue
        if stored.get("failures"):
            state = "FAILED"
        elif stored.get("warnings"):
            state = "WARNING"
        else:
            state = "PASSED"
        cells.append({"dimension": name, "short": dm.SHORT[name],
                      "state": state, "score": stored.get("score"),
                      "coverage_pct": stored.get("coverage_pct")})
    return cells


def row_for(row: st.StoredRecord) -> dict[str, Any]:
    """§187's row. Every field it names, and nothing that needs a second
    query to fill in."""
    return {
        "assurance_record_id": row.assurance_record_id,
        "investigation_id": row.investigation_id,
        "title": row.question or "(no question recorded)",
        "user_id": row.user_id,
        "project_id": row.project_id,
        "at": row.created_at,
        "scope": row.portfolio_scope,
        "language": row.language,
        "turn_index": row.turn_index,
        "officer_level": row.officer_level,
        "model_route": row.model_route,
        "case_family": row.case_family,
        # §184 all the way down to the list row.
        "overall_status": row.overall_status,
        "status_now": row.status_now,
        "operational_assurance": row.operational_assurance,
        "operational_assurance_label": rc.ASSURANCE_LABEL,
        "coverage_pct": round(row.coverage_pct, 1),
        "reference_match": rc.reference_block(row.reference_match_pct,
                                              row.reference_source),
        "dimensions": compact_dimensions(row),
        "critical_failures": row.critical_failure_count,
        "warnings": row.warning_count,
        "good_feedback": row.good_feedback_count,
        "bad_feedback": row.bad_feedback_count,
        "teaching_release_id": row.teaching_release_id,
        "release_current": not row.stale,
        "stale_reasons": list(row.stale_reasons),
        "superseded_by": row.superseded_by,
        "rerun_of": row.rerun_of,
        "open_review": bool(row.critical_failure_count
                            or row.overall_status == rc.NEEDS_REVIEW
                            or row.bad_feedback_count),
    }


@dataclass
class ReviewList:
    """One rendered view of the review list."""

    view: str = RECENT
    rows: list[dict[str, Any]] = field(default_factory=list)
    total_visible: int = 0
    filters: Filters = field(default_factory=Filters)
    #: How many rows the viewer was not shown. A count, never the rows: the
    #: number is useful to an administrator debugging a permission and
    #: discloses nothing about what the rows contain.
    withheld: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "view": self.view,
            "view_label": VIEW_LABELS.get(self.view, self.view),
            "view_means": VIEW_MEANS.get(self.view, ""),
            "views": [{"id": v, "label": VIEW_LABELS[v],
                       "means": VIEW_MEANS[v]} for v in VIEWS],
            "filters": self.filters.to_dict(),
            "filter_fields": [{"field": f, "label": label}
                              for f, label in FILTERS],
            "rows": self.rows,
            "count": len(self.rows),
            "total_visible": self.total_visible,
            "withheld": self.withheld,
            "presentation": "table",
        }


def build(viewer: ac.Viewer, *, view: str = RECENT,
          filters: Filters | None = None,
          limit: int = 100,
          records: list[st.StoredRecord] | None = None) -> ReviewList:
    """§186 and §187 assembled.

    An unknown view falls back to RECENT rather than raising — the caller is
    a URL, and a bookmark from a version that had a different view should
    show something.
    """
    chosen = view if view in VIEWS else RECENT
    predicate = VIEW_PREDICATES[chosen]
    active = filters or Filters()
    source = records if records is not None else st.recent(limit=max(limit,
                                                                     limit))
    visible: list[st.StoredRecord] = []
    withheld = 0
    for row in source:
        if not ac.may_read(viewer, _subject(row)).allowed:
            withheld += 1
            continue
        visible.append(row)

    kept = [r for r in visible
            if predicate(r, viewer) and matches(r, active)]
    # PROJECT means a project the VIEWER is in, which the predicate cannot
    # know on its own without duplicating the access rules.
    if chosen == PROJECT and viewer.reach != ac.BROAD:
        kept = [r for r in kept if r.project_id in viewer.project_ids]

    return ReviewList(view=chosen, rows=[row_for(r) for r in kept[:limit]],
                      total_visible=len(visible), filters=active,
                      withheld=withheld)


def counts(viewer: ac.Viewer,
           records: list[st.StoredRecord] | None = None) -> dict[str, int]:
    """How many rows each view holds, for the tab strip.

    Computed from the SAME predicates the views use. A count that disagrees
    with its list is worse than no count.
    """
    source = records if records is not None else st.recent()
    visible = [r for r in source if ac.may_read(viewer, _subject(r)).allowed]
    tally: dict[str, int] = {}
    for name in VIEWS:
        predicate = VIEW_PREDICATES[name]
        rows = [r for r in visible if predicate(r, viewer)]
        if name == PROJECT and viewer.reach != ac.BROAD:
            rows = [r for r in rows if r.project_id in viewer.project_ids]
        tally[name] = len(rows)
    return tally
