"""The readiness marker is a document, not whatever landed on stdout.

A fresh Mac ran `docker compose up --build` against a tree where every one of
these pieces worked. PostgreSQL came up. The migrations applied. The three
universes built. The API bound its port and served every route. And the stack
was unusable, because `localhost:3000` refused the connection.

The chain: the entrypoint captured `scripts/bootstrap_demo.py --json` into
`/tmp/creditprobe-bootstrap.json`; the builders that script calls narrate what
they are doing with the bare `print` builtin — "> Building the corporate
universe", "16 quarter(s)", "> Deriving the graph" — onto the same stdout; the
marker therefore began with prose; the container health check's `json.loads`
raised "Expecting value: line 1 column 1"; the backend stayed on
`health: starting` for ever; and the frontend, which declares
`condition: service_healthy` on it, never started at all.

Two guarantees close it, and this suite holds both to the fire:

  1. Under `--json`, narration is redirected to stderr, so stdout carries the
     JSON document and nothing else.
  2. Under `--marker PATH`, the verdict is written to a file directly from the
     structured result. It never travels through a stream, so nothing printed
     by anything can corrupt it. This is what the entrypoint uses.

Each guarantee is paired with the failure it prevents: a marker full of prose
must still be refused by the health check, and a marker that says NOT ready
must still be refused. "We could not read the verdict" and "the verdict is
yes" are different answers, and the whole defect was conflating them.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from backend.bootstrap import plan as plan_mod
from backend.bootstrap import readiness as readiness_mod

ROOT = Path(__file__).resolve().parents[2]

#: Verbatim from the failed Mac run. If narration can reach a machine-readable
#: channel, these are the bytes that get there first.
NARRATION = (
    "> Building the corporate universe",
    "  16 quarter(s) in 41.2s",
    "> Deriving the graph for 16 quarter(s)",
)


def _script():
    """`scripts/bootstrap_demo.py`, imported as a module.

    It lives outside any package — it is a command, run by the entrypoint —
    so it is loaded by path rather than imported by name.
    """
    path = ROOT / "scripts" / "bootstrap_demo.py"
    spec = importlib.util.spec_from_file_location("bootstrap_demo_under_test",
                                                  path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _passing_result() -> plan_mod.Result:
    report = readiness_mod.Report(checks=[
        readiness_mod.Check(key="lake", title="Core portfolio datasets exist",
                            status=readiness_mod.OK, detail="All present."),
    ])
    return plan_mod.Result(outcomes=[], report=report, seconds=1.0)


def _failing_result() -> plan_mod.Result:
    report = readiness_mod.Report(checks=[
        readiness_mod.Check(key="corporate",
                            title="Corporate Borrower 360 datasets exist",
                            status=readiness_mod.MISSING,
                            detail="0 of 13 dataset(s) present.",
                            remedy="python scripts/bootstrap_demo.py"),
    ])
    return plan_mod.Result(outcomes=[], report=report, seconds=1.0)


@pytest.fixture
def noisy_bootstrap(monkeypatch):
    """A bootstrap that narrates to stdout, exactly as the real builders do.

    Returns a setter so a test can choose the verdict it produces.
    """
    module = _script()

    def install(result: plan_mod.Result):
        def run(**_kwargs):
            for line in NARRATION:
                print(line)
            return result

        monkeypatch.setattr(module.bootstrap, "run", run)
        return module

    return install


# --------------------------------------------------------------- guarantee 1


class TestStdoutCarriesTheDocumentAndNothingElse:

    def test_narration_cannot_reach_the_json_on_stdout(
            self, noisy_bootstrap, capsys):
        """The original failure, reproduced and refused.

        Without the redirect this parse raises
        `json.decoder.JSONDecodeError: Expecting value: line 1 column 1`,
        which is the message the Mac health check reported.
        """
        module = noisy_bootstrap(_passing_result())

        assert module.main(["--json"]) == module.EXIT_OK

        captured = capsys.readouterr()
        body = json.loads(captured.out)  # the assertion is that this works
        assert body["ok"] is True
        for line in NARRATION:
            assert line not in captured.out
            assert line in captured.err, "progress must still be visible"

    def test_the_document_is_the_whole_of_stdout(self, noisy_bootstrap, capsys):
        """Not merely parseable — nothing precedes or follows it."""
        module = noisy_bootstrap(_passing_result())
        module.main(["--json"])
        out = capsys.readouterr().out
        assert out.lstrip().startswith("{")
        assert out.rstrip().endswith("}")

    def test_without_json_the_human_summary_is_unchanged(self, capsys):
        """The counter-test: the redirect must not silence the ordinary run.

        A developer typing the command with no flags is not asking for a
        machine document and must still see what happened.
        """
        module = _script()
        module.main(["--list"])
        assert "corporate" in capsys.readouterr().out


# --------------------------------------------------------------- guarantee 2


class TestTheMarkerIsWrittenFromTheResult:

    def test_the_marker_parses_and_says_ready(self, noisy_bootstrap, tmp_path):
        marker = tmp_path / "creditprobe-bootstrap.json"
        module = noisy_bootstrap(_passing_result())

        assert module.main(["--marker", str(marker)]) == module.EXIT_OK

        body = json.loads(marker.read_text(encoding="utf-8"))
        assert body["ok"] is True
        assert body["readiness"]["ready"] is True
        assert body["sentence"]

    def test_narration_never_reaches_the_file(self, noisy_bootstrap, tmp_path):
        marker = tmp_path / "marker.json"
        module = noisy_bootstrap(_passing_result())
        module.main(["--marker", str(marker)])
        text = marker.read_text(encoding="utf-8")
        for line in NARRATION:
            assert line not in text

    def test_a_failed_bootstrap_writes_a_marker_that_says_so(
            self, noisy_bootstrap, tmp_path):
        """Not ready is a verdict, not an absent file.

        The entrypoint starts the API even when the bootstrap fails, so that
        the failure can be inspected. The marker is what stops that container
        also reporting itself healthy.
        """
        marker = tmp_path / "marker.json"
        module = noisy_bootstrap(_failing_result())

        assert module.main(["--marker", str(marker)]) == module.EXIT_NOT_READY

        body = json.loads(marker.read_text(encoding="utf-8"))
        assert body["ok"] is False
        assert "Corporate" in json.dumps(body)

    def test_check_mode_writes_a_marker_the_health_check_understands(
            self, tmp_path, monkeypatch):
        """`run()` reports `ok`; `verify()` reports `ready`.

        The marker always carries `ok`, so the health check never has to know
        which of the two wrote it.
        """
        module = _script()
        marker = tmp_path / "marker.json"
        monkeypatch.setattr(module.bootstrap, "verify",
                            lambda *_a, **_k: _passing_result().report)
        module.main(["--check", "--marker", str(marker)])
        body = json.loads(marker.read_text(encoding="utf-8"))
        assert body["ok"] is True
        assert body["ready"] is True

    def test_the_write_leaves_no_partial_file_behind(
            self, noisy_bootstrap, tmp_path):
        """Written to a temporary name and renamed into place.

        The health check reads this file on a ten-second timer while the
        bootstrap is still running. A reader arriving mid-write must find
        either the old document or the new one, never half of one — which
        would fail to parse, which is the same defect by another route.
        """
        marker = tmp_path / "marker.json"
        module = noisy_bootstrap(_passing_result())
        module.main(["--marker", str(marker)])
        assert sorted(p.name for p in tmp_path.iterdir()) == ["marker.json"]

    def test_a_missing_parent_directory_is_created(
            self, noisy_bootstrap, tmp_path):
        marker = tmp_path / "nested" / "deeper" / "marker.json"
        module = noisy_bootstrap(_passing_result())
        module.main(["--marker", str(marker)])
        assert json.loads(marker.read_text(encoding="utf-8"))["ok"] is True


# ------------------------------------------------------- the health check


def _healthcheck(marker: Path, monkeypatch):
    monkeypatch.setenv("CREDITPROBE_READY_MARKER", str(marker))
    path = ROOT / "docker" / "healthcheck.py"
    spec = importlib.util.spec_from_file_location("ipm_healthcheck_under_test",
                                                  path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TestTheHealthCheckAgreesWithTheMarker:

    def test_a_marker_this_script_wrote_is_accepted(
            self, noisy_bootstrap, tmp_path, monkeypatch):
        marker = tmp_path / "marker.json"
        noisy_bootstrap(_passing_result()).main(["--marker", str(marker)])

        ready, why = _healthcheck(marker, monkeypatch).demonstration_ready()

        assert ready is True, why

    def test_the_original_corrupt_marker_is_still_refused(
            self, tmp_path, monkeypatch):
        """The bytes the Mac actually had in that file.

        This is the counter-test the fix must not remove: if narration ever
        reaches the marker again by some route nobody anticipated, the health
        check must go on saying NOT ready rather than shrugging and passing.
        """
        marker = tmp_path / "marker.json"
        marker.write_text("\n".join(NARRATION) + '\n{"ok": true}\n',
                          encoding="utf-8")

        ready, why = _healthcheck(marker, monkeypatch).demonstration_ready()

        assert ready is False
        assert "could not be read" in why

    def test_a_missing_marker_is_not_a_pass(self, tmp_path, monkeypatch):
        marker = tmp_path / "never-written.json"
        ready, why = _healthcheck(marker, monkeypatch).demonstration_ready()
        assert ready is False
        assert "has not finished" in why

    def test_a_failed_verdict_is_not_a_pass(
            self, noisy_bootstrap, tmp_path, monkeypatch):
        marker = tmp_path / "marker.json"
        noisy_bootstrap(_failing_result()).main(["--marker", str(marker)])

        ready, why = _healthcheck(marker, monkeypatch).demonstration_ready()

        assert ready is False
        assert why


# ----------------------------------------------------- the compose contract


def _compose() -> dict:
    yaml = pytest.importorskip("yaml")
    return yaml.safe_load((ROOT / "docker-compose.yml").read_text("utf-8"))


class TestComposeLetsTheFrontendStart:
    """The health verdict only matters because the frontend waits on it.

    These assertions are the other half of the Mac failure: the marker being
    unparseable mattered because `frontend` declares
    `condition: service_healthy` on `backend`. If that dependency were ever
    loosened the symptom would vanish and the defect would not — the frontend
    would start against an empty product instead.
    """

    def test_the_frontend_waits_for_backend_health(self):
        compose = _compose()
        depends = compose["services"]["frontend"]["depends_on"]
        assert depends["backend"]["condition"] == "service_healthy"

    def test_the_backend_health_check_is_the_readiness_one(self):
        compose = _compose()
        test = compose["services"]["backend"]["healthcheck"]["test"]
        assert any("healthcheck" in str(part) for part in test), test

    def test_the_first_start_is_given_time_to_build(self):
        """A first start generates three universes; a measured run took 319s."""
        compose = _compose()
        health = compose["services"]["backend"]["healthcheck"]
        assert health["start_period"] == "480s"


# ------------------------------------------------------------- idempotence


class TestRunningItTwiceChangesNothing:

    def test_the_entrypoint_removes_a_stale_marker_before_it_starts(self):
        """A restart must not inherit the previous start's verdict.

        Without this a container that was healthy, then had its data volume
        emptied, comes back reporting the OLD pass while serving nothing.
        """
        script = (ROOT / "docker" / "backend-entrypoint.sh").read_text("utf-8")
        assert 'rm -f "${READY_MARKER}"' in script

    def test_the_entrypoint_writes_the_marker_by_path_not_by_capture(self):
        """The one line whose absence caused all of it."""
        script = (ROOT / "docker" / "backend-entrypoint.sh").read_text("utf-8")
        assert '--marker "${READY_MARKER}"' in script
        assert '--json > "${READY_MARKER}"' not in script

    def test_a_second_run_over_the_same_marker_replaces_it(
            self, noisy_bootstrap, tmp_path):
        marker = tmp_path / "marker.json"
        noisy_bootstrap(_failing_result()).main(["--marker", str(marker)])
        assert json.loads(marker.read_text("utf-8"))["ok"] is False

        noisy_bootstrap(_passing_result()).main(["--marker", str(marker)])
        assert json.loads(marker.read_text("utf-8"))["ok"] is True


@pytest.mark.skipif(
    not (ROOT / "data").exists(),
    reason="no analytical data in this environment")
class TestAgainstTheRealDeployment:
    """The same guarantees, through the real bootstrap rather than a fake.

    `--check` rather than a full run: this asserts the stream contract and the
    marker contract, and generating three universes to do it would make a
    suite nobody runs — which is how the original gap survived.
    """

    def test_the_real_check_produces_a_parseable_marker(self, tmp_path):
        module = _script()
        marker = tmp_path / "marker.json"
        module.main(["--check", "--marker", str(marker), "--quiet"])
        body = json.loads(marker.read_text(encoding="utf-8"))
        assert "ok" in body
        assert isinstance(body.get("checks"), list)

    def test_the_real_json_run_writes_only_a_document(self, capsys):
        module = _script()
        module.main(["--check", "--json", "--quiet"])
        json.loads(capsys.readouterr().out)


# ============================================ every step agrees with the gate
#
# A second bootstrap defect, of the same shape as the marker one and found the
# same way: two pieces of code disagreeing about what "done" means, with the
# disagreement invisible until a real deployment lands in the gap between them.


class TestAStepIsNeededWheneverItsGateWouldFail:
    """The step's precondition and the readiness check must be one question.

    `_review_needed` used to ask "did a review COMPLETE?" while the gate asked
    "did a review complete AND leave Risk Cases?". A database whose run row
    survived while its cases did not was therefore simultaneously "already in
    place" and "not ready" - and `bootstrap_demo.py --step review` reported
    success having fixed nothing, which is worse than either failing or
    working.

    Asserted structurally, over every step that has a gate, rather than for
    the one step where it was found.
    """

    def test_the_review_step_asks_the_gate_and_not_a_weaker_question(self):
        from tests.conftest import database_available

        if not database_available():
            pytest.skip("PostgreSQL is not reachable")

        from backend.bootstrap import plan, readiness
        from backend.db.engine import get_session

        with get_session() as session:
            gate = readiness._review(session)
        # The step wants to run exactly when the gate would not pass. Whatever
        # state this database is in, the two must agree about it.
        assert plan._review_needed() is (not gate.ok)

    def test_a_completed_run_with_no_cases_still_needs_the_step(self,
                                                                monkeypatch):
        """The exact state the defect hid in, constructed.

        A review that ran to completion and left nothing is indistinguishable
        from a healthy quiet book if you only ask whether it ran - and on the
        bundled book it is not quiet, it is broken.
        """
        from backend.bootstrap import plan, readiness

        class Ran:
            reviewed = True

        monkeypatch.setattr(readiness, "_review_ran", lambda _s: True)
        monkeypatch.setattr(
            readiness, "_risk_case_count", lambda _s: 0, raising=False)
        gate = readiness.Check(
            key="portfolio_review", title="t", status=readiness.MISSING,
            detail="ran, left nothing", remedy="r", data={"risk_cases": 0})
        monkeypatch.setattr(readiness, "_review", lambda _s: gate)
        monkeypatch.setattr(plan, "_session", _fake_session)
        assert Ran.reviewed is True
        assert plan._review_needed() is True


class _FakeSession:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _fake_session():
    return _FakeSession()
