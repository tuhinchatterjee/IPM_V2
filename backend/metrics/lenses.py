"""The lenses CreditProbe ships with, built on the Metric Catalogue.

A preconfigured lens is not a demo. It is the answer to "what would a competent
head of this portfolio put on one screen", written once so that every
deployment starts from something a risk professional would recognise rather
than from an empty canvas.

Three of them are defined here — Retail Credit Risk, Retail Analytics and
Corporate IFRS 9 — and each is made of metric tiles and charts drawn from
:mod:`backend.metrics.library`. The CRO Lens is deliberately not here: it is a
composed executive narrative with its own page, and rebuilding it as a grid of
tiles would be a downgrade dressed as consistency.

What makes these honest
-----------------------
Every tile names a metric that exists and calculates against the governed data
in this deployment. Nothing is drawn from a placeholder, and nothing is
included because it would look good.

Where a metric a reader would reasonably expect is genuinely unavailable — a
retail IFRS 9 staging split, a month-on-month roll rate, an approval rate — the
lens says so, in `notes`, with the reason and what would be needed. A view that
quietly omits the number somebody came for teaches them not to trust it. One
that says "retail IFRS 9 staging is not available in this deployment, because
there is no retail impairment dataset" does the opposite, and costs one line.

A tile is a figure; a chart is a chart
--------------------------------------
This is the correction that shaped the current definitions. A metric tile has
always carried a `visual`, and the shipped lenses used to set it to `line` on
the tiles they wanted as trends. The tile renderer does not read it: a metric
panel computes one number for one period, so every one of those "line" tiles
drew a single figure. The declaration was checked — `check()` proved the metric
had declared itself line-drawable — and the check passed while the screen
disagreed with it, which is the worst shape a governance check can take.

So a metric tile here is always a `kpi`, and `check()` now refuses anything
else by name. Where a lens wants a trend or a breakdown it carries a real
chart, which names the dimension it is grouped by and goes through the same
validation as one a person builds by hand. What is on screen and what is
declared are the same thing again.

`check()` proves every tile and every chart against the live catalogue, and a
test runs it. A lens that names a metric which has stopped existing, or groups
one by a field its dataset does not have, fails a test rather than rendering a
hole.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.metrics import library as lib
from backend.metrics.catalogue import Unsupported

LENSES_VERSION = "2.2.0"

#: The CRO Lens is preserved as-is. Recorded here so that anything enumerating
#: the shipped lenses knows it exists and knows why it is not in `ALL`.
CRO_LENS = {
    "slug": "cro",
    "name": "CRO Lens",
    "note": ("Composed as an executive narrative rather than a grid of tiles, "
             "and kept that way. It reads as a story about the book; a "
             "metric grid would say less in more space."),
}


@dataclass(frozen=True)
class Tile:
    """One metric on a lens, drawn as a single figure.

    `visual` is not a field. A metric panel computes one number for one
    period, and the tile renderer draws exactly that; a tile that declared
    itself a line drew a figure anyway, and the declaration was a lie the
    checker could not see. A lens that wants a line asks for a `Chart`.
    """

    metric_id: str
    title: str = ""
    note: str = ""


@dataclass(frozen=True)
class Chart:
    """One metric broken out across one dimension.

    The same metric, the same formula and the same executor as a tile —
    grouped. `dimension` is a field of the metric's own dataset, and `check()`
    proves it is one the platform will actually offer, so a shipped chart is
    refused at build time for the same reasons one built by hand is refused at
    submission.
    """

    metric_id: str
    dimension: str
    visual: str = "bar"
    title: str = ""
    note: str = ""
    #: `metric` recomputes the metric's own definition within each group,
    #: which is what makes a bar comparable to the tile above it.
    aggregate: str = "metric"
    sort: str = "value"
    direction: str = "desc"
    limit: int = 20
    compare: str = ""


@dataclass(frozen=True)
class Section:
    """A named group of tiles and charts.

    Sections exist because a screen of thirty equal tiles is a screen nobody
    reads top to bottom. "Where the book is" and "where it is going wrong" are
    different questions and belong in different bands — and the bands are what
    make a long lens readable, which is why the tile limit is a limit on the
    lens rather than on the band.
    """

    title: str
    subtitle: str = ""
    tiles: tuple[Tile | Chart, ...] = ()


@dataclass(frozen=True)
class LensSpec:
    """A lens CreditProbe ships, and what it deliberately does not show."""

    slug: str
    name: str
    audience: str
    description: str
    sections: tuple[Section, ...]
    #: Metric ids from `library.UNSUPPORTED` this lens would have shown.
    absent: tuple[str, ...] = ()
    #: Why this lens exists, for the reader who opened it by accident.
    purpose: str = ""
    #: The book it reads. Shown on the lens and used to scope suggestions.
    portfolio: str = ""
    #: The governed data domains it draws on, in the reader's words.
    domains: tuple[str, ...] = ()

    @property
    def tiles(self) -> tuple[Tile | Chart, ...]:
        return tuple(t for section in self.sections for t in section.tiles)

    @property
    def metric_ids(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(t.metric_id for t in self.tiles))

    def scope(self) -> dict[str, Any]:
        """The lens definition panel §8 asks the creation flow to fill in.

        Stored on the lens so that a shipped lens and one somebody builds by
        talking to CreditProbe carry the same thing, and so the screen has an
        answer to "what is this lens for" that is not the description.
        """
        return {
            "purpose": self.purpose,
            "audience": self.audience,
            "portfolio": self.portfolio,
            "domains": list(self.domains),
            "default_period": "",
            "comparison_period": "",
            "visibility": "shared",
        }

    def notes(self) -> list[dict[str, Any]]:
        """What is missing from this lens, in the reader's words."""
        by_id = {entry.metric_id: entry for entry in lib.UNSUPPORTED}
        out: list[dict[str, Any]] = []
        for metric_id in self.absent:
            entry: Unsupported | None = by_id.get(metric_id)
            if entry is None:  # pragma: no cover - check() catches this
                continue
            out.append({
                "kind": "unavailable",
                "metric_id": entry.metric_id,
                "name": entry.name,
                "because": entry.because,
                "needs": list(entry.needs),
            })
        return out

    def layout(self) -> list[dict[str, Any]]:
        """Sections as stored on the lens definition: titles and tile indices."""
        out: list[dict[str, Any]] = []
        index = 0
        for section in self.sections:
            span = list(range(index, index + len(section.tiles)))
            index += len(section.tiles)
            out.append({"title": section.title, "subtitle": section.subtitle,
                        "panels": span})
        return out

