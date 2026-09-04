"""Calculating a pack: figures in, findings raised, stale commentary flagged.

This is what "Generate" does. It is deliberately one operation with four
ordered effects, because doing them separately lets a pack exist in a state
where the numbers have moved and the prose about them has not:

    1. every calculated block gets a fresh snapshot, at a new pack version
    2. every narrative written about a figure that MOVED is marked stale
    3. the template's materiality rules are run over the new figures
    4. findings are raised, refreshed, or left alone by fingerprint

Step two is the one that earns its keep. A pack whose default-rate commentary
says "broadly stable" over a number that has since moved forty basis points is
worse than a pack with no commentary, because a reader believes it.

What is never done here
-----------------------
No language model is called. Generation produces figures and findings, both
deterministic; the words are written afterwards by `backend.playbook.narrative`
against the snapshots this module wrote. Keeping them apart is what lets the
figures be regenerated without re-drafting the prose, and lets the prose be
re-drafted without touching the figures.

An approved pack is never regenerated. `access.assert_editable` refuses, which
is the whole reason a tabled pack shows the same numbers next quarter.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from backend.models.playbook import (
    CALCULATED_BLOCK_TYPES,
    SOURCE_SYSTEM,
    SOURCE_UI,
    PlaybookBlock,
    PlaybookFinding,
    PlaybookPack,
    PlaybookSection,
    PlaybookSnapshot,
    PlaybookTemplate,
)
from backend.playbook import access, materiality, readiness, service
from backend.playbook import snapshots as snap
from backend.playbook.access import CONTRIBUTOR

logger = logging.getLogger(__name__)

#: A figure has "moved" for the purpose of staleness when it changes by more
#: than this, relative to where it was. Not zero: a recomputation that shifts
#: a percentage in the fifteenth decimal place is floating-point noise, and
#: marking every narrative in the pack stale over it would train people to
#: click past the warning.
MOVED = 1e-9

#: Statuses whose findings a regeneration leaves entirely alone. Somebody
#: has already dealt with these and re-raising them is how a findings list
#: becomes something people scroll past.
SETTLED = frozenset({"DISMISSED", "RESOLVED", "ACTIONED"})


@dataclass
class Outcome:
    """What one generation run did, in terms somebody can read."""

    pack_id: int
    version: int
    calculated: int = 0
    available: int = 0
    unavailable: int = 0
    failed: int = 0
    moved: list[str] = field(default_factory=list)
    stale_blocks: int = 0
    findings_raised: int = 0
    findings_refreshed: int = 0
    findings_cleared: int = 0
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "pack_id": self.pack_id, "version": self.version,
            "calculated": self.calculated, "available": self.available,
            "unavailable": self.unavailable, "failed": self.failed,
            "moved": list(self.moved), "stale_blocks": self.stale_blocks,
            "findings_raised": self.findings_raised,
            "findings_refreshed": self.findings_refreshed,
            "findings_cleared": self.findings_cleared,
            "notes": list(self.notes),
            "summary": self.summary,
        }

    @property
    def summary(self) -> str:
        """One sentence a pack owner can act on.

        Names the failures first, because a failure is a platform problem and
        the unavailable ones usually are not.
        """
        if not self.calculated:
            return ("This pack has no governed figures in it yet, so there "
                    "was nothing to calculate.")
        bits = [f"{self.calculated} figure"
                f"{'s' if self.calculated != 1 else ''} calculated"]
        if self.failed:
            bits.append(f"{self.failed} failed to compute")
        if self.unavailable:
            bits.append(f"{self.unavailable} had no value for this period")
        if self.stale_blocks:
            bits.append(f"{self.stale_blocks} commentary block"
                        f"{'s' if self.stale_blocks != 1 else ''} now need"
                        f"{'' if self.stale_blocks != 1 else 's'} re-reading")
        if self.findings_raised:
            bits.append(f"{self.findings_raised} new finding"
                        f"{'s' if self.findings_raised != 1 else ''}")
        return ", ".join(bits) + "."


def generate(session: Any, pack_id: int, principal: Any, *,
             source: str = SOURCE_UI, rules: list | None = None) -> Outcome:
    """Calculate every governed figure in a pack, then read the thresholds.

    Bumps the pack version once, at the start, so every snapshot this run
    writes shares one version — which is what makes "the figures as at version
    7" a coherent set rather than a sequence of partial states.
    """
    pack, grant = access.pack_grant(session, pack_id, principal, source)
    access.assert_editable(pack)
    if not grant.at_least(CONTRIBUTOR):
        raise access.PackDenied(
            "You can read this pack but not calculate it. Contributor access "
            "is needed to generate.")

    was_status = str(pack.status)
    pack.version = int(pack.version) + 1
    pack.status = "GENERATING" if was_status in (
        "DRAFT", "DATA_PENDING", "GENERATING") else was_status
    session.flush()

    outcome = Outcome(pack_id=int(pack.id), version=int(pack.version))
    figures, snapshot_ids = _calculate(session, pack, grant, outcome)
    _mark_stale(session, pack, outcome)

    declared = rules if rules is not None else _rules_of(session, pack, outcome)
    if declared:
        observations = materiality.evaluate(
            declared, figures, snapshot_ids=snapshot_ids)
        _apply_findings(session, pack, observations, grant, outcome)

    if pack.status == "GENERATING":
        pack.status = "DATA_PENDING" if outcome.failed else "DRAFT"
    pack.updated_by = grant.user_id
    pack.updated_at = datetime.now(UTC)
    session.flush()

    service.record(
        session, entity_type="pack", action="generated", pack=pack,
        entity_id=int(pack.id), entity_ref=str(pack.code),
        changes={"version": [outcome.version - 1, outcome.version]},
        narrative=outcome.summary, grant=grant)
    readiness.refresh(session, pack)
    return outcome


def _calculate(session: Any, pack: Any, grant: access.Grant,
               outcome: Outcome) -> tuple[dict[str, snap.Figure], dict[str, int]]:
    """Freeze a fresh figure into every calculated block.

    Metrics are measured once each even when three blocks show the same one:
    a pack with a KPI, a chart and a table over the default rate should read
    the lake once, and three reads could disagree if the data moved between
    them.
    """
    blocks = session.execute(
        select(PlaybookBlock)
        .where(PlaybookBlock.pack_id == pack.id,
               PlaybookBlock.block_type.in_(tuple(CALCULATED_BLOCK_TYPES)))
        .order_by(PlaybookBlock.position)).scalars().all()
    if not blocks:
        return {}, {}

    figures: dict[str, snap.Figure] = {}
    snapshot_ids: dict[str, int] = {}
    seen: dict[tuple, PlaybookSnapshot] = {}

    for block in blocks:
        config = dict(block.config or {})
        metric_id = str(config.get("metric_id") or "").strip()
        if not metric_id:
            outcome.notes.append(
                f"“{block.title or block.block_type.title()}” names no "
                "metric, so it could not be calculated.")
            outcome.failed += 1
            continue

        period = str(block.period or pack.period or "")
        filters = dict(block.filters or {})
        key = (metric_id, period, str(pack.comparison_period),
               tuple(sorted(filters.items())))

        row = seen.get(key)
        if row is None:
            figure = snap.measure(
                # `readable` is left unset on purpose: which metrics a
                # person may see is resolved by the metric catalogue from
                # their user id, and passing a list here would be a second
                # permission model over metrics competing with that one.
                metric_id, period=period,
                comparison_period=str(pack.comparison_period or ""),
                filters=filters, user_id=grant.user_id,
                question=f"{block.title or metric_id} for {pack.name}")
            row = snap.write(session, pack=pack, figure=figure,
                             user_id=grant.user_id)
            seen[key] = row
            figures.setdefault(metric_id, figure)
            snapshot_ids.setdefault(metric_id, int(row.id))

            outcome.calculated += 1
            if figure.availability == snap.OK:
                outcome.available += 1
            elif figure.availability in (snap.CALCULATION_FAILED,
                                         snap.NOT_AUTHORISED):
                outcome.failed += 1
                outcome.notes.append(
                    f"{figure.metric_name or metric_id}: "
                    f"{figure.unavailable_reason}")
            else:
                outcome.unavailable += 1

        _note_movement(session, pack, block, row, outcome)
        block.snapshot_id = int(row.id)
        block.version = int(block.version) + 1

    session.flush()
    return figures, snapshot_ids


def _note_movement(session: Any, pack: Any, block: Any, row: Any,
                   outcome: Outcome) -> None:
    """Whether this block's figure differs from the one it was showing."""
    if block.snapshot_id is None:
        return
    before = session.get(PlaybookSnapshot, int(block.snapshot_id))
    if before is None:
        return
    if _same(before.value, row.value) and (
            str(before.availability) == str(row.availability)):
        return
    name = str(row.metric_name or row.metric_id)
    if name not in outcome.moved:
        outcome.moved.append(name)


