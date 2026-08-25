"""What identifies one execution.

A plan fingerprint answers "is this the same computation". It is not enough to
answer "should this produce the same numbers", because the same computation run
against a restated dataset or a re-declared join gives a different answer and is
entitled to. A reviewer looking at two runs nine months apart needs to tell
those two cases apart without reading the SQL.

So a run carries four hashes, each over one thing:

``plan``
    The IR: operations, inputs, parameters, output. Labels and prose excluded,
    because a re-worded label is the same computation.
``data``
    Every dataset read, at the version it was read at, with the periods it was
    read for.
``relationships``
    Every governed relationship the joins walked, at the version that was
    active when they ran. A steward re-declaring a cardinality changes this
    without touching the plan, which is exactly the case a plan hash alone
    cannot see.
``parameters``
    The bound values: periods, thresholds, filter operands. Held separately so
    "the same analysis at a different quarter" is visible as such rather than
    as an unrelated run.

``run`` is the hash of those four. Two runs sharing it computed the same thing
from the same data under the same relationship model, and are expected to agree
to the digit; two runs differing in exactly one of them say which one.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from backend.runtime.ir import AnalyticalPlan, OpType

#: Short enough to read aloud, long enough that a collision is not a practical
#: concern for the number of runs a bank will ever record.
DIGEST = 16


def _hash(payload: Any) -> str:
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:DIGEST]


def dataset_versions(plan: AnalyticalPlan) -> list[dict[str, Any]]:
    """Every dataset the plan reads, at the version the catalogue declares.

    A dataset the catalogue cannot resolve is recorded as unknown rather than
    skipped: a missing version is a fact about the run, and dropping it would
    let two different reads hash the same.
    """
    from backend.data_access.catalog import get_catalog

    catalog = get_catalog()
    periods: dict[str, set[str]] = {}
    for operation in plan.operations:
        if operation.op is not OpType.SCAN:
            continue
        name = str(operation.params.get("dataset") or "")
        if not name:
            continue
        period = operation.params.get("period")
        periods.setdefault(name, set())
        if period:
            periods[name].add(str(period))

    out: list[dict[str, Any]] = []
    for name in sorted(periods):
        try:
            spec = catalog.dataset(name)
            version = spec.version
            origin = spec.origin
        except Exception:
            version, origin = "unknown", "unknown"
        out.append({"dataset": name, "version": version, "origin": origin,
                    "periods": sorted(periods[name])})
    return out


def relationship_versions(joins: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every governed relationship the joins walked, at the version used.

    A join with no relationship behind it — the opening-to-closing self-join a
    movement analysis makes — is excluded, because it is not something a
    steward can re-declare.
    """
    seen: dict[int, dict[str, Any]] = {}
    for join in joins or []:
        identifier = join.get("relationship_id")
        if identifier is None:
            continue
        seen[int(identifier)] = {
            "relationship_id": int(identifier),
            "version": join.get("relationship_version"),
            "cardinality": join.get("cardinality"),
        }
    return [seen[key] for key in sorted(seen)]


def parameters(plan: AnalyticalPlan) -> dict[str, Any]:
    """The bound values, apart from the shape that consumed them.

    Periods, filter operands and any threshold a step carries. Two runs of one
    analysis at different quarters differ here and nowhere else, which is the
    distinction a reviewer is usually making.
    """
    # Which step reads which period, not merely which periods were read: an
    # analysis with its opening and closing quarters the wrong way round reads
    # the same two periods and means the opposite thing.
    periods: list[dict[str, Any]] = []
    operands: list[Any] = []
    for operation in sorted(plan.operations, key=lambda o: o.id):
        period = operation.params.get("period")
        if period:
            periods.append({"step": operation.id, "period": str(period)})
        for key in ("periods", "opening_period", "closing_period"):
            value = operation.params.get(key)
            if isinstance(value, list):
                periods.append({"step": operation.id, key: [str(v) for v in value]})
            elif value:
                periods.append({"step": operation.id, key: str(value)})
        for condition in operation.params.get("where") or []:
            if isinstance(condition, dict) and "value" in condition:
                operands.append({"step": operation.id,
                                 "column": condition.get("column"),
                                 "op": condition.get("op"),
                                 "value": condition.get("value")})
        for key in ("top", "limit", "threshold", "min_rows"):
            if key in operation.params:
                operands.append({"step": operation.id, key: operation.params[key]})
    return {"periods": periods, "operands": operands}


def fingerprint(plan: AnalyticalPlan, *,
                joins: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """The four hashes and the one that binds them.

    Called after execution rather than before, because the relationship
    versions are only known once the joins have run — a plan that names a path
    and a plan that walked it are the same IR, and it is the walking that binds
    a version.
    """
    datasets = dataset_versions(plan)
    relationships = relationship_versions(joins or [])
    params = parameters(plan)

    parts = {
        "plan": plan.fingerprint() if plan.operations else "",
        "data": _hash(datasets),
        "relationships": _hash(relationships),
        "parameters": _hash(params),
    }
    return {
        **parts,
        "run": _hash(parts),
        "datasets": datasets,
        "relationships_used": relationships,
        "parameters_used": params,
    }


__all__ = ["DIGEST", "dataset_versions", "fingerprint", "parameters",
           "relationship_versions"]
