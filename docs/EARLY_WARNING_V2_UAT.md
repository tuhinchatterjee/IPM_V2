# Early Warning V2 — UAT readiness

Branch `claude/early-warning-rebuild-v2-3lnttn` at `ed9e2d7`. Not merged to main.

This is the readiness record: what was checked, what it returned, and what is still
not passing with the evidence for each classification. The build itself is described in
`EARLY_WARNING_V2_HANDOFF.md`.

---

## 1. Model invariants — all confirmed from the engine

Read out of the scoring modules themselves, not from a document that could drift from
them.

| | Required | Engine reports |
|---|---|---|
| Signals | 123 / 105 / 18 | **123 / 105 / 18** |
| Classifiers | 23 | **23** |
| Triggers | 67 | **67** |
| Accelerator dimensions | 5 | **5** — magnitude, velocity, persistence, repetition, corroboration |
| Decay | separate from the accelerator | **8 signal classes**, persistence hold, cutoff 0.15 at 400 days |
| Sub-categories | 22 | **22** (14 T&A + 8 classifier) |
| Layer / dimension results | 6 | **6** (4 T&A + 2 classifier) |
| Anchor matrix | 5×5 | **5 × 5** |
| Notches | 5 | **5** at 8 points, net capped ±2 |

Notch keys: network contagion, direction of travel, evidence quality, data staleness,
management and governance.

**Rawabi regression passes.** `test_rawabi_regression.py` reproduces the workbook's own
worked example through the real roll-up, matrix and notch modules: layer scores L1 69.2,
L2 81.0, L3 78.0, L4 65.65 → T&A 73.0775; classifier 71.283; **anchor 72**, net notches
**−2**, final EWS **56.0 MEDIUM**, no override firing.

## 2. Snapshots

**15 monthly snapshots**, 2025-04 through 2026-06, 300 obligors, all at
`methodology_version = ews-v2.1.0`.

## 3. Navigation

**Exactly one** Early Warning nav item, asserted in the browser and pinned by a test so a
second cannot be added quietly.

The item's own description said **35 classifiers** — the count of an earlier and wrong
reading of the workbook, and one the brief names as forbidden. So did the data-domain
description. Both now say 23, and a test pins the number to the engine.

## 4. Journeys, verified in the browser

Fourteen checks, **all passing, zero console errors**.

| Journey | Checked |
|---|---|
| Portfolio | KPI tiles read `SAR 15.5bn` / `SAR 118.0bn`; the portfolio reading is above the tables; the 15-month trend is drawn |
| Segment | Selecting a segment writes `?segment=`; the segment interpretation renders |
| Rating | The grade level writes `?level=internal_rating`; the divergence note is present; the table labels its money column `(SAR m)` |
| Borrower | Selecting an obligor writes `?customer=`; the drill-down opens with anchor, classifier and layer detail |

## 5. Back, history and filters

**This was broken and is fixed.** Selections were written with `replaceState`, which
updates the URL without creating a history entry — a shared link worked and Back was a
lie, leaving the Early Warning page entirely on the first press after three drill-downs.

Selections are pushed now, and `popstate` reads the query string back into state so the
address bar and the screen cannot disagree after a walk. Verified live:

```
after band       band=VERY_HIGH
after level      band=VERY_HIGH&level=internal_rating
after segment    band=VERY_HIGH&segment=Public+Sector&level=internal_rating
back 1           band=VERY_HIGH&level=internal_rating
back 2           band=VERY_HIGH
back 3           (none)
forward 1        band=VERY_HIGH
```

One step per selection, Forward returns, the page never leaves, and the band chip shown
selected matches the URL.

Worth recording because it nearly shipped: the first fix put the `pushState` inside a
state updater. React deliberately calls an updater twice, so every selection wrote two
identical history entries and the first Back appeared to do nothing. The push is now
outside it, and the URL — not a ref — is what the callback reads, which is also what
keeps it stable.

Thread preservation is covered in section 8.

## 6. The eight live AI questions

All eight answer. Every one is **safe** on the four safety criteria and scores **1.00** on
the seven quality criteria, with the chart decision correct in every case.

| Question | Scope | Safe | Quality | Chart |
|---|---|---|---|---|
| Why has portfolio EWS changed? | portfolio | yes | 1.00 | yes |
| How is Contracting & Construction performing? | group | yes | 1.00 | yes |
| Why are Grade 6–7 borrowers showing elevated EWS? | level | yes | 1.00 | yes |
| Why is Rawabi flagged? | ambiguous | yes | 1.00 | no |
| Did Rawabi Group 2 improve when its score fell? | borrower | yes | 1.00 | yes |
| What should I do about Rawabi Group 2? | action | yes | 1.00 | no |
| Should I escalate it? | escalation | yes | 1.00 | no |
| Show the evidence behind its dominant node. | evidence | yes | 1.00 | no |

