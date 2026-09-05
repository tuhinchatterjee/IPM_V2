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
        "it is behind, and what the models say about where it is going."),
    sections=(
        Section(
            title="The book",
            subtitle="Size and shape before anything is said about quality.",
            tiles=(
                Tile("retail.balance", "kpi"),
                Tile("retail.accounts", "kpi"),
                Tile("retail.average_balance", "kpi"),
                Tile("retail.utilisation", "kpi"),
            )),
        Section(
            title="Arrears",
            subtitle=("Each bucket twice: how many customers are behind, and "
                      "how much money is. A dashboard showing one of those "
                      "labelled simply '90+ DPD' is read two ways."),
            tiles=(
                Tile("retail.dpd_30_count", "line"),
                Tile("retail.dpd_30_balance", "line"),
                Tile("retail.dpd_90_count", "line"),
                Tile("retail.dpd_90_balance", "line"),
                Tile("retail.delinquent_balance", "kpi"),
                Tile("retail.default_rate", "line"),
            )),
        Section(
            title="Stress in the book",
            subtitle="Behaviour that runs ahead of arrears.",
            tiles=(
                Tile("retail.high_utilisation_rate", "kpi"),
                Tile("retail.missed_payments", "kpi"),
                Tile("retail.restructured_rate", "kpi"),
            )),
        Section(
            title="What the models say",
            subtitle=("Scores and predicted PD. These are model output, not "
                      "outcomes; the arrears band above is the outcome."),
            tiles=(
                Tile("retail.average_score", "kpi"),
                Tile("retail.average_bureau_score", "kpi"),
                Tile("retail.average_pd", "kpi"),
            )),
    ),
    absent=("retail.ifrs9.stage_exposure", "retail.ifrs9.ecl",
            "retail.roll_rate", "retail.cure_rate"),
)


# =========================================================== Retail Analytics


RETAIL_ANALYTICS = LensSpec(
    slug="retail-analytics",
    name="Retail Analytics",
    audience="Head of Retail Analytics and Model Validation",
    description=(
        "Origination volume and quality, and whether the scorecards are still "
        "doing what they were built to do."),
    sections=(
        Section(
            title="What came through the door",
            subtitle="Application volume and size, by application month.",
            tiles=(
                Tile("retail.applications", "line"),
                Tile("retail.requested_amount", "kpi"),
                Tile("retail.average_ticket", "kpi"),
            )),
        Section(
            title="Who was asking",
            subtitle=("Affordability as recorded at application. These are "
                      "applicant characteristics, not book characteristics."),
            tiles=(
                Tile("retail.average_loan_to_income", "kpi"),
                Tile("retail.average_debt_burden", "kpi"),
                Tile("retail.salary_transfer_rate", "kpi"),
            )),
        Section(
            title="How the cohorts turned out",
            subtitle=("Only cohorts whose performance window has closed. A "
                      "bad rate on a cohort still maturing understates."),
            tiles=(
                Tile("retail.application_bad_rate", "kpi"),
                Tile("retail.scorecard.matured", "kpi"),
            )),
        Section(
            title="Are the scorecards still working",
            subtitle=("Discrimination, separation, stability and calibration. "
                      "A model can rank well and still be badly calibrated, "
                      "which is why all four are here."),
            tiles=(
                Tile("retail.scorecard.gini", "line"),
                Tile("retail.scorecard.ks", "kpi"),
                Tile("retail.scorecard.calibration", "kpi"),
                Tile("retail.application_gini", "kpi"),
            )),
    ),
    absent=("retail.approval_rate", "retail.scorecard.psi"),
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


ALL: tuple[LensSpec, ...] = (RETAIL_RISK, RETAIL_ANALYTICS, CORPORATE_IFRS9)


# ------------------------------------------------------------------- proving


def check() -> list[str]:
    """Every problem with the shipped lenses, as sentences.

    Run by a test. A lens naming a metric that no longer exists, or asking for
    a chart the metric has not declared itself drawable as, is a defect that
    should fail a build rather than render a hole on somebody's screen.
    """
    from backend.services.lenses import VISUALS

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
           "check", "install"]


# ------------------------------------------------------------------ seeding


def _panels(spec: LensSpec) -> list[Any]:
    from backend.services.lenses import Panel

    return [Panel.metric(tile.metric_id, title=tile.title,
                         visual=tile.visual, note=tile.note)
            for tile in spec.tiles]


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
