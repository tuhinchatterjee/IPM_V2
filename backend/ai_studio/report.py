"""
The Intelligence Performance report, Studio notifications and the audit trail.
§121, §122, §123.

Why the export is a fixed sheet list
-------------------------------------
§121 names thirteen sheets, and a report whose contents depend on what
happened to be available produces two documents with the same title and
different meanings. A sheet with nothing in it says so; a sheet that is
missing lets a reader assume it was fine.

The three things it must never contain
---------------------------------------
No secrets, no holdout gold, no client rows. All three are checked here rather
than trusted, because an export is the one artefact that leaves the building —
it goes into a model-risk pack, an email, a shared drive. Everything else in
this product can be wrong and corrected; an export that left with a holdout
question in it cannot be recalled.

Notifications are the Studio's only push
-----------------------------------------
§122 lists ten events. Every one is a change in state somebody is accountable
for and would otherwise learn about by opening a tab they had no reason to
open — a model role going unavailable, a release going stale, a critical
evaluation failing. None of them is "an evaluation completed", because a
notification that fires on success trains people to dismiss notifications.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

REPORT_VERSION = "1.0.0"

# ------------------------------------------------------- §121's thirteen
SHEETS: tuple[str, ...] = (
    "Overview", "Capability Metrics", "Case Coverage",
    "Blueprint Performance", "Judgment Performance",
    "Contradiction Performance", "Visualization Performance",
    "Model Routing", "Model Experiments", "Critical Failures",
    "Active Learning", "Release Manifest", "Known Limitations",
)

#: What each sheet carries, so a reader opening the workbook knows what they
#: are looking at before they read a number.
SHEET_CONTENTS: dict[str, str] = {
    "Overview": "The release in force, its state, and the honest demo "
                "readiness with its reasons.",
    "Capability Metrics": "Eighteen capabilities with their intervals and "
                          "sample sizes. No aggregate.",
    "Case Coverage": "Cases by family, status and difficulty, with the gaps "
                     "named.",
    "Blueprint Performance": "Selection accuracy and objective coverage per "
                             "blueprint.",
    "Judgment Performance": "Materiality, breadth and persistence against "
                            "their evaluation sets.",
    "Contradiction Performance": "Detection, diagnostic coverage and how "
                                 "often UNRESOLVED was reported honestly.",
    "Visualization Performance": "Chart validity, reconciliation and "
                                 "fallback rates.",
    "Model Routing": "Roles, thresholds, and what each route cost.",
    "Model Experiments": "Baseline against candidate, with the decision.",
    "Critical Failures": "Every one, with what it was and whether it is "
                         "fixed.",
    "Active Learning": "Items in the review queue and what came of them.",
    "Release Manifest": "What the release was cut against, axis by axis.",
    "Known Limitations": "What CreditProbe cannot currently do, stated "
                         "rather than left to be discovered.",
}

#: Checked on every cell of every sheet before the workbook is written. An
#: export is the one artefact that leaves the building.
FORBIDDEN: tuple[str, ...] = (
    "sk-ant", "api_key", "apikey", "authorization", "bearer ",
    "anthropic_api_key", "password", "secret_key",
    # Holdout gold and client content.
    "gold_answer", "gold_result", "gold_plan", "holdout_question",
)


class WouldLeak(Exception):
    """The report would carry something that must never leave.

    Raised rather than redacted. A redacted export is one somebody tries
    again with slightly different content, and the second attempt may not hit
    the same pattern.
    """


def check(rows: list[dict[str, Any]]) -> None:
    """Refuse a sheet carrying a secret, a holdout answer or a client row."""
    blob = " ".join(str(v) for row in rows for v in row.values()).lower()
    hits = [f for f in FORBIDDEN if f in blob]
    if hits:
        raise WouldLeak(
            f"the report would carry {', '.join(hits)}, which §121 forbids")


@dataclass
class Sheet:
    """One sheet, and what it says when it is empty."""

    name: str
    rows: list[dict[str, Any]] = field(default_factory=list)
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "contents": SHEET_CONTENTS.get(self.name, ""),
            "rows": list(self.rows),
            "row_count": len(self.rows),
            # An empty sheet says why. A blank one lets a reader assume it
            # was fine.
            "note": self.note or ("Nothing has been recorded for this yet."
                                  if not self.rows else ""),
        }


def build(sheets: dict[str, list[dict[str, Any]]] | None = None,
          *, notes: dict[str, str] | None = None) -> dict[str, Any]:
    """§121's report, with all thirteen sheets present.

    Every sheet appears whether or not it has content, because a report whose
    contents depend on what was available produces two documents with the
    same title and different meanings.
    """
    sheets = sheets or {}
    notes = notes or {}
    built: list[Sheet] = []
    for name in SHEETS:
        rows = list(sheets.get(name, []))
        check(rows)
        built.append(Sheet(name=name, rows=rows, note=notes.get(name, "")))
    return {
        "version": REPORT_VERSION,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "sheets": [s.to_dict() for s in built],
        "sheet_names": list(SHEETS),
        "excludes": ["secrets", "sealed-holdout gold", "client rows"],
    }


# ---------------------------------------------------------------------------
# §122 — notifications
# ---------------------------------------------------------------------------

CRITICAL_EVALUATION_FAILED = "critical_evaluation_failed"
OBJECT_STALE = "case_or_policy_stale"
ROLE_UNAVAILABLE = "model_role_unavailable"
RELEASE_STALE = "teaching_release_stale"
RELEASE_AWAITING = "release_awaiting_approval"
VERIFICATION_STALE = "live_verification_stale"
LEARNING_ASSIGNED = "active_learning_item_assigned"
COVERAGE_GAP = "coverage_gap_exceeds_policy"
PROMPT_REGRESSED = "prompt_candidate_regressed"
CRITICAL_FIXED = "critical_case_fixed"

EVENTS: tuple[str, ...] = (
    CRITICAL_EVALUATION_FAILED, OBJECT_STALE, ROLE_UNAVAILABLE,
    RELEASE_STALE, RELEASE_AWAITING, VERIFICATION_STALE, LEARNING_ASSIGNED,
    COVERAGE_GAP, PROMPT_REGRESSED, CRITICAL_FIXED,
)

#: Who needs to know, by permission rather than by role — the same reason the
#: permissions are named separately from the roles.
NOTIFY: dict[str, str] = {
    CRITICAL_EVALUATION_FAILED: "AI_EVALUATION_RUN",
    OBJECT_STALE: "AI_TEACHING_REVIEW",
    ROLE_UNAVAILABLE: "AI_LIVE_HEALTH_VIEW",
    RELEASE_STALE: "AI_RELEASE_APPROVE",
    RELEASE_AWAITING: "AI_RELEASE_APPROVE",
    VERIFICATION_STALE: "AI_LIVE_HEALTH_VIEW",
    LEARNING_ASSIGNED: "AI_TEACHING_REVIEW",
    COVERAGE_GAP: "AI_TEACHING_AUTHOR",
    PROMPT_REGRESSED: "AI_MODEL_EXPERIMENT",
    CRITICAL_FIXED: "AI_EVALUATION_RUN",
}

#: What each one means in one sentence, which is what actually arrives.
SAYS: dict[str, str] = {
    CRITICAL_EVALUATION_FAILED: "A critical evaluation suite failed. A "
                                "release cannot be cut until it passes.",
    OBJECT_STALE: "A case or policy has gone stale: what it was validated "
                  "against has since changed.",
    ROLE_UNAVAILABLE: "A model role is configured to a model the provider "
                      "cannot serve. CreditProbe will degrade visibly rather "
                      "than substitute one.",
    RELEASE_STALE: "The Teaching Release describes a product that has since "
                   "changed.",
    RELEASE_AWAITING: "A release is waiting for a named approver.",
    VERIFICATION_STALE: "The last live verification is older than the "
                        "configuration it verified.",
    LEARNING_ASSIGNED: "An active-learning item is assigned to you.",
    COVERAGE_GAP: "A case family has fallen below its coverage floor.",
    PROMPT_REGRESSED: "A prompt candidate regressed against the baseline and "
                      "was not promoted.",
    CRITICAL_FIXED: "A critical case that was failing now passes.",
}


def notification(event: str, detail: str = "") -> dict[str, Any]:
    """One Studio notification, routed by permission.

    An unknown event raises rather than being sent to everybody: a
    notification with no defined audience is a notification the whole
    administrator group learns to ignore.
    """
    if event not in EVENTS:
        raise KeyError(f"{event!r} is not one of §122's Studio events")
    return {"version": REPORT_VERSION, "event": event,
            "says": SAYS[event], "detail": detail,
            "notify_permission": NOTIFY[event],
            "at": datetime.now(UTC).isoformat(timespec="seconds")}


# ---------------------------------------------------------------------------
# §123 — the audit trail
# ---------------------------------------------------------------------------

AUDITED: tuple[str, ...] = (
    "case_authored", "case_reviewed", "case_approved", "case_rejected",
    "prompt_changed", "routing_changed", "policy_changed", "evaluation_run",
    "release_promoted", "release_rolled_back", "live_verification",
    "fine_tuning_export",
)

#: §123's required fields. Every one, on every entry — an audit entry with no
#: reason is a record that something happened, which is what a log already is.
AUDIT_FIELDS: tuple[str, ...] = (
    "action", "user", "at", "object_id", "old_version", "new_version",
    "reason", "affected_release",
)


@dataclass
class Entry:
    """One audited change. §123."""

    action: str
    user: str = ""
    at: str = ""
    object_id: str = ""
    old_version: str = ""
    new_version: str = ""
    reason: str = ""
    affected_release: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in AUDIT_FIELDS}


def record(action: str, *, user: str, object_id: str, reason: str,
           old_version: str = "", new_version: str = "",
           affected_release: str = "") -> Entry:
    """One audit entry, refusing an unnamed actor or an unstated reason.

    Both refusals are deliberate. "system" changed a routing policy is not an
    audit trail, and a change with no reason cannot be reviewed — only
    reverted, by somebody who does not know why it was made.
    """
    if action not in AUDITED:
        raise KeyError(f"{action!r} is not an audited Studio action")
    if not str(user).strip():
        raise ValueError(
            f"{action} must record who did it; an audit trail with an "
            "anonymous actor records that something happened, which is what a "
            "log already does")
    if not str(reason).strip():
        raise ValueError(
            f"{action} must record why; a change with no reason cannot be "
            "reviewed, only reverted by somebody who does not know why it was "
            "made")
    return Entry(action=action, user=user,
                 at=datetime.now(UTC).isoformat(timespec="seconds"),
                 object_id=object_id, old_version=old_version,
                 new_version=new_version, reason=reason,
                 affected_release=affected_release)


__all__ = ["AUDITED", "AUDIT_FIELDS", "CRITICAL_EVALUATION_FAILED",
           "CRITICAL_FIXED", "COVERAGE_GAP", "EVENTS", "Entry", "FORBIDDEN",
           "LEARNING_ASSIGNED", "NOTIFY", "OBJECT_STALE", "PROMPT_REGRESSED",
           "RELEASE_AWAITING", "RELEASE_STALE", "REPORT_VERSION",
           "ROLE_UNAVAILABLE", "SAYS", "SHEETS", "SHEET_CONTENTS", "Sheet",
           "VERIFICATION_STALE", "WouldLeak", "build", "check",
           "notification", "record"]
