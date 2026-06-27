/** A surface container used to group related content. */
import type { HTMLAttributes, ReactNode } from "react";

interface CardProps extends HTMLAttributes<HTMLDivElement> {
  children: ReactNode;
  /** Adds a subtle hover lift for interactive cards. */
  interactive?: boolean;
}

export function Card({ children, interactive = false, className = "", ...rest }: CardProps) {
  return (
    <div
      className={`rounded-xl border border-white/10 bg-surface p-6 ${
        interactive ? "transition-colors hover:border-white/20 hover:bg-white/[0.02]" : ""
      } ${className}`}
      {...rest}
    >
      {children}
    </div>
  );
}
