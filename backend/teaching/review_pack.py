"""
The human-review pack. §17, §18.

    §18: "Prepare a prioritized review pack for human review."
    §18: "Do not mark it approved."

Why a pack rather than a queue
--------------------------------
There are 2,453 teaching cases and none of them is approved. A reviewer told
"here are 2,453 cases" reviews none of them. The pack exists to answer a
different question: *which forty cases, reviewed first, would let production
retrieval be switched on for the highest-value question families with the
least risk?*

So selection is by RISK CLASS rather than by score. §18 names the classes —
every critical failure class, Cockpit and Project agentic flows, officer and
agent selection, proactive review, Risk Cases, workflow and approval,
unsupported questions, ambiguity, cross-domain joins, period logic, business
invariants, prompt injection and tool abuse, permission and tenant safety —
and each is represented, because a pack that is forty variations of one
family teaches a reviewer about one family.

What this module will not do
------------------------------
Approve anything. It selects, it orders, it explains why each case is in the
pack, and it labels the whole thing REVIEW REQUIRED. `may_approve` still
needs a named human, and nothing here calls it.

Its output is deliberately boring: an ordered list with a reason per row.
A reviewer's time is the scarce resource, and the only thing that respects it
is telling them what to look at first and why.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.teaching import status as st

PACK_VERSION = "1.0.0"

#: The label the pack carries, everywhere it is shown or exported. §18.
LABEL = "REVIEW REQUIRED"

#: §18's risk classes, in the order a reviewer should meet them. Ordered by
#: what a wrong answer would cost: a permission leak is unrecoverable, a
#: mis-selected specialist is expensive, an awkward follow-up suggestion is
#: neither.
CLASSES: tuple[tuple[str, str, str], ...] = (
    ("permission_tenant_safety", "Permission and tenant safety",
     "A wrong answer here shows one client another client's book. Nothing "
     "else in the list is unrecoverable in the same way."),
    ("prompt_injection", "Prompt injection and tool abuse",
     "Whether an instruction inside a question or a dataset can reach a "
     "privileged path."),
    ("business_invariants", "Business invariants",
     "Whether a figure that does not reconcile can reach a reader."),
    ("critical_failure", "Critical failure classes",
     "Wrong period, wrong population, wrong exposure definition, wrong "
     "join, duplicate amplification — the Tier 1 list."),
    ("cross_domain_join", "Cross-domain joins",
     "Two governed domains joined: the place row counts silently amplify."),
    ("period_logic", "Period logic",
     "Two-period comparisons, latest-published resolution, and the "
     "off-by-one-quarter answers nobody notices."),
    ("agentic_cockpit", "Cockpit agentic flows",
     "Whether a coordinated review in the Cockpit does real specialist "
     "work."),
    ("agentic_project", "Project agentic flows",
     "The same, inside a Project, where scope isolation also applies."),
    ("officer_selection", "Officer selection",
     "Whether the level matches the work rather than the wording."),
    ("agent_selection", "Agent selection",
     "The smallest specialist set that can safely answer."),
    ("proactive_review", "Proactive review",
     "Event-driven runs: idempotency, deduplication and severity."),
    ("risk_cases", "Risk Cases",
     "Whether a created case carries validated evidence."),
    ("workflow_approval", "Workflow and approval",
     "That an agent drafts and a person decides."),
    ("unsupported", "Unsupported questions",
     "Saying the data is not held, rather than answering something else."),
    ("ambiguity", "Ambiguity",
     "Asking rather than guessing, and asking something the user can "
     "actually answer."),
)

CLASS_IDS: tuple[str, ...] = tuple(c for c, _, _ in CLASSES)
CLASS_LABELS: dict[str, str] = {c: label for c, label, _ in CLASSES}
CLASS_WHY: dict[str, str] = {c: why for c, _, why in CLASSES}

#: How many cases per class the pack asks for by default. Small on purpose:
#: fifteen classes at four cases each is sixty cases, which is a morning's
#: work and a real decision at the end of it. A pack nobody finishes
#: approves nothing.
PER_CLASS = 4


def classify(case: Any) -> str:
    """Which risk class a case belongs to, from its recorded fields.

    Deterministic, and from the family and the tags rather than from the
    question text. A classifier reading the prose would put "show me
    exposure" and "show me exposure for another client" in the same class.
    """
    family = str(getattr(case, "family_id", "") or "").upper()
    tags = {str(t).lower() for t in (getattr(case, "tags", None) or ())}
    checks = {str(c).lower() for c in
              (getattr(case, "expected_failure_categories", None) or ())}

    for tag, name in (
        ("permission", "permission_tenant_safety"),
        ("tenant", "permission_tenant_safety"),
        ("injection", "prompt_injection"),
        ("tool_abuse", "prompt_injection"),
        ("invariant", "business_invariants"),
        ("proactive", "proactive_review"),
        ("risk_case", "risk_cases"),
        ("workflow", "workflow_approval"),
        ("approval", "workflow_approval"),
        ("officer", "officer_selection"),
        ("agent", "agent_selection"),
        ("project", "agentic_project"),
        ("agentic", "agentic_cockpit"),
    ):
        if tag in tags or any(tag in c for c in checks):
            return name

    if "AMBIG" in family or "CLARIF" in family:
        return "ambiguity"
    if "UNSUPPORTED" in family or "ABSTAIN" in family:
        return "unsupported"
    if "MULTI_DOMAIN" in family or "JOIN" in family or "CROSS" in family:
        return "cross_domain_join"
    if "PERIOD" in family or "TREND" in family or "CHANGE" in family:
        return "period_logic"
    if "INVARIANT" in family or "RECONCIL" in family:
        return "business_invariants"
    return "critical_failure"


@dataclass
class Row:
    """One case in the pack, with why a reviewer is being shown it."""

    case_id: str = ""
    title: str = ""
    question: str = ""
    family_id: str = ""
    risk_class: str = ""
    status: str = ""
    authoring_method: str = ""
    provenance: str = ""
    #: Why this one, in a sentence a reviewer can disagree with.
    why: str = ""
    #: What a reviewer has to decide. §17's list, per row.
    decide: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id, "title": self.title,
            "question": self.question, "family_id": self.family_id,
            "risk_class": self.risk_class,
            "risk_class_label": CLASS_LABELS.get(self.risk_class,
                                                 self.risk_class),
            "status": self.status,
            "status_means": st.STATUS_MEANS.get(self.status, ""),
            "authoring_method": self.authoring_method,
            "provenance": self.provenance,
            "why": self.why,
            "decide": list(self.decide),
            # Said on every row, not just in the header. A row copied out of
            # the pack into a spreadsheet must carry its own label.
            "approved": False,
            "label": LABEL,
        }


#: §17's decisions, offered on every row.
ACTIONS: tuple[str, ...] = ("APPROVE", "REJECT", "REQUEST_CHANGE",
                            "EDIT_SPECIFICATION", "MARK_RETIRED")

#: What a reviewer must be shown before they can decide. §17's list.
SHOWS: tuple[str, ...] = (
    "question and thread", "expected officer level", "expected agents",
    "actual agents", "task DAG", "selected tools", "selected datasets",
    "expected plan properties", "actual plan", "expected safe outcome",
    "actual outcome", "independent reference result where available",
    "assurance", "failures and deductions", "source and generator",
    "data version", "reviewer", "approval state", "version history",
)


def _why(case: Any, risk_class: str) -> str:
    method = str(getattr(case, "authoring_method", "") or "")
    generated = method in st.GENERATED
    return (f"{CLASS_WHY.get(risk_class, 'A risk class worth reviewing.')} "
            + ("This case was generated rather than written, so nobody has "
               "yet read the words a model or a blueprint produced."
               if generated else
               "This case has no approval record."))


def build(cases: list[Any], *, per_class: int = PER_CLASS) -> dict[str, Any]:
    """Select and order the pack. Approves nothing.

    Only cases that are NOT already approved are eligible: a pack that
    included approved cases would waste the scarce thing it exists to
    respect.
    """
    eligible = [c for c in cases
                if str(getattr(c, "review_status", "") or "").upper()
                not in (st.APPROVED, st.REJECTED, st.RETIRED)]

    grouped: dict[str, list[Any]] = {name: [] for name in CLASS_IDS}
    for case in eligible:
        grouped.setdefault(classify(case), []).append(case)

    rows: list[Row] = []
    for name in CLASS_IDS:
        for case in grouped.get(name, [])[:per_class]:
            rows.append(Row(
                case_id=str(getattr(case, "case_id", "") or ""),
                title=str(getattr(case, "title", "") or ""),
                question=str(getattr(case, "question", "") or ""),
                family_id=str(getattr(case, "family_id", "") or ""),
                risk_class=name,
                status=str(getattr(case, "review_status", "") or ""),
                authoring_method=str(getattr(case, "authoring_method", "")
                                     or ""),
                provenance=str(getattr(case, "provenance", "") or ""),
                why=_why(case, name),
                decide=list(ACTIONS)))

    covered = [n for n in CLASS_IDS if grouped.get(n)]
    return {
        "version": PACK_VERSION,
        "label": LABEL,
        "approved": False,
        "note": ("This pack is a selection for review. Nothing in it is "
                 "approved, and building it approves nothing: an approval "
                 "needs a named human reviewer and is refused without one."),
        "eligible_cases": len(eligible),
        "total_cases": len(cases),
        "rows": [r.to_dict() for r in rows],
        "selected": len(rows),
        "per_class": per_class,
        "classes": [{"id": c, "label": label, "why": why,
                     "available": len(grouped.get(c, [])),
                     "selected": min(len(grouped.get(c, [])), per_class)}
                    for c, label, why in CLASSES],
        "classes_covered": len(covered),
        "classes_empty": [n for n in CLASS_IDS if not grouped.get(n)],
        "reviewer_sees": list(SHOWS),
        "actions": list(ACTIONS),
        "production_retrieval": {
            "default": st.APPROVED,
            "also_allowed_under_policy": st.SYSTEM_VALIDATED,
            "never": sorted(set(st.STATUSES) - set(st.RETRIEVABLE)),
            "note": ("Approving a case in this pack is what makes it "
                     "retrievable. Until then production retrieves nothing "
                     "from it."),
        },
    }
