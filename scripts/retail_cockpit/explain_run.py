#!/usr/bin/env python3
"""What a run actually did, recovered from the store. Read-only.

    .venv/bin/python scripts/retail_cockpit/explain_run.py --question 2

Why this exists
---------------
When a live answer is wrong, the question is never "what does the code do" --
it is "what did THIS run do". The engine already writes everything needed to
answer that: the run record carries the published response, `messages` carries
the provider transcript including the starting packet and every tool call, and
`events` carries the public operations in order. Nothing here is inferred.

It opens the database `mode=ro` and constructs no client: it cannot spend, and
it cannot alter the evidence it is reading.

What it reports, per the questions a denomination or grain failure raises:

  A  thread_id and run_id
  B  the published response: disposition, narrative, numeric_claims
  C  every executed statement, in order
  D  which money column each statement selected: `*_sar` or `*_sar_mn`
  E  the values that came back
  F  the model-visible starting packet (sizes, and the steering text in it)
  G  the relation grain text the model was shown
  H  whether the packet carried the facility-grain denomination rule
  I  whether the catalogue was inspected before anything was executed
  J  whether validation or repair said anything about grain or denomination
  K  whether a riyal execution was converted at the end, or the millions
     column was selected in the SQL from the start
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

#: A money column in this book, either denomination.
MONEY = re.compile(r"\b([a-z_]*?(?:balance|ead|ecl|limit|income|overdue|"
                   r"undrawn|recovery|write_off|drawn)[a-z_]*?_sar(_mn)?)\b")
#: The rule the projection publishes on every money relation's grain.
RULE = "are for portfolio and segment totals only"


def _open(database: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True,
                                 timeout=5.0)
    connection.row_factory = sqlite3.Row
    return connection


def _blocks(content: Any) -> list[dict[str, Any]]:
    """A message's content as a list of blocks, whatever shape it is in."""
    if isinstance(content, list):
        return [b for b in content if isinstance(b, dict)]
    if isinstance(content, dict):
        return [content]
    return []


def _text_of(content: Any) -> str:
    if isinstance(content, str):
        return content
    out = []
    for block in _blocks(content):
        for key in ("text", "content", "input", "output"):
            value = block.get(key)
            if isinstance(value, str):
                out.append(value)
            elif value is not None:
                out.append(json.dumps(value, default=str))
    return "\n".join(out)


