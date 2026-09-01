"""
Reading a finished analysis back, so it can be written down.

Nothing here computes. Every figure in an exported workbook was produced when
the analysis ran and stored in `analysis_runs` and `trace_versions`; this module
finds it, names it, and hands it to a writer.

That constraint is the point of the module rather than a property of it. An
export that recomputed would produce a second answer under the first one's
filename, and the day the underlying data moved on, the workbook and the screen
would disagree with nobody able to say which was right. So there is no engine
call, no DuckDB query and no model call below this line — and the tests assert
that by counting the imports.

What a run persists
-------------------
A dynamic (composed) analysis stores a great deal: the presentation contract for
every column, the rows, the Analytical IR, the generated SQL and its parameters,
the datasets and joins, the reconciliation, the derived formulas, how the
question was read, and the fingerprint of the whole thing. A certified engine
analysis stores less — it has a registered methodology instead of a composed
plan — and the pack says so rather than leaving the sheet blank.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from backend.exports.contract import NotExportable, RunNotFound

logger = logging.getLogger(__name__)

#: Statuses that mean there is no result to export. A clarification is a
#: perfectly good outcome and a refusal is a governed one; neither is a
#: workbook, and offering one would be offering an empty file.
NOT_A_RESULT = {
    "needs_clarification": (
        "This question was answered with a clarification rather than a result, "
        "so there is nothing to export. Answer the clarification and the run it "
        "produces can be exported."
    ),
    "rejected": (
        "CreditProbe refused to run this plan, so no result was produced. The "
        "refusal and its reason are on the Trace."
    ),
    "unsupported": (
        "CreditProbe could not answer this from the governed data, so there is "
        "no result to export."
    ),
    "failed": (
        "This run did not complete, so there is no result to export."
    ),
}


@dataclass
class Source:
    """One governed dataset version the analysis actually read."""

    dataset: str = ""
    domain: str = ""
    family: str = ""
    business_name: str = ""
    origin: str = ""
    authority: str = ""
    published: str = ""
    period: str = ""
    version: str = ""
    grain: str = ""
    row_count: int | None = None
    field_count: int | None = None
    primary_key: str = ""
    sensitivity: str = ""
    owner: str = ""
    content_hash: str = ""
    rows_read: int | None = None
    columns_read: str = ""
    pushdown: str = ""


@dataclass
class Pack:
    """Everything one export needs, read once.

    Assembled from the persisted run rather than passed around as a dict, so a
    writer that wants the closing period asks for `pack.period` instead of
    guessing which of four keys carries it in this particular run's shape.
    """

    run_id: int
    question: str = ""
    title: str = ""
    status: str = ""
    created_at: str = ""
    duration_ms: int | None = None

    # ---- where it came from
    investigation_id: int | None = None
    investigation_title: str = ""
    project_id: int | None = None
    project_name: str = ""
    user_id: int | None = None

    # ---- the trace
    version: int = 1
    version_label: str = ""
    version_count: int = 1
    graph: dict[str, Any] = field(default_factory=dict)

    # ---- the answer
    narrative: dict[str, Any] = field(default_factory=dict)
    steps: list[dict[str, Any]] = field(default_factory=list)
    #: The step that answers the question. Everything the RESULTS sheet shows.
    primary: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] = field(default_factory=dict)
    rows: list[dict[str, Any]] = field(default_factory=list)
    columns: list[dict[str, Any]] = field(default_factory=list)
    values: dict[str, Any] = field(default_factory=dict)
    units: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    # ---- how it was produced
    certification: str = ""
    analysis_id: str = ""
    analysis_version: str = ""
    period: str = ""
    opening_period: str = ""
    closing_period: str = ""
    filters: dict[str, Any] = field(default_factory=dict)
    reading: dict[str, Any] = field(default_factory=dict)
    plan: dict[str, Any] = field(default_factory=dict)
    ir: dict[str, Any] = field(default_factory=dict)
    query: dict[str, Any] = field(default_factory=dict)
    formulas: list[dict[str, Any]] = field(default_factory=list)
    joins: list[dict[str, Any]] = field(default_factory=list)
    join_plan: dict[str, Any] = field(default_factory=dict)
    reconciliation: list[dict[str, Any]] = field(default_factory=list)
    sources: list[Source] = field(default_factory=list)
    plain_english: str = ""
    explanation: str = ""
    visual: dict[str, Any] = field(default_factory=dict)

    # ---- provenance
    fingerprint: dict[str, Any] = field(default_factory=dict)
    build_sha: str = ""
    app_version: str = ""
    model_provider: str = ""
    model_name: str = ""
    generated_at: str = ""
    generated_by: str = ""
    synthetic: bool = True

    # ---- what could not be included
    redactions: list[str] = field(default_factory=list)

    @property
    def is_dynamic(self) -> bool:
        return (self.certification or "").lower() == "dynamic"

    @property
    def plan_fingerprint(self) -> str:
        return str(self.fingerprint.get("plan") or "")

    @property
    def data_version(self) -> str:
        return str(self.fingerprint.get("data") or "")

    @property
    def period_label(self) -> str:
        """The period a reader would name this analysis by."""
        if self.opening_period and self.closing_period:
            return f"{self.opening_period} to {self.closing_period}"
        return self.closing_period or self.period or ""

    @property
    def answer(self) -> str:
        return str(
            self.narrative.get("direct_answer")
            or self.narrative.get("summary")
            or ""
        )

    def node(self, node_type: str) -> dict[str, Any]:
        """The first Trace node of a given type, or an empty dict.

        The Trace is the record of what happened, and several sheets are built
        from a single node in it — the invariants that were checked, the
        interpretation and what it was grounded in, the reconciliation ledger.
        Asking by type rather than by id keeps the writers out of the business
        of knowing how node ids are composed.
        """
        for node in self.graph.get("nodes") or []:
            if isinstance(node, dict) and node.get("type") == node_type:
                return node
        return {}

    def nodes(self, node_type: str) -> list[dict[str, Any]]:
        return [n for n in (self.graph.get("nodes") or [])
                if isinstance(n, dict) and n.get("type") == node_type]

    def visible_columns(self) -> list[dict[str, Any]]:
        """The columns in the order and shape the interface shows them.

        Hidden lineage columns are left out — an as-of stamp carried through an
        aggregate is a real column and not an answer, and §7 says the results
        workbook carries no hidden lineage columns unless asked.
        """
        declared = [c for c in self.columns if not c.get("hidden")]
        if declared:
            return declared
        # A certified engine analysis has no presentation contract; its rows are
        # the contract. Derive one so the sheet still has labels and units.
        keys = list(self.rows[0].keys()) if self.rows else []
        return [{"name": k, "label": _humanise(k), "unit": self.units.get(k, "")}
                for k in keys]


def _humanise(key: str) -> str:
    return str(key or "").replace("_", " ").strip().capitalize()


# --------------------------------------------------------------- gathering


def pack_for(run_id: int, *, version: int | None = None,
             user_id: int | None = None, user_name: str = "") -> Pack:
    """Everything about one analysis run, as it was recorded.

    Raises `NotExportable` where the run produced no result — a clarification,
    a refusal, a failure. Those are outcomes rather than errors, and the caller
    turns them into an explanation rather than a 500.
    """
    from backend.orchestration import store

    try:
        stored = store.load_version(run_id, version)
    except store.InvestigationNotFound as e:
        raise RunNotFound(str(e)) from e

    status = str(stored.get("status") or "")
    if status in NOT_A_RESULT:
        raise NotExportable(NOT_A_RESULT[status])

    steps = list(stored.get("steps") or [])
    primary = _primary_step(steps)
    if primary is None:
        raise NotExportable(
            "This run recorded no analytical step, so there is nothing to "
            "export. The Trace shows what happened."
        )
    result = dict(primary.get("result") or {})
    if not result:
        raise NotExportable(
            "This step produced no result, so there is nothing to export."
        )

    pack = Pack(
        run_id=run_id,
        question=str(stored.get("question") or ""),
        title=_title(primary, stored),
        status=status,
        created_at=str(stored.get("created_at") or ""),
        duration_ms=stored.get("duration_ms"),
        version=int(stored.get("version") or 1),
        version_label=str(stored.get("label") or ""),
        version_count=len(stored.get("available_versions") or []) or 1,
        graph=dict(stored.get("graph") or {}),
        narrative=dict(stored.get("narrative") or {}),
        steps=steps,
        primary=primary,
        result=result,
        rows=list(result.get("rows") or []),
        columns=list(result.get("columns") or []),
        values=dict(result.get("values") or {}),
        units=dict(result.get("units") or {}),
        warnings=list(result.get("warnings") or []),
        certification=str(primary.get("certification") or ""),
        analysis_id=str(primary.get("analysis_id") or ""),
        analysis_version=str(primary.get("analysis_version") or ""),
        period=str(primary.get("period") or ""),
        filters=dict(primary.get("filters") or {}),
        reading=dict(result.get("reading") or {}),
        plan=dict(stored.get("plan") or {}),
        ir=dict(result.get("plan") or {}),
        query=dict(result.get("query") or {}),
        formulas=list(result.get("formulas") or []),
        joins=list(result.get("joins") or []),
        join_plan=dict(result.get("join_plan") or {}),
        reconciliation=list(result.get("reconciliation") or []),
        plain_english=str(result.get("plain_english") or ""),
        explanation=str(result.get("explanation") or ""),
        visual=dict(result.get("visual") or {}),
        fingerprint=dict(result.get("fingerprint") or {}),
        model_provider=str(stored.get("model_provider") or ""),
        model_name=str(stored.get("model_name") or ""),
        generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
        generated_by=user_name or (f"user {user_id}" if user_id else "unknown"),
        user_id=user_id,
    )

    reading = pack.reading
    pack.opening_period = str(reading.get("opening_period") or "")
    pack.closing_period = str(
        reading.get("closing_period") or reading.get("period") or pack.period or ""
    )
    pack.sources = _sources(pack, result)
    pack.build_sha, pack.app_version = _build()
    _attach_origin(pack)
    return pack


#: Step titles the planner writes for a whole class of analyses rather than for
#: this one. Perfectly good as a heading above a table that already has its own
#: context; useless as the name of a file in a downloads folder, where
#: "aggregated_across_the_governed_book" describes every aggregate ever run.
_GENERIC_TITLES = {
    "aggregated across the governed book",
    "ranked from the governed book",
    "analysis",
    "result",
}


def _title(primary: dict[str, Any], stored: dict[str, Any]) -> str:
    """What to call this analysis, on a cover and in a filename.

    The plan's own one-line explanation first, because it names the measure,
    the breakdown and the period — which is exactly what distinguishes one
    download from the next in a folder of twelve. The step title is used where
    the planner wrote a specific one, and the question is the last resort.
    """
    explanation = str((primary.get("result") or {}).get("plan", {})
                      .get("meta", {}).get("explanation") or "").strip().rstrip(".")
    title = str(primary.get("title") or "").strip()
    if title and title.lower() not in _GENERIC_TITLES:
        return title
    if explanation:
        return explanation[:1].upper() + explanation[1:]
    return title or str(stored.get("intent") or "Analysis")


def _primary_step(steps: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The step that answers the question.

    The planner marks it, and that marking is followed rather than the order
    things happened to run in — the same rule the answer layout follows, so the
    workbook and the screen lead with the same table.
    """
    succeeded = [s for s in steps if s.get("status") == "succeeded" and s.get("result")]
    if not succeeded:
        return None
    for step in succeeded:
        if step.get("role") == "primary":
            return step
    return succeeded[0]