# =========================================================== Retail Credit Risk


RETAIL_RISK = LensSpec(
    slug="retail-credit-risk",
    name="Retail Credit Risk",
    audience="Head of Retail Credit Risk",
    portfolio="Retail",
    domains=("Retail Credit Risk",),
    purpose=(
        "The monthly read a head of retail risk is asked for: how big the "
        "book is, how much of it is behind, whether the accounts that went "
        "behind are coming back, and whether the scorecards that sort them "
        "are still working."),
    description=(
        "The retail book as it stands this month: how big it is, how much of "
        "it is behind, which way the arrears are moving, and what the models "
        "say about where it is going."),
    sections=(
        Section(
            title="The book",
            subtitle="Size and shape before anything is said about quality.",
            tiles=(
                Tile("retail.balance"),
                Tile("retail.accounts"),
                Tile("retail.average_balance"),
                Tile("retail.utilisation"),
            )),
        Section(
            title="Arrears",
            subtitle=("Each bucket twice: how many customers are behind, and "
                      "how much money is. A dashboard showing one of those "
                      "labelled simply '90+ DPD' is read two ways."),
            tiles=(
                Tile("retail.dpd_1_count"),
                Tile("retail.dpd_30_count"),
                Tile("retail.dpd_30_balance"),
                Tile("retail.dpd_60_balance"),
                Tile("retail.dpd_90_count"),
                Tile("retail.dpd_90_balance"),
                Tile("retail.delinquent_balance"),
                Tile("retail.default_rate"),
            )),
        Section(
            title="Where the arrears are going",
            subtitle=("The buckets above are a level on one date. These are "
                      "the trend behind them, over every month the "
                      "behavioural dataset holds."),
            tiles=(
                Chart("retail.dpd_30_balance", "observation_month", "line",
                      title="30+ DPD exposure rate, month by month"),
                Chart("retail.dpd_90_balance", "observation_month", "line",
                      title="90+ DPD exposure rate, month by month"),
                Chart("retail.default_rate", "observation_month", "line",
                      title="Default rate, month by month"),
            )),
        Section(
            title="In and out of arrears",
            subtitle=("A level says how many accounts are behind. These say "
                      "whether the ones that went behind are coming back, and "
                      "whether the same accounts keep going behind."),
            tiles=(
                Tile("retail.cure_rate_3m"),
                Tile("retail.repeat_delinquency_rate"),
                Tile("retail.restructured_rate"),
                Chart("retail.cure_rate_3m", "observation_month", "line",
                      title="Cure rate, month by month"),
            )),
        Section(
            title="Stress in the book",
            subtitle="Behaviour that runs ahead of arrears.",
            tiles=(
                Tile("retail.high_utilisation_rate"),
                Tile("retail.missed_payments"),
            )),
        Section(
            title="Which accounts are behind",
            subtitle=("The same 30+ DPD account rate, split three ways. A "
                      "portfolio number that is flat can hide a product or a "
                      "vintage that is not."),
            tiles=(
                Chart("retail.dpd_30_count", "product", "bar",
                      title="30+ DPD account rate by product"),
                Chart("retail.dpd_30_count", "vintage", "bar",
                      title="30+ DPD account rate by vintage",
                      sort="label", direction="asc"),
                Chart("retail.default_rate", "bureau_score_latest_bin", "line",
                      title="Default rate by bureau score band",
                      sort="label", direction="asc"),
            )),
        Section(
            title="What the models say",
            subtitle=("Scores and predicted PD. These are model output, not "
                      "outcomes; the arrears band above is the outcome."),
            tiles=(
                Tile("retail.average_score"),
                Tile("retail.average_pd"),
            )),
        Section(
            title="Are the scorecards still working",
            subtitle=("Discrimination, separation and calibration, on the "
                      "most recent cohort whose performance window has "
                      "closed. A model can rank well and still be badly "
                      "calibrated, which is why both are here."),
            tiles=(
                Tile("retail.scorecard.gini"),
                Tile("retail.scorecard.ks"),
                Tile("retail.scorecard.calibration"),
                Tile("retail.scorecard.matured"),
            )),
    ),
    absent=("retail.ifrs9.stage_exposure", "retail.ifrs9.ecl",
            "retail.roll_rate", "retail.cure_rate", "retail.scorecard.psi"),
)


