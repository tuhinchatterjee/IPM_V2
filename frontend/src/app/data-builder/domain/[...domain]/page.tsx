"use client";

import Link from "next/link";
import * as React from "react";
import { Database, Plus } from "lucide-react";

import { LifecycleBadge } from "@/app/data-builder/page";
import { ResultTable } from "@/components/analytics/primitives";
import { PageHeader } from "@/components/layout/page-header";
import { useCanEditData } from "@/components/system/role-switcher";
import { Badge } from "@/components/ui/badge";
import { BackLink } from "@/components/layout/back-link";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Tabs } from "@/components/ui/tabs";
import { api, type DatasetDetail } from "@/lib/api";
import { useAsync } from "@/lib/hooks";

/**
 * Domain detail.
 *
 * Six tabs, matching how a data office reviews a domain: what it is, what is in
 * it, what the fields mean, how the datasets join, whether the data is sound,
 * and what has been published.
 *
 * Bundled datasets (built by the data-lake script) appear alongside onboarded
 * ones, because from the engine's point of view they are equally governed.
 */
/**
 * A catch-all segment, because domain names contain slashes.
 *
 * "Core Portfolio / Facility" is a real domain name. Percent-encoding the
 * slash does not help — the router decodes it before matching, so a single
 * dynamic segment 404s on exactly the domains the product ships with. Catching
 * the remaining segments and joining them back is what makes those names work.
 */
