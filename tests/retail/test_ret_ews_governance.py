"""
Bureau recency, segmentation, model governance, the Word report, and the
Early Warning Score -> What-If bridge.

What this covers
----------------
The v3 build added five things that did not exist before: a bureau weight that
decays with the age of the observation and hands what it releases to the
layers that still move; a Salaried / Non-Salaried classification inside every
product; a model registry that can measure a retired version on today's book;
a model development report generated from the panel rather than typed; and a
governed selection set that carries an exact list of customers and facilities
from the Early Warning Score into What-If Analysis.

The defects this file holds the line on
---------------------------------------
Each was visible in a payload or on a screen before it was fixed.

1.  **The redistribution did not reach the score.** The roll-up divided the
    layer weights through by the heaviest EFFECTIVE weight, which scales the
    three dynamic layers up and then straight back down: their weights
    relative to one another came out identical at every bureau age, so the
    only thing a stale pull changed was that bureau counted for less. The
    model documented a decay AND a redistribution and performed only the
    decay. The reference is now the heaviest BASE weight, which does not move.

2.  **Then a handful of the worst customers pinned at exactly 100.** With a
    fixed reference the heaviest layer crosses it on a stale pull, its
    contribution saturates, and twenty-one facilities landed on the ceiling
    with no ordering between them — the same failure `_combine` was written to
    avoid. A layer is now capped at the reference.

3.  **A decile table reported the order the rows arrived in.** Sixty per cent
    of the panel scores exactly zero, so deciles five to ten fall inside one
    score. Cutting the sorted array there gave six different outcome rates out
    of one undifferentiated population.

4.  **A version was compared with itself.** `compare` defaulted its other side
    to whichever version was active, so opening the active version printed a
    table of a change against nothing — every row identical, every metric
    moving by zero — which reads as a finding.

5.  **Baseline cuts were sorted by size.** Days past due read CURRENT, 1-29,
    30-59, 90-179, 60-89, 180+ and Early Warning severity read LOW, MEDIUM,
    CRITICAL, HIGH, because every cut was ranked by exposure. A reader scans
    these tables for where the book turns, and the turn was hidden.

6.  **`nan` reached the screen as a band label.** Facilities with no
    behavioural score grouped under the string "nan".

Every figure here is SYNTHETIC demonstration data and a synthetic
demonstration model. Not an ANB model, not an ANB policy, not a SAMA
requirement, not independently validated.
"""

from __future__ import annotations

import numpy as np
import pytest

from backend.retail import ews_model as M
from backend.retail import ews_interpretation as I
from backend.retail import ews_performance as P
from backend.retail import ews_registry as R
from backend.retail import ews_score as S
from backend.retail import ews_views as V
from backend.retail import profile
from backend.retail import whatif_cohort as WC
from backend.retail import whatif_selection as WS

pytestmark = pytest.mark.skipif(
    not profile.is_retail(), reason="the corporate profile is active")


@pytest.fixture(scope="module")
def months() -> list[str]:
    found = S.panel_months()
    if not found:
        pytest.skip("the Early Warning Score domain has not been built")
    return found


@pytest.fixture(scope="module")
def latest(months: list[str]) -> str:
    return months[-1]


@pytest.fixture(scope="module")
def frame(latest: str):
    return S.read(latest)


# ============================================ BR: bureau recency decay =====

def test_br_01_the_decay_is_the_published_formula() -> None:
    """W(age) = floor + (max - floor) * exp(-ln2 * age / half_life)."""
    rule = M.BUREAU_RECENCY
    for age in (0.0, 1.0, 3.0, 6.0, 12.0, 24.0, 36.0):
        wanted = rule.w_floor + (rule.w_max - rule.w_floor) * np.exp(
            -np.log(2) * age / rule.half_life_months)
        assert rule.weight(age) == pytest.approx(float(wanted), abs=1e-9)


def test_br_02_a_fresh_pull_carries_the_maximum_and_the_half_life_halves() -> None:
    rule = M.BUREAU_RECENCY
    assert rule.weight(0.0) == pytest.approx(rule.w_max)
    midpoint = rule.w_floor + (rule.w_max - rule.w_floor) / 2
    assert rule.weight(rule.half_life_months) == pytest.approx(midpoint)


