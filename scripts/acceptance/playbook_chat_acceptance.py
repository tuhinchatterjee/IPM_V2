"""
The Direct Chat conversation, in a real browser.

    PLAYBOOK_SCRIPTED_CHAT=scripts/acceptance/fixtures/scripted_chat.json \
        .venv/bin/python -m uvicorn backend.api.main:app --port 8000
    .venv/bin/python scripts/acceptance/playbook_chat_acceptance.py

The API must be running with `PLAYBOOK_SCRIPTED_CHAT` set, or this exits
non-zero rather than reporting a pass — a browser journey against an
unconfigured server proves only that the interface refuses to generate, which
is not what this file claims to show.

No paid call is made. The assistant's replies and the document it writes come
from the fixture, and `GET /playbook/capabilities` reports `scripted: true` so
the run can prove that about itself rather than asserting it.
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
EVIDENCE = REPO / "docs" / "playbook" / "chat_acceptance.json"

ok: list[str] = []
bad: list[str] = []


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


async def _shoot(page, name: str) -> None:
    SHOTS.mkdir(parents=True, exist_ok=True)
    await page.evaluate("() => window.scrollTo(0, 0)")
    await page.wait_for_timeout(150)
    await page.screenshot(path=str(SHOTS / f"{name}.png"), full_page=True)


async def _new_workspace(page, title: str) -> int:
    got = await page.evaluate(
        """async (title) => {
            const r = await fetch("/api/v1/playbook/workspaces", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({title}),
            });
            return (await r.json()).id;
        }""", title)
    return int(got)


async def _answer_of(page) -> str:
    """The last assistant message on screen."""
    return await page.evaluate(
        """() => {
            const nodes = [...document.querySelectorAll('article')];
            return nodes.length ? nodes[nodes.length - 1].innerText : "";
        }""")


async def _send(page, text: str) -> None:
    box = page.locator("textarea").first
    await box.fill(text)
    await box.press("Enter")


async def _settle(page, contains: str, timeout_ms: int = 60_000) -> bool:
    try:
        await page.wait_for_function(
            """(needle) => {
                const nodes = [...document.querySelectorAll('article')];
                const last = nodes.length ? nodes[nodes.length - 1].innerText : "";
                return last.includes(needle);
            }""", arg=contains, timeout=timeout_ms)
        return True
    except Exception:  # noqa: BLE001 — reported as a failed check, not a crash
        return False


# ==========================================================================


async def a_question_is_just_answered(page, *, shoot: bool) -> None:
    """DC-01, in the browser."""
    workspace = await _new_workspace(page, "Chat acceptance — question")
    await page.goto(f"{WEB}/playbook/{workspace}", wait_until="networkidle")

    await _send(page, "What is the difference between a development and a "
                      "validation report?")
    arrived = await _settle(page, "challenges it independently")
    check("an ordinary question is answered in the thread", arrived)

    answer = await _answer_of(page)
    check("the answer is prose, not a document",
          "# " not in answer and "challenges it independently" in answer)

    state = await page.evaluate(
        """async (id) => {
            const r = await fetch(`/api/v1/playbook/workspaces/${id}`);
            return await r.json();
        }""", workspace)
    check("no document was created for a question",
          state["artifacts"] == [], str(len(state["artifacts"])))
    check("and no file card is on screen",
          "Download" not in answer)
    if shoot:
        await _shoot(page, "chat-question-answered")


async def a_report_is_asked_for_and_arrives(page, *, shoot: bool) -> int:
    """DC-15 and DC-21, in the browser."""
    workspace = await _new_workspace(page, "Chat acceptance — report")
    await page.goto(f"{WEB}/playbook/{workspace}", wait_until="networkidle")

    await _send(page, "Write the Auto Loan development report in Word and PDF.")
    arrived = await _settle(page, "both files are ready", timeout_ms=120_000)
    check("the assistant reports the work it did", arrived)

    state = await page.evaluate(
        """async (id) => {
            const r = await fetch(`/api/v1/playbook/workspaces/${id}`);
            return await r.json();
        }""", workspace)
    artifacts = state.get("artifacts") or []
    check("a document was created", len(artifacts) == 1, str(len(artifacts)))
    versions = artifacts[0]["versions"] if artifacts else []
    formats = sorted(f["format"] for v in versions for f in v["files"])
    check("with Word and PDF", formats == ["docx", "pdf"], str(formats))

    # Real bytes, fetched the way the browser fetches them.
    for version in versions:
        for file in version["files"]:
            size = await page.evaluate(
                """async (id) => {
                    const r = await fetch(
                        `/api/v1/playbook/artifact-files/${id}/download`);
                    return r.ok ? (await r.blob()).size : 0;
                }""", file["id"])
            check(f"the {file['format']} downloads as real bytes",
                  int(size) > 500, f"{size} bytes")

    answer = await _answer_of(page)
    check("the document's own prose is not dumped into the thread",
          "1,050 accounts" not in answer)
    check("and the gap the evidence does not cover is stated",
          "out-of-time" in answer.lower() or "gap" in answer.lower())
    if shoot:
        await _shoot(page, "chat-report-delivered")
    return workspace


async def the_thread_survives_a_reload(page, workspace: int) -> None:
    """DC-02: reopening keeps the conversation and the files."""
    await page.goto(f"{WEB}/playbook/{workspace}", wait_until="networkidle")
    messages = await page.locator("article").count()
    check("the conversation is still there after a reload", messages >= 2,
          f"{messages} messages")

    state = await page.evaluate(
        """async (id) => {
            const r = await fetch(`/api/v1/playbook/workspaces/${id}`);
            return await r.json();
        }""", workspace)
    check("and so is the document",
          len(state.get("artifacts") or []) == 1)


async def the_run_is_scripted(page) -> None:
    """The run proves its own premise rather than asserting it."""
    state = await page.evaluate(
        """async () => {
            const r = await fetch("/api/v1/playbook/capabilities");
            return await r.json();
        }""")
    check("the server says it is answering from a script",
          bool(state["provider"].get("scripted")), str(state["provider"]))
    check("and reports itself configured, so the composer offers to send",
          bool(state["provider"].get("configured")))


# ==========================================================================


async def run(browser, *, shoot: bool) -> None:
    context = await browser.new_context(viewport={"width": 1440, "height": 900})
    page = await context.new_page()
    await page.set_extra_http_headers({"X-IPM-Role": "ADMIN",
                                       "X-IPM-User-Id": "1"})
    await page.goto(f"{WEB}/playbook", wait_until="networkidle")

    print("\n-- The server is scripted " + "-" * 34)
    await the_run_is_scripted(page)
    print("\n-- An ordinary question " + "-" * 36)
    await a_question_is_just_answered(page, shoot=shoot)
    print("\n-- A report is asked for " + "-" * 35)
    workspace = await a_report_is_asked_for_and_arrives(page, shoot=shoot)
    print("\n-- Reopening " + "-" * 47)
    await the_thread_survives_a_reload(page, workspace)

    await context.close()


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-screenshots", action="store_true")
    args = parser.parse_args()

    from playwright.async_api import async_playwright

    executable = _chromium_path()
    if executable is None:
        print("CANNOT RUN: Chromium is not available at /opt/pw-browsers.")
        print("A run that did not happen is not a run that passed.")
        return 2

    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=executable)
        try:
            await run(browser, shoot=not args.no_screenshots)
        finally:
            await browser.close()

    print("\n" + "=" * 72)
    print(f"{len(ok)} passed, {len(bad)} failed. Evidence: "
          f"{EVIDENCE.relative_to(REPO)}")
    EVIDENCE.write_text(json.dumps(
        {"passed": ok, "failed": bad,
         "note": "Driven against a scripted assistant; no provider call was "
                 "made. See backend/playbook/scripted.py."},
        indent=2) + "\n")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
