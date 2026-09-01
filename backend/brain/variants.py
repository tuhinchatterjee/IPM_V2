"""Controlled development variants. §4.

A variant is the SAME case asked differently. It exists because a client
types "ecl by sector pls" and a corpus of well-formed questions would never
have told us whether that still works.

Two rules make variants safe rather than corrosive:

1. A variant carries `variant_of`, so it is never counted toward the
   canonical floor. Padding a corpus with reworded copies of itself and
   calling the total a coverage number is the failure this guards against.
2. A variant inherits its parent's CLUSTER. The split is by cluster, so a
   variant can never land on the other side of the holdout boundary from the
   case it was derived from - which is the leak that would make a holdout
   score meaningless without ever looking wrong.

Every transformation here is meaning-preserving by construction. None of them
touches a governed term, a number, a period or a negation, because a "variant"
that changed what was asked would be a different case wearing the first one's
expectations.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import replace

from backend.brain import vocabulary as V
from backend.brain.cases import AUTO_GENERATED, Case, CaseError, validate

VARIANT_SCHEMA_VERSION = "1.0.0"

#: How many variants each eligible case gets. §4's band.
MIN_VARIANTS = 3
MAX_VARIANTS = 6

def _governed_words() -> frozenset[str]:
    """Every word that carries governed meaning, lowercased.

    A typo in "quarter" is a typo. A typo in "collateral", "Contracting" or
    "IFRS 9 Staging" is a different question, and a corpus that contained one
    would be training the layer to guess at governed vocabulary instead of
    asking about it.
    """
    words: set[str] = set()
    sources: list[str] = [
        *V.DATASET_LABEL.values(), *V.DATASET_DOMAIN.values(),
        *(m.phrase for m in V.MEASURES), *(d.phrase for d in V.DIMENSIONS),
        *(m.field for m in V.MEASURES), *(d.field for d in V.DIMENSIONS),
        *V.DATASETS, *V.AGENT_LABEL.values(), *V.AGENTS, *V.CONCEPTS,
        *V.OFFICERS.values(),
    ]
    for phrase in sources:
        for word in re.split(r"[^A-Za-z0-9]+", phrase):
            if len(word) > 2:
                words.add(word.lower())
    # Sector, segment and region names appear in questions as literals.
    words.update({
        "contracting", "riyadh", "jeddah", "saudi", "sama", "basel", "bcbs",
        "corporate", "retail", "committee", "board", "anthropic",
    })
    return frozenset(words)


_GOVERNED_WORDS = _governed_words()

#: Terms a transformation must never touch, in any casing. Checked after the
#: fact rather than trusted: the point of a variant is that it is the same
#: question, and this is what establishes it.
_PROTECTED = re.compile(
    r"\b(IFRS|SICR|ECL|PD|LGD|EAD|DPD|RAROC|SAMA|BCBS|Basel|Stage|"
    r"Scope|FY\d\d|\d+)\b")


def _typo(text: str, seed: int) -> str:
    """Transpose two letters in one ordinary word. Never in a governed term."""
    words = text.split()
    candidates = [i for i, w in enumerate(words)
                  if len(w.strip(".,?:-")) > 4
                  and w.strip(".,?:-").lower() not in _GOVERNED_WORDS
                  and not _PROTECTED.search(w)
                  and w.strip(".,?:-").isalpha()]
    if not candidates:
        return ""
    index = candidates[seed % len(candidates)]
    word = words[index]
    core = word.strip(".,?")
    trailing = word[len(core):]
    if len(core) < 4:
        return ""
    at = 1 + (seed % (len(core) - 2))
    swapped = core[:at] + core[at + 1] + core[at] + core[at + 2:]
    words[index] = swapped + trailing
    return " ".join(words)


def _lower(text: str, _seed: int) -> str:
    """How people actually type. Governed terms lose their casing and must
    still resolve - which is the point, and is also why the protected-term
    check below compares case-insensitively."""
    return text.lower()


#: Question words that need "tell me" between the politeness and the body.
#: "Could you what is in X?" is not a variant of anything - it is broken
#: English, and a corpus that contained it would be measuring the layer's
#: tolerance for nonsense rather than its tolerance for informality.
_WH = ("what", "which", "how", "where", "when", "who", "why", "whose")

#: An auxiliary in second position means the question is inverted, and an
#: embedded form of it would have to un-invert to stay grammatical.
_AUXILIARIES = frozenset({
    "does", "do", "did", "has", "have", "had", "is", "are", "was", "were",
    "can", "could", "will", "would", "should", "must", "may", "might"})
_IMPERATIVE = ("show", "give", "tell", "compare", "explain", "chart", "plot",
               "export", "open", "take", "find", "prepare", "go", "summarise",
               "read", "list", "create", "add", "assign", "approve", "reject",
               "publish", "close", "reopen", "escalate", "rename", "refresh",
               "leave", "download", "write", "put", "restrict", "widen",
               "forget", "change", "make", "send", "email", "post", "upload",
               "share", "include", "run", "use", "have", "ignore", "answer",
               "just", "skip", "pretend", "turn", "disable", "remove",
               "point", "delete", "edit", "copy", "search", "load", "print",
               "estimate", "round", "say", "scope", "profile", "now",
               "in", "one", "two", "a", "the")


def _polite(text: str, seed: int) -> str:
    """Politeness that stays grammatical, or nothing."""
    if not text:
        return ""
    words = text.split()
    first = words[0].lower().strip(",:")
    body = text[0].lower() + text[1:]
    if first in _WH:
        # A wh-question keeps its inversion ("how complete IS x"), and an
        # embedded frame would have to undo it ("how complete x IS"). Rather
        # than try, introduce the question with a colon and leave the
        # question itself exactly as it was - which is both grammatical and
        # how people actually write.
        opener = ("I need to know: ", "Quick question: ",
                  "A question for you: ")[seed % 3]
        return opener + body.rstrip("?.") + "?"
    if first in _IMPERATIVE:
        opener = ("Could you ", "Can you ", "Would you ",
                  "Please ")[seed % 4]
        text_out = opener + body.rstrip("?.")
        # "Please show me X." stays a statement; the rest become questions.
        return text_out + ("." if opener == "Please " else "?")
    return ""


def _filler(text: str, seed: int) -> str:
    fillers = ("Quick one - ", "One more thing: ", "Sorry, ", "Right, ",
               "OK so ", "Just checking - ")
    return fillers[seed % len(fillers)] + text[0].lower() + text[1:]


def _terse(text: str, _seed: int) -> str:
    """Strip the interrogative frame. "ECL by sector?" is a real question."""
    stripped = re.sub(
        r"^(What is|What was|Show me|Give me|Tell me)\s+", "", text,
        flags=re.IGNORECASE)
    if stripped == text or len(stripped) < 10:
        return ""
    # "What is in X?" minus its frame is "in X?", which is not how anyone
    # types a terse question - it is a fragment. A leading preposition is the
    # signal that the frame was carrying the sentence.
    if stripped.split()[0].lower() in (
            "in", "on", "at", "of", "for", "to", "with", "from", "across",
            "between", "by", "about", "within"):
        return ""
    return stripped[0].upper() + stripped[1:]


def _reorder(text: str, _seed: int) -> str:
    """Move a trailing clause to the front. Only where a comma makes it
    unambiguous, and never across a negation or a conditional."""
    if text.count(",") != 1 or " not " in text or " if " in text:
        return ""
    head, tail = text.split(",", 1)
    tail = tail.strip().rstrip("?.").strip()
    if not tail or len(tail.split()) < 3 or tail.lower().startswith(
            ("and ", "or ", "but ", "then ")):
        return ""
    head = head.strip().rstrip("?.")
    return f"{tail[0].upper() + tail[1:]}, {head[0].lower() + head[1:]}?"


def _unpunctuated(text: str, _seed: int) -> str:
    """Typed without the question mark, which is how most people type."""
    stripped = text.rstrip("?.").strip()
    return stripped if stripped != text else ""


def _trailing_please(text: str, _seed: int) -> str:
    return text.rstrip("?.") + ", please?" if text.endswith("?") \
        else text.rstrip(".") + ", please."


#: (kind, transformation). Order is stable so a case's variants are stable.
TRANSFORMS: tuple[tuple[str, object], ...] = (
    ("lowercase", _lower),
    ("polite", _polite),
    ("terse", _terse),
    ("filler", _filler),
    ("typo", _typo),
    ("reorder", _reorder),
    ("please", _trailing_please),
    ("unpunctuated", _unpunctuated),
)

#: Families whose wording is load-bearing and must not be varied at all.
#: PRESENTATION's answer-length cases ARE the instruction - "In one line"
#: rewritten as "give me the detail" is not a variant, it is the opposite
#: case.
_NEVER_VARY: frozenset[str] = frozenset()

#: Individual clusters whose wording is load-bearing.
_LOCKED_CLUSTERS: frozenset[str] = frozenset({
    "presentation::answer_length",
})


def eligible(case: Case) -> bool:
    """Whether this case's meaning survives rewording.

    A case is not eligible if the wording IS the expectation. Everything else
    is: a security payload reworded is still an attack, and an ambiguous
    question reworded is still ambiguous - both of which are worth knowing.
    """
    if not case.canonical:
        return False
    if case.case_family in _NEVER_VARY:
        return False
    return case.cluster not in _LOCKED_CLUSTERS


def _preserved(original: str, variant: str) -> bool:
    """Whether every governed term in the original survived the rewrite."""
    before = sorted(t.lower() for t in _PROTECTED.findall(original))
    after = sorted(t.lower() for t in _PROTECTED.findall(variant))
    return before == after


def variants_for(case: Case) -> list[Case]:
    """This case's variants: between three and six, deterministically.

    Deterministic because a corpus that changed shape between two runs would
    make a lift measurement unreadable - the number would move and nobody
    could say whether the layer or the corpus had.
    """
    if not eligible(case):
        return []

    seed = int(hashlib.sha256(case.case_id.encode()).hexdigest()[:8], 16)
    wanted = MIN_VARIANTS + (seed % (MAX_VARIANTS - MIN_VARIANTS + 1))

    produced: list[Case] = []
    seen: set[str] = {case.question.strip().lower()}
    for offset in range(len(TRANSFORMS)):
        if len(produced) >= wanted:
            break
        kind, transform = TRANSFORMS[(seed + offset) % len(TRANSFORMS)]
        text = transform(case.question, seed + offset)  # type: ignore[operator]
        if not text or text.strip().lower() in seen:
            continue
        if not _preserved(case.question, text):
            continue
        seen.add(text.strip().lower())
        produced.append(replace(
            case,
            case_id=f"{case.case_id}-v{len(produced) + 1}",
            question=text,
            case_type="variant",
            source="system_generated_variant",
            status=AUTO_GENERATED,
            variant_of=case.case_id,
            variant_kind=kind,
            tags=(*case.tags, "variant", kind),
        ))
    return produced


def build(canonical: list[Case]) -> list[Case]:
    """Every variant of every eligible case, checked.

    Refuses rather than returns on a variant that drifted: one that changed a
    governed term, collided with another case, or claims to be canonical.
    """
    produced: list[Case] = []
    problems: list[str] = []
    parents = {c.case_id: c for c in canonical}
    fingerprints = {c.fingerprint: c.case_id for c in canonical}

    for case in canonical:
        made = variants_for(case)
        if eligible(case) and len(made) < MIN_VARIANTS:
            problems.append(
                f"{case.case_id} is eligible but produced only {len(made)} "
                f"variants; the floor is {MIN_VARIANTS}")
        for variant in made:
            if variant.cluster != parents[variant.variant_of].cluster:
                problems.append(
                    f"{variant.case_id} left its parent's cluster, which is "
                    "exactly how a variant leaks across the holdout "
                    "boundary")
            if variant.canonical:
                problems.append(f"{variant.case_id} claims to be canonical")
            faults = validate(variant)
            if faults:
                problems.append(f"{variant.case_id}: {'; '.join(faults)}")
            if variant.fingerprint in fingerprints:
                problems.append(
                    f"{variant.case_id} fingerprints as "
                    f"{fingerprints[variant.fingerprint]}")
            fingerprints[variant.fingerprint] = variant.case_id
            produced.append(variant)

    if problems:
        raise CaseError("variant generation drifted: "
                        + "; ".join(problems[:20]))
    return produced
