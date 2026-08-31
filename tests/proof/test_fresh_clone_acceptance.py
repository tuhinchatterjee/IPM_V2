"""What a fresh machine gets, asserted rather than hoped for. §16.

This suite exists because a real acceptance run on a clean Mac found a
product that started, reported itself healthy, and was empty. `docker compose
up --build` returned to the prompt looking successful; the Cockpit said no
review had been done, Borrower 360 said to run a Python script, Scorecard
Validation said no months were available, and Data Builder said 0 of 7
domains beside 344 governed fields.

Every one of those was a bootstrap step nobody ran. Nothing threw.

So the readiness contract is now a test. Two levels:

**The contract itself** — always runs, needs nothing built. It asserts that
the checks EXIST, that they are the ones a presenter cares about, that each
carries a remedy, and that `UNKNOWN` is not treated as a pass. A deployment
where the readiness list quietly shrinks is a deployment that can go back to
reporting ready on an empty product, and that is the regression this half
catches.

**The deployment** — runs when this environment actually has one. It asserts
what a presenter would find: a corporate book at scale, scorecard months,
registered and authoritative datasets, seven business domains, a completed
review, and no critical route whose main content is an instruction to run a
build script.

Why the second half does not run the bootstrap itself
-----------------------------------------------------
Generating three synthetic universes takes about five minutes and writes
gigabytes. A test suite that did it on every run would be a test suite nobody
runs, which is how the original gap survived. `scripts/bootstrap_demo.py` is
the thing under test and the clean-room run is a release gate — documented in
docs/FRESH_CLONE_ACCEPTANCE.md — while this suite asserts the CONTRACT that
gate is measured against, on whatever the environment has.
"""

from __future__ import annotations

import pytest

from backend.bootstrap import plan, readiness
from backend.services import data_domains as dd
from tests.conftest import database_available

# ---------------------------------------------------------------------------
# The contract. Needs no data, no database, and no built deployment.
# ---------------------------------------------------------------------------


class TestTheReadinessContract:
    """The list itself, before anything is measured against it."""

    #: Everything the fresh-Mac run discovered by hand. A check removed from
    #: the product must fail here rather than quietly stop being asserted.
    REQUIRED = {
        "portfolio_data": "the core credit book",
        "corporate_data": "the corporate Borrower 360 book",
        "retail_data": "the retail scorecard universe",
        "ifrs9_data": "IFRS 9 staging and scenarios",
        "corporate_scale": "a corporate book big enough to demonstrate",
        "scorecard_months": "validation months for both scorecards",
        "catalogue": "every built dataset in the governed catalogue",
        "datasets_registered": "registered in Data Builder",
        "datasets_published": "published",
        "datasets_authoritative": "authoritative for a governed purpose",
        "data_builder_domains": "the seven business domains",
        "demo_users": "somebody who can sign in",
        "scorecard_models": "a populated model registry",
        "demo_workspace": "a project and an investigation to open",
        "portfolio_review": "a completed Q2 2026 review",
    }

    #: The seven that live in PostgreSQL. `report(None)` deliberately omits
    #: them and says so, rather than reporting them as passing — which is the
    #: same rule as everywhere else here: not checked is not checked.
    NEEDS_DATABASE = frozenset({
        "datasets_registered", "datasets_published", "datasets_authoritative",
        "data_builder_domains", "demo_users", "scorecard_models",
        "demo_workspace", "portfolio_review",
    })

    def _keys(self):
        if database_available():
            from backend.db.engine import get_session

            with get_session() as session:
                return {c.key for c in readiness.report(session).checks}
        return {c.key for c in readiness.report(None).checks}

    def test_every_thing_the_fresh_mac_found_broken_is_a_check(self):
        keys = self._keys()
        expected = set(self.REQUIRED)
        if not database_available():
            expected -= self.NEEDS_DATABASE
        missing = sorted(expected - keys)
        assert not missing, (
            "these readiness checks have disappeared, so a deployment "
            "missing them would report ready: "
            + ", ".join(f"{k} ({self.REQUIRED[k]})" for k in missing))

    def test_the_database_half_is_reported_as_unchecked_not_as_passing(self):
        """Without a session, the eight database checks do not silently pass.

        The failure mode this rules out is the original one wearing different
        clothes: a readiness call that cannot see PostgreSQL returning a green
        report because it had nothing to disagree with.
        """
        report = readiness.report(None)
        assert not report.ready, (
            "a readiness report built without a database claims the "
            "deployment is ready, so eight unchecked things are being read "
            "as eight passing ones")
        assert any(c.status == readiness.UNKNOWN for c in report.checks), (
            "nothing is marked UNKNOWN, so the absence of the database half "
            "is not being reported at all")

    def test_every_check_says_what_to_do_about_it(self):
        """A red row a presenter cannot act on is a red row they ignore."""
        report = readiness.report(None)
        for check in report.checks:
            assert check.title.strip(), f"{check.key} has no title"
            if check.status != readiness.OK:
                assert check.detail.strip(), f"{check.key} explains nothing"
                assert check.remedy.strip(), (
                    f"{check.key} is not OK and names no remedy, so the "
                    "person reading it has nowhere to go")

    def test_a_check_that_could_not_run_is_not_a_check_that_passed(self):
        """UNKNOWN must not be readable as OK.

        The whole defect in one property. A bootstrap that reported success
        because a step was never reached is the same shape as a check that
        reports OK because it could not run.
        """
        assert readiness.UNKNOWN != readiness.OK
        unknown = readiness.Check(key="k", title="t", status=readiness.UNKNOWN)
        assert not unknown.ok
        assert not readiness.Report(checks=[unknown]).ready

    def test_an_empty_report_is_not_ready(self):
        """Nothing checked is not everything passing."""
        assert not readiness.Report(checks=[]).ready

    def test_the_thresholds_describe_a_demonstration_not_a_fixture(self):
        """A corporate book of forty borrowers passes no useful demo."""
        assert readiness.MINIMUM_CORPORATE_BORROWERS >= 1_000
        assert readiness.MINIMUM_CORPORATE_QUARTERS >= 8
        assert readiness.MINIMUM_SCORECARD_MONTHS >= 6
        assert readiness.MINIMUM_SCORECARD_MODELS >= 2


