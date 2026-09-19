"""
The DC-01–DC-42 matrix has to be true.

A matrix is a claim about evidence, and a claim about evidence is worth
exactly as much as the evidence's existence. Five citations in this file were
wrong when it was first written — a renamed test, a file that had moved, a
class that had never had that name — and each was found by reading, which is
not a method that scales or repeats.

So the citations are checked here: every test file named must exist, every
`file.py::Symbol` must be a symbol in that file, every browser journey letter
must be a journey the acceptance script actually runs, and the totals must
add up to 42 without counting a row twice.

What this deliberately does NOT do is judge whether the cited test proves the
criterion. No test can do that. It closes the cheaper failure — a citation
that points at nothing — so that reading the matrix is about whether the
evidence is *good*, rather than whether it is *there*.
"""

from __future__ import annotations

import functools
import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
MATRIX = REPO / "docs" / "playbook" / "DC_MATRIX.md"
TESTS = REPO / "tests"
ACCEPTANCE = (REPO / "scripts" / "acceptance"
              / "playbook_chat_acceptance.py")

#: `test_thing.py::TestClass` or `test_thing.py::test_function`, and bare
#: `test_thing.py`. Backticked in the matrix, which is how they are found.
_CITED = re.compile(r"`([A-Za-z0-9_/.]+\.py)(?:::([A-Za-z0-9_]+))?`")
_ROW = re.compile(r"^\| (DC-\d\d) \|([^|]*)\|(.*)\|\s*$", re.M)
_JOURNEY = re.compile(r"journey[s]?\s+\*\*([A-K])\*\*")

#: The other two browser suites. A row may cite one of these instead of a
#: chat journey — DC-05's selection-survives-preview evidence is in the
#: workspace suite, DC-03's draft round-trip is in the dashboard suite — and
#: naming a suite is as checkable as naming a journey.
_SUITES = {
    "workspace browser suite":
        REPO / "scripts" / "acceptance" / "playbook_browser_acceptance.py",
    "dashboard browser suite":
        REPO / "scripts" / "acceptance" / "playbook_dashboard_acceptance.py",
}


def _rows() -> list[tuple[str, str, str]]:
    return _ROW.findall(MATRIX.read_text())


@functools.lru_cache(maxsize=1)
def _index() -> dict[str, tuple[pathlib.Path, ...]]:
    """Every Python file in the repository, by basename.

    Built once. More than one directory holds a `test_api.py`, and an early
    version of this checker resolved the name to whichever it found first and
    then reported a perfectly good citation as broken. A basename maps to all
    of its files, and a citation is satisfied by any of them.
    """
    found: dict[str, list[pathlib.Path]] = {}
    for path in REPO.rglob("*.py"):
        if ".venv" in path.parts or "node_modules" in path.parts:
            continue
        found.setdefault(path.name, []).append(path)
    return {name: tuple(paths) for name, paths in found.items()}


def _candidates(name: str) -> tuple[pathlib.Path, ...]:
    """Every file a citation could mean. An exact path wins outright."""
    direct = REPO / name
    if direct.is_file():
        return (direct,)
    return _index().get(pathlib.Path(name).name, ())


class TestEveryCitationPointsAtSomething:

    def test_the_matrix_is_there_and_has_every_row(self):
        ids = [r[0] for r in _rows()]
        assert ids == [f"DC-{n:02d}" for n in range(1, 43)], (
            "the matrix must carry DC-01 to DC-42, in order, once each")

    def test_every_cited_file_exists(self):
        missing = []
        for row_id, _status, evidence in _rows():
            for name, _symbol in _CITED.findall(evidence):
                if not _candidates(name):
                    missing.append(f"{row_id} cites {name}")
        assert not missing, "citations point at files that do not exist: " \
                            + "; ".join(missing)

    def test_every_cited_symbol_exists_in_the_file_it_names(self):
        wrong = []
        for row_id, _status, evidence in _rows():
            for name, symbol in _CITED.findall(evidence):
                if not symbol:
                    continue
                paths = _candidates(name)
                if not paths:
                    continue          # the file check reports this one
                pattern = rf"^\s*(class|def)\s+{symbol}\b"
                if not any(re.search(pattern, p.read_text(), re.M)
                           for p in paths):
                    where = ", ".join(str(p.relative_to(REPO)) for p in paths)
                    wrong.append(f"{row_id}: {symbol} is in none of {where}")
        assert not wrong, "; ".join(wrong)


class TestEveryBrowserClaimNamesARealJourney:

    def test_each_cited_journey_is_one_the_script_runs(self):
        """A journey is identified by the label its checks carry, `[C]`.

        Not by a `journey_c` function: C, D, E and F share one function,
        because they are one continuous thread — request, revise, present,
        convert — and splitting them into four workspaces would stop proving
        that the revision sees the document the request made.
        """
        script = ACCEPTANCE.read_text()
        cited = sorted(set(_JOURNEY.findall(MATRIX.read_text())))
        assert cited, "the matrix claims browser evidence but names no journey"
        for letter in cited:
            assert f'"[{letter}]' in script, (
                f"journey {letter} is cited but the acceptance script runs no "
                f"check labelled [{letter}]")

    def test_a_row_claiming_the_browser_names_where_to_look(self):
        """A browser claim must say which run produced it — a chat journey or
        one of the other two suites. "Proven in the browser" with nothing
        named is the claim that cannot be checked, which is the claim worth
        forbidding."""
        for row_id, status, evidence in _rows():
            if "browser scripted" not in status:
                continue
            named = (_JOURNEY.search(evidence)
                     or any(suite in evidence for suite in _SUITES))
            assert named, (
                f"{row_id} claims browser evidence without naming a journey "
                f"or a suite")

    def test_the_suites_a_row_may_cite_are_real_files(self):
        for name, path in _SUITES.items():
            assert path.is_file(), f"{name} cites {path}, which is not there"

    def test_no_row_claims_live_verification(self):
        """Not a style rule. No live call has been made on this code, so a
        live claim here would be false; when one is made, this test is the
        thing that has to be updated deliberately."""
        for row_id, status, _evidence in _rows():
            assert "live verified" not in status, (
                f"{row_id} claims live verification — if that is now true, "
                f"say so here on purpose rather than by editing a table")


