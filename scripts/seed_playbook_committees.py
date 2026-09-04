#!/usr/bin/env python
"""Three committees, each with a previous approved pack and a current open one.

    python scripts/seed_playbook_committees.py                 build what is missing
    python scripts/seed_playbook_committees.py --check         report only
    python scripts/seed_playbook_committees.py --refresh-dates roll dates to today
    python scripts/seed_playbook_committees.py --refresh-dates --dry-run
    python scripts/seed_playbook_committees.py --reset         rebuild from scratch
    python scripts/seed_playbook_committees.py --json          machine-readable

This is the `playbook-demo` command surface: everything that creates,
inspects, re-anchors or rebuilds the demonstration committees is here, because
a second entry point is a second set of guards to keep in step with these.

What it builds, and why it is not one committee
-----------------------------------------------
One committee demonstrates a form. Three demonstrate that this is about
GOVERNANCE: Retail meets monthly on a monthly-measured book, Corporate and
IFRS 9 meet quarterly on a quarterly-measured one, and on the day of a
demonstration they sit at three different points in their cycle — one still
being drafted, one mid-review, one signed off and read-only. The shape of the
argument is the three of them side by side.

Everything is calculated
------------------------
Not one figure is typed in. Every KPI names a governed metric and is measured
against the real lake when the pack is generated, so the numbers on a
demonstration pack are the numbers Ask CreditProbe gives for the same
question, and a figure with no value says WHICH absence it is. The findings
are whatever the declared thresholds in `backend/playbook/demo.py` actually
produce — not a list somebody wrote to look interesting, which is why the
report below prints how many were raised rather than asserting a number.

Everything goes through the service layer
-----------------------------------------
Every row is created through `backend.playbook.service` with a named author,
so it is subject to the same validation, permissions, history and audit as a
row a person would have typed. A seed that inserted directly could create
states the product cannot reach, which is how a demonstration ends up showing
something that cannot happen.

Relative dates, and rebuilding is the wrong repair
---------------------------------------------------
Every date is an offset from the day the seed ran, which is true that day and
decays afterwards. `--refresh-dates` rolls the scheduling fields forward by
the days since the anchor and leaves content, status, findings, decisions,
actions and history exactly as they are. `--dry-run` prints what would move
and writes nothing. A meeting date a PERSON moved is a commitment to other
people's diaries: it is held back and reported, and `--force-demo-dates` is
the only way past that. See `backend/playbook/demo.py`.

`--reset` is guarded: it refuses outside a development or demonstration
deployment, and it removes only the three committees named here.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from backend.db.engine import get_session  # noqa: E402
from backend.db.models import User  # noqa: E402
from backend.models.playbook import (  # noqa: E402
    SOURCE_SYSTEM,
    PlaybookCommittee,
    PlaybookFinding,
    PlaybookPack,
)
from backend.playbook import actions as act  # noqa: E402
from backend.playbook import demo, generation  # noqa: E402
from backend.playbook import service as svc  # noqa: E402

logger = logging.getLogger(__name__)

EXIT_OK = 0
EXIT_CANNOT_RUN = 2

#: Who plays which part. Usernames from `backend/services/demo_users.py`, so
#: the people on these committees are the people somebody can actually log in
#: as during a demonstration.
CAST: dict[str, dict[str, str]] = {
    demo.RETAIL.code: {
        "steward": "sara.qahtani",
        "owner": "omar.nasser",
        "author": "sarah.khan",
        "reviewer": "ahmed.saleh",
        "approver": "alex.rahman",
        "viewer": "layla.haddad",
    },
    demo.CORPORATE.code: {
        "steward": "sara.qahtani",
        "owner": "sarah.khan",
        "author": "omar.nasser",
        "reviewer": "ahmed.saleh",
        "approver": "alex.rahman",
        "viewer": "layla.haddad",
    },
    demo.IFRS9.code: {
        "steward": "sara.qahtani",
        "owner": "ahmed.saleh",
        "author": "omar.nasser",
        "reviewer": "sarah.khan",
        "approver": "alex.rahman",
        "viewer": "layla.haddad",
    },
}

#: What each part means on the committee: (business role, access role).
PARTS: dict[str, tuple[str, str]] = {
    "owner": ("PACK_OWNER", "OWNER"),
    "author": ("MEMBER", "CONTRIBUTOR"),
    "reviewer": ("MEMBER", "REVIEWER"),
    "approver": ("CHAIR", "APPROVER"),
    "viewer": ("OBSERVER", "VIEWER"),
}


@dataclass
class Report:
    """What one run did, in the shape a script and a person both read."""

    built: list[str] = field(default_factory=list)
    present: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "built": sorted(self.built), "present": sorted(self.present),
            "removed": sorted(self.removed), "counts": dict(self.counts),
            "notes": list(self.notes), "error": self.error,
            "ok": not self.error,
        }


# ------------------------------------------------------------------ guards


def _may_reset() -> tuple[bool, str]:
    """Whether destructive work is allowed here.

    Two ways to be sure this is not a production deployment: the environment
    says so, or Synthetic Data Mode is on. Both are explicit; neither can be
    acquired by forgetting to set something.
    """
    from backend.config import settings
    from backend.demo import mode

    if mode.enabled():
        return True, "Synthetic Data Mode is on."
    if str(settings.env or "").lower() in {"dev", "development", "test",
                                           "demo", "local"}:
        return True, f"ENV is {settings.env}."
    return False, (
        f"ENV is {settings.env!r} and Synthetic Data Mode is off. --reset "
        "removes committees and the packs on them, so it refuses to run "
        "anywhere that might be real.")


# ------------------------------------------------------------------- people


def _principal(user: Any):
    from backend.api.permissions import Principal, Role

    return Principal(user_id=int(user.id), role=Role(str(user.role).upper()))


def _cast_for(session: Any, code: str) -> dict[str, Any] | None:
    """The people this committee needs, or None with a note if any is absent.

    Refuses rather than inventing accounts. A seed that created its own users
    would put people in the directory nobody asked for, and the demonstration
    users are seeded by their own script for exactly that reason.
    """
    wanted = CAST[code]
    found: dict[str, Any] = {}
    for part, username in wanted.items():
        row = session.execute(
            select(User).where(User.username == username)).scalars().first()
        if row is None:
            return None
        found[part] = row
    return found


# -------------------------------------------------------------------- build


def _metric_ids(spec: demo.Committee) -> list[str]:
    """Every governed metric this committee's template puts on a pack."""
    found: list[str] = []
    for section in spec.template["sections"]:
        for block in section.get("blocks") or []:
            metric_id = str((block.get("config") or {}).get("metric_id") or "")
            if metric_id and metric_id not in found:
                found.append(metric_id)
    return found


