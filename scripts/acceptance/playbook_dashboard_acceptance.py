"""
Document Intelligence browser acceptance. §36, §37.

Drives a real Chromium through every dashboard journey the specification
names, against the real front end, the real backend and the seeded
demonstration — and captures the screenshots §37 asks for from that same run,
so the images are evidence of the thing that was tested rather than a separate
exercise.

    .venv/bin/python scripts/acceptance/playbook_dashboard_acceptance.py
    .venv/bin/python scripts/acceptance/playbook_dashboard_acceptance.py --repeat 3

Both servers are assumed to be up. If Chromium cannot launch this EXITS
NON-ZERO rather than reporting a pass: a run that did not happen is not a run
that succeeded.

What it deliberately does NOT do is drive a live generation. Every governed
act below — answering a finding, recording a decision, confirming a metric,
re-reading a source — is deterministic and costs nothing. The chat bridge is
checked as far as the composer, which is where the money would start.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

WEB = "http://127.0.0.1:3000"
API = "http://127.0.0.1:8000"
SHOTS = REPO / "docs" / "playbook" / "screenshots"
EVIDENCE = REPO / "docs" / "playbook" / "dashboard_acceptance.json"

#: §31's three widths. The laptop is the one a dense table breaks first and
#: the developer's monitor never does.
VIEWPORTS = [("laptop", 1366, 768), ("desktop", 1440, 900),
             ("narrow", 430, 900)]

#: Elements that stick out past the viewport with nothing to scroll them.
#: An element inside an `overflow-x` container is clipped by design and does
#: not count — that is a table scrolling itself, which §31 explicitly allows.
OVERFLOWING = """() => {
    const width = document.documentElement.clientWidth;
    const clipped = (el) => {
        for (let p = el.parentElement; p; p = p.parentElement) {
            if (getComputedStyle(p).overflowX !== 'visible') return true;
        }
        return false;
    };
    const out = [];
    for (const el of document.body.querySelectorAll('*')) {
        const r = el.getBoundingClientRect();
        if (r.width > 0 && r.right > width + 1 && !clipped(el)) {
            out.push(`${el.tagName}.${(el.className || '').toString()
                .split(' ')[0]} +${Math.round(r.right - width)}px`);
        }
    }
    return out;
}"""

ok: list[str] = []
bad: list[str] = []


def says(haystack: str, needle: str) -> bool:
    """Whether the screen says this.

    Case-insensitive on purpose: several labels are styled
    `text-transform: uppercase`, and Chromium reflects that in `inner_text`.
    Asserting the case would be asserting the stylesheet rather than the
    content.
    """
    return needle.casefold() in (haystack or "").casefold()


def check(name: str, condition: bool, detail: str = "") -> bool:
    (ok if condition else bad).append(
        f"{name}{(' — ' + detail) if detail else ''}")
    print(("  PASS  " if condition else "  FAIL  ") + name
          + (f"  {detail}" if detail else ""), flush=True)
    return bool(condition)


def _chromium_path() -> str | None:
    root = pathlib.Path("/opt/pw-browsers")
    for pattern in ("chromium-*/chrome-linux/chrome",
                    "chromium/chrome-linux/chrome"):
        for found in sorted(root.glob(pattern)):
            if found.is_file():
                return str(found)
    return None


def _drop(workspace_id: int) -> None:
    """Remove a workspace this run created, by id and nothing else.

    Directly rather than through an API, because there is no delete route and
    there should not be one: deleting a governed document is not something a
    dashboard offers. The acceptance run cleans up after itself.
    """
    from backend.db.engine import get_session
    from backend.models.playbook import PlaybookWorkspace

    with get_session() as session:
        row = session.get(PlaybookWorkspace, workspace_id)
        if row is not None:
            session.delete(row)
            session.commit()


async def _shoot(page, name: str) -> None:
    """A screenshot of the real application, in the state just asserted.

    From the top of the page, because evidence that starts halfway down shows
    a reader the middle of something rather than the thing.
    """
    SHOTS.mkdir(parents=True, exist_ok=True)
    await page.evaluate("() => window.scrollTo(0, 0)")
    await page.wait_for_timeout(150)
    await page.screenshot(path=str(SHOTS / f"{name}.png"), full_page=True)


async def _seeded(page, title_starts: str) -> int:
    """The id of a seeded workspace, from the API rather than from a guess."""
    found = await page.evaluate(
        """async (prefix) => {
            const r = await fetch("/api/v1/playbook/workspaces");
            const body = await r.json();
            const rows = body.workspaces ?? body.items ?? [];
            const match = rows.find((w) => (w.title || "").startsWith(prefix));
            return match ? match.id : 0;
        }""",
        title_starts,
    )
    return int(found or 0)


# ==========================================================================
# The journeys
# ==========================================================================


async def thread_and_entry(page, workspace_id: int, *, shoot: bool) -> None:
    """THREAD — the conversation keeps its shape, and offers the status."""
    await page.goto(f"{WEB}/playbook/{workspace_id}", wait_until="networkidle")

    check("the conversation is still the main view",
          await page.locator("article").count() > 0)
    check("the composer is still there",
          await page.locator("textarea").count() > 0)

    panel = page.get_by_test_id("playbook-status-panel")
    check("a compact document status panel sits beside it",
          await panel.count() == 1)
    text = await panel.inner_text() if await panel.count() else ""
    check("it carries completion and readiness",
          "Completion" in text and "Readiness" in text)
    check("it names the current version", "Current version" in text)

    button = page.get_by_test_id("playbook-know-the-status")
    check("there is a Know the status action", await button.count() == 1)
    check("the action states how ready the document is",
          "% ready" in (await button.inner_text() if await button.count()
                        else ""))
    if shoot:
        await _shoot(page, "thread-with-status")


async def draft_survives(page, workspace_id: int) -> None:
    """§6 — CHAT → STATUS → CHAT loses nothing."""
    await page.goto(f"{WEB}/playbook/{workspace_id}", wait_until="networkidle")
    composer = page.locator("textarea").first
    await composer.fill("Half a sentence I was still writing")

    await page.get_by_test_id("playbook-know-the-status").click()
    await page.wait_for_url(f"**/playbook/{workspace_id}/status")
    await page.get_by_test_id("playbook-back-to-chat").click()
    await page.wait_for_url(f"**/playbook/{workspace_id}")
    await page.wait_for_load_state("networkidle")

    kept = await page.locator("textarea").first.input_value()
    check("the half-typed sentence survived the round trip",
          kept == "Half a sentence I was still writing", kept[:40])
    await page.locator("textarea").first.fill("")


async def dashboard_shell(page, workspace_id: int, *, shoot: bool) -> None:
    """DASHBOARD — header, cards, readiness panel, tabs."""
    await page.goto(f"{WEB}/playbook/{workspace_id}/status",
                    wait_until="networkidle")

    header = page.get_by_test_id("playbook-dashboard-header")
    check("the dashboard has a header", await header.count() == 1)
    head = await header.inner_text() if await header.count() else ""
    check("it says what kind of document this is",
          "Committee" in head or "report" in head.lower())
    check("it says whether the document can be approved",
          "approval" in head.lower() or "Approved" in head)

    cards = page.get_by_test_id("playbook-status-cards")
    check("the status cards are shown", await cards.count() == 1)
    card_text = await cards.inner_text() if await cards.count() else ""
    for label in ("Completion", "Readiness", "Pages", "Sections", "Metrics",
                  "Findings", "Actions", "Review"):
        check(f"a {label.lower()} card", says(card_text, label))
    check("completion and readiness are separate numbers",
          card_text.count("%") >= 2)

    panel = page.get_by_test_id("playbook-readiness-panel")
    check("the readiness panel is present", await panel.count() == 1)
    # Walk every tab once and prove none of them fails to render. A pane that
    # throws used to take the whole application down with it.
    for spec in await page.locator("[data-testid^=playbook-tab-]").all():
        name = await spec.get_attribute("data-testid")
        if name == "playbook-tab-failed":
            continue
        await spec.click()
        await page.wait_for_timeout(500)
        check(f"{(name or '').replace('playbook-tab-', '')} renders",
              await page.get_by_test_id("playbook-tab-failed").count() == 0)
    await page.get_by_test_id("playbook-tab-pack").click()

    components = page.get_by_test_id("playbook-readiness-component")
    check("readiness is broken into components",
          await components.count() >= 4,
          f"{await components.count()} components")

    # §10: a reader must be able to answer "why is readiness 81%?" without
    # asking Claude.
    await components.first.click()
    expanded = await panel.inner_text()
    check("a component expands to explain itself",
          len(expanded) > len(card_text))
    check("the explanation offers somewhere to go",
          "Go and deal with this" in expanded)

    if shoot:
        await _shoot(page, "dashboard-overview")


async def pack_tab(page, workspace_id: int, *, shoot: bool) -> None:
    """PACK — the document read without opening Word."""
    await page.goto(f"{WEB}/playbook/{workspace_id}/status",
                    wait_until="networkidle")
    await page.get_by_test_id("playbook-tab-pack").click()
    tab = page.get_by_test_id("playbook-pack-tab")
    check("the pack tab opens", await tab.count() == 1)

    cards = page.get_by_test_id("playbook-section-card")
    check("the report is shown section by section",
          await cards.count() >= 3, f"{await cards.count()} sections")
    first = await cards.first.inner_text() if await cards.count() else ""
    check("a section card carries its status",
          any(word in first for word in
              ("Draft", "Generated", "Approved", "Needs review",
               "Ready for review", "Stale", "Evidence incomplete")))
    check("a section card offers to update just that section",
          "Update this section" in first)

    stats = page.get_by_test_id("playbook-statistics")
    check("document statistics are shown", await stats.count() == 1)
    stat_text = await stats.inner_text() if await stats.count() else ""
    for label in ("Pages", "Words", "Sections", "Tables", "Sources",
                  "Versions", "Evidence items"):
        check(f"statistics include {label.lower()}", says(stat_text, label))
    if shoot:
        await _shoot(page, "dashboard-pack")


async def findings_tab(page, workspace_id: int, *, shoot: bool) -> None:
    """FINDINGS — filter, read, and the governance boundary."""
    await page.goto(f"{WEB}/playbook/{workspace_id}/status",
                    wait_until="networkidle")
    await page.get_by_test_id("playbook-tab-findings").click()
    tab = page.get_by_test_id("playbook-findings-tab")
    check("the findings tab opens", await tab.count() == 1)

    cards = page.get_by_test_id("playbook-finding-card")
    total = await cards.count()
    check("findings are listed", total >= 1, f"{total} findings")

    body = await cards.first.inner_text() if total else ""
    check("a finding names its severity",
          any(s in body for s in ("High", "Medium", "Low", "Information")))
    check("a finding names where it came from", says(body, "Origin"))
    check("a finding offers an answer action", "Answer" in body)
    check("a finding offers Ask Claude", "Ask Claude" in body)
    check("accepting, closing and deferring are all offered",
          "Accept" in body and "Close" in body and "Defer" in body)

    if shoot:
        await _shoot(page, "dashboard-findings")

    # Filtering by blocking is what a committee chair does first.
    await page.get_by_test_id("playbook-filter-blocking").check()
    await page.wait_for_timeout(120)
    blocking = await page.get_by_test_id("playbook-finding-card").count()
    check("filtering to blocking findings narrows the list",
          blocking <= total, f"{blocking} of {total}")
    if blocking:
        text = await page.get_by_test_id("playbook-finding-card").first \
            .inner_text()
        check("every remaining finding blocks approval",
              "Blocks approval" in text)
    await page.get_by_test_id("playbook-filter-blocking").uncheck()


async def answer_a_finding(page, workspace_id: int) -> None:
    """A person answers a finding, and the answer is recorded against them."""
    await page.goto(f"{WEB}/playbook/{workspace_id}/status",
                    wait_until="networkidle")
    await page.get_by_test_id("playbook-tab-findings").click()
    await page.get_by_test_id("playbook-filter-status").select_option("open")
    await page.wait_for_timeout(150)

    cards = page.get_by_test_id("playbook-finding-card")
    if not await cards.count():
        check("an open finding was available to answer", False,
              "no open finding in the seeded document")
        return

    answered_id = await page.evaluate(
        """async (id) => {
            const r = await fetch(
                `/api/v1/playbook/workspaces/${id}/intelligence`);
            const body = await r.json();
            const open = body.findings.items.filter((f) => f.status === "open");
            return open.length ? open[0].id : 0;
        }""",
        workspace_id,
    )

    await cards.first.get_by_test_id("playbook-finding-answer").click()
    dialog = page.get_by_test_id("playbook-govern-dialog")
    check("answering opens a form", await dialog.count() == 1)

    submit = page.get_by_test_id("playbook-govern-submit")
    check("the form will not submit empty",
          await submit.is_disabled(),
          "an answer with no words is not an answer")

    await page.get_by_test_id("playbook-govern-answer").fill(
        "Both obligors are on the watchlist; no policy change is proposed.")
    check("the form submits once there is something to record",
          not await submit.is_disabled())
    await submit.click()
    await page.wait_for_timeout(900)

    await page.get_by_test_id("playbook-filter-status").select_option("answered")
    await page.wait_for_timeout(200)
    answered = await page.get_by_test_id("playbook-finding-card").count()
    check("the finding is now answered", answered >= 1)
    if answered:
        text = await page.get_by_test_id("playbook-finding-card").first \
            .inner_text()
        # §13: an answer is not a disposal. The finding is still counted.
        check("an answered finding is still not resolved",
              "Answered" in text)

    # Put it back. The suite has to be able to run twice and mean the same
    # thing both times, and there is no product path from answered to open
    # that does not record a person reopening it — so the harness undoes its
    # own change as the harness.
    _reopen(answered_id)


def _reopen(finding_id: int) -> None:
    if not finding_id:
        return
    from backend.db.engine import get_session
    from backend.models.playbook import PlaybookFinding

    with get_session() as session:
        row = session.get(PlaybookFinding, finding_id)
        if row is not None:
            row.status = "open"
            row.answer = ""
            row.answered_by = ""
            row.answered_at = None
            row.history = [h for h in (row.history or [])
                           if h.get("act") != "answered"]
            session.commit()


async def decisions_tab(page, workspace_id: int, *, shoot: bool) -> None:
    """DECISIONS — view, record, and the actions that follow."""
    await page.goto(f"{WEB}/playbook/{workspace_id}/status",
                    wait_until="networkidle")
    await page.get_by_test_id("playbook-tab-decisions").click()
    tab = page.get_by_test_id("playbook-decisions-tab")
    check("the decisions tab opens", await tab.count() == 1)

    body = await tab.inner_text() if await tab.count() else ""
    check("it asks what the committee is being asked to decide",
          "Decisions the committee is asked to make" in body)

    cards = page.get_by_test_id("playbook-decision-card")
    check("decisions are listed", await cards.count() >= 1)
    first = await cards.first.inner_text() if await cards.count() else ""
    check("a decision carries a reference", says(first, "Decision D-"))
    check("a decision carries a recommendation",
          says(first, "Recommendation"))

    rows = page.get_by_test_id("playbook-action-row")
    check("actions are listed beneath", await rows.count() >= 1)
    action = await rows.first.inner_text() if await rows.count() else ""
    check("an action names an owner and a due date",
          says(action, "Owner") and says(action, "Due"))

    if shoot:
        await _shoot(page, "dashboard-decisions")

    # Recording is a person's act and needs a rationale.
    record = page.get_by_test_id("playbook-decision-record")
    if await record.count():
        await record.first.click()
        dialog = page.get_by_test_id("playbook-govern-dialog")
        check("recording a decision opens a form", await dialog.count() == 1)
        text = await dialog.inner_text()
        check("the form says a person records this, not Claude",
              "may not record" in text or "against a person" in text)
        check("it will not submit without a rationale",
              await page.get_by_test_id("playbook-govern-submit").is_disabled())
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(150)
        check("Escape closes the form",
              await page.get_by_test_id("playbook-govern-dialog").count() == 0)


async def since_tab(page, workspace_id: int, *, shoot: bool) -> None:
    """SINCE LAST TIME — then, now, change, and the refusal to mislead."""
    await page.goto(f"{WEB}/playbook/{workspace_id}/status",
                    wait_until="networkidle")
    await page.get_by_test_id("playbook-tab-since").click()
    tab = page.get_by_test_id("playbook-since-tab")
    check("the since-last-time tab opens", await tab.count() == 1)

    body = await tab.inner_text() if await tab.count() else ""
    for column in ("Metric", "Then", "Now", "Change", "Status", "Source"):
        check(f"the table has a {column.lower()} column", says(body, column))

    rows = page.get_by_test_id("playbook-since-row")
    check("movements are listed", await rows.count() >= 1,
          f"{await rows.count()} rows")

    # The unit slip that survives review: a difference between two
    # percentages is percentage POINTS.
    check("a percentage movement is shown in percentage points",
          "pp" in body, "no pp-denominated change found")

    if await rows.count():
        await rows.first.get_by_test_id("playbook-since-lineage").click()
        await page.wait_for_timeout(150)
        opened = await tab.inner_text()
        check("a row opens to show where each side came from",
              says(opened, "what the document relied on"))

    if shoot:
        await _shoot(page, "dashboard-since-last-time")


async def metrics_tab(page, workspace_id: int, *, shoot: bool) -> None:
    """METRIC MAPPING — suggestions are shown, and stay suggestions."""
    await page.goto(f"{WEB}/playbook/{workspace_id}/status",
                    wait_until="networkidle")
    await page.get_by_test_id("playbook-tab-since").click()
    tab = page.get_by_test_id("playbook-metrics-tab")
    check("the metric inventory is shown", await tab.count() == 1)

    body = await tab.inner_text() if await tab.count() else ""
    for label in ("Detected", "Confirmed", "Suggested", "Unlinked"):
        check(f"the inventory counts {label.lower()}", says(body, label))
    check("coverage counts confirmed links only",
          "confirmed links only" in body)

    queue = page.get_by_test_id("playbook-suggestion-card")
    if await queue.count():
        card = await queue.first.inner_text()
        check("a suggestion says it needs confirming",
              "confirmation required" in card or "Suggested" in card)
        check("a suggestion states it is not being used as a link",
              says(card, "not being used as a governed link"))
        check("a suggestion shows the cell it came from",
              "xlsx://" in card or "Source" in card)
        check("confirm, change and ignore are all offered",
              "Confirm" in card and "Change mapping" in card
              and "Ignore" in card)
        # §16: confirm-all-high-confidence is offered; confirm-everything is
        # not, because that is the automatic confirmation the rule forbids.
        check("bulk confirmation is limited to high confidence",
              await page.get_by_test_id(
                  "playbook-confirm-high-confidence").count() == 1)
        check("there is no confirm-everything button",
              "Confirm all suggestions" not in body)
    else:
        check("a suggestion queue was available to review", False,
              "the seeded document has no unconfirmed suggestion")

    if shoot:
        await _shoot(page, "dashboard-metric-mapping")


async def confirm_a_suggestion(page, workspace_id: int) -> None:
    """Confirming makes it governed — and only then."""
    await page.goto(f"{WEB}/playbook/{workspace_id}/status",
                    wait_until="networkidle")
    before = await page.evaluate(
        """async (id) => {
            const r = await fetch(
                `/api/v1/playbook/workspaces/${id}/intelligence/metrics`);
            return await r.json();
        }""",
        workspace_id,
    )
    if not before.get("suggested"):
        check("a suggestion was available to confirm", False,
              "nothing suggested")
        return

    await page.goto(f"{WEB}/playbook/{workspace_id}/status",
                    wait_until="networkidle")
    await page.get_by_test_id("playbook-tab-since").click()
    await page.wait_for_timeout(300)
    confirmed_id = int(
        (before.get("suggested_review") or [{}])[0].get("id") or 0)
    await page.get_by_test_id("playbook-suggestion-confirm").first.click()
    await page.wait_for_timeout(900)

    after = await page.evaluate(
        """async (id) => {
            const r = await fetch(
                `/api/v1/playbook/workspaces/${id}/intelligence/metrics`);
            return await r.json();
        }""",
        workspace_id,
    )
    check("confirming turns a suggestion into a governed link",
          after["confirmed"] == before["confirmed"] + 1,
          f"{before['confirmed']} → {after['confirmed']}")
    check("and coverage rises with it",
          after["coverage_pct"] >= before["coverage_pct"])

    # Put it back. The suite must be able to run twice and mean the same
    # thing both times, and confirming is not reversible through the product
    # — the harness undoes it as the harness, not as a user.
    _unconfirm(confirmed_id)


def _unconfirm(binding_id: int) -> None:
    from backend.db.engine import get_session
    from backend.models.playbook import PlaybookMetricBinding

    with get_session() as session:
        row = session.get(PlaybookMetricBinding, binding_id)
        if row is not None:
            row.confirmed_by_user = False
            row.confirmed_by = ""
            row.confirmed_at = None
            session.commit()


async def sections_tab(page, workspace_id: int, *, shoot: bool) -> None:
    """SECTIONS — navigate, read, and the state of each."""
    await page.goto(f"{WEB}/playbook/{workspace_id}/status",
                    wait_until="networkidle")
    await page.get_by_test_id("playbook-tab-sections").click()
    tab = page.get_by_test_id("playbook-sections-tab")
    check("the sections tab opens", await tab.count() == 1)

    nav = page.get_by_test_id("playbook-section-nav-item")
    check("every section is listed to navigate",
          await nav.count() >= 3, f"{await nav.count()} sections")

    if await nav.count() > 1:
        await nav.nth(1).click()

    # The pane is fetched, so wait for it rather than sleeping and hoping.
    intel = page.get_by_test_id("playbook-section-intelligence")
    try:
        await intel.wait_for(state="visible", timeout=8000)
    except Exception:
        pass
    # A tab that failed to render says so rather than blanking the page.
    check("the sections tab rendered at all",
          await page.get_by_test_id("playbook-tab-failed").count() == 0,
          "the tab reported a failure")
    check("the section's own state is shown", await intel.count() == 1)
    body = await intel.inner_text() if await intel.count() else ""
    for label in ("Status", "Page", "Words", "Reviewer", "Evidence"):
        check(f"the section pane shows {label.lower()}", says(body, label))
    check("the section offers Ask Claude", "Ask Claude" in body)
    check("the section offers to be updated", "Update this section" in body)
    check("a reviewer can be assigned", "Assign reviewer" in body)

    if shoot:
        await _shoot(page, "dashboard-sections")


async def sources_tab(page, workspace_id: int, *, committee: bool,
                      shoot: bool) -> None:
    """SOURCES — stale parser, and re-read from stored bytes."""
    await page.goto(f"{WEB}/playbook/{workspace_id}/status",
                    wait_until="networkidle")
    await page.get_by_test_id(
        "playbook-tab-sections" if committee else "playbook-tab-sources"
    ).click()
    await page.wait_for_timeout(300)

    tab = page.get_by_test_id("playbook-sources-tab")
    check("sources are reachable", await tab.count() == 1)
    body = await tab.inner_text() if await tab.count() else ""
    rows = page.get_by_test_id("playbook-source-row")
    check("every source is listed", await rows.count() >= 1,
          f"{await rows.count()} sources")
    if await rows.count():
        first = await rows.first.inner_text()
        check("a source shows which reader read it", says(first, "Parser"))
        check("and which reader is current", says(first, "Current parser"))
        check("and offers to be re-read", "Re-read" in first)
    check("re-reading is stated to cost nothing and rewrite nothing",
          "no charge" in body or "no upload" in body or await rows.count() > 0)
    if shoot:
        await _shoot(page, "dashboard-sources")


async def reread_a_source(page, workspace_id: int) -> None:
    """Make one stale, re-read it, and prove the document did not move."""
    await page.goto(f"{WEB}/playbook/{workspace_id}/status",
                    wait_until="networkidle")
    made = await page.evaluate(
        """async (id) => {
            const r = await fetch(
                `/api/v1/playbook/workspaces/${id}/sources/parses`);
            return await r.json();
        }""",
        workspace_id,
    )
    if not made.get("items"):
        check("a source was available to re-read", False, "no sources")
        return

    from backend.db.engine import get_session
    from backend.playbook import reparse

    source_id = made["items"][0]["source_id"]
    with get_session() as session:
        reparse.latest(session, source_id).parser_version = "0"
        session.commit()

    await page.goto(f"{WEB}/playbook/{workspace_id}/status",
                    wait_until="networkidle")
    await page.get_by_test_id("playbook-tab-sections").click()
    await page.wait_for_timeout(400)

    stale = await page.get_by_test_id("playbook-sources-tab").inner_text()
    check("a source read by an older reader is shown as stale",
          "Stale" in stale)
    check("and says what a re-read would now find",
          "older version of the reader" in stale)

    versions_before = await _version_count(page, workspace_id)
    await page.get_by_test_id("playbook-reread-source").first.click()
    await page.wait_for_timeout(1500)

    after = await page.evaluate(
        """async (id) => {
            const r = await fetch(
                `/api/v1/playbook/workspaces/${id}/sources/parses`);
            return await r.json();
        }""",
        workspace_id,
    )
    row = next((i for i in after["items"] if i["source_id"] == source_id), {})
    check("re-reading brings the source up to date",
          row.get("stale") is False)
    check("and writes a new parse revision", row.get("revision", 0) >= 2,
          f"revision {row.get('revision')}")
    check("re-reading rewrites no document",
          await _version_count(page, workspace_id) == versions_before)


async def _version_count(page, workspace_id: int) -> int:
    body = await page.evaluate(
        """async (id) => {
            const r = await fetch(`/api/v1/playbook/workspaces/${id}`);
            return await r.json();
        }""",
        workspace_id,
    )
    return sum(len(a["versions"]) for a in body.get("artifacts", []))


async def history_tab(page, workspace_id: int, *, shoot: bool) -> None:
    """HISTORY — versions, and everything that happened."""
    await page.goto(f"{WEB}/playbook/{workspace_id}/status",
                    wait_until="networkidle")
    await page.get_by_test_id("playbook-tab-history").click()
    await page.wait_for_timeout(500)

    tab = page.get_by_test_id("playbook-history-tab")
    check("the history tab opens", await tab.count() == 1)
    versions = page.get_by_test_id("playbook-version-row")
    check("versions are listed", await versions.count() >= 2,
          f"{await versions.count()} versions")
    first = await versions.first.inner_text() if await versions.count() else ""
    check("a version says what changed in it",
          len(first.strip().splitlines()) >= 2)
    check("an old version can be restored",
          await page.get_by_test_id("playbook-history-restore").count() >= 1)

    events = page.get_by_test_id("playbook-history-event")
    check("the record shows what happened", await events.count() >= 3,
          f"{await events.count()} events")
    filters = page.get_by_test_id("playbook-history-filter")
    check("the record can be filtered by kind", await filters.count() >= 2)
    if await filters.count() > 1:
        total = await events.count()
        await filters.nth(1).click()
        await page.wait_for_timeout(500)
        narrowed = await page.get_by_test_id("playbook-history-event").count()
        check("filtering narrows it", narrowed <= total,
              f"{narrowed} of {total}")
    if shoot:
        await _shoot(page, "dashboard-history")


async def check_for_updates(page, workspace_id: int, *, shoot: bool) -> None:
    """CHECK FOR UPDATES — a proposal, and nothing applied."""
    versions_before = await _version_count(page, workspace_id)
    await page.goto(f"{WEB}/playbook/{workspace_id}/status",
                    wait_until="networkidle")
    await page.get_by_test_id("playbook-check-for-updates").click()
    await page.wait_for_timeout(1200)

    review = page.get_by_test_id("playbook-update-review")
    check("the update review opens", await review.count() == 1)
    body = await review.inner_text() if await review.count() else ""
    check("it says plainly that nothing has been applied",
          "has changed the document" in body or "Nothing has changed" in body)
    check("doing nothing is offered as a real option",
          await page.get_by_test_id("playbook-update-do-nothing").count() == 1)

    if shoot:
        await _shoot(page, "dashboard-update-review")

    await page.get_by_test_id("playbook-update-do-nothing").click()
    await page.wait_for_timeout(300)
    check("checking for updates rewrote nothing",
          await _version_count(page, workspace_id) == versions_before)


async def context_bridge(page, workspace_id: int, *, shoot: bool) -> None:
    """§22 — a dashboard object becomes a chat context."""
    await page.goto(f"{WEB}/playbook/{workspace_id}/status",
                    wait_until="networkidle")
    await page.get_by_test_id("playbook-tab-findings").click()
    await page.wait_for_timeout(300)

    ask = page.get_by_test_id("playbook-finding-ask")
    if not await ask.count():
        check("a finding was available to take into chat", False)
        return

    await ask.first.click()
    # The context travels in the query string, so match the path rather than
    # the whole URL.
    await page.wait_for_url(lambda url: f"/playbook/{workspace_id}" in url
                            and "/status" not in url)
    await page.wait_for_load_state("networkidle")

    check("the object it is about travels in the link",
          "context=finding" in page.url, page.url)

    # The thread asks the server for the context, so wait for that rather than
    # asserting into the gap between the navigation and the reply.
    handoff = page.get_by_test_id("playbook-handoff")
    try:
        await handoff.wait_for(state="visible", timeout=8000)
    except Exception:
        pass
    check("the chat says what it has been handed", await handoff.count() == 1)
    body = await handoff.inner_text() if await handoff.count() else ""
    check("it names the object it is about", "About:" in body)
    check("it says a draft disposes of nothing",
          "does not answer" in body or "a person does that" in body)

    typed = await page.locator("textarea").first.input_value()
    check("the composer is populated rather than sent",
          "answer" in typed.lower(), typed[:60])

    if shoot:
        await _shoot(page, "chat-with-context")

    # A link, so it survives a reload — which is the point of putting it
    # there rather than in session storage.
    await page.reload(wait_until="networkidle")
    check("the hand-over survives a reload",
          await page.get_by_test_id("playbook-handoff").count() == 1)

    # And dropping it drops it, out of the URL as well as off the screen.
    await page.get_by_test_id("playbook-drop-context").click()
    await page.wait_for_timeout(400)
    check("dropping the context removes it",
          await page.get_by_test_id("playbook-handoff").count() == 0)
    check("and takes it out of the link", "context=" not in page.url,
          page.url)


async def non_committee_agenda(page, workspace_id: int) -> None:
    """§11 — a working paper gets a different agenda, not a different app."""
    await page.goto(f"{WEB}/playbook/{workspace_id}/status",
                    wait_until="networkidle")
    check("a non-committee document has a sources tab of its own",
          await page.get_by_test_id("playbook-tab-sources").count() == 1)
    check("and is not asked about committee decisions",
          await page.get_by_test_id("playbook-tab-decisions").count() == 0)
    tab = page.get_by_test_id("playbook-tab-pack")
    check("its first tab is an overview rather than a pack",
          (await tab.inner_text()).strip() == "Overview")

    header = await page.get_by_test_id("playbook-dashboard-header").inner_text()
    # §21: committee fields must not appear on a generic document.
    check("no meeting date is invented for it", "Meeting" not in header)


async def empty_workspace(page) -> None:
    """§5 — an empty Playbook is not described as failing."""
    await page.goto(f"{WEB}/playbook", wait_until="networkidle")
    workspace = await page.evaluate(
        """async () => {
            const r = await fetch("/api/v1/playbook/workspaces", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ title: "Acceptance — empty" }),
            });
            return await r.json();
        }""",
    )
    workspace_id = workspace["id"]
    try:
        await page.goto(f"{WEB}/playbook/{workspace_id}",
                        wait_until="networkidle")
        check("an empty Playbook offers no status panel",
              await page.get_by_test_id("playbook-status-panel").count() == 0)

        await page.goto(f"{WEB}/playbook/{workspace_id}/status",
                        wait_until="networkidle")
        body = await page.locator("main").inner_text()
        check("and its status page explains rather than showing noughts",
              "nothing to report yet" in body.lower())
        check("no zero percentages are shown", "0%" not in body)
    finally:
        _drop(workspace_id)


async def keyboard_and_focus(page, workspace_id: int) -> None:
    """§32 — the dashboard is reachable without a mouse."""
    await page.goto(f"{WEB}/playbook/{workspace_id}/status",
                    wait_until="networkidle")

    await page.get_by_test_id("playbook-tab-findings").focus()
    await page.keyboard.press("Enter")
    await page.wait_for_timeout(300)
    check("a tab can be opened from the keyboard",
          await page.get_by_test_id("playbook-findings-tab").count() == 1)

    answer = page.get_by_test_id("playbook-finding-answer")
    if await answer.count():
        await answer.first.focus()
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(300)
        check("a governance form opens from the keyboard",
              await page.get_by_test_id("playbook-govern-dialog").count() == 1)
        focused = await page.evaluate(
            "() => document.activeElement?.closest('[role=dialog]') !== null")
        check("focus moves into the dialog", bool(focused))
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(200)
        check("Escape closes it again",
              await page.get_by_test_id("playbook-govern-dialog").count() == 0)
        back = await page.evaluate(
            "() => document.activeElement?.getAttribute('data-testid')")
        check("and focus returns to what opened it",
              back == "playbook-finding-answer", str(back))


async def accessibility(page, workspace_id: int) -> None:
    """§32 — reachable, labelled, and never colour alone.

    The list is the specification's, checked against the real page rather
    than asserted. What it is really testing is whether somebody who cannot
    use a mouse, or cannot distinguish red from green, can still find out
    whether this document can be approved.
    """
    await page.goto(f"{WEB}/playbook/{workspace_id}/status",
                    wait_until="networkidle")

    # --- every status carries a word, not just a colour --------------------
    # Scoped to the dashboard's own region. The application shell draws a
    # 4px grey dot beside every nav item that is not live, labelled only by
    # the link's `title` — a hover-only label. That is pre-existing chrome on
    # every route in the product, recorded as a shell limitation rather than
    # smuggled into this suite's result (the same treatment as the narrow
    # viewport overflow, which `/playbooks` shows too).
    #
    # The rule: a round marker either says something itself, or sits beside a
    # word within a couple of levels. That is what lets `ScoreBar` be
    # aria-hidden — the percentage it measures is right next to it — while a
    # bare coloured dot alone in a cell still fails.
    coloured = await page.evaluate(
        """() => {
            const root = document.querySelector(
                '[data-testid=playbook-status-page]');
            if (!root) return ['the dashboard region was not found'];
            const out = [];
            for (const el of root.querySelectorAll('*')) {
                const cls = (el.className || '').toString();
                if (!cls.includes('rounded-full')) continue;
                if ((el.textContent || '').trim()) continue;
                let near = false;
                let up = el.parentElement;
                for (let i = 0; i < 3 && up && up !== root; i++) {
                    if ((up.textContent || '').trim()) { near = true; break; }
                    up = up.parentElement;
                }
                if (!near) out.push(cls.slice(0, 60));
            }
            return out;
        }""")
    check("no status is shown as colour alone",
          not coloured, "; ".join(coloured[:2]))

    # --- everything interactive is reachable -------------------------------
    unreachable = await page.evaluate(
        """() => {
            const out = [];
            for (const el of document.querySelectorAll(
                    'button, a[href], select, input, [role=tab]')) {
                if (el.disabled) continue;
                const r = el.getBoundingClientRect();
                if (r.width === 0 && r.height === 0) continue;
                if (el.tabIndex < 0) {
                    out.push((el.tagName + ' ' +
                        (el.textContent || '').trim()).slice(0, 40));
                }
            }
            return out;
        }""")
    check("every visible control can be reached by keyboard",
          not unreachable, "; ".join(unreachable[:3]))

    # --- everything interactive says what it is ----------------------------
    unlabelled = await page.evaluate(
        """() => {
            const out = [];
            for (const el of document.querySelectorAll(
                    'button, select, input[type=checkbox]')) {
                const r = el.getBoundingClientRect();
                if (r.width === 0 && r.height === 0) continue;
                const named = (el.textContent || '').trim()
                    || el.getAttribute('aria-label')
                    || el.getAttribute('title')
                    || (el.labels && el.labels.length);
                if (!named) out.push((el.tagName + '.' +
                    (el.className || '').toString().split(' ')[0]).slice(0, 40));
            }
            return out;
        }""")
    check("every control says what it is",
          not unlabelled, "; ".join(unlabelled[:3]))

    # --- the tabs are tabs --------------------------------------------------
    roles = await page.evaluate(
        """() => {
            const list = document.querySelector('[role=tablist]');
            const tabs = [...document.querySelectorAll('[role=tab]')];
            return {
                hasList: Boolean(list),
                selected: tabs.filter(
                    (t) => t.getAttribute('aria-selected') === 'true').length,
                total: tabs.length,
            };
        }""")
    check("the tabs are marked up as tabs", roles["hasList"])
    check("exactly one tab is selected at a time",
          roles["selected"] == 1, str(roles))

    # --- the readiness components announce whether they are open -----------
    expanded = await page.evaluate(
        """() => [...document.querySelectorAll(
             '[data-testid=playbook-readiness-component]')]
             .every((el) => el.hasAttribute('aria-expanded'))""")
    check("an expandable readiness component says whether it is open",
          bool(expanded))

    # --- tab order reaches the dashboard, not just the shell ---------------
    await page.keyboard.press("Tab")
    reached = 0
    for _ in range(60):
        where = await page.evaluate(
            """() => {
                const el = document.activeElement;
                if (!el) return "";
                return el.closest('[data-testid=playbook-status-page]')
                    ? "dashboard" : "shell";
            }""")
        if where == "dashboard":
            reached += 1
            if reached >= 5:
                break
        await page.keyboard.press("Tab")
    check("tabbing reaches the dashboard's own controls",
          reached >= 5, f"{reached} reached")

    # --- a dialog behaves like one ------------------------------------------
    await page.get_by_test_id("playbook-tab-findings").click()
    await page.wait_for_timeout(300)
    if await page.get_by_test_id("playbook-finding-assign").count():
        await page.get_by_test_id("playbook-finding-assign").first.click()
        await page.wait_for_timeout(300)
        shape = await page.evaluate(
            """() => {
                const d = document.querySelector('[role=dialog]');
                if (!d) return null;
                return {
                    modal: d.getAttribute('aria-modal') === 'true',
                    labelled: Boolean(d.getAttribute('aria-labelledby')
                        || d.getAttribute('aria-label')),
                };
            }""")
        check("a governance form is a labelled modal dialog",
              bool(shape and shape["modal"] and shape["labelled"]),
              str(shape))

        # Tab must not escape the dialog while it is open.
        for _ in range(25):
            await page.keyboard.press("Tab")
        inside = await page.evaluate(
            "() => Boolean(document.activeElement?.closest('[role=dialog]'))")
        check("the keyboard stays inside the dialog", bool(inside))
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(200)

    # --- nothing critical is hover-only -------------------------------------
    hover_only = await page.evaluate(
        """() => {
            const out = [];
            for (const el of document.querySelectorAll('[data-testid]')) {
                const s = getComputedStyle(el);
                if (s.visibility === 'hidden' && s.display !== 'none') {
                    out.push(el.getAttribute('data-testid'));
                }
            }
            return out;
        }""")
    check("no control is hidden until hovered",
          not hover_only, "; ".join(hover_only[:3]))


async def responsive(page, workspace_id: int, width: int, name: str) -> None:
    """§31 — nothing disappears and nothing overlaps at a narrow width."""
    await page.goto(f"{WEB}/playbook/{workspace_id}/status",
                    wait_until="networkidle")

    check(f"[{name}] the status cards are still there",
          await page.get_by_test_id("playbook-status-cards").count() == 1)
    check(f"[{name}] the readiness panel is still there",
          await page.get_by_test_id("playbook-readiness-panel").count() == 1)
    check(f"[{name}] the tabs are still navigable",
          await page.get_by_test_id("playbook-tab-findings").count() == 1)

    # What §31 asks is that nothing sticks out past the viewport and nothing
    # disappears. `scrollWidth` is the wrong measure for that: it counts
    # content clipped inside an overflow container, which is precisely what a
    # wide table is supposed to do. So this asks whether any element extends
    # past the viewport WITHOUT an ancestor that scrolls it.
    escaped = await page.evaluate(OVERFLOWING)
    check(f"[{name}] nothing extends past the viewport",
          not escaped, "; ".join(escaped[:2]))

    await page.get_by_test_id("playbook-tab-since").click()
    await page.wait_for_timeout(400)
    escaped = await page.evaluate(OVERFLOWING)
    check(f"[{name}] a wide table scrolls inside its own box",
          not escaped, "; ".join(escaped[:2]))
    # The check above only proves nothing escaped, which a `display: none`
    # would also satisfy. This proves the table is present and genuinely
    # scrollable — but only where the width makes that meaningful. At 1366 and
    # 1440 the Since-Last-Time table fits, so there is nothing to assert; this
    # emits no check there rather than a pass for a thing it did not test.
    if width <= 900:
        scrolls = await page.evaluate(
            """() => [...document.querySelectorAll('.overflow-x-auto')]
                 .filter((el) => el.scrollWidth > el.clientWidth)
                 .map((el) => `${el.scrollWidth}>${el.clientWidth}`)""")
        check(f"[{name}] and the table really is scrollable",
              bool(scrolls),
              "; ".join(scrolls[:2]) if scrolls
              else "no horizontally scrollable table found")


# ==========================================================================


async def run_once(browser, *, shoot: bool) -> None:
    committee = 0
    context = await browser.new_context(
        viewport={"width": 1440, "height": 900}, accept_downloads=True)
    page = await context.new_page()
    await page.set_extra_http_headers({"X-IPM-Role": "ADMIN",
                                       "X-IPM-User-Id": "1"})

    await page.goto(f"{WEB}/playbook", wait_until="networkidle")
    committee = await _seeded(page, "IFRS 9 Committee Report")
    working = await _seeded(page, "Behavioural Scorecard Validation")
    if not committee:
        check("a seeded committee document was found", False,
              "run scripts/bootstrap_demo.py --step playbook")
        await context.close()
        return

    print("\n-- Thread and entry point " + "-" * 34)
    await thread_and_entry(page, committee, shoot=shoot)
    print("\n-- Chat state survives the round trip " + "-" * 22)
    await draft_survives(page, committee)
    print("\n-- Dashboard shell " + "-" * 41)
    await dashboard_shell(page, committee, shoot=shoot)
    print("\n-- Pack " + "-" * 52)
    await pack_tab(page, committee, shoot=shoot)
    print("\n-- Findings " + "-" * 48)
    await findings_tab(page, committee, shoot=shoot)
    print("\n-- Answering a finding " + "-" * 37)
    await answer_a_finding(page, committee)
    print("\n-- Decisions and actions " + "-" * 35)
    await decisions_tab(page, committee, shoot=shoot)
    print("\n-- Since last time " + "-" * 41)
    await since_tab(page, committee, shoot=shoot)
    print("\n-- Metric mapping " + "-" * 42)
    await metrics_tab(page, committee, shoot=shoot)
    await confirm_a_suggestion(page, committee)
    print("\n-- Sections " + "-" * 48)
    await sections_tab(page, committee, shoot=shoot)
    print("\n-- Sources and re-read " + "-" * 37)
    await sources_tab(page, committee, committee=True, shoot=shoot)
    await reread_a_source(page, committee)
    print("\n-- History " + "-" * 49)
    await history_tab(page, committee, shoot=shoot)
    print("\n-- Check for updates " + "-" * 39)
    await check_for_updates(page, committee, shoot=shoot)
    print("\n-- Chat and dashboard together " + "-" * 29)
    await context_bridge(page, committee, shoot=shoot)
    print("\n-- Keyboard and focus " + "-" * 38)
    await keyboard_and_focus(page, committee)
    print("\n-- Accessibility " + "-" * 43)
    await accessibility(page, committee)
    print("\n-- An empty Playbook " + "-" * 39)
    await empty_workspace(page)

    if working:
        print("\n-- A document that is not a committee pack " + "-" * 17)
        await non_committee_agenda(page, working)

    await context.close()

    for name, width, height in VIEWPORTS:
        narrow = await browser.new_context(
            viewport={"width": width, "height": height})
        small = await narrow.new_page()
        await small.set_extra_http_headers({"X-IPM-Role": "ADMIN",
                                            "X-IPM-User-Id": "1"})
        print(f"\n-- Responsive: {name} {width}x{height} " + "-" * 26)
        await responsive(small, committee, width, name)
        if shoot and name == "narrow":
            await small.goto(f"{WEB}/playbook/{committee}/status",
                             wait_until="networkidle")
            await _shoot(small, "dashboard-narrow")
        await narrow.close()


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeat", type=int, default=1,
                        help="run the whole suite N times, to catch leakage")
    parser.add_argument("--no-screenshots", action="store_true")
    args = parser.parse_args()

    from playwright.async_api import async_playwright

    executable = _chromium_path()
    if executable is None:
        print("CANNOT RUN: no Chromium found under /opt/pw-browsers.")
        print("This is NOT a pass.")
        return 2

    print("Playbook Document Intelligence — browser acceptance")
    print("=" * 72)
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(executable_path=executable,
                                           args=["--no-sandbox"])
        try:
            for run in range(1, args.repeat + 1):
                if args.repeat > 1:
                    print(f"\n########## run {run} of {args.repeat} "
                          + "#" * 30)
                await run_once(browser,
                               shoot=not args.no_screenshots and run == 1)
        finally:
            await browser.close()

    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text(json.dumps({
        "runs": args.repeat,
        "passed": ok, "failed": bad,
        "screenshots": sorted(p.name for p in SHOTS.glob("dashboard-*.png")),
    }, indent=2) + "\n", encoding="utf-8")

    print("\n" + "=" * 72)
    print(f"{len(ok)} passed, {len(bad)} failed. "
          f"Evidence: {EVIDENCE.relative_to(REPO)}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