# =========================================================== Retail Analytics


RETAIL_ANALYTICS = LensSpec(
    slug="retail-analytics",
    name="Retail Analytics",
    audience="Retail Portfolio and Model Validation Analysts",
    portfolio="Retail",
    domains=("Retail Analytics", "Retail Credit Risk"),
    purpose=(
        "The analyst's view rather than the executive's: what came through "
        "the door, how it was mixed, how each slice of it has performed, and "
        "whether the application scorecard is separating the two."),
    description=(
        "Origination volume, mix and quality, how each cohort has turned out, "
        "and whether the scorecards are still doing what they were built to "
        "do."),
    sections=(
        Section(
            title="What came through the door",
            subtitle="Application volume and size, by application month.",
            tiles=(
                Tile("retail.applications"),
                Tile("retail.requested_amount"),
                Tile("retail.average_ticket"),
                Chart("retail.applications", "application_month", "line",
                      title="Applications, month by month"),
                Chart("retail.average_ticket", "application_month", "line",
                      title="Average ticket, month by month"),
            )),
        Section(
            title="How it was mixed",
            subtitle=("Where the volume came from. Read alongside the "
                      "performance band below: a channel that grew and a "
                      "channel that performed are rarely the same one."),
            tiles=(
                Chart("retail.applications", "product_type", "bar",
                      title="Applications by product"),
                Chart("retail.applications", "application_channel", "bar",
                      title="Applications by channel"),
                Chart("retail.applications", "customer_segment", "bar",
                      title="Applications by customer segment"),
            )),
        Section(
            title="Who was asking",
            subtitle=("Affordability as recorded at application. These are "
                      "applicant characteristics, not book characteristics."),
            tiles=(
                Tile("retail.average_loan_to_income"),
                Tile("retail.average_debt_burden"),
                Tile("retail.salary_transfer_rate"),
            )),
        Section(
            title="How the cohorts turned out",
            subtitle=("Only cohorts whose performance window has closed. A "
                      "bad rate on a cohort still maturing understates, "
                      "because the accounts that will go bad have not had "
                      "time to."),
            tiles=(
                Tile("retail.application_bad_rate"),
                Tile("retail.scorecard.matured"),
                Chart("retail.application_bad_rate", "product_type", "bar",
                      title="Bad rate by product"),
                Chart("retail.application_bad_rate", "application_channel",
                      "bar", title="Bad rate by channel"),
                Chart("retail.application_bad_rate", "customer_segment", "bar",
                      title="Bad rate by customer segment"),
            )),
        Section(
            title="Does the score separate them",
            subtitle=("The bad rate down the score bands is the picture the "
                      "Gini summarises. A scorecard that is working shows a "
                      "monotone fall across it; one that is not shows a step, "
                      "or a bump, and the Gini alone would not say where."),
            tiles=(
                Tile("retail.application_gini"),
                Chart("retail.application_bad_rate", "bureau_score_bin",
                      "line", title="Bad rate by bureau score band",
                      sort="label", direction="asc"),
            )),
        Section(
            title="How the book behind it is performing",
            subtitle=("The behavioural book, split the two ways an analyst "
                      "asks for: by product and by the year the account was "
                      "written. A vintage curve is the earliest place a "
                      "change in underwriting shows up."),
            tiles=(
                Chart("retail.dpd_30_count", "vintage", "bar",
                      title="30+ DPD account rate by vintage",
                      sort="label", direction="asc"),
                Chart("retail.utilisation", "product", "bar",
                      title="Utilisation by product"),
            )),
    ),
    absent=("retail.approval_rate", "retail.scorecard.psi",
            "retail.roll_rate"),
)


# =========================================================== Corporate IFRS 9


