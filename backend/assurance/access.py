"""
Who may read an Assurance Review. §207.

The rule in one line
--------------------
    §207: "Users may inspect Assurance Reviews only for Investigations they
           can access."

An Assurance Review is not a separate object with its own sharing model. It
is a description of an Investigation, and it carries the question that was
asked, the scope that was analysed, the datasets that were touched and the
figures that came back. Anyone who can read the review can read most of the
Investigation. So the review inherits the Investigation's access rather than
being governed alongside it — two permission models over the same content
diverge, and the one that diverges upward is a leak.

Four levels, and what each one gets
-------------------------------------
§207's four are implemented as a widening sequence, and the widening is in
what you see rather than only in which records you see:

    OWN         your own Investigations, and ones shared with you.
    PROJECT     everything in a Project you are a member of.
    WORKFLOW    objects linked to a review or approval assigned to you.
    BROAD       an administrator or AI Intelligence reviewer, across the
                tenant they belong to.

Below BROAD the review is a SUMMARY: statuses, dimensions, coverage, why
points were lost. The full drill-down — the prompts, the retrieved teaching
cases, the served model names, the raw check evidence — is a look inside the
machine rather than at the answer, and §207's "ordinary user: own/shared
Investigation summary" is what that distinction is for.

Fail-closed, and the tenant is not negotiable
-----------------------------------------------
Every unknown resolves to REFUSED: an unrecognised role, an absent viewer id,
a record with no owner recorded, a grant that names nothing. And a tenant
mismatch is checked FIRST and refuses regardless of role, because "do not
leak cross-tenant" is not a permission that an administrator role can widen —
an administrator administers their own bank.
"""

from __future__ import annotations

from dataclasses import dataclass, field

ACCESS_VERSION = "1.0.0"

#: What a viewer may see. Ordered widest-last so a comparison is meaningful.
NONE = "NONE"
SUMMARY = "SUMMARY"
FULL = "FULL"

VISIBILITY: tuple[str, ...] = (NONE, SUMMARY, FULL)

#: §207's four levels of reach.
OWN = "OWN"
PROJECT = "PROJECT"
WORKFLOW = "WORKFLOW"
BROAD = "BROAD"

REACH: tuple[str, ...] = (OWN, PROJECT, WORKFLOW, BROAD)

#: Which roles reach how far. A role absent from this map reaches nowhere,
#: which is the fail-closed answer for a role somebody adds later and forgets
#: to place.
ROLE_REACH: dict[str, str] = {
    "ADMIN": BROAD,
    "DATA_STEWARD": BROAD,
    "ANALYST": OWN,
    "VIEWER": OWN,
}

#: Who sees inside the machine. §207's "AI Intelligence reviewer".
FULL_DETAIL_ROLES: frozenset[str] = frozenset({"ADMIN", "DATA_STEWARD"})

#: Fields a SUMMARY viewer never receives. Not because any one of them is a
#: secret, but because together they are the Studio, and the Studio is an
#: administrative surface (§119).
WITHHELD_FROM_SUMMARY: tuple[str, ...] = (
    "prompt_versions", "retrieved_teaching_case_ids", "served_models",
    "check_evidence", "routing_policy_version", "method_versions",
    "relationship_versions", "result_fingerprints", "agentic_run_id",
)


@dataclass(frozen=True)
class Viewer:
    """The person asking to read a review."""

    user_id: int | None = None
    role: str = ""
    tenant_id: str = ""
    #: Projects this person is a member of.
    project_ids: frozenset[str] = field(default_factory=frozenset)
    #: Investigations shared with them directly.
    shared_investigation_ids: frozenset[str] = field(
        default_factory=frozenset)
    #: Objects they have an open review or approval on. §207's third level.
    workflow_object_ids: frozenset[str] = field(default_factory=frozenset)

    @property
    def reach(self) -> str:
        return ROLE_REACH.get(self.role.upper(), "")


