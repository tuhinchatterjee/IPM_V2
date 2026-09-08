"""
Lenses: a live dashboard, built and changed by asking.

What a Lens is
--------------
A named view of the book for one audience — the CRO, the Head of Corporate
Credit, the IFRS 9 committee — made of PANELS. Each panel names a certified
analysis, its parameters, and how the result should be drawn.

Two things make it different from a dashboard somebody configured once:

**It is live.** Opening a Lens executes its analyses against whatever is
published now. There are no stored figures, so a Lens cannot go stale without
anybody noticing, and every number on it carries a Trace exactly as it would if
you had asked for it by hand.

**It is changed by asking.** "Add the sector breakdown", "drop the stress panel",
"show me the last eight quarters instead of four" — each request produces a new
REVISION of the definition, with a plain sentence saying what changed. The
previous revision is kept, so a Lens somebody relies on can be put back.

What the AI may and may not do
------------------------------
It may SELECT from the registered analyses and set their declared parameters. It
may not invent an analysis, write a query, compute a figure, or add a panel that
reads anything the Data Access Layer does not govern. Every proposed change is
validated against the Engine Registry before it is stored, and a request the
platform cannot honour comes back as a refusal that says why — never as a panel
that silently does nothing.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from backend.config import settings

logger = logging.getLogger(__name__)

STATUS_DRAFT = "draft"
STATUS_PUBLISHED = "published"
STATUS_ARCHIVED = "archived"
STATUSES = (STATUS_DRAFT, STATUS_PUBLISHED, STATUS_ARCHIVED)

#: How a panel may be drawn. Each maps to a renderer that already exists; a
#: proposal asking for anything else is refused rather than rendered as a table
#: and quietly relabelled.
VISUALS = ("auto", "kpi", "table", "bar", "line", "matrix")

#: How many ANALYSIS panels a lens may hold. Each one runs a full analysis, and
#: beyond a dozen nobody reads the lens, they scroll past it.
MAX_PANELS = 12

#: How many METRIC tiles a lens may hold. Higher than the analysis limit,
#: because a tile is one number with a label rather than a whole result table.
#:
#: Raised from 24 deliberately. The number that matters for readability is
#: tiles per BAND, not tiles per lens, and bands are what the reader actually
#: scans — a screen of thirty-two figures under seven headings reads, and a
#: screen of eighteen under none does not. The shipped Corporate IFRS 9 lens
#: is the case that forced the question: stage exposure, stage ECL, stage
#: coverage, the five stage transitions, the five SICR triggers, overlay and
#: the model parameters are all things an impairment committee is asked about
#: by name, and at 24 the lens had to drop one of those groups entirely rather
#: than show it. Dropping a group a committee asks for is a worse failure than
#: a longer page.
#:
#: It is still a limit, and still refuses: past this a lens has stopped being
#: a view of one thing and become a catalogue.
MAX_TILES = 36

SLUG_RE = re.compile(r"[^a-z0-9]+")


class LensNotFound(LookupError):
    pass


class InvalidLens(ValueError):
    """The definition is not one the platform will render, and the message says why."""


class StorageUnavailable(RuntimeError):
    """Lenses need PostgreSQL. Running an analysis does not."""


def _require_db() -> None:
    if not settings.has_database:
        raise StorageUnavailable(
            "Lenses are stored in PostgreSQL. Analyses still run without it; "
            "the view just is not kept."
        )


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def slugify(name: str) -> str:
    return SLUG_RE.sub("-", (name or "").strip().lower()).strip("-") or "lens"


# ------------------------------------------------------------- the definition


#: The two things a panel can be. An ANALYSIS panel runs a registered analysis
#: through the Engine Registry; a METRIC panel calculates one governed or
#: user-built metric from the Metric Catalogue. Both go through the same
#: validated analytical plan and the same executor — the difference is which
#: definition they name, not how the number is produced.
KIND_ANALYSIS = "analysis"
KIND_METRIC = "metric"
#: A metric broken out across one dimension. The same metric, the same
#: formula, the same executor as the tile — grouped. It is a third kind
#: rather than a metric tile with a `visual` set, because a chart carries a
#: configuration a single figure has no use for (a dimension, a sort, a
#: comparison) and because the two are validated against different rules.
KIND_CHART = "chart"
KINDS = (KIND_ANALYSIS, KIND_METRIC, KIND_CHART)

#: How many charts one lens may hold. A chart costs a grouped scan of the
#: lake, so this is lower than the tile limit, and low enough that a lens
#: stays a view rather than a report.
MAX_CHARTS = 12


@dataclass
class Panel:
    """One thing on a Lens.

    Two kinds share this shape rather than becoming two classes, because a lens
    holds an ordered list of things to draw and everything that walks that list
    — validation, revision, rendering, layout — should not have to branch on
    which sort of tile it is holding until the moment it actually runs one.
    """

    analysis_id: str = ""
    title: str = ""
    visual: str = "auto"
    params: dict[str, Any] = field(default_factory=dict)
    #: Governed filters, applied to this panel only.
    filters: dict[str, Any] = field(default_factory=dict)
    note: str = ""
    kind: str = KIND_ANALYSIS
    #: Set on a metric panel; the id of a governed or user-built metric.
    metric_id: str = ""
    #: A period this tile pins itself to, overriding the lens period. Empty
    #: means it follows whatever the lens is showing.
    period: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "analysis_id": self.analysis_id,
            "metric_id": self.metric_id,
            "title": self.title,
            "visual": self.visual,
            "params": dict(self.params),
            "filters": dict(self.filters),
            "period": self.period,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Panel:
        metric_id = str(payload.get("metric_id") or "")
        # A definition written before metric panels existed has no `kind`, and
        # naming a metric is unambiguous, so the kind is inferred rather than
        # requiring every stored lens to be rewritten.
        kind = str(payload.get("kind")
                   or (KIND_METRIC if metric_id else KIND_ANALYSIS))
        return cls(
            analysis_id=str(payload.get("analysis_id") or ""),
            metric_id=metric_id,
            kind=kind,
            title=str(payload.get("title") or ""),
            visual=str(payload.get("visual") or "auto"),
            params=dict(payload.get("params") or {}),
            filters=dict(payload.get("filters") or {}),
            period=str(payload.get("period") or ""),
            note=str(payload.get("note") or ""),
        )

    @classmethod
    def metric(cls, metric_id: str, *, title: str = "", visual: str = "kpi",
               period: str = "", note: str = "") -> Panel:
        return cls(kind=KIND_METRIC, metric_id=metric_id, title=title,
                   visual=visual, period=period, note=note)

    @classmethod
    def chart(cls, metric_id: str, *, dimension: str, title: str = "",
              visual: str = "bar", period: str = "", note: str = "",
              aggregate: str = "metric", sort: str = "value",
              direction: str = "desc", limit: int = 20, compare: str = "",
              filters: dict[str, Any] | None = None) -> Panel:
        """A chart tile. Its configuration lives in `params`.

        In `params` rather than in named fields on `Panel`, because every
        stored lens in the database was written against the fields that are
        already there, and a chart's settings are the one part of a tile that
        varies by what is being drawn.
        """
        return cls(kind=KIND_CHART, metric_id=metric_id, title=title,
                   visual=visual, period=period, note=note,
                   filters=dict(filters or {}),
                   params={"dimension": dimension, "aggregate": aggregate,
                           "sort": sort, "direction": direction,
                           "limit": int(limit), "compare": compare})


def validate(panels: list[Panel], *, user_id: int | None = None) -> None:
    """Refuse a definition the platform cannot honestly render.

    `user_id` is who the lens is being written by, and it matters for one
    reason: a metric somebody built a minute ago is theirs and not yet
    shared, so resolving it without them says it does not exist — and the
    refusal read "'user.1.watchlist_exposure' is not a metric in the
    catalogue", which is both alarming and wrong. Nobody could put a metric
    they had just built onto a lens.
    """
    from backend.engine.registry import get_registry

    if not panels:
        raise InvalidLens("A lens needs at least one panel.")

    analyses = [p for p in panels
                if p.kind not in (KIND_METRIC, KIND_CHART)]
    tiles = [p for p in panels if p.kind == KIND_METRIC]
    charts = [p for p in panels if p.kind == KIND_CHART]
    if len(analyses) > MAX_PANELS:
        raise InvalidLens(
            f"A lens may hold at most {MAX_PANELS} analysis panels. "
            "Beyond that nobody reads it, they scroll past it."
        )
    if len(tiles) > MAX_TILES:
        raise InvalidLens(
            f"A lens may hold at most {MAX_TILES} metric tiles. "
            "Beyond that it stops being a view and becomes a list."
        )
    if len(charts) > MAX_CHARTS:
        raise InvalidLens(
            f"A lens may hold at most {MAX_CHARTS} charts. Each one is a "
            "grouped scan of the lake, and past this the page takes longer "
            "to draw than anybody waits."
        )

    registry = get_registry()
    known = {c.id: c for c in registry.contracts()}
    for panel in panels:
        if panel.kind not in KINDS:
            raise InvalidLens(
                f"'{panel.kind}' is not a kind of panel. "
                f"Available: {', '.join(KINDS)}.")
        if panel.kind == KIND_METRIC:
            _validate_metric_panel(panel, user_id=user_id)
            continue
        if panel.kind == KIND_CHART:
            _validate_chart_panel(panel, user_id=user_id)
            continue
        contract = known.get(panel.analysis_id)
        if contract is None:
            raise InvalidLens(
                f"'{panel.analysis_id}' is not a registered analysis. A lens can "
                "only show analyses the Engine Registry knows about."
            )
        if panel.visual not in VISUALS:
            raise InvalidLens(
                f"'{panel.visual}' is not a way a panel may be drawn. "
                f"Available: {', '.join(VISUALS)}."
            )
        declared = {p.name for p in contract.parameters}
        unknown = set(panel.params) - declared
        if unknown:
            raise InvalidLens(
                f"{panel.analysis_id} has no parameter "
                f"{', '.join(sorted(unknown))}. It accepts: "
                f"{', '.join(sorted(declared)) or 'no parameters'}."
            )


def _validate_metric_panel(panel: Panel, *, user_id: int | None = None
                           ) -> None:
    """Refuse a metric tile that cannot honestly be drawn as asked.

    Two separate checks, and the second is the interesting one. A metric that
    does not exist is an obvious refusal. A metric drawn as something it has
    not declared itself drawable as is the quiet failure: a single ratio
    rendered as a bar chart of one bar, or a distribution flattened to a KPI,
    both of which look like a working tile and mislead.
    """
    from backend.metrics import service as metrics

    if not panel.metric_id:
        raise InvalidLens("A metric panel has to name a metric.")

    absent = metrics.unavailable(panel.metric_id)
    if absent is not None:
        raise InvalidLens(
            f"{absent.name} cannot be calculated in this deployment. "
            f"{absent.because}")

    try:
        metric = metrics.resolve(panel.metric_id, user_id=user_id)
    except metrics.MetricNotFound as e:
        raise InvalidLens(
            f"'{panel.metric_id}' is not a metric in the catalogue. A lens can "
            "only show metrics CreditProbe governs or somebody has built."
        ) from e

    if panel.visual not in VISUALS:
        raise InvalidLens(
            f"'{panel.visual}' is not a way a panel may be drawn. "
            f"Available: {', '.join(VISUALS)}.")
    if panel.visual != "auto" and panel.visual not in metric.visuals:
        # Only what this renderer can actually draw. A metric may declare a
        # visual from the catalogue's wider vocabulary — the three IFRS 9
        # stage shares declare `stacked_bar`, which is an honest thing to say
        # about them — and offering it back as an alternative would send
        # somebody to try a tile the lens has no renderer for.
        here = [v for v in metric.visuals if v in VISUALS]
        elsewhere = [v for v in metric.visuals if v not in VISUALS]
        also = (f" It also declares {', '.join(elsewhere)}, which no lens "
                "renderer draws yet." if elsewhere else "")
        raise InvalidLens(
            f"{metric.name} should not be drawn as a {panel.visual}. On a "
            f"lens it can honestly be shown as: "
            f"{', '.join(here) or 'nothing this lens can draw'}.{also}")


def _validate_chart_panel(panel: Panel, *, user_id: int | None = None
                          ) -> None:
    """Refuse a chart the platform cannot honestly draw.

    Every check here has an equivalent in the builder's own pickers, and it is
    repeated because a lens can be submitted by anything that can reach the
    API. The interesting one is the chart type: whether a line is honest
    depends on whether the dimension has an order, so a chart that was valid
    over `observation_month` is not automatically valid over `product`.
    """
    from backend.metrics import service as metrics

    if not panel.metric_id:
        raise InvalidLens("A chart has to name a metric.")

    dimension = str(panel.params.get("dimension") or "")
    if not dimension:
        raise InvalidLens(
            f"The chart of {panel.metric_id} does not say which dimension to "
            "break it out by. A chart without one is a single figure.")

    absent = metrics.unavailable(panel.metric_id)
    if absent is not None:
        raise InvalidLens(
            f"{absent.name} cannot be calculated in this deployment. "
            f"{absent.because}")
    try:
        metric = metrics.resolve(panel.metric_id, user_id=user_id)
    except metrics.MetricNotFound as e:
        raise InvalidLens(
            f"'{panel.metric_id}' is not a metric in the catalogue. A chart "
            "can only draw metrics CreditProbe governs or somebody has built."
        ) from e

    offerable = {d["name"]: d for d in metrics.dimension_fields(metric)}
    chosen = offerable.get(dimension)
    if chosen is None:
        raise InvalidLens(
            f"'{dimension}' is not a dimension {metric.name} can be broken "
            f"out by. Available: "
            f"{', '.join(sorted(offerable)) or 'none on this dataset'}.")

    available, refused = metrics.chart_types_for(metric, chosen)
    if panel.visual not in available:
        because = next((r["because"] for r in refused
                        if r["name"] == panel.visual), "")
        raise InvalidLens(
            because or (
                f"'{panel.visual}' is not a chart type. Available for "
                f"{metric.name} by {chosen['business_name']}: "
                f"{', '.join(available) or 'none'}."))

    for name, allowed in (("aggregate", metrics.AGGREGATIONS),
                          ("sort", metrics.SORTS),
                          ("direction", metrics.DIRECTIONS),
                          ("compare", metrics.COMPARISONS)):
        value = str(panel.params.get(name) or ("" if name == "compare" else ""))
        if not value and name != "compare":
            continue
        if value not in allowed:
            raise InvalidLens(
                f"'{value}' is not a {name} a chart may use. "
                f"Available: {', '.join(k or 'none' for k in allowed)}.")

    if str(panel.params.get("aggregate") or "metric") == "average":
        # Refused here as well as in the service, so a lens cannot be stored
        # holding a chart that will only fail when somebody opens it.
        if not metrics.may_average(metric):
            raise InvalidLens(
                f"{metric.name} is not a single total, so an average of it "
                "per row is not a number that means anything. Use the "
                "metric's own definition, or count the rows.")


# ------------------------------------------------------------------- shape


@dataclass
class LensView:
    id: int
    slug: str
    name: str
    description: str
    audience: str
    panels: list[dict[str, Any]]
    #: Optional grouping of panels into named sections, each holding the
    #: indices of the panels it contains. A lens with no sections is one
    #: unbroken run of tiles, which is what every lens was before this.
    sections: list[dict[str, Any]]
    #: What this lens deliberately does NOT show, and why. A view that quietly
    #: omits the metric a reader came for teaches them not to trust it; one
    #: that says "retail IFRS 9 staging is not available in this deployment,
    #: because there is no retail impairment dataset" does the opposite.
    notes: list[dict[str, Any]]
    #: What the lens is FOR: purpose, audience, portfolio, the governed data
    #: domains it reads, the period it opens on and what it compares against.
    #: Filled by the creation flow before any metric is chosen, because a lens
    #: whose scope is decided after its tiles is a lens whose tiles decided
    #: its scope.
    scope: dict[str, Any]
    #: §17. Why the Lens is laid out this way: the monitoring objective, why
    #: each domain was chosen, why these comparisons, and the risk questions
    #: each element answers. Empty on a Lens built tile by tile, which is
    #: honest — nobody wrote a rationale for it.
    design: dict[str, Any]
    status: str
    version: int
    origin: str
    project_id: int | None
    revisions: list[dict[str, Any]] = field(default_factory=list)
    created_at: str | None = None
    updated_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "slug": self.slug,
            "name": self.name,
            "description": self.description,
            "audience": self.audience,
            "panels": self.panels,
            "sections": self.sections,
            "notes": self.notes,
            "scope": self.scope,
            "design": self.design,
            "status": self.status,
            "version": self.version,
            "origin": self.origin,
            "project_id": self.project_id,
            "revisions": self.revisions,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


def _view(session: Any, row: Any, *, with_revisions: bool = False) -> LensView:
    from sqlalchemy import select

    from backend.models.platform import LensRevision

    revisions: list[dict[str, Any]] = []
    if with_revisions:
        rows = session.execute(
            select(LensRevision)
            .where(LensRevision.lens_id == row.id)
            .order_by(LensRevision.version.desc())
        ).scalars().all()
        revisions = [{
            "version": r.version,
            "request": r.request,
            "change_summary": r.change_summary,
            "panel_count": len((r.definition or {}).get("panels") or []),
            "created_at": _iso(r.created_at),
        } for r in rows]

    definition = dict(row.definition or {})
    return LensView(
        id=row.id,
        slug=row.slug,
        name=row.name,
        description=row.description,
        audience=row.audience,
        panels=list(definition.get("panels") or []),
        sections=list(definition.get("sections") or []),
        notes=list(definition.get("notes") or []),
        scope=default_scope(definition.get("scope")),
        design=validate_design(definition.get("design")),
        status=row.status,
        version=row.version,
        origin=row.origin,
        project_id=row.project_id,
        revisions=revisions,
        created_at=_iso(row.created_at),
        updated_at=_iso(row.updated_at),
    )


#: What a lens says about itself before it says anything about the book.
#: §8 asks the creation flow to settle these before a single metric is
#: chosen, and they are stored in the definition JSON rather than in columns
#: of their own so that a lens written before they existed reads back with
#: sensible blanks rather than failing to load.
SCOPE_FIELDS = ("purpose", "audience", "portfolio", "domains",
                "default_period", "comparison_period", "visibility")

#: Who may open a lens. `private` is the owner alone; `shared` is anyone who
#: can reach the workspace. This is the lens's own declaration and is not a
#: permission on the data underneath it — a shared lens still shows each
#: reader only the metrics their datasets allow, which is enforced where the
#: metric is resolved rather than here.
VISIBILITIES = ("private", "shared")

#: Comparisons a lens may open with, mirrored from the chart vocabulary so a
#: lens and a chart cannot mean different things by "the previous period".
LENS_COMPARISONS = ("", "previous_period", "same_period_last_year")


def default_scope(stored: Any = None) -> dict[str, Any]:
    """A lens's scope, with every field present whether it was set or not.

    A screen that has to test each key before reading it grows a different
    default in each place that reads one, and the lens header and the lens
    editor then disagree about what "no default period" means.
    """
    raw = dict(stored or {})
    scope: dict[str, Any] = {
        "purpose": str(raw.get("purpose") or ""),
        "audience": str(raw.get("audience") or ""),
        "portfolio": str(raw.get("portfolio") or ""),
        "domains": [str(d) for d in (raw.get("domains") or []) if str(d)],
        "default_period": str(raw.get("default_period") or ""),
        "comparison_period": str(raw.get("comparison_period") or ""),
        "visibility": str(raw.get("visibility") or "shared"),
    }
    if scope["visibility"] not in VISIBILITIES:
        scope["visibility"] = "shared"
    if scope["comparison_period"] not in LENS_COMPARISONS:
        scope["comparison_period"] = ""
    return scope


def validate_scope(scope: dict[str, Any] | None) -> dict[str, Any]:
    """Refuse a scope the platform cannot honour, and say which field."""
    if scope is None:
        return {}
    unknown = set(scope) - set(SCOPE_FIELDS)
    if unknown:
        raise InvalidLens(
            f"A lens has no {', '.join(sorted(unknown))}. It carries: "
            f"{', '.join(SCOPE_FIELDS)}.")
    visibility = str(scope.get("visibility") or "shared")
    if visibility not in VISIBILITIES:
        raise InvalidLens(
            f"'{visibility}' is not a visibility a lens may have. "
            f"Available: {', '.join(VISIBILITIES)}.")
    comparison = str(scope.get("comparison_period") or "")
    if comparison not in LENS_COMPARISONS:
        raise InvalidLens(
            f"'{comparison}' is not a comparison a lens may open with. "
            f"Available: {', '.join(c or 'none' for c in LENS_COMPARISONS)}.")
    return default_scope(scope)


def _definition(panels: list[Panel],
                sections: list[dict[str, Any]] | None,
                notes: list[dict[str, Any]] | None,
                scope: dict[str, Any] | None = None,
                design: dict[str, Any] | None = None) -> dict[str, Any]:
    definition: dict[str, Any] = {"panels": [p.to_dict() for p in panels]}
    if sections:
        definition["sections"] = [dict(s) for s in sections]
    if notes:
        definition["notes"] = [dict(n) for n in notes]
    if scope:
        definition["scope"] = dict(scope)
    if design:
        definition["design"] = validate_design(design)
    return definition


#: §17. Why this Lens looks the way it does. Written when it is designed and
#: kept, because "why is rating migration on the CRO screen and not
#: concentration?" is asked six months later by somebody who was not there.
#:
#: It was previously shown on the proposal screen and then thrown away when
#: the Lens was created, so the reasoning survived exactly as long as the
#: browser tab did.
DESIGN_FIELDS = ("objective", "rationale", "risk_questions",
                 "why_these_domains", "why_these_comparisons")

#: Long enough for a paragraph per field and no longer. §17: "Do not generate
#: a giant essay. Make it useful to a senior risk user."
MAX_DESIGN_TEXT = 2000
MAX_RISK_QUESTIONS = 8


def validate_design(design: dict[str, Any] | None) -> dict[str, Any]:
    """The design rationale, bounded and with nothing else in it."""
    design = dict(design or {})
    out: dict[str, Any] = {}
    for field_name in DESIGN_FIELDS:
        value = design.get(field_name)
        if field_name == "risk_questions":
            out[field_name] = [str(q).strip()[:300]
                               for q in (value or [])
                               if str(q).strip()][:MAX_RISK_QUESTIONS]
            continue
        out[field_name] = str(value or "").strip()[:MAX_DESIGN_TEXT]
    return out


# ------------------------------------------------------------------ writing


def create(*, name: str, panels: list[Panel], description: str = "",
           audience: str = "", origin: str = "manual",
           project_id: int | None = None, request: str = "",
           user_id: int | None = None, slug: str = "",
           sections: list[dict[str, Any]] | None = None,
           notes: list[dict[str, Any]] | None = None,
           scope: dict[str, Any] | None = None,
           design: dict[str, Any] | None = None) -> LensView:
    """Store a new lens.

    `slug` is normally derived from the name. A caller installing a lens the
    platform ships passes it explicitly, because that slug is the lens's
    address — it is what a link, a seeder and a test all name it by — and a
    slug derived from a name is not stable enough to be an address.
    """
    _require_db()
    validate(panels, user_id=user_id)
    scope = validate_scope(scope)

    from backend.db.engine import get_session
    from backend.models.platform import Lens, LensRevision

    definition = _definition(panels, sections, notes, scope, design)
    with get_session() as session:
        slug = slugify(slug) if slug else slugify(name)
        existing = {s for (s,) in session.query(Lens.slug).all()}
        if slug in existing:
            n = 2
            while f"{slug}-{n}" in existing:
                n += 1
            slug = f"{slug}-{n}"

        row = Lens(
            slug=slug, name=name[:200], description=description,
            audience=audience[:120], definition=definition,
            status=STATUS_DRAFT, version=1, origin=origin,
            project_id=project_id, owner_id=user_id,
        )
        session.add(row)
        session.flush()
        session.add(LensRevision(
            lens_id=row.id, version=1, definition=definition, request=request,
            change_summary=f"Created with {len(panels)} "
                           f"{'panel' if len(panels) == 1 else 'panels'}.",
            created_by=user_id,
        ))
        session.commit()
        return _view(session, row, with_revisions=True)


def revise(lens_id: int, panels: list[Panel], *, request: str = "",
           change_summary: str = "", user_id: int | None = None,
           sections: list[dict[str, Any]] | None = None,
           notes: list[dict[str, Any]] | None = None,
           scope: dict[str, Any] | None = None,
           design: dict[str, Any] | None = None,
           name: str = "", description: str = "",
           audience: str = "") -> LensView:
    """Store a new revision. The previous one is kept, so it can be put back.

    `scope` left as None keeps whatever the lens already declares. A caller
    that meant to clear it passes the fields explicitly — a revision that
    silently dropped a lens's purpose and default period because it was only
    moving a tile would lose them on the first edit.

    `name`, `description` and `audience` live in columns rather than in the
    definition, and an empty one here means "leave it". They are settable
    because reinstalling a shipped lens has to be able to change them:
    without this, `install(replace=True)` rewrote the tiles and left the old
    description above them, so a lens that had grown a stage-migration band
    still described itself as the lens it was before.
    """
    _require_db()
    validate(panels, user_id=user_id)
    current = get(lens_id)
    kept = current.scope if scope is None else validate_scope(scope)
    # §17. The design rationale travels forward unless it is being replaced.
    # A revision that dropped it would lose the reasoning the first time
    # somebody added a tile, which is exactly when it starts being worth
    # having.
    kept_design = current.design if design is None else validate_design(design)

    from backend.db.engine import get_session
    from backend.models.platform import Lens, LensRevision

    definition = _definition(panels, sections, notes, kept, kept_design)
    with get_session() as session:
        row = session.get(Lens, lens_id)
        if row is None:
            raise LensNotFound(f"Lens {lens_id} does not exist.")
        version = row.version + 1
        row.definition = definition
        row.version = version
        if name:
            row.name = name[:200]
        if description:
            row.description = description
        if audience:
            row.audience = audience[:120]
        session.add(LensRevision(
            lens_id=lens_id, version=version, definition=definition,
            request=request, change_summary=change_summary,
            created_by=user_id,
        ))
        session.commit()
        return _view(session, row, with_revisions=True)


def restore(lens_id: int, version: int, *, user_id: int | None = None) -> LensView:
    """Put back an earlier revision — as a NEW revision, not by rewinding.

    Rewinding would lose the history of what was tried. Restoring forward keeps
    every step on the record, which is the difference between a version history
    and an undo button.
    """
    _require_db()
    from sqlalchemy import select

    from backend.db.engine import get_session
    from backend.models.platform import LensRevision

    with get_session() as session:
        wanted = session.execute(
            select(LensRevision).where(
                LensRevision.lens_id == lens_id, LensRevision.version == version
            )
        ).scalars().first()
        if wanted is None:
            raise LensNotFound(f"Lens {lens_id} has no version {version}.")
        stored = dict(wanted.definition or {})
        panels = [Panel.from_dict(p) for p in stored.get("panels") or []]
        sections = list(stored.get("sections") or [])
        notes = list(stored.get("notes") or [])
        # The scope travels with the version being put back. A restore that
        # kept the CURRENT purpose and default period would put back the
        # tiles of one lens under the description of another, and the
        # revision history would say it had restored something it had not.
        scope = default_scope(stored.get("scope"))
        design = validate_design(stored.get("design"))

    return revise(
        lens_id, panels, request=f"Restore version {version}",
        change_summary=f"Restored the definition from version {version}.",
        user_id=user_id, sections=sections, notes=notes, scope=scope,
        design=design,
    )


def _identity(panel: Panel) -> tuple[str, str, str]:
    """What makes a panel the same panel across a revision.

    The dimension is part of a chart's identity. Without it, "exposure by
    sector" and "exposure by segment" were the same panel — they name one
    metric — so a revision put both in whichever band the second one was
    found in, and a lens that had its concentration charts in one band and
    its trend in another came back with them merged. No shipped lens carried
    two charts of one metric until now, which is why this held.
    """
    if panel.kind == KIND_CHART:
        return (panel.kind, panel.metric_id,
                str((panel.params or {}).get("dimension") or ""))
    return (panel.kind, panel.metric_id or panel.analysis_id, "")


def resection(old: list[Panel], sections: list[dict[str, Any]],
              new: list[Panel], *,
              added_title: str = "Added by request") -> list[dict[str, Any]]:
    """Carry a lens's sections across a change to its panels.

    Sections hold panel INDICES, so a revision that removes a tile silently
    shifts every index after it and a lens that had four clean bands comes
    back scrambled. This remaps by panel identity instead: a panel that
    survives keeps its band, a panel that has gone leaves it, and anything new
    lands in a final section of its own rather than being appended to a band it
    has nothing to do with.

    An unsectioned lens stays unsectioned.
    """
    if not sections:
        return []

    # A queue of bands per identity, not one band, because a lens is allowed
    # to show one metric twice — the same figure under two titles, in two
    # sections. Matching by identity alone put the second copy in the first
    # copy's band and left the other band a tile short. Each surviving panel
    # claims the earliest band that still has an unclaimed copy of it.
    where: dict[tuple[str, str, str], list[int]] = {}
    for number, section in enumerate(sections):
        for index in section.get("panels") or []:
            if 0 <= int(index) < len(old):
                where.setdefault(_identity(old[int(index)]), []).append(number)

    grouped: dict[int, list[int]] = {n: [] for n in range(len(sections))}
    fresh: list[int] = []
    for index, panel in enumerate(new):
        queue = where.get(_identity(panel)) or []
        if not queue:
            fresh.append(index)
        else:
            grouped[queue.pop(0)].append(index)

    out: list[dict[str, Any]] = []
    for number, section in enumerate(sections):
        if not grouped[number]:
            continue  # every panel in this band has gone
        out.append({**section, "panels": grouped[number]})
    if fresh:
        out.append({"title": added_title, "subtitle": "", "panels": fresh})
    return out


def set_status(lens_id: int, status: str) -> LensView:
    if status not in STATUSES:
        raise InvalidLens(
            f"'{status}' is not a lens status. Available: {', '.join(STATUSES)}."
        )
    _require_db()
    from backend.db.engine import get_session
    from backend.models.platform import Lens

    with get_session() as session:
        row = session.get(Lens, lens_id)
        if row is None:
            raise LensNotFound(f"Lens {lens_id} does not exist.")
        row.status = status
        session.commit()
        return _view(session, row)


def delete(lens_id: int) -> None:
    _require_db()
    from backend.db.engine import get_session
    from backend.models.platform import Lens

    with get_session() as session:
        row = session.get(Lens, lens_id)
        if row is None:
            raise LensNotFound(f"Lens {lens_id} does not exist.")
        session.delete(row)
        session.commit()


# ------------------------------------------------------------------ reading


def listing(*, status: str | None = None) -> list[dict[str, Any]]:
    if not settings.has_database:
        return []
    from sqlalchemy import select

    from backend.db.engine import get_session
    from backend.models.platform import Lens

    with get_session() as session:
        query = select(Lens).order_by(Lens.updated_at.desc())
        if status:
            query = query.where(Lens.status == status)
        else:
            query = query.where(Lens.status != STATUS_ARCHIVED)
        return [_view(session, row).to_dict()
                for row in session.execute(query).scalars().all()]


def get(lens_id: int) -> LensView:
    _require_db()
    from backend.db.engine import get_session
    from backend.models.platform import Lens

    with get_session() as session:
        row = session.get(Lens, lens_id)
        if row is None:
            raise LensNotFound(f"Lens {lens_id} does not exist.")
        return _view(session, row, with_revisions=True)


def by_slug(slug: str) -> LensView:
    _require_db()
    from sqlalchemy import select

    from backend.db.engine import get_session
    from backend.models.platform import Lens

    with get_session() as session:
        row = session.execute(
            select(Lens).where(Lens.slug == slug)
        ).scalars().first()
        if row is None:
            raise LensNotFound(f"There is no lens called '{slug}'.")
        return _view(session, row, with_revisions=True)


# ----------------------------------------------- starting from a name


#: How many metrics a suggestion offers. Enough to make the lens worth
#: opening, few enough that the person is choosing rather than accepting.
SUGGESTED = 6


def _suggestion(metric: Any) -> dict[str, Any]:
    """One suggested metric, in the shape the typeahead already returns.

    The same shape deliberately: the creation screen shows suggestions and
    search results in one list, and two shapes would mean two row components
    that drift.
    """
    return {
        "metric_id": metric.metric_id,
        "name": metric.name,
        "domain": metric.domain,
        "unit": metric.unit,
        "definition": metric.definition,
        "origin": metric.origin,
        "status": metric.status,
        "governed": metric.governed,
        "datasets": list(metric.datasets),
        "formula": metric.formula_text or metric.formula.describe(),
        "decimals": metric.decimals,
        "aliases": list(metric.aliases),
        "matched": "shipped",
        "why": "on the lens CreditProbe ships for this",
    }


def suggest(name: str, *, user_id: int | None = None) -> dict[str, Any]:
    """What a lens called this is probably for, and what it probably shows.

    §8 asks the creation flow to open by asking what the lens should be
    called, then to fill in a short definition panel with suggested values
    the person controls.

    Nothing here is generated by a model. The name is matched against the
    Metric Catalogue with the same deterministic search the typeahead uses,
    and the scope is read off the metrics that matched: the domain most of
    them belong to, the portfolio most of them are about. That is a weaker
    kind of suggestion than a model would give and a much better one to
    build on — it returns the same answer on every machine, a test can
    assert it, and it cannot suggest a domain the person may not read,
    because a metric they may not read never reaches the ranking.

    Everything it returns is a default, not a decision. The screen puts each
    value in an editable field.
    """
    from backend.metrics import service as metrics

    text = (name or "").strip()
    if not text:
        raise InvalidLens("A lens needs a name before it can be suggested "
                          "anything.")

    hits = metrics.find(text, user_id=user_id,
                        limit=SUGGESTED * 3)["results"]

    #: A shipped lens whose name or audience the person has echoed is a
    #: better answer than anything assembled from search hits, because
    #: somebody wrote it on purpose.
    from backend.metrics import lenses as shipped

    lowered = text.lower()
    for spec in shipped.ALL:
        words = [w for w in spec.name.lower().split() if len(w) > 3]
        if words and all(w in lowered for w in words):
            return {
                "name": text,
                "scope": {**default_scope(spec.scope()),
                          "purpose": spec.purpose},
                "metrics": [
                    _suggestion(metrics.resolve(m, user_id=user_id))
                    for m in spec.metric_ids[:SUGGESTED]],
                "because": (
                    f"CreditProbe ships a {spec.name} lens. These are the "
                    "metrics it opens with; the shipped one has more, and is "
                    "in the library."),
                "shipped": spec.slug,
            }

    domains: dict[str, int] = {}
    portfolios: dict[str, int] = {}
    for hit in hits:
        domain = str(hit.get("domain") or "")
        if domain:
            domains[domain] = domains.get(domain, 0) + 1

    chosen = max(domains, key=lambda d: domains[d]) if domains else ""
    picked = [hit for hit in hits
              if not chosen or hit.get("domain") == chosen][:SUGGESTED]
    for hit in picked:
        try:
            portfolio = metrics.resolve(str(hit["metric_id"]),
                                        user_id=user_id).portfolio
        except metrics.MetricNotFound:  # pragma: no cover - raced deletion
            continue
        if portfolio:
            portfolios[portfolio] = portfolios.get(portfolio, 0) + 1

    return {
        "name": text,
        "scope": default_scope({
            "purpose": "",
            "portfolio": (max(portfolios, key=lambda p: portfolios[p])
                          if portfolios else ""),
            "domains": [chosen] if chosen else [],
        }),
        "metrics": picked,
        "because": (
            f"Matched against the metric catalogue. {len(picked)} "
            f"{'metric' if len(picked) == 1 else 'metrics'} in "
            f"{chosen or 'the catalogue'} answer to those words."
            if picked else
            "Nothing in the catalogue answers to those words yet. Name the "
            "lens anyway and search for metrics directly — the search matches "
            "the words people actually use, not just the canonical names."),
        "shipped": "",
    }


# ------------------------------------------------------- what it can show


def periods(lens_id: int) -> dict[str, Any]:
    """The periods this lens can honestly be shown for.

    Not "every period in the lake". A lens is a set of metrics over a set of
    datasets, and the only periods worth offering are the ones those datasets
    actually hold rows for — offering a quarter the staging dataset has never
    seen produces a screen of dashes and teaches the reader that the period
    picker is broken.

    A calendar is a dataset AND the scope read over it, not a dataset alone.
    That distinction is the one worth having. The Retail Credit Risk lens
    reads one dataset, and two of its bands do not have the same reach:
    thirty-one months of arrears, and twenty-five months of scorecard
    statistics, because the last six cohorts' performance windows have not
    closed and those metrics are scoped to matured rows. Grouping by dataset
    alone reported one calendar of thirty-one months and let a reader pick a
    month where five tiles correctly show a dash — with nothing on the picker
    to say that was coming.

    So the widest calendar is what the picker offers, and every narrower one
    is reported beside it with the note saying so. The tiles on a narrower
    calendar still explain themselves individually; this is what lets the
    reader see it before they click rather than after.
    """
    from backend.metrics import service as metrics

    #: (datasets, scope) -> the metrics that read it, for the note.
    wanted: dict[tuple[Any, ...], list[str]] = {}
    view = get(lens_id)
    for entry in view.panels:
        panel = Panel.from_dict(entry)
        if panel.kind not in (KIND_METRIC, KIND_CHART):
            continue
        try:
            metric = metrics.resolve(panel.metric_id)
        except metrics.MetricNotFound:
            continue
        if not metric.datasets:
            continue
        key = (tuple(metric.datasets), metric.scope)
        wanted.setdefault(key, [])
        if metric.name not in wanted[key]:
            wanted[key].append(metric.name)

    calendars: list[dict[str, Any]] = []
    for (datasets, scope), names in wanted.items():
        try:
            found = metrics.periods_with_rows(datasets, scope)
        except Exception:  # noqa: BLE001 - a dataset that has gone
            found = []
        if not found:
            continue
        calendars.append({
            "datasets": list(datasets),
            "periods": list(found),
            "latest": found[-1],
            "restricted_to": [c.describe() for c in scope],
            "metrics": sorted(names),
        })

    calendars.sort(key=lambda c: (-len(c["periods"]), c["datasets"]))
    #: The list a picker actually offers: the lens's widest calendar, because
    #: that is the one most of its tiles are on.
    offered = calendars[0]["periods"] if calendars else []

    narrower = [c for c in calendars[1:] if c["periods"] != offered]
    note = ""
    if narrower:
        shortest = min(narrower, key=lambda c: len(c["periods"]))
        named = shortest["metrics"]
        # The tiles by name, not the condition that restricts them. The
        # condition is `matured_flag = True`, which is a column and means
        # nothing to the person reading a dashboard; it stays on the response
        # as `restricted_to` for anyone who wants it, and each tile explains
        # itself in full on its own info panel.
        shown = ", ".join(named[:3]) + (
            f" and {len(named) - 3} more" if len(named) > 3 else "")
        note = (
            f"{len(named)} {'tile' if len(named) == 1 else 'tiles'} on this "
            f"lens reach only {shortest['periods'][0]} to "
            f"{shortest['periods'][-1]}, rather than {offered[0]} to "
            f"{offered[-1]}: {shown}. Outside that range they show no figure "
            "and say why, which is a fact about the population rather than a "
            "failure.")

    return {
        "lens_id": lens_id,
        "periods": offered,
        "latest": offered[-1] if offered else "",
        "default": view.scope.get("default_period") or "",
        "calendars": calendars,
        "note": note,
    }


def set_scope(lens_id: int, scope: dict[str, Any], *,
              user_id: int | None = None) -> LensView:
    """Change what a lens says it is for, keeping its tiles.

    A revision of its own, through the same path as every other change, so
    that "somebody repointed this lens at a different portfolio" is on the
    record next to "somebody added a tile".
    """
    before = get(lens_id)
    checked = validate_scope(scope)
    panels = [Panel.from_dict(p) for p in before.panels]
    return revise(
        lens_id, panels, request="Changed what this lens is for",
        change_summary=_scope_change(before.scope, checked),
        user_id=user_id, sections=before.sections, notes=before.notes,
        scope=checked)


def _scope_change(before: dict[str, Any], after: dict[str, Any]) -> str:
    """What changed about the lens's own description, in a sentence."""
    moved = [name for name in SCOPE_FIELDS
             if before.get(name) != after.get(name)]
    if not moved:
        return "Reviewed what this lens is for and changed nothing."
    readable = {"default_period": "the period it opens on",
                "comparison_period": "what it compares against",
                "domains": "the data domains it reads"}
    return ("Changed " + ", ".join(readable.get(m, m) for m in moved) + ".")


