"""
Publishing the projection as a release the frozen engine can open.

Why this writes its own manifest rather than calling `lake.publish`
-------------------------------------------------------------------
`lake.publish` is schema-locked on purpose: it validates a build against the
engine's static `schema.py`, reorders every frame to that spec's columns --
dropping any the spec does not list -- and writes the STATIC spec into the
manifest. That is exactly right for a book the engine's own generator built.

It is wrong for this one. This book carries concepts the engine's synthetic
retail book does not (scenario ECLs, the scorecard inputs, the SICR triggers,
affordability) and lacks two it does (a separately published 12-month and
lifetime allowance). Published through `lake.publish`, the extra columns would
be silently dropped and the two absent ones would have to be invented as
nulls, which is the one thing this integration may not do.

So the release is written here, in the identical format, and the engine reads
it the way it reads any release: `catalog.build` takes the relations, fields,
units, calendar, currency and scale from the manifest the release carries.
The fingerprint is computed by the same rule as `lake._digest` -- SHA-256 over
each published file's name and bytes, in sorted order -- so `lake.verify` and
`release.fingerprint` answer for this release exactly as they do for any
other.

Where it may write
------------------
Under the candidate's own V4 lake and nowhere else. The retail lake and the
retail catalogue are inputs: this module never opens them for writing, and
`config.check_write_target` refuses a path outside the V4 runtime directory
before the first byte.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.cockpit_v4 import lake as lake_mod
from backend.retail_cockpit_adapter import semantic_map as sm
from backend.retail_cockpit_adapter.projection import (project_month,
                                                       relation_fields)
from backend.retail_cockpit_adapter.source import (DATASET, DOMAIN_DISPLAY,
                                                   DOMAIN_ID, Snapshot)

MANIFEST = "manifest.json"

#: The engine's domain id this release is published for. The engine's domain
#: set is closed -- corporate and retail -- and this book IS the retail one,
#: so it is published as retail rather than as a third domain that would
#: require the engine's own registry to change.
ENGINE_DOMAIN = "retail"

#: What every row of this release belongs to.
#:
#: The retail installation has no tenant concept -- a principal there is a
#: user and a role -- so the adapter states one and the host maps every
#: authenticated principal onto it server-side. A request cannot name it.
#:
#: It is the ENGINE'S OWN DEFAULT deliberately. Several engine paths ask
#: whether a book is askable without naming a tenant -- the readiness
#: assessment, the startup announcement, the domain availability the Cockpit
#: home reads -- and they ask as `lake.DEFAULT_TENANT`. A release published
#: under any other name answers "not available" to all three while serving
#: questions perfectly well to a request that does name it, which is a
#: runtime that reports itself broken while working.
DEFAULT_TENANT = lake_mod.DEFAULT_TENANT

ORIGIN = "RETAIL_COCKPIT_DATA"

NOT_CLIENT_DATA = (
    "Synthetic Saudi retail demonstration data, published by the CreditProbe "
    "retail installation as the Cockpit Data domain and projected read-only "
    "for analysis. It describes no real customer, facility or institution.")



#: The four columns the engine's session filters on, in one place.
GOVERNANCE: tuple[str, ...] = ("tenant_id", "dataset_release_id",
                               "domain_id", "reporting_currency")

#: The engine's declared field types, as Arrow holds them. Declaring the
#: schema rather than inferring it per month is what stops a column whose
#: month happens to be all-null from being written as a different type in
#: one row group -- and what makes two builds of one projection fingerprint
#: the same.
ARROW_TYPES = {"float": "double", "integer": "int64", "string": "string"}


def arrow_schema(fields: list[dict[str, Any]]) -> Any:
    import pyarrow as pa

    kinds = {"double": pa.float64(), "int64": pa.int64(),
             "string": pa.string()}
    columns = [(str(f["name"]),
                kinds[ARROW_TYPES.get(str(f.get("type") or "string"),
                                      "string")])
               for f in fields]
    columns += [(name, pa.string()) for name in GOVERNANCE]
    return pa.schema(columns)


def to_table(frame: Any, schema: Any) -> Any:
    """One month of one relation, as the declared schema holds it."""
    import pyarrow as pa

    import pandas as pd

    arrays = []
    for field in schema:
        column = frame[field.name]
        if pa.types.is_string(field.type):
            column = column.astype("object").where(column.notna(), None)
        elif pa.types.is_integer(field.type):
            # A whole-number column arrives as a float wherever the book
            # leaves nulls in it, because a float is the only NumPy dtype
            # that carries one. The values are still whole; a value that is
            # NOT whole is a projection defect and is raised rather than
            # silently truncated.
            numeric = pd.to_numeric(column, errors="coerce")
            fractional = numeric.dropna() % 1
            if len(fractional) and float(fractional.abs().max()) > 0:
                raise ValueError(
                    f"{field.name} is declared a whole number and holds a "
                    f"fractional value.")
            column = numeric.round().astype("Int64")
        arrays.append(pa.array(column, type=field.type, from_pandas=True))
    return pa.Table.from_arrays(arrays, schema=schema)


class PublishRefused(RuntimeError):
    """A release was not written. Said, with the reason."""


def release_id_for(snapshot: Snapshot, *, revision: int = 1) -> str:
    """A release id that names the bytes it was projected from.

    The retail dataset version and the projection revision, because two
    projections of one book are two releases: a change in this adapter
    changes the numbers the engine sees even when the book has not moved.
    """
    return f"cockpitdata-{snapshot.dataset_version}-p{revision}"


def digest(paths: list[Path]) -> str:
    """The same rule the engine's own lake uses. Name and bytes, sorted."""
    out = hashlib.sha256()
    for path in sorted(paths, key=lambda p: p.name):
        out.update(path.name.encode("utf-8"))
        out.update(path.read_bytes())
    return out.hexdigest()


