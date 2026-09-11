#!/usr/bin/env python3
"""
A read-only probe of the WHATIF_5318 installation, to run ON THE USER'S MAC.

What this closes
----------------
`docs/RETAIL_SOURCE_PROVENANCE.md` §2.3 names five things that could not be
established from a cloud container: the launcher file itself, `git rev-parse
HEAD` inside that worktree, whether it is dirty, whether the frontend it serves
is a live dev server or a stale bundle, and the paths it writes to. WHATIF_5318
is not a ref in this repository — the token appears in no file at any branch or
tag — so the question can only be answered on the machine that holds it.

This answers all five, and nothing else.

What it will not do, by construction
------------------------------------
* **It never runs the launcher.** Not `bash`, not `source`, not `open`. A
  launcher is read as text. Executing one to discover what it does would start
  a frozen presentation, bind its ports and possibly write to its database.
* **It never prints a value from an environment file.** Variable NAMES only.
  A provider key, a database password and a connection string are all values,
  and an evidence file is a thing that gets attached to an email.
* **It never changes Git state.** `rev-parse`, `status --porcelain`,
  `describe` and `log -1` only. No checkout, no fetch, no stash, no gc — a
  frozen worktree must be exactly as frozen after this runs as before.
* **It never reads outside the directory it is given.** No home-directory
  sweep, no Spotlight query, no scan of unrelated personal files.
* **It never touches a database.** Not to connect, not to list, not to migrate.
* **It kills no process.** It reports what is listening on a port by asking
  `lsof` for that port alone.

Usage, on the Mac, from anywhere:

    python3 local_probe.py /path/to/WHATIF_5318

It writes `whatif5318_probe.json` next to itself and prints a summary. Read the
summary before sending the file: it is designed to be safe to send, and you are
the last check on that.
"""

from __future__ import annotations

import hashlib
import json
import platform
import re
import subprocess
import sys
from pathlib import Path

#: Launcher filenames worth reporting, read as text and never executed.
LAUNCHER_NAMES = ("*.command", "start*.sh", "run*.sh", "launch*.sh", "Makefile")

#: Files whose NAMES of variables are reported, never their values.
ENV_NAMES = (".env", ".env.local", ".env.retail", ".env.production")

#: What a launcher might reveal without giving anything away: a port, a host,
#: a relative path. Never a credential, and never a full URL with one in it.
PORT = re.compile(r"\b(?:PORT|port)\s*[=:]\s*(\d{2,5})\b")
URL_HOST = re.compile(r"https?://([A-Za-z0-9.\-]+)(?::(\d{1,5}))?")


def run(args: list[str], cwd: Path | None = None) -> tuple[int, str]:
    """A bounded, read-only command. Never a shell, so nothing is interpolated."""
    try:
        done = subprocess.run(args, cwd=str(cwd) if cwd else None,
                              capture_output=True, text=True, timeout=30)
        return done.returncode, (done.stdout or done.stderr).strip()
    except FileNotFoundError:
        return 127, f"{args[0]} is not installed"
    except subprocess.TimeoutExpired:
        return 124, "timed out"


def git_state(root: Path) -> dict:
    """Everything about the worktree's Git state, changing none of it."""
    if not (root / ".git").exists():
        return {"is_git_worktree": False}
    out: dict = {"is_git_worktree": True}
    for key, args in (
        ("head", ["git", "rev-parse", "HEAD"]),
        ("branch", ["git", "rev-parse", "--abbrev-ref", "HEAD"]),
        ("describe", ["git", "describe", "--always", "--tags"]),
        ("remote", ["git", "remote", "get-url", "origin"]),
        ("last_commit", ["git", "log", "-1", "--format=%H %ci %s"]),
    ):
        code, text = run(args, root)
        out[key] = text if code == 0 else None
    code, text = run(["git", "status", "--porcelain"], root)
    if code == 0:
        lines = [line for line in text.splitlines() if line.strip()]
        out["is_dirty"] = bool(lines)
        out["changed_file_count"] = len(lines)
        # Paths, not contents, and only the first twenty: a long list of
        # personal scratch files is noise, not evidence.
        out["changed_paths"] = [line[3:] for line in lines[:20]]
    # Is the recovery tag this repository's provenance anchor an ancestor?
    for tag in ("recovered-sep8-whatif", "0558f267b1c9d0eb3583cf329aed817d3aa0e15d"):
        code, _ = run(["git", "merge-base", "--is-ancestor", tag, "HEAD"], root)
        out.setdefault("ancestors", {})[tag] = (code == 0)
    return out


