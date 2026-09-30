"use client";

/**
 * Trace > LLM Exchange: every model call a run made, exactly as sent and
 * received (after secret redaction), with the deterministic CreditProbe work
 * between the calls, context composition and growth, and what data the model
 * actually saw versus what CreditProbe held.
 *
 * READ ONLY. Loading this page makes no model call.
 */

import * as React from "react";
import Link from "next/link";
import { Download, GitCompare, Loader2, ShieldCheck } from "lucide-react";

import { JsonTree } from "@/components/llm-exchange/json-tree";
import { ChartCard, downloadText } from "@/components/viz/chart-card";
import { Badge } from "@/components/ui/badge";
import { Tabs } from "@/components/ui/tabs";
import {
  compareExchanges,
  compositionFigure,
  exchangeExportUrl,
  growthFigure,
  readRunExchange,
  type Comparison,
  type ExchangeCall,
  type RunExchange,
} from "@/lib/workspace/llm-exchange";
import { count } from "@/lib/viz/format";
import { cn } from "@/lib/utils";

const STAGES = [
  { id: "readable", label: "Readable" },
  { id: "canonical", label: "Canonical request" },
  { id: "adapter", label: "Adapter / provider request" },
  { id: "raw", label: "Raw provider response" },
  { id: "normalized", label: "Normalized response" },
  { id: "meta", label: "Hashes & redactions" },
];

function Readable({ call }: { call: ExchangeCall }) {
  const req = call.canonical_request ?? {};
  const system = Array.isArray(req.system) ? (req.system as { text?: string }[]) : [{ text: String(req.system ?? "") }];
  const messages = (req.messages as { role: string; content: unknown }[]) ?? [];
  const tools = (req.tools as { name: string; description?: string }[]) ?? [];
  const norm = call.normalized_response ?? {};
  return (
    <div className="space-y-3 text-xs">
      <section>
        <h4 className="mb-1 font-semibold text-text-primary">System instructions actually sent ({system.length} block{system.length === 1 ? "" : "s"})</h4>
        {system.map((b, i) => (
          <pre key={i} className="mb-1 max-h-48 overflow-auto whitespace-pre-wrap rounded bg-surface-sunken p-2 text-[11px]">
            {b.text}
          </pre>
        ))}
      </section>
      <section>
        <h4 className="mb-1 font-semibold text-text-primary">Tools offered ({tools.length}) · tool choice {JSON.stringify(req.tool_choice ?? "auto")}</h4>
        <ul className="list-disc pl-5">
          {tools.map((t) => (
            <li key={t.name}>
              <span className="font-medium">{t.name}</span> — {t.description?.slice(0, 180)}
            </li>
          ))}
        </ul>
      </section>
      <section>
        <h4 className="mb-1 font-semibold text-text-primary">Messages, in order ({messages.length})</h4>
        {messages.map((m, i) => (
          <div key={i} className="mb-1 rounded border border-border p-2">
            <div className="mb-1 text-text-muted">
              {i + 1}. {m.role}
            </div>
            {typeof m.content === "string" ? (
              <pre className="max-h-48 overflow-auto whitespace-pre-wrap text-[11px]">{m.content}</pre>
            ) : (
              (m.content as Record<string, unknown>[]).map((block, j) => (
                <div key={j} className="mb-1">
                  <Badge variant="outline">{String(block.type)}</Badge>{" "}
                  <pre className="mt-1 max-h-48 overflow-auto whitespace-pre-wrap text-[11px]">
                    {block.type === "text"
                      ? String(block.text)
                      : block.type === "tool_result"
                        ? String(block.content).slice(0, 4000)
                        : JSON.stringify(block, null, 2).slice(0, 4000)}
                  </pre>
                </div>
              ))
            )}
          </div>
        ))}
      </section>
      <section>
        <h4 className="mb-1 font-semibold text-text-primary">What came back</h4>
        {norm.text ? <pre className="whitespace-pre-wrap rounded bg-surface-sunken p-2 text-[11px]">{norm.text}</pre> : null}
        {(norm.tool_calls ?? []).map((tc) => (
          <div key={tc.id} className="mb-1 rounded border border-border p-2">
            <div className="font-medium">
              Tool call: {tc.name} <span className="text-text-muted">({tc.id})</span>
            </div>
            <pre className="mt-1 max-h-64 overflow-auto whitespace-pre-wrap text-[11px]">
              {JSON.stringify(tc.input, null, 2)}
            </pre>
          </div>
        ))}
        {call.error && <p className="text-negative">{call.error}</p>}
      </section>
    </div>
  );
}