@dataclass(frozen=True)
class Published:
    release_id: str
    directory: Path
    manifest: dict[str, Any]

    @property
    def fingerprint(self) -> str:
        return str(self.manifest.get("release_fingerprint") or "")


def _built_with() -> dict[str, str]:
    import sys

    out = {"python": ".".join(str(n) for n in sys.version_info[:3])}
    for name in ("pandas", "numpy", "pyarrow"):
        try:  # noqa: SIM105 - an absent optional library is not an error
            out[name] = str(__import__(name).__version__)
        except Exception:  # noqa: BLE001
            pass
    return out


def publish(snapshot: Snapshot, *, lake_root: Path, release_id: str = "",
            tenant_id: str = DEFAULT_TENANT, revision: int = 1,
            overwrite: bool = False, gate: Any = None,
            on_month: Any = None) -> Published:
    """Project every published month and write the release. Immutable."""
    import pyarrow.parquet as pq

    release_id = release_id or release_id_for(snapshot, revision=revision)
    target = Path(lake_root) / release_id
    if (target / MANIFEST).exists() and not overwrite:
        raise PublishRefused(
            f"Release {release_id!r} is already published and a published "
            f"release is immutable. Publish a new revision rather than "
            f"rewriting this one.")

    findings = snapshot.verify()
    if findings:
        raise PublishRefused(
            "The Cockpit Data snapshot did not verify, so nothing was "
            "projected from it: " + "; ".join(findings[:6]))

    feature_maps = sm.feature_mappings(snapshot.columns)

    origination_maps = sm.origination_mappings(snapshot.columns)

    def mappings_for(relation: str) -> tuple[sm.Mapping, ...]:
        if relation == sm.BEHAVIOUR:
            return sm.MAPS[relation] + feature_maps
        if relation == sm.ORIGINATION:
            return sm.MAPS[relation] + origination_maps
        return sm.MAPS[relation]

    fields = {relation: relation_fields(relation, snapshot,
                                        mappings_for(relation))
              for relation in sorted(sm.MAPS)}
    schemas = {relation: arrow_schema(fields[relation])
               for relation in fields}

    target.mkdir(parents=True, exist_ok=True)
    writers: dict[str, Any] = {}
    row_counts: dict[str, int] = {relation: 0 for relation in sm.MAPS}
    entities: dict[str, set] = {"facilities": set(), "customers": set(),
                                "secured_facilities": set(),
                                "originations": set()}
    paths: dict[str, Path] = {relation: target / f"{relation}.parquet"
                              for relation in sm.MAPS}

    # STREAMED, one month at a time. The projected book is 1.35 million rows
    # across 230 columns on the behavioural relation alone; holding all of it
    # in memory to concatenate it once would be gigabytes for no reason, and
    # a month is the unit the book is published in anyway.
    try:
        for month in snapshot.months:
            projected = project_month(
                snapshot, month.reporting_month, tenant_id=tenant_id,
                release_id=release_id, domain_id=ENGINE_DOMAIN,
                feature_maps=feature_maps,
                origination_maps=origination_maps)
            # The origination relation is one row per FACILITY, so a
            # facility contributes its row the first month it is published
            # and never again. Taking it from the first month is taking it
            # from the month the values were recorded in.
            first_seen = ~projected.frames[sm.ORIGINATION]["account_id"].isin(
                entities["facilities"])
            projected.frames[sm.ORIGINATION] = (
                projected.frames[sm.ORIGINATION][first_seen])
            if gate is not None:
                gate(projected, month)
            for relation, frame in projected.frames.items():
                order = ([m.column for m in mappings_for(relation)]
                         + list(GOVERNANCE))
                table = to_table(frame[order], schemas[relation])
                writer = writers.get(relation)
                if writer is None:
                    writer = pq.ParquetWriter(paths[relation],
                                              schemas[relation])
                    writers[relation] = writer
                writer.write_table(table)
                row_counts[relation] += int(len(frame))
            entities["originations"].update(
                projected.frames[sm.ORIGINATION]["account_id"])
            entities["facilities"].update(
                projected.frames[sm.ACCOUNT]["account_id"])
            entities["customers"].update(
                projected.frames[sm.CUSTOMER]["customer_id"])
            entities["secured_facilities"].update(
                projected.frames[sm.COLLATERAL]["account_id"])
            if on_month is not None:
                on_month(month, projected)
    finally:
        for writer in writers.values():
            writer.close()

    written = [paths[relation] for relation in sorted(paths)]

    entity_counts = {name: len(values) for name, values in entities.items()}

    manifest: dict[str, Any] = {
        "release_id": release_id,
        "domain_id": ENGINE_DOMAIN,
        "domain_label": "Retail Credit",
        "origin": ORIGIN,
        "data_version": snapshot.dataset_version,
        "not_client_data": NOT_CLIENT_DATA,
        "tenants": [tenant_id],
        "geography": snapshot.country,
        "geography_name": "Saudi Arabia",
        "reporting_currency": sm.CURRENCY,
        "amount_scale": sm.AMOUNT_SCALE,
        "reporting_frequency": "monthly",
        "reporting_periods": list(snapshot.periods),
        "latest_period": snapshot.latest_period,
        "relations": [
            {"relation": relation,
             "grain": sm.RELATION_SPEC[relation]["grain"],
             "period_column": "reporting_month",
             "key_columns": list(sm.RELATION_SPEC[relation]["key_columns"]),
             "description": sm.RELATION_SPEC[relation]["description"],
             "fields": fields[relation]}
            for relation in sorted(sm.MAPS)],
        "row_counts": row_counts,
        "entity_counts": entity_counts,
        "notes": lineage_notes(snapshot, tenant_id=tenant_id),
        "built_with": _built_with(),
    }
    manifest["release_fingerprint"] = digest(written)
    (target / MANIFEST).write_text(
        json.dumps(manifest, indent=2, sort_keys=True, default=str),
        encoding="utf-8")
    return Published(release_id=release_id, directory=target,
                     manifest=manifest)


