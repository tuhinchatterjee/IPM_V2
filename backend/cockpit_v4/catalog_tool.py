"""
`inspect_catalog`: exact authorized metadata, retrieved selectively.

The V3 behaviour this replaces
------------------------------
V3 attached the whole field dictionary -- 991 addressable relation.column
definitions, every ratio, the expanded macro pivot and a full missingness
table -- to every planning call, whatever the question was. "Who are you?"
paid for the entire corporate data domain.

V4 sends a compact INDEX in the starting context (relation names, one-line
grains, subject families, available quarters) and nothing else. When the
analyst needs a definition it asks for it, and this returns the COMPLETE
metadata for exactly what was asked: definition, unit, grain, aggregation
behaviour, valid joins, coverage and missingness. Selective does not mean
partial -- a field returned with half its definition is worse than one not
returned at all, because the analyst cannot tell it is missing something.

What this tool must never do: choose a field, infer what "exposure" means, or
answer with a plausible schema when the search found nothing. An empty search
is an empty search.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from backend.cockpit_agentic import catalog as v3_catalog
from backend.cockpit_agentic import fields as v3_fields
from backend.cockpit_v4.contracts import CatalogRequest, Rejection

#: The soft output target for one page. Larger requests paginate rather than
#: silently drop fields.
OUTPUT_TARGET_TOKENS = 4_000
MAX_FIELDS_PER_PAGE = 60


@dataclass
class MetadataReceipt:
    """Proof that a specific field's metadata was actually delivered.

    `execute_analysis` checks these: a query naming a field whose definition
    the analyst never read is not refused, but the mismatch is reported, so a
    field used on a guess is visible in the trace rather than invisible in the
    numbers.
    """

    receipt_id: str
    field_ids: tuple[str, ...]
    relation_ids: tuple[str, ...]
    catalog_version: str

    def to_dict(self) -> dict[str, Any]:
        return {"receipt_id": self.receipt_id,
                "field_ids": list(self.field_ids),
                "relation_ids": list(self.relation_ids),
                "catalog_version": self.catalog_version}


@dataclass
class CatalogService:
    """Reads the pinned release's catalog. Never writes, never infers."""

    catalog: Any
    scope: Any
    coverage: Any = None
    session: Any = None
    receipts: dict[str, MetadataReceipt] = field(default_factory=dict)

    # -- helpers ---------------------------------------------------------

    @property
    def catalog_version(self) -> str:
        return str(getattr(self.catalog, "catalog_version", "")
                   or v3_catalog.__dict__.get("CATALOG_VERSION", "v3"))

    def _authorized(self, relation: str) -> bool:
        permits = getattr(self.scope, "permits", None)
        return bool(permits(relation)) if callable(permits) else True

    def _relations(self) -> tuple[str, ...]:
        names = tuple(self.catalog.relations())
        return tuple(n for n in names if self._authorized(n))

    def _field_dict(self, spec: Any, relation: str) -> dict[str, Any]:
        """One field's COMPLETE metadata. Not a fragment of a definition."""
        coverage = self._field_coverage(relation, spec.name)
        out = {
            "field_id": f"{relation}.{spec.name}",
            "relation": relation,
            "column": spec.name,
            "label": getattr(spec, "label", ""),
            "definition": spec.definition,
            "dtype": spec.dtype,
            "unit": getattr(spec, "unit", ""),
            "aggregation": getattr(spec, "aggregation", "not_additive"),
            "nullable": bool(getattr(spec, "nullable", True)),
            "value_origin": getattr(spec, "value_origin", ""),
            "availability": getattr(spec, "availability", ""),
            "missing_reason": getattr(spec, "missing_reason", ""),
            "source_name": getattr(spec, "source_name", ""),
            "lineage": getattr(spec, "lineage", ""),
        }
        enumeration = tuple(getattr(spec, "enumeration", ()) or ())
        if enumeration:
            out["allowed_values"] = list(enumeration)
        if getattr(spec, "currency_scoped", False):
            out["currency"] = getattr(self.catalog, "reporting_currency", "")
            out["amount_scale"] = getattr(self.catalog, "amount_scale", "")
        if getattr(spec, "generated_from", ""):
            out["generated_from"] = spec.generated_from
        if coverage:
            out["coverage"] = coverage
        return out

    def _field_coverage(self, relation: str, column: str
                        ) -> dict[str, Any] | None:
        """Missingness from the measured profile, never from ten sample rows."""
        if self.coverage is None:
            return None
        lookup = getattr(self.coverage, "field", None)
        if callable(lookup):
            try:
                found = lookup(relation, column)
            except Exception:  # noqa: BLE001
                return None
            if found is None:
                return None
            if isinstance(found, dict):
                return found
            to_dict = getattr(found, "to_dict", None)
            return to_dict() if callable(to_dict) else None
        return None

    def _grain(self, relation: str) -> str:
        outline = getattr(self.catalog, "outline", None)
        if callable(outline):
            try:
                doc = outline()
            except Exception:  # noqa: BLE001
                return ""
            for entry in doc.get("relations", []) or []:
                if isinstance(entry, dict) and entry.get("name") == relation:
                    return str(entry.get("grain") or entry.get("purpose") or "")
        return ""

    # -- the tool --------------------------------------------------------

    def inspect(self, request: CatalogRequest) -> dict[str, Any]:
        """Answer one catalog request. Every branch returns what is there."""
        detail = set(request.detail) or {"discovery"}
        out: dict[str, Any] = {
            "status": "ok",
            "catalog_version": self.catalog_version,
            "release_id": getattr(self.scope, "dataset_release_id", ""),
            "reporting_currency": getattr(self.catalog, "reporting_currency",
                                          ""),
            "amount_scale": getattr(self.catalog, "amount_scale", ""),
        }

        relations = self._relations()
        requested_relations = tuple(
            r for r in request.relation_ids if r in relations)
        unknown_relations = tuple(
            r for r in request.relation_ids if r not in relations)
        if unknown_relations:
            # Named, with the authorized alternatives -- and NO substitution.
            out["unknown_relations"] = {
                "requested": list(unknown_relations),
                "authorized_relations": list(relations),
                "note": ("These relations are not in the authorized domain. "
                         "Nothing was substituted for them."),
            }

        if "discovery" in detail:
            terms = [t.strip().lower()
                     for t in request.query.replace(",", " ").split()
                     if len(t.strip()) > 2]
            listed = []
            for relation in relations:
                grain = self._grain(relation)
                if terms and not any(
                        t in relation.lower() or t in grain.lower()
                        for t in terms):
                    continue
                listed.append({"relation": relation, "grain": grain,
                               "column_count": len(
                                   self.catalog.columns(relation))})
            if not listed and terms:
                # An empty search is an empty search. It is NOT an invitation
                # to return the whole catalog and let the model guess.
                out["discovery"] = []
                out["discovery_note"] = (
                    f"No authorized relation matched {request.query!r}. The "
                    f"authorized relations are listed under "
                    f"'authorized_relations'.")
                out["authorized_relations"] = list(relations)
            else:
                out["discovery"] = listed or [
                    {"relation": r, "grain": self._grain(r),
                     "column_count": len(self.catalog.columns(r))}
                    for r in relations]

        delivered_fields: list[str] = []
        if "fields" in detail or request.field_ids:
            wanted: list[tuple[str, str]] = []
            unresolved: list[str] = []
            for field_id in request.field_ids:
                relation, _, column = field_id.partition(".")
                if not column:
                    unresolved.append(field_id)
                    continue
                if relation not in relations:
                    unresolved.append(field_id)
                    continue
                try:
                    self.catalog.resolve(relation, column)
                except Exception:  # noqa: BLE001
                    unresolved.append(field_id)
                    continue
                wanted.append((relation, column))
            for relation in requested_relations:
                if not request.field_ids:
                    wanted.extend((relation, c)
                                  for c in self.catalog.columns(relation))

            start = 0
            if request.cursor:
                try:
                    start = max(0, int(request.cursor))
                except ValueError as exc:
                    raise Rejection(
                        "INVALID_MODEL_OUTPUT",
                        "cursor must be the offset returned by a previous "
                        "page.", field_path="cursor") from exc
            page = wanted[start:start + MAX_FIELDS_PER_PAGE]
            entries = []
            for relation, column in page:
                try:
                    spec = self.catalog.resolve(relation, column)
                except Exception:  # noqa: BLE001
                    unresolved.append(f"{relation}.{column}")
                    continue
                entries.append(self._field_dict(spec, relation))
                delivered_fields.append(f"{relation}.{column}")
            out["fields"] = entries
            if start + MAX_FIELDS_PER_PAGE < len(wanted):
                out["next_cursor"] = str(start + MAX_FIELDS_PER_PAGE)
                out["omitted"] = {
                    "remaining_fields": len(wanted) - (
                        start + MAX_FIELDS_PER_PAGE),
                    "note": ("This page is complete for the fields it lists. "
                             "Request the next page with the cursor; nothing "
                             "was abbreviated."),
                }
            if unresolved:
                out["unresolved_fields"] = {
                    "requested": unresolved,
                    "note": ("These field ids do not exist in the authorized "
                             "catalog. No similar field was substituted. Use "
                             "discovery to find the exact canonical id."),
                }
                for relation, column in (
                        (f.partition('.')[0], f.partition('.')[2])
                        for f in unresolved if '.' in f):
                    alternatives = getattr(self.catalog, "alternatives", None)
                    if callable(alternatives) and relation in relations:
                        try:
                            out.setdefault("alternatives", {})[
                                f"{relation}.{column}"] = list(
                                    alternatives(relation, column))[:8]
                        except Exception:  # noqa: BLE001
                            pass

        if "relationships" in detail:
            joins = getattr(self.catalog, "joins", None)
            out["relationships"] = (
                joins() if callable(joins)
                else _declared_joins(requested_relations or relations))

        if "coverage" in detail:
            calendar = getattr(self.catalog, "calendar", None)
            out["coverage"] = {
                "reporting_quarters": list(getattr(calendar, "slots", ()) or ()),
                "populated_quarters": list(
                    getattr(calendar, "populated", ()) or ()),
                "missing_quarters": list(
                    getattr(calendar, "missing", ()) or ()),
                "note": ("Twenty calendar slots are not twenty observations "
                         "for every facility. A facility that originated "
                         "part-way through the window legitimately has fewer "
                         "rows."),
            }

        if "samples" in detail and request.sample_rows:
            out["samples"] = self._samples(requested_relations,
                                           request.sample_rows)

        receipt = MetadataReceipt(
            receipt_id=f"mr-{uuid.uuid4().hex[:12]}",
            field_ids=tuple(delivered_fields),
            relation_ids=tuple(requested_relations or ()),
            catalog_version=self.catalog_version)
        self.receipts[receipt.receipt_id] = receipt
        out["metadata_receipt_id"] = receipt.receipt_id
        return out

    def _samples(self, relations: tuple[str, ...], rows: int
                 ) -> dict[str, Any]:
        """At most ten masked rows, and never a population profile."""
        if self.session is None:
            return {"status": "unavailable",
                    "reason": ("No execution session is open, so no sample "
                               "can be read. This is not an empty table.")}
        from backend.cockpit_agentic import sql as v3_sql

        out: dict[str, Any] = {"note": (
            "Masked sample rows. These are examples of SHAPE, never a "
            "population profile: do not read a total, a rate or a "
            "distribution off them.")}
        for relation in relations[:2]:
            try:
                result = v3_sql.execute(
                    f"SELECT * FROM {relation} LIMIT {int(rows)}",
                    self.session, deadline_seconds=5.0, max_rows=int(rows))
                out[relation] = {"columns": [c["name"] for c in result.columns],
                                 "rows": result.rows[:int(rows)]}
            except Exception as exc:  # noqa: BLE001
                out[relation] = {"status": "unavailable",
                                 "reason": str(exc)[:200]}
        return out

    def receipt_fields(self, receipt_ids: tuple[str, ...]) -> set[str]:
        found: set[str] = set()
        for receipt_id in receipt_ids:
            receipt = self.receipts.get(receipt_id)
            if receipt is not None:
                found.update(receipt.field_ids)
        return found


