"""What changed between two validation runs.

The question this answers
-------------------------
"What has changed since the last validation?" — asked by every validator
preparing a periodic review, and answered today by opening two screens and
reading across them.

It is answered here from PERSISTED FACTS. Neither run is recalculated, no
partition is read, and the registry is consulted only for a label. A
comparison that recomputed either side would be comparing today's data with
today's data and calling one of them history.

Why a difference is not always a change
---------------------------------------
Three ways two runs can differ, and they need different words:

**The number moved.** Both runs measured it and the values differ. Only this
one is a change in the model's behaviour, and even then only if the movement
is larger than the measurement's own noise — which is why `ROB-BOOTSTRAP` is
carried alongside and why `interval_straddles` is reported rather than left
for a reader to work out.

**The answer became available, or stopped being.** One run measured it and
the other refused. That is a change in the DATA or the ENVIRONMENT, not in
the model, and reporting it as a movement from nothing to 0.65 would be a
fabricated improvement.

**The question changed.** The registry version, the threshold profile or the
calculation kernel differs between the runs. Then the two numbers were not
produced by the same arithmetic and are not comparable at all — the tests
below say so rather than differencing them anyway, because a difference
between two definitions looks exactly like a difference between two books.

That third case is the reason the run header carries five version strings.
"""

from __future__ import annotations

from typing import Any

from backend.models.scorecard_validation import ScvRun
from backend.scorecard.validation import registry as test_registry
from backend.scorecard.validation import states, store

COMPARE_VERSION = "1.0.0"

#: How a single test differs between two runs.
MOVED = "MOVED"
UNCHANGED = "UNCHANGED"
#: Measured on one side only. A change in the data, not in the model.
APPEARED = "APPEARED"
DISAPPEARED = "DISAPPEARED"
#: Neither side produced a number. Both refused, and possibly for different
#: reasons — which is itself worth showing.
ABSENT = "ABSENT"
#: The state changed without the value changing, or with no value on either
#: side. A PASS that became a FAIL on the same number means the LIMIT moved.
VERDICT_CHANGED = "VERDICT_CHANGED"
#: The two sides were not produced by the same arithmetic.
NOT_COMPARABLE = "NOT_COMPARABLE"

MOVEMENTS: tuple[str, ...] = (
    MOVED, UNCHANGED, APPEARED, DISAPPEARED, ABSENT, VERDICT_CHANGED,
    NOT_COMPARABLE,
)

MOVEMENT_MEANING: dict[str, str] = {
    MOVED: "Both runs measured it and the value differs.",
    UNCHANGED: "Both runs measured it and the value is identical.",
    APPEARED: ("The later run measured it and the earlier one could not. A "
               "change in the data, not in the model — reporting it as a "
               "movement would invent an improvement."),
    DISAPPEARED: ("The earlier run measured it and the later one cannot. "
                  "Something the test needs has stopped being available."),
    ABSENT: "Neither run measured it. The reasons may differ.",
    VERDICT_CHANGED: ("The state changed without the value changing. The "
                      "limit moved, not the model."),
    NOT_COMPARABLE: ("The two runs used different versions of the test, the "
                     "threshold profile or the calculation kernel. The "
                     "numbers were not produced by the same arithmetic."),
}

#: The categories a validator compares first, in the order they are asked
#: about. Everything else follows; nothing is hidden.
HEADLINE: tuple[str, ...] = (
    test_registry.DISCRIMINATION,
    test_registry.CALIBRATION,
    test_registry.STABILITY,
    test_registry.VARIABLES,
    test_registry.SEGMENTATION,
    test_registry.CHAMPION_CHALLENGER,
)


def _versions_agree(older: ScvRun,
                    newer: ScvRun) -> tuple[bool, list[str]]:
    """Whether the two runs were produced by the same arithmetic.

    Named field by field. "The versions differ" tells a reader nothing about
    whether to trust the comparison; "the threshold profile moved from 1.0.0
    to 1.1.0" tells them the numbers are fine and the verdicts are not.
    """
    moved: list[str] = []
    for field, label in (
        ("registry_version", "test registry"),
        ("threshold_profile_version", "threshold profile"),
        ("calculation_version", "calculation kernel"),
        ("states_version", "result-state vocabulary"),
    ):
        before, after = getattr(older, field, ""), getattr(newer, field, "")
        if before != after:
            moved.append(f"{label} {before or '(none)'} → {after or '(none)'}")
    return (not moved), moved


def _movement(before: Any, after: Any, comparable: bool) -> str:
    if not comparable:
        return NOT_COMPARABLE
    if before is None and after is None:
        return ABSENT
    if before is None:
        return APPEARED
    if after is None:
        return DISAPPEARED
    return UNCHANGED if before == after else MOVED


