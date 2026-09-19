"""
The projection: the published retail book, read as the engine's four relations.

What a projection is here
-------------------------
A read-only restatement. Every column either comes straight from a published
column, or is a stated function of published columns. Nothing is imputed,
nothing is filled in, and a facility whose value is null stays null -- because
"this book does not record that for this product" and "the value is zero" are
different facts, and the second one is a number somebody might act on.

Grain, and why the customer relation is a projection rather than a table
-----------------------------------------------------------------------
The book is one row per facility per month-end, and every customer-level value
is repeated on each of that customer's facility rows. The engine's retail book
has a customer relation as well as an account one, and its join graph warns
that joining them and summing the customer side counts a customer once per
facility. So the customer relation here is built by DE-DUPLICATING on
customer_id -- one row per customer-month -- and the roll-ups on it are
computed from the facility rows rather than copied from them. A gate checks
that the roll-up equals the facilities summed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.retail_cockpit_adapter import semantic_map as sm
from backend.retail_cockpit_adapter.source import Snapshot


class ProjectionFailed(RuntimeError):
    """The projection could not be built. Named, never approximated."""


@dataclass(frozen=True)
class Projected:
    """One month, projected. Frames keyed by the engine's relation names."""

    reporting_month: str
    frames: dict[str, Any]
    source_rows: int


def _apply(mapping: sm.Mapping, frame: Any) -> Any:
    """One projected column, from the mapping that declares it."""
    if mapping.is_derived:
        return mapping.derive(frame)  # type: ignore[misc]
    import pandas as pd

    column = frame[mapping.source]
    unit = mapping.unit
    if unit == "rcy":
        return sm._money(column)
    if unit == sm.UNIT_SAR:
        # The riyal twin. Cast, never divided: this column is the source
        # book's own figure and it reconciles to it exactly.
        return column.astype("float64")
    if unit == "percent":
        return sm._to_percent(column)
    if pd.api.types.is_bool_dtype(column) or (
            column.dtype == object
            and set(column.dropna().unique()) <= {True, False}):
        # A flag is published as a count of one or zero, which is how the
        # engine's catalogue models every flag it has ("1 when ..."), and
        # what lets a question count them.
        return column.astype("boolean").astype("Int64")
    return column


def _unit_for(mapping: sm.Mapping, snapshot: Snapshot) -> str:
    """The engine's unit word for a projected column.

    An explicit override on the mapping wins, because the projection is
    allowed to change a unit (a ratio published as a percentage) and the
    override is where it says so. Otherwise the unit is the book's own,
    translated into the engine's vocabulary.
    """
    if mapping.unit:
        return mapping.unit
    if not mapping.source:
        return ""
    return sm.engine_unit(snapshot.column(mapping.source).get("unit"))


def relation_fields(relation: str, snapshot: Snapshot,
                    mappings: tuple[sm.Mapping, ...]) -> list[dict[str, Any]]:
    """The field block this relation publishes, in the engine's own shape."""
    out: list[dict[str, Any]] = []
    for mapping in mappings:
        # A mapping with no source column is one the projection COMPUTES --
        # a roll-up, a count, a derived band. It carries its own definition
        # and its own lineage, and there is no published column to read them
        # from.
        spec = (snapshot.column(mapping.source) if mapping.source else {})
        definition = mapping.definition or str(spec.get("definition") or "")
        # A money column and its riyal twin each carry the other's name in
        # their own definition. The analyst reads the catalogue, not this
        # module, so the grain rule has to travel in the release.
        if mapping.unit == "rcy":
            definition = (definition + sm.MILLIONS_NOTE.format(
                twin=sm.riyal_name(mapping.column))).strip()
        elif mapping.unit == sm.UNIT_SAR:
            definition = (definition + sm.RIYALS_NOTE.format(
                base=sm.millions_name(mapping.column))).strip()
        label = mapping.label or str(spec.get("business_name") or "")
        dtype = str(spec.get("data_type") or "")
        if dtype == "boolean":
            # Published as 0/1 (see `_apply`), so it is declared as the
            # count it becomes rather than as the boolean it was.
            dtype, unit_override = "integer", "count"
        else:
            unit_override = ""
        if mapping.unit in ("rcy", sm.UNIT_SAR, "percent"):
            dtype = "number"
        elif not dtype:
            # A column the projection computes has no published column to
            # read a type from, so the type comes from the unit it is
            # declared in: money and ratios are numbers, counts and day or
            # month tallies are integers, and everything else is text.
            unit = _unit_for(mapping, snapshot)
            dtype = {"rcy": "number", "percent": "number", "ratio": "number",
                     "probability_0_1": "number", "times": "number",
                     "percentage points": "number", "index": "number",
                     "count": "integer", "days": "integer",
                     "months": "integer"}.get(unit, "string")
        entry = {
            "name": mapping.column,
            "label": label,
            "type": {"number": "float", "integer": "integer",
                     "string": "string", "boolean": "integer",
                     "date": "string", "": "string"}.get(dtype, dtype),
            "unit": unit_override or _unit_for(mapping, snapshot),
            "description": definition,
            "group": mapping.group,
            # The engine reads `aggregation` as an author overruling the
            # unit's own verdict, and publishes it to the analyst on that
            # basis. Only a real override is written.
            **({"aggregation": mapping.aggregation}
               if mapping.aggregation else {}),
            # Not read by the engine's schema, and carried anyway: it is the
            # lineage this integration was told to record for every derived
            # field, and it travels with the release rather than beside it.
            "lineage": mapping.lineage,
        }
        out.append(entry)
    return out


