"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { Badge } from "@/components/ui/badge";
import { NAV_GROUPS, STATUS_LABEL, itemsInGroup } from "@/lib/navigation";
import { cn } from "@/lib/utils";

/**
 * Primary navigation.
 *
 * Every capability is listed, including those not yet built, and each carries an
 * honest status. Hiding unbuilt areas would make the product look smaller than
 * it is; presenting them as finished would mislead. Naming them and marking them
 * does neither.
 */
export function Sidebar() {
  const pathname = usePathname();

  return (
    <nav
      aria-label="Primary"
      className="flex h-full w-60 shrink-0 flex-col gap-6 overflow-y-auto border-r border-border bg-surface px-3 py-5"
    >
      {NAV_GROUPS.map((group) => (
        <div key={group}>
          <p className="px-3 pb-2 text-[11px] font-semibold uppercase tracking-wider text-text-muted">
            {group}
          </p>
          <ul className="space-y-0.5">
            {itemsInGroup(group).map((item) => {
              const active = pathname === item.href;
              const Icon = item.icon;
              return (
                <li key={item.href}>
                  <Link
                    href={item.href}
                    aria-current={active ? "page" : undefined}
                    className={cn(
                      "group flex items-center gap-2.5 rounded-md px-3 py-2 text-sm transition-colors",
                      active
                        ? "bg-accent-muted font-medium text-accent"
                        : "text-text-secondary hover:bg-surface-hover hover:text-text-primary",
                    )}
                  >
                    <Icon className="size-4 shrink-0" aria-hidden />
                    <span className="truncate">{item.label}</span>
                    {item.status !== "live" && (
                      <span
                        className="ml-auto text-[10px] font-medium uppercase tracking-wide text-text-muted"
                        title={`${STATUS_LABEL[item.status]} — ${item.phase}`}
                      >
                        {item.status === "planned" ? "" : STATUS_LABEL[item.status]}
                      </span>
                    )}
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>
      ))}

      <div className="mt-auto px-3 pt-4">
        <Badge variant="outline" className="w-full justify-center">
          Phase 1 — Foundations
        </Badge>
      </div>
    </nav>
  );
}
