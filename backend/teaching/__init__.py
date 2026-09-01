"""
The Credit-Risk Teaching Factory's governed contract. Part A §2, §4-§7.

Three modules, and the split is the governance:

``families``  The case families a library has to cover, and the
              rule each one puts on a case that claims it.
``status``    What a case is allowed to be, and the one decision that matters:
              whether it may be retrieved into a live prompt.
``schema``    The seventy-two-field TeachingCase, the thread schema, and the
              validation that separates a case that parses from a case that
              teaches.

Nothing here touches a model, a provider or a prompt. A teaching case is a
worked example of how to analyse; the deterministic runtime still calculates
every live answer, and the assurance layer still decides whether it may be
shown.

This package is imported by the backend and by the factory. It never imports
either — and in particular it never imports `intelligence_factory`, because a
backend module that can reach the curriculum can reach the sealed holdout one
line later.
"""

from backend.teaching import families, schema, status

__all__ = ["families", "schema", "status"]
