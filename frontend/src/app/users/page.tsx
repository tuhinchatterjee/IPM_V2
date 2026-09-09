"use client";

import * as React from "react";
import { KeyRound, Loader2, Plus, ShieldCheck, UserX } from "lucide-react";

import { PageHeader } from "@/components/layout/page-header";
import { useRole } from "@/components/system/role-switcher";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { api, type Role, type RoleDescription, type UserRecord } from "@/lib/api";
import { useAsync } from "@/lib/hooks";
import { cn } from "@/lib/utils";

/**
 * User administration.
 *
 * Administrator only, and the backend says so too — a Viewer who finds this URL
 * is refused by the API, not by the absence of a link.
 *
 * The role each person holds is the most consequential field on this screen, so
 * it carries its own one-line summary of what it grants rather than making
 * somebody look it up.
 */
export default function UsersPage() {
  const { role, settled } = useRole();
  const [refresh, setRefresh] = React.useState(0);
  const directory = useAsync(() => api.users(), [refresh], {
    // See the Model Lab: the role is Administrator until hydration settles,
    // so gating on it alone fires an admin-only request for every caller.
    enabled: settled && role === "ADMIN",
  });
  const [adding, setAdding] = React.useState(false);

  if (role !== "ADMIN") {
    return (
      <div className="space-y-6">
        <PageHeader
          title="Users"
          description="Accounts, roles and access."
          status="live"
        />
        <EmptyState
          icon={ShieldCheck}
          title="User administration needs the Administrator role"
          description="Adding accounts and assigning roles changes who can do what across the whole product, so it sits behind the narrowest permission."
        />
      </div>
    );
  }

  return (
    <div className="space-y-7">
      <PageHeader
        title="Users"
        description="Accounts, roles and access. Roles are enforced by the API, not by which buttons are visible — a Viewer who finds an administrator URL is refused by the server."
        status="live"
        actions={
          <Button size="sm" onClick={() => setAdding((a) => !a)}>
            <Plus aria-hidden />
            Add user
          </Button>
        }
      />

      {adding && directory.data && (
        <NewUser
          roles={directory.data.roles}
          onDone={() => {
            setAdding(false);
            setRefresh((n) => n + 1);
          }}
          onCancel={() => setAdding(false)}
        />
      )}

      {directory.loading && <Skeleton className="h-64 w-full" />}
      {directory.error && (
        <Card className="border-negative/40 p-4 text-sm text-negative">
          {directory.error}
        </Card>
      )}

      {directory.data && (
        <>
          <Card className="divide-y divide-border">
            <div className="meta flex items-center gap-3 px-4 py-2 text-text-muted">
              <span className="min-w-0 flex-1">Person</span>
              <span className="hidden w-44 shrink-0 sm:block">Role</span>
              <span className="hidden w-36 shrink-0 lg:block">Team</span>
              <span className="w-24 shrink-0 text-right">Last seen</span>
              <span className="w-[104px] shrink-0" />
            </div>
            {directory.data.users.map((user) => (
              <UserRow
                key={user.id}
                user={user}
                roles={directory.data!.roles}
                onChange={() => setRefresh((n) => n + 1)}
              />
            ))}
          </Card>

          <section>
            <h2 className="meta mb-3 text-text-muted">What each role grants</h2>
            <div className="grid gap-3 md:grid-cols-2">
              {directory.data.roles.map((role) => (
                <Card key={role.role} className="p-4">
                  <p className="display text-sm font-semibold text-text-primary">
                    {role.label}
                  </p>
                  <p className="prose-ai mt-1 text-xs text-text-muted">{role.can}</p>
                </Card>
              ))}
            </div>
          </section>
        </>
      )}
    </div>
  );
}

const ROLE_VARIANT: Record<string, "accent" | "info" | "outline" | "default"> = {
  ADMIN: "accent",
  DATA_STEWARD: "info",
  ANALYST: "outline",
  VIEWER: "default",
};

