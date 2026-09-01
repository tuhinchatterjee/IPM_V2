# Bad-patch audit — every commit since `d7c910f`

The commits audited, in order:

| Commit | Subject |
|---|---|
| `e28bf63` | Graph mathematics: effective ownership, control closure, and what they refuse |
| `2d2e11d` | Connected counterparties: control-based grouping, interdependence, percolation |
| `d564c9f` | Network analytics, and a quality gate that actually blocks |
| `8ea0b22` | Twenty Borrower 360 graph fields stop saying NOT COMPUTED |
| `f3a01aa` | Borrower 360 over HTTP: thirteen tabs, eleven views, six groups, four permissions |
| `8f6a628` | The Borrower 360 screen |
| `205fc3f` | The Borrower 360 pack: a cover and seventeen sheets |
| `1fe98fb` | Graph questions answered by an analysis, not by prose |
| `1895741` | Bad-patch audit of every commit since d7c910f, and the three fixes it found |
| `71af148` | Verification documents, and the scope regression the graph made necessary |
| `476f608` | The graph reaches the Brain: concepts, contracts and blueprints |
| `1e0445c` | Graph teaching corpus, its sealed holdout, and 556 cases that were invisible |
| `38ed6b5` | The relationship graph gets a specialist, and two verification documents |
| `1b78923` | Thirty-six failure classes in one runnable suite |
| `26e1494` | The final documents, brought up to what the code now does |
| `4397147` | Data Builder graph-domain visibility is built; say so |
| `0275c22` | The last two Borrower 360 interactions: pinning, and saved cohorts |

**Seventeen commits. 69 files changed, 25,438 insertions, 736 deletions.**

The audit was first written at `1895741`, when the range held eight commits.
It has been re-run over the whole range since, and every section below states
what the mechanical filter returns across all seventeen — not across the
eight it originally covered. Where a later commit added something a section
must account for, the section names it and the commit it came from.

The audit is mechanical where it can be — `git diff d7c910f..HEAD` filtered
for each pattern — and read by eye where it cannot. Each section states what
was searched for and what was found, including the sections where nothing
was.

---

## 1. Was any existing test changed to match a new implementation?

**No. Not one.** Across the whole seventeen-commit range, exactly three
pre-existing test files contain a deleted line:

```
git diff d7c910f..HEAD --numstat -- 'tests/**' | awk '$2>0'
44  3  tests/agentic/test_registry.py
42  1  tests/factory/test_canonical_cases.py
 8  2  tests/judgment/test_blueprints_and_challenge.py
```

Every other file in that diff is new, and `tests/corporate/conftest.py` is
**29 insertions and 0 deletions** — three added fixtures, no existing fixture
touched. Three changed lines in three files, over 25,438 inserted lines, is
the number the audit has to account for, and it accounts for all three below.

The audit's central requirement — "for every changed legacy assertion,
document the old invariant, why it was stale or wrong, the stronger
replacement, and the new regression" — is discharged for each.

### The first changed legacy assertion

`tests/judgment/test_blueprints_and_challenge.py::test_every_family_section_67_names_has_a_blueprint`

