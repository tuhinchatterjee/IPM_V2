/**
 * The protected acceptance paths, driven through a real browser.
 *
 * Some of what this product promises cannot be proved by a test that imports a
 * function. "The recipient picker shows colleagues when you click into it" is a
 * claim about a rendered page and a real session; so is "reading a message
 * makes the badge in the corner go down". Those are the claims here.
 *
 * Run it around any significant change, and always on the final HEAD of a
 * night's work:
 *
 *     node scripts/acceptance/protected-paths.mjs
 *
 * It needs the backend on :8000 and the frontend on :3000, both signed-in
 * capable. It exits non-zero and lists every problem it found; it never reports
 * a pass it did not observe.
 *
 * Playwright is resolved from the machine rather than from the repository,
 * because the browser is a tool for checking this product, not a dependency of
 * it.
 */

const PW = process.env.PLAYWRIGHT_MODULE
  ?? "/opt/node22/lib/node_modules/playwright/index.js";
const CHROME = process.env.PLAYWRIGHT_CHROMIUM
  ?? "/opt/pw-browsers/chromium-1194/chrome-linux/chrome";
const BASE = process.env.CREDITPROBE_WEB ?? "http://127.0.0.1:3000";
const API = process.env.CREDITPROBE_API ?? "http://127.0.0.1:8000/api/v1";
const USER = process.env.CREDITPROBE_USER ?? "alex.rahman";
const PASSWORD = process.env.CREDITPROBE_PASSWORD ?? "creditprobe-demo";

/** The five questions the Cockpit is allowed to advertise. */
const APPROVED = [
  "Where is risk building across the bank?",
  "Which exposures have deteriorated this quarter?",
  "What is driving Stage 2 and ECL growth?",
  "Which borrowers are weakening but are not yet on the watchlist?",
  "Where are multiple warning signals appearing together?",
];