function CallCard({
  call,
  selected,
  onSelect,
}: {
  call: ExchangeCall;
  selected: boolean;
  onSelect: (checked: boolean) => void;
}) {
  const [open, setOpen] = React.useState(call.seq === 1);
  const [stage, setStage] = React.useState("readable");
  const usage = call.usage ?? {};
  const payload: Record<string, unknown> = {
    canonical: call.canonical_request,
    adapter: call.adapter_request,
    raw: call.raw_response,
    normalized: call.normalized_response,
    meta: {
      hashes: call.hashes,
      redactions: call.redactions,
      settings: call.settings,
      adapter_translation: call.adapter_translation,
      hidden_reasoning_recorded: call.hidden_reasoning_recorded,
    },
  };
  return (
    <article className="rounded-lg border border-border bg-surface" data-testid={`llm-call-${call.seq}`}>
      <header className="flex flex-wrap items-center gap-2 p-3">
        <input
          type="checkbox"
          checked={selected}
          onChange={(e) => onSelect(e.target.checked)}
          aria-label={`Select call ${call.seq} for comparison`}
        />
        <button type="button" onClick={() => setOpen((v) => !v)} className="text-left" aria-expanded={open}>
          <span className="text-sm font-semibold text-text-primary">
            Call {call.seq} · {call.purpose || "generation"}
          </span>
        </button>
        <Badge variant={call.status === "OK" ? "positive" : "negative"}>{call.status}</Badge>
        <Badge variant="outline">{call.resolved_model}</Badge>
        <Badge variant="outline">
          {call.provider} / {call.adapter}
        </Badge>
        <span className="text-xs text-text-muted">
          {call.provider_ms} ms · stop {call.stop_reason || "—"} · in {count(usage.input_tokens)} / out{" "}
          {count(usage.output_tokens)} tokens · {count(call.context_composition?.total_bytes)} bytes sent
        </span>
        {call.redactions?.length ? (
          <Badge variant="warning">{call.redactions.length} redaction(s)</Badge>
        ) : (
          <Badge variant="default">no secrets found</Badge>
        )}
        {call.replay_of && <Badge variant="info">replay of {call.replay_of.slice(0, 14)}…</Badge>}
      </header>
      {open && (
        <div className="border-t border-border p-3">
          <Tabs tabs={STAGES} active={stage} onChange={setStage} className="mb-3" />
          {stage === "readable" ? (
            <Readable call={call} />
          ) : (
            <JsonTree
              value={payload[stage]}
              filename={`call_${call.seq}_${stage}.json`}
              testId={`llm-call-${call.seq}-${stage}`}
            />
          )}
          {stage === "raw" && !call.raw_response_available && (
            <p className="mt-2 text-xs text-text-muted">
              The provider SDK did not expose a raw response for this call (for example, the scripted analyst used in
              MODEL MOCK evidence). The normalized response is what the run continued with.
            </p>
          )}
        </div>
      )}
    </article>
  );
}

function CompareView({ result }: { result: Comparison }) {
  const row = (label: string, ok: boolean) => (
    <li className="flex items-center gap-2">
      <Badge variant={ok ? "positive" : "warning"}>{ok ? "same" : "differs"}</Badge> {label}
    </li>
  );
  return (
    <div className="grid gap-3 md:grid-cols-2" data-testid="llm-compare">
      {(["a", "b"] as const).map((side) => (
        <div key={side} className="rounded-md border border-border p-3 text-xs">
          <div className="font-semibold text-text-primary">
            {side.toUpperCase()}: {String(result[side].model)} · {String(result[side].provider)}
          </div>
          <div className="text-text-muted">
            {String(result[side].provider_ms)} ms · stop {String(result[side].stop_reason)}
          </div>
          <pre className="mt-2 max-h-72 overflow-auto whitespace-pre-wrap">
            {JSON.stringify(result[side].tool_calls, null, 2)}
          </pre>
          {result[side].text ? <p className="mt-2">{String(result[side].text)}</p> : null}
        </div>
      ))}
      <ul className="space-y-1 text-xs md:col-span-2">
        {row("canonical request", result.request.same_canonical_request)}
        {row("system instructions", result.request.same_system)}
        {row("tool definitions", result.request.same_tools)}
        {row("tool choice", result.request.same_tool_choice)}
        {row(
          `messages (${result.request.messages.filter((m) => m.same).length}/${result.request.messages.length} identical)`,
          result.request.messages.every((m) => m.same),
        )}
        {row(`tool sequence (${result.response.tool_names_a.join(", ")} vs ${result.response.tool_names_b.join(", ")})`, result.response.same_tool_sequence)}
        {row("tool arguments", result.response.same_arguments)}
        {row("stop reason", result.response.same_stop_reason)}
      </ul>
    </div>
  );
}

