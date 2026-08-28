"""
Profiling the sources an analysis read, at export time.

§16 of the export contract asks the calculation pack to describe every source
dataset over the selected period BEFORE any join: how many rows, how many
customers, whether the primary key is unique, what the exposure totals and
rating distributions look like, and how each calculation-relevant field is
distributed.

None of that is recorded when an analysis runs. The runtime records the
*result* and the plan that produced it; it does not stop to describe the tables
on the way past, and asking it to would slow every question down to serve a
workbook most questions never generate.

So the profile is computed here, when the workbook is built, by measuring the
same governed data the run read, at the same period. Two things follow, and the
workbook states both rather than leaving a reader to assume:

1. This is a profile of the DATA, never a recomputation of the ANSWER. The
   analytical figures in the pack come only from the persisted run. Nothing in
   this module can change one, and nothing in this module is compared against
   one as though it were a second opinion.

2. The data may have moved since the run. Where the dataset's catalogue version
   no longer matches the version the run stamped, or a Parquet file has been
   written since the run finished, the profile says so in the sheet instead of
   quietly describing a different table than the one that was analysed.

Confidential identifier fields are counted, never listed: how many distinct
borrowers is a fact about the population; which borrowers is a data extract,
and §40 keeps it out of a profile.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: The credit concepts a source profile reports on wherever the dataset carries
#: them, whether or not this particular question used them. A reviewer checking
#: "was this the book I think it was?" looks for the exposure total and the
#: rating spread first, and a profile that only described the two columns this
#: question touched would not answer that.
CREDIT_CONCEPTS = (
    "ead", "exposure", "ecl", "ecl_coverage", "pd", "lgd", "dpd", "rating",
    "stage",
)

#: Governed dimensions worth a value distribution in any credit profile.
CREDIT_DIMENSIONS = ("sector", "region", "country", "segment", "product_type",
                     "risk_rating", "internal_grade", "rating_bucket",
                     "grade_band", "ifrs9_stage", "exposure_grade")

#: Identifier fields whose distinct COUNT is a profile statistic and whose
#: VALUES are a data extract. Counted here, never listed.
IDENTITY_HINTS = ("customer_id", "account_id", "facility_id", "obligor_id",
                  "collateral_id", "memo_id", "test_id")

#: Sensitivities that must never contribute a value-frequency table to a
#: profile, regardless of what the field is called.
NEVER_LISTED = {"confidential", "restricted"}

#: A ceiling on how many fields one dataset profiles. A 53-column facility
#: table profiled in full is a sheet nobody reads; the fields used by the
#: calculation plus the governed credit set is what a reviewer asks about.
MAX_NUMERIC_FIELDS = 24
MAX_CATEGORICAL_FIELDS = 12

#: How many values a categorical profile lists before saying it truncated.
TOP_VALUES = 15


@dataclass
class NumericField:
    """One numeric field's distribution over the profiled population."""

    field_name: str = ""
    business_name: str = ""
    unit: str = ""
    additive: bool = True
    count: int | None = None
    nulls: int | None = None
    null_rate: float | None = None
    total: float | None = None
    mean: float | None = None
    median: float | None = None
    stdev: float | None = None
    minimum: float | None = None
    p10: float | None = None
    p25: float | None = None
    p75: float | None = None
    p90: float | None = None
    p95: float | None = None
    p99: float | None = None
    maximum: float | None = None
    role: str = ""


@dataclass
class CategoricalField:
    """One categorical field's value distribution over the profiled population."""

    field_name: str = ""
    business_name: str = ""
    distinct: int | None = None
    nulls: int | None = None
    null_rate: float | None = None
    values: list[dict[str, Any]] = field(default_factory=list)
    truncated: bool = False
    unexpected: list[str] = field(default_factory=list)
    role: str = ""


