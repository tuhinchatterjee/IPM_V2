"use client";

import * as React from "react";
import { Check, Palette } from "lucide-react";

import { THEMES } from "@/lib/themes";
import { cn } from "@/lib/utils";

import { useTheme } from "./theme-provider";

/**
 * The one-click theme switcher, in the application header.
 *
 * One click opens it, one click applies. No dialog, no settings page, no
 * reload: the theme is a `data-theme` attribute on <html> and all eight palettes
 * are already in the stylesheet, so switching is a single attribute change.
 *
 * Eight is enough that an undivided list reads as a wall, so they are grouped by
 * light and dark — which is the axis anyone picking a theme is actually deciding
 * on.
 *
 * The full gallery — with descriptions and larger previews — stays in Settings.
 * This is the version you reach for when the room lights change.
 */
export function ThemeMenu({ className }: { className?: string }) {
  const { theme, setTheme, ready } = useTheme();
  const [open, setOpen] = React.useState(false);
  const container = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    if (!open) return;
    function onPointerDown(event: MouseEvent) {
      if (!container.current?.contains(event.target as Node)) setOpen(false);
    }
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const active = THEMES.find((t) => t.id === theme) ?? THEMES[0];

  return (
    <div ref={container} className={cn("relative", className)}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
        title="Change theme"
        className={cn(
          "flex h-8 items-center gap-2 rounded-md border border-border px-2.5 text-xs",
          "text-text-secondary transition-colors hover:bg-surface-hover hover:text-text-primary",
          open && "bg-surface-hover text-text-primary",
        )}
      >
        <Palette className="size-3.5" aria-hidden />
        <span className="hidden md:inline">
          {ready ? active.name : "Theme"}
        </span>
        {/* The active palette, shown as three squares — recognisable at a glance
            even when the label is hidden on a narrow window. */}
        <span
          className="flex overflow-hidden rounded-[3px] border border-border"
          aria-hidden
        >
          {active.swatch.map((colour, i) => (
            <span
              key={i}
              className="size-2.5"
              style={{ backgroundColor: colour }}
            />
          ))}
        </span>
      </button>

      {open && (
        <div
          role="menu"
          className="absolute right-0 z-50 mt-1.5 w-64 overflow-hidden rounded-lg border border-border bg-surface-raised shadow-xl"
        >
          <ul className="p-1">
            {(["light", "dark"] as const).flatMap((mode) => [
              <li
                key={`heading-${mode}`}
                className="px-2 pb-1 pt-2 text-[10px] font-medium uppercase tracking-[0.12em] text-text-muted"
              >
                {mode === "light" ? "Light" : "Dark"}
              </li>,
              ...THEMES.filter((option) => option.mode === mode).map(
                (option) => {
                  const selected = ready && theme === option.id;
                  return (
                    <li key={option.id}>
                      <button
                        type="button"
                        role="menuitemradio"
                        aria-checked={selected}
                        onClick={() => {
                          setTheme(option.id);
                          setOpen(false);
                        }}
                        className={cn(
                          "flex w-full items-center gap-2.5 rounded-md px-2 py-2 text-left transition-colors",
                          selected
                            ? "bg-accent-muted"
                            : "hover:bg-surface-hover",
                        )}
                      >
                        <span
                          className="flex shrink-0 overflow-hidden rounded-[3px] border border-border"
                          aria-hidden
                        >
                          {option.swatch.map((colour, i) => (
                            <span
                              key={i}
                              className="size-3.5"
                              style={{ backgroundColor: colour }}
                            />
                          ))}
                        </span>
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-xs font-medium text-text-primary">
                            {option.name}
                          </span>
                        </span>
                        {selected && (
                          <Check
                            className="size-3.5 shrink-0 text-accent"
                            aria-hidden
                          />
                        )}
                      </button>
                    </li>
                  );
                },
              ),
            ])}
          </ul>
          <p className="border-t border-border px-3 py-2 text-[11px] leading-relaxed text-text-muted">
            Colour changes. Layout, spacing and behaviour do not.
          </p>
        </div>
      )}
    </div>
  );
}
