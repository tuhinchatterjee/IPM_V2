# The Cockpit's two model roles fail closed

## What was wrong

Every other role in CreditProbe resolves generously: the role's own variable,
then a nearer role, then `AI_MODEL`, then the provider SDK's own pinned
default. That is correct there. An unconfigured deployment still runs — the
deterministic reader does the reading — and a resolver that refused to find a
model would be refusing a supported mode.

The Cockpit inherited that behaviour and should never have. It has no
deterministic reader. Every answer it gives is authored by a model, so "which
model" is not a preference here, it is the whole claim. With nothing
configured, `cockpit_reasoning` fell through to `AI_COMPLEX_PLANNER_MODEL`,
then to `AI_MODEL`, then to whatever the SDK shipped — and it reported that it
had inherited, which is technically honest and practically useless: a
commissioning run against it would have measured a model nobody chose, and the
answers could not be attributed afterwards.

## What it does now

Both ids are read from their own environment variables and from nowhere else.

| Role | Variable | What it serves |
|---|---|---|
| `cockpit_preprocess` | `AI_COCKPIT_PREPROCESS_MODEL` | The two preprocessing passes and the rolling-summary update. Cleans, translates, normalises. Chooses no method and computes nothing. |
| `cockpit_reasoning` | `AI_COCKPIT_REASONING_MODEL` | Functionality selection, the analysis plan, every query and every repair, the sufficiency review and the final interpretation. Every analytical decision in the product. |

| If | Then |
|---|---|
| Either variable is unset or blank | `MODEL_CONFIGURATION_MISSING`, naming the variable |
| Either holds something that is not a model id — a trailing comment, an unexpanded `$AI_MODEL`, embedded quotes | `MODEL_CONFIGURATION_MISSING`, echoing the value back so the operator sees what they typed |
| Either names a model the provider will not serve | `MODEL_UNAVAILABLE`, naming the id |
| Any of the above | **No answer.** No deterministic substitute, no other model |

The refusal happens when the `Runtime` is constructed, before the first
preprocessing call, and is reported through the ordinary outcome rather than
as an exception — so the API surface has one shape for a stop, not two.

## The four routes that are closed

1. **Another role.** `cockpit_preprocess` no longer borrows `AI_ROUTER_MODEL`
   and `cockpit_reasoning` no longer borrows `AI_COMPLEX_PLANNER_MODEL`.
2. **`AI_MODEL`.** The shared default serves seven other roles and not these.
3. **The SDK default.** `AnthropicProvider.converse` substitutes its own
   pinned model for an empty `model` argument — correct for the legacy paths,
   forbidden here. `models.require()` is the last gate before dispatch and
   refuses an empty id, so one never reaches the provider from the Cockpit.
4. **Silent substitution of any other model.** Nothing in the Cockpit picks a
   model. There is exactly one place each id can come from and the run's
   metadata records which variable it came from.

`backend/llm/roles.py` was changed to agree, through a `STRICT_ROLES` set: the
Settings page and the preflight now report these two as unconfigured rather
than showing an inherited model for a role that will refuse to use one. A page
that displayed a fallback the runtime would not honour is the same lie in a
different place. Every other role resolves exactly as before.

The preflight reports them with their own state, `REQUIRED_UNSET`, rather than
the existing `UNCONFIGURED`, because the two mean different things: for an
ordinary role an empty id means the provider's default serves it, and for
these it means nothing serves them. It is reported and **does not fail the
preflight** — the Cockpit is off by default, the rest of the product runs
without it, and a server that refuses to boot is one an administrator cannot
reach the settings page on to fix. The enforcement belongs where it matters,
at the Cockpit's own first request.

The badge on the Cockpit screen shows the two ids when they are set and a red
`models: not configured` with the variables to set when they are not.

## Where the ids are recorded

`Outcome.to_dict()["models"]` on every run:

```json
{
  "provider": "anthropic",
  "preprocess_model": "...",
  "reasoning_model": "...",
  "source": {"cockpit_preprocess": "AI_COCKPIT_PREPROCESS_MODEL",
             "cockpit_reasoning":  "AI_COCKPIT_REASONING_MODEL"},
  "fallback_used": false,
  "verified_with_provider": false
}
```

`GET /api/v1/cockpit/diagnostics` reports the same under `cockpit_models`,
including the variables still to set when it is not configured.

## Availability, checked without spending a generation

`models.verify_live` calls the provider's token-counting endpoint once per id.
It names the exact model, costs no output, and a wrong id fails there exactly
as it would on a real call. A provider that cannot count tokens leaves the ids
**UNVERIFIED** — reported as that, rather than as either a pass or a failure.

`models.ensure_available` runs it on the first Cockpit request of a process and
caches the result against the provider and the id pair. A wrong id is wrong for
the life of the process, and paying a probe on every question to rediscover
that would be a tax on the correct case. Without it, a configured-but-wrong id
would surface only when the first real call failed, arriving as a generic
provider error with the wrong remedy attached.

## The credential

`backend/cockpit_agentic/models.py` never reads, holds, logs or reports
`ANTHROPIC_API_KEY`. The model ids are configuration and are reported; the key
is a secret and is not. A test sets a recognisable fake key in the environment
and asserts it appears in neither the resolved metadata nor the diagnostics,
and reads the module's own source to confirm it does not reach for the key at
all.

## The tests

`tests/cockpit_agentic/test_model_configuration.py`, twenty-six of them:

- a missing preprocess model fails closed, naming its variable
- a missing reasoning model fails closed, naming its variable
- blank and whitespace-only values are not configured values
- a malformed value is refused and echoed back
- `AI_MODEL` cannot substitute, and its value does not appear in the refusal
- another role cannot substitute
- the SDK default cannot substitute
- the shared resolver reports both as strict, while every other role still
  inherits as before
- **the configured preprocess id serves both preprocessing passes**, read off
  the recorded outbound requests
- **the configured reasoning id serves the gate, the plan, the repair, the
  review and the final answer**, read off the recorded outbound requests
- no request anywhere in a run leaves without a model
- an unconfigured Cockpit stops, asks the provider for nothing, and answers
  nothing
- a model the provider refuses stops with `MODEL_UNAVAILABLE`
- verification uses the exact configured ids
- every run records the ids that served it
- nothing about the configuration can carry the credential
- a refused model stops the whole request end to end, and asks the provider
  for nothing after that
- the availability check costs one call per process, not one per request
- no module in the package reaches for the credential except the one that
  builds the provider, and none passes it to anything but `bool()` and the
  provider's constructor
- the diagnostics payload the browser is actually sent carries the two model
  ids and no credential
- the preflight reports both strict roles as `REQUIRED_UNSET` and still
  returns `ok`, while an ordinary unset role still reports `UNCONFIGURED`

The test fixture configures two deliberately unmistakable ids —
`test-preprocess-model-not-a-real-id` and `test-reasoning-model-not-a-real-id`
— rather than the production ones. A test that set `claude-opus-5` would pass
whether or not the code read the variable, because the production default
would have given the same answer.

These use the labelled mock provider. What they prove is which id this
application puts on the wire, which is exactly what a mock can prove. They say
nothing about how any model behaves.
