"use client";

import * as React from "react";

/**
 * A failure in one tab is a failure in one tab.
 *
 * These panes render a lot of optional server fields, and the cost of getting
 * one wrong was found the hard way: reading `act` off a section's history
 * entry — a field only governed rows carry — threw, and React unmounted the
 * whole application, leaving a page with nothing on it but the navigation.
 *
 * A reader who sees "this tab could not be shown" can go to another tab, tell
 * somebody what they saw, and keep working. A blank page tells them nothing
 * and looks like the product is broken rather than one panel of it.
 *
 * This is a guard, not a licence. It does not excuse a component from
 * handling its own data: every failure it catches is a defect to fix, and it
 * says so on screen rather than hiding it.
 */
export class TabBoundary extends React.Component<
  { children: React.ReactNode; name: string },
  { error: Error | null }
> {
  state: { error: Error | null } = { error: null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidUpdate(previous: { name: string }) {
    // Moving to another tab clears the failure, so one bad pane does not
    // poison the rest of the dashboard for the whole visit.
    if (previous.name !== this.props.name && this.state.error) {
      this.setState({ error: null });
    }
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div
        className="rounded-lg border border-negative/40 bg-negative-muted p-4"
        data-testid="playbook-tab-failed"
        role="alert"
      >
        <p className="text-sm font-semibold text-negative">
          This tab could not be shown.
        </p>
        <p className="mt-1 text-[11px] leading-relaxed text-text-primary">
          The rest of the dashboard is unaffected — the other tabs, the status
          cards and the readiness panel all still work. This is a defect worth
          reporting, with what follows:
        </p>
        <code className="mt-2 block overflow-x-auto rounded bg-surface-sunken p-2 text-[10px] text-text-secondary">
          {this.state.error.message}
        </code>
      </div>
    );
  }
}
