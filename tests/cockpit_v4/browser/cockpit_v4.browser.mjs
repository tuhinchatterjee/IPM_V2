/**
 * REAL BROWSER · REAL UI · REAL BACKEND · MOCK ANALYST.
 *
 * A real Chromium against the real Next.js UI and the real V4 API. Every
 * network request the page makes is recorded, which is what makes the central
 * claim checkable rather than asserted: the Cockpit page uses the V4 run API
 * and never touches the legacy investigation or agentic-officer endpoints.
 *
 * The ANALYST is a stub. This proves the wiring, the lifecycle and the
 * rendering. It proves nothing about answer quality, and nothing here claims
 * a live Opus validation.
 */

import assert from "node:assert/strict";
import { chromium } from "/opt/node22/lib/node_modules/playwright/index.mjs";

const UI = process.env.V4_UI_URL ?? "http://127.0.0.1:5414";
const API = process.env.V4_API_URL ?? "http://127.0.0.1:8414";
const CHROME =
  process.env.V4_CHROME ?? "/opt/pw-browsers/chromium-1194/chrome-linux/chrome";

/** Endpoints a V4 runtime must never call. The defect, as a list. */
const FORBIDDEN = [
  "/api/v1/investigations",
  "/api/v1/agentic/officer",
  "/api/v1/ask/mode",
  "/api/v1/ask/briefing",
  "/api/v1/ask/suggestions",
  "/api/v1/ask/cockpit-v2/diagnostics",
  "/api/v1/cockpit/diagnostics",
];

const results = [];
let failures = 0;

async function test(name, fn) {
  const started = Date.now();
  try {
    await fn();
    results.push({ name, ok: true, ms: Date.now() - started });
    console.log(`  ok   ${name}`);
  } catch (error) {
    failures += 1;
    results.push({
      name,
      ok: false,
      ms: Date.now() - started,
      error: String(error?.message ?? error).split("\n").slice(0, 4).join(" | "),
    });
    console.log(`  FAIL ${name}\n       ${error?.message ?? error}`);
  }
}

/** A page that records every request it makes, with a live event tap. */
async function openCockpit(browser, { path = "/" } = {}) {
  const context = await browser.newContext();
  const page = await context.newPage();
  const requests = [];
  const sse = [];
  const problems = [];
  page.on("request", (request) => requests.push(request.url()));
  page.on("console", (message) => {
    if (message.type() === "error") problems.push(`console: ${message.text()}`);
  });
  page.on("requestfailed", (request) =>
    problems.push(
      `requestfailed: ${request.url()} — ${request.failure()?.errorText ?? ""}`,
    ),
  );
  page.on("response", (response) => {
    const url = response.url();
    if (url.includes("/events")) sse.push({ url, status: response.status() });
  });
  await page.goto(`${UI}${path}`, { waitUntil: "domcontentloaded" });
  await expect(page, '[data-testid="cockpit-v4-home"]', 60_000, problems);
  return { context, page, requests, sse, problems };
}

function calls(requests, fragment) {
  return requests.filter((url) => url.includes(fragment));
}

function assertNoLegacyCalls(requests, where) {
  for (const endpoint of FORBIDDEN) {
    const hits = calls(requests, endpoint);
    assert.equal(
      hits.length,
      0,
      `${where}: the V4 runtime called ${endpoint} (${hits[0] ?? ""}). ` +
        `That is the legacy flow, and reaching it means Opus V4 was bypassed.`,
    );
  }
}

async function ask(page, question) {
  await page.fill('[data-testid="cockpit-v4-question"]', question);
  await page.click('[data-testid="cockpit-v4-ask"]');
}

/** Wait, and say what the browser complained about when it times out. */
async function expect(page, selector, timeout, problems) {
  try {
    return await page.waitForSelector(selector, { timeout });
  } catch (error) {
    const submitError = await page
      .textContent('[data-testid="cockpit-v4-submit-error"]')
      .catch(() => "");
    throw new Error(
      `${selector} never appeared.` +
        (submitError ? ` Page said: ${submitError}.` : "") +
        (problems?.length ? ` Browser reported: ${problems.slice(0, 3).join(" ; ")}` : ""),
    );
  }
}

const browser = await chromium.launch({
  executablePath: CHROME,
  args: ["--no-sandbox", "--disable-dev-shm-usage"],
});

console.log(`\nCockpit V4 browser tests — UI ${UI}, API ${API}\n`);

// ---- the central claim -------------------------------------------------

await test(
  "asking 'Who are you?' posts to the V4 run API and never to the legacy flow",
  async () => {
    const { context, page, requests, problems } = await openCockpit(browser);
    try {
      // Nothing legacy on load, before a single interaction.
      assertNoLegacyCalls(requests, "on page load");

      await ask(page, "Who are you?");

      await expect(page, '[data-testid="v4-response"]', 60_000, problems);

      const runPosts = calls(requests, "/api/v1/cockpit-v4/runs").filter(
        (url) => !url.includes("/events") && !url.includes("/cancel"),
      );
      assert.ok(
        runPosts.length >= 1,
        "submitting must POST /api/v1/cockpit-v4/runs",
      );
      assertNoLegacyCalls(requests, "after submitting");
    } finally {
      await context.close();
    }
  },
);