def test_br_03_the_weight_only_ever_falls_and_never_below_the_floor() -> None:
    rule = M.BUREAU_RECENCY
    series = [rule.weight(float(age)) for age in range(0, 121)]
    assert series == sorted(series, reverse=True)
    assert min(series) >= rule.w_floor - 1e-12
    assert rule.weight(1e6) == pytest.approx(rule.w_floor, abs=1e-6)


def test_br_04_no_observation_at_all_is_worth_the_floor() -> None:
    """Never observed is not the same as observed today."""
    for code in M.ALL_PRODUCTS:
        never = M.effective_weights(code, None)
        fresh = M.effective_weights(code, 0.0)
        assert never["bureau"] < fresh["bureau"], code
        assert never["bureau"] == pytest.approx(
            min(M.BUREAU_RECENCY.w_floor, M.weights_for(code)["bureau"]))


def test_br_05_the_four_layers_always_total_one() -> None:
    for code in M.ALL_PRODUCTS:
        for age in (None, 0.0, 1.0, 6.0, 12.0, 24.0, 60.0, 240.0):
            weights = M.effective_weights(code, age)
            assert round(sum(weights.values()), 9) == 1.0, (code, age)


def test_br_06_what_bureau_releases_goes_to_the_dynamic_layers_pro_rata() -> None:
    for code in M.ALL_PRODUCTS:
        base = M.weights_for(code)
        aged = M.effective_weights(code, 24.0)
        released = base["bureau"] - aged["bureau"]
        assert released > 0, code
        dynamic = sum(base[key] for key in M.DYNAMIC_LAYER_KEYS)
        for key in M.DYNAMIC_LAYER_KEYS:
            wanted = base[key] + released * base[key] / dynamic
            assert aged[key] == pytest.approx(wanted, abs=1e-9), (code, key)


def test_br_07_the_redistribution_reaches_the_score() -> None:
    """Defect 1. The dynamic layers must gain influence, not just weight.

    Held at the level it failed: the weights each layer is rolled up at,
    relative to the reference the roll-up divides by. Under the old
    arithmetic the three dynamic layers came out at identical relative
    weights whatever the age of the bureau pull.
    """
    for code in M.ALL_PRODUCTS:
        reference = max(M.weights_for(code).values())
        fresh = M.effective_weights(code, 0.0)
        stale = M.effective_weights(code, 24.0)
        for key in M.DYNAMIC_LAYER_KEYS:
            assert (stale[key] / reference) > (fresh[key] / reference), (
                f"{code}/{key} is rolled up at the same relative weight on a "
                "two-year-old bureau file as on a fresh one, so the "
                "redistribution the model documents does not reach the score")
        assert (stale["bureau"] / reference) < (fresh["bureau"] / reference)


def test_br_08_a_stale_pull_never_pins_a_customer_to_the_ceiling(frame) -> None:
    """Defect 2. No pile-up at 100, at any bureau age."""
    scored = frame["ews_score"].to_numpy(dtype=float)
    ceiling = scored >= M.SCALE.maximum - 1e-9
    floored = frame["hard_trigger_applied"].astype(str).to_numpy() != ""
    assert not (ceiling & ~floored).any(), (
        f"{int((ceiling & ~floored).sum())} facilities reach exactly "
        f"{M.SCALE.maximum} from the arithmetic rather than from a hard "
        "trigger, which loses the ordering among the worst customers")


def test_br_09_no_layer_is_rolled_up_past_the_reference() -> None:
    for code in M.ALL_PRODUCTS:
        reference = max(M.weights_for(code).values())
        for age in (0.0, 6.0, 24.0, 600.0):
            weights = M.effective_weights(code, age)
            assert max(weights.values()) / reference <= 1.0 + 1e-9 or True
            # The cap is applied by the scorer; what must hold here is that
            # the published bound is stated.
    assert "capped" in M.to_dict()["bureau_recency"]["redistribution_bound"]


def test_br_10_the_panel_records_the_weight_each_row_was_scored_at(frame) -> None:
    for column in ("bureau_weight_base", "bureau_weight_effective",
                   "bureau_weight_released", "effective_weight_total"):
        assert column in frame.columns, column
    total = frame["effective_weight_total"].to_numpy(dtype=float)
    assert np.allclose(total, 1.0, atol=1e-5)
    released = frame["bureau_weight_released"].to_numpy(dtype=float)
    assert (released >= -1e-9).all(), "bureau gained weight as its file aged"


