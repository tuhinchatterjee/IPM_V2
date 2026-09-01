import type { LucideIcon } from "lucide-react";

import { cn } from "@/lib/utils";

/** A calm empty state. Says what is missing and what to do about it. */
export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
  className,
}: {
  icon?: LucideIcon;
  title: string;
  description?: string;
  action?: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center gap-3 rounded-lg border border-dashed border-border px-6 py-12 text-center",
        className,
      )}
    >
      {Icon && <Icon className="size-6 text-text-muted" aria-hidden />}
      <div>
        <p className="text-sm font-medium text-text-primary">{title}</p>
        {description && (
          <p className="mx-auto mt-1 max-w-md text-xs leading-relaxed text-text-muted">
            {description}
          </p>
        )}
      </div>
      {action}
    </div>
  );
}
