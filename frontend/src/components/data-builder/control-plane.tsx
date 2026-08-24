"use client";

import * as React from "react";
import { CircleAlert, Database, ShieldCheck, Sparkles } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { InfoPopover } from "@/components/ui/info-popover";
import { Skeleton } from "@/components/ui/skeleton";
import { api, type AssistantAnswer } from "@/lib/api";
import { useAsync } from "@/lib/hooks";

/**
 * What is actually powering CreditProbe right now.
 *
 * The single most important thing Data Builder can tell a bank, and the one it
 * must never be vague about: for each governed purpose, which dataset answers
 * it, and whether that dataset is the bank's own data or CreditProbe's demonstration
 * book. A screen that leaves this ambiguous produces credible-looking figures
 * about a portfolio that does not exist.
 */
export function ControlPlanePanel() {
  const [nonce, setNonce] = React.useState(0);
  const plane = useAsync(() => api.controlPlane(), [nonce]);
  const [syncing, setSyncing] = React.useState(false);

  const sync = async () => {
    setSyncing(true);
    try {
      await api.syncBundled();
      setNonce((n) => n + 1);
    } finally {
      setSyncing(false);
    }
  };

  if (plane.loading) return <Skeleton className="h-40 w-full" />;
  if (plane.error) {
    return <Card className="border-negative/40 p-4 text-sm text-negative">{plane.error}</Card>;
  }
  if (!plane.data) return null;

  const { purposes, using_demo_data: usingDemo, unresolved } = plane.data;
  const unregistered = purposes.every((p) => !p.dataset);

  return (
    <section>
      <div className="mb-3 flex items-center justify-between gap-4">
        <div className="flex items-center gap-2">
          <h2 className="text-sm font-semibold tracking-tight text-text-primary">
            What is powering CreditProbe
          </h2>
          <InfoPopover title="Governed purposes">
            <p>
              A certified analysis does not read a file. It asks for a governed{" "}
              <em>purpose</em> — &ldquo;the position of every credit facility&rdquo; — and CreditProbe
              resolves that to whichever dataset is marked authoritative for it.
            </p>
            <p>
              That is what lets your own data replace CreditProbe&rsquo;s demonstration book without
              anyone changing a line of analysis code. Every read records which dataset it
              actually used on the Trace.
            </p>
          </InfoPopover>
        </div>
        {unregistered && (
          <Button variant="outline" size="sm" disabled={syncing} onClick={() => void sync()}>
            {syncing ? "Registering" : "Register bundled datasets"}
          </Button>
        )}
      </div>

      {usingDemo && (
        <Card className="mb-3 flex items-start gap-2.5 border-warning/30 bg-warning-muted p-4">
          <CircleAlert className="mt-0.5 size-4 shrink-0 text-warning" aria-hidden />
          <p className="text-xs leading-relaxed text-warning">
            At least one governed purpose is being answered by CreditProbe&rsquo;s demonstration
            data. Every figure produced from it describes a synthetic book. Onboard your
            own data and mark it authoritative to replace it.
          </p>
        </Card>
      )}

      <Card className="divide-y divide-border">
        {purposes.map((purpose) => (
          <div key={purpose.purpose} className="flex items-start gap-3 px-5 py-3.5">
            <Database className="mt-0.5 size-4 shrink-0 text-text-muted" aria-hidden />
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium text-text-primary">
                {purpose.purpose.replace(/_/g, " ")}
              </p>
              <p className="mt-0.5 text-xs leading-relaxed text-text-muted">
                {purpose.description}
              </p>
              {purpose.message && <p className="mt-1 text-xs text-warning">{purpose.message}</p>}
              {purpose.alternatives.length > 0 && (
                <p className="mt-1 text-[11px] text-text-muted">
                  Also serving it: {purpose.alternatives.join(", ")}
                </p>
              )}
            </div>
            <div className="shrink-0 text-right">
              {purpose.dataset ? (
                <>
                  <p className="font-mono text-xs text-text-secondary">{purpose.dataset}</p>
                  <Badge variant={purpose.is_demo ? "warning" : "positive"} className="mt-1">
                    {purpose.is_demo ? "Demonstration data" : "Client data"}
                  </Badge>
                </>
              ) : (
                <Badge variant="negative">Unresolved</Badge>
              )}
            </div>
          </div>
        ))}
        {purposes.length === 0 && (
          <p className="px-5 py-6 text-center text-xs text-text-muted">
            No governed purposes are registered yet.
          </p>
        )}
      </Card>

      {unresolved.length > 0 && (
        <p className="mt-2 flex items-start gap-1.5 text-xs text-text-muted">
          <ShieldCheck className="mt-0.5 size-3 shrink-0" aria-hidden />
          {unresolved.length} purpose{unresolved.length === 1 ? "" : "s"} cannot be answered.
          Analyses that need them refuse to run rather than substitute something plausible.
        </p>
      )}
    </section>
  );
}

