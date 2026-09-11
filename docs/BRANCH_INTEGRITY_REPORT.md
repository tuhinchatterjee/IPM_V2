# Branch integrity: where this remediation was pushed, and what it touched

*Read-only audit. Nothing in this report was produced by rewriting, resetting
or force-pushing anything, and nothing was merged to `main`.*

Collected on 2026-09-11 from the local clone's refs and remote-tracking
reflogs.

## 1. Exact HEADs

| Ref | Commit |
|---|---|
| `origin/claude/project-planner-copilot` | `629fd28df9845b4b8f5e9613565d3b5fd06796c3` |
| `origin/claude/vigilant-darwin-eohyi1` | `629fd28df9845b4b8f5e9613565d3b5fd06796c3` |
| `origin/main` | `3855f9b6f6b231beb6f2193c8a1e219d01596421` |

The two feature branches are **the same commit**. `git rev-list
--left-right --count` between them is `0 0`: neither carries anything the
other does not.

## 2. The commits added to `claude/vigilant-darwin-eohyi1` in this remediation

Ten, `e84bc68..629fd28`, all of them Planner UAT work:

```
7063c88  UAT: the stale completeness panel was a read served from before its own write
b6a8f29  UAT: import order
83401fc  UAT: progress, guidance and clickable completeness, all derived from the plan
3827885  UAT: one save, a progress bar that means something, and an assistant that points
8dae23d  UAT: Custom reads back what it is, and the tests say it reaches the agent
ba4c67b  UAT: the state journey, and the three things it found
9f84baf  UAT: the button audit reaches the creation form, and finds it silent
bc324bf  UAT: the Docker run, and the two test leaks it exposed
0ac9ced  UAT: the five documents, for the second round
629fd28  UAT: the regression numbers, from the run on this HEAD
```

`git merge-base --is-ancestor e84bc68 629fd28` succeeds: **every push was a
fast-forward**. No commit that was on the branch before this remediation
left it.

## 3. Why that branch was advanced

Two instructions named two different branches, and both were followed:

* the session's standing instruction names `claude/vigilant-darwin-eohyi1`
  as the branch to develop on and push to;
* the phase brief named `claude/project-planner-copilot` as the Planner
  branch.

Rather than choose one and silently disobey the other, the same
fast-forward was pushed to both.

This is not new to this remediation. The remote-tracking reflog shows the
two refs moving together for the whole Planner phase — `d7ea50a`,
`e84bc68` and `0ac9ced` appear in both — and
`claude/vigilant-darwin-eohyi1` already held the Planner phase-2 HEAD
(`e84bc68`, pushed 2026-09-07 20:45) before this round began.

## 4. Were Planner-specific commits pushed there?

**Yes.** All ten are Planner work, and `claude/vigilant-darwin-eohyi1` now
carries the whole Planner feature (162 commits ahead of `origin/main`).
That branch is not a Planner-named branch, so a reader going by name alone
would not expect to find the Planner there.

## 5. Does this violate the protected-branch rule?

Split the rule into the things it protects, because the answer differs:

| Convention (SCV acceptance matrix) | Status |
|---|---|
| SCV-BRANCH-01 — `claude/playbook-committee-intelligence` unchanged | **Held.** Still `c17c426`; its reflog shows no push from this session. |
| SCV-BRANCH-04 — no force-push, no history rewrite; every push fast-forward | **Held.** Verified by ancestry above. |
| SCV-BRANCH-05 — nothing merged to `main` | **Held.** `origin/main` is `3855f9b`, unchanged; its reflog's only recent entry is a `fetch --prune` fast-forward, no push. `main` is an *ancestor* of the branch; 0 commits exist on `main` that are not on the branch. |
| SCV-BRANCH-03 — every commit in a phase lands **only** on that phase's branch | **Not held.** The same ten commits are on two branches. |

So: **no protected branch was damaged, and nothing was rewritten or merged
to `main` — but the "one phase, one branch" convention was not honoured**,
because two standing instructions named two branches and both were obeyed.

Every other feature branch is untouched by this session:
`claude/scorecard-validation-intelligence` (`e136b82`),
`claude/playbook-committee-intelligence` (`c17c426`),
`claude/integration-rehearsal`, `claude/what-if-analysis-rebuild` and the
rest show no `update by push` from this session in their reflogs.

## 6. The remedy — described, not performed

Deleting the Planner commits from `claude/vigilant-darwin-eohyi1` would
require a non-fast-forward push, which is exactly what was forbidden. So
nothing was done. The options, for a decision rather than as an action:

1. **Leave both.** The branches are identical and both are honest copies;
   the cost is that a Planner review opened on the wrong branch name shows
   the same diff, which is confusing but not wrong.
2. **Stop pushing to `claude/vigilant-darwin-eohyi1`** from here. The
   Planner history already on it stays where it is; future Planner work
   lands only on `claude/project-planner-copilot`.
3. **Reset `claude/vigilant-darwin-eohyi1`** to whatever it should have
   been. This needs a force-push, and needs to be asked for explicitly.

Option 2 is the one that costs nothing and needs no rewrite.
