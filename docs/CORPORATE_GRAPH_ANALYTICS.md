# The corporate relationship graph — methods, and what they refuse to say

Everything described here operates on `origin = SYNTHETIC_DEMO` data. It
describes no real company, no real ownership structure and no real bank's
book, and nothing in it may be presented as client data.

This document covers the derived layer: what is computed from the observed
graph, how, and — at least as important — the specific wrong readings each
measure invites and what the system does to prevent them.

---

## 1. The observed graph is not the derived graph

Twelve observed edge types are *asserted* by source systems. Five derived
types are *computed* from them:

| Derived | Computed from | Meaning |
|---|---|---|
| `UBO_OF` | integrated ownership ≥ 25% | a natural person's ultimate economic interest |
| `CONTROLS_EFFECTIVELY` | voting closure | binary, absorptive, transitive control |
| `MEMBER_OF` | control components + validated interdependence | connected-counterparty candidate group |
| `CONNECTED_TO` | the same | the pairwise form |
| `SIMILAR_TO` | Jaccard over shared evidence | a *candidate* for investigation, and nothing else |

Every derived object carries `computed_as_of`, `derivation_method`,
`pipeline_version`, `policy_version` and a validation status. A derived
relationship that cannot say where it came from is not auditable, and the
whole point of the layer is that a reviewer can ask any edge "why are you
here".

## 2. Integrated ownership: `Ã = A(I − A)⁻¹`

Solved as `(I − A)X = A`, per weakly connected component.

**Why per component.** Ownership does not cross a component boundary, so the
block-diagonal solve gives identical answers and lets one defective family
group be refused without blinding the rest of the portfolio.

**Why it can refuse.** The series converges only where the spectral radius
ρ(A) < 1. A component above that describes a structure claiming more than all
of some entity. The correct output there is the defect, not a number, so
`stake()` and `owners_of()` RAISE for entities in a refused component. Their
block of the matrix is left at zero, and returning that zero as an answer
would be precisely the manufactured value the design forbids.

**Why a stake can exceed 100%.** Integrated ownership sums every path length.
Where reciprocal holdings route ownership back through the owner, the loop
multiplies every stake by `1/(1 − k)` and totals above 100% are the arithmetic
working correctly. They are reported and FLAGGED, never capped: capping would
silently replace the quantity the method defines with a different one. A stake
above 100% in a component with **no cycle** would be a genuine defect — there
is no mechanism that could produce it — and the regression asserts it never
happens.

**What ρ(A) does not bound.** It bounds convergence, not column sums. A
shareholder register claiming 188% of a company solves perfectly well and
returns a confidently wrong answer, which is why `GQ-01` exists and why it
REJECTS rather than flags.

## 3. Control closure

Control is **binary, absorptive and transitive**. 51% of 51% is 26% of the
economics and 100% of the control. Substituting the economic percentage for
the voting percentage is the single most common way a group-structure
analysis goes wrong, so `ownership_pct` and `voting_pct` are separate columns
and the closure reads only the second.

Three rules build the direct graph, in precedence order:

1. **explicit `CONTROLS`** — an observed assertion outranks any inference;
2. **majority voting** — a holder above 50% of the votes;
3. **de-facto voting** — a holder above 30% who is strictly the largest,
   which is the case where a 35% holder facing a dispersed register controls
   in practice.

Strongly connected components are condensed (mutual control is one bloc) and
reachability is taken over the condensation DAG. The 50% / 30% / 25%
thresholds are **UNVERIFIED POLICY PARAMETERS**: they are carried from the
framework document, not confirmed as currently binding law, and every
provenance payload says so.

> **B54.** Control closure and proportional ownership give different sets *by
> design*. Neither is a substitute for the other, and a system that reports
> only one of them is answering a question nobody asked.

## 4. Connected counterparties

The order is the rule:

1. effective control gives the candidate relationships;
2. weak components are taken over **that** graph;
3. validated economic interdependence merges further members in;
4. every member keeps the criterion that put it there.

**Never weak components over raw `OWNS`.** A 2% shareholding is an ownership
edge and is not a reason to place two borrowers in one obligor group. Run that
rule over the whole register and a common minority investor, a shared funder
or the assessing bank itself connects the entire portfolio into a single
"group" that is both useless and confidently wrong. The percolation regression
measures exactly this.

Eight interdependence predicates are tested, each recording its inputs,
threshold, evidence source, verification date, policy version and a status of
VALIDATED / CANDIDATE / REJECTED. Only VALIDATED rows merge. A CANDIDATE row
is a question for a human.

> **B54.** Graph connectivity is not regulatory connectedness. These are
> candidate groups for assessment under the institution's own approved
> criteria, not a determination.

## 5. Network analytics

Five families, each answering a different question, none of them a credit
measure.

### DebtRank

