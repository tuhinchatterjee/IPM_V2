"""Learning Bundles and the Developer Intelligence Bundle. §15.

Three packages leave this installation and they are not the same thing.

A **Brain Pack** is the whole intelligence layer: ontology, teaching,
blueprints, judgment policy, prompts, routing, methods, regulatory rules. It
is what you send when another installation should think the way this one
does.

A **Learning Bundle** is the delta. What this installation learned since a
named baseline, and nothing else. It is small, it is reviewable in an
afternoon, and it is what you send when the receiver already has a Brain and
should get the improvement rather than a replacement.

A **Developer Intelligence Bundle** (§15) goes somewhere else entirely: into
a development session, to be read by a person or by Claude Code. It carries
the approved assets and an explicit README saying what may not be trusted
without evaluation. That last part is the point of the format. A bundle that
arrives in a repository looks like ground truth, and almost none of it is:
the teaching cases are approved answers to questions asked HERE, against the
datasets governed HERE, and a receiver that treats them as facts about their
own portfolio has imported a confident stranger's opinion.

Everything in this module builds `pack.Contents`. It never writes bytes
itself, so every export goes through `pack.write()` and therefore through
the same secret scan, client-data scan, sealed-content check and path check
as an import. An installation cannot produce a package it would refuse.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from backend.brain import ledger as ledger_mod
from backend.brain import pack, status

logger = logging.getLogger(__name__)

BUNDLE_SCHEMA_VERSION = "1.0.0"

#: The one status that may leave this installation inside any package.
#: §2: generated, migrated and Claude-authored cases are not human reviewed,
#: and a receiver reading a case labelled "approved" is entitled to assume a
#: person read it here. SYSTEM_VALIDATED stays home: it is a legitimate
#: retrieval status under an explicit local policy, but that policy is the
#: sender's, and shipping it would export the policy along with the case.
EXPORTABLE_CASE_STATUS = status.HUMAN_APPROVED


class BundleError(Exception):
    """An export that may not be built, and why."""


# ------------------------------------------------------------------ source


@dataclass
class Source:
    """What this installation is willing to export, already filtered.

    A dataclass rather than a live query on purpose: an export is a snapshot
    of a decision, and the decision about what is exportable is made once,
    visibly, by `collect()` — not scattered through the writer where a later
    edit could quietly widen it.
    """

    #: Approved teaching cases, as plain dicts.
    teaching_cases: list[dict[str, Any]] = field(default_factory=list)
    #: Governed ontology concepts and the version they belong to.
    ontology: dict[str, Any] = field(default_factory=dict)
    #: Investigation blueprints at APPROVED.
    blueprints: list[dict[str, Any]] = field(default_factory=list)
    #: The judgment policy: when to escalate, what counts as material.
    judgment_policy: dict[str, Any] = field(default_factory=dict)
    #: The visualization grammar: which chart a shape is allowed to take.
    visualization: dict[str, Any] = field(default_factory=dict)
    #: Prompt templates by role. Never the model's own reasoning.
    prompts: dict[str, Any] = field(default_factory=dict)
    #: Model-role routing policy — roles, not model identifiers.
    routing: dict[str, Any] = field(default_factory=dict)
    #: Agent and tool registry entries, without credentials.
    agents: list[dict[str, Any]] = field(default_factory=list)
    #: Regulatory requirements that reached APPROVED.
    regulatory: list[dict[str, Any]] = field(default_factory=list)
    #: Certified Analysis Studio method definitions.
    methods: list[dict[str, Any]] = field(default_factory=list)
    #: Evaluation summaries. Scores and counts, never holdout content.
    evaluations: dict[str, Any] = field(default_factory=dict)
    #: Approval records: who approved what, and when.
    approvals: list[dict[str, Any]] = field(default_factory=list)
    #: Portable ledger entries — §14 eligible, approved, PORTABLE.
    learning: list[dict[str, Any]] = field(default_factory=list)
    #: What this installation knows it does badly.
    known_limitations: tuple[str, ...] = ()

    def counts(self) -> dict[str, int]:
        return {
            "teaching_cases": len(self.teaching_cases),
            "blueprints": len(self.blueprints),
            "agents": len(self.agents),
            "regulatory": len(self.regulatory),
            "methods": len(self.methods),
            "approvals": len(self.approvals),
            "learning": len(self.learning),
            "ontology_concepts": len(self.ontology.get("concepts", [])),
            "prompts": len(self.prompts),
        }


# ------------------------------------------------------------- collection


def _concept_rows() -> list[dict[str, Any]]:
    from backend.semantics import ontology

    rows: list[dict[str, Any]] = []
    for contract in ontology.CONTRACTS_V2:
        rows.append({
            "concept_id": contract.concept_id,
            "label": getattr(contract, "label", ""),
            "kind": getattr(contract, "kind", ""),
            "unit": getattr(contract, "unit", ""),
            "aliases": list(getattr(contract, "aliases", ()) or ()),
            "allowed_operations": list(
                getattr(contract, "allowed_operations", ()) or ()),
            "period_behaviour": getattr(contract, "period_behaviour", ""),
        })
    return rows


#: Blueprint statuses that may be packaged. Wider than the teaching-case
#: rule and deliberately so: a blueprint is an analytical DESIGN authored
#: here and validated deterministically, not an approved answer to a
#: question about somebody's portfolio, so SYSTEM_VALIDATED is honest
#: provenance rather than a borrowed opinion. Each row carries its own
#: status so the receiver reads which it got instead of assuming.


def _blueprint_rows() -> list[dict[str, Any]]:
    from backend.judgment import blueprints as bp

    allowed = {bp.APPROVED, bp.SYSTEM_VALIDATED}
    rows: list[dict[str, Any]] = []
    for blueprint in getattr(bp, "BY_ID", {}).values():
        if getattr(blueprint, "status", "") not in allowed:
            continue
        rows.append({
            "blueprint_id": blueprint.blueprint_id,
            "version": blueprint.version,
            "business_name": blueprint.business_name,
            "family": blueprint.family,
            "description": blueprint.description,
            "applicable_scope": blueprint.applicable_scope,
            "when_to_use": list(blueprint.when_to_use or ()),
            "when_not_to_use": list(blueprint.when_not_to_use or ()),
            "required_objectives": list(blueprint.required_objectives or ()),
            "required_concepts": list(blueprint.required_concepts or ()),
            "required_methods": list(blueprint.required_methods or ()),
            "mandatory_validations": list(
                blueprint.mandatory_validations or ()),
            "stopping_rules": list(blueprint.stopping_rules or ()),
            "limitations_contract": list(blueprint.limitations_contract or ()),
            "officer_level": blueprint.officer_level,
            "ontology_version": blueprint.ontology_version,
            "status": blueprint.status,
            "fingerprint": blueprint.fingerprint,
        })
    return rows


def _agent_rows() -> list[dict[str, Any]]:
    """The Agent Registry, without anything that grants access.

    Tools are named, not wired: `allowed_tools` is a list of identifiers the
    receiver must already have. A receiver that lacks one has an agent that
    cannot run, which is the correct outcome — the alternative would be an
    agent that silently does less than its contract says.
    """
    from backend.agentic import registry as reg

    rows: list[dict[str, Any]] = []
    for agent in getattr(reg, "AGENTS", ()):
        if getattr(agent, "status", "") != getattr(reg, "ACTIVE", "ACTIVE"):
            continue
        rows.append({
            "agent_id": agent.agent_id,
            "business_name": agent.business_name,
            "purpose": agent.purpose,
            "when_to_use": list(agent.when_to_use or ()),
            "when_not_to_use": list(agent.when_not_to_use or ()),
            "allowed_capabilities": list(agent.allowed_capabilities or ()),
            "allowed_tools": list(agent.allowed_tools or ()),
            "allowed_methods": list(agent.allowed_methods or ()),
            "maximum_steps": agent.maximum_steps,
            "autonomy_level": agent.autonomy_level,
            "human_approval_requirements": list(
                agent.human_approval_requirements or ()),
            "escalation_rules": list(agent.escalation_rules or ()),
            "validation_requirements": list(
                agent.validation_requirements or ()),
            "model_role_preference": agent.model_role_preference,
            "version": agent.version,
            "status": agent.status,
        })
    return rows


def _routing_policy() -> dict[str, Any]:
    """Model ROLES and the rules that pick between them.

    Deliberately not model identifiers. §0 forbids hard-coded model IDs, and
    a package that named one would carry this installation's procurement
    decision into a receiver that may not have that model at all.
    """
    from backend.judgment import judgment_policy as jp

    return {
        "judgment_policy_version": getattr(jp, "JUDGMENT_POLICY_VERSION", ""),
        "situations": sorted(str(s) for s in getattr(jp, "SITUATIONS", ()) or ()),
        "roles": sorted({str(v) for v in getattr(jp, "ROLE_FOR", {}).values()}),
        "note": (
            "Roles, not model identifiers. The receiver maps each role to "
            "whichever model it has configured; nothing here assumes the "
            "sender's models are available."
        ),
    }


def collect(*, teaching_cases: list[dict[str, Any]] | None = None,
            regulatory: list[dict[str, Any]] | None = None,
            methods: list[dict[str, Any]] | None = None,
            evaluations: dict[str, Any] | None = None,
            approvals: list[dict[str, Any]] | None = None,
            learning_entries: list[Any] | None = None,
            known_limitations: tuple[str, ...] = ()) -> Source:
    """Build a Source from the live registries plus what the caller supplies.

    The registry halves — ontology, blueprints, judgment policy,
    visualization grammar, routing — are read here because they are code and
    therefore always available. Teaching cases, regulatory requirements,
    methods and ledger entries live in the database and are passed in, so
    this module stays importable and testable without one.

    Every list is filtered before it lands. A case that is not approved does
    not reach the Source, so no later step has to remember to exclude it.
    """
    from backend.judgment import judgment_policy as jp
    from backend.judgment import visual_grammar as vg
    from backend.semantics import ontology

    cases = [c for c in (teaching_cases or [])
             if str(c.get("status", "")) == EXPORTABLE_CASE_STATUS]
    dropped = len(teaching_cases or []) - len(cases)
    if dropped:
        logger.info("bundle: %d teaching case(s) held back — not approved",
                    dropped)

    approved_regulatory = [r for r in (regulatory or [])
                           if str(r.get("status", "")).upper() == "APPROVED"]

    portable: list[dict[str, Any]] = []
    held_back = 0
    for entry in learning_entries or []:
        if not getattr(entry, "exportable", False):
            held_back += 1
            continue
        portable.append(ledger_mod.portable_view(entry))
    if held_back:
        logger.info("bundle: %d ledger entr(ies) held back — approved and "
                    "portable are both required", held_back)

    return Source(
        teaching_cases=cases,
        ontology={"ontology_version": ontology.ONTOLOGY_VERSION,
                  "concepts": _concept_rows()},
        blueprints=_blueprint_rows(),
        judgment_policy={
            "version": getattr(jp, "JUDGMENT_POLICY_VERSION", ""),
            "max_facts": getattr(jp, "MAX_FACTS", None),
            "max_observations": getattr(jp, "MAX_OBSERVATIONS", None),
            "situations": sorted(str(s) for s in getattr(jp, "SITUATIONS", ()) or ()),
        },
        visualization={
            "grammar_version": getattr(vg, "GRAMMAR_VERSION", ""),
            "charts": sorted(str(c) for c in getattr(vg, "CHARTS", ()) or ()),
        },
        prompts={},
        routing=_routing_policy(),
        agents=_agent_rows(),
        regulatory=approved_regulatory,
        methods=[m for m in (methods or [])
                 if str(m.get("status", "")).upper() in
                 ("CERTIFIED", "APPROVED")],
        evaluations=evaluations or {},
        approvals=approvals or [],
        learning=portable,
        known_limitations=known_limitations,
    )


# ------------------------------------------------------------- assembling


def _provenance(source: Source, manifest: pack.Manifest) -> dict[str, Any]:
    return {
        "built_at": datetime.now(UTC).isoformat(),
        "built_by": manifest.created_by,
        "source_instance_id": manifest.source_instance_id,
        "source_build_sha": manifest.source_build_sha,
        "app_version": manifest.app_version,
        "bundle_schema_version": BUNDLE_SCHEMA_VERSION,
        "counts": source.counts(),
        "case_status_exported": EXPORTABLE_CASE_STATUS,
        "note": (
            "Every teaching case in this package was approved by a named "
            "person at the sending installation. Approval there is not "
            "evidence here: the questions were asked against the sender's "
            "governed datasets."
        ),
    }


def _compatibility(source: Source, manifest: pack.Manifest) -> dict[str, Any]:
    return {
        "ontology_version": source.ontology.get("ontology_version", ""),
        "concept_ids": sorted(
            c["concept_id"] for c in source.ontology.get("concepts", [])),
        "blueprint_ids": sorted(
            b["blueprint_id"] for b in source.blueprints),
        "method_ids": sorted(str(m.get("method_id", "")) for m in source.methods),
        "required_modules": list(manifest.required_modules),
        "minimum_app_version": manifest.minimum_app_version,
        "maximum_tested_app_version": manifest.maximum_tested_app_version,
        "supported_scopes": list(manifest.supported_scopes),
        "supported_languages": list(manifest.supported_languages),
    }


def brain_pack(source: Source, manifest: pack.Manifest) -> pack.Contents:
    """The full intelligence layer, as files."""
    contents = pack.Contents()
    contents.add_jsonl("teaching/cases.jsonl", source.teaching_cases)
    contents.add("ontology/concepts.json", source.ontology)
    contents.add_jsonl("blueprints/blueprints.jsonl", source.blueprints)
    contents.add("judgment/policy.json", source.judgment_policy)
    contents.add("visualization/grammar.json", source.visualization)
    if source.prompts:
        contents.add("prompts/templates.json", source.prompts)
    contents.add("routing/policy.json", source.routing)
    if source.agents:
        contents.add_jsonl("agents/registry.jsonl", source.agents)
    if source.regulatory:
        contents.add_jsonl("regulatory/requirements.jsonl", source.regulatory)
    if source.methods:
        contents.add_jsonl("methods/methods.jsonl", source.methods)
    contents.add("evaluations/summary.json", source.evaluations)
    contents.add_jsonl("approvals/records.jsonl", source.approvals)
    contents.add("provenance/provenance.json", _provenance(source, manifest))
    contents.add("compatibility/receiver.json",
                 _compatibility(source, manifest))
    return contents


def learning_bundle(source: Source, manifest: pack.Manifest, *,
                    baseline_release_id: str = "") -> pack.Contents:
    """The delta since a baseline: what was learned, not what is known.

    A Learning Bundle with no baseline is not a delta; it is a Brain Pack
    that has lost half its contents and will read to a receiver as though
    this installation knows only these forty things. Refused rather than
    written.
    """
    if not baseline_release_id.strip():
        raise BundleError(
            "a Learning Bundle is a delta and needs the baseline it is a "
            "delta from. Without it the receiver cannot tell whether this is "
            "everything this installation knows or everything it recently "
            "learned, and those lead to opposite decisions.")
    if not source.learning and not source.teaching_cases:
        raise BundleError(
            "there is nothing portable to send. Learning that is local by "
            "right stays local; an empty bundle would still install, and "
            "would still be recorded as an integration that improved "
            "nothing.")

    contents = pack.Contents()
    contents.add_jsonl("teaching/cases.jsonl", source.teaching_cases)
    contents.add_jsonl("teaching/learning.jsonl", source.learning)
    if source.regulatory:
        contents.add_jsonl("regulatory/requirements.jsonl", source.regulatory)
    if source.methods:
        contents.add_jsonl("methods/methods.jsonl", source.methods)
    contents.add("evaluations/summary.json", source.evaluations)
    contents.add_jsonl("approvals/records.jsonl", source.approvals)
    provenance = _provenance(source, manifest)
    provenance["baseline_release_id"] = baseline_release_id
    provenance["delta"] = True
    contents.add("provenance/provenance.json", provenance)
    contents.add("compatibility/receiver.json",
                 _compatibility(source, manifest))
    return contents


# ------------------------------------------- §15 developer bundle


#: What §15 says a Developer Intelligence Bundle must not carry. Listed as
#: prose because it is written into the README the receiving developer
#: reads, and a list they can check against the file tree is worth more than
#: an assurance they cannot.
DEVELOPER_EXCLUSIONS: tuple[str, ...] = (
    "No API keys, tokens or connection strings of any kind.",
    "No .env file and no environment capture.",
    "No client data: no borrower names, no account numbers, no raw rows "
    "from any governed dataset.",
    "No sealed-holdout questions and no holdout answers. The holdout is what "
    "makes a measured improvement believable, and a copy of it in a "
    "development session is a copy that can leak into training.",
    "No gold benchmark content.",
    "No hidden chain-of-thought. Model reasoning is not an asset and is not "
    "stored, here or anywhere.",
    "No executable code, no pickles, no notebooks, no shell scripts. Every "
    "file in this package is JSON, JSONL, Markdown or CSV, and nothing in "
    "it runs.",
)


def developer_bundle(source: Source, manifest: pack.Manifest) -> pack.Contents:
    """§15's EXPORT DEVELOPER INTELLIGENCE BUNDLE.

    The same approved assets as a Brain Pack, plus a README written for the
    person or agent who will open this in a repository rather than install
    it into a running system.
    """
    contents = brain_pack(source, manifest)
    contents.add("README_FOR_CLAUDE_CODE.md",
                 readme_for_claude_code(source, manifest))
    contents.add("compatibility/inspection.json", {
        "how_to_inspect": [
            "unzip -l <package> — every path is listed before anything is "
            "extracted; the package is a plain zip with no executable "
            "member.",
            "cat manifest.json — versions, counts and what the sender claims "
            "this is.",
            "cat provenance/provenance.json — who built it and from which "
            "build.",
            "cat compatibility/receiver.json — the concept, blueprint and "
            "method identifiers a receiver needs.",
            "wc -l teaching/cases.jsonl — one approved case per line.",
        ],
        "excluded": list(DEVELOPER_EXCLUSIONS),
    })
    return contents


def readme_for_claude_code(source: Source,
                           manifest: pack.Manifest) -> str:
    """§15's README. Written for a reader who will act on it.

    Its most important section is what must NOT be trusted. A bundle read
    into a development session looks authoritative — it is versioned, it is
    signed, it came from production — and the teaching cases inside it are
    approved ANSWERS TO QUESTIONS ASKED SOMEWHERE ELSE.
    """
    counts = source.counts()
    limitations = source.known_limitations or (
        "The sender declared no known limitations. That is a claim about "
        "their review process, not a property of this package.",
    )
    lines: list[str] = []
    add = lines.append

    add(f"# {manifest.brain_name} — Developer Intelligence Bundle")
    add("")
    add(f"Brain `{manifest.brain_id}` version `{manifest.brain_version}`, "
        f"built {manifest.created_at or 'unknown'} by "
        f"`{manifest.created_by or 'unknown'}`.")
    add("")
    add("This package is CreditProbe's approved intelligence assets, "
        "packaged for reading in a development session. It is data. Nothing "
        "in it executes, and importing it into a repository changes no "
        "behaviour until someone deliberately wires it up.")
    add("")

    add("## What is in it")
    add("")
    add("| Component | Path | Count |")
    add("| --- | --- | --- |")
    add(f"| Approved teaching cases | `teaching/cases.jsonl` | "
        f"{counts['teaching_cases']} |")
    add(f"| Ontology concepts | `ontology/concepts.json` | "
        f"{counts['ontology_concepts']} |")
    add(f"| Investigation blueprints | `blueprints/blueprints.jsonl` | "
        f"{counts['blueprints']} |")
    add("| Judgment policy | `judgment/policy.json` | 1 |")
    add("| Visualization grammar | `visualization/grammar.json` | 1 |")
    add("| Model-role routing policy | `routing/policy.json` | 1 |")
    add(f"| Approved regulatory requirements | "
        f"`regulatory/requirements.jsonl` | {counts['regulatory']} |")
    add(f"| Certified method definitions | `methods/methods.jsonl` | "
        f"{counts['methods']} |")
    add("| Evaluation summaries | `evaluations/summary.json` | 1 |")
    add(f"| Approval records | `approvals/records.jsonl` | "
        f"{counts['approvals']} |")
    add("")

    add("## Versions")
    add("")
    add(f"- Package schema: `{manifest.package_schema_version}`")
    add(f"- Bundle schema: `{BUNDLE_SCHEMA_VERSION}`")
    add(f"- Ontology: `{source.ontology.get('ontology_version', 'unknown')}`")
    add(f"- Judgment policy: "
        f"`{source.judgment_policy.get('version', 'unknown')}`")
    add(f"- Application it was built from: `{manifest.app_version}` "
        f"(build `{manifest.source_build_sha}`)")
    add(f"- Minimum application version to install into: "
        f"`{manifest.minimum_app_version}`")
    add("")

    add("## How to inspect it")
    add("")
    add("Read it before extracting it. The package is a zip with no "
        "executable member, so listing is safe and tells you most of what "
        "you need:")
    add("")
    add("```")
    add("unzip -l bundle.cpdev            # every path, before extraction")
    add("unzip -p bundle.cpdev manifest.json | head -40")
    add("unzip -p bundle.cpdev provenance/provenance.json")
    add("unzip -p bundle.cpdev teaching/cases.jsonl | head -3")
    add("```")
    add("")
    add("`checksums.json` carries a SHA-256 for every member. If a file's "
        "hash does not match, the package was altered after it was built and "
        "nothing in it should be believed.")
    add("")

    add("## How to import it into a repository")
    add("")
    add("1. Verify the checksums, and the signature if the sender supplied "
        "a key you already trust. A signature you verify against a key that "
        "arrived with the package proves only that the package is "
        "self-consistent.")
    add("2. Extract into a directory OUTSIDE your source tree first, and "
        "read it there. A bundle that lands in `backend/` becomes an import "
        "path by accident.")
    add("3. Treat every file as input to a review, not as a change. There is "
        "no install step, because there should not be one.")
    add("4. If you intend to run these cases in a live CreditProbe, do not "
        "copy files: use Brain Center → IMPORTS, which quarantines the "
        "package, evaluates it against YOUR holdout and produces a measured "
        "lift or regression before anything activates.")
    add("")

    add("## What must NOT be trusted without evaluation")
    add("")
    add("Everything measurable in here was measured somewhere else.")
    add("")
    add("- **The teaching cases** are approved answers to questions asked "
        "against the sender's governed datasets, with the sender's column "
        "names, period conventions and portfolio composition. A case that is "
        "correct there can be confidently wrong here.")
    add("- **The evaluation summaries** are the sender's scores on the "
        "sender's holdout. They say nothing about how this Brain performs on "
        "your data, and a score computed against a holdout the package "
        "carried would be flattering rather than wrong. This package "
        "contains no holdout for exactly that reason.")
    add("- **The regulatory requirements** were extracted from documents and "
        "approved by a reviewer in the sender's jurisdiction. Where your "
        "jurisdiction differs, they are a different regulator's rules "
        "wearing the same field names.")
    add("- **The blueprints and methods** encode analytical choices that "
        "were right for the sender's portfolio mix. Corporate-heavy "
        "assumptions do not transfer to a retail book by being versioned.")
    add("- **The known limitations below** are what the sender knew to "
        "declare. The list is not the set of things wrong with this Brain.")
    add("")
    for limitation in limitations:
        add(f"- {limitation}")
    add("")

    add("## What stays local and confidential")
    add("")
    add("This package deliberately does not contain:")
    add("")
    for exclusion in DEVELOPER_EXCLUSIONS:
        add(f"- {exclusion}")
    add("")
    add("If you find any of the above inside a package claiming to be a "
        "CreditProbe Developer Intelligence Bundle, it was not produced by "
        "this exporter — every one of those is checked at export as well as "
        "at import, and the export refuses rather than warns.")
    add("")

    add("## What this package is not")
    add("")
    add("- Not a model. There are no weights here and no fine-tune.")
    add("- Not a dataset. There are no client rows here.")
    add("- Not a licence to skip evaluation. The sender's approval is "
        "provenance, not proof.")
    add("")
    return "\n".join(lines) + "\n"
