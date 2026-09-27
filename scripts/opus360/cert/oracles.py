"""
Independent oracles. CreditProbe does not mark its own homework.

Every expected value here is computed by the harness's OWN SQL, in its own
DuckDB connection, directly over the governed Parquet files of the pinned
releases. No CreditProbe module computes, formats, or selects any oracle
value. The only thing shared with the product is the data itself, and the
data's integrity is checked independently (`release_integrity`), by
re-implementing the fingerprint over the published bytes.

An oracle is declared in the question bank as a spec, e.g.

    {"fn": "by_dim", "dim": "sector", "metrics": ["ead_s2"],
     "period": "latest", "rank_by": "ead_s2", "order": "desc", "topn": 3}

and `compute(spec, domain)` returns a `Reference`: the facts a correct
answer must publish (`required`), the facts it may publish (`universe`),
and plausible WRONG values (`distractors`) that let an evaluation say
"wrong period" or "wrong population" instead of just "wrong".
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from cert import APPROVED_RELEASES
from cert.paths import ROOT

ORACLE_VERSION = "opus360-oracles-1.0.0"

# ---- data access ------------------------------------------------------------

RELATIONS = {
    "corporate": ("corp_borrower_quarter", "corp_facility_quarter",
                  "corp_collateral_quarter", "corp_covenant_quarter"),
    "retail": ("retail_customer_month", "retail_account_month",
               "retail_behaviour_month", "retail_collateral_month"),
}
FACT_TABLE = {"corporate": "corp_facility_quarter", "retail": "retail_account_month"}
PERIOD_COL = {"corporate": "reporting_quarter", "retail": "reporting_month"}


def lake_root() -> Path:
    override = os.environ.get("OPUS360_LAKE_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    analytics = os.environ.get("DATA_ANALYTICS_DIR", "data/analytics")
    base = Path(analytics)
    if not base.is_absolute():
        base = ROOT / base
    return base.parent / "cockpit_v4_lake"


def release_dir(domain: str) -> Path:
    return lake_root() / APPROVED_RELEASES[domain]


def release_integrity(domain: str) -> dict[str, Any]:
    """Recompute the byte fingerprint independently and compare to the manifest."""
    rdir = release_dir(domain)
    manifest_path = rdir / "manifest.json"
    if not manifest_path.exists():
        return {"domain": domain, "release_id": APPROVED_RELEASES[domain],
                "present": False}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    digest = hashlib.sha256()
    for path in sorted(rdir.glob("*.parquet"), key=lambda p: p.name):
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    recomputed = digest.hexdigest()
    return {"domain": domain, "release_id": APPROVED_RELEASES[domain],
            "present": True,
            "manifest_fingerprint": manifest.get("release_fingerprint", ""),
            "recomputed_fingerprint": recomputed,
            "self_consistent": recomputed == manifest.get("release_fingerprint"),
            "latest_period": manifest.get("latest_period"),
            "periods": manifest.get("reporting_periods"),
            "built_with": manifest.get("built_with", {}),
            "row_counts": manifest.get("row_counts", {})}


_LOCAL = threading.local()


def connection():
    con = getattr(_LOCAL, "con", None)
    root = str(lake_root())
    if con is not None and getattr(_LOCAL, "root", "") == root:
        return con
    import duckdb

    con = duckdb.connect(database=":memory:")
    for domain, rels in RELATIONS.items():
        for rel in rels:
            path = release_dir(domain) / f"{rel}.parquet"
            if path.exists():
                con.execute(f"CREATE OR REPLACE VIEW {rel} AS SELECT * FROM "
                            f"read_parquet('{path.as_posix()}')")
    _LOCAL.con, _LOCAL.root = con, root
    return con


def query(sql: str, params: list[Any] | None = None) -> list[dict[str, Any]]:
    cur = connection().execute(sql, params or [])
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]


def periods(domain: str) -> list[str]:
    rows = query(f"SELECT DISTINCT {PERIOD_COL[domain]} AS p FROM {FACT_TABLE[domain]} ORDER BY 1")
    return [r["p"] for r in rows]


def resolve_period(domain: str, token: str) -> str:
    """'latest' | 'prev' | 'yoy' | 'minusN' | an explicit period."""
    ps = periods(domain)
    per_year = 4 if domain == "corporate" else 12
    if token in ("latest", "", None):
        return ps[-1]
    if token == "prev":
        return ps[-2]
    if token == "yoy":
        return ps[-1 - per_year]
    if isinstance(token, str) and token.startswith("minus"):
        return ps[-1 - int(token[5:])]
    if token in ps:
        return token
    raise ValueError(f"unknown period {token!r} for {domain}")


# ---- metric vocabulary -------------------------------------------------------

def _stage(col: str, k: int) -> str:
    return f"SUM(CASE WHEN stage={k} THEN {col} ELSE 0 END)"


#: name -> (SQL aggregate over the fact table, kind)
def metric_sql(domain: str) -> dict[str, tuple[str, str]]:
    m: dict[str, tuple[str, str]] = {
        "ead": ("SUM(ead_sar_mn)", "amount"),
        "ecl": ("SUM(ecl_sar_mn)", "amount"),
        "ecl_12m": ("SUM(ecl_12m_sar_mn)", "amount"),
        "ecl_lifetime": ("SUM(ecl_lifetime_sar_mn)", "amount"),
        "limit": ("SUM(limit_sar_mn)", "amount"),
        "n": ("COUNT(*)", "count"),
        "dpd30_ead": ("SUM(CASE WHEN dpd_days>=30 THEN ead_sar_mn ELSE 0 END)", "amount"),
        "dpd90_ead": ("SUM(CASE WHEN dpd_days>=90 THEN ead_sar_mn ELSE 0 END)", "amount"),
        "default_ead": ("SUM(CASE WHEN default_flag=1 THEN ead_sar_mn ELSE 0 END)", "amount"),
        "pd_w": ("SUM(pd_pit_12m*ead_sar_mn)/NULLIF(SUM(ead_sar_mn),0)", "ratio"),
        "lgd_w": ("SUM(lgd_pct*ead_sar_mn)/NULLIF(SUM(ead_sar_mn),0)", "pct_value"),
        "pd_avg": ("AVG(pd_pit_12m)", "ratio"),
        "coverage": ("SUM(ecl_sar_mn)/NULLIF(SUM(ead_sar_mn),0)", "ratio"),
        "coverage_rowavg": ("AVG(ecl_sar_mn/NULLIF(ead_sar_mn,0))", "ratio"),
        "dpd30_share": ("SUM(CASE WHEN dpd_days>=30 THEN ead_sar_mn ELSE 0 END)/NULLIF(SUM(ead_sar_mn),0)", "ratio"),
        "ecl_over_limit": ("SUM(ecl_sar_mn)/NULLIF(SUM(limit_sar_mn),0)", "ratio"),
    }
    for k in (1, 2, 3):
        m[f"ead_s{k}"] = (_stage("ead_sar_mn", k), "amount")
        m[f"ecl_s{k}"] = (_stage("ecl_sar_mn", k), "amount")
        m[f"ecl_12m_s{k}"] = (_stage("ecl_12m_sar_mn", k), "amount")
        m[f"n_s{k}"] = (f"SUM(CASE WHEN stage={k} THEN 1 ELSE 0 END)", "count")
        m[f"s{k}_share"] = (f"{_stage('ead_sar_mn', k)}/NULLIF(SUM(ead_sar_mn),0)", "ratio")
        m[f"coverage_s{k}"] = (f"{_stage('ecl_sar_mn', k)}/NULLIF({_stage('ead_sar_mn', k)},0)", "ratio")
    if domain == "corporate":
        m["drawn"] = ("SUM(drawn_sar_mn)", "amount")
        m["n_borrowers"] = ("COUNT(DISTINCT borrower_id)", "count")
    else:
        m["balance"] = ("SUM(balance_sar_mn)", "amount")
        m["n_customers"] = ("COUNT(DISTINCT customer_id)", "count")
    return m


#: Metrics every universe includes (claims are checked against these).
UNIVERSE_METRICS = ("ead", "ecl", "ead_s1", "ead_s2", "ead_s3", "ecl_s1", "ecl_s2",
                    "ecl_s3", "s1_share", "s2_share", "s3_share", "coverage",
                    "coverage_s2", "coverage_s3", "n", "n_s1", "n_s2", "n_s3",
                    "dpd30_ead", "dpd90_ead", "dpd30_share", "pd_w", "lgd_w",
                    "limit", "default_ead")

#: For a stage-filtered metric, its unfiltered counterpart (wrong population).
POPULATION_DISTRACTOR = {f"ead_s{k}": "ead" for k in (1, 2, 3)} | {
    f"ecl_s{k}": "ecl" for k in (1, 2, 3)} | {
    f"n_s{k}": "n" for k in (1, 2, 3)} | {"coverage_s2": "coverage", "coverage_s3": "coverage",
                                          "dpd90_ead": "dpd30_ead", "dpd30_ead": "dpd90_ead"}
#: For a ratio-of-sums metric, a mean-of-ratios counterpart (wrong method).
METHOD_DISTRACTOR = {"coverage": "coverage_rowavg", "pd_w": "pd_avg"}


# ---- reference objects --------------------------------------------------------

@dataclass
class Fact:
    fact_id: str
    key: dict[str, str]
    metric: str
    period: str
    value: float | None
    kind: str
    role: str = "universe"          # required | universe | distractor | member
    part: str = "value"             # value | base | abs_change | pct_change | share ...
    reason: str = ""                # for distractors

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Reference:
    domain: str
    spec: dict[str, Any]
    periods: list[str] = field(default_factory=list)
    population: str = ""
    facts: list[Fact] = field(default_factory=list)
    ranking: list[dict[str, str]] = field(default_factory=list)
    ranking_required: bool = False
    member_set: list[dict[str, str]] | None = None
    notes: list[str] = field(default_factory=list)
    oracle_version: str = ORACLE_VERSION

    def required(self) -> list[Fact]:
        return [f for f in self.facts if f.role == "required"]

    def to_dict(self) -> dict[str, Any]:
        return {"domain": self.domain, "spec": self.spec, "periods": self.periods,
                "population": self.population,
                "facts": [f.to_dict() for f in self.facts],
                "ranking": self.ranking, "ranking_required": self.ranking_required,
                "member_set": self.member_set, "notes": self.notes,
                "oracle_version": self.oracle_version}

    def sha256(self) -> str:
        return hashlib.sha256(json.dumps(self.to_dict(), sort_keys=True, default=str)
                              .encode("utf-8")).hexdigest()


def _num(v: Any) -> float | None:
    """A float normalised to 10 significant digits.

    DuckDB sums floats in parallel, so a join over sub-aggregates can differ in
    its last bits between processes. 10 significant digits (5e-11 relative) is
    far below every comparison tolerance and makes the frozen reference hash
    reproducible, which --resume depends on.
    """
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return float(f"{f:.10g}") if f == f else None


def _where(domain: str, period: str, filters: dict[str, Any] | None) -> tuple[str, list[Any]]:
    clauses = [f"{PERIOD_COL[domain]} = ?"]
    params: list[Any] = [period]
    for col, val in (filters or {}).items():
        if isinstance(val, (list, tuple)):
            clauses.append(f"{col} IN ({','.join('?' for _ in val)})")
            params.extend(val)
        else:
            clauses.append(f"{col} = ?")
            params.append(val)
    return " AND ".join(clauses), params


def grouped(domain: str, dims: list[str], metrics: list[str], period: str,
            filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    msql = metric_sql(domain)
    sel = ", ".join(f"{msql[m][0]} AS \"{m}\"" for m in metrics)
    where, params = _where(domain, period, filters)
    if dims:
        dcols = ", ".join(dims)
        sql = (f"SELECT {dcols}, {sel} FROM {FACT_TABLE[domain]} WHERE {where} "
               f"GROUP BY {dcols} ORDER BY {dcols}")
    else:
        sql = f"SELECT {sel} FROM {FACT_TABLE[domain]} WHERE {where}"
    return query(sql, params)


def _key(row: dict[str, Any], dims: list[str]) -> dict[str, str]:
    return {d: str(row[d]) for d in dims}


def _kid(key: dict[str, str]) -> str:
    return "|".join(f"{k}={v}" for k, v in sorted(key.items())) or "total"


# ---- the universe --------------------------------------------------------------

def add_universe(ref: Reference, dims: list[str], period_tokens: list[str],
                 filters: dict[str, Any] | None = None) -> None:
    """Every core metric, for the case's dims and periods, as 'universe' facts."""
    domain = ref.domain
    msql = metric_sql(domain)
    metrics = [m for m in UNIVERSE_METRICS if m in msql]
    seen = {(f.fact_id) for f in ref.facts}
    for tok in period_tokens:
        period = resolve_period(domain, tok)
        for group in ([], dims) if dims else ([],):
            for row in grouped(domain, list(group), metrics, period, filters):
                key = _key(row, list(group))
                for m in metrics:
                    fid = f"U:{_kid(key)}:{m}:{period}"
                    if fid in seen:
                        continue
                    seen.add(fid)
                    ref.facts.append(Fact(fid, key, m, period, _num(row[m]),
                                          msql[m][1], role="universe"))


