"""
What CreditProbe knows about credit risk, as governed contracts rather than
model recall.

`backend.orchestration.concepts` says where a concept lives — which dataset,
which column, which one is default. This package says what the concept *means*
and what may be done with it: whether a bare mention is answerable at all,
which direction is deterioration, which operations are legitimate, and which
arithmetic facts must hold about any result that claims to report it.

The split is deliberate. A field map is a lookup; a semantic contract is a
governance object with a version, and it is the version that lets a demo be
certified against a fixed understanding of "exposure".
"""

from __future__ import annotations

from backend.semantics.ontology import (
    ONTOLOGY_VERSION,
    Ambiguity,
    SemanticContract,
    ambiguity_for,
    contract,
    contracts,
    deterioration,
    fingerprint,
    invariants_for,
)

__all__ = [
    "ONTOLOGY_VERSION",
    "Ambiguity",
    "SemanticContract",
    "ambiguity_for",
    "contract",
    "contracts",
    "deterioration",
    "fingerprint",
    "invariants_for",
]
