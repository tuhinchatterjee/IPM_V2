"use client";

import * as React from "react";
import Link from "next/link";
import { Check, Loader2, Save } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ApiError, api, type EngineResult } from "@/lib/api";

/**
 * That this analysis was composed, and where to read how. §14.
 *
 * It used to carry the working itself: "How the question was read" with its
 * filter chips, "View analytical plan (7 steps)" as a table, "View SQL" with
 * its bound parameters. All of it true, all of it available, and all of it
 * underneath every answer — so a credit officer reading a portfolio scrolled
 * past an operations table to reach the next thing they cared about.
 *
 * None of it is gone. Every piece is on the Trace, which is the surface built
 * to hold it and the one an auditor opens. What stays here is the one fact a
 * reader of the ANSWER needs: this calculation was composed for this question
 * and nobody has reviewed it. That is a caveat about the result, so it belongs
 * beside the result.
 */
export function DynamicAnalysisPanel({
  result,
  traceHref,
}: {
  result: EngineResult;
  traceHref?: string;
}) {
  const reading = result.reading;
  const plan = result.plan;

  if (!reading && !plan) return null;

  return (
    <div className="border-t border-border bg-surface-sunken px-5 py-3">
      <p className="text-xs leading-relaxed text-text-muted">
        No certified analysis answers this combination of conditions, so
        CreditProbe composed one. It ran through the same governed runtime as
        every certified analysis — the same catalogue, the same validator, the
        same parameterised SQL — but nobody has reviewed the calculation
        itself.{" "}
        {traceHref ? (
          <Link href={traceHref} className="underline hover:text-text-primary">
            The Trace shows how the question was read, the{" "}
            {plan?.operations.length ?? 0}-step plan, and the statement it ran.
          </Link>
        ) : (
          <>
            The Trace shows how the question was read, the plan, and the
            statement it ran.
          </>
        )}
      </p>
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
export function SaveAsMethod({
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
