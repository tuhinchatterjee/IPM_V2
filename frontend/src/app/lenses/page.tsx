"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import * as React from "react";
import { ArrowRight, LayoutGrid, Plus, Sparkles } from "lucide-react";

import { PageHeader } from "@/components/layout/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty";
import { Skeleton } from "@/components/ui/skeleton";
import { api, type Lens, type ShippedLens } from "@/lib/api";
import { useAsync } from "@/lib/hooks";

/**
 * The Lens library.
 *
 * A Lens is a live view of the book for one audience. Opening one runs its
 * metrics against whatever is published now, so a Lens cannot quietly go
 * stale — there are no stored figures to go stale.
 *
 * Three bands, and the split is the point. A dashboard CreditProbe ships is
 * not one of "your lenses": it is the answer to "what would a competent head
 * of this portfolio put on one screen", and burying it in a list of personal
 * views is how somebody rebuilds a lens that already exists. Each shipped one
 * says who it is for and how much is on it, so the choice can be made from
 * the library rather than by opening all four.
 *
 * The single "describe your lens and it appears" box that used to sit at the
 * top is gone. It turned a sentence into a lens in one shot: you described
 * everything at once, and whatever the matcher did not understand was
 * silently absent from what you got. `/lenses/new` asks the same matcher the
 * same things one at a time, and shows what it understood before anything is
 * stored.
 */
