"""
Business concepts, and which governed field actually supplies them.

The gap this closes
-------------------
A credit officer asks about "ECL", "the rating", "exposure". None of those is a
column. Several of them exist in more than one governed dataset with genuinely
different meanings — `portfolio_facility.ead` is the operational exposure the
book carries, `ifrs9_staging.ead` is the figure the impairment calculation was
run on, and answering an impairment question from the operational number is the
kind of mistake that survives every review because both numbers are correct.

So a concept is resolved rather than guessed:

  1. the phrase is matched to a concept — "ECL", "impairment", "provision" all
     mean the same thing;
  2. the concept's candidate fields are read from the governed catalogue, so a
     concept can never resolve to a field the data does not have;
  3. a qualifier in the question picks between candidates where one exists —
     "regulatory EAD" is not "outstanding exposure";
  4. where no qualifier settles it, the catalogue's own authority metadata
     decides, and the choice is RECORDED so the answer can say which definition
     it used;
  5. where authority does not settle it either, CreditProbe asks. A confident
     figure computed from the wrong definition of exposure is the exact failure
     this product exists to prevent.

Nothing here reads data. It reads the catalogue and returns names.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

FACILITY = "portfolio_facility"
IFRS9 = "ifrs9_staging"
RATINGS = "customer_ratings"
DELINQUENCY = "facility_delinquency"
COVENANTS = "covenant_tests"
MACRO = "macro_saudi"
MEMOS = "credit_memo_signals"
FINANCIALS = "borrower_financials"
LIMITS = "facility_limits"
COLLATERAL = "collateral_register"
LIQUIDITY = "liquidity_buffer"
#: The Borrower 360 book. B44: a second portfolio in the same catalogue, and
#: the two share almost every word. The concepts below are the ones that
#: belong ONLY to it - a question that names a group structure, a beneficial
#: owner, a supply chain or a network position is asking about this book and
#: nothing in the credit book can answer it.
GROUPS = "corporate_connected_groups"
GRAPH_DQ = "corporate_graph_dq"
BORROWER_360 = "corporate_borrower_360"
RECOVERIES = "recoveries"
APPETITE = "risk_appetite_limits"
PD_MODEL = "pd_model_performance"
TRANSITIONS = "rating_transitions"


@dataclass(frozen=True)
class Candidate:
    """One governed field that can supply a concept."""

    dataset: str
    field: str
    #: Why this one rather than the other. Shown when the choice is explained.
    definition: str
    #: The word in a question that selects this candidate over its rivals.
    qualifiers: tuple[str, ...] = ()
    #: The candidate used when nothing in the question chooses.
    is_default: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {"dataset": self.dataset, "field": self.field,
                "definition": self.definition,
                "qualifiers": list(self.qualifiers), "is_default": self.is_default}


@dataclass(frozen=True)
class Concept:
    """One thing a credit officer talks about."""

    id: str
    label: str
    #: What people call it. Matched longest-first so "expected credit loss"
    #: beats "credit".
    pattern: str
    candidates: tuple[Candidate, ...]
    #: True where a HIGHER number is worse. Decides which way "deteriorated"
    #: points, and getting it wrong inverts the answer.
    higher_is_worse: bool = True
    #: An ordinal scale rather than a measure: movement is counted in steps,
    #: never averaged, and rolled up by its worst value.
    is_ordinal: bool = False
    #: A governed category rather than a quantity. Compared by equality and
    #: never differenced — subtracting one sentiment from another is not a
    #: smaller number, it is a type error waiting for a production question.
    is_categorical: bool = False
    #: A governed STATE a borrower is either in or not — on the watchlist, in
    #: covenant breach. Naming one in a question asserts it: "which borrowers
    #: are on watchlist" is a condition, not a column to report. Distinct from
    #: `is_categorical`, which has several values and needs one to be named,
    #: and from a measure, which needs a direction or a threshold before it
    #: becomes a condition at all. Without this distinction a state named in a
    #: question resolved to a field and then produced no predicate, which is
    #: how "Stage 2 borrowers not on watchlist" came back as every Stage 2
    #: borrower.
    is_state: bool = False
    #: The values a polarity word maps onto, for a categorical concept.
    polarity: tuple[tuple[str, str], ...] = ()
    unit: str = ""

    def default_candidate(self) -> Candidate:
        for candidate in self.candidates:
            if candidate.is_default:
                return candidate
        return self.candidates[0]


def _c(dataset: str, field_: str, definition: str, *qualifiers: str,
       default: bool = False) -> Candidate:
    return Candidate(dataset=dataset, field=field_, definition=definition,
                     qualifiers=tuple(qualifiers), is_default=default)


#: The concepts CreditProbe understands, and where each one lives.
#:
#: Deliberately hand-written. A concept map derived from column names would map
#: "ead" to every dataset carrying a column of that name and would have no
#: opinion about which one an impairment question means — which is the entire
#: value of having one.
CONCEPTS: tuple[Concept, ...] = (
    Concept(
        id="ecl", label="expected credit loss",
        pattern=r"expected credit loss|\becl\b|impairment|provision(?:ing)?",
        unit="SAR mn",
        candidates=(
            _c(IFRS9, "total_ecl",
               "The impairment charge as the IFRS 9 calculation booked it. The "
               "accounting figure, and the one an impairment question means.",
               "ifrs9", "ifrs 9", "accounting", "booked", "impairment",
               default=True),
            _c(FACILITY, "total_ecl",
               "The ECL carried on the facility position. The same measure "
               "read from the operational book rather than the staging run.",
               "operational", "facility", "portfolio"),
        )),
    Concept(
        id="ecl_coverage", label="ECL coverage",
        pattern=r"ecl coverage|coverage ratio|provision coverage",
        higher_is_worse=False, unit="%",
        candidates=(
            _c(IFRS9, "ecl_coverage_pct", "ECL as a percentage of exposure at "
               "default, from the staging run.", default=True),
            _c(FACILITY, "ecl_coverage_pct",
               "Coverage as carried on the facility position."),
        )),
    Concept(
        id="ead", label="exposure at default",
        pattern=r"exposure at default|\bead\b",
        unit="SAR mn",
        candidates=(
            _c(FACILITY, "ead",
               "CCF-adjusted exposure at default on the facility position — "
               "the operational figure the book is managed on.",
               "outstanding", "operational", "facility", "portfolio", "managed",
               default=True),
            _c(IFRS9, "ead",
               "Exposure at default as the impairment calculation used it. The "
               "regulatory and accounting figure.",
               "regulatory", "ifrs9", "ifrs 9", "accounting", "impairment"),
        )),
    Concept(
        id="exposure", label="drawn exposure",
        pattern=r"drawn exposure|outstanding balance|\bexposure\b(?! at default)",
        unit="SAR mn",
        candidates=(
            _c(FACILITY, "exposure",
               "Drawn, outstanding exposure on the facility position.",
               "outstanding", "drawn", "operational", default=True),
            _c(FACILITY, "ead",
               "CCF-adjusted exposure at default, which includes an allowance "
               "for undrawn commitments.", "at default", "ccf", "committed"),
            _c(IFRS9, "ead",
               "Exposure as the impairment calculation used it.",
               "regulatory", "ifrs9", "ifrs 9"),
        )),
    Concept(
        id="rating", label="internal rating",
        # Plurals included. "Which borrowers have unchanged RATINGS" resolved
        # to nothing at all, so the condition on the rating was not dropped by
        # the planner — it never existed, and the answer was about PD alone.
        pattern=r"internal ratings?|risk ratings?|\bratings?\b|\bgrades?\b"
                r"|\bnotch(?:es)?\b|downgrad\w*|upgrad\w*",
        is_ordinal=True, unit="notches",
        candidates=(
            _c(RATINGS, "internal_grade",
               "The grade awarded at the customer's annual rating cycle. One "
               "to ten, ten being default. The authoritative rating of a "
               "borrower.",
               "customer", "obligor", "borrower", "annual", "cycle",
               default=True),
            _c(FACILITY, "internal_grade",
               "The grade carried on the facility position at the reporting "
               "date. The same scale, read from the quarterly book.",
               "facility", "account", "quarterly", "snapshot"),
        )),
    Concept(
        id="stage", label="IFRS 9 stage",
        pattern=r"ifrs\s*9\s*stage|\bstage\s*[123]?\b|staging",
        is_ordinal=True,
        candidates=(
            _c(IFRS9, "ifrs9_stage",
               "The staging decision from the IFRS 9 assessment.", default=True),
            _c(FACILITY, "ifrs9_stage",
               "The stage carried on the facility position."),
        )),
    Concept(
        id="dpd", label="days past due",
        pattern=r"days past due|\bdpd\b|arrears|delinquen|past due|overdue",
        unit="days",
        candidates=(
            _c(DELINQUENCY, "days_past_due",
               "Days the oldest unpaid amount has been outstanding, from the "
               "arrears and collections record.",
               "arrears", "collections", "delinquency", default=True),
            _c(FACILITY, "dpd_days",
               "Days past due as carried on the facility position."),
        )),
    Concept(
        id="pd", label="probability of default",
        pattern=r"\bpd\b|probability of default",
        unit="%",
        candidates=(
            _c(IFRS9, "pd_12m_pct",
               "The twelve-month PD the staging assessment used.", default=True),
            _c(FACILITY, "pd_12m_pct", "The PD carried on the facility position."),
            _c(RATINGS, "pd_12m_pct", "The PD implied by the customer's grade.",
               "customer", "rating"),
        )),
    Concept(
        id="lgd", label="loss given default",
        pattern=r"\blgd\b|loss given default", unit="%",
        candidates=(
            _c(IFRS9, "lgd_pct", "LGD as the impairment calculation used it.",
               default=True),
            _c(FACILITY, "lgd_pct", "LGD carried on the facility position."),
        )),
    Concept(
        id="leverage", label="net leverage",
        pattern=r"leverage|gearing|debt to ebitda|net debt", unit="x",
        candidates=(
            _c(RATINGS, "net_leverage",
               "Net debt to EBITDA from the financials behind the rating "
               "cycle.", default=True),
        )),
    Concept(
        id="dscr", label="debt service coverage",
        # "debt-service capacity" is what a credit officer says for this, and
        # it resolved to nothing: the pattern required the word "coverage" or
        # "ratio". "Who has both rising utilisation and weakening debt-service
        # capacity?" therefore ran on utilisation alone, and the answer said
        # so about neither.
        pattern=(r"\bdscr\b|debt.service (?:cover(?:age)?|ratio|capacity|"
                 r"headroom|ability)|(?:capacity|ability) to service"),
        unit="x", higher_is_worse=False,
        candidates=(
            _c(RATINGS, "dscr",
               "EBITDA to total debt service — interest plus scheduled "
               "principal — from the financials behind the rating cycle. The "
               "credit-analysis figure, at customer level and annual.",
               "customer", "annual", "financials", "credit", default=True),
            _c(FACILITY, "dscr",
               "Debt service cover as carried on the facility position each "
               "quarter. The operational figure, at facility level.",
               "facility", "quarterly", "operational", "book"),
        )),
    Concept(
        id="interest_cover", label="interest coverage",
        pattern=r"interest cover(?:age)?|ebitda to interest", unit="x",
        higher_is_worse=False,
        candidates=(_c(RATINGS, "interest_coverage",
                       "EBITDA to interest from the rating cycle financials.",
                       default=True),)),
    Concept(
        id="margin", label="EBITDA margin",
        pattern=r"ebitda margin|profitability margin", unit="%",
        higher_is_worse=False,
        candidates=(_c(RATINGS, "ebitda_margin_pct",
                       "EBITDA as a share of revenue, from the rating cycle.",
                       default=True),)),
    Concept(
        id="covenant_headroom", label="covenant headroom",
        pattern=r"covenant headroom|headroom|covenant breach|covenant",
        higher_is_worse=False, unit="%",
        candidates=(
            _c(COVENANTS, "headroom_pct",
               "Distance to the covenant threshold, per covenant tested.",
               "covenant", "breach", "test", default=True),
            _c(FACILITY, "covenant_headroom_pct",
               "Covenant headroom as summarised on the facility position."),
        )),
    Concept(
        id="covenant_breach", label="covenant breach",
        # Deliberately ahead of `covenant_headroom` in the file, and matching
        # only the BREACH wording: headroom is a distance and breach is a
        # state, and reading "which borrowers are in covenant breach" as a
        # question about headroom gave an ordering where a condition was asked
        # for.
        pattern=r"covenant breach(?:es|ed)?|breached? (?:a )?covenants?|"
                r"in breach of (?:a )?covenants?|covenant violation",
        is_state=True,
        candidates=(
            _c(COVENANTS, "breached",
               "Whether the covenant test failed at this reporting date.",
               "covenant", "test", default=True),
        )),
    Concept(
        id="watchlist", label="watchlist",
        pattern=r"watch ?list(?:ed)?|on watch\b|under watch\b",
        is_state=True,
        candidates=(
            _c(FACILITY, "watchlist",
               "Whether the facility is flagged onto the credit watchlist at "
               "the reporting date.", "facility", "portfolio", default=True),
            _c(DELINQUENCY, "watchlist",
               "The watchlist flag as the collections book carries it.",
               "collections", "delinquency", "arrears"),
        )),
    Concept(
        id="liquidity", label="liquidity cover",
        pattern=r"liquidity(?: cover(?:age)?| buffer| position| headroom)?|"
                r"cash cover(?:age)?|months of cover",
        higher_is_worse=False, unit="months",
        candidates=(
            _c(LIQUIDITY, "liquidity_coverage_months",
               "How many months of debt service the borrower's cash and "
               "undrawn committed lines would meet.", default=True),
            _c(LIQUIDITY, "liquidity_buffer",
               "Cash plus undrawn committed facilities, as an amount.",
               "buffer", "amount", "absolute"),
        )),
    Concept(
        id="utilisation", label="utilisation",
        pattern=r"utilisation|utilization|drawn percentage", unit="%",
        candidates=(_c(FACILITY, "utilisation_pct",
                       "Drawn exposure as a share of the limit.", default=True),)),
    Concept(
        id="macro_growth", label="economic growth",
        pattern=r"gdp|economic growth|macro(?:economic)?\s*(?:environment|conditions)?",
        higher_is_worse=False, unit="%",
        candidates=(
            _c(MACRO, "real_gdp_growth_pct",
               "Real GDP growth for the quarter.", "gdp", "growth", default=True),
            _c(MACRO, "credit_cycle_factor",
               "The credit cycle factor derived from the macro series.",
               "cycle", "credit cycle"),
        )),
    Concept(
        id="macro_cycle", label="credit cycle",
        pattern=r"credit cycle|cycle factor|macro environment",
        higher_is_worse=False,
        candidates=(_c(MACRO, "credit_cycle_factor",
                       "The credit cycle factor derived from the macro series. "
                       "Positive is a supportive environment.", default=True),)),
    Concept(
        id="sentiment", label="credit file sentiment",
        pattern=r"sentiment|qualitative|credit file|memo|commentary|narrative",
        higher_is_worse=False, is_categorical=True,
        polarity=(("negative", "negative"), ("adverse", "negative"),
                  ("positive", "positive"), ("favourable", "positive"),
                  ("favorable", "positive")),
        candidates=(_c(MEMOS, "sentiment",
                       "The sentiment of the credit file note, as a structured "
                       "signal — negative, neutral or positive. Never the text "
                       "itself.", default=True),)),
    Concept(
        id="signal_strength", label="credit file signal strength",
        pattern=r"signal strength|concern level|red flag",
        candidates=(_c(MEMOS, "signal_strength_pct",
                       "How strong the structured signal from the credit file "
                       "is.", default=True),)),

    # ------------------------------------------- the corporate graph. B44.
    #
    # The three GROUP concepts are separate on purpose and are the reason
    # this block exists at all. "The group" is the single most overloaded
    # word in corporate credit: it means the economics to a shareholder, the
    # decision-making to a governance reviewer, and the obligor to a
    # regulator, and those are three different sets of companies. A concept
    # map that answered "group" with one column would be confidently wrong
    # two times in three.
    Concept(
        id="connected_group", label="connected counterparty group",
        pattern=(r"connected (?:counterpart(?:y|ies)|group)|obligor group|"
                 r"group of connected|single risk"),
        is_categorical=True,
        candidates=(
            _c(GROUPS, "connected_group_id",
               "The candidate obligor group: control components, then "
               "validated economic interdependence merged in. A CANDIDATE "
               "for assessment under the institution's own criteria, never a "
               "determination.",
               "connected", "obligor", "counterparty", default=True),
            _c(GROUPS, "group_name",
               "The same group by its readable name - its largest member.",
               "name", "called", "named"),
        )),
    Concept(
        id="control_group", label="control group",
        pattern=r"control(?:ling)? group|controlled by|who controls|controller",
        is_categorical=True,
        candidates=(_c(GROUPS, "control_group_id",
                       "The control bloc, from binary closure over VOTING "
                       "rights. NOT proportional ownership: 51% of 51% is "
                       "26% of the economics and 100% of the control.",
                       default=True),)),
    Concept(
        id="ownership_group", label="effective ownership group",
        pattern=(r"ownership group|effective ownership|beneficial ownership "
                 r"group|economic (?:ownership|interest)"),
        is_categorical=True,
        candidates=(_c(GROUPS, "effective_ownership_group_id",
                       "The group formed by integrated ownership at or above "
                       "25%, solved as A(I-A)^-1. The ECONOMICS, not the "
                       "control.", default=True),)),
    Concept(
        id="group_size", label="connected group size",
        pattern=r"group size|members? (?:of|in) the group|how (?:many|large)",
        unit="count",
        candidates=(_c(GROUPS, "connected_group_size",
                       "Members of the connected counterparty group.",
                       default=True),)),
    Concept(
        id="group_role", label="group role",
        pattern=r"group role|parent|subsidiar(?:y|ies)|affiliate|standalone",
        is_categorical=True,
        polarity=(("parent", "PARENT"), ("subsidiary", "SUBSIDIARY"),
                  ("affiliate", "AFFILIATE"), ("standalone", "STANDALONE")),
        candidates=(_c(GROUPS, "group_role",
                       "PARENT, SUBSIDIARY, AFFILIATE or STANDALONE, decided "
                       "over the CORPORATE members of the control bloc. A "
                       "company owned by its founder is standalone, not a "
                       "subsidiary.", default=True),)),
    Concept(
        id="group_exposure", label="connected group exposure",
        pattern=r"group exposure|exposure to the group|aggregate exposure",
        unit="SAR millions",
        candidates=(_c(GROUPS, "group_exposure",
                       "Total EAD across the connected group's members - the "
                       "figure the group limit is measured against.",
                       default=True),)),
    Concept(
        id="group_utilisation", label="group limit utilisation",
        pattern=(r"group (?:limit )?utilisation|group utilization|"
                 r"against the group limit|large exposure"),
        unit="%",
        candidates=(_c(GROUPS, "group_utilisation_pct",
                       "The group's exposure over the eligible capital "
                       "reference. The threshold it is compared against is an "
                       "UNVERIFIED REGULATORY PARAMETER.", default=True),)),
    Concept(
        id="ubo", label="ultimate beneficial owner",
        pattern=(r"ultimate beneficial owner|\bubo\b|beneficial owner|"
                 r"who (?:really )?owns|ultimate owner"),
        # Zero identified owners is the opaque structure. More of them is
        # not worse, so the direction of concern points down.
        higher_is_worse=False, unit="count",
        candidates=(_c(GROUPS, "ubo_count",
                       "Natural persons whose INTEGRATED ownership reaches "
                       "25%. Counted through the chain, not from direct "
                       "shareholdings - which is the whole reason a pyramid "
                       "is built.", default=True),)),
    Concept(
        id="director_count", label="directors",
        pattern=r"directors?|board (?:members?|seats?)|directorships?",
        unit="count",
        candidates=(_c(GROUPS, "director_count",
                       "Board seats held at this borrower, as filed.",
                       default=True),)),
    Concept(
        id="supplier_count", label="suppliers",
        pattern=r"suppliers?|supply chain|upstream",
        unit="count",
        candidates=(_c(GROUPS, "supplier_count",
                       "Counterparties supplying this borrower. A supply "
                       "relationship never forms a regulatory group on its "
                       "own.", default=True),)),
    Concept(
        id="customer_count", label="customers of the borrower",
        pattern=r"customers of|buyers?|downstream|who (?:it|they) supply",
        unit="count",
        candidates=(_c(GROUPS, "customer_count",
                       "Counterparties this borrower supplies.",
                       default=True),)),
    Concept(
        id="guarantee_links", label="guarantee links",
        pattern=r"guarantees?|guarantor|stands behind|surety",
        unit="count",
        candidates=(_c(GROUPS, "guarantee_links",
                       "Guarantees given or received, over reified Guarantee "
                       "nodes - one guarantee can cover several facilities of "
                       "several borrowers.", default=True),)),
    Concept(
        id="network_links", label="network links",
        pattern=r"network links?|financial claims?|exposed to whom",
        unit="count",
        candidates=(_c(GROUPS, "exposure_network_links",
                       "Financial claims to or from this borrower.",
                       default=True),)),
    Concept(
        id="network_risk_score", label="network risk score",
        pattern=(r"network risk score|network score|network risk|"
                 r"structural risk"),
        unit="index",
        candidates=(_c(GROUPS, "network_risk_score",
                       "A RELATIVE RANKING of the borrower's position in the "
                       "relationship graph. NOT a probability, NOT a PD, NOT "
                       "a rating, NOT an IFRS 9 stage and NOT an expected "
                       "credit loss.", default=True),)),
    Concept(
        id="debtrank", label="DebtRank impact",
        pattern=(r"debtrank|debt rank|contagion|network impact|"
                 r"take (?:the )?(?:most of the )?network down|systemic"),
        unit="ratio",
        candidates=(_c(GROUPS, "debtrank_impact",
                       "How much of the network's value is impaired when this "
                       "borrower is shocked. Network analytics and early "
                       "warning - NOT an expected credit loss and NOT a "
                       "capital methodology.", default=True),)),
    Concept(
        id="centrality", label="network centrality",
        pattern=r"centrality|most central|pagerank|page rank|transmits?",
        unit="ratio",
        candidates=(
            _c(GROUPS, "pagerank_transmits",
               "Forward PageRank: how central the borrower is as a "
               "TRANSMITTER - who others are exposed to.",
               "transmit", "transmits", "spread", "forward", default=True),
            _c(GROUPS, "pagerank_hurt",
               "Reverse PageRank: how exposed the borrower is to "
               "transmission from others.",
               "hurt", "exposed", "reverse", "receive"),
            _c(GROUPS, "betweenness",
               "Betweenness: whether the borrower sits on the paths between "
               "others - a conduit.",
               "betweenness", "conduit", "between", "bridge"),
        )),
    Concept(
        id="network_community", label="network community",
        pattern=r"network community|cluster|community detection|louvain",
        # An arbitrary integer label. Community 7 is not worse than
        # community 3, and there is no direction to record.
        higher_is_worse=False, is_categorical=True,
        candidates=(_c(GROUPS, "louvain_community",
                       "A modularity community over the exposure network. "
                       "Descriptive only - NOT a group in any legal, economic "
                       "or regulatory sense.", default=True),)),
    Concept(
        id="graph_confidence", label="graph evidence confidence",
        pattern=(r"graph confidence|evidence confidence|how (?:reliable|well "
                 r"evidenced)|weakest evidence"),
        higher_is_worse=False, unit="ratio",
        candidates=(
            _c(GROUPS, "graph_confidence",
               "The WEAKEST assertion on the evidence path. A conclusion is "
               "exactly as good as the worst assertion it depends on.",
               "weakest", "worst", "minimum", default=True),
            _c(GROUPS, "relationship_confidence",
               "The MEAN confidence of the edges touching this borrower - how "
               "well evidenced it is overall.",
               "mean", "average", "overall"),
        )),
    Concept(
        id="graph_quality", label="graph data quality",
        pattern=(r"graph (?:data )?quality|can we trust the graph|"
                 r"graph dq|relationship data quality"),
        is_categorical=True,
        polarity=(("degraded", "DEGRADED"), ("insufficient", "INSUFFICIENT"),
                  ("ok", "OK")),
        candidates=(_c(GROUPS, "graph_dq_status",
                       "OK, DEGRADED or INSUFFICIENT for THIS borrower. A "
                       "portfolio-wide flag does not reach this field - a "
                       "status that reads the same for every row tells a "
                       "reviewer nothing.", default=True),)),
    Concept(
        id="dq_issue_count", label="data quality issues",
        pattern=r"data.quality issues?|dq issues?|open issues?",
        unit="count",
        candidates=(_c(GROUPS, "dq_issue_count",
                       "Entity-scoped data-quality issues naming this "
                       "borrower.", default=True),)),
    Concept(
        id="dq_check_status", label="data quality check verdict",
        pattern=r"check (?:failed|passed|status)|quality verdict|rejected check",
        is_categorical=True,
        polarity=(("pass", "PASS"), ("passed", "PASS"), ("flag", "FLAG"),
                  ("flagged", "FLAG"), ("reject", "REJECT"),
                  ("rejected", "REJECT"), ("failed", "REJECT")),
        candidates=(_c(GRAPH_DQ, "status",
                       "PASS, FLAG or REJECT for one graph data-quality "
                       "check. A REJECT blocks the computation that depends "
                       "on it.", default=True),)),
    Concept(
        id="snapshot_validation", label="borrower validation status",
        pattern=(r"validation status|snapshot validation|"
                 r"passed with issues"),
        is_categorical=True,
        candidates=(_c(GROUPS, "snapshot_validation_status",
                       "PASSED, PASSED WITH ISSUES or FAILED for this "
                       "borrower's row.", default=True),)),
)


# ------------------------------------------------- credit-risk ontology v2
#
# P0.5. Each of these is a thing a credit officer says out loud and CreditProbe
# previously had no governed meaning for. Every one is backed by a real field in
# the governed lake — a concept with no data behind it is a definition wearing
# the clothes of an implementation, and it makes the catalogue look richer than
# the product is.

CONCEPTS_V2: tuple[Concept, ...] = (
    Concept(
        id="pd_12m", label="twelve-month PD",
        # "the 10 borrowers with the highest probability of credit
        # deterioration over the next 12 months" is one of the six questions
        # the acceptance run asked, and it was refused: no governed measure
        # was named, so the planner asked which figure to use and listed four
        # that do not include the one the sentence is describing.
        #
        # It IS describing this concept. A forward-looking LIKELIHOOD of a
        # credit outcome, over twelve months, is the twelve-month PD - the
        # candidate below defines itself in those exact words. The phrase is
        # what a credit officer says; "12-month PD" is what the catalogue
        # calls it, and a product that only understands the second has a
        # vocabulary gap, not a governed limit.
        #
        # Deliberately anchored on PROBABILITY (or likelihood/chance/risk OF).
        # "Which borrowers deteriorated?" is a movement question about what
        # already happened and must not resolve here; the forward-looking
        # likelihood of it is a different sentence and a different measure.
        pattern=(r"12[- ]?month pd|twelve[- ]?month pd|one[- ]?year pd|\bpd12\b"
                 r"|(?:probabilit(?:y|ies)|likelihood|chance|risk)\s+of\s+"
                 r"(?:\w+\s+){0,2}?"
                 r"(?:deteriorat\w*|default\w*|downgrad\w*|migrat\w*)"),
        unit="%",
        candidates=(
            _c(IFRS9, "pd_12m_pct",
               "The probability of default over the next twelve months, as the "
               "impairment calculation used it.", "ifrs9", "impairment",
               default=True),
            _c(FACILITY, "pd_12m_pct",
               "The twelve-month PD carried on the facility position.",
               "facility", "portfolio"),
        )),
    Concept(
        id="pd_lifetime", label="lifetime PD",
        pattern=r"lifetime pd|life[- ]?time probability|full[- ]?life pd",
        unit="%",
        candidates=(
            _c(IFRS9, "pd_lifetime_pct",
               "The probability of default over the remaining life of the "
               "exposure. Used once SICR has moved an account to a lifetime "
               "horizon.", default=True),
            _c(FACILITY, "pd_lifetime_pct",
               "Lifetime PD as carried on the facility position.",
               "facility"),
        )),
    Concept(
        id="pd_origination", label="PD at origination",
        pattern=r"pd at origination|origination pd|initial pd|pd since origination",
        unit="%",
        candidates=(_c(IFRS9, "pd_at_origination_pct",
                       "The PD recorded when the exposure was first "
                       "recognised. The reference point SICR is measured "
                       "against.", default=True),)),
    Concept(
        id="sicr", label="significant increase in credit risk",
        pattern=r"\bsicr\b|significant increase in credit risk|"
                r"stage 2 trigger|staging trigger",
        is_categorical=True,
        candidates=(
            _c(IFRS9, "sicr_any_trigger",
               "Whether any significant-increase trigger is firing.",
               default=True),
            _c(IFRS9, "sicr_pd_trigger", "The PD-deterioration trigger.", "pd"),
            _c(IFRS9, "sicr_dpd_trigger", "The days-past-due trigger.", "dpd",
               "past due"),
            _c(IFRS9, "sicr_covenant_trigger", "The covenant-breach trigger.",
               "covenant"),
            _c(IFRS9, "sicr_rating_trigger", "The rating-downgrade trigger.",
               "rating", "downgrade"),
            _c(IFRS9, "sicr_watchlist_trigger", "The watchlist trigger.",
               "watchlist"),
        )),
    Concept(
        id="overlay", label="management and macro overlay",
        pattern=r"overlay|management adjustment|post[- ]?model adjustment|\bpma\b",
        unit="SAR mn",
        candidates=(
            _c(IFRS9, "macro_overlay",
               "The overlay added on top of modelled ECL. A judgement, not a "
               "model output.", default=True),
            _c(FACILITY, "macro_overlay",
               "The overlay as carried on the facility position.", "facility"),
        )),
    Concept(
        id="model_ecl", label="modelled ECL",
        pattern=r"model(?:led|ed)? ecl|modelled impairment|pre[- ]?overlay ecl",
        unit="SAR mn",
        candidates=(_c(IFRS9, "model_ecl",
                       "ECL as the impairment model computed it, before any "
                       "overlay.", default=True),)),
    Concept(
        id="external_rating", label="external rating",
        pattern=r"external rating|agency rating|\bs&p\b|moody|fitch",
        is_categorical=True,
        candidates=(
            _c(RATINGS, "external_rating",
               "The agency rating recorded at the customer's rating cycle.",
               "customer", "cycle", default=True),
            _c(FINANCIALS, "external_rating",
               "The agency rating on the borrower's financial record.",
               "financials"),
        )),
    Concept(
        id="npl", label="non-performing",
        pattern=r"\bnpl\b|non[- ]?performing|\bnpe\b|bad book",
        is_categorical=True,
        candidates=(
            _c(FACILITY, "npl",
               "Whether the facility is non-performing at the reporting date.",
               default=True),
            _c(DELINQUENCY, "npl",
               "Non-performing status on the delinquency record.",
               "delinquen", "arrears"),
        )),
    Concept(
        id="arrears", label="arrears amount",
        # Deliberately NOT the bare word. "Accounts in arrears" and "worsening
        # arrears" are about the delinquency state, which `dpd` already owns and
        # measures in days; only a qualified phrase means the overdue AMOUNT.
        # One phrase claimed by two concepts resolves by pattern length, which
        # is to say arbitrarily.
        pattern=r"arrears (?:amount|balance)|amount (?:in arrears|overdue)|"
                r"past[- ]?due amount|overdue amount|missed instalments?",
        unit="SAR mn",
        candidates=(
            _c(DELINQUENCY, "arrears_amount",
               "The amount currently overdue.", default=True),
            _c(DELINQUENCY, "exposure_at_risk",
               "The exposure of accounts carrying arrears.", "exposure",
               "at risk"),
        )),
    Concept(
        id="dpd_bucket", label="delinquency bucket",
        pattern=r"dpd bucket|delinquency bucket|ageing bucket|arrears bucket|"
                r"bucket",
        is_ordinal=True,
        candidates=(_c(DELINQUENCY, "dpd_bucket",
                       "The ordered days-past-due band the account sits in.",
                       default=True),)),
    Concept(
        id="cure", label="cure",
        pattern=r"\bcure[ds]?\b|returned to performing|rehabilitat\w*|"
                r"back to stage 1",
        higher_is_worse=False, is_categorical=True,
        candidates=(
            _c(DELINQUENCY, "cured_this_period",
               "Whether the account returned to performing in this period.",
               default=True),
            _c(IFRS9, "quarters_clean",
               "How many consecutive quarters the account has been clean.",
               "clean", "consecutive"),
        )),
    Concept(
        id="forbearance", label="forbearance",
        pattern=r"forbear\w*|restructur\w*|concession|reschedul\w*",
        is_categorical=True,
        candidates=(
            _c(DELINQUENCY, "forbearance_type",
               "The kind of concession granted, where one was.", default=True),
            _c(DELINQUENCY, "restructured_flag",
               "Whether the facility has been restructured.", "restructur"),
        )),
    Concept(
        id="collateral", label="collateral value",
        # "collateral COVERAGE" is deliberately excluded. It is a ratio —
        # collateral over exposure — and the core credit book publishes only
        # the amount. Matched here, "collateral coverage below 50%" resolved to
        # the collateral VALUE and tested it against 50, so a question about a
        # ratio was answered as a question about millions: a condition that
        # looks applied and tests the wrong thing, which is worse than one that
        # is reported as unavailable. Excluded, the coverage gate says so.
        pattern=r"collateral(?!\s+cover)|security(?! interest)|\bltv\b|"
                r"net realisable value",
        higher_is_worse=False, unit="SAR mn",
        candidates=(
            _c(FACILITY, "collateral_value",
               "The collateral value carried on the facility position.",
               "facility", "portfolio", default=True),
            _c(COLLATERAL, "net_realisable_value",
               "Market value less the governed haircut — what the bank would "
               "expect to realise.", "realisable", "haircut", "net"),
            _c(COLLATERAL, "market_value",
               "The valuer's market value, before any haircut.", "market",
               "valuation", "gross"),
        )),
    Concept(
        id="limit", label="approved limit",
        pattern=r"\blimits?\b|approved (?:limit|facility)|facility size|"
                r"committed amount",
        unit="SAR mn",
        candidates=(
            _c(FACILITY, "limit_amount",
               "The approved limit on the facility position.", default=True),
            _c(LIMITS, "limit_amount",
               "The approved limit on the limits record.", "limits",
               "approval"),
        )),
    Concept(
        id="undrawn", label="undrawn commitment",
        pattern=r"undrawn|unutilised|unused (?:limit|commitment)|headroom on the limit",
        unit="SAR mn",
        candidates=(_c(FACILITY, "undrawn",
                       "The committed amount not yet drawn.", default=True),)),
    Concept(
        id="realised_lgd", label="realised loss given default",
        pattern=r"realis\w+ lgd|actual lgd|realised loss|recovery rate",
        unit="%",
        candidates=(
            _c(RECOVERIES, "realised_lgd_pct",
               "The loss actually realised on a defaulted exposure, once "
               "recoveries are in.", default=True),
            _c(RECOVERIES, "recovery_rate_pct",
               "Cash and collateral recovered as a share of exposure at "
               "default.", "recovery", "recovered"),
        )),
    Concept(
        id="default_rate", label="observed default rate",
        pattern=r"observed default rate|\bodr\b|default rate|realised defaults?",
        unit="%",
        candidates=(_c(PD_MODEL, "observed_default_rate_pct",
                       "The default rate actually observed for a segment, "
                       "against which the predicted PD is calibrated.",
                       default=True),)),
    Concept(
        id="notches_moved", label="rating migration",
        pattern=r"notches? moved|rating migration|migrat\w+ (?:by|of) notch|"
                r"transition matrix",
        candidates=(
            _c(RATINGS, "notches_moved",
               "How many notches the customer's grade moved at its rating "
               "cycle.", default=True),
            _c(TRANSITIONS, "notches_moved",
               "Notches moved on the rating transition record.", "transition",
               "matrix"),
        )),
    Concept(
        id="stage_moved", label="stage migration",
        pattern=r"stage migration|stage move\w*|moved (?:in)?to stage|"
                r"staging movement",
        is_categorical=True,
        candidates=(_c(IFRS9, "stage_moved",
                       "Whether the account changed IFRS 9 stage this period, "
                       "and in which direction.", default=True),)),
    Concept(
        id="appetite", label="risk appetite utilisation",
        pattern=r"risk appetite|appetite (?:limit|breach|utilisation)|"
                r"concentration limit",
        unit="%",
        candidates=(
            _c(APPETITE, "utilisation_of_limit_pct",
               "How much of a sector's appetite limit is used.", default=True),
            _c(FACILITY, "appetite_breach",
               "Whether the facility sits in a sector breaching appetite.",
               "breach", "facility"),
        )),
    Concept(
        id="raroc", label="risk-adjusted return on capital",
        pattern=r"\braroc\b|risk[- ]?adjusted return|return on capital",
        higher_is_worse=False, unit="%",
        candidates=(_c(FACILITY, "raroc_pct",
                       "Risk-adjusted return on regulatory capital for the "
                       "facility.", default=True),)),
)

#: The whole vocabulary. Built here rather than in two places so the match
#: index below cannot see a different set of concepts from the one the rest of
#: the product reads.
CONCEPTS = CONCEPTS + CONCEPTS_V2

#: Sorted longest-pattern-first so a specific phrase wins over a general one.
_ORDERED = tuple(sorted(CONCEPTS, key=lambda c: -len(c.pattern)))


@dataclass
class ConceptMatch:
    """One concept found in a question, and the field chosen for it."""

    concept: Concept
    candidate: Candidate
    phrase: str = ""
    confidence: float = 1.0
    #: Other candidates that were available. Empty when there was no choice.
    alternatives: tuple[Candidate, ...] = ()
    #: What settled the choice, in the words the answer will use.
    reason: str = ""
    #: Set when CreditProbe should ask rather than choose.
    needs_clarification: bool = False

    @property
    def dataset(self) -> str:
        return self.candidate.dataset

    @property
    def field(self) -> str:
        return self.candidate.field

    def to_dict(self) -> dict[str, Any]:
        return {
            "concept": self.concept.id,
            "label": self.concept.label,
            "phrase": self.phrase,
            "dataset": self.dataset,
            "field": self.field,
            "definition": self.candidate.definition,
            "unit": self.concept.unit,
            "is_ordinal": self.concept.is_ordinal,
            "is_categorical": self.concept.is_categorical,
            "higher_is_worse": self.concept.higher_is_worse,
            "confidence": round(self.confidence, 3),
            "reason": self.reason,
            "alternatives": [c.to_dict() for c in self.alternatives],
            "needs_clarification": self.needs_clarification,
        }


def _available(candidate: Candidate, known: dict[str, set[str]]) -> bool:
    """Whether the governed catalogue actually carries this field."""
    return candidate.field in known.get(candidate.dataset, set())


def _authority_rank(dataset: str, catalogue: Any) -> int:
    """How authoritative a dataset is — more governed purposes served, higher.

    Read from the catalogue rather than hard-coded, so a bank that makes its own
    dataset authoritative for the facility position changes what a concept
    resolves to without anybody editing this file.
    """
    try:
        return len(catalogue.dataset(dataset).authoritative_for)
    except Exception:
        return 0


def _is_client_authority(dataset: str, catalogue: Any) -> bool:
    """Whether this is the bank's own data, declared authoritative.

    The demonstration book exists so the product can be seen working. Once a
    bank has onboarded its own dataset and a steward has declared it
    authoritative for the same governed purpose, answering from the demo book
    would be a correct calculation over the wrong company's portfolio — which
    is worse than refusing, because it looks right.
    """
    try:
        definition = catalogue.dataset(dataset)
    except Exception:
        return False
    return (str(getattr(definition, "origin", "")) == "client"
            and bool(getattr(definition, "authoritative_for", ())))


def _client_authority_over(chosen: Candidate, usable: list[Candidate],
                           catalogue: Any) -> Candidate | None:
    """The bank's own authoritative source, where it outranks the default.

    Returns None unless exactly one candidate qualifies: two client datasets
    both declared authoritative for the same concept is a governance question
    for a steward, not a tie the planner should break on its own.
    """
    if catalogue is None:
        return None
    client = [c for c in usable if _is_client_authority(c.dataset, catalogue)]
    if len(client) != 1 or client[0] is chosen:
        return None
    if _is_client_authority(chosen.dataset, catalogue):
        return None
    return client[0]


def resolve_concept(concept: Concept, question: str, *,
                    known: dict[str, set[str]], catalogue: Any = None,
                    phrase: str = "") -> ConceptMatch | None:
    """Choose the field this concept means in THIS question."""
    lowered = question.lower()
    usable = [c for c in concept.candidates if _available(c, known)]
    if not usable:
        return None

    # 1. A qualifier in the question settles it outright.
    for candidate in usable:
        for qualifier in candidate.qualifiers:
            if qualifier and qualifier in lowered:
                return ConceptMatch(
                    concept=concept, candidate=candidate, phrase=phrase,
                    confidence=1.0,
                    alternatives=tuple(c for c in usable if c is not candidate),
                    reason=(f"The question says '{qualifier}', which selects "
                            f"{candidate.dataset}.{candidate.field}: "
                            f"{candidate.definition}"))

    if len(usable) == 1:
        return ConceptMatch(
            concept=concept, candidate=usable[0], phrase=phrase, confidence=1.0,
            reason=(f"{usable[0].dataset}.{usable[0].field} is the only "
                    f"governed field carrying {concept.label}."))

    # 2. The declared default, with the alternatives recorded so the answer can
    #    say which definition it used.
    chosen = next((c for c in usable if c.is_default), None)
    if chosen is not None:
        # The bank's own authoritative data beats a default that points at the
        # demonstration book. The default encodes which figure a credit officer
        # usually means; it cannot know that this bank has since onboarded its
        # own source for it.
        client = _client_authority_over(chosen, usable, catalogue)
        if client is not None:
            return ConceptMatch(
                concept=concept, candidate=client, phrase=phrase,
                confidence=0.9,
                alternatives=tuple(c for c in usable if c is not client),
                reason=(f"'{concept.label}' exists in {len(usable)} governed "
                        f"datasets. CreditProbe used {client.dataset}."
                        f"{client.field} because it is the bank's own data and "
                        "a steward has declared it authoritative; the "
                        f"synthetic source {chosen.dataset}.{chosen.field} "
                        "was not used."))
        others = tuple(c for c in usable if c is not chosen)
        catalogue_note = ""
        if catalogue is not None:
            ranks = {c.dataset: _authority_rank(c.dataset, catalogue) for c in usable}
            if ranks.get(chosen.dataset, 0) >= max(ranks.values()):
                catalogue_note = (f" {chosen.dataset} is declared authoritative "
                                  "in the governed catalogue.")
        return ConceptMatch(
            concept=concept, candidate=chosen, phrase=phrase, confidence=0.85,
            alternatives=others,
            reason=(f"'{concept.label}' exists in "
                    f"{len(usable)} governed datasets. CreditProbe used "
                    f"{chosen.dataset}.{chosen.field}: {chosen.definition}"
                    + catalogue_note))

    # 3. Genuinely ambiguous. Ask.
    return ConceptMatch(
        concept=concept, candidate=usable[0], phrase=phrase, confidence=0.4,
        alternatives=tuple(usable[1:]), needs_clarification=True,
        reason=(f"'{concept.label}' could mean any of "
                + ", ".join(f"{c.dataset}.{c.field}" for c in usable)
                + ", and they are different figures."))


@dataclass
class Reading:
    """Every concept found in one question."""

    matches: list[ConceptMatch] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)

    @property
    def datasets(self) -> list[str]:
        out: list[str] = []
        for match in self.matches:
            if match.dataset not in out:
                out.append(match.dataset)
        return out

    @property
    def needs_clarification(self) -> list[ConceptMatch]:
        return [m for m in self.matches if m.needs_clarification]

    def by_concept(self, concept_id: str) -> ConceptMatch | None:
        return next((m for m in self.matches if m.concept.id == concept_id), None)

    def to_dict(self) -> dict[str, Any]:
        return {"matches": [m.to_dict() for m in self.matches],
                "datasets": self.datasets,
                "unresolved": list(self.unresolved)}


def read_concepts(question: str, *, known: dict[str, set[str]],
                  catalogue: Any = None) -> Reading:
    """Every concept the question names, resolved to a governed field.

    Deterministic. The reading decides which datasets are joined and therefore
    what is computed; a reading that varies between two identical questions
    makes every answer unreproducible, which is the opposite of what this
    product sells.
    """
    reading = Reading()
    text = " ".join(str(question).split())
    seen: set[str] = set()
    spans: list[tuple[int, int, Any]] = []

    for concept in _ORDERED:
        match = re.search(concept.pattern, text, re.IGNORECASE)
        if not match or concept.id in seen:
            continue
        resolved = resolve_concept(concept, text, known=known,
                                   catalogue=catalogue, phrase=match.group(0))
        if resolved is None:
            reading.unresolved.append(
                f"'{match.group(0)}' means {concept.label}, which no governed "
                "dataset in this installation carries.")
            continue
        seen.add(concept.id)
        spans.append((*match.span(), resolved))

    reading.matches.extend(m for _, _, m in _widest(spans))
    return reading


def _widest(spans: list[tuple[int, int, Any]]) -> list[tuple[int, int, Any]]:
    """Drop every match that is only part of a longer one.

    "Average ECL coverage by grade" names one measure and matched two: the
    `ecl` concept on the three letters inside "ECL coverage", and
    `ecl_coverage` on the whole phrase. Both are governed and only one was
    asked for, and the spurious one came first — so the answer led with a SUM
    of expected credit loss under a question about coverage ratios.

    The concepts are already ordered longest-pattern-first so a specific phrase
    wins over a general one. That is the right intention applied to the wrong
    thing: what has to win is the longer MATCH, and a pattern's length only
    approximates that.

    Two matches that merely overlap are both kept. "ECL coverage and DPD" is
    two measures whichever way the spans fall; only containment means one
    phrase WAS the other.
    """
    kept: list[tuple[int, int, Any]] = []
    for start, end, match in sorted(spans, key=lambda s: (s[0], -(s[1] - s[0]))):
        if any(other_start <= start and end <= other_end
               for other_start, other_end, _ in spans
               if (other_start, other_end) != (start, end)
               and other_end - other_start > end - start):
            continue
        kept.append((start, end, match))
    return kept


def catalogue_fields(catalogue: Any) -> dict[str, set[str]]:
    """Every governed dataset and the fields it carries."""
    out: dict[str, set[str]] = {}
    for definition in catalogue.all():
        out[definition.name] = set(definition.fields)
    return out


__all__ = [
    "CONCEPTS",
    "Candidate",
    "Concept",
    "ConceptMatch",
    "Reading",
    "catalogue_fields",
    "read_concepts",
    "resolve_concept",
]
