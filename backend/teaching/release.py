"""
The Teaching Release, and the gate production reads it through. §43, §44.

Why a release rather than a live table
---------------------------------------
Everything else in this package answers "what may be retrieved right now". A
release answers a different question: "what was retrievable when this answer
was produced". Those come apart the moment somebody approves a case, and the
gap between them is where an unexplainable answer lives — a Trace that names
five teaching cases, two of which have since been edited, and nothing that can
reconstruct what the planner actually saw.

So a release is FROZEN. It is built from the library at a moment, given an id,
and never edited. A change to the library produces a new release; it does not
change an old one.

The gate is three sentences, and each is a different situation
--------------------------------------------------------------
§44 names them and they are not interchangeable:

``TEACHING RELEASE UNAVAILABLE`` — production is configured to use a release
    and there is not one. Retrieval returns nothing rather than falling back
    to the live library, because "the approved cases" and "whatever happens to
    be approved" are different things and only one of them was reviewed.

``STALE`` — a release exists but the world moved: the code, the ontology, the
    prompts, the routing policy or the cases themselves. The release is not
    wrong, it is describing a product that no longer exists.

``UNRELEASED TEACHING LIBRARY`` — development, running straight off the live
    library. Explicitly allowed by §44 and explicitly labelled, because the
    thing that makes it safe is that everybody can see it.

The fourth state is `APPROVED`, and it is the only one production serves from.

Nothing here writes to the library
-----------------------------------
A release reads. It cannot approve a case, change a status or edit a case's
content — those all belong to `teaching_library`, in front of a reviewer.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.teaching import families as fam
from backend.teaching import schema as sc
from backend.teaching import status as st

RELEASE_VERSION = "1.0.0"

#: Where a frozen release lands. One directory per release id, so an old one
#: is still readable after a new one is cut.
RELEASE_DIR = Path("teaching_release")

#: §44's four states.
APPROVED = "APPROVED"
STALE = "STALE"
UNAVAILABLE = "TEACHING RELEASE UNAVAILABLE"
UNRELEASED = "UNRELEASED TEACHING LIBRARY"

STATES: tuple[str, ...] = (APPROVED, STALE, UNAVAILABLE, UNRELEASED)

#: §43's file list. Held as data so a release that is missing one is a
#: detectable fact rather than a surprise at read time.
FILES: tuple[str, ...] = (
    "manifest.json",
    "approved_cases.jsonl",
    "case_families.json",
    "retrieval_policy.json",
    "planner_prompt.txt",
    "complex_planner_prompt.txt",
    "critic_prompt.txt",
    "interpretation_prompt.txt",
    "routing_policy.json",
    "thresholds.json",
    "ontology_fingerprint.json",
    "method_fingerprint.json",
    "evaluation_report.json",
    "holdout_manifest.json",
    "approval_record.json",
)

#: The axes a release goes STALE on. The same list §5 uses for a case, plus
#: the two that are properties of the release rather than of any case in it.
STALENESS_AXES: tuple[str, ...] = (*st.STALENESS_AXES, "git_sha",
                                   "retrieval_version", "routing_policy")


@dataclass
class Manifest:
    """§43's manifest, field for field."""

    release_id: str = ""
    git_sha: str = ""
    created_at: str = ""
    #: DRAFT until a person signs it. §44: production uses only an APPROVED
    #: release, and a release that certified itself is not one.
    certification_status: str = "DRAFT"
    reviewers: list[str] = field(default_factory=list)

    case_counts_by_status: dict[str, int] = field(default_factory=dict)
    case_counts_by_family: dict[str, int] = field(default_factory=dict)

    prompt_versions: dict[str, str] = field(default_factory=dict)
    routing_policy: dict[str, Any] = field(default_factory=dict)
    model_role_names: list[str] = field(default_factory=list)

    ontology_version: str = ""
    method_version: str = ""
    relationship_version: str = ""
    retrieval_version: str = ""

    evaluation_metrics: dict[str, Any] = field(default_factory=dict)
    critical_failures: list[str] = field(default_factory=list)
    confidence_bounds: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: Any) -> Manifest:
        raw = dict(raw) if isinstance(raw, dict) else {}
        from dataclasses import fields as dataclass_fields

        allowed = {f.name for f in dataclass_fields(cls)}
        return cls(**{k: v for k, v in raw.items() if k in allowed})

    def versions(self) -> dict[str, str]:
        """What this release was cut against, by staleness axis."""
        return {
            st.ONTOLOGY: self.ontology_version,
            st.METHOD: self.method_version,
            st.RELATIONSHIP: self.relationship_version,
            "retrieval_version": self.retrieval_version,
            "git_sha": self.git_sha,
            "routing_policy": _fingerprint(self.routing_policy),
        }