`W[i, j] = min(1, X[i, j] / C[i])` — the exposure of `i` to `j` as a fraction
of `i`'s own capital, capped at one because a counterparty cannot cost more
than everything you have. Three states, and the rule that gives the measure
its name: **a node propagates exactly once**, then goes INACTIVE. That is what
stops a cycle amplifying a shock forever, and it is precisely the difference
between DebtRank and a naive cascade.

Worked example, verified in the test suite: A exposed to B (50), B exposed to
C (50), capital 100 each. Shock C fully. B takes `1.0 × 0.5 = 0.5`; A takes
`0.5 × 0.5 = 0.25`; impact is the mean over the two non-seed nodes, `0.375`.
The seed's own distress is excluded — the question is what the network lost,
not what the borrower that failed lost.

> **B54.** DebtRank is network analytics and early warning. It is NOT an
> expected credit loss, NOT a capital methodology and NOT a regulatory
> measure of anything. It reads like a loss rate — it is a fraction, it rises
> with distress — which is exactly why the caveat travels on every payload.

### PageRank

**Forward** ranks transmitters: rank flows along the exposure arrow, so a
borrower many others are exposed to scores highly. **Reverse** ranks the
exposed: the arrow is flipped, so a borrower positioned to be hurt scores
highly. **Personalised** ranks relative to a seed.

Direction carries the meaning and is the thing most easily got backwards. The
tests assert that forward and reverse *disagree* on a star graph; a run where
they agree has lost the direction and is measuring nothing.

Dangling nodes have their rank redistributed rather than dropped, so the
vector sums to one.

### Betweenness and communities

Brandes betweenness per component — who sits on the paths between others.
Louvain modularity with sorted iteration and lowest-label tie-breaking, so two
runs give the identical partition. A community label that moves between runs
cannot go in a report.

### Network Risk Score

```
NRS = 100 × (0.45 × nDebtRank + 0.35 × nForwardPageRank + 0.20 × nBetweenness)
```

Weights are published constants, not parameters: a score whose weights move
between runs cannot be compared across quarters, and a reviewer who cannot see
the weights cannot challenge the score. The three components are stored
alongside the score rather than discarded, because a borrower can be high on
one and low on the others and that is the interesting case.

Normalisation is min-max over the scored population. A degenerate population —
every borrower identical — normalises to **zero**, not to one: mapping "no
spread" onto the top of the scale would hand every borrower in a flat network
the maximum score.

> **NETWORK RISK SCORE — RELATIVE NETWORK RANKING / NOT A PROBABILITY /
> NOT PD / NOT A RATING / NOT IFRS 9 STAGE / NOT ECL.**
> It ranks borrowers against each other in this population and carries no
> meaning outside it. The banner travels on every payload and on every row of
> `corporate_connected_groups`.

### SIMILAR_TO

Jaccard over shared directors, registered addresses and funding channels.
Sector is deliberately excluded: every borrower has one, thousands share it,
and including it would make the whole population look mildly similar to itself
and drown the real signal. Tokens shared by hundreds of borrowers — serviced
offices, funding channels — carry no information about any pair and are
skipped.

Two empty evidence sets score **zero**, not one. Two borrowers about whom
nothing is known are not similar; they are unknown, and the `0/0 = 1`
convention would rank every data gap as a perfect match and put the
least-documented borrowers at the top of the list.

The threshold (0.30) is an **UNVERIFIED POLICY PARAMETER** calibrated for this
synthetic population. The right threshold on a real book is an empirical
question about that book's address and director distributions.

> A `SIMILAR_TO` edge is a **HIDDEN RELATIONSHIP CANDIDATE**, drawn dotted and
> visually distinct. It does NOT establish control, does NOT establish
> beneficial ownership and does NOT place either borrower in a connected
> group. Three explicit flags on the edge say so and the tests assert them.

## 6. Confidence

The confidence of a derived relationship is the **weakest** assertion on the
evidence path — not the average, not the product.

* The average lets a long chain of registry filings hide one relationship
  manager's note.
* The product punishes length rather than weakness: six certain steps would
  come out less confident than two doubtful ones.
* The minimum says the true thing: a conclusion is exactly as good as the
  worst assertion it depends on.

An empty path is 0.0 and LOW, not 1.0. A derived relationship with no evidence
beneath it is the case a reviewer most needs to see, and defaulting it to full
confidence would bury it.

Confidence is a property of the **source**, not a number invented per edge: a
registry filing is worth more than a relationship manager's note whatever it
says, and attaching the number to the source is what makes that auditable.

Both the weakest (`graph_confidence`) and the mean (`relationship_confidence`)
are published, because they answer different questions.

## 7. Graph data quality — fifteen checks that block

