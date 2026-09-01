import * as React from "react";

import { cn } from "@/lib/utils";

const base =
  "w-full rounded-md border border-border bg-surface px-3 py-2 text-sm text-text-primary " +
  "placeholder:text-text-muted transition-colors focus:border-accent focus:outline-none " +
  "disabled:cursor-not-allowed disabled:opacity-50";

const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(
  ({ className, ...props }, ref) => (
    <input ref={ref} className={cn(base, "h-9", className)} {...props} />
  ),
);
Input.displayName = "Input";

const Textarea = React.forwardRef<
  HTMLTextAreaElement,
  React.TextareaHTMLAttributes<HTMLTextAreaElement>
>(({ className, ...props }, ref) => (
  <textarea ref={ref} className={cn(base, "min-h-20 resize-y", className)} {...props} />
));
Textarea.displayName = "Textarea";

const Select = React.forwardRef<
  HTMLSelectElement,
  React.SelectHTMLAttributes<HTMLSelectElement>
>(({ className, ...props }, ref) => (
  <select ref={ref} className={cn(base, "h-9 cursor-pointer pr-8", className)} {...props} />
));
Select.displayName = "Select";

function Label({ className, ...props }: React.LabelHTMLAttributes<HTMLLabelElement>) {
  return (
    <label
      className={cn("mb-1.5 block text-xs font-medium text-text-secondary", className)}
      {...props}
    />
  );
}

function Field({
  label,
  hint,
  children,
  className,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={className}>
      <Label>{label}</Label>
      {children}
      {hint && <p className="mt-1 text-xs leading-relaxed text-text-muted">{hint}</p>}
    </div>
  );
}

export { Input, Textarea, Select, Label, Field };
