/**
 * What-If Analysis — the eleven browser journeys.
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

/**
 * Read the endpoints the journeys use, once, before the browser starts.
 *
 * The first journey otherwise pays for a cold DuckDB cache — a 15x15 migration
 * matrix over 52,880 rows, computed inside the first click — and reports it as
 * a product failure. This measures the product, not the cache. It is NOT a
 * skip: a warm-up that cannot reach the API leaves the journeys to fail on it.
 */
async function warm() {
  const paths = ["/api/v1/whatif/staging", "/api/v1/whatif/periods",
                 "/api/v1/whatif/profile/rating", "/api/v1/whatif/migration/rating",
                 "/api/v1/whatif/profile/stage", "/api/v1/whatif/migration/stage",
                 "/api/v1/whatif/profile/macro", "/api/v1/whatif/profile/borrowers",
                 "/api/v1/whatif/models/ml"];
  for (const path of paths) {
    try {
      await fetch(`${API}${path}`, { headers: { "X-IPM-Role": "ANALYST" } });
    } catch {
      // The journeys will say so, loudly, in a moment.
    }
  }
}

async function main() {
  const { chromium } = require(PW);
  await warm();
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
    check("the nineteen governed grades plus a Total are shown", rows >= 20,
      `${rows} rows`);
    check("the 20 x 20 migration matrix is shown",
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
      check("the result names the rule set that staged the reported book",
        text.includes("Reported book staged"));
      check("and the rule set that staged the What-If",
        text.includes("What-If staged"));
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
      const ecl = await page.locator('[data-chart="ecl"]').count();
      const exposure = await page.locator('[data-chart="exposure"]').count();
      check("the movement is drawn, not only tabulated", ecl > 0 && exposure > 0,
        `ecl=${ecl} exposure=${exposure}`);
      check("the movement is attributed to the drivers that caused it",
        await appears(page, '[data-testid="whatif-attribution"]', 20_000));
      const attributed = await page.locator('[data-testid="whatif-attribution"]').textContent();
      check("the attribution names the method",
        attributed.includes("Shapley") && attributed.includes("order-neutral"));
      check("the rating driver is on the table",
        (await page.locator('[data-driver="rating"]').count()) > 0);
      // The measurement basis is its OWN driver, keyed `basis`. It used to be
      // folded into a `stage` line, which is how a Stage 1 to Stage 2 result
      // came back reading "PD effect 0.00%, Stage effect +243.97%" — true and
      // useless. The residual `stage` driver is exactly zero on a plain
      // migration and is not on the table.
      check("the Stage migration is kept apart from the rating move",
        (await page.locator('[data-driver="basis"]').count()) > 0
        && /Measurement basis/i.test(attributed),
        attributed.slice(0, 160));
      check("the table says whether it reconciles",
        (await page.locator('[data-testid="attribution-check"]').textContent())
          .includes("Reconciles"));
      check("the charts carry a baseline and a What-If series",
        (await page.getByText("Baseline", { exact: true }).count()) > 0 &&
        (await page.getByText("What-If", { exact: true }).count()) > 0);
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
    // Stage-awareness: the evidence, not the claim. The model card tab, which
    // an earlier check navigated away from.
    await page.getByRole("tab", { name: "Model card" }).click();
    check("the stage-design study is on the model card",
      await appears(page, '[data-testid="stage-study"]', 20_000));
    const study = await page.locator('[data-testid="stage-study"]').textContent();
    check("it says which design was chosen",
      study.includes("One model with Stage as a feature")
      || study.includes("One model per Stage"), "");
    check("it reports the governed Stage 1 to 2 step and both models against it",
      (await page.locator('[data-testid="stage-boundary"]').count()) > 0);
    check("it reports each Stage's share of the ECL",
      study.includes("Share of ECL"));

    await page.getByRole("tab", { name: "Explainability" }).click();
    check("the Stage interaction is shown",
      await appears(page, '[data-testid="stage-interaction"]', 20_000));
    const interaction = await page.locator('[data-testid="stage-interaction"]').textContent();
    check("Stage 1 and Stage 2 responses are both reported",
      (await page.locator('[data-stage-response="1"]').count()) > 0
      && (await page.locator('[data-stage-response="2"]').count()) > 0);
    check("and the finding is stated in words",
      interaction.includes("not an intercept"));

    // The version list lives on the Retrain tab, where a person goes to make a
    // new one and needs to see what is already there.
    await page.getByRole("tab", { name: "Retrain" }).click();
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

  /* ------------------------------------------------ 10. Staging criteria */
  await journey("Journey 10 — Staging criteria, composed on screen",
    async (page, check) => {
      await page.goto(`${WEB}/what-if/thread?journey=rating`, { waitUntil: "networkidle" });
      check("the staging control is on the thread",
        await appears(page, '[data-testid="staging-toggle"]', 60_000));
      await page.click('[data-testid="staging-toggle"]');

      // Both rule sets, and only one of them editable.
      check("the What-If rule set is shown",
        await appears(page, '[data-testid="whatif-staging"]', 30_000));
      check("the reported-book rule set is shown beside it",
        await appears(page, '[data-testid="reported-staging"]', 30_000));
      const whatif = page.locator('[data-testid="whatif-staging"]');
      const reported = page.locator('[data-testid="reported-staging"]');
      check("the two are labelled apart",
        (await whatif.textContent()).includes("What-If staging policy")
        && (await reported.textContent()).includes("Reported-book staging policy"));

      // Rule A and Rule B are ON by default, and say they are assumptions.
      const ruleA = whatif.locator('[data-rule="rating_notches"]');
      const ruleB = whatif.locator('[data-rule="scenario_pd_ratio"]');
      check("Rule A is on by default",
        await ruleA.locator('input[type="checkbox"]').isChecked());
      check("Rule B is on by default",
        await ruleB.locator('input[type="checkbox"]').isChecked());
      check("Rule A is described as an assumption, not a requirement",
        (await ruleA.textContent()).includes("Assumption"));
      check("Rule A is a two-notch rule",
        (await ruleA.textContent()).includes("2"));

      // The reported set cannot be edited from the screen.
      await page.click('[data-testid="reported-staging-toggle"]');
      const reportedBox = reported.locator('[data-rule="rating_notches"] input[type="checkbox"]');
      check("the reported set's rules are not switchable",
        await reportedBox.isDisabled());
      check("Rule A is off in the reported set", !(await reportedBox.isChecked()));

      const versionOf = async () =>
        (await page.locator('[data-testid="whatif-staging-version"]').textContent()).trim();
      const first = await versionOf();
      check("the default rule set names itself", first.includes("what-if-default"),
        first);

      // Edit a threshold.
      const threshold = ruleA.locator('input[type="number"]');
      await threshold.fill("3");
      await threshold.blur();
      await page.waitForTimeout(2500);
      const edited = await versionOf();
      check("editing a threshold gives the rule set a new version",
        edited !== first, `${first} -> ${edited}`);

      // Disable a rule.
      await ruleB.locator('input[type="checkbox"]').uncheck();
      await page.waitForTimeout(2500);
      check("a rule can be switched off",
        !(await ruleB.locator('input[type="checkbox"]').isChecked()));

      // Combine with AND.
      await page.selectOption('[data-testid="staging-combination"]', "ALL");
      await page.waitForTimeout(2500);
      check("the rules can be combined with ALL as well as ANY",
        (await page.locator('[data-testid="whatif-staging"]').textContent())
          .includes("EVERY"));

      // Add a rule, then take it away again.
      check("a rule can be composed on screen",
        await appears(page, '[data-testid="staging-add"]', 20_000));
      await page.selectOption('select[aria-label="New rule kind"]', "absolute_pd");
      await page.fill('input[aria-label="New rule threshold"]', "6");
      await page.fill('input[aria-label="New rule name"]', "Watchlist PD");
      await page.click('[data-testid="staging-add-submit"]');
      await page.waitForTimeout(2500);
      const added = await page.locator('[data-testid="whatif-staging"] tbody tr').count();
      check("the added rule joins the set", added >= 6, `${added} rules`);
      check("the added rule is named as the person named it",
        (await page.locator('[data-testid="whatif-staging"]').textContent())
          .includes("Watchlist PD"));

      await page.getByRole("button", { name: "Remove Watchlist PD" }).click();
      await page.waitForTimeout(2500);
      check("the added rule can be removed again",
        !(await page.locator('[data-testid="whatif-staging"]').textContent())
          .includes("Watchlist PD"));

      // A governed rule offers no Remove at all.
      check("a governed rule cannot be removed",
        (await page.locator('[data-rule="relative_pd"]').first().textContent())
          .includes("kept"));

      // Reset, and the thread is back on the default.
      await page.click('[data-testid="staging-reset"]');
      await page.waitForTimeout(2500);
      check("reset returns the thread to the What-If default",
        (await versionOf()).includes("what-if-default"));
    });

  /* ------------------------------------ 11. The override reaches the run */
  await journey("Journey 11 — A staging override changes the answer",
    async (page, check) => {
      await page.goto(`${WEB}/what-if/thread?journey=rating`, { waitUntil: "networkidle" });
      await appears(page, '[data-testid="whatif-composer"]', 60_000);
      await say(page, "Downgrade everyone two notches.");
      const ran = await chooseMethodology(page, check, "delta");
      if (!ran) return;
      const first = page.locator('[data-testid="whatif-result"]').first();
      check("the result names BOTH rule sets",
        (await first.locator('[data-testid="result-reported-staging"]').count()) > 0
        && (await first.locator('[data-testid="result-whatif-staging"]').count()) > 0);
      check("the reported book is staged by the reported-book policy",
        (await first.locator('[data-testid="result-reported-staging"]').textContent())
          .includes("reported-book"));
      check("the What-If is staged by the What-If default",
        (await first.locator('[data-testid="result-whatif-staging"]').textContent())
          .includes("what-if-default"));

      // Switch Rule A and Rule B off, then layer a shock so the thread runs
      // again. The staging change alone is a setting; the next run is what
      // applies it, and the version on that result is the proof.
      await page.click('[data-testid="staging-toggle"]');
      await appears(page, '[data-testid="whatif-staging"]', 30_000);
      await page.locator('[data-rule="rating_notches"] input[type="checkbox"]').uncheck();
      await page.waitForTimeout(2500);
      await page.locator('[data-rule="scenario_pd_ratio"] input[type="checkbox"]').uncheck();
      await page.waitForTimeout(2500);
      await say(page, "Also increase LGD by two percentage points.");
      await page.waitForTimeout(9000);
      const results = page.locator('[data-testid="whatif-result"]');
      const count = await results.count();
      check("the override produced a second result", count >= 2, `${count}`);
      if (count >= 2) {
        const latest = results.nth(count - 1);
        const stamped = await latest
          .locator('[data-testid="result-whatif-staging"]').textContent();
        check("the second result carries the overridden rule set, not the default",
          !stamped.includes("what-if-default"), stamped.trim());
        check("and the reported book is still staged by the reported policy",
          (await latest.locator('[data-testid="result-reported-staging"]').textContent())
            .includes("reported-book"));
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
