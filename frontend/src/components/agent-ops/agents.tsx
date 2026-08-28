"use client";

import * as React from "react";
import { ChevronDown, ShieldCheck, Wrench } from "lucide-react";

import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { api, type AgentCatalogue, type AgentDefinition } from "@/lib/api";
import { useAsync } from "@/lib/hooks";
import { cn } from "@/lib/utils";

/**
 * The AGENTS tab. §29.
 *
 * Twelve specialists, each with its purpose, its owner, the tools it may call,
 * the domains it may read, its autonomy, its model ROLE (never a model id —
 * §3), when it last ran and what it scored.
 *
 * §29: "No arbitrary code editor." This is a reading surface. An agent's
 * permissions come from `backend/agentic/registry.py`, which is reviewed like
 * any other code, and a screen that let an administrator widen a tool list in
 * a text box would make every permission in that file decorative.
 *
 * What is worth clicking for
 * -----------------------------
 * `when_not_to_use` and `escalation_rules`. Every agent registry ever written
 * says what its agents are for; what makes this one auditable is that each one
 * also says what it must NOT do and what it does when it cannot proceed.
 */
export function Agents() {
  const found = useAsync(() => api.agentRegistry(), []);
  const [open, setOpen] = React.useState<string | null>(null);

  if (found.loading) return <Skeleton className="h-64 w-full" />;
  if (found.error)
    return <p className="text-sm text-negative">{found.error}</p>;
  const catalogue = found.data as AgentCatalogue | null;
  if (!catalogue) return null;

  return (
    <div className="space-y-4">
      <p className="text-xs text-text-muted">
        {catalogue.agents.length} specialists · registry {catalogue.version} ·
        fingerprint <span className="mono">{catalogue.fingerprint}</span>
      </p>

      <div className="space-y-2">
        {catalogue.agents.map((agent) => (
          <AgentCard
            key={agent.agent_id}
            agent={agent}
            lastRun={catalogue.last_runs[agent.agent_id]}
            open={open === agent.agent_id}
            onToggle={() =>
              setOpen((now) => (now === agent.agent_id ? null : agent.agent_id))
            }
            autonomy={catalogue.autonomy_levels}
          />
        ))}
      </div>
    </div>
  );
}

function AgentCard({
  agent,
  lastRun,
  open,
  onToggle,
  autonomy,
}: {
  agent: AgentDefinition;
  lastRun?: { at: string | null; tasks: number };
  open: boolean;
  onToggle: () => void;
  autonomy: { level: number; name: string; meaning: string }[];
}) {
  const level = autonomy.find((a) => a.level === agent.autonomy_level);
  return (
    <Card className="overflow-hidden p-0" data-testid={`agent-${agent.agent_id}`}>
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        className="flex w-full items-start gap-3 px-4 py-3 text-left transition-colors hover:bg-surface-hover"
      >
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-medium text-text-primary">
              {agent.business_name}
            </span>
            <span className="rounded bg-surface-sunken px-1.5 py-0.5 text-[10px] uppercase tracking-[0.08em] text-text-muted">
              {agent.status}
            </span>
            <span className="text-[11px] text-text-muted">
              {level ? `Autonomy ${level.level} — ${level.name}` : ""}
            </span>
          </div>
          <p className="mt-0.5 line-clamp-2 text-xs text-text-secondary">
            {agent.purpose}
          </p>
          <p className="mt-0.5 flex flex-wrap items-center gap-x-3 text-[11px] text-text-muted">
            <span>
              <Wrench className="mr-1 inline size-3" aria-hidden />
              {agent.allowed_tools.length} tools
            </span>
            <span>{agent.domain_labels.join(", ")}</span>
            <span>Model role: {agent.model_role_preference}</span>
            <span>Owner: {agent.owner}</span>
            {lastRun?.at ? (
              <span>
                Last run {lastRun.at.slice(0, 10)} · {lastRun.tasks} tasks
              </span>
            ) : (
              <span>Never run</span>
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
          <List title="When to use" items={agent.when_to_use} />
          <List title="When not to use" items={agent.when_not_to_use} />
          {agent.escalation_rules.length > 0 && (
            <List title="Escalation rules" items={agent.escalation_rules} />
          )}

          <div className="grid gap-3 sm:grid-cols-2">
            <Chips title="Allowed tools" items={agent.allowed_tools} />
            <Chips title="Data domains" items={agent.domain_labels} />
          </div>

          {agent.human_approval_requirements.length > 0 && (
            <div>
              <h4 className="meta mb-1 text-text-muted">
                <ShieldCheck className="mr-1 inline size-3" aria-hidden />
                Always needs a person
              </h4>
              <div className="flex flex-wrap gap-1">
                {agent.human_approval_requirements.map((action) => (
                  <span
                    key={action}
                    className="rounded bg-warning-muted px-1.5 py-0.5 text-[10px] text-warning"
                  >
                    {action.replace(/_/g, " ")}
                  </span>
                ))}
              </div>
            </div>
          )}

          <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-[11px] sm:grid-cols-4">
            <Fact label="Max steps" value={String(agent.maximum_steps)} />
            <Fact label="Timeout" value={`${agent.timeout_seconds}s`} />
            <Fact label="Version" value={agent.version} />
            <Fact
              label="Certification"
              value={agent.certification_state.replace(/_/g, " ")}
            />
            <Fact
              label="Evaluation"
              value={
                agent.evaluation_score
                  ? agent.evaluation_score.toFixed(2)
                  : "not scored"
              }
            />
            <Fact
              label="Validation"
              value={agent.validation_requirements.join(", ") || "none"}
            />
          </dl>
        </div>
      )}
    </Card>
  );
}

function List({ title, items }: { title: string; items: string[] }) {
  if (!items.length) return null;
  return (
    <div>
      <h4 className="meta mb-1 text-text-muted">{title}</h4>
      <ul className="space-y-0.5">
        {items.map((item, index) => (
          <li
            key={index}
            className="flex items-start gap-1.5 text-xs text-text-secondary"
          >
            <span
              className="mt-1.5 size-1 shrink-0 rounded-full bg-text-muted"
              aria-hidden
            />
            {item}
          </li>
        ))}
      </ul>
    </div>
  );
}

function Chips({ title, items }: { title: string; items: string[] }) {
  if (!items.length) return null;
  return (
    <div>
      <h4 className="meta mb-1 text-text-muted">{title}</h4>
      <div className="flex flex-wrap gap-1">
        {items.map((item) => (
          <span
            key={item}
            className="mono rounded border border-border px-1.5 py-0.5 text-[10px] text-text-secondary"
          >
            {item}
          </span>
        ))}
      </div>
    </div>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-[10px] uppercase tracking-[0.08em] text-text-muted">
        {label}
      </dt>
      <dd className="truncate text-text-secondary">{value}</dd>
    </div>
  );
}
