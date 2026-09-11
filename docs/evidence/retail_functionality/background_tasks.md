# Background task disposition — Revision 2 §1

Recorded: 2026-09-11T04:38:12Z
Tree: 0cbb7db98e2925315304b5b88c76d45baf5875e3 on claude/funny-dirac-6n8f0o

## Finding

All nine background tasks are session-owned polling waiters left over from the
gate runs of 2026-09-10. Every one runs:

    until ! pgrep -f "pytest tests/retail" >/dev/null; do sleep N; done

The waiter can never terminate, because the bash wrapper that runs the loop
carries the string "pytest tests/retail" in its own command line, so pgrep -f
matches the waiter itself. The pytest run each was waiting for finished long
ago: docs/evidence/gates.log records 360 passed, PYTEST_EXIT=0.

None owns a test process. None is a service. All are obsolete.

## Waiters stopped (by verified PID, command line re-read immediately before)

| PID | Started | Poll interval | Waiting for |
|---|---|---|---|
| 8875 | Thu Sep 10 20:46:52 2026 | sleep 120 | the completed gate run |
| 8380 | Thu Sep 10 20:34:39 2026 | sleep 45 | the completed gate run |
| 8417 | Thu Sep 10 20:35:03 2026 | sleep 60 | the completed gate run |
| 8442 | Thu Sep 10 20:35:39 2026 | sleep 90 | the completed gate run |
| 9195 | Thu Sep 10 20:57:00 2026 | sleep 15 | the completed gate run |
| 7982 | Thu Sep 10 20:21:29 2026 | sleep 20 | the completed gate run |
| 5579 | Thu Sep 10 20:09:45 2026 | sleep 30 | the completed gate run |
| 8341 | Thu Sep 10 20:34:19 2026 | sleep 25 | the completed gate run |
| 8483 | Thu Sep 10 20:36:04 2026 | sleep 90 | the completed gate run |

## Retained (deliberately, not test jobs)

| PID | Process | Role |
|---|---|---|
| 3781 | postgres -D /var/lib/postgresql/retaildata -p 55432 | the RETAIL database, isolated from any source demo |
| 7591 | uvicorn backend.api.main:app --port 8328 | the retail backend |
| 5632 | npm run dev (next-server) on 5328 | the retail frontend |

These are the application servers the browser journeys drive. They are not
test jobs and were not stopped.

## Result

Nine obsolete waiters stopped by verified PID, each command line re-read
immediately before the signal and matched against the known-obsolete pattern.
No pkill, no killall, no kill-by-port. Zero test jobs remain. No final
acceptance claim in this pass depends on a still-running task.
