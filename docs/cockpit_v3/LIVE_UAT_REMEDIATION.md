# Cockpit Agentic V3 — the three live-UAT defects, and what was done

**Status:** the three defects reported from the local live-provider UAT run are
fixed, with tests. Live answer quality remains **BLOCKED / UNVERIFIED**: the
84-question bank has not been run against the configured Sonnet and Opus, and
nothing in this document is evidence about how a real model answers.

The provider itself was working in that run — real requests returned HTTP 200.
What follows are three implementation defects it exposed.

---

## Defect 1 — the gate was sent the whole dictionary

### What happened

The question **"Who are you?"** was stopped before it was sent:

| | |
|---|---:|
| Input tokens assembled | 60,530 |
| Output allowance the same call needs | 4,096 |
| Total | **64,626** |
| Standard per-call ceiling | 64,000 |

The request was refused, correctly, by the pre-dispatch counter. The user saw
nothing useful. To find out whether a question was about the portfolio at all,
the application had assembled 751 field definitions, 40 ratio formulas, the
join graph, the per-field coverage table, the sample rows and the SQL execution
contract.

### The root cause, and a second one underneath it

The first is structural: there was one packet, built before the gate, and it
carried everything any turn of the request could need.

The second is arithmetic, and it is why nothing caught it. The local token
estimator ran at 3.4 characters per token. Measured against the provider's own
counter on that request it is **2.32** — the estimator read 41,261 for a
request that counted 60,530, a 47% under-count. The reduction ladder therefore
never fired: the code believed a 60,530-token request was 33,000 tokens and had
room to spare.

### What changed

**A two-stage context.** `context.build_gate` assembles stage A; `context.build`
assembles stage B, and only after the gate has returned `query_mode =
DATA_ANALYSIS` **and** `owner = COCKPIT` **and** the server's own score test has
passed. Every other route out of the gate — product help, theory, referral,
clarification, unsupported, and a failed score test — returns before stage B
exists, so for those the dictionary is never assembled at all.

Stage A carries: the original question, the module, the high-level scope, both
Sonnet passes' output, the entities, actions, periods and ambiguities, the
compact rolling summary, the bounded recent turns, the complete product
knowledge (the functionality registry), the domain name with its high-level
field families, the available quarters, high-level coverage counts, and the
ledger budgets.

Stage A does NOT carry: the relation.column catalogue, the field definitions,
the ratio definitions, the qualitative field detail, the macro pivot columns,
any sample rows, the per-field missingness table, the join graph, the execution
relation schemas, the SQL execution instructions or the grain warnings.

**The gate is still an Opus semantic decision.** It reads the whole question and
scores the whole registry, exactly as before. Nothing in the runtime matches a
keyword, and a test drives two near-identical questions to opposite modes
through the model's own answer and asserts both are obeyed.

**The estimator is calibrated.** `tokens.CHARS_PER_TOKEN` is 2.2 — the measured
2.32 with a small margin the safe way — and `context.CHARS_PER_TOKEN`
re-exports it so there is one number rather than two that can drift. It remains
a fallback: with a credential configured, the provider's own counter is used
and every result records which method produced it.

**The ladder now measures the request, not the packet.** `opus.request_sizer`
renders a candidate payload through the same functions that render the real
request — `system_blocks` and `opening_message`, which are module-level for
exactly this reason — and the ladder reduces against that.

### Measured

| "Who are you?" | Tokens | How counted |
|---|---:|---|
| **BEFORE** | **60,530** | the provider's own counter, live UAT |
| BEFORE, same request, local estimator | 64,599 | local, calibrated at 2.2 |
| **AFTER** | **15,724** | local, calibrated at 2.2 |

The AFTER figure is a local estimate because there is no credential in the
build environment; it is stated as one. Anchored to the one live datapoint the
estimator runs about 5% above the provider's count for this content, so the
true figure is expected slightly below 15,724 and is in no danger of the 64,000
ceiling either way.

**The 64,000-token guardrail was not raised.** Standard is 64,000 with a 4,096
output allowance and Deep is 96,000 with 6,144, unchanged, and a test asserts
all four.

### A capacity finding that came with the calibration

With an honest token estimate, this domain's complete dictionary plus a growing
repair conversation does not fit Standard's per-call cap for the whole
five-submission path. Standard affords the gate, the plan and about two further
analysis turns; Deep affords the full sequence. This is a configuration fact
about the size of the dictionary, it is recorded in
`docs/cockpit_agentic_v3/CONTEXT_SIZING.md`, it is pinned by
`test_how_many_analysis_turns_each_mode_affords`, and the tests that exercise a
full five-submission loop now run in Deep and each say why. Where a request
does outgrow its cap it stops as `CONTEXT_TOO_LARGE` with the measured size,
the cap and what the packet already gave up.

### Tests

