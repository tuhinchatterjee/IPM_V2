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
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

CRITICAL_JSON = ("config.json", "generation_config.json",
                 "tokenizer_config.json", "special_tokens_map.json",
                 "preprocessor_config.json", "processor_config.json",
                 "params.json", "tokenizer.json")
CRITICAL_TEXT = ("chat_template.jinja",)
CRITICAL = CRITICAL_JSON + CRITICAL_TEXT
SHA_RE = re.compile(r"^[0-9a-f]{40}$")

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


def validate_file(path: Path, expected_blob: str | None = None
                  ) -> dict[str, Any]:
    name = path.name
    rec: dict[str, Any] = {"file": name, "path": str(path), "ok": False}
    if path.is_symlink() and not path.exists():
        return rec | {"bytes": None, "failure": "dangling symlink (blob "
                      "missing)"}
    if not path.exists():
        return rec | {"bytes": None, "failure": "missing"}
    data = path.read_bytes()
    rec["bytes"] = len(data)
    if not data:
        return rec | {"failure": "empty file"}
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        return rec | {"failure": f"not UTF-8 ({exc.reason} at byte "
                                 f"{exc.start})"}
    if name in CRITICAL_JSON:
        try:
            obj = json.loads(text)
        except ValueError as exc:
            return rec | {"failure": f"invalid JSON: {exc}"}
        if not isinstance(obj, dict):
            return rec | {"failure": f"JSON {type(obj).__name__}, not an "
                                     f"object"}
    elif not text.strip():
        return rec | {"failure": "blank text"}
    if expected_blob:
        got = git_blob_sha1(data)
        rec["revision_check"] = ("git blob id matches the pinned revision"
                                 if got == expected_blob else
                                 f"git blob id {got} != {expected_blob}")
        if got != expected_blob:
            return rec | {"failure": "content is not this revision's file "
                                     "(git blob id mismatch)"}
    else:
        rec["revision_check"] = "path snapshots/<revision> (no blob id)"
    return rec | {"ok": True}


def check(repo: str, revision: str, caches: list[Path],
          expected: dict[str, str] | None = None) -> dict[str, Any]:
    """Validate every critical metadata file present in each cache's exact
    snapshot. A cache without the snapshot is simply absent (the server
    will download it at the pinned revision)."""
    expected = expected or {}
    out: dict[str, Any] = {"repository": repo, "revision": revision,
                           "snapshots": [], "files": [], "bad": []}
    for cache in caches:
        snap = snapshot(cache, repo, revision)
        if not snap.is_dir():
            continue
        out["snapshots"].append(str(snap))
        for name in CRITICAL:
            f = snap / name
            if not (f.exists() or f.is_symlink()):
                continue
            r = validate_file(f, expected.get(name)) | {"cache": str(cache)}
            out["files"].append(r)
            if not r["ok"]:
                out["bad"].append(r)
    out["status"] = ("ABSENT" if not out["snapshots"] else
                     "VALID" if not out["bad"] else CACHE_METADATA_CORRUPT)
    return out


def hub_downloader(python: str) -> Downloader:
    """hf_hub_download(force_download=True) of ONE file at ONE revision,
    inside the given Python (the Pod-local vLLM venv)."""
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


def ensure(pid: str, repo: str, revision: str, caches: list[Path], *,
           downloader: Downloader, expected: dict[str, str] | None = None,
           runtime: Path | None = None) -> dict[str, Any]:
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
            "revision": revision, "path": bad["path"],
            "bytes": bad["bytes"], "failure": bad["failure"]})
    repaired_files: list[str] = []
    for bad in first["bad"]:
        cache = Path(bad["cache"])
        try:
            got = downloader(repo, revision, bad["file"], cache)
        except Exception as exc:  # noqa: BLE001
            result["events"].append({"event": "REPAIR_DOWNLOAD_FAILED",
                                     "file": bad["file"],
                                     "error": str(exc)[:400]})
            continue
        if f"/snapshots/{revision}/" not in str(got).replace(os.sep, "/"):
            result["events"].append({
                "event": "REPAIR_REFUSED", "file": bad["file"],
                "error": f"downloader returned {got}, not snapshots/"
                         f"{revision}: the revision must not change"})
            continue
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
    """{critical file: git blob id} from a Hub model listing at the pinned
    revision (`api/models/<repo>/revision/<sha>?blobs=true`)."""
    out = {}
    for s in info.get("siblings") or []:
        name = s.get("rfilename")
        if name in CRITICAL and s.get("blobId") and not s.get("lfs"):
            out[name] = s["blobId"]
    return out
