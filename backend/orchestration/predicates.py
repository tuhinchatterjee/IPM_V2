"""
The Boolean structure of a question, kept as a structure.

The failure this exists to prevent
----------------------------------
    "Which customers were downgraded and had expected credit loss rise?"

answered with every customer whose ECL rose. The downgrade condition was read,
resolved to a governed field, and then lost on the way to the plan. Nothing on
screen said a condition had gone missing, so the answer looked right: a table
of real borrowers, real ECL movements, a heading quoting both conditions, and a
population that satisfied one of them.

That is the worst shape of error an analytical product has. A wrong number
invites a second look; a right number about the wrong population does not.

What this module holds
----------------------
An explicit tree — AND, OR, NOT, and the governed tests at the leaves —
rather than a flat list of conditions that some later step is trusted to
combine correctly. A list cannot express

    (rising PD AND rating downgrade) OR Stage 3

at all: flattened, it is five loose concepts and whatever the compiler's
default combiner happens to be. Written as a tree it is exactly one thing, it
survives serialisation onto the Trace, and it can be compared against the plan
that actually ran — which is what makes the coverage gate in `gate.py`
possible. You cannot check that every condition was enforced unless you first
wrote down, in one place, what every condition was.

The tree is built from the question's OWN connectives. "and" is a conjunction,
"or" is a disjunction, "not"/"without"/"excluding" negate, and brackets group.
No connective is invented: a sentence with one condition produces a one-leaf
tree, and the flat where-list the runtime has always been given is what comes
out the other side, unchanged.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# The node kinds. A tree is closed over these four.
AND = "AND"
OR = "OR"
NOT = "NOT"
TEST = "TEST"

#: What a leaf tests. `movement` and `level` mirror the two kinds of condition
#: the semantic reader produces; `membership` is a governed value filter —
#: "Stage 2", "Shipping" — which is a predicate on the population exactly as
#: much as a movement is, and was previously carried in a separate list where
#: nothing could see the two together.
MOVEMENT = "movement"
LEVEL = "level"
MEMBERSHIP = "membership"


@dataclass(frozen=True)
class Test:
    """One governed predicate, and the words that asked for it.

    `phrase` is load-bearing rather than decorative: it is how a leaf is
    attached to the clause it came from, and how the coverage gate reports a
    condition the plan failed to enforce in the user's own words rather than as
    a column name.
    """

    field: str
    op: str
    value: Any = 0.0
    kind: str = MOVEMENT
    dataset: str = ""
    phrase: str = ""
    label: str = ""

    def describe(self) -> str:
        return self.label or self.phrase or self.field

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "field": self.field, "dataset": self.dataset,
                "op": self.op, "value": self.value, "phrase": self.phrase,
                "label": self.label}


@dataclass(frozen=True)
class Node:
    """One node of the tree. A leaf carries a test; a branch carries children."""

    kind: str
    children: tuple[Node, ...] = ()
    test: Test | None = None

    # ---- construction ----------------------------------------------------

    @staticmethod
    def leaf(test: Test) -> Node:
        return Node(TEST, test=test)

    @staticmethod
    def all_of(children: list[Node] | tuple[Node, ...]) -> Node:
        return _combine(AND, children)

    @staticmethod
    def any_of(children: list[Node] | tuple[Node, ...]) -> Node:
        return _combine(OR, children)

    @staticmethod
    def negate(child: Node) -> Node:
        # Double negation is removed here rather than left for the compiler,
        # because "which borrowers are not without covenant pressure" should
        # read on the Trace as the plain statement it is.
        if child.kind == NOT and child.children:
            return child.children[0]
        return Node(NOT, children=(child,))

    # ---- reading ---------------------------------------------------------

    @property
    def empty(self) -> bool:
        return self.kind != TEST and not self.children

    def leaves(self) -> tuple[Test, ...]:
        """Every test in the tree, in the order the sentence stated them."""
        if self.kind == TEST:
            return (self.test,) if self.test is not None else ()
        found: list[Test] = []
        for child in self.children:
            found.extend(child.leaves())
        return tuple(found)

    def is_conjunction(self) -> bool:
        """Whether this is a plain AND of tests — no OR anywhere, no negation.

        The common case, and worth naming: a conjunction compiles to the flat
        where-list the runtime has always been given, so the ordinary question
        produces exactly the plan it produced before this module existed.
        """
        if self.kind == TEST:
            return True
        if self.kind != AND:
            return False
        return all(c.kind == TEST for c in self.children)

    def depth(self) -> int:
        if self.kind == TEST:
            return 1
        return 1 + max((c.depth() for c in self.children), default=0)

    def describe(self) -> str:
        """The tree as a sentence, brackets and all.

        Shown on the Trace and in the answer's scope line. A reader who
        disagrees with the population should be able to see why they got it
        from this string alone.
        """
        if self.kind == TEST:
            return self.test.describe() if self.test is not None else ""
        if self.kind == NOT:
            child = self.children[0] if self.children else None
            inner = child.describe() if child is not None else ""
            if not inner:
                return ""
            # Brackets only where they carry meaning. A negated single test is
            # "not on the watchlist", which is how it was written; "not (on the
            # watchlist)" is the same claim wearing the parser's clothes, and
            # it reaches the reader in the answer's own first sentence.
            if child is not None and child.kind == TEST:
                return f"not {inner}"
            return f"not ({inner})"
        joiner = " and " if self.kind == AND else " or "
        parts = []
        for child in self.children:
            said = child.describe()
            if not said:
                continue
            # Bracket a nested branch of the OTHER kind, which is the only
            # place the reading is genuinely ambiguous without them.
            if child.kind in (AND, OR) and child.kind != self.kind:
                said = f"({said})"
            parts.append(said)
        return joiner.join(parts)

    def without(self, kinds: frozenset[str] | set[str]) -> Node:
        """The tree with leaves of these kinds pruned.

        Used to say the conditions WITHOUT restating the population the
        sentence already names — "452 Stage 2 customers where IFRS 9 stage is
        2 and on the watchlist" says Stage 2 twice. Pruning is only safe under
        a conjunction, and the caller checks that: under an OR, dropping a
        branch changes which rows the sentence describes.
        """
        if self.kind == TEST:
            return Node(AND) if (self.test is not None
                                 and self.test.kind in kinds) else self
        kept = [c.without(kinds) for c in self.children]
        return _combine(self.kind, kept)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"kind": self.kind}
        if self.kind == TEST and self.test is not None:
            out["test"] = self.test.to_dict()
        else:
            out["children"] = [c.to_dict() for c in self.children]
        return out


def _combine(kind: str, children: list[Node] | tuple[Node, ...]) -> Node:
    """A branch, flattened and simplified.

    An AND of one thing is that thing, and an AND inside an AND is one AND.
    Left unsimplified the tree still evaluates correctly but reads as nonsense
    on the Trace, and the Trace is where somebody checks this.
    """
    flat: list[Node] = []
    for child in children:
        if child is None or child.empty:
            continue
        if child.kind == kind:
            flat.extend(child.children)
        else:
            flat.append(child)
    if not flat:
        return Node(kind)
    if len(flat) == 1:
        return flat[0]
    return Node(kind, children=tuple(flat))


# =========================================================== reading a sentence
#
# A small Boolean parser over the words of the question. It is deliberately not
# a general grammar: it recognises the connectives people actually write in a
# credit question, and everything between two connectives is one clause whose
# meaning is decided elsewhere, by the concept resolver.

#: An explicit disjunction. "either" is included because "either A or B" is how
#: the disjunction is usually signalled, and a reader that only saw "or" would
#: still be right — but the word tells us the author meant it, which matters
#: when the sentence also contains a listing "or".
_OR = re.compile(r"\b(?:or)\b", re.IGNORECASE)

#: A conjunction. "but" belongs here: "unchanged ratings BUT materially rising
#: PD" is two conditions that must both hold, not a contrast to be dropped.
_AND = re.compile(
    r"\b(?:and|while|whilst|but|plus|as well as|along with|together with)\b"
    r"|[;,]", re.IGNORECASE)

#: A negation, applying to the clause that follows it.
_NOT = re.compile(
    r"\b(?:not|never|without|excluding|except|other than|apart from)\b",
    re.IGNORECASE)

@dataclass
class _Clause:
    """A run of words between connectives, and how it is joined and negated."""

    text: str
    negated: bool = False
    group: list[Any] = field(default_factory=list)


def _split_top_level(text: str) -> list[tuple[str, str]]:
    """The text split into `(connective, fragment)` at bracket depth zero.

    The connective is the one that PRECEDED the fragment, so the first entry
    always carries an empty connective.
    """
    out: list[tuple[str, str]] = []
    depth = 0
    start = 0
    joiner = ""
    index = 0
    while index < len(text):
        char = text[index]
        if char == "(":
            depth += 1
            index += 1
            continue
        if char == ")":
            depth = max(0, depth - 1)
            index += 1
            continue
        if depth == 0:
            for pattern, kind in ((_OR, OR), (_AND, AND)):
                found = pattern.match(text, index)
                if found:
                    out.append((joiner, text[start:index]))
                    joiner = kind
                    index = found.end()
                    start = index
                    break
            else:
                index += 1
                continue
            continue
        index += 1
    out.append((joiner, text[start:]))
    return [(j, f) for j, f in out if f.strip() or j]


def _bracketed(text: str) -> str:
    """The contents of a fragment that is one bracketed group, else ''."""
    stripped = text.strip()
    if not (stripped.startswith("(") and stripped.endswith(")")):
        return ""
    depth = 0
    for position, char in enumerate(stripped):
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0 and position != len(stripped) - 1:
                return ""
    return stripped[1:-1]


def _split_negation(fragment: str) -> tuple[str, str]:
    """A fragment split into what is asserted and what is denied.

    A negation governs what FOLLOWS it, not the whole fragment. "Which Stage 2
    borrowers are not on watchlist" asserts Stage 2 and denies the watchlist,
    and negating the fragment whole would have asked for borrowers who are
    neither — a smaller and different population, returned without comment.

    "not more than 15%" is left alone: that is a bound the threshold reader
    already understands, and negating it here would apply the same negation
    twice and quietly invert the test.
    """
    for found in _NOT.finditer(fragment):
        after = fragment[found.end():]
        if re.match(r"\s*(?:more than|less than|greater than|fewer than|"
                    r"lower than|higher than|above|below|over|under|"
                    r"exceeding|at least|at most)\b", after, re.IGNORECASE):
            continue
        return fragment[:found.start()], after
    return fragment, ""


def _parse(text: str) -> Any:
    """The Boolean skeleton: nested lists of `_Clause`, joined by kind.

    Returns either a `_Clause` or a `(kind, [parts])` pair.
    """
    parts = _split_top_level(text)
    if not parts:
        return _Clause(text=text)

    # Split on OR first, so AND binds tighter — "A and B or C" is
    # "(A and B) or C", which is how the sentence is read aloud.
    groups: list[list[tuple[str, str]]] = [[]]
    for joiner, fragment in parts:
        if joiner == OR and groups[-1]:
            groups.append([])
        groups[-1].append((joiner, fragment))

    def one(run: list[tuple[str, str]]) -> Any:
        made = [_one_fragment(fragment) for _, fragment in run]
        made = [m for m in made if m is not None]
        if not made:
            return None
        return made[0] if len(made) == 1 else (AND, made)

    built = [one(run) for run in groups]
    built = [b for b in built if b is not None]
    if not built:
        return None
    return built[0] if len(built) == 1 else (OR, built)


def _one_fragment(fragment: str) -> Any:
    inner = _bracketed(fragment)
    if inner:
        return _parse(inner)
    asserted, denied = _split_negation(fragment)
    parts: list[Any] = []
    if asserted.strip():
        parts.append(_Clause(text=asserted))
    if denied.strip():
        parts.append(_Clause(text=denied, negated=True))
    if not parts:
        return None
    return parts[0] if len(parts) == 1 else (AND, parts)


def _mentions(text: str, phrase: str) -> bool:
    """Whether a clause names a phrase, on word boundaries.

    Boundaries rather than a substring, for the same reason the semantic
    reader uses them: "EAD" occurs inside "headroom", and a leaf attached to
    the wrong clause is a condition applied to the wrong half of an OR.
    """
    if not phrase:
        return False
    spaced = re.escape(" ".join(str(phrase).split())).replace(r"\ ", r"\s+")
    return bool(re.search(rf"(?<!\w){spaced}(?!\w)", str(text or ""), re.I))


def _attach(node: Any, tests: list[Test], used: set[int]) -> Node | None:
    """Turn one skeleton node into a tree node, binding the tests it names."""
    if node is None:
        return None
    if isinstance(node, tuple):
        kind, parts = node
        built = [_attach(p, tests, used) for p in parts]
        built = [b for b in built if b is not None and not b.empty]
        if not built:
            return None
        return _combine(kind, built)

    clause: _Clause = node
    mine: list[Node] = []
    for index, test in enumerate(tests):
        if index in used or not _mentions(clause.text, test.phrase):
            continue
        used.add(index)
        mine.append(Node.leaf(test))
    if not mine:
        return None
    made = _combine(AND, mine)
    return Node.negate(made) if clause.negated else made


def read(text: str, tests: list[Test]) -> Node:
    """The question's Boolean structure over the tests it resolved.

    Any test the sentence structure could not place — because the phrase that
    produced it does not appear literally in the text, which happens when a
    filter is inherited from the conversation rather than written in this turn
    — is conjoined at the top. Losing it would be the very defect this module
    exists to stop.
    """
    from backend.orchestration import ordinal

    kept = [t for t in tests if t is not None]
    if not kept:
        return Node(AND)
    used: set[int] = set()
    # "Stage 2 or worse" is a RANGE. Its "or" is part of the value, and
    # splitting the sentence on it produced "stage is 2 or PD rose" — a
    # population several times the size of the one asked for, printed in the
    # answer's own heading. Blanked with equal-length spaces, so every offset
    # and every phrase this reader matches on still lines up.
    said = ordinal.without_qualifiers(str(text or ""))
    built = _attach(_parse(said), kept, used)
    unplaced = [Node.leaf(t) for index, t in enumerate(kept)
                if index not in used]
    if built is None or built.empty:
        return _combine(AND, unplaced)
    if not unplaced:
        return built
    return _combine(AND, [built, *unplaced])


# =========================================================== compiling a tree

#: The runtime's comparison spellings, keyed by the reader's.
_OPS: dict[str, str] = {
    "gt": ">", "gte": ">=", "lt": "<", "lte": "<=", "eq": "=", "ne": "!=",
    "in": "in", "not_in": "not_in",
    "is_null": "is_null", "is_not_null": "is_not_null",
}

#: The scalar function that expresses each comparison inside an expression
#: tree, for the nested case the flat where-list cannot carry.
_FUNCTIONS: dict[str, str] = {
    "gt": "gt", "gte": "gte", "lt": "lt", "lte": "lte", "eq": "eq", "ne": "ne",
}


def where(tree: Node, column_of: Any) -> list[dict[str, Any]]:
    """A pure conjunction as the flat predicate list the runtime takes.

    Raises for anything else, so a caller cannot get a silently wrong filter by
    passing a tree this shape cannot express. `compile_filter` below is what
    callers should use; this is here because a conjunction is the common case
    and its flat form is what makes a readable Trace.
    """
    if not tree.is_conjunction():
        raise ValueError("a tree with OR or NOT cannot be a flat where-list")
    out: list[dict[str, Any]] = []
    for test in tree.leaves():
        out.append({"column": column_of(test), "op": _OPS.get(test.op, "="),
                    "value": test.value})
    return out


def expression(tree: Node, column_of: Any) -> dict[str, Any]:
    """The tree as an IR expression, for the nested and disjunctive cases.

    Built as `Expr` dictionaries rather than SQL text. The runtime binds every
    literal as a parameter, so a value that came from a question can never
    become part of a statement.
    """
    from backend.runtime.ir import Expr

    def build(node: Node) -> Expr:
        if node.kind == TEST and node.test is not None:
            test = node.test
            column = Expr.col(column_of(test))
            if test.op == "is_null":
                return Expr.fn("is_null", column)
            if test.op == "is_not_null":
                return Expr.fn("is_not_null", column)
            if test.op in ("in", "not_in"):
                values = test.value if isinstance(test.value, list) \
                    else [test.value]
                listed = Expr.fn("in_list", column,
                                 *[Expr.lit(v) for v in values])
                return Expr.fn("not", listed) if test.op == "not_in" else listed
            function = _FUNCTIONS.get(test.op, "eq")
            return Expr.fn(function, column, Expr.lit(test.value))
        if node.kind == NOT:
            return Expr.fn("not", build(node.children[0]))
        made = [build(c) for c in node.children]
        if len(made) == 1:
            return made[0]
        function = "and" if node.kind == AND else "or"
        # `and` and `or` compile to a binary operator, so a three-way branch is
        # folded rather than passed as three arguments.
        folded = made[0]
        for nxt in made[1:]:
            folded = Expr.fn(function, folded, nxt)
        return folded

    if tree.empty:
        raise ValueError("an empty tree has no expression")
    return build(tree).to_dict()


def compile_filter(tree: Node, column_of: Any) -> dict[str, Any]:
    """FILTER params for this tree, in whichever form it needs.

    A conjunction keeps the flat `where` list — the shape every existing plan,
    Trace and test already reads. Anything with an OR or a negation becomes an
    `expression`, which is the only form that can carry the structure without
    lying about it.
    """
    if tree.empty:
        return {}
    if tree.is_conjunction():
        return {"where": where(tree, column_of)}
    return {"expression": expression(tree, column_of)}


__all__ = [
    "AND",
    "LEVEL",
    "MEMBERSHIP",
    "MOVEMENT",
    "NOT",
    "Node",
    "OR",
    "TEST",
    "Test",
    "compile_filter",
    "expression",
    "read",
    "where",
]
