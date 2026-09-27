"""
A scripted analyst for the DRY RUN and the fixtures. Never used live.

It stands in for Opus so the whole harness -- sequencing, threads,
clarifications, capture, evaluation, reports -- can be proven without a paid
call. It writes SQL from the case's ORACLE spec, which is exactly what a live
analyst is never given; that is the point of a dry run: when the answer is
known, a failure is the harness's, not the model's.

Everything downstream of the provider is the real product: the route, the
worker, the validator, the SQL executor, the finalizer, the store.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from typing import Any

from cert import oracles as o
from cert.paths import ROOT


def _frozen_test_helpers():
    """The frozen suite's scripted-provider helpers, loaded by PATH under a unique
    name so no other `conftest` module on sys.path can be picked up instead."""
    name = "cockpit_v4_frozen_conftest"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, ROOT / "tests" / "cockpit_v4" / "conftest.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_h = _frozen_test_helpers()
ScriptedProvider, ScriptedResult = _h.ScriptedProvider, _h.ScriptedResult
final, intent, tool_call = _h.final, _h.intent, _h.tool_call

UNIT = {"amount": "SAR million", "count": "count", "ratio": "ratio", "pct_value": "percent",
        "pct_change": "ratio", "pp_change": "ratio"}


def _lit(v: Any) -> str:
    return f"'{v}'" if isinstance(v, str) else str(v)


def _where(domain: str, period: str, filters: dict[str, Any] | None) -> str:
    parts = [f"{o.PERIOD_COL[domain]} = '{period}'"]
    for col, val in (filters or {}).items():
        if isinstance(val, (list, tuple)):
            parts.append(f"{col} IN ({', '.join(_lit(x) for x in val)})")
        else:
            parts.append(f"{col} = {_lit(val)}")
    return " AND ".join(parts)


def sql_for(spec: dict[str, Any], domain: str) -> list[str]:
    """SQL statements (one per step) that answer the spec correctly."""
    fn = spec.get("fn")
    t = o.FACT_TABLE[domain]
    m = o.metric_sql(domain)
    if fn == "scalar":
        p = o.resolve_period(domain, spec.get("period", "latest"))
        sel = ", ".join(f"{m[x][0]} AS {x}" for x in spec["metrics"])
        return [f"SELECT {sel} FROM {t} WHERE {_where(domain, p, spec.get('filters'))}"]
    if fn == "by_dim":
        dims = spec["dim"] if isinstance(spec["dim"], list) else [spec["dim"]]
        p = o.resolve_period(domain, spec.get("period", "latest"))
        metrics = list(dict.fromkeys(spec["metrics"] + ([spec["rank_by"]] if spec.get("rank_by") else [])))
        sel = ", ".join(f"{m[x][0]} AS {x}" for x in metrics)
        order = spec.get("rank_by") or metrics[0]
        direction = "ASC" if spec.get("order") == "asc" else "DESC"
        limit = f" LIMIT {spec['topn']}" if spec.get("topn") else ""
        stmts = [f"SELECT {', '.join(dims)}, {sel} FROM {t} WHERE {_where(domain, p, spec.get('filters'))} "
                 f"GROUP BY {', '.join(dims)} ORDER BY {order} {direction}{limit}"]
        if spec.get("include_total"):
            stmts.append(f"SELECT {sel} FROM {t} WHERE {_where(domain, p, spec.get('filters'))}")
        return stmts
    if fn in ("change", "condition", "contribution"):
        dims = ([] if not spec.get("dim") else spec["dim"] if isinstance(spec["dim"], list) else [spec["dim"]])
        p1 = o.resolve_period(domain, spec.get("period", "latest"))
        p0 = o.resolve_period(domain, spec.get("base", "prev"))
        metrics = ([spec["metric"]] if "metric" in spec else sorted({c["metric"] for c in spec.get("conditions", [])})
                   or spec.get("metrics", []))
        dsel = ", ".join(dims)
        g = f" GROUP BY {dsel}" if dims else ""
        a_sel = ", ".join(f"{m[x][0]} AS {x}" for x in metrics)
        using = f" USING ({dsel})" if dims else " ON TRUE"
        cols = []
        for x in metrics:
            cols += [f"a.{x} AS {x}_latest", f"b.{x} AS {x}_base", f"a.{x} - b.{x} AS {x}_abs_change",
                     f"(a.{x} - b.{x}) / NULLIF(b.{x}, 0) AS {x}_pct_change"]
        head = (", ".join(f"a.{d}" for d in dims) + ", ") if dims else ""
        filt = spec.get("filters")
        sql = (f"WITH a AS (SELECT {dsel + ', ' if dims else ''}{a_sel} FROM {t} WHERE {_where(domain, p1, filt)}{g}), "
               f"b AS (SELECT {dsel + ', ' if dims else ''}{a_sel} FROM {t} WHERE {_where(domain, p0, filt)}{g}) "
               f"SELECT {head}{', '.join(cols)} FROM a LEFT JOIN b{using}")
        if fn == "contribution":
            x = metrics[0]
            sql = (f"WITH c AS ({sql}) SELECT *, {x}_abs_change / SUM({x}_abs_change) OVER () AS contribution_share, "
                   f"SUM({x}_abs_change) OVER () AS total_abs_change FROM c ORDER BY ABS({x}_abs_change) DESC")
        elif fn == "condition":
            conds = []
            for c in spec["conditions"]:
                col = f"{c['metric']}_{'abs_change' if c['field'] == 'abs' else 'pct_change'}"
                if c.get("compare_to"):
                    other = f"{c['compare_to']}_{'abs_change' if c['field'] == 'abs' else 'pct_change'}"
                    conds.append(f"{col} {c['op']} {other}")
                else:
                    conds.append(f"{col} {c['op']} {c.get('value', 0)}")
            sql = f"WITH c AS ({sql}) SELECT * FROM c WHERE {' AND '.join(conds)}"
        elif spec.get("keys"):
            dim = dims[0]
            keys = ", ".join(_lit(k[dim]) for k in spec["keys"])
            sql = f"WITH c AS ({sql}) SELECT * FROM c WHERE {dim} IN ({keys})"
            if spec.get("topn"):
                rank = {"abs": f"{metrics[0]}_abs_change", "pct": f"{metrics[0]}_pct_change"}.get(
                    spec.get("rank_by", ""), f"{metrics[0]}_latest")
                sql += f" ORDER BY {rank} DESC LIMIT {spec['topn']}"
        elif spec.get("topn") or spec.get("rank_by"):
            rank = {"abs": f"{metrics[0]}_abs_change", "pct": f"{metrics[0]}_pct_change",
                    "latest": f"{metrics[0]}_latest"}.get(spec.get("rank_by", "latest"))
            lim = f" LIMIT {spec['topn']}" if spec.get("topn") else ""
            sql = f"WITH c AS ({sql}) SELECT * FROM c ORDER BY {rank} DESC NULLS LAST{lim}"
        return [sql]
    if fn == "stock_rate":
        dims = [spec["dim"]] if spec.get("dim") else []
        p1 = o.resolve_period(domain, spec.get("period", "latest"))
        p0 = o.resolve_period(domain, spec.get("base", "prev"))
        dsel = ", ".join(dims)
        g = f" GROUP BY {dsel}" if dims else ""
        head = (dsel + ", ") if dims else ""
        using = f" USING ({dsel})" if dims else " ON TRUE"
        sql = (f"WITH a AS (SELECT {head}SUM(ead_sar_mn) AS ead, SUM(ecl_sar_mn) AS ecl FROM {t} "
               f"WHERE {_where(domain, p1, None)}{g}), b AS (SELECT {head}SUM(ead_sar_mn) AS ead, "
               f"SUM(ecl_sar_mn) AS ecl FROM {t} WHERE {_where(domain, p0, None)}{g}) "
               f"SELECT {(', '.join('a.' + d for d in dims) + ', ') if dims else ''}a.ecl - b.ecl AS ecl_change, "
               f"(a.ead - b.ead) * (b.ecl / b.ead) AS stock_effect, "
               f"(a.ecl / a.ead - b.ecl / b.ead) * a.ead AS rate_effect FROM a JOIN b{using} "
               f"ORDER BY ABS(a.ecl - b.ecl) DESC" + (f" LIMIT {spec['topn']}" if spec.get("topn") else ""))
        return [sql]
    if fn == "concentration":
        p = o.resolve_period(domain, spec.get("period", "latest"))
        dim, metric = spec["dim"], spec.get("metric", "ead")
        shares = ", ".join(f"SUM(CASE WHEN rn <= {n} THEN v ELSE 0 END) / MAX(tot) AS top{n}_share"
                           for n in spec["topn"])
        return [f"WITH g AS (SELECT {dim}, {m[metric][0]} AS v FROM {t} WHERE {_where(domain, p, spec.get('filters'))} "
                f"GROUP BY {dim}), r AS (SELECT v, ROW_NUMBER() OVER (ORDER BY v DESC) AS rn, "
                f"SUM(v) OVER () AS tot FROM g) SELECT {shares} FROM r"]
    if fn == "trend":
        dims = [spec["dim"]] if spec.get("dim") else []
        ps = o.periods(domain)[-int(spec.get("n_periods", 6)):]
        pc = o.PERIOD_COL[domain]
        where = f"{pc} IN ({', '.join(_lit(p) for p in ps)})"
        for col, val in (spec.get("filters") or {}).items():
            where += f" AND {col} = {_lit(val)}"
        if spec.get("keys"):
            d = dims[0]
            where += f" AND {d} IN ({', '.join(_lit(k[d]) for k in spec['keys'])})"
        sel = ", ".join(f"{m[x][0]} AS {x}" for x in spec["metrics"])
        grp = ", ".join([pc] + dims)
        return [f"SELECT {grp}, {sel} FROM {t} WHERE {where} GROUP BY {grp} ORDER BY {grp}"]
    if fn == "sql":
        custom = o.CUSTOM[spec["name"]]
        if custom.get("parts"):
            return [" ".join(o.CUSTOM[p]["sql"].split()) for p in custom["parts"]]
        return [" ".join(custom["sql"].split())]
    return []


def _execute_payload(question: str, sqls: list[str], domain: str) -> dict[str, Any]:
    period = o.resolve_period(domain, "latest")
    return {
        "intent": intent("DATA_ANALYSIS", "COCKPIT", understood=question, rationale="scripted dry run"),
        "objective": question[:300], "subquestions": [question[:300]],
        "scope": {"reporting_months": [period], "filters": {}},
        "metadata_receipt_ids": [], "fields_required": [],
        "expected_output_grain": "as queried", "expected_units": {},
        "steps": [{"step_id": f"s{i + 1}", "language": "sql", "code": sql, "parameters": {},
                   "purpose": question[:200], "input_artifact_ids": [], "depends_on_step_ids": []}
                  for i, sql in enumerate(sqls)],
        "repair_of_submission_id": ""}


def bind_claims(ref: o.Reference, steps: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Claims for every required fact, bound to the executed cells."""
    from cert.evaluate import _row_strings, compare, key_matches, to_float

    claims, tables = [], []
    for step in steps:
        if step.get("artifact_id"):
            tables.append({"title": step.get("step_id", "result"), "artifact_id": step["artifact_id"],
                           "columns": list(step.get("columns") or [])})
    for n, fact in enumerate(ref.required()):
        bound = None
        for step in steps:
            for i, row in enumerate(step.get("preview") or []):
                strings, _ = _row_strings(row)
                if not key_matches(fact.key, strings):
                    continue
                for col, value in row.items():
                    if compare(fact.value, to_float(value) if not isinstance(value, str) else None, fact.kind) == "EXACT":
                        bound = {"artifact_id": step["artifact_id"], "row_key": f"r{i}", "column_id": col}
                        break
                if bound:
                    break
            if bound:
                break
        if bound:
            claims.append({"claim_id": f"c{n}", "unit": UNIT.get(fact.kind, "ratio"), "evidence": bound})
    return claims, tables