`tests/cockpit_agentic/test_two_stage_context.py` — 15 tests: what stage A
carries; what it must not carry, item by item; product help and theory build
only the gate packet; a Cockpit data analysis builds both; referral,
clarification, unsupported and a failed score test build only the gate packet;
the gate is a model decision and not a router; the BEFORE/AFTER measurement;
the ceilings are unchanged; stage B still carries the complete dictionary; the
two stages pin different prefixes and neither changes under itself; how many
turns each mode affords.

`tests/cockpit_agentic/test_caching_and_counting.py` additionally asserts that
the gate request carries no catalogue at all.

---

## Defect 2 — the rolling summary character-expanded a field

### What happened

A live thread's summary held:

```json
"settled_definitions": ["[", "\"", "C", "o", "c", "k", "p", "i", "t", ...]
```

### The root cause

Found by reading the lifecycle end to end — Sonnet structured tool result →
provider response parser → summary contract → normalization → `thread.py` →
persistence → deserialization → context builder → next model request — rather
than by looking at the symptom.

The provider parser is sound: it returns the tool input as the model sent it.
The defect is one expression in `sonnet.update_summary`:

```python
settled_definitions=[str(d) for d in (data.get("settled_definitions") or [])]
```

The schema asks for an array of strings and the model normally sends one. When
it sends a **string** instead — a bare sentence, or the array serialized — `for
d in value` iterates that string one character at a time. The result is a
genuine `list[str]`: it validates, it is stored, it is echoed back into the next
summary request, and it is re-summarised from there. One bad response makes a
thread permanently corrupt, and because the expansion is one element per
character it multiplies the summary's serialized size every time it is carried
forward.

The same expression appeared at **37** model-response boundaries across
`sonnet.py` and `opus.py`. Every one of them was the same latent defect on a
different field.

### What changed

**One normalizer, `contracts.as_text_list`, at every boundary.** Its rule:

- a scalar string becomes a ONE-ELEMENT list — `"some definition"` gives
  `["some definition"]`. Safe, and what the caller meant.
- `list("some definition")` giving `["s", "o", "m", "e", …]` is **forbidden**.
  Nothing in this package can produce it from any input.
- a string that is itself a serialized JSON array is parsed back into its
  elements — a serialization accident is neither one long statement nor 47
  characters. A string that merely looks like one and does not parse is kept
  whole.

**The contract is enforced at construction.** `ThreadSummary.__post_init__` runs
every list field through `as_text_list`, so a summary cannot be built from a
response that returned a string where the schema asked for an array.
`settled_definitions`, `corrections`, `authorized_references`,
`supported_conclusions` and `unresolved_questions` are `list[str]` and stay
`list[str]`.

**Detection and recovery for what is already stored.** Construction cannot fix a
persisted expansion — it is already a list of strings and passes through
unchanged — so `ThreadSummary.repair` detects it and undoes it:

- Detection is deliberately conservative: at least 8 elements and at least 80%
  of them one character. A short list of short strings — quarter labels, rating
  grades, fact ids — is never mistaken for corruption.
- Recovery is a **rejoin, not a reconstruction**. `"".join(elements)` parsed
  back as JSON returns the original statements character for character, or it
  returns nothing.
- Where it cannot be rejoined, **only that field is cleared**. The others are
  untouched — in particular the stored results and `authorized_references`, the
  evidence ids.
- **Nothing is manufactured.** A summary that lost a conclusion says so; it does
  not produce one from the recent exchanges. The prompt it renders tells the
  model to treat a cleared field as unknown rather than empty.
- The recovery is **recorded and surfaced**: `thread.ThreadState.last_repair`,
  the rendered summary's `recovery` block, and `summary_repair` in the API
  response.

Nothing corrupt is carried forward: the repair runs on the way out of storage
(`context_for`) and on the way in (`apply_summary`), and
`sonnet.update_summary` repairs the previous summary before echoing it to the
model. The previous summary is also now serialized as JSON rather than
interpolated as a Python repr.

### Tests

`tests/cockpit_agentic/test_summary_integrity.py` — 16 tests: the safe
conversion; the forbidden one; serialized arrays; real lists; numbers, objects
and nesting; detection; detection's conservatism; rejoin recovery; clearing;
recovery touching only the malformed field; every list field under a bare
string; the live failure reproduced through `update_summary`; a corrupt stored
summary never reaching the next request; a cleared field never refilled; the
context-token-growth check across three turns; and a source check that the
character-expanding comprehension has not come back anywhere in the package.

---

## Defect 3 — the browser gave up, and said nothing

### What happened

`frontend/src/lib/api.ts` had a shared `DEFAULT_TIMEOUT_MS = 20_000`, and
`cockpitV3Ask` inherited it. A real backend request took **20.517 seconds**. The
browser aborted it, and `page.tsx` handled the abort with:

```ts
} catch {
  setV3Steps([]);
}
```

The progress line disappeared and nothing replaced it. A request that failed in
silence reads as a request that succeeded and had nothing to say.

### What changed