| ID | Check | Worst verdict | Blocks |
|---|---|---|---|
| GQ-01 | shareholder register totals | REJECT | effective ownership, chains |
| GQ-02 | single stake within [0, 100] | REJECT | effective ownership, UBO, chains |
| GQ-03 | no self-ownership edge | REJECT | effective ownership, control closure |
| GQ-04 | edge endpoints resolve to nodes | REJECT | everything |
| GQ-05 | borrowers present in the graph | REJECT | centrality, communities, NRS |
| GQ-06 | validity interval ordering | REJECT | everything |
| GQ-07 | no knowledge from after the as-of date | REJECT | everything |
| GQ-08 | no duplicate assertions | FLAG | effective ownership |
| GQ-09 | confidence present and in [0, 1] | REJECT | effective ownership, UBO, closure |
| GQ-10 | share of low-confidence evidence | FLAG | effective ownership, UBO |
| GQ-11 | evidence recency | FLAG | effective ownership, UBO |
| GQ-12 | exposure amounts non-negative | REJECT | DebtRank, NRS |
| GQ-13 | guarantees fully specified | REJECT | DebtRank, connected groups |
| GQ-14 | no single dominant component | FLAG | centrality, communities |
| GQ-15 | declared groups have internal edges | FLAG | connected groups |

**REJECT blocks the computation.** That is the whole point. A quality report
that is written, stored and then ignored by the engine is decoration; the
value is in the engine refusing to publish an effective-ownership percentage
computed from a register that claims 188% of a company. The alternative —
compute anyway, print a warning somewhere — produces a number that looks
exactly like a correct one and will be read as correct.

**Blocks close over a dependency graph.** NRS is built from DebtRank and
centrality, so a REJECT reaching either reaches the score. A composite that
survives the failure of its own inputs still prints a number, and nothing on
the screen says the number is now meaningless.

**Rejects are scoped.** Four impossible registers out of 4,179 block effective
ownership for the twelve entities in their contaminated components — the
weakly connected components those registers sit in, because that is the unit
the solve works on — and for nobody else. A gate that blanks the whole
Borrower 360 over four rows is a gate that gets switched off within a week.

**A check that raises becomes a REJECT naming its own failure.** A gate that
crashes has told the caller nothing, and the caller will be tempted to skip it.

## 8. Four kinds of absent

The Borrower 360's graph fields never show a blank and never show a zero that
means "unknown".

| Sentinel | Means |
|---|---|
| `NOT COMPUTED` | the derivation did not run for this quarter at all |
| `NOT_AVAILABLE` | it ran, and this borrower is not in that graph at that date |
| `NOT_APPLICABLE` | the measure does not apply — a group role for a borrower in no group |
| `DATA_QUALITY_BLOCKED` | the input was rejected, so the computation did not run; the reason is in the DQ register keyed by the same borrower and quarter |

Zero is reserved for exactly one thing: **a count that was taken and came back
empty**. `director_count = 0` means the graph was searched and there are no
directors, which is a measurement. A borrower outside the exposure network does
not have a DebtRank impact of zero — it does not have one.

A test asserts that all three of the derived-layer sentinels actually appear in
the output. A distinction nothing exercises is a distinction that is not being
made.

## 9. What the graph changed about the credit numbers

`corporate_limits.group_utilisation_pct` stood at null with status
`NOT YET COMPUTED` from the day the dataset was created, because the group is a
derived answer and the derivation did not exist. It does now. As at Q2 2026,
**157 connected groups exceed the 10% investigation trigger** against the
eligible capital reference — an exposure concentration that is invisible at the
single-name level and that only the group derivation can see.

The 25% group limit and the 10% trigger are **UNVERIFIED REGULATORY
PARAMETERS** and every row says so.

## 10. Determinism and cost

Every algorithm iterates over sorted structures and stops on a stated tolerance
or a stated cap. Two runs on the same graph give the same numbers, and a
regression asserts the whole derivation is byte-identical between runs.

One quarter over the full book (3,800 borrowers, 9,333 ownership nodes, 2,960
exposure nodes):

| Stage | Seconds |
|---|---:|
| ownership graph | 4.3 |
| effective ownership | 2.6 |
| control closure | 2.5 |
| connected groups | 0.2 |
| DebtRank, all seeds | 4.0 |
| centrality (PageRank ×2, betweenness, Louvain) | 1.2 |
| Network Risk Score | 1.3 |
| quality gate | 1.0 |
| **total** | **≈18** |

Two of those numbers are the result of fixing something that was accidentally
quadratic or worse:

* control closure was **>600s** as a dense Warshall over ~9,000 blocs. Per
  component: 2.5s, identical answers, and a regression pins it under 60s.
* DebtRank rebuilt its 2,960 × 2,960 impact matrix once **per seed** — the
  sweep's entire cost, and none of it arithmetic anyone needed. Hoisted.
