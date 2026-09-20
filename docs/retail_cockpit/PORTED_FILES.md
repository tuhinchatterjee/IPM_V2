# Ported source files — the verbatim record

Source: `19dc143c433eff190de7d304e53b7e941c96735b`
(branch `claude/cockpit-single-agent-v4-h8fsbq`).

291 files. Every one is byte-identical to the source except the **two
approved core changes** and the **one approved frontend exception** listed
below — which is the claim this file exists to let anybody check, with
`git diff 19dc143c -- backend/cockpit_v4 backend/cockpit_agentic` for the core
and `scripts/retail_cockpit/verify_port.py` for all 291 hashes.

The hashes in the table below are the hashes of the files **as they are now**,
so the check stays binding: the one file that moved carries its new hash and is
marked as the exception rather than quietly re-recorded as verbatim.

## The two approved changes

| File | Change | Approved as |
|---|---|---|
| `backend/cockpit_v4/domains.py` | `DEFAULT_RELEASES` may be overridden per book by `COCKPIT_V4_<DOMAIN>_RELEASE_ID`; unset, it is the constant that was there | C1 |
| `backend/cockpit_v4/catalog.py` | the session's DuckDB memory limit and temp directory become configurable; unset, the executed statement is character-for-character the one that was there | C2 |

## The approved frontend exception

| File | Change | Approved as |
|---|---|---|
| `frontend/src/components/cockpit-v4/attention-panel.tsx` | the ECL-highlights caption names the dimension the server actually cut the cards by, per book, instead of naming the corporate one in its own JSX | F1 |

`d14825cd5e47d43c…` → `bf5a2888369d42ff…`.

### Why no host override was possible

The frozen component hard-coded, on a **retail** book, *"by sector, by borrower
and across the book"*. The `<h2>` directly above it adapts, because the server
names its own section (`feed.highlights_label`, `attention_v2.py:1179`); this
`<p>` did not. Five seams were traced and none of them reaches it:

1. **Prop / context / slot.** `AttentionPanel` (`attention-panel.tsx:98-106`)
   takes exactly `{ onOpen, domain }`. No children, no slot, no render prop, and
   it calls no `useContext`. The caption is a literal text node inside its own
   `return`. A host wrapper cannot reach it; a host context provider changes
   nothing unless the component reads it, which is the same edit.
2. **A server-side field.** The V2 feed (`attention_v2.py:1170-1216`) carries
   `attention_label` and `highlights_label` and no note, caption, subtitle or
   description for the highlights section. (`segment_note`, rendered at
   `attention-panel.tsx:219`, is emitted only by the legacy `attention.py:1310`
   and is `undefined` here; it is also the *segments* section.) Adding one means
   editing `attention_v2.py`, which is protected core — and
   `tests/retail_cockpit/test_session_seam.py::
   test_the_core_diff_is_the_two_approved_files` machine-asserts that the core
   diff is exactly C1 + C2. It would also **still** require this frontend edit,
   because the `<p>` had no `{feed.…}` slot to read the new field. Strictly more
   expensive, and it does not avoid the edit.
3. **A module alias.** The sole importer is `cockpit-v4-home.tsx:30`, and it is
   **relative**: `import { AttentionPanel } from "./attention-panel";`.
   `tsconfig.json` declares only `@/*`; `next.config.ts` sets no alias at all
   and has neither a `webpack` nor a `turbopack` key. Redirecting a relative
   specifier means matching a resolved absolute path, twice and differently for
   Turbopack (`next dev`) and webpack (`next build`). Worse, `Card` is
   module-private (`attention-panel.tsx:53`), so a redirect target could not
   wrap — it would have to fork all ~165 lines of the panel including the fetch
   effect, the domain guard, and the failure and loading branches. Duplicating
   that is a larger integrity hole than one caption.
4. **A localization override.** There is none: no i18n provider, no message
   catalogue, no translation hook, and `find frontend/src -name '*.json'`
   returns zero files. Every string in the tree is literal English in JSX.
5. **A CSS or DOM overlay.** Hiding the `<p>` and injecting text through
   `::after` leaves the wrong string in the DOM and the accessibility tree —
   concealment rather than correction — and the browser check reads
   `textContent`, so it would not even pass.

### What the change says, and why that wording

The engine itself decides the dimension: `attention_v2.py:918`,
`dimension = "sector" if domain_id == dom.CORPORATE else "product"`, and it
labels the cards `"Sector"` / `"Product"` / `"Whole book"` at
`attention_v2.py:979-981`. The retail caption states what the retail cards
actually are. **Corporate output is character-for-character unchanged**, so the
frozen book's page is provably untouched; an unrecognised book renders
`N distinct ECL developments.` and claims no dimension.

