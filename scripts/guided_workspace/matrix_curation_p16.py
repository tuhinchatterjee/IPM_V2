#!/usr/bin/env python3
"""One-off, reviewed curation of the requirement evidence map at P16.

Every row this round re-graded, with the test or journey that now carries
it. A claim of COVERED is still only a claim: the generator turns it into
PASS only if every cited test and journey PASSED in the final regression of
the candidate. Rows this round could not close keep their claim and a
precise reason (see PARTIAL_CLOSURE_AUDIT.md).

Run once; the generator then verifies every citation.
"""

import json
from pathlib import Path

P = Path("docs/guided_workspace/matrix/requirement_evidence.json")
E = json.loads(P.read_text(encoding="utf-8"))
ORC = "tests/cockpit_v4/test_gw_metric_oracles.py::"
L = "tests/cockpit_v4/test_gw_lens_content.py::"
ML = "tests/cockpit_v4/test_gw_ml_decomposition.py::"
W = "tests/cockpit_v4/test_gw_p16_wiring.py::"


def put(rid, claim, tests, journeys=None, gap="", add=True, sources=None):
    e = E[rid]
    e["claim"] = claim
    e["tests"] = (e["tests"] if add else []) + [
        t for t in tests if t not in e["tests"] or not add]
    if journeys is not None:
        e["journeys"] = list(dict.fromkeys([*e["journeys"], *journeys]))
    if sources is not None:
        e["sources"] = sources
    e["gap"] = gap
    e["note"] = "P16"


# ---- metrics: independent oracles ------------------------------------------------
ORACLE = ["M004", "M008", "M009", "M010", "M011", "M012", "M013", "M014",
          "M019", "M022", "M023", "M024", "M025", "M026", "M027", "M030",
          "M031", "M032", "M033", "M034", "M035", "M036", "M037", "M038",
          "M045", "M047"]
for mid in ORACLE:
    put(mid, "COVERED",
        [f"{ORC}test_metric_matches_its_independent_oracle[{mid}]",
         f"{ORC}test_the_oracles_are_not_vacuous"])
put("M038", "COVERED",
    [f"{ORC}test_no_published_period_exceeds_a_limit",
     f"{ORC}test_m038_counts_exactly_the_rows_over_their_limit"])
for mid in ("M043", "M044"):
    put(mid, "COVERED",
        [f"{ORC}test_m043_m044_match_the_published_sensitivity_relation"])
put("M046", "COVERED",
    [f"{ORC}test_m046_freshness_is_hours_since_the_release_publication"])
put("M049", "COVERED",
    [f"{L}test_m049_counts_the_material_changes_of_each_lens_latest_refresh"])
put("M050", "COVERED",
    [f"{L}test_m050_is_hours_since_each_lens_last_successful_refresh"])

# ---- ML path (runs on the candidate interpreter; skips on the accepted) -----
put("M042", "COVERED", [f"{ML}test_m042_reads_the_published_gap_per_ml_result"])
put("DECOMP02", "COVERED",
    [f"{ML}test_decomp02_booked_and_model_baselines_are_both_published"])
put("DECOMP03", "COVERED",
    [f"{ML}test_decomp03_the_gap_is_not_inside_the_scenario_effect"])
# DECOMP10: the P0 "environment-bound" failure was a real name overlap that
# the accepted interpreter could not see (no ML). Fixed; must pass on .venv.
put("DECOMP10", "COVERED", [])

# ---- Lenses ------------------------------------------------------------------------
put("LENS-04", "COVERED",
    [f"{L}test_m065_m066_overlay_match_the_published_ifrs9_overlay",
     f"{L}test_lens04_renders_the_overlay_and_reconciliation"])
for lid in ("LENS-05", "LENS-08"):
    put(lid, "COVERED",
        [f"{L}test_m069_reasons_match_each_rule_recomputed",
         f"{L}test_reason_visuals_render_and_honour_the_lens_filter"])
put("LENS-06", "COVERED",
    [f"{L}test_lens06_shows_booked_ecl_and_its_sector_breakdown"])
put("LENS-12", "COVERED",
    [f"{L}test_recoveries_and_write_offs_match_the_published_rows",
     f"{L}test_lens12_renders_recoveries_vs_write_offs"])
put("LENS-18", "COVERED",
    [f"{L}test_lens18_alert_groups_match_the_alert_store",
     f"{L}test_m050_is_hours_since_each_lens_last_successful_refresh",
     f"{L}test_m049_counts_the_material_changes_of_each_lens_latest_refresh"])
put("LENS-09", "PARTIAL",
    [f"{L}test_the_salary_signal_is_the_labelled_governed_proxy",
     f"{L}test_reason_visuals_render_and_honour_the_lens_filter"],
    gap=("DATA: the Retail book publishes no salary-credit feed. The Lens "
         "shows the governed salary-interruption PROXY (EWS rule R-SALARY: "
         "salaried, cyclical employer, payment ratio < 35%), labelled as a "
         "proxy; affordability, DPD, PD/ECL and default entry are complete."))
put("LENS-16", "PARTIAL",
    [f"{L}test_lens16_method_concentration_and_stage_views_read_the_result"],
    gap=("DATA/MODEL: scenario-induced STAGE MIGRATION is not modelled -- the "
         "stage policy holds stages and neither book publishes a SICR re-test "
         "rule (DECOMP12). The Lens shows ECL change by stage under the "
         "result's own policy, labelled as not migration; saved scenarios, "
         "ECL deltas, concentration (Pareto) and method comparison are "
         "complete."))
# ---- Guided Cockpit ----------------------------------------------------------------
put("GX-08", "COVERED", [f"{W}test_the_issue_card_has_no_decorative_controls"],
    journeys=["GW-P16-01"])
for rid in ("GX-03", "GX-10"):
    put(rid, E[rid]["claim"], [f"{W}test_the_issue_card_has_no_decorative_controls"],
        journeys=["GW-P16-02"], gap=E[rid]["gap"])

# ---- the P16 mutation gates bound to what they protect ----------------------------
for rid, gate in (("DECOMP10", "ML input labels apart from drivers (DECOMP10)"),
                  ("LENS-05", "EWS reasons evaluate each rule's own condition"),
                  ("LENS-08", "EWS reasons evaluate each rule's own condition")):
    checks = [c for c in E[rid].get("checks", []) if c != f"mutation:{gate}"]
    E[rid]["checks"] = [*checks, f"mutation:{gate}"]

left = [k for k, v in E.items() if v["claim"].startswith("PENDING")]
assert not left, left
P.write_text(json.dumps(E, indent=1, ensure_ascii=False), encoding="utf-8")
print("curated", len(E))
