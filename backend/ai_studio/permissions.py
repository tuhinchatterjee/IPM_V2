"""
Who may see and do what in the Studio, and what the Studio may never show.
§119, §120.

    §119: "Enforce backend-side. A normal Analyst may see only a compact
           current assurance/release badge in Trace."
    §120: "Production planner can never access them."

Why the permissions are named rather than role-checked inline
---------------------------------------------------------------
Eight named permissions map onto four roles today, and the mapping will change
— a Model Risk reviewer who may approve a release but not author a teaching
case is a real person in a real bank, and the roles this product ships with do
not express them yet. Naming the permission separately from the role means
that change is a table edit rather than a search for every `role == ADMIN` in
the codebase.

Enforced backend-side, which is the only place enforcement exists. A Studio tab
hidden in the front end is a tab reachable with curl.

§120 is the sealed holdout, one layer further out
---------------------------------------------------
The factory already keeps holdout content behind an import-graph boundary the
backend cannot cross. This is the SECOND wall: even where a number is legally
available, the Studio shows only what §120 whitelists — version, counts,
families, critical count, result, fingerprint. Never a question, a gold plan, a
gold result, a label or an answer.

Two walls rather than one because the first wall is about what the code CAN
reach and this one is about what a screen SHOWS, and a screenshot of a holdout
question in a demo has leaked it whatever the import graph says.
"""

from __future__ import annotations

from typing import Any

from backend.api.permissions import Role

STUDIO_PERMISSION_VERSION = "1.0.0"

# ------------------------------------------------------- §119's eight
VIEW = "AI_INTELLIGENCE_VIEW"
TEACHING_AUTHOR = "AI_TEACHING_AUTHOR"
TEACHING_REVIEW = "AI_TEACHING_REVIEW"
MODEL_EXPERIMENT = "AI_MODEL_EXPERIMENT"
EVALUATION_RUN = "AI_EVALUATION_RUN"
RELEASE_APPROVE = "AI_RELEASE_APPROVE"
LIVE_HEALTH_VIEW = "AI_LIVE_HEALTH_VIEW"
ADMIN = "AI_ADMIN"

PERMISSIONS: tuple[str, ...] = (VIEW, TEACHING_AUTHOR, TEACHING_REVIEW,
                                MODEL_EXPERIMENT, EVALUATION_RUN,
                                RELEASE_APPROVE, LIVE_HEALTH_VIEW, ADMIN)

#: What each one lets somebody do, in the words that would appear beside a
#: checkbox. A permission nobody can describe gets granted to everybody.
MEANS: dict[str, str] = {
    VIEW: "See the Studio and what CreditProbe has been taught.",
    TEACHING_AUTHOR: "Write and edit teaching cases. Cannot approve them.",
    TEACHING_REVIEW: "Approve or reject a teaching case for production "
                     "retrieval.",
    MODEL_EXPERIMENT: "Run prompt and model experiments against fixtures.",
    EVALUATION_RUN: "Run evaluations, including ones that cost money.",
    RELEASE_APPROVE: "Approve an Intelligence Release for production.",
    LIVE_HEALTH_VIEW: "See live provider state, latency and cost.",
    ADMIN: "Everything, including changing what the other permissions mean.",
}

#: Which roles hold which permission today. Deliberately conservative: the
#: narrowest grants in the product are the ones that change what CreditProbe
#: believes, and a data steward who may publish a dataset still may not decide
#: what a good answer looks like.
GRANTS: dict[str, frozenset[Role]] = {
    VIEW: frozenset({Role.ADMIN, Role.DATA_STEWARD}),
    TEACHING_AUTHOR: frozenset({Role.ADMIN}),
    TEACHING_REVIEW: frozenset({Role.ADMIN}),
    MODEL_EXPERIMENT: frozenset({Role.ADMIN}),
    EVALUATION_RUN: frozenset({Role.ADMIN}),
    RELEASE_APPROVE: frozenset({Role.ADMIN}),
    LIVE_HEALTH_VIEW: frozenset({Role.ADMIN, Role.DATA_STEWARD}),
    ADMIN: frozenset({Role.ADMIN}),
}