**The transport timeout, and only it.** `api.cockpitV3Ask` now passes
`timeoutMs: 120_000`. The shared `DEFAULT_TIMEOUT_MS` stays at 20,000 and every
other endpoint keeps the timeout it was given. A local UAT edit that set
150,000 is not in this branch, and a test asserts it is not.

**This is transport waiting time. It is not a deadline, a budget or a limit.**
Nothing on the server changed:

| | Owned by | Value |
|---|---|---|
| Browser transport timeout for `/cockpit/ask` | `frontend/src/lib/api.ts` | **120 s** |
| Standard overall request deadline | `ledger.STANDARD_LIMITS` | 60 s |
| Deep overall request deadline | `ledger.DEEP_LIMITS` | 120 s |
| Execution submissions | `ledger.INVARIANT` | 5 |
| Analysis rounds | `ledger.INVARIANT` | 3 |
| Total model requests | `ledger.INVARIANT` | 12 / 16 |
| Spending ceiling | `ledger.INVARIANT` | $1.00 / $2.00 |
| Per-call input cap | `ledger` | 64,000 / 96,000 |

The request settles inside its own server deadline whatever the browser's wait
is; 120 seconds is Deep's deadline with the round trip around it, so the
transport now outlives the work rather than cutting it off.

**Every request settles into something the reader can see.** Five outcomes,
stated as data in `components/ask/cockpit-v3-outcome.ts` rather than as branches
inside a component:

> answer · referral · clarification · stop · error

A **stop** is something the server decided and wrote a sentence about.
`STOPPED_TOKEN_LIMIT`, `STOPPED_COST_LIMIT`, `STOPPED_TIME_LIMIT`,
`STOPPED_EXECUTION_LIMIT`, `STOPPED_ANALYSIS_LIMIT`, `MODEL_UNAVAILABLE`,
`DATA_UNAVAILABLE`, `PARTIAL`, `WAITING_FOR_USER` and `REDIRECTED` all arrive as
envelopes and are rendered **with the backend's own explanation**. None of them
is swallowed as a transport error.

An **error** is only the case where there is no envelope at all. It now renders
through `CockpitV3Failure`: the running indicator stops, "Reading the question"
goes away, the governed message appears, and the request id is shown so the run
can be found. It never shows a stack trace, an exception class name, a bare
status code standing in for a reason, or anything from the environment — an
error that is not an `ApiError` contributes none of its own text, only the
written sentence. `v3Running` is set false in a `finally`, so it is off after
any outcome. There is no blank silence.

### Tests

`frontend/src/components/ask/__tests__/cockpit-v3-outcome.test.ts` — 17 tests:
the five settlements; each envelope kind; an unreadable response is an error
rather than an empty answer; every governed terminal state is a supported
outcome; a budget stop renders the backend's sentence; partial and redirect;
the terminal list; a timeout is reported; a governed 503 keeps its explanation;
a failure is never empty and never a bare status code; no stack trace or class
name reaches the reader; the 120,000 transport timeout with `DEFAULT_TIMEOUT_MS`
still 20,000 and no 150,000; the measured 20.517-second request would now
survive; no server deadline, budget or limit was touched; a credential can
never reach the reader through a failure; the indicator is off after
settlement; and the transport error shape matches what the API client throws.

---

## The live regression fixture

`tests/cockpit_agentic/live_uat_regression.json` records the three questions
from the run and what must now happen for each;
`tests/cockpit_agentic/test_live_uat_regression.py` drives them through the
runtime and holds the result against that record.

| Question | Mode | Packet | Opus calls |
|---|---|---|---|
| "Who are you?" | PRODUCT_HELP | gate only | `opus_gate` |
| "What is the difference between PIT and TTC PD?" | THEORY_CONCEPT | gate only | `opus_gate` |
| "Show the borrowers with the largest increase in PIT 12-month PD over the latest four quarters." | DATA_ANALYSIS | gate, then the full analytical packet | `opus_gate`, `opus_plan`, `opus_review` |

These run on the labelled mock. They prove which packets are built, which calls
are made and how each request settles. They prove nothing about answer quality.

---

## What was deliberately NOT changed

- The 64,000 / 96,000 per-call input caps, and the 4,096 / 6,144 output
  allowances.
- The 250,000 / 500,000 cumulative token ceilings and their finalization
  reserves.
- The 60-second Standard and 120-second Deep server deadlines.
- Five execution submissions and three analysis rounds.
- The 12 / 16 model-request ceilings and the $1.00 / $2.00 spending ceilings.
- `DEFAULT_TIMEOUT_MS` in the frontend API client, and every other endpoint's
  timeout.
- The gate's nature: it is an Opus semantic decision over the whole question and
  the whole registry, not a keyword router.
- Section 7.4's rule for the analytical packet: the complete dictionary, never
  abridged.
- The evidence contract: exact stored results and evidence references are
  preserved through a summary repair, and no conclusion is manufactured.
- The 84-question bank, which has not been run, and the live commissioning that
  depends on it.
