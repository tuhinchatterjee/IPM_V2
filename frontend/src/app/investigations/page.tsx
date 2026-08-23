"use client";

import Link from "next/link";
import { ArrowRight, Search } from "lucide-react";

import { PageHeader } from "@/components/layout/page-header";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { DEMO_NOTICE, INVESTIGATIONS } from "@/lib/demo";

/**
 * Investigation library.
 *
 * The investigations are seeded records, but each one names the real registered
 * analyses it runs — so opening a workspace executes governed code rather than
 * displaying a stored picture.
 */
export default function InvestigationsPage() {
  return (
    <div className="space-y-6">
      <PageHeader
        title="Investigations"
        description="Multi-step root-cause work, persisted as a named object. Each investigation runs real certified analyses; the AI narrative that will tie them together arrives with orchestration."
        status="partial"
        phase="Real analyses · AI narrative next"
      />

      <div className="grid gap-4 md:grid-cols-2">
        {INVESTIGATIONS.map((inv) => (
          <Link key={inv.id} href={`/investigations/${inv.id}`} className="group">
            <Card className="flex h-full flex-col p-5 transition-colors hover:bg-surface-hover">
              <div className="mb-2 flex items-start justify-between gap-3">
                <Search className="size-5 shrink-0 text-text-muted" aria-hidden />
                <Badge
                  variant={
                    inv.status === "closed" ? "default" : inv.status === "in_review" ? "warning" : "accent"
                  }
                >
                  {inv.status.replace("_", " ")}
                </Badge>
              </div>
              <h3 className="text-sm font-semibold text-text-primary">{inv.title}</h3>
              <p className="mt-1 text-xs italic text-text-secondary">&ldquo;{inv.question}&rdquo;</p>
              <p className="mt-2 flex-1 text-xs leading-relaxed text-text-muted">{inv.objective}</p>

              <div className="mt-3 flex flex-wrap gap-1">
                {inv.tags.map((t) => (
                  <Badge key={t} variant="outline">{t}</Badge>
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

      <p className="text-xs text-text-muted">{DEMO_NOTICE}</p>
    </div>
  );
}
