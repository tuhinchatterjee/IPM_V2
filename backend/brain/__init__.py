"""The CreditProbe Brain: the governed intelligence layer, made portable.

Precise words, used precisely (§1 of the brief):

**Claude foundation model** — the external provider model. Nothing in this
package modifies its weights, reads them, or sends anything to Anthropic for
training.

**CreditProbe intelligence layer** — the prompts, schemas, ontology,
retrieval, routing, working memory, officer and agent policies, tool
descriptions, critic rules, answer contracts and local auxiliary models that
surround the provider API. This is what is trained here.

**Learning observation** — an immutable record of one interaction.

**Teaching case** — a structured example, used according to its status.

**Learning Bundle** — a sanitized export of observations, feedback and
candidate cases from one installation.

**Brain Pack** — a frozen, evaluated, portable intelligence release.

**Brain Release** — an activated Brain Pack inside an installation.

The sentence this package exists to make true: *CreditProbe's governed
intelligence layer was trained and validated.* Never *Claude trained itself*.
"""
