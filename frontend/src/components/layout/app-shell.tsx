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
 * Whether a session is required is read from the BACKEND, not baked into this
 * build. Two places holding the same setting is two places for it to disagree,
 * and the way they disagree is a login page that never appears in front of a
 * backend refusing every request.
 */
function AuthGate({ children }: { children: React.ReactNode }) {
  const { status, user, loginRequired } = useAuth();

  // Still asking is not the same as "no session needed". Treating it as no
  // would flash the whole application at somebody who has to sign in.
  if (status === "loading" || loginRequired === null) {
    return <div className="min-h-dvh bg-canvas" aria-busy="true" />;
  }
  if (status === "anonymous" && loginRequired) {
    return <LoginScreen />;
  }
  // Signed in, or a deployment that has deliberately switched signing in off.
  void user;
  return <>{children}</>;
}
