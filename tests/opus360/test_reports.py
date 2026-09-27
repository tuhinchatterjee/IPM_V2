"""Report generation from a small scripted experiment (MODEL MOCK)."""

from __future__ import annotations

import csv

from cert import oracles as orc
from cert import protected, reports, scripted
from cert.ledger import Experiment
from cert.runner import Guards, Price, Runner

EXPECTED = ["manifest.json", "question_bank.yaml", "case_results.csv", "case_results.jsonl", "model_calls.csv",
            "tool_calls.csv", "submissions.csv", "artifacts.csv", "claims.csv", "oracle_results.csv",
            "thread_metrics.csv", "paraphrase_metrics.csv", "repeatability_metrics.csv", "failure_analysis.csv",
            "timing_metrics.csv", "token_metrics.csv", "cost_metrics.csv", "load_test.csv", "events.jsonl",
            "run.log", "checksums.sha256", "ARCHITECTURE_CERTIFICATION_REPORT.md", "ARCHITECTURE_FINDINGS.md",
            "EXECUTIVE_SUMMARY.md", "FREEZE_READINESS.md", "opus360_results.xlsx"]


def test_reports_are_complete_and_labelled(harness, bank, tmp_path):
    by_id = {r["case_id"]: r for r in bank["rows"]}
    cases = [by_id[c] for c in ("A-C01", "E-01", "F-01", "D-TD05-1", "D-TD05-2")]
    refs = {}
    for c in cases:
        refs[f"{c['case_id']}:primary"] = orc.compute(c["oracle"], c["domain"])
        if c.get("followup_oracle"):
            refs[f"{c['case_id']}:followup"] = orc.compute(c["followup_oracle"], c["domain"])
    exp = Experiment(tmp_path / "exp")
    exp.create({"experiment_id": "report-test", "live": False, "frozen_commit": "245c50e",
                "frozen_tag": "t", "model": "claude-opus-5",
                "protected_manifest_sha256": protected.verify().manifest_sha256})
    runner = Runner(exp, harness, harness.recorder, bank_rows=cases, refs=refs, price=Price(5, 25, 6.25, .5),
                    guards=Guards(live=False, max_usd=None, max_hours=None), live=False, echo=False,
                    script_factory=lambda c, r, d, b, a: scripted.analyst_for(c, r, domain=d, behaviour=b),
                    protected_manifest_sha=protected.verify().manifest_sha256)
    runner.run_phase("core", cases)
    files = reports.build(exp, bank["rows"])
    for name in EXPECTED:
        assert (exp.root / name).exists(), name
    summary = (exp.root / "EXECUTIVE_SUMMARY.md").read_text()
    assert "DRY RUN — SCRIPTED ANALYST, NOT OPUS" in summary
    assert "| Core user turns (planned) | 250 |" in summary
    rows = list(csv.DictReader(open(exp.root / "case_results.csv")))
    assert {r["case_id"] for r in rows} == {c["case_id"] for c in cases}
    pinned = [r for r in rows if r["case_id"] == "D-TD05-2"][0]
    assert pinned["behaviour_observed"] == "ROUTE_REFUSED_DOMAIN_PINNED" and pinned["passed"] == "TRUE"
    findings = (exp.root / "ARCHITECTURE_FINDINGS.md").read_text()
    assert "S-01" in findings and "No change has been made to the frozen AdvancedCockpit" in findings
    for f in exp.root.rglob("*"):
        if f.is_file() and f.suffix in (".csv", ".md", ".jsonl", ".json"):
            assert "sk-ant-" not in f.read_text(errors="ignore")
    assert len(files) >= 20
