# IPM Tool — Intelligent Portfolio Manager

A credit-risk and CBUAE regulatory-reporting cockpit for a GCC wholesale/retail
loan portfolio, built with Dash. Executive KPIs, AI early-warning signals,
Borrower 360, IFRS 9 / ECL, concentration & rating migration, limits & stress
testing, a macroeconomic outlook (IMF WEO), CBUAE BRF regulatory returns, an
ESG & climate transition/physical stressed-PD model, and a Data Hub for uploading
portfolio workbooks — with an AI chat assistant grounded in the real data.

> **New here, or setting this up on a fresh Windows PC?** Follow
> **[SETUP.md](SETUP.md)** instead — every step spelled out for Windows Terminal,
> including which tools to install and what to do when something fails. The quick
> start below assumes the prerequisites are already in place.

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
                        # upload validation, the Parquet dataset codec, and the
                        # climate engine's Excel-parity golden master
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
  climate/                  # ESG & climate stressed-PD model (see below)
  ai_chat.py, qwen_ultra_chat.py, claude_chat.py   # AI chat backends
  db/                       # SQLAlchemy models + engine
  services/                 # data_store (versioned cache), rate_limit, ai_usage, ai_common
  auth/                     # Flask-Login, login routes, Argon2 hashing
frontend/
  ui_common.py              # shared UI helpers
  brf_view.py, macro_view.py, data_hub.py, raroc_view.py, raroc2_view.py, esg_view.py
assets/                     # CSS + login background (served by Dash)
alembic/  scripts/  tests/
```

## ESG & climate stressed PD

`backend/climate/` is a code reproduction of the **Oman Climate Stressed PD model
v5.1** workbook (bundled as `Oman_Climate_StressedPD_v5 1.xlsx`), generalised to be
multi-run, auditable and parameterisable per client/country. Output is a grid of
stressed PDs — 10 sectors × 7 rating grades × 4 NGFS scenarios — plus every
intermediate quantity, 24 structural quality checks, and sensitivity views. It
computes no ECL and no LGD: it stops at the PD signal, exactly like the workbook.

```
stressed_PD = N( N⁻¹(PD₀) + push + macro_shift )
push        = k × g(transition cost ratio + physical cost ratio),  g(x,θ) = ((1+x)^θ − 1)/θ
```

```
backend/climate/
  normal.py        AS241 inverse normal + erfc CDF — Excel NORMSINV/NORMSDIST parity
  defaults.py      the v5.1 Oman dataset as a plain JSON-serialisable model dict
  registers.py     source / assumption / verification registers (the audit trail)
  engine.py        pure deterministic calculation: model dict -> result dict
  checks.py        the 24 live quality checks, run on every calculation
  sensitivity.py   one-way tornado over the five control levers + run comparison
  store.py         model versions + immutable runs carrying full input snapshots
  svg.py           inline-SVG charts for the offline report
  report.py        self-contained HTML summary pack + Excel regulator pack
```

Three invariants the engine deliberately protects, each of which the workbook got
wrong at least once before fixing: the two cost ratios are summed **inside** `g()`
(it is concave, so two separate pushes understate facing both shocks at once);
**k is a function of θ** and is refitted whenever θ moves; and the macro leg
consumes a GDP **level** deviation, never a growth rate.

`tests/test_climate_engine.py` is a golden-master suite: it asserts the engine
reproduces the workbook's published figures — k = 0.263009761023414, the full
intensity and cost-ratio tables, the MR5 grid, the θ band and the k-sensitivity
grid — to 1e-11 relative, which is tighter than Excel's own precision. Property
tests then cover what a golden master cannot: zero shocks return the baseline
exactly, exposure weights are scale-invariant, and both scenario orderings hold.

Model versions and runs are stored as JSON documents under `uploads/climate/`
(no schema migration; the payloads are documents, not relations). A version marked
`final` is immutable — editing requires cloning it — and cannot be promoted while
any quality check is failing.

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
