"""OPUS_REFERENCE_SET_V1: one saved Opus reference per question, reused,
spend-gated, read-only, and the only Opus a candidate is compared with.

A labelled FIXTURE registered as `opus-frozen` stands in for Opus; every
provider build is counted, so "zero Opus calls" is measured, not assumed.
Nothing here calls a real model or reads a real key.
"""

from __future__ import annotations

import collections
import json
import shutil
import sqlite3
import sys
from pathlib import Path

import pytest
from conftest import ROOT, as_opus_profiles, build_fixture_reference_set, make_service

from backend.model_lab import benchmark_questions as bq
from backend.model_lab import opus_references as orf

sys.path.insert(0, str(ROOT / "scripts" / "model_lab"))
import benchmark_suite  # noqa: E402
import opus_reference_set as cli  # noqa: E402
import suite_report  # noqa: E402

CALLS: collections.Counter = collections.Counter()
CANARY = "sk-" + "ant-api03-CANARY-OPUSREF-" + "Z" * 40   # split: no literal key


@pytest.fixture(scope="module", autouse=True)
def _count_provider_builds():
    import backend.model_lab.adapters as adapters
    real = adapters.build_provider

    def counted(profile, **kw):
        CALLS[profile.profile_id] += 1
        return real(profile, **kw)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(adapters, "build_provider", counted)
        mp.setenv("COCKPIT_ANTHROPIC_API_KEY", CANARY)
        yield


def _grant(rt: Path, cap: float) -> None:
    rt.mkdir(parents=True, exist_ok=True)
    (rt / "approvals.json").write_text(json.dumps(
        {"opus_spend": {"granted_at": 1.0, "granted_by": "t",
                        "cap_usd": cap}}))


def _n_comparisons(rt: Path) -> int:
    p = rt / "lab_index.sqlite3"
    if not p.exists():
        return 0
    return sqlite3.connect(p).execute(
        "SELECT COUNT(*) FROM comparisons").fetchone()[0]


def _snapshot(svc, cid: str) -> str:
    st, t = svc.coord.store, svc.cfg.tenant_id
    return json.dumps({
        "row": st.get_comparison(cid, t),
        "evaluations": st.evaluation_history(cid, t),
        "current": st.current_evaluation(cid, t),
        "events": len(st.events(cid, t, 0, 10 ** 7)),
        "children": st.children(cid),
        "runs": [st.child_runs(c["child_run_id"]) for c in st.children(cid)],
    }, sort_keys=True, default=str)


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    """Q01 and Q02 references built once, through the real CLI."""
    tmp = tmp_path_factory.mktemp("refset")
    rt, sd = tmp / "rt", tmp / "sets"
    before = CALLS["opus-frozen"]
    rc = build_fixture_reference_set(rt, sd, ["Q01", "Q02"])
    assert rc == 6                     # Q03-Q15 still missing, by design
    assert CALLS["opus-frozen"] - before == 2        # exactly one per question
    svc = make_service(rt, profiles=as_opus_profiles())
    return svc, rt, sd, json.loads(orf.set_path(sd).read_text())


# ---- the set itself -------------------------------------------------------------

def test_set_records_every_required_field(built):
    _, _, sd, doc = built
    assert doc["set_id"] == "OPUS_REFERENCE_SET_V1"
    assert list(doc["questions"]) == [q.qid for q in bq.QUESTIONS]
    for qid in ("Q01", "Q02"):
        e = doc["questions"][qid]
        assert e["state"] == "READY"
        assert e["question_text"] == bq.get(qid).text
        assert e["reference_comparison_id"].startswith("cmp-")
        assert e["opus_child_run_id"].startswith("child-")
        assert e["profile_id"] == "opus-frozen"
        assert e["data_snapshot_id"] == orf.current_snapshot_id()
        assert e["frozen_source_id"] == orf.FROZEN_COMMIT
        assert e["evaluator_version"] and isinstance(
            e["evaluation_revision"], int)
        assert e["oracle"]["oracle_version"] == "lab-oracle-suite-1"
        assert e["created_at"] and e["model_id"]
        assert e["model_io_trace"]["status"] == "FULL"
        assert e["provenance"] == "BUILT_BY_SET"
        assert e["export_pack"]["sha256"]
        assert {Path(p).name for p in e["answer_artifacts"]} == {
            "answer.json", "evaluation_child.json", "result_tables.json",
            "code.json"}
        for p, sha in e["answer_artifacts"].items():
            f = Path(p) if Path(p).is_absolute() else ROOT / p
            assert orf._sha_file(f) == sha
    assert all(doc["questions"][q.qid]["state"] == "MISSING"
               for q in bq.QUESTIONS[2:])
    assert len(doc["spend_ledger"]) == 2


