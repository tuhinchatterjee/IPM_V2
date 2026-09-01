"""
The hidden benchmark library.

What a case is
--------------
A **thread**, not a question. Most of what broke in production broke on the
second turn, so a library of isolated questions would have passed while the
product was unusable. Every case here is one or more turns run through the real
Investigation path, in order, carrying its own conversation state.

Each turn declares what a correct answer looks like — the capability it should be
routed to, the governed concepts it needs, the datasets and relationships it
should use, the period and grain, the shape of the plan, and a **reference
specification**. The reference is not an answer; it is instructions for computing
one independently (see `gold.py`), and it is executed only after CreditProbe has
already produced its own.

Why the expected answers are not in this file
---------------------------------------------
Because a figure written here would be a figure a future edit could quietly
align to the system's own output. A specification cannot be: it says "sum ead
from portfolio_facility at Q2 2026 grouped by sector", and whatever that comes
to is the truth.

The isolation rule
------------------
Nothing in production may import this module. The runner imports production; the
reverse is a defect, and `tests/validation/test_isolation.py` fails the build if
it appears. That is what stops a benchmark's expectations reaching a prompt.
"""

from __future__ import annotations

from typing import Any

#: The quarterly book's latest published period. Stated once so a case reads as
#: a question a person would ask rather than a period-shaped constant.
LATEST = "Q2 2026"
YEAR_AGO = "Q2 2025"
PREVIOUS = "Q1 2026"

FACILITY = "portfolio_facility"
IFRS9 = "ifrs9_staging"
RATINGS = "customer_ratings"
DELINQUENCY = "facility_delinquency"
COVENANTS = "covenant_tests"
COLLATERAL = "collateral_register"
LIMITS = "facility_limits"
WATCHLIST = "watchlist_register"

# Categories, in the words the validation panel shows.
DISCOVERY = "DATA DISCOVERY"
DICTIONARY = "DATA DICTIONARY"
QUALITY = "DATA COVERAGE"
RELATIONSHIP = "RELATIONSHIPS"
CALCULATION = "DYNAMIC ANALYSIS"
RANKING = "RANKING"
COUNTING = "COUNTING"
COHORT = "MULTI-DOMAIN"
METHOD = "CERTIFIED METHOD"
REFUSAL = "AMBIGUITY"
MULTITURN = "MULTI-TURN"

#: Which categories count as "metadata", "calculation" and "conversation" when
#: the runner draws its balanced sample of three.
FAMILIES: dict[str, tuple[str, ...]] = {
    "metadata": (DISCOVERY, DICTIONARY, QUALITY, RELATIONSHIP),
    "calculation": (CALCULATION, RANKING, COUNTING, METHOD),
    "conversation": (MULTITURN, COHORT, REFUSAL),
}


def _case(case_id: str, category: str, title: str,
          turns: list[dict[str, Any]]) -> dict[str, Any]:
    return {"id": case_id, "category": category, "title": title, "turns": turns}


def _turn(question: str, **expect: Any) -> dict[str, Any]:
    return {"question": question, "expect": expect}


# ===================================================== what data exists (18)

_DISCOVERY_SUBJECTS: tuple[tuple[str, str], ...] = (
    ("payment history", "payment_history"),
    ("recoveries", "recoveries"),
    ("credit memos", "credit_memo_signals"),
    ("borrower financials", "borrower_financials"),
    ("borrower ratings", RATINGS),
    ("IFRS 9 impairment", IFRS9),
    ("arrears", DELINQUENCY),
    ("collateral", COLLATERAL),
    ("covenants", COVENANTS),
    ("facility limits", LIMITS),
    ("the watchlist", WATCHLIST),
    ("the facility book", FACILITY),
)


