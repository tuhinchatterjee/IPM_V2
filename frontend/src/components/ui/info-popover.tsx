"use client";

import * as React from "react";
import { Info, X } from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * The small "i" next to a screen title.
 *
 * CreditProbe used to open every screen with a line of standfirst explaining what the
 * screen was for. Fourteen screens of that is fourteen paragraphs a CRO has read
 * once and then reads past forever — it makes a serious product look like it is
 * still introducing itself.
 *
 * So the explanation moves in here. It is one click away, it is the same
 * explanation, and the screen opens with its title and its content instead.
 */

export function InfoPopover({
  title,
  children,
  className,
}: {
  /** Heading inside the panel. Defaults to "About this screen". */
  title?: string;
  children: React.ReactNode;
  className?: string;
}) {
  const [open, setOpen] = React.useState(false);
  const container = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: MouseEvent) => {
      if (!container.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  return (
    <div ref={container} className={cn("relative inline-flex", className)}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-label={open ? "Hide the explanation" : "What is this screen for?"}
        className={cn(
          "inline-flex size-5 items-center justify-center rounded-full border transition-colors",
          open
            ? "border-accent text-accent"
            : "border-border text-text-muted hover:border-border-strong hover:text-text-secondary",
        )}
      >
        <Info className="size-3" aria-hidden />
      </button>

      {open && (
        <div
          role="dialog"
          aria-label={title ?? "About this screen"}
          className="absolute left-0 top-7 z-30 w-[22rem] max-w-[calc(100vw-3rem)] rounded-lg border border-border bg-surface-raised p-4 shadow-lg"
        >
          <div className="flex items-start justify-between gap-3">
            <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-text-muted">
              {title ?? "About this screen"}
            </p>
            <button
              type="button"
              onClick={() => setOpen(false)}
              className="-mr-1 -mt-1 rounded p-1 text-text-muted transition-colors hover:bg-surface-hover hover:text-text-primary"
              aria-label="Close"
            >
              <X className="size-3" aria-hidden />
            </button>
          </div>
          <div className="mt-2 space-y-2 text-xs leading-relaxed text-text-secondary">
            {children}
          </div>
        </div>
      )}
    </div>
  );
}
