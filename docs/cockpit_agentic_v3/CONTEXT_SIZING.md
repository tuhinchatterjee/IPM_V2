# Context sizing: two packets, the calibrated estimate, and what binds first

**Status:** measured. This document records what the Cockpit assembles, how
large each part is, how the sizes were arrived at, and which guardrail stops a
request first.

Every figure here is a measurement produced by `context.build_gate`,
`context.build`, `context.floor` and `opus.request_sizer` on the test release.
None of them is a target and none should be read as pinned: the catalogue's
size moves by a few tokens between releases, because it enumerates the filter
values each release actually contains.

## Two packets, because one question cannot be sized for two jobs

Deciding whether "Who are you?" is a portfolio question and planning an
analysis of PIT PD across four quarters need different things in front of the
model, and until the first decision is made nobody knows which the request is.
So there are two.

**Stage A — the gate packet.** `context.build_gate`. The question in all three
forms with its subquestions, measures, actions, entities, periods and
ambiguities; the server-confirmed scope; the rolling summary and the bounded
recent exchanges; the complete functionality registry; the domain in OUTLINE —
what each subject area is about, how many columns it has, which quarters exist;
capability flags; and the remaining budget.

Not in it: the relation.column catalogue, the field definitions, the ratio
definitions, the qualitative detail, the macro pivot columns, the sample rows,
the per-field missingness table, the join graph, the execution relation schemas
and the SQL execution contract. Those exist to write a correct analysis, and no
analysis is written in this turn.

**Stage B — the analytical packet.** `context.build`. Everything above, plus
the COMPLETE compact dictionary, the measured coverage, the sample rows and the
execution contract. Section 7.4 is unchanged for it: the dictionary is never
abridged, and the reduction ladder never touches it.

Stage B is built on ONE edge of the state machine —
`FUNCTIONALITY_ASSESSMENT → PLANNING`, reached only when `query_mode =
DATA_ANALYSIS`, `owner = COCKPIT` and the server's own score test passes.
Product help, theory, a referral, a clarification and an unsupported request
all return before it, and for them the dictionary is never assembled at all.

The gate remains a full semantic decision made by Opus over the whole question
and the whole registry. It is not a keyword router, nothing in the runtime
matches a word, and the two stages are two conversations rather than two halves
of one prompt.

```
RECEIVED → NORMALIZING_1 → NORMALIZING_2 → BUILDING_CONTEXT
                                              │  stage A: the gate packet
                                              ▼
                                     FUNCTIONALITY_ASSESSMENT
   ┌──────────────────────────────────────────┼───────────────────────────┐
   │ PRODUCT_HELP / THEORY_CONCEPT            │ DATA_ANALYSIS + COCKPIT   │
   │ answered in this turn                    │ and the score test passes │
   ▼                                          ▼                           │
ANSWER_VALIDATION                          PLANNING ← stage B: the full   │
   │                                          │        analytical packet   │
   │                             VALIDATING → EXECUTING → REVIEWING        │
   │                                          │                            │
   └──────────────► SUMMARIZING ◄─────────────┴────────────────────────────┘
                        │
   REDIRECTED · WAITING_FOR_USER · UNSUPPORTED leave from the gate directly
```

## The measurement

Standard mode, test release, local estimate at 2.2 characters per token.

| | Packet | Assembled request |
|---|---:|---:|
| **Stage A — the gate** | **8,064** | **15,980** |
| **Stage B — the analysis**, ladder applied | **44,458** | **54,269** |
| Stage B with no reduction | 51,542 | — |
| Stage B required core, what the guardrail forbids reducing | 40,283 | — |
| Stage B measured floor, every rung spent | 43,947 | — |

The packet is not the request. A request also carries the shared preamble, the
turn's contract, the untrusted-data note, the tool schema, the turn's own user
message, and the escaping the message envelope adds when the packet is
serialized into it — together about a fifth again. `opus.request_sizer` renders
a candidate payload through the same functions that will render the real
request and estimates the result, and the reduction ladder runs against that
rather than against the packet alone.

### Where the size is

| Section | Stage A | Stage B |
|---|---:|---:|
| D/E — the complete field dictionary, grains, joins, enumerations, calendar | — | **34,125** |
| D — the domain outline: subject areas, sizes, quarters | 1,631 | — |
| H — the functionality registry | 3,600 | 3,600 |
| F — measured field coverage | — | 3,277 (9,530 unreduced) |
| I — execution contract / capability flags | 128 | 1,127 |
| B — server-confirmed scope | 897 | 897 |
| G — sample rows | — | 593 (1,425 unreduced) |
| A, C, J — question, thread, budget | 665 | 665 |

