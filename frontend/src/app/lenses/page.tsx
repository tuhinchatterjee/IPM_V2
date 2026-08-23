import { CapabilityPlaceholder } from "@/components/layout/capability-placeholder";

export default function Page() {
  return (
    <CapabilityPlaceholder
      href="/lenses"
      willDo={[
        "Saved, composable executive views with fixed filters — \"CRO Monthly\", \"IFRS 9 Review\"",
        "Each tile is a governed engine result, with its own Trace button",
      ]}
    />
  );
}
