# Cockpit V4 — open defect log

Defects found on this branch that are **not yet fixed**. Each entry records
what was observed, what was proved, what was *not* proved, and what a fix
has to include. A defect leaves this file only when it has a fix and a
regression test that fails without it.

---

## D-001 · `seed_release.py` rebuilds an existing release instead of refusing

| | |
|---|---|
| **Status** | OPEN — not fixed |
| **Severity** | P2 |
| **Found** | 2026-09-12, incidentally, while running `pytest tests/cockpit_v4/` |
| **Failing test** | `tests/cockpit_v4/test_launcher_safety.py::test_seeding_an_existing_release_does_not_overwrite_it` |
| **Requirement violated** | `MASTER_BUILD_SPEC.md` §669 — *"Launcher cannot stop any unrelated process or overwrite a release."* Acceptance id **V4-AT-006** ("Immutability, checked rather than assumed") |

### What happens

Running the V4 test suite invokes `scripts/cockpit_v4/seed_release.py` for the
already-published release `v4-uat-20q-v1`. Instead of printing *"already
exists … immutable"* and stopping, the script **rebuilds the release**:

```
Building v4-uat-20q-v1: 120 borrowers, 280 facilities, ending 2026Q2
  published to /home/user/IPM_V2/data/cockpit_v...
  relations: 11
  quarters:  20 (2021Q3..2026Q2)
  evidence written to /home/user/IPM_V2/docs/cockpit_v4/evidence
```

The test asserts `"already exists" in out.stdout` and fails on that line.

### Why it matters beyond the red test

The rebuild has a side effect outside the test sandbox: it **rewrites four
tracked files in the repository**.

```
 M docs/cockpit_v4/evidence/coverage_summary.json
 M docs/cockpit_v4/evidence/performance.json
 M docs/cockpit_v4/evidence/release_manifest.json
 M docs/cockpit_v4/evidence/release_summary.json
```

The row counts change materially, so this is not timestamp churn:

| relation | committed | after an accidental rebuild |
|---|---:|---:|
| `cockpit_facility_quarter` | 1,655 | 3,163 |
| `cockpit_ifrs9_detail` | 5,415 | 10,440 |
| `cockpit_borrower_financial_quarter` | 1,010 | 1,936 |
| `cockpit_qualitative_quarter` | 20,200 | 38,720 |
| `cockpit_collateral_allocation` | 4,440 | 9,180 |

So **running the test suite silently changes the committed evidence for the
release that every oracle and benchmark is measured against.** Any number
quoted from those files after a suite run is a number from a different
dataset than the one on the branch. That is the real cost of this defect —
the red test is only how it announces itself.

### What was established

Resolving the guard's own path, read-only, outside pytest:

```python
COCKPIT_AGENTIC_V3=true COCKPIT_AGENTIC_V3_NAMESPACE=cockpit_v4
store.release_dir('v4-uat-20q-v1')
#  -> /home/user/IPM_V2/data/cockpit_v4/v4-uat-20q-v1
#  exists -> True
```

The guard at `seed_release.py:52` is `if target.exists() and not args.overwrite`.
With that resolution it **would** fire. `COCKPIT_V4_TEST_RELEASE` is unset in
this environment, so the test passes the same default id, `v4-uat-20q-v1`.

So the guard's logic and its default path resolution are **not** obviously
wrong, and a fix that only rewrites the condition is likely to be the wrong
fix.

### What was NOT established

**Why the guard does not fire inside the test's subprocess.** This has not
been root-caused and must be before anything is changed. Two candidates, both
unverified:

1. **Environment divergence.** The test launches with
   `env={**os.environ, "COCKPIT_AGENTIC_V3_NAMESPACE": "cockpit_v4"}`, where
   `os.environ` is pytest's, possibly already mutated by a fixture. `root()`
   is `Path(settings.analytics_dir).parent / namespace()`, so anything that
   moves `analytics_dir` moves the guard's target — and a target that does
   not exist is a target the guard waves through.
2. **Settings caching order.** `seed_release.py` sets the namespace env vars
   at lines 41–43 and imports `backend.cockpit_agentic` at line 45, relying on
   `backend.config` reading them at import time. If `backend.config.settings`
   is already materialised in that interpreter, the namespace applied to
   `root()` is the stale one.

Note these pull in opposite directions: (1) says the guard looked in the wrong
place, (2) says the same. The printed output says the rebuild published to a
path under the real `/home/user/IPM_V2/data/cockpit_v...`, which is *not*
obviously consistent with either. That contradiction is exactly why this is
recorded as not-root-caused rather than half-diagnosed.

### What a fix must include

1. A root cause, established by reproducing the guard's path resolution
   **inside the failing subprocess** — not inferred from reading the code.
2. The immutability guard holding regardless of how `analytics_dir`,
   the namespace env, or settings caching are arranged. A published release
   must be refused from any caller.
3. A regression test that **fails without the fix**, asserting both halves:
   the refusal (`returncode == 0`, `"already exists"`, `"immutable"`) **and**
   that `docs/cockpit_v4/evidence/*.json` are byte-identical before and
   after — because the file mutation is the part that actually costs
   something, and the current test does not check it.
4. Consideration of whether the evidence files should be written by a seed
   script at all, or only by an explicit `--overwrite` / publish step.

### Provenance

Found during an accidental run of the V4 suite; the four modified files were
restored with a working-tree `git checkout --`, not a branch reset, and the
rebuild was never committed. The defect itself pre-dates that run and is
present at `b4ac6aa`.
