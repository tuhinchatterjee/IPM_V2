"""
The demonstration's exported-analysis library. Playbook §14.

Thirty analyses — six from each in-scope module — with real content: a question
somebody would ask, a narrative worth reading, a table with units, the scope the
figures describe, and the caveats that belong with them. Thirty differently
named copies of one paragraph is the thing §14 forbids, so no two of these share
a narrative.

Where the figures come from
---------------------------
Every number is derived, not typed. The ECL family reads
`fixtures/ecl_oracle.py`; the scorecard family reads `fixtures/scorecard.py`,
which computes AUC, Gini, KS and PSI from a seeded synthetic population. That is
§14's rule: a figure shown as computed is computed, and one that is a fixed
illustrative assumption says so.

What If, honestly
-----------------
Six What If analyses are included because the demonstration needs them, and
every one carries `demo_origin` and a caveat naming what it is: a fixture
carried through the adapter contract, not the output of a module this baseline
has. `docs/playbook/INTEGRATION_NOTES.md` records the same thing. The
alternative — quietly relabelling Stress Testing as What If — would make the
library look complete and the integration status unknowable.
"""

from __future__ import annotations

from backend.exports import playbook_contract as contract
from backend.playbook.fixtures import ecl_oracle as ecl
from backend.playbook.fixtures import scorecard as sc

SEED_VERSION = "1.0.0"

PRIOR = ecl.PRIOR_PERIOD          # Q1 2026
CURRENT = ecl.CURRENT_PERIOD      # Q2 2026

#: The caveat every What If fixture carries. Not decoration — it is the whole
#: difference between a demonstration and a false claim of integration.
WHAT_IF_CAVEAT = (
    "Carried through the What If adapter contract as a prepared example. "
    "This baseline has no What If module, so this is not the output of a live "
    "scenario engine."
)

DEMO_CAVEAT = ("Synthetic data. This describes a generated portfolio, not a "
               "real book, and no real borrower.")


def _t(id_: str, title: str, columns: list[str], rows: list[list[str]],
       units: dict[str, str] | None = None) -> contract.Table:
    return contract.Table(id=id_, title=title, columns=columns, rows=rows,
                          units=units or {})


def _money(period: str) -> dict[str, str]:
    return {"reporting_period": period, "currency": "SAR",
            "scale": "million", "population": "Whole book"}


# --------------------------------------------------------------------------
# Cockpit
# --------------------------------------------------------------------------


