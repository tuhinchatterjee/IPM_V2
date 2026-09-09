"""Which datasets belong to scorecard validation, and who may read them.

The problem this module exists for
------------------------------------
CreditProbe now has two conversational surfaces that can reach the governed
data lake. The general Cockpit answers portfolio questions across the credit
book. The Scorecard Validation page answers model-risk questions about three
scorecards and nothing else.

Those two scopes must not overlap, and they must not overlap in *both*
directions, which is the part that is easy to get half right:

* An independent validator working on the Saudi SME scorecard must not be
  able to pull corporate covenant breaches into the conversation. A
  specialist that CAN read the whole book is not a specialist; it is the
  general Cockpit with a different page header, and the independence the
  validation is supposed to have is gone the first time somebody phrases a
  question loosely.

* The general Cockpit must not be able to read the scorecard validation
  datasets at all. Those are record-level model inputs and realised
  outcomes: the population a scorecard was fitted on, every variable that
  went into it, and who defaulted. A portfolio question has no business
  reaching them, and a screen that lets somebody ask for "the KS of the
  application scorecard" in the general chat has quietly moved a model
  validation out of the environment that governs it.

What is NOT restricted
------------------------
The governed *aggregate* scorecard metrics that the Retail Risk Lens and the
Playbook committee packs already publish. Those are approved outputs — a Gini
for a named month, computed by the same kernel, reviewed and released. They
are not conversational access to the record-level population, and blocking
them would break two shipped surfaces to defend a boundary they never
crossed. The restriction here is on **datasets**, not on published metrics.

How the restriction is enforced
---------------------------------
Not by the page hiding options, not by an instruction in a prompt, and not by
the frontend sending the right identifier. Two independent backend gates, so
that defeating one is not enough:

1. **Discovery.** `orchestration/context.py` builds the general Cockpit's
   dataset universe. Restricted datasets are dropped there, so they cannot be
   searched, autocompleted, suggested, matched to a subject, or picked up by
   a planner scanning for a table that has the word "score" in it.

2. **Execution.** `runtime/validation.py::_scan` checks every dataset a plan
   reads, whatever produced the plan. A dataset ID that arrives by any other
   route — typed by a user, replayed from a saved query, guessed by a model,
   or injected through the text of a document the model was asked to read —
   is refused there, before a single row is read.

The second gate is the one that matters. The first is a courtesy: it stops
the model proposing something that would then be refused, which is a better
conversation. Removing the first would be a usability regression. Removing
the second would be a security hole.

Fail closed
-------------
`GENERAL` is the default scope, and an unknown caller gets it. A dataset that
is restricted stays restricted unless the caller has explicitly declared the
validation scope, which only the Scorecard Validation services do.
"""

from __future__ import annotations

from typing import Any

# ------------------------------------------------------------ the three domains

#: §4. The only three scorecard domains that exist, and the only three the
#: specialist environment may read. A fourth would need a deliberate entry
#: here rather than a dataset that happens to be named plausibly.
SCORECARD_APPLICATION = "scorecard_retail_application"
SCORECARD_BEHAVIOUR = "scorecard_retail_behaviour"
SCORECARD_SME = "scorecard_saudi_sme"

SCORECARD_DOMAINS: tuple[str, ...] = (
    SCORECARD_APPLICATION, SCORECARD_BEHAVIOUR, SCORECARD_SME,
)

DOMAIN_LABELS: dict[str, str] = {
    SCORECARD_APPLICATION: "Retail Application Scorecard",
    SCORECARD_BEHAVIOUR: "Retail Behaviour Scorecard",
    SCORECARD_SME: "Saudi SME Scorecard",
}

#: The scorecard type each domain validates, in the vocabulary the existing
#: engine already uses (`backend/scorecard/variables.py`). Kept as a map
#: rather than derived from the string, because the domain identifier is a
#: permissions token and the scorecard type is an engine argument; letting one
#: be parsed out of the other couples a security boundary to a naming habit.
DOMAIN_SCORECARD_TYPE: dict[str, str] = {
    SCORECARD_APPLICATION: "APPLICATION",
    SCORECARD_BEHAVIOUR: "BEHAVIORAL",
    SCORECARD_SME: "SME",
}

SCORECARD_TYPE_DOMAIN: dict[str, str] = {
    v: k for k, v in DOMAIN_SCORECARD_TYPE.items()
}

# ------------------------------------------------------------------- the scopes

#: The general Cockpit, every general Ask handler, every saved query replayed
#: through them, and anything that did not say otherwise.
GENERAL = "GENERAL"

#: The Scorecard Validation page and its services. Declared explicitly at each
#: call site, never inferred from a request header or a page name.
VALIDATION = "VALIDATION"