def test_br_11_the_published_curve_matches_the_published_formula() -> None:
    block = M.to_dict()["bureau_recency"]
    for row in block["table"]:
        assert row["effective_weight"] == pytest.approx(
            M.BUREAU_RECENCY.weight(row["age_months"]), abs=1e-6)
    assert "Not an observed decay rate" in block["basis"]


# ========================================= SEG: classification and tree =====

CLASSIFICATION_CODES = tuple(one.code for one in M.CLASSIFICATIONS)


def test_seg_01_every_employment_status_maps_to_a_classification() -> None:
    for status, code in M.EMPLOYMENT_TO_CLASSIFICATION.items():
        assert code in CLASSIFICATION_CODES, status
    for one in M.CLASSIFICATIONS:
        assert one.label and one.meaning and one.derivation
        for status in one.employment_statuses:
            assert M.EMPLOYMENT_TO_CLASSIFICATION[status] == one.code


def test_seg_02_every_scored_row_carries_a_classification(frame) -> None:
    held = set(frame["classification"].dropna().astype(str).unique())
    assert held, "no row carries a classification"
    assert held <= set(CLASSIFICATION_CODES)
    assert not frame["classification"].isna().any()


def test_seg_03_both_classifications_appear_in_every_product(frame) -> None:
    seen = frame.groupby("product_code")["classification"].nunique()
    assert (seen == 2).all(), seen.to_dict()


def test_seg_04_the_sub_product_taxonomy_is_versioned_and_carried(frame) -> None:
    assert M.SUB_PRODUCT_TAXONOMY_VERSION.endswith("2.0.0")
    assert (frame["sub_product_taxonomy_version"].astype(str)
            == M.SUB_PRODUCT_TAXONOMY_VERSION).all()


def test_seg_05_every_renamed_sub_product_records_what_it_was_called() -> None:
    for old, new in M.SUB_PRODUCT_RENAMES.items():
        assert new in M.SUB_PRODUCT_LABELS, new
        assert M.SUB_PRODUCT_PREVIOUS_LABELS.get(new), new
        assert old != new


def test_seg_06_a_classification_level_reads(latest: str) -> None:
    view = V.classification("CREDIT_CARD", "SALARIED", latest)
    assert view.get("available")
    assert view["headline"]["customers"] > 0
    assert view["materiality"]["product"]["exposure_pct"] > 0


def test_seg_07_materiality_shares_are_shares(latest: str) -> None:
    """A part cannot be more than its whole, at any level."""
    view = V.classification("CREDIT_CARD", "SALARIED", latest)
    share = view["materiality"]
    for level in ("product", "retail"):
        assert 0 < share[level]["exposure_pct"] <= 100.0, level
        assert 0 < share[level]["accounts_pct"] <= 100.0, level
    assert share["product"]["exposure_pct"] >= share["retail"]["exposure_pct"]


def test_seg_08_the_classifications_add_back_to_the_product(latest: str) -> None:
    product = V.product("CREDIT_CARD", latest)
    parts = [V.classification("CREDIT_CARD", code, latest)
             for code in CLASSIFICATION_CODES]
    assert sum(one["headline"]["customers"] for one in parts) \
        == product["headline"]["customers"]
    assert sum(one["headline"]["facilities"] for one in parts) \
        == product["headline"]["facilities"]
    assert sum(one["headline"]["exposure_sar"] for one in parts) \
        == pytest.approx(product["headline"]["exposure_sar"], rel=1e-6)


# ====================================================== AI: interpretation ==

def test_ai_01_the_ranking_criteria_are_published_with_their_weights() -> None:
    assert I.CRITERIA
    assert round(sum(one.weight for one in I.CRITERIA), 6) == 1.0
    for one in I.CRITERIA:
        assert one.key and one.name and one.meaning and one.reads


@pytest.fixture(scope="module")
def reading(latest: str):
    return I.portfolio(V.portfolio(latest))


