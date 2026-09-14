"""Document Intelligence — a Playbook document as a governed, living object.

The service boundary §25 asks for: everything a dashboard shows is computed
here, from rows, with the reason kept beside the number. No dashboard logic
lives in a frontend component, and nothing in this package calls a provider —
a percentage an LLM felt was right is exactly what §4 forbids.
"""

from backend.playbook.intelligence import (
    adopt,
    binding,
    compare,
    context,
    governance,
    profile,
    readiness,
    sections,
    service,
)
from backend.playbook.intelligence.service import (
    Dashboard,
    NotPermitted,
    UnknownDocumentType,
    classify,
    dashboard,
    ensure_profile,
    get_profile,
)

__all__ = ["Dashboard", "NotPermitted", "adopt", "binding", "classify",
           "compare", "context",
           "dashboard", "governance",
           "ensure_profile", "get_profile", "profile", "readiness", "sections",
           "service",
           "UnknownDocumentType"]