# ------------------------------------------------------------------ running


def render(lens_id: int, *, period: str | None = None,
           user_id: int | None = None) -> dict[str, Any]:
    """Run every panel now.

    Nothing is cached and nothing is stored: a Lens is what the book says today,
    not what it said when somebody built the view. Each panel goes through the
    ordinary engine runner, so each carries its own Trace.
    """
    view = get(lens_id)
    # A lens that declares a period opens on it. Explicit beats declared —
    # somebody who picked a quarter meant that quarter — and both beat the
    # per-metric default, which is what a lens with neither falls back to.
    period = period or (view.scope.get("default_period") or None)
    from backend.engine.runner import persist_run, run_analysis

    # §21. Every metric tile on the lens is computed together, so tiles that
    # share a dataset, a period and a scope are measured in one pass of it
    # rather than one pass each. The Corporate IFRS 9 lens went from
    # thirty-four scans of the staging dataset to one.
    #
    # Two properties this has to keep, and does:
    #
    # * The period each tile means is resolved once per (dataset, scope,
    #   rule), not once per tile. Two tiles that resolved separately could
    #   land on different periods, and stage exposures meant to sum to a
    #   total would stop summing to it.
    # * The arithmetic is unchanged. Each tile's value still comes out of the
    #   metric's own formula over its own terms, so a batched figure is the
    #   same number the tile would have shown on its own.
    #
    # Nothing survives this render. A cache that outlived it would keep
    # serving yesterday's latest period after a load, which is the one kind
    # of staleness a lens must not have.
    computed = _compute_tiles(view.panels, period=period, user_id=user_id)

    panels: list[dict[str, Any]] = []
    for entry in view.panels:
        panel = Panel.from_dict(entry)
        if panel.kind == KIND_METRIC:
            panels.append(_render_metric(panel, computed=computed))
            continue
        if panel.kind == KIND_CHART:
            panels.append(_render_chart(panel, period=period,
                                        user_id=user_id))
            continue
        try:
            outcome = run_analysis(
                panel.analysis_id, params=panel.params, period=period,
                filters=panel.filters, user_id=user_id,
            )
        except Exception as e:  # pragma: no cover - a genuinely broken analysis
            panels.append({**panel.to_dict(), "status": "failed",
                           "error": str(e), "result": None})
            continue

        panels.append({
            **panel.to_dict(),
            "status": outcome.status,
            "error": outcome.error,
            "certification": outcome.certification,
            "analysis_version": outcome.analysis_version,
            "analysis_run_id": persist_run(outcome, user_id=user_id),
            "duration_ms": outcome.duration_ms,
            "result": outcome.result.to_dict() if outcome.result else None,
        })

    # A gap in the book and a gap in the platform are different things, and a
    # reader told the wrong one wastes their afternoon. `unavailable` is the
    # first; `failed` is the second, and does not include it.
    unavailable = [p for p in panels if p["status"] == "unavailable"]
    failed = [p for p in panels
              if p["status"] not in ("succeeded", "unavailable")]
    note = ""
    if failed:
        note = (f"{len(failed)} of {len(panels)} panels could not be "
                "produced.")
    elif unavailable:
        note = (f"{len(unavailable)} of {len(panels)} panels have no data for "
                "this period. Each says why.")
    return {
        "lens": view.to_dict(),
        "period": period,
        "sections": view.sections,
        "notes": view.notes,
        "scope": view.scope,
        "panels": panels,
        "failed": len(failed),
        "unavailable": len(unavailable),
        "note": note,
    }


