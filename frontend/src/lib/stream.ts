/**
 * Reading a server-sent event stream, with no React in it.
 *
 * `EventSource` is the obvious tool and it is unusable here: it cannot send a
 * header, and this deployment identifies the caller with `X-IPM-Role`. So the
 * stream is read with `fetch` and a reader, and this module is the parser that
 * turns bytes into events.
 *
 * The parsing is the part worth testing, because the failure is silent. A
 * network read boundary falls wherever it likes — in the middle of a word, in
 * the middle of a `data:` line, between the two newlines that end an event —
 * and a parser that assumes each read is a whole event drops text at random
 * under load and works perfectly in a demonstration.
 */

/** One event off the wire. `id` is the cursor a reconnect resumes from. */
export interface StreamEvent {
  id: string;
  event: string;
  data: string;
}

/**
 * An incremental SSE parser.
 *
 * Feed it whatever arrives; it returns the events that are now complete and
 * keeps the rest. Comment lines (`: keep-alive`) are consumed and produce
 * nothing, which is exactly what a heartbeat should do.
 */
export class SSEParser {
  private buffer = "";

  push(chunk: string): StreamEvent[] {
    // Normalised on the way in, so the frame separator is one thing to look
    // for rather than three. A chunk that ends mid-"\r\n" is handled by the
    // buffer: the stray "\r" is normalised on the next push.
    this.buffer += chunk.replace(/\r\n/g, "\n");
    const events: StreamEvent[] = [];
    // Events are separated by a blank line. Anything after the last separator
    // is an incomplete event and stays in the buffer.
    let index = this.buffer.indexOf("\n\n");
    while (index !== -1) {
      const frame = this.buffer.slice(0, index);
      this.buffer = this.buffer.slice(index + 2);
      const parsed = parseFrame(frame);
      if (parsed) events.push(parsed);
      index = this.buffer.indexOf("\n\n");
    }
    return events;
  }

  /** What has not yet been terminated by a blank line. */
  get pending(): string {
    return this.buffer;
  }
}

function parseFrame(frame: string): StreamEvent | null {
  let id = "";
  let event = "message";
  const data: string[] = [];
  for (const line of frame.split("\n")) {
    if (!line || line.startsWith(":")) continue;
    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    // "Optional space after the colon", per the spec — one, not all of them.
    let value = colon === -1 ? "" : line.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    if (field === "id") id = value;
    else if (field === "event") event = value;
    else if (field === "data") data.push(value);
  }
  if (!data.length && event === "message") return null;
  return { id, event, data: data.join("\n") };
}

/** The shape the Playbook stream carries, once its JSON is parsed. */
export interface PlaybookStreamEvent {
  seq: number;
  kind:
    | "state"
    | "milestone"
    | "delta"
    /** The document being written, as it is written. Never the chat answer. */
    | "draft_delta"
    /** The steps this turn intends, named before any of them has happened. */
    | "plan"
    | "artifact"
    /** The connection is open and the worker has not been heard from. */
    | "ping"
    | "done"
    | "error";
  data: Record<string, unknown>;
}

export function toPlaybookEvent(raw: StreamEvent): PlaybookStreamEvent | null {
  const kinds = [
    "state",
    "milestone",
    "delta",
    "draft_delta",
    "plan",
    "artifact",
    "ping",
    "done",
    "error",
  ];
  if (!kinds.includes(raw.event)) return null;
  let data: Record<string, unknown> = {};
  try {
    data = raw.data ? JSON.parse(raw.data) : {};
  } catch {
    // A frame that does not parse is dropped rather than shown. Half a JSON
    // object rendered as text would be worse than the missing event.
    return null;
  }
  return {
    seq: Number(raw.id) || 0,
    kind: raw.event as PlaybookStreamEvent["kind"],
    data,
  };
}

/** One step of this turn's work, and when it happened. */
export interface StreamStep {
  /** The job state it belongs to: reviewing_sources, drafting, rendering… */
  state: string;
  /** What within that state — a tool name, a format, a file. */
  detail: string;
  /** Seconds after the generation started, measured by the server. */
  at: number;
  /** Set once a later step has begun, or the run has ended. */
  done: boolean;
}

