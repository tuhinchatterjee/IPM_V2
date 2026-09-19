# Denomination: what `…-p1` got wrong, and what `…-p5` publishes

## The defect

Revision `cockpitdata-r1.2.0-c1.0.0-s20260910-p1` divided every monetary
column by 1,000,000 and declared `amount_scale = "million"`. Verified on the
demo Mac against the source book for 2026-08:

| Quantity | Source (riyals) | `p1` projection | ratio |
|---|---|---|---|
| EAD | `ead_base_sar` 6,425,968,606.83 | `ead_sar_mn` 6,425.97 | 1.0e-06 |
| ECL | `ecl_final_sar` 58,608,354.44 | `ecl_sar_mn` 58.61 | 1.0e-06 |
| Balance | `gross_carrying_amount_sar` 6,388,268,768.90 | `balance_sar_mn` 6,388.27 | 1.0e-06 |

That contradicts the approved plan §3, which requires the projection to
preserve SAR units so account-level values do not round to zero under the
frozen display policy. The conversion was introduced during implementation
and recorded only in a module docstring and a commit message; it was never
brought back for approval. The plan was right and the implementation was not.

`p1` is retained as failed evidence. It is not mutated, rewritten or deleted.

### Where it came from

| Site | Code |
|---|---|
| `semantic_map.py` | `SAR_PER_MILLION = 1_000_000.0`; `AMOUNT_SCALE = "million"` |
| `semantic_map.py` | `_money(series) -> series.astype("float64") / SAR_PER_MILLION` |
| `projection.py` `_apply` | `if unit == "rcy": return sm._money(column)` |
| 21 mappings | every money column declared `unit="rcy"`, so every one was divided |

## Why a simple relabel was not available

The frozen engine addresses retail money columns by name in *executable* code,
and states their denomination in prose a release cannot reach.

**Executable — a rename breaks these:**

| Site | Effect of a rename |
|---|---|
| `ecl.py:275,276,305,308,386` | DuckDB binder error. `routes.py:1005` catches only `EclUnavailable`, so `/ecl` returns an unhandled 500 |
| `attention_v2.py` retail families and `_highlights` (924-945) | same, on `/attention` |
| `attention_v2._check_families()` (import time) | `ValueError` against the static `schema.py`; the module does not load |
| `semantics.measures()` line 471 | every retail money term silently `continue`d out of the compact packet |
| `investigation.py:57` `_ALWAYS` | silently dropped |

**Prose — these say "million" whatever the manifest says:**

| Site | What it asserts |
|---|---|
| `semantics.py:244-260` | *"Exposure at default, in SAR million."* — in the packet the analyst reads |
| `attention_v2.py:218,235` | literal unit `"SAR million"` on the two retail ECL families |
| `export.py:225` | `amount_scale=… or "million"` — an **empty** scale makes the export footer assert millions |

So `amount_scale = ""` is a false declaration, not a neutral one, and it would
also mark the header `unverified` (`release.py:220`).

**The release-level scale is therefore not a free choice.** `ecl.py` and
`attention_v2.py` sum the `*_sar_mn` columns and label the result with
`scope.money_unit`; the scale has to be the denomination those columns are
actually in.

## What `p5` publishes

Both denominations, each true about itself, with **no protected-core edit**.
The core diff remains exactly `domains.py` (C1) and `catalog.py` (C2).

| | `*_sar_mn` | `*_sar` |
|---|---|---|
| Value | source ÷ 1,000,000 | the source figure, undivided |
| Declared unit | `rcy` | `SAR` |
| Resolves to | the release's `SAR million` | `SAR`, whatever the release scale is |
| Read by | `ecl.py`, `attention_v2.py`, `semantics`, `investigation` | facility- and customer-level answers |
| A facility balance reads | `SAR 0 million` | `SAR 3,213` |

The seam that makes this possible is `display.unit_for_field`: it resolves
`rcy` to the release's own denomination and returns any other declared unit
verbatim. `display.classify("SAR")` matches the money pattern, so a riyal
figure is governed by the same zero-decimal policy — it simply has no scale
word to round away.

21 money columns, 21 twins, generated from the authored millions mapping by
`semantic_map.with_riyals` so the pair cannot drift in source, label, group or
additivity. Each definition names the other and says which grain it belongs
at. Release size 409 MB → 509 MB; 275 → 296 fields.

## The gates (all green on `p5`, all 25 months)

| Gate | Where | What it proves |
|---|---|---|
| G1 source reconciliation | `gates.check_source_totals` | every riyal column sums **exactly** to its source column, re-read from the book by a second route. Run on every month at publish time |
| G2 truthful manifest | `test_denomination.py` | `amount_scale == "million"`; every `*_sar_mn` declares `rcy`, every `*_sar` declares `SAR`; `release.header(...).unverified == ()` |
| G3 no rendering collapse | `test_denomination.py` | 200 latest-month account rows: every positive riyal value renders non-zero, and the millions column is asserted to collapse — the reason the twin exists |
| G4 portfolio totals | `test_denomination.py` | through the engine's own session: `SUM(ead_sar)` matches the source and `SUM(ead_sar_mn)` matches it ÷ 1e6 |
| G5 frozen paths | `test_denomination.py` | ECL panel and movement return with `money_unit == "SAR million"`; the money SQL of eight of nine attention families binds and executes; all six canonical money measures resolve |
| pairwise | `gates._denomination` | publication refused if any pair is not one quantity. A negative control asserts the `p1` defect would be caught |

`check_oracles.py --release …-p5`: **5 of 5** independent cases agree. Q01 and
Q03 now assert both denominations, and Q03's coverage ratio is computed from
the riyal columns so it is checked against an oracle that used neither.

A float sum is not bit-reproducible across machines, so the pinned totals are
compared at a relative tolerance of 1e-12. The **exact** equality that matters
— source column to projected riyal column on one machine — is asserted as
equality, because no arithmetic was supposed to happen at all.

## Two limitations, measured rather than assumed

**1. The compact packet does not name the riyal columns.** `context.build`
carries the frozen canonical measure table, which names `ead_sar_mn` and
describes it as "in SAR million", plus a fixed list of release keys. It
carries no manifest field or relation description at all. So the twins are
discoverable only through `inspect_catalog`, where each definition
cross-references the other. Consequence: a facility-grain money question
answered without a catalogue read will render `SAR 0 million`. Readiness is
`sufficient` for portfolio questions, so the analyst's default first action is
`execute_analysis`. No adapter-controlled free-text field in the packet is
designed to carry a column-selection rule, and stuffing one into `origin` or
`not_client_data` would be a workaround rather than a fix.

**2. The Home attention feed is unavailable on this book, for an unrelated
reason.** `attention_v2._retail_families()` includes `segment_score_decline`,
which reads `retail_customer_month.score_migration`. This book publishes a
behavioural score at FACILITY grain and no customer-level migration, so the
projection has no column to put there. `attention_v2.compute()` has no
per-family guard, so the whole feed raises `BinderException`. Present in every
revision including `p1`; nothing to do with denomination; surfaced by G5.
Recorded as `xfail(strict=True)` so closing the gap forces the test to be
promoted rather than left stale.

The source does publish `behavioural_score_previous_month` "so a movement can
be read without joining to last month", so a facility-grain migration is
derivable. Whether to derive a customer-grain `score_migration` from it is a
contract decision and is not taken here.
