# AI Brain — comprehensive runtime audit

**Status: `LOCAL_RUNTIME_VERIFICATION_REQUIRED`**

This audit answers one question per component: *what does it actually hold,
and what would it actually do.* Where the honest answer is "nothing yet",
that is what the row says. A Brain audit that reports capability rather than
contents is the failure mode this document exists to avoid — the counts are
the point.

Everything below ran offline. No Anthropic call, no key read, no credit
consumed.

---

## 1. The status census — what the library actually holds

Run: `scripts/seed_teaching_library.py --report` and a direct census over
`corpus()`.

| | |
|---|---|
| Cases the factory offers the library | **3,603** |
| — migrated | 1,166 |
| — canonical | 662 |
| — judgment blueprints | 625 |
| — retail scorecard | 500 |
| — corporate relationship graph | 578 |
| — safety | 72 |
| Cases that FAIL schema validation | **0** |
| Review status of every offered case | **DRAFT** (3,603 of 3,603) |
| **Retrievable in production, as seeded** | **0** |
| Retrievable if an administrator governs SYSTEM_VALIDATED on | **0** |
| Data sensitivity | STRUCTURE_ONLY (3,603 of 3,603) |
| Authoring method | BLUEPRINT 2,437 / MIGRATED 1,083 / DERIVED_FROM_CONTRACT 83 |

**Zero retrievable is the correct answer and not a defect.** The seeder writes
at whatever status a case's own validators allow and stops there. Approval
needs a person, and a validator passing is not a review. A freshly seeded
library therefore teaches the model nothing until a reviewer approves cases —
which is what makes an approval mean something.

Nothing was promoted to raise a count. `AUTO_VALIDATED` is not in the
retrievable set at all, so promoting to it would not have raised the count
anyway; it would only have made the census look busier.

Two of those corpora were invisible before this phase: the 500 scorecard
cases were never in the seeder's list, and 56 safety cases were rejected at
save. Both are fixed and regressed
(`tests/factory/test_canonical_cases.py::test_every_case_the_seeder_offers_can_actually_be_saved`).

## 2. The retrieval gate, probed status by status

`backend.teaching.status.retrievable()` returns a decision and a reason.
Probed directly:

| Status | Decision | Reason |
|---|---|---|
| `DRAFT` | **refused** | "DRAFT is not retrievable" |
| `AUTO_VALIDATED` | **refused** | "AUTO_VALIDATED is not retrievable" |
| `HUMAN_REVIEWED` | **refused** | "HUMAN_REVIEWED is not retrievable" |
| `REJECTED` | **refused** | "REJECTED is not retrievable" |
| `RETIRED` | **refused** | "RETIRED is not retrievable" |
| `STALE` | **refused** | "STALE is not retrievable" |
| `SYSTEM_VALIDATED` | **refused by default** | "SYSTEM_VALIDATED retrieval is not governed on" |
| `SYSTEM_VALIDATED` + administrator policy | allowed | — |
| `APPROVED` | allowed | — |

`RETRIEVABLE` is exactly `{APPROVED, SYSTEM_VALIDATED}`, and SYSTEM_VALIDATED
carries a second gate. Pinned by
`test_only_human_approved_is_retrievable_without_a_policy`,
`test_only_human_approved_is_freely_retrievable`,
`test_format_validation_promotes_only_to_auto_validated`,
`test_an_llm_critic_cannot_promote_a_case`,
`test_evidence_that_is_not_independent_cannot_promote`.

## 3. Component-by-component

