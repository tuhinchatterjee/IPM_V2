# CreditProbe Tool — Deployment & Operations

Target host: a Windows PC on the office LAN. The app is served by **Waitress**
(production WSGI server) as a **single process, multi-threaded** — this is required
because the dataset lives in in-process globals/cache.

> Sections marked _(Phase 2+)_ are filled in as those phases land.

---

## 1. Prerequisites

- Python 3.14 (`python --version`)
- Git
- Dependencies installed: `python -m pip install -r requirements.txt`
  (developer machines can use `uv sync` instead once uv is on PATH)

## 2. Configuration

All configuration comes from environment variables (see `.env.example`). In
development, copy it to `.env`:

```
copy .env.example .env
```

Then edit `.env` and set at least `ANTHROPIC_API_KEY`. In **production the values
are injected by the NSSM service** (section 4) — no `.env` file is deployed.

Key variables: `ENV` (dev|prod), `HOST` (use `0.0.0.0` for LAN), `PORT`,
`ANTHROPIC_API_KEY`, `OLLAMA_BASE_URL`, `LOG_DIR`, `UPLOAD_DIR`, `MAX_UPLOAD_MB`.

## 3. Running

**Development** (Dash dev server, auto-debug):
```
python app.py
```

**Production** (Waitress):
```
set ENV=prod
set HOST=0.0.0.0
python serve.py
```

Health check (no auth): `http://<host>:<port>/healthz` returns JSON status.

## 4. Run as a Windows service (NSSM)

NSSM supervises the process: auto-start on boot, auto-restart on crash, log capture.
Chosen over Task Scheduler for the crash-restart and stdout/stderr capture.

Install NSSM: `choco install nssm` (or download from nssm.cc and put `nssm.exe` on PATH).

```
nssm install IPMTool "C:\QA\CreditProbe Tool\.venv\Scripts\python.exe" "C:\QA\CreditProbe Tool\serve.py"
nssm set IPMTool AppDirectory "C:\QA\CreditProbe Tool"
nssm set IPMTool AppEnvironmentExtra ENV=prod HOST=0.0.0.0 PORT=8050 ANTHROPIC_API_KEY=<new-key> OLLAMA_BASE_URL=http://localhost:11434
nssm set IPMTool AppStdout "C:\QA\CreditProbe Tool\logs\service-out.log"
nssm set IPMTool AppStderr "C:\QA\CreditProbe Tool\logs\service-err.log"
nssm set IPMTool AppExit Default Restart
nssm start IPMTool
```

> If you run from the system Python instead of a `.venv`, point the first argument
> at that `python.exe` (e.g. `C:\Users\...\Python\...\python.exe`).

Service control: `nssm restart IPMTool`, `nssm stop IPMTool`, `nssm status IPMTool`.

## 5. Firewall (LAN access)

Allow inbound TCP on the app port for the private/domain network profiles only:

```
netsh advfirewall firewall add rule name="CreditProbe Tool 8050" dir=in action=allow protocol=TCP localport=8050 profile=domain,private
```

Colleagues then reach the app at `http://<this-pc-ip>:8050`.

## 6. Update procedure

```
cd "C:\QA\CreditProbe Tool"
git pull
python -m pip install -r requirements.txt   # or: uv sync
nssm restart IPMTool
```

## 7. Secret rotation runbook

The Anthropic API key must be rotated whenever it may have been exposed (it was
committed in plaintext in an early prototype `.env`):

1. Anthropic console → create a new key, revoke the old one.
2. Update the service: `nssm set IPMTool AppEnvironmentExtra ... ANTHROPIC_API_KEY=<new-key>` (re-list the other vars too, as this replaces the set), then `nssm restart IPMTool`.
3. Dev machines: update `.env`.
4. Confirm the old key returns 401 and the app's AI chat still works.

## 8. Logs

Rotating application log: `logs/ipm.log` (10 MB × 5 files). Service stdout/stderr:
`logs/service-out.log` / `logs/service-err.log`. All are git-ignored.

## 9. Database (PostgreSQL)

PostgreSQL is the source of truth for portfolio data. Each uploaded (or the
bundled) workbook is one **dataset version**; sheets are stored as dtype-faithful
Parquet blobs, and exactly one version is `active`. The app keeps an in-process
cache in sync with the active version on every request.

**First-time setup**

1. Install PostgreSQL 16+ (installs as an auto-starting Windows service).
2. Create the role and database:
   ```sql
   CREATE ROLE ipm_app WITH LOGIN PASSWORD '<choose-a-password>';
   CREATE DATABASE ipm OWNER ipm_app;
   ```
3. Set `DATABASE_URL` (dev: `.env`; prod: the NSSM service env):
   ```
   DATABASE_URL=postgresql+psycopg://ipm_app:<password>@localhost:5432/ipm
   ```
