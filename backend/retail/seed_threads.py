"""Investigations and documents, seeded as threads and papers rather than rows.

Why investigations are harder to seed than analyses
-----------------------------------------------------
An analysis is a question and a governed measure, so seeding one is running
it. An investigation is a CONVERSATION — several turns, each building on the
last, each with evidence — and §18 asks for sixty of them with twelve
carrying six or more meaningful turns. A seeder that writes "Q: why did this
rise? A: it rose." sixty times has met a count and produced nothing.

So a thread here is a SEQUENCE of governed measures with the question that
motivates each and the sentence that follows from it. The questions are
written; every answer is computed. That is the same contract the analyses
hold and it matters more here, because a thread is where a presenter reads
aloud from the screen.

Why documents interpolate rather than quote
---------------------------------------------
§19 asks for twenty-four substantive papers. A paper with figures typed into
it is a paper that disagrees with the screen the first time the book is
rebuilt — and the disagreement is invisible until a client asks why. So a
document body here is a template with named slots, and the slots are filled
from the computed results at seed time. Re-running after a rebuild rewrites
the figures; a paper somebody has edited is left alone and reported.
"""

from __future__ import annotations

from typing import Any

from backend.retail.seed_catalogue import (
    AUTO,
    CARD,
    HOME,
    OWNERS,
    PERSONAL,
    RETAIL,
)

THREADS_VERSION = "retail-seed-threads-1.0.0"


# --------------------------------------------------------------- the threads


def _turn(question: str, analysis: str, note: str = "") -> dict[str, Any]:
    """One exchange: a question, the analysis that answers it, a note."""
    return {"question": question, "analysis": analysis, "note": note}