CORPORATE_IFRS9 = LensSpec(
    slug="corporate-ifrs9",
    name="Corporate IFRS 9",
    audience="IFRS 9 Committee and Head of Impairment",
    portfolio="Corporate",
    domains=("Corporate IFRS 9",),
    purpose=(
        "The impairment committee's screen: where the corporate book sits "
        "across the three stages, what it is provisioned at, what moved "
        "between the stages this quarter and why, and how much of the "
        "provision is judgement rather than model."),
    description=(
        "Where the corporate book sits across the three stages, what it is "
        "provisioned at, what moved between stages this quarter, what "
        "triggered the moves, and how much of the provision is judgement."),
    sections=(
        Section(
            title="The provision",
            subtitle="Total exposure, total ECL, and the coverage between them.",
            tiles=(
                Tile("corporate.ifrs9.total_ead"),
                Tile("corporate.ifrs9.total_ecl"),
                Tile("corporate.ifrs9.coverage"),
                Chart("corporate.ifrs9.total_ecl", "period", "line",
                      title="Total ECL, quarter by quarter"),
                Chart("corporate.ifrs9.coverage", "period", "line",
                      title="ECL coverage, quarter by quarter"),
            )),
        Section(
            title="Where the book sits",
            subtitle=("Exposure by stage, as an amount and as a share. The "
                      "shares sum to the book; the amounts do not move "
                      "together with them when the book grows."),
            tiles=(
                Tile("corporate.ifrs9.stage1_ead"),
                Tile("corporate.ifrs9.stage2_ead"),
                Tile("corporate.ifrs9.stage3_ead"),
                Tile("corporate.ifrs9.stage1_share"),
                Tile("corporate.ifrs9.stage2_share"),
                Tile("corporate.ifrs9.stage3_share"),
                Chart("corporate.ifrs9.stage2_share", "period", "line",
                      title="Stage 2 ratio, quarter by quarter"),
            )),
        Section(
            title="What each stage is provisioned at",
            subtitle=("The provision held against each stage, and the coverage "
                      "it implies. Stage 3 coverage moving while Stage 3 "
                      "exposure does not is a change in expected recovery, "
                      "not a change in what has defaulted."),
            tiles=(
                Tile("corporate.ifrs9.stage1_ecl"),
                Tile("corporate.ifrs9.stage2_ecl"),
                Tile("corporate.ifrs9.stage3_ecl"),
                Tile("corporate.ifrs9.stage1_coverage"),
                Tile("corporate.ifrs9.stage2_coverage"),
                Tile("corporate.ifrs9.stage3_coverage"),
            )),
        Section(
            title="What moved between the stages",
            subtitle=("Read from `prior_stage` on each facility's own row, so "
                      "a transition is measured in the same pass as a level. "
                      "The rates are shares of the exposure that started the "
                      "quarter where the move starts — not of the whole book, "
                      "which would fall whenever the book grew."),
            tiles=(
                Tile("corporate.ifrs9.stage_1_to_2_ead"),
                Tile("corporate.ifrs9.stage_2_to_1_ead"),
                Tile("corporate.ifrs9.stage_2_to_3_ead"),
                Tile("corporate.ifrs9.new_default_ead"),
                Tile("corporate.ifrs9.cured_ead"),
                Tile("corporate.ifrs9.stage_2_inflow_rate"),
                Tile("corporate.ifrs9.new_default_rate"),
                Tile("corporate.ifrs9.cure_rate"),
                Chart("corporate.ifrs9.new_default_rate", "period", "line",
                      title="New default rate, quarter by quarter"),
                Chart("corporate.ifrs9.cure_rate", "period", "line",
                      title="Cure rate, quarter by quarter"),
            )),
        Section(
            title="What triggered the move",
            subtitle=("Which significant-increase test fired, by exposure. A "
                      "facility can fire more than one in a quarter, so these "
                      "overlap and do not sum to the rate at which any "
                      "trigger fired."),
            tiles=(
                Tile("corporate.ifrs9.sicr_rate"),
                Tile("corporate.ifrs9.sicr_pd"),
                Tile("corporate.ifrs9.sicr_dpd"),
                Tile("corporate.ifrs9.sicr_rating"),
                Tile("corporate.ifrs9.sicr_watchlist"),
                Tile("corporate.ifrs9.sicr_covenant"),
            )),
        Section(
            title="Where the risk is concentrated",
            subtitle=("The same figures across the two dimensions the staging "
                      "dataset carries. A coverage ratio that is stable "
                      "overall can be two sectors moving in opposite "
                      "directions."),
            tiles=(
                Chart("corporate.ifrs9.total_ead", "sector", "bar",
                      title="Exposure by sector"),
                Chart("corporate.ifrs9.coverage", "sector", "bar",
                      title="ECL coverage by sector"),
                Chart("corporate.ifrs9.stage3_share", "sector", "bar",
                      title="Stage 3 ratio by sector"),
                Chart("corporate.ifrs9.total_ead", "segment", "bar",
                      title="Exposure by segment"),
            )),
        Section(
            title="Judgement and model parameters",
            subtitle=("How much of the provision is overlay rather than "
                      "model, and what the model is running on. The "
                      "parameters are exposure-weighted, so a large facility "
                      "counts for more."),
            tiles=(
                Tile("corporate.ifrs9.macro_overlay"),
                Tile("corporate.ifrs9.overlay_share"),
                Tile("corporate.ifrs9.weighted_pd"),
                Tile("corporate.ifrs9.weighted_lgd"),
                Tile("corporate.ifrs9.pd_drift"),
            )),
    ),
    absent=("corporate.ifrs9.ecl_movement", "corporate.ifrs9.scenario_ecl"),
)


# =========================================================== CRO Portfolio