def _declared_joins(relations: tuple[str, ...]) -> list[dict[str, Any]]:
    """The joins the domain declares, with the grain warning each carries.

    These are the repetition traps section 12 names. Stating them is not the
    same as enforcing them -- `execute_tool` does the static check -- but an
    analyst that has read them writes fewer of them.
    """
    declared = [
        {"left": v3_fields.BORROWER_FINANCIAL,
         "right": "cockpit_facility_quarter",
         "on": ["borrower_id", "reporting_quarter"],
         "cardinality": "one borrower row to many facility rows",
         "warning": ("A borrower's balance sheet repeats once per facility "
                     "after this join. Aggregate the facility side first, or "
                     "de-duplicate on borrower_id, before summing anything "
                     "from the borrower side.")},
        {"left": v3_fields.COLLATERAL,
         "right": v3_fields.COLLATERAL_ALLOCATION,
         "on": ["collateral_id", "reporting_quarter"],
         "cardinality": "one asset to many facility allocations",
         "warning": ("A shared asset appears once per allocation. Sum the "
                     "ALLOCATED value, never the whole-asset value, across "
                     "facilities.")},
        {"left": "cockpit_facility_quarter", "right": v3_fields.IFRS9_DETAIL,
         "on": ["facility_id", "reporting_quarter"],
         "cardinality": "one facility to many scenario/horizon rows",
         "warning": ("Stored scenario and horizon detail multiplies the "
                     "facility row. Booked ECL is not the sum of scenario "
                     "ECL.")},
        {"left": "cockpit_facility_quarter", "right": v3_fields.COVENANT,
         "on": ["facility_id", "reporting_quarter"],
         "cardinality": "one facility to many covenant tests",
         "warning": ("A borrower-scope covenant binds once, not once per "
                     "facility. Untested is not compliant.")},
    ]
    if not relations:
        return declared
    wanted = set(relations)
    return [j for j in declared
            if j["left"] in wanted or j["right"] in wanted] or declared


__all__ = ["CatalogService", "MAX_FIELDS_PER_PAGE", "MetadataReceipt",
           "OUTPUT_TARGET_TOKENS"]
