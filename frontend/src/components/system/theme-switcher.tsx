"use client";

import { Check, Moon, Sun } from "lucide-react";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { THEMES } from "@/lib/themes";
import { cn } from "@/lib/utils";

import { useTheme } from "./theme-provider";

/**
 * The Theme Gallery.
 *
 * Each card previews the theme's canvas, surface and accent, so the choice can
 * be made by looking rather than by guessing from a name.
 */
export function ThemeSwitcher() {
  const { theme, setTheme, ready } = useTheme();

  return (
    <Card>
      <CardHeader>
        <CardTitle>Theme</CardTitle>
        <CardDescription>
          Four themes, one interface. Colour changes; layout, typography, spacing and
          behaviour do not.
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-3 sm:grid-cols-2">
        {THEMES.map((option) => {
          const active = ready && theme === option.id;
          const ModeIcon = option.mode === "dark" ? Moon : Sun;
          return (
            <button
              key={option.id}
              type="button"
              onClick={() => setTheme(option.id)}
              aria-pressed={active}
              className={cn(
                "group flex flex-col gap-3 rounded-lg border p-4 text-left transition-colors",
                active
                  ? "border-accent bg-accent-muted"
                  : "border-border bg-surface hover:bg-surface-hover",
              )}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="flex items-center gap-2 text-sm font-medium text-text-primary">
                  <ModeIcon className="size-3.5 text-text-muted" aria-hidden />
                  {option.name}
                </span>
                {active && <Check className="size-4 text-accent" aria-hidden />}
              </div>

              {/* Preview swatches: canvas, surface, accent. */}
              <div
                className="flex h-12 overflow-hidden rounded-md border border-border"
                aria-hidden
              >
                {option.swatch.map((colour, i) => (
                  <div key={i} className="flex-1" style={{ backgroundColor: colour }} />
                ))}
              </div>

              <p className="text-xs leading-relaxed text-text-muted">{option.description}</p>
            </button>
          );
        })}
      </CardContent>
    </Card>
  );
}
