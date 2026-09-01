"""A metadata question, answered as prose and a table. §13.

Never a chart
-------------
Every answer this module produces sets `chart` empty and says so. A list of
datasets is not a distribution, a domain is not a time series, and a bar chart
of "fields per dataset" is a picture of nothing anybody asked about. §13 is
explicit that a data-understanding question returns plain text and a table,
and putting that decision here — beside the answer, rather than in a chart
selector reading the result afterwards — is what makes it hold for every
metadata question rather than for the ones somebody remembered.

Prose first
-----------
The sentence answers the question. The table is the evidence. A reader who
asked "how many datasets are in IFRS 9?" gets "Six." in the first line and the
six rows underneath — not a table they have to count.
"""

from __future__ import annotations

from typing import Any

from backend.metadata import service as svc
from backend.metadata.questions import Kind, Request

ANSWERS_VERSION = "1.0.0"

#: The §13 shape: domain, dataset, relevant fields, grain, periods, purpose.
DATASET_COLUMNS: list[dict[str, Any]] = [
    {"name": "domain", "label": "Domain", "semantic": "text"},
    {"name": "dataset", "label": "Dataset", "semantic": "text"},
    {"name": "business_name", "label": "Business name", "semantic": "text"},
    {"name": "relevant_fields", "label": "Relevant fields", "semantic": "text"},
    {"name": "grain", "label": "Grain", "semantic": "text"},
    {"name": "periods", "label": "Periods", "semantic": "text"},
    {"name": "rows", "label": "Rows", "semantic": "count", "decimals": 0,
     "align": "right"},
    {"name": "purpose", "label": "Purpose", "semantic": "text"},
]

DOMAIN_COLUMNS: list[dict[str, Any]] = [
    {"name": "domain", "label": "Domain", "semantic": "text"},
    {"name": "datasets", "label": "Datasets", "semantic": "count",
     "decimals": 0, "align": "right"},
    {"name": "fields", "label": "Fields", "semantic": "count", "decimals": 0,
     "align": "right"},
    {"name": "rows", "label": "Rows", "semantic": "count", "decimals": 0,
     "align": "right"},
    {"name": "periods", "label": "Periods", "semantic": "text"},
    {"name": "owner", "label": "Owner", "semantic": "text"},
    {"name": "description", "label": "What it holds", "semantic": "text"},
]

FIELD_COLUMNS: list[dict[str, Any]] = [
    {"name": "field", "label": "Field", "semantic": "text"},
    {"name": "label", "label": "Business name", "semantic": "text"},
    {"name": "kind", "label": "Used as", "semantic": "text"},
    {"name": "type", "label": "Type", "semantic": "text"},
    {"name": "unit", "label": "Unit", "semantic": "text"},
    {"name": "description", "label": "Definition", "semantic": "text"},
]

RELATIONSHIP_COLUMNS: list[dict[str, Any]] = [
    {"name": "from_dataset", "label": "From", "semantic": "text"},
    {"name": "from_field", "label": "Key", "semantic": "text"},
    {"name": "to_dataset", "label": "To", "semantic": "text"},
    {"name": "to_field", "label": "Key", "semantic": "text"},
    {"name": "kind", "label": "Relationship", "semantic": "text"},
]


class Answer(dict):
    """A metadata answer. A dict so every existing consumer already reads it."""


def _answer(text: str, rows: list[dict[str, Any]],
            columns: list[dict[str, Any]], *, request: Request,
            detail: dict[str, Any] | None = None,
            follow_ups: list[str] | None = None) -> Answer:
    return Answer({
        "answer": text,
        "rows": rows,
        "columns": columns,
        "chart": {},
        # Read by the presentation layer. §11 and §13: a metadata answer is a
        # table, and saying so here means no chart selector has to infer it.
        "visualization": {"kind": "table", "reason":
                          "A question about the catalogue is answered as a "
                          "table. There is nothing here to plot."},
        "execution": "metadata",
        "execution_label": "Governed metadata",
        "metadata_request": request.to_dict(),
        "detail": detail or {},
        "follow_ups": follow_ups or [],
        "values": {},
        "warnings": [],
    })


def _periods_text(periods: tuple[str, ...]) -> str:
    if not periods:
        return "not published"
    if len(periods) == 1:
        return periods[0]
    return f"{periods[0]} to {periods[-1]} ({len(periods)})"


def _dataset_row(found: svc.Dataset, *, relevant: tuple[str, ...] = ()
                 ) -> dict[str, Any]:
    return {
        "domain": found.domain,
        "dataset": found.name,
        "business_name": found.business_name,
        "relevant_fields": ", ".join(relevant) if relevant
                           else f"{found.field_count} fields",
        "grain": found.grain,
        "periods": _periods_text(found.periods),
        "rows": found.row_count,
        "purpose": found.purpose,
    }


