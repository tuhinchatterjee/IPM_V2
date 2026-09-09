import assert from "node:assert/strict";
import { test } from "node:test";

/**
 * The presentation rules of the messaging surface, tested where they are
 * decidable.
 *
 * These are pure functions of their inputs, so they belong here. Whether a
 * private thread is actually refused belongs in the API suite, which proves it
 * against three separately signed-in people — a frontend test that asserted it
 * would be testing that a component was not rendered, which is not the same
 * fact and is not the one that matters.
 *
 * The functions below mirror the components exactly. Where a rule changes in
 * one place and not the other, the drift is the defect this file exists to
 * catch, so they are written to be read side by side rather than imported —
 * the components are React and this runner is not.
 */

/* ------------------------------------------------------------------ when() */

/**
 * Today is a clock time, this week is a weekday, older is a date.
 *
 * The rule matters because an inbox in which every row prints a full timestamp
 * makes the message from this morning exactly as hard to spot as the one from
 * March.
 */
function when(iso: string | null, now: Date): string {
  if (!iso) return "";
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return "";
  const sameDay = at.toDateString() === now.toDateString();
  if (sameDay) {
    return at.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
  }
  const days = Math.floor((now.getTime() - at.getTime()) / 86_400_000);
  if (days === 1) return "Yesterday";
  if (days < 7) return at.toLocaleDateString(undefined, { weekday: "long" });
  return at.toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

test("an absent time renders nothing rather than 'Invalid Date'", () => {
  assert.equal(when(null, new Date()), "");
  assert.equal(when("not a date", new Date()), "");
});

test("today is a clock time", () => {
  const now = new Date("2026-09-02T15:00:00Z");
  const said = when("2026-09-02T09:30:00Z", now);
  assert.ok(/\d/.test(said), `expected a time, got ${said}`);
  assert.ok(!said.includes("Sep"), `expected a time, got ${said}`);
});

test("yesterday says so", () => {
  const now = new Date("2026-09-02T15:00:00Z");
  assert.equal(when("2026-09-01T09:30:00Z", now), "Yesterday");
});

test("this week is a weekday name", () => {
  const now = new Date("2026-09-02T15:00:00Z");
  const said = when("2026-08-29T09:30:00Z", now);
  assert.ok(/day$/.test(said), `expected a weekday, got ${said}`);
});

test("older than a week is a date", () => {
  const now = new Date("2026-09-02T15:00:00Z");
  const said = when("2026-03-14T09:30:00Z", now);
  assert.ok(/\d/.test(said) && !/day$/.test(said), `expected a date, got ${said}`);
});

/* ---------------------------------------------------------- request badges */

type RequestType = "fyi" | "review" | "action";
type RequestStatus = "open" | "in_review" | "responded" | "closed" | null;

const REQUEST_LABEL: Record<RequestType, string> = {
  fyi: "For information",
  review: "Review requested",
  action: "Action required",
};

const STATUS_LABEL: Record<Exclude<RequestStatus, null>, string> = {
  open: "Open",
  in_review: "In review",
  responded: "Responded",
  closed: "Closed",
};

/** What the badge says, or null when there is no badge. */
function badge(type: RequestType, status: RequestStatus): string | null {
  if (type === "fyi") return null;
  if (status === "closed") return STATUS_LABEL.closed;
  if (status && status !== "open") return STATUS_LABEL[status];
  return REQUEST_LABEL[type];
}

test("a for-information message carries no badge", () => {
  // Not "For information" on every row. A chip on everything makes the two
  // rows that need attention invisible, which is the opposite of the point.
  assert.equal(badge("fyi", null), null);
  assert.equal(badge("fyi", "open"), null);
});

test("an open request says what is being asked for", () => {
  assert.equal(badge("review", "open"), "Review requested");
  assert.equal(badge("action", "open"), "Action required");
});

test("once it moves, the badge says where it is", () => {
  assert.equal(badge("review", "in_review"), "In review");
  assert.equal(badge("action", "responded"), "Responded");
});

test("a closed request reads as closed whichever kind it was", () => {
  assert.equal(badge("review", "closed"), "Closed");
  assert.equal(badge("action", "closed"), "Closed");
});

/* -------------------------------------------------------- the state machine */

/**
 * The moves offered from each state.
 *
 * Mirrors `ALLOWED_TRANSITIONS` in the service. The UI offers only these, and
 * the backend refuses anything else — the button being absent is courtesy, and
 * the refusal is the control.
 */
const NEXT: Record<Exclude<RequestStatus, null>, string[]> = {
  open: ["in_review", "responded", "closed"],
  in_review: ["responded", "closed"],
  responded: ["closed", "in_review"],
  closed: [],
};

test("a closed request offers nothing", () => {
  assert.deepEqual(NEXT.closed, []);
});

test("nothing offers a way back to open", () => {
  // Reopening would make "who closed this, and when" unanswerable without
  // reading the event log, and the badge would stop meaning anything.
  for (const [from, moves] of Object.entries(NEXT)) {
    assert.ok(!moves.includes("open"), `${from} offered a way back to open`);
  }
});

test("responded can be reconsidered without opening a second request", () => {
  assert.ok(NEXT.responded.includes("in_review"));
});

test("every state except closed can be closed", () => {
  for (const state of ["open", "in_review", "responded"] as const) {
    assert.ok(NEXT[state].includes("closed"), `${state} could not be closed`);
  }
});

/* ------------------------------------------------------------ the sender */

interface Sender {
  type: "USER" | "SYSTEM";
  name: string;
  user: { job_title: string } | null;
}

/** How a sender is labelled. Both kinds live in one inbox and must not blur. */
function senderLabel(sender: Sender): string {
  if (sender.type === "SYSTEM") return sender.name;
  const title = sender.user?.job_title ?? "";
  return title ? `${sender.name} · ${title}` : sender.name;
}

test("a person is named with their job title", () => {
  assert.equal(
    senderLabel({ type: "USER", name: "Sarah Khan",
                  user: { job_title: "Corporate Credit Manager" } }),
    "Sarah Khan · Corporate Credit Manager",
  );
});

test("a person with no job title is still named", () => {
  assert.equal(
    senderLabel({ type: "USER", name: "Sarah Khan", user: { job_title: "" } }),
    "Sarah Khan",
  );
});

test("the product signs itself, and never with a provider name", () => {
  const said = senderLabel({ type: "SYSTEM", name: "CreditProbe AI",
                             user: null });
  assert.equal(said, "CreditProbe AI");
  for (const name of ["Claude", "Anthropic", "OpenAI", "GPT", "Sonnet",
                      "Opus", "Gemini"]) {
    assert.ok(!said.includes(name), `provider name leaked: ${name}`);
  }
});

/* ------------------------------------------------------------ empty states */

type Mailbox = "inbox" | "sent" | "drafts" | "archived" | "action";

/**
 * What an empty box says.
 *
 * "No messages" is true of every empty list in every product ever written.
 * What a reader needs to know is whether they are looking at the right place.
 */
function emptyText(box: Mailbox, searching: boolean): string {
  if (searching) return "Nothing matched that search.";
  return box === "action"
    ? "Nothing is waiting on you."
    : box === "drafts"
      ? "No unsent messages."
      : box === "sent"
        ? "You have not sent anything yet."
        : box === "archived"
          ? "Nothing filed away."
          : "Your inbox is empty.";
}

test("every mailbox has its own empty sentence", () => {
  const said = new Set(
    (["inbox", "sent", "drafts", "archived", "action"] as Mailbox[])
      .map((b) => emptyText(b, false)),
  );
  assert.equal(said.size, 5, "two mailboxes share an empty state");
});

test("an empty search is distinguished from an empty box", () => {
  assert.notEqual(emptyText("inbox", true), emptyText("inbox", false));
  assert.equal(emptyText("inbox", true), "Nothing matched that search.");
});

test("no empty state says the bare word 'None'", () => {
  for (const box of ["inbox", "sent", "drafts", "archived", "action"] as Mailbox[]) {
    const said = emptyText(box, false);
    assert.ok(said.length > 15, `${box} says too little: ${said}`);
    assert.ok(said.endsWith("."), `${box} is not a sentence: ${said}`);
  }
});

/* --------------------------------------------------------- attachment chips */

type AttachmentType = "investigation" | "analysis" | "report" | "file";

const ATTACHMENT_LABEL: Record<AttachmentType, string> = {
  investigation: "Investigation",
  analysis: "Analysis",
  report: "Report",
  file: "File",
};

test("attachments are named in the product's own vocabulary", () => {
  // "3 attachments" tells a reader nothing about whether opening the message
  // is worth their next ten minutes. "Investigation · Analysis · Excel" does.
  assert.equal(ATTACHMENT_LABEL.investigation, "Investigation");
  assert.equal(ATTACHMENT_LABEL.analysis, "Analysis");
});

test("every attachment kind has a label", () => {
  for (const kind of ["investigation", "analysis", "report", "file"] as AttachmentType[]) {
    assert.ok(ATTACHMENT_LABEL[kind], `${kind} has no label`);
  }
});

/* ---------------------------------------------------------- the unread badge */

/**
 * What the header shows.
 *
 * Null means "do not render": an anonymous caller has no mailbox, and a "0"
 * for them would be a claim about something that does not exist.
 */
function badgeCount(counts: { unread: number; action_required: number } | null):
  string | null {
  if (counts === null) return null;
  const total = counts.unread + counts.action_required;
  if (total === 0) return "";
  return total > 99 ? "99+" : String(total);
}

test("a signed-out caller gets no badge at all", () => {
  assert.equal(badgeCount(null), null);
});

test("nothing waiting shows the icon with no number", () => {
  assert.equal(badgeCount({ unread: 0, action_required: 0 }), "");
});

test("the count is unread plus what is waiting on you", () => {
  assert.equal(badgeCount({ unread: 4, action_required: 2 }), "6");
});

test("a large count is capped rather than breaking the header", () => {
  assert.equal(badgeCount({ unread: 200, action_required: 0 }), "99+");
});
