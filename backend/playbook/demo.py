"""Three committees a bank actually runs, and rolling them forward.

    Retail Credit Risk Committee     monthly, on the retail book
    Corporate Credit Committee       quarterly, on the corporate book
    IFRS 9 Impairment Committee      quarterly, on staging and coverage

Each arrives with a template, members with the access a real committee has,
a PREVIOUS approved pack and a CURRENT open one — so the first thing a reader
sees is a live cycle rather than an empty screen with a "new pack" button.

Why three, and why these three
------------------------------
One committee demonstrates a form. Three demonstrate that the product is
about GOVERNANCE rather than about one screen: they meet at different
cadences, read different books, measure at different period grains (retail is
monthly, corporate and IFRS 9 are quarterly), and sit at different points in
their cycle on the day of a demonstration — one approved and published, one
mid-review with a serious finding somebody has to answer, one still being
drafted with its data not yet complete.

Everything is calculated
------------------------
Not one figure below is typed in. Every KPI names a governed metric and is
measured against the real lake when the pack is generated, so the numbers on
a demonstration pack are the same numbers Ask CreditProbe would give for the
same question, and a figure with no value says WHICH of the five absences it
is rather than showing a zero. The materiality thresholds are declared here,
and the findings that appear are whatever those thresholds actually produce
against the data — not a list somebody wrote to look interesting.

Relative dates, always
----------------------
Every date is an offset from the day it was seeded, and the day it was
anchored to is stored on the committee. A demonstration in March and the same
demonstration in November both show a pack due in the right number of days.
`refresh()` rolls the scheduling fields forward by the days since the anchor
and leaves everything else alone; run twice on one day the shift is zero and
nothing is written, which is what makes it idempotent and what makes it safe
to put in a start-up script.

What it will not touch
----------------------
Content, status, findings, decisions, actions, reviews, commentary and
history. Only the two scheduling fields in `FIELDS`, and only on committees
whose `demo_origin` says CreditProbe seeded them — a committee a person
created has an empty `demo_origin` and is never a candidate, which is why the
marker is a stored column rather than a guess from the name.

And a MEETING DATE A PERSON MOVED is a commitment somebody made to other
people's diaries. Those are held back and reported rather than overwritten,
because the alternative is a demonstration tool quietly rescheduling a real
meeting. `force=True` is the only way past that, and it says so in the report
and in the history it writes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select

from backend.models.playbook import (
    SOURCE_SYSTEM,
    PlaybookCommittee,
    PlaybookEvent,
    PlaybookPack,
)

logger = logging.getLogger(__name__)

#: What `demo_origin` says on committees this repository's seed built. The
#: marker is a stored column rather than a guess from the code or the name,
#: so a person who names their committee "Retail Credit Risk Committee" is
#: never mistaken for the seeded one.
PLAYBOOK_DEMO = "creditprobe.playbook_demo"

#: The ONLY fields `refresh` moves. Anything not here is content.
FIELDS: tuple[str, ...] = ("meeting_at", "data_freeze_at")


# ------------------------------------------------------------- what is built


@dataclass(frozen=True)
class Committee:
    """One seeded committee and the two packs that make it a live cycle."""

    code: str
    name: str
    business_area: str
    purpose: str
    cadence: str
    meeting_weekday: int
    #: Retail is monthly; corporate and IFRS 9 are quarterly. Different grains
    #: on purpose: a committee whose pack is measured monthly and one whose
    #: pack is measured quarterly are different products to run, and a demo
    #: that hid that would be showing an easier problem than the real one.
    period_kind: str
    template: dict[str, Any]
    #: Days from today. Negative is in the past.
    previous_meeting: int
    current_meeting: int
    #: Where the current pack has got to on the day of the demonstration.
    current_status: str


def _kpi(metric_id: str, title: str, period: str = "") -> dict[str, Any]:
    return {"type": "KPI", "title": title,
            "config": {"metric_id": metric_id}, "period": period}


def _narrative(title: str, instructions: str) -> dict[str, Any]:
    return {"type": "NARRATIVE", "title": title,
            "config": {"narrative_instructions": instructions}}


RETAIL = Committee(
    code="retail-credit-risk-committee",
    name="Retail Credit Risk Committee",
    business_area="Retail Credit Risk",
    purpose=(
        "Monthly oversight of the retail lending book: performance, "
        "origination quality, collections and the decisions that follow."),
    cadence="MONTHLY",
    meeting_weekday=2,
    period_kind="month",
    previous_meeting=-28,
    current_meeting=6,
    # Mid-review, six days out. The state a pack owner is actually in when
    # they open the product, and the one where the chase list has something
    # to say.
    current_status="REVIEW",
    template={
        "name": "Monthly Retail Credit Pack",
        "code": "retail-monthly-pack",
        "description": (
            "The standard shape of the retail committee's monthly pack: how "
            "the book performed, what came in the door, and what is being "
            "done about the accounts that are going wrong."),
        "sections": [
            {
                "key": "book-performance",
                "title": "Book performance",
                "purpose": "How the retail book performed this period.",
                "required": True,
                "narrative_instructions": (
                    "Two or three sentences on the direction of the default "
                    "rate and the delinquency measures, and whether the "
                    "movement is concentrated or across the book."),
                "blocks": [
                    _kpi("retail.default_rate_current", "Facilities in default"),
                    _kpi("retail.dpd30_rate", "30+ DPD exposure rate"),
                    _kpi("retail.dpd90_rate", "90+ DPD exposure rate"),
                    _narrative(
                        "Commentary",
                        "State the direction, then the size, then whether it "
                        "is concentrated."),
                ],
            },
            {
                "key": "origination-quality",
                "title": "Origination quality",
                "purpose": "What came in the door, and how well it scored.",
                "required": True,
                "narrative_instructions": (
                    "Whether the quality of new business is holding, and "
                    "whether the application scorecard is still separating."),
                "blocks": [
                    _kpi("retail.observed_default_rate",
                         "Observed 12-month default rate"),
                    _kpi("retail.application.gini",
                         "Application scorecard Gini"),
                    _kpi("retail.average_debt_burden",
                         "Average debt burden ratio"),
                    _narrative("Commentary", "Quality first, then volume."),
                ],
            },
            {
                "key": "collections-and-forbearance",
                "title": "Collections and forbearance",
                "purpose": "The accounts already going wrong, and what is "
                           "being done about them.",
                "required": True,
                "blocks": [
                    _kpi("retail.forbearance_rate",
                         "Forbearance rate"),
                    _kpi("retail.card_utilisation",
                         "Card utilisation"),
                    _narrative(
                        "Commentary",
                        "Whether forbearance is working or deferring."),
                ],
            },
            {
                "key": "decisions",
                "title": "Decisions requested",
                "purpose": "What the committee is asked to decide.",
                "required": False,
                "blocks": [
                    {"type": "DECISION_REQUEST",
                     "title": "Decisions for this meeting"},
                ],
            },
        ],
        "materiality": [
            {"key": "retail_default_rate_move",
             "metric_id": "retail.default_rate_current",
             "comparison": "absolute_change", "threshold": 0.3,
             "direction": "worse", "severity": "HIGH",
             "finding_type": "DETERIORATION",
             "title": "Facilities in default moved materially"},
            {"key": "retail_default_rate_band",
             "metric_id": "retail.default_rate_current",
             "comparison": "above", "threshold": 2.0,
             "severity": "HIGH", "finding_type": "THRESHOLD_BREACH",
             "title": "Facilities in default above the agreed ceiling"},
            {"key": "retail_dpd30_move",
             "metric_id": "retail.dpd30_rate",
             "comparison": "absolute_change", "threshold": 0.5,
             "direction": "worse", "severity": "MEDIUM",
             "finding_type": "DETERIORATION",
             "title": "30+ DPD exposure rate moved materially"},
            {"key": "application_bad_rate_move",
             "metric_id": "retail.observed_default_rate",
             "comparison": "absolute_change", "threshold": 0.4,
             "direction": "worse", "severity": "HIGH",
             "finding_type": "DETERIORATION",
             "title": "Observed default rate deteriorated"},
            {"key": "application_gini_floor",
             "metric_id": "retail.application.gini",
             "comparison": "below", "threshold": 0.35,
             "severity": "HIGH", "finding_type": "MODEL_PERFORMANCE",
             "title": "Application scorecard Gini below its floor"},
            {"key": "restructured_rate_band",
             "metric_id": "retail.forbearance_rate",
             "comparison": "above", "threshold": 3.0,
             "severity": "MEDIUM", "finding_type": "CONCENTRATION",
             "title": "Forbearance rate above its band"},
            # A rule about ABSENCE, not about a number. A pack whose default
            # rate could not be calculated is a pack the committee must not
            # read as though the figure were fine.
            {"key": "default_rate_unavailable",
             "metric_id": "retail.default_rate_current",
             "comparison": "unavailable", "severity": "CRITICAL",
             "finding_type": "DATA_QUALITY",
             "title": "The default rate has no value this period"},
        ],
    },
)

RETAIL_IFRS9 = Committee(
    code="retail-ifrs9-committee",
    name="Retail IFRS 9 Committee",
    business_area="Retail IFRS 9",
    purpose=(
        "Monthly governance of the retail ECL result: staging, coverage, the "
        "management overlay, and the judgements behind them."),
    cadence="MONTHLY",
    meeting_weekday=3,
    period_kind="month",
    previous_meeting=-30,
    current_meeting=8,
    current_status="DRAFT",
    template={
        "name": "Retail IFRS 9 Monitoring Pack",
        "code": "retail-ifrs9-pack",
        "description": (
            "What the allowance is, what it is a proportion of, how it is "
            "staged, and how much of it is judgement rather than model."),
        "sections": [
            {
                "key": "the-allowance",
                "title": "The allowance",
                "purpose": "The headline figures, and what they are measured "
                           "against.",
                "required": True,
                "narrative_instructions": (
                    "State the allowance, then the coverage, then the "
                    "direction of travel. A coverage ratio with no exposure "
                    "beside it cannot be challenged."),
                "blocks": [
                    _kpi("retail.ecl", "Expected credit loss"),
                    _kpi("retail.gross_carrying_amount", "Gross carrying amount"),
                    _kpi("retail.ecl_coverage", "ECL coverage"),
                    _kpi("retail.overlay", "Management overlay"),
                    _narrative(
                        "Commentary",
                        "Direction first, then size, then whether the movement "
                        "is concentrated in one stage or one product."),
                ],
            },
            {
                "key": "staging",
                "title": "Staging and coverage by stage",
                "purpose": "Where the book sits across the three stages, and "
                           "whether each is provisioned as its stage implies.",
                "required": True,
                "narrative_instructions": (
                    "Stage 3 is a small share of exposure and a large share of "
                    "the allowance. Say whether that gap widened."),
                "blocks": [
                    _kpi("retail.stage1.share", "Stage 1 share of exposure"),
                    _kpi("retail.stage2.share", "Stage 2 share of exposure"),
                    _kpi("retail.stage3.share", "Stage 3 share of exposure"),
                    _kpi("retail.stage2.coverage", "Stage 2 coverage"),
                    _kpi("retail.stage3.coverage", "Stage 3 coverage"),
                    _kpi("retail.sicr_rate", "SICR rate"),
                    _narrative("Commentary",
                               "Movement between stages, and what drove it."),
                ],
            },
            {
                "key": "arrears",
                "title": "Arrears and write-offs",
                "purpose": "The outcomes the staging is meant to anticipate.",
                "required": True,
                "blocks": [
                    _kpi("retail.dpd30_rate", "30+ DPD exposure rate"),
                    _kpi("retail.dpd90_rate", "90+ DPD exposure rate"),
                    _kpi("retail.overdue_amount", "Amount overdue"),
                    _kpi("retail.writeoff_month", "Written off this month"),
                    _narrative("Commentary",
                               "Whether arrears are running ahead of staging."),
                ],
            },
            {
                "key": "decisions",
                "title": "Decisions requested",
                "purpose": "What the committee is asked to decide.",
                "required": False,
                "blocks": [
                    {"type": "DECISION_REQUEST",
                     "title": "Decisions for this meeting"},
                ],
            },
        ],
        "materiality": [
            {"key": "retail_coverage_move",
             "metric_id": "retail.ecl_coverage",
             "comparison": "absolute_change", "threshold": 0.05,
             "direction": "worse", "severity": "HIGH",
             "finding_type": "DETERIORATION",
             "title": "ECL coverage moved materially"},
            {"key": "retail_stage2_share_band",
             "metric_id": "retail.stage2.share",
             "comparison": "above", "threshold": 8.0,
             "severity": "MEDIUM", "finding_type": "THRESHOLD_BREACH",
             "title": "Stage 2 share above its agreed band"},
            {"key": "retail_stage3_coverage_floor",
             "metric_id": "retail.stage3.coverage",
             "comparison": "below", "threshold": 30.0,
             "severity": "CRITICAL", "finding_type": "THRESHOLD_BREACH",
             "title": "Stage 3 coverage below its floor"},
            {"key": "retail_sicr_move",
             "metric_id": "retail.sicr_rate",
             "comparison": "absolute_change", "threshold": 1.0,
             "direction": "worse", "severity": "MEDIUM",
             "finding_type": "DETERIORATION",
             "title": "SICR rate moved materially"},
            # A rule about ABSENCE. A pack whose allowance could not be
            # calculated must not be read as though the figure were fine.
            {"key": "retail_ecl_unavailable",
             "metric_id": "retail.ecl",
             "comparison": "unavailable", "severity": "CRITICAL",
             "finding_type": "DATA_QUALITY",
             "title": "The retail allowance has no value this period"},
        ],
    },
)


RETAIL_SCORECARD = Committee(
    code="retail-scorecard-committee",
    name="Retail Model Risk Committee",
    business_area="Retail Model Risk",
    purpose=(
        "Quarterly assurance on the retail scorecards: whether they still "
        "rank, whether the level is still right, and whether the population "
        "they score has moved."),
    cadence="QUARTERLY",
    meeting_weekday=4,
    period_kind="quarter",
    previous_meeting=-88,
    current_meeting=14,
    current_status="DRAFT",
    template={
        "name": "Retail Scorecard Assurance Pack",
        "code": "retail-scorecard-pack",
        "description": (
            "Discrimination, calibration and population stability for the "
            "retail scorecards, over the latest cohort whose twelve-month "
            "window has closed for every account."),
        "sections": [
            {
                "key": "discrimination",
                "title": "Discrimination",
                "purpose": "Whether the scores still separate the accounts "
                           "that defaulted from those that did not.",
                "required": True,
                "narrative_instructions": (
                    "Name the cohort and its size before the statistic. A Gini "
                    "on a cohort of four hundred is a different claim from the "
                    "same Gini on seventeen thousand."),
                "blocks": [
                    _kpi("retail.application.gini", "Application Gini"),
                    _kpi("retail.application.auc", "Application AUC"),
                    _kpi("retail.application.ks", "Application KS"),
                    _kpi("retail.behavioural.gini", "Behavioural Gini"),
                    _kpi("retail.bureau.gini", "Bureau score Gini"),
                    _narrative(
                        "Commentary",
                        "Compare the internal scorecards with the external "
                        "bureau reference, not only with their own history."),
                ],
            },
            {
                "key": "calibration",
                "title": "Calibration",
                "purpose": "Whether the predicted level is right, which is a "
                           "different question from whether the ranking is.",
                "required": True,
                "narrative_instructions": (
                    "Predicted against observed on the SAME population. Say "
                    "plainly that a scorecard can rank well and be badly "
                    "calibrated, and the reverse."),
                "blocks": [
                    _kpi("retail.predicted_pd", "Average predicted PD"),
                    _kpi("retail.observed_default_rate",
                         "Observed 12-month default rate"),
                    _narrative("Commentary",
                               "State the observed-to-expected ratio and what "
                               "would have to be true for it to be acceptable."),
                ],
            },
            {
                "key": "population",
                "title": "The population being scored",
                "purpose": "Whether the book the scorecard is applied to has "
                           "moved away from the one it was built on.",
                "required": True,
                "blocks": [
                    _kpi("retail.average_application_score",
                         "Average application score"),
                    _kpi("retail.average_behavioural_score",
                         "Average behavioural score"),
                    _kpi("retail.average_bureau_score", "Average bureau score"),
                    _kpi("retail.average_debt_burden", "Average debt burden"),
                    _kpi("retail.salary_transfer_rate", "Salary-transfer share"),
                    _narrative("Commentary",
                               "A shift in the population is not by itself a "
                               "model failure; say what it would take to be one."),
                ],
            },
            {
                "key": "decisions",
                "title": "Decisions requested",
                "purpose": "What the committee is asked to decide.",
                "required": False,
                "blocks": [
                    {"type": "DECISION_REQUEST",
                     "title": "Decisions for this meeting"},
                ],
            },
        ],
        "materiality": [
            {"key": "application_gini_floor",
             "metric_id": "retail.application.gini",
             "comparison": "below", "threshold": 0.30,
             "severity": "HIGH", "finding_type": "MODEL_PERFORMANCE",
             "title": "Application scorecard Gini below its floor"},
            {"key": "application_gini_move",
             "metric_id": "retail.application.gini",
             "comparison": "absolute_change", "threshold": 0.05,
             "direction": "worse", "severity": "MEDIUM",
             "finding_type": "MODEL_PERFORMANCE",
             "title": "Application scorecard Gini fell materially"},
            {"key": "behavioural_gini_floor",
             "metric_id": "retail.behavioural.gini",
             "comparison": "below", "threshold": 0.40,
             "severity": "HIGH", "finding_type": "MODEL_PERFORMANCE",
             "title": "Behavioural scorecard Gini below its floor"},
            {"key": "observed_rate_move",
             "metric_id": "retail.observed_default_rate",
             "comparison": "absolute_change", "threshold": 0.5,
             "direction": "worse", "severity": "HIGH",
             "finding_type": "DETERIORATION",
             "title": "Observed default rate deteriorated"},
            {"key": "application_gini_unavailable",
             "metric_id": "retail.application.gini",
             "comparison": "unavailable", "severity": "CRITICAL",
             "finding_type": "DATA_QUALITY",
             "title": "The application Gini has no value this cohort"},
        ],
    },
)


CORPORATE = Committee(
    code="corporate-credit-committee",
    name="Corporate Credit Committee",
    business_area="Corporate Credit Risk",
    purpose=(
        "Quarterly oversight of the corporate book: exposure, asset quality, "
        "the watchlist and the names the committee is asked to decide on."),
    cadence="QUARTERLY",
    meeting_weekday=3,
    period_kind="quarter",
    previous_meeting=-84,
    current_meeting=21,
    # Still being drafted, three weeks out, which is where a quarterly pack
    # honestly is at that distance.
    current_status="DRAFT",
    template={
        "name": "Quarterly Corporate Credit Pack",
        "code": "corporate-quarterly-pack",
        "description": (
            "The corporate committee's quarterly shape: the size and shape "
            "of the book, its asset quality, and the watchlist."),
        "sections": [
            {
                "key": "book-shape",
                "title": "Book shape",
                "purpose": "The size and utilisation of the corporate book.",
                "required": True,
                "narrative_instructions": (
                    "Whether the book grew or shrank, and whether "
                    "utilisation moved with it."),
                "blocks": [
                    _kpi("corporate.exposure", "Corporate exposure"),
                    _kpi("corporate.facilities", "Corporate facilities"),
                    _kpi("corporate.utilisation", "Corporate utilisation"),
                    _narrative("Commentary", "Size, then shape."),
                ],
            },
            {
                "key": "asset-quality",
                "title": "Asset quality",
                "purpose": "How the corporate book is performing.",
                "required": True,
                "narrative_instructions": (
                    "The direction of the NPL rate, and whether the "
                    "watchlist is telling the same story."),
                "blocks": [
                    _kpi("corporate.npl_rate", "Corporate NPL rate"),
                    _kpi("corporate.watchlist_rate", "Watchlist rate"),
                    _narrative("Commentary", "NPL first, watchlist second."),
                ],
            },
            {
                "key": "decisions",
                "title": "Decisions requested",
                "purpose": "The names and limits the committee is asked to "
                           "decide on.",
                "required": False,
                "blocks": [
                    {"type": "DECISION_REQUEST",
                     "title": "Decisions for this meeting"},
                ],
            },
        ],
        "materiality": [
            {"key": "corporate_npl_move",
             "metric_id": "corporate.npl_rate",
             "comparison": "absolute_change", "threshold": 0.25,
             "direction": "worse", "severity": "HIGH",
             "finding_type": "DETERIORATION",
             "title": "Corporate NPL rate moved materially"},
            {"key": "corporate_npl_band",
             "metric_id": "corporate.npl_rate",
             "comparison": "above", "threshold": 5.0,
             "severity": "HIGH", "finding_type": "THRESHOLD_BREACH",
             "title": "Corporate NPL rate above its agreed ceiling"},
            {"key": "watchlist_move",
             "metric_id": "corporate.watchlist_rate",
             "comparison": "absolute_change", "threshold": 2.0,
             "direction": "worse", "severity": "MEDIUM",
             "finding_type": "DETERIORATION",
             "title": "Watchlist rate moved materially"},
            {"key": "utilisation_band",
             "metric_id": "corporate.utilisation",
             "comparison": "outside_band", "low": 40.0, "high": 65.0,
             "severity": "MEDIUM", "finding_type": "CONCENTRATION",
             "title": "Corporate utilisation outside its agreed band"},
        ],
    },
)

IFRS9 = Committee(
    code="ifrs9-impairment-committee",
    name="IFRS 9 Impairment Committee",
    business_area="IFRS 9 Impairment",
    purpose=(
        "Quarterly governance of the ECL result: staging, coverage, "
        "management overlays and the judgements behind them."),
    cadence="QUARTERLY",
    meeting_weekday=4,
    period_kind="quarter",
    previous_meeting=-91,
    current_meeting=-3,
    # Already met and signed off. The read-only end of the lifecycle, where
    # "raise an amendment" is the only way to change anything — which is the
    # part of the governance argument a screenshot cannot make.
    current_status="PUBLISHED",
    template={
        "name": "Quarterly IFRS 9 Impairment Pack",
        "code": "ifrs9-quarterly-pack",
        "description": (
            "The impairment committee's quarterly shape: what the ECL is, "
            "how the book is staged, and what judgement sits on top."),
        "sections": [
            {
                "key": "ecl-result",
                "title": "The ECL result",
                "purpose": "What the expected credit loss is this quarter.",
                "required": True,
                "narrative_instructions": (
                    "The total, the direction, and whether coverage moved "
                    "with it or against it."),
                "blocks": [
                    _kpi("corporate.ifrs9.total_ecl", "Total ECL"),
                    _kpi("corporate.ifrs9.coverage", "ECL coverage"),
                    _narrative("Commentary", "Total, then coverage."),
                ],
            },
            {
                "key": "staging",
                "title": "Staging",
                "purpose": "How the book is staged and what moved.",
                "required": True,
                "narrative_instructions": (
                    "Whether the Stage 2 share moved, and whether the SICR "
                    "rate explains it."),
                "blocks": [
                    _kpi("corporate.ifrs9.stage2_share", "Stage 2 share"),
                    _kpi("corporate.ifrs9.sicr_rate", "SICR rate"),
                    _kpi("corporate.ifrs9.stage3_coverage",
                         "Stage 3 coverage"),
                    _narrative("Commentary", "Movement, then cause."),
                ],
            },
            {
                "key": "overlays",
                "title": "Management overlays",
                "purpose": "The judgement sitting on top of the model.",
                "required": True,
                "narrative_instructions": (
                    "How much of the ECL is judgement rather than model, and "
                    "whether that share is going up."),
                "blocks": [
                    _kpi("corporate.ifrs9.overlay_share", "Overlay share"),
                    _kpi("corporate.ifrs9.macro_overlay", "Macro overlay"),
                    {"type": "METHODOLOGY_NOTE",
                     "title": "Basis of the overlay",
                     "body": (
                         "The overlay is a management judgement applied on "
                         "top of the modelled result. Its basis, its owner "
                         "and the conditions for releasing it are recorded "
                         "with the decision that approved it.")},
                    _narrative("Commentary",
                               "Share first, then whether it is growing."),
                ],
            },
            {
                "key": "decisions",
                "title": "Decisions requested",
                "purpose": "The judgements the committee is asked to approve.",
                "required": False,
                "blocks": [
                    {"type": "DECISION_REQUEST",
                     "title": "Decisions for this meeting"},
                ],
            },
        ],
        "materiality": [
            {"key": "ecl_coverage_move",
             "metric_id": "corporate.ifrs9.coverage",
             "comparison": "absolute_change", "threshold": 0.15,
             "direction": "any", "severity": "HIGH",
             "finding_type": "ECL_MOVEMENT",
             "title": "ECL coverage moved materially"},
            {"key": "stage2_share_move",
             "metric_id": "corporate.ifrs9.stage2_share",
             "comparison": "absolute_change", "threshold": 0.5,
             "direction": "worse", "severity": "HIGH",
             "finding_type": "STAGING_CHANGE",
             "title": "Stage 2 share moved materially"},
            {"key": "sicr_rate_move",
             "metric_id": "corporate.ifrs9.sicr_rate",
             "comparison": "absolute_change", "threshold": 0.5,
             "direction": "worse", "severity": "MEDIUM",
             "finding_type": "STAGING_CHANGE",
             "title": "SICR rate moved materially"},
            {"key": "overlay_share_ceiling",
             "metric_id": "corporate.ifrs9.overlay_share",
             "comparison": "above", "threshold": 6.0,
             "severity": "HIGH", "finding_type": "OVERLAY",
             "title": "Management overlay above the share the committee set"},
            {"key": "stage3_coverage_floor",
             "metric_id": "corporate.ifrs9.stage3_coverage",
             "comparison": "below", "threshold": 40.0,
             "severity": "CRITICAL", "finding_type": "THRESHOLD_BREACH",
             "title": "Stage 3 coverage below its floor"},
        ],
    },
)

COMMITTEES: tuple[Committee, ...] = (
    RETAIL, RETAIL_IFRS9, RETAIL_SCORECARD, CORPORATE, IFRS9)

#: The committees whose packs are built from `corporate.*` metrics over the
#: corporate book. Retained in `COMMITTEES` — a corporate profile seeds all
#: three — and withheld from what a RETAIL installation seeds.
#:
#: The IFRS 9 Impairment Committee is here for the same reason as the Corporate
#: Credit Committee, and it is worth saying why, because a retail book plainly
#: HAS impairment. Every tile and every threshold in its pack names a
#: `corporate.ifrs9.*` metric, and the governed metric library publishes no
#: retail equivalent: its own docstring says the retail datasets are "not enough
#: for retail IFRS 9". Seeding the committee anyway would put an IFRS 9
#: governance pack in front of a reader with nothing calculable behind a single
#: tile. That is recorded as an open gap rather than papered over with a
#: committee that cannot meet.
CORPORATE_COMMITTEE_CODES: frozenset[str] = frozenset({CORPORATE.code, IFRS9.code})


def served_committees() -> tuple[Committee, ...]:
    """The committees this installation seeds."""
    from backend.retail.profile import is_retail

    if not is_retail():
        return COMMITTEES
    return tuple(c for c in COMMITTEES if c.code not in CORPORATE_COMMITTEE_CODES)


# ---------------------------------------------------------------- refreshing


@dataclass
class Moved:
    """One committee's dates, and what would move."""

    code: str
    name: str
    anchor: date | None
    shift_days: int = 0
    moved: list[str] = field(default_factory=list)
    #: Dates a person changed after seeding. Reported, and left alone.
    held: list[str] = field(default_factory=list)