#: A published metric definition being computed — the Retail Risk Lens, a
#: Playbook committee pack, the Metric Catalogue.
#:
#: This scope exists because the boundary is about *conversational* access,
#: not about the bytes. A published metric is a governed artefact: its formula
#: was written, reviewed and released, its period rule is declared, and what
#: it returns is one approved aggregate. Computing it is not the same act as
#: letting a model compose an arbitrary plan over the same rows, and refusing
#: it would break two shipped surfaces to defend a line they never crossed.
#:
#: The distinction is enforceable rather than nominal: this scope is passed by
#: `backend/metrics/service.py` when it runs a plan it built itself from a
#: registered `MetricDefinition`. No plan that came from a model reaches it,
#: because no model can register a metric definition.
GOVERNED_METRIC = "GOVERNED_METRIC"

SCOPES: tuple[str, ...] = (GENERAL, VALIDATION, GOVERNED_METRIC)

#: The scopes that may read a restricted dataset. Written as an allowlist so
#: that adding a scope does not silently grant it access.
MAY_READ_RESTRICTED: frozenset[str] = frozenset({VALIDATION, GOVERNED_METRIC})


class DomainRefused(PermissionError):
    """A caller asked for a dataset outside the scope it declared.

    A `PermissionError` rather than a `ValueError`: the dataset exists and the
    name was spelled correctly. What failed is authorisation, and a handler
    that turns this into "no such dataset" would be more informative to an
    attacker than to a user.
    """

    def __init__(self, dataset: str, scope: str, message: str = "") -> None:
        self.dataset = dataset
        self.scope = scope
        super().__init__(message or refusal(dataset, scope))


# ------------------------------------------------------------ dataset ownership

#: Which domain each restricted dataset belongs to.
#:
#: Written down rather than matched on a prefix. A prefix rule reads well
#: until somebody adds `retail_application_marketing_response`, which is not a
#: scorecard dataset, and is then silently unreachable from the general
#: Cockpit for a reason nobody can find. An explicit map fails the other way:
#: a new scorecard dataset is readable by the general Cockpit until it is
#: registered here, which a test catches.
DATASET_DOMAIN: dict[str, str] = {
    # Retail Application — built by backend/scorecard/build.py.
    "retail_application_scorecard_monthly_validation": SCORECARD_APPLICATION,
    "retail_application_scorecard_development_reference": SCORECARD_APPLICATION,
    # Retail Behaviour.
    "retail_behavioral_scorecard_monthly_validation": SCORECARD_BEHAVIOUR,
    "retail_behavioral_scorecard_development_reference": SCORECARD_BEHAVIOUR,
    # Saudi SME — built by backend/scorecard/sme/build.py.
    "sme_scorecard_monthly_validation": SCORECARD_SME,
    "sme_scorecard_development_reference": SCORECARD_SME,
    "sme_scorecard_decisions": SCORECARD_SME,
}


def restricted_datasets() -> frozenset[str]:
    """Every dataset the general Cockpit may not read."""
    return frozenset(DATASET_DOMAIN)


def domain_of(dataset: str) -> str:
    """The scorecard domain this dataset belongs to, or "" if it is not one."""
    return DATASET_DOMAIN.get(str(dataset or "").strip(), "")


def is_restricted(dataset: str) -> bool:
    return bool(domain_of(dataset))


def datasets_for(domain: str) -> tuple[str, ...]:
    """Every dataset in one scorecard domain, in a stable order."""
    return tuple(sorted(n for n, d in DATASET_DOMAIN.items() if d == domain))


def scorecard_type_of(dataset: str) -> str:
    """The engine's scorecard type for this dataset, or ""."""
    return DOMAIN_SCORECARD_TYPE.get(domain_of(dataset), "")


# --------------------------------------------------------------- the two gates


def permitted(dataset: str, *, scope: str = GENERAL) -> bool:
    """May a caller in this scope read this dataset?

    Everything that is not a scorecard dataset is permitted in both scopes —
    this module restricts three domains, it does not become a second
    authorisation system for the rest of the catalogue. Within the three, only
    the validation scope passes.
    """
    if not is_restricted(dataset):
        return True
    return scope in MAY_READ_RESTRICTED


def require(dataset: str, *, scope: str = GENERAL) -> None:
    """Raise `DomainRefused` unless this scope may read this dataset."""
    if not permitted(dataset, scope=scope):
        raise DomainRefused(dataset, scope)


