"""Entity resolution across source systems. B7.

Three source systems disagree about who a company is, because they were
populated at different times by different people for different reasons: the
core banking system knows the account holder, the CRM knows the relationship,
and the commercial registry knows the legal entity. Resolution decides which
of their records are the same company.

FRAMEWORK.md's precedence, implemented in order
-----------------------------------------------
1. **Exact commercial-registration or national-ID match.** Deterministic and
   auto-accepted: two records carrying the same CR number are the same
   company, and nothing softer should be allowed to overturn that.
2. **Normalised name plus address, or a CR-prefix agreement.** Strong but not
   certain - two subsidiaries of one group can share a registered address and
   a name stem. Auto-accepted above a confidence floor, queued below it.
3. **Fuzzy name plus a shared director.** Never auto-accepted. It goes to a
   human, because this is precisely the rule that merges two unrelated family
   companies with common surnames and a common non-executive director, and a
   wrong merge here silently doubles one borrower's exposure and deletes
   another's.

What this deliberately does NOT do
-----------------------------------
It does not merge source records. The mapping is additive: every source
record stays exactly as its system holds it, and `canonical_entity_id` is a
new column alongside, never a replacement. A destructive merge cannot be
undone when the match turns out to be wrong, and matches at precedence 3 turn
out to be wrong often enough that the ability to undo them is the point.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import numpy as np
import pandas as pd

from backend.corporate import ORIGIN

logger = logging.getLogger(__name__)

RESOLUTION_VERSION = "1.0.0"

# ------------------------------------------------------------ source systems

CORE_BANKING = "CORE_BANKING"
CRM = "CRM"
REGISTRY = "COMMERCIAL_REGISTRY"

SOURCE_SYSTEMS: tuple[str, ...] = (CORE_BANKING, CRM, REGISTRY)

# ------------------------------------------------------------ methods

EXACT_REGISTRATION = "EXACT_REGISTRATION_ID"
NAME_AND_ADDRESS = "NORMALISED_NAME_AND_ADDRESS"
REGISTRATION_PREFIX = "REGISTRATION_PREFIX_EVIDENCE"
FUZZY_NAME_AND_DIRECTOR = "FUZZY_NAME_AND_SHARED_DIRECTOR"
SINGLE_SOURCE = "SINGLE_SOURCE_RECORD"

#: Precedence, strongest first. The order is the rule: a record matched at a
#: stronger method is never re-decided by a weaker one.
PRECEDENCE: tuple[str, ...] = (
    EXACT_REGISTRATION, NAME_AND_ADDRESS, REGISTRATION_PREFIX,
    FUZZY_NAME_AND_DIRECTOR,
)

#: Confidence each method carries, and whether it may be accepted without a
#: human. Fuzzy matching is never auto-accepted at any confidence.
METHOD: dict[str, tuple[float, bool]] = {
    EXACT_REGISTRATION: (0.99, True),
    NAME_AND_ADDRESS: (0.88, True),
    REGISTRATION_PREFIX: (0.74, True),
    FUZZY_NAME_AND_DIRECTOR: (0.61, False),
    SINGLE_SOURCE: (1.00, True),
}

#: Below this, even an auto-acceptable method waits for a human.
AUTO_ACCEPT_FLOOR = 0.70

AUTO_ACCEPTED = "AUTO_ACCEPTED"
PENDING_REVIEW = "PENDING_REVIEW"
HUMAN_CONFIRMED = "HUMAN_CONFIRMED"
HUMAN_REJECTED = "HUMAN_REJECTED"

REVIEW_STATES: tuple[str, ...] = (
    AUTO_ACCEPTED, PENDING_REVIEW, HUMAN_CONFIRMED, HUMAN_REJECTED,
)

_NOISE = re.compile(
    r"\b(company|co|llc|ltd|limited|est|establishment|group|holding|"
    r"holdings|corporation|corp|inc|plc|jsc)\b")
_PUNCT = re.compile(r"[^a-z0-9 ]+")
_SPACE = re.compile(r"\s+")


def normalise(name: str) -> str:
    """A name reduced to what two systems would agree on.

    Legal-form words are removed, not just lowercased: "Al Waha Trading LLC"
    and "Al Waha Trading Company" are the same company recorded by two systems
    with different conventions, and a comparison that keeps the suffix decides
    they are not.
    """
    text = _PUNCT.sub(" ", str(name).lower())
    text = _NOISE.sub(" ", text)
    return _SPACE.sub(" ", text).strip()


def _shuffle_name(name: str, rng: np.random.Generator) -> str:
    """How a source system mangles a name it typed by hand."""
    choice = rng.integers(0, 4)
    if choice == 0:
        return name.upper()
    if choice == 1:
        return name.replace(" Company", " Co.")
    if choice == 2:
        return name.replace("Al ", "AL-")
    return f"{name} LLC"


def build(entities: pd.DataFrame, edges: pd.DataFrame,
          rng: np.random.Generator) -> pd.DataFrame:
    """Source records and the canonical entity each resolves to. B7.

    Returns one row per SOURCE RECORD, not per entity: the mapping is what is
    being recorded, and a table with one row per entity could not express a
    record that has not been resolved yet.
    """
    borrowers = entities["borrower_id"].to_numpy()
    legal = entities["legal_name"].to_numpy()
    cr = entities["cr_number"].to_numpy()
    n = len(borrowers)

    address_of = dict(zip(
        edges.loc[edges["edge_type"] == "REGISTERED_AT", "from_node"],
        edges.loc[edges["edge_type"] == "REGISTERED_AT", "to_node"],
        strict=True))

    rows: list[dict[str, Any]] = []
    counter = 0

    for position in range(n):
        canonical = str(borrowers[position])
        name = str(legal[position])
        registration = str(cr[position])
        address = address_of.get(canonical, "")

        # The registry record. Always present, always carries the CR number,
        # and is therefore always the anchor.
        counter += 1
        rows.append(_record(
            counter, REGISTRY, f"REG-{registration}", canonical, name,
            registration, address, EXACT_REGISTRATION, rng))

        # The core banking record. Usually carries the CR number too.
        counter += 1
        has_cr = rng.random() < 0.82
        rows.append(_record(
            counter, CORE_BANKING, f"CBS-{700000 + position}", canonical,
            _shuffle_name(name, rng),
            registration if has_cr else "",
            address if rng.random() < 0.86 else "",
            EXACT_REGISTRATION if has_cr else NAME_AND_ADDRESS, rng))

        # A CRM record for about two thirds of borrowers. The CRM is where
        # names are typed by hand, so it is where the hard matches live.
        if rng.random() < 0.66:
            counter += 1
            draw = rng.random()
            if draw < 0.30:
                method = EXACT_REGISTRATION
                record_cr = registration
            elif draw < 0.62:
                method = NAME_AND_ADDRESS
                record_cr = ""
            elif draw < 0.80:
                method = REGISTRATION_PREFIX
                record_cr = registration[:6]
            else:
                method = FUZZY_NAME_AND_DIRECTOR
                record_cr = ""
            rows.append(_record(
                counter, CRM, f"CRM-{900000 + position}", canonical,
                _shuffle_name(name, rng), record_cr,
                address if method != FUZZY_NAME_AND_DIRECTOR else "",
                method, rng))

    frame = pd.DataFrame(rows)

    # A human has looked at some of the queue. The rest is genuinely pending,
    # which is the honest state for a resolution nobody has confirmed.
    pending = frame["review_status"] == PENDING_REVIEW
    reviewed = pending & (rng.random(len(frame)) < 0.55)
    # Roughly a fifth of fuzzy matches are rejected on review. That number is
    # the reason the method is never auto-accepted.
    rejected = reviewed & (rng.random(len(frame)) < 0.19)
    frame.loc[reviewed & ~rejected, "review_status"] = HUMAN_CONFIRMED
    frame.loc[rejected, "review_status"] = HUMAN_REJECTED
    # A rejected match does not resolve to anything. Left explicitly empty
    # rather than pointed at a guess.
    frame.loc[rejected, "canonical_entity_id"] = ""
    return frame


def _record(counter: int, system: str, source_id: str, canonical: str,
            name: str, registration: str, address: str, method: str,
            rng: np.random.Generator) -> dict[str, Any]:
    confidence, auto = METHOD[method]
    # Confidence varies a little around the method's base, so a review queue
    # sorted by confidence has something to sort.
    confidence = float(np.clip(confidence + rng.normal(0, 0.035), 0.35, 0.995))
    status = (AUTO_ACCEPTED if auto and confidence >= AUTO_ACCEPT_FLOOR
              else PENDING_REVIEW)
    return {
        "resolution_id": f"ER-{counter:07d}",
        "source_system": system,
        "source_entity_id": source_id,
        "canonical_entity_id": canonical,
        "source_legal_name": name,
        "normalised_name": normalise(name),
        "source_registration_number": registration,
        "source_address_node": address,
        "resolution_method": method,
        "confidence": round(confidence, 3),
        "review_status": status,
        "auto_acceptable_method": auto,
        "merged_destructively": False,
        "origin": ORIGIN,
    }


def summary(frame: pd.DataFrame) -> dict[str, Any]:
    """B7, for a report or the data-quality screen."""
    resolved = frame[frame["canonical_entity_id"] != ""]
    return {
        "resolution_version": RESOLUTION_VERSION,
        "source_records": len(frame),
        "source_systems": {
            str(k): int(v) for k, v
            in frame["source_system"].value_counts().items()},
        "canonical_entities": int(resolved["canonical_entity_id"].nunique()),
        "by_method": {
            str(k): int(v) for k, v
            in frame["resolution_method"].value_counts().items()},
        "by_review_status": {
            str(k): int(v) for k, v
            in frame["review_status"].value_counts().items()},
        "pending_review": int(
            (frame["review_status"] == PENDING_REVIEW).sum()),
        "rejected": int((frame["review_status"] == HUMAN_REJECTED).sum()),
        "unresolved_source_records": int(
            (frame["canonical_entity_id"] == "").sum()),
        "destructive_merges": int(frame["merged_destructively"].sum()),
        "precedence": list(PRECEDENCE),
        "never_auto_accepted": [
            m for m, (_, auto) in METHOD.items() if not auto],
        "origin": ORIGIN,
    }