def launchers(root: Path) -> list[dict]:
    """Every launcher, READ as text. None is executed."""
    found: list[dict] = []
    seen: set[Path] = set()
    for pattern in LAUNCHER_NAMES:
        for path in sorted(root.glob(pattern)) + sorted(root.glob(f"launchers/**/{pattern}")):
            if path in seen or not path.is_file():
                continue
            seen.add(path)
            try:
                text = path.read_text(errors="replace")
            except OSError as e:
                found.append({"path": str(path.relative_to(root)), "unreadable": str(e)})
                continue
            hosts = sorted({h for h, _ in URL_HOST.findall(text)})
            ports = sorted({p for p in PORT.findall(text)}
                           | {p for _, p in URL_HOST.findall(text) if p})
            found.append({
                "path": str(path.relative_to(root)),
                "bytes": path.stat().st_size,
                "sha256": hashlib.sha256(text.encode()).hexdigest()[:16],
                "executable": bool(path.stat().st_mode & 0o111),
                "lines": len(text.splitlines()),
                # What it would bind, without running it.
                "hosts_mentioned": hosts,
                "ports_mentioned": ports,
                "mentions_dev_server": bool(re.search(r"\b(next dev|npm run dev|vite)\b", text)),
                "mentions_built_bundle": bool(re.search(r"\b(next start|npm run start|serve -s|dist/)\b", text)),
                "env_files_sourced": sorted(set(re.findall(r"\.env[\w.]*", text))),
            })
    return found


def env_variable_names(root: Path) -> dict[str, list[str]]:
    """The NAMES in each environment file. Never a value, not even a redacted one."""
    out: dict[str, list[str]] = {}
    for name in ENV_NAMES:
        path = root / name
        if not path.is_file():
            continue
        names: list[str] = []
        try:
            for line in path.read_text(errors="replace").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key = line.split("=", 1)[0].strip().removeprefix("export ").strip()
                if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
                    names.append(key)
        except OSError as e:
            out[name] = [f"<unreadable: {e}>"]
            continue
        out[name] = sorted(set(names))
    return out


def listening(ports: list[int]) -> dict[str, str]:
    """What holds each named port. One port at a time; nothing is signalled."""
    out: dict[str, str] = {}
    for port in ports:
        code, text = run(["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"])
        if code == 127:
            out[str(port)] = "lsof is not installed"
            continue
        lines = [line for line in text.splitlines()[1:] if line.strip()]
        # The command name and pid only. A full argv can carry a database URL
        # with a password in it.
        out[str(port)] = ("free" if not lines else
                          "; ".join(" ".join(line.split()[:2]) for line in lines[:3]))
    return out


def readiness() -> dict:
    """What the machine has, for the launch that is still NOT RUN."""
    out = {"platform": platform.platform(), "machine": platform.machine(),
           "python": sys.version.split()[0]}
    for key, args in (("node", ["node", "--version"]),
                      ("npm", ["npm", "--version"]),
                      ("git", ["git", "--version"])):
        code, text = run(args)
        out[key] = text.splitlines()[0] if code == 0 else None
    return out


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        print("error: give the path to the WHATIF_5318 installation directory.")
        return 2
    root = Path(sys.argv[1]).expanduser().resolve()
    if not root.is_dir():
        print(f"error: {root} is not a directory. Nothing was read.")
        return 2

    found_launchers = launchers(root)
    ports = sorted({int(p) for entry in found_launchers
                    for p in entry.get("ports_mentioned", []) if p.isdigit()})

    report = {
        "probe_version": "1.0.0",
        "read_only": True,
        "installation": str(root),
        "exists": True,
        "git": git_state(root),
        "launchers": found_launchers,
        "environment_variable_names": env_variable_names(root),
        "ports_mentioned_by_launchers": ports,
        "listening": listening(ports[:8]),
        "readiness": readiness(),
        "not_done": [
            "No launcher was executed, sourced or opened.",
            "No environment VALUE was read or recorded — names only.",
            "No Git state was changed: no checkout, fetch, stash or gc.",
            "No database was contacted.",
            "No process was signalled or stopped.",
            "Nothing outside the given directory was read.",
        ],
    }

    out = Path(__file__).resolve().parent / "whatif5318_probe.json"
    out.write_text(json.dumps(report, indent=2))

    git = report["git"]
    print()
    print(f"  Installation   {root}")
    if git.get("is_git_worktree"):
        print(f"  HEAD           {git.get('head')}")
        print(f"  Branch         {git.get('branch')}")
        print(f"  Describe       {git.get('describe')}")
        print(f"  Remote         {git.get('remote')}")
        print(f"  Dirty          {git.get('is_dirty')} "
              f"({git.get('changed_file_count', 0)} changed)")
        for tag, yes in (git.get("ancestors") or {}).items():
            print(f"  Contains {tag[:28]:28s} {yes}")
    else:
        print("  Not a Git worktree — so it was not checked out from this "
              "repository, or the .git directory is elsewhere.")
    print(f"  Launchers      {len(found_launchers)}")
    for entry in found_launchers:
        serves = ("dev server" if entry.get("mentions_dev_server")
                  else "built bundle" if entry.get("mentions_built_bundle")
                  else "unclear")
        print(f"    {entry['path']}  ports={entry.get('ports_mentioned')}  "
              f"serves={serves}")
    print(f"  Ports          {report['listening']}")
    print(f"  Node           {report['readiness'].get('node')}")
    print()
    print(f"  Written to {out}")
    print("  It contains no secret value. Read it before sending it anyway.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
