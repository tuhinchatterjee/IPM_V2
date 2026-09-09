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
  kind: "state" | "milestone" | "delta" | "artifact" | "done" | "error";
  data: Record<string, unknown>;
}

export function toPlaybookEvent(raw: StreamEvent): PlaybookStreamEvent | null {
  const kinds = ["state", "milestone", "delta", "artifact", "done", "error"];
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

/**
 * What the answer looks like so far, from the events seen.
 *
 * Kept here rather than in the component so it can be asserted directly: the
 * rule that a failed run shows no partial answer is a rule about this
 * function, not about a `useState` call.
 */
export function assemble(events: PlaybookStreamEvent[]): {
  text: string;
  state: string;
  detail: string;
  done: boolean;
  error: string;
  cancelled: boolean;
  version: number;
} {
  let text = "";
  let state = "";
  let detail = "";
  let done = false;
  let error = "";
  let cancelled = false;
  let version = 0;

  for (const event of events) {
    if (event.kind === "delta") {
      text += String(event.data.text ?? "");
    } else if (event.kind === "state" || event.kind === "milestone") {
      state = String(event.data.state ?? "");
      detail = String(event.data.detail ?? "");
    } else if (event.kind === "artifact") {
      version = Number(event.data.version ?? 0);
    } else if (event.kind === "done") {
      done = true;
      version = Number(event.data.version ?? version);
    } else if (event.kind === "error") {
      error = String(event.data.message ?? "The generation failed.");
      cancelled = Boolean(event.data.cancelled);
      done = true;
      // A run that failed has no answer. Showing the fragment it managed
      // before failing, as though it were the answer, is the thing this
      // whole design exists to prevent.
      text = "";
    }
  }
  return { text, state, detail, done, error, cancelled, version };
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
