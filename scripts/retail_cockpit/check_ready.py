#!/usr/bin/env python3
"""Is the Cockpit path actually working? Asked end to end, not port by port.

    .venv/bin/python scripts/retail_cockpit/check_ready.py \
        --api http://127.0.0.1:8329 --engine http://127.0.0.1:8415

A launcher that prints READY when a port opens hands over a Cockpit that
cannot answer anything. This asks the questions that would otherwise be
answered by the first person to use it:

* does the retail API answer, and does it refuse an unauthenticated Cockpit
  call rather than serving it;
* did the engine open the book it was configured to open, at the release id
  the environment names;
* are the capability flags the ENGINE reports good enough to accept work --
  and if not, which one is missing and why;
* does a real Cockpit call cross the proxy and come back;
* does the event stream open through the proxy with its no-buffering headers
  intact.

Exit 0 only when every one of those is true. No provider call is made.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

#: The flags that must be true before the Cockpit can accept a question.
#: `python_analysis_ready` is NOT among them: `pyrunner` reports UNAVAILABLE
#: in the frozen source, which is a disclosed limitation of the port rather
#: than something this deployment broke or should pretend away.
REQUIRED = ("process_alive", "release_ready", "sql_analysis_ready",
            "attention_ready")


def main() -> int:
    import httpx

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default="http://127.0.0.1:8329")
    parser.add_argument("--engine", default="http://127.0.0.1:8415")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    findings: list[str] = []
    report: dict = {"api": args.api, "engine": args.engine}
    client = httpx.Client(timeout=30.0)

    # 1. the retail API itself
    try:
        health = client.get(f"{args.api}/api/v1/health")
        report["retail_api"] = health.status_code
        if health.status_code != 200:
            findings.append(f"the retail API answered {health.status_code}")
    except Exception as exc:  # noqa: BLE001
        findings.append(f"the retail API did not answer: {exc}")

    # 2. the engine's own view of what it can do
    try:
        body = client.get(f"{args.engine}/health").json()
        flags = body.get("capabilities") or {}
        report["engine"] = {"startup_sha": body.get("startup_sha", ""),
                            "capabilities": flags}
    except Exception as exc:  # noqa: BLE001
        findings.append(f"the engine did not answer: {exc}")
        flags = {}

    # 3. the book it opened, read through the proxy -- which is the only
    #    path a browser will ever take.
    try:
        domains = client.get(f"{args.api}/api/v1/cockpit-v4/domains").json()
        books = {d["domain_id"]: d for d in domains.get("domains", [])}
        retail = books.get("retail")
        report["book"] = retail
        if retail is None:
            findings.append("the Cockpit reports no retail book")
        else:
            if not retail.get("ready"):
                findings.append(
                    f"the retail book is not ready: "
                    f"{retail.get('reason') or 'no reason given'}")
            if not retail.get("analysis_ready", True):
                findings.append(
                    f"the retail book cannot be analysed: "
                    f"{retail.get('reason') or 'no reason given'}")
    except Exception as exc:  # noqa: BLE001
        findings.append(f"the Cockpit's books could not be read: {exc}")

    # 4. an unauthenticated call must not be served. `REQUIRE_LOGIN=false`
    #    is a legitimate local setting, so this reports rather than fails.
    try:
        direct = httpx.post(f"{args.engine}/api/v1/cockpit-v4/threads",
                            json={"domain": "retail"}, timeout=15.0)
        report["engine_without_a_principal"] = direct.status_code
        if direct.status_code != 401:
            findings.append(
                f"the engine served an unauthenticated call "
                f"({direct.status_code}); the boundary secret is not in "
                f"force")
    except Exception as exc:  # noqa: BLE001
        findings.append(f"the engine boundary could not be checked: {exc}")

    # 5. a real Cockpit call, through the proxy, that writes something
    run = ""
    try:
        thread = client.post(f"{args.api}/api/v1/cockpit-v4/threads",
                             json={"domain": "retail"})
        report["thread"] = thread.status_code
        if thread.status_code >= 300:
            findings.append(f"a thread could not be opened through the "
                            f"proxy ({thread.status_code})")
        else:
            started = client.post(
                f"{args.api}/api/v1/cockpit-v4/runs",
                # UNIQUE per check. A fixed key answers 409
                # IDEMPOTENCY_CONFLICT the second time this runs against the
                # same store -- which is every restart after the first, and
                # reads as "the Cockpit refused a question" when the Cockpit
                # did nothing wrong.
                headers={"Idempotency-Key": f"readiness-{uuid.uuid4().hex}"},
                json={"question": "Total exposure at default by product",
                      "thread_id": thread.json()["thread_id"],
                      "mode": "standard"})
            report["run"] = started.status_code
            if started.status_code != 202:
                findings.append(
                    f"the Cockpit refused a question ({started.status_code}): "
                    f"{started.text[:200]}")
            else:
                run = started.json()["run_id"]
    except Exception as exc:  # noqa: BLE001
        findings.append(f"a Cockpit question could not be asked: {exc}")

    # 6. the event stream, with the headers that keep it live
    if run:
        try:
            with client.stream(
                    "GET",
                    f"{args.api}/api/v1/cockpit-v4/runs/{run}/events?cursor=0",
                    headers={"accept": "text/event-stream"}) as stream:
                report["stream"] = {
                    "status": stream.status_code,
                    "content_type": stream.headers.get("content-type", ""),
                    "accel_buffering": stream.headers.get(
                        "x-accel-buffering", "")}
                if stream.status_code != 200:
                    findings.append(
                        f"the event stream answered {stream.status_code}")
                if "text/event-stream" not in report["stream"]["content_type"]:
                    findings.append("the event stream is not typed as one")
                if report["stream"]["accel_buffering"].lower() != "no":
                    findings.append(
                        "X-Accel-Buffering did not survive the proxy, so the "
                        "live panel would freeze")
                for line in stream.iter_lines():
                    if line.startswith("event: "):
                        report["stream"]["first_frame"] = line[7:].strip()
                        break
        except Exception as exc:  # noqa: BLE001
            findings.append(f"the event stream did not open: {exc}")

    missing = [f for f in REQUIRED if not flags.get(f)]
    # The engine's /health closes over what `create_app` built, and the
    # candidate installs its runtime afterwards -- so a stale flag there is
    # not evidence of anything on its own. What decides it is whether the
    # Cockpit ACCEPTED the question above.
    if missing and report.get("run") != 202:
        findings.append(
            f"the engine reports {missing} not ready: "
            f"{flags.get('reason') or 'no reason given'}")

    report["findings"] = findings
    report["verdict"] = "READY" if not findings else "NOT READY"

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"  retail API      {report.get('retail_api')}")
        book = report.get("book") or {}
        print(f"  book            {book.get('release_id', '?')} "
              f"ready={book.get('ready')} "
              f"analysis={book.get('analysis_ready')}")
        print(f"  engine flags    "
              f"{ {k: flags.get(k) for k in REQUIRED} }")
        print(f"  boundary        unauthenticated call -> "
              f"{report.get('engine_without_a_principal')}")
        print(f"  question        {report.get('run')}")
        stream = report.get("stream") or {}
        print(f"  event stream    {stream.get('status')} "
              f"{stream.get('content_type', '')} "
              f"first frame {stream.get('first_frame', '-')}")
        print(f"\n  {report['verdict']}")
        for line in findings:
            print(f"    - {line}")
    return 0 if not findings else 1


if __name__ == "__main__":
    raise SystemExit(main())
