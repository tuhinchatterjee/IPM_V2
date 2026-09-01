"""What a Brain package may contain, and what it may never. §10, §26.

A Brain Pack arrives from another installation, possibly from another
organisation, and a person is about to click Import. Everything in this
module exists because that click must not be able to hurt them.

The threat is not exotic. A ZIP is a list of paths and a list of bytes, and
both are attacker-controlled:

  * a path can be `../../etc/cron.d/x` and escape the directory it was
    extracted into (zip-slip);
  * a path can be an absolute path, or a symlink pointing anywhere;
  * a few kilobytes can expand to gigabytes and take the host down;
  * an entry can be a pickle, which is not data but a program, and
    `pickle.loads` on it is `exec` with extra steps;
  * an entry can carry an API key, a client's borrower list, or another
    tenant's cases.

So this module is written as a series of refusals rather than as a parser.
Nothing here opens an entry to decide whether it is safe; it decides from
the ARCHIVE METADATA first, refuses on any doubt, and only then reads what
survived. `inspect()` never extracts, never deserialises and never imports.
"""

from __future__ import annotations

import hashlib
import hmac
import io
import json
import logging
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

logger = logging.getLogger(__name__)

SECURITY_VERSION = "1.0.0"

# --------------------------------------------------------------- the limits

#: The largest package that may be inspected at all.
MAX_PACKAGE_BYTES = 256 * 1024 * 1024          # 256 MB
#: The largest single entry, uncompressed.
MAX_ENTRY_BYTES = 64 * 1024 * 1024             # 64 MB
#: The largest total uncompressed size.
MAX_TOTAL_BYTES = 512 * 1024 * 1024            # 512 MB
#: The most entries a package may hold.
MAX_ENTRIES = 20_000
#: Compression ratio above which an entry is treated as a decompression
#: bomb. Text compresses well - JSONL of teaching cases reaches 20:1 - so
#: the bar is set where a legitimate corpus does not reach and a zip bomb
#: (over 1000:1) cannot hide.
MAX_COMPRESSION_RATIO = 200.0

# ------------------------------------------------------------- the formats

#: §10's allowlist. Anything not here is refused, rather than anything on a
#: blocklist being refused - a blocklist is a list of the attacks somebody
#: thought of.
ALLOWED_SUFFIXES: frozenset[str] = frozenset({
    ".json", ".jsonl", ".yaml", ".yml", ".md", ".txt", ".csv",
    ".onnx",          # a model format that is data, not code
    ".png", ".svg",   # allowlisted assets for a README
})

#: Entries that are refused BY NAME whatever their suffix, because the name
#: is what a reader would trust.
FORBIDDEN_NAMES: frozenset[str] = frozenset({
    ".env", ".env.local", ".env.production", "id_rsa", "id_ed25519",
    "credentials", "credentials.json", "secrets.json", ".npmrc",
    ".pypirc", ".netrc", ".git-credentials",
})

#: Suffixes that are refused with a named reason. Everything not in
#: ALLOWED_SUFFIXES is refused anyway; these are called out so the refusal
#: says something useful instead of "unknown format".
FORBIDDEN_SUFFIXES: dict[str, str] = {
    ".pkl": "a pickle is a program, not data: loading one executes it",
    ".pickle": "a pickle is a program, not data: loading one executes it",
    ".joblib": "joblib objects deserialise arbitrary Python",
    ".dill": "dill deserialises arbitrary Python",
    ".pt": "a torch checkpoint unpickles by default",
    ".pth": "a torch checkpoint unpickles by default",
    ".py": "Python source has no place in a package that is data",
    ".pyc": "compiled Python has no place in a package that is data",
    ".sh": "a shell script is not intelligence",
    ".bat": "a batch file is not intelligence",
    ".ps1": "a PowerShell script is not intelligence",
    ".exe": "an executable is not intelligence",
    ".dll": "a library is not intelligence",
    ".so": "a shared object is not intelligence",
    ".dylib": "a shared object is not intelligence",
    ".jar": "a JAR is executable",
    ".xlsm": "a macro-enabled workbook carries code",
    ".docm": "a macro-enabled document carries code",
    ".sql": "a raw SQL dump is not a portable policy",
    ".dump": "a raw database dump may carry client rows",
    ".db": "a database file may carry client rows",
    ".sqlite": "a database file may carry client rows",
}