def _periods_for(spec: demo.Committee) -> list[str]:
    """The periods this committee's own metrics actually have data for.

    Read from the lake rather than derived from the calendar, and that is the
    whole point. A pack whose period came from `date.today()` is a pack that
    asks the lake for a month it does not hold, and every figure on it comes
    back PERIOD_MISSING — which is the availability machinery working
    correctly and a demonstration of nothing.

    A committee cannot read a period that has not been loaded, so the seeded
    packs read the last two periods the data HAS. That is also what a real
    committee does: it reads the period that closed and arrived, not the one
    the calendar is standing in.
    """
    from backend.metrics import service as metrics

    #: Every period each metric can be READ in, which for an outcome metric
    #: means every period whose performance window has closed. Its own scope
    #: carries that condition, so asking with the scope is asking the right
    #: question.
    per_metric: list[list[str]] = []
    for metric_id in _metric_ids(spec):
        try:
            resolved = metrics.resolve(metric_id)
        except Exception:  # noqa: BLE001 - an absent metric is reported later
            continue
        found = [str(x) for x in
                 metrics.periods_with_rows(resolved.datasets, resolved.scope)]
        if found:
            per_metric.append(found)
    if not per_metric:
        return []

    # The intersection, in the order the first metric has them. A committee
    # reads ONE period, and the one it can read is the one every figure on
    # its pack has. Retail's default rate and application Gini are outcome
    # metrics that mature months after the month they are about, which is
    # why a real retail committee reads with a lag rather than reading last
    # month and getting three blanks. The absences are still demonstrated —
    # by the pack's own honest labelling when somebody moves the period —
    # but they are not what the seeded pack leads with.
    shared = set(per_metric[0]).intersection(*(set(x) for x in per_metric[1:]))
    return [period for period in per_metric[0] if period in shared]


