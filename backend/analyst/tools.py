"""The governed tools the analyst may use. §3.

Each tool is a declaration and a handler. The declaration is what the model is
shown — a name, what it is for, what arguments it takes; the handler is what
CreditProbe runs, under `safety`, over the governed catalogue and the
analytical runtime.

The model never writes a query
------------------------------
It names a tool and passes typed arguments. `query_dataset(dataset=...,
where=[...], columns=[...])` is turned into an analytical plan HERE, in Python,
by CreditProbe. That is why §4's forbidden list is not a filter over anything:
the model has no channel through which a DELETE could travel.

Discovery is the point
----------------------
A product where every question has to map onto one prebuilt certified analysis
can only answer the questions somebody thought of. So the first four tools do
nothing but let the model LOOK: which domains exist, which datasets are in
them, what a dataset's grain is, what its fields mean. A model that can read
the data dictionary can compose an analysis nobody wrote down, and can say
truthfully that a dimension the question named is not in the catalogue (§7)
rather than refusing the whole question or quietly answering a different one.

What a tool returns
-------------------
An `Observation` — rows, a total, the datasets read, and either a result or a
refusal. A refusal is a normal return value, not an exception: the loop shows
it to the model, which chooses something else, and the Trace records the gap.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from backend.analyst import safety
from backend.analyst.evidence import Observation
from backend.analyst.safety import (
    READ_DATA,
    READ_METADATA,
    RUN_ANALYSIS,
    Principal,
    Refused,
)

logger = logging.getLogger(__name__)

TOOLS_VERSION = "1.0.0"


@dataclass(frozen=True)
class Tool:
    """One thing the analyst can ask CreditProbe to do."""

    name: str
    #: What it is for, written for the model. One sentence, no jargon the
    #: catalogue does not itself use.
    purpose: str
    capability: str
    #: argument name -> what it is. Shown to the model verbatim; this IS the
    #: interface, so it is prose a reader can check rather than a JSON Schema
    #: nobody reads.
    arguments: dict[str, str] = field(default_factory=dict)
    required: tuple[str, ...] = ()
    handler: Callable[..., Observation] | None = None
    #: True for the tools that only read metadata. Used by the loop to let
    #: discovery happen freely while counting the expensive calls.
    discovery: bool = False

    def describe(self) -> dict[str, Any]:
        return {"name": self.name, "purpose": self.purpose,
                "arguments": dict(self.arguments),
                "required": list(self.required),
                "capability": self.capability, "discovery": self.discovery}


# --------------------------------------------------------------- the helpers


def _catalog():
    from backend.data_access.catalog import get_catalog

    return get_catalog()


def _source():
    from backend.data_access import get_data_source

    return get_data_source()


def _visible(principal: Principal):
    """The catalogue this principal may see, as {name: DatasetDef}."""
    catalog = _catalog()
    allowed = set(safety.visible_datasets(principal, catalog.names()))
    return {name: catalog.dataset(name) for name in sorted(allowed)}


def _refusal(tool: str, arguments: dict[str, Any], why: str) -> Observation:
    return Observation(tool=tool, arguments=dict(arguments), refused=why)


def _rows_of(frame, limit: int) -> tuple[list[dict[str, Any]], int]:
    """A dataframe as JSON-safe rows, truncated, with the true total."""
    total = int(len(frame))
    head = frame.head(limit)
    rows: list[dict[str, Any]] = []
    for record in head.to_dict(orient="records"):
        rows.append({str(k): _plain(v) for k, v in record.items()})
    return rows, total


#: Significant figures every numeric a tool returns is rounded to.
#:
#: Not cosmetic. DuckDB sums in whatever order its workers finish in, so the
#: same SUM over the same rows came back as 284394.6739999999 and
#: 284394.6739999996 on two consecutive runs — a difference in the last bits
#: of a float, in a figure quoted to two decimals, and enough to make §11's
#: "the same question returns the same rows" false. Nine significant figures
#: is far beyond anything a credit report shows and far short of where
#: summation order lives, and it is the same precision the evidence hash uses,
#: so a row and its hash cannot disagree.
FIGURES = 9


def _plain(value: Any) -> Any:
    import math

    if value is None:
        return None
    if isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return float(f"{value:.{FIGURES}g}")
    try:
        import pandas as pd

        if value is pd.NaT or (hasattr(pd, "isna") and pd.isna(value)):
            return None
    except Exception:  # noqa: BLE001 - a formatting helper must not fail
        pass
    return str(value)


# ----------------------------------------------------------- discovery tools


def list_data_domains(principal: Principal, **_: Any) -> Observation:
    """The business domains, from the one metadata service. §12.

    This used to group the file catalogue by whatever domain each dataset
    happened to name, which meant a heading with nothing installed under it
    did not exist — the tool answered "5" where the Data Builder screen said
    "7" for the same deployment. Both were reading something true and neither
    was reading the same thing, so both now read `backend.metadata`.

    Domains a heading holds are still filtered to what this principal may see,
    because the count of DATASETS is a permission-scoped fact even when the
    list of headings is not.
    """
    from backend import metadata as md

    visible = set(_visible(principal))
    rows = []
    for heading in md.domains():
        allowed = [n for n in heading.datasets if n in visible]
        rows.append({
            "domain": heading.name,
            "datasets": len(allowed),
            "fields": sum(len(md.fields(n)) for n in allowed),
            "rows_published": sum(
                (md.dataset(n).row_count if md.dataset(n) else 0)
                for n in allowed),
            "owner": heading.owner,
            "description": heading.description,
        })
    return Observation(
        tool="list_data_domains", rows=rows, total_rows=len(rows),
        columns=["domain", "datasets", "fields", "rows_published", "owner",
                 "description"],
        purpose="the governed business domains and how many datasets each holds")


def list_datasets(principal: Principal, domain: str = "",
                  **_: Any) -> Observation:
    from backend import metadata as md

    visible = set(_visible(principal))
    wanted = md.domain(domain) if domain else None
    rows = [
        {"dataset": found.name, "business_name": found.business_name,
         "domain": found.domain, "grain": found.grain,
         "fields": found.field_count, "period_field": found.period_field}
        for found in md.datasets()
        if found.name in visible
        and (wanted is None or found.name in wanted.datasets)
    ]
    return Observation(
        tool="list_datasets", arguments={"domain": domain},
        rows=sorted(rows, key=lambda r: r["dataset"]), total_rows=len(rows),
        columns=["dataset", "business_name", "domain", "grain", "fields"],
        purpose="the governed datasets available to this question")


def describe_domain(principal: Principal, domain: str = "",
                    **_: Any) -> Observation:
    if not domain:
        return _refusal("describe_domain", {}, "name a domain to describe.")
    found = list_datasets(principal, domain=domain)
    found.tool = "describe_domain"
    found.arguments = {"domain": domain}
    if not found.rows:
        found.refused = (f"No governed domain matches '{domain}'. "
                         "Use list_data_domains to see what exists.")
    return found


def describe_dataset(principal: Principal, dataset: str = "",
                     **_: Any) -> Observation:
    visible = _visible(principal)
    definition = visible.get(dataset)
    if definition is None:
        return _refusal(
            "describe_dataset", {"dataset": dataset},
            f"'{dataset}' is not a governed dataset this question can read. "
            "Use list_datasets to see what is available.")
    from backend import metadata as md

    described = md.dataset(dataset)
    periods = list(described.periods) if described else _periods(dataset)
    rows = [{
        "dataset": definition.name,
        "business_name": definition.business_name,
        "domain": definition.domain,
        "purpose": definition.purpose,
        "grain": definition.grain,
        "primary_keys": ", ".join(definition.primary_keys),
        "period_field": definition.period_field,
        "periods": len(periods),
        "earliest_period": periods[0] if periods else "",
        "latest_period": periods[-1] if periods else "",
        "fields": len(definition.fields),
        "is_synthetic": definition.is_synthetic,
        "authoritative_for": ", ".join(definition.authoritative_for),
    }]
    return Observation(
        tool="describe_dataset", arguments={"dataset": dataset}, rows=rows,
        total_rows=1, columns=list(rows[0]), datasets=[dataset],
        purpose=f"what one row of {dataset} represents, and over what periods")


def get_data_dictionary(principal: Principal, dataset: str = "",
                        contains: str = "", **_: Any) -> Observation:
    visible = _visible(principal)
    definition = visible.get(dataset)
    if definition is None:
        return _refusal(
            "get_data_dictionary", {"dataset": dataset},
            f"'{dataset}' is not a governed dataset this question can read.")
    rows = []
    for field_def in definition.fields.values():
        payload = field_def.to_dict()
        name = str(payload.get("name") or "")
        label = str(payload.get("business_name") or "")
        description = str(payload.get("definition") or "")
        if contains and contains.lower() not in (
                f"{name} {label} {description}".lower()):
            continue
        rows.append({
            "field": name, "label": label, "description": description,
            "type": payload.get("data_type") or "",
            "unit": payload.get("unit") or "",
            "allowed_values": ", ".join(payload.get("allowed_values") or []),
            "nullable": payload.get("nullable"),
        })
    return Observation(
        tool="get_data_dictionary",
        arguments={"dataset": dataset, "contains": contains},
        rows=sorted(rows, key=lambda r: r["field"]), total_rows=len(rows),
        columns=["field", "label", "description", "type", "unit"],
        datasets=[dataset],
        purpose=f"what every field of {dataset} means")


def get_available_measures(principal: Principal, dataset: str = "",
                           **_: Any) -> Observation:
    found = _fields_by_kind(principal, dataset, numeric=True)
    found.tool = "get_available_measures"
    found.purpose = f"the numeric measures {dataset} carries"
    return found


def get_available_dimensions(principal: Principal, dataset: str = "",
                             **_: Any) -> Observation:
    found = _fields_by_kind(principal, dataset, numeric=False)
    found.tool = "get_available_dimensions"
    found.purpose = f"the dimensions {dataset} can be grouped or filtered by"
    return found


def _fields_by_kind(principal: Principal, dataset: str,
                    *, numeric: bool) -> Observation:
    visible = _visible(principal)
    definition = visible.get(dataset)
    if definition is None:
        return _refusal("get_available_measures", {"dataset": dataset},
                        f"'{dataset}' is not a governed dataset here.")
    rows = []
    for field_def in definition.fields.values():
        payload = field_def.to_dict()
        dtype = str(payload.get("data_type") or "").lower()
        is_number = any(k in dtype for k in ("int", "float", "decimal",
                                             "number", "numeric", "double"))
        if is_number != numeric:
            continue
        rows.append({"field": payload.get("name"),
                     "label": payload.get("business_name") or "",
                     "unit": payload.get("unit") or "",
                     "means": payload.get("definition") or "",
                     "type": dtype})
    return Observation(
        tool="get_available_measures", arguments={"dataset": dataset},
        rows=sorted(rows, key=lambda r: str(r["field"])), total_rows=len(rows),
        columns=["field", "label", "unit", "means", "type"],
        datasets=[dataset])


def get_dataset_periods(principal: Principal, dataset: str = "",
                        **_: Any) -> Observation:
    visible = _visible(principal)
    if dataset not in visible:
        return _refusal("get_dataset_periods", {"dataset": dataset},
                        f"'{dataset}' is not a governed dataset here.")
    periods = _periods(dataset)
    rows = [{"period": p} for p in periods]
    return Observation(
        tool="get_dataset_periods", arguments={"dataset": dataset},
        rows=rows, total_rows=len(rows), columns=["period"],
        datasets=[dataset], period=periods[-1] if periods else "",
        purpose=f"the reporting periods {dataset} actually holds")


def _keys_of(payload: dict[str, Any]) -> str:
    """The join keys, however the relationship record spells them."""
    if payload.get("from_field") or payload.get("to_field"):
        return f"{payload.get('from_field')} = {payload.get('to_field')}"
    keys = (payload.get("on") or payload.get("keys")
            or payload.get("join_keys") or payload.get("key_pairs") or "")
    if isinstance(keys, str):
        return keys
    if isinstance(keys, dict):
        return ", ".join(f"{k} = {v}" for k, v in sorted(keys.items()))
    if isinstance(keys, (list, tuple)):
        parts = []
        for item in keys:
            if isinstance(item, dict):
                left = item.get("left") or item.get("left_field") or ""
                right = item.get("right") or item.get("right_field") or ""
                parts.append(f"{left} = {right}" if right else str(left))
            else:
                parts.append(str(item))
        return ", ".join(p for p in parts if p)
    return str(keys)


def _periods(dataset: str) -> list[str]:
    try:
        return list(_source().periods(dataset))
    except Exception as e:  # noqa: BLE001 - a dataset with no period column
        logger.debug("No periods for %s: %s", dataset, e)
        return []


def get_relationships(principal: Principal, dataset: str = "",
                      **_: Any) -> Observation:
    """The governed joins. The model may use one; it may not invent one."""
    visible = _visible(principal)
    rows: list[dict[str, Any]] = []
    declared: list[Any] = []
    try:
        from backend.db.engine import get_session
        from backend.services import relationships as rel

        with get_session() as session:
            declared = rel.active_relationships(session)
    except Exception as e:  # noqa: BLE001 - no database, or none declared
        logger.debug("No relationship graph: %s", e)
    for edge in declared:
        payload = edge if isinstance(edge, dict) else getattr(
            edge, "to_dict", dict)()
        left = str(payload.get("left_dataset") or payload.get("from_dataset")
                   or payload.get("left") or "")
        right = str(payload.get("right_dataset") or payload.get("to_dataset")
                    or payload.get("right") or "")
        if left not in visible or right not in visible:
            continue
        if dataset and dataset not in (left, right):
            continue
        rows.append({
            "left": left, "right": right,
            "keys": _keys_of(payload),
            "cardinality": payload.get("cardinality") or "",
            "means": payload.get("business_meaning")
            or payload.get("description") or "",
            "status": payload.get("status") or "",
        })
    return Observation(
        tool="get_relationships", arguments={"dataset": dataset}, rows=rows,
        total_rows=len(rows), columns=["left", "right", "keys", "cardinality"],
        purpose="the governed joins between datasets")


def get_metric_definition(principal: Principal, metric: str = "",
                          **_: Any) -> Observation:
    """Where a named business measure actually lives, and what it means."""
    del principal
    if not metric:
        return _refusal("get_metric_definition", {}, "name a metric.")
    import re

    from backend.orchestration import concepts

    rows = []
    for concept in concepts.CONCEPTS:
        if not re.search(concept.pattern, metric, re.IGNORECASE):
            continue
        for candidate in concept.candidates:
            rows.append({
                "metric": concept.label,
                "means": candidate.definition,
                "dataset": candidate.dataset,
                "field": candidate.field,
                "qualifiers": ", ".join(candidate.qualifiers),
                "is_default": candidate.is_default,
                "unit": concept.unit,
                "higher_is_worse": concept.higher_is_worse,
            })
    if not rows:
        return _refusal(
            "get_metric_definition", {"metric": metric},
            f"The governed catalogue has no measure called '{metric}'. "
            "Use get_data_dictionary to see what the datasets carry.")
    return Observation(
        tool="get_metric_definition", arguments={"metric": metric},
        rows=rows[:safety.MAX_ROWS_TO_MODEL], total_rows=len(rows),
        columns=list(rows[0]),
        datasets=sorted({str(r["dataset"]) for r in rows}),
        purpose=(f"where '{metric}' lives in the governed catalogue, and "
                 "which candidate is the default"))


def get_threshold_definition(principal: Principal, name: str = "",
                             **_: Any) -> Observation:
    """A governed threshold, its value, its owner and its version.

    §37: "what threshold was crossed" and "when did that threshold change" are
    questions the analyst must answer from metadata rather than invent.
    """
    del principal
    from backend.early_warning import taxonomy as ews
    from backend.orchestration import composites as cmp

    rows = []
    # §37: "what threshold was crossed", "when did that threshold change",
    # "what model or rule produced this result". All three are questions about
    # governed metadata, and the analyst must answer them from metadata rather
    # than invent a methodology. The early-warning taxonomy is where most of
    # the thresholds a credit officer will ask about actually live.
    for signal in ews.SIGNALS:
        if name and name.lower() not in (
                f"{signal.key} {signal.label} {signal.family}".lower()):
            continue
        rows.append({"threshold": signal.key, "means": signal.sentence(),
                     "family": ews.FAMILIES.get(signal.family, signal.family),
                     "dataset": signal.dataset, "field": signal.field,
                     "test": signal.test, "value": signal.threshold,
                     "severity": signal.severity,
                     "booked_accounting": signal.booked_accounting,
                     "owner": signal.to_dict()["owner"],
                     "version": signal.version})
    for composite in cmp.COMPOSITES:
        for signal in composite.signals:
            if name and name.lower() not in (
                    f"{signal.key} {signal.label}".lower()):
                continue
            rows.append({"threshold": signal.key, "means": signal.label,
                         "dataset": signal.dataset, "field": signal.field,
                         "test": signal.test, "value": signal.value,
                         "composite": composite.label,
                         "owner": "Credit Risk Analytics",
                         "version": getattr(cmp, "COMPOSITES_VERSION",
                                            "1.0.0")})
    if not rows:
        return _refusal(
            "get_threshold_definition", {"name": name},
            f"No governed threshold matches '{name}'." if name else
            "No governed thresholds are declared in this deployment.")
    return Observation(
        tool="get_threshold_definition", arguments={"name": name}, rows=rows,
        total_rows=len(rows),
        columns=["threshold", "means", "dataset", "field", "test", "value"],
        purpose="the governed thresholds, their values and who owns them")


def get_model_definition(principal: Principal, model: str = "",
                         **_: Any) -> Observation:
    del principal
    rows: list[dict[str, Any]] = []
    try:
        from backend.scorecard import registry

        for record in registry.registered():
            payload = record if isinstance(record, dict) else record.to_dict()
            if model and model.lower() not in str(payload).lower():
                continue
            rows.append({"model": payload.get("name") or payload.get("model_id"),
                         "kind": payload.get("kind") or "",
                         "status": payload.get("status") or "",
                         "version": payload.get("version") or "",
                         "owner": payload.get("owner") or ""})
    except Exception as e:  # noqa: BLE001 - no registry in this deployment
        logger.debug("No model registry: %s", e)
    if not rows:
        return _refusal("get_model_definition", {"model": model},
                        "No governed model registry is available here.")
    return Observation(
        tool="get_model_definition", arguments={"model": model}, rows=rows,
        total_rows=len(rows), columns=["model", "kind", "status", "version"],
        purpose="the registered models and their governance state")


def get_policy_definition(principal: Principal, policy: str = "",
                          **_: Any) -> Observation:
    del principal
    rows: list[dict[str, Any]] = []
    try:
        from backend.scorecard import policy as policy_mod

        for limit in policy_mod.seeded_limits():
            payload = limit if isinstance(limit, dict) else limit.to_dict()
            if policy and policy.lower() not in str(payload).lower():
                continue
            rows.append(payload)
    except Exception as e:  # noqa: BLE001
        logger.debug("No policy registry: %s", e)
    if not rows:
        return _refusal("get_policy_definition", {"policy": policy},
                        "No governed policy registry is available here.")
    return Observation(
        tool="get_policy_definition", arguments={"policy": policy},
        rows=rows[:safety.MAX_ROWS_TO_MODEL], total_rows=len(rows),
        columns=list(rows[0]), purpose="the governed limits and their sources")


__all__ = ["TOOLS_VERSION", "Principal", "Refused", "Tool"]


# ----------------------------------------------------------- analysis tools
#
# Every one of these builds an analytical plan HERE, from typed arguments, and
# runs it through `backend.runtime.execute` — the same entry point Ask
# CreditProbe, a saved method and the Trace editor all use, so the validator
# and the limits cannot be bypassed by adding a caller. The model supplies
# nouns; CreditProbe supplies the query.


def _plan_dict(objective: str, operations: list[dict[str, Any]]) -> dict:
    return {"objective": objective, "operations": operations,
            "meta": {"planner": "analyst-tool", "version": TOOLS_VERSION}}


def _scan(dataset: str, period: str, definition) -> dict[str, Any]:
    params: dict[str, Any] = {"dataset": dataset}
    if period and definition.period_field:
        params["filters"] = {definition.period_field: period}
    return {"id": "scan", "op": "SCAN", "inputs": [], "params": params}


def _where(where: list[dict[str, Any]] | None, definition,
           after: str) -> list[dict[str, Any]]:
    """Typed comparisons, turned into governed FILTER operations.

    Each entry is {field, op, value}. `op` is one of a closed list; a field
    the dataset does not carry is refused by name rather than dropped, because
    silently ignoring a condition is how an answer ends up describing a
    different population from the one that was asked for.
    """
    #: The model's vocabulary on the left, the runtime's on the right. A
    #: closed mapping: an operator not in it is refused by name rather than
    #: passed through and rejected later with a runtime message.
    allowed = {
        "eq": "=", "=": "=", "==": "=", "is": "=",
        "ne": "!=", "!=": "!=", "not": "!=",
        "gt": ">", ">": ">", "gte": ">=", ">=": ">=",
        "lt": "<", "<": "<", "lte": "<=", "<=": "<=",
        "in": "in", "not_in": "not_in", "between": "between",
        "contains": "contains", "starts_with": "starts_with",
        "ends_with": "ends_with",
        "is_null": "is_null", "is_not_null": "is_not_null",
    }
    if not where:
        return []
    conditions: list[dict[str, Any]] = []
    for condition in where:
        field_name = str(condition.get("field")
                         or condition.get("column") or "")
        operator = allowed.get(str(condition.get("op") or "eq").lower())
        if field_name not in definition.fields:
            raise Refused(
                f"'{field_name}' is not a field of {definition.name}. "
                "Use get_data_dictionary to see what it carries.")
        if operator is None:
            raise Refused(
                f"'{condition.get('op')}' is not a comparison the analyst can "
                f"make. Use one of: {', '.join(sorted(set(allowed)))}.")
        conditions.append({"column": field_name, "op": operator,
                           "value": condition.get("value")})
    return [{"id": "filter", "op": "FILTER", "inputs": [after],
             "params": {"where": conditions}}]


def _sorted_limit(after: str, by: str, direction: str, n: int,
                  tiebreak: str) -> list[dict[str, Any]]:
    """A deterministic ordering and a bounded result. §11.

    The tie-break is not optional. Two borrowers with the same exposure come
    back in whatever order the engine felt like, and "the same question
    returns the same rows" then depends on a query planner's mood.
    """
    order = [{"column": by, "direction": direction}]
    if tiebreak and tiebreak != by:
        order.append({"column": tiebreak, "direction": "asc"})
    return [
        {"id": "sort", "op": "SORT", "inputs": [after],
         "params": {"by": order}},
        {"id": "limit", "op": "LIMIT", "inputs": ["sort"],
         "params": {"n": max(1, min(int(n or 25), safety.MAX_TOOL_ROWS))}},
    ]


def _run(plan: dict[str, Any], *, tool: str, arguments: dict[str, Any],
         datasets: list[str], period: str, purpose: str) -> Observation:
    """Validate, run, and record. The one path every analysis tool takes."""
    from backend.runtime.executor import execute
    from backend.runtime.validation import Limits

    safety.check_plan(plan)
    started = time.perf_counter()
    limits = Limits(max_output_rows=safety.MAX_TOOL_ROWS,
                    timeout_seconds=safety.TOOL_TIMEOUT_SECONDS)
    result = execute(plan, limits=limits, question=purpose,
                     intent="analyst_tool")
    rows = [{str(k): _plain(v) for k, v in row.items()}
            for row in (result.rows or [])]
    return Observation(
        tool=tool, arguments=dict(arguments),
        rows=rows[:safety.MAX_ROWS_TO_MODEL], total_rows=len(rows),
        columns=[str(c.get("name")) for c in (result.columns or [])],
        datasets=datasets, period=period, purpose=purpose,
        duration_ms=int((time.perf_counter() - started) * 1000),
        plan=plan)


def _dataset_or_refuse(principal: Principal, dataset: str, tool: str):
    visible = _visible(principal)
    definition = visible.get(dataset)
    if definition is None:
        raise Refused(
            f"'{dataset}' is not a governed dataset this question can read. "
            "Use list_datasets to see what is available.")
    del tool
    return definition


def _latest(definition, period: str) -> str:
    if period:
        return period
    periods = _periods(definition.name)
    return periods[-1] if periods else ""


def query_dataset(principal: Principal, dataset: str = "",
                  columns: list[str] | None = None,
                  where: list[dict[str, Any]] | None = None,
                  period: str = "", order_by: str = "",
                  descending: bool = True, limit: int = 50,
                  **_: Any) -> Observation:
    """Rows from one governed dataset, filtered and ordered."""
    arguments = {"dataset": dataset, "columns": columns, "where": where,
                 "period": period, "order_by": order_by, "limit": limit}
    try:
        definition = _dataset_or_refuse(principal, dataset, "query_dataset")
        chosen = _latest(definition, period)
        wanted = [c for c in (columns or []) if c in definition.fields]
        unknown = [c for c in (columns or []) if c not in definition.fields]
        if unknown:
            raise Refused(
                f"{dataset} has no field called {', '.join(unknown)}. "
                "Use get_data_dictionary to see what it carries.")
        operations = [_scan(dataset, chosen, definition)]
        operations.extend(_where(where, definition, "scan"))
        last = operations[-1]["id"]
        if wanted:
            operations.append({"id": "select", "op": "SELECT",
                               "inputs": [last],
                               "params": {"columns": wanted}})
            last = "select"
        # The tie-break has to be a column that SURVIVES the projection. A
        # primary key the SELECT dropped is not available to sort by, and the
        # runtime says so rather than guessing — which is the right behaviour
        # and was the bug: `period` is portfolio_facility's first primary key
        # and the caller had asked for two other columns.
        available = wanted or list(definition.fields)
        key = next((k for k in definition.primary_keys if k in available),
                   available[0])
        by = order_by if order_by in available else key
        operations.extend(_sorted_limit(
            last, by, "desc" if descending else "asc", limit, key))
        return _run(_plan_dict(f"rows from {dataset}", operations),
                    tool="query_dataset", arguments=arguments,
                    datasets=[dataset], period=chosen,
                    purpose=f"rows from {dataset}")
    except Refused as e:
        return _refusal("query_dataset", arguments, str(e))
    except Exception as e:  # noqa: BLE001 - a tool failure is evidence, not a crash
        logger.warning("query_dataset failed: %s", e)
        return _refusal("query_dataset", arguments,
                        f"that query could not be run: {_why(e)}")


def aggregate_dataset(principal: Principal, dataset: str = "",
                      group_by: list[str] | None = None,
                      measures: list[dict[str, str]] | None = None,
                      where: list[dict[str, Any]] | None = None,
                      period: str = "", limit: int = 50,
                      **_: Any) -> Observation:
    """One row per group, with governed aggregates over it."""
    arguments = {"dataset": dataset, "group_by": group_by,
                 "measures": measures, "where": where, "period": period}
    try:
        definition = _dataset_or_refuse(principal, dataset, "aggregate_dataset")
        chosen = _latest(definition, period)
        keys = [k for k in (group_by or []) if k in definition.fields]
        if (group_by or []) and not keys:
            raise Refused(
                f"None of {', '.join(group_by or [])} is a field of {dataset}.")
        aggregates = _aggregates(measures, definition)
        operations = [_scan(dataset, chosen, definition)]
        operations.extend(_where(where, definition, "scan"))
        last = operations[-1]["id"]
        operations.append({
            "id": "group", "op": "GROUP", "inputs": [last],
            "params": {"by": keys, "aggregates": aggregates}})
        first_measure = aggregates[0]["as"]
        operations.extend(_sorted_limit(
            "group", first_measure, "desc", limit,
            keys[0] if keys else first_measure))
        return _run(_plan_dict(f"{dataset} grouped", operations),
                    tool="aggregate_dataset", arguments=arguments,
                    datasets=[dataset], period=chosen,
                    purpose=(f"{dataset} aggregated by "
                             f"{', '.join(keys) or 'the whole population'}"))
    except Refused as e:
        return _refusal("aggregate_dataset", arguments, str(e))
    except Exception as e:  # noqa: BLE001
        logger.warning("aggregate_dataset failed: %s", e)
        return _refusal("aggregate_dataset", arguments,
                        f"that aggregation could not be run: {_why(e)}")


#: The aggregate functions a tool may ask for. A closed list, because "any
#: function the engine happens to expose" is how a median arrives with no
#: definition of how it handles ties.
AGGREGATES: frozenset[str] = frozenset({"sum", "avg", "min", "max", "count",
                                        "count_distinct", "median"})


def _aggregates(measures: list[dict[str, str]] | None,
                definition) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for measure in measures or []:
        function = str(measure.get("function") or "sum").lower()
        column = str(measure.get("field") or measure.get("column") or "")
        if function not in AGGREGATES:
            raise Refused(
                f"'{function}' is not an aggregate the analyst may use. "
                f"Choose from: {', '.join(sorted(AGGREGATES))}.")
        if column and column not in definition.fields:
            raise Refused(
                f"'{column}' is not a field of {definition.name}.")
        out.append({"function": function, "column": column,
                    "as": measure.get("as") or f"{function}_{column or 'rows'}"})
    if not out:
        out = [{"function": "count", "column": "", "as": "rows"}]
    return out


def rank_entities(principal: Principal, dataset: str = "",
                  entity: str = "", measure: str = "",
                  function: str = "sum", where: list[dict[str, Any]] | None = None,
                  period: str = "", top: int = 25, ascending: bool = False,
                  **_: Any) -> Observation:
    """The borrowers, facilities or sectors highest or lowest on one measure.

    Separate from `aggregate_dataset` because ranking is what most credit
    questions actually are, and a tool whose name says what it does is one the
    model picks correctly.
    """
    arguments = {"dataset": dataset, "entity": entity, "measure": measure,
                 "function": function, "period": period, "top": top,
                 "ascending": ascending, "where": where}
    try:
        definition = _dataset_or_refuse(principal, dataset, "rank_entities")
        if entity not in definition.fields:
            raise Refused(
                f"'{entity}' is not a field of {dataset}. Use "
                "get_available_dimensions to see what it can be ranked by.")
        chosen = _latest(definition, period)
        aggregates = _aggregates(
            [{"function": function, "field": measure, "as": "value"}],
            definition)
        operations = [_scan(dataset, chosen, definition)]
        operations.extend(_where(where, definition, "scan"))
        last = operations[-1]["id"]
        operations.append({
            "id": "group", "op": "GROUP", "inputs": [last],
            "params": {"by": [entity], "aggregates": aggregates}})
        operations.extend(_sorted_limit(
            "group", "value", "asc" if ascending else "desc", top, entity))
        return _run(_plan_dict(f"{entity} ranked by {measure}", operations),
                    tool="rank_entities", arguments=arguments,
                    datasets=[dataset], period=chosen,
                    purpose=(f"{entity} ranked by {function}({measure}) "
                             f"at {chosen or 'the latest period'}"))
    except Refused as e:
        return _refusal("rank_entities", arguments, str(e))
    except Exception as e:  # noqa: BLE001
        logger.warning("rank_entities failed: %s", e)
        return _refusal("rank_entities", arguments,
                        f"that ranking could not be run: {_why(e)}")


def compare_periods(principal: Principal, dataset: str = "",
                    entity: str = "", measure: str = "",
                    function: str = "sum", from_period: str = "",
                    to_period: str = "", top: int = 25,
                    **_: Any) -> Observation:
    """The same measure at two periods, and the movement between them.

    Two queries and a join in Python rather than one plan, because the two
    periods are two SCANs of the same dataset and the join key is the entity —
    a shape the relationship graph does not describe and does not need to.
    """
    arguments = {"dataset": dataset, "entity": entity, "measure": measure,
                 "from_period": from_period, "to_period": to_period}
    try:
        _dataset_or_refuse(principal, dataset, "compare_periods")
        periods = _periods(dataset)
        opening = from_period or (periods[-2] if len(periods) > 1 else "")
        closing = to_period or (periods[-1] if periods else "")
        if not opening or not closing:
            raise Refused(
                f"{dataset} does not carry two reporting periods to compare.")
        before = rank_entities(principal, dataset=dataset, entity=entity,
                               measure=measure, function=function,
                               period=opening, top=safety.MAX_TOOL_ROWS)
        after = rank_entities(principal, dataset=dataset, entity=entity,
                              measure=measure, function=function,
                              period=closing, top=safety.MAX_TOOL_ROWS)
        for observation in (before, after):
            if observation.refused:
                raise Refused(observation.refused)
        opening_by = {row[entity]: row.get("value") for row in before.rows}
        rows = []
        for row in after.rows:
            key = row[entity]
            was = opening_by.get(key)
            now = row.get("value")
            movement = _movement(was, now)
            rows.append({entity: key, f"{measure}_{opening}": was,
                         f"{measure}_{closing}": now, "movement": movement})
        rows.sort(key=lambda r: (-(r["movement"] or 0), str(r[entity])))
        return Observation(
            tool="compare_periods", arguments=arguments,
            rows=rows[:min(top, safety.MAX_ROWS_TO_MODEL)],
            total_rows=len(rows),
            columns=[entity, f"{measure}_{opening}", f"{measure}_{closing}",
                     "movement"],
            datasets=[dataset], period=closing,
            purpose=(f"{measure} per {entity} at {opening} and {closing}, "
                     "and the movement between them"))
    except Refused as e:
        return _refusal("compare_periods", arguments, str(e))
    except Exception as e:  # noqa: BLE001
        logger.warning("compare_periods failed: %s", e)
        return _refusal("compare_periods", arguments,
                        f"that comparison could not be run: {_why(e)}")


def join_governed_datasets(principal: Principal, left: str = "",
                           right: str = "", columns: list[str] | None = None,
                           where: list[dict[str, Any]] | None = None,
                           period: str = "", limit: int = 50,
                           **_: Any) -> Observation:
    """Two datasets, joined on the DECLARED relationship between them.

    The model chooses which two datasets. It does not choose the key: the key
    comes from the governed relationship graph, and two datasets with no
    declared relationship cannot be joined at all. That is the difference
    between a join and a coincidence.
    """
    arguments = {"left": left, "right": right, "period": period}
    try:
        left_def = _dataset_or_refuse(principal, left, "join_governed_datasets")
        right_def = _dataset_or_refuse(principal, right,
                                       "join_governed_datasets")
        edges = get_relationships(principal, dataset=left)
        match = next(
            (r for r in edges.rows
             if {r["left"], r["right"]} == {left, right}), None)
        if match is None:
            raise Refused(
                f"No governed relationship joins {left} to {right}. "
                "A join CreditProbe has not declared is not one it will make. "
                "Use get_relationships to see the declared paths.")
        keys = str(match["keys"] or "")
        left_key, _, right_key = keys.partition(" = ")
        if not left_key or not right_key:
            raise Refused(
                f"The relationship between {left} and {right} does not name a "
                "join key that can be used here.")
        chosen = _latest(left_def, period)
        operations: list[dict[str, Any]] = [
            {"id": "left", "op": "SCAN", "inputs": [],
             "params": {"dataset": left,
                        **({"filters": {left_def.period_field: chosen}}
                           if chosen and left_def.period_field else {})}},
            {"id": "right", "op": "SCAN", "inputs": [],
             "params": {"dataset": right,
                        **({"filters": {right_def.period_field: chosen}}
                           if chosen and right_def.period_field else {})}},
            {"id": "join", "op": "JOIN", "inputs": ["left", "right"],
             "params": {"how": "inner",
                        "on": [{"left": left_key.strip(),
                                "right": right_key.strip()}]}},
        ]
        operations.extend(_where(where, left_def, "join"))
        last = operations[-1]["id"]
        wanted = [c for c in (columns or [])
                  if c in left_def.fields or c in right_def.fields]
        if wanted and left_key.strip() not in wanted:
            # The join key is kept in the projection whether or not the caller
            # asked for it, because it is the deterministic tie-break and a
            # sort by a column the SELECT dropped is not a sort.
            wanted = [left_key.strip(), *wanted]
        if wanted:
            operations.append({"id": "select", "op": "SELECT",
                               "inputs": [last],
                               "params": {"columns": wanted}})
            last = "select"
        operations.extend(_sorted_limit(last, left_key.strip(), "asc", limit,
                                        left_key.strip()))
        return _run(_plan_dict(f"{left} joined to {right}", operations),
                    tool="join_governed_datasets", arguments=arguments,
                    datasets=[left, right], period=chosen,
                    purpose=(f"{left} joined to {right} on the declared "
                             f"relationship ({keys})"))
    except Refused as e:
        return _refusal("join_governed_datasets", arguments, str(e))
    except Exception as e:  # noqa: BLE001
        logger.warning("join_governed_datasets failed: %s", e)
        return _refusal("join_governed_datasets", arguments,
                        f"that join could not be run: {_why(e)}")


#: Below this SHARE of the larger value, a difference is floating-point
#: noise from summing the same rows in a different order, not a movement. A
#: model handed "movement: 8.7e-11" will faithfully report that a sector moved.
NOISE = 1e-9


def _movement(was: Any, now: Any) -> float | None:
    if not isinstance(was, (int, float)) or not isinstance(now, (int, float)):
        return None
    difference = float(now) - float(was)
    scale = max(abs(float(was)), abs(float(now)), 1.0)
    return 0.0 if abs(difference) < NOISE * scale else difference


def _why(exc: Exception) -> str:
    """A tool failure, said without engineering detail. §9."""
    from backend.api import failures

    text = str(exc).strip().splitlines()[0] if str(exc).strip() else ""
    if not text or failures.leaks(text) or len(text) > 240:
        return "the governed runtime refused it"
    return text


# ----------------------------------------------------------- evidence tools
#
# Governed compositions over the datasets a credit officer would name. Each one
# is a query somebody could have written with the tools above; naming it
# separately is what lets the model ask the question it actually has —
# "what does the covenant evidence say about this borrower" — rather than
# reconstructing the composition every time and getting it subtly wrong.
#
# Every one of them declares which datasets it needs, and says so plainly when
# a deployment does not have them (§7). "This installation has no
# short-term-debt schedule" is an answer. Silently returning nothing is not.


@dataclass(frozen=True)
class Evidence:
    """One governed evidence bundle: where it lives and what it says."""

    name: str
    dataset: str
    #: Fields worth returning, in reading order. Missing ones are dropped and
    #: reported rather than failing the call: a deployment carrying twelve of
    #: fourteen columns should answer on twelve and say which two are absent.
    fields: tuple[str, ...]
    key: str
    purpose: str


EVIDENCE: dict[str, Evidence] = {
    "fetch_borrower_360": Evidence(
        name="fetch_borrower_360", dataset="corporate_borrower_360",
        fields=("borrower_id", "legal_name", "sector", "internal_rating",
                "ifrs9_stage", "pd_12m", "total_ead", "final_ecl",
                "utilisation_pct", "watchlist_flag", "cash",
                "collateral_coverage_pct", "average_headroom_pct",
                "breach_flag", "arrears_amount"),
        key="borrower_id",
        purpose="the whole governed position for one borrower"),
    "fetch_group_exposure": Evidence(
        name="fetch_group_exposure", dataset="corporate_connected_groups",
        fields=("borrower_id", "connected_group_id", "group_name",
                "group_role", "connected_group_size", "group_exposure",
                "group_utilisation_pct", "group_status", "debtrank_impact"),
        key="borrower_id",
        purpose="the connected group a borrower sits in, and its exposure"),
    "fetch_ifrs9_evidence": Evidence(
        name="fetch_ifrs9_evidence", dataset="corporate_ifrs9",
        fields=("borrower_id", "period", "stage", "prior_stage",
                "stage_moved", "pd_12m", "pd_lifetime", "final_ecl",
                "ecl_coverage", "sicr_flag", "sicr_trigger_pd",
                "sicr_trigger_dpd", "sicr_trigger_watchlist",
                "management_overlay", "current_dpd"),
        key="borrower_id",
        purpose=("stage, PD, ECL and which SICR trigger moved them — the "
                 "booked accounting stage, not a prediction of a future one")),
    "fetch_early_warning_evidence": Evidence(
        name="fetch_early_warning_evidence", dataset="corporate_watchlist",
        fields=("borrower_id", "period", "signal", "severity",
                "watchlist_grade", "raised_date", "raised_by"),
        key="borrower_id",
        purpose="the early-warning signals raised against a borrower"),
    "fetch_covenant_evidence": Evidence(
        name="fetch_covenant_evidence", dataset="corporate_covenants",
        fields=("borrower_id", "period", "covenant_name", "tested_measure",
                "threshold", "observed_value", "headroom_pct", "direction",
                "breach_flag", "waiver_granted", "next_test_date",
                "statement_age_days"),
        key="borrower_id",
        purpose="covenant tests, headroom, breaches and waivers"),
    "fetch_collateral_evidence": Evidence(
        name="fetch_collateral_evidence", dataset="corporate_collateral",
        fields=("borrower_id", "period", "collateral_type",
                "collateral_market_value", "collateral_eligible_value",
                "regulatory_haircut_pct", "last_valuation_date",
                "valuation_age_days", "valuation_overdue"),
        key="borrower_id",
        purpose=("collateral values — market value and post-haircut eligible "
                 "value are two different numbers and must not be confused")),
    "fetch_external_intelligence": Evidence(
        name="fetch_external_intelligence", dataset="credit_memo_signals",
        fields=("customer_id", "borrower_name", "period", "memo_type",
                "sentiment", "concerns_raised", "sector_headwind_mentioned",
                "liquidity_concern_mentioned", "covenant_breach_mentioned",
                "management_change_mentioned", "going_concern_mentioned",
                "signal_strength_pct", "extract"),
        key="customer_id",
        purpose="events and concerns recorded outside the behavioural data"),
}


def _evidence_tool(principal: Principal, spec: Evidence, *,
                   customer_id: str = "", borrower_name: str = "",
                   period: str = "", limit: int = 25) -> Observation:
    arguments = {"customer_id": customer_id, "borrower_name": borrower_name,
                 "period": period}
    visible = _visible(principal)
    definition = visible.get(spec.dataset)
    if definition is None:
        return _refusal(
            spec.name, arguments,
            f"This deployment has no {spec.dataset}, so {spec.purpose} cannot "
            "be supplied. Answer on the evidence that does exist and say this "
            "one is unavailable.")
    present = [f for f in spec.fields if f in definition.fields]
    absent = [f for f in spec.fields if f not in definition.fields]
    where: list[dict[str, Any]] = []
    if customer_id and spec.key in definition.fields:
        where.append({"field": spec.key, "op": "eq", "value": customer_id})
    elif borrower_name and "borrower_name" in definition.fields:
        where.append({"field": "borrower_name", "op": "eq",
                      "value": borrower_name})
    elif customer_id or borrower_name:
        # A borrower was named and this dataset cannot be narrowed to them.
        # Returning the whole book under a question about one borrower is
        # worse than refusing: the model would read it as that borrower's
        # evidence and every figure after it would be wrong.
        return _refusal(
            spec.name, arguments,
            f"{spec.dataset} cannot be narrowed to one borrower here — it "
            f"has no {spec.key}. Use query_dataset with the field it does "
            "carry.")
    found = query_dataset(principal, dataset=spec.dataset, columns=present,
                          where=where, period=period,
                          order_by=present[0] if present else "",
                          descending=False, limit=limit)
    found.tool = spec.name
    found.arguments = arguments
    found.purpose = spec.purpose
    if absent and not found.refused:
        found.purpose += (f" (this deployment does not carry: "
                          f"{', '.join(absent)})")
    return found


def fetch_borrower_360(principal: Principal, **kwargs: Any) -> Observation:
    return _evidence_tool(principal, EVIDENCE["fetch_borrower_360"], **kwargs)


def fetch_group_exposure(principal: Principal, **kwargs: Any) -> Observation:
    return _evidence_tool(principal, EVIDENCE["fetch_group_exposure"], **kwargs)


def fetch_ifrs9_evidence(principal: Principal, customer_id: str = "",
                         period: str = "", **kwargs: Any) -> Observation:
    """One borrower's booked IFRS 9 position, and why the book says it. §30."""
    del kwargs
    return _reading_tool("fetch_ifrs9_evidence", principal,
                         customer_id=customer_id, period=period)


