# How much memory one session needs, measured

## What was changed, and what it does unconfigured

`backend/cockpit_v4/catalog.py::_build_session` fixed two things a deployment
could not state: how much memory one materialised book may hold, and where a
session that outgrows it spills. Both are now configurable, and **the engine
default is exactly what it was**: with nothing set, the statement executed is
`SET memory_limit = '1536MB'`, character for character, and the comment
recording the measurement behind that figure now sits on the default itself.

| Setting | Variable | Default |
|---|---|---|
| Session memory | `COCKPIT_V4_SQL_MEMORY_LIMIT` | `1536MB` — today's value |
| Spill directory | `COCKPIT_V4_SQL_TEMP_DIR` | `<COCKPIT_V4_RUNTIME_DIR>/duckdb-temp` |

Both reach DuckDB as text, so both are proved before they get there: a limit
must match a size DuckDB states, a path may not contain a quote, and the
directory is checked for containment by `config.check_write_target` — the
engine's own guard, not a second opinion. A temp directory outside the runtime
directory is refused rather than obeyed, and a session that cannot create it
fails rather than falling back to the working directory. That fallback was the
defect: with no temp directory set, DuckDB spills beside an in-memory database,
which is the process working directory — the one place this runtime promises
never to write.

## The measurements

One fresh process per limit; five repeats per query. The projection is
`cockpitdata-r1.2.0-c1.0.0-s20260910-p4`, all 94 behavioural model-input
columns retained, 4,163,524 rows across five relations. Machine: Linux, 4 CPUs,
16.0 GB total / 15.5 GB available, Python 3.12.3, DuckDB 1.5.5.

| Limit | Cold open | Materialised | Spill | vs 1536MB | Peak RSS | Simple agg | Diagnostic |
|---|---|---|---|---|---|---|---|
| **1536MB** (today) | 45.0 s | 1,393 MiB | 711 MiB | — | 1,658 MiB | 4.2 ms | 54.7 ms |
| **2048MB** | 11.9 s | 1,881 MiB | 546 MiB | −23% | 2,187 MiB | 4.8 ms | 57.8 ms |
| **2560MB** | 11.3 s | 2,369 MiB | 292 MiB | −59% | 2,796 MiB | 4.2 ms | 54.3 ms |
| **3072MB** | 11.2 s | 2,857 MiB | 62 MiB | −91% | 3,063 MiB | 4.2 ms | 57.7 ms |
| 3584MB *(control)* | 13.0 s | 2,968 MiB | **0** | −100% | 3,290 MiB | 4.2 ms | 55.0 ms |
| 4096MB *(control)* | 10.5 s | 2,972 MiB | **0** | −100% | 3,286 MiB | 4.7 ms | 56.9 ms |

Warm reopen is 0.011 ms at every limit — the session is cached, and nothing here
changes that.

Three things the numbers say that the expectation did not:

1. **The cold-open cliff is between 1536MB and 2048MB, not at the top.** 45.0 s
   to 11.9 s for 512 MB more, and then flat: 11.9, 11.3, 11.2, 13.0, 10.5. At
   1536MB the materialisation is not spilling once, it is thrashing.
2. **Query latency is flat across the whole range.** A simple aggregation is
   ~4.2 ms and the multi-relation diagnostic ~55 ms whether the book spills
   711 MiB or nothing at all. Spilling is costing startup, not answers.
3. **Zero spill needs 3584MB**, because the book materialises 2,968 MiB and
   DuckDB keeps working room above it. Within the approved set, 3072MB removes
   91% of it.

## Two questions at once

The engine serves runs on one worker thread, but the API threads compute the
attention and ECL panels on the *same cached session*, so two statements can
genuinely be in flight on one DuckDB connection — and nothing in the engine uses
a cursor to separate them. Measured at every limit: both questions returned
correct row counts, no exception, wall time equal to the slower of the two
(64–76 ms) with the simple query still finishing in 4.5 ms. The shared
connection serialises rather than failing.

## What the Mac actually has, and what that changes

Measured on the demo machine: **16 GB physical, 3,033 MiB available**, with the
retail API at 105 MiB and the frontend at 18 MiB. Against the peak RSS above:

| Limit | Peak RSS | Against 3,033 MiB available | Verdict |
|---|---|---|---|
| 1536MB | 1,658 MiB | leaves ~1,375 MiB | safe |
| 2048MB | 2,187 MiB | leaves ~846 MiB | acceptable on a quiet machine |
| 2560MB | 2,796 MiB | leaves ~237 MiB | compresses and swaps |
| 3072MB | 3,063 MiB | exceeds available | do not run |
| 3584MB | 3,290 MiB | exceeds available | do not run |

