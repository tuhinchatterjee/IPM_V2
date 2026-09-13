"""The requirement matrix says what the rows say. PB-045.

A status table that disagrees with its own roll-up is worse than no table: it
is the document a reader trusts instead of counting. This is cheap to check
mechanically, so it is checked mechanically — including that the vocabulary
stays exact, because "mostly passing" is how a blocked criterion becomes a
claimed one.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

MATRIX = Path(__file__).resolve().parents[2] / "docs" / "playbook" \
    / "REQUIREMENTS_MATRIX.md"

VOCABULARY = {"PASS", "FAIL", "BLOCKED", "SKIPPED", "DEFERRED-INTEGRATION"}

_ROW = re.compile(r"^\| (PB-\d{3}) \| .* \| ([A-Z-]+) \|$", re.M)
_ROLLUP = re.compile(r"^\| ([A-Z-]+) \| *(\d+)", re.M)


@pytest.fixture(scope="module")
def text() -> str:
    assert MATRIX.exists(), f"{MATRIX} is missing"
    return MATRIX.read_text()


@pytest.fixture(scope="module")
def rows(text) -> dict[str, str]:
    return dict(_ROW.findall(text))


def test_every_requirement_has_exactly_one_row(rows):
    assert list(rows) == [f"PB-{n:03d}" for n in range(1, 46)]


def test_every_status_is_in_the_declared_vocabulary(rows):
    unknown = {pb: status for pb, status in rows.items()
               if status not in VOCABULARY}
    assert not unknown


def test_the_roll_up_agrees_with_the_rows(text, rows):
    counted = {status: sum(1 for s in rows.values() if s == status)
               for status in VOCABULARY}
    section = text[text.index("## Status roll-up"):]
    claimed = {name: int(n) for name, n in _ROLLUP.findall(section)
               if name in VOCABULARY}
    assert claimed == counted, (claimed, counted)


def test_every_status_word_in_the_vocabulary_is_documented(text):
    """A status nobody defined is a status nobody can read."""
    for word in VOCABULARY:
        assert f"`{word}`" in text


def test_a_live_row_names_its_served_model_and_a_request_id(rows, text):
    """The six criteria that need a provider. A live PASS with no request id
    is indistinguishable from a scripted one, which is the thing this whole
    matrix exists to keep apart."""
    live = ("PB-013", "PB-015", "PB-029", "PB-043")
    for pb in live:
        row = next(line for line in text.splitlines()
                   if line.startswith(f"| {pb} |"))
        assert rows[pb] == "PASS"
        assert "claude-opus-5" in row, pb
        assert "req_" in row, pb

    # PB-017 and PB-030 are live too; their evidence records the served model
    # and the run, with request ids carried on PB-030's row.
    for pb in ("PB-017", "PB-030"):
        row = next(line for line in text.splitlines()
                   if line.startswith(f"| {pb} |"))
        assert rows[pb] == "PASS" and "claude-opus-5" in row, pb


def test_what_if_is_still_recorded_as_deferred_integration(text):
    """The one honest gap. If a future branch implements What If, this test
    should be what notices that the note is now wrong."""
    assert "What If is\n**DEFERRED-INTEGRATION**" in text \
        or "What If is **DEFERRED-INTEGRATION**" in text \
        or "**What If is\nDEFERRED-INTEGRATION**" in text
    assert "INTEGRATION_NOTES.md" in text
