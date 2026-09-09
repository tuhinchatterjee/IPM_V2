"use client";

import * as React from "react";
import Link from "next/link";
import { BookUp, Check } from "lucide-react";

import { Button } from "@/components/ui/button";
import { api, type PbExportRequest } from "@/lib/api";
import { cn } from "@/lib/utils";

type Phase = "idle" | "working" | "done" | "duplicate" | "failed";

/**
 * Export to Playbook.
 *
 * The sibling of `DownloadResults` in this directory, and it copies that
 * component's discipline deliberately: one control, a four-phase state machine,
 * a `data-testid` so browser acceptance can find it, and an error that renders
 * inside the product rather than as a browser dialog.
 *
 * Two behaviours §5 asks for are visible here. A duplicate export says so
 * plainly instead of pretending to have created something — pressing the button
 * twice is a normal thing to do and lying about it would put two identical
 * cards in the library. And an export that fails can be retried, because a
 * failed export must not leave a control that has gone quiet.
 */
export function ExportToPlaybook({
  build,
  label = "Export to Playbook",
  variant = "ghost",
  compact = false,
  className,
  disabled = false,
  disabledReason = "",
}: {
  /** Built lazily, so the snapshot is what is on screen when the click happens. */
  build: () => PbExportRequest;
  label?: string;
  variant?: "ghost" | "outline" | "default";
  compact?: boolean;
  className?: string;
  disabled?: boolean;
  disabledReason?: string;
}) {
  const [phase, setPhase] = React.useState<Phase>("idle");
  const [detail, setDetail] = React.useState("");

  const run = async () => {
    setPhase("working");
    setDetail("");
    try {
      const result = await api.exportToPlaybook(build());
      setPhase(result.duplicate ? "duplicate" : "done");
      setDetail(result.message);
    } catch (error) {
      setPhase("failed");
      setDetail(error instanceof Error ? error.message : String(error));
    }
  };

  const caption =
    phase === "working"
      ? "Exporting…"
      : phase === "done"
        ? "In Playbook"
        : phase === "duplicate"
          ? "Already in Playbook"
          : phase === "failed"
            ? "Export failed — retry"
            : label;

  return (
    <span className={cn("inline-flex flex-col items-start gap-1", className)}>
      <Button
        type="button"
        variant={variant}
        size={compact ? "sm" : "default"}
        onClick={run}
        disabled={disabled || phase === "working"}
        title={disabled ? disabledReason : undefined}
        data-testid="export-to-playbook"
        data-phase={phase}
      >
        {phase === "done" || phase === "duplicate" ? (
          <Check aria-hidden />
        ) : (
          <BookUp aria-hidden />
        )}
        {caption}
      </Button>
      {disabled && disabledReason && (
        <span className="text-[11px] text-text-muted">{disabledReason}</span>
      )}
      {phase === "failed" && detail && (
        <span className="text-[11px] text-negative">{detail}</span>
      )}
      {(phase === "done" || phase === "duplicate") && (
        <Link
          href="/playbook"
          className="text-[11px] text-accent underline underline-offset-2"
        >
          Open Playbook
        </Link>
      )}
    </span>
  );
}
