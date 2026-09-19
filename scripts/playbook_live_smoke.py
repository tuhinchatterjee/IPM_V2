"""
The minimal live smoke for Direct Chat. Five steps, bounded and resumable.

    .venv/bin/python scripts/playbook_live_smoke.py --plan     # what it costs
    .venv/bin/python scripts/playbook_live_smoke.py            # run it
    .venv/bin/python scripts/playbook_live_smoke.py --resume   # after a failure

This is the ONLY paid path in the Playbook work. Everything else — the unit
suite, the route journeys, the eleven browser journeys — runs against a
scripted provider and costs nothing.

What it covers, and nothing more:

    1  an ordinary question, which must call no document tool
    2  a question about an attachment, which must create no file
    3  an explicit report request, in Word and PDF
    4  one follow-up revision
    5  one conversion of the saved report

Five steps because those are the five behaviours that can only be proven with
a real model: that it answers rather than authors, that it reads an
attachment, that it reaches for a tool when asked for a document, that it
edits the document already there, and that a conversion spends nothing.

Bounded
-------
It declares the calls it intends before spending any, stops at the first
failure with the diagnosis preserved, and refuses to start without a
credential rather than reporting a skip as a pass. `--max-calls` is a hard
ceiling; the run aborts rather than exceeding it.

Resumable
---------
Every completed step is written to `docs/playbook/live_smoke.json` with its
workspace, request ids and timings. `--resume` continues in the same workspace
and re-runs only what has not passed, so a failure at step 4 costs one call to
retry rather than four. Chapter 31: do not pay for the same journey twice.
"""

from __future__ import annotations

import argparse
import io
import json
import pathlib
import sys
import time

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

STATE = REPO / "docs" / "playbook" / "live_smoke.json"

#: One provider call each, except the report, which spends a second on the
#: authoring tool the assistant reaches for. Declared before anything is spent.
PLAN = [
    ("question", "an ordinary question — must call no tool", 1),
    ("attachment", "a question about an uploaded methodology — no file", 1),
    ("report", "an explicit report request in Word and PDF", 2),
    ("revision", "one scoped follow-up revision", 2),
    ("conversion", "one conversion of the saved report — no authoring call", 1),
]

STEPS = [name for name, _, _ in PLAN]


def _load() -> dict:
    if STATE.is_file():
        try:
            return json.loads(STATE.read_text())
        except Exception:  # noqa: BLE001 — a corrupt file starts fresh
            pass
    return {"workspace_id": None, "steps": {}, "calls": 0}


def _save(state: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=2, default=str) + "\n")


def _methodology() -> bytes:
    from docx import Document

    doc = Document()
    doc.add_heading("Scorecard methodology", level=1)
    doc.add_paragraph(
        "The target is ninety days past due observed within twelve months of "
        "origination. Exclusions are staff accounts and accounts closed "
        "within the observation window.")
    doc.add_heading("Sampling", level=2)
    doc.add_paragraph(
        "Development and holdout partitions are assigned at random, "
        "stratified by origination month. Reject inference is not described.")
    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


def _print_plan(state: dict) -> None:
    done = {k for k, v in state["steps"].items() if v.get("ok")}
    print("Planned provider calls, before anything is spent:\n")
    total = 0
    for name, what, calls in PLAN:
        mark = "done" if name in done else "    "
        if name not in done:
            total += calls
        print(f"  [{mark}] {name:<11} {what:<52} ~{calls} call(s)")
    print(f"\n  Remaining this run: ~{total} provider call(s).")
    print("  Nothing else in the Playbook work makes a paid call.")


# ==========================================================================