@dataclass
class SourceProfile:
    """One governed dataset, described over the period the analysis read."""

    dataset: str = ""
    business_name: str = ""
    period: str = ""
    grain: str = ""
    primary_key: list[str] = field(default_factory=list)

    rows: int | None = None
    distinct_keys: int | None = None
    duplicate_keys: int | None = None
    null_keys: int | None = None
    identities: dict[str, int | None] = field(default_factory=dict)
    fields_used: list[str] = field(default_factory=list)

    numeric: list[NumericField] = field(default_factory=list)
    categorical: list[CategoricalField] = field(default_factory=list)

    #: When this profile was measured, and against which version.
    computed_at: str = ""
    version_at_run: str = ""
    version_now: str = ""
    #: True where the data on disk may have changed since the analysis ran.
    moved: bool = False
    notes: list[str] = field(default_factory=list)
    error: str = ""

    @property
    def usable(self) -> bool:
        return not self.error and self.rows is not None

    def credit_summary(self) -> list[tuple[str, Any, str]]:
        """The portfolio/credit block §16 asks for: label, value, unit.

        Assembled from the profile rather than measured separately, so the
        headline total and the field profile can never disagree. Ratios are
        reported as an average and never as a sum — a summed coverage
        percentage is not a bigger number, it is a wrong one.
        """
        out: list[tuple[str, Any, str]] = []
        for stat in self.numeric:
            if stat.additive and stat.total is not None:
                out.append((f"Total {stat.business_name or stat.field_name}",
                            stat.total, stat.unit))
            elif stat.mean is not None:
                out.append((f"Mean {stat.business_name or stat.field_name}",
                            stat.mean, stat.unit))
                if stat.median is not None:
                    out.append((f"Median {stat.business_name or stat.field_name}",
                                stat.median, stat.unit))
        for stat in self.categorical:
            if stat.distinct is not None:
                out.append((f"Distinct {stat.business_name or stat.field_name}",
                            stat.distinct, ""))
        for name, count in self.identities.items():
            out.append((f"Distinct {name}", count, ""))
        return out


def profiles_for(pack: Any, view: Any) -> list[SourceProfile]:
    """Profile every dataset the plan scanned, in plan order.

    `pack` is the gathered run; `view` is the decomposed plan. A dataset read at
    two periods is profiled twice, because that is two populations and a
    movement analysis's whole question is how they differ.
    """
    seen: set[tuple[str, str]] = set()
    out: list[SourceProfile] = []
    for scan in getattr(view, "scans", []):
        key = (scan.dataset, scan.period)
        if key in seen or not scan.dataset:
            continue
        seen.add(key)
        # The scan's own period, never the run's. A source read with no period
        # was read across all its published periods — an annual rating file an
        # as-of join then selects within — and profiling it at the analysis's
        # quarter would ask for a partition that does not exist.
        out.append(profile_one(
            scan.dataset,
            period=scan.period,
            fields_used=view.fields_for(scan.dataset),
            run_at=pack.created_at,
            version_at_run=_stamped_version(pack, scan.dataset),
        ))
    return out


