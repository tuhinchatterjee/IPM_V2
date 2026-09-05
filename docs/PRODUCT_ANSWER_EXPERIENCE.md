# The product-knowledge answer experience

The Product Knowledge layer worked. Nobody could read what it produced.

    "What is CreditProbe AI?"  ->  5,079 characters

Seven sections, all eighteen capabilities, the value flow, the continuum and
the installation counts — every time, joined into one run of prose with
upper-cased headings, and rendered by the answer surface inside a single
`<p>`, where HTML collapses every newline.

Every fact in it was true and reconciled to the running installation. It was
still the wrong answer.

---

## Three mechanisms, three fixes

| # | What was wrong | Where it is fixed |
|---|---|---|
| 1 | **No selection.** The composer returned everything the registries held. | `backend/product/answers.py` — intent-specific content, with the rest offered |
| 2 | **No structure.** Sections were flattened into upper-cased lines. | `backend/product/compose.py` — Markdown emission |
| 3 | **No limit.** Nothing capped the size. | `compose.BANDS` + the composition gate |
| 4 | **The surface collapsed what survived.** | `frontend/src/components/ask/rich-text.ts` + `rich-answer.tsx` |

### Before and after

| Question | Before | After |
|---|---|---|
| What is CreditProbe AI? | 5,079 chars, 0 headings, 1 rendered paragraph | 2,479 chars, 373 words, 2 headings, 12 blocks |
| What can CreditProbe do? | 7,839 chars | 1,928 chars, 291 words, 1 `##` + 18 `###` |
| What is the role of AI in CreditProbe? | 2,907 chars, no structure | 2,821 chars, 437 words, 4 headings |
| What is the Early Warning methodology? | 15,371 chars, all 43 signals | 3,299 chars, 490 words — and an offer |
| Explain it in detail | *(no such distinction existed)* | 13,439 chars, all 43 signals, on request |

---

## The composer

`backend/product/compose.py`.

### Bands

Length is a property of the QUESTION, not of how much the registry holds.

| Band | Words | Example |
|---|---|---|
| SHORT | 150–300 | "What is Borrower 360?" |
| MEDIUM | 300–600 | "What is CreditProbe AI?", "What can CreditProbe do?" |
| DETAILED | 600–2,200 | "Explain CreditProbe end to end." |

The ceiling is enforced; the floor is advisory. An answer shorter than its
band is not a defect, an answer longer than it is.

The DETAILED ceiling is deliberately generous. "Explain the Early Warning
methodology in detail" is a request for the forty-three signals, and
answering it in six hundred words would be answering a different question.
It is still roughly four times the same methodology's own default, which is
the point of having a default.

### Progressive disclosure

A `Section` may be marked `detail`. Detail is written once, in the registry,
and shown only when the question asks for depth — "explain the Early Warning
methodology **in detail**" — or when the reader takes up the offer in the
follow-ups.

Two flags, kept apart on purpose:

- **`band`** — how LONG an answer may be.
- **`deep`** — WHICH content it may contain.

Conflating them is how a catalogue question narrowed to ten liquidity signals
started returning the threshold table nobody asked for.

Nothing held back is ever dropped silently. A test asserts that an answer with
held-back sections always offers them.

### Markdown, not flattened prose

`Answer.text()` is now `Answer.markdown()`: `##`/`###` headings, `**bold**`,
`-` bullets, blank lines between every block, blockquote process flows, pipe
tables. The structure travels IN the answer string rather than beside it —
the previous version kept the sections in a parallel payload and handed the
renderer a wall of text.

Long registry prose is split at sentence boundaries on the way out rather than
rewritten in eighteen places, so a paragraph over 55 words becomes two.

---

## The composition gate

Section 14's eleven checks, run on the composed Markdown rather than on the
intention behind it.