def test_code_and_tool_round_trips_are_captured(built):
    _, _, _, doc = built
    code = next(p for p in doc["questions"]["Q01"]["answer_artifacts"]
                if p.endswith("code.json"))
    steps = json.loads(Path(code).read_text())
    assert steps and steps[0]["steps"] and steps[0]["tool_roundtrip"]


# ---- no duplicate Opus spend -------------------------------------------------------

def test_valid_saved_references_mean_zero_opus_calls(built, tmp_path,
                                                     capsys):
    svc, rt, _, doc = built
    before = CALLS["opus-frozen"], _n_comparisons(rt)
    fresh = tmp_path / "sets"               # an empty set over the same store
    rc = cli.main(["preflight", "--runtime-dir", str(rt), "--set-dir",
                   str(fresh), "--allow-fixture-reference"], svc=svc)
    assert rc == 3
    again = json.loads(orf.set_path(fresh).read_text())
    for qid in ("Q01", "Q02"):
        assert again["questions"][qid]["state"] == "READY"
        assert again["questions"][qid]["provenance"] == "REUSED_EXISTING"
        assert again["questions"][qid]["reference_comparison_id"] == \
            doc["questions"][qid]["reference_comparison_id"]
    assert (CALLS["opus-frozen"], _n_comparisons(rt)) == before
    out = capsys.readouterr().out
    assert "existing_valid: 2 Q01,Q02" in out and "missing: 13" in out


def test_rerunning_build_makes_no_duplicate_reference(built):
    svc, rt, sd, _ = built
    before = CALLS["opus-frozen"], _n_comparisons(rt)
    rc = cli.main(["build", "--runtime-dir", str(rt), "--set-dir", str(sd),
                   "--confirm-paid-opus-calls", "--allow-fixture-reference",
                   "--question", "Q01", "--question", "Q02"], svc=svc)
    assert rc == 6
    assert (CALLS["opus-frozen"], _n_comparisons(rt)) == before


# ---- the spend gate stops BEFORE any call ---------------------------------------

@pytest.mark.parametrize("cap", [None, 5.0])
def test_insufficient_approval_stops_before_any_opus_call(tmp_path, capsys,
                                                          cap):
    rt, sd = tmp_path / "rt", tmp_path / "sets"
    if cap is not None:
        _grant(rt, cap)
    svc = make_service(rt, profiles=as_opus_profiles())
    before = CALLS["opus-frozen"]
    rc = cli.main(["build", "--runtime-dir", str(rt), "--set-dir", str(sd),
                   "--confirm-paid-opus-calls", "--allow-fixture-reference"],
                  svc=svc)
    out = capsys.readouterr().out
    assert rc == 4
    assert "OPUS_SPEND_APPROVAL_REQUIRED" in out
    assert "required_cap_usd: 45.00" in out
    assert f"current_cap_usd: {'none' if cap is None else '5.00'}" in out
    assert "missing_questions: " + ",".join(q.qid for q in bq.QUESTIONS) \
        in out
    assert CALLS["opus-frozen"] == before and _n_comparisons(rt) == 0
    # the approval is never raised automatically
    ap = rt / "approvals.json"
    assert (json.loads(ap.read_text())["opus_spend"]["cap_usd"] == cap) \
        if cap is not None else not ap.exists()


def test_build_needs_explicit_confirmation(tmp_path, capsys):
    rt = tmp_path / "rt"
    _grant(rt, 100)
    svc = make_service(rt, profiles=as_opus_profiles())
    assert cli.main(["build", "--runtime-dir", str(rt), "--set-dir",
                     str(tmp_path / "s"), "--allow-fixture-reference"],
                    svc=svc) == 2
    assert "--confirm-paid-opus-calls" in capsys.readouterr().out
    assert _n_comparisons(rt) == 0


def test_real_opus_without_key_stops_before_any_call(tmp_path, capsys):
    rt = tmp_path / "rt"
    _grant(rt, 100)

    def never(profile):
        raise AssertionError("a provider was built")
    svc = make_service(rt, provider_factory=never)   # the REAL opus profile
    rc = cli.main(["build", "--runtime-dir", str(rt), "--set-dir",
                   str(tmp_path / "s"), "--confirm-paid-opus-calls"],
                  svc=svc, env={})
    out = capsys.readouterr().out
    assert rc == 5 and "OPUS_KEY_REQUIRED" in out
    assert _n_comparisons(rt) == 0


