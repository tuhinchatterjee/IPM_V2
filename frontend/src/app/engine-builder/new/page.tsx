"use client";

import Link from "next/link";
import * as React from "react";
import { ArrowLeft, Info, Lock, Save } from "lucide-react";

import { PageHeader } from "@/components/layout/page-header";
import { ReadOnlyNotice, useCanEditData } from "@/components/system/role-switcher";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Field, Input, Select, Textarea } from "@/components/ui/input";
import { api } from "@/lib/api";
import { useAsync } from "@/lib/hooks";

/**
 * Analysis Builder.
 *
 * Defines the metadata of a new analytical capability and binds it to an
 * APPROVED engine function. There is deliberately no code editor: the registry
 * is what the planner chooses from, so accepting arbitrary Python here would put
 * a hole straight through the product's central control.
 *
 * Persisting a new definition needs an Engine Builder write endpoint, which does
 * not exist yet — the form states that plainly rather than pretending to save.
 */

const CATEGORIES = ["monitor", "detect", "investigate", "stress", "reference"];
const VISUALISATIONS = [
  "table", "bar", "stacked_bar", "line", "area", "pie", "heatmap", "matrix", "waterfall", "kpi", "treemap",
];

export default function AnalysisBuilderPage() {
  const canEdit = useCanEditData();
  const catalog = useAsync(() => api.catalog(), []);
  const library = useAsync(() => api.analyses(), []);

  const [name, setName] = React.useState("");
  const [description, setDescription] = React.useState("");
  const [category, setCategory] = React.useState("monitor");
  const [dataset, setDataset] = React.useState("portfolio_facility");
  const [fields, setFields] = React.useState("");
  const [boundFunction, setBoundFunction] = React.useState("");
  const [visualisation, setVisualisation] = React.useState("table");
  const [methodology, setMethodology] = React.useState("");

  if (!canEdit) {
    return (
      <div className="space-y-6">
        <Back />
        <PageHeader title="New analysis" description="Define an analytical capability." />
        <ReadOnlyNotice action="create or edit analyses" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <Back />
      <PageHeader
        title="New analysis"
        description="Declare what the analysis needs, what it produces and how it should be shown, then bind it to an approved engine function."
        status="preview"
        phase="Definitions are not persisted yet"
      />

      <Card className="flex items-start gap-2.5 border-info/30 bg-info-muted p-4 text-sm text-info">
        <Info className="mt-0.5 size-4 shrink-0" aria-hidden />
        <span>
          This form captures a complete analysis definition, but Engine Builder has no write
          endpoint yet, so nothing is saved. The ten certified analyses and the user-defined
          example are registered in code and are fully live in the library.
        </span>
      </Card>

      <div className="grid gap-4 lg:grid-cols-[1.5fr_1fr]">
        <Card className="p-6">
          <h3 className="mb-4 text-sm font-semibold text-text-primary">Definition</h3>
          <div className="grid gap-4 md:grid-cols-2">
            <Field label="Name">
              <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Watchlist Concentration" />
            </Field>
            <Field label="Category">
              <Select value={category} onChange={(e) => setCategory(e.target.value)}>
                {CATEGORIES.map((c) => (
                  <option key={c} value={c}>{c}</option>
                ))}
              </Select>
            </Field>
            <Field label="Description" className="md:col-span-2">
              <Textarea
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="What question does this analysis answer?"
              />
            </Field>
            <Field label="Required dataset" hint="Only published datasets may be read.">
              <Select value={dataset} onChange={(e) => setDataset(e.target.value)}>
                {(catalog.data?.datasets ?? []).map((d) => (
                  <option key={d.name} value={d.name}>{d.name}</option>
                ))}
              </Select>
            </Field>
            <Field label="Preferred visualisation">
              <Select value={visualisation} onChange={(e) => setVisualisation(e.target.value)}>
                {VISUALISATIONS.map((v) => (
                  <option key={v} value={v}>{v.replace(/_/g, " ")}</option>
                ))}
              </Select>
            </Field>
            <Field
              label="Required variables"
              className="md:col-span-2"
              hint="Comma separated governed field names."
            >
              <Input
                value={fields}
                onChange={(e) => setFields(e.target.value)}
                placeholder="ead, ifrs9_stage, sector"
                className="font-mono text-xs"
              />
            </Field>
            <Field
              label="Calculation methodology"
              className="md:col-span-2"
              hint="Written for a risk officer to review and challenge. This text appears in the Trace node beside the number."
            >
              <Textarea
                value={methodology}
                onChange={(e) => setMethodology(e.target.value)}
                className="min-h-28"
              />
            </Field>
          </div>
          <div className="mt-6 flex justify-end">
            <Button disabled title="Engine Builder has no write endpoint yet">
              <Save aria-hidden />
              Save definition
            </Button>
          </div>
        </Card>

        <div className="space-y-4">
          <Card className="p-5">
            <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-text-primary">
              <Lock className="size-4 text-text-muted" aria-hidden />
              Bind to an approved function
            </h3>
            <p className="mb-3 text-xs leading-relaxed text-text-muted">
              A new analysis binds to an engine function the bank has already approved. Arbitrary
              code is never accepted — the registry is what the planner chooses from, so a code
              editor here would defeat the control it exists to provide.
            </p>
            <Select value={boundFunction} onChange={(e) => setBoundFunction(e.target.value)}>
              <option value="">Select an approved function…</option>
              {(library.data?.analyses ?? []).map((a) => (
                <option key={a.id} value={a.id}>{a.id}</option>
              ))}
            </Select>
          </Card>

          <Card className="p-5">
            <h3 className="mb-2 text-sm font-semibold text-text-primary">Certification</h3>
            <p className="mb-3 text-xs leading-relaxed text-text-muted">
              A new analysis starts as <strong>User Defined</strong> and carries no verification
              tick. It becomes IPM Certified only after review and approval in Workflow.
            </p>
            <Badge variant="warning">User Defined</Badge>
          </Card>
        </div>
      </div>
    </div>
  );
}

function Back() {
  return (
    <Button variant="ghost" size="sm" asChild className="-ml-2">
      <Link href="/engine-builder">
        <ArrowLeft aria-hidden />
        Engine Builder
      </Link>
    </Button>
  );
}