def refusal(dataset: str, scope: str = GENERAL) -> str:
    """What to say when the answer is no.

    Says where the analysis lives rather than only that it was refused. A
    validator who asked in the wrong place needs a direction, and "not
    available" without one reads as a broken product rather than a governed
    one.
    """
    domain = domain_of(dataset)
    label = DOMAIN_LABELS.get(domain, "a scorecard model")
    if scope in MAY_READ_RESTRICTED:  # pragma: no cover - never refuses here
        return (f"{dataset} is not one of the three scorecard domains this "
                "environment validates.")
    return (
        f"{label} data is not available here. Record-level scorecard "
        "populations, model inputs and realised outcomes are read only in "
        "Scorecard Validation, where the model, its version and the maturity "
        "of the cohort are part of every answer. This analysis is available "
        "in Scorecard Validation."
    )


#: What the general Cockpit says instead of running the query. Kept as one
#: sentence so it can be asserted on in a test and rendered as a chip in the
#: UI without either copy drifting from the other.
REDIRECT_SENTENCE = "This analysis is available in Scorecard Validation."

#: Where to send them. A route rather than a free-text instruction, so the
#: general Cockpit can offer a navigation action the user can click.
REDIRECT_ROUTE = "/scorecard-validation"


def redirect_action() -> dict[str, str]:
    """The safe navigation offer that replaces the refused query."""
    return {
        "kind": "navigate",
        "label": "Open Scorecard Validation",
        "route": REDIRECT_ROUTE,
        "why": REDIRECT_SENTENCE,
    }


# ------------------------------------------------- the specialist's own bounds


def validation_domain_allowed(domain: str) -> bool:
    """Is this one of the three domains the specialist environment validates?

    The other direction of the boundary. `permitted` stops the general Cockpit
    reaching in; this stops the specialist reaching out, and it is a positive
    allowlist rather than a list of things to block: a domain that does not
    appear in `SCORECARD_DOMAINS` is refused whether or not anybody thought to
    name it.
    """
    return str(domain or "") in SCORECARD_DOMAINS


def require_validation_domain(domain: str) -> str:
    """Return the domain, or raise if the specialist may not read it."""
    if not validation_domain_allowed(domain):
        raise DomainRefused(
            str(domain), VALIDATION,
            f"Scorecard Validation reads three domains — "
            f"{', '.join(DOMAIN_LABELS[d] for d in SCORECARD_DOMAINS)} — and "
            f"{domain!r} is not one of them. This environment is scoped to "
            "scorecard model risk; portfolio, IFRS 9, covenant, planner and "
            "committee data are read elsewhere.")
    return domain


def require_scorecard_type(scorecard_type: str) -> str:
    """Return the engine's scorecard type, or raise.

    The same gate expressed in the vocabulary the calculation kernels take,
    so a tool that receives `scorecard_type` from a model-authored parameter
    is checked without first having to translate it into a domain.
    """
    wanted = str(scorecard_type or "").strip().upper()
    if wanted not in SCORECARD_TYPE_DOMAIN:
        raise DomainRefused(
            wanted, VALIDATION,
            f"{scorecard_type!r} is not a scorecard this environment "
            f"validates. The three are "
            f"{', '.join(sorted(SCORECARD_TYPE_DOMAIN))}.")
    return wanted


def summary() -> dict[str, Any]:
    """What the boundary is, for a report or a governance screen."""
    return {
        "domains": [
            {"domain": d, "label": DOMAIN_LABELS[d],
             "scorecard_type": DOMAIN_SCORECARD_TYPE[d],
             "datasets": list(datasets_for(d))}
            for d in SCORECARD_DOMAINS
        ],
        "restricted_datasets": sorted(restricted_datasets()),
        "scopes": list(SCOPES),
        "general_cockpit_may_read": [],
        "redirect": redirect_action(),
        "what_is_not_restricted": (
            "Published aggregate scorecard metrics. The Retail Risk Lens and "
            "Playbook committee packs read approved metric outputs, not these "
            "record-level populations, and are unaffected."),
    }


__all__ = [
    "DATASET_DOMAIN", "DOMAIN_LABELS", "DOMAIN_SCORECARD_TYPE", "GENERAL",
    "GOVERNED_METRIC", "MAY_READ_RESTRICTED",
    "REDIRECT_ROUTE", "REDIRECT_SENTENCE", "SCORECARD_APPLICATION",
    "SCORECARD_BEHAVIOUR", "SCORECARD_DOMAINS", "SCORECARD_SME",
    "SCORECARD_TYPE_DOMAIN", "SCOPES", "VALIDATION", "DomainRefused",
    "datasets_for", "domain_of", "is_restricted", "permitted",
    "redirect_action", "refusal", "require", "require_scorecard_type",
    "require_validation_domain", "restricted_datasets", "scorecard_type_of",
    "summary", "validation_domain_allowed",
]
