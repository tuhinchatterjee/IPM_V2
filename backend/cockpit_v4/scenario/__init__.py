"""What-If: scenario definition and deterministic ECL stress, beside `ecl.py`.

An additive package. Nothing in the accepted runtime imports it, and with both
book flags off nothing in it runs -- which is how section 2's "disabling both
must restore baseline behavior" is satisfied without a code path that checks a
flag and shrugs.

What it is
----------
Deterministic domain logic, in the shape `ecl.py` already established: no model
call, no sandbox, no network, `model_calls: 0`. It computes, normalises, types
and verifies; the existing governed path -- `execute_analysis`, `execute_tool`,
the artifact store, `derivation.py`, `finalization.py` -- executes and
publishes. Nothing here bypasses a validator.

What it is not
--------------
It is not a sixth tool. The analyst's callable surface is a frozen five-tuple
(`contracts.TOOL_NAMES`) with four copies of its membership across three
protected files, and section 1.2 forbids editing them to make an extension
appear possible. `docs/whatif/PROTECTED_CORE_INCOMPATIBILITY.md` records that
blocker and the smallest change that would lift it; nothing here implements it.

What makes that workable is a fact about the books rather than about the code:
published ECL is exactly `ead x pd x lgd` (`generate/corporate.py:1004`), so
proportional Delta is one SQL statement the analyst already has a tool to
submit, and every figure it publishes is expressible in the twelve operations
`derivation.py` already enforces.

Reading order
-------------
    units.py    what "increase PD by 20" means, and the five things it doesn't
    errors.py   the fourteen domain failures, mapped onto codes that exist
    flags.py    per-book enablement, off by default
    spec.py     the scenario as an immutable, hashable object
    fields.py   which columns may move, and the rows where they may not

`ecl.py` is the sibling worth reading first for the house style: every number
an aggregate of published columns, and the analyst never asked.
"""

from __future__ import annotations

__all__ = ["errors", "flags", "spec", "units"]
