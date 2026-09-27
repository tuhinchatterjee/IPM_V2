# Freeze readiness inputs — architecture-v1-dry-20260927T222449Z

> **DRY RUN — SCRIPTED ANALYST, NOT OPUS. Every figure below measures the HARNESS and the frozen deterministic pipeline driven by a scripted model. None of it is evidence about Opus.**

This document gives the evidence for a freeze decision. It does not make the decision.

Protected core: **PROTECTED_CORE_UNCHANGED**.

## Numerical correctness

- Exact-oracle pass rate: 100.0%; analytical: 100.0%.
- Required figures published correctly: 1479/1479; computed but not published: 0.
- Turns with a numerical error: 0.
- Wrong period: 0.
- Wrong population: 0.

## Analytical robustness (wording)

- INVARIANT: 25 group(s) PG-C01, PG-C02, PG-C03, PG-C04, PG-C05, PG-C06, PG-C07, PG-C08, PG-C09, PG-C10, PG-C11, PG-C12, PG-C13, PG-R01, PG-R02, PG-R03, PG-R04, PG-R05, PG-R06, PG-R07, PG-R08, PG-R09, PG-R10, PG-R11, PG-R12
- PRESENTATION_ONLY_VARIATION: 0 group(s) 
- MATERIAL_ANALYTICAL_VARIATION: 0 group(s) 
- FAIL: 0 group(s) 

## Conversation robustness

- Thread continuity (turns 2-5): 100.0%.
- Domain leakage: 0.
- Stale context (wrong period/population on a follow-up): 0 turn(s).
- Route refusal on a domain switch inside a pinned thread: 2: D-TD05-2, D-TD09-2.

## Governance

- Behavioural pass rate (clarify/refuse/answer correctly): 100.0%.
- Numbers stated outside the governed universe: 0.
- Genuine ambiguity detected: 100.0%; avoidable clarifications: 0.
- Unhedged causal language (HEURISTIC): 0.

## Validation

- Validator rejections: 0 across 0 turns.
- Rejections that replay to a correct answer (validator refused good work): 0.
- Finalizer rejections: 0.

## Repair

- Repair rate: 0.0%; repair success: n/a; mean repairs per executing turn: 0.0; repair tokens: 0.0.

## Efficiency

- Input-token composition (ESTIMATED, byte share of native totals): system_instruction 36%, system_static_knowledge 26%, tool_schema 17%.
- Static context tax (system + tool schema ÷ input): median 95%, p95 100%.
- History tax: median 0%, max 3%.
- Tool-result tax: median 3%, p95 5%.
- Most expensive class: A_BASELINE (mean 3,000 tokens/turn).
- Slowest class: C_COMPLEX (median 0.3 s).
- Repair tokens: 0.0 across all turns; tokens after a correct artifact existed: 0.0.
- Provider (model + token counting) share of processing time: 5%; local deterministic share: 95%.
- 460 count_tokens round trips accompanied 460 paid generations (1.00 per generation).
- Thread input-token growth per turn: median 0 tokens.
- Largest single turn: A-C01 with 3,000 tokens (static context 96% of input).

## Stability

- RG-01: all pass True, SQL identical True, token CV 0.0, latency CV 0.0576
- RG-02: all pass True, SQL identical True, token CV 0.0, latency CV 0.0949
- RG-03: all pass True, SQL identical True, token CV 0.0, latency CV 0.0611
- RG-04: all pass True, SQL identical True, token CV 0.0, latency CV 0.1366
- RG-05: all pass True, SQL identical True, token CV 0.0, latency CV 0.0384
- RG-06: all pass True, SQL identical True, token CV 0.0, latency CV 0.1383
- RG-07: all pass True, SQL identical True, token CV 0.0, latency CV 0.0956
- RG-08: all pass True, SQL identical True, token CV 0.0, latency CV 0.0702
- RG-09: all pass True, SQL identical True, token CV 0.0, latency CV 0.1469
- RG-10: all pass True, SQL identical True, token CV 0.0, latency CV 0.0636

## Corporate versus Retail

- corporate: 133 turns, pass 100.0%, leaks 0
- retail: 117 turns, pass 100.0%, leaks 0

## Operational reliability

- Provider/transient failures: 0; harness transient retries: 0; hidden SDK HTTP retries: 0; rate-limit events: 0.
- Deadline failures: 0.
- Budget terminations: 0.

## Architecture defects (by severity)

{}

## Model-specific defects (by severity)

{}

## Freeze decision inputs

- Critical architecture findings: 0
- High architecture findings: 0
- Static findings open: S-01 (HIGH), S-02 (MEDIUM), S-03 (MEDIUM), S-04 (MEDIUM), S-05 (LOW), S-06 (LOW), S-07 (LOW), S-08 (LOW), S-09 (LOW), S-10 (LOW)
- Failing turns: 0 of 250 completed.
- The decision is the reader's.
