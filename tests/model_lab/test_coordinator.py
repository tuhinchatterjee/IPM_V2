"""U01-U03, U10-U14, O03-O05, O07: scheduling, idempotency, cancel, restart."""

from __future__ import annotations

import json
import threading
import time

import pytest
from conftest import QUESTION, child, make_service, run

from backend.model_lab.coordinator import SpecError


def test_U01_one_request_creates_every_selected_child(demo):
    svc, cid, ev = demo
    st = svc.coord.status(cid)
    assert len(st["children"]) == len(st["spec"]["selected_profile_ids"])
    assert st["spec"]["question_text"] == QUESTION
    # Every child's first turn was asked the SAME original question.
    for c in st["children"]:
        for t in c["turns"][:1]:
            assert t["question"] == QUESTION


def test_U03_unavailable_models_stay_visible_with_a_reason(demo):
    _, _, ev = demo
    opus = child(ev, "opus-frozen")
    assert opus["execution_state"] == "BLOCKED"
    assert "COCKPIT_ANTHROPIC_API_KEY" in opus["reason"]
    assert opus["failures"][0]["model_failure"] is False
    q = child(ev, "qwen3.5-9b")
    assert q["execution_state"] == "BLOCKED" and "probe" in q["reason"]
    assert ev["comparator"]["status"] == "READY"


