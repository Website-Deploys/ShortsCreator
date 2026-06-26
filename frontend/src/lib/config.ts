/**
 * Client configuration, read from the environment.
 *
 * Centralising config access (rather than reading `process.env` throughout the
 * app) gives one place to validate and document it.
 */

/** Base URL of the Olympus backend API, without a trailing slash. */
export const API_BASE_URL: string = (
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000"
).replace(/\/$/, "");

/** Prefix for all versioned API routes. */
export const API_V1 = `${API_BASE_URL}/api/v1`;