def _domain_row(heading: svc.Domain) -> dict[str, Any]:
    return {
        "domain": heading.name,
        "datasets": heading.dataset_count,
        "fields": heading.field_count,
        "rows": heading.row_count,
        "periods": _periods_text(heading.periods),
        "owner": heading.owner,
        "description": heading.description,
    }


def _count(n: int, singular: str, plural: str = "") -> str:
    return f"{n:,} {singular if n == 1 else (plural or singular + 's')}"


def _fields_matching(found: svc.Dataset, subject: str) -> tuple[str, ...]:
    """The fields of one dataset that bear on a subject, for the table."""
    terms = svc._terms(subject)  # noqa: SLF001 - one module, one vocabulary
    if not terms:
        return ()
    hits = [f.name for f in found.fields
            if terms & svc._terms(f"{f.name} {f.business_name}")]  # noqa: SLF001
    return tuple(hits[:6])


# --------------------------------------------------------------- the answers


def respond(request: Request) -> Answer:
    """The answer to one metadata question."""
    handler = _HANDLERS.get(request.kind)
    if handler is None:  # pragma: no cover - Kind and _HANDLERS are one list
        return _totals(request)
    return handler(request)


def _domain_list(request: Request) -> Answer:
    headings = svc.domains()
    installed = [h for h in headings if h.installed]
    empty = [h for h in headings if not h.installed]
    lines = [f"CreditProbe is organised into {_count(len(headings), 'data domain')}. "
             f"{_count(len(installed), 'domain')} "
             f"{'has' if len(installed) == 1 else 'have'} data installed, "
             f"holding {_count(sum(h.dataset_count for h in headings), 'dataset')} "
             f"and {sum(h.row_count for h in headings):,} rows in total."]
    if empty:
        lines.append(
            "Nothing is installed under "
            + ", ".join(h.name for h in empty)
            + " in this deployment.")
    return _answer(" ".join(lines), [_domain_row(h) for h in headings],
                   DOMAIN_COLUMNS, request=request,
                   follow_ups=[f"What is in the {installed[0].name} domain?"]
                   if installed else [])


def _domain_detail(request: Request) -> Answer:
    heading = svc.domain(request.subject)
    if heading is None:
        return _no_such(request, "domain")
    found = [svc.dataset(name) for name in heading.datasets]
    rows = [_dataset_row(d) for d in found if d is not None]
    if not rows:
        text = (f"The {heading.name} domain exists but has no data installed "
                f"in this deployment.")
    else:
        text = (f"The {heading.name} domain holds "
                f"{_count(len(rows), 'dataset')}, "
                f"{heading.field_count:,} governed fields and "
                f"{heading.row_count:,} rows, covering "
                f"{_periods_text(heading.periods)}.")
    return _answer(text, rows, DATASET_COLUMNS, request=request,
                   detail={"domain": heading.to_dict()})


def _dataset_list(request: Request) -> Answer:
    # Named by its governed name, not by whatever the reader typed. A domain
    # matched loosely and then quoted back verbatim produced "25 datasets in
    # the portfolio_facility domain", which is not the name of a domain.
    heading = svc.domain(request.subject) if request.subject else None
    found = svc.datasets(heading.name) if heading is not None else svc.datasets()
    where = f" in the {heading.name} domain" if heading is not None else ""
    text = (f"There {'is' if len(found) == 1 else 'are'} "
            f"{_count(len(found), 'governed dataset')}{where}, holding "
            f"{sum(d.row_count for d in found):,} rows across "
            f"{sum(d.field_count for d in found):,} governed fields.")
    return _answer(text, [_dataset_row(d) for d in found], DATASET_COLUMNS,
                   request=request)


def _dataset_detail(request: Request) -> Answer:
    found = svc.dataset(request.subject)
    if found is None:
        return _no_such(request, "dataset")
    text = (f"{found.business_name} ({found.name}) sits in the {found.domain} "
            f"domain. {found.grain} It carries "
            f"{_count(found.field_count, 'governed field')} over "
            f"{_periods_text(found.periods)}, and holds "
            f"{found.row_count:,} rows.")
    if found.authoritative_for:
        text += (" It is the authoritative source for "
                 + ", ".join(found.authoritative_for) + ".")
    if found.purpose:
        text += f" {found.purpose}"
    return _answer(text, [_dataset_row(found)], DATASET_COLUMNS,
                   request=request,
                   detail={"dataset": found.to_dict()},
                   follow_ups=[f"What fields does {found.name} have?"])


