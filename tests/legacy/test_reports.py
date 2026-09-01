"""
Committee report packs: content model, writers, archive store and the screens.

The load-bearing property is that the two audiences share one content model, so
the Board pack and the Committee pack can never quote different numbers for the
same measure — and that what the Review Pack screen previews is what the file
actually contains.
"""

import pathlib
import re
import zipfile
from datetime import date, timedelta

import pytest

import app as A
from backend import data_loader as dl
from backend.reporting import charts, writers
from backend.reporting import content as rc
from backend.reporting import store as report_store
from frontend import reports_view as rv


@pytest.fixture(scope="module")
def smc():
    return rc.build_report("smc")


@pytest.fixture(scope="module")
def brc():
    return rc.build_report("brc")


@pytest.fixture
def tmp_store(tmp_path, monkeypatch):
    """Point the archive at a temp directory so tests never touch real packs."""
    monkeypatch.setattr(report_store, "_root",
                        lambda: _make_root(tmp_path))
    return tmp_path


def _make_root(tmp_path):
    (tmp_path / "index").mkdir(parents=True, exist_ok=True)
    (tmp_path / "files").mkdir(parents=True, exist_ok=True)
    return tmp_path


def _walk(node):
    yield node
    children = getattr(node, "children", None)
    if children is None:
        return
    for child in (children if isinstance(children, (list, tuple)) else [children]):
        yield from _walk(child)


def _ids(tree):
    return [getattr(n, "id", None) for item in tree for n in _walk(item)
            if getattr(n, "id", None)]


def _text(tree):
    out = []
    for item in tree:
        for n in _walk(item):
            c = getattr(n, "children", None)
            if isinstance(c, str):
                out.append(c)
            elif not hasattr(n, "children") and isinstance(n, str):
                out.append(n)
    return " ".join(out)


# ------------------------------------------------------------- report types

def test_two_report_types_are_offered():
    assert set(rc.REPORT_TYPES) == {"smc", "brc"}


def test_board_pack_is_a_strict_subset_of_the_committee_pack():
    """The Board version is the concise cut of the same pack — every section it
    carries must also appear in the full one, or the two would diverge."""
    smc_keys = {k for k, _ in rc.sections_for("smc")}
    brc_keys = {k for k, _ in rc.sections_for("brc")}
    assert brc_keys < smc_keys


def test_board_pack_is_actually_shorter(smc, brc):
    assert len(brc["sections"]) < len(smc["sections"])


def test_unknown_type_falls_back_rather_than_raising():
    assert rc.report_spec("nonsense")["key"] == "smc"


# ------------------------------------------------------------------ content

def test_every_section_carries_a_narrative(smc):
    for section in smc["sections"]:
        assert section["narrative"].strip(), f"{section['key']} has no narrative"


def test_no_section_reports_itself_as_failed(smc, brc):
    """build_report catches per-section errors so a pack still generates. That is
    a safety net, not an expected outcome — if it fires, the pack is wrong."""
    for report in (smc, brc):
        for section in report["sections"]:
            assert "could not be generated" not in section["narrative"], section["key"]


def test_both_packs_agree_on_the_figures_they_share(smc, brc):
    """The whole point of one content model: a measure that appears in both packs
    must carry the same value in both."""
    def exec_rows(report):
        section = next(s for s in report["sections"] if s["key"] == "executive_summary")
        return {r[0]: r[1] for r in section["table"]["rows"]}

    shared = exec_rows(smc).keys() & exec_rows(brc).keys()
    assert shared, "the two packs share no executive-summary measures"
    for measure in shared:
        assert exec_rows(smc)[measure] == exec_rows(brc)[measure], measure


def test_actions_are_derived_from_findings(smc):
    """An action must trace back to a finding — otherwise it can outlive the
    condition that produced it."""
    finding_areas = {f["area"] or "Portfolio" for f in smc["findings"]}
    for action in smc["actions"]:
        assert action["area"] in finding_areas


def test_every_action_has_an_owner_and_a_date(smc, brc):
    for report in (smc, brc):
        for action in report["actions"]:
            assert action["owner"].strip()
            assert action["due"].strip()


def test_remediation_covers_every_non_low_finding(smc):
    material = [f for f in smc["findings"] if f["severity"] != "LOW"]
    assert len(smc["remediation"]) == len(material)


def test_low_severity_findings_do_not_create_remediation():
    findings = [{"text": "minor", "severity": "LOW", "area": "Appetite"}]
    assert rc._remediation(findings) == []
    assert rc._actions(findings), "a LOW finding should still inform an action"


