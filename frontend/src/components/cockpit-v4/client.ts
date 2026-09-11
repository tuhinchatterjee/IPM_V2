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