The last two carry the obligor forward from the previous turn, which is how they were
asked.

### The answers as returned

**Why has portfolio EWS changed?**

> The portfolio early warning score is 10.8 (very low) on an exposure-weighted basis, with
> 46 of 300 obligors at high severity or above carrying SAR 15.5bn, 13.1% of exposure.
>
> Since 2025-04 the score has risen by 1.0 points. Layer 1, internal behavioural
> contributed +2.85 and Layer 3, external intelligence contributed +0.04. The movement is
> led by the obligors' own banking behaviour, which is the layer the bank sees first and
> can act on without waiting for external confirmation. The risk is spread rather than
> concentrated: the largest 5 names carry 39.1% of the high-risk exposure, so the 46
> obligors at high or above do not reduce to a handful of cases. A population action is
> likely to be more efficient than a series of single-name escalations, and the diagnosis
> tree will say whether they share a driver.

**How is Contracting & Construction performing?**

> Contracting is at 38.7 (low), 23 obligors and SAR 3.6bn, 11 at high or above.
>
> The weakness is concentrated rather than broad-based: 11 of 23 obligors sit at high or
> above and carry 75.4% of the high-risk exposure. That distinction decides the response —
> the evidence supports targeted borrower intervention rather than a sector-wide limit
> action. If the same drivers begin appearing across more obligors, it becomes a portfolio
> question instead. Layer 1, internal behavioural is the dominant source of trigger-side
> risk here at 26.6, so that is where the evidence to verify sits. Since 2025-04 the group
> has moved +19.2 points, with Layer 1, internal behavioural contributing +10.64.

**Why are Grade 6–7 borrowers showing elevated EWS?**

> Grouped by internal grade, the weakest is D at 95.0 (very high) across 11 obligors and
> SAR 2.0bn.
>
> The three weakest are D at 95.0, CC at 37.4 and CCC at 27.5, together carrying SAR
> 4.3bn. […] Grade and early warning diverge most at Salman Holding 2, internally graded
> CCC and scoring 0.0 (very low). The grade is a classifier and moves on a review cycle;
> the score is trigger-led and moves monthly, so they are not supposed to track each other.
> Where they disagree materially either the grade is stale or the trigger is a false
> positive, and the disagreement is itself what to investigate — not a reason to change the
> grade from this screen.

**Note for the UAT script.** This book is graded AAA to D. There is no grade 6 or 7 in it,
so the answer groups by the scale the book actually uses rather than inventing the one the
question assumed. A case pins that behaviour.

**Why is Rawabi flagged?**

> 11 obligors carry the Rawabi name. The weakest is Rawabi Group 2 at 60.0 (high) on SAR
> 76.3m. Which one did you mean?
>
> They are separate obligors rather than one group exposure, so they are scored separately
> and none of their positions can be read off another's: Rawabi Group 2 at 60.0, Rawabi
> Resources 10 at 16.0, […] and 5 more. If the name is a group and the exposures are
> related, that relationship belongs in the network layer, where it is scored as
> propagation across confidence-rated edges rather than assumed from a shared name.

This used to return a portfolio summary.

**Did Rawabi Group 2 improve when its score fell?**

> **No.** Rawabi Group 2's score has risen +48.0 points from 2025-06 to 2026-06, to 60.0
> (high).
>
> Of that, the anchor moved +4 points, which is the underlying condition and the notches
> moved −16 points, which is the adjustment for what the two dimension scores cannot see on
> their own. The anchor and the notches do not account for where the score ended up, and
> they are not meant to here: `unwaived_covenant_breach_floors_high` is in force, so the
> final band is set by rule rather than by the roll-up. The rule is the thing to read, and
> it is the thing that has to stop applying before the score can come down. The position it
> is at is still driven by L2.5 Security and covenant protection at 100. This is structural
> rather than live: the transactional and arrears reading is very low while the classifier
> reading is high. There is no live deterioration to contain, so the actions that matter
> are the ones that re-test the structure rather than the ones that stem an outflow.

**What should I do about Rawabi Group 2?**

> 6 actions are indicated for Rawabi Group 2, keyed to its drivers rather than to its
> score. The priority is: confirm the staging decision and the arrears position, and put
> the obligor on the watchlist at the frequency the band requires.

Every action carries owner, timeframe and closing evidence — for example: *Commission a
fresh valuation and require a collateral top-up. Collateral / Valuation, 30 days. Closes
on: valuation report and registered security.* The escalation line follows: *At high
severity on SAR 76.3m of exposure the decision sits with Credit Risk Manager, with 1-day
acknowledgement and a 10 working day decision.*