def test_O07_double_click_and_retry_are_idempotent(tmp_path):
    svc = make_service(tmp_path)
    req = {"question": QUESTION, "profile_ids": ["fixture-reference"],
           "comparator_id": "fixture-reference"}
    results = []
    ts = [threading.Thread(target=lambda: results.append(
        svc.coord.create(req, idempotency_key="same")["comparison_id"]))
        for _ in range(3)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert len(set(results)) == 1
    svc.coord.wait(results[0])
    runs = svc.coord.runs._connect().execute(
        "SELECT COUNT(*) FROM runs").fetchone()[0]
    assert runs == 1, "a double click must not run the investigation twice"


def test_O07_restart_marks_in_flight_children_interrupted_not_rerun(tmp_path):
    svc = make_service(tmp_path)
    st = svc.coord.create({"question": QUESTION,
                           "profile_ids": ["fixture-reference",
                                           "fixture-repair"],
                           "comparator_id": "fixture-reference"},
                          start=False)
    cid = st["comparison_id"]
    c0 = st["children"][0]["child_run_id"]
    svc.coord.store.transition_child(c0, "PREPARING", expect=("QUEUED",))
    svc.coord.store.transition_child(c0, "RUNNING", expect=("PREPARING",))
    svc.coord.store.set_comparison_state(cid, "RUNNING")
    # A new process comes up over the same state.
    svc2 = make_service(tmp_path)
    after = {c["child_run_id"]: c["state"]
             for c in svc2.coord.status(cid)["children"]}
    assert after[c0] == "INTERRUPTED"
    assert svc2.coord.runs._connect().execute(
        "SELECT COUNT(*) FROM runs").fetchone()[0] == 0


def test_U14_cancel_keeps_finished_results_and_cancels_the_queue(tmp_path):
    svc = make_service(tmp_path)
    st = svc.coord.create({"question": QUESTION,
                           "profile_ids": ["fixture-reference",
                                           "fixture-repair",
                                           "fixture-wrong-scope"],
                           "comparator_id": "fixture-reference"},
                          start=False)
    cid = st["comparison_id"]
    svc.coord.cancel(cid)
    svc.coord.start(cid)
    st = svc.coord.wait(cid)
    assert st["state"] == "CANCELLED"
    assert {c["state"] for c in st["children"]} == {"CANCELLED"}
    ev = svc.coord.store.current_evaluation(cid, svc.cfg.tenant_id)["body"]
    assert all(k["stages"]["S4"]["status"] == "NOT_REACHED"
               for k in ev["children"])


def test_U11_clarification_resumes_only_the_named_waiting_child(tmp_path):
    svc = make_service(tmp_path)
    cid, ev = run(svc, ["fixture-reference", "fixture-clarify"])
    wait = child(ev, "fixture-clarify")
    ref = child(ev, "fixture-reference")
    assert wait["execution_state"] == "WAITING_USER"
    assert wait["stages"]["S4"]["status"] == "NOT_REACHED"
    with pytest.raises(SpecError):
        svc.coord.answer_clarification(cid, text="EAD", child_ids=[])
    with pytest.raises(SpecError):
        svc.coord.answer_clarification(cid, text="EAD",
                                       child_ids=[ref["child_run_id"]])
    before = len(svc.coord.store.child_runs(ref["child_run_id"]))
    svc.coord.answer_clarification(cid, text="EAD",
                                   child_ids=[wait["child_run_id"]])
    svc.coord.wait(cid)
    assert len(svc.coord.store.child_runs(ref["child_run_id"])) == before
    turns = svc.coord.store.child_runs(wait["child_run_id"])
    assert [t["kind"] for t in turns] == ["INITIAL", "CLARIFICATION"]
    ev2 = svc.coord.store.current_evaluation(cid, svc.cfg.tenant_id)["body"]
    w2 = child(ev2, "fixture-clarify")
    assert w2["execution_state"] == "COMPLETED"
    assert w2["metrics"]["user_wait_ms"]["status"] == "DERIVED"
    events = [e["event_type"] for e in
              svc.coord.store.events(cid, svc.cfg.tenant_id)]
    assert "clarification.answered" in events


def test_U12_follow_up_goes_to_each_models_own_thread(tmp_path):
    svc = make_service(tmp_path)
    cid, ev = run(svc, ["fixture-reference", "fixture-alternate-plan"])
    threads = {c["child_run_id"]: c["thread_id"]
               for c in svc.coord.store.children(cid)}
    assert len(set(threads.values())) == 2      # no shared history
    svc.coord.follow_up(cid, text="And for the previous quarter?")
    svc.coord.wait(cid)
    for c in svc.coord.store.children(cid):
        assert c["lineage"] == "NATURAL_CONVERSATION"
        turns = svc.coord.store.child_runs(c["child_run_id"])
        assert [t["kind"] for t in turns] == ["INITIAL", "FOLLOW_UP"]
        for t in turns:
            rec = svc.coord.runs.get_run(t["run_id"])
            assert rec.thread_id == threads[c["child_run_id"]]


def test_O05_paid_children_need_a_cap_that_covers_the_reserve(tmp_path):
    svc = make_service(tmp_path, env={"COCKPIT_ANTHROPIC_API_KEY": "k"})
    (tmp_path / "approvals.json").write_text(json.dumps(
        {"opus_spend": {"cap_usd": 1.0}}))
    pre = svc.coord.preflight({"question": QUESTION,
                               "profile_ids": ["opus-frozen"],
                               "comparator_id": "opus-frozen",
                               "group_spend_cap_usd": 1.0})
    assert not pre["ok"] and "reserve" in " ".join(pre["errors"])
    assert pre["no_inference_performed"] is True
    with pytest.raises(SpecError):
        svc.coord.create({"question": QUESTION,
                          "profile_ids": ["opus-frozen"],
                          "comparator_id": "opus-frozen",
                          "group_spend_cap_usd": 1.0})


def test_O05_remote_parallel_requires_its_approval(tmp_path):
    svc = make_service(tmp_path)
    pre = svc.coord.preflight({"question": QUESTION,
                               "profile_ids": ["fixture-reference"],
                               "deployment": "remote_parallel"})
    assert not pre["ok"] and "remote_inference" in " ".join(pre["errors"])


def test_O03_sequential_lane_runs_one_child_at_a_time(tmp_path):
    active, peak = [0], [0]
    lock = threading.Lock()
    from backend.model_lab.adapters import build_provider

    class Counting:
        def __init__(self, inner):
            self.inner = inner

        def converse(self, **kw):
            with lock:
                active[0] += 1
                peak[0] = max(peak[0], active[0])
            try:
                time.sleep(0.02)
                return self.inner.converse(**kw)
            finally:
                with lock:
                    active[0] -= 1

    svc = make_service(tmp_path, provider_factory=lambda p: Counting(
        build_provider(p)))
    a = svc.coord.create({"question": QUESTION, "profile_ids":
                          ["fixture-reference", "fixture-repair"],
                          "comparator_id": "fixture-reference"})
    b = svc.coord.create({"question": QUESTION, "profile_ids":
                          ["fixture-alternate-plan"],
                          "comparator_id": "fixture-alternate-plan"})
    svc.coord.wait(a["comparison_id"])
    svc.coord.wait(b["comparison_id"])
    assert peak[0] == 1, "two local children overlapped on the Mac lane"


def test_M01_queue_delay_is_separate_from_service_time(demo):
    _, _, ev = demo
    ran = [k for k in ev["children"] if k["turns"]]
    delays = [k["metrics"]["queue_delay_ms"]["value"] for k in ran]
    assert delays == sorted(delays), "later children waited longer"
    for k in ran:
        assert k["metrics"]["service_ms"]["status"] == "MEASURED"
        assert k["metrics"]["queue_delay_ms"]["definition"]
    assert ev["comparison_elapsed_ms"]["status"] == "MEASURED"


def test_U13_reopen_and_reevaluate_make_no_model_call(demo):
    svc, cid, _ = demo
    runs_before = svc.coord.runs._connect().execute(
        "SELECT COUNT(*) FROM runs").fetchone()[0]
    body = svc.evaluate(cid)
    assert body["revision"] >= 2
    svc.coord.status(cid)
    runs_after = svc.coord.runs._connect().execute(
        "SELECT COUNT(*) FROM runs").fetchone()[0]
    assert runs_after == runs_before
    hist = svc.coord.store.evaluation_history(cid, svc.cfg.tenant_id)
    assert [h["status"] for h in hist][-1] == "CURRENT"
    assert "SUPERSEDED" in [h["status"] for h in hist]
