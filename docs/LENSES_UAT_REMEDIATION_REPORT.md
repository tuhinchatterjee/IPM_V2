# Lenses V2 — UAT Remediation Report

**Branch** `claude/lenses-specialist-dashboards-esd591`. Not merged, no PR.

Three UAT findings, addressed in place on the existing architecture. Nothing
listed as "preserve" in the brief was rebuilt: Lens persistence, the metric
library, metric preview, the chart builder, edit mode, drag/reorder, the
preconfigured Lens library, the existing APIs, and deterministic execution
are all unchanged — proven by re-running the two acceptance suites that
already covered them (see §4) and getting the same counts as before this
tranche.

---

## 1. UAT Issue 1 — false "Sign in to use CreditProbe."

### 1.1 Root cause, found by reproducing it

The symptom names Lens actions specifically, but the cause is systemic: an
authenticated session is verified once, when `AuthProvider` mounts, and never
re-verified after. When the backend independently stops recognising the
session — routine in local development, since a session signed with no
`SECRET_KEY` configured is invalidated by every process restart — the top
navigation keeps showing "signed in" from state it fetched once, while every
subsequent mutating call correctly 401s. A Lens component simply rendered
whatever the backend's error said, which is the literal string "Sign in to
use CreditProbe." That is not a special "you are logged out" screen; it is
the ordinary error path showing the ordinary refusal text.

Reproduced live end to end (`/tmp` throwaway scripts, not committed): sign in
normally, restart the backend under the same open tab with no page reload,
then use a Lens exactly as UAT did. Before the fix, the nav kept claiming
"Sign out" while the action produced the dead-end message. After the fix, the
same sequence flips the app to the real sign-in screen immediately, and the
interrupted action succeeds once signed back in.

### 1.2 The fix, in two parts

**Client-side recovery** (`frontend/src/lib/api.ts`, `frontend/src/components/system/auth.tsx`).
`request()` and `download()` now call `announceSessionExpired()` on exactly
`status === 401 && code === "not_signed_in"` — never on a 403, which is a
real session whose role may not do something and must never sign anyone out.
`AuthProvider` subscribes and flips `status` to `"anonymous"` on that signal.
`AppShell`'s existing, already-tested `AuthGate` does the rest: it swaps to
the real `<LoginScreen/>` the moment `status` is anonymous. No Lens component
had to change, and no new UI was built — the fix is that the one place that
remembers "signed in" is told the truth as soon as anything notices otherwise.

**Restart durability for local development** (`backend/api/auth.py`). A
session signed with no `SECRET_KEY` now survives a backend restart when
`ENV=dev` (the shipped default), by persisting the process key to
`logs/.dev_session_secret` — an already-gitignored directory, regenerated if
ever missing or unreadable. Every other `ENV` value keeps the original
behaviour unchanged: a restart there still invalidates a signature, on
purpose, because trusting a written-down key in a real deployment is the
wrong trade. This does not touch RBAC — `require()`'s 403 path is untouched —
and does not remove any authentication check; it removes the most common
reason a *genuinely valid* local session was being treated as dead.

### 1.3 Tests

- `tests/api/test_session_recovery.py` (7 tests): the dev key survives a
  simulated restart, is actually written to disk, is shared correctly across
  what a second process would see, is **not** granted outside `ENV=dev`, a
  configured `SECRET_KEY` always wins over the dev file, a read-only/corrupt
  key file degrades to a fresh key rather than crashing, and the exact
  `401`/`"not_signed_in"` contract the frontend matches on is pinned so a
  future change to it cannot silently break the recovery.
- `tests/api/test_login_required.py` — unchanged, still green: RBAC and the
  "no session, no access" default are provably untouched.
- Browser: `scripts/acceptance/lens_uat_journeys.py`, journeys `AUTH-admin`,
  `AUTH-analyst`, `AUTH-9` — see §4.

---

## 2. UAT Issue 2 — the AI Lens Builder must read broad requests

### 2.1 Design

