"""
The Playbook M1 vertical slice, against the real configured provider.

Runs one complete journey and proves each step from its result rather than from
its own report of itself:

    a real prior report and a real results workbook are uploaded and parsed
    -> the evidence ledger is assembled from them, with locators
    -> the configured authoring model writes the report
    -> its figures are reconciled against the evidence
    -> DOCX and PDF are produced, retrieved and persisted as real bytes
    -> both files are reopened and checked
    -> the workspace is reopened in a NEW session
    -> a scoped revision is requested
    -> version 2 exists, version 1 is intact, and the facts are unchanged

Exit codes follow the repository's convention for verification scripts:

    0  the slice ran and every check held
    1  the slice ran and something failed
    2  the slice could NOT run — no provider configured, or no database

Two is not a pass. A missing key means live generation is unverified, and this
script says so rather than reporting success from a fallback path.

    .venv/bin/python scripts/playbook_live_slice.py [--keep]
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from datetime import UTC, datetime

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

EVIDENCE = REPO / "docs" / "playbook" / "live_slice.json"

ok: list[str] = []
bad: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> bool:
    (ok if condition else bad).append(f"{name}{(' — ' + detail) if detail else ''}")
    print(("  PASS  " if condition else "  FAIL  ") + name
          + (f"  {detail}" if detail else ""), flush=True)
    return bool(condition)


def _prior_report() -> bytes:
    from docx import Document

    doc = Document()
    doc.core_properties.title = "IFRS 9 Committee Report — Q1 2026"
    doc.sections[0].header.paragraphs[0].text = "IFRS 9 Committee Report — Q1 2026"
    doc.add_heading("1. Executive summary", level=1)
    doc.add_paragraph(
        "Weighted ECL for the quarter was SAR 20.90 million against exposure of "
        "SAR 1,000 million, a coverage ratio of 2.09 per cent. The scenario "
        "weighting was unchanged at 60/15/25."
    )
    doc.add_heading("2. Scenario results", level=1)
    table = doc.add_table(rows=4, cols=2)
    for r, (a, b) in enumerate([("Scenario", "ECL, SAR million"),
                                ("Base", "18.00"), ("Upturn", "14.00"),
                                ("Downturn", "32.00")]):
        table.rows[r].cells[0].text = a
        table.rows[r].cells[1].text = b
    doc.add_heading("3. Limitations", level=1)
    doc.add_paragraph("Post-model adjustments are not covered in this report.")
    import io

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _results_workbook() -> bytes:
    import io

    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "ECL"
    for row in [["Scenario", "ECL, SAR million", "Weight"],
                ["Base", 19.20, 0.60], ["Upturn", 15.00, 0.15],
                ["Downturn", 36.00, 0.25]]:
        ws.append(row)
    exposure = wb.create_sheet("Exposure")
    exposure.append(["Period", "Exposure, SAR million"])
    exposure.append(["Q1 2026", 1000])
    exposure.append(["Q2 2026", 1050])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep", action="store_true",
                        help="leave the workspace in the database afterwards")
    args = parser.parse_args()

    from backend.config import settings
    from backend.playbook import provider

    state = provider.status()
    print("Playbook live vertical slice")
    print("=" * 72)
    if not state.configured:
        print(f"CANNOT RUN: {state.reason}")
        print("Live generation is therefore UNVERIFIED, not passed.")
        return 2
    if not settings.has_database:
        print("CANNOT RUN: no platform database is configured.")
        return 2

    print(f"provider={state.provider}  configured_model="
          f"{state.model or '(provider default)'}"
          f"{'  (inherited)' if state.inherited else ''}")
    print("-" * 72)

    from backend.db.engine import get_session
    from backend.playbook import repository as repo
    from backend.playbook import store
    from backend.playbook import workspace_service as service
    from backend.playbook.fixtures import ecl_oracle as oracle
    from backend.playbook.ingest import docx_reader, pdf_reader

    scope = repo.Scope(tenant="live-slice")
    record: dict = {"ran_at": datetime.now(UTC).isoformat(),
                    "configured_model": state.model}

    # ---------------------------------------------------------------- upload
    with get_session() as session:
        ws = repo.create_workspace(
            session, scope, title="IFRS 9 Committee Report — Q2 2026",
            document_family="ifrs9_committee_report")
        workspace_id = ws.id
        prior = service.add_source(session, scope, workspace_id,
                                   filename="q1-committee-report.docx",
                                   content=_prior_report(),
                                   source_role="previous_report")
        results = service.add_source(session, scope, workspace_id,
                                     filename="q2-results.xlsx",
                                     content=_results_workbook(),
                                     source_role="results")
        check("the prior report parsed", prior.status in ("parsed", "partial"),
              prior.status)
        check("the results workbook parsed",
              results.status in ("parsed", "partial"), results.status)
        source_ids = [prior.id, results.id]

    # -------------------------------------------------------------- generate
    with get_session() as session:
        ledger = service.ledger_for(session, scope, workspace_id,
                                    source_ids=source_ids,
                                    calculations=list(oracle.headline().values()))
        check("the ledger carries located evidence", len(ledger.items) > 3,
              f"{len(ledger.items)} items")

        outcome = service.author_document(
            session, scope, workspace_id,
            instruction=(
                "Update the attached Q1 2026 committee report for Q2 2026 using "
                "the attached results workbook. Keep the prior-period comparison. "
                "Use only the figures in the evidence."
            ),
            ledger=ledger,
            title="IFRS 9 Committee Report — Q2 2026",
            formats=["docx", "pdf"],
        )
        v1_id, artifact_id = outcome.version_id, outcome.artifact_id
        record["model_served"] = outcome.model_served
        record["request_ids_v1"] = outcome.request_ids
        record["renderer_v1"] = outcome.renderer
        record["downgraded"] = bool(outcome.notes and any(
            "rather than the configured" in n for n in outcome.notes))

        check("a version was written", outcome.version == 1)
        check("the model served is recorded", bool(outcome.model_served),
              outcome.model_served)
        check("no silent downgrade", not record["downgraded"])
        check("DOCX and PDF were both produced",
              set(outcome.files) == {"docx", "pdf"})
        check("every file passed validation",
              all(v.ok for v in outcome.validations.values()),
              "; ".join(i for v in outcome.validations.values() for i in v.issues))

        docx_text = " ".join(
            c.text + " " + " ".join(str(x) for row in c.data.get("rows", [])
                                    for x in row)
            for c in docx_reader.read(outcome.files["docx"]).chunks)
        pdf_text = " ".join(c.text for c in
                            pdf_reader.read(outcome.files["pdf"]).chunks)
        for figure in ("22.77", "19.20"):
            check(f"the Word file states {figure}", figure in docx_text)
            check(f"the PDF states {figure}", figure in pdf_text)
        check("no figure was invented",
              outcome.grounding is not None and outcome.grounding.ok,
              outcome.grounding.note() if outcome.grounding else "")

        rows = repo.files(session, v1_id)
        for row in rows:
            content = store.read(row.bytes_path)
            check(f"the persisted {row.format} is the exact bytes served",
                  store.sha256(content) == row.sha256)
        record["v1_files"] = [{"format": r.format, "bytes": r.size_bytes,
                               "sha256": r.sha256} for r in rows]

    # ----------------------------------------- reopen in a brand new session
    with get_session() as session:
        reopened = repo.get_workspace(session, scope, workspace_id)
        versions = repo.versions(session, artifact_id)
        check("the workspace reopens in a new session", reopened.id == workspace_id)
        check("version 1 is there after reopening", len(versions) == 1)
        v1_hash = versions[0].content_hash
        v1_text = " ".join(
            b.get("text", "") for s in versions[0].content.get("sections", [])
            for b in s.get("blocks", []))

    # ------------------------------------------------------ scoped revision
    with get_session() as session:
        ledger = service.ledger_for(session, scope, workspace_id,
                                    source_ids=source_ids,
                                    calculations=list(oracle.headline().values()))
        from backend.playbook import prompts

        revision = service.author_document(
            session, scope, workspace_id,
            instruction=prompts.task(
                "edit",
                scope="the executive summary",
                instruction=("Make it more concise and more direct, in a formal "
                             "committee register."),
            ),
            ledger=ledger,
            title="IFRS 9 Committee Report — Q2 2026",
            formats=["docx", "pdf"],
            artifact_id=artifact_id,
            base_version_id=v1_id,
            change_summary="Sharpened the executive summary.",
        )
        record["request_ids_v2"] = revision.request_ids
        check("a second version was written", revision.version == 2)
        versions = repo.versions(session, artifact_id)
        check("version 1 still exists", len(versions) == 2)
        check("the two versions genuinely differ",
              versions[1].content_hash != v1_hash)
        check("version 1 is unchanged",
              versions[0].content_hash == v1_hash)

        v2_text = revision.document.plain_text() if revision.document else ""
        for figure in ("22.77",):
            check(f"the revision preserved the figure {figure}",
                  figure in v2_text)
        check("the revision did not invent a figure",
              revision.grounding is not None and revision.grounding.ok)
        record["v2_files"] = [{"format": r.format, "bytes": r.size_bytes}
                              for r in repo.files(session, revision.version_id)]
        del v1_text

    if not args.keep:
        with get_session() as session:
            from backend.models.playbook import PlaybookWorkspace

            row = session.get(PlaybookWorkspace, workspace_id)
            if row is not None:
                session.delete(row)

    # ------------------------------------------- the rest of the live suite
    # The slice above is one vertical journey. These are the remaining
    # acceptance criteria that need a provider, defined in production code so
    # a deployment can run them too.
    from backend.validation import live_playbook

    print("-" * 72)
    print(f"Live suite: {len(live_playbook.CHECKS)} checks, "
          f"about {live_playbook.ESTIMATED_CALLS} provider calls")
    suite = live_playbook.run_all()
    for outcome in suite.outcomes:
        which = next(c for c in live_playbook.CHECKS if c.id == outcome.check)
        check(f"[{which.requirement}] {which.title}", outcome.passed,
              outcome.detail)
    record["live_suite"] = suite.to_dict()

    record["checks_passed"] = len(ok)
    record["checks_failed"] = len(bad)
    record["result"] = "PASS" if not bad else "FAIL"
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")

    print("-" * 72)
    print(f"{len(ok)} passed, {len(bad)} failed. Evidence: "
          f"{EVIDENCE.relative_to(REPO)}")
    if bad:
        for line in bad:
            print(f"  FAILED: {line}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