def _discovery() -> list[dict[str, Any]]:
    cases = []
    for index, (subject, dataset) in enumerate(_DISCOVERY_SUBJECTS, start=1):
        cases.append(_case(
            f"disc-{index:03d}", DISCOVERY,
            f"What data exists about {subject}",
            [_turn(f"What data do you have about {subject}?",
                   intent="DATA_DISCOVERY", datasets=[dataset],
                   computes=False,
                   reference={"kind": "dataset", "dataset": dataset})]))

    # No reference: "what data is available?" names no subject, so which
    # dataset it leads with is a presentation choice rather than a fact. What is
    # scored is that it was routed to the catalogue and computed nothing.
    cases.append(_case(
        "disc-101", DISCOVERY, "The catalogue as a whole",
        [_turn("What data is available?", intent="DATA_DISCOVERY",
               computes=False)]))
    cases.append(_case(
        "disc-102", DISCOVERY, "Which datasets carry exposure",
        [_turn("Which datasets do you have for exposure?",
               intent="DATA_DISCOVERY", datasets=[FACILITY], computes=False,
               reference={"kind": "dataset", "dataset": FACILITY})]))
    return cases


# ================================================= what a field means (14)

_DICTIONARY_SUBJECTS: tuple[tuple[str, str], ...] = (
    ("watchlist", WATCHLIST),
    ("recoveries", "recoveries"),
    ("payment history", "payment_history"),
    ("ratings", RATINGS),
    ("IFRS 9 staging", IFRS9),
    ("delinquency", DELINQUENCY),
    ("collateral register", COLLATERAL),
    ("covenant tests", COVENANTS),
    ("facility limits", LIMITS),
)


def _dictionary() -> list[dict[str, Any]]:
    cases = []
    for index, (subject, dataset) in enumerate(_DICTIONARY_SUBJECTS, start=1):
        cases.append(_case(
            f"dict-{index:03d}", DICTIONARY,
            f"Which fields the {subject} data carries",
            [_turn(f"What fields are available in the {subject} data?",
                   intent="DATA_DICTIONARY", datasets=[dataset],
                   computes=False,
                   reference={"kind": "dataset", "dataset": dataset})]))
    # A term lookup returns the ONE field it defines, so the dataset's field
    # count is not what a correct answer asserts. Scored on routing and source.
    cases.append(_case(
        "dict-101", DICTIONARY, "What a governed term means",
        [_turn("What does DSCR mean?", intent="DATA_DICTIONARY",
               computes=False)]))
    cases.append(_case(
        "dict-102", DICTIONARY, "What exposure at default means",
        [_turn("What is meant by exposure at default?",
               intent="DATA_DICTIONARY", computes=False)]))
    return cases


# ==================================================== how much history (8)


def _coverage() -> list[dict[str, Any]]:
    subjects = ((f"{RATINGS}", "ratings", "years"),
                (f"{IFRS9}", "IFRS 9", "quarters"),
                (f"{DELINQUENCY}", "arrears", "quarters"),
                (f"{FACILITY}", "the facility book", "quarters"),
                (f"{COVENANTS}", "covenant test", "quarters"),
                (f"{COLLATERAL}", "collateral", "quarters"))
    cases = []
    for index, (dataset, subject, unit) in enumerate(subjects, start=1):
        cases.append(_case(
            f"cov-{index:03d}", QUALITY,
            f"How much {subject} history there is",
            [_turn(f"How many {unit} of {subject} history do you have?",
                   intent="DATA_QUALITY", datasets=[dataset], computes=False,
                   reference={"kind": "dataset", "dataset": dataset})]))
    cases.append(_case(
        "cov-101", QUALITY, "Which periods the book covers",
        [_turn("What periods does the facility book cover?",
               intent="DATA_QUALITY", datasets=[FACILITY], computes=False,
               reference={"kind": "dataset", "dataset": FACILITY})]))
    return cases


# ====================================================== how things join (8)

_PAIRS: tuple[tuple[str, str, str, str], ...] = (
    ("payment history", "portfolio facility", "payment_history", FACILITY),
    ("recoveries", "portfolio facility", "recoveries", FACILITY),
    ("borrower financials", "portfolio facility", "borrower_financials", FACILITY),
    ("credit memos", "portfolio facility", "credit_memo_signals", FACILITY),
    ("ratings", "IFRS 9", RATINGS, IFRS9),
    ("portfolio facility", "IFRS 9", FACILITY, IFRS9),
    ("arrears", "portfolio facility", DELINQUENCY, FACILITY),
    ("collateral", "portfolio facility", COLLATERAL, FACILITY),
    ("covenants", "portfolio facility", COVENANTS, FACILITY),
    ("ratings", "portfolio facility", RATINGS, FACILITY),
    ("facility limits", "portfolio facility", LIMITS, FACILITY),
    ("the watchlist", "portfolio facility", WATCHLIST, FACILITY),
)


