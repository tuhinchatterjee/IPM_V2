# Validation baseline (exhaustive validation round)

Recorded at the start of the round, before any change: 2026-10-02T16:22:29Z.

| Item | Value |
|---|---|
| Starting branch | `claude/guided-workspace-final-gap-closure` |
| Starting SHA (evidence commit) | `55bfb9a4d30a61355aa027b72f93cc0c153d4ae1` |
| Candidate under validation | H `8b1592f46b06d03cec089d5b49cb93280b819993` |
| Validation branch | `claude/guided-workspace-exhaustive-validation`, created from `55bfb9a4` |
| `git status` at start | clean (0 entries) |
| Active test/browser/server processes at start | none |
| Tags | `cockpit-round-h-live-pass-2026-09-23`, `recovered-sep8-cockpit-v2`, `recovered-sep8-integrated`, `recovered-sep8-whatif`, `whatif-candidate-h1`, `windows-pilot-v1` (6; unchanged) |
| Accepted interpreter | `/home/user/.venv312` — Python 3.12.3 |
| Candidate (ML) interpreter | `.venv-whatif` — Python 3.12.3 |
| Frontend runtime | Node v22.22.2; Next.js 16.3.2; React 19.2.8; plotly.js-dist-min 3.7.0 |
| Model | MODEL MOCK (scripted analyst) for every browser journey; no provider credential in this container; no paid call authorised here |

## Releases (verified with `lake.verify`)

| Release | Fingerprint | Status |
|---|---|---|
| `v4-saudi-corporate-20q-v4` | `c79d0fdf8753576f391f2a6bb84f281595e7445291a558abe639f6a43e22a740` | VERIFIED |
| `v4-saudi-retail-20m-v5` | `c23a15d78ba88d39aeae6983e68fff2230b644f5c8f91bec5c89085399f04e5b` | VERIFIED |
| `v4-whatif-corporate-20q-s1` | `3b101bd41465fbe15f89d0d9563026e0f7f2e8081e9e778a90eebe553e01fce5` | VERIFIED |
| `v4-whatif-retail-20m-s1` | `98b494ae2721bd535f406eb6873c0b689c82da36152719e6c8e79c5da7ed92d3` | VERIFIED |
| `v4-saudi-20q-v1` (V3 store, compatibility) | manifest with 11 relations | PRESENT |

## Seed definitions (as pinned in `UAT_CANDIDATE.json`)

| Seed | Version | SHA-256 |
|---|---|---|
| Scenario templates | `gw-scenario-seed-1.0.0` | `b257bb00cb9636cefc3fb6d720dc6fa898370cdb0c0ac18969af6ff7a375e6da` |
| Lenses | `gw-lens-seed-1.1.0` | `055c4e6aaad7c7e6fbe32078c5ee99f63b0ee19a43f798988d4a82bdd59a6427` |
| Metrics | `gw-metrics-1.1.0` | `c2d5722a03077c46020b029e750fefa930623d32c048560721bd99a847204a8b` |

## Emulator artifacts in this runtime (first 16 hex of SHA-256)

| File | SHA-256 (16) | Bytes |
|---|---|---|
| corporate/additive_log.pkl | 7b9846aff63038dc | 13098 |
| corporate/lightgbm.pkl | 998c4afec676f446 | 3609743 |
| corporate/xgboost.pkl | d80c57b50de2b864 | 2017050 |
| corporate/blend.json | d0da0c08dac0aa9f | 3125 |
| retail/additive_log.pkl | e3d0f70e2c56f6f3 | 13123 |
| retail/lightgbm.pkl | 48cf0ac0c9d8eaed | 3603347 |
| retail/xgboost.pkl | 12e24f8ea5e81c81 | 1457113 |
| retail/blend.json | c29b9abf583fe9ec | 3157 |

The local pickles are this container's P0 refit (untracked); the committed
gate record (`blend.json`, model cards) is the published one. Component
pickle bytes differ from the published hashes for Corporate lightgbm and
Retail additive_log/lightgbm (REG08, BLOCKED_ENV); every gate verdict
reproduces.
