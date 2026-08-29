# Running the Intelligence Factory locally

Everything in this runbook is **offline**. No step calls Anthropic, none needs
an API key, and none spends credits. That is not a limitation of the local
setup — it is how the factory is built: retrieval, packs, routing, policy,
evaluation and the release gate are all deterministic, and the one place a live
model is involved (`scripts/verify-live-ai.ps1`) is deliberately a separate
tool with its own confirmation.

If a command here asks you for a key, something is wrong. Stop and say so.

---

## 1. What you need

| | |
|---|---|
| Python | 3.13, in `.venv` |
| PostgreSQL | 16, reachable on `DATABASE_URL` |
| Node | 20+, for the frontend only |
| Docker | optional — see §6 |

Windows PowerShell and Linux/macOS bash both work. Where they differ the
PowerShell line is given second.

---

## 2. First run

```bash
.venv/bin/python -m alembic upgrade head
.venv/bin/python scripts/seed_teaching_library.py
```

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe scripts\seed_teaching_library.py
```

The seed writes every case the factory offers — the migrated corpora and the
canonical blueprints — at whatever status their own validators allow.

**A freshly seeded library retrieves nothing.** That is correct. Production
retrieval serves `APPROVED` cases (and `SYSTEM_VALIDATED` where explicitly
governed), and nothing is approved until a person approves it. If the Studio
shows 1,828 cases and zero retrievable, the system is working.

Re-running is safe: a case whose stored body already matches is left alone, so
the version history does not fill with changes nobody made.

### What the library actually contains

```bash
.venv/bin/python -c "from backend.db.engine import SessionLocal; \
from backend.services import teaching_library as tl; \
s=SessionLocal(); print(tl.governance(s)['sentence']); s.close()"
```

The sentence names how many cases carry a **named human approval**, how many
are retrievable, and how many were written by hand rather than instantiated
from blueprints, migrated or derived from method contracts. No case is
described as human reviewed without an approval record.

---

## 3. The Retrieval Lab, without a browser

`POST /api/v1/intelligence/retrieval-lab` needs no provider. From Python:

```bash
.venv/bin/python - <<'PY'
from backend.db.engine import SessionLocal
from backend.services import teaching_library as tl
from backend.teaching import retrieval as rv, pack as tp
from sqlalchemy import select
from backend.models.platform import TeachingCase as Row

session = SessionLocal()
cases = [tl.to_case(r) for r in session.execute(select(Row)).scalars()]
session.close()

need = rv.Need(question="Decompose the ECL change in Contracting over the "
                        "latest year.",
               capability="ANALYSIS", concepts=("expected credit loss",))
found = rv.retrieve(cases, need)
for entry in found.entries:
    print(f"{entry.relevance_score:.3f}  {entry.case_id}  {entry.why_retrieved}")
print("refused:", found.refused)
print("pack tokens:", sum(p.estimated_tokens() for p in tp.build(found.cases)))
PY
```

The `refused` counts are the half worth reading. A request that retrieves
nothing is normal; the only way to tell a correct nothing from a broken one is
to see which filter fired.

---

## 4. Experiments — estimate first, always

Every batch **refuses to run without an explicit confirmation**. That is a
parameter, not a convention: a caller who forgets gets an exception naming the
estimate rather than a bill.

```bash
.venv/bin/python - <<'PY'
from intelligence_factory import experiments as ex
from intelligence_factory.teaching import canonical as cn

cases = cn.cases()
print(ex.estimate(cases, arms=[ex.BASELINE, ex.CANDIDATE_B],
                  price=ex.Price(input_per_1k=0.003,
                                 output_per_1k=0.015)).sentence())