def _relationships() -> list[dict[str, Any]]:
    cases = []
    for index, (left, right, source, target) in enumerate(_PAIRS, start=1):
        cases.append(_case(
            f"rel-{index:03d}", RELATIONSHIP,
            f"How {left} connects to {right}",
            [_turn(f"How is {left} data connected to {right} data?",
                   intent="DATA_RELATIONSHIP", datasets=[source, target],
                   computes=False, forbidden_methods=["stage_distribution",
                                                      "portfolio_summary"],
                   reference={"kind": "relationship", "source": source,
                              "target": target})]))
    return cases


# ================================================== composed analysis (16)

_AGGREGATES: tuple[tuple[str, str, str, str], ...] = (
    ("total EAD", "ead", "sector", FACILITY),
    ("total EAD", "ead", "region", FACILITY),
    ("total EAD", "ead", "segment", FACILITY),
    ("total EAD", "ead", "product_type", FACILITY),
    ("total exposure", "exposure", "sector", FACILITY),
    ("total exposure", "exposure", "region", FACILITY),
    ("total expected credit loss", "total_ecl", "sector", IFRS9),
    ("total expected credit loss", "total_ecl", "segment", IFRS9),
    ("total expected credit loss", "total_ecl", "ifrs9_stage", IFRS9),
    ("total drawn exposure", "exposure", "segment", FACILITY),
    ("total drawn exposure", "exposure", "region", FACILITY),
)


def _aggregates() -> list[dict[str, Any]]:
    cases = []
    for index, (phrase, column, dimension, dataset) in enumerate(_AGGREGATES,
                                                                 start=1):
        cases.append(_case(
            f"agg-{index:03d}", CALCULATION,
            f"{phrase} by {dimension} at the latest quarter",
            [_turn(f"What is {phrase} by {dimension} in the latest quarter?",
                   intent="ANALYSIS", computes=True, shape="aggregate",
                   dimension=dimension, period=LATEST, datasets=[dataset],
                   forbidden_methods=["sector_concentration",
                                      "portfolio_summary"],
                   reference={"kind": "aggregate", "dataset": dataset,
                              "measure": column, "dimension": dimension,
                              "period": LATEST})]))

    cases.append(_case(
        "agg-101", CALCULATION, "A filtered total by sector",
        [_turn("What is total EAD by segment for Real Estate in the latest quarter?",
               intent="ANALYSIS", computes=True, shape="aggregate",
               dimension="segment", period=LATEST,
               filters={"sector": "Real Estate"},
               reference={"kind": "aggregate", "dataset": FACILITY,
                          "measure": "ead", "dimension": "segment",
                          "period": LATEST,
                          "filters": [{"column": "sector",
                                       "value": "Real Estate"}]})]))
    # Days past due is governed on the facility book as `dpd_days`, and it is
    # rolled up by its worst value rather than averaged — a portfolio's arrears
    # position is the worst account in it, not the mean of them.
    cases.append(_case(
        "agg-102", CALCULATION, "The worst days past due in each sector",
        [_turn("What is the worst days past due by sector in the latest quarter?",
               intent="ANALYSIS", computes=True, shape="aggregate",
               dimension="sector", period=LATEST,
               reference={"kind": "aggregate", "dataset": FACILITY,
                          "measure": "dpd_days", "dimension": "sector",
                          "period": LATEST, "agg": "max"})]))
    return cases


# ============================================================ rankings (12)

_RANKINGS: tuple[tuple[str, str, str, int], ...] = (
    ("Real Estate", "EAD", "ead", 5),
    ("Contracting", "EAD", "ead", 10),
    ("Petrochemicals", "EAD", "ead", 5),
    ("Healthcare", "exposure", "exposure", 5),
    ("Transport & Logistics", "EAD", "ead", 5),
    ("Wholesale & Retail Trade", "EAD", "ead", 10),
    ("Utilities", "EAD", "ead", 5),
)


