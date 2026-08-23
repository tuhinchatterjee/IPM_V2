import { cn } from "@/lib/utils";

/**
 * Skeleton — a placeholder occupying the exact space the real content will.
 *
 * Used rather than a spinner so the layout does not jump when data arrives.
 * A page that reflows on load reads as unfinished.
 */
function Skeleton({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn("animate-pulse rounded-md bg-surface-sunken", className)}
      {...props}
    />
  );
}

export { Skeleton };
