"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Clock } from "lucide-react";

import { NAV_GROUPS, STATUS_LABEL, itemsInGroup } from "@/lib/navigation";
import { INVESTIGATIONS, PROJECTS } from "@/lib/demo";
import { cn } from "@/lib/utils";

/**
 * Primary navigation.
 *
 * Every capability is listed, including those not yet finished, and each carries
 * an honest status. Hiding unbuilt areas would make the product look smaller
 * than it is; presenting them as finished would mislead. Naming them and marking
 * them does neither.
 */

const RECENT = [
  ...INVESTIGATIONS.slice(0, 2).map((i) => ({
    href: `/investigations/${i.id}`,
    label: i.title,
    kind: "Investigation",
  })),
  ...PROJECTS.slice(0, 2).map((p) => ({
    href: `/projects/${p.id}`,
    label: p.name,
    kind: "Project",
  })),
];

export function Sidebar() {
  const pathname = usePathname();

  return (
    <nav
      aria-label="Primary"
      className="flex h-full w-60 shrink-0 flex-col gap-5 overflow-y-auto border-r border-border bg-surface px-3 py-4"
    >
      {NAV_GROUPS.map((group) => (
        <div key={group}>
          <p className="px-3 pb-1.5 text-[10px] font-semibold uppercase tracking-[0.08em] text-text-muted">
            {group}
          </p>
          <ul className="space-y-px">
            {itemsInGroup(group).map((item) => {
              const active =
                item.href === "/"
                  ? pathname === "/"
                  : pathname === item.href || pathname.startsWith(`${item.href}/`);
              const Icon = item.icon;
              return (
                <li key={item.href}>
                  <Link
                    href={item.href}
                    aria-current={active ? "page" : undefined}
                    className={cn(
                      "group flex items-center gap-2.5 rounded-md px-3 py-1.5 text-sm transition-colors",
                      active
                        ? "bg-accent-muted font-medium text-accent"
                        : "text-text-secondary hover:bg-surface-hover hover:text-text-primary",
                    )}
                  >
                    <Icon className="size-4 shrink-0" aria-hidden />
                    <span className="truncate">{item.label}</span>
                    {item.status !== "live" && (
                      <span
                        className="ml-auto size-1.5 shrink-0 rounded-full bg-border-strong"
                        title={`${STATUS_LABEL[item.status]}${item.phase ? ` — ${item.phase}` : ""}`}
                        aria-hidden
                      />
                    )}
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>
      ))}

      <div className="mt-auto">
        <p className="flex items-center gap-1.5 px-3 pb-1.5 text-[10px] font-semibold uppercase tracking-[0.08em] text-text-muted">
          <Clock className="size-3" aria-hidden />
          Recent
        </p>
        <ul className="space-y-px">
          {RECENT.map((item) => (
            <li key={item.href}>
              <Link
                href={item.href}
                className="block rounded-md px-3 py-1.5 text-xs text-text-muted transition-colors hover:bg-surface-hover hover:text-text-secondary"
              >
                <span className="block truncate">{item.label}</span>
                <span className="text-[10px] text-text-muted/70">{item.kind}</span>
              </Link>
            </li>
          ))}
        </ul>
      </div>
    </nav>
  );
}
