"""
What an Intelligence Release points at. §127.

    "Any relevant change makes the release STALE."

Why the references are a list rather than a set of fields
----------------------------------------------------------
Fourteen things, and the number will grow. Written as fields on a dataclass,
each new one needs a field, a serialiser, a comparison and a line in the
staleness check — and the line in the staleness check is the one that gets
forgotten, which means the release silently stops noticing that a thing
changed.

Written as data, adding a reference is one entry, and `stale()` iterates. A
reference nobody versions is reported as unversioned rather than as agreeing,
which is the same asymmetry a teaching case's staleness uses: a blank is not
evidence of agreement.

The difference between this and the Teaching Release
------------------------------------------------------
The Teaching Release (§43) freezes the CASES. This freezes everything the
runtime reads: the ontology, the methods, the relationship contracts, the
blueprints, the judgment policies, the taxonomy, the grammar, the prompts, the
routing, the model roles, plus the evidence — the evaluation reports, the live
verification and the approvals. A release that recorded the cases and not the
materiality policy would be a release that reproduces last week's retrieval
and this week's judgement.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

REFERENCES_VERSION = "1.0.0"

# ------------------------------------------------------- §127's fourteen
TEACHING_RELEASE = "teaching_release"
ONTOLOGY = "ontology"
METHODS = "analysis_studio_methods"
RELATIONSHIPS = "relationship_contracts"
BLUEPRINTS = "investigation_blueprints"
JUDGMENT_POLICIES = "judgment_policies"
CONTRADICTION_TAXONOMY = "contradiction_taxonomy"
VISUALIZATION_GRAMMAR = "visualization_grammar"
PROMPTS = "prompt_versions"
ROUTING_POLICY = "routing_policy"
MODEL_ROLES = "model_roles"
EVALUATION_REPORTS = "evaluation_reports"
LIVE_VERIFICATION = "live_verification"
APPROVALS = "approval_records"

REFERENCES: tuple[str, ...] = (
    TEACHING_RELEASE, ONTOLOGY, METHODS, RELATIONSHIPS, BLUEPRINTS,
    JUDGMENT_POLICIES, CONTRADICTION_TAXONOMY, VISUALIZATION_GRAMMAR,
    PROMPTS, ROUTING_POLICY, MODEL_ROLES, EVALUATION_REPORTS,
    LIVE_VERIFICATION, APPROVALS,
)

#: Why each one is referenced, in the words that would answer "does this
#: really need to invalidate a release?". Every entry here has an answer, and
#: it is always the same shape: because the runtime reads it, so a change to
#: it changes answers.
BECAUSE: dict[str, str] = {
    TEACHING_RELEASE: "Retrieval decides what the model sees before it "
                      "answers.",
    ONTOLOGY: "A concept's definition, unit or valid aggregations changing "
              "changes every figure computed from it.",
    METHODS: "A certified method changing changes the calculation.",
    RELATIONSHIPS: "A join path changing changes the population.",
    BLUEPRINTS: "A blueprint changing changes what an investigation looks "
                "at, which changes what it finds.",
    JUDGMENT_POLICIES: "Materiality, breadth and persistence policies decide "
                       "what the answer says is important.",
    CONTRADICTION_TAXONOMY: "The explanations and diagnostics decide what a "
                            "disagreement is reported as.",
    VISUALIZATION_GRAMMAR: "The roles and the mapping decide what is drawn "
                           "and what is refused.",
    PROMPTS: "A prompt is configuration that changes every answer.",
    ROUTING_POLICY: "Which model answers a question changes the answer.",
    MODEL_ROLES: "The model behind a role changing changes the answer with "
                 "nothing else changing.",
    EVALUATION_REPORTS: "The evidence the release's claims rest on.",
    LIVE_VERIFICATION: "The evidence that the configured models actually "
                       "respond.",
    APPROVALS: "Who signed it off, and for what.",
}

#: Not versioned. Reported as unversioned rather than as agreeing — a blank is
#: not evidence of agreement.
UNVERSIONED = "not versioned"


@dataclass
class Manifest:
    """§127's references, each with the version it was cut against."""

    release_id: str = ""
    created_at: str = ""
    git_sha: str = ""
    versions: dict[str, str] = field(default_factory=dict)
    approvals: list[dict[str, str]] = field(default_factory=list)

    @property
    def unversioned(self) -> list[str]:
        return [r for r in REFERENCES
                if not str(self.versions.get(r, "")).strip()]

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": REFERENCES_VERSION,
            "release_id": self.release_id, "created_at": self.created_at,
            "git_sha": self.git_sha,
            "references": [
                {"id": r, "because": BECAUSE[r],
                 "version": self.versions.get(r) or UNVERSIONED}
                for r in REFERENCES],
            "unversioned": self.unversioned,
            "approvals": [dict(a) for a in self.approvals],
            "complete": not self.unversioned,
        }