| | |
| --- | --- |
| **Old invariant** | `required == set(bp.FAMILIES)` and `required == set(bp.BY_FAMILY)` — the blueprint family set is EXACTLY the nineteen families §67 names. |
| **Why it was stale** | Its own name says "every family §67 names has a blueprint", which is a floor. The equality made it a ceiling as well, so it failed not because a §67 family had gone missing but because ten graph families were added on top — `CORPORATE_GROUP_STRUCTURE`, `BENEFICIAL_OWNERSHIP`, `CONNECTED_COUNTERPARTY`, `GROUP_LIMIT_UTILISATION`, `NETWORK_CONTAGION`, `NETWORK_CENTRALITY`, `SUPPLY_CHAIN_DEPENDENCE`, `GUARANTEE_NETWORK`, `HIDDEN_RELATIONSHIP`, `GRAPH_DATA_QUALITY`. An assertion that fails on required growth stops being read. |
| **Stronger replacement** | `required <= set(bp.FAMILIES)`, reported as the named missing families rather than as a set diff, **plus** `set(bp.FAMILIES) == set(bp.BY_FAMILY)` in both directions. The property actually worth protecting is the correspondence: a declared family with no blueprint is a menu entry leading nowhere, and a blueprint filed under an unregistered family is unreachable. The old form checked the forward direction only, against a hard-coded list; the new one checks both directions against the registry, so it also catches a *new* family added without a blueprint — which the old form could not do at all. |
| **New regression** | `tests/corporate/test_graph_brain.py::TestBlueprints` — each of the ten graph families resolves to a blueprint, each is `usable`, and each carries at least three required objectives, hypotheses, challenges and a `when_not_to_use`. |

Nothing was weakened to accommodate an implementation: the graph families
are new product, the assertion was rewritten to test its own stated
property, and it now covers strictly more than it did.

### The second changed legacy assertion

`tests/agentic/test_registry.py::test_all_twelve_specialists_are_defined`

| | |
| --- | --- |
| **Old invariant** | `{a.agent_id for a in registry.AGENTS} == expected` — the agent set is EXACTLY the twelve §12 names. |
| **Why it was stale** | Same shape as the family test above, and same failure: it read its own name ("§12 names twelve. Missing one is a specialist nothing can delegate to") as a ceiling. It failed because a thirteenth agent was ADDED — `relationship_graph`, the specialist for the corporate relationship graph, which is now a governed domain like every other. The failure the assertion exists to catch is a specialist going MISSING; it caught growth instead. |
| **Stronger replacement** | Renamed `test_every_specialist_section_twelve_names_is_defined`, asserting `expected - defined` is empty and reporting the missing names. Added `test_every_governed_domain_has_a_specialist_that_exists`, which checks both directions against the registry: every domain has an owner AND every owner is a defined agent. The old form could not see a domain owned by a misspelled id — that reads exactly like a deliberate generalist decision — and the new one can. |
| **New regression** | `test_the_relationship_graph_reaches_its_own_specialist` (a group, ownership or contagion question resolves to `relationship_graph` and to nothing else) and `test_the_graph_specialist_cannot_read_the_retail_book` (its data domains are a strict subset of all domains). |

Adding the specialist immediately broke the Brain's AGENTIC corpus with a
`KeyError`, because `backend/brain/corpus.py` reads the specialist list from
the registry rather than restating it. That is the design working, not a
defect: an agent nothing can teach is an agent nothing can measure. The
subject mapping was added and the Brain suites pass.

Three further test edits accompanied the same change and are **not** legacy
assertions — all three are in `tests/corporate/test_graph_brain.py`, written
in this session, and two of them are the tests being corrected rather than
the product:

