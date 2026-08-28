"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { useRole } from "@/components/system/role-switcher";
import { NAV_GROUPS, STATUS_LABEL, itemsInGroup } from "@/lib/navigation";
import { cn } from "@/lib/utils";

import { useNavState } from "./nav-state";

/**
 * Primary navigation.
 *
 * Two states. Expanded shows icons and labels; collapsed shows icons only and
 * gives roughly 180px back to the workspace, which is the difference between a
 * readable Trace canvas and a cramped one.
 *
 * Every capability is listed, including those not yet finished, and each carries
 * an honest status. Hiding unbuilt areas would make the product look smaller
 * than it is; presenting them as finished would mislead. Naming them and marking
 * them does neither. In the collapsed state the status dot is dropped rather
 * than crowded against the icon — the tooltip still carries it.
 */
export function Sidebar() {
  const pathname = usePathname();
  const { collapsed } = useNavState();
  // A few capabilities are role-scoped. Hiding a link is courtesy rather than
  // security — every endpoint behind Agent Operations checks the role itself —
  // but a sidebar full of things the reader cannot open is its own problem.
  const { role } = useRole();

  return (
    <nav
      aria-label="Primary"
      data-collapsed={collapsed ? "true" : "false"}
      className={cn(
        "flex h-full shrink-0 flex-col gap-6 overflow-y-auto overflow-x-hidden border-r border-border bg-surface py-5 transition-[width] duration-200",
        collapsed ? "w-[60px] px-2" : "w-[212px] px-3",
      )}
    >
      {NAV_GROUPS.filter((group) => itemsInGroup(group, role).length > 0).map(
        (group) => (
        <div key={group}>
          {collapsed ? (
            // A heading rendered at icon width is unreadable, so the group is
            // marked with a rule instead and kept for screen readers.
            <>
              <span className="sr-only">{group}</span>
              <div className="mx-auto mb-2 h-px w-5 bg-border" aria-hidden />
            </>
          ) : (
            <p className="px-2.5 pb-2 text-[10px] font-medium uppercase tracking-[0.1em] text-text-muted">
              {group}
            </p>
          )}
          <ul className="space-y-0.5">
            {itemsInGroup(group, role).map((item) => {
              const active =
                item.href === "/"
                  ? pathname === "/"
                  : pathname === item.href || pathname.startsWith(`${item.href}/`);
              const Icon = item.icon;
              const hint =
                item.status === "live"
                  ? item.label
                  : `${item.label} — ${STATUS_LABEL[item.status]}${item.phase ? `: ${item.phase}` : ""}`;
              return (
                <li key={item.href}>
                  <Link
                    href={item.href}
                    aria-current={active ? "page" : undefined}
                    title={hint}
                    className={cn(
                      "group flex items-center rounded-md text-[13px] transition-colors",
                      collapsed
                        ? "h-9 w-9 justify-center"
                        : "gap-2.5 px-2.5 py-[7px]",
                      active
                        ? "bg-accent-muted font-medium text-accent"
                        : "text-text-secondary hover:bg-surface-hover hover:text-text-primary",
                    )}
                  >
                    <Icon className="size-[15px] shrink-0" aria-hidden />
                    {!collapsed && (
                      <>
                        <span className="truncate">{item.label}</span>
                        {item.status !== "live" && (
                          <span
                            className="ml-auto size-1 shrink-0 rounded-full bg-border-strong"
                            aria-hidden
                          />
                        )}
                      </>
                    )}
                    {collapsed && <span className="sr-only">{item.label}</span>}
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>
        ),
      )}
    </nav>
  );
}
