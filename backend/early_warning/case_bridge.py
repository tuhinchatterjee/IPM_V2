"""Bridges an Early Warning V2 borrower-month score into a `RiskCase`,
reusing the platform's one generic case table and its one versioned
severity formula — never a parallel Early Warning case table, per the
plan's explicit "do not duplicate Investigations/Messages/Cases" rule.

`about="early-warning-v2"` is the dedupe discriminator: escalating the same
borrower again in the same period updates the existing case rather than
creating a duplicate (`backend.agentic.cases.upsert`'s own dedupe_key
mechanism, unchanged).
"""

from __future__ import annotations

from typing import Any

from backend.agentic import cases as agentic_cases
from backend.agentic import severity as sv

ABOUT = "early-warning-v2"


def draft_for(row: dict[str, Any]) -> agentic_cases.Draft:
    """Build a case Draft from one `early_warning_borrower_month` row."""
    score = sv.compute(
        exposure=row.get("exposure"),
        movement=None,  # month-over-month movement is available via history; omitted for the single-row case
        adverse_signals=int(row.get("signal_count_fired") or 0),
        total_signals=123,
        appetite_breached="unwaived_covenant_breach_floors_high" in (row.get("overrides_applied") or ""),
        data_confidence=1.0,
    )
    band = row.get("ews_band", "LOW")
    conclusion = (
        f"{row.get('customer_name', row.get('customer_id'))} scores {row.get('ews_score', 0):.1f} "
        f"({band}) for {row.get('snapshot_month')}: classifier {row.get('classifier_band')} "
        f"({row.get('classifier_score', 0):.1f}), T&A {row.get('ta_band')} ({row.get('ta_score', 0):.1f})."
    )
    why = (
        f"Dominant driver: {row.get('dominant_driver') or 'none — no live trigger fired'}. "
        f"Overrides applied: {row.get('overrides_applied') or 'none'}."
    )
    return agentic_cases.Draft(
        level="BORROWER",
        title=f"Early Warning: {row.get('customer_name', row.get('customer_id'))} — {band}",
        period=row.get("snapshot_month", ""),
        entity=row.get("customer_name", row.get("customer_id", "")),
        entity_id=row.get("customer_id", ""),
        entity_kind="borrower",
        conclusion=conclusion,
        why=why,
        about=ABOUT,
        exposure=row.get("exposure"),
        exposure_unit="SAR mn",
        metrics=[
            {"name": "ews_score", "value": row.get("ews_score")},
            {"name": "classifier_score", "value": row.get("classifier_score")},
            {"name": "ta_score", "value": row.get("ta_score")},
        ],
        signals=[row.get("dominant_driver")] if row.get("dominant_driver") else [],
        evidence={"methodology_version": row.get("methodology_version"),
                   "ews_band": band, "classifier_band": row.get("classifier_band"),
                   "ta_band": row.get("ta_band")},
        score=score,
        evidence_coverage=1.0 if row.get("signal_count_fired") else 0.5,
    )


#: What the escalation wrote on the case, which a later refresh must not
#: destroy. These are not derived from the borrower-month row — they record
#: which matrix version routed the case and to which cell — so a draft built
#: from the row alone does not contain them and would replace them with
#: nothing.
ESCALATION_KEYS = ("escalation_version", "routing")


def upsert_case(session, row: dict[str, Any]):
    """Refresh the borrower's case from the current month's score.

    The shared case machinery replaces `evidence` wholesale on every
    refresh, which is right for the fields that describe the score: they are
    recomputed and the newest reading wins. It is wrong for the escalation
    record, which is history rather than a reading — and the readiness run
    found that Inform, whose whole contract is that it changes nothing,
    silently erased which matrix version had routed the case and where it
    had been routed to. The audit trail was gone and nothing said so.

    So the escalation's own keys are carried forward across the refresh.
    """
    from sqlalchemy import select

    from backend.models.platform import RiskCase

    draft = draft_for(row)
    existing = session.execute(
        select(RiskCase).where(RiskCase.dedupe_key == draft.key)
    ).scalar_one_or_none()
    if existing is not None:
        carried = {k: v for k, v in (existing.evidence or {}).items()
                    if k in ESCALATION_KEYS}
        if carried:
            draft.evidence = {**draft.evidence, **carried}
    return agentic_cases.upsert(session, draft, actor_agent="early_warning_v2")
