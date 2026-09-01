"""
Part G acceptance: regulatory circular knowledge and the human teaching
corpus. §5, §44.

Every test here drives the real objects — extraction over real bytes, the real
store on a temporary root, the real service against the real database. None of
them asserts that a function was called.

The rule the whole area works under, and the one most of these tests are
about: **a corpus that has been uploaded and extracted is not knowledge.** A
rule reaches an answer through a named SME's approval and an activated
Regulatory Knowledge Release, and every shortcut past that is a test here.
"""

from __future__ import annotations

import tempfile
import uuid
from datetime import date

import pytest

from backend.regulatory import extract as ex
from backend.regulatory import knowledge as kn
from backend.regulatory import release as rl
from backend.regulatory import schema as rs
from backend.regulatory import store as stor
from backend.teaching import importer as im
from tests.conftest import database_available

# ---------------------------------------------------------------- fixtures

CIRCULAR_2025 = b"""SAMA Circular 41042432
Prudential requirements for expected credit loss

4. Scope
4.1 This circular shall apply to all licensed banks operating in the Kingdom.
4.2 A bank must maintain expected credit loss coverage of at least 1.5 % of
gross exposure at default for Stage 2 facilities.
4.3 For the purposes of this circular, significant increase in credit risk
means a downgrade of two or more internal grades since origination.
4.4 This requirement shall not apply to facilities guaranteed by the
Government, except where the guarantee has expired.
5. Reporting
5.1 A bank shall report its coverage within 30 days of each quarter end.
"""

CIRCULAR_2026 = b"""SAMA Circular 44011111
Revised expected credit loss coverage
3. Coverage
3.1 A bank must maintain expected credit loss coverage of at least 2.0 % of
gross exposure at default for Stage 2 facilities.
"""


@pytest.fixture(autouse=True)
def _isolated_store(monkeypatch):
    """Every test writes its originals into its own directory.

    A shared store would make one test's uploads visible to the next, which is
    exactly the class of defect this phase has already had to fix twice.
    """
    monkeypatch.setenv("CREDITPROBE_REGULATORY_STORE", tempfile.mkdtemp())


# ------------------------------------------------------------- extraction


def test_a_circular_is_read_into_sections_and_candidate_rules():
    found = ex.extract(CIRCULAR_2025, rs.TXT,
                       concepts=("expected credit loss",
                                 "exposure at default"))

    assert found.status == rs.EXTRACTED
    numbers = {s.number for s in found.sections}
    assert {"4", "4.1", "4.2", "4.3", "4.4", "5", "5.1"} <= numbers

    kinds = {r.kind for r in found.rules}
    assert rs.OBLIGATION in kinds
    assert rs.DEFINITION in kinds
    assert rs.THRESHOLD in kinds
    assert rs.EXCEPTION in kinds


def test_a_heading_and_a_provision_are_told_apart():
    """"4. Scope" is a heading; "4.1 A bank shall…" is the provision itself.

    Reading every numbered line as a heading put the provision INTO the
    heading and left the section text empty — so a circular with five
    obligations produced five sections and zero rules, and the corpus looked
    structured and said nothing.
    """
    found = ex.extract(CIRCULAR_2025, rs.TXT)
    by_number = {s.number: s for s in found.sections}

    assert by_number["4"].heading == "Scope"
    assert by_number["4"].text == ""
    assert by_number["4.2"].heading == ""
    assert "must maintain" in by_number["4.2"].text


def test_a_percentage_threshold_is_extracted_with_its_unit():
    """The unit boundary bug: written as `(%|per cent|…)\\b`, every threshold
    ending in `%` matched nothing, because `\\b` after a non-word character
    needs a word character next and "1.5 % of" has a space there."""
    found = ex.extract(CIRCULAR_2025, rs.TXT)
    thresholds = [r for r in found.rules if r.kind == rs.THRESHOLD]

    percentages = [r for r in thresholds if r.unit == "%"]
    assert percentages, "no percentage threshold was extracted"
    assert percentages[0].value == pytest.approx(1.5)
    assert any(r.unit == "days" and r.value == 30 for r in thresholds)


