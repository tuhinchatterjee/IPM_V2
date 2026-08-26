"""
The reference answer, computed independently of everything being tested.

Why a second implementation
---------------------------
A benchmark whose expected answer comes from the system under test measures
nothing. So the truth here is computed by a **separate, deliberately simple
path**: hand-written SQL over the Parquet layer, and direct reads of the
catalogue. It shares no code with the Analytical IR, the validator, the
compiler, the planner or the orchestrator. Where the two agree, they agree
because the figure is right, not because one asked the other.

It is also deliberately *dumber*. There is no join resolution, no grain
reconciliation and no concept vocabulary — every reference states its dataset,
its columns and its filters outright. That makes it slower and less general than
the runtime, and it makes it checkable by reading it, which is the property that
matters for a reference.

No model is involved. §AF of the brief is explicit that a language model may not
grade: an LLM judge would fail in exactly the ways the thing being judged fails,
and the correlation would look like agreement.

The isolation rule
------------------
Nothing under `backend/orchestration`, `backend/runtime`, `backend/engine` or
`backend/api` may import this package. `tests/validation/test_isolation.py`
enforces that by walking the import graph. The runner calls production; production
can never call the runner.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

#: Where the analytical layer lives. Read directly, with hive partitioning, so
#: the reference does not go through the Data Access Layer either.
LAKE = "data/analytics"

#: Bumped when a reference computation changes. Stamped onto every validation
#: run so a score can be marked stale rather than silently compared against one
#: earned under different rules.
BENCHMARK_VERSION = "1.0.0"


@dataclass
class Reference:
    """What the answer should be, and how that was worked out."""

    kind: str
    #: Named figures — totals, counts, shares. Compared with tolerance.
    values: dict[str, Any] = field(default_factory=dict)
    #: Identities the answer should contain, in order where order matters.
    ids: list[str] = field(default_factory=list)
    #: Full rows, for a table comparison.
    rows: list[dict[str, Any]] = field(default_factory=list)
    #: One sentence a person can read instead of the numbers.
    summary: str = ""
    #: The SQL or catalogue read that produced this, shown to an administrator.
    derivation: str = ""
    ordered: bool = False
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind, "values": dict(self.values),
            "ids": list(self.ids), "rows": list(self.rows),
            "summary": self.summary, "derivation": self.derivation,
            "ordered": self.ordered, "error": self.error,
        }


def _connect() -> Any:
    import duckdb

    return duckdb.connect()


def _source(dataset: str) -> str:
    return f"read_parquet('{LAKE}/{dataset}/**/*.parquet', hive_partitioning=1)"


def _where(period: str | None, filters: list[dict[str, Any]] | None) -> str:
    parts: list[str] = []
    if period:
        parts.append(f"period = '{period}'")
    for clause in filters or []:
        column = str(clause["column"])
        if "values" in clause:
            joined = ", ".join(f"'{v}'" for v in clause["values"])
            parts.append(f"CAST({column} AS VARCHAR) IN ({joined})")
        else:
            parts.append(f"CAST({column} AS VARCHAR) = '{clause['value']}'")
    return (" WHERE " + " AND ".join(parts)) if parts else ""


def _run(sql: str) -> list[dict[str, Any]]:
    with _connect() as con:
        cursor = con.execute(sql)
        columns = [d[0] for d in cursor.description]
        return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


# ------------------------------------------------------------ the references


def aggregate(*, dataset: str, measure: str, dimension: str,
              period: str, filters: list[dict[str, Any]] | None = None,
              top_n: int = 0, agg: str = "sum") -> Reference:
    """A grouped total — "total EAD by sector in the latest quarter"."""
    sql = (f"SELECT {dimension} AS grp, {agg}({measure}) AS value\n"
           f"FROM {_source(dataset)}{_where(period, filters)}\n"
           f"GROUP BY 1 ORDER BY 2 DESC"
           + (f" LIMIT {top_n}" if top_n else ""))
    try:
        rows = _run(sql)
    except Exception as e:  # noqa: BLE001
        return Reference(kind="aggregate", error=str(e), derivation=sql)

    total_sql = (f"SELECT {agg}({measure}) AS total, COUNT(DISTINCT {dimension}) "
                 f"AS groups FROM {_source(dataset)}{_where(period, filters)}")
    totals = _run(total_sql)[0] if rows else {"total": 0, "groups": 0}

    # With a cut, "the total" is the total of what is on screen. The whole
    # population is still reported, because the share of it is the point of
    # cutting — but calling the population total "the total" of a five-row
    # answer would fail a correct answer for describing itself accurately.
    shown = round(sum(_num(r["value"]) for r in rows), 4)
    # Adding up an average or a maximum across groups produces a number with no
    # meaning, so a non-sum reference asserts the groups and the largest of them
    # and stays quiet about a total nobody should quote.
    totals_matter = agg == "sum"
    return Reference(
        kind="aggregate",
        values={**({"total": shown if top_n else _num(totals.get("total")),
                    "population_total": _num(totals.get("total"))}
                   if totals_matter else {}),
                "groups": len(rows) if top_n else int(totals.get("groups") or 0),
                "row_count": len(rows),
                "top_value": _num(rows[0]["value"]) if rows else 0.0},
        ids=[str(r["grp"]) for r in rows],
        rows=[{"group": str(r["grp"]), "value": _num(r["value"])} for r in rows],
        # Order is only a fact where the values differ. A measure that ties
        # across groups — a worst-case days-past-due that several sectors reach —
        # has no single correct ordering, and asserting one would fail a correct
        # answer for breaking a tie differently.
        ordered=_strictly_ordered([_num(r["value"]) for r in rows]),
        summary=(f"{agg.upper()} of {measure} in {dataset} at {period}, grouped "
                 f"by {dimension}: {len(rows)} groups, "
                 f"{_fmt(totals.get('total'))} in total, largest is "
                 f"{rows[0]['grp'] if rows else '—'}."),
        derivation=sql + "\n\n" + total_sql,
    )


def ranking(*, dataset: str, measure: str, key: str, period: str,
            top_n: int, filters: list[dict[str, Any]] | None = None,
            agg: str = "sum", ascending: bool = False) -> Reference:
    """The N largest entities by a measure, at one period."""
    order = "ASC" if ascending else "DESC"
    sql = (f"SELECT {key} AS id, {agg}({measure}) AS value\n"
           f"FROM {_source(dataset)}{_where(period, filters)}\n"
           f"GROUP BY 1 ORDER BY 2 {order} LIMIT {top_n}")
    population_sql = (f"SELECT {agg}({measure}) AS total, COUNT(DISTINCT {key}) "
                      f"AS members FROM {_source(dataset)}"
                      f"{_where(period, filters)}")
    try:
        rows = _run(sql)
        population = _run(population_sql)[0]
    except Exception as e:  # noqa: BLE001
        return Reference(kind="ranking", error=str(e), derivation=sql)

    covered = sum(_num(r["value"]) for r in rows)
    total = _num(population.get("total"))
    return Reference(
        kind="ranking",
        values={"row_count": len(rows), "top_value": _num(rows[0]["value"]) if rows else 0.0,
                "covered": round(covered, 4), "population_total": total,
                "covered_pct": round(100 * covered / total, 4) if total else 0.0,
                "members": int(population.get("members") or 0)},
        ids=[str(r["id"]) for r in rows],
        rows=[{"id": str(r["id"]), "value": _num(r["value"])} for r in rows],
        ordered=True,
        summary=(f"The {top_n} largest {key} by {agg}({measure}) in {dataset} at "
                 f"{period}: {', '.join(str(r['id']) for r in rows[:5])}."),
        derivation=sql + "\n\n" + population_sql,
    )


def count_distinct(*, dataset: str, key: str, period: str,
                   dimension: str = "", top_n: int = 0,
                   filters: list[dict[str, Any]] | None = None) -> Reference:
    """How many distinct entities, in total or per group.

    `top_n` matters after a conversation has already cut the answer: replacing
    the measure on a five-sector view counts five sectors, and a reference that
    counted all fifteen would fail the correct answer.
    """
    if dimension:
        sql = (f"SELECT {dimension} AS grp, COUNT(DISTINCT {key}) AS value\n"
               f"FROM {_source(dataset)}{_where(period, filters)}\n"
               f"GROUP BY 1 ORDER BY 2 DESC"
               + (f" LIMIT {top_n}" if top_n else ""))
    else:
        sql = (f"SELECT COUNT(DISTINCT {key}) AS value\n"
               f"FROM {_source(dataset)}{_where(period, filters)}")
    total_sql = (f"SELECT COUNT(DISTINCT {key}) AS total FROM {_source(dataset)}"
                 f"{_where(period, filters)}")
    try:
        rows = _run(sql)
        total = _num(_run(total_sql)[0].get("total"))
    except Exception as e:  # noqa: BLE001
        return Reference(kind="count", error=str(e), derivation=sql)

    shown = round(sum(_num(r["value"]) for r in rows), 4) if dimension else total
    return Reference(
        kind="count",
        values={"total": shown if top_n else total,
                "population_total": total, "row_count": len(rows)},
        ids=[str(r["grp"]) for r in rows] if dimension else [],
        rows=([{"group": str(r["grp"]), "value": _num(r["value"])} for r in rows]
              if dimension else [{"value": total}]),
        ordered=bool(dimension),
        summary=(f"{int(total)} distinct {key} in {dataset} at {period}"
                 + (f", across {len(rows)} {dimension} values." if dimension
                    else ".")),
        derivation=sql,
    )


def movement_cohort(*, dataset: str, key: str, opening: str, closing: str,
                    conditions: list[dict[str, Any]],
                    filters: list[dict[str, Any]] | None = None) -> Reference:
    """Entities meeting every stated movement condition between two periods.

    Written as an explicit self-join rather than by reusing the runtime's
    two-period machinery, which is the point: if both produce the same cohort,
    the cohort is right.
    """
    opening_where = _where(opening, filters)
    closing_where = _where(closing, filters)
    measures = sorted({str(c["column"]) for c in conditions})
    selected = ", ".join(f"{m}" for m in measures)
    aggs = ", ".join(f"{c.get('agg', 'sum')}({c['column']}) AS {c['column']}"
                     for c in _unique_by_column(conditions))

    tests = []
    for clause in conditions:
        column, direction = str(clause["column"]), str(clause["direction"])
        operator = ">" if direction == "up" else "<"
        tests.append(f"c.{column} {operator} o.{column}")

    sql = (
        f"WITH opening AS (\n"
        f"  SELECT {key}, {aggs} FROM {_source(dataset)}{opening_where}\n"
        f"  GROUP BY {key}\n), closing AS (\n"
        f"  SELECT {key}, {aggs} FROM {_source(dataset)}{closing_where}\n"
        f"  GROUP BY {key}\n)\n"
        f"SELECT c.{key} AS id FROM closing c JOIN opening o USING ({key})\n"
        f"WHERE {' AND '.join(tests)} ORDER BY 1"
    )
    try:
        rows = _run(sql)
    except Exception as e:  # noqa: BLE001
        return Reference(kind="cohort", error=str(e), derivation=sql)

    said = ", ".join(f"{c['column']} {'rose' if c['direction'] == 'up' else 'fell'}"
                     for c in conditions)
    return Reference(
        kind="cohort",
        values={"row_count": len(rows)},
        ids=[str(r["id"]) for r in rows],
        rows=[{"id": str(r["id"])} for r in rows],
        summary=(f"{len(rows)} {key} in {dataset} where {said} between "
                 f"{opening} and {closing}."),
        derivation=sql + f"\n\n-- selected columns: {selected}",
    )


def joined_cohort(*, dataset: str, key: str, opening: str, closing: str,
                  conditions: list[dict[str, Any]],
                  join: dict[str, Any],
                  filters: list[dict[str, Any]] | None = None) -> Reference:
    """A cohort whose conditions span two governed datasets.

    The temporal alignment is stated OUTRIGHT in the benchmark rather than
    derived: an annual rating cycle read as at Q2 2026 is the 2025 cycle, and a
    reference that re-derived that rule from the same reasoning as the runtime
    would agree with it for the wrong reason. Writing the two years down makes
    the reference checkable by reading it.
    """
    other = str(join["dataset"])
    other_key = str(join.get("key") or key)

    def side(source: str, period: str, clauses: list[dict[str, Any]],
             alias: str, join_key: str) -> str:
        aggs = ", ".join(
            f"{c.get('agg', 'sum')}({c['column']}) AS {c['column']}"
            for c in _unique_by_column(clauses))
        where = _where(period, filters if source == dataset else None)
        return (f"{alias} AS (SELECT {join_key} AS k, {aggs} "
                f"FROM {_source(source)}{where} GROUP BY 1)")

    parts = [
        side(dataset, opening, conditions, "base_open", key),
        side(dataset, closing, conditions, "base_close", key),
        side(other, str(join["opening"]), join["conditions"], "other_open",
             other_key),
        side(other, str(join["closing"]), join["conditions"], "other_close",
             other_key),
    ]
    tests = [f"bc.{c['column']} {'>' if c['direction'] == 'up' else '<'} "
             f"bo.{c['column']}" for c in conditions]
    tests += [f"oc.{c['column']} {'>' if c['direction'] == 'up' else '<'} "
              f"oo.{c['column']}" for c in join["conditions"]]

    sql = ("WITH " + ",\n     ".join(parts) + "\n"
           "SELECT bc.k AS id FROM base_close bc\n"
           "JOIN base_open bo USING (k)\n"
           "JOIN other_close oc USING (k)\n"
           "JOIN other_open oo USING (k)\n"
           f"WHERE {' AND '.join(tests)} ORDER BY 1")
    try:
        rows = _run(sql)
    except Exception as e:  # noqa: BLE001
        return Reference(kind="cohort", error=str(e), derivation=sql)

    said = ", ".join(
        f"{c['column']} {'rose' if c['direction'] == 'up' else 'fell'}"
        for c in [*conditions, *join["conditions"]])
    return Reference(
        kind="cohort",
        values={"row_count": len(rows)},
        ids=[str(r["id"]) for r in rows],
        rows=[{"id": str(r["id"])} for r in rows],
        summary=(f"{len(rows)} {key} where {said}, comparing {dataset} between "
                 f"{opening} and {closing} and {other} between "
                 f"{join['opening']} and {join['closing']}."),
        derivation=sql,
    )


def _unique_by_column(conditions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for clause in conditions:
        if clause["column"] in seen:
            continue
        seen.add(str(clause["column"]))
        out.append(clause)
    return out


# ------------------------------------------------------ catalogue references


def dataset_profile(*, dataset: str) -> Reference:
    """Field count, grain, period coverage — read from the catalogue.

    A metadata question's truth is metadata, so this reads the governed
    catalogue rather than counting rows. It is still independent of the
    orchestrator: the handler under test builds an answer from a retrieved,
    ranked, trimmed context, and this reads the record directly.
    """
    try:
        from backend.data_access import get_catalog, get_data_source

        entry = get_catalog().dataset(dataset)
        periods = list(get_data_source().periods(dataset))
    except Exception as e:  # noqa: BLE001
        return Reference(kind="dataset", error=str(e))

    return Reference(
        kind="dataset",
        values={"field_count": len(entry.fields),
                "period_count": len(periods),
                "first_period": periods[0] if periods else "",
                "latest_period": periods[-1] if periods else ""},
        ids=sorted(entry.fields),
        summary=(f"{entry.business_name} ({dataset}) carries "
                 f"{len(entry.fields)} governed fields at {entry.grain} "
                 f"across {len(periods)} published periods"
                 + (f" from {periods[0]} to {periods[-1]}." if periods else ".")),
        derivation=f"catalogue.dataset({dataset!r}) and the published period list",
    )


def relationship_path(*, source: str, target: str) -> Reference:
    """How two datasets connect, read straight from the governed relationships."""
    try:
        from backend.orchestration.context import relationship_rows

        rows = relationship_rows()
    except Exception as e:  # noqa: BLE001
        return Reference(kind="relationship", error=str(e))

    direct = [r for r in rows
              if {str(r.get("from_dataset")), str(r.get("to_dataset"))}
              == {source, target}]
    hops = _shortest_hops(rows, source, target)
    return Reference(
        kind="relationship",
        values={"direct": len(direct), "hops": len(hops)},
        ids=hops,
        summary=(f"{source} reaches {target} in {len(hops)} governed "
                 f"{'hop' if len(hops) == 1 else 'hops'}: "
                 + (" → ".join([source, *hops]) if hops else "no active path.")),
        derivation="the active dataset_relationships rows, walked breadth-first",
    )


def _shortest_hops(rows: list[dict[str, Any]], source: str,
                   target: str) -> list[str]:
    """Breadth-first over declared relationships. Deliberately naive."""
    edges: dict[str, set[str]] = {}
    for row in rows:
        left, right = str(row.get("from_dataset")), str(row.get("to_dataset"))
        edges.setdefault(left, set()).add(right)
        edges.setdefault(right, set()).add(left)

    queue: list[tuple[str, list[str]]] = [(source, [])]
    seen = {source}
    while queue:
        node, path = queue.pop(0)
        if node == target:
            return path
        for nxt in sorted(edges.get(node, ())):
            if nxt in seen:
                continue
            seen.add(nxt)
            queue.append((nxt, [*path, nxt]))
    return []


# ------------------------------------------------------------------ helpers


BUILDERS = {
    "aggregate": aggregate,
    "ranking": ranking,
    "count": count_distinct,
    "cohort": movement_cohort,
    "joined_cohort": joined_cohort,
    "dataset": dataset_profile,
    "relationship": relationship_path,
}


def compute(spec: dict[str, Any]) -> Reference:
    """The reference for one benchmark, from its declared specification.

    Called ONLY after the system under test has produced its answer. The runner
    enforces that ordering; this function has no way to leak into a prompt
    because nothing that builds a prompt can import this module.
    """
    kind = str(spec.get("kind") or "")
    builder = BUILDERS.get(kind)
    if builder is None:
        return Reference(kind=kind or "unknown",
                         error=f"'{kind}' is not a reference CreditProbe computes.")
    params = {k: v for k, v in spec.items() if k != "kind"}
    try:
        return builder(**params)
    except Exception as e:  # noqa: BLE001 - a broken reference must not break a run
        logger.exception("Reference %s could not be computed", kind)
        return Reference(kind=kind, error=str(e))


def _strictly_ordered(values: list[float]) -> bool:
    return len(set(values)) == len(values)


def _num(value: Any) -> float:
    try:
        return round(float(value), 4)
    except (TypeError, ValueError):
        return 0.0


def _fmt(value: Any) -> str:
    try:
        return f"{float(value):,.1f}"
    except (TypeError, ValueError):
        return str(value)


__all__ = ["BENCHMARK_VERSION", "BUILDERS", "LAKE", "Reference", "aggregate",
           "compute", "count_distinct", "dataset_profile", "movement_cohort",
           "joined_cohort", "ranking", "relationship_path"]
