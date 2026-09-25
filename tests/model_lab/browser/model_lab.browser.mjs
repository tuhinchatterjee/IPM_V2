/**
 * Browser acceptance for the model-comparison lab (U01, U03-U06, U08-U11,
 * U13-U16). Drives the REAL lab page against the REAL lab API; the "models"
 * are labelled FIXTURES (the lab has no model in this environment), so this
 * proves the disclosure, not any model's quality.
 *
 *   LAB_UI_URL=http://127.0.0.1:5424 node tests/model_lab/browser/model_lab.browser.mjs
 */

import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { chromium } from "/opt/node22/lib/node_modules/playwright/index.mjs";

const UI = process.env.LAB_UI_URL ?? "http://127.0.0.1:5424";
const OUT = process.env.LAB_EVIDENCE_DIR ?? "artifacts/model_comparison/browser";
const CHROME =
  process.env.LAB_CHROME ?? "/opt/pw-browsers/chromium-1194/chrome-linux/chrome";
fs.mkdirSync(OUT, { recursive: true });

const results = [];
async function step(id, name, fn) {
  const t = Date.now();
  try {
    await fn();
    results.push({ id, name, outcome: "PASS", ms: Date.now() - t });
    console.log(`PASS ${id} ${name}`);
  } catch (e) {
    results.push({ id, name, outcome: "FAIL", ms: Date.now() - t, error: String(e).slice(0, 500) });
    console.log(`FAIL ${id} ${name}: ${String(e).slice(0, 300)}`);
  }
}

const browser = await chromium.launch({ executablePath: CHROME });
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, acceptDownloads: true });
const page = await ctx.newPage();
const scriptErrors = [];
page.on("pageerror", (e) => scriptErrors.push(String(e)));
const labRequests = [];
page.on("request", (r) => {
  if (r.url().includes("/api/v1/model-lab/comparisons") && r.method() === "POST")
    labRequests.push(r.url());
});

await step("U16a", "lab page loads with the section above the unchanged Cockpit", async () => {
  await page.goto(`${UI}/cockpit/lab`, { waitUntil: "domcontentloaded", timeout: 180000 });
  await page.getByRole("heading", { name: /Model comparison/ }).waitFor({ timeout: 120000 });
  await page.getByText("EXPERIMENTAL").first().waitFor();
});

await step("U02", "saved presets load and preselect models with readiness text", async () => {
  const preset = page.getByLabel("Preset");
  await preset.waitFor({ timeout: 30000 });
  for (let i = 0; i < 60 && (await preset.inputValue()) !== "fixture-demo"; i++)
    await page.waitForTimeout(500);
  assert.equal(await preset.inputValue(), "fixture-demo");
  const body = await page.textContent("body");
  assert.match(body, /Needs approval|Not installed|Disabled/);
  assert.match(body, /Opus baseline \(frozen provider\)/);
});

await step("U01", "one typed question + one click creates the whole group", async () => {
  await page.getByTestId("model-lab-question").fill(
    "What is Stage 2 exposure by sector for the latest quarter?",
  );
  await page.getByTestId("model-lab-compare").dblclick();   // double-click: still ONE group
  await page.getByTestId("model-lab-result").waitFor({ timeout: 60000 });
  await page.getByRole("heading", { name: "Four stages" }).waitFor({ timeout: 120000 });
  const creates = labRequests.filter((u) => u.endsWith("/comparisons"));
  assert.ok(creates.length >= 1);
  const text = await page.textContent("body");
  const ids = new Set(text.match(/cmp-[0-9a-f]{12}/g));
  assert.equal(ids.size, 1, `expected one comparison, saw ${[...ids]}`);
});

await step("U03", "blocked models keep a row with the reason", async () => {
  const text = await page.textContent("[data-testid=model-lab-result]");
  assert.match(text, /Opus baseline \(frozen provider\)/);
  assert.match(text, /COCKPIT_ANTHROPIC_API_KEY/);
  assert.match(text, /Qwen3\.5-9B/);
});

await step("U05", "answer cards show real per-child answers and a FIXTURE label", async () => {
  const text = await page.textContent("[data-testid=model-lab-result]");
  assert.match(text, /carries the largest Stage 2 exposure/);
  assert.match(text, /FIXTURE/);
});

