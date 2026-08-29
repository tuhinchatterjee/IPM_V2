"""
The Intelligence Release, its promotion gate, and Demo Safe Mode. Part D.

``references``  what an Intelligence Release points at, and which of those
                moving makes it STALE.
``promotion``   the thirteen conditions §128 requires before a release may be
                promoted — none of them an average.
``demo_safe``   the twelve conditions §130 requires before an answer may be
                shown to a client, checked per ANSWER rather than per session.
``agentic_gate`` the eleven conditions §134 requires before the agentic layer
                may be reported complete — a separate gate, because a product
                with excellent judgement and a dead worker answers every
                question well and never notices a deteriorating portfolio.
"""

from backend.release import agentic_gate, demo_safe, promotion, references

__all__ = ["agentic_gate", "demo_safe", "promotion", "references"]