# ------------------------------------------------------------- the scanners

#: What a secret looks like. Deliberately broad: a false positive costs a
#: reviewer thirty seconds and a false negative ships a key.
_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("Anthropic API key", re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}")),
    ("OpenAI API key", re.compile(r"\bsk-[A-Za-z0-9]{32,}\b")),
    ("AWS access key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b")),
    ("Slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}\b")),
    ("private key block",
     re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----")),
    ("JSON web token", re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.")),
    ("assigned secret",
     re.compile(r"(?i)\b(?:api[_-]?key|secret|password|passwd|token)"
                r"\s*[:=]\s*[\"']?[A-Za-z0-9/+_\-]{16,}")),
    ("database URL with credentials",
     re.compile(r"(?i)\b(?:postgres|postgresql|mysql|mongodb)://"
                r"[^\s:]+:[^\s@]+@")),
)

#: What client data looks like. A Brain carries PATTERNS, never rows: an
#: identifier column in a package is a client list leaving the building.
_CLIENT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("customer identifier column",
     re.compile(r"(?i)\"(customer_id|account_id|borrower_name|"
                r"obligor_group|relationship_owner|owner_analyst)\"\s*:")),
    ("national identifier",
     re.compile(r"\b\d{10}\b(?=\s*[,\"\]}])")),
    ("IBAN", re.compile(r"\bSA\d{2}[0-9A-Z]{18}\b")),
    ("email address",
     re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")),
)


@dataclass
class Problem:
    """One reason a package may not be trusted."""

    kind: str
    entry: str
    detail: str
    #: A blocking problem prevents activation. A warning does not, and is
    #: shown to the reviewer.
    blocking: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "entry": self.entry,
                "detail": self.detail, "blocking": self.blocking}


@dataclass
class Inspection:
    """What inspecting a package established. Never what it contained."""

    path: str
    size_bytes: int = 0
    entries: int = 0
    uncompressed_bytes: int = 0
    problems: list[Problem] = field(default_factory=list)
    #: sha256 of the package as it arrived.
    digest: str = ""
    #: Per-entry sha256, for the manifest's checksums.
    checksums: dict[str, str] = field(default_factory=dict)
    signature_state: str = "UNSIGNED"
    signer: str = ""

    @property
    def blocking(self) -> list[Problem]:
        return [p for p in self.problems if p.blocking]

    @property
    def warnings(self) -> list[Problem]:
        return [p for p in self.problems if not p.blocking]

    @property
    def clean(self) -> bool:
        return not self.blocking

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path, "size_bytes": self.size_bytes,
            "entries": self.entries,
            "uncompressed_bytes": self.uncompressed_bytes,
            "digest": self.digest,
            "signature_state": self.signature_state, "signer": self.signer,
            "clean": self.clean,
            "problems": [p.to_dict() for p in self.problems],
        }


# ------------------------------------------------------------- path safety


def unsafe_path(name: str) -> str:
    """Why this archive path may not be extracted, or "".

    Checked as a POSIX path against the archive's own naming, which is what
    a ZIP actually stores. A Windows-style `..\\..\\x` is normalised first,
    because refusing only the forward-slash form would refuse only the
    attacker who had not thought about it.
    """
    if not name or name.strip() != name:
        return "the entry name is empty or padded with whitespace"
    normalised = name.replace("\\", "/")
    if normalised.startswith("/"):
        return "an absolute path would be written outside the package root"
    if re.match(r"^[A-Za-z]:", normalised):
        return "a drive-letter path would be written outside the root"
    parts = PurePosixPath(normalised).parts
    if ".." in parts:
        return ("the path escapes the package root with '..', which is how "
                "a ZIP overwrites a file outside the directory it was "
                "extracted into")
    if any(part in (".", "") for part in parts[:-1]):
        return "the path contains an empty or self-referential segment"
    if "\x00" in name:
        return "the path contains a null byte"
    return ""


