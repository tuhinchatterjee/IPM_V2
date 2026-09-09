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
- Configuration: settings that default to the specification's values, raise
  only, and are reported through `overrides_in_force` and on the screen badge.

```
COCKPIT_AGENTIC_V3_STANDARD_INPUT_TOKENS=36000
COCKPIT_AGENTIC_V3_DEEP_INPUT_TOKENS=40000
COCKPIT_AGENTIC_V3_STANDARD_TOTAL_TOKENS=100000
COCKPIT_AGENTIC_V3_DEEP_TOTAL_TOKENS=200000
```

Without them the Cockpit returns `CONTEXT_TOO_LARGE` with the measured figure —
correct behaviour, not a bug. **The five submissions and three rounds cannot be
raised at any level.** See `CONTEXT_SIZING.md`.

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

**Not implemented, and reported rather than hidden.** Isolated Python
execution: `diagnostics` and the context packet both say `available: false`
with the reason, and a Python step is refused with `SANDBOX_UNAVAILABLE`
instead of being run in-process. Real source data: every field is `demo_only`.
Durable thread state: in-memory, with `backend/services/threads.py` as the
intended seam. The spending ceiling: inert until prices are configured, and the
ledger says so rather than implying a control it does not have.

## The unfinished work, in priority order

1. Configure a credential and run the ownership benchmark and the browser UAT
   live. Until then the architecture is demonstrated but its outputs are not.
2. Compare the local token estimate against the provider's reported usage and
   revisit the two caps with measured evidence.
3. Implement isolated Python, or leave it disabled deliberately.
4. Bind the thread layer to `backend/services/threads.py`.
5. Ingest real data and update `COCKPIT_DATA_DOMAIN_MAPPING.md`, which
   currently states honestly that nothing is real.
