/**
 * Next.js configuration for the Olympus web client.
 *
 * - `reactStrictMode` surfaces subtle bugs early.
 * - The backend base URL is read from the environment at build/runtime via
 *   `NEXT_PUBLIC_API_BASE_URL` (see `src/lib/config.ts`); no rewrites are needed
 *   for the MVP since the client calls the API directly.
 */

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
};

export default nextConfig;
