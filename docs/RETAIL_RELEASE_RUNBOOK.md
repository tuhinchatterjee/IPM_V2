# Retail demonstration — pull, start, present

Everything here is a command somebody types. Nothing is inferred from a
`Makefile` target that may not exist on the machine in front of you.

The installation serves **one** product. Every command below sources
`.env.retail` first, and every one of them will refuse to touch a corporate
database or metadata directory if you forget — `backend/retail/guard.py`
checks, because the two installations share a checkout and a mistyped
environment used to be silent.

---

## 1. Pull

```bash
cd ~/IPM_V2
git fetch origin claude/funny-dirac-6n8f0o
git checkout claude/funny-dirac-6n8f0o
git pull origin claude/funny-dirac-6n8f0o
```

## 2. Dependencies

Only if `git pull` changed `requirements.txt` or `frontend/package.json`.

```bash
cd ~/IPM_V2
.venv/bin/pip install -r requirements.txt
cd frontend && npm install && cd ..
```

## 3. The database

PostgreSQL on **55432**, which is the retail installation's port and not the
default. If it is already running, skip this.

```bash
# macOS, Homebrew PostgreSQL 16
pg_ctl -D /usr/local/var/postgresql@16-retail -o "-p 55432" -l /tmp/pg_retail.log start
```

Then the migrations:

```bash
cd ~/IPM_V2
set -a && . ./.env.retail && set +a
.venv/bin/alembic upgrade head
```

## 4. Bootstrap

This publishes the book, builds the governed views, scores the early-warning
panel, fits the What-If challenger and seeds the demonstration content. It is
idempotent: anything already correct at the published book version is left
alone, and anything whose figures have moved is refreshed rather than
duplicated.

```bash
cd ~/IPM_V2
set -a && . ./.env.retail && set +a
.venv/bin/python scripts/bootstrap_retail_installation.py
```

Then ask it whether it is ready. This changes nothing and reads the running
application rather than the files — an installation whose files are all
present and whose server is serving older code is exactly the failure it
exists to catch.

```bash
.venv/bin/python scripts/bootstrap_retail_installation.py --check
```

It must print **`The retail installation is ready to demonstrate.`** If it
prints `Still missing:` lines instead, each one says what to do.

## 5. Start

Two terminals. Both source the environment first; the frontend in particular
falls back to the **corporate** port 8000 without it, which renders the whole
page and then reports "Backend offline".

**Terminal 1 — the API, on 8328:**

```bash
cd ~/IPM_V2
set -a && . ./.env.retail && set +a
.venv/bin/uvicorn backend.api.main:app --host 0.0.0.0 --port 8328
```

**Terminal 2 — the web application, on 5328:**

```bash
cd ~/IPM_V2/frontend
set -a && . ../.env.retail && set +a
npm run dev -- --port 5328
```

Then open **http://localhost:5328** and sign in as `retail.demo` /
`RetailDemo!2026`.

### Give it two and a half minutes before you present

The API warms three expensive answers on a background thread as it starts:
the early-warning panel, the trends every seeded dashboard reads, and the §7
trait analysis. Nothing waits for it and nothing breaks if you are early — a
reader who beats the warm-up simply computes it themselves, as before. But
the trait inventory is 22 seconds computed and 0.2 seconds warmed, and on a
demonstration machine the presenter is the first reader. The log says when it
is done:

```
early warning score warmed in 89.2s
26 seeded dashboard trends warmed in 190.9s
trait analysis warmed in 22.1s
```

---

## 6. Before a client sees it

```bash
cd ~/IPM_V2
set -a && . ./.env.retail && set +a
.venv/bin/python scripts/retail_uat/smoke_release.py
```

Twenty checks, about fifteen minutes, in a real browser. It opens the
screens, runs the scenarios and opens the downloaded documents rather than
asserting that a call returned 200.

The fuller suites, if you have the time:

```bash
.venv/bin/python scripts/retail_uat/phase8_story.py            # §22/§23, 21 checks
.venv/bin/python scripts/retail_uat/phase8_navigation.py       # §25, 7 checks
.venv/bin/python scripts/retail_uat/phase9_models_and_lenses.py # §10.2/§20, 14 checks
.venv/bin/python scripts/retail_uat/phase9_timings.py          # §27, cold and warm
```

---

## 7. Presenting

Open **Demo Story** under Work. Five acts, twenty-eight steps, each one
naming the screen to open and the words to type. Every artifact it links to
is resolved against *this* installation when the page loads, so the ids are
this machine's — a guide that names "investigation 1012" is right on the
machine it was written on and wrong on every other.

It is a guided route, not a rail. Resume returns to the step you left on,
Restart clears it, and free-text navigation works throughout. Nothing in the
story is pre-answered: every prompt is answered live by the product, through
the same path a typed question takes.

---

## What is not in this release

Two of the ninety-two acceptance gates are not green, and both are recorded
in `RETAIL_DEMO_COMPLETION_ACCEPTANCE.md` rather than argued away.

**WIF-16 — Remove Step, Clone and Compare.** They exist in the API and are
exercised by the What-If suites; no control on the thread screen reaches
them. A UI gap, not a capability gap.

**VAL-16 — the wider scorecard regression suite.** Not re-run since
`994cf6d`. It was deferred when it exceeded the release window. The targeted
Phase 6 acceptance covers the behaviour this release changed; the regression
suite covers everything it did not.

Neither is on the twenty-minute demonstration path.

---

## If something is wrong

**"Backend offline" on a page that rendered.** The frontend is talking to
port 8000. Stop it, `set -a && . ../.env.retail && set +a`, start it again.

**A screen opens empty.** Run `--check`. It counts the seeded content against
the seed definitions and will say which screen is thin.

**A figure looks stale.** Every screen carries the month and the first twelve
characters of the book hash it was computed from. If two disagree, the book
was regenerated and something was not rebuilt — run the bootstrap, which
reconciles the views against the book and rebuilds on disagreement rather
than reporting it.

**A dashboard is slow the first time.** The warm-up has not finished. It will
be fast from the second reader onwards regardless.
