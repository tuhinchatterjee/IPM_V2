"""The Early Warning chat domain lock (implementation plan Section 10 /
spec Section F — "non-negotiable"): when a thread is locked to one product
domain, the planner may not silently answer from any other domain's data.

This is a hard allow-list enforced at the one choke point every plan
already passes through (`orchestration/validator.py::validate_plan`), not a
scored preference like `context.py`'s `candidate_domains`/`required_domains`
— those help the planner pick a good dataset when several could answer a
question; a domain lock removes the choice entirely. A plan step whose
registered analysis requires a dataset outside the locked domain is
rejected exactly like an unregistered analysis or an out-of-contract
parameter, with a reason the caller can show as "not available in this
domain" rather than a value quietly computed from somewhere else.
"""

from __future__ import annotations

from dataclasses import dataclass

EARLY_WARNING = "early_warning"

#: Datasets the Early Warning domain lock allows. Extended as EWS-specific
#: analyses are registered against the Phase 4 domain; anything not listed
#: here is refused while a thread is locked to "early_warning".
DOMAIN_DATASETS: dict[str, frozenset[str]] = {
    EARLY_WARNING: frozenset({
        "early_warning_borrower_month",
        "early_warning_signal_observation",
        "early_warning_network_edge_snapshot",
    }),
}


@dataclass(frozen=True)
class DomainViolation:
    analysis_id: str
    dataset: str
    domain_lock: str


def datasets_for(analysis_id: str) -> tuple[str, ...]:
    """The datasets one registered analysis actually reads, from its own
    declared contract — never guessed from the analysis id's name."""
    from backend.engine.registry import UnknownAnalysisError, get_registry

    try:
        analysis = get_registry().get(analysis_id)
    except UnknownAnalysisError:
        return ()
    return tuple(analysis.contract.required_datasets)


def check_plan(steps, domain_lock: str | None) -> list[DomainViolation]:
    """Every step whose analysis needs a dataset outside the locked
    domain's allow-list. Empty means the plan is entirely inside the lock."""
    if not domain_lock:
        return []
    allowed = DOMAIN_DATASETS.get(domain_lock)
    if allowed is None:
        return []
    violations: list[DomainViolation] = []
    for step in steps:
        for dataset in datasets_for(step.analysis_id):
            if dataset not in allowed:
                violations.append(DomainViolation(
                    analysis_id=step.analysis_id, dataset=dataset, domain_lock=domain_lock))
    return violations


def refusal_message(violations: list[DomainViolation]) -> str:
    """What the assistant says instead of silently answering from another
    domain — spec Section F: "say the required field is not presently
    available in the EWS snapshot, or offer an appropriate navigation path
    outside Early Warning."""
    datasets = sorted({v.dataset for v in violations})
    return (
        "That needs data outside the Early Warning domain "
        f"({', '.join(datasets)}), which is not presently available in the "
        "Early Warning snapshot. Ask outside Early Warning for that, or "
        "check whether the field should be added to the Early Warning "
        "pipeline's source lineage."
    )