function UserRow({
  user,
  roles,
  onChange,
}: {
  user: UserRecord;
  roles: RoleDescription[];
  onChange: () => void;
}) {
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [resetting, setResetting] = React.useState(false);
  const [password, setPassword] = React.useState("");

  async function run(fn: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
      onChange();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={cn("px-4 py-3", !user.is_active && "opacity-55")}>
      <div className="flex flex-wrap items-center gap-3">
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium text-text-primary">
            {user.display_name}
            {!user.is_active && (
              <span className="ml-2 text-xs text-text-muted">deactivated</span>
            )}
          </p>
          <p className="truncate text-[11px] text-text-secondary">
            {/* Job title first: it is what tells a colleague whether this is
                the person who owns the shipping book. The role is the select
                beside it, and the username is an identifier rather than a
                description. */}
            {user.job_title || "—"}
            {user.department && ` · ${user.department}`}
          </p>
          <p className="mono truncate text-[11px] text-text-muted">
            {user.username}
            {user.email && ` · ${user.email}`}
          </p>
        </div>

        <div className="hidden w-44 shrink-0 sm:block">
          <select
            value={user.role}
            disabled={busy}
            aria-label={`Role for ${user.display_name}`}
            onChange={(e) =>
              void run(() => api.updateUser(user.id, { role: e.target.value as Role }))
            }
            className="w-full cursor-pointer rounded-md border border-border bg-surface px-2 py-1 text-xs text-text-secondary transition-colors hover:bg-surface-hover focus:border-accent focus:outline-none"
          >
            {roles.map((role) => (
              <option key={role.role} value={role.role}>
                {role.label}
              </option>
            ))}
          </select>
        </div>

        <span className="hidden w-36 shrink-0 truncate text-xs text-text-muted lg:block">
          {user.team || "—"}
        </span>
        <span className="mono w-24 shrink-0 text-right text-[11px] text-text-muted">
          {user.last_login_at ? when(user.last_login_at) : "never"}
        </span>

        <div className="flex w-[104px] shrink-0 items-center justify-end gap-0.5">
          <Button
            variant="ghost"
            size="sm"
            disabled={busy}
            title="Set a new password"
            onClick={() => setResetting((r) => !r)}
          >
            <KeyRound aria-hidden />
            <span className="sr-only">Set password</span>
          </Button>
          <Button
            variant="ghost"
            size="sm"
            disabled={busy}
            title={user.is_active ? "Deactivate" : "Reactivate"}
            onClick={() =>
              void run(() => api.updateUser(user.id, { isActive: !user.is_active }))
            }
          >
            {busy ? (
              <Loader2 className="animate-spin" aria-hidden />
            ) : (
              <UserX aria-hidden />
            )}
            <span className="sr-only">
              {user.is_active ? "Deactivate" : "Reactivate"}
            </span>
          </Button>
        </div>
      </div>

      <div className="mt-1 hidden sm:hidden">
        <Badge variant={ROLE_VARIANT[user.role] ?? "outline"}>{user.role}</Badge>
      </div>

      {resetting && (
        <div className="mt-2.5 flex flex-wrap items-center gap-2">
          <Input
            type="password"
            value={password}
            placeholder="New password (at least 8 characters)"
            onChange={(e) => setPassword(e.target.value)}
            className="w-64"
          />
          <Button
            size="sm"
            disabled={busy || password.length < 8}
            onClick={() =>
              void run(async () => {
                await api.setUserPassword(user.id, password);
                setPassword("");
                setResetting(false);
              })
            }
          >
            Set password
          </Button>
          <Button variant="ghost" size="sm" onClick={() => setResetting(false)}>
            Cancel
          </Button>
        </div>
      )}

      {error && <p className="mt-2 text-xs text-negative">{error}</p>}
    </div>
  );
}

function NewUser({
  roles,
  onDone,
  onCancel,
}: {
  roles: RoleDescription[];
  onDone: () => void;
  onCancel: () => void;
}) {
  const [form, setForm] = React.useState({
    username: "",
    password: "",
    firstName: "",
    lastName: "",
    email: "",
    team: "",
    jobTitle: "",
    department: "",
    role: "ANALYST" as Role,
  });
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const chosen = roles.find((r) => r.role === form.role);

  function set(key: keyof typeof form, value: string) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  async function create() {
    setBusy(true);
    setError(null);
    try {
      await api.createUser(form);
      onDone();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  }

  return (
    <Card className="space-y-4 p-5">
      <div className="grid gap-3 md:grid-cols-2">
        <Field label="First name">
          <Input value={form.firstName} onChange={(e) => set("firstName", e.target.value)} />
        </Field>
        <Field label="Last name">
          <Input value={form.lastName} onChange={(e) => set("lastName", e.target.value)} />
        </Field>
        <Field label="Username">
          <Input
            value={form.username}
            placeholder="omar.nasser"
            onChange={(e) => set("username", e.target.value)}
          />
        </Field>
        <Field label="Email">
          <Input
            value={form.email}
            placeholder="omar.nasser@bank.com"
            onChange={(e) => set("email", e.target.value)}
          />
        </Field>
        <Field label="Job title">
          <Input
            value={form.jobTitle}
            placeholder="Corporate Credit Manager"
            onChange={(e) => set("jobTitle", e.target.value)}
          />
        </Field>
        <Field label="Department">
          <Input
            value={form.department}
            placeholder="Credit Risk"
            onChange={(e) => set("department", e.target.value)}
          />
        </Field>
        <Field label="Team">
          <Input
            value={form.team}
            placeholder="Portfolio Management"
            onChange={(e) => set("team", e.target.value)}
          />
        </Field>
        <Field label="Password">
          <Input
            type="password"
            value={form.password}
            placeholder="At least 8 characters"
            onChange={(e) => set("password", e.target.value)}
          />
        </Field>
      </div>

      <div>
        <label htmlFor="new-user-role" className="meta mb-1.5 block text-text-muted">
          Role
        </label>
        <select
          id="new-user-role"
          value={form.role}
          onChange={(e) => set("role", e.target.value)}
          className="h-9 w-full max-w-xs rounded-md border border-border bg-surface px-3 text-sm text-text-primary focus:border-accent focus:outline-none"
        >
          {roles.map((role) => (
            <option key={role.role} value={role.role}>
              {role.label}
            </option>
          ))}
        </select>
        {chosen && (
          <p className="prose-ai mt-1.5 max-w-xl text-xs text-text-muted">
            {chosen.can}
          </p>
        )}
      </div>

      {error && <p className="text-xs text-negative">{error}</p>}

      <div className="flex items-center gap-2">
        <Button
          size="sm"
          onClick={create}
          disabled={busy || form.username.length < 2 || form.password.length < 8}
        >
          {busy && <Loader2 className="animate-spin" aria-hidden />}
          Create account
        </Button>
        <Button variant="ghost" size="sm" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </Card>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="meta mb-1.5 block text-text-muted">{label}</span>
      {children}
    </label>
  );
}

function when(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}
