# Cockpit repoint — the field mapping, and what it found

The specification for M4b, produced before any Cockpit code is changed, as
execution rule 1 requires. It classifies every Cockpit-required field against
the canonical Corporate source and records what cannot be resolved by renaming.

**No field may be silently substituted by a semantically different one.** A
field that looks similar but is computed under a different staging policy,
rating scale, currency, grain or population is not a match, and is recorded as
needing re-derivation rather than mapping.

## Classes

| Class | Meaning |
|---|---|
| **A** Canonical direct | same name, same meaning, same grain |
| **B** Renamed | same meaning, different name |
| **C** Derivable | computable from canonical fields |
| **D** Cockpit-owned derived | legitimate Cockpit metric, computable from canonical inputs |
| **E** Genuinely missing | no canonical equivalent and not derivable |

---

## Two findings that change the scope of M4b

### 1. A hard operational blocker: Cockpit V3 materialises whole relations into a 512 MB in-memory DuckDB

`backend/cockpit_agentic/sql.py::_build_session` builds every query session by
copying whole relations into memory:

```python
connection = duckdb.connect(database=":memory:")
connection.execute(f'CREATE TABLE "{relation}" AS SELECT {projection} '
                   f"FROM read_parquet('{path}'){predicate}")
```

with `SET threads TO 2` and `SET memory_limit = '512MB'` (`sql.py:215-216`), and
`MAX_CACHED_SESSIONS = 4`.

Those limits are sized for the private book: 250 borrowers, 600 facilities, 20
quarters. The canonical book is **3,800 borrowers and roughly 14,000 facilities
over 16 quarters, with 175 declared columns on the facility relation alone** —
and four cached sessions multiply it.

**This will not fit, and it is the ruling's own consequence rather than an
objection to it.** The user's decision is that Cockpit sees the whole canonical
population and that any working set is a query-time filter, never a separate
population. That is exactly right, and it is incompatible with materialising
whole relations up front. The materialisation strategy has to change — query the
Parquet directly with predicate and projection pushdown, so the filter reaches
the file rather than the memory copy — **before the semantic mapping below is
worth anything.**

### 2. Canonical has no forecast quarters, and Cockpit's macro window is mostly forecast

Cockpit's macro pivot is keyed by `(reporting_quarter, macro_target_quarter)`
with `quarter_offset` running `-4 .. +15` — twenty positions per anchor,
asserted at `fields.py:1493` as exactly 200 macro-pivot fields.

Canonical publishes **16 quarters of actuals and zero forecast**. At the earliest
anchors `lag4` does not exist; at every anchor `lead1..lead15` does not exist.

**175 of the 200 macro-pivot cells have no canonical source.**

This is the one place where the repoint genuinely removes a capability rather
than relabelling one. Three honest options, to be decided rather than defaulted:
extend canonical with a governed macro forecast path; reduce the Cockpit macro
window to the offsets canonical can serve; or keep the forecast as an explicitly
Cockpit-owned projection over canonical actuals, labelled as a projection. The
existing `quarter_offset` guard — *"a positive offset is a forecast made at the
anchor, never an observed future quarter, and it does not add a reporting
period"* — is good and must survive whichever is chosen.

Related: canonical runs **Q3 2022 – Q2 2026**; Cockpit V3 runs **2021Q3 –
2026Q2**. The end agrees, the start does not. **Four Cockpit quarters have no
canonical data at all.**

---

## A correction to the plan: V3's rating scale already matches canonical

The integration plan recorded the 12-grade scale as a Cockpit-wide problem. It
is not. `backend/cockpit_agentic/fields.py:897-901` declares exactly the
nineteen canonical grades in the canonical order, with `assert len == 19`:

```
AAA AA+ AA AA- A+ A A- BBB+ BBB BBB- BB+ BB BB- B+ B B- CCC CC C
```

So for **Cockpit Agentic V3**, `risk_rating` and `rating_rank` are class **B**
— a rename — precisely because the scales agree.

