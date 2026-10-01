"""P16: the first-launch libraries are populated from PERSISTED objects and
are materially distinct -- no group duplicated under different titles.

Counts are measured from the store after first launch, never read from a
constant; readiness comes from the real preview of each template.

EVIDENCE LABEL: REAL DATABASE (governed candidate books, real store);
NO MODEL.
"""

# ruff: noqa: F811

from __future__ import annotations

import json
from collections import Counter

from backend.workspace import access, lenses, scenarios
from backend.workspace import scenario_library as lib
from backend.workspace.objects import Principal
from tests.cockpit_v4.test_gw_monitoring import WHO, svc  # noqa: F401


def _templates(svc):
    scenarios.ensure_seeded(svc, WHO)
    p = Principal.of(WHO)
    return [o for o in svc.list("scenario", p) if o["owner_id"] != WHO["id"]]


def _signature(o):
    return json.dumps([o["domain_id"], o["body"]["scope"], sorted(
        json.dumps({k: c.get(k) for k in ("kind", "field", "operation",
                                          "value", "factor_id", "shock")},
                   sort_keys=True) for c in o["body"]["components"])],
        sort_keys=True, default=str)


def test_the_scenario_library_is_persisted_distinct_and_honest(svc):
    found = _templates(svc)
    by_book = Counter(o["domain_id"] for o in found)
    assert by_book["corporate"] >= 18 and by_book["retail"] >= 18
    macro = [o for o in found if any(c["kind"] == "macro"
                                     for c in o["body"]["components"])]
    assert len(macro) >= 6
    sigs = Counter(_signature(o) for o in found)
    assert max(sigs.values()) == 1, "no definition is duplicated"
    # Names are unique within a book (the specification itself names
    # CORP-17 and RET-17 both "Cure sensitivity upside").
    names = Counter((o["domain_id"], o["body"]["name"]) for o in found)
    assert max(names.values()) == 1
    readiness = Counter()
    for o in found:
        out = lib.preview(access.book(WHO, o["domain_id"]), o["body"])
        readiness[out["readiness"]] += 1
        if out["readiness"] == "BLOCKED":
            assert out["blocking"], (o["body"]["name"], "a block names why")
    assert readiness["READY_FOR_CONFIRMATION"] >= 20
    assert readiness["BLOCKED"] >= 1 and \
        readiness["READY_WITH_USER_DEFINED_INPUTS"] >= 1, \
        "honest statuses, not everything READY"


def test_the_lens_library_is_persisted_diverse_and_not_duplicated(svc):
    lenses.ensure_seeded(svc, WHO)
    found = svc.list("lens", Principal.of(WHO))
    assert len(found) >= 18
    personas = {o["body"]["persona"] for o in found}
    assert len(personas) >= 12
    layouts = Counter(json.dumps(sorted(
        (v["type"], v.get("metric_id") or ",".join(v.get("metric_ids") or []),
         v.get("group_by", ""), v["domain"]) for v in o["body"]["visuals"]))
        for o in found)
    assert max(layouts.values()) == 1, "no Lens is another under a new name"
    for o in found:
        b = o["body"]
        assert b["refresh"]["cadence"] and b["visuals"] and b["metrics"]
