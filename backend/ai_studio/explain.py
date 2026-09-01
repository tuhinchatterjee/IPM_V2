"""
What every Studio object has to be able to say about itself. §117, §118.

    §117: "Every Studio object must answer: WHAT IS THIS? WHY DOES CREDITPROBE
           NEED IT? WHEN IS IT USED? HOW WAS IT VALIDATED? HOW IS IT
           PERFORMING? WHAT IS STALE OR FAILING? WHAT RELEASE USES IT?"

Why this is a type and not a convention
----------------------------------------
Seven questions written in a design document get answered for the first three
objects somebody builds and skipped for the next forty, and the Studio becomes
the admin card wall §117 explicitly says not to build: a grid of names and
numbers that only the person who wrote them can read.

So the seven answers are a dataclass with seven required fields, and
`Explanation.complete` is false when any of them is blank. A tab that ships an
object with three answers filled in ships a visibly incomplete object rather
than an invisibly unexplained one.

Why "how is it performing" may be "not measured"
-------------------------------------------------
Because that is very often the truth, and the alternative — an object that
must claim a score to be displayed — produces invented scores. The rule is
that the FIELD is mandatory and its content may be an honest absence.
`unmeasured()` exists to make writing that absence easier than fabricating a
number.

§118 is the same argument one level down
------------------------------------------
Fourteen fields a configurable object must show before anybody can decide
whether to trust it: what tested it, over how many cases, with what critical
failures, when, at what version, owned by whom, with what limitations. A
validation status with no test set behind it is a colour.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

EXPLANATION_VERSION = "1.0.0"

#: §117's seven, in the order they are asked. Order matters: a reader who has
#: not been told what a thing IS cannot use its score.
QUESTIONS: tuple[tuple[str, str], ...] = (
    ("what", "What is this?"),
    ("why", "Why does CreditProbe need it?"),
    ("when", "When is it used?"),
    ("validated", "How was it validated?"),
    ("performing", "How is it performing?"),
    ("stale_or_failing", "What is stale or failing?"),
    ("release", "What release uses it?"),
)

FIELDS: tuple[str, ...] = tuple(name for name, _ in QUESTIONS)
LABELS: dict[str, str] = dict(QUESTIONS)

#: The honest answer where nothing has measured the object yet. A sentence
#: rather than a blank, because a blank reads as an oversight and this is a
#: fact about the object.
NOT_MEASURED = ("Nothing has evaluated this yet, so there is no performance "
                "to report.")
NOT_RELEASED = ("Not in any frozen release. It is running from the live "
                "configuration.")
NOTHING_STALE = "Nothing recorded as stale or failing."


@dataclass
class Explanation:
    """§117's seven answers for one object."""

    what: str = ""
    why: str = ""
    when: str = ""
    validated: str = ""
    performing: str = ""
    stale_or_failing: str = ""
    release: str = ""

    @property
    def missing(self) -> list[str]:
        return [name for name in FIELDS if not str(
            getattr(self, name, "")).strip()]

    @property
    def complete(self) -> bool:
        return not self.missing

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": EXPLANATION_VERSION,
            "answers": [{"id": name, "question": LABELS[name],
                         "answer": str(getattr(self, name, ""))}
                        for name in FIELDS],
            "complete": self.complete,
            # Named rather than hidden. An object with three answers filled in
            # is visibly incomplete instead of invisibly unexplained.
            "missing": self.missing,
        }


def unmeasured(*, what: str, why: str, when: str,
               validated: str = "", release: str = "") -> Explanation:
    """An explanation for an object nothing has evaluated.

    Exists so writing the honest absence is easier than fabricating a number,
    which is the only way a rule like this survives contact with a deadline.
    """
    return Explanation(
        what=what, why=why, when=when,
        validated=validated or "Not yet validated.",
        performing=NOT_MEASURED, stale_or_failing=NOTHING_STALE,
        release=release or NOT_RELEASED)


# ---------------------------------------------------------------------------
# §118 — drill-down validation
# ---------------------------------------------------------------------------

#: The fourteen fields a configurable intelligence object must show. A
#: validation status with no test set behind it is a colour.
DRILL_FIELDS: tuple[str, ...] = (
    "validation_status", "test_set", "case_count", "passed", "failed",
    "critical_failures", "score_components", "last_run", "version", "owner",
    "evidence", "known_limitations", "staleness", "usage",
)

PASSED = "PASSED"
FAILED = "FAILED"
PARTIAL = "PARTIAL"
#: Nothing has run against it. Never PASSED — the rule this whole product runs
#: on. An unevaluated policy is not a working one.
NOT_EVALUATED = "NOT_EVALUATED"
STALE = "STALE"

VALIDATION_STATES: tuple[str, ...] = (PASSED, FAILED, PARTIAL, NOT_EVALUATED,
                                       STALE)


