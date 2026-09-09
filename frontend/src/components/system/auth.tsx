"use client";

import * as React from "react";

import { api, onSessionExpired, type SignedInUser } from "@/lib/api";

/**
 * Who is signed in.
 *
 * One fetch on load, shared by everything that needs a name or a role. The
 * greeting reads it, the role switcher defers to it, and the admin screens use
 * it to decide what to render — though the backend decides what is *allowed*,
 * because hiding a button is not access control.
 *
 * `status` distinguishes three states that look alike and are not: still asking
 * ("loading"), asked and nobody is signed in ("anonymous"), and signed in. A
 * screen that treats "loading" as "anonymous" flashes a login page at somebody
 * who is already signed in.
 */

export type AuthStatus = "loading" | "anonymous" | "authenticated";

interface AuthState {
  status: AuthStatus;
  user: SignedInUser | null;
  /**
   * Whether this backend insists on a session.
   *
   * Read from the backend, not from a build-time flag, so the interface cannot
   * disagree with the thing actually enforcing it. Null while still asking —
   * which is not the same as false, and treating it as false would flash the
   * whole application at somebody who has to sign in.
   */
  loginRequired: boolean | null;
  signIn: (username: string, password: string) => Promise<SignedInUser>;
  signOut: () => Promise<void>;
  refresh: () => Promise<void>;
}

const AuthContext = React.createContext<AuthState>({
  status: "loading",
  user: null,
  loginRequired: null,
  signIn: async () => {
    throw new Error("No AuthProvider");
  },
  signOut: async () => {},
  refresh: async () => {},
});

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [status, setStatus] = React.useState<AuthStatus>("loading");
  const [user, setUser] = React.useState<SignedInUser | null>(null);
  const [loginRequired, setLoginRequired] = React.useState<boolean | null>(null);

  const [nonce, setNonce] = React.useState(0);

  /** Ask again. Used after signing in or out, and on first load. */
  const refresh = React.useCallback(async () => {
    setNonce((n) => n + 1);
  }, []);

  React.useEffect(() => {
    let cancelled = false;

    // Declared inside the effect and awaited, so no setState runs
    // synchronously in the effect body — the state lands in a promise
    // callback, which is the subscription-shaped pattern effects are for.
    async function load() {
      try {
        const body = await api.me();
        if (cancelled) return;
        setUser(body.user);
        setLoginRequired(Boolean(body.login_required));
        setStatus(body.authenticated ? "authenticated" : "anonymous");
      } catch {
        // No backend, or no database. Nothing can be signed in to, and there
        // is nothing to sign in with, so the login page would be a dead end —
        // the backend-status banner explains the real problem instead.
        if (cancelled) return;
        setUser(null);
        setLoginRequired(false);
        setStatus("anonymous");
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, [nonce]);

  // The backend's own word that this session no longer exists, from whatever
  // call happened to notice it first — a Lens save, an ask, a preview, any
  // mutating request anywhere in the product. Reacting immediately rather
  // than waiting for the next `/auth/me` poll (there isn't one) is the fix
  // for the exact defect this exists to close: the top navigation asserting
  // "signed in" after the backend has already stopped agreeing, because the
  // one place that remembered "signed in" was never told otherwise.
  //
  // Set directly rather than routed through `refresh()`: a full refetch
  // would ask the same dead session's cookie whether it is still dead, which
  // it reliably is, so it is not more correct, only slower. `AuthGate` reads
  // `status` on every render, so this one assignment is what swaps the whole
  // application over to the real sign-in screen — nothing Lens-specific, and
  // nothing that had to know Lens exists.
  React.useEffect(
    () =>
      onSessionExpired(() => {
        setUser(null);
        setStatus("anonymous");
      }),
    [],
  );

  const signIn = React.useCallback(async (username: string, password: string) => {
    const body = await api.signIn(username, password);
    setUser(body.user);
    setStatus("authenticated");
    return body.user;
  }, []);

  const signOut = React.useCallback(async () => {
    await api.signOut();
    setUser(null);
    setStatus("anonymous");
  }, []);

  const value = React.useMemo(
    () => ({ status, user, loginRequired, signIn, signOut, refresh }),
    [status, user, loginRequired, signIn, signOut, refresh],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  return React.useContext(AuthContext);
}

/**
 * The name to greet somebody by.
 *
 * Falls back to nothing rather than to "there": a greeting with a placeholder
 * name reads worse than a greeting without one, and the Cockpit is built to
 * handle both.
 */
export function useGreetingName(): string {
  const { user } = useAuth();
  return user?.greeting_name ?? "";
}