def _sources(pack: Pack, result: dict[str, Any]) -> list[Source]:
    """The governed datasets this run actually read.

    Taken from the run's own fingerprint, which recorded them at execution
    time, and enriched from the catalogue where the catalogue can still be
    reached. Enrichment is best-effort on purpose: a dataset that has since
    been archived must still appear in the pack, because it is what the
    analysis read.
    """
    named = [str(d) for d in (result.get("datasets") or []) if d]
    stamped = {
        str(entry.get("dataset")): entry
        for entry in (result.get("fingerprint") or {}).get("datasets") or []
        if isinstance(entry, dict)
    }
    for name in stamped:
        if name not in named:
            named.append(name)

    catalogue = _catalogue(named)
    out: list[Source] = []
    for name in named:
        stamp = stamped.get(name, {})
        known = catalogue.get(name, {})
        periods = stamp.get("periods") or []
        out.append(Source(
            dataset=name,
            domain=str(known.get("domain") or ""),
            family=str(known.get("family") or ""),
            business_name=str(known.get("business_name") or ""),
            origin=str(stamp.get("origin") or known.get("origin") or ""),
            authority=str(known.get("authority") or ""),
            published=str(known.get("lifecycle") or ""),
            period=", ".join(str(p) for p in periods),
            version=str(stamp.get("version") or ""),
            grain=str(known.get("grain") or ""),
            row_count=known.get("row_count"),
            field_count=known.get("field_count"),
            primary_key=", ".join(known.get("primary_keys") or []),
            sensitivity=str(known.get("sensitivity") or ""),
            owner=str(known.get("owner") or ""),
            content_hash=str(stamp.get("content_hash") or ""),
            rows_read=_rows_read(pack, name, result),
            columns_read=", ".join(sorted({
                str(c.get("name")) for c in pack.columns
                if c.get("origin") == name and c.get("name")
            })),
            pushdown=_pushdown(result),
        ))
    return out