CRO_PORTFOLIO = LensSpec(
    slug="cro-portfolio",
    name="CRO Portfolio",
    audience="Chief Risk Officer",
    portfolio="Corporate",
    domains=("Corporate Portfolio", "Corporate IFRS 9",
             "Corporate Early Warning"),
    purpose=(
        "The monthly read a Chief Risk Officer is asked for: how big the book "
        "is, what it is provisioned at, how much of it is already in trouble, "
        "and how much of it is heading there."),
    description=(
        "Position, provision, and the exposure that is deteriorating — the "
        "four questions a CRO is asked in the first five minutes of a risk "
        "committee."),
    sections=(
        Section(
            title="The book",
            subtitle="Size and spread, before anything is said about quality.",
            tiles=(
                Tile("corporate.exposure"),
                Tile("corporate.limit_amount"),
                Tile("corporate.customers"),
                Tile("corporate.obligor_groups"),
                Tile("corporate.utilisation_of_limits"),
                Chart("corporate.exposure", "period", "line",
                      title="Exposure, quarter by quarter"),
            )),
        Section(
            title="What it is provisioned at",
            subtitle=("Total provision and the coverage it implies, read off "
                      "the IFRS 9 staging book."),
            tiles=(
                Tile("corporate.ifrs9.total_ecl"),
                Tile("corporate.ifrs9.coverage"),
                Tile("corporate.ifrs9.stage2_share"),
                Tile("corporate.ifrs9.stage3_share"),
                Chart("corporate.ifrs9.coverage", "period", "line",
                      title="ECL coverage, quarter by quarter"),
            )),
        Section(
            title="What is already wrong",
            subtitle="Non-performing, impaired and in breach of appetite.",
            tiles=(
                Tile("corporate.npl_rate"),
                Tile("corporate.impaired_rate"),
                Tile("corporate.delinquent_rate"),
                Tile("corporate.appetite_breach_rate"),
            )),
        Section(
            title="What is heading that way",
            subtitle=("Watchlist, trend and covenant pressure. These run "
                      "ahead of the arrears above them."),
            tiles=(
                Tile("corporate.watchlist_rate"),
                Tile("corporate.deteriorating_rate"),
                Tile("corporate.downgrade_probability"),
                Tile("corporate.covenant_breach_rate"),
                Chart("corporate.exposure", "trend", "bar",
                      title="Exposure by credit trend"),
            )),
        Section(
            title="Where it is concentrated",
            subtitle=("A portfolio number that is comfortable can be two "
                      "sectors moving in opposite directions."),
            tiles=(
                Chart("corporate.exposure", "sector", "bar",
                      title="Exposure by sector"),
                Chart("corporate.npl_rate", "sector", "bar",
                      title="NPL rate by sector"),
                Chart("corporate.exposure", "region", "bar",
                      title="Exposure by region"),
            )),
        Section(
            title="What it earns",
            subtitle="Return against the capital the book consumes.",
            tiles=(
                Tile("corporate.weighted_raroc"),
                Tile("corporate.portfolio_weighted_pd"),
                Tile("corporate.weighted_internal_grade"),
            )),
    ),
    absent=("corporate.ifrs9.scenario_ecl", "corporate.ifrs9.ecl_movement"),
)


# ==================================================== Early Warning / TAC


EARLY_WARNING = LensSpec(
    slug="early-warning-tac",
    name="Early Warning and TAC",
    audience="Transaction Approval Committee and Head of Credit Risk",
    portfolio="Corporate",
    domains=("Corporate Early Warning", "Corporate Portfolio"),
    purpose=(
        "What is deteriorating before it is delinquent. A watchlist committee "
        "meets to decide which names to act on, and the figures that decide "
        "that are trend, covenant pressure and debt service — not arrears, "
        "which arrive after the decision should have been made."),
    description=(
        "Exposure that is deteriorating rather than delinquent: the "
        "watchlist, covenant headroom, debt service coverage, and where the "
        "early-warning triggers are firing."),
    sections=(
        Section(
            title="On the watchlist",
            subtitle="What the bank has already decided to watch.",
            tiles=(
                Tile("corporate.watchlist_exposure"),
                Tile("corporate.watchlist_rate"),
                Tile("corporate.critical_severity_rate"),
                Chart("corporate.watchlist_rate", "period", "line",
                      title="Watchlist exposure rate, quarter by quarter"),
            )),
        Section(
            title="Which way it is moving",
            subtitle=("The trend assessment and the modelled downgrade risk "
                      "behind it. A downgrade is a move in grade, and most "
                      "downgrades never reach default."),
            tiles=(
                Tile("corporate.deteriorating_rate"),
                Tile("corporate.downgrade_probability"),
                Tile("corporate.ai_risk_score"),
                Chart("corporate.exposure", "trend", "bar",
                      title="Exposure by credit trend"),
                Chart("corporate.exposure", "severity", "bar",
                      title="Exposure by early-warning severity"),
            )),
        Section(
            title="Can they service the debt",
            subtitle=("Debt service coverage and covenant headroom. The "
                      "averages hide the tail, which is what the two rates "
                      "beside them are for."),
            tiles=(
                Tile("corporate.weighted_dscr"),
                Tile("corporate.dscr_below_one_rate"),
                Tile("corporate.covenant_headroom"),
                Tile("corporate.covenant_breach_rate"),
            )),
        Section(
            title="What fired the trigger",
            subtitle=("The recorded reason and the recommended action, by "
                      "exposure. Read with the SICR trigger split on the "
                      "IFRS 9 lens, which measures the same idea against the "
                      "staging book."),
            tiles=(
                Chart("corporate.exposure", "trigger_type", "bar",
                      title="Exposure by trigger type"),
                Chart("corporate.exposure", "reason_code", "bar",
                      title="Exposure by reason code"),
                Chart("corporate.exposure", "recommended_action", "bar",
                      title="Exposure by recommended action"),
            )),
        Section(
            title="Where it is",
            subtitle="The deteriorating book, split the two ways a committee "
                     "asks for.",
            tiles=(
                Chart("corporate.deteriorating_rate", "sector", "bar",
                      title="Deteriorating rate by sector"),
                Chart("corporate.watchlist_rate", "sector", "bar",
                      title="Watchlist rate by sector"),
                Chart("corporate.deteriorating_rate", "region", "bar",
                      title="Deteriorating rate by region"),
            )),
    ),
    absent=("corporate.ifrs9.ecl_movement",),
)


# ======================================================= Portfolio Quality