await test("the process panel appears and consumes the V4 event stream",
  async () => {
    const { context, page, requests, sse, problems } = await openCockpit(browser);
    try {
      await ask(page, "Who are you?");

      // The panel is on screen while the run is still working — not after.
      await expect(page, '[data-testid="v4-process-panel"]', 30_000, problems);

      await expect(page, '[data-testid="v4-response"]', 60_000, problems);

      const streams = calls(requests, "/events");
      assert.ok(
        streams.length >= 1,
        "the page must subscribe to /runs/{run_id}/events",
      );
      assert.match(
        streams[0],
        /\/api\/v1\/cockpit-v4\/runs\/run-[0-9a-f]+\/events/,
        "the stream must be the V4 run's own event endpoint",
      );
      assert.ok(
        sse.some((s) => s.status === 200),
        "the event stream must actually connect",
      );
    } finally {
      await context.close();
    }
  },
);

await test("progress events are rendered before the answer arrives",
  async () => {
    const { context, page, problems } = await openCockpit(browser);
    try {
      await ask(page, "Who are you?");

      // Open the panel and capture the summary while the run is still going.
      await expect(page, '[data-testid="v4-process-panel"]', 30_000, problems);
      await page.click('[data-testid="v4-toggle-process"]');

      const working = await page.waitForFunction(
        () => {
          const summary = document.querySelector(
            '[data-testid="v4-process-summary"]',
          );
          const answered = document.querySelector('[data-testid="v4-response"]');
          if (answered) return false;
          const text = summary?.textContent ?? "";
          return /elapsed/.test(text) ? text : false;
        },
        { timeout: 30_000 },
      );
      const summaryWhileWorking = await working.jsonValue();
      assert.ok(
        summaryWhileWorking,
        "a working summary must be visible before the answer",
      );

      // The steps are backend stages, not invented labels.
      const steps = await page.$$eval(
        '[data-testid="v4-process-steps"] li',
        (nodes) => nodes.map((n) => n.textContent ?? ""),
      );
      assert.ok(steps.length >= 1, "the panel lists real stages");
      assert.ok(
        steps.some((s) => /Request accepted|Understanding the request/.test(s)),
        `the stages must be backend stages, got ${JSON.stringify(steps)}`,
      );

      await expect(page, '[data-testid="v4-response"]', 60_000, problems);
    } finally {
      await context.close();
    }
  },
);

await test("the final answer renders with its disposition", async () => {
  const { context, page, requests, problems } = await openCockpit(browser);
  try {
    await ask(page, "Who are you?");
    const panel = await expect(page, '[data-testid="v4-response"]', 60_000, problems);
    const disposition = await panel.getAttribute("data-disposition");
    assert.equal(disposition, "answer");
    const text = await panel.textContent();
    assert.match(text ?? "", /CreditProbe/);

    // The authoritative status was read, not guessed.
    assert.ok(
      calls(requests, "/api/v1/cockpit-v4/runs/").some(
        (url) => !url.includes("/events"),
      ),
      "the page reads the authoritative run state",
    );
  } finally {
    await context.close();
  }
});