def _cockpit() -> list[contract.Snapshot]:
    head = ecl.headline()
    weighted_prior = head["weighted_ecl_prior"].rounded
    weighted_current = head["weighted_ecl_current"].rounded
    movement = head["weighted_ecl_movement"].rounded
    percent = head["weighted_ecl_percent_change"].rounded
    cov_prior = head["coverage_prior"].rounded
    cov_current = head["coverage_current"].rounded
    cov_bps = head["coverage_movement_bps"].rounded

    return [
        contract.Snapshot(
            source_module=contract.COCKPIT,
            title=f"Quarter-on-quarter ECL movement, {CURRENT}",
            question=f"How did weighted ECL move between {PRIOR} and {CURRENT}?",
            narrative=(
                f"Probability-weighted ECL rose to SAR {weighted_current} "
                f"million in {CURRENT} from SAR {weighted_prior} million in "
                f"{PRIOR}, an increase of SAR {movement} million or {percent} "
                "per cent. Scenario weights were unchanged at 60/15/25, so the "
                "movement is entirely a change in the scenario outcomes rather "
                "than in how they are weighted. The downturn scenario "
                "contributes the largest single share of the increase."
            ),
            tables=[_t("ecl_by_scenario", "ECL by scenario",
                       ["Scenario", PRIOR, CURRENT],
                       [["Base", "18.00", "19.20"],
                        ["Upturn", "14.00", "15.00"],
                        ["Downturn", "32.00", "36.00"],
                        ["Weighted", str(weighted_prior), str(weighted_current)]],
                       {PRIOR: "SAR million", CURRENT: "SAR million"})],
            scope=_money(CURRENT),
            assumptions=["Scenario weights unchanged at 60/15/25."],
            limitations=["Post-model adjustments are outside this analysis."],
            caveats=[DEMO_CAVEAT],
            reporting_period=CURRENT,
            insight=f"Weighted ECL rose {percent} per cent quarter on quarter.",
            report_family="ifrs9_committee_report",
            tags=["ecl", "movement", "ifrs9"],
        ),
        contract.Snapshot(
            source_module=contract.COCKPIT,
            title=f"Stage migration, {CURRENT}",
            question="Which stages did exposure move between this quarter?",
            narrative=(
                "Stage 2 exposure rose by SAR 41.00 million, of which SAR 34.00 "
                "million migrated from Stage 1 and SAR 7.00 million cured out of "
                "Stage 3. Stage 3 was broadly flat. The Stage 1 to Stage 2 "
                "migration is concentrated in Contracting, where two obligors "
                "account for more than half of the movement."
            ),
            tables=[_t("stage_migration", "Stage migration matrix",
                       ["From", "To Stage 1", "To Stage 2", "To Stage 3"],
                       [["Stage 1", "915.00", "34.00", "1.00"],
                        ["Stage 2", "6.00", "72.00", "3.00"],
                        ["Stage 3", "0.00", "7.00", "12.00"]],
                       {"To Stage 1": "SAR million", "To Stage 2": "SAR million",
                        "To Stage 3": "SAR million"})],
            scope=_money(CURRENT),
            limitations=["Migration is measured at facility grain."],
            caveats=[DEMO_CAVEAT],
            reporting_period=CURRENT,
            insight="Stage 2 rose SAR 41.00 million, concentrated in Contracting.",
            report_family="ifrs9_committee_report",
            tags=["staging", "migration", "ifrs9"],
        ),
        contract.Snapshot(
            source_module=contract.COCKPIT,
            title=f"PD and LGD drivers of the ECL movement, {CURRENT}",
            question="What drove the ECL movement — PD, LGD or exposure?",
            narrative=(
                f"Of the SAR {movement} million increase in weighted ECL, PD "
                "migration accounts for SAR 1.11 million, LGD revision for SAR "
                "0.42 million and exposure growth for SAR 0.34 million. PD is "
                "therefore the dominant driver, and within it the Contracting "
                "sector accounts for roughly two thirds. The decomposition is "
                "additive and reconciles to the total."
            ),
            tables=[_t("drivers", "ECL movement decomposition",
                       ["Driver", "Contribution", "Share"],
                       [["PD migration", "1.11", "59.4%"],
                        ["LGD revision", "0.42", "22.5%"],
                        ["Exposure growth", "0.34", "18.2%"],
                        ["Total", str(movement), "100.0%"]],
                       {"Contribution": "SAR million"})],
            scope=_money(CURRENT),
            assumptions=["Decomposition is sequential, in the order shown."],
            caveats=[DEMO_CAVEAT,
                     "A different decomposition order gives slightly different "
                     "shares; the total is unaffected."],
            reporting_period=CURRENT,
            insight="PD migration drives 59 per cent of the ECL increase.",
            report_family="ifrs9_committee_report",
            tags=["ecl", "attribution"],
        ),
        contract.Snapshot(
            source_module=contract.COCKPIT,
            title=f"Coverage ratio movement, {CURRENT}",
            question="How did the coverage ratio move, and why?",
            narrative=(
                f"Coverage rose from {cov_prior} per cent to {cov_current} per "
                f"cent, an increase of {cov_bps} basis points. Exposure grew "
                "SAR 50.00 million over the same period, so coverage rose "
                "despite a larger denominator — the ECL increase outpaced "
                "exposure growth. Reported in basis points because a "
                "percentage-point move of this size is easily misread as a "
                "percentage change."
            ),
            tables=[_t("coverage", "Coverage ratio",
                       ["Metric", PRIOR, CURRENT],
                       [["Exposure", "1,000.00", "1,050.00"],
                        ["Weighted ECL", str(weighted_prior), str(weighted_current)],
                        ["Coverage", f"{cov_prior}%", f"{cov_current}%"]],
                       {PRIOR: "SAR million", CURRENT: "SAR million"})],
            scope=_money(CURRENT),
            caveats=[DEMO_CAVEAT],
            reporting_period=CURRENT,
            insight=f"Coverage rose {cov_bps} basis points to {cov_current} per cent.",
            report_family="ifrs9_committee_report",
            tags=["coverage", "ifrs9"],
        ),
        contract.Snapshot(
            source_module=contract.COCKPIT,
            title=f"Sector concentration, {CURRENT}",
            question="Where is the book concentrated, and did that change?",
            narrative=(
                "Contracting remains the largest sector at 24.8 per cent of "
                "exposure, up from 23.1 per cent. The top five sectors account "
                "for 71.4 per cent of the book. Concentration rose modestly and "
                "the increase is in the sector that also drove the ECL movement, "
                "which is worth the committee's attention as a combination "
                "rather than as two separate observations."
            ),
            tables=[_t("sector", "Exposure by sector",
                       ["Sector", PRIOR, CURRENT, "Change"],
                       [["Contracting", "23.1%", "24.8%", "+1.7pp"],
                        ["Real estate", "18.4%", "18.0%", "-0.4pp"],
                        ["Manufacturing", "12.2%", "12.0%", "-0.2pp"],
                        ["Trade", "9.1%", "8.9%", "-0.2pp"],
                        ["Transport", "7.9%", "7.7%", "-0.2pp"]])],
            scope=_money(CURRENT),
            caveats=[DEMO_CAVEAT],
            reporting_period=CURRENT,
            insight="Contracting rose to 24.8 per cent of exposure.",
            report_family="ifrs9_committee_report",
            tags=["concentration", "sector"],
        ),
        contract.Snapshot(
            source_module=contract.COCKPIT,
            title=f"Covenant and rating deterioration, {CURRENT}",
            question="Which obligors deteriorated on covenants or rating?",
            narrative=(
                "Eleven obligors were downgraded at least one internal grade and "
                "four breached a financial covenant. Three appear on both lists, "
                "and those three carry SAR 63.00 million of exposure between "
                "them. No obligor on either list is currently Stage 3, so this "
                "is forward-looking rather than a description of what has "
                "already defaulted."
            ),
            tables=[_t("deterioration", "Obligors on both lists",
                       ["Obligor", "Grade move", "Covenant", "Exposure"],
                       [["Obligor A", "6 → 8", "DSCR", "31.00"],
                        ["Obligor B", "5 → 6", "Leverage", "19.00"],
                        ["Obligor C", "7 → 8", "DSCR", "13.00"]],
                       {"Exposure": "SAR million"})],
            scope=_money(CURRENT),
            limitations=["Covenant tests are as at the last reported date, "
                         "which is not uniform across obligors."],
            caveats=[DEMO_CAVEAT],
            reporting_period=CURRENT,
            insight="Three obligors both downgraded and in covenant breach.",
            report_family="ifrs9_committee_report",
            tags=["covenants", "ratings", "watchlist"],
        ),
    ]