/**
 * What the answer looks like so far, from the events seen.
 *
 * Kept here rather than in the component so it can be asserted directly: the
 * rule that a failed run shows no partial answer is a rule about this
 * function, not about a `useState` call.
 *
 * It returns the ORDERED steps, not the latest one. An earlier version
 * overwrote two scalars on every milestone, so a seven-minute run showed one
 * unchanging line and no way to tell whether it had moved in the last five
 * minutes or died. The log is what makes elapsed time per step answerable,
 * and the backend has always persisted it — nothing was reading it.
 */
export function assemble(events: PlaybookStreamEvent[]): {
  text: string;
  /** The document being written, when a tool is writing one. */
  draft: string;
  state: string;
  detail: string;
  steps: StreamStep[];
  /** The steps this turn said it would take, in order, before taking them. */
  plan: string[];
  /** Seconds since the generation started, from the newest event. */
  at: number;
  /** Seconds the worker has been silent, from the newest heartbeat. */
  quietFor: number;
  done: boolean;
  error: string;
  cancelled: boolean;
  version: number;
} {
  let text = "";
  let draft = "";
  let state = "";
  let detail = "";
  let plan: string[] = [];
  let at = 0;
  let quietFor = 0;
  let done = false;
  let error = "";
  let cancelled = false;
  let version = 0;
  const steps: StreamStep[] = [];

  for (const event of events) {
    // Every event but the heartbeat carries the server's own offset. The
    // heartbeat is written by the reader, not the worker, so it says how long
    // the worker has been quiet and deliberately does not move `at`.
    if (event.kind !== "ping" && typeof event.data.at === "number") {
      at = Math.max(at, event.data.at as number);
    }

    if (event.kind === "delta") {
      text += String(event.data.text ?? "");
    } else if (event.kind === "draft_delta") {
      draft += String(event.data.text ?? "");
    } else if (event.kind === "ping") {
      quietFor = Number(event.data.quiet_for ?? 0);
    } else if (event.kind === "plan") {
      plan = (event.data.steps as string[] | undefined) ?? [];
    } else if (event.kind === "state" || event.kind === "milestone") {
      state = String(event.data.state ?? "");
      detail = String(event.data.detail ?? "");
      const step: StreamStep = {
        state,
        detail,
        at: Number(event.data.at ?? at),
        done: false,
      };
      const previous = steps[steps.length - 1];
      // Repeats of the same step are one step, not many. The backend emits
      // `reviewing_sources` twice at the start of every turn, and a list that
      // showed it twice would be reporting the implementation rather than
      // the work.
      if (previous && previous.state === step.state
          && previous.detail === step.detail) {
        continue;
      }
      if (previous) previous.done = true;
      steps.push(step);
    } else if (event.kind === "artifact") {
      version = Number(event.data.version ?? 0);
    } else if (event.kind === "done") {
      done = true;
      version = Number(event.data.version ?? version);
      if (steps.length) steps[steps.length - 1].done = true;
    } else if (event.kind === "error") {
      error = String(event.data.message ?? "The generation failed.");
      cancelled = Boolean(event.data.cancelled);
      done = true;
      // A run that failed has no answer. Showing the fragment it managed
      // before failing, as though it were the answer, is the thing this
      // whole design exists to prevent.
      text = "";
      draft = "";
    }
  }
  return {
    text, draft, state, detail, steps, plan, at, quietFor,
    done, error, cancelled, version,
  };
}

/**
 * How many sections the draft has so far.
 *
 * Counted from the text that has actually arrived, so it is a measurement and
 * not an estimate. There is deliberately no denominator: the document does
 * not declare how many sections it will have, and inventing one is exactly
 * the invented completion figure chapter 12 forbids.
 */
export function draftSections(draft: string): number {
  return (draft.match(/^##\s+\S/gm) ?? []).length;
}

/** "4m 12s", or "8s". Elapsed time, never a claim about progress. */
export function elapsed(seconds: number): string {
  const whole = Math.max(0, Math.floor(seconds));
  const minutes = Math.floor(whole / 60);
  return minutes ? `${minutes}m ${whole % 60}s` : `${whole}s`;
}

/** What a real job state should say to somebody watching it. */
const STATE_LABEL: Record<string, string> = {
  queued: "Queued",
  reviewing_sources: "Reading the sources",
  drafting: "Writing",
  rendering: "Building the files",
  validating: "Checking the files open and say the same thing",
  ready: "Finished",
  cancelled: "Stopped",
  failed: "Failed",
};

export function stateLabel(state: string, detail = ""): string {
  const label = STATE_LABEL[state] ?? state.replace(/_/g, " ");
  return detail ? `${label} — ${detail}` : label;
}