def _add_distractors(ref: Reference, fact: Fact, dims: list[str],
                     filters: dict[str, Any] | None) -> None:
    domain = ref.domain
    msql = metric_sql(domain)
    candidates: list[tuple[str, str, str]] = []
    for tok in ("prev", "yoy", "latest"):
        try:
            p = resolve_period(domain, tok)
        except (ValueError, IndexError):
            continue
        if p != fact.period:
            candidates.append((fact.metric, p, "wrong_period"))
    if fact.metric in POPULATION_DISTRACTOR:
        candidates.append((POPULATION_DISTRACTOR[fact.metric], fact.period, "wrong_population"))
    if fact.metric in METHOD_DISTRACTOR:
        candidates.append((METHOD_DISTRACTOR[fact.metric], fact.period, "wrong_method"))
    for metric, period, reason in candidates:
        extra = dict(filters or {})
        extra.update(fact.key)
        rows = grouped(domain, [], [metric], period, extra)
        value = _num(rows[0][metric]) if rows else None
        if value is None or fact.value is None:
            continue
        if abs(value - fact.value) <= 1e-9 * max(1.0, abs(fact.value)):
            continue
        ref.facts.append(Fact(f"D:{fact.fact_id}:{reason}:{metric}:{period}", fact.key,
                              metric, period, value, msql[metric][1],
                              role="distractor", reason=reason))