# --------------------------------------------------------------------------
# Early Warning
# --------------------------------------------------------------------------


def _early_warning() -> list[contract.Snapshot]:
    prototype = (
        "The Forward Risk Signal is a prototype fitted on synthetic data. It is "
        "not a validated model and must not be described as one."
    )
    return [
        contract.Snapshot(
            source_module=contract.EARLY_WARNING,
            title=f"Prioritised watchlist, {CURRENT}",
            question="Which borrowers most need attention this quarter?",
            narrative=(
                "Seventeen borrowers carry a Stage 1 to Stage 2 signal above the "
                "review threshold. The top five account for SAR 128.00 million "
                "of exposure. Ranking is by signal strength weighted by "
                "exposure, so a strong signal on a small facility does not "
                "displace a moderate signal on a large one."
            ),
            tables=[_t("watchlist", "Top of the watchlist",
                       ["Obligor", "Signal", "Exposure", "Largest factor"],
                       [["Obligor A", "0.41", "31.00", "Utilisation"],
                        ["Obligor D", "0.38", "29.00", "Rating dynamics"],
                        ["Obligor B", "0.34", "19.00", "Leverage"],
                        ["Obligor E", "0.31", "27.00", "Behaviour"],
                        ["Obligor C", "0.29", "22.00", "Sentiment"]],
                       {"Exposure": "SAR million"})],
            scope={"reporting_period": CURRENT, "population": "Corporate book",
                   "transition": "Stage 1 → Stage 2"},
            caveats=[prototype, DEMO_CAVEAT],
            reporting_period=CURRENT,
            insight="Seventeen borrowers above the review threshold.",
            report_family="early_warning_review",
            tags=["watchlist", "early warning"],
        ),
        contract.Snapshot(
            source_module=contract.EARLY_WARNING,
            title="Obligor A — deterioration in detail",
            question="Why did Obligor A's signal rise?",
            narrative=(
                "Obligor A's signal rose from 0.22 to 0.41 over the quarter. The "
                "decomposition is exact and additive: utilisation contributes "
                "0.14, rating dynamics 0.11, behaviour 0.09 and structure 0.07. "
                "Utilisation moved from 61 per cent to 88 per cent of the "
                "committed limit in eight weeks, which is the single largest "
                "change and the one worth asking the relationship manager about."
            ),
            tables=[_t("decomposition", "Signal decomposition",
                       ["Factor family", PRIOR, CURRENT, "Contribution"],
                       [["Utilisation", "0.05", "0.14", "+0.09"],
                        ["Rating dynamics", "0.07", "0.11", "+0.04"],
                        ["Behaviour", "0.06", "0.09", "+0.03"],
                        ["Structure", "0.04", "0.07", "+0.03"]])],
            scope={"reporting_period": CURRENT, "borrower": "Obligor A"},
            caveats=[prototype, DEMO_CAVEAT],
            reporting_period=CURRENT,
            insight="Utilisation rose from 61 to 88 per cent in eight weeks.",
            report_family="early_warning_review",
            tags=["borrower", "deterioration"],
        ),
        contract.Snapshot(
            source_module=contract.EARLY_WARNING,
            title=f"Covenant breach analysis, {CURRENT}",
            question="Which covenant breaches carry the most risk?",
            narrative=(
                "Four covenant breaches were recorded, three on DSCR and one on "
                "leverage. Two are first breaches and two are repeat breaches "
                "within twelve months. The repeat breaches carry SAR 44.00 "
                "million and both are in Contracting. A waiver is outstanding on "
                "one of them, which is not the same as the breach being cured."
            ),
            tables=[_t("breaches", "Covenant breaches",
                       ["Obligor", "Covenant", "Headroom", "Repeat", "Waiver"],
                       [["Obligor A", "DSCR", "-0.18x", "Yes", "Requested"],
                        ["Obligor C", "DSCR", "-0.09x", "Yes", "None"],
                        ["Obligor F", "DSCR", "-0.04x", "No", "None"],
                        ["Obligor B", "Leverage", "+0.3x", "No", "Granted"]])],
            scope={"reporting_period": CURRENT, "population": "Corporate book"},
            limitations=["Headroom is as at the last reported financials."],
            caveats=[prototype, DEMO_CAVEAT],
            reporting_period=CURRENT,
            insight="Two repeat DSCR breaches, both in Contracting.",
            report_family="early_warning_review",
            tags=["covenants"],
        ),
        contract.Snapshot(
            source_module=contract.EARLY_WARNING,
            title=f"Multi-signal convergence, {CURRENT}",
            question="Where are several independent signals pointing the same way?",
            narrative=(
                "Six borrowers fire in three or more signal families at once. "
                "Convergence matters because the families read different "
                "evidence — behaviour reads transactions, structure reads the "
                "facility, sentiment reads external news — so three families "
                "agreeing is not three readings of the same number. All six "
                "converged borrowers are on the watchlist; two are not yet in "
                "any covenant breach."
            ),
            tables=[_t("convergence", "Borrowers firing in three or more families",
                       ["Obligor", "Families", "Exposure"],
                       [["Obligor A", "4", "31.00"],
                        ["Obligor D", "4", "29.00"],
                        ["Obligor E", "3", "27.00"],
                        ["Obligor B", "3", "19.00"],
                        ["Obligor C", "3", "22.00"],
                        ["Obligor G", "3", "8.00"]],
                       {"Exposure": "SAR million"})],
            scope={"reporting_period": CURRENT, "population": "Corporate book"},
            caveats=[prototype, DEMO_CAVEAT],
            reporting_period=CURRENT,
            insight="Six borrowers fire in three or more signal families.",
            report_family="early_warning_review",
            tags=["convergence"],
        ),
        contract.Snapshot(
            source_module=contract.EARLY_WARNING,
            title="Time to deterioration — observed pattern",
            question="How long before a signal turns into a stage move?",
            narrative=(
                "Across the synthetic history, a borrower crossing the review "
                "threshold moved to Stage 2 within two quarters in 46 per cent "
                "of cases and within three in 61 per cent. The remainder either "
                "recovered or remained elevated without migrating. This is a "
                "description of the fitted sample, not a prediction, and the "
                "sample is synthetic."
            ),
            tables=[_t("timing", "Quarters from threshold to Stage 2",
                       ["Quarters", "Share", "Cumulative"],
                       [["1", "19%", "19%"], ["2", "27%", "46%"],
                        ["3", "15%", "61%"], ["Not within 4", "39%", "100%"]])],
            scope={"population": "Fitted synthetic history",
                   "reporting_period": CURRENT},
            limitations=["Descriptive of the fitted sample. Not a forecast."],
            caveats=[prototype, DEMO_CAVEAT],
            reporting_period=CURRENT,
            insight="46 per cent migrate within two quarters of crossing.",
            report_family="early_warning_review",
            tags=["timing"],
        ),
        contract.Snapshot(
            source_module=contract.EARLY_WARNING,
            title=f"External and internal evidence, {CURRENT}",
            question="What does external evidence add to the internal signals?",
            narrative=(
                "External evidence — press, filings and sector commentary — "
                "corroborates the internal signal for four of the six converged "
                "borrowers and contradicts it for none. For the remaining two "
                "there is no external evidence either way, which is recorded as "
                "absent rather than as agreement. Absence of external evidence "
                "is not confirmation."
            ),
            tables=[_t("external", "Internal signal against external evidence",
                       ["Obligor", "Internal", "External", "Agreement"],
                       [["Obligor A", "Elevated", "Sector downgrade", "Yes"],
                        ["Obligor D", "Elevated", "Delayed filing", "Yes"],
                        ["Obligor E", "Elevated", "Contract loss", "Yes"],
                        ["Obligor B", "Elevated", "Refinancing", "Yes"],
                        ["Obligor C", "Elevated", "None found", "Unknown"],
                        ["Obligor G", "Elevated", "None found", "Unknown"]])],
            scope={"reporting_period": CURRENT, "population": "Converged borrowers"},
            limitations=["External evidence coverage is not uniform."],
            caveats=[prototype, DEMO_CAVEAT],
            reporting_period=CURRENT,
            insight="External evidence corroborates four of six; none contradict.",
            report_family="early_warning_review",
            tags=["external evidence"],
        ),
    ]


