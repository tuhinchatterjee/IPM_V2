"use client";

/**
 * A governed chart frame: title, unit and period context, the Plotly chart,
 * and -- always -- its exact data.
 *
 * "View data" shows the rows the chart was drawn from (the same array, not a
 * recomputation), and "CSV" downloads those rows with the release,
 * fingerprint, period, active filters and trace reference as header lines.
 * PNG/SVG come from Plotly itself. So a chart download and its tabular
 * download reconcile by construction (PV-07), and a reader who cannot read
 * the chart -- or does not trust it -- always has the numbers (VIZ06).
 */

import * as React from "react";
import { Download, Table2 } from "lucide-react";

import { PlotlyChart, type PlotHandle, type PlotlyChartProps } from "@/components/viz/plotly-chart";
import { cn } from "@/lib/utils";

export interface DataColumn {
  key: string;
  label: string;
  /** Display function for the cell; the CSV always carries the raw value. */
  format?: (value: unknown) => string;
  align?: "left" | "right";
}

export interface ChartData {
  columns: DataColumn[];
  rows: Record<string, unknown>[];
  /** The keyboard (and click) equivalent of clicking the chart mark a row
   * was drawn as: Enter or Space on a focused row does what the click does. */
  onRowActivate?: (row: Record<string, unknown>) => void;
  /** Accessible description of what activating a row does. */
  activateLabel?: string;
}

export interface ChartContext {
  releaseId?: string;
  fingerprint?: string;
  period?: string;
  filters?: Record<string, unknown>;
  traceRef?: string;
  source?: string;
}

export function toCsv(table: ChartData, context: ChartContext = {}): string {
  const meta: string[] = [];
  if (context.source) meta.push(`# source: ${context.source}`);
  if (context.releaseId) meta.push(`# release: ${context.releaseId}`);
  if (context.fingerprint) meta.push(`# fingerprint: ${context.fingerprint}`);
  if (context.period) meta.push(`# period: ${context.period}`);
  if (context.filters && Object.keys(context.filters).length) {
    meta.push(`# filters: ${JSON.stringify(context.filters)}`);
  }
  if (context.traceRef) meta.push(`# trace: ${context.traceRef}`);
  meta.push("# values are raw governed values; money is SAR million unless a column says otherwise");
  const escape = (value: unknown) => {
    const text = value === null || value === undefined ? "" : String(value);
    const safe = /^[=+\-@]/.test(text) && Number.isNaN(Number(text)) ? `'${text}` : text;
    return /[",\n]/.test(safe) ? `"${safe.replace(/"/g, '""')}"` : safe;
  };
  const header = table.columns.map((c) => escape(c.label)).join(",");
  const body = table.rows.map((row) => table.columns.map((c) => escape(row[c.key])).join(","));
  return [...meta, header, ...body].join("\n") + "\n";
}

export function downloadText(text: string, filename: string, mime = "text/csv") {
  const blob = new Blob([text], { type: `${mime};charset=utf-8` });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export interface ChartCardProps extends Omit<PlotlyChartProps, "ariaLabel"> {
  title: string;
  subtitle?: string;
  table: ChartData;
  context?: ChartContext;
  actions?: React.ReactNode;
  footer?: React.ReactNode;
  defaultShowData?: boolean;
}

export function ChartCard({
  title,
  subtitle,
  table,
  context,
  actions,
  footer,
  defaultShowData = false,
  testId,
  filename,
  className,
  ...plot
}: ChartCardProps) {
  const [showData, setShowData] = React.useState(defaultShowData);
  const chart = React.useRef<PlotHandle | null>(null);
  const stem = filename ?? title.toLowerCase().replace(/[^a-z0-9]+/g, "-");
  return (
    <section
      className={cn("rounded-lg border border-border bg-surface p-4", className)}
      data-testid={testId ? `${testId}-card` : undefined}
      aria-label={title}
    >
      <header className="mb-2 flex flex-wrap items-start justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold text-text-primary">{title}</h3>
          {subtitle && <p className="text-xs text-text-muted">{subtitle}</p>}
        </div>
        <div className="flex flex-wrap items-center gap-1">
          {actions}
          <button
            type="button"
            onClick={() => setShowData((v) => !v)}
            className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 text-xs text-text-secondary hover:bg-surface-hover"
            aria-pressed={showData}
            data-testid={testId ? `${testId}-view-data` : undefined}
          >
            <Table2 className="h-3.5 w-3.5" /> {showData ? "Hide data" : "View data"}
          </button>
          <button
            type="button"
            onClick={() => downloadText(toCsv(table, context), `${stem}.csv`)}
            className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 text-xs text-text-secondary hover:bg-surface-hover"
            data-testid={testId ? `${testId}-csv` : undefined}
          >
            <Download className="h-3.5 w-3.5" /> CSV
          </button>
          <button
            type="button"
            onClick={() => chart.current?.download("png")}
            className="rounded-md border border-border px-2 py-1 text-xs text-text-secondary hover:bg-surface-hover"
          >
            PNG
          </button>
          <button
            type="button"
            onClick={() => chart.current?.download("svg")}
            className="rounded-md border border-border px-2 py-1 text-xs text-text-secondary hover:bg-surface-hover"
          >
            SVG
          </button>
        </div>
      </header>
      <PlotlyChart ref={chart} ariaLabel={`${title}. ${subtitle ?? ""}`} testId={testId} filename={stem} {...plot} />
      {showData && <DataTable table={table} testId={testId ? `${testId}-table` : undefined} />}
      {footer}
    </section>
  );
}

export function DataTable({ table, testId, maxRows = 200 }: { table: ChartData; testId?: string; maxRows?: number }) {
  return (
    <div className="mt-3 max-h-80 overflow-auto rounded-md border border-border" data-testid={testId}>
      <table className="w-full text-xs">
        <thead className="sticky top-0 bg-surface-sunken">
          <tr>
            {table.columns.map((c) => (
              <th
                key={c.key}
                className={cn("px-2 py-1.5 font-medium text-text-secondary", c.align === "right" ? "text-right" : "text-left")}
              >
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {table.rows.slice(0, maxRows).map((row, i) => (
            <tr
              key={i}
              className={cn("border-t border-border", table.onRowActivate && "cursor-pointer hover:bg-surface-hover focus:bg-accent-muted focus:outline-none")}
              tabIndex={table.onRowActivate ? 0 : undefined}
              aria-label={table.onRowActivate ? `${table.activateLabel ?? "Filter to"} ${String(row[table.columns[0]?.key] ?? "")}` : undefined}
              data-activatable={table.onRowActivate ? "true" : undefined}
              onClick={table.onRowActivate ? () => table.onRowActivate?.(row) : undefined}
              onKeyDown={
                table.onRowActivate
                  ? (e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        table.onRowActivate?.(row);
                      }
                    }
                  : undefined
              }
            >
              {table.columns.map((c) => (
                <td
                  key={c.key}
                  className={cn("px-2 py-1 tabular text-text-primary", c.align === "right" ? "text-right" : "text-left")}
                >
                  {c.format ? c.format(row[c.key]) : String(row[c.key] ?? "—")}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {table.rows.length > maxRows && (
        <p className="p-2 text-xs text-text-muted">
          Showing {maxRows} of {table.rows.length} rows; the CSV carries all of them.
        </p>
      )}
    </div>
  );
}
