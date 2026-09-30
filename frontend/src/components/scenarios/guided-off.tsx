/** Said plainly when the Guided Workspace flag is off, rather than a blank page. */
export function GuidedOff({ what }: { what: string }) {
  return (
    <p className="rounded-lg border border-border bg-surface p-4 text-sm text-text-secondary" data-testid="guided-off">
      {what} is part of the Guided Risk Workspace, which is not enabled in this deployment
      (NEXT_PUBLIC_GUIDED_WORKSPACE=1 and COCKPIT_V4_GUIDED_WORKSPACE=1).
    </p>
  );
}
