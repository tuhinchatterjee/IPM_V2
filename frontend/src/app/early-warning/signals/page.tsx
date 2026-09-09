import { redirect } from "next/navigation";
/**
 * Retired route (implementation plan Section 16 — "one canonical Early
 * Warning nav item"). `/early-warning/signals` used to be a second,
 * separately-navigable Early Warning product (a rule-based taxonomy with
 * no score, distinct from the fitted Forward Risk Signal at
 * `/early-warning`). Both are superseded by the consolidated Early
 * Warning V2 product now served at `/early-warning` itself, so any
 * bookmark to this URL is sent there rather than left as a dead link.
 *
 * The original screen's code is preserved (not deleted) at
 * `../_legacy-signals/page.tsx`, a Next.js private folder excluded from
 * routing.
 */
export default function LegacySignalsRedirect() {
  redirect("/early-warning");}
