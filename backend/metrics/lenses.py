"""The lenses CreditProbe ships with, built on the Metric Catalogue.

A preconfigured lens is not a demo. It is the answer to "what would a competent
head of this portfolio put on one screen", written once so that every
deployment starts from something a risk professional would recognise rather
than from an empty canvas.

Three of them are defined here — Retail Credit Risk, Retail Analytics and
Corporate IFRS 9 — and each is made of metric tiles from
:mod:`backend.metrics.library`. The CRO Lens is deliberately not here: it is a
composed executive narrative with its own page, and rebuilding it as a grid of
tiles would be a downgrade dressed as consistency.

What makes these honest
-----------------------
Every tile names a metric that exists and calculates against the governed data
in this deployment. Nothing is drawn from a placeholder, and nothing is
included because it would look good.

Where a metric a reader would reasonably expect is genuinely unavailable — a
retail IFRS 9 staging split, a roll rate, an approval rate — the lens says so,
in `notes`, with the reason and what would be needed. A view that quietly omits
the number somebody came for teaches them not to trust it. One that says
"retail IFRS 9 staging is not available in this deployment, because there is no
retail impairment dataset" does the opposite, and costs one line.

`check()` proves every tile against the live catalogue, and a test runs it. A
lens that names a metric which has stopped existing fails a test rather than
rendering a hole.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.metrics import library as lib
from backend.metrics.catalogue import Unsupported

LENSES_VERSION = "2.0.0"

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
    """One metric on a lens, and how this lens wants it drawn."""

    metric_id: str
    visual: str = "kpi"
    title: str = ""
    note: str = ""


@dataclass(frozen=True)
class Section:
    """A named group of tiles.

    Sections exist because a screen of eighteen equal tiles is a screen nobody
    reads top to bottom. "Where the book is" and "where it is going wrong" are
    different questions and belong in different bands.
    """

    title: str
    subtitle: str = ""
    tiles: tuple[Tile, ...] = ()


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

    @property
    def tiles(self) -> tuple[Tile, ...]:
        return tuple(t for section in self.sections for t in section.tiles)

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
    description=(
        "The retail book as it stands this month: how big it is, how much of "
        "it is behind, how it is staged and provisioned, and what the models "
        "say about where it is going."),
    sections=(
        Section(
            title="The book",
            subtitle="Size and shape, before anything is said about quality.",
            tiles=(
                Tile("retail.gross_carrying_amount", "kpi"),
                Tile("retail.facilities", "kpi"),
                Tile("retail.customers", "kpi"),
                Tile("retail.average_facility_size", "kpi"),
            )),
        Section(
            title="Impairment",
            subtitle=("The allowance, and what it is a proportion OF. A "
                      "coverage ratio with no exposure beside it is a number "
                      "nobody can challenge."),
            tiles=(
                Tile("retail.ecl", "kpi"),
                Tile("retail.ecl_coverage", "kpi"),
                Tile("retail.ecl", "line"),
                Tile("retail.overlay", "kpi"),
            )),
        Section(
            title="Staging",
            subtitle=("Exposure and coverage in each stage. Stage 3 is a small "
                      "part of the book and a large part of the allowance; the "
                      "two shares are shown so that is visible rather than "
                      "inferred."),
            tiles=(
                Tile("retail.stage1.share", "bar"),
                Tile("retail.stage2.share", "bar"),
                Tile("retail.stage3.share", "bar"),
                Tile("retail.stage2.coverage", "kpi"),
                Tile("retail.stage3.coverage", "kpi"),
                Tile("retail.sicr_rate", "line"),
                Tile("retail.forbearance_rate", "line"),
            )),
        Section(
            title="Arrears",
            subtitle=("Each threshold twice: by EXPOSURE and by ACCOUNT. A "
                      "dashboard showing one of them labelled simply '90+ DPD' "
                      "is read two ways by two people in the same meeting."),
            tiles=(
                Tile("retail.dpd30_rate", "line"),
                Tile("retail.dpd30_count_rate", "line"),
                Tile("retail.dpd90_rate", "line"),
                Tile("retail.overdue_amount", "kpi"),
                Tile("retail.writeoff_month", "line"),
                Tile("retail.default_rate_current", "kpi"),
            )),
        Section(
            title="What the models say",
            subtitle=("Scores and predicted PD. These are model OUTPUT, not "
                      "outcomes; the arrears band above is the outcome."),
            tiles=(
                Tile("retail.average_application_score", "kpi"),
                Tile("retail.average_behavioural_score", "kpi"),
                Tile("retail.average_pd_current", "kpi"),
            )),
    ),
)


# ============================================================ Retail IFRS 9


RETAIL_IFRS9 = LensSpec(
    slug="retail-ifrs9-ecl",
    name="Retail IFRS 9 and ECL",
    audience="Retail IFRS 9 Committee and Head of Impairment",
    description=(
        "What the retail book is provisioned at, how the three scenarios "
        "differ, where the exposure sits across the stages, and how much of "
        "the allowance is judgement rather than model."),
    sections=(
        Section(
            title="The allowance",
            subtitle=("The reported figure, what it covers, and the two "
                      "pieces it is made of. A coverage ratio with no "
                      "exposure beside it is a number nobody can challenge."),
            tiles=(
                Tile("retail.ecl", "kpi"),
                Tile("retail.gross_carrying_amount", "kpi"),
                Tile("retail.ecl_coverage", "kpi"),
                Tile("retail.ecl_weighted_before_overlay", "kpi"),
                Tile("retail.overlay", "kpi"),
                Tile("retail.ecl", "line"),
            )),
        Section(
            title="The three scenarios",
            subtitle=("Each scenario's ECL on its own, before weighting. The "
                      "reported allowance is the weighted result plus the "
                      "overlay and is deliberately shown beside them rather "
                      "than among them: it is not a fourth scenario."),
            tiles=(
                Tile("retail.ecl_upturn", "kpi"),
                Tile("retail.ecl_base", "kpi"),
                Tile("retail.ecl_downturn", "kpi"),
                Tile("retail.ecl_downturn", "line"),
            )),
        Section(
            title="Staging",
            subtitle=("Where the exposure is, and what each stage is "
                      "provisioned at. Stage 3 is a small share of the book "
                      "and a large share of the allowance; both shares are "
                      "here so that is visible rather than inferred."),
            tiles=(
                Tile("retail.stage1.exposure", "kpi"),
                Tile("retail.stage2.exposure", "kpi"),
                Tile("retail.stage3.exposure", "kpi"),
                Tile("retail.stage1.share", "bar"),
                Tile("retail.stage2.share", "bar"),
                Tile("retail.stage3.share", "bar"),
                Tile("retail.stage1.coverage", "kpi"),
                Tile("retail.stage2.coverage", "kpi"),
                Tile("retail.stage3.coverage", "kpi"),
            )),
        Section(
            title="What moves the staging",
            subtitle=("The triggers, over time. A stage split at one date "
                      "says where the book is; these say where it is going."),
            tiles=(
                Tile("retail.sicr_rate", "line"),
                Tile("retail.forbearance_rate", "line"),
                Tile("retail.stage3.ecl", "kpi"),
                Tile("retail.stage2.ecl", "kpi"),
            )),
    ),
)


# ======================================================= Retail Early Warning


RETAIL_EARLY_WARNING = LensSpec(
    slug="retail-early-warning",
    name="Retail Early Warning",
    audience="Early Warning Review and Head of Retail Collections",
    description=(
        "What is going wrong now and what is about to: arrears at each "
        "threshold by exposure and by account, the exposure already in "
        "default, and the behavioural signals that move before any of it "
        "shows up in the arrears."),
    sections=(
        Section(
            title="Already behind",
            subtitle=("Each threshold twice, by EXPOSURE and by ACCOUNT. A "
                      "single line labelled '30+ DPD' is read two ways by two "
                      "people in the same meeting."),
            tiles=(
                Tile("retail.dpd30_rate", "line"),
                Tile("retail.dpd30_count_rate", "line"),
                Tile("retail.dpd60_rate", "line"),
                Tile("retail.dpd90_rate", "line"),
                Tile("retail.overdue_amount", "kpi"),
                Tile("retail.default_rate_current", "kpi"),
            )),
        Section(
            title="What it is worth",
            subtitle=("The exposure at stake, and the allowance already held "
                      "against it."),
            tiles=(
                Tile("retail.stage3.exposure", "kpi"),
                Tile("retail.stage3.coverage", "kpi"),
                Tile("retail.stage2.exposure", "kpi"),
                Tile("retail.writeoff_month", "line"),
            )),
        Section(
            title="Signals that move first",
            subtitle=("Behaviour and affordability, before any of it reaches "
                      "the arrears bands above. These are inputs to a view "
                      "about the future; the bands above are the outcome."),
            tiles=(
                Tile("retail.average_behavioural_score", "line"),
                Tile("retail.average_bureau_score", "line"),
                Tile("retail.average_debt_burden", "line"),
                Tile("retail.card_utilisation", "line"),
                Tile("retail.average_pd_current", "line"),
            )),
        Section(
            title="Who is exposed to it",
            subtitle=("The structural features that decide how hard a "
                      "deterioration lands: whether salary comes through the "
                      "bank, and whether there is security behind the "
                      "facility."),
            tiles=(
                Tile("retail.salary_transfer_rate", "kpi"),
                Tile("retail.secured_share", "kpi"),
                Tile("retail.forbearance_rate", "line"),
                Tile("retail.sicr_rate", "line"),
            )),
    ),
)


# =========================================================== Retail Analytics


RETAIL_ANALYTICS = LensSpec(
    slug="retail-analytics",
    name="Retail Analytics",
    audience="Head of Retail Analytics and Model Validation",
    description=(
        "Whether the scorecards are still doing their job, and what the book "
        "they are being asked to score now looks like."),
    sections=(
        Section(
            title="Discrimination",
            subtitle=("Over the latest fully observed cohort — the last month "
                      "whose twelve-month window has closed for every account, "
                      "not the last month with any outcome at all. Those are "
                      "different months and the second one contains only "
                      "defaults."),
            tiles=(
                Tile("retail.application.gini", "kpi"),
                Tile("retail.application.auc", "kpi"),
                Tile("retail.application.ks", "kpi"),
                Tile("retail.behavioural.gini", "kpi"),
                Tile("retail.bureau.gini", "kpi"),
            )),
        Section(
            title="Calibration",
            subtitle=("Predicted against observed on the SAME population. "
                      "Discrimination is the ability to rank; this is whether "
                      "the level is right, and a scorecard can pass one and "
                      "fail the other."),
            tiles=(
                Tile("retail.predicted_pd", "kpi"),
                Tile("retail.observed_default_rate", "kpi"),
                Tile("retail.observed_default_rate", "line"),
            )),
        Section(
            title="Who is being scored",
            subtitle="The population the models are applied to, as it moves.",
            tiles=(
                Tile("retail.average_application_score", "line"),
                Tile("retail.average_behavioural_score", "line"),
                Tile("retail.average_bureau_score", "line"),
                Tile("retail.average_debt_burden", "line"),
                Tile("retail.salary_transfer_rate", "line"),
                Tile("retail.secured_share", "kpi"),
                Tile("retail.card_utilisation", "line"),
                Tile("retail.undrawn", "kpi"),
            )),
    ),
)


# =========================================================== Corporate IFRS 9


CORPORATE_IFRS9 = LensSpec(
    slug="corporate-ifrs9",
    name="Corporate IFRS 9",
    audience="IFRS 9 Committee and Head of Impairment",
    description=(
        "Where the corporate book sits across the three stages, what it is "
        "provisioned at, and how much of the provision is judgement."),
    sections=(
        Section(
            title="The provision",
            subtitle="Total exposure, total ECL, and the coverage between them.",
            tiles=(
                Tile("corporate.ifrs9.total_ead", "kpi"),
                Tile("corporate.ifrs9.total_ecl", "line"),
                Tile("corporate.ifrs9.coverage", "kpi"),
            )),
        Section(
            title="Where the book sits",
            subtitle=("Exposure by stage, as an amount and as a share. The "
                      "shares sum to the book; the amounts do not move "
                      "together with them when the book grows."),
            tiles=(
                Tile("corporate.ifrs9.stage1_ead", "bar"),
                Tile("corporate.ifrs9.stage2_ead", "bar"),
                Tile("corporate.ifrs9.stage3_ead", "bar"),
                Tile("corporate.ifrs9.stage1_share", "kpi"),
                Tile("corporate.ifrs9.stage2_share", "line"),
                Tile("corporate.ifrs9.stage3_share", "kpi"),
            )),
        Section(
            title="What each stage is provisioned at",
            subtitle=("The provision held against each stage, and the coverage "
                      "it implies. Stage 3 coverage moving while Stage 3 "
                      "exposure does not is a change in expected recovery, "
                      "not a change in what has defaulted."),
            tiles=(
                Tile("corporate.ifrs9.stage1_ecl", "kpi"),
                Tile("corporate.ifrs9.stage2_ecl", "kpi"),
                Tile("corporate.ifrs9.stage3_ecl", "kpi"),
                Tile("corporate.ifrs9.stage1_coverage", "kpi"),
                Tile("corporate.ifrs9.stage2_coverage", "kpi"),
                Tile("corporate.ifrs9.stage3_coverage", "kpi"),
            )),
        Section(
            title="Movement and judgement",
            subtitle=("How much of the book triggered SICR, how much changed "
                      "stage, and how much of the provision is overlay rather "
                      "than model."),
            tiles=(
                Tile("corporate.ifrs9.sicr_rate", "kpi"),
                Tile("corporate.ifrs9.stage_moved", "kpi"),
                Tile("corporate.ifrs9.macro_overlay", "kpi"),
                Tile("corporate.ifrs9.overlay_share", "kpi"),
            )),
        Section(
            title="Model parameters",
            subtitle="Exposure-weighted, so a large facility counts for more.",
            tiles=(
                Tile("corporate.ifrs9.weighted_pd", "kpi"),
                Tile("corporate.ifrs9.weighted_lgd", "kpi"),
            )),
    ),
    absent=("corporate.ifrs9.ecl_movement", "corporate.ifrs9.scenario_ecl"),
)


ALL: tuple[LensSpec, ...] = (RETAIL_RISK, RETAIL_IFRS9, RETAIL_EARLY_WARNING,
                             RETAIL_ANALYTICS, CORPORATE_IFRS9)

#: Shipped lenses that read the corporate book. Retained in `ALL` — a corporate
#: profile installs all three — and withheld from what a RETAIL installation
#: seeds, because the bootstrap runs on every fresh deployment and would put a
#: Corporate IFRS 9 lens in the Lens catalogue of a product that holds no
#: corporate book. The bootstrap path is exactly where a retired surface comes
#: back: nobody types its URL, the installer creates it.
CORPORATE_LENS_SLUGS: frozenset[str] = frozenset({CORPORATE_IFRS9.slug})


def served() -> tuple[LensSpec, ...]:
    """The lenses this installation seeds and offers."""
    from backend.retail.profile import is_retail

    if not is_retail():
        return ALL
    return tuple(spec for spec in ALL if spec.slug not in CORPORATE_LENS_SLUGS)


# ------------------------------------------------------------------- proving


def check() -> list[str]:
    """Every problem with the shipped lenses, as sentences.

    Run by a test. A lens naming a metric that no longer exists, or asking for
    a chart the metric has not declared itself drawable as, is a defect that
    should fail a build rather than render a hole on somebody's screen.
    """
    from backend.services.lenses import VISUALS

    # Against what the library DEFINES, not what this profile serves. Every
    # lens in `ALL` is checked, including the corporate one that is retained
    # and withheld, and a corporate lens naming a corporate metric is
    # well-formed — it is simply not installed here. Checking against the
    # served set turned "this lens is not for this installation" into
    # twenty-one spurious defects.
    # Every metric the product can define under ANY profile, not the subset
    # this one serves. `ALL` below checks all three shipped lenses, including
    # the corporate one that is retained and withheld, and a corporate lens
    # naming a corporate metric is well-formed — it is simply not installed
    # here. The retail library is applied second so that where the two define
    # the same id, the one this installation actually runs decides which
    # visuals are honest.
    from backend.metrics import retail_library

    known = {m.metric_id: m for m in lib.DEFINED}
    known.update({m.metric_id: m for m in retail_library.ALL})
    # Both unsupported lists, for the same reason: a corporate lens declaring a
    # corporate metric absent is well-formed even where this profile publishes
    # only the retail absences.
    absent_ids = ({u.metric_id for u in lib.DEFINED_UNSUPPORTED}
                  | {u.metric_id for u in lib.RETAIL_UNSUPPORTED})
    problems: list[str] = []
    slugs: set[str] = set()

    for spec in ALL:
        if spec.slug in slugs:
            problems.append(f"Two lenses share the slug '{spec.slug}'.")
        slugs.add(spec.slug)
        if not spec.sections:
            problems.append(f"{spec.name} has no sections.")

        for tile in spec.tiles:
            metric = known.get(tile.metric_id)
            if metric is None:
                problems.append(
                    f"{spec.name} shows '{tile.metric_id}', which is not in "
                    "the metric library.")
                continue
            if tile.visual not in VISUALS:
                problems.append(
                    f"{spec.name} draws {metric.name} as '{tile.visual}', "
                    "which is not a way a lens panel may be drawn.")
            elif tile.visual not in metric.visuals:
                problems.append(
                    f"{spec.name} draws {metric.name} as '{tile.visual}', but "
                    f"it can honestly be shown as: "
                    f"{', '.join(metric.visuals)}.")

        for metric_id in spec.absent:
            if metric_id not in absent_ids:
                problems.append(
                    f"{spec.name} says '{metric_id}' is unavailable, but the "
                    "library does not list it as unsupported. Either it now "
                    "works and should be a tile, or the note is stale.")

    return problems


__all__ = ["LENSES_VERSION", "CRO_LENS", "Tile", "Section", "LensSpec",
           "RETAIL_RISK", "RETAIL_ANALYTICS", "CORPORATE_IFRS9", "ALL",
           "CORPORATE_LENS_SLUGS", "served",
           "check", "install"]


# ------------------------------------------------------------------ seeding


#: How a tile's declared visual becomes a panel that can actually draw it.
#:
#: The defect this closes. Every tile became a METRIC panel whatever its
#: visual, and a metric panel computes one scalar. So a tile declared `line`
#: rendered as a second copy of the same KPI — the Retail Credit Risk lens
#: showed "Retail Expected Credit Loss 15,952,109" twice, side by side, with
#: no chart and nothing to say the two were meant to be different. A lens that
#: asks for a trend and draws a number is not showing a trend.
#:
#: A `line` is a trend, so it is drawn across `reporting_month` in calendar
#: order. A `bar` is a comparison, so it is drawn across the product family —
#: the one breakdown every retail metric on this book supports and the one a
#: reader means by "by product".
TREND_DIMENSION = "reporting_month"
COMPARISON_DIMENSION = "product_label"


def _panels(spec: LensSpec) -> list[Any]:
    from backend.services.lenses import Panel

    out: list[Any] = []
    for tile in spec.tiles:
        if tile.visual == "line":
            out.append(Panel.chart(
                tile.metric_id, dimension=TREND_DIMENSION, visual="line",
                title=tile.title, note=tile.note,
                sort="label", direction="asc", limit=60))
        elif tile.visual == "bar":
            out.append(Panel.chart(
                tile.metric_id, dimension=COMPARISON_DIMENSION, visual="bar",
                title=tile.title, note=tile.note,
                sort="value", direction="desc", limit=20))
        else:
            out.append(Panel.metric(tile.metric_id, title=tile.title,
                                    visual=tile.visual, note=tile.note))
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
    for spec in served():
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
                sections=spec.layout(), notes=spec.notes())
            installed.append({"slug": spec.slug, "action": "replaced",
                              "lens_id": view.id})
            continue

        view = service.create(
            name=spec.name, panels=panels, description=spec.description,
            audience=spec.audience, origin="seeded", user_id=user_id,
            slug=spec.slug,
            request=f"Install the shipped {spec.name} lens",
            sections=spec.layout(), notes=spec.notes())
        service.set_status(view.id, service.STATUS_PUBLISHED)
        installed.append({"slug": spec.slug, "action": "created",
                          "lens_id": view.id})
    return installed
