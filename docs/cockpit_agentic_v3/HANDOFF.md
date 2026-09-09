# Cockpit Agentic V3 — handoff

## Branch and base

| | |
|---|---|
| Branch | `claude/cockpit-agentic-v3-fhg4r0` |
| Base | `83b39a602eb430444f46d08aca4e595522f3b53f` — the preserved HEAD of `claude/cockpit-intelligence-v2-mbb22o` |
| Relationship | A clean fast-forward child. `main` is an ancestor of the base, so nothing from `main` was lost. |
| Cockpit V2 branch | **Untouched.** Still the fallback and the before/after UAT baseline. |
| Merged to main | **No.** |

## What is here

| | |
|---|---:|
| New backend package | `backend/cockpit_agentic/` — 19 modules |
| Versioned prompt contracts | 6, in `backend/cockpit_agentic/prompts/` |
| Declared fields | 751 definitions; 991 addressable `relation.column` pairs; zero unexpanded placeholders. See `docs/cockpit_v3/COCKPIT_FIELD_AUDIT.md` for which count is which |
| Reporting quarters | 20, plus a separate macro axis of offsets −4…+15 |
| Demo release | 250 borrowers, 600 facilities, ~13 MB Parquet, 72 integrity gates |
| Tests | 259 in `tests/cockpit_agentic/`, all passing |
| Labelled ownership cases | 25 |
| Regressions against the base | **0** |

## The architecture, and where each rule lives

| Rule | Where it is true |
|---|---|
| Cockpit reads only the 20-quarter domain | `scope.py`; the DuckDB session materializes only the allowlisted relations, then disables file and network access and locks the configuration |
| Two Sonnet passes, then the Opus gate | `sonnet.py`, `opus.gate_and_plan`; `states.TRANSITIONS` gives `BUILDING_CONTEXT` exactly one working edge |
| A referral executes nothing | `FUNCTIONALITY_ASSESSMENT` has no edge to `VALIDATING` or `EXECUTING` |
| Opus owns every query and every repair | `failure.py` and `runtime.py` contain no SQL fragment at all — asserted by reading the source |
| Five submissions, three rounds, never reset | `ledger.py`; no override exists for either at any level |
| Full context on every repair | `opus.Conversation` threads one conversation; a captured trace proves the content |
| No fallback | `test_no_fallback.py` parses the package and asserts it cannot import the legacy paths |

## Model configuration

Two roles, named for the job rather than a model family, because a role named
after a model reads as though it were pinned to one:

```
AI_COCKPIT_PREPROCESS_MODEL=   # cleanup, normalization, summary
AI_COCKPIT_REASONING_MODEL=    # ownership, planning, authorship, repair, review
```

**No model id is hard-coded anywhere.** Blank inherits the router and complex
planner ids, then `AI_MODEL`, then the provider's own pinned default. Verify
ids against the provider's current documentation before setting them.

## The configuration this domain requires, and why

The complete field dictionary is **22,078 tokens**; the whole context packet is
**~28,000** after every permitted reduction. The specification's own per-call
input cap is 12,000 (Standard) and its cumulative ceiling 35,000 — so its
numbers cannot hold its own catalogue.

§7.4 names this case and says to fix the serialization or the configuration.
Both were done, neither quietly:

- Serialization: 29,600 → 22,078 tokens with **no field lost**, verified by a
  test that reconstructs the field set from the compact form.
- Configuration: the owner set the UAT budgets — Standard 64,000 per call and
  250,000 cumulative, Deep 96,000 and 500,000 — and those are now the shipped
  defaults. **No override is needed to run this domain**, and the test suite
  runs on the defaults so they are proved sufficient rather than assumed.

The settings remain administrator-configurable, raise only, and are reported
through `overrides_in_force` and on the screen badge:

```
COCKPIT_AGENTIC_V3_STANDARD_INPUT_TOKENS=64000   # the default
COCKPIT_AGENTIC_V3_DEEP_INPUT_TOKENS=96000       # the default
COCKPIT_AGENTIC_V3_STANDARD_TOTAL_TOKENS=250000  # the default
COCKPIT_AGENTIC_V3_DEEP_TOTAL_TOKENS=500000      # the default
```

