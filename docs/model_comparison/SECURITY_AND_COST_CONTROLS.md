# Security and cost controls

| Control | Implementation | Test |
|---|---|---|
| **Approvals are an operator action** | `scripts/model_lab/approve.py` writes `<runtime>/approvals.json` (mode 0600). No API, browser action, question or model output can grant one. Keys: `opus_spend` (needs a cap), `remote_inference` (needs a cap), `deep_diagnostics`. | `test_O05_*` |
| **Spend** | Preflight reserves $3.00 per eligible paid child, the frozen analytical-deep ceiling, and refuses creation when the group cap does not cover it. Before each child starts, committed + pending + reserve must still fit the cap. The frozen per-run `Ledger` still enforces its own ceiling. Unknown price means the route is not paid-eligible. | `test_O05_paid…` |
| **Egress** | Candidate children use only their own adapter. Candidate-only groups never construct an Anthropic client. Local profiles must use a loopback URL; remote profiles must use https. | `test_A13_…`, `test_A01_A12_…` |
| **Credentials** | Profiles name an environment variable (`api_key_env`) and never hold a key; the loader refuses a profile carrying `api_key`. The browser never receives keys. Exports never contain them. | `test_api_profiles_never_carry_secrets`, `test_O06_no_credentials…` |
| **Access** | The lab router is separate from the frozen router. The frozen principal resolver gives the owner scope; any other scope gets 404. The download path must resolve inside the lab exports directory. | `test_api_*` |
| **Untrusted content** | React renders model output as text only. There is no `dangerouslySetInnerHTML` in the lab. Export HTML is escaped and carries a no-script CSP. CSV/XLSX cells are guarded against formula injection. ZIP member names are fixed. | `test_O06_formula…`, browser U16b |
| **Model-authored code** | Always runs through the frozen validators and the frozen DuckDB/pyjail executor. The lab adds no executor. | `test_I11_…` |
| **Processes** | The lab stops only PIDs it recorded, re-verified by start time, command and cwd. It never kills by name. | Launcher code |
| **Data** | Synthetic releases only. Record-level rows in exports are bounded at 200 per table, and the omission is recorded in `limitations.md`. | `export.py` |
| **Retention** | Lab state lives under `artifacts/model_comparison/runtime/` (gitignored). Deleting that directory removes lab state only. It never reaches source data or model caches. | — |