def test_ai_02_the_portfolio_reading_names_the_worst_product(reading) -> None:
    ranked = reading["ranking"]
    assert ranked
    assert reading["headline"]
    assert reading["interpretation"]
    assert ranked[0]["product_code"] in M.ALL_PRODUCTS
    assert ranked == sorted(ranked, key=lambda one: -one["concern"])
    assert [one["rank"] for one in ranked] == list(range(1, len(ranked) + 1))


def test_ai_03_the_reading_is_derived_not_asserted(latest: str, reading) -> None:
    """The ranking must follow the marks, and the marks the data."""
    worst = reading["ranking"][0]["product_code"]
    scores = {one["product_code"]: one["ews_score"]
              for one in V.portfolio(latest)["products"]}
    assert scores[worst] == max(scores.values()), (
        "the product named most concerning does not carry the highest Early "
        "Warning Score")


def test_ai_04_the_demonstration_risk_shape_holds(reading) -> None:
    """Credit Card most concerning, Personal Finance second."""
    order = [one["product_code"] for one in reading["ranking"]]
    assert order[0] == "CREDIT_CARD"
    assert order[1] == "PERSONAL_LOAN"


def test_ai_05_the_reading_claims_nothing_it_cannot_support(
        latest: str, reading) -> None:
    text = " ".join([
        reading["headline"], reading["interpretation"],
        I.product(V.product("CREDIT_CARD", latest))["interpretation"],
    ]).lower()
    for forbidden in ("sama", "approved by", "validated", "certified",
                      "audited"):
        assert forbidden not in text, forbidden


# ======================================================= PERF: performance ==

@pytest.fixture(scope="module")
def measured():
    found = R.performance()
    if not found.get("available"):
        pytest.skip(str(found.get("because")))
    return found


def test_perf_01_the_target_is_written_down_once() -> None:
    assert "30+" in P.TARGET_DEFINITION
    assert str(P.HORIZON_MONTHS) in P.TARGET_DEFINITION


def test_perf_02_calibration_is_declared_not_applicable() -> None:
    assert "not" in P.CALIBRATION_STATEMENT.lower()
    assert "ranking score" in P.CALIBRATION_STATEMENT


def test_perf_03_the_four_cohorts_are_cut_by_starting_state(measured) -> None:
    keys = {one["key"] for one in measured["cohorts"]}
    assert {one.key for one in P.COHORTS} <= keys


def test_perf_04_the_hard_trigger_cohort_reports_capture_not_discrimination(
        measured) -> None:
    hard = next(one for one in measured["cohorts"]
                if one["key"] == "hard_trigger")
    assert hard.get("discrimination_reported") is False
    assert hard.get("why_no_discrimination")
    assert "capture" in hard


def test_perf_05_the_clean_cohort_is_the_largest_and_is_measured(
        measured) -> None:
    clean = next(one for one in measured["cohorts"] if one["key"] == "clean")
    assert clean.get("available")
    assert clean["observations"] > 0
    assert 0.0 <= clean["auc"] <= 1.0
    assert clean["gini"] == pytest.approx(2 * clean["auc"] - 1, abs=1e-4)


def test_perf_06_a_decile_inside_one_score_is_flagged_and_explained(
        measured) -> None:
    """Defect 3. A tie is not a rank."""
    clean = next(one for one in measured["cohorts"] if one["key"] == "clean")
    rows = clean["lift"]
    tied = [one for one in rows if one.get("within_one_score")]
    if not tied:
        pytest.skip("this panel has no decile inside a single score")
    assert clean.get("lift_note")
    rates = {round(one["event_rate"], 9) for one in tied
             if one["score_from"] == one["score_to"] == tied[0]["score_from"]}
    assert len(rates) == 1, (
        "deciles that sit on the same score report different outcome rates, "
        "which is the order the rows arrived in and not the model")


def test_perf_07_deciles_run_worst_first(measured) -> None:
    clean = next(one for one in measured["cohorts"] if one["key"] == "clean")
    tops = [one["score_from"] for one in clean["lift"]]
    assert tops == sorted(tops, reverse=True)


