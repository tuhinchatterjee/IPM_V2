"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import * as React from "react";
import { Boxes, Plus } from "lucide-react";

import { PageHeader } from "@/components/layout/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { api, type ProjectRow, type ProjectStatus } from "@/lib/api";
import { useAsync } from "@/lib/hooks";

/**
 * Projects: the top of the hierarchy.
 *
 * A Project holds a question somebody is working on over weeks — the
 * investigations that explore it and the analyses kept as evidence.
 *
 * The status on each card is governed, not decorative. Four of the five are a
 * person's declaration; "In review" is not. It appears only while a review is
 * genuinely outstanding, which is what makes it worth reading.
 */
export default function ProjectsPage() {
  const router = useRouter();
  const projects = useAsync(() => api.projects(), []);
  const [creating, setCreating] = React.useState(false);

  return (
    <div className="space-y-7">
      <PageHeader
        title="Projects"
        description="A project is a body of work: the investigations that explore a question and the analyses kept as evidence for it. Its status says where the work has got to — and 'In review' appears only while a reviewer genuinely holds it."
        status="live"
        actions={
          <Button size="sm" onClick={() => setCreating((c) => !c)}>
            <Plus aria-hidden />
            New project
          </Button>
        }
      />

      {creating && (
        <NewProject
          onCreated={(project) => {
            setCreating(false);
            router.push(`/projects/${project.id}`);
          }}
          onCancel={() => setCreating(false)}
        />
      )}

      {projects.loading && <Skeleton className="h-52 w-full" />}
      {projects.error && (
        <Card className="border-negative/40 p-4 text-sm text-negative">
          {projects.error}
        </Card>
      )}

      {projects.data &&
        (projects.data.projects.length > 0 ? (
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {projects.data.projects.map((project) => (
              <Link
                key={project.id}
                href={`/projects/${project.id}`}
                className="group"
              >
                <Card className="flex h-full flex-col p-5 transition-colors hover:bg-surface-hover">
                  <div className="mb-2.5 flex items-start justify-between gap-3">
                    <Boxes className="size-5 shrink-0 text-text-muted" aria-hidden />
                    <StatusBadge status={project.status} label={project.status_label} />
                  </div>
                  <h3 className="text-sm font-semibold text-text-primary">
                    {project.name}
                  </h3>
                  {project.description && (
                    <p className="mt-1.5 flex-1 line-clamp-3 text-xs leading-relaxed text-text-muted">
                      {project.description}
                    </p>
                  )}
                  <p className="mt-4 border-t border-border pt-3 text-[11px] text-text-muted">
                    {project.investigation_count}{" "}
                    {project.investigation_count === 1
                      ? "investigation"
                      : "investigations"}{" "}
                    · {project.analysis_count}{" "}
                    {project.analysis_count === 1 ? "analysis" : "analyses"}
                  </p>
                </Card>
              </Link>
            ))}
          </div>
        ) : (
          <EmptyState
            icon={Boxes}
            title="No projects yet"
            description="Open a project when a question is going to take more than one sitting. Investigations and saved analyses can then be filed under it."
            action={
              <Button size="sm" onClick={() => setCreating(true)}>
                New project
              </Button>
            }
          />
        ))}
    </div>
  );
}

export function StatusBadge({
  status,
  label,
}: {
  status: ProjectStatus;
  label: string;
}) {
  const variant =
    status === "in_review"
      ? "warning"
      : status === "active"
        ? "accent"
        : status === "completed"
          ? "positive"
          : "outline";
  return <Badge variant={variant}>{label}</Badge>;
}

function NewProject({
  onCreated,
  onCancel,
}: {
  onCreated: (project: ProjectRow) => void;
  onCancel: () => void;
}) {
  const [name, setName] = React.useState("");
  const [description, setDescription] = React.useState("");
  const [instructions, setInstructions] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  async function create() {
    if (!name.trim()) return;
    setBusy(true);
    setError(null);
    try {
      onCreated(
        await api.createProject({
          name: name.trim(),
          description: description.trim(),
          instructions: instructions.trim(),
        }),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  }

  return (
    <Card className="space-y-4 p-5">
      <div>
        <label
          htmlFor="project-name"
          className="text-xs font-medium text-text-secondary"
        >
          Name
        </label>
        <Input
          id="project-name"
          autoFocus
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Contracting concentration review"
          className="mt-1"
        />
      </div>

      <div>
        <label
          htmlFor="project-description"
          className="text-xs font-medium text-text-secondary"
        >
          What is this project for?
        </label>
        <Input
          id="project-description"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="Whether the Contracting exposure needs an action plan."
          className="mt-1"
        />
      </div>

      <div>
        <label
          htmlFor="project-instructions"
          className="text-xs font-medium text-text-secondary"
        >
          Standing instructions
        </label>
        <textarea
          id="project-instructions"
          value={instructions}
          onChange={(e) => setInstructions(e.target.value)}
          rows={2}
          placeholder="Answer for the corporate book unless told otherwise."
          className="mt-1 w-full resize-none rounded-md border border-border bg-surface px-3 py-2 text-sm text-text-primary placeholder:text-text-muted focus:border-accent focus:outline-none"
        />
        <p className="mt-1 text-[11px] text-text-muted">
          Carried into every investigation opened inside this project, so it is
          said once rather than in every question.
        </p>
      </div>

      {error && <p className="text-xs text-negative">{error}</p>}

      <div className="flex items-center gap-2">
        <Button size="sm" onClick={create} disabled={!name.trim() || busy}>
          Create project
        </Button>
        <Button variant="ghost" size="sm" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </Card>
  );
}