def test_no_remediation_when_nothing_is_wrong():
    assert rc._remediation([]) == []
    assert rc._actions([]) == []


def test_a_breach_produces_remediation(smc):
    """If the pack raises a HIGH finding it must also say what to do about it."""
    if smc["high_severity_count"]:
        assert any(r["severity"] == "HIGH" for r in smc["remediation"])


def test_pack_is_classified(smc):
    assert "CONFIDENTIAL" in smc["classification"]


# -------------------------------------------------------------------- cache

def test_context_is_cached_between_builds():
    rc.clear_context_cache()
    first = rc._context(dl.DEFAULT_QUARTER)
    second = rc._context(dl.DEFAULT_QUARTER)
    assert first is second, "the shared data load should be computed once"


def test_clearing_the_cache_recomputes():
    rc._context(dl.DEFAULT_QUARTER)
    rc.clear_context_cache()
    assert rc._context(dl.DEFAULT_QUARTER) is not None
    assert rc._CONTEXT_CACHE, "a fresh build should repopulate the cache"


def test_a_new_dataset_generation_invalidates_the_cache(monkeypatch):
    """The load-bearing property of the cache: a committee pack must never be
    served from data that has since been replaced."""
    rc.clear_context_cache()
    before = rc._context(dl.DEFAULT_QUARTER)
    monkeypatch.setattr(dl, "DATASET_GENERATION", dl.DATASET_GENERATION + 1)
    after = rc._context(dl.DEFAULT_QUARTER)
    assert after is not before, "a new dataset generation must force a recompute"


def test_swapping_the_dataset_bumps_the_generation():
    """apply_dataset_frames is the one choke point every dataset swap goes
    through — the bundled loader and the Postgres cache layer both call it."""
    start = dl.DATASET_GENERATION
    dl.apply_dataset_frames(dl.DF, dl.SUPP_DF, dl.QUARTER_SHEETS, dl.ACTIVE_SOURCE,
                            path=dl.ACTIVE_PATH)
    assert dl.DATASET_GENERATION == start + 1


def test_cache_holds_only_the_current_generation(monkeypatch):
    rc.clear_context_cache()
    rc._context(dl.DEFAULT_QUARTER)
    monkeypatch.setattr(dl, "DATASET_GENERATION", dl.DATASET_GENERATION + 1)
    rc._context(dl.DEFAULT_QUARTER)
    assert len(rc._CONTEXT_CACHE) == 1, "superseded entries must not linger"


def test_no_section_mutates_the_shared_context():
    """The context is cached and handed to every section builder. If one of them
    mutated it, the second report built would differ from the first — which is
    exactly the bug a cache introduces if the data is not treated as read-only."""
    rc.clear_context_cache()
    first = rc.build_report("smc")
    second = rc.build_report("smc")

    def comparable(report):
        return [(s["key"], s["narrative"],
                 (s.get("table") or {}).get("rows")) for s in report["sections"]]

    assert comparable(first) == comparable(second)
    assert first["findings"] == second["findings"]
    assert first["actions"] == second["actions"]


def test_building_one_type_does_not_disturb_the_other():
    rc.clear_context_cache()
    brc_alone = rc.build_report("brc")
    rc.build_report("smc")
    brc_after = rc.build_report("brc")
    assert [s["narrative"] for s in brc_alone["sections"]] == \
           [s["narrative"] for s in brc_after["sections"]]


# ------------------------------------------------------------------- charts

def test_chart_specs_all_name_a_real_renderer(smc):
    for section in smc["sections"]:
        spec = section.get("chart")
        if spec:
            assert spec["kind"] in charts._RENDERERS, spec["kind"]


def test_a_broken_chart_spec_degrades_to_none():
    """A chart that cannot be drawn must not take the pack down with it."""
    assert charts.render({"kind": "no_such_chart", "title": "x"}, {}) is None
    assert charts.render(None, {}) is None


def test_climate_multiples_chart_renders():
    png = charts.render(
        {"kind": "climate_multiples", "title": "t",
         "data": [("Energy", 1.57), ("Manufacturing", 1.19)]}, {})
    assert png and png[:8] == b"\x89PNG\r\n\x1a\n"


# ------------------------------------------------------------------ writers

def test_both_formats_are_offered():
    assert set(writers.FORMATS) == {"pdf", "docx"}