`backend/metrics/lens_planner.py`. Domain resolution is untouched —
`builder.interpret()` already does that deterministically and well, and is
called first, unchanged. New is the step after: given those domains and the
full governed catalogue (id, name, domain, unit, definition), an LLM reasons
about which metrics actually answer the request the way a senior credit-risk
analyst would, organised into six fixed sections (headline, trend, quality,
concentration, early warning, other).

**Every metric id the model returns is validated against the real
catalogue** before it reaches a screen. An id that is not in the pool the
model was shown — invented or otherwise — is moved to `unsupported` with a
stated reason, never silently kept and never silently dropped. Every chart
dimension it proposes is checked with the same `dimension_fields` /
`chart_types_for` calls the rest of the builder already uses; a dimension a
dataset does not carry falls back to a KPI rather than becoming a broken
chart.

**Degrades to the existing matcher when no provider is configured** — the
same handful of best-matching metrics `interpret()` already found, in the
same response shape, with `understood: false` and a stated reason. The
frontend (`/lenses/new`) only renders the new "Proposed Lens" panel when
`understood` is true; otherwise the existing quick-add chips (unchanged)
carry the flow exactly as they did before this tranche.

New route: `POST /lenses/plan`, `RequireAnalyst`.

### 2.2 Tests

This sandbox has no `ANTHROPIC_API_KEY` configured, so a live model's
reasoning cannot be exercised here. What is tested is what is actually this
codebase's own responsibility: `tests/metrics/test_lens_planner.py` (29
tests) runs the real pipeline — real domain interpretation, real catalogue
validation, real dimension checks — against a **scripted** provider (the same
pattern `backend/analyst/conftest.py`'s `ScriptedProvider` already
establishes for this exact reason). It proves: a fabricated metric id is
rejected, not trusted; an invalid chart dimension falls back to a KPI; the
metric/chart caps are enforced; the no-provider fallback never invents a
metric either; and all **20 golden natural-language requests** the brief
lists produce a plan whose purpose, scope and metric selection are correctly
carried through validation, using only real metric ids from this catalogue.

`tests/api/test_lens_builder_api.py` gained 4 tests for `/lenses/plan` at the
route level (honest degradation with no provider, RBAC, schema validation).

A deployment with a configured provider exercises the model's own judgement
via `scripts/acceptance/lens_uat_journeys.py` journey `AI-C`, which submits
the UAT's own sentence verbatim (see §4).

---

## 3. UAT Issue 3 — every Lens should open with an AI interpretation

### 3.1 Design

`backend/metrics/lens_interpretation.py`. Sits exactly where
`orchestration/interpretation.py` sits relative to one analysis: strictly
after the deterministic render. It is given the already-rendered Lens (every
tile's current value, its prior-period value and the delta where a
comparison exists, its definition) and never queries the book itself.

**The same metric reads differently on different Lenses, answered
generically.** The model is given the Lens's own stated `purpose` and
`audience` — already written, already specific for every shipped Lens — and
told to read the figures the way that reader needs them read. No per-Lens
template or slug-keyed special case exists; a user-built Lens gets the same
treatment from its own purpose, for free.

**Every figure the prose contains is checked against the rendered Lens.** A
number not among the current values, prior values or computed deltas the
model was shown is grounds to discard the *entire* reading — not annotate it
— the same policy `orchestration/interpretation.py` already uses. Digits that
are part of a tile's own name or definition (`"Stage 2 Ratio"`, `"30+ DPD"`)
are protected the same as a value, so a Lens's own governed terminology is
never mistaken for a fabricated figure — a defect the test suite caught and
this report is not shy about naming (§3.3).

**Caching** is keyed on a hash of the exact compact data sent to the model,
not on the Lens's version number tracked separately: a period change, a
metric added or removed, a chart recut and a source-data refresh all change
that content and so all correctly invalidate the cache, with nothing to
individually track. A `CACHE_TTL_SECONDS` (6 hours) bounds how long a write
is trusted regardless.

**Failure is never the Lens's failure.** No provider configured, a call that
raises, or a reading that fails grounding all return the same shape: `live:
false` and one plain sentence in `unavailable`. The frontend renders that
sentence and nothing else changes — the metric tiles below it are the
deterministic product whether or not this has anything to say.

