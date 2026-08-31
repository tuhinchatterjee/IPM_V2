"""A banking question corpus for the governed semantic reader. §17.

Five hundred questions that a credit officer might actually type, built to
exercise DISTINCT STRUCTURES rather than distinct nouns. Swapping "Contracting"
for "Real Estate" in the same sentence tests the vocabulary once and the reader
zero times; what breaks a reader is a clause it has not seen the shape of.

So the corpus is organised as structural families, and a family earns its place
by making a demand the others do not: a population defined by its own relative
clause, an anaphor across a sentence boundary, a comparison whose second term
is introduced by a preposition, an imperative opening a second sentence, a
count that is a quantity rather than an identifier, a measure that shares its
name with a verb.

What each case asserts
----------------------
Every case is checked against the reader's INTERMEDIATE reading — the cohorts
it found, the mentions it bound, whether it thinks it needs a previous result,
and which words it took for entity names. Not the HTTP status. A question that
returns 200 having quietly decided that `Explain` is a borrower has failed, and
only the intermediate reading says so.

Three properties hold for every question in the corpus, and each of them was a
real defect:

    NO VERB IS AN ENTITY.       "Explain the SICR evidence..." reported a
                                borrower called Explain. So did "Consider cash
                                balances...".

    A SELF-CONTAINED QUESTION   "Identify the 10 borrowers with the highest
    IS NEVER REFUSED.           probability of..." was refused for want of a
                                previous result that the sentence itself
                                supplies.

    AN AMBIGUOUS ONE IS.        "Rank them by EAD" with nothing before it must
                                still ask which borrowers. A reader that
                                resolves everything has stopped reading.

The six questions from the acceptance run are in here verbatim, in
`REPORTED`, and they are not paraphrased or softened.
"""

from __future__ import annotations

from dataclasses import dataclass, field

CORPUS_VERSION = "1.0.0"


@dataclass(frozen=True)
class Case:
    """One question and what the reader must make of it."""

    question: str
    family: str

    #: True  — the message answers its own references; refusing it is a defect.
    #: False — it genuinely depends on the conversation; refusing it is right.
    #: None  — not asserted for this case.
    self_contained: bool | None = None

    #: A name the reader MUST surface as unknown. Proves the entity guard did
    #: not simply stop reporting everything.
    expect_unknown: str = ""

    #: Words that must never come back as a borrower nobody has heard of.
    #: Empty means "every instruction verb and analytical term in the
    #: question", which the runner derives.
    forbidden: tuple[str, ...] = ()

    #: The population phrase the reader should pick up, where it matters.
    population: str = ""

    tags: tuple[str, ...] = field(default_factory=tuple)


# ---------------------------------------------------------------------------
# The six questions that exposed the defects. Verbatim.
# ---------------------------------------------------------------------------

REPORTED: tuple[Case, ...] = (
    Case(
        "Identify the 10 borrowers with the highest probability of credit "
        "deterioration over the next 12 months. For each borrower, explain "
        "the top five drivers, distinguish borrower-specific drivers from "
        "macroeconomic drivers, and rank the evidence by materiality.",
        family="self-defining population + same-turn distributive",
        self_contained=True, tags=("reported", "top-n", "same-turn")),
    Case(
        "Which borrowers are most likely to migrate from IFRS 9 Stage 1 to "
        "Stage 2? Explain the SICR evidence for every borrower and separate "
        "quantitative, qualitative and forward-looking macroeconomic "
        "triggers.",
        family="question then imperative second sentence",
        self_contained=True, forbidden=("Explain", "Stage", "SICR"),
        tags=("reported", "ifrs9", "sicr", "imperative")),
    Case(
        "Find borrowers whose leverage has increased, EBITDA margins have "
        "declined and debt-service capacity has weakened over the last four "
        "reporting periods. Which of these also have covenant pressure or "
        "negative rating migration?",
        family="multi-condition cohort + same-turn 'these'",
        self_contained=True, forbidden=("Find", "Which", "EBITDA"),
        tags=("reported", "same-turn", "financials", "covenant")),
    Case(
        "Which borrowers currently appear acceptable on headline financial "
        "ratios but show hidden deterioration when I combine covenant "
        "headroom, payment behaviour, utilisation, rating migration, "
        "collateral coverage and early-warning indicators?",
        family="contradictory-evidence cohort",
        self_contained=True, tags=("reported", "hidden", "multi-factor")),
    Case(
        "Which borrowers have the strongest evidence of liquidity stress? "
        "Consider cash balances, working-capital movements, short-term debt, "
        "utilisation, repayment patterns, interest burden and upcoming "
        "maturities.",
        family="question then imperative second sentence",
        self_contained=True, forbidden=("Consider",),
        tags=("reported", "liquidity", "imperative")),
    Case(
        "Find something in this portfolio that a human credit officer could "
        "easily miss.",
        family="open-ended discovery",
        self_contained=True, forbidden=("Find",),
        tags=("reported", "open-ended")),
)