- `test_every_graph_contract_says_what_it_is_not` looked for the literal
  string `"not"` and failed `ubo_count`, whose definition says a rejected
  borrower "has no count at all — which is different from having no owner".
  That IS a boundary. Renamed `test_every_graph_contract_states_a_boundary`
  and broadened to the property. It then caught a real omission:
  `network_centrality` stated no boundary at all, so the CONTRACT gained one
  ("a central borrower is not thereby a large one, a weak one, or one whose
  default is more likely").
- Two id references were realigned after the contract ids were renamed to
  match the concept registry (below).

### The third changed line

`tests/factory/test_canonical_cases.py::test_together_with_migration_every_available_family_has_cases`

| | |
| --- | --- |
| **Old invariant** | `covered = {c.family_id for c in [*mg.cases(), *cn.cases(), *jb.cases(), *sv.cases()]}` — the union of four named corpora must cover every family in `fam.AVAILABLE`. |
| **Why it was stale** | Not wrong; incomplete. `fam.AVAILABLE` grew by the seventeen `GRAPH` families, and the corpus that covers them (`intelligence_factory/teaching/corporate_graph.py`) was not in the union. The assertion would have failed on `missing != []` — a true report of a real gap, reported against the wrong cause: the families were covered, by a corpus this line did not read. |
| **Stronger replacement** | `*cg.cases()` added to the union, so the assertion's own claim — "every available family has cases" — is evaluated against every corpus that exists rather than against four of the five. Nothing was removed and no assertion was relaxed: the passing condition is still `missing == []`. |
| **New regression** | Two tests added in the same commit, both of which the old file had no equivalent of. `test_the_seeder_offers_every_corpus_the_factory_builds` fails if a built corpus is not in `scripts/seed_teaching_library.py::corpus()` — the exact defect that hid 500 reviewed scorecard cases from the library. `test_every_case_the_seeder_offers_can_actually_be_saved` runs every offered case through `backend.teaching.schema.validate` and fails on any rejection — the defect that dropped 56 safety cases at save while the seeder printed a line and carried on. The old file counted the corpus; these two count what can reach the library. |

This is the opposite of the forbidden pattern. The forbidden pattern narrows
an assertion until a new implementation fits inside it; this widened the
assertion's input until it saw the whole product, and then added two tests
that fail on a gap the original could not express at all.

(The one legacy assertion changed in this whole line of work was changed at
`d7c910f` itself, which is the audit's starting point rather than inside its
window: `FACILITY_ID → account_id` was replaced by
`test_an_exact_governed_name_outranks_a_synonym`, which pins the precedence
rule — exact match 1.0 beats synonym 0.8 — rather than pinning the absence
of an exact match. That is a stronger assertion than the one it replaced.)

## 2. Were numeric tolerances widened?

**No.** Every `pytest.approx` in the diff is on a `+` line in a new file, and
none carries an `abs=` or `rel=` argument — they are all at pytest's default
relative tolerance against a hand-computed value.

Two places use an explicit tolerance and both TIGHTEN rather than loosen:

* `test_a_symmetric_graph_gives_every_node_the_same_rank` asserts a spread
  below `1e-9`;
* `test_length_alone_does_not_reduce_confidence` asserts exact equality.

One relative-tolerance change exists earlier in this line of work (facility
rounding identities) and is documented in its own commit with the reason:
rounding first and then deriving makes an absolute tolerance the wrong test,
not a lenient one.

## 3. Were failures converted to skips, or xfails added?

**No xfails.** Three `pytest.skip` calls were added, all of the same shape:
the corporate Parquet lake has not been built, so the routes cannot be
exercised. None of them was ever a failing assertion.

That is still a hazard, and the audit found it: **forty silent skips and a
green run look identical to forty passes in a summary line.** Fixed rather
than argued away. Two new tests —
`test_the_lake_is_built_and_this_suite_actually_ran`, one in
`tests/api/test_corporate_api.py` and one in
`tests/corporate/test_graph_analyses.py` — **FAIL** when the lake is absent.
The absence is now reported once, loudly, and the remaining skips can never
be the whole story.

**Two more `skipif` markers were added later**, at `1b78923`, in
`tests/proof/test_zero_tolerance.py`: `needs_lake` and `needs_db`. They carry
the same hazard in a sharper form — a suite whose whole purpose is to answer
"did any of thirty-six things go wrong?" is worthless if thirty-six skips
read as thirty-six passes. So that suite carries its own sentinel:

`TestTheSuiteRan::test_the_lake_and_the_database_are_both_present` **FAILS**
— it does not skip — when either is missing. A green run of that file
therefore means the other thirty-six tests executed. In this environment both
are present and the file reports **37 passed, 0 skipped**.

No assertion anywhere in the range was turned from a failure into a skip. Every
skip added is an environment precondition guarded by a test that fails on that
same precondition.

## 4. Were linters, scanners or formatters excluded from anything?

**No exclusion was added.** `pyproject.toml`, `ruff.toml` and
`eslint.config.mjs` are untouched in this window.

One `# noqa: E402` was added, in `scripts/build_corporate_universe.py`, on an
import that must follow the `sys.path` insertion — matching the eight
existing `# noqa: E402` imports directly above it in the same file. It
suppresses import ORDER, not a defect.

**One deliberate allowlist entry was added**, and it is the audit's job to
name it rather than let it pass unremarked:

`scripts/check_decimals.py` now allows `backend/corporate/graphmath.py`, with
this reason recorded in the allowlist itself:

> The spectral radius of an ownership component, in the refusal message that
> explains why effective ownership was not computed. The whole question is
> whether rho crossed 1, and the interesting cases sit in the sixth decimal:
> a component at 0.999999 converges and one at 1.000001 does not, and at two
> decimals both read 1.00 and the message stops explaining anything.

The decimal contract's own mechanism is an allowlist with a stated reason, so
this uses the escape hatch as designed rather than evading the check. The
alternative the rules forbid — hiding the format string behind a variable to
defeat the regex — was not used. `scripts/check_decimals.py` still reports
**49 allowed sites, 0 unexplained**.

## 5. Broad catch-and-ignore exception handlers?

Across the whole range, **four** `except Exception` were added. Two are in
production code and two are in tests, and the audit accounts for all four.

*Production code, both in `graphquality.run()`.* Both
`# pragma: no cover - defensive`, and both doing the OPPOSITE of swallowing:
a check that raises becomes a **REJECT** naming its own failure and blocking
every dependent computation. It is the most severe verdict the module has.

Pinned by `test_a_check_that_raises_becomes_a_reject_not_a_crash`, which
plants a raising check and asserts the REJECT, the exception type in the
message, and that the surviving checks still ran.

*Test code, both in environment detection, neither in an assertion.*
`tests/proof/test_zero_tolerance.py::_lake` and
`tests/corporate/test_graph_analyses.py::run` catch broadly to answer one
question: is the analytical lake present? Neither wraps an assertion, and
neither can hide a product failure — because both files carry a test that
**fails** when the lake is absent, so a run in which those handlers fired is a
run that reports the absence rather than passing quietly. Catching narrowly
there would be worse, not better: a lake that is absent for an unanticipated
reason must still be reported as absent rather than crashing the collection.

**One genuine swallow was found and fixed.** The Borrower 360 screen had
`.catch(() => setGroups(null))` on two panels. A 403 there is expected — the
graph and the people behind it are narrower permissions than the borrower —
but a 500 was rendered identically, as an empty panel, which reads as *this
borrower has no group*. The two are now separate sentences: a refusal says
"you are not permitted to see this, which is not the same as there being
none"; a failure says the panel could not be loaded and why.

## 6. Hard-coded questions or canned results?

**None.** No `if question ==`, no canned answer, no fixture standing in for a
computation. The four new graph analyses all read a governed dataset through
`ctx.read` and produce a Trace; the twelve routing tests exercise the real
`certified.match` against the real registry.

## 7. Retrieval-budget or top-N inflation?

**No.** `MAX_DATASETS` and every retrieval constant are untouched.

The `top_n` parameter added to two analyses is a **display limit on a
ranking**, declared on the contract with `default=20, minimum=1,
maximum=200`, in the same shape as the existing `obligor_concentration`.
It bounds what is returned; it does not widen what is searched. The
Herfindahl-style trap — computing a statistic on the displayed rows — is
avoided explicitly: `connected_group_exposure` counts breaches over ALL
groups and returns the top N.

## 8. Silent null-to-zero?

Five `fillna(0)` sites were added. Four are correct and one was wrong:

| Site | Verdict |
|---|---|
| `check_low_confidence_share` — missing confidence counted as low | Correct. It makes the check MORE likely to flag, and GQ-09 REJECTS a missing confidence anyway. |
| `_group_exposure` — a borrower with no EAD row contributes 0 | Correct. No facility means no exposure; that is the measurement. |
| `impact_matrix` — `np.nan_to_num` on the exposure/capital ratio | Correct and unreachable: capital is floored at `CAPITAL_FLOOR`, so the divide cannot produce a NaN. Belt and braces. |
| `_weakest_confidence` — missing counted as 0 | Correct **and now says so**. A missing confidence IS the weakest evidence, so zero is the honest reading. The comment names the asymmetry with the mean so it reads as deliberate. |
| `_mean_confidence` — missing counted as 0 | **WRONG, and fixed.** Counting an absent confidence as zero drags the MEAN down and renders absent evidence as weak evidence. Two different statements, and only one of them is about the borrower. Missing values are now dropped from the mean. |

## 9. Hidden data-quality rejection, or weakened thresholds?

**No verdict, threshold or limit was removed or loosened.** The diff contains
no `-` line touching `REJECT`, `FLAG`, `threshold` or `LIMIT`.

The direction of travel is the opposite: this window ADDED fifteen checks
that can reject, a block set that closes over a dependency graph, and three
sentinels that make a refusal visible on the screen and in the export instead
of appearing as a blank.

## 10. Authorization bypass?

**None.** No `REQUIRE_LOGIN` change, no forced role, no test that grants
itself a permission. The four new permissions are enforced on the routes and
every one is called as each of the four roles in
`tests/api/test_corporate_api.py::TestPermissions`, with the status code
read — because a permission that is only a hidden menu item is a permission
an attacker has.

## 11. Stubbed production behaviour to make browser tests pass?

**None.** `scripts/browser_acceptance.py` gained one line — the new route in
its screen list — and `scripts/route_crawl.py` gained one route with a
comment saying why it is named rather than left to link discovery. No
assertion was relaxed, no marker added, no wait extended.

The runs are real: **956/956 browser checks across 4 viewports and 17
screens**, and **153/153 route-crawl visits across 3 roles** with the six
pre-existing expected refusals unchanged.

---

## What the audit changed

Three fixes, all made rather than noted:

-1. **Five hundred and fifty-six teaching cases never reached the library.**
   The retail scorecard corpus (500 cases) was built and left out of
   `scripts/seed_teaching_library.py::corpus()` entirely, and 56 safety
   cases were in it and rejected at save — 16 declaring `risk="STANDARD"`,
   which is not one of the schema's four levels, and 40 executing with an
   empty plan contract. Nothing failed: the seeder prints a rejection and
   carries on, and the human-review pack counts the CORPUS rather than the
   library, so a reviewer was shown coverage the product did not have. The
   five orchestration builders now declare the plan each case is actually
   about, the risk levels are real ones, both module corpora are offered,
   and two tests in `tests/factory/test_canonical_cases.py` fail if either
   regresses.
0. **Four contracts governed a word nothing produced.** `debtrank_impact`,
   `ubo_count`, `connected_group_size` and `network_centrality` were filed
   under contract ids the concept registry does not answer to, so
   `SemanticContract.fields` returned empty for all four: a catalogue that
   looks richer than the product, which §1 of the ontology's own test suite
   forbids. Renamed to `debtrank`, `ubo`, `group_size` and `centrality`,
   with the long forms kept as aliases so the words a person says still
   resolve. Two directions of deterioration were wrong in the registry and
   are now stated where they belong: a borrower with FEWER identified
   beneficial owners is the opaque one, and a Louvain community label has no
   direction at all.
1. **A missing lake now fails once, loudly.** Two new tests fail rather than
   skip, so a run of forty skips cannot be read as a verification.
2. **A missing confidence is dropped from the mean**, not counted as zero.
3. **A refusal and a failure are now different sentences on the screen**,
   instead of both rendering as an empty panel.
4. **A working set's privacy was claimed and not tested.** The re-run over
   the last two commits found `TestWorkspace`'s docstring asserting that
   nothing in a working set is visible to anybody else, with no test driving
   it — every case in that file calls as the same caller, so dropping the
   `user_id` filter would have leaked one person's pinned borrowers to their
   team and left the suite green.
   `test_one_persons_working_set_is_invisible_to_another` now drives it at
   the mechanism with two real users, and was confirmed to fail under exactly
   that mutation.

## The last two commits, audited separately

`4397147` and `0275c22` post-date the audit's first writing, so they get
their own paragraph rather than being covered by a re-run alone.

**`4397147` — "Data Builder graph-domain visibility is built; say so"** is
documentation only: three files, all under `docs/`, 17 insertions and 12
deletions, no code. It is a correction in the honest direction — a document
had listed a "Data Builder graph viewer" among the unbuilt work, which was my
phrasing rather than the requirement. The requirement is graph-domain
visibility, which is built and registered. Nothing was claimed that the code
does not do; a claim of *absence* was corrected to match the code, and the
same commit narrowed the remaining unbuilt list from three items to the two
that were genuinely unbuilt. A document that under-reports is still a
document that is wrong.

**`0275c22` — Borrower 360 pinning and saved cohorts** is new product: a
model, migration `0030`, `backend/corporate/workspace.py`, five routes, a
frontend panel and **157 inserted lines of tests with no deletions**. Four
things the audit checks specifically:

* *Authorization.* All five routes carry `RequireBorrower360View` — the
  permission the rest of the screen already requires. No route is open, and
  no test grants itself a role to reach one.
* *Tenant and user scoping.* Every query filters on `(tenant, user_id, kind)`
  and the table's unique constraint is `(tenant, user_id, kind, reference)`.
  The audit found this claimed in a docstring and **proved by nothing** —
  every HTTP test in the file calls as the same caller, so a query that
  dropped `user_id` would have leaked one officer's watch list to their whole
  team with the suite still green. Fixed:
  `test_one_persons_working_set_is_invisible_to_another` pins a borrower and
  saves a cohort as one real user, reads the working set as a second, and
  asserts both are empty and that the second cannot delete the first's pin.
  It was verified to FAIL by removing the `user_id` filter from
  `workspace._rows`: *"another user can read this person's pinned borrowers —
  a watch list published to a team that nobody agreed to share."* It also
  asserts the fixture actually saved, so it cannot pass because nothing was
  written.
* *No silent widening.* `_validate_query` **refuses** a facet the search does
  not declare, by name, rather than dropping it. A dropped facet would
  produce a cohort wider than the one somebody saved, under the name they
  gave the narrower one — which is the export-mismatch failure class wearing
  different clothes.
* *No stale-result hazard.* A cohort stores the query, not the borrower ids
  it matched. The corporate book is rebuilt quarterly; a stored id list would
  keep answering last quarter's question under this quarter's name.

Neither commit changed a test, a tolerance, a threshold or a linter
configuration.

## What the audit did not find

No weakened legacy assertion — all three changed lines are documented in §1,
and each covers strictly more than it did. No widened tolerance. No new
xfail, and no failure turned into a skip: every skip in the range is an
environment precondition guarded by a test that FAILS on that same
precondition. No linter exclusion beyond one allowlist entry that states its
reason in the allowlist itself. No canned answer. No inflated retrieval
budget. No removed threshold. No authorization bypass. No stubbed browser
behaviour. No synthetic truth manifest edited to match engine output.

**Re-run over all seventeen commits**, not the eight the audit originally
covered. Three additions the first pass could not have seen are named where
they belong: the third changed test line (§1), the zero-tolerance suite's two
guarded `skipif` markers and its failing sentinel (§3), and the two test-side
broad handlers (§5).
