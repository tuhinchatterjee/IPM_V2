"""
The ten mandatory Phase 0 regression threads. P0.16.

Run against a LIVE stack, through the same Investigation and Risk Case
endpoints the browser calls — not against the modules directly. A thread that
passes in a unit test and fails through the API is a thread that passes in a
place no user stands.

    scripts/dev.sh api          # or: python -m backend.api
    REQUIRE_LOGIN=false PYTHONPATH=. python scripts/phase0_threads.py

Threads 6 and 7 are ORDER DEPENDENT and the script keeps them that way: 6
checks what the Cockpit says before any review has run, so it clears the
agentic tables first; 7 runs a real review and checks the counts reconcile to
the cases it opened. Running 7 alone would pass against whatever happened to
be in the database, which is not the thing being tested.

Exit code is the number of failing threads, so CI can use it directly.
"""

# ruff: noqa: E402 - the threads run in ORDER and each imports only what it
# needs at the point it needs it. Hoisting a database import above the API
# threads that never touch one would obscure which thread depends on what.
import json
import re
import sys
import urllib.request

API = "http://127.0.0.1:8000/api/v1"

def post(path, body, timeout=600):
    req = urllib.request.Request(
        API + path, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "{}")

def get(path, timeout=300):
    try:
        with urllib.request.urlopen(API + path, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "{}")

def ask(question):
    return post("/investigations", {"question": question})

