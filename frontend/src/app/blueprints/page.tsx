import { CapabilityPlaceholder } from "@/components/layout/capability-placeholder";

export default function Page() {
  return (
    <CapabilityPlaceholder
      href="/blueprints"
      willDo={[
        "Capture a proven investigation as a reusable, parameterised template",
        "Re-run it next month, on another portfolio, or by another user, producing a comparable result",
      ]}
    />
  );
}
