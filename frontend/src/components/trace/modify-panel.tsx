"use client";

import * as React from "react";
import {
  ArrowRight,
  Check,
  CornerDownLeft,
  GitBranch,
  Loader2,
  Minus,
  Plus,
  RotateCcw,
  TriangleAlert,
  Wand2,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ApiError, api, type ProposedChange, type StepChange, type SupportedModification } from "@/lib/api";
import { humanise } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { TraceAction } from "@/components/trace/actions";

/**
 * Ask / Modify Trace.
 *
 * The interaction is deliberately two-stage, and the two stages are not the same
 * kind of action:
 *
 *   1. **Propose.** Nothing runs. CreditProbe says what it understood, which steps would
 *      change, and which parts of the map that invalidates. If it did not
 *      understand, it says so and lists what it can do — it never approximates.
 *   2. **Apply & re-run.** Only on an explicit press. The affected steps re-run,
 *      the unaffected ones reuse their recorded results, and the outcome is
 *      stored as a NEW version. Nothing about the version being modified changes.
 *
 * The separation is the governance point. A user reviewing a credit paper is
 * entitled to see what a requested change would do before it is done.
 */

const PLACEHOLDER = "Exclude Real Estate. Use borrower count instead of EAD. Add ECL Movement.";

export function ModifyPanel({
  runId,
  version,
  supported,
  actions,
  onPreview,
  onApplied,
  disabled,
  disabledReason,
}: {
  runId: number;
  version: number;
  supported: SupportedModification[];
  /** What is worth changing about THIS Trace, in its own terms. */
  actions?: TraceAction[];
  /** Called whenever the proposed change changes, so the map can highlight it. */
  onPreview: (change: ProposedChange | null) => void;
  onApplied: (newVersion: number) => void;
  disabled?: boolean;
  disabledReason?: string;
}) {
  const [text, setText] = React.useState("");
  const [change, setChange] = React.useState<ProposedChange | null>(null);
  const [busy, setBusy] = React.useState<"preview" | "apply" | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  const publish = React.useCallback(
    (next: ProposedChange | null) => {
      setChange(next);
      onPreview(next);
    },
    [onPreview],
  );

  async function propose(request: string) {
    if (!request.trim() || disabled) return;
    setBusy("preview");
    setError(null);
    try {
      publish(await api.previewModification(runId, request.trim(), version));
    } catch (e) {
      publish(null);
      setError(e instanceof ApiError ? e.message : "Could not interpret that change.");
    } finally {
      setBusy(null);
    }
  }

  async function apply() {
    if (!change?.applicable) return;
    setBusy("apply");
    setError(null);
    try {
      const applied = await api.applyModification(runId, change.request, version);
      publish(null);
      setText("");
      onApplied(applied.version);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not apply that change.");
    } finally {
      setBusy(null);
    }
  }

  function reset() {
    publish(null);
    setText("");
    setError(null);
  }

  return (
    <section className="rounded-lg border border-border bg-surface">
      <div className="flex items-center gap-2 border-b border-border px-5 py-3">
        <Wand2 className="size-3.5 text-accent" aria-hidden />
        <h3 className="text-sm font-semibold tracking-tight text-text-primary">
          Ask / Modify Trace
        </h3>
        <span className="ml-auto text-[11px] text-text-muted">
          Changes branch to a new version. The original is kept.
        </span>
      </div>

      <div className="px-5 py-4">
        {disabled ? (
          <p className="text-sm text-text-muted">{disabledReason}</p>
        ) : (
          <>
            <div className="relative">
              <textarea
                value={text}
                onChange={(e) => setText(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    void propose(text);
                  }
                }}
                rows={2}
                placeholder={PLACEHOLDER}
                aria-label="Describe a change to this analysis"
                className="w-full resize-none rounded-md border border-border bg-surface-sunken px-3 py-2.5 pr-28 text-sm text-text-primary placeholder:text-text-muted focus:border-accent focus:outline-none"
              />
              <Button
                size="sm"
                className="absolute bottom-2 right-2"
                disabled={!text.trim() || busy !== null}
                onClick={() => void propose(text)}
              >
                {busy === "preview" ? (
                  <Loader2 className="animate-spin" aria-hidden />
                ) : (
                  <CornerDownLeft aria-hidden />
                )}
                Propose
              </Button>
            </div>

            <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
              <span className="mr-0.5 text-[10px] font-semibold uppercase tracking-[0.11em] text-text-muted">
                Try
              </span>
              {/* This Trace's own terms where they are known, the general list
                  otherwise. "Exclude Real Estate" under a Contracting analysis
                  is a chip that changes the subject, and under a catalogue
                  lookup it is a chip that means nothing at all. */}
              {(actions?.length ? actions : supported).slice(0, 6).map((option) => (
                <button
                  key={option.kind}
                  type="button"
                  title={option.label}
                  onClick={() => {
                    setText(option.example);
                    void propose(option.example);
                  }}
                  className="rounded-full border border-border px-2.5 py-1 text-[11px] text-text-secondary transition-colors hover:border-accent hover:text-accent"
                >
                  {option.example}
                </button>
              ))}
            </div>

            {error && (
              <p className="mt-3 flex items-start gap-2 text-xs text-negative">
                <TriangleAlert className="mt-0.5 size-3.5 shrink-0" aria-hidden />
                {error}
              </p>
            )}

            {change && (
              <ProposedChangeView
                change={change}
                busy={busy === "apply"}
                onApply={() => void apply()}
                onDiscard={reset}
              />
            )}
          </>
        )}
      </div>
    </section>
  );
}