PY
```

Read the sentence. Then, and only then, run the batch with `confirmed=True`.
Results append to a JSONL as they arrive, so a run that dies at case four
hundred of five hundred resumes rather than re-spending the four hundred.

### Comparing arms

`ex.compare(baseline, [candidate])` applies §30's rule in §30's order:

1. **critical regressions end it** — an arm two points better overall and newly
   wrong on one grounding case has moved the failure somewhere nobody was
   looking;
2. **precision must clear the baseline with its interval**, not with its point
   estimate;
3. among survivors, the largest margin wins.

`decision: "keep the baseline"` is the normal outcome and not a failure.

### Choosing thresholds

`ex.sweep(development_cases, runner_for)` searches the routing policy grid on
the **development** set. Split first, and split on clusters:

```bash
.venv/bin/python -c "from intelligence_factory.teaching import variants as vr, canonical as cn; \
d,e = vr.split(cn.cases()); print(len(d),'development /',len(e),'evaluation')"
```

A random split puts *"What is total EAD by sector?"* in development and
*"By sector, total EAD?"* in evaluation, and the resulting score measures
paraphrase matching.

**The sealed holdout is touched once, after selection.** Nothing in
`backend/` or in the tuning path can import it, and an import-graph test
enforces that. A threshold tuned against the holdout measures the tuning.

Freeze what you chose:

```bash
.venv/bin/python -c "from intelligence_factory import experiments as ex; \
from backend.teaching import policy as pol; \
print(ex.freeze_policy(pol.default(), path=__import__('pathlib').Path('teaching_release/routing_policy.json')))"
```

---

## 5. Cutting a Teaching Release

```bash
.venv/bin/python - <<'PY'
from pathlib import Path
from sqlalchemy import select
from backend.db.engine import SessionLocal
from backend.models.platform import TeachingCase as Row
from backend.services import teaching_library as tl
from backend.teaching import release as rl
import subprocess

sha = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                     text=True).stdout.strip()
session = SessionLocal()
cases = [tl.to_case(r) for r in session.execute(select(Row)).scalars()]
session.close()

payload = rl.build(cases, git_sha=sha)
path = rl.freeze(payload)
print("frozen:", path)
print("gate:", rl.gate(require_release=True).to_dict()["state"])
PY
```

The gate will say `TEACHING RELEASE UNAVAILABLE` until somebody approves it:

```bash
.venv/bin/python -c "from backend.teaching import release as rl; \
print(rl.approve(rl.latest(), reviewers=['<your name>'], note='<why>').certification_status)"
```

A release **cannot be overwritten**. A change makes a new one, because every
Trace naming a release becomes unverifiable the moment the release it names can
be rewritten.

The four gate states mean four different things:

| State | Meaning |
|---|---|
| `APPROVED` | Production may serve from it. |
| `STALE` | It exists, but the code, ontology, prompts or routing policy moved. Worse than no release, because it looks like one. |
| `TEACHING RELEASE UNAVAILABLE` | Production wants a release and there is not one. Retrieval returns nothing. |
| `UNRELEASED TEACHING LIBRARY` | Development, off the live library. Allowed, and labelled. |

---

## 6. Docker

```bash
docker compose up -d db
docker compose run --rm api .venv/bin/python -m alembic upgrade head
docker compose run --rm api .venv/bin/python scripts/seed_teaching_library.py
docker compose up -d
```

```powershell
docker compose up -d db
docker compose run --rm api .venv/bin/python -m alembic upgrade head
docker compose run --rm api .venv/bin/python scripts/seed_teaching_library.py
docker compose up -d
```

`ANTHROPIC_API_KEY` is **not required** for any of the above. Leave it unset
and the product runs in its deterministic offline mode, which is the supported
way to run it and the way every command in this runbook is exercised.

---

## 7. The gates before you push

```bash
.venv/bin/ruff check backend/ tests/ intelligence_factory/ scripts/
.venv/bin/python -m pytest
cd frontend && npm run lint && npm test && npm run build
```

```powershell
.\.venv\Scripts\ruff.exe check backend\ tests\ intelligence_factory\ scripts\
.\.venv\Scripts\python.exe -m pytest
cd frontend; npm run lint; npm test; npm run build
```

Note that the test suite **empties the teaching library** — the fixtures delete
from `teaching_cases` before and after. Re-seed afterwards if you want the
Studio populated:

```bash
.venv/bin/python scripts/seed_teaching_library.py
```

---

## 8. What not to do

- **Do not tune against the sealed holdout.** It is touched once, after
  selection, and a number produced any other way is not an estimate of
  anything.
- **Do not approve in bulk.** An approval carries a reason for as long as the
  case survives, and every answer served from the case inherits it.
- **Do not label a generated case human reviewed.** `authoring_method` says
  what a case is: `BLUEPRINT`, `MIGRATED`, `DERIVED_FROM_CONTRACT`, `VARIANT`
  or `HUMAN`. The governance report counts them separately for a reason.
- **Do not run a batch without reading the estimate.** The confirmation exists
  because the alternative is finding out afterwards.
