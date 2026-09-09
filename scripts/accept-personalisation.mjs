/**
 * Browser acceptance for the Cockpit personalisation control.
 * The ten steps in the brief, in order, with a screenshot at each checkpoint.
 */
import { chromium } from "playwright";

const BASE = "http://127.0.0.1:3100";
const OUT = process.argv[2];
const say = (...a) => console.log(...a);

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const problems = [];

// A signed-in account, because a preference belongs to one.
await page.goto(BASE, { waitUntil: "networkidle" });
await page.waitForTimeout(1500);
const user = process.env.ACCEPT_USER, pass = process.env.ACCEPT_PASS;
const form = page.locator("#username");
if (await form.count()) {
  await page.fill("#username", user);
  await page.fill("#password", pass);
  await page.click('button[type="submit"]');
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(1500);
} else {
  console.log("!! no login form rendered — running unauthenticated");
}

// 1-2. Open the Cockpit and confirm the greeting.
await page.goto(BASE, { waitUntil: "networkidle" });
await page.waitForTimeout(1200);
const heading = () => page.locator("h1").first().innerText();
const first = await heading();
say("1-2. greeting:", JSON.stringify(first));
if (!/Good (morning|afternoon|evening)/.test(first)) problems.push("no time-of-day greeting");
if (!first.includes("Mr. Sajid")) problems.push(`default is not Mr. Sajid: ${first}`);
await page.screenshot({ path: `${OUT}/01-default.png` });

// 3. Open the top-right personalisation control.
const control = page.getByRole("button", { name: /Personalise the Cockpit/i });
if (!(await control.count())) problems.push("no personalisation control in the header");
await control.click();
const dialog = page.getByRole("dialog", { name: /Personalise Cockpit/i });
await dialog.waitFor({ state: "visible", timeout: 5000 });
say("3. control opened");
await page.screenshot({ path: `${OUT}/02-open.png` });

// 4-5. Change Mr. Sajid to Dr. Ahmed and save.
const input = page.locator("#greeting-name");
await input.fill("Dr. Ahmed");
await page.waitForTimeout(200);
const preview = await dialog.innerText();
if (!preview.includes("Dr. Ahmed")) problems.push("the preview did not follow what was typed");
say("4. preview updates live");
await page.screenshot({ path: `${OUT}/03-preview.png` });
await page.getByRole("button", { name: /^Save$/ }).click();
await page.waitForTimeout(1200);

// 6. The greeting updates immediately — no reload.
const afterSave = await heading();
say("6. after save (no reload):", JSON.stringify(afterSave));
if (!afterSave.includes("Dr. Ahmed")) problems.push(`no immediate update: ${afterSave}`);
await page.screenshot({ path: `${OUT}/04-saved.png` });

// 7-8. Reload; the preference persists.
await page.reload({ waitUntil: "networkidle" });
await page.waitForTimeout(1200);
const afterReload = await heading();
say("7-8. after reload:", JSON.stringify(afterReload));
if (!afterReload.includes("Dr. Ahmed")) problems.push(`did not persist: ${afterReload}`);
await page.screenshot({ path: `${OUT}/05-persisted.png` });

// 9-10. Reset restores the default.
const stored = await page.evaluate(async () =>
  (await fetch("/api/v1/preferences")).json());
say("   stored before reset:", JSON.stringify(stored));
await page.getByRole("button", { name: /Personalise the Cockpit/i }).click();
await dialog.waitFor({ state: "visible", timeout: 5000 });
const reset = page.getByRole("button", { name: /^Reset$/ });
say("   reset disabled?", await reset.isDisabled());
await reset.click();
await page.waitForTimeout(1200);
const afterReset = await heading();
say("9-10. after reset:", JSON.stringify(afterReset));
if (!afterReset.includes("Mr. Sajid")) problems.push(`reset did not restore the default: ${afterReset}`);
await page.screenshot({ path: `${OUT}/06-reset.png` });

// The layout stays clean: the header controls are all still there.
const controls = await page.locator("header button").count();
say("header controls:", controls);
if (controls < 5) problems.push(`header lost controls: only ${controls}`);

await browser.close();
if (problems.length) { console.log("\nFAILED:"); problems.forEach((p) => console.log(" -", p)); process.exit(1); }
console.log("\nPASSED: all ten steps");