# ---------------------------------------------------------------------------
# Structural families. Each entry is (family, template, slot values).
# The TEMPLATE is the thing under test; the slots keep it from being one case.
# ---------------------------------------------------------------------------

_MEASURES = ("ECL", "EAD", "exposure", "Stage 2 share", "provision coverage",
             "utilisation", "days past due", "covenant headroom",
             "collateral coverage", "interest cover")
_SECTORS = ("Contracting", "Real Estate", "Manufacturing", "Retail Trade",
            "Financial Services", "Healthcare", "Transport and Logistics")
_PERIODS = ("Q2 2026", "Q1 2026", "the latest quarter", "the last four quarters",
            "the last twelve months", "year on year")
_GRADES = ("BB", "B", "CCC", "investment grade", "sub-investment grade")


def _rotate(values: tuple[str, ...], count: int) -> list[str]:
    return [values[i % len(values)] for i in range(count)]


#: (family, builder, how many, tags, expectations)
_FAMILIES: tuple[tuple, ...] = (
    # -- single-turn, plain -------------------------------------------------
    ("plain measure by sector",
     lambda i: f"What is total {_MEASURES[i % len(_MEASURES)]} by sector at "
               f"{_PERIODS[i % len(_PERIODS)]}?",
     10, ("single-turn",), True),
    ("plain measure for one sector",
     lambda i: f"What is {_MEASURES[i % len(_MEASURES)]} for "
               f"{_SECTORS[i % len(_SECTORS)]} at Q2 2026?",
     10, ("single-turn", "sector-filter"), True),
    ("existence question",
     lambda i: f"Do we have any {_SECTORS[i % len(_SECTORS)]} borrowers in "
               f"Stage 3?",
     7, ("single-turn",), True),

    # -- ranking ------------------------------------------------------------
    ("top-N by measure",
     lambda i: f"Show the top {5 + i} borrowers by "
               f"{_MEASURES[i % len(_MEASURES)]}.",
     10, ("top-n", "ranking"), True),
    ("bottom-N by measure",
     lambda i: f"Which {3 + i} borrowers have the lowest "
               f"{_MEASURES[i % len(_MEASURES)]}?",
     8, ("bottom-n", "ranking"), True),
    ("largest superlative without a number",
     lambda i: f"Which sector has the largest "
               f"{_MEASURES[i % len(_MEASURES)]} at Q2 2026?",
     8, ("ranking",), True),
    ("rank an explicit cohort",
     lambda i: f"Rank {_SECTORS[i % len(_SECTORS)]} borrowers by "
               f"{_MEASURES[i % len(_MEASURES)]}, largest first.",
     7, ("ranking",), True),

    # -- comparison and trend ----------------------------------------------
    ("two-period comparison",
     lambda i: f"Compare {_MEASURES[i % len(_MEASURES)]} between Q1 2026 and "
               "Q2 2026.",
     10, ("comparison", "period-over-period"), True),
    ("year-on-year",
     lambda i: f"How has {_MEASURES[i % len(_MEASURES)]} moved year on year?",
     10, ("comparison", "yoy"), True),
    ("trend over several periods",
     lambda i: f"Show the trend in {_MEASURES[i % len(_MEASURES)]} over the "
               "last six quarters.",
     10, ("trend", "multi-period"), True),
    ("comparison with a contrastive preposition",
     lambda i: f"How does {_SECTORS[i % len(_SECTORS)]} compare with the rest "
               f"of the book on {_MEASURES[i % len(_MEASURES)]}?",
     7, ("comparison",), True),
    ("movement attribution",
     lambda i: f"What drove the change in {_MEASURES[i % len(_MEASURES)]} "
               "between Q1 2026 and Q2 2026?",
     10, ("attribution", "comparison"), True),

    # -- IFRS 9 -------------------------------------------------------------
    ("stage migration",
     lambda i: "Which borrowers moved from Stage 1 to Stage 2 in "
               f"{_PERIODS[i % len(_PERIODS)]}?",
     6, ("ifrs9", "migration"), True),
    ("SICR trigger",
     lambda i: "Which SICR triggers are appearing before stage migration in "
               f"{_SECTORS[i % len(_SECTORS)]}?",
     7, ("ifrs9", "sicr"), True),
    ("ECL contribution",
     lambda i: f"Which sectors contributed most to the ECL increase at "
               f"{_PERIODS[i % len(_PERIODS)]}?",
     6, ("ifrs9", "ecl", "attribution"), True),
    ("stage 2 risk",
     lambda i: "Which borrowers are at greatest risk of moving to Stage 2 "
               f"in {_SECTORS[i % len(_SECTORS)]}?",
     7, ("ifrs9", "forward-looking"), True),
    ("PD LGD EAD decomposition",
     lambda i: "Decompose the ECL movement into PD, LGD and EAD effects for "
               f"{_SECTORS[i % len(_SECTORS)]}.",
     7, ("ifrs9", "decomposition"), True),
    ("scenario and overlay",
     lambda i: "How much of the Stage 2 exposure is driven by the "
               "forward-looking macroeconomic scenario rather than by "
               f"observed deterioration in {_SECTORS[i % len(_SECTORS)]}?",
     7, ("ifrs9", "macro"), True),

    # -- ratings ------------------------------------------------------------
    ("rating migration",
     lambda i: f"Which borrowers were downgraded below {_GRADES[i % len(_GRADES)]} "
               "in the last year?",
     5, ("ratings", "migration"), True),
    ("rating staleness",
     lambda i: "Which borrowers have not been re-rated in more than "
               f"{12 + 6 * i} months?",
     6, ("ratings", "staleness"), True),
    ("notch gap",
     lambda i: "Where does the internal grade differ most from the external "
               f"rating in {_SECTORS[i % len(_SECTORS)]}?",
     7, ("ratings",), True),

    # -- covenants, collateral, delinquency ---------------------------------
    ("covenant breach",
     lambda i: f"Which {_SECTORS[i % len(_SECTORS)]} borrowers breached a "
               "covenant this quarter?",
     7, ("covenant",), True),
    ("covenant headroom trend",
     lambda i: "Whose covenant headroom has narrowed most over the last "
               f"{2 + i} quarters?",
     6, ("covenant", "trend"), True),
    ("collateral shortfall",
     lambda i: "Which borrowers have collateral coverage below "
               f"{80 + 10 * i}%?",
     5, ("collateral",), True),
    ("delinquency bucket",
     lambda i: f"How much exposure sits above {30 * (i + 1)} days past due?",
     5, ("delinquency",), True),
    ("payment behaviour",
     lambda i: "Which borrowers have started paying later than their "
               f"contractual terms in {_SECTORS[i % len(_SECTORS)]}?",
     7, ("payments",), True),

    # -- financials and liquidity -------------------------------------------
    ("leverage movement",
     lambda i: "Whose leverage has increased over the last "
               f"{2 + i} reporting periods?",
     6, ("financials", "trend"), True),
    ("margin compression",
     lambda i: "Which borrowers show EBITDA margin compression alongside "
               f"rising short-term debt in {_SECTORS[i % len(_SECTORS)]}?",
     7, ("financials", "multi-factor"), True),
    ("debt service",
     lambda i: "Which borrowers have interest cover below "
               f"{1 + i}x?",
     5, ("financials",), True),
    ("liquidity stress",
     lambda i: "Which borrowers show the strongest evidence of liquidity "
               f"stress in {_SECTORS[i % len(_SECTORS)]}?",
     7, ("liquidity",), True),
    # The phrasings a credit officer uses out loud, none of which contains a
    # column name. Every one is a question about WHICH BORROWERS, and the
    # product answered the first of them with one portfolio number.
    ("liquidity in plain english",
     lambda i: (
         "Which companies are running into liquidity trouble?",
         "Who is beginning to run short of cash?",
         "Which borrowers are drawing more heavily because they are under "
         "financial pressure?",
         "Rank the customers showing the strongest liquidity warning signs.",
         "Who has both rising utilisation and weakening debt-service "
         "capacity?",
         "Which names look most vulnerable to a liquidity squeeze?",
         "Who is under the most cash flow pressure right now?",
         "Which borrowers look most exposed to a funding squeeze?",
     )[i % 8],
     8, ("liquidity", "borrower-filter"), True),
    ("working capital",
     lambda i: "Where has working capital deteriorated fastest over "
               f"{_PERIODS[i % len(_PERIODS)]}?",
     6, ("financials", "trend"), True),

    # -- concentration, groups, connected counterparties ---------------------
    ("concentration",
     lambda i: f"Where is {_MEASURES[i % len(_MEASURES)]} most concentrated "
               "at Q2 2026?",
     8, ("concentration",), True),
    ("concentration movement",
     lambda i: "Has concentration in "
               f"{_SECTORS[i % len(_SECTORS)]} increased since Q1 2026?",
     7, ("concentration", "comparison"), True),
    ("connected group exposure",
     lambda i: "Which connected groups have combined exposure above "
               f"{5 + i}% of capital?",
     6, ("group", "connected"), True),
    ("group limit",
     lambda i: "Which groups are closest to their group limit at "
               f"{_PERIODS[i % len(_PERIODS)]}?",
     6, ("group", "limits"), True),

    # -- early warning, watchlist, macro ------------------------------------
    ("early warning",
     lambda i: "Which early-warning indicators are firing most often in "
               f"{_SECTORS[i % len(_SECTORS)]}?",
     7, ("early-warning",), True),
    ("watchlist",
     lambda i: f"Who has been added to the watchlist since "
               f"{_PERIODS[i % len(_PERIODS)]}?",
     6, ("watchlist",), True),
    ("macro sensitivity",
     lambda i: "Which sectors are most sensitive to the oil price in "
               f"{_PERIODS[i % len(_PERIODS)]}?",
     6, ("macro",), True),
    ("borrower versus macro attribution",
     lambda i: "For the borrowers deteriorating fastest in "
               f"{_SECTORS[i % len(_SECTORS)]}, separate borrower-specific "
               "drivers from macroeconomic ones.",
     7, ("attribution", "macro", "same-turn"), True),

    # -- stress -------------------------------------------------------------
    ("stress scenario",
     lambda i: "What happens to ECL if the downside scenario weight rises to "
               f"{30 + 5 * i}%?",
     6, ("stress",), True),
    ("sensitivity",
     lambda i: f"How sensitive is {_MEASURES[i % len(_MEASURES)]} to a "
               "200 basis point rate rise?",
     6, ("stress", "sensitivity"), True),

    # -- profitability ------------------------------------------------------
    ("risk-adjusted return",
     lambda i: "Which relationships earn least on a risk-adjusted basis in "
               f"{_SECTORS[i % len(_SECTORS)]}?",
     7, ("profitability",), True),

    # -- multi-clause and same-turn co-reference -----------------------------
    ("cohort then rank them",
     lambda i: "Which borrowers were downgraded in "
               f"{_PERIODS[i % len(_PERIODS)]}? Rank them by "
               f"{_MEASURES[i % len(_MEASURES)]}.",
     10, ("same-turn", "anaphor"), True),
    ("cohort then explain them",
     lambda i: f"Which borrowers breached a covenant at "
               f"{_PERIODS[i % len(_PERIODS)]}? Explain what changed for each "
               "of them.",
     8, ("same-turn", "anaphor", "imperative"), True),
    ("cohort then filter these",
     lambda i: "Find borrowers whose utilisation rose above 90%. Which of "
               f"these also have {_MEASURES[i % len(_MEASURES)]} "
               "deterioration?",
     8, ("same-turn", "anaphor"), True),
    ("self-defining top-N then distributive",
     lambda i: f"Identify the {5 + i} borrowers with the highest "
               f"{_MEASURES[i % len(_MEASURES)]}. For each borrower, explain "
               "the main drivers.",
     8, ("same-turn", "top-n", "distributive"), True),
    ("three clauses",
     lambda i: f"Show {_MEASURES[i % len(_MEASURES)]} by sector, compare it "
               "with Q1 2026, and say which sector moved most.",
     8, ("multi-clause",), True),
    ("compound with a shared subject",
     lambda i: f"For {_SECTORS[i % len(_SECTORS)]}, show exposure, Stage 2 "
               "share and covenant breaches at Q2 2026.",
     7, ("multi-clause", "sector-filter"), True),

    # -- imperative openings (the Explain / Consider regression) -------------
    ("imperative opening a second sentence",
     lambda i: f"Which borrowers have rising {_MEASURES[i % len(_MEASURES)]}? "
               "Explain the drivers behind each one.",
     10, ("imperative", "same-turn"), True),
    ("consider-list second sentence",
     lambda i: f"Which borrowers look weakest in "
               f"{_SECTORS[i % len(_SECTORS)]}? Consider leverage, coverage, "
               "utilisation and payment behaviour.",
     7, ("imperative",), True),
    ("separate-instruction second sentence",
     lambda i: f"Which borrowers moved to Stage 2 in "
               f"{_SECTORS[i % len(_SECTORS)]}? Separate quantitative from "
               "qualitative triggers.",
     7, ("imperative", "ifrs9"), True),
    ("summarise-instruction second sentence",
     lambda i: f"What happened to {_MEASURES[i % len(_MEASURES)]} in "
               f"{_PERIODS[i % len(_PERIODS)]}? Summarise the three biggest "
               "contributors.",
     8, ("imperative",), True),

    # -- hidden deterioration / contradictory evidence -----------------------
    ("acceptable on the surface",
     lambda i: f"Which {_SECTORS[i % len(_SECTORS)]} borrowers look "
               "acceptable on headline ratios but weak on behaviour?",
     7, ("hidden", "contradictory"), True),
    ("conflicting signals",
     lambda i: "Where do the rating and the early-warning signal disagree in "
               f"{_SECTORS[i % len(_SECTORS)]}?",
     7, ("contradictory",), True),
    ("recovery",
     lambda i: "Which borrowers have recovered since "
               f"{_PERIODS[i % len(_PERIODS)]}?",
     6, ("recovery",), True),

    # -- counts and proportions: a number that is a quantity, not an id ------
    ("count question",
     lambda i: f"How many borrowers are in Stage 2 in "
               f"{_SECTORS[i % len(_SECTORS)]}?",
     7, ("count",), True),
    ("share question",
     lambda i: f"What share of {_MEASURES[i % len(_MEASURES)]} sits in "
               "sub-investment grade?",
     8, ("proportion",), True),
    ("proportion movement",
     lambda i: "What proportion of the book moved to Stage 2 between Q1 2026 "
               "and Q2 2026?",
     4, ("proportion", "comparison"), True),

    # -- negation and exclusion ---------------------------------------------
    ("negated cohort",
     lambda i: f"Which {_SECTORS[i % len(_SECTORS)]} borrowers were NOT "
               "downgraded this year?",
     7, ("negation",), True),
    ("exclusion filter",
     lambda i: f"Show {_MEASURES[i % len(_MEASURES)]} by sector at Q2 2026, "
               "excluding Financial Services.",
     8, ("exclusion",), True),
    ("no-breach cohort",
     lambda i: "Which borrowers have never breached a covenant but still show "
               f"rising {_MEASURES[i % len(_MEASURES)]}?",
     7, ("negation", "contradictory"), True),

    # -- conditional and hypothetical ---------------------------------------
    ("conditional cohort",
     lambda i: f"If utilisation rose another {5 * (i + 1)} points, which "
               "borrowers would breach their limit?",
     6, ("conditional", "stress"), True),
    ("threshold with a unit",
     lambda i: f"Which borrowers have exposure above SAR {50 * (i + 1)} "
               "million?",
     6, ("threshold",), True),

    # -- grain and substitution ---------------------------------------------
    ("aggregation grain change",
     lambda i: f"Show {_MEASURES[i % len(_MEASURES)]} by region rather than "
               "by sector at Q2 2026.",
     7, ("grain",), True),
    ("secondary ordering",
     lambda i: f"List {_SECTORS[i % len(_SECTORS)]} borrowers by stage, then "
               f"by {_MEASURES[i % len(_MEASURES)]} within each stage.",
     7, ("ordering", "grain"), True),
    ("explicit date range",
     lambda i: f"Show {_MEASURES[i % len(_MEASURES)]} from Q3 2025 to "
               "Q2 2026.",
     8, ("period", "multi-period"), True),
    ("as-at phrasing",
     lambda i: f"What was {_MEASURES[i % len(_MEASURES)]} as at the end of "
               "Q1 2026?",
     8, ("period",), True),

    # -- why-questions ------------------------------------------------------
    ("why did it move",
     lambda i: f"Why did {_MEASURES[i % len(_MEASURES)]} rise in "
               f"{_SECTORS[i % len(_SECTORS)]} this quarter?",
     8, ("attribution", "why"), True),
    ("why is it high",
     lambda i: f"Why is provision coverage so low in "
               f"{_SECTORS[i % len(_SECTORS)]}?",
     7, ("attribution", "why"), True),

    # -- forward-looking ----------------------------------------------------
    ("forward risk",
     lambda i: f"Which {_SECTORS[i % len(_SECTORS)]} borrowers are most "
               "likely to deteriorate over the next twelve months?",
     7, ("forward-looking",), True),
    ("maturity wall",
     lambda i: f"Which borrowers have facilities maturing within "
               f"{6 * (i + 1)} months and weak coverage?",
     5, ("forward-looking", "liquidity"), True),

    # -- borrower-level attribute filters -----------------------------------
    ("borrower attribute filter",
     lambda i: f"Which borrowers rated {_GRADES[i % len(_GRADES)]} have "
               f"rising {_MEASURES[i % len(_MEASURES)]}?",
     8, ("borrower-filter",), True),
    ("group filter",
     lambda i: "Which borrowers belong to a group with more than "
               f"{2 + i} obligors in the book?",
     6, ("group", "borrower-filter"), True),
    ("product filter",
     lambda i: f"Show {_MEASURES[i % len(_MEASURES)]} for revolving "
               "facilities only.",
     6, ("borrower-filter",), True),
)