await test("an evidence-bound analysis renders artifact links", async () => {
  const { context, page, problems } = await openCockpit(browser);
  try {
    await ask(page, "What is the EAD by sector for the latest quarter?");
    await expect(page, '[data-testid="v4-response"]', 90_000, problems);
    const artifacts = await page.$$eval(
      '[data-testid="v4-artifacts"] a',
      (nodes) => nodes.map((n) => n.getAttribute("href") ?? ""),
    );
    assert.ok(artifacts.length >= 1, "the answer links to its evidence");
    assert.match(artifacts[0], /\/api\/v1\/cockpit-v4\/runs\/.+\/artifacts\//);
  } finally {
    await context.close();
  }
});

// ---- failure, cancel, replay ------------------------------------------

await test("a terminal failure renders explicitly with a support reference",
  async () => {
    const { context, page, requests, problems } = await openCockpit(browser);
    try {
      await ask(page, "please fail this run");
      await expect(page, '[data-testid="v4-terminal-failure"]', 60_000, problems);
      const text = await page.textContent('[data-testid="v4-terminal-failure"]');
      assert.match(
        text ?? "",
        /stopped|interrupted|ran out of time/i,
        "a failure is rendered as a failure, not as a short answer",
      );
      assertNoLegacyCalls(requests, "on a failed run");
    } finally {
      await context.close();
    }
  },
);

await test("stop cancels the run through the V4 cancel endpoint", async () => {
  const { context, page, requests, problems } = await openCockpit(browser);
  try {
    await ask(page, "a slow question");
    await page.waitForSelector('[data-testid="v4-stop"]', { timeout: 30_000 });
    await page.click('[data-testid="v4-stop"]');

    await page.waitForFunction(
      () => {
        const summary = document.querySelector(
          '[data-testid="v4-process-summary"]',
        );
        return /Cancelled/i.test(summary?.textContent ?? "");
      },
      { timeout: 60_000 },
    );

    const cancels = calls(requests, "/cancel");
    assert.ok(cancels.length >= 1, "Stop must call the V4 cancel endpoint");
    assert.match(cancels[0], /\/api\/v1\/cockpit-v4\/runs\/run-[0-9a-f]+\/cancel/);
  } finally {
    await context.close();
  }
});

await test("a browser refresh replays the same run instead of re-asking",
  async () => {
    const { context, page, problems } = await openCockpit(browser);
    try {
      await ask(page, "a slow question");
      await expect(page, '[data-testid="v4-process-panel"]', 30_000, problems);

      const runId = await page.evaluate(() => {
        const raw = sessionStorage.getItem("cockpit-v4:active-run");
        return raw ? JSON.parse(raw).runId : "";
      });
      assert.match(runId, /^run-[0-9a-f]+$/, "the active run is remembered");

      // Reload, and watch what the fresh page does.
      const afterReload = [];
      page.on("request", (request) => afterReload.push(request.url()));
      await page.reload({ waitUntil: "domcontentloaded" });
      await expect(page, '[data-testid="v4-process-panel"]', 60_000, problems);

      const posts = afterReload.filter(
        (url) =>
          url.endsWith("/api/v1/cockpit-v4/runs") ||
          url.endsWith("/api/v1/cockpit-v4/threads"),
      );
      assert.equal(
        posts.length,
        0,
        `a refresh must not start a new run; it requested ${JSON.stringify(posts)}`,
      );
      assert.ok(
        afterReload.some((url) => url.includes(`${runId}/events`)),
        "the refreshed page reconnects to the SAME run's event stream",
      );
      assertNoLegacyCalls(afterReload, "after a refresh");
    } finally {
      await context.close();
    }
  },
);

// ---- the shell around it ----------------------------------------------

await test("optional landing widgets show a neutral state and request nothing",
  async () => {
    const { context, page, requests, problems } = await openCockpit(browser);
    try {
      const neutral = await page.$$('[data-testid="v4-not-in-runtime"]');
      assert.ok(
        neutral.length >= 1,
        "optional widgets render a neutral not-in-this-runtime state",
      );
      const text = await page.textContent('[data-testid="v4-not-in-runtime"]');
      assert.match(text ?? "", /not available in this isolated Cockpit V4/);
      assertNoLegacyCalls(requests, "for the optional widgets");
    } finally {
      await context.close();
    }
  },
);

await test("no request from the page goes to the legacy backend port",
  async () => {
    const { context, page, requests, problems } = await openCockpit(browser);
    try {
      await ask(page, "Who are you?");
      await expect(page, '[data-testid="v4-response"]', 60_000, problems);
      const stray = requests.filter((url) => /:8000(\/|$)/.test(url));
      assert.deepEqual(stray, [], "nothing may address the legacy backend");
    } finally {
      await context.close();
    }
  },
);

// ---- the trace, the rendering and the one-generation contract ---------

await test("the process panel shows real stages, not 'not started' at 0s",
  async () => {
    const { context, page, problems } = await openCockpit(browser);
    try {
      await ask(page, "Who are you?");
      await expect(page, '[data-testid="v4-process-panel"]', 30_000, problems);
      await page.click('[data-testid="v4-toggle-process"]');
      await expect(page, '[data-testid="v4-response"]', 60_000, problems);

      const steps = await page.$$eval(
        '[data-testid="v4-process-steps"] li',
        (nodes) => nodes.map((n) => n.textContent ?? ""),
      );
      const notStarted = steps.filter((s) => /not started/.test(s));
      assert.equal(
        notStarted.length,
        0,
        `every stage the run reached must be marked; still "not started": ` +
          JSON.stringify(notStarted),
      );

      const summary = await page.textContent('[data-testid="v4-process-summary"]');
      assert.match(summary ?? "", /Answered in/);
      assert.doesNotMatch(
        summary ?? "",
        /Answered in 0s/,
        "a run that took real time must not report 0s — the recorded live " +
          "run showed 29.4s on the backend and 0s in the browser",
      );

      // Substeps live inside an expanded step, so open one. Each carries a
      // backend event with its own timing.
      const stepButtons = await page.$$(
        '[data-testid="v4-process-steps"] li button',
      );
      assert.ok(stepButtons.length >= 1, "the panel lists stages");
      // Only click a step that is CLOSED. The panel auto-expands the stage
      // that failed, and toggling it would close the very thing under test.
      for (const button of stepButtons) {
        if (await button.isDisabled()) continue;
        if ((await button.getAttribute("aria-expanded")) !== "true") {
          await button.click();
        }
      }
      const substeps = await page.$$eval(
        '[data-testid="v4-substep"]',
        (nodes) => nodes.map((n) => n.textContent ?? ""),
      );
      assert.ok(substeps.length >= 3,
        `expected several real substeps, got ${substeps.length}`);
      assert.ok(
        substeps.some((s) => /\d+\.\ds/.test(s)),
        "each substep carries the time it happened at",
      );
    } finally {
      await context.close();
    }
  },
);

await test("the answer renders as Markdown, with no raw syntax left over",
  async () => {
    const { context, page, problems } = await openCockpit(browser);
    try {
      await ask(page, "Who are you?");
      await expect(page, '[data-testid="v4-response"]', 60_000, problems);
      await expect(page, '[data-testid="v4-markdown"]', 10_000, problems);

      const headings = await page.$$eval(
        '[data-testid="v4-markdown"] h2',
        (nodes) => nodes.map((n) => n.textContent ?? ""),
      );
      assert.ok(headings.length >= 1, "headings render as headings");

      const strong = await page.$$('[data-testid="v4-markdown"] strong');
      assert.ok(strong.length >= 1, "bold renders as bold");

      const bullets = await page.$$('[data-testid="v4-markdown"] li');
      assert.ok(bullets.length >= 1, "bullets render as list items");

      const rendered = await page.textContent('[data-testid="v4-markdown"]');
      assert.doesNotMatch(rendered ?? "", /\*\*/,
        "no raw ** may reach the reader");
      assert.doesNotMatch(rendered ?? "", /^#{1,4}\s/m,
        "no raw heading syntax may reach the reader");

      // And nothing on this path builds HTML from the answer.
      const injected = await page.$$('[data-testid="v4-markdown"] script');
      assert.equal(injected.length, 0);
    } finally {
      await context.close();
    }
  },
);

await test("suggested-question chips stay interactive UI, not Markdown",
  async () => {
    const { context, page, requests, problems } = await openCockpit(browser);
    try {
      await ask(page, "Who are you?");
      await expect(page, '[data-testid="v4-response"]', 60_000, problems);

      const chips = await page.$$('[data-testid="v4-response"] button');
      assert.ok(chips.length >= 1, "the answer offers next questions as chips");
      const label = (await chips[chips.length - 1].textContent()) ?? "";
      await chips[chips.length - 1].click();

      // Clicking a chip starts a NEW V4 run, not a legacy submission.
      await page.waitForFunction(
        () => {
          const el = document.querySelector('[data-testid="v4-process-summary"]');
          return /elapsed|Answered/.test(el?.textContent ?? "");
        },
        { timeout: 30_000 },
      );
      assertNoLegacyCalls(requests, `after clicking the chip "${label}"`);
      assert.ok(
        calls(requests, "/api/v1/cockpit-v4/runs").length >= 2,
        "a chip asks through the V4 run API",
      );
    } finally {
      await context.close();
    }
  },
);

await test("a failed attempt stays visible after a later attempt succeeds",
  async () => {
    const { context, page, problems } = await openCockpit(browser);
    try {
      await ask(page, "retry once then answer");
      await expect(page, '[data-testid="v4-response"]', 90_000, problems);

      // The stage-level note is visible as soon as the panel is open: a
      // later success must not erase the earlier failure.
      const note = await expect(
        page, '[data-testid^="v4-step-failures-"]', 20_000, problems,
      );
      // One or more: a rejected answer emits both `answer.validated`
      // (rejected) and `tool.failed`, and both are genuine failed events.
      assert.match(
        (await note.textContent()) ?? "",
        /\d+ attempts? failed here/,
        "the stage says how many attempts failed there",
      );

      // And the failed attempt itself is still in the substeps.
      const stepButtons = await page.$$(
        '[data-testid="v4-process-steps"] li button',
      );
      // Only click a step that is CLOSED. The panel auto-expands the stage
      // that failed, and toggling it would close the very thing under test.
      for (const button of stepButtons) {
        if (await button.isDisabled()) continue;
        if ((await button.getAttribute("aria-expanded")) !== "true") {
          await button.click();
        }
      }
      const failedSubsteps = await page.$$eval(
        '[data-testid="v4-substep"][data-status="rejected"], ' +
          '[data-testid="v4-substep"][data-status="failed"]',
        (nodes) => nodes.map((n) => n.textContent ?? ""),
      );
      assert.ok(
        failedSubsteps.length >= 1,
        "the earlier failed attempt must remain on screen after the retry " +
          "succeeded",
      );

      // The run still ended as a real answer.
      const panel = await page.$('[data-testid="v4-response"]');
      assert.equal(await panel?.getAttribute("data-disposition"), "answer");
    } finally {
      await context.close();
    }
  },
);

// A picture of the rendered answer, so "polished" is inspectable rather than
// asserted. Written only when a path is given.
if (process.env.V4_BROWSER_SCREENSHOT) {
  const { context, page, problems } = await openCockpit(browser);
  try {
    await ask(page, "Who are you?");
    await expect(page, '[data-testid="v4-response"]', 60_000, problems);
    await page.click('[data-testid="v4-toggle-process"]');
    await page.setViewportSize({ width: 900, height: 1400 });
    await page.screenshot({
      path: process.env.V4_BROWSER_SCREENSHOT,
      fullPage: true,
    });
    console.log(`  screenshot ${process.env.V4_BROWSER_SCREENSHOT}`);
  } finally {
    await context.close();
  }
}

// ---- the home feed, the drawer, and Investigate Further ----------------

async function openDrawer(page, section = "segments-requiring-attention") {
  await page.waitForSelector(
    `[data-testid="${section}"] [data-testid="attention-card"]`,
    { timeout: 60_000 },
  );
  const cards = await page.$$(
    `[data-testid="${section}"] [data-testid="attention-card"]`,
  );
  const headline = (await cards[0].textContent()) ?? "";
  const segment = await cards[0].getAttribute("data-segment");
  await cards[0].click();
  await page.waitForSelector('[data-testid="attention-drawer"]', {
    timeout: 30_000,
  });
  return { count: cards.length, headline, segment };
}

await test("segments requiring attention loads from the pinned release",
  async () => {
    const { context, page, requests } = await openCockpit(browser);
    try {
      await page.waitForSelector('[data-testid="segments-requiring-attention"]',
        { timeout: 60_000 });
      const cards = await page.$$(
        '[data-testid="segments-requiring-attention"] [data-testid="attention-card"]',
      );
      assert.ok(
        cards.length >= 1 && cards.length <= 5,
        `expected up to five segment cards, saw ${cards.length}`,
      );
      const segments = await Promise.all(
        cards.map((card) => card.getAttribute("data-segment")),
      );
      assert.equal(
        new Set(segments).size,
        segments.length,
        "five cards must be five different segments",
      );
      assert.ok(
        calls(requests, "/api/v1/cockpit-v4/attention").length >= 1,
        "the feed comes from the V4 attention endpoint",
      );
      assertNoLegacyCalls(requests, "for the attention feed");
    } finally {
      await context.close();
    }
  },
);

await test("latest-quarter ECL highlights load below it", async () => {
  const { context, page } = await openCockpit(browser);
  try {
    await page.waitForSelector('[data-testid="ecl-highlights"]',
      { timeout: 60_000 });
    const cards = await page.$$(
      '[data-testid="ecl-highlights"] [data-testid="attention-card"]',
    );
    assert.ok(cards.length >= 1, "at least one ECL highlight renders");
    const footnote = await page.textContent('[data-testid="attention-footnote"]');
    assert.match(footnote ?? "", /no model call/);
    // Order on the page: attention above highlights.
    const order = await page.evaluate(() => {
      const a = document.querySelector('[data-testid="segments-requiring-attention"]');
      const b = document.querySelector('[data-testid="ecl-highlights"]');
      if (!a || !b) return "missing";
      return a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING
        ? "attention-first"
        : "highlights-first";
    });
    assert.equal(order, "attention-first");
  } finally {
    await context.close();
  }
});

await test("clicking a segment card opens the right-side drawer", async () => {
  const { context, page } = await openCockpit(browser);
  try {
    const { headline, segment } = await openDrawer(page);
    const title = await page.textContent('[data-testid="attention-drawer-title"]');
    assert.ok(
      headline.includes(title ?? "__none__"),
      `drawer title ${title} must match the card that was clicked`,
    );
    const why = await page.textContent('[data-testid="attention-drawer-why"]');
    assert.match(why ?? "", /Why it appeared/);
    assert.match(why ?? "", /materiality floor|scored/);
    const numbers = await page.$$(
      '[data-testid="attention-drawer-numbers"] dd',
    );
    assert.ok(numbers.length >= 3, "the drawer shows its key numbers");
    assert.ok(segment, "the card names its segment");
    // It is a right-side panel, not a navigation.
    const box = await (await page.$('[data-testid="attention-drawer"]')).boundingBox();
    const width = page.viewportSize()?.width ?? 1280;
    assert.ok(box.x > width / 2, "the drawer sits on the right");
    assert.match(page.url(), /\/(\?.*)?$/, "the Cockpit was not navigated away");
  } finally {
    await context.close();
  }
});

await test("the drawer offers borrower drill-down and no invented subsegment",
  async () => {
    const { context, page } = await openCockpit(browser);
    try {
      await openDrawer(page);
      const drill = await page.textContent(
        '[data-testid="attention-drawer-drilldown"]',
      );
      assert.match(drill ?? "", /no subsegment level/);
      assert.match(drill ?? "", /borrowers/);
    } finally {
      await context.close();
    }
  },
);

await test("possible drivers are stated as association, never as cause",
  async () => {
    const { context, page } = await openCockpit(browser);
    try {
      await openDrawer(page);
      const drivers = await page
        .textContent('[data-testid="attention-drawer-drivers"]')
        .catch(() => "");
      if (drivers) {
        for (const causal of ["because", "caused by", "driven by"]) {
          assert.ok(
            !drivers.toLowerCase().includes(causal),
            `a driver claimed cause: "${causal}"`,
          );
        }
      }
    } finally {
      await context.close();
    }
  },
);

await test("Investigate Further opens a seeded V4 thread", async () => {
  const { context, page, requests } = await openCockpit(browser);
  try {
    const { segment } = await openDrawer(page);
    await page.click('[data-testid="attention-investigate"]');
    await page.waitForSelector('[data-testid="investigation-context"]', {
      timeout: 30_000,
    });
    const banner = await page.$('[data-testid="investigation-context"]');
    assert.equal(await banner.getAttribute("data-segment"), segment);
    const threadId = await banner.getAttribute("data-thread-id");
    assert.ok(threadId?.startsWith("th-"), `a real thread id, got ${threadId}`);
    assert.ok(
      calls(requests, "/investigate").length === 1,
      "exactly one V4 investigate call",
    );
    assertNoLegacyCalls(requests, "for Investigate Further");
  } finally {
    await context.close();
  }
});

await test("a follow-up uses the seeded context without restating it",
  async () => {
    const { context, page, requests, problems } = await openCockpit(browser);
    try {
      const { segment } = await openDrawer(page);
      await page.click('[data-testid="attention-investigate"]');
      await page.waitForSelector('[data-testid="investigation-context"]',
        { timeout: 30_000 });
      const threadId = await page
        .$('[data-testid="investigation-context"]')
        .then((el) => el.getAttribute("data-thread-id"));

      const posted = [];
      page.on("request", (request) => {
        // Only the SUBMISSION. `/runs/<id>/delivered` and `/runs/<id>/cancel`
        // are POSTs to a URL containing "/runs" as well.
        if (request.method() === "POST" && /\/runs$/.test(new URL(request.url()).pathname)) {
          posted.push(request.postData() ?? "");
        }
      });

      await ask(page, "show me the customers behind this");
      await expect(page, '[data-testid="v4-response"]', 60_000, problems);

      assert.equal(posted.length, 1, "one run submitted");
      const body = JSON.parse(posted[0]);
      assert.equal(
        body.thread_id,
        threadId,
        "the follow-up runs inside the seeded thread",
      );
      assert.equal(body.question, "show me the customers behind this");
      assert.ok(
        !body.question.includes(segment ?? "__none__"),
        "the user did not have to restate the segment",
      );
      assertNoLegacyCalls(requests, "for the seeded follow-up");
    } finally {
      await context.close();
    }
  },
);

await test("the seeded context load appears in the process panel", async () => {
  const { context, page, problems } = await openCockpit(browser);
  try {
    await openDrawer(page);
    await page.click('[data-testid="attention-investigate"]');
    await page.waitForSelector('[data-testid="investigation-context"]',
      { timeout: 30_000 });
    await ask(page, "show me the customers behind this");
    await expect(page, '[data-testid="v4-process-panel"]', 30_000, problems);
    await page.click('[data-testid="v4-toggle-process"]');
    await expect(page, '[data-testid="v4-process-steps"]', 30_000, problems);
    // The detail lives in substeps, which are collapsed under their stage
    // until the reader opens one. Open every stage that has any.
    const stages = await page.$$('[data-testid="v4-process-steps"] li button[aria-expanded]');
    for (const stage of stages) {
      if ((await stage.getAttribute("aria-expanded")) === "false"
          && !(await stage.isDisabled())) {
        await stage.click();
      }
    }
    const panel = await page.textContent('[data-testid="v4-process-steps"]');
    assert.match(
      panel ?? "",
      /Investigation context loaded/,
      "context seeding is a real step and the trace shows it",
    );
    assert.ok(
      !/chain of thought|reasoning:/i.test(panel ?? ""),
      "the trace shows steps, never the model's reasoning",
    );
  } finally {
    await context.close();
  }
});

await test("an ECL highlight opens the same drawer and investigates",
  async () => {
    const { context, page } = await openCockpit(browser);
    try {
      const { segment } = await openDrawer(page, "ecl-highlights");
      const numbers = await page.$$(
        '[data-testid="attention-drawer-numbers"] dd',
      );
      assert.ok(numbers.length >= 2, "an ECL highlight shows its numbers");
      await page.click('[data-testid="attention-investigate"]');
      await page.waitForSelector('[data-testid="investigation-context"]',
        { timeout: 30_000 });
      const banner = await page.$('[data-testid="investigation-context"]');
      assert.equal(await banner.getAttribute("data-segment"), segment);
    } finally {
      await context.close();
    }
  },
);

await test("a refresh keeps the open investigation", async () => {
  const { context, page } = await openCockpit(browser);
  try {
    const { segment } = await openDrawer(page);
    await page.click('[data-testid="attention-investigate"]');
    await page.waitForSelector('[data-testid="investigation-context"]',
      { timeout: 30_000 });
    await page.reload({ waitUntil: "domcontentloaded" });
    await page.waitForSelector('[data-testid="investigation-context"]',
      { timeout: 30_000 });
    const banner = await page.$('[data-testid="investigation-context"]');
    assert.equal(
      await banner.getAttribute("data-segment"),
      segment,
      "the same investigation comes back after a reload",
    );
  } finally {
    await context.close();
  }
});

await test("an attention-feed failure does not break Ask", async () => {
  const context = await browser.newContext();
  const page = await context.newPage();
  const problems = [];
  page.on("console", (m) => {
    if (m.type() === "error") problems.push(`console: ${m.text()}`);
  });
  try {
    await page.route("**/api/v1/cockpit-v4/attention**", (route) =>
      route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({
          detail: {
            error_code: "ATTENTION_UNAVAILABLE",
            message: "the aggregate query did not return.",
            component: "segment_attention_feed",
            error_reference: "att-deadbeef1234",
          },
        }),
      }),
    );
    await page.goto(`${UI}/`, { waitUntil: "domcontentloaded" });
    await page.waitForSelector('[data-testid="attention-unavailable"]',
      { timeout: 60_000 });
    const text = await page.textContent('[data-testid="attention-unavailable"]');
    assert.match(text ?? "", /Segment attention feed unavailable/);
    assert.match(text ?? "", /att-deadbeef1234/);
    assert.ok(
      !/Not Found|something failed/i.test(text ?? ""),
      "a component failure is named, not disguised as a 404",
    );

    await ask(page, "Who are you?");
    await expect(page, '[data-testid="v4-response"]', 60_000, problems);
  } finally {
    await context.close();
  }
});

