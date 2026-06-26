"use client";

/**
 * Client-side providers.
 *
 * Wraps the app in a TanStack Query client. The client is created once per
 * browser session (via `useState`) so it is not recreated on re-render, which
 * would discard the cache.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

export function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            refetchOnWindowFocus: false,
            staleTime: 10_000,
          },
        },
      }),
  );

  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