def _existing(session: Any) -> set[str]:
    return {str(c.code) for c in demo.seeded(session)}


def _remove(session: Any, report: Report) -> None:
    """Take the seeded committees out, and nothing else.

    Deleted through the ORM so the cascades run, and only rows whose stored
    `demo_origin` marker says CreditProbe put them there.
    """
    for committee in demo.seeded(session):
        report.removed.append(str(committee.code))
        session.delete(committee)
    session.flush()


def _build_one(session: Any, spec: demo.Committee, report: Report) -> None:
    """One committee, its template, its people and its two packs."""
    cast = _cast_for(session, spec.code)
    if cast is None:
        report.notes.append(
            f"{spec.code}: skipped. The demonstration users are not present — "
            "run scripts/seed_demo_users.py first.")
        return

    steward = _principal(cast["steward"])
    today = datetime.now(UTC).date()

    committee = svc.create_committee(
        session, steward, name=spec.name, code=spec.code,
        purpose=spec.purpose, business_area=spec.business_area,
        cadence=spec.cadence, meeting_weekday=spec.meeting_weekday,
        confidentiality="CONFIDENTIAL")
    committee_id = int(committee["id"])

    # The marker and the anchor, which are what make this safe to re-anchor
    # later and what make a committee a person created unsafe to touch.
    row = session.get(PlaybookCommittee, committee_id)
    row.demo_origin = demo.PLAYBOOK_DEMO
    row.demo_anchor_date = today
    session.flush()

    for part, (business, access) in PARTS.items():
        svc.add_member(
            session, committee_id, steward,
            user_id=int(cast[part].id), business_role=business,
            access_role=access,
            title=str(cast[part].job_title or ""))

    template = svc.create_template(
        session, steward, committee_id=committee_id,
        name=spec.template["name"], code=spec.template["code"],
        description=spec.template["description"],
        sections=spec.template["sections"],
        materiality_rules=spec.template["materiality"],
        status="PUBLISHED")
    template_id = int(template["id"])
    row.default_template_id = template_id
    session.flush()

    owner = _principal(cast["owner"])
    approver = _principal(cast["approver"])
    reviewer = _principal(cast["reviewer"])

    periods = _periods_for(spec)
    if len(periods) < 3:
        report.notes.append(
            f"{spec.code}: skipped. Its metrics have data for "
            f"{len(periods)} period(s), and a committee with a previous pack "
            "and a current one needs three to read.")
        session.delete(row)
        session.flush()
        return

    previous = _build_pack(
        session, spec, committee_id, template_id, owner, approver,
        offset=spec.previous_meeting, today=today, target="PUBLISHED",
        period=periods[-2], comparison=periods[-3], reviewer=reviewer)
    current = _build_pack(
        session, spec, committee_id, template_id, owner, approver,
        offset=spec.current_meeting, today=today, target=spec.current_status,
        period=periods[-1], comparison=periods[-2], reviewer=reviewer)

    report.built.append(spec.code)
    report.counts[f"{spec.code}.packs"] = 2
    for label, pack_id in (("previous", previous), ("current", current)):
        raised = int(session.execute(
            select(PlaybookFinding).where(
                PlaybookFinding.pack_id == pack_id)).scalars().all().__len__())
        report.counts[f"{spec.code}.{label}.findings"] = raised


#: How far along the lifecycle each target is, in the order the pack moves.
TO_TARGET: dict[str, tuple[str, ...]] = {
    "DRAFT": (),
    "CONTRIBUTOR_REVIEW": ("CONTRIBUTOR_REVIEW",),
    "REVIEW": ("CONTRIBUTOR_REVIEW", "REVIEW"),
    "READY_FOR_APPROVAL": ("CONTRIBUTOR_REVIEW", "REVIEW",
                           "READY_FOR_APPROVAL"),
    "APPROVED": ("CONTRIBUTOR_REVIEW", "REVIEW", "READY_FOR_APPROVAL",
                 "APPROVED"),
    "PUBLISHED": ("CONTRIBUTOR_REVIEW", "REVIEW", "READY_FOR_APPROVAL",
                  "APPROVED", "PUBLISHED"),
}


