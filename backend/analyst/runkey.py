"""The same question, asked twice, returns the same answer. §11.

The product contract
--------------------
For the same normalized question, conversation context, resolved clarification,
permission scope, reporting period, data snapshot, catalogue, threshold and
policy versions, prompt version, tool-registry version and product release —
CreditProbe returns the SAME validated answer.

Why this cannot rest on the model
----------------------------------
Foundation models are not deterministic, and temperature zero does not make
them so: batching, hardware and serving changes all move the last token. A
credit committee reading two different answers to the same question on two
days will not accept "the sampler was different", and they will be right not
to. So the determinism is CreditProbe's, built out of two things it does
control:

  * **The computation is already deterministic.** Every tool builds a plan
    from typed arguments, sorts by an explicit key with an explicit tie-break,
    and rounds under one contract. Two runs of the same plan return the same
    rows in the same order.
  * **The narrative is cached against a key.** Once an answer has passed
    validation and grounding, it is stored under the run key. The next
    identical run returns the stored, validated answer rather than composing a
    new one.

What the key contains, and why each part
-----------------------------------------
Anything that could legitimately change the answer is IN the key, so that when
it changes a new answer is allowed rather than suppressed. Anything that could
not is out, so that an irrelevant difference does not defeat the cache.

    normalized question       the same question, said differently, is the same
    context hash              the conversation this turn continues
    clarification state       "yes, the 12-month PD" changes which figure is right
    permission scope          two roles may legitimately see different books
    period                    the reporting period the answer is at
    data snapshot             the lake's version. New data, new answer.
    catalogue version         a renamed field is a different question
    policy/threshold version  a moved threshold is a different signal
    prompt version            a changed system prompt is a changed analyst
    tool-registry version     a changed tool is a changed capability
    release version           the product build

Permission scope is part of the key rather than a filter over a shared entry:
one cache entry per (question, scope) means a result computed for one
principal cannot be handed to another, whatever the storage does.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

RUN_KEY_VERSION = "1.0.0"

#: Bumped when the system prompt changes. A different analyst gives a
#: different answer, legitimately, and the cache must not hide that.
PROMPT_VERSION = "1.0.0"


def normalize(question: str) -> str:
    """The same question, said differently, is the same question.

    Case, surrounding whitespace, repeated spaces, smart quotes and a trailing
    question mark do not change what was asked. Word order and vocabulary do,
    and are left alone: "borrowers with the highest PD" and "the highest-PD
    borrowers" are not provably the same question, and a normaliser that
    decided they were would return one answer to the other.
    """
    text = unicodedata.normalize("NFKC", str(question or ""))
    text = text.replace("’", "'").replace("‘", "'")
    text = text.replace("“", '"').replace("”", '"')
    text = text.replace("—", "-").replace("–", "-")
    text = re.sub(r"\s+", " ", text).strip().lower()
    return text.rstrip("?").strip()


def _hash(payload: Any) -> str:
    body = json.dumps(payload, sort_keys=True, default=str,
                      separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class RunKey:
    """Everything that may legitimately change an answer, in one identity."""

    question: str = ""
    context_hash: str = ""
    clarification: str = ""
    scope: str = ""
    period: str = ""
    data_version: str = ""
    catalogue_version: str = ""
    policy_version: str = ""
    prompt_version: str = PROMPT_VERSION
    tools_version: str = ""
    release_version: str = ""
    #: Not part of the identity. Recorded so a stored entry can say what it
    #: was, which is what makes a cache miss explicable.
    parts: dict[str, Any] = field(default_factory=dict, compare=False)

    def to_dict(self) -> dict[str, Any]:
        return {"version": RUN_KEY_VERSION, "key": self.key,
                "question": self.question, "context_hash": self.context_hash,
                "clarification": self.clarification, "scope": self.scope,
                "period": self.period, "data_version": self.data_version,
                "catalogue_version": self.catalogue_version,
                "policy_version": self.policy_version,
                "prompt_version": self.prompt_version,
                "tools_version": self.tools_version,
                "release_version": self.release_version}

    @property
    def key(self) -> str:
        return _hash([
            RUN_KEY_VERSION, self.question, self.context_hash,
            self.clarification, self.scope, self.period, self.data_version,
            self.catalogue_version, self.policy_version, self.prompt_version,
            self.tools_version, self.release_version,
        ])


def scope_of(principal: Any) -> str:
    """The permission scope, as an identity rather than a name.

    The ROLE and the readable dataset set, not the user id. Two analysts with
    the same permissions asking the same question should get the same answer
    and should share the work; the same question from an analyst and a viewer
    with different visible books should not.
    """
    role = str(getattr(principal, "role", "") or "").upper()
    datasets = sorted(getattr(principal, "datasets", ()) or ())
    return _hash([role, datasets])[:32]


def context_of(turns: list[dict[str, Any]] | None) -> str:
    """The conversation this turn continues.

    Question and answer text only. Timestamps, run ids and latencies differ
    between two identical conversations and would defeat the cache for no
    reason a reader would recognise.
    """
    if not turns:
        return ""
    return _hash([[str(t.get("question") or ""), str(t.get("answer") or "")]
                  for t in turns])[:32]


def build(question: str, principal: Any, *, period: str = "",
          turns: list[dict[str, Any]] | None = None,
          clarification: str = "") -> RunKey:
    """The run key for one question, read from the live governed versions."""
    return RunKey(
        question=normalize(question),
        context_hash=context_of(turns),
        clarification=normalize(clarification),
        scope=scope_of(principal),
        period=str(period or ""),
        data_version=data_version(),
        catalogue_version=catalogue_version(),
        policy_version=policy_version(),
        prompt_version=PROMPT_VERSION,
        tools_version=tools_version(),
        release_version=release_version(),
    )


# ------------------------------------------------------------- the versions
#
# Each one answers "has the thing underneath the answer moved?" and each is
# read rather than assumed, because a version that is hard-coded is a version
# that stops changing when the thing it describes does.


def data_version() -> str:
    """The analytical lake's state: which datasets, at which periods."""
    try:
        from backend.data_access import get_data_source

        source = get_data_source()
        names = sorted(source.datasets())
        latest = {}
        for name in names:
            try:
                periods = source.periods(name)
                latest[name] = periods[-1] if periods else ""
            except Exception:  # noqa: BLE001 - a dataset with no period column
                latest[name] = ""
        return _hash([names, latest])[:32]
    except Exception:  # noqa: BLE001 - no lake means no answer to cache
        return "unavailable"


