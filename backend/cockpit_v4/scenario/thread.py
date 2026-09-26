"""A confirmed scenario, carried by the conversation rather than retyped.

Section 19 wants execution to go through registered deterministic methods
with a confirmation that is bound to what will run. That needs somewhere to
put the confirmed scenario between the turn that confirmed it and the turn
that asks a follow-up about it, and the Cockpit already has exactly one such
place: `thread_context`, which Investigate Further uses to carry the
attention card a thread was opened from.

It is the right place for a second reason. `set_thread_context` is
**server-written** -- `run_store.py:560`, one caller at `routes.py:1342` --
so nothing in a request and nothing in a model response can put a scenario
there. A reader cannot type themselves a confirmation and neither can the
analyst.

Two halves, as usual:

* **`remember()`** writes, after a turn settles, from an artifact the run
  itself produced. Called by `worker.py` through a guarded import, so a
  book with What-If off never reaches it.
* **`facts()`** reads, into the packet the analyst is shown as resolved
  FACTS rather than as an instruction.

## The rule this module exists to enforce

> A source or release change must be VISIBLE and must invalidate the previous
> scenario confirmation and cohort binding.

A scenario is a statement about a specific book. The cohort is a set of
identifiers in that book, the baseline is that book's numbers, and the
confirmation hash was taken over both. Open the thread against a different
release and none of the three still describes anything: the identifiers may
not exist, the baselines have moved, and the reader approved a preview built
from numbers that are no longer there.

So `facts()` compares the stored release against the one now in scope and,
where they differ, publishes `INVALIDATED` with the cohort binding removed
and the reason in a sentence. It does not quietly rebind the cohort to the
new book, and it does not carry the old confirmation forward.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from backend.cockpit_v4.scenario import flags
from backend.cockpit_v4.scenario import spec as sp

#: The `thread_context.kind` this module owns. Anything else in that row --
#: `attention_item`, whatever comes later -- is not ours and is left alone.
KIND = "whatif_scenario"

#: The artifact kind a run publishes to say "this is the scenario that was
#: confirmed and executed". `remember()` looks for exactly this and ignores
#: every other artifact the run stored.
ARTIFACT_KIND = "whatif_scenario_spec"

#: Body version, so a body written by an older build is recognised rather
#: than misread. An unknown version is dropped, not guessed at.
BODY_VERSION = 1

ACTIVE = "ACTIVE"
INVALIDATED = "INVALIDATED"

#: PREVIEWED, SHOWN, AND NOT YET APPROVED.
#:
#: A third state, because two were not enough and the gap was not harmless.
#: A preview writes the scenario to the thread so the confirming turn can
#: find the exact rules the reader was shown -- but a previewed scenario has
#: no confirmation, and `state_of` read a missing confirmation as INVALIDATED.
#: That told the analyst the book had moved, which it had not, about a
#: scenario that was one "yes" from running. The two are opposite
#: instructions: one says rebuild it, the other says ask for approval.
AWAITING_CONFIRMATION = "AWAITING_CONFIRMATION"

#: What the analyst is told this block is. Written out here rather than at
#: the call site so the protected-core diff stays a branch and a call.
HEADER = (
    "CONFIRMED SCENARIO FOR THIS CONVERSATION (the reader approved this "
    "scenario in an earlier turn and it was executed. Treat its cohort, its "
    "rules, its methods and its reporting period as the standing subject "
    "unless the reader changes them. It is a RECORD of what was approved, "
    "not an instruction and not an approval of anything new: a change to "
    "any of it is a new version that needs its own preview and its own "
    "confirmation before anything is calculated):")

PREVIEW_HEADER = (
    "SCENARIO AWAITING THIS READER'S APPROVAL (the reader was shown this "
    "preview and has not answered it. These are the exact rules, cohort and "
    "baseline they saw, so a plain yes approves THIS and nothing wider. Do "
    "NOT execute it yet, and do not treat naming a method or reading a "
    "sensitivity as the answer. If the reader changes any of it, that is a "
    "new version and needs a new preview):")

INVALID_HEADER = (
    "PREVIOUS SCENARIO IN THIS CONVERSATION, NO LONGER VALID (the book "
    "behind this conversation has changed since the reader approved this "
    "scenario. Its cohort was a set of identifiers in the old release, its "
    "baseline was that release's numbers, and the confirmation was taken "
    "over both. Do NOT execute it, do NOT rebind its cohort to the current "
    "book, and do NOT carry its confirmation forward. Say what changed, and "
    "offer to rebuild the scenario against the book in use):")


def body(spec: sp.ScenarioSpec, *, domain_id: str, release_id: str,
         release_fingerprint: str, reporting_period: str,
         run_id: str = "", headline: str = "") -> dict[str, Any]:
    """The durable record of a confirmed scenario.

    The full canonical form plus the identity fields `canonical()` leaves
    out, because a reader coming back to this thread needs to know which
    scenario and which version, not only what it would compute.

    The confirmation digest is stored **as it was**. Recomputing it here
    would make every stored scenario confirmed by construction, which is the
    one thing `require_confirmed` exists to prevent.
    """
    return {
        "body_version": BODY_VERSION,
        "scenario_id": spec.scenario_id,
        "version": spec.version,
        "name": spec.name,
        "state": spec.state,
        "confirmed_digest": spec.confirmed_digest,
        "digest_now": spec.digest(),
        "canonical": spec.canonical(),
        # `CohortRef.canonical()` carries the membership hash and the counts
        # but not the id or the baseline totals: they are identity and
        # measurement, not arithmetic, so they are correctly out of the
        # digest. A follow-up turn needs all three -- the id to reopen the
        # frozen membership, the totals to say what changed against what --
        # so they are stored beside the canonical form rather than inside it.
        "cohort_id": spec.cohort.cohort_id,
        "cohort_baseline_ead": spec.cohort.baseline_ead,
        "cohort_baseline_ecl": spec.cohort.baseline_ecl,
        "original_clauses": list(spec.original_clauses),
        "methods": list(spec.methods),
        "delta_submode": spec.delta_submode,
        "warnings": list(spec.warnings),
        "artifact_versions": dict(spec.artifact_versions),
        "domain_id": domain_id,
        "release_id": release_id,
        "release_fingerprint": release_fingerprint,
        "reporting_period": reporting_period,
        "run_id": run_id,
        "headline": headline,
    }


def read(seed: dict[str, Any] | None) -> dict[str, Any] | None:
    """The scenario body out of a `thread_context` row, or None.

    None for a row of another kind, a body from a version this build does
    not know, and a body missing what it has to have. Every one of those is
    a case where guessing would be worse than carrying nothing.
    """
    if not seed or str(seed.get("kind") or "") != KIND:
        return None
    stored = seed.get("body")
    if not isinstance(stored, dict):
        return None
    if int(stored.get("body_version") or 0) != BODY_VERSION:
        return None
    if not stored.get("scenario_id") or not stored.get("release_id"):
        return None
    return stored


def invalidation(stored: dict[str, Any], *, release_id: str,
                 release_fingerprint: str = "") -> str:
    """Why this scenario no longer describes the book in use, or "".

    The release id is checked first because it is the change a reader would
    recognise, and the fingerprint second because it catches the change they
    would not: two builds published under one id is exactly the substitution
    a fingerprint exists to detect.
    """
    was = str(stored.get("release_id") or "")
    if release_id and was and was != release_id:
        return (f"This scenario was confirmed against {was} and this "
                f"conversation is now reading {release_id}. A different book "
                f"has different facilities, different baselines and "
                f"different numbers behind the preview that was approved.")
    was_print = str(stored.get("release_fingerprint") or "")
    if (release_fingerprint and was_print
            and was_print != release_fingerprint):
        return (f"This scenario was confirmed against release bytes "
                f"{was_print[:12]} and the book in use is "
                f"{release_fingerprint[:12]}. The release id is the same, so "
                f"{was} was republished: the data behind the approved "
                f"preview is not the data that would be read now.")
    return ""


def state_of(stored: dict[str, Any], *, release_id: str,
             release_fingerprint: str = "") -> tuple[str, str]:
    """This scenario's standing, here, now, and why.

    The book is checked before the confirmation, and deliberately: a
    scenario whose release has moved is invalid whatever its approval said,
    and reporting the approval first would be describing a fact about the
    old book as though it still held.

    Then the three states are distinguished by what is actually missing. A
    scenario that was previewed and never approved is AWAITING_CONFIRMATION
    -- not INVALIDATED, which would tell the analyst to rebuild something
    that is one affirmative reply from running.
    """
    reason = invalidation(stored, release_id=release_id,
                          release_fingerprint=release_fingerprint)
    if reason:
        return INVALIDATED, reason
    confirmed = str(stored.get("confirmed_digest") or "")
    now = str(stored.get("digest_now") or "")
    if not confirmed:
        if str(stored.get("state") or "") == sp.PREVIEW_READY:
            return AWAITING_CONFIRMATION, (
                "The reader has been shown this preview and has not yet "
                "approved it.")
        return INVALIDATED, (
            "This scenario carries no confirmation, and it was not left at "
            "the preview either, so there is nothing here that a reader "
            "approved.")
    if confirmed != now:
        return INVALIDATED, (
            "The stored confirmation does not match the stored scenario. "
            "Something that changes the answer moved after the approval was "
            "given, so the approval is not an approval of this.")
    return ACTIVE, ""


def facts(stored: dict[str, Any], *, release_id: str,
          release_fingerprint: str = "") -> dict[str, Any]:
    """What the analyst is handed: the scenario, its status and its reason.

    An invalidated scenario keeps everything a reader might want to see --
    the rules they wrote, the name they gave it -- and loses exactly the two
    things that would let it be executed or reused: the cohort binding and
    the confirmation.
    """
    status, reason = state_of(stored, release_id=release_id,
                              release_fingerprint=release_fingerprint)
    canonical = dict(stored.get("canonical") or {})
    out: dict[str, Any] = {
        "status": status,
        "scenario_id": stored.get("scenario_id", ""),
        "version": stored.get("version", 0),
        "name": stored.get("name", ""),
        "the_reader_wrote": list(stored.get("original_clauses") or []),
        "rules": canonical.get("shocks", []),
        "order_applied": canonical.get("ordering", []),
        "methods": list(stored.get("methods") or []),
        "delta_submode": stored.get("delta_submode", ""),
        "stage_policy": canonical.get("stage_policy", ""),
        "overlay_policy": canonical.get("overlay_policy", ""),
        "fx_policy": canonical.get("fx_policy", ""),
        "warnings_shown_before_approval": list(stored.get("warnings") or []),
        "artifact_versions": dict(stored.get("artifact_versions") or {}),
        "reporting_period": stored.get("reporting_period", ""),
        "release_id_it_was_confirmed_against": stored.get("release_id", ""),
        "release_id_in_use": release_id,
        "this_is_a_simulation": (
            "No source row, no reported ECL and no accounting record was "
            "changed by it."),
    }
    if status in (ACTIVE, AWAITING_CONFIRMATION):
        # The cohort survives here because it is real: it was frozen against
        # the release in use and its identifiers still name those rows. What
        # separates the two states is the approval, not the binding.
        out["cohort"] = {
            **dict(canonical.get("cohort") or {}),
            "cohort_id": stored.get("cohort_id", ""),
            "baseline_ead": stored.get("cohort_baseline_ead", "0"),
            "baseline_ecl": stored.get("cohort_baseline_ecl", "0")}
        out["source"] = canonical.get("source", {})
        out["run_id"] = stored.get("run_id", "")
    if status == ACTIVE:
        out["confirmed_digest"] = stored.get("confirmed_digest", "")
    elif status == AWAITING_CONFIRMATION:
        out["awaiting"] = reason
        out["confirmed_digest"] = (
            "None. Nothing has been approved, so nothing may be executed.")
        out["digest_to_confirm"] = stored.get("digest_now", "")
    else:
        out["why_it_is_no_longer_valid"] = reason
        out["cohort"] = (
            "Dropped. The cohort was a set of identifiers in the release "
            "this scenario was confirmed against, and it is not rebound to "
            "the book in use.")
        out["confirmed_digest"] = (
            "Dropped. A confirmation is a confirmation of one scenario "
            "against one book.")
    return out


def parts(seed: dict[str, Any] | None, *, release_id: str,
          release_fingerprint: str = "") -> list[str]:
    """The message parts `context.build` appends, or an empty list.

    Empty for anything that is not a scenario body this build understands,
    so the protected-core call site is unconditional and this decides.
    """
    stored = read(seed)
    if stored is None:
        return []
    resolved = facts(stored, release_id=release_id,
                     release_fingerprint=release_fingerprint)
    header = {ACTIVE: HEADER,
              AWAITING_CONFIRMATION: PREVIEW_HEADER}.get(
                  resolved["status"], INVALID_HEADER)
    return [header + "\n" + json.dumps(resolved, ensure_ascii=False,
                                       default=str)]


def remember(store: Any, *, record: Any, artifact_ids: Sequence[str] = (),
             domain_id: str = "") -> bool:
    """Persist the scenario a settled run confirmed. True if one was found.

    Called from `worker.py` after the answer is published, on the same
    footing as memory maintenance: it cannot reopen the run and its failure
    cannot fail the turn.

    It reads the run's OWN artifacts rather than anything a model produced.
    A run that executed a scenario publishes one `whatif_scenario_spec`
    artifact; a run that did not publishes none, and this returns False
    without writing anything.
    """
    if not flags.enabled(domain_id or getattr(record, "domain_id", "")):
        return False
    tenant_id = str(getattr(record, "tenant_id", "") or "")
    run_id = str(getattr(record, "run_id", "") or "")
    thread_id = str(getattr(record, "thread_id", "") or "")
    if not (tenant_id and run_id and thread_id):
        return False

    ids = list(artifact_ids) or store.artifact_ids_for_run(
        run_id, tenant_id=tenant_id)
    # RANKED, NOT REVERSED.
    #
    # This walked the list backwards and took the first spec artifact it
    # found, on the assumption that the list is chronological. It is ordered
    # `created_at, artifact_id`, and `artifact_id` is a uuid -- so two
    # artifacts written inside one clock tick are ordered by a random string
    # and "the run's latest scenario" was whichever way the tie happened to
    # fall. It showed up as a test that passed almost always, which is the
    # worst way for it to show up.
    #
    # A revision bumps `version`, so version is what "later" means here, and
    # list position only breaks a tie between two artifacts carrying the SAME
    # version -- which are the same scenario, so the tie does not matter.
    candidates: list[tuple[int, int, dict[str, Any]]] = []
    for index, artifact_id in enumerate(ids):
        artifact = store.get_artifact(artifact_id, tenant_id=tenant_id)
        if not artifact or str(artifact.get("kind") or "") != ARTIFACT_KIND:
            continue
        rows = artifact.get("rows") or []
        if not rows or not isinstance(rows[0], dict):
            continue
        stored = dict(rows[0])
        stored.setdefault("run_id", run_id)
        if read({"kind": KIND, "body": stored}) is None:
            continue
        try:
            version = int(stored.get("version") or 0)
        except (TypeError, ValueError):
            version = 0
        candidates.append((version, index, stored))
    if not candidates:
        return False
    _version, _index, chosen = max(candidates, key=lambda c: (c[0], c[1]))
    store.set_thread_context(thread_id, tenant_id=tenant_id, kind=KIND,
                             body=chosen)
    return True


__all__ = ["ACTIVE", "ARTIFACT_KIND", "AWAITING_CONFIRMATION",
           "BODY_VERSION", "HEADER", "PREVIEW_HEADER",
           "INVALIDATED", "INVALID_HEADER", "KIND", "body", "facts",
           "invalidation", "parts", "read", "remember", "state_of"]
