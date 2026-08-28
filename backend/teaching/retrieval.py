"""
Which teaching cases a live request gets to see. §16, §17, §48.

Two stages, and only the first one can hurt anybody
---------------------------------------------------
**Hard filters** decide what is *eligible*. Every one of them is a rule about
safety or governance rather than relevance: approved, current version,
language, portfolio scope, permission, not confidential, not from the holdout,
not stale. A bug here puts something in front of a model that should never have
been there, and no amount of good ranking afterwards undoes it.

**Weighted retrieval** decides which of the eligible cases is most useful. A
bug here shows a planner a less helpful example. Worth getting right; not worth
confusing with the first kind.

They are separate functions for that reason, and `eligible` never takes a
relevance score into account.

Hybrid, without a vector service
--------------------------------
§16 asks for governed feature matching, lexical similarity, an optional
embedding interface and diversity reranking — and says not to require a new
external vector service for the first implementation. So:

- feature matching over the sixteen governed features §16 lists, weighted;
- BM25 over the candidate questions, computed on the candidate set itself;
- an `Embedder` protocol that is used when supplied and absent otherwise;
- a rerank that admits at most one case per paraphrase cluster (§17).

The embedding interface takes text, never rows. A question is not client data
in the sense §47 means, but a result is, and nothing here can reach one.

Why the output says why
-----------------------
§17 asks for `matched_features` and `why_retrieved`. Retrieval that cannot
explain itself cannot be debugged: "the planner used a bad example" is
unactionable, and "it matched on family and grain and nothing else" is a fix.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from backend.teaching import families as fam
from backend.teaching import pack as tp
from backend.teaching import schema as sc
from backend.teaching import status as st

RETRIEVAL_VERSION = "1.0.0"

#: §17: zero to five cases. Never more, whatever the scores look like — a
#: sixth example costs budget the plan skeleton needs more.
MAX_CASES = 5

#: The relevance a case has to clear to be shown at all. §17: "3-5 only when
#: sufficiently relevant. Do not force irrelevant examples." An empty pack is
#: a better prompt than a misleading one.
FLOOR = 0.18

#: How the two scorers are blended when there is no embedder. Governed feature
#: matching leads because it is the half that knows what a credit-risk case IS;
#: lexical similarity is what catches a case whose features were recorded
#: thinly.
FEATURE_WEIGHT = 0.7
LEXICAL_WEIGHT = 0.3
#: When an embedder is supplied, it takes a share of the lexical half rather
#: than of the governed half.
EMBED_SHARE = 0.5

#: A second case from the same family is worth less than the first: five cases
#: from one family teach one thing five times. Not a hard limit — sometimes
#: five ECL decomposition examples ARE the right prompt — but a thumb on the
#: scale towards variety.
FAMILY_DECAY = 0.85

#: §16's weighted retrieval features. The weights say what a credit-risk
#: example is USEFUL for: the concepts and the capability are why a case is
#: relevant at all; the difficulty and the route are tiebreakers.
WEIGHTS: dict[str, float] = {
    "capability": 3.0,
    "conversation_action": 2.0,
    "family": 2.5,
    "concepts": 3.0,
    "objective_kinds": 1.0,
    "domains": 1.5,
    "datasets": 2.0,
    "relationships": 1.5,
    "grain": 1.5,
    "period": 1.0,
    "operations": 1.5,
    "ambiguity": 2.0,
    "discourse": 2.5,
    "visualization": 1.5,
    "route": 1.0,
    "difficulty": 0.75,
    "risk": 0.75,
}

#: A case that teaches what happens when a corporate question meets a retail
#: case. §48 admits exactly this exception, so it needs a marker a reviewer
#: sets deliberately rather than a heuristic that guesses.
SCOPE_VIOLATION_TAG = "scope-violation"

_WORD = re.compile(r"[a-z0-9]{2,}")
_STOP = frozenset({
    "the", "and", "for", "with", "what", "which", "show", "has", "have",
    "how", "much", "many", "that", "this", "them", "those", "these", "over",
    "into", "from", "are", "was", "were", "does", "did", "you", "your", "our",
    "all", "any", "its", "his", "her", "their", "been", "than", "then",
    "there", "here", "just", "also", "only", "more", "most", "each", "both",
    "same", "give", "tell", "latest", "period", "quarter", "year",
})


class Embedder(Protocol):
    """A provider-neutral embedding interface. §16.

    Takes text and returns vectors. Nothing else — in particular no rows, no
    results, and no handle on anything that could reach them.
    """

    def embed(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        ...


@dataclass(frozen=True)
class Need:
    """What the live request is asking for.

    Assembled by the caller from the structured reading, so retrieval never
    parses a question to work out what it is about. The one thing it does read
    as text is the question itself, for the lexical half.
    """

    question: str = ""
    capability: str = ""
    conversation_action: str = ""
    family: str = ""
    concepts: tuple[str, ...] = ()
    objective_kinds: tuple[str, ...] = ()
    domains: tuple[str, ...] = ()
    datasets: tuple[str, ...] = ()
    relationships: tuple[str, ...] = ()
    operations: tuple[str, ...] = ()
    grain: str = ""
    period: str = ""
    ambiguous: bool = False
    #: The same-turn referents the message actually contains (§10).
    discourse: tuple[str, ...] = ()
    visualization: str = ""
    route: str = ""
    difficulty: str = ""
    risk_level: str = ""
    language: str = "en"
    locale: str = ""
    portfolio_scope: str = fam.NO_SCOPE


@dataclass(frozen=True)
class Permission:
    """What this caller is allowed to be shown.

    Separate from `Need` because it is not about the question. A user's
    permissions do not change what a question is asking for, and folding the
    two together is how a permission check ends up depending on a reading.
    """

    #: None means every family. A set restricts to those families.
    families: frozenset[str] | None = None
    #: §5: SYSTEM_VALIDATED enters production retrieval only where governed.
    system_validated: bool = False
    #: The most demanding difficulty this caller may be shown. Empty means all.
    max_difficulty: str = ""


@dataclass(frozen=True)
class Retrieved:
    """§17's output, field for field."""

    case_id: str
    case_version: int
    relevance_score: float
    matched_features: tuple[str, ...]
    why_retrieved: str
    diversity_cluster: str
    estimated_tokens: int
    approved_status: str
    ontology_version: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id, "case_version": self.case_version,
            "relevance_score": round(self.relevance_score, 4),
            "matched_features": list(self.matched_features),
            "why_retrieved": self.why_retrieved,
            "diversity_cluster": self.diversity_cluster,
            "estimated_tokens": self.estimated_tokens,
            "approved_status": self.approved_status,
            "ontology_version": self.ontology_version,
        }


