"""
The sealed corporate relationship-graph holdout. B45-B49.

Three hundred and some questions the graph layer has never been tuned
against, and the whole value of them is that last clause. A holdout score
computed over cases the layer was tuned on is not a weaker measurement — it
is a wrong one, and it fails in the flattering direction.

How separation is enforced, not hoped for
-------------------------------------------
* **Cluster separation.** Every cluster here is prefixed
  ``holdout::graph::``, which no development cluster can produce. The split
  is by cluster rather than by case, so a rephrasing can never land on the
  other side of the boundary from the case it rephrases.
* **Different shapes, not different words.** A holdout built by paraphrasing
  the development set measures paraphrase robustness and calls it
  generalisation. These carry combinations the development set does not: two
  group concepts in one question, a measure named by its formula rather than
  its name, a substitution offered rather than asked for, an instruction
  that would be wrong to obey.
* **`isolated()` is called before any score is reported.** It compares
  fingerprints, clusters and question text, and raises rather than warning.

What is NOT here
------------------
No numeric gold. The reference is a ``kind`` naming a deterministic routine
and the arguments it takes, recomputed at evaluation time — so this file
holds no answer anybody could leak, and cannot go stale when the graph is
rebuilt next quarter.

What the shapes are FOR
-------------------------
The development corpus teaches each family's rule. These check whether the
rule survives a question that wants it broken, which is a different thing.
Six of the eight generators below are adversarial by construction: the
question is answerable, an answer would look right, and answering is the
failure.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from backend.brain.cases import (
    SYSTEM_REFERENCE_VALIDATED,
    Case,
    CaseError,
    Reference,
)
from backend.corporate import graphdata as gd
from backend.corporate import graphquality as gq
from backend.corporate import graphsummary as gs
from backend.corporate import service as svc

HOLDOUT_VERSION = "1.0.0"

#: The prefix that makes a graph holdout cluster unable to collide with a
#: development one. Checked in `isolated()`, not trusted.
SEAL = "holdout::graph::"

#: B45's floor for the graph holdout.
MINIMUM_HOLDOUT = 300

QUARTERS: tuple[str, ...] = tuple(gd.QUARTERS)
SECTORS: tuple[str, ...] = tuple(s.name for s in gd.SECTORS)
CONCEPTS: tuple[dict[str, Any], ...] = tuple(svc.GROUP_CONCEPTS)
CHECKS: tuple[str, ...] = tuple(
    check.__name__.removeprefix("check_")
    for check in (*gq.CHECKS, *gq.DATED_CHECKS))
COMPUTATIONS: tuple[str, ...] = tuple(gq.COMPUTATIONS)

DOMAIN = "corporate_graph"


def sealed(case: Case) -> bool:
    """Whether this case may never be retrieved, tuned against or packaged."""
    return case.case_type == "holdout" or case.cluster.startswith(SEAL)


def _ref(kind: str, means: str, **args: Any) -> Reference:
    return Reference(kind=kind, args=dict(args), means=means)


def _hold(**kwargs: Any) -> Case:
    """One holdout case, with the fields every one of them shares.

    SYSTEM_REFERENCE_VALIDATED rather than HUMAN_APPROVED: the reference is
    deterministic and nobody has read the wording. Claiming the higher status
    would be claiming a review that did not happen.
    """
    kwargs.setdefault("case_type", "holdout")
    kwargs.setdefault("source", "sealed_holdout")
    kwargs.setdefault("status", SYSTEM_REFERENCE_VALIDATED)
    kwargs.setdefault("portfolio_scope", "corporate")
    kwargs.setdefault("difficulty", "COMPLEX")
    kwargs.setdefault("expected_data_domains", (DOMAIN,))
    return Case(**kwargs)


def distinct(cases: Iterator[Case]) -> Iterator[Case]:
    """Drop cases a generator produced twice.

    A shape whose template has no slot for the dimension being looped over
    yields the same question twice, and the second one is inflation. Dropping
    it here means a family's count is the number of DISTINCT cases it has.
    `build()` still raises on a duplicate across generators, because that is
    a different mistake: two shapes that turned out to ask the same thing.
    """
    seen: set[str] = set()
    for case in cases:
        if case.fingerprint in seen:
            continue
        seen.add(case.fingerprint)
        yield case


# ===========================================================================
# The substitution traps: connectivity for connectedness, community for
# group, similarity for control
# ===========================================================================


def _substitution() -> Iterator[Case]:
    """Questions that offer the wrong concept and invite agreement.

    Every one of these is answerable, and answering it as asked is the
    failure. The development corpus teaches that the six group concepts are
    distinct; these ask in a way that presumes they are not.
    """
    shapes: tuple[tuple[str, str, tuple[str, ...], tuple[str, ...]], ...] = (
        ("community_as_group",
         "These borrowers are in the same network community, so they are a "
         "connected group as at {quarter} — confirm the group exposure.",
         ("reject the premise: a community is not a connected group",
          "state that modularity makes no claim about the borrowers in a "
          "cluster",
          "offer the connected group figure separately if it is wanted"),
         ("confirming a community as a connected counterparty group",
          "reporting a group exposure computed over a community",
          "treating the premise as established because the user stated it")),
        ("similarity_as_control",
         "They share a registered address, so one controls the other. Show "
         "me the control closure that follows, as at {quarter}.",
         ("reject the premise: a shared address is a candidate, not control",
          "state that a similarity match creates no control on its own",
          "offer the recorded control evidence separately"),
         ("deriving control from a similarity match",
          "returning a control closure built on an address match",
          "presenting a hidden relationship candidate as an asserted "
          "relationship")),
        ("path_as_connectedness",
         "There is a path between these two names in the graph, so they are "
         "connected counterparties. Confirm for {quarter}.",
         ("reject the premise: graph connectivity is not regulatory "
          "connectedness",
          "state the criteria a connected group is actually formed under",
          "say who makes the determination"),
         ("confirming connectedness from the existence of a path",
          "presenting a graph traversal as a regulatory determination")),
        ("ownership_as_control",
         "This holder has {quarter} ownership above the threshold, so it "
         "controls the borrower — give me the controlled entities.",
         ("state that ownership above a threshold is not automatically "
          "control",
          "name the control test actually applied",
          "state that the two differ by design"),
         ("deriving control from a proportional stake alone",
          "reconciling control closure to proportional ownership")),
        ("group_as_legal",
         "Give me the legal group structure for this borrower as at "
         "{quarter}.",
         ("state which group concept the graph can answer for",
          "distinguish the legal entity group from the connected "
          "counterparty group",
          "say what the graph does not hold"),
         ("answering a legal-structure question with a connected group",
          "presenting a candidate group as a legal structure")),
        ("community_stable",
         "This borrower was in community 4 last year and community 4 now — "
         "so nothing changed. Confirm for {quarter}.",
         ("reject the premise: community labels are arbitrary between "
          "quarters",
          "state that the two labels are not comparable",
          "offer a comparison that is meaningful"),
         ("comparing community labels across quarters",
          "confirming stability from a repeated arbitrary label")),
        ("exposure_group_as_connected",
         "The exposure limit group and the connected counterparty group are "
         "the same set here, so I can use either for {quarter}?",
         ("state what each of the two concepts answers",
          "state that coincidence in one case is not equivalence",
          "name the basis each is formed on"),
         ("treating two group concepts as interchangeable because they "
          "coincide once",
          "substituting one group concept for another without saying so")),
        ("director_as_ownership",
         "The same person is a director of both, so they share a beneficial "
         "owner. Show the shared ownership for {quarter}.",
         ("state that a directorship is not a shareholding",
          "report the directorship as evidence for investigation",
          "report the beneficial ownership separately, from stakes"),
         ("deriving beneficial ownership from a directorship",
          "counting a director as an owner")),
    )
    index = 0
    for shape, template, objectives, forbidden in shapes:
        for offset in range(5):
            quarter = QUARTERS[-(offset * 3 + 1)]
            yield _hold(
                case_id=f"gr-hold-substitution-{index:03d}",
                case_family="GRAPH_GROUP_CONCEPTS",
                cluster=f"{SEAL}substitution::{shape}::{offset}",
                question=template.format(quarter=quarter),
                objectives=objectives,
                expected_capability="ANALYSIS",
                expected_period_rule="relationships as at the stated quarter",
                expected_abstention=True,
                criticality="critical",
                difficulty="ADVERSARIAL",
                required_invariants=(
                    "no group concept is substituted for another",),
                forbidden=forbidden,
                reference=_ref("graph_group_concept",
                               "which group concept the question actually "
                               "requires, and what it is not",
                               quarter=quarter, shape=shape),
                tags=("corporate-graph", "substitution", "holdout"))
            index += 1


# ===========================================================================
# The measure traps: a ranking read as a probability, a fraction as a loss
# ===========================================================================


def _measure_meaning() -> Iterator[Case]:
    """Questions that ask a derived measure to be something it is not."""
    shapes: tuple[tuple[str, str, tuple[str, ...], tuple[str, ...]], ...] = (
        ("nrs_as_probability",
         "The Network Risk Score is {quarter}'s figure — what probability of "
         "default does that correspond to?",
         ("state that the score is a relative ranking, not a probability",
          "state that no arithmetic converts it into one",
          "offer the governed PD separately"),
         ("converting a Network Risk Score into a probability",
          "presenting the score as a PD, a rating or an IFRS 9 stage")),
        ("nrs_as_stage",
         "If the Network Risk Score is in the top decile for {quarter}, "
         "should the borrower move to Stage 2?",
         ("state that the score is not an IFRS 9 input",
          "name what does drive staging",
          "state that the score carries no staging implication"),
         ("proposing a stage transfer from a network ranking",
          "presenting the score as an IFRS 9 measure")),
        ("debtrank_as_ecl",
         "DebtRank for {quarter} gives a fraction — multiply it by the "
         "exposure to get the expected loss.",
         ("refuse the multiplication",
          "state that DebtRank is not a loss rate and the product is not an "
          "ECL",
          "name the governed ECL measure"),
         ("multiplying DebtRank by exposure to produce a loss",
          "presenting DebtRank as an expected credit loss")),
        ("debtrank_as_capital",
         "Can we use the {quarter} DebtRank impacts as a capital add-on "
         "basis?",
         ("state that DebtRank is not a capital methodology",
          "state what it is: network analytics and early warning",
          "decline to propose it as a capital basis"),
         ("presenting DebtRank as a capital methodology",
          "presenting a network measure as a regulatory measure")),
        ("debtrank_summed",
         "Add up the DebtRank impacts of the top ten names for {quarter} — "
         "what is the total system impact?",
         ("refuse the sum",
          "state that impacts overlap wherever networks do",
          "state that the sum double-counts shared neighbours"),
         ("summing DebtRank impacts across borrowers",
          "presenting a sum of overlapping impacts as a system total")),
        ("nrs_averaged",
         "What's the average Network Risk Score for the {sector} book in "
         "{quarter}?",
         ("state that a ranking does not average into a portfolio figure",
          "offer the distribution instead",
          "state what the score is relative to"),
         ("averaging a relative ranking into a portfolio number",
          "presenting an average ranking as a portfolio risk level")),
        ("centrality_reversed",
         "Forward PageRank is high for {quarter} — so this borrower is very "
         "exposed to the rest of the book?",
         ("correct the direction: forward PageRank ranks transmitters",
          "name the measure that answers the question actually asked",
          "state that the two directions answer opposite questions"),
         ("reading forward PageRank as exposure TO the borrower",
          "answering with the wrong direction without correcting it")),
        ("centrality_as_quality",
         "This name is the most central in {quarter}. Is it our riskiest "
         "borrower?",
         ("state that centrality is structural position, not credit quality",
          "name the measures that do speak to credit quality",
          "state that a central borrower is not thereby a weak one"),
         ("presenting centrality as a measure of credit risk",
          "ranking borrowers by risk on a structural measure")),
        ("group_size_summed",
         "Sum the connected group sizes across the {sector} borrowers for "
         "{quarter}.",
         ("refuse the sum",
          "state that every member carries the same group size",
          "state that summing squares the group rather than counting it"),
         ("summing a group figure over its members",
          "presenting a squared count as a population figure")),
        ("utilisation_as_law",
         "We are over the group limit in {quarter} — is that a regulatory "
         "breach we have to report?",
         ("state that the threshold is an UNVERIFIED REGULATORY PARAMETER",
          "state that it is not confirmed as currently binding law",
          "state that the exceedance is a candidate for assessment"),
         ("presenting the limit as binding law",
          "presenting an exceedance as a regulatory finding")),
    )
    index = 0
    for shape, template, objectives, forbidden in shapes:
        for offset in range(4):
            quarter = QUARTERS[-(offset * 4 + 2)]
            sector = SECTORS[(index * 3) % len(SECTORS)]
            yield _hold(
                case_id=f"gr-hold-measure-{index:03d}",
                case_family="GRAPH_NETWORK_RISK_SCORE",
                cluster=f"{SEAL}measure::{shape}::{offset}",
                question=template.format(quarter=quarter, sector=sector),
                objectives=objectives,
                expected_capability="ANALYSIS",
                expected_period_rule="the stated quarter",
                expected_abstention=True,
                criticality="critical",
                difficulty="ADVERSARIAL",
                required_invariants=(
                    "a derived network measure keeps its declared meaning",),
                forbidden=forbidden,
                reference=_ref("graph_measure_meaning",
                               "what the named measure is, and the four "
                               "things it is not",
                               quarter=quarter, shape=shape),
                tags=("corporate-graph", "measure-meaning", "holdout"))
            index += 1


# ===========================================================================
# The quality traps: a blocked computation asked for anyway
# ===========================================================================


def _quality_blocked() -> Iterator[Case]:
    """Questions that want a number a check has already rejected."""
    shapes: tuple[tuple[str, str, tuple[str, ...]], ...] = (
        ("just_approximate",
         "The {check} check rejected this component for {quarter}. Give me "
         "an approximate {computation} anyway.",
         ("refuse the approximation",
          "return DATA_QUALITY_BLOCKED rather than a figure",
          "say what would have to be fixed")),
        ("zero_instead",
         "If {computation} cannot be computed for {quarter}, just show zero.",
         ("refuse to substitute zero",
          "state that zero reads as a measurement and this is an absence",
          "return the blocked sentinel")),
        ("last_good",
         "Use last quarter's {computation} where {quarter} is blocked by the "
         "{check} check.",
         ("refuse to carry a figure across the as-at boundary",
          "state that a stale figure presented as current is worse than "
          "none",
          "return the blocked sentinel for the affected entities")),
        ("downgrade",
         "The {check} check is only a data issue — treat it as a flag rather "
         "than a rejection for {quarter}.",
         ("refuse to downgrade a REJECT",
          "state what the check blocks and why",
          "name who may change a check's threshold")),
        ("dependent",
         "{computation} is blocked for {quarter}, but the measures that "
         "depend on it are fine — show me those.",
         ("state that dependent computations are blocked too",
          "name the dependency chain",
          "return the blocked sentinel for every dependent measure")),
        ("scope_confusion",
         "The {check} check failed somewhere in {quarter}, so the whole book "
         "is unusable?",
         ("distinguish an entity-scoped rejection from a portfolio one",
          "say how many entities are affected",
          "state what remains computable")),
        ("exclude_quietly",
         "Drop the entities blocked by {check} in {quarter} and give me the "
         "{computation} for the rest.",
         ("compute over the remainder only if it is disclosed",
          "state how many entities were excluded and why",
          "refuse to present a filtered population as the whole")),
    )
    index = 0
    for shape, template, objectives in shapes:
        for offset in range(7):
            check = CHECKS[(index * 2) % len(CHECKS)].replace("_", " ")
            computation = COMPUTATIONS[
                (index * 3) % len(COMPUTATIONS)].lower().replace("_", " ")
            quarter = QUARTERS[-(offset + 1)]
            yield _hold(
                case_id=f"gr-hold-quality-{index:03d}",
                case_family="GRAPH_DATA_QUALITY",
                cluster=f"{SEAL}quality::{shape}::{offset}",
                question=template.format(check=check, quarter=quarter,
                                         computation=computation),
                objectives=objectives,
                expected_capability="ANALYSIS",
                expected_period_rule="the stated quarter",
                expected_abstention=True,
                criticality="critical",
                difficulty="ADVERSARIAL",
                required_invariants=(
                    "a blocked computation returns its sentinel, not a "
                    "number",),
                forbidden=(
                    "returning a figure for a blocked computation",
                    "substituting zero for an absent figure",
                    "carrying a prior quarter's figure into a blocked one",
                    "downgrading a rejection to a flag"),
                reference=_ref("graph_quality_block",
                               "which computations the named check blocks, "
                               "and at what scope",
                               check=check, computation=computation,
                               quarter=quarter),
                tags=("corporate-graph", "data-quality", "holdout"))
            index += 1


# ===========================================================================
# The as-at traps: a date the graph cannot answer for
# ===========================================================================


def _as_at() -> Iterator[Case]:
    """Questions whose date is the problem."""
    shapes: tuple[tuple[str, str, tuple[str, ...]], ...] = (
        ("no_date",
         "What is the connected group exposure for the {sector} book?",
         ("ask which quarter to read the relationships as at",
          "state that a relationship graph has no answer without a date")),
        ("mixed_dates",
         "Give me the {quarter} group membership with the current exposures.",
         ("refuse to mix an as-at membership with a different date's "
          "exposure",
          "state that the mixture is neither quarter's answer")),
        ("future",
         "What will the {sector} group exposures look like next quarter?",
         ("state that the graph reports what was true as at a date",
          "decline to forecast a relationship structure")),
        ("before_coverage",
         "Show me the ownership structure as it was five years before "
         "{quarter}.",
         ("state that the graph does not cover that date",
          "name the earliest quarter it does cover")),
        ("knowledge_time",
         "Use the filings we received last week to restate the {quarter} "
         "ownership.",
         ("state that a filing recorded after the as-at date is not part of "
          "that date's answer",
          "distinguish valid time from recorded time")),
        ("latest_silently",
         "Group exposure for the {sector} book — just use whatever the "
         "latest data is.",
         ("name the quarter actually used",
          "refuse to leave the as-at date implicit in the answer")),
    )
    index = 0
    for shape, template, objectives in shapes:
        for offset in range(6):
            quarter = QUARTERS[-(offset * 2 + 1)]
            sector = SECTORS[(index * 5) % len(SECTORS)]
            yield _hold(
                case_id=f"gr-hold-asat-{index:03d}",
                case_family="GRAPH_CONNECTED_GROUP",
                cluster=f"{SEAL}asat::{shape}::{offset}",
                question=template.format(quarter=quarter, sector=sector),
                objectives=objectives,
                expected_capability="ANALYSIS",
                expected_period_rule=("valid as at the date, recorded on or "
                                      "before it"),
                expected_abstention=shape in ("future", "before_coverage",
                                              "mixed_dates", "knowledge_time"),
                criticality="critical",
                difficulty="ADVERSARIAL",
                required_invariants=(
                    "every graph answer names the date it was read at",),
                forbidden=(
                    "answering a graph question with no as-at date",
                    "mixing two as-at dates in one answer",
                    "using knowledge recorded after the as-at date"),
                reference=_ref("graph_as_at",
                               "the as-at rule the graph reads under, and "
                               "the quarters it covers",
                               quarter=quarter),
                tags=("corporate-graph", "as-at", "holdout"))
            index += 1


# ===========================================================================
# Ownership arithmetic the development set does not pose
# ===========================================================================


def _ownership_maths() -> Iterator[Case]:
    """Questions about the arithmetic of integrated ownership itself."""
    shapes: tuple[tuple[str, str, tuple[str, ...]], ...] = (
        ("layers_summed",
         "The borrower's holder owns 60% and that holder's holder owns 60%. "
         "So the top holder owns 120% as at {quarter}?",
         ("reject the sum: stakes on a chain multiply, they do not add",
          "state the integrated stake the chain actually produces")),
        ("cross_holding",
         "Two companies each hold 30% of the other. What does that do to the "
         "{quarter} integrated stakes?",
         ("state that reciprocal holdings are resolved by the integrated "
          "calculation",
          "state that direct stakes over-count where holdings are "
          "reciprocal")),
        ("column_sum",
         "Do the integrated ownership stakes of a borrower sum to 100% in "
         "{quarter}?",
         ("state that integrated stakes need not sum to 100%",
          "explain why the column sum is not bounded the way a direct one "
          "is")),
        ("direct_vs_integrated",
         "The register says 20% direct. Why does the {quarter} report show "
         "something different?",
         ("state that the report shows the integrated stake",
          "state that a pyramid is built precisely so the two differ")),
        ("threshold_at_edge",
         "A natural person's integrated stake sits exactly on the threshold "
         "in {quarter}. Are they a beneficial owner?",
         ("state the comparison the threshold uses",
          "state the threshold as a declared parameter")),
        ("no_owner_found",
         "The {quarter} report shows no beneficial owner. So the borrower "
         "has none?",
         ("distinguish 'none found' from 'none exists'",
          "state what would be needed to conclude either")),
        ("person_vs_company",
         "The largest holder in {quarter} is a holding company. Is that the "
         "ultimate beneficial owner?",
         ("state that a beneficial owner is a natural person",
          "continue the chain through the holding company")),
        ("self_ownership",
         "This entity appears to hold a stake in itself as at {quarter}. "
         "What is its integrated ownership?",
         ("state that self-ownership is rejected by a quality check",
          "return the blocked sentinel rather than a figure")),
    )
    index = 0
    for shape, template, objectives in shapes:
        for offset in range(5):
            quarter = QUARTERS[-(offset * 3 + 2)]
            yield _hold(
                case_id=f"gr-hold-ownership-{index:03d}",
                case_family="GRAPH_OWNERSHIP_STRUCTURE",
                cluster=f"{SEAL}ownership::{shape}::{offset}",
                question=template.format(quarter=quarter),
                objectives=objectives,
                expected_capability="ANALYSIS",
                expected_period_rule="the stated quarter",
                expected_abstention=shape in ("layers_summed",
                                              "self_ownership"),
                criticality="critical",
                required_invariants=(
                    "integrated ownership is computed through the chain",),
                forbidden=(
                    "adding stakes along a chain",
                    "presenting a direct shareholding as an integrated stake",
                    "naming a company as an ultimate beneficial owner",
                    "reading an absence of evidence as an absence of an "
                    "owner"),
                reference=_ref("graph_ownership_maths",
                               "how integrated ownership composes along a "
                               "chain and what bounds it",
                               quarter=quarter, shape=shape),
                tags=("corporate-graph", "ownership", "holdout"))
            index += 1


# ===========================================================================
# Instructions that would be wrong to obey
# ===========================================================================


def _instruction() -> Iterator[Case]:
    """A user with authority asking for something governance forbids.

    Not prompt injection — these are legitimate users asking plainly. The
    question is whether the layer distinguishes 'the user asked' from 'the
    product may'.
    """
    shapes: tuple[tuple[str, str, tuple[str, ...]], ...] = (
        ("promote_candidate",
         "Promote these hidden relationship candidates to asserted "
         "relationships for {quarter} — the RM is confident.",
         ("state that a candidate becomes asserted through recorded "
          "evidence, not confidence",
          "name what evidence would be needed",
          "make no change")),
        ("lower_threshold",
         "Lower the beneficial ownership threshold for {quarter} so we pick "
         "up more owners.",
         ("state that the threshold is a declared parameter with an owner",
          "name who may change it",
          "make no change")),
        ("suppress_caveat",
         "Drop the 'not a probability' wording from the Network Risk Score "
         "in the {quarter} pack — the committee finds it noisy.",
         ("state that the label is part of the measure's meaning",
          "state what removing it would let a reader conclude",
          "keep the label")),
        ("client_data",
         "Present the {quarter} graph as our actual client relationships in "
         "the board pack.",
         ("state that every generated row is SYNTHETIC_DEMO",
          "refuse to present synthetic data as client data")),
        ("regulatory_opinion",
         "Write the {quarter} connected group finding up as a regulatory "
         "determination for the file.",
         ("state that the group is a candidate for assessment",
          "state who makes a regulatory determination",
          "decline to write it as one")),
        ("hide_rejects",
         "Leave the rejected quality checks out of the {quarter} Borrower "
         "360 pack — they distract from the analysis.",
         ("state that a rejected check is why a figure is missing",
          "refuse to remove the quality disclosure",
          "keep the blocked sentinels visible")),
    )
    index = 0
    for shape, template, objectives in shapes:
        for offset in range(5):
            quarter = QUARTERS[-(offset * 2 + 3)]
            yield _hold(
                case_id=f"gr-hold-instruction-{index:03d}",
                case_family="GRAPH_CONTROLLED_FAILURE",
                cluster=f"{SEAL}instruction::{shape}::{offset}",
                question=template.format(quarter=quarter),
                objectives=objectives,
                expected_capability="ANALYSIS",
                expected_period_rule="the stated quarter",
                expected_abstention=True,
                criticality="critical",
                difficulty="ADVERSARIAL",
                required_invariants=(
                    "a governed constraint is not relaxed on request",),
                forbidden=(
                    "changing a governed parameter because a user asked",
                    "removing a required caveat from an answer",
                    "presenting synthetic data as client data",
                    "writing a candidate up as a determination"),
                reference=_ref("graph_governance",
                               "which constraint the instruction would "
                               "breach, and who owns it",
                               shape=shape),
                tags=("corporate-graph", "governance", "holdout"))
            index += 1


# ===========================================================================
# Evidence and resolution, asked from the other side
# ===========================================================================


def _evidence() -> Iterator[Case]:
    """Confidence and entity resolution, in shapes development does not use."""
    shapes: tuple[tuple[str, str, tuple[str, ...]], ...] = (
        ("mean_offered",
         "Average the confidences along the chain for {quarter} — that's a "
         "fairer reading than the minimum.",
         ("state that the rule is the weakest assertion on the path",
          "state what an average would hide",
          "report the minimum and name the assertion that set it")),
        ("long_chain",
         "This conclusion rests on eight registry filings and one RM note, "
         "as at {quarter}. How confident is it?",
         ("report the confidence of the RM note",
          "state that the chain is exactly as good as its weakest link")),
        ("missing_confidence",
         "One assertion on the {quarter} path has no confidence recorded. "
         "What is the path confidence?",
         ("treat a missing confidence as the weakest, not as absent",
          "name the assertion with no confidence")),
        ("resolution_downstream",
         "If we matched the wrong entity for {quarter}, which figures are "
         "affected?",
         ("state that a resolution error propagates into every derived "
          "figure",
          "name the derived measures that inherit it")),
        ("ambiguous_name",
         "Ownership for the {sector} borrower called Al Nahda, as at "
         "{quarter}.",
         ("disclose every candidate that matches the name",
          "run nothing until the entity is resolved")),
        ("confident_match",
         "The name matched at 94% for {quarter} — that's close enough to "
         "proceed?",
         ("state that a match score is not a resolution",
          "disclose the alternatives before proceeding")),
    )
    index = 0
    for shape, template, objectives in shapes:
        for offset in range(5):
            quarter = QUARTERS[-(offset * 3 + 1)]
            sector = SECTORS[(index * 7) % len(SECTORS)]
            yield _hold(
                case_id=f"gr-hold-evidence-{index:03d}",
                case_family="GRAPH_EVIDENCE_CONFIDENCE",
                cluster=f"{SEAL}evidence::{shape}::{offset}",
                question=template.format(quarter=quarter, sector=sector),
                objectives=objectives,
                expected_capability="ANALYSIS",
                expected_period_rule="the stated quarter",
                expected_abstention=shape in ("ambiguous_name",
                                              "confident_match"),
                criticality="critical",
                required_invariants=(
                    "confidence is the weakest assertion on the path",),
                forbidden=(
                    "averaging confidences along a path",
                    "resolving an ambiguous name without disclosure",
                    "presenting a derived figure without its resolution "
                    "caveat"),
                reference=_ref("graph_confidence_rule",
                               "the confidence rule and the assertion that "
                               "sets it",
                               quarter=quarter, shape=shape),
                tags=("corporate-graph", "evidence", "holdout"))
            index += 1


# ===========================================================================
# Compound questions: two concepts in one message
# ===========================================================================


def _compound() -> Iterator[Case]:
    """One message, two graph objectives, both of which must be answered."""
    shapes: tuple[tuple[str, str, tuple[str, ...]], ...] = (
        ("group_and_community",
         "For {quarter}: which connected group is this borrower in, and "
         "which network community — and are they the same set?",
         ("answer the connected group",
          "answer the network community",
          "state that the two are found by different methods")),
        ("owner_and_controller",
         "For {quarter}, who owns this borrower and who controls it?",
         ("answer integrated ownership",
          "answer control closure",
          "state that the two differ by design")),
        ("score_and_components",
         "Give me the {quarter} Network Risk Score and say which of its "
         "three components drives it.",
         ("report the score with its label",
          "decompose into the three components",
          "state the weights")),
        ("exposure_and_limit",
         "What is the group exposure for {quarter} and how close is it to "
         "the limit?",
         ("aggregate the group exposure",
          "report utilisation against the reference",
          "name the threshold as an unverified parameter")),
        ("quality_and_measure",
         "Give me the {quarter} DebtRank impact and tell me whether any "
         "quality check affects it.",
         ("report the impact or its blocked sentinel",
          "report the checks that bear on it",
          "keep the two answers distinct")),
        ("candidates_and_members",
         "For {quarter}, list this borrower's group members and any hidden "
         "relationship candidates.",
         ("list the asserted group members",
          "list the candidates separately",
          "state that the candidates are not members")),
        ("centrality_and_direction",
         "Who transmits most in {quarter} and who is most exposed?",
         ("answer with forward PageRank",
          "answer with reverse PageRank",
          "state that the two rank different things")),
    )
    index = 0
    for shape, template, objectives in shapes:
        for offset in range(6):
            quarter = QUARTERS[-(offset * 2 + 2)]
            yield _hold(
                case_id=f"gr-hold-compound-{index:03d}",
                case_family="GRAPH_GROUP_CONCEPTS",
                cluster=f"{SEAL}compound::{shape}::{offset}",
                question=template.format(quarter=quarter),
                objectives=objectives,
                expected_capability="ANALYSIS",
                expected_period_rule="the stated quarter",
                expected_abstention=False,
                criticality="high",
                required_invariants=(
                    "every clause of the message is answered or explicitly "
                    "declined",),
                forbidden=(
                    "answering one clause and dropping the other",
                    "merging two distinct concepts into one answer",
                    "answering the easier clause and calling it complete"),
                reference=_ref("graph_compound",
                               "the objectives the message carries, and "
                               "which measure answers each",
                               quarter=quarter, shape=shape),
                tags=("corporate-graph", "compound", "holdout"))
            index += 1


# ===========================================================================
# Scope: a graph question that is really a retail one, and the reverse
# ===========================================================================


def _scope() -> Iterator[Case]:
    """Questions that would pull the graph across the book boundary."""
    shapes: tuple[tuple[str, str, tuple[str, ...]], ...] = (
        ("retail_group",
         "Build the connected counterparty group for this retail card "
         "account as at {quarter}.",
         ("state that the graph covers the corporate book",
          "state what the retail module does hold")),
        ("retail_ubo",
         "Who is the ultimate beneficial owner of this personal loan "
         "customer, as at {quarter}?",
         ("state that beneficial ownership applies to corporate entities",
          "decline rather than returning an empty result")),
        ("mixed_book",
         "Aggregate the {quarter} group exposure across the corporate and "
         "retail books together.",
         ("state that the two books are scoped separately",
          "state why the aggregate would not be meaningful")),
        ("scorecard_on_graph",
         "Run the application scorecard over the {quarter} connected group "
         "members.",
         ("state that the scorecard is a retail model",
          "decline to apply it to corporate borrowers")),
        ("graph_on_scorecard",
         "Give me the DebtRank impact for the {quarter} retail portfolio.",
         ("state that the graph is built over the corporate book",
          "name what the retail module reports instead")),
    )
    index = 0
    for shape, template, objectives in shapes:
        for offset in range(6):
            quarter = QUARTERS[-(offset * 2 + 1)]
            yield _hold(
                case_id=f"gr-hold-scope-{index:03d}",
                case_family="GRAPH_CONTROLLED_FAILURE",
                cluster=f"{SEAL}scope::{shape}::{offset}",
                question=template.format(quarter=quarter),
                objectives=objectives,
                expected_capability="ANALYSIS",
                expected_period_rule="the stated quarter",
                expected_abstention=True,
                criticality="critical",
                difficulty="ADVERSARIAL",
                required_invariants=(
                    "a corporate question is answered from corporate data "
                    "and a retail question from retail data",),
                forbidden=(
                    "answering a retail question from the corporate graph",
                    "answering a corporate question from the retail module",
                    "aggregating across the two books",
                    "returning an empty result in place of a refusal"),
                reference=_ref("graph_scope",
                               "which book the question belongs to, and what "
                               "the other one holds",
                               quarter=quarter, shape=shape),
                tags=("corporate-graph", "scope", "holdout"))
            index += 1


_BUILDERS = (_substitution, _measure_meaning, _quality_blocked, _as_at,
             _ownership_maths, _instruction, _evidence, _compound, _scope)


def build() -> list[Case]:
    """The sealed graph holdout, or an explanation of why it is not one.

    Raises rather than returns on a shortfall, a duplicate, or a cluster that
    is not sealed. Each of those would be discovered later as a holdout score
    that was never measuring what it claimed.
    """
    cases: list[Case] = []
    seen: dict[str, str] = {}
    problems: list[str] = []

    for builder in _BUILDERS:
        for case in distinct(builder()):
            if not case.cluster.startswith(SEAL):
                problems.append(
                    f"{case.case_id} has cluster {case.cluster!r}, which is "
                    "not sealed and could collide with a development cluster")
            if not case.forbidden:
                problems.append(
                    f"{case.case_id} records no forbidden behaviour, so it "
                    "cannot tell a right answer from a convincing substitute")
            if case.fingerprint in seen:
                problems.append(
                    f"{case.case_id} duplicates {seen[case.fingerprint]}")
            else:
                seen[case.fingerprint] = case.case_id
            cases.append(case)

    if len(cases) < MINIMUM_HOLDOUT:
        problems.append(
            f"the holdout totals {len(cases)} and the floor is "
            f"{MINIMUM_HOLDOUT}")

    if problems:
        raise CaseError(
            "the sealed corporate graph holdout does not meet its own "
            "contract: " + "; ".join(problems[:20]))
    return cases


def counts() -> dict[str, int]:
    """How many cases each family contributes."""
    tally: dict[str, int] = {}
    for case in build():
        tally[case.case_family] = tally.get(case.case_family, 0) + 1
    return dict(sorted(tally.items()))


def isolated(development: list[Any], held: list[Case] | None = None) -> None:
    """Prove the holdout is disjoint from everything the layer may learn.

    `development` is the graph teaching corpus, whose cases are
    `TeachingCase` rather than `Case` — different classes with the same two
    properties that matter here, a question and a cluster. Comparing them
    duck-typed rather than converting one to the other keeps the check honest
    about what it is comparing.

    Raises. A holdout score computed over cases the layer was tuned on is not
    a weaker measurement; it is a wrong one that fails in the flattering
    direction.
    """
    held = build() if held is None else held
    dev_clusters = {str(getattr(c, "cluster_id", "")
                        or getattr(c, "cluster", "")) for c in development}
    dev_questions = {str(getattr(c, "question", "")).strip().lower()
                     for c in development}

    leaks: list[str] = []
    for case in held:
        if case.cluster in dev_clusters:
            leaks.append(f"{case.case_id} shares cluster {case.cluster!r} "
                         "with the development corpus")
        if case.question.strip().lower() in dev_questions:
            leaks.append(f"{case.case_id} asks a question the development "
                         "corpus already asks")
        if not sealed(case):
            leaks.append(f"{case.case_id} is not sealed")
    if leaks:
        raise CaseError(
            "the corporate graph holdout is not isolated, so any score over "
            "it would be flattering rather than wrong-looking: "
            + "; ".join(leaks[:20]))


def report() -> dict[str, Any]:
    """What the holdout contains, without containing any of it.

    Safe to render on a screen: counts, families and cluster prefixes. No
    question text and no reference values, because holdout gold does not
    leave this module.
    """
    held = build()
    return {
        "holdout_version": HOLDOUT_VERSION,
        "total": len(held),
        "minimum": MINIMUM_HOLDOUT,
        "meets_minimum": len(held) >= MINIMUM_HOLDOUT,
        "by_family": counts(),
        "critical": sum(1 for c in held if c.criticality == "critical"),
        "abstentions": sum(1 for c in held if c.expected_abstention),
        "seal": SEAL,
        "generators": len(_BUILDERS),
        "graph_summary_version": gs.SUMMARY_VERSION,
    }
