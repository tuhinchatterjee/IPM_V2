# The labelled synthetic candidate releases

`v4-whatif-corporate-20q-s1` · `v4-whatif-retail-20m-s1`

> **These are generated books.** The borrowers and customers do not exist, the
> economy did not happen, and the ECL figures are produced by
> `backend/cockpit_v4/scenario/reference_ecl.py`, a calculator written for this
> demonstration. **Nothing here is bank output, an accounting figure, or
> observed economic history.** Every row of every candidate relation carries an
> `origin` column reading `SYNTHETIC_DEMO`, and both manifests say the same in
> their `notes`.

---

## Why they exist

The two accepted books measure ECL as exactly `ead × pd × lgd` — verified in
P2 to −0.3343 SAR mn on a 7,075,662 SAR mn Corporate book, which is rounding.
That identity is what made proportional Delta exact in P4, and it is also what
makes those books unusable for §7 and §11:

- **No macroeconomic variable of any kind.** No GDP, unemployment, CPI, oil,
  rate or property index. §7's twenty-factor registry has nothing to attach to.
- **A closed-form target.** §11.1: *"Do not manufacture the training label as
  PD × LGD × EAD and then claim the resulting model learned the bank's ECL
  engine."* A model trained on the accepted books would score near-zero WAPE
  for a trivial reason and every §11.5 target would pass meaninglessly.
- **No modelled/overlay split, term structure, discounting, scenario weights,
  rating-to-PD map, Retail application score or Retail employer sector.**

The approved plan chose a separate, clearly labelled synthetic release rather
than enriching the accepted books. This is it.

## What is guaranteed about the accepted books

| Release | Fingerprint | Status |
|---|---|---|
| `v4-saudi-corporate-20q-v4` | `e37236d0f6d4e494…` | unchanged |
| `v4-saudi-retail-20m-v5` | `a1e797dcc73236b7…` | unchanged |

Checked three ways: `scripts/whatif/seed_candidate.py` re-reads both
fingerprints after every build and exits non-zero if either moved;
`test_whatif_candidate_release.py` compares them with the values pinned at
`245c50e`; and `scripts/whatif/protected_hashes.py --check` reports
`0 removed` and no accepted parquet among its changes.

## How to build them

```bash
cd /home/user/whatif_wt
python3 scripts/whatif/seed_candidate.py --domain all \
    --evidence docs/whatif/evidence/candidate_release.json
```

The script sets both What-If flags for itself, because the candidate relations
are declared only for a book whose flag is on and `lake.publish` requires every
declared relation. **Seeding the ACCEPTED books must be run with the flags
off** — `scripts/cockpit_v4/seed_domains.py` produces no candidate relations
and the publish would refuse.

Build time is about 45 seconds per book. Two builds of the same release id
produce byte-identical parquet: every number is either a seeded `random` draw
taken in a fixed order or a pure function of `(entity, period)` through
`generate.stable()`, and every float sum goes through
`generate/totals.exact_total`, whose answer does not depend on the interpreter.

## What they contain

| | Corporate | Retail |
|---|---|---|
| Calendar | 20 quarters, 2021Q3–2026Q2 | 20 months, 2025-01–2026-08 |
| Obligors | 1,200 borrowers | 4,500 customers |
| Exposures | 2,996 facilities | 6,702 accounts |
| Exposure-periods | 59,920 | 127,936 |
| Term-structure rows | 799,836 | 1,040,040 |
| Total rows | 1,064,654 | 1,650,132 |
| Macro factors present | 16 of 20 | 14 of 20 |
| Fingerprint | `891a9872dbcde8dc…` | `0550a2e6c3390cff…` |

Smaller than the accepted books on purpose. The candidate exists to carry a
macro panel, a term structure and a trainable target — not to restate the
accepted population — and 60,000 facility-quarters is a real panel for a
chronological split while keeping the term structure in tens of megabytes
rather than hundreds.

### The accepted four relations, unchanged in shape

Both candidates publish `corp_borrower_quarter`, `corp_facility_quarter`,
`corp_collateral_quarter`, `corp_covenant_quarter` (and the Retail four) with
**exactly the columns the accepted schema declares** — no widening. They pass
the same `invariants.check` gate, with zero findings, including the identity
that the recognised ECL is the stage-selected 12-month or lifetime figure.

### The candidate relations

| Relation | Grain | What it carries |
|---|---|---|
| `whatif_*_macro_quarter` / `_month` | factor × period × scenario | The generated 20-factor panel in native units, with publication and availability dates and a forecast vintage where the value is a projection |
| `whatif_*_mev_registry` | factor | All twenty candidates with PRESENT/ABSENT and a reason for every absence |
| `whatif_*_sensitivity` | parameter × factor × lag | The fitted artifact: coefficients, native-unit slopes, the values they were evaluated at, resampled uncertainty, period counts and a readiness verdict |
| `whatif_*_term_structure` | exposure × period × scenario × horizon | Marginal and cumulative PD, survival, LGD, EAD, discount factor and expected shortfall |
| `whatif_*_ifrs9` | exposure × period | Modelled ECL against management overlay, the declared ECL denominator and rate, EIR, remaining maturity — and for Corporate, the published CCF with its eligible undrawn amount |
| `whatif_corp_rating_map` | grade × mapping version | The published scale in its own order, PD per grade per horizon, the default grade |
| `whatif_retail_score_map` | score type × version × product × band | BEHAVIOURAL and APPLICATION calibrations, kept separate |
| `whatif_retail_profile` | customer × month | Employer sector and the origination application score |
| `whatif_*_model_metric` | model × component × split × group × metric | The emulator's model card as data |

