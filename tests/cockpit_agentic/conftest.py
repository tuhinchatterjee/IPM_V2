"""Shared fixtures for the agentic-runtime tests.

Everything here uses the LABELLED MOCK provider in `fake_provider.py`. These
tests prove what is the application's responsibility -- the gate, the counters,
the context, the boundary, the stops -- and prove nothing about how a real
model behaves. Live-provider validation is BLOCKED until a credential is
configured, and is reported as such rather than implied by these passing.
"""

from __future__ import annotations

import dataclasses

import pytest

from backend.cockpit_agentic import generate as G
from backend.cockpit_agentic import ledger as L
from backend.cockpit_agentic import profile as P
from backend.cockpit_agentic import sql, store

RELEASE = "test-runtime-20q"


class Principal:
    user_id = 1
    tenant_id = G.TENANT


#: The ids these tests configure. Deliberately NOT the production ids: a test
#: that set `claude-opus-5` would pass whether or not the code reads the
#: variable, because the production default would give the same answer. These
#: are unmistakable, so a test asserting them proves the configured id reached
#: the wire.
TEST_PREPROCESS_MODEL = "test-preprocess-model-not-a-real-id"
TEST_REASONING_MODEL = "test-reasoning-model-not-a-real-id"


@pytest.fixture(autouse=True)
def cockpit_models(monkeypatch):
    """Configure the two Cockpit model roles for every test in this package.

    They fail closed now: unset means the Cockpit refuses to run. So the tests
    must configure them, exactly as a deployment must -- which is itself worth
    having, because a fixture that had to be added is a rule that is really
    enforced.
    """
    monkeypatch.setenv("AI_COCKPIT_PREPROCESS_MODEL", TEST_PREPROCESS_MODEL)
    monkeypatch.setenv("AI_COCKPIT_REASONING_MODEL", TEST_REASONING_MODEL)
    yield


@pytest.fixture(scope="package", autouse=True)
def _leave_the_lake_as_we_found_it():
    """Drop the process-wide analytical source when this package is done.

    Four fixtures here point `settings.analytics_dir` at a temporary lake and
    each restores `settings` afterwards, correctly. That is not enough:
    `backend.data_access.get_data_source()` is cached for the life of the
    PROCESS and the DuckDB source it returns remembers the root it was
    constructed with. Built once under a twenty-borrower temporary release, it
    keeps answering from there long after `settings` has been put back — and
    `settings` looking right is what made this hard to see.

    In a run of the whole repository that pointed everything downstream at the
    temporary lake. `tests/api/test_data_release_loop.py` found no published
    periods at all and thirty tests errored in setup, and the cascade from
    there is most of what a full-suite run reported as failures. Autouse and
    package-scoped, so it is set up before every fixture below and torn down
    after all of them, whatever order they finalise in.
    """
    from backend import data_access

    yield
    data_access.reset_data_source()


@pytest.fixture(scope="package")
def lake(tmp_path_factory):
    """A real published release in an isolated namespace, with a raised input
    cap so the packet fits -- which is exactly the explicitly configured mode
    docs/cockpit_agentic_v3/CONTEXT_SIZING.md describes.

    PACKAGE scope, not session. A session-scoped fixture tears down at the end
    of the whole RUN, so the `analytics_dir` override below stayed in force
    for every suite that came after this package — and the restore at the
    bottom, correct as it is, ran far too late to matter. In a run of the
    whole repository that pointed the rest of the product at a twenty-borrower
    temporary lake: `tests/api/test_data_release_loop.py` reported no
    published periods at all, and the cascade from there is most of what a
    full-suite run shows as failures. Package scope ends the override where
    the package ends, which is where it was always meant to end.
    """
    from backend import config, data_access

    base = tmp_path_factory.mktemp("runtimelake")
    original = config.settings
    # No budget overrides. The UAT configuration -- 64,000 input, 250,000
    # cumulative -- holds this domain's packet on its own, so these tests run
    # on the shipped defaults and prove they are enough.
    #
    # This fixture is session-scoped, so anything it overrode would leak into
    # every later test in the package. It did, briefly: a 400,000-token ceiling
    # set here made three ledger tests pass for the wrong reason.
    config.settings = dataclasses.replace(
        original, cockpit_agentic_v3=True, analytics_dir=base / "analytics")
    # Restoring `settings` is not enough on its own. `get_data_source()` is
    # cached for the life of the PROCESS and the DuckDB source it builds
    # remembers the `analytics_dir` it was constructed with. Build it here,
    # under a temporary lake, and every later suite in the same run reads that
    # temporary lake — which is how `tests/api/test_data_release_loop.py`
    # came to report "corporate_borrower_360 has not been built" against a
    # deployment where it plainly was. Dropped on the way in and on the way
    # out, so neither direction can leak.
    data_access.reset_data_source()
    release = G.build_release(dataset_release_id=RELEASE, borrowers=20,
                              facilities=40)
    G.conform(release)
    store.write(release, overwrite=True)
    coverage = P.profile_release(release)
    yield {"release": release, "coverage": coverage,
           "calendar": release.calendar}
    sql.clear_sessions()
    config.settings = original
    data_access.reset_data_source()


@pytest.fixture()
def runtime_factory(lake):
    """Build a Runtime over the published release, with a scripted provider."""
    from backend.cockpit_agentic.runtime import Runtime

    def make(provider, *, mode="standard", request_id="", store_=None,
             provider_error=None):
        return Runtime(
            provider=provider, principal=Principal(),
            dataset_release_id=RELEASE, coverage=lake["coverage"],
            calendar=lake["calendar"], mode=mode, request_id=request_id,
            prices=L.Prices(), store=store_ or L.LedgerStore(),
            provider_error=provider_error)

    return make


@pytest.fixture()
def sonnet_answers():
    """The two preprocessing answers, scripted. Faithful by construction here;
    what pass 1 and pass 2 actually do with a real model is not what these
    tests are about."""
    return [
        {"language": "en",
         "english_text": "How much did reported ECL change in the latest "
                         "quarter?",
         "preserved_terms": ["ECL", "latest quarter"],
         "uncertainties": []},
        {"business_question": "How much did reported ECL change in the latest "
                              "reporting quarter?",
         "subquestions": ["the change in reported ECL"],
         "requested_measures": ["ecl_reported"],
         "requested_actions": ["compare"],
         "explicit_scope": {}, "inherited_scope": {},
         "periods": [], "entity_references": [],
         "unresolved_ambiguity": []},
    ]


def scores(cockpit: int = 90, **others: int) -> list[dict]:
    """Suitability scores for all six functionalities."""
    from backend.cockpit_agentic import registry

    base = {"cockpit": cockpit, "ews": 10, "credit_scoring": 5,
            "scorecard_validation": 5, "what_if": 10, "lenses": 5}
    base.update(others)
    return [{"functionality_id": fid, "score": base[fid],
             "justification": f"scored {base[fid]}"}
            for fid in registry.FUNCTIONALITY_IDS]