At these volumes the SPEND ceiling binds before the token ceiling — $1.00
reaches at about the sixth full-context call while roughly 170,000 of the
250,000 tokens are still unspent. That is measured and left in place, per the
instruction to keep the cost ceilings and report evidence rather than raise
them pre-emptively. **The five submissions, three analysis rounds and the 60
and 120-second deadlines cannot be raised at any level.** See
`CONTEXT_SIZING.md`.

## Commands

```sh
# Build the release (refuses to publish a release failing any gate)
COCKPIT_AGENTIC_V3=true .venv/bin/python scripts/build_cockpit_agentic_v3.py --overwrite

# Regenerate the reference documents from the code
COCKPIT_AGENTIC_V3=true .venv/bin/python scripts/build_cockpit_agentic_v3_docs.py

# Tests
.venv/bin/python -m pytest tests/cockpit_agentic -q

# The ownership benchmark (exits BLOCKED without a credential)
COCKPIT_AGENTIC_V3=true .venv/bin/python tests/evals/cockpit_agentic/run_ownership_eval.py

# Browser UAT against a running stack
COCKPIT_AGENTIC_V3=true .venv/bin/python tests/cockpit_agentic/browser_uat.py
```

Rollback: the switch defaults off, and with it off nothing in this package
executes. `git checkout claude/cockpit-intelligence-v2-mbb22o` returns to V2
entirely.

## What is verified, and what is not

**Verified.** The domain boundary against a real DuckDB engine, including a
test that bypasses the validator entirely. The 20-quarter calendar and the
second macro axis. 72 data integrity gates. Every guardrail in the ledger. The
gate ordering and that a referral executes nothing. That the repair request
carries the full effective context, read off the actual serialized request.
That CreditProbe never authors SQL, read off the source. That no fallback path
can even be imported. Zero regressions against the base in a matching
configuration. A real browser showing the badge, the disclosed raised limits,
the progress states and the honest stop.

**NOT verified — BLOCKED.** Everything that depends on a model. No credential
is configured in this environment, so routing accuracy, translation fidelity,
plan quality, repair quality, answer quality, latency, token and cost
measurement are all **UNVERIFIED**. The mocks are labelled as mocks in every
file that uses them, the eval runner refuses to produce an accuracy figure
without a credential, and no deterministic output anywhere in this branch
stands in for a model-authored analysis.

**Not implemented, and reported rather than hidden.** Real source data:
every field is `demo_only`. Durable thread state: in-memory, with
`backend/services/threads.py` as the intended seam. The spending ceiling: inert
until prices are configured, and the ledger says so rather than implying a
control it does not have.

Isolated Python execution is now **implemented and verified on this host** —
separate process, fresh mount/network/PID/IPC/UTS namespaces, a chroot jail
holding only the standard library and an approved dependency surface, no
shell, no `/etc`, no repository, no credential, bounded and unprivileged. It
is offered only where a probe that actually tries to escape comes back clean,
and reported unavailable where it does not. `docs/cockpit_v3/PYTHON_EXECUTION_BOUNDARY.md`
records the measured evidence and the separate-service mechanism a locked-down
production container would need.

## The unfinished work, in priority order

1. Configure a credential and run `scripts/cockpit_v3_live_validation.py`,
   the ownership benchmark and the browser UAT live, then work
   `docs/cockpit_v3/QUESTION_BANK.md` side by side against the preserved V2
   branch. Until then the architecture is demonstrated and its outputs are
   not.
2. Compare the provider's reported usage against the measured packet and
   revisit the spend ceiling with evidence — it is what binds first at these
   volumes.
3. Bind the thread layer to `backend/services/threads.py`.
4. Run the Python sandbox as a separate service for a deployment that cannot
   grant the API process namespace privileges.
5. Ingest real data and update `COCKPIT_DATA_DOMAIN_MAPPING.md`, which
   currently states honestly that nothing is real.