def _field_list(request: Request) -> Answer:
    found = svc.dataset(request.subject)
    if found is None:
        heading = svc.domain(request.subject)
        if heading is not None:
            return _domain_detail(request)
        return _no_such(request, "dataset")
    rows = [f.to_dict() for f in found.fields]
    measures = len(found.measures)
    text = (f"{found.business_name} ({found.name}) has "
            f"{_count(len(rows), 'governed field')}: "
            f"{_count(measures, 'numeric measure')} and "
            f"{_count(len(rows) - measures, 'attribute')}. "
            f"Its period field is {found.period_field or 'not declared'} and "
            f"one row is: {found.grain}")
    return _answer(text, rows, FIELD_COLUMNS, request=request)


def _field_meaning(request: Request) -> Answer:
    wanted = request.subject
    hits: list[tuple[svc.Dataset, svc.Field]] = []
    for found in svc.datasets():
        if request.other and found.name != request.other:
            continue
        declared = found.field(wanted)
        if declared is not None:
            hits.append((found, declared))
    if not hits:
        return _no_such(request, "field")
    first = hits[0][1]
    text = (f"{first.business_name or first.name} "
            f"({first.name}){' — ' + first.definition if first.definition else ''}")
    if first.unit:
        text += f" Unit: {first.unit}."
    if len(hits) > 1:
        text += (f" It appears in {_count(len(hits), 'governed dataset')}.")
    rows = []
    for found, declared in hits:
        row = declared.to_dict()
        row["dataset"] = found.name
        row["domain"] = found.domain
        rows.append(row)
    columns = ([{"name": "dataset", "label": "Dataset", "semantic": "text"}]
               + FIELD_COLUMNS)
    return _answer(text, rows, columns, request=request)


def _periods(request: Request) -> Answer:
    if request.subject:
        found = svc.dataset(request.subject)
        if found is not None:
            text = (f"{found.business_name} ({found.name}) is published for "
                    f"{_count(found.period_count, 'period')}: "
                    f"{_periods_text(found.periods)}.")
            return _answer(text, [_dataset_row(found)], DATASET_COLUMNS,
                           request=request,
                           detail={"periods": list(found.periods)})
        heading = svc.domain(request.subject)
        if heading is not None:
            text = (f"The {heading.name} domain is published for "
                    f"{_count(len(heading.periods), 'period')}: "
                    f"{_periods_text(heading.periods)}.")
            rows = [_dataset_row(d) for d in
                    (svc.dataset(n) for n in heading.datasets) if d]
            return _answer(text, rows, DATASET_COLUMNS, request=request,
                           detail={"periods": list(heading.periods)})
    every = svc.periods()
    text = (f"The governed data covers {_count(len(every), 'reporting period')}"
            f": {_periods_text(every)}. Individual datasets cover different "
            f"parts of that window.")
    rows = [_dataset_row(d) for d in svc.datasets() if d.periods]
    rows.sort(key=lambda r: (-int(r["rows"] or 0), r["dataset"]))
    return _answer(text, rows, DATASET_COLUMNS, request=request,
                   detail={"periods": list(every)})


def _row_count(request: Request) -> Answer:
    if request.subject:
        found = svc.dataset(request.subject)
        if found is not None:
            text = (f"{found.business_name} ({found.name}) holds "
                    f"{found.row_count:,} rows over "
                    f"{_periods_text(found.periods)}.")
            return _answer(text, [_dataset_row(found)], DATASET_COLUMNS,
                           request=request)
        heading = svc.domain(request.subject)
        if heading is not None:
            text = (f"The {heading.name} domain holds {heading.row_count:,} "
                    f"rows across {_count(heading.dataset_count, 'dataset')}.")
            rows = [_dataset_row(d) for d in
                    (svc.dataset(n) for n in heading.datasets) if d]
            return _answer(text, rows, DATASET_COLUMNS, request=request)
    every = svc.counts()
    text = (f"The governed catalogue holds {every['rows']:,} rows across "
            f"{_count(every['datasets'], 'dataset')}.")
    rows = sorted((_dataset_row(d) for d in svc.datasets()),
                  key=lambda r: (-int(r["rows"] or 0), r["dataset"]))
    return _answer(text, rows, DATASET_COLUMNS, request=request)


def _relationship(request: Request) -> Answer:
    left, right = request.subject, request.other
    edges = svc.relationships(left) if left else svc.relationships()
    if right:
        edges = tuple(r for r in edges
                      if right in (r.left, r.right))
    rows = [r.to_dict() for r in edges]
    if not rows:
        both = " and ".join(x for x in (left, right) if x)
        text = (f"No governed join is declared "
                f"{'between ' + both if both else 'for that pair'}. "
                f"A steward declares joins in the Data Builder; without one, "
                f"CreditProbe will not invent a key to link them.")
        return _answer(text, rows, RELATIONSHIP_COLUMNS, request=request)
    first = edges[0]
    text = (f"{first.left} joins {first.right} on "
            f"{first.left_field} = {first.right_field}"
            f"{' (' + first.kind + ')' if first.kind else ''}. "
            f"{_count(len(rows), 'governed join')} "
            f"{'is' if len(rows) == 1 else 'are'} declared here.")
    return _answer(text, rows, RELATIONSHIP_COLUMNS, request=request)


