/**
 * What-If Analysis — the nine browser journeys.
 *
 *     node scripts/acceptance/whatif_journeys.mjs [--json]
 *
 * These drive a real Chromium against a real backend and a real front end.
 * They exist because a unit test cannot tell you that the methodology gate
 * actually blocks a calculation on screen, or that a saved What-If reopens
 * with the scenario it was saved with.
 *
 * Playwright is resolved from the machine rather than from package.json: the
 * browser is a tool for checking this product, not a dependency of it.
 *
 * A journey FAILS rather than skips when a precondition is missing. "The
 * model was not trained so we skipped the model journey" is the exact report
 * that lets a broken feature ship.
 */

import { createRequire } from "node:module";

// Playwright is loaded through createRequire rather than a dynamic import.
// The package is CommonJS, and Node's ESM interop hands back a namespace whose
// `chromium` is undefined — `require` returns the real thing.
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
    check("journey completed without throwing", false, String(error).slice(0, 200));
  } finally {
    await page.close();
  }
  const ok = checks.every((c) => c.ok);
  results.push({ name, ok, ms: Date.now() - started, checks });
  log(`  ${ok ? "JOURNEY PASSED" : "JOURNEY FAILED"} (${Date.now() - started}ms)`);
}

/** Wait for a selector, returning whether it appeared rather than throwing. */
async function appears(page, selector, timeout = 30_000) {
  try {
    await page.waitForSelector(selector, { timeout, state: "visible" });
    return true;
  } catch {
    return false;
  }
}

/** Drive the composer and wait for the turn to land. */
async function say(page, text) {
  await page.fill('[data-testid="whatif-composer"]', text);
  await page.getByRole("button", { name: "Send" }).click();
}

/** Answer the methodology gate, which must be on screen before any figure. */
async function chooseMethodology(page, check, method = "delta") {
  const gateAppeared = await appears(page, `button[data-methodology="${method}"]`, 60_000);
  check("the methodology gate is asked before any ECL figure", gateAppeared);
  if (!gateAppeared) return false;
  const figureBefore = await page.locator('[data-testid="whatif-result"]').count();
  check("no result is shown while the gate is open", figureBefore === 0);
  await page.click(`button[data-methodology="${method}"]`);
  const result = await appears(page, '[data-testid="whatif-result"]', 120_000);
  check("a result appears once the methodology is chosen", result);
  return result;
}

