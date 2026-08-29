"""
Paraphrase and variant generation, and the cluster that keeps them honest.
§14, §15.

The two sections are one mechanism
-----------------------------------
§14 makes variants. §15 stops them taking over. Separating them in code would
let one ship without the other, and a variant generator without duplicate
control is a machine for turning one reviewed case into forty near-identical
retrieval candidates that crowd out everything the planner has not seen.

So a variant is born inside a cluster, and the cluster is the unit retrieval
diversity works on.

What a variant may inherit
--------------------------
§14 lists four conditions, and a variant that meets all four inherits the
canonical case's structured target unchanged. That is the whole value: one
reviewed specification, many phrasings, no second review.

    semantic equivalence · unchanged objective set · no new ambiguity ·
    period and grain semantics preserved

Anything else is SME_REVIEW_REQUIRED. Not rejected — §14 says mark it, and a
variant a validator cannot vouch for is frequently the most interesting one in
the batch, because it found a phrasing where the structure genuinely changes.

The transforms are deliberately unglamorous
--------------------------------------------
Formal and conversational wording, abbreviations, typos, omitted subjects,
reordered clauses, banking jargon. §14 also lists changed periods, entities and
thresholds — those change the SUBJECT rather than the phrasing, so they produce
a variant whose expected result differs and cannot inherit the target. They are
implemented, and they are marked for review by construction.

Nothing here calls a model. §14 says "governed variant-generation pipeline",
and a rule-based generator is governed in a way a model is not: every
transform is a function somebody can read, and a variant that came out wrong
has a line number.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from backend.teaching import schema as sc
from backend.teaching import status as st
from intelligence_factory.teaching import canonical as cn
from intelligence_factory.teaching import migrate

VARIANT_VERSION = "1.0.0"

#: How many variants one canonical case may contribute to the library. §15's
#: "prevent near-duplicate flooding", as a number: retrieval admits one case
#: per cluster, so a cluster of forty is thirty-nine cases that can never be
#: retrieved while the fortieth exists.
MAX_PER_CASE = 4


# ---------------------------------------------------------------------------
# The transforms
# ---------------------------------------------------------------------------

#: Formal register. The phrasing a credit memo uses.
_FORMAL: tuple[tuple[str, str], ...] = (
    (r"\bshow me\b", "provide"),
    (r"\bshow\b", "present"),
    (r"\bwhat is\b", "state the"),
    (r"\bhow much\b", "what quantum of"),
    (r"\btell me\b", "report"),
    (r"\bgive me\b", "provide"),
    (r"\bfind\b", "identify"),
    (r"\bwhich\b", "which of the"),
)

#: Conversational register. What somebody types in a hurry.
_CASUAL: tuple[tuple[str, str], ...] = (
    (r"\bidentify\b", "find"),
    (r"\bprovide\b", "give me"),
    (r"\bpresent\b", "show"),
    (r"\bcalculate\b", "work out"),
    (r"\bdetermine\b", "figure out"),
    (r"\bwhat is the\b", "what's the"),
    (r"\bit is\b", "it's"),
)

#: Banking abbreviations. Every one of these is a real alias in the ontology,
#: so a variant using them tests alias resolution rather than inventing a word.
_ABBREVIATIONS: tuple[tuple[str, str], ...] = (
    (r"\bexposure at default\b", "EAD"),
    (r"\bexpected credit loss\b", "ECL"),
    (r"\bdebt service coverage ratio\b", "DSCR"),
    (r"\bdays past due\b", "DPD"),
    (r"\btwelve-month pd\b", "12m PD"),
    (r"\bloan-to-value\b", "LTV"),
    (r"\bprobability of default\b", "PD"),
    (r"\bloss given default\b", "LGD"),
)

#: Banking jargon — the words an experienced credit officer actually uses.
_JARGON: tuple[tuple[str, str], ...] = (
    (r"\bborrowers?\b", "obligors"),
    (r"\bcustomers?\b", "names"),
    (r"\bthe portfolio\b", "the book"),
    (r"\bworsening\b", "deteriorating"),
    (r"\bgot worse\b", "deteriorated"),
    (r"\bexposure\b", "outstandings"),
)

#: Typos a keyboard actually produces: adjacent-key slips and doubled letters,
#: not random noise. A corpus of random noise measures nothing anybody types.
_TYPOS: tuple[tuple[str, str], ...] = (
    (r"\bthe\b", "teh"),
    (r"\bwhich\b", "whcih"),
    (r"\bexposure\b", "exposre"),
    (r"\bsector\b", "secotr"),
    (r"\bportfolio\b", "portfolo"),
    (r"\bborrowers\b", "borowers"),
)


def _apply(question: str, rules: tuple[tuple[str, str], ...],
           limit: int = 2) -> str:
    """Apply up to `limit` substitutions. Applying every rule at once produces
    a sentence nobody would write, which teaches nothing about the sentences
    people do write."""
    out = str(question or "")
    used = 0
    for pattern, replacement in rules:
        if used >= limit:
            break
        new = re.sub(pattern, replacement, out, count=1, flags=re.I)
        if new != out:
            out = new
            used += 1
    return _sentence(out)


def _sentence(text: str) -> str:
    """A substitution at the start of a sentence leaves it lower-cased, and a
    corpus of questions beginning with a small letter teaches the model that
    the corpus was generated."""
    stripped = str(text or "").lstrip()
    if not stripped:
        return text
    return stripped[0].upper() + stripped[1:]


def formal(question: str) -> str:
    return _apply(question, _FORMAL)


def casual(question: str) -> str:
    return _apply(question, _CASUAL)


def abbreviated(question: str) -> str:
    return _apply(question, _ABBREVIATIONS, limit=3)


def jargon(question: str) -> str:
    return _apply(question, _JARGON)


def typo(question: str) -> str:
    return _apply(question, _TYPOS, limit=1)


def omit_subject(question: str) -> str:
    """Drop the leading interrogative. "Which borrowers have X?" → "Borrowers
    with X?" — the elliptical form people type when they are in a hurry."""
    text = str(question or "").strip()
    match = re.match(r"^(?:what is|what are|which|show me|show|give me|tell me"
                     r"|please\s+\w+)\s+(.*)$", text, re.I)
    if not match:
        return text
    rest = match.group(1)
    return rest[:1].upper() + rest[1:] if rest else text