def _same(before: float | None, after: float | None) -> bool:
    if before is None or after is None:
        return before is after
    scale = max(1.0, abs(before))
    return abs(float(before) - float(after)) / scale <= MOVED


def _mark_stale(session: Any, pack: Any, outcome: Outcome) -> None:
    """Flag commentary written about figures that have since moved.

    Section-scoped rather than block-scoped, and deliberately so. A narrative
    block does not declare which figures it discusses — it is prose — so the
    honest rule is that prose in a section whose numbers moved has to be read
    again. Guessing which sentences were about which figure would produce a
    confident answer that is sometimes wrong, in the direction of leaving
    stale words on the page.
    """
    if not outcome.moved:
        return
    moved_sections = {
        int(row.section_id) for row in session.execute(
            select(PlaybookBlock).where(
                PlaybookBlock.pack_id == pack.id,
                PlaybookBlock.block_type.in_(tuple(CALCULATED_BLOCK_TYPES))
            )).scalars()
        if row.snapshot_id is not None
        and _snapshot_metric(session, row.snapshot_id) in outcome.moved}
    if not moved_sections:
        return

    prose = session.execute(
        select(PlaybookBlock).where(
            PlaybookBlock.pack_id == pack.id,
            PlaybookBlock.section_id.in_(moved_sections),
            PlaybookBlock.block_type.in_(
                ("AI_NARRATIVE", "NARRATIVE", "RISK_CALLOUT")))).scalars().all()
    for block in prose:
        if not str(block.body or "").strip() or block.stale:
            continue
        block.stale = True
        outcome.stale_blocks += 1
    session.flush()


