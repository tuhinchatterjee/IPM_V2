"""
Corporate relationship-graph teaching blueprints. B45-B49.

Seventeen families, five hundred and seventy-eight cases, built the same
honest way as the canonical and scorecard corpora: the *specification* of
each family was written and reviewed once, the *subject* comes from the
governed graph vocabulary - real edge types, real quarters, real quality
check ids, real measure names read from `backend.corporate` - and the
*phrasing* is generated.

Why the families are cut this finely
--------------------------------------
The relationship graph is the part of CreditProbe where a confident wrong
answer is most expensive, and the reason is structural: every one of these
families has a near-neighbour that a plausible answer could quietly
substitute for it.

* Connectivity is not connectedness. A path in the graph is not a regulatory
  determination about a group of connected counterparties.
* A community is not a group. Modularity finds a cluster; it makes no claim
  about anybody in it.
* A DebtRank impact is a fraction, and it rises with distress, which is
  exactly why it reads like a loss rate and exactly why it is not one.
* A Network Risk Score is a ranking inside one population, not a
  probability, and there is no arithmetic that turns it into one.
* Proportional ownership and control closure disagree by design, so an
  answer that reconciles them has broken one of them.

Merging any of those pairs into one family would make the score
uninterpretable: every case that tested one would accept an answer about the
other. Separate families make the confusions separable.

What no case carries
----------------------
A figure. Not one. An impact, a score, a group size or a utilisation stored
as teaching truth is correct for one quarter and wrong for every quarter
after it — and the graph is rebuilt quarterly. Cases teach which measure, on
which population, as at which date, with which refusal. The arithmetic
belongs to the engine.

The traps
-----------
Every blueprint records what its question is usually got wrong, as forbidden
behaviours on the case. For this module they are unusually concrete, because
graph analytics has a small set of errors that recur and each one has a name:

* presenting graph connectivity as regulatory connectedness;
* reading DebtRank as an expected credit loss or a capital number;
* reading the Network Risk Score as a probability, a PD or a rating;
* treating a Louvain community as a legal or economic group;
* letting a similarity match create control, beneficial ownership or group
  membership on its own;
* reconciling control closure to proportional ownership;
* returning a number for a computation a data-quality check rejected;
* quoting the group limit as binding law rather than as an unverified
  regulatory parameter.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from backend.corporate import graphdata as gd
from backend.corporate import graphquality as gq
from backend.corporate import graphsummary as gs
from backend.corporate import service as svc
from backend.teaching import families as fam
from backend.teaching import schema as sc
from intelligence_factory.teaching import canonical as cn
from intelligence_factory.teaching import migrate as mg

GRAPH_VERSION = "1.0.0"

# ------------------------------------------------------------- vocabulary
# Read from the modules rather than restated, so an edge type renamed in the
# graph renames itself here and a case cannot drift onto a relationship that
# no longer exists.

QUARTERS: tuple[str, ...] = tuple(gd.QUARTERS)
SECTORS: tuple[str, ...] = tuple(s.name for s in gd.SECTORS)
EDGES: tuple[str, ...] = tuple(gd.OBSERVED_EDGE_TYPES)
NODES: tuple[str, ...] = tuple(gd.NODE_TYPES)

GROUPS_DATASET = gs.GROUPS_DATASET
DQ_DATASET = gs.DQ_DATASET

#: The six group concepts, as the service declares them. A case draws its
#: subject from here so the corpus cannot invent a seventh, and so the
#: "is NOT" clause a case forbids is the one the product actually publishes.
CONCEPTS: tuple[dict[str, Any], ...] = tuple(svc.GROUP_CONCEPTS)
CONCEPT_KEYS: tuple[str, ...] = tuple(c["key"] for c in CONCEPTS)

VIEWS: tuple[str, ...] = tuple(v["key"] for v in svc.NETWORK_VIEWS)

#: Data-quality checks by their function name, which is also how the report
#: identifies them. Named from the module so a check added to the graph
#: becomes askable here without anybody remembering to add it.
CHECK_NAMES: tuple[str, ...] = tuple(
    check.__name__.removeprefix("check_")
    for check in (*gq.CHECKS, *gq.DATED_CHECKS))
COMPUTATIONS: tuple[str, ...] = tuple(gq.COMPUTATIONS)

#: How a credit officer says each derived measure out loud, paired with the
#: governed field it must resolve to. The left-hand side is what the planner
#: has to produce; the right-hand side is what gets into a question.
MEASURES: tuple[tuple[str, str], ...] = (
    ("network_risk_score", "the Network Risk Score"),
    ("debtrank_impact", "the DebtRank impact"),
    ("pagerank_transmits", "forward PageRank"),
    ("pagerank_hurt", "reverse PageRank"),
    ("betweenness", "betweenness"),
    ("louvain_community", "the network community"),
    ("ubo_count", "the number of ultimate beneficial owners"),
    ("connected_group_size", "the connected group size"),
    ("group_exposure", "the group's exposure"),
    ("group_utilisation_pct", "group limit utilisation"),
    ("graph_confidence", "the graph evidence confidence"),
)

#: Thresholds, named as the parameters they are. The percentages come from
#: the module rather than being typed here, so a policy change moves the
#: corpus with it instead of leaving 500 cases asserting the old figure.
UBO_THRESHOLD = gs.OWNERSHIP_GROUP_THRESHOLD_PCT
GROUP_LIMIT = gs.GROUP_LIMIT_PCT
TRIGGER = gs.INVESTIGATION_TRIGGER_PCT

# Borrower ids are drawn as SHAPES rather than as specific customers: a case
# naming CORP-100417 is correct until the universe is regenerated with a
# different seed. "the borrower under review" and "this counterparty" are
# what a credit officer types anyway.
SUBJECTS: tuple[str, ...] = (
    "the borrower under review", "this counterparty", "this obligor",
    "the name on the screen", "this client", "the borrower in this case")


def pick(items: tuple[Any, ...], seed: str, offset: int = 0) -> Any:
    """A deterministic choice, on this module's own hash namespace.

    Namespaced `graph:` so adding a graph blueprint cannot reshuffle the
    canonical or scorecard corpora, which would make two runs' scores
    incomparable for reasons that have nothing to do with either corpus.
    """
    digest = hashlib.sha256(f"graph:{seed}:{offset}".encode()).digest()
    return items[int.from_bytes(digest[:4], "big") % len(items)]


#: Question openers, in the registers a real inbox contains. The clipped and
#: misspelled forms are not decoration: a relationship manager types "who
#: really owns this" and "grp exposure?" into a box, and a corpus that only
#: contains careful prose teaches a model to need careful prose.
FORMAL: tuple[str, ...] = (
    "Please report", "Could you show me", "I would like to see",
    "Report", "Show me", "Give me")
DIRECT: tuple[str, ...] = (
    "what's", "whats", "who's", "how big is", "can I see")
TYPOS: dict[str, str] = {
    "ownership": "onwership", "beneficial": "benefical",
    "connected": "conected", "counterparty": "counterpaty",
    "centrality": "centrallity", "guarantee": "gurantee",
    "subsidiary": "subsidary", "utilisation": "utilistaion",
}
ABBREVIATIONS: dict[str, str] = {
    "ultimate beneficial owner": "UBO",
    "Network Risk Score": "NRS",
    "connected counterparty group": "CCG",
    "exposure at default": "EAD",
    "data quality": "DQ",
    "know your customer": "KYC",
}


def _quarter(seed: str, offset: int = 3) -> str:
    return pick(QUARTERS, seed, offset)


def _subject(seed: str, offset: int = 4) -> str:
    return pick(SUBJECTS, seed, offset)


def _sector(seed: str, offset: int = 5) -> str:
    return pick(SECTORS, seed, offset)


def build(*, family: str, title: str, turns: list[cn.Turn],
          objectives: tuple[str, ...], difficulty: str = sc.INTERMEDIATE,
          risk: str = "MEDIUM", capability: str = "ANALYSIS",
          outcome: str = fam.EXECUTE, officer: int = 2,
          **fields: Any) -> sc.TeachingCase:
    """One graph case. Corporate scope is not optional here.

    Every case in this module declares CORPORATE, because the whole module
    is about a relationship graph over the corporate book and a case that
    left the scope open would be a case the retail side could match against
    — which is exactly the scope bleed the separation tests exist to catch.
    """
    case = cn.build(family=family, title=title, turns=turns,
                    objectives=objectives, difficulty=difficulty, risk=risk,
                    capability=capability, outcome=outcome, officer=officer,
                    **fields)
    case.portfolio_scope = fam.CORPORATE
    return case


#: The refusals that belong to almost every graph family, written once. A
#: family adds its own on top rather than restating these.
CONNECTIVITY = ("presenting graph connectivity as a regulatory determination "
                "of connectedness")
UNGROUNDED = "quoting a figure that no computed result contains"
BLOCKED = ("returning a number for a computation a data-quality check "
           "rejected, instead of DATA_QUALITY_BLOCKED")
SYNTHETIC = ("presenting a synthetic demonstration relationship as an "
             "observed client fact")


def _caveat(*extra: str) -> dict[str, Any]:
    return cn._forbids(CONNECTIVITY, UNGROUNDED, *extra)


# ---------------------------------------------------------------------------
# What the graph holds, answered from metadata
# ---------------------------------------------------------------------------


def _data_discovery(seed: str) -> sc.TeachingCase:
    """Which graph data exists, answered from the catalogue."""
    subject, phrase, standalone = pick((
        ("edge types", "the relationship types the graph records",
         "Which relationships does the graph hold"),
        ("quarters", "the quarters the graph covers",
         "How far back does the relationship graph go"),
        ("node types", "the entity types the graph distinguishes",
         "What kinds of entity are in the graph"),
        ("derived measures", "the derived network measures held per borrower",
         "Which network measures are computed"),
        ("group datasets", "the datasets the graph publishes",
         "Which datasets does the graph module publish"),
        ("quality checks", "the data-quality checks run over the graph",
         "What quality checks run over the relationship data"),
        ("as-at rule", "the as-at rule the graph reads relationships under",
         "How does the graph decide what was true on a date"),
        ("evidence", "the evidence types a derived edge can rest on",
         "What evidence can a derived relationship rest on"),
    ), seed, 6)
    if pick((True, False), seed, 7):
        question = f"{pick(FORMAL, seed, 8)} {phrase}."
    else:
        question = f"{standalone}?"
    return build(
        family="GRAPH_DATA_DISCOVERY",
        title=f"graph {subject}",
        turns=[cn.Turn(question, result_type="NARRATIVE",
                       behaviour="Must answer from the catalogue and the "
                                 "graph's declared vocabulary. Must not "
                                 "traverse the graph to find out what it "
                                 "contains.")],
        objectives=(f"name the governed graph {subject}",
                    "state the quarters the graph covers"),
        difficulty=sc.FOUNDATIONAL, risk="LOW", capability="DATA_DISCOVERY",
        officer=1, required_datasets=[GROUPS_DATASET],
        metrics=[], concepts=["relationship graph", subject],
        analytical_plan_contract={"capability": "DATA_DISCOVERY",
                                  "reads_metadata_only": True},
        result_contract={"shape": "a description of held graph data"},
        scope_contract=cn._forbids(
            "traversing the graph to answer a metadata question",
            "naming a quarter outside the governed range", SYNTHETIC))


# ---------------------------------------------------------------------------
# Ownership, beneficial ownership and control
# ---------------------------------------------------------------------------


def _ownership(seed: str) -> sc.TeachingCase:
    """Integrated ownership through the chain, not the direct stake."""
    who = _subject(seed)
    quarter = _quarter(seed)
    angle, clause, objective = pick((
        ("integrated stake",
         f"the integrated ownership of {who} through the whole chain",
         "report ownership integrated through every intermediate holding"),
        ("direct versus integrated",
         f"how the direct shareholdings in {who} differ from the "
         "integrated stakes",
         "state the direct figure and the integrated figure separately"),
        ("chain",
         f"the ownership chain from {who} up to its ultimate holders",
         "name each intermediate holding on the path"),
        ("pyramid",
         f"whether {who} sits under a pyramid structure",
         "say how many layers separate the borrower from its holders"),
        ("cross-holding",
         f"whether any cross-holding inflates the direct stakes in {who}",
         "state whether reciprocal holdings are present"),
        ("parent",
         f"which entity holds the largest integrated stake in {who}",
         "name the largest integrated holder"),
    ), seed, 9)
    opener = pick(FORMAL, seed, 10)
    question = f"{opener} {clause} as at {quarter}."
    return build(
        family="GRAPH_OWNERSHIP_STRUCTURE",
        title=f"integrated ownership: {angle}",
        turns=[cn.Turn(question,
                       behaviour="Must compute integrated ownership through "
                                 "the chain and must not present a direct "
                                 "shareholding as the answer. The two are "
                                 "different numbers and a pyramid is built "
                                 "precisely so they differ.")],
        objectives=(objective,
                    "state the as-at date the ownership was read under",
                    "distinguish direct from integrated"),
        difficulty=sc.COMPLEX, risk="HIGH",
        required_datasets=[GROUPS_DATASET],
        metrics=["effective_ownership_pct"],
        concepts=["ownership", "effective ownership"],
        analytical_plan_contract={"as_of_quarter": quarter,
                                  "method": "integrated_ownership"},
        result_contract={"shape": "ownership percentages with their basis"},
        scope_contract=_caveat(
            "presenting a direct shareholding as an integrated stake",
            "summing stakes across layers of the same chain", BLOCKED))


def _beneficial_ownership(seed: str) -> sc.TeachingCase:
    """Natural persons at or above the declared threshold."""
    who = _subject(seed)
    quarter = _quarter(seed)
    angle, clause, objective = pick((
        ("identify", f"the ultimate beneficial owners of {who}",
         "name the natural persons whose integrated stake reaches the "
         "threshold"),
        ("threshold", f"which natural persons reach the threshold behind {who}",
         "state the threshold as a policy parameter, not as law"),
        ("none found", f"whether any beneficial owner is identified for {who}",
         "say that no owner was FOUND rather than that none exists"),
        ("through the chain",
         f"the beneficial owners of {who} counted through the whole chain",
         "count integrated rather than direct stakes"),
        ("shared owner",
         f"whether {who} shares a beneficial owner with any other borrower",
         "name the borrowers the owner is shared with"),
        ("count", f"how many beneficial owners {who} has",
         "report the count and the threshold it was counted at"),
    ), seed, 11)
    if pick((True, False), seed, 12):
        question = f"{pick(FORMAL, seed, 13)} {clause} as at {quarter}."
    else:
        question = (f"Who really owns {who}? I need it as at {quarter} for "
                    f"{pick(('KYC', 'the file', 'the credit committee'), seed, 14)}.")
    return build(
        family="GRAPH_BENEFICIAL_OWNERSHIP",
        title=f"beneficial ownership: {angle}",
        turns=[cn.Turn(question,
                       behaviour="Must count natural persons whose "
                                 "INTEGRATED stake reaches the declared "
                                 "threshold, must state the threshold as a "
                                 "policy parameter, and must distinguish "
                                 "'no owner found' from 'no owner exists'.")],
        objectives=(objective,
                    f"name the {UBO_THRESHOLD:g}% threshold as a declared "
                    "parameter rather than as binding law",
                    "state the as-at date"),
        difficulty=sc.COMPLEX, risk="HIGH",
        required_datasets=[GROUPS_DATASET], metrics=["ubo_count"],
        concepts=["ultimate beneficial owner", "ownership"],
        analytical_plan_contract={
            "as_of_quarter": quarter,
            "threshold": "OWNERSHIP_GROUP_THRESHOLD_PCT"},
        result_contract={"shape": "identified natural persons and the "
                                  "threshold they were identified at"},
        scope_contract=_caveat(
            "reporting an absence of data as an absence of an owner",
            "counting direct shareholdings instead of integrated stakes",
            "presenting the threshold as a legal requirement", BLOCKED))


def _control_closure(seed: str) -> sc.TeachingCase:
    """The control test and its closure, kept apart from ownership."""
    who = _subject(seed)
    quarter = _quarter(seed)
    angle, clause, objective = pick((
        ("closure", f"the entities {who} controls, including indirectly",
         "apply the control test transitively"),
        ("versus ownership",
         f"why the control closure of {who} does not match its proportional "
         "ownership",
         "explain that the two tests answer different questions"),
        ("controller", f"who controls {who}",
         "name the controlling entity and the basis of control"),
        ("de facto", f"whether {who} is controlled without a majority stake",
         "state the basis on which control was concluded"),
        ("chain", f"the control chain above {who}",
         "name each step of the control chain"),
        ("role", f"whether {who} is a parent, a subsidiary or standalone",
         "state the role over the corporate members of its bloc"),
    ), seed, 15)
    question = f"{pick(FORMAL, seed, 16)} {clause} as at {quarter}."
    return build(
        family="GRAPH_CONTROL_CLOSURE",
        title=f"control closure: {angle}",
        turns=[cn.Turn(question,
                       behaviour="Must apply the control test and its "
                                 "transitive closure. Must NOT reconcile "
                                 "the closure to proportional ownership: "
                                 "control is not proportional and the two "
                                 "differ by design.")],
        objectives=(objective,
                    "state that control closure and proportional ownership "
                    "differ by design",
                    "state the as-at date"),
        difficulty=sc.COMPLEX, risk="HIGH",
        required_datasets=[GROUPS_DATASET],
        metrics=["control_closure"],
        concepts=["control group", "ownership"],
        analytical_plan_contract={"as_of_quarter": quarter,
                                  "method": "control_closure"},
        result_contract={"shape": "controlled entities and the basis"},
        scope_contract=_caveat(
            "reconciling control closure to proportional ownership",
            "reading a minority stake as control without a stated basis",
            BLOCKED))


# ---------------------------------------------------------------------------
# Groups: the candidate group, the limit, and the six concepts
# ---------------------------------------------------------------------------


def _connected_group(seed: str) -> sc.TeachingCase:
    """A connected counterparty CANDIDATE group."""
    who = _subject(seed)
    quarter = _quarter(seed)
    angle, clause, objective = pick((
        ("membership", f"which borrowers are in the connected group with {who}",
         "list the group members and the basis for each"),
        ("size", f"how large the connected group around {who} is",
         "report the member count"),
        ("basis", f"why {who} is grouped with the others in its group",
         "name the control or interdependence basis"),
        ("candidate", f"whether the group around {who} is a determination",
         "state that it is a CANDIDATE group for assessment"),
        ("interdependence",
         f"whether economic interdependence brought anybody into {who}'s group",
         "distinguish control-formed members from interdependence merges"),
        ("changed", f"whether {who}'s group membership changed into {quarter}",
         "state what changed and on what evidence"),
    ), seed, 17)
    question = f"{pick(FORMAL, seed, 18)} {clause} as at {quarter}."
    return build(
        family="GRAPH_CONNECTED_GROUP",
        title=f"connected group: {angle}",
        turns=[cn.Turn(question,
                       behaviour="Must present the group as a CANDIDATE "
                                 "formed from effective control and "
                                 "validated economic interdependence, for "
                                 "assessment under the institution's own "
                                 "approved criteria. Graph connectivity is "
                                 "not regulatory connectedness.")],
        objectives=(objective,
                    "state that the group is a candidate rather than a "
                    "determination",
                    "state the as-at date"),
        difficulty=sc.COMPLEX, risk="HIGH",
        required_datasets=[GROUPS_DATASET],
        metrics=["connected_group_size"],
        concepts=["connected group", "control group"],
        analytical_plan_contract={"as_of_quarter": quarter,
                                  "group_concept": "connected_counterparty_group"},
        result_contract={"shape": "candidate group members and the basis"},
        scope_contract=_caveat(
            "describing the group as a regulatory determination",
            "including a similarity match as a group member", BLOCKED))


def _group_limit(seed: str) -> sc.TeachingCase:
    """Group exposure against the reference, with the parameter named."""
    who = _subject(seed)
    quarter = _quarter(seed)
    angle, clause, objective = pick((
        ("utilisation", f"the group limit utilisation for {who}'s group",
         "report utilisation against the eligible capital reference"),
        ("aggregate", f"the aggregate exposure of {who}'s group",
         "aggregate exposure at the group rather than the borrower"),
        ("breach", f"whether {who}'s group is over the limit",
         "name the threshold as an unverified regulatory parameter"),
        ("headroom", f"how much headroom {who}'s group has",
         "report headroom against the stated reference"),
        ("largest", "the groups with the highest limit utilisation",
         "rank groups by utilisation"),
        ("trigger", "the groups over the investigation trigger",
         "distinguish the trigger from the limit"),
    ), seed, 19)
    if pick((True, False), seed, 20):
        question = f"{pick(FORMAL, seed, 21)} {clause} as at {quarter}."
    else:
        question = f"{clause.capitalize()}? As at {quarter} please."
    return build(
        family="GRAPH_GROUP_LIMIT",
        title=f"group limit: {angle}",
        turns=[cn.Turn(question,
                       behaviour="Must aggregate at the group and must "
                                 "name the threshold as an UNVERIFIED "
                                 "REGULATORY PARAMETER carried from a "
                                 "framework document, not confirmed as "
                                 "currently binding law. A breach here is a "
                                 "candidate for assessment, not a "
                                 "regulatory finding.")],
        objectives=(objective,
                    f"state the {GROUP_LIMIT:g}% limit and the "
                    f"{TRIGGER:g}% investigation trigger as declared "
                    "parameters",
                    "state the as-at date"),
        difficulty=sc.EXPERT, risk="HIGH",
        required_datasets=[GROUPS_DATASET],
        metrics=["group_exposure", "group_utilisation_pct"],
        concepts=["group utilisation", "exposure"],
        analytical_plan_contract={"as_of_quarter": quarter,
                                  "grain": "connected_group"},
        result_contract={"shape": "group exposure and utilisation with the "
                                  "parameter named"},
        scope_contract=_caveat(
            "presenting the limit as currently binding law",
            "presenting a breach as a regulatory finding",
            "summing the group figure across its members", BLOCKED))


def _group_concepts(seed: str) -> sc.TeachingCase:
    """Six group concepts, and never a silent substitution."""
    concept = pick(CONCEPTS, seed, 22)
    other = pick(tuple(c for c in CONCEPTS if c["key"] != concept["key"]),
                 seed, 23)
    who = _subject(seed)
    quarter = _quarter(seed)
    shape = pick((
        (f"Which {concept['label'].lower()} is {who} in",
         f"answer for the {concept['label'].lower()} specifically"),
        (f"How does the {concept['label'].lower()} for {who} differ from "
         f"its {other['label'].lower()}",
         "state what each concept answers and where they diverge"),
        (f"Is the {concept['label'].lower()} the same thing as the "
         f"{other['label'].lower()}",
         "state that they are different concepts with different bases"),
        (f"Show me {who}'s {concept['label'].lower()} membership",
         f"list the members of the {concept['label'].lower()}"),
    ), seed, 24)
    question = f"{shape[0]} as at {quarter}?"
    return build(
        family="GRAPH_GROUP_CONCEPTS",
        title=f"group concept: {concept['key']}",
        turns=[cn.Turn(question,
                       behaviour="Must answer for the group concept that "
                                 "was asked about and must not substitute "
                                 "another. The six concepts answer six "
                                 "different questions and each carries its "
                                 "own 'is NOT' statement.")],
        objectives=(shape[1],
                    f"state what the {concept['label'].lower()} is NOT",
                    "keep the six concepts distinct"),
        difficulty=sc.EXPERT, risk="HIGH",
        required_datasets=[GROUPS_DATASET],
        metrics=[], concepts=["connected group", "control group"],
        analytical_plan_contract={"as_of_quarter": quarter,
                                  "group_concept": concept["key"]},
        result_contract={"shape": "one named group concept, answered as "
                                  "itself"},
        scope_contract=_caveat(
            f"answering with the {other['label'].lower()} instead",
            "merging two group concepts into one answer", BLOCKED))


# ---------------------------------------------------------------------------
# Network analytics
# ---------------------------------------------------------------------------


def _contagion(seed: str) -> sc.TeachingCase:
    """DebtRank as a fraction of network value, never as a loss."""
    who = _subject(seed)
    quarter = _quarter(seed)
    angle, clause, objective = pick((
        ("impact", f"the DebtRank impact of {who}",
         "report the fraction of network value impaired under the shock"),
        ("ranking", "the borrowers with the highest DebtRank impact",
         "rank borrowers by impact within the scored population"),
        ("shock", f"what shock the DebtRank figure for {who} assumes",
         "state the seed, the shock and the number of iterations"),
        ("not a loss", f"whether the DebtRank impact of {who} is a loss",
         "state that it is not an expected credit loss"),
        ("propagation", f"which borrowers {who}'s distress reaches",
         "name the borrowers reached and the path"),
        ("method", "how the DebtRank impact is computed",
         "state the weight rule and the propagate-once rule"),
    ), seed, 25)
    question = f"{pick(FORMAL, seed, 26)} {clause} as at {quarter}."
    return build(
        family="GRAPH_CONTAGION",
        title=f"contagion: {angle}",
        turns=[cn.Turn(question,
                       behaviour="Must report DebtRank as a fraction of "
                                 "network value impaired under a stated "
                                 "shock. Must state that it is NOT an "
                                 "expected credit loss, NOT a capital "
                                 "methodology and NOT a regulatory measure "
                                 "— it reads like a loss rate, which is "
                                 "why it must never be presented as one.")],
        objectives=(objective,
                    "state the shock, the seed and the iteration rule",
                    "state that DebtRank is not an ECL or a capital number"),
        difficulty=sc.EXPERT, risk="HIGH",
        required_datasets=[GROUPS_DATASET], metrics=["debtrank_impact"],
        concepts=["debtrank"],
        analytical_plan_contract={"as_of_quarter": quarter,
                                  "method": "debtrank"},
        result_contract={"shape": "an impact fraction with its shock stated"},
        scope_contract=_caveat(
            "presenting DebtRank as an expected credit loss",
            "presenting DebtRank as a capital or regulatory measure",
            "summing DebtRank impacts across borrowers", BLOCKED))


def _centrality(seed: str) -> sc.TeachingCase:
    """Who transmits, who is exposed, who is a conduit."""
    who = _subject(seed)
    quarter = _quarter(seed)
    angle, clause, objective = pick((
        ("transmitters", "the borrowers others are most exposed to",
         "use forward PageRank, which ranks transmitters"),
        ("exposed", "the borrowers most exposed to others",
         "use reverse PageRank, which ranks the exposed"),
        ("conduits", "the borrowers that sit between the others",
         "use betweenness, which ranks conduits"),
        ("direction", f"whether {who} transmits risk or receives it",
         "state which direction the measure reads"),
        ("difference", "how forward and reverse PageRank differ here",
         "state that they answer different questions"),
        ("position", f"how central {who} is in the exposure network",
         "name which centrality was used and what it means"),
    ), seed, 27)
    question = f"{pick(FORMAL, seed, 28)} {clause} as at {quarter}."
    return build(
        family="GRAPH_CENTRALITY",
        title=f"centrality: {angle}",
        turns=[cn.Turn(question,
                       behaviour="Must pick the centrality that answers the "
                                 "question asked and must say which one it "
                                 "picked. Forward and reverse PageRank "
                                 "answer opposite questions and the "
                                 "direction is the thing most easily got "
                                 "backwards.")],
        objectives=(objective,
                    "name the centrality used and the direction it reads",
                    "state that centrality is structural position, not size "
                    "or credit quality"),
        difficulty=sc.COMPLEX, risk="MEDIUM",
        required_datasets=[GROUPS_DATASET],
        metrics=["pagerank_transmits", "pagerank_hurt", "betweenness"],
        concepts=["centrality"],
        analytical_plan_contract={"as_of_quarter": quarter,
                                  "method": "centrality"},
        result_contract={"shape": "a ranking with the measure named"},
        scope_contract=_caveat(
            "reading forward PageRank as exposure to the borrower",
            "presenting centrality as a measure of credit quality",
            "summing PageRank over a subset as a quantity of risk", BLOCKED))


def _network_risk_score(seed: str) -> sc.TeachingCase:
    """A relative ranking, and nothing that sounds like a probability."""
    who = _subject(seed)
    quarter = _quarter(seed)
    angle, clause, objective = pick((
        ("score", f"the Network Risk Score for {who}",
         "report the score as a relative ranking in the scored population"),
        ("ranking", "the highest Network Risk Scores in the book",
         "rank borrowers within the scored population"),
        ("components", f"what makes up {who}'s Network Risk Score",
         "state the three components and their weights"),
        ("not a pd", f"whether {who}'s Network Risk Score is a probability",
         "state that it is not a probability, a PD, a rating, a stage or "
         "an ECL"),
        ("population", "what population the Network Risk Score ranks against",
         "state that the score carries no meaning outside its population"),
        ("moved", f"whether {who}'s Network Risk Score moved into {quarter}",
         "compare within the same scored population"),
    ), seed, 29)
    if pick((True, False), seed, 30):
        question = f"{pick(FORMAL, seed, 31)} {clause} as at {quarter}."
    else:
        question = f"{pick(DIRECT, seed, 32)} {clause} for {quarter}?"
    return build(
        family="GRAPH_NETWORK_RISK_SCORE",
        title=f"network risk score: {angle}",
        turns=[cn.Turn(question,
                       behaviour="Must carry the score's label: a RELATIVE "
                                 "NETWORK RANKING, NOT A PROBABILITY, NOT "
                                 "PD, NOT A RATING, NOT AN IFRS 9 STAGE, "
                                 "NOT ECL. Must state the population it "
                                 "ranks within.")],
        objectives=(objective,
                    "carry the score's governed label in full",
                    "name the population the ranking is relative to"),
        difficulty=sc.EXPERT, risk="HIGH",
        required_datasets=[GROUPS_DATASET], metrics=["network_risk_score"],
        concepts=["network risk score"],
        analytical_plan_contract={"as_of_quarter": quarter,
                                  "method": "network_risk_score"},
        result_contract={"shape": "a ranked score with its label"},
        scope_contract=_caveat(
            "presenting the score as a probability or a PD",
            "presenting the score as a rating or an IFRS 9 stage",
            "summing or averaging scores across borrowers", BLOCKED))


def _community(seed: str) -> sc.TeachingCase:
    """A modularity community, described as descriptive only."""
    who = _subject(seed)
    quarter = _quarter(seed)
    angle, clause, objective = pick((
        ("membership", f"which network community {who} falls in",
         "report the community label as descriptive only"),
        ("not a group", f"whether {who}'s community is a group",
         "state that a community is not a group in any legal, economic or "
         "regulatory sense"),
        ("label", "what a community label means between quarters",
         "state that the label is arbitrary and not stable across quarters"),
        ("size", "how large the network communities are",
         "report community sizes as a description of the network"),
        ("versus group", f"how {who}'s community differs from its connected "
         "group",
         "state that the two are found by different methods for different "
         "purposes"),
    ), seed, 33)
    question = f"{pick(FORMAL, seed, 34)} {clause} as at {quarter}."
    return build(
        family="GRAPH_COMMUNITY",
        title=f"community: {angle}",
        turns=[cn.Turn(question, result_type="NARRATIVE",
                       behaviour="Must describe the community as "
                                 "descriptive only. A community label is an "
                                 "arbitrary integer, stable between runs "
                                 "and meaningless between quarters, and it "
                                 "makes no claim about the borrowers in "
                                 "it.")],
        objectives=(objective,
                    "state that a community is not a legal, economic or "
                    "regulatory group",
                    "state that the label is arbitrary"),
        difficulty=sc.INTERMEDIATE, risk="MEDIUM",
        required_datasets=[GROUPS_DATASET], metrics=["louvain_community"],
        concepts=["network community"],
        analytical_plan_contract={"as_of_quarter": quarter,
                                  "method": "communities"},
        result_contract={"shape": "a community label with its caveat"},
        scope_contract=_caveat(
            "treating a community as a connected counterparty group",
            "comparing community labels across quarters",
            "averaging or summing community labels", BLOCKED))


def _similarity(seed: str) -> sc.TeachingCase:
    """A hidden relationship CANDIDATE, and never more than that."""
    who = _subject(seed)
    quarter = _quarter(seed)
    angle, clause, objective = pick((
        ("candidates", f"any hidden relationship candidates for {who}",
         "present each match as a candidate for investigation"),
        ("evidence", f"what evidence links {who} to its similarity matches",
         "name the shared evidence behind the match"),
        ("not a group", f"whether a similarity match puts {who} in a group",
         "state that a similarity match creates no group membership"),
        ("shared address", f"whether {who} shares an address with anybody",
         "report the shared attribute as evidence, not as a conclusion"),
        ("shared director",
         f"whether {who} shares a director with another borrower",
         "report the shared directorship as a candidate link"),
        ("strength", f"how strong the similarity evidence for {who} is",
         "report the overlap and what it does not establish"),
    ), seed, 35)
    question = f"{pick(FORMAL, seed, 36)} {clause} as at {quarter}."
    return build(
        family="GRAPH_SIMILARITY",
        title=f"hidden relationship: {angle}",
        turns=[cn.Turn(question,
                       behaviour="Must present the match as a HIDDEN "
                                 "RELATIONSHIP CANDIDATE for "
                                 "investigation, drawn distinctly from an "
                                 "asserted relationship. A similarity match "
                                 "may never on its own create control, "
                                 "beneficial ownership or group "
                                 "membership.")],
        objectives=(objective,
                    "label the match as a candidate for investigation",
                    "state what the match does not establish"),
        difficulty=sc.COMPLEX, risk="HIGH",
        required_datasets=[GROUPS_DATASET], metrics=[],
        concepts=["hidden relationship candidate"],
        analytical_plan_contract={"as_of_quarter": quarter,
                                  "method": "similarity"},
        result_contract={"shape": "candidate links with their shared "
                                  "evidence"},
        scope_contract=_caveat(
            "letting a similarity match create control or beneficial "
            "ownership",
            "adding a similarity match to a connected counterparty group",
            "presenting a candidate as an established relationship", BLOCKED))


# ---------------------------------------------------------------------------
# Evidence, quality and resolution
# ---------------------------------------------------------------------------


def _confidence(seed: str) -> sc.TeachingCase:
    """The weakest assertion on the path sets the confidence."""
    who = _subject(seed)
    quarter = _quarter(seed)
    angle, clause, objective = pick((
        ("weakest", f"how confident the derived relationships around {who} are",
         "report the confidence of the weakest assertion on the path"),
        ("which", f"which assertion sets the confidence for {who}'s chain",
         "name the assertion that set the floor"),
        ("not average", f"whether {who}'s confidence is an average",
         "state that it is the minimum, not the mean"),
        ("path", f"the evidence path behind {who}'s ownership conclusion",
         "list the assertions on the path with their confidences"),
        ("low", "the derived relationships with the lowest confidence",
         "rank by the weakest assertion on each path"),
    ), seed, 37)
    question = f"{pick(FORMAL, seed, 38)} {clause} as at {quarter}."
    return build(
        family="GRAPH_EVIDENCE_CONFIDENCE",
        title=f"evidence confidence: {angle}",
        turns=[cn.Turn(question,
                       behaviour="Must report the WEAKEST assertion on the "
                                 "evidence path and name it. Not the "
                                 "average, which lets a long chain of "
                                 "registry filings hide one relationship "
                                 "manager's note.")],
        objectives=(objective,
                    "name the assertion that set the confidence",
                    "state that the rule is the weakest link, not the mean"),
        difficulty=sc.COMPLEX, risk="MEDIUM",
        required_datasets=[GROUPS_DATASET], metrics=["graph_confidence"],
        concepts=["graph confidence"],
        analytical_plan_contract={"as_of_quarter": quarter,
                                  "rule": "WEAKEST_EVIDENCE_ON_PATH"},
        result_contract={"shape": "a confidence and the assertion that set "
                                  "it"},
        scope_contract=_caveat(
            "averaging confidences along the path",
            "reporting a confidence without naming its weakest assertion",
            BLOCKED))


def _data_quality(seed: str) -> sc.TeachingCase:
    """A check's status, and what it blocks."""
    check = pick(CHECK_NAMES, seed, 39)
    computation = pick(COMPUTATIONS, seed, 40)
    quarter = _quarter(seed)
    angle, clause, objective = pick((
        ("status", f"the status of the {check.replace('_', ' ')} check",
         "report the check's status and what it observed"),
        ("blocked", f"whether {computation.lower().replace('_', ' ')} is "
                    "blocked by a quality check",
         "name the check and the computation it blocks"),
        ("why", f"why {computation.lower().replace('_', ' ')} returned no "
                "figure",
         "state that a rejected check blocked the computation"),
        ("scope", f"how many entities the {check.replace('_', ' ')} check "
                  "affects",
         "distinguish an entity-scoped rejection from a portfolio one"),
        ("all", "the graph quality checks that are not passing",
         "list each failing check with its status and what it blocks"),
    ), seed, 41)
    question = f"{pick(FORMAL, seed, 42)} {clause} as at {quarter}."
    return build(
        family="GRAPH_DATA_QUALITY",
        title=f"graph quality: {angle}",
        turns=[cn.Turn(question,
                       behaviour="Must report the check's own status — "
                                 "PASS, FLAG or REJECT — and, where a "
                                 "computation is blocked, return "
                                 "DATA_QUALITY_BLOCKED rather than a "
                                 "number.")],
        objectives=(objective,
                    "state which computations the check blocks",
                    "return the blocked sentinel rather than a figure"),
        difficulty=sc.COMPLEX, risk="HIGH",
        required_datasets=[DQ_DATASET], metrics=[],
        concepts=["graph quality"],
        analytical_plan_contract={"as_of_quarter": quarter,
                                  "check": check,
                                  "computation": computation},
        result_contract={"shape": "check statuses and the computations they "
                                  "block"},
        scope_contract=_caveat(
            "returning a number for a blocked computation",
            "reporting a portfolio-wide flag as a per-borrower status",
            "silently downgrading a REJECT to a FLAG"))


