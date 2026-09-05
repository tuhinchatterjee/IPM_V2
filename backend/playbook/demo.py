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
                    _kpi("retail.default_rate", "Retail default rate"),
                    _kpi("retail.dpd_30_balance", "30+ DPD exposure rate"),
                    _kpi("retail.dpd_90_balance", "90+ DPD exposure rate"),
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
                    _kpi("retail.application_bad_rate",
                         "Application cohort bad rate"),
                    _kpi("retail.application_gini",
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
                    _kpi("retail.restructured_rate",
                         "Restructured account rate"),
                    _kpi("retail.high_utilisation_rate",
                         "Accounts above 90% utilised"),
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
             "metric_id": "retail.default_rate",
             "comparison": "absolute_change", "threshold": 0.3,
             "direction": "worse", "severity": "HIGH",
             "finding_type": "DETERIORATION",
             "title": "Retail default rate moved materially"},
            {"key": "retail_default_rate_band",
             "metric_id": "retail.default_rate",
             "comparison": "above", "threshold": 7.0,
             "severity": "HIGH", "finding_type": "THRESHOLD_BREACH",
             "title": "Retail default rate above its agreed ceiling"},
            {"key": "retail_dpd30_move",
             "metric_id": "retail.dpd_30_balance",
             "comparison": "absolute_change", "threshold": 0.5,
             "direction": "worse", "severity": "MEDIUM",
             "finding_type": "DETERIORATION",
             "title": "30+ DPD exposure rate moved materially"},
            {"key": "application_bad_rate_move",
             "metric_id": "retail.application_bad_rate",
             "comparison": "absolute_change", "threshold": 0.4,
             "direction": "worse", "severity": "HIGH",
             "finding_type": "DETERIORATION",
             "title": "Application cohort bad rate deteriorated"},
            {"key": "application_gini_floor",
             "metric_id": "retail.application_gini",
             "comparison": "below", "threshold": 0.35,
             "severity": "HIGH", "finding_type": "MODEL_PERFORMANCE",
             "title": "Application scorecard Gini below its floor"},
            {"key": "restructured_rate_band",
             "metric_id": "retail.restructured_rate",
             "comparison": "above", "threshold": 10.0,
             "severity": "MEDIUM", "finding_type": "CONCENTRATION",
             "title": "Restructured account rate above its band"},
            # A rule about ABSENCE, not about a number. A pack whose default
            # rate could not be calculated is a pack the committee must not
            # read as though the figure were fine.
            {"key": "default_rate_unavailable",
             "metric_id": "retail.default_rate",
             "comparison": "unavailable", "severity": "CRITICAL",
             "finding_type": "DATA_QUALITY",
             "title": "The retail default rate has no value this period"},
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

COMMITTEES: tuple[Committee, ...] = (RETAIL, CORPORATE, IFRS9)


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
    "COMMITTEES", "CORPORATE", "Committee", "FIELDS", "IFRS9", "Moved",
    "PLAYBOOK_DEMO", "RETAIL", "Refresh", "refresh", "seeded",
]
