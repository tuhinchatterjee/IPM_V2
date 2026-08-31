"""What the product is allowed to say about itself. §12, §13.

Two words are banned from every surface a normal user can see, for two
different reasons.

**The intelligence provider.** A header reading "Questions are read and
interpreted by claude-opus-5 via anthropic" tells a credit officer nothing
they can act on and tells a competitor which vendor the bank is committed to.
It also ages badly: the sentence is wrong the day the model changes and
nobody remembers the copy exists. The provider and model identifiers stay —
governance, observability and reproducibility all need to know exactly which
model produced an answer — but they live in audit metadata and on the Trace's
technical layer, not in product copy.

**"Demo".** A product that calls itself a demonstration cannot be sold as a
product. But the data really is synthetic, and saying otherwise would be the
one thing worse than saying "demo": presenting a generated portfolio as a
bank's own book. So the disclosure stays and only its wording changes —
SYNTHETIC DATA, which is accurate, and shorter.

What this module is
-------------------
The vocabulary, the patterns that detect a lapse, and one function that
neutralises a string on its way out. It is deliberately not a middleware over
every response: scanning megabytes of result rows on every request to protect
against a word that can only appear in prose is the wrong trade. Prose is
gated here and at the few places that compose it; everything else is held by
`tests/release/test_product_copy.py`, which walks the real routes and the real
rendered frontend copy and fails on a single occurrence.

Internal names are not product copy
-----------------------------------
`ANTHROPIC_API_KEY`, `AnthropicProvider`, `backend/demo/mode.py`,
`CREDITPROBE_DEMO_MODE`, the teaching corpus's own adversarial questions —
none of these render. Renaming them would be a night spent moving letters
around for no user-visible gain, and the mandate says so explicitly. The line
is: does a normal user read it?
"""

from __future__ import annotations

import re
from typing import Any

PRODUCT_COPY_VERSION = "1.0.0"

# --------------------------------------------------------------- vocabulary

#: The synthetic-data disclosure, wherever one is required. Accurate, and it
#: does not claim the deployment is a rehearsal.
SYNTHETIC_LABEL = "SYNTHETIC DATA"

SYNTHETIC_DETAIL = (
    "This deployment runs on a synthetic Saudi corporate credit portfolio. "
    "It describes no real borrower and contains no client data.")

#: Sentence-case, for use inside prose rather than on a chip.
SYNTHETIC_SENTENCE = "Synthetic data. Every figure carries a Trace."

#: What `CREDITPROBE_DEMO_MODE` is called on screen. The switch keeps its
#: name; the posture it produces is described by what it actually does.
SYNTHETIC_MODE_LABEL = "Synthetic Data Mode"

#: What `DEMO_SAFE_MODE` is called on screen. It means: refuse to show an
#: answer that cannot be fully validated. That is a posture a bank may want on
#: its own book, which is precisely why its name should not say "demo".
SAFE_MODE_LABEL = "Client Safe Mode"

#: The one thing the product says about the intelligence behind it.
AI_LABEL = "AI POWERED"

# ----------------------------------------------------------------- patterns

#: Provider and model identities. `opus`/`sonnet`/`haiku` are bounded so an
#: ordinary word containing them cannot trip the scan.
PROVIDER_PATTERN = re.compile(
    r"\bclaude\b|\banthropic\b|\bsonnet\b|\bopus\b|\bhaiku\b|"
    r"\bgpt-?\d|\bopenai\b|\bgemini\b|\bllama\b",
    re.IGNORECASE)

#: "Demo" and its family. `demography`, `democratic` and `demonstrate` are
#: not caught — only the noun and the adjective a product would print.
DEMO_PATTERN = re.compile(
    r"\bdemos?\b|\bdemo[-\s]|\bdemonstration\b|\bdemonstrations\b",
    re.IGNORECASE)

PATTERNS: dict[str, re.Pattern[str]] = {
    "provider": PROVIDER_PATTERN,
    "demo": DEMO_PATTERN,
}


def violations(text: str) -> list[tuple[str, str]]:
    """Every prohibited word in `text`, as (kind, the matched word).

    Returns pairs rather than a boolean so a failing test can print what it
    found. A scan that only says "something is wrong" is a scan somebody
    disables.
    """
    if not text:
        return []
    found: list[tuple[str, str]] = []
    for kind, pattern in PATTERNS.items():
        found.extend((kind, m.group(0)) for m in pattern.finditer(text))
    return found


def clean(text: str) -> bool:
    return not violations(text)


# -------------------------------------------------------------- neutralising

