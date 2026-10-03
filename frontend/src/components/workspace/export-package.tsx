"use client";

/**
 * "Export package": the governed ZIP for an object -- objects as stored,
 * exact tables, Trace, manifest hashes -- with THIS page's charts attached
 * as SVG snapshots and Plotly figure specs, rendered from the same data the
 * reader is looking at. Auditors may add the sanitized LLM exchange.
 */

import * as React from "react";
import Link from "next/link";
import { Archive, Loader2, ShieldCheck } from "lucide-react";

import { loadPlotly } from "@/components/viz/plotly-chart";
import { downloadPackage, snapshotName, type Snapshot } from "@/lib/workspace/trace";
import { withBack } from "@/lib/workspace/nav";

/** At most this many charts are attached (the server caps the total). */
const MAX_CHARTS = 10;

async function collectSnapshots(scope: Element | null): Promise<Snapshot[]> {
  if (!scope) return [];
  const Plotly = await loadPlotly();
  const charts = Array.from(scope.querySelectorAll<HTMLElement>('[data-plotly="true"][data-rendered="true"]')).slice(0, MAX_CHARTS);
  const out: Snapshot[] = [];
  for (const [i, el] of charts.entries()) {
    const name = snapshotName(el.getAttribute("data-testid"), i);
    try {
      const svg = await Plotly.toImage(el, { format: "svg", width: 1200, height: Math.max(el.clientHeight, 360) });
      out.push({ name, format: "svg", data: svg });
      const gd = el as HTMLElement & { data?: unknown; layout?: unknown };
      out.push({ name, format: "plotly", data: { data: gd.data ?? [], layout: gd.layout ?? {} } });
    } catch {
      /* a chart that cannot be rasterised is simply not attached */
    }
  }
  return out;
}

export function ExportPackage({ objectId, scopeSelector, testId = "export-package", compact = false }: { objectId: string; scopeSelector?: string; testId?: string; compact?: boolean }) {
  const [busy, setBusy] = React.useState(false);
  const [llm, setLlm] = React.useState(false);
  const [note, setNote] = React.useState("");
  const [error, setError] = React.useState("");
  // One governed mutation at a time: a double-click fires twice before
  // `busy` disables the control; the ref closes that window.
  const inFlight = React.useRef(false);
  async function run() {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    setError("");
    setNote("");
    try {
      const scope = scopeSelector ? document.querySelector(scopeSelector) : null;
      const snapshots = await collectSnapshots(scope);
      const out = await downloadPackage(objectId, { includeLlmExchange: llm, snapshots });
      setNote(`Package downloaded: ${out.files} files, ${snapshots.filter((s) => s.format === "svg").length} chart snapshot(s).`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }
  return (
    <span className="inline-flex flex-wrap items-center gap-1 text-xs" data-testid={testId}>
      <button type="button" disabled={busy} onClick={() => void run()} className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 disabled:opacity-50" data-testid={`${testId}-go`}>
        {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Archive className="h-3.5 w-3.5" />} Export package
      </button>
      {!compact && (
        <label className="inline-flex items-center gap-1 text-text-muted" title="Auditors, model-risk reviewers and administrators only">
          <input type="checkbox" checked={llm} onChange={(e) => setLlm(e.target.checked)} data-testid={`${testId}-llm`} /> incl. LLM exchange
        </label>
      )}
      <Link href={withBack(`/trace/object/${encodeURIComponent(objectId)}`)} className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1" data-testid={`${testId}-trace`}>
        <ShieldCheck className="h-3.5 w-3.5" /> Trace
      </Link>
      {note && <span className="text-positive" data-testid={`${testId}-note`}>{note}</span>}
      {error && <span className="text-negative" data-testid={`${testId}-error`}>{error}</span>}
    </span>
  );
}
