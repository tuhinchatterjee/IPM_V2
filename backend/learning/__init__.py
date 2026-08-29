"""
User feedback, learning observations and governed local learning. §7-§24.

    feedback     the question, the five answers, the immutable event
    observation  every question, labelled or not
    candidate    what a correction becomes, and the nine statuses it moves
                 through
    preference   channel A: what may change immediately, per user
    guard        §11, proved: raw feedback cannot change production
    release      channel B's frozen Learning Release, and rollback
    replay       current production versus a candidate release
    models       local auxiliary models, trained and activated under governance
"""

from backend.learning import (  # noqa: F401
    candidate,
    feedback,
    guard,
    models,
    observation,
    preference,
    release,
    replay,
)

__all__ = ["candidate", "feedback", "guard", "models", "observation",
           "preference", "release", "replay"]