def reorder(question: str) -> str:
    """Move a trailing period phrase to the front. Reordering clauses is §14's
    transform; doing it on the PERIOD is the safe version, because a fronted
    adverbial does not change what is being asked."""
    text = str(question or "").strip()
    match = re.search(r",?\s+(in|for|over|during|as at)\s+"
                      r"((?:the\s+)?(?:latest|prior|last)\s+\w+"
                      r"|Q[1-4]\s+20\d\d)\s*\??$", text, re.I)
    if not match:
        return text
    stem = text[:match.start()].rstrip(" ,")
    lead = f"{match.group(1)} {match.group(2)}".capitalize()
    tail = "?" if text.rstrip().endswith("?") else ""
    return f"{lead}, {stem[:1].lower()}{stem[1:]}{tail}"


#: A transform, and whether the variant it produces may inherit the canonical
#: case's structured target. `preserves` is the §14 test in one flag: a
#: transform that changes only the phrasing preserves the target; one that
#: changes the subject cannot, whatever the semantic validator says.
@dataclass(frozen=True)
class Transform:
    id: str
    label: str
    apply: Callable[[str], str]
    preserves: bool = True
    note: str = ""


TRANSFORMS: tuple[Transform, ...] = (
    Transform("formal", "Formal wording", formal),
    Transform("casual", "Conversational wording", casual),
    Transform("abbreviated", "Banking abbreviations", abbreviated),
    Transform("jargon", "Banking jargon", jargon),
    Transform("omitted_subject", "Omitted subject", omit_subject),
    Transform("reordered", "Reordered clauses", reorder),
    Transform("typo", "Typo", typo),
)

BY_ID: dict[str, Transform] = {t.id: t for t in TRANSFORMS}


# ---------------------------------------------------------------------------
# §14's four conditions
# ---------------------------------------------------------------------------

@dataclass
class Judgement:
    """Whether a variant may inherit its canonical case's target."""

    inherits: bool
    reasons: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return self.inherits


#: Words whose appearance introduces an ambiguity the canonical case did not
#: have. A variant that swaps a named measure for one of these is a different
#: question, however similar it looks.
#: Ambiguous only when BARE. Every one of these words is unambiguous inside a
#: governed phrase — "exposure at default" is a measure, "ECL coverage" is a
#: measure, "internal rating" is a measure — and a pattern that matched them
#: would report the canonical case as already ambiguous, which makes the
#: "no NEW ambiguity" test vacuously true and lets every variant inherit.
_AMBIGUOUS = re.compile(
    r"\bexposure\b(?!\s+at\s+default)"
    r"|(?<!ecl )(?<!collateral )(?<!interest )\bcoverage\b(?!\s+ratio)"
    r"|(?<!at )(?<!given )(?<!y of )\bdefault\b"
    r"|\bthe book\b"
    r"|(?<!internal )(?<!external )\brating\b(?!\s+grade)"
    r"|\butilisation\b(?!\s+rate)(?!\s+against)",
    re.I)