@dataclass
class Drilldown:
    """§118's fourteen, for one configurable object."""

    validation_status: str = NOT_EVALUATED
    #: WHAT tested it. A status with no named test set is unfalsifiable.
    test_set: str = ""
    case_count: int = 0
    passed: int = 0
    failed: int = 0
    critical_failures: list[str] = field(default_factory=list)
    #: The parts the score is made of, so a reader can disagree with a part.
    score_components: dict[str, Any] = field(default_factory=dict)
    last_run: str = ""
    version: str = ""
    owner: str = ""
    #: Where the evidence lives — a run id, a release file, an evaluation
    #: report. Never the evidence itself: a drill-down that inlined a holdout
    #: result would leak one.
    evidence: list[str] = field(default_factory=list)
    known_limitations: list[str] = field(default_factory=list)
    staleness: list[str] = field(default_factory=list)
    usage: int = 0

    @property
    def rate(self) -> float | None:
        """Pass rate, or None when nothing ran.

        None rather than 0.0, because zero of zero displayed as 0% reads as a
        total failure and is the absence of a measurement.
        """
        total = self.passed + self.failed
        return (self.passed / total) if total else None

    @property
    def trustworthy(self) -> bool:
        """Whether a reader may rely on this object today.

        Deliberately strict: NOT_EVALUATED and STALE are both untrustworthy,
        and a single critical failure overrides the rate. The permissive
        version of this reads as a green tick on a policy nobody has tested.
        """
        return (self.validation_status == PASSED
                and not self.critical_failures and not self.staleness)

    def to_dict(self) -> dict[str, Any]:
        return {
            "validation_status": self.validation_status,
            "test_set": self.test_set or "no test set named",
            "case_count": self.case_count,
            "passed": self.passed, "failed": self.failed,
            "pass_rate": self.rate,
            "critical_failures": list(self.critical_failures),
            "score_components": dict(self.score_components),
            "last_run": self.last_run or "never",
            "version": self.version, "owner": self.owner or "unassigned",
            "evidence": list(self.evidence),
            "known_limitations": list(self.known_limitations),
            "staleness": list(self.staleness),
            "usage": self.usage,
            "trustworthy": self.trustworthy,
            "sentence": self.sentence(),
        }

    def sentence(self) -> str:
        if self.validation_status == NOT_EVALUATED:
            return ("Not evaluated. Nothing has run against this, so its "
                    "status is unknown rather than good.")
        if self.critical_failures:
            return (f"{len(self.critical_failures)} critical failure(s) — "
                    + "; ".join(self.critical_failures[:2])
                    + ". A critical failure overrides the average.")
        if self.staleness:
            return ("Stale: " + ", ".join(self.staleness)
                    + ". The evaluation describes a version that has since "
                      "changed.")
        if self.rate is None:
            return f"{self.validation_status}, with no cases recorded."
        return (f"{self.passed} of {self.passed + self.failed} passed against "
                f"{self.test_set or 'an unnamed set'}"
                + (f", last run {self.last_run}." if self.last_run else "."))


@dataclass
class Object:
    """One thing the Studio shows, with everything §117 and §118 require."""

    object_id: str = ""
    kind: str = ""
    name: str = ""
    explanation: Explanation = field(default_factory=Explanation)
    drilldown: Drilldown = field(default_factory=Drilldown)
    #: Where to go to change it. §105: deep-link rather than duplicate the
    #: editor, because two editors for one object is two sets of validation
    #: and one of them will be the old one.
    edit_in: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def complete(self) -> bool:
        return self.explanation.complete

    def to_dict(self) -> dict[str, Any]:
        return {
            "object_id": self.object_id, "kind": self.kind, "name": self.name,
            "explanation": self.explanation.to_dict(),
            "validation": self.drilldown.to_dict(),
            "edit_in": self.edit_in,
            "complete": self.complete,
            **self.extra,
        }


def audit(objects: list[Object]) -> dict[str, Any]:
    """Which Studio objects cannot explain themselves.

    Run as a test rather than displayed: the point is that shipping an
    unexplained object fails a build, not that a reader discovers one.
    """
    incomplete = [{"object_id": o.object_id, "kind": o.kind,
                   "missing": o.explanation.missing}
                  for o in objects if not o.complete]
    return {"total": len(objects), "incomplete": incomplete,
            "complete": not incomplete}


__all__ = ["DRILL_FIELDS", "Drilldown", "EXPLANATION_VERSION", "Explanation",
           "FAILED", "FIELDS", "LABELS", "NOT_EVALUATED", "NOT_MEASURED",
           "NOT_RELEASED", "NOTHING_STALE", "Object", "PARTIAL", "PASSED",
           "QUESTIONS", "STALE", "VALIDATION_STATES", "audit", "unmeasured"]