PORTFOLIO_QUALITY = LensSpec(
    slug="portfolio-quality",
    name="Portfolio Quality",
    audience="Head of Credit Portfolio Management",
    portfolio="Corporate",
    domains=("Corporate Portfolio",),
    purpose=(
        "What the book is made of, by grade and by return. Not whether it is "
        "in trouble — that is the CRO lens — but whether the mix the bank has "
        "written is the mix it meant to write."),
    description=(
        "The credit quality mix of the corporate book: grade, rating bucket, "
        "probability of default, non-performing share and the return each "
        "slice earns."),
    sections=(
        Section(
            title="The book",
            subtitle="What there is to assess the quality of.",
            tiles=(
                Tile("corporate.exposure"),
                Tile("corporate.facilities"),
                Tile("corporate.customers"),
                Tile("corporate.undrawn"),
            )),
        Section(
            title="What grade it is",
            subtitle=("Exposure-weighted, because an unweighted mean grade "
                      "treats a small facility and a very large one as "
                      "equally important."),
            tiles=(
                Tile("corporate.weighted_internal_grade"),
                Tile("corporate.investment_grade_rate"),
                Tile("corporate.impaired_rate"),
                Tile("corporate.portfolio_weighted_pd"),
                Chart("corporate.exposure", "grade_band", "line",
                      title="Exposure by grade band", sort="label",
                      direction="asc"),
                Chart("corporate.exposure", "rating_bucket", "bar",
                      title="Exposure by rating bucket"),
            )),
        Section(
            title="How much is not performing",
            subtitle="Status rather than grade: what has actually gone wrong.",
            tiles=(
                Tile("corporate.npl_rate"),
                Tile("corporate.delinquent_rate"),
                Chart("corporate.npl_rate", "sector", "bar",
                      title="NPL rate by sector"),
                Chart("corporate.npl_rate", "period", "line",
                      title="NPL rate, quarter by quarter"),
            )),
        Section(
            title="What it earns for the risk",
            subtitle=("RAROC is a return on the capital a facility consumes, "
                      "so it can be negative on a facility that is still "
                      "making money."),
            tiles=(
                Tile("corporate.weighted_raroc"),
                Chart("corporate.weighted_raroc", "rating_bucket", "bar",
                      title="RAROC by rating bucket"),
                Chart("corporate.weighted_raroc", "sector", "bar",
                      title="RAROC by sector"),
            )),
        Section(
            title="What it is secured on",
            subtitle="Registered value, not realisable value.",
            tiles=(
                Tile("corporate.collateral_coverage"),
                Chart("corporate.exposure", "collateral_type", "bar",
                      title="Exposure by collateral type"),
                Chart("corporate.exposure", "product_type", "bar",
                      title="Exposure by product"),
            )),
    ),
    absent=("corporate.ifrs9.scenario_ecl",),
)


# ========================================= Concentration and Large Exposures


CONCENTRATION = LensSpec(
    slug="concentration-large-exposures",
    name="Concentration and Large Exposures",
    audience="Credit Committee and Head of Credit Risk",
    portfolio="Corporate",
    domains=("Corporate Concentration", "Corporate Portfolio"),
    purpose=(
        "Where the book is bunched. A portfolio can be well graded, well "
        "provisioned and well inside every limit on average, and still fail "
        "because too much of it is one sector, one region or one connected "
        "group."),
    description=(
        "How the corporate book is spread across sectors, regions, groups and "
        "products — and where it sits against the bank's stated appetite."),
    sections=(
        Section(
            title="How many names it is spread across",
            subtitle=("A group is several customers the bank treats as one "
                      "credit risk, which is the unit a large exposure limit "
                      "applies to."),
            tiles=(
                Tile("corporate.exposure"),
                Tile("corporate.customers"),
                Tile("corporate.obligor_groups"),
                Tile("corporate.average_group_exposure"),
            )),
        Section(
            title="Against appetite",
            subtitle="Appetite is the bank's own stated limit, not a "
                     "regulatory one.",
            tiles=(
                Tile("corporate.appetite_breach_exposure"),
                Tile("corporate.appetite_breach_rate"),
                Chart("corporate.appetite_breach_rate", "sector", "bar",
                      title="Appetite breach rate by sector"),
                Chart("corporate.appetite_breach_rate", "period", "line",
                      title="Appetite breach rate, quarter by quarter"),
            )),
        Section(
            title="Where the exposure is bunched",
            subtitle=("The same total, split four ways. Read the largest bar "
                      "on each rather than the shape of the whole."),
            tiles=(
                Chart("corporate.exposure", "sector", "bar",
                      title="Exposure by sector"),
                Chart("corporate.exposure", "region", "bar",
                      title="Exposure by region"),
                Chart("corporate.exposure", "country", "bar",
                      title="Exposure by country"),
                Chart("corporate.exposure", "segment", "bar",
                      title="Exposure by segment"),
            )),
        Section(
            title="Committed but not drawn",
            subtitle=("Undrawn commitment is still an exposure the bank is "
                      "obliged to fund, which is why IFRS 9 measures it with "
                      "a credit conversion factor."),
            tiles=(
                Tile("corporate.limit_amount"),
                Tile("corporate.undrawn"),
                Tile("corporate.utilisation_of_limits"),
                Chart("corporate.utilisation_of_limits", "sector", "bar",
                      title="Limit utilisation by sector"),
            )),
        Section(
            title="What it is secured on",
            subtitle="Registered collateral against the exposure it secures.",
            tiles=(
                Tile("corporate.collateral_coverage"),
                Chart("corporate.collateral_coverage", "sector", "bar",
                      title="Collateral coverage by sector"),
            )),
    ),
    absent=("corporate.ifrs9.scenario_ecl",),
)


