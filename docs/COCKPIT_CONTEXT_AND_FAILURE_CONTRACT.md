# The context packet and the failure contract

What CreditProbe sends Opus, what it sends back when a query fails, and the
evidence that it really does.

## The context packet — sections A to J

Built by `backend/cockpit_agentic/context.py` from authenticated application
state and this domain's own catalogue. Sonnet contributes the cleaned and
normalized question and nothing else: it has not seen the catalogue, and there
is no field in either of its schemas for a dataset, a field, a coverage figure
or a missing rate.

| Section | Contents |
|---|---|
| **A** request | The original text, the pass-1 translation with its detected language, the pass-2 business request, every subquestion, and every ambiguity left unresolved. |
| **B** scope | Server-confirmed module, tenant, release, currency, screen filters, and `explicit_scope` kept apart from `inherited_scope` with the precedence stated. |
| **C** thread | The rolling summary and the bounded recent exchanges, each carrying its kind. |
| **D/E** catalogue | The COMPLETE field dictionary, grains, joins with their multiplicity warnings, enumerations, the forty ratio definitions and the twenty-slot calendar with the macro window. |
| **F** coverage | Field-level missingness measured over the whole release, both denominators, and every field entirely absent from a quarter. |
| **G** samples | Up to ten reproducible, permission-filtered rows, labelled as shape rather than evidence. |
| **H** functionalities | The registry: descriptions, ownership, exclusions, enabled state and verified routes. No other module's data. |
| **I** execution | The SQL dialect, the readable relations, the statement rules, the chart limit, and the honest statement that Python is unavailable. |
| **J** budget | Submissions, rounds, calls, tokens, seconds and spend remaining. |

### What shrinks, and what never does

§7.4 sets the priority: preserve the complete compact schema and the current
scope; reduce preview rows and non-essential history first; and never secretly
omit half the schema or silently raise a budget.

`context.LADDER` is that priority, as an ordered list of eight reductions —
halve the samples, cut history to three pairs, bound coverage to 120 entries,
samples to two rows, coverage to 60, drop samples, history to one pair, drop
history. Which rungs were used is reported in `reductions_applied`. If the core
still does not fit, `ContextTooLarge` is raised and the request ends with the
`CONTEXT_TOO_LARGE` status, the measured figure and a pointer to
[`CONTEXT_SIZING.md`](cockpit_agentic_v3/CONTEXT_SIZING.md).

**Measured:** the whole packet is ~32,100 tokens before reduction and ~28,000
after every rung, against §9.1's caps of 12,000 Standard and 20,000 Deep. That
gap is a configuration matter and is put to an administrator explicitly rather
than closed in code. See CONTEXT_SIZING.md for the numbers and the
consequences.

## The failure contract — §7.6A

**CreditProbe never repairs, rewrites, edits, patches, completes or substitutes
Opus-authored SQL or Python.**

`backend/cockpit_agentic/failure.py` is where that rule could most plausibly be
broken — it is the code that looks at a broken query and knows what would fix
it — and there is no branch in it that produces SQL. It reports:

- the exact submitted code and its parameters;
- the engine's own error, sanitized, in the §8.2 taxonomy;
- fields that DO exist and are near the one that did not, **with their meanings
  and units and no preference between them** — `pd_pit_12m` and `pd_ttc_12m`
  are both real, and only the question decides;
- the filter values that actually exist where a filter matched nothing;
- the grains and valid join keys;
- completed steps and reusable artifacts, so work is not redone;
- previously failed approaches, compactly, so one is not repeated;
- `repairable`, and `False` for every security or permission category, because
  §8.3 fails those closed rather than spending four more attempts on a
  workaround;
- the remaining budget and the permitted next actions, which are the server's
  to decide.

## The evidence

`docs/cockpit_agentic_v3/evidence/repair_request_shape.json` is the shape of an
**actual serialized repair request**, captured from a real run, with the cached
catalogue prefix replaced by its size. `repair_failure_packet.json` is the
packet that produced it. §14.3 asks for exactly this — the actual outbound
request, not an assertion about it.

The eight properties it demonstrates, all `true` in the committed file:

| Property | Why it matters |
|---|---|
| carries the original question | §8.1: the repair must solve the same question. |
| carries the complete dictionary | Not a hash. The test constructs the hash-only payload §8.1 says must fail, and shows it does. |
| carries the exact failed SQL | An error-only retry is forbidden. |
| carries the catalogue alternatives | Facts, so Opus can choose. |
| carries the remaining budget | Opus spends deliberately or stops. |
| **carries no repaired query** | §7.6A. The corrected SQL appears nowhere in what CreditProbe sent. |
| the catalogue is in ONE cached prefix | §8.1: the static context belongs once in the assembled input. |
| the failure packet does not duplicate the dictionary | The same rule, from the other direction. |

The request in that trace is 138,810 characters: a 3,252-character contract, a
112,438-character cached catalogue prefix, a 192-character untrusted-data note,
and four messages — the planning turn, the assistant's own `tool_use` block
threaded back verbatim, its paired `tool_result` carrying the 6,786-character
failure packet, and the repair instruction.

`tests/cockpit_agentic/test_repair_context.py` asserts all of this on every
run, including that `tool_use` and `tool_result` blocks are paired in order and
that the conversation continues rather than restarting.

## The counters, and what they mean for a repair

- Five execution submissions for the whole question, including the first. They
  do not reset when the plan changes; there is a test that pursues three plans
  and gets five attempts, not fifteen.
- Three substantive analysis rounds, including the first. A syntax or binding
  repair uses a submission and is not a round.
- An identical candidate is blocked **before** execution on a whitespace- and
  case-normalized fingerprint, so re-indenting a failed query is not a changed
  approach. The blocked duplicate does not consume an attempt.
- The earliest bound wins. A test spends two submissions, expires the deadline,
  and shows three attempts nominally remaining and none usable.

## The mock, and what it does not prove

Every trace and test above uses the labelled mock provider in
`tests/cockpit_agentic/fake_provider.py`. It proves what CreditProbe puts in
the request and how the application handles each decision. It proves nothing
about how a real model behaves, and live-provider validation is **BLOCKED**
until a credential is configured.
