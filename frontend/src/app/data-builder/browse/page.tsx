"use client";

import Link from "next/link";
import * as React from "react";
import {
  ArrowLeft,
  ChevronLeft,
  ChevronRight,
  Database,
  Lock,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { InfoPopover } from "@/components/ui/info-popover";
import { Skeleton } from "@/components/ui/skeleton";
import { api, type DatasetPage } from "@/lib/api";
import { useAsync } from "@/lib/hooks";
import { cn } from "@/lib/utils";

const PAGE_SIZE = 50;

/**
 * The dataset viewer.
 *
 * Navigate the way somebody actually thinks about their data — domain, then
 * family, then dataset, then period — and read the rows, with the governed
 * definition of every column beside it.
 *
 * Nothing here is a query surface. The dataset name is resolved against the
 * catalogue, every column shown is one the dictionary knows about, and the sort
 * column must be one of them; the backend refuses anything else and says so.
 * That is what makes this a viewer rather than a way around the governance the
 * rest of the product depends on.
 */
export default function BrowseDataPage() {
  const tree = useAsync(() => api.datasetTree(), []);
  const [dataset, setDataset] = React.useState<string | null>(null);
  const [period, setPeriod] = React.useState<string | null>(null);
  const [offset, setOffset] = React.useState(0);
  const [sort, setSort] = React.useState<string | null>(null);
  const [descending, setDescending] = React.useState(false);

  const page = useAsync(
    () =>
      api.datasetRows(dataset!, {
        period: period ?? undefined,
        offset,
        limit: PAGE_SIZE,
        sort: sort ?? undefined,
        descending,
      }),
    [dataset, period, offset, sort, descending],
    { enabled: Boolean(dataset) },
  );

  function choose(name: string) {
    setDataset(name);
    setPeriod(null);
    setOffset(0);
    setSort(null);
  }

  return (
    <div className="space-y-6">
      <Button variant="ghost" size="sm" asChild className="-ml-2">
        <Link href="/data-builder">
          <ArrowLeft aria-hidden />
          Data Builder
        </Link>
      </Button>

      <header>
        <p className="text-[10px] font-medium uppercase tracking-[0.16em] text-text-muted">
          Data Builder
        </p>
        <div className="mt-1.5 flex flex-wrap items-center gap-2">
          <h1 className="text-[24px] font-semibold leading-tight tracking-tight text-text-primary">
            Browse the data
          </h1>
          <InfoPopover title="What you are looking at">
            <p>
              Governed rows, read through the same Data Access Layer every
              certified analysis uses. The definition of each column is the one
              in the data dictionary.
            </p>
            <p>
              This is a viewer, not a query surface. Columns and sorting are
              restricted to the governed dictionary — a column name cannot become
              a query.
            </p>
          </InfoPopover>
        </div>
      </header>

      <div className="grid gap-6 lg:grid-cols-[240px_1fr]">
        <nav className="space-y-4">
          {tree.loading && <Skeleton className="h-64 w-full" />}
          {tree.error && <p className="text-xs text-negative">{tree.error}</p>}
          {tree.data?.domains.map((domain) => (
            <div key={domain.domain}>
              <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-text-muted">
                {domain.domain}
              </p>
              {domain.families.map((family) => (
                <div key={family.family} className="mb-2">
                  {family.datasets.map((entry) => (
                    <button
                      key={entry.name}
                      type="button"
                      disabled={!entry.readable}
                      onClick={() => choose(entry.name)}
                      className={cn(
                        "flex w-full items-start gap-2 rounded-md px-2 py-1.5 text-left text-[13px] transition-colors",
                        dataset === entry.name
                          ? "bg-accent-muted text-accent"
                          : "text-text-secondary hover:bg-surface-hover",
                        !entry.readable && "opacity-40",
                      )}
                      title={entry.purpose}
                    >
                      <Database className="mt-0.5 size-3.5 shrink-0" aria-hidden />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate">
                          {entry.business_name || entry.name}
                        </span>
                        <span className="block text-[10px] text-text-muted">
                          {entry.period_count > 0
                            ? `${entry.period_count} periods`
                            : "no periods"}{" "}
                          · {entry.field_count} fields
                        </span>
                      </span>
                    </button>
                  ))}
                </div>
              ))}
            </div>
          ))}
        </nav>

        <div className="min-w-0">
          {!dataset && (
            <Card className="px-5 py-12 text-center">
              <p className="text-sm text-text-secondary">
                Choose a dataset to read.
              </p>
              <p className="mx-auto mt-1 max-w-md text-xs leading-relaxed text-text-muted">
                Datasets are grouped by domain and family, which is how they are
                governed and how the engine resolves them.
              </p>
            </Card>
          )}

          {dataset && page.loading && <Skeleton className="h-96 w-full" />}
          {dataset && page.error && (
            <Card className="border-negative/40 p-4 text-sm text-negative">
              {page.error}
            </Card>
          )}
          {dataset && page.data && (
            <DatasetView
              page={page.data}
              period={period}
              onPeriod={(p) => {
                setPeriod(p);
                setOffset(0);
              }}
              onSort={(column) => {
                if (sort === column) {
                  setDescending((d) => !d);
                } else {
                  setSort(column);
                  setDescending(true);
                }
                setOffset(0);
              }}
              sort={sort}
              descending={descending}
              onOffset={setOffset}
            />
          )}
        </div>
      </div>
    </div>
  );
}

function DatasetView({
  page,
  period,
  onPeriod,
  onSort,
  sort,
  descending,
  onOffset,
}: {
  page: DatasetPage;
  period: string | null;
  onPeriod: (period: string) => void;
  onSort: (column: string) => void;
  sort: string | null;
  descending: boolean;
  onOffset: (offset: number) => void;
}) {
  const from = page.total_rows === 0 ? 0 : page.offset + 1;
  const to = page.offset + page.returned;

  return (
    <div className="space-y-4">
      <div>
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-sm font-semibold text-text-primary">
            {page.business_name || page.dataset}
          </h2>
          <Badge variant="outline">{page.domain}</Badge>
          {page.is_synthetic && <Badge variant="warning">Demo data</Badge>}
        </div>
        <p className="mt-1 text-xs text-text-muted">{page.grain}</p>
      </div>

      {page.periods.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {page.periods.map((p) => (
            <button
              key={p}
              type="button"
              onClick={() => onPeriod(p)}
              className={cn(
                "rounded-full border px-2.5 py-0.5 text-[11px] transition-colors",
                (period ?? page.period) === p
                  ? "border-accent bg-accent-muted text-accent"
                  : "border-border bg-surface text-text-muted hover:border-accent",
              )}
            >
              {p}
            </button>
          ))}
        </div>
      )}

      <Card className="overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full min-w-max text-xs">
            <thead>
              <tr className="border-b border-border bg-surface-sunken">
                {page.fields.map((field) => (
                  <th
                    key={field.name}
                    className="whitespace-nowrap px-3 py-2 text-left font-medium"
                  >
                    <button
                      type="button"
                      onClick={() => onSort(field.name)}
                      title={`${field.definition}${field.unit ? ` (${field.unit})` : ""}`}
                      className={cn(
                        "inline-flex items-center gap-1 transition-colors hover:text-accent",
                        sort === field.name ? "text-accent" : "text-text-secondary",
                      )}
                    >
                      {field.business_name || field.name}
                      {field.sensitivity === "confidential" && (
                        <Lock className="size-2.5" aria-hidden />
                      )}
                      {sort === field.name && (
                        <span aria-hidden>{descending ? "↓" : "↑"}</span>
                      )}
                    </button>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {page.rows.map((row, i) => (
                <tr
                  key={i}
                  className="border-b border-border last:border-0 hover:bg-surface-hover"
                >
                  {page.fields.map((field) => (
                    <td
                      key={field.name}
                      className={cn(
                        "whitespace-nowrap px-3 py-1.5",
                        typeof row[field.name] === "number"
                          ? "tabular text-right text-text-primary"
                          : "text-text-secondary",
                      )}
                    >
                      {row[field.name] === null || row[field.name] === undefined
                        ? "—"
                        : String(row[field.name])}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-xs text-text-muted">
          {from.toLocaleString()}–{to.toLocaleString()} of{" "}
          {page.total_rows.toLocaleString()} rows in {page.period ?? "the dataset"}
        </p>
        <div className="flex items-center gap-1">
          <Button
            variant="outline"
            size="sm"
            disabled={page.offset === 0}
            onClick={() => onOffset(Math.max(0, page.offset - PAGE_SIZE))}
          >
            <ChevronLeft aria-hidden />
            Previous
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={to >= page.total_rows}
            onClick={() => onOffset(page.offset + PAGE_SIZE)}
          >
            Next
            <ChevronRight aria-hidden />
          </Button>
        </div>
      </div>
    </div>
  );
}
