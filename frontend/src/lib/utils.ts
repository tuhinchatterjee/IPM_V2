import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/**
 * Merge Tailwind class names, letting later classes win over earlier ones.
 *
 * Without this, `cn("p-2", "p-4")` would emit both and the winner would depend
 * on stylesheet order. This is the standard shadcn/ui helper and every component
 * in the codebase uses it.
 */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
