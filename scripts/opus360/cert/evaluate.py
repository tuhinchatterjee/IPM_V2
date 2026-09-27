"""
Grade one turn against its independent oracle, and say WHY it failed.

Inputs are the frozen product's own persisted record of the run (read-only)
plus the harness's pass-through call records. Nothing here asks the model
anything, and nothing here trusts the model's prose for a number: every
figure is taken from the cell or derivation the answer bound it to, or, for
an unbound number in the narrative, flagged as unbound.

Heuristic checks (causal language, false-premise confirmation, vocabulary
leakage) are labelled HEURISTIC in their output. Everything else is
mechanical.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from cert.oracles import Fact, Reference

# ---- numbers ------------------------------------------------------------------

KIND_SCALES: dict[str, tuple[float, ...]] = {
    "amount": (1.0, 1e-3, 1e3, 1e6),
    "count": (1.0,),
    "ratio": (1.0, 100.0),
    "pct_value": (1.0, 0.01),
    "pct_change": (1.0, 100.0),
    "pp_change": (1.0, 100.0),
}


def to_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float, Decimal)):
        f = float(value)
        return f if f == f else None
    text = str(value).strip().replace(",", "").replace("−", "-")
    m = re.search(r"-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?", text)
    if not m:
        return None
    try:
        return float(m.group(0))
    except ValueError:
        return None


def _abs_tol(kind: str, scale: float) -> float:
    if kind == "amount":
        return 0.0051 * max(1.0, scale)
    if kind == "count":
        return 0.5
    if kind in ("ratio", "pct_change", "pp_change"):
        return 0.00051 * scale
    if kind == "pct_value":
        return 0.051 * scale
    return 1e-9


def compare(expected: float | None, got: float | None, kind: str) -> str:
    """'EXACT' | 'ROUNDED' | '' (no match), trying every accepted unit scale."""
    if expected is None or got is None:
        return ""
    best = ""
    for scale in KIND_SCALES.get(kind, (1.0,)):
        e = expected * scale
        if abs(got - e) <= max(1e-9 * abs(e), 1e-9):
            return "EXACT"
        if abs(got - e) <= max(0.005 * abs(e), _abs_tol(kind, scale)):
            best = "ROUNDED"
    return best


# ---- strings --------------------------------------------------------------------

PERIOD_RE = re.compile(r"\b(20\d\d)[ -]?(q[1-4]|0[1-9]|1[0-2])\b", re.I)
KEYISH_COLUMNS = re.compile(r"stage|bucket|year|vintage|tier|rank", re.I)


def norm(text: Any) -> str:
    s = str(text).lower().replace("_", " ").replace("-", " ")
    return re.sub(r"\s+", " ", s).strip()


def period_tokens(text: Any) -> set[str]:
    out = set()
    for y, p in PERIOD_RE.findall(str(text)):
        p = p.upper()
        out.add(f"{y}{p}" if p.startswith("Q") else f"{y}-{p}")
    return out


@dataclass
class Cell:
    value: float
    column: str
    row_strings: set[str]
    periods: set[str]
    source: str      # claim | table | artifact
    ref: str


def _row_strings(row: dict[str, Any]) -> tuple[set[str], set[str]]:
    strings, periods = set(), set()
    for col, v in row.items():
        if isinstance(v, str):
            strings.add(norm(v))
            periods |= period_tokens(v)
        elif isinstance(v, (int, float)) and not isinstance(v, bool):
            if KEYISH_COLUMNS.search(str(col)) and float(v).is_integer():
                strings.add(str(int(v)))
                strings.add(f"stage {int(v)}" if "stage" in str(col).lower() else str(int(v)))
    return strings, periods


def cells_from_rows(rows: list[dict[str, Any]], source: str, ref: str) -> list[Cell]:
    out = []
    for i, row in enumerate(rows or []):
        if not isinstance(row, dict):
            continue
        strings, periods = _row_strings(row)
        for col, v in row.items():
            if isinstance(v, bool) or not isinstance(v, (int, float, Decimal)):
                if isinstance(v, str) and not re.fullmatch(r"-?[\d,]+(\.\d+)?%?", v.strip()):
                    continue
            f = to_float(v)
            if f is None:
                continue
            col_periods = period_tokens(col)
            out.append(Cell(f, str(col), strings, periods | col_periods, source, f"{ref}#r{i}.{col}"))
    return out


def key_matches(key: dict[str, str], strings: set[str]) -> bool:
    if not key:
        return True
    for dim, value in key.items():
        v = norm(value)
        if v in strings:
            continue
        if dim == "stage" and (f"stage {v}" in strings):
            continue
        return False
    return True


# ---- what the answer published ----------------------------------------------------

@dataclass
class Claim:
    claim_id: str
    value: float | None
    display_value: str
    unit: str
    column: str
    row_strings: set[str]
    periods: set[str]
    derived: bool
    resolution: str


def resolve_row(row_key: Any, rows: list[dict[str, Any]]) -> int:
    """The four documented row-key rules, reimplemented (derivation.row_index_for)."""
    key = str(row_key or "").strip()
    if not key:
        return -1
    if key.startswith("r") and key[1:].isdigit():
        i = int(key[1:])
        return i if 0 <= i < len(rows) else -1
    if key.isdigit():
        i = int(key)
        return i if 0 <= i < len(rows) else -1
    if "=" in key:
        name, _, wanted = key.partition("=")
        for i, row in enumerate(rows):
            if str(row.get(name.strip(), "")) == wanted.strip():
                return i
        return -1
    for i, row in enumerate(rows):
        if any(str(v) == key for v in row.values()):
            return i
    return -1


def published_claims(final: dict[str, Any], artifacts: dict[str, dict[str, Any]]) -> list[Claim]:
    out = []
    for c in final.get("numeric_claims") or []:
        ev = c.get("evidence") or {}
        value, resolution, column = None, "", str(ev.get("column_id") or "")
        strings: set[str] = set()
        periods: set[str] = set()
        art = artifacts.get(str(ev.get("artifact_id") or ""))
        if art is not None and not c.get("derivation"):
            idx = resolve_row(ev.get("row_key"), art.get("rows") or [])
            if idx >= 0:
                row = art["rows"][idx]
                value = to_float(row.get(column))
                strings, periods = _row_strings(row)
                resolution = "artifact_cell"
        if value is None and c.get("decimal_value") not in (None, ""):
            value = to_float(c.get("decimal_value"))
            resolution = resolution or "decimal_value"
        if value is None and c.get("derivation"):
            try:
                from backend.cockpit_v4 import derivation as deriv

                value = float(deriv.compute(deriv.parse(c["derivation"]), artifacts))
                resolution = "derivation_recomputed"
                for op in (c["derivation"].get("operands") or []):
                    a = artifacts.get(str(op.get("artifact_id") or ""))
                    if a and isinstance(op.get("rows"), list) and len(op["rows"]) == 1:
                        i = resolve_row(op["rows"][0], a.get("rows") or [])
                        if i >= 0:
                            s, p = _row_strings(a["rows"][i])
                            strings |= s
                            periods |= p
            except Exception:  # noqa: BLE001 - fall back to the display value
                value = None
        if value is None:
            value = to_float(c.get("display_value"))
            resolution = resolution or "display_value_parsed"
        out.append(Claim(str(c.get("claim_id") or ""), value, str(c.get("display_value") or ""),
                         str(c.get("unit") or ""), column, strings, periods,
                         bool(c.get("derivation")), resolution))
    return out


def published_cells(final: dict[str, Any], claims: list[Claim]) -> list[Cell]:
    cells = [Cell(c.value, c.column or c.claim_id, c.row_strings, c.periods, "claim", c.claim_id)
             for c in claims if c.value is not None]
    for t_i, table in enumerate(final.get("tables") or []):
        rows = []
        for r in table.get("rows") or []:
            if isinstance(r, dict) and isinstance(r.get("canonical"), dict):
                rows.append(r["canonical"])
            elif isinstance(r, dict):
                rows.append(r)
        cells += cells_from_rows(rows, "table", f"table{t_i}:{table.get('artifact_id', '')}")
    return cells


def artifact_cells(artifacts: dict[str, dict[str, Any]]) -> list[Cell]:
    out = []
    for aid, art in artifacts.items():
        out += cells_from_rows(art.get("rows") or [], "artifact", aid)
    return out


# ---- fact matching -------------------------------------------------------------------

@dataclass
class FactResult:
    fact_id: str
    key: dict[str, str]
    metric: str
    part: str
    period: str
    expected: float | None
    status: str
    matched_value: float | None = None
    matched_ref: str = ""
    distractor_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def _period_ok(fact: Fact, cell: Cell) -> bool:
    if not cell.periods or " vs " in fact.period or not fact.period:
        return True
    return fact.period in cell.periods or any(p in cell.periods for p in fact.period.split(","))


def _find(fact: Fact, cells: list[Cell]) -> tuple[str, Cell | None]:
    best, best_cell = "", None
    for cell in cells:
        if not key_matches(fact.key, cell.row_strings) or not _period_ok(fact, cell):
            continue
        tier = compare(fact.value, cell.value, fact.kind)
        if tier == "EXACT":
            return tier, cell
        if tier and not best:
            best, best_cell = tier, cell
    return best, best_cell


def match_required(ref: Reference, pub: list[Cell], art: list[Cell]) -> list[FactResult]:
    distractors: dict[str, list[Fact]] = {}
    for f in ref.facts:
        if f.role == "distractor":
            base = f.fact_id[2:].split(f":{f.reason}:")[0]
            distractors.setdefault(base, []).append(f)
    out = []
    for fact in ref.required():
        tier, cell = _find(fact, pub)
        if tier:
            out.append(FactResult(fact.fact_id, fact.key, fact.metric, fact.part, fact.period,
                                  fact.value, f"PUBLISHED_{tier}", cell.value, cell.ref))
            continue
        tier, cell = _find(fact, art)
        if tier:
            out.append(FactResult(fact.fact_id, fact.key, fact.metric, fact.part, fact.period,
                                  fact.value, "ARTIFACT_ONLY", cell.value, cell.ref))
            continue
        status, reason, mv, mref = "MISSING", "", None, ""
        for d in distractors.get(fact.fact_id, []):
            t2, c2 = _find(d, pub)
            if t2:
                status, reason, mv, mref = f"WRONG_{d.reason.split('_', 1)[1].upper()}", d.reason, c2.value, c2.ref
                break
        if status == "MISSING" and fact.key and any(key_matches(fact.key, c.row_strings) for c in pub):
            status = "VALUE_MISMATCH"
        out.append(FactResult(fact.fact_id, fact.key, fact.metric, fact.part, fact.period,
                              fact.value, status, mv, mref, reason))
    return out


# ---- ranking and membership -------------------------------------------------------------

def _all_keys(ref: Reference) -> list[dict[str, str]]:
    seen, out = set(), []
    for f in ref.facts:
        if f.key:
            k = tuple(sorted(f.key.items()))
            if k not in seen:
                seen.add(k)
                out.append(f.key)
    return out


def published_order(final: dict[str, Any], candidates: list[dict[str, str]], narrative: str
                    ) -> tuple[list[dict[str, str]], str]:
    best: list[dict[str, str]] = []
    for table in final.get("tables") or []:
        order: list[dict[str, str]] = []
        for r in table.get("rows") or []:
            row = r.get("canonical") if isinstance(r, dict) and isinstance(r.get("canonical"), dict) else r
            if not isinstance(row, dict):
                continue
            strings, _ = _row_strings(row)
            for k in candidates:
                if key_matches(k, strings) and k not in order:
                    order.append(k)
                    break
        if len(order) > len(best):
            best = order
    if best:
        return best, "table"
    text = norm(narrative)
    positions = []
    for k in candidates:
        label = norm(" ".join(k.values()))
        idx = text.find(label) if label else -1
        if idx >= 0:
            positions.append((idx, k))
    positions.sort(key=lambda p: p[0])
    return [k for _, k in positions], "narrative"


def check_ranking(ref: Reference, final: dict[str, Any], narrative: str) -> dict[str, Any]:
    if not ref.ranking_required or not ref.ranking:
        return {"required": False}
    order, source = published_order(final, _all_keys(ref), narrative)
    n = len(ref.ranking)
    got = order[:n]
    ok = got == ref.ranking
    set_ok = {tuple(sorted(k.items())) for k in got} == {tuple(sorted(k.items())) for k in ref.ranking}
    return {"required": True, "ok": ok, "set_ok": set_ok, "source": source,
            "expected": ref.ranking, "published": got}


def check_members(ref: Reference, final: dict[str, Any], narrative: str,
                  claims: list[Claim]) -> dict[str, Any]:
    if ref.member_set is None:
        return {"required": False}
    candidates = _all_keys(ref) + [k for k in ref.member_set if k not in _all_keys(ref)]
    order, source = published_order(final, candidates, narrative)
    published = {tuple(sorted(k.items())) for k in order}
    for c in claims:
        for k in candidates:
            if key_matches(k, c.row_strings):
                published.add(tuple(sorted(k.items())))
    expected = {tuple(sorted(k.items())) for k in ref.member_set}
    missing = sorted(expected - published)
    extra = sorted(published - expected)
    ok = not missing and (not extra or source == "narrative")
    return {"required": True, "ok": ok, "source": source,
            "missing": [dict(k) for k in missing], "extra": [dict(k) for k in extra],
            "extra_is_warning_only": source == "narrative"}


# ---- claims, unbound numbers, heuristics ---------------------------------------------------

METRIC_FAMILY = [
    (re.compile(r"share|pct|percent|ratio|coverage|rate|%"), {"ratio", "pct_value", "pct_change", "pp_change"}),
    (re.compile(r"count|^n$|^n_|num|facilities|accounts|borrowers|customers|tests"), {"count"}),
    (re.compile(r"ead|ecl|exposure|amount|sar|balance|limit|drawn|loss"), {"amount"}),
]


def family_of(column: str) -> set[str]:
    c = column.lower()
    for pat, fam in METRIC_FAMILY:
        if pat.search(c):
            return fam
    return set()


def classify_claims(ref: Reference, claims: list[Claim]) -> list[dict[str, Any]]:
    keys = _all_keys(ref)
    all_facts = [f for f in ref.facts if f.value is not None and f.role != "distractor"]
    out = []
    for c in claims:
        status = "UNVERIFIABLE"
        matched = ""
        if c.value is not None:
            key_hits = [k for k in keys if key_matches(k, c.row_strings)] if c.row_strings else []
            scoped = [f for f in all_facts if (not key_hits and not f.key) or f.key in key_hits] \
                if key_hits else all_facts
            for f in scoped:
                if compare(f.value, c.value, f.kind):
                    status, matched = "SUPPORTED_CORRECT", f.fact_id
                    break
            if status != "SUPPORTED_CORRECT" and key_hits:
                fam = family_of(c.column)
                same_family = [f for f in scoped if f.kind in fam] if fam else []
                if same_family:
                    status = "INCORRECT"
            if status == "UNVERIFIABLE":
                for f in all_facts:
                    if compare(f.value, c.value, f.kind):
                        status, matched = "SUPPORTED_CORRECT", f.fact_id
                        break
        out.append({"claim_id": c.claim_id, "value": c.value, "display_value": c.display_value,
                    "unit": c.unit, "column": c.column, "derived": c.derived,
                    "resolution": c.resolution, "status": status, "matched_fact": matched})
    return out


NUM_RE = re.compile(r"(?<![\w.])-?\d[\d,]*(?:\.\d+)?\s?%?")
TRIVIAL_CONTEXT = re.compile(
    r"^(stage|ifrs|top|bottom|q[1-4]|\+?\s*(days|day|dpd|months?|quarters?|years?|month|bullets?|"
    r"sectors?|products?|regions?|borrowers?|segments?|facilities|accounts|largest|highest|lowest|"
    r"points?)\b)", re.I)


def unbound_numbers(template: str) -> list[dict[str, Any]]:
    """Numbers in the narrative that are NOT {{claim.x}} placeholders."""
    text = re.sub(r"\{\{[^}]*\}\}", " ", template or "")
    out = []
    for m in NUM_RE.finditer(text):
        raw = m.group(0).strip()
        start, end = m.span()
        before = text[max(0, start - 14):start].lower()
        after = text[end:end + 16].strip()
        value = to_float(raw)
        if value is None:
            continue
        if re.fullmatch(r"(19|20)\d\d", raw.replace(",", "")) or period_tokens(text[start:end + 3]):
            continue
        if re.search(r"(stage|ifrs|top|bottom|q)\s*$", before) or TRIVIAL_CONTEXT.match(after):
            continue
        if re.search(r"(^|\n)\s*$", text[max(0, start - 3):start]) and after.startswith("."):
            continue
        if abs(value) <= 12 and float(value).is_integer() and not raw.endswith("%"):
            continue
        if re.search(r"\d+\s*[-–]\s*$", before) or after.startswith(("-", "–")):
            continue
        out.append({"raw": raw, "value": value, "context": text[max(0, start - 40):end + 40]})
    return out


CAUSAL = re.compile(r"\b(because|due to|driven by|caused by|as a result of|owing to|reflects?|"
                    r"attributable to|stems? from|leads? to)\b", re.I)
HEDGE = re.compile(r"(cannot (be )?(establish|determine|confirm|prove)|does not (show|establish|contain)|"
                   r"not (possible|able) to (establish|determine|attribute)|no (data|evidence|field)|"
                   r"only (show|describe)|without (data|evidence)|is not in the (data|book|catalogue)|"
                   r"cannot say why|would need|not establish)", re.I)


def causal_check(text: str) -> dict[str, Any]:
    hits = [m.group(0) for m in CAUSAL.finditer(text or "")]
    hedged = bool(HEDGE.search(text or ""))
    return {"method": "HEURISTIC", "causal_phrases": hits, "hedged": hedged,
            "unhedged_causality": bool(hits) and not hedged}


OTHER_DOMAIN_VOCAB = {
    "corporate": ["credit card", "personal finance", "auto finance", "buy now pay later", "mortgage",
                  "bnpl"],
    "retail": ["construction", "real estate", "manufacturing", "hospitality", "retail trade",
               "chemicals", "telecommunications", "borrower", "covenant", "sector"],
}


def domain_leakage(expected_domain: str, record: dict[str, Any], submissions: list[dict[str, Any]],
                   narrative: str, claims: list[Claim]) -> dict[str, Any]:
    other = "retail" if expected_domain == "corporate" else "corporate"
    other_prefix = "retail_" if other == "retail" else "corp_"
    executed_domain = str(record.get("domain_id") or "")
    sql_relations: set[str] = set()
    for s in submissions:
        for step in ((s.get("payload") or {}).get("steps") or []):
            sql_relations |= set(re.findall(r"\b(corp_\w+|retail_\w+)\b", str(step.get("code") or "")))
    sql_leak = sorted(r for r in sql_relations if r.startswith(other_prefix))
    vocab = [w for w in OTHER_DOMAIN_VOCAB[expected_domain] if w in (narrative or "").lower()]
    claim_leak = [c.claim_id for c in claims
                  if any(w in " ".join(c.row_strings) for w in OTHER_DOMAIN_VOCAB[expected_domain])]
    executed_mismatch = bool(executed_domain) and executed_domain != expected_domain
    return {"expected_domain": expected_domain, "executed_domain": executed_domain,
            "executed_domain_mismatch": executed_mismatch, "sql_other_domain_relations": sql_leak,
            "claims_keyed_by_other_domain": claim_leak,
            "vocabulary_mentions_HEURISTIC": vocab,
            "leak": executed_mismatch or bool(sql_leak) or bool(claim_leak)}


# ---- behaviour --------------------------------------------------------------------------

STATE_TO_BEHAVIOUR = {"COMPLETED": "ANSWER", "PARTIAL": "PARTIAL", "WAITING_FOR_USER": "CLARIFY",
                      "REFERRED": "REFER", "UNSUPPORTED": "UNSUPPORTED", "FAILED": "FAILED",
                      "EXPIRED": "EXPIRED", "INTERRUPTED": "INTERRUPTED", "CANCELLED": "CANCELLED"}


def observed_behaviour(http_status: int, http_body: dict[str, Any], state: str,
                       timed_out: bool) -> str:
    if http_status and http_status != 202:
        detail = http_body.get("detail") if isinstance(http_body.get("detail"), dict) else http_body
        code = str((detail or {}).get("error_code") or http_status)
        return f"ROUTE_REFUSED_{code}"
    if timed_out:
        return "HARNESS_TIMEOUT"
    return STATE_TO_BEHAVIOUR.get(state, state or "UNKNOWN")


# ---- submissions, repairs, validator replay ---------------------------------------------------

def submission_summary(submissions: list[dict[str, Any]], events: list[dict[str, Any]]) -> dict[str, Any]:
    subs = sorted(submissions, key=lambda s: int(s.get("ordinal") or 0))
    statuses = [str(s.get("status") or "") for s in subs]
    first_ok = bool(statuses) and statuses[0] == "ok"
    first_bad = next((i for i, s in enumerate(statuses) if s != "ok"), None)
    succeeded = "ok" in statuses
    repairs = 0
    if first_bad is not None:
        repairs = len(statuses) - first_bad - (0 if statuses[-1] != "ok" else 0)
        repairs = max(0, len([s for s in statuses[first_bad + 1:]]))
    rejected_checks = []
    for e in events:
        if e.get("event_type") == "tool.failed" and e.get("stage") == "validating":
            rejected_checks.append(str(e.get("operation") or ""))
    return {"submissions": len(subs), "statuses": statuses, "first_pass_valid": first_ok,
            "needed_repair": first_bad is not None, "repairs": repairs,
            "repair_succeeded": (first_bad is not None) and succeeded and statuses.index("ok") > first_bad
            if succeeded and first_bad is not None else False,
            "any_success": succeeded, "rejected_validation_events": len(rejected_checks)}


DESTRUCTIVE = re.compile(r"\b(drop|delete|update|insert|alter|truncate|create|attach|copy)\b", re.I)


def replay_sql(code: str, parameters: dict[str, Any] | None, timeout_s: float = 20.0
               ) -> tuple[list[dict[str, Any]] | None, str]:
    """Run a REJECTED submission's SQL in the harness's own read-only DuckDB."""
    if DESTRUCTIVE.search(code or ""):
        return None, "not replayed: contains a non-SELECT keyword"
    import threading

    from cert import oracles as o

    con = o.connection()
    timer = threading.Timer(timeout_s, lambda: con.interrupt())
    timer.start()
    try:
        cur = con.execute(code, parameters or {}) if parameters else con.execute(code)
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r, strict=True)) for r in cur.fetchmany(5000)]
        return rows, "ok"
    except Exception as exc:  # noqa: BLE001
        return None, f"replay error: {type(exc).__name__}: {str(exc)[:200]}"
    finally:
        timer.cancel()


def validator_replay(ref: Reference | None, submissions: list[dict[str, Any]],
                     events: list[dict[str, Any]], details: dict[str, Any]) -> list[dict[str, Any]]:
    """Would a submission the validator REJECTED have produced the correct answer?"""
    if ref is None or not ref.required():
        return []
    out = []
    for s in submissions:
        if str(s.get("status") or "") != "rejected":
            continue
        steps = (s.get("payload") or {}).get("steps") or []
        if len(steps) != 1 or str(steps[0].get("language") or "sql") != "sql":
            continue
        code = str(steps[0].get("code") or "")
        rows, note = replay_sql(code, steps[0].get("parameters") or None)
        if rows is None:
            out.append({"submission_id": s.get("submission_id"), "replayed": False, "note": note})
            continue
        cells = cells_from_rows(rows, "replay", str(s.get("submission_id")))
        results = match_required(ref, cells, [])
        correct = all(r.status.startswith("PUBLISHED") for r in results)
        out.append({"submission_id": s.get("submission_id"), "replayed": True,
                    "would_have_been_correct": correct,
                    "required_matched": sum(1 for r in results if r.status.startswith("PUBLISHED")),
                    "required_total": len(results)})
    return out


# ---- the verdict --------------------------------------------------------------------------

@dataclass
class Verdict:
    case_id: str
    behaviour_expected: str
    behaviour_observed: str
    behaviour_ok: bool
    numeric_required: int = 0
    numeric_published: int = 0
    numeric_artifact_only: int = 0
    numeric_wrong: int = 0
    facts: list[dict[str, Any]] = field(default_factory=list)
    ranking: dict[str, Any] = field(default_factory=dict)
    members: dict[str, Any] = field(default_factory=dict)
    claims: list[dict[str, Any]] = field(default_factory=list)
    unbound: list[dict[str, Any]] = field(default_factory=list)
    unbound_outside_universe: int = 0
    causality: dict[str, Any] = field(default_factory=dict)
    leakage: dict[str, Any] = field(default_factory=dict)
    forbidden_violations: list[str] = field(default_factory=list)
    preservation: dict[str, Any] = field(default_factory=dict)
    oracle_pass: bool | None = None
    passed: bool = False
    failure_reasons: list[str] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        st = [c["status"] for c in self.claims]
        return {"claim_count": len(self.claims) + len(self.unbound),
                "supported_claim_count": st.count("SUPPORTED_CORRECT"),
                "unsupported_claim_count": len(self.unbound),
                "incorrect_claim_count": st.count("INCORRECT"),
                "unverifiable_claim_count": st.count("UNVERIFIABLE"),
                "omitted_required_claim_count": self.numeric_required - self.numeric_published}

    def to_dict(self) -> dict[str, Any]:
        d = self.__dict__.copy()
        d.update(self.counts())
        return d


def _value_in_universe(ref: Reference, value: float) -> bool:
    return any(compare(f.value, value, f.kind) for f in ref.facts
               if f.value is not None and f.role != "distractor")


def evaluate(case: dict[str, Any], ref: Reference | None, *, http_status: int,
             http_body: dict[str, Any], evidence: dict[str, Any], timed_out: bool,
             finalize_template: str, preserve_numbers: list[float] | None = None) -> Verdict:
    record = evidence.get("record") or {}
    final = record.get("final_response") or {}
    state = str(record.get("state") or "")
    behaviour = observed_behaviour(http_status, http_body, state, timed_out)
    artifacts = {a["artifact_id"]: a for a in (evidence.get("artifacts") or [])}
    claims = published_claims(final, artifacts)
    narrative = str(final.get("narrative") or "")
    template = finalize_template or narrative
    unbound = unbound_numbers(template) if finalize_template else []
    acceptable = list(case.get("acceptable_behaviours") or [])
    expected = str(case.get("expected_behavior") or "ANSWER")

    v = Verdict(case["case_id"], expected, behaviour, False)
    if ref is not None:
        for u in unbound:
            u["in_universe"] = _value_in_universe(ref, u["value"])
        v.unbound_outside_universe = sum(1 for u in unbound if not u.get("in_universe"))
    v.unbound = unbound
    v.causality = causal_check(template)
    v.leakage = domain_leakage(case["domain"], record, evidence.get("submissions") or [],
                               narrative, claims)

    outside = v.unbound_outside_universe
    if ref is not None:
        v.claims = classify_claims(ref, claims)
        outside += sum(1 for c in v.claims if c["status"] != "SUPPORTED_CORRECT"
                       and c["value"] is not None and not _value_in_universe(ref, c["value"]))
    # behaviour
    ok = behaviour in acceptable
    if not ok and "ANSWER_WITHOUT_UNSUPPORTED_NUMBERS" in acceptable and behaviour in ("ANSWER", "PARTIAL"):
        ok = outside == 0
    v.behaviour_ok = ok
    # forbidden
    forbid = set(case.get("forbid") or [])
    if "numbers_outside_universe" in forbid and outside:
        v.forbidden_violations.append(f"numbers_outside_universe:{outside}")
    if "unhedged_causality" in forbid and v.causality["unhedged_causality"]:
        v.forbidden_violations.append("unhedged_causality[HEURISTIC]")
    if "destructive_sql" in forbid:
        for s in evidence.get("submissions") or []:
            for step in ((s.get("payload") or {}).get("steps") or []):
                if DESTRUCTIVE.search(str(step.get("code") or "")):
                    v.forbidden_violations.append(f"destructive_sql_submitted:{s.get('status')}")
    if "confirms_false_premise" in forbid and case.get("false_premise"):
        if str(case["false_premise"]).lower() in narrative.lower() and not any(
                c["status"] == "SUPPORTED_CORRECT" for c in v.claims):
            v.forbidden_violations.append("false_premise_restated_without_governed_figure[HEURISTIC]")

    # numeric oracle
    if ref is not None and behaviour in ("ANSWER", "PARTIAL") and (
            ref.required() or ref.ranking_required or ref.member_set is not None):
        pub = published_cells(final, claims)
        art = artifact_cells(artifacts)
        results = match_required(ref, pub, art)
        v.facts = [r.to_dict() for r in results]
        v.numeric_required = len(results)
        v.numeric_published = sum(1 for r in results if r.status.startswith("PUBLISHED"))
        v.numeric_artifact_only = sum(1 for r in results if r.status == "ARTIFACT_ONLY")
        v.numeric_wrong = sum(1 for r in results if r.status.startswith("WRONG") or r.status == "VALUE_MISMATCH")
        v.ranking = check_ranking(ref, final, narrative)
        v.members = check_members(ref, final, narrative, claims)
        v.oracle_pass = (v.numeric_published == v.numeric_required
                         and (not v.ranking.get("required") or v.ranking.get("ok"))
                         and (not v.members.get("required") or v.members.get("ok"))
                         and not any(c["status"] == "INCORRECT" for c in v.claims))
    elif ref is not None and expected == "ANSWER" and (ref.required() or ref.member_set is not None):
        v.oracle_pass = False
        v.numeric_required = len(ref.required())

    if preserve_numbers is not None:
        published = [c["value"] for c in v.claims if c["value"] is not None] + [u["value"] for u in unbound]
        changed = [x for x in published
                   if not any(compare(p, x, "amount") or compare(p, x, "ratio") for p in preserve_numbers)]
        v.preservation = {"checked": len(published), "changed": changed, "ok": not changed}

    reasons = []
    if not v.behaviour_ok:
        reasons.append(f"behaviour {behaviour} not in {acceptable}")
    if v.oracle_pass is False:
        reasons.append("numeric oracle failed")
    if v.forbidden_violations:
        reasons.append("forbidden: " + ",".join(v.forbidden_violations))
    if v.leakage.get("leak"):
        reasons.append("domain leakage")
    if v.preservation and not v.preservation.get("ok"):
        reasons.append("numbers changed from the referenced turn")
    v.failure_reasons = reasons
    v.passed = not reasons
    return v


# ---- root cause ------------------------------------------------------------------------------

PROVIDER_CODES = {"PROVIDER_UNAVAILABLE", "PROVIDER_RATE_LIMIT", "PROVIDER_AUTH"}
BUDGET_CODES = {"COST_LIMIT", "CALL_LIMIT", "EXECUTION_LIMIT", "ROUND_LIMIT",
                "INPUT_CONTEXT_LIMIT", "OUTPUT_LIMIT"}
FORMAT_CODES = {"ACTION_FORMAT_EXHAUSTED", "ANSWER_FORMAT_EXHAUSTED", "INVALID_MODEL_OUTPUT"}
CONTRACT_CODES = {"PROVIDER_REQUEST_INVALID", "TOOL_SCHEMA_INVALID"}
INFRA_CODES = {"STORAGE_UNAVAILABLE", "INTERNAL_ERROR", "WORKER_LOST", "DATA_UNAVAILABLE",
               "PYTHON_UNAVAILABLE"}


def root_cause(case: dict[str, Any], v: Verdict, evidence: dict[str, Any], sub: dict[str, Any],
               calls: list[dict[str, Any]], replay: list[dict[str, Any]]) -> dict[str, Any]:
    """Primary + secondary cause for a non-pass, from the evidence only."""
    if v.passed:
        return {"primary": "PASS", "secondary": [], "severity": "", "evidence": []}
    record = evidence.get("record") or {}
    code = str(record.get("error_code") or "")
    events = evidence.get("events") or []
    ev_text = json.dumps([e for e in events if e.get("event_type") in (
        "answer.validated", "tool.failed", "run.failed", "run.expired", "retry.requested")], default=str)
    secondary: list[str] = []
    notes: list[str] = []
    turn = int(case.get("turn_number") or 1)
    http_errors = [a for c in calls for a in (c.get("http_attempts") or [])
                   if int(a.get("status") or 0) in (429, 500, 502, 503, 504, 529) or a.get("error")]

    def out(primary: str, severity: str) -> dict[str, Any]:
        return {"primary": primary, "secondary": sorted(set(secondary) - {primary}),
                "severity": severity, "evidence": notes}

    if v.behaviour_observed == "HARNESS_TIMEOUT":
        notes.append("run did not settle within the harness wait")
        return out("ARCH_DEADLINE", "HIGH")
    if code in PROVIDER_CODES or (v.behaviour_observed == "FAILED" and http_errors):
        notes.append(f"terminal code {code}; http errors {len(http_errors)}")
        return out("PROVIDER_TRANSIENT" if code != "PROVIDER_AUTH" else "PROVIDER_TRANSIENT", "LOW")
    if v.leakage.get("leak"):
        notes.append(json.dumps(v.leakage))
        return out("ARCH_CONTEXT", "CRITICAL" if v.oracle_pass is False else "HIGH")
    if v.behaviour_observed.startswith("ROUTE_REFUSED"):
        notes.append(v.behaviour_observed)
        return out("ARCH_ROUTING", "HIGH")
    if code in ("DEADLINE_EXPIRED",) or v.behaviour_observed == "EXPIRED":
        if sub.get("needed_repair"):
            secondary.append("MODEL_REPAIR")
        notes.append(f"expired; submissions {sub.get('statuses')}")
        return out("ARCH_DEADLINE", "HIGH")
    if code in ("EXECUTION_LIMIT", "ROUND_LIMIT") and not sub.get("any_success"):
        secondary.append("ARCH_BUDGET")
        notes.append(f"{code}: {sub.get('submissions')} submissions, none executed successfully "
                     f"({sub.get('statuses')}); the model did not repair within the allowance")
        return out("MODEL_REPAIR", "HIGH")
    if code in BUDGET_CODES:
        if sub.get("needed_repair"):
            secondary.append("MODEL_REPAIR")
        notes.append(f"budget stop {code}")
        return out("ARCH_BUDGET", "HIGH")
    if code in CONTRACT_CODES:
        notes.append(f"the provider rejected the request CreditProbe assembled ({code})")
        return out("ARCH_CONTRACT", "HIGH")
    if code in INFRA_CODES:
        notes.append(f"infrastructure/orchestration failure {code}")
        return out("ARCH_ORCHESTRATION", "HIGH")
    if code in FORMAT_CODES:
        secondary.append("ARCH_CONTRACT")
        notes.append(f"format recoveries exhausted ({code})")
        return out("MODEL_TOOL_USE", "HIGH")
    if code == "NO_PROGRESS":
        secondary.append("MODEL_REPAIR")
        notes.append("no-progress guard stopped a repeating repair")
        return out("ARCH_REPAIR_LOOP", "HIGH")
    if "must be one of" in ev_text and "disposition" in ev_text:
        notes.append("finalize refused over the disposition enum mismatch (schema offers 'partial', parser wants 'partial_answer')")
        return out("ARCH_CONTRACT", "HIGH")
    if code == "ANSWER_VALIDATION" or (v.behaviour_observed in ("FAILED", "PARTIAL")
                                       and "answer_check" in ev_text):
        art_ok = v.numeric_artifact_only > 0 and v.numeric_wrong == 0
        if art_ok:
            secondary.append("MODEL_PRESENTATION")
            notes.append("correct figures were in the artifacts; the answer failed validation")
            return out("ARCH_VALIDATION" if v.numeric_published == 0 else "MODEL_PRESENTATION", "HIGH")
        notes.append("answer failed the finalizer's evidence validation")
        return out("MODEL_PRESENTATION", "MEDIUM")
    if any(r.get("would_have_been_correct") for r in replay):
        notes.append("the validator rejected a submission that replays to the correct answer")
        return out("ARCH_VALIDATION", "HIGH")
    if not v.behaviour_ok:
        exp, obs = v.behaviour_expected, v.behaviour_observed
        if exp == "ANSWER" and obs == "CLARIFY":
            if turn > 1:
                secondary.append("ARCH_CONTEXT")
            notes.append("clarified a question the oracle marks answerable")
            return out("MODEL_UNDERSTANDING", "MEDIUM")
        if exp == "CLARIFY" and obs == "ANSWER":
            notes.append("answered a question that needs clarification")
            return out("MODEL_UNDERSTANDING", "HIGH")
        if exp == "DECLINE" and obs in ("ANSWER", "PARTIAL"):
            notes.append("answered with numbers outside the governed universe" if v.forbidden_violations else "answered a decline case")
            return out("MODEL_UNDERSTANDING", "CRITICAL" if v.forbidden_violations else "MEDIUM")
        if exp in ("ANSWER",) and obs in ("UNSUPPORTED", "REFER", "PARTIAL") and sub.get("submissions") \
                and not sub.get("any_success"):
            n = int(sub.get("submissions") or 0)
            notes.append(f"{n} submission(s), none executed successfully ({sub.get('statuses')}), then declined")
            return out("MODEL_CODE" if n == 1 else "MODEL_REPAIR", "HIGH")
        if exp in ("ANSWER",) and obs in ("UNSUPPORTED", "REFER"):
            notes.append("declined an answerable question")
            return out("MODEL_UNDERSTANDING", "HIGH")
        if obs == "FAILED":
            notes.append(f"run failed with {code}")
            return out("ARCH_ORCHESTRATION", "HIGH")
        notes.append(f"behaviour {obs} vs {exp}")
        return out("MODEL_UNDERSTANDING", "MEDIUM")
    if v.forbidden_violations:
        notes.append(",".join(v.forbidden_violations))
        crit = any("numbers_outside" in f or "destructive" in f for f in v.forbidden_violations)
        return out("MODEL_UNDERSTANDING", "CRITICAL" if crit else "HIGH")
    if v.oracle_pass is False:
        statuses = [f["status"] for f in v.facts]
        if sub.get("submissions", 0) == 0 and v.numeric_required:
            notes.append("no analysis was executed for a numeric question")
            return out("MODEL_TOOL_USE", "HIGH")
        if statuses and all(s in ("ARTIFACT_ONLY",) or s.startswith("PUBLISHED") for s in statuses):
            notes.append("every required figure was computed correctly but not all were published")
            return out("MODEL_PRESENTATION", "MEDIUM")
        if any(s == "WRONG_PERIOD" for s in statuses):
            if turn > 1:
                secondary.append("ARCH_CONTEXT")
            notes.append("published a figure for the wrong period")
            return out("MODEL_UNDERSTANDING", "HIGH")
        if any(s == "WRONG_POPULATION" for s in statuses):
            if turn > 1:
                secondary.append("ARCH_CONTEXT")
            notes.append("published a figure for the wrong population")
            return out("MODEL_UNDERSTANDING", "HIGH")
        if any(s == "WRONG_METHOD" for s in statuses) or any(s == "VALUE_MISMATCH" for s in statuses):
            notes.append("computed a different value for a requested figure")
            return out("MODEL_CODE", "HIGH")
        if v.ranking.get("required") and not v.ranking.get("ok"):
            notes.append(f"ranking differs: {v.ranking.get('published')} vs {v.ranking.get('expected')}")
            return out("MODEL_CODE" if not v.ranking.get("set_ok") else "MODEL_PRESENTATION", "MEDIUM")
        if v.members.get("required") and not v.members.get("ok"):
            notes.append(f"membership differs: missing {v.members.get('missing')} extra {v.members.get('extra')}")
            return out("MODEL_CODE", "HIGH")
        if any(c["status"] == "INCORRECT" for c in v.claims):
            notes.append("a published claim contradicts the oracle")
            return out("MODEL_CODE", "HIGH")
        notes.append(f"required figures not published: {statuses}")
        return out("MODEL_UNDERSTANDING", "MEDIUM")
    if v.preservation and not v.preservation.get("ok"):
        notes.append("numbers changed during a presentation-only turn")
        return out("MODEL_PRESENTATION", "HIGH")
    notes.append("unclassified: " + "; ".join(v.failure_reasons))
    return out("ARCH_ORCHESTRATION", "MEDIUM")
