"use client";

import Link from "next/link";
import { ArrowRight, Boxes } from "lucide-react";

import { PageHeader } from "@/components/layout/page-header";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { DEMO_NOTICE, PROJECTS } from "@/lib/demo";

export default function ProjectsPage() {
  return (
    <div className="space-y-6">
      <PageHeader
        title="Projects"
        description="A project is a container for a body of work — the chats, investigations, analyses, traces and documents that belong to one piece of thinking."
        status="preview"
        phase="Demo records"
      />
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {PROJECTS.map((p) => (
          <Link key={p.id} href={`/projects/${p.id}`} className="group">
            <Card className="flex h-full flex-col p-5 transition-colors hover:bg-surface-hover">
              <div className="mb-2 flex items-start justify-between gap-3">
                <Boxes className="size-5 shrink-0 text-text-muted" aria-hidden />
                <Badge variant={p.status === "in_review" ? "warning" : "accent"}>
                  {p.status.replace("_", " ")}
                </Badge>
              </div>
              <h3 className="text-sm font-semibold text-text-primary">{p.name}</h3>
              <p className="mt-1.5 flex-1 text-xs leading-relaxed text-text-muted">{p.description}</p>
              <dl className="mt-4 grid grid-cols-4 gap-2 border-t border-border pt-3 text-center">
                {[
                  ["Chats", p.counts.chats],
                  ["Investigations", p.counts.investigations],
                  ["Blueprints", p.counts.blueprints],
                  ["Documents", p.counts.documents],
                ].map(([label, value]) => (
                  <div key={String(label)}>
                    <dd className="text-sm font-semibold text-text-primary tabular">{value}</dd>
                    <dt className="text-[10px] text-text-muted">{label}</dt>
                  </div>
                ))}
              </dl>
              <div className="mt-3 flex items-center justify-between text-[11px] text-text-muted">
                <span>{p.team} · {p.updated}</span>
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
