# Architecture findings — architecture-v1-dry-20260927T215941Z

> **DRY RUN — SCRIPTED ANALYST, NOT OPUS. Every figure below measures the HARNESS and the frozen deterministic pipeline driven by a scripted model. None of it is evidence about Opus.**

No change has been made to the frozen AdvancedCockpit. Every item below is a recommendation to INVESTIGATE; nothing has been implemented.

## Static, code-verified findings (independent of any run)

| ID | Severity | Layer | Finding | Evidence | Live signal (this experiment) |
|---|---|---|---|---|---|
| S-01 | HIGH | ARCH_CONTRACT | finalize_response disposition enum disagrees with the parser | contracts/finalize_response.schema.json offers ['answer','partial','referral','clarification','unsupported'] to the model; contracts.py:56-58 DISPOSITIONS accepts 'partial_answer' and 'safe_failure' and rejects 'partial' (contracts.py:1019-1024). A schema-compliant PARTIAL answer is refused and costs an answer correction; 'partial_answer' is never offered. | [] |
| S-02 | MEDIUM | ARCH_CONTRACT | answer-reserve prompt instructs an invalid disposition | orchestration.py:618 tells the model to use `cannot_answer`, which is in neither the tool schema nor DISPOSITIONS. | 0 |
| S-03 | MEDIUM | ARCH_BUDGET | SDK retries are not disabled; up to 3 HTTP attempts per paid call are invisible to the ledger | backend/llm/anthropic_provider.py:327-328 builds anthropic.Anthropic(api_key, timeout) without max_retries; anthropic 0.112.0 DEFAULT_MAX_RETRIES == 2 (verified). allow_retry=False only disables the adapter loop. | 0 |
| S-04 | MEDIUM | ARCH_BUDGET | each generation spends 3+ provider attempts against a 24-attempt limit | provider.py:232 (count_input), :332 (_converse.send) and :497 (ask) each call ledger.spend_provider_attempt(); about 8 generations exhaust provider_attempts=24 before generation_attempts=12. | [] |
| S-05 | LOW | ARCH_ORCHESTRATION | operator records redact every *token* count | run_store.redact() (run_store.py:1610) replaces any key containing 'token', so model.response_received details and the call_report store '[redacted]' for token usage. Only reservations.usage keeps native counts. | 1168 |
| S-06 | LOW | ARCH_ORCHESTRATION | served model id is never read | anthropic_provider.py:298 returns model=chosen (the requested id); message.model is discarded, so the product cannot evidence which model served a call. | [] |
| S-07 | LOW | ARCH_ORCHESTRATION | assistant turns persisted as Python repr strings | run_store.save_messages json.dumps(default=str) on SDK block objects (run_store.py:918). | 0 |
| S-08 | LOW | TEST_HYGIENE | the frozen regression suite rewrites tracked evidence files | Running tests/cockpit_v4 modifies docs/cockpit_v4/evidence/{dual_domain_performance,math_query_engine,overnight_analytical_benchmark,performance,saudi_release_fingerprint}.json (restored by the harness). | see regression/load evidence |
| S-09 | LOW | ARCH_ORCHESTRATION | one worker thread per process; per-principal limit of 2 active runs | app.py:176-186 starts a single Worker.serve_forever thread; routes.py:328-335 returns 429 when a principal has 2 active runs. Concurrency beyond 1 queues; beyond 2 is refused at admission. | see regression/load evidence |
| S-10 | LOW | TEST_HYGIENE | Round H live-UAT capture read event fields that do not exist | scripts/cockpit_v4/live_uat.py:587-589 reads e.created_at / e.body; Event has occurred_at / detail_ref, so the Round H evidence file's event bodies were empty. | see regression/load evidence |

## Failure clusters from this experiment

No failing turns.