def fetch_early_warning_evidence(principal: Principal,
                                 customer_id: str = "", period: str = "",
                                 **kwargs: Any) -> Observation:
    """Which governed early-warning conditions fire for one borrower. §37.

    The governed TAXONOMY rather than the watchlist register: "why was this
    borrower flagged" is answered by the conditions that fired and the
    thresholds they crossed, not by the fact that somebody raised it. The
    watchlist is one of the conditions.
    """
    del kwargs
    arguments = {"customer_id": customer_id, "period": period}
    if not customer_id:
        return _refusal("fetch_early_warning_evidence", arguments,
                        "name a borrower by customer_id.")
    if not principal.may(READ_DATA):
        return _refusal("fetch_early_warning_evidence", arguments,
                        f"A {principal.role.title()} may not read this.")
    started = time.perf_counter()
    try:
        from backend.corporate import service as corporate
        from backend.early_warning import signals as sg

        snapshot = corporate._load(corporate.SNAPSHOT)
        periods = sorted((str(p) for p in snapshot["period"].unique()),
                         key=sg._period_key)
        chosen = period or (periods[-1] if periods else "")
        index = periods.index(chosen) if chosen in periods else -1
        prior = periods[index - 1] if index > 0 else ""
        rows = snapshot[(snapshot["period"] == chosen)
                        & (snapshot["borrower_id"] == customer_id)]
        if rows.empty:
            return _refusal(
                "fetch_early_warning_evidence", arguments,
                f"{customer_id} is not on book at {chosen}.")
        before = snapshot[(snapshot["period"] == prior)
                          & (snapshot["borrower_id"] == customer_id)]
        standing = sg.stand(
            rows.iloc[0].to_dict(),
            before.iloc[0].to_dict() if not before.empty else {},
            borrower_id=customer_id, period=chosen, previous_period=prior)
    except Exception as e:  # noqa: BLE001
        logger.warning("Early-warning evidence failed: %s", e)
        return _refusal("fetch_early_warning_evidence", arguments,
                        f"that evidence could not be gathered: {_why(e)}")

    out = [{"signal": o.signal, "family": o.family, "condition": o.label,
            "value": _plain(o.value), "previous": _plain(o.previous),
            "threshold": o.threshold, "lifecycle": o.lifecycle,
            "severity": o.severity, "booked_accounting": o.booked_accounting}
           for o in standing.fired]
    return Observation(
        tool="fetch_early_warning_evidence", arguments=arguments,
        rows=out[:safety.MAX_ROWS_TO_MODEL], total_rows=len(out),
        columns=["signal", "family", "condition", "value", "threshold",
                 "lifecycle", "severity"],
        datasets=["corporate_borrower_360"], period=standing.period,
        purpose=(f"{standing.sentence()} "
                 f"{len(standing.cured)} condition(s) have cured; "
                 f"{len(standing.untested)} could not be tested here."),
        duration_ms=int((time.perf_counter() - started) * 1000))


