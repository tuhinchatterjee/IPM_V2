# Cockpit Intelligence V2 — baseline and isolation

Brief §1. What this branch is based on, where its runtime lives, and how it is
kept away from everything else.

## 1. Base

| | |
|---|---|
| Repository | `tuhinchatterjee/IPM_V2` |
| Checkout | `/home/user/IPM_V2` (hosted Claude Code web session) |
| Verified base commit | `3855f9b6f6b231beb6f2193c8a1e219d01596421` |
| Base commit subject | *Merge pull request #1 from tuhinchatterjee/claude/vigilant-darwin-eohyi1* |
| Base branch | `main` |
| Working branch | `claude/cockpit-intelligence-v2-mbb22o` |
| Branch position at start | 0 commits ahead of and 0 behind `origin/main` |
| Working tree at start | clean |

### Why this base

Brief §1.1 says not to assume the open branch is the right base. It was
checked rather than assumed:

* `git rev-list --count main..HEAD` returned `0`, and `git log -1 main` returned
  the same SHA as `HEAD`. The working branch *is* main's head commit, so there is
  no in-flight Early Warning / What-if / Planner / Lenses / Playbook work sitting
  underneath this task.
* `git branch -a` shows only `main` and this task branch, locally and on the
  remote. There is no other branch that could hold a different Cockpit.
* The working Cockpit is present on this commit: `frontend/src/app/page.tsx`
  (`CockpitPage` / `Cockpit`), `POST /api/v1/ask` in
  `backend/api/routers/ask.py`, the analyst loop in `backend/analyst/`, the
  deterministic engine in `backend/orchestration/`.

No branch had to be merged or cherry-picked, and none was.

The Mac path named in the brief (`/Users/tuhinchatterjee/Desktop/IPM_V2`) is a
location hint from the owner's own machine. This is a hosted checkout; the
actual connected checkout above is what was used. No git worktree was created:
the hosted task already provides an isolated checkout on its own branch, and
brief §1.2 says not to nest a redundant worktree purely to satisfy a naming
preference.

## 2. Runtime isolation

A branch is not runtime isolation (§1.3). Every writable destination this
branch touches was redirected into a directory that did not exist before it and
that nothing else uses:

```
/home/user/IPM_V2-cockpit-v2-runtime/
├── pgdata/     an isolated PostgreSQL 16 cluster, created by initdb for this branch
├── analytics/  DATA_ANALYTICS_DIR — the Parquet lake
├── metadata/   METADATA_DIR — catalog.json
├── raw/        DATA_RAW_DIR — a copy of data/raw, never written back
├── curated/    DATA_CURATED_DIR
├── uploads/    UPLOAD_DIR
├── exports/
└── logs/       LOG_DIR, plus the PostgreSQL and API logs
```

| Resource | Isolated value | Shared default it replaces |
|---|---|---|
| Database | `postgresql+psycopg://ipm_v2@127.0.0.1:55432/ipm_v2_cockpit` | port 5432, database `ipm` |
| PostgreSQL data dir | `…-cockpit-v2-runtime/pgdata` | Docker volume `db` |
| Analytics lake | `…-cockpit-v2-runtime/analytics` | `data/analytics` |
| Catalogue | `…-cockpit-v2-runtime/metadata/catalog.json` | `metadata/catalog.json` |
| Backend port | 8100 | 8000 |
| Frontend port | 3100 | 3000 |
| Feature switch | `COCKPIT_INTELLIGENCE_V2=true` | unset → off |

Points worth stating plainly:

* The PostgreSQL cluster is **new**. `initdb` created it inside this branch's
  runtime directory on port 55432. It is not a copy of, and has no connection
  to, any existing demo or live database. No existing demo data was read,
  overwritten or migrated.
* Docker is installed in this container but its daemon is not running, so the
  repository's usual `docker compose up -d db` route was unavailable. A native
  PostgreSQL 16 (already present at `/usr/lib/postgresql/16`) was initialised
  instead, under the unprivileged `postgres` system account, listening only on
  `127.0.0.1`.
* Ports 55432 / 8100 / 3100 were checked as free before use. No process was
  killed to obtain a port.
* `.env` is untracked (`.gitignore` line 2) and is **not** committed. It holds
  no provider credential — there is none in this environment — and no secret
  beyond a local-development `SECRET_KEY` that is labelled as such in the file.