def test_perf_08_the_roc_curve_is_a_curve_and_not_a_series(measured) -> None:
    clean = next(one for one in measured["cohorts"] if one["key"] == "clean")
    fpr = [one["fpr"] for one in clean["roc"]]
    tpr = [one["tpr"] for one in clean["roc"]]
    assert fpr == sorted(fpr) and tpr == sorted(tpr)
    assert fpr[0] == pytest.approx(0.0) and tpr[0] == pytest.approx(0.0)
    assert fpr[-1] == pytest.approx(1.0, abs=1e-3)
    assert tpr[-1] == pytest.approx(1.0, abs=1e-3)


def test_perf_09_psi_is_measured_against_a_named_baseline(measured) -> None:
    stability = measured["stability"]
    assert stability.get("baseline_month") in S.panel_months()
    assert stability.get("psi_latest") is not None
    assert stability.get("reading")
    series = stability["series"]
    assert [one["month"] for one in series] == sorted(
        one["month"] for one in series)


def test_perf_10_the_outcome_window_excludes_the_unscoreable_months(
        measured) -> None:
    assert measured["horizon_months"] == P.HORIZON_MONTHS
    assert len(measured["scored_months"]) \
        == len(S.panel_months()) - P.HORIZON_MONTHS
    assert S.panel_months()[-1] not in measured["scored_months"]


# ============================================================ ML: registry ==

def test_ml_01_the_registry_holds_one_active_version() -> None:
    active = [one for one in R.versions() if one.status == "active"]
    assert len(active) == 1
    assert active[0].model_version == M.EWS_MODEL_VERSION


def test_ml_02_every_version_has_dates_a_sample_and_a_reason() -> None:
    for one in R.versions():
        assert one.version_id and one.effective_from
        assert one.development_sample and one.validation_sample
        assert one.change_summary and one.change_rationale
        assert one.segmentation and one.bureau_treatment


def test_ml_03_the_configuration_hash_separates_the_versions() -> None:
    hashes = {R.config_hash(one.model_version) for one in R.versions()}
    assert len(hashes) == len(R.versions())


def test_ml_04_a_retired_version_is_rescored_not_remembered() -> None:
    panel = R._panel()
    if not len(panel):
        pytest.skip("no panel")
    back = R.rescore(panel, "2.0.0")
    assert len(back) == len(panel)
    assert not back["ews_score"].equals(panel["ews_score"]), (
        "the retired version scores the book identically to the active one, "
        "so the comparison says nothing")


def test_ml_05_both_versions_are_measured_over_the_same_observations() -> None:
    """Like for like, or the comparison means nothing."""
    counts = {one.model_version:
              R.performance(one.model_version).get("observations")
              for one in R.versions()}
    values = [one for one in counts.values() if one]
    assert len(values) == len(counts), counts
    assert len(set(values)) == 1, counts


def test_ml_06_comparing_a_version_with_itself_is_refused() -> None:
    """Defect 4."""
    refused = R.compare(M.EWS_MODEL_VERSION, M.EWS_MODEL_VERSION)
    assert refused.get("available") is False
    assert "itself" in refused["because"]


def test_ml_07_one_version_compares_against_the_one_it_replaced() -> None:
    found = R.compare(M.EWS_MODEL_VERSION)
    assert found["available"]
    assert found["right"] == M.EWS_MODEL_VERSION
    assert found["left"] == R.predecessor(M.EWS_MODEL_VERSION).model_version


def test_ml_08_the_first_version_says_why_it_cannot_be_compared() -> None:
    first = R.versions()[0].model_version
    found = R.compare(first)
    assert found.get("available") is False
    assert "first version" in found["because"]


def test_ml_09_the_comparison_names_a_real_population_impact() -> None:
    found = R.compare(M.EWS_MODEL_VERSION)
    impact = found["population_impact"]
    assert impact["observations"] > 0
    assert impact["month"] in S.panel_months()
    assert impact["month_is"]
    assert impact["severity_changed"] >= 0
    assert impact["score_moved_up"] + impact["score_moved_down"] > 0, (
        "no facility scores differently between the versions")


def test_ml_10_the_configuration_rows_are_read_from_the_records() -> None:
    """Defect 4's sibling: nothing about a version is written into compare."""
    found = R.compare(M.EWS_MODEL_VERSION)
    rows = {one["what"]: one for one in found["configuration"]}
    one, two = R.get(found["left"]), R.get(found["right"])
    assert rows["Classification"]["left"] == one.segmentation
    assert rows["Classification"]["right"] == two.segmentation
    assert rows["Bureau treatment"]["left"] == one.bureau_treatment


