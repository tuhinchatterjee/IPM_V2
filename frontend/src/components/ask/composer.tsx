"use client";

import * as React from "react";
import { CornerDownLeft, Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { InfoPopover } from "@/components/ui/info-popover";
import { cn } from "@/lib/utils";

/**
 * The prompt composer.
 *
 * It is the largest single element on the Cockpit on purpose. IPM's claim is
 * that the conversation is the product and the dashboard is what you see while
 * you decide what to ask — a composer tucked into a sidebar would contradict
 * that on first sight.
 *
 * Restraint is the design here. A handful of suggestions, not a menu; and the
 * statement of what IPM will and will not do sits behind an "i" rather than
 * under the box, because it is a thing you read once.
 */
export function Composer({
  value,
  onChange,
  onSubmit,
  busy,
  suggestions,
  autoFocus,
  modeNote,
  readOnlyNote,
  placeholder = "What deteriorated this period?",
}: {
  value: string;
  onChange: (value: string) => void;
  onSubmit: (question: string) => void;
  busy?: boolean;
  suggestions: { question: string; note: string }[];
  autoFocus?: boolean;
  modeNote?: string;
  /** Set when the acting role may not run an analysis. */
  readOnlyNote?: string;
  placeholder?: string;
}) {
  const ref = React.useRef<HTMLTextAreaElement>(null);

  React.useEffect(() => {
    if (autoFocus) ref.current?.focus();
  }, [autoFocus]);

  return (
    <div>
      <div
        className={cn(
          "overflow-hidden rounded-xl border border-border-strong bg-surface shadow-sm transition-shadow",
          "focus-within:border-accent focus-within:shadow-md",
        )}
      >
        <div className="relative">
          <textarea
            ref={ref}
            value={value}
            onChange={(e) => onChange(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                if (value.trim() && !busy) onSubmit(value.trim());
              }
            }}
            rows={3}
            disabled={busy}
            placeholder={readOnlyNote ?? placeholder}
            aria-label="Ask IPM a question about the portfolio"
            className="w-full resize-none bg-transparent px-5 py-4 pr-32 text-base leading-relaxed text-text-primary placeholder:text-text-muted focus:outline-none disabled:opacity-60"
          />
          <div className="absolute bottom-3.5 right-4 flex items-center gap-2">
            <span className="hidden text-[11px] text-text-muted sm:inline">Enter to ask</span>
            <Button
              size="sm"
              disabled={!value.trim() || busy}
              onClick={() => onSubmit(value.trim())}
            >
              {busy ? <Loader2 className="animate-spin" aria-hidden /> : <CornerDownLeft aria-hidden />}
              Ask
            </Button>
          </div>
        </div>

        {suggestions.length > 0 && (
          <div className="flex flex-wrap items-center gap-1.5 border-t border-border bg-surface-sunken px-4 py-3">
            {suggestions.slice(0, 4).map((s) => (
              <button
                key={s.question}
                type="button"
                title={s.note}
                disabled={busy}
                onClick={() => {
                  onChange(s.question);
                  onSubmit(s.question);
                }}
                className="rounded-full border border-border bg-surface px-3 py-1 text-xs text-text-secondary transition-colors hover:border-accent hover:text-accent disabled:opacity-50"
              >
                {s.question}
              </button>
            ))}
          </div>
        )}
      </div>

      <div className="mt-2.5 flex items-center gap-2">
        <InfoPopover title="How IPM answers">
          <p>
            IPM chooses which certified analyses to run and writes the findings. It never
            calculates a figure itself, never writes a query, and never invents a number.
          </p>
          <p>
            Every answer carries a Trace showing the data, the filters, the engine function
            and its version — so any figure can be followed back to the rows behind it.
          </p>
          {modeNote && <p className="text-text-muted">{modeNote}</p>}
        </InfoPopover>
        <span className="text-[11px] text-text-muted">
          {readOnlyNote ?? "Every answer carries a Trace."}
        </span>
      </div>
    </div>
  );
}

/** "Good afternoon" — by the reader's clock, not the server's. */
export function useGreeting(): string {
  // The time of day is external state: the server cannot know it, and reading it
  // during render would make the server and client markup disagree. useSyncExternalStore
  // is the React 19 idiom for exactly this — the server snapshot is neutral, and
  // the real greeting appears on hydration without a cascading render.
  return React.useSyncExternalStore(subscribeToNothing, clientGreeting, () => "Good day");
}

/** The clock does not notify anyone; the greeting is read once, on hydration. */
function subscribeToNothing(): () => void {
  return () => {};
}

function clientGreeting(): string {
  const hour = new Date().getHours();
  return hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";
}
