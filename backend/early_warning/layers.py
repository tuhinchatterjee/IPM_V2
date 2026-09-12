"""
The four detection layers, and the words a person uses to name them.

Why this module exists
----------------------
The framework has four layers and every part of the product had its own copy
of their names: the API router held one literal list, `facts` held a second,
`ask` held a third as a tuple of search words. Three copies of one fact is
three chances to disagree, and they already did — `ask` knew L3 as
`("layer 3", "l3", "external")` while the router called it "External
Intelligence" and `facts` called it "Layer 3, external intelligence". A
reader who typed "external-intelligence warning signals" matched none of the
three.

So the registry is here, once, and the rest read it.

How a phrase becomes a layer
----------------------------
Not by listing the sentences people might type. A list like that is a list of
the sentences somebody thought of, and the reader always types the one that
is missing.

Instead the resolver is built from the framework's own vocabulary — the
layer's published title, the sub-category nodes inside it, and the small set
of single words the credit book genuinely uses for it — combined with a
grammatical rule: a layer word standing next to a **warning noun** names that
layer. "External intelligence", "external signals", "external warning
signals", "external events", "external-intelligence flags" all resolve to L3
through the same rule, because they are all the layer's word next to a word
that means a signal. "External debt" does not, because "debt" is not one.

That rule is what makes the mapping generic. Adding "external alerts" to the
product's vocabulary took no change here, and neither will the next phrasing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from backend.early_warning import aggregation as agg
from backend.early_warning import classifiers_v2 as clf

#: Nouns that mean "something the model detected". A layer word next to one
#: of these is naming the layer, whatever else the sentence is doing.
#:
#: They are not synonyms for each other and this is not a thesaurus: each is
#: a word this product itself uses on screen for a fired signal, an event
#: behind one, or the reading over them.
WARNING_NOUNS: tuple[str, ...] = (
    "intelligence", "signal", "signals", "warning", "warnings", "event",
    "events", "flag", "flags", "alert", "alerts", "indicator", "indicators",
    "trigger", "triggers", "risk", "risks", "score", "scores", "reading",
    "readings", "evidence", "driver", "drivers", "deterioration", "issue",
    "issues", "exposure", "layer", "dimension", "news", "data", "feed",
    "feeds", "source", "sources", "observation", "observations",
)

#: How many words may sit between a layer word and its warning noun.
#: "external WARNING signals" needs one; "external signals" needs none.
#: Two is where the pair stops being a phrase and starts being a coincidence.
_GAP = 2


@dataclass(frozen=True)
class Layer:
    """One detection layer, under every name the product gives it."""

    code: str
    #: The workbook's own title for the layer.
    name: str
    #: How a sentence refers to it in two or three words.
    short: str
    #: The layer-dimension key on the trigger-and-accelerator side. This is
    #: the "did something fire" side: a layer's T&A score is above zero only
    #: where a signal in it fired and has not fully decayed.
    ta_key: str
    #: The classifier-side key, where the layer has one. L1 and L3 do not:
    #: the framework scores no standing condition in them.
    c_key: str | None
    #: Phrases that name the layer outright.
    names: tuple[str, ...]
    #: Single words that name the layer only when they modify a warning noun.
    stems: tuple[str, ...]
    #: Single words that name the layer on their own, because in a credit
    #: sentence they mean nothing else. "External" is not one of them —
    #: external debt, an external auditor and an external rating are all
    #: ordinary things — which is why the two sets are separate rather than
    #: one list with a comment.
    solo: tuple[str, ...] = ()

    @property
    def active_field(self) -> str:
        """The derived flag meaning "this layer fired for this obligor"."""
        return f"{self.code.lower()}_active"

    @property
    def nodes(self) -> tuple[str, ...]:
        """The sub-category codes inside this layer, trigger side."""
        return tuple(code for code, node in sorted(agg.TA_SUBCATEGORIES.items())
                     if node.layer == self.code)

    @property
    def node_names(self) -> tuple[str, ...]:
        return tuple(node.name for code, node in sorted(agg.TA_SUBCATEGORIES.items())
                     if node.layer == self.code)

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "name": self.name, "short": self.short,
                "ta_key": self.ta_key, "c_key": self.c_key,
                "active_field": self.active_field,
                "nodes": list(self.nodes), "node_names": list(self.node_names)}


LAYERS: tuple[Layer, ...] = (
    Layer(
        code="L1", name="Internal Behavioural Intelligence",
        short="internal behavioural", ta_key="l1_ta", c_key=None,
        names=("internal behavioural intelligence", "behavioural intelligence",
               "behavioral intelligence", "internal behaviour",
               "internal behavior", "account behaviour", "account behavior",
               "transactional behaviour", "transactional behavior"),
        stems=("behaviour", "behavior"),
        solo=("behavioural", "behavioral")),
    Layer(
        code="L2", name="Credit & Financial Fundamentals",
        short="credit and financial fundamentals", ta_key="l2_ta", c_key="l2_c",
        names=("credit and financial fundamentals", "credit & financial "
               "fundamentals", "financial fundamentals", "credit fundamentals",
               "fundamental credit"),
        stems=("fundamental",), solo=("fundamentals",)),
    Layer(
        code="L3", name="External Intelligence",
        short="external intelligence", ta_key="l3_ta", c_key=None,
        names=("external intelligence",),
        stems=("external",)),
    Layer(
        code="L4", name="Graph & Relationship Intelligence",
        short="network and relationship", ta_key="l4_ta", c_key="l4_c",
        names=("graph and relationship intelligence", "graph & relationship "
               "intelligence", "relationship intelligence", "network "
               "intelligence", "network contagion", "supply chain",
               "connected group", "connected groups"),
        stems=("network", "graph", "propagation"),
        solo=("contagion",)),
)

CODES: tuple[str, ...] = tuple(layer.code for layer in LAYERS)

BY_CODE: dict[str, Layer] = {layer.code: layer for layer in LAYERS}

#: Every derived per-layer flag, so the frame builder and the dictionary can
#: agree on the set without either listing it again.
ACTIVE_FIELDS: tuple[str, ...] = tuple(layer.active_field for layer in LAYERS)

#: The trigger-side layer-dimension keys, in layer order.
TA_KEYS: tuple[str, ...] = tuple(layer.ta_key for layer in LAYERS)

#: How many layers fired for an obligor this month.
FIRING_COUNT_FIELD = "layers_firing"

#: Whether more than one layer fired. This is what a credit officer means by
#: "corroborated" when they are looking at a layer: an external event that
#: nothing internal echoes is a lead to verify, and the same event with
#: arrears moving underneath it is a finding to act on. It is a CROSS-LAYER
#: reading and deliberately not the accelerator's own corroboration
#: dimension, which asks a different question about one signal's sources.
CORROBORATED_FIELD = "corroborated"

#: Every column `activity()` produces.
DERIVED_FIELDS: tuple[str, ...] = ACTIVE_FIELDS + (FIRING_COUNT_FIELD,
                                                    CORROBORATED_FIELD)


def name(code: str) -> str:
    """The layer's published title, or the code back if it is not one."""
    found = BY_CODE.get(str(code).upper())
    return found.name if found else str(code)