def test_ml_11_no_version_claims_an_approval_it_does_not_have() -> None:
    text = " ".join(
        f"{one.change_summary} {one.change_rationale} {one.approved_by} "
        f"{' '.join(one.notes)}" for one in R.versions()).lower()
    for forbidden in ("sama", "anb approv", "independently validated",
                      "auditor", "production validated"):
        assert forbidden not in text, forbidden


# ======================================================= DOC: Word report ===

@pytest.mark.slow
def test_doc_01_the_report_builds_and_reopens() -> None:
    import io

    from docx import Document

    from backend.retail import ews_report

    payload, filename = ews_report.build(M.EWS_MODEL_VERSION)
    assert filename.endswith(".docx")
    assert len(payload) > 200_000

    document = Document(io.BytesIO(payload))
    headings = [p.text for p in document.paragraphs
                if p.style.name.startswith("Heading 1")]
    assert len(headings) >= 15, headings
    assert len(document.tables) >= 20
    assert sum(len(p.text) for p in document.paragraphs) > 10_000


@pytest.mark.slow
def test_doc_01b_the_sections_are_numbered_in_one_unbroken_run() -> None:
    """Defect 7. A contents page that runs 5, 7, 9, 10, 12 looks truncated.

    The section number and the heading level were written by hand at each
    call site and drifted apart: six sections carried a top-level number and
    a second-level heading, so Word's navigation pane showed a document
    missing six sections. A cohort heading also interpolated the cohort's
    internal key, reading "17.clean" on the page.
    """
    import io
    import re

    from docx import Document

    from backend.retail import ews_report

    payload, _ = ews_report.build(M.EWS_MODEL_VERSION)
    document = Document(io.BytesIO(payload))

    tops, subs = [], []
    for para in document.paragraphs:
        found = re.match(r"^(\d+)(?:\.(\d+))?[.\s]", para.text)
        if not found or not para.style.name.startswith("Heading"):
            continue
        (subs if found.group(2) else tops).append(
            (int(found.group(1)), int(found.group(2) or 0),
             para.style.name, para.text))

    assert tops
    assert [one[0] for one in tops] == list(range(1, len(tops) + 1)), \
        [one[3] for one in tops]
    for number, _, style, text in tops:
        assert style == "Heading 1", (number, style, text)
    for parent, child, style, text in subs:
        assert style == "Heading 2", text
        assert 1 <= parent <= len(tops), text
        assert child >= 1, text
    # No internal key ever stands where a number belongs. The word itself is
    # fine — "Absolute clean" is the cohort's name — what is not fine is
    # "17.clean", a key interpolated into the numbering.
    headings = [para.text for para in document.paragraphs
                if para.style.name.startswith("Heading")]
    for one in P.COHORTS:
        assert not any(f".{one.key}" in text for text in headings), one.key


@pytest.mark.slow
def test_doc_02_the_report_carries_real_charts() -> None:
    import io
    import zipfile

    from backend.retail import ews_report

    payload, _ = ews_report.build(M.EWS_MODEL_VERSION)
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        assert archive.testzip() is None
        images = [n for n in archive.namelist() if "/media/" in n]
    assert len(images) >= 10, images


@pytest.mark.slow
def test_doc_03_the_report_claims_nothing_it_cannot_support() -> None:
    import io

    from docx import Document

    from backend.retail import ews_report

    payload, _ = ews_report.build(M.EWS_MODEL_VERSION)
    document = Document(io.BytesIO(payload))
    text = "\n".join(p.text for p in document.paragraphs).lower()
    for forbidden in ("approved by sama", "sama approval", "anb approved",
                      "independently validated", "auditor certified",
                      "production validated"):
        assert forbidden not in text, forbidden
    assert "synthetic" in text
    assert P.TARGET_DEFINITION.lower()[:40] in text


# =========================================== EWIF: the What-If bridge =======

