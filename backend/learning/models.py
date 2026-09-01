"""
Local auxiliary models: what may be trained, and what may not. §20, §21.

The boundary this module holds
--------------------------------
    "Do not train a local generative credit-risk model from raw client
     conversations in this phase."

Every task here is a CLASSIFIER or a RANKER over structured features. None of
them writes prose, none of them produces a number a credit officer would act
on, and none of them replaces a governed calculation. What they do is choose
between options CreditProbe already has — which capability, which officer,
which specialists, which of the retrieved cases is actually relevant.

That is not a small thing. Officer selection currently runs on a hand-tuned
score with floors and a ceiling, and it is right most of the time; a model
trained on approved cases could be right more often. But it can only ever
CHOOSE, and if it is unavailable or worse than the deterministic baseline the
deterministic baseline is what runs.

Never activated automatically
-------------------------------
§20: "no automatic activation; comparison against deterministic/model
baseline; activate only if critical safety is unchanged and measured
performance improves." A model that beats the baseline on average and loses on
the safety cases is not an improvement, so those are checked separately and
the safety check is not a metric to trade against accuracy.

What is not in an artifact
----------------------------
No secrets, no raw client rows, no unredacted conversation text. `scan`
checks, and `Artifact.sealed` is False until it has.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

MODEL_VERSION = "1.0.0"

# ---------------------------------------------------------------------------
# §20's nine candidate tasks
# ---------------------------------------------------------------------------

#: task -> (what it decides, what the deterministic baseline is)
TASKS: dict[str, tuple[str, str]] = {
    "capability_classification": (
        "Which high-level capability a question needs.",
        "the keyword and ontology router"),
    "conversation_action": (
        "Whether this turn is a new request, a modification, a reuse or a "
        "clarification.",
        "the discourse rules"),
    "officer_level": (
        "Which officer level the work belongs to.",
        "the weighted score with its floor and ceiling"),
    "agent_selection": (
        "Which specialists are needed.",
        "the concept-to-agent registry"),
    "period_parsing": (
        "Which reporting period or window a phrase means.",
        "the period vocabulary"),
    "entity_type": (
        "Whether a named thing is a borrower, a sector, a product or a "
        "period.",
        "the governed dimension values"),
    "retrieval_rerank": (
        "Which of the retrieved teaching cases are actually relevant.",
        "the hybrid retrieval score"),
    "duplicate_detection": (
        "Whether two questions are the same question.",
        "the normalised-key match"),
    "feedback_error_class": (
        "Which part of the pipeline a piece of feedback is about.",
        "the category-to-class map"),
}

TASK_NAMES: tuple[str, ...] = tuple(TASKS)

#: What may never be trained here, and why. Named so a refusal explains
#: itself rather than reading as an arbitrary limit.
FORBIDDEN_TASKS: dict[str, str] = {
    "answer_generation": (
        "a local model writing credit answers is a generative credit-risk "
        "model trained on client conversations, which §20 excludes from this "
        "phase"),
    "interpretation": (
        "what an answer says about its own figures is governed "
        "interpretation, not a classification"),
    "risk_rating": (
        "a model that outputs a credit rating is a rating model and belongs "
        "in model risk management, not here"),
    "pd_estimation": ("the same, for probability of default"),
    "ecl_calculation": (
        "expected credit loss is a governed deterministic calculation and "
        "will not be approximated"),
    "threshold_setting": (
        "where a threshold sits is a policy decision with an owner"),
}

# ---------------------------------------------------------------------------
# Training runs
# ---------------------------------------------------------------------------

QUEUED = "QUEUED"
RUNNING = "RUNNING"
TRAINED = "TRAINED"
EVALUATED = "EVALUATED"
APPROVED = "APPROVED"
ACTIVE = "ACTIVE"
REJECTED = "REJECTED"
FAILED = "FAILED"
ROLLED_BACK = "ROLLED_BACK"

RUN_STATUSES: tuple[str, ...] = (QUEUED, RUNNING, TRAINED, EVALUATED,
                                 APPROVED, ACTIVE, REJECTED, FAILED,
                                 ROLLED_BACK)


class ModelError(Exception):
    """A training run or an activation that must not happen."""


#: What must never appear in an artifact.
_SECRETS = re.compile(
    r"(sk-ant-[A-Za-z0-9_\-]{8,}|sk-[A-Za-z0-9]{20,}|"
    r"Bearer\s+[A-Za-z0-9._\-]{16,}|"
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----|"
    r"password\s*[:=]|api[_-]?key\s*[:=])", re.IGNORECASE)

#: Column names that would mean raw client rows travelled into the artifact.
_CLIENT_COLUMNS = frozenset({
    "customer_id", "borrower_id", "account_id", "borrower_name",
    "customer_name", "national_id", "iban", "cr_number"})


def scan(payload: Any) -> list[str]:
    """Everything in an artifact that must not be there.

    Runs over the serialised artifact rather than over the object, because the
    thing that gets written to disk is the thing that matters and a field
    somebody added last week is in it whether or not this function knows the
    field's name.
    """
    body = json.dumps(payload, sort_keys=True, default=str)
    problems: list[str] = []
    if _SECRETS.search(body):
        problems.append("the artifact contains something that looks like a "
                        "credential")
    lowered = body.lower()
    found = sorted(c for c in _CLIENT_COLUMNS if f'"{c}"' in lowered)
    if found:
        problems.append(
            "the artifact carries client identifiers: " + ", ".join(found)
            + ". Features are structural; a borrower id in a model artifact "
            "is raw client data that has left its tenant.")
    return problems


@dataclass
class Split:
    """Train, validation and holdout, split BY FAMILY. §20.

    By family and not at random. A random split puts three variants of the
    same question in train and the fourth in holdout, and the model scores
    beautifully by having memorised the family — which is exactly the leak
    the holdout exists to detect.
    """

    train: list[str] = field(default_factory=list)
    validation: list[str] = field(default_factory=list)
    holdout: list[str] = field(default_factory=list)
    by: str = "family"

    @property
    def leakage(self) -> list[str]:
        """Any case that is in more than one side of the split."""
        seen: dict[str, int] = {}
        for name in (*self.train, *self.validation, *self.holdout):
            seen[name] = seen.get(name, 0) + 1
        return sorted(k for k, v in seen.items() if v > 1)

    def to_dict(self) -> dict[str, Any]:
        return {"train": len(self.train), "validation": len(self.validation),
                "holdout": len(self.holdout), "by": self.by,
                "leakage": self.leakage}


@dataclass
class TrainingRun:
    """§21's record. Everything needed to reproduce the artifact."""

    training_run_id: str = field(
        default_factory=lambda: f"tr-{uuid.uuid4().hex[:12]}")
    task: str = ""
    tenant: str = ""
    dataset_release_id: str = ""
    case_counts: dict[str, int] = field(default_factory=dict)
    feature_schema: list[str] = field(default_factory=list)
    algorithm: str = ""
    hyperparameters: dict[str, Any] = field(default_factory=dict)
    seed: int = 0
    build_sha: str = ""
    split: Split = field(default_factory=Split)
    metrics: dict[str, float] = field(default_factory=dict)
    baseline_metrics: dict[str, float] = field(default_factory=dict)
    #: How the model did on the cases that must never regress.
    critical_result: dict[str, Any] = field(default_factory=dict)
    artifact_hash: str = ""
    status: str = QUEUED
    approver: str = ""
    activated: bool = False
    failure: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    schema_version: str = MODEL_VERSION

    @property
    def beats_baseline(self) -> tuple[bool, str]:
        """Whether this model is measurably better than the deterministic one.

        Every metric the baseline reports has to be at least as good, and at
        least one has to be better. An average that improves while a component
        gets worse is not an improvement — it is a trade nobody agreed to.
        """
        if not self.metrics or not self.baseline_metrics:
            return False, ("no comparison against the deterministic baseline "
                           "was measured")
        worse = [k for k, v in self.baseline_metrics.items()
                 if self.metrics.get(k, float("-inf")) < v]
        if worse:
            return False, ("worse than the deterministic baseline on: "
                           + ", ".join(sorted(worse)))
        better = [k for k, v in self.baseline_metrics.items()
                  if self.metrics.get(k, v) > v]
        if not better:
            return False, ("no better than the deterministic baseline on any "
                           "metric, so there is nothing to activate it for")
        return True, "better on: " + ", ".join(sorted(better))

    @property
    def critical_unchanged(self) -> tuple[bool, str]:
        failures = list(self.critical_result.get("failures") or [])
        if "failures" not in self.critical_result:
            return False, ("the critical cases were not run, and a check that "
                           "did not run is not a check that passed")
        if failures:
            return False, (f"{len(failures)} critical case(s) fail on this "
                           "model: " + ", ".join(map(str, failures[:5])))
        return True, "no critical case regresses"

    def to_dict(self) -> dict[str, Any]:
        beats, why = self.beats_baseline
        safe, safety = self.critical_unchanged
        return {
            "training_run_id": self.training_run_id, "task": self.task,
            "task_means": TASKS.get(self.task, ("", ""))[0],
            "baseline": TASKS.get(self.task, ("", ""))[1],
            "tenant": self.tenant,
            "dataset_release_id": self.dataset_release_id,
            "case_counts": dict(self.case_counts),
            "feature_schema": list(self.feature_schema),
            "algorithm": self.algorithm,
            "hyperparameters": dict(self.hyperparameters),
            "seed": self.seed, "build_sha": self.build_sha,
            "split": self.split.to_dict(),
            "metrics": dict(self.metrics),
            "baseline_metrics": dict(self.baseline_metrics),
            "beats_baseline": beats, "beats_baseline_because": why,
            "critical_result": dict(self.critical_result),
            "critical_unchanged": safe, "critical_because": safety,
            "artifact_hash": self.artifact_hash, "status": self.status,
            "approver": self.approver, "activated": self.activated,
            "failure": self.failure,
            "created_at": self.created_at.isoformat(),
            "schema_version": self.schema_version,
        }