def _compute_tiles(entries: list[dict[str, Any]], *, period: str | None,
                   user_id: int | None) -> dict[str, Any]:
    """Every metric tile on the lens, computed together.

    Returns the answer for each metric id, in the shape one tile needs. A
    metric named by two tiles — the same figure under two titles, which a lens
    is allowed to do — is computed once and read twice.
    """
    from backend.metrics import service as metrics

    # A tile pinned to its own period is left out. It is asking a different
    # question from the rest of the lens, `_render_metric` reads it on its
    # own, and including it here would compute it twice.
    tiles = [Panel.from_dict(e) for e in entries]
    wanted = [p.metric_id for p in tiles
              if p.kind == KIND_METRIC and p.metric_id and not p.period]
    wanted = list(dict.fromkeys(wanted))
    if not wanted:
        return {}
    try:
        return metrics.values(wanted, period=period or "",
                              user_id=user_id)["metrics"]
    except Exception:  # pragma: no cover - a genuinely broken lake
        # Not fatal, and not silent. Each tile falls back to its own read
        # below and reports its own failure, which is a slow lens rather than
        # a blank one.
        logger.warning("batched tile read failed for this lens", exc_info=True)
        return {}


def _render_metric(panel: Panel, *, computed: dict[str, Any] | None = None,
                   period: str | None = None, user_id: int | None = None
                   ) -> dict[str, Any]:
    """One metric tile: the number, the working, and how it is defined.

    The §6 info panel travels with the tile rather than being fetched when
    somebody opens it. A tile that has to make a second request before it can
    explain itself is a tile whose explanation people stop opening.

    A metric with no data for the period is `unavailable`, not `failed`. The
    distinction matters on screen: one is a gap in the book, the other is a
    gap in the platform, and telling a reader the wrong one wastes their time.

    A tile pinned to its own period is not in the batch — it is asking a
    different question from the rest of the lens — so it reads on its own.
    """
    from backend.metrics import service as metrics

    outcome = None
    if not panel.period and computed:
        outcome = computed.get(panel.metric_id)
    if outcome is None:
        try:
            outcome = metrics.value(panel.metric_id,
                                    period=panel.period or (period or ""),
                                    user_id=user_id)
        except metrics.MetricNotFound as e:
            return {**panel.to_dict(), "status": "failed", "error": str(e),
                    "result": None, "metric": None}
        except Exception as e:  # pragma: no cover - a genuinely broken metric
            logger.warning("metric panel %s could not be produced",
                           panel.metric_id, exc_info=True)
            return {**panel.to_dict(), "status": "failed", "error": str(e),
                    "result": None, "metric": None}

    definition = outcome["metric"]
    if definition is None:
        return {**panel.to_dict(), "status": "failed",
                "error": outcome.get("error") or outcome["unavailable"],
                "result": None, "metric": None}

    return {
        **panel.to_dict(),
        "title": panel.title or definition["name"],
        "status": "succeeded" if outcome["available"] else "unavailable",
        "error": "",
        "unavailable": outcome["unavailable"],
        "value": outcome["value"],
        "unit": outcome["unit"],
        "decimals": outcome["decimals"],
        "higher_is_better": definition["higher_is_better"],
        "period_used": outcome["period"],
        # Everything §6 asks an info control to show, so the tile can explain
        # itself without another round trip.
        "metric": definition,
        "calculation": outcome["calculation"],
        "result": None,
    }


