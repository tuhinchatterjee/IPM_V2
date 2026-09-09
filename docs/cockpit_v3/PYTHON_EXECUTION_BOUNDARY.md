# The Python execution boundary

Some analysis is not a SELECT. A survival curve, a decomposition across several
result sets, a regression against the macro window — these are computations
over rows already fetched, and the architecture allows Opus to author Python
for them. This document is what makes running that code acceptable, and what
would have to be true elsewhere.

Nothing here changes who owns the analysis. CreditProbe validates, executes,
diagnoses and enforces the guardrails. It does not write Python, read Python
for intent, or repair Python. When a step fails, the interpreter's own
traceback goes back to Opus unedited and the next candidate is Opus's.

## Status on this host

| | |
|---|---|
| Isolated Python execution | **AVAILABLE** |
| Launch strategy in force | `privileged_namespaces` |
| Established by | running a job in a real jail whose code tries to escape |
| Probe cost | 0.41s, once per process |



## What was verified, and what verified it

`probe()` does not look for `/usr/bin/unshare` and conclude that isolation
works. It runs a real step whose code opens a socket to a routable address,
opens `/etc/passwd`, writes to `/usr`, looks for this repository, appends to
its own input, reads its environment for anything credential-shaped, tries
`/bin/sh`, imports the provider SDK and the database drivers, and reports its
uid. Python is offered only when every one of those attempts failed in the
expected way.

| Guarantee | The evidence, from this host |
|---|---|
| `network_denied` | connect() raised OSError |
| `host_filesystem_hidden` | /etc/passwd raised FileNotFoundError; root holds ['dev', 'lib', 'lib64', 'proc', 'site', 'tmp', 'usr', 'work'] |
| `host_files_read_only` | writing the bound /usr/lib raised OSError |
| `jail_skeleton_read_only` | /usr raised PermissionError; /site raised PermissionError |
| `repository_hidden` | /home/user/IPM_V2 not present |
| `inputs_read_only` | appending to the input raised PermissionError |
| `environment_scrubbed` | no credential-shaped variables |
| `no_shell` | /bin/sh raised FileNotFoundError; no binary directory exists |
| `dependency_surface` | approved: ['2.5.0', '3.0.3']; unapproved importable: none |
| `privileges_dropped` | uid 65534 |
| `separate_process` | a child process, never the API process |

A finding that is ABSENT is not a finding that passed. `REQUIRED_FINDINGS`
lists every check the probe must report on, and a report missing any of them
fails the whole probe — an evaluator that read a missing key as `None` and
moved on would certify a boundary it never tested. That defect existed for one
commit, was caught by the evidence reading `raised None`, and is now two tests.

## How the boundary is built

The code never runs in the API process. `pysandbox.py` launches
`_pyjail_boot.py` through `unshare`, and everything below happens before a
single line of model-authored Python executes.

1. **Fresh namespaces** — mount, network, PID, IPC and UTS. The network
   namespace has no interface but loopback, so `connect()` returns
   `ENETUNREACH` rather than being filtered by a rule somebody could edit.
2. **A tmpfs jail, built from nothing.** The mount tree is made private first,
   so nothing done inside reaches the host. Then: `/usr/lib` and `/usr/lib64`
   bound read-only for the standard library and the shared objects; the
   approved packages bound read-only one at a time; `/proc`; a 1 MiB `/dev`
   holding exactly `null`, `zero`, `random` and `urandom`; a tmpfs `/tmp`; and
   the workspace.
3. **No binary directories.** `/usr/bin` and `/usr/sbin` are not mounted. The
   interpreter was exec'd before the chroot and is already mapped, so nothing
   needs them — and leaving them out is what makes "no shell" true rather than
   aspirational. `ls` and `sh` are not blocked by policy; they are not there.
4. **`chroot`**, then `chdir` into the output directory. There is no `/etc`, no
   repository, no environment file, no `.env`, no home directory.
5. **Resource limits** — address space, CPU seconds, file size, process count,
   and no core dumps.
6. **Privileges dropped** — `setgroups([])`, `setgid`, `setuid` to `nobody`.
7. **Only then** is the model's code compiled and executed.

