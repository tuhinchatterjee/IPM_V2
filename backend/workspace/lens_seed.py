"""The Lens Library seed (§45): persona Lenses on governed metrics.

Every KPI, chart and breach rule names a Metric Catalogue id (and the version
is pinned when the Lens is seeded); nothing on a Lens is free-text
arithmetic. Visual types are the renderer's closed vocabulary
(`lenses.VISUALS`). Scope values are the candidate books' own categories
(Retail "Home Finance" is the `Mortgage` product in this book, and says so).

Refresh cadences are the Lens's DEFAULT; P10's Monitoring Centre runs them.
"""

from __future__ import annotations

from typing import Any

SEED_VERSION = "gw-lens-seed-1.1.0"
CORP, RET = "corporate", "retail"
TZ = "Asia/Riyadh"


def K(metric_id: str, domain: str, label: str = "") -> dict[str, Any]:
    """A KPI tile: value, prior, movement and a sparkline."""
    return {"type": "kpi", "metric_id": metric_id, "domain": domain,
            "title": label}


def T(metric_ids: list[str], domain: str, title: str, periods: int = 8
      ) -> dict[str, Any]:
    return {"type": "trend", "metric_ids": metric_ids, "domain": domain,
            "title": title, "periods": periods}


def B(metric_id: str, domain: str, by: str, title: str) -> dict[str, Any]:
    return {"type": "breakdown", "metric_id": metric_id, "domain": domain,
            "group_by": by, "title": title}


def S(domain: str, title: str = "") -> dict[str, Any]:
    return {"type": "stage_mix", "metric_id": "M018", "domain": domain,
            "group_by": "stage", "title": title or "EAD by stage"}


def TOP(domain: str, title: str = "") -> dict[str, Any]:
    return {"type": "top_owners", "metric_id": "M021", "domain": domain,
            "title": title or "Largest names by EAD", "n": 10}


def SCN(domain: str) -> dict[str, Any]:
    return {"type": "scenario_results", "metric_id": "M039", "domain": domain,
            "title": "Executed scenarios: selected-scope ECL Δ"}


def ALR(domain: str) -> dict[str, Any]:
    return {"type": "alerts", "metric_id": "M048", "domain": domain,
            "title": "Active breaches by Lens"}


def SENS(domain: str) -> dict[str, Any]:
    return {"type": "sensitivity", "metric_id": "M043", "domain": domain,
            "title": "Governed MEV sensitivities"}


def G(metric_id: str, domain: str, title: str) -> dict[str, Any]:
    """One bar per named group a catalogue evaluator publishes (EWS rules,
    alert states / metrics / owners, a result's methods / segments /
    stages)."""
    return {"type": "groups", "metric_id": metric_id, "domain": domain,
            "title": title}


def TAB(domain: str, columns: list[str], sort: str = "ecl_sar_mn",
        title: str = "Exposures") -> dict[str, Any]:
    return {"type": "table", "domain": domain, "columns": columns,
            "sort": sort, "title": title, "metric_id": "M018"}


def R(rule_id: str, name: str, metric_id: str, domain: str, op: str,
      threshold: float, severity: str = "high", *, window: str = "latest",
      materiality: float | None = None, cooldown_hours: int = 24,
      recipients: list[str] | None = None) -> dict[str, Any]:
    """A breach rule: comparison over one governed metric."""
    return {"rule_id": rule_id, "name": name, "metric_id": metric_id,
            "domain": domain, "comparison": op, "threshold": threshold,
            "window": window, "materiality": materiality,
            "dedup_key": f"{rule_id}:{domain}", "cooldown_hours":
            cooldown_hours, "severity": severity,
            "recipients": recipients or ["owner"]}


CORP_TABLE = ["borrower_name", "sector", "rating_current", "stage",
              "ead_sar_mn", "ecl_sar_mn", "pd_pit_12m", "ews_band"]
RET_TABLE = ["customer_id", "product", "score_band", "delinquency_bucket",
             "stage", "ead_sar_mn", "ecl_sar_mn", "ews_band"]


