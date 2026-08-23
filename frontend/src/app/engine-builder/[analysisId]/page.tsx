"use client";

import Link from "next/link";
import * as React from "react";
import { ArrowLeft, Play } from "lucide-react";

import { AnalyticalCard, CertificationMark } from "@/components/analytics/analytical-card";
import { DefinitionRow } from "@/components/analytics/primitives";
import { ResultView } from "@/components/analytics/result-view";
import { PageHeader } from "@/components/layout/page-header";
import { useCanRunAnalysis } from "@/components/system/role-switcher";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
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
import { useAnalysis, useAsync } from "@/lib/hooks";

/**
 * Analysis detail.
 *
 * Everything the registry declares about one capability, plus the ability to run
 * it. The methodology text is the same string the Trace node carries, so what a
 * reviewer reads here is exactly what accompanies the number.
 */
export default function AnalysisDetailPage({
  params,
}: {
  params: Promise<{ analysisId: string }>;
}) {
  const { analysisId } = React.use(params);
  const [tab, setTab] = React.useState("definition");
  const [running, setRunning] = React.useState(false);
  const canRun = useCanRunAnalysis();

  const detail = useAsync(() => api.analysis(analysisId), [analysisId]);
  const run = useAnalysis(analysisId, {}, running);

  const a = detail.data;

  return (
    <div className="space-y-6">
      <Button variant="ghost" size="sm" asChild className="-ml-2">
        <Link href="/engine-builder">
          <ArrowLeft aria-hidden />
          Analysis Library
        </Link>
      </Button>

      {detail.loading && <Skeleton className="h-64 w-full" />}
      {detail.error && (
        <Card className="border-negative/40 p-4 text-sm text-negative">{detail.error}</Card>
      )}

      {a && (
        <>
          <PageHeader
            title={a.name}
            description={a.description}
            actions={
              <div className="flex items-center gap-2">
                <CertificationMark certification={a.certification} />
                <Badge variant="outline">v{a.version}</Badge>
                <Button
                  size="sm"
                  disabled={!canRun || !a.is_runnable}
                  onClick={() => {
                    setRunning(true);
                    setTab("run");
                  }}
                  title={!canRun ? "A Viewer cannot execute an analysis" : undefined}
                >
                  <Play aria-hidden />
                  Run analysis
                </Button>
              </div>
            }
          />

          <Tabs
            active={tab}
            onChange={setTab}
            tabs={[
              { id: "definition", label: "Definition" },
              { id: "parameters", label: "Parameters", count: a.parameters.length },
              { id: "outputs", label: "Output schema", count: a.outputs.length },
              { id: "validation", label: "Validation", count: a.validation_rules.length },
              { id: "run", label: "Run" },
            ]}
          />

          {tab === "definition" && (
            <div className="grid gap-4 lg:grid-cols-[1.4fr_1fr]">
              <Card className="p-5">
                <h3 className="mb-3 text-sm font-semibold text-text-primary">
                  Calculation methodology
                </h3>
                <p className="whitespace-pre-line text-sm leading-relaxed text-text-secondary">
                  {a.calculation_description}
                </p>
              </Card>
              <div className="space-y-4">
                <Card className="p-5">
                  <h3 className="mb-2 text-sm font-semibold text-text-primary">Inputs</h3>
                  <dl className="divide-y divide-border">
                    <DefinitionRow label="Category">{titleCase(a.category)}</DefinitionRow>
                    <DefinitionRow label="Owner">{a.owner}</DefinitionRow>
                    <DefinitionRow label="Comparison period">
                      {a.requires_compare_period ? "Required" : "Not required"}
                    </DefinitionRow>
                    <DefinitionRow label="Visualisations">
                      <div className="flex flex-wrap gap-1">
                        {a.supported_visualizations.map((v) => (
                          <Badge key={v} variant="outline">
                            {v.replace(/_/g, " ")}
                          </Badge>
                        ))}
                      </div>
                    </DefinitionRow>
                  </dl>
                </Card>

                <Card className="p-5">
                  <h3 className="mb-2 text-sm font-semibold text-text-primary">Required datasets</h3>
                  <ul className="space-y-2">
                    {a.datasets.map((d) => (
                      <li key={d.name} className="flex items-start justify-between gap-3 text-sm">
                        <div className="min-w-0">
                          <p className="font-mono text-xs text-text-primary">{d.name}</p>
                          {d.grain && <p className="text-xs text-text-muted">{d.grain}</p>}
                        </div>
                        {d.available ? (
                          <Badge variant="positive">Published</Badge>
                        ) : (
                          <Badge variant="negative">Not available</Badge>
                        )}
                      </li>
                    ))}
                  </ul>
                </Card>

                <Card className="p-5">
                  <h3 className="mb-2 text-sm font-semibold text-text-primary">
                    Required variables
                    <span className="ml-2 text-xs font-normal text-text-muted">
                      {a.required_fields.length}
                    </span>
                  </h3>
                  <div className="flex flex-wrap gap-1">
                    {a.required_fields.map((f) => (
                      <code
                        key={f}
                        className="rounded bg-surface-sunken px-1.5 py-0.5 font-mono text-[11px] text-text-secondary"
                      >
                        {f}
                      </code>
                    ))}
                  </div>
                </Card>
              </div>
            </div>
          )}

          {tab === "parameters" && (
            <Card>
              <Table>
                <TableHeader>
                  <TableRow className="hover:bg-transparent">
                    <TableHead>Parameter</TableHead>
                    <TableHead>Type</TableHead>
                    <TableHead>Default</TableHead>
                    <TableHead>Allowed values</TableHead>
                    <TableHead>Range</TableHead>
                    <TableHead>Description</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {a.parameters.map((p) => (
                    <TableRow key={p.name}>
                      <TableCell className="font-mono text-xs text-text-primary">
                        {p.name}
                        {p.required && <span className="ml-1 text-negative">*</span>}
                      </TableCell>
                      <TableCell>
                        <Badge variant="outline">{p.type}</Badge>
                      </TableCell>
                      <TableCell className="font-mono text-xs">
                        {p.default === null ? "—" : String(p.default)}
                      </TableCell>
                      <TableCell className="max-w-xs text-xs text-text-muted">
                        {p.allowed_values?.map(String).join(", ") ?? "—"}
                      </TableCell>
                      <TableCell className="text-xs">
                        {p.minimum !== null || p.maximum !== null
                          ? `${p.minimum ?? "−∞"} to ${p.maximum ?? "∞"}`
                          : "—"}
                      </TableCell>
                      <TableCell className="max-w-sm text-xs text-text-muted">
                        {p.description}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </Card>
          )}

          {tab === "outputs" && (
            <Card>
              <Table>
                <TableHeader>
                  <TableRow className="hover:bg-transparent">
                    <TableHead>Output</TableHead>
                    <TableHead>Type</TableHead>
                    <TableHead>Unit</TableHead>
                    <TableHead numeric>Precision</TableHead>
                    <TableHead>Description</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {a.outputs.map((o) => (
                    <TableRow key={o.name}>
                      <TableCell className="font-mono text-xs text-text-primary">{o.name}</TableCell>
                      <TableCell>
                        <Badge variant="outline">{o.data_type}</Badge>
                      </TableCell>
                      <TableCell className="text-xs">{o.unit ?? "—"}</TableCell>
                      <TableCell numeric>{o.precision ?? "—"}</TableCell>
                      <TableCell className="max-w-md text-xs text-text-muted">
                        {o.description}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </Card>
          )}

          {tab === "validation" && (
            <Card className="p-5">
              <p className="mb-4 text-sm text-text-secondary">
                These post-conditions run on every execution, not only in tests. They catch a
                wrong answer that still looks plausible.
              </p>
              <ul className="space-y-2">
                {a.validation_rules.map((r) => (
                  <li
                    key={r.name}
                    className="rounded-md border border-border bg-surface-sunken px-4 py-3"
                  >
                    <div className="flex items-center gap-2">
                      <code className="font-mono text-xs text-text-primary">{r.name}</code>
                      <Badge variant={r.severity === "error" ? "negative" : "warning"}>
                        {r.severity}
                      </Badge>
                    </div>
                    <p className="mt-1 text-xs text-text-muted">{r.description}</p>
                  </li>
                ))}
              </ul>
            </Card>
          )}

          {tab === "run" && (
            <AnalyticalCard
              title={`${a.name} — result`}
              description="Executed with default parameters against the latest reporting period"
              run={run.data}
              loading={run.loading}
              error={run.error}
              onRetry={run.reload}
              actions={false}
              minHeight={280}
            >
              {!running && (
                <div className="flex h-full flex-col items-start justify-center gap-3">
                  <p className="text-sm text-text-muted">
                    Press Run analysis to execute this against the governed data.
                  </p>
                  <Button size="sm" disabled={!canRun} onClick={() => setRunning(true)}>
                    <Play aria-hidden />
                    Run analysis
                  </Button>
                </div>
              )}
              {run.data && <ResultView run={run.data} />}
            </AnalyticalCard>
          )}
        </>
      )}
    </div>
  );
}