RESULTS = []
def record(n, title, ok, detail):
    RESULTS.append((n, title, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  THREAD {n}: {title}")
    print(f"      {detail}")

def narrative(run):
    return json.dumps(run.get("narrative") or {})

def prose_of(run):
    n = run.get("narrative") or {}
    parts = [n.get("direct_answer",""), n.get("summary",""), n.get("interpretation","")]
    parts += [f.get("text","") for f in (n.get("findings") or [])]
    parts += list(n.get("caveats") or [])
    return "\n".join(p for p in parts if p)

def step0(run):
    steps = run.get("steps") or []
    return (steps[0].get("result") or {}) if steps else {}

# ---------------------------------------------------------------- THREAD 1
Q1 = ("Which customers experienced a rating downgrade, an increase in ECL of "
      "more than 20%, worsening DPD and declining covenant headroom over the "
      "latest year? Rank them by EAD.")
code, body = ask(Q1)
run = body.get("run") or {}
clar = (run.get("clarification") or "") or body.get("clarification") or ""
prose = prose_of(run)
asked_them = bool(re.search(r'what .{0,20}\bthem\b|who .{0,10}\bthem\b|by "them"', clar + prose, re.I))
record(1, "same-turn referent: must not ask what 'them' means",
       code in (200, 201) and body.get("status") == "succeeded" and not asked_them,
       f"HTTP {code}, status={body.get('status')}, asked-about-them={asked_them}, "
       f"rows={step0(run).get('input_row_count')}")

# ---------------------------------------------------------------- THREAD 2
Q2 = ("Identify customers whose internal rating deteriorated over the latest "
      "year and determine whether leverage, DSCR, ECL coverage and DPD "
      "deteriorated alongside the downgrade. Compare them with customers "
      "whose ratings were unchanged.")
code, body = ask(Q2)
run = body.get("run") or {}
text = (prose_of(run) + json.dumps(run.get("plan") or {})).lower()
two_cohorts = ("unchanged" in text or "compare" in text) and "downgrad" in text
record(2, "two same-turn cohorts",
       code in (200, 201) and body.get("status") == "succeeded" and two_cohorts,
       f"HTTP {code}, status={body.get('status')}, two-cohorts={two_cohorts}")

# ---------------------------------------------------------------- THREAD 3
Q3 = ("Something seems wrong with Contracting. Investigate the sector across "
      "exposure, ratings, IFRS 9, delinquency, financial performance, "
      "covenants and collateral over the latest four quarters. Tell me what "
      "changed, what is driving it and which customers require attention.")
code, body = ask(Q3)
record(3, "broad investigation: no 500",
       code in (200, 201) and body.get("status") != "failed",
       f"HTTP {code}, status={body.get('status')}, "
       f"error={str(body.get('error') or '')[:80]}")

# ---------------------------------------------------------------- THREAD 4
Q4 = ("Decompose the change in total ECL over the latest year into changes "
      "associated with exposure, Stage migration, PD, LGD and portfolio mix. "
      "Show which sectors and customers contributed most.")
code, body = ask(Q4)
run = body.get("run") or {}
detail = (step0(run).get("detail") or {}).get("decomposition") or {}
recon = detail.get("reconciles")
record(4, "ECL decomposition reconciles",
       code in (200, 201) and recon is True,
       f"HTTP {code}, reconciles={recon}, movement={detail.get('movement')}, "
       f"attributed={detail.get('attributed')}, "
       f"components={len(detail.get('components') or [])}, "
       f"sectors={len(detail.get('sectors') or [])}, "
       f"customers={len(detail.get('customers') or [])}")

# ---------------------------------------------------------------- THREAD 5
Q5 = ("For every sector, calculate Stage 2 EAD share for the latest two "
      "periods and show the change.")
code, body = ask(Q5)
run = body.get("run") or {}
chart = step0(run).get("chart") or {}
cols = {c.get("name"): c for c in (step0(run).get("columns") or [])}
axis = chart.get("x") or ""
series = chart.get("series") or ""
measure_axis = any(
    (cols.get(a) or {}).get("semantic") in ("money","percent","ratio","count","days")
    for a in (axis, series) if a)
record(5, "chart must not use raw measure values as categories",
       code in (200, 201) and not measure_axis,
       f"HTTP {code}, chart={chart.get('chart')!r}, x={axis!r}, series={series!r}, "
       f"measure-on-axis={measure_axis}")

# ---------------------------------------------------------------- THREAD 6
# Cockpit attention BEFORE a proactive review: must say NOT_RUN, never
# "nothing requires attention".
import subprocess

subprocess.run(["/home/user/IPM_V2/.venv/bin/python", "-c",
    "from backend.db.engine import SessionLocal; from sqlalchemy import text; "
    "s=SessionLocal(); s.execute(text('DELETE FROM risk_case_events')); "
    "s.execute(text('DELETE FROM risk_case_links')); "
    "s.execute(text('DELETE FROM risk_cases')); "
    "s.execute(text('DELETE FROM agent_tasks')); "
    "s.execute(text('DELETE FROM agent_runs')); s.commit()"], check=False)
code, body = get("/risk-cases?period=Q2%202026")
review = body.get("review") or {}
sentence = body.get("summary") or body.get("sentence") or ""
record(6, "attention before any review says NOT_RUN",
       code in (200, 201) and review.get("state") == "NOT_RUN"
       and "nothing requires attention" not in sentence.lower(),
       f"HTTP {code}, state={review.get('state')!r}, sentence={sentence[:110]!r}")

# ---------------------------------------------------------------- THREAD 7
# After a successful review, counts and cases reconcile to current Risk Cases.
import subprocess

proc = subprocess.run(
    ["/home/user/IPM_V2/.venv/bin/python", "-c",
     "import os; os.environ['REQUIRE_LOGIN']='false';\n"
     "from backend.agentic import review as rv, runs;\n"
     "from backend.db.engine import SessionLocal;\n"
     "s=SessionLocal();\n"
     "row, out = rv.run(s, period='Q2 2026', trigger=runs.MANUAL_REVIEW, notify=False);\n"
     "s.commit();\n"
     "print(out.to_dict())"],
    capture_output=True, text=True, timeout=1800)
review_out = (proc.stdout or proc.stderr or "").strip().splitlines()[-1:] or [""]

code, body = get("/risk-cases?period=Q2%202026")
review = body.get("review") or {}
counts = body.get("counts") or {}
cases_listed = len(body.get("cases") or body.get("items") or [])
open_cases = review.get("open_cases")
by_level = sum(v for k, v in counts.items() if k != "ALL")
record(7, "after a review, counts reconcile to the Risk Cases",
       code in (200, 201)
       and review.get("state") in ("COMPLETED_WITH_CASES", "COMPLETED_NO_CASES")
       and open_cases == by_level == counts.get("ALL", by_level),
       f"state={review.get('state')!r}, open={open_cases}, by_level={by_level}, "
       f"ALL={counts.get('ALL')}, listed={cases_listed}, run={review_out[0][:60]}")

# ---------------------------------------------------------------- THREAD 8
# Force an agent task failure. The Trace cannot show VALIDATED.
from backend.agentic import consistency as cy


class _Step:
    def __init__(self, status, meta=None):
        self.status = status
        self.result = {"meta": meta or {}}

class _Investigation:
    def __init__(self, steps): self.steps = steps

evidence = cy.Evidence(analyses=0, results=0, checks_run=0, checks_passed=0,
                       checks_failed=0, conclusion_grounded=False,
                       actions=0, failures=["the task failed"])
stages = cy.derive(evidence)
validated = next((s for s in stages if s.stage == cy.VALIDATED), None)
status, why = cy.permit("PASS", evidence)
record(8, "a failed agent task cannot show VALIDATED",
       validated is not None and validated.state != cy.PASS
       and status != "PASS",
       f"VALIDATED={getattr(validated, 'state', None)!r}, "
       f"permit('PASS')={status!r}, why={why[:70]!r}")


# ---------------------------------------------------------------- THREAD 9
# No user-facing number may carry more than two decimals.
bad = []
for q in ["What is total ECL by sector?",
          "Show ECL coverage by stage.",
          "For every sector, show the Stage 2 EAD share.",
          Q4]:
    code, body = ask(q)
    run = body.get("run") or {}
    text = prose_of(run) + json.dumps(step0(run).get("rows") or [])
    # A displayed number with three or more decimals, ignoring ids/timestamps.
    for m in re.finditer(r"(?<![\w.:])(-?\d[\d,]*\.\d{3,})(?![\d.:])", prose_of(run)):
        bad.append((q[:40], m.group(1)))
record(9, "no user-facing prose number exceeds two decimals",
       not bad, f"offending={bad[:4] if bad else 'none'}")

# ---------------------------------------------------------------- THREAD 10
code, body = ask(Q4)
run = body.get("run") or {}
graph = run.get("trace") or {}
nodes = {n.get("id"): n for n in (graph.get("nodes") or [])}
gate = (nodes.get("presentability") or {}).get("config") or {}
sections = (gate.get("sections") or {}).get("sections") or []
record(10, "complex answer passes the client-presentability rubric",
       gate.get("verdict") == "SHOW" and len(sections) == 8,
       f"verdict={gate.get('verdict')!r}, sections={len(sections)}, "
       f"why={str(gate.get('why'))[:80]!r}")

print()
print("=" * 72)
passed = sum(1 for r in RESULTS if r[2])
failing = [r for r in RESULTS if not r[2]]
print(f"{passed} of {len(RESULTS)} threads passed")
for n, title, _ok, _ in failing:
    print(f"  FAILING: thread {n} — {title}")
sys.exit(len(failing))