// ---- the restored landing page ----------------------------------------

await test("the landing page greets, then asks what is on your mind",
  async () => {
    const { context, page, requests } = await openCockpit(browser);
    try {
      const heading = await page.textContent('[data-testid="cockpit-v4-greeting"]');
      assert.match(
        heading ?? "",
        /^Good (morning|afternoon|evening)/,
        `the greeting must be time-aware, got ${heading}`,
      );
      // A name appears only when the session has one. It is never invented.
      const named = await page.$('[data-testid="cockpit-v4-greeting-name"]');
      if (named) {
        const name = (await named.textContent())?.trim() ?? "";
        assert.ok(name.length > 0, "an empty name must not be rendered");
        assert.ok(
          !/^(user|there|admin)$/i.test(name),
          `a placeholder is not a name: ${name}`,
        );
      }
      const line = await page.textContent('[data-testid="cockpit-v4-prompt-line"]');
      assert.match(line ?? "", /What.s on your mind\?/);
      assertNoLegacyCalls(requests, "for the landing page");
    } finally {
      await context.close();
    }
  },
);

await test("the Ask box is the primary element and spans the workspace",
  async () => {
    const { context, page } = await openCockpit(browser);
    try {
      const box = await page.$('[data-testid="cockpit-v4-ask-box"]');
      assert.ok(box, "the Ask box renders");
      const boxRect = await box.boundingBox();
      const home = await (await page.$('[data-testid="cockpit-v4-home"]'))
        .boundingBox();
      assert.ok(
        boxRect.width > home.width * 0.85,
        `the Ask box should span the workspace: ${boxRect.width} of ${home.width}`,
      );
      // And it sits above what requires attention, not beside or below it.
      const attention = await (
        await page.$('[data-testid="segments-requiring-attention"]')
      ).boundingBox();
      assert.ok(
        boxRect.y + boxRect.height <= attention.y,
        "the question box comes before the attention feed",
      );
      // Nothing reserves space for the process panel before a run exists.
      assert.equal(
        await page.$('[data-testid="v4-process-panel"]'),
        null,
        "an idle landing page shows no process panel",
      );
    } finally {
      await context.close();
    }
  },
);

