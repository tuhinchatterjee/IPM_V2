"""The Brain Pack and the Learning Bundle. §9, §10, §11, §12.

Two portable packages, one format.

A **Learning Bundle** (`.cplearn`) carries reviewed human learning as a
DELTA - approved teaching cases, ontology aliases, regulatory
interpretations, feedback corrections - so one installation can share what
its people learned without replacing the receiver's intelligence release.

A **Brain Pack** (`.cpbrain`) carries a complete versioned release: the
ontology, the approved teaching release, blueprints, judgment and
visualization policy, prompts, routing, agent policy, approved regulatory
knowledge, portable method definitions, auxiliary models in safe formats,
evaluation summaries, approvals, compatibility and provenance.

Both are signed ZIPs of declarative files. Neither is, and neither may
become:

    Claude foundation-model weights, API credentials, client portfolio
    data, a Docker image, arbitrary executable code, or sealed holdout
    questions and answers.

That list is not a disclaimer. `backend.brain.security` enforces the format
half of it and `_forbidden_content` enforces the rest, on the way OUT as
well as on the way in - a package that could not be imported must not be
exportable either, or the first installation to trust its own export is the
one that ships the problem.
"""

from __future__ import annotations

import json
import logging
import zipfile
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any

from backend.brain import security

logger = logging.getLogger(__name__)

PACKAGE_SCHEMA_VERSION = "1.0.0"

BRAIN_PACK = "cpbrain"
LEARNING_BUNDLE = "cplearn"
DEVELOPER_BUNDLE = "cpdev"

SUFFIX: dict[str, str] = {
    BRAIN_PACK: ".cpbrain",
    LEARNING_BUNDLE: ".cplearn",
    DEVELOPER_BUNDLE: ".cpdev",
}

#: §10's directory layout. A package need not fill every one; it may not
#: invent a top-level directory outside this set, because a reviewer reading
#: the tree should not have to ask what a folder is.
DIRECTORIES: tuple[str, ...] = (
    "ontology", "teaching", "blueprints", "judgment", "visualization",
    "prompts", "routing", "agents", "regulatory", "methods",
    "auxiliary_models", "evaluations", "approvals", "provenance",
    "compatibility",
)

REQUIRED_FILES: tuple[str, ...] = (
    "manifest.json", "checksums.json", "README.md",
)


class PackError(Exception):
    """A package that may not be written, or may not be trusted."""


# ---------------------------------------------------------------- manifest


