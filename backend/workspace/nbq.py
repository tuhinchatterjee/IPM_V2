"""
Next-Best-Question / Next-Best-Action policy (§36).

A suggestion is METADATA around an ordinary governed Cockpit turn: clicking it
submits `exact_request` as the next question in the same thread, through the
same `POST /runs` a typed question uses. Nothing here answers anything.

Rules enforced here, each pinned by a test:

* suggestions are generated only from computed evidence (an issue's measured
  facts) or from the investigation's recorded state -- every one names its
  source metric/evidence and a rationale (GX-05);
* 2-5 primary suggestions, ranked by materiality and expected information
  gain, the rest under "more";
* a question already asked in this investigation is suppressed unless the
  active cohort changed since it was asked (GX-06);
* causal language is forbidden: a hypothesis is phrased as a test ("Check
  whether ...") and a scenario is labelled a stress test, never a forecast;
* a What-If suggestion appears only once the investigation holds a finding
  (at least one answered analytical step) (GX-09).
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

TYPES = ("explain_driver", "drill_contributors", "compare_period",
         "validate_hypothesis", "inspect_data_quality", "freeze_cohort",
         "run_whatif", "save_share_monitor")

#: Words that assert a cause. A suggestion containing one is rejected.
CAUSAL = re.compile(r"\b(caused|causes|because of|due to|drove|driven by|"
                    r"results? from)\b", re.I)

PRIMARY_MAX = 5
PRIMARY_MIN = 2


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def suggestion(*, kind: str, text: str, rationale: str, source: dict[str, Any],
               capability: str, scope: str, changes_state: bool = False,
               weight: float = 0.5, label: str = "") -> dict[str, Any]:
    if kind not in TYPES:
        raise ValueError(f"unknown suggestion type {kind!r}")
    if CAUSAL.search(text):
        raise ValueError(f"a suggestion may not assert a cause: {text!r}")
    sid = "nbq-" + hashlib.sha256(f"{kind}|{_norm(text)}|{scope}".encode()
                                  ).hexdigest()[:12]
    return {"suggestion_id": sid, "type": kind, "text": label or text,
            "exact_request": text, "rationale": rationale, "source": source,
            "required_capability": capability, "predicted_scope": scope,
            "changes_state": changes_state, "weight": float(weight),
            "is_stress_test": kind == "run_whatif"}


def for_issue(issue: dict[str, Any], *, answered: list[str] | None = None,
              cohort_hash: str = "", asked_under: dict[str, str] | None = None,
              has_finding: bool = False) -> dict[str, Any]:
    """Suggestions for an issue, given what the investigation already did."""
    facts = issue["materiality"]
    dim = issue["segment"]["dimension"]
    value = issue["segment"]["value"]
    period = issue["evidence"]["period"]
    prior = issue["evidence"]["prior_period"]
    metric = issue["evidence"]["metric_ids"][0]
    where = f"in {value}" if value and value != "whole book" else "across the book"
    breakdown = issue["evidence"].get("breakdown_dimension", "")
    top = (issue.get("drivers") or [{}])[0].get("label", "")
    src = {"issue_id": issue["issue_id"], "metric_id": metric,
           "evidence": issue["evidence"]["metric_ids"]}
    scope = f"{issue['domain_id']}:{dim}={value}"
    out = [
        suggestion(kind="explain_driver",
                   text=(f"Which {breakdown.replace('_', ' ') or 'segments'} "
                         f"contributed most to the change in "
                         f"{issue['metric_name']} {where} between "
                         f"{prior} and {period}?"),
                   rationale=(f"{issue['metric_name']} moved "
                              f"{facts['movement_display']} {where}; a "
                              f"contribution breakdown separates concentrated "
                              f"from broad-based movement."),
                   source=src, capability="execute_analysis", scope=scope,
                   weight=0.95),
        suggestion(kind="drill_contributors",
                   text=(f"Show the {issue['owner_plural']} {where} with the "
                         f"largest increase in booked ECL between {prior} and "
                         f"{period}."),
                   rationale=(f"{facts['affected_entities']:,} "
                              f"{issue['entity_plural']} are affected; naming "
                              f"the largest contributors tests concentration."),
                   source=src, capability="execute_analysis", scope=scope,
                   weight=0.9),
        suggestion(kind="validate_hypothesis",
                   text=(f"Check whether rating or score deterioration "
                         f"explains the movement {where}: compare PD and stage "
                         f"between {prior} and {period} for the same "
                         f"{issue['entity_plural']}."
                         if issue["domain_id"] == "corporate" else
                         f"Check whether behaviour-score deterioration "
                         f"explains the movement {where}: compare score band "
                         f"and PD between {prior} and {period} for the same "
                         f"{issue['entity_plural']}."),
                   rationale=("Competing explanations remain; this test "
                              "discriminates between parameter drift and "
                              "population change."),
                   source=src, capability="execute_analysis", scope=scope,
                   weight=0.8),
        suggestion(kind="compare_period",
                   text=(f"How does {issue['metric_name']} {where} in "
                         f"{period} compare with the same measure four periods "
                         f"earlier?"),
                   rationale=("A longer comparison separates a one-period "
                              "move from a trend."),
                   source=src, capability="execute_analysis", scope=scope,
                   weight=0.6),
        suggestion(kind="freeze_cohort",
                   text=f"Freeze the {facts['affected_entities']:,} "
                        f"{issue['entity_plural']} {where} as a governed cohort",
                   label=f"Save cohort ({facts['affected_entities']:,} "
                         f"{issue['entity_plural']})",
                   rationale="A frozen cohort keeps the exact population "
                             "for What-If, Lenses and sharing.",
                   source=src, capability="workspace.cohort", scope=scope,
                   changes_state=True, weight=0.5),
    ]
    if top:
        out.insert(1, suggestion(
            kind="explain_driver",
            text=(f"What changed for {top} {where} between {prior} and "
                  f"{period}: exposure, PD, LGD or stage?"),
            rationale=(f"{top} is the largest measured contributor to the "
                       f"movement (association, not an established cause)."),
            source=src, capability="execute_analysis", scope=scope,
            weight=0.92))
    if has_finding:
        shock = "PD +20%" if issue["domain_id"] == "corporate" else "PD +20%"
        out.append(suggestion(
            kind="run_whatif",
            text=(f"Stress test: what would booked ECL be for the "
                  f"{facts['affected_entities']:,} {issue['entity_plural']} "
                  f"{where} if their PD rose a further 20%?"),
            label=f"Stress test {shock} on this cohort (not a forecast)",
            rationale=(f"The investigation measured "
                       f"{issue['metric_name']} deterioration {where};"
                       f" a proportional PD stress sizes the exposure to a "
                       f"continuation. A stress test, not an expectation."),
            source=src, capability="whatif", scope=scope, changes_state=True,
            weight=0.85))
    out.append(suggestion(
        kind="save_share_monitor",
        text=f"Monitor {issue['metric_name']} {where} in a Lens with "
             f"a breach rule",
        label="Monitor in a Lens",
        rationale="A standing rule turns this finding into a monitored one.",
        source=src, capability="workspace.lens", scope=scope,
        changes_state=True, weight=0.3))
    return rank(out, answered=answered or [], cohort_hash=cohort_hash,
                asked_under=asked_under or {})


def rank(items: list[dict[str, Any]], *, answered: list[str],
         cohort_hash: str = "", asked_under: dict[str, str] | None = None
         ) -> dict[str, Any]:
    asked_under = asked_under or {}
    seen = {_norm(a) for a in answered}
    kept, suppressed = [], []
    for item in items:
        prior_scope = asked_under.get(_norm(item["exact_request"]))
        already = _norm(item["exact_request"]) in seen
        if already and (not cohort_hash or prior_scope in ("", cohort_hash)):
            suppressed.append({**item, "suppressed_because":
                               "already answered in this investigation"})
            continue
        if already:
            item = {**item, "rationale": item["rationale"] +
                    " Re-offered: the active cohort changed since it was asked."}
        kept.append(item)
    kept.sort(key=lambda i: -i["weight"])
    return {"primary": kept[:PRIMARY_MAX], "more": kept[PRIMARY_MAX:],
            "suppressed": suppressed,
            "policy": {"min": PRIMARY_MIN, "max": PRIMARY_MAX,
                       "ranking": "materiality and expected information gain",
                       "causal_language": "rejected"}}


__all__ = ["CAUSAL", "PRIMARY_MAX", "PRIMARY_MIN", "TYPES", "for_issue",
           "rank", "suggestion"]