@dataclass(frozen=True)
class Subject:
    """The record being asked for, reduced to what the decision needs."""

    assurance_record_id: str = ""
    investigation_id: str = ""
    project_id: str = ""
    owner_user_id: int | None = None
    tenant_id: str = ""


@dataclass(frozen=True)
class Decision:
    """What the viewer gets, and why — the why is the point.

    A bare False leaves a support engineer guessing between "not shared",
    "wrong project" and "wrong tenant", which are three different
    conversations.
    """

    visibility: str
    reason: str
    via: str = ""

    @property
    def allowed(self) -> bool:
        return self.visibility != NONE

    @property
    def full(self) -> bool:
        return self.visibility == FULL

    def to_dict(self) -> dict[str, str]:
        return {"visibility": self.visibility, "reason": self.reason,
                "via": self.via, "allowed": str(self.allowed).lower()}


def _detail(viewer: Viewer, via: str) -> str:
    """How much of the record this viewer sees.

    An administrator sees inside the machine. Everybody else — including a
    project member reading a colleague's Investigation — sees the review,
    which is §207's "summary".
    """
    if viewer.role.upper() in FULL_DETAIL_ROLES and via in (BROAD, WORKFLOW):
        return FULL
    return SUMMARY


def may_read(viewer: Viewer, subject: Subject) -> Decision:
    """§207's decision. Every unknown answers NONE."""
    # The tenant first, and it is not a permission any role widens.
    if subject.tenant_id and viewer.tenant_id != subject.tenant_id:
        return Decision(NONE, "This record belongs to a different tenant.")
    if not viewer.role:
        return Decision(NONE, "The caller has no role, so nothing is "
                              "visible.")
    reach = viewer.reach
    if not reach:
        return Decision(NONE, f"The role {viewer.role!r} is not placed in the "
                              "assurance access policy, so it reaches "
                              "nothing.")

    if reach == BROAD:
        return Decision(_detail(viewer, BROAD),
                        "An authorized reviewer may review Investigations "
                        "across their own tenant.", BROAD)

    # Own, and shared-with-me. A record with no owner recorded is not
    # anybody's: it cannot be matched, so it is refused.
    if (subject.owner_user_id is not None
            and viewer.user_id is not None
            and subject.owner_user_id == viewer.user_id):
        return Decision(_detail(viewer, OWN),
                        "The viewer ran this Investigation.", OWN)
    if (subject.investigation_id
            and subject.investigation_id in viewer.shared_investigation_ids):
        return Decision(_detail(viewer, OWN),
                        "This Investigation was shared with the viewer.", OWN)
    if subject.project_id and subject.project_id in viewer.project_ids:
        return Decision(_detail(viewer, PROJECT),
                        "The viewer is a member of the Project this "
                        "Investigation belongs to.", PROJECT)
    if (subject.investigation_id
            and subject.investigation_id in viewer.workflow_object_ids):
        return Decision(_detail(viewer, WORKFLOW),
                        "The viewer has a workflow action on this "
                        "Investigation.", WORKFLOW)

    return Decision(NONE, "The viewer does not have access to the "
                          "Investigation this record describes.")


def readable(viewer: Viewer, subjects: list[Subject]) -> list[Subject]:
    """Filter a list. Used by the review list so a refusal is an absence
    rather than a row that says "you may not see this" — which would itself
    disclose that the Investigation exists."""
    return [s for s in subjects if may_read(viewer, s).allowed]


def redact(payload: dict, decision: Decision) -> dict:
    """Remove what a SUMMARY viewer does not get.

    Deletes rather than blanks. A key present with an empty value invites the
    reader to conclude the value was empty, which is a different and false
    statement.
    """
    if decision.full:
        return payload
    trimmed = {k: v for k, v in payload.items()
               if k not in WITHHELD_FROM_SUMMARY}
    trimmed["detail_level"] = SUMMARY
    trimmed["detail_note"] = (
        "This is the Investigation summary. The build-level detail — prompts, "
        "retrieved teaching cases and served model names — is available to "
        "AI Intelligence reviewers.")
    return trimmed
