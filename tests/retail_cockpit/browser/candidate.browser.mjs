/**
 * The Retail Demo, in a real browser, with the AdvancedCockpit on it.
 *
 * What this is for: the things unit tests cannot see. That the page mounts
 * the Cockpit and not the legacy one; that the legacy Cockpit's requests do
 * not fire behind it; that every Cockpit call goes to the RETAIL origin and
 * never to the engine's port; that the shell and its navigation survive; and
 * that the other modules still load.
 *
 * It asserts on the NETWORK as much as the DOM, because "the page rendered"
 * is exactly the claim that hides a legacy component still polling behind a
 * new one.
 *
 *   node tests/retail_cockpit/browser/candidate.browser.mjs
 */

import { chromium } from "/opt/node22/lib/node_modules/playwright/index.mjs";

const UI = process.env.CANDIDATE_UI_URL ?? "http://localhost:5328";
const API = process.env.CANDIDATE_API_URL ?? "http://127.0.0.1:8328";
const ENGINE = process.env.CANDIDATE_ENGINE_URL ?? "http://127.0.0.1:8414";
const CHROME =
  process.env.CANDIDATE_CHROME ??
  "/opt/pw-browsers/chromium-1194/chrome-linux/chrome";
const CYCLES = Number(process.env.CANDIDATE_CYCLES ?? "3");

/** The legacy Cockpit's own calls. If any fires, it is still mounted. */
const FORBIDDEN = [
  "/api/v1/ask/mode",
  "/api/v1/ask/briefing",
  "/api/v1/ask/suggestions",
  "/api/v1/agentic/officer",
];

const results = [];
let failures = 0;

function check(name, ok, detail = "") {
  results.push({ name, ok, detail });
  if (!ok) failures += 1;
  process.stdout.write(`  ${ok ? "ok  " : "FAIL"}  ${name}${detail ? ` — ${detail}` : ""}\n`);
}

async function journey(browser, cycle) {
  const context = await browser.newContext({ viewport: { width: 1600, height: 1000 } });
  const page = await context.newPage();
  const requests = [];
  page.on("request", (r) => requests.push(r.url()));
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));

  // 1. launch
  const response = await page.goto(UI, { waitUntil: "networkidle", timeout: 90_000 });
  check(`[${cycle}] the home page loads`, response?.status() === 200, `status ${response?.status()}`);

  // 2. the Cockpit, not the legacy one
  const badge = await page.locator('[data-testid="cockpit-source-badge"]').first();
  const hasBadge = await badge.count();
  check(`[${cycle}] the source badge names the book`, hasBadge > 0);
  if (hasBadge) {
    const text = (await badge.innerText()).replace(/\s+/g, " ");
    check(`[${cycle}] the badge says Retail Cockpit and the release`,
      text.includes("Retail Cockpit") && text.includes("cockpitdata-"), text.slice(0, 140));
    check(`[${cycle}] the badge states the denomination and coverage`,
      text.includes("SAR") && /month/i.test(text), text.slice(0, 140));
  }

  // 3. the legacy Cockpit is NOT behind it
  const fired = FORBIDDEN.filter((p) => requests.some((u) => u.includes(p)));
  check(`[${cycle}] the legacy Cockpit's requests never fire`, fired.length === 0, fired.join(", "));

  // 4. every Cockpit call goes to the retail origin, never the engine port
  const cockpitCalls = requests.filter((u) => u.includes("/api/v1/cockpit-v4/"));
  check(`[${cycle}] the Cockpit talked to the retail origin`, cockpitCalls.length > 0,
    `${cockpitCalls.length} call(s)`);
  const leaked = requests.filter((u) => u.startsWith(ENGINE));
  check(`[${cycle}] the browser never reached the engine directly`, leaked.length === 0,
    leaked.slice(0, 2).join(", "));

  // 5. the Cockpit's own furniture is on the page
  const body = (await page.locator("body").innerText()).replace(/\s+/g, " ");
  check(`[${cycle}] the Cockpit ask box is mounted`, /Ask the Cockpit/i.test(body));
  check(`[${cycle}] the analysis-depth control is the Cockpit's`,
    /Analysis depth/i.test(body) && /Deep/.test(body));
  check(`[${cycle}] the ECL panel computed`, /Expected credit loss/i.test(body)
    && !/could not be computed/i.test(body),
    /could not be computed/i.test(body) ? "panel reported an error" : "");
  check(`[${cycle}] the attention feed computed`,
    !/attention feed unavailable/i.test(body));

  // 6. no book switcher: the CONTROL, not the word. A suggestion that
  //    mentions the corporate book is a different (real) problem, asserted
  //    separately below.
  const switcher = await page
    .locator('button, [role="combobox"], select')
    .filter({ hasText: /corporate/i })
    .count();
  check(`[${cycle}] no Corporate/Retail switch control`, switcher === 0,
    `${switcher} control(s)`);

  // 6b. the prompts offered must belong to THIS book.
  const corporatePrompts = await page
    .getByText(/sector|corporate book|borrowers were downgraded/i)
    .count();
  check(`[${cycle}] the suggested questions are retail ones`,
    corporatePrompts === 0, `${corporatePrompts} corporate prompt(s)`);

  // 7. the shell survived: navigation still lists the other modules
  for (const label of ["Projects", "Investigations", "Data Builder", "What-If Analysis"]) {
    const found = await page.getByRole("link", { name: new RegExp(label, "i") }).count();
    check(`[${cycle}] the shell still offers ${label}`, found > 0);
  }

  // 8. another module still works
  await page.goto(`${UI}/data-builder`, { waitUntil: "networkidle", timeout: 90_000 });
  check(`[${cycle}] Data Builder loads`, page.url().includes("/data-builder"));
  const builderText = (await page.locator("body").innerText()).replace(/\s+/g, " ");
  check(`[${cycle}] Data Builder still names the published domains`,
    /Cockpit Data/i.test(builderText) || /Early Warning/i.test(builderText),
    builderText.slice(0, 120));

  // 9. back to the Cockpit, and it is still the new one
  await page.goto(UI, { waitUntil: "networkidle", timeout: 90_000 });
  check(`[${cycle}] the Cockpit is still there after navigating away and back`,
    (await page.locator('[data-testid="cockpit-source-badge"]').count()) > 0);

  // 10. a reload does not break it
  await page.reload({ waitUntil: "networkidle", timeout: 90_000 });
  check(`[${cycle}] it survives a reload`,
    (await page.locator('[data-testid="cockpit-source-badge"]').count()) > 0);

  check(`[${cycle}] no uncaught page errors`, errors.length === 0, errors.slice(0, 2).join(" | "));

  await context.close();
}

const browser = await chromium.launch({ executablePath: CHROME, args: ["--no-sandbox"] });
try {
  for (let cycle = 1; cycle <= CYCLES; cycle += 1) {
    process.stdout.write(`\ncycle ${cycle} of ${CYCLES}\n`);
    await journey(browser, cycle);
  }
} finally {
  await browser.close();
}

const passed = results.filter((r) => r.ok).length;
process.stdout.write(`\n${passed} of ${results.length} checks passed across ${CYCLES} cycles\n`);
process.exit(failures ? 1 : 0);
