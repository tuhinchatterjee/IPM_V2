"use client";

import * as React from "react";
import { Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useAuth } from "@/components/system/auth";

/**
 * Signing in.
 *
 * One card, centred, on the canvas — not a marketing page. Somebody arriving
 * here wants to be somewhere else in four seconds, and every element that is not
 * the two fields and the button is in their way.
 *
 * The wordmark is the only decoration, and it earns its place by telling a
 * person who has three internal tools open which one this is.
 */
export function LoginScreen() {
  const { signIn } = useAuth();
  const [username, setUsername] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!username.trim() || !password || busy) return;
    setBusy(true);
    setError(null);
    try {
      await signIn(username.trim(), password);
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "That username or password is not right.",
      );
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-dvh items-center justify-center bg-canvas px-6">
      <div className="w-full max-w-[340px]">
        <div className="mb-9 text-center">
          <span className="display text-[19px] font-semibold tracking-[0.01em] text-text-primary">
            CreditProbe<span className="ml-1.5 text-accent">AI</span>
          </span>
          <p className="meta mt-2.5 text-text-muted">
            Credit Portfolio Intelligence
          </p>
        </div>

        <form onSubmit={submit} className="space-y-3">
          <div>
            <label htmlFor="username" className="meta mb-1.5 block text-text-muted">
              Username or email
            </label>
            <input
              id="username"
              autoFocus
              autoComplete="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="h-10 w-full rounded-md border border-border bg-surface px-3 text-sm text-text-primary transition-colors placeholder:text-text-muted focus:border-accent focus:outline-none"
            />
          </div>

          <div>
            <label htmlFor="password" className="meta mb-1.5 block text-text-muted">
              Password
            </label>
            <input
              id="password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="h-10 w-full rounded-md border border-border bg-surface px-3 text-sm text-text-primary transition-colors focus:border-accent focus:outline-none"
            />
          </div>

          {error && (
            <p className="text-xs leading-relaxed text-negative" role="alert">
              {error}
            </p>
          )}

          <Button
            type="submit"
            className="h-10 w-full"
            disabled={busy || !username.trim() || !password}
          >
            {busy && <Loader2 className="animate-spin" aria-hidden />}
            Sign in
          </Button>
        </form>

        <p className="mt-8 text-center text-[11px] leading-relaxed text-text-muted">
          Demonstration deployment. All portfolio data is synthetic and describes
          no real borrower.
        </p>
      </div>
    </div>
  );
}
