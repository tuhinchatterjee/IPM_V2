"""What the investigation actually found, and how it can be checked. §42, §43.

An agent that reports what it read is reporting from memory. The whole point
of putting a model in front of governed data is that the figures do not come
from the model, so the record of what came back has to be separate from the
model's account of it — and it has to be checkable afterwards, by a person who
was not there.

So every tool call produces an `Observation`: the tool, the arguments, what
came back, how long it took, and a content hash of the rows. The `Ledger` holds
them in order. Two things read it:

  * **Grounding** (§42). Every number in the final answer must appear in the
    ledger. A figure the model produced that is in no observation is not a
    figure — it is a sentence that looks like one, and it is removed.
  * **The Trace** (§43). The ledger IS the investigation: which tools, in what
    order, over which datasets, returning how many rows.

The hash is over the VALUES, canonicalised — sorted keys, fixed float
formatting — so the same query returning the same rows hashes the same on a
different machine, which is what makes §11's reproducibility claim checkable
rather than asserted.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

EVIDENCE_VERSION = "1.0.0"

#: How many significant figures a value is hashed at. Two runs of the same
#: query can differ in the last bits of a float without differing in any way a
#: reader could see, and a hash that changes for that reason is a hash nobody
#: can use.
HASH_PRECISION = 9


def canonical(value: Any) -> Any:
    """`value`, in the one form it hashes from."""
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return str(value)
        return float(f"{value:.{HASH_PRECISION}g}")
    if isinstance(value, dict):
        return {str(k): canonical(v) for k, v in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [canonical(v) for v in value]
    return value


def digest(value: Any) -> str:
    payload = json.dumps(canonical(value), sort_keys=True, default=str,
                         separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


@dataclass
class Observation:
    """One governed tool call and what it returned."""

    tool: str
    arguments: dict[str, Any] = field(default_factory=dict)
    #: The rows the tool produced, already truncated to what the model sees.
    rows: list[dict[str, Any]] = field(default_factory=list)
    #: How many rows the query actually matched, before truncation.
    total_rows: int = 0
    columns: list[str] = field(default_factory=list)
    datasets: list[str] = field(default_factory=list)
    period: str = ""
    #: A sentence for the Trace: what this call was for.
    purpose: str = ""
    #: Present when the tool refused or could not run. An observation with a
    #: refusal is still an observation — the model needs to see it to choose
    #: something else, and the Trace needs it to explain a gap.
    refused: str = ""
    duration_ms: int = 0
    #: The governed plan the tool built, when it built one.
    plan: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.refused

    def hash(self) -> str:
        return digest({"tool": self.tool, "arguments": self.arguments,
                       "rows": self.rows, "total_rows": self.total_rows})

    def to_dict(self) -> dict[str, Any]:
        return {"tool": self.tool, "arguments": dict(self.arguments),
                "rows": list(self.rows), "total_rows": self.total_rows,
                "columns": list(self.columns), "datasets": list(self.datasets),
                "period": self.period, "purpose": self.purpose,
                "refused": self.refused, "duration_ms": self.duration_ms,
                "hash": self.hash(), "ok": self.ok}


#: A number in prose. Handles 1,234.5, 12%, 0.85x, SAR 4.2bn.
_NUMBER = re.compile(r"-?\d[\d,]*(?:\.\d+)?")

#: Numbers a claim may carry without an observation behind it: a year, a small
#: count that is being SAID rather than measured ("the top 10"), a percentage
#: of 100. Checking these produces false refusals and teaches everyone to
#: ignore the grounding report.
_UNREMARKABLE = frozenset({"0", "1", "2", "3", "4", "5", "10", "100"})


@dataclass
class Ledger:
    """Every observation this investigation made, in order."""

    observations: list[Observation] = field(default_factory=list)
    started: float = field(default_factory=time.perf_counter)

    def add(self, observation: Observation) -> Observation:
        self.observations.append(observation)
        return observation

    def __len__(self) -> int:
        return len(self.observations)

    @property
    def calls(self) -> int:
        return len(self.observations)

    @property
    def datasets(self) -> list[str]:
        seen: list[str] = []
        for observation in self.observations:
            for name in observation.datasets:
                if name not in seen:
                    seen.append(name)
        return seen

    @property
    def refusals(self) -> list[Observation]:
        return [o for o in self.observations if o.refused]

    def values(self) -> set[str]:
        """Every number that appears anywhere in what the tools returned.

        As STRINGS, canonicalised, because the claim being checked is a string
        in a sentence. `1234.5`, `1,234.5` and `1234.50` are the same figure
        and a reader would say so.
        """
        found: set[str] = set()
        for observation in self.observations:
            for row in observation.rows:
                for value in row.values():
                    found.update(_forms(value))
            found.update(_forms(observation.total_rows))
        return found

    def ungrounded(self, text: str) -> list[str]:
        """Numbers in `text` that no observation supports. §42.

        The check is deliberately generous about FORM and strict about
        EXISTENCE: any rounding of a figure that is in the ledger passes, and a
        figure that is in no observation fails however plausible it looks.
        """
        known = self.values()
        missing: list[str] = []
        for match in _NUMBER.finditer(text or ""):
            raw = match.group(0)
            plain = raw.replace(",", "")
            if plain in _UNREMARKABLE or plain.rstrip("0").rstrip(".") == "":
                continue
            if plain in known:
                continue
            if any(plain in form or form in plain for form in known):
                continue
            missing.append(raw)
        return missing

    def to_dict(self) -> dict[str, Any]:
        return {"version": EVIDENCE_VERSION, "calls": self.calls,
                "datasets": self.datasets,
                "observations": [o.to_dict() for o in self.observations],
                "hash": digest([o.hash() for o in self.observations])}


def _forms(value: Any) -> set[str]:
    """Every string a reader might write this value as."""
    if value is None or isinstance(value, bool):
        return set()
    if isinstance(value, int):
        return {str(value)}
    if isinstance(value, float):
        out = {f"{value:.{HASH_PRECISION}g}"}
        for places in (0, 1, 2, 3):
            out.add(f"{value:.{places}f}")
        out.add(str(value))
        return {s.rstrip(".") for s in out}
    text = str(value)
    return {m.group(0).replace(",", "") for m in _NUMBER.finditer(text)}


__all__ = ["EVIDENCE_VERSION", "HASH_PRECISION", "Ledger", "Observation",
           "canonical", "digest"]
