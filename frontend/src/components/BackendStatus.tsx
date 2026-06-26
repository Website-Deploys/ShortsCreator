"use client";

/**
 * A tiny indicator showing whether the frontend can reach the backend.
 *
 * This is a real, working call against the implemented `GET /system/info`
 * endpoint - it demonstrates the full frontend -> backend wiring today, before
 * any business endpoints exist.
 */
import { useSystemInfo } from "@/lib/queries";

export function BackendStatus() {
  const { data, isLoading, isError } = useSystemInfo();

  const tone = isError ? "bg-red-400" : isLoading ? "bg-yellow-400" : "bg-green-400";
  const label = isError
    ? "backend offline"
    : isLoading
      ? "connecting"
      : `backend v${data?.version}`;

  return (
    <span className="flex items-center gap-2 text-xs text-muted" title="Backend connectivity">
      <span className={`inline-block h-2 w-2 rounded-full ${tone}`} aria-hidden />
      {label}
    </span>
  );
}
