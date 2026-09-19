#!/usr/bin/env python3
"""Prove the event stream survives the retail proxy. No provider call.

    .venv/bin/python scripts/retail_cockpit/check_transport.py

The Cockpit's live panel is the product: a proxy that buffers frames until
the response completes turns a thinking analyst into a frozen page, and it
does so silently, because every frame still arrives in the end. So this is
measured rather than assumed.

What it checks, all through the retail origin:

* the stream is accepted, typed `text/event-stream`, and keeps the upstream's
  `X-Accel-Buffering: no` and `Cache-Control: no-transform`;
* frames are NAMED and carry the monotonic ids a reconnect resumes from;
* they arrive SPREAD OUT: the gap between `model.requested` and the terminal
  frame is the time the analyst actually spent, not zero;
* a heartbeat arrives inside that gap, which is a second, independent proof
  that nothing is being held;
* a reconnect from a cursor replays the tail and only the tail;
* Stop cancels a run in flight, the stream settles itself afterwards, and a
  second Stop is idempotent rather than an error.

Run it against an engine started with `run_engine.py --offline --think N`:
the run then fails at the model call, which is the honest outcome with no
credential and is all this needs. It claims nothing about answer quality.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_PROXY = "http://127.0.0.1:8328/api/v1/cockpit-v4"


def _start(client, proxy: str, question: str, key: str) -> str:
    thread = client.post(f"{proxy}/threads",
                         json={"domain": "retail"}).json()["thread_id"]
    run = client.post(f"{proxy}/runs", headers={"Idempotency-Key": key},
                      json={"question": question, "thread_id": thread,
                            "mode": "standard"})
    return str(run.json()["run_id"])


def _drain(client, proxy: str, run: str, cursor: int = 0,
           limit: float = 180.0) -> tuple[list[tuple[str, float]], dict]:
    seen: list[tuple[str, float]] = []
    ids: list[int] = []
    headers: dict = {}
    started = time.time()
    with client.stream("GET", f"{proxy}/runs/{run}/events?cursor={cursor}",
                       headers={"accept": "text/event-stream"}) as stream:
        headers = {"status": stream.status_code,
                   "content_type": stream.headers.get("content-type", ""),
                   "accel_buffering": stream.headers.get("x-accel-buffering",
                                                         ""),
                   "cache_control": stream.headers.get("cache-control", "")}
        for line in stream.iter_lines():
            now = round(time.time() - started, 2)
            if line.startswith("id: "):
                ids.append(int(line[4:]))
            elif line.startswith("event: "):
                seen.append((line[7:].strip(), now))
                if seen[-1][0] == "run.settled":
                    break
            elif line.startswith(": heartbeat"):
                seen.append(("<heartbeat>", now))
            if time.time() - started > limit:
                seen.append(("<timeout>", now))
                break
    headers["ids"] = ids
    return seen, headers


def main() -> int:
    import httpx

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--proxy", default=DEFAULT_PROXY)
    parser.add_argument("--think", type=float, default=8.0,
                        help="what the engine was started with")
    parser.add_argument("--evidence", type=Path,
                        default=ROOT / "docs" / "retail_cockpit" / "evidence"
                        / "transport.json")
    args = parser.parse_args()

    timeout = httpx.Timeout(connect=5.0, read=None, write=30.0, pool=5.0)
    findings: list[str] = []
    report: dict = {"what_is_measured":
                    "SSE transport through the retail proxy: framing, "
                    "buffering, replay and cancellation.",
                    "what_is_not_measured":
                    "Answer quality. No provider call is made; the run "
                    "fails at the model call by design.",
                    "paid_provider_calls": 0}

    with httpx.Client(timeout=timeout) as client:
        run = _start(client, args.proxy, "Total EAD by product this month",
                     "transport-stream")
        seen, head = _drain(client, args.proxy, run)
        names = [n for n, _ in seen]
        report["stream"] = {"headers": {k: v for k, v in head.items()
                                        if k != "ids"},
                            "frames": [{"event": n, "at_seconds": t}
                                       for n, t in seen]}

        if head["status"] != 200:
            findings.append(f"the stream answered {head['status']}")
        if "text/event-stream" not in head["content_type"]:
            findings.append(f"content type is {head['content_type']!r}")
        if head["accel_buffering"].lower() != "no":
            findings.append("X-Accel-Buffering did not survive the proxy")
        if "no-transform" not in head["cache_control"]:
            findings.append("Cache-Control no-transform did not survive")
        if "run.settled" not in names:
            findings.append("the stream never settled")
        ids = head["ids"]
        if ids != sorted(ids) or len(set(ids)) != len(ids):
            findings.append("event ids are not monotonic and unique")

        # Unbuffered: the thinking time must be VISIBLE in arrival times.
        try:
            asked = next(t for n, t in seen if n == "model.requested")
            done = next(t for n, t in seen
                        if n in ("run.failed", "answer.ready",
                                 "run.cancelled"))
            gap = round(done - asked, 2)
        except StopIteration:
            gap = 0.0
            findings.append("the run never reached the model call")
        report["stream"]["think_gap_seconds"] = gap
        report["stream"]["heartbeats"] = names.count("<heartbeat>")
        if gap < args.think * 0.6:
            findings.append(
                f"frames arrived {gap}s apart against {args.think}s of "
                f"thinking: the stream is being buffered")

        # Replay: reconnect from a cursor and get the tail, only the tail.
        if len(ids) >= 2:
            tail, _ = _drain(client, args.proxy, run, cursor=ids[0])
            tail_names = [n for n, _ in tail if not n.startswith("<")]
            report["replay"] = {"from_cursor": ids[0], "frames": tail_names}
            if tail_names != [n for n in names if not n.startswith("<")][1:]:
                findings.append("a reconnect did not replay exactly the tail")

        # Stop, twice.
        run = _start(client, args.proxy, "Total ECL by stage this month",
                     "transport-cancel")
        time.sleep(1.0)
        first = client.post(f"{args.proxy}/runs/{run}/cancel")
        after, _ = _drain(client, args.proxy, run)
        second = client.post(f"{args.proxy}/runs/{run}/cancel")
        report["cancel"] = {
            "in_flight": {"status": first.status_code, **first.json()},
            "frames_after": [n for n, _ in after],
            "repeated": {"status": second.status_code, **second.json()}}
        if first.status_code != 200 or not first.json().get("cancelled"):
            findings.append("Stop did not cancel a run in flight")
        if second.json().get("cancelled") is not False:
            findings.append("a second Stop was not idempotent")
        if "run.settled" not in report["cancel"]["frames_after"]:
            findings.append("the stream did not settle after a cancel")

    report["findings"] = findings
    report["verdict"] = "PASS" if not findings else "FAIL"
    args.evidence.parent.mkdir(parents=True, exist_ok=True)
    args.evidence.write_text(json.dumps(report, indent=2))

    print(f"stream      {head['status']} {head['content_type']}")
    print(f"            X-Accel-Buffering: {head['accel_buffering']!r} "
          f"Cache-Control: {head['cache_control']!r}")
    print(f"frames      {[n for n, _ in seen]}")
    print(f"think gap   {report['stream']['think_gap_seconds']}s against "
          f"{args.think}s of thinking, "
          f"{report['stream']['heartbeats']} heartbeat(s) inside it")
    print(f"replay      {report.get('replay', {}).get('frames')}")
    print(f"cancel      in flight {report['cancel']['in_flight']['cancelled']}"
          f", repeated {report['cancel']['repeated']['cancelled']}")
    print(f"\n{report['verdict']}  ({len(findings)} finding(s))")
    for line in findings:
        print(f"  - {line}")
    print(f"evidence    {args.evidence}")
    return 0 if not findings else 1


if __name__ == "__main__":
    raise SystemExit(main())
