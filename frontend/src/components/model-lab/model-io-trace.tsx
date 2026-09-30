"use client";

/**
 * MODEL I/O TRACE — what CreditProbe sent each model and what came back.
 *
 * Read-only: the timeline and each call's four views come from stored
 * evidence (`/model-io`), so opening a saved comparison never calls a model.
 * Everything is rendered as text (never HTML). Credentials and hidden
 * reasoning are excluded server-side before anything is stored.
 */

import * as React from "react";

import {
  type ModelIoCall,
  type ModelIoItem,
  type ModelIoTool,
  type ModelIoTrace as Trace,
  readModelIo,
  readModelIoCall,
} from "./client";

const VIEW_TITLES: [string, string][] = [
  ["engine_request", "Engine request"],
  ["wire_request", "Wire request"],
  ["wire_response_raw", "Raw response"],
  ["normalized_response", "Normalized response"],
];

function bytesOf(text: string): number {
  return new TextEncoder().encode(text).length;
}

function download(name: string, text: string) {
  const url = URL.createObjectURL(new Blob([text], { type: "application/json" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}

export function JsonView({
  title,
  data,
  file,
  size,
}: {
  title: string;
  data: unknown;
  file: string;
  size?: { bytes: number; sha256: string };
}) {
  const [pretty, setPretty] = React.useState(true);
  const [copied, setCopied] = React.useState(false);
  const raw = JSON.stringify(data ?? null);
  const text = pretty ? JSON.stringify(data ?? null, null, 2) : raw;
  return (
    <details className="rounded border border-border">
      <summary className="cursor-pointer p-1 font-medium text-text-primary">
        [{title}] <span className="font-normal text-text-muted">
          {(size?.bytes ?? bytesOf(raw)).toLocaleString("en-US")} bytes
          {size ? ` · sha256 ${size.sha256.slice(0, 16)}…` : ""}
        </span>
      </summary>
      <div className="flex flex-wrap gap-2 p-1">
        <button type="button" className="underline" onClick={() => setPretty(!pretty)}>
          {pretty ? "Raw JSON" : "Pretty JSON"}
        </button>
        <button type="button" className="underline"
          onClick={() => navigator.clipboard?.writeText(text).then(() => setCopied(true))}>
          {copied ? "Copied" : "Copy"}
        </button>
        <button type="button" className="underline" onClick={() => download(file, JSON.stringify(data ?? null, null, 2))}>
          Download
        </button>
      </div>
      <pre className="max-h-96 overflow-auto whitespace-pre-wrap break-all bg-surface-sunken p-2 text-[11px]">
        {text}
      </pre>
    </details>
  );
}

type Block = { type?: string; text?: string; name?: string; input?: unknown; content?: unknown; tool_use_id?: string; id?: string };

function Role({ label }: { label: string }) {
  return (
    <span className="mr-1 rounded border border-border-strong px-1 text-[10px] font-bold text-text-primary">
      {label}
    </span>
  );
}

/** The engine request as a readable, role-labelled conversation. */
function Conversation({ request }: { request: Record<string, unknown> | null }) {
  if (!request) return <p className="text-text-muted">No engine request captured.</p>;
  const system = request.system;
  const systemText = Array.isArray(system)
    ? (system as Block[]).map((b) => b.text ?? "").join("\n\n")
    : String(system ?? "");
  const messages = (request.messages as { role: string; content: unknown }[]) ?? [];
  return (
    <details className="rounded border border-border">
      <summary className="cursor-pointer p-1 font-medium text-text-primary">[Conversation, role-labelled]</summary>
      <div className="space-y-2 p-2">
        <div>
          <Role label="SYSTEM" />
          <pre className="max-h-64 overflow-auto whitespace-pre-wrap bg-surface-sunken p-2 text-[11px]">{systemText}</pre>
        </div>
        {messages.map((m, i) => {
          const blocks: Block[] = typeof m.content === "string"
            ? [{ type: "text", text: m.content }]
            : ((m.content as Block[]) ?? []);
          return (
            <div key={i} className="border-l-2 border-border-strong pl-2">
              {blocks.map((b, j) => {
                let label = m.role === "user" ? "USER" : "ASSISTANT";
                let body: unknown = b.text;
                if (b.type === "tool_use") {
                  label = b.name === "finalize_response" ? "FINAL RESPONSE" : "TOOL CALL";
                  body = { id: b.id, name: b.name, input: b.input };
                } else if (b.type === "tool_result") {
                  label = "TOOL RESULT";
                  body = { tool_use_id: b.tool_use_id, content: b.content };
                } else if (b.type && b.type !== "text") {
                  body = b;
                }
                return (
                  <div key={j} className="mb-1">
                    <Role label={label} />
                    <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-all text-[11px]">
                      {typeof body === "string" ? body : JSON.stringify(body, null, 2)}
                    </pre>
                  </div>
                );
              })}
            </div>
          );
        })}
      </div>
    </details>
  );
}

function CallItem({ cid, item }: { cid: string; item: ModelIoCall }) {
  const [detail, setDetail] = React.useState<ModelIoCall | null>(null);
  const [error, setError] = React.useState("");
  function load() {
    if (detail || item.dispatch_status === "NOT_SENT") return;
    readModelIoCall(cid, item.call_id).then(setDetail).catch((e: Error) => setError(e.message));
  }
  const n = String(item.n).padStart(3, "0");
  return (
    <details className="rounded border border-border-strong p-1" onToggle={load}>
      <summary className="cursor-pointer text-text-primary">
        <b>Call {item.n}</b> · {(item.stage_tags ?? []).join("+") || "no stage"}
        {item.shared_span ? " (shared)" : ""} · {item.purpose} · {item.requested_model ?? "?"} ·
        request {item.input_tokens ?? item.counted_input_tokens ?? "?"} tok · response{" "}
        {item.output_tokens ?? "?"} tok · {item.duration_ms != null ? `${Math.round(item.duration_ms)} ms` : "?"} ·{" "}
        {item.dispatch_status}
        {item.tool_calls?.length ? ` · ${item.tool_calls.map((t) => t.name).join(", ")}` : ""}
      </summary>
      {item.dispatch_status === "NOT_SENT" && (
        <p className="p-1 text-text-secondary">dispatch_status = NOT_SENT: {item.dispatch_reason}</p>
      )}
      {item.error && (
        <p className="p-1 text-text-secondary">Error: {item.error.type} {item.error.code} — {item.error.message}</p>
      )}
      {error && <p className="p-1 text-text-secondary">{error}</p>}
      {detail?.views && (
        <div className="space-y-1 p-1">
          <Conversation request={(detail.views.engine_request?.request as Record<string, unknown>) ?? null} />
          {VIEW_TITLES.map(([k, title]) => (
            <JsonView key={k} title={title} data={detail.views?.[k]}
              file={`call_${n}_${k}.json`} size={item.sizes?.[k]} />
          ))}
          <JsonView title="Download whole call" data={detail} file={`call_${n}.json`} />
        </div>
      )}
    </details>
  );
}

function ToolItem({ item }: { item: ModelIoTool }) {
  const n = String(item.n).padStart(3, "0");
  return (
    <details className="ml-4 rounded border border-border p-1">
      <summary className="cursor-pointer text-text-primary">
        <b>Tool round-trip {item.n}</b> · {item.model_tool_call?.name} ({item.model_tool_call?.id}) ·{" "}
        {(item.stage_tags ?? []).join("+")} · validation {item.validation.map((v) => v.status).join("/") || "none"} ·
        result {item.tool_result_bytes.toLocaleString("en-US")} bytes
        {item.is_final_response ? " · FINAL RESPONSE" : ""}
      </summary>
      <div className="space-y-1 p-1">
        <JsonView title="Model tool call" data={item.model_tool_call} file={`tool_${n}_call.json`} />
        <JsonView title="Validation" data={item.validation} file={`tool_${n}_validation.json`} />
        <JsonView title="Execution" data={{ execution: item.execution, submissions: item.submissions }}
          file={`tool_${n}_execution.json`} />
        <JsonView title={`Exact tool result returned (${item.tool_result_source})`}
          data={item.tool_result_returned} file={`tool_${n}_result.json`}
          size={{ bytes: item.tool_result_bytes, sha256: item.tool_result_sha256 }} />
      </div>
    </details>
  );
}

export function ModelIoTrace({ cid, refreshKey }: { cid: string; refreshKey?: string }) {
  const [trace, setTrace] = React.useState<Trace | null>(null);
  const [error, setError] = React.useState("");
  React.useEffect(() => {
    let live = true;
    readModelIo(cid)
      .then((t) => live && setTrace(t))
      .catch((e: Error) => live && setError(e.message));
    return () => {
      live = false;
    };
  }, [cid, refreshKey]);
  if (error) return <p className="text-xs text-text-secondary">Model I/O Trace unavailable: {error}</p>;
  if (!trace) return <p className="text-xs text-text-muted">Loading Model I/O Trace…</p>;
  return (
    <div className="space-y-3 text-xs" aria-label="Model I/O Trace">
      <p className="text-text-muted">
        Model I/O Trace captures the actual request/response boundary. Provider credentials and hidden
        reasoning are excluded. {trace.policy.truncation}.
      </p>
      {trace.children.map((ch) => (
        <div key={ch.child_run_id}>
          <h4 className="font-medium text-text-primary">
            {ch.display_name} — {ch.traced_calls} traced call(s) · {ch.execution_state}
          </h4>
          <p className="text-text-muted">
            {(["S1", "S2", "S3", "S4"] as const).map((s) => {
              const l = ch.stage_links[s];
              return `${s}: calls ${[...l.calls, ...l.shared_calls.map((c) => `${c}*`)].join(",") || "—"}; tools ${l.tool_roundtrips.join(",") || "—"}`;
            }).join(" · ")} (* shared span)
          </p>
          <div className="mt-1 space-y-1">
            {ch.timeline.map((it: ModelIoItem) =>
              it.kind === "call"
                ? <CallItem key={`c${it.n}`} cid={cid} item={it} />
                : <ToolItem key={`t${it.n}`} item={it} />,
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
