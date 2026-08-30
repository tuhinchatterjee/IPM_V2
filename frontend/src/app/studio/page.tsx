"use client";

import Link from "next/link";
import * as React from "react";
import {
  BadgeCheck,
  Plus,
  ScrollText,
  Search,
  ShieldQuestion,
} from "lucide-react";

import { PageHeader } from "@/components/layout/page-header";
import { LifecycleMark } from "@/components/studio/lifecycle";
import { useCanRunAnalysis } from "@/components/system/role-switcher";
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
import { api } from "@/lib/api";
import { useAsync, useDebounced } from "@/lib/hooks";

/**
 * Analysis Studio — the method library.
 *
 * Three hundred credit-risk methods, and the honest part is that most of them
 * are definitions rather than implementations. The counts across the top say so
 * in the first sentence a person reads, because a library that presents 300
 * methods as 300 certified calculations is the exact misrepresentation this
 * product exists to avoid.
 */
export default function AnalysisStudioPage() {
  const [search, setSearch] = React.useState("");
  const [category, setCategory] = React.useState("");
  const [lifecycle, setLifecycle] = React.useState("");
  const [certifiedOnly, setCertifiedOnly] = React.useState(false);
  const debounced = useDebounced(search, 250);
  const canBuild = useCanRunAnalysis();

  const library = useAsync(
    () =>
      api.studioLibrary({
        q: debounced,
        category,
        lifecycle,
        certifiedOnly,
        limit: 300,
      }),
    [debounced, category, lifecycle, certifiedOnly],
  );

  const methods = library.data?.methods ?? [];
  const stats = library.data?.stats;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Analysis Studio"
        description="Every credit-risk method CreditProbe knows: what it measures, the methodology behind it, the governed fields it needs, and — where one exists — the implementation and the test cases that prove it. Build new methods by describing them, and certify them only once their validation pack passes."
        status="live"
        actions={
          canBuild ? (
            <div className="flex flex-wrap gap-2">
              {/* §27 puts Regulatory Intelligence under Analysis Studio,
                  because this is where a method is defined and certified —
                  and a requirement that says a figure must be calculated
                  ends up here as a DRAFT method, not as a certified one. */}
              <Button asChild variant="outline">
                <Link href="/studio/regulatory-intelligence">
                  <ScrollText aria-hidden />
                  Regulatory Intelligence
                </Link>
              </Button>
              <Button asChild>
                <Link href="/studio/new">
                  <Plus aria-hidden />
                  Build a method
                </Link>
              </Button>
            </div>
          ) : undefined
        }
      />

      <div className="grid gap-3 sm:grid-cols-4">
        <Tile label="Methods" value={stats?.total} loading={library.loading} />
        <Tile
          label="CreditProbe Certified"
          value={stats?.certified}
          loading={library.loading}
          icon={<BadgeCheck className="size-4 text-info" aria-hidden />}
        />
        <Tile
          label="Runnable"
          value={stats?.runnable}
          loading={library.loading}
          note="Has an implementation the runtime can execute."
        />
        <Tile
          label="Definitions only"
          value={stats ? Math.max(stats.total - stats.runnable, 0) : undefined}
          loading={library.loading}
          note="Written down, not yet built. Shown as such rather than hidden."
        />
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <div className="relative min-w-64 flex-1">
          <Search
            className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-text-muted"
            aria-hidden
          />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search methods — try 'vintage', 'cure rate', 'ODR'…"
            className="pl-9"
            aria-label="Search methods"
          />
        </div>
        <Select
          value={category}
          onChange={(e) => setCategory(e.target.value)}
          className="w-52"
          aria-label="Filter by category"
        >
          <option value="">All categories</option>
          {(library.data?.categories ?? []).map((c) => (
            <option key={c.category} value={c.category}>
              {c.category} ({c.count})
            </option>
          ))}
        </Select>
        <Select
          value={lifecycle}
          onChange={(e) => setLifecycle(e.target.value)}
          className="w-44"
          aria-label="Filter by state"
        >
          <option value="">Any state</option>
          {(library.data?.lifecycles ?? []).map((l) => (
            <option key={l.id} value={l.id}>
              {l.label}
            </option>
          ))}
        </Select>
        <Button
          variant={certifiedOnly ? "default" : "outline"}
          size="sm"
          onClick={() => setCertifiedOnly((v) => !v)}
        >
          <BadgeCheck aria-hidden />
          Certified only
        </Button>
      </div>

      <Card>
        {library.loading ? (
          <div className="space-y-2 p-4">
            {[0, 1, 2, 3, 4, 5].map((i) => (
              <Skeleton key={i} className="h-12 w-full" />
            ))}
          </div>
        ) : library.error ? (
          <p className="p-4 text-sm text-negative">{library.error}</p>
        ) : methods.length === 0 ? (
          <p className="p-8 text-center text-sm text-text-muted">
            No method matches that. The Studio does not guess at near misses — a
            method that answers a slightly different question is worse than no
            answer.
          </p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead>Method</TableHead>
                <TableHead>Category</TableHead>
                <TableHead>State</TableHead>
                <TableHead className="text-right">Tests</TableHead>
                <TableHead>Source</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {methods.map((m) => (
                <TableRow key={m.id}>
                  <TableCell>
                    <Link
                      href={`/studio/${encodeURIComponent(m.id)}`}
                      className="block max-w-xl hover:underline"
                    >
                      <span className="font-medium text-text-primary">
                        {m.name}
                      </span>
                      <span className="mt-0.5 block truncate text-xs text-text-muted">
                        {m.definition}
                      </span>
                    </Link>
                  </TableCell>
                  <TableCell>
                    <Badge variant="outline">{m.category}</Badge>
                  </TableCell>
                  <TableCell>
                    <LifecycleMark
                      lifecycle={m.lifecycle}
                      label={m.lifecycle_label}
                    />
                  </TableCell>
                  <TableCell className="tabular text-right text-xs">
                    {m.test_count === 0 ? (
                      <span className="text-text-muted">—</span>
                    ) : (
                      <span
                        className={
                          m.tests_failing ? "text-negative" : "text-positive"
                        }
                      >
                        {m.tests_passing}/{m.test_count}
                      </span>
                    )}
                  </TableCell>
                  <TableCell className="text-xs text-text-muted">
                    {m.source === "bank" ? "This bank" : "CreditProbe"}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </Card>

      <p className="text-xs text-text-muted">
        A method implemented by a registered engine analysis links straight to
        it — those analyses are still certified, still versioned and still
        reachable at{" "}
        <Link href="/engine-builder" className="underline">
          the engine registry
        </Link>
        . They are now one kind of implementation behind a method rather than
        the whole of what CreditProbe can compute.
      </p>

      {stats && stats.certification_audit.downgraded_count > 0 && (
        <Card className="p-4">
          <h2 className="flex items-center gap-2 text-sm font-semibold text-text-primary">
            <ShieldQuestion className="size-4 text-text-muted" aria-hidden />
            {stats.certification_audit.downgraded_count} certification{" "}
            {stats.certification_audit.downgraded_count === 1
              ? "claim was"
              : "claims were"}{" "}
            not upheld
          </h2>
          <p className="mt-1 text-xs text-text-muted">
            Every claim is re-checked when the library loads. A method that
            claims the tick without a runnable implementation, or with test
            cases nobody has run, is shown as preconfigured instead — with the
            reason.
          </p>
          <ul className="mt-3 space-y-1 text-xs">
            {Object.entries(stats.certification_audit.downgraded)
              .slice(0, 6)
              .map(([id, reason]) => (
                <li key={id} className="text-text-secondary">
                  <span className="font-mono text-text-primary">{id}</span> —{" "}
                  {reason}
                </li>
              ))}
          </ul>
        </Card>
      )}
    </div>
  );
}

function Tile({
  label,
  value,
  loading,
  icon,
  note,
}: {
  label: string;
  value?: number;
  loading: boolean;
  icon?: React.ReactNode;
  note?: string;
}) {
  return (
    <Card className="p-4">
      <p className="flex items-center gap-1.5 text-xs text-text-muted">
        {icon}
        {label}
      </p>
      {loading ? (
        <Skeleton className="mt-2 h-7 w-16" />
      ) : (
        <p className="tabular mt-1 text-2xl font-semibold text-text-primary">
          {value ?? "—"}
        </p>
      )}
      {note && (
        <p className="mt-1 text-[11px] leading-snug text-text-muted">{note}</p>
      )}
    </Card>
  );
}