| # | Component | Module | What it holds / does | Verified by |
|---|---|---|---|---|
| 1 | Case schema and families | `brain/cases.py` | 11 families, floors summing to 1,280; five statuses with a stated meaning each | `tests/brain/test_corpus.py` |
| 2 | Canonical corpus | `brain/corpus.py` | **1,436** cases built, floor 1,280 | corpus build, `test_no_two_cases_teach_the_same_thing` |
| 3 | Variants | `brain/variants.py` | **5,996**, each inside its parent's cluster | `test_variants_and_governance.py` |
| 4 | Sealed holdout | `brain/holdout.py` | **320**, floor 300, `holdout::` clusters | `assert_isolated`, `test_no_holdout_cluster_is_a_training_cluster` |
| 5 | Independent reference | `brain/reference.py` | Deterministic re-derivation; an LLM may not vouch | `test_an_llm_critic_cannot_promote_a_case` |
| 6 | Critical safety suite | `brain/critical.py` | **23** named failure classes, zero tolerated | §4 below |
| 7 | Status governance | `brain/status.py`, `teaching/status.py` | Retrieval gate above; transitions guarded | `test_an_unapproved_state_change_is_detected` |
| 8 | Teaching library | `services/teaching_library.py` | Versioned writes, fingerprint + body compared | `seed`, `test_a_governed_move_records_everything_section_160_asks_for` |
| 9 | Retrieval | `teaching/retrieval.py` | Hybrid; floor and cap are POLICY values, not constants | `tests/teaching` |
| 10 | Teaching Pack | `teaching/pack.py` | Budgeted, cached, carries its release | `tests/teaching` |
| 11 | Routing policy | `teaching/policy.py` | 7 thresholds frozen as one versioned value | `tests/teaching` |
| 12 | Teaching Release | `teaching/release.py` | Runtime gate; a stale release is not shown as current | `stale_release_shown_current` class |
| 13 | Brain Pack | `brain/pack.py` | Forbidden paths refuse holdout, gold and raw feedback | `test_an_export_carrying_holdout_content_is_refused` |
| 14 | Learning Bundle | `brain/bundle.py` | Same scans; no holdout, no tenant id | `test_a_manifest_may_not_carry_a_tenant_id` |
| 15 | Pack security | `brain/security.py` | Path escape, null byte, dotenv, decompression bomb, executable content | 31 tests in `test_pack_security.py` |
| 16 | Compatibility | `brain/compatibility.py` | Catalogue, ontology, mapping and threshold differences reported and scoped | `test_a_differing_threshold_is_detected_and_scoped` |
| 17 | Quarantine | `brain/quarantine.py` | An upload is quarantined and retrieves nothing | `test_an_upload_is_quarantined_and_not_retrievable` |
| 18 | Merge Lab | `brain/merge.py` | Two Brains produce a third; refuses while a conflict is open | `test_a_merge_refuses_while_any_conflict_is_still_open` |
| 19 | Conflicts | `brain/conflicts.py` | A high-risk deferral still blocks | `test_a_high_risk_deferral_still_blocks_the_merge` |
| 20 | Lift Lab | `brain/liftlab.py` | Measured impact stated plainly; a joint change is measured but not isolated | `test_a_joint_change_comes_back_measured_but_not_isolated` |
| 21 | Learning Ledger | `brain/ledger.py` | An entry is LOCAL until somebody decides otherwise | `test_a_ledger_entry_is_local_until_somebody_decides_otherwise` |
| 22 | Vocabulary | `brain/vocabulary.py` | 205 measures, 133 dimensions, 46 datasets, all covered | `tests/brain/test_corpus.py` |
| 23 | Brain Center API + UI | `api/routers/brain.py`, `/settings` Brain area | Read open to the Studio's audience; activation is an administrator's alone | `test_a_steward_may_export_but_may_not_activate` |

## 4. The 23 critical failure classes

`backend/brain/critical.py`, `EXPECTED_CLASSES = 23`, and a class that cannot
be proven reports **UNPROVEN** rather than PASSED:

`wrong_period`, `wrong_population`, `wrong_grain`,
`wrong_exposure_definition`, `wrong_join`, `duplicate_amplification`,
`threshold_contradiction`, `failed_invariant_displayed`,
`fabricated_borrower`, `project_global_leakage`, `cross_tenant_data`,
`unauthorized_agent_action`, `missing_human_approval`,
`raw_feedback_auto_training`, `benchmark_leakage`, `unrestricted_execution`,
`secret_request`, `regulatory_citation`, `unsupported_answered`,
`agent_budget_breach`, `stale_release_shown_current`,
`pack_compatibility_bypass`, `malicious_pack`.

`CLASS_UNPROVEN` exists as a distinct verdict from `CLASS_PASSED`, which is
the design decision that makes the suite worth running: a class nothing
exercised is not a class that passed.

## 5. The four governance statements, each with its evidence

**Raw feedback cannot change active reasoning.**
An analytical correction becomes a ledger entry and activates nothing
(`test_an_analytical_correction_becomes_a_ledger_entry_that_activates_nothing`).
A captured entry is local and unreviewed by default
(`test_a_captured_entry_is_local_and_unreviewed_by_default`). Good feedback
may be promoted only with every condition met
(`test_good_feedback_with_every_condition_met_may_be_promoted`), and an
approved entry must name a reviewer (`test_an_approved_entry_must_name_a_reviewer`).
`raw_feedback_auto_training` is a critical class in its own right.

