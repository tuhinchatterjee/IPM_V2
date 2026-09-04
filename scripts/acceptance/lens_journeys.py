"""The six Lenses 2.0 journeys, driven through a real browser.

Not a route crawl — `scripts/browser_acceptance.py` already proves the pages
render at four viewports without overflowing. This proves something else and
harder: that a person can trust a number they find here.

    A  Open a shipped lens and see real figures, not placeholders.
    B  Ask a tile how it is calculated and get an answer, not a tooltip.
    C  Find a metric by typing what you call it, and watch it narrow.
    D  Ask for something this deployment cannot do and be told why.
    E  Check a figure against your own number, including when they disagree.
    F  Read what the lens deliberately does not show.
    G  Build a metric of your own, and get the right number for it.
    H  Arrange a lens by hand, and have that be a version like any other.
    I  Build a chart of a metric across a dimension, see why the chart types
       you are NOT offered are refused, and put it on a lens.

Each journey asserts something a screenshot cannot: that the three stage
exposures on screen sum to the total exposure on screen, that the info panel
carries the formula and the source fields rather than a name, that typing a
second word REMOVES suggestions, that a disagreement is recorded and confers
nothing, and that a metric assembled on the form computes what the parquet
says it should.

    .venv/bin/python scripts/acceptance/lens_journeys.py
    .venv/bin/python scripts/acceptance/lens_journeys.py --json

Requires the backend on :8000, the front end on :3000, and the shipped lenses
installed (`python -c "from backend.metrics.lenses import install; install()"`).
It FAILS rather than skips when those are missing: a run that quietly checked
nothing must not read as a pass.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

WEB = os.environ.get("LENS_WEB", "http://127.0.0.1:3000")
API = os.environ.get("LENS_API", "http://127.0.0.1:8000")

#: Signed in as a real analyst rather than an administrator with the login
#: gate off: the governance labels and the ownership rules only mean something
#: as somebody in particular.
WHO = os.environ.get("LENS_USER", "priya.raman")

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_CANNOT_RUN = 2


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

    def check(self, journey: str, name: str, ok: bool, detail: str = "") -> bool:
        self.steps.append(Step(journey, name, bool(ok), detail))
        return bool(ok)

    @property
    def failures(self) -> list[Step]:
        return [s for s in self.steps if not s.ok]

    def to_dict(self) -> dict[str, Any]:
        return {"steps": [s.to_dict() for s in self.steps],
                "passed": len(self.steps) - len(self.failures),
                "failed": len(self.failures), "error": self.error}


def _chromium() -> str | None:
    root = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw-browsers"))
    for pattern in ("chromium-*/chrome-linux/chrome",
                    "chromium_headless_shell-*/chrome-linux/headless_shell"):
        for found in sorted(root.glob(pattern), reverse=True):
            if found.is_file():
                return str(found)
    return None


def _figure(text: str) -> float | None:
    """The number out of a rendered tile: '127,248' or '6.18%'."""
    found = re.search(r"-?[\d,]+(?:\.\d+)?", (text or "").replace("−", "-"))
    if not found:
        return None
    try:
        return float(found.group().replace(",", ""))
    except ValueError:
        return None


def run(report: Report) -> Report:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        report.error = ("Playwright is not installed. The lens journeys did "
                        "not run and are NOT passed.")
        return report

    with sync_playwright() as play:
        try:
            browser = play.chromium.launch(executable_path=_chromium())
        except Exception as exc:  # noqa: BLE001
            report.error = (f"Chromium would not launch: {exc}. The lens "
                            "journeys did not run and are NOT passed.")
            return report
        context = browser.new_context(viewport={"width": 1440, "height": 900},
                                      reduced_motion="reduce")
        page = context.new_page()
        try:
            if not _sign_in(page, report):
                return report
            for name, journey in (("A", _journey_a), ("B", _journey_b),
                                  ("C", _journey_c), ("D", _journey_d),
                                  ("E", _journey_e), ("F", _journey_f),
                                  ("G", _journey_g), ("H", _journey_h),
                                  ("I", _journey_i)):
                _guard(report, name, journey, page, report)
        finally:
            context.close()
            browser.close()
    return report


def _guard(report: Report, journey: str, fn: Any, *args: Any) -> Any:
    """Run one journey, recording a crash as a failure of that journey alone.

    An acceptance run that stops early looks exactly like one that had less to
    check, which is the failure mode this exists to prevent.
    """
    try:
        return fn(*args)
    except Exception as exc:  # noqa: BLE001
        report.check(journey, "the journey ran to the end", False,
                     f"{type(exc).__name__}: {exc}")
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
                               state="detached", timeout=10_000)
    except Exception:  # noqa: BLE001
        return report.check("sign in", f"signed in as {WHO}", False,
                            "the sign-in form is still on screen.")
    return report.check("sign in", f"signed in as {WHO}", True)


# --------------------------------------------------------------- journey A
#
# Open a shipped lens and see real figures, not placeholders.


def _journey_a(page: Any, report: Report) -> None:
    lens = page.request.get(f"{API}/api/v1/lenses").json()
    slugs = {row["slug"] for row in lens.get("lenses", [])}
    if not report.check("A", "the shipped lenses are installed",
                        {"corporate-ifrs9", "retail-credit-risk"} <= slugs,
                        f"found: {sorted(slugs)}"):
        return

    ifrs9 = next(row for row in lens["lenses"]
                 if row["slug"] == "corporate-ifrs9")
    page.goto(f"{WEB}/lenses/{ifrs9['id']}", wait_until="networkidle")
    page.wait_for_timeout(2000)

    body = page.inner_text("body")
    report.check("A", "the lens is on screen", "Corporate IFRS 9" in body)
    report.check("A", "its bands are named",
                 "Where the book sits" in body and "The provision" in body)

    # The tiles carry figures, not dashes. A lens of dashes renders perfectly
    # and tells a reader nothing, so this is the check that earns its place.
    rendered = page.request.get(
        f"{API}/api/v1/lenses/{ifrs9['id']}/render?period=Q4%202024").json()
    values = {p["metric_id"]: p.get("value") for p in rendered["panels"]
              if p.get("kind") == "metric"}
    report.check("A", "no tile failed", rendered["failed"] == 0,
                 str([p["metric_id"] for p in rendered["panels"]
                      if p["status"] == "failed"]))
    report.check("A", "every tile produced a number",
                 all(isinstance(v, float) for v in values.values()),
                 str([k for k, v in values.items()
                      if not isinstance(v, float)]))

    # And the figures reconcile with each other, which is what makes them
    # figures rather than decorations.
    parts = sum(values.get(f"corporate.ifrs9.stage{n}_ead", 0.0)
                for n in (1, 2, 3))
    total = values.get("corporate.ifrs9.total_ead", 0.0)
    report.check("A", "the three stage exposures sum to the total",
                 total and abs(parts - total) < 1e-6,
                 f"{parts} vs {total}")

    shares = sum(values.get(f"corporate.ifrs9.stage{n}_share", 0.0)
                 for n in (1, 2, 3))
    report.check("A", "the stage shares account for the whole book",
                 abs(shares - 100.0) < 1e-6, str(shares))


# --------------------------------------------------------------- journey B
#
# Ask a tile how it is calculated and get an answer, not a tooltip.


def _journey_b(page: Any, report: Report) -> None:
    panel = page.request.get(
        f"{API}/api/v1/metrics/corporate.ifrs9.coverage").json()

    for field_name, why in (
            ("definition", "what it measures"),
            ("formula", "the arithmetic"),
            ("numerator", "the top of the ratio"),
            ("denominator", "the bottom of the ratio"),
            ("period_rule", "which period it used"),
            ("owner", "who owns the definition"),
            ("origin_label", "whether it is governed"),
            ("status_label", "how far it has been taken")):
        report.check("B", f"the panel gives {why}",
                     bool(str(panel.get(field_name) or "").strip()),
                     f"{field_name} was empty")

    report.check("B", "it names the fields it reads",
                 len(panel.get("source_fields") or []) > 0)
    report.check("B", "it says what it is NOT",
                 bool(str(panel.get("not_this") or "").strip()))

    # On screen: the info control opens and shows the formula, not a name.
    lens = page.request.get(f"{API}/api/v1/lenses").json()
    ifrs9 = next(row for row in lens["lenses"]
                 if row["slug"] == "corporate-ifrs9")
    page.goto(f"{WEB}/lenses/{ifrs9['id']}", wait_until="networkidle")
    page.wait_for_timeout(2000)
    # The trigger names the metric it explains, so a screen reader user does
    # not hear "what is this screen for?" once per tile.
    buttons = page.locator("button[aria-label^='How ']")
    report.check("B", "each tile's info control names its own metric",
                 buttons.count() > 0,
                 "no trigger was labelled for a particular metric")
    opened = False
    for index in range(min(buttons.count(), 6)):
        try:
            buttons.nth(index).click(timeout=2000)
            page.wait_for_timeout(400)
            body = page.inner_text("body").lower()
            if "how it is calculated" in body:
                opened = True
                break
        except Exception:  # noqa: BLE001
            continue
    report.check("B", "a tile explains itself on screen", opened,
                 "no info control showed 'How it is calculated'")


# --------------------------------------------------------------- journey C
#
# Find a metric by typing what you call it, and watch it narrow.


def _journey_c(page: Any, report: Report) -> None:
    empty = page.request.get(f"{API}/api/v1/metrics?q=").json()
    report.check("C", "the picker does not open with the whole catalogue",
                 empty["count"] == 0, str(empty["count"]))

    broad = page.request.get(f"{API}/api/v1/metrics?q=delinq&limit=50").json()
    narrow = page.request.get(
        f"{API}/api/v1/metrics?q=delinq%2030&limit=50").json()
    report.check("C", "three letters already find something",
                 broad["count"] > 0)
    report.check("C", "a second word NARROWS rather than widens",
                 0 < narrow["count"] < broad["count"],
                 f"{broad['count']} -> {narrow['count']}")
    ids = {hit["metric_id"] for hit in narrow["results"]}
    report.check("C", "the narrowed list is about 30 days",
                 "retail.dpd_30_count" in ids
                 and "retail.dpd_60_count" not in ids, str(sorted(ids)))
    report.check("C", "every suggestion says why it matched",
                 all(str(hit.get("why") or "").strip()
                     for hit in narrow["results"]))

    # An alias people actually use reaches the metric.
    bad = page.request.get(f"{API}/api/v1/metrics?q=bad%20rate").json()
    report.check("C", "'bad rate' reaches the default rate",
                 bool(bad["results"])
                 and bad["results"][0]["metric_id"] == "retail.default_rate",
                 str([h["metric_id"] for h in bad["results"][:3]]))

    # And on screen, typing gets suggestions.
    page.goto(f"{WEB}/metrics", wait_until="networkidle")
    box = page.locator("input[aria-label='Search metrics']")
    report.check("C", "the search box is on the catalogue screen",
                 box.count() > 0)
    if box.count():
        box.first.fill("delinq 30")
        page.wait_for_timeout(1200)
        body = page.inner_text("body")
        report.check("C", "the suggestions appear on screen",
                     "30+ DPD" in body, body[:200])


# --------------------------------------------------------------- journey D
#
# Ask for something this deployment cannot do and be told why.


def _journey_d(page: Any, report: Report) -> None:
    found = page.request.get(f"{API}/api/v1/metrics?q=roll%20rate").json()
    report.check("D", "a roll rate finds no metric", found["count"] == 0)
    report.check("D", "and the absence is explained",
                 bool(found.get("unavailable")),
                 "nothing was offered as a reason")
    if found.get("unavailable"):
        entry = found["unavailable"][0]
        report.check("D", "the reason is a sentence, not a code",
                     len(entry.get("because") or "") > 40, entry.get("because"))
        report.check("D", "it says what would be needed",
                     bool(entry.get("needs")))

    # Asking a lens for it is refused with the same reason rather than a tile
    # that draws a dash.
    lens = page.request.get(f"{API}/api/v1/lenses").json()
    retail = next(row for row in lens["lenses"]
                  if row["slug"] == "retail-credit-risk")
    asked = page.request.post(
        f"{API}/api/v1/lenses/{retail['id']}/ask",
        data=json.dumps({"request": "add the roll rate", "apply": False}),
        headers={"content-type": "application/json"})
    body = asked.json() if asked.ok else {}
    refusals = (body.get("proposal") or {}).get("refusals") or []
    report.check("D", "a lens refuses it with the reason",
                 any("cannot be calculated" in r for r in refusals),
                 str(refusals)[:200])

    # A metric that does not exist at all is a clean 404, not a 500.
    missing = page.request.get(f"{API}/api/v1/metrics/no.such.metric")
    report.check("D", "an unknown metric is a clean refusal",
                 missing.status == 404, f"HTTP {missing.status}")


# --------------------------------------------------------------- journey E
#
# Check a figure against your own number, including when they disagree.


def _journey_e(page: Any, report: Report) -> None:
    metric = "corporate.ifrs9.coverage"
    computed = page.request.get(
        f"{API}/api/v1/metrics/{metric}/value?period=Q4%202024").json()
    truth = computed.get("value")
    if not report.check("E", "there is a figure to check against",
                        isinstance(truth, float), str(truth)):
        return

    def verify(expected: float, decision: str) -> dict:
        response = page.request.post(
            f"{API}/api/v1/metrics/{metric}/verify",
            data=json.dumps({"expected": expected, "period": "Q4 2024",
                             "decision": decision,
                             "expected_source": "lens journey E"}),
            headers={"content-type": "application/json"})
        return response.json() if response.ok else {}

    agreed = verify(truth, "ACCEPTED")
    report.check("E", "a number that agrees is recorded as agreeing",
                 agreed.get("agrees") is True, str(agreed)[:160])

    differs = verify(truth + 5.0, "ACCEPTED")
    report.check("E", "a number that does not agree is recorded as differing",
                 differs.get("outcome") == "DIFFERS", str(differs)[:160])
    report.check("E", "the computed value was NOT moved toward it",
                 differs.get("computed") == truth,
                 f"{differs.get('computed')} vs {truth}")
    report.check("E", "accepting a disagreement confers nothing",
                 bool(differs.get("note_on_status")),
                 "nothing explained why it is still not verified")

    history = page.request.get(
        f"{API}/api/v1/metrics/{metric}/verifications").json()
    outcomes = {row["outcome"] for row in history.get("verifications", [])}
    report.check("E", "the history keeps the disagreement too",
                 "DIFFERS" in outcomes, str(sorted(outcomes)))

    # A governed metric is never promoted by this: its status is code.
    panel = page.request.get(f"{API}/api/v1/metrics/{metric}").json()
    report.check("E", "a governed metric's status is not changed by a check",
                 panel.get("origin") == "CREDITPROBE_GOVERNED"
                 and panel.get("status") == "PUBLISHED",
                 f"{panel.get('origin')} / {panel.get('status')}")


# --------------------------------------------------------------- journey F
#
# Read what the lens deliberately does not show.


def _journey_f(page: Any, report: Report) -> None:
    lens = page.request.get(f"{API}/api/v1/lenses").json()
    retail = next(row for row in lens["lenses"]
                  if row["slug"] == "retail-credit-risk")
    rendered = page.request.get(
        f"{API}/api/v1/lenses/{retail['id']}/render").json()

    notes = rendered.get("notes") or []
    report.check("F", "the lens says what it does not show", len(notes) > 0)
    for note in notes:
        report.check("F", f"'{note['name']}' comes with a reason",
                     len(note.get("because") or "") > 40)
        report.check("F", f"'{note['name']}' says what would be needed",
                     bool(note.get("needs")))

    shown = {p.get("metric_id") for p in rendered["panels"]}
    report.check("F", "nothing is both shown and declared missing",
                 not (shown & {n["metric_id"] for n in notes}))

    page.goto(f"{WEB}/lenses/{retail['id']}", wait_until="networkidle")
    page.wait_for_timeout(2000)
    body = page.inner_text("body")
    report.check("F", "it is on screen, not only in the payload",
                 "not on this lens" in body.lower(),
                 "the heading is uppercased by CSS, and inner_text returns "
                 "rendered text")
    if notes:
        report.check("F", "the reason is on screen too",
                     notes[0]["name"] in body, notes[0]["name"])


# --------------------------------------------------------------- journey G
#
# Build a metric on screen, and prove the number it saves is the right one.


#: Deliberately a definition nothing in the governed library already computes,
#: so a pass cannot come from the builder quietly resolving to a shipped
#: metric. Three or more missed instalments is a real collections threshold
#: and an integer comparison — which is the part that breaks if a value typed
#: into a box reaches the compiler as the string "3".
G_NAME = "Three Instalments Behind Share"
G_DATASET = "facility_delinquency"


def _journey_g(page: Any, report: Report) -> None:
    _forget_metric(page, G_NAME)

    page.goto(f"{WEB}/metrics", wait_until="networkidle")
    page.get_by_role("button", name="Build a metric").click()
    page.wait_for_selector("text=Build a metric", timeout=10_000)
    page.wait_for_timeout(1200)

    body = page.inner_text("body")
    report.check("G", "the builder explains what it will and will not confer",
                 "governed catalogue" in body and "draft" in body.lower())

    # Not `exact=True`: the field labels are uppercased by CSS and
    # Playwright matches rendered text, so "Dataset" is "DATASET" here.
    chooser = page.get_by_label("Dataset")

    # Only the governed datasets are offered. A builder that let somebody name
    # any of the 77 tables would be a builder for definitions nobody can
    # interpret. The count includes the "Choose…" placeholder.
    labels = [o.strip() for o in chooser.locator("option").all_inner_texts()]
    report.check("G", "the dataset list is the governed one, not every table",
                 1 < len(labels) <= 10, f"{len(labels)} options: {labels}")

    page.get_by_placeholder("Stretched Arrears Share").fill(G_NAME)
    page.get_by_placeholder("Balance 30+ DPD as a share").fill(
        "Facilities three or more instalments behind, as a share of the book.")

    business = _business_name(page, G_DATASET)
    if not report.check("G", "the delinquency dataset is offered by its "
                        "business name", business in labels,
                        f"{business!r} not in {labels}"):
        return
    chooser.select_option(label=business)
    page.wait_for_timeout(600)

    # Numerator: how many rows are three instalments behind.
    top = page.locator("section", has_text="Numerator").first
    top.get_by_label("Aggregation").select_option("count")
    top.get_by_role("button", name="Only where").click()
    top.get_by_label("Filter field").select_option(label="Instalments missed")
    top.get_by_label("Comparison").select_option(">=")
    top.get_by_label("Value").fill("3")

    # Denominator: how many rows there are.
    bottom = page.locator("section", has_text="Denominator").first
    bottom.get_by_label("Aggregation").select_option("count")

    page.get_by_role("button", name="Preview").click()
    page.wait_for_timeout(4000)

    truth = _instalments_share()
    if truth is None:
        report.check("G", "the source data could be read independently", False,
                     "no lake on disk, so nothing was checked")
        return
    report.check("G", "the source data could be read independently", True,
                 f"{truth:.6f}% straight from the Parquet")

    # The figure the person is looking at, parsed off the screen and compared
    # against the number computed in raw SQL. This is the check the journey
    # exists for: a value typed into a box has to reach the engine as the
    # integer 3, over one period rather than pooled across fifteen quarters.
    card = page.locator("p.tabular").last
    on_screen = _figure(card.inner_text()) if card.count() else None
    report.check("G", "the preview produced a figure, not a refusal",
                 on_screen is not None,
                 page.inner_text("body")[-300:])
    report.check("G", "the figure on screen is the one the data supports",
                 on_screen is not None and abs(on_screen - truth) < 0.005,
                 f"screen {on_screen} vs data {truth}")

    api_preview = page.request.post(
        f"{API}/api/v1/metrics/preview",
        data={"name": G_NAME, "unit": "percent",
              "formula": _instalments_formula()}).json()
    report.check("G", "and so is the one the endpoint returns",
                 api_preview.get("value") is not None and
                 abs(api_preview["value"] - truth) < 1e-9,
                 f"API {api_preview.get('value')} vs data {truth}")
    report.check("G", "the preview says which period it is for",
                 bool(api_preview.get("period")),
                 "a share of the book with no period reads as 'now'")
    report.check("G", "the working is shown, not just the answer",
                 "/" in (api_preview.get("formula") or ""),
                 api_preview.get("formula", ""))

    page.get_by_role("button", name="Save as a draft").click()
    page.wait_for_timeout(3000)

    saved = _find_metric(page, G_NAME)
    if not report.check("G", "the metric was saved", saved is not None):
        return

    report.check("G", "it is marked as built here, not governed",
                 saved["governed"] is False, saved.get("origin_label", ""))
    report.check("G", "it is a draft, and says so",
                 saved["trustworthy"] is False and "draft"
                 in (saved.get("status_label") or "").lower(),
                 saved.get("status_label", ""))

    value = page.request.get(
        f"{API}/api/v1/metrics/{saved['metric_id']}/value").json()
    report.check("G", "the saved metric computes the same number it previewed",
                 value.get("value") is not None and
                 abs(value["value"] - truth) < 1e-9,
                 f"saved {value.get('value')} vs data {truth}")

    body = page.inner_text("body")
    report.check("G", "the new metric is on screen with its governance labels",
                 G_NAME in body and "Draft" in body)

    # Search finds it by what it was called, alongside the shipped ones.
    found = page.request.get(
        f"{API}/api/v1/metrics?q=three+instalments").json()
    report.check("G", "it is findable by name straight away",
                 any(h["metric_id"] == saved["metric_id"]
                     for h in found.get("results", [])),
                 [h["metric_id"] for h in found.get("results", [])])

    _forget_metric(page, G_NAME)
    report.check("G", "it is gone once deleted",
                 _find_metric(page, G_NAME) is None)


def _instalments_formula() -> dict:
    """The formula the form assembles, as the form assembles it.

    Written out here so the API comparison is against the same structure the
    browser posts — 3 as a number, because that is what `coerce` produces.
    """
    return {
        "kind": "percentage", "scale": 100,
        "numerator": {"terms": [{
            "id": "top", "label": "three behind", "dataset": G_DATASET,
            "aggregate": "count", "field": "",
            "where": [{"field": "instalments_missed", "op": ">=",
                       "value": 3}]}]},
        "denominator": {"terms": [{
            "id": "bottom", "label": "facilities", "dataset": G_DATASET,
            "aggregate": "count", "field": "", "where": []}]},
    }


def _business_name(page: Any, dataset: str) -> str:
    vocab = page.request.get(f"{API}/api/v1/metrics/vocabulary").json()
    for entry in vocab.get("datasets", []):
        if entry["name"] == dataset:
            return entry.get("business_name") or entry["name"]
    return dataset


def _instalments_share() -> float | None:
    """The same share, computed straight off the Parquet, in raw DuckDB.

    Independent of every layer under test: no formula object, no validator, no
    compiler, no kernel — one SQL statement written here against the files. If
    the two numbers agree, the builder assembled what the person described. If
    only the metric produces one, it produced it on its own.
    """
    import duckdb

    from backend.config import settings

    directory = Path(settings.analytics_dir) / G_DATASET
    if not directory.is_dir():
        return None
    pattern = str(directory / "**" / "*.parquet")
    try:
        con = duckdb.connect(database=":memory:")
        # Ordered by year then quarter, not alphabetically: "Q4 2025" is the
        # string maximum over "Q1 2026", and picking that quarter would make
        # this check agree with a product that got the period wrong.
        latest = con.execute(
            f"SELECT period FROM read_parquet('{pattern}') "
            "GROUP BY period "
            "ORDER BY CAST(substr(period, 4, 4) AS INTEGER) DESC, "
            "         CAST(substr(period, 2, 1) AS INTEGER) DESC "
            "LIMIT 1").fetchone()
        if not latest or latest[0] is None:
            return None
        row = con.execute(
            "SELECT count(*) FILTER (WHERE instalments_missed >= 3) * 100.0 "
            f"/ count(*) FROM read_parquet('{pattern}') WHERE period = ?",
            [latest[0]]).fetchone()
    except Exception:  # noqa: BLE001 - no lake here means no check, not a pass
        return None
    finally:
        try:
            con.close()
        except Exception:  # noqa: BLE001
            pass
    return float(row[0]) if row and row[0] is not None else None


def _find_metric(page: Any, name: str) -> dict | None:
    catalogue = page.request.get(f"{API}/api/v1/metrics/all").json()
    for group in catalogue.get("domains", []):
        for metric in group.get("metrics", []):
            if metric["name"] == name:
                return metric
    return None


def _forget_metric(page: Any, name: str) -> None:
    """Leave the catalogue as it was found.

    An acceptance run must not deposit a metric somebody later trusts, and
    must be able to run twice.
    """
    found = _find_metric(page, name)
    if found:
        page.request.delete(f"{API}/api/v1/metrics/{found['metric_id']}")


# --------------------------------------------------------------- journey H
#
# Arrange a lens by hand, and have the change be a version like any other.


def _journey_h(page: Any, report: Report) -> None:
    lens = _scratch_lens(page)
    if lens is None:
        report.check("H", "a lens of this run's own could be made", False,
                     "the layout journey needs a lens it may rearrange")
        return
    try:
        _arrange(page, report, lens)
    finally:
        page.request.delete(f"{API}/api/v1/lenses/{lens['id']}")


def _arrange(page: Any, report: Report, lens: dict) -> None:
    before = page.request.get(
        f"{API}/api/v1/lenses/{lens['id']}").json()
    first = [p["metric_id"] for p in before["panels"]]

    page.goto(f"{WEB}/lenses/{lens['id']}", wait_until="networkidle")
    page.wait_for_timeout(2500)

    page.get_by_role("button", name="Arrange").click()
    page.wait_for_selector("text=Arrange this lens", timeout=10_000)
    body = page.inner_text("body")
    report.check("H", "the editor says a change becomes a version",
                 "new version" in body and "stays where it is" in body)

    # A metric that declares one honest visual says so, rather than offering
    # a chart type that would misrepresent it.
    first_metric = next((p for p in before["panels"]
                         if p.get("metric_id")), None)
    if first_metric:
        panel = page.request.get(
            f"{API}/api/v1/metrics/{first_metric['metric_id']}").json()
        offered = page.locator("select[aria-label^='How ']").first
        options = [o.strip() for o in offered.locator("option").all_inner_texts()]
        report.check("H", "the chart choices are the metric's own, not the "
                     "platform's list",
                     set(options) - {"auto"} == set(panel["visuals"]),
                     f"offered {options}, declared {panel['visuals']}")

    page.locator("button[aria-label^='Move ']").nth(1).click()
    page.wait_for_timeout(300)
    page.get_by_role("button", name="Save this arrangement").click()
    page.wait_for_timeout(3500)

    after = page.request.get(f"{API}/api/v1/lenses/{lens['id']}").json()
    now = [p["metric_id"] for p in after["panels"]]
    report.check("H", "the new order was kept", now != first and
                 sorted(now) == sorted(first), f"{first} -> {now}")
    report.check("H", "it is a version, not an overwrite",
                 after["version"] > before["version"],
                 f"v{before['version']} -> v{after['version']}")
    latest = after["revisions"][0]
    report.check("H", "and the version says what changed",
                 len(latest["change_summary"]) > 10,
                 latest["change_summary"])

    # The lens is on screen in its new order, not only in the payload.
    page.goto(f"{WEB}/lenses/{lens['id']}", wait_until="networkidle")
    page.wait_for_timeout(2500)
    shown = page.inner_text("body")
    names = [p["title"] for p in after["panels"] if p.get("title")]
    report.check("H", "the rearranged lens renders",
                 all(name in shown for name in names[:3]), names[:3])

    # And the arrangement before it can be put back.
    restored = page.request.post(
        f"{API}/api/v1/lenses/{lens['id']}/restore/{before['version']}").json()
    report.check("H", "the previous arrangement can be put back",
                 [p["metric_id"] for p in restored["panels"]] == first)


def _journey_i(page: Any, report: Report) -> None:
    """The Custom Chart Builder, end to end, in the browser.

    The assertion that matters is the last one: the number in the bar the
    person put on their lens is reproduced by reading the parquet directly.
    Everything before it is the workflow that has to hold for that number to
    be theirs — that the pickers came from the catalogue, that the chart types
    they could NOT pick say why, and that adding it to a lens is a version.
    """
    lens = _scratch_lens(page)
    if lens is None:
        report.check("I", "a lens of this run's own could be made", False,
                     "the chart journey needs a lens it may add to")
        return
    try:
        _build_a_chart(page, report, lens)
    finally:
        page.request.delete(f"{API}/api/v1/lenses/{lens['id']}")


#: The metric and dimension this journey builds. An additive retail metric
#: over an unordered category, so the "no line between products" refusal is
#: exercised on the way through rather than asserted in the abstract.
CHART_METRIC = "retail.balance"
CHART_SEARCH = "outstanding balance"
CHART_DIMENSION = "Product"


def _build_a_chart(page: Any, report: Report, lens: dict) -> None:
    before = page.request.get(f"{API}/api/v1/lenses/{lens['id']}").json()

    page.goto(f"{WEB}/lenses/{lens['id']}", wait_until="networkidle")
    page.wait_for_timeout(2500)

    page.get_by_role("button", name="Build a chart").click()
    page.wait_for_selector("[data-testid='chart-builder']", timeout=10_000)
    report.check("I", "the chart builder opens on the lens",
                 page.locator("[data-testid='chart-builder']").is_visible())

    # 1. the metric, found by typing what somebody calls it
    page.get_by_label("Search the metric catalogue").fill(CHART_SEARCH)
    page.get_by_role("button", name="Search").click()
    page.wait_for_timeout(1500)
    page.get_by_role("button", name="Retail Outstanding Balance").first.click()
    page.wait_for_timeout(1500)

    # 2. the dimension, offered from the governed catalogue
    dimensions = page.get_by_label("Dimension")
    offered = [o.strip() for o in dimensions.locator("option").all_inner_texts()]
    report.check("I", "the dimensions are the dataset's own fields",
                 CHART_DIMENSION in offered and "Account id" not in offered,
                 f"{len(offered)} offered")
    dimensions.select_option(label=CHART_DIMENSION)
    page.wait_for_timeout(2000)

    # The refusals, on screen, with their reasons. A person who cannot see
    # why "line" is missing concludes the product is broken.
    refused = page.locator("[data-testid='chart-types-refused']").inner_text()
    report.check("I", "a line between products is refused, and says why",
                 "Line" in refused and "progression that is not there" in refused,
                 refused.replace("\n", " ")[:110])
    report.check("I", "a matrix off one dimension is refused, and says why",
                 "Matrix" in refused and "two dimensions" in refused)
    types = page.locator("button[aria-pressed]")
    labels = [t.strip().lower() for t in types.all_inner_texts()]
    report.check("I", "a bar IS offered", "bar" in labels, str(labels))

    # 3-6. period, filter, ordering, comparison, chart type, title
    page.get_by_label("Sorted").select_option("value")
    page.get_by_label("Direction").select_option("desc")
    page.get_by_label("Compared with").select_option("previous_period")
    page.get_by_label("How many groups").fill("4")
    page.get_by_role("button", name="bar", exact=True).click()
    page.get_by_label("Title", exact=True).fill("Balance by product")

    # The preview, through the same route the lens tile uses.
    page.get_by_role("button", name="Preview").click()
    page.wait_for_selector("[data-testid='chart-preview']", timeout=120_000)
    preview = page.locator("[data-testid='chart-preview']").inner_text()
    report.check("I", "the preview draws bars with their numbers",
                 "CREDIT_CARD" in preview and "PERSONAL_LOAN" in preview,
                 preview.replace("\n", " ")[:110])
    report.check("I", "the preview names the comparison period",
                 " vs " in preview, preview.split("\n")[1] if "\n" in preview else "")
    report.check("I", "the preview carries the query that produced it",
                 "run " in preview and "query that produced" in preview)

    # Adding it to the lens goes through the same validated layout route.
    page.get_by_role("button", name="Add to this lens").click()
    page.wait_for_timeout(4000)

    after = page.request.get(f"{API}/api/v1/lenses/{lens['id']}").json()
    charts = [p for p in after["panels"] if p.get("kind") == "chart"]
    report.check("I", "the chart is on the lens",
                 len(charts) == 1 and charts[0]["metric_id"] == CHART_METRIC,
                 f"{len(after['panels'])} panels, {len(charts)} of them charts")
    if not charts:
        return
    stored = charts[0]
    report.check("I", "its configuration was kept",
                 stored["visual"] == "bar"
                 and stored["params"].get("dimension") == "product"
                 and stored["params"].get("compare") == "previous_period"
                 and int(stored["params"].get("limit") or 0) == 4,
                 json.dumps(stored["params"]))
    report.check("I", "adding it is a version, not an overwrite",
                 after["version"] > before["version"],
                 f"v{before['version']} -> v{after['version']}")
    report.check("I", "and the version says what changed",
                 "chart" in after["revisions"][0]["change_summary"].lower(),
                 after["revisions"][0]["change_summary"])

    # It renders on the lens, and its info control carries the lineage.
    page.goto(f"{WEB}/lenses/{lens['id']}", wait_until="networkidle")
    page.wait_for_timeout(4000)
    tile = page.locator("[data-testid='chart-tile']").first
    report.check("I", "the chart renders on the lens",
                 tile.is_visible() and "Balance by product" in tile.inner_text(),
                 tile.inner_text().replace("\n", " ")[:90] if tile.count() else "")

    opened = False
    info = tile.locator("button[aria-label^='How ']").first
    if info.count():
        info.click()
        page.wait_for_timeout(1200)
        shown = page.inner_text("body")
        opened = ("Grouped by" in shown and "Read from" in shown
                  and "SELECT" in shown.upper())
    report.check("I", "its info control gives the formula and the lineage",
                 opened, "opened and read the definition, dataset and query")

    # The number, reproduced outside the chart path entirely.
    rendered = page.request.get(
        f"{API}/api/v1/lenses/{lens['id']}/render").json()
    drawn = next((p for p in rendered["panels"] if p.get("kind") == "chart"),
                 None)
    if drawn is None:
        report.check("I", "the rendered lens carries the chart", False)
        return
    on_screen = {p["label"]: p["value"] for p in drawn["points"]}
    independent = _balance_by_product(drawn["period_used"])
    # A relative tolerance, not an exact one: the balances are stored as
    # 32-bit floats and the two paths add them in different orders, so the
    # last bit or two differ. A part per million is far tighter than any
    # difference that would matter and far looser than summation noise.
    report.check("I", "every bar reproduces from the parquet independently",
                 independent is not None
                 and set(on_screen) == set(independent)
                 and all(
                     abs(on_screen[label] - independent[label])
                     <= max(1.0, abs(independent[label]) * 1e-6)
                     for label in on_screen),
                 f"chart {on_screen} vs parquet "
                 f"{ {k: independent[k] for k in on_screen} if independent else 'unavailable'}")


def _balance_by_product(period: str) -> dict[str, float] | None:
    """The same numbers, computed without going near the metric catalogue.

    Straight over the parquet with pandas: read the one hive partition for
    this period, group by product, sum the balance column. It does not touch
    the formula, the IR, the compiler or the executor — if it agreed with the
    chart because it called the same code, it would prove nothing.
    """
    try:
        import pandas as pd
    except ImportError:
        return None

    from backend.config import settings

    partition = (Path(settings.analytics_dir)
                 / "retail_behavioral_scorecard_monthly_validation"
                 / f"observation_month={period}")
    files = sorted(partition.glob("*.parquet"))
    if not files:
        return None
    frame = pd.concat([pd.read_parquet(f, columns=["product", "current_balance"])
                       for f in files])
    totals = frame.groupby("product")["current_balance"].sum()
    return {str(product): float(total) for product, total in totals.items()}


def _scratch_lens(page: Any) -> dict | None:
    """A lens made for this run and deleted after it.

    Never a shipped one: an acceptance run must not leave the Corporate IFRS 9
    lens in whatever order its last assertion happened to want.
    """
    made = page.request.post(
        f"{API}/api/v1/lenses",
        data={"name": "Arrangement Under Test",
              "description": "Made by the acceptance run, and deleted by it.",
              "panels": [
                  {"kind": "metric", "metric_id": "corporate.ifrs9.stage1_ead",
                   "analysis_id": "", "title": "Stage 1", "visual": "kpi"},
                  {"kind": "metric", "metric_id": "corporate.ifrs9.stage2_ead",
                   "analysis_id": "", "title": "Stage 2", "visual": "kpi"},
                  {"kind": "metric", "metric_id": "corporate.ifrs9.stage3_ead",
                   "analysis_id": "", "title": "Stage 3", "visual": "kpi"}]})
    if not made.ok:
        return None
    return made.json()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    report = run(Report())

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        if report.error:
            print(f"! {report.error}")
        for step in report.steps:
            mark = "PASS" if step.ok else "FAIL"
            line = f"  [{mark}] {step.journey}  {step.name}"
            if not step.ok and step.detail:
                line += f"\n         {step.detail[:200]}"
            print(line)
        print(f"\n{len(report.steps) - len(report.failures)} passed, "
              f"{len(report.failures)} failed.")

    if report.error:
        return EXIT_CANNOT_RUN
    return EXIT_OK if not report.failures else EXIT_FAILED


if __name__ == "__main__":
    raise SystemExit(main())