4. Create the schema and seed the bundled workbook:
   ```
   python -m alembic upgrade head
   python scripts/migrate_xlsx_to_pg.py
   ```

**Schema migrations** (after pulling schema changes):
```
python -m alembic upgrade head
```

**Backups** — daily compressed `pg_dump`, keeping the newest 14. Register the
scheduled task (adjust the `pg_dump` path/version inside the script if needed):
```
schtasks /create /tn "CreditProbe PG Backup" /tr "powershell -ExecutionPolicy Bypass -File C:\QA\CreditProbe Tool\scripts\backup_db.ps1" /sc daily /st 02:00 /ru SYSTEM
```
Restore a dump:
```
"C:\Program Files\PostgreSQL\18\bin\pg_restore.exe" --clean --if-exists --host=localhost --username=ipm_app --dbname=ipm backups\ipm_<stamp>.dump
```

## 10. Authentication & user management

Every page and callback is behind login (Flask-Login). Sessions use `SECRET_KEY`
(set it in the service env in prod so sessions survive restarts). Cookies are
HttpOnly + SameSite=Lax; `SESSION_COOKIE_SECURE` is False because the app is served
over plain HTTP on the LAN — set it True if you put a TLS front end in place.

Manage users with the CLI (passwords are Argon2id-hashed; omit `--password` to be
prompted):
```
python scripts/manage_users.py add <username> --role admin|analyst
python scripts/manage_users.py reset-password <username>
python scripts/manage_users.py set-role <username> analyst|admin
python scripts/manage_users.py disable <username>
python scripts/manage_users.py enable <username>
python scripts/manage_users.py list
```

Seed the first admin once:
```
python scripts/manage_users.py add admin --role admin
```

## 11. Docker (alternative to the NSSM service)

### 11.1 Everyday use — the two scripts

This is the short version; the rest of the section explains what sits underneath.
The app runs in a container against the PostgreSQL already installed on this PC,
so it uses the same database, users and datasets as a local `python app.py`.

```
powershell -ExecutionPolicy Bypass -File scripts\app-start.ps1     # start  -> http://localhost:8050
powershell -ExecutionPolicy Bypass -File scripts\app-stop.ps1      # stop
docker logs -f CreditProbe                                                 # watch the log
```

`app-start.ps1` reads `DATABASE_URL`, `SECRET_KEY` and `ANTHROPIC_API_KEY` from
`.env`, rewrites the database host to `host.docker.internal` (inside a container
`localhost` is the container, not this PC — the most common cause of a container
that will not start), and starts with `--restart unless-stopped`, so the app
comes back by itself after a reboot. Re-running it replaces the running
container, so it is safe to repeat. Pass `-Port 8060` to publish elsewhere.

Stopping removes the container but not your data: PostgreSQL holds the datasets
and users, and logs/uploads live in the `ipm-logs` / `ipm-uploads` volumes.

Rebuild the image after pulling code changes:

```
docker build -t ipm-tool:0.1.0 .
powershell -ExecutionPolicy Bypass -File scripts\app-start.ps1
```

### 11.2 Self-contained stack (app + its own PostgreSQL)

An alternative to sections 3–4 and 9: `docker-compose.yml` brings up the app and
its Postgres together, with schema migration and first-time dataset seeding
handled automatically. This is for a machine that has no PostgreSQL of its own —
it starts from an **empty** database, separate from the one section 11.1 uses.
Use this **or** the NSSM service, not both against the same database.

**Image design** — multi-stage build on `python:3.14-slim`; dependencies are
compiled in a builder stage so no toolchain ships in the final image. Runs as
non-root uid 10001, with `/app` root-owned and read-only to the app user; only
`/app/logs` and `/app/uploads` are writable. Waitress serves it via `serve.py`,
so the single-process/multi-threaded rule from section 3 still applies — **never
scale `app` past one replica**, or each replica would serve its own divergent
in-process dataset cache. `HEALTHCHECK` polls `/healthz`.

**Configuration.** Compose substitutes `${...}` from the project `.env`. Add two
values it does not already have:

```
POSTGRES_PASSWORD=<choose-a-password>
SECRET_KEY=<64-hex>                     # python -c "import secrets; print(secrets.token_hex(32))"
```

Both are required and fail the run with a message if missing. `SECRET_KEY`
matters more here than under NSSM: without it every restart invalidates all
sessions (section 10), and containers restart far more often.

> `DATABASE_URL` in `.env` is **ignored** by compose — it points at
> `localhost:5432`, which inside a container is the container itself. The
> compose file targets the `db` service instead.

**Run**

```
docker compose up -d --build      # build, migrate, seed, start
docker compose logs -f app
docker compose ps                 # app should reach (healthy)
docker compose down               # stop; add -v to also delete the database volume
```

