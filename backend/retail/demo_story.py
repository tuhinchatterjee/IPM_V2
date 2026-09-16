"""The five-act presenter story, resolved against the snapshot on the machine.

§22 asks for a Demo Story a presenter can resume, with a breadcrumb, the
source month and the CURRENT artifact IDs. The last of those is the whole
point and the reason this is a module rather than a document.

Why the ids cannot be written down
------------------------------------
A presenter guide that names "investigation 1012" is correct on the machine
it was written on and wrong on every other one — the ids are database
sequence values and a fresh install produces different ones. The same goes
for the month, the source hash, and every figure the presenter is about to
read aloud.

So the story is declared as INTENT — which act, what the presenter says,
what the screen should do — and every concrete reference is resolved when
the story is asked for: the project by its seed key, the investigation by
its seed key, the month from the book, the figures from the computed
analyses. A story that cannot resolve a step says so on that step rather
than sending somebody to a dead link in front of a client.

What it is not
---------------
§22: "It is a guided navigation aid using real analyses, not a slideshow of
fake answers. Normal free-text navigation must still work." Nothing here
pre-answers anything. Each step carries the route to open and the prompt to
type; the product answers it live, through the same path a typed question
takes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

STORY_VERSION = "retail-demo-story-1.0.0"


@dataclass(frozen=True)
class Step:
    """One move in the story: what to do, and what should come back."""

    key: str
    #: What the presenter says or types. Empty for a navigation-only step.
    prompt: str = ""
    #: Where the step happens. `{...}` placeholders are resolved.
    route: str = ""
    #: The control to press, by its test id, where the step is a click.
    control: str = ""
    #: What the presenter should tell the room.
    narration: str = ""
    #: What the screen must show for the step to have worked.
    expect: tuple[str, ...] = ()
    #: Seeded objects this step depends on, by seed key.
    needs: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Act:
    key: str
    title: str
    purpose: str
    steps: tuple[Step, ...]


ACTS: tuple[Act, ...] = (
    Act("attention", "The system has already found an issue",
        "The presenter opens the product and something is already waiting. "
        "No upload, no blank page, no 'let me just run this'.",
        (
            Step("open-cockpit", route="/",
                 narration="Open the Cockpit. Requires Attention is "
                           "computed from the book, not seeded — the card "
                           "at the top is there because the measure moved.",
                 expect=("a Requires Attention card naming Credit Card",
                         "the month it was computed for",
                         "the materiality behind it")),
            Step("open-case", control="risk-case-investigate",
                 narration="Click Investigate. A persisted investigation "
                           "opens with its first answer already in it.",
                 expect=("an investigation thread, not a blank composer",
                         "the first answer, its chart and its scope"),
                 needs={"investigation": "cc-why-the-rise"}),
            Step("why", prompt="What are the reasons for this rise?",
                 narration="Ask it in the presenter's own words. The "
                           "product resolves the product, the period and "
                           "the measure from the thread rather than asking.",
                 expect=("worsening, cures and new accounts separated",
                         "a rate bridge that reconciles",
                         "the ECL movement reported separately",
                         "the improving offsets named")),
            Step("drill",
                 prompt="Which sub-product and customer characteristics "
                        "explain most of it?",
                 narration="Drill to salaried and non-salaried and to the "
                           "card sub-products. The sub-product taxonomy is "
                           "a governed derived dimension, joined on "
                           "facility id.",
                 expect=("the four card sub-products with real exposure",
                         "salaried against non-salaried",
                         "the material pockets flagged")),
            Step("top-customers",
                 prompt="Show the top five affected customers.",
                 narration="Actual governed membership, with exposure and "
                           "ECL impact. Not a sample.",
                 expect=("five customers by id",
                         "their exposure and ECL contribution")),
            Step("save-and-export", control="investigation-save",
                 narration="Save it into the Credit Card project and "
                           "download the Word report.",
                 expect=("the analysis appears under the project",
                         "a .docx that opens with its charts"),
                 needs={"project": "cc-delinquency"}),
        )),

    Act("traits", "Ask an independent trait question",
        "Back to the Cockpit, then a fresh thread. This proves the second "
        "question is answered from the book rather than from the first "
        "thread's context.",
        (
            Step("back", route="/",
                 narration="Use Back. The Cockpit returns with its scope "
                           "intact.",
                 expect=("the cockpit as it was", "no lost context")),
            Step("traits",
                 prompt="Tell me what customer traits have deteriorated and "
                        "what is the impact on ECL because of them.",
                 narration="A fresh thread. It resolves the quarter itself "
                           "and scopes to Retail rather than inheriting the "
                           "card scope from the previous conversation.",
                 expect=("the quarter and the comparison window stated",
                         "every scorecard input reviewed, not the top three",
                         "matched change separated from mix",
                         "score-point and band migration",
                         "the reconciled ECL bridge"),
                 needs={"investigation": "traits-deterioration"}),
            Step("chain",
                 prompt="Show the full income-to-score-to-PD-to-ECL "
                        "calculation for the largest five contributors.",
                 narration="The complete per-customer chain. It stops at "
                           "the arithmetic; it does not claim the income "
                           "change caused the score change.",
                 expect=("one row per customer through every step",
                         "no causal claim attached")),
            Step("export", control="investigation-export",
                 narration="Download the Word report for this thread.",
                 expect=("a .docx with the trait tables and the bridge",)),
        )),

    Act("validate", "Validate that the scorecard still fits",
        "From the analysis to the model behind it. This is where a credit "
        "conversation becomes a model-risk one.",
        (
            Step("open-validation", route="/scorecard-validation",
                 narration="Open Scorecard Validation and choose the Credit "
                           "Card behavioural scorecard.",
                 expect=("every registered scorecard listed from the "
                         "registry",
                         "eleven category cards")),
            Step("data-category", control="Data & Representativeness",
                 narration="Run Data & Representativeness. It reports what "
                           "the model was developed on and how today's book "
                           "differs.",
                 expect=("the development window, rows, defaults and rate",
                         "every model input compared on the approved bins",
                         "development ODR against the latest closed cohort",
                         "the current month with no default rate and its "
                         "horizon named")),
            Step("discrimination", control="Discrimination",
                 narration="Discrimination. The card book ranks cleanly; "
                           "its three sibling products carry a local "
                           "inversion, which is the comparison the sibling "
                           "test reports.",
                 expect=("bands with bounds, counts, intervals and PD",
                         "any inversion with its support and persistence")),
            Step("calibration", control="Calibration & Accuracy",
                 narration="Calibration. Observed default runs above "
                           "predicted in every band — a level problem, not "
                           "a ranking problem.",
                 expect=("O/E against its limit and the limit's source",
                         "the shared under-prediction finding",
                         "the four explanations worked separately")),
            Step("comment", control="scv-add-comment",
                 prompt="The development sample reads the same O/E, so the "
                        "gap predates this book. Recalibration should be "
                        "dated rather than treated as drift.",
                 narration="Add a comment on the finding, with an "
                           "assessment and a severity of your own.",
                 expect=("the comment on screen with its assessment",
                         "the author's severity labelled as theirs",
                         "the run and data version it was written against")),
            Step("report", control="a:has-text('Draft report')",
                 narration="Download the validation report and find that "
                           "exact comment in it.",
                 expect=("a .docx with fifteen sections and charts",
                         "the comment reproduced in section 13.1",
                         "every unrun test present with its reason")),
        )),

    Act("forward", "Move from lagging results to leading warning",
        "Everything so far is lagging. This act is about the customers a "
        "decision is still available for.",
        (
            Step("open-ews", route="/early-warning",
                 prompt="These are largely lagging indicators. Show me "
                        "customers who are still current but whose leading "
                        "indicators are deteriorating.",
                 narration="Open Early Warning. Choose the clean cohort — "
                           "fully current, no hard trigger — rather than "
                           "the wider 'not currently bad'.",
                 expect=("both cohorts offered with their definitions",
                         "the clean cohort materially smaller than the "
                         "wider one")),
            Step("compare-cohorts", control="ews-cohort-clean_forward_risk",
                 narration="Compare the already-delinquent population with "
                           "the fully current one. The difference is the "
                           "customers collections is already working.",
                 expect=("two counts, separately labelled",
                         "the rule for each stated on screen")),
            Step("drill", control="ews-product-CREDIT_CARD",
                 narration="Drill Credit Card, then classification, then "
                           "sub-product, then a customer.",
                 expect=("classification under the product",
                         "sub-product under the classification",
                         "a customer with their reasons and layers")),
            Step("evidence", control="ews-customer-first",
                 narration="Open a customer. Reason, layer, behavioural "
                           "history and bureau recency — with the bureau "
                           "shown as last-observed, not a fresh pull.",
                 expect=("the four layers with their contributions",
                         "bureau recency stated",
                         "missing behavioural history shown as missing")),
        )),

    Act("stress", "Stress the exact cohort, decide and document",
        "The cohort becomes a scenario, the scenario becomes a decision, "
        "and the decision becomes a paper somebody signs.",
        (
            Step("export", control="ews-export-whatif",
                 narration="Export the selected cohort to What-If. The "
                           "membership is written down and immutable — the "
                           "scenario runs on those customers, not on a "
                           "filter re-evaluated later.",
                 expect=("the thread opens with the cohort's baseline",
                         "the exact membership count",
                         "a link back to where it came from")),
            Step("method", control="ews-whatif-method-delta",
                 narration="Choose the method before the first run. Delta "
                           "is the calculation of record; the XGBoost "
                           "challenger is reported beside it.",
                 expect=("the choice offered before anything runs",
                         "the method named on the result")),
            Step("income", prompt="Reduce verified income by 10%",
                 narration="The propagation, the ECL waterfall, the "
                           "affected population and the hierarchy "
                           "materiality.",
                 expect=("the waterfall reconciling exactly",
                         "affected facilities and customers counted",
                         "materiality to product and to Retail")),
            Step("workbook", control="whatif-download-workbook",
                 narration="Download the detailed workbook. No gridlines, "
                           "formulas in the totals, every propagation "
                           "sheet.",
                 expect=("a .xlsx of twenty or more sheets",
                         "the waterfall reconciling in the sheet too")),
            Step("migration",
                 prompt="Move 20% of 30-59 DPD exposure to 90+",
                 narration="If the clean selection holds no such accounts, "
                           "the product says so and asks whether to switch "
                           "to a broader authorised selection. It does not "
                           "widen silently.",
                 expect=("either the migration on eligible accounts",
                         "or an honest refusal naming the reason")),
            Step("save-reopen", control="whatif-save",
                 narration="Save the scenario, reopen it in a new session, "
                           "and the whole thread is there.",
                 expect=("the thread restored with every turn",
                         "the same baseline and membership")),
            Step("document", route="/documents",
                 narration="Attach the analysis and the workbook to the "
                           "committee note and send it for review.",
                 expect=("the note with its evidence rail populated",
                         "the review state changing"),
                 needs={"document": "whatif-committee-note"}),
            Step("live-lens", route="/lenses",
                 narration="Return to the live Credit Card dashboard. The "
                           "baseline is unchanged — a hypothetical did not "
                           "move the book.",
                 expect=("the card dashboard as it was",
                         "the LIVE badge with the snapshot month"),
                 needs={"lens": "retail-credit-card"}),
        )),
)


# ------------------------------------------------------------- resolution


def _resolved(session: Any) -> dict[str, dict[str, Any]]:
    """Every seeded object this story points at, by kind and seed key."""
    from sqlalchemy import select

    from backend.models.platform import (
        Document,
        Investigation,
        Lens,
        Project,
        SavedAnalysis,
    )
    from backend.retail.seed_workspace import KEY

    out: dict[str, dict[str, Any]] = {
        "project": {}, "investigation": {}, "document": {}, "lens": {},
        "analysis": {},
    }
    for row in session.execute(select(Project)).scalars().all():
        key = (row.default_context or {}).get(KEY)
        if key:
            out["project"][key] = {"id": row.id, "title": row.name,
                                   "href": f"/projects/{row.id}"}
    for row in session.execute(select(Investigation)).scalars().all():
        key = (row.context or {}).get(KEY)
        if key:
            out["investigation"][key] = {
                "id": row.id, "title": row.title,
                "href": f"/investigations/{row.id}",
                "turns": row.message_count or 0}
    for row in session.execute(
            select(Document).where(Document.is_current.is_(True))
    ).scalars().all():
        if row.seed_key:
            out["document"][row.seed_key] = {
                "id": row.id, "title": row.title,
                "href": f"/documents/{row.id}", "status": row.status}
    for row in session.execute(select(Lens)).scalars().all():
        out["lens"][row.slug] = {"id": row.id, "title": row.name,
                                 "href": f"/lenses/{row.id}"}
    for row in session.execute(
            select(SavedAnalysis).where(
                SavedAnalysis.params["seeded"].astext == "true")
    ).scalars().all():
        key = (row.params or {}).get(KEY)
        if key:
            out["analysis"][key] = {"id": row.id, "title": row.title,
                                    "href": f"/analyses/{row.id}"}
    return out


def story(session: Any) -> dict[str, Any]:
    """The story, with every reference resolved against this installation."""
    from backend.retail import measures

    found = _resolved(session)
    months = measures.months()
    month = months[-1] if months else ""
    stamp = measures.stamp(month) if month else {}

    acts: list[dict[str, Any]] = []
    missing: list[str] = []
    for act in ACTS:
        steps: list[dict[str, Any]] = []
        for step in act.steps:
            links: dict[str, Any] = {}
            ready = True
            for kind, key in (step.needs or {}).items():
                got = found.get(kind, {}).get(key)
                if got is None:
                    ready = False
                    missing.append(f"{act.key}/{step.key}: {kind} {key}")
                else:
                    links[kind] = got
            route = step.route
            # The route a needed object implies, resolved to this
            # installation's id rather than written down. A guide naming
            # "investigation 1012" is right on one machine and wrong on
            # every other.
            if not route and links:
                route = next(iter(links.values())).get("href", "")
            steps.append({
                "key": step.key, "prompt": step.prompt, "route": route,
                "control": step.control, "narration": step.narration,
                "expect": list(step.expect), "links": links,
                "ready": ready,
                "why_not_ready": ("" if ready else
                                  "The object this step opens has not been "
                                  "seeded on this installation. Run the "
                                  "workspace seed and reopen the story."),
            })
        acts.append({"key": act.key, "title": act.title,
                     "purpose": act.purpose, "steps": steps,
                     "ready": all(one["ready"] for one in steps)})

    return {
        "story_version": STORY_VERSION,
        "month": month,
        "source_hash": stamp.get("source_hash", ""),
        "acts": acts,
        "ready": not missing,
        "missing": missing,
        "steps": sum(len(one["steps"]) for one in acts),
        "how_to_use": (
            "A guided navigation aid, not a slideshow. Every step opens a "
            "real screen and every prompt is answered live by the product "
            "through the same path a typed question takes. Free-text "
            "navigation works throughout; the story is a route somebody "
            "has already walked, not a rail."),
    }


__all__ = ["ACTS", "Act", "STORY_VERSION", "Step", "story"]
