# Guided Risk Workspace — Mac live-provider UAT (P14)

This is the final human acceptance gate for this round. Everything automated
ran in the Linux container as MODEL MOCK (a scripted analyst). This run is
the one that uses the real provider, the real Keychain credential and a real
Mac browser. **No tag is created until it passes and you decide to freeze.**

The package was prepared and dry-run in the container; it has not been run
on a Mac. Where a step can only be proven on the Mac, it says so.

## 1. Get the exact build

No tag exists for this round. The candidate is pinned by SHA in
`docs/guided_workspace/UAT_CANDIDATE.json` on the programme branch
(`expected_guided_uat_sha`). That file is written by the evidence commit that
recorded the final regression of record, so it names the commit the
regression actually ran on: the commit **before** the evidence commit.

```bash
cd ~/Projects                                  # anywhere outside an existing checkout
git clone https://github.com/tuhinchatterjee/ipm_v2.git CreditProbe_GW_UAT
cd CreditProbe_GW_UAT
git fetch origin claude/guided-workspace-exhaustive-validation
git branch -f claude/guided-workspace-exhaustive-validation origin/claude/guided-workspace-exhaustive-validation
EXPECTED_GUIDED_UAT_SHA=$(git show origin/claude/guided-workspace-exhaustive-validation:docs/guided_workspace/UAT_CANDIDATE.json \
  | python3 -c 'import json,sys;print(json.load(sys.stdin)["expected_guided_uat_sha"])')
git checkout --detach "$EXPECTED_GUIDED_UAT_SHA"
git rev-parse HEAD                             # must print the same SHA; note it in your UAT notes
```

The preflight reads the manifest from the branch, not from the checked-out
tree, and refuses unless:
- `git rev-parse HEAD` equals `expected_guided_uat_sha` exactly;
- the working tree is clean;
- the Scenario Library, Lens and metric seed definitions hash to the digests the manifest recorded.

There is no `--any-revision`.

## 2. Build the environments and data (once, about 15 minutes)

```bash
python3 --version                              # must be 3.12 or newer
python3 -m venv --system-site-packages .venv-whatif
.venv-whatif/bin/pip install --ignore-installed -r requirements-whatif.txt
.venv-whatif/bin/pip check                     # must print "No broken requirements found."
npm ci --prefix frontend                       # installs Next.js
.venv-whatif/bin/python scripts/cockpit_v4/seed_release.py --release v4-saudi-20q-v1 --no-evidence
.venv-whatif/bin/python scripts/cockpit_v4/seed_domains.py
.venv-whatif/bin/python scripts/whatif/seed_candidate.py --domain all
.venv-whatif/bin/python scripts/whatif/train_emulator.py --domain all
git checkout -- artifacts/whatif docs/whatif   # keep the committed gate record (BASELINE_PROVENANCE §3)
git status --short                             # must be empty
```

Retraining refits the emulator pickles. They are untracked and are not
expected to be byte-identical across machines; the container could not
reproduce them byte-for-byte either (see the regression record, REG08). The
preflight checks their gate verdicts, not their bytes.

## 2a. Model and price card (once)

The committed `config/cockpit_v4/price_card.json` is a placeholder by design.
Editing it would dirty the pinned tree, which the preflight refuses. Keep the
verified card **outside** the checkout:

```bash
mkdir -p ~/.creditprobe
cp config/cockpit_v4/price_card.json ~/.creditprobe/price_card.json
# edit ~/.creditprobe/price_card.json: replace REPLACE-WITH-YOUR-MODEL-ID with your
# exact model id; fill in all four billing classes and verified_at (RUNBOOK step 4)
export AI_COCKPIT_REASONING_MODEL=<your exact model id>
```

