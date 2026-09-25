# Data readiness

What the two published books hold, what they do not, and what that decides.
Section 3.2 asks for an inventory and section 3.1 for grain and cardinality
checks; this is both, measured against the parquet rather than read off a
schema comment.

Every figure below was computed from
`data/cockpit_v4_lake/v4-saudi-corporate-20q-v4/` and
`.../v4-saudi-retail-20m-v5/` and is re-checked on every run by
`tests/cockpit_v4/test_whatif_fields.py`. A dictionary nobody re-measures is a
wish list.

---

## 1. Shape

| | Corporate | Retail |
|---|---|---|
| Release | `v4-saudi-corporate-20q-v4` | `v4-saudi-retail-20m-v5` |
| Fingerprint | `e37236d0f6d4e494…` | `a1e797dcc73236b7…` |
| Origin | `SYNTHETIC_DEMO` | `SYNTHETIC_DEMO` |
| ECL-bearing relation | `corp_facility_quarter` | `retail_account_month` |
| Grain | facility × quarter | account × month |
| Periods | 20 quarters, 2021Q3 – 2026Q2 | 20 months, 2025-01 – 2026-08 |
| Rows | 384,009 | 584,372 |
| Entities | 21,918 facilities / 5,412 borrowers | 44,027 accounts / 26,000 customers |
| Published ECL | 7,075,662.58 SAR mn | 2,698.12 SAR mn |

Both are unbalanced panels — entities enter at origination and leave at
charge-off or maturity — so anything entity-fixed must handle ragged
histories. Both relations are unique on their declared key; checked.

---

## 2. The identity that decides the method

Published ECL is `ead × pd × lgd`, with the 12-month PD at Stage 1 and the
lifetime PD at Stages 2 and 3. Measured:

| Book | Published ECL | `ead × pd × lgd` | Difference | Worst row |
|---|---:|---:|---:|---:|
| Corporate | 7,075,662.5766 | 7,075,662.9109 | **−0.3343** (−0.0000%) | 0.0150 |
| Retail | 2,698.1228 | 2,645.0805 | **+53.0423** (+1.97%) | 1.1647 |

**Corporate is exact.** The residual is four-decimal rounding and nothing else.

**Retail's 1.97% is one population, not noise.** 1,837 written-off Stage 3
accounts carry `ecl = max(ecl, written_off − recovered)`, and they account for
53.0430 of the 53.0423 gap — the whole of it. Everywhere else the identity
holds.

This is what makes proportional Delta (§10.1) sound on this book rather than
merely defined: ECL is linear in PD, so a 20% PD rise really is a 20% ECL rise,
and no recomputation from parameters is needed.

It is also what makes §11 unbuildable here. The ECL label *is* PD × LGD × EAD,
and §11.1 forbids manufacturing that label and calling the result an emulator.
See `BASELINE_AND_EXTENSION_MAP.md` §3.

---

## 3. Inventory against §3.2

`P` published · `D` derivable exactly · `—` absent

| §3.2 input | Corporate | Retail | Note |
|---|:--:|:--:|---|
| Reported ECL | P | P | `ecl_sar_mn`; also 12m and lifetime as separate series |
| Modelled ECL vs management overlay | — | — | No split exists. `ecl.py:34-39` refuses to invent one |
| EAD | P | P | Corporate `drawn + undrawn × CCF`; Retail `= balance` except cards |
| Drawn exposure | P | P | Retail calls it `balance_sar_mn` |
| Undrawn commitment | P | — | Retail: derivable only as `limit − balance` |
| Limit | P | P | |
| Utilisation | P | P | A quotient; not directly movable |
| CCF | **D** | — | Corporate `(ead−drawn)/undrawn`, inverts EAD to 2.8e-14. Retail has none |
| PD 12-month | P | P | `pd_pit_12m`, point-in-time |
| PD lifetime | P | P | `pd_lifetime`; **the horizon length is not published** |
| PD through-the-cycle | P | — | Corporate only, at borrower grain |
| LGD | P | P | One definition; no downturn, no PIT/TTC split |
| Stage | P | P | 1/2/3, plus `sicr_flag` |
| Default / credit-impaired | P | P | `default_flag`; no default date |
| Remaining maturity | — | — | No maturity date anywhere |
| Effective interest rate | — | — | |
| Discount factors / term structure | — | — | No survival, no marginal PD curve |
| Economic scenario weights | — | — | One deterministic ECL per row |
| Corporate rating + scale | P | n/a | 19 grades + D, order published in the manifest |
| Behavioural score | n/a | P | 300–900, bands A–E |
| Application score | n/a | — | Does not exist; §8 forbids substituting the behavioural one |
| Sector | P | — | Corporate 14 / 75 sub. Retail has none; product is not a substitute |
| Product | P | P | |
| Geography | P | P | `region`, 10 / 8 |
| Collateral | P | P | Separate relations; Retail has no haircut |
| Delinquency / DPD | P | P | Retail adds two bucket columns |
| Restructuring / forbearance | P | — | Corporate, at borrower grain only |
| Vintage | P | P | |
| **Macroeconomic variables** | **—** | **—** | See §5 |