def _rankings() -> list[dict[str, Any]]:
    cases = []
    for index, (sector, phrase, column, top_n) in enumerate(_RANKINGS, start=1):
        word = {5: "five", 10: "ten"}[top_n]
        cases.append(_case(
            f"rank-{index:03d}", RANKING,
            f"The {word} largest {sector} customers by {phrase}",
            [_turn(f"Show me the {word} largest {sector} customers by {phrase}.",
                   intent="ANALYSIS", computes=True, shape="ranking",
                   grain="customer", top_n=top_n, period=LATEST,
                   filters={"sector": sector},
                   forbidden_methods=["sector_concentration",
                                      "obligor_concentration"],
                   reference={"kind": "ranking", "dataset": FACILITY,
                              "measure": column, "key": "customer_id",
                              "period": LATEST, "top_n": top_n,
                              "filters": [{"column": "sector",
                                           "value": sector}]})]))

    cases.append(_case(
        "rank-101", RANKING, "The largest customers in the book",
        [_turn("Show me the ten largest customers by exposure at default.",
               intent="ANALYSIS", computes=True, shape="ranking",
               grain="customer", top_n=10, period=LATEST,
               reference={"kind": "ranking", "dataset": FACILITY,
                          "measure": "ead", "key": "customer_id",
                          "period": LATEST, "top_n": 10})]))
    cases.append(_case(
        "rank-102", RANKING, "The largest customers by expected credit loss",
        [_turn("Show me the five largest customers by expected credit loss.",
               intent="ANALYSIS", computes=True, shape="ranking",
               grain="customer", top_n=5, period=LATEST,
               reference={"kind": "ranking", "dataset": IFRS9,
                          "measure": "total_ecl", "key": "customer_id",
                          "period": LATEST, "top_n": 5})]))
    cases.append(_case(
        "rank-103", RANKING, "A Stage 2 ranking",
        [_turn("Show me the ten largest Stage 2 customers by EAD.",
               intent="ANALYSIS", computes=True, shape="ranking",
               grain="customer", top_n=10, period=LATEST,
               filters={"ifrs9_stage": "2"},
               reference={"kind": "ranking", "dataset": FACILITY,
                          "measure": "ead", "key": "customer_id",
                          "period": LATEST, "top_n": 10,
                          "filters": [{"column": "ifrs9_stage",
                                       "value": "2"}]})]))
    return cases


# ============================================================ counting (7)


def _counting() -> list[dict[str, Any]]:
    cases = [
        _case("cnt-001", COUNTING, "How many customers are in Stage 2",
              [_turn("How many customers are in Stage 2?",
                     intent="ANALYSIS", computes=True, period=LATEST,
                     filters={"ifrs9_stage": "2"},
                     reference={"kind": "count", "dataset": FACILITY,
                                "key": "customer_id", "period": LATEST,
                                "filters": [{"column": "ifrs9_stage",
                                             "value": "2"}]})]),
        _case("cnt-002", COUNTING, "How many customers are in the book",
              [_turn("How many customers are in the book?",
                     intent="ANALYSIS", computes=True, period=LATEST,
                     reference={"kind": "count", "dataset": FACILITY,
                                "key": "customer_id", "period": LATEST})]),
        _case("cnt-003", COUNTING, "How many customers per sector",
              [_turn("How many customers are there by sector?",
                     intent="ANALYSIS", computes=True, dimension="sector",
                     period=LATEST,
                     reference={"kind": "count", "dataset": FACILITY,
                                "key": "customer_id", "period": LATEST,
                                "dimension": "sector"})]),
        _case("cnt-004", COUNTING, "How many facilities are in arrears",
              [_turn("How many facilities are in Stage 3?",
                     intent="ANALYSIS", computes=True, period=LATEST,
                     filters={"ifrs9_stage": "3"},
                     reference={"kind": "count", "dataset": FACILITY,
                                "key": "account_id", "period": LATEST,
                                "filters": [{"column": "ifrs9_stage",
                                             "value": "3"}]})]),
        _case("cnt-005", COUNTING, "Real Estate customer count",
              [_turn("How many Real Estate customers are there?",
                     intent="ANALYSIS", computes=True, period=LATEST,
                     filters={"sector": "Real Estate"},
                     reference={"kind": "count", "dataset": FACILITY,
                                "key": "customer_id", "period": LATEST,
                                "filters": [{"column": "sector",
                                             "value": "Real Estate"}]})]),
    ]
    return cases


# ====================================================== multi-domain (10)