def _render_chart(panel: Panel, *, period: str | None,
                  user_id: int | None) -> dict[str, Any]:
    """One chart tile: the points, and everything needed to challenge them.

    The same three states as a metric tile — succeeded, unavailable, failed —
    because a reader should not have to learn a second vocabulary for a chart.
    A period with no rows is `unavailable`; a chart the platform cannot draw
    is `failed`; and both say which.
    """
    from backend.metrics import service as metrics

    params = dict(panel.params or {})
    try:
        drawn = metrics.series(
            panel.metric_id,
            dimension=str(params.get("dimension") or ""),
            period=panel.period or (period or ""),
            filters=dict(panel.filters or {}),
            aggregate=str(params.get("aggregate") or "metric"),
            sort=str(params.get("sort") or "value"),
            direction=str(params.get("direction") or "desc"),
            limit=int(params.get("limit") or 20),
            compare=str(params.get("compare") or ""),
            user_id=user_id)
    except (metrics.MetricNotFound, metrics.MetricRefused) as e:
        return {**panel.to_dict(), "status": "failed", "error": str(e),
                "result": None, "metric": None, "points": []}
    except Exception as e:  # pragma: no cover - a genuinely broken chart
        logger.warning("chart panel %s could not be produced",
                       panel.metric_id, exc_info=True)
        return {**panel.to_dict(), "status": "failed", "error": str(e),
                "result": None, "metric": None, "points": []}

    has_points = any(p["value"] is not None for p in drawn["points"])
    return {
        **panel.to_dict(),
        "title": panel.title or f"{drawn['series_label']} by "
                                f"{drawn['dimension_label']}",
        "status": "succeeded" if has_points else "unavailable",
        "error": "",
        "unavailable": drawn["unavailable"] or (
            "" if has_points else
            "No group in this period has a value for this metric."),
        "period_used": drawn["period"],
        "points": drawn["points"],
        "comparison": drawn["comparison"],
        "series_label": drawn["series_label"],
        "dimension": drawn["dimension"],
        "dimension_label": drawn["dimension_label"],
        # Whether the points are in time order. The tile draws every chart as
        # labelled bars — see `ChartTile` for why — so this is how a reader
        # knows a series is a progression rather than a comparison, and knows
        # which end is the oldest.
        "over_time": drawn["over_time"],
        "unit": drawn["unit"],
        "decimals": drawn["decimals"],
        "higher_is_better": drawn["higher_is_better"],
        "groups_found": drawn.get("groups_found", 0),
        "truncated": drawn.get("truncated", False),
        "chart_notes": drawn["notes"],
        # The info control, travelling with the tile as §6 asks: what the
        # metric means, and the exact query that produced these bars.
        "metric": drawn["metric"],
        "lineage": {"dataset": drawn.get("dataset", ""),
                    "sql": drawn.get("sql", ""),
                    "run_id": drawn.get("run_id", ""),
                    "filters": drawn.get("filters", {})},
        "result": None,
    }