def _entity_resolution(seed: str) -> sc.TeachingCase:
    """A resolution error propagates, and an ambiguous match is disclosed."""
    who = _subject(seed)
    sector = _sector(seed)
    angle, clause, objective = pick((
        ("ambiguous", f"whether the name I gave matches more than one "
                      f"borrower in {sector}",
         "disclose every candidate rather than resolving silently"),
        ("propagation", f"what happens downstream if {who} was resolved to "
                        "the wrong entity",
         "state that a resolution error propagates into every derived "
         "figure"),
        ("basis", f"how {who} was matched to its registry record",
         "name the attributes the match was made on"),
        ("alias", f"whether {who} trades under another name",
         "list the recorded aliases and which is authoritative"),
        ("merged", f"whether two records were merged into {who}",
         "state what was merged and on what evidence"),
    ), seed, 43)
    question = f"{pick(FORMAL, seed, 44)} {clause}."
    return build(
        family="GRAPH_ENTITY_RESOLUTION",
        title=f"entity resolution: {angle}",
        turns=[cn.Turn(question, result_type="NARRATIVE",
                       behaviour="Must disclose an ambiguous match rather "
                                 "than picking one, and must state that "
                                 "entity-resolution errors propagate into "
                                 "every derived figure downstream.")],
        objectives=(objective,
                    "disclose ambiguity rather than resolving it silently",
                    "state that resolution errors propagate downstream"),
        difficulty=sc.COMPLEX, risk="HIGH",
        required_datasets=[GROUPS_DATASET], metrics=[],
        concepts=["entity resolution"],
        analytical_plan_contract={"discloses_ambiguity": True},
        result_contract={"shape": "candidate entities and the match basis"},
        scope_contract=_caveat(
            "resolving an ambiguous name to one entity without saying so",
            "presenting a derived figure without its resolution caveat",
            BLOCKED))


