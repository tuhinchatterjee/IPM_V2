"""
The RunPod analyst benchmark: Q01-Q15, as lab-authored METADATA.

One source for the question text, the analytical intent, the grain, the
relations and fields that matter, the filters the wording implies, and the
output contract. The ASSISTED_V1 packet is built from this plus the frozen
catalogue; the independent oracles (`benchmark_oracles.py`) implement the
same populations in pandas.

Nothing here is an answer: no expected numbers, no oracle values, no solution
SQL, no causes. A test enforces that.
"""

from __future__ import annotations

from dataclasses import dataclass, field

SUITE_VERSION = "runpod-a40-analyst-suite-v2"
DOMAIN = "corporate"
FAC, BOR = "corp_facility_quarter", "corp_borrower_quarter"


@dataclass(frozen=True)
class Question:
    qid: str
    text: str
    intent: tuple[str, ...]
    grain: str
    relations: tuple[str, ...]
    fields: dict[str, tuple[str, ...]]
    periods: tuple[str, ...]           # "latest", "previous", "last_4"
    filters: tuple[str, ...]
    joins: tuple[tuple[str, str], ...] = ()
    dimensions: tuple[str, ...] = ()
    metrics: tuple[str, ...] = ()
    ranking: str = ""
    reconciliation: str = ""
    chart: str = ""
    causal_limits: bool = False
    oracle_kind: str = "table"         # table | fact_set | review
    notes: tuple[str, ...] = field(default=())


_ID = ("borrower_id", "reporting_quarter")

