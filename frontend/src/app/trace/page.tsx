"use client";

import Link from "next/link";
import { Clock, GitBranch, Search, Sparkles } from "lucide-react";

import { PageHeader } from "@/components/layout/page-header";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import { useAsync } from "@/lib/hooks";

/**
 * Trace & Lineage.
 *
 * A trace belongs to a specific analysis run, so this page opens with the runs
 * that have one — every question asked of CreditProbe — and explains the model beneath
 * them.
 */
export default function TracePage() {
  const recent = useAsync(() => api.recentInvestigations(12), []);
  const mode = useAsync(() => api.askMode(), []);

  return (
    <div className="space-y-8">
      <PageHeader
        title="Trace & Lineage"
        description="How a particular answer was created. Not an audit log — an inspectable map of every step from question to figure, emitted by the execution itself."
        status="live"
        actions={
          <Button size="sm" asChild>
            <Link href="/?focus=ask">
              <Sparkles aria-hidden />
              Ask a question
            </Link>
          </Button>
        }
      />

      <section>
        <h2 className="mb-3 text-[10px] font-semibold uppercase tracking-[0.14em] text-text-muted">
          Open a reasoning map
        </h2>
        {recent.loading && <Skeleton className="h-40 w-full" />}
        {recent.error && (
          <Card className="border-negative/40 p-4 text-sm text-negative">{recent.error}</Card>
        )}
        {recent.data &&
          (recent.data.investigations.length > 0 ? (
            <Card className="divide-y divide-border">
              {recent.data.investigations.map((item) => (
                <Link
                  key={item.analysis_run_id}
                  href={`/trace/${item.analysis_run_id}`}
                  className="flex items-start gap-3 px-5 py-3.5 transition-colors hover:bg-surface-hover"
                >
                  <Search className="mt-0.5 size-4 shrink-0 text-text-muted" aria-hidden />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-medium text-text-primary">
                      {item.question}
                    </span>
                    <span className="mt-0.5 line-clamp-1 block text-xs text-text-muted">
                      {item.intent}
                    </span>
                  </span>
                  <span className="hidden shrink-0 items-center gap-3 text-[11px] text-text-muted sm:flex">
                    <span className="flex items-center gap-1">
                      <Clock className="size-3" aria-hidden />
                      {item.duration_ms ?? "—"}ms
                    </span>
                    <span className="flex items-center gap-1 font-medium text-accent">
                      <GitBranch className="size-3" aria-hidden />
                      Trace
                    </span>
                  </span>
                </Link>
              ))}
            </Card>
          ) : (
            <Card className="px-5 py-10 text-center">
              <p className="text-sm text-text-secondary">No traces recorded yet.</p>
              <p className="mt-1 text-xs text-text-muted">
                Every analytical result in CreditProbe carries a Trace button. Ask a question, or open a
                lens, and the map appears here.
              </p>
              <Button className="mt-4" size="sm" asChild>
                <Link href="/?focus=ask">Open the Cockpit</Link>
              </Button>
            </Card>
          ))}
      </section>

      <section className="grid gap-4 lg:grid-cols-2">
        <Card className="p-6">
          <h3 className="mb-3 text-sm font-semibold text-text-primary">The design rule</h3>
          <p className="text-sm leading-relaxed text-text-secondary">
            Trace is emitted <strong>by</strong> execution. It is never written afterwards, and it
            is never written by a language model. Each step stamps its own card as it runs — which
            dataset, which variables, which filters, how many rows before and after, which
            function at which version, how long it took. The map <em>is</em> the execution record,
            so it cannot drift from the truth.
          </p>
        </Card>

        <Card className="p-6">
          <h3 className="mb-3 text-sm font-semibold text-text-primary">What you can do on a map</h3>
          <ul className="space-y-2 text-sm text-text-secondary">
            {[
              "Pan, zoom and fit the whole reasoning map to the screen",
              "Select any step to see what fed it and what it feeds, with the rest dimmed",
              "Collapse an analysis to a single node, or expand it back to every recorded step",
              "Ask for a change in plain English, see exactly which steps it would re-run, then apply it",
              "Switch between Original, Version 2 and every later version — none is ever overwritten",
            ].map((line) => (
              <li key={line} className="flex gap-2">
                <span aria-hidden className="text-text-muted">
                  ·
                </span>
                <span>{line}</span>
              </li>
            ))}
          </ul>
          {mode.data && (
            <p className="mt-4 border-t border-border pt-3 text-xs text-text-muted">
              {mode.data.supported_modifications.length} kinds of change are supported. Anything
              outside them is refused and listed, never approximated.
            </p>
          )}
        </Card>
      </section>
    </div>
  );
}
