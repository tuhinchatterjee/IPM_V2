"""
What CreditProbe is, kept where it cannot drift away from what CreditProbe does.

The failure this exists to prevent
----------------------------------
    "What is CreditProbe AI?"

answered with

    "CreditProbe has no governed data about CreditProbe AI. It answers only
     from the datasets a steward has published…"

which is a correct statement about the borrower book and a completely wrong
answer to the question. A credit officer asking what the product is has not
asked a portfolio question, and routing them to the portfolio planner produces
the one response no product should ever give about itself.

Why this is a registry and not a paragraph
------------------------------------------
Prose about a product goes stale the day the product changes, and stale prose
is worse than none: it is a confident, specific, wrong answer. Each capability
here therefore carries two things — a curated NARRATIVE, which a person wrote
and reviewed, and an EVIDENCE function, which counts what the installation
actually has right now.

The narrative says what Borrower 360 is for. The evidence says how many
datasets the corporate book currently publishes. A test reconciles the two, so
a capability that is removed from the product fails the build rather than
living on in an answer.

What it is not
--------------
It is not a business-data domain. Nothing here is borrower data, nothing joins
to the credit book, and nothing reaches the analytical runtime. It is the
product describing itself, kept apart from the data the product analyses so
that neither can be mistaken for the other.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

KNOWLEDGE_VERSION = "1.0.0"

PRODUCT_NAME = "CreditProbe AI"

#: The one-sentence answer to "what is this", written for a credit audience and
#: deliberately free of superlatives. Everything downstream expands on it.
PURPOSE = (
    "CreditProbe is an AI-enabled credit-risk intelligence platform that brings "
    "portfolio, borrower, IFRS 9, ratings, Early Warning, covenants, "
    "collateral, liquidity, stress testing and governed analytics into one "
    "investigation environment.")

PROBLEM = (
    "A credit team's evidence is scattered by construction. The portfolio sits "
    "in a warehouse, impairment in an IFRS 9 engine, ratings in a rating "
    "system, covenants in spreadsheets and credit files, watchlists in a "
    "committee pack, and the macro view in somebody's inbox. Answering one "
    "ordinary question — why has this borrower deteriorated, and who else "
    "looks like it — means moving between all of them by hand and reconciling "
    "the answer afterwards. CreditProbe connects those views and lets an "
    "officer investigate conversationally, while every figure stays governed, "
    "reproducible and traceable to its source.")

#: The three responsibilities, kept separate because conflating them is how an
#: analytical product starts inventing figures. Read by `describe_ai_role`,
#: `describe_agentic_ai` and `describe_governed_engine`.
AI_LAYER = "ai_intelligence"
AGENTIC_LAYER = "agentic_investigation"
ENGINE_LAYER = "governed_engine"


@dataclass(frozen=True)
class Layer:
    """One of the three responsibilities, and what it owns."""

    key: str
    name: str
    owns: str
    does: tuple[str, ...]
    does_not: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"key": self.key, "name": self.name, "owns": self.owns,
                "does": list(self.does), "does_not": list(self.does_not)}


LAYERS: tuple[Layer, ...] = (
    Layer(
        key=AI_LAYER, name="AI intelligence layer",
        owns="understanding the question",
        does=(
            "Reads natural banking language — a question written the way a "
            "credit officer would say it out loud.",
            "Resolves conversational context, so a follow-up naming no "
            "population still means the population the thread is about.",
            "Decomposes a compound question into the analyses that answer it.",
            "Decides which governed evidence is worth retrieving.",
            "Identifies evidence that conflicts, and says so rather than "
            "picking a side.",
            "Forms an analytical hypothesis, labelled as a hypothesis.",
            "Explains a result in credit language, and proposes the follow-up "
            "questions the result raises.",
        ),
        does_not=(
            "It does not compute figures.",
            "It does not decide what the data means without the engine's "
            "answer in front of it.",
        )),
    Layer(
        key=AGENTIC_LAYER, name="Agentic investigation layer",
        owns="running the investigation",
        does=(
            "Plans a multi-step investigation and executes it as a bounded "
            "task graph rather than an open-ended loop.",
            "Works only through governed tools — it cannot write its own "
            "query, reach the network or open a file.",
            "Retrieves evidence across domains: portfolio, IFRS 9, ratings, "
            "covenants, collateral, liquidity and the connected group.",
            "Continues investigating when the evidence so far is not enough, "
            "within a declared budget of steps and calls.",
            "Preserves the population and the period across turns.",
            "Investigates an Early Warning case and recommends the next "
            "action for a person to approve.",
        ),
        does_not=(
            "It does not act outside its declared autonomy level.",
            "It does not inherit permissions a user does not have.",
        )),
    Layer(
        key=ENGINE_LAYER, name="Governed CreditProbe engine",
        owns="factual truth",
        does=(
            "Executes every calculation, and owns the result.",
            "Joins governed datasets over declared relationships, at declared "
            "cardinality and grain.",
            "Applies the bank's rating, IFRS 9, covenant and collateral "
            "definitions as configured, not as inferred.",
            "Enforces permissions on every read.",
            "Validates the answer against the question's own invariants "
            "before it is shown.",
            "Writes the Trace: which datasets, which joins, which filters, "
            "which arithmetic, in order.",
            "Guarantees reproducibility — the same question on the same data "
            "returns the same figures.",
        ),
        does_not=(
            "It does not let the AI layer invent, estimate or round a figure.",
            "It does not answer from anything a steward has not published.",
        )),
)

WHY_THE_SPLIT = (
    "The split is the point. Language models are flexible and are not "
    "reproducible; a credit calculation must be reproducible and does not need "
    "to be flexible. Giving the reasoning to one and the arithmetic to the "
    "other means an officer gets a system that understands the question and "
    "still cannot get the number wrong — and an auditor gets a Trace that does "
    "not depend on what a model happened to say that day.")


# =========================================================== the capabilities


@dataclass(frozen=True)
class Capability:
    """One thing the product does, and the live evidence that it does it."""

    key: str
    name: str
    #: One line. What it is.
    summary: str
    #: What it does, in two or three sentences.
    does: str
    #: Why a credit-risk function cares. This is the sentence that separates a
    #: feature list from a product explanation.
    matters: str
    #: How a risk team actually uses it, in the order they would.
    used_by: str
    #: The feature-matrix areas that prove this capability exists. Empty where
    #: the capability is proven by a registry instead — see `evidence`.
    areas: tuple[str, ...] = ()
    #: Governed data domains this capability reads.
    domains: tuple[str, ...] = ()
    #: A callable returning live counts. Never cached at import: the answer has
    #: to describe the installation as it is now.
    evidence: Callable[[], dict[str, Any]] | None = None

    def facts(self) -> dict[str, Any]:
        if self.evidence is None:
            return {}
        try:
            return dict(self.evidence())
        except Exception as exc:  # noqa: BLE001 - a count must not lose an answer
            logger.warning("Could not read evidence for %s: %s", self.key, exc)
            return {}

    def to_dict(self, *, with_evidence: bool = True) -> dict[str, Any]:
        out: dict[str, Any] = {
            "key": self.key, "name": self.name, "summary": self.summary,
            "does": self.does, "matters": self.matters,
            "used_by": self.used_by, "areas": list(self.areas),
            "domains": list(self.domains),
        }
        if with_evidence:
            out["evidence"] = self.facts()
        return out


# ---- evidence readers -------------------------------------------------------
#
# Each one asks the live installation a question. They return {} rather than
# raising: a capability whose counter is unavailable is still a capability, and
# an answer that fell over because a count could not be read would be a worse
# failure than an answer without the count.


def _datasets_in(*headings: str) -> Callable[[], dict[str, Any]]:
    def read() -> dict[str, Any]:
        from backend.metadata import service as md

        wanted = {h.lower() for h in headings}
        found = [d for d in md.domains() if d.name.lower() in wanted]
        return {"domains": len(found),
                "datasets": sum(int(getattr(d, "dataset_count", 0) or 0)
                                for d in found),
                "domain_names": [d.name for d in found]}
    return read


def _every_domain() -> dict[str, Any]:
    from backend.metadata import service as md

    found = list(md.domains())
    return {"domains": len(found),
            "datasets": sum(int(getattr(d, "dataset_count", 0) or 0)
                            for d in found),
            "domain_names": [d.name for d in found]}


def _early_warning() -> dict[str, Any]:
    from backend.early_warning import taxonomy as tx

    described = tx.describe()
    return {"signals": int(described.get("signal_count") or 0),
            "families": len(described.get("families") or {}),
            "severities": list(described.get("severities") or []),
            "taxonomy_version": described.get("version", "")}


def _relationship_graph() -> dict[str, Any]:
    from backend.orchestration import context as gc

    return {"governed_relationships": len(gc.all_relationships())}


def _methods() -> dict[str, Any]:
    from backend.orchestration import context as gc

    return {"certified_methods": len(gc.all_methods())}


def _tools() -> dict[str, Any]:
    from backend.analyst import tools as analyst_tools

    listed = getattr(analyst_tools, "TOOLS", None) or getattr(
        analyst_tools, "REGISTRY", None) or ()
    return {"governed_tools": len(listed)}


def _scorecards() -> dict[str, Any]:
    from backend.scorecard import registry as sc

    models = getattr(sc, "MODELS", None) or getattr(sc, "REGISTRY", None) or ()
    return {"registered_models": len(models)}


def _features_in(*areas: str) -> Callable[[], dict[str, Any]]:
    def read() -> dict[str, Any]:
        from backend.proof import matrix

        wanted = {a.lower() for a in areas}
        found = [f for f in matrix.FEATURES if f.area.lower() in wanted]
        return {"delivered_features": len(found)}
    return read


CAPABILITIES: tuple[Capability, ...] = (
    Capability(
        key="portfolio_intelligence",
        name="Corporate portfolio intelligence",
        summary="The whole corporate book, queryable in one place.",
        does="Holds the facility position, exposure, limits, utilisation, "
             "internal grade and stage for every facility and every reporting "
             "period, and lets a question cut it by sector, region, segment, "
             "rating band or any governed dimension.",
        matters="Portfolio questions are usually answered by whoever can build "
                "the extract fastest, which means the answer depends on who "
                "was asked. One governed book means one answer.",
        used_by="A portfolio manager opens with the shape of the book, "
                "narrows to the segment that moved, and drills to the "
                "borrowers behind the movement without leaving the thread.",
        areas=("Cockpit", "Analyses"),
        domains=("Core Portfolio / Facility",),
        evidence=_datasets_in("Core Portfolio / Facility")),
    Capability(
        key="borrower360",
        name="Borrower 360",
        summary="Everything known about one borrower, on one screen.",
        does="Assembles the borrower's exposure, ratings history, IFRS 9 "
             "position, covenants, collateral, liquidity, delinquency and its "
             "place in the connected group — including an interactive "
             "relationship graph showing ownership, guarantees and control.",
        matters="A credit officer preparing a review or defending a grade "
                "needs the whole picture, and assembling it by hand is where "
                "the hours go and where things get missed. Group risk in "
                "particular is invisible until somebody draws the structure.",
        used_by="Before a committee, an officer opens the borrower, reads the "
                "deterioration story, expands the group to see who else is "
                "exposed, and exports the pack.",
        areas=("Cockpit",),
        domains=("Core Portfolio / Facility", "Corporate Ratings"),
        evidence=_relationship_graph),
    Capability(
        key="early_warning",
        name="Early Warning",
        summary="Deterioration found before it reaches the accounts.",
        does="Runs a governed catalogue of signals across borrower "
             "fundamentals, facility behaviour, credit quality and the "
             "external picture; grades each by severity; tracks whether it is "
             "new, persistent, worsening or resolved; and promotes what "
             "matters into a Risk Case with an owner.",
        matters="By the time a borrower is Stage 3 the loss is largely "
                "decided. The value of an early-warning framework is entirely "
                "in the months before that, and only if the signals are "
                "specific enough to act on and governed enough to defend.",
        used_by="A risk officer works the Requires Attention list, opens a "
                "case, reads the evidence behind each warning, and either "
                "acts or records why not.",
        areas=("Cockpit", "Agents"),
        domains=("Core Portfolio / Facility", "IFRS 9 / ECL"),
        evidence=_early_warning),
    Capability(
        key="ifrs9",
        name="IFRS 9 and ECL intelligence",
        summary="The impairment position, and what moved it.",
        does="Reads staging, 12-month and lifetime PD, LGD, EAD, ECL and "
             "coverage, tracks stage migration and SICR triggers, and "
             "distinguishes the BOOKED accounting position from a predictive "
             "signal. It also DECOMPOSES the provision: a bridge from a flat "
             "through-the-cycle baseline through the rating distribution, the "
             "point-in-time and forward-looking view, IFRS 9 staging, "
             "collateral and loss given default, and the management overlay, "
             "each step re-measuring every facility and the last step "
             "reconciling to the reported figure.",
        matters="Impairment is where credit risk becomes a number in the "
                "accounts, and the movement between two dates is the question "
                "the audit committee actually asks.",
        used_by="An IFRS 9 owner reconciles the quarter's ECL movement, "
                "identifies the borrowers driving it, and checks which "
                "migrations were rating-driven rather than model-driven. "
                "Asked for an ECL decomposition, the same owner gets the "
                "build-up of the provision rather than its total, with each "
                "step's contribution traceable to the borrowers behind it.",
        areas=("Analyses",),
        domains=("IFRS 9 / ECL",),
        evidence=_datasets_in("IFRS 9 / ECL")),
    Capability(
        key="ratings",
        name="Corporate ratings and migration",
        summary="Where the internal grade has been, and where it is going.",
        does="Holds the annual rating cycle, prior grade and notches moved, "
             "supports migration analysis between any two dates, and applies "
             "the governed ordinal scale so a downgrade is a downgrade "
             "whichever way the scale is numbered.",
        matters="Rating migration is the cleanest single indicator of credit "
                "direction, and it is the one most often compared "
                "incorrectly — alphabetically, or across scales.",
        used_by="A credit committee reviews the quarter's downgrades, "
                "separates the ones already reflected in staging from the "
                "ones that are not.",
        areas=("Analyses",),
        domains=("Corporate Ratings",),
        evidence=_datasets_in("Corporate Ratings")),
    Capability(
        key="covenants",
        name="Covenant intelligence",
        summary="Which covenants are tested, breached, waived or close.",
        does="Tracks each covenant test per facility per period — headroom, "
             "threshold, actual, breach and waiver — and rolls it to the "
             "borrower without multiplying the book.",
        matters="A covenant breach is a contractual right the bank can only "
                "use if it knows about it in time, and headroom trending "
                "toward zero is a warning nobody sees in a total.",
        used_by="A relationship manager checks headroom before a drawdown "
                "request; a risk officer reviews breaches and waivers "
                "granted across the book.",
        areas=("Analyses",),
        domains=("Core Portfolio / Facility",)),
    Capability(
        key="collateral",
        name="Collateral intelligence",
        summary="What secures the exposure, and what it is worth.",
        does="Holds collateral by item and type with market and net "
             "realisable value, the governed haircut between them, and the "
             "valuation date.",
        matters="Recovery assumptions rest on collateral that is often valued "
                "years out of date, and the gap between market value and net "
                "realisable value is where an LGD assumption quietly fails.",
        used_by="A workout team reads what is actually available before "
                "assuming a recovery rate.",
        areas=("Analyses",),
        domains=("Core Portfolio / Facility",)),
    Capability(
        key="liquidity",
        name="Liquidity and cash-flow intelligence",
        summary="Whether the borrower can meet what falls due.",
        does="Holds cash, undrawn committed lines, debt service due and the "
             "months of cover they imply, per borrower per period.",
        matters="Most corporate defaults are liquidity events before they are "
                "solvency events. A borrower with a strong balance sheet and "
                "two months of cover is a different risk from one with the "
                "same leverage and twelve.",
        used_by="An officer investigating deterioration checks whether the "
                "problem is working capital or the capital structure.",
        areas=("Analyses",),
        domains=("Liquidity and Cash Flow",),
        evidence=_datasets_in("Liquidity and Cash Flow")),
    Capability(
        key="group_risk",
        name="Connected counterparty and group risk",
        summary="Who else the bank is exposed to through this name.",
        does="Resolves the corporate group from ownership, guarantee and "
             "control relationships; walks it upstream, downstream and "
             "laterally; distinguishes control from economic interest; and "
             "totals group exposure.",
        matters="Single-name limits mean little when four names share a "
                "parent, and a guarantee from a stressed guarantor is not "
                "the protection the file says it is.",
        used_by="Before approving a limit increase, an officer checks the "
                "group's total exposure rather than the borrower's.",
        areas=("Cockpit",),
        domains=("Core Portfolio / Facility",),
        evidence=_relationship_graph),
    Capability(
        key="external_intelligence",
        name="External and macro intelligence",
        summary="What is happening outside the book that reaches into it.",
        does="Holds macro series, sector conditions and governed external "
             "events, and links an event to the sectors and borrowers it "
             "plausibly touches — labelled as an analytical hypothesis, never "
             "as an observed fact about a borrower.",
        matters="Sector and macro pressure transmits into fundamentals months "
                "before it shows in a rating, and the link between an "
                "external event and a specific borrower is exactly where an "
                "analytical product is most tempted to overclaim.",
        used_by="An officer investigating a sector's deterioration sees which "
                "external conditions are live and how firmly they are "
                "connected.",
        areas=("Analyses",),
        domains=("External Intelligence",),
        evidence=_datasets_in("External Intelligence")),
    Capability(
        key="stress_testing",
        name="Stress testing",
        summary="What the book looks like under a scenario.",
        does="Applies governed scenarios to the portfolio and reports the "
             "movement in exposure, staging and impairment, with the scenario "
             "definition attached to the result.",
        matters="A stress result nobody can reproduce is a slide, not a "
                "control. Keeping the scenario governed is what makes the "
                "number defensible to a regulator.",
        used_by="A risk function runs the annual scenarios and explains the "
                "impairment impact by sector.",
        areas=("Analyses",)),
    Capability(
        key="scorecard_validation",
        name="Scorecard validation and model risk",
        summary="Whether the bank's models still work.",
        does="Holds registered scorecards with their equations, runs "
             "discrimination and calibration tests, applies the validation "
             "policy's limits, records findings and issues a validation "
             "opinion with an evidence pack.",
        matters="Model validation is a regulatory obligation with a deadline, "
                "and most of the work is assembling evidence rather than "
                "forming the opinion.",
        used_by="A model validator runs the suite, reviews the findings "
                "against policy, and exports the report.",
        areas=("Analyses",),
        domains=("Retail / SME Scorecards",),
        evidence=_scorecards),
    Capability(
        key="data_builder",
        name="Data Builder",
        summary="The governed data control plane.",
        does="Publishes datasets into business domains, declares the "
             "relationships between them with cardinality and temporal rule, "
             "marks which source is authoritative for a concept, tracks "
             "lineage and drift, and archives what is retired.",
        matters="Every answer downstream is only as good as the definitions "
                "here. Making them explicit, versioned and owned is what "
                "turns an analytics tool into a governed one.",
        used_by="A data steward publishes the quarter, declares the joins, "
                "and marks the authoritative source where two systems "
                "disagree.",
        areas=("Data Builder",),
        evidence=_every_domain),
    Capability(
        key="analysis_studio",
        name="Analysis Studio",
        summary="Bank-authored analytical methods, certified and reusable.",
        does="Lets an analyst compose a method over governed datasets, "
             "validate it against the catalogue, certify it, and then reuse "
             "it from the Cockpit or an investigation like any built-in "
             "analysis.",
        matters="Every bank has calculations that are its own. Without a "
                "place to put them they live in spreadsheets, and the "
                "spreadsheet becomes the system of record.",
        used_by="An analyst builds the bank's own coverage measure once, and "
                "everybody else asks for it by name.",
        areas=("Analysis Studio",),
        evidence=_methods),
    Capability(
        key="workflow",
        name="Workflow and Risk Cases",
        summary="From a finding to somebody's queue.",
        does="Turns a material finding into a Risk Case with an owner, "
             "status, due date and deterministic severity; carries comments, "
             "notifications and an action history; and holds the case open "
             "until it is resolved or explicitly dismissed with a reason.",
        matters="Analysis that ends in a screen changes nothing. The value is "
                "in what somebody does next, and in being able to show later "
                "that they did it.",
        used_by="A team lead assigns the quarter's cases, and the audit trail "
                "shows what was decided and why.",
        areas=("Workflow", "Projects")),
    Capability(
        key="trace",
        name="Trace and lineage",
        summary="Exactly how the number was produced.",
        does="Records every step behind an answer — datasets read, periods "
             "used, relationships traversed, grain reconciliations, filters "
             "applied, arithmetic performed, invariants checked — as an "
             "inspectable graph, with the plan fingerprint that makes the run "
             "reproducible.",
        matters="A credit number that cannot be defended is a liability. "
                "Trace is what lets an officer disagree with an answer "
                "specifically rather than distrust the tool generally.",
        used_by="A reviewer who doubts a figure opens the Trace, finds the "
                "join or filter they disagree with, and says so.",
        areas=("Trace", "Assurance"),
        evidence=_relationship_graph),
    Capability(
        key="ask",
        name="Ask CreditProbe",
        summary="The conversational investigation surface.",
        does="Takes a question in ordinary credit language, resolves it "
             "against governed concepts, plans an analysis, runs it on the "
             "engine, checks the answer against the question, and keeps the "
             "population and period across the turns that follow.",
        matters="The gap between having the data and answering the question "
                "is where most analytical platforms lose their users. A "
                "conversation that remembers what it is about closes it.",
        used_by="An officer starts broad, narrows twice, and drills into a "
                "single borrower — four questions, one thread, one "
                "population.",
        areas=("Conversations", "Analyses"),
        evidence=_tools),
    Capability(
        key="ai_governance",
        name="AI intelligence and learning governance",
        summary="The AI itself, under control.",
        does="Routes each question to an appropriate model tier, records what "
             "each answer cost to produce, captures feedback, "
             "governs what the system is allowed to learn from it, and "
             "publishes learning as a versioned release rather than as "
             "silent drift.",
        matters="An AI feature that changes behaviour without a version is "
                "not auditable, and a model that answers a credit question "
                "on Tuesday differently from Monday cannot be relied on.",
        used_by="A head of risk analytics reviews what the system learned "
                "this cycle before approving the release.",
        areas=("Learning", "Feedback", "Teaching corpus", "Live verification")),
)

CAPABILITY_BY_KEY: dict[str, Capability] = {c.key: c for c in CAPABILITIES}


#: How CreditProbe differs from a reporting tool. Grounded claims only: every
#: one of these is a thing the product does that a dashboard structurally
#: cannot, rather than a thing it does better.
DIFFERENTIATORS: tuple[tuple[str, str], ...] = (
    ("Cross-domain investigation",
     "One question can span the portfolio, IFRS 9, ratings, covenants, "
     "collateral, liquidity and the connected group. A dashboard shows one "
     "prepared view at a time; the join between them is left to the reader."),
    ("Reasoning over governed evidence",
     "The AI decides what to investigate. The engine decides what is true. "
     "Neither does the other's job, so an answer is both flexible and "
     "reproducible."),
    ("Deterministic computation",
     "Every figure is computed by the governed engine from published data. "
     "The language layer is never permitted to produce a number."),
    ("Traceability",
     "Every answer carries the datasets, joins, filters and arithmetic behind "
     "it, and the plan fingerprint that reproduces it."),
    ("Multi-turn investigation",
     "The population and period a question settles are carried into the "
     "questions that follow, so a thread is one investigation rather than "
     "several unrelated queries."),
    ("Portfolio-to-borrower continuity",
     "The same thread moves from the book to a sector to a borrower to a "
     "facility to the evidence, without changing tool or losing context."),
    ("Governed definitions",
     "Which dataset is authoritative for a concept, how two tables join, at "
     "what cardinality and under what temporal rule are declared, versioned "
     "and owned rather than embedded in a query."),
    ("Agentic workflow",
     "An investigation can run as a bounded multi-step task graph, under a "
     "declared autonomy level and an approval gate, and end in a Risk Case "
     "somebody owns."),
    ("It can explain why",
     "An answer is accompanied by the reading behind it — what the figures "
     "suggest, what else would explain them, and what evidence would settle "
     "it — labelled as interpretation rather than as fact."),
)

#: The product story as a flow, for the questions that ask what makes it
#: worth having. Rendered as text, never as a chart.
VALUE_FLOW: tuple[str, ...] = (
    "Data",
    "Governed credit concepts",
    "AI-led investigation",
    "Deterministic analytics",
    "Risk insight",
    "Trace",
    "Action / workflow",
)

CONTINUUM: tuple[str, ...] = (
    "Portfolio", "Sector", "Borrower", "Facility", "Evidence", "Action")


# ================================================== how the product introduces
#
# The registry above is what CreditProbe KNOWS. What follows is how it SPEAKS —
# the material an executive introduction is composed from, written for a Chief
# Risk Officer rather than for a release note.
#
# It is here rather than in the composer for the same reason the capability
# narrative is: the words a product uses about itself are owned, reviewed and
# versioned, not generated. The composer decides which of them a given question
# needs; it never writes new ones.

#: First person, used where the user is addressing CreditProbe itself. Sparing:
#: an introduction opens in first person and then talks about the work.
IDENTITY = "I'm CreditProbe AI — your AI Risk Officer for the credit book."

MISSION = ("Help you see risk earlier, understand it faster, and act with more "
           "confidence.")

#: The questions an officer can open with. Real portfolio questions, phrased the
#: way a credit officer would phrase them rather than the way a query builder
#: would.
ASK_EXAMPLES: tuple[str, ...] = (
    "Where is risk building across the bank?",
    "Which exposures have deteriorated this quarter?",
    "What is driving Stage 2 and ECL growth?",
    "Which borrowers are weakening but are not yet on the watchlist?",
    "Where are multiple warning signals appearing together?",
)

#: Forward questions. Hedged deliberately — stress testing is configured
#: scenario by scenario, and an answer that implies every scenario already
#: exists is an overclaim (section 18).
SCENARIO_EXAMPLES: tuple[str, ...] = (
    "What happens if PDs rise?",
    "What if these borrowers are downgraded by two notches?",
    "What happens to ECL if credit quality deteriorates?",
    "Which portfolios become most vulnerable under this scenario?",
)

SCENARIO_HEDGE = "as scenarios are configured in Stress Testing"

#: The capabilities named in the opening "I connect the risk picture across..."
#: sentence, in reading order, BY KEY. Built from the registry so the sentence
#: cannot name something this installation does not have — a reconciliation
#: test asserts every key resolves.
CONNECTED_PICTURE: tuple[str, ...] = (
    "portfolio_intelligence", "borrower360", "ratings", "ifrs9",
    "early_warning", "covenants", "collateral", "liquidity",
    "group_risk", "stress_testing", "external_intelligence")

#: Short reading names, for prose that lists many capabilities in one sentence.
#: "Corporate portfolio intelligence, Borrower 360, Corporate ratings and
#: migration, IFRS 9 and ECL intelligence..." is a registry talking; "portfolios,
#: borrowers, ratings, IFRS 9..." is a person talking.
SHORT_NAMES: dict[str, str] = {
    "portfolio_intelligence": "portfolios",
    "borrower360": "borrowers",
    "ratings": "ratings",
    "ifrs9": "IFRS 9",
    "early_warning": "Early Warning",
    "covenants": "covenants",
    "collateral": "collateral",
    "liquidity": "liquidity",
    "group_risk": "connected exposures",
    "stress_testing": "stress testing",
    "external_intelligence": "external intelligence",
    "scorecard_validation": "scorecard validation",
    "data_builder": "the governed data layer",
    "analysis_studio": "the method library",
    "workflow": "Risk Cases",
    "trace": "Trace",
    "ask": "Ask CreditProbe",
    "ai_governance": "AI governance",
}

#: What a senior risk professional gets, as OUTCOMES rather than as modules
#: (section 8). Each is a lead line and the sentence that earns it.
OUTCOMES: tuple[tuple[str, str], ...] = (
    ("See around corners",
     "Emerging deterioration surfaces while there is still something to do "
     "about it, rather than arriving as a committee surprise."),
    ("Challenge faster",
     "Somebody says risk has increased. Ask where, why, by how much, and "
     "which names are driving it — and have the answer in the same "
     "conversation."),
    ("Ask what if",
     "Go past what has already happened. Where scenarios are configured, ask "
     "what deterioration would do to the book before it does it."),
    ("Investigate on demand",
     "Move from the bank to a portfolio, a segment, a borrower, a facility "
     "and its evidence without commissioning another analysis."),
    ("Connect the dots",
     "A downgrade is one signal. Weakening liquidity, covenant pressure, "
     "collateral deterioration and external stress arriving together tell a "
     "different story — and they normally sit in different systems."),
    ("Walk into committee prepared",
     "The concentrations, unusual movements and individual exposures that "
     "deserve management attention, found before the meeting rather than "
     "during it."),
    ("Keep the analysis defensible",
     "Every figure is computed from governed data with traceable evidence "
     "behind it, so a challenged number can be defended line by line."),
)

#: The honest limit, stated in the product's own voice. This sentence is the
#: one that separates CreditProbe from a chatbot, and it belongs in any answer
#: that describes what the AI does.
GROUNDING = ("I can reason — but I don't invent the numbers. Every figure "
             "comes from governed data and deterministic analytics, with "
             "traceable evidence behind it.")

POSITIONING = ("Think of me less as a chatbot and more as an always-available "
               "intelligence layer across your credit book.")

#: The shape of the work, as a flow an officer recognises.
ARC: tuple[str, ...] = ("See earlier", "Investigate deeper", "Ask what if",
                        "Understand why", "Act sooner")

#: The shift the product is for, as the pair of questions it moves a risk
#: conversation between.
SHIFT_FROM = "What happened?"
SHIFT_TO = "What could happen next — and what should we do about it?"

#: How a credit team actually works with it, in the order they would (section
#: 16, question 5). Steps, not features.
TEAM_WORKFLOW: tuple[tuple[str, str], ...] = (
    ("Start the week with what moved",
     "Open with the shape of the book and what changed since the last "
     "reporting period, rather than with a pack somebody built last month."),
    ("Take the names that need attention",
     "Early Warning promotes deterioration into Risk Cases with an owner, so "
     "the queue is a work list rather than a report."),
    ("Investigate one borrower properly",
     "Borrower 360 assembles exposure, ratings, IFRS 9 position, covenants, "
     "collateral, liquidity and the connected group on one screen."),
    ("Test the reading",
     "Ask the follow-up in the same thread. The population and period a "
     "question settled carry forward, so the second question is a "
     "continuation rather than a new query."),
    ("Prepare the committee view",
     "Concentrations, movements and the borrowers behind them, with the "
     "evidence attached."),
    ("Close the loop",
     "The case carries the action, the owner and the decision, and the Trace "
     "carries the arithmetic behind it."),
)

#: Why this is not a dashboard (section 16, question 6). Four claims, each of
#: which the product can be held to.
DASHBOARD_CONTRAST: tuple[tuple[str, str], ...] = (
    ("A dashboard answers the questions it was built for",
     "CreditProbe answers the one you have now. The investigation is composed "
     "for the question rather than selected from a menu of prepared views."),
    ("A dashboard shows; it does not reason",
     "CreditProbe reads the question, plans the investigation, gathers "
     "evidence across domains and tells you what it makes of the result — "
     "labelled as interpretation, separately from the figures."),
    ("A dashboard's definitions live in its queries",
     "Here, which dataset is authoritative, how two tables join and under "
     "what temporal rule are declared, owned and versioned."),
    ("A dashboard cannot show its working",
     "Every answer carries the datasets, joins, filters and arithmetic behind "
     "it, and the fingerprint that reproduces it."),
)

#: Section 12: process flows a product answer may draw, as text.
INVESTIGATION_FLOW: tuple[str, ...] = (
    "BANK", "PORTFOLIO", "SECTOR", "BORROWER", "FACILITY", "EVIDENCE",
    "ACTION")

ANSWER_FLOW: tuple[str, ...] = (
    "ASK", "AI INVESTIGATES", "GOVERNED DATA", "DETERMINISTIC ANALYTICS",
    "EVIDENCE", "ANSWER + TRACE")

#: Section 9: the sentence the AI answer ends on.
CONTROL_LINE = "AI provides flexibility. CreditProbe provides control."


def short_name(key: str) -> str:
    """The reading name for a capability, for prose that lists several."""
    found = capability(key)
    return SHORT_NAMES.get(key) or (found.name if found else key)


def connected_picture() -> tuple[str, ...]:
    """The capability names the opening sentence connects, from the registry."""
    return tuple(short_name(key) for key in CONNECTED_PICTURE
                 if capability(key) is not None)


@dataclass(frozen=True)
class Overview:
    """The composed answer to "what is CreditProbe"."""

    name: str = PRODUCT_NAME
    purpose: str = PURPOSE
    problem: str = PROBLEM
    capabilities: tuple[Capability, ...] = field(default_factory=tuple)
    differentiators: tuple[tuple[str, str], ...] = field(default_factory=tuple)
    version: str = KNOWLEDGE_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name, "purpose": self.purpose,
            "problem": self.problem,
            "capabilities": [c.to_dict() for c in self.capabilities],
            "differentiators": [{"title": t, "detail": d}
                                for t, d in self.differentiators],
            "value_flow": list(VALUE_FLOW),
            "continuum": list(CONTINUUM),
            "version": self.version,
        }


def overview() -> Overview:
    return Overview(capabilities=CAPABILITIES,
                    differentiators=DIFFERENTIATORS)


def capabilities() -> tuple[Capability, ...]:
    return CAPABILITIES


def capability(key: str) -> Capability | None:
    wanted = str(key or "").strip().lower().replace(" ", "_").replace("-", "_")
    found = CAPABILITY_BY_KEY.get(wanted)
    if found is not None:
        return found
    for entry in CAPABILITIES:
        if wanted and (wanted in entry.name.lower().replace(" ", "_")
                       or wanted in entry.key):
            return entry
    return None


def layer(key: str) -> Layer | None:
    for entry in LAYERS:
        if entry.key == key:
            return entry
    return None


def installation() -> dict[str, Any]:
    """What this installation actually holds, right now.

    Read live on every call. A product answer quoting a dataset count is only
    worth quoting if the count is this installation's.
    """
    facts: dict[str, Any] = {}
    for reader in (_every_domain, _early_warning, _relationship_graph,
                   _methods):
        try:
            facts.update(reader())
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not read installation facts: %s", exc)
    return facts


__all__ = [
    "AGENTIC_LAYER",
    "AI_LAYER",
    "CAPABILITIES",
    "CAPABILITY_BY_KEY",
    "CONTINUUM",
    "Capability",
    "DIFFERENTIATORS",
    "ENGINE_LAYER",
    "KNOWLEDGE_VERSION",
    "LAYERS",
    "Layer",
    "Overview",
    "PRODUCT_NAME",
    "PROBLEM",
    "PURPOSE",
    "VALUE_FLOW",
    "WHY_THE_SPLIT",
    "capabilities",
    "capability",
    "installation",
    "layer",
    "overview",
]