def described(code: str) -> str:
    """The layer written the way a sentence refers to it."""
    found = BY_CODE.get(str(code).upper())
    return f"Layer {found.code[1]}, {found.short}" if found else str(code)


def is_code(value: Any) -> bool:
    return str(value).upper() in BY_CODE


def of_field(field_name: str) -> str:
    """Which layer a layer-dimension or active-flag column belongs to."""
    lowered = str(field_name).lower()
    for layer in LAYERS:
        if lowered in (layer.ta_key, layer.c_key, layer.active_field):
            return layer.code
    return ""


# --------------------------------------------------------------- resolving


def _flatten(text: str) -> str:
    """Hyphens, ampersands and runs of space all become one space.

    "external-intelligence" and "external intelligence" are the same phrase
    typed two ways, and a resolver that can only read one of them is a
    resolver the reader has to guess the spelling for.
    """
    lowered = str(text or "").lower()
    lowered = lowered.replace("&", " and ")
    lowered = re.sub(r"[\-_/]+", " ", lowered)
    return re.sub(r"\s+", " ", lowered).strip()


def _code_pattern(code: str) -> re.Pattern[str]:
    digit = code[1]
    return re.compile(rf"\b(?:l\s?{digit}|layer\s?{digit})\b")


_CODE_PATTERNS: dict[str, re.Pattern[str]] = {
    layer.code: _code_pattern(layer.code) for layer in LAYERS}

_NOUNS = "|".join(sorted(set(WARNING_NOUNS), key=len, reverse=True))


def _stem_pattern(stem: str) -> re.Pattern[str]:
    return re.compile(
        rf"\b{re.escape(stem)}\b(?:\s+\w+){{0,{_GAP}}}?\s+\b(?:{_NOUNS})\b")


_STEM_PATTERNS: dict[str, list[tuple[str, re.Pattern[str]]]] = {
    layer.code: [(stem, _stem_pattern(stem)) for stem in layer.stems]
    for layer in LAYERS}