def test_preflight_prints_the_exact_gate_block(tmp_path, capsys):
    rt = tmp_path / "rt"
    svc = make_service(rt)
    assert cli.main(["preflight", "--runtime-dir", str(rt), "--set-dir",
                     str(tmp_path / "s")], svc=svc, env={}) == 3
    out = capsys.readouterr().out
    for line in ("existing_valid: 0", "missing: 15",
                 "current_approval_cap: none", "estimated_required_cap: "
                 "$45.00", "COCKPIT_ANTHROPIC_API_KEY: absent",
                 "OPUS_SPEND_APPROVAL_REQUIRED", "cmp-f364d8b6901a"):
        assert line in out


# ---- reuse rejections (each explicit) -----------------------------------------------

def test_reuse_rejections(built, tmp_path):
    svc, rt, _, doc = built
    q1 = doc["questions"]["Q01"]["reference_comparison_id"]
    v = orf.verify_comparison
    assert v(svc.coord, q1, "Q01", allow_fixture=True)["ok"]
    assert v(svc.coord, q1, "Q01")["status"] == "REFERENCE_IS_FIXTURE"
    assert v(svc.coord, q1, "Q02", allow_fixture=True)["status"] == \
        "REFERENCE_NOT_COMPARABLE"                       # other question
    assert v(svc.coord, q1, "Q01", snapshot_id="x@y",
             allow_fixture=True)["status"] == "REFERENCE_NOT_COMPARABLE"
    assert v(svc.coord, "cmp-000000000000", "Q01")["status"] == \
        "REFERENCE_COMPARISON_UNAVAILABLE"

    # tampered copies of the store
    def copy():
        d = tmp_path / f"c{len(list(tmp_path.iterdir()))}"
        shutil.copytree(rt, d)
        return d, sqlite3.connect(d / "lab_index.sqlite3")

    d, c = copy()
    spec = json.loads(c.execute("SELECT spec_json FROM comparisons WHERE "
                                "comparison_id=?", (q1,)).fetchone()[0])
    c.execute("UPDATE comparisons SET spec_json=? WHERE comparison_id=?",
              (json.dumps(spec | {"frozen_source_id": "0" * 40}), q1))
    c.commit()
    s2 = make_service(d, profiles=as_opus_profiles())
    r = v(s2.coord, q1, "Q01", allow_fixture=True)
    assert r["status"] == "REFERENCE_CORRUPT" and "checksum" in r["reason"]

    d, c = copy()
    spec2 = spec | {"frozen_source_id": "0" * 40}
    c.execute("UPDATE comparisons SET spec_json=?, spec_hash=? WHERE "
              "comparison_id=?", (json.dumps(spec2), orf._h(
                  {k: x for k, x in spec2.items() if k not in (
                      "created_at", "preflight", "comparison_id")}), q1))
    c.commit()
    r = v(make_service(d, profiles=as_opus_profiles()).coord, q1, "Q01",
          allow_fixture=True)
    assert r["status"] == "REFERENCE_NOT_COMPARABLE" and "frozen source" \
        in r["reason"]

    d, c = copy()
    row = c.execute("SELECT evaluation_id, body FROM evaluations WHERE "
                    "comparison_id=? AND superseded_by IS NULL",
                    (q1,)).fetchone()
    c.execute("UPDATE evaluations SET body=? WHERE evaluation_id=?",
              (json.dumps(json.loads(row[1]) | {
                  "evaluator_version": "lab-eval-2"}), row[0]))
    c.commit()
    r = v(make_service(d, profiles=as_opus_profiles()).coord, q1, "Q01",
          allow_fixture=True)
    assert r["status"] == "REFERENCE_EVALUATION_INCOMPATIBLE"
    assert "reevaluate.py" in r["reason"]

    d, c = copy()
    c.execute("UPDATE children SET state='FAILED' WHERE comparison_id=?",
              (q1,))
    c.commit()
    r = v(make_service(d, profiles=as_opus_profiles()).coord, q1, "Q01",
          allow_fixture=True)
    assert r["status"] == "REFERENCE_OPUS_NOT_COMPLETED"


def test_a_ready_entry_is_never_silently_replaced(built, tmp_path):
    _, rt, sd, doc = built
    d = tmp_path / "rt"
    shutil.copytree(rt, d)
    s2 = make_service(d, profiles=as_opus_profiles())
    q1 = doc["questions"]["Q01"]["reference_comparison_id"]
    s2.evaluate(q1)                 # somebody re-scores the reference later
    moved = json.loads(json.dumps(doc))
    orf.resolve(s2.coord, moved, directory=sd, allow_fixture=True,
                write_snapshots=False)
    e = moved["questions"]["Q01"]
    assert e["state"] == "INVALID"
    assert e["invalid_status"] == "REFERENCE_CHANGED"
    assert e["reference_comparison_id"] == q1        # kept, not swapped


