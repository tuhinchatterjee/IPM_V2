"""ASSISTED_V1: exact packet in, nothing for the baseline, engine neutral.

Offline. A recording fixture provider captures exactly what each child's
provider receives; the frozen engine, executor and oracle are compared
between the two lanes. No model is called.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from conftest import child, make_service, run
from test_observer_neutrality import _norm

from backend.model_lab import assistance, model_io, registry
from backend.model_lab import benchmark_questions as bq
from backend.model_lab.adapters import build_provider

Q = bq.get("Q01")


class Capture:
    def __init__(self, inner: Any, sink: list) -> None:
        self.inner, self.sink = inner, sink

    def converse(self, **kw: Any) -> Any:
        self.sink.append(json.loads(json.dumps(kw, default=str)))
        return self.inner.converse(**kw)


@pytest.fixture(scope="module")
def lanes(tmp_path_factory):
    sent: dict[str, list] = {}

    def factory(profile):
        pid = profile.profile_id
        return Capture(build_provider(profile, env={}),
                       sent.setdefault(pid, []))

    base = registry.load_profiles()["fixture-repair"]
    profiles = registry.load_profiles() | {
        "fx-base": registry._validate(base.raw | {"profile_id": "fx-base"},
                                      Path("fx-base.json")),
        "fx-assist": registry._validate(base.raw | {"profile_id":
                                                    "fx-assist"},
                                        Path("fx-assist.json"))}
    svc = make_service(tmp_path_factory.mktemp("lab"), profiles=profiles,
                       provider_factory=factory)
    cb, eb = run(svc, ["fx-base"], comparator="", question=Q.text,
                 benchmark_question_id="Q01")
    ca, ea = run(svc, ["fx-assist"], comparator="", question=Q.text,
                 benchmark_question_id="Q01", lane="ASSISTED_V1")
    return svc, (cb, eb), (ca, ea), sent


def _blocks(kw: dict) -> list[str]:
    sysm = kw.get("system")
    if isinstance(sysm, list):
        return [b.get("text", "") for b in sysm]
    return [str(sysm or "")]


def test_baseline_receives_no_assistance(lanes):
    _, (_, eb), _, sent = lanes
    assert child(eb, "fx-base")["lane"] == "FROZEN_BASELINE"
    assert sent["fx-base"]
    for kw in sent["fx-base"]:
        assert not any(assistance.HEADER in t for t in _blocks(kw))
        assert assistance.HEADER not in json.dumps(kw["messages"])


def test_assisted_receives_exactly_the_packet_on_every_call(lanes):
    svc, _, (ca, ea), sent = lanes
    expected = assistance.render(assistance.build_packet("Q01"))
    assert child(ea, "fx-assist")["lane"] == "ASSISTED_V1"
    assert len(sent["fx-assist"]) == len(sent["fx-base"])
    for kw in sent["fx-assist"]:
        blocks = _blocks(kw)
        assert blocks[-1] == expected                # last system block
        assert sum(assistance.HEADER in t for t in blocks) == 1
    spec = svc.coord._spec(ca)
    assert spec["assistance_packet"]["rendered_text"] == expected
    tr = model_io.build(svc.coord, ca, include_bodies=True)
    assert tr["assistance_packet"]["sha256"] == \
        spec["assistance_packet"]["sha256"]
    for it in tr["children"][0]["timeline"]:
        if it["kind"] == "call":
            got = it["views"]["assistance_appended_to_request"]
            assert got["appended_system_block"] == expected


def test_assistance_changes_context_only(lanes):
    """Without the appended block, the two lanes' provider requests are the
    same; so are the frozen events, tool calls, executed code and checks."""
    svc, (cb, eb), (ca, ea), sent = lanes
    strip = []
    for kw in sent["fx-assist"]:
        k = dict(kw)
        k["system"] = kw["system"][:-1]
        strip.append(k)
    assert [_norm(x) for x in strip] == [_norm(x) for x in sent["fx-base"]]
    b, a = child(eb, "fx-base"), child(ea, "fx-assist")
    assert [c["tool_names"] for c in a["calls"]] == \
        [c["tool_names"] for c in b["calls"]]
    assert [(c["check_id"], c["outcome"]) for c in a["checks"]] == \
        [(c["check_id"], c["outcome"]) for c in b["checks"]]
    runs = svc.coord.runs
    def ev(cid):
        rid = svc.coord.store.child_runs(
            svc.coord.store.children(cid)[0]["child_run_id"])[0]["run_id"]
        return [(e.event_type, e.operation, e.status)
                for e in runs.events_since(rid)], [
            s["payload"]["steps"][0]["code"]
            for s in runs.submissions_for_run(rid)]
    assert ev(cb) == ev(ca)


def test_packet_is_deterministic_and_answer_free():
    for q in bq.QUESTIONS:
        a = assistance.packet_record(assistance.build_packet(q.qid))
        b = assistance.packet_record(assistance.build_packet(q.qid))
        assert a["sha256"] == b["sha256"] and a["bytes"] == b["bytes"]
        text = a["rendered_text"]
        assert not re.search(r"\bSELECT\b|\bGROUP BY\b|\bFROM\s+corp_",
                             text, re.I), q.qid
        for word in ("opus", "oracle value", "expected answer"):
            assert word not in text.lower()
        sections = [k for k in a["packet"] if k[:2].rstrip("_").isdigit()]
        assert len(sections) == 14


def test_quarterly_join_keys_are_metadata_not_sql():
    for qid in ("Q04", "Q05", "Q08", "Q10", "Q14"):
        p = assistance.build_packet(qid)
        joins = [j for j in p["10_valid_join_keys"] if "right" in j]
        cross = [j for j in joins if "another quarter" not in j["right"]]
        assert cross, qid
        for j in cross:
            assert j["keys"] == ["borrower_id", "reporting_quarter"]
            assert "repeat once per facility" in j["warning"]
    p = assistance.build_packet("Q07")
    assert p["10_valid_join_keys"][0]["keys"] == ["facility_id"]
    assert "own reporting_quarter" in p["10_valid_join_keys"][0]["note"]


def test_assisted_capacity_accounts_for_the_packet():
    from backend.model_lab.child_runtime import capability_for
    p = registry.load_profiles()["qwen3.5-4b-nothink-longrun-64k"]
    rec = assistance.packet_record(assistance.build_packet("Q05"))
    assert capability_for(p, context_reserve_tokens=rec[
        "estimated_tokens"]).context_tokens == 65536 - rec[
        "estimated_tokens"]


def test_assisted_lane_needs_a_registered_verbatim_question(tmp_path):
    svc = make_service(tmp_path)
    pre = svc.coord.preflight({"question": Q.text, "lane": "ASSISTED_V1",
                               "profile_ids": ["fixture-reference"]})
    assert not pre["ok"] and "benchmark_question_id" in " ".join(
        pre["errors"])
    pre = svc.coord.preflight({"question": Q.text + " please",
                               "lane": "ASSISTED_V1",
                               "benchmark_question_id": "Q01",
                               "profile_ids": ["fixture-reference"]})
    assert not pre["ok"] and "verbatim" in " ".join(pre["errors"])
    pre = svc.coord.preflight({"question": Q.text, "lane": "BOOSTED",
                               "profile_ids": ["fixture-reference"]})
    assert not pre["ok"]
