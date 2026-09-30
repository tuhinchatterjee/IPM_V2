"""
Governed early-warning rules (EWS rule set v1) over the published books.

Deterministic, versioned SQL over fields the release actually publishes. No
field is invented: where the specification names a signal the candidate book
does not carry directly (a salary-credit feed), the rule is a stated PROXY and
the limitation travels with every card, cohort and metric that uses it.

Each rule is a SQL boolean over the latest-period grid view (`grid.py`
aliases), a severity weight and a reason label. The severity of an entity is
the sum of the weights of the rules it trips, banded:

    >= 6  critical     4-5  high     2-3  moderate     1  low     0  none
"""

from __future__ import annotations

from typing import Any

RULESET_VERSION = "gw-ews-1.0.0"

RULES: dict[str, list[dict[str, Any]]] = {
    "retail": [
        {"id": "R-DPD", "label": "Payment arrears (DPD > 0)",
         "sql": "dpd_days > 0", "weight": 3},
        {"id": "R-SCORE-LOW", "label": "Weak behaviour score band (D/E)",
         "sql": "score_band IN ('D', 'E')", "weight": 1},
        {"id": "R-SCORE-DOWN", "label": "Behaviour score deteriorated",
         "sql": "score_migration = 'Deteriorated'", "weight": 2},
        {"id": "R-UTIL", "label": "High utilisation (>= 85%)",
         "sql": "utilisation_pct >= 85", "weight": 2},
        {"id": "R-MINPAY", "label": "Persistent minimum payment (payment ratio < 35%)",
         "sql": "payment_ratio_pct < 35", "weight": 1},
        {"id": "R-SALARY", "label": "Salary-interruption proxy (salaried, cyclical employer, payment ratio < 35%)",
         "sql": ("employment_type IN ('Salaried-Private', 'Salaried-Government') "
                 "AND employer_sector_group = 'Cyclical' AND payment_ratio_pct < 35"),
         "weight": 2,
         "limitation": ("The candidate book publishes no salary-credit feed. "
                        "This proxy combines employment type, employer sector "
                        "cyclicality and a low payment ratio; it is a governed "
                        "stand-in, not an observed salary interruption.")},
    ],
    "corporate": [
        {"id": "C-WATCH", "label": "On watchlist", "sql": "watchlist_flag = 1",
         "weight": 3},
        {"id": "C-DOWNGRADE", "label": "Rating downgraded this quarter",
         "sql": "rating_notches_moved > 0", "weight": 2},
        {"id": "C-COVENANT", "label": "Covenant breach", "sql": "covenant_breaches > 0",
         "weight": 2},
        {"id": "C-DPD", "label": "Past due (DPD > 0)", "sql": "dpd_days > 0",
         "weight": 3},
        {"id": "C-SICR", "label": "SICR flag raised", "sql": "sicr_flag = 1",
         "weight": 2},
        {"id": "C-UTIL", "label": "High utilisation (>= 90%)",
         "sql": "utilisation_pct >= 90", "weight": 1},
    ],
}

BANDS = ((6, "critical"), (4, "high"), (2, "moderate"), (1, "low"))


def score_sql(domain_id: str, available: set[str]) -> tuple[str, str]:
    """`(score_expr, reasons_expr)` using only rules whose columns exist."""
    parts, reasons = [], []
    for rule in RULES[domain_id]:
        needed = _columns(rule["sql"])
        if not needed <= available:
            continue
        parts.append(f"(CASE WHEN {rule['sql']} THEN {rule['weight']} ELSE 0 END)")
        reasons.append(f"CASE WHEN {rule['sql']} THEN '{rule['label']}' END")
    score = " + ".join(parts) or "0"
    reason = ("concat_ws('; ', " + ", ".join(reasons) + ")") if reasons else "''"
    return score, reason


def band_sql(score: str) -> str:
    whens = " ".join(f"WHEN ({score}) >= {floor} THEN '{name}'"
                     for floor, name in BANDS)
    return f"CASE {whens} ELSE 'none' END"


def _columns(sql: str) -> set[str]:
    import re

    unquoted = re.sub(r"'[^']*'", "", sql)
    words = set(re.findall(r"\b[a-z_][a-z0-9_]*\b", unquoted))
    keywords = {"in", "and", "or", "not", "null", "is", "case", "when", "then",
                "else", "end", "true", "false"}
    return {w for w in words if w not in keywords and not w.isupper()}


def describe(domain_id: str) -> list[dict[str, Any]]:
    return [{k: v for k, v in r.items()} for r in RULES[domain_id]]


__all__ = ["BANDS", "RULESET_VERSION", "RULES", "band_sql", "describe",
           "score_sql"]