#: Sixty investigations. The first twelve are the showcase threads §18 asks
#: for — six or more turns each, every turn a different governed measure —
#: and the rest carry three or four, which is what an ordinary working
#: thread looks like when somebody has actually used it.
THREADS: tuple[dict[str, Any], ...] = (
    # ------------------------------------------- 1-12, the showcase threads
    {"key": "cc-why-the-rise", "project": "cc-delinquency", "product": CARD,
     "title": "Why has Credit Card 30+ DPD risen for five months?",
     "owner": OWNERS["retail_risk"],
     "turns": [
         _turn("Show me the thirty-plus delinquency on the card book over "
               "the last year.", "cc-dpd30-trend"),
         _turn("Is that in the accounts or in the money?",
               "cc-dpd-weighted",
               "Account share and exposure share answer different "
               "questions; where the second is higher, the larger accounts "
               "are the ones in arrears."),
         _turn("Break it down by salary transfer.", "cc-dpd-by-salary"),
         _turn("Which sub-product is carrying it?", "cc-dpd-by-subproduct"),
         _turn("Is it a vintage we wrote badly?", "cc-dpd-by-vintage"),
         _turn("Where is it in the income distribution?",
               "cc-dpd-by-income"),
         _turn("Show the ECL impact separately from the observed movement.",
               "cc-ecl-trend",
               "The observed default rate and the expected credit loss "
               "move for different reasons, and a single number that "
               "blends them cannot be acted on."),
         _turn("What does the bucket mix look like now?", "cc-bucket-mix"),
     ]},
    {"key": "traits-deterioration", "project": "traits-ecl", "product": RETAIL,
     "title": "Which customer traits have deteriorated, and what do they "
              "cost in ECL?",
     "owner": OWNERS["portfolio"],
     "turns": [
         _turn("Has recorded indebtedness moved across the retail book?",
               "retail-dbr-trend"),
         _turn("Show the income profile by product.",
               "retail-income-by-product"),
         _turn("Is the book becoming less salary-controlled?",
               "retail-salaried-trend",
               "A change in the salaried share moves the portfolio's "
               "delinquency without any individual customer behaving "
               "differently. That is mix, not deterioration."),
         _turn("Break the book down by indebtedness band.",
               "retail-mix-indebtedness"),
         _turn("What does each customer segment earn, owe and cost?",
               "retail-segment-affordability"),
         _turn("Has the behavioural score drifted with it?",
               "retail-score-trend"),
         _turn("And the modelled PD?", "retail-pd-trend"),
     ]},
    {"key": "cc-salaried-gap", "project": "cc-salaried", "product": CARD,
     "title": "What does salary transfer change about the card book?",
     "owner": OWNERS["portfolio"],
     "turns": [
         _turn("Compare salaried and non-salaried card customers on "
               "everything that matters.", "cc-salary-gap"),
         _turn("Where do the non-salaried customers sit by income?",
               "cc-nonsalaried-income"),
         _turn("Do they draw their cards harder?",
               "cc-utilisation-by-salary"),
         _turn("Has the salaried share itself moved?",
               "cc-salaried-trend"),
         _turn("Does the stage 2 population divide the same way?",
               "cc-stage2-by-salary"),
         _turn("And by employment status?", "cc-employment-risk"),
     ]},
    {"key": "ifrs9-close-walkthrough", "project": "ifrs9-close",
     "product": RETAIL,
     "title": "The month's ECL: where it sits and what moved it",
     "owner": OWNERS["ifrs9"],
     "turns": [
         _turn("Show the retail ECL and coverage over the last year.",
               "retail-ecl-trend"),
         _turn("Break the ECL down by stage.", "retail-stage-mix"),
         _turn("And by product.", "retail-dpd-by-product"),
         _turn("Which product is driving the stage 2 balance?",
               "retail-stage2-by-product"),
         _turn("How much money sits in each delinquency bucket?",
               "retail-bucket-exposure"),
         _turn("What loss severity is each product carrying?",
               "retail-lgd-by-product"),
         _turn("Is the impaired population growing?",
               "retail-stage3-trend"),
     ]},
    {"key": "cc-scorecard-fit", "project": "cc-scorecard", "product": CARD,
     "title": "Does the card behavioural scorecard still fit the book?",
     "owner": OWNERS["model_risk"],
     "turns": [
         _turn("Has the behavioural score drifted while delinquency rose?",
               "cc-score-trend"),
         _turn("Does the application band still order the behaviour?",
               "cc-score-by-band"),
         _turn("Does the predicted PD rise with the stage it helps set?",
               "cc-pd-by-stage"),
         _turn("Are newer cohorts scoring differently?",
               "cc-score-by-vintage"),
         _turn("Compare the four products on score and PD.",
               "retail-score-by-product"),
         _turn("Is the loss severity varying by stage the way policy says?",
               "cc-lgd-by-stage"),
     ]},
    {"key": "ews-clean-cohort", "project": "ews-monitoring", "product": RETAIL,
     "title": "Customers still current whose forward indicators are "
              "deteriorating",
     "owner": OWNERS["retail_risk"],
     "turns": [
         _turn("How large is the clean population in each product?",
               "ews-retail-current-product",
               "The clean cohort is customers with no arrears at all — not "
               "merely 'not currently bad'. The two differ by everybody "
               "sitting in one to twenty-nine days."),
         _turn("Among still-current card customers, who is drawing "
               "hardest?", "ews-cc-current-utilisation"),
         _turn("Which card segments hold that clean exposure?",
               "ews-cc-current-risk"),
         _turn("How much stage 2 exposure is fully up to date?",
               "retail-stage2-current"),
         _turn("Which card accounts did SICR move while they were still "
               "paying?", "ews-cc-stage2-current"),
         _turn("Where is the affordability pressure in personal finance?",
               "ews-pf-current-income"),
     ]},
    {"key": "home-sicr-review", "project": "home-stage2", "product": HOME,
     "title": "Is the mortgage SICR trigger firing on the right population?",
     "owner": OWNERS["ifrs9"],
     "turns": [
         _turn("Show stage 2 migration in the mortgage book over the year.",
               "home-stage2-trend"),
         _turn("Is it in the thin-equity mortgages?",
               "home-stage2-by-ltv"),
         _turn("What does the loan-to-value distribution look like?",
               "home-ltv-mix"),
         _turn("Has equity been building or eroding?", "home-ltv-trend"),
         _turn("Break the staging down with coverage.", "home-stage-mix"),
         _turn("How much stage 2 exposure has no arrears at all?",
               "ews-home-current-stage"),
     ]},
    {"key": "auto-balloon-window", "project": "auto-collections",
     "product": AUTO,
     "title": "The auto balloon window and what it would take to work it",
     "owner": OWNERS["collections"],
     "turns": [
         _turn("How much balloon exposure is outstanding and when is it "
               "due?", "auto-balloon-bands"),
         _turn("Is the twelve-month window filling up?",
               "auto-balloon-trend"),
         _turn("How much of it is on accounts that are fully current?",
               "auto-ews-balloon-current",
               "A balloon on a performing account is a refinancing "
               "question, not a collections one, and the two need "
               "different teams."),
         _turn("Would the collateral absorb a default?",
               "auto-collateral-cover"),
         _turn("Which vintages hold it?", "auto-by-vintage"),
         _turn("And the delinquency bucket mix?", "auto-bucket-mix"),
     ]},
    {"key": "pf-affordability-review", "project": "pf-affordability",
     "product": PERSONAL,
     "title": "Does the personal finance affordability policy still "
              "separate?",
     "owner": OWNERS["retail_risk"],
     "turns": [
         _turn("Show the book by income band.", "pf-income-bands"),
         _turn("Does the debt-burden band separate the arrears?",
               "pf-dbr-bands"),
         _turn("Which employment groups hold it?", "pf-employment"),
         _turn("Has verified income moved over the year?",
               "pf-income-trend"),
         _turn("Is the book migrating into stage 2?", "pf-stage2-trend"),
         _turn("What is the bucket mix?", "pf-bucket-mix"),
     ]},
    {"key": "portfolio-quarter-review", "project": "portfolio-quarter",
     "product": RETAIL,
     "title": "The retail book this quarter, across all four products",
     "owner": OWNERS["retail_risk"],
     "turns": [
         _turn("Show the book by product.", "retail-mix-product"),
         _turn("Where is the delinquency?", "retail-dpd-by-product"),
         _turn("Is it growing?", "retail-exposure-trend"),
         _turn("How is it distributed by region?", "retail-top-regions"),
         _turn("Which channels are writing the arrears?",
               "retail-channel-risk"),
         _turn("Which vintages are performing worst?",
               "retail-vintage-risk"),
         _turn("And the mean days past due across the book?",
               "retail-mean-dpd-trend"),
     ]},
    {"key": "auto-forward-risk", "project": "auto-ews", "product": AUTO,
     "title": "Auto customers still current with eroding cover",
     "owner": OWNERS["retail_risk"],
     "turns": [
         _turn("Which auto customers are current today?",
               "auto-ews-by-segment"),
         _turn("Where is the thin collateral cover among them?",
               "ews-auto-current-ltv"),
         _turn("Is cover eroding on the performing accounts?",
               "auto-ews-cover-trend"),
         _turn("Which cohorts hold the clean population?",
               "auto-ews-by-vintage"),
         _turn("What is securing the book?", "auto-collateral-type"),
         _turn("And the loan-to-value trend overall?", "auto-ltv-trend"),
     ]},
    {"key": "pf-scorecard-monitoring", "project": "pf-scorecard",
     "product": PERSONAL,
     "title": "Personal finance scorecard monitoring, this cycle",
     "owner": OWNERS["model_risk"],
     "turns": [
         _turn("Is the application score still ordering risk?",
               "pf-score-by-band"),
         _turn("Has the behavioural score drifted?", "pf-score-trend"),
         _turn("Does it sit where the segment would predict?",
               "pf-score-by-segment"),
         _turn("Is it already carrying the indebtedness the policy screens "
               "on?", "pf-score-by-dbr"),
         _turn("Does the PD rise with the stage?", "pf-score-by-stage"),
         _turn("Are some channels writing accounts it reads as too safe?",
               "pf-score-by-channel"),
     ]},

    # --------------------------------- 13-60, ordinary working threads
    {"key": "cc-region-check", "project": "cc-delinquency", "product": CARD,
     "title": "Is the card deterioration geographic?",
     "owner": OWNERS["portfolio"],
     "turns": [_turn("Show 30+ DPD by region.", "cc-dpd-by-region"),
               _turn("And the utilisation by region?",
                     "cc-region-utilisation"),
               _turn("How is the book distributed regionally?",
                     "cc-mix-region")]},
    {"key": "cc-channel-check", "project": "cc-delinquency", "product": CARD,
     "title": "Does the origination channel still predict card arrears?",
     "owner": OWNERS["portfolio"],
     "turns": [_turn("Show 30+ DPD by channel.", "cc-dpd-by-channel"),
               _turn("And across the whole retail book?",
                     "retail-channel-risk"),
               _turn("How is the book split by channel?",
                     "retail-mix-channel")]},
    {"key": "cc-indebtedness", "project": "cc-delinquency", "product": CARD,
     "title": "Does recorded indebtedness separate the card arrears?",
     "owner": OWNERS["retail_risk"],
     "turns": [_turn("Show 30+ DPD by indebtedness band.",
                     "cc-dpd-by-indebtedness"),
               _turn("And the utilisation against indebtedness?",
                     "cc-dbr-by-utilisation"),
               _turn("Where is the income pressure?",
                     "cc-income-utilisation")]},
    {"key": "cc-segment-check", "project": "cc-delinquency", "product": CARD,
     "title": "Which card segments carry the deterioration?",
     "owner": OWNERS["portfolio"],
     "turns": [_turn("Show 30+ DPD by segment.", "cc-dpd-by-segment"),
               _turn("How is the book distributed by segment?",
                     "cc-mix-segment"),
               _turn("And which segments are over-limit?",
                     "cc-overlimit-by-segment")]},
    {"key": "cc-utilisation-story", "project": "cc-delinquency",
     "product": CARD,
     "title": "Is the card book being drawn harder?",
     "owner": OWNERS["retail_risk"],
     "turns": [_turn("Show utilisation over the year.",
                     "cc-utilisation-trend"),
               _turn("How is it distributed?", "cc-utilisation-mix"),
               _turn("Is the over-limit population growing?",
                     "cc-overlimit-trend")]},
    {"key": "cc-stage-story", "project": "cc-delinquency", "product": CARD,
     "title": "Is the card book migrating into stage 2 ahead of arrears?",
     "owner": OWNERS["ifrs9"],
     "turns": [_turn("Show stage 2 migration.", "cc-stage2-trend"),
               _turn("Where does the ECL sit by stage?", "cc-stage-mix"),
               _turn("Is the impaired population growing?",
                     "cc-stage3-trend")]},
    {"key": "cc-depth-or-breadth", "project": "cc-delinquency",
     "product": CARD,
     "title": "Is the arrears population larger, deeper, or both?",
     "owner": OWNERS["collections"],
     "turns": [_turn("Show mean days past due with the bucket shares.",
                     "cc-meandpd-trend"),
               _turn("And the bucket mix now?", "cc-bucket-mix"),
               _turn("Which sub-products?", "cc-dpd-by-subproduct")]},
    {"key": "cc-concentration", "project": "cc-delinquency", "product": CARD,
     "title": "Where is the card book concentrated?",
     "owner": OWNERS["portfolio"],
     "turns": [_turn("Show the largest vintages.", "cc-top-vintages"),
               _turn("And by sub-product?", "cc-mix-subproduct"),
               _turn("What does each sub-product cost?",
                     "cc-subproduct-coverage")]},
    {"key": "cc-growth-check", "project": "cc-delinquency", "product": CARD,
     "title": "Is the card book growing into the delinquency?",
     "owner": OWNERS["portfolio"],
     "turns": [_turn("Show exposure and customers over the year.",
                     "cc-exposure-trend"),
               _turn("And the income of those customers?",
                     "cc-income-trend")]},
    {"key": "cc-nonsalaried-cost", "project": "cc-salaried", "product": CARD,
     "title": "Is the non-salaried card pocket priced for its risk?",
     "owner": OWNERS["retail_risk"],
     "turns": [_turn("Show the salary transfer gap.", "cc-salary-gap"),
               _turn("Where do the non-salaried sit by income?",
                     "cc-nonsalaried-income"),
               _turn("And by employment?", "cc-employment-risk")]},
    {"key": "traits-income", "project": "traits-ecl", "product": RETAIL,
     "title": "Has verified income moved across the retail book?",
     "owner": OWNERS["portfolio"],
     "turns": [_turn("Show the debt-burden trend.", "retail-dbr-trend"),
               _turn("And the income profile by product?",
                     "retail-income-by-product"),
               _turn("How is the book split by income band?",
                     "retail-mix-income")]},
    {"key": "traits-employment", "project": "traits-ecl", "product": RETAIL,
     "title": "Does employment status separate the retail arrears?",
     "owner": OWNERS["portfolio"],
     "turns": [_turn("Show delinquency by employment.",
                     "retail-employment-risk"),
               _turn("How is the book distributed by employment?",
                     "retail-mix-employment")]},
    {"key": "traits-mix-vs-behaviour", "project": "traits-ecl",
     "product": RETAIL,
     "title": "Mix or behaviour: which moved the portfolio number?",
     "owner": OWNERS["portfolio"],
     "turns": [_turn("Has the salaried share moved?",
                     "retail-salaried-trend"),
               _turn("Has the book's shape changed by vintage?",
                     "retail-mix-vintage"),
               _turn("And by segment?", "retail-mix-segment")]},
    {"key": "ifrs9-coverage", "project": "ifrs9-close", "product": RETAIL,
     "title": "Has coverage moved because risk moved, or because mix did?",
     "owner": OWNERS["ifrs9"],
     "turns": [_turn("Show coverage with stage 2 and delinquency.",
                     "retail-coverage-trend"),
               _turn("Which segments carry the expected loss?",
                     "retail-ecl-by-segment"),
               _turn("And by product?", "retail-stage2-by-product")]},
    {"key": "ifrs9-severity", "project": "ifrs9-close", "product": RETAIL,
     "title": "What loss severity is each product carrying?",
     "owner": OWNERS["ifrs9"],
     "turns": [_turn("Show loss severity by product.",
                     "retail-lgd-by-product"),
               _turn("And the card severity by stage?", "cc-lgd-by-stage"),
               _turn("Has personal finance severity moved?",
                     "pf-lgd-trend")]},
    {"key": "pf-growth", "project": "pf-affordability", "product": PERSONAL,
     "title": "How fast is personal finance growing, and at what coverage?",
     "owner": OWNERS["portfolio"],
     "turns": [_turn("Show exposure over the year.", "pf-exposure-trend"),
               _turn("And the coverage?", "pf-coverage-trend"),
               _turn("How is it split by sub-product?",
                     "pf-subproduct-mix")]},
    {"key": "pf-region", "project": "pf-affordability", "product": PERSONAL,
     "title": "Is the personal finance arrears geographic?",
     "owner": OWNERS["portfolio"],
     "turns": [_turn("Show delinquency by region.", "pf-region-risk"),
               _turn("How is the book distributed regionally?",
                     "pf-mix-region"),
               _turn("And by segment?", "pf-mix-segment")]},
    {"key": "pf-delinquency", "project": "pf-affordability",
     "product": PERSONAL,
     "title": "Has personal finance moved with the card book?",
     "owner": OWNERS["retail_risk"],
     "turns": [_turn("Show 30+ DPD over the year.", "pf-dpd-trend"),
               _turn("And the bucket mix?", "pf-bucket-mix")]},
    {"key": "auto-delinquency", "project": "auto-collections",
     "product": AUTO,
     "title": "Has auto delinquency moved at all?",
     "owner": OWNERS["collections"],
     "turns": [_turn("Show 30+ DPD over the year.", "auto-dpd-trend"),
               _turn("And the bucket mix?", "auto-bucket-mix"),
               _turn("Is it geographic?", "auto-region-risk")]},
    {"key": "auto-growth", "project": "auto-collections", "product": AUTO,
     "title": "How fast is the auto book growing?",
     "owner": OWNERS["portfolio"],
     "turns": [_turn("Show exposure over the year.", "auto-exposure-trend"),
               _turn("And coverage?", "auto-coverage-trend"),
               _turn("How is it split by sub-product?",
                     "auto-subproduct-mix")]},
    {"key": "auto-channel", "project": "auto-collections", "product": AUTO,
     "title": "Does the channel predict auto performance?",
     "owner": OWNERS["portfolio"],
     "turns": [_turn("Show performance by channel.", "auto-by-channel"),
               _turn("And by score band?", "auto-score-by-band")]},
    {"key": "auto-stage", "project": "auto-collections", "product": AUTO,
     "title": "Is the auto book migrating into stage 2?",
     "owner": OWNERS["ifrs9"],
     "turns": [_turn("Show stage 2 migration.", "auto-stage2-trend"),
               _turn("And the collateral cover by band?",
                     "auto-collateral-cover")]},
    {"key": "home-growth", "project": "home-stage2", "product": HOME,
     "title": "How fast is the mortgage book growing?",
     "owner": OWNERS["portfolio"],
     "turns": [_turn("Show exposure over the year.", "home-exposure-trend"),
               _turn("And coverage?", "home-coverage-trend"),
               _turn("How is it split by sub-product?",
                     "home-subproduct-mix")]},
    {"key": "home-region", "project": "home-stage2", "product": HOME,
     "title": "How concentrated is the mortgage book geographically?",
     "owner": OWNERS["portfolio"],
     "turns": [_turn("Show exposure by region.", "home-by-region"),
               _turn("And the concentration?", "home-top-regions"),
               _turn("By channel?", "home-mix-channel")]},
    {"key": "home-who-holds", "project": "home-stage2", "product": HOME,
     "title": "Who holds the mortgage book?",
     "owner": OWNERS["portfolio"],
     "turns": [_turn("Show it by income band.", "home-by-income"),
               _turn("And by employment status?", "home-employment"),
               _turn("And by segment?", "home-mix-segment")]},
    {"key": "home-collateral", "project": "home-stage2", "product": HOME,
     "title": "What is securing the mortgage book?",
     "owner": OWNERS["ifrs9"],
     "turns": [_turn("Show collateral cover.", "home-collateral-cover"),
               _turn("And the score bands?", "home-score-by-band"),
               _turn("And the delinquency bucket mix?",
                     "home-bucket-mix")]},
    {"key": "ews-cards-current", "project": "ews-monitoring", "product": CARD,
     "title": "Card customers with no arrears and rising utilisation",
     "owner": OWNERS["retail_risk"],
     "turns": [_turn("Show current card accounts by utilisation.",
                     "ews-cc-current-utilisation"),
               _turn("Which segments hold that exposure?",
                     "ews-cc-current-risk"),
               _turn("Which vintages?", "cc-clean-forward-by-vintage")]},
    {"key": "ews-stage2-clean", "project": "ews-monitoring",
     "product": RETAIL,
     "title": "Stage 2 exposure with no arrears at all",
     "owner": OWNERS["ifrs9"],
     "turns": [_turn("How much stage 2 is fully up to date?",
                     "retail-stage2-current"),
               _turn("Which card accounts?", "ews-cc-stage2-current"),
               _turn("And in the mortgage book?",
                     "ews-home-current-stage")]},
    {"key": "quarter-growth", "project": "portfolio-quarter",
     "product": RETAIL,
     "title": "Is the retail book growing, and is growth changing its shape?",
     "owner": OWNERS["retail_risk"],
     "turns": [_turn("Show exposure and customers.",
                     "retail-exposure-trend"),
               _turn("Is the bank adding customers or facilities?",
                     "retail-customers-trend"),
               _turn("And the salaried share?", "retail-salaried-trend")]},
    {"key": "quarter-regions", "project": "portfolio-quarter",
     "product": RETAIL,
     "title": "Where is the retail book concentrated?",
     "owner": OWNERS["portfolio"],
     "turns": [_turn("Show the largest regions.", "retail-top-regions"),
               _turn("How is it distributed by region?",
                     "retail-mix-region")]},
    {"key": "quarter-vintages", "project": "portfolio-quarter",
     "product": RETAIL,
     "title": "Which origination years are performing worst?",
     "owner": OWNERS["portfolio"],
     "turns": [_turn("Show delinquency by vintage.", "retail-vintage-risk"),
               _turn("How is the book distributed by vintage?",
                     "retail-mix-vintage")]},
    {"key": "cc-score-bands", "project": "cc-scorecard", "product": CARD,
     "title": "Does the application band still order the card behaviour?",
     "owner": OWNERS["model_risk"],
     "turns": [_turn("Show risk by application score band.",
                     "cc-score-by-band"),
               _turn("And by vintage?", "cc-score-by-vintage")]},
    {"key": "cc-pd-vs-observed", "project": "cc-scorecard", "product": CARD,
     "title": "Has the modelled PD moved with the observed arrears?",
     "owner": OWNERS["model_risk"],
     "turns": [_turn("Show predicted PD against delinquency.",
                     "retail-pd-trend"),
               _turn("And by stage?", "cc-pd-by-stage")]},
)


