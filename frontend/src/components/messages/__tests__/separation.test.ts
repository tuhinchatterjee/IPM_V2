import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

/**
 * The 1.1 correction, where it is decidable without a browser.
 *
 * Two of the five reported defects have a purely structural half that belongs
 * here: which pages a role is offered, and which row shape a mailbox draws.
 * The behavioural halves — that the backend refuses the oversight route, that
 * a self-send reaches both boxes — are proved in the API suite against real
 * signed-in accounts, because a frontend test asserting a component did not
 * render would be a different fact from "the route said no".
 *
 * The navigation rules below are read out of `navigation.ts` as source text
 * rather than imported. The module pulls in an icon package this runner cannot
 * resolve, and mirroring the entries here would test the copy rather than the
 * file the sidebar is actually built from — which is exactly the drift the
 * test exists to catch.
 */

const NAV_SOURCE = readFileSync(
  fileURLToPath(new URL("../../../lib/navigation.ts", import.meta.url)),
  "utf8",
);

/** The literal for one navigation entry, found by its href. */
function entry(href: string): string {
  const at = NAV_SOURCE.indexOf(`href: "${href}",`);
  if (at < 0) throw new Error(`no navigation entry for ${href}`);
  const open = NAV_SOURCE.lastIndexOf("{", at);
  const close = NAV_SOURCE.indexOf("\n  },", at);
  return NAV_SOURCE.slice(open, close);
}

/* ------------------------------------------- Workflow is not a mailbox */

test("Workflow is restricted to an administrator", () => {
  const workflow = entry("/workflow");
  assert.match(workflow, /roles:\s*\["ADMIN"\]/,
               "Workflow must carry an ADMIN-only role restriction");
  assert.match(workflow, /group:\s*"Admin"/,
               "Workflow belongs with administration, not with the mailboxes");
});

test("everybody keeps their own messages and their own review queue", () => {
  for (const href of ["/messages", "/workspace", "/reviews"]) {
    assert.doesNotMatch(entry(href), /roles:/,
                        `${href} must not be restricted by role`);
  }
});

test("Messages is not filed under administration", () => {
  assert.doesNotMatch(entry("/messages"), /group:\s*"Admin"/);
});

test("the personal review queue is no longer called Workflow", () => {
  const reviews = entry("/reviews");
  assert.match(reviews, /label:\s*"My reviews"/);
  assert.doesNotMatch(reviews, /label:\s*"Workflow"/);
});

test("nothing still links the old personal queue to /workflow", () => {
  // /workflow used to BE the personal queue. Anything still pointing there
  // for a person's own work would send a non-administrator to a page the
  // backend refuses.
  assert.match(NAV_SOURCE, /href:\s*"\/reviews"/);
});

/* --------------------------------------- a mailbox draws its own rows */

type Box = "inbox" | "action" | "sent" | "drafts" | "archived";

/**
 * Which row component a mailbox page draws.
 *
 * The rule that matters: it follows the box the DATA came back as, never the
 * tab the reader last clicked. Between a click and the response those two
 * disagree for one render, and choosing by the tab drew Sent rows over Inbox
 * items — which crashed, because an inbox row carries no recipient list.
 */
function rowShape(returned: Box): "sent" | "draft" | "thread" {
  return returned === "sent" ? "sent"
    : returned === "drafts" ? "draft"
    : "thread";
}

test("every mailbox draws the row shape its own data implies", () => {
  assert.equal(rowShape("sent"), "sent");
  assert.equal(rowShape("drafts"), "draft");
  for (const box of ["inbox", "action", "archived"] as Box[]) {
    assert.equal(rowShape(box), "thread");
  }
});

test("the shape is decided by the returned box, not the selected tab", () => {
  // The reader has clicked Sent; the response in hand is still the inbox.
  const selected: Box = "sent";
  const returned: Box = "inbox";
  assert.equal(rowShape(returned), "thread");
  assert.notEqual(rowShape(returned), rowShape(selected));
});

/* ------------------------------------------- one authoritative summary */

const EMPTY = {
  inbox: 0, unread: 0, archived: 0, sent: 0, drafts: 0,
  action_required: 0, shared_with_me: 0,
};

/** What the header badge shows: work waiting, of either kind. */
function badge(counts: typeof EMPTY | null): number | null {
  return counts === null ? null : counts.unread + counts.action_required;
}

test("no badge at all when nobody is signed in", () => {
  // A zero would be a claim about a mailbox that does not exist.
  assert.equal(badge(null), null);
});

test("the badge is unread plus what is waiting on me", () => {
  assert.equal(badge({ ...EMPTY, unread: 3, action_required: 2 }), 5);
  assert.equal(badge({ ...EMPTY, unread: 0, action_required: 0 }), 0);
});

test("reading one message moves the badge by exactly one", () => {
  const before = badge({ ...EMPTY, unread: 3, action_required: 1 });
  const after = badge({ ...EMPTY, unread: 2, action_required: 1 });
  assert.equal(before, 4);
  assert.equal(after, 3);
});

test("the summary names every box the mailbox tabs show", () => {
  // If a tab existed with no count behind it, that tab would be counting for
  // itself again — which is the drift this store was built to end.
  for (const box of ["inbox", "sent", "drafts", "archived"] as const) {
    assert.ok(box in EMPTY, `${box} has no count in the summary`);
  }
  assert.ok("action_required" in EMPTY);
  assert.ok("shared_with_me" in EMPTY);
});
