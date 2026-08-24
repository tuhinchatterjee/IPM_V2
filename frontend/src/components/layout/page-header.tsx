import { InfoPopover } from "@/components/ui/info-popover";
import { NAV_ITEMS, STATUS_LABEL, type CapabilityStatus } from "@/lib/navigation";
import { cn } from "@/lib/utils";

/**
 * Standard page heading.
 *
 * Deliberately quiet: a small tracked eyebrow naming the section, the title at
 * 24px, and nothing else unless the screen genuinely needs it. Every screen in
 * CreditProbe AI opens the same way, which is what makes a fifteen-screen
 * product feel like one document rather than fifteen applications.
 *
 * Three things it does NOT do, each on purpose:
 *
 *   - no paragraph under the title. The explanation lives behind the "i".
 *     Someone who needs it clicks once; everyone else gets a screen that opens
 *     on its content.
 *   - no rule under the header. Whitespace separates as well as a line does and
 *     leaves the page quieter.
 *   - no status badge for a finished screen. A green "Live" pill on every page
 *     is noise; only an unfinished screen has something to declare, and it says
 *     it in small text rather than in a coloured box.
 */
export function PageHeader({
  title,
  description,
  status,
  phase,
  actions,
  eyebrow,
}: {
  title: string;
  description?: string;
  status?: CapabilityStatus;
  phase?: string;
  actions?: React.ReactNode;
  /** Overrides the section name, which is otherwise taken from navigation. */
  eyebrow?: string;
}) {
  const section =
    eyebrow ?? NAV_ITEMS.find((item) => item.label === title)?.group ?? "CreditProbe AI";
  const unfinished = status && status !== "live";

  return (
    <header className="mb-7">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="text-[10px] font-medium uppercase tracking-[0.16em] text-text-muted">
            {section}
          </p>
          <div className="mt-1.5 flex flex-wrap items-center gap-2">
            <h1 className="text-[24px] font-semibold leading-tight tracking-tight text-text-primary">
              {title}
            </h1>
            {(description || phase) && (
              <InfoPopover title={title}>
                {description && <p>{description}</p>}
                {phase && <p className="text-text-muted">{phase}</p>}
              </InfoPopover>
            )}
            {unfinished && (
              <span
                className={cn(
                  "text-[11px]",
                  status === "preview" ? "text-warning" : "text-text-muted",
                )}
                title={phase || undefined}
              >
                {STATUS_LABEL[status]}
              </span>
            )}
          </div>
        </div>
        {actions && <div className="flex shrink-0 items-center gap-1.5">{actions}</div>}
      </div>
    </header>
  );
}
