"""Eight live dashboards, bound to the book rather than drawn from a fixture.

§20 asks for at least eight substantive lenses, four of them product
dashboards, each product dashboard carrying at least eight governed metrics
and four distinct charts — trends, composition, migration and contribution,
not a row of KPI tiles.

What makes these LIVE
-----------------------
Every panel is a `KIND_RETAIL` tile: a governed measure over the canonical
facility-month book, computed when the page asks. Nothing is stored with the
lens except what to compute, so a rebuilt book changes the dashboard without
anybody editing it — which is the source-mutation test §20 asks for, and the
only honest basis for a LIVE badge.

The badge itself is not decoration either. Each panel returns the month it
read, the source hash of the book it read and whether that month is the
latest the book holds. A tile that read an older month because that is all
there is reports Stale; a tile pinned to an older month on purpose does not.

What a product dashboard is for
---------------------------------
Not eight numbers. The four product dashboards each answer the same five
questions in the same order, so a reader who learns one has learned all
four: how big is it, what does it cost, where is the risk, how is it moving,
and what is specific to this product. The last is where they diverge — cards
have utilisation and score bands, personal finance has income and debt
burden, auto has balloons and collateral, home has loan-to-value and stage 2
— because a dashboard whose product-specific half is the same four charts
with the filter changed has not been designed for the product.
"""

from __future__ import annotations

from typing import Any

from backend.retail.seed_catalogue import AUTO, CARD, HOME, PERSONAL, RETAIL

LENSES_SEED_VERSION = "retail-seed-lenses-1.0.0"


def _kpi(title: str, measure: str, product: str = "",
         where: dict[str, Any] | None = None, note: str = "") -> dict:
    return {
        "kind": "retail", "title": title, "visual": "number",
        "note": note,
        "params": {"shape": "value", "measures": [measure],
                   "product": product, "where": dict(where or {})},
    }


def _table(title: str, measures: list[str], cut: str, product: str = "",
           where: dict[str, Any] | None = None, visual: str = "bar",
           note: str = "") -> dict:
    return {
        "kind": "retail", "title": title, "visual": visual, "note": note,
        "params": {"shape": "table", "measures": measures, "cut": cut,
                   "product": product, "where": dict(where or {})},
    }


def _trend(title: str, measures: list[str], product: str = "",
           months: int = 13, where: dict[str, Any] | None = None,
           note: str = "") -> dict:
    return {
        "kind": "retail", "title": title, "visual": "line", "note": note,
        "params": {"shape": "trend", "measures": measures,
                   "product": product, "months": months,
                   "where": dict(where or {})},
    }


def _product_dashboard(product: str, name: str, specific: list[dict],
                       audience: str) -> dict[str, Any]:
    """The five questions every product dashboard answers, plus its own."""
    return {
        "slug": f"retail-{product.lower().replace('_', '-')}",
        "name": name,
        "audience": audience,
        "description": (
            f"The {name.lower()} book as it stands: size, cost, where the "
            "risk sits, how it is moving, and what is specific to this "
            "product. Bound to the latest published snapshot of the "
            "governed book."),
        "panels": [
            # ---- how big is it
            _kpi("Facilities", "facilities", product),
            _kpi("Distinct customers", "customers", product),
            _kpi("Gross carrying amount", "exposure", product),
            # ---- what does it cost
            _kpi("Expected credit loss", "ecl", product),
            _kpi("ECL coverage", "coverage", product),
            # ---- where is the risk
            _kpi("Stage 2 share of exposure", "stage2_exposure_share",
                 product),
            _kpi("30+ DPD share of accounts", "dpd30_share", product),
            _kpi("30+ DPD share of exposure", "dpd30_exposure_share",
                 product,
                 note="Where this exceeds the account share, the larger "
                      "balances are the ones in arrears."),
            # ---- composition
            _table("Exposure and risk by customer segment",
                   ["facilities", "exposure", "ecl", "coverage",
                    "dpd30_share"], "segment", product),
            _table("Delinquency bucket mix",
                   ["facilities", "exposure", "ecl", "coverage"],
                   "dpd_bucket", product,
                   note="Accounts and money in each bucket. The two "
                        "distributions differ and the difference is the "
                        "collections question."),
            # ---- migration
            _table("Staging and coverage",
                   ["facilities", "exposure", "ecl", "coverage"], "stage",
                   product),
            # ---- how is it moving
            _trend("Delinquency, thirteen months",
                   ["dpd30_share", "dpd30_exposure_share", "dpd90_share"],
                   product),
            _trend("Exposure and provision, thirteen months",
                   ["exposure", "ecl", "coverage"], product),
            _trend("Stage 2 migration, thirteen months",
                   ["stage2_share", "stage2_exposure_share"], product),
            # ---- and what is specific to this product
            *specific,
        ],
    }


