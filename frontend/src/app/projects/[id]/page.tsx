"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import * as React from "react";
import {
  BarChart3,
  MessageSquare,
  Send,
  Sparkles,
} from "lucide-react";

import { BackLink } from "@/components/layout/back-link";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { CertificationBadge } from "@/components/ui/certified-mark";
import { EmptyState } from "@/components/ui/empty";
import { InfoPopover } from "@/components/ui/info-popover";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs } from "@/components/ui/tabs";
import { api, type ProjectContents, type ProjectStatus } from "@/lib/api";
import { useAsync } from "@/lib/hooks";
import { fromProject, linkBack } from "@/lib/return-to";

import { StatusBadge } from "../page";

/**
 * One project: its status, its standing instructions, and what is filed here.
 *
 * The status control offers only the moves the backend permits from where the
 * project currently is, and it never offers "In review" — that is reached by
 * sending the project to somebody, and left when they decide. An interface that
 * let you set it directly would turn the most load-bearing badge in the product
 * into a decoration.
 */
export default function ProjectPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = React.use(params);
  return (
    <React.Suspense fallback={<Skeleton className="h-96 w-full" />}>
      <ProjectView id={id} />
    </React.Suspense>
  );
}

/**
 * The tab lives in the URL rather than only in state.
 *
 * §6 asks that a Back control restore the selected tab. It can only do that if
 * the tab is part of the address — otherwise "Back to Contracting review"
 * returns a reader who was reading the Analyses tab to the Investigations one,
 * which looks like the project lost their work.
 */