## How the numbers were made

**The macro comes first.** For each period a shared latent cycle is generated,
then each of the twenty factors follows it through its own loading,
persistence and idiosyncratic term. The factors therefore **co-move** — which
is the condition §7.3 warns about, present in the data rather than described
in a document.

**Risk is generated FROM the macro, with a lag.** For each exposure:

```
logit(PD)  =  base  +  quality effect  +  cycle_coefficient × segment_beta × cycle[t−1]  +  noise
LGD        =  base  +  lgd_cycle × segment_lgd_beta × property_index[t−1]  −  collateral  +  noise
arrears    follows the same conditions through its own threshold
stage      follows arrears and SICR
```

The true coefficients are published in each manifest's `notes`
(`true_cycle_coefficient`, `sector_pd_betas`, `employer_sector_betas`,
`product_betas`), so a sensitivity fitted in P5 can be checked against what
produced the data. **This ordering is the point.** Appending random macro
columns to unchanged PD values would let a fitter report coefficients, an
R-squared and a heatmap, every one of them an artefact of noise, and §7 would
be a decoration.

Measured on the published Corporate book, portfolio ECL and lagged
unemployment correlate at **0.75**, Stage 2 migration peaks at **21.7%** in the
stress and returns to near zero, and Stage 3 appears only at the peak.

**Measurement is last.** `reference_ecl.py` takes the per-scenario term
structure and computes

```
ECL_s      = Σ_h  survival[h] × pd_marginal[h] × lgd[h] × ead[h] × discount[h]
ECL_model  = Σ_s  weight[s] × ECL_s            weights 0.50 / 0.30 / 0.20
ECL_total  = ECL_model + overlay
```

with bucket 0 exactly twelve months long in both books — so the twelve-month
figure is bucket 0's contribution and the lifetime figure is every bucket's,
with no apportionment and no annual-figure-times-years approximation. Buckets
beyond remaining maturity are dropped and a bucket the maturity falls inside
counts for the fraction that survives.

### What that buys, and what it does not

Published Stage 1 ECL sits about **4%** away from `ead × pd × lgd` on the
Corporate candidate. The gap is real — discounting pulls down, scenario
weighting pushes up because the published PD is the baseline scenario's, and
the overlay adds on top — but it is not enormous, and that has a consequence
worth stating before P7 rather than after:

> **A naive `ead × pd × lgd` predictor already recovers most of the target.**
> The model card must therefore include it as a declared reference model, and
> the blend's acceptance must be judged on measured WAPE against the real
> target — not on beating nothing.

## Determinism

- Seeds `20260925` (Corporate) and `20260926` (Retail), distinct from the
  accepted books' `20260803` / `20260802`.
- `generate.stable(text, modulus)` is SHA-256 based, not `hash()`, which
  Python randomises per process.
- Every float sum goes through `totals.exact_total` (`math.fsum`);
  `test_generator_determinism.py` fails the build if a generator calls the
  builtin `sum`.
- Two builds of the same release id produce byte-identical parquet and the
  same `release_fingerprint`.

## The sensitivity artifact

`whatif_*_sensitivity` is fitted during this same build, by
`sensitivity.build.attach`, from the frames that are about to become parquet.
Sixty rows per book — twenty factors by three risk parameters — so a factor
the book does not carry has an `UNAVAILABLE` row with a reason rather than a
silence. `docs/whatif/SENSITIVITY_CARD_CORPORATE.md` and
`SENSITIVITY_CARD_RETAIL.md` are the methodology cards, and
`docs/whatif/P5_FINDINGS.md` records what the fitting work found, including
two estimator defects it corrected.

Each row stores a `source_fingerprint` that is a SHA-256 over the exact
period-level series the fit consumed, republished in the manifest notes as
`sensitivity_input_digest`. It is not the release's own fingerprint: an
artifact stored inside the release it describes cannot carry a fingerprint
taken over bytes that include it.

## The model card as data

`whatif_*_model_metric` carries the emulator's card in rows: 86 for
Corporate and 80 for Retail. Every predeclared gate with its measured value
and a `PASSED`/`FAILED` verdict, every component weight with its materiality
verdict, the declared reference model, every subgroup's WAPE with its share
of the test period's ECL, and the row and period counts behind all of it.

**Retail's G4 row reads `FAILED` and carries 0.3802.** A gate that was
missed is published with the number that missed it.

`docs/whatif/MODEL_CARD_CORPORATE.md` and `MODEL_CARD_RETAIL.md` are the
prose version; `P7_FINDINGS.md` records what the training found.

## Why the fingerprints moved after training

A model-metric table lives **inside** the release it describes, so the
release has to be published twice: once with the data the models train on,
and once more with the metrics the training produced.
`artifacts/whatif/<book>/model_metric.json` carries
`trained_against_fingerprint`, which is the fingerprint of the release the
models were actually **fitted** on — the one before the metrics were added.

The sensitivity artifact is unaffected: its `source_fingerprint` is a digest
of the period-level series the fit consumed, not of the whole release, so
republishing with new metric rows does not make it stale.