def _tool_calls(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every tool the analyst invoked, in order, with its input."""
    calls = []
    for message in messages:
        for block in _blocks(message.get("content")):
            if block.get("type") == "tool_use" or "name" in block and \
                    "input" in block:
                calls.append({"name": block.get("name", ""),
                              "input": block.get("input", {})})
    return calls


def _statements(calls: list[dict[str, Any]]) -> list[str]:
    out = []
    for call in calls:
        body = call.get("input")
        if not isinstance(body, dict):
            continue
        for key in ("sql", "statement", "query"):
            value = body.get(key)
            if isinstance(value, str) and value.strip():
                out.append(value.strip())
    return out


def money_columns(sql: str) -> list[str]:
    return sorted({m.group(1) for m in MONEY.finditer(sql)})


def report(database: Path, question: str, run_id: str = "") -> int:
    connection = _open(database)
    try:
        if run_id:
            row = connection.execute("SELECT * FROM runs WHERE run_id=?",
                                     (run_id,)).fetchone()
        else:
            rows = connection.execute(
                "SELECT * FROM runs WHERE question=? ORDER BY created_at DESC",
                (question,)).fetchall()
            answered = [r for r in rows if str(r["state"]) == "COMPLETED"
                        and r["final_response"]]
            row = (answered or rows or [None])[0]
        if row is None:
            print(f"No run of that question in {database}.")
            return 1

        run = dict(row)
        print("=" * 72)
        print("A. THE RUN")
        print("=" * 72)
        print(f"  question    {run['question']}")
        print(f"  thread_id   {run['thread_id']}")
        print(f"  run_id      {run['run_id']}")
        print(f"  state       {run['state']}  {run['error_code'] or ''}")
        print(f"  release     {run['release_id']}")
        print(f"  created     {run['created_at']}")
        cost = connection.execute(
            "SELECT COALESCE(SUM(COALESCE(settled_usd, reserved_usd)), 0.0)"
            " FROM reservations WHERE run_id=?", (run["run_id"],)).fetchone()
        print(f"  cost USD    {float(cost[0] or 0.0):.5f}")
        print(f"  budget      {run['budget']}")

        final = json.loads(run["final_response"] or "{}")
        print()
        print("=" * 72)
        print("B. WHAT IT PUBLISHED")
        print("=" * 72)
        print(f"  disposition {final.get('disposition')}")
        print(f"  narrative   {final.get('narrative')}")
        print("  numeric_claims:")
        print(json.dumps(final.get("numeric_claims") or [], indent=4)[:4000])
        for key in ("tables", "limitations", "coverage"):
            if final.get(key):
                print(f"  {key}: "
                      f"{json.dumps(final[key], default=str)[:1500]}")

        raw = connection.execute(
            "SELECT ordinal, role, content FROM messages WHERE run_id=?"
            " ORDER BY ordinal", (run["run_id"],)).fetchall()
        transcript = [{"role": r["role"],
                       "content": _maybe_json(r["content"])} for r in raw]

        calls = _tool_calls(transcript)
        statements = _statements(calls)

        print()
        print("=" * 72)
        print("C / D. WHAT IT EXECUTED, AND WHICH MONEY COLUMN")
        print("=" * 72)
        if not statements:
            print("  No statement found in the stored transcript.")
            print(f"  ({len(transcript)} transcript rows, "
                  f"{len(calls)} tool calls)")
        for i, sql in enumerate(statements, 1):
            columns = money_columns(sql)
            millions = [c for c in columns if c.endswith("_sar_mn")]
            riyals = [c for c in columns if c.endswith("_sar")]
            print(f"\n  --- statement {i} ---")
            print("  " + sql.replace("\n", "\n  ")[:2500])
            print(f"  money columns : {columns or 'none'}")
            print(f"  DENOMINATION  : "
                  f"{'MILLIONS (*_sar_mn)' if millions else ''}"
                  f"{' and ' if millions and riyals else ''}"
                  f"{'RIYALS (*_sar)' if riyals else ''}"
                  f"{'none' if not columns else ''}")

        print()
        print("=" * 72)
        print("E. WHAT CAME BACK")
        print("=" * 72)
        for art in connection.execute(
                "SELECT * FROM artifacts WHERE run_id=? ORDER BY rowid",
                (run["run_id"],)).fetchall():
            body = _maybe_json(dict(art).get("body") or "{}")
            print(f"  artifact {dict(art).get('artifact_id')} "
                  f"{dict(art).get('kind')}")
            print("  " + json.dumps(body, default=str)[:2500])

        print()
        print("=" * 72)
        print("F / G / H. THE PACKET THE MODEL SAW")
        print("=" * 72)
        packet = "\n".join(_text_of(m["content"]) for m in transcript
                           if m["role"] in ("system", "user"))
        print(f"  transcript rows      {len(transcript)}")
        print(f"  packet chars         {len(packet)}")
        grains = re.findall(r"one row per retail [a-z]+ per reporting month"
                            r"[^\"]*", packet)
        print(f"  grain strings shown  {len(grains)}")
        if grains:
            print("\n  G. the grain text the model was shown:")
            print("     " + grains[0][:600])
        print(f"\n  H. carries the facility-grain denomination rule: "
              f"{RULE in packet}  ({packet.count(RULE)} occurrences)")
        print(f"     'SAR 0 million' warnings       : "
              f"{packet.count('SAR 0 million')}")
        print(f"     'in SAR million' measure text  : "
              f"{packet.count('in SAR million')}")
        for column in ("balance_sar_mn", "balance_sar", "ead_sar_mn",
                       "ead_sar"):
            bare = packet.count(column)
            if column.endswith("_sar"):
                bare -= packet.count(column + "_mn")
            print(f"     names {column:16} : {bare}")

        print()
        print("=" * 72)
        print("I / J. THE ORDER OF OPERATIONS")
        print("=" * 72)
        print("  tool calls, in order:")
        for i, call in enumerate(calls, 1):
            print(f"    {i:2}. {call.get('name')}")
        names = [c.get("name", "") for c in calls]
        executed = next((i for i, n in enumerate(names)
                         if "execute" in n.lower()), None)
        inspected = next((i for i, n in enumerate(names)
                          if "catalog" in n.lower()), None)
        print(f"\n  I. inspect_catalog called        : {inspected is not None}")
        if inspected is not None and executed is not None:
            print(f"     ...before the first execution : {inspected < executed}")
        print("\n  J. events mentioning grain, denomination, repair or "
              "validation:")
        said = False
        for ev in connection.execute(
                "SELECT seq, payload FROM events WHERE run_id=? ORDER BY seq",
                (run["run_id"],)).fetchall():
            body = json.loads(ev["payload"])
            blob = json.dumps(body, default=str).lower()
            if any(word in blob for word in
                   ("grain", "denomination", "million", "repair",
                    "validat", "reject")):
                said = True
                print(f"    seq {ev['seq']:3} {body.get('event_type')} "
                      f"{body.get('operation')} :: "
                      f"{str(body.get('public_message'))[:220]}")
        if not said:
            print("    nothing. No validation or repair raised the grain or "
                  "the denomination.")

        print()
        print("=" * 72)
        print("K. SQL OR FINALIZATION?")
        print("=" * 72)
        all_money = sorted({c for s in statements for c in money_columns(s)})
        millions = [c for c in all_money if c.endswith("_sar_mn")]
        riyals = [c for c in all_money if c.endswith("_sar")]
        claims = [c.get("decimal_value") for c in
                  (final.get("numeric_claims") or [])]
        print(f"  columns executed : {all_money or 'none found'}")
        print(f"  claims published : {claims[:12]}")
        if millions and not riyals:
            print("\n  VERDICT: the millions column was selected IN THE SQL. "
                  "Finalization did not convert anything -- it published, at "
                  "no decimal places, what the query returned.")
        elif riyals and not millions:
            print("\n  VERDICT: the SQL selected RIYALS. If the published "
                  "figures read as millions, the scale changed after "
                  "execution.")
        elif not all_money:
            print("\n  VERDICT: no money column found in the stored "
                  "statements; read C above before concluding anything.")
        else:
            print("\n  VERDICT: both denominations appear in the SQL. Read "
                  "the statements above.")
        return 0
    finally:
        connection.close()


def _maybe_json(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return value
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=None,
                        help="the state database. Defaults to the one this "
                             "configuration points the engine at.")
    parser.add_argument("--question", default="",
                        help="a UAT question number, e.g. 2")
    parser.add_argument("--ask", default="", help="the question text itself")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--env-file",
                        default=str(ROOT / ".env.retail-candidate"))
    args = parser.parse_args()

    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "_check_live", ROOT / "scripts" / "retail_cockpit" / "check_live.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.apply_environment(args.env_file)

    from backend.retail_cockpit_host import spend

    database = args.db or spend.state_database()
    if not Path(database).exists():
        print(f"There is no state database at {database}.")
        return 1

    ask = args.ask
    if not ask and args.question:
        spec2 = importlib.util.spec_from_file_location(
            "_uat", ROOT / "scripts" / "retail_cockpit" / "run_uat.py")
        uat = importlib.util.module_from_spec(spec2)
        spec2.loader.exec_module(uat)
        match = [q for q in uat.QUESTIONS if str(q["n"]) == str(args.question)]
        if not match:
            print(f"The plan has no question {args.question!r}.")
            return 2
        ask = match[0]["ask"]
    if not ask and not args.run_id:
        print("Give --question N, --ask '...' or --run-id.")
        return 2
    return report(Path(database), ask, args.run_id)


if __name__ == "__main__":
    raise SystemExit(main())
