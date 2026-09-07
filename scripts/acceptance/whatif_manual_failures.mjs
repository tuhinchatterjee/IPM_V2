/**
 * The manual acceptance failures, reproduced in a browser.
 *
 *     node scripts/acceptance/whatif_manual_failures.mjs [--json]
 *
 * Every journey here exists because a person found it by hand. The automated
 * suite had passed; these are what it did not look at, and each one is written
 * to FAIL on the code as it was found rather than to confirm the fix. A
 * regression test that could not have caught the original defect is a test
 * about something else.
 *
 *   A  Rating migration percentages must be ROW shares — "of the borrowers
 *      who started on this grade", not "of the whole book".
 *   B  Back navigation exists on every What-If screen.
 *   C  Follow-up questions are answered, and answering one does not change
 *      the result it is about.
 *   D  The ML methodology is either runnable or refused in words, never a
 *      dynamic-linker path.
 *   E  The risk-parameter screens read as tables and distributions, never as
 *      raw JSON.
 *   F  Filters survive: "construction borrowers with exposure above SAR 100m"
 *      is not the whole book, and the screen restates what it understood.
 *   G  A Stage migration shows the measurement basis as its own driver, never
 *      a zero PD effect beside an opaque Stage effect of +243%.
 *
 * Playwright is resolved from the machine rather than from package.json: the
 * browser is a tool for checking this product, not a dependency of it. A
 * journey FAILS rather than skips when a precondition is missing.
 */

import { createRequire } from "node:module";

const require = createRequire(import.meta.url);

const PW = process.env.PLAYWRIGHT_MODULE
  ?? "/opt/node22/lib/node_modules/playwright/index.js";
const CHROME = process.env.PLAYWRIGHT_CHROMIUM
  ?? "/opt/pw-browsers/chromium-1194/chrome-linux/chrome";
const WEB = process.env.CREDITPROBE_WEB ?? "http://127.0.0.1:3000";
const API = process.env.CREDITPROBE_API ?? "http://127.0.0.1:8000";
const JSON_OUT = process.argv.includes("--json");

const results = [];
let browser;

function log(...parts) {
  if (!JSON_OUT) console.log(...parts);
}

async function journey(name, body) {
  const started = Date.now();
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const checks = [];
  const check = (label, ok, detail = "") => {
    checks.push({ label, ok: Boolean(ok), detail });
    log(`    ${ok ? "PASS" : "FAIL"}  ${label}${detail ? ` — ${detail}` : ""}`);
  };
  log(`\n== ${name}`);
  try {
    await body(page, check);
  } catch (error) {
    check("journey completed without throwing", false, String(error).slice(0, 240));
  } finally {
    await page.close();
  }
  const ok = checks.every((c) => c.ok);
  results.push({ name, ok, ms: Date.now() - started, checks });
  log(`  ${ok ? "JOURNEY PASSED" : "JOURNEY FAILED"} (${Date.now() - started}ms)`);
}

async function appears(page, selector, timeout = 45_000) {
  try {
    await page.waitForSelector(selector, { timeout, state: "visible" });
    return true;
  } catch {
    return false;
  }
}

async function say(page, text) {
  await page.fill('[data-testid="whatif-composer"]', text);
  await page.getByRole("button", { name: "Send" }).click();
}

async function chooseMethodology(page, check, method = "delta") {
  const gate = await appears(page, `button[data-methodology="${method}"]`, 90_000);
  check("the methodology gate is asked before any ECL figure", gate);
  if (!gate) return false;
  await page.click(`button[data-methodology="${method}"]`);
  const result = await appears(page, '[data-testid="whatif-result"]', 180_000);
  check("a result appears once the methodology is chosen", result);
  return result;
}

async function api(path) {
  const response = await fetch(`${API}${path}`,
    { headers: { "X-IPM-Role": "ANALYST" } });
  return { status: response.status, body: await response.json() };
}

async function warm() {
  for (const path of ["/api/v1/whatif/staging", "/api/v1/whatif/periods",
                      "/api/v1/whatif/profile/rating",
                      "/api/v1/whatif/migration/rating",
                      "/api/v1/whatif/profile/parameter/pd",
                      "/api/v1/whatif/models/ml"]) {
    try { await fetch(`${API}${path}`, { headers: { "X-IPM-Role": "ANALYST" } }); }
    catch { /* the journeys will say so */ }
  }
}

