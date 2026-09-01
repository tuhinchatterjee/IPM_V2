"""
The Analysis Studio's operations, above HTTP and below the API.

The flow a person actually goes through:

    describe → CreditProbe reads it back → answer what it could not decide
    → build → validate → certify

Each step is a function here, and each one refuses rather than degrades. A
description that is not understood produces a question, not a guess. A method
whose validation pack has not passed cannot be certified, whoever is asking.
Certification is the only irreversible-feeling act in the Studio, so it is the
one with the narrowest gate.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import Any

from backend.studio.builder import Reading, build_method, read_description
from backend.studio.model import (
    CERTIFIED_STATES,
    Category,
    Lifecycle,
    MethodDefinition,
)
from backend.studio.registry import MethodNotFound, Registry, get_registry
from backend.studio.validation import ValidationPack, build_forward_rate_pack, run_pack

logger = logging.getLogger(__name__)


class StudioError(ValueError):
    """Something the Studio refuses to do, with the reason attached."""


def describe(text: str) -> Reading:
    """Read a description and work out what still has to be decided."""
    return read_description(text)


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", str(name).lower()).strip("_")
    return slug or "method"


def build(*, name: str, description: str, answers: dict[str, str],
          opening_period: str, closing_period: str,
          dataset: str = "portfolio_facility", author: str = "",
          method_id: str = "") -> tuple[MethodDefinition, ValidationPack]:
    """Build a method from a description and run its validation pack.

    Build and validate together, always. A method that exists but has never been
    run against anything is the state this product is trying to eliminate — the
    plausible calculation nobody checked.
    """
    reading = describe(description)
    if not reading.understood:
        raise StudioError(reading.note)

    unresolved = [c.id for c in reading.clarifications
                  if c.id not in answers and c.default == ""]
    if unresolved:
        raise StudioError(
            "These decisions change the answer and have not been made: "
            + ", ".join(unresolved))

    filled = {c.id: c.default for c in reading.clarifications if c.default}
    filled.update({k: v for k, v in answers.items() if v})

    try:
        method = build_method(
            id=method_id or slugify(name), name=name, description=description,
            reading=reading, answers=filled, opening_period=opening_period,
            closing_period=closing_period, dataset=dataset, author=author,
        )
    except ValueError as e:
        # The builder refuses what it cannot compute honestly — "default at any
        # point in the horizon" being the one that matters. Surfaced as-is:
        # the reason is the useful part.
        raise StudioError(str(e)) from e

    pack = run_pack(build_forward_rate_pack(method), method)
    method.test_cases = pack.cases
    if pack.all_passed:
        method.lifecycle = Lifecycle.VALIDATED
    method.updated_at = datetime.now(UTC).isoformat()
    return method, pack


def revalidate(method: MethodDefinition) -> ValidationPack:
    """Run the pack again — after an edit, or before a sign-off."""
    pack = run_pack(build_forward_rate_pack(method), method)
    method.test_cases = pack.cases
    method.updated_at = datetime.now(UTC).isoformat()
    return pack


def certify(method: MethodDefinition, *, by: str) -> MethodDefinition:
    """Award the tick, or refuse and say what is missing.

    `can_certify` reports every gap rather than the first, because somebody
    preparing a method for sign-off needs the whole list, not a queue of one
    rejection at a time.
    """
    if not by.strip():
        raise StudioError("Certification has to be attributed to somebody.")
    ok, missing = method.can_certify()
    if not ok:
        raise StudioError(
            "This method cannot be certified yet. It is missing: "
            + "; ".join(missing))
    method.lifecycle = Lifecycle.CERTIFIED
    method.certified_at = datetime.now(UTC).isoformat()
    method.certified_by = by
    method.updated_at = method.certified_at
    return method


def fork(source: MethodDefinition, *, name: str, by: str = "",
         method_id: str = "") -> MethodDefinition:
    """Copy a method so a bank can change it without touching the original.

    The fork starts as a DRAFT with no tick and no test results, however
    certified its parent was. Inheriting evidence for a method nobody has run is
    exactly how a certification claim becomes meaningless.
    """
    new_id = method_id or f"{slugify(name)}"
    if new_id == source.id:
        raise StudioError("A fork needs a different id from its source.")

    copy = MethodDefinition.from_dict(source.to_dict(full=True))
    copy.id = new_id
    copy.name = name
    copy.aliases = []
    copy.lifecycle = Lifecycle.DRAFT
    copy.version = "1.0.0"
    copy.versions = []
    copy.certified_at = ""
    copy.certified_by = ""
    copy.forked_from = source.id
    copy.source = "bank"
    copy.owner = by or source.owner
    copy.created_at = datetime.now(UTC).isoformat()
    copy.updated_at = copy.created_at
    for case in copy.test_cases:
        case.passed = None
        case.actual = {}
        case.note = ("Inherited from the source method and not yet run against "
                     "this fork.")
    return copy


def edit(method: MethodDefinition, changes: dict[str, Any], *,
         change_note: str, by: str = "") -> tuple[MethodDefinition, list[str]]:
    """Apply an edit, recording the previous version if one was certified.

    Returns the method and a plain-English diff, because "what changed" is the
    question asked of an edited method and reading two JSON documents is not an
    answer.
    """
    editable = {
        "name", "definition", "purpose", "methodology", "when_to_use",
        "when_not_to_use", "interpretation", "limitations", "output_type",
        "aliases", "applicable_segments", "weighting_options", "owner",
    }
    rejected = set(changes) - editable
    if rejected:
        raise StudioError(
            "These are computed from the plan and cannot be edited as prose: "
            + ", ".join(sorted(rejected)))

    diff: list[str] = []
    for key, value in changes.items():
        before = getattr(method, key)
        if before == value:
            continue
        diff.append(f"{key}: {_short(before)} → {_short(value)}")
        setattr(method, key, value)

    if not diff:
        return method, []

    if method.lifecycle in CERTIFIED_STATES:
        # The signed-off version stays in the history exactly as it was. That is
        # the whole reason for keeping versions rather than a modified date.
        method.bump(change_note=change_note or "; ".join(diff), by=by,
                    lifecycle=Lifecycle.DRAFT)
    else:
        method.updated_at = datetime.now(UTC).isoformat()
    return method, diff


def _short(value: Any, limit: int = 60) -> str:
    text = ", ".join(map(str, value)) if isinstance(value, list) else str(value)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _domains_for(datasets: list[str]) -> list[str]:
    """The governed domains the method reads.

    Derived from the catalogue rather than assumed: a multi-dataset method that
    declared only the facility domain would be offered for a question its
    other sources have since been archived out of.
    """
    if not datasets:
        return ["credit_facility_position"]
    from backend.data_access.catalog import get_catalog

    catalog = get_catalog()
    domains: list[str] = []
    for name in datasets:
        try:
            domain = catalog.dataset(name).domain
        except Exception:
            continue
        if domain and domain not in domains:
            domains.append(domain)
    return domains or ["credit_facility_position"]


def _required_concepts(meta: dict[str, Any]) -> list[dict[str, Any]]:
    """What the method measures, in concepts rather than columns.

    A method that stored `ifrs9_staging.ead` breaks the day a bank supplies its
    own IFRS 9 extract under a different column name. One that stores "exposure
    at default" — with the dataset and field it resolved to on the day it was
    saved, and the reason it chose that one — can re-resolve against whatever
    the catalogue declares authoritative when it next runs, and can say what
    changed if the resolution moves.
    """
    out: list[dict[str, Any]] = []
    for raw in meta.get("concepts") or []:
        if not isinstance(raw, dict) or not raw.get("concept"):
            continue
        out.append({
            "concept": raw.get("concept"),
            "label": raw.get("label"),
            "dataset": raw.get("dataset"),
            "field": raw.get("field"),
            "definition": raw.get("definition"),
            "unit": raw.get("unit"),
            "reason": raw.get("reason"),
        })
    return out


def _required_relationships(meta: dict[str, Any]) -> list[dict[str, Any]]:
    """The governed joins the plan walked, at the version it walked them.

    Stored so the Studio can say "a steward has re-declared one of the joins
    this method depends on" — a change that alters what the method means
    without altering a character of its plan.
    """
    path = meta.get("join_path") or {}
    out: list[dict[str, Any]] = []
    seen: set[int] = set()
    for edge in path.get("edges") or []:
        identifier = edge.get("relationship_id")
        if identifier is None or identifier in seen:
            continue
        seen.add(identifier)
        out.append({
            "relationship_id": identifier,
            "name": edge.get("relationship_name"),
            "version": edge.get("relationship_version"),
            "left": edge.get("left"), "right": edge.get("right"),
            "cardinality": edge.get("cardinality"),
            "join_policy": edge.get("join_policy"),
            "temporal_rule": edge.get("temporal_rule"),
        })
    return out


def _period_alignment(meta: dict[str, Any]) -> dict[str, Any]:
    """How periods were reconciled across sources of different frequency.

    Two methods with the same plan and different alignment answer different
    questions: a quarterly book joined to the rating cycle that had completed
    by the reporting date is not the same population as one joined to the cycle
    the quarter falls inside.
    """
    path = meta.get("join_path") or {}
    asof = [
        {"dataset": edge.get("right"), "rule": edge.get("temporal_rule")}
        for edge in path.get("edges") or []
        if edge.get("temporal_rule") == "latest_on_or_before"
    ]
    alignment: dict[str, Any] = {
        "opening_period": meta.get("opening_period"),
        "closing_period": meta.get("closing_period"),
        "as_of": asof,
    }
    if asof:
        names = ", ".join(str(a["dataset"]) for a in asof)
        alignment["description"] = (
            f"{names} is reported at a different frequency and was joined "
            "as-of — the latest observation on or before the reporting date, "
            "never after it")
    elif meta.get("opening_period") and meta.get("closing_period"):
        alignment["description"] = (
            "every source was read at the same reporting period")
    return alignment


def from_dynamic(*, name: str, question: str, plan: dict[str, Any],
                 summary: str = "", author: str = "",
                 method_id: str = "") -> MethodDefinition:
    """Keep a dynamic analysis as a method.

    A composed analysis is a one-off by default: it answered a question and
    then it is gone. Saving one is how a bank turns "somebody asked this in
    March" into something the whole team can run — but it arrives as a DRAFT
    with no tests and no tick, because nothing about running once against one
    pair of periods is evidence that it is right.
    """
    if not (plan.get("operations") or []):
        raise StudioError("There is no analytical plan to save.")

    meta = dict(plan.get("meta") or {})
    conditions = [str(c.get("description") or "") for c in meta.get("conditions") or []]
    filters = [f"{f.get('field')} = {f.get('value')}" for f in meta.get("filters") or []]
    grain = str(meta.get("grain") or "facility")
    concepts = _required_concepts(meta)
    relationships = _required_relationships(meta)
    alignment = _period_alignment(meta)
    datasets = [str(d) for d in meta.get("datasets") or []]

    methodology = "\n".join(line for line in [
        f"Question as asked: {question}",
        f"Read as: {summary}" if summary else "",
        f"Grain: one row per {grain}.",
        f"Governed filters: {', '.join(filters) or 'none'}.",
        "Conditions, all of which must hold:",
        *[f"  - {c}" for c in conditions],
        f"Measured between {meta.get('opening_period')} and "
        f"{meta.get('closing_period')} on the run that produced it.",
        (f"Read across {len(datasets)} governed sources: {', '.join(datasets)}."
         if len(datasets) > 1 else ""),
        (f"Period alignment: {alignment['description']}."
         if alignment.get("description") else ""),
    ] if line)

    return MethodDefinition(
        id=method_id or slugify(name), name=name,
        category=Category.CUSTOM,
        definition=summary or f"Composed from the question: {question}",
        purpose="Saved from a dynamic analysis so it can be run again.",
        methodology=methodology.strip(),
        lifecycle=Lifecycle.DRAFT,
        aliases=[],
        when_to_use="Where the same population has to be identified again.",
        when_not_to_use=(
            "Anywhere the answer will be relied on without review. This was "
            "composed for one question and has never been validated."),
        required_grain=f"One row per {grain} per reporting period",
        required_fields=sorted(
            {f"{c['dataset']}.{c['field']}" for c in concepts
             if c.get("dataset") and c.get("field")}
            or {str(c.get("field")) for c in meta.get("conditions") or []
                if c.get("field")}),
        required_domains=_domains_for(datasets),
        required_concepts=concepts,
        required_relationships=relationships,
        period_alignment=alignment,
        output_type="Row list",
        interpretation="Each row met every condition between the two dates.",
        limitations=(
            "Composed for one question and run against one pair of periods. "
            "It carries no test cases and no certification, and the thresholds "
            "in it were read from a sentence rather than agreed by anybody."),
        plan=plan,
        source="bank",
        owner=author or "Credit Risk Analytics",
        created_at=datetime.now(UTC).isoformat(),
        updated_at=datetime.now(UTC).isoformat(),
    )


# ---------------------------------------------------------------- persistence


def save(method: MethodDefinition, *, user_id: int | None = None) -> bool:
    """Store the method and put it in the live registry.

    Registers either way. A Studio running without a database is still usable
    for the length of a session, and the caller is told the difference so the UI
    can say "saved" or "saved for this session only" honestly.
    """
    from backend.services.studio import persist

    method.source = "bank"
    stored = persist(method, user_id=user_id)
    get_registry().register(method)
    return stored


def load(method_id: str, *, registry: Registry | None = None) -> MethodDefinition:
    try:
        return (registry or get_registry()).get(method_id)
    except MethodNotFound as e:
        raise StudioError(str(e)) from e


__all__ = ["StudioError", "build", "certify", "describe", "edit", "fork",
           "from_dynamic", "load", "revalidate", "save", "slugify"]
