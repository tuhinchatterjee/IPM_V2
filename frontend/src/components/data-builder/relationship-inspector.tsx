"use client";

import * as React from "react";
import {
  Archive,
  CheckCircle2,
  Clock3,
  Loader2,
  ShieldAlert,
  ShieldCheck,
  TriangleAlert,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  ApiError,
  api,
  type RelationshipDetail,
  type RelationshipEdge,
  type RelationshipValidation,
} from "@/lib/api";
import { useAsync } from "@/lib/hooks";

/**
 * The relationship inspector.
 *
 * A steward deciding whether to trust a join needs four things in one place:
 * what it joins on, what it means in credit terms, what the data actually says
 * about it, and who moved it to its current state. Splitting those across a
 * table, a tooltip and an audit screen is how a wrong cardinality survives.
 *
 * The caller keys this component by relationship id, so a different edge is a
 * different component: a validation report can never survive onto a join it was
 * not measured against.
 *
 * Match and orphan rates are shown as measurements with the date they were
 * taken, never as a static property of the relationship — coverage is a fact
 * about a period of data, and a number with no date behind it invites a reader
 * to believe it is still true.
 */

const CARDINALITY_LABEL: Record<string, string> = {
  one_to_one: "one row to one row",
  many_to_one: "many rows to one row",
  one_to_many: "one row to many rows",
  many_to_many: "many rows to many rows",
};

const POLICY_LABEL: Record<string, string> = {
  inner: "Inner — rows without a match are dropped",
  left: "Left — rows without a match are kept, unmatched columns empty",
  asof: "As-of — the most recent row at or before the reporting date",
};

const LIFECYCLE_TONE: Record<string, "default" | "info" | "outline" | "warning"> = {
  active: "default",
  validated: "info",
  draft: "outline",
  archived: "outline",
};

function pct(value: number | null | undefined): string {
  if (value === null || value === undefined) return "not measured";
  return `${(value * 100).toFixed(1)}%`;
}

export interface RelationshipInspectorProps {
  edge: RelationshipEdge;
  canValidate: boolean;
  canPromote: boolean;
  onChanged: (edge: RelationshipEdge) => void;
}

