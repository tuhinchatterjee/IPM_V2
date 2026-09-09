"""
The context packet Opus receives. Specification section 7.4.

Sections A through J, assembled from authenticated application state and this
domain's own catalogue. Sonnet does not invent a dataset, a field, a coverage
figure or a missing rate; every number here is measured or configured.

The rule about what shrinks
---------------------------
Section 7.4's guardrail is precise about priority. When the packet is too
large, the COMPLETE compact schema and the current scope are preserved, and the
optional preview rows and non-essential history are reduced FIRST. If the
required core still does not fit, the answer is `CONTEXT_TOO_LARGE` with an
honest explanation -- never a silently halved dictionary and never a silently
raised budget.

`build` implements exactly that, as an ordered ladder of reductions, and it
reports which rungs it used. What it will not do at any rung is drop a business
field.

A measured finding, recorded rather than hidden
-----------------------------------------------
The complete compact dictionary for this domain measures about 18,700 tokens.
The specification's Standard per-call input cap is 12,000 and Deep's is 20,000.
So the mandatory catalogue does not fit Standard at all, and fits Deep only
with nothing else beside it. Section 7.4 anticipates this case in terms and
says what to do about it: "More specific user wording cannot fix an application
whose mandatory catalogue never fits. Fix that serialization/configuration as
an implementation issue."

Both halves of that were done. The serialization was fixed as far as it
honestly goes -- structural families brought it from 29,600 tokens to 18,700
with no field lost, and the remainder is 751 genuine field definitions. What
remains is a configuration question, so `required_core_tokens` is measured and
reported, the packet returns CONTEXT_TOO_LARGE when it does not fit, and
`docs/cockpit_agentic_v3/CONTEXT_SIZING.md` records the measurement and the
configuration change an administrator would need to approve. The limits are NOT
raised here to make a test pass.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from backend.cockpit_agentic import (CONTEXT_VERSION, DOMAIN, UNTRUSTED_NOTE,
                                     registry)
from backend.cockpit_agentic import fields as F
from backend.cockpit_agentic import profile as profile_mod
from backend.cockpit_agentic import sql as sql_mod
from backend.cockpit_agentic.catalog import Catalog
from backend.cockpit_agentic.contracts import (CleanedQuestion,
                                               DataCoverageProfile,
                                               NormalizedQuestion)
from backend.cockpit_agentic.ledger import Ledger
from backend.cockpit_agentic.scope import Scope

#: Characters per token for the local estimate. Deliberately conservative:
#: dense JSON tokenizes at roughly 3.5-4 characters per token for this content,
#: and 3.4 over-counts slightly rather than under-counting. Section 9.3 permits
#: a documented conservative local estimate where a counting endpoint is not
#: used, and under-counting is the failure that matters -- it would let an
#: oversized packet through.
CHARS_PER_TOKEN = 3.4


def estimate_tokens(payload: Any) -> int:
    """A conservative local token estimate.

    Not a substitute for the provider's counter, and not presented as exact.
    `build` records which method produced the number so a UAT run can compare
    the estimate with the provider's reported usage.
    """
    if isinstance(payload, str):
        text = payload
    else:
        text = json.dumps(payload, separators=(",", ":"), default=str)
    return int(len(text) / CHARS_PER_TOKEN) + 1


class ContextTooLarge(RuntimeError):
    """The required core does not fit the mode's cap. Reported, never trimmed
    into silence."""

    def __init__(self, message: str, *, required: int, cap: int,
                 breakdown: dict[str, int]) -> None:
        super().__init__(message)
        self.required = required
        self.cap = cap
        self.breakdown = breakdown


#: The reduction ladder, in the order section 7.4 mandates. Everything here is
#: OPTIONAL detail; no rung touches the dictionary or the current scope.
LADDER: tuple[tuple[str, str], ...] = (
    ("samples_10_to_5", "halve the preview rows"),
    ("history_to_3_pairs", "keep only the three default recent exchanges"),
    ("profile_to_120", "list the 120 most misleading coverage gaps"),
    ("samples_5_to_2", "reduce the preview to two rows per relation"),
    ("profile_to_60", "list the 60 most misleading coverage gaps"),
    ("drop_samples", "drop the preview rows entirely"),
    ("history_to_1_pair", "keep only the most recent exchange"),
    ("drop_history", "drop the recent exchanges, keeping the rolling summary"),
)


@dataclass
class CockpitContextPacket:
    """Sections A-J of section 7.4, and how it was assembled."""

    version: str
    request_id: str
    payload: dict[str, Any]
    estimated_tokens: int
    token_method: str
    reductions_applied: list[str] = field(default_factory=list)
    required_core_tokens: int = 0
    breakdown: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"version": self.version, "request_id": self.request_id,
                "estimated_tokens": self.estimated_tokens,
                "token_method": self.token_method,
                "reductions_applied": list(self.reductions_applied),
                "required_core_tokens": self.required_core_tokens,
                "breakdown": dict(self.breakdown),
                "payload": self.payload}

    def serialize(self) -> str:
        return json.dumps(self.payload, separators=(",", ":"), default=str)


def floor(**kwargs: Any) -> dict[str, Any]:
    """The smallest packet this domain can produce, measured.

    Runs every rung of the reduction ladder and reports what is left. Used by
    the sizing document and its test, so the recorded floor is a measurement
    rather than a number someone typed. Deliberately not implemented by passing
    an impossibly small cap: an override that only raises would ignore it, and a
    measurement that depends on a configuration quirk is not a measurement.
    """
    reduced = build(**{**kwargs, "_force_full_reduction": True})
    return {"tokens": reduced.estimated_tokens,
            "reductions_applied": list(reduced.reductions_applied),
            "breakdown": dict(reduced.breakdown)}


def build(*, request_id: str, cleaned: CleanedQuestion,
          normalized: NormalizedQuestion, scope: Scope, catalog: Catalog,
          coverage: DataCoverageProfile, ledger: Ledger,
          session: sql_mod.Session | None = None,
          ui_filters: dict[str, Any] | None = None,
          rolling_summary: dict[str, Any] | None = None,
          recent_exchanges: list[dict[str, Any]] | None = None,
          sample_relations: tuple[str, ...] = (),
          include_pivot_columns: bool = False,
          _force_full_reduction: bool = False,
          _cap_override: int = 0) -> CockpitContextPacket:
    """Assemble sections A-J, reduce optional detail if needed, or refuse."""
    limits = ledger.limits
    exchanges = list(recent_exchanges or [])
    sample_rows = limits.sample_rows_per_dataset
    profile_limit = 0
    keep_samples = True
    keep_history = True
    history_pairs = min(len(exchanges), limits.recent_pairs_hard_cap)

    def assemble() -> dict[str, Any]:
        # ---- A. the question, all three forms ------------------------
        section_a = {
            "original_question": cleaned.original_text,
            "detected_language": cleaned.detected_language,
            "english_translation": cleaned.english_text,
            "translation_uncertainties": list(cleaned.uncertainties),
            "translation_failed": cleaned.failed,
            "business_request": normalized.business_question,
            "subquestions": list(normalized.subquestions),
            "requested_measures": list(normalized.requested_measures),
            "requested_actions": list(normalized.requested_actions),
            "unresolved_ambiguity": list(normalized.unresolved_ambiguity),
            "normalization_failed": normalized.failed,
            "note": ("Every subquestion and every stated ambiguity is here. "
                     "An ambiguity is genuine: do not resolve it by guessing, "
                     "and do not drop a subquestion to make the rest "
                     "answerable."),
        }

        # ---- B. server-confirmed scope -------------------------------
        section_b = {
            "current_module": "Cockpit",
            "domain_id": DOMAIN,
            "tenant_scope": scope.to_dict(),
            "dataset_release_id": scope.dataset_release_id,
            "reporting_currency": catalog.reporting_currency,
            "amount_scale": catalog.amount_scale,
            "ui_filters": dict(ui_filters or {}),
            "explicit_scope_this_message": dict(normalized.explicit_scope),
            "inherited_scope": dict(normalized.inherited_scope),
            "effective_scope": normalized.effective_scope,
            "response_language": normalized.response_language,
            "mode": ledger.mode,
            "precedence_note": (
                "explicit_scope_this_message overrides inherited_scope. A new "
                "instruction from the user replaces an inherited filter; it "
                "does not merge with it."),
            "transmission_note": (
                "Only this domain's data may be sent to the model provider. "
                "There is no other module's data in this packet, and the "
                "functionality descriptions in section H are metadata, not a "
                "route to one."),
        }

        # ---- C. thread context ---------------------------------------
        section_c: dict[str, Any] = {
            "rolling_summary": dict(rolling_summary or {}),
            "recent_exchanges": (exchanges[-history_pairs:]
                                 if keep_history and history_pairs else []),
            "default_pairs": limits.recent_pairs_default,
            "hard_cap_pairs": limits.recent_pairs_hard_cap,
            "note": ("A recent exchange is one complete question and its final "
                     "answer, referral or clarification -- not one message. "
                     "Only authorized Cockpit evidence appears here; a result "
                     "produced by another module or an earlier, broader "
                     "Cockpit does not become authorized by appearing in an "
                     "old answer."),
        }

        # ---- D and E. the complete dictionary, grains and calendar ----
        section_de = catalog.compact(
            include_pivot_columns=include_pivot_columns)

        # ---- F. measured coverage ------------------------------------
        section_f = profile_mod.compact(coverage, limit=profile_limit)

        # ---- G. bounded, reproducible samples ------------------------
        section_g: dict[str, Any] = {"samples": [], "note": (
            "Samples illustrate the SHAPE of a relation. They do not establish "
            "a total, a distribution or a missing rate -- section F does that, "
            "measured over every row.")}
        if keep_samples and session is not None and sample_rows > 0:
            preview = ["facility_id", "borrower_id", "reporting_quarter",
                       "ifrs9_stage", "pd_pit_12m", "pd_ttc_12m",
                       "ead_reported", "ecl_reported"]
            for relation in (sample_relations or (F.FACILITY_QUARTER,)):
                try:
                    columns = (preview if relation == F.FACILITY_QUARTER
                               else None)
                    section_g["samples"].append(sql_mod.sample_rows(
                        relation, session, limit=sample_rows,
                        columns=columns))
                except Exception:                          # noqa: BLE001
                    continue
            if any(s["relation"] == F.FACILITY_QUARTER
                   for s in section_g["samples"]):
                section_g["preview_note"] = (
                    "The facility preview shows a named subset of key columns "
                    "for readability. The COMPLETE field dictionary is in "
                    "section D; do not treat these eight columns as the "
                    "available fields.")

        # ---- H. the functionality registry ---------------------------
        section_h = registry.compact()

        # ---- I. what can actually be executed ------------------------
        section_i = {
            "sql": {
                "dialect": "DuckDB 1.5 SQL",
                "available": session is not None,
                "readable_relations": sorted(scope.relations),
                "statement_rule": (
                    "Exactly one SELECT per step. No writes, no schema "
                    "changes, no configuration changes, no COPY, no ATTACH, "
                    "no INSTALL, and no file or network functions -- there is "
                    "no filesystem or network from this session."),
                "tenant_rule": (
                    "tenant_id, dataset_release_id and domain_id are already "
                    "filtered in every relation. You do not need to write "
                    "those predicates and writing them cannot widen what you "
                    "see."),
                "permitted": (
                    "Aggregates, window functions, CTEs, date arithmetic, "
                    "joins and the supported statistical functions."),
                "max_model_rows": sql_mod.MAX_MODEL_ROWS,
                "wall_seconds_per_step": limits.step_wall_seconds,
            },
            "python": {
                "available": False,
                "reason": ("Isolated Python execution is not enabled in this "
                           "runtime. It is reported as unavailable rather than "
                           "downgraded to unsafe in-process execution."),
            },
            "charts": {
                "max": limits.max_charts,
                "kinds": ["bar", "line", "waterfall", "scatter"],
                "note": ("A chart is a declarative specification bound to "
                         "result fact ids. HTML and JavaScript are never "
                         "executed."),
            },
        }

        # ---- J. the budget ledger ------------------------------------
        section_j = ledger.budget_view()

        return {
            "context_version": CONTEXT_VERSION,
            "request_id": request_id,
            "A_request": section_a,
            "B_scope": section_b,
            "C_thread": section_c,
            "D_E_catalogue": section_de,
            "F_coverage": section_f,
            "G_samples": section_g,
            "H_functionalities": section_h,
            "I_execution": section_i,
            "J_budget": section_j,
            "untrusted_data_note": UNTRUSTED_NOTE,
        }

    def measure(payload: dict[str, Any]) -> dict[str, int]:
        return {key: estimate_tokens(value) for key, value in payload.items()}

    # `_cap_override` exists so a test can simulate a deployment whose cap is
    # below this domain's floor. It is a test seam and nothing reads it in
    # production: the real cap comes from the ledger's limits.
    cap = (0 if _force_full_reduction
           else (_cap_override or limits.max_input_tokens_per_call))
    payload = assemble()
    applied: list[str] = []

    # The required core: everything the guardrail forbids reducing.
    core_keys = ("A_request", "B_scope", "D_E_catalogue", "H_functionalities",
                 "I_execution", "J_budget")
    core = estimate_tokens({k: payload[k] for k in core_keys})
    breakdown = measure(payload)

    total = estimate_tokens(payload)
    for name, _why in LADDER:
        if total <= cap:
            break
        if name == "samples_10_to_5":
            sample_rows = 5
        elif name == "history_to_3_pairs":
            history_pairs = min(history_pairs, limits.recent_pairs_default)
        elif name == "profile_to_120":
            profile_limit = 120
        elif name == "samples_5_to_2":
            sample_rows = 2
        elif name == "profile_to_60":
            profile_limit = 60
        elif name == "drop_samples":
            keep_samples = False
        elif name == "history_to_1_pair":
            history_pairs = 1
        elif name == "drop_history":
            keep_history = False
        applied.append(name)
        payload = assemble()
        total = estimate_tokens(payload)

    breakdown = measure(payload)
    if _force_full_reduction:
        # A floor measurement, not a request. Every rung has been spent; there
        # is nothing to refuse.
        return CockpitContextPacket(
            version=CONTEXT_VERSION, request_id=request_id, payload=payload,
            estimated_tokens=total, token_method="local floor measurement",
            reductions_applied=applied, required_core_tokens=core,
            breakdown=breakdown)
    if total > cap:
        raise ContextTooLarge(
            f"The Cockpit's required context is about {total} tokens against a "
            f"{cap}-token per-call limit in {ledger.mode} mode. The complete "
            f"field dictionary alone is about "
            f"{breakdown.get('D_E_catalogue', 0)} tokens and it is not "
            f"abridged: sending half a schema would produce a confident answer "
            f"over fields that were silently hidden. Every optional reduction "
            f"has already been applied "
            f"({', '.join(applied) or 'none were available'}). This is a "
            f"configuration limit, not something a differently worded question "
            f"can fix -- see docs/cockpit_agentic_v3/CONTEXT_SIZING.md.",
            required=total, cap=cap, breakdown=breakdown)

    return CockpitContextPacket(
        version=CONTEXT_VERSION, request_id=request_id, payload=payload,
        estimated_tokens=total,
        token_method=f"local conservative estimate at {CHARS_PER_TOKEN} "
                     f"characters per token",
        reductions_applied=applied, required_core_tokens=core,
        breakdown=breakdown)


__all__ = ["CHARS_PER_TOKEN", "CockpitContextPacket", "ContextTooLarge",
           "LADDER", "build", "estimate_tokens"]