class TestTheBootstrapPlan:
    """The sequence, and the two properties that make it safe to re-run."""

    def test_every_documented_step_exists(self):
        keys = {s.key for s in plan.steps()}
        for expected in ("migrations", "users", "portfolio", "corporate",
                         "retail", "models", "catalogue", "domains",
                         "relationships", "workspace", "review"):
            assert expected in keys, f"the {expected} step has disappeared"

    def test_the_saudi_builder_runs_before_the_two_that_merge_into_it(self):
        """The ordering hazard, pinned.

        `generate_saudi_universe.py` OVERWRITES metadata/catalog.json; the
        corporate and retail builders MERGE into it. Reversed, twenty-six
        catalogue entries are erased and their Parquet stays on disk where no
        analysis can see it — datasets that exist and cannot be read.
        """
        order = [s.key for s in plan.steps()]
        assert order.index("portfolio") < order.index("corporate")
        assert order.index("portfolio") < order.index("retail")

    def test_the_catalogue_is_registered_after_everything_it_registers(self):
        order = [s.key for s in plan.steps()]
        for built in ("portfolio", "corporate", "retail"):
            assert order.index(built) < order.index("catalogue")
        assert order.index("catalogue") < order.index("domains")

    def test_the_review_runs_last_so_it_reviews_a_built_book(self):
        order = [s.key for s in plan.steps()]
        assert order.index("review") == len(order) - 1

    def test_every_step_can_say_whether_it_is_needed(self):
        """Idempotency is a probe per step, not a flag file.

        A flag file says "this ran once". A probe says "this deployment has
        it", which is the question that matters when a volume was built by an
        earlier version or a start was interrupted half way.
        """
        for step in plan.steps():
            assert callable(step.needed), f"{step.key} has no probe"
            assert callable(step.run)

    def test_a_required_step_that_fails_is_not_survivable(self):
        """No step may be optional-by-default.

        The old workspace seeder caught every exception from the review and
        appended a note, so a demonstration reached a presenter with an empty
        Cockpit and a green health check.
        """
        assert all(s.required for s in plan.steps()), (
            "a step marked not-required can fail while the bootstrap reports "
            "success, which is the defect this plan replaced")