# ------------------------------------------------------ building by asking


@dataclass
class Proposal:
    """What the platform proposes to do about a request."""

    panels: list[Panel]
    change_summary: str
    #: What the request asked for that the platform will not do, and why.
    refusals: list[str] = field(default_factory=list)
    matched: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "panels": [p.to_dict() for p in self.panels],
            "change_summary": self.change_summary,
            "refusals": self.refusals,
            "matched": self.matched,
        }


def propose(request: str, *, existing: list[Panel] | None = None,
            user_id: int | None = None) -> Proposal:
    """Turn a request into a change to a Lens definition.

    The matching is over the Engine Registry's own metadata — each analysis's
    name, its trigger questions and what it says it is for. That is deliberate:
    a request can only ever resolve to an analysis that exists, because the only
    thing being searched IS the list of analyses that exist.

    Where a request names something the registry has nothing for, that is
    reported as a refusal with the reason, rather than silently dropped or
    approximated with the nearest panel.
    """
    from backend.engine.registry import get_registry

    current = list(existing or [])
    text = (request or "").strip().lower()
    if not text:
        raise InvalidLens("Say what the lens should show.")

    contracts = get_registry().contracts()
    removing = bool(re.search(r"\b(remove|drop|delete|take off|without)\b", text))

    scored = [(_match_strength(text, c), c) for c in contracts]
    scored = [(score, c) for score, c in scored if score >= MATCH_THRESHOLD]
    scored.sort(key=lambda pair: -pair[0])

    # Only decisive matches. Everything within reach of the best is taken, so
    # "staging and coverage" picks up both; anything materially weaker is not,
    # because a weak match is how a lens ends up with a panel nobody asked for.
    chosen: list[Any] = []
    if scored:
        best = scored[0][0]
        chosen = [c for score, c in scored if score >= best - 0.5][:4]

    if not chosen:
        # No analysis matched. Before refusing, ask the Metric Catalogue: a
        # lens can hold metric tiles too, and "add ECL coverage" is a request
        # the platform CAN honour even though no analysis is called that.
        return _propose_metrics(request, text, current, removing,
                                user_id=user_id)

    if removing:
        ids = {c.id for c in chosen}
        remaining = [p for p in current if p.analysis_id not in ids]
        removed = len(current) - len(remaining)
        if removed == 0:
            return Proposal(
                panels=current, change_summary="",
                refusals=[
                    f"{chosen[0].name} is not on this lens, so there was nothing "
                    "to remove."
                ],
                matched=[c.id for c in chosen],
            )
        return Proposal(
            panels=remaining,
            change_summary=(
                f"Removed {removed} {'panel' if removed == 1 else 'panels'}: "
                + ", ".join(c.name for c in chosen if c.id in ids) + "."
            ),
            matched=[c.id for c in chosen],
        )

    present = {p.analysis_id for p in current}
    added = [c for c in chosen if c.id not in present]
    already = [c for c in chosen if c.id in present]
    if not added:
        return Proposal(
            panels=current, change_summary="",
            refusals=[
                (", ".join(c.name for c in already))
                + " is already on this lens, so nothing was added."
            ],
            matched=[c.id for c in chosen],
        )

    panels = current + [
        Panel(analysis_id=c.id, title=c.name, visual="auto",
              note=getattr(c, "when_to_use", "") or c.description)
        for c in added
    ]
    if len([p for p in panels
            if p.kind not in (KIND_METRIC, KIND_CHART)]) > MAX_PANELS:
        raise InvalidLens(
            f"That would take the lens to {len(panels)} panels, and the limit "
            f"is {MAX_PANELS}. Remove something first."
        )

    return Proposal(
        panels=panels,
        change_summary=(
            f"Added {len(added)} {'panel' if len(added) == 1 else 'panels'}: "
            + ", ".join(c.name for c in added) + "."
        ),
        matched=[c.id for c in chosen],
    )