# ---------------------------------------------------------------------------
# Ambiguity and controlled failure
# ---------------------------------------------------------------------------


def _ambiguity(seed: str) -> sc.TeachingCase:
    """Ask which one was meant, rather than computing confidently."""
    # Each entry is a DISTINCT thing the product must ask about, not a
    # rewording of one. A clarification case is defined by the question it
    # has to ask back, so two shapes that would ask the same thing are one
    # scenario however differently they are phrased.
    missing, question, asks = pick((
        ("group concept", "Show me the group.",
         "which of the six group concepts was meant"),
        ("as-at date", "What is the connected group exposure?",
         "which quarter to read the relationships as at"),
        ("centrality", "How central is this borrower?",
         "which centrality - transmitters, exposed, or conduits"),
        ("borrower", "Who owns them?",
         "which borrower the question is about"),
        ("measure", "Give me the network numbers.",
         "which network measure was wanted"),
        ("direction", "Who is exposed here?",
         "whether the question is about exposure to or exposure from"),
        ("threshold", "Who are the beneficial owners?",
         "whether the declared threshold or another one applies"),
        ("size meaning", "How big is the group?",
         "whether size means members or exposure"),
        ("owner kind", "List the owners of this borrower.",
         "whether natural persons only, or corporate holders as well"),
        ("ownership basis", "What is the stake here?",
         "whether the direct shareholding or the integrated stake is wanted"),
        ("group versus community", "Which cluster is this name in?",
         "whether the connected group or the network community is meant"),
        ("population", "Rank the borrowers by network risk.",
         "which population the ranking should be relative to"),
        ("candidate or asserted",
         "Show me everyone connected to this borrower.",
         "whether asserted relationships only, or hidden relationship "
         "candidates as well"),
        ("comparison base", "Has the group exposure moved?",
         "which two quarters to compare"),
        ("limit or trigger", "Which groups are over?",
         "whether over the limit or over the investigation trigger"),
        ("shock", "What is the contagion impact here?",
         "which shock the DebtRank propagation should assume"),
        ("guarantee direction", "What guarantees are attached to this name?",
         "whether guarantees given or guarantees received"),
        ("supply direction", "Who does this borrower trade with?",
         "whether suppliers or customers"),
        ("depth", "Show me the network around this borrower.",
         "how many degrees of separation to include"),
        ("confidence rule", "How reliable is this relationship?",
         "whether the weakest assertion or the mean confidence is wanted"),
        ("entity", "What is the ownership for Al Faisal?",
         "which of the borrowers matching that name is meant"),
        ("blocked or absent", "Why is there no UBO count here?",
         "whether the question is about a blocked computation or an absent "
         "owner"),
    ), seed, 45)
    return build(
        family="GRAPH_AMBIGUITY",
        title=f"ambiguous: {missing}",
        turns=[cn.Turn(question, action="CLARIFY", result_type="NARRATIVE",
                       behaviour=f"Must ask {asks} rather than picking one "
                                 "and computing confidently. A graph "
                                 "question answered against the wrong "
                                 "concept produces a number that looks "
                                 "right.")],
        objectives=(f"ask {asks}",
                    "name the options rather than asking an open question",
                    "run nothing until the ambiguity is resolved"),
        difficulty=sc.INTERMEDIATE, risk="MEDIUM", outcome=fam.CLARIFY,
        capability="CLARIFICATION", officer=1,
        required_datasets=[], metrics=[], concepts=["connected group"],
        analytical_plan_contract={"clarifies_before_running": True},
        clarification_contract={"asks": asks,
                                "names_the_options": True,
                                "runs_nothing_until_answered": True},
        result_contract={"shape": "a question naming the options"},
        scope_contract=cn._forbids(
            "picking one reading and computing on it",
            "asking an open question instead of naming the options",
            CONNECTIVITY))


