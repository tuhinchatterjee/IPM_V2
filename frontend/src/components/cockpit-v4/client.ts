/**
 * The V4 browser client: start, watch, reconnect, cancel, acknowledge.
 *
 * Two rules this file exists to keep.
 *
 * A disconnect does not cancel paid work, and a reconnect never resubmits the
 * question. `watch` reconnects to the SAME run with the last sequence it saw
 * and replays the committed events it missed. There is no path here that
 * POSTs /runs again because a stream dropped.
 *
 * Connection loss is a CLIENT state. After the bounded reconnect attempts are
 * spent, the panel shows CONNECTION_LOST with the last stage it actually saw
 * and offers a status re-read. It never renders that as a server failure,
 * because it does not know that the server failed.
 */

export type RunEvent = {
  schema_version: string;
  event_id: string;
  run_id: string;
  seq: number;
  event_type: string;
  stage: string;
  operation: string;
  status: "started" | "ok" | "failed" | "rejected";
  occurred_at: string;
  elapsed_ms: number;
  attempt: number;
  submission: number;
  round: number;
  public_message: string;
  detail_ref: string;
  error_id: string;
  trace_id: string;
  span_id: string;
  parent_span_id: string;
};

export type RunStatus = {
  run_id: string;
  thread_id: string;
  state: string;
  mode: string;
  release_id: string;
  error_code: string;
  error_id: string;
  operation: string;
  final_response: FinalResponse | null;
  budget: Record<string, unknown>;
  terminal: boolean;
  last_event_seq: number;
  delivered_at: string;
};

export type FinalResponse = {
  disposition:
    | "answer"
    | "partial_answer"
    | "referral"
    | "clarification"
    | "unsupported"
    | "safe_failure";
  narrative: string;
  intent: { query_mode: string; owner: string; understood_request: string };
  coverage: { subquestion: string; status: string }[];
  numeric_claims: {
    claim_id: string;
    decimal_value: string;
    unit: string;
    display_precision: number;
    /** Present on a DIRECT claim: the one result cell it was read from. */
    evidence?: { artifact_id: string; row_key: string; column_id: string };
    /** Present on a DERIVED claim -- a total, a share, a movement. The
     *  server recomputed this value from the cells named here before the
     *  answer was allowed to publish. */
    derivation?: {
      operation: string;
      operands: { artifact_id: string; column_id: string; row_ids: string[] }[];
    };
  }[];
  tables: { title: string; artifact_id: string; columns: string[] }[];
  charts: unknown[];
  limitations: string[];
  suggested_questions: { question: string; kind: string }[];
  clarification_question: string;
  clarification_options: string[];
  referral_owner: string;
  referral_reason: string;
  executed: boolean;
  validation?: { warnings: string[] };
};

export const API_PREFIX = "/api/v1/cockpit-v4";

/**
 * Every event type the backend emits, by name.
 *
 * This list is load-bearing, not documentation. The server sends NAMED SSE
 * frames (`event: run.accepted`), and `EventSource.onmessage` fires only for
 * frames whose name is `message` or absent. Without a listener per name the
 * browser silently discards every analytical event and keeps only the ones it
 * was explicitly told to listen for — which is exactly how a run with fifteen
 * correctly persisted events rendered as "Answered in 0s" with every stage
 * still marked "not started".
 *
 * Kept in step with `backend/cockpit_v4/events.py:EVENT_TYPES`; a test
 * asserts the two agree, so a new backend event cannot go unrendered.
 */
export const EVENT_TYPES = [
  "run.accepted",
  "run.started",
  "context.ready",
  "model.requested",
  "model.response_received",
  "model.parsed",
  "intent.validated",
  "tool.requested",
  "tool.validated",
  "tool.started",
  "tool.completed",
  "tool.failed",
  "retry.requested",
  "answer.validated",
  "answer.ready",
  // The analysis finished and its result was kept, but the written answer
  // could not be published. Distinct from run.failed so the panel does not
  // report a successful query as a failed one.
  "analysis.preserved",
  "run.failed",
  "run.cancelled",
  "run.expired",
  "run.interrupted",
  "memory.started",
  "memory.completed",
  "memory.failed",
] as const;

