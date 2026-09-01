"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import * as React from "react";
import { ArrowRight, LayoutGrid, Loader2, Sparkles } from "lucide-react";

import { PageHeader } from "@/components/layout/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import { useAsync } from "@/lib/hooks";

/**
 * The Lens library.
 *
 * A Lens is a live view of the book for one audience, built by describing it.
 * Opening one runs its analyses against whatever is published now, so a Lens
 * cannot quietly go stale — there are no stored figures to go stale.
 *
 * The CRO Lens is a hand-built screen and stays where it is; everything else
 * here is a Lens somebody made by asking for it.
 */
export default function LensesPage() {
  const router = useRouter();
  const library = useAsync(() => api.lensList(), []);
  const [request, setRequest] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [refusals, setRefusals] = React.useState<string[]>([]);
  const [error, setError] = React.useState<string | null>(null);

  async function build() {
    if (!request.trim() || busy) return;
    setBusy(true);
    setError(null);
    setRefusals([]);
    try {
      const body = await api.buildLens(request.trim());
      if (body.lens) {
        router.push(`/lenses/${body.lens.id}`);
        return;
      }
      setRefusals(body.proposal.refusals);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-7">
      <PageHeader
        title="Lenses"
        description="A live view of the book for one audience. Describe what it should show and CreditProbe builds it from the certified analyses; ask for a change and it revises. Opening one runs the analyses against what is published now, so nothing on a lens is a stored figure."
        status="live"
      />

      <Card className="p-5">
        <label htmlFor="lens-request" className="text-xs font-medium text-text-secondary">
          What should this lens show?
        </label>
        <div className="mt-1.5 flex flex-wrap gap-2">
          <input
            id="lens-request"
            value={request}
            onChange={(e) => setRequest(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void build();
            }}
            placeholder="IFRS 9 staging, ECL coverage and where the SICR triggers are firing"
            className="h-9 min-w-0 flex-1 rounded-md border border-border bg-surface px-3 text-sm text-text-primary placeholder:text-text-muted focus:border-accent focus:outline-none"
          />
          <Button size="sm" onClick={build} disabled={busy || !request.trim()}>
            {busy ? <Loader2 className="animate-spin" aria-hidden /> : <Sparkles aria-hidden />}
            Build it
          </Button>
        </div>
        <p className="mt-2 text-[11px] leading-relaxed text-text-muted">
          Your description is matched against the analysis library, so a lens can
          only ever contain analyses that exist. Anything it cannot find, it says
          so rather than approximating with the nearest panel.
        </p>
        {refusals.map((refusal) => (
          <p key={refusal} className="mt-2 text-xs text-warning">
            {refusal}
          </p>
        ))}
        {error && <p className="mt-2 text-xs text-negative">{error}</p>}
      </Card>

      <section>
        <h2 className="mb-3 text-[10px] font-semibold uppercase tracking-[0.14em] text-text-muted">
          Built for the executive
        </h2>
        <Link href="/lenses/cro" className="group block">
          <Card className="flex flex-col p-5 transition-colors hover:bg-surface-hover">
            <div className="mb-2 flex items-start justify-between gap-3">
              <LayoutGrid className="size-5 shrink-0 text-text-muted" aria-hidden />
              <Badge variant="accent">Live</Badge>
            </div>
            <h3 className="text-sm font-semibold text-text-primary">
              CRO Portfolio Lens
            </h3>
            <p className="mt-1.5 text-xs leading-relaxed text-text-muted">
              The monthly executive view: position, staging, coverage,
              concentration, migration and the names driving deterioration —
              arranged as an argument rather than a grid of tiles.
            </p>
            <p className="mt-3 flex items-center justify-between border-t border-border pt-3 text-[11px] text-text-muted">
              Chief Risk Officer · Board Risk Committee
              <span className="inline-flex items-center gap-1 font-medium text-accent opacity-0 transition-opacity group-hover:opacity-100">
                Open <ArrowRight className="size-3" aria-hidden />
              </span>
            </p>
          </Card>
        </Link>
      </section>

      <section>
        <h2 className="mb-3 text-[10px] font-semibold uppercase tracking-[0.14em] text-text-muted">
          Your lenses
        </h2>
        {library.loading && <Skeleton className="h-40 w-full" />}
        {library.error && (
          <Card className="border-negative/40 p-4 text-sm text-negative">
            {library.error}
          </Card>
        )}
        {library.data &&
          (library.data.lenses.length > 0 ? (
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              {library.data.lenses.map((lens) => (
                <Link key={lens.id} href={`/lenses/${lens.id}`} className="group">
                  <Card className="flex h-full flex-col p-5 transition-colors hover:bg-surface-hover">
                    <div className="mb-2 flex items-start justify-between gap-3">
                      <LayoutGrid
                        className="size-5 shrink-0 text-text-muted"
                        aria-hidden
                      />
                      <div className="flex items-center gap-1.5">
                        {lens.origin === "ai" && (
                          <Badge variant="outline">Built by asking</Badge>
                        )}
                        <Badge
                          variant={lens.status === "published" ? "accent" : "outline"}
                        >
                          {lens.status}
                        </Badge>
                      </div>
                    </div>
                    <h3 className="text-sm font-semibold text-text-primary">
                      {lens.name}
                    </h3>
                    {lens.description && (
                      <p className="mt-1.5 line-clamp-3 flex-1 text-xs leading-relaxed text-text-muted">
                        {lens.description}
                      </p>
                    )}
                    <p className="mt-3 border-t border-border pt-3 text-[11px] text-text-muted">
                      {lens.panels.length}{" "}
                      {lens.panels.length === 1 ? "panel" : "panels"} · version{" "}
                      {lens.version}
                    </p>
                  </Card>
                </Link>
              ))}
            </div>
          ) : (
            <EmptyState
              icon={LayoutGrid}
              title="No lenses of your own yet"
              description="Describe one above. It is built from the certified analyses, runs live, and can be changed later by asking."
            />
          ))}
      </section>
    </div>
  );
}