export default function LensesPage() {
  const router = useRouter();
  const [said, setSaid] = React.useState("");
  const library = useAsync(() => api.lensList(), []);
  const shipped: ShippedLens[] = library.data?.shipped ?? [];
  const bySlug = new Map<string, Lens>(
    (library.data?.lenses ?? []).map((lens) => [lens.slug, lens]),
  );
  const mine = (library.data?.lenses ?? []).filter(
    (lens) => !shipped.some((spec) => spec.slug === lens.slug),
  );

  return (
    <div className="space-y-7">
      <PageHeader
        title="Lenses"
        description="A live view of the book for one audience. Every figure is calculated when you open it, against what is published now, so nothing on a lens is a stored number. Each one carries its own definitions: what every metric means, how it was calculated, and what the lens deliberately does not show."
        status="live"
        actions={
          <Button size="sm" asChild>
            <Link href="/lenses/new">
              <Plus aria-hidden />
              Create a lens
            </Link>
          </Button>
        }
      />

      {/*
        §1. The question first, and a box under it.

        A person arriving here wants one of two things: to open a dashboard
        that already exists, or to make one. Asking the second question at the
        top costs one line and saves the reader deciding whether the page is
        for browsing or for building — it is for both, and it says so.

        What they type is not turned into a lens on the spot. It is carried
        into the builder, which shows what it understood before anything is
        created. A box that built a whole lens from one sentence would leave
        whatever it did not understand silently absent.
      */}
      <Card className="p-5">
        <h2 className="text-sm font-semibold tracking-tight text-text-primary">
          How do you want to define a new Lens?
        </h2>
        <p className="mt-1 text-xs leading-relaxed text-text-muted">
          Describe what you want to monitor in your own words, and CreditProbe
          will show you which governed data it recognised and which metrics
          answer to it — before it builds anything. Or start from a blank one
          and pick metrics from the library.
        </p>
        <div className="mt-3 flex flex-wrap gap-2">
          <input
            value={said}
            aria-label="Describe what you want to monitor"
            data-testid="lens-intent"
            placeholder="Watchlist exposure and covenant breaches across the corporate book"
            onChange={(e) => setSaid(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && said.trim()) {
                router.push(
                  `/lenses/new?say=${encodeURIComponent(said.trim())}`,
                );
              }
            }}
            className="h-10 min-w-0 flex-1 rounded-md border border-border bg-surface px-3 text-sm text-text-primary placeholder:text-text-muted focus:border-accent focus:outline-none"
          />
          <Button
            data-testid="describe-lens"
            disabled={!said.trim()}
            onClick={() =>
              router.push(`/lenses/new?say=${encodeURIComponent(said.trim())}`)
            }
          >
            <Sparkles aria-hidden />
            Describe it
          </Button>
          <Button variant="outline" asChild>
            <Link href="/lenses/new">
              <Plus aria-hidden />
              Start blank
            </Link>
          </Button>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-1.5">
          <span className="text-[11px] text-text-muted">For example:</span>
          {[
            "Watchlist exposure and covenant breaches",
            "IFRS 9 coverage and retail delinquency",
            "Exposure by sector",
          ].map((example) => (
            <button
              key={example}
              type="button"
              onClick={() => setSaid(example)}
              className="rounded-full border border-border px-2.5 py-1 text-[11px] text-text-secondary transition-colors hover:bg-surface-hover"
            >
              {example}
            </button>
          ))}
        </div>
      </Card>

      <section>
        <h2 className="mb-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-text-muted">
          Specialist dashboards
        </h2>
        <p className="mb-3 max-w-2xl text-xs leading-relaxed text-text-muted">
          Built for a role rather than assembled from whatever was to hand.
          Every tile names a governed metric that calculates against this
          deployment&rsquo;s data, and each lens says what it cannot show and
          why.
        </p>
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {library.loading && !library.data && (
            <>
              <Skeleton className="h-44 w-full" />
              <Skeleton className="h-44 w-full" />
              <Skeleton className="h-44 w-full" />
            </>
          )}
          {shipped.map((spec) => {
            const stored = bySlug.get(spec.slug);
            return (
              <Link
                key={spec.slug}
                href={stored ? `/lenses/${stored.id}` : "/lenses"}
                className="group"
              >
                <Card className="flex h-full flex-col p-5 transition-colors hover:bg-surface-hover">
                  <div className="mb-2 flex items-start justify-between gap-3">
                    <LayoutGrid
                      className="size-5 shrink-0 text-text-muted"
                      aria-hidden
                    />
                    <Badge variant="accent">Shipped</Badge>
                  </div>
                  <h3 className="text-sm font-semibold text-text-primary">
                    {spec.name}
                  </h3>
                  <p className="mt-1.5 flex-1 text-xs leading-relaxed text-text-muted">
                    {spec.purpose || spec.description}
                  </p>
                  <div className="mt-3 flex flex-wrap gap-1.5">
                    {spec.domains.map((domain) => (
                      <Badge key={domain} variant="info">
                        {domain}
                      </Badge>
                    ))}
                  </div>
                  {/*
                    Two lines, not one. On one line the audience truncated and
                    took the counts with it — "IFRS 9 Committee and Head of
                    Impairment · 34 figur…" — and the counts are the half a
                    reader compares between cards.
                  */}
                  <div className="mt-3 border-t border-border pt-3 text-[11px] text-text-muted">
                    <p className="truncate">{spec.audience}</p>
                    <p className="mt-0.5 flex items-center justify-between gap-2">
                      <span>
                        {spec.tiles} figures · {spec.charts} charts
                      </span>
                      <span className="inline-flex shrink-0 items-center gap-1 font-medium text-accent opacity-0 transition-opacity group-hover:opacity-100">
                        Open <ArrowRight className="size-3" aria-hidden />
                      </span>
                    </p>
                  </div>
                </Card>
              </Link>
            );
          })}
        </div>
      </section>

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
              {library.data?.cro.note ??
                "The monthly executive view: position, staging, coverage, concentration, migration and the names driving deterioration — arranged as an argument rather than a grid of tiles."}
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
          (mine.length > 0 ? (
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              {mine.map((lens) => (
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
              description="Create one and CreditProbe will suggest what it is probably for. It runs live, and can be changed later by asking or by hand."
              action={
                <Button size="sm" asChild>
                  <Link href="/lenses/new">
                    <Plus aria-hidden />
                    Create a lens
                  </Link>
                </Button>
              }
            />
          ))}
      </section>
    </div>
  );
}