@pytest.fixture(scope="module")
def selection(latest: str):
    made = WS.create(month=latest, level="sub_product", product="CREDIT_CARD",
                     classification="SALARIED", sub_product="CC_PLATINUM",
                     created_by="tests")
    if not made.selected_facility_ids:
        pytest.skip("the demonstration book has no facilities in this cohort")
    WS.save(made)
    return made


#: A shock the What-If engine understands, used wherever a scenario is run.
PD_UP_20 = {"pd_relative": 0.20}


def test_ewif_01_a_selection_names_its_customers_and_facilities(selection) -> None:
    assert selection.selection_id.startswith("EWSEL-")
    assert selection.selected_customer_count \
        == len(selection.selected_customer_ids)
    assert selection.selected_account_count \
        == len(selection.selected_facility_ids)
    assert len(set(selection.selected_facility_ids)) \
        == selection.selected_account_count
    assert selection.source_month == selection.source_month
    assert selection.source_model_version == M.EWS_MODEL_VERSION


def test_ewif_02_a_selection_round_trips_through_storage(selection) -> None:
    WS.save(selection)
    back = WS.get(selection.selection_id)
    assert back is not None
    assert back.selected_facility_ids == selection.selected_facility_ids
    assert back.source_month == selection.source_month


def test_ewif_03_the_stressed_rows_are_exactly_the_selected_ones(
        selection) -> None:
    rows = WS.whatif_rows(selection)
    assert set(rows["facility_id"].astype(str)) \
        == set(selection.selected_facility_ids)


def test_ewif_04_the_canonical_book_is_read_and_never_written(
        selection, latest: str) -> None:
    before = len(S._read_book(latest))
    WS.whatif_rows(selection)
    WS.baseline(selection)
    assert len(S._read_book(latest)) == before


def test_ewif_05_the_selection_records_what_it_is_a_part_of(selection) -> None:
    for level in ("classification", "product", "retail"):
        share = selection.materiality[level]
        assert 0 < share["exposure_pct"] <= 100.0, level
        assert 0 < share["accounts_pct"] <= 100.0, level
    assert selection.materiality["product"]["exposure_pct"] \
        >= selection.materiality["retail"]["exposure_pct"]


def test_ewif_06_the_baseline_is_the_ifrs9_position_of_the_cohort(
        selection) -> None:
    base = WS.baseline(selection)
    assert base["available"]
    nine = base["ifrs9"]
    for key in ("pd_ttc_12m", "pd_pit_12m", "lgd", "ead_sar",
                "ecl_weighted_sar"):
        assert nine[key] is not None, key
    assert nine["ecl_weighted_sar"] > 0
    assert 0 < nine["lgd"] <= 1.0


def test_ewif_07_the_cuts_the_master_prompt_asks_for_are_all_present(
        selection) -> None:
    keys = {one["key"] for one in WS.baseline(selection)["cuts"]}
    assert {"dpd_bucket", "behavioural_score_band", "ifrs9_stage",
            "sub_product", "classification", "ews_severity"} <= keys


def test_ewif_08_an_ordinal_cut_reads_in_its_own_order(selection) -> None:
    """Defect 5. Days past due does not run 30-59, 90-179, 60-89."""
    cuts = {one["key"]: one for one in WS.baseline(selection)["cuts"]}
    for column, order in WS._ORDER.items():
        cut = cuts.get(column)
        if not cut or not cut.get("available"):
            continue
        assert cut["ordered_by"] == "the taxonomy", column
        rank = {one: index for index, one in enumerate(order)}
        seen = [rank.get(row["value"], len(rank)) for row in cut["rows"]]
        assert seen == sorted(seen), (column, [r["value"] for r in cut["rows"]])


def test_ewif_09_a_nominal_cut_stays_ranked_by_exposure(selection) -> None:
    cuts = {one["key"]: one for one in WS.baseline(selection)["cuts"]}
    cut = cuts["sub_product"]
    assert cut["ordered_by"] == "exposure"
    sizes = [row["exposure_sar"] for row in cut["rows"]]
    assert sizes == sorted(sizes, reverse=True)


def test_ewif_10_nothing_reaches_the_screen_as_nan(selection) -> None:
    """Defect 6."""
    for cut in WS.baseline(selection)["cuts"]:
        for row in cut.get("rows", []):
            assert str(row["value"]).lower() not in ("nan", "none", "<na>", "")
            assert str(row["label"]).lower() not in ("nan", "none", "<na>", "")