def fetch_covenant_evidence(principal: Principal, customer_id: str = "",
                            period: str = "", **kwargs: Any) -> Observation:
    """One borrower's covenant position, test by test. §32."""
    del kwargs
    return _reading_tool("fetch_covenant_evidence", principal,
                         customer_id=customer_id, period=period)


def fetch_collateral_evidence(principal: Principal, customer_id: str = "",
                              period: str = "", **kwargs: Any) -> Observation:
    """One borrower's security, asset by asset. §33."""
    del kwargs
    return _reading_tool("fetch_collateral_evidence", principal,
                         customer_id=customer_id, period=period)


def fetch_external_intelligence(principal: Principal, customer_id: str = "",
                                period: str = "",
                                **kwargs: Any) -> Observation:
    """What the credit file says about one borrower, in its own words. §31."""
    del kwargs
    return _reading_tool("fetch_external_intelligence", principal,
                         customer_id=customer_id, period=period)


# ---------------------------------------------------------------------------
# The four domain readings, as tools
# ---------------------------------------------------------------------------
#
# These four used to return raw rows and leave the model to work out what they
# meant. That is exactly the arrangement §30-§33 exist to end: a model reading
# `stage = 2, sicr_flag = true` and writing "this borrower is expected to
# migrate to stage 2" is not misreading the data, it is doing the only thing
# available to it. The reader supplies the meaning - booked, not predicted;
# eligible value, not market value; no memo, not no news - and the tool passes
# that meaning through rather than re-deriving it.
#
# One consequence worth stating: the analyst and the Early Warning screen now
# answer "why was this flagged" from the same module. Two paths that composed
# the same evidence separately would eventually word it differently, and the
# one a client saw would be whichever they happened to open.

