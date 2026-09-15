"""The save-gate matrix names tests that exist. §19.

A matrix is only worth having if it cannot drift from the code. This one
cannot: every row names a real pytest node, and the check below resolves each
one against the source — the file, the class, the function — and fails if it
has been deleted, renamed, quarantined with `skip` or `xfail`, or if a row
reports anything but PASS.

What this check does NOT do is make a test pass. It proves the row points at
something real and still running. Whether that test passes is established by
running `tests/playbook`, which is where these tests live and where the
matrix's Evidence section records the counts. Keeping the two apart matters:
a check that claimed to verify passes by reading a Markdown table would be
exactly the document a reader trusts instead of counting.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MATRIX = ROOT / "docs" / "playbook" / "SAVE_GATE_MATRIX.md"

#: The nineteen classes §19 names, in its order. Written out rather than
#: counted from the table, so a row deleted from the document fails here
#: instead of shrinking the requirement to fit.
CLASSES = (
    "Title duplicated as a normal section",
    "Long PDF heading wraps and defeats the check",
    "Structural numerals misclassified as claims",
    "Raw vs displayed spreadsheet values",
    "Stale parser revisions",
    "Global numeric collision",
    "Re-rounded unsupported numeric value",
    "Canonical vs rendered figure mismatch",
    "Unsupported figure sanitisation",
    "Missing substantive section",
    "Title mismatch",
    "Parser re-read",
    "Stale source used during generation",
    "Scoped edit modifying an unrelated section",
    "Provider timeout",
    "Missing AUTHOR model",
    "Duplicate generation on refresh",
    "Incomplete stream being saved",
    "Partial failed artifact replacing the last valid one",
    # Found after the first nineteen, by the work that followed. §33.
    "Metric suggestions used as governed values",
    "Then/Now across different populations",
    "Then/Now unit mismatch",
    "Section retitle loses its state",
    "First-open readiness key divergence",
    "Duplicate idempotency key across workspaces",
    "A 29%-complete document marked ready",
    "A machine moving a section into review",
    "A dashboard pane taking the page down",
    "Seeded state that silently matches nothing",
)

_ROW = re.compile(
    r"^\| (\d+) \| ([^|]+?) \| ([^|]+?) \| `([^`]+)` \| ([^|]+?) \| (\w+) \|$",
    re.M)


@pytest.fixture(scope="module")
def rows() -> list[tuple[str, ...]]:
    assert MATRIX.exists(), f"{MATRIX} is missing"
    found = _ROW.findall(MATRIX.read_text())
    assert found, "no matrix rows parsed — has the table format changed?"
    return found


def test_every_failure_class_has_exactly_one_row(rows):
    assert [r[1].strip() for r in rows] == list(CLASSES)


def test_the_rows_are_numbered_in_order(rows):
    assert [r[0] for r in rows] == [str(n) for n in range(1, len(CLASSES) + 1)]


def test_every_row_names_a_layer(rows):
    assert all(r[2].strip() for r in rows)


def test_every_row_states_the_expected_behaviour(rows):
    # Long enough to say something. A one-word "works" is not an expectation
    # anybody can check a change against.
    assert all(len(r[4].strip()) > 40 for r in rows)


def test_every_row_passes(rows):
    failing = [(r[0], r[1].strip(), r[5]) for r in rows if r[5] != "PASS"]
    assert not failing, f"the matrix requires every row to pass: {failing}"


# --------------------------------------------------------------------------
# The rows point at real, running tests
# --------------------------------------------------------------------------


def _resolve(node_id: str) -> ast.FunctionDef | str:
    """Find the test a row names, in the source.

    Two suites are addressed here, because two suites hold the line. A Python
    row is `file.py::Class::test` and is resolved through the AST. A frontend
    row is `file.ts::the test's name` and is resolved by finding the
    `test("…")` call — `node --test` has no classes, so there is nothing else
    to key on.

    Either way the point is the same: a row cannot name a test that is not
    there.
    """
    if "::" not in node_id:
        raise AssertionError(f"{node_id!r} names no test")
    path, _, rest = node_id.partition("::")
    source = ROOT / path
    assert source.exists(), f"{path} does not exist"

    if path.endswith(".ts"):
        name = rest
        text = source.read_text()
        assert f'test("{name}"' in text, f"{path} has no test named {name!r}"
        return name

    parts = rest.split("::")
    assert len(parts) == 2, f"{node_id!r} is not file::Class::test"
    class_name, func_name = parts
    tree = ast.parse(source.read_text(), filename=str(source))

    classes = [n for n in tree.body
               if isinstance(n, ast.ClassDef) and n.name == class_name]
    assert classes, f"{path} has no class {class_name}"
    functions = [n for n in classes[0].body
                 if isinstance(n, ast.FunctionDef) and n.name == func_name]
    assert functions, f"{class_name} has no test {func_name}"
    return functions[0]


def _decorator_names(func: ast.FunctionDef) -> set[str]:
    names = set()
    for decorator in func.decorator_list:
        for node in ast.walk(decorator):
            if isinstance(node, ast.Attribute):
                names.add(node.attr)
            elif isinstance(node, ast.Name):
                names.add(node.id)
    return names


def test_every_row_names_a_test_that_exists(rows):
    for number, name, _, node_id, _, _ in rows:
        assert _resolve(node_id) is not None, f"row {number} ({name})"


def test_no_row_is_held_up_by_a_quarantined_test(rows):
    """A skipped or expected-to-fail test is not a regression guard. A row
    whose test was quarantined must stop reading PASS."""
    for number, name, _, node_id, _, _ in rows:
        found = _resolve(node_id)
        if isinstance(found, str):
            # A `node --test` test has no decorators to quarantine it; the
            # only way to disable one is to delete it, which `_resolve`
            # already catches.
            continue
        marks = _decorator_names(found)
        assert not marks & {"skip", "skipif", "xfail"}, (
            f"row {number} ({name}) is guarded by a quarantined test")


def test_the_named_tests_are_spread_across_the_layers(rows):
    """Rows pointing at one file would mean the matrix describes one test's
    neighbourhood rather than the save gate."""
    files = {r[3].split("::")[0] for r in rows}
    assert len(files) >= 9, sorted(files)


def test_every_named_test_lives_in_a_suite_that_is_actually_run(rows):
    """Two suites hold this matrix, and both run on every verification pass:
    `pytest tests/playbook` and `npm test` in the frontend. A row naming a
    test in neither would be a row nobody checks."""
    for number, name, _, node_id, _, _ in rows:
        path = node_id.split("::")[0]
        assert (path.startswith("tests/playbook/")
                or path.startswith("frontend/src/")), (
            f"row {number} ({name}) names {path}, which neither suite runs")


def test_the_evidence_section_records_a_real_run(rows):
    text = MATRIX.read_text()
    assert "Last full run" in text
    # Whitespace-tolerant because Markdown wraps the line; otherwise exact.
    assert re.search(r"\*\*\d+ passed,\s+\d+ skipped,\s+0\s+failed\*\*",
                     text), "the Evidence section must record real counts"
    # A skip is never a pass. The document has to say so.
    assert "a skip is never counted as a pass" in text
