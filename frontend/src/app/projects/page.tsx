import { CapabilityPlaceholder } from "@/components/layout/capability-placeholder";

export default function Page() {
  return (
    <CapabilityPlaceholder
      href="/projects"
      willDo={[
        "Create and name a body of work, and reopen it later exactly as it was",
        "Hold chats, investigations, saved analyses, traces, scenarios, members and comments",
      ]}
      builtOn={["projects, chats and chat_messages tables"]}
    />
  );
}
