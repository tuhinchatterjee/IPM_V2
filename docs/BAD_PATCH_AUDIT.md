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

40 files changed, 17,925 insertions, 538 deletions.

The audit is mechanical where it can be — `git diff d7c910f..HEAD` filtered
for each pattern — and read by eye where it cannot. Each section states what
was searched for and what was found, including the sections where nothing
was.

---

## 1. Was any existing test changed to match a new implementation?

**No. Not one.**

```
git diff d7c910f..HEAD --stat -- 'tests/**'
```

Every file in that diff except one is a NEW file. The single exception is
`tests/corporate/conftest.py`, which is **29 insertions and 0 deletions** —
three added fixtures, no existing fixture touched.

So the audit's central requirement — "for every changed legacy assertion,
document the old invariant, why it was stale or wrong, the stronger
replacement, and the new regression" — has an empty table. **No legacy
assertion was changed, weakened, deleted or replaced in these eight
commits.**

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

Two `except Exception` were added, both in `graphquality.run()`, both
`# pragma: no cover - defensive`, and both doing the OPPOSITE of swallowing:
a check that raises becomes a **REJECT** naming its own failure and blocking
every dependent computation. It is the most severe verdict the module has.

Pinned by `test_a_check_that_raises_becomes_a_reject_not_a_crash`, which
plants a raising check and asserts the REJECT, the exception type in the
message, and that the surviving checks still ran.

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

1. **A missing lake now fails once, loudly.** Two new tests fail rather than
   skip, so a run of forty skips cannot be read as a verification.
2. **A missing confidence is dropped from the mean**, not counted as zero.
3. **A refusal and a failure are now different sentences on the screen**,
   instead of both rendering as an empty panel.

## What the audit did not find

No changed legacy assertion. No widened tolerance. No new xfail. No linter
exclusion beyond one allowlist entry that states its reason in the allowlist
itself. No canned answer. No inflated retrieval budget. No removed threshold.
No authorization bypass. No stubbed browser behaviour.
