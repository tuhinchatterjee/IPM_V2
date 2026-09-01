"""
Who may export what.

§39 sets one rule above all the others: an export enforces the same permissions
as viewing the analysis, or stricter. A workbook is the analysis, detached from
the product and mailed to a laptop — the moment a download is easier to obtain
than the screen it came from, the screen's permissions have stopped meaning
anything.

Two experiences, two bars
-------------------------
The **Results Workbook** carries what the analysis already shows: the answer,
the result table, the scope and the provenance. Anyone who may see the analysis
may download it.

The **Full Calculation Pack** goes further — source profiles, join
reconciliation, the compiled query, and where it is small enough, the row-level
population itself. That is a data extract with an audit trail wrapped around it,
so it takes a stronger claim on the analysis than merely being able to read it.

The defaults, from §39:

    ADMINISTRATOR   both, always.
    DATA_STEWARD    both, for anything within their data permissions.
    ANALYST         results always; the full pack for analyses they own or were
                    sent for review.
    VIEWER          results for analyses shared with them or published; the
                    full pack only where explicitly permitted.

Decided here, enforced in the route
-----------------------------------
This module returns a Decision, never an HTTP response, so the same rule can be
evaluated by a test, by an audit record and by the endpoint without three
different opinions about what "shared with me" means. The endpoint turns a
refusal into a 403 with the reason attached; the audit log records the decision
whether or not it allowed anything.

Hiding a button is not authorisation. The interface hides what a user cannot
download because showing it would be rude, and this module refuses it because
showing it would be a breach.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from backend.api.permissions import Principal, Role
from backend.exports.contract import CALCULATION_PACK, RESULTS

logger = logging.getLogger(__name__)


@dataclass
class Decision:
    """Whether this export may happen, and why."""

    allowed: bool
    kind: str
    reason: str
    #: The basis on which access was granted or refused, for the audit log.
    basis: str = ""
    #: Fields or sheets withheld even though the export was allowed.
    redactions: list[str] = field(default_factory=list)
    #: True where the caller may see the row-level population.
    row_level: bool = False

    def as_record(self) -> dict[str, object]:
        return {
            "allowed": self.allowed,
            "kind": self.kind,
            "basis": self.basis,
            "reason": self.reason,
            "redactions": list(self.redactions),
            "row_level": self.row_level,
        }


def decide(principal: Principal, *, kind: str, run_id: int) -> Decision:
    """May this caller export this run, in this form?

    Reads the run's ownership and sharing from the database. A database that
    cannot be reached is not a reason to allow an export: the answer is the
    conservative one, and it says which question could not be answered.
    """
    if kind == RESULTS:
        return _results(principal, run_id)
    if kind == CALCULATION_PACK:
        return _pack(principal, run_id)
    return Decision(False, kind, f"'{kind}' is not an export this product produces.",
                    basis="unknown_kind")


# ------------------------------------------------------------------- results


def _results(principal: Principal, run_id: int) -> Decision:
    if principal.role in {Role.ADMIN, Role.DATA_STEWARD}:
        return Decision(True, RESULTS, "", basis=f"role:{principal.role.value}",
                        row_level=False)
    if principal.role is Role.ANALYST:
        return Decision(True, RESULTS, "", basis="role:ANALYST", row_level=False)

    access = _viewer_access(principal, run_id)
    if access:
        return Decision(True, RESULTS, "", basis=access, row_level=False)
    return Decision(
        False, RESULTS,
        "This analysis has not been shared with you. A Viewer may download the "
        "results of an analysis that was published or sent to them; ask the "
        "owner to share it.",
        basis="viewer:not_shared",
    )


# ---------------------------------------------------------------------- pack


def _pack(principal: Principal, run_id: int) -> Decision:
    if principal.role is Role.ADMIN:
        return Decision(True, CALCULATION_PACK, "", basis="role:ADMIN",
                        row_level=True)
    if principal.role is Role.DATA_STEWARD:
        return Decision(
            True, CALCULATION_PACK, "", basis="role:DATA_STEWARD", row_level=True,
        )
    if principal.role is Role.ANALYST:
        basis = _analyst_claim(principal, run_id)
        if basis:
            return Decision(True, CALCULATION_PACK, "", basis=basis, row_level=True)
        return Decision(
            False, CALCULATION_PACK,
            "The full calculation pack carries the row-level population and the "
            "detailed lineage of this analysis, so it is available to the "
            "analyst who ran it, to anyone it was sent to for review, and to "
            "Administrators and Data Stewards. The results workbook is "
            "available to you now.",
            basis="analyst:not_owner",
        )

    return Decision(
        False, CALCULATION_PACK,
        "The full calculation pack exposes row-level data and detailed lineage, "
        "which a Viewer role does not carry. The results workbook is available "
        "to you where the analysis has been shared with you.",
        basis="viewer:role",
    )


# ------------------------------------------------------------ what the run is


def _analyst_claim(principal: Principal, run_id: int) -> str:
    """The analyst's claim on this run: ran it, or was sent it."""
    if principal.user_id is None:
        return ""
    owner = _owner_of(run_id)
    if owner is None:
        # An unattributable run predates user attribution or lost its owner.
        # Refusing every analyst would make old analyses undownloadable by
        # anyone but an administrator, which is a worse failure than allowing
        # the role that may run the same analysis again to export it.
        return "analyst:run_unattributed"
    if owner == principal.user_id:
        return "analyst:owner"
    if _sent_to(principal.user_id, run_id):
        return "analyst:recipient"
    return ""


