# Why Ask CreditProbe failed six questions in a row

*Recorded before anything was changed, from the running product. This is the
diagnosis the rebuild is answering; it is kept because "we fixed it" is not a
useful record without "this is what was wrong".*

---

## 1. What the running product actually was

`GET /api/v1/ask/mode` on the running stack returned:

```json
{"mode": "demo", "planner": "demo", "model_name": null,
 "description": "No model key is configured, so CreditProbe reads questions
                 with its built-in deterministic planner..."}
```

That is what the Trace meant by **"Planned by CreditProbe (deterministic)"**.
No language model was involved in reading any question. `get_planner()` returns
`AnthropicPlanner` only when `ANTHROPIC_API_KEY` is set, and it was not.

But the missing key is the *smaller* half of the problem.

## 2. The larger half: even with a key, the model could not reach the runtime

`AnthropicPlanner.plan()` did not produce an Analytical IR. It produced an
`AnalysisPlan` — a selection of **registered engine analyses** from a fixed
catalogue of 24. So with a key configured, the model's entire freedom was
"which of these 24 canned analyses, with which parameters".

The Analytical Runtime, the relationship graph, the multi-dataset planner and
Analysis Studio were all unreachable from the model. They were reachable only
from two deterministic regex readers.

## 3. The regex readers only fire on anticipated phrasings

`run_investigation()` routes in this order:

```
multi_candidate(question)    → deterministic regex reader (multi.py)
dynamic_candidate(question)  → deterministic regex reader (dynamic.py)
planner.plan(question)       → phrase-to-registered-analysis map (planner.py INTENTS)
```

Measured on the running build:

| question | multi | dynamic | fell through to |
|---|---|---|---|
| "Which customers had a **rating downgrade** and an **increase in ECL** over the latest year?" | None | None | `ecl_movement` |
| "Show Real Estate customers whose **ECL increased more than 20%**, rating **deteriorated at least two notches**, and EAD did not decline over the latest year." | **YES** | YES | — |

Those are the same question. The second is the phrasing the reader was written
against — it needs an explicit comparison threshold ("more than 20%", "at least
two notches") to recognise a condition at all. The first is how a person asks.

So the dynamic runtime was, in practice, reachable only from the test suite and
from questions phrased like the test suite. Every other question fell through to
the phrase map.

## 4. What each of the six did, and why

| # | question | routed to | why |
|---|---|---|---|
| 1 | "What data do you have about borrower ratings?" | `portfolio_summary` + clarification | There is no data-discovery capability. Every question is assumed to be a request for a number, so a question about the catalogue was scored against credit-risk intents and matched nothing. |
| 2 | "How is the ratings data connected to IFRS 9 data?" | `stage_distribution` | The phrase map scored `ifrs.?9` and returned Stage 2/Stage 3 exposure statistics. There is no relationship capability, so a question about a join was answered with a portfolio distribution. |
| 3 | "What is total EAD by sector in the latest quarter?" | `portfolio_summary` + clarification | Neither regex reader handles a plain group-by. The runtime can express `SCAN → FILTER → GROUP → SUM` trivially; nothing could ask it to. |
| 4 | "Show the five largest Real Estate customers by EAD" | `sector_concentration` filtered to Real Estate | The concentration analysis computes shares **within its filtered population**, so filtering to Real Estate and then reporting concentration says Real Estate is 100% of the book and the top five hold 100% of it. Every figure was correct; the question was wrong. |
| 5 | "Which customers had a rating downgrade and an increase in ECL over the latest year?" | `ecl_movement` | Two conditions across two governed sources, unrecognised (§3 above), so the closest single-dataset analysis ran: total ECL movement. |
| 6 | "Which customers have worsening leverage and declining DSCR together with a rating downgrade?" | `stage_migration` + `ecl_movement` + `top_deteriorating_borrowers` | Three conditions across Borrower Financials and Ratings, unrecognised. "deteriorating" matched the generic deterioration intent. |

Four of the six returned a **confident, correct figure for a question nobody
asked**. That is the failure mode the product exists to prevent, and it was
being produced by the product's own front door.

## 5. The root cause in one sentence

> Natural-language understanding was implemented as regular expressions over
> anticipated phrasings, and the only thing those expressions could select was a
> fixed list of pre-built analyses — so the product could answer only questions
> somebody had already thought of, and answered everything else with the nearest
> canned analysis rather than saying it had not understood.

## 6. Contributing faults, each independently sufficient

1. **No capability routing.** Every question was assumed to be an analysis
   request. Data, relationship, dictionary and method questions had nowhere to go.
2. **The model, when present, planned at the wrong altitude** — selecting named
   analyses instead of composing an IR.
3. **The fallback was silent.** With no key the product presented itself as
   normal CreditProbe rather than as a degraded mode.
4. **Falling through was silent too.** When the regex readers declined, nothing
   recorded that a composition had been attempted and abandoned; the registry
   answer was presented as the intended one.
5. **`unmatched=True` did not stop an answer.** Q1 and Q3 were scored as
   unmatched and still returned `portfolio_summary`.
6. **Credit semantics lived in phrase tables**, not in the governed concept
   definitions, so "downgrade", "worsening leverage" and "declining DSCR" had no
   meaning outside the exact strings someone had written down.

## 7. What is therefore being rebuilt

- A real, configurable LLM provider, used as the **orchestrator** — it produces
  a structured intent and an analytical plan, and never a figure.
- A **capability router** ahead of execution, so only ANALYSIS questions reach
  the numerical path.
- **Governed context retrieval** so the orchestrator plans against Data Builder
  metadata and Studio methods rather than from memory.
- A **semantic planner** that builds validated IR from concepts, replacing the
  phrase-to-analysis map, which drops to an emergency fallback.
- An honest **LIMITED OFFLINE MODE** when no provider key is configured.
- A **Trace** that shows the intent, the governed sources, the joins, the
  derivations, the mathematical query and the SQL that produced the answer.