def start(task: str, *, tenant: str = "", seed: int = 0,
          algorithm: str = "", dataset_release_id: str = "") -> TrainingRun:
    """Open a training run, or refuse the task and say why."""
    if task in FORBIDDEN_TASKS:
        raise ModelError(f"{task!r} will not be trained here: "
                         + FORBIDDEN_TASKS[task])
    if task not in TASKS:
        raise ModelError(
            f"{task!r} is not a local auxiliary task. The set is closed: "
            + ", ".join(TASK_NAMES))
    return TrainingRun(task=task, tenant=tenant, seed=seed,
                       algorithm=algorithm,
                       dataset_release_id=dataset_release_id,
                       status=QUEUED)


def seal(run: TrainingRun, artifact: dict[str, Any]) -> str:
    """Hash an artifact after checking what is in it. §21.

    Refuses rather than redacts. A credential or a client identifier in an
    artifact means the training set carried it, and quietly stripping the
    artifact leaves the training set — and the next artifact — exactly as
    wrong.
    """
    problems = scan(artifact)
    if problems:
        run.status = FAILED
        run.failure = "; ".join(problems)
        raise ModelError("; ".join(problems))
    body = json.dumps(artifact, sort_keys=True, separators=(",", ":"),
                      default=str)
    run.artifact_hash = hashlib.sha256(body.encode()).hexdigest()
    run.status = TRAINED
    return run.artifact_hash