def _build_pack(session: Any, spec: demo.Committee, committee_id: int,
                template_id: int, owner: Any, approver: Any, *,
                offset: int, today: date, target: str,
                period: str, comparison: str,
                reviewer: Any | None = None) -> int:
    """One pack, laid out, calculated, and walked to where it should be."""
    meeting = datetime.combine(
        today + timedelta(days=offset),
        datetime.min.time(), tzinfo=UTC).replace(hour=10)

    made = svc.create_pack(
        session, owner, committee_id=committee_id, template_id=template_id,
        period=period, comparison_period=comparison, meeting_at=meeting,
        owner_id=owner.user_id)
    pack_id = int(made["id"])

    row = session.get(PlaybookPack, pack_id)
    row.demo_origin = demo.PLAYBOOK_DEMO
    # The freeze is when the data has to be in: a week before the meeting,
    # which is what the committee's own workflow offsets say.
    row.data_freeze_at = meeting - timedelta(days=7)
    session.flush()

    # Every figure measured against the real lake, and whatever findings the
    # declared thresholds produce against it.
    generation.generate(session, pack_id, owner)

    _write_commentary(session, pack_id, owner)
    _answer_findings(session, pack_id, approver, target=target)
    _governance(session, spec, pack_id, owner, approver, target=target,
                today=today)
    _review_sections(session, pack_id, owner, reviewer, target=target)
    _walk(session, pack_id, owner, approver, target=target)
    return pack_id


def _review_sections(session: Any, pack_id: int, owner: Any,
                     reviewer: Any | None, *, target: str) -> None:
    """Submit and review the pack's sections, where it has got that far.

    Readiness will not let a pack reach approval with sections nobody has
    read, and that gate is the product working. So a pack that should be
    APPROVED on the day of a demonstration has to have been genuinely
    reviewed — through `submit_section` and `review_section`, by a named
    reviewer, recorded against the pack version they read.

    A pack still in REVIEW gets its sections SUBMITTED and not yet approved,
    which is what "waiting on a reviewer" actually looks like and is what
    gives the chase list something true to say.
    """
    if reviewer is None or target == "DRAFT":
        return
    whole = svc.pack(session, pack_id, owner)
    for section in whole["sections"]:
        if not section["blocks"]:
            continue
        try:
            svc.submit_section(session, section["id"], owner)
        except Exception:  # noqa: BLE001 - an empty section is not an error
            continue
        if target not in ("READY_FOR_APPROVAL", "APPROVED", "PUBLISHED"):
            continue
        svc.review_section(
            session, section["id"], reviewer, decision="APPROVED",
            note="Read at the pre-meeting review. No changes requested.")


def _write_commentary(session: Any, pack_id: int, owner: Any) -> None:
    """Words a person wrote, in the blocks the template laid out for them.

    Deliberately NOT AI drafts. The demonstration's AI story is the drafting
    button on a live pack — a seed that pre-filled every narrative with
    accepted AI text would remove the one moment where somebody sees the
    grounding check run.
    """
    whole = svc.pack(session, pack_id, owner)
    for section in whole["sections"]:
        for block in section["blocks"]:
            if block["block_type"] != "NARRATIVE" or block["body"]:
                continue
            said = _commentary_for(section, block)
            if said:
                svc.update_block(session, block["id"], owner, body=said)


def _commentary_for(section: dict[str, Any], block: dict[str, Any]) -> str:
    """A sentence built from the section's OWN figures, not from a template.

    Reads the block's siblings, so the words on a demonstration pack agree
    with the numbers beside them — which a fixed string would stop doing the
    first time the data moved.
    """
    figures = [b for b in section["blocks"]
               if b.get("figure") and b["figure"]["availability"] == "OK"]
    if not figures:
        absent = [b for b in section["blocks"] if b.get("figure")]
        if not absent:
            return ""
        return ("None of this section's figures could be calculated for this "
                "period. The pack states which of them are absent and why, "
                "and this section should not be read as a result.")

    lead = figures[0]
    said = (f"{lead['title']} is {lead['figure']['display_value']} "
            f"for {lead['figure']['period']}")
    if lead["figure"]["comparison_value"] is not None:
        said += (f", against {lead['figure']['comparison_display']} in "
                 f"{lead['figure']['comparison_period']}")
    said += "."
    if len(figures) > 1:
        rest = ", ".join(
            f"{b['title'].lower()} at {b['figure']['display_value']}"
            for b in figures[1:3])
        said += f" Alongside it, {rest}."
    return said