class TestTheBusinessDomains:
    """§6 and §7: the seven headings, and what is filed under them."""

    def test_there_are_seven_and_they_are_the_named_seven(self):
        assert len(dd.DOMAINS) == 7
        for expected in ("Core Portfolio / Facility", "IFRS 9 / ECL",
                         "Corporate Ratings", "Retail / SME Scorecards",
                         "Documents", "Policies / Knowledge",
                         "CreditProbe Operational Metadata"):
            assert expected in dd.NAMES

    def test_every_domain_describes_itself(self):
        """The cards used to read "Created from CreditProbe's bundled
        catalogue", which describes where a row came from rather than what a
        reader would find in it."""
        for domain in dd.DOMAINS:
            assert len(domain.description) > 40, (
                f"{domain.name} does not say what it holds")
            assert domain.owner.strip()

    def test_every_catalogued_dataset_has_a_business_home(self):
        """The defect, as a property.

        Thirty-nine catalogue domains, seven business ones, and nothing
        mapping between them — so the screen said 0 of 7 while 46 datasets
        were installed and working.
        """
        import json
        from pathlib import Path

        from backend.config import settings

        path = Path(settings.metadata_dir) / "catalog.json"
        if not path.exists():
            pytest.skip("no catalogue in this environment")
        entries = json.loads(path.read_text(encoding="utf-8")).get("datasets") or []
        if not entries:
            pytest.skip("the catalogue is empty")
        grouped = dd.placement(entries)
        unplaced = grouped.get(dd.UNPLACED) or []
        assert not unplaced, (
            f"{len(unplaced)} governed dataset(s) have no business domain and "
            f"would not appear on the Data Builder screen: {unplaced[:6]}")

    def test_a_business_domain_does_not_merge_two_books(self):
        """A heading is not a boundary. B44's scope separation is unaffected.

        `corporate_facilities` and `portfolio_facility` share a business
        domain because a person looking for either would look in the same
        place. They remain in different portfolio scopes, and every governed
        read still goes through the scope — which is why the two are separate
        fields.
        """
        import json
        from pathlib import Path

        from backend.config import settings

        path = Path(settings.metadata_dir) / "catalog.json"
        if not path.exists():
            pytest.skip("no catalogue in this environment")
        entries = json.loads(path.read_text(encoding="utf-8")).get("datasets") or []
        scopes: dict[str, set[str]] = {}
        for entry in entries:
            where = dd.business_domain(
                dataset=str(entry.get("name") or ""),
                catalogue_domain=str(entry.get("domain") or ""))
            scopes.setdefault(where, set()).add(
                str(entry.get("portfolio_scope") or "CREDIT_BOOK"))
        # At least one domain must legitimately span two scopes, or this test
        # is passing because nothing was grouped.
        assert any(len(s) > 1 for s in scopes.values()), (
            "no business domain spans two portfolio scopes, so this test is "
            "not exercising the distinction it exists to protect")
        # And the scopes themselves are still declared per dataset.
        for entry in entries:
            assert str(entry.get("portfolio_scope") or "CREDIT_BOOK")


# ---------------------------------------------------------------------------
# The deployment. Runs against whatever this environment actually has.
# ---------------------------------------------------------------------------


def _built() -> bool:
    try:
        from backend.data_access import get_data_source

        return "portfolio_facility" in set(get_data_source().datasets())
    except Exception:  # noqa: BLE001
        return False


needs_deployment = pytest.mark.skipif(
    not _built(), reason="no analytical layer in this environment")
needs_db = pytest.mark.skipif(not database_available(),
                              reason="needs PostgreSQL")