@dataclass
class Result:
    """What retrieval decided, and what it excluded on the way.

    `refused` is the half worth keeping: a request that retrieves nothing is
    normal, and the only way to tell a correct nothing from a broken one is to
    see which filter did it.
    """

    cases: list[sc.TeachingCase] = field(default_factory=list)
    entries: list[Retrieved] = field(default_factory=list)
    refused: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"retrieved": [e.to_dict() for e in self.entries],
                "refused": dict(self.refused)}


# ---------------------------------------------------------------------------
# Stage one — eligibility
# ---------------------------------------------------------------------------

def _scope_ok(case: sc.TeachingCase, need: Need) -> bool:
    """§48's corporate/retail safety.

    Three rules, and the third is the one that is easy to get wrong: a
    scope-neutral case is only safe when it is neutral in its *semantics*, not
    merely in its label. A case marked NONE that names a retail product is a
    retail case whose scope field was left at the default.
    """
    asked = str(need.portfolio_scope or fam.NO_SCOPE).upper()
    held = str(case.portfolio_scope or fam.NO_SCOPE).upper()

    if SCOPE_VIOLATION_TAG in case.tags:
        # A case whose lesson IS the mismatch. §48 admits exactly this.
        return True
    if asked == fam.NO_SCOPE or held == fam.NO_SCOPE:
        if held == fam.NO_SCOPE and case.industry_or_product_scope and \
                asked != fam.NO_SCOPE:
            return False
        return True
    return asked == held