# ---- oracle functions ------------------------------------------------------------

def _o_scalar(ref: Reference, spec: dict[str, Any]) -> None:
    domain = ref.domain
    period = resolve_period(domain, spec.get("period", "latest"))
    ref.periods = [period]
    msql = metric_sql(domain)
    rows = grouped(domain, [], spec["metrics"], period, spec.get("filters"))
    required = spec.get("required", spec["metrics"])
    for m in spec["metrics"]:
        role = "required" if m in required else "universe"
        fact = Fact(f"R:total:{m}:{period}", {}, m, period, _num(rows[0][m]), msql[m][1], role)
        ref.facts.append(fact)
        if role == "required":
            _add_distractors(ref, fact, [], spec.get("filters"))
    add_universe(ref, [], ["latest", "prev"], spec.get("filters"))


def _o_by_dim(ref: Reference, spec: dict[str, Any]) -> None:
    domain = ref.domain
    dims = spec["dim"] if isinstance(spec["dim"], list) else [spec["dim"]]
    period = resolve_period(domain, spec.get("period", "latest"))
    ref.periods = [period]
    msql = metric_sql(domain)
    metrics = spec["metrics"]
    rank_by = spec.get("rank_by") or metrics[0]
    all_metrics = list(dict.fromkeys(metrics + [rank_by]))
    rows = grouped(domain, dims, all_metrics, period, spec.get("filters"))
    rows = [r for r in rows if _num(r[rank_by]) is not None]
    reverse = spec.get("order", "desc") == "desc"
    rows.sort(key=lambda r: (_num(r[rank_by]) or 0.0), reverse=reverse)
    topn = spec.get("topn")
    chosen = rows[:topn] if topn else rows
    required_metrics = spec.get("required_metrics", metrics)
    for r in rows:
        key = _key(r, dims)
        in_scope = r in chosen
        for m in all_metrics:
            role = "required" if (in_scope and m in required_metrics) else "universe"
            fact = Fact(f"R:{_kid(key)}:{m}:{period}", key, m, period, _num(r[m]),
                        msql[m][1], role)
            ref.facts.append(fact)
            if role == "required":
                _add_distractors(ref, fact, dims, spec.get("filters"))
    ref.ranking = [_key(r, dims) for r in chosen]
    ref.ranking_required = bool(spec.get("ranking_required", bool(topn) or spec.get("rank_by")))
    if spec.get("include_total"):
        trow = grouped(domain, [], all_metrics, period, spec.get("filters"))[0]
        for m in metrics:
            ref.facts.append(Fact(f"R:total:{m}:{period}", {}, m, period, _num(trow[m]),
                                  msql[m][1], "required"))
    add_universe(ref, dims, ["latest", "prev"], spec.get("filters"))


