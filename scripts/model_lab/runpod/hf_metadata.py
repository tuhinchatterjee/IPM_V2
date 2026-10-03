"""
Exact-revision metadata integrity for pinned models in the persistent
Hugging Face caches, checked BEFORE any server start.

Live evidence (RTX PRO 6000 Pod): the snapshots of Ministral-3-8B
@5b26027e, Qwen3.5-4B @851bf6e8 and Qwen3.5-9B @c2022362 held a config.json
that vLLM/Transformers could not parse ("JSONDecodeError: Expecting value:
line 1 column 1" / "config.json is not a valid JSON file"). The weights were
not shown to be bad, so only the small metadata is checked and repaired.

For every pinned repository@revision, in each persistent cache (HF_HUB_CACHE
and vLLM's MODEL_CACHE_DIR) that holds that snapshot:

  * every critical metadata file present in snapshots/<revision>/ must
    exist, be non-empty, be UTF-8, and (JSON files) parse to a JSON object;
    when the pinned Hub listing gives the git blob id, the content must hash
    to it (proof it is that revision's file, not merely that path);
  * a failure is recorded as CACHE_METADATA_CORRUPT (repository, exact
    revision, path, byte size, failure), and ONLY that file is downloaded
    again for the SAME revision (force_download; never "main", never another
    revision or repository); then it is validated again;
  * success is CACHE_METADATA_REPAIRED (old/new status, revision unchanged);
    otherwise the model stops with MODEL_METADATA_CORRUPT and the roster
    continues.

VALIDITY IS DECIDED BY CONTENT READ THROUGH THE PATH, never by link
metadata: on the RunPod Global Volume (fuse.geesefs) a symlink's own lstat
reports st_size 0 while the target blob is complete, so every entry records
its kind (regular / symlink / missing), the raw link target, the resolved
target (which must stay inside that repository's cache), link_metadata_size
and resolved_content_size (bytes actually read).

REPAIR goes through a Pod-local staging cache: hf_hub_download(revision=<pin>)
fetches the one file there; its blob name (the Hub etag) must equal the git
blob id / LFS sha256 of the bytes (and the pinned listing's blob id when
known); only then is the persistent blobs/<etag> written (an existing valid
blob is never rewritten) and the snapshot entry re-linked to it. Nothing is
guessed and the revision cannot change.

Weight blobs are never deleted or re-downloaded here. Results are appended
to <runtime>/cache_integrity/<profile>.json on the persistent volume.
Standard library only; the default downloader runs huggingface_hub's
hf_hub_download inside the Pod-local vLLM environment.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

#: Weight / large binary files: never read or touched by this module.
WEIGHT_SUFFIXES = (".safetensors", ".bin", ".pt", ".pth", ".gguf", ".h5",
                   ".msgpack", ".onnx", ".ckpt")
#: Small runtime metadata validated by content (any of these present in the
#: exact snapshot): JSON must parse to an object, text must be non-empty
#: UTF-8, other tokenizer files must be non-empty.
JSON_SUFFIX, TEXT_SUFFIXES = ".json", (".jinja", ".txt")
BINARY_METADATA = ("tokenizer.model", "spiece.model", "tekken.json")
CRITICAL_JSON = ("config.json", "generation_config.json",
                 "tokenizer_config.json", "special_tokens_map.json",
                 "preprocessor_config.json", "processor_config.json",
                 "video_preprocessor_config.json", "params.json",
                 "tokenizer.json", "model.safetensors.index.json")
CRITICAL_TEXT = ("chat_template.jinja",)
CRITICAL = CRITICAL_JSON + CRITICAL_TEXT
SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def is_metadata(name: str) -> bool:
    if name.startswith(".") or name.endswith(WEIGHT_SUFFIXES):
        return False
    return (name.endswith(JSON_SUFFIX) or name.endswith(TEXT_SUFFIXES)
            or name in BINARY_METADATA or name.endswith(".tiktoken"))


CACHE_METADATA_CORRUPT = "CACHE_METADATA_CORRUPT"
CACHE_METADATA_REPAIRED = "CACHE_METADATA_REPAIRED"
MODEL_METADATA_CORRUPT = "MODEL_METADATA_CORRUPT"

#: downloader(repository, revision, filename, cache_dir) -> local path
Downloader = Callable[[str, str, str, Path], str]


def snapshot(cache: Path, repo: str, revision: str) -> Path:
    return cache / f"models--{repo.replace('/', '--')}" / "snapshots" / \
        revision


def git_blob_sha1(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()  # noqa: S324


def _inside(child: Path, parent: Path) -> bool:
    c, p = child.resolve(), parent.resolve()
    return c == p or p in c.parents


def validate_file(path: Path, expected_blob: str | None = None,
                  repo_root: Path | None = None) -> dict[str, Any]:
    """Validate ONE snapshot entry by the bytes read through it.

    Records kind, raw link target, resolved target, link_metadata_size
    (lstat; 0 for symlinks on geesefs and NOT used for validity) and
    resolved_content_size (what was actually read)."""
    name = path.name
    rec: dict[str, Any] = {"file": name, "path": str(path), "ok": False,
                           "kind": "missing", "link_target": None,
                           "resolved": None, "link_metadata_size": None,
                           "resolved_content_size": None}
    try:
        st = os.lstat(path)
    except OSError:
        return rec | {"failure": "missing"}
    rec["link_metadata_size"] = st.st_size
    if stat.S_ISLNK(st.st_mode):
        rec["kind"] = "symlink"
        rec["link_target"] = os.readlink(path)
        target = (path.parent / rec["link_target"]).resolve()
        rec["resolved"] = str(target)
        if repo_root is not None and not _inside(target, repo_root):
            return rec | {"failure": f"symlink escapes the repository cache "
                                     f"({rec['link_target']})"}
        if not target.exists():
            return rec | {"failure": "dangling symlink (target blob "
                                     "missing)"}
        if not target.is_file():
            return rec | {"failure": "symlink target is not a file"}
    elif stat.S_ISREG(st.st_mode):
        rec["kind"] = "regular"
        rec["resolved"] = str(path)
    else:
        return rec | {"kind": "other", "failure": "not a file or symlink"}
    try:
        with open(path, "rb") as f:         # through the link, by content
            data = f.read()
    except OSError as exc:
        return rec | {"failure": f"read failed: {exc}"}
    rec["resolved_content_size"] = len(data)
    rec["bytes"] = len(data)
    if not data:
        return rec | {"failure": "empty content (0 bytes read)"}
    if name in BINARY_METADATA and not name.endswith(JSON_SUFFIX):
        pass                                 # non-empty is all we can say
    else:
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            return rec | {"failure": f"not UTF-8 ({exc.reason} at byte "
                                     f"{exc.start})"}
        if name.endswith(JSON_SUFFIX):
            try:
                obj = json.loads(text)
            except ValueError as exc:
                return rec | {"failure": f"invalid JSON: {exc}"}
            if not isinstance(obj, dict):
                return rec | {"failure": f"JSON {type(obj).__name__}, not "
                                         f"an object"}
        elif not text.strip():
            return rec | {"failure": "blank text"}
    if expected_blob:
        got = (git_blob_sha1(data) if len(expected_blob) == 40 else
               hashlib.sha256(data).hexdigest())
        rec["revision_check"] = ("blob id matches the pinned revision"
                                 if got == expected_blob else
                                 f"blob id {got} != {expected_blob}")
        if got != expected_blob:
            return rec | {"failure": "content is not this revision's file "
                                     "(blob id mismatch)"}
    else:
        rec["revision_check"] = "path snapshots/<revision> (no blob id)"
    return rec | {"ok": True}


def check(repo: str, revision: str, caches: list[Path],
          expected: dict[str, str] | None = None) -> dict[str, Any]:
    """Validate every small metadata entry present in each cache's exact
    snapshot (by content). A cache without the snapshot is simply absent
    (the server downloads it at the pinned revision)."""
    expected = expected or {}
    out: dict[str, Any] = {"repository": repo, "revision": revision,
                           "snapshots": [], "files": [], "bad": []}
    for cache in caches:
        snap = snapshot(cache, repo, revision)
        if not snap.is_dir():
            continue
        out["snapshots"].append(str(snap))
        root = snap.parents[1]
        for f in sorted(snap.rglob("*")):
            if not (f.is_symlink() or f.is_file()) or \
                    not is_metadata(f.name):
                continue
            rel = str(f.relative_to(snap))
            r = validate_file(f, expected.get(rel), root) | {
                "cache": str(cache), "file": rel}
            out["files"].append(r)
            if not r["ok"]:
                out["bad"].append(r)
    out["status"] = ("ABSENT" if not out["snapshots"] else
                     "VALID" if not out["bad"] else CACHE_METADATA_CORRUPT)
    return out


def _etag_ok(etag: str, data: bytes) -> bool:
    if len(etag) == 40:
        return git_blob_sha1(data) == etag
    if len(etag) == 64:
        return hashlib.sha256(data).hexdigest() == etag
    return False


def materialise(repo: str, revision: str, filename: str, staged: Path,
                cache: Path, expected_blob: str | None = None
                ) -> dict[str, Any]:
    """Put one verified file into the persistent cache, HF layout:
    blobs/<etag> (written only if absent or invalid -- a valid blob is never
    rewritten) and snapshots/<revision>/<filename> -> ../../blobs/<etag>.
    The staged file must be the exact-revision download: its blob name
    (etag) must hash-match its bytes, and equal the pinned listing's id when
    known. Returns {"ok", "etag", "blob", "linked", "error"}."""
    staged = Path(staged)
    if f"/snapshots/{revision}/" not in str(staged).replace(os.sep, "/"):
        return {"ok": False, "error": f"staged file {staged} is not from "
                                      f"snapshots/{revision}"}
    resolved = staged.resolve()
    etag = resolved.name if resolved.parent.name == "blobs" else None
    data = staged.read_bytes()
    if not etag or not _etag_ok(etag, data):
        return {"ok": False, "error": f"staged blob identity not verified "
                                      f"(etag {etag!r})"}
    if expected_blob and etag != expected_blob:
        return {"ok": False, "error": f"staged blob {etag} != pinned "
                                      f"{expected_blob}"}
    root = cache / f"models--{repo.replace('/', '--')}"
    blob = root / "blobs" / etag
    blob.parent.mkdir(parents=True, exist_ok=True)
    wrote = False
    if not (blob.is_file() and _etag_ok(etag, blob.read_bytes())):
        tmp = blob.with_name(f".{etag}.part")
        tmp.write_bytes(data)
        os.replace(tmp, blob)
        wrote = True
    entry = root / "snapshots" / revision / filename
    entry.parent.mkdir(parents=True, exist_ok=True)
    if entry.is_symlink() or entry.exists():
        entry.unlink()                       # only this metadata entry
    rel = os.path.relpath(blob, entry.parent)
    try:
        os.symlink(rel, entry)
        linked = "symlink"
    except OSError:                          # a cache without symlinks
        entry.write_bytes(data)
        linked = "copy"
    return {"ok": True, "etag": etag, "blob": str(blob),
            "blob_written": wrote, "linked": linked}


def hub_downloader(python: str) -> Downloader:
    """hf_hub_download(revision=<pin>, force_download=True) of ONE file
    into the given (Pod-local staging) cache, inside the given Python (the
    Pod-local vLLM venv). Returns the staged snapshot path."""
    code = ("import sys\nfrom huggingface_hub import hf_hub_download\n"
            "print(hf_hub_download(repo_id=sys.argv[1], revision=sys.argv[2],"
            " filename=sys.argv[3], cache_dir=sys.argv[4], "
            "force_download=True))\n")

    def download(repo: str, revision: str, filename: str, cache: Path
                 ) -> str:
        p = subprocess.run([python, "-c", code, repo, revision, filename,
                            str(cache)], capture_output=True, text=True,
                           timeout=600)
        if p.returncode != 0:
            raise RuntimeError((p.stderr or p.stdout)[-600:])
        return p.stdout.strip().splitlines()[-1]
    return download


def staging_dir() -> Path:
    """A Pod-local (normal filesystem) cache for the one-file downloads."""
    base = os.environ.get("CREDITPROBE_APP_ROOT") or tempfile.gettempdir()
    d = Path(base) / "cache" / "hf_staging"
    d.mkdir(parents=True, exist_ok=True)
    return d


def ensure(pid: str, repo: str, revision: str, caches: list[Path], *,
           downloader: Downloader, expected: dict[str, str] | None = None,
           runtime: Path | None = None, staging: Path | None = None
           ) -> dict[str, Any]:
    """Check, repair only the broken files at the exact revision, re-check.
    Returns status VALID / ABSENT / CACHE_METADATA_REPAIRED /
    MODEL_METADATA_CORRUPT with the evidence."""
    result: dict[str, Any] = {"profile_id": pid, "repository": repo,
                              "revision": revision, "events": [],
                              "checked_at": time.strftime(
                                  "%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    if not repo or not revision or not SHA_RE.match(revision):
        result |= {"status": MODEL_METADATA_CORRUPT,
                   "detail": f"no immutable pinned revision ({revision!r}); "
                             f"metadata is never fetched from a branch"}
        return _record(runtime, pid, result)
    first = check(repo, revision, caches, expected)
    result["before"] = first
    if first["status"] in ("VALID", "ABSENT"):
        result["status"] = first["status"]
        return _record(runtime, pid, result)
    for bad in first["bad"]:
        result["events"].append({
            "event": CACHE_METADATA_CORRUPT, "repository": repo,
            "revision": revision, "path": bad["path"], "kind": bad["kind"],
            "link_target": bad.get("link_target"),
            "link_metadata_size": bad.get("link_metadata_size"),
            "resolved_content_size": bad.get("resolved_content_size"),
            "bytes": bad.get("resolved_content_size"),
            "failure": bad["failure"]})
    repaired_files: list[str] = []
    stage = staging or staging_dir()
    for bad in first["bad"]:
        cache = Path(bad["cache"])
        try:
            got = downloader(repo, revision, bad["file"], stage)
        except Exception as exc:  # noqa: BLE001
            result["events"].append({"event": "REPAIR_DOWNLOAD_FAILED",
                                     "file": bad["file"],
                                     "error": str(exc)[:400]})
            continue
        m = materialise(repo, revision, bad["file"], Path(got), cache,
                        (expected or {}).get(bad["file"]))
        if not m["ok"]:
            result["events"].append({
                "event": "REPAIR_REFUSED", "file": bad["file"],
                "error": m["error"]})
            continue
        result["events"].append({"event": "REPAIR_MATERIALISED",
                                 "file": bad["file"]} | m)
        repaired_files.append(bad["file"])
    after = check(repo, revision, caches, expected)
    result["after"] = after
    if after["status"] in ("VALID", "ABSENT"):
        result["events"].append({
            "event": CACHE_METADATA_REPAIRED, "repository": repo,
            "revision": revision, "files": repaired_files,
            "old_status": first["status"], "new_status": after["status"],
            "revision_unchanged": True})
        result["status"] = CACHE_METADATA_REPAIRED
    else:
        result["status"] = MODEL_METADATA_CORRUPT
        result["detail"] = "; ".join(f"{b['path']}: {b['failure']}"
                                     for b in after["bad"])[:600]
    return _record(runtime, pid, result)


def _record(runtime: Path | None, pid: str, result: dict[str, Any]
            ) -> dict[str, Any]:
    if runtime is not None:
        d = runtime / "cache_integrity"
        d.mkdir(parents=True, exist_ok=True)
        p = d / f"{pid}.json"
        hist = json.loads(p.read_text()) if p.exists() else []
        hist = (hist if isinstance(hist, list) else [])[-49:] + [result]
        tmp = d / f".{pid}.json.part"
        tmp.write_text(json.dumps(hist, indent=1, default=str))
        os.replace(tmp, p)             # no chmod (geesefs)
    return result


def expected_blob_ids(info: dict[str, Any]) -> dict[str, str]:
    """{metadata file: blob id} from a Hub model listing at the pinned
    revision (`api/models/<repo>/revision/<sha>?blobs=true`): the git blob
    id for regular files, the LFS sha256 for LFS-stored ones."""
    out = {}
    for s in info.get("siblings") or []:
        name = s.get("rfilename") or ""
        if not is_metadata(Path(name).name):
            continue
        if (s.get("lfs") or {}).get("sha256"):
            out[name] = s["lfs"]["sha256"]
        elif s.get("blobId"):
            out[name] = s["blobId"]
    return out
