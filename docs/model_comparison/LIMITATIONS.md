# Limitations (as of this handover)

## Scope of what was proven

- **No live model was compared.** This cloud session had no Anthropic key for the app, no local runtime, no GPU and no approvals. Every quality finding in this repository comes from labelled FIXTURES run through the real engine.
- **The Mac folder was not compared against the tag.** The frozen identity is the GitHub tag `cockpit-round-h-live-pass-2026-09-23` (245c50e). Whether the Mac folder has uncommitted changes is unverified (see BASELINE_PROVENANCE §5).
- **Only one oracle task is registered:** Stage 2 EAD by sector, latest quarter, corporate book. Any other question gets NEEDS_REVIEW and no accuracy figure. Journeys J01–J06 and J09 need their own independent oracles before they can be tested.
- **The open-weight model identities are unverified.** They were taken from the master prompt's references and not re-fetched. Licence and provenance are UNVERIFIED until the model cards are read and artifact digests are pinned.

## Constraints from the frozen engine, not edited

- **Fixed deadlines.** Per-call timeouts of 30 s (action) and 55 s (answer), and run deadlines of 60–240 s, are fixed constants (OG-01). A slow local 9B model is likely to hit them. The lab reports that as a resource/profile outcome. Lengthening the deadlines would change governance, and would need approval as a separately named variant.
- **Disposition enum mismatch.** The wire schema offers `partial`, but the parser accepts only `partial_answer` (OG-02). This is a frozen defect, and it can penalise schema-strict models.
- **Frozen writers touch tracked files.** The frozen seeders and tests rewrite tracked `docs/cockpit_v4/evidence/*.json`. The lab's reseed passes `--no-evidence`, and `frozen_regression.py` restores those files and keeps a diff.

## Features not built

- Controlled checkpoint replay.
- Controlled common-context follow-ups.
- A model judge.
- A UAT-suite batch runner.
- A training-example export.
- Saving a new preset from the UI. Presets are files: copy an entry in `profiles/presets.json`.
- A separate concise report built through the existing document-export facility. The ZIP, HTML and workbook are provided instead.

## Measurement limits

- **Stage classification:** it joins the frozen call report, observer spans and messages by order within a run. That join is recorded as the attribution basis.
- **Sentence-level claim extraction:** it uses cue patterns, carries medium or low extraction confidence, and needs review.
- **Resource sampling:** it covers the lab process and host memory only. Model-runtime memory, and GPU or unified memory, need adapter-reported values (for example Ollama `/api/ps`), which have not yet been wired in.
- **Tokens:** fixture token counts are estimates (bytes ÷ 4). Token counts from different tokenizers are not comparable.

## Not in scope

The bank production build, hardware procurement, training, mixed-model routing and What-If integration are all out of scope. The release claim stays **EXPERIMENTAL**.