#: One decision per committee, in that committee's own language. Written out
#: rather than generated, because a committee decision is a sentence somebody
#: composed and a template-generated one reads like a template.
DECISIONS: dict[str, dict[str, str]] = {
    demo.RETAIL.code: {
        "title": "Tighten the minimum score on unsecured personal loans",
        "question": (
            "Should the minimum application score on unsecured personal "
            "loans move from 580 to 600 with effect from the start of next "
            "month?"),
        "recommendation": (
            "Recommended. The cohort bad rate on the sub-600 band is running "
            "materially above the rest of the book and the volume it "
            "represents is small enough to absorb."),
        "impact": (
            "Approximately 4% of application volume, and an estimated 11% of "
            "the cohort's expected losses."),
        "decided": (
            "Approved with effect from the first of next month, and to be "
            "reviewed after three months of performance."),
        "action": (
            "Implement the 600 minimum score on unsecured personal loans in "
            "the origination policy, and confirm the change in the following "
            "month's pack."),
    },
    demo.CORPORATE.code: {
        "title": "Move two names from the watchlist to enhanced monitoring",
        "question": (
            "Should the two names flagged this quarter move from the standard "
            "watchlist to enhanced monthly monitoring with a named relationship "
            "owner?"),
        "recommendation": (
            "Recommended. Both have deteriorated across two consecutive "
            "quarters and neither has a current facility review."),
        "impact": "Two relationships; no change to limits or provisioning.",
        "decided": "",
        "action": "",
    },
    demo.IFRS9.code: {
        "title": "Retain the macroeconomic overlay at its current level",
        "question": (
            "Should the macroeconomic overlay be retained at its current "
            "level for this quarter, or released in part?"),
        "recommendation": (
            "Recommended to retain. The conditions the committee set for "
            "release — two consecutive quarters of improving forward "
            "indicators — have not both been met."),
        "impact": (
            "Retaining the overlay holds the ECL at its current level; "
            "releasing half would reduce it by the overlay's share."),
        "decided": (
            "Retained in full. To be reconsidered next quarter against the "
            "same release conditions, which are recorded with this decision."),
        "action": (
            "Prepare the release-condition assessment for next quarter's "
            "pack, showing each condition and whether it has been met."),
    },
}


def _governance(session: Any, spec: demo.Committee, pack_id: int, owner: Any,
                approver: Any, *, target: str, today: date) -> None:
    """The end of the cycle: a decision, and the action that follows it.

    On a pack the committee has already met on, the decision is DECIDED and
    the action that follows it exists, is owned and has a date — because that
    is what makes the next pack's "what happened to what we agreed last time"
    a real question rather than an empty panel.

    On a pack still in flight the decision sits in DRAFT with its question and
    its recommendation written and no outcome, which is exactly what a paper
    going to a meeting next week looks like.
    """
    spoken = DECISIONS.get(spec.code)
    if not spoken:
        return

    decision = act.create_decision(
        session, pack_id, owner, title=spoken["title"],
        question=spoken["question"],
        recommendation=spoken["recommendation"], impact=spoken["impact"],
        owner_id=owner.user_id)

    if target not in ("APPROVED", "PUBLISHED") or not spoken["decided"]:
        # A paper on its way to a meeting. Moved out of DRAFT so it reads as
        # something being asked rather than something half-written, and left
        # undecided because nobody has been in the room yet.
        act.update_decision(session, int(decision["id"]), owner,
                            status="REQUIRED")
        return

    act.update_decision(session, int(decision["id"]), owner, status="REQUIRED")
    act.decide(session, int(decision["id"]), approver, outcome="APPROVED",
               decision_text=spoken["decided"])

    if not spoken["action"]:
        return
    action = act.create_action(
        session, pack_id, owner, description=spoken["action"],
        owner_id=owner.user_id, due_date=today + timedelta(days=21),
        priority="HIGH", decision_id=int(decision["id"]), status="OPEN")
    _send_to_planner(session, int(action["id"]), owner)


