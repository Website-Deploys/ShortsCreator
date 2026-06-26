/** A surface container used to group related content. */
import type { ReactNode } from "react";

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <div className={`rounded-xl border border-white/10 bg-surface p-6 ${className}`}>
      {children}
    </div>
  );
}
