"""A Scenario Definition + a governed cohort -> ONE engine `ScenarioSpec`.

The What-If workspace defines no scenario semantics of its own. Every
component is expressed as ordinary engine shocks (`scenario.spec.Shock`) over
the cohort's frozen rows, and the engine's Delta / ML / User-defined code runs
them (`bridge.compute_core`):

* parameter / utilisation -> one shock on the field (utilisation moves the
  drawn balance or retail balance with the limit held);
* macro and property-collateral -> the governed sensitivity translation's
  absolute-pp moves on PD / LGD. Macro components that reach the same
  population are merged into ONE shock per parameter (the §7.2 linear sum,
  exact because ECL is linear in each parameter) and each factor's share is
  reported pro rata to its pp -- exact for the same reason;
* rating -> per current grade, PD multiplied by the ratio of the governed
  masterscale PDs (12-month and lifetime separately);
* behavioural score -> per product scorecard band, 12-month PD multiplied by
  the ratio of the governed band PDs;
* a component that reaches only part of the cohort is scoped by the explicit
  member list `{key: [ids]}` resolved through the grid view.

Overlaps follow the definition's explicit policy: `compound` is declared to
the engine (Delta's multiplicative compounding); `priority`, `max` and `min`
PARTITION the shared rows so exactly one component moves each row; `additive`
merges the two moves on the shared rows into one. Nothing is defaulted.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from backend.cockpit_v4.scenario import cohort as ch
from backend.cockpit_v4.scenario import spec as sp
from backend.cockpit_v4.scenario import units as un
from backend.workspace import grid, predicates
from backend.workspace import scenario_library as lib
from backend.workspace.access import Book

#: Components the Delta method can express, by kind.
DELTA_KINDS = ("parameter", "utilisation", "macro", "collateral", "rating",
               "score")

#: Taxonomy id of each component kind (`scenario.decomposition`).
KIND_COMPONENT = {"utilisation": "ccf_ead", "macro": "macro",
                  "collateral": "collateral", "rating": "rating_score",
                  "score": "rating_score", "overlay": "management_overlay",
                  "delinquency": "rating_score"}


@dataclass
class Built:
    """What the workspace hands the engine, and what it needs back."""

    spec: sp.ScenarioSpec
    frozen: ch.Frozen
    component_of: dict[str, str] = field(default_factory=dict)
    details: dict[str, dict[str, Any]] = field(default_factory=dict)
    #: Per method, the components it cannot express, named (never dropped).
    blockers: dict[str, list[str]] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def _q(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.0000000001")))


def members(book: Book, frozen: ch.Frozen) -> list[str]:
    g = ch.GRAIN[book.domain_id]
    where = f"{g['period']} = '{frozen.period}'"
    if frozen.predicate:
        where += f" AND ({frozen.predicate})"
    if frozen.selection == ch.BY_OWNER:
        where = (f"{g['period']} = '{frozen.period}' AND {g['owner']} IN "
                 f"(SELECT {g['owner']} FROM {g['relation']} WHERE {where})")
    return [str(r["k"]) for r in book.rows(
        f"SELECT {g['key']} AS k FROM {g['relation']} WHERE {where} "
        f"ORDER BY 1")]


def _scope_literal(scope: dict[str, Any], v: grid.View) -> str:
    """A scope as literal SQL over the grid view (values escaped by
    `predicates.literal`, the function a governed cohort's predicate uses)."""
    kind = scope["type"]
    if kind == "whole_book":
        return ""
    if kind in ("filters", "cohort"):
        return predicates.literal(scope["filters"]) if scope.get("filters") \
            else ""
    if kind == "top_owners":
        return lib.scope_sql(scope, v)[0]
    if kind == "any_of":
        return "(" + " OR ".join(_scope_literal(s, v) or "TRUE"
                                 for s in scope["scopes"]) + ")"
    raise AssertionError(kind)  # pragma: no cover


def frozen_for_scope(book: Book, scope: dict[str, Any], *, label: str = ""
                     ) -> ch.Frozen:
    """A definition's own scope, frozen by the engine (no cohort object).

    Filters freeze exactly as a grid cohort does (`cohorts.resolve`), so the
    same filters give the same membership hash on every route.
    """
    from backend.workspace import cohorts

    v = grid.view(book)
    if scope["type"] in ("filters", "cohort") and scope.get("filters"):
        _v, _c, frozen = cohorts.resolve(book, filters=scope["filters"])
        return frozen
    inner = _scope_literal(scope, v)
    predicate = (f"{v.key} IN (SELECT {v.key} FROM ({v.sql}) gwv WHERE "
                 f"{inner})") if inner else ""
    return ch.freeze(session=book.session, scope=book.scope,
                     predicate=predicate, period=v.period,
                     described_as=label or scope.get("label", ""))


def _population(book: Book, v: grid.View, cohort_ids: list[str],
                component: dict[str, Any]) -> set[str]:
    """The cohort rows this component reaches, through the grid view."""
    if not component.get("where") and not component.get("within"):
        return set(cohort_ids)
    cond, params = lib.component_sql(component, v)
    found = {str(r["k"]) for r in book.rows(
        f"SELECT {v.key} AS k FROM ({v.sql}) g WHERE {cond}", params)}
    return found & set(cohort_ids)


def _where(v: grid.View, ids: set[str], cohort: set[str]) -> dict[str, Any]:
    """`{}` for the whole cohort, else the explicit member list (IN)."""
    if ids == cohort:
        return {}
    return {v.key: sorted(ids)}


def build(book: Book, definition: dict[str, Any], *, frozen: ch.Frozen,
          scenario_id: str, version: int, name: str,
          baseline: dict[str, Any] | None = None) -> Built:
    """The engine spec for this definition over this frozen cohort."""
    v = grid.view(book, frozen.period)
    cohort_ids = members(book, frozen)
    cohort = set(cohort_ids)
    rows = {str(r["k"]): r for r in book.rows(
        f"SELECT {v.key} AS k, {v.owner} AS owner, pd_pit_12m, pd_lifetime, "
        f"lgd_pct, stage FROM ({v.sql}) g", [])} if cohort_ids else {}
    out = Built(spec=None, frozen=frozen)  # type: ignore[arg-type]
    assessed = {c["component_id"]: c for c in (
        lib.assess_component(book, v, comp, scope_cond="TRUE",
                             scope_params=[])
        for comp in definition["components"])}
    # Per component: a list of (field, operation, value, ids, origin, meta).
    moves: dict[str, list[dict[str, Any]]] = {}
    pops: dict[str, set[str]] = {}
    for comp in definition["components"]:
        cid = comp["component_id"]
        a = assessed[cid]
        pop = _population(book, v, cohort_ids, comp)
        pops[cid] = pop
        label = f"{cid} · {comp['label']}"[:80]
        kind = comp["kind"]
        out.component_of[label] = (
            lib_field_component(comp) if kind == "parameter"
            else KIND_COMPONENT.get(kind, "sector_segment"))
        # UNSUPPORTED, TRANSLATION_ONLY and NEEDS_USER_MAPPING components
        # are never approximated: they block Delta (and ML) BY NAME, and the
        # reader may still state the effect under User-defined.
        for method in (sp.DELTA, sp.ML):
            if a["methods"].get(method) != "COMPATIBLE":
                out.blockers.setdefault(method, []).append(
                    f"{comp['label']} ({a['status']}: "
                    f"{a.get('reason') or 'no governed translation'})")
        if a["methods"].get("delta") != "COMPATIBLE":
            moves[cid] = []
            continue
        tr = a.get("translation") or {}
        for w in tr.get("warnings") or []:
            out.notes.append(f"{comp['label']}: {w}")
        if kind in ("parameter", "utilisation"):
            moves[cid] = [{"field": tr["field"], "operation": tr["operation"],
                           "value": tr["value"], "ids": pop,
                           "origin": label}]
        elif kind in ("macro", "collateral"):
            moves[cid] = [{"field": d["field"], "operation": "absolute_pp",
                           "value": d["value"], "ids": pop, "origin": label,
                           "macro": {"kind": kind,
                                     "factor": tr.get("factor_id"),
                                     "factor_name": tr.get("factor_name"),
                                     "artifact_version":
                                     d.get("artifact_version", "")}}
                          for d in tr.get("derived") or []]
        elif kind == "rating":
            moves[cid] = _rating_moves(book, v, pop, rows, comp, label)
        elif kind == "score":
            moves[cid] = _score_moves(book, v, pop, comp, label)
    _resolve_overlaps(definition, assessed, moves, pops, rows)
    shocks, compositions = _to_shocks(v, cohort, moves, out)
    out.spec = sp.ScenarioSpec(
        scenario_id=scenario_id, version=version,
        source=sp.SourceRef(domain_id=book.domain_id,
                            release_id=frozen.release_id,
                            release_fingerprint=frozen.release_fingerprint,
                            reporting_period=frozen.period),
        cohort=frozen.ref, shocks=tuple(shocks),
        stage_policy=("frozen" if definition["stage_policy"] == "frozen"
                      else "explicit"),
        bounds_policy=dict(definition.get("bounds_policy") or {}),
        baseline=dict(baseline or {}), compositions=tuple(compositions),
        name=name[:120],
        original_clauses=tuple(c["label"] for c in
                               definition["components"]))
    return out


def lib_field_component(comp: dict[str, Any]) -> str:
    from backend.cockpit_v4.scenario import decomposition as dc

    return dc.FIELD_COMPONENT.get(comp.get("field", ""), "sector_segment")


def _rating_moves(book: Book, v: grid.View, pop: set[str],
                  rows: dict[str, Any], comp: dict[str, Any], label: str
                  ) -> list[dict[str, Any]]:
    """Per current grade: PD x (mapped PD of new grade / of old grade)."""
    scale = book.rows("SELECT rating_grade, grade_rank, pd_12m, pd_lifetime, "
                      "is_default_grade FROM whatif_corp_rating_map ORDER BY "
                      "grade_rank")
    by_grade = {r["rating_grade"]: r for r in scale}
    live = [r for r in scale if not r["is_default_grade"]]
    worst = max(r["grade_rank"] for r in live)
    by_rank = {r["grade_rank"]: r for r in live}
    notches = int(comp["value"])
    graded = book.rows(f"SELECT {v.key} AS k, rating_current AS g FROM "
                       f"({v.sql}) g0")
    groups: dict[str, set[str]] = defaultdict(set)
    for r in graded:
        if str(r["k"]) in pop:
            groups[str(r["g"])].add(str(r["k"]))
    out = []
    for grade, ids in sorted(groups.items()):
        cur = by_grade.get(grade)
        if cur is None:
            continue
        new = by_rank[min(max(cur["grade_rank"] + notches, 1), worst)]
        for fld, col in (("pd_pit_12m", "pd_12m"),
                         ("pd_lifetime", "pd_lifetime")):
            if not cur[col]:
                continue
            ratio = Decimal(str(new[col])) / Decimal(str(cur[col]))
            out.append({"field": fld, "operation": "multiply",
                        "value": _q(ratio), "ids": ids, "origin": label,
                        "group": f"{grade}→{new['rating_grade']}"})
    return out


def _score_moves(book: Book, v: grid.View, pop: set[str],
                 comp: dict[str, Any], label: str) -> list[dict[str, Any]]:
    """Per product scorecard band: 12-month PD x band PD ratio."""
    period = book.latest_period
    smap = book.rows("SELECT product, band_low, band_high, pd_12m FROM "
                     "whatif_retail_score_map WHERE score_type = ? AND "
                     "reporting_month = ? ORDER BY product, band_low",
                     [comp["score_type"], period])
    by_product: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in smap:
        by_product[str(r["product"])].append(r)
    column = ("behaviour_score" if comp["score_type"] == "BEHAVIOURAL"
              else "application_score")
    scored = book.rows(f"SELECT {v.key} AS k, product, {column} AS s FROM "
                       f"({v.sql}) g0")
    value = Decimal(comp["value"])
    groups: dict[tuple[str, int, int], set[str]] = defaultdict(set)
    for r in scored:
        k = str(r["k"])
        if k not in pop or r["s"] is None:
            continue
        product = str(r["product"]) if comp["score_type"] == "BEHAVIOURAL" \
            else "ALL"
        bands = by_product.get(product) or []
        s = Decimal(str(r["s"]))
        ix = next((i for i, b in enumerate(bands)
                   if Decimal(str(b["band_low"])) <= s
                   < Decimal(str(b["band_high"])) + 1), None)
        if ix is None:
            continue
        if comp["operation"] == "points":
            ns = s + value
            jx = next((i for i, b in enumerate(bands)
                       if Decimal(str(b["band_low"])) <= ns
                       < Decimal(str(b["band_high"])) + 1), None)
            if jx is None:
                jx = 0 if value < 0 else len(bands) - 1
        else:
            jx = min(max(ix + int(value), 0), len(bands) - 1)
        groups[(product, ix, jx)].add(k)
    out = []
    for (product, ix, jx), ids in sorted(groups.items()):
        bands = by_product.get(product) or []
        old, new = Decimal(str(bands[ix]["pd_12m"])), \
            Decimal(str(bands[jx]["pd_12m"]))
        if ix == jx or not old:
            continue
        out.append({"field": "pd_pit_12m", "operation": "multiply",
                    "value": _q(new / old), "ids": ids, "origin": label,
                    "group": f"{product} band {ix}→{jx}"})
    return out


def _moved(row: dict[str, Any], move: dict[str, Any]) -> Decimal:
    base = Decimal(str(row.get(move["field"]) or 0))
    storage = un.PERCENT if move["field"] == "lgd_pct" else un.FRACTION
    return un.apply(base, un.parse(move["value"], move["operation"]),
                    storage=storage)


def _resolve_overlaps(definition: dict[str, Any], assessed: dict[str, Any],
                      moves: dict[str, list[dict[str, Any]]],
                      pops: dict[str, set[str]], rows: dict[str, Any]
                      ) -> None:
    """Apply each explicit overlap policy to the moves, in place."""
    resolutions = definition["composition_policy"]["resolutions"]
    for oid, res in resolutions.items():
        parts = oid.split("|")
        if len(parts) != 3:
            continue
        a, b, family = parts
        if a not in moves or b not in moves:
            continue
        shared = pops.get(a, set()) & pops.get(b, set())
        if not shared:
            continue
        policy = res["policy"]
        fields = {f for f in ("pd_pit_12m", "pd_lifetime") if family == "pd"} \
            or ({"lgd_pct"} if family == "lgd" else
                {"drawn_sar_mn", "balance_sar_mn", "ccf", "ead_sar_mn"})
        if policy == "compound":
            continue  # declared to the engine in `_to_shocks`
        order = res.get("order") or [a, b]
        if policy == "priority":
            loser = order[1] if order[0] in (a, b) else b
            for m in moves[loser]:
                if m["field"] in fields:
                    m["ids"] = set(m["ids"]) - shared
        elif policy in ("max", "min"):
            win_a: set[str] = set()
            for k in shared:
                row = rows.get(k, {})
                va = [_moved(row, m) for m in moves[a]
                      if m["field"] in fields and k in m["ids"]]
                vb = [_moved(row, m) for m in moves[b]
                      if m["field"] in fields and k in m["ids"]]
                sa, sb = (max(va) if va else None), (max(vb) if vb else None)
                if sa is None or sb is None:
                    continue
                if (sa >= sb) == (policy == "max"):
                    win_a.add(k)
            for m in moves[a]:
                if m["field"] in fields:
                    m["ids"] = set(m["ids"]) - (shared - win_a)
            for m in moves[b]:
                if m["field"] in fields:
                    m["ids"] = set(m["ids"]) - win_a
        elif policy == "additive":
            merged = []
            for ma in moves[a]:
                for mb in moves[b]:
                    if ma["field"] == mb["field"] and ma["field"] in fields \
                            and ma["operation"] == mb["operation"]:
                        on = set(ma["ids"]) & set(mb["ids"]) & shared
                        if not on:
                            continue
                        merged.append({
                            "field": ma["field"], "operation": ma["operation"],
                            "value": str(Decimal(ma["value"]) +
                                         Decimal(mb["value"])),
                            "ids": on, "origin": ma["origin"],
                            "additive_with": mb["origin"]})
                        ma["ids"] = set(ma["ids"]) - on
                        mb["ids"] = set(mb["ids"]) - on
            moves[a].extend(merged)


def _to_shocks(v: grid.View, cohort: set[str],
               moves: dict[str, list[dict[str, Any]]], out: Built
               ) -> tuple[list[sp.Shock], list[dict[str, Any]]]:
    """Engine shocks, with macro moves merged per field and population."""
    shocks: list[sp.Shock] = []
    macro: dict[tuple[str, str, frozenset[str]], list[dict[str, Any]]] = \
        defaultdict(list)
    for ms in moves.values():
        for m in ms:
            if not m["ids"]:
                continue
            if "macro" in m:
                macro[(m["macro"]["kind"], m["field"],
                       frozenset(m["ids"]))].append(m)
                continue
            shocks.append(sp.Shock(
                field_id=m["field"],
                amount=un.parse(m["value"], m["operation"], m["origin"]),
                where=_where(v, set(m["ids"]), cohort), origin=m["origin"]))
    for (kind, fld, ids), ms in macro.items():
        total = sum((Decimal(m["value"]) for m in ms), Decimal(0))
        origin = ms[0]["origin"] if len({m["origin"] for m in ms}) == 1 \
            else ("Macro: " if kind == "macro" else "Collateral: ") + \
            " + ".join(sorted({m["origin"] for m in ms}))
        origin = origin[:80]
        out.component_of[origin] = KIND_COMPONENT[kind]
        out.details.setdefault(origin, {})["factors"] = [
            {"origin": m["origin"], "factor": m["macro"]["factor"],
             "field": fld, "pp": m["value"],
             "share": str((Decimal(m["value"]) / total)
                          .quantize(Decimal("0.0001"))) if total else "0"}
            for m in ms]
        shocks.append(sp.Shock(
            field_id=fld, amount=un.parse(_q(total), "absolute_pp", origin),
            where=_where(v, set(ids), cohort), origin=origin,
            mapping_version=ms[0]["macro"]["artifact_version"]))
    # Every remaining same-field overlap was resolved as `compound` (or is
    # two groups of one component): declare it, so Delta compounds them.
    probe = sp.ScenarioSpec(
        scenario_id="probe", version=1,
        source=sp.SourceRef("", "", "", ""),
        cohort=sp.CohortRef("", "", "", 0), shocks=tuple(shocks))
    compositions = [{"pair": [left.canonical(), right.canonical()],
                     "composition": "compound"}
                    for left, right in probe.conflicts()]
    return shocks, compositions


__all__ = ["Built", "DELTA_KINDS", "KIND_COMPONENT", "build", "frozen_for_scope",
           "members"]
