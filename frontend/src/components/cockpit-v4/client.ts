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

/** Bounded backoff, then a status fallback. Not an unlimited retry loop. */
export const RECONNECT_DELAYS_MS = [1000, 2000, 4000, 8000, 8000, 8000];

function base(): string {
  const configured = process.env.NEXT_PUBLIC_COCKPIT_V4_API;
  return (configured && configured.replace(/\/$/, "")) || "";
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
  mode?: "standard" | "deep";
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
export function watch(runId: string, handlers: WatchHandlers): () => void {
  let cursor = 0;
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

    source.onmessage = (raw) => {
      let event: RunEvent;
      try {
        event = JSON.parse(raw.data) as RunEvent;
      } catch {
        return;
      }
      // A gap means events were missed, not that they did not happen. The
      // authoritative status is re-read rather than reconstructed.
      if (event.seq > cursor + 1 && cursor !== 0) {
        void readStatus(runId).then(handlers.onSettled).catch(() => {});
      }
      cursor = Math.max(cursor, event.seq);
      handlers.onEvent(event);
    };

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
