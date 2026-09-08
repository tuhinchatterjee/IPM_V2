"use client";

import * as React from "react";
import { X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/**
 * The modal this design system did not have.
 *
 * Four places already hand-roll the same overlay — the share dialog, the risk
 * case drawer, the AI power panel and the fullscreen chart — and each one
 * re-implements the focus handling slightly differently, which is how a dialog
 * ends up trapping the keyboard in one place and not in another. Playbook needs
 * a fifth, so it is worth extracting the one.
 *
 * What it does that a `<div>` does not: it labels itself for a screen reader,
 * moves focus in on open and back to whatever opened it on close, keeps Tab
 * inside while it is open, and closes on Escape and on a click outside. Those
 * are not decoration — a picker that loses the keyboard is a picker that cannot
 * be used without a mouse.
 */
export function Dialog({
  open,
  onClose,
  title,
  description,
  children,
  footer,
  size = "lg",
  className,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  description?: string;
  children: React.ReactNode;
  footer?: React.ReactNode;
  size?: "md" | "lg" | "xl";
  className?: string;
}) {
  const panel = React.useRef<HTMLDivElement>(null);
  const restoreTo = React.useRef<HTMLElement | null>(null);
  const titleId = React.useId();
  const descriptionId = React.useId();

  React.useEffect(() => {
    if (!open) return;
    restoreTo.current = document.activeElement as HTMLElement | null;
    const node = panel.current;
    // Focus the panel itself rather than its first control: reading the title
    // before being dropped into a search box is the difference between knowing
    // where you are and guessing.
    node?.focus();

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.stopPropagation();
        onClose();
        return;
      }
      if (event.key !== "Tab" || !node) return;
      const focusable = node.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), textarea, input, select, [tabindex]:not([tabindex="-1"])',
      );
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener("keydown", onKeyDown, true);
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKeyDown, true);
      document.body.style.overflow = previousOverflow;
      restoreTo.current?.focus?.();
    };
  }, [open, onClose]);

  if (!open) return null;

  const width =
    size === "xl" ? "max-w-5xl" : size === "md" ? "max-w-lg" : "max-w-3xl";

  return (
    <div
      className="fixed inset-0 z-50 overflow-y-auto bg-canvas/70 p-4 backdrop-blur-sm sm:p-8"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={description ? descriptionId : undefined}
        tabIndex={-1}
        className={cn(
          "mx-auto flex max-h-[calc(100vh-4rem)] w-full flex-col rounded-xl border border-border bg-surface shadow-overlay outline-none",
          width,
          className,
        )}
      >
        <div className="flex items-start justify-between gap-4 border-b border-border px-5 py-4">
          <div className="min-w-0">
            <h2
              id={titleId}
              className="text-sm font-semibold text-text-primary"
            >
              {title}
            </h2>
            {description && (
              <p
                id={descriptionId}
                className="mt-1 text-xs leading-relaxed text-text-muted"
              >
                {description}
              </p>
            )}
          </div>
          <Button
            variant="ghost"
            size="icon"
            onClick={onClose}
            aria-label="Close"
          >
            <X aria-hidden />
          </Button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">{children}</div>

        {footer && (
          <div className="flex items-center justify-end gap-2 border-t border-border px-5 py-3">
            {footer}
          </div>
        )}
      </div>
    </div>
  );
}