def _fingerprint(payload: Any) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def release_id(*, git_sha: str = "", at: str = "") -> str:
    """A readable, sortable id. Date first, so a directory listing is a
    history."""
    stamp = (at or _now())[:19].replace(":", "").replace("-", "")
    short = (git_sha or "nogit")[:8]
    return f"tr-{stamp}-{short}"


# ---------------------------------------------------------------- building

def build(cases: list[sc.TeachingCase], *, git_sha: str = "",
          prompts: dict[str, str] | None = None,
          routing_policy: dict[str, Any] | None = None,
          thresholds: dict[str, Any] | None = None,
          evaluation: dict[str, Any] | None = None,
          holdout_manifest: dict[str, Any] | None = None,
          retrieval_policy: dict[str, Any] | None = None,
          model_roles: list[str] | None = None,
          critical_failures: list[str] | None = None,
          confidence_bounds: dict[str, Any] | None = None) -> dict[str, Any]:
    """A release, as the files §43 lists.

    Takes cases rather than a session, so a release can be built and inspected
    without a database — and so this module cannot reach the library's write
    side even by accident.

    Only APPROVED cases go in. A release containing drafts is a release whose
    review means nothing, and §44's "do not silently use unapproved draft
    cases" is exactly this filter.
    """
    approved = [c for c in cases if c.review_status == st.APPROVED
                and c.data_sensitivity == st.PUBLIC]

    by_status: dict[str, int] = {}
    by_family: dict[str, int] = {}
    for case in cases:
        by_status[case.review_status] = by_status.get(case.review_status, 0) + 1
    for case in approved:
        by_family[case.family_id] = by_family.get(case.family_id, 0) + 1

    prompts = dict(prompts or {})
    ontology = next((c.ontology_version for c in approved
                     if c.ontology_version), "")

    manifest = Manifest(
        release_id=release_id(git_sha=git_sha),
        git_sha=git_sha,
        created_at=_now(),
        certification_status="DRAFT",
        case_counts_by_status=by_status,
        case_counts_by_family=by_family,
        prompt_versions={name: _fingerprint(text)
                         for name, text in prompts.items()},
        routing_policy=dict(routing_policy or {}),
        model_role_names=list(model_roles or []),
        ontology_version=ontology,
        method_version=next((c.method_version for c in approved
                             if c.method_version), ""),
        relationship_version=next((c.relationship_version for c in approved
                                   if c.relationship_version), ""),
        retrieval_version=RELEASE_VERSION,
        evaluation_metrics=dict(evaluation or {}),
        critical_failures=list(critical_failures or []),
        confidence_bounds=dict(confidence_bounds or {}),
    )

    return {
        "manifest.json": manifest.to_dict(),
        "approved_cases.jsonl": [c.to_dict() for c in approved],
        "case_families.json": [
            {"id": f.id, "label": f.label, "group": f.group,
             "teaches": f.teaches, "available": f.available,
             "gated_on": f.gated_on} for f in fam.FAMILIES],
        "retrieval_policy.json": dict(retrieval_policy or {}),
        "planner_prompt.txt": prompts.get("planner", ""),
        "complex_planner_prompt.txt": prompts.get("complex_planner", ""),
        "critic_prompt.txt": prompts.get("critic", ""),
        "interpretation_prompt.txt": prompts.get("interpretation", ""),
        "routing_policy.json": dict(routing_policy or {}),
        "thresholds.json": dict(thresholds or {}),
        "ontology_fingerprint.json": {"version": ontology},
        "method_fingerprint.json": {"version": manifest.method_version},
        "evaluation_report.json": dict(evaluation or {}),
        # The holdout MANIFEST — counts and coverage, never a question and
        # never an answer. §41: the retrieval service cannot access holdout
        # cases or labels, and a release that carried them would hand them to
        # everything downstream at once.
        "holdout_manifest.json": _safe_holdout(holdout_manifest),
        "approval_record.json": {"status": "DRAFT", "reviewers": [],
                                 "approved_at": ""},
    }