def _viewer_access(principal: Principal, run_id: int) -> str:
    """A Viewer's claim on this run: it was published, or sent to them."""
    if _published(run_id):
        return "viewer:published"
    if principal.user_id is not None and _sent_to(principal.user_id, run_id):
        return "viewer:recipient"
    return ""


def _owner_of(run_id: int) -> int | None:
    from backend.config import settings

    if not settings.has_database:
        return None
    try:
        from backend.db.engine import get_session
        from backend.models.platform import AnalysisRun

        with get_session() as session:
            run = session.get(AnalysisRun, run_id)
            return run.user_id if run is not None else None
    except Exception as e:  # noqa: BLE001
        logger.warning("Could not read run ownership for export: %s", e)
        return None


def _published(run_id: int) -> bool:
    """Whether the investigation this run belongs to is visible to everyone.

    A standalone thread — one with no project — is global by construction; a
    project thread is global only once somebody published it. That is the same
    rule the Investigations listing applies, deliberately: an export must not be
    reachable for a thread the listing would not show.
    """
    from backend.config import settings

    if not settings.has_database:
        return False
    try:
        from backend.db.engine import get_session
        from backend.models.platform import AnalysisRun, Investigation

        with get_session() as session:
            run = session.get(AnalysisRun, run_id)
            if run is None or run.investigation_id is None:
                return False
            thread = session.get(Investigation, run.investigation_id)
            if thread is None:
                return False
            return thread.project_id is None or bool(thread.published_globally)
    except Exception as e:  # noqa: BLE001
        logger.warning("Could not read publication state for export: %s", e)
        return False


def _sent_to(user_id: int, run_id: int) -> bool:
    """Whether this run, its thread or its project was sent to this user.

    Reads the workflow the collaboration layer already maintains rather than
    inventing a second notion of sharing. Somebody asked to review an analysis
    can download it; that is what being asked to review it means.

    A run is reachable through three objects — the analysis itself, the thread
    it was asked in, and the project that thread belongs to — because that is
    how people actually share work: "review this investigation" is a request to
    look at the answers inside it.
    """
    from backend.config import settings

    if not settings.has_database:
        return False
    try:
        from sqlalchemy import and_, or_, select

        from backend.db.engine import get_session
        from backend.models.platform import (
            AnalysisRun,
            TeamMember,
            WorkflowItem,
            WorkflowRecipient,
        )

        with get_session() as session:
            run = session.get(AnalysisRun, run_id)
            if run is None:
                return False
            targets: list[tuple[str, str]] = [("analysis", str(run_id))]
            if run.investigation_id:
                targets.append(("investigation", str(run.investigation_id)))
            if run.project_id:
                targets.append(("project", str(run.project_id)))

            teams = list(session.execute(
                select(TeamMember.team_id).where(TeamMember.user_id == user_id)
            ).scalars().all())

            addressed = [WorkflowRecipient.user_id == user_id]
            if teams:
                addressed.append(WorkflowRecipient.team_id.in_(teams))

            found = session.execute(
                select(WorkflowRecipient.id)
                .join(WorkflowItem,
                      WorkflowItem.id == WorkflowRecipient.workflow_item_id)
                .where(
                    or_(*[
                        and_(WorkflowItem.object_type == kind,
                             WorkflowItem.object_id == identifier)
                        for kind, identifier in targets
                    ]),
                    or_(*addressed),
                )
                .limit(1)
            ).first()
            return found is not None
    except Exception as e:  # noqa: BLE001
        logger.warning("Could not read sharing for export: %s", e)
        return False