# ======================================================= Board / Risk Committee


BOARD_RISK = LensSpec(
    slug="board-risk-committee",
    name="Board Risk Committee",
    audience="Board Risk Committee",
    portfolio="Corporate",
    domains=("Corporate Portfolio", "Corporate IFRS 9",
             "Corporate Early Warning", "Corporate Concentration"),
    purpose=(
        "One page a board can read in five minutes: how big, how provisioned, "
        "how much is wrong, how much is going wrong, and whether the bank is "
        "inside its own appetite. Every figure on it also appears on a "
        "specialist lens where it can be taken apart."),
    description=(
        "The quarterly one-page read for a board risk committee: position, "
        "provision, deterioration, concentration and appetite."),
    sections=(
        Section(
            title="Position",
            subtitle="What the bank has lent, and to how many.",
            tiles=(
                Tile("corporate.exposure"),
                Tile("corporate.customers"),
                Tile("corporate.obligor_groups"),
                Tile("corporate.utilisation_of_limits"),
            )),
        Section(
            title="Provision",
            subtitle=("Expected credit loss and the coverage it implies, from "
                      "the IFRS 9 staging book."),
            tiles=(
                Tile("corporate.ifrs9.total_ecl"),
                Tile("corporate.ifrs9.coverage"),
                Tile("corporate.ifrs9.stage3_share"),
                Chart("corporate.ifrs9.coverage", "period", "line",
                      title="ECL coverage, quarter by quarter"),
            )),
        Section(
            title="What has gone wrong",
            tiles=(
                Tile("corporate.npl_rate"),
                Tile("corporate.impaired_rate"),
                Chart("corporate.npl_rate", "period", "line",
                      title="NPL rate, quarter by quarter"),
            )),
        Section(
            title="What is going wrong",
            subtitle="Deterioration runs ahead of arrears by a quarter or "
                     "more.",
            tiles=(
                Tile("corporate.watchlist_rate"),
                Tile("corporate.deteriorating_rate"),
                Tile("corporate.covenant_breach_rate"),
            )),
        Section(
            title="Inside appetite",
            subtitle="The bank's own stated limits, and where the book sits "
                     "against them.",
            tiles=(
                Tile("corporate.appetite_breach_rate"),
                Tile("corporate.collateral_coverage"),
                Chart("corporate.exposure", "sector", "bar",
                      title="Exposure by sector"),
            )),
        Section(
            title="Return",
            tiles=(
                Tile("corporate.weighted_raroc"),
                Tile("corporate.portfolio_weighted_pd"),
            )),
    ),
    absent=("corporate.ifrs9.scenario_ecl", "corporate.ifrs9.ecl_movement"),
)

#: The lenses a deployment starts with, in the order the library shows them.
#:
#: Six of these answer the six roles §18 names; the two retail lenses are the
#: specialist pair this branch began with. They are one list rather than two
#: because a shipped lens and a lens somebody builds go through exactly the
#: same engine — `install()` calls the same `create` and `revise` the API
#: calls, writes the same definition JSON, and the result is editable,
#: rearrangeable and versioned like any other. A preconfigured lens that was
#: special-cased anywhere would be a demo rather than a starting point.
ALL: tuple[LensSpec, ...] = (
    CRO_PORTFOLIO,
    CORPORATE_IFRS9,
    EARLY_WARNING,
    PORTFOLIO_QUALITY,
    CONCENTRATION,
    BOARD_RISK,
    RETAIL_RISK,
    RETAIL_ANALYTICS,
)

# ------------------------------------------------------------------- proving


