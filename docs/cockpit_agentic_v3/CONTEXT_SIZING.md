# Context sizing, the configured budgets, and what now binds first

**Status:** measured, and resolved by an owner decision. This document records
the measurement, the configuration that followed from it, and the constraint
that has moved as a result.

## The measurement

Measured by `context.build` and `context.floor` and written to
`evidence/context_measurements.json` on every docs build.

| Packet section | Tokens |
|---|---:|
| D/E — the complete field dictionary, grains, joins, enumerations, calendar | **22,074** |
| F — measured field coverage, unbounded | 6,150 |
| H — functionality registry | 2,330 |
| G — sample rows | 922 |
| B — server-confirmed scope | 574 |
| I — execution capabilities | 392 |
| A, C, J — question, thread, budget | ~550 combined |
| **Whole packet, no reduction** | **32,991** |
| **Measured floor**, every rung of the ladder spent | **28,105** |

Estimated locally at 3.4 characters per token — deliberately conservative,
because over-counting refuses work that would have fitted and under-counting
lets an oversized request through. **Under a live credential this is replaced
by the provider's own count** against the exact model that will serve the
request (`backend/cockpit_agentic/tokens.py`), and every result records which
method produced it. An estimate is never reported as a measurement.

The floor is a measurement, not a number typed here: `context.floor` runs every
rung of the reduction ladder and reports what is left, and a test asserts the
configured cap clears it.

## The configured budgets

The specification's own 12,000/20,000-token per-call caps and 35,000/70,000
cumulative ceilings could not hold a 22,074-token mandatory catalogue. That was
measured and put to the owner rather than closed in code. The owner's decision,
now the UAT configuration:

| | Standard | Deep |
|---|---:|---:|
| Maximum Opus input packet | **64,000** | **96,000** |
| Cumulative logical model-input ceiling | **250,000** | **500,000** |
| Finalization reserve, inside the ceiling | 25,000 | 40,000 |

64,000 leaves the 28,105-token floor about 36,000 tokens of headroom for the
conversation — the plan, the results, the failure packets and the attempt
history that accumulate across a repair loop. Both remain application
guardrails and both remain configurable upward, through
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

## What now binds first — a measured consequence

With the token ceiling at 250,000 and the spending ceiling held at $1.00,
**spend is now the binding constraint, not tokens.** The arithmetic is
deterministic and does not need a live run to state:

At Opus rates of $5.00 per million input tokens, a single call carrying the
28,105-token floor costs about **$0.14 of input** before output. Six such calls
reach $0.84; add output at $25.00 per million and the $1.00 ceiling is reached
between the fifth and sixth call — while barely 170,000 of the 250,000-token
ceiling has been used. `test_the_spend_ceiling_binds_before_the_token_ceiling_at_these_volumes`
asserts exactly this, so if the ceiling is ever raised the change is loud.

**Prompt caching is what decides whether that matters.** The cached prefix is
the catalogue — 22,074 of the 28,105 tokens, 79% of the packet. On a cache hit
those tokens are billed at the provider's cache-read rate rather than the full
input rate, which changes the cost of a repair turn by roughly an order of
magnitude while leaving the logical token count identical. The ledger counts
cached reads toward the token ceiling either way (§9.3): caching lowers cost,
never context size.

Per the owner's instruction the ceilings stay where they are and live usage
will be measured against them. **What to record in the live run:** cost per
completed question, split by cache hit and miss; how often a question stops on
`spend_ceiling_reached`; and whether those stops are legitimate analyses being
cut off or runaway loops being caught. Only then is there evidence to propose a
different number.

## How long a request can actually run — measured

Every Opus turn carries the whole packet, so the cumulative token ceiling, not
the model-call ceiling, decides how many turns a request affords. Measured by
`test_how_many_full_context_calls_each_mode_affords`, at a 28,000-token packet
growing 2,500 tokens a turn as results and attempt history accumulate:

| Mode | Full-context Opus calls afforded | Stops on | Model-call ceiling |
|---|---:|---|---:|
| Standard | **6** | token ceiling | 12 — never reached |
| Deep | **10** | token ceiling | 16 — never reached |

Two consequences worth knowing before the live run:

1. **The §9.1 call ceilings are unreachable with this catalogue.** Tokens bind
   first in both modes. That is not a defect — the earliest bound wins by
   design — but a report of "12 calls permitted" would be misleading, so the
   number that matters is above.
2. **A full five-submission repair loop is at the edge of Standard.** The gate,
   four repairs and a review are six calls, which is exactly what Standard
   affords at a 28,000-token packet and one call short at 33,000. Deep has room
   for it. If a live question is expected to need several repairs, that is a
   reason to choose Deep — and it is a decision for the user, since there is no
   automatic escalation.

Prompt caching does not change these numbers: cached reads count toward the
token ceiling in full (§9.3). It changes what they cost, not how many there
are.

## The prompt-cache design

Caching is a prefix match: any byte change anywhere before the breakpoint
invalidates everything after it. So `opus.Conversation.system` orders blocks
most-stable-first with **one** breakpoint:

| Position | Content | Changes |
|---|---|---|
| 1 | Architecture instructions and the Cockpit-only restriction | Never, in a deployment |
| 2 | The pinned domain: complete compact catalogue, grains, joins, functionality registry, execution contract | Never, within a request — the release is pinned for its lifetime |
| — | **cache breakpoint** | |
| 3 | Untrusted-data note | Never |
| `messages[0]` | Question in all three forms, effective scope and filters, thread summary and recent exchanges, measured coverage, sample rows, remaining budget | Between requests, and F and J between turns |
| `messages[1..]` | The plan, prior results, the exact failed code, the diagnostics, the repair instruction | Every turn |

That split is what makes the repair turns of one request cache hits instead of
four full re-reads of a 22,000-token catalogue.

**Caching is an optimisation and nothing else.** The catalogue is sent in full
on every request whether it is served from cache or not. There is no hash, no
id and no reference Opus would have to resolve, and §8.1 is satisfied by the
content being present rather than by it being cheap. A test reads the actual
serialized repair request and asserts the field definitions are in it.

**Verifying it works:** `usage.cache_read_input_tokens` is recorded on every
turn in `outcome.tokens.turns`. If it is zero across the repair turns of one
request, something is invalidating the prefix and the saving is not happening —
that is the first thing to check in the live run.

## Counting before spending

Before every Opus request the assembled system blocks, messages and tools are
counted and the request is **refused before dispatch** if it will not fit with
room for the answer. A request that fits the input cap but leaves no output
allowance has not fitted; discovering that from a truncated response costs a
whole call.

Counting uses the provider's `messages.count_tokens` against the exact model
that will serve the request — tokenizers differ between model families, so a
count taken against the wrong model is not a count. With no credential it falls
back to the documented local estimate and says so. Counting calls are bounded
per request and cached by payload fingerprint so the preflight cannot become a
loop, and they are reported separately from the request's model-call budget
because counting is not inference.