---

## 4. Eligibility, measured rather than assumed

§9.1: *"Missing inputs must produce reason-coded ineligibility by method …
Never silently treat an ineligible record as zero incremental ECL."*
Four rules, each from a measurement, each compiled to a SQL predicate so the
engine evaluates it over the full population and the governance trace can show
it.

| Shock | Excluded rows | Predicate | Why |
|---|---|---|---|
| PD, either horizon | Stage 3 | `stage = 3` | PD is **exactly 1.0** on all 14,836 Corporate and 13,295 Retail Stage 3 rows, and ECL there is `ead × lgd`. Scaling a probability that is already one is meaningless, not conservative |
| LGD, EAD, balance *(Retail)* | written off | `write_off_sar_mn > 0` | ECL is floored at `written_off − recovered`, so it is not a function of PD, LGD or EAD at all |
| CCF *(Corporate)* | no undrawn | `undrawn_sar_mn = 0` | 1,308 rows have nothing to convert, so no structural CCF sensitivity (§10.3) |
| CCF *(Retail)* | all | `TRUE` | No CCF exists to move; `ead = balance` on four products and the fifth uses a generator constant |

Corporate LGD and EAD exclude nothing. The Retail floor is a generator rule
with no Corporate equivalent, and inventing a symmetric exclusion would cost
real rows for the sake of tidiness.

Separately, and per §10.3: a zero baseline has no ratio, so a relative shock on
it is unsupported rather than divided by an epsilon. That is a row-level
outcome, not a population predicate — oracle O11.

---

## 5. What is absent, and what it blocks

**No macroeconomic variable exists in either book.** No GDP, unemployment, CPI,
oil price, policy rate or property index. Verified three ways: `schema.py:828`
registers no macro relation; a case-insensitive grep over both manifests
returns zero; the same grep over the generators returns zero.

Consequently **the whole of §7** — the twenty-factor registry, the sensitivity
estimation, the readiness gates, the unemployment worked example — has nothing
to attach to. §7.1's own rule applies to the registry itself: *"Never present
missing factors as zero sensitivity. Never invent coefficients to fill twenty
rows."* The honest status for all twenty is `UNAVAILABLE`.

Also blocked, with what blocks it:

| Capability | Needs | Status |
|---|---|---|
| §7 MEV sensitivities | any macro series | `UNAVAILABLE` — nothing to regress against |
| §11 ML emulator | a label that is not the model | `DEMO_ONLY` at best — the label is `ead×pd×lgd` |
| §9.1 overlay held fixed | a modelled/overlay split | operates on reported ECL, disclosed |
| §9.2 lifetime conversion | PD term structure, discounting | unsupported; no ad hoc multiplier |
| §4 family 5 stage migration | an approved SICR rule + horizon conversion | user assumption only |
| §4 family 4 on Retail | a sector dimension | unsupported |
| §10.1 CCF on Retail | a CCF | unsupported |
| §8 application-score scenarios | an application score | unsupported |

The legacy `data/cockpit_v4/v4-saudi-20q-v1/` release has macro series,
scenario weights, term structures, `ecl_modelled`/`ecl_overlay`, EIR and
maturity — for 218 facilities, under a different schema, in a lake root
`lake.py:72-76` cannot reach. It is a **design reference** for the synthetic
candidate release, not a source to import; §3.1 forbids importing the old book.

---

## 6. Enrichment: none in this pass

§3.3 permits versioned, candidate-only, read-only enrichment joined to
immutable source snapshots. **This pass adds none.** The only non-published
quantity used is the Corporate CCF, and it is *derived from published columns
in the same row* rather than joined from anywhere — labelled `DERIVED`
everywhere it appears, with its formula carried in the dictionary.

Accepted source hashes are unchanged, which
`scripts/whatif/protected_hashes.py --check` reports on every run (§D09). The
candidate's lake is a byte-for-byte copy of the accepted one, verified with
`diff -rq`.

---

## 7. Operational notes for whoever runs this next

- `data/cockpit_v4_lake/` and `data/cockpit_v4/` are **untracked**. A fresh
  checkout has no data and the suite fails at collection with
  `ReleaseNotFound`. Copy both, or publish them.
- Both roots are needed. With only `cockpit_v4_lake` present, several hundred
  tests skip silently rather than fail — the V3-namespace store reads
  `data/cockpit_v4/` when `COCKPIT_AGENTIC_V3_NAMESPACE=cockpit_v4`.
- `semantics.py:47-80`, `context.py:6` and `catalog_tool.py:7` describe the
  legacy book, not these two. Reading them gives a materially wrong impression
  of what is available.