#: How many metric tiles one request may add. A request that resolves to
#: eight metrics is a request nobody meant literally.
MAX_SUGGESTED_TILES = 4


def _propose_chart(request: str, current: list[Panel], *,
                   user_id: int | None = None) -> Proposal | None:
    """A chart for a sentence that asks for one, or None if it does not.

    None means "this was not a breakdown request" — the caller carries on and
    proposes tiles. A request that IS a breakdown but names a dimension the
    dataset cannot be cut by comes back from the interpreter with no charts,
    so it lands in the tile path and gets the metric it named. That is the
    right fallback: the metric exists, the cut does not.

    Replacing rather than duplicating is the point of the second half. "Show
    exposure by product instead" is an edit of the chart already there, and a
    lens that answered it with a second chart of the same metric would be a
    lens somebody has to tidy up by hand.
    """
    from backend.metrics import builder

    try:
        intent = builder.interpret(request, user_id=user_id)
    except Exception:  # noqa: BLE001 - an interpreter fault must not block asking
        return None
    if not intent.charts:
        return None

    panels = list(current)
    added: list[str] = []
    replaced: list[str] = []
    for idea in intent.charts[:MAX_SUGGESTED_TILES]:
        metric_id = str(idea["metric_id"])
        dimension = str(idea["dimension"])
        label = str(idea["dimension_label"])
        name = str(idea["metric_name"])
        same = [i for i, p in enumerate(panels)
                if p.kind == KIND_CHART and p.metric_id == metric_id]
        if any(panels[i].params.get("dimension") == dimension for i in same):
            continue
        panel = Panel.chart(
            metric_id, dimension=dimension, title=f"{name} by {label}",
            visual=str(idea["visual"]),
            sort="label" if idea["over_time"] else "value",
            direction="asc" if idea["over_time"] else "desc")
        if same:
            # One chart of one metric, cut the way it was last asked for.
            was = panels[same[0]].params.get("dimension", "")
            panels[same[0]] = panel
            replaced.append(f"{name} by {label} (was by {was})")
        else:
            panels.append(panel)
            added.append(f"{name} by {label}")

    if not added and not replaced:
        return Proposal(
            panels=current, change_summary="",
            refusals=[", ".join(f"{c['metric_name']} by {c['dimension_label']}"
                                for c in intent.charts)
                      + " is already on this lens, so nothing was added."],
            matched=[str(c["metric_id"]) for c in intent.charts])

    validate(panels, user_id=user_id)
    parts = []
    if added:
        parts.append("Added " + ", ".join(added))
    if replaced:
        parts.append("Changed " + ", ".join(replaced))
    return Proposal(
        panels=panels,
        change_summary="; ".join(parts) + ".",
        matched=[str(c["metric_id"]) for c in intent.charts])


