"""
The experiment folder: immutable manifest, append-only results, resume.

Layout (artifacts/opus360/<experiment_id>/):

    manifest.json            written once; never rewritten
    state.json               cumulative spend / progress (rewritten atomically)
    case_results.jsonl       one line per completed turn (append-only, fsync'd)
    events.jsonl             harness events (append-only)
    errors.jsonl             harness errors (append-only)
    run.log                  human-readable progress
    evidence/<phase>/<case>/attempt-<n>/*.json(.gz)
    calls/                   gzipped request payloads of every model call
    runtime/                 the isolated CreditProbe runtime (state DB, logs)
    owner.json               PID + start time + command + cwd of the owning process

A turn is "completed" when its line is in case_results.jsonl AND the evidence
checksum recorded on that line still matches the files on disk. On --resume,
completed turns are skipped; nothing is ever overwritten.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cert.safe_io import append_jsonl, read_jsonl, write_json_atomic, write_text_atomic


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def new_experiment_id(suite: str, live: bool) -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{suite}-{'live' if live else 'dry'}-{stamp}"


class Experiment:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.manifest_path = root / "manifest.json"
        self.state_path = root / "state.json"
        self.results_path = root / "case_results.jsonl"
        self.events_path = root / "events.jsonl"
        self.errors_path = root / "errors.jsonl"
        self.log_path = root / "run.log"
        self.evidence_root = root / "evidence"
        self.calls_root = root / "calls"
        self.runtime_dir = root / "runtime"

    # -- lifecycle -------------------------------------------------------------
    def create(self, manifest: dict[str, Any]) -> None:
        if self.manifest_path.exists():
            raise FileExistsError(f"{self.manifest_path} exists; experiments are immutable. Use --resume.")
        self.root.mkdir(parents=True, exist_ok=False)
        manifest = dict(manifest)
        manifest["manifest_written_at"] = now_iso()
        write_json_atomic(self.manifest_path, manifest)
        os.chmod(self.manifest_path, 0o444)
        self.save_state({"cumulative_usd": 0.0, "turns_completed": 0, "started_at": now_iso(),
                         "sessions": []})

    def manifest(self) -> dict[str, Any]:
        return json.loads(self.manifest_path.read_text(encoding="utf-8"))

    def state(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return {}
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    def save_state(self, state: dict[str, Any]) -> None:
        write_json_atomic(self.state_path, state)

    def claim_ownership(self, argv: list[str]) -> dict[str, Any]:
        from cert.procinfo import start_time

        owner = {"pid": os.getpid(), "started_at": start_time(os.getpid()) or time.time(),
                 "claimed_iso": now_iso(),
                 "command": " ".join([sys.executable] + argv), "cwd": os.getcwd(),
                 "experiment_root": str(self.root)}
        write_json_atomic(self.root / "owner.json", owner)
        return owner

    # -- append-only records ---------------------------------------------------------
    def log(self, line: str, *, echo: bool = True) -> None:
        stamp = datetime.now(UTC).strftime("%H:%M:%S")
        text = f"[{stamp}] {line}"
        with open(self.log_path, "a", encoding="utf-8") as fh:
            fh.write(text + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        if echo:
            print(text, flush=True)

    def event(self, kind: str, **fields: Any) -> None:
        append_jsonl(self.events_path, {"at": now_iso(), "kind": kind, **fields})

    def error(self, where: str, detail: str, **fields: Any) -> None:
        append_jsonl(self.errors_path, {"at": now_iso(), "where": where, "detail": detail[:4000], **fields})

    # -- evidence ---------------------------------------------------------------------
    def evidence_dir(self, phase: str, case_id: str, attempt: int) -> Path:
        path = self.evidence_root / phase / case_id / f"attempt-{attempt}"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def checksum_dir(path: Path) -> str:
        digest = hashlib.sha256()
        for f in sorted(p for p in path.rglob("*") if p.is_file()):
            digest.update(str(f.relative_to(path)).encode("utf-8"))
            digest.update(f.read_bytes())
        return digest.hexdigest()

    def write_evidence(self, phase: str, case_id: str, attempt: int, files: dict[str, Any]) -> tuple[Path, str]:
        d = self.evidence_dir(phase, case_id, attempt)
        for name, obj in files.items():
            write_json_atomic(d / f"{name}.json", obj)
        return d, self.checksum_dir(d)

    def record_result(self, row: dict[str, Any]) -> None:
        append_jsonl(self.results_path, row)

    def results(self) -> list[dict[str, Any]]:
        return read_jsonl(self.results_path)

    def completed(self, phase: str) -> dict[str, dict[str, Any]]:
        """Turns whose evidence still verifies. A tampered or missing one is NOT completed."""
        done: dict[str, dict[str, Any]] = {}
        for row in self.results():
            if row.get("phase") != phase or row.get("record_type") != "turn":
                continue
            ev = Path(row.get("evidence_dir") or "")
            ok = ev.exists() and self.checksum_dir(ev) == row.get("evidence_sha256")
            if ok:
                done[row["case_id"]] = row
            else:
                self.error("resume", f"evidence checksum failed for {row.get('case_id')}; the turn will be re-run",
                           case_id=row.get("case_id"))
        return done

    def write_checksums(self) -> Path:
        lines = []
        for f in sorted(p for p in self.root.rglob("*") if p.is_file()):
            if f.name == "checksums.sha256" or "/runtime/" in str(f):
                continue
            h = hashlib.sha256(f.read_bytes()).hexdigest()
            lines.append(f"{h}  {f.relative_to(self.root)}")
        path = self.root / "checksums.sha256"
        write_text_atomic(path, "\n".join(lines) + "\n")
        return path
