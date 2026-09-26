# Live-provider UAT — a separate gate

**Status: BLOCKED — CREDENTIALS NOT AVAILABLE HERE.**

Measured, not assumed: the variable this product reads is
`config.CREDENTIAL_VAR = "COCKPIT_ANTHROPIC_API_KEY"` (`config.py:32`), used by
`service.credential_status()` and `service.resolve_provider()`
(`service.py:95-118`). In this cloud container it is **unset**, as are
`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `AZURE_OPENAI_API_KEY`,
`COCKPIT_LLM_API_KEY`, `ANTHROPIC_AUTH_TOKEN` and `CLAUDE_API_KEY`.

`scripts/whatif/live_uat.py` **refuses** in that state and exits 2. It does not
fall back to the stub server, because evidence labelled LIVE over journeys
driven by a scripted analyst is worse than no evidence at all.

No API key is read, printed, logged or written by anything in this round. Only
`credential_status()`'s `PRESENT` / `MISSING` reaches the output or the
evidence file.

---

## What this gate is for, and what it is not

The 30 mock journeys (`J01–J15`, both books) prove the **path**: a question
typed into the Advanced Cockpit reaches `scenario/run.py` and its result
returns through the ordinary response path. They cannot prove the
**translation**, because the analyst's tool calls are written rather than
generated.

> The acceptance question is not whether the provider gives a beautiful
> paragraph. It is whether arbitrary natural language is reliably converted
> into the correct governed deterministic scenario contract.

So every assertion in `tests/cockpit_v4/browser/whatif.live.mjs` is about the
**contract**, read off the submitted step's own `parameters` rather than off
the prose: which book, which frozen cohort, which `field_id`, which
`operation`, whether a preview preceded any calculation, whether the
confirmation bound what ran. A beautiful paragraph over the wrong cohort is a
**failure**. A plain sentence over the right cohort, the right mapping and the
right arithmetic is a **pass**.

## The eight conversations

| # | Book | The reader's words | What the contract must be |
|---|---|---|---|
| **L1** | Corporate | *"Investigate deterioration in the portfolio and identify the customers driving the issue."* → *"For those customers increase PD by 20% and LGD by 10%."* | ONE scenario over ONE frozen cohort carrying BOTH `pd_pit_12m` and `lgd_pct`. Preview before calculation; approval binds it; Delta executes. The second half of the sentence must not be dropped. |
| **L2** | Corporate | *"What is our sensitivity to unemployment?"* → *"Reduce unemployment by 10% and show me what that does to PD, LGD and ECL."* | The first turn is a RETRIEVAL of the stored sensitivity — no scenario, no refit. The second is a **relative** move, not a percentage-point one, translated through the stored slope, previewed before anything runs. |
| **L3** | Corporate | *"Show me the sectors in this portfolio."* → *"For Construction increase PD by 25%, but for rating grades 7 and worse increase it by another 10%."* | The overlap is **explicitly resolved** — either the second rule carries its own scope, or the engine refuses with `RULE_CONFLICT` and asks which applies. Never silently composed, never called an approximation. |
| **L4** | Corporate | a 20% PD rise, comparing Delta, the ML emulator and the reader's own 15% assumption | Three methods against one confirmed scenario, one frozen cohort, one baseline, **side by side and never averaged**. |
| **L5** | Retail | investigate a deteriorating cohort → *"For those customers worsen behavioural score by 30 points."* | The **behavioural** score mapping, never the application score. "30 points" is an **absolute** move on a score, not a relative one. |
| **L6** | Retail | *"Increase PD by 20% for this cohort and compare every available method."* | Delta COMPLETE. ML **NOT READY**, with **G4** named and its measured **0.3436 against 0.1500** shown. No zero inserted, no other model substituted, no silent fall back to Delta. User-defined only if its assumption was given. |
| **L7** | Retail | *"For unsecured personal loans with weak behavioural scores, increase PD by 15% and LGD by 5."* — as the FIRST message | A scenario built with no prior investigation. The cohort is frozen and **named before** confirmation, both parameters reach the engine, and nothing is calculated until the reader approves. |
| **L8** | Retail | *"Stress them pretty badly."* | A **clarification**. No parameter, no magnitude and no cohort may be invented, and nothing may be calculated. |

## What is captured per journey

Written to `docs/whatif/evidence/live-uat.json` and the screenshots beside it:
the exact user wording, the **interpreted scenario** (the submitted
`whatif_scenario` parameters, read back from the run's own trace), the book and
release the thread is pinned to, the cohort id and membership hash, the
preview, the confirmation digest, the executed calculation, the displayed
result, the ledger reconciliation, the tool trace and a screenshot.

## How to run it on the Mac

```bash
cd <REPO>
git fetch --tags
git checkout whatif-candidate-h1      # the frozen candidate the preflight pins to

# 1. The credential, in the shell only. Never in a file, never in a .env.
export COCKPIT_ANTHROPIC_API_KEY='...'

# 2. Preflight: revision, interpreter, both releases and their fingerprints,
#    both emulators and their gate verdicts, credential PRESENT/MISSING.
.venv-whatif/bin/python scripts/whatif/uat_preflight.py

# 3. The live UAT. Refuses if the credential is absent; never uses the stub.
.venv-whatif/bin/python scripts/whatif/live_uat.py

# Or one journey at a time while reading the screen:
.venv-whatif/bin/python scripts/whatif/live_uat.py --only 'L5|L6' --keep-up
```

Or double-click `START_ADVANCEDCOCKPIT_WHATIF_UAT.command` to bring the
candidate up with the same preflight and drive it by hand.

Ports are discovered, never taken: an occupied port is stepped over and its
holder reported. An accepted Cockpit already running is not disturbed —
different interpreter, different ports, different state database, and the
What-If flags exist only in this run's child processes.

## Until it is run

This gate reads **BLOCKED — CREDENTIALS NOT AVAILABLE HERE** in the final
classification, and the 30 mock journeys keep their **MODEL MOCK** label.
Nothing is relabelled. A live journey that has not been executed is not
evidence, however carefully it was prepared.

Measured on GENERATED books. Nothing here is bank output, an accounting
figure, or a bank-validated model.