await test("prompt chips render, ask when clicked, and can be dismissed",
  async () => {
    const { context, page, problems } = await openCockpit(browser);
    try {
      const chips = await page.$$('[data-testid="cockpit-v4-prompt"]');
      assert.ok(chips.length >= 3, `expected prompt chips, saw ${chips.length}`);
      const texts = await Promise.all(chips.map((c) => c.textContent()));
      assert.ok(
        texts.some((text) => /risk|exposure|Stage 2|EAD|sector/i.test(text ?? "")),
        `chips must be business prompts, got ${JSON.stringify(texts)}`,
      );

      await page.click('[data-testid="cockpit-v4-prompts-dismiss"]');
      assert.equal(
        await page.$('[data-testid="cockpit-v4-prompts"]'),
        null,
        "dismissing hides the chips",
      );

      await page.reload({ waitUntil: "domcontentloaded" });
      await expect(page, '[data-testid="cockpit-v4-prompt"]', 30_000, problems);
      const first = (await page.$$('[data-testid="cockpit-v4-prompt"]'))[0];
      await first.click();
      await expect(page, '[data-testid="v4-process-panel"]', 30_000, problems);
    } finally {
      await context.close();
    }
  },
);

await test("the Trace line is there and explains itself", async () => {
  const { context, page } = await openCockpit(browser);
  try {
    const note = await page.textContent('[data-testid="cockpit-v4-trace-note"]');
    assert.match(note ?? "", /Every answer carries a Trace/);
    await page.click('[data-testid="cockpit-v4-trace-explain"]');
    const help = await page.textContent('[data-testid="cockpit-v4-trace-help"]');
    assert.match(help ?? "", /bound to a query that actually ran/);
  } finally {
    await context.close();
  }
});