def _test_row(test_id: str, older, newer, comparable: bool) -> dict[str, Any]:
    """One test, both sides, and what the difference means."""
    before = older.value if older is not None else None
    after = newer.value if newer is not None else None
    was = older.state if older is not None else ""
    now = newer.state if newer is not None else ""

    movement = _movement(before, after, comparable)
    # A verdict that changed on an unchanged number is the limit moving, and
    # it is the one a validator most needs pointed at: nothing about the book
    # changed, and the model is now reported differently.
    if movement == UNCHANGED and was != now:
        movement = VERDICT_CHANGED

    delta = None
    relative = None
    if movement == MOVED and before is not None and after is not None:
        delta = after - before
        if before:
            relative = delta / abs(before)

    found = test_registry.resolve(test_id)
    return {
        "test_id": test_id,
        "test_name": found.name if found else "",
        "category": found.category if found else "",
        "movement": movement,
        "movement_means": MOVEMENT_MEANING[movement],
        "before": {
            "value": before,
            "state": was,
            "state_label": states.STATE_LABELS.get(was, was),
            "limit": older.limit_value if older is not None else None,
            "limit_source": older.limit_source if older is not None else "",
            "observations": older.observations if older is not None else 0,
            "events": older.events if older is not None else 0,
            "detail": older.detail if older is not None else "",
        },
        "after": {
            "value": after,
            "state": now,
            "state_label": states.STATE_LABELS.get(now, now),
            "limit": newer.limit_value if newer is not None else None,
            "limit_source": newer.limit_source if newer is not None else "",
            "observations": newer.observations if newer is not None else 0,
            "events": newer.events if newer is not None else 0,
            "detail": newer.detail if newer is not None else "",
        },
        "delta": delta,
        "relative_delta": relative,
        #: True when the limit itself moved. Reported separately from the
        #: value, because "the model got worse" and "we tightened the rule"
        #: are different findings and only one of them is about the model.
        "limit_moved": (
            older is not None and newer is not None
            and older.limit_value != newer.limit_value),
    }


def _adverse(row: dict[str, Any]) -> bool:
    """Whether this row is bad news, however it got there."""
    if row["movement"] in (DISAPPEARED, NOT_COMPARABLE):
        return True
    after = row["after"]["state"]
    before = row["before"]["state"]
    if after in (states.FAIL, states.CALCULATION_ERROR):
        return True
    return after == states.WARNING and before == states.PASS


def compare(older: ScvRun,
            newer: ScvRun) -> dict[str, Any]:
    """Two persisted runs, differenced. Neither is recalculated.

    Ordered oldest-first by the caller's choice rather than by timestamp: a
    validator comparing against a specific earlier run means that one, not
    whichever happens to be older.
    """
    if older.run_key == newer.run_key:
        raise store.StoreError(
            "A run compared with itself has no differences to report.")
    if older.model_id != newer.model_id:
        raise store.StoreError(
            f"{older.model_id} and {newer.model_id} are different scorecards. "
            "A difference between two models is not a change over time, and "
            "presenting it as one is how a comparison becomes misleading.")

    comparable, drift = _versions_agree(older, newer)

    left = {(r.test_id, r.segment): r for r in older.results}
    right = {(r.test_id, r.segment): r for r in newer.results}
    keys = sorted(set(left) | set(right))

    rows = [_test_row(test_id, left.get((test_id, segment)),
                      right.get((test_id, segment)), comparable)
            for test_id, segment in keys]

    by_category: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_category.setdefault(row["category"], []).append(row)

    was_findings = {f.finding_key: f for f in older.findings}
    now_findings = {f.finding_key: f for f in newer.findings}

    return {
        "compare_version": COMPARE_VERSION,
        "model_id": newer.model_id,
        "model_name": newer.model_name,
        "before": store.run_header(older),
        "after": store.run_header(newer),
        # Stated before any number is read. Two runs produced by different
        # arithmetic are not comparable, and burying that under a table of
        # differences is how a definition change gets read as a book change.
        "comparable": comparable,
        "version_drift": drift,
        "not_comparable_because": (
            "" if comparable else
            "These runs were produced by different code: "
            + "; ".join(drift)
            + ". The values below are shown for reference and are not "
              "differenced, because a difference between two definitions "
              "looks exactly like a difference between two books."),
        "data_moved": older.dataset_version != newer.dataset_version,
        "data_note": (
            f"{older.dataset_as_of or 'unknown'} → "
            f"{newer.dataset_as_of or 'unknown'}"),
        "tests": rows,
        "by_category": by_category,
        "headline": [row for row in rows if row["category"] in HEADLINE],
        "adverse": [row for row in rows if _adverse(row)],
        "moved": [row for row in rows if row["movement"] == MOVED],
        "verdict_changes": [row for row in rows
                            if row["movement"] == VERDICT_CHANGED],
        "limit_changes": [row for row in rows if row["limit_moved"]],
        "findings": {
            "raised": [store.finding_body(f) for k, f in now_findings.items()
                       if k not in was_findings],
            "cleared": [store.finding_body(f) for k, f in was_findings.items()
                        if k not in now_findings],
            "persisting": [store.finding_body(f)
                           for k, f in now_findings.items()
                           if k in was_findings],
        },
        "coverage": {
            "before": {"measured": older.measured, "returned": older.returned},
            "after": {"measured": newer.measured, "returned": newer.returned},
        },
        "movements": list(MOVEMENTS),
        "movement_meaning": dict(MOVEMENT_MEANING),
        "reproduced_from": (
            "Both sides were read from stored rows. Neither run was "
            "recalculated, and neither will move when the data does."),
    }


__all__ = [
    "ABSENT", "APPEARED", "COMPARE_VERSION", "DISAPPEARED", "HEADLINE",
    "MOVED", "MOVEMENTS", "MOVEMENT_MEANING", "NOT_COMPARABLE", "UNCHANGED",
    "VERDICT_CHANGED", "compare",
]
