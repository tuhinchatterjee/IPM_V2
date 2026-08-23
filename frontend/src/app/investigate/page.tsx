import { CapabilityPlaceholder } from "@/components/layout/capability-placeholder";

export default function Page() {
  return (
    <CapabilityPlaceholder
      href="/investigate"
      willDo={[
        "Decompose a movement into its drivers — which sectors, which borrowers, how much each contributed",
        "Persist the work as a named, shareable investigation inside a project",
        "Keep every analysis in it permanently linked to its Trace",
      ]}
      builtOn={[
        "PostgreSQL tables for projects, chats, analysis runs and trace versions",
      ]}
    />
  );
}