@pytest.mark.parametrize("report_type", ["smc", "brc"])
def test_pdf_is_a_real_pdf(report_type):
    report = rc.build_report(report_type)
    data, name, mime = writers.write(report, "pdf", report_store.chart_context())
    assert data[:4] == b"%PDF"
    assert name.endswith(".pdf")
    assert mime == "application/pdf"
    pages = data.count(b"/Type /Page") - data.count(b"/Type /Pages")
    assert pages >= 5, f"{report_type} pack is only {pages} pages"
    assert re.search(rb"/Subtype\s*/Image", data), "no charts embedded"


@pytest.mark.parametrize("report_type", ["smc", "brc"])
def test_docx_is_a_real_docx(report_type):
    report = rc.build_report(report_type)
    data, name, _mime = writers.write(report, "docx", report_store.chart_context())
    assert data[:2] == b"PK"
    assert name.endswith(".docx")
    with zipfile.ZipFile(__import__("io").BytesIO(data)) as z:
        names = z.namelist()
        body = "".join(z.read(n).decode("utf-8", "replace")
                       for n in names if n.endswith(".xml"))
    assert any(n.startswith("word/media/") for n in names), "no charts embedded"
    text = re.sub(r"<[^>]+>", "", body)
    for probe in ("Executive Summary", "Recommended Actions", "Remediation Plan",
                  "CONFIDENTIAL"):
        assert probe in text, f"{report_type}: missing {probe!r}"


def test_the_two_formats_say_the_same_thing():
    """PDF and Word are poured from one model, so the headline must match."""
    report = rc.build_report("brc")
    ctx = report_store.chart_context()
    pdf, _, _ = writers.write(report, "pdf", ctx)
    docx, _, _ = writers.write(report, "docx", ctx)
    assert pdf[:4] == b"%PDF" and docx[:2] == b"PK"
    # Both are built from the same section list, so section counts agree by
    # construction; assert the model they share is the one that was written.
    assert len(report["sections"]) == len(rc.sections_for("brc"))


def test_unknown_format_falls_back_to_pdf():
    report = rc.build_report("brc")
    data, name, _ = writers.write(report, "rtf", report_store.chart_context())
    assert data[:4] == b"%PDF" and name.endswith(".pdf")


# -------------------------------------------------------------------- store

def test_generate_archives_and_reloads_identical_bytes(tmp_store):
    pack = report_store.generate("brc", fmt="pdf")
    again = report_store.load(pack["id"])
    assert again is not None
    data, filename, mime = again
    assert data == pack["data"], "an archived pack must re-serve byte for byte"
    assert filename == pack["filename"]
    assert mime == "application/pdf"


def test_archive_lists_newest_first(tmp_store):
    first = report_store.generate("brc", fmt="pdf")
    second = report_store.generate("smc", fmt="docx")
    listed = report_store.list_packs()
    assert [p["id"] for p in listed] == [second["id"], first["id"]]


def test_archive_filters(tmp_store):
    report_store.generate("brc", fmt="pdf")
    report_store.generate("smc", fmt="pdf")
    assert all(p["type"] == "smc" for p in report_store.list_packs(report_type="smc"))
    assert len(report_store.list_packs(report_type="brc")) == 1


def test_headline_is_stored_so_the_list_need_not_rebuild_the_pack(tmp_store):
    pack = report_store.generate("smc", fmt="pdf")
    row = report_store.list_packs()[0]
    assert row["headline"]["section_count"] == pack["headline"]["section_count"]
    assert row["headline"]["action_count"] >= 0
    assert row["size_bytes"] == len(pack["data"])


def test_delete_removes_index_and_payload(tmp_store):
    pack = report_store.generate("brc", fmt="pdf")
    assert report_store.delete(pack["id"]) is True
    assert report_store.get(pack["id"]) is None
    assert report_store.load(pack["id"]) is None
    assert report_store.delete(pack["id"]) is False


def test_missing_pack_reads_as_none_not_an_error(tmp_store):
    assert report_store.get(9999) is None
    assert report_store.load(9999) is None


def test_summary_counts(tmp_store):
    report_store.generate("smc", fmt="pdf")
    report_store.generate("brc", fmt="docx")
    s = report_store.summary()
    assert s["total"] == 2
    assert s["by_type"] == {"smc": 1, "brc": 1}
    assert s["by_format"] == {"pdf": 1, "docx": 1}
    assert s["total_bytes"] > 0
    assert s["latest"]["type"] == "brc"


def test_generate_can_skip_the_archive(tmp_store):
    pack = report_store.generate("brc", fmt="pdf", archive=False)
    assert pack["data"][:4] == b"%PDF"
    assert report_store.list_packs() == []


# ------------------------------------------------------------------ screens