def _cohorts() -> list[dict[str, Any]]:
    return [
        _case("coh-001", COHORT, "Rating downgrade with an ECL increase",
              [_turn("Which customers had a rating downgrade and an increase "
                     "in ECL over the latest year?",
                     intent="ANALYSIS", computes=True, shape="cohort",
                     grain="customer", period={"from": YEAR_AGO, "to": LATEST},
                     datasets=[RATINGS, IFRS9],
                     forbidden_methods=["top_deteriorating_borrowers",
                                        "portfolio_summary"],
                     reference={
                         "kind": "joined_cohort", "dataset": IFRS9,
                         "key": "customer_id", "opening": YEAR_AGO,
                         "closing": LATEST,
                         "conditions": [{"column": "total_ecl",
                                         "direction": "up"}],
                         # An annual rating cycle read as at Q2 2026 is the 2025
                         # cycle. Written down rather than derived, so the
                         # reference cannot agree with the runtime by sharing
                         # its reasoning.
                         "join": {"dataset": RATINGS, "key": "customer_id",
                                  "opening": "2024", "closing": "2025",
                                  "conditions": [{"column": "internal_grade",
                                                  "direction": "up",
                                                  "agg": "max"}]}})]),
        _case("coh-002", COHORT, "Worsening leverage, DSCR and rating",
              [_turn("Which customers have worsening leverage and declining "
                     "DSCR together with a rating downgrade?",
                     intent="ANALYSIS", computes=True, shape="cohort",
                     grain="customer", datasets=[RATINGS],
                     forbidden_methods=["portfolio_summary"],
                     reference={"kind": "cohort", "dataset": RATINGS,
                                "key": "customer_id", "opening": "2024",
                                "closing": "2025",
                                "conditions": [
                                    {"column": "net_leverage", "direction": "up"},
                                    {"column": "dscr", "direction": "down"},
                                    {"column": "internal_grade",
                                     "direction": "up"}]})]),
        _case("coh-003", COHORT, "ECL rose over the year",
              [_turn("Which customers had an increase in ECL over the latest year?",
                     intent="ANALYSIS", computes=True, shape="cohort",
                     grain="customer", period={"from": YEAR_AGO, "to": LATEST},
                     reference={"kind": "cohort", "dataset": IFRS9,
                                "key": "customer_id", "opening": YEAR_AGO,
                                "closing": LATEST,
                                "conditions": [{"column": "total_ecl",
                                                "direction": "up"}]})]),
        _case("coh-004", COHORT, "Worsening days past due over the year",
              [_turn("Which customers have worsening days past due over the "
                     "latest year?",
                     intent="ANALYSIS", computes=True, shape="cohort",
                     grain="customer", period={"from": YEAR_AGO, "to": LATEST},
                     reference={"kind": "cohort", "dataset": DELINQUENCY,
                                "key": "customer_id", "opening": YEAR_AGO,
                                "closing": LATEST,
                                "conditions": [{"column": "days_past_due",
                                                "direction": "up",
                                                "agg": "max"}]})]),
        _case("coh-005", COHORT, "Rating downgrades over the year",
              [_turn("Which customers were downgraded over the latest year?",
                     intent="ANALYSIS", computes=True, shape="cohort",
                     grain="customer", datasets=[RATINGS],
                     reference={"kind": "cohort", "dataset": RATINGS,
                                "key": "customer_id", "opening": "2024",
                                "closing": "2025",
                                "conditions": [{"column": "internal_grade",
                                                "direction": "up",
                                                "agg": "max"}]})]),
    ]


# ================================================== certified methods (5)


def _methods() -> list[dict[str, Any]]:
    return [
        _case("meth-001", METHOD, "The certified ECL movement",
              [_turn("How has ECL changed?", intent="ANALYSIS", computes=True,
                     certified="ecl_movement")]),
        _case("meth-002", METHOD, "The certified rating transition matrix",
              [_turn("Show me the rating transition matrix.",
                     intent="ANALYSIS", computes=True,
                     certified="rating_transition_matrix")]),
        _case("meth-003", METHOD, "The certified stage distribution",
              [_turn("Show me the stage distribution.", intent="ANALYSIS",
                     computes=True, certified="stage_distribution")]),
        _case("meth-004", METHOD, "The certified concentration view",
              [_turn("Where is the book most concentrated?",
                     intent="ANALYSIS", computes=True,
                     certified="sector_concentration")]),
        _case("meth-005", METHOD, "Which methods exist",
              [_turn("What analytical methods do you have?",
                     intent="METHOD_DISCOVERY", computes=False)]),
    ]


