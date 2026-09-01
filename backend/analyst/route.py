"""Which path answers a question, and in what order. §2, §5, §11.

Primary: the analyst
--------------------
When an intelligence provider is configured, the model investigates. It reads
the question in the user's own words, inspects the governed catalogue, calls
governed tools, and answers from what came back. That is §2's architecture and
it is the ordinary online path.

Fallback: the deterministic engine
-----------------------------------
`backend.orchestration` — the governed semantic reader and the analytical
planner — stays, and is used when:

  * no provider is configured, which on a bank's own network may be the only
    permitted arrangement;
  * the provider fails, which must degrade rather than fail;
  * the analyst returns CANNOT with nothing found, where the deterministic
    planner may still recognise a shape it knows.

§2 is explicit that the deterministic engine remains valuable for offline
fallback, simple-query acceleration, validation, regression and governance. It
stops being the BOTTLENECK — the thing that decides whether a capable model is
allowed to look at the data — which is a different claim from removing it.

Before either: the run key
--------------------------
An identical question, in an identical context, from an identical permission
scope, over identical data, catalogue, policy, prompt and tool versions,
returns the answer already validated for that key (§11). The check is first
because the cheapest correct answer is the one already computed, and the
guarantee is the product's rather than the model's.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from backend.analyst import answers, classify, cost, runkey, safety, session
from backend.analyst.safety import Principal

logger = logging.getLogger(__name__)

ROUTE_VERSION = "1.0.0"

ANALYST = "analyst"
DETERMINISTIC = "deterministic"
REPRODUCED = "reproduced"


def principal_of(caller: Any) -> Principal:
    """The API's principal, as the analyst's. Never defaulted upward.

    An unreadable caller becomes a VIEWER, not an administrator: the failure
    mode of a missing role has to be the one that sees less.

    The VISIBLE DATASET SET is carried across, and dropping it was a real
    defect caught by `test_a_different_scope_does_not_read_the_first_answer`:
    without it every principal of the same role collapsed to one permission
    scope, so a narrowly-scoped analyst was served an answer computed over a
    book they cannot read. Already a `Principal` passes through unchanged, so
    a caller that has done the resolution properly is not re-derived from a
    weaker source.
    """
    if isinstance(caller, Principal):
        return caller
    return Principal(
        user_id=int(getattr(caller, "user_id", 0) or 0),
        role=str(getattr(caller, "role", "") or "VIEWER").upper(),
        datasets=frozenset(getattr(caller, "datasets", ()) or ()),
    )


def answer(question: str, caller: Any, *, period: str = "",
           turns: list[dict[str, Any]] | None = None,
           clarification: str = "", provider: Any = None,
           allow_analyst: bool = True) -> dict[str, Any]:
    """Answer one question, by the best path available. §2.

    Returns the analyst's own shape. The caller decides how to present it; the
    Ask route folds it into the response beside the deterministic result so
    that no existing consumer has to change to keep working.
    """
    started = time.perf_counter()
    principal = principal_of(caller)
    reading = classify.read(question, continuation=bool(turns))
    meter = cost.current()
    if meter is not None:
        meter.question = meter.question or question
        meter.classify(reading.question_class, reading.why)
    key = runkey.build(question, principal, period=period, turns=turns,
                       clarification=clarification)

    stored = answers.recall(key)
    if stored is not None:
        # §11. The same validated answer, not a new composition of the same
        # evidence. Recomposing would be the one place a nondeterministic model
        # could change a figure between two identical questions.
        payload = dict(stored.payload)
        payload["path"] = REPRODUCED
        payload["run_key"] = key.to_dict()
        payload["reproduced"] = True
        payload["duration_ms"] = int((time.perf_counter() - started) * 1000)
        if meter is not None:
            meter.finish(path=REPRODUCED, reproduced=True)
        payload["cost"] = _cost(meter)
        return payload

    found = None
    if allow_analyst:
        found = session.investigate(
            question, principal, provider=provider,
            context=_context(turns, clarification), meter=meter)

    if found is not None and found.outcome == session.ASK:
        payload = found.to_dict()
        payload["path"] = ANALYST
        payload["run_key"] = key.to_dict()
        payload["reproduced"] = False
        payload["cost"] = _cost(meter, path=ANALYST)
        # A clarification is NOT cached. The next turn carries the user's
        # reply, which is a different run key, and storing the question would
        # make the product ask it again for ever.
        return payload

    if found is not None and found.answered:
        payload = found.to_dict()
        payload["path"] = ANALYST
        payload["run_key"] = key.to_dict()
        payload["reproduced"] = False
        payload["cost"] = _cost(meter, path=ANALYST)
        answers.remember(key, question, payload,
                         evidence_hash=found.ledger.to_dict()["hash"])
        return payload

    fallback = {
        "version": session.SESSION_VERSION,
        "question": question,
        "outcome": session.CANNOT,
        "path": DETERMINISTIC,
        "run_key": key.to_dict(),
        "reproduced": False,
        "why_fallback": _why(found),
        "duration_ms": int((time.perf_counter() - started) * 1000),
    }
    if found is not None:
        fallback["analyst"] = found.to_dict()
    fallback["cost"] = _cost(meter, path=DETERMINISTIC)
    return fallback


def _cost(meter: Any, *, path: str = "") -> dict[str, Any]:
    """What this question spent, for the Trace and the cost report. R2 §16.

    Empty outside a measured request rather than absent: a consumer that has
    to branch on whether the key exists is one that will report zero cost as
    no measurement, or no measurement as zero cost.
    """
    if meter is None:
        return {}
    if path:
        meter.path = meter.path or path
    return meter.to_dict()


def _why(found: Any) -> str:
    """Why the deterministic engine is answering this one. For the Trace."""
    if found is None:
        return "the analyst was not asked for this question"
    if found.error == "no_provider":
        return ("no intelligence provider is configured, so the governed "
                "semantic reader answered")
    if found.error == "provider_failed":
        return ("the intelligence provider did not answer, so the governed "
                "semantic reader answered")
    return ("the analyst found nothing in the governed catalogue bearing on "
            "this question")


def _context(turns: list[dict[str, Any]] | None, clarification: str) -> str:
    """What the analyst is told about the conversation so far. §38.

    The previous turns and the resolved clarification, as prose. Passing it as
    text rather than as structure is deliberate: the model reads the earlier
    turns the way the user would, and the STRUCTURED continuation — population,
    grain, period, filters — is held by CreditProbe and applied by the tools,
    where it cannot be paraphrased away.
    """
    parts: list[str] = []
    for turn in (turns or [])[-4:]:
        question = str(turn.get("question") or "")
        said = str(turn.get("answer") or "")
        if question:
            parts.append(f"Asked: {question}")
        if said:
            parts.append(f"Answered: {said[:600]}")
    if clarification:
        parts.append(
            f"The user has already answered one clarification: "
            f"{clarification}. Do not ask another; proceed on that basis.")
    return "\n".join(parts)


def available() -> bool:
    """Whether the analyst path can run at all in this deployment."""
    try:
        from backend.llm import get_provider

        return bool(getattr(get_provider(), "configured", False))
    except Exception:  # noqa: BLE001
        return False


def posture() -> dict[str, Any]:
    """What answers questions here, said without naming a vendor. §12."""
    live = available()
    return {
        "version": ROUTE_VERSION,
        "primary": ANALYST if live else DETERMINISTIC,
        "analyst_available": live,
        "label": ("Questions are investigated against the governed catalogue "
                  "and answered from what the governed runtime returns."
                  if live else
                  "No intelligence provider is configured. Questions are read "
                  "by the governed semantic reader and computed by the "
                  "governed runtime."),
        "max_turns": safety.MAX_TURNS,
        "max_tool_calls": safety.MAX_TOOL_CALLS,
        "tools": len(_tool_names()),
    }


def _tool_names() -> list[str]:
    from backend.analyst import tools

    return [t.name for t in tools.REGISTRY]


__all__ = ["ANALYST", "DETERMINISTIC", "REPRODUCED", "ROUTE_VERSION",
           "answer", "available", "posture", "principal_of"]
