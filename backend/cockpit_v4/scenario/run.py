"""One confirmed scenario, up to three methods, one cohort, one baseline.

Section 19 and section 12.3. The methods are alternative ANSWERS to one
question, and the single most damaging thing this module could do is let
them stop being that:

* **One cohort.** Every method reads the same frozen membership, the same
  reporting period and the same baseline. Two methods over two populations
  are not two estimates of one thing.
* **One baseline.** Read once, from the book, and handed to each method.
  Recomputing it per method would let rounding or an eligibility rule move
  it, and a comparison of changes against different starting points is not
  a comparison.
* **Never composed.** Delta's factor is not multiplied by the emulator's
  estimate, and a macro move is applied once. `infer.refuse_composition`
  is the ban and `Run.compare` is what is offered instead: the methods side
  by side, their difference stated, and the reason for it explained rather
  than averaged away.
* **An unavailable method is unavailable.** It carries its status and its
  reason and no number. A zero would read as "no effect", and substituting
  another method's answer would be worse still.

## Coverage, which is where a comparison quietly goes wrong

Methods do not always cover the same rows. Delta cannot scale a field it
has no factor for; the emulator can only predict where its features are
present; a user assumption covers whatever the reader named. Comparing
totals over different populations then reports a difference that is mostly
population.

So every method records the keys it actually covered, `Coverage` reports
the intersection, and `Run.compare` publishes **two** comparisons where
they differ: each method over its own population, and every method over the
rows all of them covered. The second is the like-for-like one and it says
so.

## What runs this

Several steps of ONE `execute_analysis` submission. No sixth tool: the
cohort is already frozen in the thread, the methods are library calls over
its rows, and the result is an artifact like any other. That was established
with file:line evidence before this module was written.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from backend.cockpit_v4.scenario import delta as dl
from backend.cockpit_v4.scenario import ledger as lg
from backend.cockpit_v4.scenario import spec as sp
from backend.cockpit_v4.scenario import userdefined as ud
from backend.cockpit_v4.scenario.errors import (
    METHOD_COVERAGE_GAP,
    MODEL_NOT_READY,
    ScenarioError,
    raise_for,
)

#: A method ran and produced a number over a stated population.
AVAILABLE = "AVAILABLE"

#: A method could not run. It carries a reason and NO number: a zero here
#: would read as "this method found no effect".
UNAVAILABLE = "UNAVAILABLE"

#: A method ran over fewer rows than the cohort. The number is real for the
#: rows it covers and the gap is published beside it.
PARTIAL = "PARTIAL"

STATUSES = (AVAILABLE, PARTIAL, UNAVAILABLE)

#: The READER-FACING verdict for each analytical status.
#:
#: The analytical vocabulary above is the engine's and it does not move:
#: `AVAILABLE`, `PARTIAL` and `UNAVAILABLE` are what the code branches on and
#: what every test asserts. But a reader comparing three methods is not
#: reading a state machine, and "UNAVAILABLE" reads as "the product is broken"
#: rather than "this method has not passed its validation gates". The mapping
#: is here so that the copy is a translation of the state rather than a second
#: source of truth about it -- the same discipline the run-status copy follows.
#:
#: NOT READY is the word for a method whose model exists, ran in development,
#: and missed a predeclared acceptance gate. That is the Retail emulator's
#: situation exactly: G4 material-group WAPE measured 34.36% against a 15%
#: threshold declared before the model was fitted. The gate is not moved, the
#: group is not redefined, no blend weight is invented, Corporate's model does
#: not stand in, and there is no silent fall back to Delta. The method keeps
#: its row, its cells stay EMPTY rather than zero, and the reason travels with
#: it.
VERDICTS: dict[str, str] = {
    AVAILABLE: "COMPLETE",
    PARTIAL: "PARTIAL",
    UNAVAILABLE: "NOT READY",
}

#: The three methods, in the order a result displays them. Delta first
#: because it is the one that always runs.
ORDER: tuple[str, ...] = (sp.DELTA, sp.ML, sp.USER_DEFINED)

LABELS: dict[str, str] = {
    sp.DELTA: "Delta (proportional)",
    sp.ML: "Emulator",
    sp.USER_DEFINED: "Your assumption",
}


@dataclass(frozen=True)
class Outcome:
    """One method's answer, or one method's reason for not having one."""

    method: str
    status: str
    baseline: Decimal
    scenario: Decimal | None
    covered: tuple[str, ...]
    reason: str = ""
    facts: dict[str, Any] = field(default_factory=dict)
    #: Things true of this number that a reader has to be told. A method
    #: that ran and whose model missed a predeclared acceptance gate is the
    #: case this exists for: the figure is real and it is not as reliable as
    #: the other methods', and saying nothing would leave three numbers
    #: looking equally solid.
    limitations: tuple[str, ...] = ()

    @property
    def change(self) -> Decimal | None:
        if self.scenario is None:
            return None
        return self.scenario - self.baseline

    @property
    def ran(self) -> bool:
        return self.status in (AVAILABLE, PARTIAL)

    def describe(self) -> str:
        if not self.ran:
            return (f"{LABELS[self.method]}: "
                    f"{VERDICTS.get(self.status, self.status)}. "
                    f"{self.reason}")
        change = self.change or Decimal(0)
        share = (change / self.baseline * 100) if self.baseline else None
        movement = (f"{share:+.2f}%" if share is not None
                    else "not defined from a zero baseline")
        line = (f"{LABELS[self.method]}: {self.baseline:,.4f} to "
                f"{self.scenario:,.4f}, a change of {change:+,.4f} "
                f"({movement}) over {len(self.covered):,} rows.")
        for limitation in self.limitations:
            line += f" {limitation}"
        return line


@dataclass(frozen=True)
class Coverage:
    """Which rows each method reached, and which they all reached."""

    cohort: tuple[str, ...]
    by_method: dict[str, tuple[str, ...]]

    @property
    def shared(self) -> tuple[str, ...]:
        ran = [set(keys) for keys in self.by_method.values() if keys]
        if not ran:
            return ()
        return tuple(sorted(set.intersection(*ran)))

    @property
    def uniform(self) -> bool:
        """Did every method that ran cover exactly the same rows?"""
        sets = [frozenset(keys) for keys in self.by_method.values() if keys]
        return len(set(sets)) <= 1

    def gaps(self) -> dict[str, tuple[str, ...]]:
        """Per method, the cohort rows it did NOT cover."""
        whole = set(self.cohort)
        return {method: tuple(sorted(whole - set(keys)))
                for method, keys in self.by_method.items()
                if keys and set(keys) != whole}

    def describe(self) -> str:
        if self.uniform:
            return (f"Every method covered the same {len(self.shared):,} "
                    f"rows of the {len(self.cohort):,}-row cohort.")
        pieces = ", ".join(
            f"{LABELS.get(m, m)} {len(keys):,}"
            for m, keys in sorted(self.by_method.items()) if keys)
        return (f"The methods covered different populations ({pieces}) out "
                f"of a {len(self.cohort):,}-row cohort. The like-for-like "
                f"comparison below is over the {len(self.shared):,} rows all "
                f"of them reached; comparing the totals above would report a "
                f"difference that is mostly population.")


@dataclass(frozen=True)
class Run:
    """One confirmed scenario, executed. Everything a result needs."""

    spec: sp.ScenarioSpec
    period: str
    membership_hash: str
    cohort_size: int
    book_baseline: Decimal
    outcomes: dict[str, Outcome]
    coverage: Coverage
    ledgers: dict[str, lg.Ledger] = field(default_factory=dict)
    notes: tuple[str, ...] = ()

    @property
    def ran(self) -> tuple[str, ...]:
        return tuple(m for m in ORDER
                     if m in self.outcomes and self.outcomes[m].ran)

    @property
    def unavailable(self) -> tuple[str, ...]:
        return tuple(m for m in ORDER
                     if m in self.outcomes and not self.outcomes[m].ran)

    def compare(self) -> dict[str, Any]:
        """The methods beside each other, never combined into a third.

        Where they covered different populations this publishes BOTH
        comparisons and says which is which. The like-for-like one is the
        one to read; the other is each method's own honest total over its
        own rows, and dropping it would hide that they differ.
        """
        rows = [{
            "method": method,
            "label": LABELS[method],
            "status": self.outcomes[method].status,
            "verdict": VERDICTS.get(self.outcomes[method].status,
                                    self.outcomes[method].status),
            "baseline": str(self.outcomes[method].baseline),
            "scenario": (str(self.outcomes[method].scenario)
                         if self.outcomes[method].scenario is not None
                         else None),
            "change": (str(self.outcomes[method].change)
                       if self.outcomes[method].change is not None else None),
            "rows_covered": len(self.outcomes[method].covered),
            "reason": self.outcomes[method].reason,
            "limitations": list(self.outcomes[method].limitations),
        } for method in ORDER if method in self.outcomes]

        out: dict[str, Any] = {
            "contract": self.contract(),
            "status_line": self.status_line(),
            "own_population": rows,
            "coverage": self.coverage.describe(),
            "like_for_like_needed": not self.coverage.uniform,
            "baselines_identical": len({r["baseline"] for r in rows}) <= 1,
            "never_composed": (
                "These are alternative answers to one question. The "
                "emulator's estimate is not multiplied by the Delta factor "
                "and no macro move is applied twice; where they disagree the "
                "disagreement is explained, not averaged."),
        }
        if not self.coverage.uniform and self.coverage.shared:
            out["like_for_like"] = [{
                "method": method,
                "label": LABELS[method],
                "rows_covered": len(self.coverage.shared),
                "note": ("Restricted to the rows every method reached, so "
                         "the difference between these figures is method "
                         "rather than population."),
            } for method in self.ran]
        return out

    def contract(self) -> dict[str, Any]:
        """THE ONE CONTRACT EVERY METHOD RAN AGAINST.

        Section 6 asks that the methods be comparable, and comparable means
        one book, one period, one release and fingerprint, one frozen cohort,
        one scenario revision, one approval and one baseline. Those facts were
        each enforced somewhere -- `require_same_book`, the cohort
        re-resolution, `require_confirmed`, the equal-baseline check that
        raises METHOD_COVERAGE_GAP -- and published nowhere as a single
        statement, so a reader comparing two figures had to take the
        comparability on trust. This states it once, and `baselines_identical`
        beside it is the check rather than the claim.
        """
        return {
            "book": self.spec.source.domain_id,
            "reporting_period": self.period,
            "release_id": self.spec.source.release_id,
            "release_fingerprint": self.spec.source.release_fingerprint,
            "cohort_id": self.spec.cohort.cohort_id,
            "membership_hash": self.membership_hash,
            "cohort_size": self.cohort_size,
            "scenario_id": self.spec.scenario_id,
            "scenario_version": self.spec.version,
            "confirmed_digest": self.spec.confirmed_digest,
            "book_baseline": str(self.book_baseline),
        }

    def status_line(self) -> str:
        """Every selected method, its verdict, and the reason for a refusal.

        One line, in the order the methods are declared in, so a reader sees
        that a method is missing and why rather than seeing a shorter list.
        A method that did not run contributes its reason here and no number
        anywhere: not a zero, and not another model's estimate.
        """
        parts: list[str] = []
        for method in ORDER:
            if method not in self.outcomes:
                continue
            got = self.outcomes[method]
            label = LABELS[method]
            verdict = VERDICTS.get(got.status, got.status)
            if got.ran and got.scenario is not None:
                parts.append(f"{label} {verdict}")
            else:
                reason = (got.reason or "no reason was recorded").rstrip(".")
                parts.append(f"{label} {verdict} \u2014 {reason}")
        return "; ".join(parts)

    def disagreement(self) -> str:
        """Why the methods differ, in words, without averaging them."""
        ran = [self.outcomes[m] for m in self.ran
               if self.outcomes[m].change is not None]
        if len(ran) < 2:
            return ""
        changes = [o.change or Decimal(0) for o in ran]
        widest = max(changes) - min(changes)
        biggest = max(abs(c) for c in changes)
        share = (widest / biggest * 100) if biggest else Decimal(0)
        return (
            f"The methods differ by {widest:+,.4f} at the widest, which is "
            f"{share:.1f}% of the largest change. Delta scales the published "
            f"ECL by the factors the rules resolve to; the emulator predicts "
            f"a rate from the whole feature vector and is anchored on the "
            f"observed baseline; an assumption is the reader's own figure. "
            f"They answer the same question with different information and "
            f"are shown side by side for that reason.")


def _baseline_of(rows: Iterable[Mapping[str, Any]], *, key: str,
                 ecl_column: str, ead_column: str = "ead_sar_mn"
                 ) -> tuple[dict[str, Decimal], Decimal]:
    """The cohort's baseline, read ONCE: ECL per row, and total EAD.

    EAD comes back too because a TARGET_RATE assumption is a coverage
    percentage and needs a denominator. Reading it here rather than inside
    Method 3 keeps the promise that the cohort is read once and every method
    starts from the same figures.
    """
    per_row: dict[str, Decimal] = {}
    ead = Decimal(0)
    for row in rows:
        per_row[str(row[key])] = Decimal(str(row[ecl_column] or 0))
        ead += Decimal(str(row.get(ead_column) or 0))
    return per_row, ead


def run_delta(spec: sp.ScenarioSpec, rows: Sequence[Mapping[str, Any]], *,
              key: str, plan: dl.Plan) -> tuple[Outcome, dict[str, Any]]:
    """Method 1 over the frozen cohort, row by row.

    Every row of the cohort is scaled, including the ones the rules do not
    touch -- their disposition is `unaffected` and their contribution is
    exactly zero, which is what makes the full book reconcile. A method that
    silently dropped them would produce a smaller scenario total and a
    correct-looking change.
    """
    results: dict[str, dl.RowResult] = {}
    for row in rows:
        results[str(row[key])] = dl.scale_row(plan, dict(row))
    baseline = sum((r.baseline_ecl for r in results.values()), Decimal(0))
    covered = tuple(sorted(
        k for k, r in results.items()
        if r.disposition in (dl.SCALED, dl.UNAFFECTED)))
    unsupported = [k for k, r in results.items()
                   if r.disposition == dl.UNSUPPORTED]
    scenario = sum((r.scenario_ecl for r in results.values()), Decimal(0))

    status = AVAILABLE if not unsupported else PARTIAL
    reason = ""
    if unsupported:
        reason = (
            f"{len(unsupported):,} of {len(results):,} rows could not be "
            f"scaled proportionally and carry their baseline unchanged. "
            f"They are in the total, counted, and named in the ledger.")
    if plan.unhandled:
        status = PARTIAL
        reason = (reason + " " if reason else "") + (
            f"This scenario also moves {', '.join(plan.unhandled)}, which "
            f"Delta does not express. That part of the request is not in "
            f"this number.")
    return Outcome(method=sp.DELTA, status=status, baseline=baseline,
                   scenario=scenario, covered=covered, reason=reason,
                   facts={"submode": plan.submode,
                          "factors": plan.describe(),
                          "unhandled": list(plan.unhandled),
                          "unsupported_rows": len(unsupported)}), results


def run_user_defined(spec: sp.ScenarioSpec,
                     baselines: Mapping[str, Decimal], *,
                     baseline_ead: Decimal = Decimal(0)) -> Outcome:
    """Method 3: the reader's own figure, allocated over the cohort.

    A scenario with no assumption does not get a default one. It gets
    `UNAVAILABLE` with the sentence that says what to state, because
    inventing the reader's assumption is the one thing Method 3 must never
    do.
    """
    if not spec.user_assumption:
        return Outcome(
            method=sp.USER_DEFINED, status=UNAVAILABLE,
            baseline=sum(baselines.values(), Decimal(0)), scenario=None,
            covered=(), reason=(
                "No assumption was stated for this scenario. Method 3 "
                "applies a figure the reader gives; it does not supply one. "
                "State the ECL change you want to assume -- a relative move, "
                "an absolute amount, a target total, a target rate or an "
                "elasticity -- and it will be applied and labelled as your "
                "assumption."))
    try:
        assumption = ud.from_payload(dict(spec.user_assumption))
        baseline = sum(baselines.values(), Decimal(0))
        target = ud.target_total(assumption, baseline_ecl=baseline,
                                 baseline_ead=baseline_ead)
        ordered = list(baselines.items())
        allocated = ud.allocate(target, [v for _k, v in ordered],
                               )
    except ScenarioError as exc:
        return Outcome(
            method=sp.USER_DEFINED, status=UNAVAILABLE,
            baseline=sum(baselines.values(), Decimal(0)), scenario=None,
            covered=(), reason=str(exc))

    if not ud.reconciles(allocated, target):  # pragma: no cover - guarded
        raise_for(METHOD_COVERAGE_GAP,
                  "the allocated rows do not sum to the stated target, so "
                  "the per-row figures and the headline would disagree.",
                  field_path="user_assumption")
    return Outcome(
        method=sp.USER_DEFINED, status=AVAILABLE,
        baseline=sum(baselines.values(), Decimal(0)), scenario=target,
        covered=tuple(sorted(baselines)),
        reason="",
        facts={"assumption": assumption.describe(),
               "stated_by_the_reader": assumption.stated_as,
               "allocation": "pro rata on baseline ECL",
               "label": "USER_ASSUMPTION"})


def run_ml(spec: sp.ScenarioSpec, *, anchored: Any = None,
           baseline: Decimal, covered: Sequence[str] = (),
           unavailable_reason: str = "", loaded: Any = None) -> Outcome:
    """Method 2, from an already-anchored estimate or from a refusal.

    The anchoring itself is `ml/infer.py`'s -- this only turns its result
    into an outcome, so that the one place §11.4's arithmetic lives is the
    one place it can be got wrong.

    A model that RAN but missed a predeclared acceptance gate produces a
    number AND a limitation naming the gate. Section 11.5: a failed gate is
    reported failed, and a reader shown three figures with nothing to
    distinguish them would reasonably take all three as equally reliable.
    """
    if anchored is None:
        return Outcome(
            method=sp.ML, status=UNAVAILABLE, baseline=baseline,
            scenario=None, covered=(),
            reason=unavailable_reason or (
                "No emulator is available for this book. Method 2 is "
                "unavailable; it is not a change of zero, and the other "
                "methods' figures are not substituted for it."))

    limitations: list[str] = []
    if loaded is not None and not loaded.passed_every_gate:
        failures = "; ".join(loaded.failures())
        limitations.append(
            f"This emulator MISSED a predeclared acceptance gate "
            f"({failures}). The figure is what the model predicts; the gate "
            f"it failed is published in its model card and was not relaxed "
            f"to accommodate it.")
    return Outcome(
        method=sp.ML, status=AVAILABLE, baseline=baseline,
        scenario=Decimal(str(anchored.anchored_total)),
        covered=tuple(sorted(covered)), reason="",
        facts=anchored.as_facts(), limitations=tuple(limitations))


def execute(spec: sp.ScenarioSpec, rows: Sequence[Mapping[str, Any]], *,
            key: str, ecl_column: str, plan: dl.Plan,
            anchored: Any = None, ml_unavailable: str = "",
            loaded: Any = None, book_baseline: Decimal = Decimal(0),
            labels: Mapping[str, str] | None = None) -> Run:
    """Run every method the scenario asked for, over one frozen cohort.

    Refuses an unconfirmed scenario first, before reading anything: section
    6.2's confirmation is a precondition of execution, not a label applied
    afterwards.
    """
    spec.require_confirmed()
    if not rows:
        raise_for(METHOD_COVERAGE_GAP,
                  "this cohort resolved to no rows, so there is nothing to "
                  "compute. A scenario over an empty population is not a "
                  "result of zero.",
                  field_path="cohort")

    baselines, baseline_ead = _baseline_of(rows, key=key,
                                           ecl_column=ecl_column)
    baseline_total = sum(baselines.values(), Decimal(0))
    cohort_keys = tuple(sorted(baselines))
    outcomes: dict[str, Outcome] = {}
    ledgers: dict[str, lg.Ledger] = {}
    notes: list[str] = []

    if sp.DELTA in spec.methods:
        outcome, results = run_delta(spec, rows, key=key, plan=plan)
        outcomes[sp.DELTA] = outcome
        ledgers[sp.DELTA] = lg.build(
            domain_id=spec.source.domain_id, period=spec.source.reporting_period,
            membership_hash=spec.cohort.membership_hash, results=results,
            labels=dict(labels or {}), book_baseline=book_baseline)

    if sp.ML in spec.methods:
        outcomes[sp.ML] = run_ml(
            spec, anchored=anchored, baseline=baseline_total,
            covered=cohort_keys if anchored is not None else (),
            unavailable_reason=ml_unavailable, loaded=loaded)

    if sp.USER_DEFINED in spec.methods:
        outcomes[sp.USER_DEFINED] = run_user_defined(
            spec, baselines, baseline_ead=baseline_ead)

    for method, outcome in outcomes.items():
        if outcome.baseline != baseline_total and outcome.ran:
            raise_for(METHOD_COVERAGE_GAP,
                      f"{LABELS[method]} measured a baseline of "
                      f"{outcome.baseline} and the cohort's is "
                      f"{baseline_total}. Every method starts from the same "
                      f"figure or the changes are not comparable.",
                      field_path=f"methods.{method}")

    coverage = Coverage(cohort=cohort_keys,
                        by_method={m: o.covered for m, o in outcomes.items()})
    if not coverage.uniform:
        notes.append(coverage.describe())
    if not outcomes:
        raise_for(METHOD_COVERAGE_GAP,
                  "this scenario names no method to run it with.",
                  field_path="methods")

    return Run(spec=spec, period=spec.source.reporting_period,
               membership_hash=spec.cohort.membership_hash,
               cohort_size=len(cohort_keys), book_baseline=book_baseline,
               outcomes=outcomes, coverage=coverage, ledgers=ledgers,
               notes=tuple(notes))


def unresolved_assumptions(spec: sp.ScenarioSpec) -> list[str]:
    """What Method 3 still needs, BEFORE anything is executed.

    Section 12.1: a missing assumption is resolved before the run, not
    discovered halfway through it. A run that got this far and then refused
    would have spent a budget to ask a question it could have asked first.
    """
    if sp.USER_DEFINED not in spec.methods:
        return []
    if not spec.user_assumption:
        return ["the ECL change to assume: a relative move, an absolute "
                "amount, a target total or an elasticity"]
    try:
        ud.from_payload(dict(spec.user_assumption))
    except ScenarioError as exc:
        return [str(exc)]
    return []


def require_same_book(spec: sp.ScenarioSpec, *, release_id: str,
                      release_fingerprint: str = "") -> None:
    """The scenario and the book in front of the reader are the same book."""
    if spec.source.release_id != release_id:
        raise_for(MODEL_NOT_READY,
                  f"this scenario was confirmed against "
                  f"{spec.source.release_id!r} and the book in use is "
                  f"{release_id!r}. Its cohort is a set of identifiers in "
                  f"the other release and its baseline is the other "
                  f"release's numbers.",
                  field_path="source.release_id")
    if (release_fingerprint and spec.source.release_fingerprint
            and spec.source.release_fingerprint != release_fingerprint):
        raise_for(MODEL_NOT_READY,
                  f"the release id matches and the bytes do not: confirmed "
                  f"against {spec.source.release_fingerprint[:12]}, in use "
                  f"{release_fingerprint[:12]}. The book was republished "
                  f"under the same id.",
                  field_path="source.release_fingerprint")


__all__ = ["AVAILABLE", "Coverage", "LABELS", "ORDER", "Outcome", "PARTIAL",
           "VERDICTS",
           "Run", "STATUSES", "UNAVAILABLE", "execute", "require_same_book",
           "run_delta", "run_ml", "run_user_defined",
           "unresolved_assumptions"]
