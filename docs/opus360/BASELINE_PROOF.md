# P0 — Frozen baseline proof

Recorded 2026-09-27 in the certification environment, before any harness code was written.

## 1. Tag and commit

| Item | Value |
|---|---|
| Tag | `cockpit-round-h-live-pass-2026-09-23` |
| Tag object | `aa589cafa650e1ffd12713e84f8ab919b84a28f9` (annotated) |
| Tagger | Tuhin Chatterjee, 2026-09-23 09:02:54 +0400 |
| Tag message | "AdvancedCockpit Round H live UAT passed 2026-09-23" |
| `git rev-parse <tag>^{commit}` | `245c50e45786c6e0c866b281f9dd74da17d160b5` |
| Expected commit | `245c50e45786c6e0c866b281f9dd74da17d160b5`: **MATCH** |
| Commit subject | "Cockpit V4: refresh the provider-payload evidence" (2026-09-22 20:44:55 +0000) |
| Remote | `https://github.com/tuhinchatterjee/IPM_V2` (tag fetched from `origin`; `git ls-remote` shows `refs/tags/cockpit-round-h-live-pass-2026-09-23^{} = 245c50e…`) |

`main` does **not** contain this commit. The frozen AdvancedCockpit lives on a separate line of
history (`git merge-base --is-ancestor 245c50e main` fails). The certification branch was
therefore created **from the tag commit itself**, not from `main`.

## 2. Working-tree state

`git status --porcelain` at the frozen commit: **empty** (clean). The certification branch
`claude/opus360-architecture-certification` starts at `245c50e` and adds only new paths:
`scripts/opus360/`, `tests/opus360/`, `config/opus360/`, `docs/opus360/`, `launchers/`,
`artifacts/opus360/`.

## 3. Independent clone

This certification ran in a **disposable cloud container** holding a fresh GitHub clone. It is not
the presentation folder on the Mac, and it is not a `git worktree` of it. The Mac equivalent, as the
brief asks (`~/Desktop/IPM_V2-AdvancedCockpit-Opus360`), is created by
`launchers/CLONE_OPUS360_CERTIFICATION.command`. That launcher clones the certification branch
into a new directory, re-checks that the tag resolves to `245c50e`, and verifies that the frozen
commit is an ancestor of the clone's HEAD. It never touches the presentation clone. When
`OPUS360_LAKE_SOURCE` is set, it copies release files out of the presentation clone (a read-only
use of that clone).

## 4. Runtime environment

| Item | Value |
|---|---|
| Python | 3.12.3 (`.venv`, created with `uv venv --python /usr/bin/python3.12`; pyproject requires ≥3.12) |
| Dependencies | `requirements.txt` installed exactly (pinned). SHA-256 `fd9dd717f3ffd38a95179696efc6d4e733be65c2096ed6fd7a9b6b5306175b72` |
| pyproject.toml | SHA-256 `aec3cc3a7e6a3ae557ce0c66d778340d0686ee916316c88ddbd7d04094177521` |
| Key packages | anthropic 0.112.0 · duckdb 1.5.5 · pandas 3.0.3 · pyarrow 24.0.0 · numpy 2.5.0 · fastapi 0.141.1 |
| Lock evidence | every experiment manifest records `requirements_sha256`, `pip_freeze_sha256` and `key_packages` |
| Platform | Linux x86_64 cloud container. The overnight run is intended for macOS (launchers are `.command`) |

## 5. Frozen provider configuration

The configuration is read from the frozen code, not assumed.

| Item | Value | Source |
|---|---|---|
| Provider | `anthropic` (only value `service.resolve_provider` accepts) | `backend/cockpit_v4/service.py:100-118` |
| Model | `claude-opus-5` | `scripts/cockpit_v4/live_uat.py:57` (APPROVED_MODEL), `AI_COCKPIT_REASONING_MODEL` |
| Price card | `config/cockpit_v4/price_card.claude-opus-5.json`, verified 2026-09-21: input $5, output $25, cache write $6.25, cache read $0.50 per MTok | ROUND_H_LIVE_UAT.md §2 |
| Client | `backend/llm/anthropic_provider.AnthropicProvider`; `converse(..., allow_retry=False)` | `provider.py:338` |
| Prompt caching | not requested anywhere (no `cache_control`) | ROUND_H_LIVE_UAT.md §1 (re-verified) |
| Mode | `standard` (`STANDARD_LIMITS`, widened to `ANALYTICAL_STANDARD_LIMITS` on a declared analysis: 180 s, $1.50 per run) | `config.py:179-247` |
| Memory | disabled (`COCKPIT_V4_MEMORY_ENABLED=false`, the launcher default) | `start.py` |

## 6. Governed releases

| Domain | Release | Frequency | Periods | Approved fingerprint (Round H) | Fingerprint in this runtime |
|---|---|---|---|---|---|
| Corporate | `v4-saudi-corporate-20q-v4` | quarterly | 2021Q3…2026Q2 | `e37236d0f6d4e494…750f` | `c79d0fdf8753576f…a740` |
| Retail | `v4-saudi-retail-20m-v5` | monthly | 2025-01…2026-08 | `a1e797dcc73236b7…06cb` | `c23a15d78ba88d39…4e5b` |

The runtime also opens its pinned legacy release `v4-saudi-20q-v1` (the `start.py` default for
`COCKPIT_V4_RELEASE_ID`). Routes use the domain releases above for every run.

**Deviation, and why it does not invalidate the baseline.** The releases in this container were
rebuilt with the frozen deterministic generators (`scripts/cockpit_v4/seed_domains.py`). Their byte
fingerprints differ from the approved pair. The fingerprint is SHA-256 over the raw Parquet bytes
(`lake._digest`), and Parquet embeds writer-library metadata, so identical data written by a
different writer build hashes differently. To prove the **content** is the approved content, every
oracle value recorded in the Round H evidence (`docs/cockpit_v4/evidence/live_uat_dry_run.json`,
computed on the approved Mac releases) was recomputed on this container's releases:
**14 journeys, 140 values, 0 differences.** Every experiment re-runs this check in preflight
(`run_certification.content_parity`) and records the result in its manifest.

On the Mac, set `OPUS360_LAKE_SOURCE=<presentation clone>/data` before
`SETUP_OPUS360.command`. The approved release bytes are then copied, and the fingerprints match
the approved pair exactly.

## 7. Credential mechanism

The frozen mechanism is unchanged and reused:
`scripts/cockpit_v4/start.py:obtain_credential()` reads the `COCKPIT_ANTHROPIC_API_KEY`
environment variable, then the macOS Keychain service `creditprobe-cockpit-v4`, then a hidden
`getpass` prompt. The backend reads only `COCKPIT_ANTHROPIC_API_KEY` (`service.credential()`)
and never `ANTHROPIC_API_KEY`. The harness imports that function read-only. It passes the key to
the certification process in its environment only. The key never appears on a command line, in a
file, or in any evidence (every writer passes through `safe_io.redact`).

**In this container: `COCKPIT_ANTHROPIC_API_KEY` is absent and `OPUS360_MAX_USD` is absent.**
Under §25, no paid call was made.

## 8. Frozen regression (unchanged suite)

`python -m pytest tests/cockpit_v4 --ignore=tests/cockpit_v4/browser` at the frozen commit, with
all three releases present: **3,348 tests: 3,315 passed, 0 failed, 0 errors, 33 skipped**
(`artifacts/opus360/regression/before.json`). The browser suite needs the Next.js UI and Chromium
stack, and the brief states the browser is not the system under test.
