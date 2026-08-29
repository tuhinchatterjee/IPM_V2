"""
Every question becomes an auditable Learning Observation. §12.

Why every question and not every complaint
--------------------------------------------
A corpus of complaints is a corpus of the answers somebody bothered to
complain about, which is a biased sample of the answers that were wrong and
tells you nothing about the ones that were right. Recording every question —
labelled or not — is what makes it possible to ask "how often does this go
wrong?" rather than "how often does somebody say so?".

UNLABELED is a state, not a default
-------------------------------------
An observation with no feedback is UNLABELED. It is explicitly NOT
`satisfied`, and §12 says so: "Do not assume no feedback means satisfaction."
The response rate on a feedback prompt is somewhere between five and twenty
per cent in every product that has ever measured it, so reading silence as
approval would mean concluding that eighty per cent of answers were good on
the evidence of nothing at all.

What an unlabelled observation may be used for
------------------------------------------------
Replay, drift analysis, uncertainty review, duplicate detection and test
generation — all of which are ways of LOOKING at what the product did. What it
may not do is become teaching truth: a case whose expected answer is "whatever
CreditProbe said, because nobody objected" teaches the product to keep doing
what it already does, which is the one thing it certainly does not need to
learn.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

OBSERVATION_VERSION = "1.0.0"

UNLABELED = "UNLABELED"
LABELED = "LABELED"
#: The user was asked and declined. Distinct from UNLABELED: the prompt was
#: seen. Collapsing the two makes the response rate meaningless.
DECLINED = "DECLINED"

LABELS: tuple[str, ...] = (UNLABELED, LABELED, DECLINED)

LABEL_MEANS: dict[str, str] = {
    UNLABELED: "No feedback was given. This is not approval — silence is the "
               "commonest response to a feedback prompt and says nothing "
               "about the answer.",
    LABELED: "A user rated this answer.",
    DECLINED: "The user saw the prompt and skipped it.",
}

#: What an unlabelled observation may be used for. §12's list, as a set the
#: code can be checked against rather than a paragraph nobody re-reads.
REPLAY = "replay"
DRIFT = "drift_analysis"
UNCERTAINTY = "uncertainty_review"
DUPLICATES = "duplicate_detection"
TEST_CANDIDATES = "test_generation_candidates"

UNLABELED_USES: frozenset[str] = frozenset({
    REPLAY, DRIFT, UNCERTAINTY, DUPLICATES, TEST_CANDIDATES})

#: What NOTHING unlabelled may be used for.
TEACHING_TRUTH = "teaching_truth"
RELEASE_EVIDENCE = "release_evidence"
ACCURACY_MEASUREMENT = "accuracy_measurement"

FORBIDDEN_UNLABELED_USES: frozenset[str] = frozenset({
    TEACHING_TRUTH, RELEASE_EVIDENCE, ACCURACY_MEASUREMENT})


@dataclass
class Observation:
    """One question, everything CreditProbe did with it, and how it landed.

    §12's field list, and the reason it is this long is reproduction: an
    observation that records the question and the answer is a transcript, and
    a transcript cannot be replayed against a candidate release. What can be
    replayed is the reading, the plan, the datasets and the versions — so
    those are what is kept.
    """

    observation_id: str = field(
        default_factory=lambda: f"obs-{uuid.uuid4().hex[:16]}")

    # ---- the turn
    tenant: str = ""
    user_id: str = ""
    project_id: str = ""
    investigation_id: str = ""
    message_id: str = ""
    answer_id: str = ""
    turn_index: int = 0
    question: str = ""

    # ---- what CreditProbe made of it
    reading: dict[str, Any] = field(default_factory=dict)
    working_memory: dict[str, Any] = field(default_factory=dict)
    officer_level: int | None = None
    officer_title: str = ""
    agents: list[str] = field(default_factory=list)
    task_graph: dict[str, Any] = field(default_factory=dict)
    tools: list[str] = field(default_factory=list)
    datasets: list[str] = field(default_factory=list)
    plan: dict[str, Any] = field(default_factory=dict)
    plan_fingerprint: str = ""

    # ---- what came back
    result: dict[str, Any] = field(default_factory=dict)
    validation: dict[str, Any] = field(default_factory=dict)
    interpretation: str = ""
    assurance: dict[str, Any] = field(default_factory=dict)
    outcome: str = ""
    latency_ms: int = 0

    # ---- versions, so a replay is against the same world
    build_sha: str = ""
    ontology_version: str = ""
    method_versions: dict[str, str] = field(default_factory=dict)
    teaching_release_id: str = ""
    regulatory_release_id: str = ""
    learning_release_id: str = ""

    # ---- how it landed
    label: str = UNLABELED
    feedback_event_id: str = ""
    rating: str = ""
    at: datetime = field(default_factory=lambda: datetime.now(UTC))
    schema_version: str = OBSERVATION_VERSION

    @property
    def labelled(self) -> bool:
        return self.label == LABELED

    @property
    def replayable(self) -> bool:
        """Whether this observation can be run again against a candidate.

        A question with no plan and no reading cannot be replayed — there is
        nothing to compare. It stays an observation because the response rate
        and the drift analysis still want it; it just cannot be in a replay
        set, and the Replay Lab says so rather than silently dropping it.
        """
        return bool(self.question and self.build_sha
                    and (self.plan_fingerprint or self.reading))

    def may_be_used_for(self, purpose: str) -> tuple[bool, str]:
        """Whether this observation may be put to a given use. §12.

        Returns the reason as well as the verdict, because "no" without a
        reason is how a rule gets worked around by somebody who assumes it
        was arbitrary.
        """
        if purpose in FORBIDDEN_UNLABELED_USES and not self.labelled:
            return False, (
                f"this observation is {self.label} — nobody said whether the "
                "answer was right — and an unlabelled observation may not "
                f"become {purpose.replace('_', ' ')}. Silence is not approval.")
        if purpose == REPLAY and not self.replayable:
            return False, ("this observation carries no plan and no reading, "
                           "so there is nothing to replay against a "
                           "candidate.")
        if purpose in UNLABELED_USES:
            return True, ""
        if purpose in FORBIDDEN_UNLABELED_USES and self.labelled:
            return True, ""
        return False, f"{purpose!r} is not a recognised use of an observation"

    def fingerprint(self) -> str:
        body = json.dumps(
            {"question": self.question, "plan": self.plan_fingerprint,
             "datasets": sorted(self.datasets), "build": self.build_sha,
             "officer": self.officer_level},
            sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(body.encode()).hexdigest()[:16]

    def to_dict(self) -> dict[str, Any]:
        return {
            "observation_id": self.observation_id, "tenant": self.tenant,
            "user": self.user_id, "project": self.project_id,
            "investigation": self.investigation_id,
            "message": self.message_id, "answer": self.answer_id,
            "turn_index": self.turn_index, "question": self.question,
            "reading": dict(self.reading),
            "working_memory": dict(self.working_memory),
            "officer_level": self.officer_level, "officer": self.officer_title,
            "agents": list(self.agents), "task_graph": dict(self.task_graph),
            "tools": list(self.tools), "datasets": list(self.datasets),
            "plan": dict(self.plan), "plan_fingerprint": self.plan_fingerprint,
            "result": dict(self.result), "validation": dict(self.validation),
            "interpretation": self.interpretation,
            "assurance": dict(self.assurance), "outcome": self.outcome,
            "latency_ms": self.latency_ms, "build_sha": self.build_sha,
            "ontology_version": self.ontology_version,
            "method_versions": dict(self.method_versions),
            "teaching_release_id": self.teaching_release_id,
            "regulatory_release_id": self.regulatory_release_id,
            "learning_release_id": self.learning_release_id,
            "label": self.label, "label_means": LABEL_MEANS.get(self.label, ""),
            "feedback_event_id": self.feedback_event_id,
            "rating": self.rating,
            "labelled": self.labelled, "replayable": self.replayable,
            "fingerprint": self.fingerprint(),
            "at": self.at.isoformat(),
            "schema_version": self.schema_version,
        }


def observe(answered: Any, *, question: str, tenant: str = "",
            user_id: str = "", project_id: str = "",
            investigation_id: str = "", message_id: str = "",
            answer_id: str = "", turn_index: int = 0,
            officer: Any = None, latency_ms: int = 0) -> Observation:
    """One observation, read off what the turn actually produced.

    Defensive throughout: this runs after an answer has already been given,
    and an observation that raised would turn a recorded answer into a failed
    one. A field it cannot read is left empty, which is visible in the
    observation rather than hidden by it.
    """
    build = getattr(answered, "build", None)
    runtime = getattr(answered, "runtime", None)
    composition = getattr(answered, "composition", None)
    reading = getattr(answered, "reading", None)
    invariants = getattr(answered, "invariants", None)
    written = getattr(answered, "written", None)

    datasets = list(getattr(composition, "datasets", None)
                    or getattr(build, "datasets", None)
                    or ([getattr(build, "dataset", "")]
                        if getattr(build, "dataset", "") else []))

    plan = {}
    try:
        plan = dict((getattr(build, "plan", None) or {}).get("meta") or {})
    except Exception:  # noqa: BLE001 - a plan we cannot read is an empty plan
        plan = {}

    outcome = "answered"
    if getattr(answered, "clarification", ""):
        outcome = "clarification"
    elif getattr(answered, "unsupported", ""):
        outcome = "unsupported"
    elif getattr(answered, "failure", ""):
        outcome = "failed"

    return Observation(
        tenant=tenant, user_id=str(user_id or ""), project_id=str(project_id),
        investigation_id=str(investigation_id), message_id=str(message_id),
        answer_id=str(answer_id), turn_index=turn_index, question=question,
        reading=_reading_of(reading),
        officer_level=getattr(getattr(officer, "selection", None), "level",
                              None),
        officer_title=str(getattr(getattr(officer, "selection", None), "title",
                                  "") or ""),
        agents=[str(a) for a in (getattr(officer, "specialists", None) or [])],
        datasets=[str(d) for d in datasets],
        plan=plan,
        plan_fingerprint=str(plan.get("fingerprint") or ""),
        result={"rows": int(getattr(runtime, "row_count", 0) or 0),
                "columns": len(getattr(runtime, "columns", None) or [])},
        validation={"checks": len(getattr(invariants, "checks", None) or []),
                    "failures": len(getattr(invariants, "failures", None)
                                    or []),
                    "ok": bool(getattr(invariants, "ok", False))
                    if invariants is not None else None},
        interpretation=str(getattr(written, "headline", "") or ""),
        assurance=dict(getattr(answered, "assurance", None) or {}),
        outcome=outcome, latency_ms=latency_ms,
        build_sha=_build_sha(),
    )


def _reading_of(reading: Any) -> dict[str, Any]:
    if reading is None:
        return {}
    try:
        return {
            "intent": str(getattr(reading, "intent", "") or ""),
            "concepts": [str(c) for c in
                         (getattr(reading, "concepts", None) or [])],
            "grain": str(getattr(reading, "grain", "") or ""),
            "periods": [str(p) for p in
                        (getattr(reading, "periods", None) or [])],
            "operation": str(getattr(reading, "operation", "") or ""),
        }
    except Exception:  # noqa: BLE001
        return {}


def _build_sha() -> str:
    """The build this observation was made under.

    `.sha`, not `.git_sha`. The latter has never existed on `build_info`, and
    reading it left every Assurance record and every feedback item with no
    build against them — a defect this phase's predecessor found and fixed,
    and one worth not re-introducing here.
    """
    try:
        from backend.build_info import build_info

        return str(getattr(build_info(), "sha", "") or "")
    except Exception:  # noqa: BLE001
        return ""


def label(observation: Observation, event: Any) -> Observation:
    """Attach a feedback event to the observation it is about.

    Mutates the observation's LABEL and nothing else. The observation records
    what CreditProbe did; the feedback records what a user thought; joining
    them must not let either rewrite the other.
    """
    rating = str(getattr(event, "rating", "") or "")
    observation.feedback_event_id = str(getattr(event, "event_id", "") or "")
    observation.rating = rating
    observation.label = DECLINED if rating == "SKIP" else LABELED
    return observation


__all__ = ["ACCURACY_MEASUREMENT", "DECLINED", "DRIFT", "DUPLICATES",
           "FORBIDDEN_UNLABELED_USES", "LABELED", "LABELS", "LABEL_MEANS",
           "OBSERVATION_VERSION", "Observation", "RELEASE_EVIDENCE", "REPLAY",
           "TEACHING_TRUTH", "TEST_CANDIDATES", "UNCERTAINTY", "UNLABELED",
           "UNLABELED_USES", "label", "observe"]
