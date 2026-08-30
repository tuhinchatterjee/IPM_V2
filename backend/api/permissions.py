"""
Role-based access for the API.

The shape of the control is in place now so that turning enforcement on later is
a configuration change, not a redesign of every endpoint. Today the caller's role
is read from a header and defaults to ADMIN, because there is no login on the API
yet — that is deliberate and clearly marked, not an oversight.

What is real today:
  * every mutating Data Builder endpoint declares the role it requires
  * the requirement is evaluated on every call
  * a caller without the role gets a 403 with a useful message

What is not real today:
  * the identity is asserted by the client rather than proven by a session

Phase 6 replaces `current_principal` with one backed by the existing Flask-Login
session and the users/teams tables. Nothing else in this file changes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum

from fastapi import Depends, Header, HTTPException, Request, status

from backend.config import settings

logger = logging.getLogger(__name__)


class Role(StrEnum):
    ADMIN = "ADMIN"
    DATA_STEWARD = "DATA_STEWARD"
    ANALYST = "ANALYST"
    VIEWER = "VIEWER"


# Who may do what. Data Builder writes are restricted to stewards and admins;
# reading the catalogue and running certified analyses is open to analysts.
WRITE_DATA_BUILDER = frozenset({Role.ADMIN, Role.DATA_STEWARD})
PUBLISH_DATASET = frozenset({Role.ADMIN, Role.DATA_STEWARD})
RUN_ANALYSIS = frozenset({Role.ADMIN, Role.DATA_STEWARD, Role.ANALYST})
#: Changing the model that ranks a bank's watchlist. Deliberately the narrowest
#: permission in the product: a data steward may publish data and an analyst may
#: run anything, but neither may decide what "high risk" means.
MANAGE_MODELS = frozenset({Role.ADMIN})
READ_ONLY = frozenset({Role.ADMIN, Role.DATA_STEWARD, Role.ANALYST, Role.VIEWER})
#: Saying something about something. §50: a VIEWER may "read approved/shared
#: objects and comment where permitted", and that is the one write a viewer has.
#:
#: It is a separate set from RUN_ANALYSIS on purpose. Sending a viewer an object
#: and asking them to comment on it, then refusing their reply, is the failure
#: this prevents — and it would have been invisible, because the request would
#: have looked as though it had simply not been answered.
COMMENT = frozenset({Role.ADMIN, Role.DATA_STEWARD, Role.ANALYST, Role.VIEWER})


@dataclass(frozen=True)
class Principal:
    """Who is calling. Trusted only as far as the note above allows."""

    user_id: int | None
    role: Role

    def has(self, allowed: frozenset[Role]) -> bool:
        return self.role in allowed


def current_principal(
    request: Request,
    x_ipm_role: str | None = Header(default=None, alias="X-IPM-Role"),
    x_ipm_user_id: int | None = Header(default=None, alias="X-IPM-User-Id"),
) -> Principal:
    """Resolve the caller.

    A signed session cookie ALWAYS wins. That is the whole security property:
    a signed-in Viewer cannot promote themselves by sending a header, because
    the header is never consulted once a session exists.

    Without a session, the headers decide. That path is what the demonstration's
    role switcher uses to let one person see the product as four different
    people, and it is also how the test suite acts as a particular user. It
    defaults to ADMIN so an unauthenticated local run is usable; behind a real
    deployment `settings.require_login` closes it.
    """
    # A real session, if there is one.
    from backend.api.auth import principal_from_request  # local: avoids a cycle

    session_principal = principal_from_request(request)
    if session_principal is not None:
        return session_principal

    if settings.require_login:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "not_signed_in",
                    "message": "Sign in to use CreditProbe."},
        )

    try:
        role = Role(x_ipm_role.upper()) if x_ipm_role else Role.ADMIN
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "unknown_role",
                "message": f"'{x_ipm_role}' is not a role. Valid roles: "
                           f"{', '.join(r.value for r in Role)}.",
            },
        ) from None
    return Principal(user_id=_known_user(x_ipm_user_id), role=role)


def _known_user(user_id: int | None) -> int | None:
    """The caller's id, but only if that user actually exists.

    Several tables record who did something with a foreign key to `users`. An id
    that names nobody would fail that constraint deep inside a service and
    surface as a 500 — "something went wrong on the server" — for what is really
    "the id you sent is not a user here".

    Treating an unknown id as anonymous instead means the action still happens
    and is simply recorded as having no named actor, which is the honest reading
    of a caller who could not be identified. Nothing about permissions depends on
    it: the ROLE decides what may be done, and the role is unaffected.
    """
    if user_id is None or not settings.has_database:
        return None
    try:
        from backend.db.engine import get_session
        from backend.db.models import User

        with get_session() as session:
            return user_id if session.get(User, user_id) is not None else None
    except Exception as e:  # pragma: no cover - the database went away
        logger.warning("Could not confirm user %s: %s", user_id, e)
        return None


def require(allowed: frozenset[Role]):
    """Dependency factory: refuse a caller without one of these roles."""

    def dependency(principal: Principal = Depends(current_principal)) -> Principal:
        if not principal.has(allowed):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error": "forbidden",
                    "message": (
                        f"This action requires one of: "
                        f"{', '.join(sorted(r.value for r in allowed))}. "
                        f"You are {principal.role.value}."
                    ),
                },
            )
        return principal

    return dependency


RequireDataSteward = Depends(require(WRITE_DATA_BUILDER))
RequirePublisher = Depends(require(PUBLISH_DATASET))
RequireAnalyst = Depends(require(RUN_ANALYSIS))
RequireAdmin = Depends(require(MANAGE_MODELS))
#: Everybody signed in, including a Viewer. Comments and workflow replies only.
RequireCommenter = Depends(require(COMMENT))


# ==========================================================================
# Named permissions for the AI Brain. §26, and the permission list in the
# final consolidation brief.
#
# Named rather than folded into MANAGE_MODELS because the actions differ in
# what they cost if they go wrong, and a single "AI admin" role would price
# all of them at the highest. Looking at what a package contains costs
# nothing and stops a reviewer doing their job if refused; activating one
# changes how every answer in the bank is produced.
#
# The split that matters is EVALUATE from ACTIVATE. §16 puts a measured
# evaluation before approval precisely so that the person who runs the
# numbers and the person who accepts them can be different people, and
# collapsing the two permissions would quietly remove that.
# ==========================================================================

#: Read the Brain Center: current Brain, ledger, history, lift reports.
AI_BRAIN_VIEW = frozenset({Role.ADMIN, Role.DATA_STEWARD, Role.ANALYST})
#: Build and download a Brain Pack, Learning Bundle or Developer Bundle.
#: A steward may: the export contains only approved, redacted material and
#: the exporter refuses anything else.
AI_BRAIN_EXPORT = frozenset({Role.ADMIN, Role.DATA_STEWARD})
#: Upload a package into quarantine. Uploading changes nothing about how
#: answers are produced, so this is not the narrow one.
AI_BRAIN_IMPORT = frozenset({Role.ADMIN, Role.DATA_STEWARD})
#: Run the receiver-specific evaluation against the sealed holdout.
AI_BRAIN_EVALUATE = frozenset({Role.ADMIN, Role.DATA_STEWARD})
#: Approve and activate an imported Brain. The narrowest permission here:
#: this is the one that changes what the bank's answers are made of.
AI_BRAIN_ACTIVATE = frozenset({Role.ADMIN})
#: Roll an activation back, or retire an installed Brain.
AI_BRAIN_ROLLBACK = frozenset({Role.ADMIN})
#: Add, raise or revoke trust for a signing key. §26: trust is a decision a
#: named person records, and only an administrator records it.
AI_BRAIN_SIGNERS = frozenset({Role.ADMIN})
#: Record and adjudicate Learning Ledger entries.
AI_LEARNING_REVIEW = frozenset({Role.ADMIN, Role.DATA_STEWARD})

RequireBrainView = Depends(require(AI_BRAIN_VIEW))
RequireBrainExport = Depends(require(AI_BRAIN_EXPORT))
RequireBrainImport = Depends(require(AI_BRAIN_IMPORT))
RequireBrainEvaluate = Depends(require(AI_BRAIN_EVALUATE))
RequireBrainActivate = Depends(require(AI_BRAIN_ACTIVATE))
RequireBrainRollback = Depends(require(AI_BRAIN_ROLLBACK))
RequireBrainSigners = Depends(require(AI_BRAIN_SIGNERS))
RequireLearningReview = Depends(require(AI_LEARNING_REVIEW))


# ==========================================================================
# Regulatory Intelligence. §27-§38.
#
# The same split as the Brain, for the same reason. Reading what a circular
# requires is analytical work; deciding what a clause means for this bank is
# a regulatory judgement with a name on it; and promoting that judgement into
# a change to how figures are computed is the narrowest action of the three.
#
# REGULATORY_REVIEW is deliberately not ADMIN-only. The person who should be
# reading a SAMA circular clause by clause is a credit risk SME, not whoever
# happens to hold the database password — and a permission that forces the
# wrong person to do the review produces reviews nobody trusts.
# ==========================================================================

#: See the regulatory library, requirements and releases.
REGULATORY_VIEW = frozenset({Role.ADMIN, Role.DATA_STEWARD, Role.ANALYST})
#: Upload a regulatory document and run the extraction pipeline.
REGULATORY_INGEST = frozenset({Role.ADMIN, Role.DATA_STEWARD})
#: Decide what a clause means: approve, reject, correct, split, merge, defer.
REGULATORY_REVIEW = frozenset({Role.ADMIN, Role.DATA_STEWARD})
#: Settle a contradiction between two regulatory positions.
REGULATORY_RESOLVE = frozenset({Role.ADMIN, Role.DATA_STEWARD})
#: Promote an approved requirement into a draft change, and approve a
#: Regulatory Release. The narrowest: this is where a regulation starts to
#: affect what the bank's numbers are.
REGULATORY_PROMOTE = frozenset({Role.ADMIN})

RequireRegulatoryView = Depends(require(REGULATORY_VIEW))
RequireRegulatoryIngest = Depends(require(REGULATORY_INGEST))
RequireRegulatoryReview = Depends(require(REGULATORY_REVIEW))
RequireRegulatoryResolve = Depends(require(REGULATORY_RESOLVE))
RequireRegulatoryPromote = Depends(require(REGULATORY_PROMOTE))


# ==========================================================================
# Continuous Learning. §86.
#
# Reading how the product is performing is deliberately wide: §77 requires
# every improvement claim to travel with its sample context, and a claim
# only administrators can check is a claim. An analyst who was given an
# answer is entitled to ask how well this system has been doing.
#
# Recording a measurement is narrower, because a snapshot is a permanent
# record other decisions get made against.
# ==========================================================================

#: See the Continuous Learning cockpit, timeline and dimension deltas.
AI_LEARNING_VIEW = frozenset({Role.ADMIN, Role.DATA_STEWARD, Role.ANALYST})
#: Record a baseline or a performance snapshot.
AI_LEARNING_MEASURE = frozenset({Role.ADMIN, Role.DATA_STEWARD})
#: Run an evaluation against the sealed holdout. The narrowest: §58 keeps
#: the holdout for formal certification, and each run spends some of what
#: makes it meaningful.
AI_LEARNING_CERTIFY = frozenset({Role.ADMIN})

RequireLearningView = Depends(require(AI_LEARNING_VIEW))
RequireLearningMeasure = Depends(require(AI_LEARNING_MEASURE))
RequireLearningCertify = Depends(require(AI_LEARNING_CERTIFY))
