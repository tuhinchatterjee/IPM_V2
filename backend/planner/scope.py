"""What the Project Planner Copilot will and will not talk about.

The Copilot is a delivery-management assistant. It knows about projects,
milestones, tasks, owners, dates, dependencies, risks and who is late. It does
not know about IFRS 9 staging, scorecard validation, Early Warning signals,
Borrower 360, the Data Builder catalogue, Lenses or Playbooks — not because
those are secret, but because a delivery assistant that answers a provisioning
question is a delivery assistant nobody can trust the delivery answers from.

The boundary is enforced HERE, in the backend, and not in a system prompt.
A prompt is a request; this is a rule. Two mechanisms, both required:

  the tool allowlist   `copilot.py` gives the Copilot an agent whose
                       `allowed_tools` contains only planner tools, so the
                       ordinary `agentic.tools` gate refuses anything else
                       even if a model asks for it by name;
  this classifier      refuses the QUESTION before any tool is chosen, so a
                       question the Copilot has no tool for gets a sentence
                       telling the person where the answer lives rather than
                       a shrug or, worse, a guess.

The hard part is not the refusal. It is not refusing the wrong thing.

"How is the Retail Application Scorecard Redevelopment going?" is a delivery
question about a project that happens to be named after a scorecard. "What is
the KS of the retail application scorecard?" is a scorecard question. The
words overlap almost entirely, and a classifier that matched on "scorecard"
would refuse the first — which would be worse than having no boundary at all,
because the project it refused to discuss is the one the demo is built on.

So the rule is: a foreign topic only puts a question out of scope when the
question is not already anchored to something in the plan. A phrase that
appears in a project, milestone or task the person can see is a name, and a
name is planner vocabulary no matter what it is named after.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

SCOPE_VERSION = "1.0.0"


@dataclass(frozen=True)
class Foreign:
    """One area of CreditProbe that is not the Project Planner."""

    key: str
    #: What a person calls it.
    label: str
    #: Where the answer actually lives, named so the refusal is useful.
    where: str
    #: Phrases that mean somebody is asking this area's question. Deliberately
    #: specific: "scorecard" alone is a word that appears in project names,
    #: "scorecard validation" and "gini" are not.
    patterns: tuple[str, ...] = ()


AREAS: tuple[Foreign, ...] = (
    Foreign(
        "ifrs9", "IFRS 9 and expected credit loss",
        "Ask CreditProbe, which has the staging and ECL engines behind it",
        patterns=(
            r"\bifrs\s*9\b", r"\becl\b", r"\bexpected credit loss(es)?\b",
            r"\bstage\s*[123]\b", r"\bstaging\b", r"\blifetime pd\b",
            r"\bsignificant increase in credit risk\b", r"\bsicr\b",
            r"\bprovision(s|ing)?\b", r"\bimpairment\b",
            r"\bloss allowance\b",
        )),
    Foreign(
        "scorecard", "Scorecard Validation",
        "the Scorecard Validation module",
        patterns=(
            r"\bscorecard validation\b", r"\bvalidate the scorecard\b",
            r"\bgini\b", r"\bks statistic\b", r"\bks stat\b",
            r"\bpopulation stability index\b", r"\bpsi\b",
            r"\bcharacteristic stability\b", r"\bauc\b", r"\broc curve\b",
            r"\bdiscriminatory power\b", r"\bcalibration curve\b",
            r"\bscore band(s)?\b", r"\breject inference\b",
            r"\bhosmer\b", r"\bbrier score\b",
        )),
    Foreign(
        "early_warning", "Early Warning",
        "the Early Warning module",
        patterns=(
            r"\bearly warning\b", r"\bwatchlist\b", r"\bwatch list\b",
            r"\bforward risk signal\b", r"\bdeterioration signal(s)?\b",
            r"\bcovenant(s| breach| headroom)?\b",
        )),
    Foreign(
        "borrower360", "Borrower 360",
        "Borrower 360",
        patterns=(
            r"\bborrower\s*360\b", r"\bownership structure\b",
            r"\bultimate beneficial owner\b", r"\bubo\b",
            r"\bcounterparty group\b", r"\bconnected part(y|ies)\b",
            r"\bexposure to (the )?group\b",
        )),
    Foreign(
        "data_builder", "the Data Builder",
        "the Data Builder",
        patterns=(
            r"\bdata builder\b", r"\bdataset(s)?\b", r"\bdata catalogue\b",
            r"\bpublish (a |the )?dataset\b", r"\bjoin path\b",
            r"\bdata domain(s)?\b", r"\bcolumn(s)? in\b", r"\bschema drift\b",
            r"\bupload (a |the )?file\b",
        )),
    Foreign(
        "lenses", "Lenses",
        "the Lenses module",
        patterns=(r"\blens(es)?\b", r"\bmetric catalogue\b",
                  r"\bmetric definition\b")),
    Foreign(
        "playbook", "Playbooks",
        "the Playbook module",
        patterns=(r"\bplaybook(s)?\b", r"\bcommittee pack\b",
                  r"\bmanagement pack\b", r"\bboard pack\b")),
    Foreign(
        "portfolio", "portfolio credit analytics",
        "Ask CreditProbe",
        patterns=(
            r"\bportfolio (analytics|quality|performance)\b",
            r"\bdpd\b", r"\bdays past due\b", r"\bdelinquenc(y|ies)\b",
            r"\bvintage analysis\b", r"\broll rate(s)?\b",
            r"\bnpl ratio\b", r"\bcost of risk\b", r"\bloan tape\b",
            r"\bexposure at default\b", r"\bloss given default\b",
            r"\bprobability of default\b",
            r"\bconcentration risk\b", r"\bstress test(ing)?\b",
            r"\bwhat[- ]if scenario\b",
        )),
    Foreign(
        "corporate", "corporate and retail credit assessment",
        "Ask CreditProbe",
        patterns=(
            r"\bcredit rating\b", r"\brating grade\b",
            r"\bunderwrit(e|ing)\b", r"\bcredit decision\b",
            r"\bapprove (this |the )?(loan|facility|application)\b",
            r"\bfinancial spread(ing|s)?\b", r"\bdebt service coverage\b",
            r"\bcollateral valuation\b",
        )),
)

_COMPILED: tuple[tuple[Foreign, tuple[re.Pattern[str], ...]], ...] = tuple(
    (area, tuple(re.compile(p, re.IGNORECASE) for p in area.patterns))
    for area in AREAS)


#: What the Copilot is for, said once, so every surface says it the same way.
PURPOSE = (
    "I look after project delivery: plans, milestones, tasks, owners, dates, "
    "dependencies, risks and who needs chasing.")


@dataclass
class Decision:
    """Whether a question is the Copilot's to answer."""

    in_scope: bool
    #: The area that took it out of scope, empty when it is in scope.
    area: str = ""
    label: str = ""
    #: What the person typed that triggered it, quoted back so the refusal is
    #: checkable rather than mysterious.
    matched: str = ""
    message: str = ""
    #: Names from the plan that kept an otherwise-foreign phrase in scope.
    anchors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"in_scope": self.in_scope, "area": self.area,
                "label": self.label, "matched": self.matched,
                "message": self.message, "anchors": list(self.anchors)}


