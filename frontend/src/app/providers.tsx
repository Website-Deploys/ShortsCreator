"use client";

/**
 * Client-side providers.
 *
 * Wraps the app in a TanStack Query client (created once per session so the
 * cache survives re-renders), the toast notification system, and a connectivity
 * watcher that surfaces online/offline changes.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

import { ConnectivityWatcher } from "@/components/ConnectivityWatcher";
import { ToastProvider } from "@/components/notifications/ToastProvider";

export function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: { refetchOnWindowFocus: false, staleTime: 10_000, retry: 1 },
        },
      }),
  );

  return (
    <QueryClientProvider client={client}>
      <ToastProvider>
        <ConnectivityWatcher />
        {children}
      </ToastProvider>
    </QueryClientProvider>
  );
}