## The estimate, and why it changed

The local estimator shipped at 3.4 characters per token, on the reasoning that
dense JSON tokenizes at roughly 3.5–4. Live UAT measured that wrong for this
content. The same assembled gate request estimated **41,261** tokens locally
and counted **60,530** against the provider's own tokenizer: **2.32 characters
per token**, not 3.4. Short keys, punctuation and identifiers tokenize far
denser than prose.

A 47% under-count is the failure that matters, because it is the one that lets
an oversized request through — and it is exactly what happened: the reduction
ladder never fired, because the code believed a 60,530-token request was 33,000
tokens.

`tokens.CHARS_PER_TOKEN` is now **2.2**: the measured 2.32 with a small margin
the safe way. `context.CHARS_PER_TOKEN` re-exports it, so there is one
characters-per-token number in the package rather than two that can drift.

It remains a FALLBACK. Whenever a credential is configured, `tokens.Counter`
asks the provider's `messages.count_tokens` against the exact model that will
serve the request — tokenizers differ between model families, so a count taken
against the wrong model is not a count — and every result records which method
produced it. An estimate is never reported as a measurement.

## The configured budgets

The specification's own 12,000/20,000-token per-call caps and 35,000/70,000
cumulative ceilings could not hold this domain's mandatory catalogue. That was
measured and put to the owner rather than closed in code. The owner's decision,
now the UAT configuration:

| | Standard | Deep |
|---|---:|---:|
| Maximum Opus input packet | **64,000** | **96,000** |
| Cumulative logical model-input ceiling | **250,000** | **500,000** |
| Finalization reserve, inside the ceiling | 25,000 | 40,000 |

Both remain application guardrails and both remain configurable upward, through
`COCKPIT_AGENTIC_V3_STANDARD_INPUT_TOKENS`,
`COCKPIT_AGENTIC_V3_DEEP_INPUT_TOKENS`,
`COCKPIT_AGENTIC_V3_STANDARD_TOTAL_TOKENS` and
`COCKPIT_AGENTIC_V3_DEEP_TOTAL_TOKENS`, which default to the values above and
raise only. `ledger.overrides_in_force` reports any that are set, and the
screen badge shows them, so a result obtained under a further-raised cap is
never read as one obtained under this configuration.

### What did not move, and cannot

| | |
|---|---:|
| Opus-authored execution submissions | 5 |
| Substantive analysis rounds | 3 |
| Standard overall deadline | 60 s |
| Deep overall deadline | 120 s |
| Total model requests | 12 / 16 |
| Spending ceiling | $1.00 / $2.00 |

These are in `ledger.INVARIANT` and have **no override at any level**. A test
sets every override that exists, generously, and asserts each of them is
unchanged. The deadlines are there deliberately: a deadline that could be
raised to make a slow analysis fit would stop measuring anything.

## How many turns a request affords — measured, and a real constraint

The analysis packet is built once and every later turn of the request — the
review, each repair — is appended to the same conversation. So two things bound
a request: the per-call cap, which the growing conversation walks toward, and
the cumulative ceiling.

`opus.CONVERSATION_RESERVE` holds back 4,000 tokens beyond the reply so the
packet is not sized to fill the cap exactly. That is one further turn, measured:
a repair turn carrying a failure packet with its diagnostics and prior results
costs about 3,300 tokens. It is deliberately not the worst case — reserving for
four repairs would spend every rung of the ladder on every request and, in
Standard, refuse the packet outright, including for the great majority of
questions answered from their first submission.

Measured by `test_how_many_opus_turns_each_mode_affords`, at a 16,000-token
gate request followed by analysis requests growing 3,300 tokens a turn:

| Mode | Opus turns afforded | Stops on | Model-call ceiling |
|---|---:|---|---:|
| Standard | **4** — the gate, the plan and two more | cumulative token ceiling | 12 — never reached |
| Deep | **7** — the gate, the plan and five more | cumulative token ceiling | 16 — never reached |

Three consequences worth knowing before the live run:

1. **The §9.1 call ceilings are unreachable with this catalogue.** Tokens bind
   first in both modes. That is not a defect — the earliest bound wins by
   design — but a report of "12 calls permitted" would be misleading, so the
   number that matters is above.
2. **A full five-submission repair loop does not fit Standard.** Four repairs
   and a review after the plan is more turns than Standard's per-call cap holds
   once the conversation has grown, and it is more than the cumulative ceiling
   affords. Deep has room for it. The tests that exercise the whole five-
   submission path therefore run in Deep, each saying so, and
   `test_how_many_analysis_turns_each_mode_affords` pins the Standard limit so
   it is recorded rather than discovered in production.