def profile_one(dataset: str, *, period: str = "", fields_used: list[str] | None = None,
                run_at: str = "", version_at_run: str = "") -> SourceProfile:
    """Measure one governed dataset over one period.

    Never raises: a source that cannot be profiled — archived, moved, a
    permissions change — leaves a profile carrying the reason. The pack is
    still worth having, and a sheet that says why a profile is missing is worth
    more than a sheet that silently omits it.
    """
    out = SourceProfile(
        dataset=dataset,
        period=period,
        fields_used=list(fields_used or []),
        computed_at=datetime.now(UTC).isoformat(timespec="seconds"),
        version_at_run=version_at_run,
    )
    try:
        from backend.data_access import get_data_source
        from backend.data_access.catalog import get_catalog

        spec = get_catalog().dataset(dataset)
        source = get_data_source()
    except Exception as e:  # noqa: BLE001 - a profile is never worth an export
        out.error = f"This dataset could not be reached to profile it: {e}"
        logger.info("Source profile unavailable for %s: %s", dataset, e)
        return out

    out.business_name = spec.business_name
    out.grain = spec.grain
    out.primary_key = list(spec.primary_keys or [])
    out.version_now = spec.version
    if version_at_run and version_at_run not in {spec.version, "unknown"}:
        out.moved = True
        out.notes.append(
            f"The catalogue now declares version {spec.version}; this analysis "
            f"read version {version_at_run}. The figures below describe the data "
            "as it stands now, not necessarily as it stood when the analysis ran."
        )

    chosen = _fields(spec, out.fields_used)
    try:
        measured = source.profile(
            dataset,
            period=period or None,
            numeric=chosen["numeric"],
            categorical=chosen["categorical"],
            distinct=chosen["identity"],
            top=TOP_VALUES,
        )
    except Exception as e:  # noqa: BLE001
        out.error = f"This dataset could not be profiled: {e}"
        logger.info("Source profile failed for %s: %s", dataset, e)
        return out

    out.rows = measured.get("rows")
    out.distinct_keys = measured.get("key_distinct")
    out.duplicate_keys = measured.get("duplicate_keys")
    out.null_keys = measured.get("key_nulls")
    out.identities = {
        name: value for name, value in (measured.get("distinct") or {}).items()
    }

    rows = out.rows or 0
    for stat in measured.get("numeric") or []:
        name = str(stat.get("field"))
        spec_field = spec.fields.get(name)
        out.numeric.append(NumericField(
            field_name=name,
            business_name=getattr(spec_field, "business_name", "") or name,
            unit=getattr(spec_field, "unit", "") or "",
            additive=_additive(dataset, name, spec_field),
            count=stat.get("count"),
            nulls=stat.get("nulls"),
            null_rate=_rate(stat.get("nulls"), rows),
            total=stat.get("sum") if _additive(dataset, name, spec_field) else None,
            mean=stat.get("mean"),
            median=stat.get("median"),
            stdev=stat.get("stdev"),
            minimum=stat.get("min"),
            p10=stat.get("p10"), p25=stat.get("p25"), p75=stat.get("p75"),
            p90=stat.get("p90"), p95=stat.get("p95"), p99=stat.get("p99"),
            maximum=stat.get("max"),
            role=_role(name, out.fields_used),
        ))

    for stat in measured.get("categorical") or []:
        name = str(stat.get("field"))
        spec_field = spec.fields.get(name)
        allowed = list(getattr(spec_field, "allowed_values", None) or [])
        values = list(stat.get("top") or [])
        out.categorical.append(CategoricalField(
            field_name=name,
            business_name=getattr(spec_field, "business_name", "") or name,
            distinct=stat.get("distinct"),
            nulls=stat.get("nulls"),
            null_rate=_rate(stat.get("nulls"), rows),
            values=values,
            truncated=bool(stat.get("truncated")),
            unexpected=_unexpected(stat.get("values") or values, allowed),
            role=_role(name, out.fields_used),
        ))

    skipped = measured.get("skipped_fields") or []
    if skipped:
        out.notes.append(
            "These fields were named by the plan but are not in the catalogue "
            "for this dataset today, so they are not profiled: "
            + ", ".join(skipped) + "."
        )
    if _written_since(dataset, period, run_at):
        out.moved = True
        out.notes.append(
            "A file in this dataset has been written since the analysis ran. "
            "This profile describes the data as it stands now."
        )
    return out


# ------------------------------------------------------------ field choosing


def _fields(spec: Any, used: list[str]) -> dict[str, list[str]]:
    """Which fields get a profile, and of which kind.

    The fields the calculation touched, first and always — those are what a
    reviewer is checking. Then the governed credit set the dataset happens to
    carry, so the profile answers "is this the book I think it is?" as well as
    "did this step do what it said".
    """
    known = spec.fields
    numeric: list[str] = []
    categorical: list[str] = []
    identity: list[str] = []

    def classify(name: str) -> None:
        found = known.get(name)
        if found is None:
            return
        if _is_identity(name, found):
            if name not in identity:
                identity.append(name)
            return
        kind = str(getattr(found, "data_type", "")).lower()
        if kind in {"number", "integer"} and not _is_coded(name, found):
            if name not in numeric and len(numeric) < MAX_NUMERIC_FIELDS:
                numeric.append(name)
        elif kind in {"string", "boolean", "integer"} and _listable(found):
            if name not in categorical and len(categorical) < MAX_CATEGORICAL_FIELDS:
                categorical.append(name)

    for name in used:
        classify(name)
    for name in _credit_fields(spec):
        classify(name)
    for name in CREDIT_DIMENSIONS:
        if name in known:
            classify(name)
    for name in IDENTITY_HINTS:
        if name in known and name not in identity:
            identity.append(name)

    # The period column describes the partition, not the population.
    period_field = str(getattr(spec, "period_field", "") or "")
    for bucket in (numeric, categorical):
        if period_field in bucket:
            bucket.remove(period_field)
    return {"numeric": numeric, "categorical": categorical, "identity": identity}