| Check | The question it asks |
|---|---|
| `answers_first` | Did it answer the actual question first? |
| `relevant_only` | Did it retrieve only relevant capabilities? |
| `nothing_premature` | Is anything included that was not needed yet? |
| `structured` | Is the answer structured? |
| `concise_opening` | Is the opening concise? (≤ 45 words) |
| `short_paragraphs` | Are paragraphs short? (≤ 70 words) |
| `useful_headings` | Are headings useful? (≤ 9 words, no shouting, no repeats) |
| `whitespace` | Is there enough whitespace? (no line over 700 characters) |
| `tone` | Is the tone professional but conversational? |
| `nudges` | Are follow-ups contextual? (1–3, no repeats) |
| `no_internals` | Is any internal terminology leaking? |

**It can fail, and it did.** Running it against the rewritten answers turned up
four real defects that were fixed at the source rather than by loosening a
threshold:

- the agentic layer described itself as selecting "governed tools from a
  registry — never arbitrary SQL", which is implementation vocabulary in an
  answer for a Chief Risk Officer;
- the AI governance capability quoted cost "in calls and tokens";
- the TAC answer listed what was searched as `backend/`, `docs/` and
  `frontend/src/`;
- `WHY_THE_SPLIT` and `PROBLEM` were single paragraphs of 78 and 120 words.

An answer that still fails the gate is returned WITH its failures, in
`payload["composition"]`. A gate nothing can fail is decoration, and a test
constructs a knowledge dump and asserts it is rejected.

---

## Selection, question by question

| Question | Tool | Shape |
|---|---|---|
| What is CreditProbe AI? | `get_creditprobe_overview` | first person; the mission, five questions you can ask, seven outcomes, where the numbers come from, the arc |
| What can CreditProbe do? / What features…? | `list_creditprobe_capabilities` | `## CreditProbe at a glance` + one `###` per capability, one line each |
| Why should a credit risk officer use CreditProbe? | `why_creditprobe` | outcomes, not modules |
| How can CreditProbe help a corporate credit risk team? | `how_creditprobe_helps_a_team` | a working week |
| Why is CreditProbe different from a normal BI dashboard? | `creditprobe_versus_a_dashboard` | four contrasts + the path an answer takes |
| What is the role of AI in CreditProbe? | `describe_ai_role` | AI does the thinking / Agentic AI does the investigating / The engine protects the truth |
| What is Agentic AI doing inside CreditProbe? | `describe_agentic_ai` | that layer only |
| What is Borrower 360? | `describe_borrower360` | that capability only |
| What is the Early Warning methodology? | `describe_early_warning_methodology` | purpose, four layers, the path, states, severity — then the offer |
| …in detail | same, `deep=True` | the four layers with all 43 signals, AI investigation, Trace and governance |
| What is Trace and why does it matter? | `describe_trace_lineage` | that capability only |
| Explain CreditProbe end to end. | `explain_creditprobe_end_to_end` | the long form, and the only answer that gets it |

Three questions that used to share one answer no longer do. Why a CRO cares is
about OUTCOMES; how a team uses it is about the WEEK; how it differs from a
dashboard is about investigation and traceability. One answer for all three is
the template-shaped writing section 17 forbids.

---

## The frontend

`frontend/src/components/ask/rich-text.ts` reads a composed answer into typed
blocks; `rich-answer.tsx` renders them as React elements.

**No HTML is ever injected.** There is no `dangerouslySetInnerHTML` in this
path: an answer containing `<script>` shows the text on the screen rather than
adding a tag to the document. A product answer is composed from governed
registries and is not user input, but a renderer that is only safe because its
input is trusted is one paste away from not being safe.

`DirectAnswer` decides which renderer an answer gets by looking at the
CONTENT, not at the route. A one-sentence analytical answer renders exactly as
it did before; anything carrying headings, bullets, a blockquote, a table or a
blank line renders as blocks. Any answer that gains structure later renders
correctly without another change there.