#: Which reader answers which tool, and what a caller is asking for.
READINGS: dict[str, tuple[str, str]] = {
    "fetch_ifrs9_evidence": (
        "ifrs9",
        "the booked IFRS 9 position and the trigger behind it - a "
        "classification that has happened, never a forecast of one"),
    "fetch_covenant_evidence": (
        "covenant",
        "each covenant tested individually, with its headroom and the age of "
        "the statements it was tested on"),
    "fetch_collateral_evidence": (
        "collateral",
        "security valued twice over - market value and post-haircut eligible "
        "value - because only the second one covers exposure"),
    "fetch_external_intelligence": (
        "external",
        "what people wrote about this borrower, as evidence somebody "
        "recorded rather than as a measurement"),
}


def _reading_tool(name: str, principal: Principal, *, customer_id: str,
                  period: str) -> Observation:
    arguments = {"customer_id": customer_id, "period": period}
    if not customer_id:
        return _refusal(name, arguments, "name a borrower by customer_id.")
    if not principal.may(READ_DATA):
        return _refusal(name, arguments,
                        f"A {principal.role.title()} may not read this.")
    domain, purpose = READINGS[name]
    started = time.perf_counter()
    try:
        from backend.api.routers.domain_intelligence import READERS

        module = READERS[domain]
        if module.DATASET not in _visible(principal):
            return _refusal(
                name, arguments,
                f"This deployment has no {module.DATASET}, so {purpose} "
                "cannot be supplied. Answer on the evidence that does exist "
                "and say this one is unavailable.")
        reading = module.read(customer_id, period)
    except Exception as e:  # noqa: BLE001
        logger.warning("%s failed: %s", name, e)
        return _refusal(name, arguments,
                        f"that evidence could not be gathered: {_why(e)}")

    rows = [
        {"finding": f.label, "means": f.means, "severity": f.severity,
         "value": _plain(f.value), "previous": _plain(f.previous),
         "threshold": _plain(f.threshold), "field": f.field_name,
         "booked_accounting": f.booked_accounting}
        for f in reading.findings
    ]
    said = reading.sentence()
    if reading.missing:
        # Carried into `purpose` rather than dropped: what could NOT be read
        # is the half of the evidence a model will otherwise fill in for
        # itself, and it fills it in optimistically.
        said += " " + " ".join(m.why for m in reading.missing)
    return Observation(
        tool=name, arguments=arguments,
        rows=rows[:safety.MAX_ROWS_TO_MODEL], total_rows=len(rows),
        columns=["finding", "means", "severity", "value", "threshold",
                 "field", "booked_accounting"],
        datasets=[module.DATASET], period=reading.period,
        purpose=f"{purpose}. {said}",
        duration_ms=int((time.perf_counter() - started) * 1000))


