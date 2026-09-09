import { Lock, TriangleAlert } from "lucide-react";

import type { AsyncState } from "@/lib/hooks";
import { cn } from "@/lib/utils";

/**
 * A panel that could not be shown, and why.
 *
 * The defect this exists to fix
 * -----------------------------
 * A route crawl across three roles found six screens where a Viewer — a role
 * the permission model correctly refuses — got one of two things. Either a red
 * failure card, which says the product is broken when it is working exactly as
 * designed. Or, worse, nothing at all: `configuration.data?.scenarios ?? []`
 * turned a refusal into an empty dropdown, and the Viewer was left on a page
 * with no scenarios, no configuration, no error and no next step. That is a
 * dead end, and a dead end is a defect whatever the status code behind it.
 *
 * A refusal is not a failure
 * --------------------------
 * They read differently and they are acted on differently. A refusal is
 * addressed by an administrator granting a role; a failure is addressed by
 * trying again or by an engineer. So this renders them differently: a refusal
 * is calm and neutral, a failure is negative. Both name the thing that could
 * not be shown, because "You do not have permission to do this" without a
 * subject is its own small dead end.
 *
 * The sentence in `state.error` is the SERVER's — see backend/api/failures.py
 * and backend/api/permissions.require, which already say which roles the
 * action needs and which role the caller holds. This does not rewrite it.
 */
export function Unavailable({
  state,
  what,
  className,
}: {
  /** The panel's fetch. Renders nothing while loading or once it succeeded. */
  state: Pick<AsyncState<unknown>, "error" | "refused" | "loading">;
  /**
   * What could not be shown, as a noun phrase that completes "… could not be
   * shown": "the scenario configuration", "this lens". Named rather than
   * inferred, so the reader knows which panel on the page is missing.
   */
  what: string;
  className?: string;
}) {
  if (state.loading || !state.error) return null;
  const Icon = state.refused ? Lock : TriangleAlert;
  return (
    <div
      role={state.refused ? "note" : "alert"}
      className={cn(
        "flex items-start gap-3 rounded-lg border p-4 text-[13px] leading-relaxed",
        state.refused
          ? "border-border bg-surface-raised text-text-muted"
          : "border-negative/40 bg-negative-muted text-negative",
        className,
      )}
    >
      <Icon className="mt-0.5 size-4 shrink-0" aria-hidden />
      <div className="space-y-1">
        <p className="font-medium text-text-primary">
          {state.refused
            ? `Your role does not have access to ${what}.`
            : `${what.charAt(0).toUpperCase()}${what.slice(1)} could not be loaded.`}
        </p>
        <p>{state.error}</p>
        {state.refused && (
          <p>
            Nothing on this page is missing because of an error. An
            administrator can grant the role that opens it.
          </p>
        )}
      </div>
    </div>
  );
}