Process flows wrap rather than scroll, so a seven-step flow stays readable at
1366 wide.

### A second defect the browser found

The rendering worked, and a wall of prose still appeared underneath it.

`foundNothing` treated any succeeded step with no rows and no values as "the
analysis matched nothing" — and a product answer has no rows because it
queried nothing. So every product answer was ALSO rendered as a
"nothing matched" card: the whole composed answer a second time, in one
unbroken paragraph, directly under the structured one.

A step whose certification is `metadata` ran no analysis and therefore cannot
have failed to match anything. That fixes it for catalogue and metadata
answers too, which had the same shape.

---

## Acceptance

### Through the real Ask path

All thirteen of section 16's questions, through `answer_investigation`:

```
  #  chars  words band      H2  H3 blocks gate   chart  question
  1   2479    373 medium     2   0     12 OK     False  What is CreditProbe AI?
  2   1928    291 medium     2  18     42 OK     False  What can CreditProbe do?
  3   1928    291 medium     2  18     42 OK     False  What features does CreditProbe have?
  4   1781    268 medium     2   0      7 OK     False  Why should a credit risk officer use CreditProbe?
  5   1348    212 medium     2   0      6 OK     False  How can CreditProbe help a corporate credit risk team?
  6   1314    193 medium     2   0      7 OK     False  Why is CreditProbe different from a normal BI dashboard?
  7   2821    437 medium     4   0     11 OK     False  What is the role of AI in CreditProbe?
  8    992    155 short      2   0      6 OK     False  What is Agentic AI doing inside CreditProbe?
  9    937    145 short      4   0      9 OK     False  What is Borrower 360?
 10   3299    490 medium     5   0     15 OK     False  What is the Early Warning methodology?
 11  13439   2042 detailed  12   0     42 OK     False  Explain the Early Warning methodology in detail.
 12    655    101 short      3   0      7 OK     False  What is Trace and why does it matter?
 13   4569    656 detailed   8   0     23 OK     False  Explain CreditProbe end to end.
```

Every one routes to `product_knowledge`, passes all eleven composition
checks, and proposes no chart.

### In a browser

`scripts/product_answer_acceptance.py --start` drives a real Chromium through
the real Ask composer at 1366×900 for the four principal questions, and writes
`docs/screenshots/product_answer_*.png`.

**32/32 checks passed.** Per question: real heading elements, no shouted
headings, list items, no rendered paragraph over 700 characters, no sideways
scroll, no chart surface, the answer's own marker text present, and no error
state.

The last two of those exist because the run before them reported **24/24
passed on four screenshots of a chunk-load error**. An error card has a
heading, the navigation supplies list items, and a screen with nothing on it
has neither a long paragraph nor a chart — so every structural check passed on
a page that never rendered an answer. Two things were wrong and both are
fixed: the harness now asserts a phrase only each answer contains, and it kills
the server process GROUP, because terminating `npm` left the Next server
holding port 3000 and the next run tested the previous build.

---

## What is still open

1. **`docs/PRODUCT_KNOWLEDGE.md` describes the composition this replaced.**
   Its four defects and their fixes are unchanged and still hold; the sections
   describing the shape of the answers are superseded by this document.

2. **The composition gate is deterministic and lexical.** It catches marketing
   words, implementation vocabulary, long paragraphs and missing structure. It
   cannot tell whether the writing is any good — that is what the screenshots
   are for.

3. **The style is one reviewed voice.** Section 17 asks for variation, and the
   answers do vary in structure (a test asserts at least eight distinct heading
   shapes across the thirteen). They do not vary in register, because the
   register is reviewed and a varying one would not be.

4. **Monetary units still disagree** between the concept map (`SAR mn`) and the
   Early Warning taxonomy (`SAR`). Unchanged here and unchanged on a guess —
   the same finding recorded in `docs/MULTI_CONDITION.md` and
   `docs/PRODUCT_KNOWLEDGE.md`.
