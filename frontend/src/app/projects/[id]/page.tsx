"use client";

import Link from "next/link";
import { notFound } from "next/navigation";
import * as React from "react";
import { ArrowLeft, FileText, MessageSquare, Paperclip, Search } from "lucide-react";

import { PageHeader } from "@/components/layout/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty";
import { Tabs } from "@/components/ui/tabs";
import { BLUEPRINTS, DEMO_NOTICE, DOCUMENTS, INVESTIGATIONS, findProject } from "@/lib/demo";

export default function ProjectPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = React.use(params);
  const project = findProject(id);
  if (!project) notFound();

  const [tab, setTab] = React.useState("overview");
  const investigations = INVESTIGATIONS.filter((i) => project.investigationIds.includes(i.id));
  const documents = DOCUMENTS.filter((d) => d.project === project.name);

  return (
    <div className="space-y-6">
      <Button variant="ghost" size="sm" asChild className="-ml-2">
        <Link href="/projects"><ArrowLeft aria-hidden />Projects</Link>
      </Button>

      <PageHeader
        title={project.name}
        description={project.description}
        status="preview"
        phase="Demo record"
        actions={<Badge variant="outline">{project.team}</Badge>}
      />

      <Tabs
        active={tab}
        onChange={setTab}
        tabs={[
          { id: "overview", label: "Overview" },
          { id: "chats", label: "Chats", count: project.counts.chats },
          { id: "investigations", label: "Investigations", count: investigations.length },
          { id: "blueprints", label: "Blueprints", count: project.counts.blueprints },
          { id: "files", label: "Files" },
          { id: "documents", label: "Documents", count: documents.length },
        ]}
      />

      {tab === "overview" && (
        <div className="grid gap-4 md:grid-cols-3">
          <Card className="p-5 md:col-span-2">
            <h3 className="mb-3 text-sm font-semibold text-text-primary">Recent investigations</h3>
            <ul className="space-y-2">
              {investigations.map((i) => (
                <li key={i.id}>
                  <Link
                    href={`/investigations/${i.id}`}
                    className="flex items-start gap-3 rounded-md p-2 transition-colors hover:bg-surface-hover"
                  >
                    <Search className="mt-0.5 size-4 shrink-0 text-text-muted" aria-hidden />
                    <div>
                      <p className="text-sm font-medium text-text-primary">{i.title}</p>
                      <p className="text-xs text-text-muted">{i.steps.length} analyses · {i.owner}</p>
                    </div>
                  </Link>
                </li>
              ))}
              {investigations.length === 0 && (
                <li className="text-sm text-text-muted">None yet.</li>
              )}
            </ul>
          </Card>
          <Card className="p-5">
            <h3 className="mb-3 text-sm font-semibold text-text-primary">Details</h3>
            <dl className="space-y-2 text-sm">
              {[["Owner", project.owner], ["Team", project.team], ["Status", project.status.replace("_"," ")], ["Updated", project.updated]].map(([k, v]) => (
                <div key={k} className="flex justify-between">
                  <dt className="text-xs text-text-muted">{k}</dt>
                  <dd className="text-text-secondary">{v}</dd>
                </div>
              ))}
            </dl>
          </Card>
        </div>
      )}

      {tab === "chats" && (
        <EmptyState
          icon={MessageSquare}
          title="Chats arrive with AI orchestration"
          description="A chat is a threaded conversation inside a project, with every analytical result in it permanently linked to its Trace. The tables that store chats and messages already exist."
        />
      )}

      {tab === "investigations" && (
        <div className="grid gap-3 md:grid-cols-2">
          {investigations.map((i) => (
            <Link key={i.id} href={`/investigations/${i.id}`}>
              <Card className="h-full p-4 transition-colors hover:bg-surface-hover">
                <p className="text-sm font-medium text-text-primary">{i.title}</p>
                <p className="mt-1 text-xs italic text-text-secondary">&ldquo;{i.question}&rdquo;</p>
                <p className="mt-2 text-xs text-text-muted">{i.steps.length} certified analyses</p>
              </Card>
            </Link>
          ))}
        </div>
      )}

      {tab === "blueprints" && (
        <div className="grid gap-3 md:grid-cols-2">
          {BLUEPRINTS.slice(0, project.counts.blueprints).map((b) => (
            <Link key={b.id} href={`/blueprints/${b.id}`}>
              <Card className="h-full p-4 transition-colors hover:bg-surface-hover">
                <p className="text-sm font-medium text-text-primary">{b.name}</p>
                <p className="mt-1 text-xs text-text-muted">{b.steps.length} steps · {b.cadence}</p>
              </Card>
            </Link>
          ))}
        </div>
      )}

      {tab === "files" && (
        <EmptyState
          icon={Paperclip}
          title="File attachments are not built yet"
          description="Source extracts brought into a project will appear here. Files uploaded through Data Builder are already stored, unchanged, in the raw layer."
        />
      )}

      {tab === "documents" && (
        <div className="grid gap-3 md:grid-cols-2">
          {documents.map((d) => (
            <Link key={d.id} href={`/documents/${d.id}`}>
              <Card className="flex h-full items-start gap-3 p-4 transition-colors hover:bg-surface-hover">
                <FileText className="mt-0.5 size-4 shrink-0 text-text-muted" aria-hidden />
                <div>
                  <p className="text-sm font-medium text-text-primary">{d.title}</p>
                  <p className="mt-0.5 text-xs text-text-muted">{d.kind} · {d.status.replace("_"," ")}</p>
                </div>
              </Card>
            </Link>
          ))}
          {documents.length === 0 && <p className="text-sm text-text-muted">No documents.</p>}
        </div>
      )}

      <p className="text-xs text-text-muted">{DEMO_NOTICE}</p>
    </div>
  );
}