def run_governed_analysis(principal: Principal, analysis: str = "",
                          parameters: dict[str, Any] | None = None,
                          **_: Any) -> Observation:
    """One of the certified analyses, by name.

    The certified library is not the ONLY way to answer a question any more —
    that constraint is what §2 removes — but a certified analysis carries a
    review somebody signed, and where one fits the question exactly it is the
    better answer.
    """
    arguments = {"analysis": analysis, "parameters": parameters or {}}
    if not principal.may(RUN_ANALYSIS):
        return _refusal("run_governed_analysis", arguments,
                        f"A {principal.role.title()} may not run an analysis.")
    try:
        from backend.engine.registry import get_analysis, list_analyses
    except Exception as e:  # noqa: BLE001
        logger.debug("No analysis registry: %s", e)
        return _refusal("run_governed_analysis", arguments,
                        "No certified analysis library is available here.")
    try:
        definition = get_analysis(analysis)
    except Exception:  # noqa: BLE001 - an unknown name is a normal refusal
        names = sorted(a.id for a in list_analyses())[:20]
        return _refusal(
            "run_governed_analysis", arguments,
            f"'{analysis}' is not a certified analysis. Available: "
            f"{', '.join(names)}.")
    started = time.perf_counter()
    try:
        result = definition.run(**(parameters or {}))
    except Exception as e:  # noqa: BLE001
        return _refusal("run_governed_analysis", arguments,
                        f"that analysis could not be run: {_why(e)}")
    rows = result.get("rows") if isinstance(result, dict) else []
    rows = [{str(k): _plain(v) for k, v in row.items()}
            for row in (rows or [])]
    return Observation(
        tool="run_governed_analysis", arguments=arguments,
        rows=rows[:safety.MAX_ROWS_TO_MODEL], total_rows=len(rows),
        columns=list(rows[0]) if rows else [],
        purpose=f"the certified analysis '{analysis}'",
        duration_ms=int((time.perf_counter() - started) * 1000))