**Should I escalate it?**

> At high severity on SAR 76.3m of exposure the decision sits with Credit Risk Manager,
> with 1-day acknowledgement and a 10 working day decision.
>
> The question being put is not whether the obligor is good or bad; it is what risk
> mitigation is proportionate to SAR 76.3m of exposure. Severity decides how fast that
> decision is needed and materiality decides how high it goes, which is why a smaller
> exposure at the same severity would stop lower down the ladder. The escalation should
> carry the driver rather than the score: L2.5 Security and covenant protection at 100,
> covenant breached or waived, security below 70% of exposure, with the recommended action
> and the evidence that closes it.

**Show the evidence behind its dominant node.**

> `operating_deposit_balance_decline` scored 43.2 in 2026-06, from a severity band of 2
> (40) scaled by an accelerator of 1.080.
>
> It comes from Core Portfolio / Facility (`corporate_borrower_360`, interpolated monthly
> from quarterly anchors), so that is where an analyst verifies it. Signal class
> transactional_and_behavioural, half-life 21 days. The decay factor is 1.00 because the
> condition remains uncured. Under the persistence hold the decay clock only starts on
> cure, so age has not reduced this signal's weight — it is 30 days old and still carries
> full weight. Accelerator dimensions: magnitude 3, velocity 3, persistence 3, repetition 1
> and corroboration 1.

### Against the ten checks asked for

| Check | Evidence |
|---|---|
| Numerical grounding | Every figure traced to the fact pack; ungrounded figures fail the answer |
| 1–2 paragraph senior-risk interpretation | Present on all eight, none a restatement of the table |
| Live vs structural | Stated on the borrower, action and escalation answers |
| Correct node / reason | L2.5 named with its reason code and score, not just a number |
| Remediation | Six governed actions, ranked by reversibility then cost |
| Owner / timeframe / evidence-to-close | On every recommendation; a missing one fails the answer |
| Correct escalation | Matrix rung, exposure tier, both SLAs, and why that rung |
| Specific next drill | Present on all eight; "would you like to know more?" fails |
| No inappropriate chart | Charts on portfolio/group/level/borrower; none on ambiguity, action, escalation or evidence |
| No hallucinated figures | Enforced by the grounding criterion over all 44 cases |

## 7. Escalate and Inform → Messages

Both live-tested end to end.

**Escalate** returns 200, creates one case, sends one message through the existing
Workflow service, and stamps the matrix's decision SLA as a real due date:

```
case_key       rc_cce011fc1963
workflow item  330, due 2026-09-13
routing        escalated_to ['L2','S3'], ack 0 days, decision 5 days
matrix version 1.0.40
```

The message body is the governed note: position, driver with score and reason,
corroborating drivers, the recommendation with owner and closing evidence, and the
decision requested — in the corrected riyal convention (`SAR 31.5m of a SAR 38.1m limit`).

**Inform** returns 200 and sends an FYI without changing the case.

**One defect found and fixed here.** Inform's entire contract is that it changes nothing,
but it refreshes the case, and the shared case machinery replaces `evidence` wholesale on
a refresh. Escalate, then send an FYI, and the record of which matrix version routed the
case and to which cell was silently gone. That is right for the fields describing the
score, which are recomputed; it is wrong for the escalation record, which is history. The
Early Warning bridge now carries those keys across a refresh, scoped to this domain so the
shared machinery keeps its behaviour for every other agent. Two tests cover it, and the
erasure test was verified to fail without the fix.

Escalate, Inform and Escalate again on the same obligor still leave **one** case.

**Note.** Escalate requires an explicit recipient (422 without one). That is correct
rather than a gap: the matrix names a *role* — Credit Risk Manager, Head of Credit Risk —
and this deployment has no directory mapping those roles to users or teams. Routing them
automatically would mean inventing that mapping.

## 8. Investigations

The full round trip works.

| | |
|---|---|
| Start a domain-locked thread and ask | 201, answered about the obligor by the Early Warning domain |
| Recent EWS Investigations (`?domain=early_warning`) | 200, thread present |
| Global Investigations (`?scope=all`) | 200, same thread present |
| Resume | 200, both messages restored |

The restored context carries `domain: early_warning`, `customer_id`, the conversation
turns, and the working memory including the fact pack, the six governed actions and the
live-versus-structural reading — so a resumed thread can answer "should I escalate it?"
about the right obligor without re-deriving anything.

## 9. Reports

All three scopes generate with charts embedded, and the numbers reconcile to the live API.

