import { CapabilityPlaceholder } from "@/components/layout/capability-placeholder";

export default function Page() {
  return (
    <CapabilityPlaceholder
      href="/detect"
      willDo={[
        "Rank emerging problems before they are delinquent",
        "SICR triggers, rating downgrades, covenant headroom erosion, utilisation spikes, DPD entry",
        "Explain why each facility was flagged, and what changed",
      ]}
      builtOn={[
        "Governed fields for SICR trigger, covenant headroom, downgrade probability, DPD and severity",
      ]}
    />
  );
}
