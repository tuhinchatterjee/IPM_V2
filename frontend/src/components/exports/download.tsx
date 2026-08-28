"use client";

import * as React from "react";
import { AlertTriangle, Check, FileSpreadsheet, Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { captionFor, type DownloadPhase } from "@/lib/downloads";
import { cn } from "@/lib/utils";
import { ApiError, api, type ExportAvailability } from "@/lib/api";

/**
 * The two download buttons, and the one mechanism behind them.
 *
 * §3 is explicit that these must not collapse into one control: the person who
 * wants the numbers and the reviewer who wants the evidence are asking for
 * different files, and a single "Export" that guessed between them would hand
 * each of them the other's.
 *
 *   DOWNLOAD RESULTS           the analysis header, top right
 *   DOWNLOAD FULL CALCULATION  the Trace header, top right, in all four modes
 *
 * Why a fetch and not a link
 * --------------------------
 * A plain `<a download>` cannot send the session cookie or the role header the
 * export endpoints authorise against, and it cannot show a refusal — a 403
 * arriving through a link is a browser error page, not a message inside the
 * product. So the click fetches the bytes, shows "Preparing workbook…" while
 * the server builds them, and saves the blob when it arrives. The interface
 * stays live throughout, which is what §37 actually asks for.
 *
 * The filename is the server's. It sanitised one already; a second opinion
 * here would only be a chance to disagree.
 */

/** How long the tick stays before the button returns to its label. */
const SETTLE_MS = 2600;

export interface DownloadProps {
  runId: number;
  /** The Trace version to export. The latest when omitted. */
  version?: number;
  /** Availability, where the caller already has it. Fetched otherwise. */
  availability?: ExportAvailability | null;
  size?: "sm" | "default";
  variant?: "outline" | "ghost" | "subtle" | "default";
  className?: string;
  /** Hide the label and keep the icon, for a narrow header. */
  compact?: boolean;
}

/**
 * Save a blob the browser has already been handed.
 *
 * The object URL is revoked on the next tick rather than immediately: Safari
 * has not started reading it when the click handler returns, and revoking
 * synchronously produces a download that silently never happens.
 */
function save(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

/**
 * One download button: idle, working, done, failed.
 *
 * A refusal is shown where the button is rather than as a toast that scrolls
 * away — the reader needs to know why THIS is unavailable, next to the thing
 * that is unavailable.
 */
function DownloadButton({
  label,
  tooltip,
  disabledReason,
  fetcher,
  size = "sm",
  variant = "outline",
  className,
  compact = false,
  testId,
}: {
  label: string;
  tooltip: string;
  disabledReason?: string;
  fetcher: () => Promise<{ blob: Blob; filename: string }>;
  size?: "sm" | "default";
  variant?: "outline" | "ghost" | "subtle" | "default";
  className?: string;
  compact?: boolean;
  testId: string;
}) {
  const [phase, setPhase] = React.useState<DownloadPhase>("idle");
  const [problem, setProblem] = React.useState("");
  const alive = React.useRef(true);

  React.useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  const run = React.useCallback(async () => {
    setPhase("working");
    setProblem("");
    try {
      const file = await fetcher();
      save(file.blob, file.filename);
      if (!alive.current) return;
      setPhase("done");
      setTimeout(() => alive.current && setPhase("idle"), SETTLE_MS);
    } catch (error) {
      if (!alive.current) return;
      setPhase("failed");
      setProblem(
        error instanceof ApiError
          ? error.message
          : "The workbook could not be generated.",
      );
    }
  }, [fetcher]);

  const refused = Boolean(disabledReason);
  const busy = phase === "working";

  return (
    <div className={cn("flex flex-col items-end gap-1", className)}>
      <Button
        type="button"
        size={size}
        variant={variant}
        onClick={run}
        disabled={refused || busy}
        title={disabledReason || tooltip}
        aria-label={label}
        data-testid={testId}
        data-phase={phase}
      >
        {busy ? (
          <Loader2 className="animate-spin" aria-hidden />
        ) : phase === "done" ? (
          <Check aria-hidden />
        ) : phase === "failed" ? (
          <AlertTriangle aria-hidden />
        ) : (
          <FileSpreadsheet aria-hidden />
        )}
        {!compact && <span>{captionFor(phase, label)}</span>}
      </Button>

      {refused && (
        <p className="max-w-xs text-right text-[11px] leading-snug text-text-muted">
          {disabledReason}
        </p>
      )}
      {phase === "failed" && problem && (
        <p
          role="status"
          className="max-w-xs text-right text-[11px] leading-snug text-negative"
        >
          {problem}
        </p>
      )}
    </div>
  );
}

/**
 * What this user may download for this run.
 *
 * Fetched once per run so a refusal can be explained in place. It is a
 * courtesy and never the control: the endpoints make the same decision for
 * themselves, so a button that this hook wrongly enabled would still be
 * refused by the server rather than serving a file it should not.
 */
export function useExportAvailability(
  runId: number | null | undefined,
): ExportAvailability | null {
  // The run is stored WITH the offer, and the offer is only returned when the
  // two still match. Holding the offer alone would show the previous
  // analysis's permissions for the moment between switching run and the new
  // answer arriving — briefly, and wrongly, on somebody else's analysis.
  const [loaded, setLoaded] = React.useState<{
    runId: number;
    offer: ExportAvailability;
  } | null>(null);

  React.useEffect(() => {
    if (!runId) return;
    let current = true;
    api
      .exportAvailability(runId)
      .then((offer) => {
        if (current) setLoaded({ runId, offer });
      })
      // A failure here must not remove the buttons: the download itself will
      // report its own refusal, and a silently missing button is the one
      // outcome a reader cannot ask a question about.
      .catch(() => undefined);
    return () => {
      current = false;
    };
  }, [runId]);

  return loaded && loaded.runId === runId ? loaded.offer : null;
}

/** §45. The analysis header's own download, top right. */
export function DownloadResults({
  runId,
  version,
  availability,
  size,
  variant,
  className,
  compact,
}: DownloadProps) {
  const fetched = useExportAvailability(availability === undefined ? runId : null);
  const offer = (availability ?? fetched)?.results;
  const fetcher = React.useCallback(
    () => api.downloadResults(runId, version),
    [runId, version],
  );

  return (
    <DownloadButton
      testId="download-results"
      label={offer?.label ?? "DOWNLOAD RESULTS"}
      tooltip="Download the final analysis result as Excel."
      disabledReason={offer && !offer.allowed ? offer.reason : undefined}
      fetcher={fetcher}
      size={size}
      variant={variant}
      className={className}
      compact={compact}
    />
  );
}

/** §46. The Trace header's own download, present in all four modes. */
export function DownloadCalculation({
  runId,
  version,
  availability,
  size,
  variant,
  className,
  compact,
}: DownloadProps) {
  const fetched = useExportAvailability(availability === undefined ? runId : null);
  const offer = (availability ?? fetched)?.calculation_pack;
  const fetcher = React.useCallback(
    () => api.downloadCalculationPack(runId, version),
    [runId, version],
  );

  return (
    <DownloadButton
      testId="download-calculation"
      label={offer?.label ?? "DOWNLOAD FULL CALCULATION"}
      tooltip={
        "Download the full step-by-step calculation, data profile, joins, " +
        "validations, lineage and final result." +
        (version ? ` Trace version ${version}.` : "")
      }
      disabledReason={offer && !offer.allowed ? offer.reason : undefined}
      fetcher={fetcher}
      size={size}
      variant={variant}
      className={className}
      compact={compact}
    />
  );
}