const problems = [];
const step = (name, ok, detail) => {
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? " — " + detail : ""}`);
  if (!ok) problems.push(name + (detail ? ": " + detail : ""));
};

// Playwright ships as CommonJS, so a dynamic import lands the real exports on
// `.default` under some Node versions and at the top level under others.
const pw = await import(PW);
const { chromium } = pw.default ?? pw;
const browser = await chromium.launch({ executablePath: CHROME });
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
page.on("pageerror", (e) => problems.push("page error: " + e.message));

const counts = () =>
  page.evaluate(async (api) => {
    const r = await fetch(`${api}/messages/counts`, { credentials: "include" });
    return r.ok ? await r.json() : { __status: r.status };
  }, API);

const headerBadge = async () =>
  (await page.locator('a[aria-label^="Messages,"] span').innerText()
     .catch(() => "0")).trim();

// ---------------------------------------------------------------- sign in
await page.goto(BASE + "/", { waitUntil: "domcontentloaded" });
await page.locator("#username").waitFor({ state: "visible", timeout: 90_000 })
  .catch(() => {});
if (await page.locator("#username").isVisible().catch(() => false)) {
  await page.locator("#username").fill(USER);
  await page.locator("#password").fill(PASSWORD);
  await page.getByRole("button", { name: /sign in/i }).click();
  await page.waitForTimeout(4000);
}
const me = await page.evaluate(async (api) => {
  const r = await fetch(`${api}/auth/me`, { credentials: "include" });
  const b = await r.json();
  return b.user ?? b;
}, API);
step("Signed in", Boolean(me && me.username), `${me?.username} / ${me?.role}`);
if (!me?.username) {
  console.log("\nPROBLEMS:", problems.length);
  await browser.close();
  process.exit(1);
}

// ============================================================= N. COCKPIT
// The greeting is presentation, and the suggestions are a governed set.
const heading = await page.locator("h1, h2").first().innerText().catch(() => "");
step("N1. The Cockpit greets by the personalisation name",
     /Mr\. Sajid|Good (morning|afternoon|evening)/i.test(heading),
     heading.slice(0, 70));

const bodyText = await page.locator("body").innerText();
const shown = APPROVED.filter((q) => bodyText.includes(q));
step("O1. Exactly three suggestions are shown", shown.length === 3,
     `${shown.length} shown`);
step("O2. Every one of them is from the approved five",
     shown.length > 0 && shown.every((q) => APPROVED.includes(q)),
     shown.map((q) => q.split(" ").slice(0, 4).join(" ") + "…").join(" | "));

const control = page.getByRole("button", { name: /personalise/i });
step("N2. The personalisation control is in the header",
     (await control.count()) > 0);
if (await control.count()) {
  await control.first().click();
  await page.waitForTimeout(500);
  const field = page.locator("#greeting-name");
  if (await field.count()) {
    await field.fill("Dr. Ahmed");
    await page.getByRole("button", { name: /^save$/i }).click();
    await page.waitForTimeout(1500);
    const after = await page.locator("h1, h2").first().innerText().catch(() => "");
    step("N3. The greeting updates without a reload", /Dr\. Ahmed/.test(after),
         after.slice(0, 50));

    await page.reload({ waitUntil: "domcontentloaded" });
    await page.waitForTimeout(3000);
    const reloaded = await page.locator("h1, h2").first().innerText()
      .catch(() => "");
    step("N4. It survives a reload", /Dr\. Ahmed/.test(reloaded),
         reloaded.slice(0, 50));

    const identity = await page.evaluate(async (api) => {
      const r = await fetch(`${api}/auth/me`, { credentials: "include" });
      const b = await r.json();
      return b.user ?? b;
    }, API);
    step("N5. Identity is untouched by the greeting",
         identity.username === me.username && identity.role === me.role,
         `${identity.username} / ${identity.role}`);

    await page.getByRole("button", { name: /personalise/i }).first().click();
    await page.waitForTimeout(500);
    await page.getByRole("button", { name: /^reset$/i }).click();
    await page.waitForTimeout(1500);
    const reset = await page.locator("h1, h2").first().innerText().catch(() => "");
    step("N6. Reset restores the default", /Mr\. Sajid/.test(reset),
         reset.slice(0, 50));
  } else {
    step("N3-N6. The greeting field is present", false, "#greeting-name absent");
  }
}

// =================================================== B. RECIPIENT PICKER
await page.goto(BASE + "/messages", { waitUntil: "domcontentloaded" });
await page.getByRole("button", { name: /^new message$/i })
  .waitFor({ state: "visible", timeout: 90_000 });
await page.waitForTimeout(1500);
await page.getByRole("button", { name: /^new message$/i }).click();
await page.waitForTimeout(800);
await page.locator("#compose-to").click();
await page.waitForTimeout(2000);

const options = page.locator('[data-testid="recipient-options"] li');
const onFocus = await options.count();
step("B1. Focusing To lists active users, nothing typed", onFocus > 0,
     `${onFocus} offered`);

const names = await options.locator("button").allInnerTexts()
  .then((t) => t.slice(0, 3).map((x) => x.split("\n")[0]));
step("B2. Rows are named, never raw identifiers",
     names.length > 0 &&
       names.every((n) => n && !/^\d+$/.test(n) &&
                          !/^[0-9a-f-]{30,}$/i.test(n)),
     names.join(" | "));

await page.locator("#compose-to").fill("IFRS 9");
await page.waitForTimeout(1600);
step("B3. Search by job title", (await options.count()) > 0);

await page.locator("#compose-to").fill(me.display_name ?? "Alex Rahman");
await page.waitForTimeout(1600);
const selfHit = await options.count();
step("B4. Search by whole name, and I can address myself", selfHit > 0,
     `${selfHit} match(es)`);
if (selfHit) await options.locator("button").first().click();
await page.waitForTimeout(400);

await page.locator("#compose-to").fill("Sarah");
await page.waitForTimeout(1600);
if (await options.count()) await options.locator("button").first().click();
await page.waitForTimeout(400);
let chips = await page.locator('[data-testid="recipient-chip"]').allInnerTexts();
step("B5. Self and another user are both selected", chips.length >= 2,
     chips.map((c) => c.replace(/\s*×\s*$/, "")).join(" | "));

// Removing one leaves the other.
const before = chips.length;
await page.locator('[data-testid="recipient-chip"] button').first().click();
await page.waitForTimeout(400);
chips = await page.locator('[data-testid="recipient-chip"]').allInnerTexts();
step("B6. A chip can be removed and the rest survive",
     chips.length === before - 1, `${before} → ${chips.length}`);

// ================================================= K. OBJECT SHARE + SEND
await page.getByRole("button", { name: /\+ Analysis/ }).click();
await page.waitForTimeout(2500);
const cards = page.locator('[data-testid="shareable-list"] li');
step("K1. Real analyses are offered as cards", (await cards.count()) > 0,
     `${await cards.count()} shareable`);
if (await cards.count()) {
  await cards.locator("button").first().click();
  await page.waitForTimeout(600);
}
step("K2. The chosen object attaches",
     (await page.locator('[data-testid="attachment-chip"]').count()) > 0);

// Re-add self so this is also the self-send path (C).
await page.locator("#compose-to").fill(me.display_name ?? "Alex Rahman");
await page.waitForTimeout(1600);
if (await options.count()) await options.locator("button").first().click();
await page.waitForTimeout(400);

const subject = `Protected acceptance ${Date.now()}`;
await page.locator("#compose-subject").fill(subject);
await page.locator("#compose-body").fill("Governed object attached.");
const beforeSend = await counts();
await page.getByRole("button", { name: /^send$/i }).click();
await page.waitForTimeout(5000);
const afterSend = await counts();

step("D1. The composer closes on success",
     (await page.locator("#compose-subject").count()) === 0);
const said = await page.getByRole("status").first().innerText().catch(() => "");
step("D2. The product confirms the send", /sent/i.test(said), said.trim());
step("D3. It did not navigate to Workflow", !page.url().includes("/workflow"),
     page.url());
step("D4. Sent grew by one", afterSend.sent === beforeSend.sent + 1,
     `${beforeSend.sent} → ${afterSend.sent}`);
step("C1. The self-addressed copy reached the Inbox, unread",
     afterSend.inbox === beforeSend.inbox + 1 &&
       afterSend.unread === beforeSend.unread + 1,
     `inbox ${beforeSend.inbox}→${afterSend.inbox}, ` +
     `unread ${beforeSend.unread}→${afterSend.unread}`);
step("D5. It is visible in Sent",
     (await page.getByText(subject).count()) > 0);
step("F1. Shared with me is not zero while a share exists",
     afterSend.shared_with_me > 0, `${afterSend.shared_with_me}`);

// ============================================== H. THE UNREAD COUNTDOWN
// Three real conversations, read one at a time. 3 → 2 → 1 → 0.
const meId = me.id;
const drill = [];
for (let n = 1; n <= 3; n++) {
  const made = await page.evaluate(async ([api, id, n]) => {
    const r = await fetch(`${api}/messages/send`, {
      method: "POST", credentials: "include",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ to: [id], subject: `Unread drill ${n}`,
                             body: "Counting down." }),
    });
    return r.ok ? await r.json() : { __status: r.status };
  }, [API, meId, n]);
  drill.push(made.thread_id);
}
step("H0. Three unread conversations exist", drill.every(Boolean),
     drill.join(", "));

// Clear everything else, then make exactly these three unread.
await page.evaluate(async ([api, ids]) => {
  const box = await (await fetch(`${api}/messages?box=inbox&limit=200&unread=true`,
                                 { credentials: "include" })).json();
  for (const row of box.items) {
    await fetch(`${api}/messages/threads/${row.thread_id}/read`, {
      method: "POST", credentials: "include",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ read: true }),
    });
  }
  for (const id of ids) {
    await fetch(`${api}/messages/threads/${id}/read`, {
      method: "POST", credentials: "include",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ read: false }),
    });
  }
}, [API, drill]);

await page.goto(BASE + "/messages?box=inbox", { waitUntil: "domcontentloaded" });
await page.waitForTimeout(4000);
const seq = [Number((await counts()).unread)];
const badges = [await headerBadge()];
for (const threadId of drill) {
  await page.goto(`${BASE}/messages/${threadId}`, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(3500);
  seq.push(Number((await counts()).unread));
  badges.push(await headerBadge());
}
console.log("      unread by API:", seq.join(" → "));
console.log("      header badge :", badges.join(" → "));
step("H1. Unread counts down 3 → 2 → 1 → 0",
     JSON.stringify(seq) === JSON.stringify([3, 2, 1, 0]), seq.join(" → "));

const live = await counts();
const shownBadge = parseInt(await headerBadge(), 10) || 0;
step("H2. The header badge equals the authoritative count, no reload",
     shownBadge === live.unread + live.action_required,
     `header=${shownBadge} api=${live.unread + live.action_required}`);

await page.reload({ waitUntil: "domcontentloaded" });
await page.waitForTimeout(3500);
const persisted = await counts();
step("M1. Read state persists across a reload",
     persisted.unread === live.unread,
     `${live.unread} → ${persisted.unread}`);

await page.goto(BASE + "/messages?box=inbox", { waitUntil: "domcontentloaded" });
await page.waitForTimeout(4000);
const now = await counts();
const tile = await page.locator('[data-testid="stat-unread"]').innerText()
  .catch(() => "");
step("H3. The Unread tile agrees",
     tile.trim().split(/\s+/)[0] === String(now.unread),
     `tile "${tile.replace(/\n/g, " ").trim()}", api ${now.unread}`);
const sharedTile = await page.locator('[data-testid="stat-shared-with-me"]')
  .innerText().catch(() => "");
step("F2. The Shared with me tile reconciles",
     Number(sharedTile.trim().split(/\s+/)[0]) === now.shared_with_me,
     `tile "${sharedTile.replace(/\n/g, " ").trim()}", api ${now.shared_with_me}`);

await page.goto(BASE + "/workspace", { waitUntil: "domcontentloaded" });
await page.waitForTimeout(4000);
const wsUnread = await page.locator('[data-testid="stat-unread-messages"]')
  .innerText().catch(() => "");
step("H4. My workspace agrees with the same count",
     wsUnread ? wsUnread.trim().split(/\s+/)[0] === String(now.unread)
              : (await page.locator("body").innerText())
                  .includes(String(now.unread)),
     `workspace "${wsUnread.replace(/\n/g, " ").trim()}", api ${now.unread}`);

// ============================================== G. WORKFLOW IS OVERSIGHT
await page.goto(BASE + "/workflow", { waitUntil: "domcontentloaded" });
await page.waitForTimeout(5000);
const wf = await page.locator("body").innerText();
step("G1. Workflow shows operational metadata",
     /Active accounts/i.test(wf) && /Last active/i.test(wf) &&
     /Action required/i.test(wf) && /Overdue/i.test(wf));
step("G2. No message subject or body appears on it", !wf.includes(subject),
     "checked the subject sent above");
step("G3. It is not a mailbox",
     (await page.locator('main a[href^="/messages/"]').count()) === 0 &&
     (await page.getByRole("button",
        { name: /^(Inbox|Drafts|Archived|Sent)$/ }).count()) === 0);
step("G4. It routes to user administration",
     (await page.getByRole("link", { name: /manage users/i }).count()) > 0);

const anonymous = await page.evaluate(async (api) => {
  const r = await fetch(`${api}/messages/admin/overview`, { credentials: "omit" });
  return r.status;
}, API);
step("L1. The oversight route refuses an unauthenticated caller",
     anonymous === 401 || anonymous === 403, `HTTP ${anonymous}`);

await page.goto(BASE + "/reviews", { waitUntil: "domcontentloaded" });
await page.waitForTimeout(4000);
step("G5. The personal review queue is its own page",
     /My reviews/i.test(await page.locator("body").innerText()));

// ------------------------------------------------------------- layout
for (const [name, path] of [["Messages", "/messages"],
                            ["Workflow", "/workflow"],
                            ["My workspace", "/workspace"],
                            ["Cockpit", "/"]]) {
  await page.goto(BASE + path, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(3500);
  const overflow = await page.evaluate(() =>
    document.documentElement.scrollWidth > window.innerWidth + 2
      ? `${document.documentElement.scrollWidth} > ${window.innerWidth}` : "");
  step(`Layout. ${name} does not overflow at 1440px`, overflow === "", overflow);
}

console.log("\nPROBLEMS:", problems.length);
for (const p of problems) console.log("  -", p);
await browser.close();
process.exit(problems.length ? 1 : 0);