#: Sentences that ask the Copilot to PRODUCE a number or an assessment,
#: rather than to talk about a piece of work by its name.
#:
#: Containment forgives a foreign phrase that sits inside something the plan
#: is called — that is what lets somebody discuss the "Retail Application
#: Scorecard Redevelopment" programme without being told scorecards are
#: somewhere else. But a project whose tasks are named after the metrics
#: they produce turns that kindness into a hole: name a task "Population
#: stability index review" and the planner Copilot would accept "what is the
#: population stability index?" — a question it cannot answer, asked of the
#: one part of the product that has no data to answer it with.
#:
#: So: a phrase used as a NAME is forgiven; a phrase being asked FOR is not,
#: however it is spelled. The cue is the shape of the question, not the noun.
_FOR_A_VALUE = re.compile(
    r"\b(?:what(?:'|’)?s|what\s+is|what\s+are|what\s+was|what\s+were|"
    r"how\s+much|how\s+many|how\s+high|how\s+low|"
    r"calculate|compute|work\s+out|re-?run|back-?test|"
    r"give\s+me\s+the|show\s+me\s+the|tell\s+me\s+the|"
    r"what\s+does\s+the\s+\w+\s+say)\b",
    re.IGNORECASE)


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def occurrences(message: str, names: Any) -> list[tuple[int, int, str]]:
    """Where the plan's own names appear in this message, as spans.

    A project called "Retail Application Scorecard Redevelopment" makes those
    words planner vocabulary — but only where they are being used as its name.
    Spans rather than a yes/no, because the question that matters below is not
    "does the name appear?" but "is the foreign phrase PART of the name?".

    Runs of two or more consecutive words count, so "the scorecard
    redevelopment" finds the project. A single word never does: "scorecard"
    on its own is a subject, not a name.
    """
    haystack = _normalise(message).lower()
    if not haystack:
        return []
    spans: list[tuple[int, int, str]] = []

    def add(needle: str, name: str) -> bool:
        at = haystack.find(needle)
        marked = False
        while at != -1:
            spans.append((at, at + len(needle), name))
            marked = True
            at = haystack.find(needle, at + 1)
        return marked

    for name in names or ():
        text = _normalise(name).lower()
        if not text:
            continue
        if len(text) >= 4 and add(text, str(name)):
            continue
        words = text.split()
        for size in range(len(words), 1, -1):
            runs = {" ".join(words[i:i + size])
                    for i in range(len(words) - size + 1)}
            if any(add(run, str(name)) for run in runs):
                break
    return spans