_SOLO_PATTERNS: dict[str, list[tuple[str, re.Pattern[str]]]] = {
    layer.code: [(word, re.compile(rf"\b{re.escape(word)}\b"))
                 for word in layer.solo]
    for layer in LAYERS}


@dataclass(frozen=True)
class Match:
    """What in the sentence named the layer, so a caller can say why."""

    code: str
    matched: str
    how: str
    span: int = 0


def find(text: str) -> Match | None:
    """The layer a sentence names, and what named it.

    Four ways, and where more than one fires the longest match wins — the
    sentence that says "layer 3 external intelligence" says one thing twice,
    not two things.
    """
    flat = _flatten(text)
    if not flat:
        return None
    found: list[Match] = []

    for code, pattern in _CODE_PATTERNS.items():
        hit = pattern.search(flat)
        if hit:
            # The code is the reader saying the layer's name in the model's
            # own notation. Nothing outranks it, so it carries a span that
            # nothing else reaches.
            found.append(Match(code, hit.group(0), "code", 1000))

    for layer in LAYERS:
        for phrase in layer.names:
            flat_phrase = _flatten(phrase)
            if flat_phrase and flat_phrase in flat:
                found.append(Match(layer.code, flat_phrase, "name",
                                   len(flat_phrase)))
        for node_name in layer.node_names:
            flat_node = _flatten(node_name)
            if flat_node and flat_node in flat:
                found.append(Match(layer.code, flat_node, "node",
                                   len(flat_node)))

    for code, patterns in _STEM_PATTERNS.items():
        for stem, pattern in patterns:
            hit = pattern.search(flat)
            if hit:
                found.append(Match(code, hit.group(0), "stem", len(stem)))

    for code, patterns in _SOLO_PATTERNS.items():
        for word, pattern in patterns:
            hit = pattern.search(flat)
            if hit:
                found.append(Match(code, hit.group(0), "solo", len(word)))

    if not found:
        return None
    return max(found, key=lambda m: (m.span, m.code))


def resolve(text: str) -> str:
    """The layer code a sentence names, or an empty string."""
    hit = find(text)
    return hit.code if hit else ""


def activity(rows: Any) -> dict[str, list[bool]]:
    """Per-layer "this layer fired" flags, from the layer-dimension scores.

    A layer is ACTIVE for an obligor when its trigger-and-accelerator score
    is above zero — at least one signal in that layer fired for this obligor
    in this month and has not fully decayed away. The classifier side is
    deliberately not consulted: L2's classifier score is above zero for every
    obligor in the book because it describes a standing condition, so a flag
    that read it would be true for everybody and would answer "which obligors
    carry fundamentals warnings" with the whole portfolio.

    Pure Python on purpose. Both the wide frame builder and the fact builder
    need these columns, and a helper that took a DataFrame would have to live
    in one of them and be imported by the other.
    """
    out: dict[str, list[Any]] = {field_name: [] for field_name in DERIVED_FIELDS}
    for row in rows:
        scores = row or {}
        firing = 0
        for layer in LAYERS:
            try:
                value = float(scores.get(layer.ta_key) or 0.0)
            except (AttributeError, TypeError, ValueError):
                value = 0.0
            active = value > 0.0
            out[layer.active_field].append(active)
            firing += 1 if active else 0
        out[FIRING_COUNT_FIELD].append(firing)
        out[CORROBORATED_FIELD].append(firing > 1)
    return out


def vocabulary() -> dict[str, Any]:
    """Every way the product will recognise a layer, for the /vocabulary
    endpoint and for the tests that keep the two honest."""
    return {
        "layers": [layer.to_dict() for layer in LAYERS],
        "warning_nouns": list(WARNING_NOUNS),
        "code_forms": ["L3", "layer 3", "l3"],
        "gap_words_allowed": _GAP,
    }


#: The weights each layer carries, so a reading can say what a layer is worth
#: without a second copy of the framework's numbers.
TA_WEIGHTS: dict[str, float] = dict(agg.TA_LAYER_WEIGHTS)
C_WEIGHTS: dict[str, float] = dict(clf.CLASSIFIER_LAYER_WEIGHTS)


__all__ = ["ACTIVE_FIELDS", "BY_CODE", "CODES", "CORROBORATED_FIELD",
           "C_WEIGHTS", "DERIVED_FIELDS", "FIRING_COUNT_FIELD", "LAYERS",
           "Layer", "Match", "TA_KEYS", "TA_WEIGHTS", "WARNING_NOUNS",
           "activity", "described", "find", "is_code", "name", "of_field",
           "resolve",
           "vocabulary"]