# ======================================================== refusals (6)


def _refusals() -> list[dict[str, Any]]:
    return [
        _case("amb-001", REFUSAL, "A question about nothing in the catalogue",
              [_turn("Who won the cup final?", clarification=True,
                     computes=False)]),
        _case("amb-002", REFUSAL, "A ratio the bank has not defined",
              [_turn("What is our net stable funding ratio?",
                     clarification=True, computes=False)]),
        _case("amb-003", REFUSAL, "A borrower that does not exist",
              [_turn("How much exposure do we have to Northwind Trading?",
                     clarification=True, computes=False)]),
        _case("amb-004", REFUSAL, "A referent with nothing behind it",
              [_turn("Which of these are Stage 2?", clarification=True,
                     computes=False)]),
        _case("amb-005", REFUSAL, "A measure that names no governed concept",
              [_turn("Show me the five largest.", clarification=True,
                     computes=False)]),
        _case("amb-006", REFUSAL, "A dataset nobody has published",
              [_turn("What data do you have about crypto exposures?",
                     computes=False)]),
    ]


# ======================================================== multi-turn (24)


def _threads() -> list[dict[str, Any]]:
    return [
        _case("mt-001", MULTITURN, "Catalogue walk: ratings, then its shape",
              [_turn("What data do you have about borrower ratings?",
                     intent="DATA_DISCOVERY", computes=False,
                     reference={"kind": "dataset", "dataset": RATINGS}),
               _turn("How many years of ratings history do you have?",
                     intent="DATA_QUALITY", computes=False,
                     reference={"kind": "dataset", "dataset": RATINGS}),
               _turn("What fields are available in the ratings data?",
                     intent="DATA_DICTIONARY", computes=False,
                     reference={"kind": "dataset", "dataset": RATINGS}),
               _turn("How is the ratings data connected to IFRS 9 data?",
                     intent="DATA_RELATIONSHIP", computes=False,
                     reference={"kind": "relationship", "source": RATINGS,
                                "target": IFRS9})]),

        _case("mt-002", MULTITURN, "Sector totals, cut, shared, re-measured",
              [_turn("What is total EAD by sector in the latest quarter?",
                     intent="ANALYSIS", computes=True, shape="aggregate",
                     dimension="sector", period=LATEST,
                     reference={"kind": "aggregate", "dataset": FACILITY,
                                "measure": "ead", "dimension": "sector",
                                "period": LATEST}),
               _turn("Show only the five largest sectors.",
                     intent="ANALYSIS", computes=True, action="MODIFY_PREVIOUS",
                     dimension="sector", top_n=5, period=LATEST,
                     reference={"kind": "aggregate", "dataset": FACILITY,
                                "measure": "ead", "dimension": "sector",
                                "period": LATEST, "top_n": 5}),
               _turn("Now show each one's percentage of total portfolio EAD.",
                     intent="ANALYSIS", computes=True, action="CONTINUE",
                     dimension="sector", top_n=5, period=LATEST,
                     reference={"kind": "aggregate", "dataset": FACILITY,
                                "measure": "ead", "dimension": "sector",
                                "period": LATEST, "top_n": 5}),
               # The cut from turn 2 is still in force: replacing the measure
               # does not put the other ten sectors back on screen.
               _turn("Replace EAD with number of customers.",
                     intent="ANALYSIS", computes=True, action="MODIFY_PREVIOUS",
                     dimension="sector", period=LATEST,
                     reference={"kind": "count", "dataset": FACILITY,
                                "key": "customer_id", "period": LATEST,
                                "dimension": "sector", "top_n": 5})]),

        _case("mt-003", MULTITURN, "Five customers, then their stage and ECL",
              [_turn("Show me the five largest Real Estate customers by EAD.",
                     intent="ANALYSIS", computes=True, shape="ranking",
                     grain="customer", top_n=5, period=LATEST,
                     filters={"sector": "Real Estate"},
                     forbidden_methods=["sector_concentration"],
                     reference={"kind": "ranking", "dataset": FACILITY,
                                "measure": "ead", "key": "customer_id",
                                "period": LATEST, "top_n": 5,
                                "filters": [{"column": "sector",
                                             "value": "Real Estate"}]}),
               _turn("Which of these are Stage 2 or Stage 3?",
                     intent="ANALYSIS", computes=True, action="CONTINUE",
                     population_from_previous=True, period=LATEST),
               _turn("Rank those by ECL instead.",
                     intent="ANALYSIS", computes=True, action="MODIFY_PREVIOUS",
                     population_from_previous=True, period=LATEST),
               _turn("Add their latest internal rating.",
                     intent="ANALYSIS", computes=True,
                     action="ENRICH_PREVIOUS",
                     population_from_previous=True,
                     datasets=[RATINGS])]),

        _case("mt-004", MULTITURN, "A cohort, narrowed, narrowed again, ranked",
              [_turn("Which customers had a rating downgrade and an increase "
                     "in ECL over the latest year?",
                     intent="ANALYSIS", computes=True, shape="cohort",
                     grain="customer", period={"from": YEAR_AGO, "to": LATEST},
                     datasets=[RATINGS, IFRS9]),
               _turn("Only show Contracting.", intent="ANALYSIS", computes=True,
                     action="MODIFY_PREVIOUS", filters={"sector": "Contracting"},
                     period={"from": YEAR_AGO, "to": LATEST}),
               _turn("Which of those also have worsening DPD?",
                     intent="ANALYSIS", computes=True, action="CONTINUE",
                     population_from_previous=True),
               _turn("Rank them by EAD.", intent="ANALYSIS", computes=True,
                     action="MODIFY_PREVIOUS",
                     population_from_previous=True)]),

        _case("mt-005", MULTITURN, "Financial deterioration, then the largest",
              [_turn("Which customers have worsening leverage and declining "
                     "DSCR together with a rating downgrade?",
                     intent="ANALYSIS", computes=True, shape="cohort",
                     grain="customer", datasets=[RATINGS]),
               _turn("Show me the ten largest by EAD.",
                     intent="ANALYSIS", computes=True, action="MODIFY_PREVIOUS",
                     population_from_previous=True, top_n=10),
               _turn("Which of those also had an increase in ECL?",
                     intent="ANALYSIS", computes=True, action="CONTINUE",
                     population_from_previous=True)]),

        _case("mt-006", MULTITURN, "A period settled once, reused after",
              [_turn("What is total EAD by sector in the latest quarter?",
                     intent="ANALYSIS", computes=True, dimension="sector",
                     period=LATEST,
                     reference={"kind": "aggregate", "dataset": FACILITY,
                                "measure": "ead", "dimension": "sector",
                                "period": LATEST}),
               _turn("And by region?", intent="ANALYSIS", computes=True,
                     action="CONTINUE", dimension="region", period=LATEST,
                     reference={"kind": "aggregate", "dataset": FACILITY,
                                "measure": "ead", "dimension": "region",
                                "period": LATEST})]),

        _case("mt-007", MULTITURN, "Metadata mid-analysis does not lose the thread",
              [_turn("Show me the five largest Contracting customers by EAD.",
                     intent="ANALYSIS", computes=True, top_n=5,
                     grain="customer", period=LATEST,
                     filters={"sector": "Contracting"},
                     reference={"kind": "ranking", "dataset": FACILITY,
                                "measure": "ead", "key": "customer_id",
                                "period": LATEST, "top_n": 5,
                                "filters": [{"column": "sector",
                                             "value": "Contracting"}]}),
               _turn("What fields are available in the ratings data?",
                     intent="DATA_DICTIONARY", computes=False,
                     action="NEW_REQUEST",
                     reference={"kind": "dataset", "dataset": RATINGS}),
               _turn("Rank those five by ECL instead.",
                     intent="ANALYSIS", computes=True,
                     population_from_previous=True)]),

        _case("mt-008", MULTITURN, "A new subject mid-thread is not a follow-up",
              [_turn("Show me the ten largest customers by EAD.",
                     intent="ANALYSIS", computes=True, top_n=10,
                     grain="customer", period=LATEST,
                     reference={"kind": "ranking", "dataset": FACILITY,
                                "measure": "ead", "key": "customer_id",
                                "period": LATEST, "top_n": 10}),
               _turn("How is the collateral register connected to the "
                     "facility book?",
                     intent="DATA_RELATIONSHIP", computes=False,
                     action="NEW_REQUEST",
                     reference={"kind": "relationship", "source": COLLATERAL,
                                "target": FACILITY})]),

        _case("mt-009", MULTITURN, "A referent that cannot be resolved is asked about",
              [_turn("What data do you have about covenants?",
                     intent="DATA_DISCOVERY", computes=False,
                     reference={"kind": "dataset", "dataset": COVENANTS}),
               _turn("Which of these are in breach?", clarification=True,
                     computes=False)]),

        _case("mt-010", MULTITURN, "Counting, then breaking the count down",
              [_turn("How many customers are in Stage 2?",
                     intent="ANALYSIS", computes=True, period=LATEST,
                     filters={"ifrs9_stage": "2"},
                     reference={"kind": "count", "dataset": FACILITY,
                                "key": "customer_id", "period": LATEST,
                                "filters": [{"column": "ifrs9_stage",
                                             "value": "2"}]}),
               _turn("Break that down by sector.", intent="ANALYSIS",
                     computes=True, action="CONTINUE", dimension="sector",
                     period=LATEST,
                     reference={"kind": "count", "dataset": FACILITY,
                                "key": "customer_id", "period": LATEST,
                                "dimension": "sector",
                                "filters": [{"column": "ifrs9_stage",
                                             "value": "2"}]})]),
    ]


