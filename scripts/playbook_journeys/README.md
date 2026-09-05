# Playbook journeys

Three harnesses that exercise the Committee Pack Intelligence System the way a
person does, against a running stack rather than through the test client.
Nothing here uses a fixture, a mock, or the ORM: every step is an HTTP request
over a socket, or a real browser driving the built application.

They are separate from `tests/playbook` on purpose. The pytest suite proves the
rules; these prove the product runs.

## What you need first

    # 1. the backend, on the port the frontend build expects
    .venv/bin/python -m uvicorn backend.api.main:app --host 127.0.0.1 --port 8000

    # 2. the three demonstration committees
    .venv/bin/python scripts/seed_playbook_committees.py --reset

    # 3. for the browser journeys only, the built frontend
    cd frontend && npx next build && npx next start -p 3000

Port 3000 matters: the backend's CORS list names it, and a browser on another
port cannot reach the API at all — the application renders with no data and no
sign-in screen.

`tests/playbook/test_demo_seed.py` rebuilds the demonstration committees and
removes them again when it finishes, so **run the seed again after running the
test suite** or these journeys will find nothing.

## Running them

    .venv/bin/python scripts/playbook_journeys/api_journeys.py       # A-J
    .venv/bin/python scripts/playbook_journeys/followup_journeys.py  # K-O
    CHROMIUM_PATH=/path/to/chrome \
      .venv/bin/python scripts/playbook_journeys/browser_journeys.py # P-T

Each exits non-zero on the first failing expectation and prints every check it
made. `CREDITPROBE_API`, `CREDITPROBE_APP`, `CREDITPROBE_SHOTS` and
`CHROMIUM_PATH` override the defaults.

## Against the containers

Those overrides exist so the same twenty journeys can be run against
`docker compose up` without changing a line, and they should be — the image is
what a client installs, and it is not the same environment as a developer's
machine. Two defects in this phase existed only there: a library the Playbook
imported and no requirements file named, and a bootstrap step that failed in a
way which stopped the web container from ever starting.

    docker compose up -d
    docker exec ipm-backend python scripts/seed_playbook_committees.py

    CREDITPROBE_API=http://127.0.0.1:8000 \
      .venv/bin/python scripts/playbook_journeys/api_journeys.py
    CREDITPROBE_API=http://127.0.0.1:8000 \
      .venv/bin/python scripts/playbook_journeys/followup_journeys.py
    CREDITPROBE_APP=http://127.0.0.1:3000 CHROMIUM_PATH=/path/to/chrome \
      .venv/bin/python scripts/playbook_journeys/browser_journeys.py

Wait for the backend container to report `healthy` rather than for its port to
open: the health check reads the bootstrap's own verdict, so `healthy` means
there is a demonstrable product behind it. The web container waits on that
health, so if it never starts, the backend's health output names the step that
failed.

Journey L needs a Planner project to hand an action to. A fresh container
database has none, so create one first:

    curl -s -c jar -X POST $API/api/v1/auth/login -H 'Content-Type: application/json' \
      -d '{"username":"alex.rahman","password":"creditprobe-demo"}'
    curl -s -b jar -X POST $API/api/v1/planner/projects -H 'Content-Type: application/json' \
      -d '{"code":"CJ-FOLLOWUP","name":"Committee follow-up","start_date":"2026-01-01"}'

The port note above applies to the separate-process path only. Through the
containers the browser only ever talks to the frontend origin, which proxies
the API server-side, so there is no CORS constraint to satisfy.

## The journeys

| | What it proves |
|---|---|
| A | A member opens a committee and finds this cycle's pack |
| B | The pack reads as a pack: sections, blocks, calculated figures |
| C | Every number opens to its working — metric, period, formula hash, dataset |
| D | Readiness is a gate with named checks, not a badge |
| E | Findings are answered and reopened; a dismissal without a reason is refused |
| F | The published pack carries its own governance history |
| G | Comparison against the previous cycle, with the direction read correctly |
| H | The pack downloads as PDF, Word, slides and the evidence workbook |
| I | Another committee's pack is refused by id; an observer reads and cannot write |
| J | Signed out is signed out, on every route |
| K | A decision is raised and its outcome recorded with conditions |
| L | An action leaves with an owner and a date, closes on evidence, reaches the Planner |
| M | An inbound file is checked before it is opened; hostile ones are refused |
| N | No exported cell can begin an Excel formula |
| O | A formula posted into a pack comes back inert, and `<Finance> Review` survives |
| P | Signing in, and the Playbook a member sees |
| Q | Opening a committee and its pack in the browser |
| R | The screen shows real calculated figures, not placeholders |
| S | A number opens to its working on screen |
| T | No page error, no console error, nothing saying TODO |
