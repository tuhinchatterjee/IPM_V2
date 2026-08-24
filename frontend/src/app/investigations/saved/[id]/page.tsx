"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import * as React from "react";
import {
  ArrowRight,
  GitBranch,
  History,
  MessageSquare,
  RefreshCw,
  Send,
} from "lucide-react";

import { KpiTile } from "@/components/analytics/primitives";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useCanRunAnalysis } from "@/components/system/role-switcher";
import { InfoPopover } from "@/components/ui/info-popover";
import { Skeleton } from "@/components/ui/skeleton";
import {
  api,
  type CommentRow,
  type Narrative,
  type SavedInvestigation,
} from "@/lib/api";
import { byUnit } from "@/lib/format";
import { useAsync } from "@/lib/hooks";
import { cn } from "@/lib/utils";

/**
 * One saved investigation.
 *
 * The page is built around the two things a saved answer is for: reading it, and
 * finding out whether it still holds. Refreshing re-executes the same plan — it
 * does not reload a stored number — and the account of what moved sits at the
 * top, because that is the reason anyone came back.
 */
export default function SavedInvestigationPage() {
  const params = useParams<{ id: string }>();
  const id = Number(params.id);

  const [version, setVersion] = React.useState<number | undefined>(undefined);
  const [nonce, setNonce] = React.useState(0);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const saved = useAsync(() => api.savedInvestigation(id, version), [id, version, nonce]);
  const data = saved.data;
  // Refreshing re-executes the analyses, so it needs the role that may run them.
  const canRun = useCanRunAnalysis();

  const refresh = async () => {
    setBusy(true);
    setError(null);
    try {
      const updated = await api.refreshInvestigation(id);
      setVersion(updated.version);
      setNonce((n) => n + 1);
    } catch (e) {
      setError(e instanceof Error ? e.message : "IPM could not refresh this.");
    } finally {
      setBusy(false);
    }
  };

  if (saved.loading && !data) return <Skeleton className="h-96 w-full" />;
  if (saved.error) {
    return <Card className="border-negative/40 p-4 text-sm text-negative">{saved.error}</Card>;
  }
  if (!data) return null;

  const narrative = data.narrative as Partial<Narrative>;
  const isLatest = data.version === Math.max(...data.versions.map((v) => v.version));

  return (
    <div className="space-y-7">
      <header>
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <p className="text-[11px] font-medium uppercase tracking-[0.16em] text-text-muted">
              Saved investigation
            </p>
            <h1 className="mt-1.5 max-w-3xl text-[22px] font-semibold leading-tight tracking-tight text-text-primary">
              {data.title}
            </h1>
            {data.question !== data.title && (
              <p className="mt-1 max-w-3xl text-sm text-text-muted">{data.question}</p>
            )}
          </div>
          <div className="flex shrink-0 items-center gap-1">
            {canRun && (
              <Button
                variant="outline"
                size="sm"
                disabled={busy}
                onClick={() => void refresh()}
                title="Run the same analyses again against what is published now"
              >
                <RefreshCw className={cn(busy && "animate-spin")} aria-hidden />
                {busy ? "Re-running" : "Refresh"}
              </Button>
            )}
            {data.analysis_run_id && (
              <Button variant="ghost" size="sm" asChild>
                <Link href={`/trace/${data.analysis_run_id}`}>
                  <GitBranch aria-hidden />
                  Trace
                </Link>
              </Button>
            )}
          </div>
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-xs text-text-muted">
          <span className="flex items-center gap-1.5">
            <History className="size-3" aria-hidden />
            Version {data.version} of {data.versions.length}
          </span>
          {data.from_period && data.to_period && (
            <span>
              {data.from_period} to {data.to_period}
            </span>
          )}
          {data.status === "archived" && <Badge variant="default">Archived</Badge>}
          {!isLatest && <Badge variant="warning">Not the latest version</Badge>}
        </div>
      </header>

      {error && (
        <Card className="border-negative/40 p-4 text-sm text-negative">{error}</Card>
      )}

      {/* ------------------------------------------------ what changed */}
      {data.change_narrative && (
        <section className="max-w-3xl border-l-2 border-accent/40 pl-4">
          <div className="mb-1.5 flex items-center gap-2">
            <h2 className="text-[10px] font-semibold uppercase tracking-[0.14em] text-text-muted">
              Since the last run
            </h2>
            <InfoPopover title="What this compares">
              <p>
                A refresh re-executes the same registered analyses against whatever is
                published now. Nothing is carried forward: a figure that is unchanged is
                unchanged because the calculation produced it again.
              </p>
              <p>
                The comparison is a subtraction of two engine results. It says what moved;
                it does not claim why.
              </p>
            </InfoPopover>
          </div>
          <p className="text-sm leading-relaxed text-text-secondary">{data.change_narrative}</p>
        </section>
      )}

      {data.changes.length > 0 && (
        <Card className="divide-y divide-border">
          {data.changes.map((change) => (
            <div key={change.label} className="flex items-baseline gap-3 px-4 py-2.5 text-sm">
              <span className="min-w-0 flex-1 truncate text-text-primary">{change.label}</span>
              <span className="shrink-0 text-text-muted tabular">
                {byUnit(change.before, change.unit)} → {byUnit(change.after, change.unit)}
              </span>
              <span
                className={cn(
                  "w-28 shrink-0 text-right font-medium tabular",
                  !change.moved
                    ? "text-text-muted"
                    : (change.change ?? 0) > 0 === (change.direction === "up-is-bad")
                      ? "text-negative"
                      : "text-positive",
                )}
              >
                {change.moved ? byUnit(change.change, change.unit) : "unchanged"}
              </span>
            </div>
          ))}
        </Card>
      )}

      {/* ------------------------------------------------------ the answer */}
      {(narrative.direct_answer || narrative.summary) && (
        <p className="max-w-3xl text-[19px] font-medium leading-relaxed tracking-tight text-text-primary">
          {narrative.direct_answer || narrative.summary}
        </p>
      )}

      {narrative.metrics && narrative.metrics.length > 0 && (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {narrative.metrics.map((metric) => (
            <KpiTile
              key={metric.label}
              label={metric.label}
              value={metric.value}
              unit={metric.unit}
              change={metric.change}
              changeUnit={metric.change_unit}
              direction={metric.direction}
              hint={metric.hint}
            />
          ))}
        </div>
      )}

      {narrative.interpretation_points && narrative.interpretation_points.length > 0 && (
        <section className="max-w-3xl border-l-2 border-accent/40 pl-4">
          <h2 className="mb-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-text-muted">
            IPM&rsquo;s reading
          </h2>
          <ul className="space-y-2">
            {narrative.interpretation_points.map((point) => (
              <li key={point} className="text-sm leading-relaxed text-text-secondary">
                {point}
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* -------------------------------------------------------- versions */}
      <section>
        <h2 className="mb-3 text-[10px] font-semibold uppercase tracking-[0.14em] text-text-muted">
          Versions
        </h2>
        <Card className="divide-y divide-border">
          {[...data.versions].reverse().map((v) => (
            <button
              key={v.version}
              type="button"
              onClick={() => setVersion(v.version)}
              className={cn(
                "flex w-full items-start gap-3 px-4 py-2.5 text-left transition-colors hover:bg-surface-hover",
                v.version === data.version && "bg-accent-muted",
              )}
            >
              <span className="w-16 shrink-0 text-xs font-medium text-text-primary">
                v{v.version}
              </span>
              <span className="min-w-0 flex-1">
                <span className="block text-xs text-text-secondary">
                  {v.from_period && v.to_period
                    ? `${v.from_period} to ${v.to_period}`
                    : "Current position"}
                </span>
                {v.change_narrative && (
                  <span className="mt-0.5 block line-clamp-1 text-[11px] text-text-muted">
                    {v.change_narrative}
                  </span>
                )}
              </span>
              <span className="shrink-0 text-[11px] text-text-muted">
                {v.created_at ? new Date(v.created_at).toLocaleDateString() : ""}
              </span>
            </button>
          ))}
        </Card>
      </section>

      <Collaboration investigation={data} canAct={canRun} />
    </div>
  );
}

/** Comments, and sending the investigation for review. */
function Collaboration({
  investigation,
  canAct,
}: {
  investigation: SavedInvestigation;
  canAct: boolean;
}) {
  const objectId = String(investigation.id);
  const [nonce, setNonce] = React.useState(0);
  const [draft, setDraft] = React.useState("");
  const [sent, setSent] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const thread = useAsync(() => api.comments("investigation", objectId), [objectId, nonce]);

  const post = async () => {
    if (!draft.trim()) return;
    try {
      await api.addComment("investigation", objectId, draft.trim());
      setDraft("");
      setNonce((n) => n + 1);
    } catch (e) {
      setError(e instanceof Error ? e.message : "The comment was not saved.");
    }
  };

  const sendForReview = async () => {
    setError(null);
    try {
      await api.submitForReview({
        objectType: "investigation",
        objectId,
        title: investigation.title,
      });
      setSent(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "IPM could not send this for review.");
    }
  };

  const comments: CommentRow[] = thread.data?.comments ?? [];

  return (
    <section className="grid gap-5 lg:grid-cols-[1.4fr_1fr]">
      <div>
        <h2 className="mb-3 flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-text-muted">
          <MessageSquare className="size-3" aria-hidden />
          Comments
        </h2>
        <Card>
          {comments.length > 0 ? (
            <ul className="divide-y divide-border">
              {comments.map((comment) => (
                <li key={comment.id} className="px-4 py-2.5">
                  <p className="text-sm leading-relaxed text-text-primary">{comment.body}</p>
                  <p className="mt-0.5 text-[11px] text-text-muted">
                    {comment.created_at
                      ? new Date(comment.created_at).toLocaleString()
                      : ""}
                  </p>
                </li>
              ))}
            </ul>
          ) : (
            <p className="px-4 py-5 text-center text-xs text-text-muted">
              No comments yet.
            </p>
          )}
          {canAct && (
          <div className="border-t border-border p-3">
            <textarea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              rows={2}
              placeholder="Add a comment"
              className="w-full resize-none rounded-md border border-border bg-surface px-3 py-2 text-xs text-text-primary placeholder:text-text-muted focus:border-accent focus:outline-none"
            />
            <div className="mt-2 flex justify-end">
              <Button size="sm" variant="outline" disabled={!draft.trim()} onClick={() => void post()}>
                Comment
              </Button>
            </div>
          </div>
          )}
        </Card>
      </div>

      <div>
        <h2 className="mb-3 text-[10px] font-semibold uppercase tracking-[0.14em] text-text-muted">
          Review
        </h2>
        <Card className="p-4">
          <p className="text-xs leading-relaxed text-text-muted">
            Send this to a colleague for review. The decision and any comment become part
            of an append-only history attached to the investigation.
          </p>
          {error && <p className="mt-2 text-xs text-negative">{error}</p>}
          <div className="mt-3 flex items-center gap-2">
            {canAct && (
              <Button size="sm" disabled={sent} onClick={() => void sendForReview()}>
                <Send aria-hidden />
                {sent ? "Sent for review" : "Send for review"}
              </Button>
            )}
            <Button variant="ghost" size="sm" asChild>
              <Link href="/workflow">
                Workflow
                <ArrowRight aria-hidden />
              </Link>
            </Button>
          </div>
        </Card>
      </div>
    </section>
  );
}