def catalogue_version() -> str:
    try:
        from backend.data_access.catalog import get_catalog

        catalog = get_catalog()
        return _hash([[d.name, d.version, sorted(d.fields)]
                      for d in catalog.all()])[:32]
    except Exception:  # noqa: BLE001
        return "unavailable"


def policy_version() -> str:
    """Thresholds and governed composites. A moved threshold is a new answer."""
    try:
        from backend.orchestration import composites as cmp

        return _hash([[c.key, [(s.key, s.test, s.value) for s in c.signals]]
                      for c in cmp.COMPOSITES])[:32]
    except Exception:  # noqa: BLE001
        return "unavailable"


def tools_version() -> str:
    try:
        from backend.analyst import tools

        return _hash([[t.name, t.capability, sorted(t.arguments)]
                      for t in tools.REGISTRY])[:32]
    except Exception:  # noqa: BLE001
        return "unavailable"


def release_version() -> str:
    try:
        from backend.build_info import build_info

        info = build_info().to_dict()
        return str(info.get("sha") or info.get("version") or "dev")[:32]
    except Exception:  # noqa: BLE001
        return "dev"


__all__ = ["PROMPT_VERSION", "RUN_KEY_VERSION", "RunKey", "build",
           "catalogue_version", "context_of", "data_version", "normalize",
           "policy_version", "release_version", "scope_of", "tools_version"]
