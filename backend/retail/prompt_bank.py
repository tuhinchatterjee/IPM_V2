"""The phrases that must work, with what each one must produce.

§23: "Build a versioned prompt bank with expected intent/scope/operation,
necessary clarifications and automated result assertions. Test chips through
the same path as typed questions."

Why an expectation is not an answer
-------------------------------------
A prompt bank that stored answers would be a fixture, and a fixture passes
when the product breaks in the one way that matters: it keeps returning the
stored answer. So each entry records what the product must RESOLVE — the
product it scopes to, the period it settles on, the operation it performs —
and what must be true of the result. The answer itself comes from the engine
every time.

The three outcomes an entry can require
-----------------------------------------
Most entries expect a result. Some expect a CLARIFICATION: "make it worse
somehow" has no defensible reading, and a product that guesses a shock has
invented a number somebody will quote. A few expect a REFUSAL: asking to
move thirty-to-fifty-nine day exposure in a cohort that holds none must say
so rather than widen the selection to find some.

Those three are not degrees of success. A clarification where a result was
expected is a regression, and a result where a clarification was expected is
a worse one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

PROMPT_BANK_VERSION = "retail-prompt-bank-1.0.0"

#: Where a prompt is typed. Each surface is a different composer and a
#: different resolver, and §23 asks that chips go through the same path as
#: typed text — so a chip is not a fourth surface, it is one of these with
#: the words filled in.
COCKPIT = "cockpit"
INVESTIGATION = "investigation"
WHATIF = "whatif"
VALIDATION = "validation"

#: What the product must do with it.
ANSWER = "answer"              # a result, with the evidence named below
CLARIFY = "clarify"            # ask; do not guess
REFUSE = "refuse"              # say why it cannot be done as asked


@dataclass(frozen=True)
class Prompt:
    key: str
    said: str
    surface: str
    outcome: str = ANSWER
    #: What the product must resolve from the words, without being told.
    scope: dict[str, str] = field(default_factory=dict)
    #: The operation it must perform. A label, matched against the trace.
    operation: str = ""
    #: Phrases that must appear in the answer for it to be the right answer.
    must_say: tuple[str, ...] = ()
    #: Phrases that must NOT appear. Usually a wrong scope or a claim the
    #: evidence does not support.
    must_not_say: tuple[str, ...] = ()
    #: Why this phrasing is in the bank at all.
    because: str = ""


PROMPTS: tuple[Prompt, ...] = (
    # ------------------------------------------- attention and investigation
    Prompt("why-rise-1", "What are the reasons for this rise?",
           INVESTIGATION, scope={"product": "CREDIT_CARD"},
           operation="delinquency_decomposition",
           must_say=("30", "DPD"),
           must_not_say=("gross carrying amount rose",),
           because="The flagship phrasing. It must inherit the thread's "
                   "product and measure rather than answering about the "
                   "whole portfolio's balance."),
    Prompt("why-rise-2", "what is the reason of this rise?",
           INVESTIGATION, scope={"product": "CREDIT_CARD"},
           operation="delinquency_decomposition",
           because="The same question with a grammatical slip, which is "
                   "what people actually type. §2.7 reproduced the defect "
                   "on exactly this wording."),
    Prompt("roll-breakdown",
           "Break it down into worsening accounts, cures and new accounts.",
           INVESTIGATION, operation="transition_matrix",
           must_say=("cure",),
           because="The three components must be separated rather than "
                   "netted into one movement."),
    Prompt("subproducts", "Show the sub-products driving the increase.",
           INVESTIGATION, scope={"cut": "sub_product"},
           operation="cut_by_dimension",
           because="Sub-product is a derived dimension joined from the "
                   "Early Warning view; the question must not fail because "
                   "the canonical book lacks the column."),
    Prompt("weighted-compare",
           "Compare account-count and exposure-weighted 30+ DPD.",
           INVESTIGATION, operation="weighted_comparison",
           must_say=("exposure",),
           because="Two measures of one population. A single number here "
                   "would hide which of them moved."),
    Prompt("offsets", "What improved and offset the deterioration?",
           INVESTIGATION, operation="offsets",
           because="A decomposition that reports only the worsening half "
                   "overstates the movement."),
    Prompt("ecl-separate",
           "Show the ECL impact separately from the observed default-rate "
           "movement.", INVESTIGATION, operation="ecl_bridge",
           must_say=("ECL",),
           because="The observed rate and the provision move for different "
                   "reasons and on different horizons."),
    Prompt("top-contributors",
           "Show the top five customer contributors and their full trace.",
           INVESTIGATION, operation="top_contributors",
           because="Governed membership, not a sample, and each with the "
                   "chain behind it."),

    # ------------------------------------------------------ trait analysis
    # The five questions the Cockpit itself offers, verbatim from
    # `backend.orchestration.suggestions.RETAIL_COCKPIT`. A suggestion is a
    # promise: the reader did not choose it, the product offered it. So the
    # offered wording is banked exactly, and the suite submits it through the
    # composer as a click does — §23's "test chips through the same path as
    # typed questions" is not satisfied by calling the resolver directly.
    #
    # Every one of these was run through /ask before it was banked. The first
    # draft of this list read "Where is risk building across the retail
    # book?", which came back "Which figure should CreditProbe measure?" —
    # the exact failure an offered question must never produce, since the
    # reader did what they were told and the product asked them what they
    # meant.
    Prompt("cockpit-position",
           "Show retail exposure, customers and weighted ECL by product.",
           COCKPIT, operation="portfolio_position",
           must_say=("2026-08",),
           must_not_say=("which figure",),
           because="The opening position, named by measure so the planner "
                   "never has to ask which figure was meant."),
    Prompt("cockpit-deteriorated",
           "Which retail products have deteriorated this quarter?",
           COCKPIT, operation="deterioration_scan",
           must_not_say=("which figure",),
           because="It must settle on a complete period rather than "
                   "reporting a partial one as if it were whole."),
    Prompt("cockpit-stage2-ecl",
           "What is driving Stage 2 and ECL growth?",
           COCKPIT, operation="ecl_drivers",
           must_say=("stage 2",),
           because="Stage 2 and ECL are different movements and the answer "
                   "must not present one as the explanation of the other."),
    Prompt("cockpit-not-yet-default",
           "Which retail customers are deteriorating but not yet in default?",
           COCKPIT, operation="forward_cohort",
           must_say=("not in default",),
           must_not_say=("with current default",),
           because="\u00a721's forward-risk cohort, and the negation defect "
                   "it caught: this asked for customers NOT in default and "
                   "was answered with the 816 who are, under a confident "
                   "headline. The chip is banked so that cannot come back."),
    Prompt("cockpit-signals-together",
           "Where are multiple early warning signals appearing together?",
           COCKPIT, operation="signal_overlap",
           because="Co-occurrence, not a list of the individual triggers "
                   "ranked by count."),
    Prompt("traits-main",
           "Tell me what customer traits have deteriorated and what is the "
           "impact on ECL because of them.",
           COCKPIT, scope={"product": "RETAIL"},
           operation="trait_inventory",
           must_not_say=("credit card only",),
           because="A FRESH thread. §7.1 forbids inheriting the previous "
                   "conversation's product; this must scope to Retail."),
    Prompt("traits-quarter",
           "Compare the latest complete quarter with the previous quarter.",
           INVESTIGATION, operation="quarter_comparison",
           must_say=("quarter",),
           because="The product must resolve which quarter is complete "
                   "rather than treating the current partial one as whole."),
    Prompt("traits-all-variables",
           "Show all behavioural scorecard variables, not just the top "
           "three.", INVESTIGATION, operation="full_inventory",
           because="A top-three answer to an all-variables question is the "
                   "kind of helpfulness that loses a finding."),
    Prompt("traits-mix",
           "Separate existing-customer deterioration from changes in "
           "portfolio mix.", INVESTIGATION, operation="mix_decomposition",
           must_say=("mix",),
           because="The single most important distinction in the trait "
                   "story, and the one a portfolio average destroys."),
    Prompt("traits-band-migration",
           "How many customers moved to worse behavioural score bands "
           "because of the modeled income changes?",
           INVESTIGATION, operation="band_migration",
           because="A count of movement, with the direction the score "
                   "orientation implies rather than assumed."),
    Prompt("traits-improving",
           "Show the improving variables and their offsets.",
           INVESTIGATION, operation="offsets",
           because="As with the delinquency offsets: half a decomposition "
                   "is a wrong decomposition."),
    Prompt("traits-fixed-model",
           "Keep the model version fixed and explain the trait-driven "
           "change.", INVESTIGATION, operation="fixed_model_attribution",
           because="Attribution across a model change and attribution "
                   "within one are different questions."),
    Prompt("traits-export", "Export this complete analysis to a Word "
           "report.", INVESTIGATION, operation="export_docx",
           because="The export must carry the whole thread, not the last "
                   "answer."),

    # --------------------------------------------------------------- What-If
    Prompt("lgd-pp", "Increase LGD by 5 percentage points.",
           WHATIF, operation="lgd_absolute_pp",
           must_say=("percentage point",),
           because="Percentage points, not a relative increase. Reading "
                   "this as 5% relative understates the shock by an order "
                   "of magnitude."),
    Prompt("lgd-pp-scoped",
           "Add 5 percentage points to LGD for Stage 2 Home Finance.",
           WHATIF, operation="lgd_absolute_pp",
           scope={"stage": "2", "product": "HOME_LOAN"},
           because="The same shock with two scopes in one sentence. The "
                   "'2' in 'Stage 2' must not be read as the amount."),
    Prompt("pd-relative-scoped",
           "Increase PIT 12-month PD by 20% for non-salaried Credit Card "
           "customers.",
           WHATIF, operation="pd_relative",
           scope={"product": "CREDIT_CARD", "classification": "NON_SALARIED"},
           because="Relative this time, with a classification scope."),
    Prompt("dpd-migration-all",
           "Move 100% of 1-29 DPD accounts to 60-89.",
           WHATIF, operation="dpd_migration",
           because="Exact membership, and a bucket pair that skips one."),
    Prompt("dpd-migration-part",
           "Move 20% of 30-59 DPD exposure to 90+.",
           WHATIF, operation="dpd_migration",
           must_say=("exposure",),
           because="By exposure rather than by account. The two select "
                   "different facilities."),
    Prompt("dpd-migration-loose",
           "Move 20% of 30-60 DPD exposure to 90+.",
           WHATIF, outcome=CLARIFY, operation="dpd_migration",
           because="30-60 is not a canonical bucket. The product must ask "
                   "whether 30-59 was meant rather than silently rounding "
                   "to it."),
    Prompt("income-shock", "Reduce verified income by 10% for this "
           "selection.", WHATIF, operation="income_pct",
           must_say=("income",),
           because="The exported cohort, not a re-derived filter."),
    Prompt("income-narrowed",
           "Now apply that only to forward-risk customers.",
           WHATIF, operation="narrow",
           because="Narrowing an existing scenario rather than starting a "
                   "new one. It must narrow WITHIN the selection, not "
                   "re-filter the book."),
    Prompt("expenses-fixed-stage",
           "Increase household expenses by 10% and keep stages fixed.",
           WHATIF, operation="expense_pct",
           because="Two instructions: the shock and the staging mode. "
                   "Dropping the second changes the answer."),
    Prompt("restage", "Re-evaluate stages using the displayed policy.",
           WHATIF, operation="restage",
           because="The opposite mode, named explicitly."),
    Prompt("stage-migration", "Move 15% of Stage 1 exposure to Stage 2.",
           WHATIF, operation="stage_migration",
           because="Staging moved directly rather than through a driver."),
    Prompt("band-migration", "Move 10% of behavioural band B accounts to C.",
           WHATIF, operation="score_band_migration",
           because="Score bands run E to A+ with higher safer; B to C is a "
                   "worsening and must be read as one."),
    Prompt("ccf-pp",
           "Increase CCF by 10 percentage points on eligible undrawn lines.",
           WHATIF, operation="ccf_absolute_pp",
           must_say=("percentage point",),
           because="Percentage points again, and 'eligible' means the "
                   "facilities that actually carry an undrawn limit."),
    Prompt("method-compare",
           "Use XGBoost; then compare with Delta on the same baseline.",
           WHATIF, operation="method_compare",
           must_say=("baseline",),
           because="Both methods on ONE baseline. Two baselines would make "
                   "the comparison meaningless."),
    Prompt("undo", "Undo the last step and save the earlier scenario.",
           WHATIF, operation="undo",
           because="Cumulative semantics: the thread must be able to step "
                   "back without losing what came before."),
    Prompt("vague", "make it worse somehow",
           WHATIF, outcome=CLARIFY, operation="clarify_shock",
           # A clarification is only useful if it names the missing thing. A
           # product that replies "could you be more specific?" has asked the
           # reader to guess what it does not understand.
           must_say=("which", "measure"),
           must_not_say=("10%", "applied"),
           because="No defensible reading. A product that guesses a shock "
                   "here has invented a number somebody will quote. The "
                   "clarification must name the measure and the size it "
                   "needs, not ask the reader to try again."),
    Prompt("no-eligible", "Move 20% of 30-59 DPD exposure to 90+",
           WHATIF, outcome=REFUSE, operation="refuse_no_eligible",
           # The refusal must carry the count that makes it a fact rather
           # than a policy, and the authorised alternative — a refusal with
           # no way forward is a dead end in front of a client.
           must_say=("0", "selection"),
           must_not_say=("applied to",),
           because="Asked of a clean cohort that holds no such accounts. "
                   "It must say so and offer to switch to a broader "
                   "authorised selection, not widen silently."),

    # ------------------------------------------------ validation and workspace
    Prompt("val-development", "What data was this model developed on?",
           VALIDATION, operation="DATA-PROVENANCE",
           must_say=("development",),
           because="The provenance question, answered from the registry and "
                   "the reference population rather than from prose."),
    Prompt("val-population", "Has the population changed since development?",
           VALIDATION, operation="DATA-INPUT-DRIFT",
           because="Representativeness, on every model input."),
    Prompt("val-csi", "Which variables have the highest CSI?",
           VALIDATION, operation="DATA-INPUT-DRIFT",
           must_say=("CSI",),
           because="CSI must mean feature-level shift over approved bins "
                   "here and everywhere else."),
    Prompt("val-ordering-or-calibration",
           "Is this an ordering problem, a calibration problem, or both?",
           VALIDATION, operation="cross_category",
           must_say=("calibration",),
           because="The question a validator actually asks, and the one "
                   "that decides between a recalibration and a "
                   "re-development."),
    Prompt("val-inversion",
           "Why is this better band defaulting more than the adjacent worse "
           "band?", VALIDATION, operation="DISC-RANK",
           because="The inversion, with its support, concentration and "
                   "persistence — not merely its existence."),
    Prompt("val-maturity",
           "Is today's outcome window mature enough to compare?",
           VALIDATION, operation="DATA-MATURITY",
           must_say=("matured",),
           because="The single most common way a scorecard validation goes "
                   "wrong."),
    Prompt("val-comment",
           "Add this comment to the Data & Representativeness section.",
           VALIDATION, operation="comment",
           because="A comment attached to a category, carrying the run and "
                   "data version it was written against."),
    Prompt("val-report",
           "Generate the validation Word report with my comments.",
           VALIDATION, operation="report_docx",
           because="The comment must reach the document. §15's last "
                   "sentence, end to end."),
)

BY_KEY: dict[str, Prompt] = {one.key: one for one in PROMPTS}


def catalogue() -> dict[str, Any]:
    """The bank, for the screen that shows the chips and the suite that
    tests them. One list, so a chip cannot drift from what is tested."""
    by_surface: dict[str, list[dict[str, Any]]] = {}
    for one in PROMPTS:
        by_surface.setdefault(one.surface, []).append({
            "key": one.key, "said": one.said, "outcome": one.outcome,
            "scope": dict(one.scope), "operation": one.operation,
            "must_say": list(one.must_say),
            "must_not_say": list(one.must_not_say),
            "because": one.because,
        })
    return {
        "prompt_bank_version": PROMPT_BANK_VERSION,
        "prompts": len(PROMPTS),
        "by_surface": by_surface,
        "outcomes": [
            {"outcome": ANSWER, "meaning": "A result, with the evidence "
                                           "named."},
            {"outcome": CLARIFY, "meaning": "Ask. Do not guess — a guessed "
                                            "shock is a number somebody "
                                            "will quote."},
            {"outcome": REFUSE, "meaning": "Say why it cannot be done as "
                                           "asked, and offer the authorised "
                                           "alternative rather than taking "
                                           "it."},
        ],
        "chips_are_prompts": (
            "A chip on any surface is an entry from this bank with its "
            "words filled in, submitted through the same path a typed "
            "question takes. A chip that took a shortcut would pass a test "
            "the typed phrasing fails."),
    }


__all__ = ["ANSWER", "BY_KEY", "CLARIFY", "COCKPIT", "INVESTIGATION",
           "PROMPTS", "PROMPT_BANK_VERSION", "Prompt", "REFUSE",
           "VALIDATION", "WHATIF", "catalogue"]