@dataclass
class Refresh:
    """What one pass over the seeded committees did, or would do."""

    today: date
    dry_run: bool = False
    forced: bool = False
    committees: list[Moved] = field(default_factory=list)

    @property
    def shifted(self) -> int:
        return sum(len(c.moved) for c in self.committees)

    @property
    def held(self) -> int:
        return sum(len(c.held) for c in self.committees)

    def to_dict(self) -> dict[str, Any]:
        return {
            "today": self.today.isoformat(),
            "dry_run": self.dry_run,
            "forced": self.forced,
            "shifted": self.shifted,
            "held": self.held,
            "committees": [
                {"code": c.code, "name": c.name,
                 "anchor": c.anchor.isoformat() if c.anchor else None,
                 "shift_days": c.shift_days,
                 "moved": list(c.moved), "held": list(c.held)}
                for c in self.committees],
            "summary": self.summary,
        }

    @property
    def summary(self) -> str:
        if not self.committees:
            return ("No seeded committee is present, so there are no dates "
                    "to roll forward.")
        if self.shifted == 0 and self.held == 0:
            return (f"Every seeded committee is already anchored to "
                    f"{self.today}. Nothing to do.")
        lead = "would move" if self.dry_run else "moved"
        said = f"{self.shifted} date{'' if self.shifted == 1 else 's'} {lead}"
        if self.held:
            said += (f"; {self.held} held back because a person set "
                     f"{'it' if self.held == 1 else 'them'}")
        return said + "."


