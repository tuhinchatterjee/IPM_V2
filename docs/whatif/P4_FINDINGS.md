# P4 — what building Delta and Method 3 actually turned up

Findings from implementing sections 10, 12 and 13 against the accepted books,
with the evidence for each. Everything here was measured or reproduced; none
of it is inference from a schema comment.

---

## 1. Eight defects, found by the tests rather than after them

| # | Where | What was wrong | How it was caught |
|---|---|---|---|
| 1 | `rules.compile_rules` | Its docstring promised to refuse an undeclared conflict and it did not. `order()` would have sequenced two rules on one field, and the sequence would have decided the answer — §5.2's silent "more specific wins" through the back door. | Writing the test for the promise |
| 2 | `rules.compile_rules` | Dead `by_field` bookkeeping, computed and discarded | Reading it to write #1 |
| 3 | `preview.confirm` | Tried to jump the state machine from `DRAFT` to `PREVIEW_READY` | `test_whatif_preview.py` |
| 4 | `userdefined.target_total` | **An elasticity was divided by a hundred twice**, turning a 28% stress into a 0.28% one. A plausible enough number that nothing downstream would have flagged it. | `test_an_elasticity_acts_on_a_stated_driver_move` |
| 5 | `sql.moved_value` | Emitted `col * (1 + 20 / 100)`, and DuckDB widens integer division to DOUBLE: `0.02 * (1 + 2.5/100)` came back as `0.020499999999999997`. Fixed by doing every conversion in Decimal and emitting one exact literal. | The operation-by-operation agreement grid |
| 6 | `delta._delta_fields` | Refusals named `ecl_sar_mn`, `sector`, `utilisation_pct` and `write_off_sar_mn` as fields Delta handles. `methods` defaults to both methods on every entry, so published-but-immutable columns carried DELTA. A reader following the refusal would have asked for something refused again for a different reason. | `test_a_refusal_names_only_fields_a_scenario_could_actually_ask_for` |
| 7 | `fields.limit_sar_mn` | Marked Delta-capable in both books. It enters no published ECL input in either — Corporate publishes EAD as its own column, Retail sets `ead = balance` outside Credit Card — so "cut limits by 20%" would have returned a change of **exactly zero**, a wrong answer wearing a right answer's clothes. | Working out what `plan()` should do with it |
| 8 | `ledger` default tolerance | `EXACT` as the default for a ledger whose numbers come back from a DOUBLE engine. Now `CURRENCY` (1e-4 SAR mn) for the summation checks, with `EXACT` kept for Decimal-only ledgers — and the "an untouched row moved by exactly zero" check still admits nothing at all. | Running the compiled SQL against the real book |

Defect 4 is the one worth dwelling on. It was not caught by any structural
check, any type, or any review of the code — only by an oracle that said what
the number should be. Section 17.1 asks for exactly that, and this is what it
buys.

---

## 2. Three measured facts about the books

### The zero-baseline branch has no real row to exercise it

```sql
SELECT count(*) FROM corp_facility_quarter WHERE pd_pit_12m = 0;   -- 0
SELECT count(*) FROM retail_account_month  WHERE pd_pit_12m = 0;   -- 0
```

Neither book carries a single zero-PD row, so §10.3's case — the one that
must be UNSUPPORTED rather than divided by an epsilon — **cannot be reached
by any cohort of real facilities.** A mutation that made a zero baseline
divide anyway passed every real-data test.

It does not now. Section 17.1's four hand rows are loaded into DuckDB as a
fixture relation and the same generated SQL is run over them, so the branch
is covered in the database and not only in Python.

### The NULL multiplier is load-bearing only for CCF, and here is why

For PD, LGD and EAD a zero baseline forces ECL to zero — ECL is their
product — so whether the multiplier is `NULL` or `1`, the row's value is the
same and only its label differs.

CCF is the exception. A facility with drawn 100,000, undrawn 50,000 and EAD
100,000 has a derived CCF of exactly zero and an ECL that is not zero. There
the choice changes a published number: with `NULL`, a scenario that also
moved LGD keeps the row at its baseline; with `1`, the row is scaled by the
LGD alone and published as though the whole scenario had applied, when one of
its two instructions could not be carried out.

`test_an_unsupported_factor_stops_the_whole_row_not_just_itself` is that
case, and the mutation that removes the `NULL` now fails.

### Arithmetic runs in DOUBLE, and the tolerance is declared rather than assumed

Every numeric column in both books is `DOUBLE`, so DuckDB sums in DOUBLE. On
the Corporate book that is noise of order
`sqrt(384,009) x 2.2e-16 x 7,075,662 ~= 1e-6` SAR million.

`ledger.CURRENCY` is `1e-4` SAR million — a tenth of one riyal on a book of
seven billion. Two orders of magnitude above the noise, four below the
smallest figure a reader sees. It applies to the **summation** checks only.
"An unaffected row moved by exactly zero" gets no tolerance, because those
rows carry their baseline through the SQL verbatim and there is nothing for a
floating-point argument to excuse.

---

## 3. Two architectural facts that saved core changes

**`WHAT_IF` is already in `contracts.OWNERS`.** The accepted intent
vocabulary at `contracts.py:52-54` already names this capability, so a
scenario turn declares an owner the runtime knows. One fewer protected-file
change than this might have needed, and
`test_the_accepted_contract_already_names_this_owner` keeps it that way.

**Attribution needs no thirteenth operation.** `derivation.py`'s closed set
of twelve has no attribution operator, so contributions reach a published
answer as artifact **rows** that `sum` and `share_of_total` act on — the same
way every other figure in this Cockpit is published. `ledger.Contribution`
exists for exactly that.

---

## 4. Where §13.2's bridge landed

Both views are implemented and both are named, because O04 says they are
different numbers and *"cannot be mixed"*:

| View | A's PD | A's LGD | Passes needed |
|---|---|---|---|
| `ledger.attribute` (sequential, the default) | 1,600 | 960 | 1 |
| `ledger.shapley` | 1,680 | 880 | 2^n |

Sequential telescopes, so its bars sum to the headline by construction and
one population pass produces them. Shapley is order-independent and splits
the 160 interaction evenly, and needs all 2^n coalitions — an average over a
subset is a different quantity with the same name, so supplying one is
refused. Its weights are carried as exact `Fraction`s and converted once, so
a Decimal division by six never lands a repeating third in a currency figure.

---

## 5. What is still not built, and why

| Item | Reason | Where |
|---|---|---|
| §7 MEV sensitivity library | No macro variable exists in either book. O07's arithmetic is pinned; the slope has nothing to attach to. | P5 |
| §11 ML emulator | Published ECL is closed-form `ead x pd x lgd`; §11.1 forbids calling that emulation. O09's anchoring arithmetic is pinned and Method 2 reports `MODEL_NOT_READY`. | P7 |
| Overlay split | Neither book publishes modelled against overlay, and `ecl.py` refuses to invent it. The arithmetic is in `delta.scale_row` and O08 pins it; the column defaults to zero. | A book that carries it |
| Tornado chart, Excel export | Closed chart union; `openpyxl` already pinned | P9 |
| Browser journeys J01–J14 | Need the candidate running | P10 |