The preflight resolves the model's capability row and its price-card entry
without a provider call, and refuses a card inside the checkout. Use
`COCKPIT_V4_PRICE_CARD` for a different location.
```

## 3. Store the provider credential in the Keychain (once)

```bash
security add-generic-password -s creditprobe-cockpit-v4 -a "$USER" -w
```

This is the accepted V4 Keychain item. You are prompted for the value; it is never echoed.
- The launcher reads it into its child processes only and never prints, logs or writes it.
- A value exported as `COCKPIT_ANTHROPIC_API_KEY` in the launching shell is **removed** from the child environment and not used.
- Only `--credential-from-shell` uses a shell value, and the start banner then says `SHELL`.

## 4. Preflight, start, status, stop

Double-click, or run from the checkout:

| Action | Launcher | Command |
|---|---|---|
| Preflight only | — | `.venv-whatif/bin/python scripts/guided_workspace/guided_preflight.py [--fresh]` |
| Start | `scripts/guided_workspace/START_GUIDED_WORKSPACE_UAT.command` | `.venv-whatif/bin/python scripts/guided_workspace/start_guided_uat.py [--fresh]` |
| Status | `scripts/guided_workspace/STATUS_GUIDED_WORKSPACE_UAT.command` | `.venv-whatif/bin/python scripts/cockpit_v4/status.py --runtime-dir ~/.creditprobe/guided_workspace_uat` |
| Stop | `scripts/guided_workspace/STOP_GUIDED_WORKSPACE_UAT.command` | `.venv-whatif/bin/python scripts/cockpit_v4/stop.py --runtime-dir ~/.creditprobe/guided_workspace_uat` |

- **Preflight checks** (any failure refuses; nothing is started):
  - HEAD equals the pinned SHA, the tree is clean, and the seed definitions match the pinned build;
  - Python 3.12 or newer and a clean `pip check` (LAUNCH01–02);
  - Next.js installed (LAUNCH03);
  - the What-If candidate books' fingerprints, both Guided Workspace books (Corporate `v4-saudi-corporate-20q-v4`, Retail `v4-saudi-retail-20m-v5`) verified, and the compatibility release `v4-saudi-20q-v1` published (LAUNCH04);
  - the emulator artifacts and their gate verdicts, including Retail's failed G4 (Method 2 stays UNAVAILABLE for Retail) (LAUNCH05);
  - the model and price card resolved without a call;
  - the credential present in the approved Keychain item, by name only;
  - the dedicated runtime directory belongs to this build. A directory left by another build is refused; `--fresh` moves it aside rather than deleting it.
- **Start:**
  - uses its own runtime directory, `~/.creditprobe/guided_workspace_uat`, so state, workspace and LLM Exchange stores are not shared with any other instance (LAUNCH08);
  - verifies model and price without a paid call (LAUNCH07);
  - steps over occupied ports and never kills their holder (LAUNCH09);
  - reports ready only after API and UI health (LAUNCH10). Default ports are 8434/5434.
- **Stop** kills only the pids Start recorded (LAUNCH11).
- **Status** prints the SHA, releases, ports, model and health (LAUNCH12).

## 5. The canonical journeys (live provider)

Record each as PASS / FAIL with a screenshot and, for Cockpit turns, the run
id. Every flag below is on for this run.

| # | Journey | Pass when |
|---|---|---|
| 1 | **Morning CRO** — open `/`, choose Corporate then Retail | Requires Attention cards with measured values and sparklines on both books; the free Ask box is above them |
| 2 | **Guided investigation** — open a card → Investigate → click two next-best-question chips → type one question of your own | Each chip runs as an ordinary turn in the same thread; the investigation path advances; your typed question is answered in the same thread |
| 3 | **What-If, UAT-01** — in the thread: "For the Construction borrowers, PD ×1.20 and LGD ×1.10, stages fixed" → confirm, choosing no method | The run stops at METHOD SELECTION and nothing executes. Choose Method 1 — Delta: the decomposition opens, selected scope and total book reconcile, and the bridge closes |
| 4 | **Combined scenarios** — in `/what-if`, run scenario A, then B "layered on the latest", then C on A+B | The baseline question is asked each time, the lineage tree shows A → A+B → A+B+C, and each result reconciles |
| 5 | **Lens creation and refresh** — from the thread, "Save this analysis as a Lens"; refine by asking; save; Refresh | A preview before saving; the saved Lens renders live values; refreshing writes a new observation (visible in its Trace) |
| 6 | **Alert → Investigate → What-If** — `/monitoring` → an active alert → Investigate in Cockpit, then What-If on the population | The thread opens on the alert's population; What-If opens with the same cohort (same membership hash) |
| 7 | **Messages sharing** — share a result with a second user id; as that user open, comment, duplicate, compare and run on own cohort | Every action works for the recipient; permissions hold; lineage shows the shared source |
| 8 | **Full LLM Exchange inspection** — Trace → LLM Exchange for a run from journey 3 | Every call shows canonical → translated → raw → normalized; the readable view labels SYSTEM / USER / ASSISTANT / TOOL CALL / TOOL RESULT / VALIDATOR; no credential appears anywhere; the AI Model Lab lists the same calls |
| 9 | **Macro sensitivity** — `/what-if`, the tornado, LGD only | Bars are labelled with their risk parameter. The collateral row shows SIGN_REVIEW; its sign is not corrected |
| 10 | **Governance** — on any result: Export package, then open Trace, Verify the whole tenant ledger, Verify a package (upload the zip) | Integrity verified, the ledger verifies, and the package verifies against the store |

Live answers vary in wording. Pass criteria are about governed behaviour
(gates, lineage, reconciliation, sanitisation), never about exact prose.

## 6. Collect the evidence pack (while still running)

```bash
.venv-whatif/bin/python scripts/guided_workspace/live_uat_evidence.py \
    --api http://127.0.0.1:8434 --out ~/CreditProbe_UAT_evidence
```

Use the API port Start printed if it stepped off 8434. The pack contains:
- the candidate SHA, and whether the runtime directory was created by it;
- the ledger verification;
- every recorded LLM call and each run's sanitized LLM Exchange package;
- each result you created, as a governed package verified against the store;
- the models actually served;
- a scan of the pack and of every runtime file (the databases with their WAL and SHM, and the logs) for the real credential. The scan reports PASS or FAIL; the value is never written.

The collector was dry-run in the container against the mock-analyst API. With a fake value, the scan reported PASS on a clean runtime and FAIL, exit 1, when the value was planted in a runtime file.

The command exits non-zero if the ledger, a package or the credential scan fails.

## 7. Acceptance

- **Accepted** only when all of these hold:
  - every journey in §5 passes;
  - the evidence pack reports `runtime_is_this_candidate: true`, `ledger_ok: true`, `packages_verified: true` and `credential_scan: PASS`;
  - no critical blocker is unresolved.
- **On acceptance:** freezing and tagging is your decision (P15). This round creates no tag.
- **On failure:** record the journey, the run id and a screenshot. Stop with the STOP launcher. Nothing else on the machine is affected.

## 8. Rollback

Run the STOP launcher, then:

```bash
rm -rf ~/.creditprobe/guided_workspace_uat ~/.creditprobe/guided_workspace_uat.*
```

The UAT clone is a separate directory. Deleting it removes the candidate from the Mac.

The accepted launchers under `scripts/cockpit_v4/`, and the earlier What-If launchers, are untouched and keep working as before. With the guided flags off the product behaves as before this round: the accepted browser suite runs flags-off in the regression of record (`docs/guided_workspace/evidence/final_regression/`).