def _forbidden(name: str) -> str:
    lowered = name.lower()
    base = PurePosixPath(lowered).name
    if base in FORBIDDEN_NAMES:
        return f"'{base}' never belongs in a package that is data"
    suffix = PurePosixPath(lowered).suffix
    if suffix in FORBIDDEN_SUFFIXES:
        return FORBIDDEN_SUFFIXES[suffix]
    if suffix and suffix not in ALLOWED_SUFFIXES:
        return (f"'{suffix}' is not on the allowlist; a Brain Pack carries "
                "declarative formats only")
    if not suffix:
        return "an entry with no suffix cannot be checked against the "\
               "format allowlist"
    return ""


# ---------------------------------------------------------------- scanning


def scan_secrets(text: str) -> list[tuple[str, str]]:
    """Every secret-shaped thing in a body of text."""
    found: list[tuple[str, str]] = []
    for label, pattern in _SECRET_PATTERNS:
        match = pattern.search(text)
        if match:
            shown = match.group(0)
            # Never echo a secret back. The point is to say one is there.
            found.append((label, f"{shown[:6]}… ({len(shown)} chars)"))
    return found


def scan_client_data(text: str) -> list[tuple[str, int]]:
    """Client-shaped content, and how much of it."""
    found: list[tuple[str, int]] = []
    for label, pattern in _CLIENT_PATTERNS:
        hits = pattern.findall(text)
        if hits:
            found.append((label, len(hits)))
    return found


# -------------------------------------------------------------- signatures


def digest_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sign(payload: bytes, key: bytes) -> str:
    """A detached HMAC over the package bytes.

    HMAC rather than a public-key signature deliberately: this proves the
    package came from an installation that holds the shared signing key,
    which is what a trusted-signer registry between two deployments of the
    same product actually needs. It is NOT a claim of non-repudiation, and
    §26's trusted signer registry is what carries the trust decision.
    """
    return hmac.new(key, payload, hashlib.sha256).hexdigest()


def verify(payload: bytes, key: bytes, signature: str) -> bool:
    return hmac.compare_digest(sign(payload, key), signature or "")


# -------------------------------------------------------------- inspection


def inspect(path: str, data: bytes | None = None, *,
            trusted_keys: dict[str, bytes] | None = None) -> Inspection:
    """Establish whether a package may be opened. Never opens it.

    Reads the archive's directory, decides from the metadata, and only then
    reads the bytes of entries that survived every structural check. Nothing
    is extracted to disk and nothing is deserialised.
    """
    raw = data if data is not None else _read(path)
    report = Inspection(path=path, size_bytes=len(raw),
                        digest=digest_bytes(raw))

    if len(raw) > MAX_PACKAGE_BYTES:
        report.problems.append(Problem(
            "size", "", f"the package is {len(raw):,} bytes, above the "
                        f"{MAX_PACKAGE_BYTES:,} limit"))
        return report

    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile as e:
        report.problems.append(Problem("format", "", f"not a readable "
                                                     f"package: {e}"))
        return report

    infos = archive.infolist()
    report.entries = len(infos)
    if len(infos) > MAX_ENTRIES:
        report.problems.append(Problem(
            "size", "", f"{len(infos):,} entries, above the "
                        f"{MAX_ENTRIES:,} limit"))
        return report

    total = 0
    for info in infos:
        name = info.filename
        if info.is_dir():
            continue

        problem = unsafe_path(name)
        if problem:
            report.problems.append(Problem("path", name, problem))
            continue

        # A symlink is stored as a regular entry with a mode bit. Following
        # one on extraction writes wherever it points.
        if (info.external_attr >> 16) & 0o170000 == 0o120000:
            report.problems.append(Problem(
                "path", name,
                "the entry is a symlink; extracting it writes to wherever "
                "it points"))
            continue

        forbidden = _forbidden(name)
        if forbidden:
            report.problems.append(Problem("format", name, forbidden))
            continue

        if info.file_size > MAX_ENTRY_BYTES:
            report.problems.append(Problem(
                "size", name,
                f"{info.file_size:,} bytes uncompressed, above the "
                f"{MAX_ENTRY_BYTES:,} per-entry limit"))
            continue

        ratio = (info.file_size / info.compress_size
                 if info.compress_size else float(info.file_size or 0))
        if ratio > MAX_COMPRESSION_RATIO:
            report.problems.append(Problem(
                "bomb", name,
                f"compresses {ratio:,.0f}:1, above the "
                f"{MAX_COMPRESSION_RATIO:,.0f}:1 limit; a package this "
                "dense is a decompression bomb rather than a corpus"))
            continue

        total += info.file_size
        if total > MAX_TOTAL_BYTES:
            report.problems.append(Problem(
                "bomb", name,
                f"the package expands past the {MAX_TOTAL_BYTES:,} byte "
                "total limit"))
            return report

    report.uncompressed_bytes = total
    if report.blocking:
        # Do not read the bytes of a package that already failed structure.
        return report

    for info in infos:
        if info.is_dir():
            continue
        try:
            body = archive.read(info.filename)
        except (zipfile.BadZipFile, RuntimeError, OSError) as e:
            report.problems.append(Problem("format", info.filename,
                                           f"unreadable: {e}"))
            continue
        report.checksums[info.filename] = digest_bytes(body)
        try:
            text = body.decode("utf-8")
        except UnicodeDecodeError:
            continue                      # a binary allowlisted asset

        for label, shown in scan_secrets(text):
            report.problems.append(Problem(
                "secret", info.filename,
                f"{label} present ({shown}). A Brain Pack never carries "
                "credentials."))
        for label, count in scan_client_data(text):
            report.problems.append(Problem(
                "client_data", info.filename,
                f"{count} occurrence(s) of {label}. A Brain carries "
                "patterns, not client rows.",
                blocking=label != "email address"))

    _check_signature(archive, raw, report, trusted_keys or {})
    return report


