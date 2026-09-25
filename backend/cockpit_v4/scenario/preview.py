"""The preview a reader confirms, and the question that asks them to.

Section 6.2 lists fifteen things the final inline preview must show and then
says to ask *"Shall I execute this scenario using [selected methods]?"*,
requiring an affirmative response to the CURRENT preview.

The shape of that question is not new. The Cockpit already has a turn that
puts a question back to the reader with clickable choices and settles as
WAITING_FOR_USER -- `disposition: "clarification"`, the question in
`clarification_question`, the choices in `clarification_options` -- and
`context.build` already projects the reply back with `you_asked`,
`you_offered` and `the_question_still_standing`. A preview is that turn, with
the scenario's own summary as its narrative.

Using it rather than inventing a state machine is what keeps this capability
inside the approved architecture: no new disposition, no new route, no new
persisted lifecycle beyond the spec's own `state`, and the reply is read
correctly by machinery that already exists and is already tested.

WHAT THE PREVIEW MAY NOT DO, and this is the line section 6.2 draws twice:
*"Preview calculations may resolve transformed parameters, mapping readiness
and workload checks; do not run and present final ECL results before
confirmation."* So `build()` resolves what each input becomes, counts what is
eligible, and stops. It never touches `ecl_sar_mn`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from backend.cockpit_v4 import domains as dom
from backend.cockpit_v4.scenario import cohort as ch
from backend.cockpit_v4.scenario import fields as fd
from backend.cockpit_v4.scenario import rules as ru
from backend.cockpit_v4.scenario import spec as sp

#: What section 6.2 says every preview carries. Named so a test can assert
#: the list rather than a person remembering it.
REQUIRED_SECTIONS: tuple[str, ...] = (
    "scenario", "book", "period", "cohort", "baseline", "inputs",
    "translated", "artifact_versions", "stage_and_horizon", "overlaps",
    "unaffected", "bounds", "warnings", "methods", "source_is_not_changed",
)

#: The sentence section 6.2 requires the preview to carry. A reader
#: confirming a stress is entitled to know it is a simulation.
SOURCE_UNTOUCHED = (
    "This is a simulation. The published book is read and never written: no "
    "source row, no reported ECL and no accounting record changes, whatever "
    "this scenario produces."
)


@dataclass
class Preview:
    """Everything shown, plus the hash the confirmation will bind to."""

    spec: sp.ScenarioSpec
    body: dict[str, Any] = field(default_factory=dict)

    def digest(self) -> str:
        return self.spec.digest()

    def question(self) -> str:
        """Section 6.2's wording, with the reader's own methods named."""
        chosen = ", ".join(_method_label(m) for m in self.spec.methods)
        return f"Shall I execute this scenario using {chosen}?"

    def options(self) -> list[str]:
        """Clickable, because section 5.1 asks for choices rather than typing.

        "Change something" is here on purpose: a preview whose only options
        are yes and no invites a reader who wanted one number different to
        click yes and fix it afterwards.
        """
        chosen = ", ".join(_method_label(m) for m in self.spec.methods)
        return [f"Yes, run it with {chosen}",
                "Change a method",
                "Change an assumption",
                "Cancel this scenario"]

    def as_clarification(self) -> dict[str, Any]:
        """The `finalize_response` payload for the turn that asks.

        Shaped for the existing round trip, so the reply is projected back by
        machinery that already exists.
        """
        return {
            "disposition": "clarification",
            "narrative": self.narrative(),
            "clarification_question": self.question(),
            "clarification_options": self.options(),
            "whatif_preview": self.body,
            "whatif_digest": self.digest(),
        }

    def narrative(self) -> str:
        """The preview in prose, in the order a reader needs it."""
        b = self.body
        lines = [
            f"**{b['scenario']['name'] or 'Scenario'}** "
            f"(version {b['scenario']['version']}) on the {b['book']['label']} "
            f"book at {b['period']}.",
            "",
            f"**Cohort.** {b['cohort']['described']}",
            f"Baseline EAD {b['baseline']['ead']} SAR million, ECL "
            f"{b['baseline']['ecl']} SAR million, a coverage rate of "
            f"{b['baseline']['coverage_pct']}%.",
            "",
            "**What changes.**",
        ]
        for item in b["inputs"]:
            lines.append(
                f"- {item['field']}: {item['operation']}"
                + (f" — {item['note']}" if item.get("note") else ""))
        if b["overlaps"]:
            lines += ["", "**Overlapping rules.**"]
            lines += [f"- {o['question']}" for o in b["overlaps"]]
        lines += ["", f"**Unaffected.** {b['unaffected']}"]
        if b["warnings"]:
            lines += ["", "**Before you confirm.**"]
            lines += [f"- {w}" for w in b["warnings"]]
        lines += ["", b["source_is_not_changed"]]
        return "\n".join(lines)


def _method_label(method: str) -> str:
    return {sp.DELTA: "Delta", sp.ML: "the ML emulator",
            sp.USER_DEFINED: "your own impact assumption"}.get(method, method)


def build(*, spec: sp.ScenarioSpec, frozen: ch.Frozen,
          graph: ru.Graph | None = None,
          overlaps: tuple[ru.Overlap, ...] = (),
          readiness: dict[str, str] | None = None) -> Preview:
    """Assemble the preview. Resolves parameters; calculates no ECL.

    `readiness` maps a method to its status, so the preview can say which are
    available before the reader confirms -- section 2's requirement, and the
    reason Method 2 can be listed honestly as MODEL_NOT_READY rather than
    silently omitted.
    """
    # Building a preview IS reaching PREVIEW_READY: the assumptions are
    # resolved, the cohort is frozen and the methods are chosen, which is
    # what the three states before it mean. Walked rather than jumped, so an
    # illegal starting state is still refused by `advance`.
    while spec.state in (sp.DRAFT, sp.NEEDS_CLARIFICATION,
                         sp.SCENARIO_RESOLVED, sp.METHOD_SELECTION):
        spec = spec.advance({
            sp.DRAFT: sp.SCENARIO_RESOLVED,
            sp.NEEDS_CLARIFICATION: sp.SCENARIO_RESOLVED,
            sp.SCENARIO_RESOLVED: sp.METHOD_SELECTION,
            sp.METHOD_SELECTION: sp.PREVIEW_READY,
        }[spec.state])

    graph = graph or ru.compile_rules(spec, known=overlaps)
    ead = Decimal(frozen.ref.baseline_ead)
    ecl = Decimal(frozen.ref.baseline_ecl)
    coverage = (ecl / ead * 100) if ead else Decimal(0)

    inputs = []
    warnings = list(spec.warnings)
    for shock in graph.order():
        entry = fd.lookup(spec.source.domain_id, shock.field_id)
        note = fd.eligibility_note(spec.source.domain_id, shock.field_id)
        item: dict[str, Any] = {
            "field": shock.field_id,
            "operation": shock.amount.describe(),
            "unit": entry.unit,
            "storage": entry.storage,
            "availability": entry.availability,
            "derived_from": shock.derived_from,
            "origin": shock.origin,
            "note": "" if note.startswith("every row") else note,
        }
        if entry.availability == fd.DERIVED:
            item["derivation"] = entry.derivation
            warnings.append(
                f"{shock.field_id} is derived from published columns, not a "
                f"column of the book: {entry.derivation.splitlines()[0]}")
        if not note.startswith("every row"):
            warnings.append(f"{shock.field_id}: {note}")
        inputs.append(item)

    translated = [
        {"field": s.field_id, "from_rule": s.derived_from,
         "mapping_version": s.mapping_version,
         "operation": s.amount.describe()}
        for s in spec.derived_shocks()]

    body: dict[str, Any] = {
        "scenario": {"id": spec.scenario_id, "name": spec.name,
                     "version": spec.version,
                     "parent_version": spec.parent_version,
                     "state": spec.state},
        "book": {"domain_id": spec.source.domain_id,
                 "label": dom.LABELS.get(spec.source.domain_id,
                                         spec.source.domain_id),
                 "release_id": spec.source.release_id,
                 "release_fingerprint": spec.source.release_fingerprint},
        "period": spec.source.reporting_period,
        "cohort": {
            "described": frozen.describe(),
            "grain": frozen.ref.grain,
            "selection": frozen.selection,
            "entity_count": frozen.ref.entity_count,
            "owner_count": frozen.owner_count,
            "membership_hash": frozen.ref.membership_hash,
            "fixed": frozen.ref.fixed,
            "predicate": frozen.predicate,
        },
        "baseline": {
            "ead": frozen.ref.baseline_ead,
            "ecl": frozen.ref.baseline_ecl,
            "coverage_pct": str(round(coverage, 4)),
            "denominator": "EAD (ead_sar_mn), SAR million",
        },
        "inputs": inputs,
        "translated": translated,
        "artifact_versions": dict(spec.artifact_versions),
        "stage_and_horizon": {
            "stage_policy": spec.stage_policy,
            "note": ("Stages are held as recorded. A migration needs an "
                     "approved rule and a horizon conversion, neither of "
                     "which this book publishes."
                     if spec.stage_policy == "frozen" else
                     "Stage migration is selected; its rule and horizon "
                     "conversion are declared in the scenario."),
            "overlay_policy": spec.overlay_policy,
            "overlay_note": (
                "This book does not separate modelled ECL from management "
                "overlay, so the calculation operates on reported ECL. That "
                "is disclosed rather than decomposed."),
            "fx_policy": spec.fx_policy,
        },
        "overlaps": [{"field": o.field_id, "question": o.question(),
                      "options": o.options(), "rows": o.rows, "ecl": o.ecl,
                      "composition": o.composition} for o in overlaps],
        "unaffected": _unaffected(frozen),
        "bounds": dict(spec.bounds_policy),
        "warnings": _dedupe(warnings),
        "methods": [
            {"method": m, "label": _method_label(m),
             "status": (readiness or {}).get(m, "READY"),
             "submode": spec.delta_submode if m == sp.DELTA else ""}
            for m in spec.methods],
        "user_assumption": dict(spec.user_assumption),
        "source_is_not_changed": SOURCE_UNTOUCHED,
    }
    return Preview(spec=spec, body=body)


def _unaffected(frozen: ch.Frozen) -> str:
    """What this scenario does not touch. Section 13.1 wants it explicit:
    unaffected rows must show exactly zero change."""
    grain = ch.GRAIN[frozen.domain_id]
    if not frozen.predicate:
        return (f"Nothing. This scenario covers every {grain['noun']} in the "
                f"book at {frozen.period}.")
    return (f"Every {grain['noun']} outside this cohort keeps its recorded "
            f"ECL exactly. The full-book total is this cohort's scenario ECL "
            f"plus the unchanged remainder.")


def _dedupe(items: list[str]) -> list[str]:
    """Order-preserving, because a warning list a reader scans twice is one
    they stop reading."""
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def confirm(preview: Preview, reply: str) -> sp.ScenarioSpec:
    """Read the reader's answer and bind the approval, or leave it unbound.

    Deliberately narrow about what counts. Section 6.2: *"Require an
    affirmative response to the current preview. Reading sensitivities or
    saying 'use ML' before a complete preview is not confirmation of an
    unseen calculation."* So anything that is not plainly a yes leaves the
    scenario unconfirmed, and `require_confirmed()` will refuse to run it.
    """
    said = " ".join(str(reply or "").lower().split())
    affirmative = (
        said in {"yes", "y", "run it", "go ahead", "confirm", "confirmed",
                 "ok", "okay", "proceed", "do it"}
        or said.startswith("yes,")
        or said.startswith("yes ")
    )
    if not affirmative:
        return preview.spec
    # No state walking here. `build()` is what reaches PREVIEW_READY, and a
    # confirm() that quietly advanced a DRAFT would be approving a preview
    # that was never assembled -- which is the thing the gate exists to stop.
    return preview.spec.confirm()


def readiness(spec: sp.ScenarioSpec) -> dict[str, str]:
    """Which selected methods can actually run, before anything is confirmed.

    Method 2 is not built in this pass and says so rather than being quietly
    dropped from the list -- section 11.5: *"A failed model gate cannot be
    declared a completed ML capability."* The same applies to one that was
    never built.
    """
    out: dict[str, str] = {}
    for method in spec.methods:
        if method == sp.ML:
            out[method] = "MODEL_NOT_READY"
        elif method == sp.USER_DEFINED and not spec.user_assumption:
            out[method] = "NEEDS_ASSUMPTION"
        else:
            out[method] = "READY"
    return out


__all__ = ["Preview", "REQUIRED_SECTIONS", "SOURCE_UNTOUCHED", "build",
           "confirm", "readiness"]