The 12-grade scale is **Cockpit V2's alone** (`backend/cockpit_v2/policy.py:36-54`:
twelve performing grades, `D` at rank 13, `WORST_PERFORMING_RANK = 12`), and
there it cannot be renamed:

* Rank 7 means `BB-` in V2 (PD 2.20%) and `A-` in canonical (PD 0.086%) — a
  factor of 25 in credit risk. **A rank is not portable.**
* V2 has no `AA+`, `AA-`, `A+`, `A-`, `BBB+`, `BBB-`. Canonical grades landing in
  those gaps have no V2 target.
* V2 *computes* a grade from six weighted financial ratios (`RATING_FACTORS`,
  `policy.py:96-125`). Canonical reads the grade off `rating_quality` and then
  applies committee inertia. **These are two models' outputs, not two names for
  one number.**

Re-derivation must go **via PD**, not via grade or rank:
`canonical internal_rating → ratingscale.TTC_PD_PCT → V2 PD band → V2 rank`.
Lossy in both directions; 19→12 collapses and 12→19 cannot recover the
modifiers.

---

## Two semantic traps that would corrupt SICR silently

**`pd_at_origination` does not mean the same thing on both sides.** Canonical's
`pd_at_origination_pct` is **re-conditioned every quarter onto the reporting
date's cycle** (`universe.py:1789-1801`), and the code says why: holding it at
its own vintage moved Stage 2 from 6% to 75% of the book across the cycle.
Cockpit's `pd_pit_12m_at_origination` means the vintage figure. Wiring one to
the other silently changes what the SICR ratio measures.

**Canonical's carried stage has memory.** `_staged_with_probation`
(`universe.py:1547+`) means `stage_measured` ≠ `stage` for borrowers serving
probation. Cockpit declares one `ifrs9_stage` with no probation concept, so a
Cockpit reading `stage` and a Cockpit re-deriving from triggers will disagree on
exactly the probation population — which is the disagreement
`whatif/schema.py::IFRS9_OPTIONAL["stage_measured"]` exists to warn about.

Cockpit V3 already declares that it *reads* stage and does not assign one
(`fields.py:365-375` — no trigger set, a stored `ifrs9_stage` and `sicr_flag`).
Honouring that is the resolution: canonical stages, Cockpit reads.

---

## Currency and unit: ~190 fields, and a 10x scale trap

Cockpit: `REPORTING_CURRENCY = "INR"`, `AMOUNT_SCALE = "crore"`.
Canonical: `"currency": "SAR"`, `"unit": "millions"`.

**A crore is 10^7 and a million is 10^6**, so the scale differs by ten before any
FX. No FX scalar exists on either side — Cockpit declares
`fx_to_reporting_currency` (class E) and canonical has nothing.

Roughly 190 currency-denominated fields are affected: 13 facility, 4 IFRS 9
detail, 60 collateral summary (12 types x 5), 3 collateral totals, 5 collateral
asset, 3 allocation, 41 balance-sheet, 32 income-statement, 16 ratio inputs, 4
common keys, 9 V2 measures.

The fix is book-level constants, not per-field — **except** for the places that
carry the unit as a **function default**, which would otherwise silently relabel
SAR figures as INR: `cockpit_v2/attribution.py:312-313, 373` and
`cockpit_v2/ecl.py:262, 455, 518`.

One literal trap: `fields.py:226` declares `amount_scale` as
`("unit","thousand","million","crore")` while canonical writes `"millions"`
(plural). A string comparison fails.

---

## `corporate_ifrs9_facility` — the shopping list

Of the 32 facility-grain fields Cockpit needs:

| | Count | Note |
|---|---|---|
| **Producible inside `build_ifrs9()` today** | **19** | by moving the facility groupby to the *end* of the function rather than the start. It already holds the facility frame, the collateral frame (which carries `facility_id`), the ratings join and the back-solved CCF identity |
| **High-value change** | **1** | push the `secured / unsecured / LGD` chain down to facility grain. `corporate_collateral.facility_id` already exists, and the obligor-level LGD is currently averaging away real security differences between a borrower's own facilities |
| **New but cheap** | **4** | facility `days_past_due`; facility `pd_at_origination` (canonical already carries `corporate_facilities.origination_quarter_index`); `effective_interest_rate` (the margin is computed at `universe.py:2495` inside `build_profitability` and discarded — publish it); `gross_carrying_amount` / `accrued_interest` (these belong in `build_facilities`) |
| **Need parameters canonical deliberately declined to model** | **8** | `ead_pit`, `ead_ttc`, `ccf_ttc`, `lgd_ttc`, `lgd_downturn` — the PIT/TTC split generally. Canonical has one EAD, one CCF, one LGD |

### The governance decision this forces

`build_ifrs9`'s docstring is a **policy** statement, not a convenience. If
canonical publishes `corporate_ifrs9_facility` with a facility stage, it must
decide whether a stage may differ between facilities of the same borrower.

* **If it may not**, the facility table is a broadcast and must say so on the row
  — a `stage_source = 'obligor'` column, so nobody reads a broadcast as a
  measurement.
* **If it may**, `ifrs9/policy.py::stage_of` has to be evaluated per facility and
  the obligor stage becomes a derived rollup — **which changes What-If's baseline
  column.**

This is a decision to be taken deliberately, not a refactor to be performed. It
is raised before the work rather than discovered inside it.

---

## Where Cockpit actually reads from

Neither Cockpit subsystem uses `backend/data_access/duckdb_source.py`. `git grep`
returns zero references inside either package.

**Cockpit V3 — two clean chokepoints.**

* Names: `fields.py:35-49` (`RELATIONS`) plus `catalog.py:45-47`. Everything
  downstream reaches names through `F.*` constants.
* Physical: `sql.py::_build_session` (~lines 218-240) is the single place where a
  logical relation name meets a physical path, a column projection and the
  tenant/release/domain predicate. After it runs, `enable_external_access =
  false` and `lock_configuration = true` shut the door.

Repointing V3's names is close to a four-line change.

**Cockpit V2 — physical location single, names spread.**

* Physical: `reader.py::_read` (line 45) on the read side, `persist.py:35,44` on
  the write side. Permission: `scope.py::permit`, single.
* Names: roughly **45 string literals across nine modules** — `answer.py` (13),
  `validate.py` (14), `catalogue.py` (~12), `generate.py` (10), `tools.py` (3),
  `reader.py` (1). Repointing V2's names is a grep-and-fix exercise.

**A docstring to correct while there.** `backend/cockpit_v2/reader.py` claims
every figure comes *"from the PUBLISHED data — the Parquet lake through the
governed Data Access Layer."* It does not: `_read` calls `pd.read_parquet`
directly on a path built from `settings.analytics_dir`. The only DAL contact is
`persist.py:66`'s `reload_catalog()` on the **write** side. Reads bypass the DAL
entirely — no schema resolution, no pushdown, no column check of the kind
`whatif/schema.py` performs.

---

## The repoint work list, summarised

| Category | V3 sites | V2 sites |
|---|---|---|
| Dataset-name literals | 5, all reachable from two constants | ~45, spread across nine modules |
| ID prefixes | 3 (`BRW`, `GRP`, `FAC`), all in `generate.py` | 4 (`CKB` x3 including two **regexes**, `CKG`) |
| Currency / unit strings | 6 | 9, including 5 **function-signature defaults** |
| Quarter literals | 5 | 6 |
| Rating-grade literals | 1 block of 19 — **already matches canonical** | 1 block of 12+D — **must be re-derived via PD** |

Generated artefacts that must be regenerated rather than edited:
`docs/cockpit_agentic_v3/field_catalogue.json` and `field_catalogue_compact.json`
(991 baked relation/field pairs), `docs/cockpit_v2/data_dictionary.json`, and
`docs/cockpit_agentic_v3/context_sizes.json` plus
`evidence/context_measurements.json` — the packet sizes were measured against a
250-borrower book and a 10-row preview is a different sampling fraction over
3,800.