def may_inherit(canonical: sc.TeachingCase, variant: sc.TeachingCase, *,
                transform: Transform) -> Judgement:
    """§14's four conditions, checked in the order they can fail.

    Deliberately conservative. The cost of wrongly marking a good variant for
    review is a reviewer's minute; the cost of wrongly inheriting is a case
    teaching the wrong structured target under a reviewed case's approval.
    """
    reasons: list[str] = []

    if not transform.preserves:
        reasons.append(f"{transform.label} changes the subject, not the "
                       "phrasing")

    # Semantic equivalence, as far as a deterministic check can go: the
    # variant must still name the same governed concepts.
    if set(variant.concepts) != set(canonical.concepts):
        reasons.append("the concepts changed")

    # The objective set must be unchanged.
    if [o.text for o in variant.objectives] != \
            [o.text for o in canonical.objectives]:
        reasons.append("the objective set changed")

    # No new ambiguity.
    before = bool(_AMBIGUOUS.search(canonical.question))
    after = bool(_AMBIGUOUS.search(variant.question))
    if after and not before:
        reasons.append("the wording introduces an ambiguity the canonical "
                       "case did not have")

    # Period and grain semantics.
    if variant.period_contract != canonical.period_contract:
        reasons.append("the period contract changed")
    if variant.grain != canonical.grain:
        reasons.append("the grain changed")

    # The deterministic plan validator: a variant whose case does not validate
    # cannot inherit anything.
    if sc.problems_blocking(variant):
        reasons.append("the variant does not validate")

    return Judgement(inherits=not reasons, reasons=reasons)


# ---------------------------------------------------------------------------
# Making them
# ---------------------------------------------------------------------------

def variant(canonical: sc.TeachingCase, transform: Transform, *,
            index: int = 0) -> sc.TeachingCase | None:
    """One variant, or None when the transform did not change anything.

    None rather than an identical case: a transform that found nothing to
    change has produced a duplicate, and §15 exists to keep those out.
    """
    rewritten = transform.apply(canonical.question)
    if not rewritten or rewritten.strip() == canonical.question.strip():
        return None

    built = sc.TeachingCase.from_dict(canonical.to_dict())
    built.case_id = f"{canonical.case_id}-v{index:02d}"
    built.case_version = 1
    built.question = rewritten
    built.title = f"{canonical.title} ({transform.label.lower()})"
    built.description = (f"Variant of {canonical.case_id}: "
                         f"{transform.label.lower()}. The structured target is "
                         "inherited only where §14's conditions hold.")
    built.authoring_method = st.VARIANT
    built.review_status = st.DRAFT
    built.reviewer = ""
    built.approved_at = ""
    built.source_provenance = (f"variant:{canonical.case_id}:{transform.id}"
                               f"@{VARIANT_VERSION}")
    built.tags = ["variant", transform.id,
                  *[t for t in canonical.tags if t != "canonical"]]
    # §15: a variant belongs to its canonical case's cluster, whatever the
    # words did. That is the whole point of a cluster id — two questions that
    # word-cluster apart but ARE the same question must not both be
    # retrievable.
    built.cluster_id = canonical.cluster_id or migrate._cluster(
        canonical.question)

    if built.conversation_turns:
        built.conversation_turns[0].user_message = rewritten

    return sc.sealed(built)


@dataclass
class Batch:
    """What a generation run produced, and what it decided about each."""

    made: list[sc.TeachingCase] = field(default_factory=list)
    judgements: dict[str, Judgement] = field(default_factory=dict)
    skipped: dict[str, int] = field(default_factory=dict)

    def inheriting(self) -> list[sc.TeachingCase]:
        return [c for c in self.made if self.judgements[c.case_id].inherits]

    def for_review(self) -> list[sc.TeachingCase]:
        return [c for c in self.made
                if not self.judgements[c.case_id].inherits]

    def to_dict(self) -> dict[str, Any]:
        return {
            "made": len(self.made),
            "inheriting": len(self.inheriting()),
            "for_review": len(self.for_review()),
            "skipped": dict(self.skipped),
            "clusters": len({c.cluster_id for c in self.made}),
        }


