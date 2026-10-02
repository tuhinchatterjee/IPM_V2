"use client";

/**
 * Lens Library (§32, §45): persona dashboards on governed metrics, plus
 * one-prompt creation. A prompt returns a PREVIEW (KPIs, charts, tables,
 * refresh rule, breach rules); nothing is saved until you confirm. Refine the
 * preview by asking again ("add default-entry rate", "remove utilisation",
 * "weekly"). Arriving from an investigation or a Cockpit thread proposes a
 * Lens scoped to that analysis.
 */

import * as React from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Loader2, Sparkles } from "lucide-react";

import { listLenses, proposeLens, saveLens, type LensCard, type Proposal } from "@/lib/workspace/lenses";
import { OriginBackLink } from "@/components/workspace/origin-back";
import { urlWith, withBack } from "@/lib/workspace/nav";

const CADENCE: Record<string, string> = {
  daily: "Daily",
  weekly: "Weekly",
  monthly: "Monthly",
  on_publication: "On data publication",
  on_result: "On scenario result",
  continuous: "Continuous (every refresh)",
  manual: "Manual",
};

export function LensLibrary() {
  const params = useSearchParams();
  const router = useRouter();
  const [lib, setLib] = React.useState<{ lenses: LensCard[]; total: number } | null>(null);
  const [q, setQ] = React.useState(params.get("q") ?? "");
  const [prompt, setPrompt] = React.useState("");
  const [proposal, setProposal] = React.useState<Proposal | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");
  const origin = React.useRef(false);

  React.useEffect(() => {
    listLenses()
      .then(setLib)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  // Arriving from an investigation or a Cockpit thread: propose a Lens
  // scoped to that analysis (a preview; nothing is saved).
  React.useEffect(() => {
    if (origin.current) return;
    const inv = params.get("from_investigation");
    const thread = params.get("from_thread");
    if (!inv && !thread) return;
    origin.current = true;
    proposeLens(inv ? { from_investigation: inv } : { from_thread: thread ?? "" })
      .then((p) => {
        setProposal(p);
        // The origin has been consumed: Back to this page shows the library,
        // it does not propose (and invite saving) the same Lens again.
        router.replace(urlWith({ from_investigation: null, from_thread: null }), { scroll: false });
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  }, [params, router]);

  // The filter text is part of the address, so Back from a Lens restores it.
  React.useEffect(() => {
    const t = setTimeout(() => {
      const next = urlWith({ q: q.trim() || null });
      if (next && next !== `${window.location.pathname}${window.location.search}`) router.replace(next, { scroll: false });
    }, 250);
    return () => clearTimeout(t);
  }, [q, router]);

  async function propose(base?: Proposal) {
    setBusy(true);
    setError("");
    try {
      setProposal(await proposeLens(base ? { prompt, base: base.spec } : { prompt }));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function save() {
    if (!proposal) return;
    setBusy(true);
    try {
      const obj = await saveLens(proposal.spec, proposal.source);
      router.push(withBack(`/lenses/${obj.object_id}`, urlWith({ from_investigation: null, from_thread: null })));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  }

  const needle = q.trim().toLowerCase();
  const shown = (lib?.lenses ?? []).filter((c) => !needle || `${c.name} ${c.persona} ${c.description}`.toLowerCase().includes(needle));

  return (
    <div className="space-y-4" data-testid="lens-library" data-total={lib?.total ?? 0}>
      <OriginBackLink testId="lens-library-back" />
      <header className="flex flex-wrap items-end gap-3">
        <div>
          <h1 className="text-lg font-semibold">Lenses</h1>
          <p className="text-xs text-text-muted">Persistent, refreshable dashboards. Every KPI and chart is a governed catalogue metric; opening a Lens evaluates it on the book as published now.</p>
        </div>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Filter Lenses…" className="ml-auto rounded border border-border bg-surface px-2 py-1 text-sm" data-testid="lens-search" />
      </header>

      <section className="space-y-2 rounded-xl border border-border bg-surface p-3" data-testid="lens-create">
        <label className="text-sm font-semibold" htmlFor="lens-prompt">
          Describe a dashboard
        </label>
        <div className="flex flex-wrap gap-2">
          <input
            id="lens-prompt"
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder="e.g. Credit card risk with Stage 2 EAD share and default-entry rate, weekly"
            className="min-w-[24rem] flex-1 rounded border border-border bg-surface px-2 py-1.5 text-sm"
            data-testid="lens-prompt"
          />
          <button type="button" disabled={busy || (!prompt.trim() && !proposal)} onClick={() => void propose(proposal ?? undefined)} className="inline-flex items-center gap-1 rounded-md bg-accent px-3 py-1.5 text-sm text-accent-contrast disabled:opacity-40" data-testid="lens-propose">
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />} {proposal ? "Refine preview" : "Preview"}
          </button>
          {proposal && (
            <button type="button" onClick={() => setProposal(null)} className="rounded-md border border-border px-3 py-1.5 text-sm" data-testid="lens-discard">
              Discard
            </button>
          )}
        </div>
        {error && (
          <p role="alert" className="text-sm text-negative" data-testid="lens-error">
            {error}
          </p>
        )}
        {proposal && (
          <div className="space-y-2 rounded-lg border border-accent p-3 text-xs" data-testid="lens-preview" data-kpis={proposal.summary.kpis} data-charts={proposal.summary.charts}>
            <p className="text-sm font-semibold">
              Preview — not saved: {proposal.spec.name}
            </p>
            <p data-testid="lens-preview-summary">
              {proposal.summary.kpis} KPIs · {proposal.summary.charts} charts · {proposal.summary.tables} tables · {proposal.summary.metrics} governed metrics · {proposal.summary.breach_rules} breach rules · refresh {CADENCE[proposal.summary.refresh] ?? proposal.summary.refresh}
            </p>
            <ul className="list-disc pl-5 text-text-muted">
              {proposal.reasons.map((r, i) => (
                <li key={i}>{r}</li>
              ))}
            </ul>
            <div className="grid gap-1 md:grid-cols-2">
              {proposal.spec.visuals.map((v) => (
                <div key={v.visual_id} className="rounded border border-border px-2 py-1">
                  <span className="font-mono text-text-muted">{v.type}</span> {v.title || v.metric_id} · {v.domain}
                  {v.group_by ? ` by ${v.group_by}` : ""} · {(v.metric_ids ?? [v.metric_id]).join(", ")}
                </div>
              ))}
            </div>
            {Object.keys(proposal.spec.filters ?? {}).length > 0 && <p>Scope: {JSON.stringify(proposal.spec.filters)}</p>}
            <button type="button" disabled={busy} onClick={() => void save()} className="rounded-md bg-accent px-3 py-1.5 text-sm text-accent-contrast" data-testid="lens-save">
              Save this Lens
            </button>
          </div>
        )}
      </section>

      {lib && !shown.length && (
        <p className="text-sm text-text-muted" data-testid="lens-empty-by-filter">
          No Lens matches “{q}” (EMPTY_BY_FILTER).
        </p>
      )}
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3" data-testid="lens-grid">
        {shown.map((c) => (
          <Link key={c.object_id} href={withBack(`/lenses/${c.object_id}`, urlWith({ q: q.trim() || null, from_investigation: null, from_thread: null }))} className="block rounded-xl border border-border bg-surface p-3 hover:border-accent" data-testid="lens-card" data-lens-id={c.lens_id} data-object-id={c.object_id}>
            <div className="flex items-start gap-2">
              <div className="min-w-0">
                <div className="text-xs text-text-muted">
                  {c.lens_id || "My Lens"} · {c.persona}
                </div>
                <div className="font-semibold">{c.name}</div>
              </div>
              <span className="ml-auto whitespace-nowrap rounded bg-surface-sunken px-1.5 text-[10px]">{c.domain_scope.join(" + ")}</span>
            </div>
            <p className="mt-1 line-clamp-2 text-xs text-text-muted">{c.description}</p>
            <div className="mt-2 flex flex-wrap gap-2 text-[11px]">
              <span>{c.kpis} KPIs</span>
              <span>{c.charts} charts</span>
              <span>{c.tables} tables</span>
              <span>{c.breach_rules} rules</span>
              <span>{CADENCE[c.refresh.cadence] ?? c.refresh.cadence}</span>
              {c.last_refresh && (
                <span className={c.last_refresh.breaches ? "text-negative" : "text-text-muted"}>
                  last refresh: {c.last_refresh.breaches} breaches, {c.last_refresh.material_changes} material changes
                </span>
              )}
            </div>
          </Link>
        ))}
      </div>
    </div>
  );
}
