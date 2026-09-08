"""Writing the code for a metric nobody has defined yet. §6 and §9.

What this module asks a model to produce
-----------------------------------------
Two things, together, in one call:

1. The **execution program** — a governed formula tree, or a composite over
   two of them. This is what CreditProbe compiles and runs.
2. The **SQL** that expresses the same calculation. This is what a person
   reads and approves.

Asking for both in one call is the point rather than a convenience. A model
that writes only SQL has produced something CreditProbe cannot safely execute;
a model that writes only a tree has produced something a person cannot review.
Producing both, and then having `codeguard.reconcile` prove they agree, is what
makes "the user approved the code" a control rather than a ceremony.

The model is not shown the book
--------------------------------
It gets `lens_context` — dataset names, grains, field dictionaries, coverage,
the governed metric catalogue — and the person's formula. It does not get a
single figure. A model designing a metric has no business seeing an exposure,
and one that saw one might design towards it.

Degrading honestly
------------------
With no provider configured, `generate` still returns a working, validated,
approvable artefact: the deterministic reader assembles the program from the
person's own formula using the same field matching the existing metric builder
uses, and the SQL is RENDERED from that program by the ordinary compiler. The
artefact says so — `author` is `CREDITPROBE`, not `MODEL` — and every screen
that shows it says so too, because in that mode the reconciliation check is
comparing the compiler with itself and proves nothing. A deployment with no key
gets a real feature and an accurate account of it, which is better than either
a blocked screen or a silent downgrade.

The repair loop
---------------
§9. A rejected artefact goes back with `Verdict.packet()` — the rules that
failed, the sentences, and the fields, periods and relationships that DO exist
— and the model is asked to fix exactly those. Repairs are charged to the
run's single budget (`REPAIRS` and `MODEL_CALLS`), so the loop is bounded by
the same ceiling as everything else rather than by a counter of its own.
Domain and permission failures are not repairable and end the loop: a model
asking for the Scorecard domain does not need another try.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from backend.metrics import codeguard
from backend.metrics import lens_domains as domains
from backend.metrics.composite import Composite, Leg
from backend.metrics.formula import (
    AGGREGATIONS,
    COMBINERS,
    COMPARISONS,
    KINDS,
    UNITS,
    Formula,
)
from backend.metrics.metric_code import (
    AUTHOR_CREDITPROBE,
    AUTHOR_MODEL,
    STAGE_GENERATED,
    MetricCode,
)

logger = logging.getLogger(__name__)

CODEGEN_VERSION = "3.0.0"

TOOL_NAME = "write_metric_code"

#: How many repair rounds one metric may have, before the budget's own ceiling.
#: Two, because the first repair fixes the ordinary mistake — a field name —
#: and a model still failing after the second is failing at something a
#: different prompt will not fix.
MAX_REPAIRS = 2

SYSTEM = """You are CreditProbe's metric engineer. A credit-risk professional has \
typed a formula, and you write the code that computes it.

YOU PRODUCE TWO THINGS, AND THEY MUST AGREE

1. `program` — the governed execution program CreditProbe will RUN. A formula \
tree, or a composite over two of them.
2. `sql` — read-only SQL expressing the SAME calculation, which the PERSON will \
read and approve before anything runs.

CreditProbe validates both and checks that they agree: same datasets, same \
fields, same aggregations, a denominator in one exactly when there is one in the \
other. If they disagree, the metric is rejected and you are told how. Write the \
SQL that matches the program you wrote, not a tidier version of it.

THE BOUNDARY — THIS IS NOT NEGOTIABLE

You may read ONLY the datasets in the context you were given. They are the \
Cockpit domain and the Early Warning domain. There is no third domain. If the \
person's formula needs data that is not in the context, say so in `unsupported` \
and build what the context DOES support — never name a dataset or a field that \
was not shown to you, and never guess at one that sounds right.

THE PERSON'S FORMULA IS THE SPECIFICATION

You are given their formula exactly as they typed it. Compute THAT. If it reads \
unconventionally — dividing the previous period by the current one, say — that \
has already been flagged to them separately and they have chosen. Do not \
"correct" it. `interpreted_formula` says what their formula means in terms of \
governed fields; it is not permission to change what it does.