/**
 * Ask about the model.
 *
 * Reads governed metadata only. No portfolio data, no figures, and it changes
 * nothing. A portfolio question is sent to Ask CreditProbe, where it runs a certified
 * analysis and produces a Trace.
 */
export function MetadataAssistant({
  scope = "data",
  suggestions,
}: {
  scope?: "data" | "engine";
  suggestions?: string[];
}) {
  const [question, setQuestion] = React.useState("");
  const [answer, setAnswer] = React.useState<AssistantAnswer | null>(null);
  const [busy, setBusy] = React.useState(false);

  const ask = async (text: string) => {
    const trimmed = text.trim();
    if (!trimmed) return;
    setBusy(true);
    setQuestion(trimmed);
    try {
      setAnswer(
        scope === "data"
          ? await api.askDataBuilder(trimmed)
          : await api.askEngineBuilder(trimmed),
      );
    } catch (e) {
      setAnswer({
        text: e instanceof Error ? e.message : "CreditProbe could not answer that.",
        references: [],
        source: "lookup",
        unanswered_reason: "error",
        rule: "",
      });
    } finally {
      setBusy(false);
    }
  };

  const defaults =
    suggestions ??
    (scope === "data"
      ? ["What does ead mean?", "Which datasets share a common field?"]
      : ["What does stage_migration do?", "What is ecl_movement?"]);

  return (
    <Card className="p-5">
      <div className="flex items-center gap-2">
        <Sparkles className="size-3.5 text-accent" aria-hidden />
        <h2 className="text-sm font-semibold tracking-tight text-text-primary">
          Ask about {scope === "data" ? "the data model" : "the analysis library"}
        </h2>
        <InfoPopover title="What this can see">
          <p>
            Governed metadata only:{" "}
            {scope === "data"
              ? "domain, dataset and field definitions"
              : "the registered analysis contracts"}
            . No portfolio data, no figures, and it changes nothing.
          </p>
          <p>
            For a portfolio figure, ask CreditProbe on the Cockpit — that runs a certified analysis
            and produces a Trace.
          </p>
        </InfoPopover>
      </div>

      <div className="mt-3 flex gap-2">
        <input
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") void ask(question);
          }}
          placeholder={defaults[0]}
          aria-label="Ask about the governed metadata"
          className="min-w-0 flex-1 rounded-md border border-border bg-surface px-3 py-2 text-sm text-text-primary placeholder:text-text-muted focus:border-accent focus:outline-none"
        />
        <Button size="sm" disabled={busy || !question.trim()} onClick={() => void ask(question)}>
          Ask
        </Button>
      </div>

      <div className="mt-2 flex flex-wrap gap-1.5">
        {defaults.map((s) => (
          <button
            key={s}
            type="button"
            onClick={() => void ask(s)}
            className="rounded-full border border-border px-2.5 py-0.5 text-[11px] text-text-secondary transition-colors hover:border-accent hover:text-accent"
          >
            {s}
          </button>
        ))}
      </div>

      {answer && (
        <div className="mt-4 border-t border-border pt-3">
          <p className="whitespace-pre-line text-sm leading-relaxed text-text-primary">
            {answer.text}
          </p>
          {answer.rule && (
            <p className="mt-2 text-[11px] leading-relaxed text-text-muted">{answer.rule}</p>
          )}
        </div>
      )}
    </Card>
  );
}