def _subject(request: Request) -> Answer:
    found, missing = svc.coverage(request.subject)
    subject = request.subject or "that"
    if not found:
        text = (f"No governed dataset in this deployment carries data about "
                f"{subject}. What is installed is listed under "
                + ", ".join(h.name for h in svc.domains() if h.installed)
                + ".")
        return _answer(text, [_domain_row(h) for h in svc.domains()],
                       DOMAIN_COLUMNS, request=request)
    rows = [_dataset_row(d, relevant=_fields_matching(d, request.subject))
            for d in found]
    headings = sorted({d.domain for d in found})
    text = (f"{_count(len(found), 'governed dataset')} "
            f"{'bears' if len(found) == 1 else 'bear'} on {subject}, across "
            + ", ".join(headings) + ".")
    if missing:
        # Named, because a relevance ranking that quietly drops the words it
        # could not match answers a narrower question than the one asked.
        text += (" No governed dataset or field is named for "
                 + ", ".join(missing)
                 + "; that part of the question cannot be answered from "
                   "governed data here.")
    return _answer(text, rows, DATASET_COLUMNS, request=request,
                   detail={"not_covered": list(missing)})


def _planning(request: Request) -> Answer:
    found, missing = svc.coverage(request.subject, limit=12)
    subject = request.subject or "that question"
    if not found:
        text = (f"To work on {subject} CreditProbe would need governed data "
                f"that is not installed here. The domains that do hold data "
                f"are " + ", ".join(h.name for h in svc.domains()
                                    if h.installed) + ".")
        return _answer(text, [_domain_row(h) for h in svc.domains()],
                       DOMAIN_COLUMNS, request=request)
    rows = [_dataset_row(d, relevant=_fields_matching(d, request.subject))
            for d in found]
    headings = sorted({d.domain for d in found})
    text = (f"To work on {subject} CreditProbe would read "
            f"{_count(len(headings), 'data domain')} — "
            + ", ".join(headings)
            + f" — and {_count(len(found), 'governed dataset')} "
            + ("within it. " if len(headings) == 1 else "within them. ")
            + "The table names each one, the fields that bear on the "
              "question, what one row represents and which periods are "
              "published.")
    if missing:
        text += (" No governed dataset or field is named for "
                 + ", ".join(missing) + ".")
    return _answer(text, rows, DATASET_COLUMNS, request=request,
                   detail={"domains": headings, "not_covered": list(missing)})


def _totals(request: Request) -> Answer:
    every = svc.counts()
    headings = svc.domains()
    text = (f"This deployment holds {_count(every['datasets'], 'governed dataset')} "
            f"across {_count(every['domains'], 'data domain')} "
            f"({every['domains_installed']} with data installed), "
            f"{every['fields']:,} governed fields and {every['rows']:,} rows. "
            f"The published window is {_periods_text(svc.periods())}.")
    return _answer(text, [_domain_row(h) for h in headings], DOMAIN_COLUMNS,
                   request=request, detail={"counts": every},
                   follow_ups=["Which data domains exist?",
                               "What datasets are in Core Portfolio / Facility?"])


def _no_such(request: Request, what: str) -> Answer:
    """Named something that is not governed here. Say so; do not guess."""
    if what == "domain":
        rows = [_domain_row(h) for h in svc.domains()]
        columns = DOMAIN_COLUMNS
        known = ", ".join(h.name for h in svc.domains())
    else:
        rows = [_dataset_row(d) for d in svc.datasets()]
        columns = DATASET_COLUMNS
        known = ", ".join(d.name for d in svc.datasets()[:12]) + ", …"
    text = (f"There is no governed {what} matching "
            f"“{request.subject}” in this deployment. "
            f"What exists: {known}.")
    return _answer(text, rows, columns, request=request)


_HANDLERS = {
    Kind.DOMAIN_LIST: _domain_list,
    Kind.DOMAIN_DETAIL: _domain_detail,
    Kind.DATASET_LIST: _dataset_list,
    Kind.DATASET_DETAIL: _dataset_detail,
    Kind.FIELD_LIST: _field_list,
    Kind.FIELD_MEANING: _field_meaning,
    Kind.PERIODS: _periods,
    Kind.ROW_COUNT: _row_count,
    Kind.RELATIONSHIP: _relationship,
    Kind.SUBJECT: _subject,
    Kind.PLANNING: _planning,
    Kind.TOTALS: _totals,
}


__all__ = ["ANSWERS_VERSION", "DATASET_COLUMNS", "DOMAIN_COLUMNS",
           "FIELD_COLUMNS", "RELATIONSHIP_COLUMNS", "Answer", "respond"]
