import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

/**
 * A refusal is not a failure, and neither is silence.
 *
 * The defect these hold
 * ---------------------
 * A route crawl across ADMIN, ANALYST and VIEWER found seven failing visits.
 * Six were one defect wearing six hats: a role the backend correctly refused
 * saw either a red error card — the product claiming to be broken when the
 * permission model was working — or, worse, nothing at all. On What-If,
 * `configuration.data?.scenarios ?? []` turned a 403 into an empty dropdown
 * and left the reader on a page with no scenarios, no explanation and no next
 * step. That is a dead end, which the product contract forbids.
 *
 * Two of the six had a second cause underneath: the acting role reads as
 * Administrator until hydration settles, so an admin-only fetch left the
 * browser once for every Analyst and Viewer, and came back 403 from a page
 * that then correctly told them they were not an administrator. The refusal
 * was right. The request should never have been made.
 *
 * Structural tests, deliberately. These are claims about what the code is
 * wired to do on a status the test environment cannot produce without a
 * running backend and three sessions. What silently rots is the wiring —
 * somebody re-adds a `?? []` and the dead end comes back — and that is what
 * fails here.
 */

const root = fileURLToPath(new URL("../../", import.meta.url));
const read = (path: string) => readFileSync(root + path, "utf8");

// ---------------------------------------------------------- the mechanism

test("the fetch hook carries the refusal, not just a message", () => {
  const hooks = read("lib/hooks.ts");

  // Flattening every failure into one string is what made a refusal
  // indistinguishable from a breakage at every call site.
  assert.match(hooks, /refused: boolean/);
  assert.match(hooks, /status: number/);

  // 403 and nothing else. A 401 is "sign in", a 404 is "not here"; neither
  // is the permission model refusing a role that IS signed in.
  assert.match(hooks, /phase\.code === 403/);
});

test("the refusal panel says which panel, and does not dress it as an error", () => {
  const panel = read("components/ui/unavailable.tsx");

  // Named subject. "You do not have permission to do this" without one is
  // its own small dead end on a page with several panels.
  assert.match(panel, /Your role does not have access to \$\{what\}/);

  // A refusal reads neutral; a failure reads negative. Same component, two
  // registers, because they are acted on by different people.
  assert.ok(panel.includes("bg-surface-raised"), "a refusal is not styled red");
  assert.ok(panel.includes("border-negative/40"), "a real failure still is");

  // The server's own sentence, not a second opinion invented here.
  assert.match(panel, /\{state\.error\}/);

  // And it stays out of the way when there is nothing to say.
  assert.match(panel, /if \(state\.loading \|\| !state\.error\) return null/);
});

// ------------------------------------------------- the six refused screens

test("What-If states a refused configuration instead of emptying the page", () => {
  const stress = read("app/stress/page.tsx");

  assert.match(stress, /<Unavailable state=\{configuration\}/);

  // Above the controls it explains, not below the results nobody got.
  const stated = stress.indexOf("<Unavailable");
  const controls = stress.indexOf("Configured scenario");
  assert.ok(stated > 0 && stated < controls,
    "the refusal must come before the controls it explains");
});

test("the CRO lens states one refusal, not seven", () => {
  const lens = read("app/lenses/cro/page.tsx");
  const stated = lens.match(/<Unavailable/g) ?? [];
  assert.equal(stated.length, 1,
    "seven analyses share one permission; seven copies of the refusal is noise");
});

test("Regulatory Intelligence distinguishes a refusal from a breakage", () => {
  const page = read("app/studio/regulatory-intelligence/page.tsx");

  assert.match(page, /error instanceof ApiError && error\.isForbidden/);
  assert.match(page, /<Unavailable/);

  // A refusal on one tab must not outlive the tab it belongs to.
  assert.match(page, /failed\.tab === tab/);
});

// ------------------------------- the request that should never have been made

test("an admin-only panel waits for the role to settle before asking", () => {
  const roles = read("components/system/role-switcher.tsx");

  // The hydration render has to answer with something, and the something is
  // Administrator. `settled` is how a caller knows not to believe it yet.
  assert.match(roles, /settled: boolean/);
  assert.match(roles, /getServerSnapshot/);

  for (const path of [
    "app/early-warning/lab/page.tsx",
    "app/users/page.tsx",
    "components/system/cost-trace.tsx",
  ]) {
    const source = read(path);
    assert.match(source, /settled && role === "ADMIN"/,
      `${path} must not fire its admin-only fetch before the role settles`);
  }
});

test("Brain Center distinguishes a refusal from a breakage", () => {
  const page = read("app/ai-studio/brain-center/page.tsx");

  // Found only once the crawl started impersonating roles honestly. The same
  // shape as Regulatory Intelligence, and it was hidden for the same reason:
  // the crawl set the role header and left the app believing it was ADMIN,
  // so this panel was never visited as anyone who would be refused.
  assert.match(page, /error instanceof ApiError && error\.isForbidden/);
  assert.match(page, /<Unavailable/);
  assert.match(page, /failed\.tab === tab/);
});

test("the cost trace explains itself to a role that cannot open it", () => {
  const trace = read("components/system/cost-trace.tsx");

  // Not asking is quieter AND more honest — but a panel that simply goes
  // blank is the dead end again, so the sentence stays.
  assert.match(trace, /available to administrators only/);
  assert.match(trace, /nothing here failed to load/);
});
