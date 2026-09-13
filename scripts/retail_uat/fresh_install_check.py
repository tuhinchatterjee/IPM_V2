"""A fresh retail installation, checked the way a person would find it broken.

What this reproduces
--------------------
A Mac pulled the commit that shipped the Early Warning Score, ran the
bootstrap, and got "The retail installation is ready to demonstrate." while the
Early Warning screen read "The Early Warning Score domain could not be read":
the running server exposed no `/retail/ews/*` route, and its governed catalogue
held one dataset where the file on disk held five.

Nothing on disk was wrong. Every check was about files. So this walks the whole
installation path on a database and a metadata directory of its own, and then
asks the APPLICATION the questions that were never asked:

    1. an isolated database, created here and dropped at the end
    2. the retail migrations, run against it
    3. an empty metadata directory — no catalogue at all to begin with
    4. the retail bootstrap, which must register the domain into it
    5. the runtime governed catalogue, read from a process that started
       BEFORE the bootstrap wrote the file
    6. the production FastAPI application's own OpenAPI document
    7. the Early Warning endpoints, called and read
    8. the readiness check, which must now pass — and must fail when a
       server serving older code is in front of it

The analytics lake is READ, not rebuilt. The book is the installation's data,
a fresh install does not generate a different one, and regenerating it here
would test the seeder rather than the wiring that broke.

Run:

    set -a && . ./.env.retail && set +a
    .venv/bin/python scripts/retail_uat/fresh_install_check.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FRESH_DB = "creditprobe_retail_freshcheck"

PASS, FAIL = "PASS", "FAIL"
results: list[tuple[str, str, str]] = []


def step(name: str, ok: bool, detail: str = "") -> bool:
    results.append((name, PASS if ok else FAIL, detail))
    print(f"{PASS if ok else FAIL}  {name}" + (f" — {detail}" if detail else ""),
          flush=True)
    return ok


def _admin_url(url: str) -> str:
    return url.rsplit("/", 1)[0] + "/postgres"


def _run(argv: list[str], env: dict[str, str], timeout: int = 3600):
    return subprocess.run(argv, cwd=str(ROOT), env=env, capture_output=True,
                          text=True, timeout=timeout)


def main() -> int:
    import sqlalchemy as sa

    base_url = os.environ.get("DATABASE_URL")
    if not base_url:
        print("DATABASE_URL is not set; source .env.retail first")
        return 2

    fresh_url = base_url.rsplit("/", 1)[0] + "/" + FRESH_DB
    admin = sa.create_engine(_admin_url(base_url), isolation_level="AUTOCOMMIT")

    workspace = Path(tempfile.mkdtemp(prefix="retail-fresh-"))
    metadata_dir = workspace / "metadata" / "retail"
    metadata_dir.mkdir(parents=True)

    env = {**os.environ,
           "DATABASE_URL": fresh_url,
           "METADATA_DIR": str(metadata_dir)}

    try:
        # --- 1. an isolated database
        with admin.connect() as c:
            c.execute(sa.text(f'DROP DATABASE IF EXISTS "{FRESH_DB}"'))
            c.execute(sa.text(f'CREATE DATABASE "{FRESH_DB}"'))
        step("an isolated database is created", True, FRESH_DB)

        # --- 2. the retail migrations
        done = _run([".venv/bin/python", "-m", "alembic", "upgrade", "head"], env)
        if not step("the retail migrations run", done.returncode == 0,
                    (done.stderr or done.stdout).strip().splitlines()[-1]
                    if done.returncode else ""):
            return 1

        # --- 3. the state a machine is in after the book is built and
        #        before the bootstrap has run: the canonical book in the
        #        catalogue, and nothing else. `build_retail_demo.py` writes
        #        exactly this; the derived views and the Early Warning Score
        #        domain are the bootstrap's job, which is what is under test.
        catalogue = metadata_dir / "catalog.json"
        shipped = json.loads(
            (ROOT / "metadata" / "retail" / "catalog.json").read_text())
        shipped["datasets"] = [d for d in (shipped.get("datasets") or [])
                               if str(d.get("name")) == "retail_facility_month"]
        catalogue.write_text(json.dumps(shipped, indent=1))
        step("the installation starts without the Early Warning Score domain",
             "retail_ews_score" not in catalogue.read_text(), str(catalogue))

        # --- 3a. a process that starts BEFORE the bootstrap, the way a
        #         backend already running on the machine does.
        early = _run([".venv/bin/python", "-c", (
            "from backend.data_access.catalog import get_catalog;"
            "print(len(list(get_catalog().names())))")], env)
        step("a process started before the bootstrap sees one dataset",
             early.returncode == 0 and early.stdout.strip().endswith("1"),
             early.stdout.strip().splitlines()[-1] if early.stdout else "")

        # --- 3b. the accounts. A fresh database has none, and the retail
        #         bootstrap does not create them: `scripts/seed_demo_users.py`
        #         does, and a fresh install runs it. Without this nobody can
        #         sign in, which readiness now says out loud rather than
        #         reporting an installation nobody can open as ready.
        done = _run([".venv/bin/python", "scripts/seed_demo_users.py"], env)
        step("the demonstration accounts are seeded", done.returncode == 0,
             (done.stdout or done.stderr).strip().splitlines()[-1]
             if (done.stdout or done.stderr).strip() else "")

        # --- 4. the bootstrap
        done = _run([".venv/bin/python",
                     "scripts/bootstrap_retail_installation.py"], env)
        # What the bootstrap could not finish. On a database this new, the
        # working-messages seeder has nobody to send to — that is a real gap
        # in the workspace seeder and it is not this one: nothing about it
        # touches the Early Warning Score. Anything that DOES is fatal here.
        residual = sorted({line.split("Still missing:", 1)[1].strip()
                           for line in (done.stdout + done.stderr).splitlines()
                           if "Still missing:" in line})
        theirs = [one for one in residual
                  if any(word in one.lower()
                         for word in ("ews", "early warning", "catalogue",
                                      "catalog", "domain", "score"))]
        if not step("the retail bootstrap leaves nothing about Early Warning "
                    "unfinished", not theirs and done.returncode in (0, 1),
                    "; ".join(theirs) if theirs else
                    ("unrelated, and reported: " + "; ".join(residual)
                     if residual else "")):
            print((done.stdout or "")[-4000:])
            print((done.stderr or "")[-4000:])
            return 1

        names = [str(d.get("name")) for d in
                 (json.loads(catalogue.read_text()).get("datasets") or [])
                 ] if catalogue.exists() else []
        step("the bootstrap wrote a governed catalogue holding the domain",
             "retail_ews_score" in names, ", ".join(sorted(names)))

        # --- 5, 6, 7, 8: everything the old readiness never asked.
        probe = _run([".venv/bin/python", "-c", (
            "import json;"
            "from backend.data_access.catalog import get_catalog;"
            "from backend.retail import readiness;"
            "app = readiness.production_app();"
            "print(json.dumps({"
            "  'catalogue': sorted(get_catalog().names()),"
            "  'missing_routes': readiness.missing_routes(app),"
            "  'ews_paths': sorted({p for _, p in readiness.routes_of(app)"
            "                       if '/retail/ews/' in p}),"
            "  'endpoints': readiness.check_endpoints_answer(app),"
            "  'readiness': readiness.check(live=False),"
            "}))")], env)
        payload = {}
        for line in reversed((probe.stdout or "").splitlines()):
            if line.startswith("{"):
                payload = json.loads(line)
                break
        if not payload:
            step("the application could be built and questioned", False,
                 (probe.stderr or "")[-400:])
            return 1

        step("the runtime catalogue holds the domain",
             "retail_ews_score" in payload["catalogue"],
             ", ".join(payload["catalogue"]))
        step("the production application routes every Early Warning endpoint",
             payload["missing_routes"] == [],
             f"{len(payload['ews_paths'])} paths"
             if not payload["missing_routes"]
             else ", ".join(payload["missing_routes"]))
        for path in payload["ews_paths"]:
            print(f"      {path}")
        step("the Early Warning endpoints answer and read the latest month",
             payload["endpoints"] == [], "; ".join(payload["endpoints"]))
        step("readiness passes on this installation",
             payload["readiness"] == [], "; ".join(payload["readiness"]))

        # --- and readiness must still be able to say no.
        stub = workspace / "stale_server_probe.py"
        stub.write_text(
            # The stub lives outside the repository, and Python puts the
            # SCRIPT's directory on the path rather than the working one.
            f"import sys; sys.path.insert(0, {str(ROOT)!r})\n"
            "import json, threading\n"
            "from http.server import BaseHTTPRequestHandler, HTTPServer\n"
            "from backend.retail import readiness\n"
            "\n"
            "class H(BaseHTTPRequestHandler):\n"
            "    def do_GET(self):\n"
            "        b = json.dumps({'paths': {'/api/v1/health': {'get': {}}}})\n"
            "        self.send_response(200)\n"
            "        self.send_header('Content-Type', 'application/json')\n"
            "        self.end_headers()\n"
            "        self.wfile.write(b.encode())\n"
            "    def log_message(self, *a):\n"
            "        pass\n"
            "\n"
            "s = HTTPServer(('127.0.0.1', 0), H)\n"
            "threading.Thread(target=s.serve_forever, daemon=True).start()\n"
            "said = readiness.check_live_server('http://127.0.0.1:%d'\n"
            "                                   % s.server_address[1])\n"
            "print(json.dumps(said))\n")
        refuse = _run([".venv/bin/python", str(stub)], env)
        said = [line for line in (refuse.stdout or "").splitlines()
                if line.startswith("[")]
        step("readiness REFUSES a server that is serving older code",
             bool(said) and said[-1] != "[]",
             (json.loads(said[-1])[0][:140] if said and said[-1] != "[]"
              else (refuse.stderr or "")[-200:]))

    finally:
        with admin.connect() as c:
            c.execute(sa.text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                f"WHERE datname = '{FRESH_DB}'"))
            c.execute(sa.text(f'DROP DATABASE IF EXISTS "{FRESH_DB}"'))
        import shutil

        shutil.rmtree(workspace, ignore_errors=True)

    failed = [one for one in results if one[1] == FAIL]
    print(f"\n{len(results) - len(failed)} of {len(results)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