def _change_rows(domain: str, dims: list[str], metric: str, p1: str, p0: str,
                 filters: dict[str, Any] | None) -> list[dict[str, Any]]:
    now = {_kid(_key(r, dims)): r for r in grouped(domain, dims, [metric], p1, filters)}
    base = {_kid(_key(r, dims)): r for r in grouped(domain, dims, [metric], p0, filters)}
    out = []
    for kid in sorted(set(now) | set(base)):
        r1, r0 = now.get(kid), base.get(kid)
        key = _key(r1 or r0, dims)
        v1 = _num(r1[metric]) if r1 else None
        v0 = _num(r0[metric]) if r0 else None
        abs_c = (v1 - v0) if (v1 is not None and v0 is not None) else None
        pct = (abs_c / v0) if (abs_c is not None and v0) else None
        out.append({"key": key, "latest": v1, "base": v0, "abs": abs_c, "pct": pct})
    return out


def _emit_change(ref: Reference, key: dict[str, str], metric: str, p1: str, p0: str,
                 row: dict[str, Any], kind: str, required_parts: list[str], in_scope: bool) -> None:
    ch_kind = "count" if kind == "count" else ("pp_change" if kind == "ratio" else "amount")
    parts = [("latest", row["latest"], kind, p1), ("base", row["base"], kind, p0),
             ("abs_change", row["abs"], ch_kind, f"{p1} vs {p0}"),
             ("pct_change", row["pct"], "pct_change", f"{p1} vs {p0}")]
    for part, value, k, per in parts:
        if value is None:
            continue
        role = "required" if (in_scope and part in required_parts) else "universe"
        ref.facts.append(Fact(f"R:{_kid(key)}:{metric}:{part}:{per}", key, metric, per,
                              value, k, role, part=part))


def _o_change(ref: Reference, spec: dict[str, Any]) -> None:
    domain = ref.domain
    dims = ([] if not spec.get("dim") else
            spec["dim"] if isinstance(spec["dim"], list) else [spec["dim"]])
    p1 = resolve_period(domain, spec.get("period", "latest"))
    p0 = resolve_period(domain, spec.get("base", "prev"))
    ref.periods = [p1, p0]
    msql = metric_sql(domain)
    required_parts = spec.get("parts", ["latest", "base", "abs_change", "pct_change"])
    metrics = spec["metrics"] if "metrics" in spec else [spec["metric"]]
    rank_metric = metrics[0]
    per_metric = {m: _change_rows(domain, dims, m, p1, p0, spec.get("filters")) for m in metrics}
    rows = per_metric[rank_metric]
    keys_filter = spec.get("keys")
    if keys_filter:
        wanted = [_kid(k) for k in keys_filter]
        rows = [r for r in rows if _kid(r["key"]) in wanted]
    rank_by = spec.get("rank_by", "latest")
    rank_field = {"latest": "latest", "abs": "abs", "pct": "pct", "base": "base"}[rank_by]
    reverse = spec.get("order", "desc") == "desc"
    ranked = [r for r in rows if r[rank_field] is not None]
    ranked.sort(key=lambda r: r[rank_field], reverse=reverse)
    topn = spec.get("topn")
    chosen = ranked[:topn] if topn else ranked
    chosen_ids = {_kid(r["key"]) for r in chosen}
    for m in metrics:
        for r in per_metric[m]:
            in_scope = _kid(r["key"]) in chosen_ids
            _emit_change(ref, r["key"], m, p1, p0, r, msql[m][1], required_parts, in_scope)
    ref.ranking = [r["key"] for r in chosen] if dims else []
    ref.ranking_required = bool(dims and spec.get("ranking_required", bool(topn)))
    add_universe(ref, dims, ["latest", "prev", spec.get("base", "prev")], spec.get("filters"))


def _o_condition(ref: Reference, spec: dict[str, Any]) -> None:
    """Keys satisfying every condition on changes, e.g. S2 up while EAD down."""
    domain = ref.domain
    dims = spec["dim"] if isinstance(spec["dim"], list) else [spec["dim"]]
    p1 = resolve_period(domain, spec.get("period", "latest"))
    p0 = resolve_period(domain, spec.get("base", "prev"))
    ref.periods = [p1, p0]
    msql = metric_sql(domain)
    metrics = sorted({c["metric"] for c in spec["conditions"]})
    per_metric = {m: {_kid(r["key"]): r for r in _change_rows(domain, dims, m, p1, p0, spec.get("filters"))}
                  for m in metrics}
    members = []
    for kid in sorted(per_metric[metrics[0]]):
        ok = True
        for cond in spec["conditions"]:
            if cond.get("compare_to"):
                a = per_metric[cond["metric"]].get(kid, {}).get(cond["field"])
                b = per_metric[cond["compare_to"]].get(kid, {}).get(cond["field"])
                if a is None or b is None or not (a > b if cond["op"] == ">" else a < b):
                    ok = False
            else:
                v = per_metric[cond["metric"]].get(kid, {}).get(cond["field"])
                t = cond.get("value", 0.0)
                if v is None or not (v > t if cond["op"] == ">" else v < t):
                    ok = False
        if ok:
            members.append(per_metric[metrics[0]][kid]["key"])
    ref.member_set = members
    member_ids = {_kid(k) for k in members}
    for m in metrics:
        for kid, r in per_metric[m].items():
            _emit_change(ref, r["key"], m, p1, p0, r, msql[m][1],
                         spec.get("parts", ["abs_change", "pct_change"]), kid in member_ids)
    for k in members:
        ref.facts.append(Fact(f"M:{_kid(k)}", k, "member", p1, None, "member", role="member"))
    add_universe(ref, dims, ["latest", "prev"], spec.get("filters"))