class TestTheTotalsAddUp:

    def _counts(self) -> dict:
        rows = _rows()
        return {
            "rows": len(rows),
            "deterministic": sum("PASS — deterministic" in s
                                 for _, s, _ in rows),
            "browser": sum("browser scripted" in s for _, s, _ in rows),
            "blocked": sum("BLOCKED" in s for _, s, _ in rows),
        }

    def test_the_stated_totals_are_the_counted_totals(self):
        counted = self._counts()
        text = MATRIX.read_text()
        for label, key in (("PASS — deterministic", "deterministic"),
                           ("PASS — browser scripted", "browser")):
            stated = re.search(rf"\| {re.escape(label)} \| \*\*(\d+)\*\*",
                               text)
            assert stated, f"the totals table does not state {label}"
            assert int(stated.group(1)) == counted[key], (
                f"{label}: the table says {stated.group(1)}, the rows say "
                f"{counted[key]}")

    def test_no_row_is_left_out_of_the_accounting(self):
        """42 rows, each either proven somehow or explicitly blocked."""
        unaccounted = [
            row_id for row_id, status, _ in _rows()
            if not ("PASS" in status or "BLOCKED" in status
                    or "NOT IMPLEMENTED" in status)]
        assert not unaccounted, (
            f"these rows state no status at all: {unaccounted}")


class TestTheCheckerItselfWorks:
    """Mutation. A checker that passes on a broken matrix is worse than none,
    because it licenses the table."""

    def _with(self, tmp_path, old: str, new: str) -> pathlib.Path:
        text = MATRIX.read_text()
        assert old in text, f"fixture is stale: {old!r} is not in the matrix"
        fake = tmp_path / "DC_MATRIX.md"
        fake.write_text(text.replace(old, new, 1))
        return fake

    def test_a_symbol_that_does_not_exist_is_caught(self, monkeypatch,
                                                    tmp_path):
        fake = self._with(tmp_path, "TestAnOrdinaryQuestion",
                          "TestNoSuchClassAnywhere")
        monkeypatch.setitem(globals(), "MATRIX", fake)
        with pytest.raises(AssertionError,
                           match="TestNoSuchClassAnywhere"):
            TestEveryCitationPointsAtSomething() \
                .test_every_cited_symbol_exists_in_the_file_it_names()

    def test_a_file_that_does_not_exist_is_caught(self, monkeypatch,
                                                  tmp_path):
        fake = self._with(tmp_path, "`test_reparse.py`",
                          "`test_no_such_file_at_all.py`")
        monkeypatch.setitem(globals(), "MATRIX", fake)
        with pytest.raises(AssertionError, match="do not exist"):
            TestEveryCitationPointsAtSomething().test_every_cited_file_exists()

    def test_a_journey_the_script_does_not_run_is_caught(self, monkeypatch,
                                                         tmp_path):
        fake = self._with(tmp_path, "browser journey **A**",
                          "browser journey **Z**")
        monkeypatch.setitem(globals(), "MATRIX", fake)
        # Z is outside A-K, so the row now names no runnable journey at all.
        with pytest.raises(AssertionError):
            TestEveryBrowserClaimNamesARealJourney() \
                .test_a_row_claiming_the_browser_names_where_to_look()

    def test_a_browser_claim_with_nothing_named_is_caught(self, monkeypatch,
                                                          tmp_path):
        fake = self._with(tmp_path, "browser journey **A**", "the browser")
        monkeypatch.setitem(globals(), "MATRIX", fake)
        with pytest.raises(AssertionError, match="without naming"):
            TestEveryBrowserClaimNamesARealJourney() \
                .test_a_row_claiming_the_browser_names_where_to_look()

    def test_a_wrong_total_is_caught(self, monkeypatch, tmp_path):
        fake = self._with(tmp_path, "| PASS — browser scripted | **16** |",
                          "| PASS — browser scripted | **25** |")
        monkeypatch.setitem(globals(), "MATRIX", fake)
        with pytest.raises(AssertionError, match="the table says 25"):
            TestTheTotalsAddUp() \
                .test_the_stated_totals_are_the_counted_totals()

    def test_a_smuggled_live_claim_is_caught(self, monkeypatch, tmp_path):
        fake = self._with(tmp_path, "| DC-01 | PASS — deterministic",
                          "| DC-01 | PASS — live verified; PASS — "
                          "deterministic")
        monkeypatch.setitem(globals(), "MATRIX", fake)
        with pytest.raises(AssertionError, match="claims live verification"):
            TestEveryBrowserClaimNamesARealJourney() \
                .test_no_row_claims_live_verification()
