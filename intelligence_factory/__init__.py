"""
Where CreditProbe's intelligence is developed, measured and frozen.

This package is NOT part of the running product. Nothing under `backend/`
imports it, a test enforces that, and the application starts and answers
questions with this directory deleted. It exists to produce one artefact — a
**frozen Intelligence Release** — which the product then consumes.

    curriculum  ─┐
    generators  ─┼─→ development evaluation ─→ prompt / routing choices
    ontology    ─┘                                      │
                                                        ▼
    sealed holdout ──────────────────────────→ certification ──→ release/
                                                                    │
                                              Docker consumes ──────┘

Being honest about what "training" means here
---------------------------------------------
No foundation-model weights are modified. Anthropic does not expose fine-tuning
that CreditProbe uses, and claiming otherwise would be the same kind of
dishonesty this release exists to remove. What is actually optimised is:

* a reviewed credit-risk curriculum, and paraphrases generated from it;
* the prompts each model role is given;
* which route a request takes and when it escalates;
* what governed context is retrieved;
* the thresholds at which CreditProbe clarifies rather than answers.

Those are the levers CreditProbe has, they are the ones that decide whether an
answer is right, and they are frozen into a release with a version so a demo
can be run against a fixed, measured configuration. The architecture leaves a
place for a provider-supported fine-tuned model — `AI_PLANNER_MODEL` is just an
id — without depending on one existing.

Why the holdout is sealed
-------------------------
A prompt tuned against the cases it is scored on measures the tuning. The
optimiser reads `curriculum/`; the certifier reads `holdout/`; an import-graph
test asserts nothing in the first can reach the second.
"""

from __future__ import annotations

#: Moves when the FACTORY changes how it measures. Distinct from the release
#: id, which identifies one measured configuration of the product.
FACTORY_VERSION = "1.0.0"

__all__ = ["FACTORY_VERSION"]
