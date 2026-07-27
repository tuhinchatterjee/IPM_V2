# IPM Tool — Deployment & Operations

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
nssm install IPMTool "C:\QA\IPM Tool\.venv\Scripts\python.exe" "C:\QA\IPM Tool\serve.py"
nssm set IPMTool AppDirectory "C:\QA\IPM Tool"
nssm set IPMTool AppEnvironmentExtra ENV=prod HOST=0.0.0.0 PORT=8050 ANTHROPIC_API_KEY=<new-key> OLLAMA_BASE_URL=http://localhost:11434
nssm set IPMTool AppStdout "C:\QA\IPM Tool\logs\service-out.log"
nssm set IPMTool AppStderr "C:\QA\IPM Tool\logs\service-err.log"
nssm set IPMTool AppExit Default Restart
nssm start IPMTool
```

> If you run from the system Python instead of a `.venv`, point the first argument
> at that `python.exe` (e.g. `C:\Users\...\Python\...\python.exe`).

Service control: `nssm restart IPMTool`, `nssm stop IPMTool`, `nssm status IPMTool`.

## 5. Firewall (LAN access)

Allow inbound TCP on the app port for the private/domain network profiles only:

```
netsh advfirewall firewall add rule name="IPM Tool 8050" dir=in action=allow protocol=TCP localport=8050 profile=domain,private
```

Colleagues then reach the app at `http://<this-pc-ip>:8050`.

## 6. Update procedure

```
cd "C:\QA\IPM Tool"
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
schtasks /create /tn "IPM PG Backup" /tr "powershell -ExecutionPolicy Bypass -File C:\QA\IPM Tool\scripts\backup_db.ps1" /sc daily /st 02:00 /ru SYSTEM
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

