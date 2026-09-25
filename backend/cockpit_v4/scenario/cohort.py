"""Freezing "these customers" so it means the same rows on turn three.

Section 6.1: *"When the user says 'these customers,' use the persisted,
authorized investigation cohort -- not the top ten displayed rows, a chart
sample, a paraphrase, or an unbounded new search."*

Nothing in the accepted runtime persists a cohort. `artifacts` holds one
query's result set bound to one run; `investigations` holds a title and a list
of `(kind, ref_id, label)` references. Neither is a membership, and nothing
anywhere carries a membership hash. So this is net-new, and the design choice
worth stating is how membership is stored.

NOT AS A LIST OF IDS. A Corporate cohort can be 21,918 facilities, and a JSON
column holding them would make the thread context enormous, slow to read on
every turn, and -- worse -- authoritative. A stale id list that no longer
matches the book would still look like a cohort.

INSTEAD: the PREDICATE plus a HASH of what it selected. The predicate is the
stable server-side reference section 6.1 permits; re-running it re-resolves
the rows, and the hash proves they are the same rows. If the release moves
under the thread, or a filter is edited, or the period rolls, the hash moves
and `CONFIRMATION_STALE` fires with the two digests side by side.

That is also why the hash is over the sorted ids and nothing else. Counts and
totals are recorded beside it for the preview, but they are not the identity:
two different sets of 412 facilities have the same count, and a hash that
included the ECL total would change when the book was merely refreshed.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from backend.cockpit_v4 import domains as dom
from backend.cockpit_v4.scenario import spec as sp
from backend.cockpit_v4.scenario.errors import (
    BOOK_MISMATCH,
    COHORT_UNRESOLVED,
    SOURCE_VERSION_MISMATCH,
    raise_for,
)

#: The relation a stress is measured on, per book. Deliberately the same two
#: as `ecl.py:76-83`: the ECL-bearing grain, and no other.
GRAIN: dict[str, dict[str, str]] = {
    dom.CORPORATE: {"relation": "corp_facility_quarter",
                    "key": "facility_id", "owner": "borrower_id",
                    "noun": "facility", "plural": "facilities",
                    "owner_noun": "borrower", "owner_plural": "borrowers",
                    "period": "reporting_quarter"},
    dom.RETAIL: {"relation": "retail_account_month",
                 "key": "account_id", "owner": "customer_id",
                 "noun": "account", "plural": "accounts",
                 "owner_noun": "customer", "owner_plural": "customers",
                 "period": "reporting_month"},
}

#: What a cohort is a set OF. Section 6.1 is explicit that "the facilities
#: identified" and "all facilities belonging to those borrowers" are
#: different cohorts, and that widening from one to the other needs asking.
BY_ROW = "row"
BY_OWNER = "owner"
SELECTIONS = (BY_ROW, BY_OWNER)


@dataclass(frozen=True)
class Frozen:
    """A resolved membership, and everything the preview says about it."""

    ref: sp.CohortRef
    domain_id: str
    release_id: str
    release_fingerprint: str
    period: str
    predicate: str
    selection: str
    owner_count: int
    #: The reader's own words for this selection, for the audit record.
    described_as: str = ""

    def to_context(self) -> dict[str, Any]:
        """The JSON written to `thread_context`. Small on purpose."""
        return {
            "cohort_id": self.ref.cohort_id,
            "membership_hash": self.ref.membership_hash,
            "domain_id": self.domain_id,
            "release_id": self.release_id,
            "release_fingerprint": self.release_fingerprint,
            "period": self.period,
            "predicate": self.predicate,
            "selection": self.selection,
            "grain": self.ref.grain,
            "entity_count": self.ref.entity_count,
            "owner_count": self.owner_count,
            "baseline_ead": self.ref.baseline_ead,
            "baseline_ecl": self.ref.baseline_ecl,
            "described_as": self.described_as,
            "fixed": self.ref.fixed,
        }

    def describe(self) -> str:
        """One line for the preview, naming the grain rather than implying it.

        Section 6.1: *"Distinguish 'the facilities identified' from 'all
        facilities belonging to those customers'. Default to the actual
        resolved investigation grain and state it."*
        """
        g = GRAIN[self.domain_id]
        rows = f"{self.ref.entity_count:,} {g['plural']}"
        owners = f"{self.owner_count:,} {g['owner_plural']}"
        held = ("every one of their " + g["plural"]
                if self.selection == BY_OWNER else
                "only the " + g["plural"] + " that matched")
        return (f"{rows} across {owners} at {self.period}, {held}. "
                f"Membership is fixed as at this period"
                if self.ref.fixed else
                f"{rows} across {owners} at {self.period}, {held}. "
                f"Membership RE-EVALUATES after the scenario")


def _rows(session: Any, sql: str) -> list[dict[str, Any]]:
    """The same three lines as `ecl._rows`. Kept local rather than imported
    so this package adds no coupling to a protected module."""
    cursor = session.connection.execute(sql)
    names = [c[0] for c in cursor.description]
    return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]


def membership_hash(ids: list[str]) -> str:
    """SHA-256 over the sorted ids, one per line.

    Sorted so the hash is a property of the SET rather than of the order the
    engine happened to return it in, and newline-joined rather than
    concatenated so that ("ab", "c") and ("a", "bc") cannot collide.
    """
    blob = "\n".join(sorted(str(i) for i in ids))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def freeze(*, session: Any, scope: Any, predicate: str = "",
           period: str = "", selection: str = BY_ROW,
           cohort_id: str = "", described_as: str = "",
           fixed: bool = True) -> Frozen:
    """Resolve a selection once, and record what it selected.

    `predicate` is SQL over the ECL-bearing relation, already validated and
    bound by the caller. An empty predicate is the whole book at the period,
    which is what section 6.1's "all" means -- *"all authorized eligible
    records in the active book and declared period, never both books."*
    """
    if session.domain_id != scope.domain_id:
        raise_for(BOOK_MISMATCH,
                  f"a {dom.LABELS.get(scope.domain_id, scope.domain_id)} "
                  f"cohort cannot be frozen from a "
                  f"{dom.LABELS.get(session.domain_id, session.domain_id)} "
                  f"session.",
                  field_path="domain_id")
    if selection not in SELECTIONS:
        raise_for(COHORT_UNRESOLVED,
                  f"{selection!r} is not a selection. A cohort is a set of "
                  f"rows ({BY_ROW}) or of everything its owners hold "
                  f"({BY_OWNER}).",
                  field_path="selection")

    grain = GRAIN.get(scope.domain_id)
    if grain is None:
        raise_for(COHORT_UNRESOLVED,
                  f"no exposure relation is recorded for {scope.domain_id!r}.",
                  field_path="domain_id")

    period = period or scope.latest_period
    where = f"{grain['period']} = '{period}'"
    if predicate:
        where += f" AND ({predicate})"

    if selection == BY_OWNER:
        # Everything those owners hold, not only the rows that matched. A
        # separate query rather than a widened predicate, so the preview can
        # show both numbers and section 6.1's C03 has something to assert on.
        where = (f"{grain['period']} = '{period}' AND {grain['owner']} IN "
                 f"(SELECT {grain['owner']} FROM {grain['relation']} "
                 f"WHERE {where})")

    rows = _rows(session, f"""
        SELECT {grain['key']} AS entity_id, {grain['owner']} AS owner_id,
               ead_sar_mn, ecl_sar_mn
        FROM {grain['relation']}
        WHERE {where}
        ORDER BY {grain['key']}
    """)
    if not rows:
        raise_for(COHORT_UNRESOLVED,
                  f"nothing in the {dom.LABELS.get(scope.domain_id, '')} book "
                  f"at {period} matches this selection, so there is no cohort "
                  f"to stress. An empty selection is not the whole book.",
                  field_path="predicate",
                  predicate=predicate, period=period)

    ids = [str(r["entity_id"]) for r in rows]
    owners = {str(r["owner_id"]) for r in rows}
    ead = sum((Decimal(str(r["ead_sar_mn"] or 0)) for r in rows), Decimal(0))
    ecl = sum((Decimal(str(r["ecl_sar_mn"] or 0)) for r in rows), Decimal(0))
    digest = membership_hash(ids)

    return Frozen(
        ref=sp.CohortRef(
            cohort_id=cohort_id or f"coh-{digest[:12]}",
            membership_hash=digest, grain=grain["noun"],
            entity_count=len(ids), baseline_ead=str(ead),
            baseline_ecl=str(ecl), fixed=fixed),
        domain_id=scope.domain_id,
        release_id=getattr(scope, "release_id", ""),
        release_fingerprint=getattr(scope, "release_fingerprint", ""),
        period=period, predicate=predicate, selection=selection,
        owner_count=len(owners), described_as=described_as)


def reresolve(*, session: Any, scope: Any, stored: dict[str, Any]) -> Frozen:
    """Re-run a stored cohort and prove it still selects the same rows.

    This is what makes the predicate a usable membership reference rather
    than a hopeful one. Every path that reaches a confirmed scenario goes
    through here, so a release that moved under the thread is caught before
    anything is calculated rather than after it is published.
    """
    if stored.get("domain_id") != scope.domain_id:
        raise_for(BOOK_MISMATCH,
                  f"this cohort was frozen in the {stored.get('domain_id')} "
                  f"book and the thread is now in {scope.domain_id}. A "
                  f"scenario cannot span both.",
                  field_path="cohort.domain_id")

    again = freeze(session=session, scope=scope,
                   predicate=str(stored.get("predicate") or ""),
                   period=str(stored.get("period") or ""),
                   selection=str(stored.get("selection") or BY_ROW),
                   cohort_id=str(stored.get("cohort_id") or ""),
                   described_as=str(stored.get("described_as") or ""),
                   fixed=bool(stored.get("fixed", True)))

    was = str(stored.get("membership_hash") or "")
    if was and was != again.ref.membership_hash:
        raise_for(
            SOURCE_VERSION_MISMATCH,
            f"this cohort held {stored.get('entity_count')} "
            f"{GRAIN[scope.domain_id]['plural']} when it was frozen and the "
            f"same selection now returns {again.ref.entity_count}. The rows "
            f"underneath have changed, so the scenario is about a different "
            f"population than the one that was approved.",
            field_path="cohort.membership_hash",
            frozen_hash=was, now_hash=again.ref.membership_hash,
            frozen_count=stored.get("entity_count"),
            now_count=again.ref.entity_count)
    return again


def widened(*, session: Any, scope: Any, frozen: Frozen) -> dict[str, Any]:
    """What widening this cohort to every row its owners hold would add.

    Section 6.1: *"Ask before expanding a facility-level finding to every
    facility of its borrower."* Asking well means showing the cost, so this
    returns the two counts and the two exposures rather than a yes/no.

    Never applied automatically. The caller puts it to the reader.
    """
    if frozen.selection == BY_OWNER:
        return {"already_by_owner": True}
    wider = freeze(session=session, scope=scope, predicate=frozen.predicate,
                   period=frozen.period, selection=BY_OWNER)
    grain = GRAIN[frozen.domain_id]
    added = wider.ref.entity_count - frozen.ref.entity_count
    return {
        "already_by_owner": False,
        "selected": frozen.ref.entity_count,
        "if_widened": wider.ref.entity_count,
        "adds": added,
        "selected_ecl": frozen.ref.baseline_ecl,
        "if_widened_ecl": wider.ref.baseline_ecl,
        "question": (
            f"This selection is {frozen.ref.entity_count:,} "
            f"{grain['plural']}. Every {grain['noun']} belonging to the same "
            f"{wider.owner_count:,} {grain['owner_plural']} would be "
            f"{wider.ref.entity_count:,}, {added:,} more. Which did you "
            f"mean?"),
        "options": [f"Only the {frozen.ref.entity_count:,} that matched",
                    f"All {wider.ref.entity_count:,} of those "
                    f"{grain['owner_plural']}' {grain['plural']}"],
    }


def store_key(thread_id: str) -> str:
    """Where a frozen cohort lives in `thread_context`.

    Namespaced so it cannot collide with anything the accepted runtime keeps
    there, and per-thread because section 6.2 requires switching books to
    preserve distinct context rather than reuse the other book's.
    """
    return f"whatif.cohort:{thread_id}"


def to_json(frozen: Frozen) -> str:
    return json.dumps(frozen.to_context(), sort_keys=True,
                      separators=(",", ":"), ensure_ascii=False)


__all__ = ["BY_OWNER", "BY_ROW", "Frozen", "GRAIN", "SELECTIONS", "freeze",
           "membership_hash", "reresolve", "store_key", "to_json", "widened"]