LENSES: tuple[dict[str, Any], ...] = (
    _product_dashboard(
        CARD, "Credit Card", audience="Retail Credit Risk",
        specific=[
            _table("Utilisation band mix",
                   ["facilities", "exposure", "mean_utilisation",
                    "dpd30_share", "mean_behaviour_score"],
                   "utilisation_band", CARD,
                   note="Cards are a revolving product: how hard the limit "
                        "is drawn is the signal a term loan does not have."),
            _trend("Utilisation and over-limit, thirteen months",
                   ["mean_utilisation", "overlimit_share", "dpd30_share"],
                   CARD),
            _table("Risk by application score band",
                   ["facilities", "exposure", "dpd30_share",
                    "mean_behaviour_score", "mean_pd"],
                   "application_band", CARD,
                   note="Whether the band a customer was written at still "
                        "orders how they behave."),
            _table("Salary transfer",
                   ["facilities", "exposure", "coverage", "dpd30_share",
                    "mean_utilisation"], "salary_transfer", CARD),
        ]),
    _product_dashboard(
        PERSONAL, "Personal Finance", audience="Retail Credit Risk",
        specific=[
            _table("Income band mix",
                   ["facilities", "exposure", "mean_income",
                    "mean_disposable", "dpd30_share"],
                   "income_band", PERSONAL),
            _table("Indebtedness band mix",
                   ["facilities", "exposure", "mean_dbr", "dpd30_share",
                    "coverage"], "indebtedness_band", PERSONAL,
                   note="If the affordability policy separates, the arrears "
                        "should rise monotonically across these bands."),
            _trend("Income and debt burden, thirteen months",
                   ["mean_income", "mean_disposable", "mean_dbr"], PERSONAL),
            _table("Employment status",
                   ["facilities", "exposure", "mean_income", "dpd30_share"],
                   "employment", PERSONAL),
        ]),
    _product_dashboard(
        AUTO, "Auto Finance", audience="Collections and Retail Credit Risk",
        specific=[
            _table("Balloon band mix",
                   ["facilities", "exposure", "balloon_exposure",
                    "balloon_within_year_share", "dpd30_share"],
                   "balloon_band", AUTO,
                   note="A balloon on a performing account is a refinancing "
                        "question, not a collections one."),
            _trend("Balloon exposure, thirteen months",
                   ["balloon_exposure", "balloon_within_year_share"], AUTO),
            _table("Collateral cover by loan-to-value band",
                   ["facilities", "exposure", "collateral_cover",
                    "mean_ltv", "dpd30_share"], "ltv_band", AUTO),
            _trend("Cover and loan-to-value, thirteen months",
                   ["collateral_cover", "mean_ltv", "high_ltv_share"], AUTO),
        ]),
    _product_dashboard(
        HOME, "Home Finance", audience="IFRS 9 Reporting",
        specific=[
            _table("Loan-to-value distribution",
                   ["facilities", "exposure", "mean_ltv", "high_ltv_share",
                    "stage2_share"], "ltv_band", HOME),
            _trend("Loan-to-value and cover, thirteen months",
                   ["mean_ltv", "high_ltv_share", "collateral_cover"], HOME),
            _table("Stage 2 by loan-to-value",
                   ["facilities", "exposure", "stage2_share", "coverage"],
                   "ltv_band", HOME,
                   note="Whether the SICR trigger is firing where the "
                        "equity is thin."),
            _table("Regional concentration",
                   ["facilities", "exposure", "mean_ltv", "coverage"],
                   "region", HOME),
        ]),

    # ------------------------------------------------ the four cross-cutting
    {
        "slug": "retail-executive-risk",
        "name": "Retail Executive Risk",
        "audience": "Executive Risk Committee",
        "description": "The retail book on one screen: the four products, "
                       "what each costs, where the risk sits and how it is "
                       "moving.",
        "panels": [
            _kpi("Facilities", "facilities"),
            _kpi("Distinct customers", "customers"),
            _kpi("Gross carrying amount", "exposure"),
            _kpi("Expected credit loss", "ecl"),
            _kpi("ECL coverage", "coverage"),
            _kpi("30+ DPD share of exposure", "dpd30_exposure_share"),
            _kpi("Stage 2 share of exposure", "stage2_exposure_share"),
            _kpi("Salary-transferred share", "salary_transfer_share"),
            _table("The book by product",
                   ["facilities", "customers", "exposure", "ecl",
                    "coverage", "dpd30_share"], "product"),
            _table("Risk by customer segment",
                   ["facilities", "exposure", "ecl", "coverage",
                    "dpd30_share"], "segment"),
            _table("Regional concentration",
                   ["facilities", "customers", "exposure", "coverage"],
                   "region"),
            _trend("Exposure and provision, thirteen months",
                   ["exposure", "ecl", "coverage"]),
            _trend("Delinquency across the book, thirteen months",
                   ["dpd30_share", "dpd30_exposure_share", "dpd90_share"]),
            _trend("Growth: customers and facilities",
                   ["customers", "facilities"]),
        ],
    },
    {
        "slug": "retail-ifrs9-ecl-dashboard",
        "name": "Retail IFRS 9 and ECL",
        "audience": "IFRS 9 Reporting",
        "description": "Staging, coverage and expected credit loss across "
                       "the retail book, with the movements behind them.",
        "panels": [
            _kpi("Expected credit loss", "ecl"),
            _kpi("ECL coverage", "coverage"),
            _kpi("Stage 2 share of exposure", "stage2_exposure_share"),
            _kpi("Stage 3 share of accounts", "stage3_share"),
            _kpi("Mean loss given default", "mean_lgd"),
            _kpi("Mean predicted PD", "mean_pd"),
            _kpi("Gross carrying amount", "exposure"),
            _kpi("30+ DPD share of exposure", "dpd30_exposure_share"),
            _table("Staging and what each stage costs",
                   ["facilities", "exposure", "ecl", "coverage"], "stage"),
            _table("Stage 2 by product",
                   ["facilities", "exposure", "stage2_share",
                    "stage2_exposure_share", "coverage"], "product"),
            _table("Where the money sits by delinquency bucket",
                   ["facilities", "exposure", "ecl", "coverage"],
                   "dpd_bucket"),
            _table("Loss severity by product",
                   ["facilities", "mean_lgd", "coverage", "ecl"], "product"),
            _trend("Coverage, staging and delinquency together",
                   ["coverage", "stage2_share", "dpd30_share"],
                   note="Coverage moves for two reasons: risk changing, and "
                        "the mix changing underneath a constant risk."),
            _trend("The impaired population, thirteen months",
                   ["stage3_share", "coverage", "ecl"]),
        ],
    },
    {
        "slug": "retail-forward-early-warning",
        "name": "Forward Early Warning",
        "audience": "Retail Credit Risk",
        "description": "Customers who are still fully current, and where "
                       "their forward indicators sit. The population a "
                       "decision is still available for.",
        "panels": [
            _kpi("Facilities with no arrears", "facilities",
                 where={"dpd_bucket": "0"}),
            _kpi("Customers with no arrears", "customers",
                 where={"dpd_bucket": "0"}),
            _kpi("Clean exposure", "exposure", where={"dpd_bucket": "0"}),
            _kpi("Mean behavioural score, clean cohort",
                 "mean_behaviour_score", where={"dpd_bucket": "0"}),
            _kpi("Mean predicted PD, clean cohort", "mean_pd",
                 where={"dpd_bucket": "0"}),
            _kpi("Stage 2 exposure with no arrears", "exposure",
                 where={"dpd_bucket": "0", "ifrs9_stage": "2"},
                 note="The SICR trigger working as intended: caught before "
                      "the arrears did."),
            _kpi("Card over-limit share, clean cohort", "overlimit_share",
                 product=CARD, where={"dpd_bucket": "0"}),
            _kpi("Whole book, 30+ DPD share", "dpd30_share",
                 note="Shown beside the clean cohort so the two populations "
                      "are never confused."),
            _table("The clean population by product",
                   ["facilities", "customers", "exposure",
                    "mean_behaviour_score", "mean_pd"], "product",
                   where={"dpd_bucket": "0"}),
            _table("Card utilisation among still-current accounts",
                   ["facilities", "exposure", "mean_utilisation",
                    "overlimit_share"], "utilisation_band", CARD,
                   where={"dpd_bucket": "0"}),
            _table("Stage 2 with no arrears, by product",
                   ["facilities", "exposure", "ecl", "coverage", "mean_pd"],
                   "product", where={"dpd_bucket": "0", "ifrs9_stage": "2"}),
            _table("Personal finance affordability, clean cohort",
                   ["facilities", "exposure", "mean_income", "mean_dbr"],
                   "income_band", PERSONAL, where={"dpd_bucket": "0"}),
            _trend("Card over-limit population, thirteen months",
                   ["overlimit_share", "mean_utilisation"], CARD),
            _trend("Behavioural score and PD across the book",
                   ["mean_behaviour_score", "mean_pd"]),
        ],
    },
    {
        "slug": "retail-scorecard-health",
        "name": "Scorecard Health",
        "audience": "Retail Model Risk",
        "description": "What the scorecards are producing across the four "
                       "products, and whether the score still sits where "
                       "the outcome does.",
        "panels": [
            _kpi("Mean behavioural score", "mean_behaviour_score"),
            _kpi("Mean predicted PD", "mean_pd"),
            _kpi("30+ DPD share of accounts", "dpd30_share"),
            _kpi("Stage 2 share of accounts", "stage2_share"),
            _kpi("Card mean behavioural score", "mean_behaviour_score",
                 product=CARD),
            _kpi("Card mean predicted PD", "mean_pd", product=CARD),
            _kpi("Personal finance mean PD", "mean_pd", product=PERSONAL),
            _kpi("Auto mean PD", "mean_pd", product=AUTO),
            _table("Score and PD by product",
                   ["facilities", "mean_behaviour_score", "mean_pd",
                    "dpd30_share", "coverage"], "product"),
            _table("Card risk by application score band",
                   ["facilities", "exposure", "dpd30_share",
                    "mean_behaviour_score", "mean_pd"],
                   "application_band", CARD,
                   note="A monotone column here is the score ordering risk. "
                        "A break in it is a rank inversion, and the "
                        "validation module carries the support behind it."),
            _table("Card predicted PD by stage",
                   ["facilities", "mean_pd", "mean_behaviour_score",
                    "coverage"], "stage", CARD),
            _table("Score by origination vintage",
                   ["facilities", "mean_behaviour_score", "mean_pd",
                    "dpd30_share"], "vintage", CARD),
            _trend("Score and PD against observed arrears",
                   ["mean_behaviour_score", "mean_pd", "dpd30_share"],
                   note="The modelled probability and the realised arrears "
                        "are different horizons and are plotted together "
                        "only to show whether they move at all alike."),
            _trend("Card score drift, thirteen months",
                   ["mean_behaviour_score", "mean_pd"], CARD),
        ],
    },
)


