import { ErrorBoundary } from "@/components/system/error-boundary";

import { Header } from "./header";
import { Sidebar } from "./sidebar";

/**
 * The application frame: header, sidebar, scrolling content area.
 *
 * The shell is the part that must never break, so the content area is wrapped in
 * its own error boundary. A failing page leaves the navigation usable instead of
 * blanking the window.
 */
export function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex h-dvh flex-col overflow-hidden">
      <Header />
      <div className="flex min-h-0 flex-1">
        <Sidebar />
        <main className="min-w-0 flex-1 overflow-y-auto">
          <div className="mx-auto max-w-6xl px-6 py-8">
            <ErrorBoundary area="This page">{children}</ErrorBoundary>
          </div>
        </main>
      </div>
    </div>
  );
}