def seeded(session: Any) -> list[Any]:
    """The committees CreditProbe seeded, by their stored marker."""
    return list(session.execute(
        select(PlaybookCommittee)
        .where(PlaybookCommittee.demo_origin == PLAYBOOK_DEMO)
        .order_by(PlaybookCommittee.id)).scalars())


def _moved_by_a_person(session: Any, pack: Any, field_name: str) -> bool:
    """Whether somebody changed this field after the seed set it.

    The pack's history is append-only and records `{field: [before, after]}`
    with the source that made each change, so a human edit is findable: an
    event on this pack touching this field from a source that is not SYSTEM.
    """
    rows = session.execute(
        select(PlaybookEvent).where(
            PlaybookEvent.pack_id == pack.id,
            PlaybookEvent.entity_type == "pack",
            PlaybookEvent.source != SOURCE_SYSTEM)).scalars()
    return any(field_name in dict(row.changes or {}) for row in rows)


def refresh(session: Any, *, today: date | None = None, dry_run: bool = False,
            force: bool = False) -> Refresh:
    """Roll the seeded committees' dates forward to today.

    Idempotent: the shift is `today - anchor`, so a second run on the same day
    shifts by zero and writes nothing. That is what makes this safe to put in
    a start-up script rather than something somebody has to remember.
    """
    now = today or datetime.now(UTC).date()
    out = Refresh(today=now, dry_run=dry_run, forced=force)

    for committee in seeded(session):
        anchor = committee.demo_anchor_date
        entry = Moved(code=str(committee.code), name=str(committee.name),
                      anchor=anchor)
        out.committees.append(entry)
        if anchor is None:
            # Seeded without an anchor is a fault rather than a decision, and
            # guessing one would move every date by an arbitrary amount.
            continue
        shift = (now - anchor).days
        entry.shift_days = shift
        if shift == 0:
            continue

        packs = list(session.execute(
            select(PlaybookPack)
            .where(PlaybookPack.committee_id == committee.id,
                   PlaybookPack.demo_origin == PLAYBOOK_DEMO)).scalars())
        for pack in packs:
            for name in FIELDS:
                current = getattr(pack, name, None)
                if current is None:
                    continue
                if not force and _moved_by_a_person(session, pack, name):
                    entry.held.append(f"{pack.code}.{name}")
                    continue
                entry.moved.append(f"{pack.code}.{name}")
                if not dry_run:
                    setattr(pack, name, current + timedelta(days=shift))
        if not dry_run:
            committee.demo_anchor_date = now

    if not dry_run:
        session.flush()
    return out


__all__ = [
    "COMMITTEES", "CORPORATE", "CORPORATE_COMMITTEE_CODES", "Committee",
    "RETAIL_IFRS9", "RETAIL_SCORECARD",
    "FIELDS", "IFRS9", "Moved", "served_committees",
    "PLAYBOOK_DEMO", "RETAIL", "Refresh", "refresh", "seeded",
]