def _send_to_planner(session: Any, action_id: int, owner: Any) -> None:
    """Link the action to a Planner project, where the work actually lives.

    Best effort by design: the Planner demonstration projects are seeded by
    their own script and may not be present. An action that could not be
    linked is still a real committee action — it says on screen that it has
    not been sent to the Planner, which is the truth — so a missing Planner
    must not stop the committees being built.
    """
    from backend.planner import query as planner

    try:
        rows = planner.portfolio(session, owner, limit=1).get("projects") or []
    except Exception:  # noqa: BLE001 - the Planner's absence is not an error
        return
    if not rows:
        return
    try:
        act.link_to_planner(session, action_id, owner,
                            project_id=int(rows[0]["id"]))
    except Exception as exc:  # noqa: BLE001 - reported, not swallowed
        logger.info("playbook demo: action %s not linked to the Planner: %s",
                    action_id, exc)


def _answer_findings(session: Any, pack_id: int, approver: Any, *,
                     target: str) -> None:
    """Answer what the pack raised, where the pack has got far enough.

    A pack cannot be approved with a serious finding nobody has answered, so
    a PUBLISHED demonstration pack has to have answered its own. The mid-cycle
    packs deliberately do NOT: the open finding is the thing a demonstration
    is for, and a seed that quietly answered them all would produce three
    green packs and no reason to open one.
    """
    if target not in ("APPROVED", "PUBLISHED"):
        return
    from backend.playbook import findings as find

    for finding in find.findings(session, approver, pack_id=pack_id):
        if finding["answered"]:
            continue
        find.respond(
            session, finding["id"], approver, status="EXPLAINED",
            response=(
                "Reviewed at the meeting. The movement is understood and "
                "within the tolerance the committee agreed for this period; "
                "the position is being monitored monthly."))


def _walk(session: Any, pack_id: int, owner: Any, approver: Any, *,
          target: str) -> None:
    """Move the pack along its own state machine to where it should be.

    Through `set_pack_status` rather than by writing the column, so every
    transition is validated, recorded and refused where the product would
    refuse it. A pack that arrived at APPROVED without passing the readiness
    gate would be a demonstration of something the product does not do.
    """
    for step in TO_TARGET.get(target, ()):
        who = approver if step in ("APPROVED", "PUBLISHED") else owner
        try:
            svc.set_pack_status(session, pack_id, who, status=step)
        except Exception as exc:  # noqa: BLE001 - reported, not swallowed
            # The readiness gate refusing is INFORMATION, not a failure: it
            # means the pack genuinely is not ready, and the demonstration
            # should show it where it actually is rather than forced past.
            svc.record(
                session, entity_type="pack", action="seeded",
                pack=session.get(PlaybookPack, pack_id),
                narrative=(
                    f"Seeding stopped at {step.lower().replace('_', ' ')}: "
                    f"{exc}"),
                grant=None, source=SOURCE_SYSTEM)
            return


def _sections_and_figures(session: Any, code: str) -> dict[str, int]:
    """What actually got built, counted from the rows rather than assumed."""
    from backend.models.playbook import PlaybookBlock, PlaybookSnapshot

    committee = session.execute(
        select(PlaybookCommittee)
        .where(PlaybookCommittee.code == code)).scalars().first()
    if committee is None:
        return {}
    packs = list(session.execute(
        select(PlaybookPack.id)
        .where(PlaybookPack.committee_id == committee.id)).scalars())
    if not packs:
        return {}
    blocks = len(list(session.execute(
        select(PlaybookBlock.id)
        .where(PlaybookBlock.pack_id.in_(packs))).scalars()))
    figures = len(list(session.execute(
        select(PlaybookSnapshot.id)
        .where(PlaybookSnapshot.pack_id.in_(packs))).scalars()))
    return {"blocks": blocks, "figures": figures}


