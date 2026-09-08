# The context packet does not fit the specification's per-call input cap

**Status:** a measured finding, with the serialization half fixed and the
configuration half put to the administrator. Nothing here was worked around
silently.

## The measurement

| Packet section | Estimated tokens |
|---|---:|
| D/E — the complete field dictionary, grains, joins, enumerations, calendar | **22,078** |
| F — measured field coverage (unbounded) | 6,152 |
| H — functionality registry | 2,330 |
| B — server-confirmed scope | 578 |
| I — execution capabilities | 392 |
| A, C, G, J — question, thread, samples, budget | ~600 combined |
| **Whole packet, before any reduction** | **~32,100** |
| **Measured floor** — after every reduction on the ladder | **~28,000** |

Estimated locally at 3.4 characters per token, deliberately conservative:
dense JSON of this kind tokenizes at roughly 3.5–4, and over-counting is the
safe direction because under-counting would let an oversized packet through.
The provider's own token-counting endpoint was not used because no credential
is configured in this environment; §9.3 permits a documented conservative local
estimate, and this is it. A live run should compare the estimate against the
provider's reported `input_tokens` and this document should be updated with the
observed ratio.

Against the specification's §9.1 caps:

| Mode | Per-call input cap (§9.1) | Measured floor | Fits? |
|---|---:|---:|---|
| Standard | 12,000 | ~28,000 | **No** |
| Deep | 20,000 | ~28,000 | **No** |

The floor is measured, not asserted: `measured_floor` in
`tests/cockpit_agentic/test_context_and_registry.py` sets a one-token cap,
lets every rung of the ladder run, and reads the number the builder reports.
A test also asserts that the recommended configuration below actually clears
that floor, so this document cannot drift away from the code.

## Why it cannot be made to fit by trimming

§7.4 sets the priority explicitly: preserve the complete compact schema and the
current scope; reduce optional preview rows and non-essential history first;
and *"do not secretly omit half the schema or silently raise budgets."*

`context.build` implements exactly that as an ordered ladder — halve the
samples, cut history to three pairs, bound the coverage list to 120 entries,
cut samples to two rows, bound coverage to 60, drop samples, cut history to one
pair, drop history. Every rung was applied. Together they recover about 4,000
tokens — the whole packet falls from ~32,100 to ~28,000 — because that is all
the optional detail there is. The remaining ~28,000 is the field dictionary
(22,078), the measured coverage at its most compact (2,135), the functionality
registry (2,330) and the scope and execution blocks, and none of the ladder
touches any of them.

One further honest compression was found while measuring and applied: a field
empty in every reporting quarter used to list all twenty labels, at about 140
characters each. It now reads `"quarters_fully_missing": "every quarter"`,
which says more than twenty labels do and costs a fraction of the context.
That took the coverage block from 6,152 tokens to 2,135 at its bounded size.

The dictionary itself was already compressed as far as it honestly goes:

* 29,600 → 22,078 tokens by structural families, with **no field removed** and
  a test (`test_the_compact_catalog_contains_every_business_field`) that
  reconstructs the full field set from the compact form and asserts nothing is
  missing.
* The 108 collateral summary columns are listed by their real names against
  nine shared meanings rather than 108 near-identical paragraphs — §4.9
  requires the actual names to reach Opus, and they do.
* The 40 ratio companions (`_source_value`, `_status`) share one meaning each.
* The 24 common keys are serialized once and referenced by the ten relations.
* The 200-cell macro pivot is described by an exact reversible rule whose every
  implied column still resolves through `Catalog.resolve`.

What remains is 750 genuine field definitions. A domain with 40 ratios, 20
qualitative questions, 19 grades, 12 collateral types × 9 generated columns, a
full balance sheet and income statement, and 10 macro factors cannot describe
itself in 12,000 tokens. §7.4 says so itself: *"More specific user wording
cannot fix an application whose mandatory catalogue never fits. Fix that
serialization/configuration as an implementation issue."*

## What the implementation does

1. **It measures before it calls.** `context.build` estimates the assembled
   packet and reports the breakdown.
2. **It reduces optional detail first, in the mandated order**, and records
   which rungs it used in `reductions_applied`.
3. **It refuses rather than hiding.** If the core still does not fit it raises
   `ContextTooLarge`, and the runtime returns the `CONTEXT_TOO_LARGE` terminal
   status with the measured figure, the cap, and a pointer to this document.
   It never sends half a schema.
4. **It does not raise the budget by itself.** Every other §9.1 guardrail —
   five submissions, three rounds, the deadline, the cumulative token ceiling,
   the spending ceiling — is fixed in code and cannot be overridden at all.

## The configuration change an administrator would need to approve

§7.4 permits the other branch: *"or require an explicit appropriately
configured mode"*. Two settings exist for that, and **both default to zero,
meaning the specification's own value**:

```
COCKPIT_AGENTIC_V3_STANDARD_INPUT_TOKENS=36000
COCKPIT_AGENTIC_V3_DEEP_INPUT_TOKENS=40000
```

36,000 gives the ~28,000-token floor about 8,000 tokens of headroom for the
question, the thread, the samples and the coverage detail at full fidelity.
40,000 in Deep leaves room for a larger repair conversation, where the failure
packet and the attempt history accumulate on top of the same core.

These are the only §9.1 numbers that can be moved, they can only be moved
upward, and only from configuration. `ledger.input_cap_is_overridden(mode)`
reports whether a deployment is running a raised cap, and the diagnostics
endpoint and the UAT handoff both surface it — so a result obtained under a
raised cap is never read as if it had been obtained under the specification's
own limit.

## The consequence for the cumulative token ceiling

This is the more important half, and raising the input cap does not fix it.

§9.1 sets 35,000 cumulative tokens in Standard and 70,000 in Deep. A single
Opus call carrying this core costs about 28,000 input tokens. So:

* **Standard cannot complete even one Opus call** carrying the full catalogue
  within its 35,000-token ceiling once the reserved 6,000-token finalization
  allowance is held back — 25,700 + output would leave nothing for the
  sufficiency review, let alone a repair.
* **Deep affords two** such calls within 70,000 — a plan and one review, or a
  plan and one repair, but not both, and nothing is left for the Sonnet passes
  or the summary.

§9.6 states this outcome in advance: *"five executions is a maximum, not a
promise that five fit… Sending an 11,000-token context three times already
consumes about 33,000 input tokens."* With this catalogue the figure is 28,000,
not 11,000, so the constraint binds considerably harder.

**The implication is not hidden and is not designed around.** The ledger stops
the request on the token ceiling and says so, exactly as §9.5 requires. A
deployment that wants a Standard-mode question to survive a repair round needs
a cumulative ceiling nearer 100,000, and that is an administrative decision with
a real cost attached — which is why this document puts the number in front of
someone rather than a code change putting it behind them.

Prompt caching lowers the *money and latency* of resending this core and does
not lower the logical token count for this guardrail (§9.3), so it does not
change any figure above.

## Recommended next measurement

Under a configured credential, run the UAT set and record: the provider's
reported `input_tokens` against this local estimate, the observed cache read
and write split across the calls of one question, and the p50/p95 latency of a
call carrying this core. Then revisit the two caps above with measured
evidence rather than with an estimate.
