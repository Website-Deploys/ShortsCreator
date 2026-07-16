"use client";

/**
 * Root-level error boundary.
 *
 * `app/error.tsx` only catches errors thrown *within* a route segment - it does
 * NOT catch errors thrown in the root layout or the client providers (the Query
 * client, toast provider, connectivity watcher). Without this file such an error
 * would render a blank page. `global-error.tsx` is the last line of defence: it
 * replaces the entire document with a calm, recoverable screen, so the app can
 * never white-screen during a live session.
 *
 * It must render its own <html>/<body> because it substitutes the root layout.
 */
import { useEffect } from "react";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // Surface the failure for diagnosis (also visible in server logs via digest).
    console.error(error);
  }, [error]);

  return (
    <html lang="en">
      <body
        style={{
          minHeight: "100vh",
          margin: 0,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          gap: "1.25rem",
          padding: "1.5rem",
          textAlign: "center",
          fontFamily:
            "ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif",
          background: "#0a0a0b",
          color: "#fafafa",
        }}
      >
        <div
          aria-hidden
          style={{
            display: "flex",
            height: "3rem",
            width: "3rem",
            alignItems: "center",
            justifyContent: "center",
            borderRadius: "9999px",
            background: "rgba(239, 68, 68, 0.1)",
            fontSize: "1.5rem",
          }}
        >
          !
        </div>
        <h1 style={{ fontSize: "1.5rem", fontWeight: 600, margin: 0 }}>Something went wrong</h1>
        <p style={{ maxWidth: "24rem", color: "#a1a1aa", margin: 0, lineHeight: 1.5 }}>
          An unexpected error occurred. Your projects are safe. Try again, and if it persists
          reload the page.
        </p>
        <button
          type="button"
          onClick={reset}
          style={{
            cursor: "pointer",
            borderRadius: "0.5rem",
            border: "none",
            background: "#6366f1",
            color: "#fff",
            padding: "0.625rem 1.25rem",
            fontSize: "0.875rem",
            fontWeight: 600,
          }}
        >
          Try again
        </button>
      </body>
    </html>
  );
}
