# The human teaching corpus

> **No client Q&A file is committed to this repository, and none ever should
> be.** The importer is here; the corpus belongs in the bank's deployment.
> Do not upload real client questions and answers into a development
> environment, and do not attach them to an issue or a pull request.

## What it is for

A bank has hundreds of questions its credit team already knows the right
answer to. Those are the most valuable teaching material CreditProbe can have,
and they arrive as a spreadsheet, not as an API call. This is the governed
path from that spreadsheet into the teaching library — with a review step that
cannot be skipped.

## The template

Fifteen columns. Two are required.

| Column | Required | What it holds |
|---|---|---|
| `question` | **yes** | The question, in the words somebody would actually type. |
| `expected_answer` | **yes** | What a correct answer says. Prose, not a number. |
| `family` | no | The teaching family. Blank: CreditProbe proposes, a reviewer confirms. |
| `objectives` | no | What a correct answer must settle. |
| `concepts` | no | The governed concepts involved. |
| `datasets` | no | The governed datasets a correct answer reads. |
| `period` | no | The reporting period or window. |
| `grain` | no | What one row should be: portfolio, segment, customer, facility. |
| `expected_outcome` | no | `EXECUTE`, `CLARIFY`, `UNSUPPORTED` or `FAIL`. Blank means `EXECUTE`. |
| `difficulty` | no | `FOUNDATIONAL`, `INTERMEDIATE`, `COMPLEX`, `EXPERT`, `ADVERSARIAL`. |
| `risk_level` | no | `LOW`, `MEDIUM`, `HIGH`, `CRITICAL`. |
| `citation` | no | Where the expected answer comes from. |
| `forbidden` | no | What a wrong-but-plausible answer would say. |
| `author` | no | Who wrote it, for the reviewer to ask. |
| `notes` | no | Anything the reviewer should know. |

`expected_answer` is prose deliberately. A stored figure is correct for one
quarter and wrong for every quarter after it; the corpus teaches **structure** —
which datasets, which grain, which concepts, what must be settled — and the
figures come from the governed engine at answer time.

`forbidden` is the most useful optional column in the file. It is what lets a
case distinguish a right answer from a convincing substitute, and a corpus
without it teaches recognition rather than discrimination.

Column headers are matched through an alias table, so `Question`,
`question_text` and `Q` all land in the same place. A bank's own spreadsheet
should not have to be rewritten to be importable.

## Formats and limits

XLSX, CSV and JSONL. **5,000 rows maximum** per import — a limit, not a
target: an import nobody can review is not an import.

## Preview before import

`POST /api/v1/teaching-corpus/preview` reports every row as one of four
outcomes before anything is written:

| Outcome | Meaning |
|---|---|
| `ACCEPTED` | The row will become a case. |
| `REJECTED` | The row cannot become a case. The reason is stated per row. |
| `DUPLICATE` | The same question is already in the library. |
| `CONFLICT` | The same question is present with a different expected answer. |

`CONFLICT` is separated from `DUPLICATE` on purpose. A duplicate is noise; a
conflict means two people in the bank disagree about the right answer, and
that is worth a conversation before either version is taught.

`error_workbook()` returns the rejected rows with their reasons in the same
shape as the input, so the file can be fixed and re-submitted rather than
re-typed.

## What an imported case arrives as

Every imported case arrives:

* `SME_REVIEW_REQUIRED` — never approved, never retrievable;
* authored by `HUMAN`;
* sourced as `CLIENT`.

It is **not** production-retrievable until a reviewer approves it. An import of
500 cases changes nothing about how CreditProbe answers until somebody has
read them.

Where a case is expected to execute, the importer assembles a stated
analytical plan contract from the row's own datasets, concepts and grain,
marked:

> `"source": "stated by the client corpus… to be confirmed in review"`

That phrasing is the point. The contract is what the client *said*, held
separately from what the platform has *verified*, and the review step is where
the two are reconciled.

## The API

```
GET  /api/v1/teaching-corpus/template     the fifteen columns, with guidance
POST /api/v1/teaching-corpus/preview      four outcomes per row, nothing written
POST /api/v1/teaching-corpus/import       write, all SME_REVIEW_REQUIRED
```

## Review

Imported cases join the same review workbench as every other teaching case,
and the same human-review pack. Approval is what makes a case retrievable;
nothing else does.

## The rule this exists to protect

The teaching library shipped in this repository contains **no approved,
production-retrievable cases**. Everything in it is `AUTO_VALIDATED`, which
means a machine checked its shape and no human has vouched for its content.
The corpus a bank imports is the first material that could become approved,
and it becomes approved one reviewed case at a time.