def _rows_read(pack: Pack, dataset: str, result: dict[str, Any]) -> int | None:
    """How many rows were actually read from this dataset.

    Taken from the DATASET node the execution stamped, not from the step's own
    `input_row_count` — for a grouped result those are the fifteen output
    groups, and reporting fifteen as "rows read from a 16,346-row facility
    table" is the kind of number a reviewer would catch and stop trusting the
    rest of the pack for.
    """
    for node in pack.graph.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        if node.get("dataset") != dataset:
            continue
        for key in ("rows_out", "rows_in"):
            value = node.get(key)
            if isinstance(value, int):
                return value
    return None


def _pushdown(result: dict[str, Any]) -> str:
    """Whether filtering happened in the query or after it.

    A reviewer asking "did you read the whole table?" is asking about pushdown,
    and the generated SQL is where the answer is.
    """
    sql = str((result.get("query") or {}).get("sql") or "")
    if not sql:
        return ""
    return "filters pushed into the query" if " WHERE " in sql.upper() else "no filter pushdown"


def _catalogue(names: list[str]) -> dict[str, dict[str, Any]]:
    """What the Data Builder catalogue still knows about these datasets.

    Best-effort: an export must not fail because the catalogue is unreachable
    or because a dataset was archived after the analysis ran. What is missing
    is left blank, and the pack's LIMITATIONS sheet says the enrichment was
    unavailable rather than implying the fields were empty.
    """
    from backend.config import settings

    if not names or not settings.has_database:
        return {}
    try:
        from sqlalchemy import select

        from backend.db.engine import get_session
        from backend.models.platform import DatasetDefinition, FieldDefinition

        out: dict[str, dict[str, Any]] = {}
        with get_session() as session:
            rows = session.execute(
                select(DatasetDefinition).where(DatasetDefinition.name.in_(names))
            ).scalars().all()
            for row in rows:
                fields = session.execute(
                    select(FieldDefinition)
                    .where(FieldDefinition.dataset_id == row.id)
                ).scalars().all()
                out[row.name] = {
                    "domain": row.domain,
                    "business_name": row.business_name,
                    "grain": row.grain,
                    "primary_keys": list(row.primary_keys or []),
                    "owner": row.owner,
                    "sensitivity": row.sensitivity,
                    "lifecycle": row.lifecycle,
                    "origin": "demo" if row.is_synthetic else "client",
                    "authority": row.source_type,
                    "field_count": len(fields),
                    "version": row.version,
                }
        return out
    except Exception as e:  # noqa: BLE001 - never lose an export to the catalogue
        logger.info("Catalogue enrichment unavailable for export: %s", e)
        return {}