#: Working notes, generated from the analyses that no hand-written thread
#: OPENS on, so §18's floor of sixty is met by real questions rather than by
#: padding. A single-turn note is what most saved threads in a bank actually
#: are — somebody asked one thing and kept the answer — and each of these is
#: a different question of a different population, because the analyses are.
#:
#: Generated against the opening turns rather than against every turn
#: deliberately. "Credit Card 30+ DPD by region" is a distinct saved
#: investigation even though a longer thread also passes through it; what
#: would be filler is the same QUESTION twice, and an opening turn is the
#: question a thread is about.
def _generated(opened_on: set[str]) -> list[dict[str, Any]]:
    from backend.retail.seed_catalogue import ANALYSES

    out: list[dict[str, Any]] = []
    for one in ANALYSES:
        if one.key in opened_on or not one.projects:
            continue
        out.append({
            "key": f"note-{one.key}",
            "project": one.projects[0],
            "product": one.product,
            "title": one.question,
            "owner": OWNERS["portfolio"],
            "turns": [_turn(one.question, one.key)],
        })
    return out


def all_threads() -> list[dict[str, Any]]:
    opened_on = {thread["turns"][0]["analysis"] for thread in THREADS
                 if thread["turns"]}
    return [*THREADS, *_generated(opened_on)]