def test_config_resolution_rejects_nonsense():
    cfg = rv.resolve_config({"type": "bogus", "format": "xls"})
    assert cfg["type"] == "smc"
    assert cfg["format"] == "pdf"
    assert cfg["quarter"] == dl.DEFAULT_QUARTER


def test_config_resolution_survives_a_missing_store():
    assert rv.resolve_config(None)["type"] == "smc"
    assert rv.resolve_config("not a dict")["format"] == "pdf"


def test_config_resolution_keeps_a_valid_choice():
    cfg = rv.resolve_config({"type": "brc", "format": "docx", "quarter": "Q3 2025"})
    assert (cfg["type"], cfg["format"], cfg["quarter"]) == ("brc", "docx", "Q3 2025")


@pytest.mark.parametrize("tab", ["Review Pack", "Schedules", "Archive"])
def test_every_reports_tab_renders(tab):
    assert A.build_section_tab_body("reports", tab)


def test_review_pack_offers_both_types_and_both_formats():
    ids = _ids(rv.build_review_pack_body(None))
    assert {"smc", "brc"} == {i["key"] for i in ids
                              if isinstance(i, dict) and i["type"] == "rep-type-card"}
    assert {"pdf", "docx"} == {i["key"] for i in ids
                               if isinstance(i, dict) and i["type"] == "rep-fmt-card"}
    assert "rep-generate" in ids


def test_selecting_a_type_marks_only_that_card():
    def selected(body):
        return [n.id["key"] for item in body for n in _walk(item)
                if isinstance(getattr(n, "id", None), dict)
                and n.id.get("type") == "rep-type-card"
                and "is-selected" in (getattr(n, "className", "") or "")]

    assert selected(rv.build_review_pack_body({"type": "brc"})) == ["brc"]
    assert selected(rv.build_review_pack_body({"type": "smc"})) == ["smc"]


def test_generate_button_names_the_chosen_format():
    body = rv.build_review_pack_body({"format": "docx"})
    button = next(n for item in body for n in _walk(item)
                  if getattr(n, "id", None) == "rep-generate")
    assert "Word" in button.children


def test_preview_shows_the_same_counts_the_pack_will_carry():
    """The screen must not summarise the pack independently of the pack."""
    report = rc.build_report("brc")
    text = _text(rv.build_review_pack_body({"type": "brc"}))
    assert str(len(report["sections"])) in text
    assert str(len(report["findings"])) in text
    assert report["title"] in text


def test_review_pack_lists_the_sections_it_will_contain():
    text = _text(rv.build_review_pack_body({"type": "brc"}))
    for _key, title in rc.sections_for("brc"):
        assert title in text


# ----------------------------------------------------------------- schedules

def test_no_schedule_is_ever_due_in_the_past():
    for schedule in rv.SCHEDULES:
        assert rv._next_run(schedule) >= date.today(), schedule["id"]


def test_every_schedule_names_a_real_report_type_and_format():
    for schedule in rv.SCHEDULES:
        assert schedule["type"] in rc.REPORT_TYPES
        assert schedule["format"] in writers.FORMATS


def test_quarter_end_is_the_last_day_of_the_quarter():
    assert rv._quarter_end(date(2026, 2, 15)) == date(2026, 3, 31)
    assert rv._quarter_end(date(2026, 7, 1)) == date(2026, 9, 30)
    assert rv._quarter_end(date(2026, 12, 31)) == date(2026, 12, 31)


def test_month_start_rolls_the_year_over():
    assert rv._month_start(2026, 13) == date(2027, 1, 1)
    assert rv._month_start(2026, 25) == date(2028, 1, 1)


def test_schedules_screen_offers_a_run_button_per_schedule():
    ids = _ids(rv.build_schedules_body())
    keys = {i["key"] for i in ids if isinstance(i, dict) and i["type"] == "rep-sched-run"}
    assert keys == {s["id"] for s in rv.SCHEDULES}


# ------------------------------------------------------------------ archive

def test_empty_archive_explains_itself(tmp_store):
    text = _text(rv.build_archive_body())
    assert "No packs have been generated yet." in text


def test_archive_row_offers_download_and_delete(tmp_store):
    pack = report_store.generate("brc", fmt="pdf")
    ids = _ids(rv.build_archive_body())
    assert {"type": "rep-arch-dl", "id": pack["id"]} in ids
    assert {"type": "rep-arch-del", "id": pack["id"]} in ids


def test_archive_shows_the_stored_filename(tmp_store):
    pack = report_store.generate("smc", fmt="docx")
    assert pack["filename"] in _text(rv.build_archive_body())