function ProjectView({ id }: { id: string }) {
  const projectId = Number(id);
  const params = useSearchParams();
  const requested = params.get("tab");

  const loaded = useAsync(
    () => api.projectContents(projectId),
    [projectId],
    { enabled: Number.isFinite(projectId) },
  );
  const [local, setLocal] = React.useState<ProjectContents | null>(null);
  const contents = local ?? loaded.data;
  const [tab, setTab] = React.useState(
    requested === "analyses" || requested === "history"
      ? requested
      : "investigations",
  );
  const [error, setError] = React.useState<string | null>(null);

  // Changing tab rewrites the address without a navigation, so a link taken
  // from here carries the tab the reader was actually on and Back restores it.
  const chooseTab = React.useCallback((next: string) => {
    setTab(next);
    const url = new URL(window.location.href);
    url.searchParams.set("tab", next);
    window.history.replaceState(window.history.state, "", url);
  }, []);

  if (!Number.isFinite(projectId)) {
    return (
      <Card className="border-negative/40 p-4 text-sm text-negative">
        &ldquo;{id}&rdquo; is not a project.
      </Card>
    );
  }

  if (loaded.loading && !contents) return <Skeleton className="h-96 w-full" />;
  if (loaded.error && !contents) {
    return (
      <Card className="border-negative/40 p-4 text-sm text-negative">
        {loaded.error}
      </Card>
    );
  }
  if (!contents) return null;

  const { project } = contents;

  async function moveTo(status: ProjectStatus) {
    setError(null);
    try {
      const updated = await api.setProjectStatus(projectId, status);
      setLocal({ ...contents!, project: updated });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function sendForReview() {
    setError(null);
    try {
      const updated = await api.sendProjectForReview(projectId, null);
      setLocal({ ...contents!, project: updated });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <div className="space-y-7">
      <BackLink href="/projects" label="Projects" />

      <header>
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <p className="text-[10px] font-medium uppercase tracking-[0.16em] text-text-muted">
              Project
            </p>
            <div className="mt-1.5 flex flex-wrap items-center gap-2">
              <h1 className="text-[24px] font-semibold leading-tight tracking-tight text-text-primary">
                {project.name}
              </h1>
              <StatusBadge status={project.status} label={project.status_label} />
              <InfoPopover title="What the status means">
                <p>
                  <strong>Draft</strong> — being set up, nobody relies on it yet.{" "}
                  <strong>Active</strong> — work in progress.{" "}
                  <strong>Completed</strong> — the work is finished.{" "}
                  <strong>Archived</strong> — kept for the record.
                </p>
                <p>
                  <strong>In review</strong> cannot be set by hand. It appears
                  only while somebody has been asked to review the project and
                  has not yet decided, which is what makes it worth trusting.
                </p>
              </InfoPopover>
            </div>
            {project.description && (
              <p className="mt-2 max-w-2xl text-sm leading-relaxed text-text-secondary">
                {project.description}
              </p>
            )}
          </div>

          <div className="flex shrink-0 flex-wrap items-center gap-1.5">
            {project.available_statuses.map((option) => (
              <Button
                key={option.status}
                variant="outline"
                size="sm"
                onClick={() => moveTo(option.status)}
              >
                {option.label}
              </Button>
            ))}
            {!project.review_open && project.status === "active" && (
              <Button variant="ghost" size="sm" onClick={sendForReview}>
                <Send aria-hidden />
                Send for review
              </Button>
            )}
          </div>
        </div>

        {project.review_open && (
          <p className="mt-3 text-xs text-warning">
            With a reviewer. The status moves when they decide, not before.
          </p>
        )}
        {project.instructions && (
          <p className="mt-3 max-w-2xl border-l-2 border-accent/40 pl-3 text-xs leading-relaxed text-text-muted">
            Standing instruction: {project.instructions}
          </p>
        )}
      </header>

      {error && (
        <Card className="border-negative/40 p-4 text-sm text-negative">{error}</Card>
      )}

      <Tabs
        active={tab}
        onChange={chooseTab}
        tabs={[
          {
            id: "investigations",
            label: "Investigations",
            count: contents.investigations.length,
          },
          {
            id: "analyses",
            label: "Analyses",
            count: contents.analyses.length,
          },
          { id: "history", label: "History", count: project.history.length },
        ]}
      />

      {tab === "investigations" &&
        (contents.investigations.length > 0 ? (
          <Card className="divide-y divide-border">
            {contents.investigations.map((thread) => (
              <Link
                key={thread.id}
                href={linkBack(
                  `/investigations/${thread.id}`,
                  fromProject(project.id, project.name, "investigations"),
                )}
                className="flex items-start gap-3 px-5 py-3.5 transition-colors hover:bg-surface-hover"
              >
                <MessageSquare
                  className="mt-0.5 size-4 shrink-0 text-text-muted"
                  aria-hidden
                />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium text-text-primary">
                    {thread.title}
                  </span>
                  <span className="mt-0.5 line-clamp-1 block text-xs text-text-muted">
                    {thread.question}
                  </span>
                </span>
                <span className="hidden shrink-0 text-[11px] text-text-muted sm:block">
                  {thread.message_count}{" "}
                  {thread.message_count === 1 ? "message" : "messages"}
                </span>
              </Link>
            ))}
          </Card>
        ) : (
          <EmptyState
            icon={MessageSquare}
            title="Nothing explored yet"
            description="Ask a question and move the investigation into this project, or start one from the Cockpit."
            action={
              <Button size="sm" asChild>
                <Link href="/?focus=ask">
                  <Sparkles aria-hidden />
                  Ask a question
                </Link>
              </Button>
            }
          />
        ))}

      {tab === "analyses" &&
        (contents.analyses.length > 0 ? (
          <Card className="divide-y divide-border">
            {contents.analyses.map((analysis) => (
              <div key={analysis.id} className="flex items-start gap-3 px-5 py-3.5">
                <BarChart3
                  className="mt-0.5 size-4 shrink-0 text-text-muted"
                  aria-hidden
                />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="truncate text-sm font-medium text-text-primary">
                      {analysis.title}
                    </span>
                    <CertificationBadge certification={analysis.certification} />
                  </div>
                  <p className="mt-0.5 text-[11px] text-text-muted">
                    {analysis.analysis_id}
                  </p>
                </div>
                {analysis.investigation_id !== null && (
                  <Button variant="ghost" size="sm" asChild>
                    <Link
                      href={linkBack(
                        `/investigations/${analysis.investigation_id}`,
                        fromProject(project.id, project.name, "analyses"),
                      )}
                    >
                      Open
                    </Link>
                  </Button>
                )}
              </div>
            ))}
          </Card>
        ) : (
          <EmptyState
            icon={BarChart3}
            title="No evidence kept yet"
            description="Under any answer, Save analysis keeps the certified calculations behind it and files them here."
          />
        ))}

      {tab === "history" && (
        <Card className="divide-y divide-border">
          {project.history.length > 0 ? (
            project.history.map((event, i) => (
              <div key={i} className="flex items-baseline gap-3 px-5 py-3">
                <span className="text-sm text-text-primary">
                  {event.from_status
                    ? `${event.from_status.replace("_", " ")} → ${event.to_label}`
                    : event.to_label}
                </span>
                {event.note && (
                  <span className="min-w-0 flex-1 truncate text-xs text-text-muted">
                    {event.note}
                  </span>
                )}
                <span className="ml-auto shrink-0 text-[11px] text-text-muted">
                  {when(event.created_at)}
                </span>
              </div>
            ))
          ) : (
            <p className="px-5 py-4 text-sm text-text-muted">
              Nothing recorded yet.
            </p>
          )}
        </Card>
      )}
    </div>
  );
}

function when(iso: string | null): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}