#: Authoring and approving are separated on purpose, and this records that it
#: is on purpose. A person who writes a case and approves their own case has
#: produced a case with an approval record and no review, which is exactly the
#: thing the governance report exists to make visible.
SEPARATED: tuple[tuple[str, str], ...] = (
    (TEACHING_AUTHOR, TEACHING_REVIEW),
)


def holds(role: Role | str, permission: str) -> bool:
    """Whether a role holds a permission.

    An unknown permission is refused rather than granted. The permissive
    version turns a typo in a route decorator into an open door.
    """
    allowed = GRANTS.get(permission)
    if allowed is None:
        return False
    try:
        return Role(role) in allowed
    except ValueError:
        return False


def granted(role: Role | str) -> list[str]:
    return [p for p in PERMISSIONS if holds(role, p)]


def matrix() -> dict[str, Any]:
    """The whole grant table, for the Settings tab and for a reviewer."""
    return {
        "version": STUDIO_PERMISSION_VERSION,
        "permissions": [
            {"id": p, "means": MEANS[p],
             "roles": sorted(r.value for r in GRANTS[p])}
            for p in PERMISSIONS],
        "separated_duties": [{"author": a, "review": r} for a, r in SEPARATED],
        "enforced": "backend",
    }


# ---------------------------------------------------------------------------
# The analyst's badge
# ---------------------------------------------------------------------------

def badge(release_id: str, state: str, readiness: str) -> dict[str, Any]:
    """§119: what a normal Analyst sees, and all of it.

    A compact assurance badge in the Trace. Not a link into the Studio, not a
    score, not a case count — those are the authoring surface, and an analyst
    who could read them could read which cases production retrieves, which is
    most of the way to knowing how to phrase a question to get a chosen
    answer.
    """
    return {"release_id": release_id or "unreleased", "state": state,
            "readiness": readiness}


# ---------------------------------------------------------------------------
# §120 — holdout safety
# ---------------------------------------------------------------------------

#: The only holdout fields a production Studio may render.
HOLDOUT_SHOWN: tuple[str, ...] = ("version", "case_count", "families",
                                  "critical_count", "evaluation_result",
                                  "fingerprint")

#: Named explicitly rather than left as "everything else", because a whitelist
#: that nobody can compare against a blacklist is a whitelist nobody audits.
HOLDOUT_NEVER: tuple[str, ...] = ("questions", "question", "gold_plans",
                                  "gold_plan", "gold_results", "gold_result",
                                  "labels", "label", "answers", "answer",
                                  "expected", "turns", "cases")


class HoldoutLeak(Exception):
    """A holdout payload carrying content rather than metadata.

    Raised rather than filtered. A payload silently stripped would let the
    caller go on building them, and the next one would be assembled somewhere
    this function does not run.
    """


def holdout_view(manifest: dict[str, Any]) -> dict[str, Any]:
    """§120's whitelist, applied to a holdout manifest.

    Checks for the forbidden keys as well as selecting the permitted ones, so
    a manifest that gained a `gold_results` field fails loudly here instead of
    being quietly dropped and reappearing in the next surface that forgets to
    call this.
    """
    present = [key for key in HOLDOUT_NEVER if key in manifest]
    if present:
        raise HoldoutLeak(
            f"the holdout manifest carries {', '.join(present)}, which §120 "
            "forbids the production Studio from showing")
    return {"version": STUDIO_PERMISSION_VERSION,
            **{key: manifest.get(key) for key in HOLDOUT_SHOWN},
            "shown": list(HOLDOUT_SHOWN),
            "withheld": list(HOLDOUT_NEVER),
            "note": ("Metadata and aggregate metrics only. Questions, gold "
                     "plans, gold results, labels and answers are never shown "
                     "in production, and the production planner cannot reach "
                     "them at all.")}


__all__ = ["ADMIN", "EVALUATION_RUN", "GRANTS", "HOLDOUT_NEVER",
           "HOLDOUT_SHOWN", "HoldoutLeak", "LIVE_HEALTH_VIEW", "MEANS",
           "MODEL_EXPERIMENT", "PERMISSIONS", "RELEASE_APPROVE", "SEPARATED",
           "STUDIO_PERMISSION_VERSION", "TEACHING_AUTHOR", "TEACHING_REVIEW",
           "VIEW", "badge", "granted", "holdout_view", "holds", "matrix"]