def current() -> dict[str, str]:
    """What every reference is at right now.

    Read from the modules themselves rather than from configuration, so a
    version bumped in code is noticed without anybody remembering to record
    it somewhere else — which is the failure this whole mechanism exists to
    prevent.
    """
    from backend.judgment import blueprints as bp
    from backend.judgment import contradictions as cd
    from backend.judgment import interpretation as it
    from backend.judgment import judgment_policy as jp
    from backend.judgment import materiality as mt
    from backend.judgment import visual_grammar as vg
    from backend.llm import roles as rl
    from backend.teaching import release as tr

    gate = tr.gate(require_release=False)
    return {
        TEACHING_RELEASE: gate.release_id or "",
        ONTOLOGY: _ontology_version(),
        METHODS: _method_version(),
        RELATIONSHIPS: _relationship_version(),
        BLUEPRINTS: bp.BLUEPRINT_VERSION,
        # One string covering the four policies, because they move together
        # and a release stale on one is stale.
        JUDGMENT_POLICIES: f"{jp.JUDGMENT_POLICY_VERSION}/"
                           f"{mt.MATERIALITY_VERSION}/"
                           f"{it.INTERPRETATION_VERSION}",
        CONTRADICTION_TAXONOMY: cd.CONTRADICTION_VERSION,
        VISUALIZATION_GRAMMAR: vg.GRAMMAR_VERSION,
        PROMPTS: "",
        ROUTING_POLICY: _routing_fingerprint(),
        MODEL_ROLES: ",".join(sorted(rl.ACTIVE_ROLES)),
        EVALUATION_REPORTS: "",
        LIVE_VERIFICATION: "",
        APPROVALS: "",
    }


def _ontology_version() -> str:
    try:
        from backend.semantics import ontology as on

        return str(getattr(on, "ONTOLOGY_VERSION", "") or "")
    except Exception:  # pragma: no cover - ontology moved
        return ""


def _method_version() -> str:
    try:
        from backend.studio import library as ml

        return str(getattr(ml, "METHOD_VERSION", "") or "")
    except Exception:  # pragma: no cover - method library moved
        return ""


def _relationship_version() -> str:
    try:
        from backend.data_access import relationships as rel

        return str(getattr(rel, "RELATIONSHIP_VERSION", "") or "")
    except Exception:  # pragma: no cover - relationships moved
        return ""


def _routing_fingerprint() -> str:
    try:
        from backend.teaching import policy as po

        return str(getattr(po.default(), "fingerprint", "") or "")
    except Exception:  # pragma: no cover - policy moved
        return ""


def stale(manifest: Manifest,
          now: dict[str, str] | None = None) -> list[dict[str, str]]:
    """Which of §127's references have moved under a release.

    A reference the release never recorded is STALE, not agreed. A reference
    the caller cannot version today is skipped — we know nothing about it, and
    reporting "changed" from ignorance would make the whole check noise.
    """
    now = now if now is not None else current()
    moved: list[dict[str, str]] = []
    for reference in REFERENCES:
        live = str(now.get(reference, "")).strip()
        if not live:
            continue
        recorded = str(manifest.versions.get(reference, "")).strip()
        if not recorded:
            moved.append({"reference": reference, "was": UNVERSIONED,
                          "now": live, "because": BECAUSE[reference]})
        elif recorded != live:
            moved.append({"reference": reference, "was": recorded,
                          "now": live, "because": BECAUSE[reference]})
    return moved


def build(release_id: str, *, git_sha: str = "", created_at: str = "",
          approvals: list[dict[str, str]] | None = None) -> Manifest:
    """A manifest recording what everything is at right now."""
    return Manifest(release_id=release_id, created_at=created_at,
                    git_sha=git_sha, versions=current(),
                    approvals=list(approvals or []))


__all__ = ["APPROVALS", "BECAUSE", "BLUEPRINTS", "CONTRADICTION_TAXONOMY",
           "EVALUATION_REPORTS", "JUDGMENT_POLICIES", "LIVE_VERIFICATION",
           "METHODS", "MODEL_ROLES", "Manifest", "ONTOLOGY", "PROMPTS",
           "REFERENCES", "REFERENCES_VERSION", "RELATIONSHIPS",
           "ROUTING_POLICY", "TEACHING_RELEASE", "UNVERSIONED", "build",
           "current", "stale"]
