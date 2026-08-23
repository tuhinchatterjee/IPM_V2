import { CapabilityPlaceholder } from "@/components/layout/capability-placeholder";

export default function Page() {
  return (
    <CapabilityPlaceholder
      href="/workflow"
      willDo={[
        "Review and approval of engine certification, dataset publication, scenario approval and document sign-off",
        "States, assignees, comments and an immutable decision record",
      ]}
      builtOn={[
        "workflow_items and workflow_events tables — the event log is append-only, because a workflow's history is evidence",
      ]}
    />
  );
}