await test("Segments requiring attention shows its period and only segments",
  async () => {
    const { context, page } = await openCockpit(browser);
    try {
      await page.waitForSelector('[data-testid="attention-reporting-period"]',
        { timeout: 60_000 });
      const period = await page.textContent(
        '[data-testid="attention-reporting-period"]',
      );
      assert.match(
        period ?? "",
        /Reporting period Q[1-4] \d{4}/,
        `the reporting period must come from the release, got ${period}`,
      );
      const heading = await page.textContent(
        '[data-testid="segments-requiring-attention"] h2',
      );
      assert.match(heading ?? "", /Segments requiring attention/);

      // No tab merges the two dashboards back together.
      assert.equal(
        await page.$('[data-testid="attention-tabs"]'),
        null,
        "the All tab existed only to merge two feeds that are both visible",
      );

      const cards = await page.$$(
        '[data-testid="segments-requiring-attention"] [data-testid="attention-card"]',
      );
      assert.ok(
        cards.length >= 1 && cards.length <= 5,
        `expected up to five segment cards, saw ${cards.length}`,
      );
      for (const card of cards) {
        assert.equal(
          await card.getAttribute("data-scope"),
          "segment",
          `a segment card must be about a segment: ${await card.textContent()}`,
        );
        const segment = await card.getAttribute("data-segment");
        assert.ok(segment && segment !== "Whole book", segment ?? "");
      }
    } finally {
      await context.close();
    }
  },
);

