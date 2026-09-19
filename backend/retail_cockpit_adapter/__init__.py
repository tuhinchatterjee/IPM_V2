"""
The boundary between the retail installation's published Cockpit Data domain
and the frozen AdvancedCockpit engine.

What this package is for
------------------------
The engine reads a V4 *release*: Parquet relations plus a manifest that
describes its own relations, fields, units, calendar and denomination. The
retail installation publishes something different -- one wide governed
dataset, `retail_facility_month`, partitioned by reporting month, in riyals,
at one row per facility per month-end.

This package is the adapter between the two, and it is the ONLY thing between
them. It reads the published snapshot read-only, projects it onto the shape
the engine already understands, and publishes that projection as a release
whose lineage names every field it came from. Nothing here is a second
analytical engine, a second catalogue or a second publication mechanism for
the retail product: the retail domain is untouched and remains the authority.

What it may not do
------------------
It may not invent a concept the snapshot does not carry. A required field
with no source column is recorded as a GAP and is simply absent from the
published release, which is what makes the engine say so rather than answer
from a column of nulls.
"""

from backend.retail_cockpit_adapter.source import Snapshot, open_snapshot

__all__ = ["Snapshot", "open_snapshot"]
