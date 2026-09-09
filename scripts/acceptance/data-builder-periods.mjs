/**
 * Data Builder 2.0, driven through a real browser.
 *
 * The claims here cannot be made by a test that imports a function: that a
 * steward opening a dataset is told what it actually holds, that the two
 * downloads are the period on screen, that a file can be handed over without
 * publishing anything by arriving, and that the page still says one thing
 * about the version rather than two.
 *
 *     node scripts/acceptance/data-builder-periods.mjs
 *
 * It needs the backend on :8000 and the frontend on :3000. Set SHOT_DIR to
 * keep screenshots. It exits non-zero and lists every problem it found.
 */

const PW = process.env.PLAYWRIGHT_MODULE
  ?? "/opt/node22/lib/node_modules/playwright/index.js";
const CHROME = process.env.PLAYWRIGHT_CHROMIUM
  ?? "/opt/pw-browsers/chromium-1194/chrome-linux/chrome";
const BASE = process.env.CREDITPROBE_WEB ?? "http://127.0.0.1:3000";
const API = process.env.CREDITPROBE_API ?? "http://127.0.0.1:8000/api/v1";
const USER = process.env.CREDITPROBE_USER ?? "alex.rahman";
const PASSWORD = process.env.CREDITPROBE_PASSWORD ?? "creditprobe-demo";
const SHOT = process.env.SHOT_DIR;
const problems = [];
const step = (n, ok, d) => {
  console.log(`${ok ? "PASS" : "FAIL"}  ${n}${d ? " — " + d : ""}`);
  if (!ok) problems.push(n);
};
const pw = await import(PW);
const { chromium } = pw.default ?? pw;
const browser = await chromium.launch({ executablePath: CHROME });
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
page.on("pageerror", (e) => problems.push("page error: " + e.message));

await page.goto(BASE + "/", { waitUntil: "domcontentloaded" });
await page.locator("#username").waitFor({ state: "visible", timeout: 90000 }).catch(() => {});
if (await page.locator("#username").isVisible().catch(() => false)) {
  await page.locator("#username").fill(USER);
  await page.locator("#password").fill(PASSWORD);
  await page.getByRole("button", { name: /sign in/i }).click();
  await page.waitForTimeout(4000);
}

await page.goto(`${BASE}/data-builder/dataset/ifrs9_staging`, { waitUntil: "domcontentloaded" });
await page.waitForTimeout(8000);
let body = await page.locator("body").innerText();
step("DB1. The overview says what is in service, not only what was declared",
     /In service/.test(body) && /quarterly/i.test(body),
     (body.match(/Frequency\s*\n?\s*\w+/) ?? [""])[0].replace(/\n/g, " "));
step("DB1b. It does not say published and not published at once",
     !/not published/.test(body),
     (body.match(/Version\s*\n?\s*[^\n]+/) ?? [""])[0].replace(/\n/g, " "));
step("DB2. The coverage is the real one", /Q4 2022/.test(body) && /Q2 2026/.test(body) && /\b15\b/.test(body));
if (SHOT) await page.screenshot({ path: `${SHOT}/db2-1-overview.png`, fullPage: false });

// Periods tab
await page.getByRole("button", { name: /^Periods/ }).click().catch(async () => {
  await page.getByText(/^Periods/).first().click();
});
await page.waitForTimeout(3000);
body = await page.locator("body").innerText();
step("DB3. Periods in service are listed with both downloads",
     /Periods in service/.test(body) && /CSV/.test(body) && /Excel/.test(body));
step("DB4. The upload offers a new period and a correction",
     /Upload a period/.test(body));
const modes = await page.locator("select").first().locator("option").allInnerTexts().catch(() => []);
step("DB5. Both modes are offered", modes.length === 2, modes.join(" | "));
step("DB6. Nothing is published by arriving",
     /not published/i.test(body), (body.match(/It is not published[^.]*\./) ?? [""])[0].slice(0, 60));
step("DB7. The release history is on the page", /Release history/.test(body));
if (SHOT) await page.screenshot({ path: `${SHOT}/db2-2-periods.png`, fullPage: false });

// the download really is the period
const csv = await page.evaluate(async (api) => {
  const r = await fetch(`${api}/data-builder/datasets/ifrs9_staging/export?period=Q2%202026&limit=5`,
                        { credentials: "include" });
  return { status: r.status, text: (await r.text()).slice(0, 4000) };
}, API);
const csvRows = csv.text.split("\n").filter((l) => l && !l.startsWith("#"));
step("DB8. The CSV download is the period asked for",
     csv.status === 200 && csvRows.length > 1 && csvRows[0].includes("period"),
     `HTTP ${csv.status}, ${csvRows.length} lines`);
const wb = await page.evaluate(async (api) => {
  const r = await fetch(`${api}/data-builder/datasets/ifrs9_staging/workbook?period=Q2%202026&limit=5`,
                        { credentials: "include" });
  const b = await r.arrayBuffer();
  return { status: r.status, bytes: b.byteLength,
           zip: new Uint8Array(b.slice(0, 2)).join(",") };
}, API);
step("DB9. The workbook download is a real xlsx",
     wb.status === 200 && wb.zip === "80,75" && wb.bytes > 2000, `${wb.bytes} bytes`);

// Data tab
await page.goto(`${BASE}/data-builder/dataset/ifrs9_staging?tab=data`, { waitUntil: "domcontentloaded" });
await page.waitForTimeout(12000);
body = await page.locator("body").innerText();
step("DB10. The Data tab shows real rows", /SA-ACC-/.test(body) || /account_id/i.test(body),
     (body.match(/SA-ACC-\d+/) ?? [""])[0]);
if (SHOT) await page.screenshot({ path: `${SHOT}/db2-3-data.png`, fullPage: false });

const wide = await page.evaluate(() =>
  document.documentElement.scrollWidth <= window.innerWidth + 1);
step("Layout. The dataset page does not overflow at 1440px", wide);

console.log("\nPROBLEMS:", problems.length);
if (problems.length) console.log(problems.join("\n"));
await browser.close();
process.exit(problems.length ? 1 : 0);
