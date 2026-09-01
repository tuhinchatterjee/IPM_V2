# The governed catalogue has one reader

`backend/metadata` is the single authority for what data CreditProbe holds.
Every surface that answers "what data is there?" reads it, and
`tests/metadata/test_reconciliation.py` fails when one of them grows its own
copy again.

## Why it exists

Three surfaces answered "how many data domains do you have?" and gave three
different numbers on the same deployment:

| Surface | Answered | Because it was reading |
|---|---|---|
| Data Builder screen | 45 | rows in the `data_domains` table, 38 of them empty leftovers from an earlier generator taxonomy |
| the analyst's `list_data_domains` tool | 5 | the file catalogue grouped by the domain each dataset names, so a heading with nothing under it did not exist |
| `backend.services.data_domains` | 7 | the business headings a credit officer is meant to see |

All three were reading something true. None was reading the same thing. A
product that disagrees with itself about its own catalogue cannot be trusted
about anything computed from it.

A fourth defect sat underneath: the catalogue had been renamed to the seven
business headings and the domain map went on looking only for the generator's
older spellings, so twelve governed datasets — `ifrs9_staging` among them,
sitting in a catalogue domain literally called "IFRS 9 / ECL" — were reported
as `Unmapped` and vanished from the screen.

## What it holds

```
backend/metadata/service.py     the catalogue, read once and cached
backend/metadata/questions.py   which questions are about the data
backend/metadata/answers.py     prose and a table, never a chart
backend/api/routers/metadata.py the same picture over HTTP
```

| Fact | Read from |
|---|---|
| domains | the business headings in `backend.services.data_domains` |
| datasets, grain, keys, purpose, fields, authoritative-for | the governed catalogue |
| periods | the published lake — a dataset declares a period FIELD; only the lake knows which periods exist |
| row counts | the published lake, so a draft dataset reports nothing rather than an estimate |
| relationships | the joins a steward has declared |

Nothing here reads a row of credit data. It reads how much of it there is.

Headings with nothing installed still appear. "No documents loaded" and
"documents not supported" are different answers, and grouping the catalogue by
the domain each dataset names cannot express the first.

## Routing a question about the data

`questions.read(question)` returns a typed `Request` or `None`. It runs before
the router and before any model call, for two reasons.

**Correctness.** "How many datasets are in the IFRS 9 data domain? List them."
was answered with *"20,500 count of connected group size at Q2 2026."* Nothing
downstream was broken — the analytical planner did exactly what it is for. It
should never have been asked.

**Cost.** A catalogue question has an answer that is already known. Paying a
frontier model to rediscover it is slower and less reliable than reading it.

The distinction the reader makes is the NOUN, not the verb:

```
"How many datasets are in IFRS 9?"      → the catalogue
"How many borrowers are in Stage 2?"    → the book
```

Both are the same English shape. `read()` returns `None` the moment it is not
confident, so its failure mode is the behaviour that existed before it.

### Kinds

`DOMAIN_LIST` · `DOMAIN_DETAIL` · `DATASET_LIST` · `DATASET_DETAIL` ·
`FIELD_LIST` · `FIELD_MEANING` · `PERIODS` · `ROW_COUNT` · `RELATIONSHIP` ·
`SUBJECT` · `PLANNING` · `TOTALS`

A subject-less question inherits the one the conversation is discussing, but
only for the kinds where a missing subject MEANS "the one we are discussing"
(`PERIODS`, `ROW_COUNT`, `FIELD_LIST`, `DATASET_DETAIL`, `RELATIONSHIP`).
"What datasets do you have?" is about the whole catalogue by construction.

## The answer shape

Prose first, then a table, and never a chart. The sentence answers the
question; the table is the evidence. A reader who asked "how many datasets are
in IFRS 9?" gets "Six." in the first line and the six rows underneath — not a
table they have to count.

Columns: Domain · Dataset · Business name · Relevant fields · Grain · Periods ·
Rows · Purpose.

A list of datasets is not a distribution and a domain is not a time series.
That decision lives beside the answer rather than in a chart selector reading
the result afterwards, which is what makes it hold for every metadata question
rather than for the ones somebody remembered.

## Relevance

"What data do you have about borrower liquidity risk?" answered with a climate
dataset, because `climate_risk` has the word "risk" in its name. `search()`
scores on two things: WHERE a term matches — a word in a dataset's name is
stronger evidence than the same word buried in the definition of one of its
forty fields — and how DISCRIMINATING that term is across the catalogue.

"risk" is in the stop list beside "data". This is a credit-**risk** platform:
the word is in the name of half the subject matter and separates nothing. A
term for a specific kind of risk — credit, climate, liquidity, concentration —
still carries, because that is the word doing the work.

`coverage()` also returns the terms nothing matched. A question naming three
things where the catalogue holds two is not answered by listing the two: "we
have no liquidity data" is the fact the reader needs, and it is the fact a
relevance ranking silently discards.

## Tests

`tests/metadata/test_reconciliation.py` — the Data Builder screen, the analyst
tool, the metadata API and the sentence a person reads all quote the same
counts.

`tests/metadata/test_metadata_questions.py` — 62 questions about the data, each
of which must be read as one, answered specifically, and rendered as a table
with no chart; plus 15 analytical questions that must NOT be captured, because
a router that catches metadata questions by catching everything has replaced
one defect with a worse one.