def _o_contribution(ref: Reference, spec: dict[str, Any]) -> None:
    domain = ref.domain
    dims = [spec["dim"]]
    metric = spec["metric"]
    p1 = resolve_period(domain, spec.get("period", "latest"))
    p0 = resolve_period(domain, spec.get("base", "prev"))
    ref.periods = [p1, p0]
    msql = metric_sql(domain)
    rows = _change_rows(domain, dims, metric, p1, p0, spec.get("filters"))
    total = sum(r["abs"] for r in rows if r["abs"] is not None)
    ref.facts.append(Fact(f"R:total:{metric}:abs_change", {}, metric, f"{p1} vs {p0}", total,
                          msql[metric][1], "required", part="abs_change"))
    rows = [r for r in rows if r["abs"] is not None]
    order = spec.get("order", "abs_desc")
    if order == "signed_desc":
        rows.sort(key=lambda r: r["abs"], reverse=True)
    else:
        rows.sort(key=lambda r: abs(r["abs"]), reverse=True)
    topn = spec.get("topn", 5)
    for i, r in enumerate(rows):
        in_scope = i < topn
        _emit_change(ref, r["key"], metric, p1, p0, r, msql[metric][1], ["abs_change"], in_scope)
        share = (r["abs"] / total) if total else None
        if share is not None:
            ref.facts.append(Fact(f"R:{_kid(r['key'])}:{metric}:contribution_share", r["key"],
                                  metric, f"{p1} vs {p0}", share, "ratio",
                                  "universe", part="contribution_share"))
    ref.ranking = [r["key"] for r in rows[:topn]]
    ref.ranking_required = True
    add_universe(ref, dims, ["latest", "prev"], spec.get("filters"))


def _o_stock_rate(ref: Reference, spec: dict[str, Any]) -> None:
    """ECL change = stock effect (dEAD x base coverage) + rate effect (dCoverage x latest EAD)."""
    domain = ref.domain
    dims = [spec["dim"]] if spec.get("dim") else []
    p1 = resolve_period(domain, spec.get("period", "latest"))
    p0 = resolve_period(domain, spec.get("base", "prev"))
    ref.periods = [p1, p0]
    now = {_kid(_key(r, dims)): r for r in grouped(domain, dims, ["ead", "ecl"], p1, spec.get("filters"))}
    base = {_kid(_key(r, dims)): r for r in grouped(domain, dims, ["ead", "ecl"], p0, spec.get("filters"))}
    results = []
    for kid in sorted(set(now) & set(base)):
        e1, l1 = _num(now[kid]["ead"]), _num(now[kid]["ecl"])
        e0, l0 = _num(base[kid]["ead"]), _num(base[kid]["ecl"])
        if not e0 or not e1:
            continue
        c0, c1 = l0 / e0, l1 / e1
        results.append({"key": _key(now[kid], dims), "ecl_change": l1 - l0,
                        "stock": (e1 - e0) * c0, "rate": (c1 - c0) * e1,
                        "ecl1": l1, "ecl0": l0})
    results.sort(key=lambda r: abs(r["ecl_change"]), reverse=True)
    topn = spec.get("topn") if dims else None
    chosen = results[:topn] if topn else results
    ids = {_kid(r["key"]) for r in chosen}
    per = f"{p1} vs {p0}"
    for r in results:
        req = _kid(r["key"]) in ids
        for part in ("ecl_change", "stock", "rate", "ecl1", "ecl0"):
            period = per if part not in ("ecl1", "ecl0") else (p1 if part == "ecl1" else p0)
            role = "required" if req and part in ("ecl_change", "stock", "rate") else "universe"
            ref.facts.append(Fact(f"R:{_kid(r['key'])}:ecl:{part}", r["key"], "ecl", period,
                                  r[part], "amount", role, part=part))
    if dims:
        ref.ranking = [r["key"] for r in chosen]
        ref.ranking_required = bool(topn)
    add_universe(ref, dims, ["latest", "prev"], spec.get("filters"))


def _o_concentration(ref: Reference, spec: dict[str, Any]) -> None:
    domain = ref.domain
    dim = spec["dim"]
    metric = spec.get("metric", "ead")
    period = resolve_period(domain, spec.get("period", "latest"))
    ref.periods = [period]
    rows = grouped(domain, [dim], [metric], period, spec.get("filters"))
    rows.sort(key=lambda r: _num(r[metric]) or 0.0, reverse=True)
    total = sum(_num(r[metric]) or 0.0 for r in rows)
    for n in spec["topn"]:
        top = rows[:n]
        share = sum(_num(r[metric]) or 0.0 for r in top) / total if total else None
        ref.facts.append(Fact(f"R:top{n}:{dim}:{metric}:share", {}, metric, period, share,
                              "ratio", "required", part=f"top{n}_share"))
        ref.facts.append(Fact(f"R:top{n}:{dim}:{metric}:sum", {}, metric, period,
                              sum(_num(r[metric]) or 0.0 for r in top), "amount", "universe",
                              part=f"top{n}_sum"))
    ref.facts.append(Fact(f"R:total:{metric}:{period}", {}, metric, period, total,
                          "amount", "universe"))
    for r in rows[:max(spec["topn"])]:
        ref.facts.append(Fact(f"U:{dim}={r[dim]}:{metric}:{period}", {dim: str(r[dim])}, metric,
                              period, _num(r[metric]), "amount", "universe"))
    if spec.get("dims_universe", True):
        add_universe(ref, [dim] if dim in ("sector", "product", "region") else [], ["latest"],
                     spec.get("filters"))


