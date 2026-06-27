/** Accessible button primitive with variants, sizes, and a loading state. */
import type { ButtonHTMLAttributes, ReactNode } from "react";

import { SpinnerIcon } from "@/components/icons";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "primary" | "secondary" | "ghost" | "danger";
  size?: "sm" | "md";
  loading?: boolean;
  children: ReactNode;
}

const VARIANTS: Record<string, string> = {
  primary: "bg-accent text-white hover:bg-accent-strong",
  secondary: "bg-elevated text-white border border-white/10 hover:bg-white/5",
  ghost: "text-muted hover:bg-white/5 hover:text-white",
  danger: "bg-red-500/10 text-red-300 border border-red-500/20 hover:bg-red-500/20",
};

const SIZES: Record<string, string> = {
  sm: "px-3 py-1.5 text-sm gap-1.5",
  md: "px-5 py-2.5 text-sm gap-2",
};

export function Button({
  variant = "primary",
  size = "md",
  loading = false,
  className = "",
  children,
  disabled,
  ...rest
}: ButtonProps) {
  return (
    <button
      className={`inline-flex items-center justify-center rounded-lg font-medium transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-ink disabled:cursor-not-allowed disabled:opacity-50 ${VARIANTS[variant]} ${SIZES[size]} ${className}`}
      disabled={disabled || loading}
      aria-busy={loading}
      {...rest}
    >
      {loading && <SpinnerIcon className="h-4 w-4 animate-spin" />}
      {children}
    </button>
  );
}
