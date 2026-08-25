"use client";

import * as React from "react";
import { Check, Loader2, Save } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ApiError, api, type EngineResult } from "@/lib/api";

/**
 * What a composed analysis actually did.
 *
 * A certified analysis can point at its definition in the library; a dynamic
 * one has no definition to point at, because it did not exist until the
 * question was asked. So it carries its own: how the question was read, the
 * plan the runtime executed, and the statement with its bound parameters shown
 * separately — that separation is the safety property, so it is shown as one.
 *
 * Behind disclosures rather than always open. The claim is that the working is
 * always available, not that everybody has to read it.
 */
export function DynamicAnalysisPanel({
  result,
  question,
}: {
  result: EngineResult;
  question: string;
}) {
  const reading = result.reading;
  const plan = result.plan;
  const query = result.query;

  if (!reading && !plan) return null;

  return (
    <div className="space-y-4 border-t border-border bg-surface-sunken px-5 py-4">
      <div>
        <p className="text-xs font-medium text-text-secondary">
          Composed for this question
        </p>
        <p className="mt-1 text-xs leading-relaxed text-text-muted">
          No certified analysis answers this combination of conditions, so
          CreditProbe composed one. It ran through the same governed runtime as
          every certified analysis — the same catalogue, the same validator, the
          same parameterised SQL — but nobody has reviewed the calculation
          itself.
        </p>
      </div>

      {reading && (
        <div>
          <p className="text-xs font-medium text-text-secondary">
            How the question was read
          </p>
          <p className="mt-1 text-sm leading-relaxed text-text-primary">
            {reading.summary}
          </p>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {reading.filters.map((f) => (
              <Badge key={`${f.field}-${f.value}`} variant="outline">
                {f.field} = {f.value}
              </Badge>
            ))}
            {reading.conditions.map((c) => (
              <Badge key={c.column} variant="accent">
                {c.description}
              </Badge>
            ))}
          </div>
        </div>
      )}

      {plan && plan.operations.length > 0 && (
        <details className="group">
          <summary className="cursor-pointer list-none text-xs font-medium text-text-muted hover:text-text-primary">
            View analytical plan ({plan.operations.length} steps)
          </summary>
          <Card className="mt-2 overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow className="hover:bg-transparent">
                  <TableHead className="w-8">#</TableHead>
                  <TableHead>Step</TableHead>
                  <TableHead>Operation</TableHead>
                  <TableHead>What it does</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {plan.operations.map((op, index) => (
                  <TableRow key={op.id}>
                    <TableCell className="tabular text-xs text-text-muted">
                      {index + 1}
                    </TableCell>
                    <TableCell className="font-mono text-xs">{op.id}</TableCell>
                    <TableCell>
                      <Badge variant="outline">{op.op}</Badge>
                    </TableCell>
                    <TableCell className="text-xs text-text-muted">
                      {op.label ?? ""}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Card>
        </details>
      )}

      {query?.sql && (
        <details className="group">
          <summary className="cursor-pointer list-none text-xs font-medium text-text-muted hover:text-text-primary">
            View SQL
          </summary>
          <pre className="mt-2 max-h-72 overflow-auto rounded-md border border-border bg-surface p-3 font-mono text-[11px] leading-relaxed text-text-secondary">
            {query.sql}
          </pre>
          <p className="mt-2 text-[11px] leading-relaxed text-text-muted">
            {query.parameters.length} bound parameter
            {query.parameters.length === 1 ? "" : "s"}:{" "}
            <span className="font-mono">{JSON.stringify(query.parameters)}</span>. Every
            value is a placeholder in the statement and a parameter beside it. Nothing was
            concatenated into the SQL, which is what makes a composed analysis safe to run.
          </p>
        </details>
      )}

      <SaveAsMethod result={result} question={question} />
    </div>
  );
}

/**
 * Keep this analysis.
 *
 * It saves as a DRAFT, and the button says so. Running once against one pair of
 * periods is not evidence that a calculation is right, and a saved analysis
 * that arrived carrying a tick would make the tick mean nothing.
 */
function SaveAsMethod({
  result,
  question,
}: {
  result: EngineResult;
  question: string;
}) {
  const [open, setOpen] = React.useState(false);
  const [name, setName] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [saved, setSaved] = React.useState("");
  const [error, setError] = React.useState("");

  if (!result.plan) return null;

  async function save() {
    if (!result.plan) return;
    setBusy(true);
    setError("");
    try {
      const body = await api.studioSaveDynamic({
        name: name.trim(),
        question,
        summary: result.reading?.summary ?? "",
        plan: result.plan,
      });
      setSaved(body.method.id);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not save it.");
    } finally {
      setBusy(false);
    }
  }

  if (saved) {
    return (
      <p className="flex items-center gap-1.5 text-xs text-positive">
        <Check className="size-3.5" aria-hidden />
        Saved to Analysis Studio as a draft.{" "}
        <a className="underline" href={`/studio/${encodeURIComponent(saved)}`}>
          Open it
        </a>
      </p>
    );
  }

  if (!open) {
    return (
      <Button variant="outline" size="sm" onClick={() => setOpen(true)}>
        <Save aria-hidden />
        Save as a method
      </Button>
    );
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      <Input
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder="Name this method"
        className="max-w-xs"
        aria-label="Method name"
      />
      <Button size="sm" onClick={save} disabled={!name.trim() || busy}>
        {busy && <Loader2 className="animate-spin" aria-hidden />}
        Save as a draft
      </Button>
      <Button variant="ghost" size="sm" onClick={() => setOpen(false)}>
        Cancel
      </Button>
      <span className="text-[11px] text-text-muted">
        It arrives with no test cases and no certification.
      </span>
      {error && <span className="text-xs text-negative">{error}</span>}
    </div>
  );
}
