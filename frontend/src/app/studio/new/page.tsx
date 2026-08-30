"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import * as React from "react";
import { ArrowLeft, CheckCircle2, Loader2, XCircle } from "lucide-react";

import { PageHeader } from "@/components/layout/page-header";
import { CaseVerdict } from "@/components/studio/lifecycle";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Field, Input, Textarea } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ApiError, api, type StudioBuildResult, type StudioReading } from "@/lib/api";

const EXAMPLE =
  "I want to measure the share of facilities that are performing at a reporting date and 90 or more days past due one year later.";

/**
 * Build a method by describing it.
 *
 * Three steps, and the middle one is the product. CreditProbe reads the
 * description back, then asks only the decisions that change the answer —
 * facility or customer, 90+ DPD or Stage 3, at the horizon or at any point,
 * what to do with exits, counted or exposure-weighted. Each question says why
 * it matters, because "grain?" means nothing to somebody who has not had the
 * argument before.
 *
 * Nothing is defaulted silently. A rate whose definition was assumed is a rate
 * nobody can defend in a validation meeting.
 */
export default function BuildMethodPage() {
  const router = useRouter();
  const [description, setDescription] = React.useState("");
  const [name, setName] = React.useState("");
  const [opening, setOpening] = React.useState("Q1 2025");
  const [closing, setClosing] = React.useState("Q1 2026");
  const [answers, setAnswers] = React.useState<Record<string, string>>({});

  const [reading, setReading] = React.useState<StudioReading | null>(null);
  const [result, setResult] = React.useState<StudioBuildResult | null>(null);
  const [busy, setBusy] = React.useState<"" | "reading" | "building">("");
  const [error, setError] = React.useState("");

  async function read() {
    setBusy("reading");
    setError("");
    setResult(null);
    try {
      const body = await api.studioDescribe(description);
      setReading(body.reading);
      setAnswers(
        Object.fromEntries(
          body.reading.clarifications.map((c) => [c.id, c.default || ""]),
        ),
      );
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Something went wrong.");
    } finally {
      setBusy("");
    }
  }

  async function build() {
    setBusy("building");
    setError("");
    try {
      const body = await api.studioBuild({
        name: name.trim() || "New Method",
        description,
        answers,
        openingPeriod: opening,
        closingPeriod: closing,
        save: true,
      });
      setResult(body);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Something went wrong.");
    } finally {
      setBusy("");
    }
  }

  const total = result?.validation.cases.find((c) => c.id === "portfolio_total");

  return (
    <div className="space-y-6">
      <PageHeader
        title="Build a method"
        eyebrow="Analysis Studio"
        description="Describe the measure in your own words. CreditProbe reads it back, asks the decisions that change the answer, builds the analytical plan, and runs it against a fixture whose expected results were computed independently of the plan."
        status="live"
        actions={
          <Button variant="ghost" asChild>
            <Link href="/studio">
              <ArrowLeft aria-hidden />
              Library
            </Link>
          </Button>
        }
      />

      {/* ---- 1. describe ---- */}
      <Card className="p-5">
        <Step n={1} title="Describe it" />
        <Field label="What should this method measure?" className="mt-4">
          <Textarea
            id="description"
            rows={3}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder={EXAMPLE}
          />
        </Field>
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <Button onClick={read} disabled={!description.trim() || busy !== ""}>
            {busy === "reading" && <Loader2 className="animate-spin" aria-hidden />}
            Read it back
          </Button>
          <Button variant="ghost" size="sm" onClick={() => setDescription(EXAMPLE)}>
            Use the worked example
          </Button>
        </div>
      </Card>

      {error && (
        <Card className="border-negative/40 p-4">
          <p className="text-sm text-negative">{error}</p>
        </Card>
      )}

      {/* ---- 2. decide ---- */}
      {reading && !reading.understood && (
        <Card className="p-5">
          <Step n={2} title="CreditProbe could not read this" />
          <p className="mt-3 text-sm text-text-secondary">{reading.note}</p>
        </Card>
      )}

      {reading?.understood && (
        <Card className="p-5">
          <Step n={2} title="Decide what the description left open" />
          <p className="mt-3 text-sm text-text-secondary">{reading.summary}</p>
          {Object.keys(reading.detected).length > 0 && (
            <p className="mt-2 text-xs text-text-muted">
              Read directly from your description:{" "}
              {Object.entries(reading.detected)
                .map(([k, v]) => `${k} = ${String(v)}`)
                .join(", ")}
              . Not asked again.
            </p>
          )}

          <div className="mt-5 space-y-5">
            {reading.clarifications.map((c) => (
              <div key={c.id}>
                <p className="text-sm font-medium text-text-primary">{c.question}</p>
                <p className="mt-1 text-xs leading-relaxed text-text-muted">{c.because}</p>
                <div className="mt-2 flex flex-wrap gap-2">
                  {c.options.map((o) => (
                    <button
                      key={o.id}
                      type="button"
                      onClick={() => setAnswers((a) => ({ ...a, [c.id]: o.id }))}
                      title={o.detail}
                      className={`rounded-md border px-3 py-2 text-left text-xs transition-colors ${
                        answers[c.id] === o.id
                          ? "border-accent bg-accent-muted text-accent"
                          : "border-border bg-surface text-text-secondary hover:bg-surface-hover"
                      }`}
                    >
                      <span className="block font-medium">{o.label}</span>
                      {o.detail && (
                        <span className="mt-0.5 block max-w-xs text-[11px] opacity-80">
                          {o.detail}
                        </span>
                      )}
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </div>

          <div className="mt-6 grid gap-4 sm:grid-cols-3">
            <Field label="Name it">
              <Input
                id="name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="One Year Forward Default Rate"
              />
            </Field>
            <Field label="Opening period">
              <Input id="opening" value={opening} onChange={(e) => setOpening(e.target.value)} />
            </Field>
            <Field label="Forward period">
              <Input id="closing" value={closing} onChange={(e) => setClosing(e.target.value)} />
            </Field>
          </div>

          <Button className="mt-5" onClick={build} disabled={busy !== ""}>
            {busy === "building" && <Loader2 className="animate-spin" aria-hidden />}
            Build it and run the validation pack
          </Button>
        </Card>
      )}

      {/* ---- 3. proof ---- */}
      {result && (
        <Card className="p-5">
          <Step n={3} title="What the validation pack says" />

          <div className="mt-4 flex flex-wrap items-center gap-3">
            {result.validation.all_passed ? (
              <span className="inline-flex items-center gap-1.5 text-sm font-medium text-positive">
                <CheckCircle2 className="size-4" aria-hidden />
                {result.validation.passed} of {result.validation.cases.length} cases agree
              </span>
            ) : (
              <span className="inline-flex items-center gap-1.5 text-sm font-medium text-negative">
                <XCircle className="size-4" aria-hidden />
                {result.validation.failed} case
                {result.validation.failed === 1 ? "" : "s"} disagree
              </span>
            )}
            <Badge variant="outline">{result.method.lifecycle_label}</Badge>
            <Button variant="outline" size="sm" asChild>
              <a href={api.studioValidationPackUrl(result.method.id)}>
                Download the validation pack
              </a>
            </Button>
            <Button
              size="sm"
              onClick={() => router.push(`/studio/${encodeURIComponent(result.method.id)}`)}
            >
              Open the method
            </Button>
          </div>

          {result.saved && !result.persisted && (
            <p className="mt-3 text-xs text-warning">{result.storage_note}</p>
          )}

          <p className="mt-4 text-xs leading-relaxed text-text-muted">
            The expected results were computed by a second implementation written from the
            methodology in plain Python. It shares no code with the analytical plan, the SQL
            compiler or the query engine — which is what makes agreement between them evidence
            rather than a tautology.
          </p>

          {total && (
            <div className="mt-4 rounded-md border border-border bg-surface-sunken p-4">
              <p className="text-xs text-text-muted">On the twelve fixture cases</p>
              <div className="mt-2 flex flex-wrap gap-6">
                {Object.entries(total.expected).map(([key, want]) => (
                  <div key={key}>
                    <p className="text-[11px] uppercase tracking-wide text-text-muted">{key}</p>
                    <p className="tabular text-lg font-semibold text-text-primary">
                      {formatValue(total.actual?.[key] ?? want)}
                    </p>
                    <p className="text-[11px] text-text-muted">
                      independently: {formatValue(want)}
                    </p>
                  </div>
                ))}
              </div>
            </div>
          )}

          <Table className="mt-5">
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead>Case</TableHead>
                <TableHead>Why it is contentious</TableHead>
                <TableHead>Result</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {result.validation.cases.map((c) => (
                <TableRow key={c.id}>
                  <TableCell className="align-top text-xs font-medium text-text-primary">
                    {c.name}
                  </TableCell>
                  <TableCell className="max-w-xl align-top text-xs text-text-muted">
                    {c.purpose}
                  </TableCell>
                  <TableCell className="align-top">
                    <CaseVerdict passed={c.passed} />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Card>
      )}
    </div>
  );
}

function Step({ n, title }: { n: number; title: string }) {
  return (
    <div className="flex items-center gap-3">
      <span className="tabular flex size-6 items-center justify-center rounded-full bg-surface-sunken text-xs font-semibold text-text-secondary">
        {n}
      </span>
      <h2 className="text-sm font-semibold text-text-primary">{title}</h2>
    </div>
  );
}

function formatValue(value: unknown): string {
  // Two decimals, not three. This renders a preview of a method's sample
  // output, which is a figure a reader reads - it is not a model internal,
  // and three decimals here was the display contract being bypassed by a
  // helper nobody thought of as formatting.
  if (typeof value === "number") {
    return Number.isInteger(value)
      ? value.toLocaleString("en-US")
      : value.toLocaleString("en-US", {
          minimumFractionDigits: 2,
          maximumFractionDigits: 2,
        });
  }
  return value === null || value === undefined ? "—" : String(value);
}
