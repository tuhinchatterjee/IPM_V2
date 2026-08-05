"""
ESG Inputs as an estimator: every workbook input block is editable, and editing
recomputes the whole model live without saving.

The workbook's own structure is the acceptance criterion — a block per input
sheet, each folding back into the model through the same engine.
"""

import pytest

import app as A
import backend.climate.checks as climate_checks
import backend.climate.defaults as defaults
import backend.climate.engine as engine
import backend.climate.registers as registers
from frontend import esg_view as ev

BLOCK_KEYS = [k for k, _ in ev.INPUT_BLOCKS]


def _walk(node):
    yield node
    children = getattr(node, "children", None)
    if children is None:
        return
    for child in (children if isinstance(children, (list, tuple)) else [children]):
        if hasattr(child, "children") or hasattr(child, "id"):
            yield from _walk(child)


def _table_blocks(tree):
    return {n.id["block"] for n in _walk(A.html.Div(tree))
            if isinstance(getattr(n, "id", None), dict) and n.id.get("type") == "esg-tbl"}


def _live(rows):
    return ev.resolve_live(None, rows)


# ------------------------------------------------- the workbook's input sheets

def test_every_workbook_input_sheet_has_a_block():
    """One editable block per input tab in the workbook. Missing one means part of
    the model can only be changed by editing Python."""
    assert set(BLOCK_KEYS) == {
        "sectors", "emissions", "scenarios", "hazards", "exposure",
        "calibration", "macro", "grades", "settings",
    }


@pytest.mark.parametrize("block", BLOCK_KEYS)
def test_block_renders_its_editable_tables(block):
    body = ev.build_inputs_body(None, block)
    assert body
    assert _table_blocks(body) == set(ev.tables_for(block))


@pytest.mark.parametrize("block", BLOCK_KEYS)
def test_derived_half_contains_no_editable_tables(block):
    """The live callback replaces only the derived container. If a DataTable were
    in there it would be remounted on every edit — resetting the user's position
    and risking a loop with the callback that reads its data."""
    model = defaults.default_model()
    result = engine.calculate(model)
    live = (model, result, climate_checks.run_checks(result, model))
    derived = ev.build_inputs_body(None, block, live=live, derived_only=True)
    assert isinstance(derived, list)
    assert not _table_blocks(derived)


# ------------------------------------------------------ live recalculation

def test_editing_gva_moves_intensity_and_cost_ratio():
    saved, _model, live, _checks = _live([("sectors", [
        {"id": "S05", "name": "Utilities", "gva_omr": 500.0, "turnover_gva": 1.0,
         "pass_through": 0.10, "macro_beta": 1.0, "rationale": ""}])])
    before = next(s for s in saved["sectors"] if s["id"] == "S05")
    after = next(s for s in live["sectors"] if s["id"] == "S05")
    assert after["gva_local"] == 500.0
    assert after["intensity"] > before["intensity"], "a smaller denominator must raise intensity"
    assert live["max_cost_ratio"] > saved["max_cost_ratio"]


def test_editing_the_eu_calibration_refits_k():
    """k is fitted, not stored — an EU-side edit has to move it."""
    saved, _m, live, _c = _live([("calibration", [{"key": "median_to_average", "value": 1.0}])])
    assert abs(live["k"] - saved["k"]) > 1e-9


def test_editing_an_anchor_moves_the_diagnostics_not_the_headline_k():
    """Faithful to the workbook, which holds the anchor twice: EU_k_Calibration's
    A/B selector fits the headline k, while the k_MultiAnchor table drives the
    curvature band and the out-of-sample checks. Editing the anchors table moves
    the second set, not the first — the Inputs tab says so explicitly."""
    rows = [{"id": 1, "baseline_pd": 0.02, "rel_change": 0.02, "use": "FIT"},
            {"id": 2, "baseline_pd": 0.02, "rel_change": 0.02, "use": "FIT"}]
    saved, _m, live, _c = _live([("anchors", rows)])
    assert live["k"] == pytest.approx(saved["k"]), "headline k comes from the A/B selector"
    saved_band = [b["k"] for b in saved["calibration"]["theta_band"]]
    live_band = [b["k"] for b in live["calibration"]["theta_band"]]
    assert live_band != saved_band, "the curvature band refits on the anchors table"


def test_anchor_a_selector_does_refit_the_headline_k():
    saved, _m, live, _c = _live([("calibration", [{"key": "anchor_a_rel", "value": 0.02}])])
    assert abs(live["k"] - saved["k"]) > 1e-9


def test_editing_the_series_re_estimates_beta():
    base = defaults.default_model()["macro"]["observations"]
    rows = [{"year": o["year"], "npl_ratio": o["npl_ratio"], "gdp_growth": o["gdp_growth"] * 2}
            for o in base]
    saved, _m, live, _c = _live([("macro", rows)])
    assert abs(live["macro"]["beta_in_use"] - saved["macro"]["beta_in_use"]) > 1e-9


def test_correlation_lever_moves_beta_but_not_the_estimate():
    """Correlation is the exposed lever: it changes beta in use, while the
    correlation estimated from the data is untouched."""
    saved, _m, live, _c = _live([("macro_settings",
                                  [{"key": "correlation_in_use", "value": -0.20}])])
    assert live["macro"]["correlation_in_use"] == pytest.approx(-0.20)
    assert live["macro"]["correlation_estimated"] == pytest.approx(
        saved["macro"]["correlation_estimated"])
    assert abs(live["macro"]["beta_in_use"] - saved["macro"]["beta_in_use"]) > 1e-9