def _propose_metrics(request: str, text: str, current: list[Panel],
                     removing: bool, *,
                     user_id: int | None = None) -> Proposal:
    """Turn a request into metric tiles, using the catalogue's own search.

    The same deliberate property the analysis matcher has: the only thing
    being searched IS the list of metrics that exist, so a request can never
    resolve to something the platform cannot calculate. Where it names
    something CreditProbe knows about and cannot compute here, that comes back
    as a refusal carrying the reason rather than as a tile that draws a dash.

    The AI does not invent a metric, write a formula, or set a figure. It
    selects from the catalogue, which is the whole of what it may do.
    """
    from backend.metrics import library as metric_library
    from backend.metrics import search as metric_search
    from backend.metrics import service as metrics

    # A breakdown is a chart, not a tile, and it is asked first.
    #
    # "Show exposure by sector" and "add exposure" name the same metric and
    # ask for different things: one is a number, the other is that number cut
    # by a field. It has to come before the search below, too — that search
    # requires every word to match something, and "by sector" is two words
    # about the shape of the answer rather than about which metric it is.
    if not removing:
        charted = _propose_chart(request, current, user_id=user_id)
        if charted is not None:
            return charted

    # The instruction words go first. "Add the roll rate" is a request about a
    # roll rate; leaving "add" and "the" in makes every word have to match
    # something, and nothing in the catalogue is called "add".
    wanted = " ".join(word for word in re.findall(r"[a-z0-9+]+", text)
                      if word not in STOP_WORDS) or text
    pool = metrics.catalogue(user_id=user_id)
    hits = metric_search.search(pool, wanted, limit=MAX_SUGGESTED_TILES)

    if not hits:
        absent = metric_search.unsupported_for(metric_library.UNSUPPORTED,
                                               wanted)
        if absent:
            return Proposal(
                panels=current, change_summary="",
                refusals=[
                    f"{entry.name} cannot be calculated in this deployment. "
                    f"{entry.because}" for entry in absent],
            )
        return Proposal(
            panels=current,
            change_summary="",
            refusals=[
                "Nothing in the analysis library or the metric catalogue "
                "matches that request, so the lens has not been changed. Try "
                "naming what you want to see — staging, coverage, arrears, "
                "concentration, migrations, ratings, the macro backdrop."
            ],
        )

    if removing:
        wanted = {hit.metric.metric_id for hit in hits}
        # Charts as well as tiles: "take default rate off this lens" means
        # the chart of it too, and leaving one behind is not what was asked.
        remaining = [p for p in current
                     if p.kind not in (KIND_METRIC, KIND_CHART)
                     or p.metric_id not in wanted]
        removed = len(current) - len(remaining)
        if removed == 0:
            return Proposal(
                panels=current, change_summary="",
                refusals=[f"{hits[0].metric.name} is not on this lens, so "
                          "there was nothing to remove."],
                matched=[hit.metric.metric_id for hit in hits],
            )
        return Proposal(
            panels=remaining,
            change_summary=(
                f"Removed {removed} {'tile' if removed == 1 else 'tiles'}: "
                + ", ".join(hit.metric.name for hit in hits
                            if hit.metric.metric_id in wanted) + "."),
            matched=[hit.metric.metric_id for hit in hits],
        )

    present = {p.metric_id for p in current if p.kind == KIND_METRIC}
    added = [hit.metric for hit in hits
             if hit.metric.metric_id not in present]
    if not added:
        return Proposal(
            panels=current, change_summary="",
            refusals=[
                ", ".join(hit.metric.name for hit in hits)
                + " is already on this lens, so nothing was added."],
            matched=[hit.metric.metric_id for hit in hits],
        )

    panels = current + [
        Panel.metric(metric.metric_id, title=metric.name,
                     visual=metric.visuals[0] if metric.visuals else "kpi",
                     note=metric.definition)
        for metric in added]
    try:
        validate(panels, user_id=user_id)
    except InvalidLens:
        raise

    return Proposal(
        panels=panels,
        change_summary=(
            f"Added {len(added)} {'tile' if len(added) == 1 else 'tiles'}: "
            + ", ".join(metric.name for metric in added) + "."),
        matched=[metric.metric_id for metric in added],
    )