def run_stress_analysis(principal: Principal, scenario: str = "",
                        sector: str = "", **_: Any) -> Observation:
    """A governed stress scenario over the book."""
    arguments = {"scenario": scenario, "sector": sector}
    if not principal.may(RUN_ANALYSIS):
        return _refusal("run_stress_analysis", arguments,
                        f"A {principal.role.title()} may not run a stress.")
    parameters = {"scenario": scenario or "moderate"}
    if sector:
        parameters["sector"] = sector
    found = run_governed_analysis(principal, analysis="stress_scenario_basic",
                                  parameters=parameters)
    found.tool = "run_stress_analysis"
    found.arguments = arguments
    if not found.refused:
        found.purpose = f"the '{parameters['scenario']}' stress scenario"
    return found


def fetch_trace_evidence(principal: Principal, run_id: str = "",
                         **_: Any) -> Observation:
    """What a previous run actually did — its plan, datasets and result shape."""
    del principal
    arguments = {"run_id": run_id}
    try:
        from backend.db.engine import get_session
        from backend.trace import store as trace_store

        with get_session() as session:
            found = trace_store.load(session, run_id)
    except Exception as e:  # noqa: BLE001
        logger.debug("Trace lookup failed: %s", e)
        found = None
    if not found:
        return _refusal("fetch_trace_evidence", arguments,
                        f"No stored Trace was found for run '{run_id}'.")
    payload = found if isinstance(found, dict) else found.to_dict()
    rows = [{"run_id": run_id,
             "nodes": len(payload.get("nodes") or []),
             "datasets": ", ".join(payload.get("datasets") or []),
             "question": payload.get("question") or ""}]
    return Observation(
        tool="fetch_trace_evidence", arguments=arguments, rows=rows,
        total_rows=1, columns=list(rows[0]),
        purpose="what a previous run did, from its stored Trace")


