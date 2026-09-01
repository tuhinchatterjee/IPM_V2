"""
Which Intelligence Release this build is certified against, if any.

Why the product reads this and not the factory
-----------------------------------------------
`intelligence_factory` holds the sealed holdout, and nothing under `backend/`
may import it — an isolation test asserts exactly that, because a product that
can reach its own exam has no exam. What the product reads instead is the
*manifest*: a JSON file written by a certification run, containing the versions
that were measured and the rates that came out. Facts about a completed run,
with no case in it.

UNCERTIFIED is a state, not an error
-------------------------------------
A local development image has no manifest and should not pretend otherwise. It
reports UNCERTIFIED and says so on the build endpoint, which is what a developer
needs to see. A release image without one is a build mistake, and the Docker
release gate refuses it — but that refusal belongs in the build, not here.

Never fails
-----------
A missing, unreadable or malformed manifest degrades to UNCERTIFIED. A build
endpoint that raises because a JSON file was truncated would take out the one
page somebody consults to find out what is wrong.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: Where the frozen release is copied to in the image. Overridable so a
#: developer can point at a manifest they just produced.
MANIFEST_PATH = Path(os.environ.get(
    "INTELLIGENCE_RELEASE_PATH", "intelligence_release/manifest.json"))

UNCERTIFIED = "UNCERTIFIED"
CERTIFIED = "CERTIFIED"
NOT_PASSED = "NOT_PASSED"
STALE = "STALE"


@dataclass(frozen=True)
class Release:
    """What a certification run measured, and whether it still applies."""

    status: str = UNCERTIFIED
    release_id: str = ""
    created_at: str = ""
    #: The build the certification actually ran against. When it differs from
    #: the build running now, the evidence is about different code.
    certified_sha: str = ""
    running_sha: str = ""
    holdout_version: str = ""
    curriculum_version: str = ""
    ontology_version: str = ""
    ontology_fingerprint: str = ""
    cases: int = 0
    critical_cases: int = 0
    #: The observed rate, and what the interval supports. Kept apart on
    #: purpose: one is what happened, the other is what may be said.
    observed_precision_pct: float = 0.0
    supported_precision_pct: float = 0.0
    reportable: bool = False
    critical_failures: list[str] = field(default_factory=list)
    corrections: list[dict[str, str]] = field(default_factory=list)
    detail: str = ""

    @property
    def certified(self) -> bool:
        return self.status == CERTIFIED

    def sentence(self) -> str:
        """One line, for a header or a build page."""
        if self.status == UNCERTIFIED:
            return ("No Intelligence Release is frozen into this build. It has "
                    "not been certified against the sealed holdout.")
        if self.status == NOT_PASSED:
            return (f"Intelligence Release {self.release_id} did not pass "
                    "certification. " + self.detail)
        if self.status == STALE:
            return (f"Intelligence Release {self.release_id} certified build "
                    f"{self.certified_sha}, but {self.running_sha} is running. "
                    "The evidence describes different code.")
        return (f"Certified as {self.release_id}: {self.observed_precision_pct:.2f}% "
                f"observed over {self.cases} sealed cases"
                + (f", supporting {self.supported_precision_pct:.2f}% at 95% "
                   "confidence." if self.reportable else
                   ", too few observations to support a rate claim."))

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status, "release_id": self.release_id,
            "created_at": self.created_at,
            "certified_sha": self.certified_sha,
            "running_sha": self.running_sha,
            "holdout_version": self.holdout_version,
            "curriculum_version": self.curriculum_version,
            "ontology_version": self.ontology_version,
            "ontology_fingerprint": self.ontology_fingerprint,
            "cases": self.cases, "critical_cases": self.critical_cases,
            "observed_precision_pct": self.observed_precision_pct,
            "supported_precision_pct": self.supported_precision_pct,
            "reportable": self.reportable,
            "critical_failures": list(self.critical_failures),
            "corrections": [dict(c) for c in self.corrections],
            "sentence": self.sentence(),
        }


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load(path: Path | None = None) -> Release:
    """The frozen release, or UNCERTIFIED. Never raises."""
    target = path or MANIFEST_PATH
    try:
        if not target.is_file():
            return Release(detail=f"No manifest at {target}.")
        return _from(_read(target))
    except Exception as e:  # noqa: BLE001 - a build page must not go down
        logger.warning("The Intelligence Release manifest could not be read: %s", e)
        return Release(detail=f"The manifest at {target} could not be read.")


def _from(payload: dict[str, Any]) -> Release:
    from backend.build_info import build_info

    certification = payload.get("certification") or {}
    evidence = payload.get("evidence") or {}
    holdout = payload.get("holdout") or {}
    failures = [str(f) for f in (certification.get("critical_failures") or [])]

    certified_sha = str(payload.get("build_sha") or "")
    running_sha = str(build_info().short_sha or "")

    if certification.get("status") != "PASSED":
        status = NOT_PASSED
    elif certified_sha and running_sha and certified_sha != running_sha:
        status = STALE
    else:
        status = CERTIFIED

    return Release(
        status=status,
        release_id=str(payload.get("release_id") or ""),
        created_at=str(payload.get("created_at") or ""),
        certified_sha=certified_sha, running_sha=running_sha,
        holdout_version=str(payload.get("holdout_version") or ""),
        curriculum_version=str(payload.get("curriculum_version") or ""),
        ontology_version=str(payload.get("ontology_version") or ""),
        ontology_fingerprint=str(payload.get("ontology_fingerprint") or ""),
        cases=int(holdout.get("cases") or 0),
        critical_cases=int(holdout.get("critical") or 0),
        observed_precision_pct=float(evidence.get("observed_precision_pct") or 0.0),
        supported_precision_pct=float(evidence.get("supported_precision_pct") or 0.0),
        reportable=bool(evidence.get("reportable")),
        critical_failures=failures,
        corrections=[dict(c) for c in (holdout.get("corrections") or [])],
        detail=str(evidence.get("sentence") or ""),
    )


@lru_cache(maxsize=1)
def release() -> Release:
    """Cached. The manifest is baked into the image and cannot change under it."""
    return load()


__all__ = ["CERTIFIED", "MANIFEST_PATH", "NOT_PASSED", "STALE", "UNCERTIFIED",
           "Release", "load", "release"]
