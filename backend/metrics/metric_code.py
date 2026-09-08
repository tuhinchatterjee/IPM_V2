"""The artefact a person approves before a new metric is allowed to run.

§6 lists sixteen things a generated metric must be able to say about itself,
§10 says a person must see them before the metric is locked, and §13 says all
of it is persisted when they do. This module is that artefact — one object,
carried in the request body through generate → validate → approve → preview →
lock, and stored on the metric at the end.

Two programs, and which one runs
---------------------------------
A `MetricCode` carries the calculation twice, on purpose:

``program``
    The governed execution program — a formula tree, or a composite over
    formula trees. This is what CreditProbe compiles, validates and RUNS. It
    goes through `backend.runtime`: parameterised SQL, catalogue-checked
    identifiers, no interpolated values, the same path every other number in
    the product takes.

``sql``
    The SQL the model wrote. This is what the PERSON reads and approves. It is
    validated statically — safety, domain, fields, joins — and reconciled
    against `program`, and it is never sent to a database.

§7 requires exactly that separation: "Do NOT let Opus-generated code execute
directly." A reader who wants to check that claim can search this package for
an execution path that takes `MetricCode.sql`; there is none. What executes is
`compiled_sql`, which `backend.metrics.builder.compiled_sql` renders from
`program` through the ordinary compiler, and which is shown beside the model's
SQL so the two can be compared on screen.

Why not just show the compiled SQL and skip the model's
--------------------------------------------------------
Because then nothing would have been checked. The compiled SQL is correct by
construction — it is generated from the program — so showing it alone proves
only that the compiler works. The model's SQL is an INDEPENDENT statement of
what the metric is meant to do, and reconciling it against the program is what
catches a program that computes something other than what the model described.
That reconciliation is `codeguard.reconcile`, and it has found the failure it
exists for: a denominator the prose named and the tree omitted.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from backend.metrics.composite import Composite
from backend.metrics.formula import Formula

CODE_VERSION = "3.0.0"

#: What language the model wrote. Only these two; §6's "safe read-only SQL or
#: governed Python analytical code".
LANGUAGES = ("sql", "python")

#: Where a metric definition is in the §10 sequence. Not the catalogue's
#: `STATUS`, which is about how far a metric has been VERIFIED — this is about
#: how far this particular code artefact has got through review, and the two
#: are different questions with different answers.
STAGE_GENERATED = "GENERATED"
STAGE_VALIDATED = "VALIDATED"
STAGE_REJECTED = "REJECTED"
STAGE_APPROVED = "APPROVED"
STAGE_PREVIEWED = "PREVIEWED"
STAGE_LOCKED = "LOCKED"
STAGES = (STAGE_GENERATED, STAGE_VALIDATED, STAGE_REJECTED, STAGE_APPROVED,
          STAGE_PREVIEWED, STAGE_LOCKED)

STAGE_LABELS = {
    STAGE_GENERATED: "Code written",
    STAGE_VALIDATED: "Validated by CreditProbe",
    STAGE_REJECTED: "Rejected by CreditProbe",
    STAGE_APPROVED: "Approved by you",
    STAGE_PREVIEWED: "Previewed on real data",
    STAGE_LOCKED: "Locked",
}

#: Who last wrote the code. A person who edited the generated SQL owns it from
#: that point, and every screen says so — §11's "never trust user code merely
#: because it came from the browser" is enforced by revalidating, and this is
#: how a reader knows which they are looking at.
AUTHOR_MODEL = "MODEL"
AUTHOR_USER = "USER"
#: CreditProbe's own deterministic reader wrote this, because no model is
#: configured. The distinction is not cosmetic: when CreditProbe writes both
#: the program and the SQL, the SQL is RENDERED FROM the program, so
#: reconciling the two proves only that the renderer works. Every screen that
#: shows an artefact says which of the three wrote it, and the validation
#: report says so too.
AUTHOR_CREDITPROBE = "CREDITPROBE"

AUTHOR_LABELS = {
    AUTHOR_MODEL: "Written by CreditProbe AI",
    AUTHOR_USER: "Edited by you",
    AUTHOR_CREDITPROBE: "Assembled by CreditProbe (no AI provider configured)",
}


@dataclass
class MetricCode:
    """One generated metric definition, with everything §6 asks it to carry."""

    # ---- §6.1–§6.4: what it is, in the person's terms -------------------
    name: str = ""
    #: §6.2. Byte-for-byte what the person typed. Never regenerated.
    user_formula: str = ""
    #: §6.3. What CreditProbe understood that to mean, as algebra.
    interpreted_formula: str = ""
    #: §6.4. The steps, numbered, in English.
    plain_english: list[str] = field(default_factory=list)

    # ---- §6.5–§6.13: where the number comes from ------------------------
    domains: list[str] = field(default_factory=list)      # §6.5
    datasets: list[str] = field(default_factory=list)     # §6.6
    fields: list[str] = field(default_factory=list)       # §6.7
    grain: str = ""                                       # §6.8
    period_logic: str = ""                                # §6.9
    filters: list[str] = field(default_factory=list)      # §6.10
    join_logic: str = ""                                  # §6.11
    aggregation: str = ""                                 # §6.12
    unit: str = "number"                                  # §6.13

    # ---- §6.14–§6.16: the code, and why it is here ----------------------
    #: §6.14. What the model wrote. Read and approved; never executed.
    sql: str = ""
    language: str = "sql"
    #: Governed analytical steps, for the Python execution path.
    python: str = ""
    output_grain: str = ""                                # §6.15
    why: str = ""                                         # §6.16

    # ---- what actually runs ---------------------------------------------
    formula: Formula | None = None
    composite: Composite | None = None
    #: Governed filters applied to every term — the metric's own scope.
    scope: list[dict[str, Any]] = field(default_factory=list)
    decimals: int = 2

    # ---- provenance ------------------------------------------------------
    stage: str = STAGE_GENERATED
    author: str = AUTHOR_MODEL
    model: str = ""
    #: The statement CreditProbe will actually run, rendered from `formula` or
    #: from the composite's legs. Filled in by the validator, never by a model.
    compiled_sql: str = ""
    compiled_params: list[str] = field(default_factory=list)
    #: Filled in by the validator.
    validation: dict[str, Any] = field(default_factory=dict)
    #: What the person wrote when they approved it.
    approval_note: str = ""
    notes: list[str] = field(default_factory=list)
    version: str = CODE_VERSION

    # -- identity ----------------------------------------------------------

    @property
    def program(self) -> Formula | Composite | None:
        """What runs. A composite where there is one, else the formula."""
        return self.composite if self.composite is not None else self.formula

    @property
    def is_composite(self) -> bool:
        return self.composite is not None

    def checksum(self) -> str:
        """What a person approved, as a digest.

        Covers the code, the program and the declared shape — everything an
        approval is an approval OF. `stage`, `approval_note` and `validation`
        are excluded because they change AFTER approval and would make an
        approved artefact fail to match itself.
        """
        body = json.dumps({
            "name": self.name, "user_formula": self.user_formula,
            "interpreted_formula": self.interpreted_formula,
            "sql": self.sql, "python": self.python, "language": self.language,
            "unit": self.unit, "scale": getattr(self.formula, "scale", None),
            "formula": self.formula.to_dict() if self.formula else None,
            "composite": self.composite.to_dict() if self.composite else None,
            "scope": self.scope,
        }, sort_keys=True, default=str)
        return hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]

    # -- serialisation -----------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "user_formula": self.user_formula,
            "interpreted_formula": self.interpreted_formula,
            "plain_english": list(self.plain_english),
            "domains": list(self.domains),
            "datasets": list(self.datasets),
            "fields": list(self.fields),
            "grain": self.grain,
            "period_logic": self.period_logic,
            "filters": list(self.filters),
            "join_logic": self.join_logic,
            "aggregation": self.aggregation,
            "unit": self.unit,
            "sql": self.sql,
            "language": self.language,
            "python": self.python,
            "output_grain": self.output_grain,
            "why": self.why,
            "formula": self.formula.to_dict() if self.formula else None,
            "composite": self.composite.to_dict() if self.composite else None,
            "scope": list(self.scope),
            "decimals": self.decimals,
            "stage": self.stage,
            "stage_label": STAGE_LABELS.get(self.stage, self.stage),
            "author": self.author,
            "author_label": AUTHOR_LABELS.get(self.author, self.author),
            "independently_written": self.author != AUTHOR_CREDITPROBE,
            "model": self.model,
            "compiled_sql": self.compiled_sql,
            "compiled_params": list(self.compiled_params),
            "validation": dict(self.validation),
            "approval_note": self.approval_note,
            "notes": list(self.notes),
            "checksum": self.checksum(),
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> MetricCode:
        raw_formula = payload.get("formula")
        raw_composite = payload.get("composite")
        return cls(
            name=str(payload.get("name") or ""),
            user_formula=str(payload.get("user_formula") or ""),
            interpreted_formula=str(payload.get("interpreted_formula") or ""),
            plain_english=[str(s) for s in (payload.get("plain_english") or [])],
            domains=[str(s) for s in (payload.get("domains") or [])],
            datasets=[str(s) for s in (payload.get("datasets") or [])],
            fields=[str(s) for s in (payload.get("fields") or [])],
            grain=str(payload.get("grain") or ""),
            period_logic=str(payload.get("period_logic") or ""),
            filters=[str(s) for s in (payload.get("filters") or [])],
            join_logic=str(payload.get("join_logic") or ""),
            aggregation=str(payload.get("aggregation") or ""),
            unit=str(payload.get("unit") or "number"),
            sql=str(payload.get("sql") or ""),
            language=str(payload.get("language") or "sql"),
            python=str(payload.get("python") or ""),
            output_grain=str(payload.get("output_grain") or ""),
            why=str(payload.get("why") or ""),
            formula=Formula.from_dict(raw_formula) if raw_formula else None,
            composite=(Composite.from_dict(raw_composite)
                       if raw_composite else None),
            scope=[dict(s) for s in (payload.get("scope") or [])],
            decimals=int(payload.get("decimals") or 2),
            stage=str(payload.get("stage") or STAGE_GENERATED),
            author=str(payload.get("author") or AUTHOR_MODEL),
            model=str(payload.get("model") or ""),
            compiled_sql=str(payload.get("compiled_sql") or ""),
            compiled_params=[str(s) for s in (payload.get("compiled_params") or [])],
            validation=dict(payload.get("validation") or {}),
            approval_note=str(payload.get("approval_note") or ""),
            notes=[str(s) for s in (payload.get("notes") or [])],
            version=str(payload.get("version") or CODE_VERSION),
        )

    def scope_tuple(self) -> tuple[Any, ...]:
        """The metric's own scope, in the shape the executor takes."""
        from backend.metrics.formula import Condition

        return tuple(Condition.from_dict(c) for c in self.scope)


__all__ = [
    "AUTHOR_CREDITPROBE", "AUTHOR_LABELS", "AUTHOR_MODEL", "AUTHOR_USER",
    "CODE_VERSION", "LANGUAGES",
    "STAGES", "STAGE_APPROVED", "STAGE_GENERATED", "STAGE_LABELS",
    "STAGE_LOCKED", "STAGE_PREVIEWED", "STAGE_REJECTED", "STAGE_VALIDATED",
    "MetricCode",
]