| Scope | Size | Chart images |
|---|---|---|
| portfolio | 130,312 bytes | 2 |
| segment | 99,792 bytes | 1 |
| borrower | 98,460 bytes | 1 |

Reconciliation against `GET /early-warning/v2`:

| Figure | API | Report narrative |
|---|---|---|
| Portfolio EWS | 10.8 | 10.8 |
| Borrowers | 300 | 300 |
| At high or above | 46 | 46 |
| Exposure at high or above | 15,469.86 | SAR 15.5bn |
| Total exposure | 117,990.60 | SAR 118.0bn |

The severity distribution table matches the API row for row: 12 / 34 / 1 / 7 / 246.

## 10. Money convention — the one presentation defect, fixed

The tiles read `15,470` above prose reading `SAR 15.5bn`. Five conventions were live at
once: the application-wide formatter (a bare number, no unit), the composer (millions, no
decimals), an Early Warning formatter on the interface side used by one screen, inline
f-strings in the report builders (one of which rendered the portfolio total as
`SAR 117991.0 million`), and the escalation note, which could not reach the composer's
writer because `compose` imports `escalation` and grew its own.

There is now **one writer per side**, in `backend/early_warning/units.py` and
`frontend/src/lib/early-warning-format.ts`, mirroring each other character for character:

- at or above a thousand millions → `SAR 15.5bn`
- below → `SAR 489.0m`, `SAR 31.5m`
- a live residual under a hundred thousand riyals → `SAR 0.04m`, never `SAR 0.0m`

Tables state the unit once in the header — `(SAR m)` on screen, `(SAR mn)` in a report —
and keep bare numbers, because a column where one cell reads 15.5 and the next 840.0 under
one header states two units. Four report tables rendered bare millions under an unlabelled
header; they are labelled now.

**The application-wide `money()` is untouched**, so nothing outside Early Warning changes.

Two tests hold it: both sides carry the same expected strings, and a guard reads the
source of every module that writes money and fails if any formats a riyal figure by hand.
That guard was briefly blind — stripping prose by blanking every string constant also
blanked the literal segments of the f-strings it was hunting — so it blanks docstrings
only, and a planted offender proves it bites.

---

## Test results

| Suite | Result |
|---|---|
| `tests/early_warning/` | **1446 passed**, 2 failed, 1 skipped, 3 errors |
| `tests/evals/test_early_warning_brain.py` | **231 passed**, 2 skipped (44 cases) |
| `tests/api/test_early_warning_v2.py` + `test_early_warning_api.py` | **50 passed** |
| Frontend `npm test` | **405 of 405 passed** |
| `npm run typecheck` / `lint` / `build` | clean |

## Every remaining non-pass, classified

The classification is measured, not asserted. The branch point
(`3855f9b`) was checked out into a worktree, given the same `.env` and the same data lake,
and the same suites run there.

| | Branch point | Branch head |
|---|---|---|
| `tests/api/` + `tests/orchestration/` + `tests/evals/` | 160 non-passing | **160 non-passing** |
| Introduced on this branch | — | **0** |
| `tests/early_warning/` | 5 non-passing | **5 non-passing** |

The non-passing test **identifiers** are identical at both commits — not merely the counts.
No test that passed at the branch point fails at the head.

**The five in `tests/early_warning/`** are all `test_forward_risk_signal.py`, the legacy
fitted signal, failing with `EarlyWarningError: The Forward Risk Signal needs at least
three reporting periods: two to fit on and one to test against`. They fail identically at
the branch point. Untouched by this work, and not repaired here.

**The 160 elsewhere** are the credit book's quarterly lake and platform fixtures —
`DatasetNotPublishedError: portfolio_facility`, a dataset viewer `KeyError`, a steward
sign-in returning 400, and `'Show the top 50 customers by EAD' did not compute`. None
touch Early Warning, and all fail identically at the branch point. Not repaired here, per
instruction.

## Known limitations for UAT

- **The model is not calibrated.** Every weight, band and multiplier is a documented
  starting calibration, not an estimate fitted to default data. The tool orders obligors;
  it does not predict them, and no output is a probability. The caveat travels with every
  answer, screen and report scope.
- **Layer 3 external intelligence is synthetic** in this build, and says so wherever shown.
- **Escalation needs a named recipient**, because the matrix names roles and this
  deployment has no role-to-user directory.
- **No AI provider is configured.** The reading is deterministic. The live-model seam is
  wired and inert: if a provider is configured it may rewrite the prose only if what it
  writes passes the same grounding check, and the deterministic text stands otherwise.
- **The book is graded AAA to D**, so a question naming a numeric grade band has no
  referent; the answer groups by the scale the book uses.