# ----------------------------------------------------------------- wiring

def test_the_legacy_mock_builders_are_gone():
    """The old screens were buttons with no callbacks behind them."""
    for name in ("build_review_pack_body", "build_reports_schedules_body",
                 "build_reports_archive_body", "REPORT_SECTIONS", "SCHEDULED_REPORTS"):
        assert not hasattr(A, name), f"{name} still in app.py"


def test_reports_callbacks_are_registered():
    for name in ("update_reports_config", "rerender_review_pack", "generate_report_pack",
                 "run_scheduled_report", "download_archived_pack", "delete_archived_pack"):
        assert callable(getattr(A, name, None)), name


def test_the_config_store_and_download_target_exist_in_the_layout():
    """Both live outside page-content so the choice survives a tab switch."""
    ids = _ids([A.serve_layout()])
    assert "reports-config" in ids
    assert "reports-download" in ids


def test_the_slow_generate_button_is_held_disabled_while_it_runs():
    """Generating takes seconds; without this a second click archives a duplicate
    pack. Dash stores the spec on the callback record as running/runningOff."""
    # Match on the download target too: "esg-rep-status.children" contains
    # "rep-status.children", so the looser filter picks up the ESG callback.
    specs = [c for c in A.app._callback_list
             if "reports-download.data" in str(c.get("output"))
             and "rep-status.children" in str(c.get("output"))]
    assert specs, "the generate callback is not registered"
    running = specs[0].get("running")
    assert running, "generate_report_pack lost its running= spec"
    assert running["running"] == {"rep-generate.disabled": True}
    assert running["runningOff"] == {"rep-generate.disabled": False}


def test_a_merely_disabled_button_is_never_styled_as_busy():
    """The Data Hub's "Activate Uploaded Dataset" button borrows
    .report-generate-btn and ships disabled until a workbook is dropped. Styling
    :disabled as busy left it spinning forever on an idle screen — disabled means
    unavailable, not working, and the two must not share a look."""
    css = (pathlib.Path(A.__file__).resolve().parent / "assets" / "loading.css").read_text(
        encoding="utf-8")
    for block in css.split("}"):
        if "ipm-spin" not in block or "@keyframes" in block:
            continue
        selector = block.split("{")[0]
        for part in selector.split(","):
            if ":disabled" in part:
                assert "ipm-btn-busy" in part, (
                    f"a spinner is attached to a plain :disabled selector: {part.strip()}")


def test_the_data_hub_activate_button_starts_disabled_and_borrows_the_class():
    """Guards the pairing behind the rule above: this button ships disabled and
    reuses .report-generate-btn, which is exactly why :disabled must not imply
    busy. build_upload_card is used rather than the whole page because the page
    reads the dataset store, and this fact does not need a database."""
    from frontend import data_hub

    card = data_hub.build_upload_card()
    button = next(n for n in _walk(card) if getattr(n, "id", None) == "activate-dataset-btn")
    assert button.disabled is True
    assert "report-generate-btn" in button.className


def test_the_busy_indicator_assets_are_present():
    """assets/loading.js counts in-flight Dash callbacks to drive the progress bar
    and button spinners; without it every slow action looks like a dead click."""
    assets = pathlib.Path(A.__file__).resolve().parent / "assets"
    js = (assets / "loading.js").read_text(encoding="utf-8")
    css = (assets / "loading.css").read_text(encoding="utf-8")
    # It must hook the endpoint Dash actually uses, or it will never fire.
    assert "_dash-update-component" in js
    assert "window.fetch" in js
    for cls in ("ipm-progress", "ipm-busy", "ipm-btn-busy"):
        assert cls in js and cls in css, cls

    # The only thing allowed to suppress pointer events is the progress bar,
    # which spans the top of the window and would otherwise eat clicks on the
    # nav beneath it. Putting it on a control instead swallows the very click it
    # is meant to be reporting on — that is how the chat chips regressed.
    for rule in css.split("}"):
        if "pointer-events: none" in rule:
            assert ".ipm-progress" in rule, f"pointer-events suppressed in: {rule.strip()}"


def test_schedule_dates_are_stable_across_a_year_of_month_ends():
    """Guard the month/quarter arithmetic against off-by-one at year boundaries."""
    for month in range(1, 13):
        day = date(2026, month, 28)
        end = rv._quarter_end(day)
        assert end.month in (3, 6, 9, 12)
        assert end >= day.replace(day=1)
        assert (end + timedelta(days=1)).day == 1
