"use client";

import { useAuth } from "@/components/system/auth";
import { LoginScreen } from "@/components/system/login";
import { ErrorBoundary } from "@/components/system/error-boundary";

import { Header } from "./header";
import { NavProvider } from "./nav-state";
import { Sidebar } from "./sidebar";

/**
 * The application frame: header, sidebar, scrolling content area.
 *
 * The shell is the part that must never break, so the content area is wrapped in
 * its own error boundary. A failing page leaves the navigation usable instead of
 * blanking the window.
 *
 * The content column is capped at 1200px and generously padded. A wide screen
 * is not a reason to stretch a paragraph to 1600px; it is a reason to leave
 * space around what matters.
 */
export function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <NavProvider>
      <AuthGate>
        <div className="flex h-dvh flex-col overflow-hidden">
          <Header />
          <div className="flex min-h-0 flex-1">
            <Sidebar />
            <main className="min-w-0 flex-1 overflow-y-auto">
              <div className="mx-auto max-w-[1200px] px-9 py-8">
                <ErrorBoundary area="This page">{children}</ErrorBoundary>
              </div>
            </main>
          </div>
        </div>
      </AuthGate>
    </NavProvider>
  );
}

/**
 * Show the application, or the login screen, or neither.
 *
 * "Neither" is the case that matters: while the session is still being checked,
 * rendering the login screen would flash it at somebody who is already signed
 * in, and rendering the application would flash it at somebody who is not.
 * A blank canvas for a few hundred milliseconds is the honest state.
 *
 * When the backend does not require a login — a local run — anonymous callers
 * go straight through, because the product must still be usable with
 * `docker compose up` and nothing else.
 */
function AuthGate({ children }: { children: React.ReactNode }) {
  const { status, user } = useAuth();

  if (status === "loading") {
    return <div className="min-h-dvh bg-canvas" aria-busy="true" />;
  }
  if (status === "anonymous" && requiresLogin()) {
    return <LoginScreen />;
  }
  // Signed in, or a local run where signing in is optional.
  void user;
  return <>{children}</>;
}

/**
 * Whether this deployment insists on a session.
 *
 * Baked in at build time so the decision is the deployment's, not the browser's.
 * Unset means "no" — which keeps `docker compose up` working out of the box, and
 * is the setting a real deployment changes first.
 */
function requiresLogin(): boolean {
  return process.env.NEXT_PUBLIC_REQUIRE_LOGIN === "true";
}