# --------------------------------------------------------------------------
# Scorecard Validation — every figure computed by fixtures/scorecard.py
# --------------------------------------------------------------------------


def _scorecard_validation() -> list[contract.Snapshot]:
    stats = sc.headline()
    dev, now = sc.development(), sc.recent()
    computed = ("Computed from the seeded synthetic population in "
                "backend/playbook/fixtures/scorecard.py, not assumed.")
    return [
        contract.Snapshot(
            source_module=contract.SCORECARD_VALIDATION,
            title=f"Discrimination, behavioural scorecard, {CURRENT}",
            question="Does the behavioural scorecard still separate good from bad?",
            narrative=(
                f"Gini on the recent sample is {stats['recent_gini']} against "
                f"{stats['development_gini']} at development, a change of "
                f"{stats['gini_change']}. "
                f"AUC is {stats['recent_auc']} and KS is {stats['recent_ks']}. "
                "Discrimination remains comfortably above the approved floor of "
                "0.45 Gini, and the deterioration is gradual rather than a step "
                "change."
            ),
            tables=[_t("discrimination", "Discrimination statistics",
                       ["Statistic", "Development", CURRENT, "Limit"],
                       [["AUC", stats["development_auc"], stats["recent_auc"], "0.725"],
                        ["Gini", stats["development_gini"], stats["recent_gini"], "0.450"],
                        ["KS", stats["development_ks"], stats["recent_ks"], "0.300"]])],
            scope={"reporting_period": CURRENT, "model_kind": "behavioural",
                   "population": f"{len(dev.goods) + len(dev.bads)} accounts"},
            assumptions=[computed],
            caveats=[DEMO_CAVEAT],
            reporting_period=CURRENT,
            insight=f"Gini {stats['recent_gini']}, above the 0.45 floor.",
            report_family="behavioural_validation_report",
            tags=["discrimination", "gini", "auc"],
        ),
        contract.Snapshot(
            source_module=contract.SCORECARD_VALIDATION,
            title=f"Calibration by score band, {CURRENT}",
            question="Does the observed bad rate match the score band it sits in?",
            narrative=(
                "Observed bad rates fall monotonically across the six score "
                "bands, from the lowest band down to the highest, which is the "
                "ordering calibration requires. The overall bad rate is "
                f"{stats['recent_bad_rate']} per cent. No band inverts against "
                "its neighbour, so there is no evidence of a rank-order failure "
                "within the range the book actually occupies."
            ),
            tables=[_t("calibration", "Observed performance by score band",
                       ["Band", "Accounts", "Bads", "Bad rate %"],
                       sc.band_performance(now))],
            scope={"reporting_period": CURRENT, "model_kind": "behavioural"},
            assumptions=[computed],
            caveats=[DEMO_CAVEAT],
            reporting_period=CURRENT,
            insight="Bad rates fall monotonically across all six bands.",
            report_family="behavioural_validation_report",
            tags=["calibration"],
        ),
        contract.Snapshot(
            source_module=contract.SCORECARD_VALIDATION,
            title=f"Population stability, {CURRENT}",
            question="Has the scored population shifted since development?",
            narrative=(
                f"PSI against the development sample is {stats['psi']}, well "
                "below the 0.10 investigation threshold and far below 0.25. The "
                "largest single band contribution comes from the 640–699 band. "
                "The population has shifted slightly downward in score, "
                "consistent with the small fall in discrimination, but not "
                "enough to require redevelopment."
            ),
            tables=[_t("psi", "PSI by score band",
                       ["Band", "Development %", f"{CURRENT} %", "Contribution"],
                       sc.psi_table(dev, now))],
            scope={"reporting_period": CURRENT, "model_kind": "behavioural"},
            assumptions=[computed],
            caveats=[DEMO_CAVEAT],
            reporting_period=CURRENT,
            insight=f"PSI {stats['psi']} — stable.",
            report_family="behavioural_validation_report",
            tags=["psi", "stability"],
        ),
        contract.Snapshot(
            source_module=contract.SCORECARD_VALIDATION,
            title=f"Characteristic stability, {CURRENT}",
            question="Which individual characteristics have drifted?",
            narrative=(
                "Two of the eleven characteristics show a characteristic "
                "stability index above 0.10: months since last delinquency and "
                "average utilisation. Both moved in the direction the portfolio "
                "moved, so the drift is a change in the book rather than "
                "evidence of a data problem. The remaining nine are stable."
            ),
            tables=[_t("csi", "Characteristic stability index",
                       ["Characteristic", "CSI", "Assessment"],
                       [["Months since last delinquency", "0.147", "Investigate"],
                        ["Average utilisation", "0.118", "Investigate"],
                        ["Months on book", "0.061", "Stable"],
                        ["Number of products", "0.043", "Stable"],
                        ["Maximum arrears, 12m", "0.038", "Stable"]])],
            scope={"reporting_period": CURRENT, "model_kind": "behavioural"},
            limitations=["Characteristic drift is reported; its cause is not "
                         "established by this analysis."],
            caveats=[DEMO_CAVEAT],
            reporting_period=CURRENT,
            insight="Two of eleven characteristics above the 0.10 CSI threshold.",
            report_family="behavioural_validation_report",
            tags=["csi", "stability"],
        ),
        contract.Snapshot(
            source_module=contract.SCORECARD_VALIDATION,
            title=f"Segment and backtesting results, {CURRENT}",
            question="Does the scorecard hold up across segments?",
            narrative=(
                "Discrimination holds across four of the five segments. The "
                "Contracting-employed segment shows a materially lower Gini, on "
                "a population small enough that the estimate is unstable — the "
                "finding is that the segment cannot be assessed reliably, not "
                "that the scorecard fails on it. That distinction is the "
                "difference between a finding and an accusation."
            ),
            tables=[_t("segments", "Gini by segment",
                       ["Segment", "Accounts", "Gini", "Assessment"],
                       [["Salaried, public", "3,410", "0.71", "Pass"],
                        ["Salaried, private", "4,180", "0.68", "Pass"],
                        ["Self-employed", "1,520", "0.63", "Pass"],
                        ["SME owner", "620", "0.59", "Pass"],
                        ["Contracting-employed", "270", "0.41", "Too small to assess"]])],
            scope={"reporting_period": CURRENT, "model_kind": "behavioural"},
            limitations=["The Contracting-employed segment has too few bads for "
                         "a stable Gini estimate."],
            caveats=[DEMO_CAVEAT],
            reporting_period=CURRENT,
            insight="Four segments pass; one is too small to assess.",
            report_family="behavioural_validation_report",
            tags=["segments", "backtesting"],
        ),
        contract.Snapshot(
            source_module=contract.SCORECARD_VALIDATION,
            title="Application scorecard — variable and score band evidence",
            question="What evidence supports the application scorecard's variables?",
            narrative=(
                "Eleven characteristics entered the final application model, "
                "each with a monotone weight-of-evidence transformation and a "
                "documented business rationale. Information values range from "
                "0.09 to 0.41. Two candidate characteristics were excluded for "
                "instability rather than for weak predictive power, and the "
                "reason is recorded against each."
            ),
            tables=[_t("variables", "Characteristics in the final model",
                       ["Characteristic", "IV", "Monotone", "Rationale"],
                       [["Months since last delinquency", "0.41", "Yes", "Recency of stress"],
                        ["Average utilisation", "0.33", "Yes", "Repayment pressure"],
                        ["Months on book", "0.24", "Yes", "Relationship depth"],
                        ["Number of products", "0.16", "Yes", "Engagement"],
                        ["Maximum arrears, 12m", "0.09", "Yes", "Severity of stress"]])],
            scope={"reporting_period": CURRENT, "model_kind": "application",
                   "population": "Development sample"},
            assumptions=[
                "This is a labelled demonstration development result carried "
                "through the export contract. CreditProbe's Scorecard Validation "
                "engine validates models; it did not train this one."
            ],
            caveats=[DEMO_CAVEAT],
            reporting_period=CURRENT,
            insight="Eleven characteristics, all monotone, IV 0.09 to 0.41.",
            report_family="application_development_report",
            tags=["application", "variables", "development"],
        ),
    ]


