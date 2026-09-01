"use client";

import * as React from "react";
import { Check, Minus, TriangleAlert } from "lucide-react";

import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import { useAsync } from "@/lib/hooks";
import { cn } from "@/lib/utils";

/**
 * Which columns each published period actually carries.
 *
 * A dataset's schema is not fixed once it is loaded period by period: a field
 * appears when a source system starts sending it and disappears when it stops.
 * Somebody comparing Q1 with Q4 needs to know that before they conclude the
 * book moved — a metric that goes to zero because its input stopped arriving
 * looks exactly like a metric that went to zero.
 *
 * "Present" means the column exists and is not entirely empty. A column of
 * nothing but nulls is, for the purpose of comparing periods, absent, and
 * saying so is more useful than reporting it as there.
 */
export function SchemaComparison({ dataset }: { dataset: string }) {
  const history = useAsync(() => api.datasetSchemaHistory(dataset), [dataset]);

  if (history.loading) return <Skeleton className="h-64 w-full" />;
  if (history.error) {
    return (
      <Card className="border-negative/40 p-4 text-sm text-negative">
        {history.error}
      </Card>
    );
  }
  if (!history.data) return null;

  const { periods, fields, presence, changes, stable } = history.data;

  return (
    <Card className="overflow-hidden">
      <div
        className={cn(
          "flex items-start gap-2 border-b border-border px-4 py-2.5",
          stable ? "bg-surface-sunken" : "bg-warning-muted",
        )}
      >
        {stable ? (
          <Check className="mt-0.5 size-3.5 shrink-0 text-positive" aria-hidden />
        ) : (
          <TriangleAlert
            className="mt-0.5 size-3.5 shrink-0 text-warning"
            aria-hidden
          />
        )}
        <div className="min-w-0">
          <p
            className={cn(
              "text-xs font-medium",
              stable ? "text-text-primary" : "text-warning",
            )}
          >
            {stable
              ? `The same ${fields.length} columns are present in all ${periods.length} periods.`
              : `${changes.length} column${changes.length === 1 ? "" : "s"} changed across periods.`}
          </p>
          {!stable && (
            <ul className="mt-1 space-y-0.5">
              {changes.slice(0, 6).map((change, i) => (
                <li key={i} className="text-[11px] text-warning">
                  <span className="mono">{change.field}</span> {change.change} in{" "}
                  {change.period} (it was {change.change === "appeared" ? "absent" : "present"}{" "}
                  in {change.from_period}).
                </li>
              ))}
              {changes.length > 6 && (
                <li className="text-[11px] text-text-muted">
                  and {changes.length - 6} more.
                </li>
              )}
            </ul>
          )}
        </div>
      </div>

      <div className="max-h-[40vh] overflow-auto">
        <table className="w-full border-separate border-spacing-0 text-xs">
          <thead>
            <tr>
              <th className="sticky left-0 top-0 z-30 border-b border-r border-border bg-surface-sunken px-3 py-1.5 text-left font-medium text-text-secondary">
                Column
              </th>
              {periods.map((period) => (
                <th
                  key={period}
                  className="mono sticky top-0 z-20 whitespace-nowrap border-b border-r border-border bg-surface-sunken px-2 py-1.5 text-center text-[10px] font-normal text-text-muted"
                >
                  {period}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {fields.map((field) => {
              const everywhere = periods.every((p) => presence[p]?.fields[field]);
              return (
                <tr key={field} className="group">
                  <td
                    className={cn(
                      "sticky left-0 z-10 truncate border-b border-r border-border bg-surface px-3 py-1 group-hover:bg-surface-hover",
                      everywhere ? "text-text-secondary" : "text-warning",
                    )}
                  >
                    {field}
                  </td>
                  {periods.map((period) => (
                    <td
                      key={period}
                      className="border-b border-r border-border px-2 py-1 text-center group-hover:bg-surface-hover"
                      title={`${presence[period]?.rows.toLocaleString() ?? 0} rows in ${period}`}
                    >
                      {presence[period]?.fields[field] ? (
                        <Check
                          className="mx-auto size-3 text-positive"
                          aria-label="present"
                        />
                      ) : (
                        <Minus
                          className="mx-auto size-3 text-text-muted"
                          aria-label="absent"
                        />
                      )}
                    </td>
                  ))}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