def _credit_fields(spec: Any) -> list[str]:
    """The governed credit concepts this dataset carries.

    Read from the concept map rather than from column names, so a dataset that
    calls its exposure column something else is still profiled on exposure, and
    a column called `ead` in a table that is not a credit book is not.
    """
    try:
        from backend.orchestration.concepts import CONCEPTS
    except Exception:  # noqa: BLE001 - profiling must survive without the map
        return []
    out: list[str] = []
    for concept in CONCEPTS:
        if concept.id not in CREDIT_CONCEPTS:
            continue
        for candidate in concept.candidates:
            if candidate.dataset == spec.name and candidate.field in spec.fields:
                if candidate.field not in out:
                    out.append(candidate.field)
    return out


def _is_identity(name: str, found: Any) -> bool:
    """An identifier: counted, never listed."""
    if str(getattr(found, "sensitivity", "")).lower() in NEVER_LISTED:
        return True
    return name in IDENTITY_HINTS


def _is_coded(name: str, found: Any) -> bool:
    """A numeric column that is really a code, and has no meaningful mean.

    An IFRS 9 stage averages to 1.3, which is not a stage. Columns with declared
    allowed values are categories that happen to be stored as numbers, and are
    profiled by their distribution instead.
    """
    if getattr(found, "allowed_values", None):
        return True
    return name in {"ifrs9_stage", "internal_grade"}


def _listable(found: Any) -> bool:
    return str(getattr(found, "sensitivity", "")).lower() not in NEVER_LISTED


def _additive(dataset: str, name: str, found: Any) -> bool:
    """Whether summing this field means anything.

    Percentages, ratios and scores are averaged. Summing them produces a number
    with no unit and no meaning, and §16 says not to print one.
    """
    unit = str(getattr(found, "unit", "") or "").strip()
    if unit in {"%", "x", "score", "grade", "stage"}:
        return False
    if name.endswith(("_pct", "_rate", "_ratio")):
        return False
    kind = str(getattr(found, "data_type", "")).lower()
    if kind not in {"number", "integer"}:
        return False
    return _semantically_additive(name)


def _semantically_additive(name: str) -> bool:
    """The semantic contract's opinion, where it has one.

    A field the ontology declares a ratio is not additive even if its unit is
    blank, and the ontology is the governed place that decision lives.
    """
    try:
        from backend.orchestration.concepts import CONCEPTS
        from backend.semantics.ontology import contract
    except Exception:  # noqa: BLE001
        return True
    for concept in CONCEPTS:
        if not any(c.field == name for c in concept.candidates):
            continue
        found = contract(concept.id)
        if found is not None:
            return not (found.is_ratio or found.is_ordinal or found.is_categorical)
        return not (concept.is_ordinal or concept.is_categorical)
    return True


def _role(name: str, used: list[str]) -> str:
    return "used by this calculation" if name in used else "context"


def _rate(nulls: Any, rows: int) -> float | None:
    if nulls is None or not rows:
        return None
    return round(float(nulls) / float(rows) * 100.0, 4)


def _unexpected(values: list[dict[str, Any]], allowed: list[str]) -> list[str]:
    """Values outside the catalogue's declared set, where one is declared."""
    if not allowed:
        return []
    permitted = {str(a) for a in allowed}
    return [str(v.get("value")) for v in values
            if v.get("value") is not None and str(v.get("value")) not in permitted]


def _stamped_version(pack: Any, dataset: str) -> str:
    for entry in (pack.fingerprint or {}).get("datasets") or []:
        if isinstance(entry, dict) and str(entry.get("dataset")) == dataset:
            return str(entry.get("version") or "")
    return ""


def _written_since(dataset: str, period: str, run_at: str) -> bool:
    """Whether a Parquet file for this dataset changed after the run finished.

    A cheap, honest staleness check. It can only be wrong in the safe
    direction: a filesystem that does not report modification times, or a clock
    that cannot be compared, returns False and the pack simply does not claim
    the data moved.
    """
    if not run_at:
        return False
    try:
        from backend.config import settings

        when = datetime.fromisoformat(run_at)
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        directory = Path(settings.analytics_dir) / dataset
        if period:
            directory = directory / f"period={period}"
        if not directory.exists():
            return False
        for path in directory.rglob("*.parquet"):
            stamp = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
            if stamp > when:
                return True
    except Exception as e:  # noqa: BLE001 - a staleness check never fails an export
        logger.debug("Staleness check skipped for %s: %s", dataset, e)
    return False
