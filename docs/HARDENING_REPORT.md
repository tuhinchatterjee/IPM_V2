# Agentic hardening, assurance and full-system proof — final report

**Starting commit** `a89bbfc` · **Final commit** `dc34e69` · local and remote
identical · branch `claude/vigilant-darwin-eohyi1` · Alembic head `0021`
(unchanged: no migration was needed).

**No live Anthropic call ran. No credits were consumed. The API key was
never requested, read or inspected.** Every probe executes inside
`assert_no_provider_calls`, which replaces the provider's entry points with
something that raises — and a test asserts that guard still raises, because
if it ever stops, every "no provider was called" claim here becomes
unfounded.

---

## 1-3. Commits and match

Five checkpoints, each pushed:

| Commit | What |
|---|---|
| `c5a881f` | The baseline, flow classes, `NOT_AVAILABLE`, the Coverage Map — and ten defects the baseline found |
| `204331b` | Wiring the assurance collector; four shipped defects the wiring exposed |
| `451d9fa` | Making the officer badge real; five more defects |
| `f8b38d4` | Governed case statuses, the review pack, the safety suite |
| `dc34e69` | Feature Proof Matrix, browser acceptance, test isolation |

## 4-5. Baseline and post-tuning reports

* `docs/BASELINE_AGENTIC.md` + `docs/baseline_agentic.json` — measured at
  `a89bbfc`, before any change, and **never regenerated**.
* `docs/POST_TUNING_AGENTIC.md` + `docs/post_tuning_agentic.json`.
* `docs/DEFECTS_HARDENING.md` — 22 defects, each with what was observed.

## 6-7. Cockpit and Project agentic proof

The baseline's central finding: **the portfolio review selected a Chief
Orchestrator and then ran no orchestrator, no specialist and no task.** All
fifteen probes reported `specialists = 0`, `tasks = 0`, `orchestrated =
false`.

After: threads D and E (segment investigation, portfolio review) run **5
specialists over 5 tasks and 6 governed probes**, classified
`AGENTIC_COORDINATED_REVIEW`. A metadata question still summons nobody — the
other half of the same rule.

Root cause (D13): `_reading_of` read the broad-investigation summary from
`orchestrated.investigation`, which is empty on the path the Cockpit takes.
The summary lives on the executed step under `detail.investigation`. Every
broad investigation therefore arrived at officer selection with no concepts,
`agents_for()` returned nothing, and coordination could never fire.

Project parity is asserted directly: the same question inside a Project must
produce the same orchestration, the same specialist count and the same
officer level. It does.

## 8-15. Selection and analytical accuracy

| Metric | Baseline | After |
|---|---|---|
| Officer selection accuracy | 83.3% (5/6) | 83.3% (5/6) |
| Outcome accuracy (answer/clarify/refuse) | 100% | 100% |
| Mean specialists per request | 0.00 | 0.67 |
| Mean tasks per request | 0.00 | 0.67 |
| Unnecessary specialists | 0 | 0 |
| Missed specialists | 0 | 0 |
| Mean latency | 158 ms | 184 ms |
| p95 latency | 522 ms | 796 ms |

Officer accuracy is unchanged and **not** 100%: thread C ("rating downgrade
and ECL increase") selects level 3 where §28 expects level 2 (D6, OPEN). Two
domains at borrower grain is a comparison, not a portfolio review.

The latency rise is the coordination that was not happening before. It buys
five specialists.

Dataset, relationship, period and grain accuracy are not reported as
percentages: with three probes executing an analysis, a percentage over
three cases would be a number with no evidence behind it. Each is instead a
wired assurance check that PASSed on every executed probe.

## 16-18. Proactive review, Risk Cases, Requires Attention

Not proven in this phase. `proactive_review`, `attention_case_creation` and
`case_deduplication` are `NOT_AVAILABLE` in the assurance record — the
signals are not wired, and the Coverage Map names the system that owes each
one. Reported as gaps rather than as passes.

## 19-22. Isolation, workflow, loops, injection

25 safety tests. Raw SQL does not compile; no secret appears in any payload;
the sealed holdout is not reachable from a question; an invented measure does
not resolve; no approval was granted without a named approver; no workflow
executed; a recursive request terminates. Every attempt leaves an auditable
Trace and an assurance record.

D22, found on the suite's first run: `unsupported` — the status a governed
refusal produces — was missing from the contracted-outcome set, so the safest
possible behaviour scored as an error-handling failure.

## 23-25. Assurance coverage

| | Baseline | After |
|---|---|---|
| Mean assurance coverage | **9.5%** | **93.3%** |
| Mandatory checks unresolved (15 probes) | **356** | **0** |
| Critical checks with no signal | 0 | **0** |
| Records that received a score | **0** | **15** |
| Records UNVERIFIED | 15 | 0 |

Coverage Map: **72 of 95 subcomponents wired (75.8%)**, **17 of 17 critical
(100%)**, 18 planned, 5 out-of-band. A test asserts `coverage.wired() ==
set(READERS)` in both directions — the map cannot claim a signal no reader
reads, and no reader may exist that nobody mapped.

The 23 that are not wired report `NOT_AVAILABLE` naming the system that owes
the signal, never `PASS` and never `SKIPPED`.

## 26. Assurance UI

Unchanged from Part F and verified by browser: no screen labels a figure
"accuracy", none shows a fake percent-complete, all 33 screen-viewport
combinations render an assurance figure through the one constant that names
it.

## 27-29. Teaching cases, review pack, retrieval eligibility

**2,453 cases. 0 approved. 0 retrievable by production.** Unchanged, and
that is the honest state.

§16's statuses added: `HUMAN_REVIEWED` (read and assessed, NOT signed for,
NOT retrievable) and the aliases `HUMAN_APPROVED` / 
`SYSTEM_REFERENCE_VALIDATED`. Default production retrieval is
`HUMAN_APPROVED`; `SYSTEM_REFERENCE_VALIDATED` needs an explicit
administrator policy; `AUTO_VALIDATED` — which is all 2,453 — is never
retrievable.