def build(*, reset: bool = False, check: bool = False) -> Report:
    report = Report()

    if reset:
        allowed, why = _may_reset()
        if not allowed:
            report.error = why
            return report
        report.notes.append(f"Reset allowed: {why}")

    with get_session() as session:
        present = _existing(session)
        if check:
            report.present = sorted(present)
            for code in present:
                for name, number in _sections_and_figures(
                        session, code).items():
                    report.counts[f"{code}.{name}"] = number
            missing = [s.code for s in demo.COMMITTEES if s.code not in present]
            if missing:
                report.notes.append(
                    f"Not built: {', '.join(sorted(missing))}.")
            return report

        if reset and present:
            _remove(session, report)
            present = set()

        for spec in demo.COMMITTEES:
            if spec.code in present:
                report.present.append(spec.code)
                continue
            _build_one(session, spec, report)

        session.commit()

    with get_session() as session:
        for code in report.built:
            for name, number in _sections_and_figures(session, code).items():
                report.counts[f"{code}.{name}"] = number
    return report


def refresh_dates(*, dry_run: bool = False,
                  force: bool = False) -> demo.Refresh:
    with get_session() as session:
        out = demo.refresh(session, dry_run=dry_run, force=force)
        if not dry_run:
            session.commit()
        return out


# ------------------------------------------------------------------ printing


def _print_build(report: Report) -> None:
    if report.error:
        print(f"! {report.error}")
    for note in report.notes:
        print(f"  {note}")
    for code in sorted(report.removed):
        print(f"  removed {code}")
    for code in sorted(report.present):
        print(f"  {code}: already present. Nothing to do.")
    for code in sorted(report.built):
        print(f"  built {code}")
    if report.counts:
        for name in sorted(report.counts):
            print(f"    {name:52s} {report.counts[name]}")


def _print_refresh(out: demo.Refresh, *, dry_run: bool) -> None:
    print(f"  playbook demo dates, as at {out.today}"
          + ("  (dry run — nothing was written)" if dry_run else ""))
    for entry in out.committees:
        if entry.anchor is None:
            print(f"  {entry.code}: no anchor recorded, so nothing is moved. "
                  "Rebuild it with --reset.")
            continue
        if entry.shift_days == 0:
            print(f"  {entry.code}: already anchored to {out.today}. "
                  "Nothing to do.")
            continue
        lead = "would move" if dry_run else "moved"
        print(f"  {entry.code}: anchored {entry.anchor}, "
              f"{lead} {len(entry.moved)} date"
              f"{'' if len(entry.moved) == 1 else 's'} "
              f"by {entry.shift_days} day"
              f"{'' if abs(entry.shift_days) == 1 else 's'}")
        for held in entry.held:
            print(f"    held {held} — a person set that date, so it stands")
    print(f"  {out.summary}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="report what exists; change nothing")
    parser.add_argument("--reset", action="store_true",
                        help="DESTRUCTIVE, demo/dev only: remove these three "
                             "committees and rebuild them from scratch")
    parser.add_argument("--refresh-dates", action="store_true",
                        help="roll the seeded dates forward to today")
    parser.add_argument("--dry-run", action="store_true",
                        help="with --refresh-dates: print what would move "
                             "and write nothing")
    parser.add_argument("--force-demo-dates", action="store_true",
                        help="with --refresh-dates: also move dates a person "
                             "changed after seeding")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.refresh_dates:
        try:
            out = refresh_dates(dry_run=args.dry_run,
                                force=args.force_demo_dates)
        except Exception as exc:  # noqa: BLE001 - reported, not swallowed
            message = f"{type(exc).__name__}: {exc}"
            if args.json:
                print(json.dumps({"error": message}, indent=2))
            else:
                print(f"! {message}")
            return EXIT_CANNOT_RUN
        if args.json:
            print(json.dumps(out.to_dict(), indent=2))
        else:
            _print_refresh(out, dry_run=args.dry_run)
        return EXIT_OK

    if args.dry_run or args.force_demo_dates:
        print("--dry-run and --force-demo-dates only mean something with "
              "--refresh-dates.")
        return EXIT_CANNOT_RUN

    try:
        report = build(reset=args.reset, check=args.check)
    except Exception as exc:  # noqa: BLE001 - reported, not swallowed
        message = f"{type(exc).__name__}: {exc}"
        if args.json:
            print(json.dumps({"error": message, "ok": False}, indent=2))
        else:
            print(f"! {message}")
        return EXIT_CANNOT_RUN

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        _print_build(report)
    return EXIT_CANNOT_RUN if report.error else EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