export type RunMode = "standard" | "deep";

/**
 * Where the active run is remembered across a refresh.
 *
 * A run is durable on the server; reloading the page must not orphan it. The
 * id and the last sequence the browser actually rendered are kept here, so a
 * refresh reconnects to the SAME run from where it left off rather than
 * re-asking the question and paying for it twice.
 *
 * `sessionStorage` rather than `localStorage`: this is about one tab's current
 * work, and a second tab opening onto a run it never started would show
 * progress the reader did not ask for.
 */
const ACTIVE_RUN_KEY = "cockpit-v4:active-run";

export type ActiveRun = { runId: string; threadId: string; cursor: number };

export function rememberRun(run: ActiveRun): void {
  try {
    sessionStorage.setItem(ACTIVE_RUN_KEY, JSON.stringify(run));
  } catch {
    /* a browser that refuses storage loses replay, not the run */
  }
}

export function recallRun(): ActiveRun | null {
  try {
    const raw = sessionStorage.getItem(ACTIVE_RUN_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<ActiveRun>;
    if (typeof parsed.runId !== "string" || !parsed.runId) return null;
    return {
      runId: parsed.runId,
      threadId: typeof parsed.threadId === "string" ? parsed.threadId : "",
      cursor: typeof parsed.cursor === "number" ? parsed.cursor : 0,
    };
  } catch {
    return null;
  }
}

export function forgetRun(): void {
  try {
    sessionStorage.removeItem(ACTIVE_RUN_KEY);
  } catch {
    /* nothing to clean up */
  }
}

/**
 * Where an open investigation is remembered across a refresh.
 *
 * The SEED lives on the server, attached to the thread; this is only the
 * pointer to it, so a reload comes back to the same conversation instead of
 * dropping the reader into a blank Ask box after they clicked a card.
 */
const ACTIVE_INVESTIGATION_KEY = "cockpit-v4:active-investigation";

export type RememberedInvestigation = {
  threadId: string;
  itemId: string;
  suggested: string[];
};

export function rememberInvestigation(open: RememberedInvestigation): void {
  try {
    sessionStorage.setItem(ACTIVE_INVESTIGATION_KEY, JSON.stringify(open));
  } catch {
    /* a browser that refuses storage loses the banner, not the thread */
  }
}

export function recallInvestigation(): RememberedInvestigation | null {
  try {
    const raw = sessionStorage.getItem(ACTIVE_INVESTIGATION_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<RememberedInvestigation>;
    if (typeof parsed.threadId !== "string" || !parsed.threadId) return null;
    if (typeof parsed.itemId !== "string" || !parsed.itemId) return null;
    return {
      threadId: parsed.threadId,
      itemId: parsed.itemId,
      suggested: Array.isArray(parsed.suggested)
        ? parsed.suggested.filter((s): s is string => typeof s === "string")
        : [],
    };
  } catch {
    return null;
  }
}

export function forgetInvestigation(): void {
  try {
    sessionStorage.removeItem(ACTIVE_INVESTIGATION_KEY);
  } catch {
    /* nothing to clean up */
  }
}

/** One item with its full technical evidence. Used to restore after a reload. */
export async function readAttentionItem(
  itemId: string,
): Promise<{ item: AttentionItem }> {
  return json(
    await fetch(
      `${base()}${API_PREFIX}/attention/${encodeURIComponent(itemId)}`,
      { credentials: "include" },
    ),
  );
}

/** Bounded backoff, then a status fallback. Not an unlimited retry loop. */
export const RECONNECT_DELAYS_MS = [1000, 2000, 4000, 8000, 8000, 8000];

/**
 * Raised when the V4 API address is not configured.
 *
 * Deliberately an error rather than a default. `lib/api.ts` falls back to
 * `http://127.0.0.1:8000` when its own variable is unset, which is right for
 * the main backend and wrong for this one: silently sending a Cockpit V4 run
 * to the legacy backend produces a 404 that looks like a Cockpit fault, and
 * on a machine where something IS listening on 8000 it would send an
 * authenticated question to a service that never agreed to receive it.
 */
export class CockpitV4NotConfigured extends Error {
  constructor() {
    super(
      "NEXT_PUBLIC_COCKPIT_V4_API is not set, so this build does not know " +
        "where the Cockpit V4 API is. It is deliberately NOT assumed: the " +
        "V4 API runs on its own port and must never be confused with the " +
        "main CreditProbe backend. Start the Cockpit with " +
        "scripts/cockpit_v4/START_COCKPIT_V4.command, which sets it to the " +
        "port it actually selected.",
    );
    this.name = "CockpitV4NotConfigured";
  }
}

/**
 * The V4 API origin.
 *
 * Reads ONE variable. It never consults `NEXT_PUBLIC_API_URL`, and it has no
 * numeric default — the two rules that together make a silent fall back to
 * the legacy backend impossible rather than merely unlikely.
 *
 * `same-origin` is the explicit opt-in for a deployment that proxies the V4
 * API through the page's own origin. Spelling it out is the point: an empty
 * string reached by accident and an empty string chosen on purpose behave
 * identically at runtime and mean opposite things to a reviewer.
 */
function base(): string {
  const configured = process.env.NEXT_PUBLIC_COCKPIT_V4_API?.trim();
  if (!configured) throw new CockpitV4NotConfigured();
  if (configured === "same-origin") return "";
  return configured.replace(/\/$/, "");
}

/**
 * Is this build running as a Cockpit V4 runtime?
 *
 * Read at module scope rather than in a hook, because the answer decides WHICH
 * page component is instantiated. A hook-based check would have to run inside
 * the legacy page — and by then its own hooks have already fired off the
 * legacy requests this mode exists to avoid.
 */
export function cockpitV4Enabled(): boolean {
  return Boolean(process.env.NEXT_PUBLIC_COCKPIT_V4_API?.trim());
}

/** The configured origin, or a reason it is unusable. For diagnostics. */
export function apiOrigin(): { ok: true; origin: string } | {
  ok: false;
  reason: string;
} {
  try {
    return { ok: true, origin: base() };
  } catch (error) {
    return {
      ok: false,
      reason:
        error instanceof Error ? error.message : "The V4 API is not configured.",
    };
  }
}

async function json<T>(response: Response): Promise<T> {
  const text = await response.text();
  if (!response.ok) {
    let detail: unknown = text;
    try {
      detail = JSON.parse(text);
    } catch {
      /* the body was not JSON; the text is the detail */
    }
    throw Object.assign(new Error(`request failed (${response.status})`), {
      status: response.status,
      detail,
    });
  }
  return JSON.parse(text) as T;
}

export async function createThread(): Promise<{ thread_id: string }> {
  return json(
    await fetch(`${base()}${API_PREFIX}/threads`, {
      method: "POST",
      credentials: "include",
    }),
  );
}

export async function startRun(input: {
  question: string;
  threadId?: string;
  mode?: RunMode;
  filters?: Record<string, unknown>;
  idempotencyKey?: string;
}): Promise<{ run_id: string; thread_id: string; duplicate: boolean }> {
  return json(
    await fetch(`${base()}${API_PREFIX}/runs`, {
      method: "POST",
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
        ...(input.idempotencyKey
          ? { "Idempotency-Key": input.idempotencyKey }
          : {}),
      },
      body: JSON.stringify({
        question: input.question,
        thread_id: input.threadId ?? "",
        mode: input.mode ?? "standard",
        ui_filters: input.filters ?? {},
      }),
    }),
  );
}

export async function readStatus(runId: string): Promise<RunStatus> {
  return json(
    await fetch(`${base()}${API_PREFIX}/runs/${runId}`, {
      credentials: "include",
    }),
  );
}

export async function cancelRun(runId: string): Promise<void> {
  await fetch(`${base()}${API_PREFIX}/runs/${runId}/cancel`, {
    method: "POST",
    credentials: "include",
  });
}

/** Acknowledge that the answer was actually RENDERED, not merely received. */
export async function acknowledge(runId: string): Promise<void> {
  await fetch(`${base()}${API_PREFIX}/runs/${runId}/delivered`, {
    method: "POST",
    credentials: "include",
  }).catch(() => {
    /* a failed acknowledgement must never change the analytical status */
  });
}

// ---- who is asking, and what they can reopen ---------------------------

export type RecentThread = {
  thread_id: string;
  turns: number;
  last_activity_at: string;
  last_question: string;
  last_disposition: string;
  origin: string;
  attention_item: string;
  segment: string;
};

export type SessionSummary = {
  /** A person's name, or "". Never a deployment or profile label. */
  display_name: string;
  /** "Local UAT", a service-account name -- shown in the operator view,
   *  never used to greet anybody. */
  profile_label?: string;
  tenant: string;
  release_id: string;
  recent_threads: RecentThread[];
};

export async function readSession(): Promise<SessionSummary> {
  return json(
    await fetch(`${base()}${API_PREFIX}/session`, { credentials: "include" }),
  );
}

export type ThreadTurn = {
  turn_id: string;
  ordinal: number;
  question: string;
  answer: Record<string, unknown>;
};

export async function readThread(threadId: string): Promise<{
  thread_id: string;
  turns: ThreadTurn[];
  context: { kind?: string; body?: Record<string, unknown> };
}> {
  return json(
    await fetch(
      `${base()}${API_PREFIX}/threads/${encodeURIComponent(threadId)}`,
      { credentials: "include" },
    ),
  );
}

// ---- the Cockpit home feed ---------------------------------------------

export type AttentionNumber = {
  label: string;
  value: string;
  raw: number | null;
};

export type AttentionDriver = {
  relationship: string;
  statement: string;
  metric: string;
  delta: number | null;
  strength: number;
};

export type AttentionDrilldown = {
  available: string[];
  unavailable: string[];
  note: string;
  borrower_count: number;
  suggested_questions: string[];
};

export type AttentionItem = {
  item_id: string;
  section: string;
  /** "segment" | "portfolio" | "borrower" — what the item is ABOUT. */
  scope: string;
  headline: string;
  one_line: string;
  segment: string;
  segment_dimension: string;
  metric: string;
  metric_label: string;
  family: string;
  reporting_quarter: string;
  comparison_quarter: string;
  comparison_basis: string;
  movement: string;
  severity: string;
  score: number | null;
  why_it_appeared: string;
  what_changed: string;
  key_numbers: AttentionNumber[];
  possible_drivers: AttentionDriver[];
  what_to_review_next: string[];
  evidence: Record<string, unknown>;
  evidence_url: string;
  drilldown?: AttentionDrilldown;
};

export type AttentionFeed = {
  release_id: string;
  reporting_quarter: string;
  prior_quarter: string;
  prior_year_quarter: string;
  reporting_currency: string;
  generated_at: string;
  computed_ms: number;
  model_calls: number;
  cached: boolean;
  segments_requiring_attention: AttentionItem[];
  ecl_highlights: AttentionItem[];
  segment_note: string;
  ownership: { functionality: string; basis: string; note: string };
};

export type InvestigationSeed = {
  item_id: string;
  origin: string;
  release_id: string;
  headline: string;
  segment: string;
  reporting_quarter: string;
  comparison_quarter: string;
  metric_label: string;
  drilldown?: AttentionDrilldown;
};

/** The two home sections. Deterministic, cached server-side, no model call. */
export async function readAttention(): Promise<AttentionFeed> {
  return json(
    await fetch(`${base()}${API_PREFIX}/attention`, {
      credentials: "include",
    }),
  );
}

/** Open a thread seeded with this item, so follow-ups keep its context. */
export async function investigate(itemId: string): Promise<{
  thread_id: string;
  item_id: string;
  seed: InvestigationSeed;
  suggested_questions: string[];
}> {
  return json(
    await fetch(
      `${base()}${API_PREFIX}/attention/${encodeURIComponent(itemId)}/investigate`,
      { method: "POST", credentials: "include" },
    ),
  );
}

export type WatchHandlers = {
  onEvent: (event: RunEvent) => void;
  onSettled: (status: RunStatus) => void;
  onConnectionState: (state: "open" | "retrying" | "lost") => void;
};

/**
 * Follow one run. Returns a stop function.
 *
 * `EventSource` cannot send a Last-Event-ID header on the first connect, so
 * the cursor is passed as a query parameter and the header is used by the
 * browser on its own automatic reconnects. Both resume from committed events;
 * neither invents a missing one.
 */
export function watch(
  runId: string,
  handlers: WatchHandlers,
  startCursor = 0,
): () => void {
  let cursor = startCursor;
  let attempt = 0;
  let stopped = false;
  let source: EventSource | null = null;
  let timer: ReturnType<typeof setTimeout> | null = null;

  const open = () => {
    if (stopped) return;
    source = new EventSource(
      `${base()}${API_PREFIX}/runs/${runId}/events?cursor=${cursor}`,
      { withCredentials: true },
    );

    source.onopen = () => {
      attempt = 0;
      handlers.onConnectionState("open");
    };

    source.addEventListener("run.settled", (raw) => {
      stopped = true;
      source?.close();
      try {
        handlers.onSettled(JSON.parse((raw as MessageEvent).data) as RunStatus);
      } catch {
        void readStatus(runId).then(handlers.onSettled).catch(() => {});
      }
    });

    const deliver = (raw: MessageEvent) => {
      let event: RunEvent;
      try {
        event = JSON.parse(raw.data) as RunEvent;
      } catch {
        return;
      }
      // A replayed or duplicated event is not new information. Applying it
      // twice would double-count a substep and move elapsed time backwards.
      if (event.seq <= cursor) return;
      // A gap means events were missed, not that they did not happen. The
      // authoritative status is re-read rather than reconstructed.
      if (event.seq > cursor + 1 && cursor !== 0) {
        void readStatus(runId).then(handlers.onSettled).catch(() => {});
      }
      cursor = Math.max(cursor, event.seq);
      handlers.onEvent(event);
    };

    // A listener per named event, plus `onmessage` for any unnamed frame.
    for (const name of EVENT_TYPES) {
      source.addEventListener(name, (raw) => deliver(raw as MessageEvent));
    }
    source.onmessage = deliver;

    source.onerror = () => {
      source?.close();
      if (stopped) return;
      if (attempt >= RECONNECT_DELAYS_MS.length) {
        // Six failed attempts. This is what the CLIENT knows; the run may
        // well be fine, and the panel says so.
        handlers.onConnectionState("lost");
        return;
      }
      handlers.onConnectionState("retrying");
      timer = setTimeout(open, RECONNECT_DELAYS_MS[attempt]);
      attempt += 1;
    };
  };

  open();
  return () => {
    stopped = true;
    if (timer) clearTimeout(timer);
    source?.close();
  };
}

/* ---- what a credit officer does with an answer ---------------------- */

export type SavedAnalysis = {
  saved_id: string;
  title: string;
  note: string;
  question: string;
  run_id: string;
  thread_id: string;
  release_id: string;
  created_at: string;
};

export type Investigation = {
  investigation_id: string;
  title: string;
  summary: string;
  status: string;
  origin: string;
  updated_at: string;
  items?: { entry_id: string; kind: string; ref_id: string; label: string }[];
};

export type Comment = {
  comment_id: string;
  subject_kind: string;
  subject_id: string;
  author_id: string;
  body: string;
  created_at: string;
};

/**
 * One outbox row. `delivered` is the only field the UI may render as
 * "sent": `state` alone is not a delivery claim, and a RECORDED or REFUSED
 * row carries the reason it went nowhere.
 */
export type Notification = {
  notification_id: string;
  recipient: string;
  subject: string;
  state: "RECORDED" | "REFUSED" | "SENT" | "FAILED";
  transport: string;
  reason: string;
  delivered: boolean;
  created_at: string;
};

export type DeliveryPosture = {
  transport: string | null;
  can_deliver: boolean;
  recipient_policy: string;
  authorized_recipients: string[];
  authorized_domains: string[];
};

async function send<T>(path: string, body: unknown): Promise<T> {
  return json(
    await fetch(`${base()}${API_PREFIX}${path}`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  );
}

export async function saveAnalysis(input: {
  run_id: string;
  title?: string;
  note?: string;
}): Promise<SavedAnalysis> {
  return send("/saved-analyses", input);
}

export async function listSavedAnalyses(): Promise<SavedAnalysis[]> {
  const body = await json<{ saved: SavedAnalysis[] }>(
    await fetch(`${base()}${API_PREFIX}/saved-analyses`, {
      credentials: "include",
    }),
  );
  return body.saved ?? [];
}

export async function createInvestigation(input: {
  title: string;
  summary?: string;
  origin?: string;
  thread_id?: string;
  saved_ids?: string[];
}): Promise<Investigation> {
  return send("/investigations", input);
}

export async function listInvestigations(): Promise<Investigation[]> {
  const body = await json<{ investigations: Investigation[] }>(
    await fetch(`${base()}${API_PREFIX}/investigations`, {
      credentials: "include",
    }),
  );
  return body.investigations ?? [];
}

export async function addInvestigationItem(
  investigationId: string,
  input: { kind: string; ref_id: string; label?: string },
): Promise<{ entry_id: string }> {
  return send(`/investigations/${encodeURIComponent(investigationId)}/items`, input);
}

export async function addComment(input: {
  subject_kind: string;
  subject_id: string;
  body: string;
}): Promise<Comment> {
  return send("/comments", input);
}

export async function listComments(
  subjectKind: string,
  subjectId: string,
): Promise<Comment[]> {
  const query = new URLSearchParams({
    subject_kind: subjectKind,
    subject_id: subjectId,
  });
  const body = await json<{ comments: Comment[] }>(
    await fetch(`${base()}${API_PREFIX}/comments?${query.toString()}`, {
      credentials: "include",
    }),
  );
  return body.comments ?? [];
}

export async function shareItem(input: {
  subject_kind: string;
  subject_id: string;
  audience_id: string;
  message?: string;
  notify_email?: string;
}): Promise<{
  share: { share_id: string; audience_id: string };
  notification: Notification | null;
  delivery: DeliveryPosture;
}> {
  return send("/shares", input);
}

export async function readOutbox(): Promise<{
  delivery: DeliveryPosture;
  notifications: Notification[];
}> {
  return json(
    await fetch(`${base()}${API_PREFIX}/notifications`, {
      credentials: "include",
    }),
  );
}

/**
 * The sentence the UI is allowed to show about one notification.
 *
 * There is exactly one wording that claims delivery, and it is reachable
 * only when the server said `delivered`. Everything else names what did not
 * happen, so no screen can render "email sent" over a message that sat in
 * the outbox.
 */
export function deliveryWording(notification: Notification | null): string {
  if (!notification) return "No notification was requested.";
  if (notification.delivered) {
    return `Sent to ${notification.recipient} via ${notification.transport}.`;
  }
  if (notification.state === "REFUSED") {
    return `Not sent. ${notification.recipient} is not an authorised recipient for this deployment.`;
  }
  if (notification.state === "FAILED") {
    return `Not sent. The transport refused it: ${notification.reason}`;
  }
  return `Recorded, not sent. ${notification.reason}`;
}
