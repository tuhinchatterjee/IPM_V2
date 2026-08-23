"use client";

import Link from "next/link";
import * as React from "react";
import {
  ArrowRight,
  CheckCircle2,
  CircleDashed,
  Database,
  Plus,
  ShieldCheck,
} from "lucide-react";

import { PageHeader } from "@/components/layout/page-header";
import { ReadOnlyNotice, useCanEditData } from "@/components/system/role-switcher";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty";
import { Skeleton } from "@/components/ui/skeleton";
import { api, type DatasetSummary, type Lifecycle } from "@/lib/api";
import { useAsync } from "@/lib/hooks";

/**
 * Data Builder landing.
 *
 * Domains first, because that is how a data office thinks about its estate: a
 * domain has an owner and a quality position, and datasets live inside it. Each
 * card reports what is actually in the database rather than a fixed list.
 *
 * The seven domains below are the standard IPM starting set. Any that do not yet
 * exist are shown as available to create rather than hidden, so the intended
 * shape of the estate is visible from the first screen.
 */

const STANDARD_DOMAINS = [
  {
    name: "Core Portfolio / Facility",
    description: "Facilities, limits, exposure, utilisation, collateral and staging.",
    owner: "Credit Risk Analytics",
  },
  {
    name: "IFRS 9 / ECL",
    description: "Staging, PD, LGD, EAD, expected credit loss, overlays and coverage.",
    owner: "Group Finance",
  },
  {
    name: "Corporate Ratings",
    description: "Internal grades, external ratings, notch gaps and rating history.",
    owner: "Credit Risk Analytics",
  },
  {
    name: "Retail / SME Scorecards",
    description: "Scorecard outputs and behavioural indicators for the retail book.",
    owner: "Retail Risk",
  },
  {
    name: "Documents",
    description: "Document metadata and the links between papers and the analysis inside them.",
    owner: "Group Data Office",
  },
  {
    name: "Policies / Knowledge",
    description: "Policy text, the limits framework and methodology notes.",
    owner: "Credit Policy",
  },
  {
    name: "IPM Operational Metadata",
    description: "Runs, traces, versions, usage and audit produced by IPM itself.",
    owner: "Risk Technology",
  },
];

export const LIFECYCLE_ORDER: Lifecycle[] = ["draft", "mapped", "validated", "published"];

export function LifecycleBadge({ lifecycle }: { lifecycle: Lifecycle }) {
  const variant =
    lifecycle === "published"
      ? "positive"
      : lifecycle === "validated"
        ? "accent"
        : lifecycle === "mapped"
          ? "info"
          : "default";
  return <Badge variant={variant}>{lifecycle}</Badge>;
}

