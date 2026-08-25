"use client";

import Link from "next/link";
import * as React from "react";
import {
  ArrowLeft,
  CheckCircle2,
  CircleAlert,
  Inbox,
  Loader2,
  Upload,
} from "lucide-react";

import { PageHeader } from "@/components/layout/page-header";
import { useCanEditData } from "@/components/system/role-switcher";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ApiError, api, type FieldDrift, type InboxItem } from "@/lib/api";
import { useAsync } from "@/lib/hooks";

/**
 * The Data Inbox.
 *
 * Onboarding is a one-off; arrival is forever. What this screen owes a steward
 * is not another upload wizard but an answer to "is this file the same as the
 * last one, and if it is not, does anybody know" — so a file that published
 * itself has a row here exactly like one that was stopped, and both carry the
 * reason.
 *
 * Held files come first, because they are the only ones anybody has to act on.
 */
export default function DataInboxPage() {
  const [nonce, setNonce] = React.useState(0);
  const canEdit = useCanEditData();
  const inbox = useAsync(() => api.inbox(), [nonce]);
  const refresh = React.useCallback(() => setNonce((n) => n + 1), []);

  const items = inbox.data?.items ?? [];
  const counts = inbox.data?.counts ?? {};
  const attention = items.filter((i) => i.status === "held" || i.status === "unmatched");
  const settled = items.filter((i) => i.status !== "held" && i.status !== "unmatched");

  return (
    <div className="space-y-6">
      <PageHeader
        title="Data Inbox"
        eyebrow="Data Builder"
        description="Every file that arrived, published or held, with what changed since the last one and why it was decided that way. A file publishes itself only when it matched a dataset confidently, the schema is unchanged, and nothing material drifted."
        status="live"
        actions={
          <Button variant="ghost" asChild>
            <Link href="/data-builder">
              <ArrowLeft aria-hidden />
              Data Builder
            </Link>
          </Button>
        }
      />

      <div className="grid gap-3 sm:grid-cols-4">
        <Tile label="Needs attention" value={counts.needs_attention} tone="warning" />
        <Tile label="Published" value={counts.published} tone="positive" />
        <Tile label="Rejected" value={counts.rejected} />
        <Tile label="Arrivals in total" value={counts.total} />
      </div>

      {canEdit && <Arrival onDone={refresh} />}

      {inbox.loading && !inbox.data ? (
        <Skeleton className="h-40 w-full" />
      ) : inbox.error ? (
        <Card className="border-negative/40 p-4 text-sm text-negative">{inbox.error}</Card>
      ) : items.length === 0 ? (
        <Card className="p-8 text-center text-sm text-text-muted">
          Nothing has arrived yet. Drop a file above and CreditProbe will profile it, work
          out which dataset it belongs to, and compare it against the last one accepted.
        </Card>
      ) : (
        <>
          {attention.length > 0 && (
            <section>
              <h2 className="meta mb-2.5 text-text-muted">
                Waiting for somebody ({attention.length})
              </h2>
              <div className="space-y-4">
                {attention.map((item) => (
                  <ArrivalCard
                    key={item.id}
                    item={item}
                    canEdit={canEdit}
                    onResolved={refresh}
                  />
                ))}
              </div>
            </section>
          )}

          {settled.length > 0 && (
            <section>
              <h2 className="meta mb-2.5 text-text-muted">Settled ({settled.length})</h2>
              <Card>
                <Table>
                  <TableHeader>
                    <TableRow className="hover:bg-transparent">
                      <TableHead>File</TableHead>
                      <TableHead>Dataset</TableHead>
                      <TableHead>Outcome</TableHead>
                      <TableHead>Why</TableHead>
                      <TableHead className="text-right">Rows</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {settled.map((item) => (
                      <TableRow key={item.id}>
                        <TableCell className="font-mono text-xs">{item.filename}</TableCell>
                        <TableCell className="text-xs">{item.dataset || "—"}</TableCell>
                        <TableCell>
                          <StatusBadge item={item} />
                        </TableCell>
                        <TableCell className="max-w-xl text-xs text-text-muted">
                          {item.resolution_note || item.decision_reason}
                        </TableCell>
                        <TableCell className="tabular text-right text-xs">
                          {item.row_count.toLocaleString()}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </Card>
            </section>
          )}
        </>
      )}
    </div>
  );
}

/* ------------------------------------------------------------- a new arrival */

function Arrival({ onDone }: { onDone: () => void }) {
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");
  const [result, setResult] = React.useState<InboxItem | null>(null);

  async function send(file: File, publish: boolean) {
    setBusy(true);
    setError("");
    try {
      setResult(await api.receiveFile(file, { publish }));
      onDone();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "The file could not be read.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="p-5">
      <div className="flex flex-wrap items-center gap-3">
        <Inbox className="size-4 text-text-muted" aria-hidden />
        <p className="text-sm font-medium text-text-primary">A file arrives</p>
        {busy && <Loader2 className="size-4 animate-spin text-text-muted" aria-hidden />}
      </div>
      <p className="mt-1 text-xs leading-relaxed text-text-muted">
        CreditProbe profiles it, works out which dataset it belongs to from its columns
        rather than its name, and compares it field by field against the last file that
        dataset accepted.
      </p>
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <Input
          type="file"
          accept=".csv,.xlsx,.xls,.parquet"
          className="max-w-sm"
          aria-label="File"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) void send(file, true);
            e.target.value = "";
          }}
        />
        <label className="flex cursor-pointer items-center gap-1.5 text-xs text-text-muted">
          <Upload className="size-3.5" aria-hidden />
          <span>or</span>
          <input
            type="file"
            className="hidden"
            accept=".csv,.xlsx,.xls,.parquet"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) void send(file, false);
              e.target.value = "";
            }}
          />
          <span className="underline">assess it without acting on it</span>
        </label>
      </div>
      {error && <p className="mt-3 text-xs text-negative">{error}</p>}
      {result && (
        <p className="mt-3 text-xs text-text-secondary">
          <span className="font-medium">{result.filename}</span> — {result.status_label}.{" "}
          {result.decision_reason}
        </p>
      )}
    </Card>
  );
}

