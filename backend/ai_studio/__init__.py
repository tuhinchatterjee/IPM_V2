"""
The AI Intelligence Studio. Part C.

    "Give authorized Administrators, Credit-Risk SMEs, Model Risk, Data
     Stewards and Product Owners one place to understand what intelligence has
     been configured … This is not a code editor."

What this package is for
------------------------
Parts A and B built the intelligence. Nobody outside the codebase can see any
of it. A materiality policy with nine weighted inputs, a contradiction
taxonomy with fifteen recorded diagnostics and a library of two and a half
thousand teaching cases are, from a Model Risk reviewer's chair, indis-
tinguishable from a model that guesses — because both produce answers and
neither shows its reasoning.

So this package assembles what has been configured, how it was validated, how
it is performing, what is stale and which release uses it, for every object
the product reasons with.

Two rules run through all of it:

``explain``      every object answers §117's seven questions, and an object
                 that cannot is visibly incomplete rather than invisibly
                 unexplained.
``capabilities`` no number is displayed without the evidence that supports it.
                 A capability with eleven clean cases reports eleven clean
                 cases, not 100%.
``permissions``  enforced backend-side, and the sealed holdout gets a second
                 wall: even where a number is legally available, only §120's
                 whitelist reaches a screen.
``tabs``         the fifteen tabs, assembled from the modules that own their
                 subject. Nothing here computes intelligence; a Studio with
                 its own idea of whether a blueprint is healthy tells you how
                 the Studio feels about the blueprint.
"""

from backend.ai_studio import capabilities, explain, permissions, tabs

__all__ = ["capabilities", "explain", "permissions", "tabs"]