# --------------------------------------------------------------- the registry

REGISTRY: tuple[Tool, ...] = (
    # ---- discovery: free, because a model that cannot look cannot compose
    Tool("list_data_domains",
         "The governed business domains and how many datasets each holds.",
         READ_METADATA, {}, (), list_data_domains, discovery=True),
    Tool("list_datasets",
         "The governed datasets, optionally within one domain.",
         READ_METADATA, {"domain": "a domain name, or empty for all"},
         (), list_datasets, discovery=True),
    Tool("describe_domain", "The datasets inside one business domain.",
         READ_METADATA, {"domain": "the domain name"}, ("domain",),
         describe_domain, discovery=True),
    Tool("describe_dataset",
         "What one row of a dataset represents, and over what periods.",
         READ_METADATA, {"dataset": "the governed dataset name"},
         ("dataset",), describe_dataset, discovery=True),
    Tool("get_data_dictionary",
         "Every field of a dataset, with its meaning, type and unit.",
         READ_METADATA,
         {"dataset": "the governed dataset name",
          "contains": "optional: only fields whose name or meaning contains this"},
         ("dataset",), get_data_dictionary, discovery=True),
    Tool("get_available_measures",
         "The numeric measures a dataset carries.", READ_METADATA,
         {"dataset": "the governed dataset name"}, ("dataset",),
         get_available_measures, discovery=True),
    Tool("get_available_dimensions",
         "The fields a dataset can be grouped or filtered by.", READ_METADATA,
         {"dataset": "the governed dataset name"}, ("dataset",),
         get_available_dimensions, discovery=True),
    Tool("get_dataset_periods",
         "The reporting periods a dataset actually holds.", READ_METADATA,
         {"dataset": "the governed dataset name"}, ("dataset",),
         get_dataset_periods, discovery=True),
    Tool("get_relationships",
         "The declared joins between datasets. A join not listed here cannot "
         "be made.", READ_METADATA,
         {"dataset": "optional: only relationships touching this dataset"},
         (), get_relationships, discovery=True),
    Tool("get_metric_definition",
         "Where a named business measure lives, and which candidate is the "
         "governed default.", READ_METADATA,
         {"metric": "what a credit officer calls it, e.g. 'utilisation'"},
         ("metric",), get_metric_definition, discovery=True),
    Tool("get_threshold_definition",
         "The governed thresholds, their values, and who owns them.",
         READ_METADATA, {"name": "optional: a threshold name"}, (),
         get_threshold_definition, discovery=True),
    Tool("get_model_definition",
         "The registered models and their governance state.", READ_METADATA,
         {"model": "optional: a model name"}, (), get_model_definition,
         discovery=True),
    Tool("get_policy_definition",
         "The governed limits and where each one came from.", READ_METADATA,
         {"policy": "optional: a policy or limit name"}, (),
         get_policy_definition, discovery=True),

    # ---- analysis
    Tool("query_dataset",
         "Rows from one governed dataset, filtered and ordered.",
         RUN_ANALYSIS,
         {"dataset": "the governed dataset name",
          "columns": "list of field names to return",
          "where": "list of {field, op, value}; op is eq/ne/gt/gte/lt/lte/in/"
                   "contains",
          "period": "a reporting period, e.g. 'Q2 2026'; empty means latest",
          "order_by": "a field to sort by",
          "descending": "true for largest first",
          "limit": "how many rows"},
         ("dataset",), query_dataset),
    Tool("aggregate_dataset",
         "One row per group, with sums, averages, counts or medians over it.",
         RUN_ANALYSIS,
         {"dataset": "the governed dataset name",
          "group_by": "list of fields to group by",
          "measures": "list of {function, field, as}; function is sum/avg/min/"
                      "max/count/count_distinct/median",
          "where": "list of {field, op, value}",
          "period": "a reporting period; empty means latest",
          "limit": "how many groups"},
         ("dataset",), aggregate_dataset),
    Tool("rank_entities",
         "Borrowers, facilities or sectors ordered highest or lowest on one "
         "measure. This is what most credit questions actually are.",
         RUN_ANALYSIS,
         {"dataset": "the governed dataset name",
          "entity": "the field identifying what is being ranked",
          "measure": "the field being ranked on",
          "function": "sum/avg/max/min/count",
          "where": "list of {field, op, value}",
          "period": "a reporting period; empty means latest",
          "top": "how many to return",
          "ascending": "true for the lowest rather than the highest"},
         ("dataset", "entity", "measure"), rank_entities),
    Tool("compare_periods",
         "The same measure at two reporting periods, and the movement.",
         RUN_ANALYSIS,
         {"dataset": "the governed dataset name",
          "entity": "the field identifying each row",
          "measure": "the field being compared",
          "function": "sum/avg/max/min",
          "from_period": "the opening period; empty means the previous one",
          "to_period": "the closing period; empty means the latest",
          "top": "how many rows"},
         ("dataset", "entity", "measure"), compare_periods),
    Tool("join_governed_datasets",
         "Two datasets joined on the DECLARED relationship between them. "
         "Datasets with no declared relationship cannot be joined.",
         RUN_ANALYSIS,
         {"left": "the first dataset", "right": "the second dataset",
          "columns": "fields to return from either side",
          "where": "list of {field, op, value} over the left dataset",
          "period": "a reporting period; empty means latest",
          "limit": "how many rows"},
         ("left", "right"), join_governed_datasets),
    Tool("run_governed_analysis",
         "One of the certified analyses, by name.", RUN_ANALYSIS,
         {"analysis": "the certified analysis id",
          "parameters": "its parameters, as an object"},
         ("analysis",), run_governed_analysis),
    Tool("run_stress_analysis",
         "A governed stress scenario over the book.", RUN_ANALYSIS,
         {"scenario": "the scenario name, e.g. 'moderate'",
          "sector": "optional: restrict to one sector"},
         (), run_stress_analysis),

    # ---- evidence
    Tool("fetch_borrower_360",
         "The whole governed position for one borrower.", READ_DATA,
         {"customer_id": "the borrower's customer id",
          "borrower_name": "or the borrower's name",
          "period": "a reporting period; empty means latest"},
         (), fetch_borrower_360),
    Tool("fetch_group_exposure",
         "The connected group a borrower sits in, and its exposure.",
         READ_DATA, {"customer_id": "the borrower's customer id",
                     "period": "a reporting period"}, (), fetch_group_exposure),
    Tool("fetch_ifrs9_evidence",
         "Stage, PD, ECL and what moved them.", READ_DATA,
         {"customer_id": "the borrower's customer id",
          "period": "a reporting period"}, (), fetch_ifrs9_evidence),
    Tool("fetch_early_warning_evidence",
         "Which governed early-warning conditions fire for a borrower, the "
         "threshold each one crossed, and whether it is new, persisting, "
         "worsening or improving.", READ_DATA,
         {"customer_id": "the borrower's customer id",
          "period": "a reporting period; empty means latest"},
         ("customer_id",), fetch_early_warning_evidence),
    Tool("fetch_covenant_evidence",
         "Covenant tests, headroom and breaches.", READ_DATA,
         {"customer_id": "the borrower's customer id",
          "period": "a reporting period"}, (), fetch_covenant_evidence),
    Tool("fetch_collateral_evidence",
         "Collateral values — market, net realisable and post-haircut, which "
         "are three different numbers.", READ_DATA,
         {"customer_id": "the borrower's customer id",
          "period": "a reporting period"}, (), fetch_collateral_evidence),
    Tool("fetch_external_intelligence",
         "Events observed outside the bank's own behavioural data.",
         READ_DATA, {"customer_id": "the borrower's customer id",
                     "period": "a reporting period"}, (),
         fetch_external_intelligence),
    Tool("fetch_trace_evidence",
         "What a previous run did, from its stored Trace.", READ_METADATA,
         {"run_id": "the run id"}, ("run_id",), fetch_trace_evidence,
         discovery=True),
)

