"""I10 / M16: telemetry does not change what the engine sends or does.

The same deterministic fixture conversation is run twice through the frozen
Worker: once with the bare provider and once wrapped by the lab observer.
The provider-visible requests, the frozen event sequence, the tool order and
the final answer must be identical (after normalising the random ids the
engine mints per run). Overhead is measured and reported, not asserted to
be zero.
"""

from __future__ import annotations

import json
import re
import tempfile
import time
from pathlib import Path
from typing import Any

from conftest import QUESTION

_IDS = re.compile(r"\b([a-z]{2,4})-[0-9a-f]{8,32}\b")


class Recorder:
    """Records exactly what the engine hands the provider."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.sent: list[dict[str, Any]] = []

    def converse(self, **kw: Any) -> Any:
        self.sent.append(json.loads(json.dumps(kw, default=str)))
        return self.inner.converse(**kw)


#: The engine tells the model how much time is left on every turn. Those are
#: CLOCK READINGS, different on any two runs with or without the observer,
#: so they are normalised -- and only they.
_CLOCK = re.compile(r'(\\"[a-z_]*_(?:seconds|ms)\\": )[0-9.]+')


def _norm(obj: Any) -> str:
    text = _IDS.sub(lambda m: f"{m.group(1)}-X",
                    json.dumps(obj, sort_keys=True))
    return _CLOCK.sub(lambda m: m.group(1) + "T", text)


def _drive(provider: Any) -> tuple[Any, Any, float]:
    from backend.cockpit_v4 import domain_resolver as resolver
    from backend.cockpit_v4.run_store import RunStore
    from backend.cockpit_v4.worker import Worker
    from backend.model_lab.child_runtime import runtime_for
    from backend.model_lab.registry import load_profiles

    tmp = Path(tempfile.mkdtemp())
    prof = load_profiles()["fixture-repair"]
    rt = runtime_for(prof, provider, domain="corporate", runtime_dir=tmp,
                     state_db=tmp / "s.sqlite3")
    store = RunStore(tmp / "s.sqlite3")
    scope = resolver.scope_for("corporate")
    th = store.create_thread(tenant_id="demo-tenant", principal_id="u")
    rec, _ = store.accept_run(
        thread_id=th, tenant_id="demo-tenant", principal_id="u",
        question=QUESTION, mode="standard", release_id=scope.release_id,
        domain_id="corporate", release_fingerprint=scope.release_fingerprint,
        ui_filters={}, idempotency_key="", body_digest="", startup_sha="t",
        deadline_at="")
    t = time.perf_counter()
    out = Worker(store=store, runtime=rt).execute(rec)
    return out, (store, rec.run_id), time.perf_counter() - t


def test_I10_observer_is_neutral_and_its_overhead_is_measured():
    from backend.model_lab.adapters.fixture import FixtureProvider
    from backend.model_lab.observe import observe

    bare = Recorder(FixtureProvider("repair", "lab/fixture-repair"))
    out1, (s1, r1), t1 = _drive(bare)
    spans: list[dict] = []
    inner = Recorder(FixtureProvider("repair", "lab/fixture-repair"))
    out2, (s2, r2), t2 = _drive(observe(inner, spans.append))

    assert out1.state == out2.state == "COMPLETED"
    assert len(bare.sent) == len(inner.sent) == len(spans)
    for a, b in zip(bare.sent, inner.sent, strict=True):
        assert _norm(a) == _norm(b), "the observer changed a request"
    ev1 = [(e.event_type, e.operation, e.status) for e in s1.events_since(r1)]
    ev2 = [(e.event_type, e.operation, e.status) for e in s2.events_since(r2)]
    assert ev1 == ev2, "dispatch order / events differ with telemetry on"
    f1, f2 = s1.get_run(r1).final_response, s2.get_run(r2).final_response
    assert _norm(f1["narrative"]) == _norm(f2["narrative"])
    assert f1["disposition"] == f2["disposition"]
    assert s1.get_run(r1).budget.get("generations") == \
        s2.get_run(r2).budget.get("generations")
    # Overhead is DISCLOSED, not hidden: record it for the ledger.
    print(f"observer overhead: bare {t1*1000:.1f} ms, observed "
          f"{t2*1000:.1f} ms (one run each; timing noise dominates)")


def test_observer_does_not_invent_count_tokens():
    from backend.model_lab.observe import observe

    class NoCount:
        def converse(self, **kw):
            return None

    class WithCount(NoCount):
        def count_tokens(self, **kw):
            return 7

    assert not callable(getattr(observe(NoCount(), lambda r: None),
                                "count_tokens", None))
    assert observe(WithCount(), lambda r: None).count_tokens() == 7


def test_observer_never_gates_the_run_when_telemetry_fails():
    from backend.model_lab.adapters.fixture import FixtureProvider
    from backend.model_lab.observe import observe

    def broken_sink(_):
        raise RuntimeError("telemetry store down")

    out, _, _ = _drive(observe(FixtureProvider("reference", "x"),
                               broken_sink))
    assert out.state == "COMPLETED"
