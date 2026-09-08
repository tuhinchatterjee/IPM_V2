"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { api, type EarlyWarningV2Diagnosis } from "@/lib/api";
import { money } from "@/lib/format";
import { useAsync } from "@/lib/hooks";

/**
 * AI interpretation for a selected band or segment (spec Section AO).
 *
 * A band or segment click used to just filter the same borrower table —
 * true, but not an interpretation. This wires the already-built descriptive
 * diagnosis endpoint into a panel that says what the selected population has
 * in common: how big it is, how much exposure it carries, and its top
 * drivers as a small bar chart. Descriptive only, never predictive — the
 * endpoint's own note is shown verbatim so that stays visible here too.
 */
export function InterpretationPanel({
  band,
  segment,
  label,
}: {
  band?: string;
  segment?: string;
  label: string;
}) {
  const diagnosis = useAsync<EarlyWarningV2Diagnosis>(
    () => api.earlyWarningV2Diagnose({ band, segment }),
    [band, segment],
  );

  if (diagnosis.loading) return <Skeleton className="h-40 w-full" />;
  if (diagnosis.error || !diagnosis.data) return null;

  const { population, total_exposure, drivers, note } = diagnosis.data;
  const largest = Math.max(...drivers.map((d) => d.borrower_count), 1);

  return (
    <Card>
      <CardHeader>
        <CardTitle>{label}: what this population has in common</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex flex-wrap gap-4 text-sm">
          <span>
            <span className="font-semibold text-text-primary">{population}</span>{" "}
            <span className="text-text-secondary">borrowers</span>
          </span>
          <span>
            <span className="font-semibold text-text-primary">{money(total_exposure)}</span>{" "}
            <span className="text-text-secondary">exposure</span>
          </span>
        </div>

        {drivers.length > 0 ? (
          <div className="space-y-1.5">
            <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-text-muted">
              Top common drivers
            </p>
            {drivers.map((driver) => (
              <div key={driver.signal} className="flex items-center gap-2 text-xs">
                <span className="w-40 shrink-0 truncate text-text-secondary">{driver.signal}</span>
                <span className="relative h-3 min-w-0 flex-1 overflow-hidden rounded-sm bg-surface-sunken">
                  <span
                    className="absolute inset-y-0 left-0 rounded-sm bg-accent/60"
                    style={{ width: `${(100 * driver.borrower_count) / largest}%` }}
                  />
                </span>
                <span className="w-8 shrink-0 text-right tabular text-text-muted">
                  {driver.borrower_count}
                </span>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-xs text-text-muted">No population to describe.</p>
        )}

        <p className="text-[11px] leading-relaxed text-text-muted">{note}</p>
      </CardContent>
    </Card>
  );
}