function ProposedChangeView({
  change,
  busy,
  onApply,
  onDiscard,
}: {
  change: ProposedChange;
  busy: boolean;
  onApply: () => void;
  onDiscard: () => void;
}) {
  const total =
    change.changed_steps.length + change.added_steps.length + change.removed_steps.length;

  return (
    <div className="mt-4 overflow-hidden rounded-lg border border-border-strong">
      <div className="flex items-center gap-2 border-b border-border bg-surface-sunken px-4 py-2.5">
        <GitBranch className="size-3.5 text-text-muted" aria-hidden />
        <h4 className="text-xs font-semibold uppercase tracking-[0.11em] text-text-primary">
          Proposed Trace change
        </h4>
        {change.applicable && (
          <Badge variant="accent" className="ml-auto">
            {total} {total === 1 ? "step" : "steps"} affected
          </Badge>
        )}
      </div>

      <div className="space-y-4 px-4 py-3.5">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.11em] text-text-muted">
            Understood as
          </p>
          <p className="mt-1 text-sm leading-relaxed text-text-primary">{change.description}</p>
        </div>

        {!change.understood && (
          <div>
            <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-[0.11em] text-text-muted">
              What CreditProbe can change
            </p>
            <ul className="space-y-1">
              {change.supported.map((option) => (
                <li key={option.kind} className="flex gap-2 text-xs text-text-secondary">
                  <span aria-hidden className="text-text-muted">
                    ·
                  </span>
                  <span>
                    <span className="text-text-primary">{option.label}</span>
                    <span className="text-text-muted"> — “{option.example}”</span>
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {change.rejected.length > 0 && (
          <div className="rounded-md border border-negative/30 bg-negative-muted p-3">
            <p className="mb-1 text-xs font-medium text-negative">
              CreditProbe refused this change
            </p>
            {change.rejected.map((reason) => (
              <p key={reason} className="text-xs text-negative">
                {reason}
              </p>
            ))}
          </div>
        )}

        {(change.changed_steps.length > 0 ||
          change.added_steps.length > 0 ||
          change.removed_steps.length > 0) && (
          <div className="space-y-2">
            {change.changed_steps.map((step) => (
              <StepDiff key={`c-${step.index}`} kind="changed" step={step} />
            ))}
            {change.added_steps.map((step) => (
              <StepDiff key={`a-${step.index}`} kind="added" step={step} />
            ))}
            {change.removed_steps.map((step) => (
              <StepDiff key={`r-${step.index}`} kind="removed" step={step} />
            ))}
          </div>
        )}

        {change.applicable && (
          <div className="grid gap-2 sm:grid-cols-3">
            <Tally
              label="Steps re-run"
              value={change.changed_steps.length + change.added_steps.length}
              tone="warning"
            />
            <Tally
              label="Steps reused"
              value={change.unchanged_steps.length}
              tone="positive"
              hint="Nothing about these changed"
            />
            <Tally
              label="Map nodes affected"
              value={change.affected_nodes.length + change.downstream_nodes.length}
              tone="accent"
            />
          </div>
        )}

        <div className="flex flex-wrap items-center gap-2 border-t border-border pt-3">
          <Button onClick={onApply} disabled={!change.applicable || busy}>
            {busy ? <Loader2 className="animate-spin" aria-hidden /> : <Check aria-hidden />}
            Apply &amp; re-run
          </Button>
          <Button variant="ghost" onClick={onDiscard} disabled={busy}>
            <RotateCcw aria-hidden />
            Discard
          </Button>
          <span className="text-[11px] text-text-muted">
            {change.applicable
              ? "The current version is preserved; this creates a new one."
              : "Nothing will run."}
          </span>
        </div>
      </div>
    </div>
  );
}

function StepDiff({
  kind,
  step,
}: {
  kind: "changed" | "added" | "removed";
  step: StepChange;
}) {
  const Icon = kind === "added" ? Plus : kind === "removed" ? Minus : ArrowRight;
  const tone =
    kind === "added"
      ? "border-positive/40 bg-positive-muted"
      : kind === "removed"
        ? "border-negative/40 bg-negative-muted"
        : "border-warning/40 bg-warning-muted";

  const before = step.was ? { ...step.was.params, ...step.was.filters } : null;
  const after = { ...step.params, ...step.filters };
  const keys = [...new Set([...Object.keys(before ?? {}), ...Object.keys(after)])];

  return (
    <div className={cn("rounded-md border px-3 py-2", tone)}>
      <p className="flex items-center gap-1.5 text-xs font-medium text-text-primary">
        <Icon className="size-3 shrink-0" aria-hidden />
        {step.title}
        <span className="font-normal text-text-muted">
          {kind === "added" ? "added" : kind === "removed" ? "removed" : "re-runs"}
        </span>
      </p>
      {kind === "changed" && before && (
        <ul className="mt-1 space-y-0.5">
          {keys
            .filter((key) => JSON.stringify(before[key]) !== JSON.stringify(after[key]))
            .map((key) => (
              <li key={key} className="flex items-center gap-1.5 text-[11px] text-text-secondary">
                <span className="text-text-muted">{humanise(key)}</span>
                <code className="rounded bg-surface/70 px-1 font-mono text-[10px] line-through opacity-70">
                  {short(before[key])}
                </code>
                <ArrowRight className="size-2.5 text-text-muted" aria-hidden />
                <code className="rounded bg-surface/70 px-1 font-mono text-[10px]">
                  {short(after[key])}
                </code>
              </li>
            ))}
        </ul>
      )}
    </div>
  );
}

function short(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (Array.isArray(value)) {
    return value.length <= 2
      ? value.map(String).join(", ")
      : `${value.length} values`;
  }
  const text = typeof value === "object" ? JSON.stringify(value) : String(value);
  return text.length > 28 ? `${text.slice(0, 27)}…` : text;
}

function Tally({
  label,
  value,
  tone,
  hint,
}: {
  label: string;
  value: number;
  tone: "warning" | "positive" | "accent";
  hint?: string;
}) {
  return (
    <div className="rounded-md border border-border bg-surface-sunken px-3 py-2">
      <p className="text-[10px] uppercase tracking-[0.11em] text-text-muted">{label}</p>
      <p
        className={cn(
          "mt-0.5 text-lg font-semibold tabular",
          tone === "warning" && "text-warning",
          tone === "positive" && "text-positive",
          tone === "accent" && "text-accent",
        )}
      >
        {value}
      </p>
      {hint && <p className="text-[10px] text-text-muted">{hint}</p>}
    </div>
  );
}

/** Original / Version 2 / Version 3 — switch between every stored version. */
export function VersionSwitcher({
  versions,
  current,
  onSelect,
}: {
  versions: { version: number; label: string; created_at?: string | null }[];
  current: number;
  onSelect: (version: number) => void;
}) {
  if (versions.length <= 1) return null;
  return (
    <div className="flex flex-wrap items-center gap-1 rounded-md border border-border bg-surface p-1">
      {versions.map((v) => (
        <button
          key={v.version}
          type="button"
          onClick={() => onSelect(v.version)}
          aria-pressed={v.version === current}
          className={cn(
            "rounded px-2.5 py-1 text-xs transition-colors",
            v.version === current
              ? "bg-accent text-accent-contrast"
              : "text-text-secondary hover:bg-surface-hover",
          )}
        >
          {v.label}
        </button>
      ))}
    </div>
  );
}