def _lens(lens_id: str, name: str, persona: str, scope: list[str], *,
          description: str, refresh: str, visuals: list[dict[str, Any]],
          rules: list[dict[str, Any]] | None = None,
          filters: dict[str, list[dict[str, Any]]] | None = None,
          audience: list[str] | None = None, tags: list[str] | None = None,
          note: str = "") -> dict[str, Any]:
    for i, v in enumerate(visuals, 1):
        v.setdefault("visual_id", f"v{i:02d}")
    metrics: list[dict[str, Any]] = []
    for v in visuals:
        ids = v.get("metric_ids") or [v["metric_id"]]
        for mid in ids:
            key = {"metric_id": mid, "domain": v["domain"]}
            if key not in metrics:
                metrics.append(key)
    for r in rules or []:
        key = {"metric_id": r["metric_id"], "domain": r["domain"]}
        if key not in metrics:
            metrics.append(key)
    return {
        "lens_id": lens_id, "name": name, "description": description,
        "persona": persona, "domain_scope": scope, "metrics": metrics,
        "visuals": visuals,
        "layout": {"kpi_row": [v["visual_id"] for v in visuals
                               if v["type"] == "kpi"],
                   "grid": [v["visual_id"] for v in visuals
                            if v["type"] not in ("kpi", "table")],
                   "tables": [v["visual_id"] for v in visuals
                              if v["type"] == "table"]},
        "filters": filters or {},
        "refresh": {"cadence": refresh, "timezone": TZ,
                    "expected_availability": "after each governed release "
                    "publication (Corporate quarterly, Retail monthly)"},
        "breach_rules": rules or [],
        "audience": audience or [persona],
        "delivery": {"workspace": True, "inbox": True,
                     "digest": refresh in ("daily", "weekly", "monthly")},
        "tags": tags or [], "note": note, "status": "ACTIVE",
        "seed_version": SEED_VERSION,
    }


CARD = [{"column": "product", "op": "in", "values": ["Credit Card"]}]
PF = [{"column": "product", "op": "in", "values": ["Personal Finance"]}]
HOME = [{"column": "product", "op": "in", "values": ["Mortgage"]}]
AUTO = [{"column": "product", "op": "in", "values": ["Auto Finance"]}]
CRE = [{"column": "sector", "op": "in",
        "values": ["Construction", "Real Estate"]}]