async function main() {
  const { chromium } = require(PW);
  await warm();
  browser = await chromium.launch({ executablePath: CHROME });

  /* ------------------------------------------------------------------- A */
  await journey("A — Rating migration percentages are ROW shares", async (page, check) => {
    const { body } = await api("/api/v1/whatif/migration/rating");
    check("the matrix declares its normalisation", body.normalisation === "row",
      String(body.normalisation));
    check("and says how to read a cell",
      /started the period/i.test(String(body.reads_as ?? "")),
      String(body.reads_as));
    check("and names the denominator explicitly",
      /own total/i.test(String(body.denominator ?? "")), String(body.denominator));
    check("the displayed shape is 20 x 20 on the nineteen governed grades",
      body.displayed_shape === "20 x 20", String(body.displayed_shape));

    // A row that holds borrowers must sum to 100% of ITSELF. Grand-total
    // shares were what made every cell look like rounding: the diagonal of a
    // 20 x 20 matrix over three thousand names reads as 4% either way.
    const shares = body.views?.count_pct;
    check("a percentage view is published", Boolean(shares));
    const populated = (shares?.rows ?? [])
      .filter((r) => r.label !== "Total" && (r.total ?? 0) > 0);
    check("some origin grades hold borrowers", populated.length > 5,
      `${populated.length} populated rows`);
    const offBy = populated
      .map((r) => ({
        label: r.label,
        gap: Math.abs((r.cells ?? []).reduce((a, c) => a + (c ?? 0), 0) - 100),
      }))
      .filter((r) => r.gap > 0.5);
    check("every populated row sums to 100% of its own origin grade",
      offBy.length === 0,
      offBy.map((r) => `${r.label} off by ${r.gap.toFixed(2)}pp`).join("; "));
    check("the grand total is not what the cells are shares of",
      Math.abs((shares?.grand_total ?? 0) - 100) < 0.001
      && populated.length > 1,
      `grand_total ${shares?.grand_total}`);

    await page.goto(`${WEB}/what-if/thread?journey=rating`, { waitUntil: "networkidle" });
    check("the matrix renders", await appears(page, '[data-testid="migration-matrix"]', 90_000));
    await page.click('[data-view="count_pct"]').catch(() => {});
    await page.waitForTimeout(600);
    const legend = await page.textContent('[data-testid="migration-legend"]')
      .catch(() => "");
    check("the screen says what the percentages are OF",
      /started the period/i.test(legend ?? ""), (legend ?? "").slice(0, 140));
  });

  /* ------------------------------------------------------------------- B */
  await journey("B — Back navigation exists on every What-If screen", async (page, check) => {
    for (const [where, path] of [
      ["the thread", "/what-if/thread?journey=rating"],
      ["the Delta model page", "/what-if/models/delta"],
      ["the ML model page", "/what-if/models/ml"],
    ]) {
      await page.goto(`${WEB}${path}`, { waitUntil: "networkidle" });
      // The BACK control specifically, not the sidebar entry of the same
      // name: a person who wants out of a thread reaches for the one at the
      // top of the page, and asserting on whichever link matched first is how
      // a missing Back passes.
      const back = page.locator('main [data-testid="back-link"]').first();
      const there = await back.count() > 0;
      check(`${where} offers a Back control`, there);
      if (!there) continue;
      check(`${where} Back points at the What-If index`,
        (await back.getAttribute("data-back-to")) === "/what-if");
      await Promise.all([
        page.waitForURL(/\/what-if\/?($|\?)/, { timeout: 30_000 }).catch(() => {}),
        back.click(),
      ]);
      check(`${where} Back returns to the What-If index`,
        page.url().replace(/\/$/, "").endsWith("/what-if"), page.url());
    }
  });

  /* ------------------------------------------------------------------- C */
  await journey("C — Follow-up questions are answered, and change nothing",
    async (page, check) => {
      await page.goto(`${WEB}/what-if/thread?journey=rating`, { waitUntil: "networkidle" });
      await appears(page, '[data-testid="whatif-composer"]', 90_000);
      await say(page, "Downgrade everyone one notch.");
      if (!(await chooseMethodology(page, check))) return;

      const results = page.locator('[data-testid="whatif-result"]');
      const before = await results.count();
      const headline = await results.nth(before - 1)
        .locator('[data-testid="whatif-ecl"]').first().textContent();

      for (const question of [
        "Why did the ECL increase?",
        "Which borrowers contributed most?",
        "Show this by sector.",
        "Why did Stage 3 ECL increase?",
        "How much of this is the measurement basis changing?",
      ]) {
        await say(page, question);
        const answered = await appears(page, '[data-testid="whatif-answer"]', 120_000);
        check(`"${question}" is answered`, answered);
        if (!answered) continue;
        const answer = page.locator('[data-testid="whatif-answer"]').last();
        const text = (await answer.textContent()) ?? "";
        check(`"${question}" says the scenario is unchanged`,
          /unchanged/i.test(text));
        check(`"${question}" is not answered with a stack trace`,
          !/Traceback|at Object\.|\.py"/.test(text));
      }

      check("no new ECL result was produced by asking questions",
        (await results.count()) === before, `${await results.count()} vs ${before}`);
      const after = await results.nth(before - 1)
        .locator('[data-testid="whatif-ecl"]').first().textContent();
      check("and the figure being asked about did not move", after === headline,
        `${headline} -> ${after}`);
    });

  /* ------------------------------------------------------------------- D */
  await journey("D — The ML methodology is runnable or refused in words",
    async (page, check) => {
      const { body } = await api("/api/v1/whatif/models/ml");
      const env = body.environment ?? {};
      check("the model page reports the runtime it needs",
        typeof env.available === "boolean", JSON.stringify(env).slice(0, 120));
      check("with a message a person can act on", Boolean(env.message));
      check("and never a dynamic-linker path",
        !/@rpath|dlopen|libomp\.dylib/.test(env.message ?? ""));
      if (!env.available) {
        check("a refusal names the command that fixes it", Boolean(env.command));
        check("and names the Delta Model as the way to keep working",
          /Delta Model/.test(env.message ?? ""));
      }

      await page.goto(`${WEB}/what-if/models/ml`, { waitUntil: "networkidle" });
      const shown = (await page.content());
      check("the screen shows no traceback", !/Traceback \(most recent/.test(shown));
      check("and no raw linker error", !/@rpath/.test(shown));

      const gate = await api("/api/v1/whatif/methodology");
      const ml = (gate.body.options ?? []).find((o) => o.value === "ml");
      check("the gate lists the ML option", Boolean(ml));
      if (ml && !ml.available) {
        check("an unavailable ML option says why in the gate itself",
          Boolean(ml.unavailable_because), ml.unavailable_because);
      }
    });

  /* ------------------------------------------------------------------- E */
  await journey("E — The risk-parameter screens are read, not dumped",
    async (page, check) => {
      await page.goto(`${WEB}/what-if/thread?journey=parameters`,
        { waitUntil: "networkidle" });
      check("the PD screen opens", await appears(page, "table", 90_000));
      const body = (await page.textContent("main")) ?? "";
      check("no raw JSON on screen",
        !/"period"\s*:|"parameter"\s*:|\{\s*"/.test(body),
        body.slice(0, 160));
      check("the measurement basis per Stage is stated",
        /measured on/i.test(body));
      check("a distribution is shown rather than implied",
        /Exposure-weighted|Median/i.test(body));

      for (const parameter of ["lgd", "ccf"]) {
        await page.click(`[data-tab="${parameter}"]`).catch(() => {});
        await page.getByRole("button", { name: parameter.toUpperCase() })
          .click().catch(() => {});
        await page.waitForTimeout(1500);
        const shown = (await page.textContent("main")) ?? "";
        check(`the ${parameter.toUpperCase()} screen shows no raw JSON`,
          !/"period"\s*:|\{\s*"/.test(shown));
      }
    });

  /* ------------------------------------------------------------------- F */
  await journey("F — A stated filter survives into the population",
    async (page, check) => {
      await page.goto(`${WEB}/what-if/thread?journey=rating`, { waitUntil: "networkidle" });
      await appears(page, '[data-testid="whatif-composer"]', 90_000);
      const said = "Downgrade construction borrowers with exposure above SAR 100m by two notches.";
      await say(page, said);

      const restated = await appears(page, "text=What I understood", 60_000);
      check("the screen restates what it understood before calculating", restated);
      const conversation = (await page.textContent("main")) ?? "";
      check("and names the sector filter", /Contracting/i.test(conversation));
      check("and names the exposure filter",
        /Exposure at default above SAR 100/i.test(conversation), "");

      if (!(await chooseMethodology(page, check))) return;
      const context = await page.locator('[data-testid="whatif-population"]')
        .last().textContent().catch(() => "");
      check("the result is not priced on the whole book",
        !/whole corporate book/i.test(context ?? ""), (context ?? "").slice(0, 140));

      const counted = (context ?? "").match(/([\d,]+)\s+borrower/i);
      const population = counted ? Number(counted[1].replace(/,/g, "")) : 0;
      check("the population is a fraction of the book, not all of it",
        population > 0 && population < 2000, String(population));
    });

  /* ------------------------------------------------------------------- G */
  await journey("G — A Stage migration names the measurement basis",
    async (page, check) => {
      await page.goto(`${WEB}/what-if/thread?journey=stage`, { waitUntil: "networkidle" });
      await appears(page, '[data-testid="whatif-composer"]', 90_000);
      await say(page,
        "Move 50% of Stage 1 clients in Transport & Logistics to Stage 2.");
      if (!(await chooseMethodology(page, check))) return;

      const attribution = page.locator('[data-testid="whatif-attribution"]').last();
      const there = await attribution.count() > 0;
      check("the movement is attributed to drivers", there);
      if (!there) return;
      const text = (await attribution.textContent()) ?? "";
      check("the measurement basis is a driver of its own",
        /Measurement basis/i.test(text), text.slice(0, 200));
      check("it is not collapsed into an opaque Stage effect",
        !/Stage effect/i.test(text));

      await say(page, "How much of this is the measurement basis changing?");
      const answered = await appears(page, '[data-testid="whatif-answer"]', 120_000);
      check("and the question about it is answered", answered);
      if (answered) {
        const answer = (await page.locator('[data-testid="whatif-answer"]')
          .last().textContent()) ?? "";
        check("in the terms a lender uses, not as a bare percentage",
          /lifetime/i.test(answer), answer.slice(0, 200));
      }
    });

  /* ------------------------------------------------------------------- H */
  await journey("H — The gate is confirmed and the result is READ, not only shown",
    async (page, check) => {
      await page.goto(`${WEB}/what-if/thread?journey=parameters`,
        { waitUntil: "networkidle" });
      await appears(page, '[data-testid="whatif-composer"]', 90_000);
      await say(page, "Increase Stage 1 PD by 20%.");

      // The gate is a QUESTION, and nothing is priced while it is open.
      const gate = await appears(page, 'button[data-methodology="delta"]', 90_000);
      check("the methodology gate is asked before any ECL figure", gate);
      if (!gate) return;
      check("and no result is on screen while it is open",
        (await page.locator('[data-testid="whatif-result"]').count()) === 0);
      await page.click('button[data-methodology="delta"]');
      const ran = await appears(page, '[data-testid="whatif-result"]', 180_000);
      check("a result appears once the methodology is chosen", ran);
      if (!ran) return;

      const result = page.locator('[data-testid="whatif-result"]').last();
      const shown = (await result.textContent()) ?? "";
      check("the choice is confirmed in words, not only recorded",
        /Delta Model/i.test(shown));

      // §32: a number with no reading is where a scenario tool stops being
      // useful. Somebody has to say whether this matters.
      const reading = result.locator('text=What this means');
      check("the result carries a reading of what it MEANS",
        (await reading.count()) > 0);
      const followups = await result.locator("[data-followup]").count();
      check("with follow-up questions offered as buttons", followups >= 3,
        `${followups}`);

      // And the buttons work: clicking one asks it and is answered.
      if (followups > 0) {
        await result.locator("[data-followup]").first().click();
        check("a suggested question is answered when clicked",
          await appears(page, '[data-testid="whatif-answer"]', 120_000));
      }
    });

  await browser.close();

  const passed = results.filter((r) => r.ok).length;
  const checks = results.flatMap((r) => r.checks);
  const summary = {
    journeys: results.length,
    passed,
    failed: results.length - passed,
    checks: checks.length,
    checks_passed: checks.filter((c) => c.ok).length,
    web: WEB, api: API, results,
  };
  if (JSON_OUT) {
    console.log(JSON.stringify(summary, null, 2));
  } else {
    log(`\n${"=".repeat(64)}`);
    log(`${passed}/${results.length} journeys passed · ` +
        `${summary.checks_passed}/${summary.checks} checks passed`);
    for (const r of results) {
      if (!r.ok) {
        log(`  FAILED ${r.name}`);
        for (const c of r.checks.filter((c) => !c.ok)) {
          log(`    - ${c.label}${c.detail ? ` (${c.detail})` : ""}`);
        }
      }
    }
  }
  process.exit(passed === results.length ? 0 : 1);
}

main().catch(async (error) => {
  console.error("The journey suite could not run:", error);
  if (browser) await browser.close();
  process.exit(2);
});