def analyst_for(case: dict[str, Any], ref: o.Reference | None, *, domain: str,
                behaviour: str) -> ScriptedProvider:
    """A provider script that answers `case` the way the oracle says is correct."""
    question = case.get("_asked_question") or case["question"]
    if behaviour == "CLARIFY":
        return ScriptedProvider([ScriptedResult(tool_calls=[tool_call("finalize_response", final(
            intent=intent("DATA_ANALYSIS", "COCKPIT", ambiguities=["which measure is meant"]),
            disposition="clarification", narrative="Which measure do you mean?",
            clarification_question="Which measure do you mean?",
            clarification_options=["EAD", "Limit", "Drawn balance"]))])])
    if behaviour in ("DECLINE", "UNSUPPORTED"):
        return ScriptedProvider([ScriptedResult(tool_calls=[tool_call("finalize_response", final(
            intent=intent("PRODUCT_HELP", "COCKPIT"), disposition="unsupported",
            narrative="CreditProbe cannot answer this from the governed data."))])])
    spec = case.get("_spec") or case.get("oracle") or {"fn": "none"}
    sqls = sql_for(spec, domain) if spec.get("fn") not in (None, "none") else []
    if not sqls:
        return ScriptedProvider([ScriptedResult(tool_calls=[tool_call("finalize_response", final(
            intent=intent("PRODUCT_HELP", "COCKPIT"), disposition="answer",
            narrative="Here is a summary based on the governed evidence already shown."))])])

    def answer(messages):
        body = json.loads(messages[-1]["content"][0]["content"])
        steps = body.get("steps") or []
        claims, tables = bind_claims(ref, steps) if ref is not None else ([], [])
        narrative = "Scripted dry-run answer. " + " ".join(f"{{{{claim.{c['claim_id']}}}}}" for c in claims)
        return ScriptedResult(tool_calls=[tool_call("finalize_response", final(
            intent=intent("DATA_ANALYSIS", "COCKPIT"), disposition="answer", narrative=narrative,
            numeric_claims=claims, tables=tables))])

    return ScriptedProvider([
        ScriptedResult(tool_calls=[tool_call("execute_analysis", _execute_payload(question, sqls, domain), "tu-x")]),
        answer])