* `data/analytics/` and `metadata/catalog.json` are gitignored, so no generated
  lake or catalogue enters the commit either way; the redirection above means
  nothing is written to those repository paths at all.
* No symlink into a shared `.env` or a shared SQLite file exists.

### Startup guard

`backend/cockpit_v2/guard.py` refuses to seed or reset unless the resolved
analytics directory, metadata directory and database name all sit inside the V2
namespace. It fails closed and prints the sanitized destinations it checked, so
a V2 seed cannot be pointed at a shared database or lake by an environment
mistake.

## 3. Python environment

The repository pins `numpy==2.5.0`, `pandas==3.0.3` and friends in
`requirements.txt` / `pyproject.toml`, targeting a newer interpreter than this
image's default Python 3.11. A private virtual environment was built on the
Python 3.13 that is present:

```
python3.13 -m venv .venv
.venv/bin/python -m pip install fastapi uvicorn[standard] pydantic pydantic-settings \
    duckdb pandas numpy pyarrow httpx pytest python-dotenv sqlalchemy alembic \
    psycopg[binary] argon2-cffi openpyxl anthropic requests tenacity python-multipart \
    python-docx reportlab matplotlib pillow xlsxwriter pypdf plotly dash flask \
    waitress flask-compress flask-login dash-bootstrap-components
```

Resolved versions: pandas 3.0.5, numpy 2.5.3, duckdb 1.5.5 — the same major
lines the pins intend. **No pin file was edited.** `.venv/` is gitignored.

## 4. Safe launch

```sh
cd /home/user/IPM_V2

# 1. the isolated database (idempotent; already running is fine)
su postgres -c "PATH=/usr/lib/postgresql/16/bin:\$PATH pg_ctl \
  -D /home/user/IPM_V2-cockpit-v2-runtime/pgdata \
  -o '-p 55432 -k /home/user/IPM_V2-cockpit-v2-runtime -c listen_addresses=127.0.0.1' \
  -l /home/user/IPM_V2-cockpit-v2-runtime/logs/pg.log start"

# 2. schema
.venv/bin/python -m alembic upgrade head

# 3. the analytical lake (only if …-runtime/analytics is empty)
.venv/bin/python scripts/generate_saudi_universe.py
.venv/bin/python scripts/build_corporate_universe.py

# 4. the Cockpit V2 demo datasets
.venv/bin/python scripts/build_cockpit_v2_demo.py

# 5. backend on 8100
.venv/bin/python -m uvicorn backend.api.main:app --host 127.0.0.1 --port 8100

# 6. frontend on 3100
cd frontend && npm install && NEXT_PUBLIC_API_BASE=http://127.0.0.1:8100/api/v1 npm run dev -- --port 3100
```

### Stop / rollback for this runtime

```sh
pkill -f "uvicorn backend.api.main:app --host 127.0.0.1 --port 8100"
pkill -f "next dev.*3100"
su postgres -c "PATH=/usr/lib/postgresql/16/bin:\$PATH pg_ctl -D /home/user/IPM_V2-cockpit-v2-runtime/pgdata stop"
# and, to discard the runtime entirely — it contains nothing but this branch's own data:
rm -rf /home/user/IPM_V2-cockpit-v2-runtime
rm -f /home/user/IPM_V2/.env
```

Nothing outside `/home/user/IPM_V2-cockpit-v2-runtime` and this branch's own
commits is changed by any of the above.

## 5. Outside-scope work preserved

No file belonging to Early Warning, What-if, Scorecards, Planner, Lenses or
Playbook was edited to make Cockpit work. `docs/cockpit_v2/INTEGRATION_NOTES.md`
lists every shared file this branch touches and what the flag-off behaviour of
each is. No branch was merged, no history rewritten, nothing force-pushed,
nothing deployed.

## 6. Provider status — LIVE_PROVIDER_UNVERIFIED

`ANTHROPIC_API_KEY` is not set in this environment and there is no `.env` in
the base checkout that carries one. A direct probe of the Anthropic Models API
returns:

```
HTTP 401  {"type":"error","error":{"type":"authentication_error",
           "message":"x-api-key header is required"}}
```

so the network reaches the provider and the credential is simply absent. Per
brief §2.2 this is recorded as **LIVE_PROVIDER_UNVERIFIED**. No model ID was
invented, no model was substituted, and nothing in this branch is described as
live-tested against a provider. The consequences are set out in
`docs/cockpit_v2/EVALUATION_REPORT.md`.