def _snapshot_metric(session: Any, snapshot_id: int) -> str:
    row = session.get(PlaybookSnapshot, int(snapshot_id))
    return str(row.metric_name or row.metric_id) if row is not None else ""


def _rules_of(session: Any, pack: Any, outcome: Outcome) -> list:
    """The materiality rules this pack's template declares.

    A template whose rules do not parse is a configuration fault, and it is
    reported on the run rather than silently producing a pack with no
    findings — which would look exactly like a pack with nothing material in
    it.
    """
    if pack.template_id is None:
        return []
    template = session.get(PlaybookTemplate, int(pack.template_id))
    if template is None:
        return []
    try:
        return materiality.parse(template.materiality)
    except ValueError as e:
        outcome.notes.append(
            f"This pack's template has a materiality rule that could not be "
            f"read, so no thresholds were tested: {e}")
        logger.warning("template %s has an unreadable materiality rule",
                       template.id, exc_info=True)
        return []


def _apply_findings(session: Any, pack: Any,
                    observations: list[materiality.Observation],
                    grant: access.Grant, outcome: Outcome) -> None:
    """Raise, refresh, or leave alone — by fingerprint, never by title.

    Three cases, and the middle one is the point of the whole design:

      * no finding with this fingerprint -> raise it
      * one exists and somebody has DEALT with it -> leave it entirely alone
      * one exists and is still open -> refresh its numbers, keep its identity

    A finding that comes back as new every time the pack regenerates is a
    finding people stop reading. One whose numbers never update is one they
    stop trusting.
    """
    existing = {str(row.fingerprint): row for row in session.execute(
        select(PlaybookFinding)
        .where(PlaybookFinding.pack_id == pack.id)).scalars()}
    sections = _sections_by_key(session, pack)
    still: set[str] = set()

    for found in observations:
        still.add(found.fingerprint)
        row = existing.get(found.fingerprint)
        if row is not None and str(row.status) in SETTLED:
            continue
        if row is None:
            session.add(PlaybookFinding(
                pack_id=int(pack.id),
                section_id=_section_for(found, sections),
                finding_type=found.finding_type, severity=found.severity,
                title=found.title[:240], description=found.description,
                factual_basis=found.factual_basis, metric_id=found.metric_id,
                snapshot_id=found.snapshot_id, period=found.period,
                rule_key=found.rule_key, rule_detail=dict(found.detail),
                fingerprint=found.fingerprint, status="OPEN",
                source=SOURCE_SYSTEM))
            outcome.findings_raised += 1
            continue

        # It is still true and still open: keep the identity and the response
        # somebody has written, and move the numbers underneath them.
        row.severity = found.severity
        row.description = found.description
        row.factual_basis = found.factual_basis
        row.snapshot_id = found.snapshot_id
        row.rule_detail = dict(found.detail)
        row.updated_at = datetime.now(UTC)
        outcome.findings_refreshed += 1

    # A rule that no longer fires: the condition has gone away. The finding is
    # not deleted — it was true when it was raised and the history says so —
    # it is resolved, with the reason.
    for fingerprint, row in existing.items():
        if fingerprint in still or str(row.status) in SETTLED:
            continue
        if str(row.source) != SOURCE_SYSTEM:
            # Somebody raised this by hand. A regeneration does not get to
            # close a person's finding because a rule stopped firing.
            continue
        row.status = "RESOLVED"
        row.response = (
            str(row.response or "")
            + ("\n\n" if row.response else "")
            + f"No longer above its threshold at version {pack.version}.")
        row.updated_at = datetime.now(UTC)
        outcome.findings_cleared += 1

    session.flush()
    if outcome.findings_raised or outcome.findings_cleared:
        service.record(
            session, entity_type="finding", action="evaluated", pack=pack,
            entity_id=int(pack.id),
            narrative=(f"{outcome.findings_raised} raised, "
                       f"{outcome.findings_refreshed} refreshed, "
                       f"{outcome.findings_cleared} no longer above "
                       "threshold."),
            grant=grant)


