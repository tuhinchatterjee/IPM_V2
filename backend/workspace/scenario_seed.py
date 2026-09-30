"""The Scenario Library's first-launch catalogue (§44): 18 Corporate, 18 Retail.

Every template is an editable Scenario Definition -- scope, typed components,
stage policy, composition policy, method compatibility, severity and tags --
and never answer text. Nothing here carries a number the engine would report:
a template's sample preview is computed live from the book it is opened
against (`scenario_library.preview`).

Where §44 names something the candidate books spell differently, the mapping
is stated in the template's own limitations rather than silently substituted:

* "CRE" -> the Corporate sector `Real Estate`;
* "Oil & Gas" -> the Corporate sector `Petrochemicals` (the book has no
  upstream oil and gas sector);
* "Home Finance" -> the Retail product `Mortgage`;
* "Variable-rate retail" -> the Retail sub-product `Variable Rate`;
* "Newest 6-month vintages" -> `months_on_book <= 6`;
* "Salary interruption signal" -> the governed EWS proxy R-SALARY (the book
  publishes no salary-credit feed).

Components are typed (`scenario_library.KINDS`). A component the book cannot
translate through a governed mapping is kept, labelled NEEDS_USER_MAPPING or
UNSUPPORTED in the preview, and never guessed.
"""

from __future__ import annotations

from typing import Any

SEED_VERSION = "gw-scenario-seed-1.0.0"


# ---- component builders -------------------------------------------------------

