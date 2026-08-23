import { Skeleton } from "@/components/ui/skeleton";

/**
 * Shown while a route segment loads.
 *
 * Skeletons rather than a spinner, sized to the content they replace, so the
 * page does not jump when the real content arrives.
 */
export default function Loading() {
  return (
    <div className="space-y-8">
      <div className="space-y-3">
        <Skeleton className="h-7 w-64" />
        <Skeleton className="h-4 w-full max-w-2xl" />
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        {[0, 1, 2, 3].map((i) => (
          <Skeleton key={i} className="h-32 w-full" />
        ))}
      </div>
    </div>
  );
}