def lineage_notes(snapshot: Snapshot, *, tenant_id: str) -> dict[str, Any]:
    """Where this release came from, recorded on the release itself."""
    return {
        "projected_from": {
            "product": "CreditProbe retail installation",
            "domain": DOMAIN_DISPLAY,
            "domain_id": DOMAIN_ID,
            "dataset": DATASET,
            "dataset_version": snapshot.dataset_version,
            "generator_version": snapshot.generator_version,
            "manifest_hash": snapshot.manifest_hash,
            "schema_version": str(snapshot.contract.get("schema_version")
                                  or ""),
            "grain": str(snapshot.contract.get("grain") or ""),
            "primary_key": list(snapshot.contract.get("primary_key") or ()),
            "months": [{"reporting_month": m.reporting_month,
                        "snapshot_date": m.snapshot_date,
                        "rows": m.rows,
                        "content_hash": m.content_hash}
                       for m in snapshot.months],
            "scenario": snapshot.scenario,
        },
        "denomination": (
            f"The Cockpit Data domain is denominated in {snapshot.currency} "
            f"units. Every monetary column here is that column divided by "
            f"1,000,000 and is published as {sm.CURRENCY} "
            f"{sm.AMOUNT_SCALE}. The conversion is recorded on each field."),
        "read_only": (
            "This release is a read-only projection. The Cockpit Data domain "
            "is not modified, re-versioned or republished by it."),
        "tenant": tenant_id,
        "gaps": [{"field": field, "reason": reason} for field, reason in
                 sm.GAPS],
    }


__all__ = ["ARROW_TYPES", "DEFAULT_TENANT", "GOVERNANCE", "arrow_schema",
           "to_table", "ENGINE_DOMAIN", "MANIFEST", "NOT_CLIENT_DATA",
           "ORIGIN", "PublishRefused", "Published", "digest",
           "lineage_notes", "publish", "release_id_for"]