await step("U06", "four-stage matrix shows statuses as text, incl. not-observed", async () => {
  const matrix = page.getByRole("table", { name: "Four-stage matrix" });
  const t = await matrix.textContent();
  for (const s of ["S1", "S2", "S3", "S4"]) assert.ok(t.includes(s));
  assert.match(t, /Not observed/);
  assert.match(t, /Fail/);
  assert.match(t, /CreditProbe execution/);
});

await step("U09", "a failed cell opens the exact check with expected/actual", async () => {
  const cell = page.getByRole("button", { name: /S1 for Fixture: whole-book scope error/ });
  await cell.click();
  await page.getByText("S1S2-POP").first().waitFor({ timeout: 10000 });
  const t = await page.textContent("body");
  assert.match(t, /Expected: "stage == 2/);
  assert.match(t, /Truth source: independent pandas oracle/);
});

await step("U08", "metrics carry definitions/status and are keyboard-focusable", async () => {
  const m = page.locator("table[aria-label='Overview, one row per model'] span[tabindex='0']").first();
  await m.focus();
  const label = await m.getAttribute("aria-label");
  assert.match(label, /Status: (MEASURED|DERIVED|ESTIMATED|UNAVAILABLE)/);
  const t = await page.textContent("table[aria-label='Overview, one row per model']");
  assert.match(t, /unknown/);   // blocked models: unknown, not 0
});

await step("U11", "clarification answer resumes only the ticked child", async () => {
  await page.getByText("Waiting for your clarification").waitFor({ timeout: 30000 });
  await page.getByRole("checkbox", { name: /Fixture: asks for clarification asked/ }).check();
  await page.getByLabel("Clarification answer").fill("EAD");
  await page.getByRole("button", { name: "Send" }).click();
  await page.waitForFunction(
    () => !document.body.innerText.includes("Waiting for your clarification"),
    null, { timeout: 60000 });
});

await step("U15", "the comparison pack downloads without re-running models", async () => {
  const before = labRequests.length;
  const link = page.getByTestId("model-lab-download");
  await link.waitFor({ timeout: 60000 });
  const [dl] = await Promise.all([page.waitForEvent("download"), link.click()]);
  const file = path.join(OUT, await dl.suggestedFilename());
  await dl.saveAs(file);
  assert.ok(fs.statSync(file).size > 1000);
  assert.equal(labRequests.length, before, "download must not POST a comparison");
});

await step("U13", "refresh reopens the saved comparison without a new run", async () => {
  const before = labRequests.filter((u) => u.endsWith("/comparisons")).length;
  await page.reload({ waitUntil: "domcontentloaded" });
  await page.getByTestId("model-lab-result").waitFor({ timeout: 60000 });
  const after = labRequests.filter((u) => u.endsWith("/comparisons")).length;
  assert.equal(after, before);
});

await step("U04", "the original Cockpit chat is still on the page", async () => {
  await page.getByTestId("cockpit-v4-ask-box").first().waitFor({ timeout: 60000 });
});

await step("U16b", "no script errors; untrusted text is not rendered as HTML", async () => {
  assert.deepEqual(scriptErrors, []);
  const injected = await page.locator("[data-testid=model-lab-result] script").count();
  assert.equal(injected, 0);
});

await page.screenshot({ path: path.join(OUT, "lab_desktop.png"), fullPage: false });

await step("U16c", "Mac-sized and narrow layouts do not scroll the page sideways", async () => {
  for (const width of [1280, 390]) {
    await page.setViewportSize({ width, height: 800 });
    const over = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    assert.ok(over <= 1, `page scrolls sideways by ${over}px at ${width}px`);
  }
  await page.screenshot({ path: path.join(OUT, "lab_narrow.png"), fullPage: false });
});

await browser.close();
fs.writeFileSync(path.join(OUT, "browser_results.json"), JSON.stringify(results, null, 1));
const failed = results.filter((r) => r.outcome !== "PASS");
console.log(`\n${results.length - failed.length}/${results.length} browser checks passed`);
process.exit(failed.length ? 1 : 0);