def _sections_by_key(session: Any, pack: Any) -> dict[str, int]:
    """Which section each metric lives in, so a finding lands on the page."""
    out: dict[str, int] = {}
    rows = session.execute(
        select(PlaybookBlock, PlaybookSection)
        .join(PlaybookSection, PlaybookBlock.section_id == PlaybookSection.id)
        .where(PlaybookBlock.pack_id == pack.id,
               PlaybookBlock.block_type.in_(
                   tuple(CALCULATED_BLOCK_TYPES)))).all()
    for block, section in rows:
        metric_id = str((block.config or {}).get("metric_id") or "")
        if metric_id:
            out.setdefault(metric_id, int(section.id))
    return out


def _section_for(found: materiality.Observation,
                 sections: dict[str, int]) -> int | None:
    return sections.get(found.metric_id)


def refresh_block(session: Any, block_id: int, principal: Any, *,
                  source: str = SOURCE_UI) -> dict[str, Any]:
    """Recalculate one block, without regenerating the whole pack.

    What somebody uses after fixing a filter on one tile. Bumps the pack
    version, because the pack's content changed and a concurrent editor has
    to be told.
    """
    block, section, pack, grant = access.visible_block(
        session, block_id, principal, source)
    access.assert_editable(pack)
    access.may_edit_section(session, section, grant, "recalculate this block")
    if str(block.block_type) not in CALCULATED_BLOCK_TYPES:
        raise service.InvalidPlaybook(
            f"A {str(block.block_type).lower().replace('_', ' ')} block has no "
            "figure to recalculate — it is words, not a governed number.")

    metric_id = str((block.config or {}).get("metric_id") or "").strip()
    if not metric_id:
        raise service.InvalidPlaybook(
            "This block names no metric, so there is nothing to calculate.")

    pack.version = int(pack.version) + 1
    figure = snap.measure(
        metric_id, period=str(block.period or pack.period or ""),
        comparison_period=str(pack.comparison_period or ""),
        filters=dict(block.filters or {}), user_id=grant.user_id,
        question=f"{block.title or metric_id} for {pack.name}")
    row = snap.write(session, pack=pack, figure=figure, user_id=grant.user_id)

    outcome = Outcome(pack_id=int(pack.id), version=int(pack.version),
                      calculated=1)
    _note_movement(session, pack, block, row, outcome)
    block.snapshot_id = int(row.id)
    block.version = int(block.version) + 1
    if outcome.moved:
        _mark_stale(session, pack, outcome)
    session.flush()

    service.record(
        session, entity_type="block", action="recalculated", pack=pack,
        entity_id=int(block.id), entity_ref=str(block.block_type),
        narrative=(f"{figure.metric_name or metric_id} recalculated: "
                   f"{figure.display_value}"
                   + (" — the commentary in this section now needs re-reading."
                      if outcome.stale_blocks else "")),
        grant=grant)
    readiness.refresh(session, pack)
    return {"block_id": int(block.id), "snapshot_id": int(row.id),
            "figure": figure.to_dict(), "outcome": outcome.to_dict()}