#: Keys a holdout manifest may contain. A whitelist, because the failure mode
#: is somebody adding "examples" to the manifest for debugging and shipping the
#: sealed set inside every release.
_HOLDOUT_KEYS: frozenset[str] = frozenset({
    "case_count", "families", "counts_by_family", "version", "fingerprint",
    "sealed_at", "coverage",
})


def _safe_holdout(raw: Any) -> dict[str, Any]:
    given = dict(raw or {})
    return {k: v for k, v in given.items() if k in _HOLDOUT_KEYS}


def freeze(payload: dict[str, Any], *,
           directory: Path = RELEASE_DIR) -> Path:
    """Write a release to disk, once.

    Refuses to overwrite. A release that can be rewritten is not frozen, and
    every Trace that names it becomes unverifiable the moment it is.
    """
    manifest = Manifest.from_dict(payload.get("manifest.json"))
    target = Path(directory) / (manifest.release_id or release_id())
    if target.exists():
        raise FileExistsError(f"{target} already exists; a release is frozen "
                              "and a change makes a new one")
    target.mkdir(parents=True)

    for name in FILES:
        body = payload.get(name)
        path = target / name
        if name.endswith(".jsonl"):
            path.write_text("\n".join(json.dumps(row, sort_keys=True,
                                                 default=str)
                                      for row in (body or [])),
                            encoding="utf-8")
        elif name.endswith(".txt"):
            path.write_text(str(body or ""), encoding="utf-8")
        else:
            path.write_text(json.dumps(body if body is not None else {},
                                       indent=1, sort_keys=True, default=str),
                            encoding="utf-8")
    return target


def load(path: Path) -> tuple[Manifest, list[sc.TeachingCase], list[str]]:
    """A frozen release, back. Returns the manifest, its cases, and what is
    missing."""
    path = Path(path)
    missing = [name for name in FILES if not (path / name).exists()]

    manifest = Manifest()
    manifest_path = path / "manifest.json"
    if manifest_path.exists():
        manifest = Manifest.from_dict(json.loads(
            manifest_path.read_text(encoding="utf-8") or "{}"))

    cases: list[sc.TeachingCase] = []
    cases_path = path / "approved_cases.jsonl"
    if cases_path.exists():
        for line in cases_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                cases.append(sc.TeachingCase.from_dict(json.loads(line)))
    return manifest, cases, missing


def latest(directory: Path = RELEASE_DIR) -> Path | None:
    """The newest release on disk, by id — which sorts by date."""
    root = Path(directory)
    if not root.is_dir():
        return None
    found = sorted((p for p in root.iterdir()
                    if p.is_dir() and (p / "manifest.json").exists()),
                   key=lambda p: p.name)
    return found[-1] if found else None