def _o_trend(ref: Reference, spec: dict[str, Any]) -> None:
    domain = ref.domain
    dims = [spec["dim"]] if spec.get("dim") else []
    n = int(spec.get("n_periods", 6))
    ps = periods(domain)[-n:]
    ref.periods = ps
    msql = metric_sql(domain)
    keys = spec.get("keys")
    for p in ps:
        for r in grouped(domain, dims, spec["metrics"], p, spec.get("filters")):
            key = _key(r, dims)
            if keys and _kid(key) not in [_kid(k) for k in keys]:
                continue
            for m in spec["metrics"]:
                role = "required" if m in spec.get("required_metrics", spec["metrics"]) else "universe"
                ref.facts.append(Fact(f"R:{_kid(key)}:{m}:{p}", key, m, p, _num(r[m]),
                                      msql[m][1], role))
    add_universe(ref, dims, ["latest", "prev"], spec.get("filters"))


def _o_sql(ref: Reference, spec: dict[str, Any]) -> None:
    """A named custom oracle from CUSTOM (below). Keys and values are declared.

    A custom oracle may be composite ("parts": [names]); each part adds its facts.
    """
    custom = CUSTOM[spec["name"]]
    if custom.get("parts"):
        for part in custom["parts"]:
            _o_sql(ref, {"fn": "sql", "name": part})
        return
    params = custom.get("params", [])
    rows = query(custom["sql"], params)
    ref.periods = list(custom.get("periods", []))
    keys = custom.get("keys", [])
    for i, r in enumerate(rows):
        key = {k: str(r[k]) for k in keys}
        in_scope = (custom.get("required_rows") is None or i < custom["required_rows"])
        for col, kind in custom["values"].items():
            role = "required" if in_scope and col in custom.get("required", custom["values"]) else "universe"
            ref.facts.append(Fact(f"R:{_kid(key)}:{col}", key, col, ",".join(ref.periods),
                                  _num(r[col]), kind, role))
    if custom.get("ranking"):
        n = custom.get("required_rows") or len(rows)
        ref.ranking = [{k: str(r[k]) for k in keys} for r in rows[:n]]
        ref.ranking_required = True
    if custom.get("members"):
        ref.member_set = [{k: str(r[k]) for k in keys} for r in rows]
        for r in rows:
            k = {kk: str(r[kk]) for kk in keys}
            ref.facts.append(Fact(f"M:{_kid(k)}", k, "member", "", None, "member", role="member"))
    for d in custom.get("universe_dims", []):
        add_universe(ref, [d] if d else [], ["latest", "prev"], None)
    ref.notes.append(custom.get("note", ""))


def _o_none(ref: Reference, spec: dict[str, Any]) -> None:
    """Behavioural only. A universe is still built so any number stated can be checked."""
    dims = spec.get("universe_dims", [])
    for d in (dims or [None]):
        add_universe(ref, [d] if d else [], spec.get("universe_periods", ["latest", "prev"]))


FUNCTIONS = {"scalar": _o_scalar, "by_dim": _o_by_dim, "change": _o_change,
             "condition": _o_condition, "contribution": _o_contribution,
             "stock_rate": _o_stock_rate, "concentration": _o_concentration,
             "trend": _o_trend, "sql": _o_sql, "none": _o_none}


def compute(spec: dict[str, Any], domain: str) -> Reference:
    fn = spec.get("fn", "none")
    ref = Reference(domain=domain, spec=spec)
    FUNCTIONS[fn](ref, dict(spec))
    ref.population = spec.get("population", "")
    return ref


# ---- custom oracles (independent SQL) --------------------------------------------

def _corp_latest() -> str:
    return "2026Q2"


