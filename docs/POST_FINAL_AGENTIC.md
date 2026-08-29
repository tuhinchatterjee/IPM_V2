# Agentic baseline

Generated 2026-08-29T13:19:56+0000 · 4.0s · 15 probes

**No provider call was made.** Every probe runs inside `assert_no_provider_calls`, which makes any attempt to reach a model raise. This is structural, not a promise.

## Headline metrics

| Metric | Value |
| --- | --- |
| Probes completed | 15 |
| Probes that raised | 0 |
| Officer selection accuracy % | 100.0 |
| …of which scored | 6 |
| Outcome accuracy % (answer/clarify/refuse) | 100.0 |
| Unnecessary specialists (total) | 0 |
| Missed specialists (total) | 0 |
| Mean specialists per request | 0.67 |
| Mean tasks per request | 0.67 |
| Mean model-call estimate per request | 0.0 |
| Mean latency (ms) | 190 |
| p95 latency (ms) | 837 |
| Requests that executed an analysis % | 33.3 |
| Invariants passed % (of executed) | 100.0 |
| Grounded % (where grounding ran) | — |
| Mean assurance coverage % | 93.4 |
| Records that received a score | 15 |
| Records UNVERIFIED | 0 |
| Records FAILED | 0 |
| Critical failures | 0 |
| Critical checks with no signal | 0 |
| Mandatory checks unresolved | 0 |

## Officer selection, per request

| # | Request | Flow | Officer | Expected | Specialists | Tasks | Datasets | Executed | Status | Coverage |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A | What ratings data do you have? | METADATA_DISCOVERY | 1 Credit Analyst | 1 | 0 | 0 | 0 | no | VALIDATED_WITH_LIMITATIONS | 93.8% |
| B | Show IFRS 9 EAD by sector for the latest qua | SIMPLE_ANALYSIS | 1 Credit Analyst | 1 | 0 | 0 | 1 | yes | VALIDATED_WITH_LIMITATIONS | 97.8% |
| C | Which customers had a rating downgrade and a | MULTI_DOMAIN_ANALYSIS | 2 Senior Credit Officer | 2 | 0 | 0 | 3 | yes | VALIDATED_WITH_LIMITATIONS | 92.0% |
| D | Something seems wrong with Contracting. Inve | AGENTIC_COORDINATED_REVIEW | 4 Chief Orchestrator | — | 5 | 5 | 4 | yes | VALIDATED_WITH_LIMITATIONS | 94.4% |
| E | Review the latest portfolio and tell me ever | AGENTIC_COORDINATED_REVIEW | 4 Chief Orchestrator | 4 | 5 | 5 | 4 | yes | VALIDATED_WITH_LIMITATIONS | 94.4% |
| F | Show me exposure. | CONVERSATIONAL_NO_ANALYSIS | 1 Credit Analyst | 1 | 0 | 0 | 0 | no | VALIDATED_WITH_LIMITATIONS | 93.3% |
| G | Which borrowers had their CEO resign? | CONVERSATIONAL_NO_ANALYSIS | 1 Credit Analyst | 1 | 0 | 0 | 0 | no | VALIDATED_WITH_LIMITATIONS | 93.3% |
| H1 | Show IFRS 9 ECL by sector for the last four  | SIMPLE_ANALYSIS | 1 Credit Analyst | — | 0 | 0 | 1 | yes | VALIDATED_WITH_LIMITATIONS | 97.8% |
| H2 | Does this trend make sense? | CONVERSATIONAL_NO_ANALYSIS | 1 Credit Analyst | — | 0 | 0 | 0 | no | VALIDATED_WITH_LIMITATIONS | 84.2% |
| PA | Review unresolved risks in this Project. | CONVERSATIONAL_NO_ANALYSIS | 1 Credit Analyst | — | 0 | 0 | 0 | no | VALIDATED_WITH_LIMITATIONS | 93.3% |
| PB | Refresh the saved Analyses with the latest p | CONVERSATIONAL_NO_ANALYSIS | 1 Credit Analyst | — | 0 | 0 | 0 | no | VALIDATED_WITH_LIMITATIONS | 93.3% |
| PC | Create Investigations for the three most mat | CONVERSATIONAL_NO_ANALYSIS | 1 Credit Analyst | — | 0 | 0 | 0 | no | VALIDATED_WITH_LIMITATIONS | 93.3% |
| PD | Which Project conclusions changed since the  | CONVERSATIONAL_NO_ANALYSIS | 1 Credit Analyst | — | 0 | 0 | 0 | no | VALIDATED_WITH_LIMITATIONS | 93.3% |
| PE | Send the updated Project to Portfolio Risk f | CONVERSATIONAL_NO_ANALYSIS | 1 Credit Analyst | — | 0 | 0 | 0 | no | VALIDATED_WITH_LIMITATIONS | 93.3% |
| PF | Publish this Investigation globally. | CONVERSATIONAL_NO_ANALYSIS | 2 Senior Credit Officer | — | 0 | 0 | 0 | no | VALIDATED_WITH_LIMITATIONS | 93.3% |

## Is the officer badge real? (§3)

Verdict: **MATERIAL** — 2 material, 0 decorative, monotonic: True

| Lower | Higher | Verdict | What actually differed |
| --- | --- | --- | --- |
| L1 A — metadata | L2 C — multi-domain | MATERIAL | tool_call_count, dataset_count |
| L2 C — multi-domain | L4 D — segment investigation | MATERIAL | orchestrated, agent_count, task_count, tool_call_count, dataset_count, coordinated, governed_work |

## Assurance coverage map (§19)

95 of 95 subcomponents mapped · 72 wired (75.8%) · 18 planned · 5 out of band

Critical: 17 of 17 wired (100.0%)

| Dimension | Subcomponents | Wired | Planned | Out of band | Critical wired |
| --- | --- | --- | --- | --- | --- |
| Understanding & context | 12 | 11 | 1 | 0 | 0/0 |
| Analytical design | 15 | 14 | 1 | 0 | 3/3 |
| Computation & evidence | 18 | 18 | 0 | 0 | 10/10 |
| Judgment & presentation | 18 | 13 | 5 | 0 | 2/2 |
| Agentic delivery | 16 | 8 | 8 | 0 | 1/1 |
| Reliability & experience | 16 | 8 | 3 | 5 | 1/1 |

## Coverage by flow class (§21)

| Flow | Probes | Applicable | Critical applicable | Mean coverage | Statuses | Scored |
| --- | --- | --- | --- | --- | --- | --- |
| Agentic coordinated review | 2 | 76 | 17 | 94.4% | VALIDATED_WITH_LIMITATIONS | 2 |
| Conversational (no analysis ran) | 9 | 25 | 4 | 92.3% | VALIDATED_WITH_LIMITATIONS | 9 |
| Metadata / discovery | 1 | 22 | 4 | 93.8% | VALIDATED_WITH_LIMITATIONS | 1 |
| Multi-domain analysis | 1 | 61 | 16 | 92.0% | VALIDATED_WITH_LIMITATIONS | 1 |
| Simple analysis | 2 | 55 | 15 | 97.8% | VALIDATED_WITH_LIMITATIONS | 2 |

---

Every number above is measured from what the run persisted. Nothing is inferred from the question's wording.