def approve(path: Path, *, reviewers: list[str], note: str = "") -> Manifest:
    """A person signs a release. §44: production uses only an approved one.

    Requires named reviewers for the same reason a case does: an approval with
    nobody behind it is a click, and every answer served from the release
    inherits it.
    """
    path = Path(path)
    if not reviewers or not all(str(r).strip() for r in reviewers):
        raise ValueError("a release approval needs named reviewers")

    manifest_path = path / "manifest.json"
    manifest = Manifest.from_dict(json.loads(
        manifest_path.read_text(encoding="utf-8") or "{}"))
    manifest.certification_status = APPROVED
    manifest.reviewers = [str(r).strip() for r in reviewers]
    manifest_path.write_text(json.dumps(manifest.to_dict(), indent=1,
                                        sort_keys=True, default=str),
                             encoding="utf-8")
    (path / "approval_record.json").write_text(
        json.dumps({"status": APPROVED, "reviewers": manifest.reviewers,
                    "approved_at": _now(), "note": note},
                   indent=1, sort_keys=True), encoding="utf-8")
    return manifest


# -------------------------------------------------------------- §44 the gate

@dataclass(frozen=True)
class Gate:
    """What production may use, and what it must say about it."""

    state: str
    release_id: str = ""
    #: Why it is not APPROVED, when it is not.
    reason: str = ""
    #: The axes a stale release moved on.
    moved: tuple[str, ...] = ()

    @property
    def usable(self) -> bool:
        """Whether teaching cases may be retrieved at all.

        UNRELEASED is usable — §44 allows development to run off the live
        library provided it is labelled. STALE and UNAVAILABLE are not: a
        release describing a product that no longer exists is worse than no
        release, because it looks like one.
        """
        return self.state in (APPROVED, UNRELEASED)

    @property
    def label(self) -> str:
        return self.state

    def to_dict(self) -> dict[str, Any]:
        return {"state": self.state, "label": self.label,
                "release_id": self.release_id, "reason": self.reason,
                "moved": list(self.moved), "usable": self.usable}


def gate(*, require_release: bool, directory: Path = RELEASE_DIR,
         current: dict[str, str] | None = None) -> Gate:
    """§44, as one decision.

    `require_release` is the production switch. Off, the answer is UNRELEASED
    and the label travels with every answer — which is what makes running off
    the live library acceptable in development and not in production.
    """
    if not require_release:
        return Gate(UNRELEASED,
                    reason="Running off the live teaching library. Cases are "
                           "whatever is approved right now, not a frozen "
                           "reviewed set.")

    path = latest(directory)
    if path is None:
        return Gate(UNAVAILABLE,
                    reason="Production is configured to use an approved "
                           "Teaching Release and none is present.")

    manifest, _, missing = load(path)
    if missing:
        return Gate(UNAVAILABLE, release_id=manifest.release_id,
                    reason=f"The release is incomplete: {', '.join(missing)}.")
    if manifest.certification_status != APPROVED:
        return Gate(UNAVAILABLE, release_id=manifest.release_id,
                    reason="The release has not been approved. §44 forbids "
                           "silently using unapproved cases.")

    moved = stale_axes(manifest, current or {})
    if moved:
        return Gate(STALE, release_id=manifest.release_id, moved=moved,
                    reason="The release describes a product that has since "
                           f"changed: {', '.join(moved)}.")

    return Gate(APPROVED, release_id=manifest.release_id)


def stale_axes(manifest: Manifest,
               current: dict[str, str]) -> tuple[str, ...]:
    """Which of §44's axes have moved under a release.

    An axis the caller does not version is skipped; an axis the RELEASE never
    recorded is stale. Same asymmetry as a case's staleness, and for the same
    reason: a blank is not evidence of agreement.
    """
    recorded = manifest.versions()
    moved: list[str] = []
    for axis in STALENESS_AXES:
        now = str(current.get(axis) or "").strip()
        if not now:
            continue
        if str(recorded.get(axis) or "").strip() != now:
            moved.append(axis)
    return tuple(moved)


__all__ = ["APPROVED", "FILES", "Gate", "Manifest", "RELEASE_DIR",
           "RELEASE_VERSION", "STALE", "STALENESS_AXES", "STATES",
           "UNAVAILABLE", "UNRELEASED", "approve", "build", "freeze", "gate",
           "latest", "load", "release_id", "stale_axes"]
