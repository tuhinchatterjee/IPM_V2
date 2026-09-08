"use client";

import * as React from "react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { api, type EarlyWarningV2Level } from "@/lib/api";
import { moneyCell, MONEY_COLUMN_UNIT } from "@/lib/early-warning-format";
import { useAsync } from "@/lib/hooks";
import { CategoryBarChart } from "@/components/analytics/charts";

const BAND_VARIANT: Record<string, "negative" | "warning" | "info" | "positive" | "default"> = {
  VERY_HIGH: "negative",
  HIGH: "warning",
  MEDIUM: "info",
  LOW: "default",
  VERY_LOW: "positive",
};

/**
 * The book at whatever level the reader chose.
 *
 * The grouping is not fixed to segment. Any attribute that partitions the
 * book — grade, stage, region, relationship manager, utilisation band, the
 * layer where risk is being detected — can become the level, and the same
 * screen re-renders at it. A separate screen per grouping is how a product
 * ends up with five tables that disagree.
 *
 * The grade level carries its own warning, because grade and early warning
 * are not supposed to track each other and a reader who expects them to will
 * read the divergence as an error rather than as the alert it is.
 */
export function LevelView({
  field,
  onChangeField,
  onOpenGroup,
}: {
  field: string;
  onChangeField: (field: string) => void;
  onOpenGroup?: (field: string, value: string) => void;
}) {
  const levels = useAsync(() => api.earlyWarningV2Levels(), []);
  const data = useAsync<EarlyWarningV2Level>(
    () => api.earlyWarningV2Level(field),
    [field],
  );

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between gap-3">
        <CardTitle>{data.data?.label ?? "By level"}</CardTitle>
        <select
          value={field}
          onChange={(e) => onChangeField(e.target.value)}
          aria-label="Group the book by"
          className="rounded-md border border-border bg-surface px-2 py-1 text-xs text-text-secondary"
        >
          {(levels.data?.levels ?? []).map((l) => (
            <option key={l.field} value={l.field}>
              {l.label}
            </option>
          ))}
        </select>
      </CardHeader>
      <CardContent className="space-y-3">
        {data.loading && <Skeleton className="h-48 w-full" />}
        {data.error && <p className="text-sm text-negative">{data.error}</p>}
        {data.data && (
          <>
            <p className="text-sm leading-relaxed text-text-primary">
              {data.data.reading.direct}
            </p>
            {data.data.reading.interpretation && (
              <p className="text-sm leading-relaxed text-text-secondary">
                {data.data.reading.interpretation}
              </p>
            )}

            {data.data.rows.length >= 2 && (
              <CategoryBarChart
                data={data.data.rows.slice(0, 12).map((r) => ({
                  label: String(r[data.data!.level] ?? ""),
                  ews: r.portfolio_ews,
                }))}
                xKey="label"
                series={[{ key: "ews", label: "Portfolio EWS", slot: 0 }]}
                height={Math.max(180, data.data.rows.slice(0, 12).length * 26)}
              />
            )}

            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border text-left text-text-secondary">
                    <th className="py-1.5 pr-3">{data.data.label}</th>
                    <th className="py-1.5 pr-3">Obligors</th>
                    <th className="py-1.5 pr-3">Exposure ({MONEY_COLUMN_UNIT})</th>
                    <th className="py-1.5 pr-3">EWS</th>
                    <th className="py-1.5 pr-3">Severity</th>
                    <th className="py-1.5 pr-3">High+</th>
                    <th className="py-1.5 pr-3">Weakest obligor</th>
                  </tr>
                </thead>
                <tbody>
                  {data.data.rows.map((row) => {
                    const value = String(row[data.data!.level] ?? "");
                    return (
                      <tr
                        key={value}
                        className={
                          onOpenGroup
                            ? "cursor-pointer border-b border-border/60 hover:bg-surface-hover"
                            : "border-b border-border/60"
                        }
                        onClick={
                          onOpenGroup
                            ? () => onOpenGroup(data.data!.level, value)
                            : undefined
                        }
                      >
                        <td className="py-1.5 pr-3 font-medium">{value}</td>
                        <td className="py-1.5 pr-3">{row.obligors}</td>
                        <td className="py-1.5 pr-3">{moneyCell(row.exposure)}</td>
                        <td className="py-1.5 pr-3">{row.portfolio_ews.toFixed(1)}</td>
                        <td className="py-1.5 pr-3">
                          <Badge variant={BAND_VARIANT[row.band] ?? "default"}>
                            {row.band.replace("_", " ").toLowerCase()}
                          </Badge>
                        </td>
                        <td className="py-1.5 pr-3">{row.high_plus_count}</td>
                        <td className="py-1.5 pr-3 text-text-secondary">
                          {row.weakest_obligor}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            {data.data.caveats.length > 0 && (
              <p className="text-[11px] leading-relaxed text-text-muted">
                {data.data.caveats.join(" ")}
              </p>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}