**The 3072MB recommendation is withdrawn for this machine.** It answered "which
limit removes spilling" correctly and "what can this Mac afford" not at all,
and the second is the question that decides.

The cost is not transient. The book is materialised at application startup and
cached, so the figure above is the engine's steady-state resident size, sitting
beside the demo and the browser on a machine with 13 GB already in use.

So the affordable option is the honest one: **1536MB, the engine default, with
no override at all.** Query latency is flat across the entire range whether the
book spills or not; the only cost is the materialisation, paid once by the
launcher before it prints READY, with spill on an SSD inside the candidate
runtime directory.

**Decision rule, against the Mac's own figure in demo-ready state:**

- available ≥ 3,500 MiB → `2048MB` (~12 s start, ~2.2 GB resident)
- available < 3,500 MiB → **no override**; the engine's own 1536MB
- 2560MB and above → only with ≥ 5 GB free, which this machine does not have

`benchmark_session.py` now refuses a limit this machine cannot hold — projected
resident size at 1.15× the limit, plus 512 MiB left for the machine itself —
and records the refusal instead of running it. A benchmark that swaps measures
the swap. `--allow-unsafe` overrides it deliberately.

## A caveat on the 1536MB cold open

The 45.0 s above was the first run against a freshly written lake, with the
file cache cold. A later run of the same limit on the same machine, with the
parquet in the page cache, opened in **18.3 s**. Both are true: the first start
after a reboot is the slow case, and the figure to expect on the Mac is
somewhere in that range rather than a single number. It changes nothing about
the ordering — the higher limits are ~11 s either way — but a 45 s launcher
wait quoted as fact would be one.

## The choice

The rule, written down before the numbers: *the lowest limit whose session-open
spill is zero; failing that, the lowest whose spill falls by at least 90% against
1536MB with aggregation latency within noise of the best; subject to peak RSS
leaving a margin on the machine that runs it.*

On this container the rule chose `3072MB`: the lowest value in the approved set
that materially reduced spilling (−91%), at 3,063 MiB peak RSS.

**On the Mac it chooses differently, and the Mac is the machine that matters.**
At 3,033 MiB available, 3072MB does not fit and 2560MB leaves the machine
nothing. The candidate therefore ships with **no override** — the engine's own
1536MB — until a run on that machine, in demo-ready state, says otherwise. The
safe benchmark there is two limits:

```
.venv/bin/python scripts/retail_cockpit/benchmark_session.py \
    --limits 1536MB,2048MB --repeat 3
```

which the guard will trim further if the machine is busier than it was. Neither
that nor the publisher touches the retail domain: the publisher reads
`data/retail/analytics` and writes only into the candidate Cockpit lake, and
the benchmark only opens sessions.

## Against the ported budgets

The frozen suite carries two cold-open budgets — `session_cold_open` p90 ≤ 6,000 ms
(`tests/cockpit_v4/test_dual_domain_performance.py`) and < 5.0 s
(`tests/cockpit_v4/test_performance_gates.py`). **This book meets neither at any
limit**: the best measured cold open is 10.5 s.

There is, however, no red gate to decide about, and the earlier assumption that
there would be was wrong. Both suites' `_published()` fixture skips unless
**every** domain's release is published, and this deployment publishes one book,
not two. Measured: `24 skipped, 2 errors in 0.21s`. So the budgets are a
standard this book misses in reality, recorded here, rather than a failing test
in the candidate's gate.

What takes the sting out of the 10.5 s: `create_app()` calls `_announce_books()`,
which opens every published book. The materialisation is paid during application
startup, before the server accepts a request — by the launcher's readiness wait,
not by the first reader's first question.

## A gap this run found, for the host integration ahead

The two errors above are not about memory. The ported `backend/cockpit_agentic`
package reads eight `cockpit_agentic_v3_*` settings that the retail
application's `backend/config.py` does not define — they live in the source
application's config and were not ported, because `backend/config.py` belongs to
the target. Nothing on the V4 domain path reads them (it reads `ai_provider` and
`analytics_dir`, both present), which is why the adapter, the projection, the
sessions and the benchmark all work. But `service.load_release`, which
`create_app` calls at startup for the pre-domain release, does reach V3's store.

That is a target-configuration change, not an engine one, and it belongs with
the host integration rather than with this seam. It is recorded here so it is
not discovered at launch.
