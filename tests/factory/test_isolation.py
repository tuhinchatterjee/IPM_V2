"""
The seal: nothing that shapes the product may read the holdout.

Why this is a test and not a convention
---------------------------------------
Every number the Intelligence Factory reports as evidence comes from
`intelligence_factory.holdout`, and its entire value is that nobody looked at
it while making the product better. A single `from intelligence_factory import
holdout` inside `backend/` would end that quietly — the tests would still pass,
the score would still print, and it would no longer mean anything.

So the seal is asserted three ways, because each one catches what the others
miss:

* **statically** — no module under `backend/` names the factory at all, which
  catches an import somebody added and never called;
* **structurally** — the curriculum and the generators do not import the
  holdout, which catches tuning through the open set;
* **at runtime** — answering a question does not load the holdout module, which
  catches a dynamic import that no amount of source reading would find.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
FACTORY = ROOT / "intelligence_factory"

#: The modules that must never be reachable from the product.
SEALED = ("intelligence_factory.holdout", "intelligence_factory")


def _imports(path: Path) -> set[str]:
    """Every module name this file imports, however it spells it."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    except SyntaxError as e:  # pragma: no cover - a broken file is its own bug
        pytest.fail(f"{path} does not parse: {e}")

    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
            found.update(f"{node.module}.{a.name}" for a in node.names)
    return found


def _python_files(directory: Path) -> list[Path]:
    return [p for p in directory.rglob("*.py")
            if "__pycache__" not in p.parts]


# ---------------------------------------------------------------------------
# Statically
# ---------------------------------------------------------------------------


def test_no_backend_module_imports_the_factory():
    """Production code does not import the evaluation harness at all.

    Not only the holdout. A backend module that imports the curriculum can
    reach the holdout in one more line, and the point of the seal is that the
    line is never there to be extended.
    """
    offenders = [
        f"{path.relative_to(ROOT)} imports {name}"
        for path in _python_files(BACKEND)
        for name in _imports(path)
        if name.split(".")[0] == "intelligence_factory"
    ]
    assert not offenders, (
        "The product must not import the Intelligence Factory:\n  "
        + "\n  ".join(offenders))


def test_no_backend_source_mentions_the_holdout():
    """Not even in a string, a comment or a getattr.

    A dynamic import is spelled with a string, so an import-graph check alone
    would not see it.
    """
    offenders = [
        str(path.relative_to(ROOT)) for path in _python_files(BACKEND)
        if "holdout" in path.read_text(encoding="utf-8-sig").lower()
    ]
    assert not offenders, (
        "The word 'holdout' appears in production source, which is how a "
        "dynamic import hides:\n  " + "\n  ".join(offenders))


# ---------------------------------------------------------------------------
# Structurally
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("module", ["curriculum", "generators", "metrics"])
def test_the_open_curriculum_cannot_see_the_holdout(module):
    """Tuning through the development set is still tuning.

    The curriculum is written to be looked at and iterated against. If it could
    read the holdout, a case could be copied across and the sealed score would
    be measuring the curriculum again.
    """
    names = _imports(FACTORY / f"{module}.py")
    assert not [n for n in names if "holdout" in n], (
        f"{module}.py imports the holdout; the open set must not be able to "
        "read the sealed one.")


def test_the_holdout_declares_no_expected_answers():
    """A case says what a correct answer must DO, never what it must SAY.

    A stored figure gets quietly aligned to whatever the product returns by
    somebody fixing a "wrong" test. A specification cannot be.
    """
    from intelligence_factory import holdout

    for case in holdout.CASES:
        for turn in case.turns:
            payload = turn.to_dict()
            assert "answer" not in payload
            assert "expected" not in payload
            for value in payload.values():
                assert not isinstance(value, (int, float)) or isinstance(
                    value, bool), (
                    f"{case.id} carries a bare number, which is how a gold "
                    "answer gets in")


def test_every_correction_says_what_changed_and_why():
    """A revised expectation is published, with its evidence.

    Revising a sealed case is the one move that can quietly turn a failure into
    a pass, so each one has to name the case, what it required before, what it
    requires now, and the fact about the governed data that made the old
    requirement impossible.
    """
    from intelligence_factory import holdout

    for correction in holdout.CORRECTIONS:
        assert set(correction) == {"case", "was", "now", "why"}
        assert correction["case"] in holdout.BY_ID
        assert len(correction["why"]) > 80, (
            f"{correction['case']}: a revision needs a reason somebody can "
            "disagree with")


# ---------------------------------------------------------------------------
# At runtime
# ---------------------------------------------------------------------------


def test_answering_a_question_never_loads_the_holdout():
    """The strongest of the three: what actually happens when a user asks.

    Catches an import added inside a function, behind a flag, or through
    `importlib` — none of which the static checks can see.
    """
    for name in list(sys.modules):
        if name.startswith("intelligence_factory"):
            del sys.modules[name]

    from backend.orchestration import conversation as cv
    from backend.orchestration import memory as wm
    from backend.orchestration.executor import answer_investigation

    answer_investigation(
        "What is total exposure at default by sector?", persist=False,
        state=cv.load({}), memory=wm.load({}))

    loaded = sorted(n for n in sys.modules if n.startswith("intelligence_factory"))
    assert not loaded, (
        "Answering a question loaded the Intelligence Factory: " + ", ".join(loaded))


def test_the_certifier_reaches_the_holdout_only_in_certification_mode():
    """The other half of the seal: development mode must not read it either.

    A development run is the one people repeat while changing prompts. If it
    quietly included the sealed cases, every one of those runs would be
    tuning against them.
    """
    source = (FACTORY / "certify.py").read_text(encoding="utf-8-sig")
    development = source[source.index("def development("):
                         source.index("def certification(")]
    assert "holdout" not in development, (
        "development() can see the holdout; only certification() may.")
