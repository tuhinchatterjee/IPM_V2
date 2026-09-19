"""
The Direct Chat conversation, in a real browser. Journeys A–M.

    PLAYBOOK_SCRIPTED_CHAT=scripts/acceptance/fixtures/scripted_chat.json \
        .venv/bin/python -m uvicorn backend.api.main:app --port 8000
    .venv/bin/python scripts/acceptance/playbook_chat_acceptance.py
    .venv/bin/python scripts/acceptance/playbook_chat_acceptance.py --repeat 2

The API must be running with `PLAYBOOK_SCRIPTED_CHAT` set, or this exits
non-zero rather than reporting a pass: a browser journey against an
unconfigured server proves only that the interface refuses to generate, which
is not what this file claims to show. The run reads the capability endpoint
first and fails if the server is not scripted.

No paid call is made. Replies, documents and the deliberate failures all come
from the fixture — see `backend/playbook/scripted.py`.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import pathlib
import sys
import time

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

WEB = "http://127.0.0.1:3000"
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


async def _api(page, path: str, method: str = "GET", body: dict | None = None):
    return await page.evaluate(
        """async ({path, method, body}) => {
            const r = await fetch(path, {
                method,
                headers: body ? {"Content-Type": "application/json"} : {},
                body: body ? JSON.stringify(body) : undefined,
            });
            const text = await r.text();
            try { return {status: r.status, body: JSON.parse(text)}; }
            catch { return {status: r.status, body: text}; }
        }""", {"path": path, "method": method, "body": body})


#: Every workspace this run created, so it can take them away again.
CREATED: list[int] = []


async def _new_workspace(page, title: str) -> int:
    got = await _api(page, "/api/v1/playbook/workspaces", "POST",
                     {"title": title})
    workspace = int(got["body"]["id"])
    CREATED.append(workspace)
    return workspace


def _clean_up() -> int:
    """Remove the workspaces this run created, and only those.

    Directly, because there is no delete route and there should not be one —
    deleting a governed document is not something a dashboard offers. Written
    after the omission caused a real failure: fifty-four leftover workspaces
    from earlier runs pushed the seeded demonstration off Recent Playbooks,
    and the workspace and dashboard suites then failed looking for it. The
    repeat run had not caught it, because it compared check counts and not
    the database.
    """
    if not CREATED:
        return 0
    from backend.db.engine import get_session
    from backend.models.playbook import PlaybookWorkspace

    removed = 0
    with get_session() as session:
        for workspace in CREATED:
            row = session.get(PlaybookWorkspace, workspace)
            if row is not None:
                session.delete(row)
                removed += 1
        session.commit()
    CREATED.clear()
    return removed


async def _raw_state(page, workspace: int) -> dict:
    return (await _api(page, f"/api/v1/playbook/workspaces/{workspace}"))["body"]


async def _state(page, workspace: int, timeout_ms: int = 30_000) -> dict:
    """The workspace as the API has it, once the turn is actually stored.

    The DOM and the database do not become true at the same instant. Text
    streams into the thread delta by delta, and the assistant's row is written
    when the turn ends, so a read taken the moment `_settle` sees the sentence
    can still return a thread whose last message is the user's question.

    That is not hypothetical: on a cold server the first journey failed on
    exactly this, twice, while the product was behaving correctly — the same
    journey passed on the second cycle, which is the wrong direction for a
    state-leakage signal and was worth chasing down.

    So this waits, bounded, for the assistant's row to arrive, and then
    returns whatever the API says. It never invents a pass: if the row never
    appears, the last read is returned and the check fails on the truth.
    """
    deadline = time.monotonic() + timeout_ms / 1000
    state = await _raw_state(page, workspace)
    while time.monotonic() < deadline:
        messages = state.get("messages") or []
        if messages and messages[-1]["role"] == "assistant":
            return state
        await asyncio.sleep(0.25)
        state = await _raw_state(page, workspace)
    return state


async def _progress(page, workspace: int) -> dict:
    return (await _api(
        page, f"/api/v1/playbook/workspaces/{workspace}/progress"))["body"]


async def _answer(page) -> str:
    """Everything the thread is showing.

    Not "the last article": a delivered file renders its own card, so after a
    document turn the last article is the card and the assistant's sentences
    are in the one before it. Reading the whole thread is what the user does
    anyway, and it made two checks here pass for the wrong reason before it
    made them fail for the right one.
    """
    return await page.evaluate(
        """() => [...document.querySelectorAll('article')]
                 .map((n) => n.innerText).join("\\n")""")


async def _send(page, text: str) -> None:
    box = page.locator("textarea").first
    await box.fill(text)
    await box.press("Enter")


async def _settle(page, contains: str, timeout_ms: int = 90_000) -> bool:
    try:
        await page.wait_for_function(
            """(needle) => [...document.querySelectorAll('article')]
                 .map((n) => n.innerText).join("\\n").includes(needle)""",
            arg=contains, timeout=timeout_ms)
        return True
    except Exception:  # noqa: BLE001 — a failed check, not a crash
        return False


async def _open(page, workspace: int) -> None:
    await page.goto(f"{WEB}/playbook/{workspace}", wait_until="networkidle")


async def _said(page, workspace: int) -> str:
    """The assistant's own words for the latest turn, as stored.

    The DOM proves the answer is DISPLAYED — `_settle` does that. It is the
    wrong place to check what the answer SAYS: the thread truncates a long
    message for layout, so `innerText` quietly loses the tail and an assertion
    about the last sentence fails while the product is behaving perfectly.
    """
    state = await _state(page, workspace)
    for message in reversed(state.get("messages") or []):
        if message["role"] == "assistant":
            return message["content"].get("text") or ""
    return ""


def _formats(state: dict) -> list[str]:
    return sorted(f["format"] for a in (state.get("artifacts") or [])
                  for v in a["versions"] for f in v["files"])


# ==========================================================================
# The premise
# ==========================================================================


async def the_server_is_scripted(page) -> None:
    body = (await _api(page, "/api/v1/playbook/capabilities"))["body"]
    check("the server says it is answering from a script",
          bool(body["provider"].get("scripted")), str(body["provider"]))
    check("and reports itself configured, so the composer offers to send",
          bool(body["provider"].get("configured")))


# ==========================================================================
# A — an ordinary question
# ==========================================================================


async def journey_a(page, *, shoot: bool) -> None:
    workspace = await _new_workspace(page, "A — ordinary question")
    await _open(page, workspace)
    await _send(page, "What is the difference between a scorecard development "
                      "report and a scorecard validation report?")

    check("[A] the question is answered in the thread",
          await _settle(page, "challenges it independently"))
    state = await _state(page, workspace)
    said = state["messages"][-1]["content"]["text"]
    check("[A] the answer is prose, not a document",
          "# " not in said and "challenges it independently" in said)

    check("[A] no document was created", state["artifacts"] == [])
    check("[A] and no tool was called",
          state["messages"][-1]["content"].get("tools") == [])

    progress = await _progress(page, workspace)
    check("[A] progress says there is nothing to count, not nought",
          progress["available"] is False
          and progress["overall"]["label"] == "Not applicable",
          progress["overall"]["label"])

    await page.reload(wait_until="networkidle")
    check("[A] the conversation survives a refresh",
          await page.locator("article").count() >= 2)
    if shoot:
        await _shoot(page, "chat-a-question")


# ==========================================================================
# B — a question about an attachment
# ==========================================================================


async def journey_b(page, *, shoot: bool, methodology: bytes) -> None:
    workspace = await _new_workspace(page, "B — attachment question")
    await _open(page, workspace)

    uploaded = await page.evaluate(
        """async ({id, b64}) => {
            const bytes = Uint8Array.from(atob(b64), c => c.charCodeAt(0));
            const form = new FormData();
            form.append("file", new Blob([bytes], {type:
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}),
                "methodology.docx");
            form.append("source_role", "methodology");
            const r = await fetch(
                `/api/v1/playbook/workspaces/${id}/sources`,
                {method: "POST", body: form});
            return {status: r.status, body: await r.json()};
        }""", {"id": workspace, "b64": methodology})
    check("[B] the methodology uploads", uploaded["status"] == 201,
          str(uploaded["status"]))

    await _open(page, workspace)
    await _send(page, "Summarise the methodology and tell me what appears "
                      "incomplete.")
    check("[B] the assistant answers from the attachment",
          await _settle(page, "appear incomplete"))

    said = await _said(page, workspace)
    check("[B] and names what is missing rather than filling it",
          "rejects" in said.lower() and "out-of-time" in said.lower())

    state = await _state(page, workspace)
    check("[B] no file was created for a question", state["artifacts"] == [])
    check("[B] the source is attached to the workspace",
          len(state.get("sources") or []) == 1)
    if shoot:
        await _shoot(page, "chat-b-attachment")


# ==========================================================================
# C, D, E, F — the document lifecycle, in one conversation
# ==========================================================================


async def journeys_c_to_f(page, *, shoot: bool) -> None:
    workspace = await _new_workspace(page, "C–F — document lifecycle")
    await _open(page, workspace)

    # --- C: an explicit document request ---------------------------------
    await _send(page, "Using these sources, create a detailed scorecard "
                      "development report in Word and PDF.")
    check("[C] the assistant reports what it produced",
          await _settle(page, "both files are ready", 150_000))
    check("[C] conversational progress appeared first",
          "I will draft that now." in await _said(page, workspace))

    state = await _state(page, workspace)
    check("[C] Word and PDF are both on the version",
          _formats(state) == ["docx", "pdf"], str(_formats(state)))

    for artifact in state["artifacts"]:
        for version in artifact["versions"]:
            for file in version["files"]:
                got = await page.evaluate(
                    """async (id) => {
                        const r = await fetch(
                            `/api/v1/playbook/artifact-files/${id}/download`);
                        return r.ok ? (await r.blob()).size : 0;
                    }""", file["id"])
                check(f"[C] the {file['format']} downloads as real bytes",
                      int(got) > 500, f"{got} bytes")

    progress = await _progress(page, workspace)
    check("[C] progress counts the sections that say something",
          progress["content"]["delivered"] == 6
          and progress["content"]["total"] == 7,
          progress["content"]["label"])
    check("[C] and marks the gap section as needing input",
          any(i["state"] == "needs_input" for i in progress["items"]))
    check("[C] review is a draft that nobody has signed",
          progress["review"]["state"] == "draft"
          and progress["review"]["by"] == "")
    if shoot:
        await _shoot(page, "chat-c-report")

    # --- D: a scoped revision in the same conversation --------------------
    await _send(page, "Shorten the executive summary and make it more "
                      "committee-ready.")
    check("[D] the revision is reported",
          await _settle(page, "Version 2 is saved", 150_000))

    state = await _state(page, workspace)
    versions = state["artifacts"][0]["versions"]
    check("[D] a second version exists", len(versions) == 2, str(len(versions)))
    check("[D] and the first is still there",
          sorted(v["version"] for v in versions) == [1, 2])

    latest = [v for v in versions if v["version"] == 2][0]
    check("[D] the revision needed no re-statement of the document",
          bool(latest["files"]), "no file on v2")
    if shoot:
        await _shoot(page, "chat-d-revision")

    # --- E: a presentation, in the same thread ---------------------------
    await _send(page, "Turn the latest report into a 12-slide committee "
                      "presentation.")
    check("[E] the deck is reported",
          await _settle(page, "ready as PowerPoint", 150_000))

    state = await _state(page, workspace)
    check("[E] a PowerPoint exists in this same Playbook",
          "pptx" in _formats(state), str(_formats(state)))
    check("[E] no separate workspace was needed",
          await page.evaluate("() => window.location.pathname")
          == f"/playbook/{workspace}")
    if shoot:
        await _shoot(page, "chat-e-presentation")

    # --- F: a conversion that reuses what exists -------------------------
    before = await _api(page, "/api/v1/ai/status")
    await _send(page, "Give me a PDF of the latest Word report.")
    check("[F] the conversion is reported",
          await _settle(page, "converted from the Word file", 150_000))
    check("[F] and says nothing was rewritten",
          "Nothing was rewritten" in await _said(page, workspace))
    del before
    if shoot:
        await _shoot(page, "chat-f-conversion")


# ==========================================================================
# G — one format fails, the other survives
# ==========================================================================


async def journey_g(page, *, shoot: bool) -> None:
    workspace = await _new_workspace(page, "G — partial format failure")
    await _open(page, workspace)
    await _send(page, "Write it with a broken PDF.")

    check("[G] the assistant reports the Word file and the PDF failure",
          await _settle(page, "PDF conversion could not be completed", 150_000))
    said = await _said(page, workspace)
    check("[G] the Word file is named as ready", "Word draft is ready" in said)
    check("[G] and a retry is offered", "retry the pdf" in said.lower())

    state = await _state(page, workspace)
    check("[G] only the Word file is on the version",
          _formats(state) == ["docx"], str(_formats(state)))

    [artifact] = state["artifacts"]
    [version] = artifact["versions"]
    [file] = version["files"]
    size = await page.evaluate(
        """async (id) => {
            const r = await fetch(
                `/api/v1/playbook/artifact-files/${id}/download`);
            return r.ok ? (await r.blob()).size : 0;
        }""", file["id"])
    check("[G] and it downloads", int(size) > 500, f"{size} bytes")

    progress = await _progress(page, workspace)
    check("[G] content is unaffected by the format that failed",
          progress["content"]["delivered"] == progress["content"]["total"],
          progress["content"]["label"])
    check("[G] deliverables show one of two",
          progress["deliverables"]["label"] == "1 / 2",
          progress["deliverables"]["label"])
    check("[G] and the failed format is named rather than missing",
          progress["files"].get("pdf", {}).get("present") is False)
    if shoot:
        await _shoot(page, "chat-g-partial-failure")


# ==========================================================================
# H — the document tool fails outright
# ==========================================================================


async def journey_h(page, *, shoot: bool) -> None:
    workspace = await _new_workspace(page, "H — tool failure")
    await _open(page, workspace)
    await _send(page, "Write it and fail.")

    check("[H] the assistant explains the failure",
          await _settle(page, "could not produce that document", 150_000))
    said = await _said(page, workspace)
    check("[H] and says plainly that nothing was saved",
          "no file" in said.lower() or "not saved" in said.lower())

    state = await _state(page, workspace)
    check("[H] no document was written", state["artifacts"] == [])
    check("[H] the tool failure is recorded on the message",
          any(t["ok"] is False
              for t in state["messages"][-1]["content"].get("tools") or []))

    # The conversation is still usable afterwards.
    await _send(page, "What is the difference between a scorecard development "
                      "report and a scorecard validation report?")
    check("[H] and the conversation still works",
          await _settle(page, "challenges it independently"))
    if shoot:
        await _shoot(page, "chat-h-tool-failure")


# ==========================================================================
# I — the dashboard is down
# ==========================================================================


async def journey_i(page, *, shoot: bool) -> None:
    workspace = await _new_workspace(page, "I — dashboard failure")
    await _open(page, workspace)
    await _send(page, "Write it with the dashboard down.")

    check("[I] the answer arrives with the status panel broken",
          await _settle(page, "both files are ready to download", 150_000))

    state = await _state(page, workspace)
    check("[I] and the files are there", _formats(state) == ["docx", "pdf"],
          str(_formats(state)))

    [artifact] = state["artifacts"]
    [version] = artifact["versions"]
    for file in version["files"]:
        got = await page.evaluate(
            """async (id) => {
                const r = await fetch(
                    `/api/v1/playbook/artifact-files/${id}/download`);
                return r.ok ? (await r.blob()).size : 0;
            }""", file["id"])
        check(f"[I] the {file['format']} still downloads", int(got) > 500,
              f"{got} bytes")

    # Rebuilding the status costs nothing and calls no provider: the route is
    # a read, and asking for it again is how a stale panel catches up.
    again = await _progress(page, workspace)
    check("[I] the progress panel still answers rather than erroring",
          isinstance(again, dict) and "available" in again)
    if shoot:
        await _shoot(page, "chat-i-dashboard-down")


# ==========================================================================
# J — reopening
# ==========================================================================


async def journey_j(page, *, shoot: bool) -> None:
    workspace = await _new_workspace(page, "J — reopen")
    await _open(page, workspace)
    await _send(page, "Using these sources, create a detailed scorecard "
                      "development report in Word and PDF.")
    check("[J] the report is made", await _settle(page, "both files are ready",
                                                  150_000))

    # Away and back, the way a person would.
    await page.goto(f"{WEB}/playbook", wait_until="networkidle")
    await _open(page, workspace)

    check("[J] the messages are still there",
          await page.locator("article").count() >= 2)
    state = await _state(page, workspace)
    check("[J] the files are still there", _formats(state) == ["docx", "pdf"])
    check("[J] the versions are still there",
          len(state["artifacts"][0]["versions"]) == 1)

    await _send(page, "Give me a PDF of the latest Word report.")
    check("[J] and the conversation continues naturally",
          await _settle(page, "converted from the Word file", 150_000))
    if shoot:
        await _shoot(page, "chat-j-reopen")


# ==========================================================================
# K — an interrupted turn
# ==========================================================================


async def journey_k(page, *, shoot: bool) -> None:
    workspace = await _new_workspace(page, "K — interruption")
    await _open(page, workspace)

    # A first, complete turn, so there is a previous success to preserve.
    await _send(page, "Using these sources, create a detailed scorecard "
                      "development report in Word and PDF.")
    check("[K] a report exists before the interruption",
          await _settle(page, "both files are ready", 150_000))
    before = _formats(await _state(page, workspace))

    await _send(page, "Explain the movement.")
    check("[K] the partial text arrives",
          await _settle(page, "coverage ratio moved because"))

    state = await _state(page, workspace)
    last = state["messages"][-1]["content"]
    check("[K] and is marked incomplete", last.get("interrupted") is True,
          str(last.get("interrupted")))
    check("[K] no file is claimed for the interrupted turn",
          last.get("files") in ([], None), str(last.get("files")))
    check("[K] the earlier report is untouched",
          _formats(await _state(page, workspace)) == before, str(before))
    # The DOM, not only the stored flag. This check asserted `interrupted` on
    # the row and never that anybody could see it — and the thread had no
    # branch for it at all, so a turn cut short looked exactly like a
    # finished one for as long as the flag has existed.
    check("[K] and the thread says so, not only the row",
          "cut short" in await _answer(page))
    if shoot:
        await _shoot(page, "chat-k-interrupted")


# ==========================================================================
# L — the assistant promises a document and does not call the tool
# ==========================================================================


async def journey_l(page, *, shoot: bool) -> None:
    """The failure that reached a user, driven through the real interface.

    A live model answered "I'll draft the full committee report now. Before
    the tool call…" and called nothing. The turn was recorded as a complete
    success and the Files panel said "Nothing generated yet".
    """
    workspace = await _new_workspace(page, "L — a promise with no tool call")
    await _open(page, workspace)
    await _send(page, "Draft the report from the attached sources.")

    check("[L] the turn still ends with a document",
          await _settle(page, "both files are ready", 150_000))
    state = await _state(page, workspace)
    check("[L] the correction happened rather than the promise standing",
          state["messages"][-1]["content"].get("nudged") is True,
          str(state["messages"][-1]["content"].get("nudged")))
    check("[L] and the file is real", _formats(state) == ["docx", "pdf"],
          str(_formats(state)))
    check("[L] nothing is marked as having produced no file",
          state["messages"][-1]["content"].get("no_file") is not True)

    # And when it will not call at all, the interface says so rather than
    # showing an answer that reads like success beside an empty panel.
    stubborn = await _new_workspace(page, "L — it never calls")
    await _open(page, stubborn)
    await _send(page, "Draft it and never actually write it.")
    check("[L] a turn that never calls still answers",
          await _settle(page, "Drafting now", 150_000))
    state = await _state(page, stubborn)
    check("[L] no document was written", state["artifacts"] == [])
    check("[L] the turn is marked as having produced no file",
          state["messages"][-1]["content"].get("no_file") is True,
          str(state["messages"][-1]["content"].get("no_file")))
    check("[L] and the thread says so in words",
          "produced no file" in await _answer(page))
    if shoot:
        await _shoot(page, "chat-l-promise-no-file")


# ==========================================================================
# M — a second send while a generation is running
# ==========================================================================


async def journey_m(page, *, shoot: bool) -> None:
    """Four identical messages in one thread is what the absence of this
    looked like, and each one was a second paid generation."""
    workspace = await _new_workspace(page, "M — a second send")
    await _open(page, workspace)

    # Refused by the server, whatever the interface does. The interface is
    # checked below; this is the guarantee underneath it.
    started = await _api(
        page, f"/api/v1/playbook/workspaces/{workspace}/messages", "POST",
        {"text": "Write it slowly.", "stream": True,
         "idempotency_key": f"m:{workspace}:1"})
    check("[M] the first send starts a generation",
          started["status"] in (200, 201), str(started["status"]))

    again = await _api(
        page, f"/api/v1/playbook/workspaces/{workspace}/messages", "POST",
        {"text": "Write it slowly.", "stream": True,
         # A DIFFERENT key, exactly as the browser mints one: the client's key
         # is positional, so the same sentence sent again gets a new one.
         "idempotency_key": f"m:{workspace}:2"})
    body = again["body"] if isinstance(again["body"], dict) else {}
    check("[M] a second send with a new key is refused",
          body.get("duplicate") is True, str(body)[:160])
    check("[M] and is pointed at the generation already running",
          body.get("job_id") == (started["body"] or {}).get("job_id"),
          str(body.get("job_id")))

    # Reload before watching: this generation was started through the API
    # rather than the composer, so the page was never attached to its stream.
    # A refresh mid-generation is exactly what the product has to survive, so
    # it is the right way to wait for it here.
    await _open(page, workspace)
    check("[M] the first generation finishes normally",
          await _settle(page, "both files are ready", 150_000))
    state = await _state(page, workspace)
    asked = [m for m in state["messages"] if m["role"] == "user"]
    check("[M] the refused send left no second question",
          len(asked) == 1, f"{len(asked)} user message(s)")
    if shoot:
        await _shoot(page, "chat-m-second-send")


# ==========================================================================


async def run_once(browser, *, shoot: bool, methodology: bytes) -> None:
    context = await browser.new_context(viewport={"width": 1440, "height": 900})
    page = await context.new_page()
    await page.set_extra_http_headers({"X-IPM-Role": "ADMIN",
                                       "X-IPM-User-Id": "1"})
    await page.goto(f"{WEB}/playbook", wait_until="networkidle")

    print("\n-- The server is scripted " + "-" * 34)
    await the_server_is_scripted(page)
    print("\n-- A — an ordinary question " + "-" * 32)
    await journey_a(page, shoot=shoot)
    print("\n-- B — a question about an attachment " + "-" * 22)
    await journey_b(page, shoot=shoot, methodology=methodology)
    print("\n-- C–F — request, revise, present, convert " + "-" * 17)
    await journeys_c_to_f(page, shoot=shoot)
    print("\n-- G — one format fails " + "-" * 36)
    await journey_g(page, shoot=shoot)
    print("\n-- H — the document tool fails " + "-" * 29)
    await journey_h(page, shoot=shoot)
    print("\n-- I — the dashboard is down " + "-" * 31)
    await journey_i(page, shoot=shoot)
    print("\n-- J — reopening " + "-" * 43)
    await journey_j(page, shoot=shoot)
    print("\n-- K — an interrupted turn " + "-" * 33)
    await journey_k(page, shoot=shoot)
    print("\n-- L — a promise with no tool call " + "-" * 25)
    await journey_l(page, shoot=shoot)
    print("\n-- M — a second send while one is running " + "-" * 18)
    await journey_m(page, shoot=shoot)

    await context.close()


def _methodology_docx() -> str:
    """A real .docx, base64, built here so the run needs no fixture file."""
    import base64

    from docx import Document

    doc = Document()
    doc.add_heading("Scorecard methodology", level=1)
    doc.add_paragraph(
        "The target is ninety days past due observed within twelve months of "
        "origination. Exclusions are staff accounts and accounts closed within "
        "the observation window.")
    doc.add_heading("Sampling", level=2)
    doc.add_paragraph(
        "The development and holdout partitions are assigned at random, "
        "stratified by origination month.")
    buffer = io.BytesIO()
    doc.save(buffer)
    return base64.b64encode(buffer.getvalue()).decode()


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-screenshots", action="store_true")
    parser.add_argument("--repeat", type=int, default=1,
                        help="run the whole set this many times, to catch "
                             "state left behind between runs")
    args = parser.parse_args()

    from playwright.async_api import async_playwright

    executable = _chromium_path()
    if executable is None:
        print("CANNOT RUN: Chromium is not available at /opt/pw-browsers.")
        print("A run that did not happen is not a run that passed.")
        return 2

    methodology = _methodology_docx()
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=executable)
        try:
            for cycle in range(1, args.repeat + 1):
                if args.repeat > 1:
                    print(f"\n########## cycle {cycle} of {args.repeat} "
                          f"##########")
                await run_once(browser, methodology=methodology,
                               shoot=not args.no_screenshots and cycle == 1)
        finally:
            await browser.close()
            # Even if a journey raised: a run that leaves rows behind breaks
            # the next suite rather than its own. Reported here and nowhere
            # else — an earlier second call outside this block always printed
            # nought, because the list it counted had just been emptied.
            try:
                removed = _clean_up()
                print(f"\nCleaned up {removed} workspace(s) this run "
                      f"created.")
            except Exception as exc:  # noqa: BLE001 — reported, never fatal
                print(f"  note  could not clean up ({exc}); workspaces remain")

    print("\n" + "=" * 72)
    print(f"{len(ok)} passed, {len(bad)} failed. Evidence: "
          f"{EVIDENCE.relative_to(REPO)}")
    EVIDENCE.write_text(json.dumps(
        {"passed": ok, "failed": bad, "cycles": args.repeat,
         "note": "Journeys A-K driven against a scripted assistant; no "
                 "provider call was made. See backend/playbook/scripted.py."},
        indent=2) + "\n")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