def amend(session: Any, pack_id: int, principal: Any, *, reason: str,
          source: str = SOURCE_UI) -> dict[str, Any]:
    """Correct an approved pack by raising a new version beside it.

    The approved pack is NOT edited. It becomes SUPERSEDED and a new DRAFT is
    created carrying its content forward, linked in both directions. What the
    committee actually saw stays readable for ever, which is the difference
    between a governance record and a document.
    """
    original, grant = access.pack_grant(session, pack_id, principal, source)
    access.refuse_ai(grant, "edit_approved_pack")
    if str(original.status) not in ("APPROVED", "PUBLISHED"):
        raise service.InvalidPlaybook(
            f"This pack is {str(original.status).lower().replace('_', ' ')} "
            "and can simply be edited. An amendment is for correcting a pack "
            "that has already been approved.")
    if not grant.at_least(access.EDITOR):
        raise access.PackDenied(
            "Raising an amendment to an approved pack needs editor access to "
            "the committee.")
    if not str(reason or "").strip():
        raise service.InvalidPlaybook(
            "An amendment to an approved pack has to say why it was needed. "
            "That sentence is what the committee reads first.")

    fresh = PlaybookPack(
        code=_amendment_code(session, original),
        committee_id=int(original.committee_id),
        template_id=original.template_id,
        name=f"{original.name} (amended)",
        period=str(original.period),
        comparison_period=str(original.comparison_period),
        meeting_at=original.meeting_at, as_of_date=original.as_of_date,
        owner_id=grant.user_id, status="DRAFT",
        confidentiality=str(original.confidentiality),
        amends_pack_id=int(original.id), amendment_reason=str(reason),
        previous_pack_id=original.previous_pack_id,
        created_by=grant.user_id, updated_by=grant.user_id)
    session.add(fresh)
    session.flush()

    carried = _carry_content(session, original, fresh)
    original.status = "SUPERSEDED"
    original.updated_at = datetime.now(UTC)
    session.flush()

    service.record(
        session, entity_type="pack", action="superseded", pack=original,
        entity_id=int(original.id), entity_ref=str(original.code),
        changes={"status": [("PUBLISHED" if original.published_at else
                             "APPROVED"), "SUPERSEDED"]},
        narrative=f"Superseded by {fresh.code}: {reason}", grant=grant)
    service.record(
        session, entity_type="pack", action="created", pack=fresh,
        entity_id=int(fresh.id), entity_ref=str(fresh.code),
        narrative=(f"Raised as an amendment to {original.code}, carrying "
                   f"{carried} section{'s' if carried != 1 else ''} forward. "
                   f"Reason: {reason}"),
        grant=grant)
    readiness.refresh(session, fresh)
    return service.summary_of(fresh)


def _carry_content(session: Any, original: Any, fresh: Any) -> int:
    """Copy an approved pack's sections and blocks into its amendment.

    The blocks keep their configuration and their words and LOSE their
    snapshot: an amendment is going to be regenerated, and carrying the old
    pack's frozen figures into it would mean the two packs pointed at the same
    snapshot rows, so refreshing one would appear to change the other.
    """
    made = 0
    sections = session.execute(
        select(PlaybookSection)
        .where(PlaybookSection.pack_id == original.id)
        .order_by(PlaybookSection.position)).scalars().all()
    for section in sections:
        copy = PlaybookSection(
            pack_id=int(fresh.id), template_key=str(section.template_key),
            title=str(section.title), purpose=str(section.purpose),
            position=int(section.position), owner_id=section.owner_id,
            reviewer_id=section.reviewer_id, status="DRAFTING",
            required=bool(section.required), due_date=section.due_date,
            narrative_instructions=str(section.narrative_instructions))
        session.add(copy)
        session.flush()
        made += 1
        blocks = session.execute(
            select(PlaybookBlock)
            .where(PlaybookBlock.section_id == section.id)
            .order_by(PlaybookBlock.position)).scalars().all()
        for block in blocks:
            session.add(PlaybookBlock(
                section_id=int(copy.id), pack_id=int(fresh.id),
                block_type=str(block.block_type), position=int(block.position),
                title=str(block.title), body=str(block.body),
                statement_kind=str(block.statement_kind),
                config=dict(block.config or {}),
                filters=dict(block.filters or {}), period=str(block.period),
                snapshot_id=None, import_class=str(block.import_class),
                author_id=block.author_id, source=str(block.source),
                ai_accepted=bool(block.ai_accepted),
                # Every carried figure is about to be recomputed, so prose
                # about the old ones has to be read again before it is tabled.
                stale=bool(str(block.body or "").strip())))
    session.flush()
    return made


def _amendment_code(session: Any, original: Any) -> str:
    base = f"{original.code}-A"[:46]
    code, suffix = f"{base}1", 2
    while session.execute(select(PlaybookPack.id).where(
            PlaybookPack.code == code)).scalar_one_or_none() is not None:
        code = f"{base}{suffix}"[:48]
        suffix += 1
    return code


__all__ = ["MOVED", "Outcome", "SETTLED", "amend", "generate", "refresh_block"]