3. **A wide result is expensive.** `SELECT *` over the 198-column facility
   relation produces a result packet of about 8,000 tokens even with no rows —
   it is all column metadata — and the review turn carrying it does not fit
   Standard alongside the dictionary. This is a reason to select columns, and
   a reason to choose Deep for an exploratory question. There is no automatic
   escalation; the mode is the user's choice.

Where a request does outgrow its cap, it stops as `CONTEXT_TOO_LARGE` with the
honest reason — the measured size, the cap, and what the packet already gave up
— and nothing is truncated, abridged or silently substituted.

## What binds first — a measured consequence

With the token ceiling at 250,000 and the spending ceiling held at $1.00,
**spend is now the binding constraint, not tokens.** The arithmetic is
deterministic and does not need a live run to state:

At Opus rates of $5.00 per million input tokens, a single call carrying the
44,000-token stage-B packet costs about **$0.27 of input** before output. Three
such calls reach $0.81; add output at $25.00 per million and the $1.00 ceiling
is reached around the fourth analysis call — at which point Standard's token
ceiling is close behind it.
`test_the_spend_ceiling_binds_before_the_token_ceiling_at_these_volumes` asserts
the ordering, so if either ceiling is ever raised the change is loud.

**Prompt caching is what decides whether that matters.** The cached prefix of
the analysis stage is the catalogue — 34,125 of the 44,458 tokens, 77% of the
packet. On a cache hit those tokens are billed at the provider's cache-read
rate rather than the full input rate, which changes the cost of a repair turn
by roughly an order of magnitude while leaving the logical token count
identical. The ledger counts cached reads toward the token ceiling either way
(§9.3): caching lowers cost, never context size.

The two-stage split lowers cost for a different reason and a larger one: a
product-help or theory question no longer assembles the catalogue at all, so it
costs about 16,000 tokens instead of about 60,000, and never reaches the
analytical budget.

Per the owner's instruction the ceilings stay where they are and live usage
will be measured against them. **What to record in the live run:** cost per
completed question, split by cache hit and miss and by query mode; how often a
question stops on `spend_ceiling_reached` or `CONTEXT_TOO_LARGE`; and whether
those stops are legitimate analyses being cut off or runaway loops being
caught. Only then is there evidence to propose a different number.

## The prompt-cache design

Caching is a prefix match: any byte change anywhere before the breakpoint
invalidates everything after it. So `opus.system_blocks` orders blocks
most-stable-first with **one** breakpoint, and the packet says what belongs
above it:

| Position | Content | Changes |
|---|---|---|
| 1 | Architecture instructions and the Cockpit-only restriction | Never, in a deployment |
| 2 | The pinned domain — the OUTLINE and the registry at stage A; the complete compact catalogue, grains, joins, registry and execution contract at stage B | Never, within a stage — the release is pinned for the request's lifetime |
| — | **cache breakpoint** | |
| 3 | The turn's contract, then the untrusted-data note | Between turns |
| `messages[0]` | Question in all three forms, effective scope and filters, thread; plus coverage and sample rows at stage B; remaining budget | Between requests, and J between turns |
| `messages[1..]` | The plan, prior results, the exact failed code, the diagnostics, the repair instruction | Every turn |

The two stages are two conversations, so neither prefix ever changes under
itself. That split is what makes the plan, repair and review turns of one
request cache hits instead of four full re-reads of a 34,000-token catalogue.

**Caching is an optimisation and nothing else.** The catalogue is sent in full
on every analysis turn whether it is served from cache or not. There is no
hash, no id and no reference Opus would have to resolve, and §8.1 is satisfied
by the content being present rather than by it being cheap. A test reads the
actual serialized repair request and asserts the field definitions are in it —
and a companion test asserts they are NOT in the gate request, because sending
them there is what put a 60,530-token request in front of "Who are you?".

**Verifying it works:** `usage.cache_read_input_tokens` is recorded on every
turn in `outcome.tokens.turns`, and `outcome.tokens.stages` reports each
stage's packet size, its reserve and its largest request. If cache reads are
zero across the analysis turns of one request, something is invalidating the
prefix and the saving is not happening — that is the first thing to check in
the live run.

## Counting before spending

Before every Opus request the assembled system blocks, messages and tools are
counted and the request is **refused before dispatch** if it will not fit with
room for the answer. A request that fits the input cap but leaves no output
allowance has not fitted; discovering that from a truncated response costs a
whole call.

Counting calls are bounded per request and cached by payload fingerprint so the
preflight cannot become a loop, and they are reported separately from the
request's model-call budget because counting is not inference.