def _controlled_failure(seed: str) -> sc.TeachingCase:
    """Refuse, and say what is missing."""
    # As with ambiguity, each entry is a distinct REASON the question cannot
    # be answered. Two questions refused for the same reason teach one thing.
    missing, question, says = pick((
        ("rejected component",
         "What is the effective ownership here? The register total check "
         "rejected this component.",
         "the ownership computation is blocked by a rejected check"),
        ("out of book",
         "What is the connected group for a counterparty we do not bank?",
         "the entity is outside the corporate book"),
        ("before coverage",
         "What did this group look like before the graph starts?",
         "the graph does not cover that date"),
        ("no evidence",
         "Who controls this borrower? There are no registry filings for it.",
         "no control evidence is recorded"),
        ("retail",
         "What is the connected group for this retail account?",
         "the graph covers the corporate book, not retail accounts"),
        ("forecast",
         "What will the group exposure be next quarter?",
         "the graph reports what was true as at a date, not a forecast"),
        ("no capital reference",
         "What is the group limit utilisation for a group with no capital "
         "reference recorded?",
         "utilisation cannot be computed without an eligible capital "
         "reference"),
        ("dependent computation",
         "What is the Network Risk Score here? DebtRank was blocked for this "
         "entity.",
         "the score depends on DebtRank, which a quality check blocked"),
        ("similarity as fact",
         "Add this similarity match to the borrower's connected group.",
         "a similarity match is a candidate and may not create group "
         "membership"),
        ("legal opinion",
         "Confirm that these two borrowers are legally connected under the "
         "regulation.",
         "CreditProbe reports graph connectivity and cannot make a "
         "regulatory determination"),
        ("no natural person",
         "Give me the beneficial owner's national identity number.",
         "the graph records natural persons as nodes and holds no identity "
         "document data"),
        ("unscored population",
         "What is the Network Risk Score for an entity that is not a "
         "borrower?",
         "only borrowers are in the scored population"),
        ("cross-quarter label",
         "Is this borrower in the same network community it was in last "
         "year?",
         "community labels are arbitrary and not comparable across "
         "quarters"),
        ("beyond depth",
         "Show me every borrower within ten degrees of this one.",
         "the traversal is bounded and cannot return that depth"),
        ("no guarantee",
         "What does the guarantee over this facility cover? No guarantee is "
         "recorded against it.",
         "no guarantee is recorded for that facility"),
        ("private individual",
         "Give me everything you hold on this director personally.",
         "the graph holds a director's role in the book and is not a "
         "personal dossier"),
    ), seed, 46)
    return build(
        family="GRAPH_CONTROLLED_FAILURE",
        title=f"refusal: {missing}",
        turns=[cn.Turn(question, result_type="NARRATIVE",
                       behaviour=f"Must refuse and say that {says}. Must "
                                 "not return a number, a zero, or an "
                                 "estimate in place of the answer it "
                                 "cannot give.")],
        objectives=(f"state that {says}",
                    "say what would be needed to answer",
                    "return no figure"),
        difficulty=sc.ADVERSARIAL, risk="HIGH", outcome=fam.UNSUPPORTED,
        officer=2, required_datasets=[], metrics=[],
        concepts=["graph quality"],
        analytical_plan_contract={"refuses": True},
        abstention_contract={"declines": question,
                             "because": says,
                             "returns_no_figure": True},
        result_contract={"shape": "a refusal naming what is missing"},
        scope_contract=cn._forbids(
            "returning zero in place of a figure that cannot be computed",
            "estimating a figure the data does not support",
            CONNECTIVITY, BLOCKED))


