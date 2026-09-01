"""Development, validation and sealed holdout. §58, §72.

Three partitions and one rule that makes them worth having: **a set used to
fix things cannot also be the set that says the fixes worked.**

DEVELOPMENT is where the work happens — prompts, routing, policies, teaching
cases, regression. It is looked at daily and tuned against, and after enough
of that it stops being evidence of anything except that somebody tuned
against it.

VALIDATION is out-of-sample. §58: "not used to optimize every individual
fix." Its purpose is to notice when development improvement stopped meaning
general improvement, and the moment it is used to steer a fix it can no
longer do that.

SEALED HOLDOUT is for formal certification only, and §58 lists six places
its content must never reach — live runtime, teaching retrieval, prompt
optimization, Brain import training, the continuous-learning UI, and
ordinary Administrators. This module holds the list and the check.

What is enforced here rather than promised
-------------------------------------------
`may_expose()` decides from the audience, not from the caller's intention.
`hygiene()` reports when validation is being consulted often enough to be at
risk of becoming a second development set — the failure mode that has no
symptom until a release lands badly.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

PARTITIONS_VERSION = "1.0.0"

DEVELOPMENT = "DEVELOPMENT"
VALIDATION = "VALIDATION"
SEALED_HOLDOUT = "SEALED_HOLDOUT"

PARTITIONS: tuple[str, ...] = (DEVELOPMENT, VALIDATION, SEALED_HOLDOUT)

MEANS: dict[str, str] = {
    DEVELOPMENT: "Day-to-day improvement: prompts, routing, policies, "
                 "teaching cases and regression. Tuned against, and "
                 "therefore not evidence that anything generalises.",
    VALIDATION: "Out-of-sample. Its job is to notice when development "
                "improvement stopped meaning general improvement, and it "
                "can only do that while nobody tunes against it.",
    SEALED_HOLDOUT: "Formal certification and release gates only. Its "
                    "content reaches nothing else, and aggregate figures "
                    "from it appear only after an approved certification "
                    "run.",
}

USED_FOR: dict[str, tuple[str, ...]] = {
    DEVELOPMENT: ("day-to-day improvement", "prompt tuning",
                  "routing tuning", "policy tuning",
                  "teaching case development", "regression testing",
                  "frequent scheduled evaluation"),
    VALIDATION: ("out-of-sample validation", "release-candidate comparison",
                 "periodic continuous-learning measurement"),
    SEALED_HOLDOUT: ("formal certification", "release gates"),
}

#: §58's six. Where sealed-holdout CONTENT may never appear, in the words
#: §58 uses, so a refusal quotes the rule rather than paraphrasing it.
NEVER_EXPOSE_TO: tuple[tuple[str, str], ...] = (
    ("live_runtime", "a live answer could quote the gold and score itself "
                     "correct"),
    ("teaching_retrieval", "a retrieved holdout case is training on the "
                           "exam"),
    ("prompt_optimization", "a prompt tuned against the holdout makes the "
                            "holdout measure the tuning"),
    ("brain_import_training", "an imported Brain trained on our holdout "
                              "would score perfectly and teach nothing"),
    ("continuous_learning_ui", "a screen showing holdout questions is a "
                               "screen somebody reads before a "
                               "certification run"),
    ("ordinary_administrators", "an administrator is not a certification "
                                "authority, and the fewer people who have "
                                "seen the questions the longer they mean "
                                "something"),
)

AUDIENCES: tuple[str, ...] = tuple(a for a, _ in NEVER_EXPOSE_TO)

EXPECTED_AUDIENCES = 6
if len(NEVER_EXPOSE_TO) != EXPECTED_AUDIENCES:
    raise AssertionError(
        f"§58 names {EXPECTED_AUDIENCES} places sealed-holdout content may "
        f"never reach; this module has {len(NEVER_EXPOSE_TO)}.")

#: What MAY be shown from the sealed holdout, and only after certification:
#: aggregate scores. Never a question, never a gold answer, never a case id.
AGGREGATE_ONLY: frozenset[str] = frozenset({
    "score", "case_count", "critical_failures", "coverage", "certified_at",
    "certification_id", "confidence",
})


class PartitionError(Exception):
    """An exposure or a use that was refused, and why."""


def may_expose(partition: str, audience: str, *,
               certified: bool = False) -> tuple[bool, str]:
    """Whether this partition's CONTENT may be shown to this audience.

    Content, not aggregates. A certified aggregate score is publishable;
    the questions behind it are not, and `certified` does not change that —
    certification establishes that a score is meaningful, not that the exam
    may be circulated.
    """
    if partition not in PARTITIONS:
        return False, f"{partition!r} is not a partition"
    if partition != SEALED_HOLDOUT:
        return True, ""
    reason = dict(NEVER_EXPOSE_TO).get(audience)
    if reason:
        return False, (
            f"§58 forbids sealed-holdout content reaching {audience}: "
            f"{reason}. Aggregate certified metrics may be shown; the "
            "questions and gold answers may not, certified or otherwise.")
    return False, (
        f"{audience!r} is not a known audience, and an unknown audience is "
        "refused rather than allowed — a typo in a caller should not open "
        "the holdout")


def aggregate(payload: dict[str, Any]) -> dict[str, Any]:
    """The only shape of sealed-holdout figure that may leave.

    Filters to the allowlist rather than removing known-bad keys. A
    blocklist is a list of the field names somebody thought of, and the
    field that leaks the questions will be called something else.
    """
    return {k: v for k, v in payload.items() if k in AGGREGATE_ONLY}


# ------------------------------------------------------------- §72 hygiene

#: How often validation may be consulted before it stops being
#: out-of-sample. Not a hard limit — there is no honest hard limit — but a
#: number that makes the drift visible while it is still reversible.
VALIDATION_RUNS_PER_MONTH = 8

#: Consulting validation more often than development means validation IS
#: the development set, whatever the labels say.
SUSPICIOUS_RATIO = 0.5


@dataclass
class Use:
    """One evaluation run against one partition."""

    partition: str
    at: datetime
    purpose: str = ""
    by: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"partition": self.partition, "at": self.at.isoformat(),
                "purpose": self.purpose, "by": self.by}


@dataclass
class Hygiene:
    """§72. Whether validation is still out-of-sample."""

    development_runs: int = 0
    validation_runs: int = 0
    holdout_runs: int = 0
    window_days: int = 30
    findings: list[str] = field(default_factory=list)

    @property
    def healthy(self) -> bool:
        return not self.findings

    def to_dict(self) -> dict[str, Any]:
        return {
            "window_days": self.window_days,
            "development_runs": self.development_runs,
            "validation_runs": self.validation_runs,
            "sealed_holdout_runs": self.holdout_runs,
            "healthy": self.healthy,
            "findings": list(self.findings),
            "note": (
                "A set used to fix things cannot also be the set that says "
                "the fixes worked. This does not stop anybody running the "
                "validation set; it makes the drift visible while it is "
                "still reversible."
            ),
        }


def hygiene(uses: list[Use], *, window_days: int = 30,
            now: datetime | None = None) -> Hygiene:
    """How the three partitions have actually been used lately.

    Reports rather than blocks. A hard limit would be gamed by whoever
    needed one more run before a release, and the honest control is that
    the ratio is on a screen somebody reviews.
    """
    when = now or datetime.now(UTC)
    since = when - timedelta(days=window_days)
    recent = [u for u in uses if u.at >= since]

    report = Hygiene(
        development_runs=sum(1 for u in recent if u.partition == DEVELOPMENT),
        validation_runs=sum(1 for u in recent if u.partition == VALIDATION),
        holdout_runs=sum(1 for u in recent if u.partition == SEALED_HOLDOUT),
        window_days=window_days,
    )

    if report.validation_runs > VALIDATION_RUNS_PER_MONTH:
        report.findings.append(
            f"the validation set was run {report.validation_runs} times in "
            f"{window_days} days. Above about {VALIDATION_RUNS_PER_MONTH} it "
            "starts to behave like a second development set: every look is "
            "a chance to tune towards it, and the tuning does not feel like "
            "tuning")
    if (report.development_runs
            and report.validation_runs / max(report.development_runs, 1)
            > SUSPICIOUS_RATIO):
        report.findings.append(
            "validation is being run nearly as often as development. "
            "Whatever the labels say, that is one set being used for both "
            "jobs")
    if report.holdout_runs > 1:
        report.findings.append(
            f"the sealed holdout was run {report.holdout_runs} times. §58: "
            "do not run the sealed holdout every hour — each run spends "
            "some of what makes it meaningful")
    if report.validation_runs == 0 and report.development_runs > 0:
        report.findings.append(
            "development was evaluated and validation was not. Development "
            "improvement with no out-of-sample check is not evidence that "
            "anything generalised")
    return report


def tuning_allowed(partition: str) -> tuple[bool, str]:
    """Whether a fix may be steered by results from this partition.

    §58: validation is "not used to optimize every individual fix". The
    moment it is, it stops being able to tell anybody whether development
    improvement generalised — which is the only thing it was for.
    """
    if partition == DEVELOPMENT:
        return True, ""
    if partition == VALIDATION:
        return False, (
            "§58: the validation set is not used to optimise individual "
            "fixes. Tuning against it destroys the only thing it can tell "
            "you — whether development improvement generalised")
    if partition == SEALED_HOLDOUT:
        return False, (
            "the sealed holdout is for formal certification only. A system "
            "tuned against it certifies its own tuning")
    return False, f"{partition!r} is not a partition"