def governance_columns(frame: Any, *, tenant_id: str, release_id: str,
                       domain_id: str, currency: str) -> dict[str, Any]:
    """The four columns the engine's session filters on.

    They are the isolation: `catalog._build_session` materialises each
    relation with a WHERE on tenant, release and domain, so a query cannot
    reach another tenant's or another book's rows by forgetting a predicate.
    """
    import pandas as pd

    n = len(frame)
    return {
        "tenant_id": pd.Series([tenant_id] * n, index=frame.index,
                               dtype="string"),
        "dataset_release_id": pd.Series([release_id] * n, index=frame.index,
                                        dtype="string"),
        "domain_id": pd.Series([domain_id] * n, index=frame.index,
                               dtype="string"),
        "reporting_currency": pd.Series([currency] * n, index=frame.index,
                                        dtype="string"),
    }


def project_month(snapshot: Snapshot, reporting_month: str, *,
                  tenant_id: str, release_id: str, domain_id: str,
                  feature_maps: tuple[sm.Mapping, ...] = (),
                  origination_maps: tuple[sm.Mapping, ...] = ()) -> Projected:
    """Project one published month onto the engine's four relations."""
    import pandas as pd

    maps = {relation: mappings for relation, mappings in sm.MAPS.items()}
    maps[sm.BEHAVIOUR] = maps[sm.BEHAVIOUR] + tuple(feature_maps)
    maps[sm.ORIGINATION] = maps[sm.ORIGINATION] + tuple(origination_maps)

    needed: list[str] = []
    for mappings in maps.values():
        for mapping in mappings:
            for name in mapping.reads:
                if name not in needed:
                    needed.append(name)
    # `product_code` is read by a derivation and is also published; either
    # way it must be in the frame before the derivations run.
    for extra in ("product_code", "customer_id", "facility_id"):
        if extra not in needed:
            needed.append(extra)

    book = snapshot.read_month(reporting_month, columns=needed)
    if book.empty:
        raise ProjectionFailed(
            f"{reporting_month} is published and holds no rows. Nothing was "
            f"substituted for it.")

    frames: dict[str, Any] = {}

    # -- the three facility-grain relations ------------------------------
    for relation in (sm.ACCOUNT, sm.BEHAVIOUR, sm.COLLATERAL,
                     sm.ORIGINATION):
        columns = {m.column: _apply(m, book) for m in maps[relation]}
        frame = pd.DataFrame(columns, index=book.index)
        frame = frame.assign(**governance_columns(
            frame, tenant_id=tenant_id, release_id=release_id,
            domain_id=domain_id, currency=snapshot.currency))
        if relation == sm.COLLATERAL:
            # Secured lending only. An unsecured facility has NO ROW here,
            # which is the contract the engine's join graph states: an inner
            # join against this relation is a secured-only population, and a
            # row of zeroes would hide that.
            secured = book["product_code"].isin(sm.SECURED_PRODUCTS)
            held = frame["collateral_value_sar_mn"].notna()
            frame = frame[secured & held]
        frames[relation] = frame.reset_index(drop=True)

    # -- the customer relation, de-duplicated ----------------------------
    frames[sm.CUSTOMER] = _customer_frame(
        book, snapshot=snapshot, tenant_id=tenant_id, release_id=release_id,
        domain_id=domain_id)

    return Projected(reporting_month=reporting_month, frames=frames,
                     source_rows=int(len(book)))