# ---------------------------------------------------------------------------
# The library
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Blueprint:
    """One family's reviewed shape and how many instances to build."""

    family: str
    count: int
    make: Callable[[str], sc.TeachingCase]


#: The distribution, as data. The counts are not uniform and are not
#: arbitrary: the families whose near-neighbour is most tempting — ownership
#: against control, DebtRank against loss, the score against a probability,
#: connectivity against connectedness — carry the most cases, because that is
#: where the errors actually are. Community and confidence carry fewer
#: because each has one honest answer and a limited number of ways of asking
#: for it.
BLUEPRINTS: tuple[Blueprint, ...] = (
    Blueprint("GRAPH_DATA_DISCOVERY", 30, _data_discovery),
    Blueprint("GRAPH_OWNERSHIP_STRUCTURE", 42, _ownership),
    Blueprint("GRAPH_BENEFICIAL_OWNERSHIP", 42, _beneficial_ownership),
    Blueprint("GRAPH_CONTROL_CLOSURE", 40, _control_closure),
    Blueprint("GRAPH_CONNECTED_GROUP", 42, _connected_group),
    Blueprint("GRAPH_GROUP_LIMIT", 36, _group_limit),
    Blueprint("GRAPH_GROUP_CONCEPTS", 40, _group_concepts),
    Blueprint("GRAPH_CONTAGION", 42, _contagion),
    Blueprint("GRAPH_CENTRALITY", 38, _centrality),
    Blueprint("GRAPH_NETWORK_RISK_SCORE", 40, _network_risk_score),
    Blueprint("GRAPH_COMMUNITY", 26, _community),
    Blueprint("GRAPH_SIMILARITY", 32, _similarity),
    Blueprint("GRAPH_EVIDENCE_CONFIDENCE", 26, _confidence),
    Blueprint("GRAPH_DATA_QUALITY", 38, _data_quality),
    Blueprint("GRAPH_ENTITY_RESOLUTION", 26, _entity_resolution),
    Blueprint("GRAPH_AMBIGUITY", 22, _ambiguity),
    Blueprint("GRAPH_CONTROLLED_FAILURE", 16, _controlled_failure),
)

