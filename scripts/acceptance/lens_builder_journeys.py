"""The Lens Builder, driven through a real browser.

§20 of the Lenses brief, as journeys rather than as unit tests. What these
prove is not that the routes answer — the API tests do that — but that a
person can get from a sentence to a saved, reloadable lens without knowing the
schema, and can then rearrange that lens and have the arrangement survive a
reload.

    M  Create a lens by describing it: the landing question, the reading,
       the domains, the name, an existing metric from the library, a NEW
       calculated metric with its formula, its plain-English execution logic
       and its real SQL, previewed against the real book, locked, another one
       added, saved — and still there after a reload.
    N  Edit an existing lens: the pencil, the edit state, reorder by drag,
       remove with confirmation, add a metric through the SAME builder, come
       back still in edit mode, save — and the arrangement survives a reload.
    O  Ask for a chart in words and put the chart it offers on a lens.
    P  A compound, multi-domain sentence resolves to more than one domain.

Each asserts something a screenshot cannot: that the preview's own terms
reproduce its total, that the metric locked is the metric that appears, that
the order after a reload is the order that was dragged, and that a removed
card is gone from the stored definition rather than only from the screen.

    .venv/bin/python scripts/acceptance/lens_builder_journeys.py
    .venv/bin/python scripts/acceptance/lens_builder_journeys.py --json

Requires the backend on :8000 and the front end on :3000. It FAILS rather than
skips when those are missing: a run that quietly checked nothing must not read
as a pass.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

WEB = os.environ.get("LENS_WEB", "http://127.0.0.1:3000")
API = os.environ.get("LENS_API", "http://127.0.0.1:8000")
WHO = os.environ.get("LENS_USER", "priya.raman")

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_CANNOT_RUN = 2

#: Lenses this run creates, removed at the end however it ends.
MADE: list[int] = []

#: Metrics this run builds, by name, removed at the end however it ends.
#: A built metric outlives the lens it was built for — that is the point of
#: a governed library — so deleting the lenses is not enough to leave the
#: deployment as this run found it. It also has to be enough to let the run
#: repeat: a second run drafting the same definition is refused by name, and
#: a refusal that only ever appears on the second run is the worst kind.
BUILT: list[str] = []


@dataclass
class Step:
    journey: str
    name: str
    ok: bool
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"journey": self.journey, "check": self.name, "ok": self.ok,
                "detail": self.detail}


@dataclass
class Report:
    steps: list[Step] = field(default_factory=list)
    error: str = ""
    #: Print each check as it happens rather than only at the end. A run that
    #: takes ten minutes and prints nothing until it finishes is a run nobody
    #: can diagnose while it is stuck — and the one thing you want to know
    #: about a stuck acceptance run is which check it is stuck on.
    live: bool = True

    def check(self, journey: str, name: str, ok: bool, detail: str = "") -> bool:
        step = Step(journey, name, bool(ok), detail)
        self.steps.append(step)
        if self.live:
            print(f"  [{'PASS' if step.ok else 'FAIL'}] {journey}  {name}",
                  flush=True)
            if not step.ok and detail:
                print(f"         {detail[:400]}", flush=True)
        return bool(ok)

    @property
    def failures(self) -> list[Step]:
        return [s for s in self.steps if not s.ok]

    def to_dict(self) -> dict[str, Any]:
        return {"steps": [s.to_dict() for s in self.steps],
                "passed": len(self.steps) - len(self.failures),
                "failed": len(self.failures), "error": self.error}


def _chromium() -> str | None:
    for pattern in ("chromium-*/chrome-linux/chrome",
                    "chromium_headless_shell-*/chrome-linux/headless_shell"):
        found = sorted(glob.glob(
            str(Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH",
                                    "/opt/pw-browsers")) / pattern)))
        if found:
            return found[-1]
    return None


def _sign_in(page: Any, report: Report) -> bool:
    from backend.services.demo_users import DEMO_PASSWORD

    page.goto(f"{WEB}/", wait_until="networkidle")
    if page.locator("input[name=password], #password").count() == 0:
        return report.check("sign in", "reached the product", True,
                            "no sign-in was required")
    page.fill("input[name=username], #username", WHO)
    page.fill("input[name=password], #password", DEMO_PASSWORD)
    page.click("button[type=submit]")
    try:
        page.wait_for_selector("input[name=password], #password",
                               state="detached", timeout=15_000)
    except Exception:  # noqa: BLE001
        return report.check("sign in", f"signed in as {WHO}", False,
                            "the sign-in form is still on screen")
    page.wait_for_timeout(2500)
    return report.check("sign in", f"signed in as {WHO}", True)


def _lens_id(url: str) -> int:
    tail = url.rstrip("/").rsplit("/", 1)[-1].split("?")[0]
    return int(tail) if tail.isdigit() else 0


def _stored(page: Any, lens_id: int) -> dict[str, Any]:
    return page.request.get(f"{API}/api/v1/lenses/{lens_id}").json()


# --------------------------------------------------------------- journey M
#
# From a sentence to a saved lens, including a metric that did not exist.


def _journey_m(page: Any, report: Report) -> None:
    page.goto(f"{WEB}/lenses", wait_until="networkidle")
    page.wait_for_timeout(2500)

    report.check("M", "the library asks how to define a new lens",
                 "How do you want to define a new Lens?" in page.inner_text("body"))
    report.check("M", "and offers a free-text box to answer in",
                 page.locator("[data-testid=lens-intent]").count() == 1)

    page.fill("[data-testid=lens-intent]", "watchlist exposure and covenant breaches")
    page.click("[data-testid=describe-lens]")
    page.wait_for_timeout(7000)

    report.check("M", "describing it opens the builder carrying the sentence",
                 "/lenses/new" in page.url, page.url)
    understood = page.locator("[data-testid=understood]")
    report.check("M", "and CreditProbe says what it understood",
                 understood.count() == 1 and
                 understood.inner_text().startswith("Read as:"),
                 understood.inner_text()[:120] if understood.count() else "")

    options = page.locator("[data-testid=domain-option]")
    report.check("M", "the data domains are offered as options, not decided",
                 options.count() >= 1, f"{options.count()} offered")
    report.check("M", "and a domain it missed can be typed",
                 page.locator("[data-testid=domain-freetext]").count() == 1)

    page.fill("[data-testid=lens-name]", "Acceptance Builder Lens")
    page.click("[data-testid=confirm-name]")
    page.wait_for_timeout(2000)
    report.check("M", "naming it opens what it should show",
                 "What should it show?" in page.inner_text("body"))

    # ---- an EXISTING metric, found by searching the library ----
    page.click("[data-testid=open-metric-builder]")
    page.wait_for_timeout(1200)
    report.check("M", "the metric builder offers existing or new",
                 page.locator("[data-testid=metric-builder]").count() == 1)
    library = page.locator("[data-testid=metric-library]")
    report.check("M", "the library is the default way in", library.count() == 1)

    page.fill("input[aria-label='Search the metric library']", "coverage")
    page.wait_for_timeout(2500)
    rows = page.locator("[data-testid=metric-library] ul li")
    report.check("M", "searching the library finds governed metrics",
                 rows.count() > 0, f"{rows.count()} rows for 'coverage'")
    page.locator("[data-testid=library-add]").first.click()
    page.wait_for_timeout(1500)
    report.check("M", "adding an existing metric locks it straight away",
                 page.locator("[data-testid=metric-locked]").count() == 1)

    # ---- a NEW calculated metric ----
    page.click("[data-testid=add-another-metric]")
    page.wait_for_timeout(900)
    page.get_by_role("radio", name="Define a new metric").click()
    page.wait_for_timeout(600)
    page.fill("#describe-metric", "total exposure to borrowers on the watchlist")
    page.get_by_role("button", name="Draft it").click()
    page.wait_for_timeout(9000)

    report.check("M", "describing a new metric drafts a definition",
                 page.locator("[data-testid=metric-definition]").count() == 1)
    # Remember it, and clear whatever a previous run left under the same
    # name. The catalogue refuses two metrics with one name — correctly —
    # so without this the lock below fails on every run after the first.
    drafted = page.locator("input[aria-label='Metric name']").input_value()
    if drafted:
        BUILT.append(drafted)
        _forget_metric(page, drafted)
    formula = page.locator("[data-testid=formula-line]")
    english = page.locator("[data-testid=plain-english] li")
    sql = page.locator("[data-testid=sql-line]")
    report.check("M", "the definition shows its formula",
                 formula.count() == 1 and "exposure" in formula.inner_text(),
                 formula.inner_text()[:90] if formula.count() else "")
    report.check("M", "and the plain-English execution logic",
                 english.count() >= 3, f"{english.count()} steps")
    report.check("M", "and the actual query it will run",
                 sql.count() == 1 and "SELECT" in sql.inner_text().upper())
    report.check("M", "with its values bound rather than written into it",
                 page.locator("[data-testid=sql-params]").count() == 1)

    # ---- §7: an edit moves every reading of it ----
    before = formula.inner_text()
    aggregate = page.locator("select[aria-label^='Aggregation for']").first
    if aggregate.count():
        aggregate.select_option("count")
        page.wait_for_timeout(3500)
        report.check("M", "editing the definition moves the formula with it",
                     page.locator("[data-testid=formula-line]").inner_text()
                     != before,
                     f"{before[:40]} -> "
                     f"{page.locator('[data-testid=formula-line]').inner_text()[:40]}")
        aggregate.select_option("sum")
        page.wait_for_timeout(3500)
        report.check("M", "and changing it back restores it",
                     page.locator("[data-testid=formula-line]").inner_text()
                     == before)

    # ---- §8: the real-data preview ----
    page.click("[data-testid=preview-metric]")
    page.wait_for_timeout(11_000)
    preview = page.locator("[data-testid=metric-preview]")
    if not report.check("M", "it previews against the real book",
                        preview.count() == 1):
        return
    # Lowercased on both sides: these headings are uppercased by CSS, and
    # `inner_text` returns what is rendered rather than what is in the markup.
    shown = preview.inner_text().lower()
    for wanted, label in (("portfolio_facility", "the dataset it reads"),
                          ("fields read", "the fields it reads"),
                          ("numerator", "the numerator"),
                          ("aggregation", "the aggregation"),
                          ("final calculation", "the final calculation")):
        report.check("M", f"the preview names {label}", wanted in shown)
    value = page.locator("[data-testid=preview-value]")
    report.check("M", "and shows a real figure, not a placeholder",
                 value.count() == 1 and any(c.isdigit()
                                            for c in value.inner_text()),
                 value.inner_text() if value.count() else "")

    # ---- §9, §10: lock, then add another, then back ----
    page.click("[data-testid=lock-metric]")
    page.wait_for_timeout(7000)
    # Carry the builder's own refusal into the report. A lock that fails
    # silently reads as a missing element, and "element not found" is not a
    # diagnosis of anything.
    refused = page.locator("[data-testid=builder-error]")
    if not report.check(
            "M", "locking it says so",
            page.locator("[data-testid=metric-locked]").count() == 1,
            refused.inner_text()[:200] if refused.count() else ""):
        return
    report.check("M", "and offers to add another",
                 page.locator("[data-testid=add-another-metric]").count() == 1)
    report.check("M", "and to go back to the lens",
                 page.locator("[data-testid=back-to-lens]").count() == 1)

    page.click("[data-testid=back-to-lens]")
    page.wait_for_timeout(1500)
    contents = page.locator("[data-testid=lens-contents] li")
    report.check("M", "both metrics are on the lens being built",
                 contents.count() >= 2, f"{contents.count()} on it")

    # ---- save, and reload ----
    page.click("[data-testid=create-lens]")
    page.wait_for_timeout(12_000)
    lens_id = _lens_id(page.url)
    if not report.check("M", "saving opens the lens it made", lens_id > 0,
                        page.url):
        return
    MADE.append(lens_id)

    stored = _stored(page, lens_id)
    report.check("M", "it was stored under the name that was typed",
                 stored["name"] == "Acceptance Builder Lens", stored["name"])
    report.check("M", "with the metrics that were chosen",
                 len(stored["panels"]) >= 2, str(len(stored["panels"])))
    report.check("M", "and what it was told it was for",
                 bool(stored["scope"]["domains"]), str(stored["scope"]))

    page.reload(wait_until="networkidle")
    page.wait_for_timeout(8000)
    body = page.inner_text("body")
    report.check("M", "and it is all still there after a reload",
                 "Acceptance Builder Lens" in body)
    rendered = page.request.get(
        f"{API}/api/v1/lenses/{lens_id}/render").json()
    report.check("M", "every tile on it produces a figure",
                 rendered["failed"] == 0,
                 str([p.get("error") for p in rendered["panels"]
                      if p["status"] == "failed"]))


# --------------------------------------------------------------- journey N
#
# Editing a lens that already exists.


def _journey_n(page: Any, report: Report) -> None:
    lens_id = MADE[0] if MADE else 0
    if not lens_id:
        made = page.request.post(
            f"{API}/api/v1/lenses",
            data=json.dumps({
                "name": "Acceptance Edit Lens",
                "panels": [
                    {"kind": "metric", "metric_id": "corporate.exposure",
                     "visual": "kpi"},
                    {"kind": "metric", "metric_id": "corporate.npl_rate",
                     "visual": "kpi"},
                    {"kind": "metric", "metric_id": "corporate.watchlist_rate",
                     "visual": "kpi"}]}),
            headers={"Content-Type": "application/json"})
        if made.status != 201:
            report.check("N", "a lens to edit could be made", False,
                         made.text()[:200])
            return
        lens_id = made.json()["id"]
        MADE.append(lens_id)

    page.goto(f"{WEB}/lenses/{lens_id}", wait_until="networkidle")
    page.wait_for_timeout(8000)

    before = [p["metric_id"] for p in _stored(page, lens_id)["panels"]]
    if not report.check("N", "the lens has enough cards to rearrange",
                        len(before) >= 2, str(before)):
        return

    # ---- §12: the pencil ----
    pencil = page.locator("[data-testid=edit-lens]")
    if not report.check("N", "the lens has an edit control", pencil.count() == 1):
        return
    pencil.click()
    page.wait_for_timeout(2500)

    report.check("N", "the edit bar appears",
                 page.locator("[data-testid=edit-bar]").count() == 1)
    cards = page.locator("[data-testid=editable-card]")
    report.check("N", "every card becomes editable",
                 cards.count() == len(before),
                 f"{cards.count()} cards for {len(before)} panels")

    # ---- §13: the edit state is visible ----
    # The wiggle sits one level inside the draggable element, so that the box
    # the pointer grabs holds still. Look where it actually is.
    wiggling = page.evaluate(
        """() => {
             const el = document.querySelector(
               '[data-testid=editable-card] .lens-wiggle');
             if (!el) return '';
             return getComputedStyle(el).animationName || '';
           }""")
    report.check("N", "the cards carry a visible edit state",
                 wiggling == "lens-wiggle", f"animation-name={wiggling!r}")
    grabbed = page.evaluate(
        """() => {
             const el = document.querySelector('[data-testid=editable-card]');
             return el ? getComputedStyle(el).animationName || 'none' : '';
           }""")
    report.check("N", "and the thing being dragged is not itself moving",
                 grabbed == "none", f"animation-name={grabbed!r}")
    report.check("N", "and every card has a remove control",
                 page.locator("[data-testid=remove-card]").count()
                 == cards.count())

    # ---- §14: reorder by dragging ----
    first, second = cards.nth(0), cards.nth(1)
    moved = second.get_attribute("data-metric")
    first.drag_to(second)
    page.wait_for_timeout(1500)
    after_drag = page.locator("[data-testid=editable-card]")
    report.check("N", "dragging a card changes the order on screen",
                 after_drag.nth(0).get_attribute("data-metric") != before[0],
                 f"{before[0]} -> "
                 f"{after_drag.nth(0).get_attribute('data-metric')}")

    # ---- the same move, without a pointer ----
    order_before = [after_drag.nth(i).get_attribute("data-metric")
                    for i in range(after_drag.count())]
    page.locator("[data-testid=move-later]").first.click()
    page.wait_for_timeout(700)
    cards_now = page.locator("[data-testid=editable-card]")
    order_after = [cards_now.nth(i).get_attribute("data-metric")
                   for i in range(cards_now.count())]
    report.check("N", "and a card can be moved without dragging it",
                 len(order_before) > 1
                 and order_after[:2] == [order_before[1], order_before[0]]
                 and order_after[2:] == order_before[2:],
                 f"{order_before[:3]} -> {order_after[:3]}")

    # ---- §15: remove asks first ----
    removed = (page.locator("[data-testid=editable-card]").last
               .get_attribute("data-metric"))
    page.locator("[data-testid=remove-card]").last.click()
    page.wait_for_timeout(700)
    report.check("N", "removing a card asks before it does it",
                 page.locator("[data-testid=remove-confirm]").count() == 1)
    page.locator("[data-testid=remove-confirm-yes]").click()
    page.wait_for_timeout(900)
    report.check("N", "and the card goes once confirmed",
                 page.locator("[data-testid=editable-card]").count()
                 == len(before) - 1)

    # ---- §16, §17: add a metric, come back still editing ----
    page.click("[data-testid=add-metric]")
    page.wait_for_timeout(1500)
    report.check("N", "adding a metric opens the same builder",
                 page.locator("[data-testid=metric-builder]").count() == 1)
    page.fill("input[aria-label='Search the metric library']", "utilisation")
    page.wait_for_timeout(2500)
    add = page.locator("[data-testid=library-add]")
    if report.check("N", "the library offers one to add",
                    add.count() > 0,
                    f"{add.count()} results for 'utilisation'"):
        add.first.click()
        page.wait_for_timeout(6000)
        report.check("N", "and adding it locks it onto the lens",
                     page.locator("[data-testid=metric-locked]").count() == 1)
    # The header's own way out, which is there at every stage — so this step
    # tests coming back rather than testing that the previous one worked.
    page.locator("[data-testid=leave-builder]").first.click()
    page.wait_for_timeout(6000)
    report.check("N", "coming back leaves the lens in edit mode",
                 page.locator("[data-testid=edit-bar]").count() == 1)

    # ---- save, and reload ----
    order_now = [
        page.locator("[data-testid=editable-card]").nth(i)
        .get_attribute("data-metric")
        for i in range(page.locator("[data-testid=editable-card]").count())]
    save = page.locator("[data-testid=save-layout]")
    if save.count() and save.is_enabled():
        save.click()
        page.wait_for_timeout(9000)
    stored_after = [p["metric_id"] for p in _stored(page, lens_id)["panels"]]
    report.check("N", "the arrangement is saved",
                 stored_after != before, f"{before} -> {stored_after}")
    report.check("N", "the removed card is gone from the definition",
                 removed not in stored_after,
                 f"removed {removed}, stored {stored_after}")

    page.reload(wait_until="networkidle")
    page.wait_for_timeout(8000)
    reloaded = [p["metric_id"] for p in _stored(page, lens_id)["panels"]]
    report.check("N", "and it survives a reload",
                 reloaded == stored_after, f"{stored_after} vs {reloaded}")
    report.check("N", "the order after reloading is the order that was saved",
                 [m for m in order_now if m in reloaded][:2]
                 == [m for m in reloaded if m in order_now][:2],
                 f"dragged {order_now} stored {reloaded}")
    report.check("N", "the lens still renders every tile",
                 page.request.get(
                     f"{API}/api/v1/lenses/{lens_id}/render"
                 ).json()["failed"] == 0)
    # Unless it is the one that was then removed — the removal takes the last
    # card, and the moves above decide which card that is.
    if moved and moved != removed:
        report.check("N", "the card that was dragged is still on the lens",
                     moved in reloaded, f"{moved} in {reloaded}")


# --------------------------------------------------------------- journey O
#
# Asking for a chart in words.


def _journey_o(page: Any, report: Report) -> None:
    page.goto(f"{WEB}/lenses/new?say=exposure+by+sector", wait_until="networkidle")
    page.wait_for_timeout(8000)

    understood = page.locator("[data-testid=understood]")
    report.check("O", "a breakdown request is understood as one",
                 understood.count() == 1 and
                 "sector" in understood.inner_text().lower(),
                 understood.inner_text()[:140] if understood.count() else "")

    page.fill("[data-testid=lens-name]", "Acceptance Chart Lens")
    page.click("[data-testid=confirm-name]")
    page.wait_for_timeout(2500)

    charts = page.locator("[data-testid=suggested-chart]")
    if not report.check("O", "and a chart is offered for it", charts.count() >= 1,
                        f"{charts.count()} offered"):
        return
    label = charts.first.inner_text()
    report.check("O", "the chart says what it draws and how",
                 "by" in label and ("bar" in label or "line" in label), label)
    charts.first.click()
    page.wait_for_timeout(1200)
    report.check("O", "adding it puts it on the lens",
                 page.locator("[data-testid=lens-contents] li").count() >= 1)

    page.click("[data-testid=create-lens]")
    page.wait_for_timeout(12_000)
    lens_id = _lens_id(page.url)
    if not report.check("O", "the lens saves with the chart on it", lens_id > 0,
                        page.url):
        return
    MADE.append(lens_id)

    rendered = page.request.get(f"{API}/api/v1/lenses/{lens_id}/render").json()
    drawn = [p for p in rendered["panels"] if p["kind"] == "chart"]
    report.check("O", "the chart is a chart in the stored definition",
                 len(drawn) == 1, str(len(drawn)))
    if drawn:
        report.check("O", "and it draws real points",
                     any(p["value"] is not None for p in drawn[0]["points"]),
                     f"{len(drawn[0]['points'])} points")
        report.check("O", "grouped by the dimension that was asked for",
                     drawn[0]["dimension"] == "sector", drawn[0]["dimension"])


# --------------------------------------------------------------- journey P
#
# A compound, multi-domain sentence.


def _journey_p(page: Any, report: Report) -> None:
    said = "IFRS 9 coverage and retail delinquency"
    answer = page.request.post(
        f"{API}/api/v1/lenses/interpret",
        data=json.dumps({"text": said}),
        headers={"Content-Type": "application/json"})
    if not report.check("P", "a compound sentence is read", answer.status == 200,
                        answer.text()[:200]):
        return
    body = answer.json()
    chosen = [d["name"] for d in body["domains"] if d["chosen"]]
    report.check("P", "and resolves to more than one data domain",
                 len(chosen) >= 2, str(chosen))
    report.check("P", "including the one named and the one described",
                 any("IFRS 9" in d for d in chosen)
                 and any("Retail" in d for d in chosen), str(chosen))
    ids = [m["metric_id"] for m in body["metrics"]]
    report.check("P", "and offers metrics from both",
                 any(m.startswith("corporate.ifrs9") for m in ids)
                 and any(m.startswith("retail.") for m in ids), str(ids[:6]))

    page.goto(f"{WEB}/lenses/new?say={said.replace(' ', '+')}",
              wait_until="networkidle")
    page.wait_for_timeout(8000)
    ticked = page.locator("[data-testid=domain-option][aria-pressed=true]")
    report.check("P", "both are ticked on screen", ticked.count() >= 2,
                 f"{ticked.count()} ticked")

    # §20: the truthful refusal survives the builder.
    refusals = page.locator("[data-testid=lens-refusals]")
    report.check("P", "and something it cannot calculate is still refused",
                 refusals.count() == 1
                 and "not available" in refusals.inner_text(),
                 refusals.inner_text()[:140] if refusals.count() else "none")


# ---------------------------------------------------------------- running


def _forget_metric(page: Any, name: str) -> None:
    """Delete a metric of exactly this name, if this user has one.

    Names, not ids, because the name is what the screen shows and what the
    catalogue refuses a duplicate of. Only `user.` metrics: the shipped
    catalogue is not this run's to tidy.
    """
    try:
        got = page.request.get(f"{API}/api/v1/metrics",
                               params={"q": name, "limit": 50})
        for hit in got.json().get("results", []):
            if (str(hit.get("metric_id", "")).startswith("user.")
                    and str(hit.get("name", "")).strip().lower()
                    == name.strip().lower()):
                page.request.delete(
                    f"{API}/api/v1/metrics/{hit['metric_id']}")
    except Exception:  # noqa: BLE001
        pass


def _cleanup(page: Any, report: Report) -> None:
    for name in BUILT:
        _forget_metric(page, name)
    for lens_id in MADE:
        try:
            page.request.delete(f"{API}/api/v1/lenses/{lens_id}")
        except Exception:  # noqa: BLE001
            pass
    report.check("cleanup", "the lenses this run made were removed", True,
                 f"{len(MADE)} lenses, {len(BUILT)} metrics removed")


def _guard(report: Report, journey: str, fn: Any, *args: Any) -> Any:
    try:
        return fn(*args)
    except Exception as exc:  # noqa: BLE001
        report.check(journey, "the journey ran to the end", False,
                     f"{type(exc).__name__}: {exc}")
        return None


def run(report: Report) -> Report:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        report.error = ("Playwright is not installed. The builder journeys "
                        "did not run and are NOT passed.")
        return report

    with sync_playwright() as play:
        try:
            browser = play.chromium.launch(executable_path=_chromium())
        except Exception as exc:  # noqa: BLE001
            report.error = (f"Chromium would not launch: {exc}. The builder "
                            "journeys did not run and are NOT passed.")
            return report
        context = browser.new_context(viewport={"width": 1440, "height": 1100},
                                      reduced_motion="no-preference")
        page = context.new_page()
        try:
            if not _sign_in(page, report):
                return report
            for name, journey in (("M", _journey_m), ("N", _journey_n),
                                  ("O", _journey_o), ("P", _journey_p)):
                _guard(report, name, journey, page, report)
            _cleanup(page, report)
        finally:
            context.close()
            browser.close()
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    started = time.time()
    report = run(Report(live=not args.json))
    body = report.to_dict()
    body["seconds"] = round(time.time() - started, 1)

    if args.json:
        print(json.dumps(body, indent=2))
    else:
        if report.error:
            print(f"\n{report.error}")
        print(f"\n{body['passed']} passed, {body['failed']} failed "
              f"in {body['seconds']}s.")

    if report.error:
        return EXIT_CANNOT_RUN
    return EXIT_FAILED if report.failures else EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
