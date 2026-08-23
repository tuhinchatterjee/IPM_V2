"use client";

import Link from "next/link";
import { ArrowRight, FileText } from "lucide-react";

import { PageHeader } from "@/components/layout/page-header";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { DOCUMENTS } from "@/lib/demo";

/** Document Library. A placeholder by design — see docs/PRODUCT_SPEC.md §3.11. */
export default function DocumentsPage() {
  return (
    <div className="space-y-6">
      <PageHeader
        title="Documents"
        description="Board and committee papers authored with live analytical content. Placeholder for this demo — document editing is explicitly out of scope."
        status="preview"
        phase="Placeholder by design"
      />

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {DOCUMENTS.map((d) => (
          <Link key={d.id} href={`/documents/${d.id}`} className="group">
            <Card className="flex h-full flex-col p-5 transition-colors hover:bg-surface-hover">
              <div className="mb-3 flex items-start justify-between gap-3">
                <FileText className="size-5 shrink-0 text-text-muted" aria-hidden />
                <Badge
                  variant={
                    d.status === "approved" ? "positive" : d.status === "in_review" ? "warning" : "default"
                  }
                >
                  {d.status.replace("_", " ")}
                </Badge>
              </div>
              <h3 className="text-sm font-semibold text-text-primary">{d.title}</h3>
              <p className="mt-1 text-xs text-text-muted">{d.kind}</p>
              <p className="mt-3 flex-1 text-xs text-text-muted">
                {d.sections.length} sections · {d.owner}
              </p>
              <div className="mt-3 flex items-center justify-between border-t border-border pt-3 text-[11px] text-text-muted">
                <span>{d.updated}</span>
                <span className="inline-flex items-center gap-1 font-medium text-accent opacity-0 transition-opacity group-hover:opacity-100">
                  Open <ArrowRight className="size-3" aria-hidden />
                </span>
              </div>
            </Card>
          </Link>
        ))}
      </div>
    </div>
  );
}