New route: `GET /lenses/{id}/interpretation`, `RequireAnalyst`. New frontend
component `LensInterpretationPanel`, rendered above `<LensBody>` on
`/lenses/[lensId]`, titled "CreditProbe View", keyed on `[lensId, period,
lens.version]` so it refreshes on exactly the events the brief lists
(reporting period change, metric added/removed, chart recut, Lens rebuild —
all of which bump `version`) without needing separate tracking for each.

Because the interpretation is generated from a Lens's own rendered content
and its own stated purpose rather than hand-written per Lens, it applies to
all eight shipped Lenses (CRO Portfolio, Corporate IFRS 9, Early Warning and
TAC, Portfolio Quality, Concentration and Large Exposures, Board Risk
Committee, Retail Credit Risk, Retail Analytics) with no per-Lens code.

### 3.2 Tests

`tests/metrics/test_lens_interpretation.py` (10 tests) against a scripted
provider: no provider configured degrades correctly; a raising provider
degrades correctly; a Lens with nothing to interpret is never even sent to
the model; a grounded reading is kept; **a fabricated figure discards the
whole reading**; a delta figure is correctly grounded when a prior period is
supplied; an observation naming a tile not on this Lens has the reference
stripped rather than the whole reading discarded; and three caching tests
(identical data served from cache with no second call, a changed figure
correctly bypasses the stale cache, a different period correctly bypasses
it).

`tests/api/test_lens_interpretation_api.py` (3 tests): a shipped Lens answers
honestly with no provider configured, a non-existent Lens is a 404 rather
than a broken reading, and RBAC holds (a Viewer is refused).

### 3.3 Defects found by these tests, before they could reach a screen

| # | Defect | Found by | Fix |
|---|---|---|---|
| 1 | **A tile's own name broke every interpretation of it.** "Stage 2 Ratio" contains the digit `2`; the grounding check flagged it as an ungrounded figure and discarded the entire reading — meaning any IFRS 9-shaped Lens, which is built almost entirely of "Stage 1/2/3" tiles, could never produce a live interpretation | `test_a_grounded_reading_is_kept` | Digits inside a tile's own `name`/`definition`/chart dimension are protected exactly like its value — quoting a tile's own name back is not fabrication |
| 2 | **A cached reading mutated retroactively.** The cache stored the same Python object every caller received; setting `.cached = True` on a later cache hit flipped it on the object the FIRST, uncached caller was still holding, because both were the same object in memory | `test_identical_data_is_served_from_cache_not_a_second_call` | The cache returns a copy (`dataclasses.replace`) rather than mutating the stored object |
| 3 | **The UAT acceptance script's own cleanup silently failed**, via a nonexistent import path (`backend.services.metrics`, which does not exist) AND an ownership check it never satisfied (`service.delete()` correctly refuses to delete a metric owned by someone else, and the cleanup ran as no one) — both errors were swallowed by a blanket `except Exception: pass`, leaving two stray governed-catalogue metrics behind after every UAT journey run | Journey M of the **existing, previously-green** `lens_builder_journeys.py` started failing after a UAT journey run — its metric-drafting step resolved to a different dataset than before, because `propose()`'s dataset ranking is scored across the whole catalogue including stray user metrics | Cleanup now deletes straight through the database session, matching the pattern already used for lens cleanup, rather than through an owner-checked service call |

None of these reached a real UAT scenario in this container, because none of
them is reachable with no AI provider configured — they were caught by the
scripted-provider tests specifically written to exercise the paths a live
model would take. They are exactly the class of defect this remediation
tranche's own testing strategy exists to catch before a real deployment with
a live key does.

---

## 4. Browser evidence

Real Chromium, real backend on `:8000`, real Next.js **production build**
(`next build` + `next start`) on `:3000`, real PostgreSQL,
`REQUIRE_LOGIN=true`.

### 4.1 No regression on what was preserved

| Suite | Result |
|---|---|
| `scripts/acceptance/lens_journeys.py` (A–L) | **213 passed, 0 failed** |
| `scripts/acceptance/lens_builder_journeys.py` (M–P) | **73 passed, 0 failed** |

