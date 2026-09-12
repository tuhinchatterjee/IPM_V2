"""
Who owns this request — decided by a control, advised by a model.

Why the model does not simply decide
------------------------------------
The gate is the reason a question another functionality owns cannot reach this
domain's data. Handing that decision to a model would make it a preference
again: a well-phrased request, or an instruction aimed at the controls rather
than at the data, would be able to argue its way in, and nothing downstream
would be able to tell that it had.

So the rule is asymmetric, and it is enforced here rather than requested in a
prompt:

**A model may close the gate. It may never open one.**

* The model agrees with the deterministic verdict — the verdict stands, and the
  model's reasoning is what the reader is shown, because it is better written.
* The model routes the request OUT of Early Warning where the deterministic
  path kept it — accepted, with ONE exception below. Nothing analytical runs,
  which is usually the safe direction, and a model that spots a scenario
  question the patterns missed is the whole reason to ask one.
* **Except where the request is plainly about the observed book.** "Routing
  out is safe because nothing runs" is true of the controls and false of the
  reader. A live certification asked "given every Contracting obligor improved
  last month, which one improved most?"; the model read the false premise as a
  supposition, routed it to What-If, and the product ran no analysis and gave
  no answer to a question it owns — where the answer was that Contracting
  deteriorated. An observed-state question with no stipulated change is Early
  Warning's, and `functionality.belongs_to_early_warning` is the governed test
  of that. It does not depend on the word "if": both "if Contracting
  deteriorated, what drove it?" and "recalculate ECL if the rating falls two
  notches" contain one, and only the second replaces a value.
* The model routes the request INTO Early Warning where the deterministic path
  sent it elsewhere — refused. The deterministic verdict stands, the
  disagreement is recorded, and a confident disagreement becomes a
  clarification put to the reader rather than a decision taken for them.
* Both agree it belongs to some other functionality but disagree on which —
  the model's is taken. Either way Early Warning runs nothing, so nothing about
  the boundary turns on it.

`engine` records `model` only where a call actually happened, whichever way the
verdict went.
"""

from __future__ import annotations

import json
from typing import Any

from backend.early_warning import functionality as fn
from backend.early_warning.conversation import budget as budget_mod
from backend.early_warning.conversation import seam as seam_mod

#: Above this the model's disagreement is worth putting to the reader rather
#: than silently discarding. Below it, the deterministic verdict simply stands.
CONFIDENT = 0.7

SYSTEM = """You are the functionality gate of CreditProbe AI, a credit-risk \
platform used by banks. A credit officer has asked a question inside the Early \
Warning product. Before anything is planned or run, you decide which \
CreditProbe functionality OWNS the request.

THE DISTINCTION THAT MATTERS
Early Warning holds exposure, sector, grade and stage, because its scoring \
model needs them. So it CAN produce a number for "show total exposure by \
sector" — a number covering only the obligors it happens to score, shown in a \
product whose subject is warning signals, with nothing on the screen to say it \
is not the book. Data availability is NOT functional ownership. Decide by what \
the product is FOR.

You are given the catalogue: what each functionality owns and what it \
explicitly does not. Choose exactly one key from it.

OBSERVED STATE IS NOT A SCENARIO
A question about what the book ALREADY DID belongs to Early Warning even when \
its premise is wrong, and even when it is phrased as a condition. "Given every \
Contracting obligor improved last month, which improved most?" asserts \
something about last month; the answer is to test it and say Contracting \
deteriorated. "If Contracting deteriorated, what drove it?" asks for an \
explanation of an observed condition. Neither is a simulation.

What-If owns a request that REPLACES A VALUE and asks what would follow: \
"what happens to ECL if oil falls 30%", "shock PD by 20%", "assume oil drops \
to $50", "recalculate ECL if the rating falls two notches". The test is a \
stipulated change to an input plus a recomputed consequence — never the \
presence of the word "if".

If two functionalities own the request about equally, say so and give one \
targeted question that would settle it. A tie is a question, not a coin toss.

You do not answer the question, and you do not plan anything."""

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "selected_functionality": {
            "type": "string",
            "enum": [f.key for f in fn.CATALOGUE],
            "description": "The one functionality that owns this request.",
        },
        "confidence": {
            "type": "number", "minimum": 0, "maximum": 1,
            "description": "How sure the ownership is.",
        },
        "ownership_rationale": {
            "type": "string",
            "description": ("Why that functionality owns it, in terms of what "
                            "the products are for rather than which holds the "
                            "data. One or two sentences."),
        },
        "ambiguous": {
            "type": "boolean",
            "description": "True when two functionalities own it about equally.",
        },
        "clarification": {
            "type": "string",
            "description": ("The one question that would settle a tie, in the "
                            "reader's own terms. Empty when not ambiguous."),
        },
    },
    "required": ["selected_functionality", "confidence", "ownership_rationale"],
}