def test_cyclone_record_derives_the_h1_baseline():
    """The event record is an input, not a footnote: H1's AAL is computed from it."""
    saved, _m, live, _c = _live([("events", [
        {"event": "Only event", "year": 2007, "damage_usd_m": 1000.0, "source": ""}])])
    assert live["physical"]["event_aal_share"] != pytest.approx(
        saved["physical"]["event_aal_share"])
    assert live["physical"]["observed_damage_usd_m"] == 1000.0


def test_events_with_no_damage_are_dropped_not_counted_as_zero():
    model = defaults.default_model()
    edited = ev.apply_edits(model, "events", [
        {"event": "Real", "year": 2007, "damage_usd_m": 4200.0, "source": ""},
        {"event": "Blank row", "year": 0, "damage_usd_m": None, "source": ""},
    ])
    assert len(edited["cyclone_events"]) == 1


def test_carbon_price_edit_moves_the_transition_channel():
    model = defaults.default_model()
    rows = [{"code": s["code"], "name": s["name"], "quadrant": s.get("quadrant", ""),
             "warming_2100": s["warming_2100"],
             **{f"p{y}": (s["carbon_price"][y] * 2) for y in defaults.HORIZON_YEARS},
             **{f"d{y}": s["gdp_deviation"][y] for y in defaults.HORIZON_YEARS},
             "intensity_index": 1.0, "denominator_index": 1.0}
            for s in model["scenarios"]]
    saved, _m, live, _c = _live([("scenarios", rows)])
    assert live["max_cost_ratio"] > saved["max_cost_ratio"]


def test_live_edits_never_touch_the_saved_version():
    """Estimating must not mutate anything — saving is a separate, explicit act."""
    before = engine.calculate(defaults.default_model())["k"]
    _live([("calibration", [{"key": "median_to_average", "value": 1.0}])])
    after = engine.calculate(defaults.default_model())["k"]
    assert after == pytest.approx(before)


def test_resolve_live_with_no_edits_reproduces_the_saved_model():
    saved, _m, live, _c = _live([])
    assert live["k"] == pytest.approx(saved["k"])
    assert live["max_cost_ratio"] == pytest.approx(saved["max_cost_ratio"])


# ------------------------------------------------------------- the live strip

def test_live_strip_marks_a_moved_value():
    saved, model, live, checks = _live([("calibration",
                                         [{"key": "median_to_average", "value": 1.0}])])
    strip = ev.build_inputs_live(model, live, checks, baseline=saved)
    classes = [getattr(n, "className", "") or "" for n in _walk(A.html.Div(strip))]
    text = " ".join(c for c in (getattr(n, "children", None) for n in _walk(A.html.Div(strip)))
                    if isinstance(c, str))
    assert any("is-moved" in c for c in classes)
    assert "UNSAVED ESTIMATE" in text


def test_live_strip_says_so_when_nothing_moved():
    saved, model, live, checks = _live([])
    text = " ".join(c for c in (getattr(n, "children", None)
                                for n in _walk(A.html.Div(ev.build_inputs_live(
                                    model, live, checks, baseline=saved))))
                    if isinstance(c, str))
    assert "MATCHES SAVED VERSION" in text


# ------------------------------------------------------------- guard rails

def test_out_of_range_edits_are_clamped_not_accepted():
    model = defaults.default_model()
    edited = ev.apply_edits(model, "calibration", [
        {"key": "eu_pass_through", "value": 5.0},
        {"key": "household_share", "value": -2.0},
    ])
    assert edited["calibration"]["eu_pass_through"] == 1.0
    assert edited["calibration"]["route1"]["household_share"] == 0.0


def test_a_too_short_series_is_rejected_rather_than_estimated():
    """Two points would produce a meaningless regression; the edit is ignored."""
    model = defaults.default_model()
    edited = ev.apply_edits(model, "macro", [{"year": 2020, "npl_ratio": 0.04, "gdp_growth": 0.01}])
    assert edited["macro"]["observations"] == model["macro"]["observations"]


def test_garbage_input_falls_back_to_the_existing_value():
    model = defaults.default_model()
    before = model["sectors"][0]["gva_omr"]
    edited = ev.apply_edits(model, "sectors", [{"id": model["sectors"][0]["id"],
                                                "gva_omr": "not a number"}])
    assert edited["sectors"][0]["gva_omr"] == before


# ------------------------------------------------------------- audit trail

@pytest.mark.parametrize("view", [v for v, _ in ev.AUDIT_VIEWS])
def test_audit_view_renders(view):
    assert ev.build_audit_body(view)


def test_audit_covers_the_workbook_provenance_sheets():
    assert {v for v, _ in ev.AUDIT_VIEWS} == {"verification", "assumptions", "sources", "changes"}
    assert len(registers.VERIFICATION_LOG_ROWS) >= 39
    assert len(registers.ASSUMPTION_REGISTER_ROWS) >= 33
    assert len(registers.CHANGE_LOG_ROWS) >= 19


def test_esg_section_routes_every_tab():
    for tab in A.SECTION_TABS["esg"]:
        assert A.build_section_tab_body("esg", tab)


def test_audit_trail_is_a_tab():
    assert "Audit trail" in A.SECTION_TABS["esg"]
