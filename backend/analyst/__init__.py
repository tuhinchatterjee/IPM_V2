"""The AI analyst: the model investigates, CreditProbe executes. §2, §3, §4.

The architecture this replaces
------------------------------
    question -> model reads it -> deterministic planner -> one analysis -> answer

The model's whole job was to restate the question in a schema the planner
already understood. Everything the planner could not express, the product could
not answer, and a question one word outside that vocabulary dead-ended in a
clarification card. The model was a translator standing in front of an engine
with no way to look at the data.

The architecture this is
------------------------
    question -> model, in the user's own words
             -> it inspects the governed catalogue
             -> it asks for a governed tool
             -> CreditProbe executes and returns evidence
             -> it reads the evidence and asks for more, or answers
             -> validation, grounding, Trace

The model decides HOW to investigate. It never computes. Every figure in the
final answer came out of the governed runtime, was validated, and is traceable
to the tool call that produced it.

What each module is for
-----------------------
``safety``    The read-only contract. What a tool may do, over which datasets,
              for which principal, within which limits.
``tools``     The registry: discovery, metadata, analysis and evidence tools,
              each with a schema the model is given and a handler CreditProbe
              runs.
``evidence``  What came back, hashed, so an answer can be checked against it
              rather than believed.
``session``   The loop, and its budget.

Why the loop is built on the existing single-call provider
-----------------------------------------------------------
`backend.llm` exposes one primitive: a schema-constrained structured call, in
which a reply that does not conform is an error rather than something to
salvage. That property is the whole reason the analytical path can be trusted,
and a conversational tool-calling API would have to reproduce it.

So the loop is turns of that same primitive. Each turn hands the model the
question, the tools, and the evidence so far, and asks for one governed
decision document: call this tool with these arguments, or ask this question,
or answer. It is a real agent loop — the model chooses the next step from what
the last one returned — built out of a call whose failure modes are already
understood, and it works unchanged against the fake provider the tests use.
"""

from __future__ import annotations

ANALYST_VERSION = "1.0.0"

__all__ = ["ANALYST_VERSION"]