#: B45's floor. Asserted rather than hoped for.
MINIMUM_DEVELOPMENT = 500

_ATTEMPTS = 16


def _finish(case: sc.TeachingCase, blueprint: Blueprint,
            index: int) -> sc.TeachingCase:
    case.family_id = blueprint.family
    case.source_provenance = (f"corporate_graph:{blueprint.family}:{index}"
                              f"@{GRAPH_VERSION}")
    case.tags = ["corporate-graph", blueprint.family.lower()]
    case.cluster_id = mg._cluster(case.question)
    case.description = (
        f"Relationship-graph case for {blueprint.family}: a reviewed shape "
        "instantiated over the governed corporate graph vocabulary.")
    case.industry_or_product_scope = "corporate lending"
    return mg.enrich(case)


def cases() -> list[sc.TeachingCase]:
    """Every graph development case, deterministically and distinctly.

    A blueprint keeps drawing until it has the distinct cases it asked for or
    its combination space runs out. A shortfall is reported by `report()`
    rather than padded, because a family that cannot reach its target needs
    more shapes — which is a decision for a person, not a number to inflate.
    """
    out: list[sc.TeachingCase] = []
    for blueprint in BLUEPRINTS:
        seen: set[str] = set()
        built: list[sc.TeachingCase] = []
        for attempt in range(blueprint.count * _ATTEMPTS):
            if len(built) >= blueprint.count:
                break
            case = _finish(blueprint.make(f"{blueprint.family}:{attempt}"),
                           blueprint, attempt)
            if case.fingerprint in seen:
                continue
            seen.add(case.fingerprint)
            case.case_id = (f"gr-{blueprint.family.lower().replace('_', '-')}"
                            f"-{len(built):03d}")
            built.append(case)
        out.extend(built)
    return out


def report() -> dict[str, Any]:
    """Counts per family, and any family that came up short."""
    built = cases()
    tally: dict[str, int] = {}
    for case in built:
        tally[case.family_id] = tally.get(case.family_id, 0) + 1
    short = {b.family: {"asked": b.count, "built": tally.get(b.family, 0)}
             for b in BLUEPRINTS if tally.get(b.family, 0) < b.count}
    return {
        "graph_version": GRAPH_VERSION,
        "total": len(built),
        "minimum": MINIMUM_DEVELOPMENT,
        "meets_minimum": len(built) >= MINIMUM_DEVELOPMENT,
        "families": len(BLUEPRINTS),
        "by_family": dict(sorted(tally.items())),
        "short": short,
        "difficulties": _tally(built, "difficulty"),
        "outcomes": _tally(built, "expected_outcome"),
        "vocabulary": {
            "quarters": len(QUARTERS),
            "edge_types": len(EDGES),
            "group_concepts": len(CONCEPTS),
            "quality_checks": len(CHECK_NAMES),
        },
    }


def _tally(built: list[sc.TeachingCase], attribute: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for case in built:
        key = str(getattr(case, attribute, "") or "")
        out[key] = out.get(key, 0) + 1
    return dict(sorted(out.items()))