def anchored(message: str, names: Any) -> list[str]:
    """The plan's own names that appear in this message, deduplicated."""
    found: list[str] = []
    for _start, _end, name in occurrences(message, names):
        if name not in found:
            found.append(name)
    return found


def classify(message: str, *, names: Any = ()) -> Decision:
    """Is this the Copilot's question?

    `names` is whatever the asking person can already see — project names,
    milestone names, task titles, codes. It is not optional in practice: a
    classifier without it refuses the demo project by its own name.

    The test is not "does a foreign word appear" but "is EVERY foreign phrase
    being used as part of something's name". "How is the IFRS 9 Model
    Redevelopment going?" is a delivery question; "what is the ECL under the
    IFRS 9 Model Redevelopment?" is not, and the difference is that `ECL` sits
    outside the name while `IFRS 9` sits inside it. Every match is checked,
    not the first one: a question that names a project and then asks another
    module's question about it is the other module's question.
    """
    text = _normalise(message)
    if not text:
        return Decision(True)

    spans = occurrences(text, names)
    lowered = text.lower()
    asking_for_a_value = bool(_FOR_A_VALUE.search(lowered))

    def inside(where: tuple[int, int]) -> bool:
        return any(start <= where[0] and where[1] <= end
                   for start, end, _name in spans)

    def refuse(area: Foreign, matched: str) -> Decision:
        return Decision(
            False, area=area.key, label=area.label, matched=matched,
            anchors=anchored(text, names),
            message=(f"That is a question about {area.label}, and I only "
                     f"look after project delivery. You will find it in "
                     f"{area.where}. {PURPOSE}"))

    #: A foreign phrase that appeared only inside something the plan is
    #: called. Kept rather than discarded, because it is the answer when the
    #: sentence turns out to be asking for a value.
    named: tuple[Foreign, str] | None = None
    for area, patterns in _COMPILED:
        for pattern in patterns:
            for found in pattern.finditer(lowered):
                if inside(found.span()):
                    if named is None:
                        named = (area, found.group(0))
                    continue
                return refuse(area, found.group(0))

    # Nothing foreign outside a name. If the sentence is nevertheless asking
    # for a number, the name it borrowed is the thing being asked for, and
    # this is not the place to ask.
    if named is not None and asking_for_a_value:
        return refuse(*named)
    return Decision(True, anchors=anchored(text, names))


def names_in_reach(session: Any, principal: Any, *, limit: int = 400) -> list[str]:
    """Every project, milestone and task name this person can see.

    Read through the ordinary access rules, so the anchoring above cannot be
    used to confirm that a project exists: a name somebody cannot see is not
    in the list, and their question is classified as though it did not exist.
    """
    from sqlalchemy import select

    from backend.models.planner import (
        PlannerMilestone,
        PlannerProject,
        PlannerTask,
    )
    from backend.planner import access as acl

    ids = acl.readable_project_ids(session, principal)
    if not ids:
        return []
    found: list[str] = []
    for row in session.execute(
            select(PlannerProject.name, PlannerProject.code)
            .where(PlannerProject.id.in_(ids))):
        found.extend(str(v) for v in row if v)
    for row in session.execute(
            select(PlannerMilestone.name, PlannerMilestone.code)
            .where(PlannerMilestone.project_id.in_(ids)).limit(limit)):
        found.extend(str(v) for v in row if v)
    for row in session.execute(
            select(PlannerTask.title, PlannerTask.code)
            .where(PlannerTask.project_id.in_(ids)).limit(limit)):
        found.extend(str(v) for v in row if v)
    return found


__all__ = ["AREAS", "Decision", "Foreign", "PURPOSE", "SCOPE_VERSION",
           "anchored", "classify", "names_in_reach", "occurrences"]
