# Cockpit V4 — live-UAT hardening round

Branch `claude/cockpit-single-agent-v4-h8fsbq`. Starting HEAD `c4d78a1`, the
build that was deployed for UAT. Not merged. V3 untouched. No paid provider
call was made from this environment and no key was asked for.

---

## 1. The verdict, first

**COCKPIT V4 LIVE-UAT HARDENING:
READY FOR MAC RETEST**

All four live failures are reproduced, root-caused, fixed, and covered by
regressions that fail on the old code. The Corporate book has been rebuilt at
a scale that makes its answers worth measuring. Every figure and every period
is written one way on every surface, including the export. The full matrix is
in §24 and the caveats — what a scripted analyst still cannot prove — are in
§28.

## 2. What a scripted suite could not see

The automated dual-domain suite was green while all four failures were live,
and that is not an accident of coverage. A scripted analyst does not read its
instructions, does not read its tool schema, does not decide what a word
means, and does not run out of time. Three of the four failures were in
exactly those places:

| Live failure | Where it lived | Why the suite was blind |
| --- | --- | --- |
| "This book is recorded quarterly" | the prompt, the tool schema, the registry text, and the accepted `release_id` | a scripted analyst returns what the test told it to, whatever the contract says |
| a Retail card opening a Corporate thread | one line in `routes.py` | every test constructed its run by hand with the right release; the ROUTE never did |
| DEADLINE_EXPIRED at 60s | the allowance was adopted from a parsed declaration | a scripted turn answers in milliseconds |
| catalogue thrashing over `prject finance` | nothing resolved category VALUES | a scripted analyst never has to work out what a word means |

The regressions added this round drive the REAL path — the real route, the
real worker, the real context builder — and assert on what CreditProbe sends,
opens, starts and resolves, rather than on what a mock analyst replies.

## 3. Live failure 1 — the legacy quarterly book, in a monthly thread

**Reproduced.** A new Corporate thread, asked for the latest month, was
answered from `v4-saudi-20q-v1` with a 2026Q2 period and the sentence "This
book is recorded quarterly, not monthly."

