import { redirect } from "next/navigation";

/**
 * The old Early Warning Signals route.
 *
 * There is one Early Warning workspace now, and Signals is a view inside it.
 * The route is kept so a bookmark, a Cockpit link or a saved message still
 * lands somewhere useful rather than on a 404 — it opens the workspace with
 * the signals view already showing.
 */
export default function EarlyWarningSignalsRedirect() {
  redirect("/early-warning?view=signals");
}
