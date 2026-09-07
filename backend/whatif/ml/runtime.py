"""
Whether the ML methodology can run HERE, and what to say when it cannot.

The failure this exists for
---------------------------
XGBoost is a Python wrapper around a compiled library, and on macOS that
library needs OpenMP, which Apple does not ship. So `import xgboost` on a
developer's laptop raises

    XGBoostError: ... Library not loaded: @rpath/libomp.dylib

and the product, having no answer to that, showed it. A credit officer read a
dynamic-linker path where an expected credit loss should have been, and had no
way to tell whether the model was broken, the data was broken, or the product
was.

Two things follow, and both are the point of this module.

**The check happens BEFORE the methodology is offered.** A gate that lists a
methodology this installation cannot run is asking a question with a wrong
answer in it. `available()` is cheap, cached, and consulted where the choice is
presented.

**The message is about the INSTALLATION, in the reader's terms**, with the
command that fixes it — and the Delta Model, which needs none of this, named as
the way to keep working in the meantime. It is never a traceback.

What this deliberately does not do
-----------------------------------
It does not install anything. A product that runs a package manager out of its
own request handler is a product that can change the machine it is running on
while somebody is reading a number off it. The command is PRINTED; a person
runs it.
"""

from __future__ import annotations

import functools
import platform
import sys
from dataclasses import dataclass
from typing import Any

RUNTIME_VERSION = "1.0.0"

#: What to do about it, per platform. Keyed on `sys.platform`.
REMEDY: dict[str, dict[str, str]] = {
    "darwin": {
        "cause": (
            "XGBoost is a compiled library and needs OpenMP, which macOS does "
            "not ship. Without it the Python package installs cleanly and "
            "then fails to load."),
        "command": "brew install libomp",
        "then": "Restart the CreditProbe backend.",
    },
    "linux": {
        "cause": (
            "XGBoost needs a system OpenMP runtime. Most distributions ship "
            "it; a slim container image often does not."),
        "command": "apt-get install -y libgomp1",
        "then": "Restart the CreditProbe backend.",
    },
    "win32": {
        "cause": (
            "XGBoost needs the Microsoft Visual C++ runtime, which is not "
            "part of a bare Python installation."),
        "command": "Install the Microsoft Visual C++ Redistributable (x64).",
        "then": "Restart the CreditProbe backend.",
    },
}

FALLBACK = (
    "The Delta Model needs none of this. It is the governed methodology, it "
    "prices every scenario in this product, and choosing it costs you the "
    "model comparison and nothing else.")


@dataclass(frozen=True)
class Availability:
    """Whether XGBoost loads here, and what to say if it does not."""

    available: bool
    version: str = ""
    platform_name: str = ""
    reason: str = ""
    cause: str = ""
    command: str = ""
    then: str = ""
    #: The raw loader error, kept for the log and for a support ticket. It is
    #: never what the screen shows.
    detail: str = ""

    def message(self) -> str:
        """One paragraph, for a person who is not going to read a traceback."""
        if self.available:
            return (f"XGBoost {self.version} is available on this "
                    f"installation.")
        parts = ["The ML methodology cannot run on this installation."]
        if self.cause:
            parts.append(self.cause)
        if self.command:
            parts.append(f"To enable it: {self.command}"
                         + (f" {self.then}" if self.then else ""))
        parts.append(FALLBACK)
        return " ".join(parts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "version": self.version,
            "platform": self.platform_name,
            "reason": self.reason,
            "cause": self.cause,
            "command": self.command,
            "then": self.then,
            "message": self.message(),
            "fallback": FALLBACK,
        }


def _remedy() -> dict[str, str]:
    return REMEDY.get(sys.platform, {
        "cause": "XGBoost could not be loaded on this platform.",
        "command": "Reinstall the backend dependencies with `uv sync`.",
        "then": "Restart the CreditProbe backend."})


@functools.lru_cache(maxsize=1)
def check() -> Availability:
    """Try the import once, and remember the answer.

    Cached because it is consulted on the methodology gate, which is on the
    path of every scenario. An installation does not gain OpenMP while it is
    running, and one that does is restarted.
    """
    name = f"{platform.system()} {platform.machine()}"
    try:
        import xgboost  # noqa: PLC0415 - the whole point is to try it here
    except ImportError as e:
        remedy = _remedy()
        return Availability(
            available=False, platform_name=name,
            reason="XGBoost is not installed.",
            cause="The xgboost package is not installed in this environment.",
            command="uv sync", then=remedy["then"], detail=str(e))
    except Exception as e:  # noqa: BLE001 - a loader error is not an ImportError
        # This is the macOS case. `xgboost` imports and its compiled core
        # raises, so catching ImportError alone would have let the traceback
        # through — which is exactly what happened.
        remedy = _remedy()
        return Availability(
            available=False, platform_name=name,
            reason="XGBoost is installed but its compiled library will not load.",
            cause=remedy["cause"], command=remedy["command"],
            then=remedy["then"], detail=str(e))
    return Availability(available=True,
                        version=str(getattr(xgboost, "__version__", "")),
                        platform_name=name)


def available() -> bool:
    return check().available


def require() -> None:
    """Raise a reader-facing error rather than a linker one."""
    found = check()
    if not found.available:
        raise MLUnavailable(found.message())


class MLUnavailable(RuntimeError):
    """The ML methodology cannot run here, said in the reader's terms."""


def describe() -> dict[str, Any]:
    """The environment panel on the Model Configuration screen."""
    found = check()
    return {
        **found.to_dict(),
        "preflight_version": RUNTIME_VERSION,
        "python": platform.python_version(),
        "xgboost_version": found.version,
        "statement": (
            "This is checked before the methodology is offered, not after a "
            "scenario has been composed. A gate that lists a methodology this "
            "installation cannot run is asking a question with a wrong answer "
            "in it."),
    }


__all__ = ["FALLBACK", "REMEDY", "RUNTIME_VERSION", "Availability",
           "MLUnavailable", "available", "check", "describe", "require"]