#: Words too common to carry any signal about which analysis is wanted.
STOP_WORDS = frozenset("""
a an and are as at be by can could do does for from give had has have how i in
is it me my of on or our please show shows so that the their them then there
these they this to us want was we what when where which who why will with would
add remove drop delete take off without panel panels lens dashboard view see
also instead more less new put keep
""".split())

#: How many request words must land on an analysis's NAME before it counts as a
#: match. Two, because one is a coincidence: "borrower" appears in the name of an
#: analysis about deteriorating borrowers, and a request about a borrower's
#: astrological sign is not a request for that analysis.
MATCH_THRESHOLD = 2.0


def _words(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", text.lower())
            if w not in STOP_WORDS and len(w) > 2]


def _same(a: str, b: str) -> bool:
    """Whether two words are the same word.

    Prefix matching rather than a stemmer: "staging" and "stage", "triggers" and
    "trigger", "migrations" and "migration". A stemmer would be more correct and
    would also be one more thing nobody reading this can predict.
    """
    if a == b:
        return True
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    return len(shorter) >= 4 and longer.startswith(shorter)


def _match_strength(request: str, contract: Any) -> float:
    """How strongly a request names ONE analysis.

    Matched against the analysis's NAME and identifier, not its description. A
    description is a paragraph, and matching against paragraphs is how a request
    for one thing quietly selects four — the failure this function exists to
    prevent.

    The description and trigger questions contribute only a fraction, enough to
    order two analyses whose names match equally well and never enough to make a
    match on their own.
    """
    asked = _words(request)
    if not asked:
        return 0.0

    name_words = _words(f"{contract.name} {contract.id.replace('_', ' ')}")
    hits = sum(1 for word in asked if any(_same(word, n) for n in name_words))

    # The whole name appearing intact is decisive on its own.
    if contract.name.lower() in request:
        hits = max(hits, len(name_words))

    if hits < MATCH_THRESHOLD:
        return 0.0

    supporting = " ".join([
        contract.description,
        getattr(contract, "when_to_use", "") or "",
        " ".join(getattr(contract, "trigger_questions", []) or []),
    ]).lower()
    extra = sum(0.1 for word in asked if word in supporting)
    return float(hits) + min(extra, 0.9)


__all__ = [
    "MAX_PANELS",
    "STATUSES",
    "VISUALS",
    "InvalidLens",
    "LensNotFound",
    "LensView",
    "Panel",
    "Proposal",
    "StorageUnavailable",
    "by_slug",
    "create",
    "delete",
    "get",
    "listing",
    "propose",
    "render",
    "restore",
    "revise",
    "set_status",
    "slugify",
    "validate",
]