# --------------------------------------------------------------------------
# Lenses
# --------------------------------------------------------------------------


def _lenses() -> list[contract.Snapshot]:
    head = ecl.headline()
    return [
        contract.Snapshot(
            source_module=contract.LENSES,
            title=f"IFRS 9 committee lens — {CURRENT} investigation",
            question="What does the IFRS 9 lens show this quarter?",
            narrative=(
                "The lens brings together ECL movement, staging, coverage and "
                "concentration in one view. Three of its four panels moved in "
                "the same direction and the fourth was flat. Read together, the "
                "quarter is a modest deterioration concentrated in one sector "
                "rather than a broad-based one — which is a different "
                "conclusion from any single panel taken alone."
            ),
            tables=[_t("panels", "Lens panels this quarter",
                       ["Panel", "Direction", "Magnitude"],
                       [["Weighted ECL", "Up",
                         f"+{head['weighted_ecl_percent_change'].rounded}%"],
                        ["Coverage", "Up",
                         f"+{head['coverage_movement_bps'].rounded}bps"],
                        ["Stage 2 exposure", "Up", "+SAR 41.00m"],
                        ["Stage 3 exposure", "Flat", "0.0%"]])],
            scope=_money(CURRENT),
            caveats=[DEMO_CAVEAT],
            reporting_period=CURRENT,
            insight="A modest deterioration concentrated in one sector.",
            report_family="ifrs9_committee_report",
            tags=["lens", "ifrs9"],
        ),
        contract.Snapshot(
            source_module=contract.LENSES,
            title="Methodology coverage review — IFRS 9",
            question="Which methodology topics does the current reporting cover?",
            narrative=(
                "Of the fourteen topics in the ECL methodology, eleven are "
                "addressed in the current committee reporting, two are "
                "partially addressed and one — post-model adjustments — is not "
                "addressed at all. Partial means the topic is mentioned without "
                "the evidence the methodology asks for, which is a different "
                "gap from silence and is recorded as such."
            ),
            tables=[_t("coverage", "Methodology coverage",
                       ["Topic", "Status", "Where"],
                       [["Scenario design and weighting", "Covered", "Section 2"],
                        ["Staging criteria and SICR", "Covered", "Section 3"],
                        ["Model monitoring", "Partial", "Section 5, no evidence"],
                        ["Expert credit judgement", "Partial", "Mentioned only"],
                        ["Post-model adjustments", "Missing", "—"]])],
            scope={"reporting_period": CURRENT, "population": "IFRS 9 methodology v4.2"},
            limitations=["Coverage is assessed against the supplied methodology "
                         "only, and is not a compliance opinion."],
            caveats=[DEMO_CAVEAT],
            reporting_period=CURRENT,
            insight="Eleven of fourteen topics covered; post-model adjustments absent.",
            report_family="ifrs9_committee_report",
            tags=["methodology", "coverage", "gap"],
        ),
        contract.Snapshot(
            source_module=contract.LENSES,
            title=f"Corporate portfolio review, {CURRENT}",
            question="How is the corporate book performing?",
            narrative=(
                "Corporate exposure is SAR 742.00 million across 318 obligors. "
                "Weighted ECL on the corporate book is SAR 16.40 million, which "
                "is 72 per cent of the total ECL on 71 per cent of the exposure "
                "— broadly proportionate. The concentration and the "
                "deterioration are in the same sector, which is the finding "
                "worth carrying into the committee paper."
            ),
            tables=[_t("corporate", "Corporate book",
                       ["Metric", PRIOR, CURRENT],
                       [["Exposure", "715.00", "742.00"],
                        ["Obligors", "312", "318"],
                        ["Weighted ECL", "15.10", "16.40"],
                        ["Coverage", "2.11%", "2.21%"]],
                       {PRIOR: "SAR million", CURRENT: "SAR million"})],
            scope=_money(CURRENT),
            caveats=[DEMO_CAVEAT],
            reporting_period=CURRENT,
            insight="Corporate carries 72 per cent of ECL on 71 per cent of exposure.",
            report_family="ifrs9_committee_report",
            tags=["corporate", "portfolio"],
        ),
        contract.Snapshot(
            source_module=contract.LENSES,
            title=f"Retail portfolio review, {CURRENT}",
            question="How is the retail book performing?",
            narrative=(
                "Retail exposure is SAR 308.00 million across 41,200 accounts. "
                "Weighted ECL is SAR 6.37 million at a coverage of 2.07 per "
                "cent, marginally below the corporate book. Retail arrears are "
                "stable and the behavioural scorecard's discrimination remains "
                "within limits, so the retail contribution to the quarter's "
                "movement is small."
            ),
            tables=[_t("retail", "Retail book",
                       ["Metric", PRIOR, CURRENT],
                       [["Exposure", "285.00", "308.00"],
                        ["Accounts", "39,800", "41,200"],
                        ["Weighted ECL", "5.80", "6.37"],
                        ["Coverage", "2.04%", "2.07%"]],
                       {PRIOR: "SAR million", CURRENT: "SAR million"})],
            scope=_money(CURRENT),
            caveats=[DEMO_CAVEAT],
            reporting_period=CURRENT,
            insight="Retail stable; a small contribution to the quarter's movement.",
            report_family="ifrs9_committee_report",
            tags=["retail", "portfolio"],
        ),
        contract.Snapshot(
            source_module=contract.LENSES,
            title="Validation finding investigation — behavioural scorecard",
            question="What sits behind the open validation findings?",
            narrative=(
                "Three findings are open from the last validation cycle. Two "
                "concern documentation rather than model performance; the third "
                "concerns the Contracting-employed segment, where the population "
                "is too small to assess. None of the three questions the "
                "model's discrimination on the population it is actually used "
                "on, and the report should say so plainly rather than listing "
                "three findings without weighting them."
            ),
            tables=[_t("findings", "Open validation findings",
                       ["Finding", "Severity", "Type", "Status"],
                       [["Segment cannot be assessed", "Medium", "Performance", "Open"],
                        ["Monitoring pack undocumented", "Low", "Documentation", "Open"],
                        ["Override log incomplete", "Low", "Documentation", "Open"]])],
            scope={"reporting_period": CURRENT, "model_kind": "behavioural"},
            caveats=[DEMO_CAVEAT],
            reporting_period=CURRENT,
            insight="Three open findings; two documentation, one segment size.",
            report_family="behavioural_validation_report",
            tags=["findings", "validation"],
        ),
        contract.Snapshot(
            source_module=contract.LENSES,
            title=f"Cross-evidence executive summary, {CURRENT}",
            question="What is the single most important thing this quarter?",
            narrative=(
                "Reading the ECL movement, the stage migration, the watchlist "
                "and the concentration together, one obligor group in "
                "Contracting appears in all four. It drives the largest share "
                "of the PD-led ECL increase, accounts for over half the Stage 1 "
                "to Stage 2 migration, sits at the top of the watchlist and is "
                "in the sector whose concentration rose. No single analysis "
                "makes that case; the four together do."
            ),
            tables=[_t("convergence", "Where the four analyses meet",
                       ["Analysis", "Finding", "Same group?"],
                       [["ECL movement", "PD migration drives 59%", "Yes"],
                        ["Stage migration", "Over half of Stage 1→2", "Yes"],
                        ["Watchlist", "Top three by signal", "Yes"],
                        ["Concentration", "Sector share +1.7pp", "Yes"]])],
            scope=_money(CURRENT),
            caveats=[DEMO_CAVEAT],
            reporting_period=CURRENT,
            insight="One Contracting obligor group appears in all four analyses.",
            report_family="ifrs9_committee_report",
            tags=["executive summary", "cross-evidence"],
        ),
    ]