The app is then on `http://localhost:8050` (override with `PORT` in `.env`).
Postgres is deliberately **not** published to the host; add `ports: ["5432:5432"]`
to the `db` service temporarily if you need `psql` from outside.

Startup order is enforced: `db` must report healthy, then the one-shot
`bootstrap` service runs `alembic upgrade head` followed by
`scripts/migrate_xlsx_to_pg.py` and must exit 0 before `app` starts — a failed
migration blocks a bad rollout rather than starting on a stale schema. Both
steps are safe to repeat: alembic no-ops at head, and the seed no-ops once an
active dataset version exists, so an uploaded dataset is never reverted to the
bundled workbook.

**Operations**

```
docker compose exec app python scripts/manage_users.py add admin --role admin
docker compose exec app python scripts/manage_users.py list
docker compose exec db pg_dump -U ipm_app -Fc ipm > backups/ipm.dump
docker compose up -d --build      # update: after git pull
```

Application logs and uploads live in the `logs` / `uploads` named volumes;
`logs/ipm.log` rotates inside the container exactly as in section 8.

**Ollama.** `localhost` inside the container is not the host, so
`OLLAMA_BASE_URL` defaults to `http://host.docker.internal:11434` to reach an
Ollama running on the host machine. The Anthropic model needs no such handling.

**AI keys.** `ANTHROPIC_API_KEY` is passed through from `.env` at run time and is
never baked into the image; `.dockerignore` excludes `.env` from the build
context entirely. Rotation follows section 7, then `docker compose up -d`.


---

## 12. Releasing a certified build

An ordinary `docker compose up --build` produces a **development image**. It
works, it is fully usable, and it reports `UNCERTIFIED` on `/api/v1/build`
because it has not been measured against the sealed holdout. That is the honest
answer and it is fine for everyday work.

A **release image** is different: it carries a frozen Intelligence Release,
which is the evidence that this exact commit did what was asked of it on cases
it had never seen. Producing one is a single command that refuses more often
than it succeeds.

```bash
./scripts/release.sh --check    # certify and report; build nothing
./scripts/release.sh            # certify, then build if it passed
```

It refuses, and says which, when:

| Refusal | Why it matters |
|---|---|
| The working tree has uncommitted changes | A certification run measures the code it can see. An image built from a dirty tree is not the code that was measured. |
| Certification did not pass | The blockers are printed. No release-tagged image is produced. |
| The manifest certifies a different commit | A stale manifest left by an earlier run is the exact mistake this exists for. |

On success it writes `intelligence_release/manifest.json`, copies it into the
image, and tags `creditprobe:<sha>` and `creditprobe:release`.

**The key is never involved.** It is not a build argument — a build argument is
recorded in the image history, where anyone who pulls the image can read it —
and certification runs against the deterministic governed reader unless a
provider is configured in the shell that runs the script. Nothing in the
manifest, the report or the console output contains key material.

### Checking what a running container is certified as

```bash
curl -s http://localhost:8000/api/v1/build | python -m json.tool
```

The `intelligence` block reports one of four states:

| Status | What to do |
|---|---|
| `CERTIFIED` | Nothing. The evidence names the commit that is running. |
| `UNCERTIFIED` | Expected for a development image. Use `release.sh` if you need evidence. |
| `NOT_PASSED` | A manifest exists and the gate rejected it. Do not ship this image. |
| `STALE` | The manifest certifies a **different commit**. Somebody pulled new code and shipped the old evidence. Re-certify. |

---

## 13. Running the intelligence commands against a live model

Everything below is safe to run on a laptop with a real key. None of it prints
the key, writes it to a file, or passes it to Docker.

```bash
# 1. Is a key configured for this shell? Prints only yes or no.
python -c "import os; print('configured' if os.environ.get('ANTHROPIC_API_KEY') else 'not configured')"

# 2. What would a run cost, before spending anything?
python -m intelligence_factory.certify --estimate

# 3. The open curriculum against the live path.
python -m intelligence_factory.certify

# 4. The sealed holdout, and freeze a release.
python -m intelligence_factory.certify --certify
```

Set the key in the shell that runs the command, never in a Dockerfile, a compose
file, a commit or a screenshot:

```bash
export ANTHROPIC_API_KEY='...'          # macOS / Linux
$env:ANTHROPIC_API_KEY = '...'          # Windows PowerShell
```

For the containerised stack the key belongs in `.env`, which `.dockerignore`
excludes from the build context entirely and which compose passes through at run
time. Rotation follows section 7.

**If a command ever prints something that looks like a key, treat that as a bug
and report it.** Nothing here is designed to, and the tests in
`tests/factory/test_release_manifest.py` assert that the published manifest
carries none.
