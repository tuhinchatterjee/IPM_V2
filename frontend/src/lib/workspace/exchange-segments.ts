/**
 * One recorded model call, read as the model saw it: every part of the
 * canonical request and of the normalized response labelled SYSTEM, USER,
 * ASSISTANT, TOOL CALL, TOOL RESULT or VALIDATOR, in the order sent.
 *
 * VALIDATOR is CreditProbe's own feedback to the model: a tool result the
 * application returned as an error (`is_error`) or with a rejected status --
 * a failed check, a refused query, a finalizer rejection. It travels in a
 * tool result, but it is not data: labelling it apart is what lets a
 * reviewer see the repair loop. Pure; the view only renders these.
 */

export type SegmentKind = "SYSTEM" | "USER" | "ASSISTANT" | "TOOL CALL" | "TOOL RESULT" | "VALIDATOR";

export interface Segment {
  kind: SegmentKind;
  /** "request" (what was sent) or "response" (what came back). */
  side: "request" | "response";
  /** 1-based message number in the request; 0 for system and response. */
  message: number;
  name?: string;
  id?: string;
  text: string;
}

type Block = Record<string, unknown>;

function asText(value: unknown): string {
  if (typeof value === "string") return value;
  if (Array.isArray(value)) {
    return value.map((v) => (v && typeof v === "object" && "text" in (v as Block) ? String((v as Block).text) : asText(v))).join("\n");
  }
  return JSON.stringify(value ?? "", null, 2);
}

function rejected(content: unknown): boolean {
  const text = asText(content);
  return /"status"\s*:\s*"rejected"/.test(text) || /"error_code"\s*:/.test(text);
}

export function segments(
  request: Record<string, unknown> | null | undefined,
  response?: { text?: string; tool_calls?: { id: string; name: string; input: unknown }[] } | null,
): Segment[] {
  const out: Segment[] = [];
  const req = request ?? {};
  const system = req.system;
  if (Array.isArray(system)) {
    for (const b of system) out.push({ kind: "SYSTEM", side: "request", message: 0, text: asText(b && typeof b === "object" ? (b as Block).text ?? b : b) });
  } else if (system) {
    out.push({ kind: "SYSTEM", side: "request", message: 0, text: String(system) });
  }
  const messages = (req.messages as { role?: string; content?: unknown }[]) ?? [];
  messages.forEach((m, i) => {
    const n = i + 1;
    const role = String(m.role ?? "");
    if (typeof m.content === "string") {
      out.push({ kind: role === "assistant" ? "ASSISTANT" : "USER", side: "request", message: n, text: m.content });
      return;
    }
    for (const block of (m.content as Block[]) ?? []) {
      const type = String(block.type ?? "");
      if (type === "tool_use") {
        out.push({ kind: "TOOL CALL", side: "request", message: n, name: String(block.name ?? ""), id: String(block.id ?? ""), text: JSON.stringify(block.input ?? {}, null, 2) });
      } else if (type === "tool_result") {
        const validator = block.is_error === true || rejected(block.content);
        out.push({ kind: validator ? "VALIDATOR" : "TOOL RESULT", side: "request", message: n, id: String(block.tool_use_id ?? ""), text: asText(block.content) });
      } else if (type === "text") {
        out.push({ kind: role === "assistant" ? "ASSISTANT" : "USER", side: "request", message: n, text: String(block.text ?? "") });
      } else {
        out.push({ kind: role === "assistant" ? "ASSISTANT" : "USER", side: "request", message: n, text: `[${type}] ${JSON.stringify(block).slice(0, 2000)}` });
      }
    }
  });
  if (response?.text) out.push({ kind: "ASSISTANT", side: "response", message: 0, text: response.text });
  for (const tc of response?.tool_calls ?? []) {
    out.push({ kind: "TOOL CALL", side: "response", message: 0, name: tc.name, id: tc.id, text: JSON.stringify(tc.input ?? {}, null, 2) });
  }
  return out;
}

export function counts(list: Segment[]): Record<SegmentKind, number> {
  const base: Record<SegmentKind, number> = { SYSTEM: 0, USER: 0, ASSISTANT: 0, "TOOL CALL": 0, "TOOL RESULT": 0, VALIDATOR: 0 };
  for (const s of list) base[s.kind] += 1;
  return base;
}