If any step of that fails, the bootstrap exits without running the code. There
is no degraded mode: the alternative to isolation is not running.

## The input snapshot

A Python step reads `inputs` — a dict keyed by the `step_id` of each step
already executed **in the same submission**, each carrying the same shape a SQL
step returns. There is no database handle inside the jail, so a Python step
cannot read anything a SQL step did not fetch first: the scope boundary is not
re-argued inside the sandbox, because there is nothing there to argue with.

The snapshot is read-only twice over — bound read-only into the jail, and owned
by a user the code is not. `truncated` travels with it, so a clipped table
cannot be silently summed.

## The approved dependency surface

`numpy, numpy.libs, pandas, pandas.libs, dateutil, six, pytz, tzdata` and the standard library. Everything else
in the site directory — the provider SDK, `duckdb`, `sqlalchemy`, `httpx`,
`cryptography` — is never mounted, so there is no allowlist to get around and
no import hook to defeat. The tests assert `ModuleNotFoundError` for each.

## The bounds

| | Standard | Deep |
|---|---:|---:|
| Wall clock per step | 15s | 30s |
| CPU seconds | ≤ wall | ≤ wall |
| Address space | 512 MiB | 1024 MiB |
| Result rows returned | 200 | 200 |
| Processes | 64 | 64 |
| File size written | 16 MiB | 16 MiB |

They come from the ledger. Neither the model nor the browser can raise them,
and the wall clock is additionally clamped to the time the request has left.

Exhausting one is reported as a limit, not as a bug — `RESOURCE_LIMIT`, not
`RUNTIME_ERROR` — because "your code was too expensive" and "your code was
wrong" are different things to decide about. CPU exhaustion is caught at the
soft limit so the reason survives; without that the process is simply killed
and all that is left is an exit status.

## Cancellation and cleanup

The launcher is PID 1 of its own PID namespace, so killing it takes everything
inside with it. The runtime passes the ledger's cancellation flag in, checked
four times a second. The workspace and the jail directory are removed in a
`finally`, and the jail's tmpfs disappears with the namespace whatever happened.

## The audit record

One record per step, in `Outcome.python_execution`: request and step id, a
16-character digest of the code, its length, the input keys, the strategy, the
exit code, elapsed time, the limits that were in force and the guarantees that
were verified. **Not the code, and not the data** — a fingerprint identifies a
step across a repair cycle without copying borrower rows into a log.

## Where this does not hold

The strategy in force here is `privileged_namespaces`, which needs real
`CAP_SYS_ADMIN`. A deployment that runs the API as an unprivileged user in a
container without that capability will fail the probe, and Python will be
reported unavailable rather than downgraded. Two things to know about that:

* **`user_namespace` is implemented and does pass here, with one caveat.**
  It is tried second and was probed directly: the network is unreachable, the
  host's `/usr/lib` bind is read-only, `/etc` and the repository are absent,
  there is no shell, the input snapshot is read-only, and only the approved
  packages import. What it does not give is the innermost layer — the code runs
  as uid 0 of its own namespace, so the jail's throwaway tmpfs skeleton
  (`/usr`, `/site`) is writable to it, where under `privileged_namespaces` the
  code is `nobody` and it is not. Nothing written there outlives the step or
  reaches the host, and a module planted in `/site` could only be imported by
  the same step that planted it. The probe records this as a caveat on the
  strategy rather than as a failure, and the caveat travels in the diagnostics.
  It has not been exercised as an actually-unprivileged process on this host,
  because this container runs as root; that is why it is described as the right
  shape for an unprivileged deployment rather than as proven under one.
* **The production mechanism.** The durable answer is not to grant the API
  process `CAP_SYS_ADMIN`. It is to run the sandbox as a separate service —
  gVisor, Firecracker, a Kubernetes pod with a restricted seccomp profile and
  no service-account token, or an existing code-execution service — with the
  same contract this module already has: a code string and an input snapshot
  in, a result and a diagnostic out, under the same limits. `pysandbox.execute`
  is the seam; a deployment replaces what is behind it without any other module
  changing.

Until such a deployment exists and its own probe passes, the honest report is
the one this module makes: available here, and measured, not assumed.
