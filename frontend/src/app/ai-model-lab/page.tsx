"use client";

/**
 * AI Model Lab: compare models call by call, over the SAME LLM exchange
 * records the Trace shows. There is no second recorder: a replay sends a
 * recorded canonical request to another configured model and is itself
 * recorded, linked to the call it replays.
 */

import * as React from "react";
import Link from "next/link";
import { FlaskConical, GitCompare, Loader2, Play } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import {
  compareExchanges,
  labTargets,
  listLabExchanges,
  replayExchange,
  type Comparison,
  type LabRow,
} from "@/lib/workspace/llm-exchange";

export default function AiModelLabPage() {
  const [rows, setRows] = React.useState<LabRow[] | null>(null);
  const [models, setModels] = React.useState<string[]>([]);
  const [model, setModel] = React.useState("");
  const [a, setA] = React.useState("");
  const [b, setB] = React.useState("");
  const [comparison, setComparison] = React.useState<Comparison | null>(null);
  const [targets, setTargets] = React.useState<{ target: string; label: string; configured: boolean; requires: string }[]>([]);
  const [note, setNote] = React.useState("");
  const [error, setError] = React.useState("");
  const [busy, setBusy] = React.useState(false);

  const load = React.useCallback(() => {
    listLabExchanges({ model })
      .then((r) => {
        setRows(r.exchanges);
        setModels(r.models);
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  }, [model]);

  React.useEffect(load, [load]);
  React.useEffect(() => {
    labTargets()
      .then((t) => {
        setTargets(t.targets);
        setNote(t.note);
      })
      .catch(() => undefined);
  }, []);

  async function replay(target: string) {
    if (!a) return;
    setBusy(true);
    setError("");
    try {
      const out = await replayExchange(a, target);
      if (out.replay_exchange_id) {
        setB(out.replay_exchange_id);
        setComparison(await compareExchanges(a, out.replay_exchange_id));
      }
      if (out.error) setError(out.error);
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto w-full max-w-6xl space-y-4 px-4 py-8" data-testid="ai-model-lab">
      <header>
        <h1 className="flex items-center gap-2 text-lg font-semibold text-text-primary">
          <FlaskConical className="h-5 w-5 text-accent" /> AI Model Lab
        </h1>
        <p className="text-sm text-text-muted">
          Compare Opus and open-weight models call by call, on the exact requests CreditProbe recorded. Every row below
          is a Full LLM Exchange record; open its run to see the whole trace.
        </p>
      </header>
      {error && (
        <p role="alert" className="rounded-md border border-border p-2 text-sm text-negative">
          {error}
        </p>
      )}
      <section className="rounded-lg border border-border bg-surface p-4">
        <div className="mb-2 flex flex-wrap items-center gap-2 text-xs">
          <label>
            Model{" "}
            <select value={model} onChange={(e) => setModel(e.target.value)} className="rounded border border-border bg-surface px-2 py-1">
              <option value="">all</option>
              {models.map((m) => (
                <option key={m}>{m}</option>
              ))}
            </select>
          </label>
          <span className="text-text-muted">Pick A and B to compare. A can be replayed on another configured model.</span>
        </div>
        {rows === null ? (
          <p className="flex items-center gap-2 text-sm text-text-muted">
            <Loader2 className="h-4 w-4 animate-spin" /> Loading recorded calls…
          </p>
        ) : rows.length === 0 ? (
          <p className="text-sm text-text-muted" data-testid="ai-model-lab-empty">
            No model calls have been recorded yet. Turn on the recorder (COCKPIT_V4_LLM_EXCHANGE_TRACE) and ask a question
            in the Cockpit: every call it makes appears here.
          </p>
        ) : (
          <div className="max-h-[28rem] overflow-auto">
            <table className="w-full text-xs">
              <thead className="sticky top-0 bg-surface-sunken text-left">
                <tr>
                  <th className="px-2 py-1">A</th>
                  <th className="px-2 py-1">B</th>
                  <th className="px-2 py-1">When</th>
                  <th className="px-2 py-1">Surface</th>
                  <th className="px-2 py-1">Purpose</th>
                  <th className="px-2 py-1">Model</th>
                  <th className="px-2 py-1">Status</th>
                  <th className="px-2 py-1 text-right">ms</th>
                  <th className="px-2 py-1">Run</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.exchange_id} className="border-t border-border">
                    <td className="px-2 py-1">
                      <input type="radio" name="a" checked={a === r.exchange_id} onChange={() => setA(r.exchange_id)} aria-label="Choose as A" />
                    </td>
                    <td className="px-2 py-1">
                      <input type="radio" name="b" checked={b === r.exchange_id} onChange={() => setB(r.exchange_id)} aria-label="Choose as B" />
                    </td>
                    <td className="px-2 py-1">{new Date(r.started_at * 1000).toLocaleString()}</td>
                    <td className="px-2 py-1">{r.surface}</td>
                    <td className="px-2 py-1">{r.purpose}</td>
                    <td className="px-2 py-1">
                      {r.resolved_model} {r.replay_of && <Badge variant="info">replay</Badge>}
                    </td>
                    <td className="px-2 py-1">{r.status}</td>
                    <td className="px-2 py-1 text-right tabular">{r.provider_ms}</td>
                    <td className="px-2 py-1">
                      {r.run_id.startsWith("run-") ? (
                        <Link className="text-accent underline" href={`/trace/llm-exchange/${r.run_id}`}>
                          trace
                        </Link>
                      ) : (
                        <span className="text-text-muted">{r.run_id.slice(0, 18)}</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <div className="mt-3 flex flex-wrap gap-2">
          <button
            type="button"
            disabled={!a || !b}
            onClick={() => compareExchanges(a, b).then(setComparison).catch((e) => setError(String(e)))}
            className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 text-xs disabled:opacity-50"
          >
            <GitCompare className="h-3.5 w-3.5" /> Compare A and B
          </button>
          {targets.map((t) => (
            <button
              key={t.target}
              type="button"
              disabled={!a || !t.configured || busy}
              title={t.configured ? "" : `Not configured: needs ${t.requires}`}
              onClick={() => void replay(t.target)}
              className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 text-xs disabled:opacity-50"
            >
              <Play className="h-3.5 w-3.5" /> Replay A on {t.label}
              {!t.configured && <span className="text-text-muted"> (not configured)</span>}
            </button>
          ))}
        </div>
        {note && <p className="mt-2 text-xs text-text-muted">{note}</p>}
      </section>
      {comparison && (
        <section className="rounded-lg border border-border bg-surface p-4" data-testid="ai-model-lab-compare">
          <h2 className="mb-2 text-sm font-semibold">Call-by-call comparison</h2>
          <div className="grid gap-3 md:grid-cols-2 text-xs">
            {(["a", "b"] as const).map((side) => (
              <div key={side} className="rounded border border-border p-2">
                <div className="font-semibold">
                  {side.toUpperCase()} · {String(comparison[side].model)} ({String(comparison[side].provider)})
                </div>
                <div className="text-text-muted">
                  {String(comparison[side].provider_ms)} ms · stop {String(comparison[side].stop_reason)} · usage{" "}
                  {JSON.stringify(comparison[side].usage)}
                </div>
                <pre className="mt-1 max-h-72 overflow-auto whitespace-pre-wrap">
                  {JSON.stringify(comparison[side].tool_calls, null, 2)}
                </pre>
              </div>
            ))}
          </div>
          <ul className="mt-2 grid gap-1 text-xs md:grid-cols-2">
            <li>System identical: {String(comparison.request.same_system)}</li>
            <li>Tools identical: {String(comparison.request.same_tools)}</li>
            <li>
              Messages identical: {comparison.request.messages.filter((m) => m.same).length}/
              {comparison.request.messages.length}
            </li>
            <li>Same tool sequence: {String(comparison.response.same_tool_sequence)}</li>
            <li>Same arguments: {String(comparison.response.same_arguments)}</li>
            <li>Same stop reason: {String(comparison.response.same_stop_reason)}</li>
          </ul>
        </section>
      )}
    </main>
  );
}
