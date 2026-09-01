import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

/**
 * Badge — status and classification.
 *
 * The status variants map to the semantic tokens, which in credit risk carry
 * meaning: positive/warning/negative are never used decoratively.
 */
const badgeVariants = cva(
  "inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs font-medium",
  {
    variants: {
      variant: {
        default: "border-border bg-surface-sunken text-text-secondary",
        outline: "border-border-strong bg-transparent text-text-secondary",
        accent: "border-transparent bg-accent-muted text-accent",
        positive: "border-transparent bg-positive-muted text-positive",
        warning: "border-transparent bg-warning-muted text-warning",
        negative: "border-transparent bg-negative-muted text-negative",
        info: "border-transparent bg-info-muted text-info",
      },
    },
    defaultVariants: { variant: "default" },
  },
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />;
}

export { Badge, badgeVariants };