def _p(field: str, operation: str, value: str, label: str,
       where: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {"kind": "parameter", "field": field, "operation": operation,
            "value": value, "label": label, "where": where or []}


def _util(value: str, label: str) -> dict[str, Any]:
    return {"kind": "utilisation", "operation": "relative_pct", "value": value,
            "label": label, "where": []}


def _rating(notches: str, label: str) -> dict[str, Any]:
    return {"kind": "rating", "operation": "notches", "value": notches,
            "label": label, "where": []}


def _score(score_type: str, operation: str, value: str, label: str
           ) -> dict[str, Any]:
    return {"kind": "score", "score_type": score_type, "operation": operation,
            "value": value, "label": label, "where": []}


def _dpd(bands: str, label: str) -> dict[str, Any]:
    return {"kind": "delinquency", "operation": "bands", "value": bands,
            "label": label, "where": []}


def _macro(factor_id: str, operation: str, value: str, label: str,
           where: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {"kind": "macro", "factor_id": factor_id, "operation": operation,
            "value": value, "label": label, "where": where or []}


def _collateral(asset: str, value: str, label: str) -> dict[str, Any]:
    return {"kind": "collateral", "asset": asset, "operation": "relative_pct",
            "value": value, "label": label, "where": []}


def _overlay(value: str, label: str) -> dict[str, Any]:
    return {"kind": "overlay", "operation": "relative_pct", "value": value,
            "label": label, "where": []}


def _in(column: str, *values: Any) -> dict[str, Any]:
    return {"column": column, "op": "in", "values": list(values)}


def _cmp(column: str, op: str, value: Any) -> dict[str, Any]:
    return {"column": column, "op": op, "value": value}


def _scope(label: str, *filters: dict[str, Any]) -> dict[str, Any]:
    return {"type": "filters", "label": label, "filters": list(filters)}


WHOLE = {"type": "whole_book", "label": "Whole active book"}

ALL3 = ["delta", "ml", "user_defined"]
DU = ["delta", "user_defined"]


def _t(template_id: str, name: str, domain: str, *, description: str,
       thesis: str, scope: dict[str, Any], components: list[dict[str, Any]],
       stage_policy: str = "frozen", methods: list[str] | None = None,
       severity: str = "moderate", tags: list[str] | None = None,
       resolutions: dict[str, Any] | None = None,
       assumptions: list[str] | None = None,
       limitations: list[str] | None = None,
       bounds: dict[str, Any] | None = None,
       composition_note: str = "") -> dict[str, Any]:
    for i, c in enumerate(components, 1):
        c.setdefault("component_id", f"c{i}")
        c.setdefault("priority", i)
    return {
        "template_id": template_id, "name": name, "domain_id": domain,
        "description": description, "risk_thesis": thesis, "scope": scope,
        "components": components, "stage_policy": stage_policy,
        "composition_policy": {"resolutions": resolutions or {},
                               "note": composition_note},
        "supported_methods": methods or ALL3, "severity": severity,
        "tags": tags or [], "assumptions": assumptions or [],
        "limitations": limitations or [], "bounds_policy": bounds or {},
        "status": "TEMPLATE", "baseline": {"kind": "reported"},
        "bound_cohort": None, "seed_version": SEED_VERSION,
    }


CORP = "corporate"
RET = "retail"

TEMPLATES: tuple[dict[str, Any], ...] = (
    # ---------------------------------------------------------------- Corporate
    _t("CORP-01", "Construction PD deterioration", CORP,
       description="Relative PD stress on every Construction facility, stages "
                   "held.",
       thesis="Payment delays on public projects and input-cost inflation "
              "raise default risk across contractors.",
       scope=_scope("Sector: Construction", _in("sector", "Construction")),
       components=[_p("pd_pit_12m", "relative_pct", "20", "PD +20% relative")],
       tags=["sector", "pd", "construction"], severity="moderate"),
    _t("CORP-02", "Construction PD+LGD downside", CORP,
       description="PD and LGD stressed together on Construction; run "
                   "several methods side by side.",
       thesis="Contractor distress coincides with weaker recoveries on "
              "work-in-progress collateral.",
       scope=_scope("Sector: Construction", _in("sector", "Construction")),
       components=[_p("pd_pit_12m", "relative_pct", "20", "PD +20% relative"),
                   _p("lgd_pct", "relative_pct", "10", "LGD +10% relative")],
       tags=["sector", "pd", "lgd", "construction", "compare-methods"],
       severity="severe",
       composition_note="PD and LGD are different variables; Delta compounds "
                        "them multiplicatively on booked ECL (documented "
                        "rule), so no overlap policy is needed."),
    _t("CORP-03", "Commercial real-estate collateral shock", CORP,
       description="Commercial property values fall 15% and an explicit LGD "
                   "overlay of +8% is applied to Real Estate.",
       thesis="A CRE correction erodes collateral cover and recoveries.",
       scope=_scope("Sector: Real Estate (CRE)", _in("sector", "Real Estate")),
       components=[_collateral("commercial_property", "-15",
                               "Commercial property value -15%"),
                   _p("lgd_pct", "relative_pct", "8",
                      "LGD overlay +8% relative")],
       tags=["sector", "collateral", "lgd", "real-estate", "macro"],
       severity="severe",
       resolutions={"c1|c2|lgd": {"policy": "compound",
                                  "chosen_by": "library template",
                                  "order": ["c1", "c2"]}},
       composition_note="Both rules reach LGD. The template states its "
                        "policy explicitly: the collateral translation "
                        "first, then the +8% overlay (compound).",
       limitations=["CRE is mapped to the book's `Real Estate` sector.",
                    "The collateral move translates to LGD only through the "
                    "governed commercial-property sensitivity (MEV10)."]),
    _t("CORP-04", "Oil price downside", CORP,
       description="Oil price -20% translated into PD/LGD through the governed "
                   "MEV sensitivity library.",
       thesis="Lower oil revenue weakens petrochemical margins and the "
              "wider supply chain.",
       scope=_scope("Sector: Petrochemicals (Oil & Gas)",
                    _in("sector", "Petrochemicals")),
       components=[_macro("MEV07", "relative_percent", "-20",
                          "Oil price -20%")],
       tags=["macro", "oil", "sensitivity"], severity="moderate",
       limitations=["'Oil & Gas' is mapped to the book's `Petrochemicals` "
                    "sector; there is no upstream sector in this book."]),
    _t("CORP-05", "GDP recession", CORP,
       description="Real GDP growth -1.5 pp and unemployment +100 bps across "
                   "the whole book.",
       thesis="A broad recession raises default risk in every sector.",
       scope=WHOLE,
       components=[_macro("MEV01", "percentage_points", "-1.5",
                          "Real GDP growth -1.5 pp"),
                   _macro("MEV03", "basis_points", "100",
                          "Unemployment +100 bps")],
       tags=["macro", "combined", "recession"], severity="severe",
       composition_note="Macro factors combine through the governed §7.2 "
                        "linear sum of sensitivity x change."),
    _t("CORP-06", "Rates +200 bps", CORP,
       description="Policy rate +200 bps on rate-sensitive sectors.",
       thesis="Higher funding costs bite hardest on leveraged, long-dated "
              "sectors.",
       scope=_scope("Rate-sensitive sectors",
                    _in("sector", "Real Estate", "Construction", "Hospitality",
                        "Retail Trade")),
       components=[_macro("MEV05", "basis_points", "200",
                          "Policy rate +200 bps")],
       tags=["macro", "rates", "sector"], severity="moderate",
       assumptions=["Rate-sensitive = Real Estate, Construction, Hospitality "
                    "and Retail Trade. Edit the scope to change it."]),
    _t("CORP-07", "One-notch downgrade", CORP,
       description="Every borrower rated BBB- and below moves one notch down "
                   "the published masterscale.",
       thesis="A cyclical downturn drives broad one-notch migration in the "
              "sub-investment-grade book.",
       scope=_scope("Rated BBB- and below",
                    _in("rating_current", "BBB-", "BB+", "BB", "BB-", "B+",
                        "B")),
       components=[_rating("1", "Rating -1 notch")],
       tags=["rating", "migration"], severity="moderate",
       assumptions=["Stages are held; the stage policy is explicit and can "
                    "be changed to a SICR re-test."]),
    _t("CORP-08", "Two-notch downgrade severe", CORP,
       description="Borrowers rated BB and below move two notches down; SICR "
                   "re-test enabled.",
       thesis="A severe downturn concentrates migration in the weakest "
              "grades.",
       scope=_scope("Rated BB and below",
                    _in("rating_current", "BB", "BB-", "B+", "B")),
       components=[_rating("2", "Rating -2 notches")],
       stage_policy="retest_sicr",
       tags=["rating", "migration", "sicr"], severity="severe"),
    _t("CORP-09", "LGD recovery deterioration", CORP,
       description="LGD +5 percentage points on Stage 2 and Stage 3 "
                   "facilities.",
       thesis="Longer workouts and weaker collateral markets reduce "
              "recoveries on impaired names.",
       scope=_scope("Stage 2 and 3", _in("stage", 2, 3)),
       components=[_p("lgd_pct", "absolute_pp", "5", "LGD +5 pp")],
       tags=["lgd", "recoveries", "stage"], severity="moderate"),
    _t("CORP-10", "CCF utilisation stress", CORP,
       description="CCF +15% relative on revolving and working-capital lines "
                   "with undrawn commitments.",
       thesis="Stressed borrowers draw down committed lines before default.",
       scope=_scope("Revolvers / working capital with undrawn",
                    _in("product_type", "Revolving Credit Facility",
                        "Working Capital Line"),
                    _cmp("undrawn_sar_mn", "gt", 0)),
       components=[_p("ccf", "relative_pct", "15", "CCF +15% relative")],
       methods=DU, tags=["ccf", "ead", "exposure"], severity="moderate"),
    _t("CORP-11", "Top-20 obligor concentration shock", CORP,
       description="PD +25% and LGD +10% on the 20 largest borrowers by EAD.",
       thesis="Single-name concentration: a shock to the largest obligors "
              "moves the book.",
       scope={"type": "top_owners", "label": "Top 20 borrowers by EAD",
              "n": 20, "by": "ead_sar_mn"},
       components=[_p("pd_pit_12m", "relative_pct", "25", "PD +25% relative"),
                   _p("lgd_pct", "relative_pct", "10", "LGD +10% relative")],
       tags=["concentration", "pd", "lgd"], severity="severe"),
    _t("CORP-12", "Hospitality downside", CORP,
       description="PD +30% on Hospitality.",
       thesis="Demand shock to tourism and events.",
       scope=_scope("Sector: Hospitality", _in("sector", "Hospitality")),
       components=[_p("pd_pit_12m", "relative_pct", "30", "PD +30% relative")],
       tags=["sector", "pd", "hospitality"], severity="severe"),
    _t("CORP-13", "Trade & manufacturing slowdown", CORP,
       description="PD +15% and utilisation +10% on trade and manufacturing.",
       thesis="Slower trade flows stretch working capital and raise "
              "default risk.",
       scope=_scope("Trade + Manufacturing",
                    _in("sector", "Wholesale Trade", "Retail Trade",
                        "Manufacturing")),
       components=[_p("pd_pit_12m", "relative_pct", "15", "PD +15% relative"),
                   _util("10", "Utilisation +10% (drawn +10%, limit fixed)")],
       tags=["sector", "pd", "utilisation", "compound"], severity="moderate",
       composition_note="PD and drawn balance are different variables; both "
                        "rules are visible in the component matrix."),
    _t("CORP-14", "Stage migration re-test", CORP,
       description="PD +20% on Stage 1 high-risk grades with a SICR re-test.",
       thesis="Deterioration in weak Stage 1 names may cross SICR "
              "thresholds.",
       scope=_scope("Stage 1, rated BB- and below", _in("stage", 1),
                    _in("rating_current", "BB-", "B+", "B")),
       components=[_p("pd_pit_12m", "relative_pct", "20", "PD +20% relative")],
       stage_policy="retest_sicr",
       tags=["stage", "sicr", "pd"], severity="moderate"),
    _t("CORP-15", "Severe GCC downturn", CORP,
       description="GDP -3 pp, oil -30%, unemployment +200 bps and rates "
                   "+250 bps across the book.",
       thesis="A regional shock combining oil, growth, labour and rates.",
       scope=WHOLE,
       components=[_macro("MEV01", "percentage_points", "-3",
                          "Real GDP growth -3 pp"),
                   _macro("MEV07", "relative_percent", "-30", "Oil price -30%"),
                   _macro("MEV03", "basis_points", "200",
                          "Unemployment +200 bps"),
                   _macro("MEV05", "basis_points", "250",
                          "Policy rate +250 bps")],
       tags=["macro", "combined", "severe"], severity="severe",
       composition_note="Macro factors combine through the governed §7.2 "
                        "linear sum; the preview warns that summed marginal "
                        "slopes are not a joint model."),
    _t("CORP-16", "Management overlay + downside", CORP,
       description="PD +10% on a selected sector plus a user-defined ECL "
                   "overlay of +5%.",
       thesis="Model outputs are supplemented by an explicit management "
              "judgement.",
       scope=_scope("Sector: Construction (edit to select)",
                    _in("sector", "Construction")),
       components=[_p("pd_pit_12m", "relative_pct", "10", "PD +10% relative"),
                   _overlay("5", "User overlay +5% ECL")],
       methods=DU, tags=["overlay", "user-defined", "pd"], severity="mild",
       composition_note="The overlay applies after parameter moves; it is a "
                        "user-defined component and is never estimated."),
    _t("CORP-17", "Cure sensitivity upside", CORP,
       description="PD -15% on Stage 2 with a cure (stage re-test) "
                   "assumption.",
       thesis="Improving conditions allow Stage 2 names to cure.",
       scope=_scope("Stage 2", _in("stage", 2)),
       components=[_p("pd_pit_12m", "relative_pct", "-15", "PD -15% relative")],
       stage_policy="cure_retest", severity="upside",
       tags=["upside", "cure", "stage"],
       bounds={"ecl_floor_sar_mn": "0",
               "note": "No exposure's ECL may go below zero."}),
    _t("CORP-18", "Combined sector + macro stress", CORP,
       description="Construction PD +20% and Real Estate LGD +10%, plus a "
                   "GDP -1.5 pp macro downside over both sectors.",
       thesis="A sector-specific shock on top of a macro downturn.",
       scope={"type": "any_of", "label": "Construction + Real Estate",
              "scopes": [_scope("Construction", _in("sector", "Construction")),
                         _scope("Real Estate", _in("sector", "Real Estate"))]},
       components=[_p("pd_pit_12m", "relative_pct", "20",
                      "Construction PD +20% relative",
                      where=[_in("sector", "Construction")]),
                   _p("lgd_pct", "relative_pct", "10",
                      "Real Estate LGD +10% relative",
                      where=[_in("sector", "Real Estate")]),
                   _macro("MEV01", "percentage_points", "-1.5",
                          "Real GDP growth -1.5 pp")],
       tags=["combined", "macro", "sector", "overlap"], severity="severe",
       composition_note="The macro move and the sector rules both reach PD "
                        "and LGD on the same facilities. Execution is blocked "
                        "until a composition policy is chosen for each "
                        "overlap."),

    # ---------------------------------------------------------------- Retail
    _t("RET-01", "Credit Card PD deterioration", RET,
       description="PD +20% relative on Credit Card, stages held.",
       thesis="Revolving consumer credit deteriorates first in a downturn.",
       scope=_scope("Product: Credit Card", _in("product", "Credit Card")),
       components=[_p("pd_pit_12m", "relative_pct", "20", "PD +20% relative")],
       tags=["product", "pd", "credit-card"], severity="moderate"),
    _t("RET-02", "Credit Card utilisation stress", RET,
       description="Balances +10% (utilisation) and CCF +10% on Credit Card.",
       thesis="Cardholders draw more of their limits under stress.",
       scope=_scope("Product: Credit Card", _in("product", "Credit Card")),
       components=[_util("10", "Utilisation +10% (balance +10%, limit fixed)"),
                   _p("ccf", "relative_pct", "10", "CCF +10% relative")],
       methods=DU, tags=["utilisation", "ccf", "ead", "credit-card"],
       severity="moderate",
       limitations=["Retail publishes no CCF column; the CCF rule is shown "
                    "as unsupported rather than applied."]),
    _t("RET-03", "Behaviour score deterioration", RET,
       description="Behaviour score -30 points, re-banded through the "
                   "governed product scorecards.",
       thesis="Rising indebtedness shows up in behavioural scores before "
              "arrears.",
       scope=_scope("Credit Card + Personal Finance",
                    _in("product", "Credit Card", "Personal Finance")),
       components=[_score("BEHAVIOURAL", "points", "-30",
                          "Behaviour score -30 points")],
       tags=["score", "behavioural", "migration"], severity="moderate",
       assumptions=["Direction is read from the scorecard metadata "
                    "(HIGHER_IS_SAFER)."]),
    _t("RET-04", "Application score downgrade", RET,
       description="Application score one band worse for new accounts.",
       thesis="Weaker origination quality in the newest book.",
       scope=_scope("New accounts (months on book <= 6)",
                    _cmp("months_on_book", "lte", 6)),
       components=[_score("APPLICATION", "bands", "-1",
                          "Application score -1 band")],
       methods=["user_defined"], tags=["score", "application", "origination"],
       severity="mild",
       limitations=["The application score is fixed at origination; the "
                    "governed application scorecard's band PD is shown for "
                    "information and execution needs a user-defined impact."]),
    _t("RET-05", "DPD migration stress", RET,
       description="Current accounts shift one delinquency band worse.",
       thesis="Payment stress moves current accounts into early arrears.",
       scope=_scope("0-29 DPD (Current)", _in("delinquency_bucket", "Current")),
       components=[_dpd("1", "Delinquency +1 band")],
       methods=["user_defined"], tags=["delinquency", "dpd", "migration"],
       severity="moderate",
       limitations=["No governed delinquency-to-PD mapping is published; the "
                    "preview shows the band movement and execution needs a "
                    "user-defined PD effect."]),
    _t("RET-06", "Personal Finance PD+LGD", RET,
       description="PD +15% and LGD +5% relative on Personal Finance.",
       thesis="Unsecured consumer lending under affordability pressure.",
       scope=_scope("Product: Personal Finance",
                    _in("product", "Personal Finance")),
       components=[_p("pd_pit_12m", "relative_pct", "15", "PD +15% relative"),
                   _p("lgd_pct", "relative_pct", "5", "LGD +5% relative")],
       tags=["product", "pd", "lgd", "compare-methods"], severity="moderate"),
    _t("RET-07", "Home Finance collateral shock", RET,
       description="Residential property values -15%, translated to LGD "
                   "through the governed property sensitivity.",
       thesis="A housing correction raises loss severity on mortgages.",
       scope=_scope("Product: Mortgage (Home Finance)",
                    _in("product", "Mortgage")),
       components=[_collateral("residential_property", "-15",
                               "Residential property value -15%")],
       tags=["collateral", "lgd", "mortgage", "macro"], severity="moderate",
       limitations=["'Home Finance' is mapped to the book's `Mortgage` "
                    "product."]),
    _t("RET-08", "Auto Finance collateral shock", RET,
       description="Vehicle values -20%; LGD translation requires a "
                   "user-defined mapping.",
       thesis="Used-car price falls reduce recoveries on repossession.",
       scope=_scope("Product: Auto Finance", _in("product", "Auto Finance")),
       components=[_collateral("vehicle", "-20", "Vehicle value -20%")],
       methods=["user_defined"], tags=["collateral", "lgd", "auto"],
       severity="moderate",
       limitations=["No governed vehicle-value index or sensitivity exists "
                    "in this book; state the LGD effect to run it."]),
    _t("RET-09", "Unemployment shock", RET,
       description="Unemployment +100 bps across the Retail book.",
       thesis="Job losses drive consumer defaults.",
       scope=WHOLE,
       components=[_macro("MEV03", "basis_points", "100",
                          "Unemployment +100 bps")],
       tags=["macro", "unemployment"], severity="moderate"),
    _t("RET-10", "Rate shock", RET,
       description="Policy rate +200 bps on variable-rate retail.",
       thesis="Payment shock on floating-rate borrowers.",
       scope=_scope("Variable-rate (sub-product Variable Rate)",
                    _in("sub_product", "Variable Rate")),
       components=[_macro("MEV05", "basis_points", "200",
                          "Policy rate +200 bps")],
       tags=["macro", "rates", "affordability"], severity="moderate"),
    _t("RET-11", "Salary interruption cluster", RET,
       description="PD +25% on customers carrying the salary-interruption "
                   "EWS signal.",
       thesis="Salary interruption at cyclical employers precedes default.",
       scope=_scope("EWS salary-interruption proxy",
                    _in("employment_type", "Salaried-Private",
                        "Salaried-Government"),
                    _in("employer_sector_group", "Cyclical"),
                    _cmp("payment_ratio_pct", "lt", 35)),
       components=[_p("pd_pit_12m", "relative_pct", "25", "PD +25% relative")],
       tags=["ews", "salary", "pd"], severity="severe",
       limitations=["The book has no salary-credit feed; the cohort is the "
                    "governed EWS proxy R-SALARY (gw-ews-1.0.0)."]),
    _t("RET-12", "Persistent minimum payment", RET,
       description="PD +20% and utilisation +10% on the Credit Card "
                   "minimum-payment warning cohort.",
       thesis="Minimum-payment behaviour signals stretched households.",
       scope=_scope("Credit Card, persistent minimum payment (EWS)",
                    _in("product", "Credit Card"),
                    _cmp("ews_reasons", "contains",
                         "Persistent minimum payment")),
       components=[_p("pd_pit_12m", "relative_pct", "20", "PD +20% relative"),
                   _util("10", "Utilisation +10% (balance +10%, limit fixed)")],
       tags=["ews", "credit-card", "pd", "utilisation"], severity="moderate"),
    _t("RET-13", "Affordability deterioration", RET,
       description="PD +20% and behaviour score one band worse on Personal "
                   "Finance.",
       thesis="Cost-of-living pressure weakens repayment capacity.",
       scope=_scope("Product: Personal Finance",
                    _in("product", "Personal Finance")),
       components=[_p("pd_pit_12m", "relative_pct", "20", "PD +20% relative"),
                   _score("BEHAVIOURAL", "bands", "-1",
                          "Behaviour score -1 band")],
       tags=["score", "pd", "affordability", "compound"], severity="severe",
       resolutions={"c1|c2|pd": {"policy": "compound",
                                  "chosen_by": "library template",
                                  "order": ["c2", "c1"]}},
       composition_note="Both rules reach PD. The template states its policy "
                        "explicitly: re-band first, then apply +20% "
                        "(compound). Change it before running if you "
                        "prefer most-severe-wins."),
    _t("RET-14", "High utilisation + delinquency", RET,
       description="Balances +15% and one delinquency band worse on Credit "
                   "Card.",
       thesis="Cards run up to limits and slip into arrears together.",
       scope=_scope("Product: Credit Card", _in("product", "Credit Card")),
       components=[_util("15", "Utilisation +15% (balance +15%, limit fixed)"),
                   _dpd("1", "Delinquency +1 band")],
       methods=["user_defined"],
       tags=["utilisation", "delinquency", "overlap"], severity="severe"),
    _t("RET-15", "Vintage downside", RET,
       description="PD +25% on the newest six months of vintages.",
       thesis="Recent vintages are unseasoned and underwritten late in the "
              "cycle.",
       scope=_scope("Newest 6-month vintages", _cmp("months_on_book", "lte", 6)),
       components=[_p("pd_pit_12m", "relative_pct", "25", "PD +25% relative")],
       tags=["vintage", "pd"], severity="moderate"),
    _t("RET-16", "Severe household downturn", RET,
       description="Unemployment +200 bps, rates +250 bps and house prices "
                   "-20% across Retail.",
       thesis="A combined labour, rates and housing shock to households.",
       scope=WHOLE,
       components=[_macro("MEV03", "basis_points", "200",
                          "Unemployment +200 bps"),
                   _macro("MEV05", "basis_points", "250",
                          "Policy rate +250 bps"),
                   _macro("MEV09", "relative_percent", "-20",
                          "House prices -20%")],
       tags=["macro", "combined", "severe"], severity="severe",
       composition_note="Macro factors combine through the governed §7.2 "
                        "linear sum."),
    _t("RET-17", "Cure sensitivity upside", RET,
       description="PD -10% and one delinquency band better on delinquent "
                   "accounts.",
       thesis="Recovering household finances cure early arrears.",
       scope={"type": "any_of", "label": "Stage 2+ or delinquent",
              "scopes": [_scope("Stage 2+", _cmp("stage", "gte", 2)),
                         _scope("Delinquent", _cmp("delinquency_bucket", "neq",
                                                  "Current"))]},
       components=[_p("pd_pit_12m", "relative_pct", "-10", "PD -10% relative"),
                   _dpd("-1", "Delinquency -1 band")],
       methods=["user_defined"], stage_policy="cure_retest",
       tags=["upside", "cure", "delinquency"], severity="upside",
       resolutions={"c1|c2|pd": {"policy": "compound",
                                  "chosen_by": "library template",
                                  "order": ["c2", "c1"]}},
       composition_note="Both rules reach PD: the cure band move first, "
                        "then -10% (compound), stated explicitly.",
       bounds={"ecl_floor_sar_mn": "0",
               "note": "No exposure's ECL may go below zero."}),
    _t("RET-18", "Combined EWS + macro stress", RET,
       description="PD +20% on high/critical EWS accounts plus unemployment "
                   "+100 bps.",
       thesis="Warned customers are hit hardest by a macro downturn.",
       scope=_scope("EWS band high or critical",
                    _in("ews_band", "high", "critical")),
       components=[_p("pd_pit_12m", "relative_pct", "20", "PD +20% relative"),
                   _macro("MEV03", "basis_points", "100",
                          "Unemployment +100 bps")],
       tags=["ews", "macro", "combined", "overlap"], severity="severe",
       composition_note="Both rules reach PD on the same accounts. Choose "
                        "compound or most-severe-wins before running."),
)


def by_id() -> dict[str, dict[str, Any]]:
    return {t["template_id"]: t for t in TEMPLATES}


__all__ = ["SEED_VERSION", "TEMPLATES", "by_id"]
