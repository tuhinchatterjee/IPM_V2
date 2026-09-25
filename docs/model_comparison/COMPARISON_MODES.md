# Comparison modes and classes

## Modes

| Mode | Status in this build |
|---|---|
| `E2E_BASELINE` (the Compare default) | Built. Every child runs the unchanged full workflow from the same frozen starting state. |
| `OBSERVED_STAGE_EVIDENCE` | Built, and automatic. Actual calls are classified into S1–S4 after the run (`FOUR_STAGE_CROSSWALK.md`). |
| `CONTROLLED_CHECKPOINT_REPLAY` | **Not built.** `/replays` answers 409 `REPLAY_NOT_APPROVED` / `INSUFFICIENT_REFERENCE`. Building it needs three things: (1) an approved, independently authored replay reference; (2) a real existing seam (for example, `Analyst` history at the answer turn); (3) a bounded "Deep diagnostics" preset. No replay seam has been added to the frozen pipeline. |
| `PARAMETER/CONTEXT_ABLATION` | Supported only as a **new profile file** with `parent_profile_id`, run as its own E2E comparison. There is no in-run variation. |
| `TRAINING_READINESS` | Built as a report (`/training-readiness`). No training. |

## Conversation modes

| Mode | Behaviour |
|---|---|
| Initial | Every child gets the same question, domain, data snapshot and mode. No child sees another child's output. |
| Clarification | The user's answer resumes only the children the user ticked. Each one continues on its own frozen thread. Recipients and text are recorded in `clarification.answered`. |
| Follow-up (`NATURAL_CONVERSATION`) | The same text goes to each child's own thread. The histories legitimately differ. |
| Controlled common context | Not built (it needs an approved common checkpoint). |

## Deployment classes

| Class | Behaviour |
|---|---|
| `mac_sequential` (default) | A single process-wide lane: one child at a time, with Opus never overlapping a local child during timing. |
| `remote_parallel` | Remote and external children run concurrently on a bounded pool (`LabConfig.remote_parallel_workers`), while local children stay sequential. Needs the `remote_inference` approval. Labelled `CROSS_DEPLOYMENT_COMPARISON`. |
| `same_model_hardware_diagnostic` | Same pinned artifact on two routes: two profiles sharing a `registry_id`, labelled as a deployment comparison and never as a training gain. |

Each result carries the applicable classes: `SEMANTIC_BASELINE_COMPARISON`, `SAME_HARDWARE_COMPARISON`, `CROSS_DEPLOYMENT_COMPARISON` and `FIXTURE_DEMONSTRATION`.

## Levels

| Level | Behaviour |
|---|---|
| Quick Compare | One question, one trial. Findings, no ranking. |
| Repeat Compare | `trial_count` 2–5 with `run_order_seed`, giving seeded, balanced blocks. |
| UAT Suite | Not built as a batch runner. It needs more oracle tasks first (J01–J06). |