export default function DataBuilderPage() {
  const canEdit = useCanEditData();
  const domains = useAsync(() => api.domains(), []);
  const datasets = useAsync(() => api.datasets(), []);
  const catalog = useAsync(() => api.catalog(), []);

  const byDomain = React.useMemo(() => {
    const map = new Map<string, DatasetSummary[]>();
    for (const d of datasets.data?.datasets ?? []) {
      map.set(d.domain, [...(map.get(d.domain) ?? []), d]);
    }
    return map;
  }, [datasets.data]);

  // The bundled datasets are in the governed catalogue but were built by the
  // data-lake script rather than onboarded here, so they have no Data Builder
  // record. Counting them keeps a domain's dataset count honest.
  const catalogueByDomain = React.useMemo(() => {
    const map = new Map<string, number>();
    for (const d of catalog.data?.datasets ?? []) {
      map.set(d.domain, (map.get(d.domain) ?? 0) + 1);
    }
    return map;
  }, [catalog.data]);

  const known = new Set(domains.data?.domains.map((d) => d.name) ?? []);
  const extra = (domains.data?.domains ?? []).filter(
    (d) => !STANDARD_DOMAINS.some((s) => s.name === d.name),
  );
  const cards = [
    ...STANDARD_DOMAINS.map((s) => ({
      ...s,
      exists: known.has(s.name),
      owner:
        domains.data?.domains.find((d) => d.name === s.name)?.owner || s.owner,
    })),
    ...extra.map((d) => ({
      name: d.name,
      description: d.description || "Created in Data Builder.",
      owner: d.owner || "—",
      exists: true,
    })),
  ];

  const loading = domains.loading || datasets.loading;
  const totalPublished = (datasets.data?.datasets ?? []).filter(
    (d) => d.lifecycle === "published",
  ).length;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Data Builder"
        description="Define what data exists and what it means. A steward brings a file in, maps it to governed fields, documents it, validates it and publishes it — at which point, and not before, the analytical engine can read it."
        status="live"
        actions={
          canEdit ? (
            <Button asChild>
              <Link href="/data-builder/new">
                <Plus aria-hidden />
                Add Dataset
              </Link>
            </Button>
          ) : undefined
        }
      />

      {!canEdit && <ReadOnlyNotice action="create, edit or publish datasets" />}

      {domains.error ? (
        <Card className="border-negative/40 p-4 text-sm text-negative">{domains.error}</Card>
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-3">
            <SummaryTile
              label="Domains defined"
              value={domains.data?.domains.length ?? 0}
              of={STANDARD_DOMAINS.length}
              loading={loading}
            />
            <SummaryTile
              label="Datasets published"
              value={totalPublished}
              of={datasets.data?.count ?? 0}
              loading={loading}
            />
            <SummaryTile
              label="Governed fields"
              value={catalog.data?.field_count ?? 0}
              loading={catalog.loading}
            />
          </div>

          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {loading
              ? [0, 1, 2, 3, 4, 5].map((i) => <Skeleton key={i} className="h-44 w-full" />)
              : cards.map((domain) => {
                  const owned = byDomain.get(domain.name) ?? [];
                  const catalogued = catalogueByDomain.get(domain.name) ?? 0;
                  const datasetCount = Math.max(owned.length, catalogued);
                  const published = owned.filter((d) => d.lifecycle === "published").length;
                  const lastRefresh = owned
                    .map((d) => d.published_at)
                    .filter(Boolean)
                    .sort()
                    .at(-1);
                  const qualityOk = owned.length === 0 || published === owned.length;

                  return (
                    <Link
                      key={domain.name}
                      href={`/data-builder/domain/${encodeURIComponent(domain.name)}`}
                      className="group"
                    >
                      <Card className="flex h-full flex-col p-5 transition-colors hover:bg-surface-hover">
                        <div className="mb-3 flex items-start justify-between gap-3">
                          <Database className="size-5 shrink-0 text-text-muted" aria-hidden />
                          {domain.exists ? (
                            <Badge variant={datasetCount ? "positive" : "default"}>
                              {datasetCount
                                ? `${datasetCount} dataset${datasetCount === 1 ? "" : "s"}`
                                : "Empty"}
                            </Badge>
                          ) : (
                            <Badge variant="outline">Not created</Badge>
                          )}
                        </div>

                        <h3 className="text-sm font-semibold text-text-primary">{domain.name}</h3>
                        <p className="mt-1.5 flex-1 text-xs leading-relaxed text-text-muted">
                          {domain.description}
                        </p>

                        <dl className="mt-4 space-y-1 border-t border-border pt-3 text-[11px]">
                          <Row label="Owner" value={domain.owner} />
                          <Row
                            label="Published"
                            value={
                              owned.length
                                ? `${published} of ${owned.length}`
                                : catalogued
                                  ? `${catalogued} bundled`
                                  : "—"
                            }
                          />
                          <Row
                            label="Latest refresh"
                            value={lastRefresh ? lastRefresh.slice(0, 10) : "—"}
                          />
                          <div className="flex items-center justify-between pt-0.5">
                            <dt className="text-text-muted">Quality</dt>
                            <dd className="flex items-center gap-1">
                              {qualityOk ? (
                                <>
                                  <CheckCircle2 className="size-3 text-positive" aria-hidden />
                                  <span className="text-positive">Passing</span>
                                </>
                              ) : (
                                <>
                                  <CircleDashed className="size-3 text-warning" aria-hidden />
                                  <span className="text-warning">In progress</span>
                                </>
                              )}
                            </dd>
                          </div>
                        </dl>

                        <span className="mt-3 inline-flex items-center gap-1 text-xs font-medium text-accent opacity-0 transition-opacity group-hover:opacity-100">
                          Open domain
                          <ArrowRight className="size-3" aria-hidden />
                        </span>
                      </Card>
                    </Link>
                  );
                })}
          </div>

          {datasets.data?.count === 0 && (
            <EmptyState
              icon={Database}
              title="No datasets onboarded yet"
              description="The bundled portfolio was built by the data-lake script and is already governed. Use Add Dataset to bring a new source file in through the full workflow."
              action={
                canEdit ? (
                  <Button asChild size="sm">
                    <Link href="/data-builder/new">
                      <Plus aria-hidden />
                      Add Dataset
                    </Link>
                  </Button>
                ) : undefined
              }
            />
          )}
        </>
      )}

      <Card className="p-5">
        <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-text-primary">
          <ShieldCheck className="size-4 text-text-muted" aria-hidden />
          The publication gate
        </h3>
        <p className="text-sm leading-relaxed text-text-secondary">
          A dataset becomes visible to the analytical engine only when it is{" "}
          <strong>published</strong>. Draft and partially-mapped datasets cannot leak into an
          analysis, and a dataset with blocking quality errors cannot be published at all. The
          uploaded source file is kept unchanged, so any published figure can always be
          re-derived from exactly what the source system sent.
        </p>
      </Card>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between">
      <dt className="text-text-muted">{label}</dt>
      <dd className="truncate pl-2 text-text-secondary">{value}</dd>
    </div>
  );
}

function SummaryTile({
  label,
  value,
  of,
  loading,
}: {
  label: string;
  value: number;
  of?: number;
  loading?: boolean;
}) {
  return (
    <Card className="p-4">
      <p className="text-[11px] font-medium uppercase tracking-wider text-text-muted">{label}</p>
      {loading ? (
        <Skeleton className="mt-2 h-7 w-20" />
      ) : (
        <p className="mt-1.5 text-2xl font-semibold text-text-primary tabular">
          {value}
          {of !== undefined && (
            <span className="ml-1 text-sm font-normal text-text-muted">of {of}</span>
          )}
        </p>
      )}
    </Card>
  );
}
