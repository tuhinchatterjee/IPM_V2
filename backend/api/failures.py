"""
Every way a request can fail, named. P0.10.

The defect this exists to fix
-----------------------------
A complex Contracting investigation returned:

    HTTP 500
    {"error": "internal_error",
     "message": "Something went wrong on the server."}

That is a true statement and a useless one. It does not say whether the
provider was unreachable, the plan could not be built, a dataset was missing, a
relationship was absent, the query failed, a validation refused the answer, the
database was down, the caller lacked permission, or a budget ran out. Every one
of those is a different thing for the person reading it to do, and the same
sentence is shown for all of them.

Worse, it was shown for things that are not faults at all. During Phase 0 the
database was briefly stopped and the SAME 500 appeared — a connection refused,
reported as though CreditProbe had a bug.

The categories
--------------
P0.10 names ten. Each maps to a distinct thing that went wrong and a distinct
thing to do about it:

    PROVIDER      the AI provider was unreachable or refused
    PLANNING      the question could not be turned into a governed plan
    DATA          a dataset or period is missing or unreadable
    RELATIONSHIP  no governed relationship joins what was asked for
    EXECUTION     the query or the runtime failed
    VALIDATION    the answer was computed and did not pass its checks
    PERSISTENCE   the database could not be read or written
    PERMISSION    the caller may not do this
    BUDGET        a governed limit was reached
    UNKNOWN       genuinely unrecognised — and it says so

What a user is told, and what they are not
------------------------------------------
Every message here is written for a credit officer, names the category, and
carries the correlation id so the log can be found. None of them contains a
stack trace, a file path, a SQL fragment, a connection string, an environment
variable or a model id. The detail that helps an engineer goes to the log; the
detail that helps a user goes to the screen; they are not the same detail.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

PROVIDER = "PROVIDER"
PLANNING = "PLANNING"
DATA = "DATA"
RELATIONSHIP = "RELATIONSHIP"
EXECUTION = "EXECUTION"
VALIDATION = "VALIDATION"
PERSISTENCE = "PERSISTENCE"
PERMISSION = "PERMISSION"
BUDGET = "BUDGET"
UNKNOWN = "UNKNOWN"

CATEGORIES: tuple[str, ...] = (
    PROVIDER, PLANNING, DATA, RELATIONSHIP, EXECUTION, VALIDATION,
    PERSISTENCE, PERMISSION, BUDGET, UNKNOWN,
)

#: The HTTP status each category deserves. A missing dataset is not a server
#: fault and a 500 on one tells an operator to look in the wrong place.
STATUS: dict[str, int] = {
    PROVIDER: 503,
    PLANNING: 422,
    DATA: 404,
    RELATIONSHIP: 422,
    EXECUTION: 500,
    VALIDATION: 422,
    PERSISTENCE: 503,
    PERMISSION: 403,
    BUDGET: 429,
    UNKNOWN: 500,
}

#: What the user is told. Written for the person, not for the log.
MESSAGE: dict[str, str] = {
    PROVIDER: ("CreditProbe could not reach its AI provider. The governed "
               "calculations are unaffected; the reading of your question is "
               "what could not be completed. Try again shortly."),
    PLANNING: ("CreditProbe could not turn this question into a governed "
               "analysis. Nothing was computed. Naming the measure, the "
               "population and the period usually resolves it."),
    DATA: ("CreditProbe could not find the governed data this question needs. "
           "Nothing was computed against a partial book."),
    RELATIONSHIP: ("CreditProbe has no governed relationship joining the "
                   "sources this question spans, so it will not guess one. "
                   "A data steward can define it in Data Builder."),
    EXECUTION: ("The analysis failed while running. Nothing partial has been "
                "reported as an answer."),
    VALIDATION: ("The figures were computed and did not pass their checks, so "
                 "CreditProbe is not showing them. This is the product "
                 "working: an answer that fails validation is worse than no "
                 "answer."),
    PERSISTENCE: ("CreditProbe could not reach its database. This is an "
                  "availability problem rather than a problem with your "
                  "question — nothing you asked for was wrong."),
    PERMISSION: "You do not have permission to do this.",
    BUDGET: ("This request reached a governed limit and stopped rather than "
             "spending without a ceiling. Narrowing it usually completes."),
    UNKNOWN: ("Something went wrong that CreditProbe does not recognise. It "
              "has been logged in full."),
}


@dataclass(frozen=True)
class Failure:
    """One failure, categorised, as a user sees it and as a log records it."""

    category: str
    message: str
    correlation_id: str
    status: int
    #: The exception type, for the log and for Agent Operations. Never the
    #: message — an exception's text carries paths and identifiers.
    kind: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "error": self.category.lower(),
            "category": self.category,
            "message": self.message,
            "detail": {"correlation_id": self.correlation_id,
                       "category": self.category},
        }


#: Exception type names, by category. Matched on the NAME rather than by
#: importing every module: this has to work for an exception raised anywhere in
#: the runtime, and importing the world to classify an error is how an error
#: handler becomes the thing that fails.
_BY_NAME: tuple[tuple[str, str], ...] = (
    (PERSISTENCE, r"OperationalError|InterfaceError|DBAPIError|"
                  r"PoolError|DisconnectionError|StorageUnavailable"),
    (PERMISSION, r"NotAuthorised|NotPermitted|NotVisible|PermissionError|"
                 r"Forbidden"),
    (BUDGET, r"Exhausted|BudgetError|RateLimit"),
    (PROVIDER, r"Anthropic|APIConnection|APIStatus|APITimeout|ProviderError|"
               r"Unauthorized|ServiceUnavailable"),
    (RELATIONSHIP, r"NoRelationship|JoinError|UnreachableDataset"),
    (DATA, r"DataAccessError|DatasetNotFound|UnknownDataset|MissingPeriod|"
           r"FileNotFoundError|UnknownAnalysisError"),
    (VALIDATION, r"ContractError|InvariantError|ValidationError|Ungrounded"),
    (PLANNING, r"CannotPlan|PlanError|UnreadableQuestion|LookupError"),
    (EXECUTION, r"CompileError|RuntimeError|DuckDB|Timeout|OSError"),
)

_COMPILED = tuple((category, re.compile(pattern, re.I))
                  for category, pattern in _BY_NAME)


#: Categories a MORE SPECIFIC cause is allowed to override. `RuntimeError` and
#: `OSError` are catch-alls that anything can be wrapped in, so a
#: RuntimeError("could not answer") raised `from` a driver's OperationalError
#: is a persistence failure wearing a generic coat. Reading only the outermost
#: type is how a stopped database was reported as an unknown server fault.
_GENERIC: frozenset[str] = frozenset({EXECUTION, UNKNOWN})


def classify(exc: BaseException) -> str:
    """Which category this exception belongs to.

    By exception TYPE, never by message text. A message is written for a human
    and changes when somebody improves the wording; a type is a contract.

    The whole cause chain is read, and a specific cause beats a generic
    wrapper. The chain is walked with a seen-set because `__context__` can
    cycle, and an error handler that loops is worse than the error.
    """
    seen: set[int] = set()
    generic = ""
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        found = _direct(current)
        if found not in _GENERIC:
            return found
        generic = generic or found
        current = current.__cause__ or current.__context__
    return generic or UNKNOWN


def _direct(exc: BaseException) -> str:
    """The category of one exception, ignoring its causes."""
    name = type(exc).__name__
    for category, pattern in _COMPILED:
        if pattern.search(name):
            return category
    return UNKNOWN


def of(exc: BaseException, correlation_id: str) -> Failure:
    """The categorised failure for an exception."""
    category = classify(exc)
    return Failure(
        category=category,
        message=MESSAGE.get(category, MESSAGE[UNKNOWN]),
        correlation_id=correlation_id,
        status=STATUS.get(category, 500),
        kind=type(exc).__name__,
    )


#: Anything that must never appear in a user-facing message. Checked rather
#: than assumed: the messages above are written by hand today and the check is
#: what keeps that true when somebody adds one in a hurry.
_SECRET = re.compile(
    r"sk-[A-Za-z0-9_\-]{8,}|password\s*=|postgresql\+?\w*://|"
    r"ANTHROPIC_API_KEY|SECRET_KEY|Bearer\s+[A-Za-z0-9._\-]{10,}",
    re.I)


def leaks(message: str) -> bool:
    """Whether a message carries something that must not leave the server."""
    return bool(_SECRET.search(str(message or "")))


__all__ = [
    "BUDGET",
    "CATEGORIES",
    "DATA",
    "EXECUTION",
    "Failure",
    "MESSAGE",
    "PERMISSION",
    "PERSISTENCE",
    "PLANNING",
    "PROVIDER",
    "RELATIONSHIP",
    "STATUS",
    "UNKNOWN",
    "VALIDATION",
    "classify",
    "leaks",
    "of",
]