BY_NAME: dict[str, Tool] = {tool.name: tool for tool in REGISTRY}


def describe_all(principal: Principal) -> list[dict[str, Any]]:
    """The tools this principal may use, as the model is shown them.

    A tool the principal may not use is ABSENT, not listed-and-refused. A
    model told a capability exists will spend turns trying to reach it, and
    the refusal itself would leak what the role cannot do.
    """
    return [tool.describe() for tool in REGISTRY
            if principal.may(tool.capability)]


def call(principal: Principal, name: str,
         arguments: dict[str, Any] | None = None) -> Observation:
    """Run one governed tool, under every check in `safety`. §4.

    Never raises for a refusal. The loop needs to SHOW the model what happened
    so it can choose differently, and an exception here would end an
    investigation that has a perfectly good alternative one step away.
    """
    arguments = dict(arguments or {})
    tool = BY_NAME.get(name)
    if tool is None:
        return _refusal(
            name, arguments,
            f"'{name}' is not a governed tool. Available: "
            f"{', '.join(sorted(t.name for t in REGISTRY if principal.may(t.capability)))}.")
    try:
        safety.check_permission(principal, tool.capability, tool.name)
    except Refused as e:
        return _refusal(name, arguments, str(e))
    missing = [a for a in tool.required if not arguments.get(a)]
    if missing:
        return _refusal(
            name, arguments,
            f"{name} needs {', '.join(missing)}. It takes: "
            f"{', '.join(tool.arguments)}.")
    for value in arguments.values():
        if isinstance(value, str):
            try:
                safety.refuse_writes(value)
            except Refused as e:
                return _refusal(name, arguments, str(e))
    started = time.perf_counter()
    try:
        observation = tool.handler(principal, **arguments)  # type: ignore[misc]
    except Refused as e:
        return _refusal(name, arguments, str(e))
    except TypeError as e:
        return _refusal(name, arguments,
                        f"{name} does not take those arguments. It takes: "
                        f"{', '.join(tool.arguments)}. ({e})")
    except Exception as e:  # noqa: BLE001 - a tool failure is evidence
        logger.warning("Tool %s failed: %s", name, e)
        return _refusal(name, arguments, f"{name} could not run: {_why(e)}")
    if not observation.duration_ms:
        observation.duration_ms = int((time.perf_counter() - started) * 1000)
    return observation
