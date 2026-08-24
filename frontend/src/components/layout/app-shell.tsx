"use client";

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
 * The content column is capped at 1120px and generously padded. A wide screen
 * is not a reason to stretch a paragraph to 1600px; it is a reason to leave
 * space around what matters.
 */
export function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <NavProvider>
      <div className="flex h-dvh flex-col overflow-hidden">
        <Header />
        <div className="flex min-h-0 flex-1">
          <Sidebar />
          <main className="min-w-0 flex-1 overflow-y-auto">
            <div className="mx-auto max-w-[1120px] px-10 py-9">
              <ErrorBoundary area="This page">{children}</ErrorBoundary>
            </div>
          </main>
        </div>
      </div>
    </NavProvider>
  );
}