def test_every_candidate_rule_says_where_it_came_from_and_why():
    """A rule with no page and no section is a claim, not a citation. A rule
    with no reason is something a reviewer cannot judge."""
    found = ex.extract(CIRCULAR_2025, rs.TXT)

    for rule in found.rules:
        assert rule.section_number or rule.page
        assert rule.because
        assert rule.status == rs.CANDIDATE
        assert 0 < rule.confidence <= 1


def test_an_unreadable_format_is_a_status_rather_than_an_empty_document():
    """A circular with no rules and a circular nobody could read look
    identical in a corpus, and only one of them is a finding."""
    found = ex.extract(b"anything", "DWG")

    assert found.status == rs.EXTRACTION_UNAVAILABLE
    assert found.rules == []
    assert "not a format CreditProbe reads" in found.because


def test_a_page_with_no_text_is_marked_needs_ocr():
    found = ex.extract(b"   \n  \n", rs.TXT)

    assert found.pages[0].needs_ocr is True


def test_availability_reports_what_this_deployment_cannot_do():
    found = ex.availability()

    assert set(found["formats"]) == set(rs.FORMATS)
    assert isinstance(found["ocr"], bool)
    if not found["ocr"]:
        assert "NEEDS_OCR" in found["ocr_note"]


def test_csv_xlsx_html_and_docx_all_have_an_extractor():
    """§5 names the formats. A format with no extractor is a document whose
    obligations are invisible."""
    for name in rs.FORMATS:
        assert name in ex._EXTRACTORS


def test_html_tags_do_not_become_obligations():
    page = (b"<html><head><style>.a{color:red}</style></head><body>"
            b"<p>4.1 A bank shall report within 30 days of quarter end.</p>"
            b"</body></html>")
    found = ex.extract(page, rs.HTML)

    assert "color:red" not in found.text
    assert "A bank shall report" in found.text


# ------------------------------------------------------------------ store


def test_an_original_is_written_once_under_its_hash():
    first = stor.save(CIRCULAR_2025, filename="c.pdf", tenant="bank-a")
    second = stor.save(CIRCULAR_2025, filename="c.pdf", tenant="bank-a")

    assert first.content_hash == second.content_hash
    assert first.already_present is False
    assert second.already_present is True
    assert stor.usage("bank-a")["originals"] == 1


def test_the_hash_proves_the_bytes_have_not_changed():
    stored = stor.save(CIRCULAR_2025, filename="c.pdf", tenant="bank-a")
    assert stor.verify(stored.content_hash, tenant="bank-a") is True

    stored.path.write_bytes(b"edited in place")
    assert stor.verify(stored.content_hash, tenant="bank-a") is False


def test_one_tenants_original_is_not_reachable_from_another():
    stored = stor.save(CIRCULAR_2025, filename="c.pdf", tenant="bank-a")

    assert stor.locate(stored.content_hash, tenant="bank-b") is None
    with pytest.raises(rs.RegulatoryError):
        stor.read(stored.content_hash, tenant="bank-b")


def test_a_tenant_id_cannot_walk_out_of_the_store():
    stored = stor.save(b"x", filename="c.pdf", tenant="../../etc")

    assert ".." not in str(stored.path)
    assert str(stor.root()) in str(stored.path)


def test_an_empty_or_oversized_file_is_refused():
    with pytest.raises(rs.RegulatoryError):
        stor.save(b"", filename="c.pdf")
    with pytest.raises(rs.RegulatoryError):
        stor.save(b"x" * (stor.MAX_BYTES + 1), filename="c.pdf")


# ------------------------------------------------------------- validation


