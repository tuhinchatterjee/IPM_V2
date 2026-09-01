# Agentic baseline — before hardening

Generated 2026-08-29T08:44:25+0000 · 3.5s · 15 probes

**No provider call was made.** Every probe runs inside `assert_no_provider_calls`, which makes any attempt to reach a model raise. This is structural, not a promise.

## Headline metrics

| Metric | Value |
| --- | --- |
| Probes completed | 15 |
| Probes that raised | 0 |
| Officer selection accuracy % | 83.3 |
| …of which scored | 6 |
| Outcome accuracy % (answer/clarify/refuse) | 100.0 |
| Unnecessary specialists (total) | 0 |
| Missed specialists (total) | 0 |
| Mean specialists per request | 0.0 |
| Mean tasks per request | 0.0 |
| Mean model-call estimate per request | 0.0 |
| Mean latency (ms) | 158 |
| p95 latency (ms) | 522 |
| Requests that executed an analysis % | 20.0 |
| Invariants passed % (of executed) | 0.0 |
| Grounded % (where grounding ran) | — |
| Mean assurance coverage % | 9.5 |
| Records that received a score | 0 |
| Records UNVERIFIED | 15 |
| Records FAILED | 0 |
| Critical failures | 0 |
| Critical checks with no signal | 0 |
| Mandatory checks unresolved | 356 |

## Officer selection, per request

| # | Request | Flow | Officer | Expected | Specialists | Tasks | Datasets | Executed | Status | Coverage |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A | What ratings data do you have? | CONVERSATIONAL_NO_ANALYSIS | 1 Credit Analyst | 1 | 0 | 0 | 0 | no | UNVERIFIED | 8.4% |
| B | Show IFRS 9 EAD by sector for the latest qua | SIMPLE_ANALYSIS | 1 Credit Analyst | 1 | 0 | 0 | 1 | yes | UNVERIFIED | 12.6% |
| C | Which customers had a rating downgrade and a | MULTI_DOMAIN_ANALYSIS | 3 Portfolio Risk Lead | 2 | 0 | 0 | 3 | yes | UNVERIFIED | 11.6% |
| D | Something seems wrong with Contracting. Inve | CONVERSATIONAL_NO_ANALYSIS | 3 Portfolio Risk Lead | — | 0 | 0 | 0 | no | UNVERIFIED | 8.4% |
| E | Review the latest portfolio and tell me ever | CONVERSATIONAL_NO_ANALYSIS | 4 Chief Orchestrator | 4 | 0 | 0 | 0 | no | UNVERIFIED | 8.4% |
| F | Show me exposure. | CONVERSATIONAL_NO_ANALYSIS | 1 Credit Analyst | 1 | 0 | 0 | 0 | no | UNVERIFIED | 10.5% |
| G | Which borrowers had their CEO resign? | CONVERSATIONAL_NO_ANALYSIS | 1 Credit Analyst | 1 | 0 | 0 | 0 | no | UNVERIFIED | 7.4% |
| H1 | Show IFRS 9 ECL by sector for the last four  | SIMPLE_ANALYSIS | 1 Credit Analyst | — | 0 | 0 | 1 | yes | UNVERIFIED | 12.6% |
| H2 | Does this trend make sense? | CONVERSATIONAL_NO_ANALYSIS | 1 Credit Analyst | — | 0 | 0 | 0 | no | UNVERIFIED | 8.4% |
| PA | Review unresolved risks in this Project. | CONVERSATIONAL_NO_ANALYSIS | 1 Credit Analyst | — | 0 | 0 | 0 | no | UNVERIFIED | 10.5% |
| PB | Refresh the saved Analyses with the latest p | CONVERSATIONAL_NO_ANALYSIS | 1 Credit Analyst | — | 0 | 0 | 0 | no | UNVERIFIED | 7.4% |
| PC | Create Investigations for the three most mat | CONVERSATIONAL_NO_ANALYSIS | 1 Credit Analyst | — | 0 | 0 | 0 | no | UNVERIFIED | 7.4% |
| PD | Which Project conclusions changed since the  | CONVERSATIONAL_NO_ANALYSIS | 1 Credit Analyst | — | 0 | 0 | 0 | no | UNVERIFIED | 10.5% |
| PE | Send the updated Project to Portfolio Risk f | CONVERSATIONAL_NO_ANALYSIS | 1 Credit Analyst | — | 0 | 0 | 0 | no | UNVERIFIED | 10.5% |
| PF | Publish this Investigation globally. | CONVERSATIONAL_NO_ANALYSIS | 2 Senior Credit Officer | — | 0 | 0 | 0 | no | UNVERIFIED | 7.4% |

## Is the officer badge real? (§3)

Verdict: **MATERIAL** — 2 material, 0 decorative, monotonic: False

| Lower | Higher | Verdict | What actually differed |
| --- | --- | --- | --- |
| L1 A — metadata | L3 C — multi-domain | MATERIAL | tool_call_count, dataset_count, plan_steps |
| L3 C — multi-domain | L4 E — portfolio review | MATERIAL | tool_call_count, dataset_count, plan_steps |

## Assurance coverage map (§19)

95 of 95 subcomponents mapped · 68 wired (71.6%) · 22 planned · 5 out of band

Critical: 17 of 17 wired (100.0%)

| Dimension | Subcomponents | Wired | Planned | Out of band | Critical wired |
| --- | --- | --- | --- | --- | --- |
| Understanding & context | 12 | 11 | 1 | 0 | 0/0 |
| Analytical design | 15 | 13 | 2 | 0 | 3/3 |
| Computation & evidence | 18 | 18 | 0 | 0 | 10/10 |
| Judgment & presentation | 18 | 10 | 8 | 0 | 2/2 |
| Agentic delivery | 16 | 8 | 8 | 0 | 1/1 |
| Reliability & experience | 16 | 8 | 3 | 5 | 1/1 |

## Coverage by flow class (§21)

| Flow | Probes | Applicable | Critical applicable | Mean coverage | Statuses | Scored |
| --- | --- | --- | --- | --- | --- | --- |
| Conversational (no analysis ran) | 12 | 25 | 4 | 8.8% | UNVERIFIED | 0 |
| Multi-domain analysis | 1 | 61 | 16 | 11.6% | UNVERIFIED | 0 |
| Simple analysis | 2 | 55 | 15 | 12.6% | UNVERIFIED | 0 |

---

Every number above is measured from what the run persisted. Nothing is inferred from the question's wording.