# ---- the candidate gate -----------------------------------------------------------

def _suite(tmp: Path, qids: list[str], models: list[str]) -> Path:
    suite = json.loads((ROOT / "profiles" / "_runpod_suite.json")
                       .read_text())
    suite["suite_id"] = f"t-{tmp.name}"
    suite["models"] = [{"model": m, "profile_id": m} for m in models]
    suite["questions"] = [q for q in suite["questions"]
                          if q["question_id"] in qids]
    p = tmp / "suite.json"
    p.write_text(json.dumps(suite))
    return p


@pytest.fixture(scope="module")
def gated(built, tmp_path_factory):
    svc, rt, sd, doc = built
    tmp = tmp_path_factory.mktemp("gated")
    sp = _suite(tmp, ["Q01", "Q02"], ["fixture-alternate-plan",
                                      "fixture-repair"])
    refs = {q: doc["questions"][q]["reference_comparison_id"]
            for q in ("Q01", "Q02")}
    before = {q: _snapshot(svc, c) for q, c in refs.items()}
    set_bytes = orf.set_path(sd).read_bytes()
    opus_before, n_before = CALLS["opus-frozen"], _n_comparisons(rt)
    args = ["--suite", str(sp), "--runtime-dir", str(rt), "--run",
            "--confirm-model-calls", "--reference-set",
            str(orf.set_path(sd)), "--allow-fixture-reference"]
    assert benchmark_suite.main(args) == 0
    assert benchmark_suite.main(args) == 0                   # resume
    suite = json.loads(sp.read_text())
    return dict(svc=svc, rt=rt, sd=sd, refs=refs, before=before,
                set_bytes=set_bytes, opus=CALLS["opus-frozen"] - opus_before,
                created=_n_comparisons(rt) - n_before, suite=suite,
                cp=benchmark_suite.load_checkpoint(rt, suite))


def test_candidates_trigger_no_opus_call_and_no_new_reference(gated):
    assert gated["opus"] == 0
    assert gated["created"] == 2 * 2 * 2       # models x lanes x questions


def test_every_cell_points_at_its_saved_reference(gated):
    svc, cp, refs = gated["svc"], gated["cp"], gated["refs"]
    t = svc.cfg.tenant_id
    assert cp["reference_set"]["questions"] == refs
    assert cp["reference_set"]["diagnostic_allow_missing_opus"] is False
    for key, cell in cp["cells"].items():
        pid, lane, qid = key.split("|")
        spec = json.loads(svc.coord.store.get_comparison(
            cell["comparison_id"], t)["spec_json"])
        assert spec["reference_comparison_id"] == refs[qid]
        assert cell["reference_comparison_id"] == refs[qid]
        assert spec["comparator_id"] == ""              # no live Opus child
        assert [c["profile_id"] for c in svc.coord.store.children(
            cell["comparison_id"])] == [pid]
        ev = svc.coord.store.current_evaluation(cell["comparison_id"],
                                                t)["body"]
        assert ev["saved_reference"]["reference_status"] == "READY"
        assert ev["comparator"]["status"] == "COMPARATOR_UNAVAILABLE"
        k = ev["children"][0]
        assert set(k["reference_match"]) == {"S1", "S2", "S3", "S4",
                                             "FINAL"}
    # BASELINE and ASSISTED_V1 of one model use the same reference
    for pid in ("fixture-alternate-plan", "fixture-repair"):
        for qid in ("Q01", "Q02"):
            a = cp["cells"][f"{pid}|FROZEN_BASELINE|{qid}"]
            b = cp["cells"][f"{pid}|ASSISTED_V1|{qid}"]
            assert a["reference_comparison_id"] == \
                b["reference_comparison_id"] == refs[qid]


def test_references_stay_byte_identical_and_read_only(gated):
    svc = gated["svc"]
    for q, cid in gated["refs"].items():
        assert _snapshot(svc, cid) == gated["before"][q]
    assert orf.set_path(gated["sd"]).read_bytes() == gated["set_bytes"]