def _circular(**fields) -> rs.Circular:
    base = dict(circular_id="c1", title="T", regulator="SAMA",
                reference="41042432", effective=date(2025, 1, 1),
                file_format=rs.TXT, content_hash="a" * 64)
    base.update(fields)
    return rs.Circular(**base)


def test_a_circular_with_no_effective_date_is_reported_not_stored_quietly():
    problems = rs.validate(_circular(effective=None))

    assert any("effective date" in p for p in problems)


def test_a_circular_cannot_take_effect_before_it_was_issued():
    problems = rs.validate(_circular(issued=date(2025, 6, 1),
                                     effective=date(2025, 1, 1)))

    assert any("before it was issued" in p for p in problems)


def test_in_force_fails_closed_when_there_is_no_effective_date():
    """A circular that does not say when it starts is not treated as having
    always applied."""
    assert _circular(effective=None).in_force_on(date(2030, 1, 1)) is False


# ------------------------------------------------- supersession and as-of


def _corpus() -> list[rs.Circular]:
    old = _circular(circular_id="c-old", reference="41042432",
                    effective=date(2025, 1, 1), status=rs.APPROVED,
                    confidentiality=rs.PUBLIC)
    new = _circular(circular_id="c-new", reference="44011111",
                    effective=date(2026, 1, 1), status=rs.APPROVED,
                    confidentiality=rs.PUBLIC, supersedes=["41042432"])
    for circular, value in ((old, 1.5), (new, 2.0)):
        circular.rules = [rs.Rule(
            rule_id="r1", kind=rs.THRESHOLD,
            text=("A bank must maintain expected credit loss coverage of at "
                  f"least {value} % of gross exposure at default."),
            section_number="4.2", page=1, value=value, unit="%",
            concepts=["expected credit loss"], status=rs.APPROVED,
            reviewer="sme")]
    return [old, new]


def test_a_superseded_circular_stays_retrievable_for_the_dates_it_covered():
    """A restatement of a 2025 position has to quote the 2025 rule. Deleting
    the replaced circular would make every historical restatement uncitable.
    """
    corpus = kn.apply_supersession(_corpus())
    old = next(c for c in corpus if c.reference == "41042432")

    assert old.status == rs.SUPERSEDED
    assert old.superseded_by == "44011111"
    assert old.in_force_on(date(2025, 6, 30)) is True
    assert old.in_force_on(date(2026, 6, 30)) is False


def test_retrieval_answers_as_of_the_reporting_date_not_today():
    corpus = kn.apply_supersession(_corpus())
    question = "What expected credit loss coverage is required?"

    then = kn.retrieve(corpus, question, when=date(2025, 6, 30),
                       roles=frozenset({rs.PUBLIC}))
    now = kn.retrieve(corpus, question, when=date(2026, 6, 30),
                      roles=frozenset({rs.PUBLIC}))

    assert [h.rule.value for h in then.hits] == [1.5]
    assert [h.rule.value for h in now.hits] == [2.0]


def test_every_hit_carries_a_citation_that_resolves_to_a_document():
    corpus = kn.apply_supersession(_corpus())
    found = kn.retrieve(corpus, "expected credit loss coverage",
                        when=date(2025, 6, 30), roles=frozenset({rs.PUBLIC}))

    for hit in found.hits:
        assert hit.citation.reference
        assert hit.citation.content_hash
        assert hit.citation.effective
        assert "SAMA" in hit.citation.sentence()


def test_two_rules_in_force_on_the_same_date_are_a_declared_conflict():
    """CreditProbe does not choose between them. Resolving a regulatory
    conflict is a legal opinion, not a retrieval strategy."""
    corpus = _corpus()  # supersession deliberately NOT applied
    clashes = kn.conflicts(corpus, date(2026, 6, 30))

    assert len(clashes) == 1
    assert {clashes[0].left_value, clashes[0].right_value} == {1.5, 2.0}
    assert "does not choose" in clashes[0].sentence()