def _language_ok(case: sc.TeachingCase, need: Need) -> bool:
    """Language must match; locale narrows but never blocks.

    A case written for en-SA is useful to an en-AE question — the analysis is
    the same and the vocabulary is the same. A case written in Arabic is not
    useful to an English question at all, which is why the two are treated
    differently rather than both being "compatible".
    """
    wanted = str(need.language or "en").lower()
    held = str(case.language or "en").lower()
    if held != wanted:
        return False
    if need.locale and case.locale and case.locale != need.locale:
        return True
    return True


def eligible(cases: Iterable[sc.TeachingCase], need: Need, *,
             permission: Permission | None = None
             ) -> tuple[list[sc.TeachingCase], dict[str, int]]:
    """§16's hard filters, and a count of what each one refused.

    Every rule here is about safety or governance. None of them looks at
    relevance, and none of them can be overridden by a good score.
    """
    permission = permission or Permission()
    kept: list[sc.TeachingCase] = []
    refused: Counter[str] = Counter()

    for case in cases:
        verdict = st.retrievable(
            case.review_status,
            system_validated_enabled=permission.system_validated,
            sensitivity=case.data_sensitivity)
        if not verdict:
            refused[verdict.reason] += 1
            continue
        if case.data_sensitivity != st.PUBLIC:
            # A DIAGNOSTIC case may carry the exact values that validate a
            # method (§8), and those are "never given to the live planner
            # before execution". The status check above lets DIAGNOSTIC
            # through; this is the rule that stops it.
            refused["not structure-only"] += 1
            continue
        if "holdout" in (case.source_provenance or "").lower():
            refused["holdout source"] += 1
            continue
        if not _language_ok(case, need):
            refused["language"] += 1
            continue
        if not _scope_ok(case, need):
            refused["portfolio scope"] += 1
            continue
        if permission.families is not None and \
                case.family_id not in permission.families:
            refused["permission"] += 1
            continue
        if permission.max_difficulty and \
                _harder(case.difficulty, permission.max_difficulty):
            refused["difficulty"] += 1
            continue
        kept.append(case)

    return kept, dict(refused)


def _harder(difficulty: str, ceiling: str) -> bool:
    order = list(sc.DIFFICULTIES)
    try:
        return order.index(difficulty) > order.index(ceiling)
    except ValueError:
        # An unrecognised difficulty is treated as harder than any ceiling,
        # for the same reason an unrecognised assurance status is lowered:
        # unknown must fail closed, not slip through the comparison.
        return True


# ---------------------------------------------------------------------------
# Stage two — relevance
# ---------------------------------------------------------------------------

def _overlap(left: Iterable[str], right: Iterable[str]) -> float:
    """How much of what was asked for the case actually covers.

    Deliberately asymmetric: the denominator is what the NEED asked for, so a
    case covering both requested concepts scores 1.0 whether it mentions three
    others or none. A symmetric measure would prefer thin cases.
    """
    wanted = {str(x).strip().lower() for x in right if str(x).strip()}
    if not wanted:
        return 0.0
    held = {str(x).strip().lower() for x in left if str(x).strip()}
    return len(wanted & held) / len(wanted)