export default function DomainPage({
  params,
}: {
  params: Promise<{ domain: string[] }>;
}) {
  const { domain: segments } = React.use(params);
  const domain = segments.map(decodeURIComponent).join("/");
  const canEdit = useCanEditData();
  const [tab, setTab] = React.useState("overview");

  const datasets = useAsync(() => api.datasets({ domain }), [domain]);
  const catalog = useAsync(() => api.catalog(), []);
  const relationships = useAsync(() => api.relationships(), []);

  const owned = datasets.data?.datasets ?? [];
  const catalogued = (catalog.data?.datasets ?? []).filter((d) => d.domain === domain);

  // Full detail for each onboarded dataset — needed by the dictionary, quality
  // and versions tabs. Keyed on the dataset names so it refetches when the list
  // changes and not on every render. A dataset that fails to load is skipped
  // rather than failing the whole page.
  const ownedNames = owned.map((d) => d.name).join(",");
  const detailsState = useAsync<DatasetDetail[]>(
    async () => {
      if (!ownedNames) return [];
      const results = await Promise.all(
        ownedNames.split(",").map((n) => api.dataset(n).catch(() => null)),
      );
      return results.filter(Boolean) as DatasetDetail[];
    },
    [ownedNames],
  );
  const details = React.useMemo(() => detailsState.data ?? [], [detailsState.data]);

  const dictionaryRows = React.useMemo(() => {
    const rows: Record<string, string | number | null>[] = [];
    for (const d of details) {
      for (const f of d.fields) {
        rows.push({
          dataset: d.name,
          field: f.name,
          business_name: f.business_name,
          type: f.data_type,
          unit: f.unit ?? "—",
          sensitivity: f.sensitivity,
          definition: f.definition,
        });
      }
    }
    // Bundled datasets carry their dictionary in the governed catalogue.
    for (const d of catalogued) {
      if (details.some((x) => x.name === d.name)) continue;
      rows.push({
        dataset: d.name,
        field: `${d.field_count} governed fields`,
        business_name: d.business_name,
        type: "—",
        unit: "—",
        sensitivity: "—",
        definition: d.grain,
      });
    }
    return rows;
  }, [details, catalogued]);

  const domainRelationships = (relationships.data?.relationships ?? []).filter(
    (r) =>
      owned.some((d) => d.name === r.from_dataset || d.name === r.to_dataset) ||
      catalogued.some((d) => d.name === r.from_dataset || d.name === r.to_dataset),
  );

  const allFindings = details.flatMap((d) =>
    (d.lifecycle === "published" ? [] : []).concat([]),
  );

  const versions = details.filter((d) => d.published_version);

  /** One shape for the overview list, whichever source a dataset came from. */
  const overview = [
    ...owned.map((d) => ({
      name: d.name,
      title: d.business_name || d.name,
      grain: d.grain || "No grain recorded.",
    })),
    ...catalogued
      .filter((c) => !owned.some((o) => o.name === c.name))
      .map((d) => ({ name: d.name, title: d.business_name, grain: d.grain })),
  ];

  return (
    <div className="space-y-6">
      <BackLink href="/data-builder" label="Data Builder" />

      <PageHeader
        title={domain}
        description={`${owned.length + catalogued.filter((c) => !owned.some((o) => o.name === c.name)).length} dataset(s) in this domain.`}
        status="live"
        actions={
          canEdit ? (
            <Button asChild size="sm">
              <Link href={`/data-builder/new?domain=${encodeURIComponent(domain)}`}>
                <Plus aria-hidden />
                Add Dataset
              </Link>
            </Button>
          ) : undefined
        }
      />

      <Tabs
        active={tab}
        onChange={setTab}
        tabs={[
          { id: "overview", label: "Overview" },
          { id: "datasets", label: "Datasets", count: owned.length + catalogued.length },
          { id: "dictionary", label: "Dictionary", count: dictionaryRows.length },
          { id: "relationships", label: "Relationships", count: domainRelationships.length },
          { id: "quality", label: "Quality" },
          { id: "versions", label: "Versions", count: versions.length },
        ]}
      />

      {datasets.loading && <Skeleton className="h-48 w-full" />}

      {!datasets.loading && tab === "overview" && (
        <div className="grid gap-4 md:grid-cols-3">
          <Card className="p-5 md:col-span-2">
            <h3 className="mb-3 text-sm font-semibold text-text-primary">What this domain holds</h3>
            <ul className="space-y-2">
              {overview.map((d) => (
                <li key={d.name} className="flex items-start gap-3 text-sm">
                  <Database className="mt-0.5 size-4 shrink-0 text-text-muted" aria-hidden />
                  <div className="min-w-0">
                    <p className="font-medium text-text-primary">{d.title}</p>
                    <p className="text-xs text-text-muted">{d.grain}</p>
                  </div>
                </li>
              ))}
              {overview.length === 0 && (
                <li className="text-sm text-text-muted">No datasets yet.</li>
              )}
            </ul>
          </Card>
          <Card className="p-5">
            <h3 className="mb-3 text-sm font-semibold text-text-primary">Position</h3>
            <dl className="space-y-2 text-sm">
              <Line label="Onboarded here" value={String(owned.length)} />
              <Line
                label="Published"
                value={String(owned.filter((d) => d.lifecycle === "published").length)}
              />
              <Line label="Bundled" value={String(catalogued.length)} />
              <Line label="Governed fields" value={String(dictionaryRows.length)} />
              <Line label="Relationships" value={String(domainRelationships.length)} />
            </dl>
          </Card>
        </div>
      )}

      {!datasets.loading && tab === "datasets" && (
        <Card>
          {owned.length === 0 && catalogued.length === 0 ? (
            <EmptyState
              icon={Database}
              title="No datasets in this domain"
              description="Bring a source file in through the Add Dataset workflow."
              className="border-0"
            />
          ) : (
            <Table>
              <TableHeader>
                <TableRow className="hover:bg-transparent">
                  <TableHead>Dataset</TableHead>
                  <TableHead>Grain</TableHead>
                  <TableHead>Owner</TableHead>
                  <TableHead numeric>Fields</TableHead>
                  <TableHead>Lifecycle</TableHead>
                  <TableHead>Source</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {owned.map((d) => (
                  <TableRow key={d.name}>
                    <TableCell className="font-medium text-text-primary">
                      {d.business_name || d.name}
                      <span className="ml-2 font-mono text-xs text-text-muted">{d.name}</span>
                    </TableCell>
                    <TableCell className="max-w-xs truncate text-xs">{d.grain || "—"}</TableCell>
                    <TableCell className="text-xs">{d.owner || "—"}</TableCell>
                    <TableCell numeric>{d.field_count}</TableCell>
                    <TableCell>
                      <LifecycleBadge lifecycle={d.lifecycle} />
                    </TableCell>
                    <TableCell className="text-xs">{d.source_type}</TableCell>
                    <TableCell>
                      <Button variant="ghost" size="sm" asChild>
                        <Link href={`/data-builder/dataset/${d.name}`}>Open</Link>
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
                {catalogued
                  .filter((c) => !owned.some((o) => o.name === c.name))
                  .map((d) => (
                    <TableRow key={d.name}>
                      <TableCell className="font-medium text-text-primary">
                        {d.business_name}
                        <span className="ml-2 font-mono text-xs text-text-muted">{d.name}</span>
                      </TableCell>
                      <TableCell className="max-w-xs truncate text-xs">{d.grain}</TableCell>
                      <TableCell className="text-xs">Credit Risk Analytics</TableCell>
                      <TableCell numeric>{d.field_count}</TableCell>
                      <TableCell>
                        <Badge variant="positive">published</Badge>
                      </TableCell>
                      <TableCell className="text-xs">bundled</TableCell>
                      <TableCell>
                        {d.is_synthetic && <Badge variant="warning">synthetic</Badge>}
                      </TableCell>
                    </TableRow>
                  ))}
              </TableBody>
            </Table>
          )}
        </Card>
      )}

      {!datasets.loading && tab === "dictionary" && (
        <Card>
          <ResultTable
            rows={dictionaryRows}
            columns={["dataset", "field", "business_name", "type", "unit", "sensitivity", "definition"]}
            emptyMessage="No dictionary entries in this domain yet."
            renderCell={(column, value) =>
              column === "definition" ? (
                <span className="block max-w-lg text-xs text-text-muted">{String(value)}</span>
              ) : undefined
            }
          />
        </Card>
      )}

      {!datasets.loading && tab === "relationships" && (
        <Card>
          {domainRelationships.length === 0 ? (
            <EmptyState
              title="No relationships defined"
              description="A relationship records a governed join, for example portfolio_facility.account_id to an ECL extract's account_id. Define one in the Add Dataset workflow."
              className="border-0"
            />
          ) : (
            <Table>
              <TableHeader>
                <TableRow className="hover:bg-transparent">
                  <TableHead>From</TableHead>
                  <TableHead>To</TableHead>
                  <TableHead>Cardinality</TableHead>
                  <TableHead>Kind</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {domainRelationships.map((r) => (
                  <TableRow key={`${r.from_dataset}.${r.from_field}-${r.to_dataset}.${r.to_field}`}>
                    <TableCell className="font-mono text-xs">
                      {r.from_dataset}.{r.from_field}
                    </TableCell>
                    <TableCell className="font-mono text-xs">
                      {r.to_dataset}.{r.to_field}
                    </TableCell>
                    <TableCell className="text-xs">{r.cardinality}</TableCell>
                    <TableCell>
                      <Badge variant="outline">{r.kind}</Badge>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </Card>
      )}

      {!datasets.loading && tab === "quality" && (
        <div className="space-y-3">
          {details.length === 0 && allFindings.length === 0 && (
            <EmptyState
              title="No quality results yet"
              description="Quality checks run when a dataset is validated. Open a dataset and run Validate to see its findings."
            />
          )}
          {details.map((d) => (
            <Card key={d.name} className="p-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium text-text-primary">{d.name}</p>
                  <p className="text-xs text-text-muted">
                    {d.field_count} governed fields · {d.primary_keys.join(", ") || "no key declared"}
                  </p>
                </div>
                <LifecycleBadge lifecycle={d.lifecycle} />
              </div>
              <Button variant="outline" size="sm" asChild className="mt-3">
                <Link href={`/data-builder/dataset/${d.name}`}>Open and validate</Link>
              </Button>
            </Card>
          ))}
        </div>
      )}

      {!datasets.loading && tab === "versions" && (
        <Card>
          {versions.length === 0 ? (
            <EmptyState
              title="Nothing published from this domain yet"
              description="Publishing a dataset records an immutable version with its row counts, periods and quality report."
              className="border-0"
            />
          ) : (
            <Table>
              <TableHeader>
                <TableRow className="hover:bg-transparent">
                  <TableHead>Dataset</TableHead>
                  <TableHead numeric>Version</TableHead>
                  <TableHead>Published</TableHead>
                  <TableHead numeric>Fields</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {versions.map((d) => (
                  <TableRow key={d.name}>
                    <TableCell className="font-medium text-text-primary">{d.name}</TableCell>
                    <TableCell numeric>v{d.published_version}</TableCell>
                    <TableCell className="text-xs">
                      {d.published_at?.slice(0, 19).replace("T", " ") ?? "—"}
                    </TableCell>
                    <TableCell numeric>{d.field_count}</TableCell>
                    <TableCell>
                      <Button variant="ghost" size="sm" asChild>
                        <Link href={`/data-builder/dataset/${d.name}`}>History</Link>
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </Card>
      )}
    </div>
  );
}

function Line({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between">
      <dt className="text-xs text-text-muted">{label}</dt>
      <dd className="font-medium text-text-primary tabular">{value}</dd>
    </div>
  );
}