def check() -> list[str]:
    """Every problem with the shipped lenses, as sentences.

    Run by a test. A lens naming a metric that no longer exists, grouping one
    by a field its dataset does not carry, or asking for a chart type the
    renderer will not draw over that dimension is a defect that should fail a
    build rather than render a hole on somebody's screen.

    The tile rule is the one worth stating. A metric tile has no `visual`
    here, so it cannot declare a chart type the renderer ignores — the shape
    that let the shipped lenses claim eleven line charts and draw eleven
    single figures, with the old check passing the whole time.
    """
    from backend.metrics import service as metrics
    from backend.services import lenses as service

    known = {m.metric_id: m for m in lib.ALL}
    absent_ids = {u.metric_id for u in lib.UNSUPPORTED}
    problems: list[str] = []
    slugs: set[str] = set()

    for spec in ALL:
        if spec.slug in slugs:
            problems.append(f"Two lenses share the slug '{spec.slug}'.")
        slugs.add(spec.slug)
        if not spec.sections:
            problems.append(f"{spec.name} has no sections.")

        tiles = [t for t in spec.tiles if isinstance(t, Tile)]
        charts = [t for t in spec.tiles if isinstance(t, Chart)]
        if len(tiles) > service.MAX_TILES:
            problems.append(
                f"{spec.name} has {len(tiles)} metric tiles and a lens may "
                f"hold {service.MAX_TILES}.")
        if len(charts) > service.MAX_CHARTS:
            problems.append(
                f"{spec.name} has {len(charts)} charts and a lens may hold "
                f"{service.MAX_CHARTS}.")

        for entry in spec.tiles:
            metric = known.get(entry.metric_id)
            if metric is None:
                problems.append(
                    f"{spec.name} shows '{entry.metric_id}', which is not in "
                    "the metric library.")
                continue
            if isinstance(entry, Tile):
                continue

            dimensions = {d["name"]: d
                          for d in metrics.dimension_fields(metric)}
            chosen = dimensions.get(entry.dimension)
            if chosen is None:
                problems.append(
                    f"{spec.name} groups {metric.name} by "
                    f"'{entry.dimension}', which is not a dimension its "
                    f"dataset offers. Available: "
                    f"{', '.join(sorted(dimensions)) or 'none'}.")
                continue
            available, _refused = metrics.chart_types_for(metric, chosen)
            if entry.visual not in available:
                problems.append(
                    f"{spec.name} draws {metric.name} by "
                    f"{chosen['business_name']} as a '{entry.visual}'. Over "
                    f"that dimension the honest types are: "
                    f"{', '.join(available) or 'none'}.")
            if entry.aggregate not in metrics.AGGREGATIONS:
                problems.append(
                    f"{spec.name} rolls {metric.name} up with "
                    f"'{entry.aggregate}', which is not an aggregation a "
                    "chart may use.")
            if entry.sort not in metrics.SORTS:
                problems.append(
                    f"{spec.name} sorts {metric.name} by '{entry.sort}', "
                    "which is not a way a chart may be sorted.")
            if entry.direction not in metrics.DIRECTIONS:
                problems.append(
                    f"{spec.name} sorts {metric.name} '{entry.direction}', "
                    "which is not a sort direction.")
            if entry.compare not in metrics.COMPARISONS:
                problems.append(
                    f"{spec.name} compares {metric.name} against "
                    f"'{entry.compare}', which is not a comparison a chart "
                    "may draw.")

        for metric_id in spec.absent:
            if metric_id not in absent_ids:
                problems.append(
                    f"{spec.name} says '{metric_id}' is unavailable, but the "
                    "library does not list it as unsupported. Either it now "
                    "works and should be a tile, or the note is stale.")
            if metric_id in {t.metric_id for t in spec.tiles}:
                problems.append(
                    f"{spec.name} both shows '{metric_id}' and says it is "
                    "unavailable.")

    return problems


__all__ = ["LENSES_VERSION", "CRO_LENS", "Tile", "Chart", "Section",
           "LensSpec", "RETAIL_RISK", "RETAIL_ANALYTICS", "CORPORATE_IFRS9",
           "CRO_PORTFOLIO", "EARLY_WARNING", "PORTFOLIO_QUALITY",
           "CONCENTRATION", "BOARD_RISK",
           "ALL", "check", "install"]


# ------------------------------------------------------------------ seeding


def _panels(spec: LensSpec) -> list[Any]:
    from backend.services.lenses import Panel

    out: list[Any] = []
    for entry in spec.tiles:
        if isinstance(entry, Chart):
            out.append(Panel.chart(
                entry.metric_id, dimension=entry.dimension,
                title=entry.title, visual=entry.visual, note=entry.note,
                aggregate=entry.aggregate, sort=entry.sort,
                direction=entry.direction, limit=entry.limit,
                compare=entry.compare))
            continue
        out.append(Panel.metric(entry.metric_id, title=entry.title,
                                visual="kpi", note=entry.note))
    return out


def install(*, user_id: int | None = None,
            replace: bool = False) -> list[dict[str, Any]]:
    """Put the shipped lenses in the database, idempotently.

    Called from the demo bootstrap and safe to call again. An existing lens is
    left alone unless `replace` is set, and even then the change goes through
    the ordinary revision path so the previous definition is kept — somebody
    may have edited a shipped lens deliberately, and quietly overwriting their
    work would be worse than shipping a stale one.
    """
    from backend.services import lenses as service

    problems = check()
    if problems:
        raise service.InvalidLens(
            "The shipped lenses do not match the metric library:\n- "
            + "\n- ".join(problems))

    installed: list[dict[str, Any]] = []
    for spec in ALL:
        panels = _panels(spec)
        try:
            existing = service.by_slug(spec.slug)
        except service.LensNotFound:
            existing = None

        if existing is not None and not replace:
            installed.append({"slug": spec.slug, "action": "kept",
                              "lens_id": existing.id})
            continue
        if existing is not None:
            view = service.revise(
                existing.id, panels, user_id=user_id,
                request=f"Reinstall the shipped {spec.name} lens",
                change_summary=(
                    f"Replaced with the shipped definition: "
                    f"{len(panels)} tiles in {len(spec.sections)} sections."),
                sections=spec.layout(), notes=spec.notes(),
                scope=spec.scope(),
                # The prose too, not only the tiles. A shipped lens that
                # grows a band and keeps the description it had before is a
                # lens whose header describes a different screen.
                name=spec.name, description=spec.description,
                audience=spec.audience)
            installed.append({"slug": spec.slug, "action": "replaced",
                              "lens_id": view.id})
            continue

        view = service.create(
            name=spec.name, panels=panels, description=spec.description,
            audience=spec.audience, origin="seeded", user_id=user_id,
            slug=spec.slug,
            request=f"Install the shipped {spec.name} lens",
            sections=spec.layout(), notes=spec.notes(), scope=spec.scope())
        service.set_status(view.id, service.STATUS_PUBLISHED)
        installed.append({"slug": spec.slug, "action": "created",
                          "lens_id": view.id})
    return installed
