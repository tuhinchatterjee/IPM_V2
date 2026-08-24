"use client";

import * as React from "react";
import { Database, GitCompare } from "lucide-react";

import { BackLink } from "@/components/layout/back-link";
import { DataGrid } from "@/components/data-builder/data-grid";
import { SchemaComparison } from "@/components/data-builder/schema-comparison";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { InfoPopover } from "@/components/ui/info-popover";
import { Skeleton } from "@/components/ui/skeleton";
import { api, type DatasetTree } from "@/lib/api";
import { useAsync } from "@/lib/hooks";
import { cn } from "@/lib/utils";

/**
 * The dataset viewer.
 *
 * Navigate the way somebody actually thinks about their data — domain, then
 * family, then dataset — and read the rows in a grid that behaves like the ones
 * people already work in: a header that stays put, key columns that do not
 * scroll away, sorting, filtering, searching, column profiles and an export of
 * exactly what is on screen.
 *
 * Nothing here is a query surface, and nothing here is loaded whole. Every
 * page, sort, filter and search is a request against the governed catalogue;
 * the dataset name is resolved there, every column shown is one the dictionary
 * knows about, and the comparison a filter makes is one of a fixed set. The
 * backend refuses anything else and says which part it refused.
 */
export default function BrowseDataPage() {
  const tree = useAsync(() => api.datasetTree(), []);
  const [dataset, setDataset] = React.useState<string | null>(null);
  const [comparing, setComparing] = React.useState(false);

  /** The selected dataset, with the domain it sits under. */
  const chosen = findDataset(tree.data?.domains ?? [], dataset);

  return (
    <div className="space-y-5">
      <BackLink href="/data-builder" label="Data Builder" />

      <header className="flex flex-wrap items-center gap-2">
        <h1 className="text-[24px] font-semibold leading-tight tracking-tight text-text-primary">
          Browse the data
        </h1>
        <InfoPopover title="What you are looking at">
          <p>
            Governed rows, read through the same Data Access Layer every
            certified analysis uses. The definition of each column is the one in
            the data dictionary.
          </p>
          <p>
            This is a viewer, not a query surface. Columns, sorting and filters
            are restricted to the governed dictionary — a column name cannot
            become a query, and a filter value is compared rather than executed.
          </p>
          <p>
            Rows are paged on the server. A dataset of fifteen thousand rows is
            never handed to the browser.
          </p>
        </InfoPopover>
      </header>

      <div className="grid gap-6 lg:grid-cols-[228px_1fr]">
        <nav className="space-y-4">
          {tree.loading && <Skeleton className="h-64 w-full" />}
          {tree.error && <p className="text-xs text-negative">{tree.error}</p>}
          {tree.data?.domains.map((domain) => (
            <div key={domain.domain}>
              <p className="meta mb-1.5 text-text-muted">{domain.domain}</p>
              {domain.families.map((family) => (
                <div key={family.family} className="mb-2">
                  {family.datasets.map((entry) => (
                    <button
                      key={entry.name}
                      type="button"
                      disabled={!entry.readable}
                      onClick={() => {
                        setDataset(entry.name);
                        setComparing(false);
                      }}
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

        <div className="min-w-0 space-y-3">
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

          {dataset && (
            <>
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="text-sm font-semibold text-text-primary">
                  {chosen?.business_name || dataset}
                </h2>
                {chosen?.domain && <Badge variant="outline">{chosen.domain}</Badge>}
                {chosen?.is_synthetic && <Badge variant="warning">Demo data</Badge>}
                <Button
                  variant={comparing ? "outline" : "ghost"}
                  size="sm"
                  className="ml-auto"
                  onClick={() => setComparing((c) => !c)}
                >
                  <GitCompare aria-hidden />
                  Compare periods
                </Button>
              </div>

              {comparing && <SchemaComparison dataset={dataset} />}
              <DataGrid dataset={dataset} />
            </>
          )}
        </div>
      </div>
    </div>
  );
}

type TreeDomain = DatasetTree["domains"][number];

/** Walk the tree for one dataset, carrying its domain out with it. */
function findDataset(domains: TreeDomain[], name: string | null) {
  if (!name) return null;
  for (const domain of domains) {
    for (const family of domain.families) {
      for (const entry of family.datasets) {
        if (entry.name === name) return { ...entry, domain: domain.domain };
      }
    }
  }
  return null;
}
