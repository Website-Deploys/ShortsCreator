"use client";

/**
 * Watches the browser's online/offline status and raises friendly toasts.
 *
 * Renders nothing - it exists purely to surface connection changes as
 * notifications ("Connection lost" / "Back online").
 */
import { useEffect, useRef } from "react";

import { useToast } from "@/components/notifications/ToastProvider";

export function ConnectivityWatcher() {
  const { notify } = useToast();
  const wasOffline = useRef(false);

  useEffect(() => {
    const onOffline = () => {
      wasOffline.current = true;
      notify({
        tone: "error",
        title: "Connection lost",
        description: "You appear to be offline. We'll keep your work safe.",
        durationMs: 0,
      });
    };
    const onOnline = () => {
      if (wasOffline.current) {
        wasOffline.current = false;
        notify({ tone: "success", title: "Back online", description: "Connection restored." });
      }
    };
    window.addEventListener("offline", onOffline);
    window.addEventListener("online", onOnline);
    return () => {
      window.removeEventListener("offline", onOffline);
      window.removeEventListener("online", onOnline);
    };
  }, [notify]);

  return null;
}