# ---------------------------------------------------------------------------
# Questions that MUST be refused or clarified. A reader that resolves
# everything has stopped reading, and these are how that is caught.
# ---------------------------------------------------------------------------

AMBIGUOUS: tuple[Case, ...] = (
    Case("Rank them by EAD.", family="bare anaphor",
         self_contained=False, tags=("clarify",)),
    Case("Show me those borrowers.", family="bare anaphor",
         self_contained=False, tags=("clarify",)),
    Case("What about them?", family="bare anaphor",
         self_contained=False, tags=("clarify",)),
    Case("And the same for those names.", family="bare anaphor",
         self_contained=False, tags=("clarify",)),
    Case("Compare these with last quarter.", family="bare anaphor",
         self_contained=False, tags=("clarify",)),
)


#: A genuine borrower name the reader has never heard of must still surface,
#: or the entity guard has been fixed by switching it off.
UNKNOWN_NAMES: tuple[Case, ...] = (
    Case("How is Summit Power doing?", family="unknown borrower",
         expect_unknown="Summit Power", tags=("entity",)),
    Case("Show me Falcon Trading Holdings' exposure.",
         family="unknown borrower", expect_unknown="Falcon Trading Holdings",
         tags=("entity", "possessive")),
    Case("What is the ECL for Northgate Marine Services at Q2 2026?",
         family="unknown borrower",
         expect_unknown="Northgate Marine Services", tags=("entity",)),
    Case("Has Zenith Petrochemical breached a covenant? Explain the position.",
         family="unknown borrower plus imperative",
         expect_unknown="Zenith Petrochemical",
         tags=("entity", "imperative")),
)


