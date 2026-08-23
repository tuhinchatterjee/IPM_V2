import { Badge } from "@/components/ui/badge";
import { STATUS_LABEL, type CapabilityStatus } from "@/lib/navigation";

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
}: {
  title: string;
  description?: string;
  status?: CapabilityStatus;
  phase?: string;
  actions?: React.ReactNode;
}) {
  return (
    <div className="mb-8 flex flex-wrap items-start justify-between gap-4">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2.5">
          <h1 className="text-xl font-semibold tracking-tight text-text-primary">
            {title}
          </h1>
          {status && (
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
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}