CUSTOM: dict[str, dict[str, Any]] = {
    "corp_stage_transition_s1_s3_yoy": {
        "sql": """
            SELECT n.sector, COUNT(*) AS facilities, SUM(n.ead_sar_mn) AS ead_now
            FROM corp_facility_quarter n
            JOIN corp_facility_quarter b ON b.facility_id = n.facility_id
             AND b.reporting_quarter = '2025Q2'
            WHERE n.reporting_quarter = '2026Q2' AND n.stage = 3 AND b.stage = 1
            GROUP BY n.sector ORDER BY ead_now DESC""",
        "keys": ["sector"], "values": {"facilities": "count", "ead_now": "amount"},
        "periods": ["2026Q2", "2025Q2"],
        "note": "Facilities in Stage 3 in 2026Q2 that were Stage 1 in 2025Q2, by sector."},
    "corp_stage_transition_s1_s3_yoy_total": {
        "sql": """
            SELECT COUNT(*) AS facilities, SUM(n.ead_sar_mn) AS ead_now
            FROM corp_facility_quarter n
            JOIN corp_facility_quarter b ON b.facility_id = n.facility_id
             AND b.reporting_quarter = '2025Q2'
            WHERE n.reporting_quarter = '2026Q2' AND n.stage = 3 AND b.stage = 1""",
        "keys": [], "values": {"facilities": "count", "ead_now": "amount"},
        "periods": ["2026Q2", "2025Q2"], "universe_dims": ["sector"],
        "note": "Total facilities moving Stage 1 -> Stage 3 over the year."},
    "corp_s1_to_s2_qoq_by_sector_top5": {
        "sql": """
            SELECT n.sector, COUNT(*) AS facilities, SUM(n.ead_sar_mn) AS ead_now
            FROM corp_facility_quarter n
            JOIN corp_facility_quarter b ON b.facility_id = n.facility_id
             AND b.reporting_quarter = '2026Q1'
            WHERE n.reporting_quarter = '2026Q2' AND n.stage = 2 AND b.stage = 1
            GROUP BY n.sector ORDER BY ead_now DESC""",
        "keys": ["sector"], "values": {"ead_now": "amount", "facilities": "count"},
        "required": ["ead_now"], "required_rows": 5, "ranking": True,
        "periods": ["2026Q2", "2026Q1"], "universe_dims": ["sector"],
        "note": "EAD (2026Q2) of facilities that moved Stage 1 -> Stage 2 between 2026Q1 and 2026Q2."},
    "corp_top10_borrowers_s3": {
        "sql": """
            SELECT borrower_name, MIN(sector) AS sector,
                   SUM(CASE WHEN stage=3 THEN ead_sar_mn ELSE 0 END) AS ead_s3,
                   SUM(CASE WHEN stage=3 THEN ecl_sar_mn ELSE 0 END) AS ecl_s3
            FROM corp_facility_quarter WHERE reporting_quarter='2026Q2'
            GROUP BY borrower_id, borrower_name ORDER BY ead_s3 DESC LIMIT 10""",
        "keys": ["borrower_name"], "values": {"ead_s3": "amount", "ecl_s3": "amount"},
        "required": ["ead_s3"], "ranking": True, "periods": ["2026Q2"],
        "note": "Top 10 borrowers by Stage 3 EAD (facility stage), with Stage 3 ECL."},
    "corp_top10_borrowers_ead": {
        "sql": """
            SELECT borrower_name, SUM(ead_sar_mn) AS ead
            FROM corp_facility_quarter WHERE reporting_quarter='2026Q2'
            GROUP BY borrower_id, borrower_name ORDER BY ead DESC LIMIT 10""",
        "keys": ["borrower_name"], "values": {"ead": "amount"}, "ranking": True,
        "periods": ["2026Q2"], "universe_dims": [""],
        "note": "Ten largest borrowers by EAD."},
    "corp_top5_borrowers_stage_mix": {
        "sql": """
            WITH top AS (SELECT borrower_id FROM corp_facility_quarter
                         WHERE reporting_quarter='2026Q2' GROUP BY borrower_id
                         ORDER BY SUM(ead_sar_mn) DESC LIMIT 5)
            SELECT f.borrower_name, SUM(f.ead_sar_mn) AS ead,
                   SUM(CASE WHEN stage=2 THEN ead_sar_mn ELSE 0 END) AS ead_s2,
                   SUM(CASE WHEN stage=3 THEN ead_sar_mn ELSE 0 END) AS ead_s3
            FROM corp_facility_quarter f JOIN top USING (borrower_id)
            WHERE f.reporting_quarter='2026Q2' GROUP BY f.borrower_id, f.borrower_name
            ORDER BY ead DESC""",
        "keys": ["borrower_name"], "values": {"ead": "amount", "ead_s2": "amount", "ead_s3": "amount"},
        "required": ["ead_s2", "ead_s3"], "periods": ["2026Q2"],
        "note": "For the five largest borrowers, EAD in Stage 2 and Stage 3."},
    "corp_top10_borrowers_stage_mix": {
        "sql": """
            WITH top AS (SELECT borrower_id FROM corp_facility_quarter
                         WHERE reporting_quarter='2026Q2' GROUP BY borrower_id
                         ORDER BY SUM(ead_sar_mn) DESC LIMIT 10)
            SELECT f.borrower_name, SUM(f.ead_sar_mn) AS ead,
                   SUM(CASE WHEN stage=2 THEN ead_sar_mn ELSE 0 END) AS ead_s2,
                   SUM(CASE WHEN stage=3 THEN ead_sar_mn ELSE 0 END) AS ead_s3
            FROM corp_facility_quarter f JOIN top USING (borrower_id)
            WHERE f.reporting_quarter='2026Q2' GROUP BY f.borrower_id, f.borrower_name
            ORDER BY ead DESC""",
        "keys": ["borrower_name"], "values": {"ead": "amount", "ead_s2": "amount", "ead_s3": "amount"},
        "required": ["ead_s2", "ead_s3"], "periods": ["2026Q2"],
        "note": "For the ten largest borrowers, EAD in Stage 2 and Stage 3."},
    "corp_covenant_breaches_by_type": {
        "sql": """
            SELECT covenant_type, SUM(breach_flag) AS breached_tests
            FROM corp_covenant_quarter WHERE reporting_quarter='2026Q2'
            GROUP BY covenant_type ORDER BY breached_tests DESC""",
        "keys": ["covenant_type"], "values": {"breached_tests": "count"},
        "periods": ["2026Q2"],
        "note": "Breached covenant tests by covenant type, latest quarter."},
    "corp_breached_facilities_ead": {
        "sql": """
            SELECT COUNT(*) AS facilities, SUM(f.ead_sar_mn) AS ead
            FROM corp_facility_quarter f
            WHERE f.reporting_quarter='2026Q2' AND f.facility_id IN (
              SELECT facility_id FROM corp_covenant_quarter
              WHERE reporting_quarter='2026Q2' AND breach_flag=1)""",
        "keys": [], "values": {"facilities": "count", "ead": "amount"},
        "periods": ["2026Q2"],
        "note": "Facilities with at least one breached covenant: count and EAD (no join fan-out)."},
    "corp_watchlist_by_sector": {
        "sql": """
            SELECT b.sector, COUNT(*) AS borrowers,
                   SUM(f.ead) AS ead
            FROM corp_borrower_quarter b
            JOIN (SELECT borrower_id, SUM(ead_sar_mn) AS ead FROM corp_facility_quarter
                  WHERE reporting_quarter='2026Q2' GROUP BY borrower_id) f
              ON f.borrower_id = b.borrower_id
            WHERE b.reporting_quarter='2026Q2' AND b.watchlist_flag=1
            GROUP BY b.sector ORDER BY ead DESC""",
        "keys": ["sector"], "values": {"borrowers": "count", "ead": "amount"},
        "periods": ["2026Q2"], "universe_dims": ["sector"],
        "note": "Watch-list borrowers by sector with the EAD of their facilities (pre-aggregated, no fan-out)."},
    "corp_downgrades_by_sector_top5": {
        "sql": """
            SELECT b.sector, COUNT(*) AS borrowers, SUM(f.ead) AS ead
            FROM corp_borrower_quarter b
            JOIN (SELECT borrower_id, SUM(ead_sar_mn) AS ead FROM corp_facility_quarter
                  WHERE reporting_quarter='2026Q2' GROUP BY borrower_id) f
              ON f.borrower_id = b.borrower_id
            WHERE b.reporting_quarter='2026Q2' AND b.rating_migration='DOWNGRADE'
            GROUP BY b.sector ORDER BY borrowers DESC, ead DESC""",
        "keys": ["sector"], "values": {"borrowers": "count", "ead": "amount"},
        "required_rows": 5, "ranking": True, "periods": ["2026Q2"],
        "universe_dims": ["sector"],
        "note": "Borrowers downgraded this quarter, by sector, with the EAD of their facilities."},
    "corp_s2share_cov_filter": {
        "sql": """
            SELECT sector,
                   SUM(CASE WHEN stage=2 THEN ead_sar_mn ELSE 0 END)/SUM(ead_sar_mn) AS s2_share,
                   SUM(ecl_sar_mn)/SUM(ead_sar_mn) AS coverage
            FROM corp_facility_quarter WHERE reporting_quarter='2026Q2'
            GROUP BY sector
            HAVING SUM(CASE WHEN stage=2 THEN ead_sar_mn ELSE 0 END)/SUM(ead_sar_mn) > 0.25
               AND SUM(ecl_sar_mn)/SUM(ead_sar_mn) > 0.10
            ORDER BY sector""",
        "keys": ["sector"], "values": {"s2_share": "ratio", "coverage": "ratio"},
        "members": True, "periods": ["2026Q2"], "universe_dims": ["sector"],
        "note": "Sectors with Stage 2 share > 25% and ECL coverage > 10%."},
    "corp_covenant_breaches_combined": {
        "parts": ["corp_covenant_breaches_by_type", "corp_breached_facilities_ead"],
        "note": "Breached tests by type, plus EAD of facilities with >= 1 breach."},
    "corp_al_ahsa_gulf_borrowers": {
        "sql": """
            SELECT borrower_name, SUM(ead_sar_mn) AS ead
            FROM corp_facility_quarter
            WHERE reporting_quarter='2026Q2' AND borrower_name LIKE 'Al Ahsa Gulf%'
            GROUP BY borrower_id, borrower_name ORDER BY borrower_name""",
        "keys": ["borrower_name"], "values": {"ead": "amount"}, "required": [],
        "members": True, "periods": ["2026Q2"],
        "note": "Every borrower whose name begins 'Al Ahsa Gulf' (ambiguous reference)."},
    "retail_worst_stage3_customers_by_segment": {
        "sql": """
            SELECT customer_segment, COUNT(*) AS customers, SUM(total_ead_sar_mn) AS ead
            FROM retail_customer_month WHERE reporting_month='2026-08' AND worst_stage=3
            GROUP BY customer_segment ORDER BY ead DESC""",
        "keys": ["customer_segment"], "values": {"customers": "count", "ead": "amount"},
        "periods": ["2026-08"], "universe_dims": ["customer_segment"],
        "note": "Customers whose worst account stage is 3, by segment."},
    "retail_score_deteriorated_by_segment": {
        "sql": """
            SELECT customer_segment, COUNT(*) AS customers, SUM(total_ead_sar_mn) AS ead
            FROM retail_customer_month WHERE reporting_month='2026-08'
             AND score_migration='DETERIORATED'
            GROUP BY customer_segment ORDER BY customers DESC""",
        "keys": ["customer_segment"], "values": {"customers": "count", "ead": "amount"},
        "periods": ["2026-08"], "universe_dims": ["customer_segment"],
        "note": "Customers whose behaviour score band deteriorated this month, by segment."},
    "retail_mortgage_aggregate_ltv": {
        "sql": """
            SELECT SUM(a.balance_sar_mn)/SUM(c.collateral_value_sar_mn) AS ltv,
                   SUM(a.balance_sar_mn) AS balance, SUM(c.collateral_value_sar_mn) AS collateral
            FROM retail_collateral_month c
            JOIN retail_account_month a ON a.account_id=c.account_id
             AND a.reporting_month=c.reporting_month
            WHERE c.reporting_month='2026-08' AND c.product='Mortgage'""",
        "keys": [], "values": {"ltv": "ratio", "balance": "amount", "collateral": "amount"},
        "required": ["ltv"], "periods": ["2026-08"],
        "note": "Aggregate mortgage LTV = total balance / total collateral value."},
}


def freeze_references(bank_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute every oracle in the bank; return {case_id: ref dict} + hashes."""
    out: dict[str, Any] = {}
    for row in bank_rows:
        for label, spec_key in (("primary", "oracle"), ("followup", "followup_oracle")):
            spec = row.get(spec_key)
            if not spec:
                continue
            ref = compute(spec, spec.get("domain") or row["domain"])
            out[f"{row['case_id']}:{label}"] = {"sha256": ref.sha256(),
                                                "reference": ref.to_dict()}
    return out
