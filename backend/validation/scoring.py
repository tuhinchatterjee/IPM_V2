"""
Scoring an answer against an independently computed reference.

What is graded, and what is not
------------------------------
**Not prose.** Two correct interpretations of the same result can share almost no
vocabulary, and a similarity score between them measures writing style. What is
graded is the *decisions* — which capability, which concepts, which datasets,
which relationships, which period and grain — and the *figures*, against a
reference computed by a separate implementation.

**Only what the case actually tested.** A dictionary question declares no
relationship expectation, so relationship selection is not scored for it and its
weight is removed from the denominator. Awarding full marks for a dimension a
case never exercised would make every metadata case score in the nineties by
construction, and the number would stop meaning anything.

Why every deduction carries a sentence
--------------------------------------
"91%" tells a user nothing they can act on. "Correct customers, but ranked by
facility EAD rather than IFRS 9 EAD" tells them where to look. Each check that
takes marks off writes one line in the words a credit officer uses, and those
lines are what the validation panel shows under WHY THE SCORE WAS NOT 100%.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: The eight dimensions and what each is worth, per §AH of the release brief.
WEIGHTS: dict[str, int] = {
    "intent": 15,
    "plan": 15,
    "dataset": 15,
    "relationship": 10,
    "period": 10,
    "result": 20,
    "context": 10,
    "grounding": 5,
}

LABELS: dict[str, str] = {
    "intent": "Intent match",
    "plan": "Concept and plan match",
    "dataset": "Dataset match",
    "relationship": "Relationship match",
    "period": "Period and grain match",
    "result": "Result-value match",
    "context": "Conversation context",
    "grounding": "Grounding",
}

PASS = "PASS"
PARTIAL = "PARTIAL"
FAIL = "FAIL"

#: A figure within this much of the reference counts as agreement. Tight enough
#: that a different population or a different measure fails; loose enough that
#: floating-point summation order does not.
TOLERANCE_PCT = 0.5

#: How many of the reference's identities must appear, in order, for a ranking
#: to count as matched.
ORDER_CREDIT = 0.5

#: How many identities a conversation carries forward. Mirrors
#: `conversation.MAX_ENTITY_IDS`; a result at exactly this size is a truncated
#: view rather than a disagreement about the population.
CARRY_LIMIT = 200


@dataclass
class Dimension:
    """One graded dimension of one turn."""

    name: str
    earned: float
    possible: float
    note: str = ""

    @property
    def pct(self) -> float:
        return 100.0 * self.earned / self.possible if self.possible else 0.0


@dataclass
class TurnScore:
    """What one turn earned, and why it did not earn more."""

    dimensions: list[Dimension] = field(default_factory=list)
    deductions: list[str] = field(default_factory=list)
    live: bool = True

    @property
    def earned(self) -> float:
        return sum(d.earned for d in self.dimensions)

    @property
    def possible(self) -> float:
        return sum(d.possible for d in self.dimensions)

    @property
    def pct(self) -> float:
        return 100.0 * self.earned / self.possible if self.possible else 0.0

    def add(self, name: str, earned: float, possible: float,
            note: str = "") -> None:
        self.dimensions.append(Dimension(name, earned, possible, note))
        if note and earned < possible:
            self.deductions.append(note)

    def components(self) -> dict[str, float]:
        return {d.name: round(d.pct, 1) for d in self.dimensions}


def verdict(score: float) -> str:
    if score >= 90:
        return PASS
    if score >= 70:
        return PARTIAL
    return FAIL


def band(score: float) -> tuple[str, str]:
    """The AI POWERED label and its tone, per §AI."""
    if score >= 90:
        return "HIGH", "green"
    if score >= 75:
        return "GOOD", "teal"
    if score >= 60:
        return "LIMITED", "amber"
    return "DEGRADED", "red"


# ------------------------------------------------------------- the checks


def score_turn(expect: dict[str, Any], observed: dict[str, Any],
               reference: Any) -> TurnScore:
    """Grade one turn.

    `observed` is what CreditProbe produced, flattened by the runner. `reference`
    is a `gold.Reference` computed after the fact, or None where the case
    declared no reference specification.
    """
    score = TurnScore(live=bool(observed.get("live")))

    _intent(expect, observed, score)
    _plan(expect, observed, score)
    _datasets(expect, observed, score)
    _relationships(expect, observed, score)
    _period(expect, observed, score)
    _result(expect, observed, reference, score)
    _context(expect, observed, score)
    _grounding(observed, score)
    return score


def _intent(expect: dict[str, Any], observed: dict[str, Any],
            score: TurnScore) -> None:
    weight = WEIGHTS["intent"]
    wanted_clarification = bool(expect.get("clarification"))
    asked = observed.get("status") == "needs_clarification"

    if wanted_clarification:
        if asked:
            score.add("intent", weight, weight)
        else:
            score.add("intent", 0, weight,
                      "The request could not be answered from governed data and "
                      "should have come back as a question. CreditProbe answered "
                      f"it instead ({observed.get('status')}).")
        return

    if asked and expect.get("intent"):
        score.add("intent", 0, weight,
                  "CreditProbe asked a clarifying question where the request "
                  "was answerable as it stood.")
        return

    wanted = expect.get("intent")
    if not wanted:
        return
    got = observed.get("intent")
    if got == wanted:
        score.add("intent", weight, weight)
    elif expect.get("certified") and observed.get("certified"):
        score.add("intent", weight, weight)
    else:
        score.add("intent", 0, weight,
                  f"Read as {got or 'nothing'} rather than {wanted}, which "
                  "sends the request to the wrong subsystem.")


def _plan(expect: dict[str, Any], observed: dict[str, Any],
          score: TurnScore) -> None:
    weight = WEIGHTS["plan"]
    checks: list[tuple[bool, str]] = []

    if expect.get("certified"):
        checks.append((
            observed.get("certified") == expect["certified"],
            f"The bank's certified {expect['certified']} should have run; "
            f"CreditProbe used {observed.get('certified') or 'a composed analysis'}."))

    if expect.get("shape"):
        checks.append((
            observed.get("shape") == expect["shape"],
            f"Planned as a {observed.get('shape') or 'different'} analysis "
            f"rather than a {expect['shape']}."))

    if expect.get("dimension"):
        checks.append((
            observed.get("dimension") == expect["dimension"],
            f"Broken down by {observed.get('dimension') or 'nothing'} rather "
            f"than by {expect['dimension']}."))

    if expect.get("top_n"):
        checks.append((
            int(observed.get("top_n") or 0) == int(expect["top_n"]),
            f"Returned a cut of {observed.get('top_n') or 'everything'} where "
            f"{expect['top_n']} was asked for."))

    if expect.get("filters"):
        applied = {str(k): str(v) for k, v in (observed.get("filters") or {}).items()}
        for key, value in expect["filters"].items():
            checks.append((
                applied.get(str(key)) == str(value),
                f"The {key} = {value} restriction was not applied, so the "
                "answer covers a wider population than the question."))

    if expect.get("forbidden_methods"):
        used = str(observed.get("certified") or observed.get("analysis_id") or "")
        for banned in expect["forbidden_methods"]:
            checks.append((
                used != banned,
                f"Answered with the {banned} methodology, which is a different "
                "question from the one that was asked."))

    if expect.get("computes") is not None:
        checks.append((
            bool(observed.get("computed")) == bool(expect["computes"]),
            "A figure was computed for a request that needed none."
            if observed.get("computed")
            else "No figure was computed for a request that needed one."))

    if not checks:
        return
    passed = sum(1 for ok, _ in checks if ok)
    notes = [note for ok, note in checks if not ok]
    score.add("plan", weight * passed / len(checks), weight,
              notes[0] if notes else "")
    for extra in notes[1:]:
        score.deductions.append(extra)


def _datasets(expect: dict[str, Any], observed: dict[str, Any],
              score: TurnScore) -> None:
    wanted = [str(d) for d in expect.get("datasets") or []]
    if not wanted:
        return
    weight = WEIGHTS["dataset"]
    used = {str(d) for d in observed.get("datasets") or []}
    hit = [d for d in wanted if d in used]
    missing = [d for d in wanted if d not in used]
    note = ("" if not missing else
            f"Did not read {', '.join(missing)}, which is where the figures "
            "this question needs are governed.")
    score.add("dataset", weight * len(hit) / len(wanted), weight, note)


def _relationships(expect: dict[str, Any], observed: dict[str, Any],
                   score: TurnScore) -> None:
    wanted = expect.get("relationships")
    needs_join = len(expect.get("datasets") or []) > 1
    if wanted is None and not needs_join:
        return
    weight = WEIGHTS["relationship"]
    used = observed.get("join_path") or []
    if wanted:
        names = {str(j.get("relationship_name")) for j in used}
        hit = [r for r in wanted if r in names]
        score.add("relationship", weight * len(hit) / len(wanted), weight,
                  "" if len(hit) == len(wanted) else
                  "The governed relationship this question needs was not used.")
        return
    # Two datasets were expected, so something must have joined them — unless
    # the answer was metadata, which explains a join without performing one.
    if observed.get("computed"):
        score.add("relationship", weight if used else 0, weight,
                  "" if used else
                  "Two governed datasets were needed and no declared "
                  "relationship was used to bring them together.")
    else:
        score.add("relationship", weight, weight)


def _period(expect: dict[str, Any], observed: dict[str, Any],
            score: TurnScore) -> None:
    wanted = expect.get("period")
    grain = expect.get("grain")
    if wanted is None and not grain:
        return
    weight = WEIGHTS["period"]
    checks: list[tuple[bool, str]] = []

    if isinstance(wanted, dict):
        checks.append((
            observed.get("opening") == wanted.get("from")
            and observed.get("closing") == wanted.get("to"),
            f"Compared {observed.get('opening') or '?'} with "
            f"{observed.get('closing') or '?'} rather than "
            f"{wanted.get('from')} with {wanted.get('to')}."))
    elif wanted:
        checks.append((
            observed.get("period") == wanted or observed.get("closing") == wanted,
            f"Answered as at {observed.get('period') or observed.get('closing') or '?'} "
            f"rather than {wanted}."))

    if grain:
        checks.append((
            observed.get("grain") == grain,
            f"Answered one row per {observed.get('grain') or '?'} rather than "
            f"per {grain}."))

    passed = sum(1 for ok, _ in checks if ok)
    notes = [note for ok, note in checks if not ok]
    score.add("period", weight * passed / len(checks), weight,
              notes[0] if notes else "")
    for extra in notes[1:]:
        score.deductions.append(extra)


def _result(expect: dict[str, Any], observed: dict[str, Any], reference: Any,
            score: TurnScore) -> None:
    if reference is None:
        return
    weight = WEIGHTS["result"]
    if not reference.ok:
        # The reference itself could not be computed. Not the model's fault, and
        # scoring it either way would be noise.
        return
    if expect.get("clarification"):
        return

    checks: list[tuple[bool, str]] = []

    values = observed.get("values") or {}
    for name, expected in (reference.values or {}).items():
        if not isinstance(expected, (int, float)):
            continue
        actual = _find_value(values, name)
        if actual is None:
            continue
        checks.append((
            _close(actual, expected),
            f"{LABELS['result']}: {name} came back as {_fmt(actual)} where the "
            f"reference computes {_fmt(expected)} — a difference of "
            f"{_gap(actual, expected)}."))

    # Identity comparison only where the reference's ids ARE identities. A
    # dataset reference lists field names; comparing those against the rows an
    # answer returned would be comparing two different things and calling the
    # difference an error.
    if reference.ids and reference.kind in ("ranking", "cohort", "aggregate",
                                            "count"):
        got = [str(i) for i in (observed.get("ids") or [])]
        wanted = [str(i) for i in reference.ids]
        # A large cohort is carried forward truncated — the conversation keeps a
        # bounded number of identities — so recall cannot be checked against it.
        # Precision can: everything the answer names must be in the reference,
        # and the row count must agree. A wrong population fails both.
        truncated = len(wanted) > len(got) and len(got) >= CARRY_LIMIT
        if truncated:
            wrong = [i for i in got if i not in set(wanted)]
            checks.append((
                not wrong,
                f"{len(wrong)} of the {len(got)} rows carried forward are not "
                "in the reference population."))
        else:
            overlap = len(set(got) & set(wanted)) / len(wanted)
            checks.append((
                overlap >= 0.999,
                f"Returned {len(set(got) & set(wanted))} of the {len(wanted)} "
                "rows the reference identifies"
                + (f", and {len(set(got) - set(wanted))} the reference does not."
                   if set(got) - set(wanted) else ".")))
        if reference.ordered and got and wanted and not truncated:
            checks.append((
                got[:len(wanted)] == wanted[:len(got)],
                "The rows are right but the order is not, so the largest is "
                "not the one reported as largest."))

    if not checks:
        return
    passed = sum(1 for ok, _ in checks if ok)
    notes = [note for ok, note in checks if not ok]
    score.add("result", weight * passed / len(checks), weight,
              notes[0] if notes else "")
    for extra in notes[1:]:
        score.deductions.append(extra)


def _context(expect: dict[str, Any], observed: dict[str, Any],
             score: TurnScore) -> None:
    wants_action = expect.get("action")
    wants_population = expect.get("population_from_previous")
    if not wants_action and not wants_population:
        return
    weight = WEIGHTS["context"]
    checks: list[tuple[bool, str]] = []

    if wants_action:
        checks.append((
            observed.get("action") == wants_action,
            f"Read as {observed.get('action') or 'a new request'} rather than "
            f"{wants_action}, so the conversation's context was "
            + ("lost." if wants_action != "NEW_REQUEST" else "carried when it "
               "should not have been.")))

    if wants_population:
        checks.append((
            int(observed.get("population_count") or 0) > 0,
            "The rows the previous turn returned were not carried into this "
            "one, so the follow-up was answered against the whole book."))

    passed = sum(1 for ok, _ in checks if ok)
    notes = [note for ok, note in checks if not ok]
    score.add("context", weight * passed / len(checks), weight,
              notes[0] if notes else "")
    for extra in notes[1:]:
        score.deductions.append(extra)


def _grounding(observed: dict[str, Any], score: TurnScore) -> None:
    weight = WEIGHTS["grounding"]
    loose = observed.get("ungrounded") or []
    if loose:
        score.add("grounding", 0, weight,
                  "The written interpretation contained "
                  f"{len(loose)} figure(s) the computed result does not carry.")
        return
    caveats = " ".join(observed.get("caveats") or []).lower()
    if "could not be traced" in caveats:
        score.add("grounding", weight / 2, weight,
                  "A figure in the reading was flagged as untraceable to the "
                  "result.")
        return
    score.add("grounding", weight, weight)


# ------------------------------------------------------------------ helpers


def _find_value(values: dict[str, Any], name: str) -> float | None:
    """The observed figure matching a reference figure's name.

    Names are matched loosely because the runtime and the reference name things
    for different audiences — `total` against `total_ead`, `row_count` against
    `rows`. A miss returns None and the check is skipped rather than failed:
    penalising a naming difference would be measuring the harness.
    """
    aliases = {
        "total": ("total", "total_ead", "total_ecl", "grand_total"),
        "row_count": ("row_count", "rows", "count", "customers", "facilities"),
        "groups": ("groups", "group_count", "sectors", "dimension_count"),
        "top_value": ("top_value", "largest", "max"),
        "covered_pct": ("covered_pct", "share_covered_pct"),
        # Deliberately NOT aliased to `total`: after a cut they are different
        # figures, and treating them as interchangeable failed a correct answer
        # for reporting the total of what it showed.
        "population_total": ("population_total",),
        "members": ("members", "population", "member_count"),
        "field_count": ("field_count", "fields"),
        "period_count": ("period_count", "periods"),
        "hops": ("hops", "steps"),
    }
    for key in aliases.get(name, (name,)):
        if key in values and isinstance(values[key], (int, float)):
            return float(values[key])
    return None


def _close(actual: float, expected: float) -> bool:
    if expected == 0:
        return abs(actual) < 1e-6
    return abs(actual - expected) / abs(expected) * 100 <= TOLERANCE_PCT


def _gap(actual: float, expected: float) -> str:
    if expected == 0:
        return f"{actual:,.2f}"
    return f"{abs(actual - expected) / abs(expected) * 100:.1f}%"


def _fmt(value: float) -> str:
    return f"{value:,.2f}".rstrip("0").rstrip(".") if value % 1 else f"{value:,.0f}"


def combine(turns: list[TurnScore]) -> tuple[float, dict[str, float], list[str]]:
    """One case's score, its component percentages and its deductions.

    Weighted by what each turn actually exercised, so a four-turn thread whose
    last turn lost the population is not rescued by three easy turns before it.
    """
    earned = sum(t.earned for t in turns)
    possible = sum(t.possible for t in turns)
    total = 100.0 * earned / possible if possible else 0.0

    components: dict[str, list[tuple[float, float]]] = {}
    for turn in turns:
        for dimension in turn.dimensions:
            components.setdefault(dimension.name, []).append(
                (dimension.earned, dimension.possible))

    summary = {
        name: round(100.0 * sum(e for e, _ in pairs)
                    / sum(p for _, p in pairs), 1)
        for name, pairs in components.items() if sum(p for _, p in pairs)
    }
    deductions: list[str] = []
    for index, turn in enumerate(turns, start=1):
        prefix = f"Turn {index}: " if len(turns) > 1 else ""
        deductions.extend(prefix + d for d in turn.deductions)
    return round(total, 1), summary, deductions


__all__ = ["FAIL", "LABELS", "ORDER_CREDIT", "PARTIAL", "PASS",
           "TOLERANCE_PCT", "WEIGHTS", "Dimension", "TurnScore", "band",
           "combine", "score_turn", "verdict"]
