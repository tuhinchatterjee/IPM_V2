"""
The Data Builder and Engine Builder assistants — conversation about the MODEL.

What these assistants are for
-----------------------------
"What does EAD mean here?" "Which datasets have a customer identifier?" "Which
analysis answers a question about staging, and what period does it need?" These
are questions about CreditProbe's governed metadata, and a person should be able to ask
them in English instead of clicking through a dictionary.

What they may see
-----------------
Governed metadata only: domain names, dataset names, field names and their
definitions, units, permitted values, lifecycle, origin, analysis contracts and
their parameters. Never a row of portfolio data, never a figure, never a file.

That is not a promise about prompt wording — it is what `context()` assembles,
and the model is only ever given what `context()` returns.

What they may do
----------------
Answer. That is all. They cannot map a field, publish a dataset, change a
definition, register an analysis or run one. Every one of those goes through the
existing governed endpoints with a steward's role attached. An assistant that
could act on the schema would be a much better demo and a much worse product.

Without a model key
-------------------
The deterministic answerer below handles the questions the metadata can answer
by lookup — a definition, where a field appears, which analyses need a period —
and says plainly when it cannot help. It never guesses at a definition, because
a wrong definition of "default" is worse than no answer.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from backend.config import settings

logger = logging.getLogger(__name__)

MAX_QUESTION_CHARS = 400

SYSTEM_PROMPT = """You are CreditProbe's metadata assistant. You answer questions about a \
credit-risk platform's GOVERNED METADATA: its data domains, datasets, fields and \
their definitions, and its registered analyses.

Absolute rules:
- You have no access to portfolio data and you never state a credit figure. If \
asked for one, say the question belongs in Ask CreditProbe, which runs a certified \
analysis and produces a Trace.
- You answer only from the metadata supplied below. If it does not contain the \
answer, say so and name what would have to be defined for the answer to exist.
- You never invent a field name, a dataset name, an analysis name or a definition.
- You describe; you do not change anything. If asked to map, publish, rename or \
run something, explain which screen and which role does it.
- Quote the governed name exactly as given, and give the business name alongside it.

