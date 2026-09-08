"""Whether generated code may run. §7, §8 and §9.

    OPUS WRITES.  CREDITPROBE VALIDATES.  USER APPROVES.  CREDITPROBE EXECUTES.

This module is the second step, and it is the one that makes the other three
mean anything. It is called on every path that could put a new calculation in
front of somebody — after generation, after a repair, after a person edits the
SQL by hand, and again before the preview runs — because §11 is explicit that
code arriving from a browser is not trusted for having been there.

The nine checks §8 asks for
----------------------------
Each is a function below, each returns sentences rather than a boolean, and all
of them run even after one has failed, because §9's repair packet is only
useful if it carries the whole picture.

  A domain       every dataset is inside Cockpit or Early Warning
  B permission   the asker may read every dataset named
  C field        every field named exists on the dataset it is read from
  D grain        the metric resolves to one coherent grain
  E join         a cross-domain metric uses a governed path, not an invented one
  F temporal     every period the definition needs exists on this book
  G mathematical zero denominators, nulls, units, scaling, aggregation order
  H SQL safety   one read-only statement over governed datasets, nothing else
  I Python safety no filesystem, process, network, import or environment

And the tenth, which §8 does not list and §7 requires
------------------------------------------------------
`reconcile` checks the model's SQL against the program CreditProbe will
actually run: same datasets, same fields, same aggregations, a denominator in
one exactly when there is one in the other. Without it, "the user approved the
code" would mean "the user approved a document that happened to be displayed
beside the calculation", and the two could differ without anything noticing.
That is the check that turns an approval into a control.

What a failure carries
----------------------
§9 asks for a precise failure packet — what failed, and what the model needs to
know to fix it. A `Failure` carries the rule, the sentence, whether it is
repairable at all, and `hints`: the fields that DO exist on the dataset, the
periods that DO exist on the book, the governed relationships that DO connect
two datasets. A repair round that is not given those is a round that guesses.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from backend.metrics import composite as composite_mod
from backend.metrics import lens_domains as domains
from backend.metrics import sqlguard
from backend.metrics.metric_code import MetricCode

logger = logging.getLogger(__name__)

GUARD_VERSION = "3.0.0"

RULE_DOMAIN = "domain"
RULE_PERMISSION = "permission"
RULE_FIELD = "field"
RULE_GRAIN = "grain"
RULE_JOIN = "join"
RULE_TEMPORAL = "temporal"
RULE_MATH = "mathematical"
RULE_SQL = "sql_safety"
RULE_PYTHON = "python_safety"
RULE_RECONCILE = "reconciliation"
RULE_SHAPE = "shape"

RULES = (RULE_SHAPE, RULE_DOMAIN, RULE_PERMISSION, RULE_FIELD, RULE_GRAIN,
         RULE_JOIN, RULE_TEMPORAL, RULE_MATH, RULE_SQL, RULE_PYTHON,
         RULE_RECONCILE)

RULE_LABELS = {
    RULE_SHAPE: "Definition shape",
    RULE_DOMAIN: "Data domain",
    RULE_PERMISSION: "Permission",
    RULE_FIELD: "Fields",
    RULE_GRAIN: "Grain",
    RULE_JOIN: "Joins",
    RULE_TEMPORAL: "Periods",
    RULE_MATH: "Arithmetic",
    RULE_SQL: "SQL safety",
    RULE_PYTHON: "Python safety",
    RULE_RECONCILE: "Code and calculation agree",
}

#: Rules a repair round may not fix by rewriting code. A model asking for the
#: Scorecard domain does not need a better query, it needs a different metric,
#: and letting it retry is how a boundary becomes a speed bump.
NOT_REPAIRABLE = (RULE_DOMAIN, RULE_PERMISSION)

#: Units whose ratio is a share rather than an amount. Used by §8G's scaling
#: check: currency over currency is a percentage, and a definition that says
#: `currency` has a scaling error in it, not a naming preference.
AMOUNT_UNITS = ("currency", "count")
SHARE_UNITS = ("percent", "ratio")

#: What `import` and friends mean in analytical Python. §8I is a list of things
#: that must not appear; this is the list.
PYTHON_FORBIDDEN_NODES = ("Import", "ImportFrom", "Exec", "Global", "Nonlocal",
                          "Lambda", "AsyncFunctionDef", "Await", "Yield")
PYTHON_FORBIDDEN_NAMES: frozenset[str] = frozenset({
    "open", "eval", "exec", "compile", "__import__", "input", "exit", "quit",
    "globals", "locals", "vars", "dir", "getattr", "setattr", "delattr",
    "os", "sys", "subprocess", "shutil", "socket", "requests", "urllib",
    "httpx", "pathlib", "pickle", "marshal", "shelve", "tempfile", "ctypes",
    "importlib", "builtins", "breakpoint", "memoryview", "environ", "getenv",
    "popen", "system", "spawn", "fork", "connect", "urlopen", "duckdb",
    "sqlalchemy", "psycopg", "engine", "session",
})


# ---------------------------------------------------------------------------
# What comes back
# ---------------------------------------------------------------------------


@dataclass
class Failure:
    """One reason this code will not run, with what a repair would need."""

    rule: str
    message: str
    repairable: bool = True
    hints: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"rule": self.rule, "label": RULE_LABELS.get(self.rule, self.rule),
                "message": self.message, "repairable": self.repairable,
                "hints": dict(self.hints)}


@dataclass
class Warning_:
    """Something worth saying that does not stop the metric."""

    rule: str
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {"rule": self.rule, "label": RULE_LABELS.get(self.rule, self.rule),
                "message": self.message}


@dataclass
class Verdict:
    """Whether this code may be shown to somebody, and why not."""

    ok: bool = False
    failures: list[Failure] = field(default_factory=list)
    warnings: list[Warning_] = field(default_factory=list)
    #: The statement CreditProbe will run, rendered from the program.
    compiled_sql: str = ""
    compiled_params: list[str] = field(default_factory=list)
    #: What the SQL and the program were found to agree on.
    reconciliation: dict[str, Any] = field(default_factory=dict)
    checked: list[str] = field(default_factory=list)

    @property
    def repairable(self) -> bool:
        return bool(self.failures) and all(f.repairable for f in self.failures)

    def packet(self) -> dict[str, Any]:
        """§9's failure packet: what failed, precisely, and what exists instead."""
        return {
            "failed": [f.to_dict() for f in self.failures],
            "repairable": self.repairable,
            "checks_run": list(self.checked),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "failures": [f.to_dict() for f in self.failures],
            "warnings": [w.to_dict() for w in self.warnings],
            "compiled_sql": self.compiled_sql,
            "compiled_params": list(self.compiled_params),
            "reconciliation": dict(self.reconciliation),
            "checks_run": list(self.checked),
            "repairable": self.repairable,
            "version": GUARD_VERSION,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _catalog() -> Any:
    from backend.data_access.catalog import get_catalog

    return get_catalog()


def _fields_of(dataset: str) -> set[str]:
    try:
        return set(_catalog().dataset(dataset).fields)
    except Exception:  # noqa: BLE001 - an unknown dataset is reported by rule A
        return set()


def _periods_of(dataset: str) -> list[str]:
    try:
        from backend.data_access import get_data_source

        return list(get_data_source().periods(dataset))
    except Exception:  # noqa: BLE001
        return []


def _resolve_metric(metric_id: str, *, readable: Any = None) -> Any:
    from backend.metrics import service

    return service.resolve(metric_id, readable=readable)


def _program_terms(code: MetricCode, *, resolver: Any = None) -> list[Any]:
    """Every measured quantity in the program, through governed-metric legs.

    A composite leg naming a governed metric contributes THAT metric's terms.
    Without this, a metric assembled entirely out of governed metrics reported
    no datasets and no fields, and `reconcile` then said the SQL and the
    calculation read different data — a false refusal on the very shape §14
    asks the builder to prefer.
    """
    if code.composite is not None:
        out: list[Any] = []
        for leg in code.composite.legs:
            if leg.formula is not None:
                out.extend(leg.formula.terms)
                continue
            if not leg.metric_id:
                continue
            try:
                metric = (resolver or _resolve_metric)(leg.metric_id)
            except Exception:  # noqa: BLE001 - reported by the field check
                continue
            out.extend(getattr(metric.formula, "terms", ()) or ())
        return out
    if code.formula is not None:
        return list(code.formula.terms)
    return []


def _program_datasets(code: MetricCode, *, resolver: Any = None) -> list[str]:
    return list(dict.fromkeys(t.dataset for t in _program_terms(code, resolver=resolver)
                              if t.dataset))


def _program_fields(code: MetricCode) -> set[str]:
    found: set[str] = set()
    for term in _program_terms(code):
        for name in (term.field, term.weight_field):
            if name:
                found.add(name)
        for condition in term.where or ():
            if condition.field:
                found.add(condition.field)
    return found


def _program_aggregates(code: MetricCode) -> set[str]:
    return {t.aggregate for t in _program_terms(code) if t.aggregate}


def _has_denominator(code: MetricCode) -> bool:
    if code.composite is not None:
        return code.composite.denominator is not None
    if code.formula is not None:
        return bool(code.formula.denominator
                    and code.formula.denominator.terms)
    return False


# ---------------------------------------------------------------------------
# The checks
# ---------------------------------------------------------------------------


def check_shape(code: MetricCode) -> list[Failure]:
    """Before anything else: is this a definition at all?"""
    from backend.metrics import formula as formula_mod

    found: list[Failure] = []
    if code.program is None:
        found.append(Failure(
            RULE_SHAPE,
            "This metric has no execution program — neither a formula nor a "
            "composite — so there is nothing for CreditProbe to run, whatever "
            "the SQL says."))
        return found
    if not code.name.strip():
        found.append(Failure(RULE_SHAPE, "A metric needs a name."))
    if code.language not in ("sql", "python"):
        found.append(Failure(
            RULE_SHAPE,
            f"'{code.language}' is not a language CreditProbe executes. It is "
            "safe read-only SQL, or governed Python analytical code."))
    if code.language == "sql" and not code.sql.strip():
        found.append(Failure(
            RULE_SHAPE,
            "No SQL was written. §6 requires the actual code, not a "
            "description of it — a person cannot approve what they cannot "
            "read."))

    catalog = _catalog()
    if code.composite is not None:
        for message in composite_mod.problems(code.composite, catalog=catalog):
            found.append(Failure(RULE_SHAPE, message))
    elif code.formula is not None:
        for message in formula_mod.problems(code.formula, catalog=catalog):
            found.append(Failure(RULE_SHAPE, message))
    return found


def check_domain(code: MetricCode) -> list[Failure]:
    """§8A. Only Cockpit and Early Warning, in the program AND in the SQL."""
    found: list[Failure] = []
    named = set(_program_datasets(code)) | set(code.datasets)
    if code.language == "sql" and code.sql.strip():
        named |= set(sqlguard.read(code.sql).tables)
    for message in domains.check_datasets(sorted(named)):
        found.append(Failure(
            RULE_DOMAIN, message, repairable=False,
            hints={"cockpit_datasets": domains.datasets_in(domains.COCKPIT),
                   "ews_datasets": domains.datasets_in(domains.EWS)}))
    return found


def check_permission(code: MetricCode, *,
                     readable: Iterable[str] | None = None) -> list[Failure]:
    """§8B. The asker may read every dataset this metric names.

    `readable` is the set of datasets this caller is allowed. `None` means the
    caller did not restrict, which is the product's current position — every
    analyst may read every published dataset — and the check still runs so
    that the day per-dataset permissions arrive, one argument changes.
    """
    if readable is None:
        return []
    allowed = set(readable)
    found: list[Failure] = []
    for dataset in sorted(set(_program_datasets(code)) | set(code.datasets)):
        if dataset and dataset not in allowed:
            found.append(Failure(
                RULE_PERMISSION,
                f"You are not authorised to read '{dataset}', so a metric "
                "cannot be built on it.", repairable=False,
                hints={"readable": sorted(allowed)}))
    return found


def check_fields(code: MetricCode) -> list[Failure]:
    """§8C. Every field named exists on the dataset it is read from.

    Checked twice, on purpose: on the program, against the catalogue, which is
    exact; and on the SQL's own column references, which is where a model's
    prose and its code diverge. The second is what produces §9's example
    failure — `ead_amount` does not exist, and here are the fields that do.
    """
    found: list[Failure] = []
    for term in _program_terms(code):
        available = _fields_of(term.dataset)
        if not available:
            continue
        wanted = [f for f in (term.field, term.weight_field) if f]
        wanted += [c.field for c in (term.where or ()) if c.field]
        for name in wanted:
            if name in available:
                continue
            found.append(Failure(
                RULE_FIELD,
                f"'{name}' is not a field of {term.dataset}.",
                hints={"dataset": term.dataset,
                       "related_fields": _nearest(name, available),
                       "available_fields": sorted(available)}))

    if code.language == "sql" and code.sql.strip():
        found.extend(_sql_field_failures(code))
    return found


def _sql_field_failures(code: MetricCode) -> list[Failure]:
    reading = sqlguard.read(code.sql)
    tables = [t for t in dict.fromkeys(reading.tables)
              if domains.permitted(t)]
    if not tables:
        return []
    known: set[str] = set()
    for table in tables:
        known |= _fields_of(table)
    introduced = {n.lower() for n in reading.aliases} | {
        n.lower() for n in reading.cte_names}

    found: list[Failure] = []
    seen: set[str] = set()
    for alias, column in reading.qualified_columns:
        if column.lower() in introduced or column in known or column in seen:
            continue
        if alias.lower() in introduced and column.lower() in introduced:
            continue
        seen.add(column)
        found.append(Failure(
            RULE_FIELD,
            f"The query reads '{alias}.{column}', and '{column}' is not a "
            f"field of {', '.join(tables)}.",
            hints={"dataset": tables[0],
                   "related_fields": _nearest(column, known),
                   "available_fields": sorted(known)}))
    return found


def _nearest(name: str, available: Iterable[str], limit: int = 6) -> list[str]:
    """The fields a mistyped one was probably meant to be.

    §9's packet shows these by name — "ead, exposure_amount,
    outstanding_amount" — because a model told only that a field is missing
    picks another missing one about as often as not.
    """
    import difflib

    pool = sorted(available)
    close = difflib.get_close_matches(name, pool, n=limit, cutoff=0.5)
    if len(close) >= limit:
        return close
    stem = name.lower().split("_")[0]
    for candidate in pool:
        if len(close) >= limit:
            break
        if candidate in close:
            continue
        if stem and (stem in candidate.lower() or candidate.lower() in name.lower()):
            close.append(candidate)
    return close


def check_grain(code: MetricCode) -> list[Failure]:
    """§8D. The metric resolves to one coherent grain."""
    found: list[Failure] = []
    catalog = _catalog()
    if code.composite is not None:
        for message in composite_mod._grain_problems(code.composite,
                                                     catalog=catalog):
            found.append(Failure(RULE_GRAIN, message))
        return found

    if code.formula is None:
        return found
    grains: dict[str, list[str]] = {}
    for dataset in code.formula.datasets:
        try:
            grains.setdefault(catalog.dataset(dataset).grain, []).append(dataset)
        except Exception:  # noqa: BLE001 - reported by rule A
            continue
    if len(grains) > 1:
        found.append(Failure(
            RULE_GRAIN,
            "The terms are measured at different grains — "
            + "; ".join(f"{', '.join(ds)} is '{g}'" for g, ds in grains.items())
            + ". Aggregating across them produces a figure that double-counts "
              "one side.",
            hints={"grains": {g: ds for g, ds in grains.items()}}))
    return found


def check_join(code: MetricCode) -> list[Failure]:
    """§8E. A cross-domain metric uses a governed path, not an invented one.

    Two shapes are allowed. A composite divides two aggregates, which needs no
    join and cannot fan out. A single-dataset formula whose terms read Cockpit
    fields and Early Warning fields on the SAME governed table needs no join
    either. Anything else — SQL that joins two tables — must name a governed
    relationship, and is refused with the relationships that DO exist when it
    does not.
    """
    found: list[Failure] = []
    if code.language != "sql" or not code.sql.strip():
        return found
    reading = sqlguard.read(code.sql)
    if not reading.has_join:
        return found

    # Only tables read in the SAME query scope are joined to each other. Two
    # base tables in two separate CTEs, combined afterwards, is a composite —
    # each side aggregates on its own and neither can multiply the other — and
    # refusing that would refuse exactly the shape §14 and the composite
    # builder are meant to produce.
    edges = _governed_edges()
    reported: set[tuple[str, str]] = set()
    for scope, tables in reading.tables_by_scope.items():
        distinct = list(dict.fromkeys(tables))
        if len(distinct) < 2:
            continue
        for left in distinct:
            for right in distinct:
                if left >= right or (left, right) in reported:
                    continue
                if (left, right) in edges or (right, left) in edges:
                    continue
                reported.add((left, right))
                where = (f" inside '{scope}'" if scope else "")
                found.append(Failure(
                    RULE_JOIN,
                    f"The query joins {left} to {right}{where}, and "
                    "CreditProbe has no governed relationship between them. A "
                    "join without one is a grain decision nobody has approved "
                    "— one borrower with four facilities counts four times, "
                    "and the figure looks fine. Aggregate each side "
                    "separately and combine the results, or ask a data "
                    "steward to declare the relationship.",
                    hints={"governed_relationships": sorted(
                        f"{a} ↔ {b}" for a, b in edges)}))
    return found


def _governed_edges() -> set[tuple[str, str]]:
    try:
        from backend.services import relationships as rel

        rows = rel.active_relationships()
    except Exception:  # noqa: BLE001 - no database means no declared edges
        return set()
    return {(str(r.get("from_dataset") or ""), str(r.get("to_dataset") or ""))
            for r in rows}


def check_temporal(code: MetricCode, *, period: str = "") -> list[Failure]:
    """§8F. Every period the definition needs exists on this book."""
    found: list[Failure] = []
    if code.composite is None:
        return found
    datasets = list(code.composite.datasets) or _program_datasets(code)
    available = _periods_of(datasets[0]) if datasets else []
    for leg in code.composite.legs:
        if not leg.period_offset:
            continue
        if not period:
            continue
        at = composite_mod.shift(period, back=leg.period_offset)
        if not at:
            found.append(Failure(
                RULE_TEMPORAL,
                f"CreditProbe cannot work out the period {leg.period_offset} "
                f"before '{period}' on this book's calendar, so "
                f"'{leg.label or leg.id}' has no period to read.",
                hints={"periods": available[-8:]}))
            continue
        if available and at not in available:
            found.append(Failure(
                RULE_TEMPORAL,
                f"'{leg.label or leg.id}' reads {at}, which this book does "
                f"not have. It runs from {available[0]} to {available[-1]}.",
                hints={"periods": available, "wanted": at}))
    return found


def check_math(code: MetricCode) -> tuple[list[Failure], list[Warning_]]:
    """§8G. Zero denominators, nulls, units, scaling, aggregation order."""
    found: list[Failure] = []
    noted: list[Warning_] = []

    scale = 1.0
    if code.composite is not None:
        scale = code.composite.scale
    elif code.formula is not None:
        scale = code.formula.scale

    has_denominator = _has_denominator(code)

    # Unit against shape. A ratio reported in currency is a scaling mistake
    # with a plausible-looking number on the end of it.
    if has_denominator and code.unit in AMOUNT_UNITS:
        same_side_units = _term_units(code)
        if len(same_side_units) <= 1:
            found.append(Failure(
                RULE_MATH,
                f"This metric divides one quantity by another and reports the "
                f"result as '{code.unit}'. Dividing "
                f"{next(iter(same_side_units), 'an amount')} by the same kind "
                "of thing gives a share, not an amount — the unit should be "
                "'percent' or 'ratio'.",
                hints={"suggested_units": list(SHARE_UNITS)}))
    if not has_denominator and code.unit in SHARE_UNITS:
        noted.append(Warning_(
            RULE_MATH,
            f"This metric has no denominator but reports '{code.unit}'. Check "
            "that the field it sums is already a percentage; if it is an "
            "amount, the metric is missing its denominator."))

    # Scaling. A percentage is a ratio times a hundred, and a definition that
    # says `percent` with a scale of one produces 0.094 where a screen shows
    # "0.09%".
    if code.unit == "percent" and has_denominator and scale not in (100.0, 1.0):
        noted.append(Warning_(
            RULE_MATH,
            f"This percentage is scaled by {scale:g}. A percentage is "
            "normally the ratio times 100."))
    if code.unit == "ratio" and scale == 100.0:
        found.append(Failure(
            RULE_MATH,
            "This metric is declared a ratio and multiplied by 100, which "
            "makes it a percentage. Say which it is — the two are read "
            "differently and a reader cannot tell from the number."))

    # A denominator that can be zero. Not a refusal: a zero denominator is a
    # real state of a book, and the engine already reports it rather than
    # rendering infinity. It IS worth saying, because a metric whose
    # denominator is a narrow filter will be blank more often than its author
    # expects.
    if has_denominator:
        narrow = _narrow_denominator(code)
        if narrow:
            noted.append(Warning_(
                RULE_MATH,
                f"The denominator is filtered ({narrow}), so it can be zero "
                "for a period with no matching rows. CreditProbe reports that "
                "as no value rather than as zero or infinity, and this metric "
                "will be blank in those periods."))

    # Aggregation order. An average of an average is not an average.
    aggregates = _program_aggregates(code)
    if "avg" in aggregates and has_denominator:
        noted.append(Warning_(
            RULE_MATH,
            "This metric divides an average by something. An average is "
            "already a ratio, so check that the result is the quantity you "
            "meant rather than a ratio of ratios."))

    # §8G, unit compatibility BETWEEN the two sides of a composite. This is
    # the check that catches the most plausible-looking wrong metric there is:
    # a rate divided by an amount. "Covenant breach exposure / corporate
    # exposure" is a share; resolve the numerator to the covenant breach RATE
    # by mistake and you get a percentage divided by billions, which renders
    # as 0.00% and is not obviously wrong to anybody.
    found.extend(_leg_unit_failures(code))

    # Currency compatibility. Mixing two currency fields from datasets that
    # declare different units is a sum that means nothing.
    currencies = _declared_currencies(code)
    if len(currencies) > 1:
        found.append(Failure(
            RULE_MATH,
            "This metric combines amounts declared in different currencies ("
            + ", ".join(sorted(currencies))
            + "). Converting them is a decision with an exchange rate in it, "
              "and the builder will not make it on your behalf."))
    return found, noted


def _leg_units(code: MetricCode) -> dict[str, str]:
    """The declared unit of each side of a composite, where it has one."""
    from backend.metrics import service

    out: dict[str, str] = {}
    if code.composite is None:
        return out
    for leg, side in ((code.composite.numerator, "numerator"),
                      (code.composite.denominator, "denominator")):
        if leg is None or not leg.metric_id:
            continue
        try:
            out[side] = service.resolve(leg.metric_id).unit
        except Exception:  # noqa: BLE001 - reported by the field check
            continue
    return out


def _leg_unit_failures(code: MetricCode) -> list[Failure]:
    if code.composite is None or code.composite.operation not in (
            "ratio", "growth"):
        return []
    units = _leg_units(code)
    top, bottom = units.get("numerator", ""), units.get("denominator", "")
    if not top or not bottom:
        return []
    if code.composite.operation == "growth" and top != bottom:
        return [Failure(
            RULE_MATH,
            f"A growth rate compares the same quantity at two points in time, "
            f"and these two sides are measured differently — the numerator in "
            f"{top}, the denominator in {bottom}. The result would not be a "
            "growth rate.")]
    share = {"percent", "ratio"}
    amount = {"currency", "count"}
    if (top in share and bottom in amount) or (top in amount and bottom in share):
        return [Failure(
            RULE_MATH,
            f"This divides a {top} by a {bottom}, which produces a figure "
            "with no meaning — a share over an amount. One of the two sides "
            "has resolved to a RATE where an AMOUNT was wanted. Name the "
            "amount explicitly on that side.",
            hints={"numerator_unit": top, "denominator_unit": bottom})]
    return []


def _term_units(code: MetricCode) -> set[str]:
    found: set[str] = set()
    for term in _program_terms(code):
        try:
            spec = _catalog().dataset(term.dataset).fields.get(term.field)
        except Exception:  # noqa: BLE001
            continue
        unit = getattr(spec, "unit", "") if spec else ""
        if unit:
            found.add(unit)
    return found


def _declared_currencies(code: MetricCode) -> set[str]:
    found: set[str] = set()
    for term in _program_terms(code):
        try:
            spec = _catalog().dataset(term.dataset).fields.get(term.field)
        except Exception:  # noqa: BLE001
            continue
        unit = (getattr(spec, "unit", "") if spec else "") or ""
        if unit.lower() in ("sar", "usd", "omr", "aed", "eur", "gbp"):
            found.add(unit.upper())
    return found


def _narrow_denominator(code: MetricCode) -> str:
    if code.composite is not None and code.composite.denominator is not None:
        leg = code.composite.denominator
        if leg.formula is None:
            return ""
        conditions = [c.describe() for t in leg.formula.terms
                      for c in (t.where or ())]
        return ", ".join(conditions)
    if code.formula is not None and code.formula.denominator is not None:
        conditions = [c.describe() for t in code.formula.denominator.terms
                      for c in (t.where or ())]
        return ", ".join(conditions)
    return ""


def check_python(code: MetricCode) -> list[Failure]:
    """§8I. Governed analytical Python only: no filesystem, process, network,
    import, secret or environment access.

    Parsed with `ast`, not scanned with a regex. `getattr(__builtins__,
    'ope' + 'n')` defeats a regex and does not defeat a walk over the tree,
    because the walk sees the `getattr` call and the `__builtins__` name.
    """
    if code.language != "python" or not code.python.strip():
        return []
    import ast

    try:
        tree = ast.parse(code.python, mode="exec")
    except SyntaxError as e:
        return [Failure(RULE_PYTHON,
                        f"The generated Python does not parse: {e.msg} at "
                        f"line {e.lineno}.")]

    found: list[Failure] = []
    for node in ast.walk(tree):
        kind = type(node).__name__
        if kind in PYTHON_FORBIDDEN_NODES:
            found.append(Failure(
                RULE_PYTHON,
                f"The generated Python uses `{kind}`, which the governed "
                "analytical environment does not allow. A metric computes "
                "over the frame it is given; it does not import, define "
                "coroutines, or reach outside itself."))
            continue
        if isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            found.append(Failure(
                RULE_PYTHON,
                f"The generated Python reaches for `{node.attr}`. Dunder "
                "attributes are how sandboxed code escapes a sandbox, and "
                "the analytical environment refuses all of them."))
        if isinstance(node, ast.Name) and node.id in PYTHON_FORBIDDEN_NAMES:
            found.append(Failure(
                RULE_PYTHON,
                f"The generated Python names `{node.id}`, which reaches the "
                "filesystem, the process, the network or the database. A "
                "metric reads the governed frame it is handed and nothing "
                "else."))
        if isinstance(node, ast.Attribute) and node.attr in PYTHON_FORBIDDEN_NAMES:
            found.append(Failure(
                RULE_PYTHON,
                f"The generated Python calls `.{node.attr}`, which reaches "
                "outside the governed analytical environment."))
    # De-duplicate: one sentence per distinct problem, not one per node.
    unique: dict[str, Failure] = {f.message: f for f in found}
    return list(unique.values())


def check_sql(code: MetricCode) -> list[Failure]:
    """§8H. One read-only statement over governed datasets, and nothing else."""
    if code.language != "sql" or not code.sql.strip():
        return []
    reading = sqlguard.read(code.sql)
    found = [Failure(RULE_SQL, message)
             for message in sqlguard.statement_problems(code.sql, reading)]
    for table in sorted({t for t in reading.tables}):
        if not domains.permitted(table):
            # Reported here as well as by rule A, because a table that exists
            # in neither domain AND in no catalogue is a hallucinated table and
            # the message a repair needs is a different one.
            found.append(Failure(
                RULE_SQL,
                f"The query reads '{table}', which is not a governed dataset "
                "a Lens may read.",
                hints={"cockpit_datasets": domains.datasets_in(domains.COCKPIT),
                       "ews_datasets": domains.datasets_in(domains.EWS)}))
    return found


# ---------------------------------------------------------------------------
# The tenth check
# ---------------------------------------------------------------------------


def reconcile(code: MetricCode) -> tuple[list[Failure], dict[str, Any]]:
    """§7. Does the code a person is approving describe what will run?

    Compares four things the two representations must agree on. Anything else
    — formatting, alias names, the order of a WHERE clause — is allowed to
    differ, because it does not change the number.
    """
    report: dict[str, Any] = {"checked": False}
    if code.language != "sql" or not code.sql.strip() or code.program is None:
        return [], report

    reading = sqlguard.read(code.sql)
    sql_tables = {t for t in reading.tables if domains.permitted(t)}
    program_tables = set(_program_datasets(code))
    sql_columns = ({c for _, c in reading.qualified_columns}
                   | set(reading.columns))
    program_fields = _program_fields(code)
    sql_aggregates = {a.lower() for a in reading.aggregates}
    program_aggregates = {a.lower() for a in _program_aggregates(code)}
    sql_divides = "/" in code.sql
    program_divides = _has_denominator(code)

    report = {
        "checked": True,
        "sql_datasets": sorted(sql_tables),
        "program_datasets": sorted(program_tables),
        "sql_aggregations": sorted(sql_aggregates),
        "program_aggregations": sorted(program_aggregates),
        "sql_divides": sql_divides,
        "program_divides": program_divides,
        "fields_in_both": sorted(program_fields & sql_columns),
    }

    found: list[Failure] = []
    missing_tables = program_tables - sql_tables
    extra_tables = sql_tables - program_tables
    if missing_tables or extra_tables:
        found.append(Failure(
            RULE_RECONCILE,
            "The SQL and the calculation read different datasets. The SQL "
            f"reads {', '.join(sorted(sql_tables)) or 'nothing'}; the "
            f"calculation reads {', '.join(sorted(program_tables)) or 'nothing'}. "
            "A person approving the SQL would be approving a different metric "
            "from the one that runs.",
            hints={"only_in_sql": sorted(extra_tables),
                   "only_in_calculation": sorted(missing_tables)}))

    missing_fields = sorted(f for f in program_fields if f not in sql_columns)
    if missing_fields:
        found.append(Failure(
            RULE_RECONCILE,
            "The calculation reads "
            + ", ".join(missing_fields)
            + ", and the SQL does not mention "
            + ("them" if len(missing_fields) > 1 else "it")
            + ". Write the SQL that matches the calculation, or change the "
              "calculation to match the SQL.",
            hints={"only_in_calculation": missing_fields}))

    if program_divides and not sql_divides:
        found.append(Failure(
            RULE_RECONCILE,
            "The calculation divides by a denominator and the SQL contains no "
            "division. One of them is not the metric that was asked for."))
    if sql_divides and not program_divides:
        found.append(Failure(
            RULE_RECONCILE,
            "The SQL divides and the calculation does not. The number on "
            "screen would be the numerator alone."))

    unmatched = program_aggregates - sql_aggregates
    # `count` maps onto `count(*)`, which the reader records as an aggregate,
    # and `weighted_avg` has no single SQL function — it is a sum over a
    # product over a sum, so its absence from the SQL's function list is not a
    # disagreement.
    unmatched -= {"weighted_avg", "count_distinct"}
    if unmatched:
        found.append(Failure(
            RULE_RECONCILE,
            "The calculation uses " + ", ".join(sorted(unmatched))
            + ", and the SQL does not. An aggregation that differs between "
              "the two is a different number.",
            hints={"only_in_calculation": sorted(unmatched)}))
    return found, report


# ---------------------------------------------------------------------------
# The whole thing
# ---------------------------------------------------------------------------


def compiled(code: MetricCode, *, period: str = "") -> tuple[str, list[str], str]:
    """The statement CreditProbe will actually run, rendered from the program.

    For a composite this is the numerator's statement — the legs are separate
    queries by construction — with the denominator's appended so a reader sees
    both. Not concatenated into one statement: they are two, they run
    separately, and pretending otherwise would misrepresent the execution.
    """
    from backend.metrics import builder
    from backend.metrics.catalogue import MetricDefinition

    def render(formula: Any, label: str) -> tuple[str, list[str], str]:
        metric = MetricDefinition(
            metric_id="draft", name=code.name or "draft", definition="",
            formula=formula, unit=code.unit, scope=code.scope_tuple())
        query = builder.compiled_sql(metric, period=period)
        return query["sql"], query["params"], query["unavailable"]

    if code.composite is not None:
        blocks: list[str] = []
        params: list[str] = []
        problems: list[str] = []
        for leg, side in ((code.composite.numerator, "numerator"),
                          (code.composite.denominator, "denominator")):
            if leg is None:
                continue
            formula = leg.formula
            if formula is None and leg.metric_id:
                # A leg naming a governed metric still RUNS something, and
                # "the statement CreditProbe will actually run" is exactly
                # that metric's own compiled query. Skipping it left the
                # compiled statement empty for the shape §14 asks the builder
                # to prefer — a metric assembled entirely out of governed
                # metrics showed a person no executable statement at all.
                try:
                    formula = _resolve_metric(leg.metric_id).formula
                except Exception as e:  # noqa: BLE001 - reported, not raised
                    problems.append(f"{side}: {e}")
                    continue
            if formula is None:
                continue
            sql, leg_params, why = render(formula, side)
            if why:
                problems.append(f"{side}: {why}")
                continue
            at = (f" — at the period {leg.period_offset} back"
                  if leg.period_offset else "")
            blocks.append(f"-- {side}: {leg.label or leg.id}{at}\n{sql}")
            params.extend(leg_params)
        return "\n\n".join(blocks), params, "; ".join(problems)

    if code.formula is None:
        return "", [], "There is no program to compile."
    return render(code.formula, "metric")


def check(code: MetricCode, *, period: str = "",
          readable: Iterable[str] | None = None) -> Verdict:
    """Every check §8 asks for, run together, on one artefact.

    Together rather than short-circuiting, because §9's repair packet is only
    worth a round trip if it carries everything that is wrong.
    """
    verdict = Verdict(checked=list(RULES))
    failures: list[Failure] = []
    warnings: list[Warning_] = []

    shape = check_shape(code)
    failures.extend(shape)
    failures.extend(check_domain(code))
    failures.extend(check_permission(code, readable=readable))
    failures.extend(check_sql(code))
    failures.extend(check_python(code))

    # The remaining checks read the program, and a program that failed the
    # shape check may not have one to read.
    if code.program is not None:
        failures.extend(check_fields(code))
        failures.extend(check_grain(code))
        failures.extend(check_join(code))
        failures.extend(check_temporal(code, period=period))
        math_failures, math_warnings = check_math(code)
        failures.extend(math_failures)
        warnings.extend(math_warnings)
        reconciled, report = reconcile(code)
        failures.extend(reconciled)
        verdict.reconciliation = report

        sql, params, why = compiled(code, period=period)
        verdict.compiled_sql, verdict.compiled_params = sql, params
        if why and not failures:
            failures.append(Failure(
                RULE_SHAPE,
                f"This definition will not compile to a query: {why}"))

    verdict.failures = failures
    verdict.warnings = warnings
    verdict.ok = not failures
    return verdict


def apply(code: MetricCode, verdict: Verdict) -> MetricCode:
    """Record a verdict on the artefact, and move it to the right stage."""
    from backend.metrics.metric_code import STAGE_REJECTED, STAGE_VALIDATED

    code.validation = verdict.to_dict()
    code.compiled_sql = verdict.compiled_sql
    code.compiled_params = list(verdict.compiled_params)
    code.stage = STAGE_VALIDATED if verdict.ok else STAGE_REJECTED
    return code


__all__ = [
    "GUARD_VERSION", "NOT_REPAIRABLE", "RULES", "RULE_DOMAIN", "RULE_FIELD",
    "RULE_GRAIN", "RULE_JOIN", "RULE_LABELS", "RULE_MATH", "RULE_PERMISSION",
    "RULE_PYTHON", "RULE_RECONCILE", "RULE_SHAPE", "RULE_SQL", "RULE_TEMPORAL",
    "Failure", "Verdict", "Warning_",
    "apply", "check", "check_domain", "check_fields", "check_grain",
    "check_join", "check_math", "check_permission", "check_python",
    "check_shape", "check_sql", "check_temporal", "compiled", "reconcile",
]