def _build() -> tuple[str, str]:
    try:
        from backend.build_info import build_info

        info = build_info()
        return str(getattr(info, "sha", "") or ""), str(getattr(info, "version", "") or "")
    except Exception as e:  # noqa: BLE001 - provenance must not lose an export
        logger.info("Build stamp unavailable for export: %s", e)
        return "", ""


def _attach_origin(pack: Pack) -> None:
    """Which investigation and project this run belongs to.

    Best-effort and read-only. A run whose investigation was deleted is still
    exportable; the pack simply cannot name where it came from.
    """
    from backend.config import settings

    if not settings.has_database:
        return
    try:
        from sqlalchemy import select

        from backend.db.engine import get_session
        from backend.models.platform import AnalysisRun, Investigation, Project

        with get_session() as session:
            run = session.get(AnalysisRun, pack.run_id)
            if run is None:
                return
            pack.investigation_id = run.investigation_id
            pack.project_id = run.project_id
            if run.investigation_id:
                thread = session.get(Investigation, run.investigation_id)
                if thread is not None:
                    pack.investigation_title = thread.title or ""
                    pack.project_id = pack.project_id or thread.project_id
            if pack.project_id:
                project = session.execute(
                    select(Project).where(Project.id == pack.project_id)
                ).scalars().first()
                if project is not None:
                    pack.project_name = project.name or ""
    except Exception as e:  # noqa: BLE001
        logger.info("Could not attach run origin for export: %s", e)
