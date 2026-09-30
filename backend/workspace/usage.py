"""Which Lenses, rules and issue detectors use a metric (lineage drill-down)."""

from __future__ import annotations

from typing import Any

from backend.workspace import issues, service


def metric_usage(who: dict[str, Any], metric_id: str) -> dict[str, Any]:
    principal = service.principal(who)
    lenses, rules = [], []
    try:
        for lens in service.objects().list("lens", principal):
            body = lens["body"]
            if any(m.get("metric_id") == metric_id
                   for m in body.get("metrics", [])):
                lenses.append({"object_id": lens["object_id"],
                               "title": lens["title"],
                               "version": lens["version"]})
            for rule in body.get("breach_rules", []):
                if rule.get("metric_id") == metric_id:
                    rules.append({"lens_id": lens["object_id"],
                                  "rule_id": rule.get("rule_id"),
                                  "title": rule.get("name")})
    except Exception:  # noqa: BLE001 - usage is supporting information
        pass
    detectors = [p["id"] for p in issues.PATTERNS if p["metric"] == metric_id]
    return {"lenses": lenses, "breach_rules": rules,
            "issue_detectors": detectors}


__all__ = ["metric_usage"]