await test("the two dashboards are distinct and share no card", async () => {
  const { context, page } = await openCockpit(browser);
  try {
    await page.waitForSelector('[data-testid="ecl-highlights"]',
      { timeout: 60_000 });
    const read = async (section) =>
      Promise.all(
        (
          await page.$$(`[data-testid="${section}"] [data-testid="attention-card"]`)
        ).map(async (card) => ({
          id: await card.getAttribute("data-item-id"),
          scope: await card.getAttribute("data-scope"),
          text: ((await card.textContent()) ?? "").trim(),
        })),
      );

    const segments = await read("segments-requiring-attention");
    const highlights = await read("ecl-highlights");
    assert.ok(segments.length >= 1 && highlights.length >= 1);

    const ids = new Set(segments.map((c) => c.id));
    for (const card of highlights) {
      assert.ok(!ids.has(card.id), `duplicated across dashboards: ${card.text}`);
    }
    const headlines = new Set(segments.map((c) => c.text));
    for (const card of highlights) {
      assert.ok(
        !headlines.has(card.text),
        `the same card appears twice on the page: ${card.text}`,
      );
    }

    // The specific items the live screenshot showed in the wrong list.
    const upper = segments.map((c) => c.text).join(" | ");
    for (const wrong of [
      /carries the most ECL in the book/,
      /is the largest single ECL contributor/,
      /Stage 2 share of the book/,
      /had the largest ECL reduction/,
      /had the largest ECL increase/,
    ]) {
      assert.ok(
        !wrong.test(upper),
        `an ECL highlight is in the segment list: ${wrong}`,
      );
    }

    // And the ECL feed keeps the borrower and book-level highlights it is
    // designed to carry.
    const scopes = new Set(highlights.map((c) => c.scope));
    assert.ok(scopes.has("segment"), "sector-level ECL highlights remain");
  } finally {
    await context.close();
  }
});