def test_report_keeps_correctness_and_agreement_apart(gated):
    rep = suite_report.build(gated["rt"], gated["suite"])
    assert rep["reference_set"]["questions"] == gated["refs"]
    for c in rep["cells"]:
        assert c["independent_correctness"]["source"] == \
            "independent pandas oracle"
        oa = c["opus_agreement"]
        assert oa["reference_comparison_id"] == gated["refs"][
            c["question_id"]]
        assert oa["reference_status"] == "READY"
        assert isinstance(oa["reference_evaluation_revision"], int)
        assert set(oa["stages"]) == {"S1", "S2", "S3", "S4", "FINAL"}
        for s in oa["stages"].values():          # N/A is never turned to 0
            assert (s["pct"] is None) == (s["display"] == "N/A")
            if s["pct"] is None:
                assert s["reason"]
    out = suite_report.write(gated["rt"], gated["suite"])
    head = (out / "cells.csv").read_text().splitlines()[0]
    assert "reference_comparison_id" in head and "opus_agreement_FINAL" in \
        head and "correctness" in head


def test_missing_reference_blocks_candidates_by_default(built, tmp_path,
                                                        capsys):
    _, rt, sd, _ = built
    sp = _suite(tmp_path, ["Q03"], ["fixture-alternate-plan"])
    n = _n_comparisons(rt)
    rc = benchmark_suite.main(["--suite", str(sp), "--runtime-dir", str(rt),
                               "--run", "--confirm-model-calls",
                               "--reference-set", str(orf.set_path(sd)),
                               "--allow-fixture-reference"])
    out = capsys.readouterr().out
    assert rc == 2 and "OPUS_REFERENCE_SET_INCOMPLETE" in out
    assert "Q03 MISSING" in out and _n_comparisons(rt) == n


def test_fixture_reference_is_not_opus_for_a_production_run(built,
                                                            tmp_path,
                                                            capsys):
    _, rt, sd, _ = built
    sp = _suite(tmp_path, ["Q01"], ["fixture-alternate-plan"])
    n = _n_comparisons(rt)
    rc = benchmark_suite.main(["--suite", str(sp), "--runtime-dir", str(rt),
                               "--run", "--confirm-model-calls",
                               "--reference-set", str(orf.set_path(sd))])
    assert rc == 2 and "INVALID" in capsys.readouterr().out
    assert _n_comparisons(rt) == n


def test_allow_missing_opus_is_a_labelled_diagnostic(built, tmp_path,
                                                     capsys):
    _, rt, sd, _ = built
    sp = _suite(tmp_path, ["Q03"], ["fixture-alternate-plan"])
    before = CALLS["opus-frozen"]
    rc = benchmark_suite.main(["--suite", str(sp), "--runtime-dir", str(rt),
                               "--run", "--confirm-model-calls",
                               "--lane", "FROZEN_BASELINE",
                               "--reference-set", str(orf.set_path(sd)),
                               "--allow-fixture-reference",
                               "--allow-missing-opus"])
    assert rc == 0 and "DIAGNOSTIC RUN" in capsys.readouterr().out
    cp = benchmark_suite.load_checkpoint(rt, json.loads(sp.read_text()))
    assert cp["reference_set"]["diagnostic_allow_missing_opus"] is True
    (cell,) = cp["cells"].values()
    assert cell["state"] == "DONE" and cell["reference_comparison_id"] is None
    assert cell["reference_status"].startswith("MISSING_OPUS_REFERENCE")
    assert CALLS["opus-frozen"] == before


def test_production_suite_and_bootstrap_never_bypass_the_gate():
    suite = json.loads((ROOT / "profiles" / "_runpod_suite.json")
                       .read_text())
    assert suite["reference_set"]["set_id"] == "OPUS_REFERENCE_SET_V1"
    assert "reference" not in suite
    assert [q["question_id"] for q in suite["questions"]] == \
        [q.qid for q in bq.QUESTIONS]
    assert all(m["profile_id"] != "opus-frozen" for m in suite["models"])
    boot = (ROOT / "scripts/model_lab/runpod/RUNPOD_BOOTSTRAP.sh").read_text()
    assert "--allow-missing-opus" not in boot
    assert "--allow-fixture-reference" not in boot
    assert "opus_reference_set.py" in boot
    # the paid build is only ever PRINTED for the operator, never executed
    lines = [ln.strip() for ln in boot.splitlines()
             if "--confirm-paid-opus-calls" in ln]
    assert lines and all(ln.startswith(("echo", "#")) for ln in lines)


# ---- credentials ---------------------------------------------------------------------

def test_api_key_never_reaches_set_store_trace_or_exports(built, capsys):
    _, rt, sd, _ = built
    needle = CANARY.encode()
    hits = []
    for base in (rt, sd):
        for f in base.rglob("*"):
            if f.is_file() and needle in f.read_bytes():
                hits.append(str(f))
    assert hits == []
    assert CANARY not in capsys.readouterr().out