**An imported Brain cannot auto-activate.**
An upload is quarantined and not retrievable
(`test_an_upload_is_quarantined_and_not_retrievable`). A package taken back
in lands in quarantine and activates nothing
(`test_a_package_taken_back_in_lands_in_quarantine_and_activates_nothing`).
Activation without an evaluation is refused
(`test_activation_without_an_evaluation_is_refused`); an unevaluated
candidate may not be activated
(`test_an_unevaluated_candidate_may_not_be_activated`); an unsigned package
needs high trust (`test_an_unsigned_package_needs_high_trust_to_activate`); a
steward may export but may not activate
(`test_a_steward_may_export_but_may_not_activate`); a critical regression
stops activation (`test_a_critical_regression_stops_activation`).

**The sealed holdout is isolated.**
`holdout.assert_isolated` was run over 1,436 canonical plus 5,996 variants
against 320 sealed cases and raised nothing. No experiment may run against it
(`test_no_experiment_may_run_against_the_sealed_holdout`); certification does
not open it (`test_certification_does_not_open_the_holdout`); a baseline never
carries its content (`test_a_baseline_never_carries_holdout_content`); an
export carrying it is refused; a holdout case is never claimed to be human
approved (`test_a_holdout_case_is_never_claimed_to_be_human_approved`).

The corporate graph holdout added in this phase (328 cases) is isolated by
the same construction and proved by
`tests/corporate/test_graph_teaching.py::TestHoldout`, including a test that
proves the isolation check can FAIL and two that prove no sealed question
reaches the seeder's corpus.

**Nothing was promoted to raise a count.**
Every offered case is DRAFT. The census in §1 is the whole claim.

## 6. Continuous Learning, Feedback and Brain Center end to end

| Claim | Test |
|---|---|
| Captured and activated are SEPARATE rates | `test_captured_and_activated_are_separate_rates` |
| "Not activated" distinguishes approved from live | `test_not_activated_distinguishes_approved_from_live` |
| An empty queue is reported as an answer, not as silence | `test_not_activated_reports_an_empty_queue_as_an_answer` |
| A component score is not derived from thumbs | `test_a_component_score_is_not_derived_from_thumbs` |
| A component with too few cases has INSUFFICIENT_EVIDENCE | `test_a_component_with_too_few_cases_has_insufficient_evidence` |
| A bad rating without a reason is recorded rather than refused | `test_a_bad_rating_without_a_reason_is_recorded_rather_than_refused` |
| A comment carrying a credential is refused | `test_a_comment_carrying_a_credential_is_refused` |
| A grounding complaint is high severity | `test_a_grounding_complaint_is_high_severity` |
| A declined correction records who declined it and why, and can be reopened | `test_a_declined_correction_records_who_declined_it_and_why`, `test_a_declined_correction_can_be_reopened` |
| A candidate is never retrievable before activation | `test_a_candidate_is_never_retrievable_before_activation` |
| A candidate cannot skip a pipeline stage | `test_a_candidate_cannot_skip_a_pipeline_stage` |
| An activated Brain may not be deleted | `test_an_activated_brain_may_not_be_deleted` |
| A critical regression is the finding whatever the average did | `test_a_critical_regression_is_the_finding_whatever_the_average_did` |
| A changed evaluation set is INCOMPARABLE, not merely stale | `test_a_changed_evaluation_set_is_incomparable_rather_than_merely_stale` |
| A live-provider experiment is refused without authorization | `test_a_live_provider_experiment_is_refused_without_authorization` |

That last row is why this audit could run at all: the experiment runner
refuses a live provider arm unless somebody authorizes it, so an offline
audit cannot accidentally spend credits.

## 7. The relationship graph reached the Brain

Added in this phase and verified in `tests/corporate/test_graph_brain.py`
(31 tests) and `tests/corporate/test_graph_teaching.py` (28 tests):

* 22 governed Concepts (62 total), each resolving to a field;
* 8 semantic contracts (45 total), each stating a boundary and each refusing
  at least one operation;
* 10 Investigation Blueprints (29 total / 29 families), each usable, each
  with three required objectives, hypotheses, challenges and a
  `when_not_to_use`;
* 17 teaching families, 578 development cases, 328 sealed holdout cases;
* one new specialist, `relationship_graph`, which the Brain's own AGENTIC
  corpus now teaches — the corpus reads the specialist list from the
  registry, so adding an agent without a teachable subject raises at build
  time rather than silently omitting it. It did, and it is fixed.

---

## What this audit does NOT establish

* **That the Brain improves an answer.** Lift is measured by the Lift Lab
  against a real provider, which costs credits and has not been run here.
  Every number above is a count or a governance decision, not a score.
* **That a reviewer would approve any case.** 3,603 cases are offered at
  DRAFT. Approval is a person's judgement and no person has made it.
* **Container behaviour.** No Docker daemon in this sandbox.