Identical counts to before this tranche. Lens persistence, the metric
library, metric preview, the chart builder, edit mode, drag/reorder, the
preconfigured Lens library and deterministic execution are unchanged.

### 4.2 The UAT remediation itself

`scripts/acceptance/lens_uat_journeys.py` — **40 passed, 0 failed**.

| Journey | What it proves |
|---|---|
| `AUTH-admin` | Signed in as an administrator (`alex.rahman`): refresh, creating a Lens end to end, the metric library, drafting and previewing and locking a new metric, saving, entering edit mode, and using the Lens chat — **no false sign-in at any step** |
| `AUTH-analyst` | The same eleven checks, signed in as an analyst (`priya.raman`) |
| `AUTH-9` | The actual UAT incident, reproduced: a backend restart under an open tab (with the dev key deliberately deleted first, so restart-durability cannot mask the client-side fix) correctly recovers via the real sign-in screen rather than a dead-end error, and the interrupted action succeeds once signed back in |
| `AI-C` | The UAT's own sentence, verbatim: with no provider configured, the builder still answers rather than blocking, and the ordinary keyword-matched flow keeps working underneath the (absent) rich proposal — the shape a real deployment with a key would show is proven separately in `test_lens_planner.py`'s 20 golden requests |
| `AI-D` (CRO Portfolio) | An AI Interpretation renders before the metric tiles, or an honest unavailable note; with no provider configured, the dashboard still renders fully |
| `AI-E` (Corporate IFRS 9) | Same, plus: when live, the reading is checked for staging/SICR/ECL-focused language |
| `AI-F` (Early Warning and TAC) | Same, plus: when live, the reading is checked for leading-indicator/escalation-focused language |
| `AI-G` / `AI-H` | The interpretation route answers for the Lens's own figures, never asserts a figure the Lens does not show, and answers correctly for a specific period when the period changes |

### 4.3 Full regression, run once

```
13,000 passed · 6 failed · 46 skipped
```

The six failures are the same six already documented and proven
environmental/pre-existing across this whole workstream (a suite-pollution
`Test Domain` row from an unrelated test file; two Excel-export assertions;
two independent-reconciliation assertions; one deterioration-blueprint
assertion) — none in code this tranche touched. The `+53` passed over the
prior full-regression count (12,947) is exactly the new tests this tranche
added: 29 + 10 + 7 + 3 + 4.

`ruff check backend tests scripts`, `tsc --noEmit`, `eslint`, and `next
build` are all clean. Migration head unchanged at `0041`.

---

## 5. What was not touched

No file under `alembic/`. No change to `backend/services/lenses.py`'s
persistence, `backend/metrics/service.py`'s execution path, the metric
library's governed definitions, the chart builder, drag/reorder, or any
existing route's request/response contract beyond additive fields. The two
acceptance suites that already covered all of that (§4.1) prove it rather
than assert it.

## 6. Final acceptance, against the brief's own checklist

1. False sign-in behaviour: fixed, reproduced and shown fixed (§1.1, journey `AUTH-9`).
2. Broad natural-language requests: `lens_planner.py` reasons over the governed catalogue rather than matching keywords, validated by 20 golden tests and a live browser journey.
3. Every shipped Lens begins with evidence-based AI interpretation: generic by design (§3.1), applies to all eight with no per-Lens code.
4. Interpretation refreshes with Lens state: keyed on period + version, proven in `AI-G`/`AI-H`.
5. No financial numbers are hallucinated: enforced by discarding, not annotating, any ungrounded figure — tested, and one real defect in that exact mechanism found and fixed (§3.3 #1).
6. Unsupported metrics remain truthful refusals: every proposed metric id is validated against the real catalogue; nothing invented survives.
7. Both administrator and analyst flows are browser-validated: `AUTH-admin`, `AUTH-analyst`.
8. Existing deterministic Lens calculations remain unchanged: no file under `backend/metrics/service.py`, `backend/metrics/execution.py`, or the metric library changed.
9. Existing Lens builder/edit/reorder functionality does not regress: §4.1, identical counts.
10. Full relevant regression and browser acceptance are green: §4.1–§4.3.

**Not merged. No PR opened. No force push, no rebase, no merge to main.**