def _period_cases() -> list[dict[str, Any]]:
    """The temporal vocabulary, which is where the product asked unnecessarily."""
    phrasings = (
        ("over the latest 6 months", "Q4 2025", LATEST),
        ("over the last 6 months", "Q4 2025", LATEST),
        ("over the last two years", "Q2 2024", LATEST),
        ("over the latest year", YEAR_AGO, LATEST),
        ("over the last year", YEAR_AGO, LATEST),
        ("over the past year", YEAR_AGO, LATEST),
        ("year on year", YEAR_AGO, LATEST),
        ("over the last 12 months", YEAR_AGO, LATEST),
        ("since last quarter", PREVIOUS, LATEST),
        ("quarter on quarter", PREVIOUS, LATEST),
    )
    cases = []
    for index, (phrase, opening, closing) in enumerate(phrasings, start=1):
        cases.append(_case(
            f"per-{index:03d}", COHORT,
            f"'{phrase}' resolves without asking",
            [_turn(f"Which customers had an increase in ECL {phrase}?",
                   intent="ANALYSIS", computes=True, shape="cohort",
                   grain="customer",
                   period={"from": opening, "to": closing},
                   clarification=False,
                   reference={"kind": "cohort", "dataset": IFRS9,
                              "key": "customer_id", "opening": opening,
                              "closing": closing,
                              "conditions": [{"column": "total_ecl",
                                              "direction": "up"}]})]))
    return cases


def _all() -> list[dict[str, Any]]:
    return [
        *_discovery(), *_dictionary(), *_coverage(), *_relationships(),
        *_aggregates(), *_rankings(), *_counting(), *_cohorts(),
        *_methods(), *_refusals(), *_threads(), *_period_cases(),
    ]


CASES: tuple[dict[str, Any], ...] = tuple(_all())

#: Ids, for the runner's sampling and for the audit record.
IDS: tuple[str, ...] = tuple(c["id"] for c in CASES)

BY_ID: dict[str, dict[str, Any]] = {c["id"]: c for c in CASES}


def by_family(family: str) -> list[dict[str, Any]]:
    """Cases in one of the three families the balanced sample draws from."""
    categories = FAMILIES.get(family, ())
    return [c for c in CASES if c["category"] in categories]


def family_of(case_id: str) -> str:
    """Which of the three families a case belongs to, or "" if it is unknown."""
    category = (BY_ID.get(case_id) or {}).get("category")
    for family, categories in FAMILIES.items():
        if category in categories:
            return family
    return ""


def turn_count() -> int:
    return sum(len(c["turns"]) for c in CASES)


__all__ = ["BY_ID", "CASES", "FAMILIES", "IDS", "by_family", "family_of",
           "turn_count"]