Be brief. Two or three sentences unless a list is genuinely the answer."""


@dataclass
class Answer:
    """One reply, and what it was drawn from."""

    text: str
    #: The governed objects the answer refers to, so the UI can link to them.
    references: list[dict[str, str]] = field(default_factory=list)
    #: "lookup" when answered deterministically, "model" when a model wrote it.
    source: str = "lookup"
    #: Set when CreditProbe could not answer, so the UI can say why rather than nothing.
    unanswered_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "references": list(self.references),
            "source": self.source,
            "unanswered_reason": self.unanswered_reason,
            "rule": (
                "This assistant reads CreditProbe's governed metadata only. It has no access "
                "to portfolio data, states no credit figures, and changes nothing."
            ),
        }


# --------------------------------------------------------------- the context


def data_context() -> dict[str, Any]:
    """Everything the Data Builder assistant is allowed to see."""
    if not settings.has_database:
        return {"domains": [], "datasets": [], "available": False}

    from sqlalchemy import select

    from backend.db.engine import get_session
    from backend.models.platform import DataDomain, DatasetDefinition

    with get_session() as session:
        domains = [
            {"name": d.name, "description": d.description, "owner": d.owner}
            for d in session.execute(select(DataDomain).order_by(DataDomain.name)).scalars()
        ]
        datasets = []
        for dataset in session.execute(
            select(DatasetDefinition).order_by(DatasetDefinition.name)
        ).scalars():
            datasets.append({
                "name": dataset.name,
                "business_name": dataset.business_name or dataset.name,
                "domain": dataset.domain,
                "purpose": dataset.purpose,
                "grain": dataset.grain,
                "lifecycle": dataset.lifecycle,
                "origin": dataset.origin,
                "dataset_family": dataset.dataset_family,
                "authoritative_for": list(dataset.authoritative_for or []),
                "primary_keys": list(dataset.primary_keys or []),
                "fields": [
                    {
                        "name": f.name,
                        "business_name": f.business_name or f.name,
                        "definition": f.definition,
                        "data_type": f.data_type,
                        "unit": f.unit,
                    }
                    for f in sorted(dataset.fields, key=lambda x: x.name)
                ],
            })
        return {"domains": domains, "datasets": datasets, "available": True}


def engine_context() -> dict[str, Any]:
    """Everything the Engine Builder assistant is allowed to see."""
    from backend.engine.registry import get_registry

    registry = get_registry()
    analyses = []
    for analysis_id in registry.ids():
        try:
            contract = registry.contract(analysis_id)
        except Exception:  # pragma: no cover - a broken contract is its own problem
            continue
        analyses.append({
            "id": contract.id,
            "name": contract.name,
            "description": contract.description,
            "category": str(contract.category),
            "certification": str(contract.certification),
            "version": contract.version,
            "answer_shape": str(contract.answer_shape),
            "period_requirement": str(contract.period_requirement),
            "governed_default_period": contract.governed_default_period,
            "when_to_use": contract.when_to_use,
            "limitations": contract.limitations,
            "trigger_questions": list(contract.trigger_questions),
            "required_purposes": list(contract.required_domains),
            "parameters": [
                {"name": p.name, "type": str(p.type), "required": p.required,
                 "default": p.default, "description": p.description}
                for p in contract.parameters
            ],
        })
    return {"analyses": analyses, "available": bool(analyses)}


# ------------------------------------------------------- deterministic answers


def _norm(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text.lower()).split())


def _fields_index(context: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    index: dict[str, list[dict[str, Any]]] = {}
    for dataset in context.get("datasets") or []:
        for f in dataset.get("fields") or []:
            index.setdefault(f["name"], []).append({**f, "dataset": dataset["name"]})
            business = _norm(f.get("business_name") or "")
            if business and business != f["name"]:
                index.setdefault(business, []).append({**f, "dataset": dataset["name"]})
    return index


def _lookup_field(question: str, context: dict[str, Any]) -> Answer | None:
    """"What is X?" and "where is X?" against the data dictionary."""
    asked = _norm(question)
    index = _fields_index(context)

    # Longest name first, so "ecl coverage" beats "ecl".
    for name in sorted(index, key=len, reverse=True):
        needle = _norm(name)
        if len(needle) < 3 or needle not in asked:
            continue
        entries = index[name]
        first = entries[0]
        definition = first.get("definition") or ""
        where = ", ".join(sorted({e["dataset"] for e in entries}))
        unit = f" It is recorded in {first['unit']}." if first.get("unit") else ""

        if not definition:
            return Answer(
                text=(
                    f"'{first['name']}' ({first.get('business_name')}) exists in "
                    f"{where}, but it has no definition in the data dictionary. "
                    "Until someone writes one, CreditProbe cannot tell you what it means — "
                    "and neither can anyone reading a report built on it."
                ),
                references=[{"kind": "field", "name": first["name"], "dataset": where}],
                unanswered_reason="undefined_field",
            )

        return Answer(
            text=(
                f"{first.get('business_name')} (`{first['name']}`): {definition}"
                f"{unit} It appears in {where}."
            ),
            references=[{"kind": "field", "name": first["name"], "dataset": where}],
        )
    return None


def _lookup_dataset(question: str, context: dict[str, Any]) -> Answer | None:
    asked = _norm(question)
    for dataset in context.get("datasets") or []:
        for candidate in (dataset["name"], dataset.get("business_name") or ""):
            needle = _norm(candidate)
            if len(needle) < 4 or needle not in asked:
                continue
            demo = " It is CreditProbe's demonstration data." if dataset["origin"] == "demo" else ""
            authoritative = (
                f" It is the authoritative source for "
                f"{', '.join(dataset['authoritative_for'])}."
                if dataset["authoritative_for"] else
                " It is not authoritative for any governed purpose."
            )
            return Answer(
                text=(
                    f"{dataset['business_name']} (`{dataset['name']}`) sits in "
                    f"{dataset['domain']}. {dataset.get('purpose') or ''} "
                    f"Grain: {dataset.get('grain') or 'not recorded'}. "
                    f"It is {dataset['lifecycle']} with {len(dataset['fields'])} "
                    f"governed fields.{authoritative}{demo}"
                ).strip(),
                references=[{"kind": "dataset", "name": dataset["name"]}],
            )
    return None


def _lookup_analysis(question: str, context: dict[str, Any]) -> Answer | None:
    asked = _norm(question)
    for analysis in context.get("analyses") or []:
        for candidate in (analysis["id"], analysis["name"]):
            needle = _norm(candidate)
            if len(needle) < 4 or needle not in asked:
                continue
            period = {
                "point_in_time": "It answers for a single reporting period.",
                "two_period": "It compares two reporting periods.",
                "time_series": "It runs across the whole published history.",
                "user_defined_window": "It runs over a window you choose.",
            }.get(analysis["period_requirement"], "")
            if analysis["period_requirement"] != "point_in_time" and not analysis[
                "governed_default_period"
            ]:
                period += " CreditProbe will ask which periods to compare before running it."
            return Answer(
                text=(
                    f"{analysis['name']} (`{analysis['id']}`, v{analysis['version']}, "
                    f"{analysis['certification']}): {analysis['description']} {period} "
                    f"{analysis.get('limitations') or ''}"
                ).strip(),
                references=[{"kind": "analysis", "name": analysis["id"]}],
            )
    return None


def _joins(question: str, context: dict[str, Any]) -> Answer | None:
    """"Which datasets share a customer identifier?" — the join question."""
    if not re.search(r"\bjoin|link|connect|share|common\b", question.lower()):
        return None
    shared: dict[str, set[str]] = {}
    for dataset in context.get("datasets") or []:
        for f in dataset.get("fields") or []:
            shared.setdefault(f["name"], set()).add(dataset["name"])
    joinable = {k: v for k, v in shared.items() if len(v) > 1}
    if not joinable:
        return None
    # Ranked by how many datasets carry the field, not alphabetically.
    # Breadth is the signal: a field in six datasets across three domains is
    # a join key, while one in exactly two is usually a column two versions
    # of the same dataset happen to share. Sorting by name listed whatever
    # came first in the alphabet, so a wide new domain could push
    # customer_id off the answer entirely.
    ranked = sorted(joinable.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    lines = [
        f"`{name}` — {', '.join(sorted(datasets))}"
        for name, datasets in ranked[:8]
    ]
    return Answer(
        text=(
            "These governed fields appear in more than one dataset, which is what "
            "makes them joinable:\n" + "\n".join(lines)
        ),
        references=[{"kind": "field", "name": n}
                    for n, _ in ranked[:8]],
    )


def _cannot_answer(scope: str) -> Answer:
    where = "Data Builder" if scope == "data" else "Engine Builder"
    return Answer(
        text=(
            f"I could not find that in CreditProbe's governed metadata. I can only answer "
            f"from what is defined in {where} — domain, dataset, field and analysis "
            "definitions. If this should have an answer, the definition is missing, "
            "which is worth fixing whether or not you asked me. For a portfolio "
            "figure, ask CreditProbe on the Cockpit: that runs a certified analysis and "
            "produces a Trace."
        ),
        unanswered_reason="not_in_metadata",
    )


def _asks_for_a_figure(question: str) -> bool:
    return bool(re.search(
        r"\b(how much|how many|what is our|what's our|total|ratio|exposure is|"
        r"npl|ecl|coverage)\b.*\?*$", question.lower()
    ) and re.search(r"\b(our|the portfolio|the book|currently|now|today)\b",
                    question.lower()))


def ask(question: str, *, scope: str = "data") -> Answer:
    """Answer a metadata question. `scope` is "data" or "engine"."""
    question = (question or "").strip()[:MAX_QUESTION_CHARS]
    if not question:
        return Answer(text="Ask me about a dataset, a field or an analysis.",
                      unanswered_reason="empty")

    if _asks_for_a_figure(question):
        return Answer(
            text=(
                "That is a portfolio question, not a metadata one. Ask it on the "
                "Cockpit: CreditProbe will run a certified analysis against the published "
                "data and the answer will carry a Trace. I only describe the model."
            ),
            unanswered_reason="belongs_in_ask",
        )

    context = data_context() if scope == "data" else engine_context()

    for finder in (
        (_lookup_field, _lookup_dataset, _joins) if scope == "data"
        else (_lookup_analysis,)
    ):
        answer = finder(question, context)
        if answer is not None:
            return answer

    if settings.anthropic_api_key:
        answer = _ask_model(question, context, scope)
        if answer is not None:
            return answer

    return _cannot_answer(scope)


def _ask_model(question: str, context: dict[str, Any], scope: str) -> Answer | None:
    """Put the question to a model, with the governed metadata and nothing else."""
    import json

    try:
        import anthropic

        from backend.orchestration.planner import DEFAULT_MODEL

        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        message = client.messages.create(
            model=DEFAULT_MODEL,
            max_tokens=600,
            system=SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": (
                    f"GOVERNED METADATA:\n{json.dumps(context, default=str)}\n\n"
                    f"QUESTION: {question}"
                ),
            }],
        )
        text = "".join(b.text for b in message.content if b.type == "text").strip()
    except Exception as e:
        logger.warning("Metadata assistant model call failed: %s", e)
        return None

    if not text:
        return None
    return Answer(text=text, source="model")


__all__ = ["Answer", "ask", "data_context", "engine_context"]
