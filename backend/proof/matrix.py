"""
The Feature Proof Matrix. §35.

    §35: "For each feature record: implementation location; test; browser
          acceptance; status; limitation."

Why a matrix rather than a checklist
--------------------------------------
A checklist says what was built. This says what is PROVEN, and by what — and
the two differ in exactly the places that matter. A feature with an
implementation and no test is not proven. A feature with a unit test and no
browser acceptance is proven in the backend and unproven on screen, which for
a Trace view or a set of downloads is most of the risk.

So every row carries four independent facts: where it lives, which test
covers it, whether a browser has actually seen it, and what is still limited
about it. A row missing any of the first three is not a pass — it is a row
with a gap, and the matrix reports it as one.

Honesty rules
--------------
`browser` is `RUN` only where `scripts/browser_acceptance.py` genuinely drove
a Chromium over the screen. Everything else is `NOT_RUN`, whatever the
feature's unit tests say. §36 is explicit: if browser acceptance cannot run,
it is not marked passed — and a matrix that quietly upgraded `NOT_RUN` to
`PASS` because the code looked fine would be the same lie in a table.

`limitation` is not optional prose. Where a feature has a known gap it is
named, with the defect id, so the matrix and the defect register cannot
disagree.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

MATRIX_VERSION = "1.0.0"

# ---------------------------------------------------------------- statuses

PROVEN = "PROVEN"
#: Implemented and tested, and no browser has seen it. Correct for anything
#: with no screen; a gap for anything with one.
BACKEND_ONLY = "BACKEND_ONLY"
#: Implemented, and the test that covers it does not prove the behaviour the
#: feature is for.
THIN = "THIN"
#: A named limitation stands against it.
LIMITED = "LIMITED"
#: Deliberately not covered in this phase.
DEFERRED = "DEFERRED"

STATUSES: tuple[str, ...] = (PROVEN, BACKEND_ONLY, THIN, LIMITED, DEFERRED)

RUN = "RUN"
NOT_RUN = "NOT_RUN"
NOT_APPLICABLE = "NOT_APPLICABLE"


@dataclass(frozen=True)
class Feature:
    """One delivered capability, and what actually proves it."""

    area: str
    name: str
    location: str
    test: str = ""
    browser: str = NOT_RUN
    status: str = BACKEND_ONLY
    limitation: str = ""

    @property
    def has_test(self) -> bool:
        return bool(self.test.strip())

    @property
    def gap(self) -> str:
        """What is missing, in a sentence, or empty."""
        if not self.has_test:
            return "no test names this feature"
        if self.browser == NOT_RUN and self.status == PROVEN:
            return "claimed PROVEN with no browser acceptance"
        return ""

    def to_dict(self) -> dict[str, Any]:
        return {"area": self.area, "name": self.name,
                "location": self.location, "test": self.test,
                "browser": self.browser, "status": self.status,
                "limitation": self.limitation, "gap": self.gap}


def _f(area: str, name: str, location: str, test: str = "",
       browser: str = NOT_RUN, status: str = BACKEND_ONLY,
       limitation: str = "") -> Feature:
    return Feature(area=area, name=name, location=location, test=test,
                   browser=browser, status=status, limitation=limitation)


FEATURES: tuple[Feature, ...] = (
    # ------------------------------------------------------------ Cockpit
    _f("Cockpit", "greeting and composer",
       "frontend/src/app/page.tsx", "frontend node tests", RUN, PROVEN),
    _f("Cockpit", "officer working indicator",
       "backend/agentic/officers.py, frontend/src/components/agentic/",
       "tests/agentic/test_officers.py, tests/proof/test_agentic_proof.py",
       RUN, PROVEN),
    _f("Cockpit", "suggested questions",
       "backend/orchestration/suggestions.py", "tests/orchestration/",
       RUN, BACKEND_ONLY,
       "follow_up_quality is wired but only asserts scope, not usefulness"),
    _f("Cockpit", "Requires Attention",
       "backend/agentic/attention.py", "tests/agentic/test_cases.py",
       RUN, BACKEND_ONLY),
    _f("Cockpit", "recent work and notifications",
       "backend/agentic/notifications.py", "tests/agentic/", RUN,
       BACKEND_ONLY),

    # ------------------------------------------------------ Conversations
    _f("Conversations", "global Investigation",
       "backend/orchestration/executor.py",
       "tests/evals/test_mandatory_end_to_end.py, tests/proof/", RUN,
       PROVEN),
    _f("Conversations", "Project Investigation",
       "backend/agentic/interactive.py, backend/api/routers/hierarchy.py",
       "tests/proof/test_agentic_proof.py", RUN, PROVEN),
    _f("Conversations", "multi-turn memory and referents",
       "backend/orchestration/memory.py, conversation.py",
       "tests/orchestration/", RUN, PROVEN),
    _f("Conversations", "previous-result reuse",
       "backend/orchestration/reuse.py", "tests/orchestration/", RUN,
       BACKEND_ONLY),
    _f("Conversations", "clarification and unsupported",
       "backend/orchestration/executor.py",
       "tests/proof/test_safety.py, tests/evals/", RUN, PROVEN),

    # ----------------------------------------------------------- Projects
    _f("Projects", "create, open, Project-only threads",
       "backend/api/routers/hierarchy.py", "tests/api/", RUN, PROVEN),
    _f("Projects", "publish globally",
       "backend/api/routers/hierarchy.py", "tests/api/", RUN, BACKEND_ONLY),
    _f("Projects", "Project Plan / operating plan",
       "not implemented", "", NOT_RUN, DEFERRED,
       "§8's governed Project Plan is not built. Recorded as not delivered "
       "rather than approximated by the existing Project fields."),

    # ---------------------------------------------------------- Analyses
    _f("Analyses", "dynamic run and saved Analysis",
       "backend/orchestration/, backend/api/routers/hierarchy.py",
       "tests/orchestration/", RUN, PROVEN),
    _f("Analyses", "certified method distinction",
       "backend/studio/", "tests/studio/", RUN, BACKEND_ONLY),
    _f("Analyses", "charts, tables, 3D renderers",
       "frontend/src/components/analytics/",
       "frontend/src/components/analytics/__tests__/", RUN, PROVEN),
    _f("Analyses", "Results Workbook and Calculation Pack",
       "backend/exports/", "tests/exports/", NOT_RUN, BACKEND_ONLY,
       "The download buttons were not exercised by a browser: the sandbox "
       "cannot accept a file download."),

    # ------------------------------------------------------------- Trace
    _f("Trace", "Story, Lineage, Landscape, Audit",
       "frontend/src/components/trace/",
       "frontend/src/components/trace/__tests__/", RUN, PROVEN),
    _f("Trace", "assurance summary node",
       "backend/orchestration/executor.py, backend/assurance/collect.py",
       "tests/proof/test_agentic_proof.py", RUN, PROVEN),
    _f("Trace", "version comparison",
       "backend/orchestration/modification.py", "tests/orchestration/", RUN,
       BACKEND_ONLY),
    # D19, closed. It was LIMITED here for the whole of the previous phase:
    # a coordinated review threw away every sub-analysis it ran except the
    # headline sentence, so its Trace could not say which data it touched.
    # The Investigation now accumulates a composition record, the probe reads
    # it, and the baseline shows a portfolio review reading four datasets
    # against a single query's one.
    _f("Trace", "coordinated-run lineage",
       "backend/orchestration/investigation.py, backend/agentic/interactive.py",
       "tests/proof/test_agentic_proof.py, tests/proof/test_defect_closure.py",
       RUN, PROVEN),

    # ------------------------------------------------------ Data Builder
    _f("Data Builder", "domains, datasets, periods, fields",
       "backend/api/routers/data_builder.py", "tests/api/", RUN, PROVEN),
    _f("Data Builder", "relationship map and drift",
       "backend/data_access/", "tests/data_access/", RUN, BACKEND_ONLY),

    # --------------------------------------------------- Analysis Studio
    _f("Analysis Studio", "method library and builder",
       "backend/studio/", "tests/studio/", RUN, BACKEND_ONLY),
    _f("Analysis Studio", "AI Intelligence Studio, 15 tabs",
       "backend/ai_studio/, frontend/src/app/ai-studio/",
       "tests/studio/test_ai_intelligence_studio.py", RUN, PROVEN),
    _f("Analysis Studio", "Investigation Reviews tab",
       "backend/assurance/reviews.py, frontend/src/components/ai-studio/",
       "tests/assurance/, tests/proof/", RUN, PROVEN),

    # ------------------------------------------- Workflow, collaboration
    _f("Workflow", "send, review, approve, request changes",
       "backend/api/routers/workspace.py", "tests/api/", RUN, BACKEND_ONLY),
    _f("Workflow", "human approval gates",
       "backend/agentic/approvals.py",
       "tests/agentic/test_approvals.py, tests/proof/test_safety.py",
       NOT_RUN, BACKEND_ONLY),
    _f("Workflow", "permissions and roles",
       "backend/api/permissions.py, backend/assurance/access.py",
       "tests/assurance/, tests/proof/test_safety.py", RUN, PROVEN),

    # ------------------------------------------------ Risk Cases, agents
    _f("Agents", "officer selection",
       "backend/agentic/officers.py",
       "tests/agentic/test_officers.py, tests/proof/test_agentic_proof.py",
       RUN, PROVEN),
    _f("Agents", "task DAG and orchestration",
       "backend/agentic/orchestrator.py, dag.py",
       "tests/agentic/test_orchestration.py, tests/proof/", RUN, PROVEN),
    _f("Agents", "worker, queue, schedules",
       "backend/agentic/queue.py, worker.py",
       "tests/agentic/test_queue.py", NOT_RUN, BACKEND_ONLY,
       "worker_scheduler_health and worker_queue_execution are NOT_AVAILABLE "
       "in the assurance record: no signal is wired."),
    _f("Agents", "proactive review and Risk Cases",
       "backend/agentic/review.py, cases.py",
       "tests/agentic/test_review.py, test_cases.py", RUN, LIMITED,
       "proactive_review, attention_case_creation and case_deduplication "
       "are NOT_AVAILABLE in the assurance record."),

    # ----------------------------------------------------------- Exports
    _f("Exports", "workbook structure and reconciliation",
       "backend/exports/", "tests/exports/", NOT_APPLICABLE, PROVEN),
    _f("Exports", "INVESTIGATION ASSURANCE sheet",
       "backend/exports/calculation.py", "tests/exports/",
       NOT_APPLICABLE, PROVEN),

    # ----------------------------------------------- Live verification
    _f("Live verification", "DryRun, Quick, Critical modes",
       "backend/validation/live_verify.py, scripts/verify-live-ai.ps1",
       "tests/validation/test_live_verify.py", NOT_APPLICABLE, BACKEND_ONLY,
       "By design not run here: it spends credits. §0 forbids live calls in "
       "Claude Code."),

    # ---------------------------------------------------------------- UI
    _f("UI", "themes and typography",
       "frontend/src/app/globals.css", "frontend node tests", RUN, PROVEN),
    _f("UI", "no horizontal overflow at three viewports",
       "frontend/src/", "scripts/browser_acceptance.py", RUN, PROVEN),
    _f("UI", "reduced motion",
       "frontend/src/", "scripts/browser_acceptance.py", RUN, PROVEN),
    _f("UI", "back paths and return context",
       "frontend/src/lib/return-to.ts",
       "frontend/src/lib/__tests__/return-context.test.ts", RUN, PROVEN),
    _f("UI", "Arabic and RTL",
       "not implemented", "", NOT_RUN, DEFERRED,
       "localization_rtl_readiness is NOT_AVAILABLE. Out of scope for this "
       "phase and reported rather than claimed."),

    # ------------------------------------------------------- Assurance
    _f("Assurance", "six dimensions and 95 subcomponents",
       "backend/assurance/dimensions.py", "tests/assurance/test_part_f.py",
       RUN, PROVEN),
    _f("Assurance", "Assurance Record per answer",
       "backend/assurance/collect.py, record.py, store.py",
       "tests/assurance/, tests/proof/test_agentic_proof.py", RUN, PROVEN),
    _f("Assurance", "signal readers (72 of 95 wired)",
       "backend/assurance/signals.py",
       "tests/proof/test_coverage_map.py", NOT_APPLICABLE, LIMITED,
       "23 subcomponents report NOT_AVAILABLE: the judgment engines, parts "
       "of the agentic layer, and five out-of-band UI checks."),
    _f("Assurance", "score honesty (§212's seven rules)",
       "backend/assurance/honesty.py",
       "tests/assurance/test_reviews_and_honesty.py", RUN, PROVEN),

    # --------------------------------------------- Grain (final phase §4)
    _f("Grain", "output grain inferred from the objective",
       "backend/orchestration/grain.py",
       "tests/orchestration/test_grain.py", NOT_APPLICABLE, PROVEN),
    _f("Grain", "grain postconditions block a wrong-grain answer",
       "backend/orchestration/invariants.py",
       "tests/orchestration/test_grain.py", NOT_APPLICABLE, PROVEN),
    _f("Grain", "grain in Scope and on the Trace",
       "backend/orchestration/scope.py, backend/runtime/executor.py",
       "tests/orchestration/test_grain.py", NOT_RUN, BACKEND_ONLY,
       "The Trace plan node carries the contract; no browser check reads it "
       "off the screen."),

    # ------------------------------------ Regulatory knowledge (Part G-A)
    _f("Regulatory", "bulk circular upload and immutable originals",
       "backend/regulatory/store.py, backend/api/routers/regulatory.py",
       "tests/regulatory/test_part_g.py", NOT_RUN, BACKEND_ONLY,
       "The upload route and the store are tested; no browser check drives "
       "the upload form, because the form is not built."),
    _f("Regulatory", "PDF, DOCX, XLSX, CSV, TXT and HTML extraction",
       "backend/regulatory/extract.py",
       "tests/regulatory/test_part_g.py", NOT_APPLICABLE, PROVEN),
    _f("Regulatory", "OCR fallback",
       "backend/regulatory/extract.py", "tests/regulatory/test_part_g.py",
       NOT_APPLICABLE, LIMITED,
       "No OCR engine is installed on this deployment. A scanned page is "
       "reported NEEDS_OCR rather than read, and `availability()` says so "
       "before anybody uploads."),
    _f("Regulatory", "obligations, definitions, thresholds and exceptions",
       "backend/regulatory/extract.py", "tests/regulatory/test_part_g.py",
       NOT_APPLICABLE, PROVEN),
    _f("Regulatory", "supersession, conflict and as-of retrieval",
       "backend/regulatory/knowledge.py",
       "tests/regulatory/test_part_g.py", NOT_APPLICABLE, PROVEN),
    _f("Regulatory", "SME review and Regulatory Knowledge Releases",
       "backend/regulatory/release.py, backend/services/regulatory.py",
       "tests/regulatory/test_part_g.py", NOT_RUN, BACKEND_ONLY,
       "No review workbench screen. The API and the governance are tested "
       "end to end."),
    _f("Regulatory", "Regulatory Assurance (five critical gates)",
       "backend/regulatory/assurance.py",
       "tests/regulatory/test_part_g.py", NOT_APPLICABLE, PROVEN),

    # ------------------------------------- Teaching corpus (Part G-B)
    _f("Teaching corpus", "500+ Q&A template and import",
       "backend/teaching/importer.py",
       "tests/regulatory/test_part_g.py", NOT_RUN, BACKEND_ONLY,
       "A 600-row workbook imports in a test; no browser check drives the "
       "upload form, because the form is not built."),
    _f("Teaching corpus", "duplicate and conflict review",
       "backend/teaching/importer.py",
       "tests/regulatory/test_part_g.py", NOT_APPLICABLE, PROVEN),
    _f("Teaching corpus", "imported cases arrive awaiting review",
       "backend/teaching/importer.py",
       "tests/regulatory/test_part_g.py", NOT_APPLICABLE, PROVEN),

    # ------------------------------------- Feedback and learning (§7-§39)
    _f("Feedback", "the accuracy-and-usefulness prompt",
       "backend/learning/feedback.py, "
       "frontend/src/components/feedback/accuracy-prompt.tsx",
       "tests/learning/, frontend present.test.ts", RUN, PROVEN),
    _f("Feedback", "23 issue categories and structured correction",
       "backend/learning/feedback.py", "tests/learning/", NOT_RUN,
       BACKEND_ONLY,
       "The panel renders from the backend's list; no browser check opens "
       "it, because opening it needs a completed answer in a live thread."),
    _f("Feedback", "immutable Feedback Events with 24 links",
       "backend/learning/feedback.py, backend/services/learning.py",
       "tests/learning/", NOT_APPLICABLE, PROVEN),
    _f("Feedback", "raw feedback cannot change production (§11)",
       "backend/learning/guard.py", "tests/learning/", NOT_APPLICABLE,
       PROVEN),
    _f("Feedback", "Learning Observation for every question",
       "backend/learning/observation.py, backend/agentic/interactive.py",
       "tests/learning/", NOT_APPLICABLE, PROVEN),
    _f("Feedback", "presentation preferences (channel A)",
       "backend/learning/preference.py", "tests/learning/", NOT_RUN,
       BACKEND_ONLY,
       "The closed set and its refusals are tested; no settings screen "
       "renders them yet."),
    _f("Learning", "candidate cases and the nine statuses",
       "backend/learning/candidate.py", "tests/learning/",
       NOT_APPLICABLE, PROVEN),
    _f("Learning", "review workbench (ten actions)",
       "backend/services/learning.py, "
       "frontend/src/app/ai-studio/feedback-learning/page.tsx",
       "tests/learning/", RUN, LIMITED,
       "The area renders the queues and the guard. Acting on a candidate is "
       "an API call with no form behind it yet."),
    _f("Learning", "Replay Lab",
       "backend/learning/replay.py", "tests/learning/", RUN, BACKEND_ONLY,
       "Comparison, verdicts and blocking are tested. The screen lists runs "
       "and does not yet drive one."),
    _f("Learning", "Learning Releases and rollback",
       "backend/learning/release.py", "tests/learning/", RUN, BACKEND_ONLY,
       "Five gates, activation and rollback are tested through the service."),
    _f("Learning", "local auxiliary models",
       "backend/learning/models.py", "tests/learning/", RUN, BACKEND_ONLY,
       "Nine tasks, the forbidden set, artifact scanning and the activation "
       "refusals are tested. No model has been trained: there is no "
       "approved corpus to train one on."),
    _f("Learning", "satisfaction and learning metrics",
       "backend/services/learning.py", "tests/learning/", RUN, PROVEN),
    _f("Learning", "Shadow Mode",
       "not implemented", "", NOT_RUN, DEFERRED,
       "§38 asks for it optionally and off by default. It is not built, and "
       "reporting it as off would be reporting a switch that does not "
       "exist."),
)


def summary() -> dict[str, Any]:
    """The matrix, counted, with its own gaps reported."""
    by_area: dict[str, list[Feature]] = {}
    for feature in FEATURES:
        by_area.setdefault(feature.area, []).append(feature)

    gaps = [f for f in FEATURES if f.gap]
    return {
        "version": MATRIX_VERSION,
        "features": len(FEATURES),
        "areas": len(by_area),
        "by_status": {status: len([f for f in FEATURES
                                   if f.status == status])
                      for status in STATUSES},
        "browser_run": len([f for f in FEATURES if f.browser == RUN]),
        "browser_not_run": len([f for f in FEATURES
                                if f.browser == NOT_RUN]),
        "untested": [f.name for f in FEATURES if not f.has_test],
        "limitations": [{"feature": f.name, "limitation": f.limitation}
                        for f in FEATURES if f.limitation],
        "gaps": [{"feature": f.name, "gap": f.gap} for f in gaps],
        "rows": [f.to_dict() for f in FEATURES],
        "by_area": {area: [f.to_dict() for f in found]
                    for area, found in sorted(by_area.items())},
    }
