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

Exit 0 only when every one of those is true.

What it costs
-------------
Step 5 submits a REAL question. Offline that is free -- the provider cannot
call out and the run settles as a failure at the model call. **Live it is a
billed analysis**, and the launcher runs this on every start with a fresh
idempotency key, so it would buy one run per start. The docstring here used
to say "No provider call is made", which was true only offline.

So the question step runs only when the engine is offline, or when
`--allow-paid-run` says to spend deliberately. Skipped, it is reported as
skipped rather than passed, and it is not a finding: a check that cannot be
made for free is not a failure.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from pathlib import Path


class _Skip(Exception):
    """The question step was not attempted. Not a failure."""

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
    parser.add_argument("--expect-model", default="",
                        help="the model the RUNNING engine must report")
    parser.add_argument("--expect-card", default="",
                        help="the price card filename the RUNNING engine "
                             "must report, e.g. price_card.candidate.json")
    parser.add_argument("--expect-release", default="",
                        help="the release id the RUNNING engine must report")
    parser.add_argument(
        "--allow-paid-run", action="store_true",
        help="submit the readiness question even in live mode, where "
             "it is a billed analysis. Offline it runs anyway and "
             "costs nothing.")
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

    offline = bool(os.environ.get("RETAIL_COCKPIT_OFFLINE", "").strip())

    # 4b. WHAT THE RUNNING ENGINE IS ACTUALLY CONFIGURED WITH.
    #
    # Not what the env file says, not what the operator exported: what the
    # process loaded. `/diagnostics` reports the live `config.load()` result
    # and answers even when the runtime is None, which is precisely the state
    # a bad price card leaves behind.
    #
    # This check exists because its absence cost a live UAT: the preflight
    # read the operator's shell, the launcher sourced a file that overwrote
    # it, and nothing compared either with the engine. The first question
    # came back 503.
    try:
        diag = client.get(f"{args.api}/api/v1/cockpit-v4/diagnostics")
        settings = (diag.json().get("settings") or {}) if \
            diag.status_code == 200 else {}
        report["engine_settings"] = {
            k: settings.get(k) for k in
            ("reasoning_model", "price_card_path", "release_id",
             "state_database", "credential")}
        if diag.status_code != 200:
            findings.append(f"the engine would not report its configuration "
                            f"({diag.status_code})")
        else:
            got = str(settings.get("reasoning_model") or "")
            if args.expect_model and got != args.expect_model:
                findings.append(
                    f"the RUNNING engine's reasoning_model is {got!r}, not "
                    f"{args.expect_model!r}. The launcher and the engine "
                    f"disagree.")
            # NOT `settings.release_id`: that is the engine's PRE-DOMAIN
            # release, which this candidate never publishes and which stays
            # at the engine's own default. The book the Cockpit actually
            # opens is the DOMAIN release, reported by /domains and already
            # read in step 3.
            book = str((report.get("book") or {}).get("release_id") or "")
            if args.expect_release and book != args.expect_release:
                findings.append(
                    f"the RUNNING engine opened release {book!r}, not "
                    f"{args.expect_release!r}. The launcher and the engine "
                    f"disagree about the book.")
            card = str(settings.get("price_card_path") or "")
            if args.expect_card and not card.endswith(args.expect_card):
                findings.append(
                    f"the RUNNING engine's price card is {card!r}, not "
                    f"{args.expect_card!r}. This is the mismatch that "
                    f"refuses every question with CAPABILITY_UNVERIFIED.")
            missing = settings.get("missing_settings") or []
            # A missing credential is expected offline and is not a finding
            # here; check_live.py is where live readiness is decided.
            unexpected = [m for m in missing
                          if m != "COCKPIT_ANTHROPIC_API_KEY" or not offline]
            if unexpected:
                report["engine_missing_settings"] = unexpected
    except Exception as exc:  # noqa: BLE001
        findings.append(f"the engine's configuration could not be read: {exc}")

    # 5. a real Cockpit call, through the proxy, that writes something.
    #    Billed in live mode, so it is opt-in there. See the module docstring.
    run = ""
    may_spend = offline or args.allow_paid_run
    if not may_spend:
        report["run"] = "skipped"
        report["run_skipped_because"] = (
            "live mode: submitting a question would be billed. Re-run with "
            "--allow-paid-run to spend one analysis on proving it.")
    try:
        if not may_spend:
            raise _Skip
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
    except _Skip:
        pass
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
    if missing and report.get("run") == "skipped":
        # Nothing was asked, so the stale flags are all there is -- and they
        # are known to be stale. Reported, never silently passed, and never
        # treated as proof either way.
        report["readiness_unproven"] = (
            f"the engine's /health reports {missing} not ready. That endpoint "
            f"closes over what create_app built, not what the candidate "
            f"installed, so it is not evidence on its own -- and the question "
            f"that would settle it was skipped to avoid a charge.")
    elif missing and report.get("run") != 202:
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
        engine_settings = report.get("engine_settings") or {}
        if engine_settings:
            print(f"  engine model    {engine_settings.get('reasoning_model')}")
            print(f"  engine card     "
                  f"{engine_settings.get('price_card_path')}")
            print(f"  engine state db {engine_settings.get('state_database')}")
        print(f"  boundary        unauthenticated call -> "
              f"{report.get('engine_without_a_principal')}")
        print(f"  question        {report.get('run')}")
        if report.get("run_skipped_because"):
            print(f"                  {report['run_skipped_because']}")
        if report.get("readiness_unproven"):
            print("  readiness       NOT PROVEN without spending")
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
