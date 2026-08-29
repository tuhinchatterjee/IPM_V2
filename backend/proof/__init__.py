"""
Agentic proof and assurance-coverage instrumentation. The hardening phase.

    "A different officer badge is not proof of a different execution path."

What this package is for
------------------------
Everything before it BUILT the agentic system. This package exists to find
out whether it actually works, and to say so in numbers that can be compared
before and after a change.

``probe``       one request, driven through the real governed path, with
                every field §2 asks for captured from what was persisted
                rather than from what the code intended.
``divergence``  whether materially different request classes actually take
                materially different execution paths — the assertion that
                separates real orchestration from a badge.
``coverage``    the Coverage Map: for every assurance subcomponent, which
                system produces its signal, when, and what makes it PASS,
                FAIL, SKIPPED, NOT_APPLICABLE or NOT_AVAILABLE.
``flows``       the flow classes and their coverage targets, because one
                global coverage number over six different kinds of request
                is a number about nothing.

The rule the whole package is built around: **nothing here may manufacture a
PASS.** A signal that is not wired reports NOT_AVAILABLE, which blocks where
the subcomponent is critical. That is uncomfortable by design — it is what
makes an improving coverage number mean something.
"""

from backend.proof import coverage, divergence, flows, probe

__all__ = ["coverage", "divergence", "flows", "probe"]