def test_supersession_is_only_ever_explicit():
    """A circular is never inferred to replace another because it covers the
    same ground: regulators restate far more often than they replace, and a
    guess silently removes a rule that is still in force."""
    corpus = _corpus()
    corpus[1].supersedes = []

    assert kn.supersessions(corpus) == []


def test_a_class_the_caller_may_not_read_is_excluded_and_reported():
    corpus = _corpus()
    corpus[0].confidentiality = rs.CONFIDENTIAL

    found = kn.retrieve(corpus, "expected credit loss coverage",
                        when=date(2025, 6, 30), roles=frozenset({rs.PUBLIC}))

    assert found.hits == []
    assert found.excluded
    assert "not retrievable for this role" in found.excluded[0]["why"]


def test_an_unapproved_rule_is_never_retrieved():
    corpus = _corpus()
    for circular in corpus:
        for rule in circular.rules:
            rule.status = rs.CANDIDATE

    found = kn.retrieve(corpus, "expected credit loss coverage",
                        when=date(2025, 6, 30), roles=frozenset({rs.PUBLIC}))

    assert found.hits == []


# ---------------------------------------------------------------- release


def test_a_release_cannot_be_built_from_a_corpus_nobody_reviewed():
    corpus = _corpus()
    for circular in corpus:
        for rule in circular.rules:
            rule.status = rs.CANDIDATE

    with pytest.raises(rl.ReleaseError) as caught:
        rl.build(corpus, release_id="r1", created_by="a")
    assert "no rule has been approved" in str(caught.value)


def test_a_review_needs_a_named_reviewer_and_an_assessment():
    rule = rs.Rule(rule_id="r1", kind=rs.OBLIGATION, text="x")

    for kwargs in ({"reviewer": "", "note": "fine"},
                   {"reviewer": "sme", "note": ""}):
        with pytest.raises(rl.ReleaseError):
            rl.review(rule, decision=rl.APPROVE, **kwargs)


def test_an_amendment_keeps_what_the_rule_used_to_say():
    rule = rs.Rule(rule_id="r1", kind=rs.OBLIGATION, text="clipped short")
    rl.review(rule, decision=rl.AMEND, reviewer="sme",
              note="the sentence was clipped", text="the full sentence")

    assert rule.text == "the full sentence"
    assert "clipped short" in rule.review_note
    assert rule.status == rs.REVIEWED


def test_the_only_reviewer_cannot_also_approve_the_release():
    corpus = _corpus()
    release = rl.build(corpus, release_id="r1", created_by="sme")

    with pytest.raises(rl.ReleaseError) as caught:
        rl.activate(release, approver="sme")
    assert "second pair of eyes" in str(caught.value)


def test_activating_a_release_rolls_the_previous_one_back():
    corpus = _corpus()
    first = rl.activate(rl.build(corpus, release_id="r1", created_by="a"),
                        approver="cro")
    second = rl.activate(rl.build(corpus, release_id="r2", created_by="a"),
                         approver="cro", current=first)

    assert first.status == rl.ROLLED_BACK
    assert second.status == rl.ACTIVE
    assert second.replaces == "r1"


def test_a_rollback_needs_a_reason():
    corpus = _corpus()
    first = rl.activate(rl.build(corpus, release_id="r1", created_by="a"),
                        approver="cro")
    second = rl.activate(rl.build(corpus, release_id="r2", created_by="a"),
                         approver="cro", current=first)

    with pytest.raises(rl.ReleaseError):
        rl.rollback(second, first, approver="cro", why="")


def test_two_releases_with_the_same_knowledge_have_the_same_fingerprint():
    """So a rollback is recognisable as a return to a known state rather than
    as a new and unproven one."""
    corpus = _corpus()
    first = rl.build(corpus, release_id="r1", created_by="a")
    second = rl.build(corpus, release_id="r2", created_by="b")

    assert first.fingerprint == second.fingerprint


