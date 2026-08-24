"use client";

import * as React from "react";

import { api, type SignedInUser } from "@/lib/api";

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
  signIn: (username: string, password: string) => Promise<SignedInUser>;
  signOut: () => Promise<void>;
  refresh: () => Promise<void>;
}

const AuthContext = React.createContext<AuthState>({
  status: "loading",
  user: null,
  signIn: async () => {
    throw new Error("No AuthProvider");
  },
  signOut: async () => {},
  refresh: async () => {},
});

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [status, setStatus] = React.useState<AuthStatus>("loading");
  const [user, setUser] = React.useState<SignedInUser | null>(null);

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
        setStatus(body.authenticated ? "authenticated" : "anonymous");
      } catch {
        // No backend, or no database. The product still runs unauthenticated
        // in local development, so this is a state rather than an error.
        if (cancelled) return;
        setUser(null);
        setStatus("anonymous");
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, [nonce]);

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
    () => ({ status, user, signIn, signOut, refresh }),
    [status, user, signIn, signOut, refresh],
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
