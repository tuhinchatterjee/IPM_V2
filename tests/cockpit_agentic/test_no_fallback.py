"""There is no fallback path. Specification sections 17 and 18.

Section 17 forbids a hidden fallback to the old deterministic narrative engine
if the Opus flow fails, and section 18 forbids a canned ECL decomposition
standing in for an unavailable model. Those are the easiest rules in the
specification to break by accident and the hardest to notice: a fallback added
"just in case" makes every test pass and every demonstration meaningless.

So they are tested structurally, by reading the source. A fallback cannot be
called if it cannot be imported.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parents[2] / "backend/cockpit_agentic"

#: Modules the Cockpit path must never reach. The legacy deterministic answer
#: path, the legacy analyst, and Cockpit V2's template composer and its
#: prescribed factor decomposition.
FORBIDDEN_ROOTS = (
    "backend.orchestration",
    "backend.analyst",
    "backend.cockpit_v2",
    "backend.engine",
    "backend.brain",
)


def modules() -> list[Path]:
    return sorted(PACKAGE.rglob("*.py"))


def imported_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def test_the_cockpit_package_imports_nothing_from_the_legacy_answer_paths():
    offences: list[str] = []
    for path in modules():
        for name in imported_names(path):
            for forbidden in FORBIDDEN_ROOTS:
                if name == forbidden or name.startswith(f"{forbidden}."):
                    offences.append(f"{path.name} imports {name}")
    assert offences == [], (
        "section 17: the Cockpit must not be able to fall back to the "
        "deterministic engine or the legacy analyst, and section 18 forbids a "
        "canned decomposition standing in for a missing model. "
        + "; ".join(offences))


def test_the_package_never_imports_the_prescribed_factor_decomposition():
    """Cockpit V2's Shapley attribution is a PRESCRIBED method. It survives as
    a test oracle; it is not reachable from the answer path."""
    for path in modules():
        source = path.read_text()
        assert "attribution" not in source.lower() or "attribution" in (
            path.name), f"{path.name} references the V2 attribution module"


def test_no_module_executes_generated_code_in_process():
    """Section 10.2: never quietly downgrade to unsafe in-process execution."""
    for path in modules():
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in ("exec", "eval", "compile"), (
                    f"{path.name} line {node.lineno} calls {node.func.id}()")


def test_the_runtime_has_no_branch_that_authors_sql():
    """Section 7.6A, read off the source rather than asserted.

    CreditProbe validates, executes and diagnoses. The only SQL literals
    permitted in the runtime are the ones it needs to READ its own metadata --
    sample rows and distinct filter values -- and those live in `sql.py`, not
    in the failure or runtime modules where a "helpful" repair would go.
    """
    for name in ("runtime.py", "failure.py"):
        source = (PACKAGE / name).read_text()
        lowered = source.lower()
        for fragment in ("select ", "group by", "order by", " from cockpit_"):
            assert fragment not in lowered, (
                f"{name} contains the SQL fragment {fragment!r}; CreditProbe "
                f"never authors a query")


def test_the_service_has_no_deterministic_answer_branch():
    source = (PACKAGE / "service.py").read_text()
    for fragment in ("deterministic_answer", "canned", "fallback_answer",
                     "compose("):
        assert fragment not in source, (
            f"service.py references {fragment!r}")


@pytest.mark.parametrize("module_name", [p.name for p in modules()])
def test_every_module_is_importable_on_its_own(module_name):
    """A module that only imports inside a function can hide a forbidden
    dependency from the AST check above. Importing each one proves the package
    is what it appears to be."""
    import importlib

    stem = module_name[:-3]
    if stem == "__init__":
        stem = ""
    target = f"backend.cockpit_agentic{'.' + stem if stem else ''}"
    importlib.import_module(target)