LENSES: tuple[dict[str, Any], ...] = (
    _lens("LENS-01", "CRO Executive Overview", "CRO", [CORP, RET],
          description="Both books on one page: booked ECL and its movement, "
                      "Stage 2/3, defaults, early warning, concentration and "
                      "breaches.",
          refresh="daily",
          visuals=[K("M001", CORP, "Corporate ECL"), K("M001", RET, "Retail ECL"),
                   K("M005", CORP), K("M006", CORP), K("M012", CORP),
                   K("M032", RET), K("M020", CORP),
                   T(["M001"], CORP, "Corporate booked ECL"),
                   T(["M001"], RET, "Retail booked ECL"),
                   S(CORP, "Corporate EAD by stage"),
                   B("M033", RET, "product", "EWS high/critical share by product"),
                   ALR(CORP),
                   TOP(CORP, "Top-10 corporate names")],
          rules=[R("R01-1", "Corporate ECL up > 5% on the quarter", "M003",
                   CORP, "gt", 0.05, "high"),
                 R("R01-2", "Stage 3 share above 4%", "M006", CORP, "gt",
                   0.04, "critical")],
          tags=["executive", "both-books"]),
    _lens("LENS-02", "Head of Corporate Credit", "Corporate Credit Head",
          [CORP], description="Sector, rating, ECL, stage migration, top "
                              "obligors and covenants for the corporate book.",
          refresh="daily",
          visuals=[K("M001", CORP), K("M002", CORP), K("M009", CORP),
                   K("M023", CORP), K("M036", CORP),
                   B("M001", CORP, "sector", "Booked ECL by sector"),
                   B("M015", CORP, "rating_current", "EAD-weighted PD by rating"),
                   T(["M005", "M006"], CORP, "Stage 2 / Stage 3 EAD share"),
                   TOP(CORP), TAB(CORP, CORP_TABLE)],
          rules=[R("R02-1", "Downgrade rate above 15%", "M023", CORP, "gt",
                   0.15, "high"),
                 R("R02-2", "Covenant breach rate above 25%", "M036", CORP,
                   "gt", 0.25, "moderate")]),
    _lens("LENS-03", "Head of Retail Risk", "Retail Risk Head", [RET],
          description="Product EWS, delinquency, score migration, default "
                      "entry and ECL for the retail book.",
          refresh="daily",
          visuals=[K("M001", RET), K("M032", RET), K("M028", RET),
                   K("M012", RET), K("M026", RET),
                   B("M033", RET, "product", "EWS high/critical share by product"),
                   B("M001", RET, "product", "Booked ECL by product"),
                   T(["M054"], RET, "Past-due EAD"),
                   B("M058", RET, "product", "Deteriorated-score customers"),
                   TAB(RET, RET_TABLE)],
          rules=[R("R03-1", "30+ DPD rate above 1%", "M028", RET, "gt", 0.01,
                   "high"),
                 R("R03-2", "Warned customers up >10%", "M032", RET,
                   "move_pct_gt", 0.10, "moderate")]),
    _lens("LENS-04", "IFRS 9 / ECL Oversight", "IFRS 9 / ECL team",
          [CORP, RET], description="Booked ECL, stage shares, PD/LGD/EAD "
                                   "drivers, overlays and reconciliation.",
          refresh="on_publication",
          visuals=[K("M001", CORP), K("M052", CORP), K("M015", CORP),
                   K("M016", CORP), K("M047", CORP), K("M001", RET),
                   T(["M004", "M005", "M006"], CORP, "Stage EAD shares"),
                   T(["M007", "M008"], CORP, "Stage 2/3 ECL shares"),
                   B("M052", RET, "product", "ECL coverage by product"),
                   S(RET, "Retail EAD by stage"),
                   K("M065", CORP, "Corporate management overlay"),
                   K("M065", RET, "Retail management overlay"),
                   B("M065", CORP, "sector", "Management overlay by sector"),
                   B("M066", RET, "product", "Overlay share of ECL by product")],
          rules=[R("R04-1", "Reconciliation residual above tolerance",
                   "M047", CORP, "abs_gt", 1e-6, "critical")]),
    _lens("LENS-05", "Early Warning Command Center", "EWS team", [CORP, RET],
          description="Warned customers, high/critical, forward risk, top "
                      "reasons and deterioration cohorts.",
          refresh="daily",
          visuals=[K("M032", RET), K("M033", RET), K("M034", RET),
                   K("M063", CORP, "Corporate high/critical EWS EAD"),
                   K("M062", RET, "Retail warned EAD"),
                   B("M063", CORP, "sector", "High/critical EWS EAD by sector"),
                   B("M033", RET, "product", "High/critical share by product"),
                   T(["M032"], RET, "Warned customers"),
                   TAB(RET, RET_TABLE, sort="ews_score",
                       title="Highest EWS scores"),
                   G("M069", CORP, "Top warning reasons — Corporate"),
                   G("M069", RET, "Top warning reasons — Retail")],
          rules=[R("R05-1", "High/critical share above 20%", "M033", RET,
                   "gt", 0.20, "high")]),
    _lens("LENS-06", "Corporate Portfolio Manager", "Portfolio manager",
          [CORP], description="Sector and borrower concentration, rating "
                              "migration, limits and ECL.",
          refresh="daily",
          visuals=[K("M018", CORP), K("M020", CORP), K("M021", CORP),
                   K("M037", CORP), K("M025", CORP),
                   B("M022", CORP, "sector", "EAD share by sector"),
                   B("M019", CORP, "product_type", "Utilisation by product type"),
                   TOP(CORP), T(["M018"], CORP, "Total EAD"),
                   K("M001", CORP), K("M023", CORP),
                   B("M001", CORP, "sector", "Booked ECL by sector")],
          rules=[R("R06-1", "Top-10 concentration above 15%", "M020", CORP,
                   "gt", 0.15, "high")]),
    _lens("LENS-07", "Retail Portfolio Manager", "Portfolio manager", [RET],
          description="Product, vintage, score band, ECL and delinquency "
                      "trends.",
          refresh="daily",
          visuals=[K("M018", RET), K("M001", RET), K("M056", RET),
                   K("M061", RET), K("M054", RET),
                   B("M001", RET, "vintage_year", "Booked ECL by vintage"),
                   B("M018", RET, "score_band", "EAD by score band"),
                   T(["M015"], RET, "EAD-weighted PD"),
                   TAB(RET, RET_TABLE)],
          rules=[R("R07-1", "Weak score-band share above 25%", "M056", RET,
                   "gt", 0.25, "moderate")]),
    _lens("LENS-08", "Credit Card Risk", "Product risk head", [RET],
          description="Credit Card: EWS, utilisation, DPD, score bands and "
                      "ECL.",
          refresh="daily", filters={RET: CARD},
          visuals=[K("M001", RET), K("M019", RET), K("M032", RET),
                   K("M054", RET), K("M056", RET),
                   B("M018", RET, "score_band", "EAD by score band"),
                   B("M033", RET, "sub_product", "High/critical share by sub-product"),
                   T(["M019"], RET, "Utilisation"),
                   TAB(RET, RET_TABLE, sort="utilisation_pct",
                       title="Highest utilisation"),
                   G("M069", RET, "Top warning reasons")],
          rules=[R("R08-1", "Card utilisation above 75%", "M019", RET, "gt",
                   0.75, "moderate")]),
    _lens("LENS-09", "Personal Finance Risk", "Product risk head", [RET],
          description="Personal Finance: affordability (payment ratio), "
                      "salary signals (employment), DPD, PD/ECL and default "
                      "entry.",
          refresh="daily", filters={RET: PF},
          visuals=[K("M001", RET), K("M057", RET), K("M015", RET),
                   K("M012", RET), K("M054", RET),
                   B("M057", RET, "employment_type", "Payment ratio by employment type"),
                   B("M015", RET, "employer_sector_group", "PD by employer sector"),
                   T(["M001"], RET, "Booked ECL"),
                   TAB(RET, RET_TABLE),
                   G("M069", RET, "Warning reasons, incl. the salary-interruption proxy")],
          rules=[R("R09-1", "Average payment ratio below 30%", "M057", RET,
                   "lt", 0.30, "high")]),
    _lens("LENS-10", "Home Finance Risk", "Product risk head", [RET],
          description="Home Finance (the Mortgage product in this book): "
                      "LTV and collateral, DPD, stage, ECL and geographic "
                      "concentration.",
          refresh="weekly", filters={RET: HOME},
          visuals=[K("M001", RET), K("M053", RET), K("M054", RET),
                   K("M005", RET), K("M018", RET),
                   B("M053", RET, "region", "EAD-weighted LTV by region"),
                   B("M022", RET, "region", "EAD share by region"),
                   S(RET), TAB(RET, RET_TABLE, sort="ltv_pct",
                               title="Highest LTV")],
          rules=[R("R10-1", "EAD-weighted LTV above 80%", "M053", RET, "gt",
                   0.80, "moderate")],
          note="Retail 'Home Finance' is the Mortgage product in this book."),
    _lens("LENS-11", "Auto Finance Risk", "Product risk head", [RET],
          description="Auto Finance: LTV and collateral, DPD, stage, ECL and "
                      "vintage.",
          refresh="weekly", filters={RET: AUTO},
          visuals=[K("M001", RET), K("M053", RET), K("M054", RET),
                   K("M015", RET), K("M018", RET),
                   B("M001", RET, "vintage_year", "Booked ECL by vintage"),
                   B("M053", RET, "vintage_year", "LTV by vintage"),
                   S(RET), TAB(RET, RET_TABLE)],
          rules=[R("R11-1", "Past-due EAD up >10%", "M054", RET,
                   "move_pct_gt", 0.10, "moderate")]),
    _lens("LENS-12", "Collections & Recoveries", "Collections", [RET],
          description="Delinquency buckets, roll and cure rates, recoveries "
                      "and write-offs, Stage 3/NPL exposure.",
          refresh="daily",
          visuals=[K("M054", RET), K("M030", RET), K("M031", RET),
                   K("M014", RET), K("M013", RET),
                   B("M018", RET, "delinquency_bucket", "EAD by delinquency bucket"),
                   B("M054", RET, "product", "Past-due EAD by product"),
                   T(["M030", "M031"], RET, "Roll-forward vs cure rate"),
                   TAB(RET, RET_TABLE, sort="dpd_days",
                       title="Most days past due"),
                   K("M067", RET, "Recoveries"),
                   T(["M067", "M068"], RET, "Recoveries vs write-offs", 12),
                   B("M067", RET, "product", "Recoveries by product")],
          rules=[R("R12-1", "Roll-forward rate above 5%", "M030", RET, "gt",
                   0.05, "high")]),
    _lens("LENS-13", "Risk Appetite & Limits", "CRO / Risk Appetite",
          [CORP, RET], description="Limit utilisation, breaches, "
                                   "concentration and sector/product "
                                   "appetite.",
          refresh="daily",
          visuals=[K("M037", CORP), K("M038", CORP), K("M020", CORP),
                   K("M037", RET), K("M021", CORP),
                   B("M037", CORP, "sector", "Limit utilisation by sector"),
                   B("M022", RET, "product", "EAD share by product"),
                   TOP(CORP), ALR(CORP)],
          rules=[R("R13-1", "Limit utilisation above 90%", "M037", CORP,
                   "gt", 0.90, "critical"),
                 R("R13-2", "Largest name above 5% of EAD", "M021", CORP,
                   "gt", 0.05, "high")]),
    _lens("LENS-14", "Board Risk Committee Pack", "Board / Executive",
          [CORP, RET], description="Executive trends, material changes, top "
                                   "breaches and scenario results.",
          refresh="monthly",
          visuals=[K("M001", CORP), K("M001", RET), K("M003", CORP),
                   K("M006", CORP), K("M048", CORP),
                   T(["M001"], CORP, "Corporate booked ECL", periods=12),
                   T(["M001"], RET, "Retail booked ECL", periods=12),
                   SCN(CORP), ALR(CORP)],
          rules=[R("R14-1", "Quarterly ECL move above 10%", "M003", CORP,
                   "abs_gt", 0.10, "critical")]),
    _lens("LENS-15", "Sector Watch — Construction & CRE", "Sector specialist",
          [CORP], description="Construction and Real Estate: EAD/ECL, PD/LGD, "
                              "rating migration, top borrowers and covenant "
                              "signals.",
          refresh="daily", filters={CORP: CRE},
          visuals=[K("M018", CORP), K("M001", CORP), K("M015", CORP),
                   K("M016", CORP), K("M023", CORP), K("M064", CORP),
                   B("M001", CORP, "sub_sector", "Booked ECL by sub-sector"),
                   B("M015", CORP, "rating_current", "PD by rating"),
                   TOP(CORP, "Largest Construction & CRE borrowers"),
                   TAB(CORP, CORP_TABLE)],
          rules=[R("R15-1", "Covenant-breach EAD up >10%", "M064", CORP,
                   "move_pct_gt", 0.10, "high")]),
    _lens("LENS-16", "Scenario Impact Watch", "Stress / Portfolio team",
          [CORP, RET], description="Saved scenarios' ECL deltas, method "
                                   "comparison and scope contribution.",
          refresh="on_result",
          visuals=[K("M039", CORP), K("M040", CORP), K("M041", CORP),
                   K("M039", RET), K("M042", CORP),
                   SCN(CORP), SCN(RET), SENS(CORP),
                   G("M073", CORP, "Latest result: ECL change by method"),
                   G("M074", CORP, "Latest result: change concentration by sector"),
                   G("M075", CORP, "Latest result: ECL change by stage"),
                   G("M073", RET, "Latest Retail result: ECL change by method")],
          rules=[R("R16-1", "Scenario ECL delta above 20%", "M040", CORP,
                   "gt", 0.20, "moderate")]),
    _lens("LENS-17", "Data Quality & Coverage", "Risk data owner",
          [CORP, RET], description="Missingness, freshness, coverage, "
                                   "reconciliation and release health.",
          refresh="on_publication",
          visuals=[K("M045", CORP), K("M045", RET), K("M046", CORP),
                   K("M047", CORP), K("M060", CORP), K("M060", RET),
                   T(["M060"], CORP, "Exposure count"),
                   T(["M060"], RET, "Account count"),
                   TAB(CORP, CORP_TABLE, sort="ead_sar_mn")],
          rules=[R("R17-1", "Completeness below 99%", "M045", CORP, "lt",
                   0.99, "high")]),
    _lens("LENS-18", "Monitoring & Breach Executive", "CRO / Operations",
          [CORP, RET], description="New, worsening and resolved alerts, top "
                                   "breached metrics and owners.",
          refresh="continuous",
          visuals=[K("M048", CORP), K("M049", CORP), K("M050", CORP),
                   K("M006", CORP), K("M033", RET),
                   ALR(CORP), T(["M005"], CORP, "Stage 2 EAD share"),
                   B("M063", CORP, "sector", "High/critical EWS EAD by sector"),
                   G("M070", CORP, "Alerts by state"),
                   G("M071", CORP, "Active breaches by metric"),
                   G("M072", CORP, "Active breaches by owner")],
          rules=[R("R18-1", "Active breaches above 5", "M048", CORP, "gt", 5,
                   "high")]),
    # Beyond the §45 minimum.
    _lens("LENS-19", "Hospitality & Transport Watch", "Sector specialist",
          [CORP], description="Travel-exposed sectors: ECL, PD, EWS and "
                              "utilisation.",
          refresh="daily",
          filters={CORP: [{"column": "sector", "op": "in",
                           "values": ["Hospitality", "Transport"]}]},
          visuals=[K("M001", CORP), K("M015", CORP), K("M063", CORP),
                   K("M019", CORP),
                   B("M001", CORP, "sub_sector", "Booked ECL by sub-sector"),
                   B("M019", CORP, "region", "Utilisation by region"),
                   TAB(CORP, CORP_TABLE)],
          rules=[R("R19-1", "EAD-weighted PD up > 15 bps", "M015", CORP,
                   "move_abs_gt", 0.0015, "moderate")]),
    _lens("LENS-20", "Buy Now Pay Later Watch", "Product risk head", [RET],
          description="BNPL: early delinquency, score quality and ECL.",
          refresh="weekly",
          filters={RET: [{"column": "product", "op": "in",
                          "values": ["Buy Now Pay Later"]}]},
          visuals=[K("M001", RET), K("M054", RET), K("M056", RET),
                   K("M061", RET),
                   B("M018", RET, "score_band", "EAD by score band"),
                   B("M054", RET, "origination_channel", "Past-due EAD by channel"),
                   TAB(RET, RET_TABLE)],
          rules=[R("R20-1", "Newest-vintage PD above 5%", "M061", RET, "gt",
                   0.05, "moderate")]),
)


def by_id() -> dict[str, dict[str, Any]]:
    return {lens["lens_id"]: lens for lens in LENSES}


__all__ = ["LENSES", "SEED_VERSION", "by_id"]