def test_the_review_queue_puts_thresholds_first():
    corpus = _corpus()
    corpus[0].rules = [
        rs.Rule(rule_id="d", kind=rs.DEFINITION, text="means x",
                status=rs.CANDIDATE),
        rs.Rule(rule_id="t", kind=rs.THRESHOLD, text="at least 1.5 %",
                value=1.5, unit="%", status=rs.CANDIDATE),
        rs.Rule(rule_id="o", kind=rs.OBLIGATION, text="shall do x",
                status=rs.CANDIDATE),
    ]
    rows = rl.review_queue(corpus[:1])

    assert [r["rule"]["rule_id"] for r in rows][0] == "t"


# -------------------------------------------------------------- assurance


def test_a_regulatory_answer_with_no_active_release_fails_its_own_gate():
    from backend.regulatory import assurance as ra

    corpus = _corpus()
    answer = kn.retrieve(corpus, "coverage", when=date(2025, 6, 30),
                         roles=frozenset({rs.PUBLIC}))
    record = ra.assess(answer, corpus, when=date(2025, 6, 30), release=None)

    assert record.ok is False
    assert "release_active" in [c.name for c in record.failures]


def test_an_unverifiable_original_is_not_reported_as_verified():
    """A check that did not run is not a check that passed."""
    from backend.regulatory import assurance as ra

    corpus = _corpus()
    answer = kn.retrieve(corpus, "coverage", when=date(2025, 6, 30),
                         roles=frozenset({rs.PUBLIC}))
    record = ra.assess(answer, corpus, when=date(2025, 6, 30),
                       release=None, verify_original=None)

    check = next(c for c in record.checks if c.name == "original_intact")
    assert check.outcome == ra.NOT_APPLICABLE
    assert "did not run is not a check that passed" in check.detail


def test_an_edited_original_fails_the_critical_gate():
    from backend.regulatory import assurance as ra

    corpus = _corpus()
    answer = kn.retrieve(corpus, "coverage", when=date(2025, 6, 30),
                         roles=frozenset({rs.PUBLIC}))
    record = ra.assess(answer, corpus, when=date(2025, 6, 30),
                       release=type("R", (), {"release_id": "r1",
                                              "status": "ACTIVE"})(),
                       verify_original=lambda h, tenant="": False)

    assert record.ok is False
    assert "original_intact" in [c.name for c in record.critical_failures]


def test_the_critical_gates_are_the_ones_named():
    """Five, not four. `release_active` was MANDATORY first, which made an
    answer with no release behind it report `ok` — a corpus nobody had
    reviewed, passing its own gate."""
    from backend.regulatory import assurance as ra

    assert set(ra.CRITICAL_CHECKS) == {"cited", "in_force", "reviewed",
                                       "original_intact", "release_active"}


# ------------------------------------------------- the human teaching corpus


def _workbook(rows: int) -> bytes:
    lines = ["question,expected_answer,concepts,datasets"]
    for index in range(rows):
        lines.append(
            f"What is total expected credit loss for segment {index}?,"
            f"Report one row for segment {index} with the summed expected "
            f"credit loss.,expected credit loss,ifrs9_staging")
    return "\n".join(lines).encode()


def test_a_600_case_workbook_imports_as_a_batch():
    """§5 asks for 500+ case batch support, and §44 for a 600-case
    workbook."""
    report = im.preview(_workbook(600), im.CSV, batch="b")

    assert report.fatal == ""
    assert len(report.rows) == 600
    assert report.counted()[im.ACCEPTED] == 600


def test_a_workbook_over_the_batch_limit_is_refused_with_the_number():
    report = im.preview(_workbook(im.MAX_ROWS + 1), im.CSV, batch="b")

    assert str(im.MAX_ROWS) in report.fatal