def cases() -> tuple[Case, ...]:
    """The whole corpus, in a stable order, with no question repeated.

    The slot lists have different lengths, so two families rotating through
    them can land on the same sentence. A duplicate is not a case: it inflates
    the count without testing anything, which is precisely the "500 trivial
    variants" §17 forbids. Dropped rather than renumbered, so the count this
    module reports is the count of distinct questions.
    """
    built: list[Case] = list(REPORTED)
    for family, template, count, tags, contained in _FAMILIES:
        for index in range(count):
            built.append(Case(question=template(index), family=family,
                              self_contained=contained, tags=tags))
    built.extend(AMBIGUOUS)
    built.extend(UNKNOWN_NAMES)

    seen: set[str] = set()
    unique: list[Case] = []
    for case in built:
        if case.question in seen:
            continue
        seen.add(case.question)
        unique.append(case)
    return tuple(unique)


def families() -> tuple[str, ...]:
    return tuple(sorted({c.family for c in cases()}))


def report() -> dict[str, object]:
    all_cases = cases()
    by_tag: dict[str, int] = {}
    for case in all_cases:
        for tag in case.tags:
            by_tag[tag] = by_tag.get(tag, 0) + 1
    return {
        "version": CORPUS_VERSION,
        "cases": len(all_cases),
        "families": len(families()),
        "self_contained": sum(1 for c in all_cases if c.self_contained is True),
        "must_clarify": sum(1 for c in all_cases if c.self_contained is False),
        "unknown_name_cases": len(UNKNOWN_NAMES),
        "reported_verbatim": len(REPORTED),
        "by_tag": dict(sorted(by_tag.items())),
    }


__all__ = ["AMBIGUOUS", "CORPUS_VERSION", "Case", "REPORTED", "UNKNOWN_NAMES",
           "cases", "families", "report"]