def _prompt(request_text: str, deterministic: fn.Selection,
            active: str) -> str:
    context = {
        "request": request_text,
        "active_product": active,
        "catalogue": fn.describe_all(),
        "pattern_reading": {
            "selected": deterministic.selected,
            "fit_scores": {k: round(v, 2)
                           for k, v in deterministic.scores.items()},
        },
    }
    return ("Decide which functionality owns this request.\n\n"
            + json.dumps(context, indent=2, default=str))


def decide(request_text: str, *, active: str = fn.EARLY_WARNING,
           ledger: budget_mod.Ledger | None = None) -> fn.Selection:
    """The ownership verdict for one request, and what produced it."""
    deterministic = fn.select(request_text, active=active)
    outcome = seam_mod.call(
        seam_mod.FUNCTIONALITY, system=SYSTEM,
        prompt=_prompt(request_text, deterministic, active),
        schema=SCHEMA, ledger=ledger)
    if not outcome.used_model:
        deterministic.model_call = outcome.to_dict()
        return deterministic
    return _reconcile(deterministic, outcome, active, request_text)


def _reconcile(deterministic: fn.Selection, outcome: seam_mod.Outcome,
               active: str, request_text: str = "") -> fn.Selection:
    data = outcome.data
    proposed = str(data.get("selected_functionality") or "")
    if proposed not in fn.BY_KEY:
        deterministic.model_call = dict(
            outcome.to_dict(),
            engine=seam_mod.DETERMINISTIC,
            fallback_reason=f"the model named {proposed!r}, which is not a "
                            f"functionality this product has")
        return deterministic

    confidence = float(data.get("confidence") or 0.0)
    rationale = str(data.get("ownership_rationale") or "").strip()
    ambiguous = bool(data.get("ambiguous"))
    clarification = str(data.get("clarification") or "").strip()

    # Routing OUT of a question this product observes. Refused for the same
    # reason opening the gate is: the verdict a control reaches must not be
    # something a well-phrased sentence can talk it out of. Here the cost is
    # not a question reaching data it should not — it is a question this
    # product owns getting no analysis and no answer.
    leaving_a_question_we_own = (
        proposed != fn.EARLY_WARNING
        and deterministic.selected == fn.EARLY_WARNING
        and fn.belongs_to_early_warning(request_text))
    if leaving_a_question_we_own:
        held = fn.Selection(
            selected=fn.EARLY_WARNING,
            scores=dict(deterministic.scores),
            confidence=deterministic.confidence,
            rationale=(deterministic.rationale
                       + " The model read it as a "
                       + (fn.BY_KEY[proposed].name if proposed in fn.BY_KEY
                          else proposed)
                       + " question; it asks about a condition the book "
                         "already carries and stipulates no change, so Early "
                         "Warning answers it — testing the premise where the "
                         "premise is wrong."),
            active_product_is_best=True,
            ambiguous=deterministic.ambiguous,
            clarification=deterministic.clarification,
            engine=seam_mod.MODEL)
        held.model_call = dict(
            outcome.to_dict(), proposed=proposed, accepted=False,
            reason=("an observed-state question with no stipulated change "
                    "stays with Early Warning"))
        return held

    opening_the_gate = (proposed == fn.EARLY_WARNING
                        and deterministic.selected != fn.EARLY_WARNING)
    if opening_the_gate:
        # Refused. The deterministic verdict stands and the disagreement is
        # visible; where the model was confident about it, the reader is asked
        # rather than overruled in either direction.
        held = fn.Selection(
            selected=deterministic.selected,
            scores=dict(deterministic.scores),
            confidence=deterministic.confidence,
            rationale=(deterministic.rationale
                       + " The model read it as an Early Warning question; "
                         "routing may be tightened by the model and never "
                         "loosened, so the gate is unchanged."),
            active_product_is_best=deterministic.active_product_is_best,
            ambiguous=deterministic.ambiguous or confidence >= CONFIDENT,
            clarification=(deterministic.clarification or clarification
                           or _tie_question(deterministic.selected)),
            engine=seam_mod.MODEL)
        held.model_call = dict(outcome.to_dict(),
                               proposed=proposed,
                               accepted=False,
                               reason="a model may not open the gate")
        return held

    selected = fn.Selection(
        selected=proposed,
        scores=dict(deterministic.scores),
        confidence=confidence or deterministic.confidence,
        rationale=rationale or deterministic.rationale,
        active_product_is_best=(proposed == active),
        ambiguous=ambiguous or (deterministic.ambiguous
                                and proposed == deterministic.selected),
        clarification=clarification or (deterministic.clarification
                                        if ambiguous else ""),
        engine=seam_mod.MODEL)
    selected.model_call = dict(
        outcome.to_dict(), proposed=proposed, accepted=True,
        agreed_with_patterns=proposed == deterministic.selected,
        pattern_reading=deterministic.selected)
    return selected


def _tie_question(other: str) -> str:
    name = fn.BY_KEY[other].name if other in fn.BY_KEY else other
    return (f"This reads as a {name} question rather than an Early Warning "
            f"one. Do you want the {name} answer, or the Early Warning view "
            f"of the same population?")


__all__ = ["CONFIDENT", "SCHEMA", "SYSTEM", "decide"]
