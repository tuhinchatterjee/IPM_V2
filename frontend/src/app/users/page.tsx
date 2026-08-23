import { CapabilityPlaceholder } from "@/components/layout/capability-placeholder";

export default function Page() {
  return (
    <CapabilityPlaceholder
      href="/users"
      willDo={[
        "Users, teams, roles and permissions",
        "Access enforced at three levels: capability, object and data",
      ]}
      builtOn={[
        "Existing authentication with Argon2id password hashing",
        "teams, team_members and user_preferences tables",
        "Field-level sensitivity classification already in the data catalogue",
      ]}
    />
  );
}
