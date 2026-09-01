"""
One borrower's Early Warning position, told as a credit story. R2 §5.

The instruction is explicit: **do not merely list 17 conditions**. A list of
conditions is what the signal engine produces and it is not what a credit
officer needs. What they need is the answer to a sequence of questions, asked
in the order a person asks them:

    Why is this borrower in front of me?
    What is the one thing here that matters most?
    What is new, what is getting worse, what has been true for a while, and
        what has gone away?
    Then, family by family: the earnings, the cash, the debt, the facility
        behaviour, the covenants, the collateral, the rating, the stage.
    Is anything happening outside the bank that bears on this?
    Does the group this borrower sits in change the picture?
    What argues the other way?
    What should I go and look at?

Every section here answers one of those. Each is composed from the SAME
governed evidence the signal engine produced — nothing is invented, no figure
appears that a signal did not carry — and each says plainly when it has
nothing to say, because "the collateral section is empty" and "collateral was
never tested" are different facts and a screen that shows neither teaches the
reader that silence means safety.

Composed here rather than in the screen
----------------------------------------
The same rule the observation sentences follow: the wording lives beside the
evidence so the screen, the export and the analyst's tools cannot describe the
same position three different ways. A section is a heading, a question, a body
of sentences and a list of the observations behind it; the screen decides how
that looks and never what it says.

The external and group sections are OPTIONAL by construction
-------------------------------------------------------------
They read datasets the deployment may not carry, and a section built from an
absent dataset says so rather than being dropped. §1's rule holds: unavailability
is disclosed when it is relevant to the question, and "is anything happening
outside the bank" is a question this section exists to raise.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.early_warning import signals as sg
from backend.early_warning import taxonomy as tx

STORY_VERSION = "1.0.0"

# ---------------------------------------------------------------------------
# The sections, in the order a person asks the questions
# ---------------------------------------------------------------------------

WHY_HERE = "why_here"
TOP_RISK = "top_risk"
NEW = "new"
WORSENING = "worsening"
PERSISTENT = "persistent"
CURED = "cured"
EXTERNAL = "external"
GROUP = "group"
MITIGATING = "mitigating"
INVESTIGATE = "investigate"

#: The eight signal families, in the order a credit file is read: what the
#: business earns, whether it can pay, what it owes, what the facility is
#: actually doing, then the promises, the security, the bank's own opinion and
#: finally the booked accounting.
FAMILY_ORDER: tuple[str, ...] = (
    tx.FINANCIAL, tx.LIQUIDITY, tx.LEVERAGE, tx.BEHAVIOURAL,
    tx.COVENANT, tx.COLLATERAL, tx.RATING, tx.IFRS9,
)

QUESTIONS: dict[str, str] = {
    WHY_HERE: "Why is this borrower in front of me?",
    TOP_RISK: "What is the one thing here that matters most?",
    NEW: "What was not true last quarter?",
    WORSENING: "What is getting worse?",
    PERSISTENT: "What has been true for a while?",
    CURED: "What has gone away?",
    EXTERNAL: "Is anything happening outside the bank that bears on this?",
    GROUP: "Does the group this borrower sits in change the picture?",
    MITIGATING: "What argues the other way?",
    INVESTIGATE: "What should I go and look at?",
}

HEADINGS: dict[str, str] = {
    WHY_HERE: "Why this borrower is here",
    TOP_RISK: "The risk that matters most",
    NEW: "New this quarter",
    WORSENING: "Worsening",
    PERSISTENT: "Persistent",
    CURED: "Cured",
    EXTERNAL: "External and macro context",
    GROUP: "Connected group",
    MITIGATING: "Mitigating and contradictory evidence",
    INVESTIGATE: "Recommended investigation",
}


@dataclass
class Section:
    """One part of the story: a question, an answer, and the evidence."""

    key: str
    heading: str
    question: str
    #: The answer, in sentences. Empty means there is nothing to say, which is
    #: different from `unavailable`.
    body: list[str] = field(default_factory=list)
    #: The governed observations this section rests on. Ids and payloads, so a
    #: reader can go from the sentence to the signal that produced it.
    evidence: list[dict[str, Any]] = field(default_factory=list)
    #: Set when the section could not be built because the deployment does not
    #: carry the data. Never conflated with "there is nothing here".
    unavailable: str = ""

    @property
    def empty(self) -> bool:
        return not self.body and not self.evidence and not self.unavailable

    def to_dict(self) -> dict[str, Any]:
        return {"key": self.key, "heading": self.heading,
                "question": self.question, "body": list(self.body),
                "evidence": list(self.evidence),
                "unavailable": self.unavailable, "empty": self.empty}


@dataclass
class Story:
    """The whole position, in order."""

    borrower_id: str
    period: str
    sections: list[Section] = field(default_factory=list)
    families: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": STORY_VERSION,
            "borrower_id": self.borrower_id,
            "period": self.period,
            "sections": [s.to_dict() for s in self.sections],
            "families": list(self.families),
        }


# ---------------------------------------------------------------------------
# Composition
# ---------------------------------------------------------------------------


def _fired(standing: Any) -> list[Any]:
    return list(getattr(standing, "fired", []) or [])


def _shown(observation: Any) -> dict[str, Any]:
    return observation.to_dict() if hasattr(observation, "to_dict") \
        else dict(observation)


def _why_here(standing: Any) -> Section:
    """The verdict and the sentences behind it. R2 §25 already composed these;
    repeating the reasoning here would be a second opinion about the same
    evidence, and two wordings of one verdict is one wording too many."""
    section = Section(WHY_HERE, HEADINGS[WHY_HERE], QUESTIONS[WHY_HERE])
    verdict = getattr(standing, "verdict", None)
    if verdict is not None:
        because = list(getattr(verdict, "because", lambda: [])())
        section.body = because
    if not section.body:
        section.body = [str(getattr(standing, "sentence", "") or "")]
    return section


def _top_risk(standing: Any) -> Section:
    """The single most serious thing, named.

    Chosen by severity first and by how long it has been true second. A screen
    that leads with whichever signal happens to sort first is a screen that
    buries a covenant breach under a utilisation drift, and the officer reads
    the first line.
    """
    section = Section(TOP_RISK, HEADINGS[TOP_RISK], QUESTIONS[TOP_RISK])
    fired = _fired(standing)
    if not fired:
        return section
    worst = max(fired, key=lambda o: (
        tx.SEVERITY_RANK.get(getattr(o, "severity", ""), 0),
        1 if getattr(o, "lifecycle", "") == sg.WORSENING else 0,
        1 if getattr(o, "lifecycle", "") == sg.NEW else 0))
    said = str(getattr(worst, "means", "") or getattr(worst, "label", ""))
    family = tx.FAMILIES.get(getattr(worst, "family", ""), "")
    section.body = [said]
    if family:
        section.body.append(
            f"It sits in {family.lower()}, which is where this borrower's "
            "position is weakest this quarter.")
    section.evidence = [_shown(worst)]
    return section


def _by_lifecycle(standing: Any, state: str, key: str) -> Section:
    section = Section(key, HEADINGS[key], QUESTIONS[key])
    if key == CURED:
        found = list(getattr(standing, "cured", []) or [])
    else:
        found = [o for o in _fired(standing)
                 if getattr(o, "lifecycle", "") == state]
    if not found:
        return section
    section.evidence = [_shown(o) for o in found]
    section.body = [str(getattr(o, "means", "") or getattr(o, "label", ""))
                    for o in found]
    return section


def _persistent(standing: Any) -> Section:
    """Persisting AND improving-but-still-firing. A signal that is improving
    has not gone away, and filing it under "cured" would be the one place this
    screen could tell a comfortable untruth."""
    section = Section(PERSISTENT, HEADINGS[PERSISTENT], QUESTIONS[PERSISTENT])
    found = [o for o in _fired(standing)
             if getattr(o, "lifecycle", "") in (sg.PERSISTING, sg.IMPROVING)]
    if not found:
        return section
    section.evidence = [_shown(o) for o in found]
    section.body = [str(getattr(o, "means", "") or getattr(o, "label", ""))
                    for o in found]
    return section


def _families(standing: Any) -> list[dict[str, Any]]:
    """The eight families, in credit-file order, each saying what it holds.

    Every family appears, including the quiet ones. A family shown only when
    it has something to say is a family whose silence the reader cannot
    interpret: nothing fired, or nothing was tested?
    """
    fired = _fired(standing)
    untested = list(getattr(standing, "untested", []) or [])
    out: list[dict[str, Any]] = []
    for family in FAMILY_ORDER:
        hits = [o for o in fired if getattr(o, "family", "") == family]
        quiet = [o for o in untested if getattr(o, "family", "") == family]
        severity = ""
        if hits:
            severity = max((getattr(o, "severity", "") for o in hits),
                           key=lambda s: tx.SEVERITY_RANK.get(s, 0))
        out.append({
            "family": family,
            "label": tx.FAMILIES.get(family, family),
            "means": tx.FAMILY_MEANS.get(family, ""),
            "severity": severity,
            "fired": [_shown(o) for o in hits],
            "untested": [_shown(o) for o in quiet],
            "quiet": not hits and not quiet,
            "reading": _family_reading(family, hits, quiet),
        })
    return out


def _family_reading(family: str, hits: list[Any],
                    quiet: list[Any]) -> str:
    """One sentence about this family as a whole."""
    label = tx.FAMILIES.get(family, family)
    if hits:
        severe = [o for o in hits
                  if getattr(o, "severity", "") == tx.SEVERE]
        if severe:
            return (f"{label}: {len(hits)} condition(s) met, "
                    f"{len(severe)} of them severe.")
        return f"{label}: {len(hits)} condition(s) met, none severe."
    if quiet:
        return (f"{label}: nothing met, but {len(quiet)} test(s) could not "
                "be run on this borrower.")
    return f"{label}: every test ran and none was met."


def _mitigating(standing: Any) -> Section:
    """What argues the other way.

    Three things count: a conflict the engine itself detected, a signal that
    improved without curing, and a family that was tested in full and came
    back clean. The third is the one most screens omit, and it is evidence:
    "the covenants were all tested and none is breached" is a fact about this
    borrower, not an absence of one.
    """
    section = Section(MITIGATING, HEADINGS[MITIGATING], QUESTIONS[MITIGATING])
    said: list[str] = []
    # `conflict` is a list of FAMILY keys that disagree with each other, not a
    # sentence. Printing it raw put "['collateral', 'covenant', 'financial']"
    # on the screen, which is a Python repr where a reading belongs.
    conflict = list(getattr(standing, "conflict", []) or [])
    if conflict:
        named = ", ".join(tx.FAMILIES.get(f, f).lower() for f in conflict)
        said.append(
            f"The evidence does not all point one way: {named} disagree "
            "with each other, so the reading above rests on some families "
            "and is argued against by others.")

    improving = [o for o in _fired(standing)
                 if getattr(o, "lifecycle", "") == sg.IMPROVING]
    for observation in improving:
        said.append(
            f"{getattr(observation, 'label', '')} is still met but moving in "
            "the right direction.")

    fired_families = {getattr(o, "family", "") for o in _fired(standing)}
    untested_families = {getattr(o, "family", "")
                         for o in getattr(standing, "untested", []) or []}
    clean = [f for f in FAMILY_ORDER
             if f not in fired_families and f not in untested_families]
    if clean:
        said.append(
            "Tested in full and clean: "
            + ", ".join(tx.FAMILIES.get(f, f).lower() for f in clean) + ".")

    section.body = said
    section.evidence = [_shown(o) for o in improving]
    if not said:
        section.body = [
            "Nothing in the governed evidence argues against the reading "
            "above. That is not the same as there being nothing to say for "
            "this borrower — it is what the tested signals show."]
    return section


def _investigate(standing: Any) -> Section:
    """What to go and look at, in the order it is worth looking.

    Derived from what actually fired rather than from a fixed checklist: a
    borrower with a covenant breach and no delinquency is a different visit
    from one with 90 days past due and clean covenants, and a screen that
    recommends the same five things to both is a screen nobody reads twice.
    """
    section = Section(INVESTIGATE, HEADINGS[INVESTIGATE],
                      QUESTIONS[INVESTIGATE])
    steps: list[str] = []
    families = {getattr(o, "family", "") for o in _fired(standing)}
    severe = {getattr(o, "family", "") for o in _fired(standing)
              if getattr(o, "severity", "") == tx.SEVERE}

    if tx.COVENANT in families:
        steps.append(
            "Read the covenant schedule and confirm whether a breach has been "
            "waived, reset or is live. A waived breach and a live one are the "
            "same row of data and different credit positions.")
    if tx.LIQUIDITY in families:
        steps.append(
            "Ask for the cash-flow forecast and the committed undrawn lines. "
            "Liquidity is the family that moves first and the one a borrower "
            "can least easily present otherwise.")
    if tx.BEHAVIOURAL in families:
        steps.append(
            "Pull the facility statements for the quarter. Behaviour is "
            "observed rather than reported, so it is the part of the file "
            "that does not depend on the borrower's own account of itself.")
    if tx.COLLATERAL in families:
        steps.append(
            "Check the date of the last collateral valuation and whether the "
            "insurance and documentation are current.")
    if tx.RATING in families:
        steps.append(
            "Reconcile the internal grade with what the other families are "
            "saying. A grade that has not moved while three families have is "
            "a grade worth asking about.")
    if tx.IFRS9 in families:
        steps.append(
            "Confirm whether the stage on the books reflects the evidence "
            "here, and record the reason either way.")
    if tx.FINANCIAL in families or tx.LEVERAGE in families:
        steps.append(
            "Obtain the latest management accounts. The reported figures here "
            "are as at the reporting date and the position may have moved.")

    untested = list(getattr(standing, "untested", []) or [])
    if untested:
        steps.append(
            f"{len(untested)} test(s) could not be run on this borrower for "
            "want of data. Establish whether that is a gap in what the "
            "borrower supplies or a gap in what this deployment carries.")

    if severe:
        names = ", ".join(sorted(tx.FAMILIES.get(f, f).lower()
                                 for f in severe))
        steps.insert(0, f"Start with {names}: that is where the severe "
                        "conditions are.")
    if not steps:
        steps.append(
            "Nothing fired this quarter. The routine review is enough.")
    section.body = steps
    return section


def _external(standing: Any, sector: str = "") -> Section:
    """Governed external intelligence bearing on this borrower. R2 §23.

    Reads the external-intelligence domain built in §1. Every event carries
    its own evidence type, and the distinction the section preserves is §8's:
    a FACT IN CREDITPROBE DATA is not an ANALYTICAL HYPOTHESIS, and a screen
    that showed them in the same voice would be inviting a reader to treat a
    modelled link as an observation.
    """
    section = Section(EXTERNAL, HEADINGS[EXTERNAL], QUESTIONS[EXTERNAL])
    borrower = str(getattr(standing, "borrower_id", "") or "")
    period = str(getattr(standing, "period", "") or "")
    try:
        links = _external_links(borrower, period, sector=sector)
    except Exception as e:  # noqa: BLE001 - an absent domain is a fact to say
        section.unavailable = (
            "External intelligence is not available in this deployment, so "
            "nothing outside the bank has been checked against this "
            f"borrower. ({str(e)[:120]})")
        return section
    if not links:
        section.body = [
            "No governed external event is linked to this borrower at "
            f"{period or 'this period'}"
            + (f" or to the {sector} sector" if sector else "") + "."]
        return section
    for link in links:
        attached = (
            f"linked to this borrower on {link['link_basis']}"
            if link["basis"] == BY_BORROWER else
            f"recorded against the {sector} sector, which this borrower is "
            "in. It is not attached to this borrower individually")
        section.body.append(
            f"{link['headline']} — {attached}. This is "
            + ("an analytical hypothesis, not an observed fact about this "
               "borrower." if link["evidence_type"] == "ANALYTICAL_HYPOTHESIS"
               else "recorded in the governed data.")
            + (f" {link['scenario_status']}." if link.get("scenario_status")
               else ""))
    section.evidence = links
    return section


#: How an external event came to be attached to this borrower. The two are
#: different strengths of evidence and are never shown in the same voice: a
#: borrower-level link is a statement about THIS borrower, and a sector-level
#: one is a statement about a population it belongs to.
BY_BORROWER = "borrower"
BY_SECTOR = "sector"


def _headlines() -> dict[str, dict[str, Any]]:
    from backend.intelligence import reader

    out: dict[str, dict[str, Any]] = {}
    for name in ("sector_events", "macro_events"):
        frame = reader.load(name)
        if frame is None or getattr(frame, "empty", True):
            continue
        for row in frame.to_dict(orient="records"):
            out[str(row.get("event_id"))] = row
    return out


def _external_links(borrower_id: str, period: str,
                    sector: str = "") -> list[dict[str, Any]]:
    """Every governed external event bearing on this borrower.

    Read from the EVENT's own live window rather than from the link table's
    snapshot period, and the difference matters. `borrower_external_event_link`
    is built at one reporting date and stamped with it; an event that names
    Shipping and is live from Q1 2026 to Q2 2026 bears on a Shipping borrower
    in Q2 2026 whether or not the link table happened to be built that quarter.
    Filtering on the link's stamp instead reported "nothing external" for every
    borrower in a disrupted sector, which is the failure §23 exists to prevent.

    Two bases, and they are never shown in the same voice. A BORROWER-LEVEL
    link says the governed data attaches this event to this borrower. A
    SECTOR-LEVEL one says only that the borrower sits in a population the
    event names — weaker, useful, and not to be dressed up as the first.
    """
    from backend.intelligence import reader

    events = _headlines()
    if not events:
        raise LookupError("the external-intelligence domain is not built")

    live = [row for row in events.values()
            if _live_at(row, period) and _names(row, sector)]
    if not live:
        return []

    direct: set[str] = set()
    links = reader.load("borrower_external_event_link")
    if links is not None and not getattr(links, "empty", True):
        mine = links[links["customer_id"].astype(str) == borrower_id]
        direct = {str(v) for v in mine["event_id"].astype(str)} \
            if not mine.empty else set()

    out: list[dict[str, Any]] = []
    for row in live:
        event_id = str(row.get("event_id") or "")
        out.append({
            "event_id": event_id,
            "headline": str(row.get("headline") or event_id),
            "detail": str(row.get("detail") or ""),
            "severity": str(row.get("severity") or ""),
            "direction": str(row.get("direction") or ""),
            "first_period": str(row.get("first_period") or ""),
            "last_period": str(row.get("last_period") or ""),
            "basis": BY_BORROWER if event_id in direct else BY_SECTOR,
            "link_basis": "the governed borrower-event link"
                          if event_id in direct
                          else f"the {sector} sector, which this borrower is in",
            "evidence_type": str(row.get("evidence_type") or ""),
            "scenario": str(row.get("scenario") or ""),
            "scenario_status": str(row.get("scenario_status") or ""),
            "source": str(row.get("source") or ""),
        })
    return out


def _live_at(event: dict[str, Any], period: str) -> bool:
    """Whether the event is live at this reporting period.

    An event with no window is live: a governed event that forgot to say when
    it applies is a data-quality defect, and hiding it would hide the defect
    as well as the event.
    """
    if not period:
        return True
    first = str(event.get("first_period") or "")
    last = str(event.get("last_period") or "")
    if not first and not last:
        return True
    key = _period_key(period)
    if first and key < _period_key(first):
        return False
    return not (last and key > _period_key(last))


def _period_key(period: str) -> tuple[int, int]:
    from backend.intelligence import reader

    return reader.period_key(period)


def _names(event: dict[str, Any], sector: str) -> bool:
    """Whether the event names this borrower's sector.

    An event that names NO sector is macro and reaches everything; one that
    names sectors reaches only those. Treating an empty list as "reaches
    nothing" would silently drop every economy-wide event.
    """
    named = [s.strip() for s in str(event.get("sectors_affected") or "").split(",")
             if s.strip()]
    if not named:
        return True
    return bool(sector) and sector in named


def _group(standing: Any) -> Section:
    """What the connected group adds. R2 §2 built the reading; this asks what
    it MEANS for the borrower in front of the officer."""
    section = Section(GROUP, HEADINGS[GROUP], QUESTIONS[GROUP])
    borrower = str(getattr(standing, "borrower_id", "") or "")
    period = str(getattr(standing, "period", "") or "")
    try:
        from backend.corporate import service as corporate

        network = corporate.relationship_network(borrower, period, depth=2)
    except Exception as e:  # noqa: BLE001 - the graph may not be built
        section.unavailable = (
            "The relationship graph is not available for this borrower at "
            f"this period, so the group position has not been read. "
            f"({str(e)[:120]})")
        return section

    if not network.parties:
        section.body = [
            "No ownership, control or guarantee relationship is recorded for "
            "this borrower. It is assessed on its own position."]
        return section

    from backend.corporate import relationships as rel

    above = network.by_direction(rel.UPSTREAM)
    below = network.by_direction(rel.DOWNSTREAM)
    beside = network.by_direction(rel.LATERAL)
    controlling = [p for p in above if p.controls]

    said: list[str] = []
    if controlling:
        said.append(
            f"{controlling[0].label} controls this borrower, so its own "
            "position is part of this one.")
    elif above:
        said.append(
            f"{len(above)} part(y/ies) stand above this borrower, none with "
            "a controlling stake.")
    if beside:
        said.append(
            f"{len(beside)} entity/entities sit under the same owner. "
            "Deterioration here is worth checking against them.")
    if below:
        said.append(f"This borrower carries {len(below)} relationship(s) "
                    "below it.")
    said.append(
        f"Group exposure is SAR {network.group_exposure:,.1f}m across "
        f"{network.to_dict()['group_borrowers']} borrower(s) on this book"
        + (", and the network was truncated so that is a floor."
           if network.truncated else "."))
    section.body = said
    section.evidence = [p.to_dict() for p in network.parties[:20]]
    return section


def build(standing: Any, *, sector: str = "",
          external: bool = True, group: bool = True) -> Story:
    """The whole story for one borrower.

    `external` and `group` are switches because both read datasets outside the
    Early Warning book, and a caller rendering fifty rows should not pay for
    fifty graph traversals. The detail view asks for both; the list does not.
    """
    story = Story(borrower_id=str(getattr(standing, "borrower_id", "") or ""),
                  period=str(getattr(standing, "period", "") or ""))
    story.sections = [
        _why_here(standing),
        _top_risk(standing),
        _by_lifecycle(standing, sg.NEW, NEW),
        _by_lifecycle(standing, sg.WORSENING, WORSENING),
        _persistent(standing),
        _by_lifecycle(standing, sg.CURED, CURED),
    ]
    if external:
        story.sections.append(_external(standing, sector=sector))
    if group:
        story.sections.append(_group(standing))
    story.sections += [_mitigating(standing), _investigate(standing)]
    story.families = _families(standing)
    return story


__all__ = ["CURED", "EXTERNAL", "FAMILY_ORDER", "GROUP", "HEADINGS",
           "INVESTIGATE", "MITIGATING", "NEW", "PERSISTENT", "QUESTIONS",
           "STORY_VERSION", "Section", "Story", "TOP_RISK", "WHY_HERE",
           "WORSENING", "build"]