def test_a_clients_own_column_names_are_matched_by_meaning():
    """An import that only works on the file we asked for is an import that
    gets used once."""
    for header, expected in (("Prompt", "question"),
                             ("User Question", "question"),
                             ("Correct Answer", "expected_answer"),
                             ("Model answer", "expected_answer"),
                             ("Pitfall", "forbidden"),
                             ("SME", "author")):
        assert im.normalise_header(header) == expected


def test_a_column_nothing_was_read_from_is_reported():
    """A column called "expected_result" that nobody mapped is 500 expected
    answers silently dropped."""
    payload = b"question,expected_answer,expected_result\nWhat is ECL?,Report the total expected credit loss.,something\n"
    report = im.preview(payload, im.CSV, batch="b")

    assert "expected_result" in report.unmapped_columns
    assert "expected_result" in report.sentence()


def test_a_duplicate_is_merged_and_a_conflict_is_not():
    payload = (b"question,expected_answer\n"
               b"What is total ECL?,Report the total expected credit loss.\n"
               b"What is total ECL?,Report the total expected credit loss.\n"
               b"What is total ECL?,Report the whole-book average instead.\n")
    report = im.preview(payload, im.CSV, batch="b")
    verdicts = [r.verdict for r in report.rows]

    assert verdicts == [im.ACCEPTED, im.DUPLICATE, im.CONFLICT]
    assert report.rows[2].clashes_with == 1
    assert report.rows[2].other_answer


def test_an_imported_case_arrives_awaiting_review_and_is_not_retrievable():
    """§6 depends on this. A bank that uploads 600 reviewed answers has 600
    cases awaiting review, not 600 approved ones."""
    from backend.teaching import status as st

    report = im.preview(_workbook(3), im.CSV, batch="b")

    for row in report.importable:
        assert row.case.review_status == st.SME_REVIEW_REQUIRED
        assert row.case.authoring_method == st.HUMAN
        assert st.retrievable(row.case.review_status).ok is False


def test_a_clients_corpus_is_marked_client_sensitive():
    from backend.teaching import status as st

    report = im.preview(_workbook(1), im.CSV, batch="b")

    assert report.importable[0].case.data_sensitivity == st.CLIENT


def test_the_error_workbook_carries_the_original_row_numbers():
    """The person fixing row 287 needs to find row 287."""
    payload = (b"question,expected_answer\n"
               b"What is total ECL?,Report the total expected credit loss.\n"
               b"x,\n")
    report = im.preview(payload, im.CSV, batch="b")
    errors = im.error_workbook(report)

    assert [e["row"] for e in errors] == [2]
    assert errors[0]["problem"]


def test_the_template_and_the_importer_cannot_drift_apart():
    """The file a client fills in and the contract it is checked against are
    generated from the same tuple."""
    assert {r["column"] for r in im.template_rows()} == set(
        im.TEMPLATE_COLUMNS)
    assert set(im.REQUIRED_COLUMNS) <= set(im.TEMPLATE_COLUMNS)


def test_jsonl_and_csv_read_the_same_corpus():
    rows = [b'{"question": "What is total ECL?", "expected_answer": "Report '
            b'the total expected credit loss."}']
    report = im.preview(b"\n".join(rows), im.JSONL, batch="b")

    assert report.counted()[im.ACCEPTED] == 1


def test_a_malformed_jsonl_line_names_the_line():
    report = im.preview(b'{"question": "x"}\nnot json\n', im.JSONL, batch="b")

    assert "line 2" in report.fatal


# ----------------------------------------------------- the service, end to end


db = pytest.mark.skipif(not database_available(),
                        reason="Part G's service needs the platform database")


