# Integration map — what was added, and what was not touched

## Ported verbatim from the frozen source

`19dc143c433eff190de7d304e53b7e941c96735b` (`claude/cockpit-single-agent-v4-h8fsbq`).
291 files, every one byte-identical to the source — recorded with its SHA-256 in
`PORTED_FILES.md`.

| Area | Paths |
|---|---|
| Engine | `backend/cockpit_v4/**` (58 modules, contracts, prompts, generators) |
| Its V3 dependency | `backend/cockpit_agentic/**`, reached only by import |
| Provider protocol | `backend/llm/base.py`, `backend/llm/anthropic_provider.py` |
| Cockpit UI | `frontend/src/components/cockpit-v4/**`, `frontend/src/components/system/runtime-surfaces.ts`, `frontend/src/lib/runtime.ts`, `frontend/src/app/cockpit/**` |
| Config, tooling, tests | `config/cockpit_v4/**`, `scripts/cockpit_v4/**`, `tests/cockpit_v4/**` |

`backend/llm/base.py` and `anthropic_provider.py` are the two files that already
existed here. The source versions are a strict superset: `base.py` adds
`ConverseResult`, `converse` and `count_tokens` and removes nothing;
`anthropic_provider.py` adds the same two methods and stops the API key
appearing in a dataclass repr. `backend/llm/cost.py` and `roles.py`, which the
engine does not import, are untouched.

## Added by this integration

| Class | Path | What it is |
|---|---|---|
| Data adapter | `backend/retail_cockpit_adapter/**` | source reader, semantic map, projection, publisher, gates, oracles |
| Tooling | `scripts/retail_cockpit/publish_release.py` | projects and publishes the release; `--verify` re-checks the fingerprint |
| Tooling | `scripts/retail_cockpit/check_oracles.py` | engine session versus the independent pandas oracle |
| Tooling | `scripts/retail_cockpit/write_contract_doc.py` | generates the contract document from the map |
| Docs | `docs/retail_cockpit/**` | this map, the baseline, the contract, the ported-file hashes |

## Changed in the protected core

Two files, two approved changes, each recorded with the reason it was needed.

**C1 — `backend/cockpit_v4/domains.py` (+24 lines):** `DEFAULT_RELEASES` may be overridden
per book by `COCKPIT_V4_<DOMAIN>_RELEASE_ID`. Unset — which is every other
deployment — the value is exactly the constant that was there, and nothing about
the runtime changes. It was needed because `domain_resolver.scope_for` takes
`release_id or DEFAULT_RELEASES[domain_id]` and `resolve`, the path every new
thread takes, never passes one, while `routes.py` refuses a caller-named release.

**C2 — `backend/cockpit_v4/catalog.py`:** the DuckDB session's memory limit and
temp directory, hard-coded in `_build_session`, become configurable through
`COCKPIT_V4_SQL_MEMORY_LIMIT` and `COCKPIT_V4_SQL_TEMP_DIR`. Unset, the executed
statement is character-for-character the one that was there, and the comment
recording the 1536MB measurement moved to the default it justifies. Needed
because this book materialises 2,968 MiB against that limit and spilled to the
process working directory — outside the runtime directory the engine otherwise
confines itself to. Both values are validated before they reach SQL and the temp
directory's containment is checked by `config.check_write_target`. The
measurements that chose the candidate's value are in `SESSION_MEMORY.md`.

Nothing else under `backend/cockpit_v4/` or `backend/cockpit_agentic/` differs
from the source. `git diff` against the source commit over those two trees shows
those two hunks and nothing else — asserted by
`tests/retail_cockpit/test_session_seam.py::test_the_core_diff_is_the_two_approved_files`.

## Not touched

The five published domains and their metadata; `backend/retail/**`;
`backend/api/routers/retail.py`; the Early Warning, Scorecard and What-If
modules; `launchers/retail/*`; the retail lake and catalogue, which the adapter
opens read-only and never writes to.

## Retail-only, by mechanism rather than by label

The candidate publishes one book. The corporate release is not published in its
lake, so `domain_resolver.availability()` reports Corporate not ready and
`analysis_supported("corporate")` is false — the engine's own mechanism, not a
new one. The Corporate/Retail control is hidden in the host UI mount.
