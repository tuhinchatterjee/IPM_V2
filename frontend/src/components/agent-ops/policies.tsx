"use client";

import * as React from "react";
import { ChevronDown, History } from "lucide-react";

import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { api, type AgentPolicy } from "@/lib/api";
import { useAsync } from "@/lib/hooks";
import { cn } from "@/lib/utils";

/**
 * The POLICIES tab. §32.
 *
 * Six policies — autonomy, budgets, screening thresholds, severity weights,
 * notification and retention — each versioned, each with its history.
 *
 * Versioned by row, never edited
 * -------------------------------
 * "What was the auto-create threshold when this case was raised" is a question
 * somebody asks in a review, and a row that was updated in place cannot answer
 * it. Writing a new version and deactivating the old one costs one row and
 * makes the answer readable off the screen.
 *
 * Read here, changed through the API
 * -----------------------------------
 * This tab shows the active value and the history. Changing one is an
 * administrator's PUT, and it is deliberately not a free-text box in this
 * screen: an autonomy policy edited by typing JSON into a browser is an
 * autonomy policy nobody reviewed.
 */
export function Policies() {
  const found = useAsync(() => api.agentPolicies(), []);
  const [open, setOpen] = React.useState<string | null>(null);

  if (found.loading) return <Skeleton className="h-64 w-full" />;
  if (found.error) return <p className="text-sm text-negative">{found.error}</p>;

  return (
    <div className="space-y-2">
      {(found.data?.policies ?? []).map((policy) => (
        <PolicyCard
          key={policy.key}
          policy={policy}
          open={open === policy.key}
          onToggle={() =>
            setOpen((now) => (now === policy.key ? null : policy.key))
          }
        />
      ))}
    </div>
  );
}

function PolicyCard({
  policy,
  open,
  onToggle,
}: {
  policy: AgentPolicy;
  open: boolean;
  onToggle: () => void;
}) {
  return (
    <Card className="overflow-hidden p-0" data-testid={`policy-${policy.key}`}>
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        className="flex w-full items-start gap-3 px-4 py-3 text-left transition-colors hover:bg-surface-hover"
      >
        <div className="min-w-0 flex-1">
          <span className="text-sm font-medium text-text-primary">
            {policy.label}
          </span>
          <p className="mt-0.5 flex flex-wrap items-center gap-x-3 text-[11px] text-text-muted">
            <span className="mono">{policy.key}</span>
            <span>Version {policy.version || "shipped default"}</span>
            {policy.versions > 1 && (
              <span>
                <History className="mr-1 inline size-3" aria-hidden />
                {policy.versions} versions
              </span>
            )}
          </p>
        </div>
        <ChevronDown
          className={cn(
            "mt-1 size-4 shrink-0 text-text-muted transition-transform",
            open && "rotate-180",
          )}
          aria-hidden
        />
      </button>

      {open && (
        <div className="space-y-3 border-t border-border bg-surface-sunken px-4 py-3">
          <Value value={policy.value} />
          {policy.history.length > 1 && (
            <div>
              <h4 className="meta mb-1 text-text-muted">Version history</h4>
              <ul className="space-y-0.5">
                {policy.history.map((version) => (
                  <li
                    key={version.version}
                    className="flex items-baseline gap-2 text-[11px]"
                  >
                    <span className="mono text-text-muted">
                      v{version.version}
                    </span>
                    <span
                      className={cn(
                        version.active ? "text-positive" : "text-text-muted",
                      )}
                    >
                      {version.active ? "active" : "superseded"}
                    </span>
                    <span className="text-text-secondary">
                      {version.note || "no note"}
                    </span>
                    <span className="mono ml-auto text-text-muted">
                      {(version.at ?? "").slice(0, 10)}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </Card>
  );
}

/**
 * A policy document, flattened to readable rows.
 *
 * Rows rather than a JSON dump: an administrator reading "max model calls: 12"
 * learns something, and one reading `{"model_calls": 12}` has to parse it
 * first.
 */
function Value({ value }: { value: Record<string, unknown> }) {
  const rows = flatten(value);
  if (!rows.length)
    return <p className="text-xs text-text-muted">Nothing configured.</p>;
  return (
    <dl className="grid gap-x-6 gap-y-1 sm:grid-cols-2">
      {rows.map(([key, shown]) => (
        <div key={key} className="flex items-baseline justify-between gap-3">
          <dt className="min-w-0 truncate text-[11px] text-text-secondary">
            {key.replace(/[._]/g, " ")}
          </dt>
          <dd className="mono shrink-0 text-[11px] text-text-primary tabular">
            {shown}
          </dd>
        </div>
      ))}
    </dl>
  );
}

function flatten(
  value: Record<string, unknown>,
  prefix = "",
): [string, string][] {
  const out: [string, string][] = [];
  for (const [key, item] of Object.entries(value ?? {})) {
    const path = prefix ? `${prefix}.${key}` : key;
    if (item && typeof item === "object" && !Array.isArray(item)) {
      out.push(...flatten(item as Record<string, unknown>, path));
    } else if (Array.isArray(item)) {
      out.push([path, item.length ? item.join(", ") : "none"]);
    } else {
      out.push([path, String(item)]);
    }
  }
  return out;
}