Held by `tests/retail_cockpit/test_retail_vocabulary.py`, which pins the
corporate string, forbids `sector`/`borrower` in the retail string, and asserts
this file's SHA-256 against the row above so the record and the file cannot
drift apart.

## Every ported file

| file | sha256 (first 16) | against the source |
|---|---|---|
| `backend/cockpit_agentic/__init__.py` | c12e99882f3841a4 | verbatim |
| `backend/cockpit_agentic/_pyjail_boot.py` | cbb0ccf5de3e3de1 | verbatim |
| `backend/cockpit_agentic/answer_check.py` | 75f15c68b92306e3 | verbatim |
| `backend/cockpit_agentic/calendar.py` | e9ea91537867976b | verbatim |
| `backend/cockpit_agentic/catalog.py` | 152042abe1eb177c | verbatim |
| `backend/cockpit_agentic/context.py` | 814ad18bbc3ea871 | verbatim |
| `backend/cockpit_agentic/contracts.py` | b40ff7c9e14bd05d | verbatim |
| `backend/cockpit_agentic/credential.py` | bcfd0de64bc1c5f5 | verbatim |
| `backend/cockpit_agentic/failure.py` | 853fa48a5513ecd5 | verbatim |
| `backend/cockpit_agentic/fields.py` | edd71340aefeba62 | verbatim |
| `backend/cockpit_agentic/generate.py` | 9da9a753d6386493 | verbatim |
| `backend/cockpit_agentic/ledger.py` | b1da004565a1e23d | verbatim |
| `backend/cockpit_agentic/models.py` | 5edf83ecbb4b9514 | verbatim |
| `backend/cockpit_agentic/opus.py` | 135a1a70f072d4d5 | verbatim |
| `backend/cockpit_agentic/profile.py` | 814a6c818fcff71b | verbatim |
| `backend/cockpit_agentic/prompts/opus_answer_rewrite.md` | f002601881c00d51 | verbatim |
| `backend/cockpit_agentic/prompts/opus_gate.md` | 8debf1e52d758808 | verbatim |
| `backend/cockpit_agentic/prompts/opus_plan.md` | b6a690b88944ed83 | verbatim |
| `backend/cockpit_agentic/prompts/opus_plan_compact.md` | 4127272c71d39744 | verbatim |
| `backend/cockpit_agentic/prompts/opus_repair.md` | ab561a244805ff80 | verbatim |
| `backend/cockpit_agentic/prompts/opus_review_and_answer.md` | 52eee30ccfd6c32b | verbatim |
| `backend/cockpit_agentic/prompts/shared_preamble.md` | c22335b24dc8478d | verbatim |
| `backend/cockpit_agentic/prompts/sonnet_pass1_cleanup.md` | 7ef7874606bbe410 | verbatim |
| `backend/cockpit_agentic/prompts/sonnet_pass2_normalize.md` | 14845a034c6c883f | verbatim |
| `backend/cockpit_agentic/prompts/sonnet_summary.md` | 4dd77658fe618c8f | verbatim |
| `backend/cockpit_agentic/pysandbox.py` | 1d67443b5df1cd54 | verbatim |
| `backend/cockpit_agentic/registry.py` | 62456dbbe027c3ec | verbatim |
| `backend/cockpit_agentic/runtime.py` | e6f9593088459eff | verbatim |
| `backend/cockpit_agentic/scope.py` | d2c7ba20c7f90431 | verbatim |
| `backend/cockpit_agentic/service.py` | fd3c6f67f10c653a | verbatim |
| `backend/cockpit_agentic/sonnet.py` | 8fbecd0fe325cf2e | verbatim |
| `backend/cockpit_agentic/sql.py` | 474628d537b3de7a | verbatim |
| `backend/cockpit_agentic/states.py` | 254e59ebb15f6a89 | verbatim |
| `backend/cockpit_agentic/store.py` | 25eada0d90226646 | verbatim |
| `backend/cockpit_agentic/thread.py` | 3774d8bc93187b31 | verbatim |
| `backend/cockpit_agentic/tokens.py` | 3e7470f775b28b70 | verbatim |
| `backend/cockpit_agentic/validate_data.py` | e85fe2f945fd6822 | verbatim |
| `backend/cockpit_v4/__init__.py` | bb0697ab27124455 | verbatim |
| `backend/cockpit_v4/action_state.py` | 0e8082f77bff85e5 | verbatim |
| `backend/cockpit_v4/analytical_runtime.py` | 88448fbebf80d5d4 | verbatim |
| `backend/cockpit_v4/app.py` | 09bcffd75422d95d | verbatim |
| `backend/cockpit_v4/artifacts.py` | 07bdd838cc3ca1e7 | verbatim |
| `backend/cockpit_v4/attention.py` | 6cd77c752e7d674a | verbatim |
| `backend/cockpit_v4/attention_v2.py` | 25523fd725a3b5e2 | verbatim |
| `backend/cockpit_v4/budgets.py` | a346a7b660c2e50b | verbatim |
| `backend/cockpit_v4/capability.py` | c26768d83ac29dd2 | verbatim |
| `backend/cockpit_v4/catalog.py` | bd5f2bbab8609293 | **CHANGED — see below** |
| `backend/cockpit_v4/catalog_tool.py` | c43964d4eca0feb2 | verbatim |
| `backend/cockpit_v4/collaboration.py` | b8784757baa4957c | verbatim |
| `backend/cockpit_v4/compat_health.py` | 1444828fb01103b3 | verbatim |
| `backend/cockpit_v4/config.py` | ddc5682a106eee86 | verbatim |
| `backend/cockpit_v4/context.py` | 2aeb79f1fa9a4be5 | verbatim |
| `backend/cockpit_v4/contracts.py` | 7b942a2c2d754f3d | verbatim |
| `backend/cockpit_v4/contracts/error.schema.json` | be9dcfc2ddbdcf93 | verbatim |
| `backend/cockpit_v4/contracts/event.schema.json` | b72559cededdd620 | verbatim |
| `backend/cockpit_v4/contracts/execute_analysis.schema.json` | 84b6bf4f19fd1da5 | verbatim |
| `backend/cockpit_v4/contracts/finalize_response.schema.json` | dd70b6c0546902c2 | verbatim |
| `backend/cockpit_v4/contracts/inspect_catalog.schema.json` | c978efc94c27f3aa | verbatim |
| `backend/cockpit_v4/contracts/inspect_product_knowledge.schema.json` | fa933472fb836663 | verbatim |
| `backend/cockpit_v4/contracts/read_artifact.schema.json` | 91cd37a548209018 | verbatim |
| `backend/cockpit_v4/contracts/shared_defs.schema.json` | 777408e9a8594d04 | verbatim |
| `backend/cockpit_v4/contracts/state_machine.json` | 7f4dd141d54645f6 | verbatim |
| `backend/cockpit_v4/credit_policy.json` | df0dd2911fd569ff | verbatim |
| `backend/cockpit_v4/credit_policy.py` | adfd09830ca3ea62 | verbatim |
| `backend/cockpit_v4/derivation.py` | d76d1b6ff6d837c9 | verbatim |
| `backend/cockpit_v4/display.py` | b6d9969db6db88fd | verbatim |
| `backend/cockpit_v4/domain_resolver.py` | 357bc161d34870e0 | verbatim |
| `backend/cockpit_v4/domains.py` | bd9b5e3be82853fb | **CHANGED — see below** |
| `backend/cockpit_v4/ecl.py` | 3b78e64299024381 | verbatim |
| `backend/cockpit_v4/envelope.py` | 4528b117cd6ea0eb | verbatim |
| `backend/cockpit_v4/events.py` | 32782d8695d7ac42 | verbatim |
| `backend/cockpit_v4/execute_tool.py` | 013177300524672f | verbatim |
| `backend/cockpit_v4/export.py` | e60fab467bd6ae21 | verbatim |
| `backend/cockpit_v4/finalization.py` | 203488e324188c3a | verbatim |
| `backend/cockpit_v4/generate/__init__.py` | 82f3e5b734e3db56 | verbatim |
| `backend/cockpit_v4/generate/corporate.py` | fdd3803133fa3b6d | verbatim |
| `backend/cockpit_v4/generate/retail.py` | cf383f972f98f2f1 | verbatim |
| `backend/cockpit_v4/generate/totals.py` | 115f86cab0a6a8b0 | verbatim |
| `backend/cockpit_v4/intake.py` | f257dd53863506bd | verbatim |
| `backend/cockpit_v4/intent_envelope.py` | d269b6c81694af45 | verbatim |
| `backend/cockpit_v4/invariants.py` | ac92f0b12ae485a7 | verbatim |
| `backend/cockpit_v4/investigation.py` | 006fe8af27ab2ce8 | verbatim |
| `backend/cockpit_v4/lake.py` | b9031789fec8c778 | verbatim |
| `backend/cockpit_v4/memory.py` | 6061606f5e59e6e1 | verbatim |
| `backend/cockpit_v4/model_capabilities.py` | 5eb32d99f6fb24de | verbatim |
| `backend/cockpit_v4/orchestration.py` | 5cea23b02663ce5c | verbatim |
| `backend/cockpit_v4/precision.py` | e67967559744809a | verbatim |
| `backend/cockpit_v4/product_knowledge.json` | 4a24e8af64328601 | verbatim |
| `backend/cockpit_v4/product_knowledge.py` | 309ff460a76f79a6 | verbatim |
| `backend/cockpit_v4/prompts/analyst.md` | 624b80263e2ed9d3 | verbatim |
| `backend/cockpit_v4/provider.py` | c91cb4531d9eeed4 | verbatim |
| `backend/cockpit_v4/pyrunner.py` | 45961f0f31d29d22 | verbatim |
| `backend/cockpit_v4/readiness.py` | a0dc1107f971cfa9 | verbatim |
| `backend/cockpit_v4/release.py` | f0cbcbfaf5c825a8 | verbatim |
| `backend/cockpit_v4/routes.py` | ba245b650c259330 | verbatim |
| `backend/cockpit_v4/run_store.py` | e3be63358f3c2fe7 | verbatim |
| `backend/cockpit_v4/saudi.py` | b68dbf5fc3183846 | verbatim |
| `backend/cockpit_v4/schema.py` | d4b99287299307f4 | verbatim |
| `backend/cockpit_v4/semantics.py` | ca1182dd2b3ce874 | verbatim |
| `backend/cockpit_v4/service.py` | f0e9934b313f6c20 | verbatim |
| `backend/cockpit_v4/sql.py` | 241f608854380c76 | verbatim |
| `backend/cockpit_v4/sqlbind.py` | ae2cdf5c3bf4a563 | verbatim |
| `backend/cockpit_v4/states.py` | bc505493a597da68 | verbatim |
| `backend/cockpit_v4/supervisor.py` | 2cc7ab3e98eaf3b9 | verbatim |
| `backend/cockpit_v4/values.py` | 81eca26bed0907b4 | verbatim |
| `backend/cockpit_v4/worker.py` | 045bafd783e175fe | verbatim |
| `backend/llm/anthropic_provider.py` | e519ce4e902b7a4e | verbatim |
| `backend/llm/base.py` | 32845d96bf8668e9 | verbatim |
| `config/cockpit_v4/price_card.json` | 7ac61d636eb5e602 | verbatim |
| `frontend/src/app/cockpit/data/page.tsx` | 9ea0ae6d98a7d970 | verbatim |
| `frontend/src/app/cockpit/thread/[threadId]/page.tsx` | 45ebf2c4faf9bfb9 | verbatim |
| `frontend/src/components/cockpit-v4/answer-actions.tsx` | 8e26d53e3149cd15 | verbatim |
| `frontend/src/components/cockpit-v4/ask-box.tsx` | 595dde9e97784386 | verbatim |
| `frontend/src/components/cockpit-v4/attention-client.test.ts` | dd1993fdb99b7c81 | verbatim |
| `frontend/src/components/cockpit-v4/attention-drawer.tsx` | 716a25e0063a3d0f | verbatim |
| `frontend/src/components/cockpit-v4/attention-panel.tsx` | bf5a2888369d42ff | **frontend exception (F1)** |
| `frontend/src/components/cockpit-v4/claim-display.test.ts` | 87687f7d9783347d | verbatim |
| `frontend/src/components/cockpit-v4/claim-display.ts` | 563bbb3a5c43111e | verbatim |
| `frontend/src/components/cockpit-v4/client.test.ts` | 933b9d155b0c6455 | verbatim |
| `frontend/src/components/cockpit-v4/client.ts` | 56d1dc0541ff70f8 | verbatim |
| `frontend/src/components/cockpit-v4/clock.test.ts` | 2f8435b8f53baf06 | verbatim |
| `frontend/src/components/cockpit-v4/clock.ts` | 62e508559feb7838 | verbatim |
| `frontend/src/components/cockpit-v4/cockpit-v4-home.tsx` | 1577e6f351e0d4f3 | verbatim |
| `frontend/src/components/cockpit-v4/collaboration-client.test.ts` | 0df910de04445bd1 | verbatim |
| `frontend/src/components/cockpit-v4/continue-where-you-left-off.tsx` | 3a1b5b05724029f1 | verbatim |
| `frontend/src/components/cockpit-v4/data-books.tsx` | 3370ef5579bb374a | verbatim |
| `frontend/src/components/cockpit-v4/domain-guard.test.ts` | 9731c23f647c1389 | verbatim |
| `frontend/src/components/cockpit-v4/domain-guard.ts` | a1422c23ba1f8224 | verbatim |
| `frontend/src/components/cockpit-v4/domain-meta.test.ts` | 2c3a08cf5983750d | verbatim |
| `frontend/src/components/cockpit-v4/domain-meta.ts` | 8490e0f7c598f195 | verbatim |
| `frontend/src/components/cockpit-v4/domain-switch.tsx` | ac3f6805782b6a7e | verbatim |
| `frontend/src/components/cockpit-v4/ecl-panel.tsx` | 017f40f88d5c06cf | verbatim |
| `frontend/src/components/cockpit-v4/follow-ups.test.ts` | 16f1ff015f6beb97 | verbatim |
| `frontend/src/components/cockpit-v4/follow-ups.ts` | 80dc91b240ee73da | verbatim |
| `frontend/src/components/cockpit-v4/greeting.test.ts` | 2525ee7418270c4e | verbatim |
| `frontend/src/components/cockpit-v4/greeting.ts` | cac08e56ec170630 | verbatim |
| `frontend/src/components/cockpit-v4/live-run-fixture.ts` | b2a5bbabb33b1734 | verbatim |
| `frontend/src/components/cockpit-v4/live-trace.test.ts` | e5a36237041a8c9b | verbatim |
| `frontend/src/components/cockpit-v4/markdown-parse.ts` | 82d32257e4eaec13 | verbatim |
| `frontend/src/components/cockpit-v4/markdown.test.ts` | 8282f11b1ac32ffd | verbatim |
| `frontend/src/components/cockpit-v4/markdown.tsx` | de42904b7e5ab6c8 | verbatim |
| `frontend/src/components/cockpit-v4/not-in-this-runtime.tsx` | 9bed2d600947f816 | verbatim |
| `frontend/src/components/cockpit-v4/period.ts` | b72102e672b44215 | verbatim |
| `frontend/src/components/cockpit-v4/process-panel.tsx` | a34dbfb33ad82246 | verbatim |
| `frontend/src/components/cockpit-v4/reducer.test.ts` | f84aaa60c64ca8e5 | verbatim |
| `frontend/src/components/cockpit-v4/reducer.ts` | 29ac9281f7132029 | verbatim |
| `frontend/src/components/cockpit-v4/response-panel.tsx` | ec85027173157111 | verbatim |
| `frontend/src/components/cockpit-v4/thread-view.tsx` | 0e1959a73295c481 | verbatim |
| `frontend/src/components/cockpit-v4/visual-choice.ts` | 2aad9ef8213bddb6 | verbatim |
| `frontend/src/components/cockpit-v4/visuals.test.ts` | c0b15f3493fd0ea2 | verbatim |
| `frontend/src/components/cockpit-v4/visuals.tsx` | 604a0ed935d9ed78 | verbatim |
| `frontend/src/components/system/runtime-surfaces.ts` | ea3d04a13836148e | verbatim |
| `frontend/src/lib/runtime.ts` | 1c0f6538cfb551da | verbatim |
| `scripts/cockpit_v4/START_COCKPIT_V4.command` | a4d94b2f196c79f2 | verbatim |
| `scripts/cockpit_v4/STATUS_COCKPIT_V4.command` | fb56540294f7d302 | verbatim |
| `scripts/cockpit_v4/STOP_COCKPIT_V4.command` | 868a5afe26f3b2df | verbatim |
| `scripts/cockpit_v4/_common.py` | 47a127e4646fe224 | verbatim |
| `scripts/cockpit_v4/acceptance_evidence.py` | e2d5d7a50980dee6 | verbatim |
| `scripts/cockpit_v4/answer_size_evidence.py` | aab12fed01ac36a8 | verbatim |
| `scripts/cockpit_v4/browser_evidence.py` | 4f519e67cac26b30 | verbatim |
| `scripts/cockpit_v4/example_traces.py` | e8b5bcb9d3a33627 | verbatim |
| `scripts/cockpit_v4/flake_matrix.py` | d1bc7287259e26d4 | verbatim |
| `scripts/cockpit_v4/ingest_product_deck.py` | fbbc59a347550b7d | verbatim |
| `scripts/cockpit_v4/live_path_evidence.py` | 073986c5461dca87 | verbatim |
| `scripts/cockpit_v4/numeric_evidence.py` | 2f8634fca55276f3 | verbatim |
| `scripts/cockpit_v4/orchestration_evidence.py` | 3665aca5ac7928fc | verbatim |
| `scripts/cockpit_v4/release_report.py` | 6c89e75ab2ceee74 | verbatim |
| `scripts/cockpit_v4/seed_domains.py` | e531d2951d76c102 | verbatim |
| `scripts/cockpit_v4/seed_release.py` | 5449a2ab5ef58ba3 | verbatim |
| `scripts/cockpit_v4/start.py` | 81c2ea83c0134fa6 | verbatim |
| `scripts/cockpit_v4/status.py` | e68dbb30246d3db3 | verbatim |
| `scripts/cockpit_v4/stop.py` | c1c36cabff852473 | verbatim |
| `scripts/cockpit_v4/stub_server.py` | 61a15c684c26e983 | verbatim |
| `tests/cockpit_v4/__init__.py` | e3b0c44298fc1c14 | verbatim |
| `tests/cockpit_v4/answer_object.py` | 920a6c28aa40b9c7 | verbatim |
| `tests/cockpit_v4/attention_oracle.py` | d756be7844eacc46 | verbatim |
| `tests/cockpit_v4/browser/cockpit_v4.browser.mjs` | 5e089e9dea3f0e2a | verbatim |
| `tests/cockpit_v4/conftest.py` | 2ce6220fc81993c4 | verbatim |
| `tests/cockpit_v4/domain_oracles.py` | 11eb638eea6242de | verbatim |
| `tests/cockpit_v4/math_bank.py` | f463f240e4bd1030 | verbatim |
| `tests/cockpit_v4/math_sql.py` | 3c24b1c9cf41210a | verbatim |
| `tests/cockpit_v4/oracles.py` | d31a4d64067e3ae8 | verbatim |
| `tests/cockpit_v4/question_bank.py` | 55b212e4c3f278b7 | verbatim |
| `tests/cockpit_v4/test_action_contract.py` | 6528534a7ffd78f6 | verbatim |
| `tests/cockpit_v4/test_action_latency.py` | 55e1851285123cc0 | verbatim |
| `tests/cockpit_v4/test_action_matrices.py` | 7dc438c8098cd0e2 | verbatim |
| `tests/cockpit_v4/test_action_payload_snapshot.py` | 61eb644841fba258 | verbatim |
| `tests/cockpit_v4/test_action_state_machine.py` | 743d83c3d229c40e | verbatim |
| `tests/cockpit_v4/test_analytical_execution.py` | 183619cafd4cae1c | verbatim |
| `tests/cockpit_v4/test_answer_allowance.py` | 8c52b84f269a3fb7 | verbatim |
| `tests/cockpit_v4/test_api_and_lifecycle.py` | 962e2aa20c1afcd7 | verbatim |
| `tests/cockpit_v4/test_attention_domains.py` | c0bf823f34b4da15 | verbatim |
| `tests/cockpit_v4/test_attention_feed.py` | 2771b753cf207b38 | verbatim |
| `tests/cockpit_v4/test_budget_envelope.py` | 8797bcf49cfa4a67 | verbatim |
| `tests/cockpit_v4/test_call_report.py` | 85c8240123975fdb | verbatim |
| `tests/cockpit_v4/test_catalog_answer_memory.py` | cbe4850afc170d4a | verbatim |
| `tests/cockpit_v4/test_catalog_convergence.py` | da7d1c32e8452ce1 | verbatim |
| `tests/cockpit_v4/test_chains.py` | faf5de05d5b31339 | verbatim |
| `tests/cockpit_v4/test_chart_forms.py` | ae8cb7f5a5ee75e5 | verbatim |
| `tests/cockpit_v4/test_chart_presentation.py` | 0ba65bed1d8784e5 | verbatim |
| `tests/cockpit_v4/test_claim_rendering.py` | e356aa43b2c3133c | verbatim |
| `tests/cockpit_v4/test_clarification_turn.py` | d7eb12f93c43eec0 | verbatim |
| `tests/cockpit_v4/test_collaboration_and_threads.py` | 3e473b5f8779a755 | verbatim |
| `tests/cockpit_v4/test_compartmentalization.py` | 89ed996fdda763af | verbatim |
| `tests/cockpit_v4/test_convergence.py` | 26adf98c2563dd4d | verbatim |
| `tests/cockpit_v4/test_credit_policy.py` | f1befb5f8960ad16 | verbatim |
| `tests/cockpit_v4/test_data_builder.py` | 82a27dd9445da448 | verbatim |
| `tests/cockpit_v4/test_deadline_settlement.py` | 89bddf35992e1ef7 | verbatim |
| `tests/cockpit_v4/test_derived_claims.py` | cee88af89f426c99 | verbatim |
| `tests/cockpit_v4/test_display_policy.py` | 552061ebb44af847 | verbatim |
| `tests/cockpit_v4/test_display_precision.py` | f860a9c1c9ee4443 | verbatim |
| `tests/cockpit_v4/test_domain_and_numerics.py` | 046dfd20ae442641 | verbatim |
| `tests/cockpit_v4/test_domain_calendar_presentation.py` | 0a7bc1e5c51457e6 | verbatim |
| `tests/cockpit_v4/test_domain_execution.py` | 1c38fb0d20746259 | verbatim |
| `tests/cockpit_v4/test_domain_routes.py` | 2f5e88712e8f0fcc | verbatim |
| `tests/cockpit_v4/test_domains.py` | 9acc7749ec158242 | verbatim |
| `tests/cockpit_v4/test_dual_domain_performance.py` | 4c41c4ff57127d5b | verbatim |
| `tests/cockpit_v4/test_ecl_panel.py` | 4946955fcd118117 | verbatim |
| `tests/cockpit_v4/test_event_contract_parity.py` | 019e237531c19df5 | verbatim |
| `tests/cockpit_v4/test_export.py` | 1f6383fc9a96581d | verbatim |
| `tests/cockpit_v4/test_failure_injection.py` | b81ebc0ea029a3d4 | verbatim |
| `tests/cockpit_v4/test_field_units.py` | e108fd54034b8718 | verbatim |
| `tests/cockpit_v4/test_frontend_wiring.py` | 52d8e153e7177342 | verbatim |
| `tests/cockpit_v4/test_generator_determinism.py` | 73f2bbd19dab9cc0 | verbatim |
| `tests/cockpit_v4/test_governed_precision.py` | 1b7f1ba61d87a3b8 | verbatim |
| `tests/cockpit_v4/test_incident_err_2569c1be3faa.py` | 3b4e69437c8c83b3 | verbatim |
| `tests/cockpit_v4/test_intent_contract.py` | 79ef2b312d885035 | verbatim |
| `tests/cockpit_v4/test_intent_envelope.py` | b47ded77331d8a38 | verbatim |
| `tests/cockpit_v4/test_investigation_packet.py` | c29ef13f18bf4e08 | verbatim |
| `tests/cockpit_v4/test_investigation_routing.py` | 06aea45efe2a583a | verbatim |
| `tests/cockpit_v4/test_join_grain_refusal.py` | b85aedb82b04136c | verbatim |
| `tests/cockpit_v4/test_language_and_intent.py` | cb3c3b18cb6866b1 | verbatim |
| `tests/cockpit_v4/test_latency_orchestration.py` | d6af932d0a397af4 | verbatim |
| `tests/cockpit_v4/test_launcher_safety.py` | 66c81cec9547d407 | verbatim |
| `tests/cockpit_v4/test_limits_and_isolation.py` | ecf45051cd317968 | verbatim |
| `tests/cockpit_v4/test_live_run_62282e6b.py` | 1c6307ac2586dbf0 | verbatim |
| `tests/cockpit_v4/test_live_uat_replay.py` | a8a82424ed04d633 | verbatim |
| `tests/cockpit_v4/test_mac_action_replay.py` | f0fe76d59126f881 | verbatim |
| `tests/cockpit_v4/test_mac_replay.py` | d915c26637990ef4 | verbatim |
| `tests/cockpit_v4/test_mandatory_analytical_cases.py` | 54d8787c7ccfbef3 | verbatim |
| `tests/cockpit_v4/test_math_bank_rendering.py` | 466bfdb2a22f1044 | verbatim |
| `tests/cockpit_v4/test_math_pipeline.py` | 8b3594ef0d2053cf | verbatim |
| `tests/cockpit_v4/test_metadata_bank.py` | 86b87afcadb97a1d | verbatim |
| `tests/cockpit_v4/test_money_and_period_format.py` | 79b83f61718d138d | verbatim |
| `tests/cockpit_v4/test_multilingual_and_evidence_labels.py` | 957fcaaf03a54fb9 | verbatim |
| `tests/cockpit_v4/test_narrative_units.py` | cc3c1a4fcbe0ad65 | verbatim |
| `tests/cockpit_v4/test_negative.py` | c01ad9b380cd5a97 | verbatim |
| `tests/cockpit_v4/test_no_global_domain.py` | 969af33a1860ebb9 | verbatim |
| `tests/cockpit_v4/test_opening_questions.py` | ce2f8d2aa82800b0 | verbatim |
| `tests/cockpit_v4/test_operator_detail_route.py` | 8dd85742022482fe | verbatim |
| `tests/cockpit_v4/test_orchestration_recovery.py` | e4a20b160a0c4b04 | verbatim |
| `tests/cockpit_v4/test_overnight_benchmark.py` | fbe06cb4c09350da | verbatim |
| `tests/cockpit_v4/test_ownership_and_security.py` | 3b63f4a9735bd026 | verbatim |
| `tests/cockpit_v4/test_performance_gates.py` | 821eb52571e94700 | verbatim |
| `tests/cockpit_v4/test_performance_profile.py` | f474e88707d5db07 | verbatim |
| `tests/cockpit_v4/test_planted_patterns.py` | c08479693ce188c9 | verbatim |
| `tests/cockpit_v4/test_process_events.py` | 38fb731aea6a4f26 | verbatim |
| `tests/cockpit_v4/test_product_help_benchmark.py` | 3311e5a85db40926 | verbatim |
| `tests/cockpit_v4/test_product_help_semantics.py` | 2747158497341f37 | verbatim |
| `tests/cockpit_v4/test_protocol_and_bounds.py` | dc26b98f06d7fe38 | verbatim |
| `tests/cockpit_v4/test_provider_payload.py` | d51397b24f35be3c | verbatim |
| `tests/cockpit_v4/test_provider_payload_isolation.py` | 73ae4747e07e21e7 | verbatim |
| `tests/cockpit_v4/test_provider_schema_compatibility.py` | b95c27ba5f125ea1 | verbatim |
| `tests/cockpit_v4/test_provision_sequence.py` | 46b6abb1d4216cfc | verbatim |
| `tests/cockpit_v4/test_question_banks.py` | 68b388d1228eaaa6 | verbatim |
| `tests/cockpit_v4/test_release_binding.py` | 5978149f2b1acafd | verbatim |
| `tests/cockpit_v4/test_release_header.py` | 986e78560f2482cc | verbatim |
| `tests/cockpit_v4/test_release_history.py` | 784a6f3bdc2f0599 | verbatim |
| `tests/cockpit_v4/test_release_isolation.py` | d7e481fe8413f78b | verbatim |
| `tests/cockpit_v4/test_release_scale.py` | 554cfc10ab1faa08 | verbatim |
| `tests/cockpit_v4/test_result_only_publication.py` | b0bd553f00d35fde | verbatim |
| `tests/cockpit_v4/test_result_payload_size.py` | 4b571b2821c98c8d | verbatim |
| `tests/cockpit_v4/test_row_scope_shorthand.py` | 0bd311503c28b441 | verbatim |
| `tests/cockpit_v4/test_runtime_readiness.py` | 4219ffab50867155 | verbatim |
| `tests/cockpit_v4/test_saudi_demo_surface.py` | f1177a8361f729ad | verbatim |
| `tests/cockpit_v4/test_saudi_localization.py` | 308693aaee8f3ddb | verbatim |
| `tests/cockpit_v4/test_saudi_release_smoke.py` | 1c41e55d1c93c5be | verbatim |
| `tests/cockpit_v4/test_schema_browser.py` | 8fdfa17df4ac3482 | verbatim |
| `tests/cockpit_v4/test_seeded_case_file.py` | 3e6535edf55f0c34 | verbatim |
| `tests/cockpit_v4/test_server_rendered_output.py` | 82a37737a5f94bb5 | verbatim |
| `tests/cockpit_v4/test_state_machine_and_memory.py` | e57db5782dcaa66a | verbatim |
| `tests/cockpit_v4/test_store_transactions.py` | 653e1d593145d543 | verbatim |
| `tests/cockpit_v4/test_thread_transcript.py` | 6c49e36101d7295c | verbatim |
| `tests/cockpit_v4/test_tool_contract_agreement.py` | e16c188f551f58f8 | verbatim |
| `tests/cockpit_v4/test_value_resolution.py` | f2575663984c2014 | verbatim |
| `tests/cockpit_v4/test_vertical_slice.py` | 9a676ee233d99ffc | verbatim |
| `tests/cockpit_v4/test_visual_choice.py` | 84f932c7cb628e47 | verbatim |
| `tests/cockpit_v4/test_who_are_you_acceptance.py` | adc01598f6438b6c | verbatim |
| `tests/cockpit_v4/test_write_audit.py` | 15ca6aa9b5535e68 | verbatim |
| `tests/cockpit_v4/uat_question_bank.py` | 196736a7e2012334 | verbatim |
| `tests/cockpit_v4/uat_sql.py` | a3d4fc877a77e758 | verbatim |
