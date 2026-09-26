"""
Model comparison lab for the frozen AdvancedCockpit (Cockpit V4).

A sidecar, not a new engine. Every child investigation runs through the frozen
`backend.cockpit_v4.worker.Worker.execute` with its own `Runtime`, so the
validators, executor, repair loop, finalizer and store are the frozen ones.
This package only adds: a model registry, provider adapters bound per child,
a passive observer, an experiment coordinator, post-run evaluation, exports
and a lab API.

Nothing here imports from, or writes to, any What-If code or data.
"""

LAB_VERSION = "model-lab-0.1.0"
EVALUATOR_VERSION = "lab-eval-3"
FROZEN_COMMIT = "245c50e45786c6e0c866b281f9dd74da17d160b5"
FROZEN_TAG = "cockpit-round-h-live-pass-2026-09-23"
RELEASE_CLAIM = "EXPERIMENTAL"