def features(case: sc.TeachingCase, need: Need) -> dict[str, float]:
    """Each of §16's features, scored 0 to 1."""
    scored: dict[str, float] = {}

    if need.capability:
        scored["capability"] = float(
            case.expected_capability == need.capability)
    if need.conversation_action:
        scored["conversation_action"] = float(
            case.expected_conversation_action == need.conversation_action)
    if need.family:
        scored["family"] = float(case.family_id == need.family)
    if need.concepts:
        scored["concepts"] = _overlap(case.concepts + case.metrics,
                                      need.concepts)
    if need.objective_kinds:
        scored["objective_kinds"] = _overlap(
            [o.kind for o in case.objectives], need.objective_kinds)
    if need.domains:
        scored["domains"] = _overlap(case.candidate_domains, need.domains)
    if need.datasets:
        scored["datasets"] = _overlap(case.required_datasets, need.datasets)
    if need.relationships:
        scored["relationships"] = _overlap(case.required_relationships,
                                           need.relationships)
    if need.operations:
        scored["operations"] = _overlap(case.operations, need.operations)
    if need.grain:
        scored["grain"] = float(case.grain == need.grain)
    if need.period:
        held = str(case.period_contract.get("phrase") or "").lower()
        scored["period"] = float(bool(held) and held == need.period.lower())
    if need.ambiguous:
        scored["ambiguity"] = float(bool(case.ambiguities)
                                    or case.expected_outcome == fam.CLARIFY)
    if need.discourse:
        scored["discourse"] = float(
            bool(case.same_turn_discourse.referents))
    if need.visualization:
        scored["visualization"] = float(bool(case.visualization_contract))
    if need.route:
        scored["route"] = float(case.expected_model_route == need.route)
    if need.difficulty:
        scored["difficulty"] = float(case.difficulty == need.difficulty)
    if need.risk_level:
        scored["risk"] = float(case.risk_level == need.risk_level)

    return scored


def _feature_score(scored: dict[str, float]) -> float:
    """The weighted average over the features the NEED declared.

    Averaged over what was asked, not over all sixteen: a request that only
    knows its capability and concepts must not be penalised for the fourteen
    features it said nothing about.
    """
    total = sum(WEIGHTS[name] for name in scored)
    if not total:
        return 0.0
    return sum(WEIGHTS[name] * value for name, value in scored.items()) / total


def _terms(text: str) -> list[str]:
    return [w for w in _WORD.findall(str(text or "").lower())
            if w not in _STOP]


def _bm25(need: Need, cases: Sequence[sc.TeachingCase],
          *, k1: float = 1.5, b: float = 0.75) -> list[float]:
    """Lexical similarity over the candidate set.

    BM25 computed on the candidates rather than on the whole library, because
    the eligible set is what the ranking is over and an IDF taken from the
    whole library would be dominated by families this request cannot see.
    """
    query = _terms(need.question)
    if not query or not cases:
        return [0.0] * len(cases)

    documents = [_terms(c.question) + _terms(c.title) for c in cases]
    lengths = [len(d) or 1 for d in documents]
    average = sum(lengths) / len(lengths)
    frequency = Counter(term for document in documents
                        for term in set(document))
    count = len(documents)

    scores: list[float] = []
    for document, length in zip(documents, lengths, strict=True):
        counts = Counter(document)
        total = 0.0
        for term in query:
            if term not in counts:
                continue
            idf = math.log(1 + (count - frequency[term] + 0.5)
                           / (frequency[term] + 0.5))
            weighted = counts[term] * (k1 + 1) / (
                counts[term] + k1 * (1 - b + b * length / average))
            total += idf * weighted
        scores.append(total)

    top = max(scores) or 1.0
    return [s / top for s in scores]


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    if not left or not right:
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=False))
    size = math.sqrt(sum(a * a for a in left)) * \
        math.sqrt(sum(b * b for b in right))
    return dot / size if size else 0.0


def _embedding_scores(need: Need, cases: Sequence[sc.TeachingCase],
                      embedder: Embedder) -> list[float]:
    """Cosine similarity, when an embedder is supplied.

    Failure here is not a failure of retrieval: an embedding service that is
    down means the governed and lexical halves decide alone, which is the
    behaviour with no embedder at all.
    """
    try:
        vectors = list(embedder.embed([need.question,
                                       *(c.question for c in cases)]))
    except Exception:  # noqa: BLE001 - an optional scorer must not break it
        return [0.0] * len(cases)
    if len(vectors) != len(cases) + 1:
        return [0.0] * len(cases)
    query, rest = vectors[0], vectors[1:]
    return [max(0.0, _cosine(query, vector)) for vector in rest]


