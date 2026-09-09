# What the thinking cost

**Part 14.** AI cost, rolled up by the class that decided the routing.

## The defect

`routing.Decision` published a `cost_estimate`. Nothing ever set it, so every
turn reported that its AI cost was **zero**.

A figure that is always zero is worse than no figure. It looks like an answer,
it reconciles with nothing, and the first person to add it up gets a total that
is wrong in the direction that flatters.

## The four classes

| | | |
| --- | --- | --- |
| **A** | Deterministic | Answered from governed data with no model call at all. |
| **B** | Routine | One pass through the standard planner. |
| **C** | Complex | The harder planner, and any repair it needed. |
| **D** | Critic | An independent check on top of the answer. |

Class A carries no calls **by definition** — it is the class where no model was
asked anything — so it is published with zeros rather than omitted. A rollup
that leaves it out cannot show how much of the traffic was answered for
nothing, which is the whole argument for routing.

Every configured role maps to exactly one class, and the mapping is written
down (`cost.ROLE_CLASS`) rather than inferred, so a rollup cannot quietly
reclassify a call into a cheaper bucket. A build-time test asserts that no
configured role is missing from it — a role with no class would land wherever
the default happens to be, which flatters the total.

## Prices are configured, never assumed

**There is no built-in price list.** A tariff nobody entered is reported as
`NOT_PRICED`, and a turn served by an unpriced model contributes to the token
counts and to nothing else.

Inventing a price and presenting the product of two guesses as a cost is
exactly the fabrication the rest of this system exists to prevent, and it is
the easiest one to get away with because nobody checks a number that small.

Configure with `CREDITPROBE_AI_TARIFF`, as JSON, in currency per million
tokens:

```json
{"<model>": {"input": 3.00, "output": 15.00,
             "cache_write": 3.75, "cache_read": 0.30}}
```

Every field is optional. A missing cache price falls back to the **input**
price, which is the conservative reading: a cache token priced as a plain input
token cannot understate the bill.

### Partial coverage says so

A window where some calls used a model the tariff does not cover publishes the
cost it *can* compute, the count of calls it could not, and a sentence saying
the total covers part of the traffic rather than all of it.

## The arithmetic

From the tokens the telemetry already records — including the cache read/write
split, which is the whole reason the telemetry records them separately, since
a cache read costs a fraction of a fresh input token and a cache write costs
more than one.

    cost = (input × input_price
          + output × output_price
          + cache_write × write_price
          + cache_read × read_price) ÷ 1,000,000

## Where it surfaces

`GET /api/v1/ai/cost` — not behind ADMIN, because a class is a statement about
how hard the question was rather than about who serves it. The tariff's keys
are model identifiers and therefore name a vendor, so §12 keeps them off this
surface: the endpoint publishes the *count* of priced models, and the identity
stays on `/status/audit` where it already lived.

## Per turn

`routing.Decision` now reports:

* `cost_estimate` — **`null`**, not `0.0`, where nothing was measured;
* `cost_measured` — whether anything was actually recorded, so a deterministic
  turn that genuinely cost nothing is distinguishable from a turn nobody
  instrumented;
* `unpriced_calls` — calls whose tokens are known and whose money is not.

`routing.record_call(decision, call)` folds one recorded call in, so the
per-turn figure is a sum of calls that actually happened rather than an
estimate nobody can reconcile.
