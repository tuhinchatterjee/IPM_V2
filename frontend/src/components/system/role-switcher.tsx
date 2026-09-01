"use client";

import * as React from "react";
import { LogOut, ShieldCheck } from "lucide-react";

import { useAuth } from "@/components/system/auth";
import { setActiveRole, type Role } from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * The acting role.
 *
 * When somebody is SIGNED IN, their role comes from their user record and
 * cannot be changed here. The backend enforces the same thing: a session always
 * beats the header, so a Viewer who sends `X-IPM-Role: ADMIN` is refused.
 *
 * When nobody is signed in — a local run with `REQUIRE_LOGIN` off — the role is
 * chosen here and sent as a header. That is what lets one person demonstrate
 * the permission model as four different people, and it is genuinely
 * demonstrable rather than cosmetic: a Viewer cannot publish a dataset because
 * the backend refuses, not because the button is hidden.
 */

const ROLES: { id: Role; label: string; note: string }[] = [
  { id: "ADMIN", label: "Administrator", note: "Full access, including certification" },
  { id: "DATA_STEWARD", label: "Data Steward", note: "Can create, edit and publish datasets" },
  { id: "ANALYST", label: "Analyst", note: "Can run analyses; cannot change data" },
  { id: "VIEWER", label: "Viewer", note: "Read only" },
];

const STORAGE_KEY = "ipm.role";
const DEFAULT_ROLE: Role = "ADMIN";

/* -----------------------------------------------------------------------------
   The stored role lives in localStorage, not in React, so it is read with
   useSyncExternalStore rather than copied into state inside an effect. No
   cascading render on mount, and a change in another tab is picked up.
   -------------------------------------------------------------------------- */

const listeners = new Set<() => void>();

function subscribe(onStoreChange: () => void): () => void {
  listeners.add(onStoreChange);
  window.addEventListener("storage", onStoreChange);
  return () => {
    listeners.delete(onStoreChange);
    window.removeEventListener("storage", onStoreChange);
  };
}

function getSnapshot(): Role {
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY) as Role | null;
    return stored && ROLES.some((r) => r.id === stored) ? stored : DEFAULT_ROLE;
  } catch {
    return DEFAULT_ROLE;
  }
}

function getServerSnapshot(): Role {
  return DEFAULT_ROLE;
}

const RoleContext = React.createContext<{ role: Role; setRole: (r: Role) => void }>({
  role: DEFAULT_ROLE,
  setRole: () => {},
});

export function RoleProvider({ children }: { children: React.ReactNode }) {
  const stored = React.useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
  const { user } = useAuth();
  // A real session decides the role. The stored demonstration choice applies
  // only when nobody is signed in.
  const role = user?.role ?? stored;

  // Keep the module-level value the API client reads in step with the store.
  // This touches an external system and sets no state, so it introduces no
  // cascading render.
  React.useEffect(() => {
    setActiveRole(role);
  }, [role]);

  const setRole = React.useCallback((next: Role) => {
    try {
      window.localStorage.setItem(STORAGE_KEY, next);
    } catch {
      /* not remembering the choice must not prevent making it */
    }
    setActiveRole(next);
    for (const listener of listeners) listener();
  }, []);

  const value = React.useMemo(() => ({ role, setRole }), [role, setRole]);
  return <RoleContext.Provider value={value}>{children}</RoleContext.Provider>;
}

export function useRole() {
  return React.useContext(RoleContext);
}

/** Whether the current role may change data. Mirrors the backend's rule. */
export function useCanEditData(): boolean {
  const { role } = useRole();
  return role === "ADMIN" || role === "DATA_STEWARD";
}

/** Whether the current role may execute an analysis. */
export function useCanRunAnalysis(): boolean {
  const { role } = useRole();
  return role !== "VIEWER";
}

export function RoleSwitcher({ className }: { className?: string }) {
  const { role, setRole } = useRole();
  const { user, signOut } = useAuth();

  // Signed in: the role is a fact about the account, not a control. Showing a
  // dropdown here would imply it can be changed, and the backend would refuse.
  if (user) {
    const detail = ROLES.find((r) => r.id === role);
    return (
      <div className={cn("flex items-center gap-1.5", className)}>
        <span
          className="meta hidden text-text-muted sm:inline"
          title={detail?.note}
        >
          {detail?.label ?? role}
        </span>
        <button
          type="button"
          onClick={() => void signOut()}
          title={`Signed in as ${user.display_name} — sign out`}
          className="flex size-8 items-center justify-center rounded-md text-text-muted transition-colors hover:bg-surface-hover hover:text-text-primary"
        >
          <LogOut className="size-[15px]" aria-hidden />
          <span className="sr-only">Sign out</span>
        </button>
      </div>
    );
  }

  return (
    <label className={cn("flex items-center gap-1.5", className)} title="Acting role — sent to the API on every request">
      <ShieldCheck className="size-3.5 text-text-muted" aria-hidden />
      <span className="sr-only">Acting role</span>
      <select
        value={role}
        onChange={(e) => setRole(e.target.value as Role)}
        className="cursor-pointer rounded-md border border-border bg-surface py-1 pl-1.5 pr-6 text-xs text-text-secondary transition-colors hover:bg-surface-hover focus:border-accent focus:outline-none"
      >
        {ROLES.map((r) => (
          <option key={r.id} value={r.id}>
            {r.label}
          </option>
        ))}
      </select>
    </label>
  );
}

/** Shown wherever the interface is read-only because of the acting role. */
export function ReadOnlyNotice({ action = "change this" }: { action?: string }) {
  const { role } = useRole();
  const detail = ROLES.find((r) => r.id === role);
  return (
    <div className="flex items-start gap-2 rounded-md border border-warning/30 bg-warning-muted px-3 py-2 text-xs text-warning">
      <ShieldCheck className="mt-0.5 size-3.5 shrink-0" aria-hidden />
      <span>
        Read-only. You are acting as <strong>{detail?.label ?? role}</strong> — {detail?.note}. Only
        an Administrator or Data Steward can {action}.
      </span>
    </div>
  );
}

export { ROLES };
