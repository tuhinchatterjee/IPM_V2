"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowRight, Clock, GitBranch, Search, Sparkles } from "lucide-react";

import { PageHeader } from "@/components/layout/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import { useAsync } from "@/lib/hooks";
import { DEMO_NOTICE, INVESTIGATIONS } from "@/lib/demo";

/**
 * Investigations.
 *
 * Three lists, and the differences between them matter.
 *
 * SAVED are analytical objects somebody keeps: named, owned, versioned, and
 * refreshable against newly published data.
 *
 * ASKED is every question put to IPM, with its Trace intact. Real work, but
 * nobody has decided to keep it yet.
 *
 * TEMPLATES are seeded review outlines. They name real registered analyses but
 * were written by hand and have never been executed, which is why they are last
 * and labelled.
 */
export default function InvestigationsPage() {
  const router = useRouter();
  const saved = useAsync(() => api.savedInvestigations(), []);
  const recent = useAsync(() => api.recentInvestigations(20), []);

  return (
    <div className="space-y-8">
      <PageHeader
        title="Investigations"
        description="Every question asked of IPM, kept with the plan it produced, the analyses it ran and the Trace behind each figure. Reopen one to read it, or branch it into a new version."
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

      {saved.data && saved.data.investigations.length > 0 && (
        <section>
          <h2 className="mb-3 text-[10px] font-semibold uppercase tracking-[0.14em] text-text-muted">
            Saved
          </h2>
          <Card className="divide-y divide-border">
            {saved.data.investigations.map((item) => (
              <button
                key={item.id}
                type="button"
                onClick={() => router.push(`/investigations/saved/${item.id}`)}
                className="flex w-full items-start gap-3 px-5 py-3.5 text-left transition-colors hover:bg-surface-hover"
              >
                <Search className="mt-0.5 size-4 shrink-0 text-text-muted" aria-hidden />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium text-text-primary">
                    {item.title}
                  </span>
                  <span className="mt-0.5 line-clamp-1 block text-xs text-text-muted">
                    {item.answer || item.question}
                  </span>
                </span>
                <span className="hidden shrink-0 items-center gap-3 text-[11px] text-text-muted sm:flex">
                  {item.from_period && item.to_period && (
                    <span>
                      {item.from_period} to {item.to_period}
                    </span>
                  )}
                  <Badge variant="outline">v{item.version}</Badge>
                </span>
              </button>
            ))}
          </Card>
        </section>
      )}

      <section>
        <h2 className="mb-3 text-[10px] font-semibold uppercase tracking-[0.14em] text-text-muted">
          Asked of IPM
        </h2>
        {recent.loading && <Skeleton className="h-40 w-full" />}
        {recent.error && (
          <Card className="border-negative/40 p-4 text-sm text-negative">{recent.error}</Card>
        )}
        {recent.data &&
          (recent.data.investigations.length > 0 ? (
            <Card className="divide-y divide-border">
              {recent.data.investigations.map((item) => (
                <button
                  key={item.analysis_run_id}
                  type="button"
                  onClick={() => router.push(`/investigations/${item.analysis_run_id}`)}
                  className="flex w-full items-start gap-3 px-5 py-3.5 text-left transition-colors hover:bg-surface-hover"
                >
                  <Search className="mt-0.5 size-4 shrink-0 text-text-muted" aria-hidden />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-medium text-text-primary">
                      {item.question}
                    </span>
                    <span className="mt-0.5 line-clamp-1 block text-xs text-text-muted">
                      {item.summary || item.intent}
                    </span>
                  </span>
                  <span className="hidden shrink-0 items-center gap-3 text-[11px] text-text-muted sm:flex">
                    <span>
                      {item.step_count} {item.step_count === 1 ? "analysis" : "analyses"}
                    </span>
                    <span className="flex items-center gap-1">
                      <Clock className="size-3" aria-hidden />
                      {item.duration_ms ?? "—"}ms
                    </span>
                    <span className="flex items-center gap-1 font-medium text-accent">
                      <GitBranch className="size-3" aria-hidden />
                      Trace
                    </span>
                  </span>
                </button>
              ))}
            </Card>
          ) : (
            <Card className="px-5 py-10 text-center">
              <p className="text-sm text-text-secondary">Nothing asked yet.</p>
              <p className="mt-1 text-xs text-text-muted">
                Ask a question in the Cockpit and it will be kept here with its Trace.
              </p>
              <Button className="mt-4" size="sm" asChild>
                <Link href="/?focus=ask">Open the Cockpit</Link>
              </Button>
            </Card>
          ))}
      </section>

      <section>
        <h2 className="mb-3 text-[10px] font-semibold uppercase tracking-[0.14em] text-text-muted">
          Review templates
          <span className="ml-2 font-normal normal-case tracking-normal text-text-muted/80">
            — outlines, never executed
          </span>
        </h2>
        <div className="grid gap-4 md:grid-cols-2">
          {INVESTIGATIONS.map((inv) => (
            <Link key={inv.id} href={`/investigations/${inv.id}`} className="group">
              <Card className="flex h-full flex-col p-5 transition-colors hover:bg-surface-hover">
                <div className="mb-2 flex items-start justify-between gap-3">
                  <Search className="size-5 shrink-0 text-text-muted" aria-hidden />
                  <Badge
                    variant={
                      inv.status === "closed"
                        ? "default"
                        : inv.status === "in_review"
                          ? "warning"
                          : "accent"
                    }
                  >
                    {inv.status.replace("_", " ")}
                  </Badge>
                </div>
                <h3 className="text-sm font-semibold text-text-primary">{inv.title}</h3>
                <p className="mt-1 text-xs italic text-text-secondary">
                  &ldquo;{inv.question}&rdquo;
                </p>
                <p className="mt-2 flex-1 text-xs leading-relaxed text-text-muted">
                  {inv.objective}
                </p>

                <div className="mt-3 flex flex-wrap gap-1">
                  {inv.tags.map((t) => (
                    <Badge key={t} variant="outline">
                      {t}
                    </Badge>
                  ))}
                </div>

                <div className="mt-4 flex items-center justify-between border-t border-border pt-3 text-[11px] text-text-muted">
                  <span>
                    {inv.steps.length} analyses · {inv.owner} · {inv.updated}
                  </span>
                  <span className="inline-flex items-center gap-1 font-medium text-accent opacity-0 transition-opacity group-hover:opacity-100">
                    Open
                    <ArrowRight className="size-3" aria-hidden />
                  </span>
                </div>
              </Card>
            </Link>
          ))}
        </div>
        <p className="mt-3 text-xs text-text-muted">{DEMO_NOTICE}</p>
      </section>
    </div>
  );
}
