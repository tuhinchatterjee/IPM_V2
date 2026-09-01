# Scorecard CBUAE-Aligned Validation Report

The thirteen-section report, the evidence workbook behind it, and the claim it
is careful not to make.

---

## 1. The claim, stated exactly

The report's structure is **aligned with the CBUAE Model Management Standards
and Guidance section list**. That is a claim about the section list.

**CreditProbe does not provide regulatory certification or a legal compliance
opinion, and nothing in the report constitutes one.** The disclaimer saying so
is stored with every report record rather than rendered from a template at
download time — a disclaimer that lives only in a template is one refactor
away from not existing.

Structure version: `cbuae-mms-mmg-aligned-1.0.0`.

---

## 2. The thirteen sections

| # | Section |
|---|---|
| 1 | Cover and document control |
| 2 | Executive summary |
| 3 | Model purpose, scope and usage |
| 4 | Governance and independence |
| 5 | Development and validation data |
| 6 | Model design and conceptual soundness |
| 7 | Implementation verification |
| 8 | Quantitative validation |
| 8.1 | Data and sample diagnostics |
| 8.2 | Discriminatory power |
| 8.3 | Calibration and accuracy |
| 8.4 | Stability and robustness |
| 8.5 | Sensitivity and variable diagnostics |
| 8.6 | Segment performance |
| 8.7 | Cut-off and decision performance |
| 8.8 | Overrides and usage |
| 8.9 | Challenger comparison |
| 9 | Monitoring review |
| 10 | Findings and severity |
| 11 | Model risk assessment |
| 12 | Overall validation conclusion |
| 13 | Appendices (equation, WoE bins, definitions, dictionary, evidence index) |

---

## 3. Coverage

Eighteen required topics map to the sections that address them
(`report.COVERAGE`). A topic counts as addressed only if its section **exists
and has content** — a report can contain the word "calibration" under an empty
heading and have addressed nothing.

The coverage result travels with the report to the screen, so a hole is
visible before the report reaches a committee. A test hollows a report out to
prove the check can fail.

---

## 4. What an unavailable section says

A section that could not be computed prints **the engine's own reason** and no
table.

Quoted rather than restated: the dashboard already decided the section was
unavailable and said why, and a second copy of that sentence is a second place
for it to drift.

On an open month, sections 8.2 and 8.3 read *"Discrimination compares
predicted against actual, and 2025-03's performance window closes 2026-03.
There is no realised outcome to compare against. The latest fully matured
month is 2025-01."* — never a table of dashes, and never a zero.

---

## 5. Sections that decline

Two sections decline by design in this workspace:

- **8.7 Cut-off and decision performance.** No approved cut-off is recorded.
  A cut-off invented for a report would make every acceptance rate in it
  fictional.
- **8.8 Overrides and usage.** Not captured here. It is not estimated from the
  score distribution.

Both say so. Neither is omitted.

---

## 6. Limits in the report

Section 9's table has five columns: Metric, Observed, Limit, Status, **Source**.

Without the source a reader cannot tell a demonstration default from a
regulator's number, and the note under the table says the seeded cut-offs are
not regulatory requirements. A critical check asserts every row carries a
source.

---

## 7. The evidence index

Section 13.5, and sheet one of the workbook.

Every figure the report names carries: the section, the label, the metric, the
value, the method, the period, the model version, the validation state, and
**the workbook sheet it can be checked in**. "Where does 0.7104 come from?"
has an answer that is not somebody's memory.

---

## 8. The evidence workbook

Eleven sheets: `EVIDENCE INDEX`, `METRICS`, `MONTHLY HISTORY`, `VARIABLES`,
`PSI`, `CSI`, `EQUATION`, `WOE BINS`, `IMPLEMENTATION`, `FINDINGS`,
`REGULATORY MAPPING`.

`MONTHLY HISTORY` marks each month's **outcome maturity** beside its blank
default rate, because a blank on a matured month and a blank on an open month
are opposite facts.

`REGULATORY MAPPING` maps topics to the report sections that address them. It
is a mapping of structure, not an assertion that any threshold in the report is
a regulatory requirement.

---

## 9. The content hash

§56's hash covers **sections 2 to 13** and excludes the cover.

The document-control table names who generated the report and when, so hashing
it would make every regeneration a new hash and the number would only answer
"was this run twice?". Excluding it makes regeneration answerable: *has the
assessment changed, or is this the same report with a new cover?*

---

## 10. Filenames and downloads

```
CreditProbe_<SCORECARD_TYPE>_<MODEL>_<PERIOD>_Validation_Report.docx
CreditProbe_<SCORECARD_TYPE>_<MODEL>_<PERIOD>_Validation_Report.xlsx
```

Generating and downloading are separate acts. Generating records what was
reported, to whom, with what disclaimer and against which run; downloading
reproduces it. A single button that did both would leave no record of a report
somebody looked at and did not save.

Downloads are rebuilt from the same deterministic inputs rather than served
from a stored blob: a download that could disagree with the screen it was
started from is a worse failure than a slow one. The response carries
`X-CreditProbe-Content-Hash`, and a test asserts it matches the screen's.

---

## 11. Nothing is recalculated by a model

Every figure comes from a dashboard the deterministic engine already built.
§51's "do not ask the LLM to recalculate numbers" holds because there is
nothing in the report builder to recalculate with — it has no arithmetic
beyond formatting and makes no provider call.
