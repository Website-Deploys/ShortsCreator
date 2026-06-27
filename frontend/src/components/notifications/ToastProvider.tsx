"use client";

/**
 * Toast notifications.
 *
 * A small, accessible notification system: friendly, auto-dismissing messages
 * with optional actions. Used for upload completion, connection changes,
 * processing/queue events, and friendly, actionable errors. Exposed via the
 * `useToast` hook so any component can raise one.
 */
import { createContext, useCallback, useContext, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";

import { AlertIcon, CheckCircleIcon, XIcon } from "@/components/icons";

type ToastTone = "success" | "error" | "info";

interface ToastAction {
  label: string;
  onClick: () => void;
}

interface Toast {
  id: number;
  tone: ToastTone;
  title: string;
  description?: string;
  action?: ToastAction;
}

interface ToastInput {
  tone?: ToastTone;
  title: string;
  description?: string;
  action?: ToastAction;
  /** Auto-dismiss after this many ms (0 keeps it until dismissed). */
  durationMs?: number;
}

interface ToastContextValue {
  notify: (toast: ToastInput) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

const toneStyles: Record<ToastTone, { ring: string; icon: ReactNode }> = {
  success: {
    ring: "ring-green-400/30",
    icon: <CheckCircleIcon className="h-5 w-5 text-green-400" />,
  },
  error: { ring: "ring-red-400/30", icon: <AlertIcon className="h-5 w-5 text-red-400" /> },
  info: { ring: "ring-accent/30", icon: <CheckCircleIcon className="h-5 w-5 text-accent" /> },
};

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const counter = useRef(0);

  const dismiss = useCallback((id: number) => {
    setToasts((current) => current.filter((toast) => toast.id !== id));
  }, []);

  const notify = useCallback(
    ({ tone = "info", title, description, action, durationMs = 5000 }: ToastInput) => {
      const id = ++counter.current;
      setToasts((current) => [...current, { id, tone, title, description, action }]);
      if (durationMs > 0) {
        window.setTimeout(() => dismiss(id), durationMs);
      }
    },
    [dismiss],
  );

  const value = useMemo(() => ({ notify }), [notify]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div
        aria-live="polite"
        aria-relevant="additions"
        className="pointer-events-none fixed inset-x-0 bottom-0 z-50 flex flex-col items-center gap-3 p-4 sm:items-end sm:p-6"
      >
        {toasts.map((toast) => (
          <div
            key={toast.id}
            role="status"
            className={`pointer-events-auto w-full max-w-sm animate-[toast-in_180ms_ease-out] rounded-xl border border-white/10 bg-elevated p-4 shadow-2xl shadow-black/40 ring-1 ${toneStyles[toast.tone].ring}`}
          >
            <div className="flex items-start gap-3">
              <span className="mt-0.5 shrink-0">{toneStyles[toast.tone].icon}</span>
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium text-white">{toast.title}</p>
                {toast.description && (
                  <p className="mt-1 text-sm text-muted">{toast.description}</p>
                )}
                {toast.action && (
                  <button
                    type="button"
                    onClick={() => {
                      toast.action?.onClick();
                      dismiss(toast.id);
                    }}
                    className="mt-2 text-sm font-medium text-accent transition-colors hover:text-accent-strong"
                  >
                    {toast.action.label}
                  </button>
                )}
              </div>
              <button
                type="button"
                aria-label="Dismiss notification"
                onClick={() => dismiss(toast.id)}
                className="rounded-md p-1 text-muted transition-colors hover:bg-white/10 hover:text-white"
              >
                <XIcon className="h-4 w-4" />
              </button>
            </div>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastContextValue {
  const context = useContext(ToastContext);
  if (!context) {
    throw new Error("useToast must be used within a ToastProvider.");
  }
  return context;
}