@dataclass
class Manifest:
    """§11's fields. No secret material, by construction and by test."""

    brain_id: str
    brain_name: str
    brain_version: str
    package_kind: str = BRAIN_PACK
    package_schema_version: str = PACKAGE_SCHEMA_VERSION
    created_at: str = ""
    created_by: str = ""

    # where it came from
    source_instance_id: str = ""
    source_organization: str = ""      # redacted identifier, never a tenant
    source_build_sha: str = ""
    app_version: str = ""

    # what it is
    intelligence_release_id: str = ""
    teaching_release_id: str = ""
    regulatory_release_id: str = ""
    ontology_version: str = ""
    blueprint_version: str = ""
    judgment_policy_version: str = ""
    visualization_grammar_version: str = ""
    prompt_versions: dict[str, str] = field(default_factory=dict)
    routing_policy_version: str = ""
    agent_policy_version: str = ""
    auxiliary_model_versions: dict[str, str] = field(default_factory=dict)

    # what a receiver needs to have
    supported_modules: tuple[str, ...] = ()
    required_modules: tuple[str, ...] = ()
    minimum_app_version: str = ""
    maximum_tested_app_version: str = ""
    supported_scopes: tuple[str, ...] = ()
    supported_languages: tuple[str, ...] = ("en",)

    # what is inside, honestly counted
    case_counts: dict[str, int] = field(default_factory=dict)
    human_approved_count: int = 0
    system_validated_count: int = 0
    evaluation_metrics: dict[str, Any] = field(default_factory=dict)
    known_limitations: tuple[str, ...] = ()

    # what it is derived from
    data_classification: str = "PORTABLE_APPROVED_LEARNING"
    contains_client_derived_patterns: bool = False
    redaction_status: str = "REDACTED"

    # integrity
    content_hashes: dict[str, str] = field(default_factory=dict)
    signature: str = ""
    signing_key_id: str = ""

    # governance
    approval_records: tuple[dict[str, Any], ...] = ()
    parent_brain_ids: tuple[str, ...] = ()
    merge_history: tuple[dict[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        body = asdict(self)
        return {k: (list(v) if isinstance(v, tuple) else v)
                for k, v in body.items()}

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Manifest:
        known = {f for f in cls.__dataclass_fields__}
        cleaned = {k: v for k, v in payload.items() if k in known}
        for key in ("supported_modules", "required_modules",
                    "supported_scopes", "supported_languages",
                    "known_limitations", "parent_brain_ids"):
            if key in cleaned and isinstance(cleaned[key], list):
                cleaned[key] = tuple(cleaned[key])
        for key in ("approval_records", "merge_history"):
            if key in cleaned and isinstance(cleaned[key], list):
                cleaned[key] = tuple(cleaned[key])
        return cls(**cleaned)


#: Manifest fields that must never be empty. A package that cannot say what
#: it is, which release it came from or what it was built against cannot be
#: evaluated against a receiver, and importing it would be importing an
#: unknown.
MANDATORY: tuple[str, ...] = (
    "brain_id", "brain_name", "brain_version", "package_schema_version",
    "created_at", "created_by", "source_instance_id", "source_build_sha",
    "app_version", "ontology_version", "minimum_app_version",
    "data_classification", "redaction_status",
)

#: Manifest keys that would be a leak if they ever appeared. Checked rather
#: than trusted: the dataclass has no such field today, and a future edit
#: that added one should fail loudly.
FORBIDDEN_MANIFEST_KEYS: frozenset[str] = frozenset({
    "api_key", "anthropic_api_key", "secret", "password", "token",
    "signing_key", "private_key", "database_url", "tenant_id",
    "source_tenant_id", "client_names", "connection_string",
})


def validate_manifest(manifest: Manifest) -> list[str]:
    """Everything wrong with a manifest, in one pass."""
    problems: list[str] = []
    body = manifest.to_dict()

    for name in MANDATORY:
        if not str(body.get(name) or "").strip():
            problems.append(f"{name} is required and is empty")

    if manifest.package_kind not in SUFFIX:
        problems.append(f"{manifest.package_kind!r} is not a package kind")

    leaked = sorted(set(body) & FORBIDDEN_MANIFEST_KEYS)
    if leaked:
        problems.append(
            "the manifest carries " + ", ".join(leaked)
            + ", and a manifest is the one file every reviewer opens")

    for key, value in body.items():
        if isinstance(value, str) and security.scan_secrets(value):
            problems.append(f"{key} contains something secret-shaped")

    if manifest.contains_client_derived_patterns and \
            manifest.redaction_status != "REDACTED":
        problems.append(
            "the package declares client-derived patterns and does not "
            "declare them redacted, which is the combination §14 forbids "
            "from leaving an installation")

    counted = sum(manifest.case_counts.values())
    claimed = manifest.human_approved_count + manifest.system_validated_count
    if counted and claimed > counted:
        problems.append(
            f"the manifest claims {claimed} approved or validated cases out "
            f"of {counted} counted, which cannot both be true")
    return problems


# --------------------------------------------------------------- contents


@dataclass
class Contents:
    """What goes into a package, as files rather than as objects.

    Keyed by archive path. Every value is already-serialised text, so the
    writer never has to decide how to serialise something and can never
    reach for pickle to solve a hard case.
    """

    files: dict[str, str] = field(default_factory=dict)

    def add(self, path: str, body: Any) -> None:
        if isinstance(body, str):
            text = body
        elif isinstance(body, (list, tuple)) and path.endswith(".jsonl"):
            text = "\n".join(json.dumps(row, default=str) for row in body)
        else:
            text = json.dumps(body, indent=2, default=str)
        self.files[path] = text

    def add_jsonl(self, path: str, rows: list[Any]) -> None:
        self.files[path] = "\n".join(
            json.dumps(row, default=str) for row in rows)

    @property
    def directories(self) -> set[str]:
        return {p.split("/")[0] for p in self.files if "/" in p}


def _forbidden_content(contents: Contents) -> list[str]:
    """What may not leave this installation, whatever the manifest says.

    Applied on export as well as import. A package that could not be
    imported must not be exportable, or the first installation to trust its
    own export is the one that ships the problem.
    """
    problems: list[str] = []
    for path, text in contents.files.items():
        reason = security.unsafe_path(path)
        if reason:
            problems.append(f"{path}: {reason}")
        forbidden = security._forbidden(path)
        if forbidden:
            problems.append(f"{path}: {forbidden}")
        for label, shown in security.scan_secrets(text):
            problems.append(f"{path}: {label} present ({shown})")
        for label, count in security.scan_client_data(text):
            if label == "email address":
                continue
            problems.append(
                f"{path}: {count} occurrence(s) of {label}; a Brain carries "
                "patterns, not client rows")
    unknown = contents.directories - set(DIRECTORIES)
    if unknown:
        problems.append(
            "unknown top-level directory: " + ", ".join(sorted(unknown)))
    return problems


#: Paths a package may never contain, whatever their format. Sealed holdout
#: content is the one that would be invisible: a package carrying it looks
#: exactly like a package that does not, and the score it produces would be
#: flattering rather than wrong.
FORBIDDEN_PATHS: tuple[str, ...] = (
    "teaching/holdout", "evaluations/holdout", "holdout",
    "teaching/gold", "evaluations/gold", "benchmark",
    "feedback/raw", "teaching/raw_feedback",
)


def _sealed_content(contents: Contents) -> list[str]:
    problems: list[str] = []
    for path in contents.files:
        lowered = path.lower()
        for forbidden in FORBIDDEN_PATHS:
            if lowered.startswith(forbidden):
                problems.append(
                    f"{path}: sealed holdout, gold benchmark or raw feedback "
                    "may never be packaged. A score produced against a "
                    "holdout the candidate carried is flattering rather "
                    "than wrong, and nothing downstream could tell.")
                break
    return problems


# ----------------------------------------------------------------- writing


def write(path: str | Path, manifest: Manifest, contents: Contents, *,
          readme: str = "", signing_key: bytes | None = None,
          signing_key_id: str = "") -> Path:
    """Write a signed package, or refuse to.

    Refusing is the common case worth designing for. Every check that runs
    on import runs here too, so an installation cannot produce a package it
    would itself reject.
    """
    target = Path(path)
    manifest.created_at = manifest.created_at or datetime.now(
        UTC).isoformat()
    manifest.package_schema_version = PACKAGE_SCHEMA_VERSION

    problems = validate_manifest(manifest)
    problems += _forbidden_content(contents)
    problems += _sealed_content(contents)
    if problems:
        raise PackError(
            "this package may not be written: " + "; ".join(problems[:12]))

    body = dict(contents.files)
    body["README.md"] = readme or _readme(manifest)
    manifest.content_hashes = {
        name: security.digest_bytes(text.encode("utf-8"))
        for name, text in sorted(body.items())
    }
    body["checksums.json"] = json.dumps(manifest.content_hashes, indent=2)
    if signing_key:
        manifest.signing_key_id = signing_key_id
    body["manifest.json"] = json.dumps(manifest.to_dict(), indent=2,
                                       default=str)

    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(body):
            archive.writestr(name, body[name])
        if signing_key:
            payload = b"\x00".join(
                part for name in sorted(body)
                for part in (name.encode("utf-8"),
                             body[name].encode("utf-8")))
            archive.writestr("signature.json", json.dumps({
                "signer": signing_key_id,
                "algorithm": "HMAC-SHA256",
                "content_digest": security.digest_bytes(payload),
                "signature": security.sign(payload, signing_key),
                "signed_at": datetime.now(UTC).isoformat(),
            }, indent=2))

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(buffer.getvalue())
    logger.info("wrote %s (%s, %d entries, %d bytes)", target,
                manifest.package_kind, len(body), target.stat().st_size)
    return target


def _readme(manifest: Manifest) -> str:
    """What a person opening the package needs to know first."""
    return f"""# {manifest.brain_name} {manifest.brain_version}

A CreditProbe {"AI Brain Pack" if manifest.package_kind == BRAIN_PACK
                else "Learning Bundle"}.

## What this is

A versioned, portable package of CreditProbe's governed intelligence layer:
{"a complete intelligence release" if manifest.package_kind == BRAIN_PACK
 else "reviewed learning as a delta on top of your own release"}.

## What this is NOT

* **Not Claude foundation-model weights.** Nothing here changes the
  provider's model. This is the governed layer around it.
* **Not credentials.** No API key, no `.env`, no connection string.
* **Not client data.** Patterns and policies, never borrower rows.
* **Not executable.** Declarative formats only; no pickle, no scripts.
* **Not a sealed holdout.** Evaluation gold stays with the installation
  that owns it.

## Before you trust it

Nothing in this package activates on import. It is quarantined, checked,
compared against your own evaluation sets, and shown to you as measured
lift or regression before anyone may approve it.

Built from `{manifest.source_build_sha or "unrecorded"}` against app
version `{manifest.app_version or "unrecorded"}`; needs at least
`{manifest.minimum_app_version or "unrecorded"}`.

Ontology `{manifest.ontology_version}`. {manifest.human_approved_count}
human-approved and {manifest.system_validated_count} system-validated
cases.
"""


# ----------------------------------------------------------------- reading


@dataclass
class OpenedPackage:
    """A package that passed inspection, and what it holds."""

    inspection: security.Inspection
    manifest: Manifest | None = None
    files: dict[str, str] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)

    @property
    def usable(self) -> bool:
        return (self.inspection.clean and self.manifest is not None
                and not self.problems)

    def to_dict(self) -> dict[str, Any]:
        return {
            "usable": self.usable,
            "inspection": self.inspection.to_dict(),
            "manifest": self.manifest.to_dict() if self.manifest else None,
            "entries": sorted(self.files),
            "problems": list(self.problems),
        }


def read(path: str | Path, *,
         trusted_keys: dict[str, bytes] | None = None) -> OpenedPackage:
    """Inspect a package and, only if it survives, read it.

    The order is the safety property. Nothing is read until the structural
    checks have passed, so a decompression bomb is refused from its
    directory entry rather than while it is being decompressed.
    """
    target = Path(path)
    raw = target.read_bytes()
    inspection = security.inspect(str(target), raw,
                                  trusted_keys=trusted_keys)
    opened = OpenedPackage(inspection=inspection)
    if not inspection.clean:
        return opened

    with zipfile.ZipFile(BytesIO(raw)) as archive:
        for name in archive.namelist():
            if name.endswith("/"):
                continue
            try:
                opened.files[name] = archive.read(name).decode("utf-8")
            except UnicodeDecodeError:
                continue

    for required in REQUIRED_FILES:
        if required not in opened.files:
            opened.problems.append(f"{required} is missing")

    if "manifest.json" in opened.files:
        try:
            opened.manifest = Manifest.from_dict(
                json.loads(opened.files["manifest.json"]))
        except (json.JSONDecodeError, TypeError) as e:
            opened.problems.append(f"manifest.json is unreadable: {e}")
        else:
            opened.problems.extend(validate_manifest(opened.manifest))

    recorded = opened.manifest.content_hashes if opened.manifest else {}
    for name, expected in recorded.items():
        body = opened.files.get(name)
        if body is None:
            opened.problems.append(f"{name} is in the manifest and missing")
        elif security.digest_bytes(body.encode("utf-8")) != expected:
            opened.problems.append(
                f"{name} does not match the hash the manifest recorded, so "
                "the package has been altered since it was built")
    return opened