def _run_step(client, state: dict, name: str, *, workspace: int,
              text: str, source_ids=None) -> dict:
    """One turn, timed, with everything worth reporting kept."""
    began = time.monotonic()
    body = {"text": text, "idempotency_key": f"live:{workspace}:{name}"}
    if source_ids:
        body["source_ids"] = source_ids
    response = client.post(
        f"/api/v1/playbook/workspaces/{workspace}/messages", json=body,
        timeout=900)
    elapsed = round(time.monotonic() - began, 1)

    if response.status_code not in (200, 201):
        return {"ok": False, "elapsed_s": elapsed,
                "status": response.status_code, "detail": response.text[:800]}

    payload = response.json()
    thread = client.get(f"/api/v1/playbook/workspaces/{workspace}").json()
    message = next((m for m in reversed(thread["messages"])
                    if m["role"] == "assistant"), {})
    content = message.get("content") or {}
    del state
    return {
        "ok": True,
        "elapsed_s": elapsed,
        "model_served": message.get("model", ""),
        "request_ids": message.get("request_ids") or [],
        "tools": content.get("tools") or [],
        "files": payload.get("files") or [],
        "said": (content.get("text") or "")[:400],
        "artifacts": [
            {"version": v["version"],
             "formats": sorted(f["format"] for f in v["files"])}
            for a in thread.get("artifacts") or [] for v in a["versions"]],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", action="store_true",
                        help="print the intended calls and spend nothing")
    parser.add_argument("--resume", action="store_true",
                        help="continue the recorded run, skipping passed steps")
    parser.add_argument("--max-calls", type=int, default=8,
                        help="hard ceiling; the run aborts rather than exceed it")
    parser.add_argument("--only", action="append", choices=STEPS,
                        help="run only these steps (repeatable)")
    args = parser.parse_args()

    state = _load() if args.resume else {"workspace_id": None, "steps": {},
                                         "calls": 0}
    if args.plan:
        _print_plan(state)
        return 0

    from backend.playbook import provider

    status = provider.status()
    if not status.configured:
        print("CANNOT RUN: " + (status.reason or "no provider is configured."))
        print("Live verification is UNVERIFIED, not passed.")
        return 2
    if status.scripted:
        print("CANNOT RUN: this server is answering from a script.")
        print("A scripted run is not live verification.")
        return 2

    _print_plan(state)
    print()

    from fastapi.testclient import TestClient

    from backend.api.main import create_app

    wanted = args.only or STEPS
    results: dict = dict(state["steps"])
    spent = 0

    with TestClient(create_app()) as client:
        client.headers.update({"X-IPM-Role": "ADMIN", "X-IPM-User-Id": "1"})

        workspace = state.get("workspace_id")
        if not workspace:
            created = client.post("/api/v1/playbook/workspaces",
                                  json={"title": "Live smoke — Direct Chat"})
            workspace = created.json()["id"]
            state["workspace_id"] = workspace
            _save(state)
        print(f"Workspace {workspace}\n")

        source_id = state.get("source_id")

        for name, what, calls in PLAN:
            if name not in wanted:
                continue
            if results.get(name, {}).get("ok"):
                print(f"  skip  {name} — already passed")
                continue
            if spent + calls > args.max_calls:
                print(f"  STOP  {name} would exceed --max-calls "
                      f"({args.max_calls}). Nothing further was spent.")
                break

            print(f"  run   {name} — {what}", flush=True)

            if name == "attachment" and not source_id:
                upload = client.post(
                    f"/api/v1/playbook/workspaces/{workspace}/sources",
                    files={"file": ("methodology.docx",
                                    io.BytesIO(_methodology()),
                                    "application/vnd.openxmlformats-"
                                    "officedocument.wordprocessingml.document")},
                    data={"source_role": "methodology"})
                if upload.status_code != 201:
                    results[name] = {"ok": False,
                                     "detail": f"upload: {upload.text[:400]}"}
                    break
                source_id = upload.json()["id"]
                state["source_id"] = source_id
                _save(state)

            prompt = {
                "question": "What is the difference between a scorecard "
                            "development report and a scorecard validation "
                            "report?",
                "attachment": "Summarise the attached methodology and tell me "
                              "what appears incomplete. Do not create a file.",
                "report": "Using the attached methodology, create a detailed "
                          "scorecard development report in Word and PDF.",
                "revision": "Shorten the executive summary and make it more "
                            "committee-ready. Change nothing else.",
                "conversion": "Give me a PDF of the latest Word report.",
            }[name]

            outcome = _run_step(
                client, state, name, workspace=workspace, text=prompt,
                source_ids=[source_id] if name == "attachment" else None)
            spent += calls
            state["calls"] = state.get("calls", 0) + calls

            # What each step is actually FOR, checked rather than assumed.
            if outcome.get("ok"):
                tools = [t["name"] for t in outcome["tools"]]
                if name in ("question", "attachment"):
                    if tools or outcome["files"]:
                        outcome["ok"] = False
                        outcome["detail"] = (
                            f"expected no document work; got tools={tools} "
                            f"files={len(outcome['files'])}")
                if name == "report":
                    formats = {f for a in outcome["artifacts"]
                               for f in a["formats"]}
                    if not {"docx", "pdf"} <= formats:
                        outcome["ok"] = False
                        outcome["detail"] = f"expected docx and pdf; got {formats}"
                if name == "revision":
                    versions = {a["version"] for a in outcome["artifacts"]}
                    if len(versions) < 2:
                        outcome["ok"] = False
                        outcome["detail"] = (
                            f"expected a second version; got {sorted(versions)}")
                if name == "conversion" and "convert_document" not in tools:
                    outcome["ok"] = False
                    outcome["detail"] = (
                        f"expected a conversion rather than re-authoring; "
                        f"tools={tools}")

            results[name] = outcome
            state["steps"] = results
            _save(state)

            mark = "PASS" if outcome.get("ok") else "FAIL"
            print(f"        {mark}  {outcome.get('elapsed_s', '?')}s  "
                  f"model={outcome.get('model_served', '?')}  "
                  f"requests={outcome.get('request_ids', [])}  "
                  f"tools={[t['name'] for t in outcome.get('tools', [])]}")
            if not outcome.get("ok"):
                print(f"        {outcome.get('detail') or outcome}")
                print("\n  Stopped at the first failure. The workspace and the "
                      "diagnosis are preserved; fix it offline, then "
                      "--resume.")
                break

    print("\n" + "=" * 72)
    passed = [n for n in STEPS if results.get(n, {}).get("ok")]
    failed = [n for n in STEPS if n in results and not results[n].get("ok")]
    not_run = [n for n in STEPS if n not in results]
    print(f"passed: {passed}")
    print(f"failed: {failed}")
    print(f"not run: {not_run}   (not run is not passed)")
    print(f"provider calls this run: {spent}; recorded total: "
          f"{state.get('calls', 0)}")
    print(f"evidence: {STATE.relative_to(REPO)}")
    _save(state)
    return 1 if failed else (0 if not not_run else 3)


if __name__ == "__main__":
    raise SystemExit(main())
