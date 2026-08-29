"""The safe demonstration question set, and what each answer must satisfy.

§24 and §25 of the client-demo release-candidate brief.

    "Use exact questions with deterministic acceptance specifications. Do not
     hard-code portfolio answers in production routing."

Note what is and is not here. Each entry records the EXPECTED SHAPE of a
correct answer — which capability, which officer, which datasets, which grain,
which invariants must hold, what a clarification would be legitimate for, and
what would be a forbidden fallback. It records no figure. A stored figure is
correct for one quarter and wrong for every quarter after it, and a
demonstration whose answers came from here would be a demonstration of this
file.

The runner in `scripts/demo_questions.py` drives the real routing and planning
path with the provider stubbed out and checks the deterministic half: officer
level, capability, whether it clarifies, whether it refuses. The half that
needs a live model — the prose, the interpretation — is checked by the
presenter's own `-Critical` run against their own key.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

QUESTIONS_VERSION = "1.0.0"

#: Officer levels, by the name a reader sees on screen.
ANALYST = 1
SENIOR = 2
PORTFOLIO_LEAD = 3
CHIEF = 4

OFFICER_TITLE: dict[int, str] = {
    ANALYST: "Credit Analyst",
    SENIOR: "Senior Credit Officer",
    PORTFOLIO_LEAD: "Portfolio Risk Lead",
    CHIEF: "Chief Orchestrator",
}

#: What a correct answer DOES, as a whole. One of these, never two.
EXECUTE = "EXECUTE"
CLARIFY = "CLARIFY"
UNSUPPORTED = "UNSUPPORTED"
REUSE = "REUSE"
#: Answered from the governed CATALOGUE rather than by running an analysis.
#:
#: A distinct outcome because it is distinct behaviour, and the first version
#: of this file got it wrong: it demanded EXECUTE for "what ratings data do you
#: have?", and the product was right to answer without running anything. A
#: metadata question that ran an analysis would be the defect.
METADATA = "METADATA"

OUTCOMES: tuple[str, ...] = (EXECUTE, CLARIFY, UNSUPPORTED, REUSE, METADATA)

OUTCOME_MEANS: dict[str, str] = {
    EXECUTE: "Runs a governed analysis and shows the result.",
    CLARIFY: "Asks one question back. Answering anyway would be a guess.",
    UNSUPPORTED: "Says the data cannot answer this. Not an error, an answer.",
    REUSE: "Assesses the result already on screen rather than recomputing.",
    METADATA: "Answers from the catalogue, without running an analysis.",
}


@dataclass
class Question:
    """One demonstration question and everything a correct answer must satisfy.

    `forbidden` is the field that earns its place. Every other field says what
    a right answer looks like; this one says what a WRONG-BUT-PLAUSIBLE answer
    would look like, and that is what separates a check from a formality.
    """

    ref: str
    text: str
    #: Why this question is in the set at all.
    shows: str = ""
    outcome: str = EXECUTE
    officer: int | None = None
    capability: str = ""
    specialists: int = 0
    datasets: tuple[str, ...] = ()
    period: str = ""
    grain: str = ""
    operations: tuple[str, ...] = ()
    invariants: tuple[str, ...] = ()
    #: Legitimate reasons for this question to come back with a question.
    may_clarify: tuple[str, ...] = ()
    #: What a wrong answer would do. Any of these is a failure.
    forbidden: tuple[str, ...] = ()
    presentation: str = ""
    assurance: tuple[str, ...] = ()
    trace: tuple[str, ...] = ()
    #: Follow-ups asked in the same thread, in order.
    follow_ups: tuple[str, ...] = ()
    #: Whether a failure here blocks GO.
    critical: bool = True
    #: What the offline runner cannot settle, and who settles it instead.
    #: Present only where it applies; an empty string means the offline check
    #: is the whole check.
    needs_live: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ref": self.ref, "question": self.text, "shows": self.shows,
            "expected_outcome": self.outcome,
            "expected_officer": self.officer,
            "expected_officer_title": OFFICER_TITLE.get(self.officer or 0, ""),
            "capability": self.capability,
            "specialists": self.specialists,
            "datasets": list(self.datasets), "period": self.period,
            "grain": self.grain, "operations": list(self.operations),
            "invariants": list(self.invariants),
            "may_clarify": list(self.may_clarify),
            "forbidden": list(self.forbidden),
            "presentation": self.presentation,
            "assurance": list(self.assurance), "trace": list(self.trace),
            "follow_ups": list(self.follow_ups), "critical": self.critical,
            "needs_live": self.needs_live,
        }


#: The set. Fifteen questions, in the order §24 lists them.
QUESTIONS: tuple[Question, ...] = (
    Question(
        ref="Q1",
        text="What ratings data do you have?",
        shows="A metadata question is answered by a Credit Analyst, from the "
              "catalogue, without running an analysis. The agentic layer does "
              "not engage for everything, which is as important as engaging "
              "when it should.",
        outcome=METADATA,
        officer=ANALYST,
        capability="METADATA_DISCOVERY",
        specialists=0,
        datasets=("customer_ratings", "rating_transitions"),
        operations=("describe_datasets",),
        forbidden=("summoning specialists for a question about the catalogue",
                   "inventing a dataset that is not published",
                   "answering with a portfolio figure nobody asked for"),
        presentation="table or prose; no chart",
        trace=("data sources",),
    ),
    Question(
        ref="Q2",
        text="How is ratings data connected to IFRS 9?",
        shows="Governed relationships are real objects, not prose. The answer "
              "names the join path, and does not compute anything to do it.",
        outcome=METADATA,
        # With no provider configured this is answered conversationally and
        # consults no relationship at all - flow CONVERSATIONAL_NO_ANALYSIS,
        # zero datasets. That is honest rather than wrong: without a model
        # there is nothing to compose the explanation with. What the offline
        # runner CANNOT settle is whether the live answer names the governed
        # join path, so it does not block GO and the live run checks it.
        needs_live="whether the answer names the governed join path rather "
                   "than describing a plausible one",
        critical=False,
        officer=ANALYST,
        capability="RELATIONSHIP_DISCOVERY",
        datasets=("customer_ratings", "ifrs9_staging"),
        operations=("describe_relationships",),
        forbidden=("describing a join that is not a governed relationship",
                   "computing a figure to answer a structural question"),
        trace=("relationship path",),
    ),
    Question(
        ref="Q3",
        text="What is total EAD by sector in the latest quarter?",
        shows="The straightforward case, end to end: one grouping, one "
              "measure, a Trace, and the two workbook downloads.",
        outcome=EXECUTE,
        officer=ANALYST,
        capability="ANALYSIS",
        specialists=0,
        datasets=("portfolio_facility",),
        period="latest quarter",
        grain="segment",
        operations=("filter_period", "group_by_sector", "sum_ead"),
        invariants=("non_negative_exposure", "grain_matches_request"),
        forbidden=("returning facility rows for a question about sectors",
                   "using limit or drawn where EAD was asked for",
                   "silently changing the period"),
        presentation="table, one row per sector",
        assurance=("dataset_selection", "period_selection", "grain_selection",
                   "generated_query"),
        trace=("plan", "query", "invariants", "assurance"),
        follow_ups=("Show only the five largest.",
                    "Show each one's share of portfolio EAD.",
                    "Replace EAD with customer count.",
                    "Show as a graph."),
    ),
    Question(
        ref="Q4",
        text="Show the five largest Real Estate customers by EAD.",
        shows="Customer grain, a filter and a ranking - and the grain contract "
              "that keeps a top-N at customer level rather than facility.",
        outcome=EXECUTE,
        officer=ANALYST,
        capability="ANALYSIS",
        datasets=("portfolio_facility",),
        period="latest quarter",
        grain="customer",
        operations=("filter_sector", "group_by_customer", "sum_ead",
                    "rank_desc", "top_n"),
        invariants=("ordering", "top_n_respected", "grain_matches_request"),
        forbidden=("returning five FACILITIES rather than five customers",
                   "ranking ascending",
                   "returning more or fewer than five rows"),
        presentation="table, five rows",
        follow_ups=("Which of these are Stage 2 or Stage 3?",
                    "Add latest rating.",
                    "Rank by ECL."),
    ),
    Question(
        ref="Q5",
        text=("For each sector, calculate Stage 2 EAD divided by total sector "
              "EAD, compare with four quarters ago and rank by increase."),
        shows="A nested ratio, a period comparison and a ranking in one "
              "request. Three things any one of which can be got wrong "
              "quietly.",
        outcome=EXECUTE,
        # Portfolio Risk Lead rather than Senior Credit Officer: "for each
        # sector" makes this portfolio-wide segment work, which is the
        # ladder's own definition of level 3. The first version of this file
        # guessed 2 and the product was right.
        officer=PORTFOLIO_LEAD,
        capability="ANALYSIS",
        datasets=("portfolio_facility", "ifrs9_staging"),
        period="latest quarter and four quarters before",
        grain="segment",
        operations=("filter_stage", "group_by_sector", "ratio",
                    "compare_periods", "rank_desc"),
        invariants=("ratio_between_zero_and_one", "ordering",
                    "both_periods_present"),
        forbidden=("averaging the ratios instead of dividing the totals",
                   "comparing against the wrong quarter",
                   "ranking by level rather than by increase"),
        presentation="table, one row per sector",
    ),
    Question(
        ref="Q6",
        text=("Which customers had a rating downgrade and an increase in ECL "
              "over the latest year?"),
        shows="Two domains, joined at customer grain. A Senior Credit Officer, "
              "and deliberately NOT a swarm.",
        outcome=EXECUTE,
        officer=SENIOR,
        capability="ANALYSIS",
        specialists=0,
        datasets=("customer_ratings", "rating_transitions", "ifrs9_staging"),
        period="latest year",
        grain="customer",
        operations=("detect_downgrade", "compare_ecl", "intersect"),
        invariants=("grain_matches_request", "no_duplicate_customers"),
        forbidden=("returning customers meeting only ONE of the two conditions",
                   "a join that multiplies rows and inflates the count",
                   "engaging a broad portfolio swarm for a two-domain query"),
        presentation="table, one row per customer",
    ),
    Question(
        ref="Q7",
        text=("Which customers have worsening leverage, declining DSCR and a "
              "downgrade?"),
        shows="Three conditions across financials and ratings.",
        outcome=EXECUTE,
        officer=SENIOR,
        capability="ANALYSIS",
        datasets=("borrower_financials", "customer_ratings"),
        grain="customer",
        operations=("compare_leverage", "compare_dscr", "detect_downgrade",
                    "intersect"),
        invariants=("no_duplicate_customers",),
        forbidden=("returning customers meeting two of the three conditions",
                   "treating a missing ratio as a worsening one"),
        may_clarify=("over what period, if the thread has not set one",),
    ),
    Question(
        ref="Q8",
        text=("Which large Real Estate customers have worsening DPD, "
              "increasing ECL, a downgrade and covenant headroom below 15%?"),
        shows="Four conditions and a threshold, at customer grain. The hardest "
              "question in the set that still has one right answer.",
        outcome=EXECUTE,
        # Chief Orchestrator, and it earns it: four conditions across four
        # domains, four specialists engaged, and all five datasets read. Worth
        # knowing before demonstrating it - this is the slowest question in
        # the set.
        officer=CHIEF,
        specialists=3,
        capability="ANALYSIS",
        datasets=("portfolio_facility", "facility_delinquency", "ifrs9_staging",
                  "customer_ratings", "covenant_tests"),
        grain="customer",
        operations=("filter_sector", "compare_dpd", "compare_ecl",
                    "detect_downgrade", "threshold_headroom", "intersect"),
        invariants=("threshold_applied_as_stated", "no_duplicate_customers"),
        forbidden=("applying the 15% threshold to the wrong measure",
                   "dropping one of the four conditions silently",
                   "reading 'large' as a governed filter without saying how"),
        may_clarify=("what counts as large, if the thread has not set one",),
    ),
    Question(
        ref="Q9",
        text="Something seems wrong with Contracting. Investigate it.",
        shows="A segment investigation. Specialists are engaged and the Trace "
              "says which data they read.",
        outcome=EXECUTE,
        officer=CHIEF,
        capability="BROAD_INVESTIGATION",
        specialists=3,
        datasets=("portfolio_facility", "ifrs9_staging", "customer_ratings"),
        grain="segment",
        operations=("screen_segment", "decompose", "synthesise"),
        forbidden=("a Chief Orchestrator badge over a single-query run",
                   "a synthesis that names a figure no analysis produced",
                   "reporting no datasets after running sub-analyses"),
        trace=("agentic tasks", "sub-analyses", "assurance"),
    ),
    Question(
        ref="Q10",
        text=("Review the latest portfolio and tell me what genuinely requires "
              "CRO attention."),
        shows="The broad review. Three or more specialists, a task graph, and "
              "a composition record that says what was read.",
        outcome=EXECUTE,
        officer=CHIEF,
        capability="BROAD_INVESTIGATION",
        specialists=3,
        datasets=("portfolio_facility", "ifrs9_staging"),
        period="latest quarter",
        grain="portfolio",
        operations=("screen_portfolio", "rank_materiality", "synthesise"),
        forbidden=("listing everything rather than what is material",
                   "a badge with no orchestration behind it"),
        trace=("agentic tasks", "sub-analyses", "assurance"),
    ),
    Question(
        ref="Q11",
        text="Does this trend make sense?",
        shows="Reuse. The result already on screen is assessed rather than "
              "recomputed, and the Trace says so.",
        outcome=REUSE,
        officer=ANALYST,
        capability="ASSESS_PREVIOUS_RESULT",
        operations=("assess_previous",),
        forbidden=("re-running the analysis when the result is already there",
                   "answering about a different result than the one on screen"),
        trace=("previous result reused",),
    ),
    Question(
        ref="Q12",
        text="Show me exposure.",
        shows="Material ambiguity. Limit, drawn, EAD and net exposure are "
              "different amounts, and guessing is worse than asking.",
        outcome=CLARIFY,
        officer=ANALYST,
        capability="ANALYSIS",
        may_clarify=("which exposure measure", "over what population",
                     "at what period"),
        forbidden=("picking one exposure measure and not saying which",
                   "returning a portfolio total as though the question was "
                   "specific"),
    ),
    Question(
        ref="Q13",
        text="Which borrowers had their CEO resign?",
        shows="An unsupported question answered as one. Not an error, and not "
              "an unrelated analysis.",
        outcome=UNSUPPORTED,
        officer=ANALYST,
        capability="ANALYSIS",
        forbidden=("running an unrelated analysis and presenting it",
                   "an HTTP 500",
                   "inventing a governance dataset"),
    ),
    Question(
        ref="Q14",
        text="Review unresolved risks in this Project.",
        shows="Project scope, and the clarification gate. Ask this INSIDE the "
              "seeded Project.\n\n"
              "Today CreditProbe asks which figure to measure rather than "
              "summarising the Project's open Risk Cases. That is the "
              "clarification gate working - the sentence names no governed "
              "measure - and it is ALSO a capability that is not built: "
              "there is no Project risk summary. Recorded as the expected "
              "behaviour rather than dressed up, and listed in "
              "docs/DEMO_KNOWN_LIMITATIONS.md.",
        outcome=CLARIFY,
        officer=ANALYST,
        capability="ANALYSIS",
        may_clarify=("which figure to measure",),
        forbidden=("reading an object from outside the Project",
                   "publishing the thread globally without being asked",
                   "inventing a Project risk summary from nothing"),
        critical=True,
    ),
    Question(
        ref="Q15",
        text="What does the circular say about provisioning for Stage 2?",
        shows="Regulatory retrieval WITH a citation and an effective date. "
              "Only ask this if an approved Regulatory Release exists.",
        outcome=UNSUPPORTED,
        # Left unset: a regulatory question is material, and the router
        # reaches Senior Credit Officer for it on the "material" reason. That
        # is defensible and the refusal is what matters here, so the officer
        # is not asserted rather than asserted to a number this file guessed.
        officer=None,
        capability="REGULATORY",
        forbidden=("quoting a circular with no citation",
                   "quoting one that was not in force on the reporting date",
                   "answering at all when no Regulatory Release is active",
                   "running an analysis over ifrs9_staging and presenting it "
                   "as what the circular says"),
        # Critical, and it earned it. This question is what found the defect:
        # CreditProbe ran a SIMPLE_ANALYSIS over ifrs9_staging and presented
        # the result, with no circular in the corpus. The refusal is now the
        # expected behaviour and a regression here is a NO-GO.
        critical=True,
    ),
)

BY_REF: dict[str, Question] = {q.ref: q for q in QUESTIONS}

CRITICAL: tuple[Question, ...] = tuple(q for q in QUESTIONS if q.critical)
