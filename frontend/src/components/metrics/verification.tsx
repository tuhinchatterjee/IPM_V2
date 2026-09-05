"use client";

import * as React from "react";
import { Check, Loader2, X } from "lucide-react";

import { formatMetric } from "@/components/metrics/present";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { api, type MetricValue } from "@/lib/api";
import { useAsync } from "@/lib/hooks";

/**
 * §10: putting your own number beside the one CreditProbe made.
 *
 * The discipline this screen exists to enforce is a single rule: the computed
 * value is NEVER moved toward the expected one. If the two disagree, the
 * record says they disagreed and somebody finds out why. Making the engine
 * agree with the analyst by assignment would defeat the entire exercise, and
 * a workspace that quietly did it would be worse than no workspace.
 *
 * So a comparison is kept whether it agreed or not. A history showing three
 * disagreements before a definition was corrected is more useful than one
 * showing only the final tick.
 *
 * "Accept" is not the same as "agree". Accepting a comparison that differs is
 * allowed — sometimes the analyst's number was the wrong one — but it does not
 * confer VERIFIED, because the stored evidence would not support the label.
 */
export function VerificationWorkspace({
  metricId,
  computed,
  period,
  onVerified,
}: {
  metricId: string;
  computed: MetricValue | null;
  period: string;
  onVerified?: () => void;
}) {
  const [expected, setExpected] = React.useState("");
  const [source, setSource] = React.useState("");
  const [note, setNote] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [nonce, setNonce] = React.useState(0);
  const [outcome, setOutcome] = React.useState<{
    outcome: string;
    agrees: boolean;
    computed: number | null;
    expected: number | null;
    difference: number | null;
    metric_status: string;
    note_on_status?: string;
  } | null>(null);

  const history = useAsync(
    () => api.metricVerifications(metricId),
    [metricId, nonce],
  );

  async function record(decision: "RECORDED" | "ACCEPTED" | "REJECTED") {
    const value = Number(expected);
    if (expected.trim() === "" || Number.isNaN(value)) {
      setError("Put in the number you were expecting.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const body = await api.verifyMetric(metricId, {
        expected: value,
        period,
        expected_source: source.trim(),
        note: note.trim(),
        decision,
      });
      setOutcome(body);
      setNonce((n) => n + 1);
      onVerified?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="space-y-3">
      <div>
        <h3 className="text-sm font-semibold tracking-tight text-text-primary">
          Check this against a number you already trust
        </h3>
        <p className="mt-0.5 max-w-2xl text-xs leading-relaxed text-text-muted">
          Whatever you put in, CreditProbe&rsquo;s figure stays as it is. If the
          two differ, the difference is recorded and the metric is not marked
          verified — which is the point of doing this.
        </p>
      </div>

      <div className="flex flex-wrap items-end gap-2">
        <label className="text-xs text-text-muted">
          Your number
          <input
            value={expected}
            onChange={(e) => setExpected(e.target.value)}
            inputMode="decimal"
            placeholder={
              computed?.value !== null && computed?.value !== undefined
                ? String(computed.value)
                : "0.00"
            }
            className="ml-2 h-8 w-32 rounded-md border border-border bg-surface px-2 text-sm tabular text-text-primary placeholder:text-text-muted focus:border-accent focus:outline-none"
          />
        </label>
        <label className="min-w-0 flex-1 text-xs text-text-muted">
          Where it came from
          <input
            value={source}
            onChange={(e) => setSource(e.target.value)}
            placeholder="Q4 2024 impairment pack, page 12"
            className="ml-2 h-8 w-full min-w-40 rounded-md border border-border bg-surface px-2 text-sm text-text-primary placeholder:text-text-muted focus:border-accent focus:outline-none"
          />
        </label>
      </div>

      <input
        value={note}
        onChange={(e) => setNote(e.target.value)}
        placeholder="Anything a reader of this record should know"
        className="h-8 w-full rounded-md border border-border bg-surface px-2 text-sm text-text-primary placeholder:text-text-muted focus:border-accent focus:outline-none"
      />

      <div className="flex flex-wrap gap-2">
        <Button size="sm" onClick={() => record("ACCEPTED")} disabled={busy}>
          {busy && <Loader2 className="animate-spin" aria-hidden />}
          <Check aria-hidden />
          Compare and accept
        </Button>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => record("RECORDED")}
          disabled={busy}
        >
          Just record it
        </Button>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => record("REJECTED")}
          disabled={busy}
        >
          <X aria-hidden />
          Reject
        </Button>
      </div>

      {error && <p className="text-xs text-negative">{error}</p>}

      {outcome && (
        <div
          className={`rounded-md border p-3 text-xs leading-relaxed ${
            outcome.agrees ? "border-positive/40" : "border-warning/40"
          }`}
        >
          <p className="flex flex-wrap items-center gap-2">
            <Badge variant={outcome.agrees ? "positive" : "warning"}>
              {readableOutcome(outcome.outcome)}
            </Badge>
            <span className="text-text-secondary">
              CreditProbe{" "}
              <span className="tabular">
                {formatMetric(
                  outcome.computed,
                  computed?.unit,
                  computed?.decimals,
                )}
              </span>{" "}
              · you{" "}
              <span className="tabular">
                {formatMetric(
                  outcome.expected,
                  computed?.unit,
                  computed?.decimals,
                )}
              </span>
              {outcome.difference !== null && (
                <>
                  {" "}
                  · difference{" "}
                  <span className="tabular">
                    {formatMetric(
                      outcome.difference,
                      computed?.unit,
                      computed?.decimals,
                    )}
                  </span>
                </>
              )}
            </span>
          </p>
          {outcome.note_on_status && (
            <p className="mt-1 text-text-muted">{outcome.note_on_status}</p>
          )}
        </div>
      )}

      {history.data && history.data.verifications.length > 0 && (
        <div>
          <p className="text-[10px] font-medium uppercase tracking-[0.14em] text-text-muted">
            What has been checked
          </p>
          <ul className="mt-1.5 divide-y divide-border rounded-md border border-border">
            {history.data.verifications.map((row) => (
              <li
                key={row.id}
                className="flex flex-wrap items-baseline gap-x-3 gap-y-1 px-3 py-2 text-xs"
              >
                <Badge
                  variant={
                    row.outcome === "DIFFERS" ? "warning" : "outline"
                  }
                >
                  {readableOutcome(row.outcome)}
                </Badge>
                <span className="tabular text-text-secondary">
                  {formatMetric(row.computed, computed?.unit)} vs{" "}
                  {formatMetric(row.expected, computed?.unit)}
                </span>
                {row.period && (
                  <span className="text-text-muted">{row.period}</span>
                )}
                {row.expected_source && (
                  <span className="min-w-0 flex-1 truncate text-text-muted">
                    {row.expected_source}
                  </span>
                )}
                <span className="text-text-muted">{row.decision}</span>
                {row.created_at && (
                  <span className="text-text-muted">
                    {row.created_at.slice(0, 10)}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

function readableOutcome(outcome: string): string {
  switch (outcome) {
    case "MATCH":
      return "Exactly the same";
    case "WITHIN_TOLERANCE":
      return "Agrees";
    case "DIFFERS":
      return "Differs";
    default:
      return "Not compared";
  }
}
