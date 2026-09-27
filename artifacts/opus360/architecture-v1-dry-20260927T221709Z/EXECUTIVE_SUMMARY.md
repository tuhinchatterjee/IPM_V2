# Executive summary — architecture-v1-dry-20260927T221709Z

> **DRY RUN — SCRIPTED ANALYST, NOT OPUS. Every figure below measures the HARNESS and the frozen deterministic pipeline driven by a scripted model. None of it is evidence about Opus.**

Frozen commit `245c50e45786c6e0c866b281f9dd74da17d160b5` · model `claude-opus-5` · protected core: **PROTECTED_CORE_UNCHANGED** · generated 2026-09-27T22:20:51+00:00

| Metric | Result |
|---|---:|
| Core user turns (planned) | 250 |
| Completed | 250 |
| Correct (all checks passed) | 250 (100.0%) |
| Exact oracle pass | 100.0% |
| Analytical oracle pass | 100.0% |
| Behavioural oracle pass | 100.0% |
| Supported claims | 100.0% |
| First-pass execute | 100.0% |
| Repair rate | 0.0% |
| Paraphrase invariance | 100.0% |
| Thread continuity (turns 2-5) | 100.0% |
| Domain leakage | 0.0% |
| Input tokens | 552,000 |
| Output tokens | 138,000 |
| Total tokens | 690,000 |
| Experiment cost (core + support) | $7.8155 |
| Median latency | 0.2 s |
| P95 latency | 0.4 s |
| Critical architecture findings | 0 |
| High architecture findings | 0 |
| Model-specific findings | 0 |
| Provider/transient findings | 0 |

## Top 10 things working well

1. **A_BASELINE**: 50 turns, pass rate 100.0%, median 0.1 s.
2. **B_PARAPHRASE**: 50 turns, pass rate 100.0%, median 0.2 s.
3. **C_COMPLEX**: 40 turns, pass rate 100.0%, median 0.3 s.
4. **D_THREAD**: 50 turns, pass rate 100.0%, median 0.1 s.
5. **E_CLARIFICATION**: 20 turns, pass rate 100.0%, median 0.1 s.
6. **Token reconciliation (ledger vs provider-native)**: 100.0%.
7. **Supported-claim rate**: 100.0%.
8. **First-pass execute rate**: 100.0%.
9. **Clarification detection on genuinely ambiguous questions**: 100.0%.
10. **Absence of domain leakage**: 100.0%.

## Top 10 problems

No failing turns.

## Top 10 token / latency observations

1. Input-token composition (ESTIMATED, byte share of native totals): system_instruction 36%, system_static_knowledge 26%, tool_schema 17%.
2. Static context tax (system + tool schema ÷ input): median 95%, p95 100%.
3. History tax: median 0%, max 3%.
4. Tool-result tax: median 3%, p95 5%.
5. Most expensive class: A_BASELINE (mean 3,000 tokens/turn).
6. Slowest class: C_COMPLEX (median 0.3 s).
7. Repair tokens: 0.0 across all turns; tokens after a correct artifact existed: 0.0.
8. Provider (model + token counting) share of processing time: 5%; local deterministic share: 95%.
9. 460 count_tokens round trips accompanied 460 paid generations (1.00 per generation).
10. Thread input-token growth per turn: median 0 tokens.

## Architecture vs Opus

- Architecture-attributed failing turns: 0 ({}).
- Model-attributed failing turns: 0 ({}).
- Provider/transient: 0.
- Other (oracle/data/harness): 0.
- Attribution rules are mechanical (cert/evaluate.py `root_cause`); every row in failure_analysis.csv carries the evidence line that decided it.

## What to investigate before freeze


Static, code-verified findings (independent of any run) are listed in ARCHITECTURE_FINDINGS.md (S-01 … S-10) with their live signal counts.

---

**This is a dry run.** To run the live Opus certification, see the command in `docs/opus360/RUNBOOK.md` (it requires `OPUS360_MAX_USD` and the Cockpit credential).