export function RelationshipInspector({
  edge,
  canValidate,
  canPromote,
  onChanged,
}: RelationshipInspectorProps) {
  const [nonce, setNonce] = React.useState(0);
  const [busy, setBusy] = React.useState("");
  const [error, setError] = React.useState("");
  const [report, setReport] = React.useState<RelationshipValidation | null>(null);
  const detail = useAsync<RelationshipDetail>(
    () => api.relationship(edge.id),
    [edge.id, nonce],
  );

  const current = detail.data?.relationship ?? edge;
  const thresholds = detail.data?.thresholds;

  async function validate() {
    setBusy("validate");
    setError("");
    try {
      const result = await api.validateRelationship(edge.id);
      setReport(result.report);
      onChanged(result.relationship);
      setNonce((n) => n + 1);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "That did not work.");
    } finally {
      setBusy("");
    }
  }

  async function move(to: string) {
    setBusy(to);
    setError("");
    try {
      const result = await api.setRelationshipLifecycle(edge.id, to);
      onChanged(result.relationship);
      setNonce((n) => n + 1);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "That did not work.");
    } finally {
      setBusy("");
    }
  }

  return (
    <Card className="flex h-full flex-col overflow-hidden">
      <div className="border-b border-border px-4 py-3">
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge variant={LIFECYCLE_TONE[current.lifecycle] ?? "outline"}>
            {current.lifecycle_label || current.lifecycle}
          </Badge>
          <span className="text-[11px] text-text-muted tabular">v{current.version}</span>
          {current.is_runnable ? (
            <span className="ml-auto flex items-center gap-1 text-[11px] text-positive">
              <ShieldCheck className="size-3" aria-hidden />
              the runtime may join on this
            </span>
          ) : (
            <span className="ml-auto flex items-center gap-1 text-[11px] text-text-muted">
              <ShieldAlert className="size-3" aria-hidden />
              not available to the runtime
            </span>
          )}
        </div>
        {/* Two qualified column names rarely fit one line in this panel, and a
            truncated key is worse than a wrapped one: a steward reading it is
            checking exactly which column the join uses. */}
        <p className="mt-2 break-all font-mono text-xs leading-relaxed text-text-primary">
          {current.from_dataset}.{current.from_field}
          <span className="px-1.5 text-text-muted">→</span>
          {current.to_dataset}.{current.to_field}
        </p>
      </div>

      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-4 py-3">
        <Section title="What it means">
          <p className="text-xs leading-relaxed text-text-secondary">
            {current.semantic || current.description || "No definition recorded."}
          </p>
          {current.semantic && current.description && current.semantic !== current.description && (
            <p className="mt-1.5 text-[11px] leading-relaxed text-text-muted">
              {current.description}
            </p>
          )}
        </Section>

        <Section title="How it joins">
          <Row label="Cardinality">
            {CARDINALITY_LABEL[current.cardinality] ?? current.cardinality}
          </Row>
          <Row label="Join">{POLICY_LABEL[current.join_policy] ?? current.join_policy}</Row>
          {current.temporal_label && (
            <Row label="Periods">
              <span className="flex items-start gap-1.5">
                <Clock3 className="mt-0.5 size-3 shrink-0 text-text-muted" aria-hidden />
                {current.temporal_label}
              </span>
            </Row>
          )}
          <Row label="Confidence">
            <span className="tabular">{current.confidence.toFixed(2)}</span>
            {thresholds && current.confidence < thresholds.min_confidence && (
              <span className="ml-1.5 text-warning">
                below the {thresholds.min_confidence.toFixed(2)} needed to run
              </span>
            )}
          </Row>
          {current.is_preferred && (
            <Row label="Preference">
              Preferred where more than one path reaches the same dataset.
            </Row>
          )}
        </Section>

        <Section
          title="What the data says"
          aside={
            current.validated_at
              ? `measured ${new Date(current.validated_at).toLocaleDateString()}`
              : "never measured"
          }
        >
          <div className="grid grid-cols-3 gap-2">
            <Measure label="Matched" value={pct(current.match_rate)}
              bad={thresholds !== undefined && current.match_rate !== null
                && current.match_rate < thresholds.min_match_rate} />
            <Measure label="Orphaned" value={pct(current.orphan_rate)}
              bad={current.orphan_rate !== null && current.orphan_rate > 0.2} />
            <Measure label="Duplicated" value={pct(current.duplicate_rate)}
              bad={thresholds !== undefined && current.duplicate_rate !== null
                && current.duplicate_rate > thresholds.max_duplicate_rate
                && ["one_to_one", "many_to_one"].includes(current.cardinality)} />
          </div>
          {!current.validated_at && (
            <p className="mt-2 text-[11px] leading-relaxed text-text-muted">
              A declared cardinality is an intention. Whether the right side really has unique
              keys is a property of the data, and the difference between the two is a silently
              multiplied book.
            </p>
          )}
          {report && (
            <div className="mt-2.5 rounded-md border border-border bg-surface-sunken p-2.5">
              <p className="flex items-center gap-1.5 text-xs font-medium">
                {report.ok ? (
                  <>
                    <CheckCircle2 className="size-3.5 text-positive" aria-hidden />
                    <span className="text-positive">The join holds against the data.</span>
                  </>
                ) : (
                  <>
                    <TriangleAlert className="size-3.5 text-warning" aria-hidden />
                    <span className="text-warning">
                      {report.findings.length}{" "}
                      {report.findings.length === 1 ? "finding" : "findings"}
                    </span>
                  </>
                )}
              </p>
              {report.findings.length > 0 && (
                <ul className="mt-1.5 space-y-1">
                  {report.findings.map((finding) => (
                    <li key={finding} className="text-[11px] leading-relaxed text-text-secondary">
                      {finding}
                    </li>
                  ))}
                </ul>
              )}
              {(report.left_period || report.right_period) && (
                <p className="mt-1.5 text-[10px] text-text-muted">
                  Measured at {report.left_period ?? "all history"} against{" "}
                  {report.right_period ?? "all history"}.
                </p>
              )}
            </div>
          )}
        </Section>

        <Section title="History">
          {detail.loading && !detail.data ? (
            <Skeleton className="h-16 w-full" />
          ) : (detail.data?.versions.length ?? 0) === 0 ? (
            <p className="text-[11px] text-text-muted">
              Declared and unchanged since. Every later change records what it was before.
            </p>
          ) : (
            <ol className="space-y-1.5">
              {detail.data?.versions.map((entry) => (
                <li key={entry.version} className="flex gap-2 text-[11px] leading-relaxed">
                  <span className="tabular shrink-0 text-text-muted">v{entry.version}</span>
                  <span className="text-text-secondary">
                    {entry.change_note || "Recorded."}
                    {entry.created_at && (
                      <span className="ml-1.5 text-text-muted">
                        {new Date(entry.created_at).toLocaleDateString()}
                      </span>
                    )}
                  </span>
                </li>
              ))}
            </ol>
          )}
        </Section>
      </div>

      {error && <p className="px-4 pb-2 text-xs text-negative">{error}</p>}

      {(canValidate || canPromote) && (
        <div className="flex flex-wrap gap-1.5 border-t border-border px-4 py-3">
          {canValidate && (
            <Button variant="outline" size="sm" onClick={validate} disabled={busy !== ""}>
              {busy === "validate" ? (
                <Loader2 className="animate-spin" aria-hidden />
              ) : (
                <ShieldCheck aria-hidden />
              )}
              Measure against the data
            </Button>
          )}
          {canPromote && current.lifecycle !== "active" && (
            <Button size="sm" onClick={() => move("active")} disabled={busy !== ""}>
              {busy === "active" ? <Loader2 className="animate-spin" aria-hidden /> : null}
              Make it runnable
            </Button>
          )}
          {canPromote && current.lifecycle !== "archived" && (
            <Button variant="ghost" size="sm" onClick={() => move("archived")} disabled={busy !== ""}>
              {busy === "archived" ? (
                <Loader2 className="animate-spin" aria-hidden />
              ) : (
                <Archive aria-hidden />
              )}
              Withdraw
            </Button>
          )}
        </div>
      )}
    </Card>
  );
}

function Section({
  title,
  aside,
  children,
}: {
  title: string;
  aside?: string;
  children: React.ReactNode;
}) {
  return (
    <section>
      <div className="mb-1.5 flex items-baseline gap-2">
        <h3 className="meta text-text-muted">{title}</h3>
        {aside && <span className="text-[10px] text-text-muted">{aside}</span>}
      </div>
      {children}
    </section>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex gap-2 py-0.5 text-xs leading-relaxed">
      <span className="w-24 shrink-0 text-text-muted">{label}</span>
      <span className="text-text-secondary">{children}</span>
    </div>
  );
}

function Measure({ label, value, bad }: { label: string; value: string; bad?: boolean }) {
  return (
    <div className="rounded-md border border-border px-2 py-1.5">
      <p className="text-[10px] text-text-muted">{label}</p>
      <p className={`tabular mt-0.5 text-sm font-semibold ${bad ? "text-warning" : "text-text-primary"}`}>
        {value}
      </p>
    </div>
  );
}
