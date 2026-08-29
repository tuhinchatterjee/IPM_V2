# Regulatory circular knowledge

> **No circular was uploaded here.** This describes the capability. The bank's
> own circulars are ingested in the bank's own deployment; original documents,
> extracted text and confidential sources are not committed to this
> repository and never will be.

## What the capability is for

A credit answer that mentions a regulatory position must be able to say
*which* circular, *which* clause, and *whether it was in force on the
reporting date*. Everything below exists to make an uncited regulatory claim
impossible rather than unlikely.

## 1. Ingestion

Six accepted formats: `PDF`, `DOCX`, `XLSX`, `CSV`, `TXT`, `HTML`.

Extraction is per format, and — this is the point — it **never returns empty
text silently**. Two failure states are distinguished, because they need
different actions from different people:

* `EXTRACTION_UNAVAILABLE` — no extractor is installed for this format. An
  operations problem.
* `NEEDS_OCR` — the document is a scan and carries no text layer. A document
  problem.

A pipeline that returns "" for both, and then reports a circular with zero
rules, is how a bank ends up believing it has ingested a circular it has not.

The original bytes are stored **write-once, keyed by SHA-256**, up to 64 MB.
`verify()` re-hashes on read, so a quotation can be proved against the
document it came from. Tenant names are sanitised — dots stripped — because a
tenant called `../../etc` is not a tenant.

### Structure

`sections_of()` finds headings by shape (short, no terminal full stop) rather
than by numbering alone; without that test, numbered provisions were consumed
as headings and a circular produced seven sections and no rules at all.

`rules_of()` classifies each provision into four kinds:

| Kind | What it is |
|---|---|
| `OBLIGATION` | Something a bank must or must not do. |
| `DEFINITION` | What a term means for the purposes of the circular. |
| `THRESHOLD` | A number with a unit: a percentage, a count, a period. |
| `EXCEPTION` | A carve-out from an obligation. |

Thresholds carry their unit: `%`, `per cent`, `percent`, `basis points`,
`bps`, `days`, `months`, `years`, `times`, `x`.

## 2. Confidentiality

Three classes: `PUBLIC`, `RESTRICTED`, `CONFIDENTIAL`. Only `PUBLIC` is
shareable. Retrieval filters by tenant, then confidentiality, then status,
then date — in that order — and an exclusion is **reported**, never silent. A
reader who is told nothing was found, when in fact something was found and
withheld, has been misled.

## 3. Review, and the ten statuses

```
UPLOADED -> EXTRACTED -> IN_REVIEW -> REVIEWED -> APPROVED
         \-> EXTRACTION_UNAVAILABLE                  |
         \-> NEEDS_OCR                               +-> SUPERSEDED
         \-> REJECTED                                +-> WITHDRAWN
```

Only `APPROVED` and `SUPERSEDED` are retrievable. Extraction proposes; a named
regulatory SME disposes, with one of four decisions: `APPROVE`, `REJECT`,
`AMEND`, `DEFER`. The review queue is thresholds-first, because a wrong number
is the error that reaches a report.

## 4. As-of retrieval, supersession and conflict

* `in_force_on(date)` is **fail-closed**: a circular with no effective date is
  not in force on any date. An undated document is not a document whose dates
  are all valid.
* `supersessions()` and `apply_supersession()` track what replaced what.
* `conflicts()` finds rules in force on the same date that disagree. Where two
  conflict, **both are shown and neither is chosen.** Picking one silently is
  the single most expensive thing this module could do.

## 5. Regulatory Assurance

Eight checks. **Five are critical**, and a critical failure blocks the answer:

| Check | Weight |
|---|---|
| `cited` | CRITICAL |
| `in_force` | CRITICAL |
| `reviewed` | CRITICAL |
| `original_intact` | CRITICAL |
| `release_active` | CRITICAL |
| `conflict_declared` | MANDATORY |
| `confidentiality_respected` | MANDATORY |
| `supersession_checked` | ADVISORY |

`release_active` was MANDATORY first. That made an answer produced with **no
Regulatory Knowledge Release at all** report `ok` — a corpus nobody had
reviewed, passing. It is critical now, and the test that holds the line is
named for the five rather than counting them.

## 6. Releases

A Regulatory Knowledge Release fixes exactly which approved circulars and
rules an answer may quote from. It is fingerprinted over its contents, so two
releases with the same corpus have the same fingerprint and a changed corpus
cannot reuse one.

`activate()` **refuses a sole-reviewer approval**: the approver may not be the
only person who reviewed it. Rollback restores the previous release by one
recorded action.

## 7. The API

```
GET  /api/v1/regulatory/capability          which extractors are installed
GET  /api/v1/regulatory/report
POST /api/v1/regulatory/circulars           ingest
GET  /api/v1/regulatory/circulars
GET  /api/v1/regulatory/circulars/{id}
GET  /api/v1/regulatory/review-queue
POST /api/v1/regulatory/circulars/{id}/rules/{rule_id}/review
POST /api/v1/regulatory/circulars/{id}/approve
POST /api/v1/regulatory/releases
GET  /api/v1/regulatory/releases
POST /api/v1/regulatory/releases/{id}/activate
POST /api/v1/regulatory/releases/rollback
POST /api/v1/regulatory/ask                 retrieve, cite and assure
```

## 8. Verifying it locally

```powershell
.\scripts\verify-live-ai.ps1 -RegulatoryCritical
```

Deterministic; makes no provider call; runs without a key. It checks that an
extractor is installed for every accepted format, that the five critical gates
are still the five named above, that a percentage threshold is extracted as a
rule, and that an undated circular is not in force.

## 9. What must never be committed

Original circulars, extracted text, confidential sources, and any file the
bank classifies as `RESTRICTED` or `CONFIDENTIAL`. The capability is in the
repository; the corpus is not.
