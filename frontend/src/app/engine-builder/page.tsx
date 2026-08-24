"use client";

import Link from "next/link";
import * as React from "react";
import { BadgeCheck, ClipboardCheck, GitCommitHorizontal, Plus, Search, Wrench } from "lucide-react";

import { CertificationMark } from "@/components/analytics/analytical-card";
import { MetadataAssistant } from "@/components/data-builder/control-plane";
import { PageHeader } from "@/components/layout/page-header";
import { useCanEditData } from "@/components/system/role-switcher";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input, Select } from "@/components/ui/input";
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
import { api } from "@/lib/api";
import { titleCase } from "@/lib/format";
import { useAsync, useDebounced } from "@/lib/hooks";

/**
 * Engine Builder.
 *
 * Four areas over the real registry: the library reads the registered analyses,
 * their contracts and their certification directly from the backend, so what is
 * shown here IS the system's configuration rather than a description of it.
 */
export default function EngineBuilderPage() {
  const [tab, setTab] = React.useState("library");
  const [search, setSearch] = React.useState("");
  const [category, setCategory] = React.useState("all");
  const debounced = useDebounced(search);
  const canEdit = useCanEditData();

  const library = useAsync(() => api.analyses(), []);
  const analyses = library.data?.analyses ?? [];

  const categories = Array.from(new Set(analyses.map((a) => a.category))).sort();

  const filtered = analyses.filter((a) => {
    if (category !== "all" && a.category !== category) return false;
    if (!debounced) return true;
    const q = debounced.toLowerCase();
    return (
      a.name.toLowerCase().includes(q) ||
      a.description.toLowerCase().includes(q) ||
      a.id.includes(q) ||
      a.owner.toLowerCase().includes(q)
    );
  });

  return (
    <div className="space-y-6">
      <PageHeader
        title="Engine Builder"
        description="Define, test, version and certify analytical capability. Every analysis declares the datasets and variables it needs, its parameters, its methodology, its outputs and its validation rules — and the planner may only ever choose from what is registered here."
        status="live"
        actions={
          canEdit ? (
            <Button asChild>
              <Link href="/engine-builder/new">
                <Plus aria-hidden />
                New analysis
              </Link>
            </Button>
          ) : undefined
        }
      />

      <div className="grid gap-3 sm:grid-cols-3">
        <Tile label="Registered analyses" value={library.data?.total} loading={library.loading} />
        <Tile
          label="IPM Certified"
          value={library.data?.certified}
          loading={library.loading}
          icon={<BadgeCheck className="size-4 text-info" aria-hidden />}
        />
        <Tile label="User defined" value={library.data?.user_defined} loading={library.loading} />
      </div>

      <Tabs
        active={tab}
        onChange={setTab}
        tabs={[
          { id: "library", label: "Analysis Library", count: analyses.length },
          { id: "builder", label: "Analysis Builder" },
          { id: "testing", label: "Testing & Validation" },
          { id: "governance", label: "Version & Governance" },
        ]}
      />

      {tab === "library" && (
        <>
          <div className="flex flex-wrap items-center gap-3">
            <div className="relative min-w-64 flex-1">
              <Search
                className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-text-muted"
                aria-hidden
              />
              <Input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search analyses…"
                className="pl-9"
                aria-label="Search analyses"
              />
            </div>
            <Select
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              className="w-44"
              aria-label="Filter by category"
            >
              <option value="all">All categories</option>
              {categories.map((c) => (
                <option key={c} value={c}>
                  {titleCase(c)}
                </option>
              ))}
            </Select>
          </div>

          <Card>
            {library.loading ? (
              <div className="space-y-2 p-4">
                {[0, 1, 2, 3, 4].map((i) => (
                  <Skeleton key={i} className="h-12 w-full" />
                ))}
              </div>
            ) : library.error ? (
              <p className="p-4 text-sm text-negative">{library.error}</p>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow className="hover:bg-transparent">
                    <TableHead>Analysis</TableHead>
                    <TableHead>Category</TableHead>
                    <TableHead>Required data</TableHead>
                    <TableHead>Version</TableHead>
                    <TableHead>Owner</TableHead>
                    <TableHead>Validation</TableHead>
                    <TableHead>Certification</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filtered.map((a) => (
                    <TableRow key={a.id}>
                      <TableCell>
                        <Link
                          href={`/engine-builder/${a.id}`}
                          className="block max-w-md hover:underline"
                        >
                          <span className="font-medium text-text-primary">{a.name}</span>
                          <span className="mt-0.5 block truncate text-xs text-text-muted">
                            {a.description}
                          </span>
                        </Link>
                      </TableCell>
                      <TableCell>
                        <Badge variant="outline">{titleCase(a.category)}</Badge>
                      </TableCell>
                      <TableCell className="font-mono text-xs">
                        {a.required_datasets.join(", ")}
                      </TableCell>
                      <TableCell className="tabular text-xs">v{a.version}</TableCell>
                      <TableCell className="text-xs">{a.owner}</TableCell>
                      <TableCell>
                        {a.is_certified ? (
                          <span className="text-xs text-positive">Passing</span>
                        ) : (
                          <span className="text-xs text-text-muted">Not certified</span>
                        )}
                      </TableCell>
                      <TableCell>
                        <CertificationMark certification={a.certification} />
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </Card>
          {!library.loading && filtered.length === 0 && (
            <p className="text-center text-sm text-text-muted">No analyses match that search.</p>
          )}
        </>
      )}

      {tab === "builder" && (
        <Card className="p-6">
          <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-text-primary">
            <Wrench className="size-4 text-text-muted" aria-hidden />
            Analysis Builder
          </h3>
          <p className="mb-4 max-w-3xl text-sm leading-relaxed text-text-secondary">
            Define a new analytical capability: its name, category, the governed datasets and
            variables it reads, its parameters, its output schema and its preferred
            visualisation. A new analysis binds to an approved engine function — arbitrary code
            is never accepted, which is what keeps the registry safe for the planner to choose
            from.
          </p>
          <Button asChild>
            <Link href="/engine-builder/new">
              <Plus aria-hidden />
              Open the builder
            </Link>
          </Button>
        </Card>
      )}

      {tab === "testing" && (
        <Card className="p-6">
          <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold text-text-primary">
            <ClipboardCheck className="size-4 text-text-muted" aria-hidden />
            Testing &amp; Validation
          </h3>
          <p className="mb-4 max-w-3xl text-sm leading-relaxed text-text-secondary">
            Every certified analysis declares validation rules that run on each execution — not
            only in a test suite. These are the checks that catch a wrong answer that still looks
            plausible.
          </p>
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead>Analysis</TableHead>
                <TableHead numeric>Rules</TableHead>
                <TableHead>Status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {analyses.map((a) => (
                <TableRow key={a.id}>
                  <TableCell>
                    <Link href={`/engine-builder/${a.id}`} className="hover:underline">
                      {a.name}
                    </Link>
                  </TableCell>
                  <TableCell numeric>—</TableCell>
                  <TableCell>
                    {a.is_certified ? (
                      <Badge variant="positive">Certified · rules enforced</Badge>
                    ) : (
                      <Badge variant="warning">Not certified</Badge>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <p className="mt-3 text-xs text-text-muted">
            Open an analysis to see its declared rules. Interactive test-case execution from this
            screen is not built yet; the rules themselves run on every execution today.
          </p>
        </Card>
      )}

      {tab === "governance" && (
        <Card className="p-6">
          <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold text-text-primary">
            <GitCommitHorizontal className="size-4 text-text-muted" aria-hidden />
            Version &amp; Governance
          </h3>
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead>Analysis</TableHead>
                <TableHead>Current version</TableHead>
                <TableHead>Owner</TableHead>
                <TableHead>Certification</TableHead>
                <TableHead>Runnable</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {analyses.map((a) => (
                <TableRow key={a.id}>
                  <TableCell className="font-medium text-text-primary">{a.name}</TableCell>
                  <TableCell className="tabular text-xs">v{a.version}</TableCell>
                  <TableCell className="text-xs">{a.owner}</TableCell>
                  <TableCell>
                    <CertificationMark certification={a.certification} />
                  </TableCell>
                  <TableCell>
                    {a.is_runnable ? (
                      <span className="text-xs text-positive">Yes</span>
                    ) : (
                      <span className="text-xs text-negative">Blocked</span>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <p className="mt-3 text-xs text-text-muted">
            A certified version is immutable — a change means a new version, which is what lets an
            analysis run months ago be reproduced exactly. Approval workflow for certification is
            in the Workflow screen.
          </p>
        </Card>
      )}

      <MetadataAssistant scope="engine" />
    </div>
  );
}

function Tile({
  label,
  value,
  loading,
  icon,
}: {
  label: string;
  value?: number;
  loading?: boolean;
  icon?: React.ReactNode;
}) {
  return (
    <Card className="p-4">
      <p className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wider text-text-muted">
        {icon}
        {label}
      </p>
      {loading ? (
        <Skeleton className="mt-2 h-7 w-14" />
      ) : (
        <p className="mt-1.5 text-2xl font-semibold text-text-primary tabular">{value ?? "—"}</p>
      )}
    </Card>
  );
}
