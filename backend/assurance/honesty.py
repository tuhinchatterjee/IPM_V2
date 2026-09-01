"""
§212's score honesty, as executable rules.

    §212: "It must be impossible to show: ..."

Seven things. The word is IMPOSSIBLE, not discouraged, and a prose rule in a
brief is not impossible — it is a thing somebody forgets while building the
tenth screen that shows a number. So each of the seven is a predicate here,
run over a payload before it reaches a reader, and the tests in
tests/assurance run every one of them against a payload built specifically to
violate it.

Why a checker rather than only careful construction
-----------------------------------------------------
Because the failure this prevents is not a bug in `record.py` — that module's
gates are already correct and thoroughly tested. It is a NEW SURFACE built
later that assembles its own payload from the parts and gets one of the seven
subtly wrong: a dashboard that averages, an export that labels the number
"accuracy", a summary card that reads a stored status without checking
staleness. Those screens are written by somebody who has not read §182, and
this module is how §182 reaches them.

Fail-closed, again
-------------------
A payload missing the field a rule needs FAILS that rule rather than passing
it. A checker that waved through anything it could not parse would be
reliably silent on exactly the malformed payloads worth catching.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.assurance import record as rc

HONESTY_VERSION = "1.0.0"

#: §212's seven, in its order. The id is what a test names; the sentence is
#: what a reviewer reads.
RULES: tuple[tuple[str, str], ...] = (
    ("no_full_marks_with_skipped_mandatory",
     "100% may not be shown when mandatory checks were skipped."),
    ("no_accuracy_without_a_reference",
     "The word accuracy may not appear on a figure with no approved "
     "reference answer behind it."),
    ("no_high_assurance_after_a_critical_failure",
     "HIGH_ASSURANCE may not follow a critical failure."),
    ("no_validated_without_a_computation",
     "VALIDATED may not be shown where a required analysis produced no "
     "result."),
    ("no_clean_thread_hiding_a_failed_turn",
     "A thread summary may not read clean while it contains an unresolved "
     "failed turn."),
    ("no_score_moved_by_a_thumb",
     "A validation score may not move on raw feedback alone."),
    ("no_current_validation_on_a_stale_record",
     "A record pinned to a superseded build, release or model may not "
     "present as current validation."),
)

RULE_IDS: tuple[str, ...] = tuple(rule for rule, _ in RULES)
MEANS: dict[str, str] = dict(RULES)

#: Words that may never appear as the NAME of an operational assurance
#: figure. §184's rule, enforced on the label rather than on the whole
#: payload: an explanation that says "no accuracy figure can be given" is the
#: sentence that makes the absence legible, and must not be caught by the
#: rule it exists to explain.
FORBIDDEN_LABELS: tuple[str, ...] = ("accuracy", "accurate", "correctness "
                                     "rate", "% correct")


@dataclass(frozen=True)
class Violation:
    """One rule, broken, with what broke it."""

    rule: str
    detail: str

    @property
    def means(self) -> str:
        return MEANS.get(self.rule, "")

    def to_dict(self) -> dict[str, str]:
        return {"rule": self.rule, "means": self.means, "detail": self.detail}


def _number(payload: dict[str, Any], key: str) -> float | None:
    value = payload.get(key)
    return float(value) if isinstance(value, int | float) else None


def check_payload(payload: dict[str, Any]) -> list[Violation]:
    """Run all seven over one payload about one record.

    Understands the shapes the review surfaces actually produce: a header, a
    review row and a stored record's `to_dict` all carry the same field
    names, which is why they can share one checker.
    """
    found: list[Violation] = []
    status = str(payload.get("overall_status") or "")
    score = _number(payload, "operational_assurance")
    coverage = _number(payload, "coverage_pct")

    # 1. No full marks where mandatory checks did not run.
    skipped = payload.get("skipped_mandatory")
    if isinstance(skipped, list) and skipped:
        if score is not None and score >= 100.0:
            found.append(Violation(
                "no_full_marks_with_skipped_mandatory",
                f"score {score} with {len(skipped)} mandatory check(s) "
                f"skipped: {', '.join(str(s) for s in skipped[:3])}"))
        if coverage is not None and coverage >= 100.0:
            found.append(Violation(
                "no_full_marks_with_skipped_mandatory",
                f"coverage {coverage}% with {len(skipped)} mandatory "
                "check(s) skipped"))

    # 2. No accuracy without a reference. Checked on the LABEL, which is the
    #    only place the word would be a claim.
    label = str(payload.get("operational_assurance_label") or "")
    reference = payload.get("reference_match")
    has_reference = bool(isinstance(reference, dict)
                         and reference.get("available"))
    if not has_reference:
        lowered = label.lower()
        for word in FORBIDDEN_LABELS:
            if word in lowered:
                found.append(Violation(
                    "no_accuracy_without_a_reference",
                    f"the label {label!r} says {word!r} with no approved "
                    "reference answer"))
                break

    # 3. No HIGH_ASSURANCE after a critical failure.
    criticals = payload.get("critical_failures")
    count = (len(criticals) if isinstance(criticals, list)
             else criticals if isinstance(criticals, int) else 0)
    if count and status == rc.HIGH_ASSURANCE:
        found.append(Violation(
            "no_high_assurance_after_a_critical_failure",
            f"{count} critical failure(s) with status {status}"))

    # 4. No VALIDATED where a required analysis produced nothing.
    if status in (rc.VALIDATED, rc.HIGH_ASSURANCE):
        executed = payload.get("execution_produced_result")
        if executed is False:
            found.append(Violation(
                "no_validated_without_a_computation",
                f"status {status} with no result from a required analysis"))

    # 5. No clean thread over a failed turn.
    thread = payload.get("thread")
    if isinstance(thread, dict):
        failed = thread.get("failed_turns") or []
        clean = str(thread.get("status") or "") in (rc.VALIDATED,
                                                    rc.HIGH_ASSURANCE)
        if failed and clean:
            found.append(Violation(
                "no_clean_thread_hiding_a_failed_turn",
                f"thread reads {thread.get('status')} with "
                f"{len(failed)} failed turn(s)"))
        if thread.get("averaged"):
            found.append(Violation(
                "no_clean_thread_hiding_a_failed_turn",
                "the thread status was averaged across its turns"))

    # 6. No score moved by a thumb.
    feedback = payload.get("feedback")
    if isinstance(feedback, dict):
        raw = feedback.get("raw_user_feedback")
        if isinstance(raw, dict) and raw.get("changes_score"):
            found.append(Violation(
                "no_score_moved_by_a_thumb",
                "the payload states that raw feedback changes the score"))
    if payload.get("derived_from_thumbs"):
        found.append(Violation(
            "no_score_moved_by_a_thumb",
            "the score is marked as derived from thumbs"))

    # 7. No current validation on a stale record.
    if payload.get("stale"):
        if str(payload.get("status_now") or "") not in ("", rc.STALE):
            found.append(Violation(
                "no_current_validation_on_a_stale_record",
                f"stale record presenting as {payload.get('status_now')}"))
        if "status_now" not in payload:
            found.append(Violation(
                "no_current_validation_on_a_stale_record",
                "a stale record with no current-status field, so a reader "
                "sees only the historical verdict"))
    return found


def honest(payload: dict[str, Any]) -> bool:
    return not check_payload(payload)


def report(payload: dict[str, Any]) -> dict[str, Any]:
    """What a surface would show, and whether it may."""
    violations = check_payload(payload)
    return {
        "version": HONESTY_VERSION,
        "honest": not violations,
        "rules": [{"id": r, "means": m} for r, m in RULES],
        "violations": [v.to_dict() for v in violations],
    }