def _read(path: str) -> bytes:
    from pathlib import Path

    return Path(path).read_bytes()


def _check_signature(archive: zipfile.ZipFile, raw: bytes,
                     report: Inspection,
                     trusted_keys: dict[str, bytes]) -> None:
    """Whether the package is signed, and by someone this installation trusts.

    An unsigned or untrusted package is NOT a blocking problem. §26 is
    explicit: it may be inspected and evaluated, and only activation needs
    high-trust approval. Blocking here would stop a reviewer looking at a
    package they had every right to examine.
    """
    if "signature.json" not in archive.namelist():
        report.signature_state = "UNSIGNED"
        report.problems.append(Problem(
            "signature", "signature.json",
            "the package is unsigned. It may be inspected and evaluated; "
            "activation needs high-trust approval.",
            blocking=False))
        return
    try:
        payload = json.loads(archive.read("signature.json"))
    except (json.JSONDecodeError, KeyError):
        report.signature_state = "MALFORMED"
        report.problems.append(Problem(
            "signature", "signature.json",
            "the signature block could not be read"))
        return

    signer = str(payload.get("signer") or "")
    signature = str(payload.get("signature") or "")
    report.signer = signer
    signed_digest = str(payload.get("content_digest") or "")

    body = _signable(archive)
    if signed_digest and signed_digest != digest_bytes(body):
        report.signature_state = "CONTENT_CHANGED"
        report.problems.append(Problem(
            "signature", "signature.json",
            "the package contents do not match what was signed"))
        return

    key = trusted_keys.get(signer)
    if key is None:
        report.signature_state = "UNTRUSTED_SIGNER"
        report.problems.append(Problem(
            "signature", "signature.json",
            f"signed by '{signer}', who is not in the trusted signer "
            "registry. Inspect and evaluate freely; activation needs "
            "high-trust approval.",
            blocking=False))
        return
    if verify(body, key, signature):
        report.signature_state = "TRUSTED"
    else:
        report.signature_state = "INVALID"
        report.problems.append(Problem(
            "signature", "signature.json",
            f"the signature does not verify against '{signer}'s key"))


def _signable(archive: zipfile.ZipFile) -> bytes:
    """The bytes a signature covers: every entry but the signature itself.

    Ordered by name so two packages with the same content sign identically
    whatever order a ZIP writer happened to use.
    """
    parts: list[bytes] = []
    for name in sorted(archive.namelist()):
        if name == "signature.json":
            continue
        parts.append(name.encode("utf-8"))
        parts.append(archive.read(name))
    return b"\x00".join(parts)
