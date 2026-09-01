"""Demo Mode: the deliberate, repeatable state a client demonstration runs on.

Two things live here and they are deliberately separate:

* `mode` — whether this deployment is running as a demonstration at all, and
  what that changes.
* `workspace` — what the demonstration is *about*: the Project, the
  Investigations, the saved Analyses, the Risk Cases, the workflow item and the
  notification a presenter walks through, and the reset that rebuilds them.

Demo Safe Mode is NOT here. It is an answer-quality policy and it lives in
`backend/release/demo_safe.py`, where it was before this phase. The two are
independent on purpose: Demo Safe Mode is worth running in a pilot against real
data, where Demo Mode would be actively wrong.
"""
