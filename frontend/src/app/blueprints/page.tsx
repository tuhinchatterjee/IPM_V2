"use client";

import Link from "next/link";
import { ArrowRight, ClipboardCheck, Info } from "lucide-react";

import { PageHeader } from "@/components/layout/page-header";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { BLUEPRINTS, DEMO_NOTICE } from "@/lib/demo";

export default function BlueprintsPage() {
  return (
    <div className="space-y-6">
      <PageHeader
        title="Blueprints"
        description="Reusable analytical workflows. A Blueprint captures a proven investigation — its analyses, its parameters, its order — so it can be re-run next period, on another portfolio, or by another analyst, producing a comparable result."
        status="preview"
        phase="Execution next"
      />

      <Card className="flex items-start gap-2.5 border-info/30 bg-info-muted p-4 text-sm text-info">
        <Info className="mt-0.5 size-4 shrink-0" aria-hidden />
        <span>
          A Blueprint is <strong>not a saved prompt</strong>. It is a governed workflow: an
          ordered set of registered analyses with declared parameters, versioned and owned. Running
          one produces the same defensible output every period, which is how one analyst&apos;s good
          work becomes institutional capability.
        </span>
      </Card>

      <div className="grid gap-4 md:grid-cols-2">
        {BLUEPRINTS.map((b) => (
          <Link key={b.id} href={`/blueprints/${b.id}`} className="group">
            <Card className="flex h-full flex-col p-5 transition-colors hover:bg-surface-hover">
              <div className="mb-2 flex items-start justify-between gap-3">
                <ClipboardCheck className="size-5 shrink-0 text-text-muted" aria-hidden />
                <div className="flex items-center gap-1.5">
                  <Badge variant="outline">v{b.version}</Badge>
                  <Badge variant="accent">{b.cadence}</Badge>
                </div>
              </div>
              <h3 className="text-sm font-semibold text-text-primary">{b.name}</h3>
              <p className="mt-1.5 flex-1 text-xs leading-relaxed text-text-muted">{b.description}</p>
              <ol className="mt-3 space-y-1">
                {b.steps.map((s, i) => (
                  <li key={s.analysisId} className="flex items-center gap-2 text-xs text-text-secondary">
                    <span className="flex size-4 shrink-0 items-center justify-center rounded-full bg-surface-sunken text-[10px] tabular">
                      {i + 1}
                    </span>
                    {s.title}
                  </li>
                ))}
              </ol>
              <div className="mt-4 flex items-center justify-between border-t border-border pt-3 text-[11px] text-text-muted">
                <span>{b.owner}</span>
                <span className="inline-flex items-center gap-1 font-medium text-accent opacity-0 transition-opacity group-hover:opacity-100">
                  Open <ArrowRight className="size-3" aria-hidden />
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
