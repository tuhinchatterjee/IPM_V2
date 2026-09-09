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

from backend.cockpit_agentic import catalog as C
from backend.cockpit_agentic import generate as G
from backend.cockpit_agentic import ledger as L
from backend.cockpit_agentic import profile as P
from backend.cockpit_agentic import sql, store

RELEASE = "test-runtime-20q"


class Principal:
    user_id = 1
    tenant_id = G.TENANT


@pytest.fixture(scope="session")
def lake(tmp_path_factory):
    """A real published release in an isolated namespace, with a raised input
    cap so the packet fits -- which is exactly the explicitly configured mode
    docs/cockpit_agentic_v3/CONTEXT_SIZING.md describes."""
    from backend import config

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
    release = G.build_release(dataset_release_id=RELEASE, borrowers=20,
                              facilities=40)
    G.conform(release)
    store.write(release, overwrite=True)
    coverage = P.profile_release(release)
    yield {"release": release, "coverage": coverage,
           "calendar": release.calendar}
    sql.clear_sessions()
    config.settings = original


@pytest.fixture()
def runtime_factory(lake):
    """Build a Runtime over the published release, with a scripted provider."""
    from backend.cockpit_agentic.runtime import Runtime

    def make(provider, *, mode="standard", request_id="", store_=None):
        return Runtime(
            provider=provider, principal=Principal(),
            dataset_release_id=RELEASE, coverage=lake["coverage"],
            calendar=lake["calendar"], mode=mode, request_id=request_id,
            prices=L.Prices(), store=store_ or L.LedgerStore())

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