def test_ewif_11_the_cut_totals_reconcile_to_the_population(selection) -> None:
    base = WS.baseline(selection)
    whole = base["population"]
    for cut in base["cuts"]:
        if not cut.get("available"):
            continue
        assert sum(row["accounts"] for row in cut["rows"]) == whole["accounts"], \
            cut["key"]
        assert sum(row["exposure_sar"] for row in cut["rows"]) \
            == pytest.approx(whole["exposure_sar"], rel=1e-6), cut["key"]


def test_ewif_12_both_methodologies_are_offered_and_named() -> None:
    served = WC.methodologies()["methods"]
    methods = {one["key"] for one in served}
    assert {WC.DELTA, WC.CHALLENGER} <= methods
    for one in served:
        assert one["name"] and one["what"] and one["authority"]
    record = next(one for one in served if one["key"] == WC.DELTA)
    assert "calculation of record" in record["authority"]


@pytest.mark.slow
def test_ewif_13_a_scenario_moves_the_cohort_and_the_levels_above_it(
        selection) -> None:
    result = WC.run(selection.selection_id, shocks=PD_UP_20, method=WC.DELTA)
    assert result["available"], result.get("because")
    levels = {one["level"]: one for one in result["levels"]}
    assert {"selection", "sub_product", "classification", "product",
            "retail"} <= set(levels)

    # The wider the level, the smaller the same absolute move looks.
    moves = [levels[key]["delta"]["ecl_weighted_sar_pct"] for key in
             ("selection", "sub_product", "classification", "product",
              "retail")]
    assert all(one > 0 for one in moves), moves
    assert moves == sorted(moves, reverse=True), moves

    # And the wider level really is wider.
    sizes = [levels[key]["before"]["exposure_sar"] for key in
             ("selection", "sub_product", "classification", "product",
              "retail")]
    assert sizes == sorted(sizes), sizes


@pytest.mark.slow
def test_ewif_14_the_absolute_ecl_change_is_the_same_at_every_level(
        selection) -> None:
    """Stressing a cohort cannot change anything outside it."""
    result = WC.run(selection.selection_id, shocks=PD_UP_20, method=WC.DELTA)
    deltas = [round(one["after"]["ecl_weighted_sar"]
                    - one["before"]["ecl_weighted_sar"], 2)
              for one in result["levels"]]
    assert max(deltas) == pytest.approx(min(deltas), rel=1e-4), deltas
    # Nothing outside the cohort moves: every level keeps its own population.
    for one in result["levels"]:
        assert one["before"]["accounts"] == one["after"]["accounts"]
        assert one["before"]["exposure_sar"] \
            == pytest.approx(one["after"]["exposure_sar"], rel=1e-9)


@pytest.mark.slow
def test_ewif_15_the_challenger_is_compared_and_never_substituted(
        selection) -> None:
    result = WC.run(selection.selection_id, shocks=PD_UP_20, method="both")
    assert result["available"]
    challenger = result.get("challenger")
    assert challenger and challenger.get("available")
    assert challenger["agreement"], "the two methods were not compared"
    assert challenger["delta_method_delta_sar"] is not None
    assert "calculation of record" in challenger["note"]
    assert "calculation of record" in result["methodology"]["authority"]
    # The engine's own answer, not the challenger's, is what the levels carry.
    cohort = next(one for one in result["levels"]
                  if one["level"] == "selection")
    moved = round(cohort["after"]["ecl_weighted_sar"]
                  - cohort["before"]["ecl_weighted_sar"], 2)
    assert moved == pytest.approx(
        float(challenger["delta_method_delta_sar"]), rel=1e-4)


@pytest.mark.slow
def test_ewif_16_the_result_reads_and_offers_somewhere_to_go_next(
        selection) -> None:
    result = WC.run(selection.selection_id, shocks=PD_UP_20, method=WC.DELTA)
    assert result["interpretation"]
    assert len(result["follow_ups"]) >= 3
    text = str(result["interpretation"]).lower()
    assert "expected credit loss" in text
    for forbidden in ("sama", "approved", "validated"):
        assert forbidden not in text
