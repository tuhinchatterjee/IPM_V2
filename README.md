# IPM Tool — Intelligent Portfolio Manager

A credit-risk and CBUAE regulatory-reporting cockpit for a GCC wholesale/retail
loan portfolio, built with Dash. Executive KPIs, AI early-warning signals,
Borrower 360, IFRS 9 / ECL, concentration & rating migration, limits & stress
testing, a macroeconomic outlook (IMF WEO), CBUAE BRF regulatory returns, and a
Data Hub for uploading portfolio workbooks — with an AI chat assistant grounded in
the real data.

## Quick start (development)

Prerequisites: Python 3.14, PostgreSQL 16+.

```bash
# 1. Install dependencies
python -m pip install -r requirements.txt      # or: uv sync

# 2. Configure
copy .env.example .env                          # then edit values (see below)

# 3. Create the database (in psql, as the postgres superuser)
#    CREATE ROLE ipm_app WITH LOGIN PASSWORD '...';
#    CREATE DATABASE ipm OWNER ipm_app;
#    Set DATABASE_URL in .env accordingly.

# 4. Create the schema and seed the bundled dataset
python -m alembic upgrade head
python scripts/migrate_xlsx_to_pg.py

# 5. Create the first user
python scripts/manage_users.py add admin --role admin

# 6. Run (development server)
python app.py                                   # http://127.0.0.1:8050
```

## Configuration

All configuration is environment-driven (`config.py`; see `.env.example`). Key
variables: `ENV` (dev|prod), `HOST`, `PORT`, `DATABASE_URL`, `ANTHROPIC_API_KEY`,
`OLLAMA_BASE_URL`, `SECRET_KEY`, `LOG_DIR`, `UPLOAD_DIR`, `MAX_UPLOAD_MB`.

Real process environment variables always win over `.env`; production injects them
via the service (never ships a `.env`).

## Running in production

Served by Waitress (single process, multi-threaded) and supervised as a Windows
service. See **[docs/deploy.md](docs/deploy.md)** for the NSSM service setup,
firewall rule, PostgreSQL backup schedule, user management, and the secret-rotation
runbook.

```bash
set ENV=prod
set HOST=0.0.0.0
python serve.py
```

Health probe: `GET /healthz` (no auth) returns JSON status incl. the active dataset
version and a database check.

## Authentication

Every page and callback is behind login (Flask-Login; Argon2id password hashing).
Manage users with `python scripts/manage_users.py` (add / reset-password / set-role
/ disable / enable / list).

## Tests & lint

```bash
python -m pytest        # DB-free suite: BRF regulatory math, aggregations,
                        # upload validation, and the Parquet dataset codec
python -m ruff check .  # lint
```

CI (GitHub Actions, `.github/workflows/ci.yml`) runs ruff + pytest on every push.

## Architecture

The code is split into a **`backend/`** package (data, calc engines, DB, services,
auth, config, AI) and a **`frontend/`** package (Dash view builders + `assets/`),
with `app.py` / `serve.py` at the root as the composition entry points. Frontend
depends on backend; backend never imports frontend.

```
app.py, serve.py            # Dash app + callbacks; Waitress production entrypoint
backend/
  config.py, logging_setup.py
  data_loader.py            # ≈70 pure aggregation functions
  raroc_data.py, raroc2_data.py   # RAROC / post-deal RAROC engines
  ai_chat.py, qwen_ultra_chat.py, claude_chat.py   # AI chat backends
  db/                       # SQLAlchemy models + engine
  services/                 # data_store (versioned cache), rate_limit, ai_usage, ai_common
  auth/                     # Flask-Login, login routes, Argon2 hashing
frontend/
  ui_common.py              # shared UI helpers
  brf_view.py, macro_view.py, data_hub.py, raroc_view.py, raroc2_view.py
assets/                     # CSS + login background (served by Dash)
alembic/  scripts/  tests/
```

Everything runs from the project root (`python app.py`, `python serve.py`,
`python -m pytest`, `python -m alembic …`, `python scripts/…`), which puts the
`backend`/`frontend` packages on the import path.

**Data flow:** PostgreSQL is the source of truth for portfolio data. Each uploaded
(or the bundled) workbook is a versioned dataset; sheets are stored as
dtype-faithful Parquet blobs. A per-process cache (`backend/services/data_store`)
keeps the in-memory DataFrames in sync with the active version, so the aggregation
functions never change regardless of which dataset is active.

**AI grounding:** the chat models never see the raw dataset — they call read-only
tools that query `data_loader`, so answers are grounded in real figures. Tool output
is treated as data, not instructions (prompt-injection defense).

## Note on synthetic data

The bundled `Portfolio_Monitoring_Dataset.xlsx` is synthetic. Capital-linked BRF
figures use documented proxies (a PD-driven RWA curve and a capital-ratio
assumption), and the macro scenario paths are illustrative — both are labelled as
such in the UI.