CHOOSING THE SHAPE

Use `formula` when every term reads ONE dataset at ONE period. That is most \
metrics: a sum, a count, a ratio of two filtered sums over the same table.

Use `composite` when the calculation needs TWO PERIODS (a quarter-on-quarter \
change: numerator at offset 0, denominator at offset 1) or TWO DATASETS (a \
figure from the watchlist register over a figure from the facility position). \
Each side is its own single-dataset formula, or names a governed metric by id \
from the catalogue you were given — prefer naming an existing governed metric \
over rewriting it, because a metric already in the catalogue has already been \
verified.

Do NOT write SQL that joins two governed datasets unless the context lists a \
governed relationship between them. A join without one silently multiplies one \
side by the other's row count. Use a composite instead: two aggregates divided \
have no fan-out.

WHAT EACH FIELD IS FOR

`plain_english` is the numbered steps a risk officer checks the metric by — \
"identify the latest completed quarter", "sum exposure", "divide", "subtract \
one". Not a description of the SQL; the reasoning a person would follow with a \
pencil.

`grain` is what ONE ROW OF THE SOURCE is. `output_grain` is what one row of the \
RESULT is. They are usually different and the difference is where metrics go \
wrong.

`unit` is what the RESULT is measured in. A currency divided by a currency is a \
percent or a ratio, never a currency. A percentage sets `scale` to 100; a ratio \
leaves it at 1. Getting this wrong produces a number that is off by a hundred \
and looks plausible.

`why` is one sentence: why a senior risk user wants this on this Lens.

SQL RULES