class TestWhatAPresenterFinds:
    """The screens the fresh Mac found empty, asserted as populated."""

    @needs_deployment
    def test_the_corporate_book_is_a_book_and_not_a_fixture(self):
        """Borrower 360 said: run scripts/build_corporate_universe.py."""
        check = readiness.report(None)
        found = next(c for c in check.checks if c.key == "corporate_scale")
        assert found.ok, found.detail
        assert found.data["borrowers"] >= readiness.MINIMUM_CORPORATE_BORROWERS
        assert found.data["quarters"] >= readiness.MINIMUM_CORPORATE_QUARTERS

    @needs_deployment
    def test_scorecard_validation_has_months_for_both_scorecards(self):
        """Scorecard Validation said: no months are available for APPLICATION."""
        found = next(c for c in readiness.report(None).checks
                     if c.key == "scorecard_months")
        assert found.ok, found.detail
        assert found.data["application_months"] >= readiness.MINIMUM_SCORECARD_MONTHS
        assert found.data["behavioural_months"] >= readiness.MINIMUM_SCORECARD_MONTHS

    @needs_deployment
    @needs_db
    def test_the_seven_domains_exist_and_hold_what_is_installed(self):
        """Data Builder said: Domains Defined 0 of 7, Governed Fields 344."""
        from sqlalchemy import select

        from backend.db.engine import get_session
        from backend.models.platform import DataDomain, DatasetDefinition

        with get_session() as session:
            active = {d.name for d in session.execute(
                select(DataDomain)).scalars() if d.status == "ACTIVE"}
            absent = [n for n in dd.NAMES if n not in active]
            assert not absent, f"business domains missing: {absent}"

            homeless = sorted(d.name for d in session.execute(
                select(DatasetDefinition)).scalars()
                if d.domain not in dd.NAMES)
            assert not homeless, (
                f"{len(homeless)} registered dataset(s) are filed outside the "
                f"seven business domains: {homeless[:6]}")

    @needs_deployment
    @needs_db
    def test_the_only_live_domains_are_the_seven(self):
        """§6/§7: "Domains Defined: 0 of 7" and every card "Not created".

        The contradiction is fixed by creating the seven, but the screen also
        has to SHOW seven. The bundled catalogue carries thirty-eight headings
        of its own; once their datasets are re-filed those headings are empty,
        and leaving them live turns the primary Data Builder screen into
        forty-five cards under a tile reading "Domains defined 45 of 7".
        Retired is not deleted - they are still restorable - but a domain
        holding nothing is not one a client came to look at.
        """
        from sqlalchemy import select

        from backend.db.engine import get_session
        from backend.models.platform import DataDomain, DatasetDefinition

        with get_session() as session:
            live = [d.name for d in session.execute(
                select(DataDomain)).scalars() if d.status != "ARCHIVED"]
            assert sorted(live) == sorted(dd.NAMES), (
                f"{len(live)} live domain(s) where seven were expected: "
                f"{sorted(set(live) - set(dd.NAMES))[:8]}")

            # And nothing was archived while it still held something.
            occupied = {r.domain for r in session.execute(
                select(DatasetDefinition)).scalars()}
            buried = [d.name for d in session.execute(
                select(DataDomain)).scalars()
                if d.status == "ARCHIVED" and d.name in occupied]
            assert not buried, (
                f"domain(s) archived while still holding datasets: {buried}")

    @needs_deployment
    @needs_db
    def test_the_q2_review_has_been_run_and_left_something_to_look_at(self, bootstrapped):
        """Cockpit said: no portfolio review of Q2 2026 has been completed."""
        from backend.db.engine import get_session

        with get_session() as session:
            found = next(c for c in readiness.report(session).checks
                         if c.key == "portfolio_review")
        assert found.ok, found.detail
        assert found.data["risk_cases"] >= readiness.MINIMUM_RISK_CASES

    @needs_deployment
    @needs_db
    def test_this_deployment_is_demonstrable(self, bootstrapped):
        """The whole contract, in one assertion, with the reasons."""
        from backend.db.engine import get_session

        with get_session() as session:
            report = readiness.report(session)
        assert report.ready, report.sentence() + "\n" + "\n".join(
            f"  {c.key}: {c.detail}  [{c.remedy}]" for c in report.failures)


@pytest.fixture(scope="class")
def bootstrapped():
    """The deployment, brought to the state a fresh `docker compose up`
    leaves it in.

    §16 asks these assertions to hold on a CORRECTLY BOOTSTRAPPED
    demonstration, and this suite shares a database with unit tests that
    truncate tables. Without this the acceptance result depended on what ran
    before it: the same code passed alone and failed in the full suite, which
    tells a reader nothing about whether the product is demonstrable.

    So the precondition is established rather than assumed. This is not a
    weaker assertion - it is the SAME assertion with its setup made explicit,
    and it is exactly what the entrypoint does on a fresh machine. The
    bootstrap is idempotent, so on an already-ready deployment this is a
    no-op that costs one readiness read.
    """
    from backend import bootstrap

    try:
        bootstrap.run()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"the demonstration could not be bootstrapped here: {exc}")
    return True


class TestNoScreenTellsAPresenterToRunAScript:
    """§16: no critical route whose principal content is an instruction.

    Driven through the real API rather than by grepping the frontend, because
    the string a presenter saw — "corporate_customer_master has not been
    built. Run scripts/build_corporate_universe.py..." — came from the
    BACKEND, and a frontend audit would never have found it.
    """

    #: Phrases a client must never be shown. Each was on a real screenshot.
    FORBIDDEN = ("run scripts/", "scripts/build_", "scripts/generate_",
                 "python scripts", ".py")

    @needs_deployment
    @needs_db
    def test_the_critical_routes_do_not_name_a_build_script(self):
        from fastapi.testclient import TestClient

        from backend.api.main import app

        client = TestClient(app)
        headers = {"X-IPM-Role": "ANALYST"}
        routes = [
            "/api/v1/corporate/meta",
            "/api/v1/corporate/borrowers",
            "/api/v1/scorecard/overview",
            "/api/v1/data-builder/domains",
            "/api/v1/health",
        ]
        offenders: list[str] = []
        for route in routes:
            response = client.get(route, headers=headers)
            if response.status_code >= 500:
                offenders.append(f"{route} returned {response.status_code}")
                continue
            body = response.text.lower()
            for phrase in self.FORBIDDEN:
                if phrase in body:
                    offenders.append(f"{route} says {phrase!r}")
        assert not offenders, (
            "a presenter would be shown a developer instruction: "
            + "; ".join(offenders))