def _why(scored: dict[str, float]) -> tuple[tuple[str, ...], str]:
    """The matched features, and the sentence §17 asks for."""
    matched = tuple(name for name, value in sorted(
        scored.items(), key=lambda pair: -pair[1]) if value > 0)
    if not matched:
        return (), "matched on wording only"
    return matched, "matched on " + ", ".join(matched[:4])


def rank(cases: Sequence[sc.TeachingCase], need: Need, *,
         embedder: Embedder | None = None,
         limit: int = MAX_CASES, floor: float = FLOOR) -> Result:
    """The eligible cases, scored and reranked. §16 and §17.

    Assumes `eligible` has already run: this function has no safety rules in
    it, and adding one here would put a governance decision behind a relevance
    threshold.
    """
    result = Result()
    if not cases:
        return result

    lexical = _bm25(need, cases)
    embedded = (_embedding_scores(need, cases, embedder) if embedder
                else [0.0] * len(cases))
    lexical_weight = LEXICAL_WEIGHT * (1 - EMBED_SHARE if embedder else 1.0)
    embed_weight = LEXICAL_WEIGHT * EMBED_SHARE if embedder else 0.0

    scored: list[tuple[float, sc.TeachingCase, dict[str, float]]] = []
    for case, lex, emb in zip(cases, lexical, embedded, strict=True):
        matched = features(case, need)
        total = (FEATURE_WEIGHT * _feature_score(matched)
                 + lexical_weight * lex + embed_weight * emb)
        scored.append((total, case, matched))

    scored.sort(key=lambda row: (-row[0], row[1].case_id))

    seen_clusters: set[str] = set()
    seen_families: Counter[str] = Counter()
    for total, case, matched in scored:
        if len(result.cases) >= int(limit):
            break
        cluster = case.cluster_id or case.fingerprint
        if cluster in seen_clusters:
            # §17: at most one case per paraphrase cluster. Five wordings of
            # one question is one example repeated five times.
            result.refused["duplicate cluster"] = \
                result.refused.get("duplicate cluster", 0) + 1
            continue
        adjusted = total * (FAMILY_DECAY ** seen_families[case.family_id])
        if adjusted < float(floor):
            result.refused["below relevance floor"] = \
                result.refused.get("below relevance floor", 0) + 1
            continue

        seen_clusters.add(cluster)
        seen_families[case.family_id] += 1
        names, why = _why(matched)
        built = tp.make(case)
        result.cases.append(case)
        result.entries.append(Retrieved(
            case_id=case.case_id, case_version=case.case_version,
            relevance_score=adjusted, matched_features=names,
            why_retrieved=why, diversity_cluster=cluster,
            estimated_tokens=built.estimated_tokens() if built else 0,
            approved_status=case.review_status,
            ontology_version=case.ontology_version))

    # The family decay is applied after sorting, so the order the scores were
    # computed in is not the order they rank in. Reported out of order, a
    # caller reading the top entry would not be reading the top case.
    order = sorted(range(len(result.entries)),
                   key=lambda i: -result.entries[i].relevance_score)
    result.entries = [result.entries[i] for i in order]
    result.cases = [result.cases[i] for i in order]
    return result


def retrieve(cases: Iterable[sc.TeachingCase], need: Need, *,
             permission: Permission | None = None,
             embedder: Embedder | None = None,
             limit: int = MAX_CASES, floor: float = FLOOR) -> Result:
    """Both stages, in the order that matters."""
    kept, refused = eligible(cases, need, permission=permission)
    result = rank(kept, need, embedder=embedder, limit=limit, floor=floor)
    for reason, count in refused.items():
        result.refused[reason] = result.refused.get(reason, 0) + count
    return result


__all__ = ["EMBED_SHARE", "FAMILY_DECAY", "FEATURE_WEIGHT", "FLOOR",
           "LEXICAL_WEIGHT", "MAX_CASES", "RETRIEVAL_VERSION",
           "SCOPE_VIOLATION_TAG", "WEIGHTS", "Embedder", "Need", "Permission",
           "Result", "Retrieved", "eligible", "features", "rank", "retrieve"]