def _bands(scores: Any) -> Any:
    """The governed band of a score. The target's own function, not a copy.

    `scorecards.score_band_array` is what produced the published facility
    band, and it reproduces it exactly on every scored row of the latest
    month -- which is why it is the right instrument for the customer mean
    rather than a second set of edges written here.
    """
    import pandas as pd

    from backend.retail import scorecards

    values = pd.to_numeric(scores, errors="coerce").to_numpy(dtype="float64")
    return pd.Series(scorecards.score_band_array(values), index=scores.index,
                     dtype="object")


def _migration(change: Any) -> Any:
    """IMPROVED, STABLE or DETERIORATED, on the engine's own dead band.

    Null where either month has no scored facility: "the book did not score
    this customer" and "this customer did not move" are different facts, and
    the second one is a finding somebody might act on.
    """
    import numpy as np
    import pandas as pd

    values = pd.to_numeric(change, errors="coerce")
    band = sm.SCORE_MIGRATION_BAND
    out = pd.Series(
        np.where(values < -band, "DETERIORATED",
                 np.where(values > band, "IMPROVED", "STABLE")),
        index=change.index, dtype="object")
    return out.where(values.notna())


def _customer_frame(book: Any, *, snapshot: Snapshot, tenant_id: str,
                    release_id: str, domain_id: str) -> Any:
    """One row per customer-month, rolled up from their facilities."""
    import pandas as pd

    grouped = book.groupby("customer_id", sort=True)
    first = grouped.first()

    out = pd.DataFrame(index=first.index)
    out["customer_id"] = first.index
    out["reporting_month"] = first["reporting_month"]
    out["customer_segment"] = first["customer_segment"]
    out["employment_type"] = first["employment_status"]
    out["region"] = first["region_label"]
    out["salary_transfer_flag"] = first["salary_transfer_flag"].astype(
        "boolean").astype("Int64")
    out["tenure_months"] = first["customer_tenure_months"]
    out["facilities_held"] = grouped.size()
    # Each money roll-up is computed ONCE, in riyals, and divided once. The
    # millions column is the riyal column over a million and nothing else,
    # so the pair cannot disagree about the underlying sum.
    out["income_sar"] = first[
        "verified_total_monthly_income_sar"].astype("float64")
    out["income_sar_mn"] = sm._money(out["income_sar"])
    out["obligations_sar"] = first[
        "monthly_total_credit_obligations_sar"].astype("float64")
    out["obligations_sar_mn"] = sm._money(out["obligations_sar"])
    out["disposable_income_sar"] = first[
        "disposable_income_sar"].astype("float64")
    out["disposable_income_sar_mn"] = sm._money(out["disposable_income_sar"])
    out["debt_burden_ratio"] = first["debt_burden_ratio"]

    # -- the behavioural score at customer grain ------------------------
    #
    # The engine's own generator defines this aggregate as the UNWEIGHTED
    # mean of the customer's facility scores, and `attention_v2`'s
    # `segment_score_decline` family reads the migration it produces. The
    # family is not optional: `attention_v2.compute()` has no per-family
    # guard, so a missing column takes the whole Home feed down with a
    # binder error.
    #
    # `mean()` rather than `math.fsum`: this book publishes the score at full
    # float64 precision, not rounded to two places, so the half-cent tie that
    # the engine's generator records as "the mean that cost a release" cannot
    # arise here. Measured on the latest month: no customer mean sits within
    # 1e-9 of a rounding tie, and pandas and `fsum` agree to 1.1e-13 against
    # a dead band of two whole score points.
    scored = grouped["behavioural_score"]
    previous = grouped["behavioural_score_previous_month"]
    out["behaviour_score"] = scored.mean()
    out["behaviour_score_previous"] = previous.mean()
    out["behaviour_score_change"] = (out["behaviour_score"]
                                     - out["behaviour_score_previous"])
    out["score_band"] = _bands(out["behaviour_score"])
    out["score_band_previous"] = _bands(out["behaviour_score_previous"])
    out["score_migration"] = _migration(out["behaviour_score_change"])
    out["total_ead_sar"] = grouped["ead_base_sar"].sum().astype("float64")
    out["total_ead_sar_mn"] = sm._money(out["total_ead_sar"])
    out["total_ecl_sar"] = grouped["ecl_final_sar"].sum().astype("float64")
    out["total_ecl_sar_mn"] = sm._money(out["total_ecl_sar"])
    out["worst_stage"] = grouped["ifrs9_stage"].max()
    out["worst_dpd_days"] = grouped["dpd"].max()

    out = out.assign(**governance_columns(
        out, tenant_id=tenant_id, release_id=release_id, domain_id=domain_id,
        currency=snapshot.currency))
    return out.reset_index(drop=True)


__all__ = ["ProjectionFailed", "Projected", "governance_columns",
           "project_month", "relation_fields"]