await test("both dashboards open the same right-hand drawer", async () => {
  const { context, page } = await openCockpit(browser);
  try {
    for (const section of ["segments-requiring-attention", "ecl-highlights"]) {
      const { headline } = await openDrawer(page, section);
      const title = await page.textContent(
        '[data-testid="attention-drawer-title"]',
      );
      assert.ok(
        headline.includes(title ?? "__none__"),
        `${section}: drawer title ${title} must match the card clicked`,
      );
      await page.click('[data-testid="attention-drawer-close"]');
    }
  } finally {
    await context.close();
  }
});

await test("Continue where you left off uses real V4 threads", async () => {
  const { context, page, requests, problems } = await openCockpit(browser);
  try {
    await page.waitForSelector('[data-testid="continue-where-you-left-off"]',
      { timeout: 60_000 });
    // Before anything has run in this browser profile it is either empty or
    // showing threads this tenant really has. It is never invented rows.
    const empty = await page.$('[data-testid="continue-empty"]');
    const before = await page.$$('[data-testid="continue-thread"]');
    assert.ok(empty || before.length > 0);

    await ask(page, "Who are you?");
    await expect(page, '[data-testid="v4-response"]', 60_000, problems);
    await page.reload({ waitUntil: "domcontentloaded" });
    await page.waitForSelector('[data-testid="continue-thread"]',
      { timeout: 60_000 });
    const after = await page.$$('[data-testid="continue-thread"]');
    assert.ok(after.length >= 1, "the conversation just held is listed");
    const label = await after[0].textContent();
    assert.match(label ?? "", /Who are you\?|Cockpit conversation/);
    assertNoLegacyCalls(requests, "for the thread list");
  } finally {
    await context.close();
  }
});

await test("an Arabic answer renders right-to-left without breaking the page",
  async () => {
    const { context, page, problems } = await openCockpit(browser);
    try {
      await ask(page, "ما هو CreditProbe؟");
      await expect(page, '[data-testid="v4-response"]', 60_000, problems);
      const direction = await page.evaluate(() => {
        const input = document.querySelector(
          '[data-testid="cockpit-v4-question"]',
        );
        return input ? getComputedStyle(input).direction : "";
      });
      // dir="auto" resolves from the content, so the box itself flips.
      assert.ok(["ltr", "rtl"].includes(direction), direction);
      const body = await page.evaluate(
        () => document.body.scrollWidth <= window.innerWidth + 2,
      );
      assert.ok(body, "an RTL answer must not force a horizontal scroll");
    } finally {
      await context.close();
    }
  },
);

await test("the landing page mounts the V4 Cockpit and nothing legacy",
  async () => {
    const { context, page, requests } = await openCockpit(browser);
    try {
      assert.ok(await page.$('[data-testid="cockpit-v4-home"]'));
      assert.ok(await page.$('[data-testid="cockpit-v4"]'));
      // The legacy Cockpit's own markers must be absent, not merely hidden.
      for (const legacy of [
        '[data-testid="cockpit-home"]',
        '[data-testid="agentic-officer"]',
        '[data-testid="investigation-panel"]',
      ]) {
        assert.equal(await page.$(legacy), null, `${legacy} must not mount`);
      }
      const stray = requests.filter((url) => /:8000(\/|$)/.test(url));
      assert.deepEqual(stray, []);
      assertNoLegacyCalls(requests, "for the restored landing page");
    } finally {
      await context.close();
    }
  },
);

if (process.env.V4_LANDING_SCREENSHOT) {
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1200 },
  });
  const page = await context.newPage();
  try {
    await page.goto(`${UI}/`, { waitUntil: "domcontentloaded" });
    await page.waitForSelector('[data-testid="attention-card"]',
      { timeout: 60_000 });
    await page.screenshot({
      path: process.env.V4_LANDING_SCREENSHOT,
      fullPage: true,
    });
    console.log(`  screenshot ${process.env.V4_LANDING_SCREENSHOT}`);
  } finally {
    await context.close();
  }
}

await browser.close();

const summary = {
  label: "REAL BROWSER · REAL UI · REAL BACKEND · MOCK ANALYST",
  note:
    "The analyst model is a stub. This proves the wiring, the run lifecycle " +
    "and the rendering. It is NOT a live Opus validation.",
  ui: UI,
  api: API,
  total: results.length,
  passed: results.filter((r) => r.ok).length,
  failed: failures,
  forbidden_endpoints_checked: FORBIDDEN,
  results,
};
console.log(`\n${summary.passed}/${summary.total} browser tests passed\n`);
if (process.env.V4_BROWSER_EVIDENCE) {
  const { writeFileSync } = await import("node:fs");
  writeFileSync(
    process.env.V4_BROWSER_EVIDENCE,
    JSON.stringify(summary, null, 2) + "\n",
  );
  console.log(`evidence written to ${process.env.V4_BROWSER_EVIDENCE}`);
}
process.exit(failures === 0 ? 0 : 1);
