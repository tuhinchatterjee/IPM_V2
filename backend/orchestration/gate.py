"""
Whether every condition the question set was actually enforced.

The rule
--------
Before an answer is shown, the conditions the question REQUESTED are compared
with the conditions the compiled plan EXECUTED. They must match. A question
that asked for two things and got a population selected on one of them is not
a partially-answered question; it is a wrong answer with a right-looking table,
and it is the only failure in this product a reader has no way to catch.

Why it reads the plan rather than the reading
---------------------------------------------
The obvious implementation compares the question against the semantic reading
— and it is worthless, because a reading that produced a condition and then
lost it on the way to the runtime passes. The gate therefore reads the
`FILTER` operation in the plan that is about to run and reports the columns it
genuinely tests. If a condition is not in there, it did not happen, whatever
any earlier stage believed.

What the product does about it
------------------------------
Repair first: the planner tries again for the condition it dropped. Only when
the governed data genuinely cannot carry it does the answer state the
limitation — and then it states it, in the words the person used, rather than
narrating around it.

The other half of this module is the sentence that describes the population.
It is composed from the executed predicates, so a claim that a condition was
tested is a report of the plan rather than an echo of the question. The old
sentence was built from the READING, which is how the screen came to say
"each condition was tested on the same joined population" about a population
selected on one condition of two.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from backend.orchestration import predicates as pr


@dataclass(frozen=True)
class Enforcement:
    """What was asked for, what ran, and the difference."""

    requested: tuple[pr.Test, ...] = ()
    executed: tuple[pr.Test, ...] = ()
    missing: tuple[pr.Test, ...] = ()
    #: The Boolean structure, as a sentence, over the executed predicates only.
    logic: str = ""
    #: The same, with the governed values the answer's subject already names
    #: pruned — but only where the structure is a conjunction, because under
    #: an OR a pruned branch changes which rows the sentence describes.
    headline: str = ""
    #: Concepts the question attached a movement or a level to but which
    #: reached no predicate at all. These never appear in the tree, so they
    #: cannot be found by comparing it with the plan.
    unread: tuple[str, ...] = ()
    #: The tree itself, for the post-result check. A per-condition check that
    #: every row satisfies every condition is only valid under a conjunction;
    #: under an OR it fails correct rows, which is how enabling disjunctions
    #: first showed up — as a withheld answer over a right result.
    tree: pr.Node | None = None

    @property
    def complete(self) -> bool:
        return not self.missing and not self.unread

    @property
    def limitation(self) -> str:
        """One sentence naming what was NOT enforced, or empty.

        Written for the answer's caveats, so it names the condition rather than
        the column and does not apologise.
        """
        names = [t.describe() for t in self.missing] + list(self.unread)
        names = [n for n in names if n]
        if not names:
            return ""
        listed = _and_list(names)
        was = "condition was" if len(names) == 1 else "conditions were"
        return (f"The following {was} asked for but could not be applied to "
                f"the governed data, so the population is wider than the "
                f"question: {listed}. Treat the rows as meeting the remaining "
                f"conditions only.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "requested": [t.to_dict() for t in self.requested],
            "executed": [t.to_dict() for t in self.executed],
            "missing": [t.to_dict() for t in self.missing],
            "unread": list(self.unread),
            "complete": self.complete,
            "logic": self.logic,
            "headline": self.headline,
        }


def _and_list(items: list[str]) -> str:
    if len(items) <= 1:
        return items[0] if items else ""
    return ", ".join(items[:-1]) + " and " + items[-1]


def _columns_tested(params: Any) -> set[str]:
    """Every column a FILTER's parameters genuinely test.

    Both forms, because a plan may carry either: the flat predicate list, and
    the expression tree a disjunction or a negation compiles to.
    """
    found: set[str] = set()
    if not isinstance(params, dict):
        return found

    predicates = params.get("where") or params.get("conditions") or []
    if isinstance(predicates, dict):
        predicates = [predicates]
    for predicate in predicates:
        if isinstance(predicate, dict):
            column = predicate.get("column") or predicate.get("field")
            if column:
                found.add(str(column))

    expression = params.get("expression") or params.get("expr")
    if expression is not None:
        found |= _expression_columns(expression)
    return found


def _expression_columns(node: Any) -> set[str]:
    if not isinstance(node, dict):
        return set()
    found: set[str] = set()
    if str(node.get("type") or "") == "column" and node.get("name"):
        found.add(str(node["name"]))
    for argument in node.get("args") or []:
        found |= _expression_columns(argument)
    for pair in node.get("whens") or []:
        for part in pair or []:
            found |= _expression_columns(part)
    if node.get("otherwise") is not None:
        found |= _expression_columns(node["otherwise"])
    return found


def enforced_columns(plan: Any) -> set[str]:
    """Every column any FILTER in the plan tests."""
    operations = []
    if isinstance(plan, dict):
        operations = plan.get("operations") or []
    else:
        operations = getattr(plan, "operations", None) or []
    found: set[str] = set()
    for operation in operations:
        if isinstance(operation, dict):
            if str(operation.get("op") or "") != "FILTER":
                continue
            found |= _columns_tested(operation.get("params"))
        else:
            if str(getattr(operation, "op", "") or "") != "FILTER":
                continue
            found |= _columns_tested(getattr(operation, "params", None))
    return found


def inspect(tree: pr.Node | None, plan: Any, *,
            unread: list[str] | None = None) -> Enforcement:
    """Compare the predicates the question set with the ones the plan applies."""
    requested = tuple(tree.leaves()) if tree is not None else ()
    tested = enforced_columns(plan)
    executed = tuple(t for t in requested if t.field in tested)
    missing = tuple(t for t in requested if t.field not in tested)
    logic = ""
    headline = ""
    if tree is not None and not missing:
        logic = tree.describe()
        headline = (tree.without({pr.MEMBERSHIP}).describe()
                    if tree.is_conjunction() else logic)
    elif executed:
        # A tree with a hole in it must not be described as though it were
        # whole, so the sentence falls back to the predicates that did run.
        logic = _and_list([t.describe() for t in executed])
        headline = _and_list([t.describe() for t in executed
                              if t.kind != pr.MEMBERSHIP]) or logic
    return Enforcement(requested=requested, executed=executed, missing=missing,
                       logic=logic, headline=headline,
                       unread=tuple(unread or ()), tree=tree)


def population_sentence(enforcement: Enforcement, *, grain: str,
                        opening: str = "", closing: str = "") -> str:
    """How the population was selected, said from the plan that selected it.

    Deliberately makes no claim about conditions that did not run: the sentence
    names what was tested, and the caveat named by `Enforcement.limitation`
    carries what was not.
    """
    if not enforcement.executed:
        return ""
    window = (f" between {opening} and {closing}"
              if opening and closing and opening != closing else "")
    intersection = ""
    if len(enforcement.executed) > 1:
        intersection = (" Every condition was applied to the same joined rows, "
                        "so this is the intersection rather than the union.")
    return (f"These are the {grain}s where {enforcement.logic}"
            f"{window}.{intersection}")


def unread_conditions(text: str, matches: list[Any], conditions: list[Any],
                      filters: list[tuple[str, str]]) -> list[str]:
    """Concepts the question put a direction on that produced no predicate.

    The live defect was one of these before it was anything else: "downgraded"
    resolved to the internal rating, the sentence plainly asserted a movement
    of it, and no condition came out. Comparing the tree with the plan cannot
    see that, because the leaf was never made — so this looks at the concepts
    the reading resolved and asks, of each one, whether the question said
    something about it that the plan is not testing.
    """
    from backend.orchestration import semantics as sm

    settled = {str(getattr(c, "field", "") or "") for c in conditions}
    settled |= {f for f, _ in filters}
    out: list[str] = []
    for match in matches:
        field_name = str(getattr(match, "field", "") or "")
        if not field_name or field_name in settled:
            continue
        phrase = str(getattr(match, "phrase", "") or "")
        if not phrase:
            continue
        directed = sm.movement_near(text, phrase) is not None \
            or sm.threshold_near(text, phrase) is not None
        if directed:
            out.append(phrase)
    return out


# ============================================== structure the plan did not honour
#
# The tree-against-plan comparison above catches a predicate that was BUILT and
# then not applied. It cannot catch one that was never built, because there is
# no leaf to miss — and that is the shape the live defect took. These three
# checks read the sentence instead, and each one asks a question with a
# yes-or-no answer:
#
#   * a clause that plainly asserts a direction, with no governed concept in it
#   * a negation in the question, with no negation in the plan
#   * an explicit "either ... or", with no disjunction in the plan
#
# None of them guesses at meaning. Each detects a structure the person wrote
# that the plan does not contain, which is exactly the condition under which an
# answer must not present itself as complete.

#: An explicit disjunction. "either" or "whichever", because a bare "or"
#: appears in ordinary listing ("by sector or region") where no disjunction of
#: CONDITIONS is meant, and reporting those would be crying wolf.
_EXPLICIT_OR = re.compile(r"\beither\b|\bor\b\s+(?:higher|greater|worse|more)\b"
                          r"|\bwhichever\b", re.IGNORECASE)

#: A negation applied to a condition, as opposed to one inside a bound.
_EXPLICIT_NOT = re.compile(
    r"\b(?:not|never|without|excluding|other than|apart from)\b"
    r"(?!\s+(?:more than|less than|greater than|fewer than|lower than|"
    r"higher than|above|below|over|under|at least|at most))", re.IGNORECASE)


def _has(tree: pr.Node | None, kind: str) -> bool:
    if tree is None:
        return False
    if tree.kind == kind:
        return True
    return any(_has(c, kind) for c in tree.children)


def dropped_structure(text: str, enforcement: Any, tree: pr.Node | None,
                      matches: list[Any], conditions: list[Any],
                      filters: list[tuple[str, str]]) -> list[str]:
    """Everything the question asked for that the plan does not contain.

    Reported in the person's own words, because that is what they will check
    the answer against — "worsening liquidity", not `liquidity_ratio_change`.
    """
    from backend.orchestration import semantics as sm

    said = str(text or "")
    lowered = said.lower()
    found: list[str] = []

    settled = {str(getattr(c, "field", "") or "") for c in conditions}
    settled |= {f for f, _ in filters}
    placed = {str(getattr(m, "phrase", "") or "").lower()
              for m in matches if str(getattr(m, "phrase", "") or "")}

    for clause in sm.clauses(said):
        if any(phrase and phrase in clause.lower() for phrase in placed):
            continue
        directed = (sm.find_movement(clause) is not None
                    or sm.find_threshold(clause) is not None)
        if not directed:
            continue
        # A direction with nothing governed to apply it to. The clause names
        # something CreditProbe has no word for, and the answer must say which
        # words those were rather than quietly leaving them out.
        trimmed = _subject(clause)
        if trimmed:
            found.append(trimmed)

    if _EXPLICIT_NOT.search(lowered) and not _has(tree, pr.NOT):
        found.append("the exclusion the question stated")
    if _EXPLICIT_OR.search(lowered) and not _has(tree, pr.OR):
        found.append("the either/or the question stated")

    # A concept resolved, given a direction, and still not filtered on.
    for match in matches:
        field_name = str(getattr(match, "field", "") or "")
        phrase = str(getattr(match, "phrase", "") or "")
        if not phrase or not field_name or field_name in settled:
            continue
        if sm.movement_near(said, phrase) is None \
                and sm.threshold_near(said, phrase) is None:
            continue
        found.append(phrase)

    return list(dict.fromkeys(f for f in found if f))


#: Words that carry no subject, so a clause trimmed to its subject reads as the
#: thing asked about rather than as the whole sentence.
_LEADING = re.compile(
    r"^\s*(?:which|what|who|whose|show|list|give|find|and|or|but|that|the|"
    r"a|an|are|is|was|were|have|has|had|do|does|did|also|with|of|in|on|"
    r"borrowers?|customers?|clients?|names?|counterpart(?:y|ies))\b\s*",
    re.IGNORECASE)


def _subject(clause: str) -> str:
    trimmed = " ".join(str(clause or "").split())
    previous = ""
    while trimmed and trimmed != previous:
        previous = trimmed
        trimmed = _LEADING.sub("", trimmed).strip(" ,.?!")
    return trimmed


def dropped_sentence(dropped: list[str]) -> str:
    """The caveat naming what the plan does not test."""
    listed = _and_list(list(dropped))
    was = "condition was" if len(dropped) == 1 else "conditions were"
    return (f"CreditProbe could not apply {listed} to the governed data, so "
            f"this {was} not used to select the population. The rows meet the "
            f"remaining conditions only.")


__all__ = [
    "Enforcement",
    "dropped_sentence",
    "dropped_structure",
    "enforced_columns",
    "inspect",
    "population_sentence",
    "unread_conditions",
]