def activate(run: TrainingRun, *, approver: str) -> TrainingRun:
    """Put a trained model into the routing path. §20.

    Four refusals, and the order is the argument: unevaluated before
    unapproved, safety before accuracy, and a model that is merely
    not-worse before one that is better.
    """
    if run.status not in (EVALUATED, TRAINED, ROLLED_BACK):
        raise ModelError(f"a {run.status} run cannot be activated")
    if not str(approver).strip():
        raise ModelError("activating a local model needs a named approver")
    if not run.artifact_hash:
        raise ModelError("the artifact has not been sealed, so what would be "
                         "activated is not recorded")
    if run.split.leakage:
        raise ModelError(
            f"{len(run.split.leakage)} case(s) appear on more than one side "
            "of the split, so the holdout score is not a holdout score")

    safe, safety = run.critical_unchanged
    if not safe:
        raise ModelError(safety)
    beats, why = run.beats_baseline
    if not beats:
        raise ModelError(
            why + ". A local model that does not beat the deterministic "
            "baseline is a dependency with no benefit, and the baseline "
            "stays.")

    run.status = ACTIVE
    run.activated = True
    run.approver = approver.strip()
    return run


def rollback(run: TrainingRun, *, why: str) -> TrainingRun:
    """Take a model back out of the routing path."""
    if not str(why).strip():
        raise ModelError("a rollback needs a reason")
    run.status = ROLLED_BACK
    run.activated = False
    run.failure = why.strip()
    return run


__all__ = ["ACTIVE", "APPROVED", "EVALUATED", "FAILED", "FORBIDDEN_TASKS",
           "MODEL_VERSION", "ModelError", "QUEUED", "REJECTED",
           "ROLLED_BACK", "RUNNING", "RUN_STATUSES", "Split", "TASKS",
           "TASK_NAMES", "TRAINED", "TrainingRun", "activate", "rollback",
           "scan", "seal", "start"]