/* ------------------------------------------------------ one held or unmatched */

function ArrivalCard({
  item,
  canEdit,
  onResolved,
}: {
  item: InboxItem;
  canEdit: boolean;
  onResolved: () => void;
}) {
  const [note, setNote] = React.useState("");
  const [dataset, setDataset] = React.useState(item.dataset);
  const [busy, setBusy] = React.useState("");
  const [error, setError] = React.useState("");

  const drift = "findings" in item.drift ? item.drift : null;
  const findings = drift?.findings ?? [];

  async function resolve(action: "publish" | "reject") {
    setBusy(action);
    setError("");
    try {
      await api.resolveInboxItem(item.id, action, note, dataset);
      onResolved();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "That did not work.");
    } finally {
      setBusy("");
    }
  }

  return (
    <Card className="overflow-hidden">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-border px-5 py-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="font-mono text-sm font-medium text-text-primary">
              {item.filename}
            </h3>
            <StatusBadge item={item} />
            {item.dataset && (
              <Badge variant="outline">
                {item.dataset} · {Math.round(item.match_confidence * 100)}% match
              </Badge>
            )}
          </div>
          <p className="mt-1 max-w-3xl text-xs leading-relaxed text-text-secondary">
            {item.decision_reason}
          </p>
          {item.match_reason && (
            <p className="mt-0.5 text-[11px] text-text-muted">{item.match_reason}</p>
          )}
        </div>
        <p className="tabular shrink-0 text-xs text-text-muted">
          {item.row_count.toLocaleString()} rows · {item.column_count} columns
        </p>
      </div>

      <div className="px-5 py-4">
        {drift?.first_load ? (
          <p className="text-xs text-text-muted">
            First file for this dataset. There is nothing to compare it against, so
            nothing here is drift — which is exactly why a person looks at it.
          </p>
        ) : findings.length === 0 ? (
          <p className="flex items-center gap-1.5 text-xs text-positive">
            <CheckCircle2 className="size-3.5" aria-hidden />
            Nothing changed since the last accepted file.
          </p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead>Field</TableHead>
                <TableHead>What changed</TableHead>
                <TableHead>Why it matters</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {findings.map((finding, index) => (
                <TableRow key={`${finding.field}-${finding.kind}-${index}`}>
                  <TableCell className="align-top">
                    <SeverityMark finding={finding} />
                  </TableCell>
                  <TableCell className="max-w-md align-top text-xs text-text-primary">
                    {finding.detail}
                  </TableCell>
                  <TableCell className="max-w-lg align-top text-xs text-text-muted">
                    {finding.because}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </div>

      {canEdit && (
        <div className="flex flex-wrap items-center gap-2 border-t border-border bg-surface-sunken px-5 py-3">
          {!item.dataset && (
            <Input
              value={dataset}
              onChange={(e) => setDataset(e.target.value)}
              placeholder="Which dataset?"
              className="max-w-48"
              aria-label="Dataset"
            />
          )}
          <Input
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="Why are you publishing this?"
            className="max-w-md"
            aria-label="Reason"
          />
          <Button size="sm" onClick={() => resolve("publish")} disabled={busy !== ""}>
            {busy === "publish" && <Loader2 className="animate-spin" aria-hidden />}
            Publish anyway
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => resolve("reject")}
            disabled={busy !== ""}
          >
            Reject
          </Button>
          <span className="text-[11px] text-text-muted">
            Whichever you choose is recorded against your name, and the drift above stays
            on the record.
          </span>
          {error && <span className="text-xs text-negative">{error}</span>}
        </div>
      )}
    </Card>
  );
}

/* ------------------------------------------------------------------- bits */

function StatusBadge({ item }: { item: InboxItem }) {
  const variant =
    item.status === "published"
      ? "positive"
      : item.status === "rejected"
        ? "default"
        : item.status === "unmatched"
          ? "warning"
          : "warning";
  return <Badge variant={variant}>{item.status_label}</Badge>;
}

function SeverityMark({ finding }: { finding: FieldDrift }) {
  const tone =
    finding.severity === "blocking"
      ? "text-negative"
      : finding.severity === "material"
        ? "text-warning"
        : "text-text-muted";
  return (
    <span className="flex items-start gap-1.5">
      <CircleAlert className={`mt-0.5 size-3.5 shrink-0 ${tone}`} aria-hidden />
      <span className="font-mono text-xs text-text-primary">{finding.field || "file"}</span>
    </span>
  );
}

function Tile({
  label,
  value,
  tone,
}: {
  label: string;
  value?: number;
  tone?: "warning" | "positive";
}) {
  const colour =
    tone === "warning" && (value ?? 0) > 0
      ? "text-warning"
      : tone === "positive"
        ? "text-text-primary"
        : "text-text-primary";
  return (
    <Card className="p-4">
      <p className="text-xs text-text-muted">{label}</p>
      <p className={`tabular mt-1 text-2xl font-semibold ${colour}`}>{value ?? 0}</p>
    </Card>
  );
}
