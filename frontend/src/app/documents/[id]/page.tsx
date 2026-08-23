"use client";

import Link from "next/link";
import { notFound } from "next/navigation";
import * as React from "react";
import {
  ArrowLeft, FileDown, GitBranch, History, MessageSquare, Pencil, Presentation, Workflow,
} from "lucide-react";

import { PageHeader } from "@/components/layout/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { findDocument } from "@/lib/demo";

/**
 * Document Workspace — placeholder.
 *
 * The future capabilities are shown so the intended shape is clear, and each is
 * marked Coming Soon and genuinely disabled. Nothing here pretends to work.
 */
const FUTURE = [
  { icon: Pencil, label: "Paragraph editing", note: "Edit prose, charts and tables in place" },
  { icon: MessageSquare, label: "Comments", note: "Threaded review on any paragraph" },
  { icon: History, label: "Version history", note: "Every draft, with who changed what" },
  { icon: Workflow, label: "Workflow", note: "Submission, review and sign-off" },
  { icon: GitBranch, label: "Trace links", note: "Every embedded figure linked to its Trace" },
  { icon: FileDown, label: "Export Word", note: ".docx with formatting preserved" },
  { icon: Presentation, label: "Export PowerPoint", note: "Committee deck from the same content" },
  { icon: FileDown, label: "Export PDF", note: "Print-ready board pack" },
];

export default function DocumentPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = React.use(params);
  const doc = findDocument(id);
  if (!doc) notFound();

  return (
    <div className="space-y-6">
      <Button variant="ghost" size="sm" asChild className="-ml-2">
        <Link href="/documents"><ArrowLeft aria-hidden />Documents</Link>
      </Button>

      <PageHeader
        title={doc.title}
        description={`${doc.kind} · ${doc.owner} · last updated ${doc.updated}`}
        status="preview"
        phase="Placeholder by design"
        actions={
          <Badge variant={doc.status === "approved" ? "positive" : "warning"}>
            {doc.status.replace("_", " ")}
          </Badge>
        }
      />

      <div className="grid gap-4 lg:grid-cols-[1fr_1.6fr]">
        <Card className="p-5">
          <h3 className="mb-3 text-sm font-semibold text-text-primary">Contents</h3>
          <ol className="space-y-1.5">
            {doc.sections.map((s, i) => (
              <li key={s} className="flex items-start gap-2.5 text-sm text-text-secondary">
                <span className="w-4 shrink-0 text-right text-xs text-text-muted tabular">{i + 1}</span>
                {s}
              </li>
            ))}
          </ol>
        </Card>

        <Card className="p-8">
          <div className="mx-auto max-w-prose space-y-4 text-center">
            <FileText />
            <h3 className="text-base font-semibold text-text-primary">
              Document editing is not built
            </h3>
            <p className="text-sm leading-relaxed text-text-secondary">
              This is a deliberate placeholder. Eventually a paper is authored here with live
              analytical content: each embedded chart and table stays linked to the Trace of the
              analysis that produced it, so a figure in a board pack can always be opened back to
              the data and function version behind it.
            </p>
            <p className="text-xs text-text-muted">
              The report writers that will produce the Word and PDF output already exist in the
              backend and are used by the preserved reporting module.
            </p>
          </div>
        </Card>
      </div>

      <section>
        <h2 className="mb-3 text-sm font-semibold tracking-tight text-text-primary">
          Planned capabilities
        </h2>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {FUTURE.map(({ icon: Icon, label, note }) => (
            <div
              key={label}
              className="cursor-not-allowed rounded-lg border border-border bg-surface-sunken p-4 opacity-70"
              aria-disabled
            >
              <div className="mb-2 flex items-start justify-between gap-2">
                <Icon className="size-4 text-text-muted" aria-hidden />
                <Badge variant="outline">Coming Soon</Badge>
              </div>
              <p className="text-sm font-medium text-text-secondary">{label}</p>
              <p className="mt-0.5 text-xs text-text-muted">{note}</p>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}

function FileText() {
  return (
    <svg
      className="mx-auto size-10 text-text-muted"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      aria-hidden
    >
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <path d="M14 2v6h6M16 13H8M16 17H8M10 9H8" />
    </svg>
  );
}