QUESTIONS: tuple[Question, ...] = (
    Question(
        "Q01", "What is Stage 2 exposure by sector for the latest quarter?",
        ("aggregation", "segmentation"), "facility-quarter", (FAC,),
        {FAC: ("facility_id", "reporting_quarter", "stage", "sector",
               "ead_sar_mn")},
        ("latest",), ("stage = 2", "reporting_quarter = latest quarter"),
        dimensions=("sector",), metrics=("sum of ead_sar_mn",),
        ranking="identify the largest sector",
        reconciliation="sector values should sum to the Stage 2 total"),
    Question(
        "Q02", "How many Stage 2 facilities are there in each sector in the "
        "latest quarter, which three sectors have the most, and what is the "
        "total?",
        ("aggregation", "ranking"), "facility-quarter", (FAC,),
        {FAC: ("facility_id", "reporting_quarter", "stage", "sector")},
        ("latest",), ("stage = 2", "reporting_quarter = latest quarter"),
        dimensions=("sector",), metrics=("count of distinct facility_id",),
        ranking="top 3 sectors by facility count",
        reconciliation="per-sector counts must sum to the total count"),
    Question(
        "Q03", "How did Stage 2 EAD by sector change between the preceding "
        "quarter and the latest quarter? Which sectors increased and "
        "decreased the most?",
        ("comparison", "change analysis"), "facility-quarter", (FAC,),
        {FAC: ("facility_id", "reporting_quarter", "stage", "sector",
               "ead_sar_mn")},
        ("latest", "previous"), ("stage = 2 (in each quarter)",
                                 "reporting_quarter in (preceding, latest)"),
        dimensions=("sector",),
        metrics=("Stage 2 EAD in each quarter", "change = latest - preceding"),
        ranking="largest increases and largest decreases",
        reconciliation="sector changes should sum to the change in the "
                       "Stage 2 total"),
    Question(
        "Q04", "What drove the change in Stage 2 EAD in the latest quarter? "
        "Separate what the data shows from any explanation of causes.",
        ("driver analysis", "comparison"), "facility-quarter", (FAC, BOR),
        {FAC: ("facility_id", "borrower_id", "reporting_quarter", "stage",
               "sector", "ead_sar_mn"),
         BOR: ("borrower_id", "reporting_quarter", "rating_migration",
               "rating_driver")},
        ("latest", "previous"), ("reporting_quarter in (preceding, latest)",),
        joins=((FAC, BOR),),
        dimensions=("sector", "stage movement"),
        metrics=("Stage 2 EAD in each quarter",
                 "EAD of facilities entering / leaving Stage 2"),
        reconciliation="flows should bridge the Stage 2 total between the "
                       "two quarters",
        causal_limits=True, oracle_kind="fact_set"),
    Question(
        "Q05", "Which borrowers were downgraded in the latest quarter? Give "
        "each one's prior and current rating, sector and EAD.",
        ("filtering", "listing"), "borrower-quarter", (BOR, FAC),
        {BOR: ("borrower_id", "borrower_name", "reporting_quarter",
               "sector", "rating_previous", "rating_current",
               "rating_migration", "rating_notches_moved"),
         FAC: ("facility_id", "borrower_id", "reporting_quarter",
               "ead_sar_mn")},
        ("latest",), ("rating_migration = 'DOWNGRADE' (equivalently "
                      "rating_notches_moved < 0)",
                      "reporting_quarter = latest quarter"),
        joins=((FAC, BOR),),
        dimensions=("borrower",),
        metrics=("prior rating", "current rating", "sector",
                 "borrower EAD = sum of its facilities' ead_sar_mn"),
        reconciliation="the downgraded population count"),
    Question(
        "Q06", "What is ECL by IFRS 9 stage and sector in the latest quarter? "
        "Show it as a chart.",
        ("aggregation", "cross-tabulation"), "facility-quarter", (FAC,),
        {FAC: ("facility_id", "reporting_quarter", "stage", "sector",
               "ecl_sar_mn")},
        ("latest",), ("reporting_quarter = latest quarter",),
        dimensions=("stage", "sector"), metrics=("sum of ecl_sar_mn",),
        reconciliation="stage x sector cells must sum to stage totals, "
                       "sector totals and the portfolio total",
        chart="a chart of ECL by stage and sector"),
    Question(
        "Q07", "Show the IFRS 9 stage migration from the preceding quarter "
        "to the latest quarter. Where were the largest moves into Stage 2?",
        ("migration", "transition matrix"), "facility-quarter", (FAC,),
        {FAC: ("facility_id", "reporting_quarter", "stage", "sector",
               "ead_sar_mn")},
        ("latest", "previous"), ("reporting_quarter in (preceding, latest)",),
        joins=((FAC, FAC),),
        dimensions=("stage in preceding quarter", "stage in latest quarter"),
        metrics=("facility count", "EAD (latest quarter)"),
        ranking="largest moves into Stage 2 (by sector)",
        reconciliation="matrix cells must sum to the facilities present in "
                       "both quarters; state how new and exited facilities "
                       "are treated",
        notes=("Compare a facility with ITSELF: pair rows on facility_id "
               "across the two reporting quarters.",)),
    Question(
        "Q08", "Who are the top 10 Stage 2 borrowers by EAD in the latest "
        "quarter, with their sector and rating?",
        ("ranking",), "borrower-quarter", (FAC, BOR),
        {FAC: ("facility_id", "borrower_id", "reporting_quarter", "stage",
               "ead_sar_mn"),
         BOR: ("borrower_id", "borrower_name", "reporting_quarter",
               "sector", "rating_current")},
        ("latest",), ("stage = 2", "reporting_quarter = latest quarter"),
        joins=((FAC, BOR),),
        dimensions=("borrower",),
        metrics=("borrower Stage 2 EAD = sum of the borrower's Stage 2 "
                 "facilities' ead_sar_mn",),
        ranking="top 10 by Stage 2 EAD, descending"),
    Question(
        "Q09", "Which sectors are deteriorating? Use Stage 2 EAD, ECL and "
        "the borrower and facility signals available.",
        ("comparison", "multi-metric assessment"), "sector", (FAC, BOR),
        {FAC: ("facility_id", "reporting_quarter", "stage", "sector",
               "ead_sar_mn", "ecl_sar_mn", "dpd_days"),
         BOR: ("borrower_id", "reporting_quarter", "sector",
               "rating_migration", "watchlist_flag")},
        ("latest", "previous"), ("reporting_quarter in (preceding, latest)",),
        dimensions=("sector",),
        metrics=("Stage 2 EAD change", "ECL change",
                 "downgraded borrowers", "watch-list borrowers"),
        causal_limits=True, oracle_kind="fact_set",
        notes=("State each measurable component separately; any overall "
               "judgement is interpretation.",)),
    Question(
        "Q10", "Write an executive summary of corporate credit "
        "deterioration in the latest quarter.",
        ("executive synthesis",), "portfolio", (FAC, BOR),
        {FAC: ("facility_id", "borrower_id", "reporting_quarter", "stage",
               "sector", "ead_sar_mn", "ecl_sar_mn"),
         BOR: ("borrower_id", "reporting_quarter", "rating_migration")},
        ("latest", "previous"), ("reporting_quarter in (preceding, latest)",),
        joins=((FAC, BOR),),
        metrics=("Stage 2 and Stage 3 EAD", "ECL", "sector concentration",
                 "stage migration", "downgraded borrowers"),
        causal_limits=True, oracle_kind="fact_set"),
    Question(
        "Q11", "What is total EAD by sector in the latest quarter across all "
        "stages, and what is the portfolio total?",
        ("aggregation",), "facility-quarter", (FAC,),
        {FAC: ("facility_id", "reporting_quarter", "sector", "ead_sar_mn")},
        ("latest",), ("reporting_quarter = latest quarter",
                      "all stages (no stage filter)"),
        dimensions=("sector",), metrics=("sum of ead_sar_mn",),
        reconciliation="sector totals must sum to the portfolio total"),
    Question(
        "Q12", "What are Stage 3 EAD and ECL by sector in the latest "
        "quarter, and where are they most concentrated?",
        ("aggregation", "concentration"), "facility-quarter", (FAC,),
        {FAC: ("facility_id", "reporting_quarter", "stage", "sector",
               "ead_sar_mn", "ecl_sar_mn")},
        ("latest",), ("stage = 3", "reporting_quarter = latest quarter"),
        dimensions=("sector",),
        metrics=("sum of ead_sar_mn", "sum of ecl_sar_mn"),
        ranking="largest concentrations",
        reconciliation="sector values must sum to the Stage 3 totals"),
    Question(
        "Q13", "Where are the largest Stage 2 concentrations by sector and by "
        "borrower in the latest quarter, as shares of total Stage 2 EAD?",
        ("concentration", "ranking"), "facility-quarter", (FAC,),
        {FAC: ("facility_id", "borrower_id", "borrower_name",
               "reporting_quarter", "stage", "sector", "ead_sar_mn")},
        ("latest",), ("stage = 2", "reporting_quarter = latest quarter"),
        dimensions=("sector", "borrower"),
        metrics=("Stage 2 EAD", "share of total Stage 2 EAD"),
        ranking="top sectors and top borrowers by Stage 2 EAD",
        reconciliation="shares are of the same Stage 2 total; sector "
                       "values sum to it"),
    Question(
        "Q14", "Which borrowers moved into Stage 3 in the latest quarter? "
        "Give their EAD, ECL, sector and rating.",
        ("migration", "listing"), "borrower-quarter", (FAC, BOR),
        {FAC: ("facility_id", "borrower_id", "reporting_quarter", "stage",
               "ead_sar_mn", "ecl_sar_mn"),
         BOR: ("borrower_id", "borrower_name", "reporting_quarter",
               "sector", "rating_current")},
        ("latest", "previous"), ("a facility is Stage 3 in the latest "
                                 "quarter and was Stage 1 or 2 in the "
                                 "preceding quarter",),
        joins=((FAC, FAC), (FAC, BOR)),
        dimensions=("borrower",),
        metrics=("EAD and ECL of the facilities that moved into Stage 3",),
        notes=("A borrower 'moved into Stage 3' when at least one of its "
               "facilities did.",)),
    Question(
        "Q15", "How risky is the corporate book right now?",
        ("executive synthesis", "open question"), "portfolio", (FAC, BOR),
        {FAC: ("facility_id", "reporting_quarter", "stage", "sector",
               "ead_sar_mn", "ecl_sar_mn"),
         BOR: ("borrower_id", "reporting_quarter", "rating_migration",
               "watchlist_flag")},
        ("latest",), ("reporting_quarter = latest quarter",),
        causal_limits=True, oracle_kind="review",
        notes=("Deliberately open: state the measures you use and your "
               "assumptions.",)),
)

BY_ID = {q.qid: q for q in QUESTIONS}


def get(qid: str) -> Question:
    return BY_ID[qid]


def for_text(text: str) -> Question | None:
    t = " ".join(str(text or "").split()).casefold()
    return next((q for q in QUESTIONS
                 if " ".join(q.text.split()).casefold() == t), None)
