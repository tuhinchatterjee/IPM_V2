"use client";

import * as React from "react";
import { AlertTriangle, RotateCcw } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

interface Props {
  children: React.ReactNode;
  /** Name of the area being protected, shown in the message. */
  area?: string;
}

interface State {
  error: Error | null;
}

/**
 * Catches a rendering error in one area so it does not blank the whole page.
 *
 * A single failing panel taking down the entire application is the difference
 * between "one chart is broken" and "the product crashed" in front of an
 * audience. Each major area is wrapped separately.
 *
 * Must be a class component: React only supports error boundaries this way.
 */
export class ErrorBoundary extends React.Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error("[IPM] Render error", error, info.componentStack);
  }

  reset = () => this.setState({ error: null });

  render() {
    if (!this.state.error) return this.props.children;

    return (
      <Card className="border-negative/40">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-negative">
            <AlertTriangle className="size-4" aria-hidden />
            {this.props.area ? `${this.props.area} could not be displayed` : "Something went wrong"}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-text-secondary">
            The rest of the application is unaffected. The technical detail has been
            written to the browser console.
          </p>
          <code className="block overflow-x-auto rounded-md border border-border bg-surface-sunken p-3 font-mono text-xs text-text-muted">
            {this.state.error.message}
          </code>
          <Button variant="outline" size="sm" onClick={this.reset}>
            <RotateCcw aria-hidden />
            Try again
          </Button>
        </CardContent>
      </Card>
    );
  }
}