def build(session: Any, owner: Any, report: Any, *,
          preview: bool = False) -> None:
    """Seed or refresh the eight dashboards, by stable slug."""
    from sqlalchemy import select

    from backend.models.platform import Lens

    for one in LENSES:
        row = session.execute(
            select(Lens).where(Lens.slug == one["slug"])).scalars().first()
        definition = {"panels": one["panels"],
                      "seed_version": LENSES_SEED_VERSION,
                      "seeded": True}

        if preview:
            report.add("lens", one["slug"],
                       "create" if row is None else "refresh", one["name"])
            continue

        if row is None:
            session.add(Lens(
                slug=one["slug"], name=one["name"],
                description=one["description"], audience=one["audience"],
                definition=definition, status="published", version=1,
                origin="seed", created_by=getattr(owner, "id", None)))
            report.add("lens", one["slug"], "create",
                       f"{one['name']} — {len(one['panels'])} panels")
            continue

        if (row.definition or {}).get("panels") == one["panels"]:
            report.add("lens", one["slug"], "unchanged", one["name"])
            continue

        row.name = one["name"]
        row.description = one["description"]
        row.audience = one["audience"]
        row.definition = definition
        row.version = (row.version or 1) + 1
        row.status = "published"
        report.add("lens", one["slug"], "refresh",
                   f"{one['name']} — {len(one['panels'])} panels")


__all__ = ["LENSES", "LENSES_SEED_VERSION", "build"]