The review pack (`GET /api/v1/intelligence/review-pack`) is labelled REVIEW
REQUIRED on every row, and approves nothing.

**D21, which the pack found:** it covers **6 of 15** risk classes. Permission
and tenant safety, prompt injection, officer selection, agent selection,
proactive review, Risk Cases and workflow approval have **zero** cases. The
library teaches analytical questions and nothing about the classes where a
wrong answer is least recoverable.

## 30-32. Corpora and holdout

Development corpus: 2,453 cases, unchanged — no case was generated in this
phase. Generating more AUTO_VALIDATED cases would raise a count and change
nothing, since none would be retrievable or read.

Sealed holdout: unchanged and untouched. **No holdout expectation was
corrected**, because none was consulted: the isolation test still asserts the
backend cannot import `intelligence_factory`.

## 33-35. Evaluation results and cost

Tier 1 (critical): no critical failure on any probe; no critical
`NOT_AVAILABLE`; no permission, tenant or Project leak; no unauthorised
action; no uncontrolled loop.

One Tier 1-class defect is OPEN and **contained** (D15): a portfolio-level
question returns account-grain rows and fails the `ordering` invariant. The
gate WITHHELD it — the turn ends `failed` rather than displaying a wrong
answer. The governed pipeline behaved as designed; grain selection did not.

Model-call estimate: 0.00 both before and after — the deterministic path
makes none, which is why the latency figures are milliseconds and not
seconds. **These numbers do not predict live-model latency or cost.**

## 36. Feature Proof Matrix

45 features, 13 areas: 26 PROVEN, 14 BACKEND_ONLY, 3 LIMITED, 2 DEFERRED.
36 have been seen by a browser. Two have no test and say so: the Project Plan
(§8 — not built) and Arabic/RTL (out of scope). Nine carry named limitations
tied to defect ids.

## 37. Browser acceptance

**231/231 checks passed** — 11 screens × 3 viewports (1440×900, 1366×768,
tablet) × 7 checks, against a production build and a live backend. It
genuinely ran; the script exits 2 with a message rather than reporting
success if Chromium cannot launch.

## 38. Docker

`docker compose config -q` valid. **The daemon is unavailable in this
sandbox, so build, start and health were NOT run and are not claimed.**
Exact Windows commands in `docs/AGENTIC_LIVE_VERIFICATION.md`.

## 39-43. Test counts

| Suite | Count |
|---|---|
| Backend total | **3,850** (0 failures, 16 skipped) |
| Front end | **254** |
| Assurance | 152 |
| Agentic | 270 |
| Proof (new this phase) | 98 |
| Independent-reference | **0** — none exists; see §46 |

## 44. Live-verification commands

`docs/AGENTIC_LIVE_VERIFICATION.md`. Start with `-DryRun`, which spends
nothing and reports what each mode would cost.

## 45. Unresolved limitations

| Id | What | Why not fixed here |
|---|---|---|
| D6 | Officer level 3 where 2 is expected on the two-domain case | A routing-threshold change needs its own before/after |
| D15 | Portfolio question returns account-grain rows | Contained by the gate. A planner change made under time pressure to clear a test is how the next defect ships |
| D17 | Table columns not in governed rank order | Cosmetic; reported |
| D19 | A coordinated review does not aggregate what its specialists read | Its Trace cannot say which data it touched. Held open by a test that breaks when it is closed |
| D20 | A coordinated review registers no evidence facts | Same shape as D12, in a different place |
| D21 | 9 of 15 review-pack risk classes have no cases | Needs cases written against real behaviour and read by a person |
| — | Proactive review, Risk Cases, worker health | `NOT_AVAILABLE`: signals not wired |
| — | Project Plan (§8) | Not built. Recorded as not delivered |
| — | Arabic / RTL | Out of scope |

## 46. Is 99.99% accepted-answer precision demonstrated?

**No. It is not demonstrated, and it is not statistically demonstrable from
anything in this repository.**

Three independent reasons:

1. **There is no independent reference to measure against.** Every number in
   this phase is OPERATIONAL ASSURANCE — what the runtime could prove about
   its own process. Zero independent-reference tests exist. Accuracy is a
   different claim and nothing here supports it.
2. **The sample cannot carry the claim.** 15 probes. Demonstrating 99.99%
   at any useful confidence needs tens of thousands of independently
   adjudicated cases. With 15, the honest upper bound is far below it.
3. **No case has been reviewed by a person.** All 2,453 are
   `AUTO_VALIDATED`; a machine agreeing with itself is not evidence.

What *is* demonstrated: on 15 probes, with 93.3% mean assurance coverage,
zero critical failures, zero critical checks without a signal, and zero
mandatory checks unresolved. That is a statement about process, on a small
sample, and it should be quoted as one.

## 47. No live calls, no credits

**Confirmed.** No provider call was made. `assert_no_provider_calls` wraps
every probe and raises on any attempt; a test asserts the guard still works
and restores the provider afterwards. The API key was never requested, read,
printed or logged. The live smoke test and sealed certification remain
deferred precisely because they spend real money.
