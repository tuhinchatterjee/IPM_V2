"""
Playbook — CreditProbe's chat-first document workspace.

What this package is for
------------------------
Turning evidence somebody chose — uploaded documents and explicitly exported
analyses — into professional reports, presentations and workbooks, through a
conversation rather than a template wizard.

Not the other Playbook. `backend/services/playbooks.py` is a standing
instruction that RUNS certified analyses on a trigger (docs/PRODUCT_SPEC.md §9).
This package shares its name and nothing else, and does not touch it.

The boundary this package inherits
----------------------------------
The repository's governing rule is that the language model is not the
calculator. Playbook is where that rule is hardest to keep, because the model
here is writing prose full of numbers rather than emitting a validated plan. It
is kept the same way it is kept everywhere else — mechanically:

* every figure that reaches a document comes from an export snapshot, a parsed
  source chunk with a locator, or `backend.playbook.calc`;
* `backend.playbook.grounding` checks the drafted prose against the evidence
  ledger and removes what it cannot find, recording the removal;
* nothing in this package derives a constant by hand that
  `backend.playbook.fixtures` can derive in code.

The model chooses the words, the structure and the argument. It does not get to
choose the numbers.
"""