**Root cause, first half.** The period vocabulary was hard-coded in three
places the analyst must believe: the worked example in `prompts/analyst.md`
("period not specified: using the latest populated quarter 2026Q2 against
2026Q1"), the same sentence in every tool schema, and a field literally named
`reporting_quarters` in `execute_analysis`. The V3 module registry told it the
Cockpit owns "the twenty-quarter corporate domain". The analyst believed the
CONTRACT over the catalogue, correctly, because the contract is the thing it
has to fill in.

**Root cause, second half, and the real one.** `routes.py` accepted every run
against `body.release_id or cfg.release_id` — the request, or else whatever
release the PROCESS was configured for — while stamping the correct
`domain_id`. On a Mac configured for the pre-domain release, every run of
either book was accepted against `v4-saudi-20q-v1`. `arun.for_run` then raised
`LegacyRelease` and the worker fell back to the legacy corporate book. That
one line is the whole of this failure and the whole of failure 2.

**Fixed.** `semantics.vocabulary()` derives nine period tokens from the run's
own book and `{{TOKEN}}` substitution rewrites the instruction, the registry
line and every tool schema. The wire field is `reporting_periods`; all three
spellings are still accepted. `routes.py` accepts `release_id=scope.release_id`
and refuses a request naming a different release with 409
`RELEASE_NOT_SETTABLE` rather than obeying it.

**Regression.** `test_provider_payload_isolation.py` drives the real worker
with a provider that records the payload and then raises, so the bytes under
test are the bytes a paid call would carry. Nine forbidden patterns, both
books, every tool schema.

## 4. Live failure 2 — Investigate Further opened the wrong book

**Reproduced.** A Retail Credit Card ECL card, opened with Investigate
Further, produced a thread that answered: "The Credit Card ECL card sits in
the retail book, and this thread reads the corporate book only."

**Root cause.** The same line in `routes.py`. The seed named Retail, the
thread was created in Retail, and the RUN was accepted against the configured
release.

**Fixed.** As above. The seed envelope carries `domain_id`, `release_id`,
`release_fingerprint`, the originating item id, the period, the segment and
the metric, and the thread is created in the book the card came from before
the seed is written.

**Regression.** `test_investigation_routing.py` walks EVERY card of EVERY
attention family and EVERY ECL-highlight family on BOTH dashboards through the
whole flow — open the card, investigate, inspect the created thread, start a
run in it, and check the book that run actually reads — rather than one
fixture.

## 5. Live failure 3 — a data-analysis turn killed by the product-help clock

**Reproduced.** In a thread that had already run an analysis, "How is risk
building in Information Technology?" failed with DEADLINE_EXPIRED at sixty
seconds. Sixty is the PRODUCT HELP allowance.

**Root cause.** The analytical allowance was adopted only after the analyst
declared `DATA_ANALYSIS`, or called `execute_analysis`. Declaring it costs a
provider generation, and on a large book a first generation is most of a
minute. The turn was killed by the clock it was meant to have left behind
before it started.

**Fixed.** `envelope.classify` names one policy family before the first
provider call, from the question, the mode and the thread. A conversation
opened from an attention card, or one whose earlier turn ran an analysis, is
about a figure; a question naming a measure, a comparison or a period is about
a figure. The classification is deliberately asymmetric — an allowance is a
CEILING, so mistaking help for analysis costs nothing and the reverse kills
the turn. The declaration path is unchanged and still widens a turn that
started narrow.

## 6. The allowance ladder, published

| Family | Deadline | Ceiling |
| --- | --- | --- |
| `product_help.standard` | 60s | $1.00 |
| `data_analysis.standard` | 120s | $1.50 |
| `data_analysis.deep` | 240s | $3.00 |

`/diagnostics` serves `budget_policy.families` and `STATUS_COCKPIT_V4` prints
the three named families, so an operator reading a run that stopped on time
can see which family it was in without reading the source.

## 7. The finalization reserve is now spent writing

Twenty seconds were reserved on every analytical run to write the answer up,
and the only way that reserve was ever reached was an exception: when the
action window closed, the next call raised DEADLINE_EXPIRED and the run
published nothing. The reserve was held back to write an answer and then no
answer was written.

`Orchestrator._demand_an_answer_if_time_is_short` now hands it over as one
bounded turn with only `finalize_response` on it, telling the analyst what it
has and how long it has. Nothing is fabricated: where an analysis executed,
the turn writes a concise answer from evidence that already exists; where none
did, it says what the question was understood to mean and that the run stopped
before it could be answered.

## 8. Live failure 4 — schema resolution answering a value question

**Reproduced.** "and within prject finance?" sent a live run round the
catalogue asking for `product_name`, then `product_category`, then
`facility_type`, then `product`, then `product_code`. It had `facility_type`
in the first call.

**Root cause.** SCHEMA RESOLUTION ("which field?") and VALUE RESOLUTION
("which category value?") are different questions, and only one of them had a
mechanism. Nothing could decide that the string the reader typed was the
string the book spells `project_finance`, so the run kept looking for a field
that would obviously contain it — and invented field names when none did.

**Fixed.** `values.py` builds a bounded index of the values each governed
categorical dimension actually holds, keyed by a normalised form and a small
authored alias table, and reads the reader's spelling against it:

- exact for case, spaces, underscores, hyphens and punctuation — no fuzzy
  matching is involved in reading `Project-Finance` as `project_finance`;
- a bounded near match for a typo, taken only when it is uniquely strong
  (similarity ≥ 0.82 AND ≥ 0.08 clear of the runner-up);
- a named question where the phrase is genuinely more than one real value:
  "finance" is Project, Trade and Asset Finance in this book, and choosing one
  of them is choosing the analysis.

A real value of the book outranks an authored alias. Nothing is ever resolved
to a value the release does not hold. High-cardinality fields are not indexed:
there is no useful "did you mean" across three thousand borrower names.

## 9. The resolution is in the run's semantics

Each resolution is recorded — an exact one as a `canonical_mapping`, a
corrected spelling as a `resolved_assumption` that reads as a correction —
whether or not the analyst repeats it, so the trace shows what was read and
what it was taken to mean, and a reader who disagrees can see exactly what to
disagree with.

The packet also carries `governed_values`: every low-cardinality dimension of
this release with the values it holds. That is about 3.1KB for Corporate and
1.3KB for Retail, and it is the answer to "which field holds this word", so
the analyst has no reason to go looking.

## 10. The Corporate book was not a corporate book

`v4-saudi-corporate-20m-v1` was 97 borrowers and 290 facilities. Every
consequence of that was invisible until somebody asked a real question of it:

- "EAD by sub-sector" returned rows holding a single obligor, so "sub-sector"
  and "borrower" were the same dimension wearing two names;
- the twenty largest exposures WERE a fifth of the book, so every
  concentration answer was trivially true;
- every latency figure was measured against a database small enough to fit in
  a cache line, so "fast" said nothing about the engine.

## 11. `v4-saudi-corporate-20m-v2`

| | v1 | v2 |
| --- | --- | --- |
| borrowers | 97 | **3,260** |
| facilities | 290 | **9,779** |
| parent groups | 52 | 1,614 |
| sectors | 13 | 13 |
| sub-sectors | 44 | **70** |
| facility types | 5 (Title Case) | **8 (`snake_case`)** |
| regions | 10 | 10 |
| rows | 19,340 | **651,940** |
| months | 20 (2025-01..2026-08) | 20 (2025-01..2026-08) |

Fingerprint `b4a85148c803846b`. Built in 16 seconds, byte-identical across
processes — every figure is a pure function of `(entity, month)` hashed with
SHA-256, never `hash()`, which Python randomises per process.

Facility types are the book's own identifiers: `term_loan`,
`working_capital`, `revolving_credit`, `trade_finance`, `project_finance`,
`overdraft`, `guarantee`, `asset_finance`. The reader never has to type them
that way — `values.resolve` reads "project finance", "Project-Finance" and
"prject finance" as the one identifier — and every surface shows the reader's
form.

## 12. Cohort stories, and why they are subtracted

A book whose only story is "these three sectors got worse" answers one
question. Each name now carries one of six authored trajectories:

| cohort | names | what it does over the window |
| --- | --- | --- |
| stable | 1,957 | its sector's story and nothing else |
| improver | 493 | improves against its sector |
| early deterioration | 414 | nothing for half the window, then turns |
| severe deterioration | 199 | deteriorates throughout |
| cure | 125 | goes late, peaks around month fourteen, recovers |
| default | 72 | goes to ninety days past due and stays |

The cohort shape is added with the book's OWN WEIGHTED MEAN SUBTRACTED.
Cohorts redistribute risk; they do not add it. Added raw, forty-two per cent
of the names were in a cohort that only ever pushes upward, and the
portfolio's ECL coverage went from 3.5% to nearly 8% without any sector
having a new story. What changed is the DISPERSION.

The result: 401 facilities have been ninety days past due at some point and
249 of them are current again; 871 have been Stage 3 and 295 are not now.
"Did anything recover?" has an answer.

## 13. The book is still a book a credit reader would accept

Last month of the window, by exposure: Stage 1 65.0%, Stage 2 29.1%, Stage 3
5.9%, ECL coverage 4.12%. First month: 89.7% / 8.4% / 1.9%, coverage 1.37%.
A portfolio under pressure, not one in workout — which matters, because a
generated book whose last month is a third impaired teaches a reader to
ignore the stage column.

## 14. v1 is not mutated

`v4-saudi-corporate-20m-v1` stays published and readable — an analysis saved
against it names it — and still verifies against the fingerprint it was
published under. The generator now REFUSES to rebuild it by name: it would
hand back different bytes under a name that already means something else,
which is the one thing an immutable release id exists to prevent.

## 15. Retail

`v4-saudi-retail-20m-v1` is unchanged: 9,000 customers, 12,000 accounts,
611,474 rows, fingerprint `52e470651214cb80`. §22 asks for at least 3,000
customers and prefers keeping at least 9,000; it already has them, and
rebuilding a release that meets the requirement would only break every saved
analysis that names it.

## 16. Performance with the large books

Every figure below is from `test_release_scale.py`, which measures the
published releases rather than a fixture.

| | budget | Corporate | Retail |
| --- | --- | --- | --- |
| grouped aggregate over the latest month | 1.0s | passes | passes |
| three-way join across the whole 20-month window, top 50 | 2.0s | passes | — |
| opening the book (session materialisation) | 10.0s | passes | passes |
| building the value index (once per release) | — | 106ms | 75ms |

## 17. Everything recomputed against the new release

Corporate oracles C01–C12, the attention feed, the ECL highlights, the
seeded case file, the schema browser, the exports and the dual-domain
performance evidence all read the release rather than a recorded number, so
all of them moved with it. Three oracles had to change: C05, C07 and C11 asked
an unbounded "which are the biggest" question of a three-thousand-borrower
book, and comparing a capped preview against a complete oracle finds a
difference that is the cap. They ask for a top twenty-five now, and the oracle
is sliced the same way.

## 18. A thread now opens on something

Investigate Further put the reader on a page holding a headline and an empty
box. The card already carried questions the release can answer, computed when
the card was computed, and none of them reached the screen.

Every card now carries five, and each one names a field the book holds and a
month it has. The drill-down is offered only where the book records a level
below the segment; the cross-cut names a real second dimension of the same
relation. `GET /threads/{id}` serves them as `opening_questions` while the
thread is empty, and a thread nobody seeded gets the book's own five.

## 19. And it does not end at a dead end

A validated answer may legitimately carry no suggestions — the analyst is not
required to invent them, and validation drops any naming a field the release
does not hold. The reader then reached the end of a good answer with nowhere
to go. `chipsToShow` now falls through: the answer's own suggestions, else the
book's deterministic follow-ups, else — while the thread is empty — the
opening set. Never two at once, and never a model call.

## 20. The Ask next strip

It sat in the transparent top of the composer's gradient with
`items-center`, so a chip that wrapped to two lines overlapped the transcript
showing through behind it, and the label collided with the first chip at
narrow widths. It is now an opaque band: its own background, the label on its
own row, and the chips aligned to the TOP of their row so a wrapped chip grows
downward into the band's padding rather than over its neighbour. The browser
suite measures the geometry — background colour, label/chip separation,
pairwise chip overlap, containment within the band — rather than trusting it.

## 21. One figure, one way, on every surface

`test_money_and_period_format.py` drives a real run in each book and inspects
the prose, the figure list, the table, the chart labels, the tooltip's own
`display` map and the exported markdown. A monetary amount shows no decimal
places on any of them, and the figure in the prose is the figure in the table.

## 22. One period, one way

No surface of an answer, no attention card, and no exported document names a
quarter. Two things were found doing it:

- `Header.reporting_frequency` defaulted to `"quarterly"` and nothing ever
  set it, so every published answer from a monthly book travelled with a
  header saying the book was quarterly — into the thread header, the saved
  analysis, the export footer and every shared link;
- `latest_populated_quarter` was the field NAME. It is
  `latest_populated_period` now, with the old key still served so a saved
  header is not broken.

And the exported document said which book, which release and which day it was
exported, and never which MONTH the figures described. The periods now come
from what the run executed.

## 23. A fingerprint that hashed nothing

`release.fingerprint` hashed a directory the domain releases are not in.
Hashing an empty directory returns `e3b0c44298fc1c14…`, the SHA-256 of the
empty string: a valid-looking fingerprint that identifies no release and
matches every other book's header. Both books were stamping it on every
published answer and every export. It reads the digest the release recorded
when it was published.
