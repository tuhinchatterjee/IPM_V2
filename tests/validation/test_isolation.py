"""
Proof that a benchmark's expected answer cannot reach the thing being tested.

Why this test is worth more than the benchmark library
------------------------------------------------------
A hidden benchmark is only hidden if there is no path from production code to
the answers. Care is not a mechanism: somebody adds a "helpful" import, and from
then on the score measures how well the product can look up its own marking
scheme.

So the rule is architectural and this test enforces it by walking the import
graph. `backend/validation` may import production. Production may never import
`backend/validation`.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"

#: Everything that can run while a user's question is being answered.
PRODUCTION = ("orchestration", "runtime", "engine", "api", "services",
              "data_access", "llm", "studio", "early_warning", "trace")

FORBIDDEN = "backend.validation"

#: The single file allowed to reach the evaluation package, and why.
#:
#: The intelligence check has to be startable from somewhere, and that somewhere
#: is an HTTP endpoint. What matters is the direction: this router calls the
#: runner, the runner calls the orchestrator, and the orchestrator has no way
#: back. `test_the_orchestrator_cannot_see_gold_data_at_runtime` proves the
#: return path does not exist even dynamically.
ALLOWED = {"backend/api/routers/validation.py"}


def _imports(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def _production_files() -> list[pathlib.Path]:
    return [p for package in PRODUCTION
            for p in (BACKEND / package).rglob("*.py")]


def test_production_never_imports_the_benchmark_library():
    """The one-way rule, checked on every file that can serve a question."""
    offenders: list[str] = []
    for path in _production_files():
        relative = path.relative_to(ROOT).as_posix()
        if relative in ALLOWED:
            continue
        for module in _imports(path):
            if module == FORBIDDEN or module.startswith(FORBIDDEN + "."):
                offenders.append(f"{relative} imports {module}")
    assert not offenders, (
        "Production code must never reach the benchmark's expected answers:\n"
        + "\n".join(offenders))


def test_the_orchestrator_cannot_see_gold_data_at_runtime():
    """Not just static: the module is absent from the running import graph.

    A dynamic import inside a function would pass the AST check above. This
    imports the whole orchestration path in a fresh interpreter and asserts the
    validation package never appeared in `sys.modules`.
    """
    import subprocess
    import sys

    script = (
        "import sys;"
        "import backend.orchestration.orchestrator;"
        "import backend.orchestration.executor;"
        "import backend.orchestration.router;"
        "import backend.orchestration.analysis_planner;"
        "leaked=[m for m in sys.modules if m.startswith('backend.validation')];"
        "print('LEAKED' if leaked else 'CLEAN', leaked)"
    )
    result = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [sys.executable, "-c", script], cwd=ROOT, capture_output=True,
        text=True, timeout=180, check=False,
        env={"PATH": "/usr/bin:/bin", "AI_PROVIDER": "offline",
             "PYTHONPATH": str(ROOT)})
    assert "CLEAN" in result.stdout, (
        f"the validation package was imported by production code: "
        f"{result.stdout}{result.stderr[-400:]}")


def test_no_prompt_in_the_product_mentions_a_benchmark():
    """The prompts are searched for the benchmark's own vocabulary."""
    from backend.orchestration import interpretation, router

    for text in (router.SYSTEM, interpretation.SYSTEM):
        lowered = text.lower()
        for word in ("benchmark", "expected answer", "reference answer",
                     "gold", "validation case", "correct answer is"):
            assert word not in lowered, (
                f"a production prompt mentions {word!r}")


def test_the_reference_is_computed_after_the_answer(monkeypatch):
    """The ordering rule, asserted rather than assumed.

    `gold.compute` is replaced with a spy that records when it ran. If a
    reference were computed before the orchestrator answered, the recorded order
    would show it — and a benchmark that knows the answer before it asks the
    question is not a benchmark.
    """
    from backend.validation import benchmarks, runner

    order: list[str] = []
    real_compute = runner.gold.compute
    real_answer = runner_answer_hook()

    def spy_compute(spec):
        order.append("reference")
        return real_compute(spec)

    def spy_answer(*args, **kwargs):
        order.append("answer")
        return real_answer(*args, **kwargs)

    monkeypatch.setattr(runner.gold, "compute", spy_compute)
    monkeypatch.setattr("backend.orchestration.executor.answer_investigation",
                        spy_answer)

    runner.run([benchmarks.BY_ID["agg-001"]])
    assert order[:2] == ["answer", "reference"], (
        f"the reference must be computed only after the answer: {order}")


def runner_answer_hook():
    from backend.orchestration.executor import answer_investigation

    return answer_investigation


@pytest.mark.parametrize("family", ["metadata", "calculation", "conversation"])
def test_every_family_has_cases_to_draw_from(family):
    """A balanced sample cannot be balanced if a family is empty."""
    from backend.validation import benchmarks

    assert len(benchmarks.by_family(family)) >= 10