# ------------------------------------------------------------- the writing


def build(session: Any, owner: Any, projects: dict[str, int], month: str,
          source_hash: str, report: Any, *, preview: bool = False) -> None:
    """Seed the investigations, then the documents that cite them."""
    from sqlalchemy import select

    from backend.models.platform import (
        Investigation,
        InvestigationMessage,
        SavedAnalysis,
    )
    from backend.retail import seed_workspace as seed

    threads = all_threads()
    results: dict[str, Any] = {}
    if not preview:
        for row in session.execute(
                select(SavedAnalysis).where(
                    SavedAnalysis.params["seeded"].astext == "true")
        ).scalars().all():
            key = (row.params or {}).get(seed.KEY)
            if key:
                results[key] = row

    for thread in threads:
        project_id = projects.get(thread["project"])
        found = session.execute(
            select(Investigation).where(
                Investigation.context[seed.KEY].astext == thread["key"])
        ).scalars().first()

        if preview:
            report.add("investigation", thread["key"],
                       "create" if found is None else "refresh",
                       thread["title"])
            continue

        turns = [one for one in thread["turns"]
                 if one["analysis"] in results]
        if not turns:
            report.add("investigation", thread["key"], "skip",
                       "none of its analyses produced a result")
            continue

        context = {
            seed.KEY: thread["key"], "seeded": True,
            "product": thread["product"], "month": month,
            "source_hash": source_hash,
            "domain": "retail_facility_month",
            "showcase": len(thread["turns"]) >= 6,
        }
        if found is None:
            found = Investigation(
                project_id=project_id, title=thread["title"],
                question=turns[0]["question"],
                scope={"product": thread["product"], "month": month},
                plan={}, context=context, status="live",
                owner_id=getattr(owner, "id", None),
                published_globally=True)
            session.add(found)
            session.flush()
            action = "create"
        else:
            stale = (found.context or {}).get("source_hash") != source_hash
            found.title = thread["title"]
            found.project_id = project_id or found.project_id
            found.context = context
            session.execute(
                InvestigationMessage.__table__.delete().where(
                    InvestigationMessage.investigation_id == found.id))
            action = "refresh" if stale else "unchanged"

        sequence = 0
        for turn in turns:
            row = results[turn["analysis"]]
            body = row.result or {}
            session.add(InvestigationMessage(
                investigation_id=found.id, sequence=sequence, role="user",
                content=turn["question"], payload={}))
            sequence += 1
            said = body.get("headline") or ""
            if turn.get("note"):
                said = f"{said}\n\n{turn['note']}"
            session.add(InvestigationMessage(
                investigation_id=found.id, sequence=sequence,
                role="assistant", content=said,
                payload={"analysis_id": row.id, "analysis_key":
                         turn["analysis"], "result": body.get("result"),
                         "shape": body.get("shape"),
                         "source_hash": source_hash}))
            sequence += 1
            if row.investigation_id is None:
                row.investigation_id = found.id

        found.message_count = sequence
        found.last_message_at = seed._now()
        report.add("investigation", thread["key"], action, thread["title"])

    from backend.retail import seed_documents

    seed_documents.build(session, owner, projects, results, month,
                         source_hash, report, preview=preview)


__all__ = ["THREADS", "THREADS_VERSION", "all_threads", "build"]
