"""§57's mandatory browser acceptance, run against the live stack."""
import asyncio
import pathlib
import sys

from playwright.async_api import async_playwright

DOWN = pathlib.Path("/tmp/accept")
DOWN.mkdir(exist_ok=True)
SHOTS = pathlib.Path("/tmp/shots")
SHOTS.mkdir(exist_ok=True)
Q = "Show IFRS 9 EAD by internal rating for the latest period."
ok, bad = [], []

def check(name, condition, detail=""):
    (ok if condition else bad).append(f"{name}{(' — ' + detail) if detail else ''}")
    print(("  PASS  " if condition else "  FAIL  ") + name + (f"  {detail}" if detail else ""))

async def main():
    async with async_playwright() as pw:
        b = await pw.chromium.launch(args=["--no-sandbox"],
            executable_path="/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
        ctx = await b.new_context(viewport={"width":1500,"height":1050}, accept_downloads=True)
        page = await ctx.new_page()
        errs = []
        page.on("console", lambda m: errs.append(m.text) if m.type=="error" else None)
        page.on("pageerror", lambda e: errs.append(str(e)))

        # 1. Run the mandatory question.
        await page.goto("http://127.0.0.1:3000/", wait_until="networkidle")
        box = page.get_by_role("textbox").first
        await box.fill(Q)
        await box.press("Enter")
        await page.wait_for_timeout(18000)
        await page.screenshot(path=str(SHOTS/"A1-answer.png"), full_page=True)

        # 2. DOWNLOAD RESULTS in the analysis header, top right.
        btn = page.get_by_test_id("download-results").first
        check("2. DOWNLOAD RESULTS present", await btn.count() > 0 and await btn.is_visible())
        rect = await btn.bounding_box()
        width = await page.evaluate("document.body.clientWidth")
        check("2. it is in the right half of the header", rect and rect["x"] > width/2,
              f"x={rect and round(rect['x'])} of {width}")
        check("2. it is labelled", (await btn.get_attribute("aria-label")) == "DOWNLOAD RESULTS")

        # 3. Download it.
        async with page.expect_download(timeout=120000) as dl:
            await btn.click()
        d = await dl.value
        results_path = DOWN / d.suggested_filename
        await d.save_as(str(results_path))
        check("3. results workbook downloaded", results_path.stat().st_size > 0,
              f"{d.suggested_filename} {results_path.stat().st_size} bytes")

        # Read the on-screen FIGURES. The answer opens as a chart for this
        # shape, so switch to the table first — that is the view whose numbers
        # the workbook must match cell for cell.
        table_toggle = page.get_by_role("button", name="Table").first
        if await table_toggle.count():
            await table_toggle.click()
            await page.wait_for_timeout(1200)
        await page.screenshot(path=str(SHOTS/"A1b-table.png"), full_page=True)
        screen = await page.evaluate("""() => {
            const surface = document.querySelector('[data-testid="chart-surface"]');
            const t = (surface ?? document).querySelector('table');
            if (!t) return null;
            return [...t.querySelectorAll('tr')].map(r =>
              [...r.querySelectorAll('th,td')].map(c => c.innerText.trim()));
        }""")

        # 5/6. Trace, and the pack button in every mode.
        # The answer's own Trace link, not the navigation entry beside it.
        href = await page.locator('a[href^="/trace/"]').first.get_attribute("href")
        await page.goto("http://127.0.0.1:3000" + href, wait_until="networkidle")
        await page.wait_for_timeout(6000)
        pack_btn = page.get_by_test_id("download-calculation").first
        check("6. DOWNLOAD FULL CALCULATION present", await pack_btn.count() > 0)
        check("6. it is labelled", (await pack_btn.get_attribute("aria-label")) == "DOWNLOAD FULL CALCULATION")
        base = page.url.split("?")[0]
        for mode in ("story", "lineage", "landscape", "audit"):
            await page.goto(f"{base}?mode={mode}", wait_until="networkidle")
            await page.wait_for_timeout(2500)
            present = await page.get_by_test_id("download-calculation").count() > 0
            check(f"5. present in Trace {mode}", present)

        # 7. Download the pack.
        await page.goto(f"{base}?mode=story", wait_until="networkidle")
        await page.wait_for_timeout(3000)
        async with page.expect_download(timeout=180000) as dl:
            await page.get_by_test_id("download-calculation").first.click()
        d = await dl.value
        pack_path = DOWN / d.suggested_filename
        await d.save_as(str(pack_path))
        check("7. calculation pack downloaded", pack_path.stat().st_size > 0,
              f"{d.suggested_filename} {pack_path.stat().st_size} bytes")
        await page.screenshot(path=str(SHOTS/"A2-trace.png"), full_page=True)

        check("10. no console errors", len([e for e in errs if "favicon" not in e]) == 0,
              str([e for e in errs if "favicon" not in e][:2]))
        await b.close()

    # Report to a file the workbook checker reads.
    (DOWN / "screen.json").write_text(__import__("json").dumps(screen))
    (DOWN / "paths.txt").write_text(f"{results_path}\n{pack_path}\n")
    print(f"\nbrowser: {len(ok)} passed, {len(bad)} failed")
    if bad:
        print("FAILED:", bad)
        sys.exit(1)

asyncio.run(main())
