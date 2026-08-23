import { Badge } from "@/components/ui/badge";
import { NAV_ITEMS, STATUS_LABEL, type CapabilityStatus } from "@/lib/navigation";

const STATUS_VARIANT: Record<
  CapabilityStatus,
  "positive" | "accent" | "warning" | "default"
> = {
  live: "positive",
  partial: "accent",
  preview: "warning",
  planned: "default",
};

/**
 * Standard page heading.
 *
 * Set editorially rather than as a toolbar: a small tracked eyebrow naming the
 * section, the title at display size, and one line of standfirst beneath it,
 * closed with a rule. Every screen in IPM opens the same way, which is what
 * makes a fourteen-screen product feel like one document rather than fourteen
 * applications.
 *
 * The status badge is not decoration. The product rule is that a placeholder is
 * never presented as production functionality, so every page states what it
 * actually is.
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
    eyebrow ??
    NAV_ITEMS.find((item) => item.label === title)?.group ??
    "Credit Portfolio Intelligence";

  return (
    <header className="mb-8 border-b border-border pb-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="text-[11px] font-medium uppercase tracking-[0.18em] text-text-muted">
            {section}
          </p>
          <div className="mt-2 flex flex-wrap items-center gap-2.5">
            <h1 className="text-[26px] font-semibold leading-tight tracking-tight text-text-primary">
              {title}
            </h1>
            {status && status !== "live" && (
              <Badge variant={STATUS_VARIANT[status]}>{STATUS_LABEL[status]}</Badge>
            )}
            {phase && status !== "live" && (
              <span className="text-xs text-text-muted">{phase}</span>
            )}
          </div>
          {description && (
            <p className="mt-2 max-w-2xl text-sm leading-relaxed text-text-secondary">
              {description}
            </p>
          )}
        </div>
        {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
      </div>
    </header>
  );
}
