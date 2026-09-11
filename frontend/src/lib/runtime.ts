/**
 * Which backend this build is talking to, and what that backend serves.
 *
 * Dependency-free on purpose: `lib/api.ts` imports it, and so does the test
 * runner, which strips types from `.ts` and cannot resolve the `@/` alias
 * through a module graph.
 */

/**
 * The paths an isolated Cockpit V4 runtime actually serves.
 *
 * Everything else in the API client belongs to the main CreditProbe backend,
 * which a V4 instance does not start. Calling one of them there produces a
 * 404 — noise in the API log, an error state on a widget, and a page nobody
 * can test a Cockpit in.
 */
export const V4_SERVED_PREFIXES = ["/health", "/cockpit-v4/"];

/** Is this build running as a Cockpit V4 runtime? */
export function cockpitV4Runtime(): boolean {
  return Boolean(process.env.NEXT_PUBLIC_COCKPIT_V4_API?.trim());
}

/**
 * Would this path reach a backend that exists in the current runtime?
 *
 * Decided on the PATH, before any request is made. Catching a 404 afterwards
 * still sends the request, still fills the API log, and still shows the
 * widget an error — which is the behaviour this replaces.
 */
export function servedByCurrentRuntime(path: string): boolean {
  if (!cockpitV4Runtime()) return true;
  return V4_SERVED_PREFIXES.some((prefix) => path.startsWith(prefix));
}
