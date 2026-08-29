"""
The Intelligence Release, its promotion gate, and Demo Safe Mode. Part D.

``references``  what an Intelligence Release points at, and which of those
                moving makes it STALE.
``promotion``   the thirteen conditions §128 requires before a release may be
                promoted — none of them an average.
``demo_safe``   the twelve conditions §130 requires before an answer may be
                shown to a client, checked per ANSWER rather than per session.
"""

from backend.release import demo_safe, promotion, references

__all__ = ["demo_safe", "promotion", "references"]