One statement. SELECT or WITH only. No semicolons except at the very end. Use `?` \
for period values rather than writing a literal quarter into the string. Never \
call read_parquet, read_csv, or anything that reads a file, an extension, a \
system catalogue or the network. Never qualify a table with a schema."""


# ---------------------------------------------------------------------------
# The schema
# ---------------------------------------------------------------------------


def _condition_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "field": {"type": "string"},
            "op": {"type": "string", "enum": sorted(COMPARISONS)},
            "value": {
                "description": "A string, number, boolean, or list of them. "
                               "Omit for is_null and is_not_null.",
                "anyOf": [{"type": "string"}, {"type": "number"},
                          {"type": "boolean"},
                          {"type": "array", "items": {
                              "anyOf": [{"type": "string"}, {"type": "number"}]}}],
            },
        },
        "required": ["field", "op"],
    }


def _term_schema(datasets: list[str]) -> dict[str, Any]:
    dataset_field = ({"type": "string", "enum": datasets} if datasets
                     else {"type": "string"})
    return {
        "type": "object",
        "properties": {
            "id": {"type": "string",
                   "description": "A short identifier, unique within the "
                                  "metric, e.g. \"s2\" or \"total\"."},
            "label": {"type": "string",
                      "description": "What this quantity is called on the "
                                     "preview, e.g. \"Stage 2 exposure\"."},
            "dataset": dataset_field,
            "aggregate": {"type": "string", "enum": sorted(AGGREGATIONS)},
            "field": {"type": "string",
                      "description": "The governed field to aggregate. Empty "
                                     "only for `count`."},
            "weight_field": {"type": "string",
                             "description": "Only for weighted_avg."},
            "where": {"type": "array", "items": _condition_schema(),
                      "description": "Filters on THIS term only, ANDed."},
        },
        "required": ["id", "label", "dataset", "aggregate"],
    }


def _side_schema(datasets: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "terms": {"type": "array", "items": _term_schema(datasets)},
            "combine": {"type": "string", "enum": list(COMBINERS)},
        },
        "required": ["terms"],
    }


def _formula_schema(datasets: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "kind": {"type": "string", "enum": list(KINDS)},
            "numerator": _side_schema(datasets),
            "denominator": _side_schema(datasets),
            "scale": {"type": "number",
                      "description": "100 for a percentage, 1 otherwise."},
        },
        "required": ["kind", "numerator"],
    }


def _leg_schema(datasets: list[str], metric_ids: list[str]) -> dict[str, Any]:
    metric_field = ({"type": "string", "enum": [""] + metric_ids}
                    if metric_ids else {"type": "string"})
    return {
        "type": "object",
        "properties": {
            "id": {"type": "string"},
            "label": {"type": "string",
                      "description": "What this side is called on the "
                                     "preview, in the person's own words "
                                     "where they gave them."},
            "said": {"type": "string",
                     "description": "The part of the person's formula this "
                                    "side corresponds to, copied exactly."},
            "metric_id": metric_field,
            "formula": _formula_schema(datasets),
            "period_offset": {
                "type": "integer", "minimum": 0, "maximum": 16,
                "description": "0 for the period being shown, 1 for the one "
                               "before it, 4 for the same quarter last year."},
        },
        "required": ["id", "label", "period_offset"],
    }


def schema(datasets: list[str], metric_ids: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "name": {"type": "string",
                     "description": "What this metric is called on a "
                                    "dashboard. Short, specific, no verbs."},
            "interpreted_formula": {
                "type": "string",
                "description": "The person's formula in terms of governed "
                               "fields, e.g. \"SUM(exposure)[Q] / "
                               "SUM(exposure)[Q-1] - 1\"."},
            "plain_english": {
                "type": "array", "items": {"type": "string"},
                "description": "The numbered steps a risk officer would "
                               "follow to check this by hand."},
            "shape": {"type": "string", "enum": ["formula", "composite"]},
            "formula": _formula_schema(datasets),
            "composite": {
                "type": "object",
                "properties": {
                    "operation": {"type": "string",
                                  "enum": ["ratio", "growth", "difference",
                                           "sum", "product"]},
                    "numerator": _leg_schema(datasets, metric_ids),
                    "denominator": _leg_schema(datasets, metric_ids),
                    "scale": {"type": "number"},
                },
                "required": ["operation", "numerator"],
            },
            "sql": {"type": "string",
                    "description": "One read-only statement computing this "
                                   "metric. `?` for period values."},
            "grain": {"type": "string",
                      "description": "What one row of the SOURCE is."},
            "output_grain": {"type": "string",
                             "description": "What one row of the RESULT is."},
            "period_logic": {"type": "string",
                             "description": "Which period(s) this reads and "
                                            "how they are chosen."},
            "join_logic": {"type": "string",
                           "description": "How the two sides relate when the "
                                          "metric crosses datasets. Empty "
                                          "when it does not."},
            "aggregation": {"type": "string",
                            "description": "The aggregation(s), e.g. \"SUM, "
                                           "then divide\"."},
            "unit": {"type": "string", "enum": list(UNITS)},
            "decimals": {"type": "integer", "minimum": 0, "maximum": 6},
            "why": {"type": "string",
                    "description": "One sentence: why a senior risk user "
                                   "wants this on this Lens."},
            "unsupported": {
                "type": "array", "items": {"type": "string"},
                "description": "Anything the person's formula asked for that "
                               "the given context cannot supply."},
        },
        "required": ["name", "interpreted_formula", "plain_english", "shape",
                     "sql", "grain", "output_grain", "period_logic",
                     "aggregation", "unit", "why"],
    }


# ---------------------------------------------------------------------------
# The prompt
# ---------------------------------------------------------------------------


def _prompt(intake: Any, context: Any, *, period: str = "",
            lens: dict[str, Any] | None = None) -> str:
    lines = [
        "THE PERSON TYPED:",
        f"  {intake.said}",
        "",
        "THEIR FORMULA, EXACTLY AS TYPED — COMPUTE THIS:",
        f"  {intake.formula_text or intake.said}",
    ]
    if intake.numerator_text:
        lines.append(f"  numerator side: {intake.numerator_text}")
    if intake.denominator_text:
        lines.append(f"  denominator side: {intake.denominator_text}")
    if intake.operation:
        lines.append(f"  arithmetic: {intake.operation}")
    if intake.unconventional:
        lines.append("")
        lines.append(
            "NOTE: this formula was flagged to the person as unconventional "
            "and they chose to keep it. Compute what they wrote.")
    if intake.suggested_name:
        lines.append(f"  they may want it called: {intake.suggested_name}")
    if intake.unit_hint:
        lines.append(f"  the result looks like a: {intake.unit_hint}")
    lines.append("")
    if period:
        lines.append(f"THE PERIOD THE LENS IS SHOWING: {period}")
        lines.append("")
    if lens:
        lines.append(f"THE LENS THIS GOES ON: {lens.get('name', '')} — "
                     f"{lens.get('purpose') or lens.get('description', '')}")
        lines.append("")
    lines.append("THE ONLY DATA YOU MAY READ:")
    lines.append(json.dumps(context.to_dict(), default=str))
    lines.append("")
    lines.append("Write the metric.")
    return "\n".join(lines)


def _repair_prompt(code: MetricCode, verdict: Any) -> str:
    return "\n".join([
        "CreditProbe REJECTED the code you wrote. Fix exactly these problems "
        "and return the whole metric again.",
        "",
        "WHAT YOU WROTE:",
        json.dumps({"sql": code.sql,
                    "program": (code.composite.to_dict() if code.composite
                                else (code.formula.to_dict() if code.formula
                                      else None))}, default=str),
        "",
        "WHAT FAILED:",
        json.dumps(verdict.packet(), default=str),
        "",
        "The `hints` on each failure list what DOES exist — the fields on that "
        "dataset, the periods this book has, the governed relationships that "
        "are declared. Use them. Do not guess at a name that is not in them.",
        "",
        "Return the corrected metric.",
    ])


# ---------------------------------------------------------------------------
# Building the artefact
# ---------------------------------------------------------------------------


def _formula_from(payload: dict[str, Any] | None) -> Formula | None:
    if not payload or not (payload.get("numerator") or {}).get("terms"):
        return None
    below = payload.get("denominator") or {}
    return Formula.from_dict({
        "kind": payload.get("kind") or "sum",
        "numerator": payload.get("numerator") or {},
        "denominator": below if below.get("terms") else None,
        "scale": payload.get("scale") or 1.0,
    })


def _leg_from(payload: dict[str, Any] | None, fallback_id: str) -> Leg | None:
    if not payload:
        return None
    metric_id = str(payload.get("metric_id") or "").strip()
    formula = _formula_from(payload.get("formula"))
    if not metric_id and formula is None:
        return None
    return Leg(
        id=str(payload.get("id") or fallback_id),
        label=str(payload.get("label") or ""),
        said=str(payload.get("said") or ""),
        # A leg naming a governed metric must not ALSO carry a formula: the
        # composite refuses both, and the metric is the more governed of the
        # two, so the formula is what is dropped.
        metric_id=metric_id,
        formula=None if metric_id else formula,
        period_offset=int(payload.get("period_offset") or 0))


def _artefact(data: dict[str, Any], intake: Any, *, model: str,
              author: str = AUTHOR_MODEL) -> MetricCode:
    shape = str(data.get("shape") or "formula")
    formula = composite = None
    if shape == "composite":
        raw = data.get("composite") or {}
        numerator = _leg_from(raw.get("numerator"), "numerator")
        denominator = _leg_from(raw.get("denominator"), "denominator")
        composite = Composite(
            operation=str(raw.get("operation") or "ratio"),
            numerator=numerator, denominator=denominator,
            scale=float(raw.get("scale") or 1.0))
    else:
        formula = _formula_from(data.get("formula"))

    code = MetricCode(
        name=str(data.get("name") or intake.suggested_name or "").strip(),
        user_formula=intake.formula_text or intake.said,
        interpreted_formula=str(data.get("interpreted_formula") or "").strip(),
        plain_english=[str(s).strip()
                       for s in (data.get("plain_english") or []) if str(s).strip()],
        grain=str(data.get("grain") or "").strip(),
        output_grain=str(data.get("output_grain") or "").strip(),
        period_logic=str(data.get("period_logic") or "").strip(),
        join_logic=str(data.get("join_logic") or "").strip(),
        aggregation=str(data.get("aggregation") or "").strip(),
        unit=str(data.get("unit") or intake.unit_hint or "number").strip(),
        decimals=int(data.get("decimals") or 2),
        why=str(data.get("why") or "").strip(),
        sql=str(data.get("sql") or "").strip(),
        language="sql",
        formula=formula, composite=composite,
        stage=STAGE_GENERATED, author=author, model=model,
        notes=[str(s) for s in (data.get("unsupported") or []) if str(s)],
    )
    return code


def _describe(code: MetricCode, *, resolver: Any = None) -> MetricCode:
    """Fill in the parts of §6 that are FACTS about the program.

    Domains, datasets and fields are read off the program rather than taken
    from what the model said they were. A model that names the right tables in
    prose and the wrong ones in the tree would otherwise produce an artefact
    whose §6 panel is right and whose calculation is not.

    A composite leg naming a governed metric contributes that metric's own
    datasets and fields, resolved through `resolver`. Without it, a metric
    built entirely out of governed metrics would report that it reads no data
    at all — which is how a cross-domain metric loses the lineage that is the
    reason for showing it.
    """
    terms = list(codeguard._program_terms(code))
    if code.composite is not None and resolver is not None:
        for leg in code.composite.legs:
            if not leg.metric_id:
                continue
            try:
                terms.extend(resolver(leg.metric_id).formula.terms)
            except Exception:  # noqa: BLE001 - reported by the field check
                continue
    code.datasets = list(dict.fromkeys(
        t.dataset for t in terms if t.dataset))
    code.fields = sorted({f for t in terms
                          for f in ([t.field, t.weight_field]
                                    + [c.field for c in (t.where or ())])
                          if f})
    found: list[str] = []
    for term in terms:
        for name in ([t for t in (term.field, term.weight_field) if t]
                     + [c.field for c in (term.where or ()) if c.field] or [""]):
            domain = domains.domain_of_field(term.dataset, name)
            if domain and domain not in found:
                found.append(domain)
    code.domains = [d for d in domains.LENS_DOMAINS if d in found]
    code.filters = sorted({c.describe() for t in terms
                           for c in (t.where or ())})
    if not code.aggregation:
        code.aggregation = ", ".join(sorted({t.aggregate for t in terms}))
    if not code.interpreted_formula and code.program is not None:
        code.interpreted_formula = code.program.describe()
    return code


# ---------------------------------------------------------------------------
# The deterministic assembler
# ---------------------------------------------------------------------------


#: Words that say WHICH period a side reads rather than WHAT it measures.
#: Stripped before the catalogue is searched, and turned into a period offset
#: instead — "Current Quarter Exposure" and "Previous Quarter Exposure" are the
#: same measurement at two points in time, and searching the catalogue for the
#: whole phrase finds neither.
_PERIOD_WORDS = (
    ("previous quarter", 1), ("prior quarter", 1), ("last quarter", 1),
    ("preceding quarter", 1), ("previous period", 1), ("prior period", 1),
    ("last period", 1), ("previous year", 4), ("prior year", 4),
    ("last year", 4), ("year ago", 4), ("year-ago", 4), ("same quarter last year", 4),
    ("current quarter", 0), ("this quarter", 0), ("latest quarter", 0),
    ("current period", 0), ("this period", 0), ("latest period", 0),
    ("current", 0), ("latest", 0), ("previous", 1), ("prior", 1),
)


def _split_period(text: str) -> tuple[str, int]:
    """A side's words, with the period phrase removed, and the offset it meant.

    Returns the offset separately rather than leaving it in the text, because
    what the catalogue can match is the MEASUREMENT — "exposure" — and what
    decides the offset is the phrase around it.
    """
    lowered = (text or "").lower()
    offset = 0
    cleaned = text or ""
    for phrase, back in _PERIOD_WORDS:
        at = lowered.find(phrase)
        if at < 0:
            continue
        offset = back
        cleaned = (cleaned[:at] + cleaned[at + len(phrase):])
        break
    return " ".join(cleaned.split()).strip(" ,.;:"), offset


def resolve_side(text: str, *, user_id: int | None = None,
                 readable: Any = None) -> tuple[Leg | None, str]:
    """One side of a formula, as a leg, and how it was resolved.

    Tries the governed catalogue FIRST. That ordering is §14's point: a
    formula whose numerator is "total exposure" should reuse the governed
    metric that already means total exposure, not draft a fresh definition of
    it that a committee would then have to verify separately.
    """
    from backend.metrics import builder, service

    words, offset = _split_period(text)
    if not words:
        return None, ""

    found = service.find(words, limit=3, user_id=user_id, readable=readable)
    for hit in found.get("results", []):
        metric_id = hit.get("metric_id")
        if not metric_id:
            continue
        try:
            metric = service.resolve(metric_id, user_id=user_id,
                                     readable=readable)
        except Exception:  # noqa: BLE001 - try the next hit
            continue
        if not domains.metric_permitted(metric):
            continue
        return (Leg(id=_leg_id(text), label=metric.name, said=text,
                    metric_id=metric_id, period_offset=offset),
                f"matched the governed metric '{metric.name}'")

    proposal = builder.propose(words, user_id=user_id, readable=readable)
    if proposal.unresolved or not proposal.formula.numerator.terms:
        return None, ""
    return (Leg(id=_leg_id(text), label=proposal.name or words, said=text,
                formula=proposal.formula, period_offset=offset),
            f"drafted from {proposal.dataset}")


def _leg_id(text: str) -> str:
    import re as _re

    slug = _re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")
    return (slug[:40] or "side")


def assemble(intake: Any, *, period: str = "", user_id: int | None = None,
             readable: Any = None) -> MetricCode:
    """A working metric from the person's formula, with no model involved.

    Every side is resolved through the governed catalogue first, so what comes
    out is normally a composite over metrics somebody has already verified —
    which is both the safest definition available and the clearest thing to
    put in front of a person for approval.

    The SQL is RENDERED from the resulting program rather than written
    independently, and the artefact says so: see `AUTHOR_CREDITPROBE`.
    """
    notes: list[str] = [
        "This definition was assembled by CreditProbe's own reader rather "
        "than written by a model, because no AI provider is configured. The "
        "SQL below was rendered from the calculation, so it is a faithful "
        "reading of what will run — but it is not an independent statement "
        "of the metric, so the reconciliation check proves less here than it "
        "does when a model wrote the two separately."]

    unit = intake.unit_hint or "number"
    top, how_top = resolve_side(
        intake.numerator_text or intake.formula_text or intake.said,
        user_id=user_id, readable=readable)
    bottom, how_bottom = (
        resolve_side(intake.denominator_text, user_id=user_id,
                     readable=readable)
        if intake.denominator_text else (None, ""))

    if top is None:
        return MetricCode(
            name=intake.suggested_name or "New metric",
            user_formula=intake.formula_text or intake.said,
            author=AUTHOR_CREDITPROBE, unit=unit,
            notes=notes + [
                "CreditProbe could not match this formula to a governed "
                "metric or field on its own. Configure an AI provider, or "
                "build the metric from the metric library."])

    if how_top:
        notes.append(f"Numerator: {how_top}.")
    if how_bottom:
        notes.append(f"Denominator: {how_bottom}.")

    formula = composite = None
    scale = 100.0 if unit == "percent" else 1.0

    if intake.operation == "growth":
        # A growth rate over one measurement at two periods. The offsets come
        # from the words the person used on EACH SIDE and are kept exactly as
        # written — §5.
        #
        # This is the line the whole formula-preservation rule turns on.
        # Assigning offset 0 to the numerator and 1 to the denominator, as an
        # earlier draft of this function did, silently turned "Previous
        # Quarter Exposure / Current Quarter Exposure - 1" into the
        # conventional growth formula: the person's own inverted formula was
        # replaced by the one CreditProbe preferred, and the screen showed
        # their words above a different calculation. Nothing about that would
        # have been visible in the number.
        other = bottom or top
        offsets = (top.period_offset, other.period_offset)
        if offsets == (0, 0):
            # Neither side named a period — "quarter on quarter growth in
            # exposure" — so the conventional reading is the only one there
            # is, and it is applied because nothing was displaced by it.
            offsets = (0, 1)
        composite = Composite(
            operation="growth",
            numerator=Leg(id="numerator", label=top.label, said=top.said,
                          metric_id=top.metric_id, formula=top.formula,
                          period_offset=offsets[0]),
            denominator=Leg(id="denominator", label=other.label,
                            said=other.said or top.said,
                            metric_id=other.metric_id,
                            formula=other.formula,
                            period_offset=offsets[1]),
            scale=scale)
    elif bottom is not None and intake.operation in ("/", "ratio"):
        composite = Composite(
            operation="ratio",
            numerator=Leg(id="numerator", label=top.label, said=top.said,
                          metric_id=top.metric_id, formula=top.formula,
                          period_offset=top.period_offset),
            denominator=Leg(id="denominator", label=bottom.label,
                            said=bottom.said, metric_id=bottom.metric_id,
                            formula=bottom.formula,
                            period_offset=bottom.period_offset),
            scale=scale)
    elif top.formula is not None and not top.period_offset:
        formula = top.formula
        unit = unit if unit != "percent" else "number"
    else:
        composite = Composite(operation="sum", numerator=top, scale=1.0)
        unit = unit if unit != "percent" else "number"

    program = composite or formula
    code = MetricCode(
        name=intake.suggested_name or "New metric",
        user_formula=intake.formula_text or intake.said,
        interpreted_formula=program.describe() if program else "",
        plain_english=_steps(intake, formula, composite),
        unit=unit, decimals=2,
        period_logic=(
            "The period the Lens is showing, and the one before it."
            if composite is not None and composite.crosses_periods
            else "The period the Lens is showing."),
        why=intake.intent or "",
        author=AUTHOR_CREDITPROBE, formula=formula, composite=composite,
        notes=notes)
    return _finish(code, period=period, user_id=user_id, readable=readable)


def _finish(code: MetricCode, *, period: str = "", user_id: int | None = None,
            readable: Any = None) -> MetricCode:
    """Fill in the facts, the grain and the readable SQL.

    Shared by the assembler and by every path that hands an artefact on, so a
    model-written metric and a CreditProbe-written one carry the same §6
    panel filled in the same way.
    """
    from backend.metrics import service, sqlrender

    def resolver(metric_id: str) -> Any:
        return service.resolve(metric_id, user_id=user_id, readable=readable)

    code = _describe(code, resolver=resolver)
    if not code.grain:
        code.grain = _grain_of(code)
    if not code.output_grain:
        code.output_grain = "One row: the portfolio, for the period shown."
    if not code.sql:
        code.sql = sqlrender.render(code.program, resolver=resolver)
    sql, params, _why = codeguard.compiled(code, period=period)
    code.compiled_sql, code.compiled_params = sql, params
    return code


def _grain_of(code: MetricCode) -> str:
    from backend.data_access.catalog import get_catalog

    grains: list[str] = []
    for dataset in code.datasets:
        try:
            grain = get_catalog().dataset(dataset).grain
        except Exception:  # noqa: BLE001
            continue
        if grain not in grains:
            grains.append(grain)
    return " ".join(grains)


def _steps(intake: Any, formula: Formula | None,
           composite: Composite | None) -> list[str]:
    """The plain-English execution logic, when no model wrote it."""
    steps: list[str] = []
    if composite is not None and composite.crosses_periods:
        steps.append("Identify the period the Lens is showing.")
        top = composite.numerator
        bottom = composite.denominator
        steps.append(f"Compute {top.label or 'the numerator'} for that period: "
                     f"{top.formula.describe() if top.formula else top.metric_id}.")
        if bottom is not None:
            steps.append(
                f"Identify the period {bottom.period_offset} before it.")
            steps.append(
                f"Compute {bottom.label or 'the denominator'} for that "
                f"period, the same way.")
        if composite.operation == "growth":
            steps.append("Divide the first by the second.")
            steps.append("Subtract one.")
        else:
            steps.append("Divide the first by the second.")
        if composite.scale == 100:
            steps.append("Express the result as a percentage.")
        return steps
    program = composite or formula
    if program is None:
        return steps
    steps.append("Read the governed dataset for the period the Lens is showing.")
    steps.append(f"Compute {program.describe()}.")
    scale = getattr(program, "scale", 1.0)
    if scale == 100:
        steps.append("Express the result as a percentage.")
    return steps


# ---------------------------------------------------------------------------
# Public
# ---------------------------------------------------------------------------


def generate(intake: Any, *, context: Any = None, period: str = "",
             lens: dict[str, Any] | None = None, user_id: int | None = None,
             readable: Any = None, budget: Any = None, model: str = "",
             effort: str = "") -> tuple[MetricCode, Any]:
    """Write the code for this formula, validate it, repair it if it fails.

    Returns the artefact and the verdict on it. An artefact that failed
    validation is still returned — §10 shows the person what was rejected and
    why, rather than an empty screen with an error on it.
    """
    from backend.llm import get_provider
    from backend.metrics import lens_context

    context = context or lens_context.build(user_id=user_id, readable=readable,
                                            lens=lens, budget=budget)
    provider = get_provider()

    if not provider.configured:
        code = assemble(intake, period=period, user_id=user_id,
                        readable=readable)
        verdict = codeguard.check(code, period=period, readable=readable)
        return codeguard.apply(code, verdict), verdict

    dataset_names = context.dataset_names
    metric_ids = context.metric_ids()
    call_schema = schema(dataset_names, metric_ids)

    code = _call(provider, SYSTEM,
                 _prompt(intake, context, period=period, lens=lens),
                 call_schema, intake, budget=budget, model=model, effort=effort)
    if code is None:
        fallback = assemble(intake, period=period, user_id=user_id,
                            readable=readable)
        fallback.notes.append(
            "The live model could not be reached, so this definition was "
            "assembled by CreditProbe's own reader instead.")
        verdict = codeguard.check(fallback, period=period, readable=readable)
        return codeguard.apply(fallback, verdict), verdict

    verdict = codeguard.check(code, period=period, readable=readable)
    rounds = 0
    while (not verdict.ok and verdict.repairable and rounds < MAX_REPAIRS
           and _may_repair(budget)):
        rounds += 1
        logger.info("repairing generated metric code, round %s", rounds)
        repaired = _call(provider, SYSTEM, _repair_prompt(code, verdict),
                         call_schema, intake, budget=budget, model=model,
                         effort=effort)
        if repaired is None:
            break
        repaired.notes = list(code.notes) + [
            f"Repaired {rounds} time(s) after CreditProbe rejected the first "
            "attempt."]
        code = repaired
        verdict = codeguard.check(code, period=period, readable=readable)

    return codeguard.apply(code, verdict), verdict


def _may_repair(budget: Any) -> bool:
    if budget is None:
        return True
    from backend.agentic.budgets import REPAIRS

    return budget.try_spend(REPAIRS)


def _call(provider: Any, system: str, prompt: str, call_schema: dict[str, Any],
          intake: Any, *, budget: Any, model: str, effort: str
          ) -> MetricCode | None:
    from backend.llm import LLMError

    if budget is not None:
        from backend.agentic.budgets import MODEL_CALLS

        if not budget.try_spend(MODEL_CALLS):
            logger.info("no model-call budget left for metric code generation")
            return None
    try:
        answer = provider.structured(
            system=system, prompt=prompt, schema=call_schema,
            tool_name=TOOL_NAME,
            tool_description="Write the execution code for this metric. Call "
                             "this exactly once.",
            max_tokens=4000, purpose="metric_codegen", model=model,
            role="complex_planner", effort=effort)
    except LLMError as e:
        logger.warning("metric code generation failed: %s", e)
        return None
    except Exception as e:  # noqa: BLE001 - an outage must never block the builder
        logger.warning("metric code generation failed: %s", e)
        return None
    return _finish(_artefact(answer.data or {}, intake, model=answer.model))


def revalidate(code: MetricCode, *, period: str = "",
               readable: Any = None) -> tuple[MetricCode, Any]:
    """§11. Check an artefact that came back from a browser.

    The §6 facts are recomputed from the program rather than trusted, so a
    request body claiming a metric reads `portfolio_facility` while its tree
    reads something else is corrected before it is checked, and then refused
    on what it actually does.
    """
    code = _finish(code, period=period, readable=readable)
    verdict = codeguard.check(code, period=period, readable=readable)
    return codeguard.apply(code, verdict), verdict


__all__ = ["CODEGEN_VERSION", "MAX_REPAIRS", "SYSTEM", "TOOL_NAME",
           "assemble", "generate", "revalidate", "schema"]