def generate(cases: list[sc.TeachingCase], *,
             transforms: tuple[Transform, ...] = TRANSFORMS,
             per_case: int = MAX_PER_CASE) -> Batch:
    """Variants for a set of canonical cases, with §15's controls applied.

    Three controls, and each stops a different way the corpus degrades:

    - at most `per_case` variants, because retrieval admits one case per
      cluster and the rest are cases that can never be retrieved;
    - a variant identical to another variant is dropped, by fingerprint;
    - a variant identical to its own canonical case is never made at all.
    """
    batch = Batch()
    seen: set[str] = {sc.fingerprint(c) for c in cases}

    for case in cases:
        made = 0
        for transform in transforms:
            if made >= per_case:
                batch.skipped["per-case cap"] = \
                    batch.skipped.get("per-case cap", 0) + 1
                break
            built = variant(case, transform, index=made)
            if built is None:
                batch.skipped["no change"] = \
                    batch.skipped.get("no change", 0) + 1
                continue
            if built.fingerprint in seen:
                batch.skipped["duplicate"] = \
                    batch.skipped.get("duplicate", 0) + 1
                continue

            verdict = may_inherit(case, built, transform=transform)
            if verdict:
                # §14: a variant meeting all four conditions inherits the
                # canonical structured target, so its validators have passed
                # on the same target a person already reviewed. That is
                # AUTO_VALIDATED — not APPROVED, which still needs a person.
                built.review_status = st.AUTO_VALIDATED
            else:
                built.review_status = st.SME_REVIEW_REQUIRED
                built.notes = "; ".join(verdict.reasons)
            seen.add(built.fingerprint)
            batch.made.append(built)
            batch.judgements[built.case_id] = verdict
            made += 1

    return batch


# ---------------------------------------------------------------------------
# §15's duplicate control, over a whole corpus
# ---------------------------------------------------------------------------

@dataclass
class Clusters:
    """How a corpus divides into paraphrase clusters, and where it is
    lopsided."""

    by_cluster: dict[str, list[str]] = field(default_factory=dict)
    duplicates: dict[str, list[str]] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return sum(len(v) for v in self.by_cluster.values())

    def crowded(self, limit: int = MAX_PER_CASE + 1) -> dict[str, int]:
        """Clusters big enough to crowd retrieval.

        Not an error — a family whose question has six genuinely different
        phrasings should have six — but a number worth seeing, because
        retrieval will only ever show one of them.
        """
        return {k: len(v) for k, v in self.by_cluster.items()
                if len(v) > limit}

    def to_dict(self) -> dict[str, Any]:
        return {
            "cases": self.total,
            "clusters": len(self.by_cluster),
            "largest": max((len(v) for v in self.by_cluster.values()),
                           default=0),
            "crowded": self.crowded(),
            "duplicate_groups": len(self.duplicates),
            "duplicates": {k: v for k, v in list(self.duplicates.items())[:20]},
        }


def clusters(cases: list[sc.TeachingCase]) -> Clusters:
    """§15's view of a corpus: what clusters with what, and what is identical.

    Two different questions. A cluster holds paraphrases of one question and
    is expected to have several members; a duplicate group holds cases that
    teach exactly the same thing and should have one.
    """
    found = Clusters()
    by_fingerprint: dict[str, list[str]] = {}
    for case in cases:
        key = case.cluster_id or sc.fingerprint(case)
        found.by_cluster.setdefault(key, []).append(case.case_id)
        by_fingerprint.setdefault(sc.fingerprint(case), []).append(
            case.case_id)
    found.duplicates = {k: v for k, v in by_fingerprint.items()
                        if len(v) > 1}
    return found


def split(cases: list[sc.TeachingCase], *, holdout_fraction: float = 0.2
          ) -> tuple[list[sc.TeachingCase], list[sc.TeachingCase]]:
    """A development/evaluation split that cuts on CLUSTERS, not cases. §15.

    "Split evaluation by family/cluster, not random individual question, to
    prevent leakage." A random split puts "What is total EAD by sector?" in
    development and "By sector, total EAD?" in evaluation, and the resulting
    score measures paraphrase matching.

    Deterministic: the same corpus splits the same way on every machine, so
    two evaluation runs are comparable.
    """
    grouped: dict[str, list[sc.TeachingCase]] = {}
    for case in cases:
        grouped.setdefault(case.cluster_id or sc.fingerprint(case),
                           []).append(case)

    keys = sorted(grouped)
    every = max(1, int(round(1 / max(holdout_fraction, 1e-6))))
    development: list[sc.TeachingCase] = []
    evaluation: list[sc.TeachingCase] = []
    for index, key in enumerate(keys):
        target = evaluation if index % every == 0 else development
        target.extend(grouped[key])
    return development, evaluation


def canonical_cases() -> list[sc.TeachingCase]:
    """The canonical corpus, for a generation run to work from."""
    return cn.cases()


__all__ = ["BY_ID", "Batch", "Clusters", "Judgement", "MAX_PER_CASE",
           "TRANSFORMS", "Transform", "VARIANT_VERSION", "abbreviated",
           "canonical_cases", "casual", "clusters", "formal", "generate",
           "jargon", "may_inherit", "omit_subject", "reorder", "split",
           "typo", "variant"]
