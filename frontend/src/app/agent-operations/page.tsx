"use client";

import * as React from "react";

import { PageHeader } from "@/components/layout/page-header";
import { useRole } from "@/components/system/role-switcher";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

/**
 * Agent Operations. §28–§33, §64, §78.
 *
 * Six tabs: AGENTS, RUNS, SCHEDULES, POLICIES, APPROVALS, EVALUATIONS.
 *
 * Lazy, deliberately
 * ------------------
 * §78: "Do not block first paint on Agent Operations code. Lazy-load admin
 * screens." Every panel is a `React.lazy` import, so a Cockpit user who never
 * opens this page never downloads the run tables, the policy editor or the
 * evaluation grid — and opening one tab does not download the other five.
 *
 * Role
 * ----
 * §64: "Only authorized roles can access it." The sidebar hides the link for
 * an analyst, this page says so plainly if they arrive by URL, and every
 * endpoint behind it refuses them. Three layers, and only the third is
 * security — the other two are manners.
 */

const Agents = React.lazy(() =>
  import("@/components/agent-ops/agents").then((m) => ({ default: m.Agents })),
);
const Runs = React.lazy(() =>
  import("@/components/agent-ops/runs").then((m) => ({ default: m.Runs })),
);
const Schedules = React.lazy(() =>
  import("@/components/agent-ops/schedules").then((m) => ({
    default: m.Schedules,
  })),
);
const Policies = React.lazy(() =>
  import("@/components/agent-ops/policies").then((m) => ({
    default: m.Policies,
  })),
);
const Approvals = React.lazy(() =>
  import("@/components/agent-ops/approvals").then((m) => ({
    default: m.Approvals,
  })),
);
const Evaluations = React.lazy(() =>
  import("@/components/agent-ops/evaluations").then((m) => ({
    default: m.Evaluations,
  })),
);

const TABS = [
  { id: "agents", label: "Agents", Panel: Agents },
  { id: "runs", label: "Runs", Panel: Runs },
  { id: "schedules", label: "Schedules", Panel: Schedules },
  { id: "policies", label: "Policies", Panel: Policies },
  { id: "approvals", label: "Approvals", Panel: Approvals },
  { id: "evaluations", label: "Evaluations", Panel: Evaluations },
] as const;

type TabId = (typeof TABS)[number]["id"];

export default function AgentOperationsPage() {
  const [tab, setTab] = React.useState<TabId>("agents");
  const { role } = useRole();
  const permitted = role === "ADMIN" || role === "DATA_STEWARD";

  const active = TABS.find((t) => t.id === tab) ?? TABS[0];
  const Panel = active.Panel;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Agent Operations"
        description="The governed agentic layer: who the specialists are and what each may do, every run and what it cost, the schedules that fire on their own, the policies they run under, the approvals waiting for a person, and how they score against the evaluation corpus."
      />

      {!permitted ? (
        <Card className="p-6">
          <h2 className="text-sm font-medium text-text-primary">
            Agent Operations is for data stewards and administrators
          </h2>
          <p className="mt-1.5 max-w-2xl text-sm leading-relaxed text-text-secondary">
            This screen governs what CreditProbe&rsquo;s agents are permitted to
            do — their tools, their data domains, their budgets and their
            autonomy. Reading it needs the standing to change it, and every
            endpoint behind it enforces that regardless of what the sidebar
            shows.
          </p>
        </Card>
      ) : (
        <>
          <div
            role="tablist"
            aria-label="Agent Operations"
            className="flex flex-wrap items-center gap-1 border-b border-border pb-2"
          >
            {TABS.map((one) => (
              <button
                key={one.id}
                type="button"
                role="tab"
                aria-selected={tab === one.id}
                onClick={() => setTab(one.id)}
                data-testid={`agent-ops-tab-${one.id}`}
                className={cn(
                  "rounded px-2.5 py-1.5 text-xs uppercase tracking-[0.08em] transition-colors",
                  tab === one.id
                    ? "bg-accent text-accent-contrast"
                    : "text-text-secondary hover:bg-surface-hover",
                )}
              >
                {one.label}
              </button>
            ))}
          </div>

          <React.Suspense fallback={<Skeleton className="h-64 w-full" />}>
            <Panel />
          </React.Suspense>
        </>
      )}
    </div>
  );
}
