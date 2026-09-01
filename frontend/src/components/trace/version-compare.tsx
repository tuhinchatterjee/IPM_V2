"use client";

import * as React from "react";
import { GitCompare, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { api, type StoredInvestigation } from "@/lib/api";
import { cn } from "@/lib/utils";

import {
  compare,
  summarise,
  type ComparableVersion,
  type NodeChange,
} from "./compare";

/**
 * Two versions of one analysis, and what changed between them.
 *
 * §49. The version switcher already lets a reader move between versions; the
 * question it cannot answer is the one they actually have — somebody modified
 * this Trace, and what did that DO? Reading two graphs side by side and
 * holding them in your head is not an answer.
 *
 * The diff itself is in `compare.ts` and is tested there. This fetches the
 * other version and renders the result.
 */
export function VersionCompare({
  runId,
  current,
  currentVersion,
  versions,
}: {
  runId: number;
  /** The version on screen, already loaded. */
  current: StoredInvestigation;
  currentVersion: number;
  versions: { version: number; label: string }[];
}) {
  const [against, setAgainst] = React.useState<number | null>(null);
  // One piece of state carrying WHICH version it belongs to. Loading is then
  // derived — "asked for a version we have not got yet" — rather than being a
  // second flag that has to be flipped in step with the fetch. Two flags is
  // how a panel ends up showing version 3's diff while the spinner claims to
  // be fetching version 4.
  const [loaded, setLoaded] = React.useState<{
    version: number;
    data: StoredInvestigation | null;
    error: string;
  } | null>(null);

  React.useEffect(() => {
    if (against === null) return;
    let live = true;
    api
      .investigation(runId, against)
      .then((data) => {
        if (live) setLoaded({ version: against, data, error: "" });
      })
      .catch((error: unknown) => {
        if (!live) return;
        setLoaded({
          version: against,
          data: null,
          error:
            error instanceof Error
              ? error.message
              : "That version could not be loaded.",
        });
      });
    return () => {
      live = false;
    };
  }, [runId, against]);

  const settled = loaded && loaded.version === against ? loaded : null;
  const loading = against !== null && settled === null;
  const other = settled?.data ?? null;
  const problem = settled?.error ?? "";

  const options = versions.filter((v) => v.version !== currentVersion);
  if (options.length === 0) return null;

  const found =
    other && against !== null
      ? compare(asComparable(other, against), asComparable(current, currentVersion))
      : null;

  return (
    <Card className="space-y-3 p-4">
      <div className="flex flex-wrap items-center gap-2">
        <GitCompare className="size-3.5 shrink-0 text-text-muted" aria-hidden />
        <span className="text-[11px] font-medium uppercase tracking-[0.11em] text-text-muted">
          Compare with
        </span>
        <div className="flex flex-wrap items-center gap-1">
          {options.map((v) => (
            <button
              key={v.version}
              type="button"
              onClick={() =>
                setAgainst((now) => (now === v.version ? null : v.version))
              }
              aria-pressed={against === v.version}
              className={cn(
                "rounded px-2 py-1 text-xs transition-colors",
                against === v.version
                  ? "bg-accent text-accent-contrast"
                  : "text-text-secondary hover:bg-surface-hover",
              )}
            >
              {v.label}
            </button>
          ))}
        </div>
        {against !== null && (
          <Button
            variant="ghost"
            size="sm"
            className="ml-auto"
            onClick={() => setAgainst(null)}
          >
            <X aria-hidden />
            Close
          </Button>
        )}
      </div>

      {loading && <Skeleton className="h-24 w-full" />}
      {problem && <p className="text-xs text-negative">{problem}</p>}

      {found && !loading && (
        <div className="space-y-3">
          <p className="text-xs text-text-secondary">{summarise(found)}</p>

          <dl className="grid gap-2 sm:grid-cols-2">
            <Side
              title={`Version ${found.from}`}
              answer={found.answerBefore}
              rows={found.rowsBefore}
            />
            <Side
              title={`Version ${found.to} (on screen)`}
              answer={found.answerAfter}
              rows={found.rowsAfter}
            />
          </dl>

          {found.changes.length > 0 && (
            <ul className="space-y-1.5">
              {found.changes.map((change, index) => (
                <li key={`${change.id}-${change.kind}-${index}`}>
                  <Change change={change} />
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </Card>
  );
}

function Side({
  title,
  answer,
  rows,
}: {
  title: string;
  answer: string;
  rows: number | null;
}) {
  return (
    <div className="rounded-md border border-border bg-surface-sunken p-2.5">
      <dt className="text-[11px] font-medium uppercase tracking-[0.11em] text-text-muted">
        {title}
      </dt>
      <dd className="mt-1 text-xs leading-relaxed text-text-secondary">
        {answer || "No answer recorded for this version."}
      </dd>
      <dd className="mono mt-1 text-[11px] text-text-muted">
        {rows === null ? "row count not recorded" : `${rows.toLocaleString()} rows`}
      </dd>
    </div>
  );
}

const WORDS: Record<NodeChange["kind"], string> = {
  added: "added",
  removed: "removed",
  status: "status",
  rows: "rows",
  label: "renamed",
};

function Change({ change }: { change: NodeChange }) {
  return (
    <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 text-[11px]">
      <span
        className={cn(
          "rounded px-1.5 py-0.5 font-medium uppercase tracking-[0.08em]",
          change.kind === "added" && "bg-positive-muted text-positive",
          change.kind === "removed" && "bg-negative-muted text-negative",
          change.kind === "rows" && "bg-accent-muted text-accent",
          (change.kind === "status" || change.kind === "label") &&
            "bg-surface-sunken text-text-muted",
        )}
      >
        {WORDS[change.kind]}
      </span>
      <span className="text-text-primary">{change.label}</span>
      {change.before && change.after && (
        <span className="text-text-muted">
          <span className="line-through">{change.before}</span>
          {" → "}
          <span className="text-text-secondary">{change.after}</span>
        </span>
      )}
      <span className="mono ml-auto text-[10px] text-text-muted">{change.id}</span>
    </div>
  );
}

/**
 * A stored version, reduced to what the diff needs.
 *
 * Kept here rather than in `compare.ts` so the diff stays free of the API's
 * shapes — the day the response gains a field, one adapter changes and the
 * comparison and its tests do not.
 */
function asComparable(
  found: StoredInvestigation,
  version: number,
): ComparableVersion {
  const primary =
    found.steps.find((s) => s.role === "primary") ?? found.steps[0] ?? null;
  return {
    version,
    label: found.label,
    nodes: (found.graph?.nodes ?? []).map((n) => ({
      id: n.id,
      type: n.type,
      label: n.label,
      status: n.status,
      rows_out: n.rows_out ?? null,
    })),
    answer: found.narrative?.direct_answer ?? found.narrative?.summary ?? "",
    rowCount: primary?.result?.rows?.length ?? null,
  };
}
