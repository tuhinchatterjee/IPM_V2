"use client";

import Link from "next/link";
import { notFound } from "next/navigation";
import * as React from "react";
import { ArrowLeft, Play } from "lucide-react";

import { PageHeader } from "@/components/layout/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { DEMO_NOTICE, findBlueprint } from "@/lib/demo";

export default function BlueprintPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = React.use(params);
  const blueprint = findBlueprint(id);
  if (!blueprint) notFound();

  return (
    <div className="space-y-6">
      <Button variant="ghost" size="sm" asChild className="-ml-2">
        <Link href="/blueprints"><ArrowLeft aria-hidden />Blueprints</Link>
      </Button>

      <PageHeader
        title={blueprint.name}
        description={blueprint.description}
        status="preview"
        phase="One-click execution next"
        actions={
          <div className="flex items-center gap-2">
            <Badge variant="outline">v{blueprint.version}</Badge>
            <Badge variant="accent">{blueprint.cadence}</Badge>
            <Button size="sm" disabled title="Blueprint execution is not built yet">
              <Play aria-hidden />
              Run blueprint
            </Button>
          </div>
        }
      />

      <div className="grid gap-4 lg:grid-cols-[1.4fr_1fr]">
        <Card className="p-5">
          <h3 className="mb-3 text-sm font-semibold text-text-primary">Workflow steps</h3>
          <ol className="space-y-3">
            {blueprint.steps.map((s, i) => (
              <li key={s.analysisId} className="flex items-start gap-3">
                <span className="flex size-6 shrink-0 items-center justify-center rounded-full border border-border text-xs font-semibold text-text-secondary tabular">
                  {i + 1}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium text-text-primary">{s.title}</p>
                  <Link
                    href={`/engine-builder/${s.analysisId}`}
                    className="font-mono text-xs text-accent hover:underline"
                  >
                    {s.analysisId}
                  </Link>
                </div>
                <Button variant="ghost" size="sm" asChild>
                  <Link href={`/analysis/${s.analysisId}`}>Run step</Link>
                </Button>
              </li>
            ))}
          </ol>
          <p className="mt-4 border-t border-border pt-3 text-xs text-text-muted">
            Each step is a registered, certified analysis and can be run on its own today.
            Executing the whole workflow in one action, with shared parameters, is the next step.
          </p>
        </Card>

        <Card className="p-5">
          <h3 className="mb-3 text-sm font-semibold text-text-primary">Parameters</h3>
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead>Name</TableHead>
                <TableHead>Default</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {blueprint.parameters.map((p) => (
                <TableRow key={p.name}>
                  <TableCell>
                    <span className="font-mono text-xs text-text-primary">{p.name}</span>
                    <span className="mt-0.5 block text-xs text-text-muted">{p.description}</span>
                  </TableCell>
                  <TableCell className="font-mono text-xs">{p.default}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <dl className="mt-4 space-y-2 border-t border-border pt-3 text-sm">
            <div className="flex justify-between">
              <dt className="text-xs text-text-muted">Owner</dt>
              <dd className="text-text-secondary">{blueprint.owner}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-xs text-text-muted">Cadence</dt>
              <dd className="text-text-secondary">{blueprint.cadence}</dd>
            </div>
          </dl>
        </Card>
      </div>
      <p className="text-xs text-text-muted">{DEMO_NOTICE}</p>
    </div>
  );
}