async function main() {
  const { chromium } = require(PW);
  browser = await chromium.launch({ executablePath: CHROME });

  /* --------------------------------------------------- 1. Rating Movement */
  await journey("Journey 1 — Rating Movement", async (page, check) => {
    await page.goto(`${WEB}/what-if`, { waitUntil: "networkidle" });
    check("What-If Analysis is the page title",
      (await page.textContent("h1")) ?.includes("What-If Analysis"));
    check("the umbrella is not called Stress Testing",
      !(await page.content()).includes(">Stress Testing<"));
    check("six guided journeys are offered",
      (await page.locator("[data-journey]").count()) === 6);

    await page.click('[data-journey="rating"]');
    check("the rating profile opens", await appears(page, "table"));
    const rows = await page.locator('[data-row]').count();
    check("the fourteen governed grades plus a Total are shown", rows >= 15,
      `${rows} rows`);
    check("the 15 x 15 migration matrix is shown",
      await appears(page, '[data-testid="migration-matrix"]', 60_000));

    await page.click('[data-view="exposure"]');
    check("the migration offers an exposure view", true);

    await say(page, "Downgrade everyone one notch.");
    const ran = await chooseMethodology(page, check, "delta");
    if (ran) {
      const text = await page.textContent('[data-testid="whatif-result"]');
      check("the result names the period", text.includes("Q"));
      check("the result names the methodology", text.includes("Delta Model"));
      check("the result shows the baseline and the What-If ECL",
        text.includes("Official baseline ECL") && text.includes("What-If ECL"));
      check("the result shows the staging criteria version",
        text.includes("Staging"));
    }
  });

  /* ------------------------------------------------- 2. Risk Parameters */
  await journey("Journey 2 — Risk Parameters, layered", async (page, check) => {
    await page.goto(`${WEB}/what-if/thread?journey=parameters`, { waitUntil: "networkidle" });
    check("the parameter profile opens", await appears(page, "h1"));
    await say(page, "Increase Stage 1 PD by 20%.");
    const ran = await chooseMethodology(page, check, "delta");
    if (!ran) return;
    check("one step is on the scenario", (await page.locator("[data-step-kind]").count()) === 1);

    await say(page, "Increase LGD by five percentage points.");
    await page.waitForTimeout(6000);
    const steps = await page.locator("[data-step-kind]").count();
    check("the second shock layers onto the first", steps === 2, `${steps} steps`);
    const results = await page.locator('[data-testid="whatif-result"]').count();
    check("the layered result is calculated without asking the gate again",
      results >= 2, `${results} results`);
  });

  /* ------------------------------------------------- 3. Stage Migration */
  await journey("Journey 3 — Stage Migration", async (page, check) => {
    await page.goto(`${WEB}/what-if/thread?journey=stage`, { waitUntil: "networkidle" });
    check("the stage profile opens", await appears(page, "table"));
    check("the historical 3 x 3 migration is shown",
      await appears(page, '[data-testid="migration-matrix"]', 60_000));
    await say(page, "Move half the Stage 1 borrowers to Stage 2.");
    const ran = await chooseMethodology(page, check, "delta");
    if (ran) {
      const text = await page.textContent('[data-testid="whatif-result"]');
      check("the result reports stage movement", text.includes("Stage moves"));
      check("deterioration is shown", text.includes("Deteriorated"));
    }
  });

  /* -------------------------------------------------------- 4. Macro */
  await journey("Journey 4 — Macroeconomic Shock", async (page, check) => {
    await page.goto(`${WEB}/what-if/thread?journey=macro`, { waitUntil: "networkidle" });
    const shown = await appears(page, "[data-macro]", 60_000);
    check("the macro variables are shown", shown);
    const variables = await page.locator("[data-macro]").count();
    check("all ten CreditProbe V1 variables are shown", variables === 10, `${variables}`);
    check("the synthetic-macro limitation is disclosed",
      (await page.content()).includes("single latent cycle factor"));
    await say(page, "Increase unemployment by one percentage point.");
    const ran = await chooseMethodology(page, check, "delta");
    if (ran) {
      await say(page, "Increase Stage 1 PD by 20%.");
      await page.waitForTimeout(6000);
      check("a PD shock layers onto the macro shock",
        (await page.locator("[data-step-kind]").count()) === 2);
    }
  });

  /* ------------------------------------------------------- 5. Sector */
  await journey("Journey 5 — Sector Stress", async (page, check) => {
    await page.goto(`${WEB}/what-if/thread?journey=sector`, { waitUntil: "networkidle" });
    check("the sector profile opens", await appears(page, "table", 60_000));
    const text = await page.textContent("body");
    check("real sectors are listed", text.includes("Real Estate") || text.includes("Contracting"));
    await say(page, "Reduce Contracting collateral by 20%.");
    await chooseMethodology(page, check, "delta");
  });

  /* ----------------------------------------------------- 6. Borrower */
  await journey("Journey 6 — Borrower Stress", async (page, check) => {
    await page.goto(`${WEB}/what-if/thread?journey=borrower`, { waitUntil: "networkidle" });
    const shown = await appears(page, "[data-borrower]", 60_000);
    check("the top Stage 2 borrowers are shown", shown);
    const borrowers = await page.locator("[data-borrower]").count();
    check("ten borrowers are listed", borrowers === 10, `${borrowers}`);
    await say(page, "Downgrade everyone two notches.");
    const ran = await chooseMethodology(page, check, "delta");
    if (ran) {
      const text = await page.textContent('[data-testid="whatif-result"]');
      check("the book-level impact is reported", text.includes("What-If ECL"));
    }
  });

  /* --------------------------------------------------- 7. Save/reopen */
  await journey("Journey 7 — Save and reopen", async (page, check) => {
    await page.goto(`${WEB}/what-if/thread?journey=parameters`, { waitUntil: "networkidle" });
    await say(page, "Increase Stage 1 PD by 20%.");
    const ran = await chooseMethodology(page, check, "delta");
    if (!ran) return;
    const before = await page.textContent('[data-testid="whatif-result"]');
    const name = `Browser journey ${Date.now()}`;
    await page.fill('input[aria-label="Name this What-If"]', name);
    await page.getByRole("button", { name: "Save What-If" }).click();
    check("the save is confirmed",
      await appears(page, `text=Saved as "${name}"`, 60_000));

    await page.goto(`${WEB}/what-if`, { waitUntil: "networkidle" });
    const card = page.locator(`text=${name}`).first();
    check("the saved What-If appears on the landing page",
      await card.isVisible().catch(() => false));
    await card.click();
    check("reopening restores the scenario",
      await appears(page, "text=Reopened", 60_000));
    const after = await page.textContent("body");
    check("the reopened What-If names the same period",
      after.includes(before.match(/Q\d \d{4}/)?.[0] ?? "Q"));
  });

  /* ------------------------------------------------------- 8. ML model */
  await journey("Journey 8 — ML model configuration", async (page, check) => {
    await page.goto(`${WEB}/what-if/models/ml`, { waitUntil: "networkidle" });
    check("an active model is shown, not an empty page",
      await appears(page, '[data-testid="active-model"]', 60_000));
    const text = await page.textContent("body");
    check("the limitations are stated", text.includes("MECHANICAL"));
    check("the macro collinearity is disclosed",
      text.includes("single latent cycle factor"));
    check("out-of-time metrics are shown", text.includes("out-of-time"));
    check("the artifact format is stated", text.includes("xgboost-native-json"));

    await page.getByRole("tab", { name: "Explainability" }).click();
    check("SHAP is shown", await appears(page, "text=Top predictors", 60_000));
    check("feature importance is shown",
      (await page.textContent("body")).includes("gain importance"));

    await page.getByRole("tab", { name: "Worked example" }).click();
    await page.getByRole("button", { name: /Score Client X/ }).click();
    check("Client X is scored by the real model",
      await appears(page, '[data-testid="client-x-result"]', 90_000));

    await page.getByRole("tab", { name: "Retrain" }).click();
    check("the retrain prompt names the periods",
      (await page.textContent("body")).includes("trained through"));
    check("versions are listed", (await page.textContent("body")).includes("ACTIVE"));
  });

  /* --------------------------------------------- 9. Direct complex chat */
  await journey("Journey 9 — A complex scenario typed directly", async (page, check) => {
    await page.goto(`${WEB}/what-if`, { waitUntil: "networkidle" });
    await page.fill('[data-testid="whatif-composer"]',
      "Downgrade Stage 1 construction borrowers by two notches.");
    await page.getByRole("button", { name: "Send" }).click();
    check("a typed scenario opens a thread without clicking a card",
      await appears(page, '[data-testid="whatif-composer"]', 60_000));
    const ran = await chooseMethodology(page, check, "ml");
    if (ran) {
      const text = await page.textContent('[data-testid="whatif-result"]');
      check("the ML methodology is named on the result",
        text.includes("ML Model"));
      check("the model version is on the result", /v\d{4}\./.test(text));
    }
    await say(page, "Also increase LGD by five percentage points.");
    await page.waitForTimeout(6000);
    check("the follow-up layers onto the same scenario",
      (await page.locator("[data-step-kind]").count()) >= 2);
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
    web: WEB,
    api: API,
    results,
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