@db
def test_the_whole_regulatory_lifecycle():
    """Upload, dedupe, extract, review, approve, release, activate, ask.

    One test rather than eight because the lifecycle IS the feature: each
    step is only meaningful as a gate on the next, and a suite that proved
    each in isolation would not prove that the gates are in the right order.
    """
    from backend.db.engine import get_session
    from backend.services import regulatory as svc

    tenant = f"t-{uuid.uuid4().hex[:8]}"
    with get_session() as session:
        first = svc.upload(
            session, CIRCULAR_2025, filename="c1.txt",
            title="ECL prudential requirements", regulator="SAMA",
            reference=f"41042432-{tenant}", effective="2025-01-01",
            tenant=tenant, confidentiality=rs.PUBLIC, uploaded_by="tester",
            concepts=("expected credit loss", "exposure at default"))
        assert first["status"] == rs.EXTRACTED
        assert first["rule_counts"][rs.THRESHOLD] >= 1

        again = svc.upload(
            session, CIRCULAR_2025, filename="c1.txt", title="x",
            regulator="SAMA", reference=f"41042432-{tenant}",
            effective="2025-01-01", tenant=tenant)
        assert again["already_present"] is True

        # Nothing is retrievable before a release exists, and the answer says
        # exactly why rather than looking like an empty corpus.
        empty = svc.ask(session, "What ECL coverage is required?",
                        when=date(2025, 6, 30), tenant=tenant)
        assert empty["hits"] == []
        assert "No Regulatory Knowledge Release is active" in empty["because"]
        assert empty["assurance"]["ok"] is False

        with pytest.raises(rl.ReleaseError):
            svc.build_release(session, created_by="a", tenant=tenant)

        circular_id = first["circular_id"]
        for rule in svc.document(session, circular_id).body["rules"]:
            svc.review_rule(session, circular_id, rule["rule_id"],
                            decision=rl.APPROVE, reviewer="sme@bank",
                            note="Checked against the circular.")
        svc.approve_document(session, circular_id, approver="head@bank",
                             note="Complete and correct.")

        built = svc.build_release(session, created_by="head@bank",
                                  tenant=tenant, note="first")
        with pytest.raises(rl.ReleaseError):
            svc.activate_release(session, built["release_id"],
                                 approver="sme@bank")
        active = svc.activate_release(session, built["release_id"],
                                      approver="cro@bank")
        assert active["status"] == rl.ACTIVE

        answer = svc.ask(
            session,
            "What expected credit loss coverage is required for Stage 2?",
            when=date(2025, 6, 30), tenant=tenant)
        assert answer["hits"]
        assert answer["assurance"]["ok"] is True
        assert answer["assurance"]["critical_failures"] == []
        assert all(h["citation"]["content_hash"] for h in answer["hits"])

        report = svc.corpus_report(session, tenant=tenant)
        assert report["circulars"] == 1
        assert report["approved_rules"] > 0
        assert report["active_release"] == built["release_id"]
        assert "approved by a regulatory SME" in report["honest_sentence"]

        session.rollback()


@db
def test_a_document_cannot_be_approved_before_every_rule_is_reviewed():
    from backend.db.engine import get_session
    from backend.services import regulatory as svc

    tenant = f"t-{uuid.uuid4().hex[:8]}"
    with get_session() as session:
        found = svc.upload(
            session, CIRCULAR_2025, filename="c.txt", title="T",
            regulator="SAMA", reference=f"REF-{tenant}",
            effective="2025-01-01", tenant=tenant)
        with pytest.raises(svc.RegulatoryServiceError) as caught:
            svc.approve_document(session, found["circular_id"],
                                 approver="a", note="looks fine")
        assert "REVIEWED" in str(caught.value)
        session.rollback()


@db
def test_an_approval_without_an_assessment_is_refused():
    from backend.db.engine import get_session
    from backend.services import regulatory as svc

    tenant = f"t-{uuid.uuid4().hex[:8]}"
    with get_session() as session:
        found = svc.upload(
            session, CIRCULAR_2025, filename="c.txt", title="T",
            regulator="SAMA", reference=f"REF-{tenant}",
            effective="2025-01-01", tenant=tenant)
        with pytest.raises(svc.RegulatoryServiceError):
            svc.approve_document(session, found["circular_id"],
                                 approver="a", note="")
        session.rollback()