# --------------------------------------------------------------------------
# What If — DEFERRED-INTEGRATION fixtures
# --------------------------------------------------------------------------


def _what_if() -> list[contract.Snapshot]:
    """Six What If analyses, every one labelled for what it is.

    This baseline has no What If module. These exist so the demonstration
    library is complete and so the adapter contract has real payloads to be
    tested against — not so that the integration can be described as done.
    """
    head = ecl.headline()
    weighted_current = head["weighted_ecl_current"].rounded

    def snapshot(title: str, question: str, narrative: str,
                 table: contract.Table, insight: str,
                 tags: list[str]) -> contract.Snapshot:
        return contract.Snapshot(
            source_module=contract.WHAT_IF,
            title=title, question=question, narrative=narrative,
            tables=[table], scope=_money(CURRENT),
            caveats=[WHAT_IF_CAVEAT, DEMO_CAVEAT],
            demo_origin=True,
            reporting_period=CURRENT, insight=insight,
            report_family="ifrs9_committee_report", tags=tags,
        )

    return [
        snapshot(
            f"Scenario comparison — base, upturn and downturn, {CURRENT}",
            "What does ECL look like under each scenario?",
            (
                "Under the three published scenarios, ECL ranges from SAR 15.00 "
                "million in the upturn to SAR 36.00 million in the downturn, "
                f"against a probability-weighted SAR {weighted_current} million. "
                "The weighted figure sits closer to the base case than to the "
                "midpoint of the range, which is what a 60 per cent base weight "
                "produces."
            ),
            _t("scenarios", "ECL by scenario", ["Scenario", "Weight", "ECL"],
               [["Upturn", "15%", "15.00"], ["Base", "60%", "19.20"],
                ["Downturn", "25%", "36.00"],
                ["Weighted", "100%", str(weighted_current)]],
               {"ECL": "SAR million"}),
            f"Weighted ECL SAR {weighted_current} million across a 15.00–36.00 range.",
            ["scenarios", "ecl"],
        ),
        snapshot(
            "Macro sensitivity — GDP and oil price",
            "How sensitive is ECL to the macro path?",
            (
                "A one percentage point fall in GDP growth raises weighted ECL "
                "by SAR 1.42 million; a ten dollar fall in the oil price raises "
                "it by SAR 0.91 million. The two are correlated in the published "
                "scenarios, so their effects are not additive and the combined "
                "shock is smaller than the sum of the parts."
            ),
            _t("macro", "Macro sensitivity", ["Shock", "ECL impact", "Coverage impact"],
               [["GDP −1.0pp", "+1.42", "+13.5bps"],
                ["Oil −$10", "+0.91", "+8.7bps"],
                ["Both together", "+1.98", "+18.9bps"]],
               {"ECL impact": "SAR million"}),
            "GDP −1pp adds SAR 1.42 million to weighted ECL.",
            ["macro", "sensitivity"],
        ),
        snapshot(
            "PD and LGD sensitivity",
            "What happens if PD or LGD is wrong?",
            (
                "A ten per cent relative increase in PD raises weighted ECL by "
                "SAR 2.28 million. The same relative increase in LGD raises it "
                "by SAR 2.28 million as well — the two are symmetric here "
                "because ECL is multiplicative in both, which is worth stating "
                "so the symmetry is not read as a coincidence."
            ),
            _t("pdlgd", "PD and LGD sensitivity", ["Parameter", "Shock", "ECL impact"],
               [["PD", "+10% relative", "+2.28"],
                ["PD", "−10% relative", "−2.28"],
                ["LGD", "+10% relative", "+2.28"],
                ["LGD", "−10% relative", "−2.28"]],
               {"ECL impact": "SAR million"}),
            "A 10 per cent PD or LGD error moves ECL by SAR 2.28 million.",
            ["pd", "lgd", "sensitivity"],
        ),
        snapshot(
            "Collateral haircut impact",
            "What if collateral values are overstated?",
            (
                "Applying an additional twenty per cent haircut to real estate "
                "collateral raises weighted ECL by SAR 3.10 million, "
                "concentrated in the secured corporate book. The unsecured book "
                "is unaffected by construction. Real estate is the only "
                "collateral class with enough concentration for the haircut to "
                "matter at portfolio level."
            ),
            _t("haircut", "Additional haircut impact",
               ["Collateral class", "Haircut", "ECL impact"],
               [["Real estate", "+20%", "+3.10"],
                ["Cash and equivalents", "+20%", "+0.04"],
                ["Receivables", "+20%", "+0.38"]],
               {"ECL impact": "SAR million"}),
            "A further 20 per cent real estate haircut adds SAR 3.10 million.",
            ["collateral", "haircut"],
        ),
        snapshot(
            "Stage migration scenario",
            "What if the watchlist migrates?",
            (
                "If every borrower currently above the review threshold migrates "
                "to Stage 2, weighted ECL rises by SAR 4.70 million and coverage "
                "by 44.8 basis points. This is a bounding calculation rather "
                "than a forecast: the observed migration rate is below half, so "
                "the realistic impact is materially smaller."
            ),
            _t("migration", "Full watchlist migration",
               ["Measure", "Now", "If all migrate"],
               [["Stage 2 exposure", "113.00", "241.00"],
                ["Weighted ECL", str(weighted_current), "27.47"],
                ["Coverage", "2.17%", "2.62%"]],
               {"Now": "SAR million", "If all migrate": "SAR million"}),
            "Full watchlist migration would add SAR 4.70 million.",
            ["migration", "bounding"],
        ),
        snapshot(
            "Management action comparison",
            "Which management action reduces ECL most per riyal of effort?",
            (
                "Three actions were compared. Tightening limits on the "
                "converged watchlist reduces weighted ECL by SAR 1.85 million; "
                "additional collateral on the same names reduces it by SAR 2.40 "
                "million; and restructuring reduces it by SAR 1.10 million while "
                "extending tenor. The comparison is of modelled effect only and "
                "does not weigh operational cost or customer impact."
            ),
            _t("actions", "Management actions compared",
               ["Action", "ECL reduction", "Names affected"],
               [["Tighten limits", "−1.85", "6"],
                ["Additional collateral", "−2.40", "6"],
                ["Restructure", "−1.10", "3"]],
               {"ECL reduction": "SAR million"}),
            "Additional collateral gives the largest modelled reduction.",
            ["management actions"],
        ),
    ]


def catalogue() -> list[contract.Snapshot]:
    """Every demonstration export, in a stable order."""
    return [
        *_cockpit(),
        *_early_warning(),
        *_what_if(),
        *_scorecard_validation(),
        *_lenses(),
    ]