export function LlmExchangeView({ runId }: { runId: string }) {
  const [data, setData] = React.useState<RunExchange | null>(null);
  const [error, setError] = React.useState("");
  const [tab, setTab] = React.useState("calls");
  const [picked, setPicked] = React.useState<string[]>([]);
  const [comparison, setComparison] = React.useState<Comparison | null>(null);

  React.useEffect(() => {
    readRunExchange(runId)
      .then(setData)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  }, [runId]);

  async function exportPackage() {
    const response = await fetch(exchangeExportUrl(runId), { credentials: "include" });
    if (!response.ok) {
      setError(`Export failed (${response.status}).`);
      return;
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `llm_exchange_${runId}.zip`;
    a.click();
    URL.revokeObjectURL(url);
  }

  if (error) {
    return (
      <div role="alert" className="rounded-md border border-border p-4 text-sm text-negative" data-testid="llm-exchange-error">
        {error}
      </div>
    );
  }
  if (!data) {
    return (
      <p className="flex items-center gap-2 text-sm text-text-muted">
        <Loader2 className="h-4 w-4 animate-spin" /> Reading the recorded exchange…
      </p>
    );
  }
  const growth = growthFigure(data.context_growth);
  const composition = compositionFigure(data.calls);
  const vis = data.data_visibility;
  return (
    <div className="space-y-4" data-testid="llm-exchange">
      <section className="rounded-lg border border-border bg-surface p-4">
        <div className="flex flex-wrap items-center gap-2">
          <ShieldCheck className="h-4 w-4 text-accent" />
          <h2 className="text-sm font-semibold text-text-primary">Full LLM Exchange</h2>
          <Badge variant={data.recorder.enabled ? "positive" : "warning"}>
            recorder {data.recorder.enabled ? "on" : "off"}
          </Badge>
          <Badge variant="outline">{data.recorder.calls_recorded} call(s) recorded</Badge>
          <button
            type="button"
            onClick={() => void exportPackage()}
            className="ml-auto inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 text-xs"
            data-testid="llm-exchange-export"
          >
            <Download className="h-3.5 w-3.5" /> Export llm_exchange package
          </button>
          <Link href="/ai-model-lab" className="text-xs text-accent underline">
            Compare in AI Model Lab
          </Link>
        </div>
        <p className="mt-1 text-xs text-text-muted">“{data.question}” · release {data.release_id}</p>
        <ul className="mt-2 list-disc pl-5 text-xs text-text-muted">
          {data.notes.map((n) => (
            <li key={n}>{n}</li>
          ))}
        </ul>
        {!data.recorder.enabled && data.calls.length === 0 && (
          <p className="mt-2 text-xs text-warning">
            No calls were recorded for this run: the recorder ({data.recorder.flag}) was off when it ran. Nothing is
            reconstructed after the fact.
          </p>
        )}
      </section>
      <Tabs
        tabs={[
          { id: "calls", label: "Calls", count: data.calls.length },
          { id: "timeline", label: "Timeline", count: data.timeline.length },
          { id: "composition", label: "Context composition" },
          { id: "growth", label: "Context growth" },
          { id: "visibility", label: "Data visibility" },
        ]}
        active={tab}
        onChange={setTab}
      />
      {tab === "calls" && (
        <div className="space-y-2">
          {picked.length === 2 && (
            <button
              type="button"
              onClick={() => compareExchanges(picked[0], picked[1]).then(setComparison).catch((e) => setError(String(e)))}
              className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 text-xs"
              data-testid="llm-compare-button"
            >
              <GitCompare className="h-3.5 w-3.5" /> Compare the two selected calls
            </button>
          )}
          {comparison && <CompareView result={comparison} />}
          {data.calls.map((call) => (
            <CallCard
              key={call.exchange_id}
              call={call}
              selected={picked.includes(call.exchange_id)}
              onSelect={(checked) =>
                setPicked((prev) =>
                  checked ? [...prev.filter((p) => p !== call.exchange_id), call.exchange_id].slice(-2) : prev.filter((p) => p !== call.exchange_id),
                )
              }
            />
          ))}
        </div>
      )}
      {tab === "timeline" && (
        <ol className="space-y-1 text-xs" data-testid="llm-timeline">
          {data.timeline.map((item, i) => (
            <li
              key={i}
              className={cn(
                "rounded border px-2 py-1",
                item.kind === "llm_call" ? "border-accent bg-accent-muted" : "border-border",
              )}
            >
              <span className="font-medium">{item.kind === "llm_call" ? "MODEL" : "CreditProbe"}</span> · {item.label}{" "}
              <span className="text-text-muted">{item.detail}</span>
            </li>
          ))}
        </ol>
      )}
      {tab === "composition" && (
        <ChartCard
          title="What each request was made of"
          subtitle="Measured bytes of the sanitized request, by component. Token split per component is an estimate (bytes ÷ 4); totals below are provider-reported."
          data={composition.data}
          layout={composition.layout}
          testId="llm-composition"
          table={{
            columns: [
              { key: "seq", label: "Call" },
              { key: "component", label: "Component" },
              { key: "detail", label: "Detail" },
              { key: "bytes", label: "Bytes (measured)", align: "right" },
              { key: "estimated_tokens", label: "Tokens (estimate)", align: "right" },
            ],
            rows: data.calls.flatMap((c) =>
              (c.context_composition?.parts ?? []).map((p) => ({ seq: c.seq, ...p })),
            ),
          }}
        />
      )}
      {tab === "growth" && (
        <ChartCard
          title="Context growth, call by call"
          subtitle="Request size in measured KB; input tokens as reported by the provider."
          data={growth.data}
          layout={growth.layout}
          testId="llm-growth"
          table={{
            columns: [
              { key: "seq", label: "Call" },
              { key: "purpose", label: "Purpose" },
              { key: "total_bytes", label: "Bytes", align: "right" },
              { key: "growth_bytes", label: "Growth (bytes)", align: "right" },
              { key: "messages", label: "Messages", align: "right" },
              { key: "tool_result_bytes", label: "Tool-result bytes", align: "right" },
              { key: "input_tokens_exact", label: "Input tokens (exact)", align: "right" },
              { key: "output_tokens_exact", label: "Output tokens (exact)", align: "right" },
            ],
            rows: data.context_growth as unknown as Record<string, unknown>[],
          }}
        />
      )}
      {tab === "visibility" && (
        <div className="grid gap-3 md:grid-cols-2" data-testid="llm-visibility">
          <section className="rounded-lg border border-border bg-surface p-4">
            <h3 className="text-sm font-semibold text-text-primary">AVAILABLE TO CREDITPROBE</h3>
            <p className="text-xs text-text-muted">Held inside the governed runtime for this run. Not sent anywhere.</p>
            <dl className="mt-2 grid grid-cols-2 gap-1 text-xs">
              <dt>Release</dt>
              <dd className="mono">{vis.available_to_creditprobe.release_id}</dd>
              <dt>Rows in the release</dt>
              <dd className="tabular">{count(vis.available_to_creditprobe.release_rows_total)}</dd>
              <dt>Rows produced by this run&apos;s analyses</dt>
              <dd className="tabular">{count(vis.available_to_creditprobe.artifact_rows_produced)}</dd>
              <dt>Artifacts computed</dt>
              <dd className="tabular">{vis.available_to_creditprobe.artifacts.length}</dd>
            </dl>
          </section>
          <section className="rounded-lg border border-border bg-surface p-4">
            <h3 className="text-sm font-semibold text-text-primary">ACTUALLY TRANSMITTED TO THE MODEL</h3>
            <p className="text-xs text-text-muted">{vis.actually_transmitted_to_model.basis}</p>
            <dl className="mt-2 grid grid-cols-2 gap-1 text-xs">
              <dt>Tool results sent</dt>
              <dd className="tabular">{vis.actually_transmitted_to_model.unique_tool_results}</dd>
              <dt>Rows inside them</dt>
              <dd className="tabular">{count(vis.actually_transmitted_to_model.rows)}</dd>
              <dt>Bytes of tool results</dt>
              <dd className="tabular">{count(vis.actually_transmitted_to_model.bytes)}</dd>
            </dl>
            <button
              type="button"
              className="mt-2 text-xs text-accent underline"
              onClick={() => downloadText(JSON.stringify(vis, null, 2), `data_visibility_${runId}.json`, "application/json")}
            >
              Download data-visibility record
            </button>
          </section>
        </div>
      )}
    </div>
  );
}