#: Phrase-level rewrites, longest first, applied before the word-level ones so
#: "Demo Safe Mode" becomes "Client Safe Mode" rather than "Safe Mode".
_PHRASES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bDemo Safe Mode\b", re.I), SAFE_MODE_LABEL),
    (re.compile(r"\bDEMO\s*[-–—]\s*SYNTHETIC DATA\b", re.I), SYNTHETIC_LABEL),
    (re.compile(r"\bSYNTHETIC DEMONSTRATION DATA\b"), "SYNTHETIC DATA"),
    (re.compile(r"\bsynthetic demonstration data\b", re.I), "synthetic data"),
    (re.compile(r"\bdemonstration data\b", re.I), "synthetic data"),
    (re.compile(r"\bdemo data\b", re.I), "synthetic data"),
    (re.compile(r"\bDemo Mode\b", re.I), SYNTHETIC_MODE_LABEL),
    (re.compile(r"\bDEMO POLICY\b"), "SEEDED POLICY"),
    (re.compile(r"\bdemonstration (default|value|parameter)s?\b", re.I),
     lambda m: f"seeded {m.group(1)}"),
    (re.compile(r"\bfor demonstration\b", re.I), "for this deployment"),
    (re.compile(r"\bdemonstration scale\b", re.I), "full scale"),
    (re.compile(r"\ba demonstration\b", re.I), "this deployment"),
    (re.compile(r"\bthe demonstration\b", re.I), "this deployment"),
    (re.compile(r"\bdemonstration\b", re.I), "synthetic"),
    (re.compile(r"\bdemo\b", re.I), "synthetic"),
)

#: Provider identities, replaced by what the reader can actually use.
_PROVIDER_PHRASES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(
        r"\b(?:read and interpreted|interpreted|read) by "
        r"[\w\-]+(?:\.[\w\-]+)* via [\w\-]+(?:\.[\w\-]+)*"),
     "read and interpreted by the configured intelligence provider"),
    (re.compile(r"\b(?:claude|gpt)[-\w]*(?:\.[\w\-]+)*", re.I),
     "the language model"),
    (re.compile(r"\banthropic\b|\bopenai\b", re.I),
     "the intelligence provider"),
)


def neutralise(text: str) -> str:
    """Rewrite a string so no prohibited word survives, preserving meaning.

    Used where copy is composed from parts that a governance layer legitimately
    knows — the provider health sentence, an export's disclosure banner — so
    the neutral wording is produced once rather than remembered in twelve
    places. Where the copy is a literal, the literal itself is written
    correctly and this function never sees it.
    """
    if not text:
        return text
    out = text
    for pattern, replacement in _PROVIDER_PHRASES:
        out = pattern.sub(replacement, out)
    for pattern, replacement in _PHRASES:
        out = pattern.sub(replacement, out)  # type: ignore[arg-type]
    return out


def scrub(value: Any) -> Any:
    """`neutralise`, applied through a JSON-shaped structure.

    Keys are left alone: a key is an identifier, not copy, and rewriting one
    breaks the reader. Only string values are touched.
    """
    if isinstance(value, str):
        return neutralise(value)
    if isinstance(value, dict):
        return {k: scrub(v) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub(v) for v in value]
    if isinstance(value, tuple):
        return tuple(scrub(v) for v in value)
    return value


#: Keys whose VALUE is a vendor or model identifier. Blanked rather than
#: dropped, so a reader written against the internal shape still finds the key
#: and a test can assert it is empty.
IDENTITY_KEYS: frozenset[str] = frozenset({
    "provider", "model", "ai_model", "model_provider", "model_id",
    "provider_name", "model_name", "llm_model", "llm_provider",
    "ai_provider", "planner_model", "interpreter_model",
})


def withhold_identity(value: Any) -> Any:
    """Blank every vendor identifier in a payload, then neutralise its prose.

    Applied at the API boundary of the surfaces a normal user reads. Two
    passes because the identity can arrive either as a field — `{"model":
    "claude-opus-5"}` — or embedded in a sentence somebody composed, and
    stopping only one of those leaves the other rendering on the header.
    """
    if isinstance(value, dict):
        return {
            k: ("" if k in IDENTITY_KEYS and isinstance(v, str)
                else withhold_identity(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [withhold_identity(v) for v in value]
    if isinstance(value, str):
        return neutralise(value)
    return value


__all__ = [
    "AI_LABEL", "DEMO_PATTERN", "PATTERNS", "PRODUCT_COPY_VERSION",
    "PROVIDER_PATTERN", "SAFE_MODE_LABEL", "SYNTHETIC_DETAIL",
    "SYNTHETIC_LABEL", "SYNTHETIC_MODE_LABEL", "SYNTHETIC_SENTENCE",
    "IDENTITY_KEYS", "clean", "neutralise", "scrub",
    "violations", "withhold_identity",
]
