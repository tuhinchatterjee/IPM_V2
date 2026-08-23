# IPM — Credit Portfolio Intelligence & Monitoring

An AI-native credit-risk analytical platform for banks.

The language model interprets the question, plans the investigation and writes the
explanation. **Every figure is produced by a deterministic, versioned, tested
engine** — and every result is fully traceable back to the data, filters,
parameters and function version that produced it.

> **New here?** Jump straight to
> [How to run IPM locally — for a non-developer](#how-to-run-ipm-locally--for-a-non-developer).

| Document | What it covers |
|---|---|
| [docs/PRODUCT_SPEC.md](docs/PRODUCT_SPEC.md) | What the product is: the 16 capabilities, the LLM/engine boundary, the Trace model |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | How it is built: layers, data architecture, repository structure |
| [docs/DEMO_SCOPE.md](docs/DEMO_SCOPE.md) | What is being built, in what order, and what is honestly not built yet |

---

## The governing rule

**The language model is not the calculator and is not the source of truth.**

| The language model does | The IPM Engine does |
|---|---|
| Understand the question | Retrieve, filter and aggregate data |
| Interpret intent | Compute portfolio metrics |
| Build an investigation plan | Compute stage and DPD migration |
| Choose approved IPM analyses | Compute rating transition matrices |
| Select parameters | Analyse ECL and deterioration |
| Interpret returned results | Run stress scenarios |
| Write the narrative | Return structured numerical output |

Enforced mechanically, not merely requested: the model's only numeric-facing
output is a **plan**, validated against the engine registry. It may name only
registered analyses, with parameters that satisfy each analysis's declared
contract. Anything else is **rejected before execution**.

*The model can order from the menu. It cannot cook.*

---

## How to run IPM locally — for a non-developer

Written for someone who does not write software. Every step is spelled out. If a
step fails, the error message tells you exactly what to do.

### What you need to install first

Three things, once. Install each one and accept all the defaults.

| # | What | Where to get it | How to check it worked |
|---|---|---|---|
| 1 | **Docker Desktop** — runs the database for you, so you never have to install or configure a database yourself | https://www.docker.com/products/docker-desktop/ | Open it. Wait until it says **Running** in the bottom-left corner. |
| 2 | **Node.js** (version 20 or newer) — runs the user interface | https://nodejs.org/ (choose the **LTS** version) | Open a terminal and type `node -v`. You should see something like `v22.x.x`. |
| 3 | **Python** (version 3.11 or newer) — runs the analytics | https://www.python.org/downloads/ | Type `python --version`. You should see `3.11` or higher. |

> **Windows users:** when installing Python, tick the box that says
> **"Add python.exe to PATH"** on the very first screen. It is easy to miss and
> everything else depends on it.

**"Open a terminal" means:**
- **Windows** — press the Start button, type `Windows Terminal`, press Enter.
- **Mac** — press ⌘ + Space, type `Terminal`, press Enter.

Then move into the IPM folder by typing `cd ` (with a space) and dragging the IPM
folder onto the terminal window, then pressing Enter.

---

### Step 1 — Set it up (once)

**Mac or Linux:**
```bash
./scripts/setup.sh
```

**Windows:**
```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
cd frontend
npm install
cd ..
copy .env.example .env
.venv\Scripts\python scripts\build_data_lake.py
```

This installs everything IPM needs and converts the sample credit data into the
format the analytics engine reads. It takes a few minutes the first time.

---

### Step 2 — Set your database password (once)

Open the file called **`.env`** in the IPM folder with any text editor (Notepad
is fine). Find these two lines:

```
POSTGRES_PASSWORD=change_me_local_dev_password
DATABASE_URL=postgresql+psycopg://ipm_app:change_me_local_dev_password@localhost:5432/ipm
```

Replace **`change_me_local_dev_password`** in *both* places with a password of
your choosing. It must be identical in both lines. This password only protects
the database running on your own computer.

Save the file and close it.

> **Never share or commit the `.env` file.** It is already excluded from git, so
> it will not be uploaded anywhere.

---

### Step 3 — Start IPM

Make sure **Docker Desktop is open and running**, then:

**Mac or Linux:**
```bash
./scripts/dev.sh
```

**Windows:**
```powershell
.\scripts\dev.ps1
```

You will see it start each part in turn, checking each one is ready:

```
> Checking prerequisites
  [ok] Docker is running
  [ok] Node.js v22.22.2
  [ok] Python packages installed

> Starting PostgreSQL
  [ok] PostgreSQL is ready on port 5432

> Applying database migrations
  [ok] Database schema is up to date

> Checking the analytical data
  [ok] Analytical layer already built (10 Parquet files)

> Starting the backend API
  [ok] API ready at http://127.0.0.1:8000

> Starting the frontend
  [ok] Frontend ready

  IPM is running.

    Open this in your browser:   http://localhost:3000
```

### Step 4 — Open it

Go to **http://localhost:3000** in your browser.

The top-right corner shows the live system status. If everything is working it
says **All systems operational**.

---

### Stopping IPM

Press **Ctrl + C** once in the terminal. That stops the interface and the
analytics. The database keeps running quietly in the background; to stop that
too:

```
docker compose down
```

Your data is kept. To erase the database entirely and start fresh, use
`docker compose down -v`.

---

### If something goes wrong

Every failure message names the fix. The most common ones:

| Message | What it means | What to do |
|---|---|---|
| `Docker is installed but not running` | Docker Desktop is closed | Open Docker Desktop, wait for **Running**, try again |
| `No .env file found` | Step 2 was skipped | `cp .env.example .env` (Windows: `copy .env.example .env`) |
| `The Python packages are not installed` | Step 1 did not finish | Re-run `./scripts/setup.sh` |
| `PostgreSQL did not become ready` | The database failed to start | Run `docker compose logs db` to see why |
| `Cannot reach the IPM backend` in the browser | The backend stopped | Look in `logs/api-dev.log` |
| `port is already allocated` | Something else is using port 5432 | Change `POSTGRES_PORT=5433` in `.env` (and in `DATABASE_URL`) |

Two log files hold the detail: **`logs/api-dev.log`** and **`logs/web-dev.log`**.

---

## What each part does

| Part | What it is | Why IPM uses it |
|---|---|---|
| **PostgreSQL** | A database | The filing cabinet: users, projects, chats, analysis runs, traces, and the Engine Builder / Data Builder definitions. Everything the bank has *decided* or *recorded*. |
| **Parquet** | A file format for large tables | Stores data column by column, so totalling one column of millions of rows reads only that column. This is where the monthly credit data lives — **not** in PostgreSQL. |
| **DuckDB** | A query tool | Runs SQL directly against those Parquet files, with no server to install. Filtering and totalling happen inside DuckDB; only the summary comes back. |
| **FastAPI** | The backend | Exposes every capability over the web so the interface never reaches into the analytics directly. That boundary is what lets either side be replaced independently. |
| **Next.js / React** | The frontend | The user interface: an enterprise-grade application with four themes and, from Phase 4, the interactive Trace graph. |

---

## Everyday commands

| What you want | Command |
|---|---|
| Start everything | `./scripts/dev.sh` (Windows: `.\scripts\dev.ps1`) |
| Run every quality check | `./scripts/check.sh` |
| Rebuild the analytical data | `.venv/bin/python scripts/build_data_lake.py` |
| Update the database schema | `.venv/bin/python -m alembic upgrade head` |
| Start only the database | `docker compose up -d db` |
| Stop the database | `docker compose down` |
| Browse the database in a web page | `docker compose --profile tools up -d` then http://localhost:5050 |
| Read the API documentation | http://127.0.0.1:8000/docs while IPM is running |

---

## Repository structure

```
backend/
  api/              FastAPI — the HTTP surface the frontend talks to
  data_access/      the Data Access Layer: governed names in, DataFrames out.
                    The ONLY place that knows about DuckDB.
  engine/           the deterministic IPM Engine: contracts, registry, functions
  trace/            the Trace graph — nodes, edges, content hashing
  orchestration/    the only place a language model is used (Phase 3)
  stress/           stress scenarios (Phase 2+)
  models/           PostgreSQL tables for the platform
  climate/          the Oman climate stressed-PD engine (validated to 1e-11)
  data_loader.py    ~70 proven credit-risk calculations (become engine functions)
  reporting/        PDF and Word writers

frontend/           Next.js + TypeScript + Tailwind + shadcn/ui + Recharts
  src/app/          one route per capability
  src/components/   ui/ (shadcn primitives), layout/, system/
  src/lib/          api client, themes, navigation

data/
  raw/              source files exactly as received — never modified
  curated/          mapped to governed field names, typed and validated
  analytics/        business-ready Parquet, read by DuckDB (generated)

metadata/           the governed data catalogue (generated)
alembic/            database migrations
tests/              engine, trace, data_access, api, and the legacy Dash suites
legacy/dash_app/    the original Dash application, preserved and still tested
docs/               product spec, architecture, demo scope
scripts/            setup.sh, dev.sh, dev.ps1, check.sh, build_data_lake.py
```

### The import rule

```
frontend       → talks to backend only over HTTP
backend/api    → may use everything below
backend/engine → may use data_access;  never api, never an LLM, never duckdb
data_access    → may use nothing above it
```

The credit-risk maths must never become dependent on the screen it is shown on.
That one rule is what lets the interface be replaced, the API be extended, and
the storage move to a lakehouse — without touching a calculation.

---

## The data

The bundled portfolio is **synthetic**: 6,599 facility positions across ten
quarterly reporting periods from Q4 2023 to Q1 2026, with 53 attributes each,
plus 389 borrower financial records.

It is rich enough for genuine stage migration, DPD migration, rating transitions,
ECL attribution and deterioration ranking — it carries the prior period's rating
and utilisation, so movement is measured rather than estimated.

Every dataset carries a `synthetic` flag through the governed catalogue, and the
interface labels it wherever its figures appear.

---

## Quality gates

```bash
./scripts/check.sh
```

| Gate | Covers |
|---|---|
| `ruff` | Python linting |
| `pytest` | Data Access Layer, engine contracts, Trace graph, API, and the preserved Dash suites including the climate golden master |
| `tsc --noEmit` | TypeScript type checking |
| `eslint` | Frontend linting |
| `next build` | Frontend production build |

CI runs the Python gates on every push (`.github/workflows/ci.yml`).

---

## The original Dash application

The previous Dash application is preserved, working and still under test, in
**`legacy/dash_app/`**. It is no longer the product front end — Next.js is — but
it contains proven analytical screens worth referring back to while the React
interface is built. Its seven test suites still run as part of `pytest`.

Its backend analytics were **not** moved to legacy: `backend/data_loader.py`,
`backend/climate/`, the RAROC engines and the report writers are all retained and
become the implementations behind registered engine functions in Phase 2.

---

## Current status

**Phase 1 — Foundations, complete.** The spine is built and tested; the
analytical capabilities and the screens that show them arrive in Phases 2–6. See
[docs/DEMO_SCOPE.md](docs/DEMO_SCOPE.md) for the sequence.

Every screen in the application states its own honest status. IPM does not
present unbuilt functionality as if it were finished, and never shows invented
figures.
